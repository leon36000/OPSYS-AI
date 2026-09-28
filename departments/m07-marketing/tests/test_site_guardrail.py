from pathlib import Path
_SITE = Path(__file__).resolve().parents[1] / "src" / "m7_marketing" / "site"

from m7_marketing.site import guardrail
import pytest


def _html(**overrides) -> str:
    """Document HTML conforme minimal servant de référence pour les tests."""
    return f"""<!DOCTYPE html>
<html lang="{overrides.get('lang', 'fr')}">
<head>
  <meta charset="utf-8">
  <title>{overrides.get('title', 'Site Test AAA')}</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="{overrides.get('description', 'Un site de test respectant les contrats WCAG AAA avec suffisamment de texte pour valider les invariants.')}">
  <link rel="canonical" href="{overrides.get('canonical', 'https://example.com/page')}">
  <meta name="theme-color" content="{overrides.get('theme_color', '#0044cc')}">
  <link rel="icon" href="{overrides.get('favicon', 'favicon.svg')}">
  <style>
    body {{ background-color: {overrides.get('bg', '#ffffff')}; color: {overrides.get('fg', '#000000')}; }}
    header {{ background-color: {overrides.get('header_bg', '#f0f0f0')}; color: {overrides.get('header_fg', '#000000')}; }}
    nav {{ background-color: {overrides.get('nav_bg', '#e0e0e0')}; color: {overrides.get('nav_fg', '#000000')}; }}
    footer {{ background-color: {overrides.get('footer_bg', '#d0d0d0')}; color: {overrides.get('footer_fg', '#000000')}; }}
    a {{ color: {overrides.get('link', '#0000ee')}; }}
  </style>
</head>
<body>
  <a class="skip-link" href="#main">Aller au contenu principal</a>
  <header>
    <h1>{overrides.get('h1', 'Titre Principal')}</h1>
  </header>
  <nav aria-label="Navigation principale">
    <ul><li><a href="#section1">Section 1</a></li></ul>
  </nav>
  <main id="main">
    <h2>{overrides.get('h2', 'Section 1')}</h2>
    <p>{overrides.get('p', 'Contenu de la section.')}</p>
  </main>
  <footer>
    <p>© 2025 Organisation Test</p>
  </footer>
  <script type="application/ld+json">
  {{
    "@context": "https://schema.org",
    "@type": "Organization",
    "name": "Org Test",
    "url": "https://example.com",
    "description": "Une organisation de test"
  }}
  </script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# G-01 : un seul <html lang=...>, lang non vide
# ---------------------------------------------------------------------------
def test_positive_G_01():
    html = _html()
    violations = guardrail.validate(html)
    codes = [c for c, _ in violations]
    assert "G-01" not in codes


def test_negative_G_01():
    # supprimer l'attribut lang
    html = _html().replace(' lang="fr"', "", 1)
    violations = guardrail.validate(html)
    codes = [c for c, _ in violations]
    assert "G-01" in codes
    with pytest.raises(guardrail.GuardrailViolation) as excinfo:
        guardrail.assert_valid(html)
    assert excinfo.value.code == "G-01"


# ---------------------------------------------------------------------------
# G-02 : un seul <title>, longueur ∈ [10,70]
# ---------------------------------------------------------------------------
def test_positive_G_02():
    html = _html(title="A" * 30)
    violations = guardrail.validate(html)
    codes = [c for c, _ in violations]
    assert "G-02" not in codes


def test_negative_G_02():
    # titre trop court
    html = _html(title="Court")
    violations = guardrail.validate(html)
    assert any(c == "G-02" for c, _ in violations)

    with pytest.raises(guardrail.GuardrailViolation) as excinfo:
        guardrail.assert_valid(html)
    assert excinfo.value.code == "G-02"


# ---------------------------------------------------------------------------
# G-03 : <meta charset="utf-8"> présent
# ---------------------------------------------------------------------------
def test_positive_G_03():
    html = _html()
    violations = guardrail.validate(html)
    assert all(c != "G-03" for c, _ in violations)


def test_negative_G_03():
    # supprimer la balise meta charset
    html = _html().replace('<meta charset="utf-8">', "", 1)
    violations = guardrail.validate(html)
    assert any(c == "G-03" for c, _ in violations)
    with pytest.raises(guardrail.GuardrailViolation) as excinfo:
        guardrail.assert_valid(html)
    assert excinfo.value.code == "G-03"


# ---------------------------------------------------------------------------
# G-04 : <meta name="viewport"> présent, SANS user-scalable=no, maximum-scale>=2
# ---------------------------------------------------------------------------
def test_positive_G_04():
    html = _html()
    violations = guardrail.validate(html)
    assert all(c != "G-04" for c, _ in violations)


def test_negative_G_04():
    # ajouter user-scalable=no
    bad = '<meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no">'
    html = _html().replace('<meta name="viewport" content="width=device-width, initial-scale=1">', bad, 1)
    violations = guardrail.validate(html)
    assert any(c == "G-04" for c, _ in violations)
    with pytest.raises(guardrail.GuardrailViolation) as excinfo:
        guardrail.assert_valid(html)
    assert excinfo.value.code == "G-04"


# ---------------------------------------------------------------------------
# G-05 : <meta name="description"> non vide, longueur ∈ [50,300]
# ---------------------------------------------------------------------------
def test_positive_G_05():
    html = _html(description="A" * 100)
    violations = guardrail.validate(html)
    assert all(c != "G-05" for c, _ in violations)


def test_negative_G_05():
    html = _html(description="Trop court")
    violations = guardrail.validate(html)
    assert any(c == "G-05" for c, _ in violations)
    with pytest.raises(guardrail.GuardrailViolation) as excinfo:
        guardrail.assert_valid(html)
    assert excinfo.value.code == "G-05"


# ---------------------------------------------------------------------------
# G-06 : <link rel="canonical" href="https://..."> absolu
# ---------------------------------------------------------------------------
def test_positive_G_06():
    html = _html(canonical="https://example.com/absolu")
    violations = guardrail.validate(html)
    assert all(c != "G-06" for c, _ in violations)


def test_negative_G_06():
    # href relatif
    html = _html().replace('href="https://example.com/page"', 'href="/relative"', 1)
    violations = guardrail.validate(html)
    assert any(c == "G-06" for c, _ in violations)
    with pytest.raises(guardrail.GuardrailViolation) as excinfo:
        guardrail.assert_valid(html)
    assert excinfo.value.code == "G-06"


# ---------------------------------------------------------------------------
# G-07 : <meta name="theme-color" content="#hex valide">
# ---------------------------------------------------------------------------
def test_positive_G_07():
    html = _html(theme_color="#aabbcc")
    violations = guardrail.validate(html)
    assert all(c != "G-07" for c, _ in violations)


def test_negative_G_07():
    # couleur invalide
    html = _html().replace('content="#0044cc"', 'content="bleu"', 1)
    violations = guardrail.validate(html)
    assert any(c == "G-07" for c, _ in violations)
    with pytest.raises(guardrail.GuardrailViolation) as excinfo:
        guardrail.assert_valid(html)
    assert excinfo.value.code == "G-07"


# ---------------------------------------------------------------------------
# G-08 : <link rel="icon" href=...> déclaré ; si assets_dir fourni, l'asset existe
# ---------------------------------------------------------------------------
def test_positive_G_08():
    html = _html()
    violations = guardrail.validate(html)
    assert all(c != "G-08" for c, _ in violations)


def test_negative_G_08():
    # supprimer l'icône
    html = _html().replace('<link rel="icon" href="favicon.svg">', "", 1)
    violations = guardrail.validate(html)
    assert any(c == "G-08" for c, _ in violations)
    with pytest.raises(guardrail.GuardrailViolation) as excinfo:
        guardrail.assert_valid(html)
    assert excinfo.value.code == "G-08"


# ---------------------------------------------------------------------------
# G-09 : exactement un <h1>
# ---------------------------------------------------------------------------
def test_positive_G_09():
    html = _html()
    violations = guardrail.validate(html)
    assert all(c != "G-09" for c, _ in violations)


def test_negative_G_09():
    # ajouter un deuxième h1
    html = _html().replace("</header>", "<h1>Second H1</h1></header>", 1)
    violations = guardrail.validate(html)
    assert any(c == "G-09" for c, _ in violations)
    with pytest.raises(guardrail.GuardrailViolation) as excinfo:
        guardrail.assert_valid(html)
    assert excinfo.value.code == "G-09"


# ---------------------------------------------------------------------------
# G-10 : ordre des titres sans saut de niveau (h1->h2->h3 ; jamais h1->h3)
# ---------------------------------------------------------------------------
def test_positive_G_10():
    html = _html()
    violations = guardrail.validate(html)
    assert all(c != "G-10" for c, _ in violations)


def test_negative_G_10():
    # saut de h1 à h3
    html = _html().replace("<h2>Section 1</h2>", "<h3>Section 1</h3>", 1)
    violations = guardrail.validate(html)
    assert any(c == "G-10" for c, _ in violations)
    with pytest.raises(guardrail.GuardrailViolation) as excinfo:
        guardrail.assert_valid(html)
    assert excinfo.value.code == "G-10"


# ---------------------------------------------------------------------------
# G-11 : landmarks présents : <header>, <nav>, <main>, <footer> (≥1 chacun)
# ---------------------------------------------------------------------------
def test_positive_G_11():
    html = _html()
    violations = guardrail.validate(html)
    assert all(c != "G-11" for c, _ in violations)


def test_negative_G_11():
    # supprimer <nav>
    html = _html().replace("<nav", "<!-- nav supprimé --> <nav style=\"display:none\"", 1)  # pas bon, on veut absence totale
    # mieux : effacer la balise
    html = _html().replace("<nav ", "<div class=\"was-nav\"", 1).replace("</nav>", "</div>", 1)
    violations = guardrail.validate(html)
    assert any(c == "G-11" for c, _ in violations)
    with pytest.raises(guardrail.GuardrailViolation) as excinfo:
        guardrail.assert_valid(html)
    assert excinfo.value.code == "G-11"


# ---------------------------------------------------------------------------
# G-12 : skip-link (a.skip-link ou 1er <a href="#...">) cible un id EXISTANT
# ---------------------------------------------------------------------------
def test_positive_G_12():
    html = _html()
    violations = guardrail.validate(html)
    assert all(c != "G-12" for c, _ in violations)


def test_negative_G_12():
    # changer le href de la skip-link vers une cible inexistante
    html = _html().replace('href="#main"', 'href="#inexistant"', 1)
    violations = guardrail.validate(html)
    assert any(c == "G-12" for c, _ in violations)
    with pytest.raises(guardrail.GuardrailViolation) as excinfo:
        guardrail.assert_valid(html)
    assert excinfo.value.code == "G-12"


# ---------------------------------------------------------------------------
# G-13 : toute <img> a un attribut alt non vide (site sans img => vacuously true)
# ---------------------------------------------------------------------------
def test_positive_G_13():
    html = _html()
    # aucune image, doit être ok
    violations = guardrail.validate(html)
    assert all(c != "G-13" for c, _ in violations)


def test_negative_G_13():
    # ajouter une img sans alt
    html = _html().replace("<p>Contenu de la section.</p>", '<p>Contenu<img src="img.png"></p>', 1)
    violations = guardrail.validate(html)
    assert any(c == "G-13" for c, _ in violations)
    with pytest.raises(guardrail.GuardrailViolation) as excinfo:
        guardrail.assert_valid(html)
    assert excinfo.value.code == "G-13"


# ---------------------------------------------------------------------------
# G-14 : aucun gestionnaire d'événement inline (on*=), aucun javascript:
# ---------------------------------------------------------------------------
def test_positive_G_14():
    html = _html()
    violations = guardrail.validate(html)
    assert all(c != "G-14" for c, _ in violations)


def test_negative_G_14():
    # ajouter onclick
    html = _html().replace("<a class=\"skip-link\"", "<a class=\"skip-link\" onclick=\"void(0)\"", 1)
    violations = guardrail.validate(html)
    assert any(c == "G-14" for c, _ in violations)
    with pytest.raises(guardrail.GuardrailViolation) as excinfo:
        guardrail.assert_valid(html)
    assert excinfo.value.code == "G-14"


# ---------------------------------------------------------------------------
# G-15 : JSON-LD : JSON valide, @context=schema.org, @type=Organization, champs remplis
# ---------------------------------------------------------------------------
def test_positive_G_15():
    html = _html()
    violations = guardrail.validate(html)
    assert all(c != "G-15" for c, _ in violations)


def test_negative_G_15():
    # supprimer le bloc JSON-LD
    html = _html().replace('<script type="application/ld+json">', '<script type="application/ld+json" style="display:none">', 1)  # pas bon
    # on enlève carrément
    html = _html().replace('<script type="application/ld+json">', '<!-- ld+json retiré -->', 1)
    html = html.replace('</script>', '', 1)  # enlever la fermeture
    violations = guardrail.validate(html)
    assert any(c == "G-15" for c, _ in violations)
    with pytest.raises(guardrail.GuardrailViolation) as excinfo:
        guardrail.assert_valid(html)
    assert excinfo.value.code == "G-15"


# ---------------------------------------------------------------------------
# G-16 : contraste AAA ≥ 7.0 pour paires fg/bg, link/bg, header, nav, footer
# ---------------------------------------------------------------------------
def test_positive_G_16():
    # couleurs conformes
    html = _html()
    violations = guardrail.validate(html)
    assert all(c != "G-16" for c, _ in violations)


def test_negative_G_16():
    # bg et fg trop proches (par exemple #767676 sur #ffffff ~4.54)
    html = _html(fg="#767676", bg="#ffffff")
    violations = guardrail.validate(html)
    assert any(c == "G-16" for c, _ in violations)
    with pytest.raises(guardrail.GuardrailViolation) as excinfo:
        guardrail.assert_valid(html)
    assert excinfo.value.code == "G-16"


# ---------------------------------------------------------------------------
# G-17 : <nav> porte aria-label ou aria-labelledby non vide
# ---------------------------------------------------------------------------
def test_positive_G_17():
    html = _html()
    violations = guardrail.validate(html)
    assert all(c != "G-17" for c, _ in violations)


def test_negative_G_17():
    # supprimer aria-label du nav
    html = _html().replace('aria-label="Navigation principale"', "", 1)
    violations = guardrail.validate(html)
    assert any(c == "G-17" for c, _ in violations)
    with pytest.raises(guardrail.GuardrailViolation) as excinfo:
        guardrail.assert_valid(html)
    assert excinfo.value.code == "G-17"


# ---------------------------------------------------------------------------
# G-18 : cohérence : lang du <html> == content['lang'] si content fourni
# ---------------------------------------------------------------------------
def test_positive_G_18():
    html = _html(lang="en")
    content = {"lang": "en"}
    violations = guardrail.validate(html, content=content)
    assert all(c != "G-18" for c, _ in violations)


def test_negative_G_18():
    html = _html(lang="fr")
    content = {"lang": "en"}
    violations = guardrail.validate(html, content=content)
    assert any(c == "G-18" for c, _ in violations)
    with pytest.raises(guardrail.GuardrailViolation) as excinfo:
        guardrail.assert_valid(html, content=content)
    assert excinfo.value.code == "G-18"


def test_positive_G_16_liens_nav():
    """nav sombre mais avec règle nav a conforme -> aucun G-16"""
    html = _html()
    html = html.replace("nav { background-color: #e0e0e0; color: #000000; }",
                        "nav { background-color: #1a1a1a; color: #ffffff; } nav a { color: #ffffff; }")
    violations = guardrail.validate(html)
    codes = [c for c, _ in violations]
    assert "G-16" not in codes


def test_negative_G_16_liens_nav():
    """nav sombre sans règle nav a -> lien hérite a{color:#0000ee} contraste insuffisant -> G-16"""
    html = _html()
    html = html.replace("nav { background-color: #e0e0e0; color: #000000; }",
                        "nav { background-color: #1a1a1a; color: #ffffff; }")
    violations = guardrail.validate(html)
    codes = [c for c, _ in violations]
    assert "G-16" in codes
    with pytest.raises(guardrail.GuardrailViolation) as excinfo:
        guardrail.assert_valid(html)
    assert excinfo.value.code == "G-16"


# ---------------------------------------------------------------------------
# G-16 : couleur non hexadécimale — bug corrigé (mission §3, guardrail.py ~l.456).
# Avant le correctif, une couleur non hex (nommée, rgb()) rendait le contraste
# totalement IGNORÉ (aucune violation), au lieu d'être traité comme un échec.
# ---------------------------------------------------------------------------
def test_negative_G_16_couleur_nommee_non_ignoree():
    """RED : bg/fg en couleurs NOMMÉES (non hex) doit produire une violation G-16
    (contraste non vérifiable), jamais un passage silencieux."""
    html = _html(fg="white", bg="white")
    violations = guardrail.validate(html)
    codes = [c for c, _ in violations]
    assert "G-16" in codes, "une couleur non hexadécimale doit être signalée, jamais ignorée"
    with pytest.raises(guardrail.GuardrailViolation) as excinfo:
        guardrail.assert_valid(html)
    assert excinfo.value.code == "G-16"


def test_negative_G_16_couleur_rgb_non_ignoree():
    """RED : bg/fg en rgb() (non hex) doit aussi produire une violation G-16."""
    html = _html(fg="rgb(255,255,255)", bg="rgb(255,255,255)")
    violations = guardrail.validate(html)
    codes = [c for c, _ in violations]
    assert "G-16" in codes


# ---------------------------------------------------------------------------
# G-15 : @type accepte Organization/LocalBusiness/HomeAndConstructionBusiness — bug
# corrigé (mission §3, R9 §1.4 : contradiction avec aeo_engine.py règle A-08).
# ---------------------------------------------------------------------------
def test_positive_G_15_homeandconstructionbusiness():
    html = _html().replace('"@type": "Organization"', '"@type": "HomeAndConstructionBusiness"')
    violations = guardrail.validate(html)
    codes = [c for c, _ in violations]
    assert "G-15" not in codes


def test_positive_G_15_localbusiness():
    html = _html().replace('"@type": "Organization"', '"@type": "LocalBusiness"')
    violations = guardrail.validate(html)
    codes = [c for c, _ in violations]
    assert "G-15" not in codes


def test_negative_G_15_type_hors_ensemble_accepte():
    """L'élargissement ne devient pas un chèque en blanc : un @type totalement hors
    ensemble accepté reste une violation G-15."""
    html = _html().replace('"@type": "Organization"', '"@type": "Person"')
    violations = guardrail.validate(html)
    codes = [c for c, _ in violations]
    assert "G-15" in codes
