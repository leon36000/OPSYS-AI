"""Double FICTIF d'un site public : le transport de TEST de la veille (voir `collecte.py`).

Il sert des pages, des `robots.txt`, des plans de site et les accidents d'un vrai site (redirections, y compris hors
domaine,
401, 403, 404, 429, 500, délai dépassé, corps géant, mauvais type de contenu, page piégée par une injection de
consigne, page
qui porte le courriel et le téléphone d'un tiers). Il ne suit AUCUNE redirection et NE REÇOIT que l'URL et l'agent :
c'est
exactement le contrat du port. Il journalise chaque requête (`requetes`) pour qu'un test prouve l'ORDRE (robots avant
page) et
l'absence de toute requête interdite.

Données FICTIVES seulement (domaines en `.example`). Module sans entrée-sortie.
"""

from __future__ import annotations

import html as html_module
import urllib.parse
from collections.abc import Iterable, Mapping
from typing import Any

from .collecte import ErreurTransportPublic, ReponsePublique

HTML = "text/html; charset=utf-8"
XML = "application/xml"


def page_html(*, titre: str | None = "Services Horizon : entretien extérieur à Laval",
    description: str | None = None,
              h1: Iterable[str] = ("Entretien extérieur à Laval",), corps: str = "", langue: str | None = "fr-CA",
              canonical: str | None = None, ld: Iterable[str] = (), liens: Iterable[str] = ()) -> bytes:
    """Une page HTML minimale, assemblée à la main. Les textes sont ÉCHAPPÉS comme le ferait un site : un `<` du
    texte reste du
    texte."""
    echapper = html_module.escape
    titre = echapper(titre) if titre is not None else None
    description = echapper(description, quote=True) if description is not None else None
    h1 = [echapper(t) for t in h1]
    corps = echapper(corps)
    tete = []
    if titre is not None:
        tete.append(f"<title>{titre}</title>")
    if description is not None:
        tete.append(f'<meta name="description" content="{description}">')
    if canonical is not None:
        tete.append(f'<link rel="canonical" href="{canonical}">')
    for bloc in ld:
        tete.append(f'<script type="application/ld+json">{bloc}</script>')
    lang = f' lang="{langue}"' if langue else ""
    corps_html = "".join(f"<h1>{t}</h1>" for t in h1) + f"<p>{corps}</p>" + "".join(
        f'<a href="{lien}">lien</a>' for lien in liens)
    return f"<!doctype html><html{lang}><head>{''.join(tete)}</head><body>{corps_html}</body></html>".encode()


def plan_de_site(urls: Iterable[str]) -> bytes:
    return ("<?xml version=\"1.0\" encoding=\"UTF-8\"?><urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">"
            + "".join(f"<url><loc>{u}</loc></url>" for u in urls) + "</urlset>").encode()


class DoubleSitePublic:
    """Transport de test. `ajouter(url, ...)` déclare une réponse ; une URL inconnue répond 404."""

    def __init__(self) -> None:
        self._reponses: dict[str, list[Any]] = {}
        self.requetes: list[dict[str, str]] = []

    # -- déclaration ---------------------------------------------------------------------------------------------------
    def ajouter(self, url: str, corps: bytes | str = b"", *, statut: int = 200, type_contenu: str | None = HTML,
                en_tetes: Mapping[str, str] | None = None, delai: bool = False, exception: Exception | None = None,
                suite: bool = False) -> None:
        """Déclare la réponse d'une URL. Une nouvelle déclaration REMPLACE la précédente ; avec `suite=True` elle
        s'y AJOUTE
        (la première une fois, puis la suivante : un 429 puis un succès)."""
        octets = corps.encode("utf-8") if isinstance(corps, str) else corps
        entetes = {k.lower(): v for k, v in (en_tetes or {}).items()}
        if type_contenu is not None:
            entetes.setdefault("content-type", type_contenu)
        element = ("delai" if delai else exception, ReponsePublique(statut, entetes, octets, url))
        if suite:
            self._reponses.setdefault(url, []).append(element)
        else:
            self._reponses[url] = [element]

    def robots(self, hote: str, texte: str, *, statut: int = 200) -> None:
        self.ajouter(f"https://{hote}/robots.txt", texte, statut=statut, type_contenu="text/plain")

    def redirection(self, url: str, vers: str, *, statut: int = 301) -> None:
        self.ajouter(url, b"", statut=statut, type_contenu=None, en_tetes={"Location": vers})

    # -- ce que le test lit --------------------------------------------------------------------------------------------
    def urls_demandees(self) -> list[str]:
        return [r["url"] for r in self.requetes]

    def pages_demandees(self) -> list[str]:
        return [u for u in self.urls_demandees() if not u.endswith("/robots.txt")]

    # -- transport -----------------------------------------------------------------------------------------------------
    def obtenir(self, url: str, agent_utilisateur: str, delai_s: float) -> ReponsePublique:
        self.requetes.append({"url": url, "agent": agent_utilisateur})
        if urllib.parse.urlsplit(url).scheme != "https":
            raise ErreurTransportPublic("schema")
        suite = self._reponses.get(url)
        if not suite:
            return ReponsePublique(404, {"content-type": "text/plain"}, b"introuvable", url)
        panne, reponse = suite[0] if len(suite) == 1 else suite.pop(0)
        if panne == "delai":
            raise ErreurTransportPublic("delai")
        if isinstance(panne, Exception):
            raise panne
        return reponse


__all__ = ["DoubleSitePublic", "HTML", "XML", "page_html", "plan_de_site"]
