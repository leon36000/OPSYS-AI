# Stockage privé des originaux courriel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Conserver un original chiffré et rendre un reçu interne seulement après commit SQLite.

**Architecture:** Propriétaire socle interne non exposé, migration additive 0030 depuis 0029. Codec pur existant et AES-GCM déjà disponible, domaine AAD courriel distinct. Le propriétaire ouvre/commit sa transaction canonique; transaction ambiante refusée. Autorité vivante et clé externe injectées par futur appelant privé, sans valeur par défaut ou droit nouveau.

**Tech Stack:** SQLAlchemy/Alembic/SQLite, cryptography AESGCM existant, Python pytest/ruff.

**Spec:** `docs/grs/crm/CRM06-COURRIEL-CONTRAT.md` et audit CRM06; architecture du reçu SMS réutilisée sans identité/permission SMS.

## Global Constraints

- Root seul writer; données fictives, homes/tmp privés avant imports, Source RO, réseau interdit, ressources bornées.
- Aucun endpoint, outil modèle, grant, sélection de projet, automatisation IMAP ou preuve d’origine fournisseur.
- `recevoir(arguments:dict, *, source:bytes, autoriser:Callable, obtenir_cle:Callable) -> dict` et `lire(coordonnees:dict, *, autoriser:Callable, obtenir_cle:Callable) -> tuple[dict, OriginalCourriel]`.
- `identifier_source(coordonnees:dict)->str` partage la validation et l’identité des six champs du codec; ne confère aucune autorité.
- `autoriser(cnx, coordonnees_immuables, operation)` obligatoire, renvoie tuple exact `(acteur, empreinte_politique_SHA256)`; refus/exception/incohérence = PermissionError générique. Revalider avant toute recherche puis avant commit; la politique vivante doit être identique. Ce callback de confiance n’est pas une permission M1 déjà raccordée.
- `obtenir_cle(reference_or_None)` obligatoire, tuple exact `(reference_hex32, bytes32)`. Aucun secret DB ou ENV de repli; None choisit une génération courante, une référence existante exige cette génération exacte. Le callback doit revalider ses clés vivantes.
- MIME + métadonnées ensemble chiffrés : longueur métadonnées 4 octets big endian, JSON UTF8 canonique puis octets MIME. AES-GCM nonce aléatoire12. AAD domaine courriel v1 + identité, receipt_id, SHA, taille, date d’enregistrement, référence clé, version.
- Une ligne par identité, PK + receipt_id unique. Même identité/octets : reçu historique exact, sans écriture; autres octets : conflit, aucun remplacement. Déchiffrer et revalider l’existant avant retour/rejeu.
- Quota fermé :4096 lignes et128Mio de chiffrés cumulés; aucun effacement/éviction automatique. Original1Mio et métadonnées<=16Kio. Chiffrement et clé séparée du domaine Finance; bibliothèque AESGCM réutilisée, pas le propriétaire Finance.
- SQLite canonique seulement qualifié. Schéma SQLAlchemy portable, PostgreSQL pas annoncé. Migration downgrade non vide refusée; sauvegardes ne donnent aucune promesse d’effacement.

## Review Focus

- Callback révoqué ou politique changée après INSERT : original/audit annulés et aucun reçu.
- Rejeu avec clé absente, chiffré/AAD falsifié ou source différente : refus, aucun reçu historique aveugle.
- Retour avant vrai commit ou transaction d’appelant : refus imbriqué; test fermeture/réouverture SQLite et rollback.
- Confusion instance/source/boîte ou dict modifié par callback : identité et coordonnées capturées une seule fois, aucune traversée.
- Original, coordonnées privées et clé absents du SQL clair, ACK et journal; quota avant chargement de lignes et crypto indisponible fermée.

### Task 1 : table et propriétaire interne

**Files:** modifier `src/opsys/reception_courriel_contrat.py`, `src/opsys/stockage/schema.py`; créer `src/opsys/reception_courriel_stockage.py`, `src/opsys/stockage/migrations/versions/0030_receptions_courriel.py`, `tests/test_reception_courriel_stockage.py`; mettre à jour docs CRM06/matrice.

- [x] Tests comportement/migration/autorité SQL réelle fictive; rouge d’absence du propriétaire.
- [x] Migration additive et identité pure réutilisable; implémentation du propriétaire sans route.
- [x] QA ciblée codec+stockage, migrations et contrats existants touchés; revue précise puis une passe de correction causale si nécessaire.
- [x] Docs/reçus et commit local; réconciliation CI parente avant publication normale.

Le rappel d’autorité est une obligation du futur appelant privé, pas un substitut à la capture Host.
L’ACK est seulement `ORIGINAL_STOCKE_INTERNE`, jamais « fournisseur livré », « M1 qualifié » ou « courriel envoyé ».

## Rulings et preuve

Revue statique dédiée sans autreP1/P2 confirmé. BEGIN IMMEDIATE réel vérifié dans moteur.py, pas une
simple transaction SQLAlchemy logique. Limite WAL/NORMAL conservée : pas de preuve power-loss.
Readback SQL final après autorité/audit ajouté après2rouges triggers; second contrôle de clé avant
autorité/readback ajouté après6rouges révocation/rotation. Suite ciblée91PASS, ruff/verifier0.
Le comparateur historique0023 doit explicitement connaître le compartiment0030 : régression1FAIL
pour la fixture obsolète, correction test seulement sans masquage dynamique. PostgreSQL/Docker privé
non disponible : SKIP conservé, pas de nouvelle infrastructure ni droit acquis. Résultats étendus
consignés dans le reçu avant commit; les lots recoupés ne s’additionnent pas.
