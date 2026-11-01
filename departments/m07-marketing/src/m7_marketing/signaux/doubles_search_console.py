"""Double FICTIF de l'API Search Analytics de Google Search Console (voir `doubles_base.py`).

Il connaît une propriété (URL encodée dans le chemin), des totaux par jour, des requêtes et des pages par semaine, et
répond
comme le service documenté : corps `{startDate, endDate, dimensions, rowLimit, startRow, dataState, type}`, réponse
`{rows: [{keys, clicks, impressions, ctr, position}], responseAggregationType}`, tri par clics décroissants (par date
croissante pour la dimension `date`), pagination par `startRow`/`rowLimit`, `rowLimit` jusqu'à 25 000, 400 sur une
requête mal
formée, 404 sur une propriété inconnue, 403 sur une propriété sans accès. Données FICTIVES seulement.
"""

from __future__ import annotations

import urllib.parse
from collections.abc import Mapping
from datetime import date, timedelta
from typing import Any

from .doubles_base import ServeurFictif
from .transport import ReponseHttp, RequeteHttp

Ligne = tuple[str, int, int, float, float]  # (clé, clics, impressions, ctr, position)


class DoubleSearchConsole(ServeurFictif):
    HOTES = frozenset({"searchconsole.googleapis.com"})

    def __init__(
        self,
        *,
        propriete: str,
        jeton: str,
        jours: Mapping[str, Ligne] | None = None,
        requetes: Mapping[str, list[Ligne]] | None = None,
        pages: Mapping[str, list[Ligne]] | None = None,
        sans_acces: bool = False,
        **options: Any,
    ) -> None:
        super().__init__(jeton=jeton, **options)
        self._propriete = propriete
        self._jours = dict(jours or {})
        self._requetes = {k: list(v) for k, v in (requetes or {}).items()}  # clé : lundi de la semaine
        self._pages = {k: list(v) for k, v in (pages or {}).items()}
        self._sans_acces = sans_acces

    def reviser_jour(self, jour: str, clics: int, impressions: int) -> None:
        cle, _, _, _, position = self._jours[jour]
        self._jours[jour] = (cle, clics, impressions, round(clics / impressions, 6) if impressions else 0.0, position)

    def traiter(self, requete: RequeteHttp, chemin: str) -> ReponseHttp:
        prefixe, suffixe = "/webmasters/v3/sites/", "/searchAnalytics/query"
        if requete.methode != "POST" or not (chemin.startswith(prefixe) and chemin.endswith(suffixe)):
            return ReponseHttp(404, {"error": {"message": "méthode inconnue"}})
        site = urllib.parse.unquote(chemin[len(prefixe) : -len(suffixe)])
        if site != self._propriete:
            return ReponseHttp(404, {"error": {"message": "propriété inconnue"}})
        if self._sans_acces:
            return ReponseHttp(403, {"error": {"errors": [{"reason": "forbidden"}], "status": "PERMISSION_DENIED"}})
        corps = requete.corps or {}
        try:
            debut, fin = date.fromisoformat(corps["startDate"]), date.fromisoformat(corps["endDate"])
            dimensions, limite, depart = corps["dimensions"], corps["rowLimit"], corps.get("startRow", 0)
        except (KeyError, ValueError, TypeError):
            return ReponseHttp(400, {"error": {"message": "requête mal formée"}})
        if (
            debut > fin
            or dimensions not in (["date"], ["query"], ["page"])
            or type(limite) is not int
            or not 1 <= limite <= 25000
            or type(depart) is not int
            or depart < 0
        ):
            return ReponseHttp(400, {"error": {"message": "paramètres invalides"}})
        if dimensions == ["date"]:
            lignes = [v for k, v in sorted(self._jours.items()) if debut <= date.fromisoformat(k) <= fin]
        else:
            source = self._requetes if dimensions == ["query"] else self._pages
            lignes = []
            lundi = debut
            while lundi <= fin:
                lignes += source.get(lundi.isoformat(), [])
                lundi += timedelta(days=7)
            lignes = sorted(lignes, key=lambda ligne: (-ligne[1], ligne[0]))
        page = lignes[depart : depart + limite]
        return ReponseHttp(
            200,
            {
                "rows": [
                    {"keys": [c], "clicks": cl, "impressions": im, "ctr": ctr, "position": pos}
                    for c, cl, im, ctr, pos in page
                ],
                "responseAggregationType": "byProperty",
            },
        )


__all__ = ["DoubleSearchConsole", "Ligne"]
