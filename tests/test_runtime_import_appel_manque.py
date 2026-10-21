"""Tests proposés pour la route MCP runtime privée; à intégrer dans tests/ et à exécuter par ROOT."""
from __future__ import annotations

import asyncio
import json
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest
from m1_front_office import outils as outils_m1
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from sqlalchemy import select, update

from opsys import agents, identite, stockage, taxonomie
from opsys.departements import charger_departements
from opsys.serveur_mcp import application_http_departements
from opsys.stockage.schema import (
    AGENTS_CONFIGURABLES,
    CLES_CHIFFREMENT,
    EVENEMENTS_RECUS,
    EVENEMENTS_SORTANTS,
    MUTATIONS_APPLIQUEES,
    REGISTRES,
)

JETON_PUBLIC = "jeton-public-appel-manque-fictif-long-01"
JETON_RUNTIME = "jeton-runtime-appel-manque-fictif-long-01"
BASE = {
    "provider": "mock",
    "event_id": "event-01",
    "call_id": "provider-call-01",
    "occurred_at": "2026-10-03T15:00:00Z",
    "telephone": "+15145550142",
}


@pytest.fixture
def profile_m1(session, declarer_services, monkeypatch):
    monkeypatch.setenv("OPSYS_EVENEMENTS_REPARTITEUR", "0")
    deps = charger_departements(Path(__file__).resolve().parents[1] / "departments")
    with session() as cnx:
        identite.creer_personne(cnx, "appel-admin", "Admin fictif", "synthetic-password-01", ["admin"])
        agents.creer(
            cnx, deps,
            {
                "id": "m1-private-ingress", "departement": "m01-front-office",
                "responsabilite": "Profil fictif du test d'import host-only.",
                "palier_modele": "standard", "outils": ["m1_importer_appel_manuellement"],
                "budget_jour": 100, "budget_mois": 1_000, "limite_tours": 2,
                "limite_reessais": 1, "limite_concurrence": 1,
                "declencheurs": [{"type": "manuel"}],
            }, par="appel-admin", mutation_id="appel-profile-create-01",
        )
        agents.definir_actif(
            cnx, "m1-private-ingress", deps, True, par="appel-admin",
            mutation_id="appel-profile-activate-01", revision_attendue=1,
        )
        profil = agents.obtenir(cnx, "m1-private-ingress")
    declarer_services()
    taxonomie.enregistrer_zone_desservie(["Laval", "Québec"])
    outils_m1.utiliser_stockage_durable()
    yield deps, profil
    outils_m1.reinitialiser_registre()


def _appel_http(app, args, *, token=JETON_RUNTIME):
    async def run():
        http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000")
        http.headers["Authorization"] = f"Bearer {token}"
        async with (
            http,
            app._application.router.lifespan_context(app._application),
            streamable_http_client(
                "http://127.0.0.1:8000/mcp/runtime/m1-private-ingress", http_client=http,
            ) as (read, write),
            ClientSession(read, write) as client,
        ):
            await client.initialize()
            return await client.call_tool("opsys_runtime_importer_appel_manque", args)
    return asyncio.run(run())


def _app(deps, session):
    return application_http_departements(
        deps, session, JETON_PUBLIC, hote="127.0.0.1", jeton_contexte=JETON_RUNTIME,
    )


def _lignes_m1(session):
    with session():
        return list(stockage.maillons("m01-front-office", "principal"))


def _etat_durable(session):
    """All register chains, outbox, receipts, keys, mutations and profile authority."""
    tables = (REGISTRES, EVENEMENTS_SORTANTS, EVENEMENTS_RECUS,
              MUTATIONS_APPLIQUEES, CLES_CHIFFREMENT, AGENTS_CONFIGURABLES)
    with session() as cnx:
        return {table.name: list(cnx.execute(select(table).order_by(*table.primary_key.columns)))
                for table in tables}


def test_http_private_route_imports_replay_and_canonical_utc(profile_m1, session, monkeypatch):
    deps, profile = profile_m1
    app = _app(deps, session)
    outils_m1.utiliser_stockage_durable()
    premiere = _appel_http(app, {**BASE, "revision_profil": profile["revision"]})
    assert json.loads(premiere.content[0].text) == {
        "ok": True, "source": "voice-call:mock", "call_id": BASE["call_id"], "status": "manque",
    }
    avant = _lignes_m1(session)
    etat_apres_import = _etat_durable(session)
    signaux = [row for row in avant if row.get("type_entree") == "signal"]
    assert any(row.get("source") == "appel_operateur" for row in signaux)
    assert any(row.get("signal_id", "").startswith("appel-hote:voice-call:mock:") for row in signaux)
    assert not any(row.get("source") == "appel_manuel" for row in signaux)
    transferts = [row for row in avant if row.get("type_entree") == "transfert"]
    assert any(row.get("source") == "appel_operateur" for row in transferts)
    assert any("Contact : numéro transmis par l'hôte (porté à part)." in row.get("faits", "")
               for row in transferts)
    rejouee = _appel_http(_app(deps, session), {
        **BASE, "event_id": "event-redelivered-02", "occurred_at": "2026-10-03T11:00:00-04:00",
        "revision_profil": profile["revision"],
    })
    assert json.loads(rejouee.content[0].text) == json.loads(premiere.content[0].text)
    assert len(_lignes_m1(session)) == len(avant)
    assert _etat_durable(session) == etat_apres_import

    conflit = _appel_http(_app(deps, session), {
        **BASE, "event_id": "event-03", "telephone": "+15145550143",
        "revision_profil": profile["revision"],
    })
    assert conflit.is_error is True
    assert json.loads(conflit.content[0].text) == {"ok": False, "erreur": "import_appel_refuse"}
    assert len(_lignes_m1(session)) == len(avant)

    champ_extra = _appel_http(_app(deps, session), {
        **BASE, "transcription": "PII", "revision_profil": profile["revision"],
    })
    assert champ_extra.is_error is True
    assert json.loads(champ_extra.content[0].text) == {"ok": False, "erreur": "import_appel_refuse"}

    fournisseur_invalide = _appel_http(_app(deps, session), {
        **BASE, "provider": "unknown", "event_id": "event-unknown-provider",
        "revision_profil": profile["revision"],
    })
    assert fournisseur_invalide.is_error is True
    assert json.loads(fournisseur_invalide.content[0].text) == {
        "ok": False, "erreur": "import_appel_refuse",
    }


def test_runtime_tool_not_in_public_catalogue(profile_m1, session):
    deps, _ = profile_m1
    app = _app(deps, session)

    async def run():
        http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000")
        http.headers["Authorization"] = f"Bearer {JETON_PUBLIC}"
        async with (
            http,
            app._application.router.lifespan_context(app._application),
            streamable_http_client("http://127.0.0.1:8000/mcp/m01-front-office", http_client=http) as (read, write),
            ClientSession(read, write) as client,
        ):
            await client.initialize()
            tools = await client.list_tools()
            return {item.name for item in tools.tools}
    assert "opsys_runtime_importer_appel_manque" not in asyncio.run(run())


@pytest.mark.parametrize("retrait", ["inactif", "sans_outil", "revision_stale"])
def test_profile_current_rights_required(profile_m1, session, retrait):
    deps, profile = profile_m1
    app = _app(deps, session)  # la route est enregistrée quand le profil est actif, puis l'autorité change en DB.
    revision_a_tester = profile["revision"] - 1 if retrait == "revision_stale" else profile["revision"]
    with session() as cnx:
        if retrait == "inactif":
            agents.definir_actif(cnx, profile["id"], deps, False, par="appel-admin",
                                 mutation_id="appel-profile-disable-01", revision_attendue=profile["revision"])
            revision_a_tester = agents.obtenir(cnx, profile["id"])["revision"]
        elif retrait == "sans_outil":
            revision_a_tester += 1
            cnx.execute(update(AGENTS_CONFIGURABLES).where(AGENTS_CONFIGURABLES.c.id == profile["id"])
                        .values(outils="[]", revision=revision_a_tester))
    answer = _appel_http(app, {**BASE, "revision_profil": revision_a_tester})
    assert answer.is_error is True
    assert json.loads(answer.content[0].text) == {"ok": False, "erreur": "import_appel_refuse"}
    assert not any(row.get("type_entree") == "appel_importe" for row in _lignes_m1(session))


def test_profile_other_department_and_factory_not_bound_are_refused(profile_m1, session):
    deps, profile = profile_m1
    app = _app(deps, session)
    with session() as cnx:
        cnx.execute(update(AGENTS_CONFIGURABLES).where(AGENTS_CONFIGURABLES.c.id == profile["id"])
                    .values(departement="m02-revenue-crm", outils='["m2_ingerer_lead"]',
                            revision=profile["revision"] + 1))
    wrong_dept = _appel_http(app, {**BASE, "revision_profil": profile["revision"] + 1})
    assert wrong_dept.is_error is True


def test_unbound_factory_is_refused(profile_m1, session):
    deps, profile = profile_m1
    @contextmanager
    def non_liee():
        with stockage.moteur().begin() as cnx:
            yield cnx
    app = application_http_departements(
        deps, non_liee, JETON_PUBLIC, hote="127.0.0.1", jeton_contexte=JETON_RUNTIME,
    )
    answer = _appel_http(app, {**BASE, "revision_profil": profile["revision"]})
    assert answer.is_error is True
    assert json.loads(answer.content[0].text) == {"ok": False, "erreur": "import_appel_refuse"}
    assert not any(row.get("type_entree") == "appel_importe" for row in _lignes_m1(session))


def test_bad_ack_or_mid_import_revoke_rolls_back(profile_m1, session, monkeypatch):
    deps, profile = profile_m1
    app = _app(deps, session)
    original = outils_m1.importer_appel_manque_hote
    before = _etat_durable(session)
    calls = 0

    def importer_then_revoke(**kwargs):
        nonlocal calls
        result = original(**kwargs)
        calls += 1
        cnx = stockage.connexion_courante()
        cnx.execute(update(AGENTS_CONFIGURABLES).where(AGENTS_CONFIGURABLES.c.id == profile["id"])
                    .values(outils="[]", revision=profile["revision"] + 1))
        return result

    monkeypatch.setattr(outils_m1, "importer_appel_manque_hote", importer_then_revoke)
    answer = _appel_http(app, {**BASE, "revision_profil": profile["revision"]})
    assert answer.is_error is True
    assert calls == 1
    assert not any(row.get("type_entree") == "appel_importe" for row in _lignes_m1(session))
    assert _etat_durable(session) == before


def test_false_m1_ack_rolls_back(profile_m1, session, monkeypatch):
    deps, profile = profile_m1
    app = _app(deps, session)
    original = outils_m1.importer_appel_manque_hote
    before = _etat_durable(session)
    calls = 0

    def importer_then_false_ack(**kwargs):
        nonlocal calls
        original(**kwargs)
        calls += 1
        return {
            "accepte": False, "source": f"voice-call:{kwargs['provider']}",
            "appel_id": kwargs["call_id"], "statut": "manque",
        }

    monkeypatch.setattr(outils_m1, "importer_appel_manque_hote", importer_then_false_ack)
    answer = _appel_http(app, {**BASE, "revision_profil": profile["revision"]})
    assert answer.is_error is True
    assert calls == 1
    assert json.loads(answer.content[0].text) == {"ok": False, "erreur": "import_appel_refuse"}
    assert not any(row.get("type_entree") == "appel_importe" for row in _lignes_m1(session))
    assert _etat_durable(session) == before


def test_manual_facade_keeps_historical_provenance(profile_m1, session):
    _, _profile = profile_m1
    with session():
        outils_m1.importer_appel_manuellement(
            source="export manuel fictif", evenement_id="manual-event-01", appel_id="manual-call-01",
            recu_le="2026-10-03T15:00:00+00:00", telephone="+15145550144", statut="manque",
        )
    rows = _lignes_m1(session)
    signal = next(row for row in rows if row.get("signal_id") ==
                  "appel-manuel:export manuel fictif:manual-event-01")
    transfert = next(row for row in rows if row.get("type_entree") == "transfert"
                     and row.get("signal_id") == signal["signal_id"])
    assert signal["source"] == "appel_manuel"
    assert transfert["source"] == "appel_manuel"
    assert "Contact : aucun connu." in transfert["faits"]


def test_manual_import_cannot_claim_host_namespace(profile_m1, session):
    before = _lignes_m1(session)
    with pytest.raises(ValueError, match="REJ-SOURCE-RESERVEE"), session():
        outils_m1.importer_appel_manuellement(
            source=" voice-call:mock ", evenement_id="manual-event-claim",
            appel_id=BASE["call_id"], recu_le="2026-10-03T15:00:00.000000Z",
            telephone=BASE["telephone"], statut="manque",
        )
    assert _lignes_m1(session) == before


def test_historical_manual_claim_cannot_satisfy_host_ack(profile_m1, session):
    deps, profile = profile_m1
    # Reproduce a record written by the historical manual owner before its namespace guard.
    with session():
        outils_m1._importer_appel(
            "voice-call:mock", "historical-manual-event", BASE["call_id"],
            "2026-10-03T15:00:00.000000Z", BASE["telephone"], "manque",
            declenchement="appel_manuel", prefixe_signal="appel-manuel",
            source_contact="numéro de téléphone importé manuellement",
        )
    before = _lignes_m1(session)
    result = _appel_http(_app(deps, session), {**BASE, "revision_profil": profile["revision"]})
    assert result.is_error is True
    assert json.loads(result.content[0].text) == {"ok": False, "erreur": "import_appel_refuse"}
    assert _lignes_m1(session) == before


@pytest.mark.parametrize("modification", [
    {"occurred_at": "2026-10-03T15:00:00"},
    {"occurred_at": "2026-02-31T15:00:00Z"},
    {"occurred_at": "x" * 41},
    {"revision_profil": True},
    {"event_id": "   "},
    {"event_id": "bad\x00event"},
    {"call_id": "bad\ncall"},
    {"champ_inconnu": "refus"},
    {"telephone": "+1514١٢٣٤٥٦٧"},
])
def test_invalid_payload_is_refused_before_any_write(profile_m1, session, modification):
    deps, profile = profile_m1
    app = _app(deps, session)
    payload = {**BASE, "revision_profil": profile["revision"]}
    payload.update(modification)
    answer = _appel_http(app, payload)
    assert answer.is_error is True
    assert json.loads(answer.content[0].text) == {"ok": False, "erreur": "import_appel_refuse"}
    assert not any(row.get("type_entree") == "appel_importe" for row in _lignes_m1(session))


def test_in_memory_owner_cannot_ack_a_durable_import(profile_m1, session):
    deps, profile = profile_m1
    app = _app(deps, session)
    before = _etat_durable(session)
    outils_m1.reinitialiser_registre()
    try:
        answer = _appel_http(app, {**BASE, "revision_profil": profile["revision"]})
        assert answer.is_error is True
        assert json.loads(answer.content[0].text) == {"ok": False, "erreur": "import_appel_refuse"}
        assert outils_m1._obtenir_registre().lire() == []
        assert _etat_durable(session) == before
    finally:
        outils_m1.utiliser_stockage_durable()


def test_storage_url_change_during_owner_call_rolls_back(profile_m1, session, monkeypatch):
    deps, profile = profile_m1
    app = _app(deps, session)
    ancienne_url = stockage.url_base()
    original = outils_m1.importer_appel_manque_hote
    before = _etat_durable(session)
    calls = 0

    def importer_then_switch_base(**kwargs):
        nonlocal calls
        result = original(**kwargs)
        calls += 1
        monkeypatch.setenv(stockage.ENV_URL, "sqlite:////tmp/opsys-m1-other-db.sqlite")
        return result

    monkeypatch.setattr(outils_m1, "importer_appel_manque_hote", importer_then_switch_base)
    answer = _appel_http(app, {**BASE, "revision_profil": profile["revision"]})
    assert answer.is_error is True
    assert calls == 1
    monkeypatch.setenv(stockage.ENV_URL, ancienne_url)
    assert not any(row.get("type_entree") == "appel_importe" for row in _lignes_m1(session))
    assert _etat_durable(session) == before
