"""Connecteurs PageSpeed Insights et CrUX : forme des requêtes, faits exacts, absences honnêtes, erreurs typées, secret.

Données FICTIVES, doubles de test (aucun réseau) : ces tests prouvent le code du connecteur, jamais le vrai service.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import date

import pytest
from fabriques_signaux import JETON, MAINTENANT, CoffreFictif, coffre_pour, compte
from m7_marketing.signaux import curseurs, ingestion, modele, registre
from m7_marketing.signaux.doubles_pagespeed import DoubleCrux, DoublePageSpeed
from m7_marketing.signaux.erreurs import ErreurSignaux
from m7_marketing.signaux.pagespeed import ConnecteurCrux, ConnecteurPageSpeed
from m7_marketing.signaux.quotas import LimiteurQuota, Quota
from m7_marketing.signaux.transport import Authentification, RequeteHttp, TransportNonBranche
from sqlalchemy import select

from opsys import stockage
from opsys.stockage.schema import EVENEMENTS_SORTANTS

SITE = "https://www.horizon.example/"
ORIGINE = "https://www.horizon.example"
AUJOURDHUI = date(2026, 11, 1)
FENETRE = modele.Fenetre(AUJOURDHUI, AUJOURDHUI)

LABO = {"score": 0.87, "lcp": 2345.678, "cls": 0.0423, "tbt": 180.4, "fcp": 1200.6, "si": 3100.2}
TERRAIN = {"overall": "AVERAGE", "metrics": {
    "LARGEST_CONTENTFUL_PAINT_MS": (2800, "AVERAGE"),
    "CUMULATIVE_LAYOUT_SHIFT_SCORE": (5, "FAST"),
    "INTERACTION_TO_NEXT_PAINT": (180, "FAST"),
    "FIRST_CONTENTFUL_PAINT_MS": (1500, "FAST"),
    "EXPERIMENTAL_TIME_TO_FIRST_BYTE": (600, "AVERAGE"),
}}
CRUX_PHONE = {
    "largest_contentful_paint": (2800, [0.62, 0.25, 0.13]),
    "interaction_to_next_paint": (180, [0.81, 0.12, 0.07]),
    "cumulative_layout_shift": ("0.05", [0.9, 0.06, 0.04]),
    "experimental_time_to_first_byte": (600, [0.7, 0.2, 0.1]),
}
PERIODE_CRUX = ((2026, 10, 4), (2026, 10, 31))


def _pages(avec_terrain: bool = True):
    return {SITE: {"mobile": {**LABO, "terrain": TERRAIN if avec_terrain else None},
                   "desktop": {**LABO, "score": 0.95, "terrain": None}}}


def _psi(base_pii, horloge, *, scenario=(), avec_terrain=True, fictif=True, **opts):
    cf = coffre_pour("pagespeed")
    srv = DoublePageSpeed(jeton=JETON, pages=_pages(avec_terrain), scenario=scenario)
    con = ConnecteurPageSpeed(srv, compte("pagespeed", SITE, fictif=fictif), cf.fournisseurs(),
                              maintenant=horloge, masqueur=base_pii, **opts)
    return con, srv, cf


def _crux(pii, horloge, *, scenario=(), origines=None, **opts):
    cf = coffre_pour("crux")
    donnees = {ORIGINE: {"PHONE": CRUX_PHONE, "periode": PERIODE_CRUX}} if origines is None else origines
    srv = DoubleCrux(jeton=JETON, origines=donnees, scenario=scenario)
    con = ConnecteurCrux(srv, compte("crux", ORIGINE), cf.fournisseurs(), maintenant=horloge, masqueur=pii, **opts)
    return con, srv, cf


def _etats():
    return curseurs.lire_etats(stockage.maillons(*registre.REGISTRE_CURSEURS))


def _faits():
    return registre.charger(stockage.maillons(*registre.REGISTRE))


# -- forme des requêtes, lecture seule --------------------------------------------------------------------------
def test_requete_pagespeed_forme_exacte(pii, horloge):
    con, srv, _ = _psi(pii, horloge)
    con.lire_page("mobile", FENETRE, None)
    assert srv.requetes == [{
        "methode": "GET", "url": "https://www.googleapis.com/pagespeedonline/v5/runPagespeed",
        "chemin": "/pagespeedonline/v5/runPagespeed",
        "params": {"url": SITE, "strategy": "mobile", "category": "performance"}, "corps": None,
        "schema_auth": "parametre"}]


def test_requete_crux_forme_exacte(pii, horloge):
    con, srv, _ = _crux(pii, horloge)
    con.lire_page("phone", FENETRE, None)
    assert srv.requetes == [{
        "methode": "POST", "url": "https://chromeuxreport.googleapis.com/v1/records:queryRecord",
        "chemin": "/v1/records:queryRecord", "params": {},
        "corps": {"origin": ORIGINE, "formFactor": "PHONE",
                  "metrics": ["largest_contentful_paint", "interaction_to_next_paint", "cumulative_layout_shift",
                              "experimental_time_to_first_byte"]},
        "schema_auth": "parametre"}]


@pytest.mark.parametrize("fabrique", ["psi", "crux"])
def test_la_cle_n_est_jamais_dans_l_url_ni_dans_les_parametres(pii, horloge, fabrique):
    con, srv, _ = (_psi if fabrique == "psi" else _crux)(pii, horloge)
    con.lire_page(con.FLUX[0], FENETRE, None)
    for requete in srv.requetes:
        assert JETON not in json.dumps(requete) and "key" not in requete["params"] and "key=" not in requete["url"]
        assert requete["schema_auth"] == "parametre"


def test_lecture_seule_un_seul_point_d_acces_chacun():
    assert frozenset({"runPagespeed"}) == ConnecteurPageSpeed.POINTS_ACCES
    assert frozenset({"records:queryRecord"}) == ConnecteurCrux.POINTS_ACCES


def test_point_d_acces_hors_liste_refuse_sans_rien_envoyer_ni_ouvrir_le_secret(pii, horloge):
    con, srv, cf = _psi(pii, horloge)
    with pytest.raises(ErreurSignaux) as exc:
        con._appeler("runPagespeed:mutate", "POST", "https://www.googleapis.com/pagespeedonline/v5/runPagespeed")
    assert exc.value.code == "REJ-SIGNAUX-ECRITURE-INTERDITE"
    assert srv.nombre_requetes == 0 and cf.ouvertures["principal"] == 0


@pytest.mark.parametrize("url", [
    "https://evil.example/pagespeedonline/v5/runPagespeed",
    "http://www.googleapis.com/pagespeedonline/v5/runPagespeed",
    "https://user:mdp@www.googleapis.com/pagespeedonline/v5/runPagespeed",
    "https://www.googleapis.com:8443/pagespeedonline/v5/runPagespeed",
    "https://www.googleapis.com/pagespeedonline/v5/runPagespeed#frag",
])
def test_hote_ou_url_inattendu_refuse_avant_l_envoi(pii, horloge, url):
    con, srv, cf = _psi(pii, horloge)
    with pytest.raises(ErreurSignaux) as exc:
        con._appeler("runPagespeed", "GET", url)
    assert exc.value.code == "REJ-SIGNAUX-HOTE-NON-PERMIS"
    assert srv.nombre_requetes == 0 and cf.ouvertures["principal"] == 0


def test_methode_d_ecriture_impossible_a_construire():
    with pytest.raises(ErreurSignaux) as exc:
        RequeteHttp("DELETE", "https://www.googleapis.com/x")
    assert exc.value.code == "REJ-SIGNAUX-ECRITURE-INTERDITE"


# -- faits exacts ------------------------------------------------------------------------------------------------
def test_faits_pagespeed_valeurs_exactes(pii, horloge):
    con, _, _ = _psi(pii, horloge)
    page = con.lire_page("mobile", FENETRE, None)
    assert page.termine and page.curseur_suivant is None and page.donnees_jusqu_au == "2026-11-01"
    labo, terrain = (modele.normaliser_fait(f) for f in page.faits)
    assert labo["nature"] == "vitesse_page_labo" and labo["portee"] == {"type": "page", "ref": f"{SITE}@mobile"}
    assert (labo["periode_debut"], labo["periode_fin"]) == ("2026-11-01", "2026-11-01")
    assert labo["mesures"] == {"cls": "0.042", "fcp_ms": "1201", "lcp_ms": "2346", "score_performance": "87",
                               "speed_index_ms": "3100", "tbt_ms": "180"}
    assert labo["echantillon"] == {"nature": "echantillonne", "n": 1} and labo["fictif"] is True
    assert labo["provenance"]["mode"] == "api_lecture" and labo["provenance"]["point_acces"] == "runPagespeed"
    assert labo["provenance"]["version_api"] == "pagespeedonline/v5" and labo["devise"] is None
    assert terrain["nature"] == "terrain_cwv"
    assert (terrain["periode_debut"], terrain["periode_fin"]) == ("2026-10-05", "2026-11-01")
    assert terrain["mesures"] == {
        "cls_categorie": "1", "cls_p75": "0.05", "fcp_categorie": "1", "fcp_p75_ms": "1500", "global_categorie": "2",
        "inp_categorie": "1", "inp_p75_ms": "180", "lcp_categorie": "2", "lcp_p75_ms": "2800",
        "ttfb_categorie": "2", "ttfb_p75_ms": "600"}
    assert terrain["echantillon"] == {"nature": "echantillonne", "n": None}


def test_mobile_et_desktop_sont_deux_faits_distincts(pii, horloge):
    con, _, _ = _psi(pii, horloge)
    mobile = modele.normaliser_fait(con.lire_page("mobile", FENETRE, None).faits[0])
    desktop = modele.normaliser_fait(con.lire_page("desktop", FENETRE, None).faits[0])
    assert mobile["fait_id"] != desktop["fait_id"] and desktop["mesures"]["score_performance"] == "95"
    assert desktop["portee"]["ref"].endswith("@desktop")


def test_sans_donnees_de_terrain_seulement_le_fait_de_labo(pii, horloge):
    con, _, _ = _psi(pii, horloge, avec_terrain=False)
    page = con.lire_page("mobile", FENETRE, None)
    assert [f["nature"] for f in page.faits] == ["vitesse_page_labo"]
    assert not any(cle.endswith(("_p75_ms", "_p75", "_categorie")) for cle in page.faits[0]["mesures"])


def test_metriques_vides_jamais_un_zero(pii, horloge):
    cf = coffre_pour("pagespeed")
    pages = _pages()
    pages[SITE]["mobile"]["terrain"] = {"overall": "NONE", "metrics": {}}
    srv = DoublePageSpeed(jeton=JETON, pages=pages)
    con = ConnecteurPageSpeed(srv, compte("pagespeed", SITE), cf.fournisseurs(), maintenant=horloge, masqueur=pii)
    assert [f["nature"] for f in con.lire_page("mobile", FENETRE, None).faits] == ["vitesse_page_labo"]


def test_faits_crux_valeurs_exactes(pii, horloge):
    con, _, _ = _crux(pii, horloge)
    page = con.lire_page("phone", FENETRE, None)
    assert page.termine and len(page.faits) == 1
    fait = modele.normaliser_fait(page.faits[0])
    assert fait["nature"] == "terrain_cwv" and fait["portee"] == {"type": "site", "ref": f"{ORIGINE}/@phone"}
    assert (fait["periode_debut"], fait["periode_fin"]) == ("2026-10-04", "2026-10-31")
    assert fait["mesures"] == {
        "cls_bon": "0.9", "cls_p75": "0.05", "inp_bon": "0.81", "inp_p75_ms": "180", "lcp_bon": "0.62",
        "lcp_p75_ms": "2800", "ttfb_bon": "0.7", "ttfb_p75_ms": "600"}
    assert fait["echantillon"] == {"nature": "echantillonne", "n": None}
    assert fait["provenance"]["point_acces"] == "records:queryRecord" and fait["provenance"]["version_api"] == "crux/v1"


def test_crux_404_est_une_page_vide_pas_une_panne(pii, horloge):
    con, srv, cf = _crux(pii, horloge)
    page = con.lire_page("desktop", FENETRE, None)  # aucun facteur DESKTOP pour cette origine
    assert page.faits == () and page.termine and page.curseur_suivant is None
    assert srv.nombre_requetes == 1 and cf.ouverts == 0


def test_crux_origine_inconnue_aucun_fait_sans_echec_a_l_ingestion(base, pii, horloge):
    con, _, _ = _crux(pii, horloge, origines={})
    bilan = ingestion.tour_ingestion(con, maintenant=horloge)
    assert [f["statut"] for f in bilan["flux"]] == ["termine", "termine"]
    assert all(f["faits_nouveaux"] == 0 and f["erreur"] is None for f in bilan["flux"])
    assert _faits() == [] and all(e.echec() is None for e in _etats().values())


def test_crux_reponse_sans_metrique_aucun_fait(pii, horloge):
    donnees = {ORIGINE: {"PHONE": {}, "periode": PERIODE_CRUX}}
    con, _, _ = _crux(pii, horloge, origines=donnees)
    assert con.lire_page("phone", FENETRE, None).faits == ()


# -- réponses malformées -----------------------------------------------------------------------------------------
@pytest.mark.parametrize("modif", [
    lambda r: r.update(score=1.5), lambda r: r.update(score=-0.1), lambda r: r.update(score=None),
    lambda r: r.update(score=True),
])
def test_score_invalide_refuse(pii, horloge, modif):
    cf = coffre_pour("pagespeed")
    pages = _pages()
    modif(pages[SITE]["mobile"])
    con = ConnecteurPageSpeed(DoublePageSpeed(jeton=JETON, pages=pages), compte("pagespeed", SITE), cf.fournisseurs(),
                              maintenant=horloge, masqueur=pii)
    with pytest.raises(ErreurSignaux) as exc:
        con.lire_page("mobile", FENETRE, None)
    assert exc.value.code == "REJ-SIGNAUX-REPONSE-INVALIDE"


def test_categorie_inconnue_ou_horodatage_futur_refuses(pii, horloge):
    con, srv, _ = _psi(pii, horloge)
    srv.analyse_le = "2026-11-09T00:00:00Z"
    with pytest.raises(ErreurSignaux) as exc:
        con.lire_page("mobile", FENETRE, None)
    assert exc.value.code == "REJ-SIGNAUX-REPONSE-INVALIDE"
    srv.analyse_le = "pas une date"
    with pytest.raises(ErreurSignaux) as exc:
        con.lire_page("mobile", FENETRE, None)
    assert exc.value.code == "REJ-SIGNAUX-REPONSE-INVALIDE"
    pages = _pages()
    pages[SITE]["mobile"]["terrain"] = {
        "overall": "AVERAGE", "metrics": {"LARGEST_CONTENTFUL_PAINT_MS": (2800, "GOOD")}}
    cf = coffre_pour("pagespeed")
    con = ConnecteurPageSpeed(DoublePageSpeed(jeton=JETON, pages=pages), compte("pagespeed", SITE), cf.fournisseurs(),
                              maintenant=horloge, masqueur=pii)
    with pytest.raises(ErreurSignaux) as exc:
        con.lire_page("mobile", FENETRE, None)
    assert exc.value.code == "REJ-SIGNAUX-REPONSE-INVALIDE"


def test_periode_crux_incoherente_refusee(pii, horloge):
    inversee = {ORIGINE: {"PHONE": CRUX_PHONE, "periode": ((2026, 11, 5), (2026, 10, 1))}}
    con, _, _ = _crux(pii, horloge, origines=inversee)
    with pytest.raises(ErreurSignaux) as exc:
        con.lire_page("phone", FENETRE, None)
    assert exc.value.code == "REJ-SIGNAUX-REPONSE-INVALIDE"
    con, _, _ = _crux(pii, horloge, origines={ORIGINE: {"PHONE": CRUX_PHONE, "periode": ((2026, 2, 30), (2026, 3, 1))}})
    with pytest.raises(ErreurSignaux) as exc:
        con.lire_page("phone", FENETRE, None)
    assert exc.value.code == "REJ-SIGNAUX-REPONSE-INVALIDE"


def test_flux_inconnu_et_curseur_refuses(pii, horloge):
    con, srv, _ = _psi(pii, horloge)
    for flux, curseur, code in (("tablette", None, "REJ-SIGNAUX-ARGUMENT-INVALIDE"),
                                ("mobile", "sig:v1:pagespeed:e30", "REJ-SIGNAUX-CURSEUR-INVALIDE")):
        with pytest.raises(ErreurSignaux) as exc:
            con.lire_page(flux, FENETRE, curseur)
        assert exc.value.code == code
    assert srv.nombre_requetes == 0


# -- cadence hebdomadaire ----------------------------------------------------------------------------------------
@pytest.mark.parametrize("classe", [ConnecteurPageSpeed, ConnecteurCrux])
def test_fenetre_une_lecture_par_semaine(pii, horloge, classe):
    source = "pagespeed" if classe is ConnecteurPageSpeed else "crux"
    cpt = compte(source, SITE if source == "pagespeed" else ORIGINE)
    con = classe(DoublePageSpeed(jeton=JETON, pages={}), cpt, coffre_pour(source).fournisseurs(), maintenant=horloge,
                 masqueur=pii)
    assert con.fenetre_suivante(None, AUJOURDHUI) == modele.Fenetre(AUJOURDHUI, AUJOURDHUI)
    assert con.fenetre_suivante(date(2026, 10, 26), AUJOURDHUI) is None  # 6 jours
    assert con.fenetre_suivante(date(2026, 11, 1), AUJOURDHUI) is None
    assert con.fenetre_suivante(date(2026, 10, 25), AUJOURDHUI) == modele.Fenetre(AUJOURDHUI, AUJOURDHUI)  # 7 jours


def test_ingestion_pagespeed_idempotente_et_hebdomadaire(base, pii, horloge):
    con, srv, _ = _psi(pii, horloge, fictif=False)
    bilan = ingestion.tour_ingestion(con, maintenant=horloge)
    assert [(f["flux"], f["statut"], f["faits_nouveaux"]) for f in bilan["flux"]] == [
        ("mobile", "termine", 2), ("desktop", "termine", 1)]
    assert len(_faits()) == 3 and srv.nombre_requetes == 2
    # même jour, six jours plus tard : rien à lire, aucune requête
    bilan = ingestion.tour_ingestion(con, maintenant=horloge)
    assert [f["statut"] for f in bilan["flux"]] == ["rien_de_nouveau", "rien_de_nouveau"]
    horloge.avancer(days=6)
    ingestion.tour_ingestion(con, maintenant=horloge)
    assert srv.nombre_requetes == 2 and len(_faits()) == 3
    # sept jours : une nouvelle analyse, de nouveaux faits (une autre période)
    horloge.avancer(days=1)
    srv.analyse_le = "2026-11-08T08:00:00Z"
    bilan = ingestion.tour_ingestion(con, maintenant=horloge)
    assert [f["faits_nouveaux"] for f in bilan["flux"]] == [2, 1] and srv.nombre_requetes == 4
    assert len(_faits()) == 6
    etat = _etats()["pagespeed|principal|mobile"]
    assert etat.watermark == "2026-11-08" and etat.donnees_jusqu_au == "2026-11-08" and etat.dernier_echec is None


def test_meme_analyse_relue_est_inchangee(base, pii, horloge):
    con, srv, _ = _psi(pii, horloge)
    ingestion.tour_ingestion(con, maintenant=horloge)
    horloge.avancer(days=7)  # l'analyse renvoyée a le même horodatage : mêmes faits, aucun doublon
    bilan = ingestion.tour_ingestion(con, maintenant=horloge)
    assert [(f["faits_nouveaux"], f["faits_inchanges"]) for f in bilan["flux"]] == [(0, 2), (0, 1)]
    assert len(_faits()) == 3


def test_evenement_de_fraicheur_annonce_sans_valeur(base, pii, horloge):
    con, _, _ = _psi(pii, horloge)
    ingestion.tour_ingestion(con, maintenant=horloge)
    with stockage.transaction() as cnx:
        lignes = cnx.execute(select(EVENEMENTS_SORTANTS.c.type_evenement, EVENEMENTS_SORTANTS.c.charge)).all()
    signaux = [lg for lg in lignes if lg.type_evenement == ingestion.TYPE_SIGNAUX]
    assert len(signaux) == 2 and not [lg for lg in lignes if lg.type_evenement == ingestion.TYPE_DEPENSES]
    assert all("score_performance" not in lg.charge and JETON not in lg.charge for lg in signaux)


# -- erreurs typées, état d'échec, secret ------------------------------------------------------------------------
ERREURS = [
    ("401", "REJ-SIGNAUX-AUTH-REFUSEE", False, None),
    ("403_permission", "REJ-SIGNAUX-PERMISSION-REFUSEE", False, None),
    ("403_quota", "REJ-SIGNAUX-LIMITE-DEBIT", True, 60),
    ("429", "REJ-SIGNAUX-LIMITE-DEBIT", True, 17),
    ("429_sans_attente", "REJ-SIGNAUX-LIMITE-DEBIT", True, 60),
    ("503", "REJ-SIGNAUX-FOURNISSEUR-INDISPONIBLE", True, 5),
    ("delai", "REJ-SIGNAUX-RESEAU", True, None),
    ("exception_secrete", "REJ-SIGNAUX-RESEAU", True, None),
    ("json_invalide", "REJ-SIGNAUX-REPONSE-INVALIDE", False, None),
    ("trop_gros", "REJ-SIGNAUX-REPONSE-TROP-GROSSE", False, None),
]


@pytest.mark.parametrize("fabrique", ["psi", "crux"])
@pytest.mark.parametrize(("scenario", "code", "reprenable", "attente"), ERREURS)
def test_erreur_typee_et_etat_d_echec_sans_avancer(base, pii, horloge, caplog, fabrique, scenario, code, reprenable,
                                                    attente):
    caplog.set_level("DEBUG")
    con, srv, cf = (_psi if fabrique == "psi" else _crux)(pii, horloge, scenario=[scenario])
    flux = con.FLUX[0]
    resultat = ingestion.tour_flux(con, flux, maintenant=horloge)
    assert resultat.statut == "echec" and resultat.erreur["code"] == code
    assert resultat.erreur["reprenable"] is reprenable and resultat.erreur["reessayer_apres_s"] == attente
    etat = _etats()[f"{con.SOURCE}|principal|{flux}"]
    assert etat.echec()["code"] == code and etat.watermark is None and etat.curseur is None
    assert etat.derniere_lecture_reussie_le is None and _faits() == []
    assert cf.ouverts == 0 and cf.ouvertures["principal"] == 1
    # la reprise réussit (le scénario est épuisé) et efface l'échec
    reprise = ingestion.tour_flux(con, flux, maintenant=horloge)
    assert reprise.statut == "termine" and _etats()[f"{con.SOURCE}|principal|{flux}"].echec() is None
    assert JETON not in caplog.text


@pytest.mark.parametrize("scenario", [s for s, *_ in ERREURS])
def test_la_cle_n_apparait_dans_aucune_erreur_ni_trace(pii, horloge, scenario):
    con, srv, cf = _psi(pii, horloge, scenario=[scenario])
    with pytest.raises(ErreurSignaux) as exc:
        con.lire_page("mobile", FENETRE, None)
    for texte in (str(exc.value), repr(exc.value), json.dumps(exc.value.publique()), repr(srv.requetes), repr(con)):
        assert JETON not in texte
    assert cf.ouverts == 0


def test_la_cle_n_apparait_ni_au_registre_ni_aux_curseurs(base, pii, horloge):
    con, srv, _ = _psi(pii, horloge, fictif=False)
    ingestion.tour_ingestion(con, maintenant=horloge)
    brut = json.dumps([list(stockage.maillons(*registre.REGISTRE)),
                       list(stockage.maillons(*registre.REGISTRE_CURSEURS))], default=str)
    assert JETON not in brut
    auth = Authentification("parametre", JETON, nom="key")
    requete = RequeteHttp("GET", "https://www.googleapis.com/x", {"url": "u"}, None, auth)
    assert JETON not in repr(requete) and JETON not in repr(requete.authentification)


def test_mauvaise_cle_donne_un_refus_d_authentification(pii, horloge):
    cf = CoffreFictif({"principal": "autre-cle-fictive"})
    srv = DoublePageSpeed(jeton=JETON, pages=_pages())
    con = ConnecteurPageSpeed(srv, compte("pagespeed", SITE), cf.fournisseurs(), maintenant=horloge, masqueur=pii)
    with pytest.raises(ErreurSignaux) as exc:
        con.lire_page("mobile", FENETRE, None)
    assert exc.value.code == "REJ-SIGNAUX-AUTH-REFUSEE" and exc.value.reprenable is False
    assert "autre-cle" not in str(exc.value)


def test_coffre_en_panne_ne_laisse_pas_fuir_son_message(pii, horloge):
    class CoffreCasse:
        def __call__(self):
            raise RuntimeError(f"coffre fermé, jeton {JETON}")

    srv = DoublePageSpeed(jeton=JETON, pages=_pages())
    con = ConnecteurPageSpeed(srv, compte("pagespeed", SITE), {"principal": CoffreCasse()}, maintenant=horloge,
                              masqueur=pii)
    with pytest.raises(ErreurSignaux) as exc:
        con.lire_page("mobile", FENETRE, None)
    assert exc.value.code == "REJ-SIGNAUX-COFFRE-INDISPONIBLE" and JETON not in str(exc.value)
    assert srv.nombre_requetes == 0


def test_transport_non_branche_arrete_le_tour(base, pii, horloge):
    cf = coffre_pour("pagespeed")
    con = ConnecteurPageSpeed(TransportNonBranche(), compte("pagespeed", SITE), cf.fournisseurs(), maintenant=horloge,
                              masqueur=pii)
    bilan = ingestion.tour_ingestion(con, maintenant=horloge)
    assert len(bilan["flux"]) == 1 and bilan["flux"][0]["erreur"]["code"] == "REJ-SIGNAUX-TRANSPORT-NON-BRANCHE"
    assert cf.ouverts == 0


def test_echec_d_authentification_arrete_les_autres_flux(base, pii, horloge):
    con, srv, _ = _psi(pii, horloge, scenario=["401"])
    bilan = ingestion.tour_ingestion(con, maintenant=horloge)
    assert len(bilan["flux"]) == 1 and srv.nombre_requetes == 1


# -- quota local, compte ------------------------------------------------------------------------------------------
def test_quota_local_refuse_avant_l_envoi_et_se_declare_a_verifier(pii, horloge):
    for classe in (ConnecteurPageSpeed, ConnecteurCrux):
        assert (classe.LIMITES.par_minute, classe.LIMITES.par_jour, classe.LIMITES.a_verifier) == (10, 200, True)
    limiteur = LimiteurQuota(Quota(par_minute=1, par_jour=None, source="test"))
    con, srv, cf = _psi(pii, horloge, limiteur=limiteur)
    con.lire_page("mobile", FENETRE, None)
    with pytest.raises(ErreurSignaux) as exc:
        con.lire_page("desktop", FENETRE, None)
    assert exc.value.code == "REJ-SIGNAUX-QUOTA-LOCAL" and exc.value.reprenable and exc.value.reessayer_apres_s >= 1
    assert srv.nombre_requetes == 1 and cf.ouvertures["principal"] == 1


def test_quota_du_jour_persiste_avec_le_curseur(base, pii, horloge):
    limiteur = LimiteurQuota(Quota(par_minute=None, par_jour=2, source="test"))
    con, srv, _ = _psi(pii, horloge, limiteur=limiteur)
    bilan = ingestion.tour_ingestion(con, maintenant=horloge)
    assert [f["statut"] for f in bilan["flux"]] == ["termine", "termine"]
    assert _etats()["pagespeed|principal|desktop"].appels_jour == 2
    horloge.avancer(days=7)
    # un « redémarrage » : nouveau limiteur du MÊME jour restauré depuis l'état → plus de requête possible ce jour-là
    limiteur2 = LimiteurQuota(Quota(par_minute=None, par_jour=2, source="test"))
    limiteur2.restaurer(horloge().date().isoformat(), 2)
    con2, srv2, _ = _psi(pii, horloge, limiteur=limiteur2)
    resultat = ingestion.tour_flux(con2, "mobile", maintenant=horloge)
    assert resultat.statut == "echec" and resultat.erreur["code"] == "REJ-SIGNAUX-QUOTA-LOCAL"
    assert srv2.nombre_requetes == 0


def test_compte_desactive_jamais_lu(pii, horloge):
    cpt = dataclasses.replace(compte("pagespeed", SITE), actif=False)
    with pytest.raises(ErreurSignaux) as exc:
        ConnecteurPageSpeed(DoublePageSpeed(jeton=JETON, pages={}), cpt, coffre_pour("pagespeed").fournisseurs(),
                            maintenant=horloge, masqueur=pii)
    assert exc.value.code == "REJ-SIGNAUX-COMPTE-INACTIF"


def test_compte_d_une_autre_source_ou_fournisseurs_incomplets_refuses(pii, horloge):
    with pytest.raises(ErreurSignaux):
        ConnecteurCrux(DoubleCrux(jeton=JETON, origines={}), compte("pagespeed", SITE),
                       coffre_pour("crux").fournisseurs(), maintenant=horloge, masqueur=pii)
    with pytest.raises(ErreurSignaux):
        ConnecteurPageSpeed(DoublePageSpeed(jeton=JETON, pages={}), compte("pagespeed", SITE), {}, maintenant=horloge,
                            masqueur=pii)
    with pytest.raises(ErreurSignaux):
        ConnecteurPageSpeed(DoublePageSpeed(jeton=JETON, pages={}), compte("pagespeed", SITE),
                            coffre_pour("pagespeed").fournisseurs(), maintenant=horloge, masqueur=None)


def test_horloge_de_reference_et_fenetre_de_ingestion_sont_en_utc(base, pii, horloge):
    assert horloge() == MAINTENANT
    con, _, _ = _psi(pii, horloge)
    resultat = ingestion.tour_flux(con, "mobile", maintenant=horloge)
    assert resultat.fenetre == "2026-11-01/2026-11-01"
