"""Cadence par défaut d'un constat planifié : DÉRIVÉE de la fraîcheur du catalogue de M8, jamais d'une constante.

Pur (catalogue livré, aucune base, aucune horloge). Prouve : la fenêtre d'un constat est la plus stricte des
fenêtres des mesures qu'il alimente ; la cadence de la source (D7) relève la fenêtre ; une déclaration du
propriétaire la change ; le constat passe plus d'une fois par fenêtre (une panne d'un passage ne périme pas la
mesure) ; une mesure inconnue ou sans fenêtre est refusée. Données fictives."""

from __future__ import annotations

import copy

import pytest
import yaml
from m8_analytics import cadence_constats, catalogue_mesures, fraicheur_mesures

FICTIF = True
CAT = catalogue_mesures.charger()
ENTREES = catalogue_mesures.par_identifiant(CAT)


def _fenetre(metric_id: str) -> int:
    return fraicheur_mesures.fenetre_effective(ENTREES[metric_id], {}, None, None, None)["secondes"]


def test_un_constat_passe_au_moins_deux_fois_par_fenetre_de_la_mesure_la_plus_stricte():
    assert cadence_constats.PASSAGES_PAR_FENETRE >= 2
    resultat = cadence_constats.calculer(["m8_factures_emises", "m8_facturation_emise_cad"], CAT)
    fenetre = _fenetre("m8_factures_emises")
    assert resultat["fenetre_s"] == fenetre == 86400
    assert resultat["intervalle_s"] == fenetre // cadence_constats.PASSAGES_PAR_FENETRE
    assert resultat["intervalle_s"] * cadence_constats.PASSAGES_PAR_FENETRE <= fenetre
    assert resultat["passages_par_fenetre"] == cadence_constats.PASSAGES_PAR_FENETRE


def test_la_cadence_de_la_source_releve_la_fenetre_la_capacite_hebdomadaire_n_est_pas_perimee_a_24_h():
    mesures = ["m8_capacite_heures_disponibles", "m8_capacite_heures_planifiees", "m8_charge_planifiee_pct"]
    resultat = cadence_constats.calculer(mesures, CAT)
    assert ENTREES[mesures[0]]["fraicheur"]["cadence_s"] == 604800
    assert resultat["fenetre_s"] == 604800 == _fenetre(mesures[0])
    assert resultat["intervalle_s"] == 604800 // cadence_constats.PASSAGES_PAR_FENETRE


def test_la_mesure_la_plus_stricte_commande_et_elle_est_nommee():
    resultat = cadence_constats.calculer(["m8_capacite_heures_disponibles", "m8_factures_emises"], CAT)
    assert resultat["mesure_limitante"] == "m8_factures_emises" and resultat["fenetre_s"] == 86400
    assert resultat["fenetres"] == {"m8_capacite_heures_disponibles": 604800, "m8_factures_emises": 86400}


def test_une_fenetre_declaree_par_le_proprietaire_change_la_cadence():
    resultat = cadence_constats.calculer(["m8_factures_emises"], CAT, {"m8_factures_emises": 7200})
    assert resultat["fenetre_s"] == 7200 and resultat["intervalle_s"] == 3600
    # une cadence de source déclarée plus longue que la fenêtre du catalogue la relève
    resultat = cadence_constats.calculer(["m8_factures_emises"], CAT, None, {"m8_factures_emises": 172800})
    assert resultat["fenetre_s"] == 172800 and resultat["intervalle_s"] == 86400


def test_une_mesure_inconnue_du_catalogue_est_refusee_pas_ignoree():
    with pytest.raises(ValueError, match=cadence_constats.REJ_MESURE_INCONNUE):
        cadence_constats.calculer(["m8_factures_emises", "m8_mesure_qui_n_existe_pas"], CAT)


def test_des_mesures_toutes_terminales_n_ont_aucune_cadence_a_deriver():
    terminale = next((e["metric_id"] for e in CAT["mesures"] if "terminale" in e["fraicheur"]), None)
    assert terminale is not None, "le catalogue livré a des mesures terminales (chantiers terminés)"
    with pytest.raises(ValueError, match=cadence_constats.REJ_AUCUNE_FENETRE):
        cadence_constats.calculer([terminale], CAT)
    # une mesure terminale ne commande rien quand une autre a une fenêtre
    assert cadence_constats.calculer([terminale, "m8_factures_emises"], CAT)["mesure_limitante"] == "m8_factures_emises"


def test_le_resultat_ne_depend_que_du_catalogue_pas_d_une_valeur_recopiee():
    modifie = copy.deepcopy(CAT)
    for entree in modifie["mesures"]:
        if entree["metric_id"] == "m8_factures_emises":
            entree["fraicheur"] = {"fenetre_s": 10000, "cadence_s": None}
    assert cadence_constats.calculer(["m8_factures_emises"], modifie)["intervalle_s"] == 5000


def test_cadence_par_defaut_lit_la_configuration_du_proprietaire_dans_le_manifeste(tmp_path, monkeypatch):
    sans = cadence_constats.cadence_par_defaut(["m8_factures_emises"])
    assert sans["fenetre_s"] == 86400
    manifeste = tmp_path / "department.yaml"
    manifeste.write_text(yaml.safe_dump({"configuration": {"fraicheur_mesures_s": {"m8_factures_emises": 21600}}}),
                         encoding="utf-8")
    monkeypatch.setattr(cadence_constats, "_MANIFESTE", manifeste)
    avec = cadence_constats.cadence_par_defaut(["m8_factures_emises"])
    assert avec["fenetre_s"] == 21600 and avec["intervalle_s"] == 10800
    # une déclaration invalide est refusée par la lecture des mesures : la cadence suit la fenêtre réellement appliquée
    manifeste.write_text(yaml.safe_dump({"configuration": {"fraicheur_mesures_s": {"m8_factures_emises": -5}}}),
                         encoding="utf-8")
    assert cadence_constats.cadence_par_defaut(["m8_factures_emises"])["fenetre_s"] == 86400
