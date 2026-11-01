"""Le RÉSUMÉ agrégé des valeurs de signaux de performance, publié pour M8 (`m7.performance_signaux_constatee`, D2 de
`docs/architecture/M8-ENTREPOT-SOURCES.md`).

Module pur : aucune entrée-sortie, aucune horloge. M8 ne lit aucun outil de M7 : M7 publie, sur le bus, des TOTAUX par
source
et par période, sans rien de ce qui identifie une requête, une page, un référent ou une personne.

Ce qui est sommé, et seulement cela :
- `search_console` et `bing_webmaster` : `clics` et `impressions` des faits `performance_recherche_jour` de portée
`site` ;
- `umami` et `matomo` : `visites` des faits `audience_jour` de portée `site`.
La dernière révision de chaque fait fait foi (`registre.courants`). Un jour sans fait n'est jamais un zéro :
`jours_couverts`
dit combien des `jours_periode` ont un fait. Une mesure que la source ne porte pas, ou qu'aucun fait ne porte, vaut
`None`.
Les faits d'un compte de démonstration (`fictif`) forment leur propre résumé, marqué.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from . import modele
from .erreurs import refus

__all__ = ["JOURS_MAX", "resumer"]

JOURS_MAX = 367
_NATURE_PAR_SOURCE = {
    modele.SEARCH_CONSOLE: ("performance_recherche_jour", ("clics", "impressions")),
    modele.BING_WEBMASTER: ("performance_recherche_jour", ("clics", "impressions")),
    modele.UMAMI: ("audience_jour", ("visites",)),
    modele.MATOMO: ("audience_jour", ("visites",)),
}
_TOUTES_MESURES = ("clics", "impressions", "visites")


def _texte_entier(valeur: Decimal) -> str:
    return format(valeur.quantize(Decimal(1)), "f")


def resumer(faits_courants: Iterable[Mapping[str, Any]], debut: str, fin: str) -> list[dict[str, Any]]:
    """Un résumé par (source, compte, fictif) pour la période `[debut, fin]` (au plus 367 jours) ; liste vide si aucun
    fait
    ne la couvre. Chaque résumé : source, compte_ref, période, jours, jours_couverts, totaux (ou `None`), dernière
    observation, fenêtre de fraîcheur déclarée par M7 pour la source, fictif."""
    d, f = modele.date_iso(debut, "debut"), modele.date_iso(fin, "fin")
    if f < d or (f - d).days >= JOURS_MAX:
        raise refus("REJ-SIGNAUX-FENETRE-INVALIDE", f"période inversée ou de plus de {JOURS_MAX} jours", 422)
    groupes: dict[tuple[str, str, bool], list[Mapping[str, Any]]] = {}
    for fait in faits_courants:
        source = fait["source"]
        attendu = _NATURE_PAR_SOURCE.get(source)
        if attendu is None or fait["nature"] != attendu[0] or fait["portee"]["type"] != "site":
            continue
        if fait["periode_debut"] < debut or fait["periode_fin"] > fin:
            continue
        groupes.setdefault((source, fait["compte_ref"], fait["fictif"]), []).append(fait)
    resumes = []
    for (source, compte_ref, fictif), faits in sorted(groupes.items()):
        jours: set[date] = set()
        for fait in faits:
            jour = date.fromisoformat(fait["periode_debut"])
            while jour <= date.fromisoformat(fait["periode_fin"]):
                jours.add(jour)
                jour += timedelta(days=1)
        totaux: dict[str, Decimal | None] = {nom: None for nom in _TOUTES_MESURES}
        for nom in _NATURE_PAR_SOURCE[source][1]:
            valeurs = [Decimal(fait["mesures"][nom]) for fait in faits if nom in fait["mesures"]]
            totaux[nom] = sum(valeurs, Decimal(0)) if valeurs else None
        resumes.append(
            {
                "source": source,
                "compte_ref": compte_ref,
                "periode_debut": debut,
                "periode_fin": fin,
                "jours_periode": (f - d).days + 1,
                "jours_couverts": len(jours),
                "clics": None if totaux["clics"] is None else _texte_entier(totaux["clics"]),
                "impressions": None if totaux["impressions"] is None else _texte_entier(totaux["impressions"]),
                "visites": None if totaux["visites"] is None else _texte_entier(totaux["visites"]),
                "derniere_observation_le": max(fait["observe_le"] for fait in faits),
                "fraicheur_fenetre_h": modele.SOURCES[source].fraicheur_h,
                "fictif": fictif,
            }
        )
    return resumes
