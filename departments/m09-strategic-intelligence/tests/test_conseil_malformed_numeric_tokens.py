import pytest
from m9_strategic_intelligence import conseil


def _sortie_hypothese(enonce: str, valeurs_citees: list[str] | None = None) -> dict:
    affirmations = [
        {
            "id": f"s{index}",
            "nature": "observation_source",
            "reference": f"r{index}",
            "valeur": valeur,
        }
        for index, valeur in enumerate(valeurs_citees or [], 1)
    ]
    affirmations.append({"id": "h1", "nature": "hypothese", "enonce": enonce})
    return {"affirmations": affirmations}


def _admettre(enonce: str, valeurs_citees: list[str] | None = None) -> dict:
    valeurs_citees = valeurs_citees or []
    sources = {f"r{index}": valeur for index, valeur in enumerate(valeurs_citees, 1)}
    return conseil.admettre_proposition(_sortie_hypothese(enonce, valeurs_citees), sources=sources)


@pytest.mark.parametrize(
    ("texte", "fragments"),
    [
        ("Gain 1,2,3", ["1", "2", "3"]),
        ("Total 1，234", ["1", "234"]),
        ("Total 12．34", ["12", "34"]),
        ("Total 12٫34٫56", ["12", "34", "56"]),
        ("Total 1٬234", ["1", "234"]),
        ("Total 1‧234", ["1", "234"]),
        ("Total 1 234", ["1", "234"]),
    ],
)
def test_admettre_proposition_refuse_sequences_malformees_meme_si_fragments_cites(texte, fragments):
    assert conseil.chiffres_libres(texte, fragments) == [texte.split(maxsplit=1)[-1]]
    with pytest.raises(ValueError, match=conseil.CODE_CHIFFRE_LIBRE):
        _admettre(texte, fragments)


def test_entier_nu_et_identifiants_attaches_restent_hors_du_garde_historique():
    assert conseil.chiffres_libres("3 leads", []) == []
    assert _admettre("3 leads")["type"] == "PROPOSITION_ADMISE"
    assert _admettre("La version v1.2.3 est disponible")["type"] == "PROPOSITION_ADMISE"
    assert _admettre("Le dossier M9.23 reste ouvert")["type"] == "PROPOSITION_ADMISE"


def test_identifiants_a_separateurs_exigent_label_et_citation_exacte():
    assert _admettre("Version 1.2.3 est disponible", ["Version 1.2.3"])["type"] == "PROPOSITION_ADMISE"
    assert _admettre("Lot 12.34.56 reçu", ["Lot 12.34.56"])["type"] == "PROPOSITION_ADMISE"
    with pytest.raises(ValueError, match=conseil.CODE_CHIFFRE_LIBRE):
        _admettre("Gain 1,2,3", ["Gain 1,2,3"])


def test_citation_numerique_exacte_est_preservee_sans_autoriser_ses_fragments():
    assert _admettre("La source indique 1,2,3", ["1,2,3"])["type"] == "PROPOSITION_ADMISE"
    with pytest.raises(ValueError, match=conseil.CODE_CHIFFRE_LIBRE):
        _admettre("La source indique 1,2,3", ["1", "2", "3"])


def test_dates_exactes_et_montants_valides_ne_sont_pas_requalifies():
    date = "2026-11-09"
    assert _admettre(f"Date de référence {date}", [date])["type"] == "PROPOSITION_ADMISE"
    assert conseil.chiffres_libres("Gain $12,345.67", ["$12,345.67"]) == []
