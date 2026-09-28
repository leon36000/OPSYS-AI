"""Test consommateur-type (Content Factory v2) contre le contrat gelé v1 — D-015."""

from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# Chargement du contrat
# ---------------------------------------------------------------------------
CONTRACT_PATH = (
    Path(__file__).resolve().parents[1] / "contracts" / "brand-contract.v1.yaml"
)


def load_contract() -> dict:
    with open(CONTRACT_PATH, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


# ---------------------------------------------------------------------------
# Attentes minimales du consommateur (Content Factory)
# ---------------------------------------------------------------------------
REQUIRED_BY_CONSUMER = {"name", "tone", "langue"}
EXPECTED_TYPE = str


def test_contract_supports_consumer_needs():
    """Le contrat doit exposer en string les champs name, tone, langue."""
    contract = load_contract()
    fields = {
        f["name"]: f["type"] for f in contract["profile_schema"]["required_fields"]
    }
    for field in REQUIRED_BY_CONSUMER:
        assert field in fields, f"Champ requis par le consommateur absent du contrat: {field}"
        assert fields[field] == "string", (
            f"Le champ {field} doit être de type string dans le contrat, "
            f"trouvé {fields[field]}"
        )


# ---------------------------------------------------------------------------
# Gel du contrat par hachage SHA-256
# ---------------------------------------------------------------------------
# HASH_GELE = sha256 du fichier brand-contract.v1.yaml en lecture binaire.
# Pour recalculer (en cas de bump de version → nouveau fichier v2) :
# python -c "import hashlib; print(hashlib.sha256(open('<path_to_file>', 'rb').read()).hexdigest())"
HASH_GELE = "2c987a2d88c41c582c56ac6ce823aeaa1880649ab74a027fa6cd4bc170ace469"  # À ÉPINGLER APRÈS GEL


def test_contract_hash_frozen():
    """Le fichier du contrat ne doit pas être modifié sans bump de version + mise à jour du hash."""
    content = CONTRACT_PATH.read_bytes()
    actual_hash = hashlib.sha256(content).hexdigest()
    assert actual_hash == HASH_GELE, (
        f"Le hash du contrat a changé !\n"
        f"Attendu : {HASH_GELE}\n"
        f"Obtenu  : {actual_hash}\n"
        "Si vous avez intentionnellement modifié le contrat, vous devez créer un "
        "nouveau fichier v2 et mettre à jour cette constante HASH_GELE après "
        "revue d'architecture."
    )
