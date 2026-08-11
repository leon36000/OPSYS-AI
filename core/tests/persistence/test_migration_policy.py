"""Tests pour core/src/opsys_core/persistence/migrations.py (C05-002) —
moteur de migrations expand/contract, VALIDATEUR PUREMENT STATIQUE.

Couvre les 3 cas RED obligatoires de tasks/C05-002.md :
  1. bloquer DROP/rename destructif sans phase contract et gate
  2. checksum obligatoire
  3. migration appliquée deux fois reste idempotente

Conception revue par architecture AVANT code (subagent `architecte`,
Claude Opus 5 natif, verdict complet dans l'Evidence Bundle) : liste
blanche par phase (jamais une liste noire de verbes — fail-open),
double classe d'exception pour le checksum (forme vs contenu, sinon
une mutation du contrôle de forme serait indétectable), piège `bool`
INVERSÉ sur `reversible` (une valeur non-bool truthy ouvrirait la
seule autorisation destructive du système), `validate_migration`
purement statique (aucune connexion, confirmé par l'architecte : aucune
Sortie de cette tâche ne prévoit de table de suivi ni d'exécution
réelle — C05-003/C05-004 exécutent, pas celle-ci), aucune modification
de `core/dependency-rules.toml` (opsys_core/persistence/ est déjà un
PRÉFIXE RÉPERTOIRE dans [layers.adapters].paths depuis C05-001,
migrations.py est un NOUVEAU FICHIER dans ce répertoire EXISTANT).

Aucun `conftest.py` (convention déjà mesurée : aucun n'existe sous
core/tests/, chaque fichier insère core/src lui-même — même patron que
test_postgres_configuration.py, C05-001).
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pytest

from opsys_core.persistence.migrations import (
    ChecksumFormatInvalide,
    ChecksumIncorrect,
    MigrationDestructiveRefusee,
    MigrationNonIdempotente,
    MigrationPlan,
    PhaseInvalide,
    ReversibleNonBooleen,
    validate_migration,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _checksum(sql: str) -> str:
    return hashlib.sha256(sql.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Cas RED 1 — bloquer DROP/rename destructif sans phase contract et gate
# ---------------------------------------------------------------------------


def test_cr_er_le_moteur_de_migrations_expand_contract_1():
    """LISTE BLANCHE par construction : un verbe destructif est refusé
    SAUF autorisation complète (phase=contract + reversible=True +
    marqueur lié à LA VERSION EXACTE, non copiable-collable). SQL
    idempotence-safe (IF EXISTS) délibérément, pour isoler PROPREMENT
    la garde destructive de la garde d'idempotence dans les mutations
    (sinon un DROP sans IF EXISTS serait aussi intercepté par cette
    2e garde, masquant une mutation de la 1re)."""
    sql_drop = "DROP TABLE IF EXISTS ancien_index;"

    # 1a. DROP en phase expand -> refusé (destructif hors phase contract)
    plan_expand = MigrationPlan(
        version="0001_expand_test", phase="expand", checksum=_checksum(sql_drop), reversible=True
    )
    with pytest.raises(MigrationDestructiveRefusee):
        validate_migration(plan_expand, sql_drop)

    # 1b. DROP en phase contract SANS reversible=True -> refusé
    plan_non_reversible = MigrationPlan(
        version="0001_contract_test", phase="contract", checksum=_checksum(sql_drop), reversible=False
    )
    with pytest.raises(MigrationDestructiveRefusee):
        validate_migration(plan_non_reversible, sql_drop)

    # 1c. DROP en phase contract AVEC reversible=True MAIS SANS marqueur -> refusé
    plan_sans_marqueur = MigrationPlan(
        version="0001_contract_test", phase="contract", checksum=_checksum(sql_drop), reversible=True
    )
    with pytest.raises(MigrationDestructiveRefusee):
        validate_migration(plan_sans_marqueur, sql_drop)

    # 1d. RENAME et TRUNCATE aussi détectés (pas seulement DROP) — token
    # nu \bDROP\b etc., pas la paire "DROP COLUMN" (ALTER TABLE t DROP col
    # est valide en PostgreSQL SANS le mot COLUMN).
    for sql_verbe in ("RENAME TABLE a TO b;", "TRUNCATE TABLE x;", "ALTER TABLE t DROP col;"):
        plan_verbe = MigrationPlan(
            version="0001_verbe_test", phase="expand", checksum=_checksum(sql_verbe), reversible=True
        )
        with pytest.raises(MigrationDestructiveRefusee):
            validate_migration(plan_verbe, sql_verbe)

    # 1e. Contrôle positif : DROP en phase contract, reversible=True, AVEC
    # le marqueur exact lié à LA version -> accepté.
    sql_autorise = "-- AUTORISATION-CONTRACT:0099_autorise_test\nDROP TABLE IF EXISTS ancien_index;"
    plan_autorise = MigrationPlan(
        version="0099_autorise_test", phase="contract", checksum=_checksum(sql_autorise), reversible=True
    )
    validate_migration(plan_autorise, sql_autorise)  # ne lève pas

    # 1f. Contrôle positif : SQL additif jamais bloqué par CETTE garde,
    # même en phase expand (IF NOT EXISTS le rend aussi idempotent, cf.
    # cas RED 3 — double couverture volontaire, pas un hasard).
    sql_additif = "CREATE TABLE IF NOT EXISTS nouvelle(id int);"
    plan_additif = MigrationPlan(
        version="0002_additif_test", phase="expand", checksum=_checksum(sql_additif), reversible=False
    )
    validate_migration(plan_additif, sql_additif)  # ne lève pas

    # 1g. Le marqueur d'une AUTRE version ne fonctionne pas — non
    # copiable-collable d'une migration à l'autre.
    sql_mauvais_marqueur = "-- AUTORISATION-CONTRACT:9999_autre_migration\nDROP TABLE ancien_index;"
    plan_mauvais_marqueur = MigrationPlan(
        version="0001_contract_test",
        phase="contract",
        checksum=_checksum(sql_mauvais_marqueur),
        reversible=True,
    )
    with pytest.raises(MigrationDestructiveRefusee):
        validate_migration(plan_mauvais_marqueur, sql_mauvais_marqueur)


def test_reversible_non_booleen_refuse_a_la_construction():
    """Piège INVERSÉ du bool de C05-001 : une valeur non-bool truthy
    (ex. la CHAÎNE "false", non vide donc truthy en Python) OUVRIRAIT la
    seule autorisation destructive du système si elle passait comme
    `reversible`. isinstance(x, bool) STRICT, à LA CONSTRUCTION."""
    for valeur_non_bool in ("false", 1, 0, "true", None):
        with pytest.raises(ReversibleNonBooleen):
            MigrationPlan(
                version="0001_bool_test",
                phase="expand",
                checksum=_checksum("SELECT 1;"),
                reversible=valeur_non_bool,
            )

    # Contrôle positif : bool strict accepté des deux côtés.
    MigrationPlan(version="0001_bool_test", phase="expand", checksum=_checksum("SELECT 1;"), reversible=True)
    MigrationPlan(version="0001_bool_test", phase="expand", checksum=_checksum("SELECT 1;"), reversible=False)


def test_phase_hors_vocabulaire_ferme_refusee_sans_normalisation():
    """Vocabulaire fermé, ZÉRO normalisation — .strip()/.lower() élargirait
    silencieusement l'autorisation (revue d'architecture AVANT code)."""
    for phase_invalide in ("CONTRACT", " contract ", "contract\n", "delete", ""):
        with pytest.raises(PhaseInvalide):
            MigrationPlan(
                version="0001_phase_test",
                phase=phase_invalide,
                checksum=_checksum("SELECT 1;"),
                reversible=False,
            )


# ---------------------------------------------------------------------------
# Cas RED 2 — checksum obligatoire
# ---------------------------------------------------------------------------


def test_cr_er_le_moteur_de_migrations_expand_contract_2():
    """Deux gardes SÉPARÉES (revue d'architecture AVANT code) : forme (64
    hex minuscules) À LA CONSTRUCTION, contenu (== sha256(sql) RÉEL) dans
    validate_migration — une mutation de l'une reste détectable sans
    l'autre (une seule classe d'exception rendrait la garde de forme
    indétectable, la branche contenu lèverait quand même)."""
    sql = "CREATE TABLE IF NOT EXISTS t(id int);"

    # 2a. Format checksum invalide (pas 64 hex minuscules) -> refusé À LA
    # CONSTRUCTION de MigrationPlan, jamais différé à validate_migration.
    for mauvais_checksum in ("", "abc", "x" * 64, hashlib.sha256(sql.encode()).hexdigest().upper()):
        with pytest.raises(ChecksumFormatInvalide):
            MigrationPlan(version="0001_checksum_test", phase="expand", checksum=mauvais_checksum, reversible=False)

    # 2b. Format valide mais CONTENU faux (checksum d'un AUTRE texte) ->
    # refusé à validate_migration — discrimination : le secret est résolu
    # avec succès (forme OK), la garde vient du CONTENU, pas de la forme.
    checksum_dun_autre_sql = hashlib.sha256(b"AUTRE CONTENU SANS RAPPORT").hexdigest()
    plan_checksum_faux = MigrationPlan(
        version="0001_checksum_test", phase="expand", checksum=checksum_dun_autre_sql, reversible=False
    )
    with pytest.raises(ChecksumIncorrect):
        validate_migration(plan_checksum_faux, sql)

    # 2c. Contrôle positif : checksum réellement correspondant -> accepté.
    plan_ok = MigrationPlan(version="0001_checksum_test", phase="expand", checksum=_checksum(sql), reversible=False)
    validate_migration(plan_ok, sql)  # ne lève pas

    # 2d. Discrimination forte : un SQL modifié APRÈS coup avec l'ANCIEN
    # checksum est détecté — preuve que le contrôle vérifie le CONTENU
    # réel, pas seulement la PRÉSENCE d'un champ non vide.
    sql_modifie = sql + " -- ligne ajoutée après le calcul du checksum"
    with pytest.raises(ChecksumIncorrect):
        validate_migration(plan_ok, sql_modifie)


# ---------------------------------------------------------------------------
# Cas RED 3 — migration appliquée deux fois reste idempotente
# ---------------------------------------------------------------------------


def test_cr_er_le_moteur_de_migrations_expand_contract_3():
    """Idempotence PURE (aucune Sortie de cette tâche ne prévoit de table
    de suivi/connexion) : ré-exécutabilité PAR CONSTRUCTION du SQL +
    absence d'effet observable entre deux appels identiques successifs."""
    # 3a. CREATE TABLE sans IF NOT EXISTS -> refusé (pas idempotent par construction).
    sql_create_pas_idempotent = "CREATE TABLE t(id int);"
    plan_create = MigrationPlan(
        version="0001_idempotence_test",
        phase="expand",
        checksum=_checksum(sql_create_pas_idempotent),
        reversible=False,
    )
    with pytest.raises(MigrationNonIdempotente):
        validate_migration(plan_create, sql_create_pas_idempotent)

    # 3b. INSERT sans ON CONFLICT -> refusé.
    sql_insert_pas_idempotent = "INSERT INTO t(id) VALUES (1);"
    plan_insert = MigrationPlan(
        version="0002_idempotence_test",
        phase="backfill",
        checksum=_checksum(sql_insert_pas_idempotent),
        reversible=False,
    )
    with pytest.raises(MigrationNonIdempotente):
        validate_migration(plan_insert, sql_insert_pas_idempotent)

    # 3c. Contrôle positif : formes idempotentes par construction -> acceptées.
    sql_idempotent = (
        "CREATE TABLE IF NOT EXISTS t(id int); "
        "INSERT INTO t(id) VALUES (1) ON CONFLICT DO NOTHING;"
    )
    plan_idempotent = MigrationPlan(
        version="0003_idempotence_test", phase="expand", checksum=_checksum(sql_idempotent), reversible=False
    )
    validate_migration(plan_idempotent, sql_idempotent)  # ne lève pas

    # 3d. PURETÉ — preuve directe du cas RED nommé : rejouer EXACTEMENT le
    # même (plan, sql) une 2e fois donne TOUJOURS le même verdict, aucun
    # état de suivi caché n'a mémorisé un premier passage.
    validate_migration(plan_idempotent, sql_idempotent)  # 2e appel identique, toujours accepté
    with pytest.raises(MigrationNonIdempotente):
        validate_migration(plan_create, sql_create_pas_idempotent)  # 2e appel identique, toujours refusé

    # 3e. Contrôle positif : DROP TABLE IF EXISTS (idempotent par
    # construction) autorisé en phase contract avec le marqueur — les cas
    # RED 1 et RED 3 se recoupent ici sans se contredire.
    sql_drop_idempotent = "-- AUTORISATION-CONTRACT:0004_idempotence_test\nDROP TABLE IF EXISTS ancien;"
    plan_drop_idempotent = MigrationPlan(
        version="0004_idempotence_test",
        phase="contract",
        checksum=_checksum(sql_drop_idempotent),
        reversible=True,
    )
    validate_migration(plan_drop_idempotent, sql_drop_idempotent)  # ne lève pas


# ---------------------------------------------------------------------------
# Corrections issues de la revue scellée tour 1 (civ_review) — 6 objections
# (4 Kimi-K3 dont 2 MAJEURES, 2 DeepSeek), TOUTES vérifiées vraies par
# reproduction directe AVANT correction (jamais acceptées sur la seule
# autorité des reviewers).
# ---------------------------------------------------------------------------


def test_idempotence_create_couvre_les_formes_hors_table_index():
    """Kimi-K3 MAJEURE (tour 1, confirmée vraie) : le motif original
    n'exigeait IF NOT EXISTS qu'immédiatement après CREATE TABLE/INDEX —
    CREATE UNIQUE INDEX, CREATE SEQUENCE, CREATE SCHEMA, CREATE EXTENSION
    sans IF NOT EXISTS n'étaient JAMAIS détectés. Corrigé : toute
    instruction contenant CREATE doit porter IF NOT EXISTS QUELQUE PART
    dans CETTE MÊME instruction."""
    for sql_verbe in (
        "CREATE UNIQUE INDEX idx ON t(c);",
        "CREATE SEQUENCE seq_id;",
        "CREATE SCHEMA nouveau;",
        "CREATE EXTENSION pgcrypto;",
    ):
        plan = MigrationPlan(
            version="0005_create_forme_test", phase="expand", checksum=_checksum(sql_verbe), reversible=False
        )
        with pytest.raises(MigrationNonIdempotente):
            validate_migration(plan, sql_verbe)

    # Contrôle positif : les mêmes formes AVEC IF NOT EXISTS sont acceptées.
    for sql_verbe_ok in (
        "CREATE UNIQUE INDEX IF NOT EXISTS idx ON t(c);",
        "CREATE SEQUENCE IF NOT EXISTS seq_id;",
    ):
        plan_ok = MigrationPlan(
            version="0005_create_forme_test", phase="expand", checksum=_checksum(sql_verbe_ok), reversible=False
        )
        validate_migration(plan_ok, sql_verbe_ok)  # ne lève pas


def test_idempotence_insert_verifiee_par_instruction_pas_globalement():
    """Kimi-K3 MAJEURE (tour 1, confirmée vraie) : un seul ON CONFLICT
    n'importe où dans un fichier multi-instructions blanchissait TOUS les
    INSERT INTO, y compris ceux sans leur PROPRE ON CONFLICT. Corrigé :
    vérification PAR INSTRUCTION (découpage par ';')."""
    sql_mixte = (
        "INSERT INTO a(id) VALUES (1) ON CONFLICT DO NOTHING; "
        "INSERT INTO b(id) VALUES (2);"
    )
    plan = MigrationPlan(
        version="0006_insert_instruction_test", phase="backfill", checksum=_checksum(sql_mixte), reversible=False
    )
    with pytest.raises(MigrationNonIdempotente):
        validate_migration(plan, sql_mixte)

    # Contrôle positif : les DEUX instructions avec leur propre ON CONFLICT.
    sql_deux_ok = (
        "INSERT INTO a(id) VALUES (1) ON CONFLICT DO NOTHING; "
        "INSERT INTO b(id) VALUES (2) ON CONFLICT DO NOTHING;"
    )
    plan_ok = MigrationPlan(
        version="0006_insert_instruction_test", phase="backfill", checksum=_checksum(sql_deux_ok), reversible=False
    )
    validate_migration(plan_ok, sql_deux_ok)  # ne lève pas


def test_marqueur_autorisation_refuse_collision_par_prefixe_de_version():
    """Kimi-K3 mineure (tour 1, confirmée vraie) : le marqueur était
    vérifié par sous-chaîne (`in`), donc le marqueur de la version
    "0001" (préfixe) matchait dans un SQL portant le marqueur de la
    version "0001_hotfix" (une AUTRE migration). Corrigé : ancrage par
    lookahead négative sur caractère non-espace après la version."""
    sql_avec_marqueur_dune_autre_version = (
        "-- AUTORISATION-CONTRACT:0001_hotfix\nDROP TABLE IF EXISTS ancien_index;"
    )
    plan = MigrationPlan(
        version="0001",
        phase="contract",
        checksum=_checksum(sql_avec_marqueur_dune_autre_version),
        reversible=True,
    )
    with pytest.raises(MigrationDestructiveRefusee):
        validate_migration(plan, sql_avec_marqueur_dune_autre_version)

    # Contrôle positif : le marqueur EXACT (version complète, terminé par
    # un espace/saut de ligne) autorise toujours.
    sql_marqueur_exact = "-- AUTORISATION-CONTRACT:0001\nDROP TABLE IF EXISTS ancien_index;"
    plan_ok = MigrationPlan(
        version="0001", phase="contract", checksum=_checksum(sql_marqueur_exact), reversible=True
    )
    validate_migration(plan_ok, sql_marqueur_exact)  # ne lève pas


def test_checksum_format_refuse_65_caracteres_avec_saut_de_ligne_final():
    """Kimi-K3 mineure (tour 1, confirmée vraie) : `re.match(r"^[0-9a-f]
    {64}$", ...)` — `$` matche aussi juste avant un saut de ligne
    terminal en Python, donc un checksum de 65 caractères (64 hex + un
    `\\n` final) passait à tort la garde de FORME. Corrigé :
    `.fullmatch()` sans ancres `^$`."""
    checksum_65_caracteres = "a" * 64 + "\n"
    with pytest.raises(ChecksumFormatInvalide):
        MigrationPlan(
            version="0007_checksum_65_test", phase="expand", checksum=checksum_65_caracteres, reversible=False
        )


def test_mot_destructif_dans_un_commentaire_ne_declenche_pas_le_refus():
    """DeepSeek mineure (tour 1, confirmée vraie) : un mot destructif
    (DROP/TRUNCATE/RENAME) MENTIONNÉ dans un commentaire SQL (`-- ...`)
    n'est PAS un verbe SQL réel — corrigé : les commentaires sont
    retirés AVANT la détection de mots-clés destructifs ET idempotence."""
    sql_commentaire_seulement = (
        "-- ce commentaire mentionne DROP mais n'en fait pas un\n"
        "CREATE TABLE IF NOT EXISTS t(id int);"
    )
    plan = MigrationPlan(
        version="0008_commentaire_test", phase="expand", checksum=_checksum(sql_commentaire_seulement), reversible=False
    )
    validate_migration(plan, sql_commentaire_seulement)  # ne lève pas (ni destructif ni non-idempotent)


def test_insert_where_not_exists_reste_refuse_biais_conservateur_assume():
    """DeepSeek mineure (tour 1, confirmée vraie) : `INSERT ... SELECT
    ... WHERE NOT EXISTS` est une forme idempotente ALTERNATIVE à `ON
    CONFLICT`, mais N'EST PAS reconnue comme telle — DÉLIBÉRÉMENT NON
    CORRIGÉ (biais conservateur assumé : le faux négatif, SQL sûr
    rejeté, est la direction SÛRE du fail-closed ; élargir la
    reconnaissance de formes ajouterait de la surface de motif pour un
    bénéfice de confort, pas de sûreté). Ce test PROUVE le comportement
    documenté plutôt que de le laisser implicite — s'il devient vert un
    jour sans intention explicite, un changement de comportement non
    documenté aura eu lieu."""
    sql_where_not_exists = (
        "INSERT INTO t(id) SELECT 1 WHERE NOT EXISTS (SELECT 1 FROM t WHERE id=1);"
    )
    plan = MigrationPlan(
        version="0009_where_not_exists_test",
        phase="backfill",
        checksum=_checksum(sql_where_not_exists),
        reversible=False,
    )
    with pytest.raises(MigrationNonIdempotente):
        validate_migration(plan, sql_where_not_exists)


# ---------------------------------------------------------------------------
# Croisement avec le harnais existant — preuve, pas supposition
# ---------------------------------------------------------------------------


def test_dependency_rules_toml_couvre_migrations_sans_modification():
    """L'architecte a confirmé (revue AVANT code) qu'AUCUNE modification
    de dependency-rules.toml n'est nécessaire : opsys_core/persistence/
    est déjà un PRÉFIXE RÉPERTOIRE dans [layers.adapters].paths (ajouté
    C05-001), et migrations.py est un NOUVEAU FICHIER dans ce répertoire
    EXISTANT (contrairement à compat/ et persistence/ eux-mêmes, qui
    introduisaient un NOUVEAU répertoire). Ce test PROUVE l'affirmation
    plutôt que de la supposer."""
    import tomllib

    regles = tomllib.loads((_REPO_ROOT / "core" / "dependency-rules.toml").read_text(encoding="utf-8"))
    chemins_adapters = regles["layers"]["adapters"]["paths"]
    assert any(p.rstrip("/") == "opsys_core/persistence" for p in chemins_adapters), (
        f"'opsys_core/persistence/' absent de [layers.adapters].paths : {chemins_adapters}"
    )
    chemin_migrations = _REPO_ROOT / "core" / "src" / "opsys_core" / "persistence" / "migrations.py"
    assert chemin_migrations.is_file(), "migrations.py doit exister sous opsys_core/persistence/"
    # Vocabulaire de couches toujours EXACT (aucune 6e couche ajoutée).
    assert set(regles["layers"]) == {"kernel", "domain", "ports", "application", "adapters"}


def test_validate_migration_naimporte_ni_psycopg_ni_connection():
    """Confirmé par l'architecte (revue AVANT code, point 5) : validateur
    PUREMENT STATIQUE, aucune connexion réelle. Preuve mécanique plutôt
    que déclarative : le module source ne contient AUCUN import de
    psycopg ni de connection.py."""
    source = (
        _REPO_ROOT / "core" / "src" / "opsys_core" / "persistence" / "migrations.py"
    ).read_text(encoding="utf-8")
    assert "import psycopg" not in source
    assert "from .connection" not in source
    assert "from opsys_core.persistence.connection" not in source


def test_readme_vocabulaire_phases_bijectif_avec_le_code():
    """Croisement bijectif (revue d'architecture AVANT code, point 5) :
    le vocabulaire de phases documenté dans core/migrations/README.md
    doit être EXACTEMENT le même ensemble que celui figé dans le code —
    ni sous-ensemble, ni sur-ensemble, avec garde de non-vacuité (un
    README vide ou un vocabulaire vide passerait sinon silencieusement)."""
    import re

    from opsys_core.persistence.migrations import _VOCABULAIRE_PHASES

    readme = (_REPO_ROOT / "core" / "migrations" / "README.md").read_text(encoding="utf-8")
    phases_readme = set(re.findall(r"^- `(\w+)`$", readme, re.MULTILINE))
    assert phases_readme, "aucune phase trouvée dans le README — garde de non-vacuité"
    assert phases_readme == _VOCABULAIRE_PHASES, (
        f"README ({sorted(phases_readme)}) != code ({sorted(_VOCABULAIRE_PHASES)})"
    )
