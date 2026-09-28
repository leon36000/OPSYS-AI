import sys
from pathlib import Path
import hashlib
import yaml

_M7 = Path(__file__).resolve().parents[2]
_CONTRACTS = _M7 / "contracts"
_CONTRACT_YAML = _CONTRACTS / "content-item.v1.yaml"
_SHA256_FILE = _CONTRACTS / "content_item_v1.sha256"
SHA256_CONTENT_ITEM_V1 = "668f388274ce73ee453917f510ddae0bcad745556adb98f72fd66095ebb13298"  # GEL 2026-07-25 (D-015)

def test_contrat_present():
    """Le fichier de contrat doit exister (RED tant qu'il n'est pas livré)."""
    assert _CONTRACT_YAML.is_file(), f"Contrat absent : {_CONTRACT_YAML}"

def test_contrat_sha256_epingle():
    """Le sha256 du fichier doit correspondre à la constante épinglée."""
    assert _SHA256_FILE.is_file(), f"Fichier sha256 absent : {_SHA256_FILE}"
    hash_attendu = _SHA256_FILE.read_text().strip()
    assert hash_attendu == SHA256_CONTENT_ITEM_V1, (
        f"Le sha256 épinglé ne correspond pas : attendu {SHA256_CONTENT_ITEM_V1}, "
        f"trouvé {hash_attendu}"
    )
    contenu = _CONTRACT_YAML.read_bytes()
    sha256_calcule = hashlib.sha256(contenu).hexdigest()
    assert sha256_calcule == SHA256_CONTENT_ITEM_V1, (
        f"Le sha256 du contrat ({sha256_calcule}) ne correspond pas à la constante épinglée."
    )

def test_contrat_immuable_champs():
    """Le YAML doit déclarer les 14 champs obligatoires de l'ADR."""
    contenu = _CONTRACT_YAML.read_text(encoding="utf-8")
    doc = yaml.safe_load(contenu)
    assert doc is not None, "Le contrat est vide"
    champs_obligatoires = [
        "id", "version", "brand_ref", "seo_knowledge_ref",
        "surface", "pillar", "type", "title", "body",
        "tactics_applied", "timestamp", "approval_status",
        "approver", "approval_timestamp",
    ]
    for champ in champs_obligatoires:
        assert champ in doc, f"Champ obligatoire manquant dans le contrat : {champ}"
