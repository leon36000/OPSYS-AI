"""Un appel direct enrichi C5 doit refuser proprement l'absence du registre durable."""

from __future__ import annotations

import m6_material_control.outils as m6_outils
import pytest

from opsys import stockage


@pytest.fixture
def base(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'm6-c5-direct-refusal-fictif.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    try:
        yield url
    finally:
        stockage.liberer()


def _entrees():
    material, project, po = "mat-c5-direct-fictif", "CH-c5-direct-fictif", "PO-c5-direct-fictif"
    date = "2026-11-08T10:00:00-04:00"
    return material, {
        "po_id": po,
        "chantier_id": project,
        "lignes_demandees": [{"materiau_id": material, "quantite_demandee": 2.0}],
        "horodatage": date,
    }, {
        "po_id": po,
        "chantier_id": project,
        "lignes_recues": [{"materiau_id": material, "quantite_recue": 2.0}],
        "horodatage": date,
    }


@pytest.mark.parametrize("c5", ["details", "lieu"])
def test_reception_c5_directe_refuse_nomme_avant_toute_ecriture(base, c5):
    material, bon, receipt = _entrees()
    history = []
    options = {}
    if c5 == "details":
        options["details_reception"] = [{"materiau_id": material, "statut_ligne": "conforme"}]
    else:
        options["lieu_livraison"] = {"type": "depot"}

    response = m6_outils.receptionner_commande(
        bon, receipt, registre_historique=history, **options
    )

    assert response["accepte"] is False
    assert response["verdict"]["code"] == "REJ-M6-TRANSACTION-REQUISE"
    assert history == []


def test_reception_directe_historique_sans_options_c5_reste_compatible(base):
    material, bon, receipt = _entrees()
    history = []
    response = m6_outils.receptionner_commande(bon, receipt, registre_historique=history)

    assert response["accepte"] is True
    assert len(response["registre_historique"]) == 1
    assert response["registre_historique"][0]["materiau_id"] == material
    assert history == []
