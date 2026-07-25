import sys
from pathlib import Path
import pytest

_M7 = Path(__file__).resolve().parents[2]
_CONTENT = _M7 / "src" / "content"
for p in (str(_CONTENT),):
    if p not in sys.path:
        sys.path.insert(0, p)
import validation  # noqa: E402

def _item_valide():
    """Retourne un dict complet et valide selon le schéma content-item.v1."""
    return {
        "id": "12345678-1234-4678-1234-567812345678",
        "version": "1.0.0",
        "brand_ref": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "seo_knowledge_ref": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "surface": "google_aio",
        "pillar": "seo",
        "type": "post_social",
        "title": "Titre valide",
        "body": "Corps valide",
        "tactics_applied": [
            {"tactique": "mot-clé longue traîne", "statut": "approuvé", "source": "source1"},
        ],
        "timestamp": "2026-07-25T00:00:00+00:00",
        "approval_status": "PROPOSE",
        "approver": "",
        "approval_timestamp": "",
    }

def test_item_valide_passe():
    """Un item complet et correct est accepté."""
    item = _item_valide()
    assert validation.validate_content_item(item) is True

@pytest.mark.parametrize("champ", [
    "id", "version", "brand_ref", "seo_knowledge_ref",
    "surface", "pillar", "type", "title", "body",
    "tactics_applied", "timestamp", "approval_status",
    "approver", "approval_timestamp",
])
def test_champ_manquant_leve_valueerror(champ):
    """L'absence d'un champ obligatoire lève ValueError."""
    item = _item_valide()
    del item[champ]
    with pytest.raises(ValueError, match=rf"{champ}"):
        validation.validate_content_item(item)

@pytest.mark.parametrize("valeur", ["invalide", "google_aio_inconnu", ""])
def test_surface_invalide(valeur):
    item = _item_valide()
    item["surface"] = valeur
    with pytest.raises(ValueError, match="surface"):
        validation.validate_content_item(item)

@pytest.mark.parametrize("valeur", ["invalide", "ppc_social", ""])
def test_pillar_invalide(valeur):
    item = _item_valide()
    item["pillar"] = valeur
    with pytest.raises(ValueError, match="pillar"):
        validation.validate_content_item(item)

@pytest.mark.parametrize("valeur", ["invalide", "post_blog", ""])
def test_type_invalide(valeur):
    item = _item_valide()
    item["type"] = valeur
    with pytest.raises(ValueError, match="type"):
        validation.validate_content_item(item)

def test_title_vide_leve_valueerror():
    item = _item_valide()
    item["title"] = ""
    with pytest.raises(ValueError, match="title"):
        validation.validate_content_item(item)

def test_title_trop_long_leve_valueerror():
    item = _item_valide()
    item["title"] = "a" * 101
    with pytest.raises(ValueError, match="title"):
        validation.validate_content_item(item)

def test_body_vide_leve_valueerror():
    item = _item_valide()
    item["body"] = ""
    with pytest.raises(ValueError, match="body"):
        validation.validate_content_item(item)

def test_body_trop_long_leve_valueerror():
    item = _item_valide()
    item["body"] = "a" * 5001
    with pytest.raises(ValueError, match="body"):
        validation.validate_content_item(item)

def test_id_non_uuidv4_leve_valueerror():
    item = _item_valide()
    item["id"] = "not-a-uuid"
    with pytest.raises(ValueError, match="id"):
        validation.validate_content_item(item)

def test_timestamp_non_iso8601_leve_valueerror():
    item = _item_valide()
    item["timestamp"] = "2026-07-25"  # sans timezone
    with pytest.raises(ValueError, match="timestamp"):
        validation.validate_content_item(item)

def test_approval_status_invalide():
    item = _item_valide()
    item["approval_status"] = "INVALIDE"
    with pytest.raises(ValueError, match="approval_status"):
        validation.validate_content_item(item)

def test_approved_sans_approver_leve_valueerror():
    item = _item_valide()
    item["approval_status"] = "APPROVED"
    item["approver"] = ""
    with pytest.raises(ValueError, match="approver"):
        validation.validate_content_item(item)

def test_tactics_applied_element_sans_tactique():
    item = _item_valide()
    item["tactics_applied"] = [{"statut": "approuvé", "source": "src"}]
    with pytest.raises(ValueError, match="tactique"):
        validation.validate_content_item(item)

def test_tactics_applied_element_sans_statut():
    item = _item_valide()
    item["tactics_applied"] = [{"tactique": "mot-clé", "source": "src"}]
    with pytest.raises(ValueError, match="statut"):
        validation.validate_content_item(item)

def test_tactics_applied_element_sans_source():
    item = _item_valide()
    item["tactics_applied"] = [{"tactique": "mot-clé", "statut": "approuvé"}]
    with pytest.raises(ValueError, match="source"):
        validation.validate_content_item(item)
