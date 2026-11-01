"""Connecteurs de LECTURE des rapports publicitaires (Google Ads, Meta Ads), contre les doubles fictifs.

Ce que ces tests prouvent : la forme des requêtes (lecture seulement, deux secrets pour Google), le calcul EXACT des
coûts (micros, arrondi au cent), la minimisation des libellés, la pagination et la reprise au curseur, l'URL
`paging.next` jamais suivie, la limite de débit au style de Meta, les relevés de dépense (CAD, hors taxes, total et
campagne, révision, aucun relevé pour un compte fictif ou une devise étrangère), leur lecture par `lire_depenses`
(CONNUE ou PARTIELLE, jamais un zéro) et les événements du bus (totaux seulement, sans nom de campagne). Ce qu'ils
ne prouvent PAS : le comportement des vrais services (aucun réseau, aucun compte publicitaire ; les formes d'API
sont celles que la recherche R4 rapporte, versions à revérifier).
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime, timedelta

import pytest
from fabriques_signaux import JETON, JETON_DEV, CoffreFictif, Horloge, coffre_pour, compte, masqueur
from m7_marketing import depenses_marketing
from m7_marketing.signaux import curseurs, ingestion, modele, publicite, registre
from m7_marketing.signaux.doubles_publicite import DoubleGoogleAds, DoubleMetaAds
from m7_marketing.signaux.erreurs import ErreurSignaux
from m7_marketing.signaux.transport import ReponseHttp, RequeteHttp
from sqlalchemy import select

from opsys import stockage
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_SORTANTS

CLIENT = "1234567890"
COMPTE_META = "act_12345678"
# les rapports publicitaires se lisent jusqu'à HIER (jour complet)
AUJOURD_HUI = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
JOURS = [date(2026, 10, 4) + timedelta(days=i) for i in range(28)]  # la fenêtre de 28 jours qui finit le 31
FENETRE = modele.Fenetre(JOURS[0], JOURS[-1])
PETITE = modele.Fenetre(date(2026, 10, 1), date(2026, 10, 3))


def _google_jours(jours=JOURS):
    """Campagne A : 40,00 $ (1 000 impr., 50 clics, 2 conv.) ; campagne B : 25,50 $ (800, 30, 1,5) ; le total du compte
    ajoute 14,50 $ d'autre dépense : 80,00 $, 2 000 impressions, 100 clics, 4 conversions."""
    a = {j.isoformat(): (40_000_000, 1000, 50, 2.0) for j in jours}
    b = {j.isoformat(): (25_500_000, 800, 30, 1.5) for j in jours}
    total = {j.isoformat(): (80_000_000, 2000, 100, 4.0) for j in jours}
    return total, {"111": {"nom": "Gouttières Laval", "jours": a}, "222": {"nom": "Revêtement Rive-Nord", "jours": b}}


def _double_google(jours=JOURS, **kw):
    total, campagnes = _google_jours(jours)
    return DoubleGoogleAds(client=CLIENT, jeton=JETON, jeton_dev=JETON_DEV, jours=total, campagnes=campagnes, **kw)


def _meta_jours(jours=JOURS):
    total = {j.isoformat(): ("50.00", 3000, 120, [("lead", 5)]) for j in jours}
    c = {j.isoformat(): ("30.00", 2000, 70, [("lead", 3)]) for j in jours}
    return total, {"333": {"nom": "Soumissions Meta", "jours": c}}


def _double_meta(jours=JOURS, **kw):
    total, campagnes = _meta_jours(jours)
    return DoubleMetaAds(compte=COMPTE_META, jeton=JETON, jours=total, campagnes=campagnes, **kw)


def _con(classe, serveur, ressource, *, fictif=False, horloge=None, compte_ref="principal", coffre=None, limiteur=None):
    source = classe.SOURCE
    cpt = compte(source, ressource, fictif=fictif, compte_ref=compte_ref)
    coffre = coffre or coffre_pour(source)
    return classe(serveur, cpt, coffre.fournisseurs(), maintenant=horloge or Horloge(AUJOURD_HUI), masqueur=masqueur(),
                  limiteur=limiteur), coffre


def _google(serveur, **kw):
    return _con(publicite.ConnecteurGoogleAds, serveur, CLIENT, **kw)


def _meta(serveur, **kw):
    return _con(publicite.ConnecteurMetaAds, serveur, COMPTE_META, **kw)


class Stub:
    def __init__(self, reponse):
        self.reponse, self.requetes = reponse, []

    def envoyer(self, requete, *, delai_s=30.0):
        self.requetes.append(requete)
        return self.reponse


def _faits(page):
    return [modele.normaliser_fait(f) for f in page.faits]


def _evenements(type_evenement):
    with stockage.transaction() as cnx:
        lignes = cnx.execute(select(EVENEMENTS_SORTANTS).where(
            EVENEMENTS_SORTANTS.c.type_evenement == type_evenement).order_by(EVENEMENTS_SORTANTS.c.evenement_id)
        ).mappings().all()
    return [(ligne["evenement_id"], codec.decoder(ligne["charge"])) for ligne in lignes]


def _releves():
    return depenses_marketing._decoder_chaine(list(stockage.maillons(*depenses_marketing.REGISTRE)))  # noqa: SLF001


def _canal(resultat, nom):
    return next(c for c in resultat["canaux"] if c["canal"] == nom)


# ======================================================================================================================
# GOOGLE ADS
# ======================================================================================================================
def test_google_requete_de_lecture_gaql_et_deux_secrets_hors_de_l_url():
    serveur = _double_google()
    con, coffre = _google(serveur)
    con.lire_page("compte", FENETRE, None)
    (requete,) = serveur.requetes
    assert requete["methode"] == "POST" and requete["url"] == \
        "https://googleads.googleapis.com/v17/customers/1234567890/googleAds:search"
    assert requete["params"] == {} and requete["schema_auth"] == "bearer"
    assert requete["corps"]["pageSize"] == 1000 and "pageToken" not in requete["corps"]
    gaql = requete["corps"]["query"]
    assert gaql.startswith("SELECT ") and " FROM customer " in gaql and "mutate" not in gaql.lower()
    assert "BETWEEN '2026-10-04' AND '2026-10-31'" in gaql
    brut = json.dumps(serveur.requetes)
    assert JETON not in brut and JETON_DEV not in brut
    assert coffre.ouvertures == {"principal": 1, "jeton_developpeur": 1} and coffre.ouverts == 0


def test_google_cout_exact_en_micros_et_arrondi_commercial_au_cent():
    jours = {"2026-10-01": (1_234_565_000, 900, 31, 12.0), "2026-10-02": (1_234_564_999, 10, 1, 2.5),
             "2026-10-03": (1, 0, 0, 0.0)}
    serveur = DoubleGoogleAds(client=CLIENT, jeton=JETON, jeton_dev=JETON_DEV, jours=jours)
    con, _ = _google(serveur)
    faits = {f["periode_debut"]: f for f in _faits(con.lire_page("compte", PETITE, None))}
    assert faits["2026-10-01"]["mesures"] == {"clics": "31", "conversions": "12", "cout_cad": "1234.57",
                                              "cout_micros": "1234565000", "impressions": "900"}
    deux = faits["2026-10-02"]["mesures"]
    assert deux["cout_cad"] == "1234.56" and deux["conversions"] == "2.5"
    assert faits["2026-10-03"]["mesures"]["cout_cad"] == "0.00" and faits["2026-10-03"]["mesures"]["cout_micros"] == "1"
    assert all(f["nature"] == "compte_jour" and f["devise"] == "CAD" and f["portee"] == {"type": "compte",
        "ref": CLIENT}
               for f in faits.values())


def test_google_campagnes_portee_stable_et_nom_minimise():
    total, campagnes = _google_jours(JOURS[:2])
    campagnes["111"]["nom"] = "Soumission jean.dupont@example.test appel 514-555-0199"
    serveur = DoubleGoogleAds(client=CLIENT, jeton=JETON, jeton_dev=JETON_DEV, jours=total, campagnes=campagnes)
    con, _ = _google(serveur)
    page = con.lire_page("campagnes", modele.Fenetre(JOURS[0], JOURS[1]), None)
    faits = _faits(page)
    assert len(faits) == 4 and {f["portee"]["ref"] for f in faits} == {"gads-111", "gads-222"}
    assert all(f["nature"] == "campagne_jour" and f["portee"]["type"] == "campagne" for f in faits)
    nom = next(f["texte"] for f in faits if f["portee"]["ref"] == "gads-111")
    assert "jean.dupont@example.test" not in nom and "514-555-0199" not in nom and "[[COURRIEL:" in nom


def test_google_devise_etrangere_garde_sa_devise_et_ne_porte_pas_cout_cad():
    jours = {"2026-10-01": (10_000_000, 100, 5, 1.0)}
    serveur = DoubleGoogleAds(client=CLIENT, jeton=JETON, jeton_dev=JETON_DEV, jours=jours, devise="USD")
    con, _ = _google(serveur)
    (fait,) = _faits(con.lire_page("compte", PETITE, None))
    assert fait["devise"] == "USD" and "cout_cad" not in fait["mesures"] and fait["mesures"]["cout_devise"] == "10.00"
    inconnue = DoubleGoogleAds(client=CLIENT, jeton=JETON, jeton_dev=JETON_DEV, jours=jours, devise="GBP")
    con2, _ = _google(inconnue)
    page = con2.lire_page("compte", PETITE, None)
    assert page.faits == () and page.ignores == 1  # jamais une devise devinée


def test_google_le_jeton_de_developpeur_est_exige_et_verifie():
    con, _ = _google(_double_google())
    cpt = con.compte
    with pytest.raises(ErreurSignaux) as exc:  # le fournisseur du secret annexe manque
        publicite.ConnecteurGoogleAds(_double_google(), cpt,
            {"principal": coffre_pour("search_console").fournisseur("principal")},
                                      maintenant=Horloge(AUJOURD_HUI), masqueur=masqueur())
    assert exc.value.code == "REJ-SIGNAUX-SECRET-REF"
    mauvais = CoffreFictif({"principal": JETON, "jeton_developpeur": "autre-jeton-developpeur"})
    con2, _ = _google(_double_google(), coffre=mauvais)
    with pytest.raises(ErreurSignaux) as exc2:
        con2.lire_page("compte", FENETRE, None)
    assert exc2.value.code == "REJ-SIGNAUX-AUTH-REFUSEE"


def test_google_aucune_ecriture_n_est_appelable():
    serveur = _double_google()
    con, _ = _google(serveur)
    url = "https://googleads.googleapis.com/v17/customers/1234567890/googleAds:search"
    for point in ("googleAds:mutate", "campaigns:mutate", "campaignBudgets:mutate", "customers:createCustomerClient"):
        with pytest.raises(ErreurSignaux) as exc:
            con._appeler(point, "POST", url, corps={"mutateOperations": []})  # noqa: SLF001
        assert exc.value.code == "REJ-SIGNAUX-ECRITURE-INTERDITE"
    for methode in ("PUT", "PATCH", "DELETE"):
        with pytest.raises(ErreurSignaux):
            RequeteHttp(methode, url)
    assert serveur.nombre_requetes == 0
    con.lire_page("campagnes", FENETRE, None)  # et la lecture normale n'envoie que des requêtes de lecture
    assert serveur.methodes() == {"POST"} and all(r["chemin"].endswith("googleAds:search") for r in serveur.requetes)
    assert all("mutate" not in r["url"] for r in serveur.requetes)


def test_google_gaql_hostile_ne_sort_jamais_de_la_fenetre():
    con, _ = _google(_double_google())
    gaql = con._gaql("campagnes", FENETRE)  # noqa: SLF001
    assert gaql.count("'") == 4 and ";" not in gaql and gaql.upper().count("SELECT") == 1
    with pytest.raises(ErreurSignaux):
        con.lire_page("campagnes'; DROP", FENETRE, None)


def test_google_pagination_reprise_au_curseur_apres_un_echec_au_milieu(base, monkeypatch):
    monkeypatch.setattr(publicite, "TAILLE_PAGE_GOOGLE", 20)
    horloge = Horloge(AUJOURD_HUI)
    serveur = _double_google(scenario=["ok", "503"])  # 56 lignes de campagne : pages de 20, 20, 16
    con, _ = _google(serveur, fictif=True, horloge=horloge)
    bilan = ingestion.tour_flux(con, "campagnes", maintenant=horloge)
    assert bilan.statut == "echec" and bilan.pages == 1 and bilan.faits_nouveaux == 20 and bilan.erreur["reprenable"]
    etat = curseurs.lire_etats(stockage.maillons(*registre.REGISTRE_CURSEURS))["google_ads|principal|campagnes"]
    assert curseurs.decoder_curseur(modele.GOOGLE_ADS, etat.curseur) == {"t": "p20"} and not etat.termine
    bilan2 = ingestion.tour_flux(con, "campagnes", maintenant=horloge)
    assert bilan2.statut == "termine" and bilan2.pages == 2 and bilan2.faits_nouveaux == 36
    assert [r["corps"].get("pageToken") for r in serveur.requetes] == [None, "p20", "p20", "p40"]
    faits = registre.charger(stockage.maillons(*registre.REGISTRE))
    assert len(faits) == 56 and len({f["fait_id"] for f in faits}) == 56


@pytest.mark.parametrize(("scenario", "code", "reprenable", "attente"), [
    ("401", "REJ-SIGNAUX-AUTH-REFUSEE", False, None),
    ("403_permission", "REJ-SIGNAUX-PERMISSION-REFUSEE", False, None),
    ("403_quota", "REJ-SIGNAUX-LIMITE-DEBIT", True, 60),
    ("429", "REJ-SIGNAUX-LIMITE-DEBIT", True, 17),
    ("503", "REJ-SIGNAUX-FOURNISSEUR-INDISPONIBLE", True, 5),
    ("delai", "REJ-SIGNAUX-RESEAU", True, None),
    ("json_invalide", "REJ-SIGNAUX-REPONSE-INVALIDE", False, None),
])
def test_google_erreurs_traduites_en_refus_types(scenario, code, reprenable, attente):
    con, coffre = _google(_double_google(scenario=[scenario]))
    with pytest.raises(ErreurSignaux) as exc:
        con.lire_page("compte", FENETRE, None)
    assert (exc.value.code, exc.value.reprenable, exc.value.reessayer_apres_s) == (code, reprenable, attente)
    assert coffre.ouverts == 0


def test_google_gaql_invalide_et_client_inconnu():
    serveur = _double_google()
    from m7_marketing.signaux.transport import Authentification

    auth = Authentification("bearer", JETON, annexes=(("developer-token", JETON_DEV),))
    base_url = "https://googleads.googleapis.com/v17/customers/1234567890/googleAds:search"
    assert serveur.envoyer(RequeteHttp("POST", base_url, corps={"query": "DELETE FROM campaign"},
                                       authentification=auth)).statut == 400
    assert serveur.envoyer(RequeteHttp("POST", base_url.replace(CLIENT, "999"), corps={"query": "SELECT 1"},
                                       authentification=auth)).statut == 404


def test_google_costmicros_invalide_est_refuse():
    for micros in ("-5", "12.5", "abc", None):
        corps = {"results": [{"customer": {"currencyCode": "CAD"}, "segments": {"date": "2026-10-01"},
                              "metrics": {"costMicros": micros, "impressions": "1", "clicks": "1", "conversions": 0}}]}
        con, _ = _google(Stub(ReponseHttp(200, corps)))
        with pytest.raises(ErreurSignaux) as exc:
            con.lire_page("compte", PETITE, None)
        assert exc.value.code == "REJ-SIGNAUX-REPONSE-INVALIDE"
    hors = {"results": [{"customer": {"currencyCode": "CAD"}, "segments": {"date": "2026-09-01"},
                         "metrics": {"costMicros": "1", "impressions": "1", "clicks": "1", "conversions": 0}}]}
    con2, _ = _google(Stub(ReponseHttp(200, hors)))
    with pytest.raises(ErreurSignaux) as exc2:
        con2.lire_page("compte", PETITE, None)
    assert exc2.value.code == "REJ-SIGNAUX-REPONSE-INVALIDE"


def test_les_deux_secrets_ne_fuient_nulle_part(caplog):
    caplog.set_level(logging.DEBUG)
    serveur = _double_google(scenario=["exception_secrete", "ok"])
    con, _ = _google(serveur)
    with pytest.raises(ErreurSignaux) as exc:
        con.lire_page("compte", FENETRE, None)
    page = con.lire_page("compte", FENETRE, None)
    sorties = [repr(con), str(exc.value), repr(exc.value.publique()), json.dumps(page.faits), repr(page),
               json.dumps(serveur.requetes), caplog.text, repr(con.compte)]
    assert exc.value.code == "REJ-SIGNAUX-RESEAU"
    assert all(JETON not in s and JETON_DEV not in s for s in sorties)


# ======================================================================================================================
# META ADS
# ======================================================================================================================
def test_meta_requete_get_de_lecture_sans_secret_dans_l_url():
    serveur = _double_meta()
    con, coffre = _meta(serveur)
    con.lire_page("compte", FENETRE, None)
    (requete,) = serveur.requetes
    assert requete["methode"] == "GET" and requete["url"] == "https://graph.facebook.com/v21.0/act_12345678/insights"
    p = requete["params"]
    assert p["level"] == "account" and p["time_increment"] == "1" and p["limit"] == "500" and "after" not in p
    assert json.loads(p["time_range"]) == {"since": "2026-10-04", "until": "2026-10-31"}
    assert "spend" in p["fields"] and "campaign_id" not in p["fields"] and requete["schema_auth"] == "bearer"
    assert "access_token" not in p and JETON not in json.dumps(serveur.requetes)
    assert coffre.ouvertures == {"principal": 1} and coffre.ouverts == 0
    con.lire_page("campagnes", FENETRE, None)
    deuxieme = serveur.requetes[1]["params"]
    assert deuxieme["level"] == "campaign" and "campaign_name" in deuxieme["fields"]


def test_meta_valeurs_conversions_sans_double_compte_et_absence_n_est_pas_zero():
    jours = {
        "2026-10-01": ("123.455", 1000, 40, [("lead", 4), ("onsite_conversion.lead_grouped", 3), ("link_click", 99)]),
        "2026-10-02": ("10.00", 500, 20, [("onsite_conversion.lead_grouped", 2), ("offsite_conversion.fb_pixel_lead",
            3)]),
        "2026-10-03": ("5.5", 300, 10, None),
        "2026-10-04": ("0.00", 0, 0, []),
    }
    con, _ = _meta(DoubleMetaAds(compte=COMPTE_META, jeton=JETON, jours=jours))
    faits = {f["periode_debut"]: f for f in _faits(con.lire_page("compte", modele.Fenetre(date(2026, 10, 1),
                                                                                           date(2026, 10, 4)), None))}
    assert faits["2026-10-01"]["mesures"] == {"clics": "40", "conversions": "4", "cout_cad": "123.46",
                                              "impressions": "1000"}  # 4, jamais 4 + 3 ; 123,455 -> 123,46
    assert faits["2026-10-02"]["mesures"]["conversions"] == "5"  # à défaut du total, les deux ventilations
    assert "conversions" not in faits["2026-10-03"]["mesures"]  # champ actions ABSENT : inconnu, pas zéro
    assert faits["2026-10-03"]["mesures"]["cout_cad"] == "5.50"
    assert faits["2026-10-04"]["mesures"]["conversions"] == "0"  # liste vide : zéro DÉCLARÉ
    assert all(f["portee"] == {"type": "compte", "ref": COMPTE_META} and f["nature"] == "compte_jour"
               for f in faits.values())


def test_meta_campagnes_nom_minimise_et_reference():
    total, campagnes = _meta_jours(JOURS[:1])
    campagnes["333"]["nom"] = "Promo courriel@example.test"
    con, _ = _meta(DoubleMetaAds(compte=COMPTE_META, jeton=JETON, jours=total, campagnes=campagnes))
    (fait,) = _faits(con.lire_page("campagnes", modele.Fenetre(JOURS[0], JOURS[0]), None))
    assert fait["portee"] == {"type": "campagne", "ref": "meta-333"} and "courriel@example.test" not in fait["texte"]


def test_meta_paging_next_n_est_jamais_suivi_seul_le_curseur_after_sert(monkeypatch):
    monkeypatch.setattr(publicite, "TAILLE_PAGE_META", 10)
    serveur = _double_meta(url_suivante_hostile=True)
    con, _ = _meta(serveur)
    curseur, total = None, 0
    while True:
        page = con.lire_page("compte", FENETRE, curseur)
        total += len(page.faits)
        if page.termine:
            break
        curseur = page.curseur_suivant
    assert total == 28
    assert [r["params"].get("after") for r in serveur.requetes] == [None, "cur-10", "cur-20"]
    assert all("exfiltration" not in r["url"] and r["url"].startswith("https://graph.facebook.com/")
               for r in serveur.requetes)
    assert all(curseurs.decoder_curseur(modele.META_ADS, c) for c in [curseur])


def test_meta_limite_de_debit_est_un_http_400_code_17_donc_reprenable(base, monkeypatch):
    monkeypatch.setattr(publicite, "TAILLE_PAGE_META", 10)
    horloge = Horloge(AUJOURD_HUI)
    serveur = _double_meta(limite_apres=1)
    con, _ = _meta(serveur, fictif=True, horloge=horloge)
    bilan = ingestion.tour_flux(con, "compte", maintenant=horloge)
    assert bilan.statut == "echec" and bilan.erreur["code"] == "REJ-SIGNAUX-LIMITE-DEBIT"
    assert bilan.erreur["reprenable"] is True and bilan.erreur["reessayer_apres_s"] == 120
    assert bilan.faits_nouveaux == 10
    etat = curseurs.lire_etats(stockage.maillons(*registre.REGISTRE_CURSEURS))["meta_ads|principal|compte"]
    assert curseurs.decoder_curseur(modele.META_ADS, etat.curseur) == {"a": "cur-10"}
    # plus tard, la limite est levée : on reprend à cur-10, sans relire la première page
    reprise = _double_meta()
    con2, _ = _meta(reprise, fictif=True, horloge=horloge)
    bilan2 = ingestion.tour_flux(con2, "compte", maintenant=horloge)
    assert bilan2.statut == "termine" and bilan2.faits_nouveaux == 18
    assert reprise.requetes[0]["params"]["after"] == "cur-10"


def test_meta_jeton_refuse_est_un_http_400_code_190():
    con, _ = _meta(_double_meta(jeton_expire=True))
    with pytest.raises(ErreurSignaux) as exc:
        con.lire_page("compte", FENETRE, None)
    assert exc.value.code == "REJ-SIGNAUX-AUTH-REFUSEE" and not exc.value.reprenable


def test_meta_requete_invalide_reste_une_requete_invalide():
    corps = {"error": {"message": "paramètre invalide", "type": "OAuthException", "code": 100}}
    con, _ = _meta(Stub(ReponseHttp(400, corps)))
    with pytest.raises(ErreurSignaux) as exc:
        con.lire_page("compte", FENETRE, None)
    assert exc.value.code == "REJ-SIGNAUX-REQUETE-INVALIDE"
    perm = {"error": {"message": "permission", "code": 200}}
    con2, _ = _meta(Stub(ReponseHttp(403, perm)))
    with pytest.raises(ErreurSignaux) as exc2:
        con2.lire_page("compte", FENETRE, None)
    assert exc2.value.code == "REJ-SIGNAUX-PERMISSION-REFUSEE"


@pytest.mark.parametrize(("scenario", "code"), [
    ("401", "REJ-SIGNAUX-AUTH-REFUSEE"), ("429", "REJ-SIGNAUX-LIMITE-DEBIT"), ("503",
        "REJ-SIGNAUX-FOURNISSEUR-INDISPONIBLE"),
    ("delai", "REJ-SIGNAUX-RESEAU"), ("json_invalide", "REJ-SIGNAUX-REPONSE-INVALIDE"),
])
def test_meta_erreurs_http_traduites(scenario, code):
    con, _ = _meta(_double_meta(scenario=[scenario]))
    with pytest.raises(ErreurSignaux) as exc:
        con.lire_page("compte", FENETRE, None)
    assert exc.value.code == code


def test_meta_reponses_mal_formees_sont_refusees():
    base_ligne = {"spend": "1.00", "impressions": "10", "clicks": "1", "account_currency": "CAD",
                  "date_start": "2026-10-01", "date_stop": "2026-10-01"}
    mauvaises = [
        {**base_ligne, "date_stop": "2026-10-02"},  # plusieurs jours malgré time_increment=1
        {**base_ligne, "spend": "abc"}, {**base_ligne, "spend": "-5"}, {**base_ligne, "spend": None},
        {**base_ligne, "date_start": "2026-09-01", "date_stop": "2026-09-01"},  # hors fenêtre
        {**base_ligne, "actions": "pas une liste"}, {**base_ligne, "actions": [{"action_type": "lead", "value": "x"}]},
    ]
    for ligne in mauvaises:
        con, _ = _meta(Stub(ReponseHttp(200, {"data": [ligne]})))
        with pytest.raises(ErreurSignaux) as exc:
            con.lire_page("compte", PETITE, None)
        assert exc.value.code == "REJ-SIGNAUX-REPONSE-INVALIDE", ligne
    con, _ = _meta(Stub(ReponseHttp(200, {"data": [{**base_ligne, "account_currency": "JPY"}]})))
    page = con.lire_page("compte", PETITE, None)
    assert page.faits == () and page.ignores == 1


def test_meta_aucune_ecriture_n_est_appelable():
    serveur = _double_meta()
    con, _ = _meta(serveur)
    url = "https://graph.facebook.com/v21.0/act_12345678/campaigns"
    for point in ("act.campaigns.create", "campaign.update", "act.adsets.create"):
        with pytest.raises(ErreurSignaux) as exc:
            con._appeler(point, "POST", url, corps={"name": "x"})  # noqa: SLF001
        assert exc.value.code == "REJ-SIGNAUX-ECRITURE-INTERDITE"
    with pytest.raises(ErreurSignaux):
        RequeteHttp("DELETE", url)
    assert serveur.nombre_requetes == 0
    with pytest.raises(ErreurSignaux) as exc2:  # un hôte hors liste (p. ex. une URL de réponse) n'est jamais appelé
        con._appeler(publicite.POINT_ACCES_META, "GET",
            "https://exfiltration.example/v21.0/act_12345678/insights")  # noqa: SLF001
    assert exc2.value.code == "REJ-SIGNAUX-HOTE-NON-PERMIS" and serveur.nombre_requetes == 0


def test_meta_le_secret_ne_fuit_nulle_part(caplog):
    caplog.set_level(logging.DEBUG)
    serveur = _double_meta(scenario=["exception_secrete", "ok"])
    con, _ = _meta(serveur)
    with pytest.raises(ErreurSignaux) as exc:
        con.lire_page("compte", FENETRE, None)
    page = con.lire_page("compte", FENETRE, None)
    sorties = [repr(con), str(exc.value), json.dumps(page.faits), json.dumps(serveur.requetes), caplog.text]
    assert all(JETON not in s for s in sorties)


# ======================================================================================================================
# DÉPENSES : relevés, registre des dépenses, événements du bus
# ======================================================================================================================
def _tour(con, horloge, flux=None):
    bilans = ingestion.tour_ingestion(con, maintenant=horloge)["flux"]
    return {b["flux"]: b for b in bilans}


def test_compte_reel_ecrit_des_releves_totaux_et_de_campagne_lus_par_lire_depenses(base):
    horloge = Horloge(AUJOURD_HUI)
    con, _ = _google(_double_google(), horloge=horloge)
    bilans = _tour(con, horloge)
    assert bilans["compte"]["statut"] == bilans["campagnes"]["statut"] == "termine"
    assert bilans["compte"]["releves_ecrits"] == 28 and bilans["campagnes"]["releves_ecrits"] == 56
    releves = _releves()
    total = next(r for r in releves if r["releve_id"] == "google_ads-principal-2026-10-04")
    assert total == {
        "releve_id": "google_ads-principal-2026-10-04", "revision": 1, "canal": "google_ads", "campagne_ref": None,
        "libelle_campagne": None, "periode_debut": "2026-10-04", "periode_fin": "2026-10-04", "montant_cad": "80.00",
        "devise": "CAD", "base_taxes": "HORS_TAXES", "source": "RELEVE_PLATEFORME", "source_ref": total["source_ref"],
        "releve_le": "2026-11-01T12:00:00Z"}
    assert total["source_ref"].startswith("google:") and len(total["source_ref"]) == len("google:") + 16
    detail = next(r for r in releves if r["releve_id"] == "google_ads-principal-gads-111-2026-10-04")
    assert detail["campagne_ref"] == "gads-111" and detail["libelle_campagne"] == "Gouttières Laval"
    assert detail["montant_cad"] == "40.00"
    lu = depenses_marketing.lire_depenses(JOURS[0], JOURS[-1])
    google = _canal(lu, "google_ads")
    assert google["statut"] == "CONNUE" and google["montant_cad"] == "2240.00" and google["base_taxes"] == "HORS_TAXES"
    assert google["jours_couverts"] == 28 and len(google["lignes_campagne"]) == 56
    assert _canal(lu, "meta")["statut"] == "NON_BRANCHEE" and lu["statut"] == "PARTIELLE"  # meta : jamais un zéro


def test_un_jour_manquant_donne_partielle_jamais_un_zero(base):
    horloge = Horloge(AUJOURD_HUI)
    jours = [j for j in JOURS if j != date(2026, 10, 15)]
    con, _ = _google(_double_google(jours), horloge=horloge)
    _tour(con, horloge)
    google = _canal(depenses_marketing.lire_depenses(JOURS[0], JOURS[-1]), "google_ads")
    assert google["statut"] == "PARTIELLE" and google["montant_cad"] is None and google["au_moins_cad"] == "2160.00"
    assert google["jours_couverts"] == 27 and "COUVERTURE_PERIODE_INCOMPLETE" in google["manque"]


def test_google_et_meta_ensemble_total_connu(base):
    horloge = Horloge(AUJOURD_HUI)
    g, _ = _google(_double_google(), horloge=horloge)
    m, _ = _meta(_double_meta(), horloge=horloge)
    _tour(g, horloge)
    bilans = _tour(m, horloge)
    assert bilans["compte"]["releves_ecrits"] == 28 and bilans["campagnes"]["releves_ecrits"] == 28
    lu = depenses_marketing.lire_depenses(JOURS[0], JOURS[-1])
    assert lu["statut"] == "CONNUE" and lu["total_cad"] == "3640.00"  # 28 x 80,00 + 28 x 50,00
    meta = _canal(lu, "meta")
    assert meta["montant_cad"] == "1400.00"
    assert any(r["releve_id"].startswith("meta-principal-meta-333") for r in _releves())


def test_un_compte_fictif_n_ecrit_jamais_un_releve_ni_un_evenement_de_depense(base):
    horloge = Horloge(AUJOURD_HUI)
    con, _ = _google(_double_google(), fictif=True, horloge=horloge)
    bilans = _tour(con, horloge)
    assert bilans["compte"]["releves_ecrits"] == 0 and bilans["compte"]["releves_non_ecrits"] == 28
    assert bilans["campagnes"]["releves_non_ecrits"] == 56
    assert _releves() == [] and _evenements("m7.depenses_marketing_constatees") == []
    assert len(registre.charger(stockage.maillons(*registre.REGISTRE))) == 84  # les SIGNAUX, eux, sont gardés (fictif)
    assert depenses_marketing.lire_depenses(JOURS[0], JOURS[-1])["statut"] == "NON_BRANCHEE"


def test_evenements_de_depense_totaux_seulement_sans_nom_de_campagne_et_sans_doublon_au_rejeu(base):
    horloge = Horloge(AUJOURD_HUI)
    con, _ = _google(_double_google(), horloge=horloge)
    _tour(con, horloge)
    evenements = _evenements("m7.depenses_marketing_constatees")
    assert len(evenements) == 28  # les 28 totaux, aucun relevé de campagne
    ident, charge = next(e for e in evenements if e[0] == "m7-depense-google_ads-principal-2026-10-04-r1")
    assert charge == {"releve_id": "google_ads-principal-2026-10-04", "revision": 1, "canal": "google_ads",
                      "periode_debut": "2026-10-04", "periode_fin": "2026-10-04", "montant_cad": "80.00",
                      "devise": "CAD", "base_taxes": "HORS_TAXES", "source": "RELEVE_PLATEFORME",
                      "releve_le": "2026-11-01T12:00:00Z"}
    brut = json.dumps(evenements)
    assert "Gouttières" not in brut and "gads-" not in brut and "campagne" not in brut
    horloge.avancer(hours=1)
    rejeu = _tour(con, horloge)
    assert rejeu["compte"]["releves_ecrits"] == 0 and rejeu["campagnes"]["releves_ecrits"] == 0
    assert len(_evenements("m7.depenses_marketing_constatees")) == 28 and len(_releves()) == 84


def test_une_depense_revisee_par_la_plateforme_est_la_revision_suivante(base):
    horloge = Horloge(AUJOURD_HUI)
    serveur = _double_google()
    con, _ = _google(serveur, horloge=horloge)
    _tour(con, horloge)
    serveur.reviser_jour("2026-10-30", 90_000_000)  # la plateforme corrige : 90,00 $ au lieu de 80,00 $
    horloge.avancer(hours=1)
    bilans = _tour(con, horloge)
    assert bilans["compte"]["faits_revises"] == 1 and bilans["compte"]["releves_ecrits"] == 1
    assert bilans["campagnes"]["releves_ecrits"] == 0  # les campagnes n'ont pas changé
    revise = next(r for r in _releves() if r["releve_id"] == "google_ads-principal-2026-10-30" and r["revision"] == 2)
    assert revise["montant_cad"] == "90.00" and revise["releve_le"] == "2026-11-01T13:00:00Z"
    assert any(e[0] == "m7-depense-google_ads-principal-2026-10-30-r2" for e in _evenements(
        "m7.depenses_marketing_constatees"))
    assert _canal(depenses_marketing.lire_depenses(JOURS[0], JOURS[-1]), "google_ads")["montant_cad"] == "2250.00"


def test_aucun_releve_pour_une_devise_etrangere_jamais_de_conversion(base):
    horloge = Horloge(AUJOURD_HUI)
    jours = {j.isoformat(): (10_000_000, 100, 5, 1.0) for j in JOURS}
    con, _ = _google(DoubleGoogleAds(client=CLIENT, jeton=JETON, jeton_dev=JETON_DEV, jours=jours, devise="USD"),
                     horloge=horloge)
    bilan = ingestion.tour_flux(con, "compte", maintenant=horloge)
    assert bilan.statut == "termine" and bilan.faits_nouveaux == 28 and bilan.releves_ecrits == 0
    assert _releves() == []  # les signaux restent, avec leur devise ; la dépense n'est pas établie


def test_un_releve_deja_declare_par_le_proprietaire_n_est_jamais_ecrase(base):
    horloge = Horloge(AUJOURD_HUI)
    with stockage.transaction():
        depenses_marketing.enregistrer_releve({
            "releve_id": "decl-oct", "revision": 1, "canal": "google_ads", "campagne_ref": None,
                "libelle_campagne": None,
            "periode_debut": "2026-10-01", "periode_fin": "2026-10-31", "montant_cad": "2000.00", "devise": "CAD",
            "base_taxes": "TAXES_INCLUSES", "source": "DECLARATION_PROPRIETAIRE", "source_ref": "declaration-001",
            "releve_le": "2026-10-31T00:00:00Z"})
    con, _ = _google(_double_google(), horloge=horloge)
    bilan = ingestion.tour_flux(con, "compte", maintenant=horloge)
    # le chevauchement est refusé, compté, jamais forcé
    assert bilan.releves_ecrits == 0 and bilan.releves_non_ecrits == 28
    assert len(_releves()) == 1


def test_identifiants_de_releve_longs_sont_courts_uniques_et_valides(base):
    horloge = Horloge(AUJOURD_HUI)
    long = "a" * 64
    total, campagnes = _google_jours(JOURS[:2])
    serveur = DoubleGoogleAds(client=CLIENT, jeton=JETON, jeton_dev=JETON_DEV, jours=total, campagnes=campagnes)
    con, _ = _google(serveur, horloge=horloge, compte_ref=long)
    fenetre = modele.Fenetre(JOURS[0], JOURS[1])
    faits = [f for flux in ("compte", "campagnes") for f in con.lire_page(flux, fenetre, None).faits]
    releves = con.releves_depenses(faits)
    ids = [r["releve_id"] for r in releves]
    assert len(ids) == len(set(ids)) == 2 + 4 and all(len(i) <= 80 and ":" in i for i in ids)
    assert all(depenses_marketing.normaliser_releve(r) == r for r in releves)
    court, _ = _google(serveur, horloge=horloge, compte_ref="principal")
    naturels = [r["releve_id"] for r in court.releves_depenses(faits)]
    assert all(":" not in i for i in naturels) and not set(naturels) & set(ids)


def test_meta_releves_et_evenements(base):
    horloge = Horloge(AUJOURD_HUI)
    con, _ = _meta(_double_meta(), horloge=horloge)
    _tour(con, horloge)
    evenements = _evenements("m7.depenses_marketing_constatees")
    assert len(evenements) == 28 and all(c["canal"] == "meta" and c["montant_cad"] == "50.00" for _, c in evenements)
    detail = next(r for r in _releves() if r["campagne_ref"] == "meta-333")
    assert detail["libelle_campagne"] == "Soumissions Meta" and detail["montant_cad"] == "30.00"


def test_evenement_de_signaux_a_la_fin_de_la_fenetre_sans_valeur_de_mesure(base):
    horloge = Horloge(AUJOURD_HUI)
    con, _ = _google(_double_google(), fictif=True, horloge=horloge)
    _tour(con, horloge)
    evenements = _evenements("m7.signaux_marketing_constates")
    assert sorted(c["flux"] for _, c in evenements) == ["campagnes", "compte"]
    charge = next(c for _, c in evenements if c["flux"] == "compte")
    assert charge["source"] == "google_ads" and charge["faits_nouveaux"] == 28 and charge["fictif"] is True
    assert charge["periode_debut"] == "2026-10-04" and charge["periode_fin"] == "2026-10-31"
    assert "80.00" not in json.dumps(charge) and "Gouttières" not in json.dumps(charge)


def test_quota_local_du_jour_survit_a_un_redemarrage(base):
    horloge = Horloge(AUJOURD_HUI)
    serveur = _double_google()
    con, _ = _google(serveur, fictif=True, horloge=horloge)
    ingestion.tour_flux(con, "compte", maintenant=horloge)
    etat = curseurs.lire_etats(stockage.maillons(*registre.REGISTRE_CURSEURS))["google_ads|principal|compte"]
    assert etat.jour_quota == "2026-11-01" and etat.appels_jour == 1
    # « redémarrage » : un nouveau connecteur, un nouveau limiteur ; le compte du jour est repris de l'état persisté
    con2, _ = _google(_double_google(), fictif=True, horloge=horloge)
    ingestion.tour_flux(con2, "campagnes", maintenant=horloge)
    assert con2.limiteur.compte_du_jour == ("2026-11-01", 2)


def test_relire_la_meme_fenetre_a_la_meme_reponse_ne_fait_pas_tomber_le_tour(base):
    horloge = Horloge(AUJOURD_HUI)
    con, _ = _google(_double_google(), fictif=True, horloge=horloge)
    _tour(con, horloge)
    horloge.avancer(hours=1)
    _tour(con, horloge)  # fenêtre de relecture (7 jours), réponse inconnue du registre : événement publié
    horloge.avancer(hours=1)
    bilans = _tour(con, horloge)  # même fenêtre, même réponse, autre instant
    assert bilans["compte"]["statut"] == "termine"
