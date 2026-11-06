"""Régressions fictives C8 : précision XmR à grande échelle et à la frontière des limites."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
from fractions import Fraction

from m8_analytics import nombres, tendances

FICTIF = True
VERSION = "v1"
METRIC_ID = "m8_mesure_fictive"
MAINTENANT = datetime(2026, 10, 30, 9, 0, tzinfo=UTC)
ENTREE = {
    "metric_id": METRIC_ID,
    "nom": "Mesure fictive",
    "unite": "CAD",
    "proprietaire": "M5",
    "version_definition": VERSION,
    "fraicheur": {"fenetre_s": 86_400},
}


def _historique(valeurs):
    debut = datetime(2026, 10, 30, tzinfo=UTC)
    return [
        {
            "construction_id": f"construction-fictive-{i}",
            "metric_id": METRIC_ID,
            "construit_le": (debut + timedelta(hours=i)).isoformat(),
            "statut": "calculee",
            "couverture": {"etat": "complete"},
            "valeur": str(valeur),
            "version_definition": VERSION,
            "dernier_fait_le": (debut + timedelta(hours=i)).isoformat(),
        }
        for i, valeur in enumerate(valeurs)
    ]


def _limites_exactes(valeurs):
    rationnels = [Fraction(valeur) for valeur in valeurs]
    centre = sum(rationnels, Fraction(0)) / len(rationnels)
    amplitudes = [abs(rationnels[i] - rationnels[i - 1]) for i in range(1, len(rationnels))]
    amplitude_moyenne = sum(amplitudes, Fraction(0)) / len(amplitudes)
    delta = Fraction("2.66") * amplitude_moyenne
    return centre - delta, centre + delta


def test_xmr_ne_signale_pas_un_point_dans_la_limite_avec_une_resolution_de_1e_moins_50():
    base = Decimal("1000000000000000")
    valeurs = [
        base,
        base,
        Decimal("1000000000000000.0000000000000000000000000000000000000001"),
        base,
        base,
        base,
        base,
        Decimal("1000000000000000.0000000000000000000000000000000000000000000000000000000001"),
    ]
    assert all(len(str(valeur)) <= 80 and nombres.decimal_lu(valeur) is not None for valeur in valeurs)
    assert Fraction(valeurs[-1]) < _limites_exactes(valeurs)[1]

    resultat = tendances.analyser(_historique(valeurs), ENTREE, MAINTENANT)

    assert resultat["xmr"]["statut"] == "evalue"
    assert resultat["xmr"]["signal"] == "DANS_LES_LIMITES"


def test_xmr_inclut_exactement_un_point_egal_a_la_limite_naturelle():
    base = Decimal("1000000000000000")
    unite = Decimal("1e-50")
    with localcontext() as contexte:
        contexte.prec = 120
        valeurs = [base - 33 * unite, *([base] * 6), base + 17 * unite]

    assert all(len(str(valeur)) <= 80 and nombres.decimal_lu(valeur) is not None for valeur in valeurs)
    basse, haute = _limites_exactes(valeurs)
    assert Fraction(valeurs[-1]) == haute

    resultat = tendances.analyser(_historique(valeurs), ENTREE, MAINTENANT)

    assert resultat["xmr"]["statut"] == "evalue"
    assert resultat["xmr"]["signal"] == "DANS_LES_LIMITES"


def test_valeur_decimal_hors_borne_de_longueur_est_exclue_avant_calcul():
    valeur = Decimal("1000000000000000." + "0" * 100 + "1")

    assert tendances._valeur_lue(valeur) is None
