"""Acteur humain d'une écriture que le modèle ne fait jamais seul (PLAN T3.3-suite-b).

Certaines écritures de M10 engagent la confiance qu'un agent place dans le paquet de contexte : prendre
connaissance d'un signal critique, le clore, lier une conversation à une affaire. Un modèle qui les ferait
seul viderait le paquet de son sens. Elles se font donc par un HUMAIN, et l'écriture dit lequel, avec son
rôle, par quelle voie et pourquoi.

Ce module est pur (DA-M10-08) : il ne lit ni l'identité ni la base. C'est ``outils.py`` (l'adaptateur,
seul) qui établit QUI décide — identité d'un jeton d'appareil confirmée en base, ou décision humaine en
cours d'exécution dans la file d'approbation — et qui passe ici le résultat. Ce module reçoit donc une
personne, un rôle et une voie DÉJÀ établis ; il refuse tout ce qui n'est pas de la forme d'un humain
identifié et motivé (défense en profondeur : même un appelant direct ne peut pas écrire sans personne).

Deux voies, jamais une troisième :
- ``appareil`` : la personne authentifiée du jeton d'appareil, rôle ``admin`` ;
- ``approbation`` : la personne qui a approuvé la demande dans la file d'approbation, rôle ``admin`` ou
  ``nathan_owner`` (celui que la politique du département autorise pour ce niveau) ;
- ``cli`` : authentification personnelle interactive d'un adaptateur opérateur dédié, juste avant l'écriture.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from . import validation

ROLE_ADMIN = "admin"
ROLE_PROPRIETAIRE = "nathan_owner"
SOURCE_APPAREIL = "appareil"
SOURCE_APPROBATION = "approbation"
SOURCE_CLI = "cli"

MOTIF_MIN_CARACTERES = 10
MOTIF_MAX_CARACTERES = 500

REJ_HUMAIN_REQUIS = "REJ-HUMAIN-REQUIS"
REJ_HUMAIN_IDENTITE_INVALIDE = "REJ-HUMAIN-IDENTITE-INVALIDE"
REJ_HUMAIN_ROLE_INSUFFISANT = "REJ-HUMAIN-ROLE-INSUFFISANT"
REJ_HUMAIN_ACTEUR_INVALIDE = "REJ-HUMAIN-ACTEUR-INVALIDE"
REJ_HUMAIN_MOTIF_INVALIDE = "REJ-HUMAIN-MOTIF-INVALIDE"
REJ_HUMAIN_HORODATAGE_INVALIDE = "REJ-HUMAIN-HORODATAGE-INVALIDE"

_ROLES_HUMAINS = frozenset({ROLE_ADMIN, ROLE_PROPRIETAIRE})
_SOURCES_DECISION = frozenset({SOURCE_APPAREIL, SOURCE_APPROBATION, SOURCE_CLI})
# Même forme qu'un identifiant de personne d'OPSYS (`opsys.identite`) : minuscules, chiffres, `.`, `_`, `-`.
_PERSONNE = re.compile(r"^[a-z][a-z0-9_.-]{1,63}$")


def roles_humains() -> frozenset[str]:
    return _ROLES_HUMAINS


def acteur_valide(par: Any, role: Any, source: Any) -> bool:
    """Vrai si ``(par, role, source)`` a la forme d'un humain identifié, par l'une des deux voies."""
    return (
        isinstance(par, str)
        and _PERSONNE.fullmatch(par) is not None
        and role in _ROLES_HUMAINS
        and source in _SOURCES_DECISION
    )


def motif_valide(motif: Any) -> bool:
    return isinstance(motif, str) and MOTIF_MIN_CARACTERES <= len(motif.strip()) <= MOTIF_MAX_CARACTERES


def horodatage_valide(horodatage: Any) -> bool:
    if not isinstance(horodatage, str) or not horodatage:
        return False
    try:
        instant = datetime.fromisoformat(horodatage)
    except ValueError:
        return False
    return instant.tzinfo is not None


def verifier_ecriture(par: Any, role: Any, source: Any, motif: Any, horodatage: Any) -> dict[str, Any] | None:
    """``None`` si l'écriture est recevable, sinon le verdict ``{code, detail}`` du premier défaut."""
    if not acteur_valide(par, role, source):
        return validation.construire_verdict(
            REJ_HUMAIN_ACTEUR_INVALIDE,
            "l'écriture exige une personne identifiée (rôle admin ou nathan_owner) par un jeton d'appareil "
            "ou une approbation humaine",
        )
    if not motif_valide(motif):
        return validation.construire_verdict(
            REJ_HUMAIN_MOTIF_INVALIDE,
            f"le motif est obligatoire : {MOTIF_MIN_CARACTERES} à {MOTIF_MAX_CARACTERES} caractères, "
            "dit pourquoi",
        )
    if not horodatage_valide(horodatage):
        return validation.construire_verdict(
            REJ_HUMAIN_HORODATAGE_INVALIDE, "horodatage ISO 8601 avec fuseau requis"
        )
    return None
