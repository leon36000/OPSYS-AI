from decimal import Decimal, Inexact, Rounded, localcontext
from pathlib import Path

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


def test_calculer_taxes_est_independant_du_contexte_decimal_appelant():
    with localcontext() as contexte:
        contexte.prec = 2
        contexte.traps[Inexact] = True
        contexte.traps[Rounded] = True
        resultat, verdict = taxes.calculer_taxes(Decimal("100.00"), _dictionnaire_reel())

    assert verdict is None
    assert resultat["total_taxes"] == Decimal("14.98")
    assert resultat["montant_apres_taxes"] == Decimal("114.98")


def test_calculer_taxes_refuse_un_montant_fini_hors_du_domaine():
    resultat, verdict = taxes.calculer_taxes(Decimal("1e100"), _dictionnaire_reel())

    assert resultat is None
    assert verdict["code"] == "REJ-MOUVEMENT-MONTANT-INVALIDE"


def test_calculer_taxes_tps_arrondit_un_demi_cent_vers_le_haut():
    """4,50 $ x 5 % = 0,225 $ pile : un demi-cent exact. ROUND_HALF_UP (choisi ici) arrondit à
    0,23 $ ; le mode par défaut du module decimal (ROUND_HALF_EVEN) arrondirait à 0,22 $.

    Règle légale (source officielle, vérifiée par recherche web le 2026-09-28) : Agence du revenu
    du Canada, « Renseignements généraux sur la TPS/TVH pour les inscrits » (RC4022), section
    « Arrondir les montants fractionnaires » :
    « Arrondissez les montants de la TPS/TVH au cent près, de l'une des façons suivantes :
    Si le montant est inférieur à la moitié d'un cent, vous pouvez arrondir au cent inférieur.
    Si le montant est égal ou supérieur à la moitié d'un cent, arrondissez au cent supérieur. »
    https://www.canada.ca/fr/agence-revenu/services/formulaires-publications/publications/rc4022/renseignements-generaux-tps-tvh-inscrits.html#H2_221
    """
    resultat, verdict = taxes.calculer_taxes(
        Decimal("4.50"), _dictionnaire_reel(), ids_taux=("tps_federale",)
    )

    assert verdict is None
    assert resultat["taxes"][0]["montant"] == Decimal("0.23")
    # confirme le contraste : sans rounding= explicite, le module decimal arrondirait à 0.22
    assert Decimal("4.50") * Decimal("0.05") == Decimal("0.225")
    assert Decimal("0.225").quantize(Decimal("0.01")) == Decimal("0.22")


def test_calculer_taxes_tvq_arrondit_un_demi_cent_vers_le_haut():
    """60,00 $ x 9,975 % = 5,985 $ pile : un demi-cent exact. ROUND_HALF_UP (choisi ici) arrondit
    à 5,99 $ ; le mode par défaut du module decimal (ROUND_HALF_EVEN) arrondirait à 5,98 $.

    Règle légale (source officielle, vérifiée par recherche web le 2026-09-28) : Revenu Québec,
    « Calcul des taxes » :
    « Seules les fractions égales ou supérieures à 0,005 $ doivent être arrondies à 0,01 $. »
    https://www.revenuquebec.ca/fr/entreprises/taxes/tpstvh-et-tvq/perception-de-la-tps-et-de-la-tvq/calcul-des-taxes/
    """
    resultat, verdict = taxes.calculer_taxes(
        Decimal("60.00"), _dictionnaire_reel(), ids_taux=("tvq_quebec",)
    )

    assert verdict is None
    assert resultat["taxes"][0]["montant"] == Decimal("5.99")
    # confirme le contraste : sans rounding= explicite, le module decimal arrondirait à 5.98
    assert Decimal("60.00") * Decimal("0.09975") == Decimal("5.98500")
    assert Decimal("5.98500").quantize(Decimal("0.01")) == Decimal("5.98")


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
