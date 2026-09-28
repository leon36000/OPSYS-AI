"""Test de bout en bout du protocole MCP (client officiel ↔ serveur OPSYS en mémoire)."""

from __future__ import annotations

import json

import anyio
from mcp import Client

from opsys.capacites import Capacites
from opsys.serveur_mcp import creer_serveur


def test_protocole_mcp_liste_et_appel(departements_demo, session):
    serveur = creer_serveur(Capacites(departements_demo, session))

    async def scenario():
        async with Client(serveur) as client:
            outils = await client.list_tools()
            par_nom = {o.name: o for o in outils.tools}
            assert par_nom["m9_additionner"].annotations.read_only_hint is True
            assert par_nom["m9_payer"].annotations.destructive_hint is True
            assert par_nom["m9_additionner"].input_schema["required"] == ["a", "b"]

            somme = await client.call_tool("m9_additionner", {"a": 2, "b": 3})
            assert somme.is_error is False
            assert json.loads(somme.content[0].text) == {"ok": True, "resultat": {"somme": "5"}}

            paiement = await client.call_tool("m9_payer", {"montant": 10})
            donnees = json.loads(paiement.content[0].text)
            assert donnees["statut"] == "en_attente_approbation"

            refus = await client.call_tool("m9_refuser_si_negatif", {"valeur": -3})
            assert refus.is_error is True

    anyio.run(scenario)
