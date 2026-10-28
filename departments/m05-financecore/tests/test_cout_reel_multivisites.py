"""Régression : un WCT scalaire fictif ne prouve pas une équipe unique."""
from decimal import Decimal

from m5_financecore import cout_reel


def test_duree_scalaire_sans_preuve_ne_certifie_pas_la_main_d_oeuvre():
    wct = {"wct_id": "FICTIF-MULTI", "duree_reelle_minutes": 390}
    resultat = cout_reel._main_d_oeuvre(wct, Decimal("100"))
    assert resultat["statut"] == "non_disponible"
    assert resultat["cout"] is None
    assert resultat["manque"]
