"""Frontière MCP réelle : lecture authentifiée et refus sans trace des mutations sans clé."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import anyio
import demo_outils
import pytest
from mcp import Client
from sqlalchemy import select

from opsys import contexte, identite
from opsys.capacites import Capacites
from opsys.departements import charger_departements
from opsys.outils import Autonomie, Niveau
from opsys.serveur_mcp import creer_serveur
from opsys.stockage.schema import APPROBATIONS, EVENEMENTS_SORTANTS, JOURNAL, MUTATIONS_APPLIQUEES, REGISTRES

FICTIF = True
IDENTITE = {"opsys/personne": "employe-fictif", "opsys/role": "employee"}


def _etat(session):
    with session() as cnx:
        return {table.name: [dict(ligne) for ligne in cnx.execute(select(table)).mappings()]
                for table in (APPROBATIONS, EVENEMENTS_SORTANTS, JOURNAL, MUTATIONS_APPLIQUEES, REGISTRES)}


@pytest.mark.parametrize("niveau", [Niveau.N1, Niveau.N2, Niveau.N3, Niveau.N4, Niveau.N5])
def test_mcp_refuse_tout_niveau_ecriture_sans_cle_meme_si_t0(departements_demo, session, niveau):
    demo_outils.JOURNAL.clear()
    cap = Capacites(departements_demo, session)
    dept, outil = cap.index["m9_pointer"]
    cap.index[outil.nom] = (dept, dataclasses.replace(outil, autonomie=Autonomie.T0, niveau=niveau))
    avant = _etat(session)

    async def scenario():
        async with Client(creer_serveur(cap)) as client:
            for _ in range(2):
                resultat = await client.call_tool(outil.nom, {"appareil": "cam-fictif"}, meta=IDENTITE)
                assert resultat.is_error is True
                assert json.loads(resultat.content[0].text)["erreur"] == "idempotence_appareil_requise"

    anyio.run(scenario)
    assert demo_outils.JOURNAL == []
    assert _etat(session) == avant
    assert contexte.identite_appelante() is None


def test_mcp_lecture_t0_n0_sans_cle_garde_identite_et_aucune_mutation(departements_demo, session):
    demo_outils.IDENTITES_VUES.clear()
    cap = Capacites(departements_demo, session)
    avant = _etat(session)

    async def scenario():
        async with Client(creer_serveur(cap)) as client:
            resultat = await client.call_tool("m9_voir_identite", {}, meta=IDENTITE)
            assert resultat.is_error is False
            assert json.loads(resultat.content[0].text)["resultat"] == {"vu": True}

    anyio.run(scenario)
    identites_attendues = [contexte.IdentiteAppelante("employe-fictif", "employee")]
    assert identites_attendues == demo_outils.IDENTITES_VUES
    assert _etat(session) == avant
    assert contexte.identite_appelante() is None


def test_mcp_mutation_identifiee_avec_cle_rejoue_une_seule_fois(departements_demo, session):
    demo_outils.JOURNAL.clear()
    cap = Capacites(departements_demo, session)
    meta = {**IDENTITE, "opsys/idempotencyKey": "mutation-fictive",
            "opsys/appareil": "tel-fictif", "opsys/horodatageAppareil": "2026-10-04T00:00:00Z"}

    async def scenario():
        async with Client(creer_serveur(cap)) as client:
            for rejouee in (False, True):
                resultat = await client.call_tool("m9_pointer", {"appareil": "cam-fictif"}, meta=meta)
                donnees = json.loads(resultat.content[0].text)
                assert resultat.is_error is False
                assert donnees["ok"] is True and donnees["rejoue"] is rejouee

    anyio.run(scenario)
    assert demo_outils.JOURNAL == [{"pointage": "cam-fictif"}]
    assert len(_etat(session)[MUTATIONS_APPLIQUEES.name]) == 1


def test_mutation_t1_refusee_et_console_interne_preservee(departements_demo, session):
    demo_outils.JOURNAL.clear()
    cap = Capacites(departements_demo, session)
    avant = _etat(session)
    with contexte.appele_par_appareil(contexte.IdentiteAppelante("employe-fictif", "employee")):
        refus = cap.appeler("m9_pointer", {"appareil": "cam-fictif"})
    assert refus["erreur"] == "idempotence_appareil_requise"
    assert demo_outils.JOURNAL == [] and _etat(session) == avant
    with contexte.appele_par_appareil(contexte.IdentiteAppelante("owner-fictif", "nathan_owner", source="console")):
        resultat = cap.appeler("m9_pointer", {"appareil": "cam-fictif"})
    assert resultat["ok"] is True
    assert demo_outils.JOURNAL == [{"pointage": "cam-fictif"}]
    assert not _etat(session)[MUTATIONS_APPLIQUEES.name]


def test_mcp_mutation_sans_identite_garde_le_protocole_agent(departements_demo, session):
    demo_outils.JOURNAL.clear()
    cap = Capacites(departements_demo, session)

    async def scenario():
        async with Client(creer_serveur(cap)) as client:
            resultat = await client.call_tool("m9_pointer", {"appareil": "cam-fictif"})
            assert resultat.is_error is False

    anyio.run(scenario)
    assert demo_outils.JOURNAL == [{"pointage": "cam-fictif"}]
    assert not _etat(session)[MUTATIONS_APPLIQUEES.name]


@pytest.mark.parametrize("departement,nom,arguments,identite_meta", [
    ("m04-field-ops", "m4_demarrer_route", {
        "intervention_id": "intervention-fictive", "technicien_id": "employe-fictif",
        "horodatage": "2026-10-04T00:00:00Z",
    }, IDENTITE),
    ("m07-marketing", "m7_importer_avis_manuel", {}, IDENTITE),
    ("m07-marketing", "m7_exporter_reponse_avis_manuel", {"avis_id": "avis-fictif"},
     {"opsys/personne": "proprio-fictif", "opsys/role": "admin"}),
])
def test_registre_metier_reel_refuse_mutations_appareil_sans_cle(
    session, departement, nom, arguments, identite_meta,
):
    departements = charger_departements(Path(__file__).resolve().parents[1] / "departments")
    cap = Capacites(departements, session, filtre={departement}, appelant=departement)
    outil = cap.index[nom][1]
    assert identite_meta["opsys/role"] in outil.roles_appareil
    avant = _etat(session)

    async def scenario():
        async with Client(creer_serveur(cap)) as client:
            resultat = await client.call_tool(nom, arguments, meta=identite_meta)
            assert resultat.is_error is True
            assert json.loads(resultat.content[0].text)["erreur"] == "idempotence_appareil_requise"

    anyio.run(scenario)
    assert _etat(session) == avant


@pytest.fixture
def consentement_marketing(session):
    with session() as cnx:
        identite.creer_personne(cnx, "employe-fictif", "Employé fictif", "mot-de-passe-fictif-1234", ["employee"])
    departements = charger_departements(Path(__file__).resolve().parents[1] / "departments")
    cap = Capacites(departements, session, filtre={"m07-marketing"}, appelant="m07-marketing")
    arguments = {
        "consentement_id": "consentement-fictif",
        "personne_ref": "client-fictif",
        "texte_consentement": "Consentement fictif à une référence locale",
        "source_preuve": "preuve-fictive",
        "horodatage": "2026-10-04T00:00:00Z",
    }
    return cap, arguments


def test_consentement_marketing_sans_cle_ne_cree_aucune_preuve(session, consentement_marketing):
    cap, arguments = consentement_marketing
    avant = _etat(session)

    async def scenario():
        async with Client(creer_serveur(cap)) as client:
            resultat = await client.call_tool("m7_enregistrer_consentement_reference", arguments, meta=IDENTITE)
            assert resultat.is_error is True
            assert json.loads(resultat.content[0].text)["erreur"] == "idempotence_appareil_requise"

    anyio.run(scenario)
    assert _etat(session) == avant


def test_consentement_marketing_avec_cle_rejoue_une_seule_preuve(session, consentement_marketing):
    cap, arguments = consentement_marketing
    meta = {**IDENTITE, "opsys/idempotencyKey": "consentement-fictif",
            "opsys/appareil": "tel-fictif", "opsys/horodatageAppareil": "2026-10-04T00:00:00Z"}

    async def scenario():
        async with Client(creer_serveur(cap)) as client:
            for rejouee in (False, True):
                resultat = await client.call_tool("m7_enregistrer_consentement_reference", arguments, meta=meta)
                donnees = json.loads(resultat.content[0].text)
                assert resultat.is_error is False
                assert donnees["resultat"]["statut"] == "consentement_enregistre"
                assert donnees["rejoue"] is rejouee

    anyio.run(scenario)
    with session() as cnx:
        preuves = [json.loads(ligne["maillon"]) for ligne in cnx.execute(select(REGISTRES)).mappings()
                   if ligne["registre"] == "local_campaigns"
                   and json.loads(ligne["maillon"]).get("type") == "consentement_reference"]
        assert len(preuves) == 1
        assert preuves[0]["saisi_par"] == "employe-fictif"
    assert len(_etat(session)[MUTATIONS_APPLIQUEES.name]) == 1


@pytest.mark.parametrize("nom", [
    "m7_enregistrer_consentement_reference", "m7_exporter_reponse_avis_manuel", "m7_importer_avis_manuel",
])
def test_catalogue_mcp_ne_presente_pas_les_ecritures_marketing_comme_lectures(session, nom):
    departements = charger_departements(Path(__file__).resolve().parents[1] / "departments")
    cap = Capacites(departements, session, filtre={"m07-marketing"}, appelant="m07-marketing")

    async def scenario():
        async with Client(creer_serveur(cap)) as client:
            catalogue = {outil.name: outil for outil in (await client.list_tools()).tools}
            assert catalogue[nom].annotations.read_only_hint is False

    anyio.run(scenario)


def test_identite_appareil_ne_peut_pas_lire_la_memoire(departements_demo, session):
    cap = Capacites(departements_demo, session)
    assert "opsys_memoire_rechercher" in cap.index
    avant = _etat(session)
    with contexte.appele_par_appareil(contexte.IdentiteAppelante("employe-fictif", "employee")):
        resultat = cap.appeler("opsys_memoire_rechercher", {"requete": "information privee fictive"})
    assert resultat["ok"] is False
    assert "MEMOIRE-APPAREIL-FERME" in resultat["details"]
    assert _etat(session) == avant


@pytest.mark.parametrize("enveloppe", [
    {"opsys/appareil": "tel-fictif"},
    {"opsys/horodatageAppareil": "2026-10-04T00:00:00Z"},
    {"opsys/idempotencyKey": ""},
])
def test_mcp_enveloppe_partielle_ne_devient_pas_une_lecture_sans_idempotence(
    departements_demo, session, enveloppe,
):
    cap = Capacites(departements_demo, session)
    avant = _etat(session)

    async def scenario():
        async with Client(creer_serveur(cap)) as client:
            resultat = await client.call_tool("m9_additionner", {"a": 2, "b": 3}, meta={**IDENTITE, **enveloppe})
            assert resultat.is_error is True
            assert json.loads(resultat.content[0].text)["erreur"] == "meta_invalide"

    anyio.run(scenario)
    assert _etat(session) == avant
