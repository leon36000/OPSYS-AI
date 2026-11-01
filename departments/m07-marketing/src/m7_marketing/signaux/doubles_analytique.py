"""Doubles FICTIFS d'Umami et de Matomo auto-hébergés (voir `doubles_base.py`).

Un service auto-hébergé n'a pas d'hôte fixe : le double reçoit son `hote` au constructeur (celui de l'adresse de base
déclarée par le client), et un éventuel préfixe de chemin (`prefixe_chemin`, p. ex. « /matomo »).

`DoubleUmami` répond comme l'API REST documentée : `GET <préfixe>/api/websites/<id>/stats?startAt=&endAt=` →
`{pageviews: {value, prev}, visitors, visits, bounces, totaltime}` (la somme des jours de la plage ; `prev` = la
plage de même longueur qui précède) ; `GET …/metrics?type=referrer&startAt=&endAt=&limit=` → `[{x, y}]` trié par `y`
décroissant ; jeton porteur ; 400 sur une plage inversée, un `type` inconnu ou une `limit` hors 1–500 ; 404 sur un
site inconnu.

`DoubleMatomo` répond comme la Reporting API : `POST <préfixe>/index.php`, corps de formulaire `{module: API, method,
idSite, period, date, format: JSON, token_auth}` ; `VisitsSummary.get` (période `day`, `date` = « début,fin ») rend
un objet par jour, `[]` pour un jour sans donnée ; `Referrers.getWebsites` (période `range`) rend `[{label,
nb_visits}]`. Comme le vrai service, il répond HTTP 200 avec `{"result": "error", "message": …}` à un jeton faux, un
site inconnu, une méthode inconnue ou un paramètre invalide. Données FICTIVES seulement.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from typing import Any

from .doubles_base import ServeurFictif
from .transport import Authentification, ReponseHttp, RequeteHttp

CLES_UMAMI = ("pageviews", "visitors", "visits", "bounces", "totaltime")


def _jour_de_ms(ms: int) -> date:
    return (datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=ms)).date()


class DoubleUmami(ServeurFictif):
    def __init__(self, *, hote: str, site_id: str, jeton: str, jours: Mapping[str, Mapping[str, int]] | None = None,
                 referents: Mapping[str, list[tuple[str, int]]] | None = None, prefixe_chemin: str = "",
                 **options: Any) -> None:
        super().__init__(jeton=jeton, hotes=[hote], **options)
        self._site_id, self._prefixe = site_id, prefixe_chemin
        self._jours = {j: dict(v) for j, v in (jours or {}).items()}
        self._referents = {j: list(v) for j, v in (referents or {}).items()}

    def reviser_jour(self, jour: str, **valeurs: int) -> None:
        self._jours[jour] = {**self._jours.get(jour, {}), **valeurs}

    def _somme(self, debut: date, fin: date) -> dict[str, int]:
        total = dict.fromkeys(CLES_UMAMI, 0)
        courant = debut
        while courant <= fin:
            for cle, valeur in self._jours.get(courant.isoformat(), {}).items():
                total[cle] += valeur
            courant += timedelta(days=1)
        return total

    @staticmethod
    def _plage(params: Mapping[str, str]) -> tuple[int, int] | None:
        try:
            debut, fin = int(params["startAt"]), int(params["endAt"])
        except (KeyError, ValueError):
            return None
        return (debut, fin) if 0 <= debut <= fin and fin - debut < 367 * 86_400_000 else None

    def traiter(self, requete: RequeteHttp, chemin: str) -> ReponseHttp:
        racine = f"{self._prefixe}/api/websites/"
        if requete.methode != "GET" or not chemin.startswith(racine):
            return ReponseHttp(404, {"error": "route inconnue"})
        site, _, action = chemin[len(racine):].partition("/")
        if site != self._site_id:
            return ReponseHttp(404, {"error": "site inconnu"})
        if action not in ("stats", "metrics"):
            return ReponseHttp(404, {"error": "route inconnue"})
        plage = self._plage(requete.params)
        if plage is None:
            return ReponseHttp(400, {"error": "paramètres"})
        debut, fin = _jour_de_ms(plage[0]), _jour_de_ms(plage[1])
        if action == "stats":
            actuel, longueur = self._somme(debut, fin), (fin - debut).days + 1
            avant = self._somme(debut - timedelta(days=longueur), debut - timedelta(days=1))
            return ReponseHttp(200, {cle: {"value": actuel[cle], "prev": avant[cle]} for cle in CLES_UMAMI})
        limite = requete.params.get("limit", "10")
        if requete.params.get("type") != "referrer" or not limite.isdigit() or not 1 <= int(limite) <= 500:
            return ReponseHttp(400, {"error": "paramètres"})
        cumul: dict[str, int] = {}
        courant = debut
        while courant <= fin:
            for x, y in self._referents.get(courant.isoformat(), []):
                cumul[x] = cumul.get(x, 0) + y
            courant += timedelta(days=1)
        lignes = sorted(cumul.items(), key=lambda t: (-t[1], t[0]))[:int(limite)]
        return ReponseHttp(200, [{"x": x, "y": y} for x, y in lignes])


class DoubleMatomo(ServeurFictif):
    SCHEMA_AUTH = "parametre"
    NOM_AUTH = "token_auth"

    def __init__(self, *, hote: str, id_site: str, jeton: str, jours: Mapping[str, Mapping[str, int]] | None = None,
                 referents: Mapping[str, list[tuple[str, int]]] | None = None, prefixe_chemin: str = "",
                 **options: Any) -> None:
        super().__init__(jeton=jeton, hotes=[hote], **options)
        self._id_site, self._prefixe = id_site, prefixe_chemin
        self._jours = {j: dict(v) for j, v in (jours or {}).items()}
        self._referents = {j: list(v) for j, v in (referents or {}).items()}

    def reviser_jour(self, jour: str, **valeurs: int) -> None:
        self._jours[jour] = {**self._jours.get(jour, {}), **valeurs}

    def _authentifie(self, auth: Authentification | None) -> bool:
        return True  # Matomo répond 200 + {"result": "error"} à un jeton faux : vérifié dans `traiter`

    @staticmethod
    def _erreur(message: str) -> ReponseHttp:
        return ReponseHttp(200, {"result": "error", "message": message})

    @staticmethod
    def _dates(texte: Any) -> tuple[date, date] | None:
        try:
            debut, _, fin = str(texte).partition(",")
            return date.fromisoformat(debut), date.fromisoformat(fin)
        except ValueError:
            return None

    def traiter(self, requete: RequeteHttp, chemin: str) -> ReponseHttp:
        if requete.methode != "POST" or chemin != f"{self._prefixe}/index.php":
            return ReponseHttp(404, {"error": "route inconnue"})
        auth = requete.authentification
        if auth is None or auth.schema != "parametre" or auth.nom != "token_auth" or auth.valeur != self._jeton:
            return self._erreur("accès refusé : jeton invalide")
        corps = requete.corps or {}
        if corps.get("module") != "API" or corps.get("format") != "JSON":
            return self._erreur("module ou format invalide")
        if str(corps.get("idSite")) != self._id_site:
            return self._erreur("site inconnu ou sans accès")
        methode, plage = corps.get("method"), self._dates(corps.get("date"))
        if plage is None or plage[0] > plage[1]:
            return self._erreur("date invalide")
        if methode == "VisitsSummary.get" and corps.get("period") == "day":
            resultat: dict[str, Any] = {}
            courant = plage[0]
            while courant <= plage[1]:
                valeurs = self._jours.get(courant.isoformat())
                resultat[courant.isoformat()] = [] if not valeurs else {
                    "nb_visits": valeurs["visites"], "nb_uniq_visitors": valeurs["visiteurs"],
                    "nb_actions": valeurs["actions"], "bounce_count": valeurs["rebonds"],
                    "sum_visit_length": valeurs["duree_totale_s"]}
                courant += timedelta(days=1)
            return ReponseHttp(200, resultat)
        if methode == "Referrers.getWebsites" and corps.get("period") == "range":
            limite = str(corps.get("filter_limit", "-1"))
            cumul: dict[str, int] = {}
            courant = plage[0]
            while courant <= plage[1]:
                for label, visites in self._referents.get(courant.isoformat(), []):
                    cumul[label] = cumul.get(label, 0) + visites
                courant += timedelta(days=1)
            lignes = sorted(cumul.items(), key=lambda t: (-t[1], t[0]))
            if limite.isdigit():
                lignes = lignes[:int(limite)]
            return ReponseHttp(200, [{"label": label, "nb_visits": visites} for label, visites in lignes])
        return self._erreur("méthode ou période non disponible")


__all__ = ["DoubleMatomo", "DoubleUmami"]
