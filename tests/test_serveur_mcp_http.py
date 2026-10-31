"""MCP en HTTP streamable (mode OpenClaw) : vrai serveur uvicorn, vrai client MCP officiel."""

from __future__ import annotations

import json
import logging
import socket
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import anyio
import pytest
import uvicorn
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client

from opsys import admission_agents, agents, identite
from opsys.capacites import Capacites
from opsys.serveur_mcp import (
    CHEMIN_RUNTIME_PREFIXE,
    CHEMIN_SANTE,
    _SansAccesSante,
    application_http,
    application_http_departements,
)

JETON = "jeton-de-test-suffisamment-long-0123456789"
JETON_INTERNE = "jeton-interne-de-test-distinct-0123456789"
JETON_CONTEXTE = "jeton-contexte-de-test-distinct-0123456789"


def _port_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def serveur_http(departements_demo, session):
    port = _port_libre()
    app = application_http(Capacites(departements_demo, session), JETON, hote="127.0.0.1")
    serveur = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    fil = threading.Thread(target=serveur.run, daemon=True)
    fil.start()
    for _ in range(100):
        if serveur.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}/mcp"
    serveur.should_exit = True
    fil.join(timeout=5)


@pytest.fixture(params=["un_point_d_acces", "un_point_par_departement"])
def racine_http(request, departements_demo, session):
    """Racine HTTP des deux applications MCP : toutes deux passent par le même garde de jeton."""
    port = _port_libre()
    if request.param == "un_point_d_acces":
        app = application_http(Capacites(departements_demo, session), JETON, hote="127.0.0.1")
    else:
        app = application_http_departements(departements_demo, session, JETON, hote="127.0.0.1")
    serveur = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    fil = threading.Thread(target=serveur.run, daemon=True)
    fil.start()
    for _ in range(100):
        if serveur.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    serveur.should_exit = True
    fil.join(timeout=5)


def test_sante_sans_jeton_repond_ok_sans_donnee_metier(racine_http):
    with urllib.request.urlopen(racine_http + CHEMIN_SANTE, timeout=5) as reponse:
        assert reponse.status == 200
        assert reponse.headers["Content-Type"] == "application/json"
        assert json.loads(reponse.read()) == {"statut": "ok", "service": "opsys-metier"}


def test_sante_head_sans_corps(racine_http):
    requete = urllib.request.Request(racine_http + CHEMIN_SANTE, method="HEAD")
    with urllib.request.urlopen(requete, timeout=5) as reponse:
        assert reponse.status == 200
        assert reponse.read() == b""


def test_sante_refuse_les_ecritures_sans_jeton(racine_http):
    requete = urllib.request.Request(racine_http + CHEMIN_SANTE, data=b"{}", method="POST")
    with pytest.raises(urllib.error.HTTPError) as erreur:
        urllib.request.urlopen(requete, timeout=5)
    assert erreur.value.code == 405
    assert erreur.value.headers["Allow"] == "GET, HEAD"


@pytest.mark.parametrize("chemin", ["/sante/", "/sante/x", "/SANTE", "/mcp", "/"])
def test_seul_le_chemin_exact_de_sante_echappe_au_jeton(racine_http, chemin):
    with pytest.raises(urllib.error.HTTPError) as erreur:
        urllib.request.urlopen(racine_http + chemin, timeout=5)
    assert erreur.value.code == 401


def _acces(chemin: str) -> logging.LogRecord:
    """Enregistrement du journal d'accès d'uvicorn (format `%s - "%s %s HTTP/%s" %d`)."""
    return logging.LogRecord("uvicorn.access", logging.INFO, __file__, 0,
                             '%s - "%s %s HTTP/%s" %d', ("127.0.0.1:5000", "GET", chemin, "1.1", 200), None)


def test_journal_d_acces_ignore_seulement_les_sondes_de_sante():
    filtre = _SansAccesSante()
    assert filtre.filter(_acces(CHEMIN_SANTE)) is False
    assert filtre.filter(_acces("/mcp/m03-estimation")) is True
    assert filtre.filter(_acces("/mcp?q=/sante")) is True


def test_sans_jeton_401(serveur_http):
    requete = urllib.request.Request(serveur_http, data=b"{}", method="POST",
                                     headers={"Content-Type": "application/json"})
    with pytest.raises(urllib.error.HTTPError) as erreur:
        urllib.request.urlopen(requete, timeout=5)
    assert erreur.value.code == 401


def test_jeton_trop_court_refuse(departements_demo, session):
    with pytest.raises(ValueError, match="24 caractères"):
        application_http(Capacites(departements_demo, session), "court")


def test_aller_retour_mcp_http(serveur_http):
    async def scenario():
        client_http = create_mcp_http_client(headers={"Authorization": f"Bearer {JETON}"})
        async with client_http, streamable_http_client(serveur_http, http_client=client_http) as flux:
            lecture, ecriture = flux[0], flux[1]
            async with ClientSession(lecture, ecriture) as session_mcp:
                await session_mcp.initialize()
                outils = await session_mcp.list_tools()
                assert "m9_additionner" in {o.name for o in outils.tools}
                resultat = await session_mcp.call_tool("m9_additionner", {"a": 1.5, "b": 2})
                assert json.loads(resultat.content[0].text) == {"ok": True, "resultat": {"somme": "3.5"}}

    anyio.run(scenario)


def test_route_admission_privee_est_liee_au_profil_et_au_jeton(session):
    from opsys.departements import charger_departements

    departements = charger_departements()
    with session() as cnx:
        identite.creer_personne(cnx, "runtime-admin", "Admin", "test-password-runtime-1234", ["admin"])
        profil = agents.creer(
            cnx,
            departements,
            {
                "id": "m09-runtime",
                "departement": "m09-strategic-intelligence",
                "responsabilite": "Calculer les sommes vérifiables.",
                "palier_modele": "standard",
                "outils": ["m9_etat_consolide"],
                "budget_jour": 1000,
                "budget_mois": 10000,
                "limite_tours": 3,
                "limite_reessais": 1,
                "limite_concurrence": 1,
                "declencheurs": [{"type": "manuel"}],
            },
            par="runtime-admin",
            mutation_id="create-runtime-001",
        )
        agents.definir_actif(
            cnx, profil["id"], departements, True, par="runtime-admin",
            mutation_id="activate-runtime-001", revision_attendue=1,
        )
        admission_agents.configurer_plafonds_entreprise(
            cnx, 10_000, 100_000, par="runtime-admin", revision_attendue=0,
        )
    port = _port_libre()
    app = application_http_departements(
        departements, session, JETON, hote="127.0.0.1", jeton_contexte=JETON_INTERNE
    )
    serveur = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    fil = threading.Thread(target=serveur.run, daemon=True)
    fil.start()
    try:
        for _ in range(100):
            if serveur.started:
                break
            time.sleep(0.05)
        url = f"http://127.0.0.1:{port}{CHEMIN_RUNTIME_PREFIXE}{profil['id']}"
        for jeton in (JETON, ""):
            requete = urllib.request.Request(
                url, data=b"{}", method="POST", headers={"Authorization": f"Bearer {jeton}"}
            )
            with pytest.raises(urllib.error.HTTPError) as erreur:
                urllib.request.urlopen(requete, timeout=5)
            assert erreur.value.code == 401

        async def scenario():
            client_http = create_mcp_http_client(headers={"Authorization": f"Bearer {JETON_INTERNE}"})
            async with (
                client_http,
                streamable_http_client(url, http_client=client_http) as flux,
                ClientSession(flux[0], flux[1]) as session_mcp,
            ):
                await session_mcp.initialize()
                outils = await session_mcp.list_tools()
                assert {outil.name for outil in outils.tools} == {
                    "opsys_runtime_admettre",
                    "opsys_runtime_concilier",
                    "opsys_runtime_liberer_avant_dispatch",
                    "opsys_runtime_verifier_outil",
                    "opsys_runtime_cfo_ticket",
                    "opsys_runtime_importer_appel_manque",
                    "opsys_runtime_deposer_faits",
                    "opsys_runtime_lire_reception_sms",
                    "opsys_runtime_recevoir_sms",
                }
                runtime_args = {
                    "execution_id": "http-before-dispatch-001", "cle_idempotence": "http-before-dispatch-001:0:0",
                    "tokens_plafond": 50, "revision_profil": 2, "tours": 1,
                    "attempt_id": "http-before-dispatch-001:0", "cycle_id": "http-before-dispatch-001:0:0",
                    "candidate_index": 0, "stream_ordinal": 0, "is_fallback_retry": False,
                }
                reserved = await session_mcp.call_tool("opsys_runtime_admettre", runtime_args)
                reservation = json.loads(reserved.content[0].text)
                assert reservation["ok"] is True and reservation["accord_neuf"] is True
                release_args = {key: runtime_args[key] for key in (
                    "execution_id", "attempt_id", "cycle_id", "candidate_index", "stream_ordinal", "revision_profil",
                )}
                release_args["reservation_id"] = reservation["resultat"]["id"]
                for changes in ({"agent_id": "forged-profile"}, {"raison": "arbitrary"},
                                {"candidate_index": False}, {"revision_profil": True}):
                    refused = await session_mcp.call_tool(
                        "opsys_runtime_liberer_avant_dispatch", {**release_args, **changes},
                    )
                    assert refused.is_error is True
                wrong_run = {**release_args, "execution_id": "http-another-run-001",
                             "attempt_id": "http-another-run-001:0", "cycle_id": "http-another-run-001:0:0"}
                refused = await session_mcp.call_tool("opsys_runtime_liberer_avant_dispatch", wrong_run)
                assert refused.is_error is True
                released = await session_mcp.call_tool("opsys_runtime_liberer_avant_dispatch", release_args)
                assert json.loads(released.content[0].text)["resultat"]["statut"] == "liberee"
                replay = await session_mcp.call_tool("opsys_runtime_liberer_avant_dispatch", release_args)
                assert json.loads(replay.content[0].text) == json.loads(released.content[0].text)
                denied_admission = await session_mcp.call_tool("opsys_runtime_admettre", runtime_args)
                assert denied_admission.is_error is True
                with session() as cnx:
                    assert [event["evenement"] for event in admission_agents.historique(
                        cnx, release_args["reservation_id"],
                    )] == ["reservee", "liberee"]
            public_http = create_mcp_http_client(headers={"Authorization": f"Bearer {JETON}"})
            public_url = f"http://127.0.0.1:{port}/mcp/m09-strategic-intelligence"
            async with (
                public_http,
                streamable_http_client(public_url, http_client=public_http) as flux_public,
                ClientSession(flux_public[0], flux_public[1]) as public_mcp,
            ):
                await public_mcp.initialize()
                names = {tool.name for tool in (await public_mcp.list_tools()).tools}
                assert "opsys_runtime_liberer_avant_dispatch" not in names
                denied = await public_mcp.call_tool("opsys_runtime_liberer_avant_dispatch", release_args)
                assert denied.is_error is True

        anyio.run(scenario)
    finally:
        serveur.should_exit = True
        fil.join(timeout=5)


def test_outil_emission_ticket_est_prive_au_catalogue_contexte(session):
    from opsys.departements import charger_departements

    departements = charger_departements(Path(__file__).resolve().parents[1] / "departments")
    port = _port_libre()
    app = application_http_departements(
        departements, session, JETON, hote="127.0.0.1", jeton_contexte=JETON_CONTEXTE
    )
    serveur = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    fil = threading.Thread(target=serveur.run, daemon=True)
    fil.start()
    try:
        for _ in range(100):
            if serveur.started:
                break
            time.sleep(0.05)

        async def lister(url: str, jeton: str) -> set[str]:
            client_http = create_mcp_http_client(headers={"Authorization": f"Bearer {jeton}"})
            async with (
                client_http,
                streamable_http_client(url, http_client=client_http) as flux,
                ClientSession(flux[0], flux[1]) as session_mcp,
            ):
                await session_mcp.initialize()
                resultat = await session_mcp.list_tools()
                return {outil.name for outil in resultat.tools}

        async def scenario():
            base = f"http://127.0.0.1:{port}"
            contextuels = await lister(base + "/mcp/contexte/m10-memoire", JETON_CONTEXTE)
            publics_m2 = await lister(base + "/mcp/m02-revenue-crm", JETON)
            publics_m10 = await lister(base + "/mcp/m10-memoire", JETON)
            publics_tous = await lister(base + "/mcp", JETON)
            assert contextuels == {
                "m10_paquet_contexte_affaire", "opsys_contexte_creer_ticket_cible",
                "opsys_contexte_creer_ticket_memoire",
            }
            for publics in (publics_m2, publics_m10, publics_tous):
                assert "m10_paquet_contexte_affaire" not in publics
                assert "opsys_contexte_creer_ticket_cible" not in publics
                assert "opsys_contexte_creer_ticket_memoire" not in publics

        anyio.run(scenario)
    finally:
        serveur.should_exit = True
        fil.join(timeout=5)


def test_revalidation_profile_au_dispatch_refuse_revision_modifiee_apres_verification(
    departements_demo, session, monkeypatch
):
    """Le profil change après le RPC Core mais avant le vrai tools/call MCP métier."""
    from opsys import admission_agents

    profile_id = "m09-dispatch-race"
    with session() as cnx:
        identite.creer_personne(cnx, "dispatch-admin", "Admin fictif", "password-dispatch-test-1234", ["admin"])
        agents.creer(
            cnx,
            departements_demo,
            {
                "id": profile_id,
                "departement": "m09-demo",
                "responsabilite": "Profil synthétique du test de révision avant dispatch.",
                "palier_modele": "standard",
                "outils": ["m9_additionner", "m9_refuser_si_negatif"],
                "budget_jour": 100,
                "budget_mois": 1_000,
                "limite_tours": 2,
                "limite_reessais": 1,
                "limite_concurrence": 1,
                "declencheurs": [{"type": "manuel"}],
            },
            par="dispatch-admin",
            mutation_id="dispatch-profile-create-001",
        )
        agents.definir_actif(
            cnx,
            profile_id,
            departements_demo,
            True,
            par="dispatch-admin",
            mutation_id="dispatch-profile-activate-001",
            revision_attendue=1,
        )
        allowed = admission_agents.verifier_outil_runtime(
            cnx,
            profile_id,
            departements_demo,
            "opsys_m9__m9_additionner",
            2,
        )
        assert allowed == {"autorise": True, "revision_profil": 2}
        current = agents.obtenir(cnx, profile_id)
        assert current is not None
        specification = {
            key: current[key]
            for key in (
                "id",
                "departement",
                "responsabilite",
                "palier_modele",
                "outils",
                "budget_jour",
                "budget_mois",
                "limite_tours",
                "limite_reessais",
                "limite_concurrence",
                "declencheurs",
            )
        }
        specification["outils"] = ["m9_refuser_si_negatif"]

    calls = []
    original_dispatch = Capacites._distribuer

    def observed_dispatch(self, nom, arguments, **kwargs):
        calls.append(nom)
        return original_dispatch(self, nom, arguments, **kwargs)

    monkeypatch.setattr(Capacites, "_distribuer", observed_dispatch)
    port = _port_libre()
    app = application_http_departements(departements_demo, session, JETON, hote="127.0.0.1")
    serveur = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    fil = threading.Thread(target=serveur.run, daemon=True)
    fil.start()
    try:
        for _ in range(100):
            if serveur.started:
                break
            time.sleep(0.05)
        url = f"http://127.0.0.1:{port}/mcp/m09-demo"

        async def scenario():
            client_http = create_mcp_http_client(headers={"Authorization": f"Bearer {JETON}"})
            async with (
                client_http,
                streamable_http_client(url, http_client=client_http) as flux,
                ClientSession(flux[0], flux[1]) as session_mcp,
            ):
                await session_mcp.initialize()
                valid = await session_mcp.call_tool(
                    "m9_additionner",
                    {"a": 2, "b": 3},
                    meta={
                        "opsys/runtimeProfileId": profile_id,
                        "opsys/runtimeProfileRevision": "2",
                        "opsys/runtimeServer": "opsys_m9",
                    },
                )
                assert valid.is_error is not True
                assert calls == ["m9_additionner"]
                with session() as cnx:
                    agents.modifier(
                        cnx,
                        profile_id,
                        departements_demo,
                        specification,
                        par="dispatch-admin",
                        mutation_id="dispatch-profile-remove-tool-001",
                        revision_attendue=2,
                    )
                stale = await session_mcp.call_tool(
                    "m9_additionner",
                    {"a": 2, "b": 3},
                    meta={
                        "opsys/runtimeProfileId": profile_id,
                        "opsys/runtimeProfileRevision": "2",
                        "opsys/runtimeServer": "opsys_m9",
                    },
                )
                assert stale.is_error is True
                assert calls == ["m9_additionner"]
                removed = await session_mcp.call_tool(
                    "m9_additionner",
                    {"a": 2, "b": 3},
                    meta={
                        "opsys/runtimeProfileId": profile_id,
                        "opsys/runtimeProfileRevision": "3",
                        "opsys/runtimeServer": "opsys_m9",
                    },
                )
                assert removed.is_error is True
                malformed = await session_mcp.call_tool(
                    "m9_additionner",
                    {"a": 2, "b": 3},
                    meta={"opsys/runtimeProfileId": profile_id, "opsys/runtimeProfileRevision": "3"},
                )
                assert malformed.is_error is True
                assert calls == ["m9_additionner"]
                legacy = await session_mcp.call_tool("m9_additionner", {"a": 2, "b": 3})
                assert legacy.is_error is not True
                assert calls == ["m9_additionner", "m9_additionner"]

                for invalid_revision in ("0", "9007199254740992", "٣"):
                    invalid = await session_mcp.call_tool(
                        "m9_additionner",
                        {"a": 2, "b": 3},
                        meta={
                            "opsys/runtimeProfileId": profile_id,
                            "opsys/runtimeProfileRevision": invalid_revision,
                            "opsys/runtimeServer": "opsys_m9",
                        },
                    )
                    assert invalid.is_error is True
                    assert json.loads(invalid.content[0].text)["erreur"] == "meta_invalide"
                    assert calls == ["m9_additionner", "m9_additionner"]

        anyio.run(scenario)
    finally:
        serveur.should_exit = True
        fil.join(timeout=5)


def test_ticket_cfo_stale_profile_est_refuse_avant_consommation(session, monkeypatch):
    import asyncio
    from pathlib import Path

    import httpx
    from m5_financecore import outils as m5_outils
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    from opsys import agent_cfo_grants, contexte, departements, serveur_mcp

    monkeypatch.setenv("OPSYS_EVENEMENTS_REPARTITEUR", "0")
    deps = departements.charger_departements(Path(__file__).resolve().parents[1] / "departments")
    owner = "owner.profile-toctou.fictif"
    spec = {
        "id": "m5-cfo-profile-toctou",
        "departement": "m05-financecore",
        "responsabilite": "Préparer un dossier CFO synthétique.",
        "palier_modele": "rapide",
        "outils": sorted(agent_cfo_grants.OUTILS),
        "budget_jour": 10000,
        "budget_mois": 100000,
        "limite_tours": 8,
        "limite_reessais": 1,
        "limite_concurrence": 1,
        "declencheurs": [{"type": "manuel"}],
    }
    with session() as cnx:
        identite.creer_personne(cnx, owner, "Propriétaire fictif", "secret-fictif-profile-toctou-01", ["nathan_owner"])
        profile = agents.creer(cnx, deps, spec, par=owner, mutation_id="profile-toctou-create-001")
        profile = agents.definir_actif(
            cnx,
            profile["id"],
            deps,
            True,
            par=owner,
            mutation_id="profile-toctou-activate-001",
            revision_attendue=1,
        )
        instance = agent_cfo_grants.instance_id(cnx)
    args = {"aujourd_hui": "2026-10-01", "question_posee": "Dossier synthétique"}
    with contexte.appele_par_appareil(
        contexte.IdentiteAppelante(owner, "nathan_owner", source="console")
    ), session() as cnx:
        agent_cfo_grants.accorder(
            cnx,
            profile["id"],
            par=owner,
            instance_id=instance,
            revision_attendue=profile["revision"],
            version_attendue=0,
            date_debut_rapport="2026-10-01",
            date_fin_rapport="2026-10-31",
        )
    with session() as cnx:
        issued = agent_cfo_grants.emettre(
            cnx,
            profile["id"],
            "m5_preparer_dossier_decision_cfo",
            args,
            instance_id=instance,
            revision_profil=profile["revision"],
        )
    ticket = issued["ticket"]
    reads = 0
    original_read = m5_outils._lectures_finance

    def count_finance_read(*call_args, **kwargs):
        nonlocal reads
        reads += 1
        return original_read(*call_args, **kwargs)

    monkeypatch.setattr(m5_outils, "_lectures_finance", count_finance_read)
    m5_outils.utiliser_stockage_durable()
    app = serveur_mcp.application_http_departements(deps, session, JETON)

    async def run():
        transport = httpx.ASGITransport(app=app)
        async with (
            httpx.AsyncClient(transport=transport, base_url="http://opsys.test") as http,
            app._application.router.lifespan_context(app._application),
            streamable_http_client("http://opsys.test/mcp/m05-financecore", http_client=http) as (read, write),
            ClientSession(read, write) as business,
        ):
            http.headers["Authorization"] = f"Bearer {JETON}"
            await business.initialize()
            malformed_revision = await business.call_tool(
                "m5_preparer_dossier_decision_cfo",
                args,
                meta={
                    "opsys/cfoGrantTicket": ticket,
                    "opsys/runtimeProfileId": profile["id"],
                    "opsys/runtimeProfileRevision": "0",
                    "opsys/runtimeServer": "opsys_m5",
                },
            )
            assert malformed_revision.is_error is True
            assert json.loads(malformed_revision.content[0].text)["erreur"] == "meta_invalide"
            assert reads == 0
            stale = await business.call_tool(
                "m5_preparer_dossier_decision_cfo",
                args,
                meta={
                    "opsys/cfoGrantTicket": ticket,
                    "opsys/runtimeProfileId": profile["id"],
                    "opsys/runtimeProfileRevision": str(profile["revision"] + 1),
                    "opsys/runtimeServer": "opsys_m5",
                },
            )
            assert stale.is_error is True
            assert reads == 0
    asyncio.run(run())
    # Consume explicitly afterwards: this proves the rejected stale MCP attempt left the one-use
    # CFO ticket untouched. The synthetic report uses no provider or business network call.
    with session() as cnx:
        agent_cfo_grants.consommer(
            cnx,
            ticket,
            "m5_preparer_dossier_decision_cfo",
            args,
            instance_id=instance,
        )
    assert reads == 0


def test_prevol_appareil_http_ferme_par_defaut_et_authentifie(serveur_http, monkeypatch):
    """Prévol privé réel : le bearer MCP seul ne constitue pas une attestation gateway."""
    import hashlib
    import hmac

    import httpx

    from opsys import attestation_appareil_gateway as att

    url = serveur_http.removesuffix("/mcp") + att._CHEMIN
    bearer = {"Authorization": "Bearer " + JETON}
    monkeypatch.delenv(att._ENV, raising=False)
    assert httpx.get(url, headers=bearer, timeout=2).status_code == 404
    secret = "qa-gateway-secret-fictif-01234567890123456789"
    monkeypatch.setenv(att._ENV, secret)
    assert httpx.get(url, headers=bearer, timeout=2).status_code == 404
    preuve = hmac.new(secret.encode(), b"opsys.device.generation.v1", hashlib.sha256).hexdigest()
    resultat = httpx.get(url, headers={**bearer, "x-opsys-gateway-proof": preuve}, timeout=2)
    assert resultat.status_code == 200
    assert resultat.json() == {"generation": att.generation()}
    assert resultat.headers["cache-control"] == "no-store"
