"""Parcours HTTP de la mémoire dev sous session console authentifiée et CSRF."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from memoire.doubles import postgres_ephemere, raison_sans_docker

from opsys import identite, stockage
from opsys.console import memoire_api, securite

SECRET_SESSION = "secret-session-test-" + "x" * 32
ADMIN = "admin.dev"
EMPLOYEE = "employee.dev"
PASSWORD = "mot-de-passe-memoire-dev-1234"


@pytest.fixture
def api(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'instance.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, ADMIN, "Admin mémoire", PASSWORD, ["admin"])
        identite.creer_personne(cnx, EMPLOYEE, "Employé mémoire", PASSWORD, ["employee"])

    def session_api(request: Request, *, administrateur: bool = True):
        session = securite.lire_session(request.cookies.get(securite.NOM_COOKIE), SECRET_SESSION)
        if session is None:
            raise HTTPException(401, "authentification requise")
        with stockage.transaction() as cnx:
            personne = identite.personne_active(cnx, session.utilisateur)
        if personne is None:
            raise HTTPException(401, "authentification requise")
        session = replace(session, roles=personne.roles)
        if administrateur and not personne.roles.intersection({"admin", "nathan_owner"}):
            raise HTTPException(403, "administration réservée")
        return session

    def ecriture_api(request: Request):
        session = session_api(request)
        if not securite.csrf_valide(request.headers.get("x-csrf-token"), session):
            raise HTTPException(403, "jeton CSRF absent ou invalide")
        return session

    parse_calls = []

    async def objet_json_borne(request):
        parse_calls.append(request)
        return await memoire_api._objet_json_borne(request)

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.session_api = session_api
    app.state.ecriture_api = ecriture_api
    app.include_router(
        memoire_api.creer_router(
            session_api=session_api,
            ecriture_api=ecriture_api,
            cnx_factory=stockage.transaction,
            objet_json=objet_json_borne,
        )
    )
    with TestClient(app, base_url="https://testserver") as client:
        yield client, tmp_path, parse_calls
    stockage.liberer()


def _connecter(client: TestClient, utilisateur: str = ADMIN, roles: list[str] | None = None) -> str:
    session = securite.ouvrir_session(utilisateur, roles or ["admin"], maintenant=1_800_000_000)
    client.cookies.set(securite.NOM_COOKIE, securite.signer_session(session, SECRET_SESSION), path="/")
    return session.csrf


def test_http_refuse_sans_cookie_bearer_public_employe_et_role_retire(api):
    client, _, _ = api
    assert (
        client.get("/api/memoire-developpement/status", headers={"authorization": "Bearer public"}).status_code == 401
    )

    _connecter(client, EMPLOYEE, ["employee"])
    assert client.get("/api/memoire-developpement/status").status_code == 403

    csrf = _connecter(client)
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, ADMIN, "admin")
        identite.ajouter_role(cnx, ADMIN, "employee")
    assert client.get("/api/memoire-developpement/status").status_code == 403
    assert client.post("/api/memoire-developpement/prompts", json={}, headers={"x-csrf-token": csrf}).status_code == 403


def test_audit_http_est_authentifie_strict_borne_et_non_destructif(api, monkeypatch, tmp_path):
    client, _, parse_calls = api
    endpoint = "/api/memoire-developpement/audit"
    assert client.get(endpoint + "?limite=oops&actor=admin.dev").status_code == 401
    csrf = _connecter(client)
    before = len(parse_calls)
    # GET n'analyse jamais de corps JSON et le dépôt vient du serveur, jamais de la requête.
    monkeypatch.setattr(memoire_api, "_repository", lambda: tmp_path)
    response = client.request("GET", endpoint + "?limite=10", content=b"not-json")
    assert response.status_code == 200
    assert response.json()["repository"] == str(tmp_path.resolve())
    assert len(parse_calls) == before

    for query in ("limite=0", "limite=501", "limite=true", "limite=1.0", "limite=2&limite=3", "repository=/tmp"):
        assert client.get(endpoint + "?" + query).status_code == 400

    # Le vrai registre reçoit un prompt orphelin, un plan sans postflight et deux verdicts opposés.
    prompt = {
        "prompt_id": "audit-orphan",
        "content": "Contenu confidentiel qui ne doit pas sortir dans le rapport",
        "version": 1,
        "module": "M7",
        "purpose": "test audit",
    }
    assert (
        client.post("/api/memoire-developpement/prompts", json=prompt, headers={"x-csrf-token": csrf}).status_code
        == 200
    )
    plan = {
        "plan_id": "audit-plan",
        "version": 1,
        "module": "M7",
        "prompt_id": "audit-orphan",
        "prompt_version": 1,
        "objective": "Plan pour rapport audit",
        "steps": [{"id": "step", "description": "Vérifier les preuves"}],
        "files": [],
    }
    assert client.post("/api/memoire-developpement/plans", json=plan, headers={"x-csrf-token": csrf}).status_code == 200
    orphan = prompt | {"prompt_id": "audit-prompt-without-plan"}
    assert (
        client.post("/api/memoire-developpement/prompts", json=orphan, headers={"x-csrf-token": csrf}).status_code
        == 200
    )
    postflight = {
        "operation_id": "audit-run-1",
        "module": "M7",
        "plan_id": "audit-claim-plan",
        "status": "done",
        "summary": "Résultat vérifié",
        "changes": [],
        "tests": [],
        "report_refs": [],
        "claim_key": "audit-claim",
    }
    assert (
        client.post(
            "/api/memoire-developpement/postflight", json=postflight, headers={"x-csrf-token": csrf}
        ).status_code
        == 200
    )
    second = postflight | {"operation_id": "audit-run-2", "status": "failed"}
    assert (
        client.post("/api/memoire-developpement/postflight", json=second, headers={"x-csrf-token": csrf}).status_code
        == 200
    )
    journal_before = client.get("/api/memoire-developpement/status").json()
    rapport = client.get(endpoint).json()
    assert rapport["status"] == "available"
    assert rapport["counts"]["prompts_sans_plan"] == 1
    assert rapport["counts"]["plans_sans_postflight"] == 1
    assert rapport["counts"]["claims_contradictoires"] == 1
    assert "Contenu confidentiel" not in str(rapport)
    finding_json = str(rapport["findings"])
    assert "event_id" in finding_json and "hash" in finding_json
    assert client.get("/api/memoire-developpement/status").json() == journal_before
    maillons_before = list(stockage.maillons("m10-memoire", "developpement"))

    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, ADMIN, "admin")
        identite.ajouter_role(cnx, ADMIN, "employee")
    assert client.get(endpoint).status_code == 403
    assert list(stockage.maillons("m10-memoire", "developpement")) == maillons_before


def test_http_refuse_une_session_apres_desactivation_du_compte(api):
    client, _, _ = api
    csrf = _connecter(client)
    with stockage.transaction() as cnx:
        identite.activer(cnx, ADMIN, False)

    assert client.get("/api/memoire-developpement/status").status_code == 401
    assert client.post("/api/memoire-developpement/prompts", json={}, headers={"x-csrf-token": csrf}).status_code == 401


def test_http_exige_csrf_et_refuse_identite_ou_chemin_depot_du_corps(api):
    client, _, _ = api
    csrf = _connecter(client)
    command = {
        "prompt_id": "api-prompt",
        "content": "Réparer le rappel API_KEY=sk-api-test-secret-1234567890",
        "version": 1,
        "module": "M7",
        "purpose": "rappel test HTTP",
    }
    assert client.post("/api/memoire-developpement/prompts", json=command).status_code == 403
    assert (
        client.post(
            "/api/memoire-developpement/prompts", json=command | {"actor": ADMIN}, headers={"x-csrf-token": csrf}
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/memoire-developpement/scan", json={"repository": "/tmp"}, headers={"x-csrf-token": csrf}
        ).status_code
        == 400
    )

    response = client.post("/api/memoire-developpement/prompts", json=command, headers={"x-csrf-token": csrf})
    assert response.status_code == 200
    assert "sk-api-test-secret-1234567890" not in response.text
    assert response.json()["redacted"] is True

    preflight = client.post(
        "/api/memoire-developpement/preflight",
        json={"module": "M7", "task": "rappel test HTTP", "files": []},
    )
    assert preflight.status_code == 200
    assert preflight.json()["status"] == "available"
    assert client.get("/api/memoire-developpement/status").json()["status"] == "valid"


def test_http_postgresql_persiste_sur_le_stockage_canonique(monkeypatch):
    raison = raison_sans_docker()
    if raison:
        pytest.skip(raison)

    with postgres_ephemere() as url:
        monkeypatch.setenv(stockage.ENV_URL, url)
        stockage.migrer(url)
        with stockage.transaction() as cnx:
            identite.creer_personne(cnx, ADMIN, "Admin mémoire PG", PASSWORD, ["admin"])

        def session_api(request: Request, *, administrateur: bool = True):
            session = securite.lire_session(request.cookies.get(securite.NOM_COOKIE), SECRET_SESSION)
            if session is None:
                raise HTTPException(401, "authentification requise")
            with stockage.transaction() as cnx:
                personne = identite.personne_active(cnx, session.utilisateur)
            if personne is None:
                raise HTTPException(401, "authentification requise")
            if administrateur and not personne.roles.intersection({"admin", "nathan_owner"}):
                raise HTTPException(403, "administration réservée")
            return replace(session, roles=personne.roles)

        def ecriture_api(request: Request):
            session = session_api(request)
            if not securite.csrf_valide(request.headers.get("x-csrf-token"), session):
                raise HTTPException(403, "jeton CSRF absent ou invalide")
            return session

        app = FastAPI()
        app.include_router(
            memoire_api.creer_router(
                session_api=session_api, ecriture_api=ecriture_api, cnx_factory=stockage.transaction
            )
        )
        with TestClient(app, base_url="https://testserver") as client:
            csrf = _connecter(client)
            response = client.post(
                "/api/memoire-developpement/prompts",
                json={
                    "prompt_id": "postgres-prompt",
                    "content": "Conserver le rappel Postgres",
                    "version": 1,
                    "module": "M7",
                    "purpose": "test backend canonique",
                },
                headers={"x-csrf-token": csrf},
            )
            assert response.status_code == 200
            reprise = client.post(
                "/api/memoire-developpement/preflight",
                json={"module": "M7", "task": "rappel Postgres", "files": []},
            )
            assert reprise.status_code == 200 and reprise.json()["status"] == "available"
        stockage.liberer()


def test_http_auth_et_csrf_precedent_toute_lecture_du_corps_et_limite_64k(api):
    client, _, parse_calls = api
    before = len(parse_calls)
    oversized = b'{"invalid":"' + b"x" * (64 * 1024) + b'"}'
    response = client.post("/api/memoire-developpement/prompts", content=oversized)
    assert response.status_code == 401
    assert len(parse_calls) == before

    csrf = _connecter(client)
    sans_csrf = client.post("/api/memoire-developpement/prompts", content=oversized)
    assert sans_csrf.status_code == 403
    assert len(parse_calls) == before

    trop_gros = client.post(
        "/api/memoire-developpement/prompts",
        content=oversized,
        headers={"x-csrf-token": csrf, "content-type": "application/json"},
    )
    assert trop_gros.status_code == 413
    assert len(parse_calls) == before + 1
    assert client.get("/api/memoire-developpement/status").json()["verified"] == 0


def test_factory_sans_callback_applique_la_meme_limite_de_corps(api):
    client, _, _ = api
    app = FastAPI()
    app.include_router(
        memoire_api.creer_router(
            session_api=client.app.state.session_api,
            ecriture_api=client.app.state.ecriture_api,
            cnx_factory=stockage.transaction,
        )
    )
    with TestClient(app, base_url="https://testserver") as autonome:
        csrf = _connecter(autonome)
        response = autonome.post(
            "/api/memoire-developpement/scan",
            content=b'{"large":"' + b"x" * (64 * 1024) + b'"}',
            headers={"x-csrf-token": csrf, "content-type": "application/json"},
        )
        assert response.status_code == 413
        assert autonome.get("/api/memoire-developpement/status").json()["verified"] == 0


@pytest.mark.parametrize(
    "modifications",
    [
        {"version": True},
        {"version": 0},
        {"version": 2**40},
        {"module": 7},
        {"prompt_id": []},
        {"content": 17},
        {"purpose": None},
        {"source_refs": "docs/notes.md"},
        {"source_refs": ["docs/notes.md", 4]},
        {"status": True},
    ],
)
def test_http_refuse_types_prompt_malformes_sans_ecriture(api, modifications):
    client, _, _ = api
    csrf = _connecter(client)
    command = {
        "prompt_id": "typed-prompt",
        "content": "Conserver un prompt valide.",
        "version": 1,
        "module": "M7",
        "purpose": "validation stricte",
        "source_refs": [],
    } | modifications
    response = client.post("/api/memoire-developpement/prompts", json=command, headers={"x-csrf-token": csrf})
    assert response.status_code == 400
    assert client.get("/api/memoire-developpement/status").json()["verified"] == 0


def test_http_refuse_plan_et_postflight_malformes_sans_ecriture(api):
    client, _, _ = api
    csrf = _connecter(client)
    prompt = {
        "prompt_id": "typed-plan-prompt",
        "content": "Un prompt préalable",
        "version": 1,
        "module": "M7",
        "purpose": "plan",
    }
    assert (
        client.post("/api/memoire-developpement/prompts", json=prompt, headers={"x-csrf-token": csrf}).status_code
        == 200
    )
    current = client.get("/api/memoire-developpement/status").json()["verified"]
    malformed_plans = [
        {"steps": "pas une liste"},
        {"steps": ["pas un objet"]},
        {"steps": [{"id": 4, "description": "type incorrect"}]},
        {"version": True},
        {"prompt_version": False},
        {"files": "fichier.md"},
        {"owners": [3]},
    ]
    plan = {
        "plan_id": "typed-plan",
        "version": 1,
        "module": "M7",
        "prompt_id": "typed-plan-prompt",
        "prompt_version": 1,
        "objective": "plan",
        "steps": [{"id": "step-1", "description": "Inspecter", "statut": "active"}],
        "files": [],
    }
    for mutation in malformed_plans:
        response = client.post(
            "/api/memoire-developpement/plans",
            json=plan | mutation,
            headers={"x-csrf-token": csrf},
        )
        assert response.status_code == 400
        assert client.get("/api/memoire-developpement/status").json()["verified"] == current

    malformed_postflights = [
        {"changes": "fichier.md"},
        {"changes": [{"fichier": 5}]},
        {"tests": "passed"},
        {"report_refs": "reports/run"},
        {"version": True},
        {"claim_key": 4},
    ]
    postflight = {
        "operation_id": "typed-run",
        "module": "M7",
        "plan_id": "typed-plan",
        "status": "done",
        "summary": "Résultat",
        "changes": [],
        "tests": [],
        "report_refs": [],
    }
    for mutation in malformed_postflights:
        response = client.post(
            "/api/memoire-developpement/postflight",
            json=postflight | mutation,
            headers={"x-csrf-token": csrf},
        )
        assert response.status_code == 400
        assert client.get("/api/memoire-developpement/status").json()["verified"] == current


@pytest.mark.parametrize(
    "modification",
    [
        {"options": "une chaîne"},
        {"reasons": [False]},
        {"consequences": [None]},
        {"source_refs": "docs/source.md"},
        {"version": True},
        {"authority": []},
    ],
)
def test_http_refuse_decisions_malformees_sans_ecriture(api, modification):
    client, _, _ = api
    csrf = _connecter(client)
    decision = {
        "decision_id": "typed-decision",
        "version": 1,
        "module": "M7",
        "context": "Contexte",
        "options": ["garder"],
        "reasons": ["preuve"],
        "consequences": ["rappel sourcé"],
        "authority": "admin",
        "source_refs": ["docs/source.md"],
    } | modification
    response = client.post(
        "/api/memoire-developpement/decisions",
        json=decision,
        headers={"x-csrf-token": csrf},
    )
    assert response.status_code == 400
    assert client.get("/api/memoire-developpement/status").json()["verified"] == 0


def test_http_postflight_diagnostic_typé_journalise_et_refuse_schema_malforme(api):
    client, _, _ = api
    csrf = _connecter(client)
    diagnostic = {
        "incident_id": "M10-API-404",
        "symptom": "Le lien attendu est absent.",
        "cause": "La relation cible a été tronquée.",
        "cause_status": "confirmed",
        "prevention": "Citer le chemin exact et surveiller les compteurs.",
        "source_refs": ["core/src/preflight.py"],
        "observed_at": "2026-09-30T15:00:00+00:00",
    }
    command = {
        "operation_id": "api-diagnostic-1",
        "module": "CORE",
        "plan_id": "api-diagnostic-plan",
        "status": "done",
        "summary": "Correctif de récupération",
        "changes": [{"fichier": "core/src/preflight.py", "resume": "Ajoute le diagnostic"}],
        "tests": [{"source": "core/test/preflight.test.ts", "resultat": "passed"}],
        "report_refs": [],
        "diagnostic": diagnostic,
    }
    before = list(stockage.maillons("m10-memoire", "developpement"))
    denied = client.post(
        "/api/memoire-developpement/postflight", json=command, headers={"x-csrf-token": "incorrect"}
    )
    assert denied.status_code == 403
    assert list(stockage.maillons("m10-memoire", "developpement")) == before

    accepted = client.post(
        "/api/memoire-developpement/postflight", json=command, headers={"x-csrf-token": csrf}
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["diagnostic"] == diagnostic
    assert accepted.json()["diagnostic"]["cause_status"] == "confirmed"
    assert accepted.json()["diagnostic_assurance"] == "author_assertion_unverified"
    replay = client.post(
        "/api/memoire-developpement/postflight", json=command, headers={"x-csrf-token": csrf}
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["replayed"] is True
    assert replay.json()["diagnostic_assurance"] == "author_assertion_unverified"
    preflight = client.post(
        "/api/memoire-developpement/preflight",
        json={"module": "CORE", "task": "M10-API-404", "files": ["core/src/preflight.py"]},
    )
    assert preflight.status_code == 200
    candidate = next(item for item in preflight.json()["must_know"] if item["payload"].get("diagnostic"))
    assert candidate["diagnostic_assurance"] == "author_assertion_unverified"

    invalid = client.post(
        "/api/memoire-developpement/postflight",
        json=command | {"operation_id": "api-diagnostic-invalid", "diagnostic": diagnostic | {"unexpected": "x"}},
        headers={"x-csrf-token": csrf},
    )
    assert invalid.status_code == 400
    assert "api-diagnostic-invalid" not in json.dumps(list(stockage.maillons("m10-memoire", "developpement")))
    invalid_time = client.post(
        "/api/memoire-developpement/postflight",
        json=command
        | {
            "operation_id": "api-diagnostic-invalid-time",
            "diagnostic": diagnostic | {"observed_at": "2026-09-30T15:00:00"},
        },
        headers={"x-csrf-token": csrf},
    )
    assert invalid_time.status_code == 400
    assert "api-diagnostic-invalid-time" not in json.dumps(list(stockage.maillons("m10-memoire", "developpement")))

    employee_csrf = _connecter(client, EMPLOYEE, ["employee"])
    maillons_before_denied = list(stockage.maillons("m10-memoire", "developpement"))
    unauthorized = client.post(
        "/api/memoire-developpement/postflight",
        json=command | {"operation_id": "api-diagnostic-unauthorized"},
        headers={"x-csrf-token": employee_csrf},
    )
    assert unauthorized.status_code == 403
    assert list(stockage.maillons("m10-memoire", "developpement")) == maillons_before_denied
