"""Ticket de clôture M9 fictif : bus/SQLite/N3 réels, aucun effet terrain."""
from __future__ import annotations

import importlib.util
from copy import deepcopy
from pathlib import Path

import pytest
from sqlalchemy import update

from opsys import liaison_cibles, stockage
from opsys.capacites import Capacites
from opsys.outils import executer_atomique
from opsys.stockage.schema import EVENEMENTS_RECUS, EVENEMENTS_SORTANTS, REGISTRES

_spec = importlib.util.spec_from_file_location(
    "_cloture_cible_m9_base", Path(__file__).with_name("test_suivi_m9_cible_core.py"))
b = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(b)
installation = b.installation
serveur_http = b.serveur_http
CLORE = "m9_clore_suivi_decision"


def _plan_ouvert(installation, session):
    b._lier()
    arguments = b._arguments()
    demande = b._proposer(installation, session, arguments, b._emettre(session, arguments))
    assert b._approuver(installation, session, demande)["statut"] == "executee"
    with session():
        [plan] = list(stockage.maillons(b.M9, "suivi_decisions"))
    return plan, arguments


def _arguments_cloture(installation, session, suivi_id, evenement_id):
    cap = Capacites(installation, session, filtre={b.M9}, appelant=b.M9, memoire=False)
    preparation = cap.appeler("m9_preparer_cloture_suivi_decision", {
        "suivi_id": suivi_id, "evenement_id": evenement_id,
    })
    assert preparation["ok"] is True, preparation
    prep = preparation["resultat"]
    assert prep["accepte"] is True
    return {"suivi_id": suivi_id, "empreinte_suivi": prep["empreinte_suivi"],
            "evenement_id": evenement_id, "empreinte_preuve": prep["preuve"]["empreinte_source"],
            "bilan": "Revue humaine fictive de durée, aucune action terrain attestée."}


def _emettre_cloture(session, arguments):
    with session() as cnx:
        return liaison_cibles.emettre_ticket(
            cnx, departement=b.M9, agent_id=b.M9, cle_session=b.CLE_SESSION,
            affaire_id="lead-cible-fictif-A", origine_affaire="session",
            outil=CLORE, arguments=arguments,
        )


def _proposer_cloture(installation, session, arguments, ticket):
    cap = Capacites(installation, session, filtre={b.M9}, appelant=b.M9, memoire=False)
    return cap.appeler(CLORE, arguments, ticket_cible=liaison_cibles.TicketMeta(ticket["ticket"]))


def _registres_metier():
    with stockage.transaction():
        return {nom: list(stockage.maillons(b.M9, nom))
                for nom in ("suivi_decisions", "clotures_suivi_decisions", "alertes_m8")}


def test_ticket_cloture_originale_exige_son_n3_et_un_seul_effet(installation, session):
    """Sans branche de cible dédiée, aucun ticket de clôture ni parcours N3 n'existe."""
    plan, ouverture = _plan_ouvert(installation, session)
    arguments = _arguments_cloture(installation, session, plan["suivi_id"], ouverture["evenement_id"])
    avant = _registres_metier()
    ticket = _emettre_cloture(session, arguments)
    assert _registres_metier() == avant
    demande = _proposer_cloture(installation, session, arguments, ticket)
    assert demande["statut"] == "en_attente_approbation", demande
    assert demande["demande_id"] != plan["suivi_id"]
    assert _registres_metier() == avant
    decision = b._approuver(installation, session, demande)
    assert decision["statut"] == "executee", decision
    apres = _registres_metier()
    assert apres["suivi_decisions"] == avant["suivi_decisions"] == [plan]
    assert apres["alertes_m8"] == avant["alertes_m8"]
    [cloture] = apres["clotures_suivi_decisions"]
    assert cloture["statut"] == "cloturee_par_revue_humaine"
    assert cloture["suivi_id"] == plan["suivi_id"]
    assert cloture["empreinte_suivi"] == arguments["empreinte_suivi"]
    assert cloture["preuve"]["alerte"] == plan["source"]["alerte"]
    assert cloture["bilan"] == arguments["bilan"]
    assert cloture["decision"]["demande_id"] == demande["demande_id"]
    assert cloture["decision"]["decide_role"] == "nathan_owner"
    tables = b._tables()
    rejeu = _proposer_cloture(installation, session, arguments, ticket)
    assert rejeu["rejoue"] is True
    assert rejeu["resultat"]["cloture"] == cloture
    assert b._tables() == tables


@pytest.mark.parametrize("nouvelle_affaire", ["A", "B"])
def test_cloture_scellee_revalide_affaire_et_ligne_m10(installation, session, nouvelle_affaire):
    plan, ouverture = _plan_ouvert(installation, session)
    args = _arguments_cloture(installation, session, plan["suivi_id"], ouverture["evenement_id"])
    demande = _proposer_cloture(installation, session, args, _emettre_cloture(session, args))
    assert demande["statut"] == "en_attente_approbation"
    b._lier(nouvelle_affaire)
    avant = b._tables()
    with pytest.raises(liaison_cibles.CibleRefusee, match="révoquée|remplacée"):
        b._approuver(installation, session, demande)
    assert b._tables() == avant
    assert _registres_metier()["clotures_suivi_decisions"] == []


def test_ticket_cloture_scelle_tout_le_bilan_avant_demande(installation, session):
    plan, ouverture = _plan_ouvert(installation, session)
    args = _arguments_cloture(installation, session, plan["suivi_id"], ouverture["evenement_id"])
    ticket = _emettre_cloture(session, args)
    avant = b._tables()
    refus = _proposer_cloture(installation, session, args | {"bilan": "Un autre bilan fictif"}, ticket)
    assert refus["erreur"] == "cible_refusee"
    assert b._tables() == avant


@pytest.mark.parametrize("defaut", ["hash_plan", "hash_preuve", "bilan_vide", "bilan_long", "cle_extra",
                                  "preuve_etrangere", "plan_origine_fantome", "plan_alerte_alteree"])
def test_emission_cloture_refuse_preuve_ou_plan_non_lies(installation, session, defaut):
    plan, ouverture = _plan_ouvert(installation, session)
    if defaut in {"plan_origine_fantome", "plan_alerte_alteree"}:
        with session() as cnx:
            if defaut == "plan_origine_fantome":
                plan["source"]["evenement_id"] = "origine-fantome-fictive"
                plan["source"]["alerte"]["evenement_id"] = "origine-fantome-fictive"
                plan["source"]["empreinte_source"] = b.empreinte(plan["source"]["alerte"])
            else:
                # Le hash déclaré reste celui de l'alerte canonique ; modifier l'objet embarqué doit refuser.
                plan["source"]["alerte"]["quoi"] = "Ancienne alerte embarquée fictivement altérée"
            cnx.execute(update(REGISTRES).where(REGISTRES.c.departement == b.M9,
                        REGISTRES.c.registre == "suivi_decisions").values(maillon=b.codec.encoder(plan)))
    args = _arguments_cloture(installation, session, plan["suivi_id"], ouverture["evenement_id"])
    changements = {"hash_plan": {"empreinte_suivi": "0" * 64},
                   "hash_preuve": {"empreinte_preuve": "0" * 64},
                   "bilan_vide": {"bilan": " "}, "bilan_long": {"bilan": "a" * 2001},
                   "cle_extra": {"affaire_id": "lead-cible-fictif-B"},
                   "preuve_etrangere": {"evenement_id": b._arguments("B")["evenement_id"],
                                         "empreinte_preuve": b._arguments("B")["empreinte_source"]}}
    args |= changements.get(defaut, {})
    avant = b._tables()
    with pytest.raises(liaison_cibles.CibleRefusee):
        _emettre_cloture(session, args)
    assert b._tables() == avant


@pytest.mark.parametrize("moment", ["emission", "approbation"])
@pytest.mark.parametrize("defaut", ["publication", "recu", "wct"])
def test_cloture_revalide_la_preuve_canonique_avant_effet(installation, session, moment, defaut):
    plan, ouverture = _plan_ouvert(installation, session)
    args = _arguments_cloture(installation, session, plan["suivi_id"], ouverture["evenement_id"])
    demande = None
    if moment == "approbation":
        demande = _proposer_cloture(installation, session, args, _emettre_cloture(session, args))
        assert demande["statut"] == "en_attente_approbation"
    with session() as cnx:
        if defaut == "publication":
            cnx.execute(update(EVENEMENTS_SORTANTS).where(
                EVENEMENTS_SORTANTS.c.evenement_id == ouverture["evenement_id"]
            ).values(producteur="m08-producteur-fictif-etranger"))
        elif defaut == "recu":
            cnx.execute(update(EVENEMENTS_RECUS).where(
                EVENEMENTS_RECUS.c.evenement_id == ouverture["evenement_id"],
                EVENEMENTS_RECUS.c.consommateur == b.M9,
            ).values(statut="echec"))
        else:
            cnx.execute(update(EVENEMENTS_SORTANTS).where(
                EVENEMENTS_SORTANTS.c.evenement_id == "wct-cible-fictif-A"
            ).values(producteur="m04-producteur-fictif-etranger"))
    avant = b._tables()
    with pytest.raises(liaison_cibles.CibleRefusee):
        if demande is None:
            _emettre_cloture(session, args)
        else:
            b._approuver(installation, session, demande)
    assert b._tables() == avant
    assert _registres_metier()["clotures_suivi_decisions"] == []


def test_ticket_seul_et_approbation_ouverture_ne_cloturent_pas(installation, session):
    plan, ouverture = _plan_ouvert(installation, session)
    args = _arguments_cloture(installation, session, plan["suivi_id"], ouverture["evenement_id"])
    _emettre_cloture(session, args)
    cap = Capacites(installation, session, filtre={b.M9}, appelant=b.M9, memoire=False)
    outil = cap.index[CLORE][1]
    avant = b._tables()
    with b.contexte.executer_demande_approuvee(plan["suivi_id"]):
        reponse = executer_atomique(outil, args)
    assert reponse["resultat"]["accepte"] is False
    assert b._tables() == avant
    assert _registres_metier()["clotures_suivi_decisions"] == []


def test_proprietaire_actuel_revoque_ne_cloture_pas_le_ticket(installation, session):
    plan, ouverture = _plan_ouvert(installation, session)
    args = _arguments_cloture(installation, session, plan["suivi_id"], ouverture["evenement_id"])
    demande = _proposer_cloture(installation, session, args, _emettre_cloture(session, args))
    with session() as cnx:
        b.identite.retirer_role(cnx, b.PROPRIO, "nathan_owner")
    avant = b._tables()
    outils = {nom: entree[1] for nom, entree in Capacites(installation, session, memoire=False).index.items()}
    with session() as cnx, pytest.raises(ValueError):
        b.approbations.decider(cnx, demande["demande_id"], True, b.PROPRIO, outils, installation)
    assert b._tables() == avant


def test_nouveau_proprietaire_peut_clore_le_plan_historique(installation, session):
    plan, ouverture = _plan_ouvert(installation, session)
    with session() as cnx:
        b.identite.retirer_role(cnx, b.PROPRIO, "nathan_owner")
        b.identite.creer_personne(cnx, "nouveau-proprietaire-fictif", "Propriétaire fictif actuel",
                                 "mot-de-passe-fictif-actuel", ["nathan_owner"])
    args = _arguments_cloture(installation, session, plan["suivi_id"], ouverture["evenement_id"])
    demande = _proposer_cloture(installation, session, args, _emettre_cloture(session, args))
    outils = {nom: entree[1] for nom, entree in Capacites(installation, session, memoire=False).index.items()}
    with session() as cnx:
        decision = b.approbations.decider(cnx, demande["demande_id"], True, "nouveau-proprietaire-fictif",
                                         outils, installation)
    assert decision["statut"] == "executee", decision
    [cloture] = _registres_metier()["clotures_suivi_decisions"]
    assert cloture["decision"]["decide_par"] == "nouveau-proprietaire-fictif"
    assert _registres_metier()["suivi_decisions"] == [plan]


def test_fragment_core_garde_la_cloture_non_admise(installation):
    configuration = b.openclaw._configuration_contexte(installation, {b.M9: []})
    assert configuration["niveaux"][CLORE] == "N3"
    assert configuration["cibles"][CLORE] == {"type": "inconnue"}


def _publier_autre_preuve_fictive(installation, plan):
    # Une seconde charge M8 explicitement fictive ; publication/réception réelles,
    # même WCT canonique. Ce test n'atteste pas la génération de cette charge par M8.
    alerte = deepcopy(plan["source"]["alerte"])
    alerte["evenement_id"] = "M8-MESURE-SEUIL-FRANCHI-preuve-cloture-fictive"
    alerte["quoi"] = "Deuxième alerte fictive pour la revue humaine du même chantier"
    b.evenements.publier("m8.alerte_proposee", "m08-analytics", alerte,
                         evenement_id=alerte["evenement_id"])
    tour = b.evenements.repartir(installation, maintenant="2026-10-20T10:00:00-04:00")
    assert tour["echecs"] == tour["quarantaines"] == 0, tour
    return alerte


@pytest.mark.parametrize("moment", ["emission", "approbation"])
@pytest.mark.parametrize("ancrage", ["origine", "choisi"])
@pytest.mark.parametrize("defaut", ["publication", "recu"])
def test_les_deux_alertes_distinctes_exigent_leur_provenance(installation, session, moment, ancrage, defaut):
    plan, ouverture = _plan_ouvert(installation, session)
    autre = _publier_autre_preuve_fictive(installation, plan)
    args = _arguments_cloture(installation, session, plan["suivi_id"], autre["evenement_id"])
    demande = None
    if moment == "approbation":
        demande = _proposer_cloture(installation, session, args, _emettre_cloture(session, args))
        assert demande["statut"] == "en_attente_approbation"
    cible = ouverture["evenement_id"] if ancrage == "origine" else autre["evenement_id"]
    with session() as cnx:
        if defaut == "publication":
            cnx.execute(update(EVENEMENTS_SORTANTS).where(
                EVENEMENTS_SORTANTS.c.evenement_id == cible
            ).values(producteur="producteur-fictif-etranger"))
        else:
            cnx.execute(update(EVENEMENTS_RECUS).where(
                EVENEMENTS_RECUS.c.evenement_id == cible, EVENEMENTS_RECUS.c.consommateur == b.M9,
            ).values(statut="echec"))
    avant = b._tables()
    with pytest.raises(liaison_cibles.CibleRefusee):
        if demande is None:
            _emettre_cloture(session, args)
        else:
            b._approuver(installation, session, demande)
    assert b._tables() == avant
    assert _registres_metier()["clotures_suivi_decisions"] == []


def test_cloture_admet_deux_preuves_canoniques_distinctes_du_meme_chantier(installation, session):
    plan, _ = _plan_ouvert(installation, session)
    autre = _publier_autre_preuve_fictive(installation, plan)
    args = _arguments_cloture(installation, session, plan["suivi_id"], autre["evenement_id"])
    demande = _proposer_cloture(installation, session, args, _emettre_cloture(session, args))
    assert b._approuver(installation, session, demande)["statut"] == "executee"
    apres = _registres_metier()
    assert apres["suivi_decisions"] == [plan]
    [cloture] = apres["clotures_suivi_decisions"]
    assert cloture["preuve"]["alerte"] == autre
    assert cloture["preuve"]["evenement_id"] != plan["source"]["evenement_id"]


def test_mcp_prive_propose_la_cloture_sans_decider_a_la_place_du_proprietaire(
    installation, session, serveur_http,
):
    plan, ouverture = _plan_ouvert(installation, session)
    args = _arguments_cloture(installation, session, plan["suivi_id"], ouverture["evenement_id"])

    async def scenario():
        emission = await b._appeler_http(
            serveur_http, "/mcp/contexte/" + b.M9, "opsys_contexte_creer_ticket_cible",
            {"agent_id": b.M9, "cle_session": b.CLE_SESSION, "affaire_id": "lead-cible-fictif-A",
             "origine_affaire": "session", "outil": CLORE, "arguments": args}, b.JETON_CONTEXTE,
        )
        assert emission["ok"] is True, emission
        return await b._appeler_http(
            serveur_http, "/mcp/" + b.M9, CLORE, args, b.JETON_METIER,
            {"opsys/cibleTicket": emission["resultat"]["ticket"]},
        )

    demande = b.anyio.run(scenario)
    assert demande["statut"] == "en_attente_approbation", demande
    assert _registres_metier()["clotures_suivi_decisions"] == []
    assert b._approuver(installation, session, demande)["statut"] == "executee"
    [cloture] = _registres_metier()["clotures_suivi_decisions"]
    assert cloture["decision"]["demande_id"] == demande["demande_id"]
    assert cloture["suivi_id"] == plan["suivi_id"]
