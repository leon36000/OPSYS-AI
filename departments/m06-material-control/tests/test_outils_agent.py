"""Capacités d'agent de M6 : contrat des outils et chaîne matériel composée."""

from __future__ import annotations

from pathlib import Path

from m6_material_control.outils import outils

from opsys.departements import lire_manifeste
from opsys.outils import Autonomie, executer


def _outil(nom):
    return next(o for o in outils() if o.nom == nom)


def _bon_demande(po_id="PO-1", chantier_id="C1", lignes=None):
    return {
        "po_id": po_id,
        "chantier_id": chantier_id,
        "lignes_demandees": lignes or [{"materiau_id": "MAT-1", "quantite_demandee": 10.0}],
        "horodatage": "2026-01-01T00:00:00Z",
    }


def _reception_po(po_id="PO-1", chantier_id="C1", lignes=None):
    return {
        "po_id": po_id,
        "chantier_id": chantier_id,
        "lignes_recues": lignes or [{"materiau_id": "MAT-1", "quantite_recue": 10.0}],
        "horodatage": "2026-01-02T00:00:00Z",
    }


def _catalogue(cout=5.0):
    return {"version": "v1", "unite_monetaire": "CAD", "postes": {"MAT-1": {"cout_unitaire": cout, "libelle": "x"}}}


def _wct():
    return {
        "wct_id": "w1",
        "intervention_id": "i1",
        "lead_id": "l1",
        "technicien_id": "t1",
        "horodatage_completion": "2026-01-03T00:00:00Z",
        "fix_gps_completion": {"latitude": 1.0, "longitude": 2.0},
        "duree_reelle_minutes": 30,
        "ecart_signale": False,
        "revue_id": None,
        "hash_maillon": "a" * 64,
        "consommateurs_cibles": ["M6"],
        "devis_id": None,
    }


def test_manifeste_et_outils_coherents():
    dep = lire_manifeste(Path(__file__).resolve().parents[1])
    noms = [o.nom for o in dep.charger_outils()]
    assert noms[0] == "m6_receptionner_commande"
    assert all(nom.startswith("m6_") for nom in noms)
    assert dep.mode == "ombre"
    assert dep.dependances == ("m04-field-ops",)


def test_autonomie_respecte_la_regle_finance():
    """M6 ne porte aucune écriture financière (elle signale, jamais ne paie) :
    ses écritures de registre interne restent T1 ; lecture/calcul = T0."""
    assert _outil("m6_receptionner_commande").autonomie == Autonomie.T1
    assert _outil("m6_consommer_materiaux").autonomie == Autonomie.T1
    assert _outil("m6_soumettre_comptage").autonomie == Autonomie.T1
    assert _outil("m6_produire_digest").autonomie == Autonomie.T0
    assert _outil("m6_resoudre_prix_materiau").autonomie == Autonomie.T0


# --- m6_receptionner_commande : composé de bout en bout ---------------------


def test_receptionner_commande_nominal_ecrit_le_stock_et_signale_m5():
    reponse = executer(
        _outil("m6_receptionner_commande"),
        {"bon_demande": _bon_demande(), "reception_po": _reception_po(), "catalogue_materiaux": _catalogue()},
    )

    assert reponse["ok"] is True
    resultat = reponse["resultat"]["resultat"]
    assert resultat["accuse_reception"]["verdict_reception"] == "CONFORME"
    assert resultat["signal_po_a_payer"]["montant_total_estime"] == 50.0
    assert reponse["resultat"]["registre_historique"][0]["type_mouvement"] == "RECEPTION"


def test_receptionner_commande_sans_catalogue_n_emet_aucun_signal_po():
    reponse = executer(
        _outil("m6_receptionner_commande"),
        {"bon_demande": _bon_demande(), "reception_po": _reception_po()},
    )

    assert reponse["ok"] is True
    resultat = reponse["resultat"]["resultat"]
    assert resultat["accuse_reception"]["montant_total_estime"] is None
    assert resultat["signal_po_a_payer"] is None
    # Le stock physique est écrit malgré tout (DA-M6-08).
    assert reponse["resultat"]["registre_historique"][0]["quantite"] == 10.0


def test_receptionner_commande_po_incoherent_est_un_refus_sans_ecriture():
    reponse = executer(
        _outil("m6_receptionner_commande"),
        {
            "bon_demande": _bon_demande(po_id="PO-A"),
            "reception_po": _reception_po(po_id="PO-DIFFERENT"),
            "catalogue_materiaux": _catalogue(),
        },
    )

    assert reponse["ok"] is True
    resultat = reponse["resultat"]["resultat"]
    assert resultat["accuse_reception"]["verdict_reception"] == "INDETERMINE"
    assert reponse["resultat"]["registre_historique"] == []


def test_receptionner_commande_rejette_une_cle_interdite_glissee_dans_une_ligne():
    """Bug NEW-PROD corrigé : frontieres.py était jamais câblé, une clé comme
    « virement » traversait silencieusement les entrées de M6."""
    bon = _bon_demande()
    bon["lignes_demandees"][0]["virement"] = "virement-001"

    reponse = executer(
        _outil("m6_receptionner_commande"),
        {"bon_demande": bon, "reception_po": _reception_po(), "catalogue_materiaux": _catalogue()},
    )

    assert reponse["ok"] is True
    assert reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "REJ-FRONTIERE-VIOLEE"


def test_receptionner_commande_parametre_requis_manquant_est_un_refus_de_schema():
    reponse = executer(_outil("m6_receptionner_commande"), {"bon_demande": _bon_demande()})

    assert reponse["ok"] is False
    assert reponse["erreur"] == "arguments_invalides"


# --- m6_consommer_materiaux : chaîné à une réception préalable --------------


def test_consommer_materiaux_apres_reception_reussit_bug_stock_insuffisant_corrige():
    r1 = executer(
        _outil("m6_receptionner_commande"),
        {"bon_demande": _bon_demande(), "reception_po": _reception_po(), "catalogue_materiaux": _catalogue()},
    )
    historique = r1["resultat"]["registre_historique"]

    formulaire = {
        "wct_id": "w1",
        "intervention_id": "i1",
        "chantier_id": "C1",
        "lignes_consommees": [{"materiau_id": "MAT-1", "quantite": 4.0}],
    }
    r2 = executer(
        _outil("m6_consommer_materiaux"),
        {"wct": _wct(), "formulaire": formulaire, "registre_historique": historique},
    )

    assert r2["ok"] is True
    assert r2["resultat"]["accepte"] is True
    assert r2["resultat"]["resultat"]["stock_restant"] == [{"materiau_id": "MAT-1", "quantite": 6.0}]


def test_consommer_materiaux_sans_stock_prealable_est_refuse_nomme():
    formulaire = {
        "wct_id": "w1",
        "intervention_id": "i1",
        "chantier_id": "C1",
        "lignes_consommees": [{"materiau_id": "MAT-1", "quantite": 4.0}],
    }

    reponse = executer(_outil("m6_consommer_materiaux"), {"wct": _wct(), "formulaire": formulaire})

    assert reponse["ok"] is True
    assert reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "REJ-STOCK-INSUFFISANT"


# --- m6_soumettre_comptage ---------------------------------------------------


def test_soumettre_comptage_apres_reception_ecrit_la_variance():
    r1 = executer(
        _outil("m6_receptionner_commande"),
        {"bon_demande": _bon_demande(), "reception_po": _reception_po(), "catalogue_materiaux": _catalogue()},
    )
    historique = r1["resultat"]["registre_historique"]

    comptage = {
        "chantier_id": "C1",
        "materiau_id": "MAT-1",
        "quantite_comptee": 7.0,
        "horodatage": "2026-01-05T00:00:00Z",
    }
    r2 = executer(_outil("m6_soumettre_comptage"), {"comptage": comptage, "registre_historique": historique})

    assert r2["ok"] is True
    resultat = r2["resultat"]["resultat"]
    assert resultat["verdict_variance"] == "STOCK_INFERIEUR_AU_THEORIQUE"
    assert resultat["ecart"] == -3.0
    assert resultat["note_investigation"] is None
    assert len(r2["resultat"]["registre_historique"]) == 2


def test_soumettre_comptage_sans_mouvement_prealable_est_indetermine():
    comptage = {
        "chantier_id": "C-JAMAIS-VU",
        "materiau_id": "MAT-JAMAIS-VU",
        "quantite_comptee": 5.0,
        "horodatage": "2026-01-05T00:00:00Z",
    }

    reponse = executer(_outil("m6_soumettre_comptage"), {"comptage": comptage})

    assert reponse["ok"] is True
    assert reponse["resultat"]["resultat"]["verdict_variance"] == "INDETERMINE"
    assert reponse["resultat"]["registre_historique"] == []


# --- m6_produire_digest / m6_resoudre_prix_materiau : lecture seule ---------


def test_produire_digest_reproductible_sur_le_meme_historique():
    r1 = executer(
        _outil("m6_receptionner_commande"),
        {"bon_demande": _bon_demande(), "reception_po": _reception_po(), "catalogue_materiaux": _catalogue()},
    )
    historique = r1["resultat"]["registre_historique"]

    d1 = executer(_outil("m6_produire_digest"), {"registre_historique": historique})
    d2 = executer(_outil("m6_produire_digest"), {"registre_historique": historique})

    assert d1["ok"] is True and d2["ok"] is True
    assert d1["resultat"] == d2["resultat"]
    assert d1["resultat"]["type"] == "DIGEST_MATERIEL"


def test_resoudre_prix_materiau_indetermine_sans_catalogue_ni_historique():
    reponse = executer(_outil("m6_resoudre_prix_materiau"), {"materiau_id": "MAT-INCONNU"})

    assert reponse["ok"] is True
    assert reponse["resultat"]["verdict_resolution_prix"] == "INDETERMINE"
    assert reponse["resultat"]["cout_unitaire_resolu"] is None
