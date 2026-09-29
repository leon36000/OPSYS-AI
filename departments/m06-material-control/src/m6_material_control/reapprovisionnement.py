"""Stock bas et besoin de commande à la sortie de stock (M6.15, PLAN T1.5-d).

DEFINITION-PRODUIT.md §6 (cascade « travaux terminés », ligne M6) : M6 « ajuste le stock, signale le
stock bas, crée le besoin de commande ». Ce module est la RÈGLE, écrite une fois :

    stock théorique de l'article < seuil de réapprovisionnement  =>  besoin de commande
    quantité à commander = quantité cible - stock théorique

- Le seuil et la quantité cible vivent dans `department.yaml`, bloc `configuration.reapprovisionnement.
  articles`, par article (`materiau_id`) : le seul endroit que M6 offre à un non-développeur (comme
  `seuil_variance_chantier_pourcentage`). M6 n'a pas de catalogue persisté (M6.1, question ouverte de
  PLAN T2.3-e) : quand il existera, ces deux champs y migreront, à un seul endroit à la fois.
- Un article sans paramètres, ou dont les paramètres sont invalides, n'est JAMAIS évalué avec un seuil
  deviné : il est signalé « seuil non configuré » (`seuil_a_configurer`), visible de l'admin, avec ce qu'il
  faut renseigner. Fail-closed (AGENTS.md).
- Un stock théorique négatif est une donnée à vérifier, pas une quantité à commander : le besoin est
  signalé sans quantité (`quantite_a_commander` nulle), jamais « cible + le manque » deviné.
- Ce module NE CRÉE JAMAIS de bon de commande (DA-M6-13) : il constate et signale. Un bon de commande reste
  un brouillon demandé explicitement puis approuvé (`bons_commande.py`, T2.4/T2.5). Aucun import de
  `bons_commande` ici, et un test le garde.

Deux faits, dans le registre durable `besoins_commande` (append-only, un maillon par constat, distinct du
registre de mouvements : un constat ne fait bouger aucune quantité) :
- `besoin_commande` : à l'événement déclencheur (le WCT dont la déclaration a sorti du stock), l'article
  était sous son seuil ; les nombres du constat sont ceux de cet instant, figés pour l'audit ;
- `seuil_a_configurer` : à cet événement, l'article n'avait pas de paramètres (`seuil_absent`) ou des
  paramètres inutilisables (`configuration_invalide`, avec le code du refus).
Idempotents par article ET événement déclencheur (`constat_id`) : un rejeu ne double rien.

Le signal de l'admin (`attentes`) n'est PAS le dernier fait recopié : c'est l'état COURANT, recalculé
pour chaque article que M6 a constaté (stock d'aujourd'hui, configuration d'aujourd'hui). Une réception qui
reconstitue le stock, ou un seuil renseigné, fait donc disparaître ou apparaître le signal sans attendre le
prochain chantier — même principe que DA-M6-09 (« tout dérivé du registre, jamais un état caché »).

Le stock est celui de l'ARTICLE, tous lieux confondus (`stock.deriver_stock_articles`) : le seuil est
par article. Sans réservation par chantier (M6.8) ni emplacements (M6.9), c'est la quantité théorique en
main, pas la quantité disponible.

Module pur (AGENTS.md, ADR-0009) : aucun import `opsys`, aucune horloge (les horodatages sont ceux du
WCT), aucun aléa, aucun réseau. `outils.py` fait les entrées-sorties.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from decimal import Decimal
from typing import Any

from . import stock

__all__ = [
    "CLES_PARAMETRES_ARTICLE",
    "TYPE_ATTENTE_BESOIN_COMMANDE",
    "TYPE_ATTENTE_SEUIL_A_CONFIGURER",
    "attentes",
    "construire_constat",
    "constat_deja_range",
    "evaluer",
    "lire_parametres",
]

# Types de fait du registre `besoins_commande`.
TYPE_BESOIN_COMMANDE = "besoin_commande"
TYPE_SEUIL_A_CONFIGURER = "seuil_a_configurer"
# Types d'attente rendus à la file de l'admin (`opsys.approbations.CHAMPS_ATTENTE`).
TYPE_ATTENTE_BESOIN_COMMANDE = "besoin_commande"
TYPE_ATTENTE_SEUIL_A_CONFIGURER = "seuil_a_configurer"
ID_ATTENTE_SEUIL_A_CONFIGURER = "seuils-reapprovisionnement"

# Statuts d'évaluation d'un article.
STATUT_CONFIGURE = "configure"
STATUT_STOCK_BAS = "stock_bas"
STATUT_STOCK_SUFFISANT = "stock_suffisant"
STATUT_SEUIL_ABSENT = "seuil_absent"
STATUT_CONFIGURATION_INVALIDE = "configuration_invalide"

# Les deux paramètres d'un article, exactement : une clé de plus est une faute de frappe à dire, pas à
# ignorer (fail-closed).
CLES_PARAMETRES_ARTICLE = frozenset({"seuil_reapprovisionnement", "quantite_cible"})

NIVEAU_ATTENTE = "N2"  # alerte interne (DEFINITION-PRODUIT.md §5, P1) : rien ne s'exécute seul
_MAX_ARTICLES_NOMMES = 4


def _nombre(valeur: Any) -> Decimal | None:
    """Le nombre YAML (`int` ou `float` fini, jamais un booléen ni un texte) en décimal exact, ou `None`."""
    if isinstance(valeur, bool) or not isinstance(valeur, (int, float)):
        return None
    if isinstance(valeur, float) and not math.isfinite(valeur):
        return None
    return Decimal(str(valeur))


def _texte(valeur: Decimal) -> str:
    return format(valeur, "f")


def _invalide(code: str, detail: str) -> dict[str, Any]:
    return {"statut": STATUT_CONFIGURATION_INVALIDE, "code": code, "detail": detail}


def lire_parametres(articles: Mapping[str, Any] | None, materiau_id: str) -> dict[str, Any]:
    """Les paramètres de réapprovisionnement de cet article, ou pourquoi il n'en a pas.

    `articles` est le bloc `configuration.reapprovisionnement.articles` de `department.yaml` ; `None` dit que
    le bloc est illisible (pas un dictionnaire), ce qui n'est pas la même chose qu'un bloc vide. Rend
    `{"statut": "configure", "seuil": Decimal, "quantite_cible": Decimal}`, ou `{"statut": "seuil_absent"}`
    (l'article n'est pas dans la configuration), ou `{"statut": "configuration_invalide", "code", "detail"}`.
    """
    if articles is None:
        return _invalide(
            "REJ-REAPPRO-CONFIGURATION-ILLISIBLE",
            "le bloc configuration.reapprovisionnement.articles n'est pas un dictionnaire",
        )
    if materiau_id not in articles:
        return {"statut": STATUT_SEUIL_ABSENT}
    parametres = articles[materiau_id]
    if not isinstance(parametres, Mapping) or set(parametres) != CLES_PARAMETRES_ARTICLE:
        return _invalide(
            "REJ-REAPPRO-ARTICLE-INVALIDE",
            "attendu exactement : seuil_reapprovisionnement et quantite_cible",
        )
    seuil = _nombre(parametres["seuil_reapprovisionnement"])
    if seuil is None or seuil <= 0:
        return _invalide("REJ-REAPPRO-SEUIL-INVALIDE", "seuil_reapprovisionnement : un nombre fini supérieur à zéro")
    cible = _nombre(parametres["quantite_cible"])
    if cible is None or cible < seuil:
        return _invalide(
            "REJ-REAPPRO-CIBLE-INVALIDE", "quantite_cible : un nombre fini, au moins égal au seuil"
        )
    return {"statut": STATUT_CONFIGURE, "seuil": seuil, "quantite_cible": cible}


def evaluer(materiau_id: str, stock_article: Decimal, articles: Mapping[str, Any] | None) -> dict[str, Any]:
    """Le verdict de l'article : `stock_bas`, `stock_suffisant`, ou ce qui manque (`seuil_absent`,
    `configuration_invalide`). « Sous le seuil » est strict : un stock égal au seuil n'est pas bas.

    `stock_bas` porte les nombres de l'instant (stock, seuil, cible en texte décimal) et
    `quantite_a_commander` = cible - stock, sauf si le stock théorique est négatif (`stock_negatif`), où elle
    vaut `None` : commander « cible + le manque » validerait une erreur de livre.
    """
    parametres = lire_parametres(articles, materiau_id)
    if parametres["statut"] != STATUT_CONFIGURE:
        return {"materiau_id": materiau_id, **parametres}
    seuil, cible = parametres["seuil"], parametres["quantite_cible"]
    if stock_article >= seuil:
        return {
            "materiau_id": materiau_id, "statut": STATUT_STOCK_SUFFISANT, "stock_theorique": _texte(stock_article),
        }
    negatif = stock_article < 0
    return {
        "materiau_id": materiau_id,
        "statut": STATUT_STOCK_BAS,
        "stock_theorique": _texte(stock_article),
        "seuil_reapprovisionnement": _texte(seuil),
        "quantite_cible": _texte(cible),
        "quantite_a_commander": None if negatif else _texte(cible - stock_article),
        "stock_negatif": negatif,
    }


def construire_constat(
    verdict: Mapping[str, Any], *, evenement_declencheur: str, horodatage: Any, chantier_id: Any, unite: Any
) -> dict[str, Any] | None:
    """Le maillon du registre `besoins_commande` pour ce verdict, ou `None` si le stock est suffisant (rien
    à constater : le silence n'est pas un fait). Sans écriture : l'appelant ajoute le maillon, après
    `constat_deja_range`. `horodatage` est celui du WCT (jamais une horloge), `chantier_id` le lieu de la
    sortie qui a déclenché l'évaluation."""
    statut = verdict["statut"]
    if statut == STATUT_STOCK_SUFFISANT:
        return None
    materiau_id = verdict["materiau_id"]
    type_entree = TYPE_BESOIN_COMMANDE if statut == STATUT_STOCK_BAS else TYPE_SEUIL_A_CONFIGURER
    constat: dict[str, Any] = {
        "type_entree": type_entree,
        "constat_id": f"{type_entree}:{materiau_id}:{evenement_declencheur}",
        "materiau_id": materiau_id,
        "evenement_declencheur": evenement_declencheur,
        "chantier_id": chantier_id,
        "unite": unite,
        "horodatage": horodatage,
    }
    if statut == STATUT_STOCK_BAS:
        for cle in (
            "stock_theorique", "seuil_reapprovisionnement", "quantite_cible", "quantite_a_commander",
            "stock_negatif",
        ):
            constat[cle] = verdict[cle]
    else:
        constat["motif"] = statut
        constat["code"] = verdict.get("code")
        constat["detail"] = verdict.get("detail")
    return constat


def constat_deja_range(constat: Mapping[str, Any], maillons_existants: Iterable[Mapping[str, Any]]) -> bool:
    """Vrai si un maillon porte déjà ce `constat_id` : un même article, pour un même événement déclencheur,
    ne se constate qu'une fois (rejeu, appel répété : aucun doublon, aucune réécriture)."""
    return any(maillon.get("constat_id") == constat["constat_id"] for maillon in maillons_existants)


def _avec_unite(valeur: str, unite: Any) -> str:
    return f"{valeur} {unite}" if isinstance(unite, str) and unite else valeur


def _attente_besoin(dernier: Mapping[str, Any], verdict: Mapping[str, Any]) -> dict[str, Any]:
    unite = dernier.get("unite")
    materiau_id = verdict["materiau_id"]
    stock_en_main = _avec_unite(verdict["stock_theorique"], unite)
    seuil = _avec_unite(verdict["seuil_reapprovisionnement"], unite)
    if verdict["stock_negatif"]:
        resume = (
            f"Stock bas : {materiau_id} — stock théorique négatif ({stock_en_main}), à vérifier avant de "
            f"commander ; seuil {seuil}"
        )
    else:
        a_commander = _avec_unite(verdict["quantite_a_commander"], unite)
        cible = _avec_unite(verdict["quantite_cible"], unite)
        resume = (
            f"Stock bas : {materiau_id} — {stock_en_main} en main, sous le seuil de {seuil} ; besoin de "
            f"commande : {a_commander} pour atteindre {cible} (chantier {dernier.get('chantier_id')})"
        )
    return {
        "type": TYPE_ATTENTE_BESOIN_COMMANDE,
        "id": f"{TYPE_BESOIN_COMMANDE}:{materiau_id}",
        "resume": resume,
        "niveau": NIVEAU_ATTENTE,
        "depuis": _depuis(dernier),
        "action_proposee": (
            "Décider de commander : un bon de commande se demande en brouillon puis s'approuve, M6 n'en "
            "crée jamais seul"
        ),
    }


def _depuis(constat: Mapping[str, Any]) -> str:
    horodatage = constat.get("horodatage")
    return horodatage if isinstance(horodatage, str) else ""


def _attente_a_configurer(a_configurer: list[tuple[str, Mapping[str, Any], str]]) -> dict[str, Any]:
    """Une seule attente pour tous les articles sans paramètres utilisables : au début de l'usage, ils sont
    nombreux, et une attente par article noierait les alertes qui demandent une décision."""
    nommes = [
        f"{materiau_id} (invalide)" if statut == STATUT_CONFIGURATION_INVALIDE else materiau_id
        for materiau_id, _, statut in a_configurer[:_MAX_ARTICLES_NOMMES]
    ]
    reste = len(a_configurer) - len(nommes)
    liste = ", ".join(nommes) + (f" et {reste} autre(s)" if reste > 0 else "")
    return {
        "type": TYPE_ATTENTE_SEUIL_A_CONFIGURER,
        "id": ID_ATTENTE_SEUIL_A_CONFIGURER,
        "resume": (
            f"Seuil de réapprovisionnement non configuré : {liste}. Le stock bas de "
            f"{'cet article' if len(a_configurer) == 1 else 'ces articles'} n'est pas évalué."
        ),
        "niveau": NIVEAU_ATTENTE,
        "depuis": min(_depuis(dernier) for _, dernier, _ in a_configurer),
        "action_proposee": (
            "Renseigner seuil_reapprovisionnement et quantite_cible de chaque article dans le "
            "department.yaml de M6 (configuration.reapprovisionnement.articles)"
        ),
    }


def attentes(
    constats: Iterable[Mapping[str, Any]], mouvements: Iterable[Mapping[str, Any]],
    articles: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    """Les attentes de M6 pour la file de l'admin (forme `opsys.approbations.CHAMPS_ATTENTE`).

    Pour chaque article que M6 a constaté au moins une fois (`constats`), l'état d'AUJOURD'HUI :
    - paramètres utilisables et stock d'aujourd'hui sous le seuil : une attente `besoin_commande` PAR ARTICLE
      (`id` = l'article, stable d'un chantier à l'autre), avec les nombres d'aujourd'hui, et `depuis` = le
      dernier constat (le WCT qui a sorti du stock) ;
    - paramètres absents ou invalides aujourd'hui : l'article rejoint l'attente unique
      `seuil_a_configurer` (jamais un seuil deviné) ;
    - stock redevenu suffisant, ou article maintenant configuré et au-dessus de son seuil : rien.
    Une attente sans fait derrière elle n'existe pas : un article que M6 n'a jamais constaté n'apparaît pas.
    """
    dernier_par_article: dict[str, Mapping[str, Any]] = {}
    for constat in constats:
        dernier_par_article[constat["materiau_id"]] = constat
    if not dernier_par_article:
        return []
    stocks = stock.deriver_stock_articles(dernier_par_article, mouvements)
    besoins: list[dict[str, Any]] = []
    a_configurer: list[tuple[str, Mapping[str, Any], str]] = []
    for materiau_id in sorted(dernier_par_article):
        dernier = dernier_par_article[materiau_id]
        verdict = evaluer(materiau_id, stocks[materiau_id], articles)
        if verdict["statut"] == STATUT_STOCK_BAS:
            besoins.append(_attente_besoin(dernier, verdict))
        elif verdict["statut"] != STATUT_STOCK_SUFFISANT:
            a_configurer.append((materiau_id, dernier, verdict["statut"]))
    if a_configurer:
        besoins.append(_attente_a_configurer(a_configurer))
    return besoins
