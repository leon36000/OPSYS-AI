import sys
from decimal import Decimal
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m5_financecore import contrats, validation


def _mouvement(**surcharges):
    mouvement = {
        "montant": Decimal("150.00"),
        "type_mouvement": "ENCAISSEMENT",
        "horodatage": "2026-08-03T12:00:00+00:00",
        "classe_retention": "STANDARD",
        "source": "m4_field_ops:intervention:INT-042",
    }
    mouvement.update(surcharges)
    return mouvement


def test_catalogue_verdicts_m5_contient_les_codes_attendus():
    codes_attendus = {
        "REJ-MOUVEMENT-STRUCTURE-INVALIDE",
        "REJ-MOUVEMENT-MONTANT-INVALIDE",
        "REJ-MOUVEMENT-TYPE-INCONNU",
        "REJ-MOUVEMENT-CLASSE-RETENTION-INCONNUE",
    }
    assert codes_attendus.issubset(validation.CODES_M5_LIST)
    assert validation.CODES_M5 == set(validation.CODES_M5_LIST)


def test_construire_verdict_accepte_un_code_reconnu():
    code = "REJ-MOUVEMENT-STRUCTURE-INVALIDE"
    assert validation.est_verdict(code) is True
    assert validation.construire_verdict(code, "detail") == {
        "code": code,
        "detail": "detail",
    }


def test_construire_verdict_rejette_un_code_inconnu():
    code = "REJ-CODE-INEXISTANT"
    assert validation.est_verdict(code) is False
    with pytest.raises(validation.CodeVerdictInconnu):
        validation.construire_verdict(code)


def test_valider_mouvement_accepte_un_mouvement_valide():
    assert validation.valider_mouvement(_mouvement()) == (True, None)


def test_valider_mouvement_rejette_un_montant_float_binaire():
    valide, verdict = validation.valider_mouvement(_mouvement(montant=0.1))

    assert valide is False
    assert verdict["code"] == "REJ-MOUVEMENT-MONTANT-INVALIDE"


def test_valider_mouvement_rejette_un_montant_entier():
    valide, verdict = validation.valider_mouvement(_mouvement(montant=1))

    assert valide is False
    assert verdict["code"] == "REJ-MOUVEMENT-MONTANT-INVALIDE"


def test_valider_mouvement_accepte_le_type_autre():
    assert validation.valider_mouvement(
        _mouvement(type_mouvement="AUTRE")
    ) == (True, None)


def test_valider_mouvement_rejette_une_valeur_non_dict():
    valide, verdict = validation.valider_mouvement(None)
    assert valide is False
    assert verdict["code"] == "REJ-MOUVEMENT-STRUCTURE-INVALIDE"


def test_valider_mouvement_rejette_une_cle_manquante():
    mouvement = _mouvement()
    del mouvement["source"]

    valide, verdict = validation.valider_mouvement(mouvement)

    assert valide is False
    assert verdict["code"] == "REJ-MOUVEMENT-STRUCTURE-INVALIDE"


def test_valider_mouvement_rejette_une_cle_en_trop():
    mouvement = _mouvement(extra="valeur")

    valide, verdict = validation.valider_mouvement(mouvement)

    assert valide is False
    assert verdict["code"] == "REJ-MOUVEMENT-STRUCTURE-INVALIDE"


def test_valider_mouvement_rejette_un_montant_invalide():
    valide, verdict = validation.valider_mouvement(_mouvement(montant="150.0"))
    assert valide is False
    assert verdict["code"] == "REJ-MOUVEMENT-MONTANT-INVALIDE"


def test_valider_mouvement_rejette_un_montant_booleen():
    valide, verdict = validation.valider_mouvement(_mouvement(montant=True))
    assert valide is False
    assert verdict["code"] == "REJ-MOUVEMENT-MONTANT-INVALIDE"


def test_valider_mouvement_rejette_un_type_inconnu():
    valide, verdict = validation.valider_mouvement(
        _mouvement(type_mouvement="INCONNU")
    )
    assert valide is False
    assert verdict["code"] == "REJ-MOUVEMENT-TYPE-INCONNU"


def test_valider_mouvement_rejette_une_classe_retention_inconnue():
    valide, verdict = validation.valider_mouvement(
        _mouvement(classe_retention="INCONNUE")
    )
    assert valide is False
    assert verdict["code"] == "REJ-MOUVEMENT-CLASSE-RETENTION-INCONNUE"


def test_valider_mouvement_rejette_un_horodatage_non_chaine():
    valide, verdict = validation.valider_mouvement(_mouvement(horodatage=12345))
    assert valide is False
    assert verdict["code"] == "REJ-MOUVEMENT-CHAMP-TEXTE-INVALIDE"


def test_valider_mouvement_rejette_un_horodatage_vide():
    valide, verdict = validation.valider_mouvement(_mouvement(horodatage=""))
    assert valide is False
    assert verdict["code"] == "REJ-MOUVEMENT-CHAMP-TEXTE-INVALIDE"


def test_valider_mouvement_rejette_une_source_non_chaine():
    valide, verdict = validation.valider_mouvement(_mouvement(source=None))
    assert valide is False
    assert verdict["code"] == "REJ-MOUVEMENT-CHAMP-TEXTE-INVALIDE"


def test_valider_mouvement_rejette_une_source_vide():
    valide, verdict = validation.valider_mouvement(_mouvement(source=""))
    assert valide is False
    assert verdict["code"] == "REJ-MOUVEMENT-CHAMP-TEXTE-INVALIDE"


def test_valider_mouvement_rejette_montant_nan():
    valide, verdict = validation.valider_mouvement(_mouvement(montant=float("nan")))
    assert valide is False
    assert verdict["code"] == "REJ-MOUVEMENT-MONTANT-INVALIDE"


def test_valider_mouvement_rejette_montant_infini_positif():
    valide, verdict = validation.valider_mouvement(_mouvement(montant=float("inf")))
    assert valide is False
    assert verdict["code"] == "REJ-MOUVEMENT-MONTANT-INVALIDE"


def test_valider_mouvement_rejette_montant_infini_negatif():
    valide, verdict = validation.valider_mouvement(_mouvement(montant=float("-inf")))
    assert valide is False
    assert verdict["code"] == "REJ-MOUVEMENT-MONTANT-INVALIDE"


@pytest.mark.parametrize(
    "montant",
    [Decimal("NaN"), Decimal("sNaN"), Decimal("Infinity"), Decimal("-Infinity")],
)
def test_valider_mouvement_rejette_un_decimal_non_fini(montant):
    valide, verdict = validation.valider_mouvement(_mouvement(montant=montant))

    assert valide is False
    assert verdict["code"] == "REJ-MOUVEMENT-MONTANT-INVALIDE"
