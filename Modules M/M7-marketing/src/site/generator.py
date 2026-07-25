import html
import json
import os
from pathlib import Path

import yaml

import guardrail

REQUIRED_KEYS = {
    "lang",
    "title",
    "description",
    "canonical",
    "theme_color",
    "favicon",
    "colors",
    "org",
    "nav_label",
    "sections",
}


def load_content(path: str) -> dict:
    """Charge et valide le fichier YAML, lève ValueError si une clé requise manque."""
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError("Le contenu YAML n'est pas un dictionnaire")
    missing = [k for k in REQUIRED_KEYS if k not in data]
    if missing:
        raise ValueError(f"Clé(s) requise(s) manquante(s) : {', '.join(missing)}")
    return data


def render_html(content: dict) -> str:
    """Génère un document HTML complet, conforme aux invariants du garde-fou."""
    # Échappement de tous les textes provenant du contenu
    title = html.escape(content["title"])
    description = html.escape(content["description"])
    canonical = html.escape(content["canonical"])
    theme_color = html.escape(content["theme_color"])
    favicon = html.escape(content["favicon"])
    lang = html.escape(content["lang"])
    nav_label = html.escape(content["nav_label"])
    colors = content["colors"]
    org = content["org"]

    # Feuille de style
    css = f"""\
    body {{ background-color: {colors['bg']}; color: {colors['fg']}; }}
    header {{ background-color: {colors['header_bg']}; color: {colors['header_fg']}; }}
    nav {{ background-color: {colors['nav_bg']}; color: {colors['nav_fg']}; }}
    nav a {{ color: {colors['nav_fg']}; }}
    footer {{ background-color: {colors['footer_bg']}; color: {colors['footer_fg']}; }}
    a {{ color: {colors['link']}; }}"""

    # Données structurées JSON-LD
    ld_data = {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": org["name"],
        "url": org["url"],
        "description": org["description"],
    }
    ld_json = json.dumps(ld_data, ensure_ascii=False, indent=2)

    # Sections de contenu
    sections_html = ""
    for sec in content["sections"]:
        sec_id = html.escape(sec["id"])
        heading = html.escape(sec["heading"])
        sections_html += f'    <section id="{sec_id}">\n'
        sections_html += f'      <h2>{heading}</h2>\n'
        for para in sec["paragraphs"]:
            sections_html += f"      <p>{html.escape(para)}</p>\n"
        sections_html += "    </section>\n"

    # Liens de navigation
    nav_items = ""
    for sec in content["sections"]:
        sec_id = html.escape(sec["id"])
        heading = html.escape(sec["heading"])
        nav_items += f'        <li><a href="#{sec_id}">{heading}</a></li>\n'

    # Assemblage du document HTML complet
    return f"""<!DOCTYPE html>
<html lang="{lang}">
<head>
  <meta charset="utf-8">
  <title>{title}</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="{description}">
  <link rel="canonical" href="{canonical}">
  <meta name="theme-color" content="{theme_color}">
  <link rel="icon" href="{favicon}">
  <style>
{css}
  </style>
  <script type="application/ld+json">
{ld_json}
  </script>
</head>
<body>
  <a class="skip-link" href="#contenu">Aller au contenu</a>
  <header>
    <h1>{title}</h1>
  </header>
  <nav aria-label="{nav_label}">
    <ul>
{nav_items}    </ul>
  </nav>
  <main id="contenu">
{sections_html}  </main>
  <footer>
    <p>© OPSYS-AI — Tous droits réservés.</p>
  </footer>
</body>
</html>"""


def generate(content_path: str, out_path: str) -> str:
    """Charge le contenu, génère le HTML, valide avec le garde-fou et écrit le fichier en sortie."""
    content = load_content(content_path)
    html_out = render_html(content)
    guardrail.assert_valid(
        html_out,
        content=content,
        assets_dir=os.path.dirname(os.path.abspath(str(out_path)))
    )
    Path(out_path).write_text(html_out, encoding="utf-8")
    return html_out
