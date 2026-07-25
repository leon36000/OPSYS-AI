import html.parser
import html.entities
import json
import os
import re
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------
class GuardrailViolation(Exception):
    """Violation du garde-fou déterministe."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


# ---------------------------------------------------------------------------
# Calcul de contraste WCAG
# ---------------------------------------------------------------------------
def _normalize_hex(hex_color: str) -> str:
    """Convertit #rgb -> #rrggbb, minuscule. Lève ValueError si format invalide."""
    if not isinstance(hex_color, str) or not hex_color.startswith("#"):
        raise ValueError(f"Couleur hex invalide: {hex_color}")
    h = hex_color[1:]
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6 or not all(c in "0123456789abcdef" for c in h):
        raise ValueError(f"Couleur hex invalide: {hex_color}")
    return "#" + h


def _srgb_linearize(c: float) -> float:
    """Linéarisation d'un canal sRGB (valeur dans [0,1])."""
    if c <= 0.03928:
        return c / 12.92
    else:
        return ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(hex_color: str) -> float:
    """Luminance relative sRGB selon WCAG 2.x."""
    h = _normalize_hex(hex_color)
    r = int(h[1:3], 16) / 255.0
    g = int(h[3:5], 16) / 255.0
    b = int(h[5:7], 16) / 255.0
    return 0.2126 * _srgb_linearize(r) + 0.7152 * _srgb_linearize(g) + 0.0722 * _srgb_linearize(b)


def contrast_ratio(hex_a: str, hex_b: str) -> float:
    """Ratio de contraste WCAG (1.0..21.0)."""
    lum_a = relative_luminance(hex_a)
    lum_b = relative_luminance(hex_b)
    lighter = max(lum_a, lum_b)
    darker = min(lum_a, lum_b)
    return (lighter + 0.05) / (darker + 0.05)


# ---------------------------------------------------------------------------
# Parsing HTML
# ---------------------------------------------------------------------------
class _SiteValidator(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.html_lang: Optional[str] = None
        self.html_tag_count: int = 0
        self.title_text: Optional[str] = None
        self.title_count: int = 0
        self.meta_charset_ok: bool = False
        self.meta_viewport_content: Optional[str] = None
        self.meta_viewport_violation: bool = False   # true si restriction détectée
        self.meta_description_content: Optional[str] = None
        self.meta_description_length_ok: Optional[bool] = None
        self.canonical_href: Optional[str] = None
        self.theme_color: Optional[str] = None
        self.icon_hrefs: List[str] = []
        self.h1_count: int = 0
        self.heading_levels: List[int] = []   # dans l'ordre d'apparition
        self.landmarks: set = set()
        self.element_ids: set = set()
        self.skip_link_target: Optional[str] = None   # id sans '#'
        self.skip_link_found: bool = False
        self.first_a_href_id: Optional[str] = None
        self.imgs_without_alt: bool = False
        self.has_on_attr: bool = False
        self.has_javascript_protocol: bool = False
        self.script_ld_json_content: Optional[str] = None
        self.style_content: Optional[str] = None
        self.nav_aria_label_ok: bool = True   # True si tous les <nav> ont aria-label ou aria-labelledby
        # temporaires pour parsing
        self._in_title: bool = False
        self._in_style: bool = False
        self._in_script_ld: bool = False
        self._title_buf: List[str] = []
        self._style_buf: List[str] = []
        self._script_buf: List[str] = []

    def handle_starttag(self, tag, attrs):
        tag_lower = tag.lower()
        attrs_dict = dict((k.lower(), v) for k, v in attrs)

        # <html>
        if tag_lower == "html":
            self.html_tag_count += 1
            if "lang" in attrs_dict and attrs_dict["lang"].strip():
                self.html_lang = attrs_dict["lang"].strip()

        # <title>
        elif tag_lower == "title":
            self._in_title = True
            self._title_buf.clear()

        # <meta>
        elif tag_lower == "meta":
            if "charset" in attrs_dict:
                if "utf-8" in attrs_dict["charset"].lower():
                    self.meta_charset_ok = True
            elif attrs_dict.get("http-equiv", "").lower() == "content-type":
                content = attrs_dict.get("content", "")
                if "utf-8" in content.lower():
                    self.meta_charset_ok = True

            if attrs_dict.get("name", "").lower() == "viewport":
                content = attrs_dict.get("content", "")
                self.meta_viewport_content = content
                # vérifier restrictions
                content_lower = content.lower()
                # user-scalable=no
                if re.search(r'user-scalable\s*=\s*no', content_lower):
                    self.meta_viewport_violation = True
                # maximum-scale < 2
                match = re.search(r'maximum-scale\s*=\s*([0-9.]+)', content_lower)
                if match:
                    try:
                        scale = float(match.group(1))
                        if scale < 2.0:
                            self.meta_viewport_violation = True
                    except ValueError:
                        pass

            if attrs_dict.get("name", "").lower() == "description":
                self.meta_description_content = attrs_dict.get("content", "")

            if attrs_dict.get("name", "").lower() == "theme-color":
                self.theme_color = attrs_dict.get("content", "")

        # <link>
        elif tag_lower == "link":
            rel = attrs_dict.get("rel", "").lower()
            if rel == "canonical":
                href = attrs_dict.get("href", "")
                if href.startswith("https://"):
                    self.canonical_href = href
            if rel == "icon":
                href = attrs_dict.get("href", "")
                if href:
                    self.icon_hrefs.append(href)

        # <h1>..<h6>
        elif tag_lower in ("h1", "h2", "h3", "h4", "h5", "h6"):
            level = int(tag_lower[1])
            self.heading_levels.append(level)
            if tag_lower == "h1":
                self.h1_count += 1

        # landmarks
        elif tag_lower in ("header", "nav", "main", "footer"):
            self.landmarks.add(tag_lower)

        # <a>
        elif tag_lower == "a":
            # skip-link
            cls = attrs_dict.get("class", "")
            href = attrs_dict.get("href", "")
            if "skip-link" in cls.split():  # la classe skip-link est présente
                self.skip_link_found = True
                if href.startswith("#"):
                    self.skip_link_target = href[1:]
            elif self.skip_link_target is None and href.startswith("#") and self.first_a_href_id is None:
                self.first_a_href_id = href[1:]

        # <img>
        elif tag_lower == "img":
            alt = attrs_dict.get("alt", "")
            if not alt.strip():
                self.imgs_without_alt = True

        # <script ld+json>
        elif tag_lower == "script" and attrs_dict.get("type") == "application/ld+json":
            self._in_script_ld = True
            self._script_buf.clear()

        # <style>
        elif tag_lower == "style":
            self._in_style = True
            self._style_buf.clear()

        # collect ids
        if "id" in attrs_dict:
            self.element_ids.add(attrs_dict["id"])

        # check on* attributes
        for attr in attrs_dict:
            if attr.startswith("on"):
                self.has_on_attr = True

        # check javascript: protocol in attribute values
        for val in attrs_dict.values():
            if val.strip().lower().startswith("javascript:"):
                self.has_javascript_protocol = True

        # <nav> aria-label / aria-labelledby
        if tag_lower == "nav":
            aria_label = attrs_dict.get("aria-label", "")
            aria_labelledby = attrs_dict.get("aria-labelledby", "")
            if not aria_label.strip() and not aria_labelledby.strip():
                self.nav_aria_label_ok = False

    def handle_endtag(self, tag):
        tag_lower = tag.lower()
        if tag_lower == "title" and self._in_title:
            self._in_title = False
            self.title_text = "".join(self._title_buf).strip()
            self.title_count += 1
        elif tag_lower == "style" and self._in_style:
            self._in_style = False
            self.style_content = "".join(self._style_buf)
        elif tag_lower == "script" and self._in_script_ld:
            self._in_script_ld = False
            self.script_ld_json_content = "".join(self._script_buf).strip()

    def handle_data(self, data):
        if self._in_title:
            self._title_buf.append(data)
        if self._in_style:
            self._style_buf.append(data)
        if self._in_script_ld:
            self._script_buf.append(data)

    def handle_entityref(self, name):
        # convert common entities for title extraction
        char = html.entities.html5.get(name)
        if char:
            self.handle_data(char)
        else:
            self.handle_data(f"&{name};")

    def handle_charref(self, name):
        try:
            if name.startswith("x"):
                char = chr(int(name[1:], 16))
            else:
                char = chr(int(name))
            self.handle_data(char)
        except (ValueError, OverflowError):
            self.handle_data(f"&#{name};")


# ---------------------------------------------------------------------------
# CSS parsing helpers for G-16
# ---------------------------------------------------------------------------
def _parse_css_for_contrast(style_text: str) -> Dict[str, Dict[str, str]]:
    """
    Extrait les propriétés color et background-color pour les sélecteurs simples.
    Retourne un dict: selector -> {prop: value}
    """
    if not style_text:
        return {}
    # supprime commentaires simples /* ... */
    style_text = re.sub(r'/\*.*?\*/', '', style_text, flags=re.DOTALL)
    # capture blocs
    blocks = re.findall(r'([^{]+)\{([^}]+)\}', style_text)
    styles: Dict[str, Dict[str, str]] = {}
    for selectors, body in blocks:
        body = body.strip()
        # propriétés
        color_match = re.search(r'(?<!-)color\s*:\s*(#[0-9a-fA-F]{3,6})\s*;', body)
        bg_match = re.search(r'background-color\s*:\s*(#[0-9a-fA-F]{3,6})\s*;', body)
        for sel in selectors.split(","):
            sel = sel.strip().lower()
            if not sel:
                continue
            if sel not in styles:
                styles[sel] = {}
            if color_match:
                styles[sel]["color"] = color_match.group(1).lower()
            if bg_match:
                styles[sel]["background-color"] = bg_match.group(1).lower()
    return styles


# ---------------------------------------------------------------------------
# Main validation entry points
# ---------------------------------------------------------------------------
def validate(html_text: str, *, content: Optional[dict] = None, assets_dir: Optional[str] = None) -> List[Tuple[str, str]]:
    """Retourne la liste des violations (code, detail), triée par code."""
    parser = _SiteValidator()
    parser.feed(html_text)
    parser.close()

    violations: List[Tuple[str, str]] = []

    # --- G-01 ---
    if parser.html_tag_count == 0:
        violations.append(("G-01", "Aucune balise <html> trouvée."))
    elif parser.html_tag_count > 1:
        violations.append(("G-01", "Plusieurs balises <html> trouvées."))
    elif not parser.html_lang:
        violations.append(("G-01", "Attribut lang manquant ou vide sur <html>."))

    # --- G-02 ---
    if parser.title_count == 0:
        violations.append(("G-02", "Balise <title> absente."))
    elif parser.title_count > 1:
        violations.append(("G-02", "Plusieurs balises <title> trouvées."))
    else:
        length = len(parser.title_text) if parser.title_text else 0
        if length < 10 or length > 70:
            violations.append(("G-02", f"Longueur du <title> = {length} (doit être entre 10 et 70)."))

    # --- G-03 ---
    if not parser.meta_charset_ok:
        violations.append(("G-03", '<meta charset="utf-8"> absent ou invalide.'))

    # --- G-04 ---
    if parser.meta_viewport_content is None:
        violations.append(("G-04", '<meta name="viewport"> absent.'))
    elif parser.meta_viewport_violation:
        violations.append(("G-04", 'Restriction zoom interdite (user-scalable=no ou maximum-scale < 2).'))

    # --- G-05 ---
    if parser.meta_description_content is None:
        violations.append(("G-05", '<meta name="description"> absent.'))
    else:
        length = len(parser.meta_description_content.strip())
        if length < 50 or length > 300:
            violations.append(("G-05", f"Longueur description = {length} (doit être entre 50 et 300)."))

    # --- G-06 ---
    if parser.canonical_href is None:
        violations.append(("G-06", '<link rel="canonical" href="https://..."> absent ou href non absolu.'))

    # --- G-07 ---
    if parser.theme_color is None:
        violations.append(("G-07", '<meta name="theme-color"> absent.'))
    else:
        if not re.fullmatch(r'#[0-9a-fA-F]{3}([0-9a-fA-F]{3})?', parser.theme_color):
            violations.append(("G-07", f"Valeur theme-color invalide : {parser.theme_color}"))

    # --- G-08 ---
    if not parser.icon_hrefs:
        violations.append(("G-08", '<link rel="icon"> absent.'))
    elif assets_dir is not None:
        if not any(os.path.isfile(os.path.join(assets_dir, h)) for h in parser.icon_hrefs):
            violations.append(("G-08", "Fichier favicon introuvable dans le dossier d'assets."))

    # --- G-09 ---
    if parser.h1_count != 1:
        violations.append(("G-09", f"Nombre de <h1> = {parser.h1_count} (attendu exactement 1)."))

    # --- G-10 ---
    for i, level in enumerate(parser.heading_levels):
        if i == 0:
            continue
        prev = parser.heading_levels[i - 1]
        if level > prev + 1:
            violations.append(("G-10", f"Saut de titre : h{prev} → h{level} non autorisé."))
            break

    # --- G-11 ---
    for landmark in ("header", "nav", "main", "footer"):
        if landmark not in parser.landmarks:
            violations.append(("G-11", f"Landmark <{landmark}> absent."))

    # --- G-12 ---
    target = parser.skip_link_target if parser.skip_link_found else parser.first_a_href_id
    if target is not None:
        if target not in parser.element_ids:
            violations.append(("G-12", f"L'ancre de skip-link '#{target}' ne correspond à aucun id."))
    else:
        # Pas de skip-link ni de lien ancre → violation
        violations.append(("G-12", "Aucun lien interne (skip-link ou premier ancre) trouvé."))

    # --- G-13 ---
    if parser.imgs_without_alt:
        violations.append(("G-13", "Image sans attribut alt non vide."))

    # --- G-14 ---
    if parser.has_on_attr or parser.has_javascript_protocol:
        violations.append(("G-14", "Gestionnaire d'événement inline ou protocole javascript: détecté."))

    # --- G-15 ---
    if parser.script_ld_json_content is None:
        violations.append(("G-15", "Script JSON-LD absent."))
    else:
        try:
            ld = json.loads(parser.script_ld_json_content)
        except json.JSONDecodeError:
            violations.append(("G-15", "JSON-LD invalide (JSON mal formé)."))
        else:
            if isinstance(ld, dict):
                ctx = ld.get("@context", "")
                if isinstance(ctx, str):
                    if "schema.org" not in ctx:
                        violations.append(("G-15", "@context ne contient pas schema.org."))
                elif isinstance(ctx, list):
                    if not any("schema.org" in c for c in ctx if isinstance(c, str)):
                        violations.append(("G-15", "@context ne contient pas schema.org."))
                else:
                    violations.append(("G-15", "@context invalide ou absent."))

                if ld.get("@type") != "Organization":
                    violations.append(("G-15", '@type absent ou différent de "Organization".'))

                for field in ('name', 'url', 'description'):
                    val = ld.get(field)
                    if not isinstance(val, str) or not val.strip():
                        violations.append(("G-15", f'Champ {field} manquant ou vide dans JSON-LD.'))
            else:
                violations.append(("G-15", "JSON-LD n'est pas un objet JSON."))

    # --- G-16 ---
    if parser.style_content is not None:
        styles = _parse_css_for_contrast(parser.style_content)
        # paires à vérifier
        checks = [
            ("body color/bg", styles.get("body", {}).get("color"), styles.get("body", {}).get("background-color")),
            ("header", styles.get("header", {}).get("color"), styles.get("header", {}).get("background-color")),
            ("nav", styles.get("nav", {}).get("color"), styles.get("nav", {}).get("background-color")),
            ("footer", styles.get("footer", {}).get("color"), styles.get("footer", {}).get("background-color")),
            ("link on body", styles.get("a", {}).get("color"), styles.get("body", {}).get("background-color")),
        ]
        for label, fg, bg in checks:
            if fg and bg:
                try:
                    ratio = contrast_ratio(fg, bg)
                    if ratio < 7.0:
                        violations.append(("G-16", f"Contraste {label}: {fg} sur {bg} → {ratio:.2f} (min 7.0 requis pour AAA)."))
                except ValueError:
                    # couleur invalide → on ignore
                    pass

    # --- G-17 ---
    if "nav" in parser.landmarks and not parser.nav_aria_label_ok:
        violations.append(("G-17", "<nav> sans aria-label ni aria-labelledby non vide."))

    # --- G-18 ---
    if content and "lang" in content and parser.html_lang:
        if content["lang"] != parser.html_lang:
            violations.append(("G-18", f"Incohérence de langue : HTML lang={parser.html_lang} vs content.lang={content['lang']}."))

    violations.sort(key=lambda x: x[0])
    return violations


def assert_valid(html_text: str, *, content: Optional[dict] = None, assets_dir: Optional[str] = None) -> None:
    """Lève GuardrailViolation avec le premier code (ordre croissant) si une violation existe."""
    vios = validate(html_text, content=content, assets_dir=assets_dir)
    if vios:
        code, detail = vios[0]
        raise GuardrailViolation(code, detail)
