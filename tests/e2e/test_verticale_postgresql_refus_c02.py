"""Le ticket de cible C02 (liaison M10 -> outil) sur PostgreSQL : sans liaison active, le refus typé de DOMAINE (celui
de SQLite), par HTTP réel, sans la moindre mutation.

Avant le portage PostgreSQL, ce test prouvait que PostgreSQL REFUSAIT la liaison de cible (« désactivée hors de
SQLite »). La garde est levée : le parcours positif complet (affaire, bus, recalcul certifié) tourne sur PostgreSQL
dans `test_verticale_affaire_durable.py` (deux moteurs), et ce test fige le refus de domaine."""

import json

import anyio
import pytest
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client
from memoire.doubles import raison_sans_docker
from tests.e2e.test_verticale_affaire_durable import JETON_CONTEXTE_FICTIF, _empreinte


@pytest.mark.parametrize(
    "moteur",
    [
        pytest.param(
            "postgresql", marks=pytest.mark.skipif(raison_sans_docker() is not None, reason="Docker inaccessible")
        )
    ],
    indirect=True,
)
def test_ticket_c02_sans_liaison_active_est_refuse_sur_postgresql_comme_sur_sqlite_sans_mutation(moteur):
    moteur.arreter()
    moteur.jeton_contexte = JETON_CONTEXTE_FICTIF
    moteur.demarrer()
    avant = _empreinte(moteur)

    async def emettre():
        http = create_mcp_http_client(headers={"Authorization": f"Bearer {JETON_CONTEXTE_FICTIF}"})
        async with (
            http,
            streamable_http_client(
                f"http://127.0.0.1:{moteur.port}/mcp/contexte/m03-estimation", http_client=http
            ) as flux,
            ClientSession(flux[0], flux[1]) as client,
        ):
            await client.initialize()
            resultat = await client.call_tool(
                "opsys_contexte_creer_ticket_cible",
                {
                    "agent_id": "m03-estimation",
                    "cle_session": "agent:m03-estimation:webchat:direct:refus-pg-fictif",
                    "affaire_id": "lead-pg-fictif",
                    "origine_affaire": "session",
                    "outil": "m3_creer_devis",
                    "arguments": {"lead_id": "lead-pg-fictif", "devis_id": "devis-pg-fictif"},
                },
            )
            assert len(resultat.content) == 1 and resultat.content[0].type == "text"
            return json.loads(resultat.content[0].text)

    refus = anyio.run(emettre)
    assert refus["ok"] is False
    assert refus["erreur"] == "refus_metier"
    assert refus["details"] == "REJ-LIAISON-CIBLE: aucune liaison M10 active vers cette affaire"
    assert _empreinte(moteur) == avant
