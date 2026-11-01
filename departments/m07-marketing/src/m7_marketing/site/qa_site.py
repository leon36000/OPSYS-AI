"""Contrôle qualité automatisé d'un site statique généré (décision d'architecte r6, exigence 3).

Le contrôle lit les FICHIERS produits (`{chemin relatif: octets}`, ceux de `rendu_statique.rendre_site` ou de tout
autre adaptateur du même schéma) et le schéma dont ils viennent ; il ne lit ni réseau ni disque. Chaque contrôle
rend `ok` et ses constats (fichier, détail) ; le rapport est conforme si TOUS les contrôles le sont.

Contrôles (`CONTROLES`) : HTML bien formé (`html.parser`, pile d'éléments), garde-fou de page hérité (G-01 à G-18 de
`guardrail.py`), liens internes, ancres, images (texte de remplacement, dimensions déclarées et réelles), libellés de
formulaires, focus visible, contraste calculé de la charte, langues et `hreflang` réciproques, canonique et Open
Graph, JSON-LD valide et concordant avec la NAP et le texte visible, aucune ressource tierce, aucun JavaScript,
poids des pages, plan du site XML, `robots.txt`, pages 404.

Ce que ce contrôle n'est pas : un navigateur. Il ne mesure ni le rendu réel, ni Lighthouse, ni axe-core (non
installables ici, docs/sites-web.md) ; il vérifie statiquement ce qui peut l'être, sans jamais dire « accessible ».

Module pur : aucune entrée-sortie.
"""

from __future__ import annotations

import html.parser
import json
import posixpath
import re
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from typing import Any

from ..aeo.aeo_engine import TYPES_LOCALBUSINESS
from . import guardrail
from .rendu_statique import dimensions_image
from .schema_site import chemin_page, contrastes_charte

CONTROLES: tuple[tuple[str, str], ...] = (
    ("QA-HTML-BIEN-FORME", "HTML bien formé"),
    ("QA-GARDE-FOU-PAGE", "Garde-fou de page G-01 à G-18 (structure, accessibilité, JSON-LD)"),
    ("QA-LIENS-INTERNES", "Liens internes valides"),
    ("QA-ANCRES", "Ancres présentes dans la page visée"),
    ("QA-IMAGES", "Images : texte de remplacement et dimensions"),
    ("QA-FORMULAIRES", "Champs de formulaire étiquetés"),
    ("QA-FOCUS-VISIBLE", "Focus visible au clavier"),
    ("QA-CONTRASTE", "Contraste des couleurs de la charte (WCAG 2.2 AA)"),
    ("QA-LANGUES", "Langue des pages et hreflang réciproques"),
    ("QA-CANONIQUE-OG", "URL canonique et balises Open Graph"),
    ("QA-JSONLD", "JSON-LD valide et concordant avec la NAP"),
    ("QA-RESSOURCES-TIERCES", "Aucune ressource tierce"),
    ("QA-SCRIPTS", "Aucun JavaScript"),
    ("QA-POIDS", "Poids des pages"),
    ("QA-PLAN-DU-SITE", "Plan du site XML"),
    ("QA-ROBOTS", "robots.txt"),
    ("QA-404", "Pages 404"),
)
POIDS_HTML_MAX = 50_000  # octets d'un document HTML
POIDS_PAGE_MAX = 500_000  # octets d'une page avec ses images et son icône
CONSTATS_MAX = 50
_VIDES = frozenset({
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr",
})
_RESSOURCES = {("img", "src"), ("script", "src"), ("link", "href"), ("source", "src"), ("iframe", "src"),
               ("video", "src"), ("audio", "src"), ("embed", "src"), ("object", "data")}
_SITEMAP = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
_XHTML = "{http://www.w3.org/1999/xhtml}"


class _Analyse(html.parser.HTMLParser):
    """Tout ce que les contrôles lisent d'un document, en une passe."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.erreurs: list[str] = []
        self.doctype = False
        self.pile: list[str] = []
        self.ids: list[str] = []
        self.liens: list[tuple[str, str, str, dict[str, str]]] = []  # (balise, attribut, valeur, attributs)
        self.images: list[dict[str, str]] = []
        self.scripts: list[tuple[dict[str, str], str]] = []
        self.styles: list[str] = []
        self.attributs_style: list[str] = []
        self.metas: list[dict[str, str]] = []
        self.links: list[dict[str, str]] = []
        self.lang: str | None = None
        self.gestionnaires: list[str] = []
        self.champs: list[tuple[dict[str, str], bool]] = []  # (attributs, dans un <label>)
        self.labels_for: set[str] = set()
        self._labels = 0
        self._texte: list[str] = []
        self._dans: list[str] = []
        self._tampon: list[str] = []

    def handle_decl(self, decl: str) -> None:
        if decl.strip().lower() == "doctype html":
            self.doctype = True

    def _attributs(self, tag: str, attrs: list[tuple[str, str | None]]) -> dict[str, str]:
        noms = [k for k, _ in attrs]
        if len(set(noms)) != len(noms):
            self.erreurs.append(f"<{tag}> : attribut en double")
        return {k.lower(): (v or "") for k, v in attrs}

    def _ouvrir(self, tag: str, attrs: list[tuple[str, str | None]], auto_ferme: bool) -> None:
        a = self._attributs(tag, attrs)
        if tag == "html" and a.get("lang"):
            self.lang = a["lang"]
        if "id" in a:
            self.ids.append(a["id"])
        if "style" in a:
            self.attributs_style.append(a["style"])
        for nom, valeur in a.items():
            if nom.startswith("on"):
                self.gestionnaires.append(f"<{tag} {nom}>")
            if nom in ("href", "src", "data", "action", "formaction", "poster"):
                self.liens.append((tag, nom, valeur, a))
        if tag == "img":
            self.images.append(a)
        elif tag == "meta":
            self.metas.append(a)
        elif tag == "link":
            self.links.append(a)
        elif tag == "label":
            if "for" in a:
                self.labels_for.add(a["for"])
            if not auto_ferme:
                self._labels += 1
        elif tag in ("input", "select", "textarea"):
            self.champs.append((a, self._labels > 0))
        if tag in ("script", "style", "head", "title"):
            self._dans.append(tag)
            self._tampon = []
            if tag == "script":
                self.scripts.append((a, ""))
        if tag in _VIDES:
            return
        if auto_ferme:
            self.erreurs.append(f"<{tag}/> : un élément non vide ne se ferme pas lui-même")
            return
        self.pile.append(tag)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._ouvrir(tag, attrs, False)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._ouvrir(tag, attrs, True)

    def handle_endtag(self, tag: str) -> None:
        if tag in _VIDES:
            self.erreurs.append(f"</{tag}> : un élément vide n'a pas de balise de fermeture")
            return
        if tag == "label" and self._labels:
            self._labels -= 1
        if self._dans and self._dans[-1] == tag:
            self._dans.pop()
            contenu = "".join(self._tampon)
            if tag == "script":
                self.scripts[-1] = (self.scripts[-1][0], contenu)
            elif tag == "style":
                self.styles.append(contenu)
        if self.pile and self.pile[-1] == tag:
            self.pile.pop()
        elif tag in self.pile:
            ouverts = self.pile[self.pile.index(tag) + 1:]
            self.erreurs.append(f"</{tag}> ferme aussi des éléments ouverts : {ouverts}")
            del self.pile[self.pile.index(tag):]
        else:
            self.erreurs.append(f"</{tag}> sans ouverture correspondante")

    def handle_data(self, data: str) -> None:
        if self._dans:
            self._tampon.append(data)
        else:
            self._texte.append(data)

    def close(self) -> None:
        super().close()
        if not self.doctype:
            self.erreurs.append("<!DOCTYPE html> absent")
        if self.pile:
            self.erreurs.append(f"éléments non fermés : {self.pile}")

    @property
    def texte(self) -> str:
        return re.sub(r"\s+", " ", " ".join(self._texte)).strip()

    def meta(self, cle: str, valeur: str) -> str | None:
        return next((m.get("content") for m in self.metas if m.get(cle) == valeur), None)


def texte_visible(document: str) -> str:
    """Texte visible d'un document (hors en-tête, scripts et styles), espaces réduits."""
    analyse = _Analyse()
    analyse.feed(document)
    analyse.close()
    return analyse.texte


def chemin_de_fichier(fichier: str) -> str:
    """`services/index.html` -> `/services/` ; `index.html` -> `/` ; `404.html` -> `/404.html`."""
    if fichier == "index.html":
        return "/"
    if fichier.endswith("/index.html"):
        return "/" + fichier[: -len("index.html")]
    return "/" + fichier


def _resoudre(fichier: str, chemin: str) -> str:
    """Fichier visé par un chemin interne, relatif au document `fichier`."""
    if not chemin.startswith("/"):
        repertoire = posixpath.dirname(chemin_de_fichier(fichier))
        dossier = chemin.endswith("/")
        chemin = posixpath.normpath(posixpath.join(repertoire, chemin)) + ("/" if dossier else "")
    relatif = chemin.lstrip("/")
    return relatif + "index.html" if relatif == "" or relatif.endswith("/") else relatif


class _Rapport:
    def __init__(self) -> None:
        self.constats: dict[str, list[dict[str, str]]] = {code: [] for code, _ in CONTROLES}

    def __call__(self, code: str, fichier: str, detail: str) -> None:
        if len(self.constats[code]) < CONSTATS_MAX:
            self.constats[code].append({"fichier": fichier, "detail": detail})


def controler_site(fichiers: Mapping[str, bytes], schema: Mapping[str, Any]) -> dict[str, Any]:
    """Le rapport de contrôle qualité des `fichiers` générés depuis `schema`."""
    constat = _Rapport()
    domaine = schema["domaine"]
    origine = f"https://{domaine}"
    langues = tuple(schema["langues"])
    pages_html = sorted(f for f in fichiers if f.endswith(".html"))
    pages_404 = {chemin_page("", lg, langues).lstrip("/") + "404.html": lg for lg in langues}
    analyses: dict[str, _Analyse] = {}

    for fichier in pages_html:
        analyse = _Analyse()
        try:
            document = fichiers[fichier].decode("utf-8")
        except UnicodeDecodeError:
            constat("QA-HTML-BIEN-FORME", fichier, "le document n'est pas en UTF-8")
            continue
        analyse.feed(document)
        analyse.close()
        analyses[fichier] = analyse
        for erreur in analyse.erreurs:
            constat("QA-HTML-BIEN-FORME", fichier, erreur)
        doublons = sorted({i for i in analyse.ids if analyse.ids.count(i) > 1})
        if doublons:
            constat("QA-HTML-BIEN-FORME", fichier, f"id en double : {doublons}")
        for code, detail in guardrail.validate(document, content={"lang": analyse.lang} if analyse.lang else None):
            constat("QA-GARDE-FOU-PAGE", fichier, f"{code} : {detail}")

    for fichier, analyse in analyses.items():
        _controler_liens(constat, fichier, analyse, fichiers, analyses, origine)
        _controler_images(constat, fichier, analyse, fichiers, schema)
        _controler_formulaires(constat, fichier, analyse)
        _controler_focus(constat, fichier, analyse)
        _controler_scripts(constat, fichier, analyse)
        _controler_poids(constat, fichier, analyse, fichiers)
        indexable = fichier not in pages_404
        _controler_langue_et_canonique(constat, fichier, analyse, analyses, origine, langues, indexable)
        _controler_jsonld(constat, fichier, analyse, schema)

    for paire in contrastes_charte(schema["charte"]):
        if not paire["conforme_aa"]:
            constat(
                "QA-CONTRASTE", "charte",
                f"{paire['paire']} ({paire['usage']}) : {paire['ratio']}:1 < {paire['seuil_aa']}:1",
            )
    _controler_plan_du_site(constat, fichiers, analyses, origine, pages_404)
    _controler_robots(constat, fichiers, origine)
    for fichier, langue in pages_404.items():
        analyse = analyses.get(fichier)
        if analyse is None:
            constat("QA-404", fichier, "page 404 absente")
            continue
        if analyse.meta("name", "robots") != "noindex":
            constat("QA-404", fichier, "la page 404 doit porter <meta name=\"robots\" content=\"noindex\">")
        if analyse.lang != langue:
            constat("QA-404", fichier, f"langue {analyse.lang!r}, attendue {langue}")

    controles = [
        {"code": code, "titre": titre, "ok": not constat.constats[code], "constats": constat.constats[code]}
        for code, titre in CONTROLES
    ]
    return {
        "site_id": schema.get("site_id"),
        "conforme": all(c["ok"] for c in controles),
        "fichiers": len(fichiers),
        "pages": len(pages_html),
        "octets_total": sum(len(v) for v in fichiers.values()),
        "controles": controles,
        "contrastes": contrastes_charte(schema["charte"]),
    }


# Les navigateurs retirent blancs et caractères de contrôle avant de lire le schéma d'une URL (`java\tscript:`).
_SANS_BLANCS = re.compile("[\x00-\x20\x7f-\xa0\u1680\u180e\u2000-\u200f\u2028\u2029\u202f\u205f\u3000\ufeff]")


def _externe(valeur: str) -> bool:
    return valeur.startswith(("http://", "https://", "//"))


def _controler_liens(
    constat: _Rapport, fichier: str, analyse: _Analyse, fichiers: Mapping[str, bytes],
    analyses: Mapping[str, _Analyse], origine: str,
) -> None:
    for balise, attribut, valeur, attrs in analyse.liens:
        valeur = valeur.strip()
        bas = valeur.lower()
        if _SANS_BLANCS.sub("", bas).startswith("javascript:"):
            constat("QA-SCRIPTS", fichier, f"<{balise} {attribut}> en javascript:")
            continue
        if bas.startswith(("mailto:", "tel:")):
            if bas.startswith("tel:") and not re.fullmatch(r"tel:\+\d{8,15}", bas):
                constat("QA-LIENS-INTERNES", fichier, f"lien téléphone mal formé : {valeur}")
            continue
        ressource = (balise, attribut) in _RESSOURCES and not (
            balise == "link" and attrs.get("rel") in ("canonical", "alternate")
        )
        if _externe(valeur):
            if valeur.startswith(origine + "/") or valeur == origine:
                valeur = valeur[len(origine):] or "/"
            else:
                if ressource or balise == "link":
                    constat("QA-RESSOURCES-TIERCES", fichier, f"<{balise} {attribut}=\"{valeur}\"> hors du site")
                continue
        if bas.startswith("data:"):
            if ressource:
                constat("QA-RESSOURCES-TIERCES", fichier, f"<{balise}> en data: (ressource non vérifiable)")
            continue
        chemin, _, ancre = valeur.partition("#")
        cible = fichier if chemin == "" else _resoudre(fichier, chemin)
        if cible not in fichiers:
            constat("QA-LIENS-INTERNES", fichier, f"<{balise} {attribut}=\"{valeur}\"> : {cible} introuvable")
            continue
        if ancre:
            analyse_cible = analyses.get(cible)
            if analyse_cible is None or ancre not in analyse_cible.ids:
                constat("QA-ANCRES", fichier, f"ancre #{ancre} absente de {cible}")


def _controler_images(
    constat: _Rapport, fichier: str, analyse: _Analyse, fichiers: Mapping[str, bytes], schema: Mapping[str, Any]
) -> None:
    for image in analyse.images:
        src = image.get("src", "")
        if not image.get("alt", "").strip():
            constat("QA-IMAGES", fichier, f"<img src=\"{src}\"> sans texte de remplacement")
        largeur, hauteur = image.get("width", ""), image.get("height", "")
        if not (largeur.isdigit() and hauteur.isdigit()):
            constat("QA-IMAGES", fichier, f"<img src=\"{src}\"> sans width/height entiers (décalage de mise en page)")
            continue
        relatif = src.lstrip("/")
        if relatif in fichiers:
            reelles = dimensions_image(fichiers[relatif], relatif)
            if reelles is not None and reelles != (int(largeur), int(hauteur)):
                constat("QA-IMAGES", fichier, f"{src} : {reelles[0]}x{reelles[1]} réels, {largeur}x{hauteur} déclarés")


def _controler_formulaires(constat: _Rapport, fichier: str, analyse: _Analyse) -> None:
    for attrs, dans_label in analyse.champs:
        if attrs.get("type", "").lower() in ("hidden", "submit", "button", "reset", "image"):
            continue
        etiquete = (
            dans_label or attrs.get("id", "") in analyse.labels_for
            or attrs.get("aria-label", "").strip() or attrs.get("aria-labelledby", "").strip()
        )
        if not etiquete:
            constat("QA-FORMULAIRES", fichier, f"champ {attrs.get('name') or attrs.get('id') or '?'} sans libellé")


_FOCUS = re.compile(r":focus-visible[^{]*\{[^}]*outline\s*:\s*(\d+(?:\.\d+)?)(?:px|rem|em)\s+solid\s+#[0-9a-f]{3,6}",
                    re.IGNORECASE)
_SANS_CONTOUR = re.compile(r"outline\s*:\s*(?:none|0)\s*(?:;|\}|$)", re.IGNORECASE)


def _controler_focus(constat: _Rapport, fichier: str, analyse: _Analyse) -> None:
    css = "\n".join(analyse.styles)
    trouve = _FOCUS.search(css)
    if trouve is None or float(trouve.group(1)) < 2:
        constat("QA-FOCUS-VISIBLE", fichier, "aucune règle :focus-visible avec un contour plein de 2px au moins")
    if _SANS_CONTOUR.search(css) or any(_SANS_CONTOUR.search(s) for s in analyse.attributs_style):
        constat("QA-FOCUS-VISIBLE", fichier, "outline: none / 0 supprime l'indicateur de focus")


def _controler_scripts(constat: _Rapport, fichier: str, analyse: _Analyse) -> None:
    for attrs, _contenu in analyse.scripts:
        if attrs.get("type", "").lower() != "application/ld+json":
            constat("QA-SCRIPTS", fichier, f"<script type=\"{attrs.get('type', '')}\"> exécutable")
    for gestionnaire in analyse.gestionnaires:
        constat("QA-SCRIPTS", fichier, f"gestionnaire inline {gestionnaire}")
    for css in analyse.styles:
        if re.search(r"@import|url\(\s*[\"']?\s*(?:https?:|//)|@font-face", css, re.IGNORECASE):
            constat("QA-RESSOURCES-TIERCES", fichier, "feuille de style qui charge une ressource ou une police")


def _controler_poids(constat: _Rapport, fichier: str, analyse: _Analyse, fichiers: Mapping[str, bytes]) -> None:
    octets_html = len(fichiers[fichier])
    if octets_html > POIDS_HTML_MAX:
        constat("QA-POIDS", fichier, f"document de {octets_html} octets, {POIDS_HTML_MAX} au plus")
    ressources = {
        valeur.lstrip("/") for balise, attribut, valeur, attrs in analyse.liens
        if (balise, attribut) in (("img", "src"), ("link", "href"))
        and attrs.get("rel") not in ("canonical", "alternate")
        and valeur.lstrip("/") in fichiers
    }
    total = octets_html + sum(len(fichiers[r]) for r in ressources)
    if total > POIDS_PAGE_MAX:
        constat("QA-POIDS", fichier, f"page de {total} octets avec ses ressources, {POIDS_PAGE_MAX} au plus")


def _controler_langue_et_canonique(
    constat: _Rapport, fichier: str, analyse: _Analyse, analyses: Mapping[str, _Analyse], origine: str,
    langues: tuple[str, ...], indexable: bool,
) -> None:
    attendue = origine + chemin_de_fichier(fichier)
    if analyse.lang not in langues:
        constat("QA-LANGUES", fichier, f"lang={analyse.lang!r} hors des langues du site {list(langues)}")
    canonique = next((lk.get("href") for lk in analyse.links if lk.get("rel") == "canonical"), None)
    if canonique != attendue:
        constat("QA-CANONIQUE-OG", fichier, f"canonique {canonique!r}, attendue {attendue}")
    for propriete in ("og:title", "og:description", "og:url", "og:locale", "og:type", "og:site_name"):
        if not (analyse.meta("property", propriete) or "").strip():
            constat("QA-CANONIQUE-OG", fichier, f"{propriete} absent")
    if analyse.meta("property", "og:url") not in (None, canonique):
        constat("QA-CANONIQUE-OG", fichier, "og:url diffère de l'URL canonique")
    if analyse.lang and analyse.meta("property", "og:locale") != analyse.lang.replace("-", "_"):
        constat("QA-CANONIQUE-OG", fichier, f"og:locale ne correspond pas à lang={analyse.lang}")
    if not indexable:
        return
    alternes = {lk.get("hreflang"): lk.get("href", "") for lk in analyse.links if lk.get("rel") == "alternate"}
    for langue in (*langues, "x-default"):
        href = alternes.get(langue)
        if href is None:
            constat("QA-LANGUES", fichier, f"hreflang {langue} absent")
            continue
        if not href.startswith(origine + "/"):
            constat("QA-LANGUES", fichier, f"hreflang {langue} hors du site : {href}")
            continue
        cible = _resoudre(fichier, href[len(origine):])
        autre = analyses.get(cible)
        if autre is None:
            constat("QA-LANGUES", fichier, f"hreflang {langue} vise {cible}, introuvable")
            continue
        langue_cible = langues[0] if langue == "x-default" else langue
        if autre.lang != langue_cible:
            constat("QA-LANGUES", fichier, f"hreflang {langue} vise une page en {autre.lang}")
        retour = {lk.get("hreflang"): lk.get("href") for lk in autre.links if lk.get("rel") == "alternate"}
        if retour.get(analyse.lang) != attendue:
            constat("QA-LANGUES", fichier, f"hreflang {langue} non réciproque ({cible} ne renvoie pas ici)")
    if alternes.get(analyse.lang) not in (None, attendue):
        constat("QA-LANGUES", fichier, "le hreflang de la page elle-même diffère de sa canonique")


def _normal(texte: str) -> str:
    return re.sub(r"\s+", " ", texte).strip()


def _controler_jsonld(constat: _Rapport, fichier: str, analyse: _Analyse, schema: Mapping[str, Any]) -> None:
    blocs = [contenu for attrs, contenu in analyse.scripts if attrs.get("type", "").lower() == "application/ld+json"]
    if len(blocs) != 1:
        constat("QA-JSONLD", fichier, f"{len(blocs)} bloc(s) JSON-LD, exactement un attendu")
        return
    try:
        donnees = json.loads(blocs[0])
    except json.JSONDecodeError as exc:
        constat("QA-JSONLD", fichier, f"JSON-LD invalide : {exc.msg}")
        return
    if not isinstance(donnees, dict) or donnees.get("@context") != "https://schema.org":
        constat("QA-JSONLD", fichier, "objet JSON-LD de @context https://schema.org attendu")
        return
    graphe = donnees.get("@graph")
    if not isinstance(graphe, list):
        constat("QA-JSONLD", fichier, "@graph attendu")
        return
    entreprises = [n for n in graphe if isinstance(n, dict) and n.get("@type") in TYPES_LOCALBUSINESS]
    if len(entreprises) != 1:
        constat("QA-JSONLD", fichier, f"{len(entreprises)} nœud(s) LocalBusiness, exactement un attendu")
        return
    entreprise, texte = entreprises[0], analyse.texte
    nap, nom = schema["entreprise"]["nap"], schema["entreprise"]["nom"]
    adresse = nap["adresse"]
    attendu = {
        "name": nom, "telephone": nap["telephone"], "email": nap["courriel"],
        "address.streetAddress": adresse["rue"], "address.addressLocality": adresse["ville"],
        "address.addressRegion": adresse["region"], "address.postalCode": adresse["code_postal"],
        "address.addressCountry": adresse["pays"],
    }
    for cle, valeur in attendu.items():
        noeud: Any = entreprise
        for segment in cle.split("."):
            noeud = noeud.get(segment) if isinstance(noeud, dict) else None
        if noeud != valeur:
            constat("QA-JSONLD", fichier, f"{cle} = {noeud!r}, la NAP dit {valeur!r}")
    for visible in (nom, nap["telephone"], adresse["code_postal"]):
        if visible not in texte:
            constat("QA-JSONLD", fichier, f"NAP « {visible} » absente du texte visible de la page")
    for noeud in graphe:
        if not isinstance(noeud, dict):
            continue
        if noeud.get("@type") == "Service":
            if noeud.get("provider", {}).get("@id") != entreprise.get("@id"):
                constat("QA-JSONLD", fichier, f"Service {noeud.get('name')!r} sans provider vers l'entreprise")
            if _normal(str(noeud.get("name", ""))) not in texte:
                constat("QA-JSONLD", fichier, f"Service {noeud.get('name')!r} absent du texte visible")
        elif noeud.get("@type") == "FAQPage":
            for question in noeud.get("mainEntity", []):
                q = _normal(str(question.get("name", "")))
                r = _normal(str(question.get("acceptedAnswer", {}).get("text", "")))
                if not q or q not in texte or not r or r not in texte:
                    constat("QA-JSONLD", fichier, f"question FAQ {q!r} ou sa réponse absente du texte visible")


def _controler_plan_du_site(
    constat: _Rapport, fichiers: Mapping[str, bytes], analyses: Mapping[str, _Analyse], origine: str,
    pages_404: Mapping[str, str],
) -> None:
    contenu = fichiers.get("sitemap.xml")
    if contenu is None:
        constat("QA-PLAN-DU-SITE", "sitemap.xml", "plan du site absent")
        return
    try:
        racine = ET.fromstring(contenu)
    except ET.ParseError as exc:
        constat("QA-PLAN-DU-SITE", "sitemap.xml", f"XML mal formé : {exc}")
        return
    if racine.tag != f"{_SITEMAP}urlset":
        constat("QA-PLAN-DU-SITE", "sitemap.xml", "racine <urlset> du protocole sitemaps.org attendue")
        return
    listes: set[str] = set()
    for url in racine.findall(f"{_SITEMAP}url"):
        loc = (url.findtext(f"{_SITEMAP}loc") or "").strip()
        if not loc.startswith(origine + "/"):
            constat("QA-PLAN-DU-SITE", "sitemap.xml", f"<loc> hors du site : {loc}")
            continue
        cible = _resoudre("index.html", loc[len(origine):])
        listes.add(cible)
        if cible not in fichiers:
            constat("QA-PLAN-DU-SITE", "sitemap.xml", f"<loc> {loc} : {cible} introuvable")
        if not url.findall(f"{_XHTML}link"):
            constat("QA-PLAN-DU-SITE", "sitemap.xml", f"<loc> {loc} sans versions linguistiques (xhtml:link)")
    for fichier in analyses:
        if fichier not in pages_404 and fichier not in listes:
            constat("QA-PLAN-DU-SITE", "sitemap.xml", f"page indexable absente du plan : {fichier}")


def _controler_robots(constat: _Rapport, fichiers: Mapping[str, bytes], origine: str) -> None:
    contenu = fichiers.get("robots.txt")
    if contenu is None:
        constat("QA-ROBOTS", "robots.txt", "robots.txt absent")
        return
    lignes = [ligne.strip() for ligne in contenu.decode("utf-8", errors="replace").splitlines()]
    if "User-agent: *" not in lignes:
        constat("QA-ROBOTS", "robots.txt", "User-agent: * absent")
    if "Disallow: /" in lignes or "Allow: /" not in lignes:
        constat("QA-ROBOTS", "robots.txt", "le site doit rester explorable (Allow: /, sans Disallow: /)")
    if f"Sitemap: {origine}/sitemap.xml" not in lignes:
        constat("QA-ROBOTS", "robots.txt", f"Sitemap: {origine}/sitemap.xml absent")


def rapport_lisible(rapport: Mapping[str, Any]) -> str:
    """Le rapport en texte court, une ligne par contrôle, puis ses constats."""
    lignes = [
        f"Contrôle qualité du site {rapport['site_id']} : {'CONFORME' if rapport['conforme'] else 'NON CONFORME'}",
        f"{rapport['pages']} pages, {rapport['fichiers']} fichiers, {rapport['octets_total']} octets.",
    ]
    for controle in rapport["controles"]:
        etat = "OK" if controle["ok"] else f"ÉCHEC ({len(controle['constats'])})"
        lignes.append(f"- {controle['code']} — {controle['titre']} : {etat}")
        lignes.extend(f"    · {c['fichier']} : {c['detail']}" for c in controle["constats"])
    lignes.append("Contrastes de la charte :")
    lignes.extend(
        f"    · {p['paire']} ({p['usage']}) : {p['ratio']}:1 "
        f"(AA {p['seuil_aa']}:1 {'oui' if p['conforme_aa'] else 'non'})"
        for p in rapport["contrastes"]
    )
    return "\n".join(lignes)
