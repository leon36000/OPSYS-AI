"""bons_commande.py — PLAN T2.5 point 1/3/4 (M6.5). Lève DA-M6-12 (docs/bmad/03-ARCHITECTURE.md).
Module pur : tous les registres (PO, prix, fournisseurs, mouvements) sont de simples listes Python
en mémoire ici — la persistance durable (`opsys.stockage.maillons`) est prouvée séparément dans
``test_registre_durable.py``.
"""

from __future__ import annotations

import pytest
from m6_material_control import bons_commande, contrats, fournisseurs, livre_prix
from m6_material_control.registre import Registre


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
    lignes = lignes if lignes is not None else [{"materiau_id": "MAT-1", "quantite_demandee": 5.0}]
    registre_po = [] if registre_po is None else registre_po
    registre_prix = _prix_gentek() if registre_prix is None else registre_prix
    registre_fournisseurs = _fournisseurs_avec_gentek() if registre_fournisseurs is None else registre_fournisseurs
    po, verdict = bons_commande.creer_brouillon(
        po_id, chantier_id, "gentek", lignes, "2026-01-02T00:00:00Z",
        registre_po, registre_prix, registre_fournisseurs,
    )
    assert verdict is None, verdict
    return po, registre_po


# ------------------------------------------------------------------------------- calculer_lignes


def test_calculer_lignes_a_commander_ecart_positif():
    registre = Registre()
    registre.ajouter({"type_mouvement": "RECEPTION", "chantier_id": "C1", "materiau_id": "MAT-1",
                       "quantite": 3.0, "cout_unitaire": 10.0})
    besoins = [{"materiau_id": "MAT-1", "quantite_estimee": 10.0, "unite": "boite"}]
    lignes = bons_commande.calculer_lignes_a_commander(besoins, "C1", registre)
    assert lignes == [{"materiau_id": "MAT-1", "quantite_demandee": 7.0}]


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
        {"materiau_id": "MAT-1", "quantite_demandee": 10.0}
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
            "materiau_id": "MAT-1", "quantite_demandee": 5.0, "verdict_prix": "PRIX_LIVRE",
            "prix_unitaire_prevu": 10.0, "devise_prevue": "CAD", "montant_ligne_prevu": 50.0,
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
        "PO-1", "C1", "fournisseur-fantome", [{"materiau_id": "MAT-1", "quantite_demandee": 5.0}],
        "2026-01-02T00:00:00Z", [], _prix_gentek(), [],
    )
    assert po is None
    assert verdict["code"] == "REJ-PO-FOURNISSEUR-INCONNU"


def test_creer_brouillon_lignes_vides_refuse_nomme():
    po, verdict = bons_commande.creer_brouillon(
        "PO-1", "C1", "gentek", [], "2026-01-02T00:00:00Z", [], [], _fournisseurs_avec_gentek()
    )
    assert po is None
    assert verdict["code"] == "REJ-PO-LIGNES-VIDES"


def test_creer_brouillon_ligne_dupliquee_refuse_nomme():
    lignes = [
        {"materiau_id": "MAT-1", "quantite_demandee": 5.0},
        {"materiau_id": "MAT-1", "quantite_demandee": 2.0},
    ]
    po, verdict = bons_commande.creer_brouillon(
        "PO-1", "C1", "gentek", lignes, "2026-01-02T00:00:00Z", [], _prix_gentek(), _fournisseurs_avec_gentek()
    )
    assert po is None
    assert verdict["code"] == "REJ-PO-LIGNE-DUPLIQUEE"


def test_creer_brouillon_quantite_invalide_refuse_nomme():
    lignes = [{"materiau_id": "MAT-1", "quantite_demandee": -1.0}]
    po, verdict = bons_commande.creer_brouillon(
        "PO-1", "C1", "gentek", lignes, "2026-01-02T00:00:00Z", [], _prix_gentek(), _fournisseurs_avec_gentek()
    )
    assert po is None
    assert verdict["code"] == "REJ-PO-LIGNE-INVALIDE"


def test_creer_brouillon_frontiere_violee_refuse_nomme():
    # Clé interdite (DA-M6-03 ensemble #1) glissée dans une ligne, vérifiée AVANT la structure
    # exacte de la ligne (ordre épinglé : frontière -> structure, comme validation.py).
    ligne_avec_cle_interdite = {"materiau_id": "MAT-1", "quantite_demandee": 5.0, "prix_vente": 1}
    po, verdict = bons_commande.creer_brouillon(
        "PO-1", "C1", "gentek", [ligne_avec_cle_interdite],
        "2026-01-02T00:00:00Z", [], _prix_gentek(), _fournisseurs_avec_gentek(),
    )
    assert po is None
    assert verdict["code"] == "REJ-FRONTIERE-VIOLEE"


def test_creer_brouillon_idempotent_replay_identique():
    registre_po: list[dict] = []
    registre_prix = _prix_gentek()
    registre_fournisseurs = _fournisseurs_avec_gentek()
    lignes = [{"materiau_id": "MAT-1", "quantite_demandee": 5.0}]
    po1, _ = _creer_po(
        registre_po=registre_po, registre_prix=registre_prix,
        registre_fournisseurs=registre_fournisseurs, lignes=lignes,
    )
    po2, verdict = bons_commande.creer_brouillon(
        "PO-1", "C1", "gentek", lignes, "2026-01-02T00:00:00Z", registre_po, registre_prix, registre_fournisseurs
    )
    assert verdict is None
    assert po2 == po1
    assert len(registre_po) == 1, "rejoué à l'identique -> aucun maillon de plus"


def test_creer_brouillon_meme_po_id_contenu_different_refuse_nomme():
    registre_po: list[dict] = []
    registre_prix = _prix_gentek()
    registre_fournisseurs = _fournisseurs_avec_gentek()
    _creer_po(registre_po=registre_po, registre_prix=registre_prix, registre_fournisseurs=registre_fournisseurs)
    po2, verdict = bons_commande.creer_brouillon(
        "PO-1", "C1", "gentek", [{"materiau_id": "MAT-1", "quantite_demandee": 999.0}],
        "2026-01-02T00:00:00Z", registre_po, registre_prix, registre_fournisseurs,
    )
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
