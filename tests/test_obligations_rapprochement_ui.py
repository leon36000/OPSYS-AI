"""Tests candidats HTTP privés; non exécutés par le sous-agent."""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from opsys import identite, stockage
from opsys.console import obligations_privees as op
from opsys.console import obligations_rapprochement_ui as ui
from opsys.console.securite import Session

_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))
import test_console_paie as paie_test  # noqa: E402
from test_console_paie import OWNER  # noqa: E402

client_paie = paie_test.client_paie

FICTIF = True
CSRF = "token-csrf-fictif-stable"
FINANCE = "finance-rapprochement-fictif"
FINANCE_PASSWORD = "finance-rapprochement-fictif-password"


def _obligation(amount="1250.00"):
    return {
        "type": "paies", "montant_cad": amount,
        "periode_debut": "2026-09-01", "periode_fin": "2026-09-15",
        "date_paie": "2026-09-18", "echeance": "2026-09-21",
        "reference_piece": "paie-fictive", "autorite": "source déclarée fictive",
        "source_consultee_le": "2026-09-17", "applicable_du": "2026-01-01",
        "applicable_au": "2026-12-31", "version": "déclarée-2026",
    }


def _capture():
    catalog = {"legacy": {"paies": {"sha256": "1" * 64, "montant_cad": "1250.00"}},
               "provisions": {}}
    def builder(obligations_sha256):
        return {
            "finance_snapshot_id": hashlib.sha256(("snapshot-fictif" + obligations_sha256).encode()).hexdigest(),
            "obligations_sha256": obligations_sha256,
            "sources": catalog,
        }
    return SimpleNamespace(sources=catalog, snapshot_builder=builder, verifier_sources_courantes=lambda: True)


def _finance_module():
    return SimpleNamespace(
        capturer_snapshot_prive=lambda _cnx: _capture(),
        calculer_capture_privee=lambda capture, projection: {
            **projection,
            "finance_snapshot_id": capture.snapshot_builder(projection["obligations_sha256"])["finance_snapshot_id"],
        },
    )


@pytest.fixture
def client_rapprochement(client_paie, session):
    from datetime import UTC, datetime, timedelta
    csrf_session = Session(OWNER, frozenset({"nathan_owner", "admin"}), CSRF,
                           int((datetime.now(UTC) + timedelta(hours=2)).timestamp()))
    app = FastAPI()
    async def form(request):
        return dict(await request.form())
    app.include_router(ui.creer_router(
        session_page=lambda _request, administrateur=False: csrf_session,
        formulaire=form, cnx_factory=session, journal=op, finance_snapshot=_finance_module(), prefixe="",
    ))
    with TestClient(app, base_url="http://testserver") as client:
        yield client


def _ajouter_obligation(session):
    with session() as cnx:
        op.ajouter(cnx, _obligation(), revision_attendue=0, mutation_id="a" * 32,
                   confirme_par=OWNER, confirme_le="2026-10-03T12:00:00+00:00", verifier_acteur=lambda *_: None)


def _form_body(cnx, *, csrf=CSRF, snapshot_id=None, revision="1", extra=None):
    state = op.lire(cnx)
    builder = _capture().snapshot_builder
    snapshot_id = snapshot_id or builder(op._empreinte_obligations(state))["finance_snapshot_id"]
    result = {
        "action": "LEGACY_IDENTIQUE", "obligation_id": "a" * 32, "source_ref": "paies",
        "montant_cad": "1250.00", "revision_attendue": revision,
        "snapshot_id_attendu": snapshot_id, "mutation_id": "b" * 32, "csrf": csrf,
    }
    result.update(extra or {})
    return result


def test_route_html_humaine_no_store_et_rapprochement_cas(client_rapprochement, session):
    _ajouter_obligation(session)
    page = client_rapprochement.get("/finance/paie/rapprochements")
    assert page.status_code == 200
    assert "no-store" in page.headers["cache-control"]
    assert "paiement bancaire" in page.text
    with session() as cnx:
        body = _form_body(cnx)
    retour = client_rapprochement.post("/finance/paie/rapprochements", data=body, follow_redirects=False)
    assert retour.status_code == 303
    assert "no-store" in retour.headers["cache-control"]
    assert len(stockage.maillons(op.DEPARTEMENT, op.REGISTRE)) == 2
    get_apres = client_rapprochement.get("/finance/paie/rapprochements")
    assert "État actuel : CONNU" in get_apres.text
    assert "paiement bancaire" in get_apres.text


def test_csrf_champs_extra_query_et_snapshot_stale_refuses(client_rapprochement, session):
    _ajouter_obligation(session)
    with session() as cnx:
        body = _form_body(cnx)
    assert client_rapprochement.get("/finance/paie/rapprochements?montant=1").status_code == 400
    assert client_rapprochement.post("/finance/paie/rapprochements?x=1", data=body).status_code == 400
    assert client_rapprochement.post("/finance/paie/rapprochements", data={**body, "csrf": "bad"}).status_code == 403
    assert client_rapprochement.post("/finance/paie/rapprochements", data={**body, "x": "inattendu"}).status_code == 400
    stale = {**body, "snapshot_id_attendu": "0" * 64, "mutation_id": "c" * 32}
    assert client_rapprochement.post("/finance/paie/rapprochements", data=stale).status_code == 409
    assert len(stockage.maillons(op.DEPARTEMENT, op.REGISTRE)) == 1


def test_role_non_finance_refuse_avant_capture(client_paie, session, monkeypatch):
    with session() as cnx:
        identite.creer_personne(cnx, "admin-only-reconcile", "Admin fictif", "admin-only-password", ["admin"])
    from datetime import UTC, datetime, timedelta
    admin_session = Session("admin-only-reconcile", frozenset({"admin"}), CSRF,
                            int((datetime.now(UTC) + timedelta(hours=2)).timestamp()))
    called = False
    def capture(_cnx):
        nonlocal called
        called = True
        return _capture()
    app = FastAPI()
    app.include_router(ui.creer_router(
        session_page=lambda *_args, **_kwargs: admin_session, formulaire=lambda _request: {},
        cnx_factory=session, journal=op, finance_snapshot=SimpleNamespace(capturer_snapshot_prive=capture), prefixe="",
    ))
    with TestClient(app) as client:
        assert client.get("/finance/paie/rapprochements").status_code == 403
    assert called is False


def test_retrait_role_pendant_chiffrement_ne_persiste_pas(client_rapprochement, session, monkeypatch):
    _ajouter_obligation(session)
    with session() as cnx:
        body = _form_body(cnx)
    aead_reel = op._aead()
    class AeadAvecRetrait:
        def __init__(self, key):
            self.aes = aead_reel(key)
        def decrypt(self, nonce, ciphertext, aad):
            return self.aes.decrypt(nonce, ciphertext, aad)
        def encrypt(self, nonce, clair, aad):
            cipher = self.aes.encrypt(nonce, clair, aad)
            current = stockage.connexion_courante()
            assert current is not None
            identite.retirer_role(current, OWNER, "nathan_owner")
            return cipher
    monkeypatch.setattr(op, "_aead", lambda: AeadAvecRetrait)
    retour = client_rapprochement.post("/finance/paie/rapprochements", data=body)
    assert retour.status_code == 403
    assert len(stockage.maillons(op.DEPARTEMENT, op.REGISTRE)) == 1


def test_role_finance_actif_peut_lire_la_route_privee(client_paie, session):
    with session() as cnx:
        identite.creer_personne(cnx, FINANCE, "Finance fictive", FINANCE_PASSWORD, ["finance"])
    from datetime import UTC, datetime, timedelta
    finance_session = Session(FINANCE, frozenset({"finance"}), CSRF,
                              int((datetime.now(UTC) + timedelta(hours=2)).timestamp()))
    app = FastAPI()
    app.include_router(ui.creer_router(
        session_page=lambda *_args, **_kwargs: finance_session, formulaire=lambda _request: {},
        cnx_factory=session, journal=op, finance_snapshot=_finance_module(), prefixe="",
    ))
    with TestClient(app) as client:
        response = client.get("/finance/paie/rapprochements")
    assert response.status_code == 200
    assert "no-store" in response.headers["cache-control"]


def test_sources_fichier_modifiees_pendant_chiffrement_refuse_sans_append(client_paie, session, monkeypatch):
    _ajouter_obligation(session)
    from datetime import UTC, datetime, timedelta
    csrf_session = Session(OWNER, frozenset({"nathan_owner", "admin"}), CSRF,
                           int((datetime.now(UTC) + timedelta(hours=2)).timestamp()))
    capture = _capture()
    state = {"sources_valides": True}
    capture.verifier_sources_courantes = lambda: state["sources_valides"]
    finance = SimpleNamespace(
        capturer_snapshot_prive=lambda _cnx: capture,
        calculer_capture_privee=lambda current, projection: {
            **projection,
            "finance_snapshot_id": current.snapshot_builder(projection["obligations_sha256"])["finance_snapshot_id"],
        },
    )
    app = FastAPI()
    async def form(request):
        return dict(await request.form())
    app.include_router(ui.creer_router(
        session_page=lambda _request, administrateur=False: csrf_session,
        formulaire=form, cnx_factory=session, journal=op, finance_snapshot=finance, prefixe="",
    ))
    with TestClient(app, base_url="http://testserver") as client:
        with session() as cnx:
            body = _form_body(cnx)
        aead_reel = op._aead()
        class AeadAvecChangementSource:
            def __init__(self, key):
                self.aes = aead_reel(key)
            def decrypt(self, nonce, ciphertext, aad):
                return self.aes.decrypt(nonce, ciphertext, aad)
            def encrypt(self, nonce, clair, aad):
                cipher = self.aes.encrypt(nonce, clair, aad)
                state["sources_valides"] = False
                return cipher
        monkeypatch.setattr(op, "_aead", lambda: AeadAvecChangementSource)
        response = client.post("/finance/paie/rapprochements", data=body)
    assert response.status_code == 409
    assert len(stockage.maillons(op.DEPARTEMENT, op.REGISTRE)) == 1
