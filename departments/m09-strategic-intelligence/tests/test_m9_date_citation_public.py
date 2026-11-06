import pytest
from m9_strategic_intelligence import recommandation_gouvernee as rg


def _recommandation(description: str, valeur_citee: str) -> dict:
    return {
        "schema": rg.SCHEMA,
        "question": "Quel est le solde ?",
        "domaines": ["strategie"],
        "hypotheses": [
            {
                "id": "h-date",
                "enonce": "Date de référence déclarée.",
                "source": "direction",
                "valeur": valeur_citee,
                "declaree_par": "Direction fictive",
            }
        ],
        "chiffres": [],
        "options": [
            {"id": "o-1", "titre": "Examiner", "description": description, "chiffres": [], "risques": []},
            {"id": "o-2", "titre": "Attendre", "description": "Attendre une confirmation.",
             "chiffres": [], "risques": []},
        ],
        "risques": [],
        "donnees_manquantes": [],
        "recommandation": {
            "option_id": "o-1",
            "texte": "Comparer les éléments déclarés.",
            "abstention_raison": None,
        },
        "statut": rg.STATUT,
        "decision_prise_par_m9": False,
        "validation_requise": ["direction"],
        "mention_professionnelle": None,
    }


def _controler(reco: dict) -> dict:
    return rg.controler(reco, faits={}, certitudes={})


def test_annee_d_une_date_citee_ne_source_pas_un_montant_distinct():
    reco = _recommandation("Le solde est 2026.", "Date 2026-11-09")
    with pytest.raises(ValueError, match="CHIFFRE-LIBRE"):
        _controler(reco)


def test_date_iso_citee_reste_comparable_en_texte_exact():
    reco = _recommandation("La date de référence est 2026-11-09.", "Date 2026-11-09")
    assert _controler(reco)["valide"] is True


def test_valeur_numerique_atomique_citee_continue_de_sourcer_un_chiffre():
    reco = _recommandation("Le solde est 2026.", "2026")
    assert _controler(reco)["valide"] is True
