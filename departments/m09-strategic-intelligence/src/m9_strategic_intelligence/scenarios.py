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
unités. Un choc sans sensibilité honnête (trésorerie serrée, rupture d'inventaire) n'a AUCUN effet calculé : il n'est
jamais ``calculable`` et ne rend que ses ``a_calculer_par``.
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
    """Sensibilité arithmétique : ``operation`` ∈ OPERATIONS (voir ``_appliquer``)."""

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


OPERATIONS = frozenset(
    {"mult_pct_baisse", "mult_pct_hausse", "soustraire", "soustraire_produit", "ajouter", "soustraire_pct_de"}
)
_POURCENT = lambda nom, haut="100": Parametre(nom, "%", Decimal("0"), Decimal(haut))  # noqa: E731
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
        Base(
            "encaissements_attendus_periode", "CAD", "m05-financecore", "encaissements clients attendus sur la période"
        ),
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
        Choc(
            "achat_equipement",
            "Achat d'un équipement",
            (_POSITIF("prix", "CAD"),),
            (Effet("cash_apres_achat_equipement", "cash_libre", "soustraire", ("prix",), "CAD", 2),),
            (
                {
                    "effet": "décision d'investissement et amortissement",
                    "proprietaire": "m05-financecore",
                    "outil": "m5_preparer_decision_capital",
                    "entrees": ["cash_apres_achat_equipement", "prix"],
                    "gouvernance": "achat majeur : validation humaine",
                },
                {
                    "effet": "capacité gagnée",
                    "proprietaire": "m04-field-ops",
                    "entrees": ["prix"],
                    "motif": "aucun gain de productivité établi par un producteur",
                },
            ),
        ),
        Choc(
            "achat_batisse",
            "Achat d'une bâtisse",
            (_POSITIF("prix", "CAD"), _POURCENT("mise_de_fonds_pct")),
            (
                Effet(
                    "cash_apres_mise_de_fonds",
                    "cash_libre",
                    "soustraire_pct_de",
                    ("prix", "mise_de_fonds_pct"),
                    "CAD",
                    2,
                ),
            ),
            (
                {
                    "effet": "financement, intérêts et charges de la bâtisse",
                    "proprietaire": "m05-financecore",
                    "outil": "m5_preparer_decision_capital",
                    "entrees": ["prix", "mise_de_fonds_pct", "cash_apres_mise_de_fonds"],
                    "gouvernance": "achat majeur et dette : validation humaine, avis comptable et juridique",
                },
            ),
        ),
        Choc(
            "gain_gros_client",
            "Gain d'un gros client",
            (_POSITIF("revenu_ajoute", "CAD"),),
            (Effet("revenu_apres_gain", "revenu_periode", "ajouter", ("revenu_ajoute",), "CAD", 2),),
            (
                {
                    "effet": "capacité d'équipe pour absorber le volume",
                    "proprietaire": "m04-field-ops",
                    "entrees": ["revenu_ajoute"],
                },
                {"effet": "marge et trésorerie", "proprietaire": "m05-financecore", "entrees": ["revenu_apres_gain"]},
            ),
        ),
        Choc(
            "retard_paiement_client",
            "Retard de paiement d'un client",
            (_POSITIF("montant_retarde", "CAD"), _POSITIF("jours_retard", "jours", "366")),
            (
                Effet(
                    "encaissements_apres_retard",
                    "encaissements_attendus_periode",
                    "soustraire",
                    ("montant_retarde",),
                    "CAD",
                    2,
                    plancher_zero=True,
                ),
            ),
            (
                {
                    "effet": "trésorerie semaine par semaine",
                    "proprietaire": "m05-financecore",
                    "outil": "m5_prevoir_tresorerie",
                    "entrees": ["montant_retarde", "jours_retard"],
                },
            ),
        ),
        Choc(
            "saison_morte_faible",
            "Saison morte plus faible",
            (_POURCENT("baisse_revenu_pct"),),
            (Effet("revenu_projete", "revenu_periode", "mult_pct_baisse", ("baisse_revenu_pct",), "CAD", 2),),
            (
                {
                    "effet": "trésorerie de la saison morte",
                    "proprietaire": "m05-financecore",
                    "outil": "m5_prevoir_tresorerie",
                    "entrees": ["revenu_projete"],
                },
                {"effet": "équipes à occuper", "proprietaire": "m04-field-ops", "entrees": ["baisse_revenu_pct"]},
            ),
        ),
        Choc(
            "nouveau_service",
            "Lancement d'un nouveau service",
            (_POSITIF("investissement", "CAD"),),
            (Effet("cash_apres_lancement", "cash_libre", "soustraire", ("investissement",), "CAD", 2),),
            (
                {
                    "effet": "demande pour le service",
                    "proprietaire": "m02-revenue-crm / m07-marketing",
                    "motif": "aucune donnée de marché fournie pour ce service",
                    "entrees": ["investissement"],
                },
                {
                    "effet": "prix de vente et estimation",
                    "proprietaire": "m03-estimation",
                    "entrees": ["description du service par la personne"],
                },
                {
                    "effet": "capacité et compétences",
                    "proprietaire": "m04-field-ops",
                    "entrees": ["description du service par la personne"],
                },
            ),
        ),
        Choc(
            "concurrent_agressif",
            "Concurrent agressif",
            (_POURCENT("perte_leads_pct"),),
            (Effet("leads_projetes", "leads_periode", "mult_pct_baisse", ("perte_leads_pct",), "leads", 2),),
            (
                {
                    "effet": "pipeline et revenus",
                    "proprietaire": "m02-revenue-crm / m05-financecore",
                    "entrees": ["leads_projetes"],
                },
                {
                    "effet": "positionnement et prix",
                    "proprietaire": "m07-marketing / m03-estimation",
                    "outil": "m7_analyser_concurrents",
                    "entrees": ["perte_leads_pct"],
                    "gouvernance": "baisse de prix globale : validation humaine",
                },
            ),
        ),
        Choc(
            "cashflow_serre",
            "Trésorerie serrée",
            (
                Parametre("horizon_semaines", "semaines", Decimal("1"), Decimal("52")),
                _POSITIF("seuil_minimal", "CAD"),
            ),
            (),
            (
                {
                    "effet": "trésorerie projetée face au seuil de la personne",
                    "proprietaire": "m05-financecore",
                    "outil": "m5_prevoir_tresorerie",
                    "entrees": ["horizon_semaines", "seuil_minimal"],
                    "motif": "une projection de trésorerie n'est pas une sensibilité arithmétique : M9 ne la calcule "
                    "pas",
                },
            ),
        ),
        Choc(
            "rupture_inventaire",
            "Rupture d'inventaire",
            (_POSITIF("jours_rupture", "jours", "366"),),
            (),
            (
                {
                    "effet": "matériaux manquants et réservations touchées",
                    "proprietaire": "m06-material-control",
                    "outil": "m6_lire_disponibilite",
                    "entrees": ["jours_rupture"],
                },
                {
                    "effet": "interventions à replanifier",
                    "proprietaire": "m04-field-ops",
                    "entrees": ["jours_rupture"],
                    "motif": "une rupture ne bloque pas tous les chantiers : aucune capacité retirée par M9",
                },
            ),
        ),
        Choc(
            "trop_de_demandes",
            "Trop de demandes",
            (_POURCENT("hausse_pct", "1000"),),
            (Effet("leads_projetes", "leads_periode", "mult_pct_hausse", ("hausse_pct",), "leads", 2),),
            (
                {
                    "effet": "capacité d'estimation et de pose",
                    "proprietaire": "m03-estimation / m04-field-ops",
                    "entrees": ["leads_projetes"],
                    "motif": "aucune capacité d'équipe publiée par un producteur",
                },
            ),
        ),
    )
}


def _verifier_catalogue() -> None:
    for choc in CHOCS.values():
        noms = {p.nom for p in choc.parametres}
        if len(noms) != len(choc.parametres) or not choc.a_calculer_par:
            raise ValueError(f"{choc.id} : paramètres en double ou effets à confier absents")
        for effet in choc.effets:
            if effet.base not in BASES or effet.operation not in OPERATIONS or not set(effet.parametres) <= noms:
                raise ValueError(f"{choc.id}.{effet.id} : base, opération ou paramètre inconnu")


_verifier_catalogue()


def _choc(choc_id: object) -> Choc:
    if type(choc_id) is not str or choc_id not in CHOCS:
        raise _refus("REJ-SCENARIO-CHOC", "choc inconnu du catalogue")
    return CHOCS[choc_id]


def bases_requises(choc_id: str) -> list[dict]:
    """Bases citables qu'exige le choc (nom, unité, propriétaire) ; vide si M9 n'a aucun effet arithmétique honnête."""
    return [
        {
            "base": nom,
            "unite": BASES[nom].unite,
            "proprietaire": BASES[nom].proprietaire,
            "description": BASES[nom].description,
        }
        for nom in sorted({effet.base for effet in _choc(choc_id).effets})
    ]


def valider_parametre(choc_id: str, nom: str, texte: object) -> Decimal:
    """Un paramètre du choc : nom déclaré, décimal textuel sobre, dans ses bornes (refus nommés sinon)."""
    choc = _choc(choc_id)
    parametre = next((p for p in choc.parametres if p.nom == nom), None)
    if parametre is None:
        raise _refus("REJ-SCENARIO-PARAMETRES", f"paramètres exacts requis : {[p.nom for p in choc.parametres]}")
    valeur = decimal(texte, nom=parametre.nom)
    if not parametre.minimum <= valeur <= parametre.maximum:
        raise _refus(
            "REJ-SCENARIO-BORNE",
            f"{parametre.nom} hors de [{parametre.minimum}, {parametre.maximum}] {parametre.unite}",
        )
    return valeur


def valider_parametres(choc_id: str, parametres: object) -> dict[str, Decimal]:
    """Tous les paramètres du choc, exactement : ni manquant, ni en trop, chacun valide et borné."""
    choc = _choc(choc_id)
    if not isinstance(parametres, Mapping) or set(parametres) != {p.nom for p in choc.parametres}:
        raise _refus("REJ-SCENARIO-PARAMETRES", f"paramètres exacts requis : {[p.nom for p in choc.parametres]}")
    return {p.nom: valider_parametre(choc_id, p.nom, parametres[p.nom]) for p in choc.parametres}


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
        elif effet.operation == "ajouter":
            brut = base + valeurs[effet.parametres[0]]
        elif effet.operation == "soustraire_pct_de":
            brut = base - valeurs[effet.parametres[0]] * valeurs[effet.parametres[1]] / Decimal(100)
        else:  # pragma: no cover - garde de construction
            raise ValueError("opération inconnue")
        return brut.quantize(Decimal(1).scaleb(-effet.echelle), rounding=ROUND_HALF_UP)


def evaluer(choc_id: str, parametres: Mapping[str, str], bases: Mapping[str, str], faits: Mapping[str, str]) -> dict:
    """Un scénario : paramètres validés (unités, bornes), bases sourcées, effets arithmétiques et effets à confier."""
    choc = _choc(choc_id)
    valeurs = valider_parametres(choc_id, parametres)
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
    if not choc.effets:
        # Aucune sensibilité arithmétique honnête : tout reste au propriétaire, rien n'est présenté comme calculé.
        scenario["calculable"] = False
        scenario["nature"] = "A_CALCULER_PAR_LE_PROPRIETAIRE"
        scenario["raison"] = "aucun effet arithmétique honnête pour M9 : voir a_calculer_par et ses entrées"
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
