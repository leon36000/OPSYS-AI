"""Décision humaine sur un contenu de chantier (PLAN T4.17 : « approbation du propriétaire par À voir », N3).

Un contenu proposé attend une décision humaine : `approuver` ou `rejeter`. L'approbation est un acte du
PROPRIÉTAIRE (rôle `nathan_owner`), jamais du modèle qui a proposé le contenu ni d'un autre agent. Ce module
est pur : il ne lit ni l'identité ni la base. C'est l'adaptateur (`outils.py`) qui établit QUI décide — identité
d'un jeton d'appareil confirmée en base, ou décision qu'un humain vient d'approuver dans la file d'approbation
du socle — et qui passe ici une personne, un rôle et une voie DÉJÀ établis. Ce module refuse tout ce qui n'a pas
la forme d'un humain identifié (défense en profondeur : un appelant direct ne peut pas écrire sans personne).

La décision porte l'empreinte du texte décidé : un export refuse un texte qui ne serait plus celui qui a été
approuvé.

Module pur : aucune entrée-sortie, aucun import `opsys`.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Mapping
from typing import Any

from . import verdicts
from .registre import STATUT_APPROUVE, STATUT_REJETE
from .retrait import horodatage_valide

DECISION_APPROUVER = "approuver"
DECISION_REJETER = "rejeter"
DECISIONS = (DECISION_APPROUVER, DECISION_REJETER)

ROLE_DECIDEUR = "nathan_owner"
SOURCE_APPAREIL = "appareil"
SOURCE_APPROBATION = "approbation"

MOTIF_MAX = 500
MOTIF_MIN_REJET = 5

# Même forme qu'un identifiant de personne d'OPSYS (`opsys.identite`) : minuscules, chiffres, `.`, `_`, `-`.
_PERSONNE = re.compile(r"^[a-z][a-z0-9_.-]{1,63}$")


def acteur_valide(par: Any, role: Any, source: Any) -> bool:
    """Vrai si `(par, role, source)` a la forme d'un propriétaire identifié, par l'une des deux voies."""
    return (
        isinstance(par, str) and _PERSONNE.fullmatch(par) is not None
        and role == ROLE_DECIDEUR and source in (SOURCE_APPAREIL, SOURCE_APPROBATION)
    )


def construire_decision(
    proposition: Mapping[str, Any], decision: Any, par: Any, role: Any, source: Any, motif: Any, horodatage: Any,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """`(maillon de décision, None)` ou `(None, verdict)` : ce qui est refusé n'écrit rien."""
    if not acteur_valide(par, role, source):
        return None, verdicts.verdict(
            verdicts.REJ_HUMAIN_ACTEUR_INVALIDE,
            "la décision exige une personne identifiée (le propriétaire), par un jeton d'appareil ou une "
            "approbation humaine",
        )
    if decision not in DECISIONS:
        return None, verdicts.verdict(verdicts.REJ_DECISION_INVALIDE, f"decision : {' ou '.join(DECISIONS)}")
    texte_motif = motif.strip() if isinstance(motif, str) else ""
    if len(texte_motif) > MOTIF_MAX:
        return None, verdicts.verdict(verdicts.REJ_MOTIF_REQUIS, f"le motif ne dépasse pas {MOTIF_MAX} caractères")
    if decision == DECISION_REJETER and len(texte_motif) < MOTIF_MIN_REJET:
        return None, verdicts.verdict(
            verdicts.REJ_MOTIF_REQUIS, "un rejet dit pourquoi : ce que le nouveau texte doit corriger"
        )
    if not horodatage_valide(horodatage):
        return None, verdicts.verdict(verdicts.REJ_HORODATAGE_INVALIDE, "horodatage ISO 8601 avec fuseau requis")
    canonique = json.dumps({"contenu_id": proposition["contenu_id"], "type": "decision_contenu"}, sort_keys=True)
    return {
        "decision_id": str(uuid.uuid5(uuid.NAMESPACE_URL, canonique)),
        "contenu_id": proposition["contenu_id"],
        "wct_id": proposition["wct_id"],
        "plateforme": proposition["plateforme"],
        "revision": proposition["revision"],
        "decision": STATUT_APPROUVE if decision == DECISION_APPROUVER else STATUT_REJETE,
        "par": par,
        "role": role,
        "source": source,
        "motif": texte_motif,
        "horodatage": horodatage,
        "empreinte_texte": proposition["empreinte_texte"],
    }, None
