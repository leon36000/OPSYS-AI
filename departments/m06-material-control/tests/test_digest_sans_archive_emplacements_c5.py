"""L'appel hors transaction ne possède pas la chaîne durable des emplacements."""

import pytest
from m6_material_control import outils as outils_m6
from m6_material_control.registre import Registre

from opsys import stockage
from opsys.outils import executer, executer_atomique


def _outil(nom):
    return next(outil for outil in outils_m6.outils() if outil.nom == nom)


@pytest.fixture
def base(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'm6-archive-absente-fictif.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    try:
        yield url
    finally:
        stockage.liberer()


def test_digest_hors_transaction_signale_l_indetermination_quand_l_archive_emplacements_manque():
    materiau = "MAT-archive-absente-fictif"
    chantier = "CH-archive-absente-fictif"
    seuils = [{"chantier_id": chantier, "materiau_id": materiau, "seuil_quantite": 6.0}]
    reception = executer(_outil("m6_receptionner_commande"), {
        "bon_demande": {
            "po_id": "PO-archive-absente-fictif",
            "chantier_id": chantier,
            "lignes_demandees": [{"materiau_id": materiau, "quantite_demandee": 5.0}],
            "horodatage": "2026-10-06T14:00:00-04:00",
        },
        "seuils_reorder": seuils,
        "reception_po": {
            "po_id": "PO-archive-absente-fictif",
            "chantier_id": chantier,
            "lignes_recues": [{"materiau_id": materiau, "quantite_recue": 5.0}],
            "horodatage": "2026-10-06T14:30:00-04:00",
        },
    })
    assert reception["ok"] and reception["resultat"]["accepte"] is True, reception
    reception_digest = reception["resultat"]["resultat"]
    assert reception_digest["signaux_reorder"] == []
    assert reception["resultat"]["reapprovisionnements_indetermines"] == [{
        "chantier_id": chantier,
        "materiau_id": materiau,
        "motif": "stock_localise_par_chantier_non_reconstructible",
    }]
    historique = reception["resultat"]["registre_historique"]

    lecture = executer(_outil("m6_produire_digest"), {
        "registre_historique": historique,
        "seuils_reorder": seuils,
    })

    assert lecture["ok"] is True, lecture
    digest = lecture["resultat"]
    assert digest["reorders"] == []
    assert digest["nb_reorders_suggeres"] == 0
    assert digest["reapprovisionnements_indetermines"] == [{
        "chantier_id": chantier,
        "materiau_id": materiau,
        "motif": "stock_localise_par_chantier_non_reconstructible",
    }]
    assert digest["nb_reapprovisionnements_indetermines"] == 1


def test_reception_directe_apres_reception_c5_endommagee_signale_l_archive_absente(base):
    materiau = "MAT-C5-endommage-archive-fictif"
    chantier = "CH-C5-endommage-archive-fictif"
    seuils = [{"chantier_id": chantier, "materiau_id": materiau, "seuil_quantite": 7.0}]
    initiale = executer_atomique(_outil("m6_receptionner_commande"), {
        "bon_demande": {
            "po_id": "PO-C5-endommage-archive-fictif-1",
            "chantier_id": chantier,
            "lignes_demandees": [{"materiau_id": materiau, "quantite_demandee": 5.0}],
            "horodatage": "2026-10-07T14:00:00-04:00",
        },
        "reception_po": {
            "po_id": "PO-C5-endommage-archive-fictif-1",
            "chantier_id": chantier,
            "lignes_recues": [{"materiau_id": materiau, "quantite_recue": 5.0}],
            "horodatage": "2026-10-07T14:30:00-04:00",
        },
        "details_reception": [{
            "materiau_id": materiau,
            "statut_ligne": "endommage",
            "photos": ["fichier:sha256:" + "ef" * 32],
        }],
        "lieu_livraison": {"type": "depot"},
        "seuils_reorder": seuils,
    })
    assert initiale["ok"] and initiale["resultat"]["accepte"] is True, initiale
    with stockage.transaction():
        historique = list(stockage.maillons("m06-material-control", "principal"))
    stockage.liberer()

    seconde = executer(_outil("m6_receptionner_commande"), {
        "bon_demande": {
            "po_id": "PO-C5-endommage-archive-fictif-2",
            "chantier_id": chantier,
            "lignes_demandees": [{"materiau_id": materiau, "quantite_demandee": 1.0}],
            "horodatage": "2026-10-08T14:00:00-04:00",
        },
        "reception_po": {
            "po_id": "PO-C5-endommage-archive-fictif-2",
            "chantier_id": chantier,
            "lignes_recues": [{"materiau_id": materiau, "quantite_recue": 1.0}],
            "horodatage": "2026-10-08T14:30:00-04:00",
        },
        "registre_historique": historique,
        "seuils_reorder": seuils,
    })

    assert seconde["ok"] and seconde["resultat"]["accepte"] is True, seconde
    resultat = seconde["resultat"]["resultat"]
    assert resultat["signaux_reorder"] == []
    assert seconde["resultat"]["reapprovisionnements_indetermines"] == [{
        "chantier_id": chantier,
        "materiau_id": materiau,
        "motif": "stock_localise_par_chantier_non_reconstructible",
    }]


def test_digest_absent_archive_ne_compense_pas_les_mouvements_entre_chantiers():
    materiau = "MAT-annulation-chantiers-fictif"
    chantier_positif = "CH-annulation-positif-fictif"
    chantier_negatif = "CH-annulation-negatif-fictif"
    registre = Registre()
    for mouvement in (
        {
            "type_mouvement": "RECEPTION",
            "chantier_id": chantier_positif,
            "materiau_id": materiau,
            "quantite": 5.0,
            "cout_unitaire": 2.0,
        },
        {
            "type_mouvement": "CONSOMMATION",
            "chantier_id": chantier_negatif,
            "materiau_id": materiau,
            "quantite": -5.0,
            "cout_unitaire": None,
        },
    ):
        _, erreur = registre.ajouter(mouvement)
        assert erreur is None

    paires = [
        {"chantier_id": chantier, "materiau_id": materiau, "seuil_quantite": 6.0}
        for chantier in (chantier_positif, chantier_negatif)
    ]
    lecture = executer(_outil("m6_produire_digest"), {
        "registre_historique": registre.lire(),
        "seuils_reorder": paires,
    })

    assert lecture["ok"] is True, lecture
    digest = lecture["resultat"]
    assert digest["reorders"] == []
    assert digest["nb_reorders_suggeres"] == 0
    assert digest["reapprovisionnements_indetermines"] == [
        {
            "chantier_id": chantier_negatif,
            "materiau_id": materiau,
            "motif": "stock_localise_par_chantier_non_reconstructible",
        },
        {
            "chantier_id": chantier_positif,
            "materiau_id": materiau,
            "motif": "stock_localise_par_chantier_non_reconstructible",
        },
    ]
    assert digest["nb_reapprovisionnements_indetermines"] == 2
