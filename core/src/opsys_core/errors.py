"""Taxonomie d'erreurs Core (C03-004).

CoreError : code STABLE et SÉRIALISABLE (fermé à la taxonomie ci-dessous),
JAMAIS de secret/PII dans safe_message — seul le TYPE de l'exception (pas
son message brut) y figure. La cause interne complète est préservée via
details_ref, un pointeur content-addressed (hash déterministe du repr()
de l'exception) — jamais la cause elle-même exposée directement. Toute
erreur inconnue devient UNKNOWN_FAILURE, jamais un succès silencieux
(CANON : « No error, timeout or missing tool becomes success »).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum


class ErrorCode(Enum):
    VALIDATION = "VALIDATION"
    POLICY_DENIED = "POLICY_DENIED"
    PREREQUISITE_MISSING = "PREREQUISITE_MISSING"
    CONFLICT = "CONFLICT"
    IN_DOUBT = "IN_DOUBT"
    EXTERNAL_FAILURE = "EXTERNAL_FAILURE"
    UNKNOWN_FAILURE = "UNKNOWN_FAILURE"


_CODES_VALIDES = {c.value for c in ErrorCode}


@dataclass(frozen=True)
class CoreError:
    code: str
    retryable: bool
    safe_message: str
    details_ref: str | None = None

    def __post_init__(self) -> None:
        if self.code not in _CODES_VALIDES:
            raise ValueError(
                f"code inconnu: {self.code!r} — doit être un membre de ErrorCode {sorted(_CODES_VALIDES)}"
            )


def mapper_exception(
    exc: BaseException,
    *,
    code: str = ErrorCode.EXTERNAL_FAILURE.value,
    retryable: bool = False,
) -> CoreError:
    """Convertit une exception Python BRUTE (potentiellement porteuse de
    secrets/PII dans son message) en CoreError SÛRE : le message brut de
    l'exception n'apparaît JAMAIS dans safe_message — seul le NOM DE TYPE
    y figure. La cause complète reste référencée par details_ref (hash
    sha256 déterministe de repr(exc), jamais le texte en clair) — la
    même exception (même type, même message) produit toujours le même
    details_ref, permettant une corrélation fiable sans jamais exposer
    la cause elle-même."""
    if code not in _CODES_VALIDES:
        code = ErrorCode.UNKNOWN_FAILURE.value
    empreinte = hashlib.sha256(repr(exc).encode("utf-8")).hexdigest()
    return CoreError(
        code=code,
        retryable=retryable,
        safe_message=f"Échec interne ({type(exc).__name__}) — cause référencée par details_ref",
        details_ref=f"sha256:{empreinte}",
    )
