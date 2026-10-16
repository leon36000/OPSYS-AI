"""Suivis internes : projection pure d'une preuve reçue et d'une décision humaine.

Aucune horloge, identité, base, mesure recalculée ou exécution d'action ici.
Une preuve historique n'atteste pas la couverture ni l'actualité de l'entreprise.
"""

from __future__ import annotations

import copy
import json
import re
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from .encodage import empreinte


def texte(valeur: str, champ: str, limite: int) -> str:
    if not isinstance(valeur, str) or not valeur.strip() or len(valeur) > limite:
        raise ValueError(f"REJ-SUIVI-ARGUMENT : {champ} requis, texte non vide de {limite} caractères maximum")
    return valeur


def borner(resultat: dict[str, Any], budget: int) -> dict[str, Any]:
    if len(json.dumps(resultat, ensure_ascii=False, allow_nan=False)) > budget:
        raise ValueError("REJ-SUIVI-BORNE : preuve ou suivi trop volumineux, aucune troncature autorisée")
    return resultat


def preparer_source(alertes: Iterable[dict[str, Any]], evenement_id: str) -> dict[str, Any]:
    texte(evenement_id, "evenement_id", 1024)
    trouvees = [a for a in alertes if isinstance(a, dict) and a.get("evenement_id") == evenement_id]
    if len(trouvees) != 1:
        raise ValueError("REJ-SUIVI-SOURCE : preuve reçue absente ou ambiguë")
    alerte = trouvees[0]
    if alerte.get("type_alerte") != "MESURE-SEUIL-FRANCHI":
        raise ValueError("REJ-SUIVI-SOURCE : une alerte de mesure M8 reçue est requise")
    for champ in ("metric_id", "quoi", "a_qui", "pourquoi", "source", "horodatage_reference"):
        texte(alerte.get(champ), champ, 4096)
    preuve = alerte.get("preuve")
    if not isinstance(preuve, dict) or preuve.get("metric_id") != alerte["metric_id"]:
        raise ValueError("REJ-SUIVI-SOURCE : preuve de mesure absente ou métrique discordante")
    for champ in ("wct_id", "valeur", "unite", "sens", "seuil", "version_definition"):
        texte(preuve.get(champ), champ, 1024)
    if not re.fullmatch(r"[0-9a-f]{64}", preuve["version_definition"]):
        raise ValueError("REJ-SUIVI-SOURCE : version de définition M8 invalide")
    return {"evenement_id": evenement_id, "empreinte_source": empreinte(alerte),
            "alerte": copy.deepcopy(alerte), "nature": "historique_recue", "couverture": "non_evaluee"}


def construire(
    *, source: dict[str, Any], empreinte_source: str, action: str, responsable_id: str,
    echeance: str, demande_id: str, decide_par: str, decide_role: str, decide_le: str,
) -> dict[str, Any]:
    if empreinte_source != source["empreinte_source"]:
        raise ValueError(
            "REJ-SUIVI-EMPREINTE : la preuve diffère de celle liée à la demande ; nouvelle approbation requise"
        )
    texte(action, "action", 1000)
    texte(responsable_id, "responsable_id", 64)
    texte(echeance, "echeance", 64)
    try:
        instant = datetime.fromisoformat(echeance)
    except ValueError as exc:
        raise ValueError("REJ-SUIVI-ECHEANCE : instant ISO avec fuseau explicite requis") from exc
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("REJ-SUIVI-ECHEANCE : instant ISO avec fuseau explicite requis")
    return {"schema": 1, "suivi_id": demande_id, "statut": "planifiee", "action": action,
            "responsable_id": responsable_id, "echeance": echeance, "source": source,
            "decision": {"demande_id": demande_id, "decide_par": decide_par,
                         "decide_role": decide_role, "decide_le": decide_le}}
