"""Connecteur Bing Webmaster : requêtes exactes, faits aux valeurs calculées à la main, idempotence et révisions,
erreurs typées, secret absent de tout, quota local, minimisation. Double fictif (forme d'API jamais exercée contre le
vrai service).
"""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta

import pytest
from fabriques_signaux import JETON, Horloge, coffre_pour, compte
from m7_marketing.signaux import bing_webmaster as bw
from m7_marketing.signaux import curseurs, ingestion, modele, registre
from m7_marketing.signaux.doubles_bing_webmaster import DoubleBingWebmaster, date_ms
from m7_marketing.signaux.erreurs import ErreurSignaux
from m7_marketing.signaux.quotas import LimiteurQuota, Quota
from m7_marketing.signaux.transport import RequeteHttp
from sqlalchemy import select

from opsys import stockage
from opsys.stockage.schema import EVENEMENTS_SORTANTS, REGISTRES

SITE = "https://www.horizon.example/"
URL = "https://ssl.bing.com/webmaster/api.svc/json/"


class Capteur:
    """Transport enveloppe : garde les objets `RequeteHttp` (avec leur authentification) pour les inspecter."""

    def __init__(self, interne):
        self.interne, self.requetes = interne, []

    def envoyer(self, requete, *, delai_s=30.0):
        self.requetes.append(requete)
        return self.interne.envoyer(requete, delai_s=delai_s)


def _jours():
    debut, jours = date(2026, 9, 20), {}
    while debut <= date(2026, 10, 31):
        jours[debut.isoformat()] = (200, 10)
        debut += timedelta(days=1)
    del jours["2026-10-10"]  # un jour sans donnée
    jours["2026-10-12"] = (3, 1)
    return jours


REQUETES = [
    ("2026-09-27", "avant la première semaine", 50, 5, 1.0, 1.0),
    ("2026-09-28", "gouttière laval", 100, 5, 6.0, 7.0),
    ("2026-09-30", "gouttière laval", 300, 15, 5.0, 8.0),
    ("2026-10-01", "contact jean.tremblay@example.test 514-555-0123", 20, 1, 9.0, 9.0),
    ("2026-10-06", "solo", 10, 2, 2.0, 2.0),
    ("2026-10-27", "semaine incomplète", 40, 4, 3.0, 3.0),
]
PAGES = [("2026-09-29", "https://www.horizon.example/services?x=1&courriel=a@b.example", 10, 1, 3.0, 4.0)]


def _monter(*, scenario=(), requetes=REQUETES, pages=PAGES, jours=None, limiteur=None, fictif=True, **kw):
    horloge = Horloge()
    srv = DoubleBingWebmaster(propriete=SITE, jeton=JETON, jours=_jours() if jours is None else jours,
                              requetes=requetes, pages=pages, scenario=scenario, **kw)
    capteur = Capteur(srv)
    coffre = coffre_pour(modele.BING_WEBMASTER)
    from fabriques_signaux import masqueur
    con = bw.ConnecteurBingWebmaster(capteur, compte(modele.BING_WEBMASTER, SITE, fictif=fictif), coffre.fournisseurs(),
                                     maintenant=horloge, masqueur=masqueur(), limiteur=limiteur)
    return con, srv, capteur, coffre, horloge


def _faits(nature=None):
    tous = registre.courants(registre.charger(stockage.maillons(*registre.REGISTRE))).values()
    return sorted((f for f in tous if nature is None or f["nature"] == nature),
                  key=lambda f: (f["nature"], f["periode_debut"], f["portee"]["ref"]))


def _tout_le_texte() -> str:
    with stockage.transaction() as cnx:
        lignes = [r.maillon for r in cnx.execute(select(REGISTRES.c.maillon)).all()]
        lignes += [r.charge for r in cnx.execute(select(EVENEMENTS_SORTANTS.c.charge)).all()]
    return "\n".join(lignes)


def test_la_forme_exacte_des_requetes_et_le_secret_hors_de_l_url(base):
    con, srv, capteur, _, horloge = _monter()
    ingestion.tour_ingestion(con, maintenant=horloge)
    assert [(r["methode"], r["url"], r["params"], r["corps"], r["schema_auth"]) for r in srv.requetes] == [
        ("GET", URL + "GetRankAndTrafficStats", {"siteUrl": SITE}, None, "parametre"),
        ("GET", URL + "GetQueryStats", {"siteUrl": SITE}, None, "parametre"),
        ("GET", URL + "GetPageStats", {"siteUrl": SITE}, None, "parametre"),
    ]
    for requete in capteur.requetes:
        assert JETON not in requete.url and JETON not in json.dumps(dict(requete.params)) and JETON not in repr(requete)
        assert requete.authentification.nom == "apikey" and requete.authentification.valeur == JETON
        assert JETON not in repr(requete.authentification)
    assert srv.methodes() == {"GET"}


def test_les_faits_par_jour_sont_calcules_et_un_jour_sans_donnee_n_est_pas_un_zero(base):
    con, _, _, _, horloge = _monter()
    bilan = ingestion.tour_ingestion(con, maintenant=horloge)["flux"][0]
    assert bilan["statut"] == "termine" and bilan["fenetre"] == "2026-09-26/2026-10-30"
    assert bilan["faits_nouveaux"] == 34
    jours = {f["periode_debut"]: f for f in _faits("performance_recherche_jour")}
    assert len(jours) == 34 and "2026-10-10" not in jours  # le trou reste un trou
    assert "2026-09-25" not in jours and "2026-10-31" not in jours  # hors fenêtre : ignorés
    assert jours["2026-10-01"]["mesures"] == {"clics": "10", "ctr": "0.05", "impressions": "200"}
    assert jours["2026-10-12"]["mesures"] == {"clics": "1", "ctr": "0.333333", "impressions": "3"}
    exemple = jours["2026-10-01"]
    assert exemple["source"] == "bing_webmaster" and exemple["portee"] == {"type": "site", "ref": "propriete"}
    assert exemple["echantillon"] == {"nature": "complet", "n": None} and exemple["fictif"] is True
    assert exemple["provenance"]["mode"] == "api_lecture" and exemple["provenance"]["fournisseur"] == "microsoft"
    assert exemple["provenance"]["point_acces"] == "GetRankAndTrafficStats"


def test_les_requetes_sont_agregees_par_semaine_complete_avec_position_ponderee(base):
    con, _, _, _, horloge = _monter()
    ingestion.tour_ingestion(con, maintenant=horloge)
    faits = {(f["periode_debut"], f["portee"]["ref"]): f for f in _faits("requetes_periode")}
    # semaine du 28 septembre : 100 + 300 impressions, 5 + 15 clics ; position (100×7 + 300×8) ÷ 400 = 7,75
    laval = faits[("2026-09-28", "gouttière laval")]
    assert laval["periode_fin"] == "2026-10-04"
    assert laval["mesures"] == {"clics": "20", "ctr": "0.05", "impressions": "400", "position": "7.75"}
    assert laval["echantillon"]["nature"] == "anonymise_partiel"
    assert faits[("2026-10-05", "solo")]["mesures"]["clics"] == "2"
    refs = {ref for _, ref in faits}
    assert "avant la première semaine" not in refs and "semaine incomplète" not in refs
    assert len(faits) == 3


def test_les_renseignements_personnels_des_requetes_et_des_pages_sont_masques(base):
    con, _, _, _, horloge = _monter()
    ingestion.tour_ingestion(con, maintenant=horloge)
    texte = _tout_le_texte()
    assert "jean.tremblay" not in texte and "514-555-0123" not in texte and "a@b.example" not in texte
    refs = {f["portee"]["ref"] for f in _faits("requetes_periode")}
    assert any("[[COURRIEL:" in r and "[[TEL:" in r for r in refs)
    pages = _faits("pages_periode")
    assert [f["portee"]["ref"] for f in pages] == ["https://www.horizon.example/services"]  # paramètres retirés
    assert pages[0]["echantillon"]["nature"] == "echantillonne"


def test_deux_requetes_qui_se_confondent_apres_minimisation_comptent_un_ignore_sans_conflit(base):
    long1 = "x" * 200 + "première fin"
    long2 = "x" * 200 + "seconde fin"
    lignes = [("2026-10-06", long1, 100, 9, 1.0, 1.0), ("2026-10-07", long2, 50, 4, 1.0, 1.0)]
    con, _, _, _, horloge = _monter(requetes=lignes)
    bilan = ingestion.tour_ingestion(con, maintenant=horloge)["flux"][1]
    assert bilan["statut"] == "termine" and bilan["faits_nouveaux"] == 1 and bilan["ignores"] == 1
    assert len(_faits("requetes_periode")) == 1


def test_idempotence_et_revision_quand_le_fournisseur_change_une_valeur(base):
    con, srv, _, _, horloge = _monter()
    ingestion.tour_ingestion(con, maintenant=horloge)
    avant = len(stockage.maillons(*registre.REGISTRE))
    horloge.avancer(days=1)  # nouvelle fenêtre (le repère a avancé) : les jours déjà lus sont relus, identiques
    second = ingestion.tour_ingestion(con, maintenant=horloge)["flux"][0]
    assert second["fenetre"] == "2026-10-17/2026-10-31"
    assert second["faits_nouveaux"] == 1 and second["faits_revises"] == 0 and second["faits_inchanges"] == 14
    assert len(stockage.maillons(*registre.REGISTRE)) == avant + 1  # seul le 31 octobre est nouveau
    srv.reviser_jour("2026-10-20", 500, 25)  # Bing révise un jour déjà lu
    horloge.avancer(days=1)
    revise = ingestion.tour_ingestion(con, maintenant=horloge)["flux"][0]
    assert revise["faits_revises"] == 1
    fait = next(f for f in _faits("performance_recherche_jour") if f["periode_debut"] == "2026-10-20")
    assert fait["revision"] == 2 and fait["mesures"]["clics"] == "25" and fait["mesures"]["ctr"] == "0.05"
    assert registre.charger(stockage.maillons(*registre.REGISTRE))  # chaîne intacte


def test_l_evenement_au_bus_ne_porte_aucune_valeur(base):
    con, _, _, _, horloge = _monter()
    ingestion.tour_ingestion(con, maintenant=horloge)
    with stockage.transaction() as cnx:
        charges = [json.loads(r.charge) for r in cnx.execute(
            select(EVENEMENTS_SORTANTS.c.charge).where(
                EVENEMENTS_SORTANTS.c.type_evenement == "m7.signaux_marketing_constates")).all()]
    assert len(charges) == 3 and {c["source"] for c in charges} == {"bing_webmaster"}
    assert all("mesures" not in str(c) and "clics" not in str(c) for c in charges)


@pytest.mark.parametrize(("scenario", "code", "reprenable"), [
    ("401", "REJ-SIGNAUX-AUTH-REFUSEE", False),
    ("403_permission", "REJ-SIGNAUX-PERMISSION-REFUSEE", False),
    ("403_quota", "REJ-SIGNAUX-LIMITE-DEBIT", True),
    ("429", "REJ-SIGNAUX-LIMITE-DEBIT", True),
    ("503", "REJ-SIGNAUX-FOURNISSEUR-INDISPONIBLE", True),
    ("delai", "REJ-SIGNAUX-RESEAU", True),
    ("exception_secrete", "REJ-SIGNAUX-RESEAU", True),
    ("json_invalide", "REJ-SIGNAUX-REPONSE-INVALIDE", False),
    ("trop_gros", "REJ-SIGNAUX-REPONSE-TROP-GROSSE", False),
])
def test_une_erreur_typee_s_inscrit_sans_avancer_le_curseur_et_sans_fuite(base, caplog, scenario, code, reprenable):
    con, _, _, coffre, horloge = _monter(scenario=[scenario])
    with caplog.at_level(logging.DEBUG):
        bilan = ingestion.tour_flux(con, "jour", maintenant=horloge)
    assert bilan.statut == "echec" and bilan.erreur["code"] == code and bilan.erreur["reprenable"] is reprenable
    if scenario == "429":
        assert bilan.erreur["reessayer_apres_s"] == 17
    etat = curseurs.lire_etats(stockage.maillons(*registre.REGISTRE_CURSEURS))["bing_webmaster|principal|jour"]
    assert etat.termine is False and etat.watermark is None and etat.derniere_lecture_reussie_le is None
    assert etat.echec()["code"] == code and etat.curseur is None
    assert JETON not in json.dumps(bilan.erreur) and JETON not in caplog.text and JETON not in _tout_le_texte()
    assert coffre.ouverts == 0 and coffre.ouvertures["principal"] == 1  # le coffre est refermé même en erreur
    assert _faits() == []


def test_apres_un_echec_la_reprise_relit_la_meme_fenetre_et_efface_l_echec(base):
    con, _, _, _, horloge = _monter(scenario=["503"])
    assert ingestion.tour_flux(con, "jour", maintenant=horloge).statut == "echec"
    horloge.avancer(minutes=5)
    bilan = ingestion.tour_flux(con, "jour", maintenant=horloge)
    assert bilan.statut == "termine" and bilan.faits_nouveaux == 34
    etat = curseurs.lire_etats(stockage.maillons(*registre.REGISTRE_CURSEURS))["bing_webmaster|principal|jour"]
    assert etat.echec() is None and etat.watermark == "2026-10-30"


def test_le_format_de_date_inconnu_est_refuse_pas_devine(base):
    con, _, _, _, horloge = _monter(dates_brutes=True)
    bilan = ingestion.tour_flux(con, "jour", maintenant=horloge)
    assert bilan.statut == "echec" and bilan.erreur["code"] == "REJ-SIGNAUX-REPONSE-INVALIDE"
    assert _faits() == []


def test_le_decodage_des_dates_ms_en_jour_utc():
    assert bw.jour_depuis_ms(date_ms("2026-10-01")) == date(2026, 10, 1)
    assert bw.jour_depuis_ms("/Date(1696118400000+0000)/") == date(2023, 10, 1)
    for mauvais in ("2026-10-01", "/Date(abc)/", "Date(1)", 12, None, "/Date(99999999999999999)/"):
        with pytest.raises(ErreurSignaux) as exc:
            bw.jour_depuis_ms(mauvais)
        assert exc.value.code == "REJ-SIGNAUX-REPONSE-INVALIDE"


def test_un_jour_repete_ou_plus_de_clics_que_d_impressions_est_refuse(base):
    con, _, _, _, horloge = _monter(jours={"2026-10-01": (5, 9)})
    assert ingestion.tour_flux(con, "jour", maintenant=horloge).erreur["code"] == "REJ-SIGNAUX-REPONSE-INVALIDE"


def test_aucune_semaine_complete_aucune_requete(base):
    con, srv, _, _, _ = _monter()
    page = con.lire_page("requetes", modele.Fenetre(date(2026, 10, 26), date(2026, 10, 30)), None)
    assert page.faits == () and page.termine and srv.nombre_requetes == 0 and page.appels == 0


def test_aucun_curseur_n_est_emis_et_un_curseur_etranger_est_refuse(base):
    con, _, _, _, _ = _monter()
    fenetre = modele.Fenetre(date(2026, 10, 1), date(2026, 10, 7))
    for curseur in ("n'importe quoi", curseurs.encoder_curseur("search_console", {"s": 0}),
                    curseurs.encoder_curseur("bing_webmaster", {"s": 0})):
        with pytest.raises(ErreurSignaux) as exc:
            con.lire_page("jour", fenetre, curseur)
        assert exc.value.code == "REJ-SIGNAUX-CURSEUR-INVALIDE"


def test_hote_hors_liste_et_url_non_https_sont_refuses_avant_tout_envoi(base):
    con, srv, _, _, _ = _monter()
    for url in ("https://evil.example/webmaster/api.svc/json/GetQueryStats",
                "http://ssl.bing.com/webmaster/api.svc/json/GetQueryStats",
                "https://ssl.bing.com@evil.example/x", "https://ssl.bing.com:8443/x"):
        with pytest.raises(ErreurSignaux) as exc:
            con._appeler("GetQueryStats", "GET", url)
        assert exc.value.code == "REJ-SIGNAUX-HOTE-NON-PERMIS"
    assert srv.nombre_requetes == 0


def test_un_point_d_acces_d_ecriture_ou_une_methode_http_d_ecriture_est_refuse(base):
    con, srv, _, _, _ = _monter()
    with pytest.raises(ErreurSignaux) as exc:
        con._appeler("SubmitUrl", "POST", URL + "SubmitUrl", corps={"siteUrl": SITE, "url": SITE})
    assert exc.value.code == "REJ-SIGNAUX-ECRITURE-INTERDITE"
    with pytest.raises(ErreurSignaux) as exc:
        RequeteHttp("DELETE", URL + "GetQueryStats")
    assert exc.value.code == "REJ-SIGNAUX-ECRITURE-INTERDITE"
    assert srv.nombre_requetes == 0
    assert not any(p.startswith(("Submit", "Add", "Remove", "Delete")) for p in bw.ConnecteurBingWebmaster.POINTS_ACCES)


def test_le_quota_local_refuse_avant_l_envoi_et_se_reprend(base):
    limiteur = LimiteurQuota(Quota(par_minute=1, par_jour=None, source="test"))
    con, srv, _, _, horloge = _monter(limiteur=limiteur)
    bilan = ingestion.tour_ingestion(con, maintenant=horloge)["flux"]
    assert bilan[0]["statut"] == "termine" and bilan[1]["statut"] == "echec"
    assert bilan[1]["erreur"]["code"] == "REJ-SIGNAUX-QUOTA-LOCAL" and bilan[1]["erreur"]["reprenable"] is True
    assert srv.nombre_requetes == 1  # la seconde requête n'est jamais partie
    horloge.avancer(seconds=61)
    assert ingestion.tour_flux(con, "requetes", maintenant=horloge).statut == "termine"


def test_le_compte_du_jour_survit_au_redemarrage(base):
    con, _, _, _, horloge = _monter(limiteur=LimiteurQuota(Quota(par_minute=None, par_jour=2, source="test")))
    flux = ingestion.tour_ingestion(con, maintenant=horloge)["flux"]
    assert [f["statut"] for f in flux] == ["termine", "termine", "echec"]
    # « redémarrage » : nouveau connecteur, nouveau limiteur, mêmes registres
    neuf, _, _, _, _ = _monter(limiteur=LimiteurQuota(Quota(par_minute=None, par_jour=2, source="test")))
    bilan = ingestion.tour_flux(neuf, "pages", maintenant=horloge)
    assert bilan.statut == "echec" and bilan.erreur["code"] == "REJ-SIGNAUX-QUOTA-LOCAL"


def test_un_compte_inactif_ou_d_une_autre_source_n_est_jamais_lu(base):
    import dataclasses

    from fabriques_signaux import masqueur
    cpt = compte(modele.BING_WEBMASTER, SITE)
    srv = DoubleBingWebmaster(propriete=SITE, jeton=JETON)
    coffre = coffre_pour(modele.BING_WEBMASTER)
    with pytest.raises(ErreurSignaux) as exc:
        bw.ConnecteurBingWebmaster(srv, dataclasses.replace(cpt, actif=False), coffre.fournisseurs(),
                                   maintenant=Horloge(), masqueur=masqueur())
    assert exc.value.code == "REJ-SIGNAUX-COMPTE-INACTIF"
    with pytest.raises(ErreurSignaux):
        bw.ConnecteurBingWebmaster(srv, dataclasses.replace(cpt, source="crux"), coffre.fournisseurs(),
                                   maintenant=Horloge(), masqueur=masqueur())
    assert srv.nombre_requetes == 0


def test_un_mauvais_jeton_donne_401_et_une_propriete_inconnue_404(base):
    con, _, _, _, horloge = _monter()
    horloge2 = Horloge()
    srv = DoubleBingWebmaster(propriete=SITE, jeton="autre-jeton")
    from fabriques_signaux import masqueur
    mauvais = bw.ConnecteurBingWebmaster(srv, compte(modele.BING_WEBMASTER, SITE),
                                         coffre_pour("bing_webmaster").fournisseurs(),
                                         maintenant=horloge2, masqueur=masqueur())
    assert ingestion.tour_flux(mauvais, "jour", maintenant=horloge2).erreur["code"] == "REJ-SIGNAUX-AUTH-REFUSEE"
    inconnu = DoubleBingWebmaster(propriete="https://autre.example/", jeton=JETON)
    c2 = bw.ConnecteurBingWebmaster(inconnu, compte(modele.BING_WEBMASTER, SITE),
                                         coffre_pour("bing_webmaster").fournisseurs(),
                                    maintenant=horloge2, masqueur=masqueur())
    assert ingestion.tour_flux(c2, "pages", maintenant=horloge2).erreur["code"] == "REJ-SIGNAUX-INTROUVABLE"
    sans = DoubleBingWebmaster(propriete=SITE, jeton=JETON, sans_acces=True)
    c3 = bw.ConnecteurBingWebmaster(sans, compte(modele.BING_WEBMASTER, SITE),
                                         coffre_pour("bing_webmaster").fournisseurs(),
                                    maintenant=horloge2, masqueur=masqueur())
    assert ingestion.tour_flux(c3, "pages", maintenant=horloge2).erreur["code"] == "REJ-SIGNAUX-PERMISSION-REFUSEE"
    assert con is not None and horloge is not None


def test_un_compte_fictif_n_ecrit_pas_de_depense_et_aucun_flux_de_bing_n_en_produit(base):
    con, _, _, _, horloge = _monter(fictif=False)
    bilan = ingestion.tour_ingestion(con, maintenant=horloge)
    assert all(f["releves_ecrits"] == 0 for f in bilan["flux"])
    assert con.releves_depenses([]) == []
