"""Connecteurs Umami et Matomo (analytique auto-hébergée) : hôte = celui de l'adresse déclarée, requêtes exactes,
faits aux valeurs calculées à la main, un trou n'est pas un zéro, idempotence et révisions, reprise après échec,
erreurs typées, secret absent de tout, quota local, minimisation. Doubles fictifs (forme d'API jamais exercée contre
un vrai service).
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime, timedelta

import pytest
from fabriques_signaux import JETON, Horloge, coffre_pour, compte, masqueur
from m7_marketing.signaux import analytique as an
from m7_marketing.signaux import curseurs, ingestion, modele, registre
from m7_marketing.signaux.doubles_analytique import DoubleMatomo, DoubleUmami
from m7_marketing.signaux.erreurs import ErreurSignaux
from m7_marketing.signaux.quotas import LimiteurQuota, Quota
from m7_marketing.signaux.transport import Authentification, RequeteHttp
from sqlalchemy import select

from opsys import stockage
from opsys.stockage.schema import EVENEMENTS_SORTANTS, REGISTRES

HOTE = "analytics.horizon.example"
BASE = f"https://{HOTE}"
UID = "12345678-1234-1234-1234-123456789abc"
ID_SITE = "3"
STANDARD = {"pageviews": 30, "visitors": 10, "visits": 12, "bounces": 4, "totaltime": 900}


def _ms(jour: str, fin: bool = False) -> int:
    debut = int(datetime.combine(date.fromisoformat(jour), datetime.min.time(), tzinfo=UTC).timestamp() * 1000)
    return debut + 86_399_999 if fin else debut


class Capteur:
    def __init__(self, interne):
        self.interne, self.requetes = interne, []

    def envoyer(self, requete, *, delai_s=30.0):
        self.requetes.append(requete)
        return self.interne.envoyer(requete, delai_s=delai_s)


def _jours_umami():
    jours, d = {}, date(2026, 10, 1)
    while d <= date(2026, 11, 1):
        jours[d.isoformat()] = dict(STANDARD)
        d += timedelta(days=1)
    del jours["2026-10-10"]  # jour muet : 0 visite, 0 page vue
    jours["2026-10-15"] = {"pageviews": 7, "visitors": 3, "visits": 3, "bounces": 1, "totaltime": 120}
    return jours


REFERENTS_UMAMI = {
    "2026-10-06": [("chatgpt.com", 3), ("", 5), ("contact-jean.tremblay@example.test", 2)],
    "2026-10-07": [("chatgpt.com", 4)],
    "2026-10-20": [("perplexity.ai", 6)],
}


def _monter_umami(*, scenario=(), jours=None, referents=None, limiteur=None, base_url=BASE, prefixe=""):
    horloge = Horloge()
    srv = DoubleUmami(hote=HOTE, site_id=UID, jeton=JETON, jours=_jours_umami() if jours is None else jours,
                      referents=REFERENTS_UMAMI if referents is None else referents, scenario=scenario,
                      prefixe_chemin=prefixe)
    capteur = Capteur(srv)
    coffre = coffre_pour(modele.UMAMI)
    con = an.ConnecteurUmami(capteur, compte(modele.UMAMI, UID, base_url=base_url), coffre.fournisseurs(),
                             maintenant=horloge, masqueur=masqueur(), limiteur=limiteur)
    return con, srv, capteur, coffre, horloge


def _jours_matomo():
    jours, d = {}, date(2026, 10, 1)
    while d <= date(2026, 11, 1):
        jours[d.isoformat()] = {"visites": 12, "visiteurs": 10, "actions": 30, "rebonds": 4, "duree_totale_s": 900}
        d += timedelta(days=1)
    del jours["2026-10-10"]  # Matomo rend [] pour ce jour : un trou
    jours["2026-10-15"] = {"visites": 3, "visiteurs": 3, "actions": 7, "rebonds": 1, "duree_totale_s": 120}
    return jours


REFERENTS_MATOMO = {
    "2026-10-06": [("example.test", 4), ("", 2), ("contact-jean.tremblay@example.test", 1)],
    "2026-10-07": [("example.test", 3)],
}


def _monter_matomo(*, scenario=(), jours=None, referents=None, limiteur=None, jeton_double=JETON, id_site=ID_SITE):
    horloge = Horloge()
    srv = DoubleMatomo(hote=HOTE, id_site=id_site, jeton=jeton_double,
                       jours=_jours_matomo() if jours is None else jours,
                       referents=REFERENTS_MATOMO if referents is None else referents, scenario=scenario)
    capteur = Capteur(srv)
    coffre = coffre_pour(modele.MATOMO)
    con = an.ConnecteurMatomo(capteur, compte(modele.MATOMO, ID_SITE, base_url=BASE), coffre.fournisseurs(),
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


def _etat(source: str, flux: str):
    return curseurs.lire_etats(stockage.maillons(*registre.REGISTRE_CURSEURS))[f"{source}|principal|{flux}"]


ERREURS = [
    ("401", "REJ-SIGNAUX-AUTH-REFUSEE", False),
    ("403_permission", "REJ-SIGNAUX-PERMISSION-REFUSEE", False),
    ("403_quota", "REJ-SIGNAUX-LIMITE-DEBIT", True),
    ("429", "REJ-SIGNAUX-LIMITE-DEBIT", True),
    ("503", "REJ-SIGNAUX-FOURNISSEUR-INDISPONIBLE", True),
    ("delai", "REJ-SIGNAUX-RESEAU", True),
    ("exception_secrete", "REJ-SIGNAUX-RESEAU", True),
    ("json_invalide", "REJ-SIGNAUX-REPONSE-INVALIDE", False),
    ("trop_gros", "REJ-SIGNAUX-REPONSE-TROP-GROSSE", False),
]


# ================================================================================================= Umami
def test_umami_la_forme_exacte_des_requetes_l_hote_declare_et_le_secret_hors_de_l_url(base):
    con, srv, capteur, _, horloge = _monter_umami()
    bilan = ingestion.tour_ingestion(con, maintenant=horloge)["flux"]
    assert bilan[0]["fenetre"] == "2026-10-04/2026-10-31" and bilan[0]["pages"] == 4  # 28 jours, 7 par page
    premiere = srv.requetes[0]
    assert (premiere["methode"], premiere["url"], premiere["corps"], premiere["schema_auth"]) == (
        "GET", f"{BASE}/api/websites/{UID}/stats", None, "bearer")
    assert premiere["params"] == {"startAt": str(_ms("2026-10-04")), "endAt": str(_ms("2026-10-04", True))}
    metrics = [r for r in srv.requetes if r["url"].endswith("/metrics")]
    assert len(metrics) == 3 and len(srv.requetes) == 28 + 3
    assert metrics[0]["params"] == {"type": "referrer", "startAt": str(_ms("2026-10-05")),
                                    "endAt": str(_ms("2026-10-11", True)), "limit": "100"}
    for r in capteur.requetes:
        assert JETON not in r.url and JETON not in json.dumps(dict(r.params)) and JETON not in repr(r)
        assert r.authentification.schema == "bearer"
    assert srv.methodes() == {"GET"}


def test_umami_les_faits_par_jour_un_jour_muet_n_est_pas_un_zero(base):
    con, _, _, _, horloge = _monter_umami()
    bilan = ingestion.tour_ingestion(con, maintenant=horloge)["flux"][0]
    assert bilan["statut"] == "termine" and bilan["faits_nouveaux"] == 27 and bilan["ignores"] == 1
    jours = {f["periode_debut"]: f for f in _faits("audience_jour")}
    assert "2026-10-10" not in jours and "2026-11-01" not in jours and "2026-10-03" not in jours
    assert jours["2026-10-04"]["mesures"] == {"duree_totale_s": "900", "pages_vues": "30", "rebonds": "4",
                                              "visites": "12", "visiteurs": "10"}
    assert jours["2026-10-15"]["mesures"]["pages_vues"] == "7" and jours["2026-10-15"]["mesures"]["visiteurs"] == "3"
    assert jours["2026-10-04"]["provenance"]["point_acces"] == "websites.stats"
    assert jours["2026-10-04"]["source"] == "umami"


def test_umami_les_referents_par_semaine_direct_nomme_et_pii_masquee(base):
    con, _, _, _, horloge = _monter_umami()
    ingestion.tour_ingestion(con, maintenant=horloge)
    faits = {(f["periode_debut"], f["portee"]["ref"]): f for f in _faits("referents_periode")}
    assert faits[("2026-10-05", "chatgpt.com")]["mesures"] == {"visites": "7"}  # 3 + 4, deux jours de la semaine
    assert faits[("2026-10-05", "(direct)")]["mesures"] == {"visites": "5"}
    assert faits[("2026-10-19", "perplexity.ai")]["periode_fin"] == "2026-10-25"
    assert faits[("2026-10-05", "chatgpt.com")]["portee"]["type"] == "referent"
    assert "jean.tremblay" not in _tout_le_texte()
    assert any("[[COURRIEL:" in ref for _, ref in faits)


def test_umami_deux_referents_confondus_apres_minimisation_comptent_un_ignore(base):
    longs = {"2026-10-06": [("y" * 200 + "a.example", 5), ("y" * 200 + "b.example", 4)]}
    con, _, _, _, horloge = _monter_umami(referents=longs)
    bilan = ingestion.tour_ingestion(con, maintenant=horloge)["flux"][1]
    assert bilan["statut"] == "termine" and bilan["faits_nouveaux"] == 1 and bilan["ignores"] == 1


def test_umami_idempotence_revision_et_chaine_intacte(base):
    con, srv, _, _, horloge = _monter_umami()
    ingestion.tour_ingestion(con, maintenant=horloge)
    avant = len(stockage.maillons(*registre.REGISTRE))
    horloge.avancer(days=1)
    second = ingestion.tour_ingestion(con, maintenant=horloge)["flux"][0]
    assert second["fenetre"] == "2026-10-18/2026-11-01"
    assert second["faits_nouveaux"] == 1 and second["faits_revises"] == 0 and second["faits_inchanges"] == 14
    assert len(stockage.maillons(*registre.REGISTRE)) == avant + 1  # seul le 1er novembre est nouveau
    srv.reviser_jour("2026-10-20", pageviews=99, visits=40)
    horloge.avancer(days=1)
    revise = ingestion.tour_ingestion(con, maintenant=horloge)["flux"][0]
    assert revise["faits_revises"] == 1
    fait = next(f for f in _faits("audience_jour") if f["periode_debut"] == "2026-10-20")
    assert fait["revision"] == 2 and fait["mesures"]["pages_vues"] == "99" and fait["mesures"]["visites"] == "40"


def test_umami_la_journee_en_cours_n_est_jamais_lue(base):
    con, srv, _, _, horloge = _monter_umami()
    ingestion.tour_ingestion(con, maintenant=horloge)
    assert all(r["params"].get("startAt") != str(_ms("2026-11-01")) for r in srv.requetes)  # aujourd'hui (UTC)


def test_umami_reprise_au_curseur_apres_un_echec_en_milieu_de_fenetre(base):
    con, srv, _, _, horloge = _monter_umami(scenario=["ok"] * 7 + ["503"])
    bilan = ingestion.tour_flux(con, "jour", maintenant=horloge)
    assert bilan.statut == "echec" and bilan.pages == 1
    assert bilan.erreur["code"] == "REJ-SIGNAUX-FOURNISSEUR-INDISPONIBLE"
    etat = _etat("umami", "jour")
    assert etat.termine is False and etat.watermark is None and etat.echec()["code"] == bilan.erreur["code"]
    assert curseurs.decoder_curseur("umami", etat.curseur) == {"j": 7}
    assert len(_faits("audience_jour")) == 6  # sept jours lus dont le 10 muet ; la seconde page n'a rien écrit
    horloge.avancer(minutes=5)
    suite = ingestion.tour_flux(con, "jour", maintenant=horloge)
    assert suite.statut == "termine" and suite.pages == 3 and len(_faits("audience_jour")) == 27
    # la première requête de la reprise est le 11 octobre (index 7), pas le 4
    assert srv.requetes[8]["params"]["startAt"] == str(_ms("2026-10-11"))
    assert _etat("umami", "jour").echec() is None


def test_umami_un_echec_au_milieu_d_une_page_n_ecrit_rien_de_cette_page(base):
    con, _, _, _, horloge = _monter_umami(scenario=["ok", "ok", "503"])
    bilan = ingestion.tour_flux(con, "jour", maintenant=horloge)
    assert bilan.statut == "echec" and _faits() == []
    assert _etat("umami", "jour").curseur is None


@pytest.mark.parametrize(("scenario", "code", "reprenable"), ERREURS)
def test_umami_erreur_typee_sans_avancer_le_curseur_et_sans_fuite(base, caplog, scenario, code, reprenable):
    con, _, _, coffre, horloge = _monter_umami(scenario=[scenario])
    with caplog.at_level(logging.DEBUG):
        bilan = ingestion.tour_flux(con, "jour", maintenant=horloge)
    assert bilan.statut == "echec" and bilan.erreur["code"] == code and bilan.erreur["reprenable"] is reprenable
    etat = _etat("umami", "jour")
    assert etat.termine is False and etat.watermark is None and etat.curseur is None and etat.echec()["code"] == code
    assert JETON not in json.dumps(bilan.erreur) and JETON not in caplog.text and JETON not in _tout_le_texte()
    assert coffre.ouverts == 0 and coffre.ouvertures["principal"] == 1
    assert _faits() == []


def test_umami_hote_hors_adresse_declaree_refuse_et_prefixe_de_chemin_respecte(base):
    con, srv, _, _, _ = _monter_umami()
    for url in (f"https://evil.example/api/websites/{UID}/stats", f"https://{HOTE}.evil.example/x",
                f"http://{HOTE}/x", f"https://{HOTE}:8443/x", f"https://{HOTE}@evil.example/x"):
        with pytest.raises(ErreurSignaux) as exc:
            con._appeler("websites.stats", "GET", url)
        assert exc.value.code == "REJ-SIGNAUX-HOTE-NON-PERMIS"
    assert srv.nombre_requetes == 0
    con2, srv2, _, _, horloge = _monter_umami(base_url=BASE + "/umami", prefixe="/umami")
    assert ingestion.tour_flux(con2, "jour", maintenant=horloge).statut == "termine"
    assert srv2.requetes[0]["url"] == f"{BASE}/umami/api/websites/{UID}/stats"


def test_umami_ecriture_refusee_et_curseurs_invalides(base):
    con, srv, _, _, _ = _monter_umami()
    for point in ("websites.reset", "websites.delete", "websites.create"):
        with pytest.raises(ErreurSignaux) as exc:
            con._appeler(point, "POST", f"{BASE}/api/websites/{UID}/reset")
        assert exc.value.code == "REJ-SIGNAUX-ECRITURE-INTERDITE"
    assert srv.nombre_requetes == 0
    fenetre = modele.Fenetre(date(2026, 10, 4), date(2026, 10, 31))
    for curseur in ("texte libre", curseurs.encoder_curseur("matomo", {"j": 0}),
                    curseurs.encoder_curseur("umami", {"j": 999}), curseurs.encoder_curseur("umami", {"j": -1}),
                    curseurs.encoder_curseur("umami", {"j": "7"})):
        with pytest.raises(ErreurSignaux) as exc:
            con.lire_page("jour", fenetre, curseur)
        assert exc.value.code == "REJ-SIGNAUX-CURSEUR-INVALIDE"


def test_umami_quota_local_avant_l_envoi_et_reprise(base):
    con, srv, _, _, horloge = _monter_umami(limiteur=LimiteurQuota(Quota(par_minute=7, par_jour=None, source="test")))
    bilan = ingestion.tour_flux(con, "jour", maintenant=horloge)
    assert bilan.statut == "echec" and bilan.erreur["code"] == "REJ-SIGNAUX-QUOTA-LOCAL" and bilan.erreur["reprenable"]
    assert srv.nombre_requetes == 7  # la huitième requête n'est jamais partie
    assert curseurs.decoder_curseur("umami", _etat("umami", "jour").curseur) == {"j": 7}


def test_umami_coherence_refuse_plus_de_rebonds_que_de_visites(base):
    con, _, _, _, horloge = _monter_umami(jours={"2026-10-04": {"pageviews": 5, "visitors": 1, "visits": 1,
                                                                  "bounces": 3, "totaltime": 1}})
    bilan = ingestion.tour_flux(con, "jour", maintenant=horloge)
    assert bilan.erreur["code"] == "REJ-SIGNAUX-REPONSE-INVALIDE" and _faits() == []


def test_umami_le_double_se_comporte_comme_le_service_documente():
    srv = DoubleUmami(hote=HOTE, site_id=UID, jeton=JETON, jours={"2026-10-04": dict(STANDARD)})
    auth = Authentification("bearer", JETON)
    p = {"startAt": str(_ms("2026-10-04")), "endAt": str(_ms("2026-10-04", True))}

    def appel(chemin, params, a=auth, methode="GET"):
        return srv.envoyer(RequeteHttp(methode, f"{BASE}{chemin}", params, authentification=a)).statut

    assert appel(f"/api/websites/{UID}/stats", p) == 200
    assert appel(f"/api/websites/{UID}/stats", p, Authentification("bearer", "faux")) == 401
    assert appel("/api/websites/autre/stats", p) == 404
    assert appel(f"/api/websites/{UID}/stats", {"startAt": "x", "endAt": "y"}) == 400
    assert appel(f"/api/websites/{UID}/stats", {"startAt": p["endAt"], "endAt": p["startAt"]}) == 400
    assert appel(f"/api/websites/{UID}/metrics", {**p, "type": "os"}) == 400
    assert appel(f"/api/websites/{UID}/metrics", {**p, "type": "referrer", "limit": "501"}) == 400
    assert appel(f"/api/websites/{UID}/reset", p, methode="POST") == 404
    reponse = srv.envoyer(RequeteHttp("GET", f"{BASE}/api/websites/{UID}/stats", p, authentification=auth))
    assert reponse.corps["pageviews"] == {"value": 30, "prev": 0}


# ================================================================================================ Matomo
def test_matomo_la_forme_exacte_des_requetes_le_token_dans_le_corps_jamais_dans_l_url(base):
    con, srv, capteur, _, horloge = _monter_matomo()
    ingestion.tour_ingestion(con, maintenant=horloge)
    assert srv.requetes[0]["methode"] == "POST" and srv.requetes[0]["url"] == f"{BASE}/index.php"
    assert srv.requetes[0]["params"] == {}
    assert srv.requetes[0]["corps"] == {"module": "API", "method": "VisitsSummary.get", "idSite": ID_SITE,
                                        "period": "day", "date": "2026-10-04,2026-10-31", "format": "JSON"}
    assert srv.requetes[1]["corps"] == {"module": "API", "method": "Referrers.getWebsites", "idSite": ID_SITE,
                                        "period": "range", "date": "2026-10-05,2026-10-11", "format": "JSON",
                                        "filter_limit": "100"}
    assert len(srv.requetes) == 1 + 3
    for r in capteur.requetes:
        assert r.authentification.schema == "parametre" and r.authentification.nom == "token_auth"
        assert JETON not in r.url and JETON not in json.dumps(dict(r.corps)) and JETON not in repr(r)
    assert srv.methodes() == {"POST"}


def test_matomo_les_faits_un_trou_n_est_pas_un_zero(base):
    con, _, _, _, horloge = _monter_matomo()
    bilan = ingestion.tour_ingestion(con, maintenant=horloge)["flux"][0]
    assert bilan["statut"] == "termine" and bilan["faits_nouveaux"] == 27 and bilan["pages"] == 1
    assert bilan["ignores"] == 1
    jours = {f["periode_debut"]: f for f in _faits("audience_jour")}
    assert "2026-10-10" not in jours and len(jours) == 27
    assert jours["2026-10-04"]["mesures"] == {"actions": "30", "duree_totale_s": "900", "rebonds": "4",
                                              "visites": "12", "visiteurs": "10"}
    assert jours["2026-10-15"]["mesures"]["visites"] == "3"
    assert jours["2026-10-04"]["provenance"]["point_acces"] == "VisitsSummary.get"
    assert jours["2026-10-04"]["provenance"]["fournisseur"] == "matomo"


def test_matomo_les_referents_par_semaine_direct_et_pii_masquee(base):
    con, _, _, _, horloge = _monter_matomo()
    ingestion.tour_ingestion(con, maintenant=horloge)
    faits = {f["portee"]["ref"]: f for f in _faits("referents_periode")}
    assert faits["example.test"]["mesures"] == {"visites": "7"} and faits["(direct)"]["mesures"] == {"visites": "2"}
    assert "jean.tremblay" not in _tout_le_texte() and any("[[COURRIEL:" in r for r in faits)


def test_matomo_deux_referents_confondus_apres_minimisation_comptent_un_ignore(base):
    longs = {"2026-10-06": [("z" * 200 + "a", 5), ("z" * 200 + "b", 4)]}
    con, _, _, _, horloge = _monter_matomo(referents=longs)
    bilan = ingestion.tour_ingestion(con, maintenant=horloge)["flux"][1]
    assert bilan["faits_nouveaux"] == 1 and bilan["ignores"] == 1


def test_matomo_idempotence_et_revision(base):
    con, srv, _, _, horloge = _monter_matomo()
    ingestion.tour_ingestion(con, maintenant=horloge)
    horloge.avancer(days=1)
    second = ingestion.tour_ingestion(con, maintenant=horloge)["flux"][0]
    assert second["faits_nouveaux"] == 1 and second["faits_revises"] == 0 and second["faits_inchanges"] == 14
    srv.reviser_jour("2026-10-20", visites=50)
    horloge.avancer(days=1)
    revise = ingestion.tour_ingestion(con, maintenant=horloge)["flux"][0]
    assert revise["faits_revises"] == 1
    fait = next(f for f in _faits("audience_jour") if f["periode_debut"] == "2026-10-20")
    assert fait["revision"] == 2 and fait["mesures"]["visites"] == "50"


@pytest.mark.parametrize(("scenario", "code", "reprenable"), ERREURS)
def test_matomo_erreur_typee_sans_avancer_le_curseur_et_sans_fuite(base, caplog, scenario, code, reprenable):
    con, _, _, coffre, horloge = _monter_matomo(scenario=[scenario])
    with caplog.at_level(logging.DEBUG):
        bilan = ingestion.tour_flux(con, "jour", maintenant=horloge)
    assert bilan.statut == "echec" and bilan.erreur["code"] == code and bilan.erreur["reprenable"] is reprenable
    etat = _etat("matomo", "jour")
    assert etat.termine is False and etat.watermark is None and etat.curseur is None and etat.echec()["code"] == code
    assert JETON not in json.dumps(bilan.erreur) and JETON not in caplog.text and JETON not in _tout_le_texte()
    assert coffre.ouverts == 0 and coffre.ouvertures["principal"] == 1 and _faits() == []


def test_matomo_une_erreur_applicative_http_200_est_traduite_sans_recopier_le_message(base):
    con, _, _, _, horloge = _monter_matomo(jeton_double="un-autre-jeton")
    bilan = ingestion.tour_flux(con, "jour", maintenant=horloge)
    assert bilan.erreur["code"] == "REJ-SIGNAUX-PERMISSION-REFUSEE" and bilan.erreur["reprenable"] is False
    assert "jeton invalide" not in json.dumps(bilan.erreur)
    con2, _, _, _, horloge2 = _monter_matomo(id_site="99")
    assert ingestion.tour_flux(con2, "referents", maintenant=horloge2).erreur["code"] == (
        "REJ-SIGNAUX-PERMISSION-REFUSEE")


def test_matomo_hote_hors_adresse_declaree_et_methodes_d_ecriture_refusees(base):
    con, srv, _, _, _ = _monter_matomo()
    with pytest.raises(ErreurSignaux) as exc:
        con._appeler("VisitsSummary.get", "POST", "https://evil.example/index.php", corps={})
    assert exc.value.code == "REJ-SIGNAUX-HOTE-NON-PERMIS"
    for methode in ("SitesManager.addSite", "UsersManager.deleteUser", "SitesManager.deleteSite",
                    "CoreAdminHome.invalidateArchivedReports"):
        with pytest.raises(ErreurSignaux) as exc:
            con._appeler(methode, "POST", f"{BASE}/index.php", corps={"module": "API", "method": methode})
        assert exc.value.code == "REJ-SIGNAUX-ECRITURE-INTERDITE"
    assert srv.nombre_requetes == 0
    assert frozenset({"VisitsSummary.get", "Referrers.getWebsites"}) == an.ConnecteurMatomo.POINTS_ACCES


def test_matomo_reponses_incoherentes_sont_refusees(base):
    # une liste non vide là où un objet par jour est attendu ; un jour hors de la fenêtre demandée
    con, _, _, _, horloge = _monter_matomo()
    fenetre = modele.Fenetre(date(2026, 10, 4), date(2026, 10, 31))
    con._api = lambda *a, **k: ([{"nb_visits": 1}], "0" * 64)
    with pytest.raises(ErreurSignaux) as exc:
        con.lire_page("jour", fenetre, None)
    assert exc.value.code == "REJ-SIGNAUX-REPONSE-INVALIDE"
    con._api = lambda *a, **k: ({"2026-09-01": {"nb_visits": 1}}, "0" * 64)
    with pytest.raises(ErreurSignaux) as exc:
        con.lire_page("jour", fenetre, None)
    assert exc.value.code == "REJ-SIGNAUX-REPONSE-INVALIDE"
    con._api = lambda *a, **k: ({"2026-10-04": {"nb_visits": 1}}, "0" * 64)  # champs obligatoires manquants
    with pytest.raises(ErreurSignaux) as exc:
        con.lire_page("jour", fenetre, None)
    assert exc.value.code == "REJ-SIGNAUX-REPONSE-INVALIDE"
    assert horloge is not None


def test_matomo_une_reponse_entierement_vide_ne_donne_aucun_fait_et_aucun_zero(base):
    vide = {}
    con, _, _, _, horloge = _monter_matomo(jours=vide, referents={})
    bilan = ingestion.tour_ingestion(con, maintenant=horloge)["flux"]
    assert bilan[0]["statut"] == "termine" and bilan[0]["faits_nouveaux"] == 0 and bilan[0]["ignores"] == 28
    assert _faits() == []


def test_matomo_quota_local_et_curseur_de_referents(base):
    con, srv, _, _, horloge = _monter_matomo(limiteur=LimiteurQuota(Quota(par_minute=2, par_jour=None, source="test")))
    bilan = ingestion.tour_flux(con, "jour", maintenant=horloge)  # 1 requête
    assert bilan.statut == "termine"
    bilan = ingestion.tour_flux(con, "referents", maintenant=horloge)  # 1 requête de plus, puis le plafond
    assert bilan.statut == "echec" and bilan.erreur["code"] == "REJ-SIGNAUX-QUOTA-LOCAL"
    assert srv.nombre_requetes == 2
    assert curseurs.decoder_curseur("matomo", _etat("matomo", "referents").curseur) == {"s": 1}
    fenetre = modele.Fenetre(date(2026, 10, 4), date(2026, 10, 31))
    for mauvais in ("x", curseurs.encoder_curseur("umami", {"s": 0}), curseurs.encoder_curseur("matomo", {"s": 9})):
        with pytest.raises(ErreurSignaux) as exc:
            con.lire_page("referents", fenetre, mauvais)
        assert exc.value.code == "REJ-SIGNAUX-CURSEUR-INVALIDE"
    with pytest.raises(ErreurSignaux) as exc:
        con.lire_page("jour", fenetre, curseurs.encoder_curseur("matomo", {"s": 1}))
    assert exc.value.code == "REJ-SIGNAUX-CURSEUR-INVALIDE"


def test_matomo_le_double_se_comporte_comme_le_service_documente():
    srv = DoubleMatomo(hote=HOTE, id_site=ID_SITE, jeton=JETON, jours={"2026-10-04": {
        "visites": 1, "visiteurs": 1, "actions": 2, "rebonds": 0, "duree_totale_s": 10}})
    auth = Authentification("parametre", JETON, nom="token_auth")
    corps = {"module": "API", "method": "VisitsSummary.get", "idSite": ID_SITE, "period": "day",
             "date": "2026-10-04,2026-10-05", "format": "JSON"}

    def appel(c, a=auth, chemin="/index.php"):
        return srv.envoyer(RequeteHttp("POST", f"{BASE}{chemin}", {}, c, a))

    ok = appel(corps)
    assert ok.statut == 200 and ok.corps["2026-10-05"] == [] and ok.corps["2026-10-04"]["nb_actions"] == 2
    assert appel(corps, Authentification("parametre", "faux", nom="token_auth")).corps["result"] == "error"
    assert appel({**corps, "idSite": "9"}).corps["result"] == "error"
    assert appel({**corps, "format": "XML"}).corps["result"] == "error"
    assert appel({**corps, "date": "pas,une-date"}).corps["result"] == "error"
    assert appel({**corps, "method": "SitesManager.addSite"}).corps["result"] == "error"
    assert appel(corps, chemin="/autre.php").statut == 404
