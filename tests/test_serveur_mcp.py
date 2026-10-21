"""Test de bout en bout du protocole MCP (client officiel ↔ serveur OPSYS en mémoire)."""

from __future__ import annotations

import json
import sys
import types as modules
from pathlib import Path

import anyio
import pytest
from mcp import Client
from sqlalchemy import select

from opsys.capacites import Capacites
from opsys.departements import Budget, Departement, charger_departements
from opsys.outils import Autonomie, Niveau, Outil, executer_atomique
from opsys.serveur_mcp import creer_serveur
from opsys.stockage import codec
from opsys.stockage.schema import APPROBATIONS, EVENEMENTS_SORTANTS


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


def test_toute_reponse_est_un_seul_bloc_texte_portant_une_enveloppe_avec_ok_booleen(departements_demo, session):
    """Ce sur quoi le core s'appuie pour un appel d'appareil (T1.4-c6, `readOpsysEnvelope`) : un seul bloc
    texte, un JSON objet, une clé `ok` booléenne. Vrai pour un succès, un refus métier, une demande en
    attente d'approbation et un outil inconnu ; le core refuse toute autre forme au lieu d'inventer."""
    serveur = creer_serveur(Capacites(departements_demo, session))

    async def scenario():
        async with Client(serveur) as client:
            appels = [
                ("m9_additionner", {"a": 2, "b": 3}),
                ("m9_refuser_si_negatif", {"valeur": -3}),
                ("m9_payer", {"montant": 10}),
                ("m9_outil_qui_n_existe_pas", {}),
            ]
            for nom, arguments in appels:
                reponse = await client.call_tool(nom, arguments)
                assert len(reponse.content) == 1, nom
                assert reponse.content[0].type == "text", nom
                enveloppe = json.loads(reponse.content[0].text)
                assert isinstance(enveloppe, dict), nom
                assert isinstance(enveloppe["ok"], bool), nom

    anyio.run(scenario)


def _annonce(outil) -> tuple:
    a = outil.annotations
    return (a.read_only_hint, a.destructive_hint, a.idempotent_hint, a.open_world_hint)


_DEFINITION_M4_FICTIVE = {
    "metric_id": "m4_duree_reelle_minutes",
    "departement_proprietaire": "m04-field-ops",
    "unite": "min",
    "source": "Module M4 — WCT",
    "fraicheur_attendue_jours": 2,
    "regles_qualite": {"plage_min": None, "plage_max": None},
}


def test_m8_qualite_n2_annonce_son_effet_et_publie_un_fait_via_client_officiel(session):
    """M8 publie `m8.alerte_proposee` sous transaction (tâche interne N2, automatique) : le client
    MCP officiel ne doit pas la voir comme une lecture pure ni comme idempotente."""
    departements = charger_departements(Path(__file__).resolve().parents[1] / "departments")
    capacites = Capacites(departements, session, filtre={"m08-analytics"}, appelant="m08-analytics")
    _dep, evaluateur = capacites.index["m8_evaluer_qualite_metrique"]
    executer_atomique(capacites.index["m8_enregistrer_definition_metrique"][1],
                      {"definition": _DEFINITION_M4_FICTIVE})
    executer_atomique(capacites.index["m8_rapport_metriques"][1], {
        "dictionnaire": {"m04-field-ops": {"m4_duree_reelle_minutes": {}}},
        "snapshot": {"module_source": "m04-field-ops", "horodatage": "2026-01-01T00:00:00Z",
                     "valeurs": {"m4_duree_reelle_minutes": "42"}},
        "metric_ids": ["m4_duree_reelle_minutes"],
        "horodatage_reference": "2026-01-01T00:00:00Z", "n_minimal": 1,
    })
    with session() as cnx:
        assert cnx.execute(select(EVENEMENTS_SORTANTS)).all() == []
        assert cnx.execute(select(APPROBATIONS)).all() == []

    async def scenario():
        async with Client(creer_serveur(capacites)) as client:
            catalogue = {o.name: o for o in (await client.list_tools()).tools}
            reponse = await client.call_tool("m8_evaluer_qualite_metrique", {
                "metric_id": "m4_duree_reelle_minutes", "horodatage_reference": "2026-01-11T00:00:00Z",
            })
            return catalogue["m8_evaluer_qualite_metrique"], reponse

    annonce, reponse = anyio.run(scenario)

    enveloppe = json.loads(reponse.content[0].text)
    assert reponse.is_error is False and enveloppe["ok"] is True and "statut" not in enveloppe
    assert [a["type_alerte"] for a in enveloppe["resultat"]["alertes_proposees"]] == ["REJ-QUALITE-DONNEE-PERIMEE"]
    with session() as cnx:
        publies = cnx.execute(select(EVENEMENTS_SORTANTS.c.type_evenement, EVENEMENTS_SORTANTS.c.producteur,
                                     EVENEMENTS_SORTANTS.c.charge)).all()
        assert cnx.execute(select(APPROBATIONS)).all() == []  # N2 automatique : aucune demande humaine
    assert [(ligne.type_evenement, ligne.producteur) for ligne in publies] == [("m8.alerte_proposee", "m08-analytics")]
    charge = codec.decoder(publies[0].charge)
    assert (charge["type_alerte"], charge["horodatage_reference"]) == ("REJ-QUALITE-DONNEE-PERIMEE",
                                                                      "2026-01-11T00:00:00Z")
    # Le point de publication est atteint : l'annonce MCP doit dire que l'appel écrit.
    assert _annonce(annonce) == (False, False, False, None)
    assert (evaluateur.autonomie, evaluateur.niveau_effectif) == (Autonomie.T0, Niveau.N2)


_effets_fictifs: list[str] = []

_PALIERS = {
    "t0_n0": (Autonomie.T0, Niveau.N0),
    "t0_n1": (Autonomie.T0, Niveau.N1),
    "t0_n2": (Autonomie.T0, Niveau.N2),
    "t1_n3": (Autonomie.T1, None),
    "t2_n4": (Autonomie.T2, None),
    "t3_n5": (Autonomie.T3, None),
}


@pytest.fixture
def capacites_paliers(session, monkeypatch):
    """Département fictif en mode `ombre` (seuil N3) : un outil par palier, effet interne témoin."""
    module = modules.ModuleType("opsys_test_paliers_mcp_fictifs")

    def effet(nom):
        def fonction():
            _effets_fictifs.append(nom)
            return {"effet": nom}
        return fonction

    vide = {"type": "object", "properties": {}, "additionalProperties": False}
    module.OUTILS = tuple(
        Outil(f"m9_palier_{nom}", f"Outil fictif {nom}.", vide, effet(nom), autonomie, niveau=niveau)
        for nom, (autonomie, niveau) in _PALIERS.items()
    )
    monkeypatch.setitem(sys.modules, module.__name__, module)
    _effets_fictifs.clear()
    dep = Departement(
        id="m09-paliers-fictifs", code="M9", nom="Paliers fictifs", mission="test", module_outils=module.__name__,
        mode="ombre", dependances=(), modeles={"defaut": "standard"}, skills=(), planifications=(),
        budget=Budget(1000, 20000), memoire_lecture=(), memoire_ecriture=(), kpis=(), racine=Path("."),
    )
    yield Capacites({dep.id: dep}, session, memoire=False)
    _effets_fictifs.clear()


def _lister_et_appeler(capacites, nom):
    async def scenario():
        async with Client(creer_serveur(capacites)) as client:
            catalogue = {o.name: o for o in (await client.list_tools()).tools}
            return catalogue[nom], await client.call_tool(nom, {})

    return anyio.run(scenario)


@pytest.mark.parametrize(("palier", "attendue"), [
    ("t0_n0", (True, False, True, None)),
    ("t0_n1", (False, False, False, None)),
    ("t0_n2", (False, False, False, None)),
])
def test_annotations_t0_n0_n1_n2_et_appels_automatiques_via_client_officiel(capacites_paliers, session,
                                                                            palier, attendue):
    nom = f"m9_palier_{palier}"
    annonce, reponse = _lister_et_appeler(capacites_paliers, nom)

    assert json.loads(reponse.content[0].text) == {"ok": True, "resultat": {"effet": palier}}
    assert _effets_fictifs == [palier]
    with session() as cnx:
        assert cnx.execute(select(APPROBATIONS)).all() == []
    assert _annonce(annonce) == attendue


@pytest.mark.parametrize(("palier", "niveau", "attendue"), [
    ("t1_n3", "N3", (False, False, None, None)),
    ("t2_n4", "N4", (False, False, None, True)),
    ("t3_n5", "N5", (False, True, None, True)),
])
def test_paliers_t1_t2_t3_conservent_annotations_et_approbations_via_client_officiel(capacites_paliers, session,
                                                                                     palier, niveau, attendue):
    nom = f"m9_palier_{palier}"
    annonce, reponse = _lister_et_appeler(capacites_paliers, nom)

    assert len(reponse.content) == 1 and reponse.content[0].type == "text"
    enveloppe = json.loads(reponse.content[0].text)
    assert enveloppe["ok"] is True and enveloppe["statut"] == "en_attente_approbation"
    assert _effets_fictifs == []  # en attente : la fonction n'est jamais atteinte
    with session() as cnx:
        demandes = cnx.execute(select(APPROBATIONS.c.id, APPROBATIONS.c.outil, APPROBATIONS.c.statut,
                                      APPROBATIONS.c.niveau)).all()
    assert [tuple(d) for d in demandes] == [(enveloppe["demande_id"], nom, "en_attente", niveau)]
    assert _annonce(annonce) == attendue
