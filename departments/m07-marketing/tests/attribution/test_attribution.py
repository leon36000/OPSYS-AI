import json
from pathlib import Path

import pytest
from m7_marketing.attribution.attribution_engine import (
    charger_et_valider_fixtures,
    attribuer,
    rapport_vers_json,
)
from m7_marketing.utm.utm_engine import valider_lien_utm

# Chemins vers les fixtures réelles du dépôt
FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent / "fixtures"
VISITES_FILE = FIXTURES_DIR / "matomo" / "visites.v1.yaml"
LEADS_FILE = FIXTURES_DIR / "crm" / "leads.v1.yaml"


def test_refus_sans_fictif(tmp_path):
    """Un fichier avec fictif: false doit lever ValueError mentionnant 'fictif'."""
    visites_content = """
fictif: false
visites:
  - visitor_id: v-001
    date: 2026-07-01
    utm_source: google
    utm_medium: organique
    utm_campaign: test
    landing: /test
"""
    crm_content = """
fictif: true
leads:
  - lead_id: l-001
    date: 2026-07-01
    source_declaree: Google
    statut: nouveau
    visitor_id: v-001
"""
    fichier_visites = tmp_path / "visites.yaml"
    fichier_visites.write_text(visites_content)
    fichier_leads = tmp_path / "leads.yaml"
    fichier_leads.write_text(crm_content)

    with pytest.raises(ValueError, match="fictif"):
        charger_et_valider_fixtures(str(fichier_visites), str(fichier_leads))


def test_jointure_multi_touch():
    """l-001 possède plusieurs visites ; première et dernière touche correctement identifiées."""
    visites, leads = charger_et_valider_fixtures(str(VISITES_FILE), str(LEADS_FILE))
    rapport = attribuer(visites, leads, fenetre_jours=30)

    # Par conception des fixtures : l-001 a 3 visites, les deux extrêmes de source 'google'
    par_canal = rapport["par_canal"]
    assert "google" in par_canal
    assert par_canal["google"]["leads_premiere_touche"] >= 1
    assert par_canal["google"]["leads_derniere_touche"] >= 1

    # l-001 ne doit pas être classé comme divergence
    divergences = rapport.get("divergences", [])
    assert not any(div["lead_id"] == "l-001" for div in divergences)


def test_non_attribuable():
    """l-003 (sans visitor_id) et l-004 (visitor_id inconnu) comptés non_attribuables."""
    visites, leads = charger_et_valider_fixtures(str(VISITES_FILE), str(LEADS_FILE))
    rapport = attribuer(visites, leads, fenetre_jours=30)
    assert rapport["non_attribuables"] >= 2

    # Vérification de cohérence : somme des premiers contacts + non_attribuables = total leads
    total_leads = len(leads)
    somme_touches = sum(
        canal["leads_premiere_touche"] for canal in rapport["par_canal"].values()
    )
    assert somme_touches + rapport["non_attribuables"] == total_leads


def test_fenetre_exclut():
    """l-005 a une visite trop ancienne (hors 30j) → non_attribuable.
       Avec fenêtre élargie (365j) il redevient attribuable."""
    visites, leads = charger_et_valider_fixtures(str(VISITES_FILE), str(LEADS_FILE))
    rapport30 = attribuer(visites, leads, fenetre_jours=30)
    rapport365 = attribuer(visites, leads, fenetre_jours=365)

    total_leads = len(leads)
    somme30 = sum(c["leads_premiere_touche"] for c in rapport30["par_canal"].values())
    somme365 = sum(c["leads_premiere_touche"] for c in rapport365["par_canal"].values())

    # Conservation du nombre total de leads
    assert somme30 + rapport30["non_attribuables"] == total_leads
    assert somme365 + rapport365["non_attribuables"] == total_leads

    # l-005 doit faire basculer au moins un lead de non_attribuable → attribué
    assert rapport30["non_attribuables"] > rapport365["non_attribuables"]
    assert somme365 > somme30


def test_divergence_signalee_jamais_tranchee():
    """l-002 déclare 'bouche-à-oreille' mais sa dernière touche est gbp → divergence signalée,
       sans champ de résolution."""
    visites, leads = charger_et_valider_fixtures(str(VISITES_FILE), str(LEADS_FILE))
    rapport = attribuer(visites, leads, fenetre_jours=30)
    divergences = rapport["divergences"]
    div_l002 = [d for d in divergences if d["lead_id"] == "l-002"]
    assert len(div_l002) == 1
    div = div_l002[0]
    assert div["source_declaree"] == "bouche-à-oreille"
    # Dernière (et unique) visite de v-002 = source gbp
    assert div["utm_source"] == "gbp"

    # Aucun champ de verdict
    for champ_interdit in ("verdict", "resolution", "score", "statut_resolution"):
        assert champ_interdit not in div


def test_parse_error_ko(tmp_path):
    """Un YAML malformé doit lever une exception contenant 'parse_error' et une position."""
    malforme = """
fictif: true
visites:
  - visitor_id: v-001
    date: 2026-07-01
    utm_source: google
   utm_medium: organique
"""
    fichier_visites = tmp_path / "visites_mal.yaml"
    fichier_visites.write_text(malforme)
    crm_content = """
fictif: true
leads: []
"""
    fichier_leads = tmp_path / "leads_ok.yaml"
    fichier_leads.write_text(crm_content)

    with pytest.raises(Exception) as excinfo:
        charger_et_valider_fixtures(str(fichier_visites), str(fichier_leads))
    msg = str(excinfo.value).lower()
    assert "parse_error" in msg or "parse error" in msg
    assert "line" in msg or "ligne" in msg or "position" in msg


def test_determinisme():
    """Deux appels identiques doivent produire des rapports bit à bit égaux."""
    visites, leads = charger_et_valider_fixtures(str(VISITES_FILE), str(LEADS_FILE))
    rapport1 = attribuer(visites, leads)
    rapport2 = attribuer(visites, leads)
    assert rapport1 == rapport2

    json1 = rapport_vers_json(rapport1)
    json2 = rapport_vers_json(rapport2)
    assert json1 == json2


def test_aucun_ratio_denominateur_nul():
    """Aucun ratio, taux ou score n'est présent, même pour les canaux sans lead."""
    visites, leads = charger_et_valider_fixtures(str(VISITES_FILE), str(LEADS_FILE))
    rapport = attribuer(visites, leads)
    json_str = rapport_vers_json(rapport)

    # Pas de NaN ni Infinity
    assert "NaN" not in json_str
    assert "Infinity" not in json_str

    data = json.loads(json_str)

    def interdit_cles(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                for mot in ("taux", "ratio", "score"):
                    if mot in k.lower():
                        raise AssertionError(f"Clé interdite trouvée : {k}")
                interdit_cles(v)

    interdit_cles(data)


def test_visites_utm_validees():
    """Chaque visite des fixtures doit être acceptée par le validateur UTM de S012."""
    visites, leads = charger_et_valider_fixtures(str(VISITES_FILE), str(LEADS_FILE))
    for v in visites:
        url = (
            f"https://opsys-ai.ca{v['landing']}"
            f"?utm_source={v['utm_source']}"
            f"&utm_medium={v['utm_medium']}"
            f"&utm_campaign={v['utm_campaign']}"
        )
        verdicts = valider_lien_utm(url)
        fails = [v for v in verdicts if v[1] == "fail"]
        assert not fails, f"Visite {v['visitor_id']} : UTM non conforme S012 : {fails}"
