"""Vue privée des déclarations paie/DAS associée au CFO humain, sans les intégrer au cash."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

_ID = re.compile(r"^[a-f0-9]{32}$")
_MONTANT = re.compile(r"^(?:0|[1-9][0-9]{0,8})\.[0-9]{2}$")
_DATES = (
    "periode_debut", "periode_fin", "date_paie", "echeance", "source_consultee_le",
    "applicable_du", "applicable_au",
)


class SnapshotPriveInvalide(ValueError):
    """Le registre a passé son contrôle cryptographique mais sa vue ne respecte pas le contrat UI."""


def composer(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Projette les déclarations privées sans les agréger ni les rendre utilisables en cash/forecast.

    Le dossier CFO public ne porte pas les IDs canoniques des obligations legacy et ne détaille pas la
    catégorie des mouvements PROVISION. La jointure serait donc spéculative; chaque montant utilisable
    reste `None` jusqu'à réconciliation explicite de ces deux propriétaires.
    """
    if (
        not isinstance(snapshot, Mapping)
        or type(snapshot.get("revision")) is not int
        or snapshot["revision"] < 0
        or not isinstance(snapshot.get("obligations"), list)
    ):
        raise SnapshotPriveInvalide("snapshot privé invalide")

    lignes = []
    for ligne in snapshot["obligations"]:
        if not isinstance(ligne, Mapping):
            raise SnapshotPriveInvalide("ligne privée invalide")
        obligation = ligne.get("obligation")
        identifiant = ligne.get("id")
        if (
            not isinstance(obligation, Mapping)
            or not isinstance(identifiant, str)
            or not _ID.fullmatch(identifiant)
            or obligation.get("type") not in {"paies", "das"}
            or not isinstance(ligne.get("statut"), str)
            or not isinstance(obligation.get("montant_cad"), str)
            or not _MONTANT.fullmatch(obligation["montant_cad"])
            or any(not isinstance(obligation.get(cle), str) for cle in _DATES)
            or any(not isinstance(obligation.get(cle), str) or not obligation[cle].strip()
                   for cle in ("reference_piece", "autorite", "version"))
        ):
            raise SnapshotPriveInvalide("déclaration privée incomplète")
        lignes.append({
            "id": identifiant,
            "type": obligation["type"],
            "statut_source": ligne["statut"],
            "montant_declare_cad": obligation["montant_cad"],
            "montant_utilisable_cad": None,
            "periode": [obligation["periode_debut"], obligation["periode_fin"]],
            "date_paie": obligation["date_paie"],
            "echeance": obligation["echeance"],
            "reference_piece": obligation["reference_piece"],
            "autorite": obligation["autorite"],
            "source_consultee_le": obligation["source_consultee_le"],
            "applicabilite": [obligation["applicable_du"], obligation["applicable_au"]],
            "version": obligation["version"],
            "confirmee_le": ligne.get("confirme_le"),
            "reglee_le": ligne.get("reglee_le"),
            "reference_cycle": ligne.get("remplace_id", ligne.get("remplace_par_id", ligne.get("cible_id"))),
        })

    source_id = hashlib.sha256(json.dumps(
        {"revision": snapshot["revision"], "ids": [ligne["id"] for ligne in lignes]},
        sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    return {
        "statut": "INCONNU",
        "montant_utilisable_cad": None,
        "revision_source": snapshot["revision"],
        "snapshot_prive_id": source_id,
        "lignes": lignes,
        "raisons": [
            "les IDs de cette déclaration ne sont pas reliés aux anciennes obligations du manifeste",
            "les mouvements PROVISION ne portent pas de catégorie vérifiable; risque de double compte",
        ],
        "cash_libre_modifie": False,
        "prevision_modifiee": False,
    }
