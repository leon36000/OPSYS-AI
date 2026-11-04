"""C5 : le constat de trésorerie prévue que M5 publie (module pur `constat_tresorerie_prevue`).

Tests ROUGES avant le code : le module n'existe pas encore. Le constat reprend la prévision
(`prevision.assembler`, flux connus et datés) sous la forme fermée de
`m5.tresorerie_prevue_constatee` : solde minimal prévu et sa semaine, semaines sous le seuil,
série hebdomadaire pour le prévu-contre-réel de M8, instant d'émission. Aucun montant n'est
recalculé ici.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

from m5_financecore import constat_tresorerie_prevue as ctp

FICTIF = True
D = Decimal
JOUR = date(2026, 9, 29)
EMISE_LE = "2026-09-29T07:00:00-04:00"


def _resultat(
    soldes=(("CALCULE", "19885.02"), ("CALCULE", "15685.02"), ("CALCULE", "18013.46")),
    seuil="16000.00",
    statut_alerte="ALERTE",
    semaines_alerte=(2,),
):
    semaines = [
        {"semaine": k + 1, "statut": statut, "solde_fin": D(montant) if montant is not None else None}
        for k, (statut, montant) in enumerate(soldes)
    ]
    return {
        "horizon_semaines": len(soldes),
        "calculable": all(s["statut"] == "CALCULE" for s in semaines),
        "non_calculable_a_partir_de": None,
        "semaines": semaines,
        "alerte": {
            "statut": statut_alerte,
            "seuil": D(seuil) if seuil is not None else None,
            "semaines": list(semaines_alerte),
        },
        "manque": [],
        "prevision_id": "b" * 64,
    }


def _charge(resultat=None, jour=JOUR, sequence=1):
    return ctp.charge_evenement(_resultat() if resultat is None else resultat, jour, sequence, EMISE_LE)


def test_la_charge_reprend_le_solde_minimal_et_sa_semaine():
    charge = _charge()
    assert charge["solde_minimal_prevu_cad"] == "15685.02"
    assert charge["semaine_solde_minimal"] == 2
    assert charge["semaines_sous_seuil"] == [2]
    assert charge["statut_alerte"] == "ALERTE"
    assert charge["seuil_cad"] == "16000.00"
    assert charge["emise_le"] == EMISE_LE and charge["horizon_semaines"] == 3


def test_la_charge_dit_chaque_semaine_pour_le_prevu_contre_reel():
    charge = _charge()
    assert [(s["semaine"], s["statut"], s["solde_fin_cad"]) for s in charge["soldes_hebdo"]] == [
        (1, "CALCULE", "19885.02"), (2, "CALCULE", "15685.02"), (3, "CALCULE", "18013.46"),
    ]


def test_l_identifiant_est_deterministe_par_rang_jour_et_version():
    resultat = _resultat()
    assert ctp.identifiant(JOUR, 1, resultat["prevision_id"]) == _charge(resultat)["evenement_id"]
    assert ctp.identifiant(JOUR, 1, resultat["prevision_id"]) != ctp.identifiant(JOUR, 2, resultat["prevision_id"])
    assert ctp.identifiant(JOUR, 1, resultat["prevision_id"]).startswith("m5-tresorerie-prevue-1-2026-09-29-")


def test_une_prevision_non_calculable_ne_porte_aucun_chiffre_apres_le_blocage():
    resultat = _resultat(
        soldes=(("CALCULE", "19885.02"), ("NON_CALCULABLE", None), ("NON_CALCULABLE", None)),
        statut_alerte="NON_EVALUEE", semaines_alerte=(),
    )
    resultat["calculable"] = False
    resultat["non_calculable_a_partir_de"] = 2
    resultat["manque"] = [{
        "code": "REJ-PREVISION-DELAI-CLIENTS-A-DECLARER", "a_partir_de_semaine": 2, "flux": ["F-1"],
        "detail": "délai à déclarer",
    }]
    charge = _charge(resultat)
    assert charge["solde_minimal_prevu_cad"] == "19885.02"
    assert charge["semaine_solde_minimal"] == 1
    assert charge["non_calculable_a_partir_de"] == 2
    assert charge["manque"] == [{"code": "REJ-PREVISION-DELAI-CLIENTS-A-DECLARER", "a_partir_de_semaine": 2}]
    assert charge["soldes_hebdo"][1] == {"semaine": 2, "statut": "NON_CALCULABLE", "solde_fin_cad": None}


def test_aucune_semaine_calculee_le_minimal_est_nul_pas_zero():
    resultat = _resultat(soldes=(("NON_CALCULABLE", None),), statut_alerte="NON_EVALUEE", semaines_alerte=())
    resultat["calculable"] = False
    resultat["non_calculable_a_partir_de"] = 1
    resultat["manque"] = [{
        "code": "REJ-PREVISION-DELAI-CLIENTS-A-DECLARER", "a_partir_de_semaine": 1, "flux": ["F-1"],
        "detail": "délai à déclarer",
    }]
    charge = _charge(resultat)
    assert charge["solde_minimal_prevu_cad"] is None
    assert charge["semaine_solde_minimal"] is None


def test_seuil_a_configurer_le_seuil_est_nul_et_le_dit():
    charge = _charge(_resultat(seuil=None, statut_alerte="SEUIL_A_CONFIGURER", semaines_alerte=()))
    assert charge["statut_alerte"] == "SEUIL_A_CONFIGURER"
    assert charge["seuil_cad"] is None and charge["semaines_sous_seuil"] == []


def test_l_entete_planifie_ne_porte_aucun_montant():
    entete = ctp.entete(_charge())
    texte = json.dumps(entete, ensure_ascii=False)
    for interdit in ("19885.02", "15685.02", "18013.46", "16000.00"):
        assert interdit not in texte
    assert entete["statut_alerte"] == "ALERTE"


def test_le_resume_a_la_demande_porte_les_montants_publies():
    resume = ctp.resume(_charge())
    assert resume["solde_minimal_prevu_cad"] == "15685.02" and resume["sequence"] == 1


def test_la_trace_ne_garde_que_l_en_tete():
    trace = ctp.construire_trace(_charge())
    assert trace["type_entree"] == "tresorerie_prevue_constatee" and trace["sequence"] == 1
    texte = json.dumps(trace, ensure_ascii=False)
    for interdit in ("19885.02", "15685.02", "16000.00"):
        assert interdit not in texte


def test_lire_jour_refuse_un_jour_invalide_sans_le_corriger():
    jour, verdict = ctp.lire_jour("2026-13-40")
    assert jour is None and verdict["code"] == "REJ-CONSTAT-DATE-INVALIDE"
    assert ctp.lire_jour("2026-09-29")[0] == JOUR
    # `and` et pas `or` : un entier et une date imaginaire sont tous deux refusés sans deviner.
    assert ctp.lire_jour(20260929)[1]["code"] == "REJ-CONSTAT-DATE-INVALIDE"
    assert ctp.lire_jour("2026-02-30")[1]["code"] == "REJ-CONSTAT-DATE-INVALIDE"


def test_lire_emission_refuse_un_instant_invalide_sans_le_corriger():
    instant, verdict = ctp.lire_emission("2026-09-29 07h00")
    assert instant is None and verdict["code"] == "REJ-CONSTAT-EMISSION-INVALIDE"
    assert ctp.lire_emission(EMISE_LE)[0] == EMISE_LE


def test_lire_emission_refuse_un_jour_ou_une_heure_imaginaire():
    for impossible in ("2026-02-30T25:99:99+99:99", "2026-02-30T07:00:00-04:00",
                       "2026-09-29T25:00:00-04:00", "2026-09-29T07:99:00-04:00",
                       "2026-09-29T07:00:99-04:00", "2026-09-29T07:00:00+99:99"):
        instant, verdict = ctp.lire_emission(impossible)
        assert instant is None and verdict is not None, impossible
        assert verdict["code"] == "REJ-CONSTAT-EMISSION-INVALIDE", impossible


def test_le_catalogue_refuse_une_emission_imaginaire_et_une_serie_incoherente():
    from opsys.evenements.schemas import erreurs_charge

    assert erreurs_charge(ctp.TYPE_EVENEMENT_TRESORERIE_PREVUE, _charge()) == []

    emission = _charge()
    emission["emise_le"] = "2026-02-30T25:99:99+99:99"
    assert erreurs_charge(ctp.TYPE_EVENEMENT_TRESORERIE_PREVUE, emission) != []

    non_calculable_avec_montant = _charge()
    non_calculable_avec_montant["soldes_hebdo"][1]["statut"] = "NON_CALCULABLE"
    assert erreurs_charge(ctp.TYPE_EVENEMENT_TRESORERIE_PREVUE, non_calculable_avec_montant) != []

    calcule_sans_montant = _charge()
    calcule_sans_montant["soldes_hebdo"][1]["solde_fin_cad"] = None
    assert erreurs_charge(ctp.TYPE_EVENEMENT_TRESORERIE_PREVUE, calcule_sans_montant) != []

    doublon = _charge()
    doublon["semaines_sous_seuil"] = [2, 2]
    assert erreurs_charge(ctp.TYPE_EVENEMENT_TRESORERIE_PREVUE, doublon) != []

    alerte_sans_semaine = _charge()
    alerte_sans_semaine["semaines_sous_seuil"] = []
    assert erreurs_charge(ctp.TYPE_EVENEMENT_TRESORERIE_PREVUE, alerte_sans_semaine) != []


def test_lire_emission_refuse_un_non_texte_sans_lever():
    # Tue le mutant `isinstance(brut, str) and fullmatch` -> `or` (le motif lèverait TypeError sur un entier).
    for brut in (20261104, None, 1.5, ["2026-11-04T07:00:00-05:00"], b"2026-11-04T07:00:00-05:00"):
        instant, verdict = ctp.lire_emission(brut)
        assert instant is None and verdict["code"] == ctp._CODE_EMISSION_INVALIDE
