from decimal import Decimal, Inexact, Rounded, localcontext

import pytest
from m5_financecore import registre, soldes, validation

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


def test_un_decaissement_positif_est_refuse_avant_d_atteindre_le_solde():
    """Bug NEW-PROD : un DECAISSEMENT de +100 produisait un solde de +100 (au lieu
    de -100) faute de contrôle de signe. La garde doit intervenir à l'écriture,
    AVANT que le mouvement n'atteigne le registre et ne fausse calculer_solde."""
    registre_cible = registre.Registre()
    _ajouter(registre_cible, Decimal("100.00"), "ENCAISSEMENT")

    with pytest.raises(validation.MouvementInvalide) as erreur:
        _ajouter(registre_cible, Decimal("100.00"), "DECAISSEMENT")

    assert erreur.value.verdict["code"] == "REJ-MOUVEMENT-SIGNE-INCOHERENT"
    # Le solde reste celui d'avant la tentative : jamais +100 fantôme.
    assert soldes.calculer_solde(registre_cible) == Decimal("100.00")


def test_registre_vide_donne_un_solde_et_un_argent_disponible_nuls():
    registre_cible = registre.Registre()

    assert soldes.calculer_solde(registre_cible) == Decimal("0")
    assert soldes.calculer_argent_disponible(registre_cible) == Decimal("0")


def test_un_encaissement_est_compte_dans_le_solde():
    registre_cible = registre.Registre()
    _ajouter(registre_cible, Decimal("100.00"), "ENCAISSEMENT")

    assert soldes.calculer_solde(registre_cible) == Decimal("100.00")


def test_un_decaissement_deja_signe_negativement_diminue_le_solde():
    registre_cible = registre.Registre()
    _ajouter(registre_cible, Decimal("100.00"), "ENCAISSEMENT")
    _ajouter(registre_cible, Decimal("-30.00"), "DECAISSEMENT")

    assert soldes.calculer_solde(registre_cible) == Decimal("70.00")


def test_une_provision_n_affecte_pas_le_solde_mais_diminue_l_argent_disponible():
    registre_cible = registre.Registre()
    _ajouter(registre_cible, Decimal("100.00"), "ENCAISSEMENT")
    _ajouter(registre_cible, Decimal("20.00"), "PROVISION")

    assert soldes.calculer_solde(registre_cible) == Decimal("100.00")
    assert soldes.calculer_argent_disponible(registre_cible) == Decimal("80.00")


def test_un_ajustement_est_compte_dans_le_solde():
    registre_cible = registre.Registre()
    _ajouter(registre_cible, Decimal("100.00"), "ENCAISSEMENT")
    _ajouter(registre_cible, Decimal("-10.00"), "AJUSTEMENT")

    assert soldes.calculer_solde(registre_cible) == Decimal("90.00")


def test_un_mouvement_autre_est_compte_dans_le_solde():
    registre_cible = registre.Registre()
    _ajouter(registre_cible, Decimal("5.00"), "AUTRE")

    assert soldes.calculer_solde(registre_cible) == Decimal("5.00")


def test_toutes_les_provisions_s_additionnent_pour_calculer_l_argent_disponible():
    registre_cible = registre.Registre()
    _ajouter(registre_cible, Decimal("100.00"), "ENCAISSEMENT")
    _ajouter(registre_cible, Decimal("20.00"), "PROVISION")
    _ajouter(registre_cible, Decimal("30.00"), "PROVISION")

    assert soldes.calculer_argent_disponible(registre_cible) == Decimal("50.00")


def test_sans_provision_l_argent_disponible_est_exactement_egal_au_solde():
    registre_cible = registre.Registre()
    _ajouter(registre_cible, Decimal("100.00"), "ENCAISSEMENT")
    _ajouter(registre_cible, Decimal("-30.00"), "DECAISSEMENT")

    solde = soldes.calculer_solde(registre_cible)
    argent_disponible = soldes.calculer_argent_disponible(registre_cible)

    assert argent_disponible == solde


def test_les_calculs_sont_purs_et_reproductibles_sur_le_meme_registre():
    registre_cible = registre.Registre()
    _ajouter(registre_cible, Decimal("100.00"), "ENCAISSEMENT")
    _ajouter(registre_cible, Decimal("-10.00"), "AJUSTEMENT")
    _ajouter(registre_cible, Decimal("20.00"), "PROVISION")

    solde_initial = soldes.calculer_solde(registre_cible)
    argent_initial = soldes.calculer_argent_disponible(registre_cible)

    solde_recalcule = soldes.calculer_solde(registre_cible)
    argent_recalcule = soldes.calculer_argent_disponible(registre_cible)

    assert solde_recalcule == solde_initial
    assert argent_recalcule == argent_initial
    assert solde_initial == Decimal("90.00")
    assert argent_initial == Decimal("70.00")


def test_un_solde_decimal_ne_subit_pas_d_erreur_binaire():
    registre_cible = registre.Registre()
    _ajouter(registre_cible, Decimal("0.10"), "ENCAISSEMENT")
    _ajouter(registre_cible, Decimal("0.20"), "ENCAISSEMENT")

    solde = soldes.calculer_solde(registre_cible)

    assert type(solde) is Decimal
    assert solde == Decimal("0.30")


def test_solde_et_provisions_sont_independants_du_contexte_decimal_appelant():
    registre_cible = registre.Registre()
    _ajouter(registre_cible, Decimal("100000000"), "ENCAISSEMENT")
    _ajouter(registre_cible, Decimal("0.01"), "ENCAISSEMENT")
    _ajouter(registre_cible, Decimal("-100000000"), "AJUSTEMENT")
    _ajouter(registre_cible, Decimal("100000000"), "PROVISION")
    _ajouter(registre_cible, Decimal("0.01"), "PROVISION")
    _ajouter(registre_cible, Decimal("100000000"), "PROVISION")

    with localcontext() as contexte:
        contexte.prec = 8
        contexte.traps[Inexact] = True
        contexte.traps[Rounded] = True
        solde = soldes.calculer_solde(registre_cible)
        provisions = soldes.calculer_provisions(registre_cible)[0]
        disponible = soldes.calculer_argent_disponible(registre_cible)

    assert solde == Decimal("0.01")
    assert provisions == Decimal("200000000.01")
    assert disponible == Decimal("-200000000.00")


def test_decrire_les_mouvements_ne_compte_que_les_mouvements_pas_les_autres_maillons_du_registre():
    """PLAN T4.16 : la source du solde dit combien de MOUVEMENTS le portent (`nombre`), pas la taille du registre
    (`taille_registre`) où d'autres familles de maillons peuvent vivre ; la tête est celle de la chaîne entière."""
    registre_cible = registre.Registre()
    _ajouter(registre_cible, Decimal("100.00"), "ENCAISSEMENT")
    registre_cible.ajouter({"type_entree": "demande_creee", "horodatage": "2026-08-04T09:00:00+00:00"})
    _ajouter(registre_cible, Decimal("20.00"), "PROVISION")

    decrit = soldes.decrire_mouvements(registre_cible)

    assert decrit["nombre"] == 2 and decrit["taille_registre"] == 3
    assert decrit["derniere_piece"] == HORODATAGE and decrit["tete"] == registre_cible.tete()
    assert soldes.decrire_mouvements(registre.Registre()) == {
        "nombre": 0, "derniere_piece": None, "taille_registre": 0, "tete": None}
