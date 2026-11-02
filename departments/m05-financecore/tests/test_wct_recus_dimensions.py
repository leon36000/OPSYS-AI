"""Le reçu de fin de chantier garde `service` et `ville` : les rejeux doivent les repasser, sinon le coût certifié
est refusé."""
from m5_financecore import wct_recus
from m5_financecore.encodage import encoder_canonique

CHARGE = {
    "wct_id": "FICTIF-WCT-D", "intervention_id": "FICTIF-INT-D", "devis_id": "FICTIF-DEVIS-D",
    "horodatage_completion": "2026-11-02T16:00:00-05:00", "service": "gouttieres", "ville": "Laval",
}


def _recu(charge, **dimensions):
    return wct_recus.construire(
        wct_id=charge["wct_id"], intervention_id=charge["intervention_id"], devis_id=charge["devis_id"],
        horodatage_completion=charge["horodatage_completion"], empreinte_charge="e" * 64, **dimensions)


def _rejoue(recu, charge):
    return wct_recus.construire(
        wct_id=charge["wct_id"], intervention_id=charge["intervention_id"], devis_id=charge["devis_id"],
        horodatage_completion=charge["horodatage_completion"], empreinte_charge="e" * 64,
        **wct_recus.dimensions_a_rejouer(recu, charge))


def test_un_recu_avec_dimensions_se_rejoue_a_l_identique():
    recu = _recu(CHARGE, service=CHARGE["service"], ville=CHARGE["ville"])
    assert recu["service"] == "gouttieres" and recu["ville"] == "Laval"
    assert encoder_canonique(_rejoue(recu, CHARGE)) == encoder_canonique(recu)


def test_un_ancien_recu_sans_dimensions_ne_diverge_pas_a_tort():
    ancien = _recu(CHARGE)
    assert "service" not in ancien and "ville" not in ancien
    assert encoder_canonique(_rejoue(ancien, CHARGE)) == encoder_canonique(ancien)


def test_une_dimension_alteree_dans_le_recu_reste_une_divergence():
    recu = _recu(CHARGE, service=CHARGE["service"], ville="Montréal")
    assert encoder_canonique(_rejoue(recu, CHARGE)) != encoder_canonique(recu)


def test_un_recu_absent_ou_illisible_ne_repasse_aucune_dimension():
    assert wct_recus.dimensions_a_rejouer(None, CHARGE) == {}
