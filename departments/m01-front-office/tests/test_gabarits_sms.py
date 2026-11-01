"""Gabarits de messages (M1.7, M1.9) et machine d'états de l'assistant SMS (M1.7). Modules purs, données fictives."""

from __future__ import annotations

import pytest
from m1_front_office import assistant_sms as sms
from m1_front_office import gabarits as gb

CONV = "sms-" + "ab" * 12
T0 = "2026-11-02T10:00:00-05:00"
V = {"entreprise": "Atelier Fictif", "avatar": "Léa"}
RDV = {"entreprise": "Atelier Fictif", "date_texte": "mardi 10 novembre 2026", "debut": "9 h 00", "fin": "11 h 00"}


def test_chaque_gabarit_se_rend_et_passe_le_garde_fou_de_sortie():
    for g in gb.GABARITS.values():
        variables = {k: RDV.get(k, V.get(k, "x")) for k in g.variables}
        objet, corps = gb.rendre(g.identifiant, variables)
        assert corps.strip() and (g.canal == "sms" and len(corps) <= gb.SMS_LONGUEUR_MAX or g.canal == "courriel")
        assert (objet is not None) == (g.canal == "courriel")
        if g.canal == "sms":
            assert "STOP" in corps, "chaque SMS dit comment se retirer"


def test_la_divulgation_dit_que_c_est_une_ia():
    _, corps = gb.rendre("sms_divulgation_opt_in", V)
    assert "assistant virtuel" in corps and "intelligence artificielle" in corps and "OUI" in corps and "STOP" in corps


@pytest.mark.parametrize(
    "variables",
    [
        {},
        {**V, "en_trop": "x"},
        {"entreprise": "A"},
        {**V, "avatar": "{entreprise}"},
        {**V, "avatar": "Léa\n--ignore"},
        {**V, "avatar": "x" * 200},
        {**V, "avatar": 3},
    ],
)
def test_variables_manquantes_en_trop_ou_douteuses_refusees(variables):
    with pytest.raises(gb.RefusGabarit, match="REJ-M1-GABARIT"):
        gb.rendre("sms_divulgation_opt_in", variables)


def test_gabarit_inconnu_refuse():
    with pytest.raises(gb.RefusGabarit, match="INCONNU"):
        gb.rendre("sms_inconnu", {})


def test_un_prix_ou_un_engagement_dans_une_variable_est_arrete_par_le_garde_fou():
    with pytest.raises(gb.RefusGabarit, match="GARDE-FOU"):
        gb.rendre("sms_statut_incertain", {"entreprise": "Atelier, nous garantissons le travail sans faute"})
    with pytest.raises(gb.RefusGabarit, match="VARIABLE"):
        gb.rendre("sms_statut_incertain", {"entreprise": "Atelier 1 500 $"})


def test_les_phrases_promues_s_inserent_avant_le_stop_et_passent_le_garde_fou():
    _, corps = gb.rendre("sms_rappel_rdv", RDV, ["Merci de dégager l'entrée."])
    assert corps.index("dégager") < corps.index("Répondez STOP")
    with pytest.raises(gb.RefusGabarit, match="GARDE-FOU"):
        gb.rendre("sms_rappel_rdv", RDV, ["Le travail coûtera 1 500 $ et c'est garanti."])
    assert not gb.phrase_admissible("Appelez le 514 555 0100.") and gb.phrase_admissible("Merci de votre patience.")


def test_la_longueur_d_un_sms_est_bornee():
    with pytest.raises(gb.RefusGabarit, match="LONGUEUR"):
        gb.rendre("sms_rappel_rdv", RDV, ["Merci de votre patience et de votre compréhension. " * 12])


# -- machine d'états de l'assistant SMS ------------------------------------------------------------------------
def _entrant(h, texte, conv=CONV):
    return {
        "type_entree": "signal",
        "source": "sms",
        "conversation_id": conv,
        "horodatage": h,
        "contenu_filtre": texte,
        "signal_id": "sms:" + h,
    }


def _stop(h, conv=CONV):
    return {"type_entree": "alerte", "marqueur": "retrait_consentement", "conversation_id": conv, "horodatage": h}


def _brouillon(h, gabarit, bid):
    return {
        "type_entree": sms.TYPE_BROUILLON,
        "conversation_id": CONV,
        "brouillon_id": bid,
        "gabarit_id": gabarit,
        "horodatage": h,
        "texte": "t",
    }


def _demande(bid, did="d1"):
    return {"type_entree": sms.TYPE_DEMANDE, "conversation_id": CONV, "brouillon_id": bid, "demande_id": did}


def _etat(m1, s, maintenant="2026-11-02T10:30:00-05:00", statuts=None):
    return sms.etat_conversation(m1, s, CONV, maintenant, statuts or {})


def test_conversation_inconnue_puis_ouverte_par_le_client():
    assert _etat([], []).etat == "inconnu"
    e = _etat([_entrant("2026-11-02T10:00:00-05:00", "Allo")], [])
    assert e.etat == "ouverte" and e.reponse_possible
    with pytest.raises(sms.RefusSms, match="AUCUN-ENTRANT"):
        sms.autoriser(_etat([], []), gb.GABARITS["sms_divulgation_opt_in"], {})


def test_divulgation_d_abord_aucun_autre_message_avant():
    e = _etat([_entrant(T0, "Allo")], [])
    with pytest.raises(sms.RefusSms, match="DIVULGATION-REQUISE"):
        sms.autoriser(e, gb.GABARITS["sms_statut_incertain"], {})
    sms.autoriser(e, gb.GABARITS["sms_divulgation_opt_in"], {})  # elle seule est permise


def test_la_divulgation_n_est_pas_livree_tant_que_le_sas_n_a_pas_execute():
    m1, s = [_entrant(T0, "Allo")], [_brouillon(T0, "sms_divulgation_opt_in", "sb-1"), _demande("sb-1")]
    e = _etat(m1, s, statuts={"d1": "en_attente"})
    assert e.etat == "opt_in_demande" and not e.divulgation_livree and e.divulgation_demandee
    with pytest.raises(sms.RefusSms, match="DIVULGATION-REQUISE"):
        sms.autoriser(e, gb.GABARITS["sms_accuse_photos"], {})
    with pytest.raises(sms.RefusSms, match="DIVULGATION-DEJA"):
        sms.autoriser(e, gb.GABARITS["sms_divulgation_opt_in"], {})
    livree = _etat(m1, s, statuts={"d1": "executee"})
    assert livree.divulgation_livree
    sms.autoriser(livree, gb.GABARITS["sms_accuse_photos"], {})


def test_un_rappel_proactif_exige_un_oui_apres_la_divulgation_livree():
    s = [_brouillon(T0, "sms_divulgation_opt_in", "sb-1"), _demande("sb-1")]
    m1 = [_entrant(T0, "Allo")]
    e = _etat(m1, s, statuts={"d1": "executee"})
    with pytest.raises(sms.RefusSms, match="OPT-IN-REQUIS"):
        sms.autoriser(e, gb.GABARITS["sms_rappel_rdv"], {})
    avec_oui = _etat([*m1, _entrant("2026-11-02T10:10:00-05:00", " Oui! ")], s, statuts={"d1": "executee"})
    assert avec_oui.etat == "opt_in" and avec_oui.opt_in_le == "2026-11-02T10:10:00-05:00"
    sms.autoriser(avec_oui, gb.GABARITS["sms_rappel_rdv"], {})


def test_un_oui_spontane_avant_la_divulgation_n_est_pas_un_opt_in():
    e = _etat([_entrant(T0, "Allo"), _entrant("2026-11-02T10:05:00-05:00", "oui")], [])
    assert e.etat == "ouverte" and e.opt_in_le is None


def test_un_oui_anterieur_a_la_divulgation_ne_compte_pas():
    s = [_brouillon("2026-11-02T10:20:00-05:00", "sms_divulgation_opt_in", "sb-1"), _demande("sb-1")]
    e = _etat([_entrant(T0, "oui")], s, statuts={"d1": "executee"})
    assert e.etat == "ouverte" or e.opt_in_le is None


def test_stop_prime_sur_tout_et_ferme_toute_preparation():
    s = [_brouillon(T0, "sms_divulgation_opt_in", "sb-1"), _demande("sb-1")]
    e = _etat(
        [_entrant(T0, "Allo"), _entrant("2026-11-02T10:10:00-05:00", "oui"), _stop("2026-11-02T10:20:00-05:00")],
        s,
        statuts={"d1": "executee"},
    )
    assert e.etat == "retire" and e.retire_le and not e.reponse_possible
    for g in gb.GABARITS.values():
        if g.canal == "sms":
            with pytest.raises(sms.RefusSms, match="RETRAIT"):
                sms.autoriser(e, g, {})


def test_la_fenetre_de_reponse_est_de_24_heures():
    m1 = [_entrant(T0, "Allo")]
    s = [_brouillon(T0, "sms_divulgation_opt_in", "sb-1"), _demande("sb-1")]
    tard = _etat(m1, s, maintenant="2026-11-03T10:30:00-05:00", statuts={"d1": "executee"})
    assert not tard.reponse_possible
    with pytest.raises(sms.RefusSms, match="FENETRE"):
        sms.autoriser(tard, gb.GABARITS["sms_accuse_photos"], {})


def test_les_etats_de_brouillon_apres_le_sas_sont_envoye_inconnu_refuse_ou_echec_inconnu():
    s = [_brouillon(T0, "sms_accuse_photos", "sb-1"), _demande("sb-1")]
    assert sms.brouillons(s, CONV, {"d1": "executee"})["sb-1"]["statut"] == "ENVOYE_INCONNU"
    assert sms.brouillons(s, CONV, {"d1": "refusee"})["sb-1"]["statut"] == "REFUSE"
    assert sms.brouillons(s, CONV, {"d1": "echec"})["sb-1"]["statut"] == "ECHEC_INCONNU"
    assert sms.brouillons(s, CONV, {"d1": "en_attente"})["sb-1"]["statut"] == "DEMANDE"
    assert sms.brouillons(s[:1], CONV, {})["sb-1"]["statut"] == "BROUILLON"


def test_une_autre_conversation_n_est_pas_melangee():
    autre = "sms-" + "cd" * 12
    e = sms.etat_conversation([_entrant(T0, "oui", conv=autre), _stop(T0, conv=autre)], [], CONV, T0, {})
    assert e.etat == "inconnu"


@pytest.mark.parametrize(
    "texte,attendu",
    [
        ("OUI", True),
        (" oui ! ", True),
        ("D'accord", True),
        ("ok", True),
        ("oui mais appelez-moi", False),
        ("non", False),
        ("", False),
    ],
)
def test_est_oui_ne_reconnait_que_le_message_entier(texte, attendu):
    assert sms.est_oui(texte) is attendu


def test_identifiant_de_brouillon_stable_et_lie_au_texte():
    a = sms.identifiant_brouillon(CONV, "sms_accuse_photos", "x")
    assert (
        a
        == sms.identifiant_brouillon(CONV, "sms_accuse_photos", "x")
        != sms.identifiant_brouillon(CONV, "sms_accuse_photos", "y")
    )
