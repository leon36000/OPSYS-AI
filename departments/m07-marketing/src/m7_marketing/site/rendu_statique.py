"""Premier adaptateur de rendu du schéma de site (`schema_site.py`) : HTML statique en Python pur (décision r6).

Même schéma -> mêmes octets : aucune horloge (l'année du pied de page et `lastmod` viennent de `revision.date`), aucun
ordre de dictionnaire implicite, aucune ressource tierce. Le rendu ne valide pas : il reçoit un schéma déjà accepté
par `schema_site.valider_schema` et `garde_contenu.controler_contenu` (voir `service.py`), et des actifs déjà acceptés
par `verifier_actifs`. Astro sera un second adaptateur du même schéma ; ce module en est la référence de sortie.

Sortie (`rendre_site`) : `{chemin relatif: octets}` — pages en URL propres (`services/index.html` pour `/services/`),
français à la racine, anglais sous `/en/`, `404.html` et `en/404.html`, `sitemap.xml`, `robots.txt`, `favicon.svg`
(dérivé de la charte) et les images déclarées. Chaque page porte `lang`, `hreflang`, canonique, Open Graph, une
politique CSP stricte (style par empreinte, aucun script exécutable), et un seul bloc JSON-LD `@graph`
(LocalBusiness/HomeAndConstructionBusiness, Service, FAQPage) tiré de la NAP structurée.

Module pur : aucune entrée-sortie.
"""

from __future__ import annotations

import base64
import hashlib
import html
import json
import re
import struct
from collections.abc import Mapping, Sequence
from typing import Any
from xml.etree import ElementTree

from .schema_site import chemin_page, refus

REJ_IMAGE_ABSENTE = "REJ-SITE-IMAGE-ABSENTE"
REJ_IMAGE_FORMAT = "REJ-SITE-IMAGE-FORMAT"
REJ_IMAGE_DIMENSIONS = "REJ-SITE-IMAGE-DIMENSIONS"
REJ_IMAGE_ACTIVE = "REJ-SITE-IMAGE-SVG-ACTIF"

_TEXTES_UI: dict[str, dict[str, str]] = {
    "fr-CA": {
        "aller_contenu": "Aller au contenu",
        "nav_principale": "Navigation principale",
        "nav_legale": "Liens légaux",
        "nav_langue": "Langue",
        "nom_langue": "Français",
        "consentement": "Publié avec le consentement de son auteur.",
        "en_savoir_plus": "En savoir plus : {nom}",
        "telephone": "Téléphone",
        "courriel": "Courriel",
        "adresse": "Adresse",
        "heures": "Heures d'ouverture",
        "zones": "Zones desservies",
        "identification": "Identification de l'entreprise",
        "rbq": "Licence RBQ",
        "responsable_rp": "Responsable de la protection des renseignements personnels",
        "sans_traceur": (
            "Ce site n'utilise aucun témoin (cookie) ni traceur non essentiel et ne charge aucune ressource externe."
        ),
        "droits": "Tous droits réservés.",
        "introuvable_titre": "Page introuvable",
        "introuvable_texte": "La page demandée n'existe pas ou a été déplacée.",
        "introuvable_description": "La page demandée n'existe pas ou a été déplacée. Revenez à l'accueil du site.",
        "retour_accueil": "Retour à l'accueil",
        "heure": "{h} h {m}",
        "a": "à",
        "dp": " : ",
        "og_locale": "fr_CA",
    },
    "en-CA": {
        "aller_contenu": "Skip to content",
        "nav_principale": "Main navigation",
        "nav_legale": "Legal links",
        "nav_langue": "Language",
        "nom_langue": "English",
        "consentement": "Published with the author's consent.",
        "en_savoir_plus": "Learn more: {nom}",
        "telephone": "Phone",
        "courriel": "Email",
        "adresse": "Address",
        "heures": "Opening hours",
        "zones": "Service areas",
        "identification": "Company identification",
        "rbq": "RBQ licence",
        "responsable_rp": "Person in charge of the protection of personal information",
        "sans_traceur": "This site uses no non-essential cookie or tracker and loads no external resource.",
        "droits": "All rights reserved.",
        "introuvable_titre": "Page not found",
        "introuvable_texte": "The requested page does not exist or has moved.",
        "introuvable_description": "The requested page does not exist or has moved. Go back to the home page.",
        "retour_accueil": "Back to the home page",
        "heure": "{h}:{m}",
        "a": "to",
        "dp": ": ",
        "og_locale": "en_CA",
    },
}
_JOURS = {
    "fr-CA": {"Mo": "lundi", "Tu": "mardi", "We": "mercredi", "Th": "jeudi", "Fr": "vendredi", "Sa": "samedi",
              "Su": "dimanche"},
    "en-CA": {"Mo": "Monday", "Tu": "Tuesday", "We": "Wednesday", "Th": "Thursday", "Fr": "Friday", "Sa": "Saturday",
              "Su": "Sunday"},
}
_JOURS_SCHEMA = {"Mo": "Monday", "Tu": "Tuesday", "We": "Wednesday", "Th": "Thursday", "Fr": "Friday",
                 "Sa": "Saturday", "Su": "Sunday"}
TITRE_PAGE_MAX = 70

_CSS = """\
*, *::before, *::after { box-sizing: border-box; }
body { margin: 0; font-family: system-ui, -apple-system, "Segoe UI", Roboto, Arial, sans-serif; font-size: 1.0625rem; \
line-height: 1.6; background-color: {fond}; color: {texte}; }
header { background-color: {primaire}; color: {sur_primaire}; padding: 1rem; }
nav { background-color: {primaire}; color: {sur_primaire}; }
footer { background-color: {primaire}; color: {sur_primaire}; padding: 1.5rem 1rem; margin-top: 3rem; }
a { color: {primaire}; text-underline-offset: 0.15em; }
header a { color: {sur_primaire}; }
nav a { color: {sur_primaire}; }
footer a { color: {sur_primaire}; }
a:focus-visible { outline: 3px solid {focus}; outline-offset: 2px; }
.skip-link { position: absolute; left: -10000px; top: auto; }
.skip-link:focus { position: static; display: inline-block; padding: 0.5rem 1rem; background-color: {fond}; \
color: {texte}; }
.marque { font-size: 1.25rem; font-weight: 700; margin: 0 0 0.5rem; }
nav ul, .langue { list-style: none; margin: 0.5rem 0 0; padding: 0; display: flex; flex-wrap: wrap; \
gap: 0.25rem 1.25rem; }
main { max-width: 72rem; margin: 0 auto; padding: 1rem; }
img { max-width: 100%; height: auto; }
.bouton { display: inline-block; padding: 0.75rem 1.25rem; border-radius: 0.25rem; background-color: {primaire}; \
color: {sur_primaire}; font-weight: 600; text-decoration: none; }
.cartes { display: grid; grid-template-columns: repeat(auto-fit, minmax(16rem, 1fr)); gap: 1.5rem; padding: 0; \
list-style: none; }
blockquote { margin: 0; font-style: italic; }
figcaption { font-size: 0.95rem; }
"""


def feuille_de_style(charte: Mapping[str, str]) -> str:
    """La feuille de style du gabarit, couleurs de la charte (hexadécimales, déjà validées) substituées."""
    css = _CSS
    for cle, valeur in (
        ("{fond}", charte["fond"]), ("{texte}", charte["texte"]), ("{primaire}", charte["primaire"]),
        ("{sur_primaire}", charte["texte_sur_primaire"]), ("{focus}", charte["focus"]),
    ):
        css = css.replace(cle, valeur.lower())
    return css


def politique_csp(css: str, *, en_tete_http: bool = False) -> str:
    """CSP stricte : rien par défaut, images du site seulement, le style inline par son empreinte SHA-256, aucun
    script exécutable (le bloc JSON-LD est une donnée, jamais exécuté). `frame-ancestors` n'existe qu'en en-tête."""
    empreinte = base64.b64encode(hashlib.sha256(css.encode("utf-8")).digest()).decode("ascii")
    politique = (
        f"default-src 'none'; img-src 'self'; style-src 'sha256-{empreinte}'; base-uri 'none'; form-action 'none'"
    )
    return politique + "; frame-ancestors 'none'" if en_tete_http else politique


def _e(texte: Any) -> str:
    return html.escape(str(texte), quote=True)


def _url(schema: Mapping[str, Any], chemin: str) -> str:
    return f"https://{schema['domaine']}{chemin}"


def _telephone_uri(telephone: str) -> str:
    return "tel:" + re.sub(r"[^\d+]", "", telephone)


def _heure(valeur: str, langue: str) -> str:
    h, m = valeur.split(":")
    if langue == "fr-CA":
        return f"{int(h)} h" if m == "00" else f"{int(h)} h {m}"
    return _TEXTES_UI[langue]["heure"].format(h=int(h), m=m)


# ---------------------------------------------------------------------------
# Actifs (images)
# ---------------------------------------------------------------------------
_SVG_RACINE = re.compile(r"<svg\b[^>]*>", re.IGNORECASE)
_SVG_ACTIF = re.compile(
    r"<script|<foreignobject|\son[a-z]+\s*=|(?:xlink:)?href\s*=\s*[\"']\s*(?:https?:|//|javascript:|data:)|"
    r"@import|url\(\s*[\"']?\s*(?:https?:|//)",
    re.IGNORECASE,
)


_BLANCS_IGNORES = re.compile("[\x00-\x20\x7f-\xa0\u1680\u180e\u2000-\u200f\u2028\u2029\u202f\u205f\u3000\ufeff]")
_SCHEMAS_REFUSES = ("javascript:", "vbscript:", "data:", "http:", "https:", "//")
_CSS_EXTERNE = re.compile(r"url\([\"']?(?:https?:|//|javascript:|data:)|@import")
_ELEMENTS_ACTIFS = frozenset({"script", "foreignobject", "iframe", "embed", "object", "handler", "listener"})


def _svg_actif(texte: str) -> bool:
    """Vrai si le SVG porte quelque chose d'actif ou d'externe. Le texte brut est d'abord passé au crible
    (`_SVG_ACTIF`), puis le XML est LU : une entité (`&#106;avascript:`), une tabulation dans le schéma ou un élément
    d'animation qui vise `href` échappent à une simple recherche de motifs, pas au navigateur qui décode d'abord."""
    if _SVG_ACTIF.search(texte) or re.search(r"<!DOCTYPE|<!ENTITY", texte, re.IGNORECASE):
        return True
    try:
        racine = ElementTree.fromstring(texte)
    except ElementTree.ParseError:
        return False  # pas du XML : aucun navigateur ne l'exécute, et `dimensions_image` le refusera comme format
    for element in racine.iter():
        etiquette = element.tag.rsplit("}", 1)[-1].lower() if isinstance(element.tag, str) else ""
        if etiquette in _ELEMENTS_ACTIFS:
            return True
        if etiquette == "style" and _CSS_EXTERNE.search(_BLANCS_IGNORES.sub("", element.text or "").lower()):
            return True
        cible_animee = (element.get("attributeName") or "").rsplit(":", 1)[-1].lower()
        for nom, valeur in element.attrib.items():
            nom_court = nom.rsplit("}", 1)[-1].lower()
            net = _BLANCS_IGNORES.sub("", valeur).lower()
            if nom_court.startswith("on"):
                return True
            visee = nom_court in {"href", "src"} or (
                etiquette in {"set", "animate"} and nom_court in {"to", "values", "from", "by"}
                and (cible_animee in {"href", "src"} or cible_animee.startswith("on")))
            if visee and net.startswith(_SCHEMAS_REFUSES):
                return True
            if _CSS_EXTERNE.search(net):
                return True
    return False


def dimensions_image(contenu: bytes, fichier: str) -> tuple[int, int] | None:
    """(largeur, hauteur) lues dans le fichier lui-même (attributs de la racine SVG, en-tête IHDR d'un PNG)."""
    if fichier.endswith(".png"):
        if contenu[:8] != b"\x89PNG\r\n\x1a\n" or contenu[12:16] != b"IHDR" or len(contenu) < 24:
            return None
        return struct.unpack(">II", contenu[16:24])
    try:
        texte = contenu.decode("utf-8")
    except UnicodeDecodeError:
        return None
    racine = _SVG_RACINE.search(texte)
    if racine is None:
        return None
    largeur = re.search(r'\swidth="(\d+)"', racine.group(0))
    hauteur = re.search(r'\sheight="(\d+)"', racine.group(0))
    if largeur is None or hauteur is None:
        return None
    return int(largeur.group(1)), int(hauteur.group(1))


def verifier_actifs(schema: Mapping[str, Any], actifs: Mapping[str, bytes]) -> list[dict[str, str]]:
    """Chaque image déclarée existe, est un SVG ou PNG dont les dimensions réelles sont celles déclarées, et un SVG
    ne porte rien d'actif (script, gestionnaire, ressource externe)."""
    resultat = []
    for i, image in enumerate(schema.get("images", [])):
        chemin, fichier = f"$.images[{i}]", image["fichier"]
        contenu = actifs.get(fichier)
        if contenu is None:
            resultat.append(refus(REJ_IMAGE_ABSENTE, chemin, f"fichier {fichier} non fourni"))
            continue
        if fichier.endswith(".svg") and _svg_actif(contenu.decode("utf-8", errors="replace")):
            resultat.append(refus(REJ_IMAGE_ACTIVE, chemin, "SVG avec script, gestionnaire ou ressource externe"))
            continue
        dimensions = dimensions_image(contenu, fichier)
        if dimensions is None:
            resultat.append(refus(REJ_IMAGE_FORMAT, chemin, "SVG (width/height entiers) ou PNG lisible attendu"))
        elif dimensions != (image["largeur"], image["hauteur"]):
            resultat.append(refus(
                REJ_IMAGE_DIMENSIONS, chemin,
                f"dimensions réelles {dimensions[0]}x{dimensions[1]}, déclarées {image['largeur']}x{image['hauteur']}",
            ))
    return resultat


def favicon(charte: Mapping[str, str]) -> bytes:
    """Icône SVG dérivée de la charte (un toit stylisé) : aucun fichier externe à fournir."""
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="32" height="32">'
        f'<rect width="32" height="32" rx="6" fill="{charte["primaire"].lower()}"/>'
        f'<path d="M6 17 16 8l10 9h-3v8H9v-8z" fill="{charte["texte_sur_primaire"].lower()}"/></svg>\n'
    ).encode()


# ---------------------------------------------------------------------------
# Rendu
# ---------------------------------------------------------------------------
class _Site:
    """Index du schéma utilisé par le rendu (aucune logique de validation)."""

    def __init__(self, schema: Mapping[str, Any]) -> None:
        self.schema = schema
        self.langues: tuple[str, ...] = tuple(schema["langues"])
        self.entreprise = schema["entreprise"]
        self.nap = self.entreprise["nap"]
        self.services = {s["id"]: s for s in schema["services"]}
        self.zones = {z["id"]: z for z in schema["zones"]}
        self.temoignages = {t["id"]: t for t in schema["temoignages"]}
        self.faq = {q["id"]: q for q in schema["faq"]}
        self.ctas = {c["id"]: c for c in schema["cta"]}
        self.images = {i["id"]: i for i in schema["images"]}
        self.pages = list(schema["pages"])
        self.page_par_id = {p["id"]: p for p in self.pages}
        self.page_du_service = {
            s["service"]: p["id"] for p in self.pages for s in p["sections"] if s["type"] == "service_detail"
        }
        self.page_legale = {
            s["type"]: p["id"] for p in self.pages for s in p["sections"]
            if s["type"] in ("mentions_legales", "confidentialite")
        }
        self.css = feuille_de_style(schema["charte"])
        self.id_entreprise = _url(schema, "/#entreprise")

    def chemin(self, page_id: str, langue: str) -> str:
        return chemin_page(self.page_par_id[page_id]["slug"][langue], langue, self.langues)

    def accueil(self) -> str:
        return next(p["id"] for p in self.pages if all(v == "" for v in p["slug"].values()))


def _noeud_entreprise(site: _Site, langue: str) -> dict[str, Any]:
    adresse = site.nap["adresse"]
    noeud: dict[str, Any] = {
        "@type": site.entreprise["type_schema"],
        "@id": site.id_entreprise,
        "name": site.entreprise["nom"],
        "url": _url(site.schema, "/"),
        "description": site.entreprise["description"][langue],
        "telephone": site.nap["telephone"],
        "email": site.nap["courriel"],
        "address": {
            "@type": "PostalAddress",
            "streetAddress": adresse["rue"],
            "addressLocality": adresse["ville"],
            "addressRegion": adresse["region"],
            "postalCode": adresse["code_postal"],
            "addressCountry": adresse["pays"],
        },
        "areaServed": [{"@type": "City", "name": z["nom"]} for z in site.schema["zones"]],
    }
    if site.entreprise["heures"]:
        noeud["openingHoursSpecification"] = [
            {
                "@type": "OpeningHoursSpecification",
                "dayOfWeek": [f"https://schema.org/{_JOURS_SCHEMA[j]}" for j in plage["jours"]],
                "opens": plage["ouverture"],
                "closes": plage["fermeture"],
            }
            for plage in site.entreprise["heures"]
        ]
    return noeud


def _noeud_service(site: _Site, service_id: str, langue: str) -> dict[str, Any]:
    service = site.services[service_id]
    noeud: dict[str, Any] = {
        "@type": "Service",
        "@id": _url(site.schema, f"/#service-{service_id}"),
        "name": service["nom"][langue],
        "description": service["resume"][langue],
        "provider": {"@id": site.id_entreprise},
        "areaServed": [{"@type": "City", "name": z["nom"]} for z in site.schema["zones"]],
    }
    if service_id in site.page_du_service:
        noeud["url"] = _url(site.schema, site.chemin(site.page_du_service[service_id], langue))
    return noeud


def json_ld(graphe: list[dict[str, Any]]) -> str:
    """Le bloc JSON-LD, sérialisé de façon stable ; `</` est neutralisé pour ne jamais fermer le `<script>`."""
    return json.dumps({"@context": "https://schema.org", "@graph": graphe}, ensure_ascii=False).replace("</", "<\\/")


def _cta_href(site: _Site, cta: Mapping[str, Any], langue: str) -> str:
    cible = cta["cible"]
    if "page" in cible:
        return site.chemin(cible["page"], langue)
    if "telephone" in cible:
        return _telephone_uri(site.nap["telephone"])
    return f"mailto:{site.nap['courriel']}"


def _cta(site: _Site, cta_id: str, langue: str) -> str:
    cta = site.ctas[cta_id]
    return f'<p><a class="bouton" href="{_e(_cta_href(site, cta, langue))}">{_e(cta["libelle"][langue])}</a></p>'


def _image(site: _Site, image_id: str, langue: str, *, prioritaire: bool = False) -> str:
    image = site.images[image_id]
    chargement = "" if prioritaire else ' loading="lazy"'
    return (
        f'<img src="/{_e(image["fichier"])}" alt="{_e(image["alt"][langue])}" width="{image["largeur"]}" '
        f'height="{image["hauteur"]}" decoding="async"{chargement}>'
    )


def _paragraphes(paragraphes: Sequence[str]) -> list[str]:
    return [f"<p>{_e(p)}</p>" for p in paragraphes]


def _coordonnees(site: _Site, langue: str) -> list[str]:
    ui = _TEXTES_UI[langue]
    adresse = site.nap["adresse"]
    lignes = [
        f"<p><strong>{_e(site.entreprise['nom'])}</strong><br>",
        f"{_e(ui['adresse'])}{ui['dp']}{_e(adresse['rue'])}, {_e(adresse['ville'])} ({_e(adresse['region'])}) "
        f"{_e(adresse['code_postal'])}<br>",
        f'{_e(ui["telephone"])}{ui["dp"]}<a href="{_e(_telephone_uri(site.nap["telephone"]))}">'
        f'{_e(site.nap["telephone"])}</a><br>',
        f'{_e(ui["courriel"])}{ui["dp"]}<a href="mailto:{_e(site.nap["courriel"])}">{_e(site.nap["courriel"])}</a></p>',
    ]
    return lignes


def _heures(site: _Site, langue: str) -> list[str]:
    ui = _TEXTES_UI[langue]
    if not site.entreprise["heures"]:
        return []
    items = []
    for plage in site.entreprise["heures"]:
        jours = ", ".join(_JOURS[langue][j] for j in plage["jours"])
        items.append(
            f"<li>{_e(jours)}{ui['dp']}{_e(_heure(plage['ouverture'], langue))} {ui['a']} "
            f"{_e(_heure(plage['fermeture'], langue))}</li>"
        )
    return [f"<h3>{_e(ui['heures'])}</h3>", "<ul>", *items, "</ul>"]


def _section(site: _Site, page: Mapping[str, Any], section: Mapping[str, Any], rang: int, langue: str) -> list[str]:
    ui = _TEXTES_UI[langue]
    type_section = section["type"]
    ancre = section.get("ancre", f"section-{rang}")
    corps: list[str] = []
    titre = section.get("titre", {}).get(langue) if isinstance(section.get("titre"), Mapping) else None
    if titre:
        corps.append(f"<h2>{_e(titre)}</h2>")
    if type_section == "hero":
        if "image" in section:
            corps.append(f"<p>{_image(site, section['image'], langue, prioritaire=True)}</p>")
        corps.append(f'<p class="accroche">{_e(section["texte"][langue])}</p>')
        if "cta" in section:
            corps.append(_cta(site, section["cta"], langue))
    elif type_section in ("texte", "mentions_legales", "confidentialite"):
        if type_section == "mentions_legales":
            corps.append(f"<h3>{_e(ui['identification'])}</h3>")
            corps.extend(_coordonnees(site, langue))
            licence = site.entreprise.get("licence_rbq")
            if licence:
                corps.append(f"<p>{_e(ui['rbq'])}{ui['dp']}{_e(licence['numero'])}</p>")
        corps.extend(_paragraphes(section["paragraphes"][langue]))
        if type_section == "confidentialite":
            responsable = site.schema["legal"]["responsable_rp"]
            corps.append(f"<h3>{_e(ui['responsable_rp'])}</h3>")
            corps.append(
                f'<p>{_e(responsable["titre"][langue])}{ui["dp"]}<a href="mailto:{_e(responsable["courriel"])}">'
                f'{_e(responsable["courriel"])}</a></p>'
            )
            corps.append(f"<p>{_e(ui['sans_traceur'])}</p>")
    elif type_section == "services":
        corps.append('<ul class="cartes">')
        for service_id in section.get("services", list(site.services)):
            service = site.services[service_id]
            corps.append(f"<li><h3>{_e(service['nom'][langue])}</h3><p>{_e(service['resume'][langue])}</p>")
            if service_id in site.page_du_service:
                lien = ui["en_savoir_plus"].format(nom=service["nom"][langue])
                cible = site.chemin(site.page_du_service[service_id], langue)
                corps.append(f'<p><a href="{_e(cible)}">{_e(lien)}</a></p>')
            corps.append("</li>")
        corps.append("</ul>")
    elif type_section == "service_detail":
        service = site.services[section["service"]]
        corps.append(f"<h2>{_e(service['nom'][langue])}</h2>")
        if "image" in service:
            corps.append(f"<p>{_image(site, service['image'], langue)}</p>")
        corps.extend(_paragraphes(service["description"][langue]))
    elif type_section == "zones":
        if "texte" in section:
            corps.append(f"<p>{_e(section['texte'][langue])}</p>")
        corps.append("<ul>")
        corps.extend(f"<li>{_e(z['nom'])}</li>" for z in site.schema["zones"])
        corps.append("</ul>")
    elif type_section == "temoignages":
        for temoignage_id in section.get("temoignages", list(site.temoignages)):
            temoignage = site.temoignages[temoignage_id]
            zone = site.zones[temoignage["zone"]]["nom"]
            corps.append(
                f'<figure><blockquote><p>{_e(temoignage["texte"][langue])}</p></blockquote>'
                f'<figcaption>{_e(temoignage["initiales"])}, {_e(zone)}. {_e(ui["consentement"])}</figcaption></figure>'
            )
    elif type_section == "faq":
        for question_id in section.get("questions", list(site.faq)):
            question = site.faq[question_id]
            corps.append(f"<h3>{_e(question['question'][langue])}</h3>")
            corps.append(f"<p>{_e(question['reponse'][langue])}</p>")
    elif type_section == "coordonnees":
        corps.extend(_coordonnees(site, langue))
        corps.extend(_heures(site, langue))
        for cta_id in section.get("cta", []):
            corps.append(_cta(site, cta_id, langue))
    elif type_section == "cta":
        if "texte" in section:
            corps.append(f"<p>{_e(section['texte'][langue])}</p>")
        corps.append(_cta(site, section["cta"], langue))
    return [f'<section id="{_e(ancre)}">', *corps, "</section>"]


def _graphe_page(site: _Site, page: Mapping[str, Any], langue: str) -> list[dict[str, Any]]:
    graphe = [_noeud_entreprise(site, langue)]
    services: list[str] = []
    questions: list[str] = []
    for section in page["sections"]:
        if section["type"] == "service_detail":
            services.append(section["service"])
        elif section["type"] == "services":
            services.extend(section.get("services", list(site.services)))
        elif section["type"] == "faq":
            questions.extend(section.get("questions", list(site.faq)))
    for service_id in dict.fromkeys(services):
        graphe.append(_noeud_service(site, service_id, langue))
    if questions:
        url_page = _url(site.schema, site.chemin(page["id"], langue))
        graphe.append({
            "@type": "FAQPage",
            "@id": f"{url_page}#faq",
            "mainEntity": [
                {
                    "@type": "Question",
                    "name": site.faq[q]["question"][langue],
                    "acceptedAnswer": {"@type": "Answer", "text": site.faq[q]["reponse"][langue]},
                }
                for q in dict.fromkeys(questions)
            ],
        })
    return graphe


def _titre_document(site: _Site, titre: str) -> str:
    complet = f"{titre} | {site.entreprise['nom']}"
    return complet if len(complet) <= TITRE_PAGE_MAX else titre


def _document(
    site: _Site, langue: str, *, titre: str, description: str, chemin: str, h1: str, corps: list[str],
    page_id: str | None, graphe: list[dict[str, Any]],
) -> str:
    ui = _TEXTES_UI[langue]
    nom = site.entreprise["nom"]
    url = _url(site.schema, chemin)
    tete = [
        "<!DOCTYPE html>",
        f'<html lang="{langue}">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f'<meta http-equiv="Content-Security-Policy" content="{_e(politique_csp(site.css))}">',
        f"<title>{_e(_titre_document(site, titre))}</title>",
        f'<meta name="description" content="{_e(description)}">',
        f'<link rel="canonical" href="{_e(url)}">',
    ]
    if page_id is None:
        tete.append('<meta name="robots" content="noindex">')
    alternes = (
        {autre: site.chemin(page_id, autre) for autre in site.langues} if page_id is not None
        else {autre: chemin_page("", autre, site.langues) + "404.html" for autre in site.langues}
    )
    for autre in site.langues:
        tete.append(f'<link rel="alternate" hreflang="{autre}" href="{_e(_url(site.schema, alternes[autre]))}">')
    tete.append(
        f'<link rel="alternate" hreflang="x-default" href="{_e(_url(site.schema, alternes[site.langues[0]]))}">'
    )
    tete += [
        '<meta property="og:type" content="website">',
        f'<meta property="og:site_name" content="{_e(nom)}">',
        f'<meta property="og:title" content="{_e(titre)}">',
        f'<meta property="og:description" content="{_e(description)}">',
        f'<meta property="og:url" content="{_e(url)}">',
        f'<meta property="og:locale" content="{ui["og_locale"]}">',
    ]
    tete += [
        f'<meta property="og:locale:alternate" content="{_TEXTES_UI[autre]["og_locale"]}">'
        for autre in site.langues if autre != langue
    ]
    tete += [
        f'<meta name="theme-color" content="{_e(site.schema["charte"]["primaire"].lower())}">',
        '<link rel="icon" href="/favicon.svg" type="image/svg+xml">',
        f"<style>{site.css}</style>",
        f'<script type="application/ld+json">{json_ld(graphe)}</script>',
        "</head>",
    ]

    navigation = []
    for page in site.pages:
        if not page.get("navigation", True):
            continue
        libelle = (page.get("titre_nav") or page["titre"])[langue]
        courant = ' aria-current="page"' if page["id"] == page_id else ""
        navigation.append(f'<li><a href="{_e(site.chemin(page["id"], langue))}"{courant}>{_e(libelle)}</a></li>')
    langues = []
    for autre in site.langues:
        if autre == langue:
            continue
        langues.append(
            f'<li><a href="{_e(alternes[autre])}" hreflang="{autre}" lang="{autre}">'
            f'{_e(_TEXTES_UI[autre]["nom_langue"])}</a></li>'
        )
    legaux = [
        f'<li><a href="{_e(site.chemin(pid, langue))}">{_e(site.page_par_id[pid]["titre"][langue])}</a></li>'
        for pid in dict.fromkeys(site.page_legale[t] for t in ("mentions_legales", "confidentialite"))
    ]
    annee = site.schema["revision"]["date"][:4]
    corps_html = [
        "<body>",
        f'<a class="skip-link" href="#contenu">{_e(ui["aller_contenu"])}</a>',
        "<header>",
        f'<p class="marque"><a href="{_e(chemin_page("", langue, site.langues))}">{_e(nom)}</a></p>',
        f'<nav aria-label="{_e(ui["nav_principale"])}"><ul>',
        *navigation,
        "</ul></nav>",
    ]
    if langues:
        corps_html += [f'<ul class="langue" aria-label="{_e(ui["nav_langue"])}">', *langues, "</ul>"]
    corps_html += [
        "</header>",
        '<main id="contenu">',
        f"<h1>{_e(h1)}</h1>",
        *corps,
        "</main>",
        "<footer>",
        *_coordonnees(site, langue),
        f'<nav aria-label="{_e(ui["nav_legale"])}"><ul>',
        *legaux,
        "</ul></nav>",
        f"<p>© {annee} {_e(nom)}. {_e(ui['droits'])}</p>",
        "</footer>",
        "</body>",
        "</html>",
    ]
    return "\n".join(tete + corps_html) + "\n"


def rendre_page(site: _Site, page: Mapping[str, Any], langue: str) -> str:
    corps: list[str] = []
    for rang, section in enumerate(page["sections"], start=1):
        corps.extend(_section(site, page, section, rang, langue))
    return _document(
        site, langue, titre=page["titre"][langue], description=page["description"][langue],
        chemin=site.chemin(page["id"], langue), h1=page["titre"][langue], corps=corps, page_id=page["id"],
        graphe=_graphe_page(site, page, langue),
    )


def _page_introuvable(site: _Site, langue: str) -> str:
    ui = _TEXTES_UI[langue]
    prefixe = chemin_page("", langue, site.langues)
    corps = [
        '<section id="section-1">',
        f"<p>{_e(ui['introuvable_texte'])}</p>",
        f'<p><a class="bouton" href="{_e(prefixe)}">{_e(ui["retour_accueil"])}</a></p>',
        "</section>",
    ]
    return _document(
        site, langue, titre=ui["introuvable_titre"], description=ui["introuvable_description"],
        chemin=f"{prefixe}404.html", h1=ui["introuvable_titre"], corps=corps, page_id=None,
        graphe=[_noeud_entreprise(site, langue)],
    )


def fichier_de_chemin(chemin: str) -> str:
    """`/services/` -> `services/index.html` ; `/` -> `index.html` ; `/favicon.svg` -> `favicon.svg`."""
    relatif = chemin.lstrip("/")
    return relatif + "index.html" if relatif == "" or relatif.endswith("/") else relatif


def _sitemap(site: _Site) -> str:
    lignes = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">',
    ]
    for page in site.pages:
        for langue in site.langues:
            lignes.append("<url>")
            lignes.append(f"<loc>{_e(_url(site.schema, site.chemin(page['id'], langue)))}</loc>")
            for autre in (*site.langues, "x-default"):
                cible = site.langues[0] if autre == "x-default" else autre
                lignes.append(
                    f'<xhtml:link rel="alternate" hreflang="{autre}" '
                    f'href="{_e(_url(site.schema, site.chemin(page["id"], cible)))}"/>'
                )
            lignes.append(f"<lastmod>{site.schema['revision']['date']}</lastmod>")
            lignes.append("</url>")
    lignes.append("</urlset>")
    return "\n".join(lignes) + "\n"


def _robots(site: _Site) -> str:
    return f"User-agent: *\nAllow: /\n\nSitemap: {_url(site.schema, '/sitemap.xml')}\n"


def rendre_site(schema: Mapping[str, Any], actifs: Mapping[str, bytes]) -> dict[str, bytes]:
    """Tous les fichiers du site, `{chemin relatif: octets}`, triés par chemin. Même schéma et mêmes actifs : mêmes
    octets (test d'idempotence)."""
    site = _Site(schema)
    fichiers: dict[str, bytes] = {}
    for page in site.pages:
        for langue in site.langues:
            fichiers[fichier_de_chemin(site.chemin(page["id"], langue))] = rendre_page(site, page, langue).encode()
    for langue in site.langues:
        prefixe = chemin_page("", langue, site.langues).lstrip("/")
        fichiers[f"{prefixe}404.html"] = _page_introuvable(site, langue).encode()
    fichiers["sitemap.xml"] = _sitemap(site).encode()
    fichiers["robots.txt"] = _robots(site).encode()
    fichiers["favicon.svg"] = favicon(schema["charte"])
    for image in schema["images"]:
        fichiers[image["fichier"]] = bytes(actifs[image["fichier"]])
    return dict(sorted(fichiers.items()))
