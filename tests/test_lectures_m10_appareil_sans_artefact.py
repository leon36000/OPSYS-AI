"""Lectures appareil M10 fictives : le plafond effectif ferme sans artefact ni transaction."""
from unittest.mock import Mock

import pytest
from tests.test_paquet_prive_sans_artefact import enveloppe, tables

from opsys import jetons
from opsys.capacites import Capacites

SOURCES = [
    ("m10_lire_paquet_affaire_appareil", "REJ-PAQUET-AFFAIRE-SORTIE-TROP-VOLUMINEUSE"),
    ("m10_rechercher_affaire_appareil", "REJ-RECHERCHE-AFFAIRE-SORTIE-TROP-VOLUMINEUSE"),
]


@pytest.mark.parametrize("source,code", SOURCES)
@pytest.mark.parametrize("limite", [800, 6000])
@pytest.mark.parametrize("ecart", [-1, 0, 1])
@pytest.mark.parametrize("prefixe", ["fictif", "é😀", '\"\\\n\t'])
def test_plafond_appareil_effectif_sans_artefact(
    departements_demo, session, monkeypatch, source, code, limite, ecart, prefixe,
):
    cap = Capacites(departements_demo, session, limite_sortie=limite)
    initial = tables(session)
    transaction = Mock(side_effect=AssertionError("transaction de fallback sur lecture appareil M10"))
    tronquer = Mock(side_effect=AssertionError("artefact sur lecture appareil M10"))
    monkeypatch.setattr(cap, "_cnx_factory", transaction)
    monkeypatch.setattr(jetons, "tronquer", tronquer)
    r = enveloppe(limite + ecart, prefixe)
    lu = cap._tronquer(r, source, departement="m10-memoire", origine="m10-memoire")
    if ecart <= 0:
        assert lu is r
    else:
        assert lu["ok"] is False and lu["erreur"] == code
        assert set(lu) == {"ok", "erreur", "details"}
        assert "aucun détail partiel" in lu["details"]
    transaction.assert_not_called()
    tronquer.assert_not_called()
    assert tables(session) == initial
