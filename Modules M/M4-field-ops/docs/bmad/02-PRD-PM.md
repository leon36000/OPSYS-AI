# PRD PM — MODULE M4 (FIELD OPS)

> Arbitrage Orchestrateur (post-gate verif_coherence) : les mentions « (partiel) » fragmentaient
> cinq CA sur deux stories chacun — un CA sans propriétaire unique n'est prouvé par personne
> (leçon M2). Propriétaires tranchés : CA-M4-03->S002, CA-M4-08 et CA-M4-12->S006 (la logique y
> vit, S007 fournit la mécanique de file), CA-M4-11->S008, CA-M4-14->S009. Le gate a aussi révélé
> que l'INJECTIVITÉ n'était portée par aucun CA : CA-M4-18 créé, porté par S001.

Rédigé par : PM BMAD | Statut : PROPOSÉ | Date : 2025-01-XX

## 1. Personas

Le technicien terrain consulte chaque matin sa cédule personnelle, filtrée par date et par ville. Il attend de M4 une liste claire de ses interventions planifiées avec l'identifiant du lead, le type de travaux, la ville tokenisée, et la fenêtre horaire assignée. Il pointe son arrivée sur site et son départ via un événement local signé capturant l'horodatage, le fix GPS, et l'attestation d'appareil. Il ne voit jamais de prix, de montant facturé, ni de calcul de rentabilité. En cas d'écart entre le prévu et le réalisé, il déclare sa version des faits et le système bascule l'intervention en revue sans jamais l'accuser de fraude.

Le répartiteur ou l'administrateur supervise l'ensemble des interventions actives, arbitre les écarts via la file d'attente de revue, et consulte le digest quotidien des interventions en attente de complétion ou bloquées en revue depuis plus de vingt-quatre heures simulées. Il assigne les techniciens aux interventions planifiées et valide ou rejette les demandes de revue. Il ne reçoit jamais de chiffre financier ni de calcul de marge.

Nathan, propriétaire, reçoit un digest synthétique horodaté et hash-chaîné listant les interventions complétées de la journée, les interventions en revue, et la volumétrie de la file d'attente. Nathan ne reçoit jamais de prix, de date d'exécution future non confirmée, ni de donnée personnelle client en clair.

Les six modules aval (M6, M5, M2, M7, M8, M10) consomment le Work Completion Trigger comme signal de déclenchement de leurs workflows respectifs. Ils ne reçoivent que l'événement de cascade, jamais l'état interne du registre M4.

## 2. Parcours principaux

(a) Planification d'une intervention. M2 émet un lead ayant franchi la readiness gate. M4 valide le contrat gelé, vérifie l'absence de champs interdits (prix, montant, date ferme imposée), inscrit l'intervention au statut planifiee dans le registre append-only hash-chaîné, et retourne un accusé de réception portant l'intervention_id et le hash du maillon. L'intervention reste planifiee jusqu'à l'assignation d'un technicien et d'une fenêtre horaire, générée de manière déterministe par les règles pures de cédule.

(b) Pointage terrain. Le technicien déclenche un événement de pointage (arrivée sur site ou départ) en fournissant un horodatage ISO-8601 avec fuseau explicite, un fix GPS, et une attestation d'appareil. M4 valide la transition d'état autorisée par la machine à états, vérifie la cohérence minimale du fix GPS avec la ville tokenisée de l'intervention, et inscrit le pointage comme maillon chaîné au registre. Si le pointage est incohérent (GPS hors périmètre, horodatage antérieur au précédent, transition illégale), l'intervention passe en en_revue et une demande d'arbitrage est créée.

(c) Complétion et cascade WCT. Lorsque le technicien pointe son départ final et que tous les pointages sont cohérents, M4 transitionne l'intervention vers terminee, calcule la durée réelle à partir des pointages, et émet le Work Completion Trigger dans l'outbox transactionnel. L'outbox garantit que l'événement de cascade et le changement d'état sont atomiques : en cas d'interruption, la reprise intégrale est assurée. Les six modules aval consomment l'événement de manière idempotente.

(d) Gestion des écarts. Si un écart est détecté entre le prévu et le réalisé (durée, périmètre, matériaux déclarés), l'intervention passe en en_revue. Les deux versions des faits (prévue et déclarée) sont présentées à l'administrateur dans la file pending_review. M4 ne procède jamais à un écrasement silencieux. L'administrateur valide ou rejette l'écart, ce qui déclenche soit la complétion normale avec WCT, soit l'annulation de l'intervention.

## 3. Périmètre v1 vs Roadmap

Sont dans le périmètre v1, prouvables en CI Python mode ombre (stdlib + PyYAML, zéro réseau, zéro horloge interne) : le registre append-only hash-chaîné des interventions, la machine à états fermée, la cédule déterministe par règles pures, le pointage simulé acceptant fix GPS et horodatage fournis par l'appelant (fixtures avec fictif: true), la gestion des écarts avec file pending_review, le Work Completion Trigger matérialisé par l'outbox append-only, et le digest quotidien déterministe.

Sont explicitement repoussés en phase GATED/T3 : le routage routier réel (API VRP ou self-hosted), l'API météo pour validation des conditions terrain, le temps réel WebSocket/push pour la mise à jour dynamique de la cédule, le polling GPS matériel réel, l'attestation d'appareil cryptographique réelle, l'envoi de notifications push aux techniciens, et l'intégration effective avec M3 (devis accepté comme champ optionnel gelé ultérieurement).

## 4. Enum des états de l'intervention

L'énuméré fermé des états de l'intervention est tranché ainsi : planifiee, en_route, sur_site, en_revue, reportee, terminee, annulee. L'état reportee couvre le report terrain quel qu'en soit le motif — enum fermé de motifs : client_absent, meteo, decision_admin — et retourne vers planifiee lors de la re-cédule.

Écarts par rapport à la proposition de l'analyste : en_cours est renommé sur_site pour lever l'ambiguïté entre le transit et le travail effectif sur le lieu d'intervention ; completed_pending_review est renommé en_revue pour assurer la cohérence lexicale avec le registre pending_review et éviter le mélange anglais-français dans les identifiants d'état.

Table des transitions conditionnées :
- planifiee vers en_route : conditionnée à l'assignation effective d'un technicien et au pointage de départ du dépôt.
- en_route vers sur_site : conditionnée au pointage d'arrivée sur site avec fix GPS cohérent.
- sur_site vers en_revue : conditionnée à la détection d'un écart ou à une anomalie de pointage.
- sur_site vers terminee : conditionnée au pointage de départ final sans écart détecté.
- en_revue vers terminee : conditionnée à la validation humaine de l'écart.
- en_revue vers annulee : conditionnée au rejet humain de l'écart.
- planifiee vers annulee : conditionnée à une décision administrative avant tout pointage.
- planifiee ou en_route vers reportee : conditionnée à un motif du enum fermé (client_absent, meteo, decision_admin) ; reportee vers planifiee lors de la re-cédule ; reportee vers annulee sur décision administrative.
- en_route vers annulee : conditionnée à une annulation client ou administrative pendant le déplacement (le pointage de départ reste au registre).
- en_revue vers sur_site : conditionnée à la résolution d'une anomalie de pointage par l'administrateur, l'intervention reprend.
- Toute autre transition est illégale et rejetée avec le verdict REJ-TRANSITION-ILLEGALE.

## 5. Contrat du Work Completion Trigger

Le contrat d'événement de cascade est nommé WorkCompletionTriggerV1. Ses champs sont les suivants, tous obligatoires sauf mention contraire :

- wct_id : identifiant unique de l'événement de cascade, dérivé par encodage canonique injectif.
- intervention_id : référence à l'intervention complétée dans le registre M4.
- lead_id : référence au lead d'origine tel que reçu de M2.
- technicien_id : identifiant du technicien ayant réalisé l'intervention.
- horodatage_completion : horodatage ISO-8601 avec fuseau explicite du dernier pointage valide.
- fix_gps_completion : latitude et longitude du dernier pointage valide.
- duree_reelle_minutes : durée effective en minutes calculée déterministement depuis les pointages d'arrivée et de départ.
- ecart_signale : booléen indiquant si un écart a été détecté et validé par revue humaine.
- revue_id : référence vers la demande de revue si ecart_signale est vrai, champ nul sinon.
- hash_maillon : empreinte sha256 du maillon de registre correspondant à la transition vers terminee.
- consommateurs_cibles : liste énumérée des six modules aval (M6, M5, M2, M7, M8, M10).
- devis_id : identifiant du devis M3 accepté, champ optionnel comblé par un identifiant nul en v1, en attente de l'implémentation de M3.

## 6. Critères d'acceptation

CA-M4-01 : Le système refuse toute inscription d'intervention si le lead sous-jacent n'a pas franchi la readiness gate M2, vérifié par le rejet explicite avec le verdict REJ-READINESS-NON-FRANCHIE.

CA-M4-02 : Le système refuse toute intervention dont le contrat d'entrée contient un champ interdit (prix, montant, date ferme imposée, engagement financier), vérifié par le rejet explicite avec le verdict REJ-FRONTIERE-VIOLEE.

CA-M4-03 : Le système inscrit toute intervention acceptée dans le registre append-only hash-chaîné avec le statut initial planifiee, vérifié par la lecture du maillon de tête et la validation de la chaîne de hash.

CA-M4-04 : Le système refuse toute transition d'état non prévue dans la table des transitions conditionnées, vérifié par le rejet explicite avec le verdict REJ-TRANSITION-ILLEGALE.

CA-M4-05 : Le système génère la cédule de manière déterministe à partir des données fournies par l'appelant, vérifié par l'exécution de deux appels identiques produisant exactement la même sortie.

CA-M4-06 : Le système accepte un pointage uniquement si l'horodatage est au format ISO-8601 avec fuseau explicite, vérifié par le rejet de tout horodatage sans fuseau ou mal formé.

CA-M4-07 : Le système refuse un pointage dont l'horodatage est antérieur au dernier pointage enregistré pour la même intervention, vérifié par le rejet explicite avec le verdict REJ-HORODATAGE-ANTERIEUR.

CA-M4-08 : Le système transitionne automatiquement l'intervention vers en_revue si le fix GPS du pointage est incohérent avec la ville tokenisée de l'intervention, vérifié par la présence d'une demande d'arbitrage dans la file pending_review.

CA-M4-09 : Le système ne procède jamais à un écrasement silencieux d'un écart, vérifié par la conservation des deux versions (prévue et déclarée) dans la demande de revue.

CA-M4-10 : Le système émet le Work Completion Trigger dans l'outbox transactionnel uniquement lorsque l'intervention atteint le statut terminee, vérifié par la présence de l'événement dans l'outbox et l'absence d'événement pour tout statut intermédiaire.

CA-M4-11 : Le système écrit la transition vers terminee et l'événement WCT par UNE SEULE opération d'ajout au registre (maillon composite) : il n'existe par construction aucun état intermédiaire observable. Vérifié par trois moyens déterministes : le balayage du registre entier après scénarios (tout maillon terminee porte un WCT complet, aucun WCT hors maillon terminee) ; l'inspection statique qu'aucun chemin de code n'écrit la transition et l'événement en deux ajouts ; et un CONSOMMATEUR DE RÉFÉRENCE in-memory LIVRÉ PAR M4 dont la resoumission du curseur est idempotente (relire depuis un curseur antérieur ne produit aucun double effet). La preuve par injection de panne réelle est GATED (hors CI Python), actée.

CA-M4-12 : Le système refuse tout pointage si aucune intervention n'est au statut en_route ou sur_site pour le technicien concerné, vérifié par le rejet explicite avec le verdict REJ-PUNCH-SANS-INTERVENTION.

CA-M4-13 : Le système tokenise systématiquement le lien vers le client final dans tout événement de cascade, vérifié par l'absence d'adresse résidentielle en clair dans le WCT et les événements outbox.

CA-M4-14 : Le système expose dans le digest quotidien la volumétrie de la file pending_review, vérifié par la présence du champ count_pending_review dans le digest hash-chaîné.

CA-M4-15 : Le système n'infère jamais l'heure à partir de l'horloge ambiante du serveur, vérifié par l'absence de tout appel à une fonction d'horloge système dans le code de M4 et par l'exigence de fuseau explicite dans chaque horodatage fourni.

CA-M4-16 : Le système refuse tout scoring punitif ou profilage comportemental des techniciens, vérifié par l'absence de tout champ ou calcul de score dans les entités et événements M4.

CA-M4-17 : Le système produit un digest quotidien déterministe et hash-chaîné listant les interventions complétées, les interventions en revue, et la volumétrie de la file d'attente, vérifié par l'exécution de deux appels identiques produisant exactement le même digest.

CA-M4-19 : Le système rejette tout pointage dont l'horodatage est hors de la fenêtre de travail déclarée du technicien avec le verdict REJ-PUNCH-HORS-HEURES, sans conserver AUCUNE donnée de localisation de l'événement rejeté ; la fenêtre déclarée est elle-même VALIDÉE (début strictement antérieur à la fin, fuseaux explicites sur les deux bornes) et toute fenêtre invalide est rejetée avec REJ-FENETRE-INVALIDE avant tout examen de pointage. Vérifié par les rejets explicites et l'absence de tout champ GPS dans le registre pour les tentatives rejetées (GPS strictement borné aux heures de travail, Loi 25).

CA-M4-20 : Le système ne formule jamais d'accusation : toute anomalie de pointage produit une demande de revue de type anomalie_pointage listant des causes possibles neutres, et aucune entité ni aucun événement M4 ne comporte de champ de culpabilité ou de fraude, vérifié DÉTERMINISTIQUEMENT : chaque entité et chaque événement M4 porte une liste FERMÉE de clés autorisées (whitelist gelée par entité) et le test échoue si une clé hors liste apparaît ; aucune valeur des enums fermés ne contient de terme accusatoire (conformité R-020).

CA-M4-21 : Le système traite la file pending_review en append-only : une résolution est une NOUVELLE entrée portant le champ demande_id de la demande d'origine (identifiant dérivé par encodage canonique injectif), jamais une mutation ou une suppression, vérifié par la validation de la chaîne, la présence simultanée de la demande et de sa résolution, et la correspondance exacte du demande_id.

CA-M4-18 : Le système dérive tout identifiant (intervention, pointage, événement outbox, jeton client) uniquement par encodage canonique injectif à préfixage par longueur : deux tuples distincts, y compris les cas de collision par concaténation, produisent des identifiants distincts, vérifié de manière déterministe inter-processus.

## 7. Stories

### S001 — Encodage canonique et identifiants M4
Périmètre : Fournir l'encodage canonique injectif (préfixage par longueur) pour dériver les identifiants d'interventions, de pointages, et d'événements outbox, ainsi que les empreintes sha256 associées.
Critères portés : CA-M4-18.
Tier : T1.
Dépendances : Aucune (socle).

### S002 — Registre append-only hash-chaîné des interventions
Périmètre : Implémenter le registre des interventions avec les opérations ajouter, lire, tete, valider_chaine, assert_chaine, et taille, garantissant l'immutabilité et la traçabilité de chaque maillon.
Critères portés : CA-M4-03.
Tier : T1.
Dépendances : S001.

### S003 — Contrats d'entrée et frontières de vérité
Périmètre : Valider structurellement le contrat gelé du lead qualifié consommé depuis M2, détecter les champs interdits (prix, montant, date ferme, engagement), et rejeter avec les verdicts appropriés.
Critères portés : CA-M4-01, CA-M4-02.
Tier : T1.
Dépendances : S001.

### S004 — Machine à états de l'intervention
Périmètre : Modéliser l'énuméré fermé des les états de l'énuméré fermé et la table des transitions conditionnées, rejeter toute transition illégale avec le verdict REJ-TRANSITION-ILLEGALE.
Critères portés : CA-M4-04.
Tier : T1.
Dépendances : S002, S003.

### S005 — Planification déterministe de la cédule
Périmètre : Générer la cédule des interventions de manière déterministe par règles pures appliquées sur les données fournies par l'appelant, sans recours à un moteur de routage réel.
Critères portés : CA-M4-05.
Tier : T1.
Dépendances : S004.

### S006 — Pointage horodaté et géolocalisé
Périmètre : Accepter et valider les événements de pointage (arrivée, départ) en vérifiant le format ISO-8601 avec fuseau explicite, la cohérence temporelle, et la cohérence géographique minimale avec la ville tokenisée.
Critères portés : CA-M4-06, CA-M4-07, CA-M4-08, CA-M4-12, CA-M4-19.
Tier : T1.
Dépendances : S004, S005.

### S007 — Gestion des écarts et file pending_review
Périmètre : Détecter les écarts entre le prévu et le réalisé, créer les demandes d'arbitrage avec les deux versions des faits, gérer la file pending_review, et exposer la volumétrie.
Critères portés : CA-M4-09, CA-M4-20, CA-M4-21. Les demandes de revue portent un type fermé (ecart_metier, anomalie_pointage) : les deux concepts ne confluent jamais dans une même sémantique.
Tier : T1.
Dépendances : S006.

### S008 — Work Completion Trigger et outbox transactionnel
Périmètre : Émettre le Work Completion Trigger dans l'outbox append-only lors de la transition vers terminee, garantir l'atomicité entre le changement d'état et l'écriture outbox, et assurer la tokenisation des données client.
Critères portés : CA-M4-10, CA-M4-11, CA-M4-13.
Tier : T2.
Dépendances : S002, S004, S006, S007.

### S009 — Digest quotidien et conformité horodatage
Périmètre : Produire le digest quotidien déterministe et hash-chaîné des interventions complétées, en revue, et de la volumétrie de la file d'attente, et garantir l'absence d'inférence d'horloge système.
Critères portés : CA-M4-14, CA-M4-15, CA-M4-16, CA-M4-17.
Tier : T1.
Dépendances : S002, S007, S008.

## 8. Hors périmètre v1 (GATED/T3)

Les éléments suivants sont explicitement exclus du périmètre v1 et repoussés en phase GATED/T3, nécessitant des éditeurs de CI, un accès réseau, et du matériel réel :

- Routage routier réel via API VRP (Vehicle Routing Problem) ou moteur self-hosted. La cédule v1 est déterministe par règles pures uniquement.
- API météo pour validation des conditions terrain et ajustement dynamique de la cédule.
- Temps réel WebSocket ou push pour la mise à jour dynamique de la cédule en cours de journée.
- Polling GPS matériel réel avec attestation cryptographique d'appareil. Le pointage v1 accepte des fixtures fictives.
- Envoi de notifications push aux techniciens pour alertes de cédule ou rappels de pointage.
- Intégration effective avec M3 (Estimation) : le champ devis_id dans le WCT est comblé par un identifiant nul en v1, le contrat M3 sera gelé ultérieurement selon l'ordre de construction ratifié (ADR-0003).
- Scoring de performance des techniciens à des fins d'optimisation de cédule : autorisé en principe mais repoussé pour éviter tout risque de dérive vers le profilage comportemental ou la sanction automatique.
