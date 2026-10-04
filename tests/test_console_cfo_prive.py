"""CFO humain : snapshot privé chiffré, sans fuite API ni agrégation financière."""

import json

import pytest
from fastapi.testclient import TestClient

from opsys import identite
from opsys.console import application, obligations_privees
from opsys.console.paie_das_privees_cfo import SnapshotPriveInvalide, composer
from opsys.console.securite import Configuration

FICTIF = True
SECRET = "secret-console-cfo-prive-fictif-" + "x" * 32
PREFIXE = "/opsys"
PASSWORD = "mot-de-passe-cfo-prive-fictif-123"
OWNER = "owner.cfo.prive.fictif"
ADMIN = "admin.cfo.prive.fictif"
QUESTION = "Quelles obligations humaines restent à vérifier?"


@pytest.fixture
def client_cfo_prive(session):
    from m5_financecore import outils

    outils.utiliser_stockage_durable()
    with session() as cnx:
        identite.creer_personne(cnx, OWNER, "Propriétaire fictif", PASSWORD, ["nathan_owner"])
        identite.creer_personne(cnx, ADMIN, "Admin fictif", PASSWORD, ["admin"])
    app = application.creer_application(Configuration(SECRET), None, session)
    with TestClient(app, base_url=f"https://testserver{PREFIXE}") as client:
        yield client


def _connecter(client, personne=OWNER):
    retour = client.post(
        "/connexion", data={"identifiant": personne, "mot_de_passe": PASSWORD}, follow_redirects=False
    )
    assert retour.status_code == 303
    return client.get("/api/session").json()["csrf"]


def _declaration_privee(csrf):
    return {
        "type": "paies",
        "montant_cad": "1250.00",
        "periode_debut": "2026-10-01",
        "periode_fin": "2026-10-02",
        "date_paie": "2026-10-06",
        "echeance": "2026-10-07",
        "reference_piece": '<script>pièce-fictive</script>',
        "autorite": "Source déclarée fictive",
        "source_consultee_le": "2026-10-03",
        "applicable_du": "2026-01-01",
        "applicable_au": "2026-12-31",
        "version": "édition humaine fictive 2026",
        "revision_attendue": "0",
        "mutation_id": "a" * 32,
        "csrf": csrf,
    }


def test_projection_privee_ne_somme_ni_ne_rend_utilisable():
    obligation = {
        "type": "paies", "montant_cad": "1250.00", "periode_debut": "2026-10-01",
        "periode_fin": "2026-10-02", "date_paie": "2026-10-06", "echeance": "2026-10-07",
        "reference_piece": "pièce-1", "autorite": "autorité", "source_consultee_le": "2026-10-03",
        "applicable_du": "2026-01-01", "applicable_au": "2026-12-31", "version": "v1",
    }
    snapshot = {"revision": 1, "obligations": [{
        "id": "a" * 32, "obligation": obligation, "statut": "ACTIVE", "confirme_le": "2026-10-03T00:00:00+00:00",
    }]}
    resultat = composer(snapshot)
    assert resultat["statut"] == "INCONNU"
    assert resultat["montant_utilisable_cad"] is None
    assert resultat["lignes"][0]["montant_declare_cad"] == "1250.00"
    assert resultat["lignes"][0]["montant_utilisable_cad"] is None
    assert resultat["cash_libre_modifie"] is False and resultat["prevision_modifiee"] is False
    assert "total_cad" not in resultat and "total" not in resultat
    assert "PROVISION" in " ".join(resultat["raisons"])
    assert composer({**snapshot, "revision": 2})["snapshot_prive_id"] != resultat["snapshot_prive_id"]


def test_projection_privee_refuse_structure_invalide():
    with pytest.raises(SnapshotPriveInvalide):
        composer({"revision": 1, "obligations": [{"id": "a" * 32}]})
    with pytest.raises(SnapshotPriveInvalide):
        composer({"revision": True, "obligations": []})


def test_cfo_html_lit_le_journal_chiffre_sans_modifier_cash_ni_exposer_api(client_cfo_prive):
    client = client_cfo_prive
    csrf = _connecter(client)
    api_avant = client.post(
        "/api/finance/cfo", json={"question_posee": QUESTION}, headers={"x-csrf-token": csrf}
    )
    assert api_avant.status_code == 200
    avant = api_avant.json()["resultat"]

    saisi = client.post("/finance/paie/obligations", data=_declaration_privee(csrf))
    assert saisi.status_code == 200, saisi.text
    api_apres = client.post(
        "/api/finance/cfo", json={"question_posee": QUESTION}, headers={"x-csrf-token": csrf}
    )
    assert api_apres.status_code == 200
    apres = api_apres.json()["resultat"]
    assert apres == avant
    assert "1250.00" not in json.dumps(apres, ensure_ascii=False)

    page = client.post("/finance/cfo", data={"csrf": csrf, "question_posee": QUESTION})
    assert page.status_code == 200, page.text
    assert page.headers["cache-control"] == "no-store"
    assert page.headers["pragma"] == "no-cache"
    assert "Déclarations paie/DAS privées" in page.text
    assert "1250.00" in page.text and "Montant utilisable : non disponible" in page.text
    assert "2026-10-01" in page.text and "2026-10-07" in page.text
    assert "édition humaine fictive 2026" in page.text
    assert "&lt;script&gt;pièce-fictive&lt;/script&gt;" in page.text
    assert "<script>" not in page.text
    assert "INCONNU" in page.text and "aucun cumul n’est calculé" in page.text


def test_cfo_api_et_admin_sans_role_finance_ne_dechiffrent_pas(client_cfo_prive, monkeypatch):
    client = client_cfo_prive
    csrf_owner = _connecter(client)
    assert client.post("/finance/paie/obligations", data=_declaration_privee(csrf_owner)).status_code == 200

    def lecture_interdite(_cnx):
        raise AssertionError("l'API et admin seul ne lisent pas le registre privé")

    monkeypatch.setattr(obligations_privees, "lire", lecture_interdite)
    response = client.post(
        "/api/finance/cfo", json={"question_posee": QUESTION}, headers={"x-csrf-token": csrf_owner}
    )
    assert response.status_code == 200 and "1250.00" not in response.text
    csrf_admin = _connecter(client, ADMIN)
    page = client.post("/finance/cfo", data={"csrf": csrf_admin, "question_posee": QUESTION})
    assert page.status_code == 200
    assert "1250.00" not in page.text and "Déclarations paie/DAS privées" not in page.text


def test_cfo_html_revalide_finance_apres_dechiffrement(client_cfo_prive, session, monkeypatch):
    client = client_cfo_prive
    csrf = _connecter(client)
    assert client.post("/finance/paie/obligations", data=_declaration_privee(csrf)).status_code == 200
    lire_original = obligations_privees.lire

    def lire_puis_revoquer(cnx):
        resultat = lire_original(cnx)
        identite.retirer_role(cnx, OWNER, "nathan_owner")
        return resultat

    monkeypatch.setattr(obligations_privees, "lire", lire_puis_revoquer)
    retour = client.post("/finance/cfo", data={"csrf": csrf, "question_posee": QUESTION})
    assert retour.status_code == 403
    assert "1250.00" not in retour.text
