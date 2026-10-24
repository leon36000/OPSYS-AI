"""Attribution des appels au département appelant : outils communs, approbations, points d'accès MCP."""

from __future__ import annotations

import json
import socket
import threading
import time

import anyio
import pytest
import uvicorn
from agents_base_qa import provisionner_base_qa
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client

from opsys import approbations, capacites, cli, openclaw, tableau_de_bord
from opsys.capacites import Capacites
from opsys.contexte import DEPARTEMENT_APPELANT
from opsys.departements import charger_departements
from opsys.outils import Autonomie, Outil
from opsys.serveur_mcp import application_http_departements

JETON = "jeton-de-test-suffisamment-long-0123456789"
VUS: list[str | None] = []
_SCHEMA = {"type": "object", "properties": {"note": {"type": "string"}}, "required": ["note"]}
# opsys_effacer est T3 -> niveau par défaut N5 (ADR-0009 §4) : attestation obligatoire pour approuver.
ATTESTATION_TEST = {"nom": "Alex Comptable", "profession": "CPA", "reference_document": "piece-jointe-test.pdf"}


def _noter(note: str) -> dict:
    VUS.append(DEPARTEMENT_APPELANT.get())
    return {"note": note, "departement": DEPARTEMENT_APPELANT.get()}


@pytest.fixture(autouse=True)
def outils_communs_factices(monkeypatch):
    VUS.clear()
    monkeypatch.setattr(
        capacites,
        "_outils_memoire",
        lambda: (
            Outil("opsys_noter", "Écrit une note.", _SCHEMA, _noter, Autonomie.T1),
            Outil("opsys_effacer", "Efface des données.", _SCHEMA, _noter, Autonomie.T3),
        ),
    )


def test_outil_commun_sans_appelant_refuse(departements_demo, session):
    reponse = Capacites(departements_demo, session).appeler("opsys_noter", {"note": "x"})
    assert reponse["erreur"] == "departement_appelant_inconnu"
    assert VUS == []


def test_outil_commun_execute_au_nom_de_l_appelant(departements_demo, session, nathan):
    cap = Capacites(departements_demo, session, appelant="m09-demo")  # mode supervise : T1 passe
    assert cap.appeler("opsys_noter", {"note": "x"})["resultat"]["departement"] == "m09-demo"
    demande = cap.appeler("opsys_effacer", {"note": "y"})  # T3 : toujours approuvé
    assert demande["statut"] == "en_attente_approbation"
    index = {o.nom: o for o in cap.lister()}
    with session() as cnx:
        assert approbations.lister(cnx)[0]["departement"] == "m09-demo"
        approbations.decider(
            cnx, demande["demande_id"], True, nathan, index, departements_demo, attestation=ATTESTATION_TEST
        )
    assert VUS == ["m09-demo", "m09-demo"]  # l'exécution approuvée garde le département d'origine


def test_outil_commun_approuve_depuis_la_console_et_la_cli(
    departements_demo, racine_demo, session, monkeypatch, capsys, nathan
):
    """Une demande pour un outil commun (mémoire) doit s'exécuter quelle que soit la surface qui l'approuve."""
    cap = Capacites(departements_demo, session, appelant="m09-demo")
    par_console = cap.appeler("opsys_effacer", {"note": "console"})["demande_id"]
    par_cli = cap.appeler("opsys_effacer", {"note": "cli"})["demande_id"]
    with session() as cnx:
        resultat = tableau_de_bord.decider_approbation(
            cnx, departements_demo, par_console, "approuver", nathan, attestation=ATTESTATION_TEST
        )
    assert resultat["statut"] == "executee"

    monkeypatch.setenv("OPSYS_DEPARTMENTS", str(racine_demo))
    capsys.readouterr()
    commande = [
        "approbations",
        "approuver",
        par_cli,
        "--par",
        nathan,
        "--attestation-nom",
        ATTESTATION_TEST["nom"],
        "--attestation-profession",
        ATTESTATION_TEST["profession"],
        "--attestation-document",
        ATTESTATION_TEST["reference_document"],
    ]
    assert cli.main(commande) != 0
    assert VUS == ["m09-demo"]
    capsys.readouterr()
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cli.getpass, "getpass", lambda _: "mot-de-passe-de-test-nathan-1234")
    assert cli.main(commande) == 0
    assert json.loads(capsys.readouterr().out)["statut"] == "executee"
    assert VUS == ["m09-demo", "m09-demo"]


def test_appelant_inconnu_refuse(departements_demo, session):
    with pytest.raises(ValueError, match="appelant inconnu"):
        Capacites(departements_demo, session, appelant="m05-absent")


def test_isolation_des_agents_openclaw(tmp_path, session):
    deps = charger_departements()
    paliers = {p: {"provider": "anthropic", "model": "claude-sonnet-5"} for p in ("rapide", "standard", "fort")}
    paliers["local"] = {"provider": "custom", "model": "qwen3:8b", "base_url": "http://ollama:11434/v1"}
    # ADR-0010 : mémoire Couche A fail-closed, cf. tests/test_openclaw_memoire.py.
    environ = {"OPSYS_EMBEDDINGS_URL": "http://embeddings-test:11434/v1", "OPSYS_EMBEDDINGS_MODELE": "bge-m3"}
    provisionner_base_qa(session, deps)
    fichiers = openclaw.generer(deps, tmp_path, paliers, environ=environ, cnx_factory=session)
    agents = json.loads(fichiers["agents"].read_text(encoding="utf-8"))["entries"]
    serveurs = json.loads(fichiers["mcp"].read_text(encoding="utf-8"))["servers"]
    assert len(agents) == 10
    assert set(serveurs) == ({openclaw.serveur_mcp(dep) for dep in deps.values()}
                             | {f"opsys_runtime_base-{dep.id}" for dep in deps.values()})
    assert len(serveurs) == 20
    refus_m3 = agents["m03-estimation"]["tools"]["deny"]
    assert "opsys_m3__*" not in refus_m3 and "opsys_m5__*" in refus_m3
    assert "opsys_context_*__*" in refus_m3
    assert "opsys_runtime_*__*" in refus_m3
    assert len([nom for nom in refus_m3 if nom not in {"opsys_context_*__*", "opsys_runtime_*__*"}]) == 9
    assert serveurs["opsys_m3"]["url"] == "http://opsys:8765/mcp/v1/m03-estimation"


def _port_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_points_d_acces_mcp_par_departement(departements_demo, session):
    port = _port_libre()
    app = application_http_departements(departements_demo, session, JETON, hote="127.0.0.1")
    serveur = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    fil = threading.Thread(target=serveur.run, daemon=True)
    fil.start()
    for _ in range(100):
        if serveur.started:
            break
        time.sleep(0.05)

    async def appel(chemin: str) -> dict:
        client = create_mcp_http_client(headers={"Authorization": f"Bearer {JETON}"})
        async with (
            client,
            streamable_http_client(f"http://127.0.0.1:{port}{chemin}", http_client=client) as flux,
            ClientSession(flux[0], flux[1]) as s,
        ):
            await s.initialize()
            outils = {o.name for o in (await s.list_tools()).tools}
            assert "m9_additionner" in outils
            resultat = await s.call_tool("opsys_noter", {"note": "via " + chemin})
            return json.loads(resultat.content[0].text)

    try:
        assert anyio.run(appel, "/mcp/m09-demo")["resultat"]["departement"] == "m09-demo"
        assert anyio.run(appel, "/mcp")["erreur"] == "departement_appelant_inconnu"
    finally:
        serveur.should_exit = True
        fil.join(timeout=5)
