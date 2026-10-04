"""Reprise des identifiants métier Unicode; facture et sources entièrement fictives."""

from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

from m5_financecore import comptes_a_payer, registre

from opsys import stockage
from opsys.console import fusion_ap_m5

FICTIF = True
_SPEC = importlib.util.spec_from_file_location(
    "fixture_saisie_unicode", Path(__file__).with_name("test_fusion_ap_m5_saisie.py"),
)
assert _SPEC is not None and _SPEC.loader is not None
_BASE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_BASE)
ap_m5_saisie = _BASE.ap_m5_saisie


def test_saisie_et_rejeu_conservent_po_et_fournisseur_unicode(ap_m5_saisie):
    po_id, fournisseur_id = "PO-FICTIF-épreuve", "fournisseur-fictif-éprouvé"
    with stockage.transaction():
        reg = registre.Registre(maillons=stockage.maillons("m05-financecore", "comptes_a_payer"))
        entree = copy.deepcopy(reg.lire()[0])
        entree.update(evenement_id="réception-unicode-fictive", po_id=po_id, fournisseur_id=fournisseur_id)
        assert comptes_a_payer.enregistrer_reception(entree, reg)[1] is None
    contexte = ap_m5_saisie
    observation = fusion_ap_m5.verifier(
        stockage.transaction, contexte["acteur"], contexte["pdf"]["lot_id"],
        revision_pdf=contexte["pdf"]["revision"], revision_ap=contexte["brouillon"]["revision"],
        po_id=po_id, fournisseur_id=fournisseur_id, correspondance_confirmee=True,
    )
    recu = _BASE._saisir(contexte, observation, po_id=po_id, fournisseur_id=fournisseur_id)
    avant_rejeu = _BASE._FIXTURE._tables()
    rejoue = _BASE._saisir(contexte, observation, po_id=po_id, fournisseur_id=fournisseur_id)
    assert rejoue == {**recu, "rejoue": True}
    assert _BASE._FIXTURE._tables() == avant_rejeu

    from opsys.console import fusion_ap_m5_reference

    assert fusion_ap_m5_reference.lire(
        stockage.transaction, contexte["acteur"], contexte["pdf"]["lot_id"],
    ) == {
        "facture_id": recu["facture_id"], "approbation_id": recu["approbation_id"],
        "statut_m5": "SAISIE", "corrections": 0,
    }
    assert _BASE._FIXTURE._tables() == avant_rejeu
