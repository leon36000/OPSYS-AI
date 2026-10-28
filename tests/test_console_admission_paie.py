"""Console documentaire : identités, données et SQLite strictement FICTIFS."""

import pytest
from fastapi.testclient import TestClient

from opsys import identite, stockage
from opsys.console import application, metier, securite
from opsys.departements import lire_manifeste

FICTIF = True
PASSWORD = "identite-QA-fictive-documentaire"
CONTEXTE = {"annee": 2026, "date_paie": "2026-10-23", "juridiction": "QC",
            "frequence": "bihebdomadaire", "periode_annuelle": 22, "pm": 12}
PAGE = "/finance/paie/admission"
API = "/api/finance/paie/admission"


@pytest.fixture
def client(tmp_path, monkeypatch):
    from pathlib import Path

    from m5_financecore import outils

    monkeypatch.setenv(stockage.ENV_URL, "sqlite:///" + str(tmp_path / "fictif.db"))
    stockage.migrer()
    outils.utiliser_stockage_durable()
    with stockage.transaction() as cnx:
        for name, roles in [("owner.fictif", ["nathan_owner", "admin"]),
                            ("admin.fictif", ["admin"]), ("employee.fictif", ["employee"])]:
            identite.creer_personne(cnx, name, "Identité fictive QA", PASSWORD, roles)
    dep = lire_manifeste(Path(outils.__file__).resolve().parents[2])
    config = securite.Configuration("secret-fictif-QA-documentaire-" + "x" * 32, cookie_securise=False)
    app = application.creer_application(config, {dep.id: dep}, stockage.transaction)
    with TestClient(app, base_url="http://testserver/opsys") as client:
        yield client
    stockage.liberer()


def login(client, name="owner.fictif"):
    response = client.post("/connexion", data={"identifiant": name, "mot_de_passe": PASSWORD},
                           follow_redirects=False)
    assert response.status_code == 303, response.text
    return client.get("/api/session").json()["csrf"]


def test_anonyme_refuse_page_et_api(client):
    assert client.get(PAGE, follow_redirects=False).status_code == 303
    assert client.post(API, json=CONTEXTE).status_code == 401


def test_owner_authentifie_diagnostic_reel_sans_mouvement_financier(client):
    csrf = login(client)
    page = client.get(PAGE)
    assert page.status_code == 200, page.text
    assert "Vérifier les préconditions documentaires" in page.text
    assert 'name="date_paie"' in page.text
    assert "no-store" in page.headers["cache-control"]
    assert "/finance/paie/admission" in client.get("/finance/paie").text
    avant = list(stockage.maillons("m05-financecore", "principal"))
    response = client.post(API, json=CONTEXTE, headers={"x-csrf-token": csrf})
    assert response.status_code == 200, response.text
    result = response.json()["resultat"]["resultat"]
    assert result["admissible"] is False
    assert result["qualification_regles"] == "NON_QUALIFIEE_POUR_PAIE"
    assert result["actions_financieres_bloquees"] is True
    assert result["autorisation_outil_ou_acteur"] is False
    assert len(result["motifs"]) == 4
    assert all("CAPTURE_INDISPONIBLE_OU_LIEE" in m for m in result["motifs"])
    assert list(stockage.maillons("m05-financecore", "principal")) == avant


def test_csrf_absent_ou_faux_refuse_avant_outil(client, monkeypatch):
    login(client)
    def interdit(*args, **kwargs):
        pytest.fail("outil exécuté avant CSRF")
    monkeypatch.setattr(metier, "executer", interdit)
    assert client.post(API, json=CONTEXTE).status_code == 403
    assert client.post(API, json=CONTEXTE, headers={"x-csrf-token": "faux"}).status_code == 403
    assert client.post(PAGE, data={**CONTEXTE, "csrf": "faux"}).status_code == 403


def test_admin_et_employee_sans_owner_refuses(client, monkeypatch):
    def interdit(*args, **kwargs):
        pytest.fail("outil exécuté pour une identité non propriétaire")
    monkeypatch.setattr(metier, "executer", interdit)
    for name in ("admin.fictif", "employee.fictif"):
        csrf = login(client, name)
        assert client.get(PAGE).status_code == 403
        assert client.post(API, json=CONTEXTE, headers={"x-csrf-token": csrf}).status_code == 403


def test_role_sql_revoque_malgre_cookie_signe(client, monkeypatch):
    csrf = login(client)
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, "owner.fictif", "nathan_owner")
    def interdit(*args, **kwargs):
        pytest.fail("outil exécuté après révocation SQL")
    monkeypatch.setattr(metier, "executer", interdit)
    assert client.get(PAGE).status_code == 403
    assert client.post(API, json=CONTEXTE, headers={"x-csrf-token": csrf}).status_code == 403


def test_chemin_hash_role_ou_bool_injectes_refuses(client, monkeypatch):
    csrf = login(client)
    def interdit(*args, **kwargs):
        pytest.fail("outil exécuté avec des arguments structurellement invalides")
    monkeypatch.setattr(metier, "executer", interdit)
    for name, value in [("chemin_configuration", "/tmp/fictif.json"), ("generation", "0" * 64),
                        ("role", "nathan_owner"), ("pm", True), ("annee", "2026")]:
        assert client.post(API, json={**CONTEXTE, name: value},
                           headers={"x-csrf-token": csrf}).status_code == 400


def test_formulaire_rend_refus_reel_et_echappe_sorties(client, monkeypatch):
    csrf = login(client)
    response = client.post(PAGE, data={**CONTEXTE, "csrf": csrf})
    assert response.status_code == 200, response.text
    assert "NON_QUALIFIEE_POUR_PAIE" in response.text
    assert "CAPTURE_INDISPONIBLE_OU_LIEE" in response.text
    assert "Actions financières bloquées" in response.text
    original = metier.executer
    def annoter(*args, **kwargs):
        reponse = original(*args, **kwargs)
        reponse["resultat"]["resultat"]["motifs"] = ["<script>fictif</script>"]
        return reponse
    monkeypatch.setattr(metier, "executer", annoter)
    response = client.post(PAGE, data={**CONTEXTE, "csrf": csrf})
    assert "&lt;script&gt;fictif&lt;/script&gt;" in response.text
    assert "<script>fictif</script>" not in response.text


def test_cookie_altere_refuse_avant_diagnostic(client, monkeypatch):
    csrf = login(client)
    cookie = client.cookies.get(securite.NOM_COOKIE)
    client.cookies.clear()
    client.cookies.set(securite.NOM_COOKIE, cookie + "faux", domain="testserver.local", path="/opsys")
    def interdit(*args, **kwargs):
        pytest.fail("outil exécuté avec une signature invalide")
    monkeypatch.setattr(metier, "executer", interdit)
    assert client.post(API, json=CONTEXTE, headers={"x-csrf-token": csrf}).status_code == 401
