"""MCP en HTTP streamable (mode OpenClaw) : vrai serveur uvicorn, vrai client MCP officiel."""

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request

import anyio
import pytest
import uvicorn
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client

from opsys.capacites import Capacites
from opsys.serveur_mcp import application_http

JETON = "jeton-de-test-suffisamment-long-0123456789"


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
