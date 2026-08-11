"""Taxonomie d'erreurs Core (C03-004).

CoreError : code STABLE et SÉRIALISABLE (fermé à la taxonomie ci-dessous),
JAMAIS de secret/PII dans safe_message — seul le TYPE de l'exception (pas
son message brut) y figure. La cause interne complète est préservée via
details_ref, un pointeur content-addressed (empreinte déterministe du
repr() de l'exception) — jamais la cause elle-même exposée directement.
Toute erreur inconnue devient UNKNOWN_FAILURE, jamais un succès silencieux
(CANON : « No error, timeout or missing tool becomes success »).

CORRECTIF sécurité (revue TRIAD_CONSENSUS de clôture de phase C03,
DeepSeek-V4-Pro, objection MAJEURE confirmée) : un sha256 NU et NON SALÉ
de repr(exc) est un ORACLE d'énumération — un attaquant qui suppose un
secret à faible entropie contenu dans le message d'exception peut
précalculer son hash hors ligne avec la même formule publique et le
comparer à details_ref, confirmant sa supposition sans jamais voir le
secret en clair. `details_ref` utilise donc un HMAC-SHA256 avec une clé
générée aléatoirement UNE FOIS par import du module (jamais persistée,
jamais exposée) plutôt qu'un sha256 nu : la formule seule (repr(exc)) ne
suffit plus à un tiers pour reproduire l'empreinte hors ligne. Le
déterminisme reste garanti à l'intérieur d'un même process (même clé en
mémoire) — c'est le seul déterminisme sourcé par tasks/C03-004.md
(« préserver cause interne dans la preuve ») et testé
(test_mapper_exception_details_ref_est_deterministe_content_addressed) ;
aucune corrélation INTER-process n'est demandée ni testée.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from enum import Enum

# Clé de process, générée une seule fois au chargement du module : jamais
# journalisée, jamais sérialisée, jamais dérivable de repr(exc) seul.
_CLE_DETAILS_REF = secrets.token_bytes(32)


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
    empreinte = hmac.new(_CLE_DETAILS_REF, repr(exc).encode("utf-8"), hashlib.sha256).hexdigest()
    return CoreError(
        code=code,
        retryable=retryable,
        safe_message=f"Échec interne ({type(exc).__name__}) — cause référencée par details_ref",
        details_ref=f"sha256:{empreinte}",
    )
