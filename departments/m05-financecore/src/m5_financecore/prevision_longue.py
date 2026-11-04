"""Prévision financière LONGUE de M5 (M5-PREV-2) : 6, 12 ou 24 mois, trois sources et des hypothèses DÉCLARÉES.

Ce que le module rend : une projection mensuelle du solde, pour des scénarios NOMMÉS par la direction, à partir de
trois sources réelles et jamais mélangées au hasard :

1. le CARNET DE CHANTIERS : les échéances datées des contrats explicitement saisis et revus par une personne
   (`echeanciers_contrats`) ; une échéance est un encaissement TTC à sa date, sans taxe recalculée ;
2. le BUDGET DÉCLARÉ : les produits et charges qu'une personne a déclarés pour un mois (`budgets_declares`) ; un
   montant à zéro est un zéro CONNU, jamais un repli sur l'historique ;
3. l'HISTORIQUE DU GRAND LIVRE : la moyenne mensuelle des produits et des charges des écritures DÉFINITIVES des
   `mois_historique` mois complets qui précèdent le mois courant ; un mois sans écriture définitive fait refuser.

Les hypothèses de chaque scénario (croissance mensuelle des revenus et des charges, douze coefficients de
saisonnalité, délai d'encaissement des clients, délai de paiement des fournisseurs) sont DÉCLARÉES par la direction
dans `configuration.prevision_longue`. Elles ne sont jamais supposées : absent ou illisible, le module refuse et dit
quoi déclarer. Les scénarios sont nommés ; aucun nom ni aucune valeur n'est inventé.

RÈGLE DE PRIORITÉ, PAR MOIS (elle évite le double compte) :
- si une échéance contractuelle tombe dans le mois, elle est le produit CONNU du mois ; le budget de produits du même
  mois est IGNORÉ et compté (`couverture.budget_produits_ignores_*`) ;
- sinon, le budget de produits du mois s'il est déclaré ;
- sinon, la moyenne du grand livre, multipliée par la croissance et la saisonnalité du mois civil.
Les charges suivent la même priorité (budget du mois, sinon moyenne du grand livre), sans saisonnalité : la
saisonnalité déclarée porte sur les revenus, jamais sur les charges.

DATES ET DÉLAIS :
- une échéance contractuelle garde sa DATE (elle est déjà datée par la pièce) ; le délai client ne s'y applique pas ;
- un produit du budget ou de l'historique est encaissé à la fin de son mois PLUS le délai client déclaré ;
- une charge est payée à la fin de son mois PLUS le délai fournisseur déclaré ;
- un flux dont la date de trésorerie sort de l'horizon est EXCLU et compté (produits/charges hors horizon) : jamais
  replié sur le dernier mois.

PRUDENCE : une échéance contractuelle déjà ÉCHUE n'est pas comptée (comme la prévision 13 semaines : un client en
retard ne paie pas « au mois 1 ») ; le nombre et le montant sont dits. Une échéance hors horizon est exclue et dite.

HORIZONS : seuls 6, 12 et 24 mois complets APRÈS le mois courant sont acceptés. Le premier mois projeté est le mois
suivant `aujourd_hui` ; le mois courant, partiel, n'est jamais projeté.

CE MODULE NE FAIT JAMAIS : payer, encaisser, remettre, déclarer, écrire, envoyer. Il lit des entrées normalisées et
calcule. Il ne remplace ni la prévision des flux connus et datés à 13 semaines (`prevision.py`), ni le cash libre : il
n'inclut ni taxes, ni paies, ni dettes, ni impôts, ni subventions, et ne lit aucun pipeline commercial. Ces limites sont
dites dans chaque réponse.

ARITHMÉTIQUE : `Decimal` exact, prévision au cent, un seul arrondi explicite par montant calculé (moyenne mensuelle,
croissance, saisonnalité, décalage) avec `ROUND_HALF_UP`, comme le reste de M5. Les sommes de montants déjà au cent
sont exactes. Aucun flottant.

Module pur (ADR-0009, même règle que `prevision.py` et `rapports_financiers.py`) : aucun import d'`opsys`, aucune
horloge, aucun registre, aucun réseau. L'adaptateur (`outils_prevision_longue.py`) lit les registres et appelle ce
module avec des ENTRÉES NORMALISÉES (textes décimaux, dates ISO, entiers).
"""

from __future__ import annotations

import copy
import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Context, Decimal, InvalidOperation, localcontext
from typing import Any

from . import encodage, recu_calcul, verdicts_prevision_longue

__all__ = [
    "HORIZONS",
    "SCENARIOS_MAX",
    "VERSION",
    "calculer",
    "limites",
    "rejouer",
    "vue",
]

VERSION = "1.0.0"
HORIZONS = frozenset({6, 12, 24})
SCENARIOS_MAX = 4
MOIS_HISTORIQUE_MIN = 3
MOIS_HISTORIQUE_MAX = 24
LIGNES_MAX = 24

_CENT = Decimal("0.01")
_ZERO = Decimal("0.00")
_UN = Decimal(1)
_CONTEXTE = Context(prec=64)
_MONTANT_MAX = Decimal("1000000000000")
_TAUX_MAX = Decimal(100)
_MOIS = r"([0-9]{4})-([0-9]{2})"
_MONTANT = r"-?(?:0|[1-9][0-9]{0,11})(?:\.[0-9]{1,2})?"
_TAUX = r"-?(?:0|[1-9][0-9]{0,3})(?:\.[0-9]{1,6})?"
_NOM_SCENARIO = r"[a-z][a-z0-9_-]{0,39}"
_ID_CONTRAT = r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}"
_ECHEANCE = r"[1-9][0-9]{0,5}"
_CLES_CONFIGURATION = frozenset({"mois_historique", "scenarios"})
_CLES_SCENARIO = frozenset({
    "nom", "croissance_revenus_mensuelle", "croissance_charges_mensuelle", "saisonnalite",
    "delai_encaissement_jours", "delai_paiement_jours",
})
_CLES_HISTORIQUE = frozenset({"mois", "produits", "charges", "ecritures", "brouillons"})
_CLES_BUDGET = frozenset({"mois", "produits", "charges"})
_CLES_CARNET = frozenset({"date", "montant", "contrat_id", "echeance"})
_ORDRE_SOURCES = ("carnet", "budget", "historique")

_LIMITES = (
    "hypothèses DÉCLARÉES, pas une prédiction ; aucun CPA ne les a validées",
    "ni taxes, ni paies, ni dettes, ni impôts, ni subventions ; ne remplace pas m5_prevoir_tresorerie ni le cash libre",
    "aucun pipeline commercial ni vente probable n'est lu ou ajouté",
    "solde de départ = registre des mouvements, pas la somme des comptes de banque du grand livre",
    "récurrents = moyenne mensuelle du grand livre, arrondie au cent",
    "une échéance échue n'est pas comptée ; une facture active du même devis bloque l'échéancier",
    "aucun nom de client, aucun texte libre ni donnée personnelle dans la réponse ou le reçu",
)


def limites() -> list[str]:
    """Les limites de la prévision longue, telles qu'elles voyagent avec chaque réponse."""
    return list(_LIMITES)


def _verdict(code: str, detail: str = "") -> dict[str, Any]:
    return verdicts_prevision_longue.construire_verdict(code, detail=detail)


# ================================================================================================ petits outils
def _au_cent(valeur: Decimal) -> Decimal:
    return valeur.quantize(_CENT, rounding=ROUND_HALF_UP)


def _texte_montant(valeur: Decimal) -> str:
    arrondi = _au_cent(valeur)
    if arrondi == 0:
        return "0.00"
    return format(arrondi, "f")


def _somme(valeurs: Iterable[Decimal]) -> Decimal:
    return _au_cent(sum(valeurs, _ZERO))


def _montant(brut: Any) -> Decimal | None:
    """Un montant au cent, lu d'un TEXTE décimal (jamais un flottant, jamais un booléen)."""
    if not isinstance(brut, str) or not brut.isascii():
        return None
    if re.fullmatch(_MONTANT, brut) is None:
        return None
    try:
        valeur = Decimal(brut)
    except InvalidOperation:  # pragma: no cover - la forme est déjà contrôlée
        return None
    if not valeur.is_finite() or abs(valeur) > _MONTANT_MAX:
        return None
    return _au_cent(valeur)


def _taux(brut: Any) -> Decimal | None:
    """Un taux décimal (croissance, coefficient), lu d'un texte ; six décimales au plus, jamais un flottant."""
    if not isinstance(brut, str) or not brut.isascii():
        return None
    if re.fullmatch(_TAUX, brut) is None:
        return None
    try:
        valeur = Decimal(brut)
    except InvalidOperation:  # pragma: no cover
        return None
    if not valeur.is_finite() or abs(valeur) > _TAUX_MAX:
        return None
    return valeur


def _texte_taux(valeur: Decimal) -> str:
    return "0" if valeur == 0 else format(valeur.normalize(), "f")


def _entier(brut: Any) -> int | None:
    return brut if type(brut) is int else None


def _date_iso(brut: Any) -> date | None:
    if not isinstance(brut, str) or len(brut) != 10 or not brut.isascii():
        return None
    try:
        valeur = date.fromisoformat(brut)
    except ValueError:
        return None
    return valeur if valeur.isoformat() == brut else None


def _mois_valide(brut: Any) -> tuple[int, int] | None:
    if not isinstance(brut, str) or not brut.isascii():
        return None
    correspondance = re.fullmatch(_MOIS, brut)
    if correspondance is None:
        return None
    annee, mois = int(correspondance.group(1)), int(correspondance.group(2))
    return (annee, mois) if 1900 <= annee <= 2999 and 1 <= mois <= 12 else None


def _fenetre_dates_valide(jour: date, horizon: int, historique: int) -> bool:
    """La plage acceptée par les lecteurs de mois contient toute la fenêtre demandée."""
    mois_courant = jour.year * 12 + jour.month - 1
    return mois_courant - historique >= 1900 * 12 and mois_courant + horizon <= 2999 * 12 + 11


def _mois_de(jour: date) -> str:
    return f"{jour.year:04d}-{jour.month:02d}"


def _decaler_mois(mois: str, decalage: int) -> str:
    annee, numero = _mois_valide(mois) or (0, 0)
    indice = annee * 12 + numero - 1 + decalage
    return f"{indice // 12:04d}-{indice % 12 + 1:02d}"


def _fin_de_mois(mois: str) -> date:
    annee, numero = _mois_valide(mois) or (0, 0)
    suivant = date(annee + (numero == 12), numero % 12 + 1, 1)
    return suivant - timedelta(days=1)


def _mois_projetes(aujourd_hui: date, horizon: int) -> list[str]:
    premier = _decaler_mois(_mois_de(aujourd_hui), 1)
    return [_decaler_mois(premier, indice) for indice in range(horizon)]


def _mois_historique_attendus(aujourd_hui: date, nombre: int) -> list[str]:
    courant = _mois_de(aujourd_hui)
    return [_decaler_mois(courant, -decalage) for decalage in range(nombre, 0, -1)]


def _ordre(mois: Sequence[str]) -> list[str]:
    rang = {valeur: indice for indice, valeur in enumerate(mois)}
    return sorted(mois, key=lambda valeur: rang.get(valeur, len(rang)))


# ================================================================================================= lecture fermée
def _lire_configuration(brut: Any) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """La configuration `configuration.prevision_longue`, validée et normalisée, ou le refus qui dit quoi déclarer."""
    if brut is None or brut == {}:
        return None, _verdict(
            "REJ-PREVISION-LONGUE-A-DECLARER",
            "aucune hypothèse déclarée : écrire configuration.prevision_longue avec mois_historique (3 à 24) et au "
            "moins un scénario nommé {nom, croissance_revenus_mensuelle, croissance_charges_mensuelle, saisonnalite "
            "(12 coefficients), delai_encaissement_jours, delai_paiement_jours}. Aucune valeur n'est supposée.",
        )
    if not isinstance(brut, Mapping) or set(brut) != _CLES_CONFIGURATION:
        return None, _verdict(
            "REJ-PREVISION-LONGUE-CONFIGURATION-INVALIDE",
            "configuration.prevision_longue : exactement les clés mois_historique et scenarios",
        )
    nombre = _entier(brut["mois_historique"])
    if nombre is None or not MOIS_HISTORIQUE_MIN <= nombre <= MOIS_HISTORIQUE_MAX:
        return None, _verdict(
            "REJ-PREVISION-LONGUE-MOIS-HISTORIQUE-INVALIDE",
            f"mois_historique : entier de {MOIS_HISTORIQUE_MIN} à {MOIS_HISTORIQUE_MAX} (mois complets avant le mois "
            "courant)",
        )
    scenarios_bruts = brut["scenarios"]
    if not isinstance(scenarios_bruts, (list, tuple)) or not scenarios_bruts:
        return None, _verdict(
            "REJ-PREVISION-LONGUE-SCENARIOS-A-DECLARER",
            "scenarios : une liste non vide (au plus quatre) de scénarios NOMMÉS par la direction. Aucun nom n'est "
            "supposé.",
        )
    if len(scenarios_bruts) > SCENARIOS_MAX:
        return None, _verdict(
            "REJ-PREVISION-LONGUE-CONFIGURATION-INVALIDE",
            f"scenarios : au plus {SCENARIOS_MAX} scénarios nommés",
        )
    scenarios: list[dict[str, Any]] = []
    noms: set[str] = set()
    for brut_scenario in scenarios_bruts:
        scenario, verdict = _lire_scenario(brut_scenario)
        if verdict is not None:
            return None, verdict
        if scenario["nom"] in noms:
            return None, _verdict(
                "REJ-PREVISION-LONGUE-SCENARIO-DOUBLE", f"le scénario {scenario['nom']!r} est déclaré deux fois"
            )
        noms.add(scenario["nom"])
        scenarios.append(scenario)
    return {"mois_historique": nombre, "scenarios": scenarios}, None


def _lire_scenario(brut: Any) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if not isinstance(brut, Mapping) or set(brut) != _CLES_SCENARIO:
        return None, _verdict(
            "REJ-PREVISION-LONGUE-SCENARIO-INVALIDE",
            "un scénario porte exactement nom, croissance_revenus_mensuelle, croissance_charges_mensuelle, "
            "saisonnalite, delai_encaissement_jours et delai_paiement_jours",
        )
    if not isinstance(brut["nom"], str) or re.fullmatch(_NOM_SCENARIO, brut["nom"]) is None:
        return None, _verdict(
            "REJ-PREVISION-LONGUE-SCENARIO-INVALIDE",
            "nom : minuscules, chiffres, _ ou - (2 à 40 caractères, commence par une lettre), sans espace ni saut de "
            "ligne",
        )
    croissances = {}
    for cle in ("croissance_revenus_mensuelle", "croissance_charges_mensuelle"):
        valeur = _taux(brut[cle])
        if valeur is None or not -_UN < valeur <= _UN:
            return None, _verdict(
                "REJ-PREVISION-LONGUE-CROISSANCE-INVALIDE",
                f"{cle} : texte décimal strictement supérieur à -1 et inférieur ou égal à 1 (fraction mensuelle)",
            )
        croissances[cle] = _texte_taux(valeur)
    if "saisonnalite" not in brut or brut["saisonnalite"] is None:
        return None, _verdict(
            "REJ-PREVISION-LONGUE-SAISONNALITE-A-DECLARER",
            "saisonnalite : DOUZE coefficients, un par mois civil, déclarés par la direction (aucun n'est supposé)",
        )
    saisonnalite_brute = brut["saisonnalite"]
    if not isinstance(saisonnalite_brute, (list, tuple)):
        return None, _verdict(
            "REJ-PREVISION-LONGUE-SCENARIO-INVALIDE", "saisonnalite : une liste de douze coefficients"
        )
    if len(saisonnalite_brute) != 12:
        return None, _verdict(
            "REJ-PREVISION-LONGUE-SAISONNALITE-A-DECLARER",
            "saisonnalite : DOUZE coefficients exactement (un par mois civil), aucun n'est supposé",
        )
    saisonnalite: list[str] = []
    for coefficient in saisonnalite_brute:
        valeur = _taux(coefficient)
        if valeur is None or not _ZERO <= valeur <= Decimal(3):
            return None, _verdict(
                "REJ-PREVISION-LONGUE-SAISONNALITE-INVALIDE",
                "chaque coefficient de saisonnalite est un texte décimal entre 0 et 3",
            )
        saisonnalite.append(_texte_taux(valeur))
    delais = {}
    for cle in ("delai_encaissement_jours", "delai_paiement_jours"):
        valeur = _entier(brut[cle])
        if valeur is None or not 0 <= valeur <= 365:
            return None, _verdict(
                "REJ-PREVISION-LONGUE-DELAI-INVALIDE", f"{cle} : entier de 0 à 365 jours"
            )
        delais[cle] = valeur
    return {
        "nom": brut["nom"],
        "croissance_revenus_mensuelle": croissances["croissance_revenus_mensuelle"],
        "croissance_charges_mensuelle": croissances["croissance_charges_mensuelle"],
        "saisonnalite": saisonnalite,
        "delai_encaissement_jours": delais["delai_encaissement_jours"],
        "delai_paiement_jours": delais["delai_paiement_jours"],
    }, None


def _lire_historique(
    brut: Any, aujourd_hui: date, nombre: int
) -> tuple[list[dict[str, Any]] | None, dict[str, Any] | None]:
    attendus = _mois_historique_attendus(aujourd_hui, nombre)
    if not isinstance(brut, (list, tuple)) or len(brut) != nombre:
        return None, _verdict(
            "REJ-PREVISION-LONGUE-HISTORIQUE-INCOMPLET",
            f"historique : {nombre} mois complets attendus ({attendus[0]} à {attendus[-1]}), reçus "
            f"{len(brut) if isinstance(brut, (list, tuple)) else 0}",
        )
    normalises: list[dict[str, Any]] = []
    vides: list[str] = []
    brouillons = 0
    for indice, entree in enumerate(brut):
        if not isinstance(entree, Mapping) or set(entree) != _CLES_HISTORIQUE:
            return None, _verdict(
                "REJ-PREVISION-LONGUE-HISTORIQUE-INVALIDE",
                "chaque mois porte exactement mois, produits, charges, ecritures et brouillons",
            )
        if entree["mois"] != attendus[indice]:
            return None, _verdict(
                "REJ-PREVISION-LONGUE-HISTORIQUE-INCOMPLET",
                f"historique : mois {attendus[indice]} attendu à la position {indice + 1}, reçu {entree['mois']!r}",
            )
        produits = _montant(entree["produits"])
        charges = _montant(entree["charges"])
        ecritures = _entier(entree["ecritures"])
        nombre_brouillons = _entier(entree["brouillons"])
        if (
            produits is None
            or charges is None
            or ecritures is None
            or ecritures < 0
            or nombre_brouillons is None
            or nombre_brouillons < 0
        ):
            return None, _verdict(
                "REJ-PREVISION-LONGUE-HISTORIQUE-INVALIDE",
                f"mois {entree['mois']} : produits et charges en texte décimal au cent, ecritures et brouillons "
                "entiers positifs ou nuls",
            )
        if ecritures == 0:
            vides.append(entree["mois"])
        brouillons += nombre_brouillons
        normalises.append({
            "mois": entree["mois"],
            "produits": _texte_montant(produits),
            "charges": _texte_montant(charges),
            "ecritures": ecritures,
            "brouillons": nombre_brouillons,
        })
    if vides:
        return None, _verdict(
            "REJ-PREVISION-LONGUE-HISTORIQUE-INCOMPLET",
            f"mois sans AUCUNE écriture définitive : {', '.join(vides)}. La moyenne serait faussée : déclarer un mois "
            "historique complet ou réduire mois_historique",
        )
    return normalises, None


def _lire_budget(
    brut: Any, mois_projetes: Sequence[str]
) -> tuple[list[dict[str, Any]] | None, dict[str, dict[str, Decimal | None]], dict[str, Any] | None]:
    if brut is None:
        brut = []
    if not isinstance(brut, (list, tuple)):
        return None, {}, _verdict("REJ-PREVISION-LONGUE-BUDGET-INVALIDE", "budget : une liste de mois déclarés")
    autorises = set(mois_projetes)
    par_mois: dict[str, dict[str, Decimal | None]] = {}
    normalises: list[dict[str, Any]] = []
    for entree in brut:
        if not isinstance(entree, Mapping) or set(entree) != _CLES_BUDGET:
            return None, {}, _verdict(
                "REJ-PREVISION-LONGUE-BUDGET-INVALIDE",
                "chaque mois de budget porte exactement mois, produits et charges (produits/charges peuvent être null)",
            )
        if _mois_valide(entree["mois"]) is None or entree["mois"] not in autorises:
            return None, {}, _verdict(
                "REJ-PREVISION-LONGUE-BUDGET-INVALIDE",
                f"mois {entree['mois']!r} hors de l'horizon projeté ({mois_projetes[0]} à {mois_projetes[-1]})",
            )
        produits = None if entree["produits"] is None else _montant(entree["produits"])
        charges = None if entree["charges"] is None else _montant(entree["charges"])
        if (entree["produits"] is not None and produits is None) or (entree["charges"] is not None and charges is None):
            return None, {}, _verdict(
                "REJ-PREVISION-LONGUE-BUDGET-INVALIDE",
                f"mois {entree['mois']} : produits et charges en texte décimal au cent",
            )
        if produits is None and charges is None:
            return None, {}, _verdict(
                "REJ-PREVISION-LONGUE-BUDGET-INVALIDE",
                f"mois {entree['mois']} : au moins un des produits ou des charges est déclaré",
            )
        if (produits is not None and produits < 0) or (charges is not None and charges < 0):
            return None, {}, _verdict(
                "REJ-PREVISION-LONGUE-BUDGET-INVALIDE", f"mois {entree['mois']} : un budget n'est jamais négatif"
            )
        if entree["mois"] in par_mois:
            return None, {}, _verdict(
                "REJ-PREVISION-LONGUE-BUDGET-DOUBLE", f"le mois {entree['mois']} est déclaré deux fois"
            )
        par_mois[entree["mois"]] = {"produits": produits, "charges": charges}
        normalises.append({
            "mois": entree["mois"],
            "produits": None if produits is None else _texte_montant(produits),
            "charges": None if charges is None else _texte_montant(charges),
        })
    return normalises, par_mois, None


def _lire_carnet(
    brut: Any, mois_projetes: Sequence[str]
) -> tuple[list[dict[str, Any]] | None, list[dict[str, Any]], list[dict[str, Any]], dict[str, Any] | None]:
    if brut is None:
        brut = []
    if not isinstance(brut, (list, tuple)):
        return None, [], [], _verdict("REJ-PREVISION-LONGUE-CARNET-INVALIDE", "carnet : une liste d'échéances datées")
    premier = date.fromisoformat(mois_projetes[0] + "-01")
    dernier = _fin_de_mois(mois_projetes[-1])
    retenus: list[dict[str, Any]] = []
    echues: list[dict[str, Any]] = []
    hors: list[dict[str, Any]] = []
    vus: set[tuple[str, str]] = set()
    normalises: list[dict[str, Any]] = []
    for entree in brut:
        if not isinstance(entree, Mapping) or set(entree) != _CLES_CARNET:
            return None, [], [], _verdict(
                "REJ-PREVISION-LONGUE-CARNET-INVALIDE",
                "chaque échéance porte exactement date, montant, contrat_id et echeance (aucun texte libre)",
            )
        jour = _date_iso(entree["date"])
        if jour is None:
            return None, [], [], _verdict(
                "REJ-PREVISION-LONGUE-CARNET-DATE-INVALIDE", f"date {entree['date']!r} : AAAA-MM-JJ exigé"
            )
        montant = _montant(entree["montant"])
        if montant is None or montant <= 0:
            return None, [], [], _verdict(
                "REJ-PREVISION-LONGUE-CARNET-INVALIDE",
                f"échéance {entree.get('contrat_id')!r} : montant en texte décimal au cent, strictement positif",
            )
        contrat = entree["contrat_id"]
        echeance = entree["echeance"]
        if not isinstance(contrat, str) or re.fullmatch(_ID_CONTRAT, contrat) is None:
            return None, [], [], _verdict(
                "REJ-PREVISION-LONGUE-CARNET-INVALIDE", "contrat_id : identifiant de 1 à 64 caractères surs"
            )
        if not isinstance(echeance, str) or re.fullmatch(_ECHEANCE, echeance) is None:
            return None, [], [], _verdict(
                "REJ-PREVISION-LONGUE-CARNET-INVALIDE", "echeance : rang entier positif (texte), sans zéro devant"
            )
        cle = (contrat, echeance)
        if cle in vus:
            return None, [], [], _verdict(
                "REJ-PREVISION-LONGUE-CARNET-DOUBLE",
                f"l'échéance {echeance} du contrat {contrat} est présente deux fois",
            )
        vus.add(cle)
        normalise = {
            "date": jour.isoformat(),
            "montant": _texte_montant(montant),
            "contrat_id": contrat,
            "echeance": echeance,
        }
        normalises.append(normalise)
        if jour < premier:
            echues.append(normalise)
        elif jour > dernier:
            hors.append(normalise)
        else:
            retenus.append(normalise)
    return normalises, retenus, [*echues, *hors], None


# =================================================================================================== projection
def calculer(
    *,
    aujourd_hui: Any,
    horizon_mois: Any,
    solde_initial: Any,
    historique: Any,
    budget: Any,
    carnet: Any,
    configuration: Any,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """La prévision longue : `(complet, None)` ou `(None, verdict)`. Aucune entrée n'est corrigée ni supposée."""
    jour = _date_iso(aujourd_hui)
    if jour is None:
        return None, _verdict("REJ-PREVISION-LONGUE-DATE-INVALIDE", f"{aujourd_hui!r} : AAAA-MM-JJ exigé")
    if type(horizon_mois) is not int or horizon_mois not in HORIZONS:
        return None, _verdict(
            "REJ-PREVISION-LONGUE-HORIZON-INVALIDE",
            f"horizon_mois : l'un de {', '.join(str(h) for h in sorted(HORIZONS))} mois complets après le mois courant",
        )
    solde = _montant(solde_initial)
    if solde is None:
        return None, _verdict(
            "REJ-PREVISION-LONGUE-SOLDE-INVALIDE",
            "solde_initial : texte décimal au cent (négatif accepté : un découvert est un fait)",
        )
    configuration_lue, verdict = _lire_configuration(configuration)
    if verdict is not None:
        return None, verdict
    assert configuration_lue is not None
    # Les helpers de mois acceptent 1900–2999 : refuser toute fenêtre qui
    # dépasserait cette plage avant de construire les mois ou leurs dates.
    if not _fenetre_dates_valide(jour, horizon_mois, configuration_lue["mois_historique"]):
        return None, _verdict(
            "REJ-PREVISION-LONGUE-DATE-INVALIDE",
            "la fenêtre historique et l'horizon doivent rester entre 1900-01 et 2999-12",
        )
    mois = _mois_projetes(jour, horizon_mois)
    historique_lu, verdict = _lire_historique(historique, jour, configuration_lue["mois_historique"])
    if verdict is not None:
        return None, verdict
    budget_lu, budget_par_mois, verdict = _lire_budget(budget, mois)
    if verdict is not None:
        return None, verdict
    carnet_lu, carnet_retenu, carnet_exclu, verdict = _lire_carnet(carnet, mois)
    if verdict is not None:
        return None, verdict
    assert historique_lu is not None and budget_lu is not None and carnet_lu is not None

    complet = _projeter(
        jour=jour,
        horizon=horizon_mois,
        solde=solde,
        mois=mois,
        historique=historique_lu,
        budget_lu=budget_lu,
        budget_par_mois=budget_par_mois,
        carnet_lu=carnet_lu,
        carnet_retenu=carnet_retenu,
        carnet_exclu=carnet_exclu,
        scenarios=configuration_lue["scenarios"],
        configuration=configuration_lue,
    )
    complet["recu"] = _construire_recu(
        jour=jour, horizon=horizon_mois, solde=solde, historique=historique_lu, budget=budget_lu,
        carnet=carnet_lu, configuration=configuration_lue, complet=complet,
    )
    return complet, None


def _projeter(
    *,
    jour: date,
    horizon: int,
    solde: Decimal,
    mois: Sequence[str],
    historique: Sequence[Mapping[str, Any]],
    budget_lu: Sequence[Mapping[str, Any]],
    budget_par_mois: Mapping[str, Mapping[str, Decimal | None]],
    carnet_lu: Sequence[Mapping[str, Any]],
    carnet_retenu: Sequence[Mapping[str, Any]],
    carnet_exclu: Sequence[Mapping[str, Any]],
    scenarios: Sequence[Mapping[str, Any]],
    configuration: Mapping[str, Any],
) -> dict[str, Any]:
    """Le calcul pur, à partir d'entrées déjà validées. Une seule boucle par scénario, aucun état caché."""
    nombre = len(historique)
    with localcontext(_CONTEXTE):
        moyenne_produits = _au_cent(sum((Decimal(m["produits"]) for m in historique), _ZERO) / Decimal(nombre))
        moyenne_charges = _au_cent(sum((Decimal(m["charges"]) for m in historique), _ZERO) / Decimal(nombre))

    carnet_par_mois: dict[str, Decimal] = {}
    for echeance in carnet_retenu:
        carnet_par_mois[echeance["date"][:7]] = carnet_par_mois.get(echeance["date"][:7], _ZERO) + Decimal(
            echeance["montant"]
        )

    mois_carnet = [m for m in mois if m in carnet_par_mois]
    mois_budget = [m for m in mois if m in budget_par_mois]
    mois_recurrents: list[str] = []
    budget_produits_ignores = _ZERO
    budget_produits_ignores_mois: list[str] = []
    decisions: list[dict[str, Any]] = []
    for indice, m in enumerate(mois):
        budget_mois = budget_par_mois.get(m)
        if m in carnet_par_mois:
            source_produits = "carnet"
            if budget_mois is not None and budget_mois["produits"] is not None:
                budget_produits_ignores += budget_mois["produits"]
                budget_produits_ignores_mois.append(m)
        elif budget_mois is not None and budget_mois["produits"] is not None:
            source_produits = "budget"
        else:
            source_produits = "historique"
        source_charges = (
            "budget" if budget_mois is not None and budget_mois["charges"] is not None else "historique"
        )
        if source_produits == "historique" or source_charges == "historique":
            mois_recurrents.append(m)
        decisions.append({
            "indice": indice,
            "mois": m,
            "source_produits": source_produits,
            "source_charges": source_charges,
        })

    scenarios_out: list[dict[str, Any]] = []
    for scenario in scenarios:
        lignes, totaux = _projeter_scenario(
            solde=solde, mois=mois, decisions=decisions, budget_par_mois=budget_par_mois,
            carnet_par_mois=carnet_par_mois, moyenne_produits=moyenne_produits,
            moyenne_charges=moyenne_charges, scenario=scenario,
        )
        scenarios_out.append({
            "nom": scenario["nom"],
            "hypotheses": copy.deepcopy(dict(scenario)),
            "lignes": lignes,
            **totaux,
        })

    brouillons = sum(int(m["brouillons"]) for m in historique)
    premier_jour = date.fromisoformat(mois[0] + "-01")
    dernier_jour = _fin_de_mois(mois[-1])
    echeances_echues = [e for e in carnet_exclu if date.fromisoformat(e["date"]) < premier_jour]
    echeances_hors = [e for e in carnet_exclu if date.fromisoformat(e["date"]) > dernier_jour]
    couverture = {
        "mois_budget": _ordre(mois_budget),
        "mois_carnet": _ordre(mois_carnet),
        "budget_produits_ignores_montant": _texte_montant(budget_produits_ignores),
        "budget_produits_ignores_mois": _ordre(budget_produits_ignores_mois),
        "brouillons_historique": brouillons,
        "echeances_echues": {
            "nombre": len(echeances_echues),
            "montant": _texte_montant(sum((Decimal(e["montant"]) for e in echeances_echues), _ZERO)),
        },
        "echeances_hors_horizon": {
            "nombre": len(echeances_hors),
            "montant": _texte_montant(sum((Decimal(e["montant"]) for e in echeances_hors), _ZERO)),
        },
    }
    limites_reponse = limites()
    if brouillons:
        limites_reponse.append(
            f"{brouillons} écriture(s) en brouillon dans les mois historiques : elles ne sont NI comptées NI "
            "validées ; l'historique est incomplet tant qu'une personne ne les a pas validées (N4)."
        )
    if budget_produits_ignores:
        limites_reponse.append(
            f"{_texte_montant(budget_produits_ignores)} de budget de produits ignoré(s) pour "
            f"{', '.join(_ordre(budget_produits_ignores_mois))} : une échéance contractuelle du même mois est plus "
            "certaine et évite un double compte."
        )
    if echeances_echues:
        limites_reponse.append(
            f"{len(echeances_echues)} échéance(s) contractuelle(s) échue(s) NON comptée(s) "
            f"({_texte_montant(sum((Decimal(e['montant']) for e in echeances_echues), _ZERO))}) : un client en retard "
            "ne paie pas au premier mois (prudent)."
        )
    if echeances_hors:
        limites_reponse.append(
            f"{len(echeances_hors)} échéance(s) contractuelle(s) au-delà de l'horizon, exclue(s) et non repliées."
        )
    if not budget_lu:
        limites_reponse.append(
            "aucun budget déclaré sur l'horizon : les produits et charges récurrents viennent de la moyenne du grand "
            "livre ; la direction peut déclarer un budget (m5_etablir_budget, N3)."
        )
    if mois_recurrents:
        limites_reponse.append(
            "mois sans échéance ni budget : moyenne du grand livre × croissance × saisonnalité DÉCLARÉES (hypothèse)."
        )
    return {
        "type": "PREVISION_LONGUE",
        "statut": "BROUILLON",
        "version": VERSION,
        "aujourd_hui": jour.isoformat(),
        "horizon_mois": horizon,
        "premier_mois": mois[0],
        "dernier_mois": mois[-1],
        "solde_initial": _texte_montant(solde),
        "configuration": copy.deepcopy(dict(configuration)),
        "couverture": couverture,
        "scenarios": scenarios_out,
        "limites": limites_reponse,
    }


def _projeter_scenario(
    *,
    solde: Decimal,
    mois: Sequence[str],
    decisions: Sequence[Mapping[str, Any]],
    budget_par_mois: Mapping[str, Mapping[str, Decimal | None]],
    carnet_par_mois: Mapping[str, Decimal],
    moyenne_produits: Decimal,
    moyenne_charges: Decimal,
    scenario: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    horizon = len(mois)
    croissance_revenus = Decimal(scenario["croissance_revenus_mensuelle"])
    croissance_charges = Decimal(scenario["croissance_charges_mensuelle"])
    saisonnalite = [Decimal(valeur) for valeur in scenario["saisonnalite"]]
    delai_clients = int(scenario["delai_encaissement_jours"])
    delai_fournisseurs = int(scenario["delai_paiement_jours"])
    index = {m: indice for indice, m in enumerate(mois)}

    contrats = [_ZERO] * horizon
    budget_produits = [_ZERO] * horizon
    historique_produits = [_ZERO] * horizon
    budget_charges = [_ZERO] * horizon
    historique_charges = [_ZERO] * horizon
    sources_produits: list[set[str]] = [set() for _ in range(horizon)]
    sources_charges: list[set[str]] = [set() for _ in range(horizon)]
    produits_hors = _ZERO
    charges_hors = _ZERO

    for decision in decisions:
        indice = int(decision["indice"])
        m = decision["mois"]
        budget_mois = budget_par_mois.get(m)
        source_produits = decision["source_produits"]
        source_charges = decision["source_charges"]
        if source_produits == "carnet":
            montant = carnet_par_mois[m]
            contrats[indice] += montant
            sources_produits[indice].add("carnet")
        else:
            if source_produits == "budget":
                montant = (budget_mois or {}).get("produits")
                assert montant is not None
                cible = budget_produits
            else:
                facteur = (_UN + croissance_revenus) ** (indice + 1)
                coefficient = saisonnalite[int(m[5:7]) - 1]
                montant = _au_cent(moyenne_produits * facteur * coefficient)
                cible = historique_produits
            jour_produit = _fin_de_mois(m) + timedelta(days=delai_clients)
            cible_mois = index.get(_mois_de(jour_produit))
            if cible_mois is None:
                produits_hors += montant
            else:
                cible[cible_mois] += montant
                sources_produits[cible_mois].add(source_produits)
        if source_charges == "budget":
            montant_charge = (budget_mois or {}).get("charges")
            assert montant_charge is not None
            cible_charge = budget_charges
        else:
            facteur_charge = (_UN + croissance_charges) ** (indice + 1)
            montant_charge = _au_cent(moyenne_charges * facteur_charge)
            cible_charge = historique_charges
        jour_charge = _fin_de_mois(m) + timedelta(days=delai_fournisseurs)
        mois_charge = index.get(_mois_de(jour_charge))
        if mois_charge is None:
            charges_hors += montant_charge
        else:
            cible_charge[mois_charge] += montant_charge
            sources_charges[mois_charge].add(source_charges)

    lignes: list[dict[str, Any]] = []
    cumul = solde
    total_revenus = _ZERO
    total_charges = _ZERO
    minimal = solde
    sous_zero: list[str] = []
    for indice, m in enumerate(mois):
        revenus = _somme([contrats[indice], budget_produits[indice], historique_produits[indice]])
        charges = _somme([budget_charges[indice], historique_charges[indice]])
        net = _somme([revenus, -charges])
        cumul = _somme([cumul, net])
        total_revenus += revenus
        total_charges += charges
        minimal = min(minimal, cumul)
        if cumul < 0:
            sous_zero.append(m)
        lignes.append({
            "mois": m,
            "contrats": _texte_montant(contrats[indice]),
            "revenus": _texte_montant(revenus),
            "charges": _texte_montant(charges),
            "net": _texte_montant(net),
            "solde_projete": _texte_montant(cumul),
            "sources_produits": [source for source in _ORDRE_SOURCES if source in sources_produits[indice]],
            "sources_charges": [source for source in ("budget", "historique") if source in sources_charges[indice]],
        })
    totaux = {
        "solde_final": _texte_montant(cumul),
        "solde_minimal": _texte_montant(minimal),
        "mois_sous_zero": sous_zero,
        "total_revenus": _texte_montant(total_revenus),
        "total_charges": _texte_montant(total_charges),
        "net_total": _texte_montant(_somme([total_revenus, -total_charges])),
        "produits_hors_horizon": _texte_montant(produits_hors),
        "charges_hors_horizon": _texte_montant(charges_hors),
    }
    return lignes, totaux


# ====================================================================================================== reçu
def _construire_recu(
    *,
    jour: date,
    horizon: int,
    solde: Decimal,
    historique: Sequence[Mapping[str, Any]],
    budget: Sequence[Mapping[str, Any]],
    carnet: Sequence[Mapping[str, Any]],
    configuration: Mapping[str, Any],
    complet: Mapping[str, Any],
) -> dict[str, Any]:
    entrees = {
        "aujourd_hui": jour.isoformat(),
        "horizon_mois": horizon,
        "solde_initial": _texte_montant(solde),
        "historique": [dict(m) for m in historique],
        "budget": [dict(m) for m in budget],
        "carnet": [dict(e) for e in carnet],
        "configuration": copy.deepcopy(dict(configuration)),
    }
    etat = {
        "horizon_mois": horizon,
        "premier_mois": complet["premier_mois"],
        "dernier_mois": complet["dernier_mois"],
        "scenarios": copy.deepcopy(complet["scenarios"]),
    }
    empreinte_etat = encodage.empreinte("m5.prevision_longue.etat.v1", etat)
    resultat = {
        "horizon_mois": horizon,
        "premier_mois": complet["premier_mois"],
        "dernier_mois": complet["dernier_mois"],
        "solde_initial": _texte_montant(solde),
        "solde_final": complet["scenarios"][0]["solde_final"],
        "scenarios": [
            {
                "nom": scenario["nom"],
                "solde_final": scenario["solde_final"],
                "solde_minimal": scenario["solde_minimal"],
                "net_total": scenario["net_total"],
            }
            for scenario in complet["scenarios"]
        ],
        "empreinte_etat": empreinte_etat,
    }
    return recu_calcul.construire(
        moteur="prevision_longue",
        version_moteur=VERSION,
        methode=(
            "Par mois : échéance contractuelle, sinon budget, sinon moyenne du grand livre × croissance × "
            "saisonnalité ; délais déclarés ; sommes exactes au cent et solde cumulé."
        ),
        precision={
            "montants": "Decimal exact au cent (produits calculés arrondis ROUND_HALF_UP)",
            "saisonnalite": "douze coefficients déclarés, par mois civil",
            "horizons": "6, 12 ou 24 mois complets",
        },
        parametres={"horizon_mois": horizon, "scenarios": [s["nom"] for s in configuration["scenarios"]]},
        entrees=entrees,
        resultat=resultat,
        avertissements=[
            *complet["limites"][:3],
            "les limites complètes voyagent avec la réponse (clé `limites`) ; ce reçu porte les trois principales",
        ],
    )


def rejouer(recu: Any) -> tuple[bool, str]:
    """Vérifie un reçu et REFAIT le calcul depuis ses entrées normalisées. `(True, "")` si tout est identique."""
    valide, raison = recu_calcul.verifier(recu)
    if not valide:
        return False, raison
    if not isinstance(recu, Mapping) or "entrees" not in recu:
        return False, (
            "reçu compact (sans entrées) : le rejeu hors ligne est impossible ; rappeler l'outil sur les mêmes "
            "registres"
        )
    entrees = recu["entrees"]
    if not isinstance(entrees, Mapping):
        return False, "entrees : objet attendu"
    try:
        refait, verdict = calculer(
            aujourd_hui=entrees["aujourd_hui"],
            horizon_mois=entrees["horizon_mois"],
            solde_initial=entrees["solde_initial"],
            historique=entrees["historique"],
            budget=entrees["budget"],
            carnet=entrees["carnet"],
            configuration=entrees["configuration"],
        )
    except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
        return False, f"entrées inexploitables : {type(exc).__name__}"
    if verdict is not None:
        return False, f"le rejeu refuse : {verdict['code']}"
    assert refait is not None
    if refait["recu"]["empreinte"] != recu["empreinte"]:
        return False, "le rejeu ne redonne pas le même reçu : les chiffres ne sont pas ceux des entrées"
    return True, ""


# ====================================================================================================== vues
def vue(
    complet: Mapping[str, Any], *, scenario: Any = None, depart: Any = 0, limite: Any = 12
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """La vue d'un scénario (lignes paginées) ou le résumé de tous les scénarios. Pure, sans entrée-sortie."""
    if type(depart) is not int or depart < 0:
        return None, _verdict("REJ-PREVISION-LONGUE-LIMITE-INVALIDE", "depart : entier positif ou nul")
    if type(limite) is not int or not 1 <= limite <= LIGNES_MAX:
        return None, _verdict(
            "REJ-PREVISION-LONGUE-LIMITE-INVALIDE", f"limite : entier de 1 à {LIGNES_MAX} lignes par page"
        )
    scenarios = list(complet["scenarios"])
    corps: dict[str, Any] = {
        "type": "PREVISION_LONGUE",
        "statut": "BROUILLON",
        "version": VERSION,
        "aujourd_hui": complet["aujourd_hui"],
        "horizon_mois": complet["horizon_mois"],
        "premier_mois": complet["premier_mois"],
        "dernier_mois": complet["dernier_mois"],
        "solde_initial": complet["solde_initial"],
        "couverture": copy.deepcopy(complet["couverture"]),
        "limites": list(complet["limites"]),
    }
    if scenario is None:
        corps["scenarios"] = [
            {cle: copy.deepcopy(valeur) for cle, valeur in item.items() if cle != "lignes"} for item in scenarios
        ]
        return corps, None
    if not isinstance(scenario, str):
        return None, _verdict("REJ-PREVISION-LONGUE-SCENARIO-INCONNU", "scenario : nom exact d'un scénario déclaré")
    choisi = next((item for item in scenarios if item["nom"] == scenario), None)
    if choisi is None:
        return None, _verdict(
            "REJ-PREVISION-LONGUE-SCENARIO-INCONNU",
            f"scénario {scenario!r} inconnu ; déclarés : {', '.join(item['nom'] for item in scenarios)}",
        )
    lignes = list(choisi["lignes"])
    tranche = copy.deepcopy(lignes[depart:depart + limite])
    corps["scenario"] = {
        **{cle: copy.deepcopy(valeur) for cle, valeur in choisi.items() if cle != "lignes"},
        "lignes": tranche,
        "lignes_total": len(lignes),
        "prochain_depart": depart + limite if depart + limite < len(lignes) else None,
    }
    return corps, None
