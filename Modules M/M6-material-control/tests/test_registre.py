import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import re

from m6_material_control.registre import Registre


_CLES_MAILLON = {
    "index",
    "type_mouvement",
    "chantier_id",
    "materiau_id",
    "quantite",
    "cout_unitaire",
    "hash_precedent",
    "hash_maillon",
}


def _reception():
    return {
        "type_mouvement": "RECEPTION",
        "chantier_id": "chantier-A",
        "materiau_id": "beton-C25",
        "quantite": 12.5,
        "cout_unitaire": 110.0,
    }


def _consommation():
    return {
        "type_mouvement": "CONSOMMATION",
        "chantier_id": "chantier-A",
        "materiau_id": "beton-C25",
        "quantite": -3.0,
        "cout_unitaire": 110.0,
    }


def _variance():
    return {
        "type_mouvement": "VARIANCE_INVENTAIRE",
        "chantier_id": "chantier-A",
        "materiau_id": "beton-C25",
        "quantite": -0.5,
        "cout_unitaire": None,
    }


def test_ajouter_premier_maillon_utilise_hash_precedent_vide_et_index_zero():
    registre = Registre()

    maillon, erreur = registre.ajouter(_reception())

    assert erreur is None
    assert maillon["index"] == 0
    assert maillon["hash_precedent"] == ""
    assert re.fullmatch(r"[0-9a-f]{64}", maillon["hash_maillon"])


def test_ajouter_deuxieme_maillon_chaine_le_hash_precedent_et_l_index():
    registre = Registre()
    premier, erreur_premier = registre.ajouter(_reception())
    second, erreur_second = registre.ajouter(_consommation())

    assert erreur_premier is None
    assert erreur_second is None
    assert second["index"] == 1
    assert second["hash_precedent"] == premier["hash_maillon"]


def test_lire_retourne_deux_maillons_aux_huit_cles_exactes():
    registre = Registre()
    registre.ajouter(_reception())
    registre.ajouter(_consommation())

    maillons = registre.lire()

    assert len(maillons) == 2
    assert set(maillons[0]) == _CLES_MAILLON
    assert set(maillons[1]) == _CLES_MAILLON


def test_valider_chaine_accepte_une_chaine_intacte_de_deux_maillons():
    registre = Registre()
    registre.ajouter(_reception())
    registre.ajouter(_consommation())

    assert registre.valider_chaine() == (True, "")


def test_lire_retourne_une_copie_isolee_des_maillons_internes():
    registre = Registre()
    registre.ajouter(_reception())
    registre.ajouter(_consommation())

    resultat = registre.lire()
    resultat[0]["quantite"] = 999.0

    assert registre.valider_chaine() == (True, "")


def test_valider_chaine_detecte_l_alteration_directe_du_premier_maillon():
    registre = Registre()
    registre.ajouter(_reception())
    registre.ajouter(_consommation())
    registre._maillons[0]["quantite"] = 999.0

    valide, message = registre.valider_chaine()

    assert valide is False
    assert "0" in message


def test_hash_tete_est_vide_pour_un_registre_vide():
    registre = Registre()

    assert registre.hash_tete() == ""


def test_hash_tete_est_le_hash_du_dernier_maillon_ajoute():
    registre = Registre()
    maillon, erreur = registre.ajouter(_reception())

    assert erreur is None
    assert registre.hash_tete() == maillon["hash_maillon"]


def test_ajouter_refuse_un_type_invalide_sans_modifier_le_registre():
    registre = Registre()
    mouvement_invalide = {
        "type_mouvement": "AUTRE",
        "chantier_id": "chantier-A",
        "materiau_id": "beton-C25",
        "quantite": 1.0,
        "cout_unitaire": 110.0,
    }

    maillon, code_erreur = registre.ajouter(mouvement_invalide)

    assert maillon is None
    assert isinstance(code_erreur, str)
    assert code_erreur
    assert registre.lire() == []


def test_ajouter_lot_ajoute_et_chaine_les_mouvements_apres_un_etat_preexistant():
    registre = Registre()
    precedent, erreur_precedent = registre.ajouter(_reception())

    maillons, erreur = registre.ajouter_lot([_consommation(), _variance()])

    assert erreur_precedent is None
    assert erreur is None
    assert len(maillons) == 2
    assert maillons[0]["index"] == 1
    assert maillons[0]["hash_precedent"] == precedent["hash_maillon"]
    assert maillons[1]["index"] == 2
    assert maillons[1]["hash_precedent"] == maillons[0]["hash_maillon"]
    assert registre.lire() == [precedent, maillons[0], maillons[1]]


def test_ajouter_lot_est_atomique_si_le_second_mouvement_est_invalide():
    registre = Registre()
    registre.ajouter(_reception())
    avant = registre.lire()
    mouvement_invalide = {
        "type_mouvement": "AUTRE",
        "chantier_id": "chantier-A",
        "materiau_id": "beton-C25",
        "quantite": 1.0,
        "cout_unitaire": 110.0,
    }

    maillons, code_erreur = registre.ajouter_lot([_consommation(), mouvement_invalide])

    assert maillons is None
    assert isinstance(code_erreur, str)
    assert code_erreur
    assert registre.lire() == avant
