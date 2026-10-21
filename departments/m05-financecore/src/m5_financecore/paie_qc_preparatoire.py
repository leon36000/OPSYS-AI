"""Composition préparatoire publique RRQ → R42 et cotisations RQAP/AE."""

from __future__ import annotations

from typing import Any

from . import validation
from .cotisations_rqap_ae_2026 import calculer_cotisations_rqap_ae_preparatoires
from .cotisations_rrq_regulieres import calculer_cotisation_rrq_preparatoire
from .impot_quebec_regulier import calculer_retenue_preparatoire

_CONTEXTE = ("annee", "date_paie", "juridiction", "frequence", "periode_annuelle")


def _refus(code: str, detail: str) -> dict[str, str]:
    return validation.construire_verdict(code, detail=detail)


def calculer_paie_qc_preparatoire(
    *,
    entree_rrq: object,
    entree_impot_qc: object,
    entree_rqap_ae: object,
) -> dict[str, Any]:
    """Appelle les moteurs publics et rend des postes distincts sans total/net.

    Les trois demandes sont des structures d'entrée déclaratives. Leur provenance et
    leur exactitude ne sont pas authentifiées par cette façade.
    """
    if any(not isinstance(item, dict) for item in (entree_rrq, entree_impot_qc, entree_rqap_ae)):
        return {
            "schema": "m5-paie-qc-preparatoire/1",
            "statut": "INCOMPLET",
            "refus": {"structure": _refus("REJ-PAIE-ASSIETTE-INVALIDE", "trois demandes structurées sont requises")},
            "postes": {},
            "statut_ccq": "UNKNOWN",
            "retenue_impot_federal": None,
            "revenu_net": None,
            "das_complete": None,
            "cout_employeur_global": None,
            "actions_financieres_bloquees": True,
        }
    rrq_input = dict(entree_rrq)
    impot_input = dict(entree_impot_qc)
    cotisations_input = dict(entree_rqap_ae)
    valeurs_contexte: list[tuple[object, ...]] = []
    for source in (rrq_input, impot_input, cotisations_input):
        try:
            valeurs_contexte.append(tuple(source[nom] for nom in _CONTEXTE))
        except KeyError:
            valeurs_contexte.append(())
    coherence = bool(valeurs_contexte[0]) and all(valeurs == valeurs_contexte[0] for valeurs in valeurs_contexte)
    rapport: dict[str, Any] = {
        "schema": "m5-paie-qc-preparatoire/1",
        "statut": "INCOMPLET",
        "mode": "PREPARATOIRE",
        "qualification_regles": "NON_QUALIFIEE_POUR_PAIE",
        "authenticite_preuves": "NON_VERIFIEE",
        "contexte": dict(zip(_CONTEXTE, valeurs_contexte[0], strict=True)) if coherence else None,
        "postes": {},
        "refus": {},
        "statut_ccq": "UNKNOWN",
        "retenue_impot_federal": None,
        "revenu_net": None,
        "das_complete": None,
        "cout_employeur_global": None,
        "actions_financieres_bloquees": True,
    }
    if not coherence:
        rapport["refus"]["contexte"] = _refus(
            "REJ-PAIE-ASSIETTE-INVALIDE", "année, date, juridiction, fréquence et période doivent concorder"
        )
        return rapport

    try:
        rrq, refus_rrq = calculer_cotisation_rrq_preparatoire(**rrq_input)
    except TypeError:
        rrq, refus_rrq = None, _refus("REJ-PAIE-ASSIETTE-INVALIDE", "demande RRQ incomplète")
    if refus_rrq:
        rapport["refus"]["rrq"] = refus_rrq
    else:
        rapport["postes"]["rrq"] = rrq
        impot_input["CSA"] = rrq["CSA"]
        try:
            impot, refus_impot = calculer_retenue_preparatoire(**impot_input)
        except TypeError:
            impot, refus_impot = None, _refus("REJ-PAIE-ASSIETTE-INVALIDE", "demande d’impôt QC incomplète")
        if refus_impot:
            rapport["refus"]["impot_qc"] = refus_impot
        else:
            rapport["postes"]["impot_qc"] = impot

    try:
        cotisations, refus_cotisations = calculer_cotisations_rqap_ae_preparatoires(**cotisations_input)
    except TypeError:
        cotisations, refus_cotisations = None, _refus("REJ-PAIE-ASSIETTE-INVALIDE", "demande RQAP/AE incomplète")
    if refus_cotisations:
        rapport["refus"]["rqap_ae"] = refus_cotisations
    else:
        rapport["postes"]["rqap_ae"] = cotisations

    if len(rapport["postes"]) == 3 and not rapport["refus"]:
        rapport["composantes"] = "CALCULEES_PREPARATOIRES"
        rapport["motif_incompletude"] = "impot federal et autres obligations non calcules; aucune paie nette"
    return rapport
