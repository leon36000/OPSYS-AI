"""Centre privé : personnes, profils et paliers fictifs, SQLite réellement migrée."""

from __future__ import annotations

import dataclasses
import socket

import pytest
from fastapi.testclient import TestClient

from opsys import agents, identite
from opsys.console import application, configuration_lecture, connecteurs_ui
from opsys.console.connecteurs_ui import JSONResponse
from opsys.console.securite import Configuration
from opsys.departements import charger_departements

_PASSWORD = "mot-de-passe-centre-fictif-2026"


@pytest.fixture(autouse=True)
def _base_isolee(monkeypatch, opsys_home):
    monkeypatch.delenv("OPSYS_BASE_URL", raising=False)


@pytest.fixture
def centre(session, tmp_path):
    with session() as cnx:
        identite.creer_personne(cnx, "centre_fictif", "Owner fictif", _PASSWORD, ["nathan_owner"])
    paliers = tmp_path / "paliers-fictifs.yaml"
    paliers.write_text("paliers:\n  standard:\n    provider: openai\n    model: modele-fictif\n", encoding="utf-8")
    app = application.creer_application(
        Configuration("secret-session-centre-fictif-" + "x" * 32),
        charger_departements(), session, chemin_paliers=paliers,
    )
    with TestClient(app, base_url="https://testserver/opsys") as client:
        response = client.post(
            "/connexion", data={"identifiant": "centre_fictif", "mot_de_passe": _PASSWORD},
            follow_redirects=False,
        )
        assert response.status_code == 303
        yield client, paliers


def test_centre_rassemble_les_dix_departements_et_paliers_existants(centre):
    client, _ = centre
    response = client.get("/api/connecteurs")
    assert response.status_code == 200
    projection = response.json()["resultat"]["configuration_dashboard"]
    assert {d["code"] for d in projection["departements"]} == {f"M{i}" for i in range(1, 11)}
    assert len(projection["paliers"]) == 4
    assert projection["verification_runtime"] == "non_observee"
    page = client.get("/connecteurs")
    assert page.status_code == 200
    assert "Spécialistes et connexions par département" in page.text
    assert '/opsys/departements#m03-estimation' in page.text
    assert '/opsys/modeles#palier-standard' in page.text
    assert "Déclencheurs déclarés, non raccordés" in page.text


def test_palier_declare_avec_cle_absente_ne_devient_pas_connecte(centre, monkeypatch):
    client, _ = centre
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    response = client.get("/api/connecteurs")
    assert response.status_code == 200
    paliers = response.json()["resultat"]["configuration_dashboard"]["paliers"]
    standard = next(p for p in paliers if p["nom"] == "standard")
    assert standard["statut"] == "references_manquantes"
    assert standard["references_absentes"] == ["OPENAI_API_KEY"]
    assert standard["authentification_distante"] == "non_verifiee"


def test_profils_actifs_et_plafonds_viennent_du_canon_sans_claim_execution(centre, session):
    client, _ = centre
    deps = charger_departements()
    with session() as cnx:
        agents.creer(cnx, deps, {
            "id": "mesure-fictive", "departement": "m03-estimation",
            "responsabilite": "texte-libre-prive-fictif", "palier_modele": "standard", "outils": [],
            "budget_jour": 1000, "budget_mois": 20000,
            "limite_tours": 8, "limite_reessais": 2, "limite_concurrence": 1,
            "declencheurs": [{"type": "manuel"}],
        }, par="centre_fictif", mutation_id="profil-centre-fictif")
        agents.definir_actif(cnx, "mesure-fictive", deps, True, par="centre_fictif",
                             mutation_id="activation-centre-fictif", revision_attendue=1)
    response = client.get("/api/connecteurs")
    assert response.status_code == 200
    projection = response.json()["resultat"]["configuration_dashboard"]
    profil = projection["profils"]["items"][0]
    assert profil["actif"] is True and profil["revision"] == 2
    assert profil["budget_jour"] == 1000 and profil["budget_mois"] == 20000
    assert profil["runtime"] == "non_observe"
    assert profil["declencheurs"] == "declares_non_raccordes"
    assert projection["plafonds_specialistes"] is None
    m3 = next(d for d in projection["departements"] if d["code"] == "M3")
    assert m3["specialistes"] == {"total": 1, "actifs": 1, "inactifs": 0}
    assert "texte-libre-prive-fictif" not in response.text
    assert '/opsys/agents/mesure-fictive' in client.get("/connecteurs").text


@pytest.mark.parametrize("chemin", ["/connecteurs", "/api/connecteurs"])
def test_get_sans_reseau_sans_ecriture_et_sans_valeurs_secretes(centre, session, monkeypatch, chemin):
    client, paliers = centre
    paliers.write_text("""paliers:
  standard:
    provider: custom
    model: modele-prive-sentinelle
    base_url: https://serveur-prive-fictif.invalid/v1
    api_key_env: FICTIF_API_KEY
""", encoding="utf-8")
    monkeypatch.setenv("FICTIF_API_KEY", "cle-privee-sentinelle")
    monkeypatch.setenv("OPSYS_DATABASE_URL", "postgresql://secret:sentinelle@prive.invalid/db")

    def reseau_interdit(*_args, **_kwargs):
        pytest.fail("un GET du centre ne doit lancer aucun réseau")

    monkeypatch.setattr(socket, "create_connection", reseau_interdit)
    with session() as cnx:
        avant = tuple(cnx.connection.driver_connection.iterdump())
    response = client.get(chemin)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert all(s not in response.text for s in (
        "modele-prive-sentinelle", "serveur-prive-fictif", "cle-privee-sentinelle", "secret:sentinelle",
    ))
    assert "FICTIF_API_KEY" in response.text
    with session() as cnx:
        assert tuple(cnx.connection.driver_connection.iterdump()) == avant


@pytest.mark.parametrize("chemin", ["/connecteurs", "/api/connecteurs"])
@pytest.mark.parametrize("retrait", ["role", "compte"])
def test_retrait_pendant_lecture_refuse_projection(centre, session, monkeypatch, chemin, retrait):
    client, _ = centre
    original = configuration_lecture.lire

    def lire_et_retirer(*args, **kwargs):
        projection = original(*args, **kwargs)
        with session() as cnx:
            if retrait == "role":
                identite.retirer_role(cnx, "centre_fictif", "nathan_owner")
            else:
                identite.activer(cnx, "centre_fictif", False)
        return projection

    monkeypatch.setattr(configuration_lecture, "lire", lire_et_retirer)
    response = client.get(chemin, follow_redirects=False)
    assert response.status_code == (403 if retrait == "role" else 401)
    assert response.headers["cache-control"] == "no-store"
    assert "configuration_dashboard" not in response.text and "m03-estimation" not in response.text


@pytest.mark.parametrize("chemin", ["/connecteurs", "/api/connecteurs"])
def test_retrait_pendant_rendu_refuse_toute_reponse_privee(centre, session, monkeypatch, chemin):
    client, _ = centre

    def retirer():
        with session() as cnx:
            identite.retirer_role(cnx, "centre_fictif", "nathan_owner")

    if chemin == "/connecteurs":
        original = connecteurs_ui.configuration_contenu

        def rendre(projection, prefixe):
            html = original(projection, prefixe)
            retirer()
            return html

        monkeypatch.setattr(connecteurs_ui, "configuration_contenu", rendre)
    else:
        original = JSONResponse.render

        def rendre(self, content):
            body = original(self, content)
            if isinstance(content, dict) and "configuration_dashboard" in content.get("resultat", {}):
                retirer()
            return body

        monkeypatch.setattr(JSONResponse, "render", rendre)
    response = client.get(chemin)
    assert response.status_code == 403
    assert "m03-estimation" not in response.text and "configuration_dashboard" not in response.text


@pytest.mark.parametrize("chemin", ["/connecteurs", "/api/connecteurs"])
def test_role_retire_avant_get_ne_lit_pas_les_paliers(centre, session, monkeypatch, chemin):
    client, _ = centre
    with session() as cnx:
        identite.retirer_role(cnx, "centre_fictif", "nathan_owner")

    def lire_interdit(*_args, **_kwargs):
        pytest.fail("un acteur sans droits ne doit pas lire la configuration")

    monkeypatch.setattr(configuration_lecture, "lire", lire_interdit)
    assert client.get(chemin).status_code == 403


@pytest.mark.parametrize("chemin", ["/connecteurs", "/api/connecteurs"])
@pytest.mark.parametrize("corruption,code", [
    ("paliers: {}\npaliers: {}\n", "paliers_schema_invalide"),
    ("é" * 32769, "paliers_trop_volumineux"),
])
def test_paliers_invalides_diagnostic_ferme_sans_contenu(centre, chemin, corruption, code):
    client, paliers = centre
    paliers.write_text(corruption, encoding="utf-8")
    response = client.get(chemin)
    assert response.status_code == (413 if code == "paliers_trop_volumineux" else 409)
    assert response.json()["detail"] == code
    assert str(paliers) not in response.text
    assert response.headers["cache-control"] == "no-store"


def test_nom_departement_echappe_en_html(centre, monkeypatch):
    client, _ = centre
    original = configuration_lecture.lire

    def lire_nom_fictif(cnx, deps, *args):
        copies = dict(deps)
        copies["m03-estimation"] = dataclasses.replace(
            deps["m03-estimation"], nom='<script>sentinelle-fictive</script>',
        )
        return original(cnx, copies, *args)

    monkeypatch.setattr(configuration_lecture, "lire", lire_nom_fictif)
    page = client.get("/connecteurs")
    assert page.status_code == 200
    assert '<script>sentinelle-fictive</script>' not in page.text
    assert '&lt;script&gt;sentinelle-fictive&lt;/script&gt;' in page.text


def test_reponse_html_limitee_en_octets_apres_rendu(centre, monkeypatch):
    client, _ = centre
    monkeypatch.setattr(connecteurs_ui, "configuration_contenu", lambda *_args: "é" * 32769)
    response = client.get("/connecteurs")
    assert response.status_code == 413
    assert response.json()["detail"] == "configuration_sortie_trop_volumineuse"
