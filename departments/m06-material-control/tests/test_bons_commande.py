"""bons_commande.py — PLAN T2.5 point 1/3/4 (M6.5). Lève DA-M6-12 (docs/bmad/03-ARCHITECTURE.md).
Module pur : tous les registres (PO, prix, fournisseurs, mouvements) sont de simples listes Python
en mémoire ici — la persistance durable (`opsys.stockage.maillons`) est prouvée séparément dans
``test_registre_durable.py``.
"""

from __future__ import annotations

import copy
import hashlib
import json

import pytest
from m6_material_control import bons_commande, contrats, fournisseurs, livre_prix
from m6_material_control.registre import Registre

CONDITIONS_PO = {"date_requise": "2099-12-31", "mode_livraison": "ramassage"}


def _fournisseurs_avec_gentek(courriel="commandes@gentek.exemple-fictif.test"):
    registre: list[dict] = []
    fournisseurs.enregistrer_fournisseur(
        "gentek", "Gentek", "2026-01-01T00:00:00Z", registre, courriel_commande=courriel
    )
    return registre


def _prix_gentek(prix_unitaire=10.0):
    registre: list[dict] = []
    livre_prix.enregistrer_prix("MAT-1", "gentek", prix_unitaire, "CAD", "2026-01-01", registre)
    return registre


def _creer_po(
    po_id="PO-1", chantier_id="C1", lignes=None, registre_po=None,
    registre_prix=None, registre_fournisseurs=None,
):
    lignes = lignes if lignes is not None else [{"materiau_id": "MAT-1", "quantite_nette": 5.0, "unite": "boite"}]
    registre_po = [] if registre_po is None else registre_po
    registre_prix = _prix_gentek() if registre_prix is None else registre_prix
    registre_fournisseurs = _fournisseurs_avec_gentek() if registre_fournisseurs is None else registre_fournisseurs
    po, verdict = bons_commande.creer_brouillon(
        po_id, chantier_id, "gentek", lignes, "2026-01-02T00:00:00Z",
        registre_po, registre_prix, registre_fournisseurs, conditions=CONDITIONS_PO)
    assert verdict is None, verdict
    return po, registre_po


# ------------------------------------------------------------------------------- calculer_lignes


def test_calculer_lignes_a_commander_ecart_positif():
    registre = Registre()
    registre.ajouter({"type_mouvement": "RECEPTION", "chantier_id": "C1", "materiau_id": "MAT-1",
                       "quantite": 3.0, "cout_unitaire": 10.0})
    besoins = [{"materiau_id": "MAT-1", "quantite_estimee": 10.0, "unite": "boite"}]
    lignes = bons_commande.calculer_lignes_a_commander(besoins, "C1", registre)
    assert lignes == [{"materiau_id": "MAT-1", "quantite_nette": 7.0, "unite": "boite"}]


def test_calculer_lignes_a_commander_stock_suffisant_omet_la_ligne():
    registre = Registre()
    registre.ajouter({"type_mouvement": "RECEPTION", "chantier_id": "C1", "materiau_id": "MAT-1",
                       "quantite": 20.0, "cout_unitaire": 10.0})
    besoins = [{"materiau_id": "MAT-1", "quantite_estimee": 10.0, "unite": "boite"}]
    assert bons_commande.calculer_lignes_a_commander(besoins, "C1", registre) == []


def test_calculer_lignes_a_commander_aucun_stock_commande_tout():
    registre = Registre()
    besoins = [{"materiau_id": "MAT-1", "quantite_estimee": 10.0, "unite": "boite"}]
    assert bons_commande.calculer_lignes_a_commander(besoins, "C1", registre) == [
        {"materiau_id": "MAT-1", "quantite_nette": 10.0, "unite": "boite"}
    ]


# ---------------------------------------------------------------------------- transition_autorisee


def test_transition_autorisee_exhaustive_12x12():
    """Preuve exhaustive (audit M6 §5, Phase 1 tâche 5) : les 12 statuts nommés par
    DEFINITION-PRODUIT.md §7 M6.5, chaque paire testée contre une table ATTENDUE écrite ici,
    INDÉPENDANTE de contrats.TRANSITIONS_PO (comparer le module à lui-même serait tautologique)."""
    statuts = (
        "draft", "pending_admin_review", "approved", "email_ready", "sent_to_supplier",
        "supplier_confirmed", "partially_received", "received", "cancelled", "disputed",
        "invoiced", "closed",
    )
    assert set(statuts) == contrats.STATUTS_PO
    assert len(statuts) == 12

    attendues = {
        ("draft", "pending_admin_review"), ("draft", "approved"), ("draft", "cancelled"),
        ("pending_admin_review", "approved"), ("pending_admin_review", "cancelled"),
        ("approved", "email_ready"), ("approved", "cancelled"),
        ("email_ready", "sent_to_supplier"), ("email_ready", "cancelled"),
        ("sent_to_supplier", "supplier_confirmed"), ("sent_to_supplier", "partially_received"),
        ("sent_to_supplier", "received"), ("sent_to_supplier", "disputed"), ("sent_to_supplier", "cancelled"),
        ("supplier_confirmed", "partially_received"), ("supplier_confirmed", "received"),
        ("supplier_confirmed", "disputed"), ("supplier_confirmed", "cancelled"),
        ("partially_received", "partially_received"), ("partially_received", "received"),
        ("partially_received", "disputed"),
        ("received", "invoiced"), ("received", "disputed"),
        ("invoiced", "closed"), ("invoiced", "disputed"),
        ("disputed", "closed"), ("disputed", "cancelled"),
    }
    for actuel in statuts:
        for cible in statuts:
            attendu = (actuel, cible) in attendues
            assert bons_commande.transition_autorisee(actuel, cible) is attendu, (actuel, cible)

    # cancelled et closed sont TERMINAUX : aucune transition sortante.
    for terminal in ("cancelled", "closed"):
        assert all(not bons_commande.transition_autorisee(terminal, cible) for cible in statuts)

    # Statut inconnu : jamais autorisé (fail-closed, table figée).
    assert bons_commande.transition_autorisee("statut_inconnu", "draft") is False


# ------------------------------------------------------------------------------------- creer_brouillon


def test_creer_brouillon_nominal_prix_livre():
    po, _ = _creer_po()
    assert po["statut"] == "draft"
    assert po["po_id"] == "PO-1"
    assert po["chantier_id"] == "C1"
    assert po["fournisseur_id"] == "gentek"
    assert po["lignes"] == [
        {
            "materiau_id": "MAT-1", "designation": None, "unite": "boite", "unite_source": "declaree",
            "quantite_nette": 5.0, "facteur_perte": None, "quantite_demandee": 5.0, "verdict_prix": "PRIX_LIVRE",
            "prix_unitaire_prevu": 10.0, "devise_prevue": "CAD", "montant_ligne_prevu": 50.0,
            "prix_unite_confirmee": False,
        }
    ]
    assert po["montant_total_prevu"] == 50.0


def test_creer_brouillon_prix_indetermine_jamais_bloquant_a_la_creation():
    po, _ = _creer_po(registre_prix=[])  # aucun prix au livre pour MAT-1/gentek
    assert po["statut"] == "draft"
    assert po["lignes"][0]["verdict_prix"] == "INDETERMINE"
    assert po["lignes"][0]["prix_unitaire_prevu"] is None
    assert po["montant_total_prevu"] is None, "null SSI au moins une ligne indéterminée"


def test_creer_brouillon_fournisseur_inconnu_refuse_nomme():
    po, verdict = bons_commande.creer_brouillon(
        "PO-1", "C1", "fournisseur-fantome", [{"materiau_id": "MAT-1", "quantite_nette": 5.0, "unite": "boite"}],
        "2026-01-02T00:00:00Z", [], _prix_gentek(), [], conditions=CONDITIONS_PO)
    assert po is None
    assert verdict["code"] == "REJ-PO-FOURNISSEUR-INCONNU"


def test_creer_brouillon_lignes_vides_refuse_nomme():
    po, verdict = bons_commande.creer_brouillon(
        "PO-1", "C1", "gentek", [], "2026-01-02T00:00:00Z", [], [], _fournisseurs_avec_gentek(),
        conditions=CONDITIONS_PO)
    assert po is None
    assert verdict["code"] == "REJ-PO-LIGNES-VIDES"


def test_creer_brouillon_ligne_dupliquee_refuse_nomme():
    lignes = [
        {"materiau_id": "MAT-1", "quantite_nette": 5.0, "unite": "boite"},
        {"materiau_id": "MAT-1", "quantite_nette": 2.0, "unite": "boite"},
    ]
    po, verdict = bons_commande.creer_brouillon(
        "PO-1", "C1", "gentek", lignes, "2026-01-02T00:00:00Z", [], _prix_gentek(), _fournisseurs_avec_gentek(),
        conditions=CONDITIONS_PO)
    assert po is None
    assert verdict["code"] == "REJ-PO-LIGNE-DUPLIQUEE"


def test_creer_brouillon_quantite_invalide_refuse_nomme():
    lignes = [{"materiau_id": "MAT-1", "quantite_nette": -1.0, "unite": "boite"}]
    po, verdict = bons_commande.creer_brouillon(
        "PO-1", "C1", "gentek", lignes, "2026-01-02T00:00:00Z", [], _prix_gentek(), _fournisseurs_avec_gentek(),
        conditions=CONDITIONS_PO)
    assert po is None
    assert verdict["code"] == "REJ-PO-LIGNE-INVALIDE"


def test_creer_brouillon_frontiere_violee_refuse_nomme():
    # Clé interdite (DA-M6-03 ensemble #1) glissée dans une ligne, vérifiée AVANT la structure
    # exacte de la ligne (ordre épinglé : frontière -> structure, comme validation.py).
    ligne_avec_cle_interdite = {"materiau_id": "MAT-1", "quantite_nette": 5.0, "unite": "boite", "prix_vente": 1}
    po, verdict = bons_commande.creer_brouillon(
        "PO-1", "C1", "gentek", [ligne_avec_cle_interdite],
        "2026-01-02T00:00:00Z", [], _prix_gentek(), _fournisseurs_avec_gentek(), conditions=CONDITIONS_PO)
    assert po is None
    assert verdict["code"] == "REJ-FRONTIERE-VIOLEE"


def test_creer_brouillon_idempotent_replay_identique():
    registre_po: list[dict] = []
    registre_prix = _prix_gentek()
    registre_fournisseurs = _fournisseurs_avec_gentek()
    lignes = [{"materiau_id": "MAT-1", "quantite_nette": 5.0, "unite": "boite"}]
    po1, _ = _creer_po(
        registre_po=registre_po, registre_prix=registre_prix,
        registre_fournisseurs=registre_fournisseurs, lignes=lignes,
    )
    po2, verdict = bons_commande.creer_brouillon(
        "PO-1", "C1", "gentek", lignes, "2026-01-02T00:00:00Z", registre_po, registre_prix, registre_fournisseurs,
        conditions=CONDITIONS_PO)
    assert verdict is None
    assert po2 == po1
    assert len(registre_po) == 1, "rejoué à l'identique -> aucun maillon de plus"


def test_creer_brouillon_meme_po_id_contenu_different_refuse_nomme():
    registre_po: list[dict] = []
    registre_prix = _prix_gentek()
    registre_fournisseurs = _fournisseurs_avec_gentek()
    _creer_po(registre_po=registre_po, registre_prix=registre_prix, registre_fournisseurs=registre_fournisseurs)
    po2, verdict = bons_commande.creer_brouillon(
        "PO-1", "C1", "gentek", [{"materiau_id": "MAT-1", "quantite_nette": 999.0, "unite": "boite"}],
        "2026-01-02T00:00:00Z", registre_po, registre_prix, registre_fournisseurs, conditions=CONDITIONS_PO)
    assert po2 is None
    assert verdict["code"] == "REJ-PO-ID-DEJA-UTILISE"


def test_lire_po_inconnu_rend_none():
    assert bons_commande.lire([], "PO-INCONNU") is None


def test_lister_tri_deterministe():
    registre_po: list[dict] = []
    registre_prix = _prix_gentek()
    registre_fournisseurs = _fournisseurs_avec_gentek()
    _creer_po(
        po_id="PO-B", registre_po=registre_po, registre_prix=registre_prix,
        registre_fournisseurs=registre_fournisseurs,
    )
    _creer_po(
        po_id="PO-A", registre_po=registre_po, registre_prix=registre_prix,
        registre_fournisseurs=registre_fournisseurs,
    )
    assert [po["po_id"] for po in bons_commande.lister(registre_po)] == ["PO-A", "PO-B"]


# ------------------------------------------------------------------------------------------ approuver


def test_approuver_nominal():
    po, registre_po = _creer_po()
    approuve, verdict = bons_commande.approuver("PO-1", "2026-01-03T00:00:00Z", registre_po)
    assert verdict is None
    assert approuve["statut"] == "approved"
    assert approuve["lignes"] == po["lignes"], "les champs de création restent visibles après transition"


def test_approuver_refuse_prix_indetermine():
    po, registre_po = _creer_po(registre_prix=[])
    assert po["lignes"][0]["verdict_prix"] == "INDETERMINE"
    resultat, verdict = bons_commande.approuver("PO-1", "2026-01-03T00:00:00Z", registre_po)
    assert resultat is None
    assert verdict["code"] == "REJ-PO-PRIX-INDETERMINE"


def test_approuver_po_introuvable():
    resultat, verdict = bons_commande.approuver("PO-FANTOME", "2026-01-03T00:00:00Z", [])
    assert resultat is None
    assert verdict["code"] == "REJ-PO-INTROUVABLE"


def test_approuver_transition_illegale_deja_approuve():
    _, registre_po = _creer_po()
    bons_commande.approuver("PO-1", "2026-01-03T00:00:00Z", registre_po)
    resultat, verdict = bons_commande.approuver("PO-1", "2026-01-04T00:00:00Z", registre_po)
    assert resultat is None
    assert verdict["code"] == "REJ-PO-TRANSITION-ILLEGALE"


# -------------------------------------------------------------------------------------------- annuler


def test_annuler_nominal():
    _, registre_po = _creer_po()
    annule, verdict = bons_commande.annuler("PO-1", "chantier abandonné", "2026-01-03T00:00:00Z", registre_po)
    assert verdict is None
    assert annule["statut"] == "cancelled"
    assert annule["motif_annulation"] == "chantier abandonné"


def test_annuler_motif_vide_refuse_nomme():
    _, registre_po = _creer_po()
    resultat, verdict = bons_commande.annuler("PO-1", "", "2026-01-03T00:00:00Z", registre_po)
    assert resultat is None
    assert verdict["code"] == "REJ-PO-MOTIF-ANNULATION-VIDE"


def test_annuler_deux_fois_refuse_nomme():
    _, registre_po = _creer_po()
    bons_commande.annuler("PO-1", "motif", "2026-01-03T00:00:00Z", registre_po)
    resultat, verdict = bons_commande.annuler("PO-1", "motif 2", "2026-01-04T00:00:00Z", registre_po)
    assert resultat is None
    assert verdict["code"] == "REJ-PO-TRANSITION-ILLEGALE"


# ------------------------------------------------------------------------------------ generer_courriel


def _po_approuve(**kwargs):
    po, registre_po = _creer_po(**kwargs)
    bons_commande.approuver(po["po_id"], "2026-01-03T00:00:00Z", registre_po)
    return registre_po


def test_generer_courriel_nominal_avec_destinataire():
    registre_po = _po_approuve()
    resultat, verdict = bons_commande.generer_courriel(
        "PO-1", "2026-01-04T00:00:00Z", registre_po, _fournisseurs_avec_gentek(), "GRS"
    )
    assert verdict is None
    assert resultat["statut"] == "email_ready"
    courriel = resultat["courriel"]
    assert courriel["destinataire"] == "commandes@gentek.exemple-fictif.test"
    assert courriel["repli_manuel_requis"] is False
    assert "PO-1" in courriel["objet"]
    assert "MAT-1" in courriel["corps"]
    assert "C1" in courriel["corps"]


def test_generer_courriel_sans_courriel_fournisseur_demande_repli_manuel():
    registre_po = _po_approuve()
    fournisseurs_sans_courriel = _fournisseurs_avec_gentek(courriel=None)
    resultat, verdict = bons_commande.generer_courriel(
        "PO-1", "2026-01-04T00:00:00Z", registre_po, fournisseurs_sans_courriel, "GRS"
    )
    assert verdict is None
    assert resultat["courriel"]["destinataire"] is None
    assert resultat["courriel"]["repli_manuel_requis"] is True


def test_generer_courriel_nom_entreprise_vide_refuse_nomme():
    registre_po = _po_approuve()
    resultat, verdict = bons_commande.generer_courriel(
        "PO-1", "2026-01-04T00:00:00Z", registre_po, _fournisseurs_avec_gentek(), ""
    )
    assert resultat is None
    assert verdict["code"] == "REJ-PO-NOM-ENTREPRISE-VIDE"


def test_generer_courriel_avant_approbation_refuse_nomme():
    _, registre_po = _creer_po()
    resultat, verdict = bons_commande.generer_courriel(
        "PO-1", "2026-01-04T00:00:00Z", registre_po, _fournisseurs_avec_gentek(), "GRS"
    )
    assert resultat is None
    assert verdict["code"] == "REJ-PO-TRANSITION-ILLEGALE"


# --------------------------------------------------------------------------------------- marquer_envoye


def _po_email_ready():
    registre_po = _po_approuve()
    bons_commande.generer_courriel(
        "PO-1", "2026-01-04T00:00:00Z", registre_po, _fournisseurs_avec_gentek(), "GRS",
    )
    return registre_po


def test_marquer_envoye_nominal():
    registre_po = _po_email_ready()
    envoye, verdict = bons_commande.marquer_envoye("PO-1", "2026-01-05T00:00:00Z", registre_po)
    assert verdict is None
    assert envoye["statut"] == "sent_to_supplier"


def test_marquer_envoye_avant_email_ready_refuse_nomme():
    _, registre_po = _creer_po()
    resultat, verdict = bons_commande.marquer_envoye("PO-1", "2026-01-05T00:00:00Z", registre_po)
    assert resultat is None
    assert verdict["code"] == "REJ-PO-TRANSITION-ILLEGALE"


# ---------------------------------------------------------------------------- enregistrer_reception_po


def test_enregistrer_reception_po_conforme_donne_received():
    registre_po = _po_email_ready()
    bons_commande.marquer_envoye("PO-1", "2026-01-05T00:00:00Z", registre_po)
    po, verdict = bons_commande.enregistrer_reception_po("PO-1", "CONFORME", "2026-01-06T00:00:00Z", registre_po)
    assert verdict is None
    assert po["statut"] == "received"
    assert po["verdict_reception"] == "CONFORME"


def test_enregistrer_reception_po_superieure_donne_received():
    registre_po = _po_email_ready()
    bons_commande.marquer_envoye("PO-1", "2026-01-05T00:00:00Z", registre_po)
    po, verdict = bons_commande.enregistrer_reception_po(
        "PO-1", "RECEPTION_SUPERIEURE", "2026-01-06T00:00:00Z", registre_po
    )
    assert verdict is None
    assert po["statut"] == "received"


def test_enregistrer_reception_po_inferieure_donne_partially_received():
    registre_po = _po_email_ready()
    bons_commande.marquer_envoye("PO-1", "2026-01-05T00:00:00Z", registre_po)
    po, verdict = bons_commande.enregistrer_reception_po(
        "PO-1", "RECEPTION_INFERIEURE", "2026-01-06T00:00:00Z", registre_po
    )
    assert verdict is None
    assert po["statut"] == "partially_received"


def test_enregistrer_reception_po_mixte_donne_partially_received():
    registre_po = _po_email_ready()
    bons_commande.marquer_envoye("PO-1", "2026-01-05T00:00:00Z", registre_po)
    po, verdict = bons_commande.enregistrer_reception_po(
        "PO-1", "RECEPTION_MIXTE", "2026-01-06T00:00:00Z", registre_po
    )
    assert verdict is None
    assert po["statut"] == "partially_received"


def test_enregistrer_reception_po_partiel_repete_reste_partiel():
    registre_po = _po_email_ready()
    bons_commande.marquer_envoye("PO-1", "2026-01-05T00:00:00Z", registre_po)
    bons_commande.enregistrer_reception_po("PO-1", "RECEPTION_INFERIEURE", "2026-01-06T00:00:00Z", registre_po)
    po, verdict = bons_commande.enregistrer_reception_po(
        "PO-1", "RECEPTION_INFERIEURE", "2026-01-07T00:00:00Z", registre_po
    )
    assert verdict is None
    assert po["statut"] == "partially_received"


def test_enregistrer_reception_po_partiel_puis_complet_devient_received():
    registre_po = _po_email_ready()
    bons_commande.marquer_envoye("PO-1", "2026-01-05T00:00:00Z", registre_po)
    bons_commande.enregistrer_reception_po("PO-1", "RECEPTION_INFERIEURE", "2026-01-06T00:00:00Z", registre_po)
    po, verdict = bons_commande.enregistrer_reception_po("PO-1", "CONFORME", "2026-01-07T00:00:00Z", registre_po)
    assert verdict is None
    assert po["statut"] == "received"


def test_enregistrer_reception_po_indetermine_ne_transitionne_pas():
    registre_po = _po_email_ready()
    bons_commande.marquer_envoye("PO-1", "2026-01-05T00:00:00Z", registre_po)
    taille_avant = len(registre_po)
    po, verdict = bons_commande.enregistrer_reception_po("PO-1", "INDETERMINE", "2026-01-06T00:00:00Z", registre_po)
    assert verdict is None
    assert po["statut"] == "sent_to_supplier", "rien n'a été écrit au stock non plus, rien ne transitionne"
    assert len(registre_po) == taille_avant


def test_enregistrer_reception_po_avant_envoi_refuse_nomme():
    _, registre_po = _creer_po()
    resultat, verdict = bons_commande.enregistrer_reception_po("PO-1", "CONFORME", "2026-01-06T00:00:00Z", registre_po)
    assert resultat is None
    assert verdict["code"] == "REJ-PO-TRANSITION-ILLEGALE"


def test_enregistrer_reception_po_introuvable_refuse_nomme():
    resultat, verdict = bons_commande.enregistrer_reception_po("PO-X", "CONFORME", "2026-01-06T00:00:00Z", [])
    assert resultat is None
    assert verdict["code"] == "REJ-PO-INTROUVABLE"


def test_enregistrer_reception_po_verdict_inconnu_refuse_nomme():
    registre_po = _po_email_ready()
    bons_commande.marquer_envoye("PO-1", "2026-01-05T00:00:00Z", registre_po)
    resultat, verdict = bons_commande.enregistrer_reception_po(
        "PO-1", "VERDICT_FANTOME", "2026-01-06T00:00:00Z", registre_po
    )
    assert resultat is None
    assert verdict["code"] == "REJ-PO-VERDICT-RECEPTION-INCONNU"


def test_peut_recevoir():
    assert bons_commande.peut_recevoir("sent_to_supplier") is True
    assert bons_commande.peut_recevoir("supplier_confirmed") is True
    assert bons_commande.peut_recevoir("partially_received") is True
    assert bons_commande.peut_recevoir("draft") is False
    assert bons_commande.peut_recevoir("received") is False
    assert bons_commande.peut_recevoir("cancelled") is False


# ------------------------------------------------------------------------------- bon_demande_correspond


def test_bon_demande_correspond_nominal():
    po, _ = _creer_po()
    bon_demande = {"po_id": "PO-1", "chantier_id": "C1", "lignes_demandees": [
        {"materiau_id": "MAT-1", "quantite_demandee": 5.0}
    ]}
    assert bons_commande.bon_demande_correspond(po, bon_demande) is True


def test_bon_demande_correspond_chantier_different():
    po, _ = _creer_po()
    bon_demande = {"chantier_id": "AUTRE", "lignes_demandees": [{"materiau_id": "MAT-1", "quantite_demandee": 5.0}]}
    assert bons_commande.bon_demande_correspond(po, bon_demande) is False


def test_bon_demande_correspond_quantite_differente():
    po, _ = _creer_po()
    bon_demande = {"chantier_id": "C1", "lignes_demandees": [{"materiau_id": "MAT-1", "quantite_demandee": 999.0}]}
    assert bons_commande.bon_demande_correspond(po, bon_demande) is False


def test_construire_bon_demande_forme_attendue():
    po, _ = _creer_po()
    bon_demande = bons_commande.construire_bon_demande(po)
    assert bon_demande == {
        "po_id": "PO-1", "chantier_id": "C1",
        "lignes_demandees": [{"materiau_id": "MAT-1", "quantite_demandee": 5.0}],
        "horodatage": "2026-01-02T00:00:00Z",
    }


# ----------------------------------------------------------------------------------- detecter_ecarts_prix


def test_detecter_ecarts_prix_sous_le_seuil_aucun_signal():
    po, _ = _creer_po()  # prix prévu 10.0
    lignes_accuse = [{"materiau_id": "MAT-1", "cout_unitaire_resolu": 10.2}]
    assert bons_commande.detecter_ecarts_prix(po, lignes_accuse, 0.30) == []


def test_detecter_ecarts_prix_au_dessus_du_seuil_signale():
    po, _ = _creer_po()  # prix prévu 10.0
    lignes_accuse = [{"materiau_id": "MAT-1", "cout_unitaire_resolu": 15.0}]
    signaux = bons_commande.detecter_ecarts_prix(po, lignes_accuse, 0.30)
    assert signaux == [
        {"po_id": "PO-1", "chantier_id": "C1", "materiau_id": "MAT-1", "prix_prevu": 10.0,
         "prix_reel": 15.0, "ecart_pourcentage": 0.5}
    ]


def test_detecter_ecarts_prix_baisse_aussi_signalee():
    po, _ = _creer_po()  # prix prévu 10.0
    lignes_accuse = [{"materiau_id": "MAT-1", "cout_unitaire_resolu": 4.0}]
    signaux = bons_commande.detecter_ecarts_prix(po, lignes_accuse, 0.30)
    assert len(signaux) == 1
    assert signaux[0]["ecart_pourcentage"] == 0.6


def test_detecter_ecarts_prix_prevu_indetermine_ignore_silencieusement():
    po, _ = _creer_po(registre_prix=[])
    lignes_accuse = [{"materiau_id": "MAT-1", "cout_unitaire_resolu": 999.0}]
    assert bons_commande.detecter_ecarts_prix(po, lignes_accuse, 0.30) == []


def test_detecter_ecarts_prix_reel_indetermine_ignore_silencieusement():
    po, _ = _creer_po()
    lignes_accuse = [{"materiau_id": "MAT-1", "cout_unitaire_resolu": None}]
    assert bons_commande.detecter_ecarts_prix(po, lignes_accuse, 0.30) == []


@pytest.mark.parametrize(
    ("prix_prevu", "prix_reel", "seuil", "signal_attendu"),
    [
        (0.10, 0.12, 0.20, True),
        (1.00, 1.20, 0.20, True),
        (0.30, 0.33, 0.10, True),
        (0.10, 0.08, 0.20, True),
        (0.10, 0.1199, 0.20, False),
        (0.10, 0.1201, 0.20, True),
    ],
)
def test_detecter_ecarts_prix_seuil_decimal_exact(prix_prevu, prix_reel, seuil, signal_attendu):
    """Prix fictifs : le seuil atteint est inclus, sans perte liée au calcul binaire."""
    po = {
        "po_id": "PO-FICTIF-AUDIT-SEUIL",
        "chantier_id": "CHANTIER-FICTIF-AUDIT-SEUIL",
        "lignes": [{"materiau_id": "VIS-FICTIF", "prix_unitaire_prevu": prix_prevu}],
    }
    signaux = bons_commande.detecter_ecarts_prix(
        po, [{"materiau_id": "VIS-FICTIF", "cout_unitaire_resolu": prix_reel}], seuil
    )
    assert bool(signaux) is signal_attendu
    if signal_attendu:
        assert len(signaux) == 1
        assert signaux[0]["po_id"] == po["po_id"]
        assert signaux[0]["materiau_id"] == "VIS-FICTIF"


@pytest.mark.parametrize("source,marque", [(None, "FALLBACK_PRICE_BOOK"), ("FACT-FICTIF", "SOURCE_DECLAREE")])
def test_capture_provenance_po_hors_lignes_economiques(source, marque):
    livre, registre_po = [], []
    livre_prix.enregistrer_prix("MAT-1", "gentek", 12.5, "CAD", "2026-01-01", livre, source)
    po, registre_retour = _creer_po(
        lignes=[{"materiau_id": "MAT-1", "quantite_nette": 2.0,
                 "unite": "boite"}], registre_po=registre_po, registre_prix=livre
    )
    assert registre_retour is registre_po and po["statut"] == "draft"
    assert po["provenance_prix_lignes"] == [
        {
            "materiau_id": "MAT-1",
            "capture": "CAPTURE",
            "date_effet": "2026-01-01",
            "source_document": source,
            "marquage_source": marque,
        }
    ]
    # Les six champs économiques d'origine (identité du rejeu) + ceux de C2 (unité, quantité nette, perte déclarée).
    assert set(po["lignes"][0]) == {
        "materiau_id",
        "quantite_demandee",
        "verdict_prix",
        "prix_unitaire_prevu",
        "devise_prevue",
        "montant_ligne_prevu",
        "designation", "unite", "unite_source", "quantite_nette", "facteur_perte", "prix_unite_confirmee",
    }
    assert po["montant_total_prevu"] == 25.0
    assert registre_po[0]["provenance_prix_lignes"] == po["provenance_prix_lignes"]
    avant = copy.deepcopy(registre_po)
    po["provenance_prix_lignes"][0]["source_document"] = "REFERENCE-MODIFIEE-FICTIVE"
    assert registre_po == avant, "le retour ne doit pas donner un alias modifiable de la capture"


def test_rejeu_meme_id_garde_capture_originale_malgre_doc_date_modifies():
    livre, registre_po = [], []
    livre_prix.enregistrer_prix("MAT-1", "gentek", 12.5, "CAD", "2026-01-01", livre)
    premier, _ = _creer_po(registre_po=registre_po, registre_prix=livre)
    avant = copy.deepcopy(registre_po)
    livre_prix.enregistrer_prix("MAT-1", "gentek", 12.5, "CAD", "2026-02-01", livre, "FACT-NOUVELLE-FICTIVE")
    rejoue, registre_retour = _creer_po(registre_po=registre_po, registre_prix=livre)
    assert registre_retour is registre_po and rejoue == premier
    assert rejoue["provenance_prix_lignes"][0]["source_document"] is None
    assert rejoue["provenance_prix_lignes"][0]["date_effet"] == "2026-01-01"
    assert registre_po == avant
    livre_prix.enregistrer_prix("MAT-1", "gentek", 14.0, "CAD", "2026-03-01", livre, "FACT-FICTIVE")
    conflit, verdict = bons_commande.creer_brouillon(
        "PO-1",
        "C1",
        "gentek",
        [{"materiau_id": "MAT-1", "quantite_nette": 5.0, "unite": "boite"}],
        "2026-01-02T00:00:00Z",
        registre_po,
        livre,
        _fournisseurs_avec_gentek(), conditions=CONDITIONS_PO)
    assert conflit is None and verdict["code"] == "REJ-PO-ID-DEJA-UTILISE"
    assert registre_po == avant


def test_legacy_po_sans_capture_rejoue_estimated_sans_emprunter_livre_courant():
    initial, _ = _creer_po()
    initial.pop("provenance_prix_lignes", None)
    registre_po, livre = [copy.deepcopy(initial)], _prix_gentek()
    avant = copy.deepcopy(registre_po)
    livre_prix.enregistrer_prix("MAT-1", "gentek", 10.0, "CAD", "2026-02-01", livre, "FACT-POSTERIEURE-FICTIVE")
    lu = bons_commande.lire(registre_po, "PO-1")
    assert lu["provenance_prix_lignes"] == [
        {
            "materiau_id": "MAT-1",
            "capture": "NON_CAPTURE",
            "date_effet": None,
            "source_document": None,
            "marquage_source": "ESTIMATED",
        }
    ]
    assert bons_commande.lister(registre_po) == [lu]
    rejoue, registre_retour = _creer_po(registre_po=registre_po, registre_prix=livre)
    assert registre_retour is registre_po and rejoue == lu
    assert registre_po == avant
    assert lu["lignes"] == initial["lignes"] and lu["montant_total_prevu"] == initial["montant_total_prevu"]


@pytest.mark.parametrize(
    "livre",
    [
        [],
        [
            {
                "materiau_id": "MAT-1",
                "fournisseur_id": "royal",
                "prix_unitaire": 10.0,
                "devise": "CAD",
                "date_effet": "2026-01-01",
                "source_document": "FACT-FICTIVE",
            }
        ],
    ],
)
def test_po_prix_absent_ou_autre_fournisseur_null_sans_date_inventee(livre):
    po, _ = _creer_po(registre_prix=livre)
    assert po["lignes"][0]["verdict_prix"] == "INDETERMINE"
    assert po["montant_total_prevu"] is None
    provenance = po["provenance_prix_lignes"][0]
    assert provenance["marquage_source"] is provenance["source_document"] is provenance["date_effet"] is None
    legacy = copy.deepcopy(po)
    legacy.pop("provenance_prix_lignes")
    assert bons_commande.lire([legacy], "PO-1")["provenance_prix_lignes"][0]["marquage_source"] is None


# --- Bornes, entrées malformées et filtres (mutants survivants) ----------------------

_LIGNE_MIN = {"materiau_id": "MAT-1", "quantite_nette": 5.0, "unite": "boite"}


_CONDITIONS_PAR_DEFAUT = object()


def _creer_avec(lignes, conditions=_CONDITIONS_PAR_DEFAUT, unites_fiche=None, registre_prix=None):
    conditions = CONDITIONS_PO if conditions is _CONDITIONS_PAR_DEFAUT else conditions
    return bons_commande.creer_brouillon(
        "PO-MUT", "C1", "gentek", lignes, "2026-01-02T00:00:00Z", [],
        _prix_gentek() if registre_prix is None else registre_prix, _fournisseurs_avec_gentek(),
        conditions=conditions, unites_fiche=unites_fiche)


def test_repartition_plafond_de_20_fournisseurs():
    repartition = [{"po_id": f"P{i}", "fournisseur_id": f"f{i}", "materiau_ids": []} for i in range(21)]
    affectations, verdict = bons_commande.repartir_besoin([], repartition)
    assert affectations is None
    assert verdict["code"] == "REJ-PO-REPARTITION-TROP-GRANDE"


def test_repartition_plafond_de_200_lignes_par_bon():
    entree = {"po_id": "P", "fournisseur_id": "f", "materiau_ids": [f"M{i}" for i in range(201)]}
    affectations, verdict = bons_commande.repartir_besoin([], [entree])
    assert affectations is None
    assert verdict["code"] == "REJ-PO-REPARTITION-TROP-GRANDE"


def test_longueurs_des_textes_de_conditions_aux_bornes():
    for cle, maximum in (("lieu_livraison", 200), ("ville", 80), ("notes", 500)):
        conditions = {**CONDITIONS_PO, cle: "a" * maximum}
        po, verdict = _creer_avec([dict(_LIGNE_MIN)], conditions)
        assert verdict is None, (cle, verdict)
        assert po[cle] == "a" * maximum
        rejete, verdict = _creer_avec([dict(_LIGNE_MIN)], {**CONDITIONS_PO, cle: "a" * (maximum + 1)})
        assert rejete is None and verdict["code"] == "REJ-PO-TEXTE-INVALIDE", cle


def test_longueur_de_l_unite_aux_bornes():
    po, verdict = _creer_avec([{**_LIGNE_MIN, "unite": "u" * 40}])
    assert verdict is None and po["lignes"][0]["unite"] == "u" * 40
    rejete, verdict = _creer_avec([{**_LIGNE_MIN, "unite": "u" * 41}])
    assert rejete is None and verdict["code"] == "REJ-PO-UNITE-REQUISE"


def test_longueur_de_la_designation_aux_bornes():
    po, verdict = _creer_avec([{**_LIGNE_MIN, "designation": "a" * 200}])
    assert verdict is None and po["lignes"][0]["designation"] == "a" * 200
    rejete, verdict = _creer_avec([{**_LIGNE_MIN, "designation": "a" * 201}])
    assert rejete is None and verdict["code"] == "REJ-PO-TEXTE-INVALIDE"


@pytest.mark.parametrize("quantite", [True, "5"])
def test_quantite_booleenne_ou_textuelle_refusee(quantite):
    po, verdict = _creer_avec([{**_LIGNE_MIN, "quantite_nette": quantite}])
    assert po is None and verdict["code"] == "REJ-PO-LIGNE-INVALIDE"


@pytest.mark.parametrize("quantite", [1.0, 5.0])
def test_quantite_finie_positive_acceptee(quantite):
    po, verdict = _creer_avec([{**_LIGNE_MIN, "quantite_nette": quantite}])
    assert verdict is None and po["lignes"][0]["quantite_nette"] == quantite


def test_quantite_non_finie_refusee_sans_laisser_calculer():
    for quantite in (float("inf"), float("nan")):
        po, verdict = _creer_avec([{**_LIGNE_MIN, "quantite_nette": quantite}])
        assert po is None and verdict["code"] == "REJ-PO-LIGNE-INVALIDE"
        assert "detail" not in verdict


def test_quantite_nulle_refusee_sans_laisser_calculer():
    po, verdict = _creer_avec([{**_LIGNE_MIN, "quantite_nette": 0.0}])
    assert po is None and verdict["code"] == "REJ-PO-LIGNE-INVALIDE"
    assert "detail" not in verdict


def test_calculer_lignes_ecart_exactement_nul_omet_la_ligne():
    registre = Registre()
    registre.ajouter({"type_mouvement": "RECEPTION", "chantier_id": "C1", "materiau_id": "MAT-1",
                      "quantite": 10.0, "cout_unitaire": 10.0})
    besoins = [{"materiau_id": "MAT-1", "quantite_estimee": 10.0, "unite": "boite"}]
    assert bons_commande.calculer_lignes_a_commander(besoins, "C1", registre) == []


def test_calculer_lignes_ecart_fractionnaire_est_commande():
    registre = Registre()
    registre.ajouter({"type_mouvement": "RECEPTION", "chantier_id": "C1", "materiau_id": "MAT-1",
                      "quantite": 9.5, "cout_unitaire": 10.0})
    besoins = [{"materiau_id": "MAT-1", "quantite_estimee": 10.0, "unite": "boite"}]
    assert bons_commande.calculer_lignes_a_commander(besoins, "C1", registre) == [
        {"materiau_id": "MAT-1", "quantite_nette": 0.5, "unite": "boite"}]


def test_unite_none_ou_vide_refusee_proprement():
    for unite in (None, ""):
        po, verdict = _creer_avec([{**_LIGNE_MIN, "unite": unite}])
        assert po is None and verdict["code"] == "REJ-PO-UNITE-REQUISE"


def test_unite_de_un_caractere_acceptee():
    po, verdict = _creer_avec([{**_LIGNE_MIN, "unite": "u"}])
    assert verdict is None and po["lignes"][0]["unite"] == "u"


def test_unite_avec_espace_de_bord_refusee():
    po, verdict = _creer_avec([{**_LIGNE_MIN, "unite": " boite"}])
    assert po is None and verdict["code"] == "REJ-PO-UNITE-REQUISE"


def test_caractere_de_controle_dans_un_texte_refuse():
    po, verdict = _creer_avec([{**_LIGNE_MIN, "designation": "ciment\x01"}])
    assert po is None and verdict["code"] == "REJ-PO-TEXTE-INVALIDE"


def test_ligne_non_dict_ou_incomplete_refusee_nommee():
    po, verdict = _creer_avec(["pas-une-ligne"])
    assert po is None and verdict["code"] == "REJ-PO-LIGNE-INVALIDE"
    po, verdict = _creer_avec([{"materiau_id": "MAT-1", "quantite_nette": 5.0}])
    assert po is None and verdict["code"] == "REJ-PO-LIGNE-INVALIDE"


def test_ligne_avec_toutes_les_cles_acceptee():
    ligne = {**_LIGNE_MIN, "facteur_perte": "0.1", "designation": "Ciment", "unite_source": "declaree"}
    po, verdict = _creer_avec([ligne])
    assert verdict is None and po["lignes"][0]["designation"] == "Ciment"


def test_materiau_vide_refuse():
    po, verdict = _creer_avec([{**_LIGNE_MIN, "materiau_id": ""}])
    assert po is None and verdict["code"] == "REJ-PO-LIGNE-INVALIDE"


def test_quantite_hors_domaine_garde_son_motif():
    po, verdict = _creer_avec([{**_LIGNE_MIN, "quantite_nette": 0.0}])
    assert po is None and "detail" not in verdict


@pytest.mark.parametrize("facteur", [1, "abc", "1", "1.5"])
def test_facteur_de_perte_invalide_refuse(facteur):
    po, verdict = _creer_avec([{**_LIGNE_MIN, "facteur_perte": facteur}])
    assert po is None and verdict["code"] == "REJ-PO-FACTEUR-PERTE-INVALIDE"


def test_facteur_de_perte_valide_applique_une_seule_fois():
    po, verdict = _creer_avec([{**_LIGNE_MIN, "facteur_perte": "0.1"}])
    assert verdict is None
    assert po["lignes"][0]["quantite_demandee"] == 5.5


@pytest.mark.parametrize("facteur", ["0." + "0" * 17 + "1", "0." + "0" * 18 + "1"])
def test_facteur_de_perte_longueur_limite(facteur):
    po, verdict = _creer_avec([{**_LIGNE_MIN, "facteur_perte": facteur}])
    if len(facteur) == 20:
        assert verdict is None
    else:
        assert po is None and verdict["code"] == "REJ-PO-FACTEUR-PERTE-INVALIDE"


def test_quantite_qui_deborde_du_domaine_float_refusee():
    po, verdict = _creer_avec(
        [{**_LIGNE_MIN, "quantite_nette": 1.7e308, "facteur_perte": "0.5"}], registre_prix=[])
    assert po is None
    assert verdict["code"] == "REJ-PO-LIGNE-INVALIDE"
    assert "hors domaine" in verdict["detail"]


def test_unite_de_fiche_identique_acceptee_et_differente_refusee():
    po, verdict = _creer_avec([dict(_LIGNE_MIN)], unites_fiche={"MAT-1": "boite"})
    assert verdict is None
    po, verdict = _creer_avec([dict(_LIGNE_MIN)], unites_fiche={"MAT-1": "palette"})
    assert po is None and verdict["code"] == "REJ-PO-UNITE-INCOHERENTE"


def test_ligne_sans_designation_ou_avec_designation_valide_acceptee():
    po, verdict = _creer_avec([dict(_LIGNE_MIN)])
    assert verdict is None and po["lignes"][0]["designation"] is None
    po, verdict = _creer_avec([{**_LIGNE_MIN, "designation": "Ciment"}])
    assert verdict is None and po["lignes"][0]["designation"] == "Ciment"


def test_conditions_invalides_refusees_nommees():
    for conditions in (None, {}, {**CONDITIONS_PO, "x": 1}):
        po, verdict = _creer_avec([dict(_LIGNE_MIN)], conditions)
        assert po is None and verdict["code"] == "REJ-PO-CONDITIONS-INVALIDES"


def test_conditions_avec_toutes_les_cles_acceptees():
    conditions = {
        "date_requise": "2099-12-31", "mode_livraison": "ramassage",
        "lieu_livraison": "Dépôt fictif", "ville": "Québec", "notes": "Sonner", "devis_id": "D-1",
    }
    po, verdict = _creer_avec([dict(_LIGNE_MIN)], conditions)
    assert verdict is None and po["devis_id"] == "D-1" and po["notes"] == "Sonner"


def test_date_requise_non_textuelle_ou_avant_creation_refusee():
    po, verdict = _creer_avec([dict(_LIGNE_MIN)], {**CONDITIONS_PO, "date_requise": 20260102})
    assert po is None and verdict["code"] == "REJ-PO-DATE-REQUISE-INVALIDE"
    po, verdict = _creer_avec([dict(_LIGNE_MIN)], {**CONDITIONS_PO, "date_requise": "2026-01-01"})
    assert po is None and verdict["code"] == "REJ-PO-DATE-REQUISE-INVALIDE"


def test_date_requise_le_jour_meme_de_la_creation_acceptee():
    po, verdict = _creer_avec([dict(_LIGNE_MIN)], {**CONDITIONS_PO, "date_requise": "2026-01-02"})
    assert verdict is None and po["date_requise"] == "2026-01-02"


def test_livraison_au_chantier_sans_lieu_refusee():
    conditions = {**CONDITIONS_PO, "mode_livraison": "livraison_chantier"}
    po, verdict = _creer_avec([dict(_LIGNE_MIN)], conditions)
    assert po is None and verdict["code"] == "REJ-PO-LIEU-LIVRAISON-REQUIS"


def test_texte_optional_invalide_ou_devis_vide_refuses():
    po, verdict = _creer_avec([dict(_LIGNE_MIN)], {**CONDITIONS_PO, "ville": "Québec\x01"})
    assert po is None and verdict["code"] == "REJ-PO-TEXTE-INVALIDE"
    po, verdict = _creer_avec([dict(_LIGNE_MIN)], {**CONDITIONS_PO, "devis_id": ""})
    assert po is None and verdict["code"] == "REJ-PO-TEXTE-INVALIDE"


def test_manques_de_commandabilite_dune_livraison_au_chantier_sans_lieu():
    po = {"date_requise": "2099-12-31", "mode_livraison": "livraison_chantier",
          "lignes": [{"materiau_id": "MAT-1", "unite": "boite"}]}
    assert bons_commande.manques_commandabilite(po) == ["lieu_livraison"]


def test_un_maillon_pour_un_po_inconnu_est_ignore():
    registre = [
        {"type_entree": "po_cree", "po_id": "P1", "statut": "draft", "lignes": []},
        {"type_entree": "transition_po", "po_id": "P2", "statut": "approved"},
    ]
    assert [po["po_id"] for po in bons_commande.lister(registre)] == ["P1"]


def test_pourcentage_de_perte_du_courriel():
    po, verdict = _creer_avec([{**_LIGNE_MIN, "facteur_perte": "0.1"}])
    assert verdict is None
    courriel = bons_commande.construire_courriel(po, "d@exemple-fictif.test", "GRS")
    assert "perte déclarée de 10 %" in courriel["corps"]


def test_empreinte_du_courriel_est_le_json_canonique():
    conditions = {**CONDITIONS_PO, "ville": "Montréal"}
    po, verdict = _creer_avec([dict(_LIGNE_MIN)], conditions)
    assert verdict is None
    courriel = bons_commande.construire_courriel(po, "d@exemple-fictif.test", "GRS")
    attendu = hashlib.sha256(json.dumps(
        {"objet": courriel["objet"], "destinataire": courriel["destinataire"], "corps": courriel["corps"]},
        sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    assert courriel["empreinte"] == attendu


def _po_envoye():
    registre_po = _po_email_ready()
    bons_commande.marquer_envoye("PO-1", "2026-01-05T00:00:00Z", registre_po)
    return registre_po


def test_changer_statut_pilotable_avec_motif():
    registre_po = _po_envoye()
    po, verdict = bons_commande.changer_statut("PO-1", "disputed", "litige fictif", "2026-01-06T00:00:00Z", registre_po)
    assert verdict is None and po["statut"] == "disputed"
    po, verdict = bons_commande.changer_statut("PO-1", "closed", "", "2026-01-07T00:00:00Z", registre_po)
    assert po is None and verdict["code"] == "REJ-PO-MOTIF-VIDE"


def test_confirmation_de_fournisseur_seulement_sur_un_po_envoye():
    registre_po = _po_email_ready()
    po, verdict = bons_commande.confirmer_fournisseur("PO-1", "2026-01-06T00:00:00Z", registre_po, {})
    assert po is None and "confirmation de fournisseur" in verdict["detail"]
    po, verdict = bons_commande.confirmer_fournisseur("PO-X", "2026-01-06T00:00:00Z", registre_po, {})
    assert po is None and verdict["code"] == "REJ-PO-INTROUVABLE"
    bons_commande.marquer_envoye("PO-1", "2026-01-05T00:00:00Z", registre_po)
    po, verdict = bons_commande.confirmer_fournisseur("PO-1", "2026-01-06T00:00:00Z", registre_po, {})
    assert verdict is None and po["statut"] == "supplier_confirmed"


def test_repartition_nominale_et_cles_en_double_refusees():
    lignes = [{"materiau_id": "MAT-1", "quantite_nette": 5.0, "unite": "boite"}]
    entree = {"po_id": "P1", "fournisseur_id": "f1", "materiau_ids": ["MAT-1"]}
    affectations, verdict = bons_commande.repartir_besoin(lignes, [entree])
    assert verdict is None and affectations == [{"po_id": "P1", "fournisseur_id": "f1", "lignes": lignes}]

    double_po = [entree, {"po_id": "P1", "fournisseur_id": "f2", "materiau_ids": ["MAT-1"]}]
    _, verdict = bons_commande.repartir_besoin(lignes, double_po)
    assert verdict["code"] == "REJ-PO-REPARTITION-PO-DOUBLE"

    double_f = [entree, {"po_id": "P2", "fournisseur_id": "f1", "materiau_ids": ["MAT-1"]}]
    _, verdict = bons_commande.repartir_besoin(lignes, double_f)
    assert verdict["code"] == "REJ-PO-REPARTITION-FOURNISSEUR-DOUBLE"


def test_repartition_entrees_malformees_refusees_nommees():
    lignes = [{"materiau_id": "MAT-1", "quantite_nette": 5.0, "unite": "boite"}]
    entree = {"po_id": "P1", "fournisseur_id": "f1", "materiau_ids": ["MAT-1"]}
    for repartition in (("pas", "une", "liste"), [5], ["pas-un-objet"],
                        [{**entree, "materiau_ids": 5}], [{**entree, "x": 1}],
                        [{**entree, "po_id": ""}], [{**entree, "fournisseur_id": ""}],
                        [{**entree, "materiau_ids": "MAT-1"}], [{**entree, "materiau_ids": [""]}]):
        affectations, verdict = bons_commande.repartir_besoin(lignes, repartition)
        assert affectations is None, repartition
        assert verdict["code"] == "REJ-PO-REPARTITION-INCOMPLETE", repartition


def test_repartition_tuple_meme_valide_refusee():
    lignes = [{"materiau_id": "MAT-1", "quantite_nette": 5.0, "unite": "boite"}]
    entree = {"po_id": "P1", "fournisseur_id": "f1", "materiau_ids": ["MAT-1"]}
    affectations, verdict = bons_commande.repartir_besoin(lignes, (entree,))
    assert affectations is None
    assert verdict["code"] == "REJ-PO-REPARTITION-INCOMPLETE"


def test_repartition_liste_de_materiaux_vide_refusee():
    entree = {"po_id": "P1", "fournisseur_id": "f1", "materiau_ids": []}
    affectations, verdict = bons_commande.repartir_besoin([], [entree])
    assert affectations is None and verdict["code"] == "REJ-PO-REPARTITION-INCOMPLETE"


def test_repartition_de_200_lignes_acceptee():
    lignes = [{"materiau_id": f"M{i}", "quantite_nette": 1.0, "unite": "u"} for i in range(200)]
    entree = {"po_id": "P", "fournisseur_id": "f", "materiau_ids": [ligne["materiau_id"] for ligne in lignes]}
    affectations, verdict = bons_commande.repartir_besoin(lignes, [entree])
    assert verdict is None and len(affectations[0]["lignes"]) == 200


def test_repartition_de_20_fournisseurs_acceptee():
    lignes = [{"materiau_id": f"M{i}", "quantite_nette": 1.0, "unite": "u"} for i in range(20)]
    repartition = [{"po_id": f"P{i}", "fournisseur_id": f"f{i}", "materiau_ids": [f"M{i}"]} for i in range(20)]
    affectations, verdict = bons_commande.repartir_besoin(lignes, repartition)
    assert verdict is None and len(affectations) == 20


def test_livraison_doit_apparier_le_po_et_le_chantier():
    po = bons_commande.lire(_creer_po()[1], "PO-1")
    base = {"po_id": "PO-1", "chantier_id": "C1", "horodatage": "2026-01-06T00:00:00Z",
            "lignes_recues": [{"materiau_id": "MAT-1", "quantite_recue": 5}]}
    assert bons_commande.construire_livraison(po, base)["lignes"][0]["quantite_recue"] == "5"
    assert bons_commande.construire_livraison(po, {**base, "po_id": "PO-AUTRE"}) is None
    assert bons_commande.construire_livraison(po, {**base, "chantier_id": "C-AUTRE"}) is None
    assert bons_commande.construire_livraison(po, {**base, "lignes_recues": None}) is None
    assert bons_commande.construire_livraison(po, {**base, "lignes_recues": []}) is None


def test_livraisons_et_comptage_ne_gardent_que_ce_po():
    registre = [
        {"type_entree": "transition_po", "po_id": "P1", "verdict_reception": "CONFORME",
         "livraison": {"empreinte": "e1"}},
        {"type_entree": "transition_po", "po_id": "P2", "verdict_reception": "CONFORME",
         "livraison": {"empreinte": "e2"}},
        {"type_entree": "transition_po", "po_id": "P1", "verdict_reception": "RECEPTION_INFERIEURE"},
        {"type_entree": "po_cree", "po_id": "P1", "verdict_reception": "CONFORME",
         "livraison": {"empreinte": "e3"}},
    ]
    assert bons_commande.livraisons(registre, "P1") == [{"empreinte": "e1"}]
    assert bons_commande.livraisons_sans_detail(registre, "P1") == 1
    assert bons_commande.livraison_deja_enregistree(registre, "P1", {"empreinte": "e1"}) is True
    assert bons_commande.livraison_deja_enregistree(registre, "P1", {"empreinte": "inconnue"}) is False


def test_une_reception_avec_detail_ne_manque_pas_de_detail():
    registre = [{"type_entree": "transition_po", "po_id": "P1", "verdict_reception": "CONFORME",
                 "livraison": {"empreinte": "e1"}}]
    assert bons_commande.livraisons_sans_detail(registre, "P1") == 0


def test_une_transition_illegale_en_base_n_est_pas_rejouee_par_lire():
    """Le registre est éditable hors outil : un maillon hostile ne doit pas ressusciter un PO."""
    _, registre = _creer_po()
    approuve, verdict = bons_commande.approuver("PO-1", "2026-01-03T00:00:00Z", registre)
    assert verdict is None and approuve["statut"] == "approved"

    registre.append({"type_entree": "transition_po", "po_id": "PO-1", "statut": "closed",
                     "horodatage": "2026-01-04T00:00:00Z", "motif_statut": "hostile fictif"})

    assert bons_commande.lire(registre, "PO-1")["statut"] == "approved"
    annule, verdict = bons_commande.annuler("PO-1", "annulation fictive légitime", "2026-01-05T00:00:00Z", registre)
    assert verdict is None and annule["statut"] == "cancelled", "une transition hostile ne bloque pas les suivantes"


def test_une_transition_illisible_ou_non_textuelle_n_est_pas_rejouee():
    _, registre = _creer_po()
    registre.append({"type_entree": "transition_po", "po_id": "PO-1", "statut": ["closed"],
                     "horodatage": "2026-01-04T00:00:00Z"})
    registre.append({"type_entree": "transition_po", "po_id": "PO-1", "statut": None,
                     "horodatage": "2026-01-04T00:00:00Z"})

    assert bons_commande.lire(registre, "PO-1")["statut"] == "draft"
