"""Doubles FICTIFS de PageSpeed Insights v5 et de l'API CrUX (voir `doubles_base.py`).

Ils parlent la forme publique que R4 rapporte, jamais vérifiée contre le vrai service : l'authentification est une CLÉ
D'API passée comme paramètre nommé `key` (`Authentification("parametre", …, nom="key")`) lue dans
`requete.authentification`, jamais dans l'URL ni dans les paramètres ; un 400 sur une requête mal formée ; un 404
sur une origine sans donnée (CrUX). Données FICTIVES seulement.
"""

from __future__ import annotations

import urllib.parse
from collections.abc import Mapping
from typing import Any

from .doubles_base import ServeurFictif
from .transport import ReponseHttp, RequeteHttp

Terrain = Mapping[str, Any]


class DoublePageSpeed(ServeurFictif):
    """`pages` : {url: {stratégie: résultat}} ; un résultat est
    `{score, lcp, cls, tbt, fcp, si, terrain}` où `terrain` est `None` (pas de données de terrain) ou
    `{overall, metrics: {NOM_METRIQUE: (percentile, catégorie)}}`."""

    HOTES = frozenset({"www.googleapis.com"})
    SCHEMA_AUTH = "parametre"
    NOM_AUTH = "key"

    def __init__(self, *, jeton: str, pages: Mapping[str, Mapping[str, Mapping[str, Any]]],
                 analyse_le: str = "2026-11-01T12:00:00.123Z", **options: Any) -> None:
        super().__init__(jeton=jeton, **options)
        self._pages = pages
        self.analyse_le = analyse_le

    def traiter(self, requete: RequeteHttp, chemin: str) -> ReponseHttp:
        if requete.methode != "GET" or chemin != "/pagespeedonline/v5/runPagespeed":
            return ReponseHttp(404, {"error": {"message": "méthode inconnue"}})
        p = requete.params
        if p.get("strategy") not in ("mobile", "desktop") or p.get("category") != "performance" or "key" in p:
            return ReponseHttp(400, {"error": {"message": "paramètres invalides"}})
        if p.get("url") not in self._pages or not urllib.parse.urlsplit(p["url"]).hostname:
            return ReponseHttp(400, {"error": {"message": "URL non analysable"}})
        r = self._pages[p["url"]][p["strategy"]]
        corps: dict[str, Any] = {
            "id": p["url"], "analysisUTCTimestamp": self.analyse_le,
            "lighthouseResult": {
                "categories": {"performance": {"score": r["score"]}},
                "audits": {
                    "largest-contentful-paint": {"numericValue": r["lcp"]},
                    "cumulative-layout-shift": {"numericValue": r["cls"]},
                    "total-blocking-time": {"numericValue": r["tbt"]},
                    "first-contentful-paint": {"numericValue": r["fcp"]},
                    "speed-index": {"numericValue": r["si"]},
                },
            },
        }
        terrain = r.get("terrain")
        if terrain is None:
            corps["loadingExperience"] = {"id": p["url"], "initial_url": p["url"]}
        else:
            corps["loadingExperience"] = {
                "id": p["url"], "overall_category": terrain["overall"],
                "metrics": {nom: {"percentile": pct, "category": cat}
                            for nom, (pct, cat) in terrain["metrics"].items()},
            }
        return ReponseHttp(200, corps)


class DoubleCrux(ServeurFictif):
    """`origines` : {origine: {facteur (PHONE|DESKTOP): {metrique: (p75, [densité bon, moyen, mauvais])},
    "periode": ((a, m, j), (a, m, j))}}`. Une origine ou un facteur absent donne 404 « données introuvables »."""

    HOTES = frozenset({"chromeuxreport.googleapis.com"})
    SCHEMA_AUTH = "parametre"
    NOM_AUTH = "key"
    METRIQUES = ("largest_contentful_paint", "interaction_to_next_paint", "cumulative_layout_shift",
                 "experimental_time_to_first_byte")

    def __init__(self, *, jeton: str, origines: Mapping[str, Mapping[str, Any]], **options: Any) -> None:
        super().__init__(jeton=jeton, **options)
        self._origines = origines

    def traiter(self, requete: RequeteHttp, chemin: str) -> ReponseHttp:
        if requete.methode != "POST" or chemin != "/v1/records:queryRecord":
            return ReponseHttp(404, {"error": {"message": "méthode inconnue"}})
        corps = requete.corps or {}
        origine, facteur, metriques = corps.get("origin"), corps.get("formFactor"), corps.get("metrics")
        if (origine is None or set(corps) - {"origin", "formFactor", "metrics"} or facteur not in ("PHONE", "DESKTOP")
                or not isinstance(metriques, list) or not metriques or set(metriques) - set(self.METRIQUES)
                or "key" in requete.params):
            return ReponseHttp(400, {"error": {"code": 400, "message": "requête invalide",
                                               "status": "INVALID_ARGUMENT"}})
        donnees = self._origines.get(origine, {}).get(facteur)
        if donnees is None:
            return ReponseHttp(404, {"error": {"code": 404, "message": "chrome ux report data not found",
                                               "status": "NOT_FOUND"}})
        sortie: dict[str, Any] = {}
        for nom in metriques:
            if nom not in donnees:
                continue
            p75, densites = donnees[nom]
            cls = nom == "cumulative_layout_shift"
            bornes = ([("0.00", "0.10"), ("0.10", "0.25"), ("0.25", None)] if cls
                      else [(0, 2500), (2500, 4000), (4000, None)])
            histogramme = []
            for (debut, fin), densite in zip(bornes, densites, strict=True):
                bac: dict[str, Any] = {"start": debut, "density": densite}
                if fin is not None:
                    bac["end"] = fin
                histogramme.append(bac)
            sortie[nom] = {"histogram": histogramme, "percentiles": {"p75": p75}}
        debut, fin = self._origines[origine]["periode"]
        return ReponseHttp(200, {"record": {
            "key": {"origin": origine, "formFactor": facteur}, "metrics": sortie,
            "collectionPeriod": {"firstDate": dict(zip(("year", "month", "day"), debut, strict=True)),
                                 "lastDate": dict(zip(("year", "month", "day"), fin, strict=True))}}})


__all__ = ["DoubleCrux", "DoublePageSpeed"]
