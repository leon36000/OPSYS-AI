"""Phase 2 de l'entrepôt de M8, les pièces une à une : les sept types de constats rangés, la source UTM des leads (D6),
les
déclarations du propriétaire dans les registres, la cadence de la source dans la fenêtre de fraîcheur (D7).

Pur (aucune base). Les sept types sont réduits à la liste fermée du catalogue d'événements : une propriété de plus ne
se range
pas. Données fictives.
"""

from __future__ import annotations

import copy

import pytest
from m8_analytics import (
    catalogue_mesures,
    entonnoir,
    fraicheur_mesures,
    jeux_fictifs,
    moteur_mesures,
)
from m8_analytics import (
    operations_recues as op,
)

FICTIF = True
CAT = catalogue_mesures.charger()
ENTREES = catalogue_mesures.par_identifiant(CAT)
PUBLIE = "2026-10-30T07:00:00-04:00"


# ================================================================================================ types de constats
def test_les_huit_types_de_la_phase_2_sont_declares_avec_leur_evenement_et_leur_cle_de_contenu():
    assert len(op.EVENEMENT_PAR_TYPE) == 16
    attendus = {
        "m5.depense_publicitaire_constatee": op.TYPE_DEPENSE_COMPTABILISEE,
        "m5.facture_emise_constatee": op.TYPE_FACTURE_EMISE,
        "m7.performance_signaux_constatee": op.TYPE_PERFORMANCE,
        "m4.capacite_equipe_constatee": op.TYPE_CAPACITE,
        "m2.pipeline_constate": op.TYPE_PIPELINE,
        "m6.disponibilite_constatee": op.TYPE_DISPONIBILITE,
        "m1.plaintes_constatees": op.TYPE_PLAINTES,
        "m2.filet_anti_perte_constate": op.TYPE_FILET,
    }
    for evenement, type_entree in attendus.items():
        assert op.EVENEMENT_PAR_TYPE[evenement] == type_entree
        assert op.cles_unicite(type_entree)
    # la dépense suit le rang de M5 ; une facture son statut ; un constat horodaté son instant de constat
    assert op.cles_unicite(op.TYPE_DEPENSE_COMPTABILISEE) == ("periode_debut", "periode_fin", "sequence")
    assert op.cles_unicite(op.TYPE_FACTURE_EMISE) == ("facture_id", "statut")
    for type_entree in (op.TYPE_CAPACITE, op.TYPE_PIPELINE, op.TYPE_DISPONIBILITE):
        assert "constate_le" in op.cles_unicite(type_entree)


def _faits_fictifs():
    return {f["type_entree"]: f for f in jeux_fictifs.operations_fictives()}


@pytest.mark.parametrize("type_entree", sorted(op.TYPES_PHASE_2))
def test_chaque_fait_garde_son_instant_de_publication_et_sa_provenance_mais_aucune_propriete_de_plus(type_entree):
    fait = _faits_fictifs()[type_entree]
    assert fait["publie_le"].startswith("2026-10-30T")
    assert fait["provenance"]["evenement"] in op.EVENEMENT_PAR_TYPE and len(fait["provenance"]["empreinte"]) == 64
    charge = {k: v for k, v in fait.items() if k not in ("type_entree", "provenance", "publie_le")}
    charge["evenement_id"] = fait["provenance"]["evenement_id"]
    charge["champ_personnel_en_trop"] = "Jeanne Fictive"
    range_ = op.fait(type_entree, charge, PUBLIE)
    assert "champ_personnel_en_trop" not in range_
    assert range_["publie_le"] == PUBLIE
    # l'empreinte de provenance porte la charge REÇUE (avant réduction), elle ne change pas le contenu rangé
    assert range_["provenance"]["empreinte"] != fait["provenance"]["empreinte"]


def test_le_resume_du_recu_du_bus_ne_porte_aucun_montant_ni_valeur():
    for type_entree, fait in _faits_fictifs().items():
        if type_entree not in op.TYPES_PHASE_2:
            continue
        resume = op.resume_recu(type_entree, fait)
        assert set(resume) == {"type_entree", op.cles_unicite(type_entree)[0]}, type_entree


def test_la_section_de_la_vue_executive_ne_montre_aucun_des_sept_types():
    nouveaux = [f for f in jeux_fictifs.operations_fictives() if f["type_entree"] in op.TYPES_PHASE_2]
    assert nouveaux and op.section(nouveaux) is None
    avec = op.section(jeux_fictifs.operations_fictives())
    sans = op.section([f for f in jeux_fictifs.operations_fictives() if f not in nouveaux])
    assert avec == sans, "les résumés de la phase 2 se lisent par leurs mesures, pas par la vue exécutive"


def test_un_type_inconnu_ou_une_charge_incomplete_est_refuse():
    with pytest.raises(ValueError):
        op.fait("inconnu", {}, PUBLIE)
    with pytest.raises(KeyError):
        op.fait(op.TYPE_PIPELINE, {"date_reference": "2026-10-30"}, PUBLIE)


# ================================================================================================ D6 : source UTM
def test_le_fait_lead_recu_garde_la_source_utm_en_minuscules_jamais_la_campagne():
    base = {"lead_id": "lead-1", "client_id": "a" * 64, "horodatage_association": "2026-10-30T08:00:00-04:00"}
    assert "utm_source" not in entonnoir.fait_lead_recu(base)
    fait = entonnoir.fait_lead_recu({**base, "utm": {"utm_source": " Google ", "utm_campaign": "ete-2026"}})
    assert fait["utm_source"] == "google" and "utm_campaign" not in fait and "client_id" not in fait
    assert "utm_source" not in entonnoir.fait_lead_recu({**base, "utm": {"utm_campaign": "ete-2026"}})
    assert "utm_source" not in entonnoir.fait_lead_recu({**base, "utm": {"utm_source": "  "}})


# ================================================================================================ déclarations du
# propriétaire
def test_les_declarations_sont_facultatives_et_comptent_dans_l_empreinte_des_registres():
    avec = jeux_fictifs.registres_fictifs(avec_operations=True)
    sans_cle = {k: v for k, v in avec.items() if k != "declarations"}
    assert moteur_mesures.normaliser_registres(sans_cle)["declarations"] == []
    autre = copy.deepcopy(avec)
    autre["declarations"][0]["canaux"]["meta"].append("tiktok")
    assert moteur_mesures.empreinte_registres(autre) != moteur_mesures.empreinte_registres(avec)
    assert moteur_mesures.empreinte_registres(sans_cle) != moteur_mesures.empreinte_registres(avec)
    with pytest.raises(ValueError, match="REJ-MOTEUR-REGISTRES"):
        moteur_mesures.normaliser_registres({**avec, "declarations": "canaux"})


# ================================================================================================ D7 : cadence
def test_la_cadence_de_la_source_releve_la_fenetre_du_producteur_au_dessus_de_24_h():
    capacite = ENTREES["m8_capacite_heures_disponibles"]
    assert capacite["fraicheur"] == {"fenetre_s": 86400, "cadence_s": 604800}
    assert fraicheur_mesures.fenetre_effective(capacite, {}) == {
        "secondes": 604800,
        "origine": fraicheur_mesures.ORIGINE_CADENCE,
    }
    # une mesure sporadique sans cadence déclarée garde 24 h : aucune fenêtre n'est inventée
    sporadique = ENTREES["m8_factures_emises"]
    assert sporadique["fraicheur"]["cadence_s"] is None
    assert fraicheur_mesures.fenetre_effective(sporadique, {}) == {
        "secondes": 86400,
        "origine": fraicheur_mesures.ORIGINE_CATALOGUE,
    }


def test_le_proprietaire_declare_une_cadence_qui_remplace_celle_du_catalogue():
    sporadique = ENTREES["m8_factures_emises"]
    assert fraicheur_mesures.fenetre_effective(sporadique, {}, None, None, {"m8_factures_emises": 7 * 86400}) == {
        "secondes": 604800,
        "origine": fraicheur_mesures.ORIGINE_CADENCE,
    }
    capacite = ENTREES["m8_capacite_heures_disponibles"]
    # une cadence plus courte que 24 h ne raccourcit jamais la fenêtre : max(24 h, cadence)
    assert fraicheur_mesures.fenetre_effective(capacite, {}, None, None, {"m8_capacite_heures_disponibles": 3600}) == {
        "secondes": 86400,
        "origine": fraicheur_mesures.ORIGINE_CATALOGUE,
    }


def test_la_fenetre_fixee_par_le_proprietaire_l_emporte_sur_toute_cadence():
    capacite = ENTREES["m8_capacite_heures_disponibles"]
    assert fraicheur_mesures.fenetre_effective(capacite, {"m8_capacite_heures_disponibles": 7200}) == {
        "secondes": 7200,
        "origine": fraicheur_mesures.ORIGINE_CONFIGURATION,
    }


def test_l_appelant_et_la_source_resserrent_toujours_meme_une_fenetre_elargie_par_la_cadence():
    capacite = ENTREES["m8_capacite_heures_disponibles"]
    assert fraicheur_mesures.fenetre_effective(capacite, {}, 3600)["origine"] == fraicheur_mesures.ORIGINE_APPELANT
    assert fraicheur_mesures.fenetre_effective(capacite, {}, None, 7200) == {
        "secondes": 7200,
        "origine": fraicheur_mesures.ORIGINE_SOURCE,
    }


def test_une_mesure_terminale_n_a_pas_de_cadence_et_reste_terminale():
    terminale = ENTREES["m8_heures_sur_site_chantiers"]
    assert terminale["fraicheur"] == {"terminale": True}
    assert fraicheur_mesures.fenetre_effective(terminale, {}, None, None, {"m8_heures_sur_site_chantiers": 99999}) == {
        "secondes": None,
        "origine": fraicheur_mesures.ORIGINE_TERMINALE,
    }


def test_la_configuration_des_cadences_se_lit_comme_celle_des_fenetres_valeur_invalide_dite():
    lue = fraicheur_mesures.lire_configuration(
        {"m8_capacite_heures_disponibles": 604800, "m8_factures_emises": 0, "m8_inconnue": 5, "m8_visites_site": True},
        CAT,
    )
    assert lue["fenetres"] == {"m8_capacite_heures_disponibles": 604800}
    assert {r["metric_id"] for r in lue["refusees"]} == {"m8_factures_emises", "m8_visites_site"}
    assert lue["ignorees"] == ["m8_inconnue"]
    assert fraicheur_mesures.CLE_CADENCES == "cadences_mesures_s"


def test_une_mesure_lue_est_evaluee_avec_la_cadence_du_catalogue_et_celle_du_proprietaire():
    registres = jeux_fictifs.registres_fictifs(avec_operations=True)
    lues = moteur_mesures.lire(registres, CAT)
    cinq_jours = fraicheur_mesures.lire_maintenant("2026-11-04T07:00:00-05:00")
    par_defaut = {m["metric_id"]: m for m in fraicheur_mesures.lire_mesures_avec_fraicheur(lues, CAT, cinq_jours, {})}
    assert par_defaut["m8_capacite_heures_disponibles"]["fraicheur"]["statut"] == fraicheur_mesures.STATUT_A_JOUR
    assert (
        par_defaut["m8_capacite_heures_disponibles"]["fraicheur"]["origine_fenetre"]
        == fraicheur_mesures.ORIGINE_CADENCE
    )
    assert par_defaut["m8_pipeline_leads_ouverts"]["fraicheur"]["statut"] == fraicheur_mesures.STATUT_PERIME
    avec_cadence = {
        m["metric_id"]: m
        for m in fraicheur_mesures.lire_mesures_avec_fraicheur(
            lues, CAT, cinq_jours, {}, None, {"m8_pipeline_leads_ouverts": 7 * 86400}
        )
    }
    assert avec_cadence["m8_pipeline_leads_ouverts"]["fraicheur"]["statut"] == fraicheur_mesures.STATUT_A_JOUR
    assert avec_cadence["m8_articles_en_rupture"]["fraicheur"]["statut"] == fraicheur_mesures.STATUT_PERIME
