"""Dépôt POSTFLIGHT privé : vrais MCP HTTP/M10/SQLite, données et profil fictifs."""
from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path

import httpx
import pytest
from m10_memoire import outils as outils_m10
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from sqlalchemy import select, update

from opsys import agents, identite, stockage
from opsys.departements import charger_departements
from opsys.serveur_mcp import application_http_departements
from opsys.stockage.schema import AGENTS_CONFIGURABLES, REGISTRES

PUBLIC = "public-postflight-fictif-long-token-01"
RUNTIME = "runtime-postflight-fictif-long-token-01"
PROFILE = "m3-postflight-fictif"
FACT = {"cle": "tc-" + "a" * 40, "outil": "m3_estimer_projet", "resultat": "ok", "code": None}
BASE = {"affaire_id": "lead-postflight-fictif", "faits": [FACT], "horodatage": "2026-10-05T10:00:00+00:00"}


@pytest.fixture
def profile(session, monkeypatch):
    monkeypatch.setenv("OPSYS_EVENEMENTS_REPARTITEUR", "0")
    deps = charger_departements(Path(__file__).resolve().parents[1] / "departments")
    with session() as cnx:
        identite.creer_personne(cnx, "pf-admin", "Admin fictif", "synthetic-password-pf", ["admin"])
        agents.creer(cnx, deps, {
            "id": PROFILE, "departement": "m03-estimation", "responsabilite": "Profil POSTFLIGHT fictif.",
            "palier_modele": "standard", "outils": ["m3_estimer_projet"],
            "budget_jour": 100, "budget_mois": 1_000, "limite_tours": 2,
            "limite_reessais": 1, "limite_concurrence": 1, "declencheurs": [{"type": "manuel"}],
        }, par="pf-admin", mutation_id="pf-create-fictif")
        agents.definir_actif(cnx, PROFILE, deps, True, par="pf-admin", mutation_id="pf-activate-fictif",
                            revision_attendue=1)
        data = agents.obtenir(cnx, PROFILE)
    return deps, data


def app_for(deps, session):
    return application_http_departements(deps, session, PUBLIC, hote="127.0.0.1", jeton_contexte=RUNTIME)


def call(app, args, *, token=RUNTIME, route=f"/mcp/runtime/{PROFILE}", tool="opsys_runtime_deposer_faits"):
    async def run():
        async with (
            httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000",
                              headers={"Authorization": f"Bearer {token}"}) as http,
            app._application.router.lifespan_context(app._application),
            streamable_http_client("http://127.0.0.1:8000" + route, http_client=http) as (read, write),
            ClientSession(read, write) as client,
        ):
            await client.initialize()
            result = await client.call_tool(tool, args)
            return json.loads(result.content[0].text)
    return asyncio.run(run())


def snapshot(session):
    with session() as cnx:
        return {table.name: list(cnx.execute(select(table).order_by(*table.primary_key.columns)))
                for table in (REGISTRES, AGENTS_CONFIGURABLES)}


def rows(session):
    with session():
        return list(stockage.maillons("m10-memoire", "affaires"))


def args_for(profile):
    return copy.deepcopy({**BASE, "revision_profil": profile["revision"]})


def test_real_deposit_replay_after_reopen_and_source_bound_ack(profile, session):
    deps, p = profile
    app = app_for(deps, session)
    first = call(app, args_for(p))
    assert first["ok"] is True
    ack = first["resultat"]
    assert ack["accepte"] is True
    assert ack["source"] == {"profil_id": PROFILE, "revision": p["revision"],
                              "departement": "m03-estimation", "engine_id": "opsys"}
    assert ack["affaire_id"] == BASE["affaire_id"] and ack["cles"] == [FACT["cle"]]
    assert ack["resultat"]["ecrits"] == 1 and ack["resultat"]["deja_deposes"] == 0
    saved = rows(session)
    assert len(saved) == 1 and saved[0]["departement_source"] == "m03-estimation"
    assert saved[0]["cle_depot"] == FACT["cle"] and saved[0]["statut"] == "candidat"
    assert outils_m10._REGISTRE_AFFAIRES.valider_chaine() == (True, "")
    stockage.liberer()
    replay = call(app_for(deps, session), args_for(p))
    assert replay["resultat"]["resultat"] == {"ecrits": 0, "deja_deposes": 1, "lignes": []}
    assert rows(session) == saved


def test_divergent_replay_preserves_first_and_does_not_ack(profile, session):
    deps, p = profile
    app = app_for(deps, session)
    assert call(app, args_for(p))["ok"] is True
    saved = snapshot(session)
    args = args_for(p)
    args["faits"][0]["resultat"] = "refus"
    result = call(app_for(deps, session), args)
    assert result["ok"] is False or result["resultat"]["accepte"] is False
    assert snapshot(session) == saved


@pytest.mark.parametrize("change", ["inactive", "deleted", "missing_tool", "stale_revision"])
def test_live_profile_authority_required(profile, session, change):
    deps, p = profile
    app = app_for(deps, session)
    args = args_for(p)
    with session() as cnx:
        changes = {"inactive": {"actif": False}, "deleted": {"supprime": True},
                   "missing_tool": {"outils": "[]"}, "stale_revision": {"revision": p["revision"] + 1}}
        cnx.execute(update(AGENTS_CONFIGURABLES).where(AGENTS_CONFIGURABLES.c.id == PROFILE)
                    .values(**changes[change]))
    saved = snapshot(session)
    result = call(app, args)
    assert result == {"ok": False, "erreur": "depot_postflight_refuse"}
    assert snapshot(session) == saved


@pytest.mark.parametrize("change", ["other_department", "unknown_tool", "empty", "duplicate", "extra_fact",
                                   "extra_profile", "extra_department", "boolean_revision", "bad_date", "too_many"])
def test_closed_canonical_contract_and_source_tool_allowlist(profile, session, change):
    deps, p = profile
    app = app_for(deps, session)
    args = args_for(p)
    if change == "other_department":
        args["faits"][0]["outil"] = "m5_preparer_facture"
    elif change == "unknown_tool":
        args["faits"][0]["outil"] = "m3_inconnu"
    elif change == "empty":
        args["faits"] = []
    elif change == "duplicate":
        args["faits"] *= 2
    elif change == "extra_fact":
        args["faits"][0]["resultat_metier"] = "secret-fictif-ne-doit-pas-entrer"
    elif change == "extra_profile":
        args["profil_id"] = "other-fictif"
    elif change == "extra_department":
        args["departement"] = "m05-financecore"
    elif change == "boolean_revision":
        args["revision_profil"] = True
    elif change == "bad_date":
        args["horodatage"] = "sans-fuseau"
    else:
        args["faits"] = [{**FACT, "cle": "tc-" + f"{i:040x}"} for i in range(21)]
    saved = snapshot(session)
    assert call(app, args) == {"ok": False, "erreur": "depot_postflight_refuse"}
    assert snapshot(session) == saved


def test_second_write_failure_rolls_back_entire_batch(profile, session, monkeypatch):
    deps, p = profile
    app = app_for(deps, session)
    args = args_for(p)
    args["faits"].append({**FACT, "cle": "tc-" + "b" * 64})
    original = outils_m10._REGISTRE_AFFAIRES.ajouter
    count = 0
    def interrupted(entry):
        nonlocal count
        count += 1
        if count == 2:
            raise RuntimeError("synthetic-write-failure")
        return original(entry)
    monkeypatch.setattr(outils_m10._REGISTRE_AFFAIRES, "ajouter", interrupted)
    saved = snapshot(session)
    assert call(app, args) == {"ok": False, "erreur": "depot_postflight_refuse"}
    assert count == 2 and snapshot(session) == saved


@pytest.mark.parametrize("fault", ["false_count", "boolean_count", "missing_counts", "revoke"])
def test_post_write_validation_rolls_back_without_false_ack(profile, session, monkeypatch, fault):
    deps, p = profile
    app = app_for(deps, session)
    original = outils_m10.deposer_faits_candidats
    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        if fault == "false_count":
            result["resultat"]["ecrits"] = 0
        elif fault == "boolean_count":
            result["resultat"]["ecrits"] = True
        elif fault == "missing_counts":
            result["resultat"] = {}
        else:
            cnx = stockage.connexion_courante()
            cnx.execute(update(AGENTS_CONFIGURABLES).where(AGENTS_CONFIGURABLES.c.id == PROFILE)
                        .values(actif=False))
        return result
    monkeypatch.setattr(outils_m10, "deposer_faits_candidats", changed)
    saved = snapshot(session)
    assert call(app, args_for(p)) == {"ok": False, "erreur": "depot_postflight_refuse"}
    assert snapshot(session) == saved


def test_public_department_does_not_expose_private_deposit(profile, session):
    deps, p = profile
    app = app_for(deps, session)
    assert call(app, args_for(p), token=PUBLIC, route="/mcp/m03-estimation") == {
        "ok": False, "erreur": "outil_inconnu", "details": "opsys_runtime_deposer_faits",
    }


def test_twenty_facts_and_replay_preserve_exact_keys(profile, session):
    deps, p = profile
    args = args_for(p)
    args["faits"] = [{**FACT, "cle": "tc-" + f"{i:064x}"} for i in range(20)]
    result = call(app_for(deps, session), args)
    assert result["resultat"]["cles"] == [fact["cle"] for fact in args["faits"]]
    assert result["resultat"]["resultat"]["ecrits"] == 20
    before = rows(session)
    assert len(before) == 20
    again = call(app_for(deps, session), args)
    assert again["resultat"]["resultat"] == {"ecrits": 0, "deja_deposes": 20, "lignes": []}
    assert rows(session) == before


def test_public_token_cannot_reach_private_runtime(profile, session):
    deps, _ = profile
    app = app_for(deps, session)
    async def rejected():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000",
                                     headers={"Authorization": f"Bearer {PUBLIC}"}) as http:
            return await http.post(f"/mcp/runtime/{PROFILE}", json={})
    saved = snapshot(session)
    assert asyncio.run(rejected()).status_code == 401
    assert snapshot(session) == saved


def test_database_switch_during_deposit_rolls_back(profile, session, monkeypatch, tmp_path):
    deps, p = profile
    app = app_for(deps, session)
    original = outils_m10.deposer_faits_candidats
    saved = snapshot(session)
    with monkeypatch.context() as patch:
        def switched(*args, **kwargs):
            result = original(*args, **kwargs)
            patch.setenv(stockage.ENV_URL, "sqlite:///" + str(tmp_path / "other-fictif.db"))
            return result
        patch.setattr(outils_m10, "deposer_faits_candidats", switched)
        assert call(app, args_for(p)) == {"ok": False, "erreur": "depot_postflight_refuse"}
    assert snapshot(session) == saved


def test_concurrent_same_deposit_then_retry_does_not_duplicate(profile, session):
    deps, p = profile
    app = app_for(deps, session)
    async def together():
        async with (
            httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000",
                              headers={"Authorization": f"Bearer {RUNTIME}"}) as http,
            app._application.router.lifespan_context(app._application),
            streamable_http_client(f"http://127.0.0.1:8000/mcp/runtime/{PROFILE}",
                                   http_client=http) as (read, write),
            ClientSession(read, write) as client,
        ):
            await client.initialize()
            replies = await asyncio.gather(*(client.call_tool("opsys_runtime_deposer_faits", args_for(p))
                                              for _ in range(2)))
            return [json.loads(reply.content[0].text) for reply in replies]
    results = asyncio.run(together())
    assert any(result.get("ok") is True for result in results)
    before = rows(session)
    assert len(before) == 1 and before[0]["cle_depot"] == FACT["cle"]
    retry = call(app_for(deps, session), args_for(p))
    assert retry["resultat"]["resultat"] == {"ecrits": 0, "deja_deposes": 1, "lignes": []}
    assert rows(session) == before and outils_m10._REGISTRE_AFFAIRES.valider_chaine() == (True, "")
