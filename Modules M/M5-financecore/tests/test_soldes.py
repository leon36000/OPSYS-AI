import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m5_financecore import registre, soldes


HORODATAGE = "2026-08-03T12:00:00+00:00"


def _ajouter(registre_cible, montant, type_mouvement, source="test"):
    mouvement = {
        "montant": montant,
        "type_mouvement": type_mouvement,
        "horodatage": HORODATAGE,
        "classe_retention": "STANDARD",
        "source": source,
    }
    return registre.enregistrer_mouvement(mouvement, registre_cible)


def test_registre_vide_donne_un_solde_et_un_argent_disponible_nuls():
    registre_cible = registre.Registre()

    assert soldes.calculer_solde(registre_cible) == 0.0
    assert soldes.calculer_argent_disponible(registre_cible) == 0.0


def test_un_encaissement_est_compte_dans_le_solde():
    registre_cible = registre.Registre()
    _ajouter(registre_cible, 100.0, "ENCAISSEMENT")

    assert soldes.calculer_solde(registre_cible) == 100.0


def test_un_decaissement_deja_signe_negativement_diminue_le_solde():
    registre_cible = registre.Registre()
    _ajouter(registre_cible, 100.0, "ENCAISSEMENT")
    _ajouter(registre_cible, -30.0, "DECAISSEMENT")

    assert soldes.calculer_solde(registre_cible) == 70.0


def test_une_provision_n_affecte_pas_le_solde_mais_diminue_l_argent_disponible():
    registre_cible = registre.Registre()
    _ajouter(registre_cible, 100.0, "ENCAISSEMENT")
    _ajouter(registre_cible, 20.0, "PROVISION")

    assert soldes.calculer_solde(registre_cible) == 100.0
    assert soldes.calculer_argent_disponible(registre_cible) == 80.0


def test_un_ajustement_est_compte_dans_le_solde():
    registre_cible = registre.Registre()
    _ajouter(registre_cible, 100.0, "ENCAISSEMENT")
    _ajouter(registre_cible, -10.0, "AJUSTEMENT")

    assert soldes.calculer_solde(registre_cible) == 90.0


def test_un_mouvement_autre_est_compte_dans_le_solde():
    registre_cible = registre.Registre()
    _ajouter(registre_cible, 5.0, "AUTRE")

    assert soldes.calculer_solde(registre_cible) == 5.0


def test_toutes_les_provisions_s_additionnent_pour_calculer_l_argent_disponible():
    registre_cible = registre.Registre()
    _ajouter(registre_cible, 100.0, "ENCAISSEMENT")
    _ajouter(registre_cible, 20.0, "PROVISION")
    _ajouter(registre_cible, 30.0, "PROVISION")

    assert soldes.calculer_argent_disponible(registre_cible) == 50.0


def test_sans_provision_l_argent_disponible_est_exactement_egal_au_solde():
    registre_cible = registre.Registre()
    _ajouter(registre_cible, 100.0, "ENCAISSEMENT")
    _ajouter(registre_cible, -30.0, "DECAISSEMENT")

    solde = soldes.calculer_solde(registre_cible)
    argent_disponible = soldes.calculer_argent_disponible(registre_cible)

    assert argent_disponible == solde


def test_les_calculs_sont_purs_et_reproductibles_sur_le_meme_registre():
    registre_cible = registre.Registre()
    _ajouter(registre_cible, 100.0, "ENCAISSEMENT")
    _ajouter(registre_cible, -10.0, "AJUSTEMENT")
    _ajouter(registre_cible, 20.0, "PROVISION")

    solde_initial = soldes.calculer_solde(registre_cible)
    argent_initial = soldes.calculer_argent_disponible(registre_cible)

    solde_recalcule = soldes.calculer_solde(registre_cible)
    argent_recalcule = soldes.calculer_argent_disponible(registre_cible)

    assert solde_recalcule == solde_initial
    assert argent_recalcule == argent_initial
    assert solde_initial == 90.0
    assert argent_initial == 70.0
