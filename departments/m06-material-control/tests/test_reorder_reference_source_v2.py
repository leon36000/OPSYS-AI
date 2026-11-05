"""Proposition expérimentale : ne pas transformer une localisation non attribuable en liste vide.

Tous les identifiants, quantités, preuves CAS et enregistrements SQLite sont fictifs. Ces tests
appellent les outils publics et ne créent aucun achat.
"""

from __future__ import annotations

from pathlib import Path

import m6_material_control.outils as m6_outils
import pytest

from opsys import stockage
from opsys.outils import executer_atomique
from opsys.registre_mcp import registre as registre_mcp


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
    assert [(signal["chantier_id"], signal["quantite_suggeree"]) for signal in resultat["signaux_reorder"]] == [
        (b, 6.0),
    ]
    assert second["resultat"]["reapprovisionnements_indetermines"] == []

    digest = executer_atomique(_outil("m6_produire_digest"), {"seuils_reorder": seuil_a + seuil_b})
    assert digest["ok"] is True, digest
    contenu = digest["resultat"]
    assert [(signal["chantier_id"], signal["quantite_suggeree"]) for signal in contenu["reorders"]] == [
        (a, 6.0), (b, 6.0),
    ]
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


def test_adverse_un_rebut_c5_lie_a_ne_melange_pas_l_evaluation_du_second_chantier(base):
    material = "mat-scope-paire-fictif"
    a, b = "CH-scope-a-fictif", "CH-scope-b-fictif"
    premier = _recevoir(
        material, a, "PO-SCOPE-A", 5.0, "2026-10-11T14:30:00-04:00",
        [{"chantier_id": a, "materiau_id": material, "seuil_quantite": 5.0}],
        statut="endommage", lieu={"type": "depot"},
    )
    assert premier["ok"] and premier["resultat"]["accepte"] is True, premier
    assert premier["resultat"]["reapprovisionnements_indetermines"][0]["chantier_id"] == a

    second = _recevoir(
        material, b, "PO-SCOPE-B", 5.0, "2026-10-12T14:30:00-04:00",
        [{"chantier_id": b, "materiau_id": material, "seuil_quantite": 6.0}],
        statut="conforme", lieu={"type": "depot"},
    )
    assert second["ok"] and second["resultat"]["accepte"] is True, second
    assert second["resultat"]["reapprovisionnements_indetermines"] == []
    assert [(signal["chantier_id"], signal["quantite_suggeree"])
            for signal in second["resultat"]["resultat"]["signaux_reorder"]] == [(b, 1.0)]
    disponibilite = executer_atomique(_outil("m6_lire_disponibilite"), {"materiau_ids": [material]})
    article = disponibilite["resultat"]["resultat"]["articles"][0]
    assert (article["stock_theorique"], article["hors_main"], article["disponible"]) == ("10", "5", "5")
    assert article["par_emplacement"] == {"depot": "5", "rebut": "5", "inconnu": "0"}

    # L'ancien calcul public de cette paire, limité au registre du chantier B, produit une suggestion de 1;
    # le candidat la retire au motif d'un rebut dont la référence source est le mouvement de A.
    from m6_material_control import reorder

    class RegistreB:
        def lire(self):
            return [{"type_mouvement": "RECEPTION", "chantier_id": b, "materiau_id": material,
                     "quantite": 5.0}]

    attendu_b = reorder.evaluer_reorder(
        b, material, [{"chantier_id": b, "materiau_id": material, "seuil_quantite": 6.0}], RegistreB()
    )
    assert attendu_b["quantite_suggeree"] == 1.0

    digest = executer_atomique(_outil("m6_produire_digest"), {"seuils_reorder": [
        {"chantier_id": a, "materiau_id": material, "seuil_quantite": 5.0},
        {"chantier_id": b, "materiau_id": material, "seuil_quantite": 6.0},
    ]})
    assert digest["ok"] is True, digest
    assert [(item["chantier_id"], item["materiau_id"])
            for item in digest["resultat"]["reapprovisionnements_indetermines"]] == [(a, material)]
    assert [(item["chantier_id"], item["quantite_suggeree"])
            for item in digest["resultat"]["reorders"]] == [(b, 1.0)]


def test_digest_ne_pool_pas_les_sources_liees_vers_un_chantier_sans_mouvement(base):
    material = "mat-scope-zero-fictif"
    a, b, c = "CH-scope-zero-a", "CH-scope-zero-b", "CH-scope-zero-c"
    for chantier, po, date in (
        (a, "PO-SCOPE-ZERO-A", "2026-10-13T14:30:00-04:00"),
        (b, "PO-SCOPE-ZERO-B", "2026-10-14T14:30:00-04:00"),
    ):
        reponse = _recevoir(
            material, chantier, po, 5.0, date,
            [{"chantier_id": chantier, "materiau_id": material, "seuil_quantite": 5.0}],
            statut="conforme", lieu={"type": "depot"},
        )
        assert reponse["ok"] and reponse["resultat"]["accepte"] is True, reponse

    seuils = [
        {"chantier_id": a, "materiau_id": material, "seuil_quantite": 5.0},
        {"chantier_id": b, "materiau_id": material, "seuil_quantite": 5.0},
        {"chantier_id": c, "materiau_id": material, "seuil_quantite": 5.0},
    ]
    digest = executer_atomique(_outil("m6_produire_digest"), {"seuils_reorder": seuils})
    assert digest["ok"] is True, digest
    assert digest["resultat"]["reapprovisionnements_indetermines"] == []
    assert [(x["chantier_id"], x["quantite_suggeree"]) for x in digest["resultat"]["reorders"]] == [(c, 5.0)]

    from m6_material_control import reorder

    class RegistreVide:
        def lire(self):
            return []

    ancien = reorder.evaluer_reorder(c, material, [seuils[2]], RegistreVide())
    assert ancien["stock_actuel"] == 0.0 and ancien["quantite_suggeree"] == 5.0


def test_transfert_historique_sans_reference_source_reste_indetermine_apres_reception_future(base):
    material, chantier = "mat-legacy-rebut-fictif", "CH-legacy-rebut-fictif"
    seuil = [{"chantier_id": chantier, "materiau_id": material, "seuil_quantite": 5.0}]
    premiere = _recevoir(
        material, chantier, "PO-LEGACY-A", 5.0, "2026-10-15T14:30:00-04:00", seuil
    )
    assert premiere["ok"] and premiere["resultat"]["accepte"] is True, premiere
    transfert = executer_atomique(_outil("m6_transferer_stock"), {
        "transfert_id": "TRANSFER-LEGACY-REBUT-FICTIF",
        "materiau_id": material,
        "quantite": 5.0,
        "de": {"type": "inconnu"},
        "vers": {"type": "rebut"},
        "motif": "rebut fictif historique sans référence source",
        "horodatage": "2026-10-16T14:30:00-04:00",
    })
    assert transfert["ok"] and transfert["resultat"]["accepte"] is True, transfert
    assert "reference_source" not in transfert["resultat"]["transfert"]

    digest = executer_atomique(_outil("m6_produire_digest"), {"seuils_reorder": seuil})
    assert digest["resultat"]["reorders"] == []
    assert digest["resultat"]["nb_reapprovisionnements_indetermines"] == 1
    assert digest["resultat"]["reapprovisionnements_indetermines"][0]["chantier_id"] == chantier

    future = _recevoir(
        material, chantier, "PO-LEGACY-B", 1.0, "2026-10-17T14:30:00-04:00", seuil
    )
    assert future["ok"] and future["resultat"]["accepte"] is True, future
    assert future["resultat"]["resultat"]["signaux_reorder"] == []
    assert future["resultat"]["reapprovisionnements_indetermines"][0]["chantier_id"] == chantier


def test_transfert_non_lie_historique_garde_toutes_les_paires_prudentes(base):
    material = "mat-legacy-paires-fictif"
    a, b = "CH-legacy-a-fictif", "CH-legacy-b-fictif"
    for chantier, po, date in (
        (a, "PO-LEGACY-PAIRE-A", "2026-10-18T14:30:00-04:00"),
        (b, "PO-LEGACY-PAIRE-B", "2026-10-19T14:30:00-04:00"),
    ):
        reception = _recevoir(
            material, chantier, po, 5.0, date,
            [{"chantier_id": chantier, "materiau_id": material, "seuil_quantite": 6.0}],
            statut="conforme", lieu={"type": "depot"},
        )
        assert reception["ok"] and reception["resultat"]["accepte"] is True, reception

    transfert = executer_atomique(_outil("m6_transferer_stock"), {
        "transfert_id": "TRANSFER-LEGACY-PAIRES-FICTIF",
        "materiau_id": material,
        "quantite": 1.0,
        "de": {"type": "depot"},
        "vers": {"type": "rebut"},
        "motif": "transfert historique sans source fictif",
        "horodatage": "2026-10-20T14:30:00-04:00",
    })
    assert transfert["ok"] and transfert["resultat"]["accepte"] is True, transfert
    assert "reference_source" not in transfert["resultat"]["transfert"]

    digest = executer_atomique(_outil("m6_produire_digest"), {"seuils_reorder": [
        {"chantier_id": a, "materiau_id": material, "seuil_quantite": 6.0},
        {"chantier_id": b, "materiau_id": material, "seuil_quantite": 6.0},
    ]})
    assert digest["ok"] is True, digest
    assert [(x["chantier_id"], x["materiau_id"])
            for x in digest["resultat"]["reapprovisionnements_indetermines"]] == [(a, material), (b, material)]
    assert digest["resultat"]["reorders"] == []


def test_descriptions_et_schemas_des_outils_restent_scelles_au_registre_mcp():
    chemin_registre = Path(registre_mcp.__file__).with_name("registre.v1.json")
    registre = registre_mcp.charger(chemin_registre)
    outils = {outil.nom: outil for outil in m6_outils.outils()}
    for nom in ("m6_receptionner_commande", "m6_produire_digest"):
        definition = registre_mcp.DefinitionOutil.depuis_outil(outils[nom], "m06-material-control")
        assert registre_mcp.verifier_definition(registre, definition) is None
