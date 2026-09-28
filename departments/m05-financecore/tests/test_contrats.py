

from m5_financecore import contrats


def test_champs_mouvement_financier_constante_exacte():
    assert isinstance(contrats.CHAMPS_MOUVEMENT_FINANCIER, frozenset)
    assert frozenset(
        {
            "montant",
            "type_mouvement",
            "horodatage",
            "classe_retention",
            "source",
        }
    ) == contrats.CHAMPS_MOUVEMENT_FINANCIER


def test_types_mouvement_et_classes_retention_constantes():
    assert isinstance(contrats.TYPE_MOUVEMENT, tuple)
    assert set(contrats.TYPE_MOUVEMENT) == {
        "ENCAISSEMENT",
        "DECAISSEMENT",
        "PROVISION",
        "AJUSTEMENT",
        "AUTRE",
    }
    assert "AUTRE" in contrats.TYPE_MOUVEMENT

    assert isinstance(contrats.CLASSE_RETENTION, tuple)
    assert set(contrats.CLASSE_RETENTION) == {"FISCALE_6_ANS", "STANDARD"}

