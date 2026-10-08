"""Lectures M6 fictives : une borne dépassée ne produit ni copie partielle ni écriture."""

from unittest.mock import Mock

import pytest
from tests.test_paquet_prive_sans_artefact import enveloppe, tables

from opsys import jetons
from opsys.capacites import Capacites

SOURCES = [
    ("m6_lister_wct_pertes_appareil", "REJ-M6-WCT-SORTIE-TROP-VOLUMINEUSE"),
    ("m6_lire_pertes_alertes_wct_appareil", "REJ-M6-PERTES-SORTIE-TROP-VOLUMINEUSE"),
]


@pytest.mark.parametrize("source,code", SOURCES)
@pytest.mark.parametrize("limite", [800, 6000])
@pytest.mark.parametrize("ecart", [-1, 0, 1])
@pytest.mark.parametrize("prefixe", ["fictif", "é😀", '\"\\\n\t'])
def test_plafond_m6_effectif_sans_artefact(
    departements_demo, session, monkeypatch, source, code, limite, ecart, prefixe,
):
    cap = Capacites(departements_demo, session, limite_sortie=limite)
    initial = tables(session)
    transaction = Mock(side_effect=AssertionError("fallback de lecture M6"))
    tronquer = Mock(side_effect=AssertionError("artefact de lecture M6"))
    monkeypatch.setattr(cap, "_cnx_factory", transaction)
    monkeypatch.setattr(jetons, "tronquer", tronquer)
    reponse = enveloppe(limite + ecart, prefixe)
    lu = cap._tronquer(reponse, source, departement="m06-material-control", origine="m06-material-control")
    if ecart <= 0:
        assert lu is reponse
    else:
        assert lu["ok"] is False and lu["erreur"] == code
        assert set(lu) == {"ok", "erreur", "details"}
        assert "aucun détail partiel" in lu["details"]
    transaction.assert_not_called()
    tronquer.assert_not_called()
    assert tables(session) == initial
