"""Identité de jeton d'appareil exposée par le contexte (T1.4-c2). Contrat :
`docs/architecture/IDEMPOTENCE.md` §7 bis."""

from __future__ import annotations

import anyio
import demo_outils
from mcp import Client

from opsys import contexte
from opsys.capacites import Capacites
from opsys.serveur_mcp import creer_serveur

FICTIF = True  # tout identifiant ci-dessous est fictif (AGENTS.md)


# -- contrat pur : depuis_meta_mcp_identite --------------------------------------------------------


def test_depuis_meta_mcp_identite_sans_meta_rend_none():
    assert contexte.depuis_meta_mcp_identite(None) is None
    assert contexte.depuis_meta_mcp_identite({}) is None
    assert contexte.depuis_meta_mcp_identite({"opsys/idempotencyKey": "k"}) is None


def test_depuis_meta_mcp_identite_exige_les_deux_cles():
    assert contexte.depuis_meta_mcp_identite({"opsys/personne": "nathan"}) is None
    assert contexte.depuis_meta_mcp_identite({"opsys/role": "admin"}) is None
    assert contexte.depuis_meta_mcp_identite({"opsys/personne": "", "opsys/role": "admin"}) is None
    assert contexte.depuis_meta_mcp_identite({"opsys/personne": "nathan", "opsys/role": "  "}) is None
    assert contexte.depuis_meta_mcp_identite({"opsys/personne": 1, "opsys/role": "admin"}) is None


def test_depuis_meta_mcp_identite_valide():
    identite = contexte.depuis_meta_mcp_identite({
        "opsys/personne": "jdupont", "opsys/role": "employee", "opsys/idempotencyKey": "k",
    })
    assert identite == contexte.IdentiteAppelante(personne="jdupont", role="employee")


# -- gestionnaire de contexte : imbrication et remise à zéro ---------------------------------------


def test_appele_par_appareil_imbrique_puis_restaure():
    assert contexte.identite_appelante() is None
    exterieur = contexte.IdentiteAppelante("nathan", "nathan_owner")
    interieur = contexte.IdentiteAppelante("jdupont", "employee")
    with contexte.appele_par_appareil(exterieur):
        assert contexte.identite_appelante() == exterieur
        with contexte.appele_par_appareil(interieur):
            assert contexte.identite_appelante() == interieur
        assert contexte.identite_appelante() == exterieur
    assert contexte.identite_appelante() is None


# -- appel MCP de bout en bout : serveur_mcp.appeler_outil expose l'identité -----------------------


def test_appel_mcp_avec_identite_expose_au_contexte(departements_demo, session):
    demo_outils.IDENTITES_VUES.clear()
    serveur = creer_serveur(Capacites(departements_demo, session))
    meta_mcp = {"opsys/personne": "jdupont", "opsys/role": "employee"}

    async def scenario() -> None:
        async with Client(serveur) as client:
            await client.call_tool("m9_voir_identite", {}, meta=meta_mcp)

    anyio.run(scenario)
    assert [contexte.IdentiteAppelante("jdupont", "employee")] == demo_outils.IDENTITES_VUES
    assert contexte.identite_appelante() is None  # jamais visible hors de l'appel


def test_appel_mcp_sans_identite_rend_none_au_contexte(departements_demo, session):
    demo_outils.IDENTITES_VUES.clear()
    serveur = creer_serveur(Capacites(departements_demo, session))

    async def scenario() -> None:
        async with Client(serveur) as client:
            await client.call_tool("m9_voir_identite", {})

    anyio.run(scenario)
    assert demo_outils.IDENTITES_VUES == [None]


def test_appel_mcp_avec_identite_partielle_rend_none_au_contexte(departements_demo, session):
    """Une identité mal formée ne bloque jamais l'appel (à la différence de l'idempotence) : elle
    est simplement absente du contexte — c'est OPSYS-CORE qui a déjà décidé de laisser passer
    l'appel ou non, ce module ne fait que transporter ce qu'il a reçu."""
    demo_outils.IDENTITES_VUES.clear()
    serveur = creer_serveur(Capacites(departements_demo, session))

    async def scenario() -> None:
        async with Client(serveur) as client:
            resultat = await client.call_tool("m9_voir_identite", {}, meta={"opsys/personne": "jdupont"})
            assert resultat.is_error is False

    anyio.run(scenario)
    assert demo_outils.IDENTITES_VUES == [None]
