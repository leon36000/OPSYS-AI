"""Double FICTIF de l'API JSON de Bing Webmaster Tools (voir `doubles_base.py`).

Il connaît une propriété (paramètre `siteUrl`), des totaux par jour et des lignes par date pour les requêtes et les
pages, et répond comme le service documenté : `GET /webmaster/api.svc/json/<Méthode>?siteUrl=…`, clé d'API en
paramètre `apikey` (placé par le transport : jamais dans les paramètres vus ici), réponse `{"d": [ {Date:
"/Date(ms)/", …} ]}`, 400 sur un paramètre manquant, 404 sur une méthode inconnue, 403 sur une propriété sans
accès. L'API n'a ni pagination ni période : toute la mémoire du double est rendue. Données FICTIVES seulement.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Any

from .doubles_base import ServeurFictif
from .transport import ReponseHttp, RequeteHttp

# Ligne de requête ou de page : (jour ISO, clé, impressions, clics, position moyenne de clic, position moyenne
# d'impression)
LigneBing = tuple[str, str, int, int, float, float]


def date_ms(jour: str) -> str:
    """Un jour ISO au format `/Date(ms)/` du service (minuit UTC)."""
    ms = int(datetime.combine(date.fromisoformat(jour), datetime.min.time(), tzinfo=UTC).timestamp() * 1000)
    return f"/Date({ms})/"


class DoubleBingWebmaster(ServeurFictif):
    HOTES = frozenset({"ssl.bing.com"})
    SCHEMA_AUTH = "parametre"
    NOM_AUTH = "apikey"

    def __init__(self, *, propriete: str, jeton: str, jours: Mapping[str, tuple[int, int]] | None = None,
                 requetes: list[LigneBing] | None = None, pages: list[LigneBing] | None = None,
                 sans_acces: bool = False, dates_brutes: bool = False, **options: Any) -> None:
        super().__init__(jeton=jeton, **options)
        self._propriete = propriete
        self._jours = dict(jours or {})  # jour ISO -> (impressions, clics)
        self._requetes = list(requetes or [])
        self._pages = list(pages or [])
        self._sans_acces = sans_acces
        self._dates_brutes = dates_brutes  # le service « change de format » : le connecteur doit refuser

    def reviser_jour(self, jour: str, impressions: int, clics: int) -> None:
        self._jours[jour] = (impressions, clics)

    def _date(self, jour: str) -> str:
        return jour if self._dates_brutes else date_ms(jour)

    def traiter(self, requete: RequeteHttp, chemin: str) -> ReponseHttp:
        prefixe = "/webmaster/api.svc/json/"
        if requete.methode != "GET" or not chemin.startswith(prefixe):
            return ReponseHttp(404, {"Message": "méthode inconnue"})
        methode = chemin[len(prefixe):]
        if methode not in ("GetRankAndTrafficStats", "GetQueryStats", "GetPageStats"):
            return ReponseHttp(404, {"Message": "méthode inconnue"})
        site = requete.params.get("siteUrl")
        if not site:
            return ReponseHttp(400, {"Message": "siteUrl manquant"})
        if site != self._propriete:
            return ReponseHttp(404, {"Message": "site inconnu"})
        if self._sans_acces:
            return ReponseHttp(403, {"Message": "accès refusé à ce site"})
        if methode == "GetRankAndTrafficStats":
            lignes = [{"Date": self._date(j), "Impressions": i, "Clicks": c}
                      for j, (i, c) in sorted(self._jours.items())]
        else:
            source = self._requetes if methode == "GetQueryStats" else self._pages
            lignes = [{"Date": self._date(j), "Query": q, "Impressions": i, "Clicks": c, "AvgClickPosition": pc,
                       "AvgImpressionPosition": pi} for j, q, i, c, pc, pi in sorted(source)]
        return ReponseHttp(200, {"d": lignes})


__all__ = ["DoubleBingWebmaster", "LigneBing", "date_ms"]
