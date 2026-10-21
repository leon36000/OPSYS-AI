"""Catalogue privé M5→M7 ; fixtures synthétiques, aucun coût ni provider réel."""

import pytest

from opsys.departements import charger_departements

NOMS = {
    "m5_affecter_cout_marketing", "m5_revoquer_affectation_cout_marketing",
    "m5_lire_couts_marketing_affectes",
}


def _lecteur(_campagne):
    return {"ok": False, "erreur": "fixture-fictive-source-absente"}


def test_catalogue_public_et_port_m4_ne_recoivent_aucun_outil_cout():
    dep = charger_departements()["m05-financecore"]
    assert not NOMS & {o.nom for o in dep.charger_outils()}
    assert not NOMS & {o.nom for o in dep.charger_outils(ports_prives={"lecteur_heures_m4": _lecteur})}


@pytest.mark.parametrize("m4", [False, True])
def test_raccord_m7_prive_contient_exactement_trois_outils_fermes(m4):
    dep = charger_departements()["m05-financecore"]
    publics = {o.nom for o in dep.charger_outils()}
    ports = {"lecteur_campagne_m7": _lecteur}
    if m4:
        ports["lecteur_heures_m4"] = _lecteur
    catalogue = dep.charger_outils(ports_prives=ports)
    assert {o.nom for o in catalogue} - publics == NOMS
    assert all(not o.roles_appareil for o in catalogue if o.nom in NOMS)
    assert {o.nom: o.niveau_effectif.value for o in catalogue if o.nom in NOMS} == {
        "m5_affecter_cout_marketing": "N4", "m5_revoquer_affectation_cout_marketing": "N4",
        "m5_lire_couts_marketing_affectes": "N0",
    }


@pytest.mark.parametrize("ports", [{"lecteur_campagne_m7": "commande"}, {"autre_port": _lecteur}])
def test_port_hors_contrat_refuse(ports):
    with pytest.raises(ValueError, match="port privé non autorisé"):
        charger_departements()["m05-financecore"].charger_outils(ports_prives=ports)
