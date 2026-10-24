"""Retenue fédérale préparatoire QC 2026 : P1 historique et crédits YTD après P1."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from decimal import ROUND_HALF_UP, Context, Decimal, InvalidOperation, localcontext
from typing import Any

from . import validation
from .paie_qc_preparatoire import calculer_paie_qc_preparatoire

VERSION_BAREME = "T4127-122-2026-01-QC26P-P1-r1"
SOURCE_T4127_SHA256 = "c715b8e6d33e0887119e0462b9a4cf8915370c56381932f1d7ba3a32385ddd8c"
SOURCE_TP1015_SHA256 = "a65675dc6ad2bfc6c4fe2695d4914a57f381eccc9b8b1e1c581b7c9c8a18e72b"
SOURCE_TR26_SHA256 = "2079c958132de69216157b5c16c0296c89556e6deb69ad1854c9ebddf680c321"
SOURCE_EI_SHA256 = "b72d19f75f50e8b9515404226d73b2e6896fb8e749adc6854a12683c582ada35"

_PARAMETRES = {
    "schema": "m5-impot-federal-qc-preparatoire/1",
    "version": VERSION_BAREME,
    "juridiction": "QC",
    "annee": 2026,
    "edition": "T4127-122-2026-01",
    "date_debut_inclusive": "2026-01-01",
    "date_fin_inclusive": "2026-06-30",
    "frequence": "bihebdomadaire",
    "periodes_annuelles": 26,
    "periode_couverte": 1,
    "pm_requis_atteste": 12,
    "option": 1,
    "montant_max_entree": "999999999999.99",
    "precision_decimal": 50,
    "emin_decimal": -999999,
    "emax_decimal": 999999,
    "clamp_decimal": 0,
    "arrondi_decimal": "ROUND_HALF_UP",
    "pieges_decimal": "desactives",
    "arrondis": {
        "cotisations_enfant": "valeurs publiques déjà arrondies par le calculateur source",
        "F5Q": "aucun arrondi intermédiaire; taux ratio exact",
        "K2Q": "ratios et terme IE×0.00430 gardés exacts; EI vient du poste public arrondi",
        "retenue_finale": "centime ROUND_HALF_UP",
    },
    "taux_tranches": [
        {"borne_superieure": "58523.00", "taux": "0.1400", "constante": "0.00"},
        {"borne_superieure": "117045.00", "taux": "0.2050", "constante": "3804.00"},
        {"borne_superieure": "181440.00", "taux": "0.2600", "constante": "10241.00"},
        {"borne_superieure": "258482.00", "taux": "0.2900", "constante": "15685.00"},
        {"borne_superieure": None, "taux": "0.3300", "constante": "26024.00"},
    ],
    "credit_personnel": {"taux_minimal": "0.14", "TC_obligatoire": "TD1_declare; aucun_defaut"},
    "K2Q": {
        "taux_federal": "0.14",
        "taux_rrq_base": "0.0530",
        "taux_rrq_total_palier1": "0.0630",
        "maximum_rrq_base": "3768.30",
        "maximum_ei_qc": "895.70",
        "taux_qpip_credit": "0.00430",
        "maximum_qpip": "442.90",
    },
    "K4": {"taux_federal": "0.14", "maximum_cea": "1501.00"},
    "abattement_qc": "0.165",
    "LCF_maximum_annuel": "750.00",
    "inputs_nuls_obligatoires": ["F", "F2", "HD", "F1", "U1", "K3", "LCF", "L"],
    "sources": {
        "t4127_janvier": {"sha256": SOURCE_T4127_SHA256, "pages": "3, 14-17, 32", "url": "https://www.canada.ca/en/revenue-agency/services/forms-publications/payroll/t4127-payroll-deductions-formulas/t4127-jan.html"},
        "rrq": {
            "version": "TP-1015.F-2026-01-RRQ-26P-r1",
            "sha256": SOURCE_TP1015_SHA256,
            "sha256_tr26": SOURCE_TR26_SHA256,
        },
        "rqap_ae": {
            "sha256_tp1015": SOURCE_TP1015_SHA256,
            "sha256_t4127": SOURCE_T4127_SHA256,
            "sha256_ei": SOURCE_EI_SHA256,
        },
        "impot_qc_facade": {"sha256_tp1015": SOURCE_TP1015_SHA256},
    },
    "limites": [
        "premiere periode annuelle seulement, janvier a juin 2026",
        "emploi annuel continu QC, resident declare, 26 paies bihebdomadaires, PM=12",
        "assiettes de paie egales attestees, zero autre credit/deduction explicite",
        "preuves declaratives non authentifiees; aucune paie finale, aucun net ni DAS complete",
    ],
}
HASH_PARAMETRES = hashlib.sha256(
    json.dumps(_PARAMETRES, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
).hexdigest()


def _parametres_pour_demande(demande: dict[str, Any]) -> dict[str, Any]:
    # Copie indépendante : aucun appelant ne peut modifier le snapshot global.
    parametres = json.loads(json.dumps(_PARAMETRES))
    if demande["periode_annuelle"] == 1:
        return parametres
    juillet = demande["date_paie"] >= "2026-07-01"
    edition = "T4127-123-2026-07" if juillet else "T4127-122-2026-01"
    parametres.update(
        version=f"{edition}-QC26P-YTD-r1",
        edition=edition,
        date_debut_inclusive="2026-07-01" if juillet else "2026-01-01",
        date_fin_inclusive="2026-12-31" if juillet else "2026-06-30",
        periode_couverte=list(range(2, 27)),
        methode_credits="CUMULS_PLUS_PERIODES_RESTANTES",
        projection_credits="PR=26-periode+1; cumuls avant + PR fois poste courant, plafonds distincts",
    )
    parametres["sources"]["t4127_juillet"] = {
        "url": "https://www.canada.ca/en/revenue-agency/services/forms-publications/payroll/"
        "t4127-payroll-deductions-formulas/t4127-jul/t4127-jul-payroll-deductions-formulas.html",
        "sections": "chapitre 4, formules inchangées renvoyant à la 122e édition; tableaux 8.1 et 8.2",
        "consultation": "2026-10-24",
    }
    parametres["sources"]["t4127_janvier"]["sections_credits_ytd"] = "chapitre 4, étape 2, variante YTD K2Q"
    parametres["limites"][0] = "periodes 2 a 26 de 2026; edition datee; credits cumules option 1"
    return parametres

_CENT = Decimal("0.01")
_MAX_MONTANT = Decimal(_PARAMETRES["montant_max_entree"])
_MONTANT = re.compile(r"^(?:0|[1-9][0-9]{0,11})\.[0-9]{2}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ID_PREUVE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_CHAMPS_DEMANDE = frozenset(
    {
        "annee",
        "date_paie",
        "juridiction",
        "frequence",
        "periode_annuelle",
        "pm",
        "emploi_annuel_continu",
        "resident",
        "revenu_brut_emploi",
        "TC",
        "F",
        "F2",
        "HD",
        "F1",
        "U1",
        "K3",
        "LCF",
        "L",
        "preuves",
    }
)
_CHAMPS_PREUVES = frozenset(
    {"td1", "emploi_annuel_continu", "assiettes_egales", "residence", "zeros_hors_scope"}
)
_CHAMPS_ZERO = _PARAMETRES["inputs_nuls_obligatoires"]


def _refus(code: str, detail: str) -> tuple[None, dict[str, str]]:
    return None, validation.construire_verdict(code, detail=detail)


def _decimal(valeur: object) -> Decimal | None:
    if not isinstance(valeur, str) or len(valeur) > 15 or _MONTANT.fullmatch(valeur) is None:
        return None
    try:
        montant = Decimal(valeur)
    except (InvalidOperation, ValueError):
        return None
    if not montant.is_finite() or montant < 0 or montant > _MAX_MONTANT:
        return None
    return montant


def _preuve_valide(preuve: object) -> bool:
    return (
        isinstance(preuve, dict)
        and set(preuve) == {"id", "sha256", "fictif"}
        and isinstance(preuve.get("id"), str)
        and _ID_PREUVE.fullmatch(preuve["id"]) is not None
        and isinstance(preuve.get("sha256"), str)
        and _SHA256.fullmatch(preuve["sha256"]) is not None
        and type(preuve.get("fictif")) is bool
    )


def _contexte_decimal() -> Context:
    contexte = Context(
        prec=_PARAMETRES["precision_decimal"],
        rounding=ROUND_HALF_UP,
        Emin=_PARAMETRES["emin_decimal"],
        Emax=_PARAMETRES["emax_decimal"],
        clamp=_PARAMETRES["clamp_decimal"],
    )
    for signal in contexte.traps:
        contexte.traps[signal] = False
    return contexte


def _fmt(nombre: Decimal) -> str:
    return format(nombre, "f")


def _contexte_demande_valide(demande: dict[str, Any]) -> dict[str, Any] | None:
    if set(demande) != _CHAMPS_DEMANDE:
        return None
    if type(demande["annee"]) is not int or demande["annee"] != 2026:
        return None
    if not isinstance(demande["date_paie"], str):
        return None
    try:
        jour = date.fromisoformat(demande["date_paie"])
    except ValueError:
        return None
    if jour.isoformat() != demande["date_paie"] or not date(2026, 1, 1) <= jour <= date(2026, 12, 31):
        return None
    if (
        demande["juridiction"] != "QC"
        or demande["frequence"] != "bihebdomadaire"
        or type(demande["periode_annuelle"]) is not int
        or not 1 <= demande["periode_annuelle"] <= 26
        or type(demande["pm"]) is not int
        or demande["pm"] != 12
        or type(demande["emploi_annuel_continu"]) is not bool
        or not demande["emploi_annuel_continu"]
        or type(demande["resident"]) is not bool
        or not demande["resident"]
    ):
        return None
    if demande["periode_annuelle"] == 1 and jour > date(2026, 6, 30):
        return None
    if not isinstance(demande["preuves"], dict) or set(demande["preuves"]) != _CHAMPS_PREUVES:
        return None
    if any(not _preuve_valide(preuve) for preuve in demande["preuves"].values()):
        return None
    montants = {champ: _decimal(demande[champ]) for champ in ("revenu_brut_emploi", "TC", *_CHAMPS_ZERO)}
    if any(valeur is None for valeur in montants.values()):
        return None
    if any(demande[champ] != "0.00" for champ in _CHAMPS_ZERO):
        return None
    return {"date": jour, "montants": montants}


def _entrees_coherentes(
    entree_rrq: object,
    entree_impot_qc: object,
    entree_rqap_ae: object,
    demande: dict[str, Any],
) -> bool:
    if any(type(entree) is not dict for entree in (entree_rrq, entree_impot_qc, entree_rqap_ae)):
        return False
    sources = (entree_rrq, entree_impot_qc, entree_rqap_ae)
    noms_contexte = ("annee", "date_paie", "juridiction", "frequence", "periode_annuelle")
    valeurs_attendues = tuple(demande[nom] for nom in noms_contexte)
    if any(tuple(entree.get(nom) for nom in noms_contexte) != valeurs_attendues for entree in sources):
        return False
    if entree_rrq.get("pm") != 12 or type(entree_rrq.get("pm")) is not int:
        return False
    if (
        entree_rrq.get("emploi_continu") is not True
        or entree_rrq.get("paiement_regulier_fixe") is not True
        or entree_rqap_ae.get("paiement_regulier_fixe") is not True
        or entree_impot_qc.get("paiement_regulier_fixe") is not True
        or entree_impot_qc.get("resident") is not True
    ):
        return False
    champs_assiette = (
        (entree_rrq, "salaire_rrq_periode"),
        (entree_impot_qc, "G"),
        (entree_impot_qc, "D"),
        (entree_rqap_ae, "assiette_rqap_periode"),
        (entree_rqap_ae, "assiette_ae_periode"),
    )
    assiettes = [_decimal(entree.get(champ)) for entree, champ in champs_assiette]
    revenu = _decimal(demande["revenu_brut_emploi"])
    return revenu is not None and all(valeur is not None and valeur == revenu for valeur in assiettes)


def _sorties_facade_valides(rapport: object, date_paie: str, periode_annuelle: int = 1) -> bool:
    if not isinstance(rapport, dict) or rapport.get("schema") != "m5-paie-qc-preparatoire/1":
        return False
    if rapport.get("statut") != "INCOMPLET" or rapport.get("refus") != {}:
        return False
    if rapport.get("composantes") != "CALCULEES_PREPARATOIRES":
        return False
    contexte = rapport.get("contexte")
    postes = rapport.get("postes")
    if not isinstance(contexte, dict) or not isinstance(postes, dict):
        return False
    if set(postes) != {"rrq", "impot_qc", "rqap_ae"}:
        return False
    if contexte != {
        "annee": 2026,
        "date_paie": date_paie,
        "juridiction": "QC",
        "frequence": "bihebdomadaire",
        "periode_annuelle": periode_annuelle,
    }:
        return False
    rrq = postes["rrq"]
    rqap_ae = postes["rqap_ae"]
    impot_qc = postes["impot_qc"]
    if not isinstance(rrq, dict) or not isinstance(rqap_ae, dict) or not isinstance(impot_qc, dict):
        return False
    rrq_params = rrq.get("parametres")
    rrq_sources = rrq_params.get("sources") if isinstance(rrq_params, dict) else None
    if (
        rrq.get("date_paie") != date_paie
        or rrq.get("periode_annuelle") != periode_annuelle
        or rrq.get("parametres", {}).get("version") != "TP-1015.F-2026-01-RRQ-26P-r1"
        or not isinstance(rrq_sources, list)
        or len(rrq_sources) < 2
        or rrq_sources[0].get("sha256") != SOURCE_TP1015_SHA256
        or rrq_sources[1].get("sha256") != SOURCE_TR26_SHA256
    ):
        return False
    rqap_params = rqap_ae.get("parametres")
    if not isinstance(rqap_params, dict):
        return False
    rqap_sources = rqap_params.get("rqap", {}).get("sources", {})
    ae_sources = rqap_params.get("ae_qc", {}).get("sources", {})
    if (
        rqap_ae.get("date_paie") != date_paie
        or rqap_params.get("schema") != "m5-cotisations-qc-preparatoires/1"
        or rqap_sources.get("sha256") != SOURCE_TP1015_SHA256
        or ae_sources.get("t4127_jan_sha256") != SOURCE_T4127_SHA256
        or ae_sources.get("cra_rates_sha256") != SOURCE_EI_SHA256
    ):
        return False
    source_qc = impot_qc.get("source")
    if (
        impot_qc.get("date_paie") != date_paie
        or not isinstance(source_qc, dict)
        or source_qc.get("sha256_pdf") != SOURCE_TP1015_SHA256
        or source_qc.get("edition") != "2026-01"
    ):
        return False
    return (
        _decimal(rrq.get("cotisation_palier1")) is not None
        and _decimal(rrq.get("cotisation_palier2")) is not None
        and _decimal(rqap_ae.get("postes", {}).get("ae_salarie")) is not None
    )


def calculer_retenue_federale_qc_preparatoire(
    *,
    entree_rrq: object,
    entree_impot_qc: object,
    entree_rqap_ae: object,
    demande_federale: object,
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Recalcule les postes publics M5 puis estime la retenue fédérale T4127.

    Les références de preuve sont déclaratives. Un statut `INCOMPLET` de la façade
    M5 est normal si ses trois postes sont calculés et qu'aucun refus n'est présent;
    il le reste après cette estimation fédérale, car aucune paie complète n'en résulte.
    """
    if type(demande_federale) is not dict:
        return _refus("REJ-PAIE-ASSIETTE-INVALIDE", "demande fédérale structurée requise")
    valide = _contexte_demande_valide(demande_federale)
    if valide is None:
        return _refus("REJ-PAIE-ASSIETTE-INVALIDE", "contexte, montant, preuve ou périmètre fédéral invalide")
    date_paie = demande_federale["date_paie"]
    if not _entrees_coherentes(entree_rrq, entree_impot_qc, entree_rqap_ae, demande_federale):
        return _refus("REJ-PAIE-ASSIETTE-INVALIDE", "les contextes ou assiettes déclarées doivent concorder")

    try:
        facade = calculer_paie_qc_preparatoire(
            entree_rrq=entree_rrq,
            entree_impot_qc=entree_impot_qc,
            entree_rqap_ae=entree_rqap_ae,
        )
    except (KeyError, TypeError, ValueError):
        return _refus("REJ-PAIE-SNAPSHOT-REQUIS", "les trois demandes publiques préparatoires sont requises")
    periode = demande_federale["periode_annuelle"]
    if not _sorties_facade_valides(facade, date_paie, periode):
        return _refus("REJ-PAIE-SOURCE-NON-QUALIFIEE", "la façade publique ne fournit pas les trois postes attendus")

    parametres = _parametres_pour_demande(demande_federale)
    hash_parametres = hashlib.sha256(
        json.dumps(parametres, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    postes = facade["postes"]
    rrq = postes["rrq"]
    rqap_ae = postes["rqap_ae"]
    montant_demande = valide["montants"]
    i = montant_demande["revenu_brut_emploi"]
    tc = montant_demande["TC"]
    f = montant_demande["F"]
    f2 = montant_demande["F2"]
    hd = montant_demande["HD"]
    f1 = montant_demande["F1"]
    u1 = montant_demande["U1"]
    k3 = montant_demande["K3"]
    lcf = montant_demande["LCF"]
    l_amount = montant_demande["L"]
    c = _decimal(rrq["cotisation_palier1"])
    c2 = _decimal(rrq["cotisation_palier2"])
    ei = _decimal(rqap_ae["postes"]["ae_salarie"])
    ie = _decimal(entree_rqap_ae["assiette_ae_periode"])
    assert c is not None and c2 is not None and ei is not None and ie is not None

    with localcontext(_contexte_decimal()):
        p = Decimal(_PARAMETRES["periodes_annuelles"])
        pm = Decimal(demande_federale["pm"])
        taux_base = Decimal(_PARAMETRES["K2Q"]["taux_rrq_base"])
        taux_total = Decimal(_PARAMETRES["K2Q"]["taux_rrq_total_palier1"])
        f5q = c * Decimal("0.0100") / taux_total + c2
        a = p * (i - f - f2 - f5q - u1) - hd - f1
        tranche = next(
            ligne
            for ligne in _PARAMETRES["taux_tranches"]
            if ligne["borne_superieure"] is None or a <= Decimal(ligne["borne_superieure"])
        )
        r = Decimal(tranche["taux"])
        k = Decimal(tranche["constante"])
        taux_federal = Decimal(_PARAMETRES["K2Q"]["taux_federal"])
        k1 = taux_federal * tc
        rqpp_base = min(
            p * c * taux_base / taux_total,
            Decimal(_PARAMETRES["K2Q"]["maximum_rrq_base"]) * pm / Decimal(12),
        )
        credit_ei = min(p * ei, Decimal(_PARAMETRES["K2Q"]["maximum_ei_qc"]))
        credit_qpip = min(
            p * ie * Decimal(_PARAMETRES["K2Q"]["taux_qpip_credit"]),
            Decimal(_PARAMETRES["K2Q"]["maximum_qpip"]),
        )
        pr = p - Decimal(periode) + Decimal(1)
        if periode > 1:
            # Les API enfants ont déjà validé ces montants et leurs preuves.
            # Ne pas annualiser un C/EI devenu nul après atteinte du plafond.
            dq = _decimal(entree_rrq["rrq_palier1_cumul_avant"])
            d1 = _decimal(entree_rqap_ae["ae_salarie_cumul_avant"])
            qpip_ytd = _decimal(entree_rqap_ae["rqap_salarie_cumul_avant"])
            assert dq is not None and d1 is not None and qpip_ytd is not None
            rqpp_base = min(
                (dq + pr * c) * taux_base / taux_total,
                Decimal(_PARAMETRES["K2Q"]["maximum_rrq_base"]) * pm / Decimal(12),
            )
            credit_ei = min(d1 + pr * ei, Decimal(_PARAMETRES["K2Q"]["maximum_ei_qc"]))
            credit_qpip = min(
                qpip_ytd + pr * ie * Decimal(_PARAMETRES["K2Q"]["taux_qpip_credit"]),
                Decimal(_PARAMETRES["K2Q"]["maximum_qpip"]),
            )
        k2q = taux_federal * (rqpp_base + credit_ei + credit_qpip)
        k4 = min(
            taux_federal * p * i,
            taux_federal * Decimal(_PARAMETRES["K4"]["maximum_cea"]),
        )
        t3 = max(Decimal(0), r * a - k - k1 - k2q - k3 - k4)
        t1 = max(
            Decimal(0),
            (t3 - p * lcf) - Decimal(_PARAMETRES["abattement_qc"]) * t3,
        )
        t = max(Decimal(0), t1 / p + l_amount)
        retenue = t.quantize(_CENT, rounding=ROUND_HALF_UP)
        retour = {
            "schema": _PARAMETRES["schema"],
            "version_bareme": parametres["version"],
            "hash_parametres": hash_parametres,
            "parametres": parametres,
            "methode_credits": parametres.get("methode_credits", "ANNUALISATION_PERIODE_1"),
            "statut": "PREPARATOIRE",
            "qualification_regles": "NON_QUALIFIEE_POUR_PAIE",
            "authenticite_preuves": "NON_VERIFIEE",
            "contexte": {
                "annee": 2026,
                "date_paie": date_paie,
                "juridiction": "QC",
                "frequence": "bihebdomadaire",
                "periode_annuelle": periode,
                "pm": 12,
                "option": 1,
            },
            "preuves": {nom: dict(preuve) for nom, preuve in demande_federale["preuves"].items()},
            "sources_composantes": {
                "rrq_version": rrq["parametres"]["version"],
                "rqap_ae_hash_parametres": rqap_ae["hash_parametres"],
                "impot_qc_sha256": postes["impot_qc"]["source"]["sha256_pdf"],
            },
            "entrees": {
                "revenu_brut_emploi": _fmt(i),
                "TC_TD1": _fmt(tc),
                "assiette_IE": _fmt(ie),
                "RRQ_C": _fmt(c),
                "RRQ_C2": _fmt(c2),
                "EI_salarie": _fmt(ei),
            },
            "facteurs_exacts": {
                "PR": _fmt(pr),
                "F5Q": _fmt(f5q),
                "A": _fmt(a),
                "R": _fmt(r),
                "K": _fmt(k),
                "K1": _fmt(k1),
                "K2Q": _fmt(k2q),
                "K4": _fmt(k4),
                "T3": _fmt(t3),
                "T1": _fmt(t1),
                "T": _fmt(t),
            },
            "retenue_impot_federal": format(retenue, ".2f"),
            "postes_composants": {
                "rrq": {
                    "cotisation_palier1": rrq["cotisation_palier1"],
                    "cotisation_palier2": rrq["cotisation_palier2"],
                },
                "rqap_ae": dict(rqap_ae["postes"]),
                "impot_qc": dict(postes["impot_qc"]),
            },
            "motif_incompletude": "retenue préparatoire uniquement; aucune paie complète ni validation de paie",
            "statut_ccq": "UNKNOWN",
            "revenu_net": None,
            "das_complete": None,
            "cout_employeur_global": None,
            "actions_financieres_bloquees": True,
        }
    return retour, None
