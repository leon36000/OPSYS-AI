import unicodedata
from decimal import Decimal

import pytest
from m9_strategic_intelligence import conseil
from m9_strategic_intelligence import recommandation_gouvernee as rg


@pytest.mark.parametrize("moins", ["\uff0d", "\ufe63"])
def test_moins_compatibilite_signe_sans_normaliser_tout_le_texte(moins):
    assert unicodedata.normalize("NFKC", moins) == "-"
    assert conseil._nombre(f"{moins}8400.00") == Decimal("-8400.00")
    assert conseil.chiffres_libres("Solde positif 8400.00 $", [f"{moins}8400.00"]) == ["8400.00 $"]
    assert rg.nombres_libres("Solde positif 8400.00 $", [f"{moins}8400.00"]) == ["8400.00"]
    assert conseil.chiffres_libres(f"Solde {moins}8400.00 $", [f"{moins}8400.00"]) == []
    assert rg.nombres_libres(f"Solde {moins}8400.00 $", [f"{moins}8400.00"]) == []


@pytest.mark.parametrize("moins", ["\uff0d", "\ufe63"])
def test_moins_unicode_avant_et_apres_dollar(moins):
    for source in (f"{moins}$8400.00", f"${moins}8400"):
        captures = list(conseil._MONTANT.finditer(source))
        assert len(captures) == 1
        assert captures[0].group(0) == source
        assert conseil._nombre(source) < 0
        assert conseil.chiffres_libres(f"Solde {source}", [source]) == []
        assert conseil.chiffres_libres("Solde positif 8400.00 $", [source]) == ["8400.00 $"]
        assert rg.nombres_libres(f"Solde {source}", [source]) == []
        assert rg.nombres_libres("Solde positif 8400.00 $", [source]) == ["8400.00"]


def test_tiret_typographique_reste_une_ponctuation_positive():
    texte = "Solde—8400.00 $"
    assert conseil.chiffres_libres(texte, ["-8400.00"]) == ["8400.00 $"]
    assert rg.nombres_libres(texte, ["-8400.00"]) == ["8400.00"]


def test_nfkc_modifierait_identifiant_et_date_mais_les_extracteurs_ne_normalisent_pas_le_texte():
    texte = "ID lead\uff0d2; date 2026-11-09"
    assert unicodedata.normalize("NFKC", texte) == "ID lead-2; date 2026-11-09"
    assert conseil.chiffres_libres(texte, ["2026-11-09"]) == []
    assert rg.nombres_libres(texte, ["2026-11-09"]) == []
    date_compat = "2026\uff0d11\ufe6309"
    assert unicodedata.normalize("NFKC", date_compat) == "2026-11-09"
    # La date de sortie diffère; elle est rapportée comme date entière, pas comme un chiffre partiel.
    assert rg.nombres_libres("Date 2026\uff0d11\uff0d10", [f"Date {date_compat}"]) == [
        "2026\uff0d11\uff0d10"
    ]
    assert rg.nombres_libres("Lot 1234", ["Lot 12\uff0d34"]) == ["1234"]


@pytest.mark.parametrize("source", ["perte: -8400.00", "CAD -8400.00"])
def test_recommandation_ne_normalise_pas_une_citation_composite_en_positif(source):
    assert rg.nombres_libres("Solde positif 8400.00 $", [source]) == ["8400.00"]
    assert rg.nombres_libres("Solde négatif -8400.00 $", [source]) == []


def test_valeur_atomique_negativement_citee_reste_autorisee():
    assert rg.nombres_libres("Solde négatif -8400.00 $", ["-8400.00"]) == []


@pytest.mark.parametrize(
    ("texte", "source", "valeur_libre"),
    [
        ("La mesure vaut 20261109", "Date de référence 2026-11-09", "20261109"),
        ("Le total est 1234", "Lot 12-34", "1234"),
    ],
)
def test_citation_composite_ne_concatene_pas_dates_ou_identifiants(texte, source, valeur_libre):
    assert rg.nombres_libres(texte, [source]) == [valeur_libre]


@pytest.mark.parametrize(
    ("source", "meme_valeur", "valeur_partielle"),
    [
        ("-$8,400.00", "-$8,400.00", "-8.40 $"),
        ("$-8,400.00", "$-8,400.00", "-8.40 $"),
        ("$8,400.00", "$8,400.00", "8.40 $"),
        ("8,400.00 $", "8,400.00 $", "8.40 $"),
    ],
)
def test_separateurs_mixtes_sont_entiers_et_n_autorisent_pas_un_prefixe(source, meme_valeur, valeur_partielle):
    captures = list(conseil._MONTANT.finditer(source))
    assert len(captures) == 1 and captures[0].group(0) == meme_valeur
    assert conseil.chiffres_libres(f"Solde {meme_valeur}", [source]) == []
    assert rg.nombres_libres(f"Solde {meme_valeur}", [source]) == []
    assert conseil.chiffres_libres(f"Solde {valeur_partielle}", [source]) == [valeur_partielle]
    assert rg.nombres_libres(f"Solde {valeur_partielle}", [source]) == [valeur_partielle.removesuffix(" $")]


@pytest.mark.parametrize("invalide", ["-$8,40.00", "-$8.400,00"])
def test_separateurs_mixtes_invalides_ne_fournissent_aucun_chiffre(invalide):
    assert list(conseil._MONTANT.finditer(invalide)) == []
    assert list(rg._NOMBRE_LIBRE.finditer(invalide)) == []
    assert conseil._nombre(invalide) is None
