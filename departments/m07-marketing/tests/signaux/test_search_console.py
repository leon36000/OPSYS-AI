"""Connecteur Search Console : forme des requêtes, faits exacts, semaines complètes, minimisation, erreurs typées.

Le double parle la forme publique de l'API (R4 §3.2) ; elle n'a JAMAIS été exercée contre le vrai service.
"""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta

import pytest
from fabriques_signaux import JETON, Horloge, coffre_pour, compte, masqueur
from m7_marketing.signaux import curseurs, ingestion, modele, registre, search_console
from m7_marketing.signaux.doubles_search_console import DoubleSearchConsole
from m7_marketing.signaux.erreurs import ErreurSignaux

from opsys import stockage

SITE = "https://www.horizon.example/"


def jours_de(debut: date, fin: date, clics=10):
    sortie, d = {}, debut
    while d <= fin:
        sortie[d.isoformat()] = (d.isoformat(), clics, 200, 0.05, 8.5)
        d += timedelta(days=1)
    return sortie


def banc(**kw):
    serveur = kw.pop("serveur", None) or DoubleSearchConsole(propriete=SITE, jeton=JETON, **kw)
    horloge = Horloge()
    cpt = compte("search_console", SITE)
    con = search_console.ConnecteurSearchConsole(
        serveur, cpt, coffre_pour("search_console").fournisseurs(), maintenant=horloge, masqueur=masqueur()
    )
    return con, serveur, horloge


def fenetre(debut="2026-10-01", fin="2026-10-14"):
    return modele.Fenetre(date.fromisoformat(debut), date.fromisoformat(fin))


def test_les_semaines_completes_sont_celles_qui_tiennent_entierement_dans_la_fenetre():
    # 2026-10-05 est un lundi
    assert search_console.semaines_completes(fenetre("2026-10-01", "2026-10-14")) == [
        (date(2026, 10, 5), date(2026, 10, 11))
    ]
    assert search_console.semaines_completes(fenetre("2026-10-05", "2026-10-18")) == [
        (date(2026, 10, 5), date(2026, 10, 11)),
        (date(2026, 10, 12), date(2026, 10, 18)),
    ]
    assert search_console.semaines_completes(fenetre("2026-10-06", "2026-10-18")) == [
        (date(2026, 10, 12), date(2026, 10, 18))
    ]
    assert search_console.semaines_completes(fenetre("2026-10-05", "2026-10-10")) == []


def test_la_requete_du_flux_jour_est_exactement_celle_de_l_api(base):
    con, serveur, _ = banc(jours=jours_de(date(2026, 10, 1), date(2026, 10, 14)))
    page = con.lire_page("jour", fenetre(), None)
    r = serveur.requetes[0]
    assert (r["methode"], r["chemin"]) == (
        "POST",
        "/webmasters/v3/sites/https%3A%2F%2Fwww.horizon.example%2F/searchAnalytics/query",
    )
    assert r["corps"] == {
        "startDate": "2026-10-01",
        "endDate": "2026-10-14",
        "dimensions": ["date"],
        "rowLimit": 1000,
        "startRow": 0,
        "dataState": "final",
        "type": "web",
    }
    assert r["params"] == {} and JETON not in r["url"] and r["schema_auth"] == "bearer"
    assert len(page.faits) == 14 and page.termine and page.curseur_suivant is None


def test_les_faits_du_jour_ont_les_valeurs_et_la_provenance_du_fournisseur(base):
    con, _, _ = banc(jours={"2026-10-01": ("2026-10-01", 12, 340, 0.035294, 8.2)})
    (f,) = con.lire_page("jour", fenetre("2026-10-01", "2026-10-01"), None).faits
    f = modele.normaliser_fait(f)
    assert f["mesures"] == {"clics": "12", "ctr": "0.035294", "impressions": "340", "position": "8.2"}
    assert (f["nature"], f["portee"], f["periode_debut"], f["periode_fin"]) == (
        "performance_recherche_jour",
        {"type": "site", "ref": "propriete"},
        "2026-10-01",
        "2026-10-01",
    )
    assert f["provenance"]["fournisseur"] == "google" and f["provenance"]["version_api"] == "webmasters/v3"
    assert f["provenance"]["point_acces"] == "searchAnalytics.query" and f["echantillon"] == {
        "nature": "complet",
        "n": None,
    }
    assert f["observe_le"] == "2026-11-01T12:00:00Z" and f["fictif"] is True and f["devise"] is None


def test_la_pagination_se_fait_par_start_row_et_le_curseur_est_lie_a_la_source(base, monkeypatch):
    monkeypatch.setattr(search_console, "LIGNES_JOUR", 5)
    con, serveur, _ = banc(jours=jours_de(date(2026, 10, 1), date(2026, 10, 12)))
    p1 = con.lire_page("jour", fenetre("2026-10-01", "2026-10-12"), None)
    assert not p1.termine and curseurs.decoder_curseur("search_console", p1.curseur_suivant) == {"s": 0, "r": 5}
    p2 = con.lire_page("jour", fenetre("2026-10-01", "2026-10-12"), p1.curseur_suivant)
    p3 = con.lire_page("jour", fenetre("2026-10-01", "2026-10-12"), p2.curseur_suivant)
    assert [r["corps"]["startRow"] for r in serveur.requetes] == [0, 5, 10] and p3.termine
    assert len(p1.faits) + len(p2.faits) + len(p3.faits) == 12
    with pytest.raises(ErreurSignaux) as exc:
        con.lire_page("jour", fenetre(), curseurs.encoder_curseur("bing_webmaster", {"s": 0, "r": 0}))
    assert exc.value.code == "REJ-SIGNAUX-CURSEUR-INVALIDE"


@pytest.mark.parametrize(
    "curseur_donnees", [{"s": -1, "r": 0}, {"s": 0, "r": -5}, {"s": "0", "r": 0}, {"s": 0.5, "r": 0}, {"s": 99, "r": 0}]
)
def test_un_curseur_de_forme_valide_mais_aberrante_est_refuse(base, curseur_donnees):
    con, _, _ = banc()
    mauvais = curseurs.encoder_curseur("search_console", curseur_donnees)
    flux = "requetes" if curseur_donnees.get("s") == 99 else "jour"
    with pytest.raises(ErreurSignaux) as exc:
        con.lire_page(flux, fenetre("2026-10-05", "2026-10-18"), mauvais)
    assert exc.value.code == "REJ-SIGNAUX-CURSEUR-INVALIDE"


def test_un_flux_inconnu_est_refuse(base):
    con, _, _ = banc()
    with pytest.raises(ErreurSignaux):
        con.lire_page("positions_google", fenetre(), None)


def test_les_requetes_et_pages_se_lisent_par_semaine_complete_avec_les_100_premieres_lignes(base):
    con, serveur, _ = banc(
        requetes={"2026-10-05": [("gouttière laval", 5, 100, 0.05, 7.0), ("devis toit", 9, 300, 0.03, 5.5)]},
        pages={"2026-10-05": [("https://www.horizon.example/services/?utm_source=x&email=a@b.test", 4, 90, 0.04, 6.0)]},
    )
    f_ = fenetre("2026-10-01", "2026-10-14")
    pr = con.lire_page("requetes", f_, None)
    corps = serveur.requetes[0]["corps"]
    assert (corps["startDate"], corps["endDate"], corps["dimensions"], corps["rowLimit"]) == (
        "2026-10-05",
        "2026-10-11",
        ["query"],
        100,
    )
    refs = [modele.normaliser_fait(f)["portee"]["ref"] for f in pr.faits]
    assert refs == ["devis toit", "gouttière laval"]  # tri du fournisseur : par clics décroissants
    assert {modele.normaliser_fait(f)["echantillon"]["nature"] for f in pr.faits} == {"anonymise_partiel"}
    assert pr.termine
    pp = con.lire_page("pages", f_, None)
    (page,) = [modele.normaliser_fait(f) for f in pp.faits]
    assert page["portee"] == {"type": "page", "ref": "https://www.horizon.example/services/"}  # paramètres retirés
    assert "email" not in json.dumps(page) and page["echantillon"]["nature"] == "echantillonne"


def test_sans_semaine_complete_le_flux_est_vide_sans_requete(base):
    con, serveur, _ = banc()
    page = con.lire_page("requetes", fenetre("2026-10-05", "2026-10-10"), None)
    assert page.faits == () and page.termine and serveur.nombre_requetes == 0


def test_plusieurs_semaines_sont_lues_a_la_suite_et_le_curseur_avance_de_semaine_en_semaine(base):
    con, serveur, _ = banc(requetes={"2026-10-05": [("a", 1, 10, 0.1, 3.0)], "2026-10-12": [("b", 2, 20, 0.1, 4.0)]})
    f_ = fenetre("2026-10-05", "2026-10-18")
    p1 = con.lire_page("requetes", f_, None)
    assert not p1.termine and curseurs.decoder_curseur("search_console", p1.curseur_suivant) == {"s": 1, "r": 0}
    p2 = con.lire_page("requetes", f_, p1.curseur_suivant)
    assert p2.termine and [r["corps"]["startDate"] for r in serveur.requetes] == ["2026-10-05", "2026-10-12"]


def test_les_requetes_personnelles_sont_masquees_et_les_collisions_comptees(base):
    con, _, _ = banc(
        requetes={
            "2026-10-05": [
                ("écrire à jean.tremblay@exemple.test", 5, 100, 0.05, 7.0),
                ("appeler 514-555-0123 maintenant", 4, 80, 0.05, 7.0),
                ("x" * 250 + "a", 3, 60, 0.05, 7.0),
                ("x" * 250 + "b", 2, 40, 0.05, 7.0),
            ]
        }
    )
    page = con.lire_page("requetes", fenetre("2026-10-01", "2026-10-14"), None)
    sortie = json.dumps([modele.normaliser_fait(f) for f in page.faits], ensure_ascii=False)
    assert "jean.tremblay" not in sortie and "exemple.test" not in sortie and "514-555-0123" not in sortie
    assert "[[COURRIEL:" in sortie and "[[TEL:" in sortie
    assert page.ignores == 1  # les deux longues requêtes se confondent après coupe à 200 caractères


def test_un_jour_hors_periode_ou_une_ligne_mal_formee_est_une_reponse_invalide(base):
    class Double:
        def __init__(self, ligne):
            self.ligne = ligne

        def envoyer(self, requete, *, delai_s=30.0):
            from m7_marketing.signaux.transport import ReponseHttp

            return ReponseHttp(200, {"rows": [self.ligne]})

    for ligne in (
        {"keys": ["2020-01-01"], "clicks": 1, "impressions": 1, "ctr": 1, "position": 1},
        {"keys": [], "clicks": 1, "impressions": 1, "ctr": 1, "position": 1},
        {"keys": ["2026-10-02"], "clicks": "beaucoup", "impressions": 1, "ctr": 1, "position": 1},
        {"keys": ["2026-10-02"], "impressions": 1, "ctr": 1, "position": 1},
        {"keys": ["2026-10-02"], "clicks": True, "impressions": 1, "ctr": 1, "position": 1},
    ):
        con, _, _ = banc(serveur=Double(ligne))
        with pytest.raises(ErreurSignaux) as exc:
            con.lire_page("jour", fenetre(), None)
        assert exc.value.code == "REJ-SIGNAUX-REPONSE-INVALIDE"


def test_une_propriete_inconnue_ou_sans_acces_donne_un_refus_typé_non_reprenable(base):
    con, _, _ = banc(sans_acces=True)
    with pytest.raises(ErreurSignaux) as exc:
        con.lire_page("jour", fenetre(), None)
    assert (exc.value.code, exc.value.reprenable) == ("REJ-SIGNAUX-PERMISSION-REFUSEE", False)
    serveur = DoubleSearchConsole(propriete="https://autre.example/", jeton=JETON)
    con, _, _ = banc(serveur=serveur)
    with pytest.raises(ErreurSignaux) as exc:
        con.lire_page("jour", fenetre(), None)
    assert exc.value.code == "REJ-SIGNAUX-INTROUVABLE"


@pytest.mark.parametrize(
    "scenario,code,reprenable",
    [
        ("401", "REJ-SIGNAUX-AUTH-REFUSEE", False),
        ("403_permission", "REJ-SIGNAUX-PERMISSION-REFUSEE", False),
        ("403_quota", "REJ-SIGNAUX-LIMITE-DEBIT", True),
        ("429", "REJ-SIGNAUX-LIMITE-DEBIT", True),
        ("503", "REJ-SIGNAUX-FOURNISSEUR-INDISPONIBLE", True),
        ("delai", "REJ-SIGNAUX-RESEAU", True),
        ("json_invalide", "REJ-SIGNAUX-REPONSE-INVALIDE", False),
        ("trop_gros", "REJ-SIGNAUX-REPONSE-TROP-GROSSE", False),
        ("exception_secrete", "REJ-SIGNAUX-RESEAU", True),
    ],
)
def test_chaque_panne_du_fournisseur_a_son_refus_et_le_secret_ne_fuit_jamais(base, caplog, scenario, code, reprenable):
    con, serveur, _ = banc(scenario=[scenario], jours=jours_de(date(2026, 10, 1), date(2026, 10, 14)))
    with caplog.at_level(logging.DEBUG), pytest.raises(ErreurSignaux) as exc:
        con.lire_page("jour", fenetre(), None)
    e = exc.value
    assert (e.code, e.reprenable) == (code, reprenable)
    assert JETON not in str(e) and JETON not in repr(e.publique()) and JETON not in caplog.text
    assert JETON not in repr(serveur.requetes)


def test_un_jeton_faux_donne_un_401_sans_rien_ecrire(base):
    serveur = DoubleSearchConsole(
        propriete=SITE, jeton="autre-jeton-fictif", jours=jours_de(date(2026, 10, 1), date(2026, 10, 14))
    )
    con, _, horloge = banc(serveur=serveur)
    bilan = ingestion.tour_flux(con, "jour", maintenant=horloge)
    assert bilan.erreur["code"] == "REJ-SIGNAUX-AUTH-REFUSEE"
    assert list(stockage.maillons(*registre.REGISTRE)) == []


def test_aucune_ecriture_n_est_exposee_par_ce_connecteur():
    assert frozenset({"searchAnalytics.query"}) == search_console.ConnecteurSearchConsole.POINTS_ACCES
    assert frozenset({"searchconsole.googleapis.com"}) == search_console.ConnecteurSearchConsole.HOTES
    quota = search_console.ConnecteurSearchConsole.LIMITES
    assert quota.a_verifier is True and quota.par_minute < 1200 and "R4" in quota.source
