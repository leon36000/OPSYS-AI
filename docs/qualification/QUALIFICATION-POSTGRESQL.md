# Qualification PostgreSQL : ce qui n'avait tourné que sur SQLite, rejoué sur un vrai PostgreSQL

> **Ce que ce document est.** Le compte rendu d'un banc scripté et rejouable qui a monté un VRAI PostgreSQL 17 éphémère
> (Docker, image locale, sans réseau), appliqué toutes les migrations (0001 → 0056), puis rejoué contre lui
> 1208 fichiers de test du socle et des dix départements, **deux fois** (la suite telle quelle, puis avec les bases
> SQLite que les tests bâtissent eux-mêmes redirigées vers PostgreSQL), en triant chaque échec. Il dit ce qui a été **trouvé et
> corrigé**, ce qui **tourne** sur PostgreSQL, et, sans euphémisme, ce qui **ne tourne pas** (§5, §6, §14).
>
> **Ce qu'il n'est pas.** Ce n'est pas la qualification d'une offre hébergée. Décision D5 de l'architecte : « PostgreSQL devient
> obligatoire avant toute offre hébergée ». Verdict de ce banc : **PostgreSQL n'est pas encore une cible complète**. Le socle
> et les chemins « agent » tournent ; 91 gardes « SQLite seulement » (§6) refusent PostgreSQL de façon typée dans
> 63 fichiers, surtout les écritures humaines de la console et quelques services qui reposent sur le verrou
> d'écriture unique de SQLite. Formule exacte autorisée : **« socle, bases de connaissances M10, graphe M10, sas
> d'approbation, bail, créneaux, idempotence et envoi unique éprouvés sur PostgreSQL 17 réel (par les tests qui ont réellement
> émis du SQL PostgreSQL, §3) ; consoles de saisie et services à verrou SQLite non portés »**.

Date : 1er novembre 2026 · Base de code : ligne architecte `1f031031e` + branche `claude/qualification-postgresql` · Banc :
[`install/qualification/postgresql/`](../../install/qualification/postgresql/) · Preuves brutes :
[`preuves-postgresql/`](preuves-postgresql/).

## 1. Résumé

| | Résultat |
|---|---|
| Serveur | PostgreSQL 17.11 (Debian), pgvector 0.8.7, aarch64, image `pgvector/pgvector:pg17` (`sha256:ac08538c6f8b…`, déjà en cache : aucun téléchargement). Exécuté avec `fsync=off` : banc jetable, **jamais** une configuration d'exploitation |
| Migrations | 0001 → 0056 montent en 0,45 s sur une base vide ; la descente jusqu'à 0021 (limite voulue du logiciel) puis la remontée redonnent un schéma identique (colonnes, contraintes, index, déclencheurs, fonctions) ; la chaîne s'installe aussi dans deux schémas distincts d'une même base |
| Suite rejouée, telle quelle | PostgreSQL : 30863 réussis, 1857 échecs ou erreurs, 208 ignorés ; SQLite (même code) : 32549 / 159 / 208 |
| Suite rejouée, bases SQLite des tests redirigées | PostgreSQL : 29355 réussis, 3364 échecs ou erreurs, 208 ignorés |
| Tests qui ont réellement parlé à PostgreSQL | 3884 sur 32057 en suite telle quelle ; **10409 sur 31522** en mode redirigé (les suites des départements bâtissent leurs propres bases SQLite : sans redirection, elles ne prouvent rien sur PostgreSQL) |
| Défauts de production trouvés et corrigés | **6** (§4) : `rowcount == -1` d'un `INSERT … SELECT` ; deux courses de comparaison-échange sous READ COMMITTED (états des connaissances, états des arêtes du graphe) ; immuabilité absente sur PostgreSQL pour deux tables (`fusion_ap_ocr_sources`, `service_attestations_m4`) ; `evenement_id` limité à 128 caractères sur PostgreSQL seulement (les opportunités répétées de M2 ne pouvaient pas être publiées) ; fuseau de session PostgreSQL non épinglé (`cree_le`) |
| Nouveau | adaptateur de recherche lexicale PostgreSQL (`tsvector`/GIN), migration 0056, 7 fichiers de tests (89 cas PostgreSQL réels ajoutés au job CI `frontiere-postgresql`, et 6 cas du banc qui n'ont pas besoin de Docker), banc rejouable |
| Tests existants rendus portables | 9 fichiers (recensement de tables, `?`, `PRAGMA`, transactions avortées, `rowid`) |
| Mutations | 24 mutations des correctifs et des gardes : 23 tuées, 1 équivalente, aucune survivante (§13) |
| Non porté | 91 gardes, dont les consoles de saisie M4/M6/M7, le cron opérateur, la liaison de cibles, les grants CFO, le moteur de recalcul M4, l'export SQLite (§6)  ; des défauts latents derrière elles (§5) |

## 2. Le banc

```bash
# prérequis : docker, l'image pgvector/pgvector:pg17 en cache, le venv Python du dépôt
python3 install/qualification/postgresql/banc.py demarrer            # conteneur opsys-pg-test-qualif-<hex>, port local aléatoire
python3 install/qualification/postgresql/banc.py suites              # tests/ + departments/, un processus pytest par fichier
python3 install/qualification/postgresql/banc.py suites --redirige   # idem, et les URL sqlite:/// des tests visent PostgreSQL
python3 install/qualification/postgresql/banc.py sqlite              # même cibles, SANS PostgreSQL : la référence
python3 install/qualification/postgresql/banc.py arreter             # supprime le conteneur (-v)
python3 install/qualification/postgresql/matrice.py DOSSIER_PG DOSSIER_SQLITE [--redirige DOSSIER_PGR] --md matrice.md
python3 install/qualification/postgresql/gardes.py --md gardes.md    # recensement des gardes « SQLite seulement »
```

- **Plugiciel `plugin_pg.py`** (`pytest -p plugin_pg`, inerte sans `OPSYS_QUALIF_PG_ADMIN_URL`) : une base « gabarit » migrée une fois
  par processus, puis, pour CHAQUE test, `CREATE DATABASE … TEMPLATE` (isolée, supprimée ensuite) et `OPSYS_BASE_URL` qui y pointe ;
  la valeur par défaut de `stockage.url_base()` y pointe aussi (les tests qui suppriment la variable restent sur PostgreSQL).
- **Mode `--redirige`** : plus de 300 fichiers de test bâtissent eux-mêmes leur base (`stockage.migrer("sqlite:///…")`, surtout
  les tests « durables » des départements) et ne touchaient donc jamais PostgreSQL. Le plugiciel crée alors, pour chaque URL SQLite
  distincte d'un test, une base PostgreSQL VIDE (le test migre lui-même, comme sur un fichier neuf), réutilisée tant que le test
  redemande la même URL (la « réouverture » d'un fichier). Un test qui lit le fichier par `sqlite3`/`Path`, le passe à un
  sous-processus ou compte sur un écouteur SQLite échoue alors pour une raison propre à SQLite (classe B, §7), pas à PostgreSQL.
- **Un compteur** compte les ordres SQL réellement émis vers un dialecte PostgreSQL pendant chaque test : un test qui n'en émet aucun
  est compté « n'a pas touché PG » et **ne prouve rien** sur PostgreSQL.
- Chaque exécution écrit un dossier horodaté (journaux bruts, un JSONL par fichier, `resume.json`) : rien n'est écrasé, rouges comprises.
- Les 49 fichiers qui bâtissent leur propre conteneur (`memoire.doubles.postgres_ephemere`) tournent tels quels, avec les
  drapeaux d'activation du dépôt : `OPSYS_QUALIFIER_M9_PG17=1 OPSYS_M03_PG_TESTS=1 OPSYS_M03_REAL_PG=1 OPSYS_R41_REAL_PG=1`.
  Sans drapeaux : 452 réussis, 45 ignorés (les frontières concurrentes M2/M3/M5/M7/M8/M9 et trois fichiers d'embeddings). Avec :
  **496 réussis, 2 échecs** — les deux exigent un modèle ONNX local (`/dev/shm/opsys-r35-20261002-onnx`) absent de cette machine :
  **non exécutables ici**, ni PostgreSQL ni le code en cause. La commande exacte du job CI `frontiere-postgresql` (21 fichiers) :
  **40 cas, 0 ignoré, 0 échec**.

### Exécutions conservées (aucune n'est écrasée, rouges comprises)

Journaux bruts hors dépôt (environ 1 Go) ; résumés versionnés dans [`preuves-postgresql/`](preuves-postgresql/).

| Exécution | Code | Résultat |
|---|---|---|
| PG n°1, suite entière | avant tout correctif | 1 201 fichiers : 1 051 verts, 150 rouges. A révélé le `rowcount == -1` (§4.1) |
| SQLite, les 150 fichiers rouges de PG n°1 | idem | 133 verts, 17 rouges (fusion PDF/AP, licences : préexistants, §8) |
| Levée expérimentale n°1 | idem + gardes levées en copie jetable | 89 des 133 fichiers « propres à PostgreSQL » verts |
| PG n°2, suite entière | correctifs + table lexicale dans un schéma dédié | 1 205 fichiers : 1 061 verts, 144 rouges. Le test d'installation par schéma (`test_pg_recalcul_wct_migration_qa.py`) a prouvé que ce schéma fixe cassait la chaîne : table ramenée dans le schéma courant (§9, §12) |
| PG redirigé n°1 | idem | 1 206 fichiers : 935 verts, 271 rouges. A révélé `evenement_id` > 128, les déclencheurs manquants et le fuseau (§4.4–§4.6) |
| **PG n°3, suite telle quelle** | **état livré** | **1208 fichiers : 1064 verts, 144 rouges (§3)** |
| **PG n°3, bases SQLite redirigées** | **état livré** | **1208 fichiers : 938 verts, 270 rouges (§3)** |
| **SQLite, suite entière** | **état livré** | **1208 fichiers : 1190 verts, 18 rouges (préexistants, §8)** |
| Levée expérimentale n°2 | état livré + gardes levées | 90 des 127 fichiers « propres à PostgreSQL » verts (§6.1) |
| Mutations | état livré | §13 |

Limites du banc, dites sans détour : `fsync=off` et `synchronous_commit=off` (aucune preuve de durabilité), un seul serveur (aucune
réplication ni bascule), pas de charge (les tests créent quelques lignes), pas de PgBouncer ni de pool externe, image aarch64
seulement, version majeure 17 seulement.

## 3. Matrice par tranche

Chaque cellule compte des TESTS (un fichier de test en contient plusieurs). « Échecs » inclut les erreurs de mise en place. Les
colonnes « tests ayant émis du SQL PG » disent combien de tests ont réellement parlé à PostgreSQL : c'est la seule colonne qui
prouve quelque chose sur PostgreSQL, un test vert qui n'en a pas émis ne prouve rien.

| Tranche | Fichiers | SQLite : réussis / échecs / ignorés | PostgreSQL, suite telle quelle | tests ayant émis du SQL PG | PostgreSQL, URL SQLite des tests redirigées | tests ayant émis du SQL PG (redirigé) |
|---|---:|---|---|---|---|---|
| Connaissances M10 (0041) | 9 | 339 / 0 / 0 | 339 / 0 / 0 | 161 sur 339 | 315 / 24 / 0 | 266 sur 339 |
| Consoles (HTTP) | 131 | 2333 / 46 / 13 | 1182 / 1197 / 13 | 1349 sur 1930 | 1088 / 1291 / 13 | 1765 sur 1930 |
| Courriel connecteurs (0040) | 19 | 599 / 0 / 0 | 572 / 27 / 0 | 33 sur 599 | 569 / 30 / 0 | 342 sur 599 |
| Cron opérateur / agents | 10 | 279 / 0 / 0 | 118 / 161 / 0 | 153 sur 169 | 113 / 166 / 0 | 162 sur 169 |
| E2E concurrence | 46 | 225 / 0 / 33 | 225 / 0 / 33 | 33 sur 225 | 175 / 50 / 33 | 219 sur 225 |
| Entrepôt M8 / pont BI (0046) | 7 | 167 / 0 / 1 | 167 / 0 / 1 | 89 sur 167 | 163 / 4 / 1 | 110 sur 167 |
| Fusion / PDF / sauvegarde | 22 | 397 / 110 / 2 | 335 / 173 / 2 | 89 sur 439 | 284 / 223 / 2 | 185 sur 439 |
| Graphe M10 (0052) | 11 | 306 / 0 / 0 | 306 / 0 / 0 | 114 sur 306 | 287 / 19 / 0 | 152 sur 306 |
| Liaison de cibles / CFO / MCP | 8 | 214 / 0 / 0 | 86 / 128 / 0 | 164 sur 195 | 85 / 129 / 0 | 181 sur 195 |
| M1 front office | 47 | 1909 / 0 / 0 | 1909 / 0 / 0 | 0 sur 1909 | 1861 / 48 / 0 | 262 sur 1909 |
| M2 revenue CRM | 44 | 2269 / 0 / 0 | 2269 / 0 / 0 | 0 sur 2269 | 2227 / 42 / 0 | 661 sur 2269 |
| M3 estimation | 74 | 2667 / 0 / 36 | 2667 / 0 / 36 | 0 sur 2668 | 2646 / 21 / 36 | 219 sur 2668 |
| M4 field ops | 99 | 3579 / 0 / 20 | 3579 / 0 / 20 | 0 sur 3599 | 3497 / 82 / 20 | 557 sur 3549 |
| M5 financecore | 120 | 3792 / 0 / 0 | 3805 / 0 / 0 | 2 sur 3805 | 3797 / 8 / 0 | 1024 sur 3805 |
| M6 material control | 67 | 1817 / 0 / 0 | 1817 / 0 / 0 | 0 sur 1817 | 1552 / 265 / 0 | 357 sur 1561 |
| M8 analytics | 46 | 1314 / 0 / 0 | 1314 / 0 / 0 | 0 sur 1314 | 1291 / 23 / 0 | 207 sur 1314 |
| M9 strategic intelligence | 76 | 1683 / 0 / 2 | 1683 / 0 / 2 | 0 sur 1685 | 1683 / 0 / 2 | 300 sur 1685 |
| Mémoire M10 (couche B, PostgreSQL) | 67 | 1750 / 0 / 7 | 1750 / 0 / 7 | 7 sur 1750 | 1627 / 123 / 7 | 413 sur 1746 |
| Planificateur (0044) | 1 | 21 / 0 / 0 | 21 / 0 / 0 | 0 sur 21 | 21 / 0 / 0 | 21 sur 21 |
| Sas social / WordPress / studio / signaux M7 | 35 | 686 / 0 / 4 | 672 / 14 / 4 | 82 sur 686 | 626 / 60 / 4 | 332 sur 686 |
| Socle (autres) | 265 | 6091 / 3 / 90 | 5935 / 157 / 90 | 1608 sur 6053 | 5337 / 755 / 90 | 2673 sur 5828 |
| Vision (0049) | 4 | 112 / 0 / 0 | 112 / 0 / 0 | 0 sur 112 | 111 / 1 / 0 | 1 sur 112 |
| **Total** | **1208** | 32549 / 159 / 208 | 30863 / 1857 / 208 | 3884 sur 32057 | 29355 / 3364 / 208 | 10409 sur 31522 |


Lecture : un écart entre SQLite et PostgreSQL est soit une garde « SQLite seulement » (§6), soit un test lié à SQLite (§7), soit un
défaut (§4, §5). Les échecs communs aux deux moteurs sont préexistants (§8). Les suites des départements M1 à M9 émettent **zéro**
ordre SQL en suite telle quelle : leurs tests sont des tests d'unité en mémoire ou bâtissent leur propre base SQLite ; ce qui les
met réellement face à PostgreSQL est le mode redirigé.

### Triage des échecs, suite telle quelle (PostgreSQL)

| Classe | Fichiers rouges | Tests en échec | Sens |
|---|---:|---:|---|
| C | 14 | 101 | préexistant (échoue aussi sur SQLite) |
| D | 97 | 1231 | garde « SQLite seulement » (non porté) |
| B | 9 | 56 | hypothèse SQLite codée dans le test |
| B+D | 22 | 400 | mixte (garde et test lié à SQLite) |
| A-latent | 1 | 58 | défaut latent de production trouvé (§5) |
| ? | 1 | 1 | cause non établie |

| Classe | Cause | Fichiers | Tests en échec |
|---|---|---:|---:|
| ? | (non établie) | 1 | 1 |
| A-latent | audit dupliqué sous concurrence (deux lignes de journal pour une publication) (L10) | 1 | 58 |
| B | le test lit les paramètres SQL sous forme de tuple (SQLite) ; PostgreSQL les rend en dictionnaire | 1 | 25 |
| B | API `sqlite3` utilisée sur une connexion SQLAlchemy | 2 | 20 |
| B | le test attend le texte d'erreur de SQLite | 1 | 3 |
| B | le test attend une erreur propre à SQLite (contrainte, déclencheur, refus de la garde) | 1 | 3 |
| B | valeur de test hors d'un entier 32 bits (colonne `Integer`, voir L6) | 1 | 3 |
| B | le test attend la base SQLite par défaut sous `OPSYS_HOME` | 1 | 3 |
| B | faux module `psycopg` du test incompatible avec le moteur réel | 1 | 2 |
| B | valeur de test plus longue que la colonne (PostgreSQL applique `varchar(n)`) | 1 | 1 |
| B | le test bâtit sa propre base PostgreSQL et se heurte à `OPSYS_BASE_URL` du banc | 1 | 1 |
| B | marqueurs « ? » de SQLite dans le SQL du test | 1 | 1 |
| B+D | console : surface fermée (503) hors SQLite | 10 | 187 |
| B+D | le test attend le texte d'erreur de SQLite | 12 | 183 |
| B+D | console de saisie ou service (instance non qualifiée) | 12 | 163 |
| B+D | le test attend une erreur propre à SQLite (contrainte, déclencheur, refus de la garde) | 6 | 139 |
| B+D | cron opérateur : base SQLite fichier dédiée | 2 | 69 |
| B+D | le test ouvre le fichier SQLite lui-même (`sqlite3`, `Path`) ou le passe à un sous-processus | 1 | 33 |
| B+D | ordre SQLite brut (`PRAGMA`, `BEGIN`, `INSERT OR …`) dans le test | 1 | 27 |
| B+D | réception courriel / SMS et suivi de rappel M1 (stockage qualifié SQLite) | 1 | 27 |
| B+D | captures et lectures documentaires M10 (SQLite fichier) | 2 | 22 |
| B+D | liaison de cibles | 1 | 17 |
| B+D | `DROP TABLE` de test refusé (objets dépendants) | 1 | 12 |
| B+D | grants CFO des agents | 1 | 11 |
| B+D | confirmation des dates et équipes M4 (cédule, journal, adéquation) | 1 | 10 |
| B+D | entier 0/1 pour une colonne booléenne dans le SQL du test | 1 | 6 |
| C | échoue aussi sur SQLite | 14 | 101 |
| D | console : surface fermée (503) hors SQLite | 35 | 468 |
| D | console de saisie ou service (instance non qualifiée) | 34 | 439 |
| D | confirmation des dates et équipes M4 (cédule, journal, adéquation) | 24 | 227 |
| D | tarifs et catalogue M6 (réception de prix, saisie console) | 11 | 211 |
| D | fusion opérationnelle (CSV / PDF / AP) | 5 | 96 |
| D | liaison de cibles | 5 | 93 |
| D | cron opérateur : base SQLite fichier dédiée | 6 | 85 |
| D | modèles de soumission M3 (écriture console) | 5 | 76 |
| D | catalogue M6 (console) | 3 | 40 |
| D | export / sauvegarde chiffrée de la base SQLite | 2 | 34 |
| D | grants CFO des agents | 3 | 22 |
| D | studio M7 (textes, médias) | 3 | 22 |
| D | écrivains concurrents de console (`EcritureConcurrente` non traduite) | 2 | 11 |
| D | réception courriel / SMS et suivi de rappel M1 (stockage qualifié SQLite) | 1 | 9 |
| D | captures et lectures documentaires M10 (SQLite fichier) | 1 | 6 |
| D | l'installateur local refuse `OPSYS_BASE_URL` : il gère la base SQLite de l'instance | 1 | 6 |
| D | service à verrou d'écriture SQLite (`BEGIN IMMEDIATE`) | 2 | 2 |

### Triage des échecs, bases SQLite des tests redirigées (PostgreSQL)

| Classe | Fichiers rouges | Tests en échec | Sens |
|---|---:|---:|---|
| C | 13 | 98 | préexistant (échoue aussi sur SQLite) |
| D | 156 | 1789 | garde « SQLite seulement » (non porté) |
| B | 65 | 759 | hypothèse SQLite codée dans le test |
| B+D | 33 | 618 | mixte (garde et test lié à SQLite) |
| A-latent | 1 | 58 | défaut latent de production trouvé (§5) |
| ? | 2 | 2 | cause non établie |

| Classe | Cause | Fichiers | Tests en échec |
|---|---|---:|---:|
| ? | (non établie) | 2 | 2 |
| A-latent | audit dupliqué sous concurrence (deux lignes de journal pour une publication) (L10) | 1 | 58 |
| B | le test lit le fichier SQLite de la base | 14 | 354 |
| B | le test ouvre une autre base que celle où il a migré (URL SQLite remplacée) | 17 | 215 |
| B | inventaire des tables par `sqlite_master` | 20 | 202 |
| B | ordre SQLite brut (`PRAGMA`, `BEGIN`, `INSERT OR …`) dans le test | 7 | 56 |
| B | le test attend une erreur propre à SQLite (contrainte, déclencheur, refus de la garde) | 4 | 40 |
| B | le test réutilise une transaction après une erreur SQL (PostgreSQL l'annule entièrement) | 3 | 29 |
| B | valeur de test non convertible dans la colonne typée (SQLite ne vérifie pas le type) | 2 | 29 |
| B | le test ouvre le fichier SQLite lui-même (`sqlite3`, `Path`) ou le passe à un sous-processus | 7 | 26 |
| B | marqueurs « ? » de SQLite dans le SQL du test | 4 | 26 |
| B | le test lit les paramètres SQL sous forme de tuple (SQLite) ; PostgreSQL les rend en dictionnaire | 1 | 25 |
| B | entier 0/1 pour une colonne booléenne dans le SQL du test | 5 | 23 |
| B | API `sqlite3` utilisée sur une connexion SQLAlchemy | 3 | 23 |
| B | le test attend le texte d'erreur de SQLite | 5 | 20 |
| B | `DROP TABLE` de test refusé (objets dépendants) | 1 | 18 |
| B | le test attend une date SANS fuseau (SQLite) ; PostgreSQL rend l'instant en UTC | 2 | 9 |
| B | valeur de test hors d'un entier 32 bits (colonne `Integer`, voir L6) | 2 | 7 |
| B | mode redirigé : les processus fils ouvrent le vrai fichier SQLite, pas la base redirigée | 1 | 5 |
| B | le test attend la base SQLite par défaut sous `OPSYS_HOME` | 1 | 3 |
| B | le test compare l'inventaire exact des tables du schéma, construit pour SQLite | 1 | 2 |
| B | faux module `psycopg` du test incompatible avec le moteur réel | 1 | 2 |
| B | index d'adresses : fichier SQLite propre à M4 (hors base de l'instance) | 1 | 1 |
| B | valeur de test plus longue que la colonne (PostgreSQL applique `varchar(n)`) | 1 | 1 |
| B | le test bâtit sa propre base PostgreSQL et se heurte à `OPSYS_BASE_URL` du banc | 1 | 1 |
| B | le test attend le fichier `opsys.db` dans l'archive de sauvegarde | 1 | 1 |
| B+D | console : surface fermée (503) hors SQLite | 13 | 236 |
| B+D | le test attend le texte d'erreur de SQLite | 15 | 223 |
| B+D | console de saisie ou service (instance non qualifiée) | 16 | 210 |
| B+D | inventaire des tables par `sqlite_master` | 5 | 185 |
| B+D | cron opérateur : base SQLite fichier dédiée | 5 | 149 |
| B+D | le test attend une erreur propre à SQLite (contrainte, déclencheur, refus de la garde) | 7 | 122 |
| B+D | le test ouvre une autre base que celle où il a migré (URL SQLite remplacée) | 3 | 84 |
| B+D | ordre SQLite brut (`PRAGMA`, `BEGIN`, `INSERT OR …`) dans le test | 3 | 72 |
| B+D | fusion opérationnelle (CSV / PDF / AP) | 1 | 50 |
| B+D | liaison de cibles | 3 | 46 |
| B+D | tarifs d'équipe M5 (transaction SQLite requise) | 1 | 41 |
| B+D | le test lit le fichier SQLite de la base | 3 | 37 |
| B+D | le test ouvre le fichier SQLite lui-même (`sqlite3`, `Path`) ou le passe à un sous-processus | 1 | 33 |
| B+D | réception courriel / SMS et suivi de rappel M1 (stockage qualifié SQLite) | 1 | 27 |
| B+D | captures et lectures documentaires M10 (SQLite fichier) | 2 | 22 |
| B+D | grants CFO des agents | 1 | 13 |
| B+D | `DROP TABLE` de test refusé (objets dépendants) | 1 | 12 |
| B+D | confirmation des dates et équipes M4 (cédule, journal, adéquation) | 1 | 10 |
| B+D | marketing M7 : stratégie CMO, Growth, coûts (port console SQLite) | 1 | 9 |
| B+D | entier 0/1 pour une colonne booléenne dans le SQL du test | 1 | 6 |
| C | échoue aussi sur SQLite | 13 | 98 |
| D | console : surface fermée (503) hors SQLite | 40 | 529 |
| D | console de saisie ou service (instance non qualifiée) | 49 | 518 |
| D | confirmation des dates et équipes M4 (cédule, journal, adéquation) | 36 | 308 |
| D | tarifs et catalogue M6 (réception de prix, saisie console) | 11 | 211 |
| D | tarifs d'équipe M5 (transaction SQLite requise) | 17 | 177 |
| D | documents d'affaire M10 (pilote et lecteur documentaires SQLite) | 7 | 153 |
| D | fusion opérationnelle (CSV / PDF / AP) | 8 | 149 |
| D | liaison de cibles | 12 | 126 |
| D | modèles de soumission M3 (écriture console) | 5 | 76 |
| D | marketing M7 : stratégie CMO, Growth, coûts (port console SQLite) | 6 | 72 |
| D | captures et lectures documentaires M10 (SQLite fichier) | 4 | 40 |
| D | catalogue M6 (console) | 3 | 40 |
| D | export / sauvegarde chiffrée de la base SQLite | 2 | 34 |
| D | réception courriel / SMS et suivi de rappel M1 (stockage qualifié SQLite) | 4 | 27 |
| D | grants CFO des agents | 3 | 22 |
| D | studio M7 (textes, médias) | 3 | 22 |
| D | écrivains concurrents de console (`EcritureConcurrente` non traduite) | 2 | 11 |
| D | cron opérateur : base SQLite fichier dédiée | 3 | 8 |
| D | l'installateur local refuse `OPSYS_BASE_URL` : il gère la base SQLite de l'instance | 1 | 6 |
| D | service à verrou d'écriture SQLite (`BEGIN IMMEDIATE`) | 2 | 2 |
| D | outil d'audit qualifié SQLite (refuse sur PostgreSQL) | 1 | 1 |

Causes non établies (premier message d'erreur du journal, tel quel) :

- `tests/test_banc_postgresql.py` (1) : `E       KeyError: 'OPSYS_QUALIF_PG_ADMIN_URL'`
- `tests/test_cablage_processus.py` (1) : `E       AssertionError: ['hemy/engine/default.py", line 1180, in do_execute`
- `tests/test_banc_postgresql.py` (1) : `E       KeyError: 'OPSYS_QUALIF_PG_ADMIN_URL'`

Suivi de ces cas, après les exécutions : `test_banc_postgresql.py` échouait à cause de son propre démontage (il supprimait la variable du banc) : corrigé (`monkeypatch.context()`), rejoué sous le plugiciel du banc, vert. `test_cablage_processus.py` est sensible à la charge (vingt travailleurs sur une machine de vingt coeurs) : rejoué seul sous PostgreSQL, vert.

## 4. Défauts de production trouvés et corrigés

Corrigés de façon minimale, **sans changer le comportement sur SQLite** (le verrou de ligne est ignoré par le dialecte SQLite ;
`RETURNING` exige SQLite ≥ 3.35, déjà requis par SQLAlchemy 2 et par `mnemo/graphe/sql.py` ; ici 3.45.1 ; les changements de schéma
de la migration 0056 ne s'appliquent qu'à PostgreSQL), chacun avec un test de non-régression qui tourne sur **les deux moteurs** quand
c'est possible et qui échoue sans le correctif (§13).

### 4.1 `rowcount == -1` : toute transition d'état de connaissance était refusée

`opsys/connaissances/etats.py::ajouter_etat` écrit un événement d'état par `INSERT … SELECT … WHERE état courant = attendu`
puis vérifiait `rowcount != 1`. Sous psycopg, `rowcount` d'un `INSERT … SELECT` (et d'un `insert()` Core qui rend sa clé) vaut
**−1** : toute transition légitime (`revu`, `publié`, `retiré`) levait « l'état courant n'est plus … ». La recherche de connaissances
était donc inutilisable sur PostgreSQL, avant même l'absence d'index lexical. Correction : `RETURNING id` (une ligne rendue = la
condition tenait à l'écriture). **Recensement** des 51 occurrences de `rowcount` dans `src/` et `departments/*/src/` : 48 portent sur
des `UPDATE`/`DELETE` (exacts sous psycopg, y compris les requêtes psycopg directes de `memoire`), 1 est un commentaire (le graphe
M10 avait déjà été écrit avec `RETURNING`), 1 porte sur un fichier SQLite propre à M4 (adresses), 1 était celui-ci. Mesuré à la main
sous psycopg 3.2.3 / SQLAlchemy 2.1.1 : `UPDATE`, `DELETE` et `INSERT … SELECT` en texte donnent un compte exact ; l'`insert()` Core
(qui rend sa clé) et `insert().from_select()` donnent −1.

### 4.2 Comparaison-échange non atomique sous READ COMMITTED : une version retirée pouvait redevenir « revue »

Une fois le `rowcount` corrigé, un défaut plus profond est apparu. En READ COMMITTED, deux transactions qui exécutent en même temps
l'`INSERT … SELECT WHERE état courant = 'brouillon'` lisent **toutes les deux** `brouillon` (l'événement de l'autre n'est pas encore
validé) et s'écrivent **chacune**. Mesuré : huit transitions simultanées « brouillon → revu » donnaient **huit** événements `revu` ;
un retrait et une revue simultanés laissaient la version dans l'état du dernier écrit (une version retirée pouvait ressusciter).
SQLite masquait le défaut : `BEGIN IMMEDIATE` n'admet qu'un écrivain. Correction : verrou de ligne de la version
(`SELECT … FOR UPDATE`) avant l'`INSERT` conditionnel ; le second écrivain attend, relit l'état validé du premier (nouvel
instantané à chaque instruction) et se voit refuser (`REJ-CONN-TRANSITION-INTERDITE`). Même défaut, même correction, pour les arêtes
du graphe M10 (`mnemo/graphe/sql.py`) : une arête pouvait être confirmée ET rejetée. Les verrous se prennent dans un ordre
constant (`retirer` parcourt les versions par numéro) : pas d'interblocage prévisible.

### 4.3 Ce qui n'a PAS été trouvé (vérifié)

Le code de production est presque entièrement en SQLAlchemy Core. Recherchés dans `src/` et `departments/*/src/` : `INSERT OR
REPLACE` (0 hors fichiers SQLite propres à M10/M4), `rowid` (0), `GLOB` (0), `strftime` SQL (0 : ceux du code sont ceux de Python),
`.like()`/`.startswith()` de colonne (0 : la sensibilité à la casse de `LIKE` ne diffère donc nulle part), `COLLATE` (0), `IFNULL`
(0), `PRAGMA` (tous derrière une garde SQLite ou dans une branche par dialecte), `AUTOINCREMENT` (fichiers SQLite propres),
`ON CONFLICT` (portable : `stockage.inserer()` choisit l'insertion du dialecte). Les dates sont des `TEXT` ISO, sauf
`registres_maillons.cree_le` (§4.6). Le tri des `NULL` (premiers sous SQLite, derniers sous PostgreSQL en ordre croissant) et le
`GROUP BY` strict n'ont pas été audités un à un : aucun test vert sur PostgreSQL ne les a révélés, ce n'est pas une preuve. Les
noms de contraintes `CHECK` de plus de 63 caractères sont tronqués avec une empreinte par PostgreSQL (SQLite les garde entiers) :
sans conséquence sauf pour un code qui lirait le nom dans un message d'erreur (aucun trouvé).

### 4.4 Immuabilité absente sur PostgreSQL pour deux tables

Les migrations 0026 (`fusion_ap_ocr_sources`) et 0033 (`service_attestations_m4`) ne posaient leurs déclencheurs d'immuabilité que
sur SQLite (`if dialect == "sqlite"`) : sur PostgreSQL, ces deux tables déclarées append-only acceptaient `UPDATE` et `DELETE`.
Trouvé par le test d'installation redirigé (`test_downgrade_0026_refuse_lien_ocr_conserve`, « DID NOT RAISE »), puis généralisé :
un comparateur des déclencheurs d'une base migrée sous SQLite et d'une base migrée sous PostgreSQL ne trouve que ces deux écarts
sur 27 tables à déclencheurs. Correction : migration 0056, une fonction plpgsql générique qui rend le même message que SQLite avec
le même SQLSTATE (23514, `IntegrityError`). Le comparateur reste en test : toute future table à déclencheur SQLite sans équivalent
PostgreSQL fait échouer `test_toute_table_a_declencheurs_sur_sqlite_a_leur_equivalent_sur_postgresql`. Les deux tables sont
derrière des gardes aujourd'hui : l'exposition était latente, la correction est préventive.

### 4.5 `evenement_id` limité à 128 caractères sur PostgreSQL seulement

`evenement_id` est un `VARCHAR(128)` dans six tables ; SQLite ne fait pas respecter la longueur, PostgreSQL oui. L'identifiant que
M2 construit pour une opportunité répétée (`m2-lead-assigne-<lead 64>~opp~<wct 64>`, plus de 128 caractères avec des identifiants de
64) ne pouvait donc **jamais** être publié sur PostgreSQL : le consommateur partait en quarantaine après cinq essais
(`StringDataRightTruncation`). Trouvé par `test_cascade_opportunite_m10` (8 tests) en mode redirigé ; ce chemin n'est derrière
AUCUNE garde : il aurait cassé en production dès la première opportunité répétée. Correction : migration 0056, les six colonnes
passent à `VARCHAR(512)` (PostgreSQL accepte ce que SQLite accepte déjà) ; `schema.py` déclare la même longueur. Les lecteurs en aval
qui bornent encore l'identifiant à 128 (provenance M5 de M8, inventaire de calibration) le font déjà sous SQLite : ce n'est pas nouveau
et n'est pas modifié. La descente refuse de tronquer un identifiant plus long.

### 4.6 Fuseau de session PostgreSQL non épinglé

`registres_maillons.cree_le` est un `timestamptz` : PostgreSQL le rend dans le fuseau de la SESSION. Avec un fuseau de base ou de rôle
autre que UTC, l'`isoformat()` que des empreintes hachent (`import_tarifs_confirmation`, `dernier_cree_le_sql` de M7) passait de
`+00:00` à `-05:00`. Le moteur épingle maintenant `timezone=UTC` à la connexion (PostgreSQL seulement). Prouvé avec une base dont le
fuseau est `America/Toronto`, lue par le moteur d'OPSYS (UTC) puis par une connexion non épinglée (`-05:00`).

## 5. Défauts LATENTS derrière les gardes (trouvés, NON corrigés)

Ils sont atteignables seulement si une garde est levée. Ils ne sont pas corrigés ici : corriger du code qu'aucun chemin PostgreSQL
n'exécute serait un correctif sans test d'intégration possible. Ils sont listés pour que la levée d'une garde les traite d'abord.

Relevés pendant la levée expérimentale des gardes (§6.1) et par lecture du code. Chacun est atteignable seulement quand la garde
qui l'abrite est levée ; **aucun n'est corrigé ici**.

| # | Défaut latent | Où | Effet sur PostgreSQL | Correction envisagée |
|---|---|---|---|---|
| L1 | Écrivains concurrents de console : la collision de rang d'un registre (`pk_registres_maillons`), de classement (`pk_pieces_classements`) ou de saisie (`uq_pieces_projet_saisie`) remonte en `EcritureConcurrente` / `IntegrityError` **non traduite en verdict**. Sous SQLite l'écrivain unique rend un verdict typé (`REVISION-PERIMEE`, HTTP 409). | consoles M6 (catalogue, prix, fournisseurs), M4 (absences, compositions), pièces classées, pièces de projet, suivi de rappel | le perdant reçoit une exception ou un 503 au lieu d'un refus typé ; aucune donnée corrompue | attraper `EcritureConcurrente` au point d'entrée et rendre le même verdict que la relecture sous SQLite |
| L2 | `func.length(cast(colonne, LargeBinary))` pour compter des OCTETS d'un texte : 64 occurrences dans 39 fichiers (`fusion_pdf`, `fusion_pdf_ocr`, `receptions_tarifs`, `agents_cron_*`, `documents_affaire_*`, `service_recalcul_m4`, consoles…). Seul `evenements/bus.py` choisit par moteur. | voir ci-contre | `CAST(varchar AS bytea)` n'existe pas : erreur SQL | un helper `octets(colonne)` : `length(CAST(… AS BLOB))` sur SQLite, `octet_length(…)` sur PostgreSQL |
| L3 | `func.typeof(colonne)` : fonction propre à SQLite | `documents_affaire_instance`, `documents_affaire_transactions`, `fusion_pdf_ocr`, `evenements/bus.py` (branche SQLite) | erreur SQL | contrainte de type au schéma, ou `pg_typeof` par moteur |
| L4 | SQL en texte `CAST(maillon AS BLOB)` | `console/memoire_apprentissage_ui.py` | `type "blob" does not exist` | `octet_length(maillon)` par moteur |
| L5 | `cast(colonne_booléenne, LargeBinary)` | `console/comptes_terrain.py` | `cannot cast type boolean to bytea` | comparer le booléen, ne pas le convertir |
| L6 | Colonnes `Integer` (32 bits sur PostgreSQL) qui portent des époques ou des révisions : `agents_cron_retraits.epoch`, `agents_declencheurs_remises.epoch` et `.lease_epoch`, `agents_configurables.revision` | schéma | débordement le 19 janvier 2038 (époques en secondes) ; une révision au-delà de 2 147 483 647 est acceptée par le code et refusée par la base (un test pousse 2^53) | migration `BigInteger` (PostgreSQL seulement ; SQLite est déjà 64 bits) |
| L7 | Cron opérateur : une base SQLite FICHIER dédiée, identifiée par son URL (`stockage/base_cron_operateur.py`) | `agents_declencheurs`, `agents_cron_*`, console cron | `CRON-SQLITE-REQUIS` : **aucun équivalent PostgreSQL** | décision d'architecture : table dans la base principale avec verrou de ligne, ou base dédiée PostgreSQL |
| L8 | Services M4 (recalcul certifié, lectures, historique, capability) et acteur système : exigent l'écouteur `BEGIN IMMEDIATE` (`_debuter_sqlite`) sur le moteur | `service_*_m4`, `moteur_recalcul_m4`, `service_capability`, `service_acteur_systeme` | refus typé `VERROU_ECRITURE_ABSENT` / `BACKEND_NON_SQLITE` | reconcevoir l'exclusion d'écriture (verrou consultatif ou ligne d'instance `FOR UPDATE`) |
| L9 | `INSERT OR IGNORE` / `PRAGMA` / `AUTOINCREMENT` dans des bases SQLite FICHIER propres à un module (adresses RQA de M4, magasin de développement de M10, export SQLite) | `m4_field_ops/localisation.py`, `m10_memoire/developpement.py`, `exportation.py`, `sauvegarde_chiffree.py` | sans objet : ces fichiers ne sont pas la base de l'instance | aucune (hors périmètre) ; l'export refuse PostgreSQL et renvoie à `deploy/backup.sh` |
| L10 | `notes_commande_memoire.publier` : deux publications simultanées de la même référence ne produisent qu'UNE référence sortante mais **deux lignes d'audit** (`console.reference_note_m6`) | notes de commande M6 (console) | le journal compte deux publications pour une | écrire l'audit sous le même verrou ou la même contrainte que la référence |


## 6. Gardes « SQLite seulement » : ce qui n'est pas porté

91 gardes dans 63 fichiers refusent PostgreSQL de façon **typée** (`INSTANCE-NON-QUALIFIEE`,
`CRON-SQLITE-REQUIS`, `BACKEND_NON_SQLITE`, `STOCKAGE_NON_QUALIFIE`, `REJ-…-NON-QUALIFIEE`, `HTTP 503`…). C'est la conception
fail-closed du dépôt : le code qui suit la garde n'a jamais tourné sur PostgreSQL et repose souvent sur `BEGIN IMMEDIATE`
(`_debuter_sqlite`) pour sa comparaison-échange. **Ces refus sont corrects tant qu'ils existent ; ils bloquent l'offre hébergée.**

Recensement mécanique (analyse syntaxique : `python3 install/qualification/postgresql/gardes.py`) :

| Module | Gardes | Fonction → refus typé |
|---|---:|---|
| `agent_cfo_grants.py` | 1 | `_sqlite_uniquement` → GrantCfoRefuse('grants CFO agents non disponibles hors SQLite à ce jal… |
| `agents_declencheurs.py` | 2 | `_transaction` → CRON-SQLITE-REQUIS |
| `cles_chiffrement.py` | 1 | `_nettoyer_fichiers_courants` → return (False, 'backend_non_qualifie') |
| `console/comptes_terrain.py` | 1 | `_capturer` → INSTANCE-NON-QUALIFIEE |
| `console/couts_marketing.py` | 1 | `executer_action` → REJ-COUT-MARKETING-BACKEND-NON-PRIS-EN-CHARGE |
| `console/crm_ui.py` | 1 | `confirmer_dates_plan` → HTTPException(503, 'Modification des dates indisponible sur cette inst… |
| `console/devis_modele_ui.py` | 1 | `nouveau` → HTTPException(503, 'Création non qualifiée sur cette instance') |
| `console/finance_snapshot_prive.py` | 2 | `_guard_registers` → ValueError('backend non qualifié'); `capturer_snapshot_prive` → ValueError('capture financière indisponible') |
| `console/frontoffice_marketing.py` | 1 | `dans_source_suivi` → RuntimeError('source non qualifiée') |
| `console/memoire_apprentissage_ui.py` | 1 | `_backend_sqlite` → BackendNonPrisEnCharge('aperçu M10 : backend SQLite uniquement, concur… |
| `console/memoire_chantier.py` | 1 | `_admin` → INSTANCE-NON-QUALIFIEE |
| `console/meteo_dates_chantier.py` | 1 | `preparer` → INSTANCE-NON-QUALIFIEE |
| `console/metier.py` | 4 | `_executer_edition_texte` → REJ-TEXTE-ECRITURE-NON-QUALIFIEE; `_port_cmo` → CMO-PORT-NON-QUALIFIE; `_executer_observation_growth_humaine` → GROWTH-ECRITURE-NON-QUALIFIEE; `_executer_note_commande` → ECRITURE-NON-QUALIFIEE |
| `console/notes_commande_ui.py` | 1 | `appeler` → HTTPException(503, 'Écriture des notes indisponible sur cette instance… |
| `console/prefill_ui.py` | 1 | `lecture` → HTTPException(503, 'Écriture non qualifiée sur cette instance') |
| `console/preparation_chantier.py` | 1 | `lire` → INSTANCE-NON-QUALIFIEE |
| `console/reprise_visite.py` | 1 | `preparer` → ARGUMENTS |
| `console/temps_pointes.py` | 1 | `_cible` → INSTANCE-NON-QUALIFIEE |
| `documents_affaire_instance.py` | 1 | `copier_registre_m10` → — |
| `documents_affaire_lecture_appareil.py` | 1 | `_connexion` → — |
| `documents_affaire_transactions.py` | 1 | `_connexion` → — |
| `evenements/bus.py` | 1 | `copier_cohorte_provenance_m5_m8` → ValueError('dialecte de provenance invalide') |
| `evenements/inventaire_calibration.py` | 1 | `_connexion` → InventaireRefuse('backend_source_non_qualifie') |
| `evenements/reconciliateur_cout_certifie.py` | 1 | `reconcilier` → return resume |
| `exportation.py` | 2 | `_base_sqlite` → ErreurExportation("cette commande exporte la base SQLite de l'instance…; `_verifier_base` → ErreurExportation(f'la révision SQLite ({revision_sqlite!r}) ne corres… |
| `fusion_csv.py` | 1 | `_isoler_transaction` → STOCKAGE_NON_QUALIFIE |
| `liaison_cibles.py` | 1 | `_sqlite_uniquement` → CibleRefusee('liaison de cible temporairement désactivée hors de SQLit… |
| `memoire_liaison.py` | 1 | `main` → return 1 |
| `moteur_recalcul_m4.py` | 2 | `_verifier` → RefusRecalculM4(VERROU_ECRITURE_ABSENT, 'écouteur BEGIN IMMEDIATE abse…; `_recalculer` → RefusRecalculM4(BACKEND_NON_SQLITE, 'recalcul certifié qualifié pour S… |
| `notes_commande_affaire.py` | 1 | `resoudre` → BACKEND-NON-QUALIFIE |
| `openclaw.py` | 1 | `configuration_cron_memoire_developpement` → ValueError('cron M10 exige une base SQLite fichier sans identifiants d… |
| `reception_courriel_stockage.py` | 1 | `_autoriser` → COURRIEL-AUTORITE-REFUSEE |
| `receptions_tarifs.py` | 1 | `_connexion` → — |
| `service_acteur_systeme.py` | 1 | `verifier` → PermissionError('acteur système qualifié pour SQLite seulement') |
| `service_capability.py` | 5 | `_verifier` → RefusAutorite('portée transactionnelle non vérifiable'); `courante` → RefusAutorite('backend non qualifié'); `_base` → RefusAutorite('garde SQLite indisponible'); `_projection_m4` → RefusAutorite('projection non qualifiée sur ce backend'); `_revoquer` → RefusAutorite('backend non qualifié') |
| `service_history_m4.py` | 2 | `attester` → RefusAutorite('backend non qualifié'); `lire_historique` → RefusAutorite('transaction non qualifiée') |
| `service_lecture_m4.py` | 2 | `_verifier` → sc.RefusAutorite('portée de lecture inactive'); `_ouvrir_interne` → sc.RefusAutorite('contexte de lecture invalide') |
| `service_politiques.py` | 1 | `_exiger_contexte` → BACKEND_NON_SQLITE |
| `service_recalcul_m4.py` | 2 | `_verifier` → sc.RefusAutorite('portée recalcul non vérifiable'); `lire_historique_v2` → sc.RefusAutorite('lecture non qualifiée') |
| `stockage/base_cron_operateur.py` | 1 | `identite_url_cron_operateur` → ValueError('base non canonique') |
| `stockage/lecture_m1.py` | 1 | `borner` → RuntimeError('source non qualifiée') |
| `stockage/maillons.py` | 2 | `_verrouiller_m2_principal` → ValueError('backend non qualifié pour la garde M2'); `copier_maillons_stricts` → ValueError('transaction SQLite courante requise') |
| `m01/m1_front_office/outils.py` | 2 | `_lire_registre_suivi_rappel` → REJ-SUIVI-RAPPEL-STOCKAGE-NON-QUALIFIE; `registre_sms_hote` → REJ-M1-SMS-SOURCE-NON-QUALIFIEE |
| `m01/m1_front_office/rappels_appareil.py` | 1 | `_acteur` → STOCKAGE-NON-QUALIFIE |
| `m02/m2_revenue_crm/outils.py` | 3 | `reconcilier_memoire_contact_client` → REJ-CONTACT-BACKEND-NON-QUALIFIE; `corriger_contact_client` → REJ-CONTACT-BACKEND-NON-QUALIFIE; `enregistrer_rendez_vous` → ECRITURE-NON-QUALIFIEE |
| `m03/m3_estimation/outils.py` | 3 | `enregistrer_modele_soumission` → ECRITURE-NON-QUALIFIEE; `creer_devis_depuis_modele` → ECRITURE-NON-QUALIFIEE; `_mutation_prefill` → ECRITURE-NON-QUALIFIEE |
| `m03/m3_estimation/service_attente_devis.py` | 1 | `_verifier_commun` → ValueError('requête M3 invalide') |
| `m04/m4_field_ops/absences_durables.py` | 1 | `capturer` → INSTANCE-NON-QUALIFIEE |
| `m04/m4_field_ops/composition_durable.py` | 1 | `capturer` → INSTANCE-NON-QUALIFIEE |
| `m04/m4_field_ops/journal_durable.py` | 1 | `capturer` → INSTANCE-NON-QUALIFIEE |
| `m04/m4_field_ops/outils.py` | 2 | `confirmer_dates_cedule` → REJ-FRONTIERE-VIOLEE; `_enregistrer_repere` → ECRITURE-NON-QUALIFIEE |
| `m04/m4_field_ops/service_faits_m4.py` | 1 | `_lire` → REQUETE-INVALIDE |
| `m04/m4_field_ops/visites_ecriture.py` | 1 | `capturer_visites` → INSTANCE-NON-QUALIFIEE |
| `m05/m5_financecore/outils.py` | 3 | `_autoriser_tarifs_equipes` → PermissionError("tarifs d'équipe : identité admin console et transacti…; `_autorite_couts_marketing` → BACKEND-NON-PRIS-EN-CHARGE; `_snapshot_couts_marketing` → BACKEND-NON-PRIS-EN-CHARGE |
| `m05/m5_financecore/port_lecture_courante_m4.py` | 1 | `calculer` → service_capability.RefusAutorite('lecture courante non qualifiée') |
| `m06/m6_material_control/catalogue_console.py` | 1 | `_autoriser` → INSTANCE-NON-QUALIFIEE |
| `m06/m6_material_control/historique_prix_console.py` | 1 | `capturer` → INSTANCE-NON-QUALIFIEE |
| `m06/m6_material_control/import_tarifs_console.py` | 1 | `capturer` → INSTANCE-NON-QUALIFIEE |
| `m07/m7_marketing/cmo_strategie.py` | 1 | `_autorite` → CMO-PORT-HUMAIN-REQUIS |
| `m07/m7_marketing/growth.py` | 1 | `enregistrer_observation_humaine` → PermissionError('saisie humaine Growth réservée au port console SQLite… |
| `m07/m7_marketing/usine/service.py` | 4 | `reviser_texte_humain` → REJ-TEXTE-ECRITURE-NON-QUALIFIEE; `preparer_media_humain` → REJ-MEDIA-ECRITURE-NON-QUALIFIEE; `decider_dossier_medias` → REJ-MEDIA-ECRITURE-NON-QUALIFIEE; `remettre_dossier_medias_manuel` → REJ-MEDIA-ECRITURE-NON-QUALIFIEE |
| `m10/m10_memoire/consolidation_developpement.py` | 1 | `_sqlite_seulement` → BackendConsolidationNonPrisEnCharge('backend_non_pris_en_charge : jobs… |
| `m10/m10_memoire/outils.py` | 3 | `_verifier_capture_paquets` → ValueError('capture inactive'); `capture_paquets_appareil` → CAPTURE-M10-INDISPONIBLE; `_verifier_invocation_lecture_documentaire` → LECTURE-DOCUMENTAIRE-INDISPONIBLE |


### 6.1 Levée expérimentale des gardes (copie jetable, rien n'est livré)

Pour savoir ce qui se cache derrière les gardes, une COPIE JETABLE du dépôt a vu toutes les gardes `!= "sqlite"` remplacées par
`not in ("sqlite", "postgresql")` (sauf les fichiers qui manipulent réellement un fichier SQLite : export, effacement, cron
opérateur, bus, maillons) et les 127 fichiers rouges propres à PostgreSQL ont été rejoués.

**Résultat** : sur 127 fichiers rouges propres à PostgreSQL, **90 deviennent verts** une fois les gardes levées (ce qui était refusé tourne alors, et passe) et 37 restent rouges.

| Cause des fichiers restés rouges | Fichiers |
|---|---:|
| test lié à SQLite (`sqlite_master`, `?`, `PRAGMA`, `iterdump`, `row_factory`…) | 11 |
| écrivains concurrents de console : `EcritureConcurrente` non traduite (L1) | 7 |
| service à verrou d'écriture SQLite (`BEGIN IMMEDIATE`) ou fichier SQLite requis (L8) | 6 |
| cron opérateur : base SQLite fichier dédiée, non levable (L7) | 5 |
| test qui attend le refus PostgreSQL (la garde levée, il ne se produit plus) | 3 |
| conversion de type SQLite-seulement (`CAST … BLOB`, booléen vers `bytea`) (L2–L5) | 2 |
| réception courriel / SMS M1 : cause non établie derrière la garde (état « inconnu ») | 2 |
| autre (voir le journal brut) | 1 |

Lecture : la levée **n'est pas un correctif** (le code livré garde ses gardes). Elle montre que, pour la majorité des fichiers, rien de plus profond que la garde ne casse sur PostgreSQL ; les causes restantes sont les défauts latents du §5 (écrivains concurrents de console, conversions de type, colonnes 32 bits), des tests liés à SQLite, et des services dont l'exclusion d'écriture repose sur `BEGIN IMMEDIATE`. **Un fichier vert ici prouve que le code tourne sur PostgreSQL, pas qu'il y est sûr sous concurrence** (L1 et L10 ont été trouvés dans des fichiers dont seuls les tests à deux écrivains échouaient). Fichiers verts après levée (liste complète dans `preuves-postgresql/levee-gardes.json`) : `test_agents_base_declencheurs.py`, `test_agents_cron_empreintes.py`, `test_banc_postgresql.py`, `test_besoins_profil_estimation_durable.py`, `test_cascade_catalogues_m10.py`, `test_cascade_fournisseurs_m10.py`, `test_cascade_tarifs_m10.py`, `test_cfo_obligations_preparees.py`, `test_cloture_suivi_m9_cible_core.py`, `test_console_absence_formulaire.py`, `test_console_absences_personnes.py`, `test_console_absences_personnes_http.py`, ….

## 7. Tests liés à SQLite (type b) et ce qui en a été fait

**Adaptés pour porter sur le contrat, pas sur SQLite** (9 fichiers ; le comportement sur SQLite est inchangé, ils restent verts
sur les deux moteurs) :

| Fichier | Hypothèse SQLite | Adaptation |
|---|---|---|
| `tests/test_connaissances_pipeline.py` | compte des lignes de `connaissances_fts` ; `UPDATE … SET rowid = rowid` ; `DROP TRIGGER …_no_delete` ; erreur SQL puis réutilisation de la même transaction | table de l'index par moteur ; première colonne réelle de la table ; déclencheurs retirés par moteur ; points de sauvegarde (`begin_nested()`), car PostgreSQL annule toute la transaction sur une erreur |
| `tests/test_connaissances_migration.py` | nombre de tables `connaissances_%` sur PostgreSQL | + `connaissances_lexique` (migration 0056) |
| `tests/test_agents_sms_configuration.py`, `test_openclaw_sms_profile.py`, `test_reception_sms_receipt.py`, `test_runtime_sms_profile_guard.py` | recensement des tables par `sqlite_master` | `inspect(cnx).get_table_names()` (portable) |
| `tests/test_avatars_voix_registre.py` | `SET actif = 0` | `SET actif = false` |
| `tests/test_fichiers.py` | marqueurs `?` | paramètres nommés |
| `tests/test_pont_bi.py` | `PRAGMA query_only` ; écriture refusée puis requête dans la même transaction | lecture du mode par moteur (`SHOW transaction_read_only`) ; point de sauvegarde |

**Non adaptés (type b restant)**, listés au triage (§3) : API `sqlite3` sur une connexion SQLAlchemy (`iterdump`), capture « SQLite
native » avec marqueurs `?` (`test_console_rapprochement_bancaire`), `row_factory` de `sqlite3` (`test_console_agents_etat`),
identifiant plus long que `varchar(64)` (`test_configuration_lecture`), `DROP TABLE` avec dépendances
(`test_console_estimation_apprentissage`), faux module `psycopg` (`test_postgres_fixture_doubles`), `BEGIN` brut
(`test_reception_courriel_stockage`), base SQLite par défaut attendue (`test_stockage_home_prive`). Ils ne bloquent rien : ils portent
sur SQLite par construction.

**Règle apprise, à appliquer à tout nouveau test** : (1) jamais `sqlite_master`, `rowid`, `PRAGMA`, `?` ni `iterdump` dans un test de
contrat ; (2) après une erreur SQL attendue, `begin_nested()` ; (3) une colonne booléenne se compare à `true`/`false`.


## 8. Échecs préexistants (type c)

Échecs communs aux deux moteurs (SQLite : 18 fichiers rouges) :

- `tests/test_cablage_m7.py`
- `tests/test_conformite_licences.py`
- `tests/test_console_fusion_ap.py`
- `tests/test_console_fusion_ap_m5.py`
- `tests/test_console_fusion_ap_m5_reference.py`
- `tests/test_console_fusion_ap_m5_saisie.py`
- `tests/test_console_fusion_pdf.py`
- `tests/test_console_fusion_pdf_ocr.py`
- `tests/test_fusion_ap.py`
- `tests/test_fusion_ap_m5.py`
- `tests/test_fusion_ap_m5_ocr.py`
- `tests/test_fusion_ap_m5_reference.py`
- `tests/test_fusion_ap_m5_saisie.py`
- `tests/test_fusion_ap_m5_saisie_gardes.py`
- `tests/test_fusion_ap_m5_saisie_unicode.py`
- `tests/test_fusion_ap_saisie_migration.py`
- `tests/test_fusion_pdf.py`
- `tests/test_ocr_profil.py`

- **Fusion CSV/PDF/AP et OCR** (`test_fusion_*`, `test_console_fusion_*`, `test_ocr_profil`) : l'isolation du worker PDF (bubblewrap)
  est absente de cette machine ; échecs identiques sur SQLite, hors périmètre (le brief commun les nomme).
- **`tests/test_conformite_licences.py`** : une licence (NumPy) cherchée dans une donnée de documentation absente ; échoue de la même
  façon sans PostgreSQL, ne dépend pas de la base.
- **`tests/test_cablage_m7.py`** et **`tests/test_cablage_processus.py`** : sensibles à la charge de la machine (vingt processus de test en
  parallèle sur vingt coeurs). Rouges dans une exécution chargée, verts rejoués seuls, sur SQLite comme sur PostgreSQL ; pas un
  écart entre moteurs.


## 9. Recherche lexicale PostgreSQL pour les connaissances (M10)

Conception, mesure et limites : [`docs/architecture/CONNAISSANCES.md`](../architecture/CONNAISSANCES.md) §10–§13. En bref :

- **Adaptateur par moteur** (`src/opsys/connaissances/lexical.py`) derrière les mêmes entrées et sorties : FTS5/`bm25()` sur SQLite,
  `tsvector` + index GIN + `websearch_to_tsquery` + `ts_rank_cd` sur PostgreSQL. Migration 0056, **PostgreSQL seulement**, table
  `connaissances_lexique` dans le schéma courant (rien n'est qualifié : la chaîne s'installe dans n'importe quel schéma ; un schéma
  fixe dédié avait été essayé et cassait l'installation par schéma, `test_pg_recalcul_wct_migration_qa.py`). Colonne `tsv`
  **générée** (`to_tsvector('simple', terme)`), append-only.
- **Normalisation commune, en Python**, avant l'index ET avant la requête, sur les deux moteurs : mêmes termes, donc mêmes ensembles
  de fragments retrouvés. Mêmes filtres (états, date, périmé rétrogradé, bases, couverture lexicale), mêmes provenances, mêmes
  refus ; le champ de score porte le nom de la mesure du moteur (`bm25` / `ts_rank_cd`).
- **Configuration `simple`, pas `french`** (écart assumé avec la consigne « `french` si disponible ») : `french` EXISTE dans
  l'image, mais le français est déjà normalisé en Python (accents, mots vides, radicaux) ; empiler son racinisateur réduit des
  termes déjà réduits et éloigne PostgreSQL de SQLite. Mesuré sur le corpus de mesure (10 sources, 28 questions, double
  d'embeddings) :

| Moteur / configuration | Mode | recall@1 | recall@3 | recall@5 | MRR@10 | Fausses « aucune source » |
|---|---|---|---|---|---|---|
| SQLite FTS5 | lexical | 0,76 | 0,84 | 0,84 | 0,7933 | 4 |
| **PostgreSQL `simple` (livré)** | lexical | 0,76 | 0,84 | 0,84 | 0,7933 | 4 |
| PostgreSQL `french` (mesuré, non retenu) | lexical | 0,80 | 0,84 | 0,84 | 0,8133 | 4 |
| SQLite FTS5 | hybride | 0,80 | 0,84 | 0,84 | 0,8133 | 3 |
| **PostgreSQL `simple` (livré)** | hybride | 0,80 | 0,84 | 0,84 | 0,8133 | 3 |
| PostgreSQL `french` | hybride | 0,80 | 0,84 | 0,84 | 0,8133 | 3 |

  **Écart de métriques SQLite → PostgreSQL `simple` : nul** sur les trois modes. L'**ordre** de fragments de score voisin diffère (BM25
  contre densité de couverture) : 3 questions sur 28 voient leur classement bouger, **jamais l'ensemble des 10 premiers** ; le rang 1
  ne bouge qu'une fois (lexical seul, question dont la bonne réponse reste au rang 2 sur les deux moteurs). `french` gagne UNE
  question au rang 1 en lexical seul : dans le bruit d'un corpus de 25 questions (CONNAISSANCES.md §11), non retenu pour la parité.
  Le test `test_le_corpus_de_mesure_donne_les_memes_ensembles_et_les_memes_metriques_sur_pg_et_sqlite` épingle ces égalités.
- **pgvector** : l'extension EST dans l'image (0.8.7 ; `CREATE EXTENSION vector`, `halfvec(3)` et un index HNSW créés à la main,
  **non branchés au code**). La similarité reste exacte en Python (plafond 20 000 vecteurs) ; le plan pgvector reste NON exécuté
  (CONNAISSANCES.md §10). `pg_textsearch` (BM25) n'est PAS dans l'image.
- **Non prouvé** : la latence et la qualité à l'échelle réelle (index GIN éprouvé sur quelques dizaines de fragments), un vrai corpus,
  un vrai modèle d'embeddings.

## 10. Concurrence réelle sur PostgreSQL

**Déjà couverts et rejoués** (49 fichiers, §2) : les 40 frontières de la CI (publication et reprise du bus, réception M2→M3, écritures
M3, mouvements, brouillons, envois, paiements et saisies fournisseur M5, imports et décisions M7, reprise M8, ingestion M9, restauration
`pg_dump`), plus les tests à fils multiples de la suite ordinaire rejoués sur PostgreSQL (40 fils sur un bail, deux décisions
d'approbation, idempotence, planificateur).

**Ajouté** (`tests/test_postgresql_concurrence_processus.py`, **vrais processus** `spawn`, départ commun, effets comptés dans un fichier
partagé ; sur SQLite ET PostgreSQL) : quatre processus décident la MÊME approbation (une seule exécution, une seule décision au
journal) ; quatre exécuteurs se disputent une ressource (un seul bail, jeton de fencing croissant à la reprise d'un bail expiré,
l'ancien détenteur le voit au renouvellement) ; quatre processus réservent le même créneau de planificateur (un seul passe) ;
quatre processus réservent l'envoi du même brouillon approuvé (une seule réservation `ENVOI_RESERVE`, les autres reçoivent
`REJ-COURRIEL-BROUILLON-ETAT` ou `…-APPROBATION-REJOUEE`) ; quatre processus rejouent la même clé d'idempotence d'appareil (une
exécution fraîche, trois renvois identiques). Et, en fils, les états append-only (§4.2).

### Différences d'isolation qui affectent les comparaisons-échanges

| | SQLite (WAL, `BEGIN IMMEDIATE`) | PostgreSQL (READ COMMITTED, le défaut des moteurs OPSYS) |
|---|---|---|
| Écrivains | **un seul** à la fois, dès l'ouverture de la transaction | simultanés ; chaque instruction voit un instantané neuf |
| `UPDATE … WHERE état = ?` (comparaison-échange) | atomique | **atomique** : le second `UPDATE` attend le verrou de ligne puis réévalue sa condition → sûr tel quel |
| `INSERT … SELECT WHERE état courant = ?` | atomique (écrivain unique) | **PAS atomique** sans verrou de ligne (§4.2) |
| `SELECT` puis `INSERT`/`UPDATE` (lire-puis-écrire) | atomique | à protéger par `FOR UPDATE`, verrou consultatif (`maillons` M2) ou contrainte unique |
| Collision de rang d'un registre chaîné | impossible | `IntegrityError` sur la clé primaire, traduite en `EcritureConcurrente` par `maillons.append` ; **les écrivains de console de M6/M4 ne la traduisent pas en verdict** (§5) |
| Échec d'une instruction dans une transaction | la transaction reste utilisable | la transaction est **avortée** jusqu'au `ROLLBACK`/point de sauvegarde (le code utilise `begin_nested()` aux bons endroits ; des tests non) |
| `SERIALIZABLE` | non utilisé | **non utilisé** : aucun code ne rejoue sur `40001`. Passer à SERIALIZABLE exigerait des boucles de reprise partout ; la garde M2 exige explicitement READ COMMITTED sans autocommit |
| Verrous | un fichier ; attente `busy_timeout` 5 s | verrous de ligne et verrous consultatifs ; **interblocages possibles** si deux chemins verrouillent dans un ordre différent (aucun trouvé ; non prouvé) |
| Types | affinité souple : une chaîne dans un entier, une longueur dépassée ou un fuseau absent passent | types stricts : `varchar(n)`, `integer` 32 bits, `boolean`, `timestamptz` en fuseau de session (§4.5, §4.6, §5 L6) |

## 11. Sauvegarde et restauration sur PostgreSQL

`tests/test_postgresql_sauvegarde_restauration.py` utilise les binaires de l'image, **dans le conteneur** : `pg_dump -Fc` d'une base
migrée jusqu'à la tête et garnie (identité, journal, approbation, deux bases de connaissances publiées avec index lexical), création
d'une base vide, `pg_restore --no-owner --exit-on-error`. Vérifié : mêmes lignes et mêmes contenus sur TOUTES les tables (nombre et
`md5` du contenu trié, `connaissances_lexique` comprise : la colonne `tsvector` générée est recalculée à l'identique) ; mêmes
déclencheurs, fonctions plpgsql et colonnes générées ; la base restaurée est à la tête (rien à rejouer) ; les déclencheurs
d'immuabilité refusent encore `UPDATE` et `DELETE` ; les séquences repartent après les valeurs restaurées ; la recherche lexicale
rend exactement les mêmes résultats. Une archive tronquée à la moitié est **refusée** par `pg_restore` (code non nul), rien n'est
restauré en silence. Les scripts `deploy/backup.sh` et `deploy/restore.sh` ont leurs propres bancs (`tests/test_deploy_backup_restore.py`,
`tests/e2e/test_deploy_postgresql_restore.py`, rejoué : voir §2).

**Non prouvé** : restauration d'un cluster physique (`pgdata`), sauvegarde à chaud sous charge, chiffrement de l'archive (la commande
`opsys exporter` ne couvre que SQLite : elle refuse PostgreSQL avec un message qui renvoie à `deploy/backup.sh`), copie hors site,
restauration entre versions majeures, durée de restauration d'une grosse base.

## 12. Chaîne de migrations

`tests/test_postgresql_migrations_chaine.py` : montée de 0001 à la tête sur une base vide, descente jusqu'à 0021 (la limite voulue :
0021 refuse de supprimer des autorités cron conservées), remontée, et comparaison des schémas (colonnes et types, contraintes, index,
déclencheurs, fonctions) avec la première montée : identiques ; installation dans deux schémas distincts d'une même base (un déploiement
« un schéma par client » n'exige rien de qualifié en dur). Chaque migration récente (0040, 0041, 0044, 0046, 0049, 0052) avait déjà
son test sur PostgreSQL éphémère ; 0056 a les siens (table, colonne générée, GIN, déclencheurs, longueurs, descente refusée avec données).

## 13. Mutations

| # | Mutation (appliquée seule à la source) | Verdict | Premier test qui la tue |
|---|---|---|---|
| M01 | rowcount accepté à -1 (défaut d'origine rétabli) | TUÉE | `tests/test_postgresql_parite_cas.py::test_transition_d_etat_de_connaissance_sans_concurrence_n_est_plus_refusee[postgresql]` |
| M02 | verrou de ligne des états de connaissance retiré | TUÉE | `tests/test_postgresql_parite_cas.py::test_huit_transitions_simultanees_de_connaissance_n_en_ecrivent_qu_une[postgresql]` |
| M03 | verrou de ligne des arêtes du graphe retiré | TUÉE | `tests/test_postgresql_parite_cas.py::test_confirmation_et_rejet_simultanes_d_une_arete_n_en_ecrivent_qu_un[postgresql]` |
| M04 | termes sans guillemets dans la requête websearch (« or » = opérateur) | ÉQUIVALENTE | — |
| M05 | classement inversé (pire d'abord) | TUÉE | `tests/test_connaissances_postgresql.py::test_la_limite_garde_les_meilleurs_candidats_sur_les_deux_moteurs[postgresql]` |
| M06 | filtre de versions retiré de la requête PostgreSQL | TUÉE | `tests/test_connaissances_postgresql.py::test_une_version_retiree_disparait_et_la_remplacante_se_trouve` |
| M07 | score PostgreSQL rendu sans changement de signe | TUÉE | `tests/test_connaissances_postgresql.py::test_la_valeur_rendue_est_dans_le_sens_naturel_et_jamais_un_zero_negatif` |
| M08 | adaptateur SQLite choisi pour PostgreSQL | TUÉE | `tests/test_connaissances_postgresql.py::test_0053_descente_refusee_avec_donnees_puis_permise_a_vide_et_remontable` |
| M09 | migration 0056 sans déclencheur d'immuabilité | TUÉE | `tests/test_connaissances_postgresql.py::test_0053_sur_pg_cree_la_table_la_colonne_generee_l_index_gin_et_le_declencheur` |
| M10 | colonne générée en 'french' alors que le code interroge en 'simple' | TUÉE | `tests/test_connaissances_postgresql.py::test_0053_sur_pg_cree_la_table_la_colonne_generee_l_index_gin_et_le_declencheur` |
| M11 | réservation d'approbation sans condition d'état | TUÉE | `tests/test_postgresql_concurrence_processus.py::test_n_processus_decident_la_meme_approbation_l_outil_ne_s_execute_qu_une_fois[postgresql]` |
| M12 | bail : un détenteur non expiré est cédé | TUÉE | `tests/test_postgresql_concurrence_processus.py::test_n_executeurs_se_disputent_une_ressource_un_seul_obtient_le_bail_puis_la_reprise_est_unique[sqlite]` |
| M13 | créneau de planificateur sans comparaison-échange | TUÉE | `tests/test_postgresql_concurrence_processus.py::test_n_processus_reservent_le_meme_creneau_de_planificateur_un_seul_passe[postgresql]` |
| M14 | réservation d'envoi sans condition « APPROUVE » | TUÉE | `tests/test_postgresql_concurrence_processus.py::test_n_processus_reservent_l_envoi_du_meme_brouillon_approuve_un_seul_part[postgresql]` |
| M15 | idempotence : conflit d'insertion non résolu par relecture | TUÉE | `tests/test_postgresql_concurrence_processus.py::test_n_processus_rejouent_la_meme_cle_d_idempotence_une_seule_execution_fraiche[postgresql]` |
| M16 | filtre des termes sains retiré (adaptateur PostgreSQL) | TUÉE | `tests/test_connaissances_postgresql.py::test_l_adaptateur_n_interprete_aucun_terme_non_normalise[postgresql--tau]` |
| M17 | filtre des termes sains retiré (adaptateur SQLite) | TUÉE | `tests/test_connaissances_postgresql.py::test_l_adaptateur_n_interprete_aucun_terme_non_normalise[sqlite--tau]` |
| M18 | colonne tsv ordinaire au lieu de générée | TUÉE | `tests/test_connaissances_postgresql.py::test_0053_sur_pg_cree_la_table_la_colonne_generee_l_index_gin_et_le_declencheur` |
| M19 | requête PostgreSQL sans ORDER BY | TUÉE | `tests/test_connaissances_postgresql.py::test_la_limite_garde_les_meilleurs_candidats_sur_les_deux_moteurs[postgresql]` |
| M20 | requête SQLite sans ORDER BY | TUÉE | `tests/test_connaissances_postgresql.py::test_la_limite_garde_les_meilleurs_candidats_sur_les_deux_moteurs[sqlite]` |
| M21 | déclencheur 0056 qualifié « public. » (installation dans un autre schéma impossible) | TUÉE | `tests/test_postgresql_migrations_chaine.py::test_la_chaine_s_installe_dans_deux_schemas_distincts_de_la_meme_base` |
| M22 | déclencheurs d'immuabilité de fusion_ap_ocr_sources et service_attestations_m4 non posés sur PostgreSQL | TUÉE | `tests/test_postgresql_parite_schema.py::test_toute_table_a_declencheurs_sur_sqlite_a_leur_equivalent_sur_postgresql` |
| M23 | colonnes evenement_id laissées à 128 caractères | TUÉE | `tests/test_postgresql_parite_schema.py::test_un_identifiant_d_evenement_de_160_caracteres_est_accepte_sur_les_deux_moteurs[postgresql]` |
| M24 | fuseau de session PostgreSQL non épinglé | TUÉE | `tests/test_postgresql_parite_schema.py::test_le_fuseau_de_session_est_epingle_a_utc_meme_si_la_base_a_un_autre_fuseau` |

Chaque mutation est appliquée SEULE au code d'un clone du dépôt, la cible de tests est rejouée (le témoin sans mutation est vert), le fichier est restauré. Résultats bruts : `preuves-postgresql/mutations.json`. **M04** est une mutation ÉQUIVALENTE : mettre ou non chaque terme entre guillemets ne change rien à la requête `websearch_to_tsquery` quand les termes ne contiennent que `[a-z0-9]` (même « or », devenu simple mot lorsqu'il suit un opérateur) ; la protection réelle est le filtre des termes sains, tué par M16/M17. M05, M16 et M17 avaient survécu à la première version des tests ; ils ont fermé les trous (limite de candidats, termes hostiles à l'adaptateur) et sont tués.

## 14. Ce qui n'est PAS prouvé

- **La plupart des consoles de saisie, le cron opérateur, la liaison de cibles, les grants CFO, le recalcul certifié M4, l'export
  de la base** : refusés sur PostgreSQL (§6). Ce qui a été observé en levant les gardes dans une copie jetable (§6.1) est un indice,
  pas une qualification.
- **Charge, latence, volume** : aucune mesure (quelques lignes par test). L'index GIN n'a pas été éprouvé à 100 000 fragments.
- **Durabilité** : `fsync=off` ; aucune coupure de courant, aucun `kill -9` du serveur, aucune réplication.
- **Pool de connexions externe** (PgBouncer en mode transaction), **plusieurs serveurs d'application** contre la même base,
  **multi-client** (une base ou un schéma par client, hormis l'installation de la chaîne dans deux schémas) : non testés.
- **SERIALIZABLE** : non utilisé ni testé (§10).
- **Interblocages** : aucun observé ; l'ordre des verrous n'a pas été audité hors des chemins éprouvés.
- **Le mode redirigé ne prouve que ce que les tests exercent** : les tests qui lisent le fichier SQLite, qui le passent à un
  sous-processus ou qui comptent sur un écouteur SQLite échouent pour une raison propre à SQLite (classe B) ; leur code de
  production sous-jacent n'a donc pas été exercé sur PostgreSQL par eux.
- **Les causes non établies** (classe « ? » du triage) : listées telles quelles ; aucune n'est présentée comme un défaut ni comme
  une réussite.
- **Intégration continue** : une étape a été ajoutée au job `frontiere-postgresql` (`ci.yml`) pour les 89 cas de ce banc ;
  elle n'a pas été exécutée sur GitHub (pas de pipeline ici).
- **Modèles ONNX locaux** (2 tests) : machine sans modèle.
- **Colonnes `Integer` 32 bits** (§5 L6) : latent.

## 15. Avant l'offre hébergée : ordre de travail proposé

1. Lever les gardes une par une, en commençant par celles dont la levée expérimentale est verte (§6.1), avec pour chaque module :
   verrou de ligne ou contrainte unique à la place de `BEGIN IMMEDIATE`, traduction de `EcritureConcurrente` en verdict typé,
   `length(cast(… AS BLOB))` → `octet_length`, suppression de `typeof()`.
2. Faire tourner la suite ordinaire sur PostgreSQL, **avec `--redirige`**, à chaque intégration (le banc existe ; une exécution complète
   prend une heure sur cette machine) et traiter tout écart comme un défaut : trois des six défauts de ce rapport ne se voient qu'ainsi.
3. Qualifier ce que ce banc ne couvre pas (§14) : durabilité, pool externe, charge, pgvector, multi-client.
