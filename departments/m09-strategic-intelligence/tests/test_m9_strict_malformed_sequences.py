from decimal import Decimal

import pytest
from m9_strategic_intelligence import conseil
from m9_strategic_intelligence import recommandation_gouvernee as rg


def _recommandation(description: str, valeur_citee: str | list[str] = "Valeur déclarée") -> dict:
    valeurs = valeur_citee if isinstance(valeur_citee, list) else [valeur_citee]
    return {
        "schema": rg.SCHEMA,
        "question": "Que disent les données citées ?",
        "domaines": ["strategie"],
        "hypotheses": [
            {
                "id": f"h{index}",
                "enonce": "Valeur de contexte déclarée.",
                "source": "direction",
                "valeur": valeur,
                "declaree_par": "Direction fictive",
            }
            for index, valeur in enumerate(valeurs, 1)
        ],
        "chiffres": [],
        "options": [
            {"id": "o1", "titre": "Examiner", "description": description, "chiffres": [], "risques": []},
            {"id": "o2", "titre": "Attendre", "description": "Attendre une confirmation.",
             "chiffres": [], "risques": []},
        ],
        "risques": [],
        "donnees_manquantes": [],
        "recommandation": {
            "option_id": "o1",
            "texte": "Comparer les informations citées.",
            "abstention_raison": None,
        },
        "statut": rg.STATUT,
        "decision_prise_par_m9": False,
        "validation_requise": ["direction"],
        "mention_professionnelle": None,
    }


@pytest.mark.parametrize("texte,token", [("Le total est 1,2,3", "1,2,3"), ("Il y a 12.34.56 plaintes", "12.34.56")])
def test_recommandation_stricte_refuse_les_sequences_non_parseables(texte, token):
    assert rg.nombres_libres(texte, []) == [token]
    with pytest.raises(ValueError, match="CHIFFRE-LIBRE"):
        rg.controler(_recommandation(texte), faits={}, certitudes={})


@pytest.mark.parametrize(
    ("texte", "token", "fragments"),
    [
        ("Le total est 1，2，3", "1，2，3", ["1", "2", "3"]),
        ("Total 1，234", "1，234", ["1", "234"]),
        ("Total 12．34", "12．34", ["12", "34"]),
        ("Total 12٫34٫56", "12٫34٫56", ["12", "34", "56"]),
        ("Total 1٬234", "1٬234", ["1", "234"]),
        ("Total 1‧234", "1‧234", ["1", "234"]),
        ("Total 1 234", "1 234", ["1", "234"]),
    ],
)
def test_separateurs_numeriques_unicode_malformes_ne_sont_pas_des_fragments(texte, token, fragments):
    assert rg.nombres_libres(texte, fragments) == [token]
    with pytest.raises(ValueError, match="CHIFFRE-LIBRE"):
        rg.controler(_recommandation(texte, fragments), faits={}, certitudes={})
    # Le garde public du conseil refuse le token composite, sans traiter 3 leads comme un montant.
    assert conseil.chiffres_libres(texte, fragments) == [token]


@pytest.mark.parametrize("identifiant", ["v1.2.3", "M9.23", "mkt-A07", "lead-2"])
def test_versions_et_ids_attaches_ne_sont_pas_scannes_comme_nombres(identifiant):
    assert rg.nombres_libres(identifiant, []) == []


def test_contexte_exactement_cite_preserve_un_identifiant_a_separateurs():
    assert rg.nombres_libres("Version 1.2.3", ["Version 1.2.3"]) == []
    assert rg.nombres_libres("Version 1.2.3 est disponible", ["Version 1.2.3"]) == []
    assert rg.nombres_libres("Lot 12.34.56 reçu", ["Lot 12.34.56"]) == []
    assert rg.nombres_libres("ID: 7.8.9 identifié", ["ID: 7.8.9"]) == []
    assert rg.controler(
        _recommandation("Version 1.2.3 est disponible", "Version 1.2.3"), faits={}, certitudes={}
    )["valide"]
    assert rg.controler(_recommandation("Lot 12.34.56 reçu", "Lot 12.34.56"), faits={}, certitudes={})["valide"]
    # Une étiquette non identifiante ne transforme jamais une séquence libre en identifiant.
    assert rg.nombres_libres("Gain 1,2,3", ["Gain 1,2,3"]) == ["1,2,3"]
    with pytest.raises(ValueError, match="CHIFFRE-LIBRE"):
        rg.controler(_recommandation("Gain 1,2,3", "Gain 1,2,3"), faits={}, certitudes={})
    # Une séquence numérique nue malformée ne devient pas valide par une citation numérique partielle.
    assert rg.nombres_libres("1.2.3", ["1.2.3"]) == ["1.2.3"]
    assert rg.nombres_libres("Valeur 1.2.3", ["1.2.3"]) == ["1.2.3"]
    assert rg.nombres_libres("1,2,3", ["1,2,3"]) == ["1,2,3"]


@pytest.mark.parametrize("separateur", [
    "-", "/", "\uff0d", "\ufe63", "\u2212", "\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\uff0f",
])
def test_dates_compatibles_sont_comparees_exactement_sans_sourcer_leur_annee(separateur):
    date = f"2026{separateur}11{separateur}09"
    citee = f"Date {date}"
    assert rg.nombres_libres(citee, [citee]) == []
    assert rg.nombres_libres("Montant 2026", [citee]) == ["2026"]
    with pytest.raises(ValueError, match="CHIFFRE-LIBRE"):
        rg.controler(_recommandation("Montant 2026", citee), faits={}, certitudes={})
    autre_date = f"Date 2026{separateur}11{separateur}10"
    assert rg.nombres_libres(autre_date, [citee]) == [autre_date.removeprefix("Date ")]


def test_orthographe_de_date_n_est_pas_normalisee():
    assert rg.nombres_libres("Date 2026-11-09", ["Date 2026\u221211\u221209"]) == ["2026-11-09"]
    assert rg.nombres_libres("Date 2026/11/09", ["Date 2026\uff0f11\uff0f09"]) == ["2026/11/09"]


def test_multiples_groupes_de_trois_sans_decimales_sont_valides():
    assert conseil._nombre("$8,400,000") == Decimal(8400000)
    source = "$8,400,000"
    assert conseil.chiffres_libres(f"Gain {source}", [source]) == []
    assert rg.nombres_libres(f"Gain {source}", [source]) == []
    assert rg.nombres_libres("Gain $8400000", [source]) == []
    assert rg.nombres_libres("1,234,567", ["1,234,567"]) == []
    assert conseil._nombre("$8,400") is None
    assert rg.nombres_libres("Gain $8,400", ["Gain $8,400"]) == ["$8,400"]
