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


def test_ajouter_lot_ne_modifie_rien_si_un_mouvement_du_lot_manque_un_champ():
    registre = Registre()
    avant = registre.lire()
    mouvement_incomplet = {
        "type_mouvement": "CONSOMMATION",
        "chantier_id": "chantier-A",
        "materiau_id": "beton-C25",
        "quantite": -3.0,
    }

    maillons, code_erreur = registre.ajouter_lot([_reception(), mouvement_incomplet])

    assert maillons is None
    assert code_erreur == "REJ-MOUVEMENT-STRUCTURE-INVALIDE"
    assert registre.lire() == avant
    assert registre.lire() == []


def _retour():
    return {
        "type_mouvement": "RETOUR",
        "chantier_id": "chantier-A",
        "materiau_id": "beton-C25",
        "quantite": 2.0,
        "cout_unitaire": 110.0,
    }


def _perte():
    return {
        "type_mouvement": "PERTE",
        "chantier_id": "chantier-A",
        "materiau_id": "beton-C25",
        "quantite": -1.0,
        "cout_unitaire": 110.0,
    }


def _bris():
    return {
        "type_mouvement": "BRIS",
        "chantier_id": "chantier-A",
        "materiau_id": "beton-C25",
        "quantite": -1.0,
        "cout_unitaire": 110.0,
    }


# --- PLAN T1.1-d2 : RETOUR/PERTE/BRIS, wct_id optionnel et rétrocompatible -------------


def test_types_mouvement_retour_perte_bris_sont_acceptes():
    registre = Registre()

    for mouvement in (_retour(), _perte(), _bris()):
        maillon, erreur = registre.ajouter(mouvement)
        assert erreur is None
        assert maillon["type_mouvement"] == mouvement["type_mouvement"]

    assert registre.valider_chaine() == (True, "")


def test_maillon_sans_wct_id_garde_exactement_les_huit_cles_historiques():
    """Rétrocompatibilité PLAN T1.1-d2 : un mouvement sans wct_id (tout appelant
    antérieur) produit un maillon STRICTEMENT identique en forme à avant ce changement."""
    registre = Registre()

    maillon, erreur = registre.ajouter(_reception())

    assert erreur is None
    assert set(maillon) == _CLES_MAILLON


def test_maillon_avec_wct_id_porte_la_cle_en_plus_et_reste_valide():
    registre = Registre()

    maillon, erreur = registre.ajouter({**_consommation(), "wct_id": "wct-1"})

    assert erreur is None
    assert set(maillon) == _CLES_MAILLON | {"wct_id"}
    assert maillon["wct_id"] == "wct-1"
    assert registre.valider_chaine() == (True, "")


def test_wct_id_entre_dans_le_hash_deux_wct_id_differents_donnent_des_hash_differents():
    registre_1 = Registre()
    registre_2 = Registre()

    maillon_1, _ = registre_1.ajouter({**_consommation(), "wct_id": "wct-1"})
    maillon_2, _ = registre_2.ajouter({**_consommation(), "wct_id": "wct-2"})

    assert maillon_1["hash_maillon"] != maillon_2["hash_maillon"]


def test_alteration_du_wct_id_est_detectee_par_valider_chaine():
    registre = Registre()
    registre.ajouter({**_consommation(), "wct_id": "wct-1"})

    registre._maillons[0]["wct_id"] = "wct-falsifie"

    valide, message = registre.valider_chaine()
    assert valide is False
    assert "0" in message


def test_mouvement_sans_wct_id_produit_le_meme_hash_qu_avant_ce_changement():
    """Preuve de non-régression directe : le hash d'un mouvement SANS wct_id est
    identique, avec ou sans le code PLAN T1.1-d2 — recalculé ici à la main avec la
    formule d'origine (7 arguments, sans wct_id)."""
    from m6_material_control import encodage

    registre = Registre()
    maillon, _ = registre.ajouter(_reception())

    hash_attendu_formule_dorigine = encodage.empreinte(
        0,
        _reception()["type_mouvement"],
        _reception()["chantier_id"],
        _reception()["materiau_id"],
        _reception()["quantite"],
        _reception()["cout_unitaire"],
        "",
    )
    assert maillon["hash_maillon"] == hash_attendu_formule_dorigine


def test_ajouter_lot_produit_un_chainage_de_hash_identique_au_cas_ajouter_un_par_un():
    mouvements = [_reception(), _consommation(), _variance()]

    registre_un_par_un = Registre()
    maillons_un_par_un = []
    for m in mouvements:
        maillon, erreur = registre_un_par_un.ajouter(m)
        assert erreur is None
        maillons_un_par_un.append(maillon)

    registre_lot = Registre()
    maillons_lot, erreur_lot = registre_lot.ajouter_lot(mouvements)

    assert erreur_lot is None
    assert len(maillons_lot) == len(maillons_un_par_un)
    for a, b in zip(maillons_un_par_un, maillons_lot, strict=True):
        assert a["hash_maillon"] == b["hash_maillon"]
        assert a["hash_precedent"] == b["hash_precedent"]
        assert a["index"] == b["index"]
    assert [m["hash_maillon"] for m in registre_un_par_un.lire()] == [m["hash_maillon"] for m in registre_lot.lire()]
