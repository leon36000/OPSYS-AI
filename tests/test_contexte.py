"""Identité de jeton d'appareil exposée par le contexte (T1.4-c2). Contrat :
`docs/architecture/IDEMPOTENCE.md` §7 bis."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from threading import Barrier

import anyio
import demo_outils
import pytest
from mcp import Client

from opsys import contexte
from opsys.capacites import Capacites
from opsys.serveur_mcp import creer_serveur

FICTIF = True  # tout identifiant ci-dessous est fictif (AGENTS.md)


def test_formulaire_signe_copie_immutable_et_absence_distincte():
    signal = "formulaire:site-fictif:nonce-fictif"
    utm = {"utm_source": "facebook", "utm_medium": "social"}
    assert contexte.formulaire_signe_courant() is None
    assert contexte.verifier_formulaire_signe(signal, utm) is False
    with contexte.reception_formulaire_signee(signal, utm):
        capture = contexte.formulaire_signe_courant()
        utm["utm_source"] = "google"
        assert capture.utm == (("utm_medium", "social"), ("utm_source", "facebook"))
        with pytest.raises(FrozenInstanceError):
            capture.signal_id = "formulaire:autre-fictif"
        assert contexte.verifier_formulaire_signe(signal, dict(reversed(capture.utm))) is True
        with pytest.raises(ValueError, match="REJ-FORMULAIRE-SIGNE-INCOHERENT"):
            contexte.verifier_formulaire_signe(signal, utm)
        with pytest.raises(ValueError, match="REJ-FORMULAIRE-SIGNE-INCOHERENT"):
            contexte.verifier_formulaire_signe(signal, None)
    with contexte.reception_formulaire_signee(signal, None):
        assert contexte.formulaire_signe_courant().utm is None
        assert contexte.verifier_formulaire_signe(signal, None) is True
    assert contexte.formulaire_signe_courant() is None


def test_formulaire_signe_restaure_portee_imbriquee_et_exception():
    with contexte.reception_formulaire_signee("formulaire:exterieur-fictif", None):
        capture = contexte.formulaire_signe_courant()
        with (
            pytest.raises(RuntimeError, match="panne fictive"),
            contexte.reception_formulaire_signee("formulaire:interieur-fictif", {"utm_source": "google"}),
        ):
            assert contexte.formulaire_signe_courant() is not capture
            raise RuntimeError("panne fictive")
        assert contexte.formulaire_signe_courant() is capture
    assert contexte.formulaire_signe_courant() is None


def test_formulaire_signe_contextes_threads_concurrents_isoles():
    barriere = Barrier(2)

    def worker(signal, source):
        assert contexte.formulaire_signe_courant() is None
        with contexte.reception_formulaire_signee(signal, {"utm_source": source}):
            barriere.wait(timeout=5)
            assert contexte.verifier_formulaire_signe(signal, {"utm_source": source}) is True
            capture = contexte.formulaire_signe_courant()
        assert contexte.formulaire_signe_courant() is None
        return capture.signal_id, capture.utm

    with (
        contexte.reception_formulaire_signee("formulaire:parent-fictif", None),
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        a = pool.submit(worker, "formulaire:a-fictif", "facebook")
        b = pool.submit(worker, "formulaire:b-fictif", "google")
        assert a.result(timeout=10) == ("formulaire:a-fictif", (("utm_source", "facebook"),))
        assert b.result(timeout=10) == ("formulaire:b-fictif", (("utm_source", "google"),))
        assert contexte.formulaire_signe_courant().signal_id == "formulaire:parent-fictif"
    assert contexte.formulaire_signe_courant() is None


def test_formulaire_signe_portee_presente_invalide_ne_devient_pas_legacy():
    token = contexte._FORMULAIRE_SIGNE.set(object())
    try:
        with pytest.raises(ValueError, match="REJ-FORMULAIRE-SIGNE-INCOHERENT"):
            contexte.verifier_formulaire_signe("formulaire:fictif", None)
    finally:
        contexte._FORMULAIRE_SIGNE.reset(token)
    assert contexte.formulaire_signe_courant() is None


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
    identite = contexte.depuis_meta_mcp_identite(
        {
            "opsys/personne": "jdupont",
            "opsys/role": "employee",
            "opsys/idempotencyKey": "k",
        }
    )
    assert identite == contexte.IdentiteAppelante(personne="jdupont", role="employee")


def test_meta_mcp_ne_peut_pas_declarer_une_session_console():
    identite = contexte.depuis_meta_mcp_identite(
        {
            "opsys/personne": "nathan",
            "opsys/role": "nathan_owner",
            "opsys/source": "console",
            "source": "console",
        }
    )
    assert identite.source == "appareil"


# -- gestionnaire de contexte : imbrication et remise à zéro ---------------------------------------


def test_appele_par_appareil_imbrique_puis_restaure():
    assert contexte.identite_appelante() is None


def test_departement_origine_reste_distinct_du_departement_executeur():
    assert contexte.departement_origine_appelante() is None
    with contexte.appeler_en_tant_que("m10-memoire", origine="m01-front-office"):
        assert contexte.DEPARTEMENT_APPELANT.get() == "m10-memoire"
        assert contexte.departement_origine_appelante() == "m01-front-office"
        with contexte.appeler_en_tant_que("m09-strategic-intelligence"):
            assert contexte.DEPARTEMENT_APPELANT.get() == "m09-strategic-intelligence"
            assert contexte.departement_origine_appelante() == "m09-strategic-intelligence"
        assert contexte.departement_origine_appelante() == "m01-front-office"
    assert contexte.departement_origine_appelante() is None
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


# -- T1.4-c4 : l'identité ne peut arriver que par le chemin authentifié (_meta), jamais un argument -


def test_identite_appelante_ignore_les_arguments_de_loutil(departements_demo, session):
    """Preuve que le socle retire la mise en garde « non authentifié » de `identite_appelante()`
    (PLAN T1.4-c4) en toute sécurité : même un argument d'outil qui PRÉTEND porter un rôle
    (`pretend_role="nathan_owner"`, une valeur qu'un modèle halluciné ou un client compromis
    pourrait produire) n'influence jamais l'identité exposée — seul `_meta` (que OPSYS-CORE
    n'attribue plus que depuis un jeton d'appareil vérifié, jamais depuis le corps de la requête,
    T1.4-c4 côté core) le peut. Structurellement garanti ici :
    `depuis_meta_mcp_identite` (contexte.py) ne reçoit que `meta` en paramètre, jamais les
    arguments — ce test l'exerce de bout en bout par un vrai appel MCP plutôt que de le déduire de
    la seule signature."""
    demo_outils.IDENTITES_VUES.clear()
    serveur = creer_serveur(Capacites(departements_demo, session))
    meta_mcp = {"opsys/personne": "jdupont", "opsys/role": "employee"}

    async def scenario() -> None:
        async with Client(serveur) as client:
            await client.call_tool(
                "m9_voir_identite_avec_argument",
                {"pretend_role": "nathan_owner"},
                meta=meta_mcp,
            )

    anyio.run(scenario)
    # L'identité vue est EXACTEMENT celle de `_meta` : jamais celle suggérée par l'argument, et
    # jamais une fusion des deux.
    assert [contexte.IdentiteAppelante("jdupont", "employee")] == demo_outils.IDENTITES_VUES


def test_identite_appelante_absente_meme_avec_un_argument_qui_pretend_en_porter_une(
    departements_demo,
    session,
):
    """Même sans `_meta` du tout, un argument suggestif ne crée jamais d'identité au contexte."""
    demo_outils.IDENTITES_VUES.clear()
    serveur = creer_serveur(Capacites(departements_demo, session))

    async def scenario() -> None:
        async with Client(serveur) as client:
            await client.call_tool(
                "m9_voir_identite_avec_argument",
                {"pretend_role": "nathan_owner"},
            )

    anyio.run(scenario)
    assert demo_outils.IDENTITES_VUES == [None]
