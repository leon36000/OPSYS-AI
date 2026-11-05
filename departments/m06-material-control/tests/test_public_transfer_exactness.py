from __future__ import annotations

from dataclasses import replace
from decimal import localcontext

import pytest
import test_review_rebut_consumption_stock_mismatch as fx

from opsys import stockage
from opsys.capacites import Capacites
from opsys.departements import charger_departements

M6 = "m06-material-control"


def _cap():
    deps = charger_departements()
    deps[M6] = replace(deps[M6], mode="supervise")
    return Capacites(deps, stockage.transaction, filtre={M6}, appelant=M6, memoire=False)


def _recevoir(cap, materiau, chantier, quantite, suffix):
    po = f"PO-public-decimal-{suffix}"
    date = "2026-11-05T10:00:00-04:00"
    return cap.appeler("m6_receptionner_commande", {
        "bon_demande": {
            "po_id": po, "chantier_id": chantier,
            "lignes_demandees": [{"materiau_id": materiau, "quantite_demandee": quantite}],
            "horodatage": date,
        },
        "reception_po": {
            "po_id": po, "chantier_id": chantier,
            "lignes_recues": [{"materiau_id": materiau, "quantite_recue": quantite}],
            "horodatage": date,
        },
        "catalogue_materiaux": {
            "version": "v1", "unite_monetaire": "CAD",
            "postes": {materiau: {"cout_unitaire": 5.0, "libelle": "Article fictif"}},
        },
        "details_reception": [{"materiau_id": materiau, "statut_ligne": "conforme"}],
        "lieu_livraison": {"type": "depot"},
    })


def test_capacites_public_transfer_05_records_exact_before_after(base):
    materiau = "mat-public-transfer-decimal-fictif"
    chantier = "CH-public-transfer-decimal-fictif"
    cap = _cap()

    first = _recevoir(cap, materiau, chantier, 0.1, "fraction")
    second = _recevoir(cap, materiau, chantier, 10**28, "large")
    assert first["ok"] and first["resultat"]["accepte"] is True, str(first)[:500]
    assert second["ok"] and second["resultat"]["accepte"] is True, str(second)[:500]

    transfer = cap.appeler("m6_transferer_stock", {
        "transfert_id": "T-public-transfer-decimal-fictif",
        "materiau_id": materiau,
        "quantite": 0.05,
        "de": {"type": "depot"},
        "vers": {"type": "chantier", "reference": chantier},
        "motif": "Transfert décimal fictif",
        "horodatage": "2026-11-05T11:00:00-04:00",
    })
    assert transfer["ok"] and transfer["resultat"]["accepte"] is True, str(transfer)[:500]

    with stockage.transaction():
        chain = list(stockage.maillons(M6, "emplacements"))
    relevant = [m for m in chain if m.get("materiau_id") == materiau]
    c5_large = next(m for m in relevant if m["quantite"] == str(10**28))
    explicit = next(m for m in relevant if m.get("transfert_id") == "T-public-transfer-decimal-fictif")
    observed = {
        "c5_large_apres": c5_large["apres"],
        "transfer_avant": explicit["avant"],
        "transfer_apres": explicit["apres"],
    }
    expected = {
        "c5_large_apres": {"de": "0", "vers": "10000000000000000000000000000.1"},
        "transfer_avant": {"de": "10000000000000000000000000000.1", "vers": "0"},
        "transfer_apres": {"de": "10000000000000000000000000000.05", "vers": "0.05"},
    }
    assert observed == expected, observed


@pytest.mark.parametrize("precision", [28, 40])
def test_public_c5_large_then_fraction_keeps_fraction_and_context_invariant(base, precision):
    material = f"mat-public-c5-order-{precision}-fictif"
    project = f"CH-public-c5-order-{precision}-fictif"
    with localcontext() as contexte_decimal:
        contexte_decimal.prec = precision
        large = fx._recevoir_quantite(material, project, 10**28, statut="conforme", suffix=f"large-{precision}")
        fraction = fx._recevoir_quantite(material, project, 0.1, statut="conforme", suffix=f"fraction-{precision}")
        assert large["ok"] and large["resultat"]["accepte"] is True, large
        assert fraction["ok"] and fraction["resultat"]["accepte"] is True, fraction
        lecture = fx.executer_atomique(fx._outil("m6_lire_disponibilite"), {"materiau_ids": [material]})

    assert lecture["ok"] and lecture["resultat"]["accepte"] is True, lecture
    article = lecture["resultat"]["resultat"]["articles"][0]
    assert article["stock_theorique"] == "10000000000000000000000000000.1"
    assert article["par_emplacement"] == {"depot": "10000000000000000000000000000.1", "inconnu": "0"}
