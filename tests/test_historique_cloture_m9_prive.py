"""Historique fictif de clôture : vrai HTTP privé, SQLite et N3, aucune reprise métier."""
from __future__ import annotations

import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import pytest
from sqlalchemy import delete, select, update

from opsys import liaison_cibles
from opsys.stockage.schema import APPROBATIONS, LIAISONS_TICKETS, OPSYS_INSTANCE

_spec = importlib.util.spec_from_file_location(
    "_historique_cloture_m9_base", Path(__file__).with_name("test_cloture_suivi_m9_cible_core.py"))
c = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(c)
b = c.b
installation = c.installation
serveur_http = c.serveur_http
ecritures_lecture_m9 = b.ecritures_lecture_m9


def _proposition(installation, session):
    plan, ouverture = c._plan_ouvert(installation, session)
    args = c._arguments_cloture(installation, session, plan["suivi_id"], ouverture["evenement_id"])
    ticket = c._emettre_cloture(session, args)
    demande = c._proposer_cloture(installation, session, args, ticket)
    assert demande["statut"] == "en_attente_approbation"
    assert plan["suivi_id"] != demande["demande_id"]
    return plan, args, ticket, demande


def _lecture(ticket, demande):
    return b._arguments_lecture_privee(ticket, demande) | {"outil": c.CLORE}


def test_historique_cloture_confirme_son_n3_distinct_sans_ecriture(
    installation, serveur_http, session, ecritures_lecture_m9,
):
    plan, args, ticket, demande = _proposition(installation, session)
    decision = b._approuver(installation, session, demande)
    assert decision["statut"] == "executee"
    assert decision["reponse"]["resultat"]["cloture"]["decision"]["demande_id"] == demande["demande_id"]
    assert decision["reponse"]["resultat"]["suivi"]["suivi_id"] == plan["suivi_id"] != demande["demande_id"]
    with session() as cnx:
        instance = cnx.execute(select(OPSYS_INSTANCE.c.instance_id)).scalar_one()
    reponse = b._lire_sans_ecriture(serveur_http, _lecture(ticket, demande), ecritures_lecture_m9)
    assert reponse["resultat"] == {"schema": 1, "confirme": True, "instance_id": instance,
                                   "demande_id": demande["demande_id"], "outil": c.CLORE}
    assert ticket["ticket"] not in json.dumps(reponse)
    assert liaison_cibles.empreinte_ticket(ticket["ticket"]) not in json.dumps(reponse)
    assert args["bilan"] not in json.dumps(reponse)


def test_emission_cloture_porte_la_meme_identite_native(installation, session):
    _, _, ticket, _ = _proposition(installation, session)
    with session() as cnx:
        instance = cnx.execute(select(OPSYS_INSTANCE.c.instance_id)).scalar_one()
    assert ticket["instance_id"] == instance


def test_historique_cloture_admet_preuve_distincte_du_plan(
    installation, serveur_http, session, ecritures_lecture_m9,
):
    plan, _ = c._plan_ouvert(installation, session)
    autre = c._publier_autre_preuve_fictive(installation, plan)
    args = c._arguments_cloture(installation, session, plan["suivi_id"], autre["evenement_id"])
    ticket = c._emettre_cloture(session, args)
    demande = c._proposer_cloture(installation, session, args, ticket)
    decision = b._approuver(installation, session, demande)
    assert decision["statut"] == "executee"
    assert decision["reponse"]["resultat"]["cloture"]["preuve"]["evenement_id"] != plan["source"]["evenement_id"]
    reponse = b._lire_sans_ecriture(serveur_http, _lecture(ticket, demande), ecritures_lecture_m9)
    assert reponse["resultat"]["confirme"] is True
    assert reponse["resultat"]["demande_id"] == demande["demande_id"] != plan["suivi_id"]


def test_emission_cloture_sans_identite_refuse_sans_ticket(installation, session):
    plan, ouverture = c._plan_ouvert(installation, session)
    args = c._arguments_cloture(installation, session, plan["suivi_id"], ouverture["evenement_id"])
    with session() as cnx:
        cnx.execute(delete(OPSYS_INSTANCE))
    avant = b._tables()
    with pytest.raises(liaison_cibles.CibleRefusee, match="identité"):
        c._emettre_cloture(session, args)
    assert b._tables() == avant


@pytest.mark.parametrize("etat", ["pending", "refus"])
def test_cloture_en_attente_ou_refusee_ne_confirme_pas(
    installation, serveur_http, session, ecritures_lecture_m9, etat,
):
    _, _, ticket, demande = _proposition(installation, session)
    if etat == "refus":
        outils = {nom: entree[1] for nom, entree in b.Capacites(installation, session, memoire=False).index.items()}
        with session() as cnx:
            assert b.approbations.decider(
                cnx, demande["demande_id"], False, b.PROPRIO, outils, installation,
            )["statut"] == "refusee"
    reponse = b._lire_sans_ecriture(serveur_http, _lecture(ticket, demande), ecritures_lecture_m9)
    assert reponse["resultat"]["confirme"] is False
    assert reponse["resultat"]["outil"] == c.CLORE
    assert c._registres_metier()["clotures_suivi_decisions"] == []


@pytest.mark.parametrize("outil", [None, b.OUVRIR, "outil-fictif-inconnu"])
def test_historique_cloture_exige_son_outil_explicite(
    installation, serveur_http, session, ecritures_lecture_m9, outil,
):
    _, _, ticket, demande = _proposition(installation, session)
    assert b._approuver(installation, session, demande)["statut"] == "executee"
    args = b._arguments_lecture_privee(ticket, demande)
    if outil is not None:
        args["outil"] = outil
    reponse = b._lire_sans_ecriture(serveur_http, args, ecritures_lecture_m9, succes=False)
    assert reponse["ok"] is False and "resultat" not in reponse


def test_historique_ouverture_executee_ne_confirme_pas_cloture(
    installation, serveur_http, session, ecritures_lecture_m9,
):
    b._lier()
    args = b._arguments()
    ticket = b._emettre(session, args)
    demande = b._proposer(installation, session, args, ticket)
    assert b._approuver(installation, session, demande)["statut"] == "executee"
    reponse = b._lire_sans_ecriture(serveur_http, _lecture(ticket, demande), ecritures_lecture_m9, succes=False)
    assert reponse["ok"] is False
    # Le défaut historique d'ouverture et l'ouverture explicite restent compatibles.
    for lecture in [b._arguments_lecture_privee(ticket, demande),
                    b._arguments_lecture_privee(ticket, demande) | {"outil": b.OUVRIR}]:
        assert b._lire_sans_ecriture(serveur_http, lecture, ecritures_lecture_m9)["resultat"]["confirme"] is True


@pytest.mark.parametrize("apres", ["expiration", "ancien_proprietaire_inactif"])
def test_historique_cloture_conserve_effet_deja_commis(
    installation, serveur_http, session, ecritures_lecture_m9, apres,
):
    _, _, ticket, demande = _proposition(installation, session)
    assert b._approuver(installation, session, demande)["statut"] == "executee"
    with session() as cnx:
        if apres == "expiration":
            cnx.execute(update(LIAISONS_TICKETS).where(
                LIAISONS_TICKETS.c.ticket_hash == liaison_cibles.empreinte_ticket(ticket["ticket"]),
            ).values(expire_le="2000-01-01T00:00:00+00:00"))
        else:
            b.identite.activer(cnx, b.PROPRIO, False)
    reponse = b._lire_sans_ecriture(serveur_http, _lecture(ticket, demande), ecritures_lecture_m9)
    assert reponse["resultat"]["confirme"] is True


@pytest.mark.parametrize("corruption", [
    "cache_seul", "ancien_succes_ouverture", "plan_id_egal_demande_cloture", "cloture_suivi_id",
    "decision_id", "decision_role", "decision_auteur", "decision_date",
    "plan_schema_booleen", "cloture_schema_booleen", "bilan",
    "preuve_evenement", "preuve_hash", "plan_source", "etat", "accepte_entier", "ok_entier", "cle_extra",
])
def test_historique_cloture_refuse_caches_concordants_mais_non_approuves(
    installation, serveur_http, session, ecritures_lecture_m9, corruption,
):
    plan, _, ticket, demande = _proposition(installation, session)
    decision = b._approuver(installation, session, demande)
    assert decision["statut"] == "executee"
    rep = deepcopy(decision["reponse"])
    contenu = rep["resultat"]
    cloture = contenu["cloture"]
    if corruption == "ancien_succes_ouverture":
        rep["resultat"] = {"accepte": True, "suivi": plan}
    elif corruption == "plan_id_egal_demande_cloture":
        contenu["suivi"]["suivi_id"] = demande["demande_id"]
    elif corruption == "cloture_suivi_id":
        cloture["suivi_id"] = "0" * 12
    elif corruption == "decision_id":
        cloture["decision"]["demande_id"] = plan["suivi_id"]
    elif corruption == "decision_role":
        cloture["decision"]["decide_role"] = "employee"
    elif corruption == "decision_auteur":
        cloture["decision"]["decide_par"] = b.RESPONSABLE
    elif corruption == "decision_date":
        cloture["decision"]["decide_le"] = "2026-10-19T10:00:00+00:00"
    elif corruption == "plan_schema_booleen":
        contenu["suivi"]["schema"] = True
    elif corruption == "cloture_schema_booleen":
        cloture["schema"] = True
    elif corruption in {"bilan", "cache_seul"}:
        cloture["bilan"] = "Bilan fictif jamais approuvé."
    elif corruption == "preuve_evenement":
        cloture["preuve"]["evenement_id"] = "evenement-fictif-etranger"
    elif corruption == "preuve_hash":
        cloture["preuve"]["empreinte_source"] = "0" * 64
    elif corruption == "plan_source":
        contenu["suivi"]["source"]["alerte"]["quoi"] = "Preuve historique fictivement altérée"
    elif corruption == "etat":
        contenu["etat_suivi"] = "planifiee"
    elif corruption == "accepte_entier":
        contenu["accepte"] = 1
    elif corruption == "ok_entier":
        rep["ok"] = 1
    else:
        cloture["annexe_non_approuvee"] = "fictif"
    with session() as cnx:
        cnx.execute(update(LIAISONS_TICKETS).where(
            LIAISONS_TICKETS.c.ticket_hash == liaison_cibles.empreinte_ticket(ticket["ticket"]),
        ).values(reponse=json.dumps(rep)))
        if corruption != "cache_seul":
            cnx.execute(update(APPROBATIONS).where(APPROBATIONS.c.id == demande["demande_id"]).values(
                resultat=json.dumps(rep),
            ))
    reponse = b._lire_sans_ecriture(serveur_http, _lecture(ticket, demande), ecritures_lecture_m9, succes=False)
    assert reponse["ok"] is False and "resultat" not in reponse


@pytest.mark.parametrize("liaison", ["A", "B"])
def test_historique_cloture_exige_encore_exacte_ligne_m10(
    installation, serveur_http, session, ecritures_lecture_m9, liaison,
):
    _, _, ticket, demande = _proposition(installation, session)
    assert b._approuver(installation, session, demande)["statut"] == "executee"
    b._lier(liaison)
    reponse = b._lire_sans_ecriture(serveur_http, _lecture(ticket, demande), ecritures_lecture_m9, succes=False)
    assert reponse["ok"] is False
