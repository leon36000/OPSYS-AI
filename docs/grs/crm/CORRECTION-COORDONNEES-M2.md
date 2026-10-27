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
L'audit avant/après est durable dans M2. Un écran paginé d'historique et un événement dédié pour M10
restent à réaliser ; ne pas confondre ce registre avec une preuve d'ingestion M10.

Tests ciblés : HTTP console et vraie base SQLite, CSRF, champs fermés, XSS, acteur réel, révocation,
rejeu, collision historique, recherche courante, accès vendeur, plusieurs projets, nouvelle ingestion,
rollback et concurrence de deux transactions. Régressions : Client 360, doublons, registre, liste, accès
M2 et console. Reçus distincts sous `work/chantier-opsys-20261010/crm-root-qa-20261027-r1/contact-*`.
Les rouges et erreurs de harnais restent conservés. Aucun total cumulé ne signifie CRM terminé.
