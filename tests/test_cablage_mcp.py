"""Les outils du courriel de M1 sont servis par le VRAI serveur MCP (uvicorn + client MCP officiel) ; l'outil du sas
d'envoi est exécutable par `approbations.decider` mais jamais listé ni appelable par un agent. Les événements du
câblage sont déclarés et cohérents. Données fictives."""

from __future__ import annotations

import socket
import threading
import time
from pathlib import Path

import anyio
import pytest
import uvicorn
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client

from opsys import evenements, stockage
from opsys.capacites import NOM_OUTIL_SAS_COURRIEL
from opsys.courriel_connecteurs import envoi
from opsys.departements import lire_manifeste
from opsys.serveur_mcp import application_http_departements

FICTIF = True
RACINE = Path(__file__).resolve().parents[1]
JETON = "jeton-de-test-suffisamment-long-0123456789"
OUTILS_COURRIEL = {
    "m1_lister_comptes_courriel", "m1_lire_courriels_recus", "m1_lire_reponse_courriel",
    "m1_preparer_reponse_courriel", "m1_demander_envoi_courriel",
}


def test_le_nom_de_l_outil_du_sas_est_celui_de_la_garde():
    assert NOM_OUTIL_SAS_COURRIEL == envoi.NOM_OUTIL == "opsys_courriel_approuver_envoi"


@pytest.fixture
def serveur(session):
    session  # noqa: B018 — base de l'instance migrée
    dep = lire_manifeste(RACINE / "departments" / "m01-front-office")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    app = application_http_departements({dep.id: dep}, stockage.transaction, JETON, hote="127.0.0.1")
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    fil = threading.Thread(target=srv.run, daemon=True)
    fil.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True
    fil.join(timeout=5)


def _avec_session(base, chemin, action):
    async def passer():
        client_http = create_mcp_http_client(headers={"Authorization": f"Bearer {JETON}"})
        async with (
            client_http,
            streamable_http_client(base + chemin, http_client=client_http) as flux,
            ClientSession(flux[0], flux[1]) as session_mcp,
        ):
            await session_mcp.initialize()
            return await action(session_mcp)

    return anyio.run(passer)


@pytest.mark.parametrize("chemin", ["/mcp/m01-front-office", "/mcp"])
def test_les_outils_de_m1_sont_listes_et_l_outil_du_sas_ne_l_est_pas(serveur, chemin):
    async def lister(s):
        return {o.name for o in (await s.list_tools()).tools}

    noms = _avec_session(serveur, chemin, lister)
    assert noms >= OUTILS_COURRIEL
    assert NOM_OUTIL_SAS_COURRIEL not in noms
    assert not [n for n in noms if "envoyer_courriel" in n or n.startswith("m1_envoyer")]  # aucun outil d'envoi


def test_un_agent_ne_peut_pas_appeler_l_outil_du_sas_et_la_lecture_marche(serveur):
    async def action(s):
        refus = await s.call_tool(NOM_OUTIL_SAS_COURRIEL, {"brouillon_id": "x", "revision": 1, "empreinte": "e",
                                                           "compte_id": "c", "departement": "m01-front-office"})
        comptes = await s.call_tool("m1_lister_comptes_courriel", {})
        return refus, comptes

    refus, comptes = _avec_session(serveur, "/mcp/m01-front-office", action)
    assert refus.is_error is True
    assert comptes.is_error is False and '"comptes": []' in comptes.content[0].text


def test_les_evenements_du_cablage_sont_declares_au_catalogue_et_coherents():
    attendus = {"m1.courriel_recu", "m1.brouillon_courriel_pret", "m1.approbation_envoi_demandee",
                "m1.courriel_envoye", "m1.envoi_courriel_echoue", "m7.publication_faite", "m7.publication_echouee"}
    assert attendus <= evenements.types_connus()
    deps = {d.id: d for d in (lire_manifeste(RACINE / "departments" / n)
                              for n in ("m01-front-office", "m07-marketing"))}
    assert attendus <= {*deps["m01-front-office"].evenements_publie, *deps["m07-marketing"].evenements_publie}
    assert evenements.verifier_coherence(deps) == []
    for type_evenement in attendus:  # aucune adresse, aucun texte, aucun jeton dans les charges déclarées
        proprietes = set(evenements.schema(type_evenement)["properties"])
        assert not proprietes & {"expediteur", "destinataires", "corps", "objet", "texte", "jeton", "contenu"}
