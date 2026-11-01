"""Façade du moteur de calcul M5 (tranche 1, `docs/moteur-calcul.md`) : entrées brutes → refus typé ou reçu.

Les agents ne calculent jamais « de tête » (SOUL.md) : ils appellent ces moteurs, qui VALIDENT chaque entrée (refus
typé de `verdicts_calcul.py` : rien n'est deviné, aucun défaut n'est inventé), NORMALISENT (textes décimaux
canoniques), calculent avec `maths_financieres.py`, `monte_carlo_tresorerie.py` ou `sensibilite.py`, et rendent un
REÇU (`recu_calcul.py`) rejouable à l'identique par `rejouer`.

Chaque moteur public a la forme `moteur(entrees, parametres) -> (sortie, None) | (None, verdict)`, où `sortie` porte
`recu` (et, pour l'amortissement, le `tableau` complet que le reçu couvre par `empreinte_tableau`). Rejouer un reçu,
c'est rappeler le même moteur avec ses `entrees` et les paramètres d'appel qu'il porte, et comparer les empreintes.

GARDE NC 31-103 : M5 n'est pas un conseiller inscrit. Les calculs d'investissement portent sur un `objet` de la liste
fermée des décisions d'EXPLOITATION de l'entreprise (équipement, véhicule, embauche...) ; un placement en valeurs
mobilières (actions, obligations, fonds, FNB, cryptoactifs, portefeuille) est refusé (`REJ-CALC-OBJET-HORS-PERIMETRE`)
et chaque reçu dit qu'il s'agit d'information générale sur les hypothèses fournies, jamais d'un conseil personnalisé.

Module pur : aucune horloge, aucun registre, aucune écriture (garde anti-décaissement en mode strict).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal, InvalidOperation, localcontext
from typing import Any

from . import encodage, recu_calcul, sensibilite, verdicts_calcul
from . import maths_financieres as mf
from . import monte_carlo_tresorerie as mc

__all__ = [
    "AVERTISSEMENT_FISCAL", "AVERTISSEMENT_NC_31_103", "MOTEURS", "OBJETS_ADMIS", "analyser_sensibilite",
    "calculer_amortissement", "calculer_echelonnement_termes", "calculer_point_mort", "calculer_remboursement_anticipe",
    "calculer_rentabilite", "comparer_credit_bail_achat", "rejouer", "simuler_tresorerie",
]

VERSION = "1.0.0"
# Liste fermée choisie par l'appelant : tout autre objet est refusé (garde NC 31-103), jamais classé « autre ».
OBJETS_ADMIS = frozenset({
    "equipement", "vehicule", "outillage", "immeuble_exploitation", "embauche", "projet_interne", "pret_entreprise",
    "credit_bail_entreprise",
})
AVERTISSEMENT_NC_31_103 = (
    "Information générale calculée sur les hypothèses fournies par l'appelant : ni conseil en placement personnalisé, "
    "ni recommandation d'achat de titres (NC 31-103) ; aucun placement en valeurs mobilières n'est calculé."
)
AVERTISSEMENT_FISCAL = (
    "Aucun effet fiscal (DPA, TPS/TVQ, déductibilité, crédits d'impôt) n'est modélisé : à valider avec le CPA."
)
PRECISION = {
    "chiffres_significatifs": mf.PRECISION,
    "arrondi_interne": "ROUND_HALF_EVEN",
    "arrondi_monetaire": "ROUND_HALF_UP au cent, seulement où la méthode le dit",
}
FLUX_MAX = 600
MONTANT_MAX = Decimal("999999999999.99")
TAUX_MAX = Decimal(1)
ANNEES_MAX = 40
MOIS_MAX = 120
DUREE_PROJET_MAX = 50
VARIATIONS_MAX = len(sensibilite.HYPOTHESES)
SCENARIOS_MAX = 8
MASSE_TRONCATURE_MIN = Decimal("1e-6")
FACTEUR_MAX = Decimal(10)
ECART_TYPE_MAX = Decimal(5)
_QUANTUM_TAUX = Decimal("1e-12")
_QUANTUM_POURCENT = Decimal("0.0001")
_RE_DECIMAL = re.compile(r"^-?[0-9]{1,15}(\.[0-9]{1,15})?$")
_RE_NOM_SCENARIO = re.compile(r"^[a-z0-9_-]{1,40}$")
_RE_IDENTIFIANT_FLUX = re.compile(r"^[^\s]{1,160}$")


def _refus(code: str, detail: str) -> tuple[None, dict[str, str]]:
    return None, verdicts_calcul.construire_verdict(code, detail)


# ------------------------------------------------------------------------------------------ lecture d'entrées
def _decimal(brut: Any) -> Decimal | None:
    if type(brut) is not str or _RE_DECIMAL.fullmatch(brut) is None:
        return None
    try:
        return Decimal(brut)
    except InvalidOperation:
        return None


def _montant(brut: Any, nom: str, *, minimum: Decimal = -MONTANT_MAX, strictement_positif: bool = False):
    """Un montant en texte décimal au cent au plus (« 1250.00 », « -300 »), dans [minimum, MONTANT_MAX]."""
    valeur = _decimal(brut)
    if (valeur is None or valeur.as_tuple().exponent < -2 or not minimum <= valeur <= MONTANT_MAX
            or (strictement_positif and valeur <= 0)):
        borne = "> 0" if strictement_positif else f"≥ {minimum}"
        return _refus("REJ-CALC-MONTANT-INVALIDE",
                      f"{nom} : texte décimal au cent au plus, {borne} et ≤ {MONTANT_MAX} (reçu {brut!r})")
    # Forme canonique (exposant −2) : « 100 », « 100.0 » et « 100.00 » donnent le même calcul, le même reçu.
    return valeur.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), None


def _taux(brut: Any, nom: str, *, minimum: Decimal = Decimal(0), maximum: Decimal = TAUX_MAX):
    """Un taux en fraction (« 0.05 » = 5 %), au plus 12 décimales, dans [minimum, maximum]."""
    valeur = _decimal(brut)
    if valeur is None or valeur.as_tuple().exponent < -12 or not minimum <= valeur <= maximum:
        return _refus("REJ-CALC-TAUX-HORS-BORNES",
                      f"{nom} : fraction décimale (0.05 = 5 %) de {minimum} à {maximum}, 12 décimales au plus "
                      f"(reçu {brut!r})")
    return Decimal(_txt_norme(valeur)), None


def _entier(brut: Any, nom: str, code: str, minimum: int, maximum: int):
    if type(brut) is not int or not minimum <= brut <= maximum:
        return _refus(code, f"{nom} : entier de {minimum} à {maximum} (reçu {brut!r})")
    return brut, None


def _objet(brut: Any):
    if type(brut) is not str or brut not in OBJETS_ADMIS:
        return _refus("REJ-CALC-OBJET-HORS-PERIMETRE", (
            f"objet {brut!r} hors de la liste des décisions d'exploitation {sorted(OBJETS_ADMIS)} : M5 ne calcule ni "
            "ne compare un placement en valeurs mobilières (actions, obligations, fonds, FNB, cryptoactifs, "
            "portefeuille). NC 31-103 : information générale seulement ; s'adresser à un représentant inscrit."))
    return brut, None


def _cles(entrees: Any, permises: set[str], requises: set[str], code: str = "REJ-CALC-FLUX-INVALIDES"):
    if not isinstance(entrees, Mapping):
        return _refus(code, "entrées : objet attendu")
    if set(entrees) - permises or requises - set(entrees):
        return _refus(code, f"clés requises {sorted(requises)}, permises {sorted(permises)}")
    return dict(entrees), None


# ------------------------------------------------------------------------------------------- textes de sortie
def _txt_cent(valeur: Decimal) -> str:
    return format(mf.au_cent(valeur), "f")


def _txt_taux(valeur: Decimal) -> str:
    with localcontext(mf.CONTEXTE):
        return format(valeur.quantize(_QUANTUM_TAUX, rounding=ROUND_HALF_EVEN), "f")


def _txt_pourcent(valeur: Decimal) -> str:
    with localcontext(mf.CONTEXTE):
        return format((valeur * 100).quantize(_QUANTUM_POURCENT, rounding=ROUND_HALF_UP), "f")


def _txt_norme(valeur: Decimal) -> str:
    """Texte canonique d'une entrée décimale : « 0.0500 » → « 0.05 », « 100 » → « 100 »."""
    texte = format(valeur.normalize(), "f")
    return "0" if texte in ("-0", "0") else texte


def _vue_delai(delai: Mapping[str, Any]) -> dict[str, Any]:
    return {"statut": delai["statut"],
            "periodes": None if delai["periodes"] is None else format(delai["periodes"], "f"),
            "redevient_negatif": delai["redevient_negatif"]}


def _vue_tri(resultat: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "statut": resultat["statut"],
        "valeur": None if resultat["tri"] is None else format(resultat["tri"], "f"),
        "pourcentage": None if resultat["tri"] is None else _txt_pourcent(resultat["tri"]),
        "racines": [format(r, "f") for r in resultat["racines"]],
        "changements_de_signe": resultat["changements_de_signe"],
        "van_au_tri": resultat["van_au_tri"],
        "tolerance_van": resultat["tolerance_van"],
        "iterations": resultat["iterations"],
    }


def _avertissements_tri(statut: str) -> list[str]:
    textes = {
        "AUCUN_CHANGEMENT_DE_SIGNE": "Aucun TRI : les flux ne changent jamais de signe.",
        "HORS_BORNES": (f"TRI non rendu : la racine est hors de [{mf.TAUX_MIN_TRI}, {mf.TAUX_MAX_TRI}] par période."),
        "MULTIPLE": "TRI non rendu : plusieurs racines (flux non conventionnels) ; lire la VAN ou le TRI modifié.",
        "NON_GARANTI": ("TRI non rendu : plusieurs changements de signe, une seule racine trouvée sans preuve "
                        "d'unicité ; lire la VAN ou le TRI modifié."),
        "INDEFINI": ("TRI non rendu : plusieurs changements de signe et aucune racine trouvée (une racine double "
                     "peut exister) ; lire la VAN ou le TRI modifié."),
    }
    return [textes[statut]] if statut in textes else []


def _recu(moteur: str, methode: str, parametres: Mapping[str, Any], entrees: Mapping[str, Any],
          resultat: Mapping[str, Any], avertissements: list[str]) -> dict[str, Any]:
    return recu_calcul.construire(
        moteur=moteur, version_moteur=VERSION, methode=methode, precision=PRECISION, parametres=parametres,
        entrees=entrees, resultat=resultat, avertissements=avertissements)


# ---------------------------------------------------------------------------- 1. rentabilité d'un investissement
_METHODE_RENTABILITE = (
    "VAN = Σ c_t/(1+r)^t (c_0 au temps 0, flux en fin de période) ; TRI : racine de VAN(r)=0 sur "
    f"[{mf.TAUX_MIN_TRI}, {mf.TAUX_MAX_TRI}] par bissection protégée + Newton, unicité prouvée seulement pour un "
    "changement de signe (Descartes), sinon balayage d'une grille et aucun TRI rendu ; TRI modifié = "
    "(VF des flux positifs au taux de réinvestissement / VA des flux négatifs au taux de financement)^(1/n) − 1 ; "
    "délais de récupération simple et actualisé, interpolés linéairement dans la période."
)


def calculer_rentabilite(entrees: Any, parametres: Any = None):
    """VAN, TRI, TRI modifié et délais de récupération d'une suite de flux par période."""
    brut, verdict = _cles(entrees, {"objet", "flux", "taux_actualisation", "taux_financement",
                                    "taux_reinvestissement"}, {"objet", "flux", "taux_actualisation"})
    if verdict:
        return None, verdict
    objet, verdict = _objet(brut["objet"])
    if verdict:
        return None, verdict
    flux_bruts = brut["flux"]
    if not isinstance(flux_bruts, list) or len(flux_bruts) < 2:
        return _refus("REJ-CALC-FLUX-VIDES", "flux : liste d'au moins deux montants (c_0 au temps 0, puis c_1...)")
    if len(flux_bruts) > FLUX_MAX:
        return _refus("REJ-CALC-BORNE-DEPASSEE", f"flux : {FLUX_MAX} périodes au plus (reçu {len(flux_bruts)})")
    flux = []
    for index, valeur in enumerate(flux_bruts):
        montant, verdict = _montant(valeur, f"flux[{index}]")
        if verdict:
            return None, verdict
        flux.append(montant)
    if all(c == 0 for c in flux):
        return _refus("REJ-CALC-FLUX-INVALIDES", "flux tous nuls : aucune rentabilité à calculer")
    taux, verdict = _taux(brut["taux_actualisation"], "taux_actualisation")
    if verdict:
        return None, verdict
    financement = reinvestissement = None
    if brut.get("taux_financement") is not None or brut.get("taux_reinvestissement") is not None:
        financement, verdict = _taux(brut.get("taux_financement"), "taux_financement")
        if verdict:
            return None, verdict
        reinvestissement, verdict = _taux(brut.get("taux_reinvestissement"), "taux_reinvestissement")
        if verdict:
            return None, verdict
    try:
        resultat_tri = mf.tri(flux)
        trim = None if financement is None else mf.tri_modifie(flux, financement, reinvestissement)
        simple, actualise = mf.delai_recuperation(flux), mf.delai_recuperation(flux, taux)
        van_au_cent = _txt_cent(mf.van(taux, flux))
    except ArithmeticError as exc:
        return _refus("REJ-CALC-RESULTAT-HORS-PRECISION", f"rentabilité non calculable avec ces montants : {exc}")
    resultat = {
        "van": van_au_cent,
        "tri": _vue_tri(resultat_tri),
        "tri_modifie": {
            "statut": "NON_DEMANDE" if financement is None else ("INDEFINI" if trim is None else "CALCULE"),
            "valeur": None if trim is None else _txt_taux(trim),
            "pourcentage": None if trim is None else _txt_pourcent(trim),
        },
        "delai_recuperation_simple": _vue_delai(simple),
        "delai_recuperation_actualise": _vue_delai(actualise),
    }
    avertissements = [AVERTISSEMENT_NC_31_103, AVERTISSEMENT_FISCAL, *_avertissements_tri(resultat_tri["statut"])]
    if simple["redevient_negatif"] or actualise["redevient_negatif"]:
        avertissements.append("Le cumul des flux redevient négatif après la récupération : délai à lire avec prudence.")
    normalisees = {
        "objet": objet, "flux": [format(c, ".2f") for c in flux], "taux_actualisation": _txt_norme(taux),
        "taux_financement": None if financement is None else _txt_norme(financement),
        "taux_reinvestissement": None if reinvestissement is None else _txt_norme(reinvestissement),
    }
    parametres_recu = {"taux_min_tri": str(mf.TAUX_MIN_TRI), "taux_max_tri": str(mf.TAUX_MAX_TRI),
                       "tolerance_tri": format(mf.TOLERANCE_TRI, "E"),
                       "tolerance_van_relative": format(mf.TOLERANCE_VAN_RELATIVE, "E"),
                       "iterations_max": mf.ITERATIONS_MAX}
    return {"recu": _recu("rentabilite_investissement", _METHODE_RENTABILITE, parametres_recu, normalisees, resultat,
                          avertissements)}, None


# --------------------------------------------------------------------------------- 2. amortissement d'un prêt
_METHODE_AMORTISSEMENT = (
    "Taux par versement i : nominal_compose_a_la_frequence j/m ; canadienne_semestrielle (1+j/2)^(2/m) − 1 ; "
    "effectif_annuel (1+j)^(1/m) − 1. Versement constant P·i/(1 − (1+i)^−n) arrondi au cent (ROUND_HALF_UP) ; "
    "intérêt de chaque période arrondi au cent ; dernière échéance ajustée : Σ capital = principal au cent."
)


def calculer_amortissement(entrees: Any, parametres: Any = None):
    """Tableau d'amortissement complet d'un prêt à versement constant (`sortie["tableau"]`, en textes)."""
    cles = {"objet", "montant_emprunte", "taux_annuel", "frequence", "convention", "amortissement_annees"}
    brut, verdict = _cles(entrees, cles, cles)
    if verdict:
        return None, verdict
    objet, verdict = _objet(brut["objet"])
    if verdict:
        return None, verdict
    principal, verdict = _montant(brut["montant_emprunte"], "montant_emprunte", strictement_positif=True)
    if verdict:
        return None, verdict
    taux_annuel, verdict = _taux(brut["taux_annuel"], "taux_annuel")
    if verdict:
        return None, verdict
    if type(brut["frequence"]) is not str or brut["frequence"] not in mf.FREQUENCES:
        return _refus("REJ-CALC-FREQUENCE-INCONNUE",
                      f"frequence {brut['frequence']!r} : une de {sorted(mf.FREQUENCES)}")
    if type(brut["convention"]) is not str or brut["convention"] not in mf.CONVENTIONS_TAUX:
        return _refus("REJ-CALC-CONVENTION-INCONNUE",
                      f"convention {brut['convention']!r} : une de {sorted(mf.CONVENTIONS_TAUX)}")
    annees, verdict = _entier(brut["amortissement_annees"], "amortissement_annees", "REJ-CALC-DUREE-INVALIDE",
                              1, ANNEES_MAX)
    if verdict:
        return None, verdict
    n = annees * mf.FREQUENCES[brut["frequence"]]
    i = mf.taux_periodique(taux_annuel, brut["frequence"], brut["convention"])
    try:
        tableau = mf.amortir(principal, i, n)
    except ArithmeticError as exc:
        return _refus("REJ-CALC-AMORTISSEMENT-IMPOSSIBLE", str(exc))
    lignes = [{"periode": ligne["periode"], **{cle: format(ligne[cle], "f") for cle in
                                                ("versement", "interet", "capital", "solde")}}
              for ligne in tableau["lignes"]]
    resultat = {
        "taux_periodique": format(i.quantize(Decimal("1e-20"), rounding=ROUND_HALF_EVEN), "f"),
        "nombre_versements_prevu": n,
        "versement": format(tableau["versement"], "f"),
        "nombre_versements": tableau["nombre_versements"],
        "dernier_versement": format(tableau["dernier_versement"], "f"),
        "ajustement_dernier_versement": format(tableau["ajustement_dernier_versement"], "f"),
        "total_versements": format(tableau["total_versements"], "f"),
        "total_interets": format(tableau["total_interets"], "f"),
        "total_capital": format(tableau["total_capital"], "f"),
        "empreinte_tableau": encodage.empreinte("tableau_amortissement", lignes),
    }
    avertissements = [AVERTISSEMENT_NC_31_103, AVERTISSEMENT_FISCAL,
                      "Les versements sont numérotés par période : aucune date n'est supposée (jours fériés, "
                      "date du premier versement et frais du prêteur à lire sur l'offre)."]
    if tableau["nombre_versements"] < n:
        avertissements.append(f"L'arrondi du versement solde le prêt en {tableau['nombre_versements']} versements "
                              f"au lieu de {n}.")
    normalisees = {"objet": objet, "montant_emprunte": format(principal, ".2f"), "taux_annuel": _txt_norme(taux_annuel),
                   "frequence": brut["frequence"], "convention": brut["convention"], "amortissement_annees": annees}
    recu = _recu("amortissement_pret", _METHODE_AMORTISSEMENT, {"versements_par_an": dict(mf.FREQUENCES)}, normalisees,
                 resultat, avertissements)
    return {"recu": recu, "tableau": lignes}, None


# --------------------------------------------------------------------------------- 3. crédit-bail ou achat
_METHODE_CREDIT_BAIL = (
    "Valeur actuelle des coûts sur `mois` mois, taux mensuel i = (1 + r annuel effectif)^(1/12) − 1 : achat comptant = "
    "prix + frais − valeur résiduelle/(1+i)^mois ; crédit-bail = dépôt + Σ paiements actualisés (début de période : "
    "t = 0..mois−1 ; fin : t = 1..mois) + (option d'achat − valeur résiduelle)/(1+i)^mois si l'option est exercée."
)


def comparer_credit_bail_achat(entrees: Any, parametres: Any = None):
    """Compare en valeur actuelle le coût d'un achat comptant et d'un crédit-bail, hypothèses explicites."""
    cles = {"objet", "taux_actualisation_annuel", "mois", "prix_achat", "frais_achat", "valeur_residuelle",
            "paiement_mensuel", "depot_initial", "paiements_en_debut_de_periode", "option_achat_finale"}
    brut, verdict = _cles(entrees, cles, cles - {"option_achat_finale"})
    if verdict:
        return None, verdict
    objet, verdict = _objet(brut["objet"])
    if verdict:
        return None, verdict
    taux, verdict = _taux(brut["taux_actualisation_annuel"], "taux_actualisation_annuel")
    if verdict:
        return None, verdict
    mois, verdict = _entier(brut["mois"], "mois", "REJ-CALC-DUREE-INVALIDE", 1, MOIS_MAX)
    if verdict:
        return None, verdict
    montants = {}
    for nom in ("prix_achat", "frais_achat", "valeur_residuelle", "paiement_mensuel", "depot_initial"):
        montants[nom], verdict = _montant(brut[nom], nom, minimum=Decimal(0), strictement_positif=nom == "prix_achat")
        if verdict:
            return None, verdict
    option = None
    if brut.get("option_achat_finale") is not None:
        option, verdict = _montant(brut["option_achat_finale"], "option_achat_finale", minimum=Decimal(0))
        if verdict:
            return None, verdict
    if type(brut["paiements_en_debut_de_periode"]) is not bool:
        return _refus("REJ-CALC-FLUX-INVALIDES", "paiements_en_debut_de_periode : vrai ou faux, jamais supposé")
    taux_mensuel = mf.taux_periodique(taux, "mensuelle", "effectif_annuel")
    calcul = mf.comparer_credit_bail_achat(
        taux_mensuel=taux_mensuel, mois=mois, option_achat_finale=option,
        paiements_en_debut_de_periode=brut["paiements_en_debut_de_periode"], **montants)
    achat, bail = mf.au_cent(calcul["va_cout_achat"]), mf.au_cent(calcul["va_cout_credit_bail"])
    resultat = {
        "taux_mensuel": _txt_taux(taux_mensuel),
        "va_cout_achat": format(achat, "f"),
        "va_cout_credit_bail": format(bail, "f"),
        "va_paiements_credit_bail": _txt_cent(calcul["va_paiements_credit_bail"]),
        "va_option_nette": _txt_cent(calcul["va_option_nette"]),
        "ecart_credit_bail_moins_achat": format(bail - achat, "f"),
        "option_au_cout_actualise_le_plus_bas": "egalite" if achat == bail else (
            "achat" if achat < bail else "credit_bail"),
    }
    avertissements = [
        AVERTISSEMENT_NC_31_103, AVERTISSEMENT_FISCAL,
        "Comparaison des seuls coûts actualisés sous les hypothèses fournies : ce n'est pas une recommandation ; "
        "entretien, assurance, kilométrage excédentaire et frais de fin de bail ne sont comptés que s'ils sont saisis.",
        "Achat comptant : le coût de renonciation est le taux d'actualisation fourni ; un achat financé se compare "
        "avec m5_calculer_amortissement_pret.",
    ]
    if option is None:
        avertissements.append("Option d'achat non exercée : l'actif est rendu au bailleur à la fin du terme.")
    normalisees = {"objet": objet, "taux_actualisation_annuel": _txt_norme(taux), "mois": mois,
                   **{nom: format(valeur, ".2f") for nom, valeur in montants.items()},
                   "paiements_en_debut_de_periode": brut["paiements_en_debut_de_periode"],
                   "option_achat_finale": None if option is None else format(option, ".2f")}
    return {"recu": _recu("credit_bail_contre_achat", _METHODE_CREDIT_BAIL, {}, normalisees, resultat,
                          avertissements)}, None


# ------------------------------------------------------------------------------------------------ 4. point mort
_METHODE_POINT_MORT = (
    "q* = frais fixes / (prix unitaire − coût variable unitaire) ; quantité entière = ⌈q*⌉ ; chiffre d'affaires du "
    "point mort = q* × prix unitaire (au cent) ; marge de sécurité = (quantité prévue − q*) / quantité prévue."
)


def calculer_point_mort(entrees: Any, parametres: Any = None):
    """Point mort en unités et en chiffre d'affaires (unités : chantiers, pieds linéaires... au choix de l'appelant)."""
    cles = {"frais_fixes", "prix_unitaire", "cout_variable_unitaire", "quantite_prevue"}
    brut, verdict = _cles(entrees, cles, cles - {"quantite_prevue"})
    if verdict:
        return None, verdict
    frais, verdict = _montant(brut["frais_fixes"], "frais_fixes", minimum=Decimal(0))
    if verdict:
        return None, verdict
    prix, verdict = _montant(brut["prix_unitaire"], "prix_unitaire", strictement_positif=True)
    if verdict:
        return None, verdict
    cout, verdict = _montant(brut["cout_variable_unitaire"], "cout_variable_unitaire", minimum=Decimal(0))
    if verdict:
        return None, verdict
    prevue = None
    if brut.get("quantite_prevue") is not None:
        prevue, verdict = _montant(brut["quantite_prevue"], "quantite_prevue", strictement_positif=True)
        if verdict:
            return None, verdict
    try:
        calcul = mf.point_mort(frais, prix, cout)
    except ArithmeticError:
        return _refus("REJ-CALC-MARGE-NON-POSITIVE",
                      "prix_unitaire ≤ cout_variable_unitaire : chaque unité perd de l'argent, aucun point mort")
    with localcontext(mf.CONTEXTE):
        resultat = {
            "marge_unitaire": format(calcul["marge_unitaire"], "f"),
            "taux_de_marge_pourcentage": _txt_pourcent(calcul["taux_de_marge"]),
            "quantite_exacte": format(calcul["quantite_exacte"].quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
                                      "f"),
            "quantite_entiere": format(calcul["quantite_entiere"], "f"),
            "chiffre_affaires_point_mort": _txt_cent(calcul["chiffre_affaires_exact"]),
            "chiffre_affaires_quantite_entiere": _txt_cent(calcul["chiffre_affaires_quantite_entiere"]),
            "marge_de_securite_pourcentage": None if prevue is None else _txt_pourcent(
                (prevue - calcul["quantite_exacte"]) / prevue),
        }
    normalisees = {"frais_fixes": format(frais, ".2f"), "prix_unitaire": format(prix, ".2f"),
                   "cout_variable_unitaire": format(cout, ".2f"),
                   "quantite_prevue": None if prevue is None else _txt_norme(prevue)}
    avertissements = [AVERTISSEMENT_FISCAL, "Modèle linéaire : prix et coût variable constants par unité, frais fixes "
                      "constants sur la période ; aucune capacité maximale ni saison n'est modélisée."]
    return {"recu": _recu("point_mort", _METHODE_POINT_MORT, {}, normalisees, resultat, avertissements)}, None


# --------------------------------------------------------------------------- 5. Monte-Carlo de la trésorerie
_METHODE_MONTE_CARLO = (
    "Flux connus et datés de la prévision M5.7, perturbés nature par nature : facteur de montant par inversion de la "
    "répartition (triangulaire fermée ; normale tronquée AS241 en Decimal, troncature par erf), arrondi au cent ; "
    "retard Bernoulli (encaissements seulement), hors horizon = non compté ; uniformes u = (2k+1)/2^54, "
    "k = getrandbits(53) de random.Random(graine) ; percentiles au rang le plus proche ⌈p·N⌉, sans interpolation."
)


def _loi(brut: Any, nature: str):
    detail = f"distributions.{nature}.montant"
    if not isinstance(brut, Mapping) or brut.get("loi") not in ("triangulaire", "normale_tronquee"):
        return _refus("REJ-CALC-DISTRIBUTION-INVALIDE", f"{detail} : loi triangulaire ou normale_tronquee")
    cles = {"loi", "min", "mode", "max"} if brut["loi"] == "triangulaire" else {
        "loi", "moyenne", "ecart_type", "min", "max"}
    if set(brut) != cles:
        return _refus("REJ-CALC-DISTRIBUTION-INVALIDE", f"{detail} : clés exactes {sorted(cles)}")
    valeurs = {}
    for cle in sorted(cles - {"loi"}):
        valeur = _decimal(brut[cle])
        if valeur is None or valeur.as_tuple().exponent < -12 or not 0 <= valeur <= FACTEUR_MAX:
            return _refus("REJ-CALC-DISTRIBUTION-INVALIDE",
                          f"{detail}.{cle} : facteur décimal de 0 à {FACTEUR_MAX}, 12 décimales au plus")
        valeurs[cle] = Decimal(_txt_norme(valeur))
    if valeurs["min"] >= valeurs["max"]:
        return _refus("REJ-CALC-DISTRIBUTION-INVALIDE", f"{detail} : min < max exigé")
    loi = {"loi": brut["loi"], **valeurs}
    if brut["loi"] == "triangulaire":
        if not valeurs["min"] <= valeurs["mode"] <= valeurs["max"]:
            return _refus("REJ-CALC-DISTRIBUTION-INVALIDE", f"{detail} : min ≤ mode ≤ max exigé")
    else:
        if not 0 < valeurs["ecart_type"] <= ECART_TYPE_MAX:
            return _refus("REJ-CALC-DISTRIBUTION-INVALIDE", f"{detail}.ecart_type : de 0 (exclu) à {ECART_TYPE_MAX}")
        if mc.masse_troncature(loi) < MASSE_TRONCATURE_MIN:
            return _refus("REJ-CALC-DISTRIBUTION-INVALIDE",
                          f"{detail} : la troncature [min, max] garde moins de {MASSE_TRONCATURE_MIN} de la loi")
    return loi, None


def _distributions(brut: Any):
    if not isinstance(brut, Mapping) or not brut:
        return _refus("REJ-CALC-DISTRIBUTION-INVALIDE",
                      "distributions : au moins une nature de flux, chacune déclarée (aucune loi par défaut)")
    natures = set(mc.NATURES_ENTREE) | set(mc.NATURES_SORTIE)
    resultat: dict[str, dict[str, Any]] = {}
    for nature in sorted(brut):
        spec = brut[nature]
        if nature not in natures:
            return _refus("REJ-CALC-DISTRIBUTION-INVALIDE", f"nature {nature!r} : une de {sorted(natures)}")
        if not isinstance(spec, Mapping) or set(spec) - {"montant", "retard"} or not spec:
            return _refus("REJ-CALC-DISTRIBUTION-INVALIDE", f"distributions.{nature} : clés montant et/ou retard")
        loi = retard = None
        if spec.get("montant") is not None:
            loi, verdict = _loi(spec["montant"], nature)
            if verdict:
                return None, verdict
        if spec.get("retard") is not None:
            if nature not in mc.NATURES_ENTREE:
                return _refus("REJ-CALC-DISTRIBUTION-INVALIDE",
                              f"distributions.{nature}.retard : un retard ne s'applique qu'aux encaissements "
                              "(retarder un décaissement serait optimiste)")
            r = spec["retard"]
            probabilite = _decimal(r.get("probabilite")) if isinstance(r, Mapping) else None
            if (not isinstance(r, Mapping) or set(r) != {"probabilite", "semaines"} or probabilite is None
                    or not 0 <= probabilite <= 1 or probabilite.as_tuple().exponent < -12
                    or type(r["semaines"]) is not int or not 1 <= r["semaines"] <= mc.SEMAINES_MAX):
                return _refus("REJ-CALC-DISTRIBUTION-INVALIDE",
                              f"distributions.{nature}.retard : probabilite de 0 à 1 et semaines entières de 1 à "
                              f"{mc.SEMAINES_MAX}")
            retard = {"probabilite": Decimal(_txt_norme(probabilite)), "semaines": r["semaines"]}
        if loi is None and retard is None:
            return _refus("REJ-CALC-DISTRIBUTION-INVALIDE", f"distributions.{nature} : montant ou retard non nul")
        resultat[nature] = {"montant": loi, "retard": retard}
    return resultat, None


def _texte_loi(loi: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if loi is None:
        return None
    return {cle: (valeur if cle == "loi" else _txt_norme(valeur)) for cle, valeur in loi.items()}


def simuler_tresorerie(entrees: Any, parametres: Any):
    """Monte-Carlo à graine. `entrees` : {solde_initial, flux [{id, sens, nature, semaine, montant}], seuil,
    prevision_id} (lus de la prévision existante par l'adaptateur) ; `parametres` : {graine, tirages, semaines,
    distributions}, tous déclarés par l'appelant."""
    params, verdict = _cles(parametres, {"graine", "tirages", "semaines", "distributions"},
                            {"graine", "tirages", "semaines", "distributions"}, "REJ-CALC-DISTRIBUTION-INVALIDE")
    if verdict:
        return None, verdict
    graine = params["graine"]
    if type(graine) is not int or not 0 <= graine <= mc.GRAINE_MAX:
        return _refus("REJ-CALC-GRAINE-INVALIDE",
                      f"graine : entier de 0 à {mc.GRAINE_MAX}, déclarée (jamais l'horloge)")
    tirages, verdict = _entier(params["tirages"], "tirages", "REJ-CALC-BORNE-DEPASSEE", 1, mc.TIRAGES_MAX)
    if verdict:
        return None, verdict
    semaines, verdict = _entier(params["semaines"], "semaines", "REJ-CALC-DUREE-INVALIDE", 1, mc.SEMAINES_MAX)
    if verdict:
        return None, verdict
    distributions, verdict = _distributions(params["distributions"])
    if verdict:
        return None, verdict
    brut, verdict = _cles(entrees, {"solde_initial", "flux", "seuil", "prevision_id"},
                          {"solde_initial", "flux", "seuil", "prevision_id"})
    if verdict:
        return None, verdict
    solde, verdict = _montant(brut["solde_initial"], "solde_initial")
    if verdict:
        return None, verdict
    seuil = None
    if brut["seuil"] is not None:
        seuil, verdict = _montant(brut["seuil"], "seuil")
        if verdict:
            return None, verdict
    if type(brut["prevision_id"]) is not str or not 1 <= len(brut["prevision_id"]) <= 128:
        return _refus("REJ-CALC-FLUX-INVALIDES", "prevision_id : l'empreinte de la prévision d'origine")
    if not isinstance(brut["flux"], list):
        return _refus("REJ-CALC-FLUX-INVALIDES", "flux : liste")
    if len(brut["flux"]) > mc.FLUX_MAX:
        return _refus("REJ-CALC-BORNE-DEPASSEE", f"flux : {mc.FLUX_MAX} au plus (reçu {len(brut['flux'])})")
    flux = []
    natures = set(mc.NATURES_ENTREE) | set(mc.NATURES_SORTIE)
    for index, f in enumerate(brut["flux"]):
        if (not isinstance(f, Mapping) or set(f) != {"id", "sens", "nature", "semaine", "montant"}
                or type(f["id"]) is not str or _RE_IDENTIFIANT_FLUX.fullmatch(f["id"]) is None
                or type(f["nature"]) is not str or f["nature"] not in natures
                or f["sens"] != ("ENTREE" if f["nature"] in mc.NATURES_ENTREE else "SORTIE")
                or type(f["semaine"]) is not int or not 1 <= f["semaine"] <= semaines):
            return _refus("REJ-CALC-FLUX-INVALIDES", f"flux[{index}] : id, sens cohérent avec la nature, nature "
                          f"connue, semaine de 1 à {semaines}, montant")
        montant, verdict = _montant(f["montant"], f"flux[{index}].montant", minimum=Decimal(0))
        if verdict:
            return None, verdict
        flux.append({**f, "montant": montant})
    if len({f["id"] for f in flux}) != len(flux):
        return _refus("REJ-CALC-FLUX-INVALIDES", "deux flux portent le même identifiant")
    perturbes = sum(1 for f in flux if f["nature"] in distributions)
    if tirages * max(perturbes, 1) > mc.BUDGET_TIRAGES_X_FLUX:
        return _refus("REJ-CALC-BORNE-DEPASSEE", (
            f"tirages × flux perturbés = {tirages} × {perturbes} dépasse {mc.BUDGET_TIRAGES_X_FLUX} : réduire les "
            "tirages ou l'horizon"))
    calcul = mc.simuler(solde_initial=solde, flux=flux, semaines=semaines, distributions=distributions,
                        graine=graine, tirages=tirages, seuil=seuil)

    def texte(valeur: Any) -> Any:
        return format(valeur, "f") if isinstance(valeur, Decimal) else valeur

    # En colonnes : 26 semaines tiennent dans une réponse d'outil (6 000 caractères) avec le reçu entier.
    colonnes = list(calcul["semaines"][0])
    resultat = {
        "colonnes": colonnes,
        "semaines": [[texte(ligne[cle]) for cle in colonnes] for ligne in calcul["semaines"]],
        **{cle: ({k: texte(v) for k, v in valeur.items()} if isinstance(valeur, dict) else texte(valeur))
           for cle, valeur in calcul.items() if cle != "semaines"},
        "flux_perturbes": perturbes,
    }
    natures_sans_flux = sorted(set(distributions) - {f["nature"] for f in flux})
    avertissements = [
        "Simulation des seuls flux connus et datés de la prévision : aucune vente, aucun flux nouveau n'est inventé ; "
        "les distributions sont celles déclarées par l'appelant, pas une estimation statistique.",
        "Les tirages sont indépendants d'un flux à l'autre : aucune corrélation (choc commun) n'est modélisée.",
        "Un encaissement non compté par la prévision (échu ou sans date) ne l'est pas non plus ici.",
    ]
    if natures_sans_flux:
        avertissements.append(f"Distributions déclarées sans flux correspondant : {natures_sans_flux}.")
    normalisees = {
        "solde_initial": format(solde, ".2f"), "seuil": None if seuil is None else format(seuil, ".2f"),
        "prevision_id": brut["prevision_id"],
        "flux": [{**f, "montant": format(f["montant"], ".2f")} for f in sorted(flux, key=mc._cle_flux)],
    }
    parametres_recu = {
        "graine": graine, "tirages": tirages, "semaines": semaines,
        "distributions": {nature: {"montant": _texte_loi(spec["montant"]),
                                   "retard": None if spec["retard"] is None else {
                                       "probabilite": _txt_norme(spec["retard"]["probabilite"]),
                                       "semaines": spec["retard"]["semaines"]}}
                          for nature, spec in distributions.items()},
        "generateur": "random.Random (Mersenne Twister), getrandbits(53)",
        "percentiles": "rang le plus proche ⌈p·N⌉",
        "quantum_facteur": "1E-12",
    }
    return {"recu": _recu("monte_carlo_tresorerie", _METHODE_MONTE_CARLO, parametres_recu, normalisees, resultat,
                          avertissements)}, None


# ------------------------------------------------------------------------------- 6. sensibilité et scénarios
_METHODE_SENSIBILITE = (
    "Projet : flux_0 = −investissement ; flux_t = F × (1+g)^(t−1) au cent, t = 1..n, + valeur résiduelle en n ; VAN au "
    "taux d'actualisation, TRI (maths_financieres.tri), délai simple. Tornade : chaque hypothèse seule à sa valeur "
    "basse puis haute, amplitude |VAN(haut) − VAN(bas)|, tri décroissant ; scénarios : jeux nommés de valeurs."
)


def _hypothese(nom: str, valeur: Any):
    if nom == "duree_annees":
        return _entier(valeur, nom, "REJ-CALC-DUREE-INVALIDE", 1, DUREE_PROJET_MAX)
    if nom == "croissance_annuelle":
        return _taux(valeur, nom, minimum=Decimal("-0.5"))
    if nom == "taux_actualisation":
        return _taux(valeur, nom)
    if nom == "flux_annuel":
        return _montant(valeur, nom)
    return _montant(valeur, nom, minimum=Decimal(0))


def _texte_hypothese(valeur: Any) -> Any:
    return valeur if isinstance(valeur, int) else _txt_norme(valeur)


def analyser_sensibilite(entrees: Any, parametres: Any = None):
    """Tornade sur les hypothèses déclarées et scénarios nommés d'un projet d'investissement de l'entreprise."""
    brut, verdict = _cles(entrees, {"objet", "base", "variations", "scenarios"},
                          {"objet", "base", "variations", "scenarios"}, "REJ-CALC-HYPOTHESE-INVALIDE")
    if verdict:
        return None, verdict
    objet, verdict = _objet(brut["objet"])
    if verdict:
        return None, verdict
    if not isinstance(brut["base"], Mapping) or set(brut["base"]) != set(sensibilite.HYPOTHESES):
        return _refus("REJ-CALC-HYPOTHESE-INVALIDE", f"base : exactement {sorted(sensibilite.HYPOTHESES)}")
    base = {}
    for nom in sorted(sensibilite.HYPOTHESES):
        base[nom], verdict = _hypothese(nom, brut["base"][nom])
        if verdict:
            return None, verdict
    variations_brutes, scenarios_bruts = brut["variations"], brut["scenarios"]
    if not isinstance(variations_brutes, Mapping) or not isinstance(scenarios_bruts, list):
        return _refus("REJ-CALC-HYPOTHESE-INVALIDE", "variations : objet ; scenarios : liste")
    if not variations_brutes and not scenarios_bruts:
        return _refus("REJ-CALC-HYPOTHESE-INVALIDE", "au moins une variation ou un scénario")
    if len(scenarios_bruts) > SCENARIOS_MAX:
        return _refus("REJ-CALC-BORNE-DEPASSEE", f"scenarios : {SCENARIOS_MAX} au plus")
    variations = {}
    for nom, bornes in variations_brutes.items():
        if nom not in sensibilite.HYPOTHESES or not isinstance(bornes, Mapping) or set(bornes) != {"bas", "haut"}:
            return _refus("REJ-CALC-HYPOTHESE-INVALIDE",
                          f"variations.{nom} : hypothèse de {sorted(sensibilite.HYPOTHESES)} avec bas et haut")
        bas, verdict = _hypothese(nom, bornes["bas"])
        if verdict:
            return None, verdict
        haut, verdict = _hypothese(nom, bornes["haut"])
        if verdict:
            return None, verdict
        if not bas <= base[nom] <= haut or bas == haut:
            return _refus("REJ-CALC-HYPOTHESE-INVALIDE", f"variations.{nom} : bas ≤ base ≤ haut et bas ≠ haut")
        variations[nom] = {"bas": bas, "haut": haut}
    scenarios = []
    for index, scenario in enumerate(scenarios_bruts):
        if (not isinstance(scenario, Mapping) or set(scenario) != {"nom", "hypotheses"}
                or type(scenario["nom"]) is not str or _RE_NOM_SCENARIO.fullmatch(scenario["nom"]) is None
                or not isinstance(scenario["hypotheses"], Mapping) or not scenario["hypotheses"]):
            return _refus("REJ-CALC-SCENARIO-INVALIDE", f"scenarios[{index}] : nom [a-z0-9_-]{{1,40}} et hypotheses")
        valeurs = {}
        for nom, valeur in scenario["hypotheses"].items():
            if nom not in sensibilite.HYPOTHESES:
                return _refus("REJ-CALC-SCENARIO-INVALIDE", f"scenarios[{index}] : hypothèse inconnue {nom!r}")
            valeurs[nom], verdict = _hypothese(nom, valeur)
            if verdict:
                return None, verdict
        scenarios.append({"nom": scenario["nom"], "hypotheses": valeurs})
    if len({s["nom"] for s in scenarios}) != len(scenarios):
        return _refus("REJ-CALC-SCENARIO-INVALIDE", "deux scénarios portent le même nom")
    try:
        calcul = sensibilite.analyser(base, variations, scenarios)
    except ArithmeticError as exc:
        return _refus("REJ-CALC-RESULTAT-HORS-PRECISION", f"sensibilité non calculable avec ces hypothèses : {exc}")

    def vue_mesure(mesure: Mapping[str, Any]) -> dict[str, Any]:
        return {"van": format(mesure["van"], "f"), "tri_statut": mesure["tri_statut"],
                "tri_pourcentage": None if mesure["tri"] is None else _txt_pourcent(mesure["tri"]),
                "delai_recuperation": _vue_delai(mesure["delai_recuperation"])}

    resultat = {
        "base": vue_mesure(calcul["base"]),
        "tornade": [{"hypothese": b["hypothese"], "valeur_basse": _texte_hypothese(b["valeur_basse"]),
                     "valeur_haute": _texte_hypothese(b["valeur_haute"]), "van_basse": format(b["van_basse"], "f"),
                     "van_haute": format(b["van_haute"], "f"), "amplitude": format(b["amplitude"], "f")}
                    for b in calcul["tornade"]],
        "scenarios": [{"nom": s["nom"], **vue_mesure(s)} for s in calcul["scenarios"]],
    }
    normalisees = {
        "objet": objet,
        "base": {nom: _texte_hypothese(valeur) for nom, valeur in base.items()},
        "variations": {nom: {"bas": _texte_hypothese(v["bas"]), "haut": _texte_hypothese(v["haut"])}
                       for nom, v in sorted(variations.items())},
        "scenarios": [{"nom": s["nom"], "hypotheses": {n: _texte_hypothese(v) for n, v in
                                                        sorted(s["hypotheses"].items())}} for s in scenarios],
    }
    avertissements = [AVERTISSEMENT_NC_31_103, AVERTISSEMENT_FISCAL,
                      "Une hypothèse varie à la fois (tornade) : les interactions entre hypothèses ne se lisent que "
                      "dans les scénarios ; les valeurs basses, hautes et de scénario sont celles de l'appelant."]
    return {"recu": _recu("sensibilite_projet", _METHODE_SENSIBILITE, {"modele": "projet_croissance_constante"},
                          normalisees, resultat, avertissements)}, None


# ------------------------------------------------------------------ 7. remboursement anticipé d'un prêt
_METHODE_ANTICIPE = (
    "Tableau d'amortissement à versement constant (conventions de amortissement_pret) auquel la stratégie ajoute un "
    "versement additionnel par période et/ou des remboursements forfaitaires à des périodes données ; intérêt de "
    "chaque "
    "période = solde × i arrondi au cent ; le dernier paiement solde exactement ; les frais saisis par l'appelant "
    "s'ajoutent au total payé ; économie = intérêts de la stratégie « base » − intérêts de la stratégie."
)
STRATEGIES_MAX = 4
FORFAITS_MAX = 12


def _simuler_pret(principal: Decimal, i: Decimal, n: int, versement: Decimal, extra: Decimal,
                  forfaits: Mapping[int, Decimal]) -> dict[str, Any]:
    with localcontext(mf.CONTEXTE):
        solde, interets, paye, dernier, nombre = principal, Decimal(0), Decimal(0), Decimal(0), 0
        for periode in range(1, n + 1):
            interet = mf.au_cent(solde * i)
            paiement = versement + extra + forfaits.get(periode, Decimal(0))
            if periode == n or paiement >= solde + interet:
                paiement = solde + interet
            solde -= paiement - interet
            interets, paye, dernier, nombre = interets + interet, paye + paiement, paiement, periode
            if solde == 0:
                break
        return {"nombre": nombre, "interets": interets, "paye": paye, "dernier": dernier, "solde_final": solde}


def calculer_remboursement_anticipe(entrees: Any, parametres: Any = None):
    """Compare des stratégies de remboursement accéléré d'un prêt à la stratégie « base » (échéancier normal)."""
    cles = {"objet", "montant_emprunte", "taux_annuel", "frequence", "convention", "amortissement_annees", "strategies"}
    brut, verdict = _cles(entrees, cles, cles)
    if verdict:
        return None, verdict
    objet, verdict = _objet(brut["objet"])
    if verdict:
        return None, verdict
    principal, verdict = _montant(brut["montant_emprunte"], "montant_emprunte", strictement_positif=True)
    if verdict:
        return None, verdict
    taux_annuel, verdict = _taux(brut["taux_annuel"], "taux_annuel")
    if verdict:
        return None, verdict
    if type(brut["frequence"]) is not str or brut["frequence"] not in mf.FREQUENCES:
        return _refus(
            "REJ-CALC-FREQUENCE-INCONNUE", f"frequence {brut['frequence']!r} : une de {sorted(mf.FREQUENCES)}"
        )
    if type(brut["convention"]) is not str or brut["convention"] not in mf.CONVENTIONS_TAUX:
        return _refus("REJ-CALC-CONVENTION-INCONNUE",
                      f"convention {brut['convention']!r} : une de {sorted(mf.CONVENTIONS_TAUX)}")
    annees, verdict = _entier(brut["amortissement_annees"], "amortissement_annees", "REJ-CALC-DUREE-INVALIDE", 1,
                              ANNEES_MAX)
    if verdict:
        return None, verdict
    strategies = brut["strategies"]
    if not isinstance(strategies, list) or not 1 <= len(strategies) <= STRATEGIES_MAX:
        return _refus("REJ-CALC-SCENARIO-INVALIDE", f"strategies : 1 à {STRATEGIES_MAX} stratégies")
    n = annees * mf.FREQUENCES[brut["frequence"]]
    i = mf.taux_periodique(taux_annuel, brut["frequence"], brut["convention"])
    try:
        versement = mf.versement_constant(principal, i, n)
        if versement <= mf.au_cent(principal * i):
            raise ArithmeticError("le versement arrondi ne couvre pas l'intérêt de la première période")
    except ArithmeticError as exc:
        return _refus("REJ-CALC-AMORTISSEMENT-IMPOSSIBLE", str(exc))
    base = _simuler_pret(principal, i, n, versement, Decimal(0), {})
    lues = []
    noms: set[str] = {"base"}
    for index, brute in enumerate(strategies):
        cles_s = {"nom", "versement_additionnel", "remboursements_forfaitaires", "frais"}
        lu, verdict = _cles(brute, cles_s, {"nom"}, "REJ-CALC-SCENARIO-INVALIDE")
        if verdict:
            return None, verdict
        nom = lu["nom"]
        if type(nom) is not str or _RE_NOM_SCENARIO.fullmatch(nom) is None or nom in noms:
            return _refus(
                "REJ-CALC-SCENARIO-INVALIDE",
                f"strategies[{index}].nom : minuscules, chiffres, - _ ; unique, et différent de « base »",
            )
        noms.add(nom)
        extra, verdict = _montant(lu.get("versement_additionnel", "0"), f"{nom}.versement_additionnel",
                                  minimum=Decimal(0))
        if verdict:
            return None, verdict
        frais, verdict = _montant(lu.get("frais", "0"), f"{nom}.frais", minimum=Decimal(0))
        if verdict:
            return None, verdict
        forfaits_bruts = lu.get("remboursements_forfaitaires", [])
        if not isinstance(forfaits_bruts, list) or len(forfaits_bruts) > FORFAITS_MAX:
            return _refus("REJ-CALC-SCENARIO-INVALIDE", f"{nom}.remboursements_forfaitaires : au plus {FORFAITS_MAX}")
        forfaits: dict[int, Decimal] = {}
        for k, f in enumerate(forfaits_bruts):
            lu_f, verdict = _cles(f, {"periode", "montant"}, {"periode", "montant"}, "REJ-CALC-SCENARIO-INVALIDE")
            if verdict:
                return None, verdict
            periode, verdict = _entier(lu_f["periode"], f"{nom}.forfait[{k}].periode", "REJ-CALC-DUREE-INVALIDE", 1, n)
            if verdict:
                return None, verdict
            montant, verdict = _montant(lu_f["montant"], f"{nom}.forfait[{k}].montant", strictement_positif=True)
            if verdict:
                return None, verdict
            forfaits[periode] = forfaits.get(periode, Decimal(0)) + montant
        if extra == 0 and not forfaits:
            return _refus("REJ-CALC-SCENARIO-INVALIDE", f"{nom} : sans versement additionnel ni remboursement "
                                                        "forfaitaire, c'est la stratégie « base »")
        lues.append((nom, extra, forfaits, frais))
    resultats = []
    for nom, extra, forfaits, frais in lues:
        s = _simuler_pret(principal, i, n, versement, extra, forfaits)
        resultats.append({
            "nom": nom, "nombre_versements": s["nombre"], "dernier_versement": _txt_cent(s["dernier"]),
            "total_interets": _txt_cent(s["interets"]), "frais": _txt_cent(frais),
            "total_paye": _txt_cent(s["paye"] + frais),
            "versements_economises": base["nombre"] - s["nombre"],
            "economie_interets": _txt_cent(base["interets"] - s["interets"]),
            "economie_nette_des_frais": _txt_cent(base["interets"] - s["interets"] - frais),
            "solde_final": _txt_cent(s["solde_final"]),
        })
    resultat = {
        "taux_periodique": _txt_taux(i), "versement_normal": _txt_cent(versement),
        "base": {"nombre_versements": base["nombre"], "total_interets": _txt_cent(base["interets"]),
                 "total_paye": _txt_cent(base["paye"])},
        "strategies": resultats,
    }
    avertissements = [
        AVERTISSEMENT_NC_31_103, AVERTISSEMENT_FISCAL,
        "Les pénalités et frais de remboursement anticipé du prêteur ne sont comptés que s'ils sont saisis (« "
        "frais ») : "
        "lire le contrat de prêt.",
        "Un remboursement anticipé réduit les liquidités de l'entreprise : comparer avec sa trésorerie (cash "
        "libre) avant "
        "d'en tirer quoi que ce soit.",
    ]
    normalisees = {
        "objet": objet, "montant_emprunte": format(principal, ".2f"), "taux_annuel": _txt_norme(taux_annuel),
        "frequence": brut["frequence"], "convention": brut["convention"], "amortissement_annees": annees,
        "strategies": [{"nom": nom, "versement_additionnel": format(extra, ".2f"), "frais": format(frais, ".2f"),
                        "remboursements_forfaitaires": [{"periode": p, "montant": format(m, ".2f")}
                                                         for p, m in sorted(forfaits.items())]}
                       for nom, extra, forfaits, frais in lues]}
    return {"recu": _recu("remboursement_anticipe_pret", _METHODE_ANTICIPE, {"versements_par_an": dict(mf.FREQUENCES)},
                          normalisees, resultat, avertissements)}, None


# -------------------------------------------------- 8. échelonnement de placements à terme fixe (trésorerie)
_METHODE_ECHELONNEMENT = (
    "Pour chaque échelon, valeur à l'échéance = montant + intérêts ; intérêt simple : montant × r × terme/12 ; composé "
    "annuellement : montant × (1+r)^(années entières) × (1 + r × mois restants/12) ; arrondi au cent (ROUND_HALF_UP). "
    "Taux moyen pondéré par les montants ; terme moyen pondéré en mois ; couverture de chaque besoin de liquidités = "
    "valeur cumulée des échelons échus au plus tard ce mois-là − besoins cumulés."
)
ECHELONS_MAX = 12
BESOINS_MAX = 12
TERME_MAX_MOIS = 120
_CAPITALISATIONS = ("simple", "compose_annuellement")


def _valeur_echeance(montant: Decimal, taux: Decimal, mois: int, capitalisation: str) -> Decimal:
    with localcontext(mf.CONTEXTE):
        if capitalisation == "simple":
            return mf.au_cent(montant * (Decimal(1) + taux * Decimal(mois) / Decimal(12)))
        annees, reste = divmod(mois, 12)
        return mf.au_cent(montant * (Decimal(1) + taux) ** annees * (Decimal(1) + taux * Decimal(reste) / Decimal(12)))


def calculer_echelonnement_termes(entrees: Any, parametres: Any = None):
    """Échelonnement de placements à terme fixe de la TRÉSORERIE (taux saisis par l'appelant, jamais fournis par M5) :
    valeurs à l'échéance, taux et terme moyens pondérés, couverture des besoins de liquidités. Aucun produit, aucune
    institution : information générale (NC 31-103)."""
    brut, verdict = _cles(entrees, {"montant_total", "echelons", "besoins"}, {"montant_total", "echelons"})
    if verdict:
        return None, verdict
    total, verdict = _montant(brut["montant_total"], "montant_total", strictement_positif=True)
    if verdict:
        return None, verdict
    echelons_bruts = brut["echelons"]
    if not isinstance(echelons_bruts, list) or not 1 <= len(echelons_bruts) <= ECHELONS_MAX:
        return _refus("REJ-CALC-SCENARIO-INVALIDE", f"echelons : 1 à {ECHELONS_MAX} échelons")
    echelons = []
    noms: set[str] = set()
    for index, e in enumerate(echelons_bruts):
        cles_e = {"nom", "montant", "terme_mois", "taux_annuel", "interets"}
        lu, verdict = _cles(e, cles_e, cles_e, "REJ-CALC-SCENARIO-INVALIDE")
        if verdict:
            return None, verdict
        nom = lu["nom"]
        if type(nom) is not str or _RE_NOM_SCENARIO.fullmatch(nom) is None or nom in noms:
            return _refus("REJ-CALC-SCENARIO-INVALIDE", f"echelons[{index}].nom : minuscules, chiffres, - _ ; unique")
        noms.add(nom)
        montant, verdict = _montant(lu["montant"], f"{nom}.montant", strictement_positif=True)
        if verdict:
            return None, verdict
        terme, verdict = _entier(lu["terme_mois"], f"{nom}.terme_mois", "REJ-CALC-DUREE-INVALIDE", 1, TERME_MAX_MOIS)
        if verdict:
            return None, verdict
        taux, verdict = _taux(lu["taux_annuel"], f"{nom}.taux_annuel")
        if verdict:
            return None, verdict
        if lu["interets"] not in _CAPITALISATIONS:
            return _refus("REJ-CALC-CONVENTION-INCONNUE", f"{nom}.interets : un de {list(_CAPITALISATIONS)}")
        echelons.append((nom, montant, terme, taux, lu["interets"]))
    if sum((e[1] for e in echelons), Decimal(0)) != total:
        return _refus("REJ-CALC-FLUX-INVALIDES", "la somme des montants des échelons ne vaut pas montant_total")
    besoins = []
    for index, b in enumerate(brut.get("besoins", [])):
        if not isinstance(brut.get("besoins"), list) or len(brut["besoins"]) > BESOINS_MAX:
            return _refus("REJ-CALC-BORNE-DEPASSEE", f"besoins : au plus {BESOINS_MAX}")
        lu, verdict = _cles(b, {"mois", "montant"}, {"mois", "montant"}, "REJ-CALC-SCENARIO-INVALIDE")
        if verdict:
            return None, verdict
        mois, verdict = _entier(lu["mois"], f"besoins[{index}].mois", "REJ-CALC-DUREE-INVALIDE", 1, TERME_MAX_MOIS)
        if verdict:
            return None, verdict
        montant, verdict = _montant(lu["montant"], f"besoins[{index}].montant", strictement_positif=True)
        if verdict:
            return None, verdict
        besoins.append((mois, montant))
    besoins.sort()
    valeurs = [(nom, montant, terme, taux, cap, _valeur_echeance(montant, taux, terme, cap))
               for nom, montant, terme, taux, cap in echelons]
    with localcontext(mf.CONTEXTE):
        taux_moyen = sum((v[1] * v[3] for v in valeurs), Decimal(0)) / total
        terme_moyen = sum((v[1] * v[2] for v in valeurs), Decimal(0)) / total
    couverture = []
    cumul = Decimal(0)
    for mois, montant in besoins:
        cumul += montant
        disponible = sum((v[5] for v in valeurs if v[2] <= mois), Decimal(0))
        couverture.append({"mois": mois, "besoin": _txt_cent(montant), "besoin_cumule": _txt_cent(cumul),
                           "valeur_echue_cumulee": _txt_cent(disponible), "ecart": _txt_cent(disponible - cumul),
                           "couvert": disponible >= cumul})
    resultat = {
        "echelons": [{"nom": v[0], "montant": _txt_cent(v[1]), "terme_mois": v[2], "taux_annuel": _txt_norme(v[3]),
                      "interets": v[4], "valeur_a_l_echeance": _txt_cent(v[5]),
                      "interets_gagnes": _txt_cent(v[5] - v[1])} for v in valeurs],
        "total_investi": _txt_cent(total),
        "valeur_totale_aux_echeances": _txt_cent(sum((v[5] for v in valeurs), Decimal(0))),
        "interets_totaux": _txt_cent(sum((v[5] - v[1] for v in valeurs), Decimal(0))),
        "taux_moyen_pondere": _txt_taux(taux_moyen), "taux_moyen_pondere_pourcentage": _txt_pourcent(taux_moyen),
        "terme_moyen_pondere_mois": format(terme_moyen.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f"),
        "couverture_des_besoins": couverture,
    }
    avertissements = [
        AVERTISSEMENT_NC_31_103, AVERTISSEMENT_FISCAL,
        "Les taux sont ceux que l'appelant a saisis (soumissions de son institution) : M5 n'en fournit aucun et ne "
        "compare ni produit ni institution.",
        "Le rachat avant l'échéance (pénalités, produits non rachetables) et la protection des dépôts ne sont pas "
        "modélisés : lire les conditions du produit.",
        "L'impôt sur les intérêts gagnés n'est pas modélisé.",
    ]
    normalisees = {"montant_total": format(total, ".2f"),
                   "echelons": [{"nom": n, "montant": format(m, ".2f"), "terme_mois": t, "taux_annuel": _txt_norme(r),
                                 "interets": c} for n, m, t, r, c in echelons],
                   "besoins": [{"mois": m, "montant": format(a, ".2f")} for m, a in besoins]}
    return {"recu": _recu("echelonnement_placements_terme_fixe", _METHODE_ECHELONNEMENT, {"capitalisations": list(
        _CAPITALISATIONS)}, normalisees, resultat, avertissements)}, None


# ---------------------------------------------------------------------------------------------------- rejeu
MOTEURS: dict[tuple[str, str], tuple[Callable[..., Any], tuple[str, ...]]] = {
    ("rentabilite_investissement", VERSION): (calculer_rentabilite, ()),
    ("amortissement_pret", VERSION): (calculer_amortissement, ()),
    ("credit_bail_contre_achat", VERSION): (comparer_credit_bail_achat, ()),
    ("point_mort", VERSION): (calculer_point_mort, ()),
    ("monte_carlo_tresorerie", VERSION): (simuler_tresorerie, ("graine", "tirages", "semaines", "distributions")),
    ("sensibilite_projet", VERSION): (analyser_sensibilite, ()),
    ("remboursement_anticipe_pret", VERSION): (calculer_remboursement_anticipe, ()),
    ("echelonnement_placements_terme_fixe", VERSION): (calculer_echelonnement_termes, ()),
}


def rejouer(recu: Any):
    """Refait le calcul d'un reçu COMPLET (avec `entrees`) et compare les empreintes : `({"identique", ...}, None)`
    ou le refus (reçu retouché ou compact : `REJ-CALC-RECU-INVALIDE` ; moteur ou version inconnus :
    `REJ-CALC-MOTEUR-INCONNU`)."""
    valide, raison = recu_calcul.verifier(recu)
    if not valide:
        return _refus("REJ-CALC-RECU-INVALIDE", raison)
    if "entrees" not in recu:
        return _refus("REJ-CALC-RECU-INVALIDE", (
            "reçu compact (sans entrées) : son empreinte est vérifiée, mais il ne se rejoue qu'avec ses entrées ; pour "
            "le Monte-Carlo, relancer la simulation avec la même graine sur la même prévision (prevision_id)"))
    cle = (recu["moteur"], recu["version_moteur"])
    if cle not in MOTEURS:
        return _refus("REJ-CALC-MOTEUR-INCONNU", f"moteur {cle[0]!r} version {cle[1]!r} : non rejouable par ce code")
    moteur, cles_parametres = MOTEURS[cle]
    parametres = {nom: recu["parametres"].get(nom) for nom in cles_parametres} if cles_parametres else None
    sortie, verdict = moteur(recu["entrees"], parametres)
    if verdict is not None:
        return None, verdict
    recalcule = sortie["recu"]["empreinte"]
    return {"identique": recalcule == recu["empreinte"], "moteur": cle[0], "version_moteur": cle[1],
            "empreinte_recue": recu["empreinte"], "empreinte_recalculee": recalcule}, None
