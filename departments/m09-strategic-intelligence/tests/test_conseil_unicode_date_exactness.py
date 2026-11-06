import pytest
from m9_strategic_intelligence import conseil


def _admettre(texte: str, date_citee: str | None = None) -> dict:
    affirmations = []
    sources = {}
    if date_citee is not None:
        affirmations.append(
            {
                "id": "s1",
                "nature": "observation_source",
                "reference": "r1",
                "valeur": date_citee,
            }
        )
        sources["r1"] = date_citee
    affirmations.append({"id": "h1", "nature": "hypothese", "enonce": texte})
    return conseil.admettre_proposition({"affirmations": affirmations}, sources=sources)


@pytest.mark.parametrize("separateur", ["-", "/", "\u2212", "\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\uff0f"])
def test_date_candidate_doit_etre_citee_litteralement(separateur):
    date = f"Date 2026{separateur}11{separateur}09"

    assert conseil.chiffres_libres(date, [date]) == []
    assert _admettre(date, date)["type"] == "PROPOSITION_ADMISE"
    assert conseil.chiffres_libres(date, []) == [date.removeprefix("Date ")]
    with pytest.raises(ValueError, match=conseil.CODE_CHIFFRE_LIBRE):
        _admettre(date)

    autre_date = f"Date 2026{separateur}11{separateur}10"
    assert conseil.chiffres_libres(autre_date, [date]) == [autre_date.removeprefix("Date ")]
    with pytest.raises(ValueError, match=conseil.CODE_CHIFFRE_LIBRE):
        _admettre(autre_date, date)


def test_orthographe_differente_de_date_ne_devient_pas_une_citation():
    source = "Date 2026\u201411\u201409"
    texte = "Date 2026-11-09"

    assert conseil.chiffres_libres(texte, [source]) == ["2026-11-09"]
    with pytest.raises(ValueError, match=conseil.CODE_CHIFFRE_LIBRE):
        _admettre(texte, source)


def test_entiers_nus_et_identifiants_conservent_le_comportement_historique():
    assert conseil.chiffres_libres("3 leads", []) == []
    assert conseil.chiffres_libres("M9.23", []) == []
    assert _admettre("La version v1.2.3 est disponible")["type"] == "PROPOSITION_ADMISE"
