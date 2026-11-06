import pytest
from m9_strategic_intelligence import conseil
from m9_strategic_intelligence import recommandation_gouvernee as rg


def _recommandation(description: str, valeur_citee: str) -> dict:
    return {
        "schema": rg.SCHEMA,
        "question": "Quel est le gain ?",
        "domaines": ["strategie"],
        "hypotheses": [
            {
                "id": "h1",
                "enonce": "Valeur déclarée à vérifier.",
                "source": "direction",
                "valeur": valeur_citee,
                "declaree_par": "Direction fictive",
            }
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
            "texte": "Comparer les valeurs déclarées.",
            "abstention_raison": None,
        },
        "statut": rg.STATUT,
        "decision_prise_par_m9": False,
        "validation_requise": ["direction"],
        "mention_professionnelle": None,
    }


def test_sortie_specialiste_refuse_les_tokens_monetaire_malformes():
    for valeur in ("Gain 1,2,3 $", "Gain $12.345.67"):
        expected = valeur.removeprefix("Gain ")
        assert conseil.chiffres_libres(valeur, []) == [expected]
        assert rg.nombres_libres(valeur, []) == [expected]
        sortie = {"affirmations": [{"id": "h1", "nature": "hypothese", "enonce": valeur}]}
        with pytest.raises(ValueError, match="CHIFFRE-LIBRE"):
            conseil.admettre_proposition(sortie, sources={})
        with pytest.raises(ValueError, match="CHIFFRE-LIBRE"):
            rg.controler(_recommandation(valeur, ""), faits={}, certitudes={})


@pytest.mark.parametrize(
    ("source", "fragment"),
    [
        ("Gain 1,2,3 $", "Gain 1.2 $"),
        ("Gain $12.345.67", "Gain $12.34"),
        ("$8,400", "Gain 8.40 $"),
        ("$ 0..738", "Le solde est 0 $"),
    ],
)
def test_source_malformee_ou_ambigue_n_autorise_pas_un_fragment(source, fragment):
    assert conseil.chiffres_libres(fragment, [source])
    assert rg.nombres_libres(fragment, [source])
    sortie = {
        "affirmations": [
            {"id": "s1", "nature": "observation_source", "reference": "r1", "valeur": source},
            {"id": "h1", "nature": "hypothese", "enonce": fragment},
        ]
    }
    with pytest.raises(ValueError, match="CHIFFRE-LIBRE"):
        conseil.admettre_proposition(sortie, sources={"r1": source})
    with pytest.raises(ValueError, match="CHIFFRE-LIBRE"):
        rg.controler(_recommandation(fragment, source), faits={}, certitudes={})


def test_montant_a_une_virgule_et_trois_chiffres_est_refuse_sans_locale():
    assert conseil._nombre("$8,400") is None
    assert conseil.chiffres_libres("Gain $8,400", ["Gain $8,400"])
    assert rg.nombres_libres("Gain $8,400", ["Gain $8,400"])
    assert conseil._nombre("$8,400.00") == conseil._nombre("$8400.00")
    assert conseil.chiffres_libres("Gain $8,400.00", ["Gain $8,400.00"]) == []
    assert rg.nombres_libres("Gain $8,400.00", ["Gain $8,400.00"]) == []


def test_date_compatibilite_est_traitee_comme_date_et_ne_source_pas_annee():
    date = "2026－11﹣09"
    assert conseil._DATE_COMPAT.findall(date) == [date]
    assert conseil.chiffres_libres(f"Date {date}", [f"Date {date}"]) == []
    assert rg.nombres_libres(f"Date {date}", [f"Date {date}"]) == []
    assert rg.nombres_libres("Montant 2026", [f"Date {date}"]) == ["2026"]
    with pytest.raises(ValueError, match="CHIFFRE-LIBRE"):
        rg.controler(_recommandation("Montant 2026", f"Date {date}"), faits={}, certitudes={})
    assert rg.controler(_recommandation(f"Date {date}", f"Date {date}"), faits={}, certitudes={})["valide"]


def test_dates_ascii_et_identifiants_exactement_cites_ne_sont_pas_malformes():
    texte = "Date 2026-11-09; lot 12-34"
    assert conseil._montants_malformes(texte) == []
    assert conseil.chiffres_libres(texte, ["Date 2026-11-09", "lot 12-34"]) == []
    assert rg.nombres_libres(texte, ["Date 2026-11-09", "lot 12-34"]) == []


def test_montants_valides_restent_comparables():
    montant = "$12,345.67"
    assert conseil._montants_malformes(montant) == []
    assert conseil.chiffres_libres(f"Gain {montant}", [montant]) == []
    assert rg.nombres_libres(f"Gain {montant}", [montant]) == []
