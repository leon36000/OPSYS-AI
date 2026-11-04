"""Ordre exact des instants ISO reçus par M10, sans altérer le texte d'origine."""

from m10_memoire import chronologie


def test_cle_exacte_compare_offsets_fractions_variables_et_instants_ex_aequo():
    ancien = "2026-09-15T10:00:00.12345610+01:00"
    recent = "2026-09-15T09:00:00.1234569Z"
    meme_instant_offset_different = "2026-09-15T10:00:00.100000+01:00"
    meme_instant_fraction_courte = "2026-09-15T09:00:00.1Z"

    assert chronologie.cle_instant(ancien) < chronologie.cle_instant(recent)
    assert chronologie.cle_instant(meme_instant_offset_different) == chronologie.cle_instant(
        meme_instant_fraction_courte
    )
    assert chronologie.cle_instant("2026-09-15X09:00:00.1Z") == chronologie.cle_instant(
        meme_instant_fraction_courte
    )
    assert chronologie.cle_instant("2026-09-15T09:00.1234567Z") == chronologie.cle_instant(
        "2026-09-15T09:00:00.1234567Z"
    )
    assert chronologie.cle_instant("2026-09-15T09.1234567Z") == chronologie.cle_instant(
        "2026-09-15T09:00:00.1234567Z"
    )
    lundi_semaine_iso = "2025-12-29T09:00:00.1234569+00:00"
    assert chronologie.cle_instant("2026-W01T09:00:00.1234569+00:00") == chronologie.cle_instant(lundi_semaine_iso)
    assert chronologie.cle_instant("2026W01T09:00:00.1234569+00:00") == chronologie.cle_instant(lundi_semaine_iso)
    assert chronologie.cle_instant("2026-W01T09:00:00.1234561+00:00") < chronologie.cle_instant(
        "2026-W01T09:00:00.1234569+00:00"
    )
    assert chronologie.cle_instant("2026W01T09:00:00.1234561+00:00") < chronologie.cle_instant(
        "2026W01T09:00:00.1234569+00:00"
    )


def test_cle_exacte_ne_borne_pas_les_chiffres_fractionnaires_et_normalise_le_report():
    prefixe = "2026-09-15T09:00:00."
    trente_chiffres = "123456789012345678901234567890"
    fraction_plus_petite = prefixe + trente_chiffres + "1Z"
    fraction_plus_grande = prefixe + trente_chiffres + "2Z"

    assert chronologie.cle_instant(fraction_plus_petite) < chronologie.cle_instant(fraction_plus_grande)
    # L'offset fractionnaire produit une fraction UTC négative : elle doit emprunter une seconde.
    assert chronologie.cle_instant("2026-09-15T09:00:30.1+00:00:30.2") == chronologie.cle_instant(
        "2026-09-15T08:59:59.9Z"
    )
    assert chronologie.cle_instant("2026-09-15T09:00+00:00:30.1") == chronologie.cle_instant(
        "2026-09-15T08:59:29.9Z"
    )
    assert chronologie.cle_instant("2026-09-15T09:00:00.1-00:00:30.2") == chronologie.cle_instant(
        "2026-09-15T09:00:30.3Z"
    )
    assert chronologie.cle_instant("2026-09-15T09:00:00.1000000+00:00:30.1234567") == chronologie.cle_instant(
        "2026-09-15T08:59:29.9765433Z"
    )
    assert chronologie.cle_instant("2026-09-15T09:00:00.1000000-00:00:30.1234567") == chronologie.cle_instant(
        "2026-09-15T09:00:30.2234567Z"
    )
    assert chronologie.cle_instant("2026-09-15T09:00:00.1000000+00:00:00.1234567") == chronologie.cle_instant(
        "2026-09-15T08:59:59.9765433Z"
    )
    assert chronologie.cle_instant("2026-09-15T09:00:00.1000000-00:00:00.1234567") == chronologie.cle_instant(
        "2026-09-15T09:00:00.2234567Z"
    )
