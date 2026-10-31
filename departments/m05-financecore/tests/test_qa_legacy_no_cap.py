"""Vrai bus M5 : ancien WCT sans capacité ne devient ni erreur ni coût complet."""

from opsys import stockage
from test_cout_reel_cascade import _codes, _livrer, _publier, _traces
from test_cout_reel_cascade import base_durable as base_durable
from test_cout_reel_cascade import taux_configure as taux_configure


def test_legacy_recu_partiel_et_rejeu(base_durable, taux_configure):
    for piece in ("devis", "wct", "variance"):
        _publier(piece)
        _livrer()
    traces = _traces()
    assert traces and traces[-1]["verdict"] == "PARTIELLE"
    assert "REJ-COUT-TEMPS-POINTE-ABSENT" in _codes(traces[-1])
    assert traces[-1]["rentabilite"]["cout_reel"]["main_d_oeuvre"]["cout"] is None
    with stockage.transaction():
        recus = list(stockage.maillons("m05-financecore", "wct_recus"))
        service = list(stockage.maillons("m05-financecore", "rentabilite_service_v1"))
    assert len(recus) == 1 and service == []
    _livrer()
    assert _traces() == traces
    with stockage.transaction():
        assert list(stockage.maillons("m05-financecore", "wct_recus")) == recus
