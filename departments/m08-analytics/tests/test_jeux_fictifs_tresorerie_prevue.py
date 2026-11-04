"""C5 : les constats de trésorerie prévue du jeu fictif doivent être CONFORMES au catalogue.

Le jeu sert de données de démonstration et de base aux wallboards/qualité : un constat hors schéma y ferait passer une
donnée forgée pour la réalité. Le minimum de la série est calculé en `Decimal`, jamais par l'ordre des chaînes
(`"100000.00"` est lexicalement plus petit que `"15685.02"` mais lui est numériquement supérieur). Fictif.
"""

from __future__ import annotations

from m8_analytics import jeux_fictifs, operations_recues

from opsys.evenements.schemas import erreurs_charge

FICTIF = True


def _constats():
    faits = [
        fait
        for fait in jeux_fictifs.operations_fictives("2026-10-30")
        if fait.get("type_entree") == operations_recues.TYPE_TRESORERIE_PREVUE
    ]
    assert len(faits) == 2
    return faits


def test_les_constats_fictifs_de_tresorerie_prevue_sont_conformes_au_catalogue():
    for fait in _constats():
        charge = {k: v for k, v in fait.items() if k not in ("type_entree", "provenance", "publie_le")}
        assert erreurs_charge("m5.tresorerie_prevue_constatee", charge) == []


def test_le_minimal_fictif_est_calcule_en_decimal_pas_par_ordre_lexicographique():
    constat = next(fait for fait in _constats() if fait["sequence"] == 2)
    assert "100000.00" in [ligne["solde_fin_cad"] for ligne in constat["soldes_hebdo"]]
    assert constat["solde_minimal_prevu_cad"] == "15685.02"
    assert constat["semaine_solde_minimal"] == 2
