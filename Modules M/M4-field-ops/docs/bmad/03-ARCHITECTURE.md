# 03-ARCHITECTURE — MODULE M4 (FIELD OPS)

> Architecte : Qwen3.7-Max (prose, rôle respecté ; Kimi-K3 défaillant, rotation journalisée).
> Décision structurante : OUTBOX = maillon COMPOSITE du registre unique hash-chaîné —
> l'atomicité de CA-M4-11 se prouve par l'indivisibilité du maillon, la consommation aval
> par curseur idempotent.


## 1. Arborescence du module

Le paquet m4_field_ops est découpé en treize modules isolés, chacun portant une responsabilité unique pour faciliter la preuve en CI et éviter les dépendances circulaires.

Le module encodage fournit l'encodage canonique injectif par préfixage de longueur pour dériver les identifiants et les empreintes.
Le module horodatage valide la conformité ISO-8601 avec fuseau explicite et rejette toute ambiguïté temporelle.
Le module verdicts catalogue les identifiants stables de rejet et de succès propres à M4.
Le module registre implémente la structure append-only hash-chaînée pour les interventions et l'outbox.
Le module contrats valide structurellement le contrat gelé du lead qualifié et les entités internes.
Le module frontieres détecte les champs interdits tels que les prix ou les engagements financiers.
Le module etats modélise l'énuméré fermé des six statuts et la table des transitions conditionnées.
Le module cedule applique les règles pures de tri pour générer la planification déterministe.
Le module pointage traite les événements de terrain en vérifiant la cohérence temporelle et géographique.
Le module ecarts gère la détection des anomalies et la file d'attente de revue.
Le module outbox matérialise l'émission transactionnelle du Work Completion Trigger.
Le module digest agrège les données quotidiennes de manière déterministe et hash-chaînée.
Le module fixtures_garde fournit les données fictives pour les tests, explicitement marquées comme telles.

## 2. Schémas de données

L'entité Intervention représente le cycle de vie complet d'un travail terrain. Elle contient l'identifiant unique, la référence au lead, le technicien assigné, la ville tokenisée, le type de travaux, la fenêtre horaire prévue, le statut actuel, et la liste ordonnée des pointages. Aucun champ financier n'y figure.

L'entité Pointage capture l'action du technicien. Elle inclut l'identifiant du pointage, la référence à l'intervention, le type d'action (arrivée ou départ), l'horodatage ISO-8601 avec fuseau, le fix GPS (latitude et longitude), et l'attestation d'appareil simulée.

L'entité DemandeRevue matérialise un écart. Elle stocke l'identifiant de la revue, la référence à l'intervention, la version prévue des faits, la version déclarée par le technicien, le motif de l'écart, et le statut de l'arbitrage (en attente, validé, rejeté).

L'entité EvenementOutbox représente le Work Completion Trigger. Elle porte l'identifiant de l'événement, la référence à l'intervention, le lead, le technicien, l'horodatage de complétion, le fix GPS final, la durée réelle, le booléen d'écart signalé, la référence à la revue, le hash du maillon, la liste des consommateurs cibles, et le devis nul en version un. Le lien client y est strictement tokenisé.

## 3. Interfaces et contrats

L'interface de planification reçoit une liste d'interventions prêtes, une liste de techniciens et des fenêtres horaires. Elle retourne une cédule ordonnée sans jamais consulter d'horloge système.

L'interface de pointage reçoit un événement de terrain. Elle valide le format de l'horodatage, vérifie que la transition d'état est légale, compare le fix GPS à la ville tokenisée, et retourne un accusé de réception ou un verdict de rejet.

L'interface de revue permet à l'administrateur de valider ou rejeter une demande d'arbitrage. Elle déclenche soit la complétion avec émission du Work Completion Trigger, soit l'annulation de l'intervention.

L'interface de digest prend une date cible et retourne un document synthétique hash-chaîné listant les interventions terminées, celles en revue, et la volumétrie de la file d'attente.

## 4. Décisions d'architecture tranchées

Premièrement, le découpage en treize modules isolés garantit qu'une responsabilité unique est assignée à chaque fichier, prévenant ainsi les effets de bord et facilitant la vérification unitaire.

Deuxièmement, le patron outbox en mode ombre utilise un registre hash-chaîné unique où le maillon composite porte simultanément la transition d'état et l'événement de cascade. L'atomicité est prouvée par l'indivisibilité du maillon, et les modules aval consomment l'événement via un curseur idempotent, éliminant tout risque de désynchronisation.

Troisièmement, le schéma du contrat Work Completion Trigger est figé et inclut un champ devis identifiant explicitement nul en version un. Ce choix garantit que les modules aval reçoivent une structure immuable et prévisible, tout en respectant la Loi 25 par la tokenisation du lien client.

Quatrièmement, la cédule déterministe est générée par un tri multi-critères strict appliquant l'ordre alphabétique de la ville tokenisée, puis le type de travaux, puis l'identifiant du lead. L'absence totale d'horloge assure que deux appels identiques produisent exactement la même sortie.

Cinquièmement, la tokenisation du lien client est réalisée par l'encodage canonique injectif d'un sel fourni par l'appelant, concaténé à l'identifiant du lead, puis haché. Cette méthode utilise uniquement la bibliothèque standard et évite toute cryptographie exotique.

Sixièmement, les patrons de M2 sont copiés et adaptés avec le préfixe M4, et aucun import inter-modules n'est autorisé. Cette séparation stricte des identités de paquet prévient le couplage fort et permet une évolution indépendante.

Septièmement, les invariants de CI interdisent tout réseau, toute horloge interne, et tout modèle de langage, tout en imposant des énumérés fermés et un fuseau horaire obligatoire. Ces contraintes garantissent la reproductibilité absolue et préviennent les dérives temporelles.

## 4 bis. Énuméré des états (repris VERBATIM du PRD — cohérence vérifiée par gate)

L'énuméré fermé des états de l'intervention est strictement celui du PRD : planifiee, en_route,
sur_site, en_revue, terminee, annulee. Toute divergence entre les deux documents est un écart
bloquant détecté par verif_coherence.py.

## 5. Anti-dérive et stratégie de preuve

La story S001 prouve la propriété d'injectivité de l'encodage canonique, garantissant qu'aucune collision d'identifiant n'est possible.

La story S002 prouve l'immutabilité du registre append-only, vérifiée par la validation de la chaîne de hash depuis le maillon de tête jusqu'à la racine.

La story S003 prouve l'étanchéité des frontières de vérité, démontrée par le rejet systématique de tout contrat contenant des champs financiers ou des engagements interdits.

La story S004 prouve la fermeture de la machine à états, vérifiée par le rejet explicite de toute transition non documentée dans la table officielle.

La story S005 prouve le déterminisme de la cédule, démontré par l'exécution de deux appels identiques produisant une sortie strictement égale.

La story S006 prouve la rigueur temporelle et géographique du pointage, vérifiée par le rejet des horodatages sans fuseau et la détection des incohérences de localisation.

La story S007 prouve la transparence des écarts, démontrée par la conservation intacte des deux versions des faits dans la file de revue, sans jamais d'écrasement silencieux.

La story S008 prouve l'atomicité de la cascade du Work Completion Trigger, vérifiée par la présence corrélée du maillon de transition et de l'événement outbox dans le registre unique.

La story S009 prouve l'indépendance temporelle du digest quotidien, démontrée par l'absence d'appel à l'horloge système et la reproductibilité du hash de synthèse.
