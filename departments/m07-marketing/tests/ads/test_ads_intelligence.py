import inspect
import json
import math
from pathlib import Path

import pytest
from m7_marketing.ads import ads_loader, intelligence

_M7 = Path(__file__).resolve().parents[2]

FIXTURES = _M7 / "fixtures" / "ads"
CALENDRIER = _M7 / "data" / "saisons" / "calendrier-quebec.v1.yaml"


def _date_ref(value: str = "2026-07-15") -> str:
    return f"{value}T00:00:00+00:00"


def test_loader_refuse_fictif_false(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text(
        """
fictif: false
plateforme: google_ads
campagnes:
  - campagne: test
    periode: 2026-07
    fenetre_id: fw-haute-saison-estivale
    budget: 100
    cout: 10
    impressions: 1000
    clics: 20
    conversions: 1
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="fictif"):
        ads_loader.load_fixture(str(p))


def test_loader_refuse_plateforme_non_minuscule(tmp_path):
    p = tmp_path / "bad-platform.yaml"
    p.write_text(
        """
fictif: true
plateforme: Google_Ads
campagnes:
  - campagne: test
    periode: 2026-07
    fenetre_id: fw-haute-saison-estivale
    budget: 100
    cout: 10
    impressions: 1000
    clics: 20
    conversions: 1
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="minuscules"):
        ads_loader.load_fixture(str(p))


def test_generate_report_regles_et_actions_proposees():
    report = intelligence.generate_report(str(FIXTURES), str(CALENDRIER), _date_ref())

    assert report["fenetres_actives"] == ["fw-haute-saison-estivale"]
    assert len(report["campagnes"]) == 3

    c_hors_fenetre = next(c for c in report["campagnes"] if c["campagne"] == "GA - Hors fenêtre estivale")
    assert c_hors_fenetre["faits_mesures"]["ctr"] == "n_insuffisant"
    assert c_hors_fenetre["faits_mesures"]["cpc"] == "n_insuffisant"
    assert c_hors_fenetre["faits_mesures"]["cpa"] == "n_insuffisant"

    verdicts = {v["regle"]: v for v in c_hors_fenetre["verdicts"]}
    assert verdicts["AD-03"]["verdict"] == "action_proposee"
    assert verdicts["AD-03"]["action"] == "réallocation"
    assert verdicts["AD-04"]["verdict"] == "action_proposee"
    assert verdicts["AD-04"]["action"] == "pause candidate"
    assert verdicts["AD-05"]["verdict"] == "action_proposee"
    assert "dépassement budget" in verdicts["AD-05"]["action"]

    assert all(r["statut"] == "PROPOSE" for r in report["recommandations"])


def test_divisions_ne_produisent_ni_inf_ni_nan():
    report = intelligence.generate_report(str(FIXTURES), str(CALENDRIER), _date_ref())

    for campagne in report["campagnes"]:
        for value in campagne["faits_mesures"].values():
            if isinstance(value, str):
                assert value == "n_insuffisant"
            else:
                assert not math.isinf(value)
                assert not math.isnan(value)


def test_determinisme_et_sans_score():
    date_ref = _date_ref()
    report1 = intelligence.generate_report(str(FIXTURES), str(CALENDRIER), date_ref)
    report2 = intelligence.generate_report(str(FIXTURES), str(CALENDRIER), date_ref)
    assert report1 == report2

    report_json = json.dumps(report1).lower()
    assert "score" not in report_json


def test_rules_ad_01_a_ad_06_toujours_presentes():
    report = intelligence.generate_report(str(FIXTURES), str(CALENDRIER), _date_ref())
    for campagne in report["campagnes"]:
        regles = [v["regle"] for v in campagne["verdicts"]]
        assert regles == ["AD-01", "AD-02", "AD-03", "AD-04", "AD-05", "AD-06"]


def test_zero_reseau():
    for mod in (ads_loader, intelligence):
        source = inspect.getsource(mod)
        for token in ("urllib", "socket", "http.client", "requests", "httpx"):
            assert token not in source


def test_ad01_chemin_conforme():
    """Une campagne avec CTR, CPC, CPA calculables doit obtenir AD-01 conforme."""
    report = intelligence.generate_report(str(FIXTURES), str(CALENDRIER), _date_ref())
    campagne = next(
        c for c in report["campagnes"] if c["campagne"] == "GA - Été visibilité"
    )
    ad01 = next(v for v in campagne["verdicts"] if v["regle"] == "AD-01")
    assert ad01["verdict"] == "conforme"


def test_ad02_plateforme_conforme():
    """AD-02 vérifie la cohérence d'entonnoir (clics <= impressions, conversions <= clics),
    jamais vacuously conforme du seul fait que la plateforme est déjà valide (bug corrigé :
    auparavant AD-02 était systématiquement 'conforme', quelles que soient les données)."""
    report = intelligence.generate_report(str(FIXTURES), str(CALENDRIER), _date_ref())
    campagne = next(
        c for c in report["campagnes"] if c["plateforme"] == "google_ads"
    )
    ad02 = next(v for v in campagne["verdicts"] if v["regle"] == "AD-02")
    assert ad02["verdict"] == "conforme"
    assert "impressions=" in ad02["fait_mesure"]


def test_ad02_entonnoir_incoherent_est_non_conforme(tmp_path):
    """RED : une campagne avec plus de clics que d'impressions (entonnoir impossible)
    doit être détectée par AD-02 — avant le correctif, AD-02 restait 'conforme' quelles
    que soient les données mesurées (jamais vérifié, seulement la plateforme)."""
    f = tmp_path / "entonnoir_casse.yaml"
    f.write_text(
        """fictif: true
plateforme: google_ads
campagnes:
  - campagne: "Entonnoir impossible"
    periode: "2026-07"
    fenetre_id: "fw-haute-saison-estivale"
    budget: 100
    cout: 50
    impressions: 10
    clics: 999
    conversions: 1
""",
        encoding="utf-8",
    )
    report = intelligence.generate_report(str(tmp_path), str(CALENDRIER), _date_ref())
    campagne = report["campagnes"][0]
    ad02 = next(v for v in campagne["verdicts"] if v["regle"] == "AD-02")
    assert ad02["verdict"] == "non_conforme"
    assert any(r["regle"] == "AD-02" for r in report["recommandations"] if r["campagne"] == campagne["campagne"])


def test_ad06_seuil_attention():
    """La campagne 'GA - Été visibilité' consomme exactement 80 % du budget -> AD-06 attention."""
    report = intelligence.generate_report(str(FIXTURES), str(CALENDRIER), _date_ref())
    campagne = next(
        c for c in report["campagnes"] if c["campagne"] == "GA - Été visibilité"
    )
    ad06 = next(v for v in campagne["verdicts"] if v["regle"] == "AD-06")
    assert ad06["verdict"] == "attention"
    assert ad06["fait_mesure"] == "consommation_budget=0.8"


def test_ad06_budget_nul_ou_negatif(tmp_path):
    """Avec budget=0, AD-06 doit retourner 'attention' et fait_mesure='budget=0'."""
    f = tmp_path / "zero_budget.yaml"
    f.write_text(
        """fictif: true
plateforme: google_ads
campagnes:
  - campagne: "Budget zero"
    periode: "2026-07"
    fenetre_id: "fw-haute-saison-estivale"
    budget: 0
    cout: 0
    impressions: 10000
    clics: 200
    conversions: 5
""",
        encoding="utf-8",
    )
    report = intelligence.generate_report(str(tmp_path), str(CALENDRIER), _date_ref())
    campagne = report["campagnes"][0]
    ad06 = next(v for v in campagne["verdicts"] if v["regle"] == "AD-06")
    assert ad06["verdict"] == "attention"
    assert ad06["fait_mesure"] == "budget=0"


def test_chemins_conformes_ad03_04_05():
    """La campagne 'META - Remarketing été' est entièrement saine -> AD-03/04/05 conformes."""
    report = intelligence.generate_report(str(FIXTURES), str(CALENDRIER), _date_ref())
    campagne = next(
        c for c in report["campagnes"]
        if c["campagne"] == "META - Remarketing été"
    )
    for regle in ("AD-03", "AD-04", "AD-05"):
        v = next(v for v in campagne["verdicts"] if v["regle"] == regle)
        assert v["verdict"] == "conforme", f"Échec {regle}"


def test_conforme_sans_recommandation():
    """Les campagnes sans verdict non conforme ne génèrent aucune recommandation."""
    report = intelligence.generate_report(str(FIXTURES), str(CALENDRIER), _date_ref())
    # Identifier les campagnes 100 % conformes
    campagnes_conformes = {
        c["campagne"]
        for c in report["campagnes"]
        if all(v["verdict"] == "conforme" for v in c["verdicts"])
    }
    # Vérifier qu'aucune recommandation ne pointe vers ces campagnes
    for rec in report["recommandations"]:
        assert (
            rec["campagne"] not in campagnes_conformes
        ), f"Recommandation inattendue pour {rec['campagne']}"

    # Double vérification : la campagne clean connue doit être dans l'ensemble
    assert "META - Remarketing été" in campagnes_conformes
