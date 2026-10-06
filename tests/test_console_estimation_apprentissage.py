"""Console M3 : HTTP, identité et SQLite réels; publications/reçus fictifs."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from opsys import contexte, identite, stockage
from opsys.console import application, pages
from opsys.console.securite import Configuration
from opsys.departements import lire_manifeste
from opsys.stockage.schema import EVENEMENTS_SORTANTS, REGISTRES

FICTIF = True
PASSWORD = "mot-de-passe-console-m3-fictif"
SECRET = "secret-console-m3-fictif-" + "x" * 32
PAGE = "/estimation/apprentissage/couverture"
API = "/api" + PAGE


@pytest.fixture
def clients(departements_demo, session):
    with session() as cnx:
        for role in ("admin", "nathan_owner", "employee", "seller"):
            identite.creer_personne(cnx, role, "Personne fictive", PASSWORD, [role])
    racine = Path(__file__).resolve().parents[1]
    m3 = lire_manifeste(racine / "departments/m03-estimation")
    deps = {**departements_demo, m3.id: m3}

    @contextmanager
    def client(role="admin", *, departements=None, factory=None):
        app = application.creer_application(
            Configuration(SECRET), deps if departements is None else departements,
            session if factory is None else factory,
        )
        with TestClient(app, base_url="https://testserver/opsys") as navigateur:
            if role:
                connexion = navigateur.post("/connexion", data={
                    "identifiant": role, "mot_de_passe": PASSWORD,
                }, follow_redirects=False)
                assert connexion.status_code == 303
            yield navigateur

    return client, deps


def _publier(*ids, producteur="m04-field-ops"):
    with stockage.transaction() as cnx:
        cnx.execute(EVENEMENTS_SORTANTS.insert(), [{
            "evenement_id": i, "type_evenement": "m4.travaux_termines", "producteur": producteur,
            "charge": "CONTENU-CHANTIER-FICTIF-PRIVE", "cree_le": "2026-10-01T12:00:00Z",
        } for i in ids])


def _recevoir(*ids):
    with stockage.transaction():
        journal = stockage.maillons("m03-estimation", "estime_vs_reel")
        for ident in ids:
            journal.append({
                "type_entree": "wct_recu", "wct_id": ident, "devis_id": "DEVIS-FICTIF",
                "lead_id": "LEAD-FICTIF", "intervention_id": "INTERVENTION-FICTIVE",
                "horodatage_completion": "2026-10-01T12:00:00Z", "main_doeuvre": {},
                "materiaux": None, "horodatage": "2026-10-01T12:00:00Z",
            })


def _snapshot():
    with stockage.transaction() as cnx:
        return [list(cnx.execute(select(table))) for table in (EVENEMENTS_SORTANTS, REGISTRES)]


@pytest.mark.parametrize("role", ["admin", "nathan_owner"])
def test_html_et_api_jointes_sans_identite_appareil_ni_mutation(clients, role, monkeypatch):
    def identite_fabriquee_interdite(*args, **kwargs):
        raise AssertionError("la console ne doit pas fabriquer une identité d’appareil")

    monkeypatch.setattr(contexte, "appele_par_appareil", identite_fabriquee_interdite)
    _publier("WCT-FICTIF-A", "WCT-FICTIF-B")
    _recevoir("WCT-FICTIF-A", "WCT-FICTIF-HISTORIQUE")
    avant = _snapshot()
    with clients[0](role) as client:
        html = client.get(PAGE)
        assert html.status_code == 200
        assert "WCT-FICTIF-B" in html.text and "WCT-FICTIF-HISTORIQUE" in html.text
        assert "non prouvée" in html.text and "Aucun barème activé" in html.text
        assert API in html.text
        rapport = client.get(API)
        assert rapport.status_code == 200
        assert rapport.json()["compteurs"] == {
            "publications_m4": 2, "recus_m3": 2, "recoupes": 1,
            "manquants_m3": 1, "hors_univers_m4": 1,
        }
        assert rapport.json()["candidate_active"] is False
        assert rapport.json()["contenu_wct_verifie"] is False
        for response in (html, rapport):
            assert response.headers["cache-control"] == "no-store"
            assert response.headers["x-content-type-options"] == "nosniff"
            assert "CONTENU-CHANTIER-FICTIF-PRIVE" not in response.text
            assert "LEAD-FICTIF" not in response.text
        assert "estimation/apprentissage/couverture" in client.get("/connecteurs").text
    assert avant == _snapshot()
    assert contexte.identite_appelante() is None


def test_univers_vide_ne_devient_pas_calibration_reussie(clients):
    with clients[0]() as client:
        rapport = client.get(API)
        assert rapport.status_code == 200
        assert rapport.json()["statut"] == "univers_vide"
        assert rapport.json()["completude_corpus_m4"] == "non_prouvee"
        assert "Aucune publication" in client.get(PAGE).text


@pytest.mark.parametrize("role,html_statut,api_statut", [
    (None, 303, 401), ("employee", 403, 403), ("seller", 403, 403),
])
def test_acces_refuse_avant_lecture_sources(clients, monkeypatch, role, html_statut, api_statut):
    from opsys.evenements import inventaire_calibration

    def interdit():
        raise AssertionError("lecture de données avant authentification")

    monkeypatch.setattr(inventaire_calibration, "lire_publications_m4", interdit)
    monkeypatch.setattr(inventaire_calibration, "lire_receptions_m3", interdit)
    with clients[0](role) as client:
        assert client.get(PAGE, follow_redirects=False).status_code == html_statut
        assert client.get(API).status_code == api_statut


@pytest.mark.parametrize("route", [PAGE, API])
def test_cookie_ancien_ne_conserve_pas_role_admin(clients, session, route):
    _publier("WCT-FICTIF-CONFIDENTIEL")
    with clients[0]() as client:
        with session() as cnx:
            identite.retirer_role(cnx, "admin", "admin")
        reponse = client.get(route)
        assert reponse.status_code == 403
        assert "WCT-FICTIF-CONFIDENTIEL" not in reponse.text


@pytest.mark.parametrize("route", [PAGE, API])
def test_role_retire_apres_lecture_refuse_tout_resultat(clients, session, monkeypatch, route):
    from m3_estimation import couverture_apprentissage

    original = couverture_apprentissage.auditer

    def lire_puis_revoquer(**kwargs):
        resultat = original(**kwargs)
        with session() as cnx:
            identite.retirer_role(cnx, "admin", "admin")
        return resultat

    monkeypatch.setattr(couverture_apprentissage, "auditer", lire_puis_revoquer)
    _publier("WCT-FICTIF-CONFIDENTIEL")
    with clients[0]() as client:
        reponse = client.get(route)
        assert reponse.status_code == 403
        assert "WCT-FICTIF-CONFIDENTIEL" not in reponse.text


def test_revalidation_apres_rendu_html(clients, session, monkeypatch):
    original = pages.gabarit

    def rendre_puis_revoquer(*args, **kwargs):
        resultat = original(*args, **kwargs)
        with session() as cnx:
            identite.retirer_role(cnx, "admin", "admin")
        return resultat

    with clients[0]() as client:
        monkeypatch.setattr(pages, "gabarit", rendre_puis_revoquer)
        assert client.get(PAGE).status_code == 403


def test_departement_absent_refuse_sans_lecture(clients, monkeypatch):
    from opsys.evenements import inventaire_calibration

    def interdit():
        raise AssertionError("aucune lecture si M3 absent")

    monkeypatch.setattr(inventaire_calibration, "lire_receptions_m3", interdit)
    sans_m3 = {k: v for k, v in clients[1].items() if k != "m03-estimation"}
    with clients[0](departements=sans_m3) as client:
        assert client.get(API).status_code == 503


def test_factory_non_canonique_refuse_autre_base(clients):
    @contextmanager
    def connexion_sans_contexte():
        with stockage.moteur().begin() as cnx:
            yield cnx

    with clients[0](factory=connexion_sans_contexte) as client:
        reponse = client.get(API)
        assert reponse.status_code == 503
        assert reponse.json()["detail"] == "connexion_canonique_requise"


@pytest.mark.parametrize("producteur,ident", [
    ("m04-field-ops", "<script>FICTIF</script>"), ("imposteur-fictif", "WCT-FICTIF-A"),
])
def test_source_invalide_409_sans_reflection_ni_compteur(clients, producteur, ident):
    _publier(ident, producteur=producteur)
    with clients[0]() as client:
        response = client.get(API)
        assert response.status_code == 409
        assert "compteurs" not in response.text and ident not in response.text


def test_schema_source_absent_ne_migre_pas(clients):
    with stockage.transaction() as cnx:
        cnx.exec_driver_sql("DROP TABLE evenements_sortants")
    with clients[0]() as client:
        response = client.get(API)
        assert response.status_code == 503
        assert response.json()["detail"] == "sources_lecture_indisponibles"
    with stockage.transaction() as cnx:
        assert cnx.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='evenements_sortants'"
        ).fetchall() == []


def test_exemples_bornes_et_aucun_parametre_de_filtrage(clients):
    _publier(*(f"WCT-FICTIF-{i:02d}" for i in range(12)))
    with clients[0]() as client:
        rapport = client.get(API).json()
        assert len(rapport["manquants_m3"]["exemples"]) == 10
        assert rapport["manquants_m3"]["omis"] == 2
        assert client.get(API, params={"wct_id": "WCT-FICTIF-00"}).status_code == 400
        assert client.post(API, json={}).status_code == 405


def test_outil_appareil_reste_refuse_dans_console(clients):
    from m3_estimation import outils

    with clients[0]() as client:
        assert client.get(API).status_code == 200
    with stockage.transaction():
        assert outils.auditer_couverture_apprentissage() == {
            "statut": "refuse", "raison": "identite_admin_authentifiee_requise", "candidate_active": False,
        }


def test_role_retire_apres_serialisation_json(clients, session, monkeypatch):
    from opsys.console import estimation_apprentissage_ui as ui

    original = ui.JSONResponse

    def serialiser_puis_revoquer(*args, **kwargs):
        resultat = original(*args, **kwargs)
        with session() as cnx:
            identite.retirer_role(cnx, "admin", "admin")
        return resultat

    _publier("WCT-FICTIF-CONFIDENTIEL")
    with clients[0]() as client:
        monkeypatch.setattr(ui, "JSONResponse", serialiser_puis_revoquer)
        reponse = client.get(API)
        assert reponse.status_code == 403
        assert "WCT-FICTIF-CONFIDENTIEL" not in reponse.text


@pytest.mark.parametrize("route", [PAGE, API])
def test_plafond_reponse_refuse_sans_troncature(clients, monkeypatch, route):
    from opsys.console import estimation_apprentissage_ui as ui

    monkeypatch.setattr(ui, "MAX_REPONSE_OCTETS", 16)
    with clients[0]() as client:
        response = client.get(route)
        assert response.status_code == 413
        assert "compteurs" not in response.text


def test_backend_non_qualifie_refuse_503(clients, monkeypatch):
    from opsys.evenements import inventaire_calibration as inventaire

    def backend_refuse():
        raise inventaire.InventaireRefuse("backend_source_non_qualifie")

    monkeypatch.setattr(inventaire, "lire_receptions_m3", backend_refuse)
    with clients[0]() as client:
        response = client.get(API)
        assert response.status_code == 503
        assert response.json() == {"detail": "backend_source_non_qualifie"}


@pytest.mark.parametrize("catalogue_invalide", [False, True])
def test_catalogue_m3_refuse_avant_sources(clients, monkeypatch, catalogue_invalide):
    from m3_estimation import outils

    from opsys.evenements import inventaire_calibration

    original = outils.outils

    def catalogue():
        return (object(),) if catalogue_invalide else tuple(
            o for o in original() if o.nom != "m3_auditer_couverture_apprentissage"
        )

    def interdit():
        raise AssertionError("lecture de sources sur catalogue refusé")

    with clients[0]() as client:
        monkeypatch.setattr(outils, "outils", catalogue)
        monkeypatch.setattr(inventaire_calibration, "lire_receptions_m3", interdit)
        response = client.get(API)
        assert response.status_code == 503
        assert response.json() == {"detail": "catalogue M3 indisponible"}
