"""Revue adverse (num) : la quantité à commander et la quantité suggérée se calculent en décimal EXACT.

Défaut trouvé : `calculer_lignes_a_commander` (estimé − stock disponible) et `reorder.evaluer_reorder` (seuil − stock)
soustrayaient des float : 10,3 − 3,1 donnait 7,200000000000001 comme quantité DEMANDÉE du bon de commande. Recevoir
exactement 7,2 (ce qu'on pensait commander) était alors une réception « inférieure » (écart de −8,9e-16) et le bon
de commande ne se complétait jamais. Les écarts se calculent en `Decimal(str(x))` comme les stocks (`stock.py`) ; la
sortie reste un float, celui du nombre décimal le plus proche du résultat exact. Données fictives.
"""

from __future__ import annotations

import pytest
from m6_material_control import bons_commande, fournisseurs, livre_prix, reorder
from m6_material_control.reception import traiter_reception
from m6_material_control.registre import Registre

CONDITIONS_PO = {"date_requise": "2099-12-31", "mode_livraison": "ramassage"}

FICTIF = True


def _registre(quantite_en_stock):
    registre = Registre()
    registre.ajouter({"type_mouvement": "RECEPTION", "chantier_id": "C1", "materiau_id": "M1",
                      "quantite": quantite_en_stock, "cout_unitaire": 1.0})
    return registre


@pytest.mark.parametrize("estimee, stock, attendu", [
    (10.3, 3.1, 7.2), (0.3, 0.1, 0.2), (1.1, 0.1, 1.0), (2.675, 1.005, 1.67), (4.35, 0.15, 4.2), (7.0, 2.5, 4.5),
])
def test_la_quantite_a_commander_est_l_ecart_decimal_exact(estimee, stock, attendu):
    lignes = bons_commande.calculer_lignes_a_commander(
        [{"materiau_id": "M1", "quantite_estimee": estimee, "unite": "u"}], "C1", _registre(stock))
    assert lignes == [{"materiau_id": "M1", "quantite_nette": attendu, "unite": "u"}]


@pytest.mark.parametrize("estimee, stock", [(10.3, 10.3), (0.3, 0.3), (3.0, 3.5), (1.1, 1.1000000000000001)])
def test_un_materiau_deja_couvert_n_a_pas_de_ligne(estimee, stock):
    assert bons_commande.calculer_lignes_a_commander(
        [{"materiau_id": "M1", "quantite_estimee": estimee, "unite": "u"}], "C1", _registre(stock)) == []


def test_recevoir_exactement_ce_qui_etait_a_commander_est_une_reception_conforme():
    lignes = bons_commande.calculer_lignes_a_commander(
        [{"materiau_id": "M1", "quantite_estimee": 10.3, "unite": "u"}], "C1", _registre(3.1))
    fournisseurs_registre: list[dict] = []
    fournisseurs.enregistrer_fournisseur(
        "gentek", "Gentek", "2026-01-01T00:00:00Z", fournisseurs_registre, courriel_commande="c@exemple-fictif.test")
    prix: list[dict] = []
    livre_prix.enregistrer_prix("M1", "gentek", 2.0, "CAD", "2026-01-01", prix)
    po, verdict = bons_commande.creer_brouillon(
        "PO-1", "C1", "gentek", lignes, "2026-01-02T00:00:00Z", [], prix, fournisseurs_registre,
        conditions=CONDITIONS_PO)
    assert verdict is None and po["lignes"][0]["quantite_demandee"] == 7.2 and po["montant_total_prevu"] == 14.4
    bon = bons_commande.construire_bon_demande(po)
    recu = {"po_id": "PO-1", "chantier_id": "C1", "lignes_recues": [{"materiau_id": "M1", "quantite_recue": 7.2}],
            "horodatage": "2026-01-03T00:00:00Z"}
    accuse = traiter_reception(bon, recu, None, Registre())
    assert accuse["verdict_reception"] == "CONFORME" and accuse["lignes"][0]["ecart"] == 0.0


@pytest.mark.parametrize("seuil, stock, attendu", [(10.3, 3.1, 7.2), (0.3, 0.1, 0.2), (5.0, 1.5, 3.5)])
def test_la_quantite_suggeree_du_reapprovisionnement_est_exacte(seuil, stock, attendu):
    signal = reorder.evaluer_reorder(
        "C1", "M1", [{"chantier_id": "C1", "materiau_id": "M1", "seuil_quantite": seuil}], _registre(stock))
    assert signal is not None and signal["quantite_suggeree"] == attendu


def test_stock_egal_au_seuil_ne_signale_rien():
    assert reorder.evaluer_reorder(
        "C1", "M1", [{"chantier_id": "C1", "materiau_id": "M1", "seuil_quantite": 0.3}], _registre(0.3)) is None


@pytest.mark.parametrize("demandee, recue, attendu, verdict", [
    (3.0, 3.3, 0.3, "RECEPTION_SUPERIEURE"), (10.3, 7.2, -3.1, "RECEPTION_INFERIEURE"),
    (0.3, 0.3, 0.0, "CONFORME"), (1.1, 1.0, -0.1, "RECEPTION_INFERIEURE"),
])
def test_l_ecart_de_reception_est_exact(demandee, recue, attendu, verdict):
    bon = {"po_id": "PO-1", "chantier_id": "C1",
           "lignes_demandees": [{"materiau_id": "M1", "quantite_demandee": demandee}],
           "horodatage": "2026-01-01T00:00:00Z"}
    recu_po = {"po_id": "PO-1", "chantier_id": "C1", "lignes_recues": [{"materiau_id": "M1", "quantite_recue": recue}],
               "horodatage": "2026-01-02T00:00:00Z"}
    accuse = traiter_reception(bon, recu_po, None, Registre())
    assert accuse["lignes"][0]["ecart"] == attendu and accuse["verdict_reception"] == verdict
