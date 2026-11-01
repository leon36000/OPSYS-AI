"""Texte d'un document source : texte, markdown, HTML nettoyé ou PDF (worker existant), en pages.

- `texte` et `markdown` : UTF-8, tel quel (les `#` d'un markdown deviennent les sections des fragments).
- `html` : le texte VISIBLE seulement, avec les titres `<h1>`–`<h6>` rendus en `#`. Script, style, commentaire et
  élément masqué (`hidden`, `aria-hidden`, `display:none`, taille nulle…) sont retirés : le contenu masqué est le
  véhicule
  classique d'une consigne cachée à l'humain, jamais indexé ici.
- `pdf` : RÉUTILISE l'extraction de l'ingestion d'onboarding (`ingestion_onboarding.extraction_texte`) : worker natif
  isolé (pypdf dans bubblewrap) puis, pour un scan, l'OCR local SI son bundle est configuré. Sans isolation ou sans OCR,
  c'est un refus typé (`REJ-CONN-PDF-INDISPONIBLE` ou `REJ-CONN-PDF-REFUSE`), jamais un autre moteur à sa place ni le
  parsing du PDF dans le processus principal.

Aucun appel réseau. Le texte d'un document est une DONNÉE NON FIABLE : rien ici ne l'interprète.
"""

from __future__ import annotations

import hashlib
import html.parser
import re
import unicodedata
from collections.abc import Callable
from typing import Any

from .codes import (
    ENTREE_INVALIDE,
    PDF_INDISPONIBLE,
    PDF_REFUSE,
    TEXTE_TROP_LONG,
    TEXTE_VIDE,
    TYPE_NON_PRIS_EN_CHARGE,
    ErreurConnaissances,
)
from .modele import PDF_MAX_OCTETS, TEXTE_MAX, TYPES_SOURCE

ExtracteurPDF = Callable[[bytes], dict[str, Any]]
SEPARATEUR_PAGES = "\f"
# Caractères de contrôle (sauf \t \n ; le saut de page \f sépare les pages, jamais dans une page), invisibles et marques
# bidirectionnelles.
_INVISIBLES = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f­؜᠎​-‏‪-‮⁠-⁤⁦-⁯﻿￹-￻]")
_MASQUE_STYLE = re.compile(
    r"display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0(?:px|pt|em|%)?\s*(?:;|$)"
    r"|opacity\s*:\s*0(?:\.0+)?\s*(?:;|$)|text-indent\s*:\s*-\d{3,}|mso-hide\s*:\s*all|height\s*:\s*0(?:px)?\s*;?[^;]*overflow\s*:\s*hidden",
    re.IGNORECASE,
)


class _VisibleHtml(html.parser.HTMLParser):
    _IGNORES = frozenset({"script", "style", "head", "title", "template", "noscript", "iframe", "object", "embed",
                          "svg", "math", "meta", "link", "base", "form", "input", "button", "select", "textarea"})
    _VIDES = frozenset({"br", "hr", "img", "input", "meta", "link", "area", "base", "col", "embed", "source", "wbr"})
    _BLOCS = frozenset({"p", "div", "br", "tr", "ul", "ol", "table", "blockquote", "pre", "section", "article",
                        "header", "footer", "hr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "dd", "dt"})
    _TITRES = {"h1": "# ", "h2": "## ", "h3": "### ", "h4": "#### ", "h5": "##### ", "h6": "###### "}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._morceaux: list[str] = []
        self._pile: list[bool] = []
        self._masque = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._BLOCS and not self._masque:
            self._morceaux.append("\n\n" if tag in self._TITRES or tag == "p" else "\n")
        if tag in self._VIDES:
            return
        dico = {k.lower(): (v or "") for k, v in attrs}
        masque = (tag in self._IGNORES or "hidden" in dico or dico.get("aria-hidden") == "true"
                  or bool(_MASQUE_STYLE.search(dico.get("style", ""))) or dico.get("type", "").lower() == "hidden")
        self._pile.append(masque)
        self._masque += masque
        if not self._masque:
            if tag in self._TITRES:
                self._morceaux.append(self._TITRES[tag])
            elif tag == "li":
                self._morceaux.append("- ")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._VIDES:
            return
        if self._pile:
            self._masque -= self._pile.pop()
        if tag in self._BLOCS and not self._masque:
            self._morceaux.append("\n\n" if tag in self._TITRES or tag == "p" else "\n")

    def handle_data(self, data: str) -> None:
        if not self._masque:
            self._morceaux.append(data)

    def handle_comment(self, data: str) -> None:
        return

    def texte(self) -> str:
        return "".join(self._morceaux)


def nettoyer(texte: str) -> str:
    """NFC, fins de ligne `\\n`, invisibles retirés, espaces de fin de ligne retirés, lignes vides réduites à une."""
    texte = unicodedata.normalize("NFC", texte).replace("\r\n", "\n").replace("\r", "\n")
    texte = _INVISIBLES.sub("", texte)
    texte = re.sub(r"[ \t\v]+\n", "\n", texte)
    texte = re.sub(r"\n{3,}", "\n\n", texte)
    return texte.strip()


def _decoder(contenu: str | bytes) -> str:
    if isinstance(contenu, str):
        return contenu
    try:
        return contenu.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ErreurConnaissances(ENTREE_INVALIDE, "le contenu doit être de l'UTF-8 valide") from None


def _html_vers_texte(source: str) -> str:
    parseur = _VisibleHtml()
    try:
        parseur.feed(source)
        parseur.close()
    except (ValueError, RecursionError, AssertionError):
        raise ErreurConnaissances(ENTREE_INVALIDE, "HTML illisible") from None
    texte = parseur.texte()
    # Espaces internes d'une ligne : un HTML indenté ne doit pas produire de texte indenté.
    return "\n".join(re.sub(r"[ \t]+", " ", ligne).strip() for ligne in texte.split("\n"))


def _pdf(octets: bytes, extracteur_pdf: ExtracteurPDF | None) -> list[str]:
    from ..ingestion_onboarding import extraction_texte
    from ..ingestion_onboarding.codes import EchecEtape

    if len(octets) > PDF_MAX_OCTETS:
        raise ErreurConnaissances(TEXTE_TROP_LONG, f"PDF de plus de {PDF_MAX_OCTETS // (1024 * 1024)} Mo refusé")
    identifiant = hashlib.sha256(octets).hexdigest()[:32]
    try:
        resultat = extraction_texte.extraire("pdf", octets, document_id=identifiant, extracteur_pdf=extracteur_pdf)
    except EchecEtape as exc:
        code = PDF_INDISPONIBLE if exc.reprenable else PDF_REFUSE
        raise ErreurConnaissances(code, f"{exc.code} : {exc.detail}") from None
    if resultat.get("genre") != "texte":
        raise ErreurConnaissances(PDF_REFUSE, "le PDF n'a pas produit de texte")
    return [str(page.get("texte", "")) for page in sorted(resultat["pages"], key=lambda p: p["numero"])]


def extraire_pages(type_source: str, contenu: str | bytes, *, extracteur_pdf: ExtracteurPDF | None = None) -> list[str]:
    """Pages de texte nettoyé (au moins une, aucune vide à la fin). Refus typé sinon."""
    if type_source not in TYPES_SOURCE:
        raise ErreurConnaissances(TYPE_NON_PRIS_EN_CHARGE, f"type de source parmi {', '.join(TYPES_SOURCE)}")
    if type_source == "pdf":
        if not isinstance(contenu, bytes):
            raise ErreurConnaissances(ENTREE_INVALIDE, "un PDF se fournit en octets")
        brutes = _pdf(contenu, extracteur_pdf)
    else:
        if not isinstance(contenu, (str, bytes)):
            raise ErreurConnaissances(ENTREE_INVALIDE, "contenu texte attendu")
        texte = _decoder(contenu)
        if len(texte) > 4 * TEXTE_MAX:  # borne avant tout traitement (HTML démesuré, bombe de texte)
            raise ErreurConnaissances(TEXTE_TROP_LONG, f"plus de {4 * TEXTE_MAX} caractères reçus")
        brutes = [_html_vers_texte(texte) if type_source == "html" else texte]
    pages = [nettoyer(p) for p in brutes]
    while pages and not pages[-1]:
        pages.pop()
    if not pages or not any(pages):
        raise ErreurConnaissances(TEXTE_VIDE, "aucun texte exploitable dans la source")
    if sum(len(p) for p in pages) + len(pages) - 1 > TEXTE_MAX:
        raise ErreurConnaissances(TEXTE_TROP_LONG, f"plus de {TEXTE_MAX} caractères de texte")
    return pages
