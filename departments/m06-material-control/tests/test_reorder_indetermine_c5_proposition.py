"""Proposition expérimentale : ne pas transformer une localisation non attribuable en liste vide.

Tous les identifiants, quantités, preuves CAS et enregistrements SQLite sont fictifs. Ces tests
appellent les outils publics et ne créent aucun achat.
"""

from __future__ import annotations

import m6_material_control.outils as m6_outils
import pytest

from opsys import stockage
from opsys.outils import executer_atomique


@pytest.fixture
def base(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'm6-reorder-indetermine-fictif.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    try:
        yield url
    finally:
        stockage.liberer()


def _outil(nom):
    return next(outil for outil in m6_outils.outils() if outil.nom == nom)


def _recevoir(material, chantier, po, quantite, horodatage, seuils, *, statut=None, lieu=None):
    args = {
        "bon_demande": {
            "po_id": po,
            "chantier_id": chantier,
            "lignes_demandees": [{"materiau_id": material, "quantite_demandee": quantite}],
            "horodatage": horodatage,
        },
        "reception_po": {
            "po_id": po,
            "chantier_id": chantier,
            "lignes_recues": [{"materiau_id": material, "quantite_recue": quantite}],
            "horodatage": horodatage,
        },
        "seuils_reorder": seuils,
    }
    if statut is not None:
        detail = {"materiau_id": material, "statut_ligne": statut}
        if statut == "endommage":
            detail["photos"] = ["fichier:sha256:" + "cd" * 32]
        args["details_reception"] = [detail]
    if lieu is not None:
        args["lieu_livraison"] = lieu
    return executer_atomique(_outil("m6_receptionner_commande"), args)


def test_rebut_est_signale_indetermine_sans_stock_global_et_persiste_a_la_reception_future(base):
    material, chantier = "mat-c5-indet-fictif", "CH-c5-indet-fictif"
    seuil = [{"chantier_id": chantier, "materiau_id": material, "seuil_quantite": 5.0}]

    initiale = _recevoir(
        material, chantier, "PO-C5-REBUT-1", 5.0, "2026-10-06T14:30:00-04:00", seuil,
        statut="endommage", lieu={"type": "depot"},
    )
    assert initiale["ok"] and initiale["resultat"]["accepte"] is True, initiale
    resultat = initiale["resultat"]["resultat"]
    assert resultat["signaux_reorder"] == []
    assert initiale["resultat"]["reapprovisionnements_indetermines"] == [{
        "chantier_id": chantier,
        "materiau_id": material,
        "motif": "stock_localise_par_chantier_non_reconstructible",
    }]

    lecture = executer_atomique(_outil("m6_lire_disponibilite"), {"materiau_ids": [material]})
    article = lecture["resultat"]["resultat"]["articles"][0]
    assert (article["stock_theorique"], article["en_main"], article["disponible"]) == ("5", "0", "0")
    assert article["par_emplacement"] == {"rebut": "5", "inconnu": "0"}

    future = _recevoir(
        material, chantier, "PO-C5-REBUT-2", 1.0, "2026-10-07T14:30:00-04:00", seuil,
        statut="conforme", lieu={"type": "depot"},
    )
    assert future["ok"] and future["resultat"]["accepte"] is True, future
    resultat_futur = future["resultat"]["resultat"]
    assert resultat_futur["signaux_reorder"] == []
    assert future["resultat"]["reapprovisionnements_indetermines"] == initiale["resultat"][
        "reapprovisionnements_indetermines"
    ]
    lecture_future = executer_atomique(_outil("m6_lire_disponibilite"), {"materiau_ids": [material]})
    article_futur = lecture_future["resultat"]["resultat"]["articles"][0]
    assert (article_futur["stock_theorique"], article_futur["en_main"], article_futur["disponible"]) == (
        "6", "1", "1"
    )
    assert article_futur["par_emplacement"] == {"depot": "1", "rebut": "5", "inconnu": "0"}

    digest = executer_atomique(_outil("m6_produire_digest"), {"seuils_reorder": seuil})
    assert digest["ok"] is True, digest
    contenu = digest["resultat"]
    assert contenu["reorders"] == [] and contenu["nb_reorders_suggeres"] == 0
    assert contenu["reapprovisionnements_indetermines"] == initiale["resultat"][
        "reapprovisionnements_indetermines"
    ]
    assert contenu["nb_reapprovisionnements_indetermines"] == 1


def test_references_c5_distinguables_conservent_les_suggestions_par_chantier(base):
    material = "mat-melange-fictif"
    a, b = "CH-melange-a-fictif", "CH-melange-b-fictif"
    seuil_a = [{"chantier_id": a, "materiau_id": material, "seuil_quantite": 10.0}]
    seuil_b = [{"chantier_id": b, "materiau_id": material, "seuil_quantite": 10.0}]

    premier = _recevoir(material, a, "PO-MELANGE-A", 4.0, "2026-10-08T14:30:00-04:00", seuil_a,
                        statut="conforme", lieu={"type": "depot"})
    assert premier["ok"] and premier["resultat"]["resultat"]["signaux_reorder"]
    assert premier["resultat"]["reapprovisionnements_indetermines"] == []

    second = _recevoir(material, b, "PO-MELANGE-B", 4.0, "2026-10-09T14:30:00-04:00", seuil_b,
                       statut="conforme", lieu={"type": "depot"})
    assert second["ok"] and second["resultat"]["accepte"] is True, second
    resultat = second["resultat"]["resultat"]
    assert [(signal["chantier_id"], signal["quantite_suggeree"])
            for signal in resultat["signaux_reorder"]] == [(b, 6.0)]
    assert second["resultat"]["reapprovisionnements_indetermines"] == []

    digest = executer_atomique(_outil("m6_produire_digest"), {"seuils_reorder": seuil_a + seuil_b})
    assert digest["ok"] is True, digest
    contenu = digest["resultat"]
    assert [(signal["chantier_id"], signal["quantite_suggeree"])
            for signal in contenu["reorders"]] == [(a, 6.0), (b, 6.0)]
    assert contenu["nb_reorders_suggeres"] == 2
    assert contenu["reapprovisionnements_indetermines"] == []
    assert contenu["nb_reapprovisionnements_indetermines"] == 0


def test_aucun_seuil_n_est_invente_et_reception_historique_sans_transfert_reste_inchangee(base):
    material, chantier = "mat-sans-transfert-fictif", "CH-sans-transfert-fictif"
    seuil = [{"chantier_id": chantier, "materiau_id": material, "seuil_quantite": 5.0}]
    reception = _recevoir(
        material, chantier, "PO-SANS-TRANSFERT", 2.0, "2026-10-10T14:30:00-04:00", seuil
    )
    assert reception["ok"] and reception["resultat"]["accepte"] is True, reception
    assert reception["resultat"]["resultat"]["signaux_reorder"][0]["quantite_suggeree"] == 3.0
    assert reception["resultat"]["reapprovisionnements_indetermines"] == []

    digest_sans_seuil = executer_atomique(_outil("m6_produire_digest"), {})
    assert digest_sans_seuil["ok"] is True, digest_sans_seuil
    assert digest_sans_seuil["resultat"]["reapprovisionnements_indetermines"] == []
    assert digest_sans_seuil["resultat"]["nb_reapprovisionnements_indetermines"] == 0


def test_rebut_attribue_ne_masque_pas_le_chantier_sain(base):
    material = "mat-deux-chantiers-fictif"
    a, b = "CH-rebut-fictif", "CH-sain-fictif"
    seuils = [
        {"chantier_id": a, "materiau_id": material, "seuil_quantite": 6.0},
        {"chantier_id": b, "materiau_id": material, "seuil_quantite": 6.0},
    ]
    assert _recevoir(material, a, "PO-rebut-fictif", 5.0, "2026-10-08T14:30:00-04:00", seuils,
                     statut="endommage", lieu={"type": "depot"})["ok"]
    assert _recevoir(material, b, "PO-sain-fictif", 5.0, "2026-10-09T14:30:00-04:00", seuils,
                     statut="conforme", lieu={"type": "depot"})["ok"]
    contenu = executer_atomique(_outil("m6_produire_digest"), {"seuils_reorder": seuils})["resultat"]
    assert contenu["reapprovisionnements_indetermines"] == [{
        "chantier_id": a, "materiau_id": material,
        "motif": "stock_localise_par_chantier_non_reconstructible",
    }]
    assert [(r["chantier_id"], r["quantite_suggeree"]) for r in contenu["reorders"]] == [(b, 1.0)]
