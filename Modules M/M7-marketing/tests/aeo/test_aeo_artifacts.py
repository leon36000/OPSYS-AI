import sys
from pathlib import Path
_M7 = Path(__file__).resolve().parents[2]
for p in (str(_M7 / "src" / "aeo"), str(_M7 / "src" / "content")):
    if p not in sys.path:
        sys.path.insert(0, p)
import aeo_engine  # noqa: E402

import pytest
import yaml
import tempfile
import os
import inspect

SEO_KNOWLEDGE_PATH = _M7 / "docs" / "seo-knowledge.v1.yaml"
TIMESTAMP = "2026-07-25T00:00:00+00:00"
SITE_HTML_PATH = _M7 / "src" / "site" / "static" / "index.html"
BRAND_PROFILE_PATH = _M7 / "src" / "brand" / "profile.yaml"


def test_load_seo_knowledge_reel():
    data, sha = aeo_engine.load_seo_knowledge(SEO_KNOWLEDGE_PATH)
    assert isinstance(data, dict)
    assert 'surfaces' in data
    assert isinstance(sha, str)
    assert len(sha) == 64
    assert all(c in '0123456789abcdef' for c in sha)


def test_site_artifact_reel():
    ts = "2026-07-01T00:00:00Z"
    artifact = aeo_engine.build_site_artifact(SITE_HTML_PATH, SEO_KNOWLEDGE_PATH, ts)
    assert isinstance(artifact, dict)
    assert 'html' in artifact
    assert artifact['html']
    assert 'jsonld' in artifact
    assert isinstance(artifact['jsonld'], list)
    assert len(artifact['jsonld']) > 0
    assert artifact.get('timestamp') == ts


BRAND_PROFILE_PATH = _M7 / "src" / "brand" / "profile.yaml"

def test_item_artifact_reel():
    import factory

    with open(BRAND_PROFILE_PATH, 'r') as f:
        brand = yaml.safe_load(f)

    sujet = {
        "titre": "Toitures au printemps",
        "description": "Préparer sa toiture après l'hiver québécois.",
        "mots_cles": ["toiture"],
    }
    item = factory.build_content_item(
        brand,
        surface="google_aio",
        type="post_social",
        sujet=sujet,
        timestamp=TIMESTAMP,
    )
    artifact = aeo_engine.build_item_artifact(item, SEO_KNOWLEDGE_PATH, TIMESTAMP)
    assert item["title"] in artifact["html"]
    assert item["body"] in artifact["html"]
    assert artifact["content_item"] is item



def test_html_malforme_ko():
    with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as f:
        f.write("<html><head><title>Unclosed</head><body><p>Content")
        malformed_path = f.name
    try:
        with pytest.raises(ValueError, match="parse_error"):
            aeo_engine.build_site_artifact(malformed_path, SEO_KNOWLEDGE_PATH, "2026-01-01T00:00:00Z")
    finally:
        os.unlink(malformed_path)


def test_zero_reseau():
    src = inspect.getsource(aeo_engine)
    forbidden = ['urllib', 'socket', 'http.client', 'requests', 'httpx']
    for mod in forbidden:
        assert mod not in src, f"Forbidden import {mod} found in aeo_engine"
