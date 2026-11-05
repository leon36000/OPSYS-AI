"""Normalisation UTM : table d'alias déclarée, raisons des refus, identifiants de clic écartés, URL hostiles."""

from __future__ import annotations

import pytest
from m7_marketing.mesure import utm

BASE = "https://exemple-fictif.test/page"


@pytest.mark.parametrize(
    "brut,attendu",
    [
        ("fb", "facebook"),
        ("Facebook", "facebook"),
        ("FACEBOOK.COM", "facebook"),
        ("m.facebook.com", "facebook"),
        ("ig", "instagram"),
        ("Instagram.com", "instagram"),
        ("google.com", "google"),
        ("Google Ads", "google"),
        ("google_ads", "google"),
        ("adwords", "google"),
        ("GMB", "gbp"),
        ("Google Business Profile", "gbp"),
        ("lnkd.in", "linkedin"),
        ("TikTok.com", "tiktok"),
        ("perplexity.ai", "perplexity"),
        ("Newsletter", "infolettre"),
        ("Infolettre", "infolettre"),
        ("site", "site"),
    ],
)
def test_chaque_alias_de_source_est_ramene_a_la_convention(brut, attendu):
    r = utm.normaliser_source(brut)
    assert r["normalise"] == attendu and r["verdict"] in (utm.CONFORME, utm.NORMALISABLE)
    assert (r["verdict"] == utm.CONFORME) == (brut == attendu)


@pytest.mark.parametrize(
    "brut,attendu",
    [
        ("PPC", "cpc"),
        ("Paid Search", "cpc"),
        ("paid-social", "cpc"),
        ("Organic", "organique"),
        ("SEO", "organique"),
        ("Social Media", "social"),
        ("Email", "courriel"),
        ("E-mail", "courriel"),
        ("reference", "referral"),
        ("Banner", "display"),
        ("bannière", "display"),
        ("CPC", "cpc"),
    ],
)
def test_chaque_alias_de_medium_est_ramene_a_la_convention(brut, attendu):
    r = utm.normaliser_medium(brut)
    assert r["normalise"] == attendu and r["verdict"] == utm.NORMALISABLE


@pytest.mark.parametrize("brut", ["meta", "Meta", "social", "ads", "direct", "(direct)", "(not set)", "none"])
def test_une_source_ambigue_n_est_pas_devinee(brut):
    r = utm.normaliser_source(brut)
    assert r["verdict"] == utm.NON_NORMALISABLE and r["normalise"] is None
    assert "ambig" in r["raison"] or "aucune source" in r["raison"] or "visite directe" in r["raison"]


@pytest.mark.parametrize("brut", ["blogue-de-mon-oncle", "xyz", "twitter", "", "   "])
def test_une_source_inconnue_est_non_normalisable_jamais_autre(brut):
    r = utm.normaliser_source(brut)
    assert r["verdict"] == utm.NON_NORMALISABLE and r["normalise"] is None and r["raison"]


def test_medium_hors_convention_et_valeurs_hostiles():
    assert utm.normaliser_medium("podcast")["verdict"] == utm.NON_NORMALISABLE
    assert utm.normaliser_source("x" * 101)["verdict"] == utm.NON_NORMALISABLE
    assert "contrôle" in utm.normaliser_source("fa\x00cebook")["raison"]
    assert utm.normaliser_source("face‮book")["verdict"] == utm.NON_NORMALISABLE  # direction cachée
    assert utm.normaliser_source(123)["verdict"] == utm.NON_NORMALISABLE  # type: ignore[arg-type]
    assert utm.normaliser_source(None)["verdict"] == utm.ABSENT


def test_campagne_doit_tomber_sur_le_format_du_contrat():
    ok = utm.normaliser_campagne("fenetre-printemps-2026")
    assert ok["verdict"] == utm.CONFORME and ok["normalise"] == "fenetre-printemps-2026"
    n = utm.normaliser_campagne("Fenêtre Printemps 2026")
    assert n["verdict"] == utm.NORMALISABLE and n["normalise"] == "fenetre-printemps-2026"
    w = utm.normaliser_campagne("workflow_relance_Été_2026")
    assert w["normalise"] == "workflow-relance-ete-2026"
    for mauvais in ("promo-ete", "Brand_2026", "fenetre-2026", "fenetre-x-26", "!!!"):
        r = utm.normaliser_campagne(mauvais)
        assert r["verdict"] == utm.NON_NORMALISABLE and r["normalise"] is None, mauvais
    assert utm.normaliser_campagne("fenetre-" + "a" * 100 + "-2026")["verdict"] == utm.NON_NORMALISABLE


def test_contenu_facultatif_alphabet_du_contrat():
    assert utm.normaliser_contenu("facebook-ab12cd")["verdict"] == utm.CONFORME
    assert utm.normaliser_contenu("Facebook AB12")["normalise"] == "facebook-ab12"
    assert utm.normaliser_contenu("!!!")["verdict"] == utm.NON_NORMALISABLE
    assert utm.normaliser_contenu("a" * 90)["verdict"] == utm.NON_NORMALISABLE


def test_analyse_d_une_url_conforme_normalisable_et_non_normalisable():
    conforme = utm.analyser_url(f"{BASE}?utm_source=facebook&utm_medium=cpc&utm_campaign=fenetre-ete-2026")
    assert conforme["verdict"] == utm.CONFORME and conforme["identifiants_ecartes"] == []
    normalisable = utm.analyser_url(f"{BASE}?UTM_Source=FB&utm_medium=Paid%20Search&utm_campaign=Fenetre%20Ete%202026")
    assert normalisable["verdict"] == utm.NORMALISABLE
    assert normalisable["parametres"]["utm_source"]["normalise"] == "facebook"
    assert normalisable["parametres"]["utm_medium"]["normalise"] == "cpc"
    sans = utm.analyser_url(f"{BASE}?utm_source=facebook&utm_medium=cpc")
    assert sans["verdict"] == utm.NON_NORMALISABLE and sans["parametres"]["utm_campaign"]["verdict"] == utm.ABSENT
    assert utm.analyser_url(BASE)["verdict"] == utm.NON_NORMALISABLE


def test_identifiants_de_clic_signales_par_leur_nom_et_jamais_renvoyes():
    url = (f"{BASE}?utm_source=google&utm_medium=cpc&utm_campaign=fenetre-ete-2026"
           "&gclid=VALEUR-SECRETE-123&fbclid=ABC&MSCLKID=zz")
    r = utm.analyser_url(url)
    assert r["identifiants_ecartes"] == ["MSCLKID", "fbclid", "gclid"]
    assert "VALEUR-SECRETE-123" not in repr(r) and "=ABC" not in repr(r) and "zz" not in repr(r)
    assert url not in repr(r)


def test_parametre_utm_repete_est_refuse():
    r = utm.analyser_url(f"{BASE}?utm_source=google&utm_source=facebook&utm_medium=cpc&utm_campaign=fenetre-a-2026")
    assert r["verdict"] == utm.NON_NORMALISABLE and "répété" in r["raison"]


def test_nom_de_cle_utm_inconnu_est_masque():
    url = (
        f"{BASE}?utm_source=google&utm_medium=cpc&utm_campaign=fenetre-a-2026"
        "&utm_alice%40example.test=x&utm_bob%40example.test=y"
    )
    r = utm.analyser_url(url)
    assert r["utm_inconnus"] == ["nom masqué", "nom masqué"]
    assert "alice@example.test" not in repr(r) and "bob@example.test" not in repr(r) and url not in repr(r)


def test_nom_de_cle_utm_pii_repete_n_est_pas_dans_le_refus():
    url = (
        f"{BASE}?utm_source=google&utm_medium=cpc&utm_campaign=fenetre-a-2026"
        "&utm_alice%40example.test=x&utm_alice%40example.test=y"
    )
    r = utm.analyser_url(url)
    assert r["verdict"] == utm.NON_NORMALISABLE
    assert r["raison"] == "paramètre UTM répété"
    assert "alice@example.test" not in repr(r) and url not in repr(r)


@pytest.mark.parametrize(
    "hostile",
    [
        "javascript:alert(1)",
        "data:text/html,<script>",
        "ftp://exemple.test/?utm_source=google",
        "file:///etc/passwd",
        "https://x.test/?utm_source=goo\x00gle",
        "https://x.test/?" + "a=b&" * 200,
        "https://x.test/" + "a" * 2100,
        "",
        "   ",
        None,
        42,
    ],
)
def test_url_hostile_non_normalisable_sans_exception(hostile):
    r = utm.analyser_url(hostile)
    assert r["verdict"] == utm.NON_NORMALISABLE and r["raison"]


def test_couverture_exacte():
    urls = [
        f"{BASE}?utm_source=google&utm_medium=cpc&utm_campaign=fenetre-a-2026",
        f"{BASE}?utm_source=fb&utm_medium=cpc&utm_campaign=fenetre-a-2026",
        f"{BASE}?utm_source=inconnu&utm_medium=cpc&utm_campaign=fenetre-a-2026",
        BASE,
    ]
    c = utm.analyser_urls(urls)["couverture"]
    assert c == {
        "total": 4,
        "conformes": 1,
        "normalisables": 1,
        "non_normalisables": 2,
        "part_conforme": "0.2500",
        "part_exploitable": "0.5000",
    }
    assert utm.analyser_urls([])["couverture"]["part_conforme"] is None


def test_bornes_de_la_liste():
    assert utm.analyser_urls([BASE] * utm.URLS_MAX)["couverture"]["total"] == 500
    with pytest.raises(ValueError, match="REJ-MESURE-UTM-ENTREE-INVALIDE"):
        utm.analyser_urls([BASE] * (utm.URLS_MAX + 1))
    with pytest.raises(ValueError, match="REJ-MESURE-UTM-ENTREE-INVALIDE"):
        utm.analyser_urls("pas une liste")  # type: ignore[arg-type]


def test_la_table_d_alias_ne_contient_que_des_valeurs_de_la_convention():
    sources, mediums = utm._enums()
    assert set(utm.ALIAS_SOURCE.values()) <= set(sources) and set(utm.ALIAS_MEDIUM.values()) <= set(mediums)
    assert not (set(utm.AMBIGUES) & set(utm.ALIAS_SOURCE))
