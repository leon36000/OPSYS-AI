"""Calcul préparatoire RRQ régulier 2026 QC, sans outil ni raccord de paie."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from decimal import ROUND_DOWN, ROUND_HALF_UP, Context, Decimal, InvalidOperation, localcontext
from typing import Any

from . import validation

VERSION_BAREME = "TP-1015.F-2026-01-RRQ-26P-r1"
SOURCE_URL_F = "https://www.revenuquebec.ca/documents/fr/formulaires/tp/TP-1015.F%282026-01%29.pdf"
SOURCE_URL_TR26 = "https://www.revenuquebec.ca/documents/fr/formulaires/tp/TP-1015.TR.26%282026-01%29.pdf"
SOURCE_SHA256_F = "a65675dc6ad2bfc6c4fe2695d4914a57f381eccc9b8b1e1c581b7c9c8a18e72b"
SOURCE_SHA256_TR26 = "2079c958132de69216157b5c16c0296c89556e6deb69ad1854c9ebddf680c321"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ID_PREUVE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_DECIMAL_TEXTE = re.compile(r"^(?:0|[1-9][0-9]*)(?:\.[0-9]{1,2})?$")
_CHAMPS_PREUVE = frozenset({"id", "sha256", "fictif"})
_CHAMPS = frozenset(
    {
        "annee",
        "date_paie",
        "juridiction",
        "frequence",
        "periode_annuelle",
        "emploi_continu",
        "paiement_regulier_fixe",
        "gratif_ou_retroactif",
        "transfert_rpc_vers_rrq",
        "exemption_speciale",
        "assujettissement_qc",
        "pm",
        "preuve_pm",
        "salaire_rrq_periode",
        "salaire_rrq_cumul_avant",
        "rrq_palier1_cumul_avant",
        "rrq_palier2_cumul_avant",
        "preuve_assiette",
        "preuve_cumuls",
        "preuve_calendrier",
    }
)

# This canonical object is the exact executable parameter snapshot. Its digest is
# emitted with every result; the version label alone is never treated as provenance.
_PARAMETRES = {
    "edition": "TP-1015.F-2026-01 / TP-1015.TR.26-2026-01",
    "version": VERSION_BAREME,
    "annee": 2026,
    "juridiction": "QC",
    "frequence": "bihebdomadaire",
    "periodes_annuelles": 26,
    "mois_par_annee": 12,
    "pm_requis_atteste": 12,
    "maximum_gains_admissibles": "74600.00",
    "exemption_generale": "3500.00",
    "taux_palier1": "0.0630",
    "taux_premiere_supplementaire": "0.01",
    "maximum_cotisation_palier1": "4479.30",
    "maximum_supplementaire_gains_admissibles": "85000.00",
    "taux_palier2": "0.04",
    "maximum_cotisation_palier2": "416.00",
    "cent": "0.01",
    "montant_max_entree": "999999999999.99",
    "decimales_max_entree": 2,
    "exposant_max_entree": 12,
    "precision_contexte_decimal": 50,
    "emin_contexte_decimal": -999999,
    "emax_contexte_decimal": 999999,
    "clamp_contexte_decimal": 0,
    "arrondi_contexte_decimal": "ROUND_HALF_UP",
    "pieges_contexte_decimal": "all_disabled",
    "regles_arrondi": {
        "exemption_par_periode": "truncate_cent_down",
        "cotisations": "positive_below_cent_to_cent_else_half_up_cent",
        "csa": "half_up_cent_internal_convention_from_TP-1015.F_example_2026-01",
    },
    "source_f": {
        "sha256": SOURCE_SHA256_F,
        "pages": "7, 13, 29, 37-40, 46, 51-52",
        "url": SOURCE_URL_F,
    },
    "source_tr26": {
        "sha256": SOURCE_SHA256_TR26,
        "annexe": "D, table A et table C",
        "url": SOURCE_URL_TR26,
    },
    "scope": [
        "emploi continu",
        "26 periodes regulieres",
        "QC",
        "PM=12 explicitly attested",
        "no bonus or retroactive",
        "no RPC-to-RRQ transfer",
        "no special exemption",
    ],
}
CENT = Decimal(_PARAMETRES["cent"])
MAX_MONTANT = Decimal(_PARAMETRES["montant_max_entree"])
_HASH_PARAMETRES = hashlib.sha256(
    json.dumps(_PARAMETRES, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
).hexdigest()

_TAUX_PALIER1 = Decimal(_PARAMETRES["taux_palier1"])
_TAUX_PALIER2 = Decimal(_PARAMETRES["taux_palier2"])
_TAUX_PREMIERE_SUPPLEMENTAIRE = Decimal(_PARAMETRES["taux_premiere_supplementaire"])
_MGA = Decimal(_PARAMETRES["maximum_gains_admissibles"])
_EXEMPTION = Decimal(_PARAMETRES["exemption_generale"])
_MAX_COTISATION_PALIER1 = Decimal(_PARAMETRES["maximum_cotisation_palier1"])
_MGS = Decimal(_PARAMETRES["maximum_supplementaire_gains_admissibles"])
_MAX_COTISATION_PALIER2 = Decimal(_PARAMETRES["maximum_cotisation_palier2"])
_ANNEE = _PARAMETRES["annee"]
_P = Decimal(_PARAMETRES["periodes_annuelles"])
_MOIS_ANNEE = Decimal(_PARAMETRES["mois_par_annee"])
_PM = Decimal(_PARAMETRES["pm_requis_atteste"])


def _refus(code: str, detail: str) -> tuple[None, dict[str, str]]:
    return None, validation.construire_verdict(code, detail=detail)


def _decimal_montant(valeur: object) -> Decimal | None:
    """Parse a bounded M5 monetary input without accepting float or bool."""
    if not isinstance(valeur, (str, Decimal)) or isinstance(valeur, bool):
        return None
    if isinstance(valeur, str) and len(valeur) > 64:
        return None
    if isinstance(valeur, str) and _DECIMAL_TEXTE.fullmatch(valeur) is None:
        return None
    try:
        montant = Decimal(valeur)
    except (InvalidOperation, ValueError):
        return None
    if not montant.is_finite() or montant < 0 or montant > MAX_MONTANT:
        return None
    exposant = montant.as_tuple().exponent
    if not isinstance(exposant, int) or not -_PARAMETRES["decimales_max_entree"] <= exposant <= _PARAMETRES[
        "exposant_max_entree"
    ]:
        return None
    return montant


def _preuve_valide(preuve: Any) -> bool:
    return (
        isinstance(preuve, dict)
        and set(preuve) == _CHAMPS_PREUVE
        and isinstance(preuve.get("id"), str)
        and _ID_PREUVE.fullmatch(preuve["id"]) is not None
        and isinstance(preuve.get("sha256"), str)
        and _SHA256.fullmatch(preuve["sha256"]) is not None
        and type(preuve.get("fictif")) is bool
    )


def _arrondir_cotisation(montant: Decimal) -> Decimal:
    if montant <= 0:
        return Decimal("0.00")
    if montant < CENT:
        return CENT
    return montant.quantize(CENT, rounding=ROUND_HALF_UP)


def _texte_montant(montant: Decimal) -> str:
    return format(montant.quantize(CENT, rounding=ROUND_HALF_UP), ".2f")


def calculer_cotisation_rrq_preparatoire(
    **demande: object,
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Calcule C, C2 et CSA pour le seul périmètre régulier explicitement supporté.

    Le hash des paramètres identifie la transcription utilisée; les références et
    attestations d'entrée restent déclaratives et leur authenticité n'est pas vérifiée.
    """
    if set(demande) != _CHAMPS:
        return _refus("REJ-PAIE-ASSIETTE-INVALIDE", "structure de demande RRQ invalide")
    annee = demande["annee"]
    date_paie = demande["date_paie"]
    juridiction = demande["juridiction"]
    frequence = demande["frequence"]
    periode_annuelle = demande["periode_annuelle"]
    emploi_continu = demande["emploi_continu"]
    paiement_regulier_fixe = demande["paiement_regulier_fixe"]
    gratif_ou_retroactif = demande["gratif_ou_retroactif"]
    transfert_rpc_vers_rrq = demande["transfert_rpc_vers_rrq"]
    exemption_speciale = demande["exemption_speciale"]
    assujettissement_qc = demande["assujettissement_qc"]
    pm = demande["pm"]
    preuve_pm = demande["preuve_pm"]
    salaire_rrq_periode = demande["salaire_rrq_periode"]
    salaire_rrq_cumul_avant = demande["salaire_rrq_cumul_avant"]
    rrq_palier1_cumul_avant = demande["rrq_palier1_cumul_avant"]
    rrq_palier2_cumul_avant = demande["rrq_palier2_cumul_avant"]
    preuve_assiette = demande["preuve_assiette"]
    preuve_cumuls = demande["preuve_cumuls"]
    preuve_calendrier = demande["preuve_calendrier"]
    if type(annee) is not int or annee != _ANNEE:
        return _refus("REJ-PAIE-EDITION-ABSENTE", "seule l’édition RRQ 2026-01 est transcrite")
    if not isinstance(date_paie, str):
        return _refus("REJ-PAIE-DATE-INVALIDE", "date ISO 2026 requise")
    try:
        date_parsee = date.fromisoformat(date_paie)
    except ValueError:
        return _refus("REJ-PAIE-DATE-INVALIDE", "date ISO 2026 requise")
    if date_parsee.isoformat() != date_paie or date_parsee.year != _ANNEE:
        return _refus("REJ-PAIE-DATE-INVALIDE", "date ISO dans l’année documentaire 2026 requise")
    if juridiction != _PARAMETRES["juridiction"]:
        return _refus("REJ-PAIE-JURIDICTION-NON-COUVERTE", "seule la juridiction QC est couverte")
    if frequence != _PARAMETRES["frequence"]:
        return _refus("REJ-PAIE-FREQUENCE-NON-COUVERTE", "seule la fréquence de 26 périodes est couverte")
    if type(periode_annuelle) is not int or not 1 <= periode_annuelle <= int(_P):
        return _refus("REJ-PAIE-PERIODE-INVALIDE", "rang de période entier entre 1 et 26 requis")

    indicateurs = {
        "emploi_continu": emploi_continu,
        "paiement_regulier_fixe": paiement_regulier_fixe,
        "gratif_ou_retroactif": gratif_ou_retroactif,
        "transfert_rpc_vers_rrq": transfert_rpc_vers_rrq,
        "exemption_speciale": exemption_speciale,
        "assujettissement_qc": assujettissement_qc,
    }
    if any(type(valeur) is not bool for valeur in indicateurs.values()):
        return _refus("REJ-PAIE-ASSIETTE-INVALIDE", "indicateurs booléens stricts requis")
    if (
        not emploi_continu
        or not paiement_regulier_fixe
        or gratif_ou_retroactif
        or transfert_rpc_vers_rrq
        or exemption_speciale
        or not assujettissement_qc
    ):
        return _refus("REJ-PAIE-ASSIETTE-INVALIDE", "situation hors couverture RRQ préparatoire")
    if type(pm) is not int or pm != int(_PM) or not _preuve_valide(preuve_pm):
        return _refus("REJ-PAIE-SNAPSHOT-REQUIS", "PM=12 et référence d’attestation explicite requis")
    preuves = {
        "assiette": preuve_assiette,
        "cumuls": preuve_cumuls,
        "calendrier": preuve_calendrier,
    }
    if any(not _preuve_valide(preuve) for preuve in preuves.values()):
        return _refus("REJ-PAIE-SNAPSHOT-REQUIS", "références/hash d’assiette, cumuls et calendrier requis")

    montants_entree = {
        "salaire_rrq_periode": salaire_rrq_periode,
        "salaire_rrq_cumul_avant": salaire_rrq_cumul_avant,
        "rrq_palier1_cumul_avant": rrq_palier1_cumul_avant,
        "rrq_palier2_cumul_avant": rrq_palier2_cumul_avant,
    }
    montants = {nom: _decimal_montant(valeur) for nom, valeur in montants_entree.items()}
    if any(valeur is None for valeur in montants.values()):
        return _refus("REJ-PAIE-ASSIETTE-INVALIDE", "montants CAD finis à deux décimales au plus requis")
    salaire_courant = montants["salaire_rrq_periode"]
    salaire_avant = montants["salaire_rrq_cumul_avant"]
    palier1_avant = montants["rrq_palier1_cumul_avant"]
    palier2_avant = montants["rrq_palier2_cumul_avant"]
    assert salaire_courant is not None
    assert salaire_avant is not None
    assert palier1_avant is not None
    assert palier2_avant is not None
    if palier1_avant > _MAX_COTISATION_PALIER1 or palier2_avant > _MAX_COTISATION_PALIER2:
        return _refus("REJ-PAIE-ASSIETTE-INVALIDE", "cumul RRQ antérieur dépasse le plafond annuel")
    if periode_annuelle == 1 and any(
        montant != 0 for montant in (salaire_avant, palier1_avant, palier2_avant)
    ):
        return _refus("REJ-PAIE-ASSIETTE-INVALIDE", "les cumuls avant la première période doivent être nuls")

    contexte_calcul = Context(
        prec=_PARAMETRES["precision_contexte_decimal"],
        rounding=ROUND_HALF_UP,
        Emin=_PARAMETRES["emin_contexte_decimal"],
        Emax=_PARAMETRES["emax_contexte_decimal"],
        clamp=_PARAMETRES["clamp_contexte_decimal"],
    )
    for signal in contexte_calcul.traps:
        contexte_calcul.traps[signal] = False
    with localcontext(contexte_calcul):
        exemption = (_EXEMPTION / _P).quantize(CENT, rounding=ROUND_DOWN)
        plafond_premier_restant = max(
            Decimal(0), _MAX_COTISATION_PALIER1 * (Decimal(pm) / _MOIS_ANNEE) - palier1_avant
        )
        base_premier = max(Decimal(0), _TAUX_PALIER1 * (salaire_courant - exemption))
        cotisation_palier1 = _arrondir_cotisation(min(plafond_premier_restant, base_premier))

        plafond_second_restant = max(
            Decimal(0), _MAX_COTISATION_PALIER2 * (Decimal(pm) / _MOIS_ANNEE) - palier2_avant
        )
        seuil_palier2_avant = max(salaire_avant, _MGA * (Decimal(pm) / _MOIS_ANNEE))
        base_second = max(
            Decimal(0), _TAUX_PALIER2 * (salaire_avant + salaire_courant - seuil_palier2_avant)
        )
        cotisation_palier2 = _arrondir_cotisation(min(plafond_second_restant, base_second))
        rrq_total = cotisation_palier1 + cotisation_palier2
        csa_exact = (
            cotisation_palier1 * (_TAUX_PREMIERE_SUPPLEMENTAIRE / _TAUX_PALIER1)
            + cotisation_palier2
        )
        csa = csa_exact.quantize(CENT, rounding=ROUND_HALF_UP)

        return {
            "mode": "PREPARATOIRE",
            "statut": "NON_QUALIFIEE_POUR_PAIE",
            "juridiction": _PARAMETRES["juridiction"],
            "annee": _ANNEE,
            "date_paie": date_paie,
            "frequence": _PARAMETRES["frequence"],
            "periode_annuelle": periode_annuelle,
            "emploi_continu": True,
            "pm": pm,
            "calendrier_statut": "DECLARATION_NON_VERIFIEE",
            "preuves": {nom: dict(preuve) for nom, preuve in {"pm": preuve_pm, **preuves}.items()},
            "preuve_authenticite": "NON_VERIFIEE",
            "statut_ccq": "UNKNOWN",
            "parametres": {
                "version": VERSION_BAREME,
                "sha256": _HASH_PARAMETRES,
                "snapshot": json.loads(
                    json.dumps(_PARAMETRES, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                ),
                "edition": _PARAMETRES["edition"],
                "sources": [
                    {"url": SOURCE_URL_F, "sha256": SOURCE_SHA256_F, "pages": "7, 13, 29, 37-40, 46, 51-52"},
                    {"url": SOURCE_URL_TR26, "sha256": SOURCE_SHA256_TR26, "annexe": "D, tables A/C"},
                ],
            },
            "entrees": {
                "salaire_rrq_periode": _texte_montant(salaire_courant),
                "salaire_rrq_cumul_avant": _texte_montant(salaire_avant),
                "rrq_palier1_cumul_avant": _texte_montant(palier1_avant),
                "rrq_palier2_cumul_avant": _texte_montant(palier2_avant),
            },
            "exemption_par_periode": _texte_montant(exemption),
            "cotisation_palier1": _texte_montant(cotisation_palier1),
            "cotisation_palier2": _texte_montant(cotisation_palier2),
            "cotisation_rrq_totale": _texte_montant(rrq_total),
            "CSA": _texte_montant(csa),
            "detail_calcul": {
                "csa_exacte_avant_arrondi": str(csa_exact),
                "arrondi_csa": "centime_demi_superieur_implementation_alignee_exemple_TP-1015.F_p46",
            },
            "net": None,
            "DAS": None,
            "cout_employeur_global": None,
            "actions_bloquees": True,
        }, None
