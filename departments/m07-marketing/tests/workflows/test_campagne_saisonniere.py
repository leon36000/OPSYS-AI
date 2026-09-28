import hashlib
import inspect
from pathlib import Path

import pytest
import yaml

_M7 = Path(__file__).resolve().parents[2]

from m7_marketing.workflows import campagne_saisonniere
from m7_marketing.content import approval

CALENDRIER = _M7 / "data" / "saisons" / "calendrier-quebec.v1.yaml"

SHA256_CALENDRIER_V1 = "129160d4e64cca2c8e634cee54bb91bb9b6a4b04539530a790dc3949ca53c82a"  # GEL 2026-07-25 (D-015)


def charger_themes_reels():
    """Charge le YAML et retourne un dict fenetre_id -> nb_themes pour les assertions."""
    with open(CALENDRIER, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    fenetres = data["fenetres_marketing"]
    themes_count = {}
    for fw in fenetres:
        themes_count[fw["id"]] = len(fw["themes"])
    return themes_count


THEMES_PAR_FENETRE = charger_themes_reels()


@pytest.fixture(autouse=True)
def _reset_approval():
    approval.reset()
    yield
    approval.reset()


def _make_iso(date_str: str) -> str:
    return f"{date_str}T00:00:00+00:00"


class TestCampagneSaisonniere:

    def test_juillet_haute_saison(self):
        date_ref_iso = _make_iso("2026-07-15")
        plan = campagne_saisonniere.planifier_campagne_saisonniere(date_ref_iso, str(CALENDRIER))

        assert plan["date_reference"] == date_ref_iso

        fenetres = plan["fenetres_actives"]
        assert len(fenetres) == 1
        fw = fenetres[0]
        assert fw["id"] == "fw-haute-saison-estivale"
        assert fw["mois_debut"] == 6
        assert fw["mois_fin"] == 8
        assert len(fw["themes"]) == THEMES_PAR_FENETRE["fw-haute-saison-estivale"]

        items = plan["items_proposes"]
        assert len(items) == len(fw["themes"])
        item_themes = {item["theme_source"] for item in items}
        assert item_themes == set(fw["themes"])
        for item in items:
            assert item["statut"] == "proposed"
            ci = item["content_item"]
            assert ci["title"]  # non vide
            assert ci["approval_status"] == "PROPOSE"
        # compteurs
        assert plan["compteurs"]["fenetres_actives"] == 1
        assert plan["compteurs"]["items_proposes"] == len(items)
        assert plan["compteurs"]["themes_couverts"] == len(fw["themes"])

    def test_janvier_creux_chevauchement(self):
        date_ref_iso = _make_iso("2026-01-15")
        plan = campagne_saisonniere.planifier_campagne_saisonniere(date_ref_iso, str(CALENDRIER))
        fenetres = plan["fenetres_actives"]
        assert len(fenetres) == 1
        assert fenetres[0]["id"] == "fw-creux-hivernal"
        assert fenetres[0]["mois_debut"] == 12
        assert fenetres[0]["mois_fin"] == 1
        assert len(fenetres[0]["themes"]) == THEMES_PAR_FENETRE["fw-creux-hivernal"]

        items = plan["items_proposes"]
        assert len(items) == THEMES_PAR_FENETRE["fw-creux-hivernal"]
        for item in items:
            assert item["fenetre_id"] == "fw-creux-hivernal"
            assert item["statut"] == "proposed"

    def test_mars_transition(self):
        date_ref_iso = _make_iso("2026-03-15")
        plan = campagne_saisonniere.planifier_campagne_saisonniere(date_ref_iso, str(CALENDRIER))
        fenetres = plan["fenetres_actives"]
        assert len(fenetres) == 1
        assert fenetres[0]["id"] == "fw-transition-hiver-printemps"
        assert fenetres[0]["mois_debut"] == 2
        assert fenetres[0]["mois_fin"] == 3
        assert len(fenetres[0]["themes"]) == THEMES_PAR_FENETRE["fw-transition-hiver-printemps"]

    def test_mai_aucune_fenetre(self):
        date_ref_iso = _make_iso("2026-05-15")
        plan = campagne_saisonniere.planifier_campagne_saisonniere(date_ref_iso, str(CALENDRIER))
        assert plan["fenetres_actives"] == []
        assert plan["items_proposes"] == []
        compteurs = plan["compteurs"]
        assert compteurs["fenetres_actives"] == 0
        assert compteurs["items_proposes"] == 0
        assert compteurs["themes_couverts"] == 0

    def test_determinisme(self):
        date_ref_iso = _make_iso("2026-07-15")
        plan1 = campagne_saisonniere.planifier_campagne_saisonniere(date_ref_iso, str(CALENDRIER))
        approval.reset()
        plan2 = campagne_saisonniere.planifier_campagne_saisonniere(date_ref_iso, str(CALENDRIER))
        assert plan1 == plan2

    def test_propose_only(self, monkeypatch):
        from m7_marketing.content import approval as mod_approval

        # Setup spies
        called_approve = []
        called_publish = []
        monkeypatch.setattr(mod_approval, "approve", lambda *args, **kwargs: called_approve.append(1))
        monkeypatch.setattr(mod_approval, "publish", lambda *args, **kwargs: called_publish.append(1))

        date_ref_iso = _make_iso("2026-07-15")
        plan = campagne_saisonniere.planifier_campagne_saisonniere(date_ref_iso, str(CALENDRIER))

        # Approve/publish never called
        assert not called_approve, "approval.approve should not be called"
        assert not called_publish, "approval.publish should not be called"

        # Check that all items have statut "proposed" and approval_status "PROPOSE"
        for item in plan["items_proposes"]:
            assert item["statut"] == "proposed"
            assert item["content_item"]["approval_status"] == "PROPOSE"

    def test_timestamp_est_la_date_reference(self):
        date_ref_iso = _make_iso("2026-07-15")
        plan = campagne_saisonniere.planifier_campagne_saisonniere(date_ref_iso, str(CALENDRIER))
        for item in plan["items_proposes"]:
            ci = item["content_item"]
            assert ci["timestamp"] == date_ref_iso

    def test_sha256_calendrier_epingle(self):
        # Vérifie l'intégrité du fichier calendrier
        data = CALENDRIER.read_bytes()
        h = hashlib.sha256(data).hexdigest()
        assert h == SHA256_CALENDRIER_V1, f"Hash calendrier changé: {h} (attendu {SHA256_CALENDRIER_V1})"

    def test_zero_reseau(self):
        src = inspect.getsource(campagne_saisonniere)
        forbidden = [
            "urllib", "socket", "http.client", "requests", "httpx",
            "datetime.now", "time.time"
        ]
        for token in forbidden:
            assert token not in src, f"Code interdit trouvé : {token}"
