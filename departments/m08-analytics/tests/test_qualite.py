import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m8_analytics import qualite  # noqa: E402


def test_evaluer_presence_n_zero_et_valeur_none_est_donnee_absente():
    resultat = qualite.evaluer_presence("m_cpl", 0, None)

    assert resultat == {"metric_id": "m_cpl", "verdict": qualite.VERDICT_DONNEE_ABSENTE, "n": 0}


def test_evaluer_presence_n_zero_mais_valeur_fournie_reste_absente_garde_defensive():
    """n == 0 déclenche l'absence même si `valeur` est incohéremment non None : la garde ne
    fait jamais confiance à une seule des deux moitiés du signal, comme xmr.py::detecter_signal
    avec n_minimal <= 0."""
    resultat = qualite.evaluer_presence("m_cpl", 0, 42.0)

    assert resultat["verdict"] == qualite.VERDICT_DONNEE_ABSENTE


def test_evaluer_presence_valeur_none_mais_n_positif_reste_absente_garde_defensive():
    resultat = qualite.evaluer_presence("m_cpl", 3, None)

    assert resultat["verdict"] == qualite.VERDICT_DONNEE_ABSENTE


def test_evaluer_presence_valeur_connue_ne_signale_rien():
    assert qualite.evaluer_presence("m_cpl", 1, 42.5) is None


def test_evaluer_fraicheur_sans_valeur_ne_double_signale_pas():
    """fraicheur_jours=None : evaluer_presence a déjà signalé l'absence, jamais un doublon."""
    assert qualite.evaluer_fraicheur("m_cpl", None, 2) is None


def test_evaluer_fraicheur_egale_au_seuil_nest_pas_perimee():
    """Limite inclusive : exactement au seuil n'est pas encore périmé, seul un dépassement
    STRICT l'est."""
    assert qualite.evaluer_fraicheur("m_cpl", 2.0, 2) is None


def test_evaluer_fraicheur_sous_le_seuil_ne_signale_rien():
    assert qualite.evaluer_fraicheur("m_cpl", 1.5, 2) is None


def test_evaluer_fraicheur_au_dela_du_seuil_est_perimee():
    resultat = qualite.evaluer_fraicheur("m_cpl", 5.0, 2)

    assert resultat == {
        "metric_id": "m_cpl",
        "verdict": qualite.VERDICT_DONNEE_PERIMEE,
        "fraicheur_jours": 5.0,
        "fraicheur_attendue_jours": 2,
    }


def test_evaluer_plage_sans_valeur_ne_double_signale_pas():
    assert qualite.evaluer_plage("m_cpl", None, 0, 10) is None


def test_evaluer_plage_sans_bornes_naccepte_aucune_contrainte():
    assert qualite.evaluer_plage("m_cpl", -999.0, None, None) is None


def test_evaluer_plage_dans_les_bornes_ne_signale_rien():
    assert qualite.evaluer_plage("m_cpl", 5.0, 0, 10) is None


def test_evaluer_plage_sur_les_bornes_incluses_ne_signale_rien():
    assert qualite.evaluer_plage("m_cpl", 0, 0, 10) is None
    assert qualite.evaluer_plage("m_cpl", 10, 0, 10) is None


def test_evaluer_plage_sous_la_borne_basse_est_hors_plage():
    resultat = qualite.evaluer_plage("m_cpl", -1.0, 0, 10)

    assert resultat == {
        "metric_id": "m_cpl",
        "verdict": qualite.VERDICT_HORS_PLAGE,
        "valeur": -1.0,
        "plage_min": 0,
        "plage_max": 10,
    }


def test_evaluer_plage_au_dessus_de_la_borne_haute_est_hors_plage():
    resultat = qualite.evaluer_plage("m_cpl", 11.0, 0, 10)

    assert resultat["verdict"] == qualite.VERDICT_HORS_PLAGE
    assert resultat["valeur"] == 11.0


def test_evaluer_plage_borne_basse_seule():
    """plage_max=None : seule la borne basse contraint, une valeur très grande passe."""
    assert qualite.evaluer_plage("m_cpl", 10_000.0, 0, None) is None
    assert qualite.evaluer_plage("m_cpl", -1.0, 0, None)["verdict"] == qualite.VERDICT_HORS_PLAGE


# ---------------------------------------------------------------------------
# T3.1-suite : unicité (doublons d'observation) et cohérence entre séries.
# ---------------------------------------------------------------------------


def test_evaluer_unicite_sans_horodatage_ne_signale_rien():
    assert qualite.evaluer_unicite("m_cpl", []) is None


def test_evaluer_unicite_horodatages_tous_distincts_ne_signale_rien():
    horodatages = ["2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z", "2026-01-03T00:00:00Z"]
    assert qualite.evaluer_unicite("m_cpl", horodatages) is None


def test_evaluer_unicite_horodatage_en_double_est_signale():
    resultat = qualite.evaluer_unicite(
        "m_cpl", ["2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z", "2026-01-01T00:00:00Z"]
    )

    assert resultat == {
        "metric_id": "m_cpl",
        "verdict": qualite.VERDICT_DOUBLON,
        "horodatages_doublons": {"2026-01-01T00:00:00Z": 2},
        "n_observations": 3,
    }


def test_evaluer_unicite_plusieurs_horodatages_en_double_sont_tous_rapportes():
    horodatages = [
        "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z",
        "2026-01-02T00:00:00Z", "2026-01-02T00:00:00Z", "2026-01-02T00:00:00Z",
        "2026-01-03T00:00:00Z",
    ]

    resultat = qualite.evaluer_unicite("m_cpl", horodatages)

    assert resultat["horodatages_doublons"] == {
        "2026-01-01T00:00:00Z": 2,
        "2026-01-02T00:00:00Z": 3,
    }
    assert resultat["n_observations"] == 6


def test_evaluer_coherence_dans_la_tolerance_ne_signale_rien():
    composantes = {
        "m5_revenu_cad": {"coefficient": 1.0, "valeur": 500.0},
        "m5_cout_cad": {"coefficient": -1.0, "valeur": 350.0},
    }
    assert qualite.evaluer_coherence("m5_marge_cad", 150.0, composantes, 0.01) is None


def test_evaluer_coherence_exactement_a_la_tolerance_ne_signale_rien():
    """Limite inclusive, même convention que evaluer_fraicheur : égal au seuil n'est pas encore
    une incohérence."""
    composantes = {"a": {"coefficient": 1.0, "valeur": 100.0}}
    assert qualite.evaluer_coherence("m", 105.0, composantes, 5.0) is None


def test_evaluer_coherence_hors_tolerance_est_signalee():
    composantes = {
        "m5_revenu_cad": {"coefficient": 1.0, "valeur": 500.0},
        "m5_cout_cad": {"coefficient": -1.0, "valeur": 350.0},
    }

    resultat = qualite.evaluer_coherence("m5_marge_cad", 100.0, composantes, 0.01)

    assert resultat == {
        "metric_id": "m5_marge_cad",
        "verdict": qualite.VERDICT_INCOHERENT,
        "valeur": 100.0,
        "valeur_attendue": 150.0,
        "ecart": -50.0,
        "tolerance": 0.01,
        "composantes": composantes,
    }


def test_evaluer_coherence_sans_composante_compare_a_zero():
    """composantes={} : la somme attendue est 0, un choix assumé de l'appelant."""
    resultat = qualite.evaluer_coherence("m", 10.0, {}, 0.0)

    assert resultat["valeur_attendue"] == 0.0
    assert resultat["ecart"] == 10.0


def test_evaluer_coherence_poids_positif_seul_verifie_une_simple_somme():
    composantes = {
        "a": {"coefficient": 1.0, "valeur": 10.0},
        "b": {"coefficient": 1.0, "valeur": 20.0},
        "c": {"coefficient": 1.0, "valeur": 30.0},
    }
    assert qualite.evaluer_coherence("total", 60.0, composantes, 0.0) is None
