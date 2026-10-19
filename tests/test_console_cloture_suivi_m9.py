"""Clôture M9 par la console : vraie connexion, session, CSRF et décision HTTP ; aucun effet terrain.

Préparation et proposition restent natives (bus M8, SQLite, fixtures M9) ; seule la décision passe
par HTTP. Une clôture approuvée atteste une revue humaine fictive, ni action ni causalité terrain.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from opsys import etat, identite, stockage
from opsys.console import application
from opsys.console.securite import Configuration
from opsys.stockage.schema import APPROBATIONS

RACINE = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "_console_cloture_suivi_m9",
    RACINE / "departments" / "m09-strategic-intelligence" / "tests" / "test_cloture_suivi_decisions.py",
)
h = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(h)
b = h.b
installation = h.installation

SECRET = "secret-de-signature-console-m9-" + "x" * 32
PREFIXE = "/opsys"
MOT_DE_PASSE = "mot-de-passe-suivi-fictif"


def _client(installation):
    app = application.creer_application(Configuration(SECRET), installation, etat.session)
    return TestClient(app, base_url=f"https://testserver{PREFIXE}")


def _connecter(client):
    reponse = client.post(
        "/connexion", data={"identifiant": b.PROPRIO.personne, "mot_de_passe": MOT_DE_PASSE}, follow_redirects=False
    )
    assert reponse.status_code == 303, reponse.text
    session = client.get("/api/session")
    assert session.status_code == 200 and session.json()["utilisateur"] == b.PROPRIO.personne, session.text
    return session.json()["csrf"]


def _demande(demande_id):
    with stockage.transaction() as cnx:
        return dict(cnx.execute(select(APPROBATIONS).where(APPROBATIONS.c.id == demande_id)).mappings().one())


def _decider_http(client, demande_id, csrf=None):
    entetes = {} if csrf is None else {"x-csrf-token": csrf}
    return client.post(f"/api/approbations/{demande_id}/decision", json={"decision": "approuver"}, headers=entetes)


def test_console_approuve_la_cloture_dediee_signee_par_le_proprietaire_sql(installation):
    cap, suivi_id, demande_id, args, alerte = h._proposer(installation)
    with _client(installation) as client:
        csrf = _connecter(client)
        plan = b._suivis()
        avant = h._metier_hors_cloture()
        reponse = _decider_http(client, demande_id, csrf)
        assert reponse.status_code == 200, reponse.text
        recu = reponse.json()
        assert recu["id"] == demande_id and recu["statut"] == "executee", recu
        executees = client.get("/api/approbations", params={"statut": "executee"})
        assert executees.status_code == 200, executees.text
        assert demande_id in [d["id"] for d in executees.json()["approbations"]]
    ligne = _demande(demande_id)
    assert (ligne["statut"], ligne["outil"], ligne["departement"]) == ("executee", h.CLORE, b.DEPARTEMENT)
    assert ligne["niveau"] == "N3" and json.loads(ligne["arguments"]) == args
    assert ligne["decide_par"] == b.PROPRIO.personne and ligne["decide_role"] == "nathan_owner"
    assert b._suivis() == plan and h._metier_hors_cloture() == avant
    resultat = b._lire(cap, b.LIRE, {"suivi_id": suivi_id})
    assert resultat["suivi"] == plan[0]
    assert resultat["etat_suivi"] == "cloturee_par_revue_humaine"
    cloture = resultat["cloture"]
    assert cloture["suivi_id"] == suivi_id and cloture["statut"] == "cloturee_par_revue_humaine"
    assert cloture["empreinte_suivi"] == args["empreinte_suivi"]
    assert cloture["preuve"]["alerte"] == alerte and cloture["bilan"] == args["bilan"]
    assert cloture["decision"]["demande_id"] == demande_id
    assert cloture["decision"]["decide_par"] == b.PROPRIO.personne
    assert cloture["decision"]["decide_role"] == "nathan_owner"
    assert cloture["decision"]["decide_le"] == ligne["decide_le"]
    assert h._clotures() == [cloture]
    stockage.liberer()
    cap = b._capacites(installation)
    assert b._lire(cap, b.LIRE, {"suivi_id": suivi_id}) == resultat
    assert h._clotures() == [cloture] and b._suivis() == plan


def test_console_refuse_apres_retrait_sql_du_role_proprietaire(installation):
    _, _, demande_id, _, _ = h._proposer(installation)
    with _client(installation) as client:
        csrf = _connecter(client)
        with stockage.transaction() as cnx:
            identite.retirer_role(cnx, b.PROPRIO.personne, "nathan_owner")
            personne = identite.personne_active(cnx, b.PROPRIO.personne)
            assert personne is not None and "admin" in personne.roles and "nathan_owner" not in personne.roles
        assert client.get("/api/session").json()["roles"] == ["admin"]
        demande = _demande(demande_id)
        plan = b._suivis()
        avant = h._metier_hors_cloture()
        reponse = _decider_http(client, demande_id, csrf)
        assert reponse.status_code == 400, reponse.text
        assert "aucun rôle autorisé pour N3" in reponse.json()["detail"]
        assert "nathan_owner" in reponse.json()["detail"] and "CSRF" not in reponse.text
    assert _demande(demande_id) == demande and demande["statut"] == "en_attente"
    assert h._clotures() == [] and b._suivis() == plan and h._metier_hors_cloture() == avant


def test_console_refuse_decision_sans_jeton_csrf(installation):
    _, _, demande_id, _, _ = h._proposer(installation)
    with _client(installation) as client:
        _connecter(client)
        demande = _demande(demande_id)
        plan = b._suivis()
        avant = h._metier_hors_cloture()
        reponse = _decider_http(client, demande_id)
        assert reponse.status_code == 403 and "CSRF" in reponse.json()["detail"], reponse.text
        attente = client.get("/api/approbations", params={"statut": "en_attente"})
        assert attente.status_code == 200, attente.text
        assert demande_id in [d["id"] for d in attente.json()["approbations"]]
    assert _demande(demande_id) == demande and demande["statut"] == "en_attente"
    assert h._clotures() == [] and b._suivis() == plan and h._metier_hors_cloture() == avant


def test_console_refuse_decision_sans_session_signee(installation):
    _, _, demande_id, _, _ = h._proposer(installation)
    demande = _demande(demande_id)
    plan = b._suivis()
    avant = b._tables()
    with _client(installation) as client:
        reponse = _decider_http(client, demande_id, "jeton-csrf-fictif-sans-cookie")
        assert reponse.status_code == 401, reponse.text
        assert reponse.json()["detail"] == "authentification requise"
    assert _demande(demande_id) == demande and demande["statut"] == "en_attente"
    assert h._clotures() == [] and b._suivis() == plan and b._tables() == avant
