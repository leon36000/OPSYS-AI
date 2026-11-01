"""Interconnexion M7 -> M8 et M7 -> M5 sur le VRAI bus (consommateurs réels, aucun double de handler)."""

from __future__ import annotations

import interconnexion_charges as ch
import interconnexion_monde as im
import pytest

M5, M7, M8 = "m05-financecore", "m07-marketing", "m08-analytics"


@pytest.fixture
def monde(tmp_path, monkeypatch):
    yield im.monter(tmp_path, monkeypatch, (M5, M7, M8))
    im.demonter()


def test_depense_vers_m8_et_m5(monde):
    ch.publier_depuis(M7, "m7.depenses_marketing_constatees", ch.depense_marketing(), "m7-dep-1")
    r = monde.repartir()
    assert r["quarantaines"] == 0 and r["echecs"] == 0, r
    print(monde.registre(M5, "charges_marketing_recues"))
    print(monde.registre(M8, "faits_operations"))
    print(monde.registre(M5, "grand_livre"))
