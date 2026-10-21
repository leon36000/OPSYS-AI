"""Saisie Fusion AP -> M5 : fixture SQLite/PDF/M5 réelle, données factices isolées."""

from __future__ import annotations

import base64
import importlib.util
from pathlib import Path

import pytest
from m5_financecore import outils as outils_m5
from sqlalchemy import select

from opsys import fusion_ap, stockage
from opsys.console import fusion_ap_m5, fusion_ap_m5_saisie
from opsys.departements import charger_departements
from opsys.stockage.schema import APPROBATIONS, FUSION_AP_SAISIES, REGISTRES

_SPEC = importlib.util.spec_from_file_location(
    "fixture_fusion_ap_m5_saisie", Path(__file__).with_name("test_fusion_ap_m5.py"),
)
assert _SPEC is not None and _SPEC.loader is not None
_FIXTURE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_FIXTURE)


@pytest.fixture
def ap_m5_saisie(request, monkeypatch, tmp_path):
    monkeypatch.setenv("OPSYS_INGESTION_CLE", base64.b64encode(b"v" * 32).decode())
    return _FIXTURE.ap_m5.__wrapped__(request.getfixturevalue("nathan"), monkeypatch, tmp_path)


def _resultat(ctx):
    return fusion_ap_m5.verifier(
        stockage.transaction, ctx["acteur"], ctx["pdf"]["lot_id"],
        revision_pdf=ctx["pdf"]["revision"], revision_ap=ctx["brouillon"]["revision"],
        po_id="PO-FICTIF-7", fournisseur_id="fournisseur-fictif", correspondance_confirmee=True,
    )


def _saisir(ctx, resultat=None, **overrides):
    resultat = _resultat(ctx) if resultat is None else resultat
    args = {
        "revision_pdf": ctx["pdf"]["revision"], "revision_ap": ctx["brouillon"]["revision"],
        "po_id": "PO-FICTIF-7", "fournisseur_id": "fournisseur-fictif",
        "correspondance_confirmee": True, "saisie_confirmee": True,
        "snapshot_attendu": resultat["commande_sha256"], "mutation_id": "fusion-ap-saisie-1",
        "deps": charger_departements(),
    }
    args.update(overrides)
    return fusion_ap_m5_saisie.saisir(
        stockage.transaction, ctx["acteur"], ctx["pdf"]["lot_id"], **args,
    )


def _compter_registre():
    with stockage.transaction() as cnx:
        return cnx.execute(select(REGISTRES.c.rang).where(
            (REGISTRES.c.departement == "m05-financecore")
            & (REGISTRES.c.registre == "comptes_a_payer")
        )).all()


def test_confirmation_cree_une_saisie_m5_n3_et_rejoue_sans_second_append(ap_m5_saisie):
    avant = len(_compter_registre())
    resultat = _resultat(ap_m5_saisie)
    recu = _saisir(ap_m5_saisie, resultat)
    assert recu["statut"] == "SAISIE_M5_REFERENCEE" and recu["rejoue"] is False
    assert len(_compter_registre()) == avant + 1
    with stockage.transaction() as cnx:
        liaison = cnx.execute(select(FUSION_AP_SAISIES).where(
            FUSION_AP_SAISIES.c.lot_id == ap_m5_saisie["pdf"]["lot_id"],
        )).mappings().one()
        approval = cnx.execute(select(APPROBATIONS).where(
            APPROBATIONS.c.id == recu["approbation_id"],
        )).mappings().one()
    assert liaison["facture_id"] == recu["facture_id"]
    assert liaison["commande_sha256"] == resultat["commande_sha256"]
    assert approval["statut"] == "executee" and approval["niveau"] == "N3"
    rejoue = _saisir(ap_m5_saisie, resultat)
    assert rejoue == {**recu, "rejoue": True}
    assert len(_compter_registre()) == avant + 1


@pytest.mark.parametrize("champ", ["correspondance_confirmee", "saisie_confirmee"])
def test_double_confirmation_est_requise_sans_ecriture(ap_m5_saisie, champ):
    resultat = _resultat(ap_m5_saisie)
    avant = len(_compter_registre())
    with pytest.raises(fusion_ap.FusionAPErreur) as refus:
        _saisir(ap_m5_saisie, resultat, **{champ: False})
    assert refus.value.statut_http == 400
    assert len(_compter_registre()) == avant


def test_snapshot_obsolete_ou_second_identifiant_de_mutation_ne_saisit_pas(ap_m5_saisie):
    resultat = _resultat(ap_m5_saisie)
    with pytest.raises(fusion_ap.FusionAPErreur):
        _saisir(ap_m5_saisie, resultat, snapshot_attendu="0" * 64)
    _saisir(ap_m5_saisie, resultat)
    avant = len(_compter_registre())
    with pytest.raises(fusion_ap.FusionAPErreur):
        _saisir(ap_m5_saisie, resultat, mutation_id="autre-cle")
    assert len(_compter_registre()) == avant


def test_reponse_m5_sans_append_declenche_rollback_complet(ap_m5_saisie, monkeypatch):
    monkeypatch.setattr(outils_m5, "saisir_facture_fournisseur", lambda **_: {"accepte": True, "resultat": {}})
    resultat = _resultat(ap_m5_saisie)
    before = _FIXTURE._tables()
    with pytest.raises(fusion_ap.FusionAPErreur):
        _saisir(ap_m5_saisie, resultat)
    assert _FIXTURE._tables() == before
