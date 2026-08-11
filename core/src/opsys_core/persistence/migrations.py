"""Moteur de migrations expand/contract, VALIDATEUR PUREMENT STATIQUE (C05-002).

`validate_migration(plan, sql) -> None` n'ouvre AUCUNE connexion, n'importe
ni `psycopg` ni `connection.py` — c'est le nom même de la fonction
(« validate », pas « apply »/« run ») qui porte cette discipline. Confirmé
par revue d'architecture AVANT code (subagent architecte, Claude Opus 5
natif) : aucune Sortie de cette tâche ne prévoit de table de suivi ni de
connexion réelle, C05-003 (unité de travail transactionnelle) et C05-004
(premier fichier .sql réel) sont les tâches qui exécutent, pas celle-ci.

« Dry-run » et « rollback » (bornes d'implémentation) sont donc rendus
SANS EXÉCUTION :
  - dry-run = `validate_migration` lui-même (verdict sans toucher la base).
  - rollback = `MigrationPlan.reversible` + exigence d'une section de
    retour arrière documentée dans core/migrations/README.md pour toute
    migration destructive future — cf. README pour la convention.

3 cas RED obligatoires (tasks/C05-002.md), chacun un détecteur DÉDIÉ :
  1. bloquer DROP/RENAME/TRUNCATE destructif SAUF si `plan.phase ==
     "contract"` ET `plan.reversible is True` ET le SQL porte un marqueur
     d'autorisation contenant `plan.version` (non copiable-collable d'une
     migration à l'autre) — LISTE BLANCHE par construction (le refus est
     le défaut), jamais une liste noire de verbes qui laisserait passer
     l'inconnu (même discipline que `connection.py::_detecter_cible_non_
     postgresql`, C05-001 : « une liste noire serait fail-open »).
  2. checksum obligatoire, en DEUX gardes séparées (revue d'architecture
     AVANT code : une seule classe d'exception rendrait une mutation du
     contrôle de FORME indétectable, la branche CONTENU lèverait quand
     même) — forme (64 hex minuscules) à la CONSTRUCTION de MigrationPlan
     (fail fast, comme DatabaseConfig C05-001), contenu (`==
     sha256(sql)` RÉEL, pas seulement présent) dans `validate_migration`
     (seul point qui voit `sql`).
  3. idempotence PURE (aucun état de suivi, aucune Sortie de cette tâche
     ne prévoit de table `schema_migrations`) : `validate_migration`
     exige la ré-exécutabilité PAR CONSTRUCTION du SQL (CREATE sans IF
     NOT EXISTS, DROP sans IF EXISTS, INSERT sans ON CONFLICT ⇒ refusés)
     — deux appels successifs avec `(plan, sql)` identiques donnent
     TOUJOURS le même verdict, aucun effet observable (aucun état
     module-level, même discipline que composition.py/provider_registry.py
     C04-004).
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

# Vocabulaire de phases FERMÉ — zéro normalisation (.strip()/.lower()
# élargirait silencieusement l'autorisation, revue d'architecture AVANT
# code, point (c)). Recoupé mécaniquement avec core/migrations/README.md
# par test_dependency_rules_toml_couvre_migrations_sans_modification.
_VOCABULAIRE_PHASES = frozenset({"expand", "backfill", "switch", "contract"})

_CHECKSUM_RE = re.compile(r"^[0-9a-f]{64}$")

# Token-level, insensible à la casse : `ALTER TABLE t DROP col` est valide
# en PostgreSQL SANS le mot COLUMN — un motif `DROP\s+COLUMN` raterait ce
# cas, `\bDROP\b` non (revue d'architecture AVANT code, point 1).
_MOTIFS_DESTRUCTIFS = re.compile(r"\b(DROP|TRUNCATE|RENAME)\b", re.IGNORECASE)

# search() (pas finditer()) : détection booléenne « au moins une occurrence
# quelque part », jamais une énumération multi-match traitée différemment
# par occurrence — le bug de classe « search() en boucle masque les
# occurrences suivantes » (déjà mesuré dans check_module_isolation.py) ne
# s'applique pas ici, un seul appel hors boucle.
_CREATE_SANS_IF_NOT_EXISTS = re.compile(
    r"\bCREATE\s+(TABLE|INDEX)\s+(?!IF\s+NOT\s+EXISTS)", re.IGNORECASE
)
_DROP_SANS_IF_EXISTS = re.compile(
    r"\bDROP\s+(TABLE|INDEX)\s+(?!IF\s+EXISTS)", re.IGNORECASE
)
_INSERT_INTO = re.compile(r"\bINSERT\s+INTO\b", re.IGNORECASE)
_ON_CONFLICT = re.compile(r"\bON\s+CONFLICT\b", re.IGNORECASE)


def _marqueur_autorisation(version: str) -> str:
    """Marqueur d'autorisation LIÉ à la version — copier un marqueur
    d'une autre migration ne fonctionne jamais (revue d'architecture
    AVANT code, point 1 : « non copiable-collable d'une migration à
    l'autre »)."""
    return f"AUTORISATION-CONTRACT:{version}"


class PhaseInvalide(ValueError):
    """Levée par `MigrationPlan.__post_init__` quand `phase` n'appartient
    pas au vocabulaire fermé — AUCUNE normalisation avant comparaison."""

    def __init__(self, phase: object) -> None:
        super().__init__(
            f"phase {phase!r} hors vocabulaire fermé {sorted(_VOCABULAIRE_PHASES)}"
        )
        self.code = "VALIDATION"


class ReversibleNonBooleen(ValueError):
    """Levée par `MigrationPlan.__post_init__` quand `reversible` n'est
    pas strictement un `bool`. Piège INVERSÉ de C05-001 (`config.py` :
    `bool` est un sous-type d'`int`, exclu pour ne pas être PASSÉ comme
    entier) : ici une valeur non-bool truthy (ex. `reversible="false"`,
    une chaîne non vide) OUVRIRAIT la seule autorisation destructive du
    système si elle n'était pas rejetée explicitement — revue
    d'architecture AVANT code, point 6(a)."""

    def __init__(self, valeur: object) -> None:
        super().__init__(f"reversible doit être un bool strict (reçu {valeur!r})")
        self.code = "VALIDATION"


class ChecksumFormatInvalide(ValueError):
    """Levée par `MigrationPlan.__post_init__` quand `checksum` n'est pas
    64 caractères hexadécimaux minuscules — garde de FORME uniquement,
    distincte de `ChecksumIncorrect` (garde de CONTENU) pour qu'une
    mutation de l'une des deux gardes reste détectable séparément."""

    def __init__(self, checksum: object) -> None:
        super().__init__(
            f"checksum doit être 64 caractères hexadécimaux minuscules (reçu {checksum!r})"
        )
        self.code = "VALIDATION"


class ChecksumIncorrect(ValueError):
    """Levée par `validate_migration` quand `plan.checksum` ne correspond
    PAS à `sha256(sql)` réel — garde de CONTENU, vit ici (seul point qui
    voit `sql`), pas dans `MigrationPlan` (qui ne connaît que le
    checksum déclaré, jamais le SQL réel avant l'appel)."""

    def __init__(self) -> None:
        super().__init__("checksum déclaré ne correspond pas au sha256 réel du SQL")
        self.code = "CONFLICT"


class MigrationDestructiveRefusee(ValueError):
    """Levée par `validate_migration` quand le SQL contient un verbe
    destructif (DROP/TRUNCATE/RENAME) sans autorisation explicite
    complète (phase contract + reversible=True + marqueur lié à la
    version). LISTE BLANCHE par construction : le refus est le défaut,
    l'autorisation est l'exception qui doit être prouvée."""

    def __init__(self, motif: str) -> None:
        super().__init__(f"migration destructive refusée : {motif}")
        self.code = "POLICY_DENIED"
        self.motif = motif


class MigrationNonIdempotente(ValueError):
    """Levée par `validate_migration` quand le SQL n'est pas
    ré-exécutable PAR CONSTRUCTION (CREATE sans IF NOT EXISTS, DROP sans
    IF EXISTS, INSERT sans ON CONFLICT). Propriété STATIQUE du texte SQL
    — aucune connexion, aucun état de suivi requis."""

    def __init__(self, motif: str) -> None:
        super().__init__(f"migration non idempotente par construction : {motif}")
        self.code = "VALIDATION"
        self.motif = motif


@dataclass(frozen=True)
class MigrationPlan:
    version: str
    phase: str
    checksum: str
    reversible: bool

    def __post_init__(self) -> None:
        if not isinstance(self.version, str) or not self.version.strip():
            raise ValueError("version doit être une chaîne non vide")

        if self.phase not in _VOCABULAIRE_PHASES:
            raise PhaseInvalide(self.phase)

        # isinstance(reversible, bool) STRICT — AVANT toute autre garde,
        # même position défensive que le piège bool de C05-001.
        if not isinstance(self.reversible, bool):
            raise ReversibleNonBooleen(self.reversible)

        if not isinstance(self.checksum, str) or not _CHECKSUM_RE.match(self.checksum):
            raise ChecksumFormatInvalide(self.checksum)


def validate_migration(plan: MigrationPlan, sql: str) -> None:
    """Validateur PUREMENT STATIQUE — aucune connexion, aucun état
    module-level, aucun effet observable. Deux appels successifs avec
    `(plan, sql)` identiques donnent TOUJOURS le même verdict (preuve
    d'idempotence par pureté, cas RED 3)."""
    # 1) Contenu du checksum — AVANT toute autre garde de contenu (fail
    # fast sur l'intégrité du texte SQL lui-même).
    checksum_reel = hashlib.sha256(sql.encode("utf-8")).hexdigest()
    if checksum_reel != plan.checksum:
        raise ChecksumIncorrect()

    # 2) Destructif : liste blanche — refusé SAUF autorisation complète.
    if _MOTIFS_DESTRUCTIFS.search(sql) is not None:
        marqueur = _marqueur_autorisation(plan.version)
        autorise = (
            plan.phase == "contract"
            and plan.reversible is True
            and marqueur in sql
        )
        if not autorise:
            raise MigrationDestructiveRefusee(
                "verbe destructif (DROP/TRUNCATE/RENAME) détecté sans "
                f"autorisation complète (phase=contract, reversible=True, "
                f"marqueur {marqueur!r} présent dans le SQL)"
            )

    # 3) Idempotence par construction — propriété STATIQUE du texte SQL.
    if _CREATE_SANS_IF_NOT_EXISTS.search(sql) is not None:
        raise MigrationNonIdempotente("CREATE TABLE/INDEX sans IF NOT EXISTS")
    if _DROP_SANS_IF_EXISTS.search(sql) is not None:
        raise MigrationNonIdempotente("DROP TABLE/INDEX sans IF EXISTS")
    if _INSERT_INTO.search(sql) is not None and _ON_CONFLICT.search(sql) is None:
        raise MigrationNonIdempotente("INSERT INTO sans ON CONFLICT")
