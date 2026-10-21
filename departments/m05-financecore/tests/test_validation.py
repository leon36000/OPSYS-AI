from decimal import Decimal

import pytest
from m5_financecore import validation


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
    assert set(validation.CODES_M5_LIST) == validation.CODES_M5


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


# Bug NEW-PROD : soldes.py ne contrôlait aucun signe — un DECAISSEMENT de +100
# donnait un solde de +100 au lieu de le diminuer. Le signe doit être cohérent
# avec le type_mouvement, imposé au point d'entrée unique de toute écriture.


def test_valider_mouvement_rejette_un_decaissement_au_montant_positif():
    valide, verdict = validation.valider_mouvement(
        _mouvement(type_mouvement="DECAISSEMENT", montant=Decimal("100.00"))
    )

    assert valide is False
    assert verdict["code"] == "REJ-MOUVEMENT-SIGNE-INCOHERENT"


def test_valider_mouvement_rejette_un_decaissement_au_montant_nul():
    valide, verdict = validation.valider_mouvement(
        _mouvement(type_mouvement="DECAISSEMENT", montant=Decimal("0.00"))
    )

    assert valide is False
    assert verdict["code"] == "REJ-MOUVEMENT-SIGNE-INCOHERENT"


def test_valider_mouvement_accepte_un_decaissement_au_montant_negatif():
    assert validation.valider_mouvement(
        _mouvement(type_mouvement="DECAISSEMENT", montant=Decimal("-100.00"))
    ) == (True, None)


def test_valider_mouvement_rejette_un_encaissement_au_montant_negatif():
    valide, verdict = validation.valider_mouvement(
        _mouvement(type_mouvement="ENCAISSEMENT", montant=Decimal("-50.00"))
    )

    assert valide is False
    assert verdict["code"] == "REJ-MOUVEMENT-SIGNE-INCOHERENT"


def test_valider_mouvement_rejette_une_provision_au_montant_negatif():
    valide, verdict = validation.valider_mouvement(
        _mouvement(type_mouvement="PROVISION", montant=Decimal("-20.00"))
    )

    assert valide is False
    assert verdict["code"] == "REJ-MOUVEMENT-SIGNE-INCOHERENT"


def test_valider_mouvement_accepte_un_ajustement_negatif_ou_positif():
    assert validation.valider_mouvement(
        _mouvement(type_mouvement="AJUSTEMENT", montant=Decimal("-10.00"))
    ) == (True, None)
    assert validation.valider_mouvement(
        _mouvement(type_mouvement="AJUSTEMENT", montant=Decimal("10.00"))
    ) == (True, None)


def test_valider_mouvement_accepte_autre_negatif_ou_positif():
    assert validation.valider_mouvement(
        _mouvement(type_mouvement="AUTRE", montant=Decimal("-5.00"))
    ) == (True, None)
    assert validation.valider_mouvement(
        _mouvement(type_mouvement="AUTRE", montant=Decimal("5.00"))
    ) == (True, None)
