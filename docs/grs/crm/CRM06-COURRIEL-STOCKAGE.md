# CRM06 — stockage privé des originaux courriel

28 octobre 2026 UTC. **Fondation interne SQLite; aucun raccord IMAP ou journal client actif.**

## Objectif et pourquoi

Conserver le message exact chiffré avec ses coordonnées de réception, puis retrouver le même reçu
après reconnexion. Le reçu interne n’est jamais le succès d’un tour agent, une livraison fournisseur,
un courriel envoyé, une qualification M1 ou un rattachement client/projet.

## Architecture et fichiers

`src/opsys/reception_courriel_stockage.py` possède les opérations privées `recevoir` et `lire`.
`reception_courriel_contrat.py` expose aussi `identifier_source` pour partager le cadrage des six
coordonnées. `stockage/schema.py` définit `RECEPTIONS_COURRIEL`; migration additive
`stockage/migrations/versions/0030_receptions_courriel.py` depuis0029, sans modification des données
existantes. `tests/test_reception_courriel_stockage.py` exerce le propriétaire avec SQLite réel et une
autorité fictive relisant les personnes/rôles SQL actuels. [Plan](../../superpowers/plans/2026-10-28-courriel-stockage-chiffre.md).

Aucune route, CLI, opération MCP, capacité Host, politique IMAP, permission ou tâche modèle ajoutée.
Le stockage n’est appelé par aucun connecteur. Le reçu porte `ORIGINAL_STOCKE_INTERNE` uniquement.

## Données et chiffrement

Identité instance/source/compte/boîte/UIDValidity/UID et SHA du contenu distincts. MIME et métadonnées
sont chiffrés ensemble : longueur JSON sur4octets, JSON canonique puis octets MIME intacts. AES-GCM
existant, nonce aléatoire12octets, clé externe32octets obligatoire. AAD versionné liant identité,
reçu, SHA, taille, version, date d’enregistrement et référence de génération de clé. Aucune clé,
adresse, boîte ou corps dans l’ACK, le journal ou les colonnes en clair. Les empreintes et tailles
restent des métadonnées privées, pas une anonymisation.

Limites : original1Mio, métadonnées16Kio,4096lignes et128Mio de chiffrés cumulés. Les mesures SQL
précèdent le chargement des blobs; dépassement = refus, aucune éviction ou suppression automatique.
La copie brute reçue n’est ni analysée, ni rendue, ni exécutée, ni transmise à un modèle.

## Workflow et autorité

1. Refuser une transaction ambiante; capturer/valider les coordonnées et octets.
2. Ouvrir la transaction canonique SQLite (`BEGIN IMMEDIATE` réel du moteur partagé).
3. Appeler l’autorité privée vivante avant recherche ou rejeu; vérifier l’instance canonique et les quotas.
4. Créer l’original chiffré, le reçu et l’audit dans cette même transaction. Même identité/mêmes octets :
   déchiffrer/revalider et retrouver le reçu historique exact, sans nouvel audit d’écriture. Autres
   octets : conflit sans remplacement. Les dates de relecture ne réécrivent pas l’historique.
5. Relire la clé : génération courante pour un nouvel original, génération historique exacte pour
   lecture/rejeu; référence et octets doivent être identiques à ceux utilisés. Relire ensuite l’autorité
   et son empreinte de politique, l’instance, la ligne réellement persistée et les quotas.
6. Commit extérieur réussi, puis seulement renvoyer le reçu ou l’original privé. Toute panne, révocation,
   changement de clé/politique ou corruption par trigger provoque rollback, sans reçu.

`autoriser(cnx, coordonnees_immuables, operation)` et `obtenir_cle(reference_ou_None)` sont obligatoires,
sans fallback ENV ou clé persistée dans la DB. Ce sont des callbacks de **code privé de confiance**;
ils ne doivent jamais être fournis par JSON, par le modèle ou par un plugin non habilité. La vérification
SQL de QA n’est pas une permission M1 de production. Le futur Host doit fournir une autorité réellement
liée à la source/configuration/génération vivantes et un fournisseur de clés externes approprié.
Une clé reste susceptible d’être révoquée après le dernier contrôle : aucune transaction atomique
avec un coffre externe ou garantie de disponibilité permanente n’est annoncée.

## Tests, migration et limites

Préflight M10/M1 de développement privé; aucun secret ni message réel. Suite ciblée `crm06-store-v4` :
91PASS (dont60du codec), ruff/verificateur natifs0. Deux rouges ont prouvé le besoin de readback SQL
après les triggers d’écriture/lecture; six rouges ont prouvé le besoin du dernier contrôle de clé.
Corrections causales en une passe, revue statique indépendante sans autreP1/P2 confirmé.

Migration vide0030→0029→head préserve instance/personne; downgrade occupé refusé sans perte. Réouverture,
rejeu, refus avant SELECT après révocation SQL, chiffrement/AAD, conflit, panne commit, quotas et audit
sont exercés. Le comparateur historique0023 exclut explicitement la nouvelle table0030; il continue
à exiger toutes les tables réellement attendues en0023, sans ignorer dynamiquement les absentes.
Les résultats de régression et SKIP sont consignés dans le reçu de qualification, sans additionner
les populations recoupées.

Le moteur partagé garde WAL et `synchronous=NORMAL`. Preuve locale : commit SQL et fermeture/réouverture;
aucune qualification de coupure électrique, crash machine, matériel de stockage ou processus tué
pour ce nouveau propriétaire. PostgreSQL n’est pas qualifié; aucun réglage global de durabilité modifié.

## Statut, intégrations et gates Nathan

PARTIAL. Aucun fait métier M1/M2 ni copie M10 automatique créé. Pas de droit de lecture employé, pas
d’envoi, engagement fournisseur, paiement, déploiement ou activation. Rétention, rotation/effacement des
clés externes, capture Host, attestation d’origine, ACK avant progression IMAP, attribution exacte au
projet et restitution CRM restent des tranches distinctes. Les validations d’activation réelle restent
requises; ce travail local ne les donne pas. CRM06 Suivi client demeure MANQUANT.

Régression finale `crm06-store-regression-v2` : **193 PASS, 1 SKIP**, ruff/verificateur0.
Le SKIP concerne PostgreSQL+pgvector réel, Docker privé inaccessible; aucune qualification PostgreSQL
induite. Ce lot comprend les91cas ciblés, qui ne s’y ajoutent pas. Toutes les unités QA possédées
sont fermées et les sources testées épinglées.
