"""Base des DOUBLES de fournisseurs : des serveurs FICTIFS qui parlent la forme de l'API (chemins, paramètres,
corps, pagination,
statuts d'erreur) pour que le code du connecteur — construction de la requête, lecture de la réponse, traduction des
erreurs —
soit exercé en entier. Ce sont des doubles : ils ne prouvent rien sur le vrai service, dont la forme n'a jamais été
vérifiée
ici (aucun réseau).

Un double :
- vérifie l'hôte, le schéma d'authentification et la VALEUR du jeton attendu (jamais loggée ; un jeton faux donne 401) ;
- consigne chaque requête SANS authentification (`requetes`), pour qu'un test prouve ce qui a été demandé (méthode, URL,
  paramètres) et ce qui ne l'a jamais été (aucune écriture) ;
- rejoue un SCÉNARIO de pannes dans l'ordre : `429`, `429_sans_attente`, `503`, `401`, `403_permission`, `403_quota`,
  `delai`, `json_invalide`, `exception_secrete` (une exception dont le texte contient le jeton : le connecteur ne doit
  jamais la recopier), `trop_gros`, `ok`.

Module sans entrée-sortie : aucun module réseau n'est importé.
"""

from __future__ import annotations

import urllib.parse
from collections.abc import Iterable, Iterator, Mapping
from typing import Any, ClassVar

from .transport import Authentification, ErreurTransport, ReponseHttp, RequeteHttp

SCENARIOS = (
    "ok",
    "429",
    "429_sans_attente",
    "503",
    "401",
    "403_permission",
    "403_quota",
    "delai",
    "json_invalide",
    "exception_secrete",
    "trop_gros",
)


class ServeurFictif:
    """Transport de test. La classe fille déclare `HOTES` et implémente `traiter(requete, chemin) -> ReponseHttp`."""

    HOTES: ClassVar[frozenset[str]] = frozenset()
    SCHEMA_AUTH: ClassVar[str] = "bearer"
    NOM_AUTH: ClassVar[str | None] = None
    # Style d'erreur de quota : `google` (403 + motif) ou `plat` (429 seulement).
    STYLE_QUOTA: ClassVar[str] = "google"

    def __init__(
        self,
        *,
        jeton: str,
        scenario: Iterable[str] = (),
        hotes: Iterable[str] | None = None,
        annexes: Mapping[str, str] | None = None,
    ) -> None:
        inconnus = set(scenario) - set(SCENARIOS)
        if inconnus:
            raise ValueError(f"scénario inconnu : {sorted(inconnus)}")
        self._jeton = jeton
        self._annexes = dict(annexes or {})
        self._hotes = frozenset(hotes) if hotes is not None else self.HOTES
        self._scenario: Iterator[str] = iter(scenario)
        self.requetes: list[dict[str, Any]] = []

    # -- ce que le test lit -----------------------------------------------------------------------------------------
    @property
    def nombre_requetes(self) -> int:
        return len(self.requetes)

    def methodes(self) -> set[str]:
        return {r["methode"] for r in self.requetes}

    # -- transport ----------------------------------------------------------------------------------------------------
    def envoyer(self, requete: RequeteHttp, *, delai_s: float = 30.0) -> ReponseHttp:
        morceaux = urllib.parse.urlsplit(requete.url)
        self.requetes.append(
            {
                "methode": requete.methode,
                "url": requete.url,
                "chemin": morceaux.path,
                "params": dict(requete.params),
                "corps": dict(requete.corps or {}) or None,
                "schema_auth": requete.authentification.schema if requete.authentification else None,
            }
        )
        if morceaux.hostname not in self._hotes:
            raise ErreurTransport("hote_inconnu")
        panne = next(self._scenario, "ok")
        if panne == "delai":
            raise ErreurTransport("delai")
        if panne == "exception_secrete":
            auth = requete.authentification
            raise RuntimeError(f"échec de connexion avec le jeton {auth.valeur if auth else ''}")
        if panne == "429":
            return ReponseHttp(429, {"error": {"message": "trop de requêtes"}}, {"Retry-After": "17"})
        if panne == "429_sans_attente":
            return ReponseHttp(429, {"error": {"message": "trop de requêtes"}})
        if panne == "503":
            return ReponseHttp(503, {"error": {"message": "indisponible"}}, {"Retry-After": "5"})
        if panne == "401":
            return ReponseHttp(401, {"error": {"message": "jeton expiré"}})
        if panne == "403_permission":
            return ReponseHttp(403, {"error": {"errors": [{"reason": "forbidden"}], "status": "PERMISSION_DENIED"}})
        if panne == "403_quota":
            return ReponseHttp(
                403, {"error": {"errors": [{"reason": "rateLimitExceeded"}], "status": "RESOURCE_EXHAUSTED"}}
            )
        if panne == "json_invalide":
            return ReponseHttp(200, "ceci n'est pas un objet JSON")
        if panne == "trop_gros":
            return ReponseHttp(200, {"rows": ["x" * 1024] * 6000})
        if not self._authentifie(requete.authentification):
            return ReponseHttp(401, {"error": {"message": "authentification refusée"}})
        return self.traiter(requete, morceaux.path)

    def _authentifie(self, auth: Authentification | None) -> bool:
        if auth is None or auth.schema != self.SCHEMA_AUTH or auth.valeur != self._jeton:
            return False
        if self.NOM_AUTH is not None and auth.nom != self.NOM_AUTH:
            return False
        return all(dict(auth.annexes).get(nom) == valeur for nom, valeur in self._annexes.items())

    def traiter(self, requete: RequeteHttp, chemin: str) -> ReponseHttp:
        """Le comportement du fournisseur. À implémenter par la classe fille (jamais appelée sur la base)."""
        return ReponseHttp(404, {"error": {"message": "inconnu"}})


__all__ = ["SCENARIOS", "ServeurFictif"]
