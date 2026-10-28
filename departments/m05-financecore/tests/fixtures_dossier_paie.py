"""Fabriques FICTIVES (fictif: true) du dossier de paie préparatoire; aucune donnée réelle."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from m5_financecore import dossier_paie_preparatoire as d

ADMISSION_OK = {
    "admissible": True,
    "motifs": [],
    "sources_verifiees": ["arc_jan2026", "rq_f2026", "rq_tr26_2026"],
    "empreintes_sources": {"arc_jan2026": "a" * 64, "rq_f2026": "b" * 64, "rq_tr26_2026": "c" * 64},
    "schema": "opsys.admission-paie-preparatoire/v1",
}
ADMISSION_REFUSEE = {
    **ADMISSION_OK,
    "admissible": False,
    "motifs": ["rq_f2026:CAPTURE_INDISPONIBLE_OU_LIEE"],
    "sources_verifiees": [],
    "empreintes_sources": {},
}
Z = "0.00"


def parametres_employeur() -> dict[str, Any]:
    return {
        "fss": {
            "secteur": "AUTRES",
            "masse_salariale_estimative_cad": "500000.00",
            "base_estimation": "ANNEE_PRECEDENTE",
            "reference": "fss-declaration-fictive",
        },
        "cnesst": {
            "taux_versement_pour_100": "1.54",
            "base_excedent": "ANNUELLE",
            "reference": "decision-fictive-2026",
        },
        "normes_travail": {"assujetti": True, "reference": "normes-declaration-fictive"},
        "fdrcmo": {"masse_salariale_annee_cad": "500000.00", "reference": "fdrcmo-declaration-fictive"},
    }


def entrees(
    periode: int = 1,
    *,
    premiere: str = "2026-01-15",
    debut: str = "2026-01-01",
    fin: str = "2026-01-14",
    date_paie: str = "2026-01-15",
    cumuls: dict[str, str] | None = None,
    origine: str = "NUL_PERIODE_1",
    employeur: bool = True,
) -> dict[str, Any]:
    return {
        "schema": d.SCHEMA_ENTREES,
        "fictif": True,
        "employeur_reference": "employeur-fictif",
        "periode": {
            "annee": 2026,
            "periode_annuelle": periode,
            "debut": debut,
            "fin": fin,
            "fuseau": "America/Montreal",
            "date_paie": date_paie,
            "premiere_date_paie_annee": premiere,
        },
        "arrondi": {"politique": "centime_demi_superieur", "hypothese": "Hypothèse fictive, non vérifiée."},
        "classification": {"regime_ccq": "NON_CCQ_DECLARE"},
        "attestations": dict.fromkeys(d.CHAMPS_ATTESTATIONS, True),
        "pieces": {slot: {"reference": f"piece-{slot}-fictive", "sha256": None} for slot in d.CHAMPS_PIECES},
        "credits_federal": {"TC": "16452.00", **dict.fromkeys(d.CHAMPS_CREDITS_FEDERAL_NULS, Z)},
        "credits_qc": {
            **dict.fromkeys(d.CHAMPS_CREDITS_QC_MONTANTS, Z),
            **dict.fromkeys(d.CHAMPS_CREDITS_QC_MARQUEURS, False),
        },
        "cumuls_avant": {
            "origine": origine,
            "valeurs": cumuls or dict.fromkeys(d.CHAMPS_CUMULS, Z),
            "source_simulee": None,
            "reference_confirmation": None,
        },
        "autres_retenues_employe": {"montant": Z, "reference": "aucune-autre-retenue-fictive"},
        "autres_couts_employeur": {"montant": Z, "reference": "aucun-autre-cout-fictif"},
        "parametres_employeur": parametres_employeur() if employeur else None,
    }


def entrees_periode_20() -> dict[str, Any]:
    """Période 20 (2026-09-25, première paie 2026-01-02), cumuls au bord des plafonds annuels (salaire 74 590 $)."""
    cumuls = {
        "salaire_rrq_cumul_avant": "74590.00",
        "rrq_palier1_cumul_avant": "4479.29",
        "rrq_palier2_cumul_avant": "0.00",
        "rqap_salarie_cumul_avant": "442.89",
        "rqap_employeur_cumul_avant": "620.05",
        "ae_salarie_cumul_avant": "895.69",
        "ae_employeur_cumul_avant": "1253.97",
    }
    return entrees(
        20,
        premiere="2026-01-02",
        debut="2026-09-07",
        fin="2026-09-20",
        date_paie="2026-09-25",
        cumuls=cumuls,
        origine="DECLARE_HISTORIQUE",
    )


def copie(valeur: Any) -> Any:
    return deepcopy(valeur)
