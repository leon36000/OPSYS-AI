"""M1-C : appel manqué complet (M1.4), sur le vrai socle (SQLite, registre, sas N4), données fictives.

Ce que ces tests prouvent : le gabarit « Nous avons manqué votre appel » est une divulgation, un brouillon est préparé
à l'import (aucun envoi), la demande d'envoi passe par le sas N4 existant, STOP annule, un numéro déjà retiré ne
reçoit rien, le rejeu est idempotent et la clôture humaine « contact réussi » mesure le délai de rappel.
Limites : aucun transport SMS/téléphone réel ; le brouillon n'est pas une preuve de livraison.
"""

from __future__ import annotations

import datetime as dt

import pytest
from m1_front_office import assistant_sms, reception
from m1_front_office import gabarits as gb
from m1_front_office import outils as outils_m1

from opsys import approbations, identite, stockage, taxonomie
from opsys.capacites import Capacites, outils_executables
from opsys.departements import charger_departements

HEURE = "2026-09-29T09:15:00-04:00"
ENTREPRISE = "Atelier Fictif"
NUMERO = "+15145550142"
CONV = reception.identifiant_de_conversation("sms", NUMERO)
BASE = {
    "source": "export manuel PBX du 29 septembre",
    "evenement_id": "evt-appel-manque-001",
    "appel_id": "call-appel-manque-001",
    "recu_le": HEURE,
    "telephone": NUMERO,
    "statut": "manque",
    "nom_entreprise": ENTREPRISE,
}


@pytest.fixture
def capacites_m1(tmp_path, monkeypatch, declarer_services):
    url = f"sqlite:///{tmp_path / 'm1-appel-manque.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    declarer_services()
    taxonomie.enregistrer_zone_desservie(["Laval", "Québec"])
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "nathan", "Nathan Fictif", "mot-de-passe-nathan-12345", ["nathan_owner"])
    outils_m1.utiliser_stockage_durable()
    deps = charger_departements()
    capacites = Capacites({"m01-front-office": deps["m01-front-office"]}, stockage.transaction, memoire=False)
    try:
        yield capacites
    finally:
        outils_m1.reinitialiser_registre()
        stockage.liberer()


def _importer(capacites, args=None):
    reponse = capacites.appeler("m1_importer_appel_manuellement", {**BASE, **(args or {})})
    assert reponse.get("ok") is True, reponse
    return reponse["resultat"]


def _sms_lignes():
    with stockage.transaction():
        return list(stockage.maillons("m01-front-office", "sms_assistant"))


def _sms(capacites, texte, message_id="SM-1", recu=HEURE):
    reponse = capacites.appeler(
        "m1_recevoir_message_canal",
        {"canal": "sms", "expediteur": NUMERO, "message_id": message_id, "recu_le": recu, "texte": texte},
    )
    assert reponse.get("ok") is True, reponse
    return reponse["resultat"]


def _decider(capacites, demande_id, par="nathan"):
    with stockage.transaction() as cnx:
        return approbations.decider(
            cnx, demande_id, True, par,
            outils_executables(capacites.departements, stockage.transaction), capacites.departements,
        )


def test_gabarit_appel_manque_dit_le_motif_et_la_divulgation():
    g = gb.GABARITS["sms_appel_manque"]
    assert g.version == 1
    assert g.divulgation is True and g.proactif is False and g.canal == "sms"
    _, texte = gb.rendre("sms_appel_manque", {"entreprise": ENTREPRISE})
    assert "manqué votre appel" in texte
    assert "assistant virtuel" in texte and "intelligence artificielle" in texte and "STOP" in texte


def test_import_appel_manque_prepare_un_brouillon_sans_rien_envoyer(capacites_m1):
    resultat = _importer(capacites_m1)
    brouillon = resultat["brouillon_sms"]
    assert brouillon["prepare"] is True and brouillon["deja_prepare"] is False
    assert brouillon["statut"] == "BROUILLON"
    assert "manqué votre appel" in brouillon["texte"]
    assert resultat["envoi_automatique"] is False
    with stockage.transaction() as cnx:
        assert approbations.lister(cnx, "en_attente") == []
    (ligne,) = [x for x in _sms_lignes() if x["type_entree"] == assistant_sms.TYPE_BROUILLON]
    assert ligne["conversation_id"] == CONV and ligne["gabarit_id"] == "sms_appel_manque"


def test_demande_n4_porte_le_texte_exact_du_brouillon(capacites_m1):
    resultat = _importer(capacites_m1)
    b = resultat["brouillon_sms"]
    demande = capacites_m1.appeler(
        "m1_sms_demander_envoi",
        {"brouillon_id": b["brouillon_id"], "conversation_id": CONV, "horodatage": "2026-09-29T09:20:00-04:00"},
    )
    assert demande.get("ok") is True, demande
    demande_id = demande["resultat"]["resultat"]["demande_id"]
    with stockage.transaction() as cnx:
        d = approbations.lire(cnx, demande_id)
    assert (d["outil"], d["niveau"]) == ("m1_emettre_notification", "N4")
    assert d["arguments"] == {"canal": f"sms:{CONV}", "message": b["texte"]}
    assert _decider(capacites_m1, demande_id)["statut"] == "executee"


def test_stop_entre_la_demande_et_l_approbation_annule_l_envoi(capacites_m1):
    resultat = _importer(capacites_m1)
    b = resultat["brouillon_sms"]
    demande = capacites_m1.appeler(
        "m1_sms_demander_envoi",
        {"brouillon_id": b["brouillon_id"], "conversation_id": CONV, "horodatage": "2026-09-29T09:20:00-04:00"},
    )["resultat"]["resultat"]
    _sms(capacites_m1, "STOP", message_id="SM-stop-1", recu="2026-09-29T09:25:00-04:00")
    sortie = _decider(capacites_m1, demande["demande_id"])
    assert sortie["statut"] == "echec"
    assert "REJ-SMS-RETRAIT" in sortie["reponse"]["details"]
    etat = capacites_m1.appeler(
        "m1_lire_session_sms", {"conversation_id": CONV, "horodatage": "2026-09-29T09:30:00-04:00"}
    )["resultat"]["resultat"]
    assert etat["etat"] == "retire" and etat["gabarits_permis"] == []


def test_numero_deja_retire_ne_prepare_aucun_brouillon(capacites_m1):
    _sms(capacites_m1, "STOP", message_id="SM-stop-2")
    resultat = _importer(capacites_m1)
    assert resultat["brouillon_sms"] == {
        "prepare": False,
        "raison": "REJ-SMS-RETRAIT: le correspondant s'est retiré (STOP) : aucun message n'est préparé",
    }
    assert not [x for x in _sms_lignes() if x["type_entree"] == assistant_sms.TYPE_BROUILLON]


def test_rejeu_du_meme_appel_ne_cree_pas_un_second_brouillon(capacites_m1):
    premier = _importer(capacites_m1)
    avant = _sms_lignes()
    second = _importer(capacites_m1, {"evenement_id": "evt-appel-manque-relivre"})
    assert second == premier
    assert _sms_lignes() == avant
    assert second["brouillon_sms"]["brouillon_id"] == premier["brouillon_sms"]["brouillon_id"]


def test_import_sans_nom_d_entreprise_ne_devine_pas_le_brouillon(capacites_m1):
    resultat = _importer(capacites_m1, {"nom_entreprise": None})
    assert resultat["brouillon_sms"]["prepare"] is False
    assert "REJ-M1-APPEL-ENTREPRISE" in resultat["brouillon_sms"]["raison"]
    assert not [x for x in _sms_lignes() if x["type_entree"] == assistant_sms.TYPE_BROUILLON]


def test_contact_reussi_mesure_le_delai_et_vide_la_file(capacites_m1):
    resultat = _importer(capacites_m1)
    transfert_id = resultat["tache_rappel"]["transfert_id"]
    demande = capacites_m1.appeler(
        "m1_consigner_contact_reussi",
        {"transfert_id": transfert_id, "horodatage": "2026-09-29T10:15:00-04:00"},
    )
    assert demande.get("ok") is True and demande["statut"] == "en_attente_approbation", demande
    assert outils_m1.attentes()[0]["id"] == transfert_id, "rien n'est clos avant la décision humaine"

    assert _decider(capacites_m1, demande["demande_id"])["statut"] == "executee"
    assert outils_m1.attentes() == []
    with stockage.transaction():
        lignes = outils_m1._obtenir_registre().lire()
    (cloture,) = [x for x in lignes if x.get("evenement") == "clos" and x["transfert_id"] == transfert_id]
    assert cloture["issue"] == "contact_reussi"
    assert cloture["delai_rappel_s"] == 3600
    assert cloture["appel_recu_le"] == HEURE
    assert cloture["clos_par"] == "nathan"

    rejoue = capacites_m1.appeler(
        "m1_consigner_contact_reussi",
        {"transfert_id": transfert_id, "horodatage": "2026-09-29T10:30:00-04:00"},
    )
    assert rejoue.get("statut") == "en_attente_approbation", rejoue
    sortie_rejeu = _decider(capacites_m1, rejoue["demande_id"])
    assert sortie_rejeu["statut"] == "echec"
    assert "REJ-TRANSFERT-DEJA-CLOS" in str(sortie_rejeu)


def test_contact_reussi_refuse_un_transfert_sans_appel(capacites_m1):
    _sms(capacites_m1, "Bonjour, pouvez-vous me rappeler au sujet de ma demande?")
    transfert = capacites_m1.appeler(
        "m1_transferer", {"type_transfert": "ventes", "canal": "sms", "expediteur": NUMERO}
    )
    assert transfert.get("ok") is True, transfert
    transfert_id = transfert["resultat"]["resultat"]["transfert"]["transfert_id"]
    refus = capacites_m1.appeler(
        "m1_consigner_contact_reussi",
        {"transfert_id": transfert_id, "horodatage": "2026-09-29T10:15:00-04:00"},
    )
    assert refus.get("statut") == "en_attente_approbation", refus
    sortie = _decider(capacites_m1, refus["demande_id"])
    assert sortie["statut"] == "echec"
    assert "REJ-RAPPEL-SANS-APPEL" in str(sortie)


def test_contact_reussi_refuse_un_horodatage_anterieur_a_l_appel(capacites_m1):
    resultat = _importer(capacites_m1)
    transfert_id = resultat["tache_rappel"]["transfert_id"]
    demande = capacites_m1.appeler(
        "m1_consigner_contact_reussi",
        {"transfert_id": transfert_id, "horodatage": "2026-09-29T08:00:00-04:00"},
    )
    assert demande.get("ok") is True and demande["statut"] == "en_attente_approbation"
    sortie = _decider(capacites_m1, demande["demande_id"])
    assert sortie["statut"] == "echec"
    assert "REJ-RAPPEL-HORODATAGE-ANTERIEUR" in sortie["reponse"]["details"]
    assert outils_m1.attentes()[0]["id"] == transfert_id


def test_gabarit_appel_manque_refuse_sur_une_conversation_sans_appel(capacites_m1):
    _sms(capacites_m1, "Bonjour")
    reponse = capacites_m1.appeler(
        "m1_sms_preparer_message",
        {
            "conversation_id": CONV, "gabarit_id": "sms_appel_manque",
            "variables": {"entreprise": ENTREPRISE}, "horodatage": "2026-09-29T09:20:00-04:00",
        },
    )
    assert reponse.get("ok") is False and "REJ-SMS-AUCUN-APPEL" in reponse["details"]


def test_delai_exact_a_la_seconde_pres_et_deux_appels_distincts(capacites_m1):
    resultat = _importer(capacites_m1)
    transfert_id = resultat["tache_rappel"]["transfert_id"]
    ferme = "2026-09-29T09:15:45-04:00"
    demande = capacites_m1.appeler(
        "m1_consigner_contact_reussi", {"transfert_id": transfert_id, "horodatage": ferme}
    )
    assert demande["statut"] == "en_attente_approbation"
    _decider(capacites_m1, demande["demande_id"])
    with stockage.transaction():
        lignes = outils_m1._obtenir_registre().lire()
    (cloture,) = [x for x in lignes if x.get("evenement") == "clos" and x["transfert_id"] == transfert_id]
    assert cloture["delai_rappel_s"] == 45
    assert dt.datetime.fromisoformat(cloture["horodatage"]) == dt.datetime.fromisoformat(ferme)

def test_un_autre_signal_du_correspondant_n_est_pas_la_source_du_rappel(capacites_m1):
    _sms(capacites_m1, "Bonjour, j'ai une question.", message_id="SM-avant-appel", recu="2026-09-29T08:00:00-04:00")
    resultat = _importer(capacites_m1)
    assert resultat["tache_rappel"] is not None
    with stockage.transaction():
        lignes = outils_m1._obtenir_registre().lire()
    (transfert,) = [
        x for x in lignes
        if x.get("type_entree") == "transfert" and x.get("evenement") == "ouvert"
    ]
    assert transfert["signal_id"] == "appel-manuel:export manuel PBX du 29 septembre:evt-appel-manque-001"
    assert transfert["canal"] == "telephone"
    etat = capacites_m1.appeler(
        "m1_lire_session_sms", {"conversation_id": CONV, "horodatage": "2026-09-29T09:30:00-04:00"}
    )["resultat"]["resultat"]
    assert etat["appel_manque_le"] == HEURE


def test_une_fenetre_de_conversation_invalide_refuse_l_import(capacites_m1, monkeypatch):
    monkeypatch.setattr(
        taxonomie, "charger_fenetre_conversation",
        lambda: (None, {"code": "REJ-PROFIL-INVALIDE", "detail": "fenêtre fictive illisible"}),
    )
    reponse = capacites_m1.appeler("m1_importer_appel_manuellement", dict(BASE))
    assert reponse.get("ok") is False and "REJ-PROFIL-INVALIDE" in reponse["details"]

def test_une_ligne_de_transfert_telephone_ne_vaut_pas_un_appel_entrant(capacites_m1):
    _sms(capacites_m1, "Bonjour", message_id="SM-sans-appel")
    with stockage.transaction():
        outils_m1._obtenir_registre().ajouter({
            "type_entree": "transfert", "evenement": "ouvert", "transfert_id": "tr-" + "a" * 20,
            "canal": "telephone", "conversation_id": CONV, "horodatage": "2026-09-29T08:30:00-04:00",
            "signal_id": "sms:SM-sans-appel",
        })
    reponse = capacites_m1.appeler(
        "m1_sms_preparer_message",
        {
            "conversation_id": CONV, "gabarit_id": "sms_appel_manque",
            "variables": {"entreprise": ENTREPRISE}, "horodatage": "2026-09-29T09:00:00-04:00",
        },
    )
    assert reponse.get("ok") is False and "REJ-SMS-AUCUN-APPEL" in reponse["details"]

