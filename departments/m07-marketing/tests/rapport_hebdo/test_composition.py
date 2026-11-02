"""Rapport hebdomadaire : sections, jamais un zéro inventé, rien recalculé en finance, déterministe
(M7-RAPPORT-HEBDO)."""

from __future__ import annotations

import copy
import json

import pytest
from m7_marketing.rapport_hebdo import composition, recommandations

FICTIF = True
LUNDI = "2026-10-26"


def composer(entrees, debut=LUNDI):
    return composition.composer(entrees, debut)


def test_le_rapport_complet_a_toutes_ses_sections_sourcees_et_une_empreinte(entrees):
    r = composer(entrees)
    assert r["type"] == "RAPPORT_HEBDOMADAIRE" and r["semaine"] == {"debut": "2026-10-26", "fin": "2026-11-01"}
    assert r["sources"] == {n: "disponible" for n in composition.SOURCES}
    for nom in (
        "leads_par_canal",
        "cout_par_lead",
        "conversion",
        "contenus",
        "calendrier",
        "reputation",
        "croissance_engagement",
        "mesures_m8",
    ):
        assert r[nom]["statut"] == "calcule", nom
    assert r["roi"]["statut"] == "donnees_insuffisantes" and r["roi"]["roi"] is None
    assert len(r["empreinte"]) == 64 and r["empreinte"] == composition.empreinte(r)


def test_leads_par_canal_regroupe_trie_et_dit_la_couverture_partielle(entrees):
    canaux = composer(entrees)["leads_par_canal"]["canaux"]
    assert [(c["canal"], c["leads"]) for c in canaux] == [("facebook", 5), ("google", 3), ("inconnu", 2)]
    fb = canaux[0]
    assert fb["marge_constatee_m5_cad"] == "3100.00" and fb["couverture"] == "partielle" and fb["devis_acceptes"] == 2
    assert canaux[1]["marge_constatee_m5_cad"] is None  # jamais zéro quand M5 n'a rien constaté
    assert composer(entrees)["leads_par_canal"]["total_leads"] == 10


def test_la_marge_est_dite_somme_partielle_quand_m5_ne_connait_pas_tous_les_chantiers(entrees):
    assert composer(entrees)["leads_par_canal"]["canaux"][0]["marge_somme_partielle"] is False
    entrees["performance"]["campagnes"][0]["manque"] = ["SOMME_MARGES_CONNUES_SEULEMENT"]
    assert composer(entrees)["leads_par_canal"]["canaux"][0]["marge_somme_partielle"] is True
    entrees["performance"]["campagnes"][0]["manque"] = []
    entrees["performance"]["campagnes"].append(
        {
            "source": "facebook",
            "campagne": "autre",
            "leads_associes_observes": 1,
            "devis_acceptes": 1,
            "marge_constatee_M5_cad": None,
            "couverture": "PARTIELLE",
            "manque": [],
        }
    )
    assert composer(entrees)["leads_par_canal"]["canaux"][0]["marge_somme_partielle"] is True


def test_le_cout_par_lead_est_celui_de_m8_tel_quel_et_jamais_recalcule(entrees):
    c = composer(entrees)["cout_par_lead"]
    assert c["cout_par_lead_pub_cad"]["valeur"] == "42.50" and c["leads_publicitaires"]["valeur"] == "8"
    assert "jamais recalculé" in c["source"]


def test_cout_par_lead_non_calculable_est_dit_pas_zero(entrees, fab):
    entrees["m8_mesures"] = [
        fab.mesure("m8_cout_par_lead_pub_cad", None, statut="non_calculable", fraicheur="manquant")
    ]
    c = composer(entrees)["cout_par_lead"]
    assert c["statut"] == "donnees_insuffisantes" and "non calculable" in c["manque"]
    assert "0" not in str(c["cout_par_lead_pub_cad"]["valeur"])


def test_roi_n_est_jamais_un_ratio_calcule_ici_mais_montre_les_deux_composantes_de_m5(entrees):
    r = composer(entrees)["roi"]
    assert (
        r["roi"] is None and r["marge_constatee_m5_cad"] == "3100.00" and r["depense_comptabilisee_m5_cad"] == "340.00"
    )
    assert "ne recalcule pas la finance" in r["raison"] and "CPA" in r["raison"]


def test_conversion_est_un_rapport_de_comptes_entiers_avec_un_seuil(entrees, fab):
    c = composer(entrees)["conversion"]
    assert c["statut"] == "calcule" and c["leads_attribues_aux_contenus"] == 6
    assert c["lead_vers_devis_envoye_pct"] == "67" and c["lead_vers_devis_accepte_pct"] == "33"
    entrees["m8_contenus"] = [fab.contenu("facebook-aaaa", leads=2, envoyes=1, acceptes=1)]
    petit = composer(entrees)["conversion"]
    assert petit["statut"] == "donnees_insuffisantes" and "lead_vers_devis_accepte_pct" not in petit
    assert "au moins 5 leads" in petit["manque"]


def test_conversion_avec_des_comptes_inconnus_n_est_pas_calculee(entrees, fab):
    ligne = fab.contenu("facebook-zzzz", leads=6)
    ligne["devis_envoyes"] = None  # M8 : entonnoir non reçu
    entrees["m8_contenus"] = [ligne]
    assert composer(entrees)["conversion"]["statut"] == "donnees_insuffisantes"


def test_meilleurs_et_pires_contenus_exigent_assez_de_contenus_mesurables(entrees, fab):
    c = composer(entrees)["contenus"]
    assert [x["utm_content"] for x in c["meilleurs"]] == ["facebook-aaaa", "instagram-bbbb"]
    assert [x["utm_content"] for x in c["faibles"]] == ["fiche_google-cccc", "video_courte-dddd"]
    assert c["exportes"] == 5 and c["mesurables"] == 4 and c["sans_lien_de_suivi"] == 1
    assert c["sans_lien_ids"] == ["facebook-eeee"]
    entrees["m8_contenus"] = entrees["m8_contenus"][:2]
    pauvre = composer(entrees)["contenus"]
    assert pauvre["statut"] == "donnees_insuffisantes" and "meilleurs" not in pauvre


def test_un_contenu_recent_sans_lead_n_est_pas_dit_faible(entrees, fab):
    entrees["m8_contenus"][2] = fab.contenu(
        "fiche_google-cccc", "fiche_google", leads=0, exporte="2026-10-30T10:00:00-04:00"
    )
    assert "fiche_google-cccc" not in [x["utm_content"] for x in composer(entrees)["contenus"]["faibles"]]


def test_tie_break_des_meilleurs_est_stable_quel_que_soit_l_ordre_des_entrees(entrees):
    a = composer(entrees)
    entrees["m8_contenus"].reverse()
    assert composer(entrees)["contenus"]["meilleurs"] == a["contenus"]["meilleurs"]


def test_croissance_dit_la_variation_entre_les_deux_dernieres_observations(entrees):
    series = {(s["plateforme"], s["metrique"]): s for s in composer(entrees)["croissance_engagement"]["series"]}
    ig = series[("instagram", "abonnes")]
    assert ig["derniere_valeur"] == "100" and ig["variation"] == {"difference": "-20", "pct": "-17"}
    assert ig["observation_ids"] == ["obs-ig-abonnes-1", "obs-ig-abonnes-2"]


def test_chaque_source_absente_donne_une_section_qui_dit_ce_qui_manque_pas_un_zero():
    r = composer({})
    for nom in (
        "leads_par_canal",
        "cout_par_lead",
        "contenus",
        "calendrier",
        "reputation",
        "croissance_engagement",
        "conversion",
    ):
        assert r[nom]["statut"] == "source_absente" and r[nom]["manque"], nom
    assert r["sources"] == {n: "absente" for n in composition.SOURCES}
    assert r["recommandations"] and recommandations.verifier_liaison(r) == []
    assert len(r["donnees_manquantes"]) >= 7


def test_une_source_mal_formee_est_illisible_donc_absente(entrees):
    entrees["performance"] = "n'importe quoi"
    entrees["m8_contenus"] = {"pas": "une liste"}
    r = composer(entrees)
    assert r["sources"]["performance"] == "illisible" and r["sources"]["m8_contenus"] == "illisible"
    assert r["leads_par_canal"]["statut"] == "source_absente" and r["contenus"]["statut"] == "source_absente"


def test_aucun_lead_observe_n_est_pas_un_zero(entrees):
    entrees["performance"] = {"campagnes": []}
    s = composer(entrees)["leads_par_canal"]
    assert s["statut"] == "donnees_insuffisantes" and "pas un zéro" in s["manque"] and "total_leads" not in s


def test_rapport_deterministe_et_independant_de_l_ordre_des_mesures(entrees):
    a = composer(entrees)
    b = composer(copy.deepcopy(entrees))
    assert a == b and json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    entrees["m8_mesures"].reverse()
    assert composer(entrees)["cout_par_lead"] == a["cout_par_lead"]


def test_le_debut_doit_etre_un_lundi():
    with pytest.raises(ValueError):
        composition.composer({}, "2026-10-27")
    with pytest.raises(ValueError):
        composition.composer({}, "26-10-2026")


def test_le_rapport_ne_contient_aucun_texte_de_client_ni_coordonnee(entrees):
    entrees["reputation"]["note_moyenne_semaine"] = 4
    texte = json.dumps(composer(entrees), ensure_ascii=False)
    assert "@" not in texte and "wct" not in texte and "lead_id" not in texte


def test_les_mesures_inattendues_de_m8_ne_sont_pas_reprises(entrees, fab):
    entrees["m8_mesures"].append(fab.mesure("m8_secret_interne", "999"))
    assert "m8_secret_interne" not in composer(entrees)["mesures_m8"]["mesures"]


def test_valeur_non_texte_d_une_mesure_n_est_pas_reprise(entrees, fab):
    m = fab.mesure("m8_cout_par_lead_pub_cad", None)
    m["valeur"] = 42.5  # M8 rend du texte : un nombre flottant n'est pas une valeur reconnue
    entrees["m8_mesures"] = [m]
    assert composer(entrees)["mesures_m8"]["mesures"]["m8_cout_par_lead_pub_cad"]["valeur"] is None
