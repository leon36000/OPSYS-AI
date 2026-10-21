"""Contrat pur d'un créneau éditorial relié à un contenu de chantier canonique.

Le registre du calendrier est un journal OPSYS (adapté par service.py), jamais une base M7 distincte.
Un créneau approuvé n'est ni une programmation ni une publication.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import Any


def horodatage_valide(valeur: Any) -> bool:
    if not isinstance(valeur, str) or not valeur:
        return False
    try:
        return datetime.fromisoformat(valeur).tzinfo is not None
    except ValueError:
        return False


def empreinte(valeur: Mapping[str, Any]) -> str:
    canonique = json.dumps(valeur, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonique.encode("utf-8")).hexdigest()


def _identite(creneau: Mapping[str, Any]) -> dict[str, Any]:
    return {
        cle: creneau.get(cle)
        for cle in (
            "contenu_id",
            "revision",
            "wct_id",
            "wct_empreinte",
            "wct_termine_le",
            "empreinte_texte",
            "planifie_le",
        )
    }


def empreinte_valide(creneau: Mapping[str, Any]) -> bool:
    return empreinte(_identite(creneau)) == creneau.get("empreinte_creneau")


def creer_creneau(
    proposition: Mapping[str, Any], charge: Mapping[str, Any], planifie_le: Any, cree_le: Any
) -> dict[str, Any] | None:
    if not horodatage_valide(planifie_le) or not horodatage_valide(cree_le):
        return None
    source = {
        "contenu_id": proposition["contenu_id"],
        "revision": proposition["revision"],
        "wct_id": proposition["wct_id"],
        "wct_empreinte": charge.get("hash_maillon"),
        "wct_termine_le": charge.get("horodatage_completion"),
        "empreinte_texte": proposition["empreinte_texte"],
    }
    identite = {**source, "planifie_le": planifie_le}
    creneau_id = str(uuid.uuid5(uuid.NAMESPACE_URL, json.dumps(identite, sort_keys=True)))
    return {
        "type": "creneau_contenu",
        "creneau_id": creneau_id,
        **identite,
        "plateforme": proposition["plateforme"],
        "cree_le": cree_le,
        "empreinte_creneau": empreinte(identite),
        "source": {
            "registre": "wct_recus",
            "wct_id": proposition["wct_id"],
            "wct_hash": charge.get("hash_maillon"),
            "wct_termine_le": charge.get("horodatage_completion"),
            "registre_contenu": "contenus_chantier",
            "contenu_id": proposition["contenu_id"],
        },
    }


def etat(
    creneau: Mapping[str, Any],
    decisions: list[Mapping[str, Any]],
    exports: list[Mapping[str, Any]],
    statut_contenu: str,
) -> dict[str, Any]:
    decision = next((d for d in reversed(decisions) if d["creneau_id"] == creneau["creneau_id"]), None)
    export = next((e for e in exports if e["creneau_id"] == creneau["creneau_id"]), None)
    return {
        **dict(creneau),
        "statut": "RETIRE"
        if statut_contenu == "CONSENTEMENT_RETIRE"
        else (
            "CONFLIT_SOURCE"
            if (
                not empreinte_valide(creneau)
                or (decision is not None and decision.get("empreinte_creneau") != creneau.get("empreinte_creneau"))
            )
            else "CONTENU_NON_APPROUVE"
            if statut_contenu != "APPROVED"
            else (decision["decision"] if decision else "BROUILLON")
        ),
        "decision": None if decision is None else dict(decision),
        "export": None if export is None else dict(export),
    }
