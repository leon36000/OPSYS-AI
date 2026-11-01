"""Doubles FICTIFS des API de rapports publicitaires (Google Ads REST, Meta Marketing API insights) : voir
`doubles_base.py`.

`DoubleGoogleAds` répond à `POST /v17/customers/{id}/googleAds:search` : il lit la requête GAQL (SELECT … FROM
customer|campaign … WHERE segments.date BETWEEN 'a' AND 'b'), refuse ce qui n'est pas une lecture (400), exige le
jeton de développeur (annexe `developer-token`), pagine par `pageSize`/`nextPageToken`, rend `costMicros` en TEXTE
entier et la monnaie du compte. Une méthode d'écriture (`:mutate`) n'existe pas chez lui : 404 ; le journal des
requêtes le prouve si le connecteur l'appelait.

`DoubleMetaAds` répond à `GET /v21.0/act_N/insights` : `level`, `time_increment=1`, `time_range` en JSON, `fields`,
`limit`, `after` ; `spend` en texte décimal ; `actions` ABSENT quand il n'y en a aucune ; `paging.cursors.after` et
`paging.next` (URL complète, éventuellement HOSTILE pour prouver qu'elle n'est jamais suivie) ; limite de débit au
style Meta (HTTP 400 +
code 17) et jeton refusé (HTTP 400 + code 190). Données FICTIVES seulement.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import date
from typing import Any

from .doubles_base import ServeurFictif
from .transport import ReponseHttp, RequeteHttp

# jour -> (cost_micros, impressions, clics, conversions)
JourGoogle = tuple[int, int, int, float]
_GAQL = re.compile(r"^SELECT (?P<champs>.+?) FROM (?P<ressource>customer|campaign) WHERE segments\.date BETWEEN "
                   r"'(?P<d>\d{4}-\d{2}-\d{2})' AND '(?P<f>\d{4}-\d{2}-\d{2})'(?: ORDER BY [a-z., ]+)?$")


class DoubleGoogleAds(ServeurFictif):
    HOTES = frozenset({"googleads.googleapis.com"})

    def __init__(self, *, client: str, jeton: str, jeton_dev: str, devise: str = "CAD",
                 jours: Mapping[str, JourGoogle] | None = None,
                 campagnes: Mapping[str, Mapping[str, Any]] | None = None, **options: Any) -> None:
        """`jours` : total de compte par jour. `campagnes` : id → {"nom": str, "jours": {jour: JourGoogle}}."""
        super().__init__(jeton=jeton, annexes={"developer-token": jeton_dev}, **options)
        self._client, self._devise = client, devise
        self._jours = dict(jours or {})
        self._campagnes = {k: {"nom": v["nom"], "jours": dict(v["jours"])} for k, v in (campagnes or {}).items()}

    def reviser_jour(self, jour: str, cost_micros: int) -> None:
        _, i, c, v = self._jours[jour]
        self._jours[jour] = (cost_micros, i, c, v)

    def traiter(self, requete: RequeteHttp, chemin: str) -> ReponseHttp:
        attendu = f"/v17/customers/{self._client}/googleAds:search"
        if requete.methode != "POST" or chemin != attendu:
            return ReponseHttp(404, {"error": {"message": "méthode ou client inconnu"}})
        corps = requete.corps or {}
        requete_gaql, taille = corps.get("query"), corps.get("pageSize", 1000)
        jeton_page = corps.get("pageToken")
        correspond = _GAQL.fullmatch(requete_gaql) if isinstance(requete_gaql, str) else None
        if (correspond is None or type(taille) is not int or not 1 <= taille <= 10000
                or (jeton_page is not None and not (isinstance(jeton_page, str) and re.fullmatch(r"p[0-9]+",
                    jeton_page)))
                or set(corps) - {"query", "pageSize", "pageToken"}):
            return ReponseHttp(400, {"error": {"code": 400, "status": "INVALID_ARGUMENT",
                                               "message": "requête GAQL invalide"}})
        try:
            debut, fin = date.fromisoformat(correspond["d"]), date.fromisoformat(correspond["f"])
        except ValueError:
            return ReponseHttp(400, {"error": {"code": 400, "status": "INVALID_ARGUMENT", "message": "date invalide"}})
        lignes: list[dict[str, Any]] = []
        if correspond["ressource"] == "customer":
            sources = [(jour, v, None, None) for jour, v in sorted(self._jours.items())]
        else:
            sources = sorted(((jour, v, cid, c["nom"]) for cid, c in self._campagnes.items()
                              for jour, v in c["jours"].items()), key=lambda t: (t[0], t[2]))
        for jour, (micros, impressions, clics, conversions), cid, nom in sources:
            if not debut <= date.fromisoformat(jour) <= fin:
                continue
            ligne: dict[str, Any] = {
                "customer": {"currencyCode": self._devise},
                "metrics": {"costMicros": str(micros), "impressions": str(impressions), "clicks": str(clics),
                            "conversions": conversions},
                "segments": {"date": jour},
            }
            if cid is not None:
                ligne["campaign"] = {"id": cid, "name": nom, "status": "ENABLED"}
            lignes.append(ligne)
        depart = int(jeton_page[1:]) if jeton_page else 0
        page = lignes[depart:depart + taille]
        reponse: dict[str, Any] = {"results": page, "totalResultsCount": str(len(lignes))}
        if depart + taille < len(lignes):
            reponse["nextPageToken"] = f"p{depart + taille}"
        return ReponseHttp(200, reponse)


class DoubleMetaAds(ServeurFictif):
    HOTES = frozenset({"graph.facebook.com"})

    def __init__(self, *, compte: str, jeton: str, devise: str = "CAD", jours: Mapping[str, tuple] | None = None,
                 campagnes: Mapping[str, Mapping[str, Any]] | None = None, url_suivante_hostile: bool = False,
                 limite_apres: int | None = None, jeton_expire: bool = False, **options: Any) -> None:
        """`jours` : jour → (spend texte, impressions, clics, actions | None). `campagnes` : id → {"nom", "jours": …}.
        `limite_apres` : après N requêtes réussies, HTTP 400 code 17. `jeton_expire` : HTTP 400 code 190."""
        super().__init__(jeton=jeton, **options)
        self._compte, self._devise = compte, devise
        self._jours = dict(jours or {})
        self._campagnes = {k: {"nom": v["nom"], "jours": dict(v["jours"])} for k, v in (campagnes or {}).items()}
        self._hostile, self._limite_apres, self._expire = url_suivante_hostile, limite_apres, jeton_expire
        self._reussies = 0

    def traiter(self, requete: RequeteHttp, chemin: str) -> ReponseHttp:
        if self._expire:
            return ReponseHttp(400, {"error": {"message": "jeton invalide", "type": "OAuthException", "code": 190}})
        if self._limite_apres is not None and self._reussies >= self._limite_apres:
            return ReponseHttp(400, {"error": {"message": "limite de débit", "type": "OAuthException", "code": 17}},
                               {"Retry-After": "120"})
        if requete.methode != "GET" or chemin != f"/v21.0/{self._compte}/insights":
            return ReponseHttp(404, {"error": {"message": "inconnu", "code": 803}})
        p = requete.params
        try:
            niveau, limite = p["level"], int(p.get("limit", "25"))
            plage = json.loads(p["time_range"])
            debut, fin = date.fromisoformat(plage["since"]), date.fromisoformat(plage["until"])
            depart = int(p["after"].removeprefix("cur-")) if "after" in p else 0
        except (KeyError, ValueError, TypeError):
            return ReponseHttp(400, {"error": {"message": "paramètre invalide", "type": "OAuthException", "code": 100}})
        if (niveau not in ("account", "campaign") or p.get("time_increment") != "1" or not 1 <= limite <= 500
                or debut > fin or depart < 0 or "fields" not in p):
            return ReponseHttp(400, {"error": {"message": "paramètre invalide", "type": "OAuthException", "code": 100}})
        sources = ([(jour, v, None, None) for jour, v in sorted(self._jours.items())] if niveau == "account" else
                   sorted(((jour, v, cid, c["nom"]) for cid, c in self._campagnes.items()
                           for jour, v in c["jours"].items()), key=lambda t: (t[0], t[2])))
        lignes = []
        for jour, (depense, impressions, clics, actions), cid, nom in sources:
            if not debut <= date.fromisoformat(jour) <= fin:
                continue
            ligne: dict[str, Any] = {"spend": depense, "impressions": str(impressions), "clicks": str(clics),
                                     "account_currency": self._devise, "date_start": jour, "date_stop": jour}
            if actions is not None:
                ligne["actions"] = [{"action_type": t, "value": str(v)} for t, v in actions]
            if cid is not None:
                ligne["campaign_id"], ligne["campaign_name"] = cid, nom
            lignes.append(ligne)
        page = lignes[depart:depart + limite]
        corps: dict[str, Any] = {"data": page}
        if depart + limite < len(lignes):
            apres = f"cur-{depart + limite}"
            suite = ("https://exfiltration.example/capture?token=" if self._hostile
                     else f"https://graph.facebook.com/v21.0/{self._compte}/insights?after=") + apres
            corps["paging"] = {"cursors": {"before": f"cur-{depart}", "after": apres}, "next": suite}
        else:
            corps["paging"] = {"cursors": {"before": f"cur-{depart}", "after": f"cur-{depart + len(page)}"}}
        self._reussies += 1
        return ReponseHttp(200, corps)


__all__ = ["DoubleGoogleAds", "DoubleMetaAds", "JourGoogle"]
