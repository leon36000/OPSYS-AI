"""Le transport HTTP des connecteurs : une interface INJECTÉE, jamais un appel réseau dans la logique d'adaptateur.

`Transport.envoyer(requete) -> ReponseHttp` est la seule porte vers Internet. Les tests branchent des doubles
(faux serveurs Gmail et Graph, tests/fixtures/courriel_doubles.py). `TransportUrllib` est l'implémentation de
production : `urllib` de la bibliothèque standard, HTTPS seulement, AUCUNE redirection suivie (un jeton ne doit jamais
être renvoyé vers un autre hôte), corps de réponse borné. Elle est testée avec un `ouvrir` injecté ; elle n'a JAMAIS
été exécutée contre un vrai service (docs/architecture/CONNECTEURS-COURRIEL.md, « Plan de qualification »).

Un en-tête d'autorisation n'apparaît dans aucun `repr`, aucune exception, aucun journal.
"""

from __future__ import annotations

import dataclasses
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from typing import Protocol

CORPS_REPONSE_MAX = 64 * 1024 * 1024
_SENSIBLES = frozenset({"authorization", "proxy-authorization", "cookie", "x-goog-api-key"})


class ErreurTransport(Exception):
    """Panne de transport (délai, connexion, TLS). Le message est fixe : il ne recopie jamais l'exception d'origine,
    qui pourrait contenir une URL, un jeton ou un en-tête."""

    def __init__(self, nature: str = "reseau") -> None:
        super().__init__(f"transport : {nature}")
        self.nature = nature


@dataclasses.dataclass(frozen=True)
class RequeteHttp:
    methode: str
    url: str
    entetes: Mapping[str, str] = dataclasses.field(default_factory=dict)
    corps: bytes | None = dataclasses.field(default=None, repr=False)
    delai_s: float = 30.0

    def __repr__(self) -> str:
        entetes = {k: ("•••" if k.lower() in _SENSIBLES else v) for k, v in self.entetes.items()}
        return f"RequeteHttp({self.methode} {self.url.split('?', 1)[0]} entetes={entetes})"


@dataclasses.dataclass(frozen=True)
class ReponseHttp:
    statut: int
    entetes: Mapping[str, str] = dataclasses.field(default_factory=dict)
    corps: bytes = dataclasses.field(default=b"", repr=False)

    def entete(self, nom: str) -> str | None:
        nom = nom.lower()
        for cle, valeur in self.entetes.items():
            if cle.lower() == nom:
                return valeur
        return None


class Transport(Protocol):
    def envoyer(self, requete: RequeteHttp) -> ReponseHttp: ...


class _SansRedirection(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # noqa: ANN002, ANN003 — signature imposée par urllib
        return None


def _ouvrir_reel(requete: urllib.request.Request, delai_s: float):
    opener = urllib.request.build_opener(_SansRedirection())
    return opener.open(requete, timeout=delai_s)  # noqa: S310 — HTTPS seulement, vérifié par TransportUrllib


class TransportUrllib:
    """Transport de production (`urllib`). `ouvrir(requete_urllib, delai_s)` rend un objet réponse (`status`,
    `headers`, `read(n)`) ou lève `urllib.error.HTTPError` : injectable pour les tests."""

    def __init__(self, ouvrir: Callable[..., object] | None = None) -> None:
        self._ouvrir = ouvrir or _ouvrir_reel

    def envoyer(self, requete: RequeteHttp) -> ReponseHttp:
        if not requete.url.startswith("https://"):
            raise ErreurTransport("https_requis")
        brute = urllib.request.Request(requete.url, data=requete.corps, headers=dict(requete.entetes),
                                       method=requete.methode)
        try:
            reponse = self._ouvrir(brute, min(max(requete.delai_s, 1.0), 120.0))
        except urllib.error.HTTPError as exc:
            try:
                corps = exc.read(CORPS_REPONSE_MAX + 1) if exc.fp is not None else b""
            except OSError:
                corps = b""
            return ReponseHttp(exc.code, {k.lower(): v for k, v in (exc.headers or {}).items()}, corps)
        except TimeoutError:
            raise ErreurTransport("delai") from None
        except (urllib.error.URLError, OSError):
            raise ErreurTransport("connexion") from None
        try:
            corps = reponse.read(CORPS_REPONSE_MAX + 1)  # type: ignore[attr-defined]
            statut = int(reponse.status)  # type: ignore[attr-defined]
            entetes = {k.lower(): v for k, v in reponse.headers.items()}  # type: ignore[attr-defined]
        except (OSError, TimeoutError):
            raise ErreurTransport("lecture") from None
        finally:
            fermer = getattr(reponse, "close", None)
            if callable(fermer):
                fermer()
        if len(corps) > CORPS_REPONSE_MAX:
            raise ErreurTransport("reponse_trop_grosse")
        return ReponseHttp(statut, entetes, corps)
