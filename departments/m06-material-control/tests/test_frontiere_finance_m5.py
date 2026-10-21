"""Frontière M6 -> M5 : les montants M6 sont des float (contrat gelé §2.6/§2.8)
alors que M5-FinanceCore exige un Decimal fini (CA-M5-01). Bug NEW-PROD corrigé
ici : fournir la conversion sûre `Decimal(str(x))` (jamais `Decimal(x)`, qui
importerait l'imprécision binaire du float) et prouver, par un test inter-
départements, qu'un SignalPoAPayer converti est bien accepté par le vrai
validateur M5. Aucune modification de m5_financecore : ce test lit seulement
son code réel (permis par la mission, qui porte les deux départements) — le
paquet m6_material_control n'importe jamais m5_financecore en dehors des tests
(#109).
"""

from decimal import Decimal

import pytest
from m6_material_control.contrats_sortie import montant_decimal_a_la_frontiere


def test_conversion_utilise_la_representation_texte_jamais_le_binaire_du_float():
    """0.1 + 0.2 en float n'est PAS 0.3 exactement (imprécision binaire). La
    conversion doit passer par str() pour ne jamais importer cette erreur."""
    resultat = montant_decimal_a_la_frontiere(0.1)

    assert resultat == Decimal("0.1")
    assert resultat != Decimal(0.1)  # Decimal(float) directement serait faux.


def test_conversion_accepte_un_montant_entier():
    assert montant_decimal_a_la_frontiere(100) == Decimal("100")


def test_conversion_rejette_un_booleen():
    with pytest.raises(TypeError):
        montant_decimal_a_la_frontiere(True)


def test_conversion_rejette_un_montant_non_numerique():
    with pytest.raises(TypeError):
        montant_decimal_a_la_frontiere("100.0")


def test_conversion_rejette_un_montant_non_fini():
    with pytest.raises(ValueError):
        montant_decimal_a_la_frontiere(float("inf"))
    with pytest.raises(ValueError):
        montant_decimal_a_la_frontiere(float("nan"))


def test_signal_po_a_payer_converti_est_accepte_par_le_vrai_validateur_m5():
    """Test inter-départements M6 -> M5 : un SignalPoAPayer réel (produit par
    materiel.enregistrer_reception), une fois son montant converti à la
    frontière, doit former un MouvementFinancier accepté par
    m5_financecore.validation.valider_mouvement (le VRAI validateur M5, jamais
    réécrit ni simulé)."""
    from m5_financecore import validation as validation_m5
    from m6_material_control import materiel
    from m6_material_control.registre import Registre

    registre_m6 = Registre()
    bon_demande = {
        "po_id": "PO-900",
        "chantier_id": "CHANTIER-9",
        "lignes_demandees": [{"materiau_id": "MAT-9", "quantite_demandee": 3.0}],
        "horodatage": "2026-01-01T08:00:00Z",
    }
    reception_po = {
        "po_id": "PO-900",
        "chantier_id": "CHANTIER-9",
        "lignes_recues": [{"materiau_id": "MAT-9", "quantite_recue": 3.0}],
        "horodatage": "2026-01-02T08:00:00Z",
    }
    catalogue = {
        "version": "2026.01",
        "unite_monetaire": "CAD",
        "postes": {"MAT-9": {"cout_unitaire": 100.0, "libelle": "Matériau 9"}},
    }

    resultat, code = materiel.enregistrer_reception(bon_demande, reception_po, catalogue, registre_m6)
    assert code is None
    signal = resultat["signal_po_a_payer"]
    assert signal is not None

    montant_decimal = montant_decimal_a_la_frontiere(signal["montant_total_estime"])

    mouvement_m5 = {
        # Un paiement de PO est une sortie d'argent pour l'entreprise : signé
        # négativement, cohérent avec le contrôle de signe DECAISSEMENT de M5
        # (validation.py, REJ-MOUVEMENT-SIGNE-INCOHERENT).
        "montant": -montant_decimal,
        "type_mouvement": "DECAISSEMENT",
        "horodatage": "2026-01-02T09:00:00+00:00",
        "classe_retention": "STANDARD",
        "source": f"m6_material_control:po:{signal['po_id']}",
    }

    valide, verdict = validation_m5.valider_mouvement(mouvement_m5)

    assert valide is True
    assert verdict is None
    assert type(mouvement_m5["montant"]) is Decimal
    assert signal["montant_total_estime"] == 300.0
    assert mouvement_m5["montant"] == Decimal("-300.0")
