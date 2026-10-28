# Correction historisée des coordonnées — CRM-04

Statut : PARTIAL pour CRM-04. Tranche serveur et console sur SQLite ; PostgreSQL, transport MCP
complet, navigateur et propagation documentaire ne sont pas qualifiés ici.

## Objectif et audit préalable

La secrétaire doit pouvoir corriger le nom, le courriel ou le téléphone sans perdre les projets du
client. Avant cette tranche, `clients.identifiant_client` dérivait l'identité du contact initial exact ;
`client_associe` reliait chaque lead à cette identité. Client 360 et la recherche lisaient les contrats
initiaux. Modifier ces contrats ou recalculer leur identifiant aurait cassé la provenance et risqué
la séparation des projets. Le répertoire existant et les liens sont réutilisés.

Trois options examinées : réécriture des contrats (écartée : historique détruit), second catalogue CRM
(écarté : vérité parallèle), correction append-only sur l'identité stable (retenue). Aucun framework
supplémentaire : le registre M2, les transactions SQLite, les identités SQL, les formulaires CSRF et
l'idempotence de console fournissent déjà les mécanismes nécessaires. Cette décision technique relève
de la poursuite autonome autorisée ; elle ne constitue pas une validation métier de données réelles.

## Contrat, fichiers et routes

`m2_corriger_contact_client(client_id, contact, revision_attendue, motif, horodatage)` écrit un maillon
`contact_client_corrige` : identité, révision, avant/après, auteur authentifié, motif, horodatage,
identifiant chaîné. Le registre est protégé par les accès existants ; l'empreinte du contact initial
n'est pas une anonymisation. Aucun contact n'est copié dans les logs de console.

- `clients.py` : correction, projection courante, résolution des coordonnées historiques exactes.
- `registre.py`, `verdicts.py` : type additif et refus nommés.
- `liste_leads.py` : recherche sur le contact courant avant pagination et après portée vendeur.
- `doublons.py` : nouvelle détection sur les contacts courants ; les signalements déjà enregistrés restent historiques.
- `outils.py` : autorité admin SQL, écriture durable SQLite, contrat de l'outil.
- `console/metier.py`, `console/crm_ui.py` : surface fermée, formulaire et API.

Routes sous le préfixe console : `POST /crm/lead/{lead_id}/contact` et
`POST /api/crm/lead/{lead_id}/contact`. `GET /crm/lead/{lead_id}` expose le formulaire seulement
sur le backend qualifié. Le formulaire fournit la révision lue et un identifiant de mutation.
La console détermine le client à partir du lead, l'auteur et l'heure côté serveur.

Le contact est un remplacement explicite de l'ensemble des coordonnées : seules les clés `nom`,
`courriel`, `telephone` sont acceptées, une au minimum, chaque valeur texte non blanche de
254 caractères au plus. Un champ de formulaire laissé vide est retiré du contact courant ; il reste
dans l'historique. Aucun enrichissement automatique ni vérification de délivrabilité n'est prétendu.
Le motif est obligatoire, 300 caractères maximum. La révision entière est bornée et les booléens refusés.

## Identité, concurrence et permissions

L'identifiant et les liens existants ne changent jamais. Un nouveau lead dont le contact correspond
exactement à une correction connue rejoint cette identité stable. Les anciennes coordonnées restent
réservées à ce client ; les collisions exactes avec un autre client sont refusées, sans fusion.
Les rapprochements approximatifs (même courriel avec nom différent, variations orthographiques, etc.)
restent hors de cette tranche. Les signalements de doublons ne sont pas des décisions de fusion.

La correction exige un admin authentifié encore actif. Le vendeur, l'employé, le propriétaire sans rôle
admin et l'agent sans identité humaine n'obtiennent pas ce droit. Aucun rôle n'est attribué à une personne
réelle. Les lectures vendeur conservent uniquement ses opportunités ; elles montrent les coordonnées
courantes du client partagé sans exposer les autres projets, leurs notes ou leur historique de correction.

`BEGIN IMMEDIATE` sérialise les transactions SQLite avant la lecture : deux écritures sur la même
révision produisent un succès et un conflit. Une demande périmée ne remplace pas une modification plus
récente. Le même identifiant de mutation rejoue son reçu, sans seconde correction. L'autorité courante
précède la restitution d'un reçu. Une transaction annulée retire ensemble la correction et son reçu.
La voie PostgreSQL de correction reste refusée jusqu'à qualification de son verrouillage et de ses reprises.

## Frontières et suivi

Les contrats ingérés, soumissions, factures et pièces émises restent inchangés. Corriger une adresse
ne vaut ni consentement marketing ni autorisation d'envoi. Aucun courriel, appel ou paiement n'est lancé.
La synchronisation des coordonnées vers les départements et documents dépendants doit être conçue
avec leurs contrats de versionnement et de consentement ; cette tranche ne l'annonce pas réalisée.
L'audit avant/après est durable dans M2. L’écran paginé d’historique admin est disponible (contrat ci-dessous). Le fait M10 minimisé est décrit ci-dessous ; l’audit des coordonnées reste dans M2.

Tests ciblés : HTTP console et vraie base SQLite, CSRF, champs fermés, XSS, acteur réel, révocation,
rejeu, collision historique, recherche courante, accès vendeur, plusieurs projets, nouvelle ingestion,
rollback et concurrence de deux transactions. Régressions : Client 360, doublons, registre, liste, accès
M2 et console. Reçus distincts sous `work/chantier-opsys-20261010/crm-root-qa-20261027-r1/contact-*`.
Les rouges et erreurs de harnais restent conservés. Aucun total cumulé ne signifie CRM terminé.


## Consultation admin de l’historique — CRM-04

La route `GET /crm/lead/{lead_id}/contact/historique`, accessible depuis le dossier, réutilise
`m2_lister_historique_contact_client`. L’identité client est résolue depuis le lead ; les corrections
concernent tous ses projets. Chaque entrée expose la révision, les coordonnées avant/après, le motif,
l’auteur authentifié et l’heure présentée à Montréal. Aucun bouton de rétablissement ni export ajouté.
Les valeurs sont échappées et la réponse HTTP porte `Cache-Control: no-store`.

La lecture exige un admin humain encore actif, contrôlé en base à chaque appel ; l’agent sans identité,
le vendeur (même propriétaire d’un projet), l’employé et le propriétaire sans rôle admin sont refusés.
Client 360 vendeur ne reçoit toujours pas cet historique. Aucun rôle réel n’est attribué.

Le contrat source accepte `limite` de 1 à 50 (défaut 20), `decalage` de 0 à 1 000 000 et
`revision_max` facultative de 0 à 1 000 001. Les booléens ne valent pas des entiers. Un plafond supérieur
à la révision actuelle est refusé. Le plafond par défaut est la dernière révision existante. Les liens
précédent/suivant de la console gardent ce plafond et 20 entrées par page : une nouvelle correction
n’ajoute pas une entrée au milieu de la consultation. « Actualiser l’historique » ouvre un nouvel état.
L’ordre est celui des révisions croissantes, indépendamment des horodatages déclarés. Un client inconnu
produit un refus ; un client connu sans correction produit une page vide. Une page au-delà de la fin
est vide. La pagination borne la réponse, pas le coût de lecture du registre entier ; aucun benchmark
de gros volume ni index SQL n’est revendiqué.

Fichiers : `clients.historique_contact`, adaptateur et contrat `outils.py`, liste de lectures admin
`console/metier.py`, rendu et route `console/crm_ui.py`. Aucune table, migration ou dépendance ajoutée.
Tests : 22 corrections en SQLite réelle, nouvelle correction entre deux pages, absence de mutation de
la base, XSS avant/après/motif, accès refusés et révocation, plus bornes et isolation sur registre pur.
Qualification limitée à la console HTTP TestClient et aux primitives M2 ; navigateur, transport MCP,
PostgreSQL restent hors preuve de cette interface. Ce livrable complète la consultation de l’audit
M2, pas l’ensemble CRM-04 ni le CRM 3-en-1.


## Référence de correction dans M10 — intégration serveur SQLite

Audit préalable : M10 indexe ses événements par affaire (lead/opportunité), pas par client global.
La table `etapes.py`, son consommateur dynamique, son classement de confidentialité et la boîte
transactionnelle M2 sont réutilisés ; aucun nouveau framework, outil, rôle ou schéma SQL ajouté.

Après une correction acceptée, M2 publie `m2.contact_corrige` pour chaque projet déjà lié au client.
La même transaction contient la correction et tous ces événements : une panne de publication annule
l’ensemble. M10 reçoit ensuite le fait par le répartiteur habituel. La réception asynchrone n’est pas
promise au retour HTTP ; une panne du consommateur relève des reprises du bus existant.

La charge fermée contient seulement `client_id`, `lead_id`, `revision`, `source_ligne_id`,
`horodatage` et `fait_id`. La clé sémantique est le SHA256 UTF-8 de
`m2-contact-v1:{client_id}:{revision}:{lead_id}` ; l’identifiant transport est `m2-contact-` suivi
par cette clé. M10 recalcule la clé, valide les identifiants, la révision et l’instant avec fuseau.
Les identifiants demeurent des données pseudonymes, pas des données anonymes. Le catalogue impose
la forme canonique des affaires ; un ancien identifiant incompatible empêche la publication et fait
échouer la transaction, sans correction partielle. Les coordonnées, l’auteur et le motif libre ne
sont pas transférés. Les sources M2 avant/après sont accessibles uniquement par l’historique admin.

Le fait M10 est `CLIENT_PRIVATE`, selon la politique existante : utilisable par les agents M1/M2
sur les couches autorisées, retenu pour les autres. Ce classement n’est pas une nouvelle permission
admin ni une restriction par vendeur. Les résumés consolidés peuvent exposer le nombre de références
et leur provenance opaque, sans coordonnées ni motif ni contenu de l’audit M2. Un fait par projet
n’est pas une correction client supplémentaire : ne pas sommer ces références comme des clients
corrigés. Un rejeu sous un autre identifiant transport ne crée pas de second fait ; une provenance
contradictoire conserve le premier fait et retourne `identique: false` dans le reçu existant.

Fichiers : `m02-revenue-crm/outils.py`, manifestes M2/M10,
`evenements/catalogue/m2.contact_corrige.json`, `m10-memoire/etapes.py`,
`tests/test_contact_m2_m10.py` et contrat de manifeste `test_amont.py`.
Les routes de correction et de consultation restent celles décrites plus haut.

Les tests emploient le vrai stockage SQLite, la boîte transactionnelle, le répartiteur des dix
modules et le registre M10 : plusieurs projets et révisions, rejeu sémantique, provenance
contradictoire, annulation sur panne au deuxième événement, refus de révision, charges invalides,
confidentialité des contextes, consolidation et audit des faits non oubliés. Les rouges de harnais
MCP/PostgreSQL restent dans les reçus QA et ne prouvent ni un défaut produit ni leur qualification.

Statut : tranche locale qualifiée séparément du CRM complet. Pas de reprise des corrections anciennes,
pas d’ajout rétroactif aux projets créés ensuite, pas de modification des destinataires, documents,
consentements ou règles de fusion. Le diagnostic en lecture seule ci-dessous compare l’historique M2 et les références M10.
Une reprise contrôlée reste un changement distinct, non effectué. Aucun envoi réel autorisé
par ce fait ; PostgreSQL, navigateur et transport MCP restent à qualifier.


## Diagnostic admin de transmission des corrections

Objectif : permettre au secrétariat de constater une correction conservée dans M2 mais absente,
en attente ou contradictoire dans M10, sans confondre publication, reçu technique et mémoire métier.
L’audit réutilise les trois sources existantes. `m2_republier_assignations` a servi de référence de
lecture du bus ; il n’est pas appelé. Une bibliothèque de synchronisation n’apporterait pas les
sémantiques propres au registre M2 : aucune dépendance ajoutée.

L’outil de lecture `m2_reconcilier_memoire_contact_client` exige un admin humain encore actif et le
stockage durable SQLite. La console l’expose à `GET /crm/lead/{lead_id}/contact/memoire`, avec lien
depuis l’historique. Aucun endpoint de correction, d’export ou de rejeu n’est ajouté. Le contenu HTTP
est échappé et porte `Cache-Control: no-store` ; l’identité réelle et son rôle sont revérifiés.

Les liens client/projet sont parcourus dans l’ordre physique du registre. Chaque correction ne
concerne que les projets déjà liés à cet instant ; son horodatage déclaratif ne réordonne pas les
liens. La génération de charge versionnée est partagée avec le producteur. Les corrections anciennes
sont observables même sans publication automatique ; elles ne sont jamais publiées par cette lecture.

La réponse distingue `total_corrections` et `total_references` : plusieurs projets donnent plusieurs
références pour une même révision. Les statuts sont calculés pour les références de la page :

| État | Preuve observée |
|---|---|
| NON_PUBLIE | Identifiant de transport canonique absent de la boîte transactionnelle |
| EN_ATTENTE | Publication conforme présente, aucun fait M10 confirmé |
| ECHEC_LIVRAISON | Reçu d’échec M10, sans fait conforme |
| QUARANTAINE | Reçu de quarantaine M10, sans fait conforme |
| MEMORISE | Charge canonique conforme et fait M10 exact, classé CLIENT_PRIVATE |
| CONFLIT | Provenance différente, plusieurs faits concurrents, reçu contradictoire ou reçu traité sans fait conforme |

`publication_presente`, `memoire_presente` et `livraison` restent séparés : un reçu traité ne suffit
pas à prouver le souvenir. Le diagnostic cherche le transport canonique ; une livraison par un
identifiant alternatif peut laisser la publication canonique absente même si M10 contient un fait.
Il ne reconstitue pas l’historique complet de tous les transports alternatifs. Aucun motif libre,
coordonnée, auteur de correction, message d’erreur ou charge contradictoire n’est recopié dans la réponse.
Les références pseudonymes ne deviennent pas anonymes.

Paramètres : `limite` 1..50, `decalage` 0..1 000 000, `revision_max` 0..1 000 001. Les booléens sont
refusés. Le plafond par défaut est la dernière correction ; un plafond futur est refusé. `suivant`
est le décalage effectif après application du budget de sortie de 5 900 caractères ; une page peut
contenir moins que `limite`. La console garde ce plafond pour la page suivante. L’ensemble de
références reste stable, mais leur livraison peut progresser entre deux lectures : ce n’est pas un
instantané historique des reçus. Les registres sont parcourus pour établir les références et lire M10 ;
seules les requêtes du bus et la réponse sont bornées. Aucun benchmark de grand volume n’est revendiqué.

Fichiers : projection pure `m2_revenue_crm/contact_memoire.py`, adaptateur/contrat `outils.py`, surfaces
`console/metier.py` et `console/crm_ui.py`. Tests SQLite réels : avant/après répartition, projets tardifs,
correction antérieure sans événement, statut de reçu sans souvenir, provenance divergente, pagination
sous budget sans perte, base inchangée, accès refusé et révocation, rendu HTTP sans contenu sensible.
Les états d’erreur injectés dans les tests sont fictifs ; aucune panne fournisseur réelle n’est simulée
comme une preuve de production. Statut : diagnostic local qualifié, CRM-04 toujours PARTIAL.

Suite : raccorder la cédule visuelle CRM-01 aux créneaux effectivement confirmés par M4, en auditer
le contrat actuel avant code. La reprise historique des corrections demeure hors de cette tranche et
ne doit pas être déclenchée parce qu’une référence apparaît NON_PUBLIE.
