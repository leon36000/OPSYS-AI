"""Contrat public fictif : le refus de taux reste prioritaire après l'intégrité GL."""
from __future__ import annotations

from contextlib import suppress

import pytest
from sqlalchemy import select, update

from opsys import stockage
from opsys.stockage.codec import decoder, encoder
from opsys.stockage.schema import REGISTRES


@pytest.fixture
def public(tmp_path, monkeypatch, m5_test_helpers):
    helper = m5_test_helpers
    fixture = helper.base_durable._fixture_function(tmp_path, monkeypatch)
    url = next(fixture)
    helper.declare._fixture_function(tmp_path, monkeypatch)({"categories_depense_sans_po": ["carburant"]})
    tools = {outil.nom: outil for outil in helper.m5_outils.outils()}
    try:
        yield helper, tools, url
    finally:
        with suppress(StopIteration):
            next(fixture)
        stockage.liberer(url)


def test_refus_taux_precede_chaine_ap_secondaire_invalide(public, tmp_path, monkeypatch):
    helper, tools, url = public
    monkeypatch.setattr(
        helper.m5_outils,
        "_CHEMIN_PLAN_COMPTABLE",
        helper._RACINE_M5 / "contracts/plan_comptable_pme_qc.v1.yaml",
    )
    monkeypatch.setattr(
        helper.m5_outils,
        "_CHEMIN_TAUX_FISCAUX",
        helper._RACINE_M5 / "contracts/taux_fiscaux.v1.yaml",
    )
    created = helper._appeler(tools, "m5_saisir_facture_sans_po", {
        "fournisseur_id": "fournisseur-fictif",
        "categorie": "carburant",
        "numero_facture": "AP-TAUX-ORDRE-FICTIF",
        "date_facture": "2026-10-01",
        "montant_avant_taxes": "100.00",
        "total_facture": None,
        "horodatage": helper.SAISIE,
    }, helper.COMPTABLE)
    assert created["ok"] and created["resultat"]["accepte"], created

    with stockage.transaction(url) as cnx:
        texte = cnx.execute(select(REGISTRES.c.maillon).where(
            REGISTRES.c.departement == "m05-financecore",
            REGISTRES.c.registre == "comptes_a_payer",
            REGISTRES.c.rang == 0,
        )).scalar_one()
        maillon = decoder(texte)
        maillon["montant_avant_taxes"] = "900.00"
        cnx.execute(update(REGISTRES).where(
            REGISTRES.c.departement == "m05-financecore",
            REGISTRES.c.registre == "comptes_a_payer",
            REGISTRES.c.rang == 0,
        ).values(maillon=encoder(maillon)))

    taux_invalides = tmp_path / "taux-fictifs-invalides.yaml"
    taux_invalides.write_text("schema_version: 2\ntaux: []\n", encoding="utf-8")
    monkeypatch.setattr(helper.m5_outils, "_CHEMIN_TAUX_FISCAUX", taux_invalides)

    response = helper._appeler(tools, "m5_rapprocher_grand_livre", helper.OCTOBRE)
    assert response["ok"] is True
    assert response["resultat"]["accepte"] is False
    assert response["resultat"]["verdict"]["code"] == "REJ-TAUX-FICHIER-INVALIDE"
    assert "resultat" not in response["resultat"]
