"""Fail closed ciblé sur l'incohérence AP explicitement détectée par le module pur."""
from __future__ import annotations

from contextlib import suppress

import pytest
from sqlalchemy import insert

from opsys import stockage
from opsys.stockage.codec import encoder
from opsys.stockage.schema import REGISTRES


@pytest.fixture
def public(tmp_path, monkeypatch, m5_test_helpers):
    gl = m5_test_helpers
    fixture = gl.base_durable._fixture_function(tmp_path, monkeypatch)
    url = next(fixture)
    tools = {outil.nom: outil for outil in gl.m5_outils.outils()}
    try:
        yield tools, url
    finally:
        with suppress(StopIteration):
            next(fixture)
        stockage.liberer(url)


def _annulation_orpheline():
    return {
        "type_entree": "annulation_facture_fournisseur",
        "modification_id": "apm-fictif000000000000",
        "facture_fournisseur_id": "apf-inexistante000000",
        "motif": "motif fictif", "annule_par": "nathan.fictif",
        "role": "nathan_owner", "voie": "approbation", "avant": {},
        "horodatage": "2026-10-25T10:00:00-04:00",
    }


def test_type_dedie_preserve_heritage_runtime_error(m5_test_helpers):
    gl = m5_test_helpers
    with pytest.raises(gl.m5_outils.comptes_a_payer.RegistreComptesIncoherent) as raised:
        gl.m5_outils.comptes_a_payer._etats_factures([_annulation_orpheline()])
    assert isinstance(raised.value, RuntimeError)


def test_rapprochement_refuse_ap_incoherent_avec_verdict_structure(public, m5_test_helpers):
    gl = m5_test_helpers
    tools, url = public
    reg = gl.m5_outils.registre_module.Registre()
    reg.ajouter(_annulation_orpheline())
    with stockage.transaction(url) as cnx:
        cnx.execute(insert(REGISTRES).values(
            departement="m05-financecore", registre="comptes_a_payer", rang=0,
            maillon=encoder(reg.lire()[0]),
        ))
    response = gl._appeler(tools, "m5_rapprocher_grand_livre", gl.OCTOBRE)
    assert response["ok"] is True, response
    assert response["resultat"]["accepte"] is False
    assert response["resultat"]["verdict"]["code"] == "REJ-GL-SOURCE-ILLISIBLE"
    assert "resultat" not in response["resultat"]


def test_exception_runtime_non_classee_n_est_pas_masquee(public, monkeypatch, m5_test_helpers):
    gl = m5_test_helpers
    tools, _url = public

    def erreur_programmation(*_args, **_kwargs):
        raise RuntimeError("erreur interne fictive")

    monkeypatch.setattr(gl.m5_outils, "_factures_fournisseurs_vivantes", erreur_programmation)
    with pytest.raises(RuntimeError, match="erreur interne fictive"):
        gl._appeler(tools, "m5_rapprocher_grand_livre", gl.OCTOBRE)
