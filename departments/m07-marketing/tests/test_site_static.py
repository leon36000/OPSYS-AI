"""Tests déterministes (stdlib) pour l'amorce statique du site M7."""

from __future__ import annotations

import json
import re
from pathlib import Path

_TESTS_DIR = Path(__file__).parent.resolve()
STATIC_DIR = (_TESTS_DIR.parent / "src" / "m7_marketing" / "site" / "static").resolve()
INDEX_PATH = STATIC_DIR / "index.html"
ROBOTS_PATH = STATIC_DIR / "robots.txt"


def _html() -> str:
    return INDEX_PATH.read_text(encoding="utf-8")


def _robots() -> str:
    return ROBOTS_PATH.read_text(encoding="utf-8")


def test_index_file_exists():
    assert INDEX_PATH.is_file(), f"index.html absent : {INDEX_PATH}"


def test_robots_file_exists():
    assert ROBOTS_PATH.is_file(), f"robots.txt absent : {ROBOTS_PATH}"


def test_lang_fr():
    assert 'lang="fr"' in _html(), "Attribut lang=\"fr\" absent de <html>"


def test_skip_link_present():
    html = _html()
    assert 'href="#contenu"' in html, "Skip-link vers #contenu absent"


def test_landmark_header():
    assert "<header" in _html(), "Landmark <header> absent"


def test_landmark_nav():
    assert "<nav" in _html(), "Landmark <nav> absent"


def test_landmark_main_with_id():
    assert 'id="contenu"' in _html(), "Landmark <main id=\"contenu\"> absent"
    assert "<main" in _html(), "Landmark <main> absent"


def test_landmark_footer():
    assert "<footer" in _html(), "Landmark <footer> absent"


def test_exactly_one_h1():
    h1_matches = re.findall(r"<h1[\s>]", _html())
    assert len(h1_matches) == 1, f"Exactement 1 <h1> attendu, trouvé : {len(h1_matches)}"


def test_json_ld_parses_and_type_homeandconstructionbusiness():
    """@type attendu : HomeAndConstructionBusiness (sous-type strict de LocalBusiness),
    plus "Organization" (bug corrigé, R9 §1.4 : contradiction avec aeo_engine.py A-08,
    qui exige LocalBusiness — cf. m7_marketing/site/generator.py et guardrail.py G-15)."""
    html = _html()
    match = re.search(
        r'<script\s+type="application/ld\+json">(.*?)</script>',
        html,
        re.DOTALL,
    )
    assert match, "Bloc <script type=\"application/ld+json\"> absent"
    data = json.loads(match.group(1))
    assert data.get("@type") == "HomeAndConstructionBusiness", (
        f"@type attendu: HomeAndConstructionBusiness, obtenu: {data.get('@type')}"
    )


def test_no_external_script():
    assert not re.search(r"<script\s+src", _html(), re.IGNORECASE), (
        "JavaScript externe (<script src) interdit"
    )


def test_robots_user_agent_star():
    assert "User-agent: *" in _robots(), "robots.txt : User-agent: * absent"


def test_robots_allow_root():
    assert "Allow: /" in _robots(), "robots.txt : Allow: / absent"
