"""Scénarios et tests de stress M9.8 : hypothèses nommées, bases sourcées, arithmétique transparente, comparaison à la
référence.

Module pur et déterministe (Decimal exact, arrondi demi-supérieur à l'échelle déclarée). Un scénario applique un CHOC
(paramètres nommés, avec unité et bornes) à des BASES ; une base n'est jamais saisie à la main : c'est un fait citable
du
dossier (``<lecture>#<rang>:<chemin>``, valeur textuelle exacte d'une capture) dont la nature et l'unité sont celles que
le
choc exige. Une base absente ou illisible REFUSE le calcul concerné en nommant ce qui manque et qui le possède — jamais
une
valeur par défaut, jamais un zéro.

Ce que ce module calcule : des SENSIBILITÉS arithmétiques d'une seule hypothèse sur une base (ex. leads × (1 −
pct/100)).
Ce qu'il ne calcule jamais : marge, trésorerie, rentabilité, ROI, capacité d'équipe, élasticité marketing ou date
promise —
ces effets restent ``A_CALCULER_PAR`` leur propriétaire (M5 finance, M4 capacité, M6 stock, M8 mesure) avec les entrées
exactes à lui fournir. Le scénario de RÉFÉRENCE est la base inchangée ; la comparaison rend les écarts signés de mêmes
unités.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from decimal import ROUND_HALF_UP, Decimal, localcontext

VERSION = "2026-10-28.1"
_DECIMAL = re.compile(r"-?\d{1,15}(\.\d{1,6})?")
MAX_CHOCS = 12
_LIMITES = (
    "Sensibilité arithmétique d'hypothèses nommées sur des bases citées : ni prévision, ni marge, ni trésorerie, ni "
    "capacité.",
    "Les effets financiers, de capacité, de stock ou de mesure restent à calculer par leur propriétaire "
    "(A_CALCULER_PAR).",
)


def _refus(code: str, detail: str) -> ValueError:
    return ValueError(f"{code} : {detail}")


def decimal(texte: object, *, nom: str) -> Decimal:
    """Décimal exact depuis un texte sobre (jamais float, NaN, infini ni notation exponentielle)."""
    if type(texte) is not str or not _DECIMAL.fullmatch(texte):
        raise _refus("REJ-SCENARIO-NOMBRE", f'{nom} : nombre décimal textuel sobre requis (ex. "12", "8400.50")')
    return Decimal(texte)


@dataclasses.dataclass(frozen=True)
class Parametre:
    nom: str
    unite: str
    minimum: Decimal
    maximum: Decimal


@dataclasses.dataclass(frozen=True)
class Base:
    nom: str
    unite: str
    proprietaire: str  # département dont la lecture doit fournir cette base
    description: str


@dataclasses.dataclass(frozen=True)
class Effet:
    """Sensibilité arithmétique : ``operation`` ∈ mult_pct_baisse, mult_pct_hausse, soustraire, soustraire_produit."""

    id: str
    base: str
    operation: str
    parametres: tuple[str, ...]
    unite: str
    echelle: int  # décimales conservées (arrondi demi-supérieur)
    plancher_zero: bool = False  # si vrai, un résultat négatif est signalé INFAISABLE (jamais tronqué à zéro)


@dataclasses.dataclass(frozen=True)
class Choc:
    id: str
    libelle: str
    parametres: tuple[Parametre, ...]
    effets: tuple[Effet, ...]
    a_calculer_par: tuple[dict, ...]  # effets que M9 ne calcule pas : propriétaire, outil, entrées à fournir


_POURCENT = lambda nom: Parametre(nom, "%", Decimal("0"), Decimal("100"))  # noqa: E731
_POSITIF = lambda nom, unite, haut="1000000000": Parametre(nom, unite, Decimal("0"), Decimal(haut))  # noqa: E731

BASES: Mapping[str, Base] = {
    base.nom: base
    for base in (
        Base("leads_periode", "leads", "m02-revenue-crm", "leads reçus sur la période de référence"),
        Base("budget_marketing_periode", "CAD", "m07-marketing", "budget marketing déclaré de la période"),
        Base("cout_materiaux_periode", "CAD", "m06-material-control", "coût matériaux de la période"),
        Base("capacite_jours_personnes", "jours-personnes", "m04-field-ops", "capacité d'équipe de la période"),
        Base("jours_ouvrables", "jours", "m04-field-ops", "jours ouvrables de la période"),
        Base("cash_libre", "CAD", "m05-financecore", "cash libre constaté"),
        Base("revenu_periode", "CAD", "m05-financecore", "revenu facturé de la période"),
    )
}

CHOCS: Mapping[str, Choc] = {
    choc.id: choc
    for choc in (
        Choc(
            "baisse_leads",
            "Baisse du volume de leads",
            (_POURCENT("baisse_pct"),),
            (Effet("leads_projetes", "leads_periode", "mult_pct_baisse", ("baisse_pct",), "leads", 2),),
            (
                {
                    "effet": "pipeline et revenus",
                    "proprietaire": "m02-revenue-crm / m05-financecore",
                    "entrees": ["leads_projetes"],
                },
            ),
        ),
        Choc(
            "hausse_budget_marketing",
            "Hausse du budget marketing",
            (_POURCENT("hausse_pct"),),
            (
                Effet(
                    "budget_marketing_projete", "budget_marketing_periode", "mult_pct_hausse", ("hausse_pct",), "CAD", 2
                ),
            ),
            (
                {
                    "effet": "leads additionnels",
                    "proprietaire": "m07-marketing",
                    "entrees": ["budget_marketing_projete"],
                    "motif": "aucune élasticité budget→leads établie par un producteur",
                },
            ),
        ),
        Choc(
            "hausse_cout_materiaux",
            "Hausse du coût des matériaux",
            (_POURCENT("hausse_pct"),),
            (Effet("cout_materiaux_projete", "cout_materiaux_periode", "mult_pct_hausse", ("hausse_pct",), "CAD", 2),),
            (
                {
                    "effet": "marge de chantier",
                    "proprietaire": "m05-financecore",
                    "outil": "m5_lire_rentabilite_chantier",
                    "entrees": ["cout_materiaux_projete"],
                },
            ),
        ),
        Choc(
            "absences",
            "Absences d'équipe",
            (_POSITIF("personnes", "personnes", "1000"), _POSITIF("jours_absents", "jours", "366")),
            (
                Effet(
                    "capacite_restante",
                    "capacite_jours_personnes",
                    "soustraire_produit",
                    ("personnes", "jours_absents"),
                    "jours-personnes",
                    2,
                    plancher_zero=True,
                ),
            ),
            ({"effet": "chantiers décalés", "proprietaire": "m04-field-ops", "entrees": ["capacite_restante"]},),
        ),
        Choc(
            "meteo",
            "Jours de mauvais temps",
            (_POSITIF("jours_bloques", "jours", "366"),),
            (
                Effet(
                    "jours_disponibles",
                    "jours_ouvrables",
                    "soustraire",
                    ("jours_bloques",),
                    "jours",
                    0,
                    plancher_zero=True,
                ),
            ),
            ({"effet": "reprogrammation", "proprietaire": "m04-field-ops", "entrees": ["jours_disponibles"]},),
        ),
        Choc(
            "achat_camion",
            "Achat d'un camion",
            (_POSITIF("prix", "CAD"),),
            (Effet("cash_apres_achat", "cash_libre", "soustraire", ("prix",), "CAD", 2),),
            (
                {
                    "effet": "décision d'investissement",
                    "proprietaire": "m05-financecore",
                    "outil": "m5_preparer_decision_capital",
                    "entrees": ["cash_apres_achat", "prix"],
                    "gouvernance": "dépense réelle : validation humaine",
                },
            ),
        ),
        Choc(
            "nouvel_employe",
            "Embauche d'un employé",
            (_POSITIF("cout_mensuel", "CAD"), _POSITIF("mois", "mois", "120")),
            (Effet("cash_apres_embauche", "cash_libre", "soustraire_produit", ("cout_mensuel", "mois"), "CAD", 2),),
            (
                {
                    "effet": "masse salariale et capacité",
                    "proprietaire": "m05-financecore / m04-field-ops",
                    "entrees": ["cash_apres_embauche"],
                    "gouvernance": "embauche : validation humaine",
                },
            ),
        ),
        Choc(
            "perte_gros_client",
            "Perte d'un gros client",
            (_POSITIF("revenu_perdu", "CAD"),),
            (Effet("revenu_apres_perte", "revenu_periode", "soustraire", ("revenu_perdu",), "CAD", 2),),
            ({"effet": "trésorerie et marge", "proprietaire": "m05-financecore", "entrees": ["revenu_apres_perte"]},),
        ),
        Choc(
            "nouvelle_ville",
            "Ouverture d'une nouvelle ville",
            (_POSITIF("leads_supplementaires", "leads", "1000000"), _POSITIF("investissement", "CAD")),
            (Effet("cash_apres_ouverture", "cash_libre", "soustraire", ("investissement",), "CAD", 2),),
            (
                {
                    "effet": "demande locale",
                    "proprietaire": "m02-revenue-crm / m07-marketing",
                    "motif": "aucune donnée de marché fournie pour cette ville",
                    "entrees": ["leads_supplementaires"],
                },
            ),
        ),
    )
}


def _base(nom: str, bases: Mapping[str, str], faits: Mapping[str, str]) -> tuple[Decimal | None, dict]:
    """(valeur, source) de la base ``nom`` ; ``bases`` : ``nom → adresse de fait`` choisie par l'appelant."""
    definition = BASES[nom]
    adresse = bases.get(nom)
    if adresse is None:
        return None, {
            "base": nom,
            "etat": "BASE_ABSENTE",
            "manque": f"{definition.description} ({definition.proprietaire})",
        }
    if adresse not in faits:
        return None, {
            "base": nom,
            "etat": "FAIT_INCONNU",
            "adresse": adresse,
            "manque": "adresse absente du dossier connu",
        }
    try:
        valeur = decimal(faits[adresse], nom=nom)
    except ValueError:
        return None, {"base": nom, "etat": "FAIT_ILLISIBLE", "adresse": adresse, "manque": "valeur non décimale sobre"}
    return valeur, {
        "base": nom,
        "etat": "SOURCEE",
        "adresse": adresse,
        "valeur": faits[adresse],
        "unite": definition.unite,
        "proprietaire": definition.proprietaire,
    }


def _appliquer(effet: Effet, base: Decimal, valeurs: Mapping[str, Decimal]) -> Decimal:
    with localcontext() as contexte:
        contexte.prec = 40
        if effet.operation == "mult_pct_baisse":
            brut = base * (Decimal(100) - valeurs[effet.parametres[0]]) / Decimal(100)
        elif effet.operation == "mult_pct_hausse":
            brut = base * (Decimal(100) + valeurs[effet.parametres[0]]) / Decimal(100)
        elif effet.operation == "soustraire":
            brut = base - valeurs[effet.parametres[0]]
        elif effet.operation == "soustraire_produit":
            brut = base - valeurs[effet.parametres[0]] * valeurs[effet.parametres[1]]
        else:  # pragma: no cover - garde de construction
            raise ValueError("opération inconnue")
        return brut.quantize(Decimal(1).scaleb(-effet.echelle), rounding=ROUND_HALF_UP)


def evaluer(choc_id: str, parametres: Mapping[str, str], bases: Mapping[str, str], faits: Mapping[str, str]) -> dict:
    """Un scénario : paramètres validés (unités, bornes), bases sourcées, effets arithmétiques et effets à confier."""
    choc = CHOCS.get(choc_id)
    if choc is None:
        raise _refus("REJ-SCENARIO-CHOC", "choc inconnu du catalogue")
    if not isinstance(parametres, Mapping) or set(parametres) != {p.nom for p in choc.parametres}:
        raise _refus("REJ-SCENARIO-PARAMETRES", f"paramètres exacts requis : {[p.nom for p in choc.parametres]}")
    valeurs: dict[str, Decimal] = {}
    for parametre in choc.parametres:
        valeur = decimal(parametres[parametre.nom], nom=parametre.nom)
        if not parametre.minimum <= valeur <= parametre.maximum:
            raise _refus(
                "REJ-SCENARIO-BORNE",
                f"{parametre.nom} hors de [{parametre.minimum}, {parametre.maximum}] {parametre.unite}",
            )
        valeurs[parametre.nom] = valeur
    effets, manques, sources = [], [], {}
    for effet in choc.effets:
        base, source = _base(effet.base, bases, faits)
        sources[effet.base] = source
        if base is None:
            manques.append(source)
            effets.append({"id": effet.id, "statut": "NON_CALCULE", "raison": source["manque"], "base": effet.base})
            continue
        resultat = _appliquer(effet, base, valeurs)
        entree = {
            "id": effet.id,
            "base": effet.base,
            "valeur_base": str(base),
            "unite": effet.unite,
            "operation": effet.operation,
            "parametres": {nom: parametres[nom] for nom in effet.parametres},
            "valeur": str(resultat),
            "ecart": str(resultat - base),
            "nature": "SENSIBILITE_ARITHMETIQUE",
        }
        if effet.plancher_zero and resultat < 0:
            entree["statut"] = "INFAISABLE"
            entree["raison"] = (
                "le résultat serait négatif : hypothèse incompatible avec la base, aucune troncature à zéro"
            )
        else:
            entree["statut"] = "CALCULE"
        effets.append(entree)
    scenario = {
        "type": "SCENARIO",
        "version": VERSION,
        "choc": choc.id,
        "libelle": choc.libelle,
        "hypotheses": [
            {"nom": p.nom, "valeur": parametres[p.nom], "unite": p.unite, "origine": "DECLAREE_PAR_LA_PERSONNE"}
            for p in choc.parametres
        ],
        "bases": sources,
        "effets": effets,
        "a_calculer_par": [dict(element) for element in choc.a_calculer_par],
        "calculable": not manques,
        "limites": list(_LIMITES),
    }
    scenario["scenario_id"] = hashlib.sha256(
        json.dumps(scenario, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()
    return scenario


def comparer(scenarios: Sequence[Mapping], bases: Mapping[str, str], faits: Mapping[str, str]) -> dict:
    """Référence (bases inchangées) et chaque scénario : écarts signés, mêmes unités, aucun classement ni moyenne."""
    if not isinstance(scenarios, Sequence) or not 1 <= len(scenarios) <= MAX_CHOCS:
        raise _refus("REJ-SCENARIO-COMPARAISON", f"1 à {MAX_CHOCS} scénarios requis")
    referencees: dict[str, dict] = {}
    for scenario in scenarios:
        for nom, source in scenario["bases"].items():
            if source["etat"] == "SOURCEE":
                referencees[nom] = {"valeur": source["valeur"], "unite": source["unite"], "adresse": source["adresse"]}
    lignes = []
    for scenario in scenarios:
        for effet in scenario["effets"]:
            if effet["statut"] == "NON_CALCULE":
                lignes.append(
                    {
                        "scenario": scenario["choc"],
                        "effet": effet["id"],
                        "statut": "NON_CALCULE",
                        "raison": effet["raison"],
                    }
                )
                continue
            reference = referencees[effet["base"]]
            if reference["unite"] != effet["unite"] and effet["operation"] not in (
                "mult_pct_baisse",
                "mult_pct_hausse",
            ):
                raise _refus("REJ-SCENARIO-UNITE", f"{effet['id']} : unités de la base et de l'effet divergentes")
            lignes.append(
                {
                    "scenario": scenario["choc"],
                    "effet": effet["id"],
                    "statut": effet["statut"],
                    "reference": reference["valeur"],
                    "valeur": effet["valeur"],
                    "ecart": effet["ecart"],
                    "unite": effet["unite"],
                }
            )
    return {
        "type": "COMPARAISON_SCENARIOS",
        "version": VERSION,
        "reference": referencees,
        "lignes": lignes,
        "scenarios": [s["scenario_id"] for s in scenarios],
        "limites": list(_LIMITES),
    }
