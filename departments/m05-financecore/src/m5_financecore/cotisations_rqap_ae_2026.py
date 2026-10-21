"""Calculs préparatoires séparés RQAP et AE-QC 2026, sans raccord de paie."""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from datetime import date
from decimal import ROUND_HALF_UP, Context, Decimal, InvalidOperation, localcontext
from typing import Any

from . import validation

SOURCE_TP1015_SHA256 = "a65675dc6ad2bfc6c4fe2695d4914a57f381eccc9b8b1e1c581b7c9c8a18e72b"
SOURCE_T4127_JAN_SHA256 = "c715b8e6d33e0887119e0462b9a4cf8915370c56381932f1d7ba3a32385ddd8c"
SOURCE_T4127_JUL_SHA256 = "69d86d952cb14c786fdcc0321ec293f66db1529276ef310217b3ade47db25671"
SOURCE_CRA_EI_SHA256 = "b72d19f75f50e8b9515404226d73b2e6896fb8e749adc6854a12683c582ada35"

_CENT = Decimal("0.01")
_MAX_MONTANT = Decimal("999999999999.99")
_TEXTE_MONTANT = re.compile(r"^(?:0|[1-9][0-9]{0,11})\.[0-9]{2}$")
_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ID_PREUVE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_PREUVE_KEYS = frozenset({"id", "sha256", "fictif"})
_PARAMETRES = {
    "schema": "m5-cotisations-qc-preparatoires/1",
    "annee": 2026,
    "juridiction": "QC",
    "frequence": "bihebdomadaire",
    "periodes_annuelles": 26,
    "limites_montant": {"minimum": "0.00", "maximum": "999999999999.99", "precision": 2},
    "decimal": {
        "precision": 50,
        "emin": -999999,
        "emax": 999999,
        "clamp": 0,
        "arrondi": "ROUND_HALF_UP",
        "pieges": "desactives",
    },
    "rqap": {
        "edition": "TP-1015.F-2026-01",
        "en_vigueur": "2026-01-01",
        "revenu_max_assurable": "103000.00",
        "taux_salarie": "0.00430",
        "maximum_salarie": "442.90",
        "taux_employeur": "0.00602",
        "maximum_employeur": "620.06",
        "arrondi_salarie": "half_up_cent; montant positif sous 0.01 devient 0.01",
        "arrondi_employeur": "half_up_cent; aucun minimum spécial sous 0.01",
        "sources": {
            "sha256": SOURCE_TP1015_SHA256,
            "pages": "7, 41-42",
            "url": "https://www.revenuquebec.ca/documents/fr/formulaires/tp/TP-1015.F%282026-01%29.pdf",
        },
    },
    "ae_qc": {
        "edition_formules": "T4127-122-2026-01; T4127-123-2026-07",
        "applicabilite_documentaire": "janvier:2026-01-01/06-30; juillet:depuis_2026-07-01; formule_AE_inchangee",
        "revenu_max_assurable": "68900.00",
        "taux_salarie": "0.0130",
        "maximum_salarie": "895.70",
        "taux_employeur": "0.01820",
        "maximum_employeur": "1253.98",
        "arrondi_salarie_et_employeur": "half_up_cent (T4127 mathematical rules)",
        "relation_employeur": "1.4 times employee rate; not applied to rounded employee premium",
        "sources": {
            "t4127_jan_sha256": SOURCE_T4127_JAN_SHA256,
            "t4127_jul_sha256": SOURCE_T4127_JUL_SHA256,
            "cra_rates_sha256": SOURCE_CRA_EI_SHA256,
            "pages": "T4127 ch.7 p.31, table 8.7 p.34, general rounding p.3; CRA EI rates/maximums",
            "url": "https://www.canada.ca/en/revenue-agency/services/tax/businesses/topics/payroll/payroll-deductions-contributions/employment-insurance-ei/ei-premium-rates-maximums.html",
        },
    },
    "portee": [
        "2026; QC; 26 periodes bihebdomadaires; emploi regulier; un employeur",
        "assiettes et cumuls avant la periode prouves separement pour chaque ligne",
        "exclusions: transfert de province, taux AE reduit, exemptions, remuneration speciale, multi-employeurs",
        "preuves declaratives; authenticite non verifiee; catalogue reglementaire non qualifie",
    ],
}
HASH_PARAMETRES = hashlib.sha256(
    json.dumps(_PARAMETRES, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
).hexdigest()

_CHAMPS = frozenset(
    {
        "annee",
        "date_paie",
        "juridiction",
        "frequence",
        "periode_annuelle",
        "paiement_regulier_fixe",
        "gratif_ou_retroactif",
        "transfert_province",
        "taux_ae_reduit",
        "exemption_speciale",
        "assujettissement_qc",
        "salaire_en_argent_confirme",
        "assiette_rqap_periode",
        "rqap_salarie_cumul_avant",
        "rqap_employeur_cumul_avant",
        "assiette_ae_periode",
        "ae_salarie_cumul_avant",
        "ae_employeur_cumul_avant",
        "preuve_assiette_rqap",
        "preuve_cumul_rqap_salarie",
        "preuve_cumul_rqap_employeur",
        "preuve_assiette_ae",
        "preuve_cumul_ae_salarie",
        "preuve_cumul_ae_employeur",
    }
)


def _refus(code: str, detail: str) -> tuple[None, dict[str, str]]:
    return None, validation.construire_verdict(code, detail=detail)


def _montant(valeur: object) -> Decimal | None:
    if not isinstance(valeur, str) or len(valeur) > 15 or _TEXTE_MONTANT.fullmatch(valeur) is None:
        return None
    try:
        resultat = Decimal(valeur)
    except (InvalidOperation, ValueError):
        return None
    if not resultat.is_finite() or resultat < 0 or resultat > _MAX_MONTANT:
        return None
    return resultat


def _preuve_valide(preuve: object) -> bool:
    return (
        isinstance(preuve, dict)
        and set(preuve) == _PREUVE_KEYS
        and isinstance(preuve.get("id"), str)
        and _ID_PREUVE.fullmatch(preuve["id"]) is not None
        and isinstance(preuve.get("sha256"), str)
        and _HEX_SHA256.fullmatch(preuve["sha256"]) is not None
        and type(preuve.get("fictif")) is bool
    )


def _arrondir(montant: Decimal) -> Decimal:
    return montant.quantize(_CENT, rounding=ROUND_HALF_UP)


def _montant_salarie_rqap(montant: Decimal) -> Decimal:
    if montant > 0 and montant < _CENT:
        return _CENT
    return _arrondir(montant)


def _contexte_decimal() -> Context:
    contexte = Context(prec=50, rounding=ROUND_HALF_UP, Emin=-999999, Emax=999999, clamp=0)
    for signal in contexte.traps:
        contexte.traps[signal] = False
    return contexte


def calculer_cotisations_rqap_ae_preparatoires(
    **demande: object,
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Calcule quatre postes distincts; les attestations d'entrée restent déclaratives."""
    if set(demande) != _CHAMPS:
        return _refus("REJ-PAIE-ASSIETTE-INVALIDE", "structure de demande RQAP/AE invalide")
    if type(demande["annee"]) is not int or demande["annee"] != 2026:
        return _refus("REJ-PAIE-EDITION-ABSENTE", "seule l’édition des cotisations 2026 est transcrite")
    date_paie = demande["date_paie"]
    if not isinstance(date_paie, str):
        return _refus("REJ-PAIE-DATE-INVALIDE", "date ISO 2026 requise")
    try:
        date_parsee = date.fromisoformat(date_paie)
    except ValueError:
        return _refus("REJ-PAIE-DATE-INVALIDE", "date ISO 2026 requise")
    if date_parsee.isoformat() != date_paie or date_parsee.year != 2026:
        return _refus("REJ-PAIE-DATE-INVALIDE", "date ISO exacte dans l’année 2026 requise")
    if demande["juridiction"] != "QC":
        return _refus("REJ-PAIE-JURIDICTION-NON-COUVERTE", "seule la province QC est couverte")
    if demande["frequence"] != "bihebdomadaire":
        return _refus("REJ-PAIE-FREQUENCE-NON-COUVERTE", "seule la fréquence de 26 périodes est couverte")
    if type(demande["periode_annuelle"]) is not int or not 1 <= demande["periode_annuelle"] <= 26:
        return _refus("REJ-PAIE-PERIODE-INVALIDE", "période entière entre 1 et 26 requise")
    indicateurs = (
        "paiement_regulier_fixe",
        "gratif_ou_retroactif",
        "transfert_province",
        "taux_ae_reduit",
        "exemption_speciale",
        "assujettissement_qc",
        "salaire_en_argent_confirme",
    )
    if any(type(demande[nom]) is not bool for nom in indicateurs):
        return _refus("REJ-PAIE-ASSIETTE-INVALIDE", "indicateurs booléens stricts requis")
    if (
        not demande["paiement_regulier_fixe"]
        or demande["gratif_ou_retroactif"]
        or demande["transfert_province"]
        or demande["taux_ae_reduit"]
        or demande["exemption_speciale"]
        or not demande["assujettissement_qc"]
        or not demande["salaire_en_argent_confirme"]
    ):
        return _refus("REJ-PAIE-ASSIETTE-INVALIDE", "situation hors portée régulière attestée RQAP/AE")

    noms_montants = (
        "assiette_rqap_periode",
        "rqap_salarie_cumul_avant",
        "rqap_employeur_cumul_avant",
        "assiette_ae_periode",
        "ae_salarie_cumul_avant",
        "ae_employeur_cumul_avant",
    )
    montants = {nom: _montant(demande[nom]) for nom in noms_montants}
    if any(valeur is None for valeur in montants.values()):
        return _refus("REJ-PAIE-ASSIETTE-INVALIDE", "chaînes CAD canoniques à deux décimales requises")
    if demande["periode_annuelle"] == 1 and any(
        montants[nom] != 0
        for nom in (
            "rqap_salarie_cumul_avant",
            "rqap_employeur_cumul_avant",
            "ae_salarie_cumul_avant",
            "ae_employeur_cumul_avant",
        )
    ):
        return _refus("REJ-PAIE-ASSIETTE-INVALIDE", "les cumuls antérieurs doivent être nuls à la période 1")
    plafonds = {
        "rqap_salarie_cumul_avant": Decimal(_PARAMETRES["rqap"]["maximum_salarie"]),
        "rqap_employeur_cumul_avant": Decimal(_PARAMETRES["rqap"]["maximum_employeur"]),
        "ae_salarie_cumul_avant": Decimal(_PARAMETRES["ae_qc"]["maximum_salarie"]),
        "ae_employeur_cumul_avant": Decimal(_PARAMETRES["ae_qc"]["maximum_employeur"]),
    }
    if any(montants[nom] > plafond for nom, plafond in plafonds.items()):
        return _refus("REJ-PAIE-ASSIETTE-INVALIDE", "cumul antérieur supérieur au plafond annuel correspondant")
    if (
        montants["rqap_salarie_cumul_avant"] == plafonds["rqap_salarie_cumul_avant"]
        and montants["rqap_employeur_cumul_avant"] < plafonds["rqap_employeur_cumul_avant"]
    ):
        return _refus("REJ-PAIE-ASSIETTE-INVALIDE", "le maximum salarié RQAP impose aussi le maximum employeur")
    preuves = (
        "preuve_assiette_rqap",
        "preuve_cumul_rqap_salarie",
        "preuve_cumul_rqap_employeur",
        "preuve_assiette_ae",
        "preuve_cumul_ae_salarie",
        "preuve_cumul_ae_employeur",
    )
    if any(not _preuve_valide(demande[nom]) for nom in preuves):
        return _refus("REJ-PAIE-SNAPSHOT-REQUIS", "une référence/hash distincts par assiette et cumul est requis")

    with localcontext(_contexte_decimal()):
        rqap_salarie_brut = min(
            Decimal(_PARAMETRES["rqap"]["maximum_salarie"]) - montants["rqap_salarie_cumul_avant"],
            Decimal(_PARAMETRES["rqap"]["taux_salarie"]) * montants["assiette_rqap_periode"],
        )
        rqap_employeur_brut = min(
            Decimal(_PARAMETRES["rqap"]["maximum_employeur"]) - montants["rqap_employeur_cumul_avant"],
            Decimal(_PARAMETRES["rqap"]["taux_employeur"]) * montants["assiette_rqap_periode"],
        )
        ae_salarie_brut = min(
            Decimal(_PARAMETRES["ae_qc"]["maximum_salarie"]) - montants["ae_salarie_cumul_avant"],
            Decimal(_PARAMETRES["ae_qc"]["taux_salarie"]) * montants["assiette_ae_periode"],
        )
        ae_employeur_brut = min(
            Decimal(_PARAMETRES["ae_qc"]["maximum_employeur"]) - montants["ae_employeur_cumul_avant"],
            Decimal(_PARAMETRES["ae_qc"]["taux_employeur"]) * montants["assiette_ae_periode"],
        )
        montants_sortie = {
            "rqap_salarie": _montant_salarie_rqap(rqap_salarie_brut),
            "rqap_employeur": _arrondir(rqap_employeur_brut),
            "ae_salarie": _arrondir(ae_salarie_brut),
            "ae_employeur": _arrondir(ae_employeur_brut),
        }
        rapport = {
            "schema": _PARAMETRES["schema"],
            "annee": 2026,
            "date_paie": date_paie,
            "juridiction": "QC",
            "frequence": "bihebdomadaire",
            "periode_annuelle": demande["periode_annuelle"],
            "statut": "PREPARATOIRE",
            "qualification_regles": "NON_QUALIFIEE_POUR_PAIE",
            "authenticite_preuves": "NON_VERIFIEE",
            "hash_parametres": HASH_PARAMETRES,
            "parametres": deepcopy(_PARAMETRES),
            "postes": {nom: format(valeur, ".2f") for nom, valeur in montants_sortie.items()},
            "preuves": {nom: deepcopy(demande[nom]) for nom in preuves},
            "statut_ccq": "UNKNOWN",
            "retenue_impot_federal": None,
            "revenu_net": None,
            "das_complete": None,
            "cout_employeur_global": None,
            "actions_financieres_bloquees": True,
        }
    return rapport, None
