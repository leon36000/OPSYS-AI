import hashlib
from pathlib import Path

from m7_marketing.attribution.attribution_engine import attribuer, charger_et_valider_fixtures

FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent / "fixtures"
VISITES_PATH = FIXTURES_DIR / "matomo" / "visites.v1.yaml"
LEADS_PATH = FIXTURES_DIR / "crm" / "leads.v1.yaml"

# À geler après génération des fixtures
SHA256_VISITES_V1 = "b4728e35d363250585569131ab0121b784d998c09618cc373a397d29db077b4b"  # GEL 2026-07-26
SHA256_LEADS_V1 = "7597f5ef9f204433f7048f2192c567b610c7554702df97c203a1167d04669628"  # GEL 2026-07-26


def test_sha256_epingles():
    """Les empreintes des fixtures doivent correspondre aux constantes gelées."""
    h_visites = hashlib.sha256(VISITES_PATH.read_bytes()).hexdigest()
    h_leads = hashlib.sha256(LEADS_PATH.read_bytes()).hexdigest()
    assert h_visites == SHA256_VISITES_V1, f"Hash actuel visites : {h_visites}"
    assert h_leads == SHA256_LEADS_V1, f"Hash actuel leads : {h_leads}"


def test_lecture_seule():
    """Les fichiers de fixtures ne doivent pas être altérés par le pipeline (D-043)."""
    h_visites_avant = hashlib.sha256(VISITES_PATH.read_bytes()).hexdigest()
    h_leads_avant = hashlib.sha256(LEADS_PATH.read_bytes()).hexdigest()

    visites, leads = charger_et_valider_fixtures(str(VISITES_PATH), str(LEADS_PATH))
    _ = attribuer(visites, leads)

    h_visites_apres = hashlib.sha256(VISITES_PATH.read_bytes()).hexdigest()
    h_leads_apres = hashlib.sha256(LEADS_PATH.read_bytes()).hexdigest()
    assert h_visites_avant == h_visites_apres
    assert h_leads_avant == h_leads_apres
