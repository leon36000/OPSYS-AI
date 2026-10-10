"""Fermeture du nom générique SMS aux deux frontières réelles ; données fictives."""
from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import json
from pathlib import Path

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from sqlalchemy import MetaData, Table, select, update

from opsys import admission_agents, agents, departements, identite
from opsys.capacites import Capacites
from opsys.serveur_mcp import application_http_departements
from opsys.stockage import schema

PROFILE = "m01-sms-guard"
TOOL = "m1_recevoir_message_canal"
FULL_TOOL = "opsys_m1__" + TOOL
ADMIN = "sms-guard-admin-fictif"
PUBLIC = "sms-guard-public-fictif-token-long-01"
PRIVATE = "sms-guard-private-fictif-token-long-01"
TRIGGER = {"type": "canal", "version": 1, "canal": "sms", "compte_id": "default",
           "account_sid": "AC" + "1234567890abcdef" * 2}
PROOF_WINDOWS = []


def _sql_encoder(value):
    if isinstance(value, (dt.date, dt.datetime)):
        return {"date": value.isoformat()}
    if isinstance(value, (bytes, memoryview)):
        return {"bytes": bytes(value).hex()}
    raise TypeError("type SQL non pris en charge")


def snapshot(session):
    with session() as cnx:
        result = {}
        for name in cnx.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").scalars():
            table = schema.META.tables.get(name)
            if table is None:
                table = Table(name, MetaData(), autoload_with=cnx)
            rows = [json.dumps(dict(row), ensure_ascii=False, sort_keys=True, allow_nan=False, default=_sql_encoder)
                    for row in cnx.execute(select(table)).mappings()]
            result[name] = {"count": len(rows), "sha256": hashlib.sha256(
                json.dumps(sorted(rows), ensure_ascii=False).encode()).hexdigest()}
        return result


def no_changes(before, after):
    PROOF_WINDOWS.append({"before": before, "after": after})
    assert before == after


@pytest.fixture
def profile(session, monkeypatch):
    monkeypatch.setenv("OPSYS_EVENEMENTS_REPARTITEUR", "0")
    deps = departements.charger_departements(Path(__file__).resolve().parents[1] / "departments")
    with session() as cnx:
        identite.creer_personne(cnx, ADMIN, "Admin fictif", "mot-de-passe-sms-guard-fictif", ["admin"])
        agents.creer(cnx, deps, {
            "id": PROFILE, "departement": "m01-front-office", "responsabilite": "Accueil fictif SMS.",
            "palier_modele": "rapide", "outils": [TOOL], "budget_jour": 1000, "budget_mois": 10000,
            "limite_tours": 3, "limite_reessais": 1, "limite_concurrence": 1,
            "declencheurs": [dict(TRIGGER)],
        }, par=ADMIN, mutation_id="guard-sms-create-01")
        active = agents.definir_actif(cnx, PROFILE, deps, True, par=ADMIN,
                                     mutation_id="guard-sms-activate-01", revision_attendue=1)
    return deps, active


@pytest.mark.parametrize("channel", ["sms", "formulaire", "courriel", None])
def test_cap_denies_generic_name_before_any_business_dispatch(profile, session, monkeypatch, channel):
    deps, p = profile
    cap = Capacites(deps, session, filtre={"m01-front-office"}, appelant="m01-front-office")
    calls = []

    def dispatch(*args):
        calls.append(args)
        return {"ok": True, "resultat": {"espion_fictif": True}}

    monkeypatch.setattr(cap, "appeler", dispatch)
    before = snapshot(session)
    args = {} if channel is None else {"canal": channel}
    result = cap.appeler_profil_runtime(TOOL, args, None, None, profile_id=PROFILE,
                                       profile_revision=p["revision"], server="opsys_m1")
    assert result["ok"] is False and result["erreur"] == "admission_profil_refusee"
    assert calls == []
    no_changes(before, snapshot(session))


def _http_verify(app, revision, *, token=PRIVATE):
    async def run():
        async with (
            httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000",
                              headers={"Authorization": f"Bearer {token}"}) as http,
            app._application.router.lifespan_context(app._application),
            streamable_http_client(f"http://127.0.0.1:8000/mcp/runtime/{PROFILE}", http_client=http) as flux,
            ClientSession(flux[0], flux[1]) as client,
        ):
            await client.initialize()
            response = await client.call_tool("opsys_runtime_verifier_outil",
                                              {"outil": FULL_TOOL, "revision_profil": revision})
            return json.loads(response.content[0].text)
    return asyncio.run(run())


def test_actual_private_mcp_generic_verifier_denies_but_native_permission_remains(profile, session):
    deps, p = profile
    app = application_http_departements(deps, session, PUBLIC, hote="127.0.0.1", jeton_contexte=PRIVATE)
    before = snapshot(session)
    assert _http_verify(app, p["revision"])["ok"] is False
    with session() as cnx:
        assert admission_agents.verifier_outil_runtime(cnx, PROFILE, deps, FULL_TOOL, p["revision"]) == {
            "autorise": True, "revision_profil": p["revision"]}
    no_changes(before, snapshot(session))


@pytest.mark.parametrize("raw", ["null", "{}", "not-json", "[]", json.dumps([{**TRIGGER, "version": True}]),
                               json.dumps([{**TRIGGER, "compte_id": "Default"}]),
                               json.dumps([{**TRIGGER, "extra": "fictif"}]),
                               json.dumps([TRIGGER, {"type": "manuel"}])])
def test_corrupt_current_trigger_never_falls_back_to_generic(profile, session, monkeypatch, raw):
    deps, p = profile
    with session() as cnx:
        cnx.execute(update(schema.AGENTS_CONFIGURABLES).where(schema.AGENTS_CONFIGURABLES.c.id == PROFILE)
                    .values(declencheurs=raw))
    cap = Capacites(deps, session, filtre={"m01-front-office"}, appelant="m01-front-office")
    calls = []
    monkeypatch.setattr(cap, "appeler", lambda *args: calls.append(args) or {"ok": True})
    before = snapshot(session)
    response = cap.appeler_profil_runtime(TOOL, {}, None, None, profile_id=PROFILE,
                                         profile_revision=p["revision"], server="opsys_m1")
    assert response["ok"] is False and calls == []
    no_changes(before, snapshot(session))


def test_legacy_manual_receiver_dispatch_and_native_dto_remain(profile, session, monkeypatch):
    deps, p = profile
    with session() as cnx:
        current = agents.obtenir(cnx, PROFILE)
        spec = {key: current[key] for key in ("id", "departement", "responsabilite", "palier_modele", "outils",
                "budget_jour", "budget_mois", "limite_tours", "limite_reessais", "limite_concurrence", "declencheurs")}
        spec["declencheurs"] = [{"type": "manuel"}]
        legacy = agents.modifier(cnx, PROFILE, deps, spec, par=ADMIN, mutation_id="guard-to-manual-01",
                                revision_attendue=p["revision"])
    cap = Capacites(deps, session, filtre={"m01-front-office"}, appelant="m01-front-office")
    calls = []
    monkeypatch.setattr(cap, "appeler", lambda *args: calls.append(args) or {"ok": True, "espion_fictif": True})
    before = snapshot(session)
    response = cap.appeler_profil_runtime(TOOL, {"canal": "formulaire"}, None, None, profile_id=PROFILE,
                                         profile_revision=legacy["revision"], server="opsys_m1")
    assert response == {"ok": True, "espion_fictif": True} and len(calls) == 1
    app = application_http_departements(deps, session, PUBLIC, hote="127.0.0.1", jeton_contexte=PRIVATE)
    assert _http_verify(app, legacy["revision"]) == {"ok": True, "resultat": {
        "autorise": True, "revision_profil": legacy["revision"]}}
    no_changes(before, snapshot(session))


@pytest.mark.parametrize("change,revision,server", [
    ({}, 1, "opsys_m1"),
    ({}, 2, "opsys_m7"),
    ({"actif": False}, 2, "opsys_m1"),
    ({"supprime": True}, 2, "opsys_m1"),
    ({"outils": "[]"}, 2, "opsys_m1"),
    ({"revision": 3}, 2, "opsys_m1"),
])
def test_current_authority_guards_remain_before_dispatch(profile, session, monkeypatch, change, revision, server):
    deps, _ = profile
    if change:
        with session() as cnx:
            cnx.execute(update(schema.AGENTS_CONFIGURABLES).where(schema.AGENTS_CONFIGURABLES.c.id == PROFILE)
                        .values(**change))
    cap = Capacites(deps, session, filtre={"m01-front-office"}, appelant="m01-front-office")
    calls = []
    monkeypatch.setattr(cap, "appeler", lambda *args: calls.append(args) or {"ok": True})
    before = snapshot(session)
    result = cap.appeler_profil_runtime(TOOL, {}, None, None, profile_id=PROFILE,
                                       profile_revision=revision, server=server)
    assert result["ok"] is False and result["erreur"] == "admission_profil_refusee"
    assert calls == []
    no_changes(before, snapshot(session))
