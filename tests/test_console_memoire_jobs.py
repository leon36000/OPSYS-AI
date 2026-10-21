"""Console des jobs de consolidation M10 : grants humains, lecture expurgée et révocation."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import text

from opsys import identite
from opsys.console import application
from opsys.console.securite import Configuration

SECRET = "secret-de-signature-de-test-" + "x" * 32
IDENTIFIANT = "nathan"
MOT_DE_PASSE = "mot-de-passe-de-console-test-1234"
PREFIXE = "/opsys"


def _connecter(client):
    return client.post(
        "/connexion", data={"identifiant": IDENTIFIANT, "mot_de_passe": MOT_DE_PASSE}, follow_redirects=False
    )


def _csrf(client):
    return client.get("/api/session").json()["csrf"]


@pytest.fixture
def personne_nathan(session):
    with session() as cnx:
        identite.creer_personne(cnx, IDENTIFIANT, "Nathan St-Louis", MOT_DE_PASSE, ["nathan_owner"])
    return IDENTIFIANT


@pytest.fixture
def client_jobs(departements_demo, session, personne_nathan):
    app = application.creer_application(Configuration(SECRET), departements_demo, session)
    from fastapi.testclient import TestClient

    with TestClient(app, base_url=f"https://testserver{PREFIXE}") as client:
        assert _connecter(client).status_code == 303
        yield client


def _grant(client, *, job_id="audit-console", **extra):
    headers = {"x-csrf-token": _csrf(client)}
    return client.post(
        "/api/memoire-developpement/jobs",
        json={"job_id": job_id, "fuseau": "America/Toronto", **extra},
        headers=headers,
    )


def test_jobs_authentifies_liste_statut_et_revocation(client_jobs):
    client = client_jobs
    assert client.get("/api/memoire-developpement/jobs").status_code == 200
    assert client.get("/api/memoire-developpement/jobs").json() == {"jobs": []}

    sans_csrf = client.post("/api/memoire-developpement/jobs", json={"job_id": "audit-console"})
    assert sans_csrf.status_code == 403

    cree = _grant(client)
    assert cree.status_code == 200, cree.text
    donnees = cree.json()
    assert donnees["job_id"] == "audit-console" and donnees["active"] is True
    assert donnees["configuration_core_a_regenerer"] is True
    assert "capability" not in str(donnees).lower()
    assert "credential_file" not in donnees
    credential_v1 = Path(os.environ["OPSYS_HOME"]) / "secrets" / "memoire-jobs" / "audit-console.json"
    ancien_secret = credential_v1.read_bytes()
    doublon = _grant(client)
    assert doublon.status_code == 409
    assert credential_v1.read_bytes() == ancien_secret
    assert not credential_v1.with_name("audit-console-v2.json").exists()

    liste = client.get("/api/memoire-developpement/jobs")
    assert liste.status_code == 200 and len(liste.json()["jobs"]) == 1
    statut = client.get("/api/memoire-developpement/jobs/audit-console")
    assert statut.status_code == 200
    assert statut.json()["active"] is True
    assert statut.json()["domain"] == "development"
    assert "credential_file" not in statut.json()
    assert "capability_hash" not in str(statut.json())

    headers = {"x-csrf-token": _csrf(client)}
    revoke = client.post("/api/memoire-developpement/jobs/audit-console/revoquer", headers=headers, json={})
    assert revoke.status_code == 200 and revoke.json()["active"] is False
    assert client.get("/api/memoire-developpement/jobs/audit-console").json()["active"] is False
    renouvellement = _grant(client)
    assert renouvellement.status_code == 200, renouvellement.text
    assert renouvellement.json()["version"] == 2
    assert renouvellement.json()["configuration_core_a_regenerer"] is True
    credential_v2 = credential_v1.with_name("audit-console-v2.json")
    assert credential_v1.read_bytes() == ancien_secret
    assert credential_v2.is_file() and credential_v2.read_bytes() != ancien_secret
    assert "credential_file" not in renouvellement.text and "capability" not in renouvellement.text.lower()


def test_jobs_refusent_champs_identite_depot_et_commandes(client_jobs):
    client = client_jobs
    headers = {"x-csrf-token": _csrf(client)}
    for extra in (
        {"actor": "nathan", "role": "admin"},
        {"repository": "/tmp"},
        {"credential_file": "/tmp/secret"},
        {"capability": "x"},
        {"command": ["python", "-c", "..." ]},
        {"limites": {"max_events": True}},
        {"fuseau": "<script>alert(1)</script>"},
    ):
        response = client.post(
            "/api/memoire-developpement/jobs",
            json={"job_id": "audit-console", **extra},
            headers=headers,
        )
        assert response.status_code == 400, (extra, response.text)
    assert not (Path(os.environ["OPSYS_HOME"]) / "secrets" / "memoire-jobs").exists()
    malformed = client.post(
        "/api/memoire-developpement/jobs",
        content="{",
        headers={"x-csrf-token": headers["x-csrf-token"], "content-type": "application/json"},
    )
    assert malformed.status_code == 400
    assert not (Path(os.environ["OPSYS_HOME"]) / "secrets" / "memoire-jobs").exists()


def test_jobs_unauthentifie_ne_cree_aucun_fichier(client_jobs, opsys_home):
    client = client_jobs
    client.post("/deconnexion", data={"csrf": _csrf(client)}, follow_redirects=False)
    response = client.post("/api/memoire-developpement/jobs", json={"job_id": "sans-session"})
    assert response.status_code == 401
    assert not (opsys_home / "secrets").exists()


def test_jobs_revalident_compte_actif_et_role(client_jobs, session, opsys_home):
    client = client_jobs
    headers = {"x-csrf-token": _csrf(client)}
    with session() as cnx:
        cnx.execute(text("UPDATE personnes SET actif = 0 WHERE identifiant = :id"), {"id": IDENTIFIANT})
    assert client.get("/api/memoire-developpement/jobs").status_code in {401, 403}
    assert client.post("/api/memoire-developpement/jobs", json={"job_id": "retire"}, headers=headers).status_code in {
        401,
        403,
    }
    assert not (opsys_home / "secrets").exists()


def test_jobs_revalident_role_retraite(client_jobs, session):
    client = client_jobs
    csrf = _csrf(client)
    with session() as cnx:
        identite.retirer_role(cnx, IDENTIFIANT, "nathan_owner")
        identite.ajouter_role(cnx, IDENTIFIANT, "employee")
    assert client.get("/api/memoire-developpement/jobs").status_code == 403
    assert client.post(
        "/api/memoire-developpement/jobs", json={"job_id": "role-retire"},
        headers={"x-csrf-token": csrf},
    ).status_code == 403
    assert not (Path(os.environ["OPSYS_HOME"]) / "secrets" / "memoire-jobs" / "role-retire.json").exists()


def test_jobs_refusent_creation_si_parent_credential_est_symlink(client_jobs, opsys_home, tmp_path):
    client = client_jobs
    dossier = tmp_path / "cible"
    dossier.mkdir(mode=0o700)
    jobs = opsys_home / "secrets" / "memoire-jobs"
    jobs.parent.mkdir(parents=True, mode=0o700)
    jobs.symlink_to(dossier, target_is_directory=True)
    headers = {"x-csrf-token": _csrf(client)}
    response = client.post(
        "/api/memoire-developpement/jobs",
        json={"job_id": "symlink"},
        headers=headers,
    )
    assert response.status_code in {400, 403}
    assert list(dossier.iterdir()) == []


def test_jobs_page_echappe_et_ne_divulgue_pas_credential(client_jobs):
    client = client_jobs
    assert _grant(client, job_id="<script>").status_code == 400
    page = client.get("/memoire/consolidation")
    assert page.status_code == 200
    assert "Consolidation planifiée" in page.text
    assert "n’installe pas un ordonnanceur" in page.text and "configurer-cron" in page.text
    assert "capability" not in page.text.lower()
    assert "credential_file" not in page.text


def test_jobs_admin_peut_lire_et_creer(departements_demo, session):
    identifiant = "gestionnaire-jobs"
    mot_de_passe = "mot-de-passe-admin-jobs-1234"
    with session() as cnx:
        identite.creer_personne(cnx, identifiant, "Gestionnaire", mot_de_passe, ["admin"])
    app = application.creer_application(Configuration(SECRET), departements_demo, session)
    from fastapi.testclient import TestClient

    with TestClient(app, base_url=f"https://testserver{PREFIXE}") as client:
        assert client.post(
            "/connexion", data={"identifiant": identifiant, "mot_de_passe": mot_de_passe}, follow_redirects=False
        ).status_code == 303
        assert client.get("/api/memoire-developpement/jobs").status_code == 200
        response = _grant(client, job_id="admin-grant")
        assert response.status_code == 200, response.text


def test_jobs_get_refuse_parametres_excedentaires_et_rapport_inconnu(client_jobs):
    client = client_jobs
    assert _grant(client, job_id="query-strict").status_code == 200
    assert client.get("/api/memoire-developpement/jobs", params={"limite": 5}).status_code == 400
    assert client.get("/api/memoire-developpement/jobs/query-strict", params={"debug": "1"}).status_code == 400
    assert client.get(
        "/api/memoire-developpement/jobs/query-strict/rapport", params={"report_id": "f" * 64}
    ).status_code == 404
    assert client.get(
        "/api/memoire-developpement/jobs/query-strict/rapport?report_id=abc&report_id=def"
    ).status_code == 400
    assert client.get(
        "/api/memoire-developpement/jobs/query-strict/rapport?report_id=abc&extra=1"
    ).status_code == 400


def test_jobs_refusent_backend_non_supporte_sans_creer_de_credential(client_jobs, opsys_home, monkeypatch):
    from m10_memoire import consolidation_developpement as jobs

    def backend_refuse():
        raise jobs.BackendConsolidationNonPrisEnCharge("backend detail privé")

    monkeypatch.setattr(jobs, "_sqlite_seulement", backend_refuse)
    response = _grant(client_jobs, job_id="backend-pg")
    assert response.status_code == 409
    assert "SQLite fichier" in response.json()["detail"]
    assert "backend detail privé" not in response.text and "Traceback" not in response.text
    assert not (opsys_home / "secrets" / "memoire-jobs" / "backend-pg.json").exists()


def test_jobs_rapport_reel_est_lisible_et_les_valeurs_html_sont_echappees(client_jobs, opsys_home, monkeypatch):
    import datetime as dt

    from m10_memoire import consolidation_developpement as jobs

    # Le premier créneau du jour est dû à 03 h Toronto, indépendamment de l’heure du runner.
    monkeypatch.setattr(jobs, "_maintenant", lambda: dt.datetime(2026, 10, 1, 12, tzinfo=dt.UTC))
    client = client_jobs
    cree = _grant(client, job_id="rapport-reel")
    assert cree.status_code == 200, cree.text
    credential = opsys_home / "secrets" / "memoire-jobs" / "rapport-reel.json"
    assert credential.is_file() and credential.stat().st_mode & 0o777 == 0o600

    execution = jobs.executer("rapport-reel", credential)
    assert execution["report_id"]
    api = client.get("/api/memoire-developpement/jobs/rapport-reel/rapport")
    assert api.status_code == 200
    assert api.json()["report_id"] == execution["report_id"]
    assert api.json()["report"]["domain"] == "development"
    assert "credential_file" not in api.text and "capability_hash" not in api.text
    page = client.get("/memoire/consolidation/rapport-reel/rapport")
    assert page.status_code == 200 and "Rapport de consolidation" in page.text
    revoke = client.post(
        "/api/memoire-developpement/jobs/rapport-reel/revoquer",
        headers={"x-csrf-token": _csrf(client)},
        json={},
    )
    detail = client.get("/api/memoire-developpement/jobs/rapport-reel")
    assert revoke.status_code == 200 and detail.json()["active"] is False

    monkeypatch.setattr(
        jobs,
        "lire_rapport",
        lambda job_id, report_id=None: {
            "job_id": job_id,
            "report_id": "x",
            "report": {
                "domain": "development",
                "analyzer_version": "<script>alert(1)</script>",
                "limits": {"max_events": 1, "max_report_bytes": 2048},
                "coverage": {"events_total": 12, "sources_total": 3},
                "audit": {
                    "status": "partial",
                    "truncated": True,
                    "repository": "/path/private",
                    "limit": 100,
                    "counts": {"sources": 3},
                    "findings": [{
                        "type": "<img src=x onerror=alert(1)>", "detail": "<script>secret</script>",
                        "event_ids": ["event-1"],
                        "preuves": [{"source_ref": "src:abc", "sha256": "sha256-visible", "omissions": 2}],
                    }],
                },
                "self_model": {
                    "identity": "M10 développement", "completion": "not_evaluated",
                    "modules": [{"module": "M7", "state": "observed", "proofs": [{
                        "source_ref": "src:abc", "path": "docs/ref.md", "indexed_sha256": "sha256-file",
                        "observed_sha256": None, "freshness": "stale", "scope": "inside_grant",
                    }]}],
                    "mission": {"state": "unknown", "reason": "<script>inconnu</script>"},
                    "tools_and_permissions": {"state": "unknown", "reason": "non évalué"},
                    "limits": ["partiel", "<script>limite</script>"],
                },
            },
        },
    )
    page_xss = client.get("/memoire/consolidation/rapport-reel/rapport")
    assert page_xss.status_code == 200
    assert "<script>secret</script>" not in page_xss.text
    assert "&lt;script&gt;secret&lt;/script&gt;" in page_xss.text
    assert "sha256-file" in page_xss.text and "sha256-visible" in page_xss.text
    assert "not_evaluated" in page_xss.text and "inconnu" in page_xss.text
    assert "non lu / inconnu" in page_xss.text and "inside_grant" in page_xss.text
    assert "max events" in page_xss.text and "omissions" in page_xss.text
    assert "/path/private" not in page_xss.text
    assert "credential" not in page_xss.text.lower()
