"""Connecteurs de LECTURE de la fiche d'établissement Google (avis et performance), contre le double fictif.

Ce que ces tests prouvent : la forme des requêtes, la lecture des réponses, la minimisation (aucun nom d'auteur,
texte seulement sur option et masqué), les trous qui ne deviennent jamais des zéros, la pagination et la reprise au
curseur, l'idempotence et la révision, les erreurs typées, l'absence de secret partout, l'absence de toute écriture.
Ce qu'ils ne prouvent PAS : le comportement du vrai service (aucun réseau, la forme de l'API est celle que la
recherche R4 rapporte).
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, date, datetime

import pytest
from fabriques_signaux import JETON, CoffreFictif, Horloge, coffre_pour, compte, masqueur
from m7_marketing.signaux import curseurs, gbp, ingestion, modele, registre
from m7_marketing.signaux.base import REPONSE_OCTETS_MAX
from m7_marketing.signaux.doubles_gbp import DoubleGbp, avis_fictif
from m7_marketing.signaux.erreurs import ErreurSignaux
from m7_marketing.signaux.quotas import LimiteurQuota, Quota
from m7_marketing.signaux.transport import Authentification, ReponseHttp, RequeteHttp
from sqlalchemy import select

from opsys import stockage
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_SORTANTS

AVIS_RES = "accounts/123/locations/456"
PERF_RES = "locations/456"
AUJOURD_HUI = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
FENETRE_AVIS = modele.Fenetre(date(2026, 10, 4), date(2026, 10, 31))
FENETRE_PERF = modele.Fenetre(date(2026, 10, 1), date(2026, 10, 3))


def _cree(jour: str, heure: str = "14:03:22.123456Z") -> str:
    return f"{jour}T{heure}"


def _avis_recents(n: int, *, premier: str = "2026-10-30") -> list[dict]:
    return [avis_fictif(f"rev-recent-{i:03d}", 5 - i % 5, _cree(premier, f"10:{i % 60:02d}:00Z"),
                        commentaire=f"Très bon travail numéro {i}") for i in range(n)]


def _connecteur(classe, serveur, ressource, *, fictif=True, options=None, horloge=None, limiteur=None, coffre=None):
    source = classe.SOURCE
    cpt = compte(source, ressource, fictif=fictif, options=options)
    coffre = coffre or coffre_pour(source)
    horloge = horloge or Horloge(AUJOURD_HUI)
    return classe(serveur, cpt, coffre.fournisseurs(), maintenant=horloge, masqueur=masqueur(),
        limiteur=limiteur), coffre


def _avis(serveur, **kw):
    return _connecteur(gbp.ConnecteurGbpAvis, serveur, AVIS_RES, **kw)


def _perf(serveur, **kw):
    return _connecteur(gbp.ConnecteurGbpInsights, serveur, PERF_RES, **kw)


class Stub:
    """Transport qui rend toujours la même réponse (réponses mal formées)."""

    def __init__(self, reponse):
        self.reponse, self.requetes = reponse, []

    def envoyer(self, requete, *, delai_s=30.0):
        self.requetes.append(requete)
        return self.reponse


def _faits_registre():
    return registre.charger(stockage.maillons(*registre.REGISTRE))


def _evenements(type_evenement):
    with stockage.transaction() as cnx:
        lignes = cnx.execute(select(EVENEMENTS_SORTANTS).where(
            EVENEMENTS_SORTANTS.c.type_evenement == type_evenement).order_by(EVENEMENTS_SORTANTS.c.evenement_id)
        ).mappings().all()
    return [(ligne["evenement_id"], codec.decoder(ligne["charge"])) for ligne in lignes]


def _etat(source, compte_ref, flux):
    return curseurs.lire_etats(stockage.maillons(*registre.REGISTRE_CURSEURS))[curseurs.cle_etat(source, compte_ref,
        flux)]


# ======================================================================================================================
# AVIS : forme de la requête, faits, minimisation
# ======================================================================================================================
def test_requete_des_avis_est_un_get_de_lecture_sans_secret():
    serveur = DoubleGbp(jeton=JETON, avis={AVIS_RES: _avis_recents(2)})
    con, coffre = _avis(serveur)
    con.lire_page("principal", FENETRE_AVIS, None)
    (requete,) = serveur.requetes
    assert requete["methode"] == "GET" and requete["schema_auth"] == "bearer"
    assert requete["url"] == "https://mybusiness.googleapis.com/v4/accounts/123/locations/456/reviews"
    assert requete["params"] == {"pageSize": "50"} and requete["corps"] is None
    assert JETON not in json.dumps(serveur.requetes)
    assert coffre.ouvertures == {"principal": 1} and coffre.ouverts == 0  # ouvert le temps de l'appel, refermé


def test_un_avis_devient_un_fait_sans_auteur_ni_texte_par_defaut():
    avis = [avis_fictif("rev-A", 5, _cree("2026-10-30"), commentaire="Excellent, merci Marie Tremblay !",
                        auteur="Marie Tremblay", reponse="Merci !"),
            avis_fictif("rev-B", 2, _cree("2026-10-29"), auteur="Jean Gagnon")]
    serveur = DoubleGbp(jeton=JETON, avis={AVIS_RES: avis})
    con, _ = _avis(serveur)
    page = con.lire_page("principal", FENETRE_AVIS, None)
    faits = {f["portee"]["ref"]: modele.normaliser_fait(f) for f in page.faits}
    ref_a = hashlib.sha256(b"rev-A").hexdigest()[:16]
    ref_b = hashlib.sha256(b"rev-B").hexdigest()[:16]
    a, b = faits[ref_a], faits[ref_b]
    assert a["nature"] == "avis" and a["portee"]["type"] == "avis"
    assert a["periode_debut"] == a["periode_fin"] == "2026-10-30"
    assert a["mesures"] == {"a_reponse": "1", "longueur_texte": str(len("Excellent, merci Marie Tremblay !")),
                            "note": "5"}
    assert b["mesures"] == {"a_reponse": "0", "longueur_texte": "0", "note": "2"}
    assert a["texte"] is None and b["texte"] is None  # option fermée par défaut
    brut = json.dumps(page.faits, ensure_ascii=False)
    for interdit in ("Marie", "Tremblay", "Gagnon", "Excellent", "rev-A", "rev-B"):
        assert interdit not in brut  # ni nom d'auteur, ni texte, ni identifiant brut


def test_extrait_conserve_sur_option_masque_et_borne():
    long = "Équipe ponctuelle. Écrivez à client.fictif@example.test ou appelez le 514-555-0123. " + "x" * 400
    serveur = DoubleGbp(jeton=JETON, avis={AVIS_RES: [avis_fictif("rev-L", 4, _cree("2026-10-30"), commentaire=long)]})
    con, _ = _avis(serveur, options={"extraits_avis": True})
    (fait,) = con.lire_page("principal", FENETRE_AVIS, None).faits
    texte = modele.normaliser_fait(fait)["texte"]
    assert texte is not None and len(texte) <= 280
    assert "client.fictif@example.test" not in texte and "514-555-0123" not in texte
    assert "[[COURRIEL:" in texte and "[[TEL:" in texte
    assert fait["mesures"]["longueur_texte"] == str(len(long))  # la longueur est celle de l'avis, pas de l'extrait


def test_note_inconnue_est_ignoree_jamais_devinee():
    avis = [avis_fictif("rev-X", 3, _cree("2026-10-30")), avis_fictif("rev-Y", 3, _cree("2026-10-29"))]
    avis[0]["starRating"] = "STAR_RATING_UNSPECIFIED"
    serveur = DoubleGbp(jeton=JETON, avis={AVIS_RES: avis})
    con, _ = _avis(serveur)
    page = con.lire_page("principal", FENETRE_AVIS, None)
    assert len(page.faits) == 1 and page.ignores == 1


def test_avis_hors_fenetre_et_doublon_de_page():
    avis = [avis_fictif("rev-D", 4, _cree("2026-10-30")), avis_fictif("rev-D", 4, _cree("2026-10-30")),
            avis_fictif("rev-vieux", 4, _cree("2026-09-01"), modifie=_cree("2026-10-20"))]
    serveur = DoubleGbp(jeton=JETON, avis={AVIS_RES: avis})
    con, _ = _avis(serveur)
    page = con.lire_page("principal", FENETRE_AVIS, None)
    assert len(page.faits) == 1 and page.ignores == 1  # le vieil avis (créé avant la fenêtre) n'est pas un fait


# ======================================================================================================================
# AVIS : pagination, arrêt, reprise au curseur
# ======================================================================================================================
def test_pagination_s_arrete_quand_la_page_ne_contient_plus_rien_de_recent():
    recents = _avis_recents(40)
    vieux = [avis_fictif(f"rev-vieux-{i:03d}", 3, _cree("2026-08-15", f"09:{i % 60:02d}:00Z")) for i in range(90)]
    serveur = DoubleGbp(jeton=JETON, avis={AVIS_RES: recents + vieux})
    con, _ = _avis(serveur)
    page1 = con.lire_page("principal", FENETRE_AVIS, None)
    assert len(page1.faits) == 40 and not page1.termine and page1.curseur_suivant
    page2 = con.lire_page("principal", FENETRE_AVIS, page1.curseur_suivant)
    assert page2.faits == () and page2.termine and page2.curseur_suivant is None
    assert [r["params"].get("pageToken") for r in serveur.requetes] == [None, "tk-50"]  # 130 avis, 2 requêtes seulement


def test_un_curseur_d_une_autre_source_est_refuse():
    serveur = DoubleGbp(jeton=JETON, avis={AVIS_RES: _avis_recents(1)})
    con, _ = _avis(serveur)
    etranger = curseurs.encoder_curseur(modele.SEARCH_CONSOLE, {"t": "tk-50"})
    with pytest.raises(ErreurSignaux) as exc:
        con.lire_page("principal", FENETRE_AVIS, etranger)
    assert exc.value.code == "REJ-SIGNAUX-CURSEUR-INVALIDE" and serveur.nombre_requetes == 0


def test_reprise_au_curseur_apres_un_echec_au_milieu(base):
    horloge = Horloge(AUJOURD_HUI)
    recents = _avis_recents(120)  # 3 pages de 50, 50, 20
    serveur = DoubleGbp(jeton=JETON, avis={AVIS_RES: recents}, scenario=["ok", "503"])
    con, _ = _avis(serveur, horloge=horloge)
    bilan = ingestion.tour_flux(con, "principal", maintenant=horloge)
    assert bilan.statut == "echec" and bilan.erreur["code"] == "REJ-SIGNAUX-FOURNISSEUR-INDISPONIBLE"
    assert bilan.erreur["reprenable"] is True and bilan.pages == 1 and bilan.faits_nouveaux == 50
    etat = _etat(gbp.ConnecteurGbpAvis.SOURCE, "principal", "principal")
    assert etat.termine is False and etat.fenetre == FENETRE_AVIS.cle() and etat.derniere_lecture_reussie_le is None
    assert etat.echec()["code"] == "REJ-SIGNAUX-FOURNISSEUR-INDISPONIBLE"
    assert curseurs.decoder_curseur(modele.GBP_AVIS, etat.curseur) == {"t": "tk-50"}  # la page 2 n'est PAS sautée
    # reprise : jamais la page 1 de nouveau
    bilan2 = ingestion.tour_flux(con, "principal", maintenant=horloge)
    assert bilan2.statut == "termine" and bilan2.pages == 2 and bilan2.faits_nouveaux == 70
    assert [r["params"].get("pageToken") for r in serveur.requetes] == [None, "tk-50", "tk-50", "tk-100"]
    assert len(_faits_registre()) == 120
    assert _etat(modele.GBP_AVIS, "principal", "principal").echec() is None


def test_idempotence_puis_revision_quand_une_reponse_est_ajoutee(base):
    horloge = Horloge(AUJOURD_HUI)
    avis = _avis_recents(3, premier="2026-10-30")
    serveur = DoubleGbp(jeton=JETON, avis={AVIS_RES: avis})
    con, _ = _avis(serveur, horloge=horloge)
    assert ingestion.tour_flux(con, "principal", maintenant=horloge).faits_nouveaux == 3
    horloge.avancer(hours=1)
    rejeu = ingestion.tour_flux(con, "principal", maintenant=horloge)
    assert (rejeu.faits_nouveaux, rejeu.faits_revises, rejeu.faits_inchanges) == (0, 0, 3)
    # l'établissement répond à l'avis 1 : la valeur change, c'est la révision suivante du MÊME fait
    modifie = [dict(a) for a in avis]
    modifie[1]["reviewReply"] = {"comment": "Merci !", "updateTime": _cree("2026-10-31", "09:00:00Z")}
    modifie[1]["updateTime"] = _cree("2026-10-31", "09:00:00Z")
    serveur.remplacer_avis(AVIS_RES, modifie)
    horloge.avancer(hours=1)
    revise = ingestion.tour_flux(con, "principal", maintenant=horloge)
    assert (revise.faits_nouveaux, revise.faits_revises, revise.faits_inchanges) == (0, 1, 2)
    courants = registre.courants(_faits_registre())
    revises = [f for f in courants.values() if f["revision"] == 2]
    assert len(revises) == 1 and revises[0]["mesures"]["a_reponse"] == "1"
    assert len(_faits_registre()) == 4  # 3 initiaux + 1 révision, jamais un doublon


# ======================================================================================================================
# AVIS : erreurs typées, frontières, secrets
# ======================================================================================================================
@pytest.mark.parametrize(("scenario", "code", "reprenable", "attente"), [
    ("401", "REJ-SIGNAUX-AUTH-REFUSEE", False, None),
    ("403_permission", "REJ-SIGNAUX-PERMISSION-REFUSEE", False, None),
    ("403_quota", "REJ-SIGNAUX-LIMITE-DEBIT", True, 60),
    ("429", "REJ-SIGNAUX-LIMITE-DEBIT", True, 17),
    ("429_sans_attente", "REJ-SIGNAUX-LIMITE-DEBIT", True, 60),
    ("503", "REJ-SIGNAUX-FOURNISSEUR-INDISPONIBLE", True, 5),
    ("delai", "REJ-SIGNAUX-RESEAU", True, None),
    ("json_invalide", "REJ-SIGNAUX-REPONSE-INVALIDE", False, None),
    ("trop_gros", "REJ-SIGNAUX-REPONSE-TROP-GROSSE", False, None),
])
def test_erreurs_du_fournisseur_traduites_en_refus_types(scenario, code, reprenable, attente):
    serveur = DoubleGbp(jeton=JETON, avis={AVIS_RES: _avis_recents(1)}, scenario=[scenario])
    con, coffre = _avis(serveur)
    with pytest.raises(ErreurSignaux) as exc:
        con.lire_page("principal", FENETRE_AVIS, None)
    assert (exc.value.code, exc.value.reprenable, exc.value.reessayer_apres_s) == (code, reprenable, attente)
    assert coffre.ouverts == 0


def test_fiche_inconnue_est_introuvable_et_jeton_faux_est_refuse():
    con, _ = _avis(DoubleGbp(jeton=JETON, avis={"accounts/9/locations/9": []}))
    with pytest.raises(ErreurSignaux) as exc:
        con.lire_page("principal", FENETRE_AVIS, None)
    assert exc.value.code == "REJ-SIGNAUX-INTROUVABLE"
    con2, _ = _avis(DoubleGbp(jeton="un-autre-jeton", avis={AVIS_RES: []}))
    with pytest.raises(ErreurSignaux) as exc2:
        con2.lire_page("principal", FENETRE_AVIS, None)
    assert exc2.value.code == "REJ-SIGNAUX-AUTH-REFUSEE"


def test_aucune_ecriture_n_est_appelable():
    serveur = DoubleGbp(jeton=JETON, avis={AVIS_RES: []})
    con, _ = _avis(serveur)
    for point in ("accounts.locations.reviews.updateReply", "accounts.locations.localPosts.create"):
        with pytest.raises(ErreurSignaux) as exc:
            con._appeler(point, "GET",
                "https://mybusiness.googleapis.com/v4/accounts/123/locations/456/reviews")  # noqa: SLF001
        assert exc.value.code == "REJ-SIGNAUX-ECRITURE-INTERDITE"
    with pytest.raises(ErreurSignaux) as exc2:
        RequeteHttp("PUT", "https://mybusiness.googleapis.com/v4/x")
    assert exc2.value.code == "REJ-SIGNAUX-ECRITURE-INTERDITE"
    assert serveur.nombre_requetes == 0
    # et le double lui-même refuse toute méthode autre que GET (405), même authentifiée
    reponse = serveur.envoyer(RequeteHttp("POST",
        "https://mybusiness.googleapis.com/v4/accounts/123/locations/456/reviews",
                                          corps={}, authentification=Authentification("bearer", JETON)))
    assert reponse.statut == 405


def test_hote_hors_liste_et_url_de_reponse_ne_sont_jamais_suivis():
    serveur = DoubleGbp(jeton=JETON, avis={AVIS_RES: []})
    con, _ = _avis(serveur)
    for url in ("https://exfiltration.example/v4/accounts/123/locations/456/reviews",
                "http://mybusiness.googleapis.com/v4/x", "https://u:p@mybusiness.googleapis.com/v4/x"):
        with pytest.raises(ErreurSignaux) as exc:
            con._appeler(gbp.POINT_ACCES_AVIS, "GET", url)  # noqa: SLF001
        assert exc.value.code == "REJ-SIGNAUX-HOTE-NON-PERMIS"
    assert serveur.nombre_requetes == 0


def test_quota_local_refuse_avant_l_envoi():
    serveur = DoubleGbp(jeton=JETON, avis={AVIS_RES: _avis_recents(1)})
    con, _ = _avis(serveur, limiteur=LimiteurQuota(Quota(par_minute=1, par_jour=None, source="test")))
    con.lire_page("principal", FENETRE_AVIS, None)
    with pytest.raises(ErreurSignaux) as exc:
        con.lire_page("principal", FENETRE_AVIS, None)
    assert exc.value.code == "REJ-SIGNAUX-QUOTA-LOCAL" and exc.value.reprenable and exc.value.reessayer_apres_s
    assert serveur.nombre_requetes == 1


def test_le_secret_ne_fuit_nulle_part(caplog):
    caplog.set_level(logging.DEBUG)
    serveur = DoubleGbp(jeton=JETON, avis={AVIS_RES: _avis_recents(2)}, scenario=["exception_secrete", "ok"])
    con, _ = _avis(serveur)
    with pytest.raises(ErreurSignaux) as exc:
        con.lire_page("principal", FENETRE_AVIS, None)
    page = con.lire_page("principal", FENETRE_AVIS, None)
    sorties = [repr(con), str(exc.value), repr(exc.value.publique()), json.dumps(page.faits), repr(page),
               json.dumps(serveur.requetes), caplog.text, repr(con.compte)]
    assert exc.value.code == "REJ-SIGNAUX-RESEAU"
    assert all(JETON not in s for s in sorties)


def test_coffre_ferme_est_un_refus_type_sans_son_message():
    class CoffreCasse(CoffreFictif):
        def fournisseur(self, role):
            def ouvrir():
                raise RuntimeError(f"coffre verrouillé, secret={JETON}")

            return ouvrir

    serveur = DoubleGbp(jeton=JETON, avis={AVIS_RES: []})
    con, _ = _avis(serveur, coffre=CoffreCasse({"principal": JETON}))
    with pytest.raises(ErreurSignaux) as exc:
        con.lire_page("principal", FENETRE_AVIS, None)
    assert exc.value.code == "REJ-SIGNAUX-COFFRE-INDISPONIBLE" and JETON not in str(exc.value)
    assert serveur.nombre_requetes == 0


def test_reponse_mal_formee_est_refusee():
    for corps in ({"reviews": "pas une liste"}, {"reviews": [{"reviewId": 12}]},
                  {"reviews": [{"reviewId": "a", "createTime": "hier", "updateTime": "hier", "starRating": "ONE"}]}):
        con, _ = _avis(Stub(ReponseHttp(200, corps)))
        with pytest.raises(ErreurSignaux) as exc:
            con.lire_page("principal", FENETRE_AVIS, None)
        assert exc.value.code in ("REJ-SIGNAUX-REPONSE-INVALIDE", "REJ-SIGNAUX-FAIT-INVALIDE")
    assert REPONSE_OCTETS_MAX == 5 * 1024 * 1024


# ======================================================================================================================
# PERFORMANCE : requêtes, faits, trous
# ======================================================================================================================
def _series():
    def serie(valeurs):
        return {"2026-10-01": valeurs[0], "2026-10-02": valeurs[1], "2026-10-03": valeurs[2]}

    return {PERF_RES: {
        "BUSINESS_IMPRESSIONS_DESKTOP_MAPS": serie(["10", "20", None]),
        "BUSINESS_IMPRESSIONS_MOBILE_MAPS": serie(["30", None, None]),
        "BUSINESS_IMPRESSIONS_DESKTOP_SEARCH": serie(["5", "6", None]),
        "BUSINESS_IMPRESSIONS_MOBILE_SEARCH": serie(["7", "8", None]),
        "CALL_CLICKS": serie(["2", "3", None]),
        "BUSINESS_DIRECTION_REQUESTS": serie(["1", None, None]),
        "WEBSITE_CLICKS": serie(["9", "4", None]),
    }}


def test_une_requete_par_metrique_en_get_sans_secret():
    serveur = DoubleGbp(jeton=JETON, series=_series())
    con, coffre = _perf(serveur)
    page = con.lire_page("principal", FENETRE_PERF, None)
    assert page.appels == 7 and serveur.nombre_requetes == 7 and serveur.methodes() == {"GET"}
    assert {r["params"]["dailyMetric"] for r in serveur.requetes} == set(gbp.METRIQUES)
    premiere = serveur.requetes[0]
    assert premiere["url"] == "https://businessprofileperformance.googleapis.com/v1/locations/456:getDailyMetricsTimeSeries"
    assert {k: v for k, v in premiere["params"].items() if k != "dailyMetric"} == {
        "dailyRange.startDate.year": "2026", "dailyRange.startDate.month": "10", "dailyRange.startDate.day": "1",
        "dailyRange.endDate.year": "2026", "dailyRange.endDate.month": "10", "dailyRange.endDate.day": "3"}
    assert JETON not in json.dumps(serveur.requetes)
    assert coffre.ouvertures == {"principal": 7} and coffre.ouverts == 0


def test_faits_de_performance_aux_valeurs_calculees_a_la_main_et_trous_sans_zero():
    serveur = DoubleGbp(jeton=JETON, series=_series())
    con, _ = _perf(serveur)
    page = con.lire_page("principal", FENETRE_PERF, None)
    faits = {f["periode_debut"]: modele.normaliser_fait(f) for f in page.faits}
    assert sorted(faits) == ["2026-10-01", "2026-10-02"]  # le 3 n'a AUCUNE valeur : aucun fait, pas de zéro
    assert faits["2026-10-01"]["mesures"] == {
        "appels": "2", "clics_site": "9", "impressions_maps_mobile": "30", "impressions_maps_ordinateur": "10",
        "impressions_recherche_mobile": "7", "impressions_recherche_ordinateur": "5", "itineraires": "1"}
    # le 2 : trous pour mobile-maps et itinéraires => mesures ABSENTES, jamais "0"
    assert faits["2026-10-02"]["mesures"] == {
        "appels": "3", "clics_site": "4", "impressions_maps_ordinateur": "20", "impressions_recherche_mobile": "8",
        "impressions_recherche_ordinateur": "6"}
    assert all(f["nature"] == "insights_fiche_jour" and f["portee"] == {"type": "fiche", "ref": PERF_RES}
               for f in faits.values())
    assert page.curseur_suivant is None and page.termine


def test_performance_refuse_une_date_hors_periode_ou_invalide():
    for corps in ({"timeSeries": {"datedValues": [{"date": {"year": 2026, "month": 9, "day": 1}, "value": "1"}]}},
                  {"timeSeries": {"datedValues": [{"date": {"year": 2026, "month": 2, "day": 31}, "value": "1"}]}},
                  {"timeSeries": {"datedValues": [{"date": {"year": 2026, "month": 10, "day": 1}, "value": "x"}]}},
                  {"timeSeries": "vide"}):
        con, _ = _perf(Stub(ReponseHttp(200, corps)))
        with pytest.raises(ErreurSignaux) as exc:
            con.lire_page("principal", FENETRE_PERF, None)
        assert exc.value.code == "REJ-SIGNAUX-REPONSE-INVALIDE"


def test_performance_une_page_incomplete_est_rejouee_en_entier(base):
    horloge = Horloge(AUJOURD_HUI)
    serveur = DoubleGbp(jeton=JETON, series=_series(), scenario=["ok", "ok", "503"])  # la 3e métrique échoue
    con, _ = _perf(serveur, horloge=horloge)
    bilan = ingestion.tour_flux(con, "principal", maintenant=horloge)
    assert bilan.statut == "echec" and bilan.erreur["code"] == "REJ-SIGNAUX-FOURNISSEUR-INDISPONIBLE"
    assert len(_faits_registre()) == 0  # rien d'écrit à moitié
    assert _etat(modele.GBP_INSIGHTS, "principal", "principal").curseur is None


def test_performance_retard_de_trois_jours_et_ingestion_complete(base):
    horloge = Horloge(AUJOURD_HUI)
    serveur = DoubleGbp(jeton=JETON, series=_series())
    con, _ = _perf(serveur, horloge=horloge)
    fenetre = con.fenetre_suivante(None, AUJOURD_HUI.date())
    assert fenetre.fin == date(2026, 10, 28)  # retard déclaré : 3 jours
    bilan = ingestion.tour_flux(con, "principal", maintenant=horloge)
    assert bilan.statut == "termine" and bilan.faits_nouveaux == 2
    evenements = _evenements("m7.signaux_marketing_constates")
    assert len(evenements) == 1
    charge = evenements[0][1]
    assert charge["source"] == "gbp_insights" and charge["faits_nouveaux"] == 2 and charge["fictif"] is True
    assert JETON not in json.dumps(charge) and "valeur" not in charge
    # rejeu : même fenêtre relue, aucun doublon de fait
    horloge.avancer(hours=2)
    rejeu = ingestion.tour_flux(con, "principal", maintenant=horloge)
    assert rejeu.faits_nouveaux == 0 and len(_faits_registre()) == 2


def test_performance_n_accepte_pas_de_curseur_et_aucune_ecriture():
    serveur = DoubleGbp(jeton=JETON, series=_series())
    con, _ = _perf(serveur)
    with pytest.raises(ErreurSignaux) as exc:
        con.lire_page("principal", FENETRE_PERF, curseurs.encoder_curseur(modele.GBP_INSIGHTS, {"t": "x"}))
    assert exc.value.code == "REJ-SIGNAUX-CURSEUR-INVALIDE"
    with pytest.raises(ErreurSignaux) as exc2:
        con._appeler("locations.updateAttributes", "GET",  # noqa: SLF001
                     "https://businessprofileperformance.googleapis.com/v1/locations/456:getDailyMetricsTimeSeries")
    assert exc2.value.code == "REJ-SIGNAUX-ECRITURE-INTERDITE" and serveur.nombre_requetes == 0
    assert serveur.envoyer(RequeteHttp("GET", "https://businessprofileperformance.googleapis.com/v1/locations/999:x",
                                       authentification=None)).statut == 401


def test_performance_erreur_de_metrique_inconnue_est_une_requete_invalide():
    serveur = DoubleGbp(jeton=JETON, series=_series())
    reponse = serveur.envoyer(RequeteHttp(
        "GET", "https://businessprofileperformance.googleapis.com/v1/locations/456:getDailyMetricsTimeSeries",
        params={"dailyMetric": "METRIQUE_INCONNUE"}, authentification=Authentification("bearer", JETON)))
    assert reponse.statut == 400
