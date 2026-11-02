"""Revue adverse (num) : les montants de ligne d'un bon de commande et d'un accusé de réception sont au CENT.

Défaut trouvé : `prix_unitaire * quantite` se faisait en flottant, sans arrondi (le contrat M6 garde des float, mais
un montant n'est jamais du bruit binaire) : 4,35 $ × 100 donnait 434,99999999999994 $ au bon de commande que la
personne approuve ; 0,1 $ × 3 donnait 0,30000000000000004 $. Une quantité démesurée donnait `inf`, qu'aucune
sérialisation JSON ne porte. Les montants de ligne se calculent maintenant en décimal exact (`Decimal(str(x))`), au cent
(ROUND_HALF_UP), et un montant hors du domaine monétaire de M5 (999 999 999 999,99 $) est refusé. Données fictives.
"""

from __future__ import annotations

import json

import pytest
from m6_material_control import bons_commande, contrats_sortie, fournisseurs, livre_prix
from m6_material_control.reception import traiter_reception

CONDITIONS_PO = {"date_requise": "2099-12-31", "mode_livraison": "ramassage"}

FICTIF = True


def _po(prix, quantite, po_id="PO-NUM-1", registre_po=None):
    fournisseurs_registre: list[dict] = []
    fournisseurs.enregistrer_fournisseur(
        "gentek", "Gentek", "2026-01-01T00:00:00Z", fournisseurs_registre, courriel_commande="c@exemple-fictif.test")
    prix_registre: list[dict] = []
    livre_prix.enregistrer_prix("MAT-1", "gentek", prix, "CAD", "2026-01-01", prix_registre)
    registre_po = [] if registre_po is None else registre_po
    reponse = bons_commande.creer_brouillon(
        po_id, "C1", "gentek", [{"materiau_id": "MAT-1", "quantite_nette": quantite,
                                 "unite": "boite"}], "2026-01-02T00:00:00Z",
        registre_po, prix_registre, fournisseurs_registre, conditions=CONDITIONS_PO)
    return reponse, registre_po


@pytest.mark.parametrize("prix, quantite, attendu", [
    (4.35, 100, 435.0), (0.1, 3, 0.3), (1.1, 3, 3.3), (19.99, 3, 59.97), (0.07, 100, 7.0),
    (2.5, 3.333, 8.33),  # 8,3325 : le troisième chiffre décimal est 2, donc 8,33
    (0.5, 0.01, 0.01),  # 0,005 : un demi-cent monte (ROUND_HALF_UP, comme le reste de M5)
    (0.01, 0.49, 0.0),  # 0,0049 : sous le demi-cent
    (10.0, 5.0, 50.0),
    (1.005, 1, 1.01),  # le float 1.005 vaut 1,00499999… en binaire : c'est sa représentation décimale qui compte
    (2.675, 1, 2.68),
])
def test_le_montant_de_ligne_du_bon_de_commande_est_exact_au_cent(prix, quantite, attendu):
    (po, verdict), registre = _po(prix, quantite)
    assert verdict is None, verdict
    assert po["lignes"][0]["montant_ligne_prevu"] == attendu
    assert po["montant_total_prevu"] == attendu
    assert json.loads(json.dumps(po))["montant_total_prevu"] == attendu


def test_le_total_de_plusieurs_lignes_est_la_somme_exacte_des_montants_de_ligne():
    fournisseurs_registre: list[dict] = []
    fournisseurs.enregistrer_fournisseur(
        "gentek", "Gentek", "2026-01-01T00:00:00Z", fournisseurs_registre, courriel_commande="c@exemple-fictif.test")
    prix_registre: list[dict] = []
    for materiau, prix in (("MAT-1", 0.1), ("MAT-2", 0.2), ("MAT-3", 4.35)):
        livre_prix.enregistrer_prix(materiau, "gentek", prix, "CAD", "2026-01-01", prix_registre)
    lignes = [{"materiau_id": "MAT-1", "quantite_nette": 3, "unite": "u"}, {"materiau_id": "MAT-2",
                                                                            "quantite_nette": 3, "unite": "u"},
              {"materiau_id": "MAT-3", "quantite_nette": 100, "unite": "u"}]
    po, verdict = bons_commande.creer_brouillon(
        "PO-NUM-2", "C1", "gentek", lignes, "2026-01-02T00:00:00Z", [], prix_registre, fournisseurs_registre,
        conditions=CONDITIONS_PO)
    assert verdict is None
    assert [ligne["montant_ligne_prevu"] for ligne in po["lignes"]] == [0.3, 0.6, 435.0]
    assert po["montant_total_prevu"] == 435.9  # 0,3 + 0,6 + 435 en flottant donnerait 435.90000000000003


def test_rejouer_la_creation_est_toujours_un_no_op_idempotent():
    (premier, _), registre = _po(4.35, 100)
    (second, verdict), _ = _po(4.35, 100, registre_po=registre)
    assert verdict is None and second == premier and len(registre) == 1


@pytest.mark.parametrize("prix, quantite", [
    (1e300, 1e300), (10.0, 1e308), (1.0, 1e12), (1e9, 1e4),
    (0.5, 1999999999999.99),  # 999 999 999 999,995 : l'arrondi au cent monte à 1 000 000 000 000,00, hors domaine
])
def test_un_montant_hors_du_domaine_monetaire_est_refuse_et_rien_n_est_ecrit(prix, quantite):
    (po, verdict), registre = _po(prix, quantite)
    assert po is None and verdict["code"] == "REJ-PO-LIGNE-INVALIDE"
    assert "domaine" in verdict["detail"]
    assert registre == []


def test_le_total_de_deux_lignes_est_exact():
    fournisseurs_registre: list[dict] = []
    fournisseurs.enregistrer_fournisseur(
        "gentek", "Gentek", "2026-01-01T00:00:00Z", fournisseurs_registre, courriel_commande="c@exemple-fictif.test")
    prix_registre: list[dict] = []
    for materiau, prix in (("MAT-1", 0.1), ("MAT-2", 0.2)):
        livre_prix.enregistrer_prix(materiau, "gentek", prix, "CAD", "2026-01-01", prix_registre)
    lignes = [{"materiau_id": "MAT-1", "quantite_nette": 1, "unite": "u"}, {"materiau_id": "MAT-2",
                                                                            "quantite_nette": 1, "unite": "u"}]
    po, verdict = bons_commande.creer_brouillon(
        "PO-NUM-3", "C1", "gentek", lignes, "2026-01-02T00:00:00Z", [], prix_registre, fournisseurs_registre,
        conditions=CONDITIONS_PO)
    assert verdict is None and po["montant_total_prevu"] == 0.3  # 0.1 + 0.2 = 0.30000000000000004 en flottant


def test_la_limite_du_domaine_reste_permise():
    (po, verdict), _ = _po(999999999999.99, 1)
    assert verdict is None and po["montant_total_prevu"] == 999999999999.99


def _reception(cout, quantite):
    bon = {"po_id": "PO-1", "chantier_id": "C1", "lignes_demandees": [{"materiau_id": "BETON",
           "quantite_demandee": quantite}], "horodatage": "2026-01-01T08:00:00Z"}
    recu = {"po_id": "PO-1", "chantier_id": "C1", "lignes_recues": [{"materiau_id": "BETON",
            "quantite_recue": quantite}], "horodatage": "2026-01-02T08:00:00Z"}
    catalogue = {"version": "2026.01", "unite_monetaire": "CAD", "postes": {"BETON": {"cout_unitaire": cout,
                 "libelle": "Béton"}}}
    return traiter_reception(bon, recu, catalogue, type("R", (), {"lire": lambda self: []})())


@pytest.mark.parametrize("cout, quantite, attendu", [(4.35, 100, 435.0), (0.1, 3, 0.3), (19.99, 3, 59.97)])
def test_le_montant_de_ligne_de_l_accuse_de_reception_est_exact_au_cent(cout, quantite, attendu):
    accuse = _reception(cout, quantite)
    assert accuse["lignes"][0]["montant_ligne"] == attendu
    assert accuse["montant_total_estime"] == attendu


def test_le_total_de_l_accuse_de_deux_lignes_est_exact():
    bon = {"po_id": "PO-1", "chantier_id": "C1", "lignes_demandees": [
        {"materiau_id": "A", "quantite_demandee": 1}, {"materiau_id": "B", "quantite_demandee": 1}],
        "horodatage": "2026-01-01T08:00:00Z"}
    recu = {"po_id": "PO-1", "chantier_id": "C1", "lignes_recues": [
        {"materiau_id": "A", "quantite_recue": 1}, {"materiau_id": "B", "quantite_recue": 1}],
        "horodatage": "2026-01-02T08:00:00Z"}
    catalogue = {"version": "2026.01", "unite_monetaire": "CAD", "postes": {
        "A": {"cout_unitaire": 0.1, "libelle": "A"}, "B": {"cout_unitaire": 0.2, "libelle": "B"}}}
    accuse = traiter_reception(bon, recu, catalogue, type("R", (), {"lire": lambda self: []})())
    assert accuse["montant_total_estime"] == 0.3


def test_un_montant_d_accuse_hors_domaine_est_indetermine_jamais_infini():
    accuse = _reception(1e300, 1e300)
    assert accuse["lignes"][0]["montant_ligne"] is None and accuse["montant_total_estime"] is None
    json.dumps(accuse, allow_nan=False)  # sérialisable


def test_montant_ligne_au_cent_helper():
    assert contrats_sortie.montant_ligne_au_cent(4.35, 100) == 435.0
    assert contrats_sortie.montant_ligne_au_cent(0.1, 3) == 0.3
    assert contrats_sortie.montant_ligne_au_cent(1e300, 1e300) is None
    assert contrats_sortie.montant_ligne_au_cent(float("inf"), 1) is None
    assert contrats_sortie.montant_ligne_au_cent(True, 1) is None
    assert contrats_sortie.montant_ligne_au_cent(2, 3) == 6.0
    assert contrats_sortie.montant_ligne_au_cent(0.5, 1999999999999.99) is None
    assert contrats_sortie.montant_ligne_au_cent(1.005, 1) == 1.01
    assert contrats_sortie.somme_montants_au_cent([0.1, 0.2]) == 0.3
    assert contrats_sortie.somme_montants_au_cent([]) == 0.0
