import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m6_material_control.reception import traiter_reception


class RegistreVide:
    def __init__(self, entrees=None):
        self._entrees = [] if entrees is None else entrees

    def lire(self):
        return self._entrees


def test_reception_conforme_pour_deux_lignes_aux_quantites_identiques():
    bon_demande = {
        "po_id": "PO-001",
        "chantier_id": "CHANTIER-A",
        "lignes_demandees": [
            {"materiau_id": "BETON", "quantite_demandee": 10.0},
            {"materiau_id": "ACIER", "quantite_demandee": 5.0},
        ],
        "horodatage": "2025-01-01T08:00:00Z",
    }
    reception_po = {
        "po_id": "PO-001",
        "chantier_id": "CHANTIER-A",
        "lignes_recues": [
            {"materiau_id": "BETON", "quantite_recue": 10.0},
            {"materiau_id": "ACIER", "quantite_recue": 5.0},
        ],
        "horodatage": "2025-01-02T08:00:00Z",
    }
    catalogue = {
        "version": "2025.01",
        "unite_monetaire": "CAD",
        "postes": {"BETON": {"cout_unitaire": 100.0, "libelle": "BETON"}, "ACIER": {"cout_unitaire": 50.0, "libelle": "ACIER"}},
    }

    accuse = traiter_reception(bon_demande, reception_po, catalogue, RegistreVide())

    assert accuse["po_id"] == "PO-001"
    assert accuse["chantier_id"] == "CHANTIER-A"
    assert accuse["verdict_reception"] == "CONFORME"
    assert accuse["lignes"][0]["ecart"] == 0.0
    assert accuse["lignes"][1]["ecart"] == 0.0
    assert "hash_maillon" not in accuse


def test_reception_inferieure_lorsqu_une_ligne_est_strictement_inferieure():
    bon_demande = {
        "po_id": "PO-002",
        "chantier_id": "CHANTIER-A",
        "lignes_demandees": [
            {"materiau_id": "BETON", "quantite_demandee": 10.0},
            {"materiau_id": "ACIER", "quantite_demandee": 5.0},
        ],
        "horodatage": "2025-01-01T08:00:00Z",
    }
    reception_po = {
        "po_id": "PO-002",
        "chantier_id": "CHANTIER-A",
        "lignes_recues": [
            {"materiau_id": "BETON", "quantite_recue": 8.0},
            {"materiau_id": "ACIER", "quantite_recue": 5.0},
        ],
        "horodatage": "2025-01-02T08:00:00Z",
    }
    catalogue = {
        "version": "2025.01",
        "unite_monetaire": "CAD",
        "postes": {"BETON": {"cout_unitaire": 100.0, "libelle": "BETON"}, "ACIER": {"cout_unitaire": 50.0, "libelle": "ACIER"}},
    }

    accuse = traiter_reception(bon_demande, reception_po, catalogue, RegistreVide())

    assert accuse["verdict_reception"] == "RECEPTION_INFERIEURE"
    assert accuse["lignes"][0]["ecart"] == -2.0
    assert accuse["lignes"][1]["ecart"] == 0.0


def test_reception_superieure_lorsqu_une_ligne_est_strictement_superieure():
    bon_demande = {
        "po_id": "PO-003",
        "chantier_id": "CHANTIER-A",
        "lignes_demandees": [
            {"materiau_id": "BETON", "quantite_demandee": 10.0},
            {"materiau_id": "ACIER", "quantite_demandee": 5.0},
        ],
        "horodatage": "2025-01-01T08:00:00Z",
    }
    reception_po = {
        "po_id": "PO-003",
        "chantier_id": "CHANTIER-A",
        "lignes_recues": [
            {"materiau_id": "BETON", "quantite_recue": 10.0},
            {"materiau_id": "ACIER", "quantite_recue": 7.0},
        ],
        "horodatage": "2025-01-02T08:00:00Z",
    }
    catalogue = {
        "version": "2025.01",
        "unite_monetaire": "CAD",
        "postes": {"BETON": {"cout_unitaire": 100.0, "libelle": "BETON"}, "ACIER": {"cout_unitaire": 50.0, "libelle": "ACIER"}},
    }

    accuse = traiter_reception(bon_demande, reception_po, catalogue, RegistreVide())

    assert accuse["verdict_reception"] == "RECEPTION_SUPERIEURE"
    assert accuse["lignes"][0]["ecart"] == 0.0
    assert accuse["lignes"][1]["ecart"] == 2.0


def test_reception_mixte_lorsqu_une_ligne_est_inferieure_et_une_autre_superieure():
    bon_demande = {
        "po_id": "PO-004",
        "chantier_id": "CHANTIER-A",
        "lignes_demandees": [
            {"materiau_id": "BETON", "quantite_demandee": 10.0},
            {"materiau_id": "ACIER", "quantite_demandee": 5.0},
        ],
        "horodatage": "2025-01-01T08:00:00Z",
    }
    reception_po = {
        "po_id": "PO-004",
        "chantier_id": "CHANTIER-A",
        "lignes_recues": [
            {"materiau_id": "BETON", "quantite_recue": 8.0},
            {"materiau_id": "ACIER", "quantite_recue": 7.0},
        ],
        "horodatage": "2025-01-02T08:00:00Z",
    }
    catalogue = {
        "version": "2025.01",
        "unite_monetaire": "CAD",
        "postes": {"BETON": {"cout_unitaire": 100.0, "libelle": "BETON"}, "ACIER": {"cout_unitaire": 50.0, "libelle": "ACIER"}},
    }

    accuse = traiter_reception(bon_demande, reception_po, catalogue, RegistreVide())

    assert accuse["verdict_reception"] == "RECEPTION_MIXTE"
    assert accuse["lignes"][0]["ecart"] == -2.0
    assert accuse["lignes"][1]["ecart"] == 2.0


def test_reception_indeterminee_lorsque_le_po_id_ne_correspond_pas():
    bon_demande = {
        "po_id": "PO-005",
        "chantier_id": "CHANTIER-A",
        "lignes_demandees": [
            {"materiau_id": "BETON", "quantite_demandee": 10.0},
        ],
        "horodatage": "2025-01-01T08:00:00Z",
    }
    reception_po = {
        "po_id": "PO-AUTRE",
        "chantier_id": "CHANTIER-A",
        "lignes_recues": [
            {"materiau_id": "BETON", "quantite_recue": 10.0},
        ],
        "horodatage": "2025-01-02T08:00:00Z",
    }
    catalogue = {
        "version": "2025.01",
        "unite_monetaire": "CAD",
        "postes": {"BETON": {"cout_unitaire": 100.0, "libelle": "BETON"}},
    }

    accuse = traiter_reception(bon_demande, reception_po, catalogue, RegistreVide())

    assert accuse["verdict_reception"] == "INDETERMINE"


def test_reception_indeterminee_lorsqu_une_ligne_demandee_n_a_pas_de_reception():
    bon_demande = {
        "po_id": "PO-006",
        "chantier_id": "CHANTIER-A",
        "lignes_demandees": [
            {"materiau_id": "BETON", "quantite_demandee": 10.0},
            {"materiau_id": "ACIER", "quantite_demandee": 5.0},
        ],
        "horodatage": "2025-01-01T08:00:00Z",
    }
    reception_po = {
        "po_id": "PO-006",
        "chantier_id": "CHANTIER-A",
        "lignes_recues": [
            {"materiau_id": "BETON", "quantite_recue": 10.0},
        ],
        "horodatage": "2025-01-02T08:00:00Z",
    }
    catalogue = {
        "version": "2025.01",
        "unite_monetaire": "CAD",
        "postes": {"BETON": {"cout_unitaire": 100.0, "libelle": "BETON"}, "ACIER": {"cout_unitaire": 50.0, "libelle": "ACIER"}},
    }

    accuse = traiter_reception(bon_demande, reception_po, catalogue, RegistreVide())

    assert accuse["verdict_reception"] == "INDETERMINE"


def test_montant_total_estime_est_la_somme_exacte_lorsque_tous_les_prix_sont_resolus():
    bon_demande = {
        "po_id": "PO-007",
        "chantier_id": "CHANTIER-A",
        "lignes_demandees": [
            {"materiau_id": "BETON", "quantite_demandee": 2.0},
            {"materiau_id": "ACIER", "quantite_demandee": 3.0},
        ],
        "horodatage": "2025-01-01T08:00:00Z",
    }
    reception_po = {
        "po_id": "PO-007",
        "chantier_id": "CHANTIER-A",
        "lignes_recues": [
            {"materiau_id": "BETON", "quantite_recue": 2.0},
            {"materiau_id": "ACIER", "quantite_recue": 3.0},
        ],
        "horodatage": "2025-01-02T08:00:00Z",
    }
    catalogue = {
        "version": "2025.01",
        "unite_monetaire": "CAD",
        "postes": {"BETON": {"cout_unitaire": 12.5, "libelle": "BETON"}, "ACIER": {"cout_unitaire": 7.0, "libelle": "ACIER"}},
    }

    accuse = traiter_reception(bon_demande, reception_po, catalogue, RegistreVide())

    assert accuse["lignes"][0]["verdict_resolution_prix"] == "PRIX_CATALOGUE"
    assert accuse["lignes"][0]["cout_unitaire_resolu"] == 12.5
    assert accuse["lignes"][0]["montant_ligne"] == 25.0
    assert accuse["lignes"][1]["verdict_resolution_prix"] == "PRIX_CATALOGUE"
    assert accuse["lignes"][1]["cout_unitaire_resolu"] == 7.0
    assert accuse["lignes"][1]["montant_ligne"] == 21.0
    assert accuse["montant_total_estime"] == 46.0


def test_montant_total_estime_est_null_si_au_moins_un_prix_est_indetermine():
    bon_demande = {
        "po_id": "PO-008",
        "chantier_id": "CHANTIER-A",
        "lignes_demandees": [
            {"materiau_id": "BETON", "quantite_demandee": 2.0},
            {"materiau_id": "MATERIAU_INCONNU", "quantite_demandee": 3.0},
        ],
        "horodatage": "2025-01-01T08:00:00Z",
    }
    reception_po = {
        "po_id": "PO-008",
        "chantier_id": "CHANTIER-A",
        "lignes_recues": [
            {"materiau_id": "BETON", "quantite_recue": 2.0},
            {"materiau_id": "MATERIAU_INCONNU", "quantite_recue": 3.0},
        ],
        "horodatage": "2025-01-02T08:00:00Z",
    }
    catalogue = {
        "version": "2025.01",
        "unite_monetaire": "CAD",
        "postes": {"BETON": {"cout_unitaire": 12.5, "libelle": "BETON"}},
    }

    accuse = traiter_reception(bon_demande, reception_po, catalogue, RegistreVide())

    assert accuse["lignes"][0]["verdict_resolution_prix"] == "PRIX_CATALOGUE"
    assert accuse["lignes"][0]["montant_ligne"] == 25.0
    assert accuse["lignes"][1]["verdict_resolution_prix"] == "INDETERMINE"
    assert accuse["lignes"][1]["cout_unitaire_resolu"] is None
    assert accuse["lignes"][1]["montant_ligne"] is None
    assert accuse["montant_total_estime"] is None


def test_bareme_version_reprend_la_version_du_catalogue_fourni():
    bon_demande = {
        "po_id": "PO-009",
        "chantier_id": "CHANTIER-A",
        "lignes_demandees": [
            {"materiau_id": "BETON", "quantite_demandee": 1.0},
        ],
        "horodatage": "2025-01-01T08:00:00Z",
    }
    reception_po = {
        "po_id": "PO-009",
        "chantier_id": "CHANTIER-A",
        "lignes_recues": [
            {"materiau_id": "BETON", "quantite_recue": 1.0},
        ],
        "horodatage": "2025-01-02T08:00:00Z",
    }
    catalogue = {
        "version": "bareme-2025-04",
        "unite_monetaire": "CAD",
        "postes": {"BETON": {"cout_unitaire": 100.0, "libelle": "BETON"}},
    }

    accuse = traiter_reception(bon_demande, reception_po, catalogue, RegistreVide())

    assert accuse["bareme_version"] == "bareme-2025-04"


def test_bareme_version_est_null_lorsque_le_catalogue_est_absent():
    bon_demande = {
        "po_id": "PO-010",
        "chantier_id": "CHANTIER-A",
        "lignes_demandees": [
            {"materiau_id": "BETON", "quantite_demandee": 1.0},
        ],
        "horodatage": "2025-01-01T08:00:00Z",
    }
    reception_po = {
        "po_id": "PO-010",
        "chantier_id": "CHANTIER-A",
        "lignes_recues": [
            {"materiau_id": "BETON", "quantite_recue": 1.0},
        ],
        "horodatage": "2025-01-02T08:00:00Z",
    }

    accuse = traiter_reception(bon_demande, reception_po, None, RegistreVide())

    assert accuse["bareme_version"] is None


def test_prix_indetermine_ne_bloque_pas_le_verdict_physique_de_reception():
    bon_demande = {
        "po_id": "PO-011",
        "chantier_id": "CHANTIER-A",
        "lignes_demandees": [
            {"materiau_id": "BETON", "quantite_demandee": 4.0},
            {"materiau_id": "MATERIAU_INCONNU", "quantite_demandee": 2.0},
        ],
        "horodatage": "2025-01-01T08:00:00Z",
    }
    reception_po = {
        "po_id": "PO-011",
        "chantier_id": "CHANTIER-A",
        "lignes_recues": [
            {"materiau_id": "BETON", "quantite_recue": 4.0},
            {"materiau_id": "MATERIAU_INCONNU", "quantite_recue": 2.0},
        ],
        "horodatage": "2025-01-02T08:00:00Z",
    }
    catalogue = {
        "version": "2025.01",
        "unite_monetaire": "CAD",
        "postes": {"BETON": {"cout_unitaire": 100.0, "libelle": "BETON"}},
    }

    accuse = traiter_reception(bon_demande, reception_po, catalogue, RegistreVide())

    assert accuse["verdict_reception"] == "CONFORME"
    assert accuse["lignes"][1]["verdict_resolution_prix"] == "INDETERMINE"
    assert accuse["montant_total_estime"] is None
