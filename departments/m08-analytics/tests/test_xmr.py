import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m8_analytics import xmr


def test_detecter_signal_reste_silencieux_si_derniere_valeur_dans_les_limites():
    valeurs = [10.0, 10.0, 10.0, 10.0, 10.0]

    moyenne = sum(valeurs) / len(valeurs)
    amplitudes_mobiles = [
        abs(valeurs[index] - valeurs[index - 1])
        for index in range(1, len(valeurs))
    ]
    amplitude_moyenne = sum(amplitudes_mobiles) / len(amplitudes_mobiles)
    limite_naturelle_haute = moyenne + 2.66 * amplitude_moyenne
    limite_naturelle_basse = moyenne - 2.66 * amplitude_moyenne

    assert limite_naturelle_haute == 10.0
    assert limite_naturelle_basse == 10.0
    assert xmr.detecter_signal("m", valeurs, 3) is None


def test_detecter_signal_retourne_signal_limite_superieure_avec_limites_calculees():
    valeurs = [10.0, 10.0, 10.0, 10.0, 50.0]

    moyenne = sum(valeurs) / len(valeurs)
    amplitudes_mobiles = [
        abs(valeurs[index] - valeurs[index - 1])
        for index in range(1, len(valeurs))
    ]
    amplitude_moyenne = sum(amplitudes_mobiles) / len(amplitudes_mobiles)
    limite_naturelle_haute = moyenne + 2.66 * amplitude_moyenne
    limite_naturelle_basse = moyenne - 2.66 * amplitude_moyenne

    signal = xmr.detecter_signal("m", valeurs, 3)

    assert signal["metric_id"] == "m"
    assert signal["type_signal"] == "HORS_LIMITE_SUPERIEURE"
    assert signal["valeur_observee"] == 50.0
    assert signal["limite_naturelle_haute"] == limite_naturelle_haute
    assert signal["limite_naturelle_basse"] == limite_naturelle_basse
    assert signal["n"] == len(valeurs)


def test_detecter_signal_retourne_signal_limite_inferieure():
    valeurs = [10.0, 10.0, 10.0, 10.0, -30.0]

    moyenne = sum(valeurs) / len(valeurs)
    amplitudes_mobiles = [
        abs(valeurs[index] - valeurs[index - 1])
        for index in range(1, len(valeurs))
    ]
    amplitude_moyenne = sum(amplitudes_mobiles) / len(amplitudes_mobiles)
    limite_naturelle_haute = moyenne + 2.66 * amplitude_moyenne
    limite_naturelle_basse = moyenne - 2.66 * amplitude_moyenne

    signal = xmr.detecter_signal("m", valeurs, 3)

    assert valeurs[-1] < limite_naturelle_basse
    assert signal["type_signal"] == "HORS_LIMITE_INFERIEURE"
    assert signal["valeur_observee"] == -30.0
    assert signal["limite_naturelle_haute"] == limite_naturelle_haute
    assert signal["limite_naturelle_basse"] == limite_naturelle_basse


def test_detecter_signal_retourne_donnees_insuffisantes_avec_dict_complet():
    valeurs = [10.0, 20.0]

    assert xmr.detecter_signal("m", valeurs, 5) == {
        "metric_id": "m",
        "type_signal": "DONNEES_INSUFFISANTES",
        "valeur_observee": None,
        "limite_naturelle_haute": None,
        "limite_naturelle_basse": None,
        "n": 2,
    }


def test_detecter_signal_accepte_n_egal_a_n_minimal():
    valeurs = [10.0, 10.0, 10.0]

    moyenne = sum(valeurs) / len(valeurs)
    amplitudes_mobiles = [
        abs(valeurs[index] - valeurs[index - 1])
        for index in range(1, len(valeurs))
    ]
    amplitude_moyenne = sum(amplitudes_mobiles) / len(amplitudes_mobiles)
    limite_naturelle_haute = moyenne + 2.66 * amplitude_moyenne
    limite_naturelle_basse = moyenne - 2.66 * amplitude_moyenne

    assert limite_naturelle_basse <= valeurs[-1] <= limite_naturelle_haute
    assert xmr.detecter_signal("m", valeurs, 3) is None


def test_detecter_signal_ignore_les_points_intermediaires_hors_limites():
    valeurs = [10.0, 999.0, 10.0, 10.0, 10.0]

    moyenne = sum(valeurs) / len(valeurs)
    amplitudes_mobiles = [
        abs(valeurs[index] - valeurs[index - 1])
        for index in range(1, len(valeurs))
    ]
    amplitude_moyenne = sum(amplitudes_mobiles) / len(amplitudes_mobiles)
    limite_naturelle_haute = moyenne + 2.66 * amplitude_moyenne
    limite_naturelle_basse = moyenne - 2.66 * amplitude_moyenne

    assert limite_naturelle_basse <= valeurs[-1] <= limite_naturelle_haute
    assert xmr.detecter_signal("m", valeurs, 3) is None


def test_detecter_signal_ne_declenche_pas_si_derniere_valeur_egale_limite_haute():
    valeurs = [0.0, 0.0, 0.0, 67.5, 100.0]

    moyenne = sum(valeurs) / len(valeurs)
    amplitudes_mobiles = [
        abs(valeurs[index] - valeurs[index - 1])
        for index in range(1, len(valeurs))
    ]
    amplitude_moyenne = sum(amplitudes_mobiles) / len(amplitudes_mobiles)
    limite_naturelle_haute = moyenne + 2.66 * amplitude_moyenne
    limite_naturelle_basse = moyenne - 2.66 * amplitude_moyenne

    assert valeurs[-1] == limite_naturelle_haute
    assert valeurs[-1] >= limite_naturelle_basse
    assert xmr.detecter_signal("m", valeurs, 3) is None


def test_detecter_signal_historique_vide_ne_leve_pas_zero_division_error():
    """Cas limite : n_minimal <= 0 avec un historique vide.

    ``n < n_minimal`` est alors faux (0 < 0), le code tombait dans le calcul de
    moyenne et divisait par ``n == 0``. Zéro point d'historique est TOUJOURS
    insuffisant pour dériver une moyenne, quel que soit le ``n_minimal`` demandé.
    """
    assert xmr.detecter_signal("m", [], 0) == {
        "metric_id": "m",
        "type_signal": "DONNEES_INSUFFISANTES",
        "valeur_observee": None,
        "limite_naturelle_haute": None,
        "limite_naturelle_basse": None,
        "n": 0,
    }


def test_detecter_signal_historique_vide_avec_n_minimal_negatif_ne_leve_pas():
    assert xmr.detecter_signal("m", [], -1) == {
        "metric_id": "m",
        "type_signal": "DONNEES_INSUFFISANTES",
        "valeur_observee": None,
        "limite_naturelle_haute": None,
        "limite_naturelle_basse": None,
        "n": 0,
    }


def test_detecter_signal_utilise_n_minimal_fourni_par_appelant():
    valeurs = [10.0, 10.0, 50.0]

    resultat_insuffisant = xmr.detecter_signal("m", valeurs, 5)

    moyenne = sum(valeurs) / len(valeurs)
    amplitudes_mobiles = [
        abs(valeurs[index] - valeurs[index - 1])
        for index in range(1, len(valeurs))
    ]
    amplitude_moyenne = sum(amplitudes_mobiles) / len(amplitudes_mobiles)
    limite_naturelle_haute = moyenne + 2.66 * amplitude_moyenne
    limite_naturelle_basse = moyenne - 2.66 * amplitude_moyenne

    resultat_normal = xmr.detecter_signal("m", valeurs, 2)

    assert resultat_insuffisant == {
        "metric_id": "m",
        "type_signal": "DONNEES_INSUFFISANTES",
        "valeur_observee": None,
        "limite_naturelle_haute": None,
        "limite_naturelle_basse": None,
        "n": 3,
    }
    assert limite_naturelle_basse <= valeurs[-1] <= limite_naturelle_haute
    assert resultat_normal is None
