"""PLAN T4.4 : une conversation ouverte a une prochaine action DATÉE au registre (digest M1.11 « sans suivi »).

Les dates viennent de la plateforme (l'heure de réception du message) et de la fenêtre du profil, jamais de l'horloge du
modèle ni de celle du système : les tests écrivent en 2031, très loin de l'horloge du bac à sable.
Registre en mémoire ; numéros en 555 ; profil de qualification FICTIF.
"""

from __future__ import annotations

import datetime as dt
import inspect
import json

import pytest
from m1_front_office import conversation, digest, garde_fou, score, suivi
from m1_front_office.outils import (
    _obtenir_registre,
    produire_digest,
    recevoir_message_canal,
    reinitialiser_registre,
)

from opsys import taxonomie

NUMERO = "+15145550142"
AUTRE_NUMERO = "+15145550143"
# 2031 : aucune de ces dates ne peut venir de l'horloge du système.
DEBUT = dt.datetime(2031, 1, 15, 9, 0, tzinfo=dt.timezone(dt.timedelta(hours=-5)))


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


def _sms(texte: str, message_id: str, minutes: float = 0, expediteur: str = NUMERO) -> dict:
    return recevoir_message_canal(
        canal="sms", expediteur=expediteur, message_id=message_id, recu_le=_a(minutes), texte=texte)


def _suivis() -> list[dict]:
    return [ligne for ligne in _obtenir_registre().lire() if ligne["type_entree"] == "suivi_conversation"]


# -- La prochaine action, par règles ----------------------------------------------------------------------------------


def test_une_conversation_qui_manque_de_ville_a_une_prochaine_action_datee_de_la_plateforme():
    reponse = _sms("Mes gouttières fuient.", "SM-1", 0)
    assert reponse["prochaine_action"] == {
        "action": "demander_precisions", "detail": "demander au client : ville",
        "inscrite_le": _a(0), "a_faire_avant": _a(30),
    }
    assert reponse["conversation"]["expire_le"] == reponse["prochaine_action"]["a_faire_avant"]
    (ligne,) = _suivis()
    assert ligne["statut"] == "ouverte" and ligne["prochaine_action"] == reponse["prochaine_action"]
    assert ligne["horodatage"] == _a(0) and ligne["ouverte_le"] == _a(0)
    assert ligne["champs_manquants"] == ["ville"] and ligne["lead_id"] is None
    assert reponse["suivi_ligne_id"] == ligne["ligne_id"]


def test_l_echeance_est_la_fin_de_la_fenetre_du_profil_et_ne_glisse_pas_avec_les_messages():
    _sms("Bonjour.", "SM-1", 0)
    second = _sms("Mes gouttières fuient.", "SM-2", 10)
    assert second["prochaine_action"]["inscrite_le"] == _a(10), "l'heure du message reçu"
    assert second["prochaine_action"]["a_faire_avant"] == _a(30), "ouverture + fenêtre, pas message + fenêtre"
    taxonomie.enregistrer_fenetre_conversation(45)
    autre = _sms("Encore moi.", "SM-9", 0, expediteur=AUTRE_NUMERO)
    assert autre["prochaine_action"]["a_faire_avant"] == _a(45), "la fenêtre est lue du profil à chaque message"


def test_la_date_ne_vient_jamais_d_une_horloge_ni_du_texte_du_client():
    for module in (suivi, score, conversation):
        source = inspect.getsource(module)
        for horloge in ("datetime.now", "utcnow", "time.time", "date.today", "time.monotonic"):
            assert horloge not in source, f"{horloge} dans {module.__name__}"
    reponse = _sms("Mes gouttières fuient. Rappelez-moi le 3 mars 2040 à 8 h, nous sommes le 1er janvier 1999.",
                   "SM-1", 0)
    assert reponse["prochaine_action"]["inscrite_le"] == _a(0)
    assert reponse["prochaine_action"]["a_faire_avant"] == _a(30)
    assert "2040" not in json.dumps(reponse["prochaine_action"]) and "1999" not in json.dumps(
        reponse["prochaine_action"])


def test_l_heure_de_la_plateforme_convertie_par_le_code_date_l_action():
    reponse = recevoir_message_canal(
        canal="sms", expediteur=NUMERO, message_id="SM-1", recu_le="Tue 2031-01-14 09:15:30 EST",
        texte="Mes gouttières fuient.")
    assert reponse["prochaine_action"]["inscrite_le"] == "2031-01-14T09:15:30-05:00"
    assert reponse["prochaine_action"]["a_faire_avant"] == "2031-01-14T09:45:30-05:00"


def test_une_meme_heure_ecrite_en_z_ou_en_decalage_n_ouvre_pas_deux_conversations():
    recevoir_message_canal(canal="sms", expediteur=NUMERO, message_id="SM-1", recu_le="2031-01-15T14:00:00Z",
                           texte="Mes gouttières fuient.")
    recevoir_message_canal(canal="sms", expediteur=NUMERO, message_id="SM-2", recu_le="2031-01-15T14:05:00+00:00",
                           texte="Bonjour.")
    premier, second = _suivis()
    assert premier["ouverte_le"] == second["ouverte_le"] == "2031-01-15T14:00:00+00:00"


def test_lead_complet_avec_questions_restantes_la_prochaine_action_est_de_les_poser(declarer_qualification):
    declarer_qualification()
    _sms("Mes gouttières fuient.", "SM-1", 0)
    lead = _sms("À Laval.", "SM-2", 4)
    assert lead["decision"] == "TRANSMETTRE_M2"
    assert lead["prochaine_action"] == {
        "action": "poser_les_questions_du_service", "detail": "poser les questions du service : longueur, etages",
        "inscrite_le": _a(4), "a_faire_avant": _a(30)}
    derniere = _suivis()[-1]
    assert derniere["lead_id"] == lead["lead"]["lead_id"] and derniere["statut"] == "ouverte"
    assert derniere["questions"] == {"statut": "a_poser", "repondues": [], "restantes": ["longueur", "etages"]}


def test_la_conversation_se_ferme_quand_il_ne_reste_rien_a_demander(declarer_qualification):
    declarer_qualification()
    _sms("Mes gouttières fuient à Laval.", "SM-1", 0)
    apres_une = _sms("Environ 40 pieds.", "SM-2", 2)
    assert apres_une["prochaine_action"]["detail"] == "poser les questions du service : etages"
    fini = _sms("Deux étages.", "SM-3", 4)
    assert fini["prochaine_action"] is None
    derniere = _suivis()[-1]
    assert derniere["statut"] == "close" and derniere["motif_fermeture"] == "rien_a_demander"
    assert derniere["prochaine_action"] is None


def test_sans_question_declaree_un_lead_complet_ferme_la_conversation_sans_rien_inventer():
    reponse = _sms("Mes gouttières fuient à Laval.", "SM-1", 0)
    assert reponse["prochaine_action"] is None
    (ligne,) = _suivis()
    assert ligne["statut"] == "close" and ligne["questions"]["statut"] == "non_configurees"


def test_un_client_retire_n_a_aucun_message_propose_mais_une_personne_decide(declarer_qualification):
    declarer_qualification()
    _sms("STOP", "SM-STOP", 0)
    reponse = _sms("Gouttières à Laval.", "SM-2", 5)
    assert reponse["prochaine_action"]["action"] == "decision_humaine_apres_retrait"
    assert reponse["prochaine_action"]["detail"].startswith("le client s'est retiré des messages")
    assert reponse["prochaine_action"]["a_faire_avant"] == _a(35)
    assert reponse["brouillon_reponse"] is None and reponse["sans_brouillon"] == "retrait_consentement"


def test_stop_ferme_la_conversation_ouverte_au_registre():
    _sms("Mes gouttières fuient.", "SM-1", 0)
    assert _suivis()[-1]["statut"] == "ouverte"
    _sms("STOP", "SM-STOP", 3)
    fermeture = _suivis()[-1]
    assert fermeture["statut"] == "close" and fermeture["motif_fermeture"] == "retrait_consentement"
    assert fermeture["ouverte_le"] == _a(0) and fermeture["prochaine_action"] is None
    assert fermeture["signal_id"] == "sms:SM-STOP"


def test_stop_comme_premier_message_n_ecrit_pas_de_suivi():
    _sms("STOP", "SM-STOP", 0)
    assert _suivis() == []


def test_un_message_rejoue_n_ajoute_aucune_ligne_de_suivi():
    _sms("Mes gouttières fuient.", "SM-1", 0)
    taille = _obtenir_registre().taille()
    rejoue = _sms("Mes gouttières fuient.", "SM-1", 0)
    assert rejoue["doublon"] is True and len(_suivis()) == 1 and _obtenir_registre().taille() == taille


def test_sans_fenetre_declaree_aucune_conversation_n_est_suivie():
    fichier = taxonomie.fichier_profil()
    fichier.write_text(fichier.read_text(encoding="utf-8").replace("fenetre_conversation_minutes: 30\n", ""),
                       encoding="utf-8")
    reponse = _sms("Mes gouttières fuient.", "SM-1", 0)
    assert "prochaine_action" not in reponse and "score" not in reponse and _suivis() == []


def test_la_ligne_de_suivi_ne_garde_aucun_texte_du_client_et_la_chaine_reste_valide(declarer_qualification):
    declarer_qualification()
    _sms("Mes gouttières fuient, mon mot de passe est hunter2.", "SM-1", 0)
    _sms("À Laval.", "SM-2", 3)
    for ligne in _suivis():
        texte = json.dumps(ligne, ensure_ascii=False)
        assert "hunter2" not in texte and "fuient" not in texte and "Laval" not in texte.replace('"ville": "Laval"', "")
        assert NUMERO not in texte, "ni le numéro, ni le texte : la ligne dit l'état, pas le contenu"
    assert _obtenir_registre().valider_chaine() == (True, None)


# -- Le module pur -----------------------------------------------------------------------------------------


def test_la_prochaine_action_est_un_choix_ferme_decide_par_regles():
    date, fin = "2031-01-15T09:00:00-05:00", "2031-01-15T09:30:00-05:00"
    assert suivi.prochaine_action(["ville"], [], False, date, fin)["action"] == "demander_precisions"
    assert suivi.prochaine_action([], ["longueur"], False, date, fin)["action"] == "poser_les_questions_du_service"
    assert suivi.prochaine_action(["ville"], ["longueur"], False, date, fin)["action"] == "demander_precisions", (
        "d'abord le lead, ensuite les questions")
    assert suivi.prochaine_action([], [], False, date, fin) is None
    humaine = suivi.prochaine_action(["ville"], [], True, date, fin)
    assert humaine["action"] == "decision_humaine_apres_retrait" and humaine["a_faire_avant"] == fin
    assert suivi.prochaine_action([], [], True, date, fin) is None, "rien à décider quand rien ne reste"


# -- Le digest M1.11 relit les conversations ouvertes ------------------------------------------------------------------


def _digest(jour: str) -> str:
    return produire_digest(jour)


def _ligne_du_digest(texte: str, debut: str) -> int:
    (ligne,) = [ligne for ligne in texte.splitlines() if ligne.startswith(debut)]
    return int(ligne.rsplit(":", 1)[1])


def test_le_digest_compte_les_conversations_sans_suivi_a_l_echeance_de_leur_fenetre(declarer_qualification):
    declarer_qualification()
    _sms("Mes gouttières fuient.", "A-1", 0, expediteur="+15145550101")  # ville manquante : ouverte
    _sms("Mes gouttières fuient à Laval.", "B-1", 1, expediteur="+15145550102")  # lead, questions restantes : ouverte
    _sms("Mes gouttières font 40 pieds, bungalow, à Laval.", "C-1", 2, expediteur="+15145550103")  # tout dit : fermée
    texte = _digest("2031-01-15")
    assert _ligne_du_digest(texte, "- conversations ouvertes à suivre") == 2
    assert _ligne_du_digest(texte, "- conversations sans suivi à l'échéance de leur fenêtre") == 2
    assert garde_fou.verifier_sortie(texte)["code"] == "OK"

    # B répond à ses questions : sa conversation se ferme et ne compte plus.
    _sms("Environ 40 pieds, un bungalow.", "B-2", 5, expediteur="+15145550102")
    texte = _digest("2031-01-15")
    assert _ligne_du_digest(texte, "- conversations ouvertes à suivre") == 1
    assert _ligne_du_digest(texte, "- conversations sans suivi à l'échéance de leur fenêtre") == 1


def test_une_conversation_n_est_sans_suivi_que_le_jour_de_son_echeance():
    _sms("Mes gouttières fuient.", "A-1", 14 * 60 + 50)  # 23 h 50 : la fenêtre se termine le lendemain, à 0 h 20
    veille, lendemain = _digest("2031-01-15"), _digest("2031-01-16")
    assert _ligne_du_digest(veille, "- conversations ouvertes à suivre") == 1
    assert _ligne_du_digest(veille, "- conversations sans suivi à l'échéance de leur fenêtre") == 0
    assert _ligne_du_digest(lendemain, "- conversations ouvertes à suivre") == 0
    assert _ligne_du_digest(lendemain, "- conversations sans suivi à l'échéance de leur fenêtre") == 1
    surlendemain = _digest("2031-01-17")
    assert _ligne_du_digest(surlendemain, "- conversations ouvertes à suivre") == 0
    assert _ligne_du_digest(surlendemain, "- conversations sans suivi à l'échéance de leur fenêtre") == 0


def test_un_stop_retire_la_conversation_du_digest():
    _sms("Mes gouttières fuient.", "A-1", 0)
    _sms("STOP", "A-STOP", 2)
    texte = _digest("2031-01-15")
    assert _ligne_du_digest(texte, "- conversations ouvertes à suivre") == 0
    assert _ligne_du_digest(texte, "- conversations sans suivi à l'échéance de leur fenêtre") == 0


def test_les_lignes_de_suivi_ne_sont_pas_des_entrees_non_classees_et_le_digest_sans_suivi_ne_change_pas():
    entrees = [{"type_entree": "signal", "canal": "texte", "horodatage": "2031-01-15T09:00:00-05:00"}]
    sans = digest.produire_digest(entrees, "2031-01-15")
    assert "conversations" not in sans and sans.endswith("- entrées non classées : 0")
    avec = digest.produire_digest(
        [*entrees, {"type_entree": "suivi_conversation", "canal": "texte", "conversation_id": "c", "statut": "close",
                    "ouverte_le": "2031-01-15T09:00:00-05:00", "horodatage": "2031-01-15T09:00:00-05:00"}],
        "2031-01-15")
    assert avec.endswith("- entrées non classées : 0"), "une ligne de suivi n'est jamais « non classée »"
    assert avec.replace("- conversations ouvertes à suivre : 0\n- conversations sans suivi à l'échéance de leur "
                        "fenêtre : 0\n", "") == sans


def test_le_digest_de_suivi_est_deterministe_et_ne_lit_aucune_horloge():
    _sms("Mes gouttières fuient.", "A-1", 0)
    assert _digest("2031-01-15") == _digest("2031-01-15")
    assert "datetime.now" not in inspect.getsource(digest)
