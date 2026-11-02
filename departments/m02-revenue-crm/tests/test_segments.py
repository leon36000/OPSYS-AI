"""PLAN T4.6 (M2.11) : les 14 segments, leurs règles citées et ce qui manque quand ils ne se calculent pas.

`segments.py` est PUR : aucune base, aucune horloge (l'instant est un argument). Chaque test fixe l'instant, les
seuils et les faits, et vérifie le segment, sa règle et la donnée qui le déclenche. Les cas négatifs comptent autant
que les positifs : un segment ne se déclenche ni à la frontière moins une seconde, ni avec un statut voisin, ni avec
une valeur « presque vraie » (texte, 1). Un segment non calculable ne se déclenche jamais, quelles que soient les
données. Données fictives.
"""

from __future__ import annotations

import copy
import itertools
import re
from pathlib import Path

import pytest
from m2_revenue_crm import segments, statuts

FICTIF = True

RACINE = Path(__file__).resolve().parents[3]
MAINTENANT = "2026-09-29T12:00:00-04:00"
SEUILS_OK = segments.lire_seuils({"jours_inactivite_dormant": 30, "jours_soumission_perimee": 14})
SEUILS_VIDES = segments.lire_seuils({})


def _lead(statut: str = "qualifie", **plus) -> dict:
    base = {
        "lead_id": "lead-fictif-1",
        "statut": statut,
        "urgence_declaree": False,
        "derniere_activite": MAINTENANT,  # activité à l'instant : jamais dormant par défaut
        "reference_devis_m3": None,
    }
    return {**base, **plus}


def _faits(**plus) -> dict:
    base = {"maintenant": MAINTENANT, "pret_pour_m3": False, "devis_sans_reponse": [], "satisfaction": {},
            "opportunite_payee": None}
    return {**base, **plus}


def _noms(resultat: dict) -> list[str]:
    return [s["segment"] for s in resultat["segments"]]


def _manques(resultat: dict) -> dict[str, str]:
    return {n["segment"]: n["manque"] for n in resultat["non_calculables"]}


def _segment(resultat: dict, nom: str) -> dict:
    return next(s for s in resultat["segments"] if s["segment"] == nom)


def _devis(
    devis_id: str = "devis-fictif-1", statut: str = "envoye", horodatage: str = "2026-09-01T12:00:00-04:00",
) -> dict:
    return {"devis_id": devis_id, "lead_id": "lead-fictif-1", "statut_devis": statut, "horodatage_devis": horodatage}


# ---------------------------------------------------------------------------------------------------------
# Les 14 segments : la définition du produit, l'ordre, le partage calculable / non calculable
# ---------------------------------------------------------------------------------------------------------
def test_les_14_segments_sont_ceux_de_la_definition_du_produit_dans_son_ordre():
    """Épinglé sur le texte de DEFINITION-PRODUIT §7 M2.11 : un segment ajouté, retiré ou renommé là-bas fait
    échouer ce test, il ne laisse pas une liste locale dériver."""
    texte = (RACINE / "docs" / "produit" / "DEFINITION-PRODUIT.md").read_text(encoding="utf-8")
    ligne = re.search(r"^- M2\.11 Segmentation : (.+)$", texte, re.M)
    assert ligne is not None, "la ligne M2.11 n'est plus dans la définition du produit"
    assert tuple(re.findall(r"`([a-z_]+)`", ligne.group(1))) == segments.SEGMENTS
    assert len(segments.SEGMENTS) == 14 == len(set(segments.SEGMENTS))


def test_onze_segments_calculables_trois_non_calculables_sans_recouvrement():
    """M2-C5 : `quote_sent`, `referral_candidate` et `complaint_risk` ne sont plus structurellement non calculables."""
    assert segments.SEGMENTS_CALCULABLES == (
        "hot_lead", "estimate_ready", "quote_sent", "quote_stale", "won_pending_schedule", "active_job",
        "invoice_pending", "past_customer", "referral_candidate", "complaint_risk", "dormant_lead",
    )
    assert segments.SEGMENTS_NON_CALCULABLES == ("needs_photos", "high_value_customer", "seasonal_opportunity")
    assert set(segments.SEGMENTS_CALCULABLES) | set(segments.SEGMENTS_NON_CALCULABLES) == set(segments.SEGMENTS)
    assert not set(segments.SEGMENTS_CALCULABLES) & set(segments.SEGMENTS_NON_CALCULABLES)


def test_les_statuts_lus_par_les_regles_existent_dans_la_machine_a_etats():
    """Un statut renommé dans `statuts.py` ne doit pas rendre une règle muette sans que personne le voie."""
    lus = {
        segments._STATUT_QUALIFIE, segments._STATUT_CONVERTI, segments._STATUT_PAYE,
        *segments._STATUTS_OUVERTS, *segments._STATUTS_CHANTIER, *segments._STATUTS_FACTURE,
    }
    assert lus <= set(statuts.STATUTS)


def test_chaque_segment_calculable_a_une_regle_citee_et_chaque_regle_sert():
    regles_des_segments = set(segments._REGLE_DE_SEGMENT.values())
    assert set(segments._REGLE_DE_SEGMENT) == set(segments.SEGMENTS_CALCULABLES)
    assert set(segments.REGLES) == regles_des_segments
    assert all(len(texte) > 20 and texte.endswith(".") for texte in segments.REGLES.values())


# ---------------------------------------------------------------------------------------------------------
# Statuts : ce que chaque statut déclenche seul (aucune donnée voisine)
# ---------------------------------------------------------------------------------------------------------
STATUT_VERS_SEGMENTS = {
    "nouveau": [], "qualifie": [], "perdu": [], "avis": [],
    "converti": ["won_pending_schedule"],
    "cedule": ["active_job"], "chantier": ["active_job"],
    "facture": ["invoice_pending"], "paiement": ["invoice_pending"],
}


def test_la_table_de_statuts_couvre_toute_la_machine_a_etats():
    assert set(STATUT_VERS_SEGMENTS) == set(statuts.STATUTS)


@pytest.mark.parametrize("statut", statuts.STATUTS)
def test_un_statut_seul_declenche_exactement_ses_segments(statut):
    resultat = segments.segmenter(_lead(statut, reference_devis_m3="devis-fictif-9"), _faits(), SEUILS_OK)
    assert _noms(resultat) == STATUT_VERS_SEGMENTS[statut]


def test_soumission_acceptee_cite_sa_regle_et_le_devis():
    resultat = segments.segmenter(_lead("converti", reference_devis_m3="devis-fictif-9"), _faits(), SEUILS_OK)
    assert resultat["segments"] == [{
        "segment": "won_pending_schedule", "regle": "soumission_acceptee_a_planifier",
        "donnee": {"statut": "converti", "reference_devis_m3": "devis-fictif-9"},
    }]


@pytest.mark.parametrize(("statut", "segment", "regle"), [
    ("cedule", "active_job", "chantier_cedule_ou_en_cours"),
    ("chantier", "active_job", "chantier_cedule_ou_en_cours"),
    ("facture", "invoice_pending", "chantier_facture_paiement_non_confirme"),
    ("paiement", "invoice_pending", "chantier_facture_paiement_non_confirme"),
])
def test_chantier_et_facture_citent_leur_regle_et_le_statut(statut, segment, regle):
    resultat = segments.segmenter(_lead(statut), _faits(), SEUILS_OK)
    assert resultat["segments"] == [{"segment": segment, "regle": regle, "donnee": {"statut": statut}}]


# ---------------------------------------------------------------------------------------------------------
# hot_lead
# ---------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("statut", ["nouveau", "qualifie"])
def test_urgence_declaree_sur_un_lead_ouvert_est_chaude(statut):
    resultat = segments.segmenter(_lead(statut, urgence_declaree=True), _faits(), SEUILS_OK)
    assert resultat["segments"] == [{
        "segment": "hot_lead", "regle": "urgence_declaree_lead_ouvert",
        "donnee": {"urgence_declaree": True, "statut": statut},
    }]


@pytest.mark.parametrize("statut", ["converti", "cedule", "chantier", "facture", "paiement", "avis", "perdu"])
def test_urgence_declaree_sur_un_lead_ferme_ou_avance_n_est_pas_chaude(statut):
    resultat = segments.segmenter(_lead(statut, urgence_declaree=True), _faits(), SEUILS_OK)
    assert "hot_lead" not in _noms(resultat)


@pytest.mark.parametrize("urgence", [False, None, "oui", "true", 1, 0, [True]])
def test_seule_une_urgence_vraie_rend_chaud_jamais_une_valeur_presque_vraie(urgence):
    resultat = segments.segmenter(_lead("qualifie", urgence_declaree=urgence), _faits(), SEUILS_OK)
    assert "hot_lead" not in _noms(resultat)


def test_urgence_absente_du_lead_n_est_pas_chaude():
    lead = _lead("qualifie")
    del lead["urgence_declaree"]
    assert "hot_lead" not in _noms(segments.segmenter(lead, _faits(), SEUILS_OK))


# ---------------------------------------------------------------------------------------------------------
# estimate_ready
# ---------------------------------------------------------------------------------------------------------
def test_readiness_satisfaite_sur_un_lead_qualifie_est_prete_pour_l_estimation():
    resultat = segments.segmenter(_lead("qualifie"), _faits(pret_pour_m3=True), SEUILS_OK)
    assert resultat["segments"] == [{
        "segment": "estimate_ready", "regle": "readiness_m3_satisfaite",
        "donnee": {"statut": "qualifie", "pret_pour_m3": True},
    }]


def test_readiness_non_satisfaite_n_est_pas_prete_et_reste_calculable():
    resultat = segments.segmenter(_lead("qualifie"), _faits(pret_pour_m3=False), SEUILS_OK)
    assert "estimate_ready" not in _noms(resultat)
    assert "estimate_ready" not in _manques(resultat)


@pytest.mark.parametrize("statut", [s for s in statuts.STATUTS if s != "qualifie"])
def test_seul_un_lead_qualifie_peut_etre_pret_pour_l_estimation(statut):
    resultat = segments.segmenter(_lead(statut), _faits(pret_pour_m3=True), SEUILS_OK)
    assert "estimate_ready" not in _noms(resultat)


def test_readiness_jamais_evaluee_d_un_lead_qualifie_est_non_calculable_pas_fausse():
    resultat = segments.segmenter(_lead("qualifie"), _faits(pret_pour_m3=None), SEUILS_OK)
    assert "estimate_ready" not in _noms(resultat)
    assert _manques(resultat)["estimate_ready"].startswith("non calculable, manque ")


# ---------------------------------------------------------------------------------------------------------
# quote_stale
# ---------------------------------------------------------------------------------------------------------
def test_devis_envoye_au_dela_du_seuil_est_perime_avec_sa_donnee():
    faits = _faits(devis_sans_reponse=[_devis(horodatage="2026-09-01T12:00:00-04:00")])  # 28 jours avant
    resultat = segments.segmenter(_lead("qualifie"), faits, SEUILS_OK)
    assert _segment(resultat, "quote_stale") == {
        "segment": "quote_stale", "regle": "devis_envoye_sans_reponse_perime",
        "donnee": {
            "devis_id": "devis-fictif-1", "statut_devis": "envoye",
            "horodatage_devis": "2026-09-01T12:00:00-04:00", "jours_ecoules": 28, "seuil_jours": 14,
        },
    }
    assert _noms(resultat) == ["quote_sent", "quote_stale"], "un devis périmé est aussi un devis envoyé"


def test_frontiere_du_seuil_de_soumission_exactement_egal_est_perime_une_seconde_de_moins_ne_l_est_pas():
    # Seuil de 14 jours ; maintenant = 2026-09-29T12:00-04:00 = 16:00Z.
    exact = _devis(horodatage="2026-09-15T16:00:00+00:00")
    presque = _devis(horodatage="2026-09-15T16:00:01+00:00")
    assert "quote_stale" in _noms(
        segments.segmenter(_lead("qualifie"), _faits(devis_sans_reponse=[exact]), SEUILS_OK))
    assert "quote_stale" not in _noms(
        segments.segmenter(_lead("qualifie"), _faits(devis_sans_reponse=[presque]), SEUILS_OK))


def test_un_devis_brouillon_n_est_jamais_perime_le_client_n_a_rien_recu():
    faits = _faits(devis_sans_reponse=[_devis(statut="brouillon", horodatage="2026-01-01T12:00:00-04:00")])
    resultat = segments.segmenter(_lead("qualifie"), faits, SEUILS_OK)
    assert "quote_stale" not in _noms(resultat)
    assert "quote_stale" not in _manques(resultat)


@pytest.mark.parametrize("statut", [s for s in statuts.STATUTS if s != "qualifie"])
def test_un_devis_perime_ne_compte_que_pour_un_lead_qualifie(statut):
    faits = _faits(devis_sans_reponse=[_devis(horodatage="2026-01-01T12:00:00-04:00")])
    assert "quote_stale" not in _noms(segments.segmenter(_lead(statut), faits, SEUILS_OK))


def test_sans_seuil_un_devis_tres_ancien_n_est_pas_declare_perime_le_segment_est_non_calculable():
    faits = _faits(devis_sans_reponse=[_devis(horodatage="2020-01-01T12:00:00-04:00")])
    resultat = segments.segmenter(_lead("qualifie"), faits, SEUILS_VIDES)
    assert "quote_stale" not in _noms(resultat)
    manque = _manques(resultat)["quote_stale"]
    assert manque.startswith("non calculable, manque le seuil jours_soumission_perimee")
    assert "seuil à configurer" in manque
    assert "configuration.segments" in manque


def test_un_seuil_invalide_est_dit_invalide_pas_a_configurer():
    seuils = segments.lire_seuils({"jours_soumission_perimee": "quatorze", "jours_inactivite_dormant": 30})
    resultat = segments.segmenter(_lead("qualifie"), _faits(devis_sans_reponse=[_devis()]), seuils)
    assert "quote_stale" not in _noms(resultat)
    assert "seuil invalide" in _manques(resultat)["quote_stale"]
    assert "seuil à configurer" not in _manques(resultat)["quote_stale"]


def test_source_des_devis_illisible_rend_le_segment_non_calculable_pas_aucun_devis_en_retard():
    resultat = segments.segmenter(_lead("qualifie"), _faits(devis_sans_reponse=None), SEUILS_OK)
    assert "quote_stale" not in _noms(resultat)
    assert "relances_devis_recues" in _manques(resultat)["quote_stale"]


def test_le_devis_le_plus_ancien_est_cite_puis_le_devis_id_departage():
    faits = _faits(devis_sans_reponse=[
        _devis("devis-b", horodatage="2026-09-01T12:00:00-04:00"),
        _devis("devis-a", horodatage="2026-08-01T12:00:00-04:00"),
        _devis("devis-c", horodatage="2026-09-10T12:00:00-04:00"),
    ])
    donnee = _segment(segments.segmenter(_lead("qualifie"), faits, SEUILS_OK), "quote_stale")["donnee"]
    assert donnee["devis_id"] == "devis-a"
    egaux = _faits(devis_sans_reponse=[_devis("devis-z", horodatage="2026-08-01T12:00:00-04:00"),
                                       _devis("devis-m", horodatage="2026-08-01T12:00:00-04:00")])
    assert _segment(segments.segmenter(_lead("qualifie"), egaux, SEUILS_OK), "quote_stale")["donnee"][
        "devis_id"] == "devis-m"


def test_les_jours_ecoules_sont_entiers_et_arrondis_vers_le_bas():
    faits = _faits(devis_sans_reponse=[_devis(horodatage="2026-09-13T13:00:00-04:00")])  # 15 j 23 h
    assert _segment(segments.segmenter(_lead("qualifie"), faits, SEUILS_OK), "quote_stale")["donnee"][
        "jours_ecoules"] == 15


@pytest.mark.parametrize("horodatage", ["hier", "2026-09-01T12:00:00", None, 42])
def test_horodatage_de_devis_illisible_est_non_calculable_et_nomme_le_devis(horodatage):
    faits = _faits(devis_sans_reponse=[_devis("devis-casse", horodatage=horodatage)])
    resultat = segments.segmenter(_lead("qualifie"), faits, SEUILS_OK)
    assert "quote_stale" not in _noms(resultat)
    assert "devis-casse" in _manques(resultat)["quote_stale"]


def test_un_devis_illisible_ne_cache_pas_un_autre_devis_perime_lisible():
    faits = _faits(devis_sans_reponse=[
        _devis("devis-casse", horodatage="hier"), _devis("devis-bon", horodatage="2026-08-01T12:00:00-04:00")])
    resultat = segments.segmenter(_lead("qualifie"), faits, SEUILS_OK)
    assert _segment(resultat, "quote_stale")["donnee"]["devis_id"] == "devis-bon"
    assert "quote_stale" not in _manques(resultat)


# ---------------------------------------------------------------------------------------------------------
# dormant_lead
# ---------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("statut", ["nouveau", "qualifie"])
def test_lead_ouvert_sans_activite_au_dela_du_seuil_est_dormant_avec_sa_donnee(statut):
    lead = _lead(statut, derniere_activite="2026-08-20T12:00:00-04:00")  # 40 jours
    resultat = segments.segmenter(lead, _faits(), SEUILS_OK)
    assert resultat["segments"] == [{
        "segment": "dormant_lead", "regle": "lead_ouvert_sans_activite",
        "donnee": {"derniere_activite": "2026-08-20T12:00:00-04:00", "jours_ecoules": 40, "seuil_jours": 30},
    }]


def test_frontiere_du_seuil_de_dormance_exactement_egal_est_dormant_une_seconde_de_moins_ne_l_est_pas():
    # Seuil de 30 jours ; maintenant = 16:00Z.
    exact = _lead("qualifie", derniere_activite="2026-08-30T16:00:00+00:00")
    presque = _lead("qualifie", derniere_activite="2026-08-30T16:00:01+00:00")
    assert "dormant_lead" in _noms(segments.segmenter(exact, _faits(), SEUILS_OK))
    assert "dormant_lead" not in _noms(segments.segmenter(presque, _faits(), SEUILS_OK))


@pytest.mark.parametrize("statut", [s for s in statuts.STATUTS if s not in ("nouveau", "qualifie")])
def test_seul_un_lead_ouvert_peut_etre_dormant(statut):
    lead = _lead(statut, derniere_activite="2020-01-01T12:00:00-04:00")
    assert "dormant_lead" not in _noms(segments.segmenter(lead, _faits(), SEUILS_OK))


def test_sans_seuil_un_lead_tres_ancien_n_est_pas_declare_dormant_le_segment_est_non_calculable():
    lead = _lead("qualifie", derniere_activite="2020-01-01T12:00:00-04:00")
    resultat = segments.segmenter(lead, _faits(), SEUILS_VIDES)
    assert "dormant_lead" not in _noms(resultat)
    manque = _manques(resultat)["dormant_lead"]
    assert manque.startswith("non calculable, manque le seuil jours_inactivite_dormant")
    assert "seuil à configurer" in manque


def test_derniere_activite_illisible_ou_absente_rend_le_segment_non_calculable_pour_ce_lead():
    for valeur in (None, "hier", "2026-08-20T12:00:00"):
        resultat = segments.segmenter(_lead("qualifie", derniere_activite=valeur), _faits(), SEUILS_OK)
        assert "dormant_lead" not in _noms(resultat)
        assert "dernière activité" in _manques(resultat)["dormant_lead"]


def test_les_fuseaux_ne_changent_pas_le_verdict_un_meme_instant_donne_le_meme_segment():
    a = _lead("qualifie", derniere_activite="2026-08-20T12:00:00-04:00")
    b = _lead("qualifie", derniere_activite="2026-08-20T16:00:00+00:00")
    c = _lead("qualifie", derniere_activite="2026-08-20T18:00:00+02:00")
    jours = [segments.segmenter(x, _faits(), SEUILS_OK)["segments"][0]["donnee"]["jours_ecoules"] for x in (a, b, c)]
    assert jours == [40, 40, 40]


# ---------------------------------------------------------------------------------------------------------
# past_customer
# ---------------------------------------------------------------------------------------------------------
def test_un_client_avec_un_chantier_paye_est_un_ancien_client_et_cite_ce_lead():
    resultat = segments.segmenter(_lead("qualifie"), _faits(opportunite_payee="lead-paye-1"), SEUILS_OK)
    assert resultat["segments"] == [{
        "segment": "past_customer", "regle": "client_avec_chantier_paye",
        "donnee": {"lead_paye": "lead-paye-1", "statut": "avis"},
    }]


@pytest.mark.parametrize("payee", [None, ""])
def test_sans_chantier_paye_visible_pas_d_ancien_client(payee):
    resultat = segments.segmenter(_lead("qualifie"), _faits(opportunite_payee=payee), SEUILS_OK)
    assert "past_customer" not in _noms(resultat)


def test_un_lead_peut_avoir_plusieurs_segments_dans_l_ordre_de_la_definition():
    lead = _lead("qualifie", urgence_declaree=True, derniere_activite="2026-01-01T12:00:00-04:00")
    faits = _faits(pret_pour_m3=True, opportunite_payee="lead-paye-1",
                   devis_sans_reponse=[_devis(horodatage="2026-08-01T12:00:00-04:00")])
    assert _noms(segments.segmenter(lead, faits, SEUILS_OK)) == [
        "hot_lead", "estimate_ready", "quote_sent", "quote_stale", "past_customer", "dormant_lead"]


# ---------------------------------------------------------------------------------------------------------
# Les trois segments sans donnée, et ce qui manque
# ---------------------------------------------------------------------------------------------------------
GRILLE_STATUTS = list(statuts.STATUTS)
DEVIS_POSSIBLES = [[], [_devis(horodatage="2020-01-01T12:00:00-04:00")], None]


@pytest.mark.parametrize("statut", GRILLE_STATUTS)
def test_les_trois_segments_sans_donnee_ne_se_declenchent_jamais_et_disent_ce_qui_manque(statut):
    lead = _lead(statut, urgence_declaree=True, derniere_activite="2020-01-01T12:00:00-04:00")
    faits = _faits(pret_pour_m3=True, opportunite_payee="lead-paye-1", devis_sans_reponse=[_devis()])
    resultat = segments.segmenter(lead, faits, SEUILS_OK)
    manques = _manques(resultat)
    for segment in segments.SEGMENTS_NON_CALCULABLES:
        assert segment not in _noms(resultat)
        assert manques[segment].startswith("non calculable, manque "), segment


def test_les_manques_disent_quelle_donnee_est_absente_pas_une_excuse_generique():
    manques = _manques(segments.segmenter(_lead("qualifie"), _faits(), SEUILS_OK))
    assert "photos" in manques["needs_photos"]
    assert "valeur du client" in manques["high_value_customer"]
    assert "saisonnier" in manques["seasonal_opportunity"]
    assert segments.manque_du_segment("needs_photos", SEUILS_OK).startswith("non calculable, manque ")


@pytest.mark.parametrize(
    ("statut", "seuils", "devis"),
    list(itertools.product(GRILLE_STATUTS, [SEUILS_OK, SEUILS_VIDES], DEVIS_POSSIBLES)),
)
def test_un_segment_n_est_jamais_a_la_fois_applique_et_non_calculable(statut, seuils, devis):
    lead = _lead(statut, urgence_declaree=True, derniere_activite="2020-01-01T12:00:00-04:00")
    resultat = segments.segmenter(lead, _faits(pret_pour_m3=True, devis_sans_reponse=devis), seuils)
    assert not set(_noms(resultat)) & set(_manques(resultat))
    ordre = list(segments.SEGMENTS)
    assert _noms(resultat) == sorted(_noms(resultat), key=ordre.index)
    assert [n["segment"] for n in resultat["non_calculables"]] == sorted(_manques(resultat), key=ordre.index)


def test_chaque_segment_applique_cite_une_regle_connue_et_une_donnee_non_vide():
    lead = _lead("qualifie", urgence_declaree=True, derniere_activite="2026-01-01T12:00:00-04:00")
    faits = _faits(pret_pour_m3=True, opportunite_payee="lead-paye-1",
                   devis_sans_reponse=[_devis(horodatage="2026-08-01T12:00:00-04:00")])
    tous = segments.segmenter(lead, faits, SEUILS_OK)["segments"]
    tous += segments.segmenter(_lead("converti"), _faits(), SEUILS_OK)["segments"]
    tous += segments.segmenter(_lead("cedule"), _faits(), SEUILS_OK)["segments"]
    tous += segments.segmenter(_lead("facture"), _faits(), SEUILS_OK)["segments"]
    tous += segments.segmenter(_lead("facture"), _faits(satisfaction={"client_satisfait": True, "wct_id": "w1",
                               "horodatage_completion": MAINTENANT}), SEUILS_OK)["segments"]
    tous += segments.segmenter(_lead("avis"), _faits(satisfaction={"client_satisfait": False, "wct_id": "w2",
                               "horodatage_completion": MAINTENANT}), SEUILS_OK)["segments"]
    assert {s["segment"] for s in tous} == set(segments.SEGMENTS_CALCULABLES)
    for applique in tous:
        assert applique["regle"] in segments.REGLES
        assert applique["donnee"], applique
        assert set(applique) == {"segment", "regle", "donnee"}


# ---------------------------------------------------------------------------------------------------------
# Seuils de department.yaml
# ---------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(("brut", "etat"), [
    ({}, "a_configurer"), (None, "a_configurer"), ({"jours_inactivite_dormant": None}, "a_configurer"),
    ({"jours_inactivite_dormant": 1}, "ok"), ({"jours_inactivite_dormant": 365}, "ok"),
    ({"jours_inactivite_dormant": 0}, "invalide"), ({"jours_inactivite_dormant": -5}, "invalide"),
    ({"jours_inactivite_dormant": True}, "invalide"), ({"jours_inactivite_dormant": 30.0}, "invalide"),
    ({"jours_inactivite_dormant": "30"}, "invalide"), ({"jours_inactivite_dormant": [30]}, "invalide"),
    ([30], "invalide"), ("trente", "invalide"), (30, "invalide"),
])
def test_lecture_des_seuils_vide_valide_ou_invalide_sans_jamais_de_defaut(brut, etat):
    seuil = segments.lire_seuils(brut)["jours_inactivite_dormant"]
    assert seuil["etat"] == etat
    if etat == "ok":
        assert seuil["valeur"] == brut["jours_inactivite_dormant"]
    else:
        assert seuil["valeur"] is None


def test_les_deux_seuils_sont_lus_separement_et_une_cle_inconnue_est_ignoree():
    seuils = segments.lire_seuils({"jours_soumission_perimee": 7, "jours_bidon": 3})
    assert seuils["jours_soumission_perimee"] == {"etat": "ok", "valeur": 7}
    assert seuils["jours_inactivite_dormant"] == {"etat": "a_configurer", "valeur": None}
    assert set(seuils) == {"jours_soumission_perimee", "jours_inactivite_dormant"}


# ---------------------------------------------------------------------------------------------------------
# Pureté : mêmes entrées, même sortie, entrées intactes, aucune horloge
# ---------------------------------------------------------------------------------------------------------
def test_la_segmentation_est_deterministe_et_ne_modifie_pas_ses_entrees():
    lead = _lead("qualifie", urgence_declaree=True, derniere_activite="2026-01-01T12:00:00-04:00")
    faits = _faits(pret_pour_m3=True, devis_sans_reponse=[_devis(horodatage="2026-08-01T12:00:00-04:00")])
    avant = copy.deepcopy((lead, faits, SEUILS_OK))
    premier = segments.segmenter(lead, faits, SEUILS_OK)
    second = segments.segmenter(lead, faits, SEUILS_OK)
    assert premier == second
    assert (lead, faits, SEUILS_OK) == avant


def test_l_instant_de_reference_decide_seul_le_meme_lead_a_deux_instants():
    lead = _lead("qualifie", derniere_activite="2026-09-01T12:00:00-04:00")
    tot = segments.segmenter(lead, _faits(maintenant="2026-09-20T12:00:00-04:00"), SEUILS_OK)
    tard = segments.segmenter(lead, _faits(maintenant="2026-10-05T12:00:00-04:00"), SEUILS_OK)
    assert "dormant_lead" not in _noms(tot)
    assert "dormant_lead" in _noms(tard)


@pytest.mark.parametrize("maintenant", ["2026-09-29T12:00:00", "hier", None])
def test_un_instant_sans_fuseau_ou_illisible_est_refuse_jamais_le_fuseau_de_la_machine(maintenant):
    with pytest.raises((ValueError, TypeError)):
        segments.segmenter(_lead("qualifie"), _faits(maintenant=maintenant), SEUILS_OK)


def test_le_module_est_pur_aucun_import_opsys_ni_horloge():
    source = (Path(segments.__file__)).read_text(encoding="utf-8")
    assert not re.search(r"^\s*(from|import) opsys", source, re.M)
    assert "datetime.now" not in source
    assert "time.time" not in source
    assert "random" not in source


# ---------------------------------------------------------------------------------------------------------
# M2-C5 : quote_sent, referral_candidate, complaint_risk (des données déjà reçues, maintenant gardées)
# ---------------------------------------------------------------------------------------------------------
def test_quote_sent_cite_le_devis_envoye_le_plus_recent_pour_un_lead_qualifie():
    faits = _faits(devis_sans_reponse=[
        _devis("devis-1", horodatage="2026-09-20T12:00:00-04:00"),
        _devis("devis-2", horodatage="2026-09-25T12:00:00-04:00"),
        _devis("devis-brouillon", statut="brouillon", horodatage="2026-09-28T12:00:00-04:00")])
    envoi = _segment(segments.segmenter(_lead("qualifie"), faits, SEUILS_OK), "quote_sent")
    assert envoi == {"segment": "quote_sent", "regle": "devis_envoye_au_client", "donnee": {
        "devis_id": "devis-2", "statut_devis": "envoye", "horodatage_devis": "2026-09-25T12:00:00-04:00"}}


def test_quote_sent_ne_se_declenche_ni_sans_devis_envoye_ni_hors_du_statut_qualifie():
    brouillon = _faits(devis_sans_reponse=[_devis(statut="brouillon")])
    assert "quote_sent" not in _noms(segments.segmenter(_lead("qualifie"), brouillon, SEUILS_OK))
    assert "quote_sent" not in _noms(segments.segmenter(_lead("qualifie"), _faits(), SEUILS_OK))
    for statut in (s for s in statuts.STATUTS if s != "qualifie"):
        resultat = segments.segmenter(_lead(statut), _faits(devis_sans_reponse=[_devis()]), SEUILS_OK)
        assert "quote_sent" not in _noms(resultat)


def test_quote_sent_est_calculable_sans_aucun_seuil_et_non_calculable_si_les_devis_sont_illisibles():
    avec = segments.segmenter(_lead("qualifie"), _faits(devis_sans_reponse=[_devis()]), SEUILS_VIDES)
    assert "quote_sent" in _noms(avec), "le fait « devis envoyé » ne dépend d'aucun seuil"
    sans = segments.segmenter(_lead("qualifie"), _faits(devis_sans_reponse=None), SEUILS_OK)
    assert "quote_sent" not in _noms(sans) and "devis_envoyes_recus" in _manques(sans)["quote_sent"]


def test_un_horodatage_de_devis_illisible_ne_cache_pas_un_devis_envoye():
    faits = _faits(devis_sans_reponse=[_devis("devis-casse", horodatage="hier")])
    assert _segment(segments.segmenter(_lead("qualifie"), faits, SEUILS_OK), "quote_sent")["donnee"][
        "devis_id"] == "devis-casse"


@pytest.mark.parametrize("statut", statuts.STATUTS)
def test_un_client_satisfait_est_un_candidat_a_la_reference_quel_que_soit_le_statut(statut):
    faits = _faits(satisfaction={"client_satisfait": True, "wct_id": "wct-1", "horodatage_completion": MAINTENANT})
    resultat = segments.segmenter(_lead(statut), faits, SEUILS_OK)
    assert _segment(resultat, "referral_candidate") == {
        "segment": "referral_candidate", "regle": "client_satisfait_signale",
        "donnee": {"client_satisfait": True, "wct_id": "wct-1", "horodatage_completion": MAINTENANT}}
    assert "complaint_risk" not in _noms(resultat)


def test_un_client_insatisfait_est_un_risque_de_plainte_jamais_un_candidat():
    faits = _faits(satisfaction={"client_satisfait": False, "wct_id": "wct-2", "horodatage_completion": MAINTENANT})
    resultat = segments.segmenter(_lead("facture"), faits, SEUILS_OK)
    assert _segment(resultat, "complaint_risk")["regle"] == "client_insatisfait_signale"
    assert "referral_candidate" not in _noms(resultat)


@pytest.mark.parametrize("fait", [{}, {"client_satisfait": None}, {"client_satisfait": "oui"}, {"client_satisfait": 1},
                                   {"client_satisfait": 0}])
def test_sans_booleen_explicite_ni_candidat_ni_risque_et_les_deux_segments_restent_calculables(fait):
    resultat = segments.segmenter(_lead("facture"), _faits(satisfaction=fait), SEUILS_OK)
    assert not {"referral_candidate", "complaint_risk"} & set(_noms(resultat))
    assert not {"referral_candidate", "complaint_risk"} & set(_manques(resultat))


def test_le_dernier_chantier_termine_fait_foi_pour_la_satisfaction_d_un_lead():
    from m2_revenue_crm import faits_interconnexion as fi

    def fait(wct, quand, satisfait):
        return fi.fait_satisfaction({"wct_id": wct, "lead_id": "l1", "horodatage_completion": quand,
                                     "client_satisfait": satisfait}, "l1")

    plus_recent_en_premier = [
        fait("w2", "2026-09-20T12:00:00-04:00", False),
        fait("w1", "2026-09-01T12:00:00-04:00", True),
    ]
    assert fi.satisfaction_par_lead(plus_recent_en_premier)["l1"]["wct_id"] == "w2"
    assert fi.satisfaction_par_lead(reversed(plus_recent_en_premier))["l1"]["wct_id"] == "w2"
    assert fi.fait_satisfaction({"wct_id": "w", "lead_id": "l", "horodatage_completion": "x"}, None) is None
    assert fi.fait_satisfaction({"wct_id": "w", "lead_id": "l", "horodatage_completion": "x",
                                 "client_satisfait": None}, None) is None
    sur_origine = fi.fait_satisfaction({"wct_id": "w", "lead_id": "origine", "horodatage_completion": "x",
                                        "client_satisfait": False}, None)
    assert fi.satisfaction_par_lead([sur_origine]).keys() == {"origine"}


@pytest.mark.parametrize("brut", ["oui", "non", 1, 0, "true", [True], {"x": 1}])
def test_seul_un_booleen_explicite_est_garde_comme_satisfaction(brut):
    from m2_revenue_crm import faits_interconnexion as fi

    charge = {
        "wct_id": "w", "lead_id": "l", "horodatage_completion": "2026-09-01T12:00:00-04:00", "client_satisfait": brut,
    }
    assert fi.fait_satisfaction(charge, None) is None
