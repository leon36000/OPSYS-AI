"""PLAN T4.4 (« sans conversation qui meurt à la porte ») : quand le client cite plusieurs services, M1 lui demande
lequel ; sa réponse doit pouvoir lever l'ambiguïté. Le texte rassemblé évoquait toujours les deux services : la question
n'avait jamais de réponse, et la conversation restait bloquée jusqu'à l'expiration de la fenêtre.

Règle (`conversation.services_retenus`) : quand plusieurs services sont en jeu, un message qui n'en nomme qu'UN est le
choix du client. Ce que ce choix écarte est dit (`services_ecartes`), jamais perdu. Numéros en 555, messages fictifs.
"""

from __future__ import annotations

import datetime as dt

import pytest
from m1_front_office import conversation
from m1_front_office.outils import _obtenir_registre, recevoir_message_canal, reinitialiser_registre

from opsys import taxonomie

NUMERO = "+15145550142"
DEBUT = dt.datetime(2026, 9, 29, 9, 0, tzinfo=dt.timezone(dt.timedelta(hours=-4)))


def _a(minutes: float) -> str:
    return (DEBUT + dt.timedelta(minutes=minutes)).isoformat()


@pytest.fixture(autouse=True)
def _instance(declarer_services):
    declarer_services()
    taxonomie.enregistrer_zone_desservie(["Laval", "Québec"])
    taxonomie.enregistrer_fenetre_conversation(30)
    reinitialiser_registre()
    yield
    reinitialiser_registre()


def _sms(texte: str, message_id: str, minutes: float = 0) -> dict:
    return recevoir_message_canal(
        canal="sms", expediteur=NUMERO, message_id=message_id, recu_le=_a(minutes), texte=texte)


def _codes(contenus: list[str]) -> list[str]:
    services, _ = taxonomie.charger_services()
    return [s.code for s in conversation.services_retenus(contenus, services)]


# -- Le module pur : la règle, message après message -----------------------------------------------------


@pytest.mark.parametrize(("contenus", "retenus"), [
    ([], ["gouttieres", "revetement", "soffite_fascia", "reparation"]),  # rien d'évoqué : rien de retenu
    (["Bonjour."], ["gouttieres", "revetement", "soffite_fascia", "reparation"]),
    (["Mes gouttières fuient."], ["gouttieres"]),
    (["Mes gouttières fuient.", "Encore les gouttières."], ["gouttieres"]),
    (["Gouttières et soffite."], ["gouttieres", "soffite_fascia"]),
    (["Gouttières et soffite.", "Gouttières."], ["gouttieres"]),  # le client choisit
    (["Gouttières et soffite.", "Le soffite d'abord."], ["soffite_fascia"]),
    (["Gouttières et soffite.", "Merci."], ["gouttieres", "soffite_fascia"]),  # aucun choix : on redemande
    (["Gouttières.", "Soffite."], ["gouttieres", "soffite_fascia"]),  # deux services, pas de choix
    (["Gouttières.", "Soffite.", "Gouttières."], ["gouttieres"]),  # le troisième message choisit
    (["Gouttières et soffite.", "Gouttières.", "Aussi le soffite."], ["gouttieres", "soffite_fascia"]),
    (["Gouttières.", "Gouttières et soffite."], ["gouttieres", "soffite_fascia"]),  # un service de plus s'ajoute
    (["Gouttières et soffite et réparation.", "Réparation."], ["reparation"]),
    (["Gouttières et soffite.", "Revêtement."], ["revetement"]),  # le client nomme un autre service : il le choisit
])
def test_un_message_qui_nomme_un_seul_service_quand_plusieurs_sont_en_jeu_est_le_choix_du_client(contenus, retenus):
    assert _codes(contenus) == retenus


# -- Dans la conversation ----------------------------------------------------------------------------------------------


def test_la_reponse_du_client_a_lequel_donne_le_lead_et_dit_ce_qui_est_ecarte():
    premier = _sms("Gouttières et soffite à Laval.", "SM-1", 0)
    assert premier["qualifie"] is False and premier["champs_manquants"] == ["service"]
    assert premier["brouillon_reponse"].endswith(
        "Vous parlez de plusieurs services : Gouttières et descentes, Soffite et fascia. Par lequel souhaitez-vous "
        "commencer?")

    reponse = _sms("Les gouttières en premier.", "SM-2", 2)
    assert reponse["decision"] == "TRANSMETTRE_M2"
    lead = reponse["lead"]
    assert (lead["service"], lead["ville"]) == ("gouttieres", "Laval")
    assert reponse["conversation"]["services_ecartes"] == ["soffite_fascia"], "le soffite n'est pas perdu de vue"
    assert reponse["conversation"]["connu"]["service"] == "gouttieres"
    (ligne_lead,) = [ligne for ligne in _obtenir_registre().lire() if ligne["type_entree"] == "lead_emis"]
    assert ligne_lead["services_ecartes"] == ["soffite_fascia"] and ligne_lead["signaux_rassembles"] == [
        "sms:SM-1", "sms:SM-2"]
    assert "services_ecartes" not in lead, "le contrat v2 est gelé"


def test_un_client_qui_ajoute_un_service_reste_ambigu_et_on_redemande_sans_ecarter_personne():
    _sms("Gouttières à Laval.", "SM-1", 0)  # lead
    reponse = _sms("Et aussi le soffite.", "SM-2", 2)
    assert reponse["decision"] == "CONVERSATION_DEJA_QUALIFIEE"
    assert reponse["complement"]["autre_service_evoque"] is True

    reinitialiser_registre()
    premier = _sms("Gouttières.", "SM-3", 100)
    second = _sms("Aussi le soffite à Laval.", "SM-4", 101)
    assert premier["champs_manquants"] == ["ville"]
    assert second["qualifie"] is False and second["champs_manquants"] == ["service"]
    assert "services_ecartes" not in second["conversation"]


def test_un_message_sans_choix_apres_la_question_laisse_la_question_posee():
    _sms("Gouttières et soffite à Laval.", "SM-1", 0)
    reponse = _sms("Merci de me revenir.", "SM-2", 2)
    assert reponse["qualifie"] is False and reponse["champs_manquants"] == ["service"]
    assert "Par lequel souhaitez-vous commencer" in reponse["brouillon_reponse"]


def test_un_message_qui_cite_encore_plusieurs_services_ne_choisit_pas_et_la_liste_redemandee_reste_celle_d_avant():
    _sms("Gouttières, soffite et réparation à Laval.", "SM-1", 0)
    reponse = _sms("Finalement, le soffite ou les gouttières.", "SM-2", 2)
    assert reponse["qualifie"] is False and reponse["champs_manquants"] == ["service"]
    assert reponse["brouillon_reponse"].endswith(
        "Vous parlez de plusieurs services : Gouttières et descentes, Soffite et fascia, Réparation. "
        "Par lequel souhaitez-vous commencer?"), "seul un message qui nomme UN service choisit"


def test_la_conversation_expiree_ou_fermee_par_stop_ne_garde_pas_le_choix_d_avant():
    _sms("Gouttières et soffite.", "SM-1", 0)
    tard = _sms("Gouttières à Laval.", "SM-2", 120)  # autre conversation : ne rassemble plus le soffite
    assert tard["decision"] == "TRANSMETTRE_M2" and "services_ecartes" not in tard["conversation"]

    reinitialiser_registre()
    _sms("Gouttières et soffite.", "SM-3", 0)
    _sms("STOP", "SM-STOP", 1)
    apres = _sms("Soffite à Laval.", "SM-4", 3)
    assert apres["decision"] == "TRANSMETTRE_M2" and apres["lead"]["service"] == "soffite_fascia"
    assert "services_ecartes" not in apres["conversation"]


def test_sans_fenetre_la_qualification_message_par_message_ne_change_pas():
    fichier = taxonomie.fichier_profil()
    fichier.write_text(fichier.read_text(encoding="utf-8").replace("fenetre_conversation_minutes: 30\n", ""),
                       encoding="utf-8")
    premier = _sms("Gouttières et soffite à Laval.", "SM-1", 0)
    second = _sms("Gouttières.", "SM-2", 1)
    assert premier["qualifie"] is False and second["qualifie"] is False
    assert second["champs_manquants"] == ["ville"], "chaque message est qualifié seul, comme avant"
