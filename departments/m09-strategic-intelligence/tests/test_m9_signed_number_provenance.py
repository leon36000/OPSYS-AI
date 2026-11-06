from decimal import Decimal

import pytest
from m9_strategic_intelligence import conseil
from m9_strategic_intelligence import recommandation_gouvernee as rg


def test_chiffres_libres_distingue_le_signe_dans_les_deux_sens():
    assert conseil.chiffres_libres("Le solde est de 8 400,00 $", ["-8400.00"]) == ["8 400,00 $"]
    assert conseil.chiffres_libres("Le solde est de -8400.00 $", ["8400.00"]) == ["-8400.00 $"]
    assert conseil.chiffres_libres("Le solde est de -8400.00 $", ["-8400.00"]) == []
    assert conseil.chiffres_libres("Le taux est de -3.5 %", ["3.5 %"]) == ["-3.5 %"]
    assert conseil.chiffres_libres("Le taux est de +3.5 %", ["3.5 %"]) == []
    assert conseil._nombre("−8400.00") == Decimal("-8400.00")


@pytest.mark.parametrize(
    ("source", "enonce"),
    [
        ("-8400.00", "Le solde est de 8 400,00 $"),
        ("8400.00", "Le solde est de -8400.00 $"),
    ],
)
def test_admission_publique_refuse_une_reformulation_qui_inverse_le_signe(source, enonce):
    reference = "m5.faits#0:p0.resultat.solde"
    sortie = {
        "affirmations": [
            {"id": "A1", "nature": "observation_source", "reference": reference, "valeur": source},
            {"id": "H1", "nature": "hypothese", "enonce": enonce},
        ]
    }
    with pytest.raises(ValueError, match="REJ-CONSEIL-CHIFFRE-LIBRE"):
        conseil.admettre_proposition(sortie, sources={reference: source})


def test_tiret_separateur_date_et_identifiants_ne_deviennent_pas_des_signes():
    assert conseil.chiffres_libres("Total - 8 400,00 $", ["8400.00"]) == []
    assert conseil.chiffres_libres("Le 2026-11-09, voir lead-2 et option-8400.00", ["2026-11-09"]) == []


def test_nombres_libres_de_recommandation_distingue_le_signe_et_preserve_dates_identifiants():
    assert rg.nombres_libres("Solde 8 400,00 $", ["-8400.00"]) == ["8 400,00"]
    assert rg.nombres_libres("Solde -8400.00 $", ["8400.00"]) == ["-8400.00"]
    assert rg.nombres_libres("Solde -8400.00 $", ["-8400.00"]) == []
    assert rg.nombres_libres("Date 2026-11-09, options c1 et lead-2", ["2026-11-09"]) == []
    assert rg.nombres_libres("Total - 8 400,00 $", ["8400.00"]) == []
