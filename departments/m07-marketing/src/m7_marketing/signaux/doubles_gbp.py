"""Double FICTIF des API de la fiche d'établissement Google (avis v4 et Performance v1) : voir `doubles_base.py`.

Il connaît des fiches (par leur ressource `accounts/N/locations/M` ou `locations/M`), des avis et des séries
quotidiennes, et répond comme les services documentés : avis triés par `updateTime` décroissant, `pageSize` jusqu'à
50, pagination par `nextPageToken` opaque, 400 sur un paramètre invalide, 404 sur une fiche inconnue ; séries
`getDailyMetricsTimeSeries` avec `datedValues` dont la `value` est un TEXTE entier ABSENT pour un jour sans valeur.
Il fournit le nom de l'auteur de chaque avis (pour qu'un test prouve que le connecteur ne le garde jamais). Toute
méthode autre que GET est refusée (405). Données FICTIVES seulement.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, timedelta
from typing import Any

from .doubles_base import ServeurFictif
from .transport import ReponseHttp, RequeteHttp

NOTES_TEXTE = {1: "ONE", 2: "TWO", 3: "THREE", 4: "FOUR", 5: "FIVE"}
METRIQUES_CONNUES = frozenset({
    "BUSINESS_IMPRESSIONS_DESKTOP_MAPS", "BUSINESS_IMPRESSIONS_MOBILE_MAPS", "BUSINESS_IMPRESSIONS_DESKTOP_SEARCH",
    "BUSINESS_IMPRESSIONS_MOBILE_SEARCH", "CALL_CLICKS", "BUSINESS_DIRECTION_REQUESTS", "WEBSITE_CLICKS",
})


def avis_fictif(identifiant: str, note: int, cree: str, *, commentaire: str | None = None, auteur: str = "Auteur "
                                                                                                         "Fictif",
                reponse: str | None = None, modifie: str | None = None) -> dict[str, Any]:
    """Un avis au format du service. `cree` et `modifie` : RFC 3339 UTC."""
    avis: dict[str, Any] = {"reviewId": identifiant, "reviewer": {"displayName": auteur, "isAnonymous": False},
                            "starRating": NOTES_TEXTE[note], "createTime": cree, "updateTime": modifie or cree}
    if commentaire is not None:
        avis["comment"] = commentaire
    if reponse is not None:
        avis["reviewReply"] = {"comment": reponse, "updateTime": modifie or cree}
    return avis


class DoubleGbp(ServeurFictif):
    HOTES = frozenset({"mybusiness.googleapis.com", "businessprofileperformance.googleapis.com"})

    def __init__(self, *, jeton: str, avis: Mapping[str, list[dict[str, Any]]] | None = None,
                 series: Mapping[str, Mapping[str, Mapping[str, str | None]]] | None = None, **options: Any) -> None:
        """`avis` : ressource → liste d'avis. `series` : ressource → métrique → {AAAA-MM-JJ: valeur texte | None}."""
        super().__init__(jeton=jeton, **options)
        self._avis = {k: list(v) for k, v in (avis or {}).items()}
        self._series = {k: {m: dict(j) for m, j in v.items()} for k, v in (series or {}).items()}

    def remplacer_avis(self, ressource: str, avis: list[dict[str, Any]]) -> None:
        """Le fournisseur change ses avis (une réponse ajoutée, une note modifiée)."""
        self._avis[ressource] = list(avis)

    def traiter(self, requete: RequeteHttp, chemin: str) -> ReponseHttp:
        if requete.methode != "GET":
            return ReponseHttp(405, {"error": {"message": "méthode non permise"}})
        if chemin.startswith("/v4/") and chemin.endswith("/reviews"):
            return self._avis_page(chemin[len("/v4/"):-len("/reviews")], requete.params)
        if chemin.startswith("/v1/") and chemin.endswith(":getDailyMetricsTimeSeries"):
            return self._serie(chemin[len("/v1/"):-len(":getDailyMetricsTimeSeries")], requete.params)
        return ReponseHttp(404, {"error": {"message": "méthode inconnue"}})

    def _avis_page(self, ressource: str, params: Mapping[str, str]) -> ReponseHttp:
        if ressource not in self._avis:
            return ReponseHttp(404, {"error": {"message": "fiche inconnue"}})
        try:
            taille = int(params.get("pageSize", "20"))
            depart = int(params["pageToken"].removeprefix("tk-")) if "pageToken" in params else 0
        except ValueError:
            return ReponseHttp(400, {"error": {"message": "paramètre invalide"}})
        if not 1 <= taille <= 50 or depart < 0 or ("pageToken" in params and not params["pageToken"].startswith("tk-")):
            return ReponseHttp(400, {"error": {"message": "paramètre invalide"}})
        tries = sorted(self._avis[ressource], key=lambda a: a["updateTime"], reverse=True)
        page = tries[depart:depart + taille]
        corps: dict[str, Any] = {"reviews": page, "totalReviewCount": len(tries)}
        if depart + taille < len(tries):
            corps["nextPageToken"] = f"tk-{depart + taille}"
        return ReponseHttp(200, corps)

    def _serie(self, ressource: str, params: Mapping[str, str]) -> ReponseHttp:
        if ressource not in self._series:
            return ReponseHttp(404, {"error": {"message": "fiche inconnue"}})
        metrique = params.get("dailyMetric")
        if metrique not in METRIQUES_CONNUES:
            return ReponseHttp(400, {"error": {"message": "métrique inconnue"}})
        try:
            debut = date(int(params["dailyRange.startDate.year"]), int(params["dailyRange.startDate.month"]),
                         int(params["dailyRange.startDate.day"]))
            fin = date(int(params["dailyRange.endDate.year"]), int(params["dailyRange.endDate.month"]),
                       int(params["dailyRange.endDate.day"]))
        except (KeyError, ValueError):
            return ReponseHttp(400, {"error": {"message": "plage invalide"}})
        if debut > fin:
            return ReponseHttp(400, {"error": {"message": "plage inversée"}})
        valeurs = self._series[ressource].get(metrique, {})
        lignes, jour = [], debut
        while jour <= fin:
            ligne: dict[str, Any] = {"date": {"year": jour.year, "month": jour.month, "day": jour.day}}
            valeur = valeurs.get(jour.isoformat())
            if valeur is not None:
                ligne["value"] = valeur
            lignes.append(ligne)
            jour += timedelta(days=1)
        return ReponseHttp(200, {"timeSeries": {"datedValues": lignes}})


__all__ = ["DoubleGbp", "METRIQUES_CONNUES", "NOTES_TEXTE", "avis_fictif"]
