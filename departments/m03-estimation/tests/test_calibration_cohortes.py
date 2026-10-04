"""Tests du contrat pur des cohortes; tous les faits sont fictifs et préparés."""

from __future__ import annotations

import copy
import sys
from decimal import ROUND_DOWN, ROUND_UP, Decimal, Inexact, getcontext, localcontext
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m3_estimation import calibration_cohortes  # noqa: E402

_COUPE = "2026-06-01T00:00:00Z"
_PROTOCOLE = "cohortes-r1"


def _observation(index: int, *, phase: str = "train", chantier: str | None = None, ecart: int = 5) -> dict:
    if phase == "train":
        debut = f"2026-05-{(index % 20) + 1:02d}T08:00:00Z"
        fin = f"2026-05-{(index % 20) + 1:02d}T10:00:00Z"
    else:
        debut = f"2026-06-{(index % 20) + 2:02d}T08:00:00Z"
        fin = f"2026-06-{(index % 20) + 2:02d}T10:00:00Z"
    return {
        "wct_id": f"wct-{index:04d}",
        "chantier_id": chantier or f"job-{index:04d}",
        "intervention_id": f"int-{index:04d}",
        "devis_id": f"quote-{index:04d}",
        "horodatage_debut": debut,
        "horodatage_completion": fin,
        "statut": "completed_verified",
        "duree_estimee_minutes": "100",
        "duree_reelle_minutes": 100 + ecart,
        "type_service": "gouttieres",
        "quantite": "25",
        "unite_quantite": "pi_lin",
        "taux_minutes_par_unite": "4",
        "bareme_version": "bar-2026-01",
        "preuve": {
            "m3_source_hash": f"{index + 1:064x}",
            "m4_wct_hash": f"{index + 1001:064x}",
            "liaison_exacte": True,
            "chaine_m3_valide": True,
            "schema_trace": 2,
            "semantique_trace": "duree_ecoulee_intervention",
            "semantique_reel": "duree_ecoulee_intervention",
            "unite_duree_estimee": "minute",
            "unite_duree_reelle": "minute",
        },
    }


def _cohorte(*, ecarts_train: list[int] | None = None) -> list[dict]:
    ecarts_train = ecarts_train or [5] * 20
    return [
        *[_observation(i, ecart=ecarts_train[i]) for i in range(20)],
        *[_observation(i + 20, phase="holdout", ecart=10) for i in range(10)],
    ]


def _rapport(observations: list[dict]) -> dict:
    return calibration_cohortes.construire_rapport(
        observations, coupure_utc=_COUPE, protocole_version=_PROTOCOLE
    )


def test_statistique_p80_est_le_quantile_de_l_erreur_absolue():
    lignes = [
        {"chantier_id": f"job-{i}", "estime": Decimal(200), "reel": Decimal(200 + erreur),
         "erreur": Decimal(erreur), "quantite": Decimal(1)}
        for i, erreur in enumerate((-100, 1, 2, 3, 4))
    ]
    stats = calibration_cohortes._stats(lignes)
    assert stats["erreur_minutes_p80"] == "3"
    assert stats["erreur_absolue_minutes_p80"] == "4"


def test_candidate_deterministe_inactive_et_avec_statistiques_robustes():
    observations = _cohorte(ecarts_train=[5] * 19 + [500])
    original = copy.deepcopy(observations)

    premier = _rapport(observations)
    second = _rapport(observations)

    assert premier == second
    assert premier["statut"] == "candidate"
    assert premier["candidate_active"] is False
    assert premier["segments"][0]["candidate_active"] is False
    assert premier["segments"][0]["ajustement_descriptif_train_minutes"] == "5"
    assert premier["segments"][0]["taux_minutes_par_unite_source"] == "4"
    assert premier["segments"][0]["taux_minutes_par_unite_candidat"] == "4.2"
    assert premier["segments"][0]["train"]["mad_erreur_minutes"] == "0"
    assert premier["segments"][0]["holdout_reference"]["erreur_absolue_minutes_mediane"] == "10"
    assert premier["segments"][0]["holdout_apres_candidate"]["erreur_absolue_minutes_mediane"] == "5"
    assert observations == original
    assert len(premier["rapport_sha256"]) == 64


def test_preinscription_train_only_ne_calcule_ni_ne_compte_le_holdout():
    observations = _cohorte()
    rapport = calibration_cohortes.construire_rapport(
        observations, coupure_utc=_COUPE, protocole_version=_PROTOCOLE, train_only=True,
    )
    assert rapport["statut"] == "candidate"
    assert rapport["compteurs"]["chantiers_holdout"] == 0
    assert rapport["compteurs"]["observations_holdout"] == 0
    assert rapport["compteurs"]["observations_recues"] == 20
    assert all(item["partition"] == "train" for item in rapport["provenance_observations"])
    assert rapport["segments"][0]["holdout_reference"] is None
    assert rapport["segments"][0]["holdout_apres_candidate"] is None

    contradiction = copy.deepcopy(observations[0])
    contradiction["horodatage_debut"] = "2026-06-02T08:00:00Z"
    contradiction["horodatage_completion"] = "2026-06-02T10:00:00Z"
    contradiction["chantier_id"] = "un-autre-chantier"
    refuse = calibration_cohortes.construire_rapport(
        [*observations, contradiction], coupure_utc=_COUPE,
        protocole_version=_PROTOCOLE, train_only=True,
    )
    assert refuse["statut"] == "refuse"
    assert refuse["raisons"] == ["wct_train_contradiction_connu"]


def test_coupure_exclut_tout_chantier_traversant_et_compte_le_retrait():
    observations = _cohorte()
    observations[0]["chantier_id"] = "job-overlap"
    observations[0]["horodatage_debut"] = "2026-05-31T23:00:00Z"
    observations[0]["horodatage_completion"] = "2026-06-01T01:00:00Z"
    observations[20]["chantier_id"] = "job-overlap"

    rapport = _rapport(observations)

    assert rapport["compteurs"]["chantiers_chevauchant_coupure"] == 1
    assert rapport["compteurs"]["observations_train"] == 19
    assert rapport["compteurs"]["observations_holdout"] == 9
    exclus = [ligne for ligne in rapport["exclusions"] if ligne.get("raisons") == ["chantier_chevauche_coupure"]]
    assert {ligne["wct_id"] for ligne in exclus} == {observations[0]["wct_id"], observations[20]["wct_id"]}
    assert rapport["statut"] == "insuffisant"


def test_rejeu_identique_compte_une_observation_et_conflit_refuse():
    observations = _cohorte()
    rapport = _rapport([*observations, copy.deepcopy(observations[0])])
    assert rapport["statut"] == "candidate"
    assert rapport["compteurs"]["rejeux_identiques"] == 1
    assert rapport["compteurs"]["observations_distinctes_valides"] == 30

    divergent = copy.deepcopy(observations[0])
    divergent["duree_reelle_minutes"] += 1
    conflit = _rapport([*observations, divergent])
    assert conflit["statut"] == "refuse"
    assert conflit["compteurs"]["conflits_rejeu"] == 1
    assert conflit["segments"] == []


@pytest.mark.parametrize(
    ("mutation", "raison"),
    [
        (lambda ligne: ligne["preuve"].update(semantique_trace="legacy"), "semantique_trace_non_qualifiee"),
        (lambda ligne: ligne["preuve"].update(unite_duree_reelle="heure"), "unite_duree_non_qualifiee"),
        (lambda ligne: ligne["preuve"].update(liaison_exacte=False), "liaison_exacte_non_prouvee"),
        (lambda ligne: ligne["preuve"].update(chaine_m3_valide=False), "chaine_m3_non_valide"),
    ],
)
def test_preuves_internes_et_unites_non_qualifiees_exclues(mutation, raison):
    observations = _cohorte()
    mutation(observations[0])
    rapport = _rapport(observations)

    assert rapport["compteurs"]["observations_train"] == 19
    assert rapport["statut"] == "insuffisant"
    assert raison in rapport["exclusions"][0]["raisons"]


def test_bool_float_dates_locales_et_decimaux_non_stricts_rejetes():
    observations = _cohorte()
    observations[0]["duree_reelle_minutes"] = True
    observations[1]["duree_estimee_minutes"] = 100.0
    observations[2]["quantite"] = "1e3"
    observations[3]["horodatage_debut"] = "2026-05-01T08:00:00-04:00"
    rapport = _rapport(observations)

    assert rapport["compteurs"]["observations_train"] == 16
    raisons = {raison for exclue in rapport["exclusions"] for raison in exclue["raisons"]}
    assert {
        "duree_reelle_type_invalide",
        "duree_estimee_type_invalide",
        "quantite_format_invalide",
        "horodatage_debut_utc_requis",
    } <= raisons
    assert rapport["statut"] == "insuffisant"


def test_minima_holdout_absent_ou_coupure_non_utc_ne_produisent_pas_de_candidate():
    trop_peu = _rapport(_cohorte()[:20])
    assert trop_peu["statut"] == "insuffisant"
    assert trop_peu["candidate_active"] is False
    invalide = calibration_cohortes.construire_rapport(
        _cohorte(), coupure_utc="2026-06-01T00:00:00-04:00", protocole_version=_PROTOCOLE
    )
    assert invalide == {"statut": "refuse", "raisons": ["coupure_utc_utc_requis"]}


def test_limite_observations_fail_closed():
    resultat = calibration_cohortes.construire_rapport(
        [{}] * 2001, coupure_utc=_COUPE, protocole_version=_PROTOCOLE
    )
    assert resultat["statut"] == "refuse"
    assert "limite_observations_depassee" in resultat["raisons"]


def test_quantite_exacte_separe_les_segments_et_provenance_reste_auditable():
    observations = _cohorte()
    for index, observation in enumerate(observations):
        observation["quantite"] = "25" if index % 2 == 0 else "26"
        observation["duree_estimee_minutes"] = str(int(observation["quantite"]) * 4)
        observation["duree_reelle_minutes"] = (
            int(observation["duree_estimee_minutes"]) + (5 if index < 20 else 10)
        )

    rapport = _rapport(observations)

    assert rapport["statut"] == "insuffisant"
    assert {segment["quantite_exacte"] for segment in rapport["segments"]} == {"25", "26"}
    assert all(segment["statut"] == "insuffisant" for segment in rapport["segments"])
    assert len(rapport["provenance_observations"]) == 30
    assert {ligne["partition"] for ligne in rapport["provenance_observations"]} == {"train", "holdout"}


def test_observation_invalide_avec_wct_deja_vu_invalide_le_conflit():
    observations = _cohorte()
    invalide = copy.deepcopy(observations[0])
    invalide["duree_reelle_minutes"] = True

    rapport = _rapport([*observations, invalide])

    assert rapport["statut"] == "refuse"
    assert rapport["compteurs"]["conflits_rejeu"] == 1
    assert observations[0]["wct_id"] not in {ligne["wct_id"] for ligne in rapport["provenance_observations"]}


def test_limite_chantiers_fail_closed():
    observations = [_observation(index) for index in range(501)]
    resultat = _rapport(observations)
    assert resultat["statut"] == "refuse"
    assert "limite_chantiers_depassee" in resultat["raisons"]


def test_resultat_independant_du_contexte_decimal_ambiant_et_appelant_inchange():
    observations = _cohorte()
    for index, observation in enumerate(observations):
        observation["quantite"] = "24"
        observation["duree_estimee_minutes"] = "96"
        observation["duree_reelle_minutes"] = 101 if index < 20 else 106

    reference = _rapport(observations)
    assert reference["segments"][0]["train"]["duree_reelle_minutes_mediane"] == "101"
    assert reference["segments"][0]["division_taux_non_exacte"] is True
    assert reference["arithmetique_decimal"]["divisions_taux_non_exactes"] is True
    assert "ne représente pas la précision terrain" in reference["arithmetique_decimal"]["note"]

    with localcontext() as contexte_appelant:
        contexte_appelant.prec = 2
        contexte_appelant.rounding = ROUND_DOWN
        contexte_appelant.traps[Inexact] = True
        contexte_appelant.clear_flags()
        avant = contexte_appelant.copy()
        sous_contexte_bas = _rapport(observations)
        courant = getcontext()
        assert courant.prec == avant.prec
        assert courant.rounding == avant.rounding
        assert courant.traps == avant.traps
        assert courant.flags == avant.flags

    with localcontext() as contexte_appelant:
        contexte_appelant.prec = 3
        contexte_appelant.rounding = ROUND_UP
        contexte_appelant.traps[Inexact] = True
        contexte_appelant.clear_flags()
        avant = contexte_appelant.copy()
        sous_autre_contexte = _rapport(observations)
        courant = getcontext()
        assert courant.prec == avant.prec
        assert courant.rounding == avant.rounding
        assert courant.traps == avant.traps
        assert courant.flags == avant.flags

    assert reference == sous_contexte_bas == sous_autre_contexte
