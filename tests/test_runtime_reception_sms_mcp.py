"""Réception privée via vrai SDK/HTTP ASGI ; données et jetons fictifs."""
from __future__ import annotations

import asyncio
import copy
import json
from contextlib import contextmanager

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from tests.test_reception_sms_receipt import arguments, census
from tests.test_reception_sms_receipt import instance as instance

from opsys import agents, reception_sms_receipt
from opsys.reception_sms_runtime import valider_commande
from opsys.serveur_mcp import application_http_departements

LIRE = "opsys_runtime_lire_reception_sms"
RECEVOIR = "opsys_runtime_recevoir_sms"
PUBLIC = "sms-rpc-public-fictif-token-long-001"
PRIVATE = "sms-rpc-private-fictif-token-long-001"
WINDOWS = []


@pytest.fixture(autouse=True)
def _tracer_windows(request, monkeypatch):
    monkeypatch.setenv("OPSYS_EVENEMENTS_REPARTITEUR", "0")
    start = len(WINDOWS)
    yield
    request.node.user_properties.append(("sms_rpc_sql_windows", json.dumps(WINDOWS[start:], sort_keys=True)))


def snapshot(session):
    with session() as cnx:
        return census(cnx)


def comparer(before, after, *, changes=frozenset()):
    changed = {name for name in before if before[name] != after[name]}
    assert before.keys() == after.keys() and changed == changes
    WINDOWS.append({"before": {n: {"count": v["nombre"], "sha256": v["sha256"]} for n, v in before.items()},
                    "after": {n: {"count": v["nombre"], "sha256": v["sha256"]} for n, v in after.items()},
                    "changed": sorted(changed)})


def application(instance, *, factory=None):
    session, _, deps = instance
    return application_http_departements(deps, factory or session, PUBLIC, hote="127.0.0.1",
                                         jeton_contexte=PRIVATE)


def rpc(app, profile, name, args, *, meta=None, token=PRIVATE):
    return rpc_many(app, profile, [(name, args, meta)], token=token)[0]


def rpc_many(app, profile, calls, *, token=PRIVATE):
    async def run():
        async with (
            httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000",
                              headers={"Authorization": f"Bearer {token}"}) as http,
            app._application.router.lifespan_context(app._application),
            streamable_http_client(f"http://127.0.0.1:8000/mcp/runtime/{profile}", http_client=http) as flux,
            ClientSession(flux[0], flux[1]) as client,
        ):
            await client.initialize()
            try:
                return [await client.call_tool(name, args, meta=meta) for name, args, meta in calls]
            except Exception as exc:
                return exc
    results = asyncio.run(run())
    if isinstance(results, Exception):
        raise results
    acks = []
    for result in results:
        assert len(result.content) == 1 and result.content[0].type == "text"
        data = result.content[0].text.encode("utf-8")
        assert len(data) <= 8192
        ack = json.loads(data)
        assert result.is_error is (ack["ok"] is False)
        acks.append(ack)
    return acks


def test_reception_T0_reel_rejeu_et_lire_sans_mutation(instance):
    session, profile, _ = instance
    app = application(instance)
    args = arguments(profile)
    before = snapshot(session)
    absent = rpc(app, profile["id"], LIRE, args)
    assert absent["etat"] == "absent" and absent["recu"] is None and absent["ok"]
    comparer(before, snapshot(session))
    first = rpc(application(instance), profile["id"], RECEVOIR, args)
    assert first["ok"] and first["recu"]["decision"] == "TRANSMETTRE_M2"
    stable = snapshot(session)
    comparer(before, stable, changes={"registres_maillons", "evenements_sortants"})
    for name in (LIRE, RECEVOIR):
        ack = rpc(application(instance), profile["id"], name, args)
        assert set(ack) == {"version", "operation", "ok", "etat", "intention_id", "commande_sha256",
                            "arguments_sha256", "permission", "recu"}
        assert ack["recu"] == first["recu"] and ack["intention_id"] == first["intention_id"]
        assert ack["arguments_sha256"] == valider_commande(args, operation=name).arguments_sha256
        comparer(stable, snapshot(session))


@pytest.mark.parametrize("name", [LIRE, RECEVOIR])
def test_profil_de_route_fixe_refuse_avant_backend(instance, monkeypatch, name):
    session, profile, deps = instance
    with session() as cnx:
        spec = {key: profile[key] for key in ("departement", "responsabilite", "palier_modele", "outils",
            "budget_jour", "budget_mois", "limite_tours", "limite_reessais", "limite_concurrence")}
        spec.update(id="m01-autre-profil", declencheurs=[{**profile["declencheurs"][0], "compte_id": "cabinet-2"}])
        other = agents.creer(cnx, deps, spec, par="admin.sms.fictif", mutation_id="rpc-creer-autre-0001")
        other = agents.definir_actif(cnx, other["id"], deps, True, par="admin.sms.fictif",
                                    mutation_id="rpc-activer-autre-0001", revision_attendue=1)
    args = arguments(other)
    args["commande"]["compte_id"] = "cabinet-2"
    valider_commande(args, operation=name)
    from m1_front_office import outils as m1

    with session() as cnx:
        assert reception_sms_receipt.executer(cnx, args, operation=LIRE, m1=m1)["etat"] == "absent"
    calls = []
    monkeypatch.setattr(reception_sms_receipt, "executer", lambda *a, **k: calls.append((a, k)))
    before = snapshot(session)
    ack = rpc(application(instance), profile["id"], name, args)
    assert ack == {"version": 1, "operation": "lire" if name == LIRE else "recevoir", "ok": False,
                   "etat": "refus", "code": "REJ-M1-SMS-AUTORITE-REFUSEE"}
    assert calls == []
    comparer(before, snapshot(session))


@pytest.mark.parametrize("meta", [{"opsys/idempotencyKey": "fictif"}, {"opsys/actor": "admin.forge"},
                                  {"opsys/runtimeProfileId": "m01-autre"}, {"opsys/cfoGrantTicket": "fictif"},
                                  {"opsys/deviceId": "fictif"}, {"fictif/extra": True}])
def test_meta_non_protocolaire_refuse_sans_backend(instance, monkeypatch, meta):
    session, profile, _ = instance
    calls = []
    monkeypatch.setattr(reception_sms_receipt, "executer", lambda *a, **k: calls.append((a, k)))
    before = snapshot(session)
    ack = rpc(application(instance), profile["id"], LIRE, arguments(profile), meta=meta)
    assert set(ack) == {"version", "operation", "ok", "etat", "code"}
    assert ack["etat"] == "forme_invalide" and not ack["ok"] and calls == []
    comparer(before, snapshot(session))


@pytest.mark.parametrize("change", ["extra", "bool_revision", "oversize_text", "unicode_phone"])
def test_malformed_arguments_sous_vrai_SDK_sans_backend(instance, monkeypatch, change):
    session, profile, _ = instance
    args = copy.deepcopy(arguments(profile))
    if change == "extra":
        args["acteur"] = "admin.forge"
    elif change == "bool_revision":
        args["permission"]["revision_profil"] = True
    elif change == "oversize_text":
        args["commande"]["texte"] = "é" * 10001
    else:
        args["commande"]["expediteur"] = "+１５１４５５５０１４２"
    calls = []
    monkeypatch.setattr(reception_sms_receipt, "executer", lambda *a, **k: calls.append((a, k)))
    before = snapshot(session)
    ack = rpc(application(instance), profile["id"], RECEVOIR, args)
    assert ack["etat"] == "forme_invalide" and not ack["ok"] and calls == []
    comparer(before, snapshot(session))


def test_revision_perimee_avant_contenu_R_sur_HTTP(instance, monkeypatch):
    session, profile, deps = instance
    args = arguments(profile)
    assert rpc(application(instance), profile["id"], RECEVOIR, args)["ok"]
    app = application(instance)
    with session() as cnx:
        agents.definir_actif(cnx, profile["id"], deps, False, par="admin.sms.fictif",
                            mutation_id="rpc-retirer-sms-0001", revision_attendue=profile["revision"])
    from m1_front_office import outils as m1

    def forbidden():
        raise AssertionError("Aucune lecture R après P périmée")

    monkeypatch.setattr(m1, "registre_sms_hote", forbidden)
    before = snapshot(session)
    for ack in rpc_many(app, profile["id"], [(LIRE, args, None), (RECEVOIR, args, None)]):
        assert not ack["ok"] and ack["etat"] == "revision_perimee" and "recu" not in ack
    comparer(before, snapshot(session))


def test_echec_apres_commit_retient_intention_et_reprise_T0(instance):
    session, profile, _ = instance
    app = application(instance)
    args = arguments(profile)
    before = snapshot(session)

    @contextmanager
    def ack_perdu():
        with session() as cnx:
            yield cnx
        raise OSError("réponse perdue fictive après commit")

    # La factory d'application capture les routes durant sa construction : installer
    # la panne seulement après cette lecture, par fermeture mutable propre à ce test.
    active = [False]

    @contextmanager
    def factory():
        with (ack_perdu() if active[0] else session()) as cnx:
            yield cnx

    broken = application(instance, factory=factory)
    active[0] = True
    unknown = rpc(broken, profile["id"], RECEVOIR, args)
    assert unknown == {"version": 1, "operation": "recevoir", "ok": False,
                       "etat": "inconnu", "code": "M1-SMS-INCONNU"}
    stable = snapshot(session)
    comparer(before, stable, changes={"registres_maillons", "evenements_sortants"})
    ack = rpc(app, profile["id"], LIRE, args)
    assert ack["ok"] and ack["etat"] == "recu"
    assert ack["intention_id"] == valider_commande(args, operation=LIRE).intention_id
    assert rpc(application(instance), profile["id"], RECEVOIR, args)["recu"] == ack["recu"]
    comparer(stable, snapshot(session))


def test_catalogues_prive_et_public_reels(instance):
    session, profile, _ = instance
    app = application(instance)

    async def run():
        lists = {}
        async with app._application.router.lifespan_context(app._application):
            for path, token in [("/mcp", PUBLIC), ("/mcp/m01-front-office", PUBLIC),
                                ("/mcp/runtime/" + profile["id"], PRIVATE)]:
                async with (
                    httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000",
                                      headers={"Authorization": f"Bearer {token}"}) as http,
                    streamable_http_client("http://127.0.0.1:8000" + path, http_client=http) as flux,
                    ClientSession(flux[0], flux[1]) as client,
                ):
                    await client.initialize()
                    lists[path] = (await client.list_tools()).model_dump(by_alias=True)
        return lists

    before = snapshot(session)
    lists = asyncio.run(run())
    for path in ("/mcp", "/mcp/m01-front-office"):
        assert {LIRE, RECEVOIR}.isdisjoint(t["name"] for t in lists[path]["tools"])
    tools = {t["name"]: t for t in lists["/mcp/runtime/" + profile["id"]]["tools"]}
    for name in (LIRE, RECEVOIR):
        schema = tools[name]["inputSchema"]
        assert set(schema["properties"]) == set(schema["required"]) == {"version", "commande", "permission"}
        assert schema["additionalProperties"] is False
        assert len(schema["properties"]["commande"]["required"]) == 12
        assert len(schema["properties"]["permission"]["required"]) == 3
    comparer(before, snapshot(session))


@pytest.mark.parametrize("token", [PUBLIC, "sms-rpc-mauvais-fictif-token-001", None])
def test_route_privee_auth_HTTP_refuse_avant_dispatch(instance, monkeypatch, token):
    session, profile, _ = instance
    app = application(instance)
    calls = []
    monkeypatch.setattr(reception_sms_receipt, "executer", lambda *a, **k: calls.append((a, k)))

    async def run():
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000") as http:
            return await http.post("/mcp/runtime/" + profile["id"], headers=headers,
                                   json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                         "params": {"name": RECEVOIR, "arguments": arguments(profile)}})

    before = snapshot(session)
    response = asyncio.run(run())
    assert response.status_code == 401 and calls == []
    assert "preuve_sha256" not in response.text and profile["id"] not in response.text
    comparer(before, snapshot(session))


def test_encodage_transport_trop_grand_apres_pipeline_annule_tout(instance, monkeypatch):
    session, profile, _ = instance
    original = reception_sms_receipt.executer
    observed = []

    def altered(*a, **kw):
        ack = original(*a, **kw)
        observed.append(ack["recu"])
        return {**ack, "extra_fictif": "é" * 8192}

    monkeypatch.setattr(reception_sms_receipt, "executer", altered)
    before = snapshot(session)
    ack = rpc(application(instance), profile["id"], RECEVOIR, arguments(profile))
    assert observed[0]["signal_ligne_id"] and ack["etat"] == "inconnu" and not ack["ok"]
    comparer(before, snapshot(session))


def raw_rpc(app, profile, name, args, meta):
    """JSON bytes préservés, headers de session/protocole observés sur initialize réel."""
    async def run():
        observed = {}

        async def observe(response):
            session_id = response.headers.get("mcp-session-id")
            if session_id:
                observed["Mcp-Session-Id"] = session_id

        async with (
            httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000",
                              headers={"Authorization": f"Bearer {PRIVATE}"},
                              event_hooks={"response": [observe]}) as http,
            app._application.router.lifespan_context(app._application),
            streamable_http_client(f"http://127.0.0.1:8000/mcp/runtime/{profile}", http_client=http) as flux,
            ClientSession(flux[0], flux[1]) as client,
        ):
            initialized = await client.initialize()
            body = json.dumps({"jsonrpc": "2.0", "id": 9001, "method": "tools/call",
                               "params": {"name": name, "arguments": args, "_meta": meta}}, ensure_ascii=False)
            response = await http.post("/mcp/runtime/" + profile, content=body.encode("utf-8"), headers={
                **observed, "MCP-Protocol-Version": initialized.protocol_version,
                "Accept": "application/json, text/event-stream", "Content-Type": "application/json"})
            return response, body
    response, body = asyncio.run(run())
    assert response.status_code == 200
    if response.headers["content-type"].startswith("application/json"):
        envelope = response.json()
    else:
        envelopes = [json.loads(line[5:].strip()) for line in response.text.splitlines() if line.startswith("data:")]
        envelope = next(item for item in envelopes if item.get("id") == 9001)
    return envelope, body


def test_meta_NULL_raw_preservee_refuse_avant_backend(instance, monkeypatch):
    session, profile, _ = instance
    calls = []
    monkeypatch.setattr(reception_sms_receipt, "executer", lambda *a, **k: calls.append((a, k)))
    before = snapshot(session)
    wire, sent = raw_rpc(application(instance), profile["id"], LIRE, arguments(profile),
                         {"opsys/idempotencyKey": None})
    assert '"opsys/idempotencyKey": null' in sent
    ack = json.loads(wire["result"]["content"][0]["text"])
    assert ack["etat"] == "forme_invalide" and not ack["ok"] and calls == []
    comparer(before, snapshot(session))


def test_progressToken_raw_protocolaire_accepte_sans_autorite(instance):
    session, profile, _ = instance
    before = snapshot(session)
    wire, sent = raw_rpc(application(instance), profile["id"], LIRE, arguments(profile),
                         {"progressToken": "progress-sms-fictif"})
    assert '"progressToken"' in sent
    ack = json.loads(wire["result"]["content"][0]["text"])
    assert ack["ok"] and ack["etat"] == "absent"
    comparer(before, snapshot(session))


@pytest.mark.parametrize("args", [None, [], {"version": 1}])
def test_params_raw_invalides_distinction_SDK_et_codec(instance, monkeypatch, args):
    session, profile, _ = instance
    calls = []
    monkeypatch.setattr(reception_sms_receipt, "executer", lambda *a, **k: calls.append((a, k)))
    before = snapshot(session)
    wire, _ = raw_rpc(application(instance), profile["id"], RECEVOIR, args, {})
    if isinstance(args, list):
        assert wire["error"]["code"] == -32602
        assert "preuve_sha256" not in wire["error"]["message"]
    else:
        ack = json.loads(wire["result"]["content"][0]["text"])
        assert ack["etat"] == "forme_invalide" and not ack["ok"]
    assert calls == []
    comparer(before, snapshot(session))


def test_exception_avant_commit_annule_pipeline_et_constante_sans_details(instance):
    session, profile, _ = instance
    active = [False]
    candidate = []

    @contextmanager
    def factory():
        with session() as cnx:
            yield cnx
            if active[0]:
                candidate.append(census(cnx))
                raise OSError("TRACE-fictive-privee-SMS-commit")

    app = application(instance, factory=factory)
    before = snapshot(session)
    active[0] = True
    ack = rpc(app, profile["id"], RECEVOIR, arguments(profile))
    assert ack == {"version": 1, "operation": "recevoir", "ok": False,
                   "etat": "inconnu", "code": "M1-SMS-INCONNU"}
    assert candidate[0]["registres_maillons"]["nombre"] == before["registres_maillons"]["nombre"] + 3
    comparer(before, snapshot(session))


def test_sept_decisions_metier_via_transport_reel(instance):
    import yaml
    from m1_front_office import outils as m1
    from tests.test_reception_sms_receipt import M1

    from opsys import taxonomie

    session, profile, _ = instance
    taxonomie.enregistrer_fenetre_conversation(30)
    corpus = yaml.safe_load((M1 / "fixtures/plaintes/plaintes.v1.yaml").read_text())
    plainte = next(c for c in corpus["plaintes"] if "securite" not in c["categories"])["texte"]
    urgence = next(c for c in corpus["urgences"] if "securite" in c["categories"])["texte"]
    samples = [arguments(profile, 1, "Bonjour."), arguments(profile, 2), arguments(profile, 3, "Merci!"),
               arguments(profile, 4, "STOP"), arguments(profile, 5, plainte, "+15145550143"),
               arguments(profile, 6, "Merci", "+15145550143"), arguments(profile, 7, urgence, "+15145550144")]
    before = snapshot(session)
    acks = rpc_many(application(instance), profile["id"], [(RECEVOIR, a, None) for a in samples])
    assert all(a["ok"] for a in acks)
    assert [a["recu"]["decision"] for a in acks] == [
        "DEMANDER_PRECISIONS", "TRANSMETTRE_M2", "CONVERSATION_DEJA_QUALIFIEE", "RETRAIT_CONSENTEMENT",
        "ESCALADE_PLAINTE", "TRANSFERT_EN_COURS", "ESCALADE_URGENCE"]
    with session():
        assert sum(r.get("type_entree") == "reception_hote_sms_v1" for r in m1._obtenir_registre().lire()) == 7
    stable = snapshot(session)
    comparer(before, stable, changes={"registres_maillons", "evenements_sortants"})
    reads = rpc_many(application(instance), profile["id"], [(LIRE, a, None) for a in samples])
    assert [a["recu"] for a in reads] == [a["recu"] for a in acks]
    comparer(stable, snapshot(session))


def test_panne_thread_avant_backend_ne_reflete_pas_details_SDK(instance, monkeypatch):
    import anyio

    session, profile, _ = instance
    original = anyio.to_thread.run_sync

    async def panne(func, *args, **kwargs):
        if getattr(func, "__name__", None) == "_reception_sms":
            raise RuntimeError("TRACE-SMS-fictive-privee-thread")
        return await original(func, *args, **kwargs)

    monkeypatch.setattr(anyio.to_thread, "run_sync", panne)
    before = snapshot(session)
    ack = rpc(application(instance), profile["id"], LIRE, arguments(profile))
    assert ack == {"version": 1, "operation": "lire", "ok": False,
                   "etat": "inconnu", "code": "M1-SMS-INCONNU"}
    comparer(before, snapshot(session))
