"""Revue adverse (num) : analyse des campagnes publicitaires (fixtures FICTIVES).

Défauts trouvés :
- AD-05 (dépassement de budget) ne se déclenchait que si `budget > 0` : une campagne à budget NUL qui dépense 250 $
  était « conforme » avec le fait « dépassement_budget=250 » (contradiction : la dépense sans budget est le pire
  dépassement) ;
- le chargeur ne contrôlait que la PRÉSENCE des champs : un budget texte levait `TypeError`, un coût `.nan` donnait des
  verdicts « conformes » (toutes les comparaisons avec NaN sont fausses), un coût négatif « un dépassement négatif ».
"""

from __future__ import annotations

from pathlib import Path

import pytest
from m7_marketing.ads import ads_loader, intelligence

FICTIF = True
_M7 = Path(__file__).resolve().parents[2]
CALENDRIER = _M7 / "data" / "saisons" / "calendrier-quebec.v1.yaml"
DATE_REF = "2026-07-15T00:00:00+00:00"

MODELE = """fictif: true
plateforme: google_ads
campagnes:
  - campagne: "Campagne test"
    periode: "2026-07"
    fenetre_id: "fw-haute-saison-estivale"
    budget: {budget}
    cout: {cout}
    impressions: {impressions}
    clics: {clics}
    conversions: {conversions}
"""


def _ecrire(tmp_path, **champs):
    valeurs = {"budget": 100, "cout": 50, "impressions": 1000, "clics": 50, "conversions": 5, **champs}
    (tmp_path / "campagne.yaml").write_text(MODELE.format(**valeurs), encoding="utf-8")
    return tmp_path


def _verdict(tmp_path, regle, **champs):
    rapport = intelligence.generate_report(str(_ecrire(tmp_path, **champs)), str(CALENDRIER), DATE_REF)
    return next(v for v in rapport["campagnes"][0]["verdicts"] if v["regle"] == regle)


def test_ad05_une_depense_sans_budget_est_un_depassement(tmp_path):
    verdict = _verdict(tmp_path, "AD-05", budget=0, cout=250)
    assert verdict["verdict"] == "action_proposee" and verdict["action"] == "alerte dépassement budget"
    assert verdict["fait_mesure"] == "dépassement_budget=250"


@pytest.mark.parametrize("budget, cout, attendu", [
    (100, 100, "conforme"), (100, 100.01, "action_proposee"), (100, 99.99, "conforme"),
    (0, 0, "conforme"), (0, 0.01, "action_proposee"), (1000, 800, "conforme"),
])
def test_ad05_bornes_du_depassement(tmp_path, budget, cout, attendu):
    assert _verdict(tmp_path, "AD-05", budget=budget, cout=cout)["verdict"] == attendu


@pytest.mark.parametrize("champ, valeur", [
    ("budget", '"cent"'), ("cout", '"50"'), ("budget", ".nan"), ("cout", ".nan"), ("cout", ".inf"), ("budget", "-5"),
    ("cout", "-0.01"), ("budget", "true"), ("cout", "true"), ("impressions", "1.5"), ("clics", "-1"),
    ("conversions", '"3"'), ("impressions", ".nan"), ("clics", "true"),
])
def test_le_chargeur_refuse_un_champ_numerique_illisible(tmp_path, champ, valeur):
    _ecrire(tmp_path, **{champ: valeur})
    with pytest.raises(ValueError, match=champ):
        ads_loader.load_fixture(str(tmp_path / "campagne.yaml"))


def test_le_chargeur_accepte_les_valeurs_legitimes(tmp_path):
    donnees = ads_loader.load_fixture(str(_ecrire(tmp_path, budget=0, cout=0.0, impressions=0, clics=0, conversions=0)
                                          / "campagne.yaml"))
    assert donnees["campagnes"][0]["budget"] == 0
    donnees = ads_loader.load_fixture(str(_ecrire(tmp_path, budget=1000.5, cout=800.25) / "campagne.yaml"))
    assert donnees["campagnes"][0]["cout"] == 800.25


def test_les_fixtures_du_depot_restent_valides():
    for fixture in ads_loader.load_fixtures(str(_M7 / "fixtures" / "ads")):
        assert fixture["campagnes"]
