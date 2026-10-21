"""Formule préparatoire QC TP-1015.F 2026, sans activation ni calcul de paie."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import ROUND_HALF_UP, Context, Decimal, InvalidOperation, localcontext
from typing import Any

from . import validation

VERSION_BAREME = "TP-1015.F-2026-01-2.1.1"
SOURCE_SHA256 = "a65675dc6ad2bfc6c4fe2695d4914a57f381eccc9b8b1e1c581b7c9c8a18e72b"
SOURCE_URL = "https://www.revenuquebec.ca/documents/fr/formulaires/tp/TP-1015.F%282026-01%29.pdf"
SOURCE_PAGES = "12-16, 46-49"
MAX_MONTANT = Decimal("999999999999.99")
CENT = Decimal("0.01")
_PARAMETRES = {
    "edition": "TP-1015.F-2026-01",
    "formule": "2.1.1",
    "P": 26,
    "deduction_travailleur": {"taux": "0.06", "plafond_annuel": "1450"},
    "tranches": [
        {"maximum_I": "54345", "taux": "0.14", "constante": "0"},
        {"maximum_I": "108680", "taux": "0.19", "constante": "2717"},
        {"maximum_I": "132245", "taux": "0.24", "constante": "8151"},
        {"maximum_I": None, "taux": "0.2575", "constante": "10465"},
    ],
    "credits": {"E": "0.14", "Q_Q1": "0.15"},
    "CSA_ratio": "0.01/0.0630",
    "B2_regulier_sans_forfait": "0",
    "plafond_annuel_FTQ_Fondaction": "5000",
    "source_pages": SOURCE_PAGES,
    "politique_implementation": {"H": "centime_demi_superieur", "A": "centime_demi_superieur"},
    "contexte_decimal": {
        "precision": 50,
        "arrondi": "ROUND_HALF_UP",
        "emin": -999999,
        "emax": 999999,
        "clamp": 0,
        "pieges": "desactives",
    },
}
HASH_SNAPSHOT_PARAMETRES = hashlib.sha256(
    json.dumps(_PARAMETRES, sort_keys=True, separators=(",", ":")).encode("utf-8")
).hexdigest()
_P = Decimal(_PARAMETRES["P"])
_H_TAUX = Decimal(_PARAMETRES["deduction_travailleur"]["taux"])
_H_PLAFOND = Decimal(_PARAMETRES["deduction_travailleur"]["plafond_annuel"])
_E_CREDIT = Decimal(_PARAMETRES["credits"]["E"])
_Q_CREDIT = Decimal(_PARAMETRES["credits"]["Q_Q1"])
_PLAFOND_FONDS = Decimal(_PARAMETRES["plafond_annuel_FTQ_Fondaction"])
_TRANCHES = tuple(
    (
        Decimal(ligne["maximum_I"]) if ligne["maximum_I"] is not None else None,
        Decimal(ligne["taux"]),
        Decimal(ligne["constante"]),
    )
    for ligne in _PARAMETRES["tranches"]
)

_MONTANTS = (
    "G",
    "F",
    "D",
    "CSA",
    "J_annuel",
    "J3",
    "J1_annuel",
    "J2",
    "K1_annuel",
    "K2",
    "E1",
    "E2",
    "Q",
    "Q1",
    "fonds_travailleurs_total_annuel_programme",
    "L",
)
_BOOL = (
    "paiement_regulier_fixe",
    "gratif_ou_retroactif",
    "remuneration_variable",
    "exonere",
    "transfert_province",
    "resident",
    "J_determined_after_period_1",
    "J1_determined_after_period_1",
    "K1_determined_after_period_1",
)


def _refus(code: str, detail: str) -> tuple[None, dict[str, str]]:
    return None, validation.construire_verdict(code, detail=detail)


def _decimal_montant(valeur: object) -> Decimal | None:
    if not isinstance(valeur, (str, Decimal)) or isinstance(valeur, bool):
        return None
    if isinstance(valeur, str) and len(valeur) > 64:
        return None
    if isinstance(valeur, Decimal):
        exposant = valeur.as_tuple().exponent
        if not isinstance(exposant, int) or not -2 <= exposant <= 12:
            return None
    try:
        nombre = Decimal(valeur)
    except (InvalidOperation, ValueError):
        return None
    if not nombre.is_finite() or nombre < 0 or nombre > MAX_MONTANT:
        return None
    if not -2 <= nombre.as_tuple().exponent <= 12:
        return None
    return nombre


def _arrondir(nombre: Decimal, quantum: Decimal) -> Decimal:
    return nombre.quantize(quantum, rounding=ROUND_HALF_UP)


def _contexte_decimal() -> Context:
    contexte = Context(
        prec=_PARAMETRES["contexte_decimal"]["precision"],
        rounding=ROUND_HALF_UP,
        Emin=_PARAMETRES["contexte_decimal"]["emin"],
        Emax=_PARAMETRES["contexte_decimal"]["emax"],
        clamp=_PARAMETRES["contexte_decimal"]["clamp"],
    )
    for signal in contexte.traps:
        contexte.traps[signal] = False
    return contexte


def _tranche(revenu: Decimal) -> tuple[Decimal, Decimal]:
    for borne, taux, constante in _TRANCHES:
        if borne is None or revenu <= borne:
            return taux, constante
    raise AssertionError("tranche fiscale sans borne finale")


def calculer_retenue_preparatoire(
    *,
    annee: object,
    date_paie: object,
    juridiction: object,
    frequence: object,
    periode_annuelle: object,
    paiement_regulier_fixe: object,
    gratif_ou_retroactif: object,
    remuneration_variable: object,
    exonere: object,
    transfert_province: object,
    resident: object,
    G: object,
    F: object,
    D: object,
    CSA: object,
    J_annuel: object,
    J3: object,
    J_determined_after_period_1: object,
    J1_annuel: object,
    J2: object,
    J1_determined_after_period_1: object,
    K1_annuel: object,
    K2: object,
    K1_determined_after_period_1: object,
    E1: object,
    E2: object,
    Q: object,
    Q1: object,
    fonds_travailleurs_total_annuel_programme: object,
    L: object,
    **champs_inconnus: object,
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Produit un calcul préparatoire de l’impôt QC régulier; n’est pas utilisable en paie.

    `CSA` est une déduction par période déjà calculée à partir des assiettes RRQ par un
    processus distinct. Cette fonction ne calcule pas RRQ, avantages imposables, net, ni
    cumul d’assiettes. `PR` est déterminé ici comme 27 moins la période courante.
    """
    if champs_inconnus:
        return _refus("REJ-PAIE-ASSIETTE-INVALIDE", "champ de formule inconnu")
    if type(annee) is not int or annee != 2026:
        return _refus("REJ-PAIE-EDITION-ABSENTE", "seule l’édition documentaire 2026-01 est transcrite")
    if not isinstance(date_paie, str):
        return _refus("REJ-PAIE-DATE-INVALIDE", "date ISO 2026 requise")
    try:
        date_parsee = date.fromisoformat(date_paie)
    except ValueError:
        return _refus("REJ-PAIE-DATE-INVALIDE", "date ISO 2026 requise")
    if date_parsee.isoformat() != date_paie or date_parsee.year != 2026:
        return _refus("REJ-PAIE-DATE-INVALIDE", "date ISO dans l’année documentaire 2026 requise")
    if juridiction != "QC":
        return _refus("REJ-PAIE-JURIDICTION-NON-COUVERTE", "seule la juridiction QC est transcrite")
    if frequence != "bihebdomadaire":
        return _refus("REJ-PAIE-FREQUENCE-NON-COUVERTE", "seule la fréquence 26 périodes est transcrite")
    if type(periode_annuelle) is not int or not 1 <= periode_annuelle <= 26:
        return _refus("REJ-PAIE-PERIODE-INVALIDE", "rang de période entier entre 1 et 26 requis")
    indicateurs = {
        "paiement_regulier_fixe": paiement_regulier_fixe,
        "gratif_ou_retroactif": gratif_ou_retroactif,
        "remuneration_variable": remuneration_variable,
        "exonere": exonere,
        "transfert_province": transfert_province,
        "resident": resident,
        "J_determined_after_period_1": J_determined_after_period_1,
        "J1_determined_after_period_1": J1_determined_after_period_1,
        "K1_determined_after_period_1": K1_determined_after_period_1,
    }
    if any(type(indicateurs[champ]) is not bool for champ in _BOOL):
        return _refus("REJ-PAIE-ASSIETTE-INVALIDE", "indicateurs de contexte booléens requis")
    if periode_annuelle == 1 and (
        J_determined_after_period_1 or J1_determined_after_period_1 or K1_determined_after_period_1
    ):
        return _refus("REJ-PAIE-ASSIETTE-INVALIDE", "marqueur après période 1 incohérent avec la période courante")
    if (
        not paiement_regulier_fixe
        or gratif_ou_retroactif
        or remuneration_variable
        or exonere
        or transfert_province
        or not resident
    ):
        return _refus("REJ-PAIE-ASSIETTE-INVALIDE", "situation hors couverture de la formule régulière préparatoire")
    valeurs_montants = {
        "G": G,
        "F": F,
        "D": D,
        "CSA": CSA,
        "J_annuel": J_annuel,
        "J3": J3,
        "J1_annuel": J1_annuel,
        "J2": J2,
        "K1_annuel": K1_annuel,
        "K2": K2,
        "E1": E1,
        "E2": E2,
        "Q": Q,
        "Q1": Q1,
        "fonds_travailleurs_total_annuel_programme": fonds_travailleurs_total_annuel_programme,
        "L": L,
    }
    montants = {champ: _decimal_montant(valeurs_montants[champ]) for champ in _MONTANTS}
    if any(valeur is None for valeur in montants.values()):
        return _refus("REJ-PAIE-ASSIETTE-INVALIDE", "montants CAD non négatifs à deux décimales au plus requis")
    if montants["fonds_travailleurs_total_annuel_programme"] > _PLAFOND_FONDS:
        return _refus("REJ-PAIE-ASSIETTE-INVALIDE", "total annuel FTQ/Fondaction supérieur au plafond transcrit")
    with localcontext(_contexte_decimal()):
        if montants["Q"] + montants["Q1"] > montants["fonds_travailleurs_total_annuel_programme"]:
            return _refus("REJ-PAIE-ASSIETTE-INVALIDE", "Q/Q1 de la période dépassent le total annuel déclaré")

    with localcontext(_contexte_decimal()):
        P = _P
        periode = Decimal(periode_annuelle)
        PR = P - periode + 1
        H = _arrondir(min(_H_TAUX * montants["D"], _H_PLAFOND / P), CENT)
        J = (P * montants["J3"] / PR) if J_determined_after_period_1 else montants["J_annuel"]
        J1 = (P * montants["J2"] / PR) if J1_determined_after_period_1 else montants["J1_annuel"]
        K1 = (P * montants["K2"] / PR) if K1_determined_after_period_1 else montants["K1_annuel"]
        revenu_imposable = max(Decimal(0), P * (montants["G"] - montants["F"] - H - montants["CSA"]) - J - J1)
        E_exact = montants["E1"] + montants["E2"]
        E = _arrondir(E_exact, Decimal("1"))
        T, K_constante = _tranche(revenu_imposable)
        Y = max(
            Decimal(0),
            T * revenu_imposable
            - K_constante
            - K1
            - _E_CREDIT * E
            - _Q_CREDIT * P * montants["Q"]
            - _Q_CREDIT * P * montants["Q1"],
        )
        A = max(Decimal(0), _arrondir(Y / P + montants["L"], CENT))
        I_sortie = _arrondir(revenu_imposable, CENT)
        Y_sortie = _arrondir(Y, CENT)
        H_sortie = _arrondir(H, CENT)
        J_sortie = _arrondir(J, CENT)
        J1_sortie = _arrondir(J1, CENT)
        K1_sortie = _arrondir(K1, CENT)

    return {
        "mode": "PREPARATOIRE",
        "methode": "retenue_impot_qc_paiement_regulier",
        "retenue_qc_preparatoire": f"{A:.2f}",
        "devise": "CAD",
        "net": None,
        "actions_bloquees": True,
        "human_validation_required": True,
        "source": {
            "statut": "NON_QUALIFIEE_POUR_PAIE",
            "edition": "2026-01",
            "bareme_version": VERSION_BAREME,
            "formule": "TP-1015.F/2.1.1",
            "url": SOURCE_URL,
            "pages": SOURCE_PAGES,
            "sha256_pdf": SOURCE_SHA256,
            "sha256_snapshot_parametres": HASH_SNAPSHOT_PARAMETRES,
            "applicabilite_juridique_confirmee": False,
        },
        "date_paie": date_paie,
        "contexte": {
            "juridiction": "QC",
            "resident": resident,
            "paiement_regulier_fixe": paiement_regulier_fixe,
            "gratif_ou_retroactif": gratif_ou_retroactif,
            "remuneration_variable": remuneration_variable,
            "exonere": exonere,
            "transfert_province": transfert_province,
        },
        "parametres": {"annee_documentaire": 2026, "frequence": "bihebdomadaire", "P": 26},
        "periode_annuelle": periode_annuelle,
        "periodes_restantes": int(PR),
        "decisions_formule": {
            "J_apres_periode_1": J_determined_after_period_1,
            "J1_apres_periode_1": J1_determined_after_period_1,
            "K1_apres_periode_1": K1_determined_after_period_1,
        },
        "assiettes_fournies": {champ: f"{montants[champ]:.2f}" for champ in _MONTANTS},
        "intermediaires": {
            "H": f"{H_sortie:.2f}",
            "E_arrondi": f"{E:.0f}",
            "I": f"{I_sortie:.2f}",
            "Y": f"{Y_sortie:.2f}",
            "PR": int(PR),
        },
        "J_applique": f"{J_sortie:.2f}",
        "J1_applique": f"{J1_sortie:.2f}",
        "K1_applique": f"{K1_sortie:.2f}",
        "revenu_imposable_annuel": f"{I_sortie:.2f}",
        "impot_annuel_intermediaire": f"{Y_sortie:.2f}",
        "tranche": {"taux": f"{T}", "constante": f"{K_constante:.2f}"},
        "avertissements": [
            "Capture de formule historique; source et applicabilité 2026 non qualifiées pour la paie.",
            "CSA est fournie explicitement; RRQ et ses assiettes ne sont pas calculés ici.",
            "La politique de retenue au centime est un choix d’implémentation, pas une règle générale "
            "affirmée par la source.",
            "Aucune comparaison ou équivalence avec les tables TP-1015.TI n’est affirmée.",
        ],
    }, None
