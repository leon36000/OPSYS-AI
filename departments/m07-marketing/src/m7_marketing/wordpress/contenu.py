"""Garde-fou du contenu d'un article WordPress avant tout envoi au site (brouillon compris).

Le plugin assainit aussi (`wp_kses_post`) : ceci n'est que la première barrière, côté OPSYS, pour refuser tôt et
nommer la
règle. Deux familles de contrôles :

  - le CONTENU ACTIF : balises (`script`, `iframe`, `object`, `embed`, `form`, `style`, `link`, `meta`, `base`, `svg`…),
    attributs `on…` et adresses `javascript:` / `data:` dans un lien ou une source -> `REJ-WP-CONTENU-ACTIF` ;
  - le TEXTE VISIBLE (titre, extrait, texte extrait du HTML) : les familles du garde-fou du socle que M7 applique à tout
    texte public, sauf `lien` (un article porte des liens) et `longueur` (les limites d'un article sont celles de
    WordPress).

Un contenu généré par un modèle doit être marqué (`texte_genere_par_ia`), jamais présenté comme rédigé à la main.

Module pur : aucune entrée-sortie.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any

from opsys import garde_fou_texte as socle

REJ_CONTENU_ACTIF = "REJ-WP-CONTENU-ACTIF"
REJ_CHAMP = "REJ-WP-CHAMP"
REJ_IA_NON_DECLAREE = "REJ-WP-IA-NON-DECLAREE"

TITRE_MAX = 200
CONTENU_MAX = 100_000
EXTRAIT_MAX = 1000
SLUG_MAX = 100
STATUTS_BROUILLON = ("draft", "pending")
BALISES_ACTIVES = frozenset(
    {
        "script",
        "iframe",
        "object",
        "embed",
        "form",
        "style",
        "link",
        "meta",
        "base",
        "svg",
        "math",
        "applet",
        "frame",
        "frameset",
        "template",
        "noscript",
        "audio",
        "video",
        "source",
        "input",
        "button",
        "textarea",
        "select",
    }
)
_URL_ACTIVE = re.compile(r"\s*(?:javascript|vbscript|data)\s*:", re.IGNORECASE)
_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")

PROFIL_ARTICLE = socle.profil(
    "m7_article_wordpress",
    (
        socle.TEXTE_VIDE,
        socle.ADRESSE,
        socle.COORDONNEES,
        socle.NOM_CLIENT,
        socle.IDENTIFIANT_INTERNE,
        socle.PRIX_OFFRE,
        socle.CHIFFRE_NON_SOURCE,
        socle.GARANTIE_NON_VALIDEE,
        socle.PROMESSE_DE_DATE,
        socle.EXAGERATION,
    ),
)


class _Lecteur(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.texte: list[str] = []
        self.actif: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in BALISES_ACTIVES:
            self.actif.append(f"balise <{tag.lower()}>")
        for nom, valeur in attrs:
            nom = nom.lower()
            if nom.startswith("on"):
                self.actif.append(f"attribut {nom}")
            elif (
                nom in {"href", "src", "action", "formaction", "xlink:href", "srcset", "poster"}
                and valeur
                and _URL_ACTIVE.match(valeur)
            ):
                self.actif.append(f"adresse active dans {nom}")

    handle_startendtag = handle_starttag

    def handle_data(self, data: str) -> None:
        self.texte.append(data)


def lire_html(html: str) -> tuple[str, list[str]]:
    """(texte visible, constats de contenu actif)."""
    lecteur = _Lecteur()
    lecteur.feed(html)
    lecteur.close()
    return " ".join(lecteur.texte), lecteur.actif


def controler(donnees: dict[str, Any], contexte: socle.Contexte | None = None) -> list[dict[str, str]]:
    """Les refus `{code, chemin, detail}` d'un article `{type, titre, contenu, extrait, slug}` (types déjà validés)."""
    refus: list[dict[str, str]] = []

    def ajouter(code: str, chemin: str, detail: str) -> None:
        refus.append({"code": code, "chemin": chemin, "detail": detail})

    for nom, maximum in (("titre", TITRE_MAX), ("contenu", CONTENU_MAX), ("extrait", EXTRAIT_MAX), ("slug", SLUG_MAX)):
        valeur = donnees.get(nom)
        if not isinstance(valeur, str):
            ajouter(REJ_CHAMP, f"$.{nom}", "texte attendu")
        elif len(valeur) > maximum:
            ajouter(REJ_CHAMP, f"$.{nom}", f"{len(valeur)} caractères, {maximum} au plus")
    if refus:
        return refus
    if not donnees["titre"].strip():
        ajouter(REJ_CHAMP, "$.titre", "titre vide")
    if donnees["slug"] and not _SLUG.fullmatch(donnees["slug"]):
        ajouter(REJ_CHAMP, "$.slug", "minuscules, chiffres et tirets seulement")
    texte_contenu, actif = lire_html(donnees["contenu"])
    texte_extrait, actif_extrait = lire_html(donnees["extrait"])
    texte_titre, actif_titre = lire_html(donnees["titre"])
    for origine, constats in (("contenu", actif), ("extrait", actif_extrait), ("titre", actif_titre)):
        for constat in sorted(set(constats)):
            ajouter(REJ_CONTENU_ACTIF, f"$.{origine}", f"{constat} : le contenu actif n'a pas sa place dans un article")
    for origine, texte in (("titre", texte_titre), ("contenu", texte_contenu), ("extrait", texte_extrait)):
        if origine == "extrait" and not texte.strip():
            continue
        for violation in socle.controler(texte, PROFIL_ARTICLE, contexte):
            ajouter(violation.regle, f"$.{origine}", violation.detail)
    return refus
