import inspect
import math
import sys
from pathlib import Path

import pytest

_M7 = Path(__file__).resolve().parents[2]
_ADS = _M7 / "src" / "ads"
if str(_ADS) not in sys.path:
    sys.path.insert(0, str(_ADS))

import intelligence  # noqa: E402
import ads_loader  # noqa: E402

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

    c_hiver = next(c for c in report["campagnes"] if c["campagne"] == "GA - Hiver hors saison")
    assert c_hiver["faits_mesures"]["ctr"] == "n_insuffisant"
    assert c_hiver["faits_mesures"]["cpc"] == "n_insuffisant"
    assert c_hiver["faits_mesures"]["cpa"] == "n_insuffisant"

    verdicts = {v["regle"]: v for v in c_hiver["verdicts"]}
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

    import json

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
