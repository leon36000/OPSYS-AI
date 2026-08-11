# Migrations Core — expand/contract (C05-002)

Ce répertoire porte les futures migrations PostgreSQL du Core (fichiers
`.sql` réels ajoutés à partir de C05-004 — cette tâche ne livre que le
moteur de validation et le squelette de répertoire, `versions/.gitkeep`).

`core/src/opsys_core/persistence/migrations.py` fournit
`MigrationPlan(version, phase, checksum, reversible)` et
`validate_migration(plan, sql) -> None` — un **validateur PUREMENT
STATIQUE** : il n'ouvre AUCUNE connexion et n'importe ni `psycopg` ni
`connection.py` (revue d'architecture AVANT code, confirmé : aucune
Sortie de cette tâche ne prévoit de table de suivi ni d'exécution
réelle — `validate_migration`, pas `apply_migration`).

## Vocabulaire des phases (figé)

Recoupé mécaniquement avec `migrations.py::_VOCABULAIRE_PHASES` par
`test_readme_vocabulaire_phases_bijectif_avec_le_code` — toute
divergence entre cette liste et le code casse ce test, jamais un
oubli silencieux. Zéro normalisation dans le code (`.strip()`/`.lower()`
élargirait silencieusement l'autorisation) : la valeur de `phase` doit
correspondre EXACTEMENT à l'un de ces quatre mots.

- `expand`
- `backfill`
- `switch`
- `contract`

Une migration additive (nouvelle table/colonne, toujours avec
`IF NOT EXISTS`) appartient à `expand`. Le déplacement de données
(`INSERT ... ON CONFLICT`, jamais un simple `INSERT`) appartient à
`backfill`. Le basculement du code applicatif vers le nouveau schéma
(hors périmètre SQL de cette tâche) appartient à `switch`. Le retrait
définitif de l'ancien schéma (`DROP`/`RENAME`/`TRUNCATE`) appartient à
`contract` — SEULE phase où un verbe destructif peut être autorisé, et
seulement sous la garde complète décrite ci-dessous.

## Dry-run

`validate_migration` **est** le dry-run : un verdict complet (checksum,
destructivité, idempotence) sans jamais toucher une base réelle. Il n'y
a pas de mode d'exécution séparé dans cette tâche — appeler
`validate_migration(plan, sql)` est le dry-run, littéralement le seul
mode disponible avant C05-003/C05-004.

## Rollback

Deux mécanismes, aucun des deux n'exécute quoi que ce soit ici :

1. **`MigrationPlan.reversible: bool`** — déclare si la migration EST
   accompagnée d'un chemin de retour arrière. `isinstance(reversible,
   bool)` strict (`migrations.py::ReversibleNonBooleen`) : une valeur
   non-bool truthy (ex. la chaîne `"false"`) ne doit JAMAIS pouvoir
   ouvrir l'autorisation destructive réservée à `reversible is True`.
2. **Convention future (fichiers `.sql` réels, à partir de C05-004)** :
   toute migration de phase `contract` (donc potentiellement
   destructive) DOIT porter une section de retour arrière explicite
   dans son fichier — soit un bloc commenté `-- ROLLBACK:` en fin de
   fichier, soit un fichier `.rollback.sql` apparié de même préfixe de
   version. Cette convention n'est pas encore mécaniquement gardée
   (aucun fichier `.sql` réel n'existe avant C05-004) — nommée ici en
   clair plutôt que laissée implicite, à garder par un test dédié
   quand les premiers fichiers réels seront ajoutés.

## Autorisation d'une migration destructive (phase `contract`)

Liste blanche par construction — le refus est le défaut
(`migrations.py::MigrationDestructiveRefusee`). Un verbe destructif
(`DROP`/`TRUNCATE`/`RENAME`, détection au niveau du token, pas de la
paire — `ALTER TABLE t DROP col` est valide en PostgreSQL sans le mot
`COLUMN`) n'est autorisé que si LES TROIS conditions suivantes sont
réunies simultanément :

1. `plan.phase == "contract"`.
2. `plan.reversible is True`.
3. Le texte SQL contient le marqueur exact `AUTORISATION-CONTRACT:<version>`
   où `<version>` est **la version de cette migration précise**
   (`plan.version`) — un marqueur copié depuis une autre migration ne
   fonctionne jamais.

## Idempotence par construction

`validate_migration` refuse toute forme non ré-exécutable :
`CREATE TABLE`/`CREATE INDEX` sans `IF NOT EXISTS`, `DROP TABLE`/
`DROP INDEX` sans `IF EXISTS`, `INSERT INTO` sans `ON CONFLICT`. Aucun
état de suivi (pas de table `schema_migrations`, aucune Sortie de cette
tâche ne le prévoit) : la preuve d'idempotence est la PURETÉ de
`validate_migration` lui-même — deux appels identiques donnent
toujours le même verdict.
