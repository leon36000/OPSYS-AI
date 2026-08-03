import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m5_financecore import registre


HORODATAGE = "2026-08-03T12:00:00+00:00"


def _entree(suffix=""):
    return {
        "type_entree": "mouvement_enregistre",
        "horodatage": HORODATAGE,
        "valeur": suffix,
    }


def _mouvement(source="caisse-principale"):
    return {
        "montant": "125.00",
        "type_mouvement": "ENCAISSEMENT",
        "horodatage": HORODATAGE,
        "classe_retention": "STANDARD",
        "source": source,
    }


def test_type_entree_valide_est_present_dans_l_enumeration_privee():
    assert "mouvement_enregistre" in registre._TYPE_ENTREE_VALIDES


def test_ajouter_retourne_un_ligne_id_et_lire_retourne_le_maillon_complet():
    journal = registre.Registre()

    ligne_id = journal.ajouter(_entree())

    assert isinstance(ligne_id, str)
    assert ligne_id
    maillons = journal.lire()
    assert len(maillons) == 1
    assert maillons[0]["ligne_id"] == ligne_id
    assert maillons[0]["precedent_ligne_id"] is None
    assert maillons[0]["type_entree"] == "mouvement_enregistre"


def test_ajouter_protege_le_maillon_de_la_mutation_de_l_entree_originale():
    journal = registre.Registre()
    entree = _entree()
    journal.ajouter(entree)

    entree["valeur"] = "modifiee"
    entree["nouvelle_cle"] = True

    maillon = journal.lire()[0]
    assert maillon["valeur"] == ""
    assert "nouvelle_cle" not in maillon


def test_lire_retourne_des_copies_profondes():
    journal = registre.Registre()
    journal.ajouter(_entree())

    copie = journal.lire()
    copie[0]["valeur"] = "modifiee"

    assert journal.lire()[0]["valeur"] == ""


def test_tete_vaut_none_pour_un_registre_vide_puis_le_dernier_id():
    journal = registre.Registre()

    assert journal.tete() is None

    premier_id = journal.ajouter(_entree("premier"))
    second_id = journal.ajouter(_entree("second"))

    assert journal.tete() == second_id
    assert second_id != premier_id


def test_une_chaine_de_trois_maillons_est_valide():
    journal = registre.Registre()

    journal.ajouter(_entree("un"))
    journal.ajouter(_entree("deux"))
    journal.ajouter(_entree("trois"))

    assert journal.valider_chaine() == (True, "")


def test_type_entree_inconnu_leve_value_error():
    journal = registre.Registre()

    with pytest.raises(ValueError):
        journal.ajouter(
            {
                "type_entree": "type_inconnu",
                "horodatage": HORODATAGE,
            }
        )


def test_horodatage_absent_leve_une_erreur():
    journal = registre.Registre()

    with pytest.raises((KeyError, ValueError)):
        journal.ajouter({"type_entree": "mouvement_enregistre"})


@pytest.mark.parametrize(
    "horodatage",
    ["pas-une-date", "2026-08-03T12:00:00"],
)
def test_horodatage_invalide_ou_sans_fuseau_leve_value_error(horodatage):
    journal = registre.Registre()

    with pytest.raises(ValueError):
        journal.ajouter(
            {
                "type_entree": "mouvement_enregistre",
                "horodatage": horodatage,
            }
        )


def test_enregistrer_mouvement_chaine_deux_maillons_et_conserve_les_champs():
    journal = registre.Registre()
    mouvement = _mouvement()

    premier = registre.enregistrer_mouvement(mouvement, journal)
    second = registre.enregistrer_mouvement(mouvement, journal)

    assert premier["type_entree"] == "mouvement_enregistre"
    assert second["type_entree"] == "mouvement_enregistre"
    assert premier["ligne_id"] != second["ligne_id"]
    assert premier["precedent_ligne_id"] is None
    assert second["precedent_ligne_id"] == premier["ligne_id"]

    for champ, valeur in mouvement.items():
        assert premier[champ] == valeur
        assert second[champ] == valeur

    assert set(premier) == {
        "montant",
        "type_mouvement",
        "horodatage",
        "classe_retention",
        "source",
        "type_entree",
        "ligne_id",
        "precedent_ligne_id",
    }
    assert journal.lire() == [premier, second]
