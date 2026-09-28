from pathlib import Path
import pytest

_M7 = Path(__file__).resolve().parents[2]

from m7_marketing.content import approval

@pytest.fixture(autouse=True)
def clean_approval_file():
    """Réinitialise la file d'approbation avant chaque test."""
    approval.reset()

def _item_base():
    """Retourne un item de base pour les tests d'approbation."""
    return {
        "id": "12345678-1234-4678-1234-567812345678",
        "version": "1.0.0",
        "brand_ref": "aaa",
        "seo_knowledge_ref": "bbb",
        "surface": "google_aio",
        "pillar": "seo",
        "type": "post_social",
        "title": "Titre",
        "body": "Corps",
        "tactics_applied": [],
        "timestamp": "2026-07-25T00:00:00+00:00",
        "approval_status": "PROPOSE",
        "approver": "",
        "approval_timestamp": "",
    }

def test_propose_enregistre_proposer():
    """propose() enregistre le proposer et met le statut PROPOSE."""
    item = _item_base()
    result = approval.propose(item, actor="alice")
    assert result["approval_status"] == "PROPOSE"
    assert result.get("proposer") == "alice"

def test_approve_acteur_distinct():
    """approve() avec un acteur différent du proposer passe à APPROVED."""
    item = _item_base()
    item = approval.propose(item, actor="alice")
    result = approval.approve(item, actor="bob")
    assert result["approval_status"] == "APPROVED"
    assert result["approver"] == "bob"

def test_auto_approbation_interdite():
    """Approuver avec le même acteur que le proposer lève ValueError."""
    item = _item_base()
    item = approval.propose(item, actor="alice")
    with pytest.raises(ValueError, match="auto-approbation"):
        approval.approve(item, actor="alice")

def test_approve_sans_acteur():
    """approve() avec acteur vide lève ValueError."""
    item = _item_base()
    item = approval.propose(item, actor="alice")
    with pytest.raises(ValueError, match="acteur"):
        approval.approve(item, actor="")

def test_reject():
    """reject() passe le statut à REJECTED et trace l'acteur."""
    item = _item_base()
    item = approval.propose(item, actor="alice")
    result = approval.reject(item, actor="bob")
    assert result["approval_status"] == "REJECTED"
    assert result["approver"] == "bob"

def test_resoumission():
    """Un item REJECTED peut être remis en PROPOSE."""
    item = _item_base()
    item = approval.propose(item, actor="alice")
    item = approval.reject(item, actor="bob")
    result = approval.propose(item, actor="alice")
    assert result["approval_status"] == "PROPOSE"
    assert result.get("proposer") == "alice"

def test_publish_fail_closed():
    """publish() lève RuntimeError si le statut n'est pas APPROVED."""
    # Item PROPOSE
    item_propose = _item_base()
    with pytest.raises(RuntimeError, match="APPROVED"):
        approval.publish(item_propose)

    # Item REJECTED
    item_rejected = approval.reject(approval.propose(_item_base(), actor="alice"), actor="bob")
    with pytest.raises(RuntimeError, match="APPROVED"):
        approval.publish(item_rejected)

    # Item APPROVED (ne doit pas lever)
    item_approved = approval.approve(approval.propose(_item_base(), actor="alice"), actor="bob")
    try:
        approval.publish(item_approved)
    except RuntimeError:
        pytest.fail("publish() a levé RuntimeError pour un item APPROVED")

def test_list_items_filtre():
    """list_items() filtre correctement par statut."""
    # Créer deux items avec statuts différents
    item1 = approval.propose(_item_base(), actor="alice")  # PROPOSE
    item2 = _item_base()
    item2["id"] = "87654321-4321-4678-1234-567812345678"
    item2 = approval.approve(approval.propose(item2, actor="alice"), actor="bob")  # APPROVED

    toutes = approval.list_items()
    assert len(toutes) == 2

    proposees = approval.list_items("PROPOSE")
    assert len(proposees) == 1
    assert proposees[0]["id"] == item1["id"]


# Ce fichier est destiné à être lu/recopié (ou inclus) dans la suite de tests.

# Les fonctions suivantes sont à ajouter dans test_approval.py
# ------------------------------------------------------------

def test_transition_enregistre_timestamp():
    """propose alice ; approve(bob, timestamp='...') → approval_timestamp == valeur transmise."""
    item = {
        "id": "12345678-1234-4678-1234-567812345678",
        "version": "1.0.0",
        "brand_ref": "aaa",
        "seo_knowledge_ref": "bbb",
        "surface": "google_aio",
        "pillar": "seo",
        "type": "post_social",
        "title": "Titre",
        "body": "Corps",
        "tactics_applied": [],
        "timestamp": "2026-07-25T00:00:00+00:00",
        "approval_status": "PROPOSE",
        "approver": "",
        "approval_timestamp": "",
    }
    ts = "2026-07-25T01:00:00+00:00"
    item = approval.propose(item, actor="alice")
    result = approval.approve(item, actor="bob", timestamp=ts)
    assert result["approval_timestamp"] == ts
    assert result["approval_status"] == "APPROVED"
    assert result["approver"] == "bob"


def test_auto_rejet_interdit():
    """propose alice ; reject(alice) → ValueError."""
    item = {
        "id": "12345678-1234-4678-1234-567812345678",
        "version": "1.0.0",
        "brand_ref": "aaa",
        "seo_knowledge_ref": "bbb",
        "surface": "google_aio",
        "pillar": "seo",
        "type": "post_social",
        "title": "Titre",
        "body": "Corps",
        "tactics_applied": [],
        "timestamp": "2026-07-25T00:00:00+00:00",
        "approval_status": "PROPOSE",
        "approver": "",
        "approval_timestamp": "",
    }
    item = approval.propose(item, actor="alice")
    with pytest.raises(ValueError, match="auto-rejet"):
        approval.reject(item, actor="alice")


def test_approve_refuse_un_item_jamais_propose():
    """RED — bug corrigé : approve() acceptait auparavant un item FORGÉ, jamais passé par
    propose(), du moment que son champ 'proposer' différait de l'acteur. approve() doit
    refuser tout item dont l'id n'est pas actuellement PROPOSE dans la file."""
    item_jamais_propose = _item_base()
    item_jamais_propose["proposer"] = "quelquun-d-autre"  # forgé à la main, jamais proposé
    with pytest.raises(ValueError, match="jamais proposé"):
        approval.approve(item_jamais_propose, actor="bob")


def test_reject_refuse_un_item_jamais_propose():
    """Même garde-fou pour reject() : un item forgé, jamais dans la file, est refusé."""
    item_jamais_propose = _item_base()
    item_jamais_propose["proposer"] = "quelquun-d-autre"
    with pytest.raises(ValueError, match="jamais proposé"):
        approval.reject(item_jamais_propose, actor="bob")


def test_approve_refuse_un_item_deja_tranche():
    """Un item déjà APPROVED (ou REJECTED) ne peut pas être ré-approuvé sans nouvelle
    proposition explicite : la file n'est plus à l'état PROPOSE pour cet id."""
    item = approval.propose(_item_base(), actor="alice")
    approval.approve(item, actor="bob")
    with pytest.raises(ValueError, match="jamais proposé"):
        approval.approve(item, actor="carol")
