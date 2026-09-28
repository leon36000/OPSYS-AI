# R13 — Socle métier unifié d'OPSYS-AI

Recommandation d'architecture : source de vérité par département, événements inter-départements,
workflows avec validation humaine, RBAC, audit, observabilité, et articulation avec OPSYS-CORE.
Méthode : lecture directe du dépôt (`src/opsys/`, `departments/*/src`, `deploy/`, ADR-0006/0007,
`docs/architecture/*`, `docs/memory/RAG-PREMIUM.md`, `docs/research/INGREDIENTS.md`) + recherche web
pour les versions/licences non déjà vérifiées par R1–R10 (constat au 2026-09-28). Aucun paquet
installé, aucun code amont exécuté.

## 0. Ce qui existe déjà (vérifié, pas supposé)

Le socle n'est pas une page blanche : une bonne partie du problème est déjà résolue une fois, bien,
et à étendre plutôt qu'à refaire (P5).

| Brique | État réel | Fichier |
|---|---|---|
| Plan de contrôle | SQLite WAL : `approbations`, `usage_tokens`, `artefacts`, `journal` (audit append-only), `modes_departements`. Une connexion courte par opération (`session()`) | `src/opsys/etat.py` |
| Politique T0–T3 | `Autonomie` (T0 lecture → T3 frontière humaine) × mode `ombre/supervise/autonome` → `approbation_requise()` | `src/opsys/politiques.py` |
| Approbations | File asynchrone : `creer_demande` → réservation atomique `en_attente→en_cours` → exécution exacte des arguments enregistrés, jamais rejouée deux fois | `src/opsys/approbations.py` |
| Point d'accès agents | MCP streamable-HTTP, un sous-chemin `/mcp/<département>` par département (le département appelant vient de l'URL, jamais du modèle) | `src/opsys/serveur_mcp.py`, `capacites.py` |
| Mémoire d'entreprise | PostgreSQL 17 + pgvector, schéma `memoire` (documents/fragments/journal_effacements), FTS français + HNSW cosinus, fusion RRF, cloisonnement par portée obligatoire | `src/opsys/memoire/store.py`, déployé (`deploy/docker-compose.yml`) |
| Console | FastAPI, session HMAC, **un seul mot de passe admin partagé**, aucun rôle | `src/opsys/console/securite.py` |
| Départements | 10 manifestes `department.yaml` (mode, budget, portées mémoire, skills, cron) ; outils = fonctions Python pures enveloppées en `Outil` (JSON Schema à la main, pas de Pydantic) | `src/opsys/departements.py`, `outils.py` |
| Registres métier | Journaux append-only **hash-chaînés mais en mémoire process** (`Registre._maillons = []`) : aucune persistance entre redémarrages, aucun partage entre processus. Présents dans M3, M4, M8 au moins | ex. `departments/m03-estimation/.../registre.py` |
| **Outbox déjà prototypé** | M4 a un « Work Completion Trigger » : la transition `→ terminee` et l'événement sont écrits en **une seule opération d'ajout** (garde AST `garde_ecriture_unique`), lu par `lire_outbox(depuis_index)`, consommé de façon idempotente par un curseur + un `set` de `wct_id` vus. Cible aujourd'hui codée : `CONSOMMATEURS_CIBLES = (M6, M5, M2, M7, M8, M10)` | `departments/m04-field-ops/src/m4_field_ops/outbox.py` |
| Données métier durables (leads, clients, chantiers, factures, stock, PO) | **Absentes.** Aucun `sqlite3`/`psycopg`/`sqlalchemy` dans `departments/*/src` (vérifié par grep) : chaque département recalcule tout en mémoire à chaque appel | — |
| RBAC | **Absent.** Un nom libre signe chaque décision (`valider_nom`), aucune vérification de rôle | `src/opsys/console/securite.py` |
| Audit riche (confiance/coût/risque/avant-après) | Partiel : `journal` trace qui/quoi/quand pour les décisions d'approbation et les changements de mode ; pas de confiance/coût/risque par action, pas d'avant/après | `etat.py::journaliser` |

**Conclusion du constat :** le socle « plan de contrôle » (approbations, budget, MCP) est solide et ne
doit pas être touché. Le trou réel est ailleurs : (1) aucune donnée métier ne survit à un
redémarrage, (2) l'outbox de M4 est un excellent prototype mais n'est ni durable ni relié aux 6
départements cibles, (3) il n'y a pas de rôles.

---

## 1. Où vit le métier

**Recommandation : (a) service Python**, exposé en MCP comme aujourd'hui — pas de portage TypeScript,
pas d'hybride qui couperait les départements en deux piles.

| Brique clé déjà choisie (INGREDIENTS.md) | Langage | Portable en TS ? |
|---|---|---|
| OR-Tools (Apache-2.0, v9.15) / PyVRP (MIT) — VRP de M4 | Python natif (OR-Tools : binding C++) | Bindings Node existent mais tiers, non officiels ; réécriture du modèle de contraintes |
| SAM2 / Grounding DINO (Apache-2.0), OpenCV (Apache-2.0) — vision M3 | Python/PyTorch | ONNX.js existe mais perd l'écosystème `transformers` déjà retenu par R7 |
| Monte Carlo (stdlib `random`, puis SciPy/beta pour PERT) — M3 | Python | Trivial en soi, mais dépend des sorties vision ci-dessus |
| Docling (MIT) — ingestion RAG | Python | Pas d'équivalent TS mûr trouvé par R4 |
| DuckDB (MIT, v1.5.2) / pandas — M8 | Python (bindings natifs) | `duckdb-node` existe, mais dbt-core/MetricFlow/PyMC-Marketing (déjà catalogués Phase 2 pour M8/M9) sont Python |
| 3 156 tests, 77 outils déterministes déjà écrits | Python | Coût de réécriture = tout refaire pour un gain nul (OpenClaw parle MCP, pas un langage) |

L'argument qui tranchait pour OpenClaw dans ADR-0007 (« le langage du Core n'a plus d'impact sur le
métier, les départements sont exposés en MCP ») **s'applique dans l'autre sens avec la même force** :
rien n'oblige le métier à être dans la même langue que le Core. Réécrire 24 k+ lignes Python testées
vers TypeScript pour un bénéfice d'« unification » cosmétique violerait P5 et coûterait des mois pour
zéro capacité nouvelle. Le service opsys existe déjà, tourne déjà à côté du Core (même
`docker-compose.yml`, même réseau interne `opsys_internal`), et est déjà « supervisé » au sens
opérationnel (`restart: unless-stopped`, `healthcheck`) — **précision utile** : OpenClaw n'est pas un
superviseur de processus d'opsys, c'est un **client MCP** d'opsys (`mcp.servers.opsys_mN` dans sa
config) ; les deux sont des services pairs sous la même unité de déploiement Docker Compose, pas un
parent/enfant. C'est déjà la bonne relation : ni fork profond, ni ré-implémentation.

Nuance de vocabulaire par rapport à l'énoncé : il n'y a **pas un seul** service FastAPI métier
aujourd'hui, mais deux ASGI distincts sous le même processus Python — le serveur MCP
(`mcp.server.lowlevel.Server` + Starlette, pas FastAPI) qui expose les outils aux agents, et la
console FastAPI qui expose l'UI humaine. Cette séparation est saine (surface MCP minimale, jamais de
route HTTP « bonus ») et doit rester telle quelle ; seule la console reste FastAPI.

**Rejetée : (b) tout en TypeScript.** Coût de réécriture prohibitif (§ tableau), perte de l'écosystème
scientifique Python (OR-Tools, PyTorch, SciPy, DuckDB) sans équivalent TS mûr déjà vetté par
INGREDIENTS.md. **Rejetée : (c) hybride « logique légère en TS, lourde en Python ».**
Cela double la surface de contrat (deux langages à garder synchronisés avec le contrat gelé
`LeadQualifie`/`EstimationV1` déjà épinglé par des tests de non-dérive) pour un gain incertain — la
frontière MCP fait déjà ce travail proprement.

---

## 2. Base de données

**Recommandation : une seule instance PostgreSQL 17 + pgvector (déjà déployée), un schéma par
département, ORM = SQLAlchemy 2 Core (pas l'ORM déclaratif) + Alembic.** SQLite reste, mais seulement
là où il est déjà et pour ce qu'il fait déjà : le plan de contrôle.

### 2.1 Pourquoi pas « SQLite par défaut »

Le docker-compose actuel rend déjà Postgres **obligatoire** (`postgres` n'a pas de `profiles:`,
contrairement à `ollama`) pour la mémoire RAG. Ajouter un second moteur (SQLite) pour les données
métier créerait deux dialectes à maintenir, et surtout casserait la garantie qui fait tout l'intérêt
d'un outbox : **l'événement et la ligne métier qui le produit doivent être écrits dans la même
transaction.** Si le registre de M4 est dans un moteur et son `evenements_sortants` dans un autre,
on retombe dans le problème classique de double-écriture qu'un outbox existe pour éliminer. Un seul
Postgres, une seule transaction, règle le problème sans nouvelle brique.

### 2.2 Pourquoi pas PGlite

PGlite (Apache-2.0 / PostgreSQL License, ElectricSQL) est un Postgres WASM **embarqué dans un
process Node** — aucun binding Python natif, une connexion par instance. Il faudrait un pont HTTP/
socket (`pglite-socket`) pour qu'`opsys` (Python) le lise, ce qui réintroduit exactement le problème
réseau que la vraie instance Postgres résout déjà nativement. Intéressant pour un futur cache local
côté app mobile/PWA (hors périmètre ici), pas comme base serveur.

### 2.3 Règle d'or sur l'accès concurrent Node ↔ Python

**Jamais deux runtimes n'ouvrent le même fichier SQLite.** C'est déjà la pratique : la mémoire
d'agent d'OpenClaw (SQLite, Couche A de `RAG-PREMIUM.md`) n'est jamais touchée par Python, et le
`etat.db` d'opsys n'est jamais touché par Node — les deux ne se parlent qu'au travers d'une frontière
de service (MCP HTTP, CLI `openclaw`). C'est le bon patron et il doit s'étendre à tout le reste : la
future base métier Postgres n'est, elle non plus, **jamais** ouverte directement par OpenClaw — il la
voit uniquement à travers les outils MCP d'un département, exactement comme `memoire` aujourd'hui.
Côté Postgres lui-même, la concurrence entre les 10 départements (10 process/threads Python) est déjà
gérée par Postgres nativement (MVCC, verrous par ligne) ; `psycopg[binary]==3.2.3` (déjà épinglé) et
un pool de connexions courtes (même patron que `etat.session()`) suffisent.

### 2.4 Schéma proposé

```
PostgreSQL 17 (opsys)
 ├─ memoire            (existant, inchangé — RAG)
 ├─ audit               (nouveau — trace P3 cross-département, §4)
 ├─ evenements          (nouveau — catalogue versionné des événements, §3)
 ├─ checkpoints          (nouveau, optionnel — LangGraph, §3.4)
 └─ m1 … m10             (nouveau — un schéma par département, données métier + registre + inbox/outbox)
```

Le nom de schéma `m3`, `m4`… réutilise **exactement** `Departement.prefixe_outils`
(`src/opsys/departements.py`), déjà la convention de préfixe des outils (`m3_estimer_projet`) : aucun
nouveau vocabulaire à apprendre, un département = un préfixe = un schéma = une frontière de
migration.

### 2.5 ORM et migrations

**SQLAlchemy 2.1** (sorti le 24 septembre 2026 ; branche 2.0 encore maintenue en parallèle) +
**Alembic 1.20** (11 septembre 2026, déjà compatible 2.1) — les deux MIT. Recommandation : démarrer
sur la dernière version stable de la branche **2.0** (des années de production, pas 4 jours) et
suivre 2.1 après quelques correctifs mineurs — un socle fail-closed ne doit pas être le premier
consommateur d'une release de 4 jours.

**Core, pas l'ORM déclaratif.** Le style du dépôt est déjà « le code calcule » avec des
`@dataclasses.dataclass(frozen=True)` explicites et `vers_json`/`depuis_couple` pour le passage à
JSON (`src/opsys/outils.py`) — pas de graphe d'objets, pas de lazy-loading caché, pas de session
implicite. SQLAlchemy **Core** (`Table`, `select()`, `insert()` explicites) prolonge ce style sans
ambiguïté sur ce qui touche la base ; l'ORM déclaratif (ou **SQLModel**, qui l'enveloppe avec
Pydantic) ajouterait un second paradigme de validation alors que `outils.py` a déjà le sien
(JSON Schema à la main) — pas retenu, pour rester cohérent plutôt que d'empiler (AGENTS.md).

Couche d'accès commune proposée : `src/opsys/bd.py` — fabrique de moteur (lit `OPSYS_DATABASE_URL`,
déjà la variable existante), `session()` en gestionnaire de contexte au même nom que
`etat.session()` (connexion courte par opération), une fonction `enregistrer(table, dataclass)` qui
réutilise `vers_json` pour l'écriture. Chaque département garde son propre dossier de migrations
Alembic (`departments/mNN-*/migrations/`), une branche par schéma — cohérent avec « chaque
département a une source de vérité » (P13) : le schéma Alembic ne bouge que quand CE département
change, jamais par effet de bord d'un autre.

Le schéma `memoire` existant (géré aujourd'hui par un `schema.sql` idempotent rejoué à la main, pas
par Alembic) n'est **pas réécrit** : il est enveloppé comme migration `0001` (revision "baseline")
qui exécute ce même fichier tel quel. À partir de là, tout changement de schéma — y compris futur sur
`memoire` — passe par Alembic, sans avoir touché une ligne du SQL déjà testé.

### 2.6 SaaS multi-instances

Rappel de principe déjà tranché et à ne pas rouvrir : « une installation = une entreprise = un VPS »
(`ARCHITECTURE.md`). Le multi-instance ne veut donc **pas** dire une base partagée multi-tenant avec
colonne `tenant_id` — cela voudrait dire N instances Postgres indépendantes (une par client), chacune
migrée par la **même** chaîne Alembic. Le point d'accroche à construire (§6) : une commande
`opsys db migrer` (Alembic `upgrade head` contre `OPSYS_DATABASE_URL`), idempotente, sur le modèle
exact de `python -m opsys.memoire migrer` déjà existant — rejouable à chaque déploiement d'un
client sans script par instance.

---

## 3. Événements et workflows

**Recommandation : étendre l'outbox déjà prototypé par M4 (table Postgres + `LISTEN/NOTIFY` +
répartiteur qui poll en secours), pas une nouvelle brique de streaming.** Un moteur de graphes
d'agents (LangGraph) reste utile, mais pour un usage différent : les étapes **internes** d'un agent,
pas la propagation **entre** départements.

### 3.1 Le mécanisme (durcir l'existant, pas le remplacer)

1. Le registre en mémoire de chaque département (`Registre._maillons`) devient une table
   `mN.registre` (append-only, même schéma de maillon, même chaîne de hash — un test de
   non-régression rejoue les fixtures existantes et compare les hash obtenus en mémoire vs en base).
2. L'écriture du maillon **et** la ligne `mN.evenements_sortants` se font dans **une seule
   transaction SQL** — c'est la traduction directe, en durable, de la garde `garde_ecriture_unique`
   qui existe déjà par analyse AST dans `outbox.py` : demain, l'atomicité vient de la transaction,
   plus besoin de vérifier le code source pour la garantir (mais la garde AST peut rester, en défense
   en profondeur).
3. Un petit service `opsys-repartiteur` (asyncio, tâche de fond dans le conteneur `opsys` existant,
   aucun nouveau service Docker) fait `LISTEN opsys_evenements` pour la latence et interroge
   `SELECT … WHERE livre_le IS NULL` toutes les 2-5 s en filet de sécurité (une notification manquée
   — process arrêté au mauvais moment — s'auto-corrige au prochain poll ; `NOTIFY` seul n'est jamais
   la source de vérité, `evenements_sortants` l'est).
4. Pour chaque `(événement, consommateur)` déclaré au catalogue (§5), le répartiteur insère une ligne
   dans `<consommateur>.evenements_recus` avec une contrainte `UNIQUE(evenement_id)` — l'idempotence
   du `ConsommateurReference.wct_vus` (aujourd'hui un `set()` Python volatile) devient une contrainte
   SQL durable, rejouable après un crash sans double-effet.
5. Chaque département traite sa propre table `evenements_recus` par un outil T0 dédié (lecture),
   déclenché soit par son cron existant (`planifications` du manifeste), soit à la prochaine session
   agent — le traitement métier reste une fonction pure comme aujourd'hui ; seule la source change
   (table au lieu d'un paramètre direct).

### 3.2 Pourquoi pas Temporal / Hatchet / DBOS / NATS / Redis Streams comme brique par défaut

| Option | Licence (vérifiée) | Pourquoi pas en v1 |
|---|---|---|
| **Temporal** (server) | MIT | Excellent produit, mais un service de plus (serveur + UI + sa propre base) pour un volume — une PME, un VPS modeste — qui ne le justifie pas ; contraire à « sans infrastructure lourde par défaut » |
| **Hatchet** | MIT, Postgres-backed | Même verdict : moteur + UI séparés, RabbitMQ optionnel en plus ; le besoin réel (fan-out à 6-8 consommateurs internes) ne demande pas un ordonnanceur distribué |
| **DBOS Transact** | MIT (Python + TS), bibliothèque, pas un serveur | Le plus proche de « rien à ajouter » : durabilité par décorateurs directement sur Postgres, sans process séparé. **Retenu comme porte de sortie phase 2** si un département a un jour besoin de sagas longues (jours), de minuteries/`sleep` durables ou de retries exponentiels que le répartiteur simple ne couvre pas — mais non nécessaire pour la cascade §5, qui est un fan-out, pas une saga |
| **NATS (JetStream)** | Apache-2.0, CNCF | Bon bus pub/sub, mais encore un service à déployer/sauvegarder/superviser alors que Postgres LISTEN/NOTIFY + la table durable couvrent le besoin à cette échelle |
| **Redis Streams** | — | Redis lui-même est refusé par INGREDIENTS.md (RSALv2/SSPLv1/AGPLv3 depuis Redis 8) |
| **Valkey Streams** | BSD-3-Clause | Déjà déployé (cache LiteLLM) et supporte `XADD`/`XREADGROUP`/`XACK` à l'identique de Redis — techniquement viable, mais Valkey n'a **aucune garantie de durabilité transactionnelle avec une écriture Postgres** (deux moteurs = même problème de double-écriture qu'en §2.1) ; à réserver à un futur besoin de diffusion basse latence pur (ex. WebSocket vers le dashboard), jamais comme source de vérité d'un événement métier |

Aucun rejet n'est une question de licence ici — les quatre premiers sont MIT/Apache-2.0/BSD et
utilisables. Le critère décisif est « s'installe partout, sans service de plus » : Postgres est déjà
la seule pièce ajoutée, et elle sert trois fois (métier, RAG, outbox).

### 3.3 Validation humaine durable (N3–N5) et reprises

Ne change pas de mécanisme : la file `approbations` (SQLite, §0) reste l'unique porte humaine, et
elle est **déjà** durable et rejouable (réservation atomique `en_attente→en_cours`, jamais deux
exécutions). Ce qui change : les outils que le répartiteur invoque en conséquence d'un événement
(ex. M5 qui prépare une facture après `job.completed`) passent par `Capacites.appeler` comme n'importe
quel appel d'outil — donc par la même politique T0–T3 déjà en place. **Aucune nouvelle notion
d'approbation à inventer** ; l'événement ne fait que fournir les arguments que l'outil aurait reçus
d'un agent, la porte T3 reste la même porte.

Reprise après panne : un événement non livré reste `livre_le IS NULL` (rejoué au prochain poll) ; une
demande d'approbation `en_cours` interrompue en cours d'exécution finit `echec` (jamais remise à
`en_attente`, déjà garanti par `approbations.decider`) — l'humain la revoit et la relance
explicitement, jamais de rejeu silencieux d'une action T3.

### 3.4 LangGraph : oui, mais pour un usage différent

`INGREDIENTS.md` retient déjà LangGraph (MIT) pour le futur superviseur stratégique M9 (Phase 2,
GATED), et P7 le nomme explicitement pour « les workflows à états avec validation humaine, reprises
et cycles ». C'est le bon outil, mais pour l'orchestration **interne à un département** — un graphe
d'étapes (ex. le Conseil d'agents de M9, ou la conversation vocale de M1) qui doit se suspendre au
milieu et reprendre — pas pour la propagation entre départements (§3.1 le fait mieux, plus simplement,
avec zéro dépendance nouvelle). `langgraph-checkpoint-postgres` (MIT) écrit ses points de reprise dans
le schéma `checkpoints` du même Postgres. Le mécanisme natif `interrupt()` de LangGraph correspond
précisément à une porte N3–N5 posée **au milieu** d'un graphe long, en complément — jamais en
remplacement — de la file `approbations`, qui reste la source de vérité de la décision elle-même.

---

## 4. Identité, RBAC, audit, observabilité

### 4.1 Rôles (P8)

Rôles canoniques : `nathan_owner`, `admin`, `finance`, `manager`, `seller`, `employee`, `client`,
`system_agent`. Certains manifestes (ex. M6 : `inventory_manager`, `field_employee`, `propriétaire`)
utilisent des variantes locales — à réconcilier en alias vers la liste canonique de P8 plutôt qu'en
seconde taxonomie parallèle.

### 4.2 Le trou réel, et pourquoi il est concret

Aujourd'hui, `OPSYS_CONSOLE_MOT_DE_PASSE` est **un seul secret partagé** ; quiconque le détient signe
n'importe quelle décision, pour n'importe quel département, sous n'importe quel nom qu'il tape
(`valider_nom` n'exige qu'une chaîne non vide). Un employé peut donc, en pratique, approuver une
écriture comptable T3 de M5. Ce n'est pas un défaut de conception future : c'est l'état actuel du
code testé.

### 4.3 Recommandation : composer avec l'existant, pas dupliquer

Trois axes déjà largement présents séparément — les assembler plutôt qu'ajouter un quatrième système :

1. **Qui** — une personne (nom + identifiant), pas une chaîne libre.
2. **Quel rôle, sur quel département** — table `roles(personne_id, role, departement NULL=global)`.
3. **Quel palier d'action** — déjà `Autonomie` T0–T3 × mode (`politiques.py`), **inchangé**.

RBAC répond à « qui a le droit de tenter/décider », l'autonomie répond à « l'action part-elle tout de
suite ou attend-elle un humain » — deux questions différentes, à ne pas fusionner.

Implémentation minimale, additive, sans nouvelle brique :
- `etat.py` : ajouter `personnes(id, nom, actif)` et `roles(personne_id, role, departement)` au même
  `_SCHEMA` idempotent déjà en place (WAL, `CREATE TABLE IF NOT EXISTS`).
- `console/securite.py` : `valider_nom` vérifie en plus que le nom correspond à une personne active ;
  la `Session` porte ses rôles résolus.
- `department.yaml` : champ optionnel `roles_eligibles` (liste de rôles autorisés à décider une
  approbation de ce département) — additif au schéma `opsys.departement/v1` existant, comme
  `planifications` ou `kpis` déjà optionnels, donc rétrocompatible sans bump de version.
- `approbations.decider` : refuse si le rôle de `par` n'est pas dans `roles_eligibles` du département
  de la demande (fail-closed : rôle absent du manifeste ⇒ tous les rôles globaux seulement).

Identité elle-même : pas de fournisseur d'identité lourd en v1 (Pocket ID/Authentik déjà catalogués
Phase 2 dans INGREDIENTS.md — BSD-2/MIT, retenus le jour où plusieurs opérateurs nommés ont besoin
d'un vrai login individuel, passkeys compris). Pour une décision RBAC pure (pas d'authentification
distribuée), **Casbin** (`pycasbin`, Apache-2.0, RBAC/ABAC par fichier de politique) reste une option
si la matrice rôle×département×action grandit au point qu'une table statique ne suffit plus —
non retenu par défaut : le nombre de rôles (8) et de départements (10) est petit et stable, une table
SQL + une fonction pure suffisent et restent dans le style « le code calcule » du dépôt.

### 4.4 Audit (qui, quoi, pourquoi, source, modèle, confiance, coût, risque, statut ; avant/après)

Séparer deux choses déjà distinctes dans le dépôt plutôt que les mélanger dans une seule table :

- **Le fait métier (avant/après)** : c'est exactement ce que le registre hash-chaîné de chaque
  département porte déjà — un maillon *est* un avant/après vérifiable (hash du précédent + hash du
  courant). Le rendre durable (§3.1) répond déjà à « avant/après » sans nouvelle table.
- **La décision (qui, pourquoi, avec quel modèle, quelle confiance)** : nouvelle table `audit.trace`
  (schéma Postgres partagé), écrite au point de passage unique déjà existant — `Capacites.appeler`
  (`src/opsys/capacites.py`), après `executer()`. Colonnes : `quand, departement, outil, par
  (personne ou "system_agent"), motif, source (evenement_id ou session agent), modele, confiance,
  risque, statut, cout_tokens, reference_maillon` (pointeur vers le maillon du registre concerné,
  jamais une copie).
- `confiance`/`risque`/`statut` sont lus dans le résultat de l'outil **quand il les porte déjà** (ex.
  `niveau_confiance` dans `EstimationV1` de M3) — jamais inventés si absents (fail-closed, comme
  partout ailleurs dans ce dépôt).
- `cout_tokens` : la dépense par appel de modèle est déjà visible côté LiteLLM/Control UI OpenClaw
  (clé virtuelle par département) — la colonne reste `NULL` pour un déclenchement sans tour agent
  (ex. cron interne, 0 coût réel) plutôt que d'inventer un chiffre.
- `journal` (SQLite, décisions d'approbation et changements de mode) **reste tel quel** : il répond
  vite à une question opérationnelle locale même si Postgres est momentanément indisponible. La
  console agrège les deux (page « Journal » qui fusionne `etat.journal` et `audit.trace` par
  horodatage) plutôt que de forcer une seule source.

### 4.5 Observabilité

- **OpenTelemetry** (Apache-2.0) par défaut : un span par appel d'outil dans `Capacites.appeler` +
  `serveur_mcp`, export OTLP. Les conventions sémantiques `gen_ai.*` restent **expérimentales** en
  2026 (déplacées dans un dépôt dédié en juin 2026, `v1.42.0`, aucun 1.0 annoncé) : les utiliser
  derrière `OTEL_SEMCONV_STABILITY_OPT_IN` et s'attendre à des changements de noms d'attributs, pas
  à une API figée.
- **Langfuse** (cœur MIT ; dossiers `ee/` séparés, payants) reste une bonne UI de traces LLM, mais son
  socle (v4 exige ClickHouse ≥ 25.12 + Postgres + stockage objet) est lourd pour un VPS modeste : à
  proposer en **profil docker-compose optionnel**, jamais par défaut — cohérent avec le classement
  « Phase 2 » déjà posé par R3/R5 dans INGREDIENTS.md.
- Traces système (API, base, workflows, erreurs) : même collecteur OTel, pas un outil séparé.

---

## 5. Contrats d'interface entre départements

### 5.1 Catalogue

Table `evenements.catalogue(nom, version, producteur, schema_json, consommateurs[], introduit_le,
deprecie_le)`. Nom = `<entité>.<événement>` au passé (`job.completed`, `materials.used`,
`invoice.drafted`), jamais préfixé par le département — le département est une colonne, pas une
syntaxe. Validation du `schema_json` par le validateur JSON Schema **déjà écrit et testé**
(`opsys.outils.valider_arguments`) — pas de nouvelle dépendance (Pydantic reste possible au cas par
cas pour un département qui en a l'usage, jamais imposé). Versionnage additif : un champ optionnel
en plus reste en version courante ; un changement cassant crée une nouvelle `version`, les deux
coexistent le temps que tous les consommateurs déclarés migrent (`opsys verifier` étendu refuse un
événement publié hors catalogue ou contre un schéma qui ne valide pas).

### 5.2 La cascade « travaux terminés », étape par étape

| # | Étape | Département | Détail |
|---|---|---|---|
| 1 | Déclencheur | App mobile (hors ligne d'abord) | Employé touche « Terminer » ; checklist, photos après, temps réel, signature validés localement, synchronisés dès réseau |
| 2 | Écriture atomique | **M4** | `completer_intervention` (déjà codé) écrit, en une transaction Postgres `m4` : le maillon `sur_site/en_revue → terminee` **et** la ligne `m4.evenements_sortants` portant `job.completed` v1 — payload = `CHAMPS_WCT` existant (wct_id, intervention_id, lead_id, technicien_id, horodatage_completion, fix_gps_completion, duree_reelle_minutes, ecart_signale, revue_id, devis_id, hash_maillon) |
| 3 | Statut conditionnel | **M4** | Checklist/preuves incomplètes ou matériel divergent ⇒ `completed_pending_review`, jamais `completed_verified` — inchangé, déjà une règle produit |
| 4 | Fan-out | Répartiteur | Poll + `NOTIFY` ; pour chacun des 6 consommateurs déclarés au catalogue (**M6, M5, M2, M7, M8, M10** — liste déjà correcte dans `CONSOMMATEURS_CIBLES`, voir note ci-dessous), insertion idempotente dans `<dep>.evenements_recus` |
| 5 | Matériaux | **M6** | Ouvre le formulaire matériaux utilisés (mobile), valide les sorties, compare estimé/réel ; écart faible ⇒ stock ajusté (T1, interne) ; écart fort ⇒ alerte admin (T2) **et** publie `materials.variance_detected` (nouvel événement, consommé par M3 et M5) |
| 6 | Facture | **M5** | Prépare la facture brouillon (T1, jamais envoyée automatiquement — `auto_send_invoice_max_amount = 0` par défaut), calcule le coût réel, met à jour AR et rentabilité |
| 7 | CRM | **M2** | Marque le chantier terminé, écrit l'activité, fixe la prochaine action (T1) |
| 8 | Marketing | **M7** | Propose une demande d'avis + contenu avant/après **si consentement** déjà enregistré (T2 pour publication) |
| 9 | Analytique | **M8** | Temps réel vs prévu, marge prévue vs réelle, performance d'équipe — lecture pure (T0), alimente son entrepôt de faits |
| 10 | Mémoire | **M10** | Grave l'événement, les écarts et les leçons (T1, portée `chantiers`/`decisions`) |
| 11 | Second ordre → M3 | **M3** | Consomme `materials.variance_detected` (pas l'événement brut) pour recalibrer ses barèmes — cohérent avec la boucle de rétroaction du §6 produit (« M4, M5, M6 → M3 ») |
| 12 | Second ordre → M9 | **M9** | Consomme le paquet de preuves que **M8** publie après l'étape 9, pas l'événement brut — cohérent avec « M8 → M9 : paquets de preuves » |
| 13 | Audit | Tout au long | Chaque outil invoqué en réaction écrit sa ligne `audit.trace` (source = `job.completed`/`materials.variance_detected`, id de l'événement) |

**Note de validation** : le code existant limite volontairement `CONSOMMATEURS_CIBLES` à 6
départements, sans M3 ni M9 — la lecture du §6 produit confirme que c'est le bon design : M3 et M9
reçoivent l'information **enrichie** (variance, preuves), pas l'événement brut. Rien à corriger ici,
seulement à rendre durable et à câbler les 6 consommateurs manquants (aucun n'est câblé aujourd'hui,
seul `ConsommateurReference` existe comme test).

### 5.3 Flux des matériaux (M3 → M6 → M4 → M6)

Même mécanique, catalogue étendu : `materials.needed` (M3→M6), `po.approved` (M6, après validation
admin T2), `po.email_ready` (M6→M1, canal administratif — M1 reste un canal, jamais la source de
vérité du PO), `po.supplier_confirmed`/`po.received` (M6). Chaque flèche du §6 produit devient une
ligne de catalogue avant d'être codée — c'est ce catalogue, pas la mémoire du développeur, qui devient
la référence de ce qui existe entre départements.

---

## 6. Plan d'implémentation

Ordre : fondations DB → un département pilote (M4, déjà prototypé) → généralisation → RBAC/audit →
observabilité → LangGraph → industrialisation SaaS. Chaque tâche est petite et se termine par un test
qui la prouve (jamais de faux vert).

| # | Tâche | Preuve attendue |
|---|---|---|
| 0.1 | `src/opsys/bd.py` : moteur SQLAlchemy 2 + `session()`, extra `pyproject.toml` `db` | test unitaire, SQLite mémoire, sans toucher Postgres |
| 0.2 | Envelopper `memoire/schema.sql` en migration Alembic `0001` (baseline, contenu inchangé) | `alembic upgrade head` sur base vide == état actuel (diff nul) |
| 0.3 | Migration `0002` : schéma `audit` (`audit.trace`) | insertion + lecture d'une trace |
| 0.4 | Migration `0003` : schéma `evenements` (catalogue) + validation JSON Schema au chargement | `opsys verifier` refuse un catalogue mal formé |
| 1.1 | Porter `Registre`/`etats.py` de **M4** vers `m4.registre` (Postgres), même contrat de hash | rejouer les fixtures existantes : hash identiques mémoire vs Postgres |
| 1.2 | `m4.evenements_sortants`, écrite dans la même transaction que le maillon `terminee` | test d'interruption simulée entre les deux écritures : impossible par construction (une seule requête) |
| 1.3 | `opsys-repartiteur` (poll + `LISTEN/NOTIFY`) | tests contre le service Postgres du compose de test (patron `avec_docker` déjà utilisé par `tests/test_memoire_store.py`) : livraison idempotente, résiste à un redémarrage |
| 1.4 | `m6.evenements_recus` + outil `m6_traiter_evenements_recus` (premier consommateur pilote) | E2E : chantier fictif complété → M6 reçoit `job.completed` → écrit sa comparaison estimé/réel |
| 2.1 | Répéter 1.4 pour M5, M2, M7, M8, M10 (une PR par département) | un E2E par département, isolé |
| 2.2 | `materials.variance_detected` (M6→M3) et paquet de preuves (M8→M9) | E2E cascade complet (les 13 étapes du §5.2) |
| 3.1 | `personnes`/`roles` dans `etat.py` ; `securite.py` exige un nom connu | test : nom inconnu refusé à la connexion |
| 3.2 | `roles_eligibles` optionnel dans `department.yaml` ; `approbations.decider` le vérifie | test : décision refusée si rôle hors liste, `opsys verifier` accepte l'absence du champ (rétrocompatible) |
| 3.3 | `Capacites.appeler` écrit `audit.trace` après chaque exécution T1+ | test : ligne présente avec `confiance`/`risque` repris du résultat quand disponibles |
| 3.4 | Console : page Journal fusionnant `etat.journal` + `audit.trace` | test manuel documenté + capture |
| 4.1 | OpenTelemetry sur `capacites.py`/`serveur_mcp.py`, export OTLP | spans visibles sur un collecteur local de test |
| 4.2 | Profil `docker-compose --profile observabilite` (Langfuse, optionnel) | démarrage isolé, jamais entraîné par défaut |
| 5.1 | LangGraph + `langgraph-checkpoint-postgres` pour un seul pilote (Conseil M9) | reprise après interruption d'un graphe à mi-parcours |
| 6.1 | CLI `opsys db migrer` (Alembic `upgrade head`), idempotente | deux exécutions consécutives : la seconde ne change rien |

---

## Sources externes (versions/licences vérifiées, 2026-09-28)

- [Temporal server, licence MIT](https://github.com/temporalio/temporal) · [Hatchet, MIT, Postgres-backed](https://github.com/hatchet-dev/hatchet) · [DBOS Transact, MIT, bibliothèque sur Postgres](https://www.dbos.dev/dbos-transact)
- [NATS/JetStream, Apache-2.0, gouvernance CNCF confirmée 2026](https://www.cncf.io/blog/2025/05/01/protecting-nats-and-the-integrity-of-open-source-cncfs-commitment-to-the-community/)
- [Valkey Streams : XADD/XREADGROUP/XACK identiques à Redis](https://valkey.io/topics/streams-intro/)
- [sqlite-vec, dual MIT/Apache-2.0](https://github.com/asg017/sqlite-vec) · [PGlite, Apache-2.0/PostgreSQL License, WASM Node uniquement](https://github.com/electric-sql/pglite)
- [SQLAlchemy 2.1.0/2.1.1, MIT, sorti le 24-25 septembre 2026](https://www.sqlalchemy.org/blog/2026/09/24/sqlalchemy-2.1.0-released/) · [Alembic 1.20.0, MIT, 11 septembre 2026](https://github.com/sqlalchemy/alembic/releases)
- [Casbin/pycasbin, Apache-2.0](https://github.com/apache/casbin-pycasbin)
- [Langfuse, cœur MIT, `ee/` séparé, v4 exige ClickHouse ≥ 25.12](https://langfuse.com/self-hosting/deployment/infrastructure/clickhouse)
- [OpenTelemetry GenAI semantic conventions, expérimental, dépôt dédié depuis v1.42.0 (juin 2026)](https://opentelemetry.io/blog/2026/genai-observability/)
- [Google OR-Tools v9.15, Apache-2.0, janvier 2026](https://github.com/google/or-tools/releases) · [Docling, MIT, donné à la Linux Foundation AAIF début 2026](https://research.ibm.com/blog/docling-generative-AI) · [DuckDB v1.5.2, MIT, avril 2026](https://en.wikipedia.org/wiki/DuckDB)

---

PREUVE:
- Lu intégralement (fichier complet) : `AGENTS.md`, `CLAUDE.md`, `docs/architecture/ARCHITECTURE.md`,
  `docs/architecture/DEPARTEMENTS.md`, `core/UPSTREAM.md`, `docs/research/INGREDIENTS.md` (293 l.),
  `docs/research/00-BRIEF.md` (42 l.), `docs/decisions/ADR-0007-core-openclaw.md` (95 l.).
- Lu en grande partie, au-delà du strict requis par la mission : `docs/produit/DEFINITION-PRODUIT.md`
  (927 lignes ; §0 à §9 complets — dont §1, §4, §5/P1-P14, §6, §8 explicitement demandés, §7 en entier
  plutôt qu'un survol, §9 mobile en bonus — et début de §10 ; §11-§13 non lus, non requis par la
  mission). `docs/memory/RAG-PREMIUM.md` (395 lignes ; §1 et §2 complets, §3 amorcé — Docling/découpage
  — §4 et suivants non lus). Extrait (60/266 lignes) de `docs/research/R7-m3-m4.md`, pour le style de
  tableau de briques et le constat déjà fait sur M3/M4.
- Lu le code source (pas seulement les docs) : `src/opsys/{outils,politiques,approbations,etat,
  capacites,contexte,jetons,departements,serveur_mcp,profils}.py`, `src/opsys/console/securite.py`,
  `src/opsys/memoire/{store,outils}.py`, `pyproject.toml`, `deploy/docker-compose.yml`,
  `departments/m03-estimation/{department.yaml,src/m3_estimation/{registre,contrats}.py}`,
  `departments/m04-field-ops/src/m4_field_ops/{outbox,etats}.py`, `departments/m10-memoire/department.yaml`.
- Commandes exécutées (lecture seule, aucune installation, aucun code amont exécuté) :
  `find`/`wc -l` sur `src/opsys`, `departments/*`, `docs/*` ; `grep -rl "sqlite3\|psycopg\|sqlalchemy\|CREATE TABLE" departments/*/src` (aucun résultat — confirme l'absence de persistance métier) ;
  `grep -rl pydantic departments src` (aucun résultat) ; `grep -n "skip\|OPSYS_DATABASE_URL\|import psycopg\|pytest.mark" tests/test_memoire_store.py` (révèle le marqueur `avec_docker`) ;
  `find .github/workflows` ; `cat pyproject.toml` ; `wc -l` de vérification sur chaque fichier cité ci-dessus avant d'écrire les affirmations de couverture.
- Recherche web (WebSearch) pour chaque licence/version citée en §1-§5 et listée en « Sources
  externes » ci-dessus ; aucune affirmation de version/licence non recoupée par au moins une source.
- Contrainte respectée : un seul fichier écrit (`docs/research/R13-socle-metier.md`), aucun autre
  fichier du dépôt modifié, aucun paquet installé, aucun code tiers exécuté. `pytest`/`ruff check`/
  `opsys verifier` non exécutés volontairement : cette livraison ne touche ni `src/` ni `tests/`
  (uniquement `docs/research/`), donc rien à régresser — les exécuter n'aurait rien prouvé de plus
  que « le dépôt était déjà vert avant ce fichier ».
