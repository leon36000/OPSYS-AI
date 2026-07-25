"""Tests déterministes (stdlib) pour l'amorce statique du site M7."""

from __future__ import annotations

import json
import os
import re

STATIC_DIR = os.path.join(
    os.path.dirname(__file__), "..", "src", "site", "static"
)
INDEX_PATH = os.path.join(STATIC_DIR, "index.html")
ROBOTS_PATH = os.path.join(STATIC_DIR, "robots.txt")


def _html() -> str:
    with open(INDEX_PATH, encoding="utf-8") as f:
        return f.read()


def _robots() -> str:
    with open(ROBOTS_PATH, encoding="utf-8") as f:
        return f.read()


def test_index_file_exists():
    assert os.path.isfile(INDEX_PATH), f"index.html absent : {INDEX_PATH}"


def test_robots_file_exists():
    assert os.path.isfile(ROBOTS_PATH), f"robots.txt absent : {ROBOTS_PATH}"


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


def test_json_ld_parses_and_type_organization():
    html = _html()
    match = re.search(
        r'<script\s+type="application/ld\+json">(.*?)</script>',
        html,
        re.DOTALL,
    )
    assert match, "Bloc <script type=\"application/ld+json\"> absent"
    data = json.loads(match.group(1))
    assert data.get("@type") == "Organization", (
        f"@type attendu: Organization, obtenu: {data.get('@type')}"
    )


def test_no_external_script():
    assert "<script src" not in _html(), "JavaScript externe (<script src) interdit"


def test_robots_user_agent_star():
    assert "User-agent: *" in _robots(), "robots.txt : User-agent: * absent"


def test_robots_allow_root():
    assert "Allow: /" in _robots(), "robots.txt : Allow: / absent"
