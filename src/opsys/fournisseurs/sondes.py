"""Sondes de test de connexion des fournisseurs.

`sonder` choisit la sonde selon le point d'accès :
- `https://…` ou `http://127.0.0.1…` : requête GET bornée (délai ≤ 10 s, aucune redirection suivie pour ne
  jamais renvoyer une clé vers un autre hôte) ; une base `…/v1` compatible OpenAI est sondée sur `/v1/models` ;
- `module:<nom>` : le module Python est-il installable/importable ici (`importlib.util.find_spec`, sans import) ;
- `binaire:<nom>` : l'exécutable est-il dans le PATH ;
- `appareil:<nom>` : rendu sur l'appareil de l'utilisateur, non vérifiable par le serveur.

En QA, aucune sonde réseau réelle : les tests injectent `ouvrir` (ou une sonde simulée complète).
Le détail rendu est court, fixe et masqué ; il ne contient jamais l'en-tête d'autorisation.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import shutil
import socket
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from ..secrets_coffre import masquage
from .modele import Fournisseur

STATUTS = ("succes", "echec", "delai", "non_verifiable")
DELAI_MAX_S = 10.0


@dataclasses.dataclass(frozen=True)
class ResultatSonde:
    statut: str
    detail: str
    latence_ms: int | None = None

    def __post_init__(self) -> None:
        if self.statut not in STATUTS:
            raise ValueError("statut de sonde inconnu")

    def vers_json(self) -> dict[str, Any]:
        return {"statut": self.statut, "detail": masquage.masquer_texte(self.detail)[:200],
                "latence_ms": self.latence_ms}


Sonde = Callable[[Fournisseur, "str | None", float], ResultatSonde]


class _SansRedirection(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        raise urllib.error.HTTPError(args[1].full_url if len(args) > 1 else "", 399, "redirection refusée", None,
                                     None)


def _ouvrir_reel(requete: urllib.request.Request, delai_s: float) -> int:
    opener = urllib.request.build_opener(_SansRedirection())
    with opener.open(requete, timeout=delai_s) as reponse:  # noqa: S310 — schéma validé par modele.Fournisseur
        return reponse.status


class SondeHttp:
    """GET borné ; `ouvrir(requete, delai_s) -> code HTTP` est injectable (tests : aucun réseau)."""

    def __init__(self, ouvrir: Callable[[urllib.request.Request, float], int] | None = None) -> None:
        self._ouvrir = ouvrir or _ouvrir_reel

    def __call__(self, fournisseur: Fournisseur, secret: str | None, delai_s: float) -> ResultatSonde:
        url = fournisseur.point_acces or ""
        cible = url.rstrip("/") + "/models" if url.rstrip("/").endswith("/v1") else url
        entetes = {"User-Agent": "opsys-sonde/1", "Accept": "application/json"}
        if secret is not None:
            entetes["Authorization"] = f"Bearer {secret}"
        requete = urllib.request.Request(cible, headers=entetes, method="GET")
        debut = time.monotonic()
        try:
            code = self._ouvrir(requete, min(max(delai_s, 0.1), DELAI_MAX_S))
        except urllib.error.HTTPError as exc:
            latence = int((time.monotonic() - debut) * 1000)
            if exc.code in (401, 403):
                return ResultatSonde("echec", f"authentification refusée (HTTP {exc.code})", latence)
            if exc.code == 399:
                return ResultatSonde("echec", "redirection refusée", latence)
            return ResultatSonde("echec", f"HTTP {exc.code}", latence)
        except TimeoutError:
            return ResultatSonde("delai", f"aucune réponse en {delai_s:g} s", None)
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                return ResultatSonde("delai", f"aucune réponse en {delai_s:g} s", None)
            return ResultatSonde("echec", "hôte injoignable", None)
        except OSError:
            return ResultatSonde("echec", "erreur réseau", None)
        latence = int((time.monotonic() - debut) * 1000)
        if 200 <= code < 300:
            return ResultatSonde("succes", f"HTTP {code}", latence)
        return ResultatSonde("echec", f"HTTP {code}", latence)


def sonde_locale(fournisseur: Fournisseur) -> ResultatSonde:
    point = fournisseur.point_acces or ""
    if point.startswith("module:"):
        nom = point.removeprefix("module:")
        try:
            trouve = importlib.util.find_spec(nom) is not None
        except (ImportError, ValueError):
            trouve = False
        return ResultatSonde("succes" if trouve else "echec",
                             f"module {nom} {'présent' if trouve else 'absent'} sur ce serveur")
    if point.startswith("binaire:"):
        nom = point.removeprefix("binaire:")
        trouve = shutil.which(nom) is not None
        return ResultatSonde("succes" if trouve else "echec", f"exécutable {nom} {'présent' if trouve else 'absent'}")
    if point.startswith("passerelle:"):
        return ResultatSonde("non_verifiable",
                             "joint par la passerelle de modèles : tester depuis « Modèles et rôles »")
    if point.startswith("appareil:"):
        return ResultatSonde("non_verifiable", "rendu sur l'appareil de l'utilisateur : non vérifiable par le serveur")
    return ResultatSonde("echec", "point d'accès non configuré")


def sonder(fournisseur: Fournisseur, secret: str | None, delai_s: float, *, http: Sonde | None = None) -> ResultatSonde:
    point = fournisseur.point_acces or ""
    if point.startswith(("https://", "http://")):
        return (http or SondeHttp())(fournisseur, secret, delai_s)
    return sonde_locale(fournisseur)
