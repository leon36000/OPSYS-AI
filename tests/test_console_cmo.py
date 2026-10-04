"""Projection de plan M7.11a, lecture seule et faits M2/M3/M5 synthétiques."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from opsys import evenements, identite, stockage
from opsys.console import application
from opsys.console.securite import Configuration
from opsys.departements import charger_departements
from opsys.stockage.schema import EVENEMENTS_RECUS, EVENEMENTS_SORTANTS

SECRET = "secret-cmo-console-fictif-2026-" + "x" * 32
PREFIXE = "/opsys"
MOT_DE_PASSE = "mot-de-passe-cmo-fictif-1234"
PROPRIETAIRE = "nathan.cmo.fictif"


@pytest.fixture
def client_cmo(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'console-cmo.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, PROPRIETAIRE, "Nathan fictif", MOT_DE_PASSE, ["nathan_owner"])
        identite.creer_personne(cnx, "admin.cmo.fictif", "Admin fictif", MOT_DE_PASSE, ["admin"])
        identite.creer_personne(cnx, "employe.cmo.fictif", "Employé fictif", MOT_DE_PASSE, ["employee"])
        identite.creer_personne(cnx, "vendeur.cmo.fictif", "Vendeur fictif", MOT_DE_PASSE, ["seller"])
        identite.creer_personne(cnx, "client.cmo.fictif", "Client fictif", MOT_DE_PASSE, ["client"])
    app = application.creer_application(
        Configuration(SECRET, cookie_securise=False, prefixe=PREFIXE), charger_departements(), stockage.transaction
    )
    with TestClient(app, base_url=f"https://testserver{PREFIXE}") as client:
        yield client
    stockage.liberer()


def _connecter(client: TestClient, utilisateur: str = PROPRIETAIRE) -> str:
    reponse = client.post(
        "/connexion", data={"identifiant": utilisateur, "mot_de_passe": MOT_DE_PASSE}, follow_redirects=False
    )
    assert reponse.status_code == 303, reponse.text
    return client.get("/api/session").json()["csrf"]


def _params(depart="2026-10-01", debut="2026-09-01", fin="2026-09-30"):
    return {"date_depart": depart, "debut": debut, "fin": fin}


def test_cmo_routes_authentifient_et_refusent_employe(client_cmo):
    assert client_cmo.get("/marketing/cmo", follow_redirects=False).status_code == 303
    assert client_cmo.get("/api/marketing/cmo/plan").status_code == 401
    _connecter(client_cmo, "employe.cmo.fictif")
    assert client_cmo.get("/marketing/cmo", params=_params(), follow_redirects=False).status_code == 403
    assert client_cmo.get("/api/marketing/cmo/plan", params=_params()).status_code == 403
    _connecter(client_cmo, "vendeur.cmo.fictif")
    assert client_cmo.get("/api/marketing/cmo/plan", params=_params()).status_code == 403
    _connecter(client_cmo, "client.cmo.fictif")
    assert client_cmo.get("/marketing/cmo", params=_params(), follow_redirects=False).status_code == 403


def test_cmo_page_initiale_affiche_dates_vides_sans_lecture_m7(client_cmo, monkeypatch):
    _connecter(client_cmo)
    from opsys.console import metier as console_metier

    def refuser_toute_lecture(*_args, **_kwargs):
        pytest.fail("un affichage du formulaire vide ne doit appeler aucun outil métier")

    monkeypatch.setattr(console_metier, "executer", refuser_toute_lecture)
    response = client_cmo.get("/marketing/cmo")
    assert response.status_code == 200, response.text
    for field in ("date_depart", "debut", "fin"):
        assert f'name="{field}" required' in response.text
    assert 'name="date_depart" required value=""' in response.text
    assert response.headers["cache-control"] == "no-store"


def test_cmo_api_ne_devine_jamais_les_dates_absentes(client_cmo, monkeypatch):
    _connecter(client_cmo)
    from opsys.console import metier as console_metier

    def refuser_toute_lecture(*_args, **_kwargs):
        pytest.fail("les dates manquantes doivent être refusées avant lecture M7")

    monkeypatch.setattr(console_metier, "executer", refuser_toute_lecture)
    assert client_cmo.get("/api/marketing/cmo/plan").status_code == 400


def test_cmo_admin_actif_est_autorise_selon_la_politique_console_existante(client_cmo):
    _connecter(client_cmo, "admin.cmo.fictif")
    response = client_cmo.get("/api/marketing/cmo/plan", params=_params())
    assert response.status_code == 200, response.text


def test_cmo_role_revoque_apres_login_est_revalide(client_cmo):
    _connecter(client_cmo)
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, PROPRIETAIRE, "nathan_owner")
    assert client_cmo.get("/api/marketing/cmo/plan", params=_params()).status_code == 403


def test_cmo_compte_desactive_apres_login_est_revalide(client_cmo):
    _connecter(client_cmo)
    with stockage.transaction() as cnx:
        identite.activer(cnx, PROPRIETAIRE, False)
    assert client_cmo.get("/api/marketing/cmo/plan", params=_params()).status_code == 401


@pytest.mark.parametrize(
    "query",
    [
        {},
        {"date_depart": "2026-10-01", "debut": "2026-09-01"},
        {"date_depart": "2026-10-01", "debut": "2026-09-01", "fin": "2026-09-30", "role": "admin"},
        {"date_depart": "2026-02-30", "debut": "2026-09-01", "fin": "2026-09-30"},
        {"date_depart": "2026-10-01", "debut": "2026-09-31", "fin": "2026-09-30"},
        {"date_depart": "2026-10-01", "debut": "2026-10-01", "fin": "2026-09-30"},
        {"date_depart": "9999-12-31", "debut": "2026-09-01", "fin": "2026-09-30"},
    ],
)
def test_cmo_refuse_dates_absentes_invalides_overflow_ou_params_inconnus(client_cmo, query):
    _connecter(client_cmo)
    response = client_cmo.get("/api/marketing/cmo/plan", params=query)
    assert response.status_code == 400, response.text


def test_cmo_refuse_parametre_duplique(client_cmo):
    _connecter(client_cmo)
    response = client_cmo.get(
        "/api/marketing/cmo/plan?date_depart=2026-10-01&debut=2026-09-01&fin=2026-09-30&fin=2026-09-29"
    )
    assert response.status_code == 400, response.text



def _publier_faits_performance(deps, *, campagne: str, suffixe: str) -> None:
    from datetime import date

    jour = date.today().isoformat()
    lead_id, devis_id = f"lead-cmo-{suffixe}", f"devis-cmo-{suffixe}"
    chantier_id = f"chantier-cmo-{suffixe}"
    evenements.publier(
        "m2.client_associe", "m02-revenue-crm",
        {"lead_id": lead_id, "client_id": f"client-cmo-{suffixe}",
         "horodatage_association": f"{jour}T12:00:00Z",
         "utm": {"utm_source": "google", "utm_campaign": campagne}},
        evenement_id=f"m2-cmo-{suffixe}",
    )
    evenements.publier(
        "m3.devis_accepte", "m03-estimation",
        {"devis_id": devis_id, "lead_id": lead_id, "chantier_id": chantier_id,
         "lignes": [{"reference_ligne": f"{devis_id}-L0", "description": "Gouttières",
                     "quantite": "1", "unite": "forfait", "prix_unitaire": "2000.00",
                     "prix_ligne": "2000.00", "reference_besoin_materiau": None}],
         "cout_total": "1000.00", "prix_total": "2000.00", "taux_marge": "1.00",
         "horodatage_acceptation": f"{jour}T13:00:00Z"},
        evenement_id=f"m3-cmo-{suffixe}",
    )
    evenements.publier(
        "m5.rentabilite_chantier", "m05-financecore",
        {"evenement_id": f"m5-cmo-{suffixe}", "devis_id": devis_id, "chantier_id": chantier_id,
         "wct_id": f"wct-cmo-{suffixe}", "sequence": 1, "version_entrees": "b" * 64,
         "horodatage_completion": f"{jour}T14:00:00Z", "verdict": "CALCULEE", "devise": "CAD",
         "cout_reel_complet": True, "cout_reel_cad": "800.00", "cout_connu_cad": "800.00",
         "marge_reelle_cad": "1200.00", "marge_prevue_cad": "1000.00",
         "ecart_marge_cad": "200.00", "manque": []},
        evenement_id=f"m5-cmo-publie-{suffixe}",
    )
    livraisons = evenements.repartir(
        {"m07-marketing": deps["m07-marketing"]}, maintenant=f"{jour}T23:59:00+00:00"
    )
    assert livraisons["traites"] == 3 and livraisons["echecs"] == 0, livraisons
    assert livraisons["quarantaines"] == 0, livraisons


def test_cmo_projection_reutilise_bus_canonique_et_ne_change_aucun_registre(client_cmo, monkeypatch):
    csrf = _connecter(client_cmo)
    deps = charger_departements()
    _publier_faits_performance(deps, campagne="<script>alert(1)</script>", suffixe="cmo")
    jour = __import__("datetime").date.today().isoformat()
    periode = {"date_depart": "2026-10-01", "debut": jour, "fin": jour}
    from opsys.console import metier as console_metier

    appels = []
    execute_original = console_metier.executer

    def enregistrer_appel(*args, **kwargs):
        appels.append(args[3])
        return execute_original(*args, **kwargs)

    monkeypatch.setattr(console_metier, "executer", enregistrer_appel)
    avant = {
        nom: list(stockage.maillons("m07-marketing", nom))
        for nom in ("performance_campagnes", "brand_profiles", "calendrier_contenus", "plans_growth")
    }
    with stockage.transaction() as cnx:
        bus_avant = tuple(
            cnx.execute(select(func.count()).select_from(table)).scalar_one()
            for table in (EVENEMENTS_SORTANTS, EVENEMENTS_RECUS)
        )
    api = client_cmo.get("/api/marketing/cmo/plan", params=periode)
    page = client_cmo.get("/marketing/cmo", params=periode)
    appels_cmo = list(appels)
    accueil_marketing = client_cmo.get("/marketing")
    apres = {
        nom: list(stockage.maillons("m07-marketing", nom))
        for nom in ("performance_campagnes", "brand_profiles", "calendrier_contenus", "plans_growth")
    }
    with stockage.transaction() as cnx:
        bus_apres = tuple(
            cnx.execute(select(func.count()).select_from(table)).scalar_one()
            for table in (EVENEMENTS_SORTANTS, EVENEMENTS_RECUS)
        )

    assert api.status_code == 200, api.text
    assert page.status_code == 200, page.text
    assert accueil_marketing.status_code == 200, accueil_marketing.text
    assert "/marketing/cmo" in accueil_marketing.text
    lecture_attendue = [
        "m7_lire_profil_marque_courant", "m7_lister_calendrier", "m7_lire_performance_campagnes",
    ] * 2
    assert appels_cmo == lecture_attendue
    assert not {"m7_generer_plan_growth_30j", "m7_planifier_campagne_saisonniere"} & set(appels_cmo)
    plan = api.json()["resultat"]
    assert [w["id"] for w in plan["fenetres"]] == ["J1-30", "J31-60", "J61-90"]
    assert plan["date_depart"] == "2026-10-01"
    assert plan["performance"]["couverture"] == "PARTIELLE"
    assert plan["performance"]["campagnes"][0]["leads_associes_observes"] == 1
    assert plan["performance"]["campagnes"][0]["devis_acceptes"] == 1
    assert plan["performance"]["campagnes"][0]["marge_constatee_M5_cad"] == "1200.00"
    assert plan["performance"]["campagnes"][0]["cout_ads_cad"] is None
    assert plan["sources"]["performance"]["outil"] == "m7_lire_performance_campagnes"
    assert plan["manques"] and plan["actions"]
    assert all(action["statut"] == "a_arbitrer" for action in plan["actions"])
    assert all(action["date_arbitrage"] == next(
        fenetre["fin"] for fenetre in plan["fenetres"] if fenetre["id"] == action["fenetre"]
    ) for action in plan["actions"])
    assert plan["regle_date_arbitrage"]["date"] == "fin_fenetre"
    assert "1 200.00" in page.text or "1200.00" in page.text
    assert "ne constituent pas une prévision" in page.text
    assert "<script>alert(1)</script>" not in page.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page.text
    assert "date proposée pour arbitrage" in page.text
    assert "m7_lire_performance_campagnes" in page.text
    assert 'name="date_depart" required' in page.text
    assert csrf
    assert apres == avant
    assert bus_apres == bus_avant


def test_cmo_html_echappe_valeurs_et_api_est_no_store(client_cmo):
    _connecter(client_cmo)
    query = {"date_depart": "2026-10-01", "debut": "2026-09-01", "fin": "2026-09-30"}
    api = client_cmo.get("/api/marketing/cmo/plan", params=query)
    page = client_cmo.get("/marketing/cmo", params=query)
    assert api.status_code == 200, api.text
    assert api.headers["cache-control"] == "no-store"
    assert page.status_code == 200, page.text
    assert page.headers["cache-control"] == "no-store"
    assert "&lt;script&gt;" not in page.text


def test_cmo_absence_de_campagne_reste_inconnue_pas_zero(client_cmo):
    _connecter(client_cmo)
    response = client_cmo.get(
        "/api/marketing/cmo/plan",
        params={"date_depart": "2026-10-01", "debut": "2026-09-01", "fin": "2026-09-30"},
    )
    assert response.status_code == 200, response.text
    plan = response.json()["resultat"]
    assert plan["performance"]["couverture"] == "INCONNUE"
    assert plan["performance"]["campagnes"] == []
    assert plan["performance"]["couts_ads_cad"] is None
    assert plan["performance"]["roi"] is None


def test_projection_signale_les_listes_sources_bornees():
    from m7_marketing import plan_cmo

    slots = [{"creneau_id": f"slot-{i}", "planifie_le": "2026-10-01T12:00:00+00:00"} for i in range(101)]
    refs = [{"type": "m2.client_associe", "reference": f"lead-{i}"} for i in range(101)]
    campagnes = [{
        "source": "google", "campagne": "automne", "leads_associes_observes": 101,
        "devis_acceptes": 0, "chantiers_marge_constatee": 0, "marge_constatee_M5_cad": None,
        "statut_financier": "INCONNU", "couverture": "PARTIELLE", "manque": ["SOURCE_ABSENTE"],
        "source_refs": refs, "cout_ads_cad": None, "cout_par_lead_cad": None, "roi": None,
    }]
    plan = plan_cmo.projeter(
        date_depart="2026-10-01", debut="2026-09-01", fin="2026-09-30",
        profil_marque={"statut": "configure", "revision": 1},
        calendrier={"creneaux": slots},
        performance={"periode": {"debut": "2026-09-01", "fin": "2026-09-30"},
                     "couverture": "PARTIELLE", "campagnes": campagnes, "source_refs": refs,
                     "manque": ["SOURCE_ABSENTE"], "exclusions": {}},
    )
    assert plan["sources_tronquees"]["calendrier"] is True
    assert plan["sources_tronquees"]["references_performance"] is True
    assert plan["sources_tronquees"]["references_par_campagne"] is True
    assert plan["performance"]["source_refs_observees_total"] == 101
    assert len(plan["performance"]["source_refs"]) == 100
    assert plan["performance"]["campagnes"][0]["source_refs_tronquees"] is True
    assert plan["fenetres"][1]["calendrier"]["statut"] == "INDETERMINE_SOURCE_TRONQUEE"
    assert any(action["regle"] == "CALENDRIER_SOURCE_A_COMPLETER_V1" for action in plan["actions"])


def test_projection_refuse_manque_non_textuel_avec_erreur_metier_nommee():
    from m7_marketing import plan_cmo

    with pytest.raises(ValueError, match="SOURCE_PERFORMANCE_MANQUE_INVALIDE"):
        plan_cmo.projeter(
            date_depart="2026-10-01", debut="2026-09-01", fin="2026-09-30",
            profil_marque={"statut": "configure", "revision": 1},
            calendrier={"creneaux": []},
            performance={"periode": {"debut": "2026-09-01", "fin": "2026-09-30"},
                         "couverture": "PARTIELLE", "campagnes": [], "source_refs": [],
                         "manque": [{"code": "INVALID"}], "exclusions": {}},
        )


def test_projection_date_calendrier_absente_est_un_manque_pas_un_calendrier_vide():
    from m7_marketing import plan_cmo

    plan = plan_cmo.projeter(
        date_depart="2026-10-01", debut="2026-09-01", fin="2026-09-30",
        profil_marque={"statut": "configure", "revision": 1},
        calendrier={"creneaux": [{"creneau_id": "slot-sans-date"}]},
        performance={"periode": {"debut": "2026-09-01", "fin": "2026-09-30"},
                     "couverture": "INCONNUE", "campagnes": [], "source_refs": [],
                     "manque": ["DEPENSES_NON_BRANCHEES"], "exclusions": {}},
    )
    assert plan["fenetres"][0]["calendrier"]["statut"] == "INDETERMINE_DATE_ABSENTE"
    assert "CALENDRIER_DATE_ABSENTE" in plan["manques"]
    assert any(action["regle"] == "CALENDRIER_DATE_A_COMPLETER_V1" for action in plan["actions"])
    assert not any(action["regle"] == "CALENDRIER_A_REVOIR_V1" for action in plan["actions"])
