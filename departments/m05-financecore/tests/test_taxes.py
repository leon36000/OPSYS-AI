import sys
from decimal import Decimal
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m5_financecore import taux_fiscaux, taxes

_CHEMIN_REEL = Path(__file__).resolve().parents[1] / "contracts" / "taux_fiscaux.v1.yaml"


def _dictionnaire_reel():
    dictionnaire, erreurs = taux_fiscaux.charger_taux_fiscaux(_CHEMIN_REEL)
    assert erreurs == []
    return dictionnaire


def test_calculer_taxes_tps_tvq_sur_le_fichier_versionne_reel():
    resultat, verdict = taxes.calculer_taxes(Decimal("100.00"), _dictionnaire_reel())

    assert verdict is None
    assert resultat["montant_avant_taxes"] == Decimal("100.00")
    assert [t["id"] for t in resultat["taxes"]] == ["tps_federale", "tvq_quebec"]
    assert resultat["taxes"][0]["montant"] == Decimal("5.00")
    assert resultat["taxes"][1]["montant"] == Decimal("9.98")
    assert resultat["total_taxes"] == Decimal("14.98")
    assert resultat["montant_apres_taxes"] == Decimal("114.98")
    assert all(type(t["montant"]) is Decimal for t in resultat["taxes"])
    assert type(resultat["total_taxes"]) is Decimal
    assert type(resultat["montant_apres_taxes"]) is Decimal


def test_calculer_taxes_reprend_la_version_du_taux_declare():
    resultat, verdict = taxes.calculer_taxes(Decimal("10.00"), _dictionnaire_reel())

    assert verdict is None
    assert resultat["taxes"][0]["version"] == "2026-v1"
    assert resultat["taxes"][1]["version"] == "2026-v1"


def test_calculer_taxes_bloque_sur_un_identifiant_de_taux_absent():
    resultat, verdict = taxes.calculer_taxes(
        Decimal("100.00"), _dictionnaire_reel(), ids_taux=("taxe_inexistante",)
    )

    assert resultat is None
    assert verdict["code"] == "REJ-TAUX-INCONNU"


def test_calculer_taxes_ne_calcule_rien_si_un_seul_taux_de_plusieurs_est_absent():
    """Fail-closed : si UN taux de la liste demandée est inconnu, aucun montant
    partiel n'est renvoyé (pas de facture à moitié taxée)."""
    resultat, verdict = taxes.calculer_taxes(
        Decimal("100.00"),
        _dictionnaire_reel(),
        ids_taux=("tps_federale", "taxe_inexistante"),
    )

    assert resultat is None
    assert verdict["code"] == "REJ-TAUX-INCONNU"


def test_calculer_taxes_rejette_un_montant_non_decimal():
    resultat, verdict = taxes.calculer_taxes(100.0, _dictionnaire_reel())

    assert resultat is None
    assert verdict["code"] == "REJ-MOUVEMENT-MONTANT-INVALIDE"


def test_calculer_taxes_rejette_un_montant_decimal_non_fini():
    resultat, verdict = taxes.calculer_taxes(Decimal("NaN"), _dictionnaire_reel())

    assert resultat is None
    assert verdict["code"] == "REJ-MOUVEMENT-MONTANT-INVALIDE"


def test_calculer_taxes_est_reproductible():
    dictionnaire = _dictionnaire_reel()

    premier, _ = taxes.calculer_taxes(Decimal("37.42"), dictionnaire)
    second, _ = taxes.calculer_taxes(Decimal("37.42"), dictionnaire)

    assert premier == second


def test_calculer_taxes_utilise_le_taux_lu_du_fichier_jamais_code_en_dur():
    """Un taux modifié dans la déclaration versionnée doit changer le résultat :
    preuve que le calcul lit bien `dictionnaire_taux`, pas une constante interne."""
    dictionnaire_modifie = {
        "tps_federale": {
            "id": "tps_federale",
            "nom": "Taxe fédérale (test)",
            "taux": 0.10,
            "version": "test-v9",
            "source": "fixture de test",
        },
    }

    resultat, verdict = taxes.calculer_taxes(
        Decimal("100.00"), dictionnaire_modifie, ids_taux=("tps_federale",)
    )

    assert verdict is None
    assert resultat["taxes"][0]["montant"] == Decimal("10.00")
    assert resultat["taxes"][0]["version"] == "test-v9"
