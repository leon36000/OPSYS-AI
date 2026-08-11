"""Configuration PostgreSQL autoritative (C05-001).

`DatabaseConfig` est un value-object FIGÉ (frozen) dont TOUTE la
validation vit dans `__post_init__` — fail fast à la construction,
jamais différée. Deux gardes indépendantes :
  - `dsn_secret_ref` doit être un NOM de secret, jamais un DSN déjà
    résolu (« refuser DSN en clair », cas RED obligatoire). Détecteur
    DÉDIÉ, volontairement distinct de `config.settings._INLINE_PATTERNS`
    (revue d'architecture AVANT code : ces motifs ciblent des clés
    API/tokens, aucun ne matche un DSN PostgreSQL — les réutiliser
    donnerait un refus « vert pour la mauvaise raison », déclenché par
    la seule heuristique de longueur).
  - `pool_min`/`pool_max`/`statement_timeout_ms` doivent être des
    entiers sains (« timeout et pool invalides bloquent », cas RED
    obligatoire). `bool` est un sous-type d'`int` en Python
    (`isinstance(True, int) is True`) — vérifié et EXCLU explicitement,
    sinon `statement_timeout_ms=True` passerait silencieusement.

Le refus « SQLite/in-memory comme profil production » n'est PAS ici :
`DatabaseConfig` ne connaît que le NOM du secret, jamais sa valeur
résolue — cette garde vit nécessairement dans `open_database`
(connection.py), seul point qui voit la cible réelle après résolution.
"""
from __future__ import annotations

from dataclasses import dataclass


class DsnEnClairRefuse(ValueError):
    """Levée par `DatabaseConfig.__post_init__` quand `dsn_secret_ref`
    ressemble à un DSN déjà résolu plutôt qu'à un nom de secret."""

    def __init__(self, motif: str) -> None:
        super().__init__(
            f"dsn_secret_ref ressemble à un DSN déjà résolu, pas un nom de secret ({motif})"
        )
        self.code = "VALIDATION"
        self.motif = motif


class ParametresPoolOuTimeoutInvalides(ValueError):
    """Levée par `DatabaseConfig.__post_init__` sur un pool ou un
    timeout invalide."""

    def __init__(self, raison: str) -> None:
        super().__init__(f"paramètres de pool/timeout invalides : {raison}")
        self.code = "VALIDATION"


_MOTS_CLES_LIBPQ = ("host=", "dbname=", "user=", "password=", "port=", "sslmode=")  # proof:allow — noms de mots-clés libpq pour la détection, aucune valeur de secret


def _detecter_dsn_clair(dsn_secret_ref: str) -> str | None:
    """Retourne le motif détecté si `dsn_secret_ref` ressemble à un DSN
    déjà résolu ; `None` si c'est un nom de secret légitime.

    LIMITATION CONNUE (revue scellée C05-001, objection mineure Kimi-K3
    confirmée vraie, non résolue en silence) : les heuristiques finales
    (caractère '@', espace, longueur > 40) peuvent refuser à tort un nom
    de secret légitime mais atypique (ex. chemin Vault long ou ARN
    Secrets Manager > 40 caractères, sans '://' ni '=' libpq). Choix de
    politique fail-closed délibéré et assumé (un faux positif bloque
    sans risque de sécurité ; un faux négatif laisserait passer un DSN
    en clair) — à revisiter si un provider futur bute réellement dessus."""
    if not isinstance(dsn_secret_ref, str) or not dsn_secret_ref.strip():
        return "vide ou non-chaîne"
    minuscule = dsn_secret_ref.lower()
    if "://" in minuscule:
        return "schéma URL (://)"
    if minuscule.startswith("sqlite:"):
        return "schéma sqlite:"
    if "=" in dsn_secret_ref and any(mc in minuscule for mc in _MOTS_CLES_LIBPQ):
        return "syntaxe keyword/value libpq"
    if "@" in dsn_secret_ref:
        return "caractère '@' (userinfo probable)"
    if " " in dsn_secret_ref:
        return "espace (valeur composite probable)"
    if len(dsn_secret_ref) > 40:
        return "longueur > 40 caractères (probable valeur, pas un nom)"
    return None


@dataclass(frozen=True)
class DatabaseConfig:
    dsn_secret_ref: str
    pool_min: int
    pool_max: int
    statement_timeout_ms: int

    def __post_init__(self) -> None:
        motif = _detecter_dsn_clair(self.dsn_secret_ref)
        if motif is not None:
            raise DsnEnClairRefuse(motif)

        for nom_champ, valeur in (
            ("pool_min", self.pool_min),
            ("pool_max", self.pool_max),
            ("statement_timeout_ms", self.statement_timeout_ms),
        ):
            # bool est un sous-type d'int en Python — exclu explicitement
            # AVANT le test isinstance(..., int), sinon True/False
            # passeraient silencieusement comme 1/0.
            if isinstance(valeur, bool) or not isinstance(valeur, int):
                raise ParametresPoolOuTimeoutInvalides(
                    f"{nom_champ} doit être un entier non booléen (reçu {valeur!r})"
                )

        if self.pool_min < 1:
            raise ParametresPoolOuTimeoutInvalides(
                f"pool_min doit être >= 1 (reçu {self.pool_min})"
            )
        if self.pool_max < self.pool_min:
            raise ParametresPoolOuTimeoutInvalides(
                f"pool_max ({self.pool_max}) doit être >= pool_min ({self.pool_min})"
            )
        if self.statement_timeout_ms <= 0:
            raise ParametresPoolOuTimeoutInvalides(
                f"statement_timeout_ms doit être > 0 (reçu {self.statement_timeout_ms})"
            )
