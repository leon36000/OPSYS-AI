"""Tests unitaires purs du module consentement.py (PLAN T4.2, POLITIQUE-geolocalisation.md §4).

Même patron que test_geolocalisation_gps.py : registre EN MÉMOIRE, aucun import opsys.
"""
from __future__ import annotations

import pytest
from m4_field_ops import consentement as consentement_mod
from m4_field_ops import registre as registre_mod

H1 = "2025-06-01T08:00:00+00:00"
H2 = "2025-06-02T08:00:00+00:00"
H3 = "2025-06-03T08:00:00+00:00"
VERSION = "POLITIQUE-geolocalisation-v1-test"
PREUVE_OK = {"fictif": True, "reference": "formulaire-signe-001"}


def _registre():
    return registre_mod.Registre()


# ------------------------------------------------------------------ enregistrer_consentement
def test_donner_consentement_accepte_et_ecrit_un_maillon():
    reg = _registre()
    accuse, verdict = consentement_mod.enregistrer_consentement(
        "T1", "donne", H1, VERSION, PREUVE_OK, reg,
    )
    assert accuse is not None, f"refusé : {verdict}"
    assert accuse["technicien_id"] == "T1"
    assert accuse["actif"] is True
    assert reg.taille() == 1
    maillon = reg.lire()[0]
    assert maillon["type_entree"] == consentement_mod.TYPE_CONSENTEMENT
    assert maillon["action"] == "donne"
    assert maillon["version_politique"] == VERSION
    assert maillon["preuve"] == {"fictif": True, "reference": "formulaire-signe-001"}
    assert reg.valider_chaine() is True


def test_retirer_consentement_accuse_actif_faux():
    reg = _registre()
    consentement_mod.enregistrer_consentement("T1", "donne", H1, VERSION, PREUVE_OK, reg)
    accuse, verdict = consentement_mod.enregistrer_consentement(
        "T1", "retire", H2, VERSION, PREUVE_OK, reg,
    )
    assert accuse is not None, f"refusé : {verdict}"
    assert accuse["actif"] is False


@pytest.mark.parametrize("technicien_id", ["", None, 123])
def test_technicien_id_invalide_refuse_rien_ecrit(technicien_id):
    reg = _registre()
    accuse, verdict = consentement_mod.enregistrer_consentement(
        technicien_id, "donne", H1, VERSION, PREUVE_OK, reg,
    )
    assert accuse is None
    assert verdict["code"] == "REJ-CONSENTEMENT-INVALIDE"
    assert reg.taille() == 0


def test_action_hors_enum_refuse_rien_ecrit():
    reg = _registre()
    accuse, verdict = consentement_mod.enregistrer_consentement(
        "T1", "peut_etre", H1, VERSION, PREUVE_OK, reg,
    )
    assert accuse is None
    assert verdict["code"] == "REJ-CONSENTEMENT-INVALIDE"
    assert reg.taille() == 0


def test_horodatage_sans_fuseau_refuse():
    reg = _registre()
    accuse, verdict = consentement_mod.enregistrer_consentement(
        "T1", "donne", "2025-06-01T08:00:00", VERSION, PREUVE_OK, reg,
    )
    assert accuse is None
    assert verdict["code"] == "REJ-CONSENTEMENT-INVALIDE"


@pytest.mark.parametrize("version", ["", None, 42])
def test_version_politique_manquante_ou_vide_refuse(version):
    reg = _registre()
    accuse, verdict = consentement_mod.enregistrer_consentement(
        "T1", "donne", H1, version, PREUVE_OK, reg,
    )
    assert accuse is None
    assert verdict["code"] == "REJ-CONSENTEMENT-INVALIDE"
    assert reg.taille() == 0


@pytest.mark.parametrize("preuve", [
    {"fictif": False, "reference": "x"},   # preuve réelle non supportée en mode ombre
    {"fictif": True, "reference": ""},     # reference vide
    {"fictif": True},                      # reference manquante
    {"reference": "x"},                    # fictif manquant
    "pas-un-dict",
    None,
])
def test_preuve_invalide_refuse_rien_ecrit(preuve):
    reg = _registre()
    accuse, verdict = consentement_mod.enregistrer_consentement(
        "T1", "donne", H1, VERSION, preuve, reg,
    )
    assert accuse is None
    assert verdict["code"] == "REJ-CONSENTEMENT-INVALIDE"
    assert reg.taille() == 0


# ------------------------------------------------------------------ consentement_actif (fail-closed)
def test_consentement_actif_absent_par_defaut_false():
    """§2 : consentement documenté AVANT activation — aucun maillon -> False, jamais un défaut actif."""
    reg = _registre()
    assert consentement_mod.consentement_actif(reg, "T-JAMAIS-VU") is False


def test_consentement_actif_apres_donne_true():
    reg = _registre()
    consentement_mod.enregistrer_consentement("T1", "donne", H1, VERSION, PREUVE_OK, reg)
    assert consentement_mod.consentement_actif(reg, "T1") is True


def test_consentement_actif_apres_retrait_immediatement_false():
    """§4 : « le retrait désactive immédiatement le punch géorépéré » — vrai dès ce maillon écrit,
    sans file d'attente ni tâche différée."""
    reg = _registre()
    consentement_mod.enregistrer_consentement("T1", "donne", H1, VERSION, PREUVE_OK, reg)
    consentement_mod.enregistrer_consentement("T1", "retire", H2, VERSION, PREUVE_OK, reg)
    assert consentement_mod.consentement_actif(reg, "T1") is False


def test_consentement_actif_redonne_apres_retrait_true():
    """§7 : droit de retrait à tout moment — n'empêche pas un consentement ultérieur."""
    reg = _registre()
    consentement_mod.enregistrer_consentement("T1", "donne", H1, VERSION, PREUVE_OK, reg)
    consentement_mod.enregistrer_consentement("T1", "retire", H2, VERSION, PREUVE_OK, reg)
    consentement_mod.enregistrer_consentement("T1", "donne", H3, VERSION, PREUVE_OK, reg)
    assert consentement_mod.consentement_actif(reg, "T1") is True


def test_consentement_actif_par_technicien_jamais_partage():
    reg = _registre()
    consentement_mod.enregistrer_consentement("T1", "donne", H1, VERSION, PREUVE_OK, reg)
    assert consentement_mod.consentement_actif(reg, "T2") is False


# ------------------------------------------------------------------ historique_consentement (§7)
def test_historique_consentement_porte_donne_et_retire_jamais_ecrase():
    reg = _registre()
    consentement_mod.enregistrer_consentement("T1", "donne", H1, VERSION, PREUVE_OK, reg)
    consentement_mod.enregistrer_consentement("T1", "retire", H2, VERSION, PREUVE_OK, reg)
    historique = consentement_mod.historique_consentement(reg, "T1")
    assert [m["action"] for m in historique] == ["donne", "retire"]
    assert [m["horodatage"] for m in historique] == [H1, H2]


def test_historique_consentement_technicien_inconnu_liste_vide():
    reg = _registre()
    assert consentement_mod.historique_consentement(reg, "T-INCONNU") == []
