import hashlib
import json
from copy import deepcopy
from decimal import ROUND_DOWN, Inexact, localcontext

import pytest
from m5_financecore.cotisations_rrq_regulieres import calculer_cotisation_rrq_preparatoire


def entree(**modifications):
    valeur = {
        "annee": 2026,
        "date_paie": "2026-09-01",
        "juridiction": "QC",
        "frequence": "bihebdomadaire",
        "periode_annuelle": 19,
        "emploi_continu": True,
        "paiement_regulier_fixe": True,
        "gratif_ou_retroactif": False,
        "transfert_rpc_vers_rrq": False,
        "exemption_speciale": False,
        "assujettissement_qc": True,
        "pm": 12,
        "preuve_pm": {"id": "fixture-pm", "sha256": "a" * 64, "fictif": True},
        "salaire_rrq_periode": "4000.00",
        "salaire_rrq_cumul_avant": "72000.00",
        "rrq_palier1_cumul_avant": "4383.36",
        "rrq_palier2_cumul_avant": "0.00",
        "preuve_assiette": {"id": "fixture-assiette", "sha256": "b" * 64, "fictif": True},
        "preuve_cumuls": {"id": "fixture-cumuls", "sha256": "c" * 64, "fictif": True},
        "preuve_calendrier": {"id": "fixture-calendrier", "sha256": "d" * 64, "fictif": True},
    }
    valeur.update(modifications)
    return valeur


def _calcul(**modifications):
    return calculer_cotisation_rrq_preparatoire(**entree(**modifications))


def test_reproduit_bascule_officielle_periodes_19_et_20_et_csa_distincte():
    periode_19, refus = _calcul()
    assert refus is None
    assert periode_19["cotisation_palier1"] == "95.94"
    assert periode_19["cotisation_palier2"] == "56.00"
    assert periode_19["cotisation_rrq_totale"] == "151.94"
    assert periode_19["CSA"] == "71.23"

    periode_20, refus = _calcul(
        periode_annuelle=20,
        date_paie="2026-09-15",
        salaire_rrq_cumul_avant="76000.00",
        rrq_palier1_cumul_avant="4479.30",
        rrq_palier2_cumul_avant="56.00",
    )
    assert refus is None
    assert periode_20["cotisation_palier1"] == "0.00"
    assert periode_20["cotisation_palier2"] == "160.00"
    assert periode_20["CSA"] == "160.00"


def test_reproduit_le_point_de_controle_csa_officiel_annexe_1():
    rapport, refus = _calcul(
        periode_annuelle=1,
        date_paie="2026-01-15",
        salaire_rrq_cumul_avant="0.00",
        rrq_palier1_cumul_avant="0.00",
        rrq_palier2_cumul_avant="0.00",
    )
    assert refus is None
    assert rapport["cotisation_palier1"] == "243.52"
    assert rapport["cotisation_palier2"] == "0.00"
    assert rapport["CSA"] == "38.65"


@pytest.mark.parametrize(
    ("salaire", "attendu"),
    [("134.61", "0.00"), ("134.62", "0.01"), ("134.84", "0.01"), ("134.85", "0.02")],
)
def test_exemption_26_periodes_tronquee_et_minimum_dun_cent(salaire, attendu):
    rapport, refus = _calcul(
        periode_annuelle=1,
        date_paie="2026-01-15",
        salaire_rrq_periode=salaire,
        salaire_rrq_cumul_avant="0.00",
        rrq_palier1_cumul_avant="0.00",
        rrq_palier2_cumul_avant="0.00",
    )
    assert refus is None
    assert rapport["exemption_par_periode"] == "134.61"
    assert rapport["cotisation_palier1"] == attendu


def test_refuse_un_cumul_superieur_aux_plafonds_de_cotisation():
    for champ, valeur in [
        ("rrq_palier1_cumul_avant", "4479.31"),
        ("rrq_palier2_cumul_avant", "416.01"),
    ]:
        rapport, refus = _calcul(**{champ: valeur})
        assert rapport is None
        assert refus["code"] == "REJ-PAIE-ASSIETTE-INVALIDE"


@pytest.mark.parametrize(
    "modifications",
    [
        {"annee": 2025},
        {"annee": "2026"},
        {"date_paie": "2025-12-31"},
        {"date_paie": "2026-1-1"},
        {"periode_annuelle": 0},
        {"periode_annuelle": 27},
        {"periode_annuelle": True},
        {"frequence": "hebdomadaire"},
        {"juridiction": "ON"},
        {"emploi_continu": 1},
        {"paiement_regulier_fixe": "true"},
        {"gratif_ou_retroactif": True},
        {"transfert_rpc_vers_rrq": True},
        {"exemption_speciale": True},
        {"assujettissement_qc": False},
        {"pm": 11},
        {"pm": True},
        {"preuve_pm": None},
        {"salaire_rrq_periode": 4000.0},
        {"salaire_rrq_periode": True},
        {"salaire_rrq_periode": "NaN"},
        {"salaire_rrq_periode": "-0.01"},
        {"salaire_rrq_periode": "134.621"},
        {"salaire_rrq_periode": "1e3"},
        {
            "periode_annuelle": 1,
            "date_paie": "2026-01-15",
            "salaire_rrq_cumul_avant": "0.00",
            "rrq_palier1_cumul_avant": "0.01",
        },
        {"preuve_assiette": {"id": "fixture", "sha256": "A" * 64, "fictif": True}},
        {"preuve_cumuls": {"id": "fixture", "sha256": "c" * 64, "fictif": "true"}},
        {"preuve_calendrier": None},
        {"age": 30},
    ],
)
def test_refuse_hors_perimetre_types_invalides_ou_preuves_incompletes(modifications):
    rapport, refus = _calcul(**modifications)
    assert rapport is None
    assert refus is not None
    assert refus["code"].startswith("REJ-PAIE-")


def test_resultat_json_ne_promet_pas_authenticite_ni_paie_complete():
    rapport, refus = _calcul()
    assert refus is None
    assert rapport["mode"] == "PREPARATOIRE"
    assert rapport["statut"] == "NON_QUALIFIEE_POUR_PAIE"
    assert rapport["preuves"]["assiette"]["fictif"] is True
    assert rapport["preuve_authenticite"] == "NON_VERIFIEE"
    assert rapport["statut_ccq"] == "UNKNOWN"
    assert rapport["net"] is None
    assert rapport["DAS"] is None
    assert rapport["cout_employeur_global"] is None
    assert rapport["actions_bloquees"] is True
    assert isinstance(rapport["parametres"]["sha256"], str)
    assert len(rapport["parametres"]["sha256"]) == 64
    snapshot = rapport["parametres"]["snapshot"]
    canonical = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert hashlib.sha256(canonical).hexdigest() == rapport["parametres"]["sha256"]
    assert json.loads(json.dumps(rapport, allow_nan=False)) == rapport


def test_cumuls_non_nuls_avant_la_premiere_periode_sont_refuses():
    rapport, refus = _calcul(
        periode_annuelle=1,
        date_paie="2026-01-15",
        salaire_rrq_cumul_avant="0.01",
        rrq_palier1_cumul_avant="0.00",
        rrq_palier2_cumul_avant="0.00",
    )
    assert rapport is None
    assert refus["code"] == "REJ-PAIE-ASSIETTE-INVALIDE"


def test_calcul_et_contexte_decimal_sont_independants_des_parametres_ambiants():
    entrees = entree()
    original = deepcopy(entrees)
    with localcontext() as contexte:
        contexte.prec = 3
        contexte.rounding = ROUND_DOWN
        contexte.traps[Inexact] = True
        avant = contexte.copy()
        rapport, refus = calculer_cotisation_rrq_preparatoire(**entrees)
        assert contexte.prec == avant.prec
        assert contexte.rounding == avant.rounding
        assert contexte.traps == avant.traps
    assert refus is None
    assert rapport["cotisation_palier1"] == "95.94"
    assert rapport["CSA"] == "71.23"
    assert entrees == original


def test_calcul_ignore_les_bornes_emin_emax_et_clamp_ambiantes():
    entrees = entree()
    with localcontext() as contexte:
        contexte.prec = 2
        contexte.rounding = ROUND_DOWN
        contexte.Emin = -2
        contexte.Emax = 2
        contexte.clamp = 1
        contexte.traps[Inexact] = True
        avant = contexte.copy()
        rapport, refus = calculer_cotisation_rrq_preparatoire(**entrees)
        assert contexte.prec == avant.prec
        assert contexte.rounding == avant.rounding
        assert contexte.Emin == avant.Emin
        assert contexte.Emax == avant.Emax
        assert contexte.clamp == avant.clamp
        assert contexte.traps == avant.traps
        assert contexte.flags == avant.flags
    assert refus is None
    assert rapport["cotisation_palier1"] == "95.94"
    assert rapport["cotisation_palier2"] == "56.00"
    assert rapport["CSA"] == "71.23"
