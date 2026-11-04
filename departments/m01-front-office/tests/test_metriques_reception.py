"""M1-H : les métriques de réception, calculées sur le registre anti-perte, sans valeur inventée.

Délai jusqu'à la première prise en charge humaine, appels manqués rappelés, leads par service/ville : comptes exacts.
Hors zone et photos : NON_EVALUÉS, jamais zéro. Une période sans source n'est pas une période à zéro.
"""

from __future__ import annotations

from m1_front_office import metriques_reception as mr

DEBUT = "2031-01-15T09:00:00-05:00"
T = "2031-01-15T10:00:00-05:00"
DATE_REF = "2031-01-20"
JOURS = 6
PERIODE = {"debut": "2031-01-15", "fin": "2031-01-20"}


def _signal(jour=15, conversation="sms-a"):
    return {"type_entree": "signal", "canal": "sms", "conversation_id": conversation,
            "signal_id": f"{conversation}:{jour}", "horodatage": f"2031-01-{jour:02d}T08:00:00-05:00"}


def _lead(jour=15, service="gouttieres", ville="Laval", lead_id="l1"):
    return {"type_entree": "lead_emis", "canal": "sms", "conversation_id": "sms-a", "signal_id": "sms:a",
            "horodatage": f"2031-01-{jour:02d}T08:05:00-05:00",
            "lead": {"lead_id": lead_id, "service": service, "ville": ville}}


def _transfert(tid, jour=15, ouvert="09:00", type_transfert="plainte"):
    return {"type_entree": "transfert", "evenement": "ouvert", "transfert_id": tid,
            "type_transfert": type_transfert, "niveau": "N4", "categories": ["insatisfaction"],
            "canal": "sms", "conversation_id": "sms-a", "signal_id": "sms:a", "signaux": ["sms:a"],
            "horodatage": f"2031-01-{jour:02d}T{ouvert}:00-05:00"}


def _humain(tid, evenement, jour=15, heure="09:10", **plus):
    return {"type_entree": "transfert", "evenement": evenement, "transfert_id": tid,
            "horodatage": f"2031-01-{jour:02d}T{heure}:00-05:00", **plus}


def _appel(jour=16, tid=None, appel_id="A1"):
    reponse = {"tache_rappel": {"transfert_id": tid}} if tid else {}
    return {"type_entree": "appel_importe", "statut": "manque", "appel_id": appel_id,
            "horodatage": f"2031-01-{jour:02d}T08:00:00-05:00", "reponse": reponse}


def test_un_scenario_complet_donne_des_comptes_exacts_et_deux_metriques_non_evaluees():
    lignes = [
        _signal(15), _signal(16), _signal(17),
        _lead(15, "gouttieres", "Laval", "l1"),
        _lead(16, "revetement", "Laval", "l2"),
        _lead(17, "gouttieres", "Quebec", "l3"),
        _transfert("tr-1", 15), _humain("tr-1", "clos", 15, "09:10"),
        _transfert("tr-2", 16), _humain("tr-2", "prise_en_charge", 16, "09:20"),
        _transfert("tr-3", 17),
        _humain("tr-2", "tentative_sans_contact", 16, "09:30"),
        _appel(16, "tr-2", "A1"), _appel(17, "tr-3", "A2"), _appel(18, None, "A3"),
    ]
    c = mr.constater(lignes, date_reference=DATE_REF, jours=JOURS)
    assert c["date_reference"] == DATE_REF and c["jours"] == JOURS and c["periode"] == PERIODE
    assert c["delai_premiere_prise_en_charge_s"] == {
        "statut": "CALCULEE", "motif": None, "median_s": 900, "max_s": 1200, "echantillon": 2, "en_attente": 1,
    }
    assert c["appels_manques_rappeles_pct"] == {
        "statut": "CALCULEE", "motif": None, "valeur": "33.33", "numerateur": 1, "denominateur": 3,
    }
    assert c["leads_par_service"] == {
        "statut": "CALCULEE", "motif": None, "comptes": {"gouttieres": 2, "revetement": 1}, "total": 3,
    }
    assert c["leads_par_ville"] == {
        "statut": "CALCULEE", "motif": None, "comptes": {"Laval": 2, "Quebec": 1}, "total": 3,
    }
    assert c["hors_zone"] == {"statut": "NON_EVALUEE", "motif": "HORS_ZONE_NON_TRACE", "valeur": None}
    assert c["photos_recues_pct"] == {
        "statut": "NON_EVALUEE", "motif": "PHOTOS_NON_TRACEES", "valeur": None, "numerateur": None,
        "denominateur": None,
    }
    assert len(c["empreinte_contenu"]) == 64


def test_une_periode_sans_source_n_est_jamais_un_zero():
    c = mr.constater([], date_reference=DATE_REF, jours=JOURS)
    assert c["delai_premiere_prise_en_charge_s"]["statut"] == "NON_EVALUEE"
    assert c["delai_premiere_prise_en_charge_s"]["motif"] == "AUCUN_TRANSFERT"
    assert c["delai_premiere_prise_en_charge_s"]["median_s"] is None
    assert c["appels_manques_rappeles_pct"]["statut"] == "NON_EVALUEE"
    assert c["appels_manques_rappeles_pct"]["valeur"] is None
    assert c["leads_par_service"]["statut"] == "NON_EVALUEE"
    assert c["leads_par_service"]["comptes"] is None
    assert c["leads_par_ville"]["statut"] == "NON_EVALUEE"


def test_des_signaux_sans_lead_donnent_un_vrai_zero_pas_une_absence():
    c = mr.constater([_signal(15)], date_reference=DATE_REF, jours=JOURS)
    assert c["leads_par_service"] == {"statut": "CALCULEE", "motif": None, "comptes": {}, "total": 0}
    assert c["leads_par_ville"] == {"statut": "CALCULEE", "motif": None, "comptes": {}, "total": 0}


def test_aucun_appel_manque_est_non_evalue_pas_zero_pour_cent():
    c = mr.constater([_signal(15)], date_reference=DATE_REF, jours=JOURS)
    assert c["appels_manques_rappeles_pct"]["statut"] == "NON_EVALUEE"
    assert c["appels_manques_rappeles_pct"]["motif"] == "AUCUN_APPEL_MANQUE"


def test_des_transferts_sans_ligne_humaine_disent_aucune_prise_en_charge():
    c = mr.constater([_transfert("tr-1", 15), _transfert("tr-2", 16)], date_reference=DATE_REF, jours=JOURS)
    assert c["delai_premiere_prise_en_charge_s"] == {
        "statut": "NON_EVALUEE", "motif": "AUCUNE_PRISE_EN_CHARGE", "median_s": None, "max_s": None,
        "echantillon": 0, "en_attente": 2,
    }


def test_un_ratio_est_arrondi_au_centieme_avec_half_up():
    lignes = [_appel(16, "tr-1", "A1"), _appel(17, "tr-2", "A2"), _appel(18, "tr-3", "A3"),
              _transfert("tr-1", 16), _humain("tr-1", "tentative_sans_contact", 16, "09:10"),
              _transfert("tr-2", 17), _humain("tr-2", "tentative_sans_contact", 17, "09:10"),
              _transfert("tr-3", 18)]
    c = mr.constater(lignes, date_reference=DATE_REF, jours=JOURS)
    assert c["appels_manques_rappeles_pct"]["valeur"] == "66.67"


def test_les_lignes_hors_periode_sont_ignorees():
    lignes = [_signal(10), _lead(10), _transfert("tr-1", 10), _humain("tr-1", "clos", 10, "09:10"),
              _appel(10, "tr-1", "A1")]
    c = mr.constater(lignes, date_reference=DATE_REF, jours=JOURS)
    assert c["delai_premiere_prise_en_charge_s"]["statut"] == "NON_EVALUEE"
    assert c["leads_par_service"]["statut"] == "NON_EVALUEE"
    assert c["appels_manques_rappeles_pct"]["statut"] == "NON_EVALUEE"


def test_le_meme_registre_donne_la_meme_empreinte():
    lignes = [_signal(15), _lead(15)]
    assert mr.constater(lignes, date_reference=DATE_REF)["empreinte_contenu"] == (
        mr.constater(lignes, date_reference=DATE_REF)["empreinte_contenu"]
    )



def test_les_bornes_de_periode_et_la_valeur_par_defaut():
    for jours in (1, 92):
        assert mr.constater([], date_reference=DATE_REF, jours=jours)["jours"] == jours
    assert mr.constater([], date_reference=DATE_REF)["jours"] == mr.JOURS_DEFAUT == 7


def test_un_horodatage_non_texte_est_ignore_et_non_une_panne():
    lignes = [{"type_entree": "signal", "horodatage": 123, "conversation_id": "sms-a", "signal_id": "x"}]
    c = mr.constater(lignes, date_reference=DATE_REF, jours=JOURS)
    assert c["leads_par_service"]["statut"] == "NON_EVALUEE"


def test_la_borne_de_fin_de_periode_est_incluse():
    lignes = [_signal(20), _lead(20), _transfert("tr-fin", 20), _humain("tr-fin", "clos", 20, "09:10")]
    c = mr.constater(lignes, date_reference=DATE_REF, jours=JOURS)
    assert c["leads_par_service"]["total"] == 1
    assert c["delai_premiere_prise_en_charge_s"]["echantillon"] == 1


def test_un_humain_avant_l_ouverture_ne_cree_pas_un_delai_negatif():
    lignes = [_transfert("tr-1", 15), _humain("tr-1", "clos", 15, "08:00")]
    c = mr.constater(lignes, date_reference=DATE_REF, jours=JOURS)
    assert c["delai_premiere_prise_en_charge_s"]["statut"] == "NON_EVALUEE"
    assert c["delai_premiere_prise_en_charge_s"]["en_attente"] == 1


def test_la_mediane_d_un_echantillon_impair_est_la_valeur_du_milieu():
    lignes = [
        _transfert("tr-1", 15), _humain("tr-1", "clos", 15, "09:10"),
        _transfert("tr-2", 16), _humain("tr-2", "clos", 16, "09:20"),
        _transfert("tr-3", 17), _humain("tr-3", "clos", 17, "09:30"),
    ]
    c = mr.constater(lignes, date_reference=DATE_REF, jours=JOURS)
    assert c["delai_premiere_prise_en_charge_s"]["median_s"] == 1200


def test_une_cloture_contact_reussi_compte_comme_un_rappel():
    lignes = [
        _appel(16, "tr-1", "A1"), _transfert("tr-1", 16),
        _humain("tr-1", "clos", 16, "09:20", issue="contact_reussi"),
    ]
    c = mr.constater(lignes, date_reference=DATE_REF, jours=JOURS)
    assert c["appels_manques_rappeles_pct"]["numerateur"] == 1


def test_un_evenement_de_rappel_sans_ouverture_canonique_ne_compte_pas():
    lignes = [
        _appel(16, "transfert-orphelin", "A1"),
        _humain("transfert-orphelin", "tentative_sans_contact", 16, "09:10"),
    ]
    c = mr.constater(lignes, date_reference=DATE_REF, jours=JOURS)
    assert c["appels_manques_rappeles_pct"]["numerateur"] == 0
    assert c["appels_manques_rappeles_pct"]["valeur"] == "0.00"


def test_une_cloture_non_reussie_canonique_n_est_pas_remplacee_par_une_seconde():
    lignes = [
        _appel(16, "tr-1", "A1"),
        _transfert("tr-1", 16),
        _humain("tr-1", "clos", 16, "09:10", issue="autre"),
        _humain("tr-1", "clos", 16, "09:20", issue="contact_reussi"),
    ]
    c = mr.constater(lignes, date_reference=DATE_REF, jours=JOURS)
    assert c["appels_manques_rappeles_pct"]["numerateur"] == 0


def test_une_tentative_avant_ouverture_canonique_ne_compte_pas():
    lignes = [
        _appel(16, "tr-1", "A1"),
        _humain("tr-1", "tentative_sans_contact", 16, "09:05"),
        _transfert("tr-1", 16, "09:10"),
    ]
    c = mr.constater(lignes, date_reference=DATE_REF, jours=JOURS)
    assert c["appels_manques_rappeles_pct"]["numerateur"] == 0


def test_une_tentative_apres_premiere_cloture_canonique_ne_compte_pas():
    lignes = [
        _appel(16, "tr-1", "A1"),
        _transfert("tr-1", 16),
        _humain("tr-1", "clos", 16, "09:10", issue="autre"),
        _humain("tr-1", "tentative_sans_contact", 16, "09:20"),
    ]
    c = mr.constater(lignes, date_reference=DATE_REF, jours=JOURS)
    assert c["appels_manques_rappeles_pct"]["numerateur"] == 0


def test_un_service_non_texte_est_range_dans_non_renseigne():
    lignes = [_signal(15), _lead(15, service=123)]
    c = mr.constater(lignes, date_reference=DATE_REF, jours=JOURS)
    assert c["leads_par_service"]["comptes"] == {"non_renseigne": 1}


def test_l_empreinte_couvre_l_ordre_des_cles_et_l_unicode():
    import hashlib
    import json

    lignes = [_signal(15), _lead(15, service="réparation", ville="Québec")]
    c = mr.constater(lignes, date_reference=DATE_REF, jours=JOURS)
    contenu = {k: v for k, v in c.items() if k != "empreinte_contenu"}
    attendu = hashlib.sha256(json.dumps(
        contenu, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
    assert c["empreinte_contenu"] == attendu



def test_un_horodatage_de_dix_caracteres_est_accepte():
    lignes = [
        {"type_entree": "signal", "horodatage": "2031-01-15", "conversation_id": "sms-a", "signal_id": "s"},
        {"type_entree": "lead_emis", "horodatage": "2031-01-15", "conversation_id": "sms-a", "signal_id": "s",
         "lead": {"lead_id": "l1", "service": "gouttieres", "ville": "Laval"}},
    ]
    c = mr.constater(lignes, date_reference=DATE_REF, jours=JOURS)
    assert c["leads_par_service"]["total"] == 1


def test_une_prise_en_charge_a_l_instant_de_l_ouverture_donne_un_delai_zero():
    lignes = [_transfert("tr-1", 15), _humain("tr-1", "clos", 15, "09:00")]
    c = mr.constater(lignes, date_reference=DATE_REF, jours=JOURS)
    assert c["delai_premiere_prise_en_charge_s"]["median_s"] == 0
    assert c["delai_premiere_prise_en_charge_s"]["en_attente"] == 0


def test_la_mediane_d_un_echantillon_pair_de_quatre_valeurs():
    lignes = [
        _transfert("tr-1", 15), _humain("tr-1", "clos", 15, "09:10"),
        _transfert("tr-2", 15), _humain("tr-2", "clos", 15, "09:20"),
        _transfert("tr-3", 15), _humain("tr-3", "clos", 15, "09:30"),
        _transfert("tr-4", 15), _humain("tr-4", "clos", 15, "09:40"),
    ]
    c = mr.constater(lignes, date_reference=DATE_REF, jours=JOURS)
    assert c["delai_premiere_prise_en_charge_s"]["median_s"] == 1500


def test_une_cloture_sans_contact_reussi_ne_compte_pas_comme_un_rappel():
    lignes = [
        _appel(16, "tr-1", "A1"), _transfert("tr-1", 16),
        _humain("tr-1", "clos", 16, "09:20", issue="autre"),
    ]
    c = mr.constater(lignes, date_reference=DATE_REF, jours=JOURS)
    assert c["appels_manques_rappeles_pct"]["valeur"] == "0.00"


def test_une_date_ou_une_periode_invalide_est_refusee():
    import pytest

    for jours in (0, 93, True, 1.5):
        with pytest.raises(ValueError, match="REJ-M1-RECEPTION-PERIODE"):
            mr.constater([], date_reference=DATE_REF, jours=jours)
    with pytest.raises(ValueError, match="REJ-M1-RECEPTION-DATE"):
        mr.constater([], date_reference="20-01-2031")
