"""Repro fictive du prélèvement de stock théorique déjà localisé au rebut."""

from __future__ import annotations

import m6_material_control.outils as m6_outils
import pytest
from sqlalchemy import func, select, update

from opsys import evenements, stockage
from opsys.outils import executer, executer_atomique
from opsys.stockage.schema import EVENEMENTS_SORTANTS, REGISTRES


@pytest.fixture
def base(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'm6-rebut-consumption-fictif.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    try:
        yield url
    finally:
        stockage.liberer()


def _outil(nom):
    return next(outil for outil in m6_outils.outils() if outil.nom == nom)


def _recevoir_cinq(material, project, thresholds, statut="endommage"):
    date = "2026-11-03T10:00:00-04:00"
    po_id = f"PO-consomme-rebut-fictif-{project}"
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
        "details_reception": [{
            "materiau_id": material,
            "statut_ligne": statut,
            **({"photos": ["fichier:sha256:" + "cd" * 32]} if statut == "endommage" else {}),
        }],
        "lieu_livraison": {"type": "depot"},
        "seuils_reorder": thresholds,
        "catalogue_materiaux": {
            "version": "v1",
            "unite_monetaire": "CAD",
            "postes": {material: {"cout_unitaire": 5.0, "libelle": "Article fictif"}},
        },
    })


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
    received = _recevoir_cinq(material, project, thresholds)
    assert received["ok"] and received["resultat"]["accepte"] is True, received

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


def test_legacy_global_suffisant_ne_prouve_pas_le_stock_local_de_a(base):
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

    # Limite documentée : le garde agrégé ne prouve pas que la quantité du chantier A
    # soit physiquement dans A; l'ancien contrat ne reconstruit pas cette attribution.
    accepted = _consommer_legacy(wct_a, project_a, [{"materiau_id": material, "quantite": 5.0}])

    assert accepted["ok"] and accepted["resultat"]["accepte"] is True, accepted


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
