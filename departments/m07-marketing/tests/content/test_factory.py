from pathlib import Path
import pytest

_M7 = Path(__file__).resolve().parents[2]

from m7_marketing.content import factory
from m7_marketing.content import validation

BRAND = {
    "name": "OPSYS-AI",
    "tagline": "Automatisation d'entreprise par IA",
    "tone": "professionnel",
    "colors": ["#111111"],
    "langue": "fr",
}

SUJET = {
    "titre": "Toitures au printemps",
    "description": "Préparer sa toiture après l'hiver québécois.",
    "mots_cles": ["toiture", "printemps"],
}

def test_item_conforme():
    """L'item produit passe la validation."""
    item = factory.build_content_item(
        brand=BRAND,
        surface="google_aio",
        type="post_social",
        sujet=SUJET,
        timestamp="2026-07-25T00:00:00+00:00",
    )
    assert validation.validate_content_item(item) is True

def test_determinisme():
    """Deux appels identiques retournent le même dict (id inclus)."""
    args = (BRAND, "google_aio", "post_social", SUJET, "2026-07-25T00:00:00+00:00")
    item1 = factory.build_content_item(*args)
    item2 = factory.build_content_item(*args)
    assert item1 == item2, "Le déterminisme total est requis"

def test_surface_tracee():
    """La surface demandée est reportée et les tactiques correspondantes sont présentes."""
    surface = "google_aio"
    item = factory.build_content_item(
        brand=BRAND,
        surface=surface,
        type="post_social",
        sujet=SUJET,
        timestamp="2026-07-25T00:00:00+00:00",
    )
    assert item["surface"] == surface
    assert isinstance(item["tactics_applied"], list)
    assert len(item["tactics_applied"]) > 0, "Aucune tactique appliquée"
    for t in item["tactics_applied"]:
        assert "tactique" in t
        assert "statut" in t
        assert "source" in t
        assert isinstance(t["statut"], str)
        assert len(t["statut"]) > 0

def test_composition_sans_invention():
    """Le titre et le corps sont une composition exacte des gabarits et données."""
    item = factory.build_content_item(
        brand=BRAND,
        surface="google_aio",
        type="post_social",
        sujet=SUJET,
        timestamp="2026-07-25T00:00:00+00:00",
    )
    titre_attendu = "OPSYS-AI - Toitures au printemps"
    assert item["title"] == titre_attendu, (
        f"Titre attendu : {titre_attendu}, reçu : {item['title']}"
    )
    body_attendu = (
        "Automatisation d'entreprise par IA\n"
        "Préparer sa toiture après l'hiver québécois."
    )
    assert item["body"] == body_attendu, (
        f"Corps attendu : {body_attendu!r}, reçu : {item['body']!r}"
    )


def test_timestamp_transmis():
    """Le timestamp fourni est repris à l'identique, sans horloge interne."""
    ts = "2026-07-25T00:00:00+00:00"
    item = factory.build_content_item(
        brand=BRAND,
        surface="google_aio",
        type="post_social",
        sujet=SUJET,
        timestamp=ts,
    )
    assert item["timestamp"] == ts

def test_statut_initial():
    """L'item est créé en statut PROPOSE avec approver vide."""
    item = factory.build_content_item(
        brand=BRAND,
        surface="google_aio",
        type="post_social",
        sujet=SUJET,
        timestamp="2026-07-25T00:00:00+00:00",
    )
    assert item["approval_status"] == "PROPOSE"
    assert item["approver"] == ""


def test_surface_inconnue_rejetee():
    """build_content_item(..., surface='tiktok', ...) → ValueError."""
    brand = {"name": "TestBrand", "tagline": "Tag", "tone": "neutre", "langue": "fr"}
    sujet = {"titre": "Titre", "description": "Desc"}
    with pytest.raises(ValueError, match="surface invalide"):
        factory.build_content_item(
            brand=brand,
            surface="tiktok",
            type="post_social",
            sujet=sujet,
            timestamp="2026-07-25T00:00:00+00:00",
        )


def test_gabarit_variable_inconnue_rejetee():
    """Un template contenant {hack} doit lever ValueError 'non autorisée'."""
    with pytest.raises(ValueError, match="non autorisée"):
        factory._verifier_gabarit({"title_template": "{hack}", "body_template": "ok"})

    # cas légitime
    factory._verifier_gabarit(
        {"title_template": "{brand_name} - {sujet_titre}", "body_template": "{brand_tagline}"}
    )
