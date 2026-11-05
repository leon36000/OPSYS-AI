"""Repro fictive du prélèvement de stock théorique déjà localisé au rebut."""

from __future__ import annotations

import sys
from decimal import Decimal, localcontext
from itertools import permutations

import m6_material_control.outils as m6_outils
import pytest
from m6_material_control import emplacements, reception, reorder, reservations, stock
from m6_material_control import registre as registre_module
from sqlalchemy import func, select, update

from opsys import evenements, stockage
from opsys.outils import executer, executer_atomique
from opsys.stockage.schema import EVENEMENTS_SORTANTS, REGISTRES


def test_somme_borne_decimale_est_exacte_et_abstient_au_dela_des_ressources():
    assert reorder.somme_decimaux_exactement([
        (Decimal("1E+28"), 1), (Decimal(1), 1), (Decimal("1E+28"), -1),
    ]) == Decimal(1)
    assert reorder.somme_decimaux_exactement([
        (Decimal("1E+27"), 1), (Decimal("0.1"), 1), (Decimal("1E+27"), -1),
    ]) == Decimal("0.1")
    assert reorder.somme_decimaux_exactement([
        (Decimal("0.05"), 1), (Decimal("0.05"), 1),
    ]) == Decimal("0.1")
    assert reorder.somme_decimaux_exactement([(Decimal("1E+99999999"), 1)]) is None
    assert reorder.somme_decimaux_exactement([(Decimal("9" * 5000), 1)]) is None
    assert reorder.somme_decimaux_exactement((Decimal(1), 1) for _ in range(5000)) == Decimal(5000)
    grand = Decimal("1E+4090")
    petit = Decimal("1E-4090")
    assert reorder.somme_decimaux_exactement([(grand, 1), (petit, 1), (grand, -1)]) is None
    assert reorder.somme_decimaux_exactement([(grand, 1), (grand, -1), (petit, 1)]) == petit
    grand_coefficient = Decimal("9" * 4096)
    assert reorder.somme_decimaux_exactement([
        (grand_coefficient, 1), (grand_coefficient, 1),
        (grand_coefficient, -1), (grand_coefficient, -1),
    ]) is None
    assert reorder.somme_decimaux_exactement([
        (grand_coefficient, 1), (grand_coefficient, -1),
        (grand_coefficient, 1), (grand_coefficient, -1),
    ]) == Decimal(0)


def test_somme_borne_s_abstient_si_le_plafond_entier_python_empeche_conversion():
    if not hasattr(sys, "set_int_max_str_digits"):
        pytest.skip("Python sans plafond configurable de conversion int/str")
    plafond_initial = sys.get_int_max_str_digits()
    coefficient_trop_long = Decimal("9" * 641)
    premier = Decimal("9" * 640)
    second = Decimal("9" * 640)
    try:
        sys.set_int_max_str_digits(640)
        assert reorder.somme_decimaux_exactement([(coefficient_trop_long, 1)]) is None
        assert reorder.somme_decimaux_exactement([(premier, 1), (second, 1)]) is None
    finally:
        sys.set_int_max_str_digits(plafond_initial)
    assert sys.get_int_max_str_digits() == plafond_initial


def test_stock_signe_et_canonique_invariants_aux_permutations_et_contextes():
    materiau = "mat-somme-exacte-permutation-fictif"
    mouvements = [
        {"type_mouvement": "RECEPTION", "materiau_id": materiau, "quantite": "10000000000000000000000000000"},
        {"type_mouvement": "CONSOMMATION", "materiau_id": materiau, "quantite": "-10000000000000000000000000000"},
        {"type_mouvement": "RECEPTION", "materiau_id": materiau, "quantite": "0.1"},
    ]
    stock_attendu = Decimal("0.1")
    canonique_attendu = "10000000000000000000000000000.1"

    for ordre in permutations(mouvements):
        for precision in (28, 40):
            with localcontext() as contexte_decimal:
                contexte_decimal.prec = precision
                resultat = stock.deriver_stock_articles([materiau], ordre)[materiau]
                assert resultat == stock_attendu
                assert stock.texte_canonique(Decimal(canonique_attendu)) == canonique_attendu
                disponibilite = stock.deriver_disponibilite([materiau], ordre, {}, {})[materiau]
                assert disponibilite["disponible"] == stock_attendu


def test_demande_legacy_est_somme_exacte_independamment_du_contexte_decimal():
    materiau = "mat-demande-exacte-contexte-fictif"
    mouvements = [{
        "type_mouvement": "RECEPTION",
        "chantier_id": "CH-demande-exacte-contexte-fictif",
        "materiau_id": materiau,
        "quantite": "10000000000000000000000000000",
    }]

    class Registre:
        def lire(self):
            return mouvements

    demandes = [
        {"materiau_id": materiau, "quantite": 10**28},
        {"materiau_id": materiau, "quantite": 0.1},
    ]
    for precision in (28, 40):
        with localcontext() as contexte_decimal:
            contexte_decimal.prec = precision
            accepte, code = stock.verifier_disponibilite_consommation(
                "CH-demande-exacte-contexte-fictif", demandes, Registre()
            )
            assert accepte is False
            assert code == "REJ-STOCK-INSUFFISANT"


def test_cumul_reception_exact_et_borne_sans_contexte_decimal_ambiant():
    material = "mat-cumul-reception-exact-fictif"
    commandees = [{"materiau_id": material, "quantite_demandee": "10000000000000000000000000000"}]
    livraisons = [
        [{"materiau_id": material, "quantite_recue": "10000000000000000000000000000"}],
        [{"materiau_id": material, "quantite_recue": "0.1"}],
    ]
    for precision in (28, 40):
        with localcontext() as contexte_decimal:
            contexte_decimal.prec = precision
            resultat = reception.evaluer_cumul(commandees, livraisons)
            assert resultat["verdict_reception"] == "RECEPTION_SUPERIEURE"
            assert resultat["lignes"][0]["ecart_cumule"] == "0.1"
            cumul_long = reception.evaluer_cumul(
                [{"materiau_id": material, "quantite_demandee": "0"}],
                ([{"materiau_id": material, "quantite_recue": "0.1"}] for _ in range(4097)),
            )
            assert cumul_long["lignes"][0]["quantite_recue_cumulee"] == "409.7"


def test_reservations_exactes_sous_contextes_et_reconciliation():
    material = "mat-reservation-exacte-fictif"
    base = [
        {
            "type_entree": "reservation", "devis_id": "D-old", "chantier_id": "CH-old",
            "evenement": "creee", "actif": True,
            "revision": 1, "lignes": [{"materiau_id": material, "quantite_besoin": "10000000000000000000000000000",
                                       "quantite_reservee": "10000000000000000000000000000"}],
        },
        {
            "type_entree": "reservation", "devis_id": "D-new", "chantier_id": "CH-new",
            "evenement": "creee", "actif": True,
            "revision": 1, "lignes": [{"materiau_id": material, "quantite_besoin": "0.1",
                                       "quantite_reservee": "0.1"}],
        },
    ]
    for precision in (28, 40):
        with localcontext() as contexte_decimal:
            contexte_decimal.prec = precision
            assert reservations.reserve_par_article(base)[material] == Decimal("10000000000000000000000000000.1")
            faits = reservations.reconcilier([material], {material: Decimal(10000000000000000000000000000)},
                                             base, "2026-11-05T13:00:00-04:00")
            assert len(faits) == 1 and faits[0]["devis_id"] == "D-new"
            assert faits[0]["lignes"][0]["quantite_reservee"] == "0"


def _outil(nom):
    return next(outil for outil in m6_outils.outils() if outil.nom == nom)


def _recevoir_cinq(material, project, thresholds, statut="endommage", suffix=""):
    date = "2026-11-03T10:00:00-04:00"
    po_id = f"PO-consomme-rebut-fictif-{project}{'-' + suffix if suffix else ''}"
    return executer_atomique(_outil("m6_receptionner_commande"), {
        "bon_demande": {
            "po_id": po_id,
            "chantier_id": project,
            "lignes_demandees": [{"materiau_id": material, "quantite_demandee": 5.0}],
            "horodatage": date,
        },
        "reception_po": {
            "po_id": po_id,
            "chantier_id": project,
            "lignes_recues": [{"materiau_id": material, "quantite_recue": 5.0}],
            "horodatage": date,
        },
        **({"details_reception": [{
            "materiau_id": material,
            "statut_ligne": statut,
            **({"photos": ["fichier:sha256:" + "cd" * 32]} if statut == "endommage" else {}),
        }]} if statut is not None else {}),
        "lieu_livraison": {"type": "depot"},
        "seuils_reorder": thresholds,
        "catalogue_materiaux": {
            "version": "v1",
            "unite_monetaire": "CAD",
            "postes": {material: {"cout_unitaire": 5.0, "libelle": "Article fictif"}},
        },
    })


def _recevoir_quantite(material, project, quantity, *, statut=None, suffix=""):
    date = "2026-11-03T10:00:00-04:00"
    po_id = f"PO-quantite-decimale-fictif-{project}-{suffix}"
    arguments = {
        "bon_demande": {
            "po_id": po_id,
            "chantier_id": project,
            "lignes_demandees": [{"materiau_id": material, "quantite_demandee": quantity}],
            "horodatage": date,
        },
        "reception_po": {
            "po_id": po_id,
            "chantier_id": project,
            "lignes_recues": [{"materiau_id": material, "quantite_recue": quantity}],
            "horodatage": date,
        },
        "catalogue_materiaux": {
            "version": "v1",
            "unite_monetaire": "CAD",
            "postes": {material: {"cout_unitaire": 5.0, "libelle": "Article fictif"}},
        },
    }
    if statut is not None:
        arguments["details_reception"] = [{
            "materiau_id": material,
            "statut_ligne": statut,
            **({"photos": ["fichier:sha256:" + "cd" * 32]} if statut == "endommage" else {}),
        }]
        arguments["lieu_livraison"] = {"type": "depot"}
    return executer_atomique(_outil("m6_receptionner_commande"), arguments)


def _wct(project, wct_id="w-consomme-rebut-legacy-fictif"):
    return {
        "wct_id": wct_id,
        "intervention_id": "i-consomme-rebut-legacy-fictif",
        "lead_id": "lead-fictif",
        "technicien_id": "tech-fictif",
        "horodatage_completion": "2026-11-03T12:00:00-04:00",
        "fix_gps_completion": {"latitude": 1.0, "longitude": 2.0},
        "duree_reelle_minutes": 30,
        "ecart_signale": False,
        "revue_id": None,
        "hash_maillon": "a" * 64,
        "consommateurs_cibles": ["M6"],
        "devis_id": None,
    }


def _publier_wct(wct):
    charge = {**wct, "statut": "completed_pending_review"}
    with stockage.transaction():
        evenements.publier("m4.travaux_termines", "m04-field-ops", charge, evenement_id=wct["wct_id"])


def _consommer_legacy(wct, project, lignes):
    return executer_atomique(_outil("m6_consommer_materiaux"), {
        "wct": wct,
        "formulaire": {
            "wct_id": wct["wct_id"],
            "intervention_id": wct["intervention_id"],
            "chantier_id": project,
            "lignes_consommees": lignes,
        },
    })


def _consommer_legacy_direct(wct, project, lignes):
    formulaire = {
        "wct_id": wct["wct_id"],
        "intervention_id": wct["intervention_id"],
        "chantier_id": project,
        "lignes_consommees": lignes,
    }
    with stockage.transaction():
        return m6_outils.consommer_materiaux(wct, formulaire)


def _etat_stock_durable(material):
    with stockage.transaction() as cnx:
        return (
            list(stockage.maillons("m06-material-control", "besoins_commande")),
            list(stockage.maillons("m06-material-control", "principal")),
            list(stockage.maillons("m06-material-control", "reservations")),
            list(stockage.maillons("m06-material-control", "emplacements")),
            list(stockage.maillons("m06-material-control", "wct_recus")),
            cnx.execute(select(func.count()).select_from(EVENEMENTS_SORTANTS)).scalar_one(),
        )


def test_consommation_acceptee_depuis_un_rebut_fait_passer_en_main_sous_zero(base):
    material, project = "mat-consomme-rebut-fictif", "CH-consomme-rebut-fictif"
    thresholds = [{"chantier_id": project, "materiau_id": material, "seuil_quantite": 10.0}]
    date = "2026-11-03T10:00:00-04:00"
    received = executer_atomique(_outil("m6_receptionner_commande"), {
        "bon_demande": {
            "po_id": "PO-consomme-rebut-fictif",
            "chantier_id": project,
            "lignes_demandees": [{"materiau_id": material, "quantite_demandee": 5.0}],
            "horodatage": date,
        },
        "reception_po": {
            "po_id": "PO-consomme-rebut-fictif",
            "chantier_id": project,
            "lignes_recues": [{"materiau_id": material, "quantite_recue": 5.0}],
            "horodatage": date,
        },
        "details_reception": [{
            "materiau_id": material,
            "statut_ligne": "endommage",
            "photos": ["fichier:sha256:" + "cd" * 32],
        }],
        "lieu_livraison": {"type": "depot"},
        "seuils_reorder": thresholds,
    })
    assert received["ok"] and received["resultat"]["accepte"] is True, received
    assert received["resultat"]["reapprovisionnements_indetermines"] == [{
        "chantier_id": project,
        "materiau_id": material,
        "motif": "stock_localise_par_chantier_non_reconstructible",
    }]

    wct = {
        "wct_id": "w-consomme-rebut-fictif",
        "intervention_id": "i-consomme-rebut-fictif",
        "lead_id": "lead-fictif",
        "technicien_id": "tech-fictif",
        "horodatage_completion": "2026-11-03T12:00:00-04:00",
        "fix_gps_completion": {"latitude": 1.0, "longitude": 2.0},
        "duree_reelle_minutes": 30,
        "ecart_signale": False,
        "revue_id": None,
        "hash_maillon": "a" * 64,
        "consommateurs_cibles": ["M6"],
        "devis_id": None,
    }
    with stockage.transaction():
        evenements.publier(
            "m4.travaux_termines", "m04-field-ops", {**wct, "statut": "completed_pending_review"},
            evenement_id=wct["wct_id"],
        )

    consumed = executer_atomique(_outil("m6_declarer_materiaux_utilises"), {
        "wct_id": wct["wct_id"],
        "formulaire": {
            "wct_id": wct["wct_id"],
            "intervention_id": wct["intervention_id"],
            "chantier_id": project,
            "lignes_materiaux": [{
                "type_ligne": "prevu",
                "materiau_id": material,
                "quantite": 5.0,
                "unite": "boite",
                "quantite_estimee": 5.0,
            }],
        },
    })
    assert consumed["ok"] and consumed["resultat"]["accepte"] is True, consumed

    availability = executer_atomique(_outil("m6_lire_disponibilite"), {"materiau_ids": [material]})
    assert availability["ok"] is True, availability
    article = availability["resultat"]["resultat"]["articles"][0]
    assert article["stock_theorique"] == "0"
    assert article["hors_main"] == "5"
    assert article["en_main"] == article["disponible"] == "-5"
    assert article["par_emplacement"] == {"rebut": "5", "inconnu": "-5"}

    digest = executer_atomique(_outil("m6_produire_digest"), {"seuils_reorder": thresholds})
    assert digest["ok"] is True, digest
    assert digest["resultat"]["reorders"] == []
    assert digest["resultat"]["reapprovisionnements_indetermines"] == received["resultat"][
        "reapprovisionnements_indetermines"
    ]


def test_legacy_refuse_si_le_stock_en_main_global_est_prouve_insuffisant_sans_ecriture(base):
    material, project = "mat-consomme-rebut-fictif", "CH-consomme-rebut-fictif"
    thresholds = [{"chantier_id": project, "materiau_id": material, "seuil_quantite": 10.0}]
    received = _recevoir_cinq(material, project, thresholds, statut=None)
    assert received["ok"] and received["resultat"]["accepte"] is True, received
    transfer = executer_atomique(_outil("m6_transferer_stock"), {
        "transfert_id": "T-global-insuffisant-fictif",
        "materiau_id": material,
        "quantite": 5.0,
        "de": {"type": "depot"},
        "vers": {"type": "rebut"},
        "motif": "mise au rebut fictive sans liaison C5",
        "horodatage": "2026-11-03T11:00:00-04:00",
    })
    assert transfer["ok"] and transfer["resultat"]["accepte"] is True, transfer

    wct = _wct(project)
    _publier_wct(wct)
    before = _etat_stock_durable(material)
    refused = executer_atomique(_outil("m6_consommer_materiaux"), {
        "wct": wct,
        "formulaire": {
            "wct_id": wct["wct_id"],
            "intervention_id": wct["intervention_id"],
            "chantier_id": project,
            "lignes_consommees": [{"materiau_id": material, "quantite": 5.0}],
        },
    })

    assert refused["ok"] is True and refused["resultat"]["accepte"] is False, refused
    verdict = refused["resultat"]["verdict"]
    assert verdict["code"] == "REJ-STOCK-INSUFFISANT"
    assert "stock en main global 0" in verdict["detail"]
    assert "quantité demandée 5" in verdict["detail"]
    assert "Aucun mouvement n'a été écrit" in verdict["detail"]
    assert _etat_stock_durable(material) == before


def test_legacy_somme_les_lignes_repetant_un_materiau_avant_le_controle(base):
    material, project = "mat-lignes-repetes-fictif", "CH-lignes-repetes-fictif"
    received = _recevoir_cinq(material, project, [])
    assert received["ok"] and received["resultat"]["accepte"] is True, received
    wct = _wct(project, "w-lignes-repetes-fictif")
    _publier_wct(wct)
    before = _etat_stock_durable(material)

    refused = _consommer_legacy(wct, project, [
        {"materiau_id": material, "quantite": 2.0},
        {"materiau_id": material, "quantite": 3.0},
    ])

    assert refused["ok"] and refused["resultat"]["accepte"] is False, refused
    assert refused["resultat"]["verdict"]["code"] == "REJ-STOCK-INSUFFISANT"
    assert "quantité demandée 5" in refused["resultat"]["verdict"]["detail"]
    assert _etat_stock_durable(material) == before


def test_legacy_ne_refuse_pas_le_stock_en_main_de_b_si_a_est_au_rebut(base):
    material, project_a, project_b = (
        "mat-deux-chantiers-fictif", "CH-rebut-a-fictif", "CH-en-main-b-fictif"
    )
    thresholds = [
        {"chantier_id": project_a, "materiau_id": material, "seuil_quantite": 10.0},
        {"chantier_id": project_b, "materiau_id": material, "seuil_quantite": 10.0},
    ]
    rebut = _recevoir_cinq(material, project_a, thresholds)
    depot = _recevoir_cinq(material, project_b, thresholds, statut="conforme")
    assert rebut["ok"] and rebut["resultat"]["accepte"] is True, rebut
    assert depot["ok"] and depot["resultat"]["accepte"] is True, depot
    wct_b = _wct(project_b, "w-en-main-b-fictif")
    _publier_wct(wct_b)

    accepted = _consommer_legacy(wct_b, project_b, [{"materiau_id": material, "quantite": 5.0}])

    assert accepted["ok"] and accepted["resultat"]["accepte"] is True, accepted
    assert accepted["resultat"]["resultat"]["stock_restant"] == [
        {"materiau_id": material, "quantite": 0.0}
    ]


def test_legacy_refuse_si_une_reception_c5_exacte_est_entierement_au_rebut(base):
    material, project_a, project_b = (
        "mat-localisation-limite-fictif", "CH-rebut-local-limite-fictif", "CH-en-main-local-limite-fictif"
    )
    thresholds = [
        {"chantier_id": project_a, "materiau_id": material, "seuil_quantite": 10.0},
        {"chantier_id": project_b, "materiau_id": material, "seuil_quantite": 10.0},
    ]
    rebut = _recevoir_cinq(material, project_a, thresholds)
    depot = _recevoir_cinq(material, project_b, thresholds, statut="conforme")
    assert rebut["ok"] and rebut["resultat"]["accepte"] is True, rebut
    assert depot["ok"] and depot["resultat"]["accepte"] is True, depot
    wct_a = _wct(project_a, "w-localisation-limite-a-fictif")
    _publier_wct(wct_a)

    before = _etat_stock_durable(material)
    refused = _consommer_legacy(wct_a, project_a, [{"materiau_id": material, "quantite": 1.0}])

    assert refused["ok"] and refused["resultat"]["accepte"] is False, refused
    assert refused["resultat"]["verdict"]["code"] == "REJ-STOCK-INSUFFISANT"
    assert "borne supérieure prouvée du stock en main local 0" in refused["resultat"]["verdict"]["detail"]
    assert "aucun mouvement n'a été écrit" in refused["resultat"]["verdict"]["detail"]
    assert _etat_stock_durable(material) == before


def test_borne_locale_exacte_ne_perd_pas_l_unite_apres_grande_mise_au_rebut(base):
    material, project, project_b = (
        "mat-borne-grand-rebut-fictif", "CH-borne-grand-rebut-fictif", "CH-borne-grand-rebut-global-fictif"
    )
    rebut = _recevoir_quantite(material, project, 10**28, statut="endommage", suffix="rebut")
    legacy_reception = _recevoir_quantite(material, project, 1, suffix="legacy")
    stock_global = _recevoir_quantite(material, project_b, 10, statut="conforme", suffix="global")
    assert rebut["ok"] and rebut["resultat"]["accepte"] is True, rebut
    assert legacy_reception["ok"] and legacy_reception["resultat"]["accepte"] is True, legacy_reception
    assert stock_global["ok"] and stock_global["resultat"]["accepte"] is True, stock_global
    wct = _wct(project, "w-borne-grand-rebut-fictif")
    _publier_wct(wct)
    before = _etat_stock_durable(material)

    consumed = _consommer_legacy(wct, project, [{"materiau_id": material, "quantite": 1}])

    assert consumed["ok"] and consumed["resultat"]["accepte"] is True, consumed
    assert _etat_stock_durable(material) != before


def test_borne_locale_exacte_somme_le_rebut_et_dixieme_restant(base):
    material, project, project_b = (
        "mat-borne-dixieme-fictif", "CH-borne-dixieme-fictif", "CH-borne-dixieme-global-fictif"
    )
    rebut = _recevoir_quantite(material, project, 10**27, statut="endommage", suffix="rebut")
    legacy_reception = _recevoir_quantite(material, project, 0.1, suffix="legacy")
    stock_global = _recevoir_quantite(material, project_b, 1, statut="conforme", suffix="global")
    assert rebut["ok"] and rebut["resultat"]["accepte"] is True, rebut
    assert legacy_reception["ok"] and legacy_reception["resultat"]["accepte"] is True, legacy_reception
    assert stock_global["ok"] and stock_global["resultat"]["accepte"] is True, stock_global
    wct = _wct(project, "w-borne-dixieme-fictif")
    _publier_wct(wct)
    before = _etat_stock_durable(material)

    consumed = _consommer_legacy(wct, project, [
        {"materiau_id": material, "quantite": 0.05},
        {"materiau_id": material, "quantite": 0.05},
    ])

    assert consumed["ok"] and consumed["resultat"]["accepte"] is True, consumed
    assert _etat_stock_durable(material) != before


def test_garde_publique_flux_historique_et_4097_lignes_ne_perd_pas_la_preuve_locale(base):
    material = "mat-provenance-flux-4097-fictif"
    project_a = "CH-provenance-flux-A-fictif"
    project_b = "CH-provenance-flux-B-fictif"
    damaged = _recevoir_quantite(material, project_a, 1, statut="endommage", suffix="rebut")
    assert damaged["ok"] and damaged["resultat"]["accepte"] is True, damaged

    # 4096 réceptions exactes supplémentaires sur A + une sur B. Le stock global couvre
    # la demande de 4097 lignes; la borne C5 exacte de A reste 4096 après la mise au rebut.
    with stockage.transaction():
        registry = registre_module.Registre(maillons=stockage.maillons("m06-material-control", "principal"))
        _, error = registry.ajouter_lot([
            {
                "type_mouvement": "RECEPTION", "chantier_id": project_a,
                "materiau_id": material, "quantite": "1", "cout_unitaire": 5.0,
            }
            for _ in range(4096)
        ] + [{
            "type_mouvement": "RECEPTION", "chantier_id": project_b,
            "materiau_id": material, "quantite": "1", "cout_unitaire": 5.0,
        }])
        assert error is None, error
        movements = list(stockage.maillons("m06-material-control", "principal"))
        transfers = list(stockage.maillons("m06-material-control", "emplacements"))

    assert reorder.borne_superieure_en_main_locale(project_a, material, movements, transfers) == Decimal(4096)
    wct = _wct(project_a, "w-provenance-flux-4097-fictif")
    _publier_wct(wct)
    before = _etat_stock_durable(material)
    refused = _consommer_legacy(wct, project_a, [
        {"materiau_id": material, "quantite": 1} for _ in range(4097)
    ])

    assert refused["ok"] and refused["resultat"]["accepte"] is False, refused
    assert refused["resultat"]["verdict"]["code"] == "REJ-STOCK-INSUFFISANT"
    assert "borne supérieure prouvée du stock en main local 4096" in refused["resultat"]["verdict"]["detail"]
    assert _etat_stock_durable(material) == before


def test_public_garde_locale_agrege_4097_lignes_sans_plafond_de_termes(base):
    material = "mat-demande-limite-provenance-fictif"
    project_a = "CH-demande-provenance-A-fictif"
    project_b = "CH-demande-provenance-B-fictif"
    damaged = _recevoir_quantite(material, project_a, 1, statut="endommage", suffix="rebut-A")
    good_b = _recevoir_quantite(material, project_b, 1, statut="conforme", suffix="conforme-B")
    assert damaged["ok"] and damaged["resultat"]["accepte"] is True, damaged
    assert good_b["ok"] and good_b["resultat"]["accepte"] is True, good_b

    with stockage.transaction():
        movements = list(stockage.maillons("m06-material-control", "principal"))
        transfers = list(stockage.maillons("m06-material-control", "emplacements"))
    assert reorder.borne_superieure_en_main_locale(project_a, material, movements, transfers) == Decimal(0)
    wct = _wct(project_a, "w-demande-limite-provenance-fictif")
    _publier_wct(wct)
    before = _etat_stock_durable(material)
    demand = [{"materiau_id": material, "quantite": 0.0001} for _ in range(4097)]
    response = _consommer_legacy(wct, project_a, demand)
    after = _etat_stock_durable(material)

    assert response.get("ok") is True, response
    assert response.get("resultat", {}).get("accepte") is False, response
    assert response["resultat"]["verdict"]["code"] == "REJ-STOCK-INSUFFISANT"
    assert after == before


def test_reception_multiligne_borne_seulement_la_source_finale_exacte(base):
    material_first = "mat-multiligne-premiere-ligne-fictif"
    material_last = "mat-multiligne-derniere-ligne-fictif"
    project = "CH-multiligne-borne-fictif"
    project_other = "CH-multiligne-stock-global-fictif"
    date = "2026-11-03T10:00:00-04:00"
    po_id = "PO-multiligne-borne-fictif"
    thresholds = [
        {"chantier_id": project, "materiau_id": material_first, "seuil_quantite": 10.0},
        {"chantier_id": project, "materiau_id": material_last, "seuil_quantite": 10.0},
    ]
    multi = executer_atomique(_outil("m6_receptionner_commande"), {
        "bon_demande": {
            "po_id": po_id,
            "chantier_id": project,
            "lignes_demandees": [
                {"materiau_id": material_first, "quantite_demandee": 5.0},
                {"materiau_id": material_last, "quantite_demandee": 5.0},
            ],
            "horodatage": date,
        },
        "reception_po": {
            "po_id": po_id,
            "chantier_id": project,
            "lignes_recues": [
                {"materiau_id": material_first, "quantite_recue": 5.0},
                {"materiau_id": material_last, "quantite_recue": 5.0},
            ],
            "horodatage": date,
        },
        "details_reception": [
            {
                "materiau_id": material_first,
                "statut_ligne": "endommage",
                "photos": ["fichier:sha256:" + "cd" * 32],
            },
            {
                "materiau_id": material_last,
                "statut_ligne": "endommage",
                "photos": ["fichier:sha256:" + "ef" * 32],
            },
        ],
        "lieu_livraison": {"type": "depot"},
        "seuils_reorder": thresholds,
        "catalogue_materiaux": {
            "version": "v1",
            "unite_monetaire": "CAD",
            "postes": {
                material_first: {"cout_unitaire": 5.0, "libelle": "Article fictif A"},
                material_last: {"cout_unitaire": 5.0, "libelle": "Article fictif B"},
            },
        },
    })
    assert multi["ok"] and multi["resultat"]["accepte"] is True, multi
    accuse = multi["resultat"]["resultat"]["accuse_reception"]

    # Stocks conformes hors de ce chantier neutralisent le refus global historique.
    stock_first = _recevoir_quantite(material_first, project_other, 5.0, statut="conforme", suffix="global-a")
    stock_last = _recevoir_quantite(material_last, project_other, 5.0, statut="conforme", suffix="global-b")
    assert stock_first["ok"] and stock_first["resultat"]["accepte"] is True, stock_first
    assert stock_last["ok"] and stock_last["resultat"]["accepte"] is True, stock_last

    with stockage.transaction():
        mouvements = list(stockage.maillons("m06-material-control", "principal"))
        transferts = list(stockage.maillons("m06-material-control", "emplacements"))
    assert registre_module.Registre(maillons=mouvements).valider_chaine()[0] is True
    assert emplacements.valider_chaine(transferts)[0] is True
    mouvements_cibles = {
        materiau_id: next(
            mouvement for mouvement in mouvements
            if mouvement.get("chantier_id") == project and mouvement.get("materiau_id") == materiau_id
            and mouvement.get("type_mouvement") == "RECEPTION"
        )
        for materiau_id in (material_first, material_last)
    }
    assert mouvements_cibles[material_last]["hash_maillon"] == accuse["hash_maillon"]
    for materiau_id, mouvement in mouvements_cibles.items():
        references = [
            transfert["reference_source"] for transfert in transferts
            if transfert.get("materiau_id") == materiau_id and "reference_source" in transfert
            and transfert["reference_source"]["mouvement"]["index"] == mouvement["index"]
        ]
        assert references and all(reference["hash_reception"] == accuse["hash_maillon"] for reference in references)

    # L'avant-dernière ligne ne peut pas prouver sa clôture exacte; la dernière la prouve et borne le rebut à zéro.
    assert reorder.borne_superieure_en_main_locale(project, material_first, mouvements, transferts) is None
    assert reorder.borne_superieure_en_main_locale(project, material_last, mouvements, transferts) == Decimal(0)

    wct_first = _wct(project, "w-multiligne-premiere-ligne-fictif")
    _publier_wct(wct_first)
    consumed_first = _consommer_legacy(wct_first, project, [{"materiau_id": material_first, "quantite": 1.0}])
    assert consumed_first["ok"] and consumed_first["resultat"]["accepte"] is True, consumed_first

    wct_last = _wct(project, "w-multiligne-derniere-ligne-fictif")
    _publier_wct(wct_last)
    before_last = _etat_stock_durable(material_last)
    consumed_last = _consommer_legacy(wct_last, project, [{"materiau_id": material_last, "quantite": 1.0}])
    assert consumed_last["ok"] and consumed_last["resultat"]["accepte"] is False, consumed_last
    assert consumed_last["resultat"]["verdict"]["code"] == "REJ-STOCK-INSUFFISANT"
    assert "borne supérieure prouvée du stock en main local 0" in consumed_last["resultat"]["verdict"]["detail"]
    assert _etat_stock_durable(material_last) == before_last


def test_rejeu_wct_garde_le_refus_idempotent_avant_la_nouvelle_borne(base):
    material, project_a, project_b = (
        "mat-borne-idempotence-fictif", "CH-borne-idempotence-a-fictif", "CH-borne-idempotence-b-fictif"
    )
    seuils = [
        {"chantier_id": project_a, "materiau_id": material, "seuil_quantite": 10.0},
        {"chantier_id": project_b, "materiau_id": material, "seuil_quantite": 10.0},
    ]
    _recevoir_cinq(material, project_a, seuils, statut="endommage")
    _recevoir_cinq(material, project_b, seuils, statut="conforme")
    wct = _wct(project_b, "w-borne-idempotence-fictif")
    _publier_wct(wct)
    first = _consommer_legacy(wct, project_b, [{"materiau_id": material, "quantite": 1.0}])
    assert first["ok"] and first["resultat"]["accepte"] is True, first

    replay = _consommer_legacy(wct, project_a, [{"materiau_id": material, "quantite": 1.0}])

    assert replay["ok"] and replay["resultat"]["accepte"] is False, replay
    assert replay["resultat"]["verdict"]["code"] == "REJ-DECLARATION-DEJA-SOUMISE"


@pytest.mark.parametrize("quantite,accepte", [(5.0, True), (5.01, False)])
def test_legacy_borne_locale_exacte_c5_accepte_egalite_et_refuse_le_depassement(base, quantite, accepte):
    material, project = "mat-borne-exacte-fictif", "CH-borne-exacte-fictif"
    seuils = [{"chantier_id": project, "materiau_id": material, "seuil_quantite": 10.0}]
    endommage = _recevoir_cinq(material, project, seuils, statut="endommage")
    conforme = _recevoir_cinq(material, project, seuils, statut="conforme", suffix="conforme")
    assert endommage["ok"] and endommage["resultat"]["accepte"] is True, endommage
    assert conforme["ok"] and conforme["resultat"]["accepte"] is True, conforme
    wct = _wct(project, f"w-borne-exacte-{quantite}-fictif")
    _publier_wct(wct)
    before = _etat_stock_durable(material)

    resultat = _consommer_legacy(wct, project, [{"materiau_id": material, "quantite": quantite}])

    assert resultat["ok"] and resultat["resultat"]["accepte"] is accepte, resultat
    if accepte:
        assert resultat["resultat"]["resultat"]["stock_restant"] == [
            {"materiau_id": material, "quantite": 5.0}
        ]
    else:
        assert resultat["resultat"]["verdict"]["code"] == "REJ-STOCK-INSUFFISANT"
        assert "borne supérieure prouvée du stock en main local 5" in resultat["resultat"]["verdict"]["detail"]
        assert _etat_stock_durable(material) == before


@pytest.mark.parametrize("quantite", [float("nan"), float("inf"), float("-inf")], ids=["nan", "inf", "-inf"])
def test_borne_locale_ne_preempte_pas_le_refus_des_quantites_non_finies(base, quantite):
    material, project_a, project_b = (
        "mat-borne-non-fini-fictif", "CH-borne-non-fini-a-fictif", "CH-borne-non-fini-b-fictif"
    )
    seuils = [
        {"chantier_id": project_a, "materiau_id": material, "seuil_quantite": 10.0},
        {"chantier_id": project_b, "materiau_id": material, "seuil_quantite": 10.0},
    ]
    _recevoir_cinq(material, project_a, seuils, statut="endommage")
    _recevoir_cinq(material, project_b, seuils, statut="conforme")
    wct = _wct(project_a, f"w-borne-non-fini-{quantite}-fictif")
    _publier_wct(wct)
    before = _etat_stock_durable(material)

    refused = _consommer_legacy(wct, project_a, [{"materiau_id": material, "quantite": quantite}])

    assert refused["ok"] is True, refused
    assert refused["resultat"]["accepte"] is False, refused
    assert refused["resultat"]["verdict"]["code"] == "REJ-FORMULAIRE-LIGNE-INVALIDE"
    assert _etat_stock_durable(material) == before


@pytest.mark.parametrize(
    "quantite,code_attendu",
    [
        (True, "REJ-FORMULAIRE-LIGNE-INVALIDE"),
        (10**400, "REJ-STOCK-INSUFFISANT"),
        ("5", "REJ-FORMULAIRE-LIGNE-INVALIDE"),
        ("NaN", "REJ-FORMULAIRE-LIGNE-INVALIDE"),
        ("Infinity", "REJ-FORMULAIRE-LIGNE-INVALIDE"),
    ],
    ids=["bool", "grand-entier", "texte-decimal", "texte-nan", "texte-infini"],
)
def test_appel_direct_garde_le_verdict_pour_types_et_entiers_extremes(base, quantite, code_attendu):
    material, project_a, project_b = (
        "mat-borne-types-direct-fictif", "CH-borne-types-direct-a-fictif", "CH-borne-types-direct-b-fictif"
    )
    seuils = [
        {"chantier_id": project_a, "materiau_id": material, "seuil_quantite": 10.0},
        {"chantier_id": project_b, "materiau_id": material, "seuil_quantite": 10.0},
    ]
    _recevoir_cinq(material, project_a, seuils, statut="endommage")
    _recevoir_cinq(material, project_b, seuils, statut="conforme")
    wct = _wct(project_a, f"w-borne-types-{quantite!r}-fictif")
    _publier_wct(wct)
    before = _etat_stock_durable(material)

    refused = _consommer_legacy_direct(wct, project_a, [{"materiau_id": material, "quantite": quantite}])

    assert refused["accepte"] is False, refused
    assert refused["verdict"]["code"] == code_attendu, refused
    assert _etat_stock_durable(material) == before


def test_borne_locale_reste_indeterminee_apres_un_transfert_sans_source(base):
    material, project_a, project_b = (
        "mat-borne-transfert-ambigu-fictif", "CH-borne-transfert-a-fictif", "CH-borne-transfert-b-fictif"
    )
    seuils = [
        {"chantier_id": project_a, "materiau_id": material, "seuil_quantite": 10.0},
        {"chantier_id": project_b, "materiau_id": material, "seuil_quantite": 10.0},
    ]
    _recevoir_cinq(material, project_a, seuils, statut="endommage")
    _recevoir_cinq(material, project_b, seuils, statut="conforme")
    transfert = executer_atomique(_outil("m6_transferer_stock"), {
        "transfert_id": "T-reliberation-ambigue-fictif",
        "materiau_id": material,
        "quantite": 5.0,
        "de": {"type": "rebut"},
        "vers": {"type": "depot"},
        "motif": "cas fictif à source non liée",
        "horodatage": "2026-11-03T11:00:00-04:00",
    })
    assert transfert["ok"] and transfert["resultat"]["accepte"] is True, transfert
    with stockage.transaction():
        mouvements = list(stockage.maillons("m06-material-control", "principal"))
        emplacements = list(stockage.maillons("m06-material-control", "emplacements"))
    assert reorder.borne_superieure_en_main_locale(project_a, material, mouvements, emplacements) is None

    # La garde ciblée ne reconstitue pas le lot et laisse le chemin historique inchangé.
    wct = _wct(project_a, "w-borne-transfert-ambigu-fictif")
    _publier_wct(wct)
    legacy = _consommer_legacy(wct, project_a, [{"materiau_id": material, "quantite": 1.0}])
    assert legacy["ok"] and legacy["resultat"]["accepte"] is True, legacy


def test_borne_locale_reste_indeterminee_apres_une_sortie_deja_declaree(base):
    material, project_a, project_b = (
        "mat-borne-sortie-ambigue-fictif", "CH-borne-sortie-a-fictif", "CH-borne-sortie-b-fictif"
    )
    seuils = [
        {"chantier_id": project_a, "materiau_id": material, "seuil_quantite": 10.0},
        {"chantier_id": project_b, "materiau_id": material, "seuil_quantite": 10.0},
    ]
    _recevoir_cinq(material, project_a, seuils, statut="endommage")
    _recevoir_cinq(material, project_b, seuils, statut="conforme")

    wct_declaratif = _wct(project_a, "w-declaratif-sortie-ambigue-fictif")
    _publier_wct(wct_declaratif)
    declaration = executer_atomique(_outil("m6_declarer_materiaux_utilises"), {
        "wct_id": wct_declaratif["wct_id"],
        "formulaire": {
            "wct_id": wct_declaratif["wct_id"],
            "intervention_id": wct_declaratif["intervention_id"],
            "chantier_id": project_a,
            "lignes_materiaux": [{
                "type_ligne": "prevu", "materiau_id": material, "quantite": 1.0,
                "unite": "boite", "quantite_estimee": 1.0,
            }],
        },
    })
    assert declaration["ok"] and declaration["resultat"]["accepte"] is True, declaration
    with stockage.transaction():
        mouvements = list(stockage.maillons("m06-material-control", "principal"))
        emplacements = list(stockage.maillons("m06-material-control", "emplacements"))
    assert reorder.borne_superieure_en_main_locale(project_a, material, mouvements, emplacements) is None

    # Une sortie historique existante rend la localisation non attribuable par ce garde; aucune source
    # n'est réaffectée et le formulaire déclaratif C5/M6 reste inchangé.
    wct_legacy = _wct(project_a, "w-legacy-sortie-ambigue-fictif")
    _publier_wct(wct_legacy)
    legacy = _consommer_legacy(wct_legacy, project_a, [{"materiau_id": material, "quantite": 1.0}])
    assert legacy["ok"] and legacy["resultat"]["accepte"] is True, legacy


def test_borne_locale_reste_indeterminee_apres_un_transfert_interchantier(base):
    material, project_a, project_b = (
        "mat-borne-interchantier-fictif", "CH-borne-interchantier-a-fictif", "CH-borne-interchantier-b-fictif"
    )
    seuils = [
        {"chantier_id": project_a, "materiau_id": material, "seuil_quantite": 10.0},
        {"chantier_id": project_b, "materiau_id": material, "seuil_quantite": 10.0},
    ]
    _recevoir_cinq(material, project_a, seuils, statut="endommage")
    _recevoir_cinq(material, project_b, seuils, statut="conforme")
    transfert = executer_atomique(_outil("m6_transferer_stock"), {
        "transfert_id": "T-interchantier-ambigu-fictif",
        "materiau_id": material,
        "quantite": 5.0,
        "de": {"type": "depot"},
        "vers": {"type": "chantier", "reference": project_a},
        "motif": "transfert entre chantiers fictif sans source",
        "horodatage": "2026-11-03T11:00:00-04:00",
    })
    assert transfert["ok"] and transfert["resultat"]["accepte"] is True, transfert
    with stockage.transaction():
        mouvements = list(stockage.maillons("m06-material-control", "principal"))
        emplacements = list(stockage.maillons("m06-material-control", "emplacements"))
    assert reorder.borne_superieure_en_main_locale(project_a, material, mouvements, emplacements) is None

    # Le mouvement physique vers A est ambigu quant à sa source : le garde n'invente ni le lot ni son attribution.
    wct = _wct(project_a, "w-borne-interchantier-ambigu-fictif")
    _publier_wct(wct)
    legacy = _consommer_legacy(wct, project_a, [{"materiau_id": material, "quantite": 5.0}])
    assert legacy["ok"] and legacy["resultat"]["accepte"] is True, legacy


@pytest.mark.parametrize("registre", ["principal", "emplacements"])
def test_legacy_refuse_si_une_chaine_de_stock_est_invalide_sans_ecriture(base, registre):
    material, project = "mat-chaine-invalide-fictif", "CH-chaine-invalide-fictif"
    received = _recevoir_cinq(material, project, [])
    assert received["ok"] and received["resultat"]["accepte"] is True, received
    wct = _wct(project, "w-chaine-invalide-fictif")
    _publier_wct(wct)
    with stockage.transaction() as cnx:
        row = cnx.execute(select(REGISTRES.c.maillon).where(
            REGISTRES.c.departement == "m06-material-control",
            REGISTRES.c.registre == registre,
            REGISTRES.c.rang == 0,
        )).scalar_one()
        maillon = stockage.codec.decoder(row)
        maillon["hash_maillon"] = "0" * 64
        cnx.execute(update(REGISTRES).where(
            REGISTRES.c.departement == "m06-material-control",
            REGISTRES.c.registre == registre,
            REGISTRES.c.rang == 0,
        ).values(maillon=stockage.codec.encoder(maillon)))
    before = _etat_stock_durable(material)

    refused = _consommer_legacy(wct, project, [{"materiau_id": material, "quantite": 5.0}])

    assert refused["ok"] and refused["resultat"]["accepte"] is False, refused
    assert refused["resultat"]["verdict"]["code"] == "REJ-REGISTRE-INVALIDE"
    assert "disponibilité physique n'est pas vérifiable" in refused["resultat"]["verdict"]["detail"]
    assert _etat_stock_durable(material) == before


def test_legacy_accepte_l_egalite_quand_cinq_unites_sont_en_main_courantes(base):
    material, project = "mat-en-main-fictif", "CH-en-main-fictif"
    thresholds = [{"chantier_id": project, "materiau_id": material, "seuil_quantite": 10.0}]
    received = _recevoir_cinq(material, project, thresholds, statut="conforme")
    assert received["ok"] and received["resultat"]["accepte"] is True, received
    wct = _wct(project, "w-en-main-fictif")
    _publier_wct(wct)

    accepted = executer_atomique(_outil("m6_consommer_materiaux"), {
        "wct": wct,
        "formulaire": {
            "wct_id": wct["wct_id"],
            "intervention_id": wct["intervention_id"],
            "chantier_id": project,
            "lignes_consommees": [{"materiau_id": material, "quantite": 5.0}],
        },
    })
    assert accepted["ok"] and accepted["resultat"]["accepte"] is True, accepted
    assert accepted["resultat"]["resultat"]["stock_restant"] == [{"materiau_id": material, "quantite": 0.0}]


def test_legacy_historique_sans_emplacements_garde_la_consommation_existante(base):
    material, project = "mat-legacy-inconnu-fictif", "CH-legacy-inconnu-fictif"
    date = "2026-11-03T10:00:00-04:00"
    received = executer_atomique(_outil("m6_receptionner_commande"), {
        "bon_demande": {
            "po_id": "PO-legacy-inconnu-fictif",
            "chantier_id": project,
            "lignes_demandees": [{"materiau_id": material, "quantite_demandee": 5.0}],
            "horodatage": date,
        },
        "reception_po": {
            "po_id": "PO-legacy-inconnu-fictif",
            "chantier_id": project,
            "lignes_recues": [{"materiau_id": material, "quantite_recue": 5.0}],
            "horodatage": date,
        },
        "catalogue_materiaux": {
            "version": "v1",
            "unite_monetaire": "CAD",
            "postes": {material: {"cout_unitaire": 5.0, "libelle": "Article fictif"}},
        },
    })
    assert received["ok"] and received["resultat"]["accepte"] is True, received
    assert _etat_stock_durable(material)[3] == []

    wct = _wct(project, "w-legacy-inconnu-fictif")
    _publier_wct(wct)
    accepted = executer_atomique(_outil("m6_consommer_materiaux"), {
        "wct": wct,
        "formulaire": {
            "wct_id": wct["wct_id"],
            "intervention_id": wct["intervention_id"],
            "chantier_id": project,
            "lignes_consommees": [{"materiau_id": material, "quantite": 5.0}],
        },
    })
    assert accepted["ok"] and accepted["resultat"]["accepte"] is True, accepted


def test_legacy_sans_stockage_refuse_le_wct_car_la_source_canonique_est_inaccessible():
    assert stockage.connexion_courante() is None
    wct = _wct("CH-sans-stockage-fictif", "w-sans-stockage-fictif")
    refused = executer(_outil("m6_consommer_materiaux"), {
        "wct": wct,
        "formulaire": {
            "wct_id": wct["wct_id"],
            "intervention_id": wct["intervention_id"],
            "chantier_id": "CH-sans-stockage-fictif",
            "lignes_consommees": [{"materiau_id": "mat-sans-stockage-fictif", "quantite": 1.0}],
        },
    })
    assert refused["ok"] and refused["resultat"] == {
        "accepte": False, "verdict": {"code": "REJ-WCT-INCONNU"}
    }


def test_declaratif_facte_deja_accompli_reste_accepte_et_lecture_expose_le_stock_incoherent(base):
    material, project = "mat-consomme-rebut-fictif", "CH-consomme-rebut-fictif"
    thresholds = [{"chantier_id": project, "materiau_id": material, "seuil_quantite": 10.0}]
    received = _recevoir_cinq(material, project, thresholds)
    assert received["ok"] and received["resultat"]["accepte"] is True, received
    wct = _wct(project, "w-declaratif-rebut-fictif")
    _publier_wct(wct)
    declaration = executer_atomique(_outil("m6_declarer_materiaux_utilises"), {
        "wct_id": wct["wct_id"],
        "formulaire": {
            "wct_id": wct["wct_id"],
            "intervention_id": wct["intervention_id"],
            "chantier_id": project,
            "lignes_materiaux": [{
                "type_ligne": "prevu", "materiau_id": material, "quantite": 5.0,
                "unite": "boite", "quantite_estimee": 5.0,
            }],
        },
    })
    assert declaration["ok"] and declaration["resultat"]["accepte"] is True, declaration

    lecture = executer_atomique(_outil("m6_lire_disponibilite"), {"materiau_ids": [material]})
    assert lecture["ok"] and lecture["resultat"]["accepte"] is True, lecture
    article = lecture["resultat"]["resultat"]["articles"][0]
    assert article["en_main"] == article["disponible"] == "-5"
    assert article["par_emplacement"] == {"rebut": "5", "inconnu": "-5"}


def test_formulaire_malforme_avec_materiau_valide_refuse_sans_ecriture(base):
    material, project = "mat-malforme-fictif", "CH-malforme-fictif"
    wct = _wct(project, "w-malforme-fictif")
    _publier_wct(wct)
    before = _etat_stock_durable(material)

    for lines in (
        [{"materiau_id": material}],
        [{"materiau_id": material, "quantite": "bad"}],
        [{"materiau_id": material, "quantite": 1.0}, "extra"],
    ):
        result = executer_atomique(_outil("m6_consommer_materiaux"), {
            "wct": wct,
            "formulaire": {
                "wct_id": wct["wct_id"],
                "intervention_id": wct["intervention_id"],
                "chantier_id": project,
                "lignes_consommees": lines,
            },
        })
        assert result["ok"] is True, result
        assert result["resultat"]["accepte"] is False, result
        assert result["resultat"]["verdict"]["code"] == "REJ-FORMULAIRE-LIGNE-INVALIDE", result
        assert _etat_stock_durable(material) == before
