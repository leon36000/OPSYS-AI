# 03-ARCHITECTURE — MODULE M4 (FIELD OPS)

> Architecte : Qwen3.7-Max (prose, rôle respecté ; Kimi-K3 défaillant, rotation journalisée).
> Décision structurante : OUTBOX = maillon COMPOSITE du registre unique hash-chaîné —
> l'atomicité de CA-M4-11 se prouve par l'indivisibilité du maillon, la consommation aval
> par curseur idempotent.


## 1. Arborescence du module

Le paquet m4_field_ops est découpé en modules isolés, chacun portant une responsabilité unique pour faciliter la preuve en CI et éviter les dépendances circulaires.

Le module encodage fournit l'encodage canonique injectif par préfixage de longueur pour dériver les identifiants et les empreintes.
Le module horodatage valide la conformité ISO-8601 avec fuseau explicite et rejette toute ambiguïté temporelle.
Le module verdicts catalogue les identifiants stables de rejet et de succès propres à M4.
Le module registre implémente la structure append-only hash-chaînée pour les interventions et l'outbox.
Le module contrats valide structurellement le contrat gelé du lead qualifié et les entités internes.
Le module frontieres détecte les champs interdits tels que les prix ou les engagements financiers.
Le module etats modélise l'énuméré fermé des statuts et la table des transitions conditionnées.
Le module cedule applique les règles pures de tri pour générer la planification déterministe.
Le module pointage traite les événements de terrain en vérifiant la cohérence temporelle et géographique.
Le module ecarts gère la détection des anomalies et la file d'attente de revue.
Le module outbox matérialise l'émission transactionnelle du Work Completion Trigger.
Le module digest agrège les données quotidiennes de manière déterministe et hash-chaînée.
Le module fixtures_garde fournit les données fictives pour les tests, explicitement marquées comme telles.
Le module consentement tient le registre du consentement GPS par employé — donné, retiré, avec
preuve et version de politique — et dit si le consentement d'un technicien est actif à l'instant
où le registre est rejoué, jamais un état tenu à part (PLAN T4.2, POLITIQUE-geolocalisation.md §4).
Le module retention porte l'arithmétique d'échéance de rétention (12 mois, la plus longue des deux
périodes citées par la politique), le chiffrement/déchiffrement d'un fix GPS avec une clé fournie
par l'appelant, et la construction des maillons d'accès et de purge — jamais la destruction
elle-même, qui appartient à l'adaptateur impur (PLAN T4.2, POLITIQUE-geolocalisation.md §5).

## 2. Schémas de données

L'entité Intervention représente le cycle de vie complet d'un travail terrain. Elle contient l'identifiant unique, la référence au lead, le technicien assigné, la ville tokenisée, le type de travaux, la fenêtre horaire prévue, le statut actuel, et la liste ordonnée des pointages. Aucun champ financier n'y figure.

L'entité Pointage capture l'action du technicien. Elle inclut l'identifiant du pointage, la référence à l'intervention, le type d'action (arrivée, départ ou pause), l'horodatage ISO-8601 avec fuseau, et l'attestation d'appareil simulée. Le fix GPS (PLAN T4.2, POLITIQUE-geolocalisation.md) n'y figure QUE si le consentement du technicien était actif au moment du pointage, et alors CHIFFRÉ (jamais latitude/longitude en clair) — sinon l'entité porte un mode manuel explicite, sans aucune donnée géographique. Voir la section 6 pour le mécanisme complet.

L'entité DemandeRevue matérialise un écart. Elle stocke l'identifiant de la revue, la référence à l'intervention, la version prévue des faits, la version déclarée par le technicien, le motif de l'écart, et le statut de l'arbitrage (en attente, validé, rejeté).

Clarification levant toute ambiguïté de représentation : l'entité EvenementOutbox est la CHARGE
UTILE portée PAR le maillon composite — une représentation logique, pas un registre séparé ; le
schéma gelé du WCT décrit cette charge utile et rien d'autre ; il n'existe AUCUN second registre
ni fichier d'outbox distinct. L'entité DemandeRevue porte un type fermé — ecart_metier ou anomalie_pointage — car les deux concepts appellent des arbitrages différents (revue de faits déclarés contre revue de cohérence d'un événement de terrain) et ne doivent jamais confluer ; la file est append-only, une résolution est une nouvelle entrée liée. L'entité EvenementOutbox représente le Work Completion Trigger. Elle porte l'identifiant de l'événement, la référence à l'intervention, le lead, le technicien, l'horodatage de complétion, le fix GPS final, la durée réelle, le booléen d'écart signalé, la référence à la revue, le hash du maillon, la liste des consommateurs cibles, et le devis nul en version un. Le lien client y est strictement tokenisé.

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
sur_site, en_revue, reportee, terminee, annulee. Toute divergence entre les deux documents est un écart
bloquant détecté par verif_coherence.py.

## 5. Anti-dérive et stratégie de preuve

La story S001 prouve la propriété d'injectivité de l'encodage canonique, garantissant qu'aucune collision d'identifiant n'est possible.

La story S002 prouve l'immutabilité du registre append-only, vérifiée par la validation de la chaîne de hash depuis le maillon de tête jusqu'à la racine.

La story S003 prouve l'étanchéité des frontières de vérité, démontrée par le rejet systématique de tout contrat contenant des champs financiers ou des engagements interdits.

La story S004 prouve la fermeture de la machine à états, vérifiée par le rejet explicite de toute transition non documentée dans la table officielle.

La story S005 prouve le déterminisme de la cédule, démontré par l'exécution de deux appels identiques produisant une sortie strictement égale.

La story S006 prouve la rigueur temporelle et géographique du pointage, vérifiée par le rejet des horodatages sans fuseau, la détection des incohérences de localisation, le rejet des pointages hors fenêtre de travail sans conservation de localisation (CA-M4-19, Loi 25) et la validation de la fenêtre elle-même.

La story S007 prouve la transparence des écarts, démontrée par la conservation intacte des deux versions des faits dans la file de revue, sans jamais d'écrasement silencieux.

La story S008 prouve l'atomicité de la cascade du Work Completion Trigger — écriture en UNE opération d'ajout, invariants de balayage, consommateur de référence idempotent — ainsi que la tokenisation du lien client dans la charge utile (CA-M4-13).

La story S009 prouve l'indépendance temporelle du digest quotidien, démontrée par l'absence d'appel à l'horloge système et la reproductibilité du hash de synthèse.

## 6. Consentement, chiffrement et rétention GPS (PLAN T4.2, POLITIQUE-geolocalisation.md)

Le consentement (§4 de la politique) vit dans le même registre hash-chaîné que le reste de M4 — un
maillon `consentement_gps` par événement (donné ou retiré), jamais un second registre : le module
consentement rejoue la chaîne et retient le DERNIER événement par technicien, exactement comme
`etats.statut_courant` retient le dernier statut d'une intervention. `m4_pointer` (outils.py, la
seule frontière impure autorisée à cette décision) consulte ce module avant chaque pointage : le
fix fourni par l'appelant n'est retenu QUE si le consentement est actif, sinon il est ignoré et le
pointage bascule en mode manuel — jamais rejeté, l'employé peut toujours pointer. Un retrait prend
effet au maillon suivant, sans file d'attente.

Le mécanisme de destruction (§5) répond à une contrainte structurelle : le registre append-only ne
permet ni modification ni suppression d'un maillon déjà écrit (le stockage durable de l'instance
n'expose même pas d'opération UPDATE ou DELETE sur un maillon), donc une coordonnée écrite en clair
y resterait pour toujours. Trois options ont été étudiées : garder la position hors chaîne, ne
porter qu'une empreinte à sens unique, ou chiffrer avant écriture avec une clé détruite à échéance.
La troisième est retenue : `pointage.enregistrer_pointage` reçoit la clé comme un argument pur
supplémentaire (même patron que `sel` pour `cedule.tokeniser_ville`), calcule la cohérence GPS sur
le texte clair comme avant PLAN T4.2, puis écrit le chiffré (module retention, HMAC-SHA256 en mode
compteur, bibliothèque standard uniquement) à la place de latitude/longitude. La clé elle-même vit
hors du registre, dans une table dédiée du socle (`opsys.cles_chiffrement`) qui autorise une VRAIE
suppression — une par technicien, alignée sur l'unité de rétention de la politique (l'échéance ne
distingue pas un pointage d'un autre pour un même employé). `m4_purger_retention_gps` détruit cette
clé une fois l'échéance atteinte ; le maillon déjà écrit ne bouge pas d'un octet, sa chaîne reste
intègre pour toujours, mais la position redevient irrécupérable — l'effacement cryptographique.

L'échéance (12 mois après la fin du contrat de travail ou le dernier punch, selon la plus longue
des deux périodes) est CITÉE telle quelle depuis la politique, jamais recalculée ni approximée ;
`fin_contrat_travail` est une donnée RH que M4 ne connaît pas de lui-même (son registre ne porte
que des interventions terrain), donc TOUJOURS fournie par l'appelant — son absence bloque toute
purge (REJ-RETENTION-DONNEE-MANQUANTE), jamais un défaut inventé. `m4_purger_retention_gps` est un
outil N5 (ADR-0009 §4) : il PROPOSE une destruction définitive, jamais ne l'exécute lui-même — seul
le propriétaire, avec l'attestation d'un professionnel, peut approuver.

Chaque lecture d'une position déchiffrée (`m4_lire_position_gps`, droit d'accès §7) écrit un
maillon `acces_position_gps` — qui, quoi, quand, quel résultat — jamais la position elle-même (§6 :
journal des accès). C'est la même discipline de minimisation que la ville tokenisée (section 2) :
ce qui n'entre jamais en clair dans le registre n'a jamais besoin d'en être retiré.

**Limite déclarée : les sauvegardes.** La clé vit dans la même base que le registre (ADR-0009 §2).
Détruire la clé ne la retire donc pas des sauvegardes déjà faites : `deploy/backup.sh` garde 14
jours de copies locales et, si restic est configuré, 14 quotidiennes, 8 hebdomadaires et 12
mensuelles. Pendant cette période, la position reste récupérable par quiconque restaure une
sauvegarde, et une restauration ressusciterait la clé détruite. L'effacement n'est donc complet
qu'à l'expiration de la dernière sauvegarde qui contient la clé. Deux décisions restent à prendre
(PLAN, GATE NATHAN) : la durée de conservation des sauvegardes au regard de la Loi 25, et une
procédure qui réapplique les purges après toute restauration, à partir d'un journal de purge tenu
hors des sauvegardes. Le chiffrement lui-même (flux HMAC-SHA256, nonce déterministe par pointage,
sans authentification) protège la confidentialité ; l'intégrité est assurée par la chaîne du
registre. Il relève du code critique et demande une revue externe avant la mise en service.

## 7. Lectures pures du propriétaire (PLAN T4.27-a)

Trois lectures servent l'app du propriétaire sans rien écrire au registre : la liste des interventions par pages, la
météo du créneau d'une intervention et le relevé des reports et des incidents. Chacune est un outil de lecture (T0).
L'adaptateur impur (outils.py) lit l'identité de l'appareil, la fait confirmer par la base, puis délègue à un module pur.
Les deux dernières sont réservées à l'administrateur, refusées dans le code à tout autre rôle d'appareil.

Le module pagination_interventions coupe la liste dans l'ordre de l'identifiant d'intervention. Le curseur est
l'identifiant de la dernière intervention de la page : il ne dépend d'aucun rang, donc une intervention qui naît entre
deux pages ne fait ni sauter ni répéter une ligne déjà lue. La page est la plus grande qui tient sous la borne d'une
réponse d'appareil, mesurée par le code et jamais estimée, avec au moins une intervention par page. Le contrat gelé de la
liste ne change pas : curseur et taille_page sont des clés sœurs additives, et sans elles la liste est rendue comme avant.
La pagination suit le filtre de visibilité : un employé ne compte jamais les interventions des autres.

La fonction verifier_intervention du module meteo_creneaux trouve le créneau que le dernier plan appliqué donne à une
intervention, puis délègue à la même évaluation que la vérification d'un plan : il n'existe pas de seconde évaluation. Une
donnée absente (créneau, date, prévision, seuil, fournisseur en panne) donne inconnu, jamais ok. La lecture ne propose ni
report ni nouvelle cédule.

Le module retards relève, à partir de l'heure de référence que l'appelant fournit (aucune horloge), les reports en cours et
les demandes de revue ouvertes, avec leur âge, au seuil de blocage du digest. Le retard sur la cédule n'est pas mesurable :
le plan numérote ses jours sans date civile et le registre ne garde aucune fenêtre planifiée. Le relevé le dit au lieu de
l'inventer.

Les modules restent purs : aucun import du socle, aucune horloge, aucun aléa, aucun réseau, aucun flottant, ce que des
tests vérifient par analyse du code. Aucun ne porte de coordonnée, de contact ni de champ financier.
