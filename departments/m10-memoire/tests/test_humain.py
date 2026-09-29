"""humain.py : la forme d'un humain identifié et motivé (PLAN T3.3-suite-b). Données fictives."""

import pytest
from m10_memoire import humain

FICTIF = True
MOTIF = "Un motif qui dit vraiment pourquoi."
HORODATAGE = "2026-09-16T09:00:00-04:00"


def test_les_deux_roles_et_les_deux_voies_sont_les_seuls_admis():
    assert humain.roles_humains() == {"admin", "nathan_owner"}
    assert humain.acteur_valide("amina.admin", "admin", "appareil") is True
    assert humain.acteur_valide("nathan", "nathan_owner", "approbation") is True
    for role in ("employee", "seller", "manager", "finance", "client", "system_agent", "", None):
        assert humain.acteur_valide("amina.admin", role, "appareil") is False
    for source in ("modele", "cli", "", None):
        assert humain.acteur_valide("amina.admin", "admin", source) is False


@pytest.mark.parametrize("par", ["", "A", "Amina", "amina admin", "1amina", "amina\n", "x" * 65, None, 3])
def test_une_personne_a_la_forme_d_un_identifiant_de_personne_d_opsys(par):
    assert humain.acteur_valide(par, "admin", "appareil") is False


def test_le_motif_est_borne_apres_retrait_des_blancs():
    assert humain.motif_valide("x" * humain.MOTIF_MIN_CARACTERES) is True
    assert humain.motif_valide("x" * humain.MOTIF_MAX_CARACTERES) is True
    assert humain.motif_valide("x" * (humain.MOTIF_MIN_CARACTERES - 1)) is False
    assert humain.motif_valide("x" * (humain.MOTIF_MAX_CARACTERES + 1)) is False
    assert humain.motif_valide("   " + "x" * (humain.MOTIF_MIN_CARACTERES - 1) + "   ") is False
    assert humain.motif_valide(None) is False


def test_verifier_ecriture_rend_none_quand_tout_est_conforme():
    assert humain.verifier_ecriture("amina.admin", "admin", "appareil", MOTIF, HORODATAGE) is None


@pytest.mark.parametrize(
    "arguments,code",
    [
        (("modele", "system_agent", "appareil", MOTIF, HORODATAGE), humain.REJ_HUMAIN_ACTEUR_INVALIDE),
        (("amina.admin", "admin", "appareil", "", HORODATAGE), humain.REJ_HUMAIN_MOTIF_INVALIDE),
        (("amina.admin", "admin", "appareil", MOTIF, "2026-09-16T09:00:00"), humain.REJ_HUMAIN_HORODATAGE_INVALIDE),
    ],
)
def test_verifier_ecriture_nomme_le_premier_defaut_et_dit_quoi_faire(arguments, code):
    verdict = humain.verifier_ecriture(*arguments)

    assert verdict["code"] == code and verdict["detail"]
