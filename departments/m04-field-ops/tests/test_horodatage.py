import m4_field_ops.horodatage as horodatage_mod
import pytest

HORODATAGES_VALIDES = [
    "2025-04-14T12:00:00+00:00",
    "2025-04-14 12:00:00+00:00",
    "2025-04-14T12:00:00-05:00",
]

HORODATAGES_INVALIDES = [
    "2025-04-14T12:00:00",
    None,
    42,
    [],
    "",
    "pas-une-date",
]


@pytest.mark.parametrize("texte", HORODATAGES_VALIDES)
def test_valider_horodatage_accepte_iso_avec_fuseau(texte):
    resultat = horodatage_mod.valider_horodatage(texte)
    assert resultat == texte
    assert resultat is texte


@pytest.mark.parametrize("valeur", HORODATAGES_INVALIDES)
def test_valider_horodatage_rejet_avec_code_rejet(valeur):
    with pytest.raises(ValueError) as exc_info:
        horodatage_mod.valider_horodatage(valeur)
    assert "REJ-HORODATAGE-INVALIDE" in str(exc_info.value)
    # __cause__ is None ne discrimine PAS le retrait de `from None` dans la
    # branche except (le chaînage implicite remplit __context__, pas __cause__ —
    # mutation mesurée non détectée). Le discriminant est __suppress_context__,
    # que SEUL `from None` positionne à True, dans les trois branches.
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__suppress_context__ is True


def test_valider_horodatage_rejet_sans_fuite_message_datetime():
    with pytest.raises(ValueError) as exc_info:
        horodatage_mod.valider_horodatage("pas-une-date")
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__suppress_context__ is True, (
        "sans `from None`, le message brut de datetime fuit dans le traceback"
    )
