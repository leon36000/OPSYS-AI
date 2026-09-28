import hashlib
from pathlib import Path

import pytest
from m7_marketing.site import generator, guardrail

_SITE = Path(__file__).resolve().parents[1] / "src" / "m7_marketing" / "site"


# Contenu YAML minimal conforme aux clés requises
MINIMAL_CONTENT_DICT = {
    "lang": "fr",
    "title": "Mon Site Test",
    "description": (
        "Un site de test conforme avec une description assez longue pour valider les invariants "
        "de longueur minimale."
    ),
    "canonical": "https://example.com/",
    "theme_color": "#0044cc",
    "favicon": "favicon.svg",
    "colors": {
        "bg": "#ffffff",
        "fg": "#000000",
        "link": "#0000ee",
        "header_bg": "#f0f0f0",
        "header_fg": "#000000",
        "nav_bg": "#e0e0e0",
        "nav_fg": "#000000",
        "footer_bg": "#d0d0d0",
        "footer_fg": "#000000",
    },
    "org": {
        "name": "Org Test",
        "url": "https://example.com",
        "description": "Organisation de test"
    },
    "nav_label": "Navigation principale",
    "sections": [
        {
            "id": "intro",
            "heading": "Introduction",
            "paragraphs": ["Bienvenue sur le site."]
        },
        {
            "id": "details",
            "heading": "Détails",
            "paragraphs": ["Plus d'informations."]
        }
    ]
}


# ---------------------------------------------------------------------------
# Test de déterminisme de render_html
# ---------------------------------------------------------------------------
def test_determinisme():
    html1 = generator.render_html(MINIMAL_CONTENT_DICT)
    html2 = generator.render_html(MINIMAL_CONTENT_DICT)
    assert html1 == html2, "render_html doit être déterministe"
    sha1 = hashlib.sha256(html1.encode("utf-8")).hexdigest()
    sha2 = hashlib.sha256(html2.encode("utf-8")).hexdigest()
    assert sha1 == sha2, "le SHA-256 doit être stable"


# ---------------------------------------------------------------------------
# Test sortie conforme : render_html + validate = pas de violation
# ---------------------------------------------------------------------------
def test_sortie_conforme(tmp_path):
    # Écrire un content.yaml temporaire
    content_file = tmp_path / "content.yaml"
    import yaml
    with open(content_file, "w", encoding="utf-8") as f:
        yaml.safe_dump(MINIMAL_CONTENT_DICT, f)
    content = generator.load_content(str(content_file))
    html = generator.render_html(content)
    violations = guardrail.validate(html, content=content)
    assert violations == [], f"Le HTML produit doit être sans violation : {violations}"


# ---------------------------------------------------------------------------
# Test generate refuse si non conforme et n'écrit pas le fichier
# ---------------------------------------------------------------------------
def test_generate_refuse_si_non_conforme(tmp_path):
    # Créer un contenu délibérément invalide (description trop courte)
    bad_content = dict(MINIMAL_CONTENT_DICT)
    bad_content["description"] = "trop court"
    content_file = tmp_path / "bad_content.yaml"
    import yaml
    with open(content_file, "w", encoding="utf-8") as f:
        yaml.safe_dump(bad_content, f)
    out_file = tmp_path / "output.html"

    with pytest.raises(guardrail.GuardrailViolation):
        generator.generate(str(content_file), str(out_file))

    assert not out_file.exists(), "Le fichier de sortie ne doit pas être écrit en cas d'échec du garde-fou"


# ---------------------------------------------------------------------------
# Test de référence du ratio de contraste
# ---------------------------------------------------------------------------
def test_contrast_ratio_reference():
    r_black_white = guardrail.contrast_ratio("#000000", "#ffffff")
    assert abs(r_black_white - 21.0) < 0.1, f"Contraste noir/blanc attendu ~21.0, obtenu {r_black_white}"
    r_grey_white = guardrail.contrast_ratio("#767676", "#ffffff")
    assert abs(r_grey_white - 4.54) < 0.05, f"Contraste #767676 sur blanc attendu ~4.54, obtenu {r_grey_white}"
    # symétrie
    assert guardrail.contrast_ratio("#ffffff", "#000000") == r_black_white
    assert guardrail.contrast_ratio("#ffffff", "#767676") == r_grey_white


# ---------------------------------------------------------------------------
# Critère d'acceptation 4 : le contenu RÉEL du dépôt est conforme (R2)
# ---------------------------------------------------------------------------
def test_site_reel_conforme():
    """Critère d'acceptation 4 : le content.yaml RÉEL du dépôt, rendu puis validé avec
    assets_dir=static réel, donne zéro violation."""
    site_dir = _SITE  # défini en tête du fichier de tests (Path vers src/m7_marketing/site)
    content = generator.load_content(str(site_dir / "content.yaml"))
    html_out = generator.render_html(content)
    violations = guardrail.validate(html_out, content=content, assets_dir=str(site_dir / "static"))
    assert violations == [], f"Le site réel doit être conforme : {violations}"


# ---------------------------------------------------------------------------
# Correctifs mission §3 : schema.org HomeAndConstructionBusiness (contradiction G-15/A-08)
# et identité de l'entreprise fournie en paramètre (jamais "© OPSYS-AI" codé en dur).
# ---------------------------------------------------------------------------
def test_jsonld_type_est_homeandconstructionbusiness():
    """RED — bug corrigé (R9 §1.4) : generator.py émettait "Organization" en dur, ce que
    guardrail.py G-15 acceptait mais que aeo_engine.py A-08 rejetait systématiquement
    (il exige LocalBusiness). HomeAndConstructionBusiness est un sous-type STRICT de
    LocalBusiness, adapté à une entreprise de rénovation extérieure, et satisfait les deux
    garde-fous à la fois."""
    import json

    html = generator.render_html(MINIMAL_CONTENT_DICT)
    violations = guardrail.validate(html, content=MINIMAL_CONTENT_DICT)
    assert violations == [], f"HomeAndConstructionBusiness doit rester conforme à G-15 : {violations}"

    marker = '<script type="application/ld+json">'
    start = html.index(marker) + len(marker)
    end = html.index("</script>", start)
    ld = json.loads(html[start:end])
    assert ld["@type"] == "HomeAndConstructionBusiness"


def test_copyright_footer_utilise_le_nom_de_marque_fourni_en_parametre():
    """RED — bug corrigé (mission §3) : le pied de page affichait littéralement
    "© OPSYS-AI" quel que soit le contenu, alors que M7 gère le marketing d'une entreprise
    de rénovation extérieure distincte. Le nom affiché doit venir de content["org"]["name"],
    jamais d'un littéral codé en dur."""
    content_autre_entreprise = dict(MINIMAL_CONTENT_DICT)
    content_autre_entreprise["org"] = {
        "name": "Toitures Boréales Inc.",
        "url": "https://example.com",
        "description": "Organisation de test",
    }
    html = generator.render_html(content_autre_entreprise)
    assert "© Toitures Boréales Inc." in html
    assert "OPSYS-AI" not in html
    violations = guardrail.validate(html, content=content_autre_entreprise)
    assert violations == [], f"Doit rester conforme quel que soit le nom de marque : {violations}"
