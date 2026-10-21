"""Parcours HTTP M7 Brand Core sur l'application console et les registres réels."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from opsys import approbations, identite, stockage
from opsys.console import application
from opsys.console.securite import Configuration
from opsys.stockage.schema import APPROBATIONS

SECRET = "secret-console-brand-fictif-2026-" + "b" * 32
PREFIXE = "/opsys"
MOT_DE_PASSE = "mot-de-passe-console-brand-fictif-1234"


@pytest.fixture
def client_brand(session):
    with session() as cnx:
        identite.creer_personne(cnx, "nathan", "Nathan fictif", MOT_DE_PASSE, ["nathan_owner"])
        identite.creer_personne(cnx, "admin", "Administratrice fictive", MOT_DE_PASSE, ["admin"])
        identite.creer_personne(cnx, "lecteur", "Lectrice fictive", MOT_DE_PASSE, ["employee"])

    app = application.creer_application(Configuration(SECRET, cookie_securise=False, prefixe=PREFIXE), None, session)

    with TestClient(app, base_url=f"https://testserver{PREFIXE}") as client:
        yield client


def _connecter(client: TestClient, utilisateur="nathan") -> str:
    connexion = client.post(
        "/connexion",
        data={"identifiant": utilisateur, "mot_de_passe": MOT_DE_PASSE},
        follow_redirects=False,
    )
    assert connexion.status_code == 303, connexion.text
    return client.get("/api/session").json()["csrf"]


def _profil(**remplacements):
    return {
        "name": "Entreprise Démo",
        "tagline": "Travaux extérieurs avec soin",
        "tone": "professionnel et factuel",
        "colors": ["#123456", "#abcdef"],
        "langue": "fr-CA",
        **remplacements,
    }


def _maillons():
    with stockage.transaction():
        return list(stockage.maillons("m07-marketing", "brand_profiles"))


def _nombre_approbations(session):
    with session() as cnx:
        return cnx.execute(select(func.count()).select_from(APPROBATIONS)).scalar_one()


def test_page_affiche_etat_a_configurer_et_contrat_sans_promesse_de_verification(client_brand):
    client = client_brand
    _connecter(client)
    marketing = client.get("/marketing")
    assert marketing.status_code == 200 and "/marketing/marque" in marketing.text
    response = client.get("/marketing/marque")
    assert response.status_code == 200, response.text
    assert "À configurer" in response.text
    assert "name" in response.text and "tagline" in response.text and "colors" in response.text
    assert "champs requis et leur type" in response.text.casefold()
    assert _maillons() == []


def test_configuration_proprietaire_persiste_et_provenance_est_visible_apres_nouvelle_instance(client_brand, session):
    client = client_brand
    csrf = _connecter(client)
    form = client.get("/marketing/marque")
    assert form.status_code == 200
    response = client.post(
        "/marketing/marque",
        data={
            "csrf": csrf,
            "mutation_id": "brand-console-create-1",
            "name": "Entreprise Démo",
            "tagline": "<script>alert(1)</script>",
            "tone": "professionnel et factuel",
            "colors": "#123456\n#abcdef",
            "langue": "fr-CA",
        },
        follow_redirects=False,
    )
    assert response.status_code in {200, 303}, response.text
    assert len(_maillons()) == 1
    assert _maillons()[0]["revision"] == 1
    assert _maillons()[0]["configure_par"] == "nathan"

    # Une seconde application / connexion relit le registre durable, sans fixture de profil.
    app = application.creer_application(Configuration(SECRET, cookie_securise=False, prefixe=PREFIXE), None, session)
    with TestClient(app, base_url=f"https://testserver{PREFIXE}") as reopened:
        _connecter(reopened)
        page = reopened.get("/marketing/marque")
        assert page.status_code == 200
        assert "Entreprise Démo" in page.text
        assert "révision 1" in page.text
        assert "Nathan fictif" in page.text or "nathan" in page.text
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page.text
        assert "<script>alert(1)</script>" not in page.text
        _connecter(reopened, "admin")
        page_admin = reopened.get("/marketing/marque")
        assert "Entreprise Démo" in page_admin.text
        assert "Enregistrer une révision" not in page_admin.text


def test_champs_forges_csrf_absent_et_admin_sans_droit_proprietaire_ne_creent_aucune_revision(client_brand, session):
    client = client_brand
    csrf = _connecter(client, "admin")
    page_admin = client.get("/marketing/marque")
    assert page_admin.status_code == 200
    assert "Enregistrer une révision" not in page_admin.text
    assert "Entreprise Démo" not in page_admin.text
    approvals_avant = _nombre_approbations(session)
    forged = client.post(
        "/api/marketing/marque",
        json={"profil": _profil(), "mutation_id": "brand-forged", "acteur": "nathan", "role": "nathan_owner"},
        headers={"x-csrf-token": csrf},
    )
    assert forged.status_code == 403, forged.text
    no_csrf = client.post("/api/marketing/marque", json={"profil": _profil(), "mutation_id": "brand-no-csrf"})
    assert no_csrf.status_code == 403, no_csrf.text
    admin = client.post(
        "/api/marketing/marque",
        json={"profil": _profil(), "mutation_id": "brand-admin"},
        headers={"x-csrf-token": csrf},
    )
    assert admin.status_code == 403, admin.text
    assert _nombre_approbations(session) == approvals_avant
    assert _maillons() == []

    query_admin = client.post(
        "/api/marketing/marque?acteur=nathan",
        json={"profil": _profil(), "mutation_id": "brand-admin-query"},
        headers={"x-csrf-token": csrf},
    )
    assert query_admin.status_code == 403, query_admin.text
    assert _nombre_approbations(session) == approvals_avant
    malformed = client.post(
        "/api/marketing/marque",
        content=b"not-json",
        headers={"x-csrf-token": csrf, "content-type": "application/json"},
    )
    assert malformed.status_code == 403, malformed.text
    assert _nombre_approbations(session) == approvals_avant


def test_retrait_role_apres_page_refuse_mutation_et_texte_est_escape(client_brand, session):
    client = client_brand
    csrf = _connecter(client)
    page = client.get("/marketing/marque")
    assert page.status_code == 200
    approvals_avant = _nombre_approbations(session)
    with session() as cnx:
        identite.retirer_role(cnx, "nathan", "nathan_owner")
    mutation = client.post(
        "/marketing/marque",
        data={
            "csrf": csrf,
            "mutation_id": "brand-revoked-role",
            "name": "<script>alert(1)</script>",
            "tagline": "x",
            "tone": "x",
            "colors": "#123456",
            "langue": "fr",
        },
        follow_redirects=False,
    )
    assert mutation.status_code == 403
    api = client.post(
        "/api/marketing/marque",
        json={"profil": _profil(), "mutation_id": "brand-revoked-api"},
        headers={"x-csrf-token": csrf},
    )
    assert api.status_code == 403, api.text
    assert _nombre_approbations(session) == approvals_avant
    assert _maillons() == []
    assert "<script>alert(1)</script>" not in mutation.text


def test_api_lecture_retourne_courant_sans_historique_ni_ecriture(client_brand):
    client = client_brand
    _connecter(client)
    response = client.get("/api/marketing/marque")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["resultat"]["statut"] == "a_configurer"
    assert _maillons() == []


def test_lecture_refuse_personne_sans_role_admin_ou_proprietaire(client_brand):
    client = client_brand
    _connecter(client, "lecteur")
    response = client.get("/marketing/marque", follow_redirects=False)
    assert response.status_code == 403, response.text
    assert _maillons() == []


def test_anonyme_est_redirige_par_html_et_api_refuse_sans_session(client_brand):
    client = client_brand
    page = client.get("/marketing/marque", follow_redirects=False)
    assert page.status_code == 303
    assert page.headers["location"].endswith("/opsys/connexion")
    api = client.get("/api/marketing/marque")
    assert api.status_code == 401, api.text
    assert _maillons() == []


def test_query_inattendue_sur_post_owner_refuse_sans_approbation(client_brand, session):
    client = client_brand
    csrf = _connecter(client)
    approvals_avant = _nombre_approbations(session)
    response = client.post(
        "/api/marketing/marque?role=admin",
        json={"profil": _profil(), "mutation_id": "brand-extra-query"},
        headers={"x-csrf-token": csrf},
    )
    assert response.status_code == 400, response.text
    assert _nombre_approbations(session) == approvals_avant
    assert _maillons() == []

    extra_actor = client.post(
        "/api/marketing/marque",
        json={"profil": _profil(), "mutation_id": "brand-forged-owner", "acteur": "admin", "role": "admin"},
        headers={"x-csrf-token": csrf},
    )
    assert extra_actor.status_code == 400, extra_actor.text
    assert _nombre_approbations(session) == approvals_avant

    form_query = client.post(
        "/marketing/marque?role=admin",
        content=b"not-a-form",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert form_query.status_code == 400, form_query.text
    assert _nombre_approbations(session) == approvals_avant


def test_role_owner_revoque_pendant_parse_json_refuse_avant_approbation(session, monkeypatch):
    with session() as cnx:
        identite.creer_personne(
            cnx, "owner_admin", "Propriétaire administrateur fictif", MOT_DE_PASSE, ["admin", "nathan_owner"]
        )
    parser_json = application._objet_json
    approbations_creees = []
    creer_demande = approbations.creer_demande

    def observer_creer_demande(*args, **kwargs):
        approbations_creees.append((args, kwargs))
        return creer_demande(*args, **kwargs)

    monkeypatch.setattr(approbations, "creer_demande", observer_creer_demande)

    async def parser_puis_retirer_owner(request):
        corps = await parser_json(request)
        with session() as cnx:
            identite.retirer_role(cnx, "owner_admin", "nathan_owner")
        return corps

    monkeypatch.setattr(application, "_objet_json", parser_puis_retirer_owner)
    app = application.creer_application(Configuration(SECRET, cookie_securise=False, prefixe=PREFIXE), None, session)
    approvals_avant = _nombre_approbations(session)
    with TestClient(app, base_url=f"https://testserver{PREFIXE}") as client:
        csrf = _connecter(client, "owner_admin")
        response = client.post(
            "/api/marketing/marque",
            json={"profil": _profil(), "mutation_id": "brand-race-revoke-owner"},
            headers={"x-csrf-token": csrf},
        )
    assert response.status_code == 403, response.text
    with session() as cnx:
        personne = identite.personne_active(cnx, "owner_admin")
    assert personne is not None and personne.roles == {"admin"}
    assert approbations_creees == []
    assert _nombre_approbations(session) == approvals_avant
    assert _maillons() == []


def test_api_proprietaire_suit_contrat_et_rejeu_idempotent_ne_cree_pas_deuxieme_revision(client_brand):
    client = client_brand
    csrf = _connecter(client)
    payload = {"profil": _profil(), "mutation_id": "brand-api-idempotent-1"}
    premier = client.post("/api/marketing/marque", json=payload, headers={"x-csrf-token": csrf})
    assert premier.status_code == 200, premier.text
    assert premier.json()["ok"] is True
    rejoue = client.post("/api/marketing/marque", json=payload, headers={"x-csrf-token": csrf})
    assert rejoue.status_code == 200, rejoue.text
    assert len(_maillons()) == 1
    conflit = client.post(
        "/api/marketing/marque",
        json={"profil": _profil(tagline="Autre signature"), "mutation_id": "brand-api-idempotent-1"},
        headers={"x-csrf-token": csrf},
    )
    assert conflit.status_code in {400, 409}, conflit.text
    assert len(_maillons()) == 1
