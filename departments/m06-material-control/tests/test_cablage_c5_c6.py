"""Câblage C5/C6 (tests ROUGES avant code) : additif, contrats existants inchangés.

C5 : `receptionner_commande` accepte `details_reception`, `lieu_livraison`,
`prix_bl` (optionnels) ; refus nommés AVANT écriture, signaux BL marqués
`BON_LIVRAISON` au seuil DÉCLARÉ, sans toucher à l'événement fermé.
C6 : `m6_declarer_achat_terrain` trace (registre durable dédié), décide au
plafond DÉCLARÉ, transmet une attente M5 sans jamais payer.
"""

import m6_material_control.outils as m6_outils
from m6_material_control import achats_terrain, details_reception


def _bon(po_id="PO-EPHEMERE"):
    return {"po_id": po_id, "chantier_id": "CH-FICT-1",
            "lignes_demandees": [{"materiau_id": "gouttiere-5po", "quantite_demandee": 10.0}],
            "horodatage": "2026-09-29T09:15:00-04:00"}


def _rec(gouttiere=10.0):
    return {"po_id": "PO-EPHEMERE", "chantier_id": "CH-FICT-1",
            "lignes_recues": [{"materiau_id": "gouttiere-5po", "quantite_recue": gouttiere}],
            "horodatage": "2026-09-29T09:15:00-04:00"}


def _detail(**champs):
    base = {"materiau_id": "gouttiere-5po", "statut_ligne": "conforme"}
    base.update(champs)
    return base


def test_c5_substitue_incomplet_refuse_avant_ecriture():
    reponse = m6_outils.receptionner_commande(
        _bon(), _rec(), details_reception=[_detail(statut_ligne="substitue")],
        registre_historique=[])
    assert reponse["accepte"] is False
    assert reponse["verdict"]["code"] == "REJ-RECEPTION-SUBSTITUE-INCOMPLET"
    assert "registre_historique" not in reponse


def test_c5_lieu_hors_liste_refuse():
    reponse = m6_outils.receptionner_commande(
        _bon(), _rec(), lieu_livraison={"type": "grenier"}, registre_historique=[])
    assert reponse["accepte"] is False
    assert reponse["verdict"]["code"] == "REJ-RECEPTION-LIEU-INVALIDE"


def test_c5_prix_bl_20_pourcent_signale_source_bl():
    signaux = details_reception.detecter_ecarts_prix_bl(
        [{"materiau_id": "gouttiere-5po", "prix_unitaire_prevu": 10.0}],
        {"gouttiere-5po": 12.0}, seuil_pourcentage=0.15)
    assert len(signaux) == 1 and signaux[0]["source_prix"] == "BON_LIVRAISON"


def test_c6_declarer_sous_plafond_trace_sans_payer():
    achat = {"materiau_id": "scellant-fictif", "quantite": 3.0, "montant": "25.50",
             "devise": "CAD", "fournisseur": "Quincaillerie Fictive",
             "raison": "urgence chantier", "chantier_id": "CH-FICT-1",
             "recu": "fichier:sha256:" + "ab" * 32}
    reponse = m6_outils.declarer_achat_terrain(achat, achats_terrain_historique=[])
    assert reponse["accepte"] is True
    assert reponse["decision"]["statut"] == "accepte"
    attente = reponse["attente_m5"]
    assert attente["type"] == "depense_terrain_a_saisir"
    assert "paiement" not in attente and "remboursement" not in attente
    assert reponse["attente_m5"]["source_prix"] == "RECU_TERRAIN"


def test_c6_meme_recu_deux_fois_second_refuse():
    achat = {"materiau_id": "scellant-fictif", "quantite": 3.0, "montant": "25.50",
             "devise": "CAD", "fournisseur": "Quincaillerie Fictive",
             "raison": "urgence chantier", "chantier_id": "CH-FICT-1",
             "recu": "fichier:sha256:" + "cd" * 32}
    premier = m6_outils.declarer_achat_terrain(achat, achats_terrain_historique=[])
    assert premier["accepte"] is True
    second = m6_outils.declarer_achat_terrain(
        achat, achats_terrain_historique=premier["achats_terrain_historique"])
    assert second["accepte"] is False
    assert second["verdict"]["code"] == "REJ-ACHAT-TERRAIN-DEJA-DECLARE"


def test_c6_sans_recu_refuse_avant_ecriture():
    achat = {"materiau_id": "scellant-fictif", "quantite": 3.0, "montant": "25.50",
             "devise": "CAD", "fournisseur": "Quincaillerie Fictive",
             "raison": "urgence chantier", "chantier_id": "CH-FICT-1"}
    reponse = m6_outils.declarer_achat_terrain(achat, achats_terrain_historique=[])
    assert reponse["accepte"] is False
    assert reponse["verdict"]["code"] == "REJ-ACHAT-TERRAIN-PREUVE-MANQUANTE"


def test_c6_role_visiteur_refuse():
    assert achats_terrain.valider_achat(
        {"materiau_id": "m", "quantite": 1.0, "montant": "1.00", "devise": "CAD",
         "fournisseur": "f", "raison": "r", "chantier_id": "c",
         "recu": "fichier:sha256:" + "ef" * 32}, role="visiteur")[1] == "REJ-ACHAT-TERRAIN-ROLE-INTERDIT"


def test_attentes_prix_bl_une_par_signal_sans_ecraser():
    from m6_material_control import attentes_c5_c6
    assert attentes_c5_c6.attentes_prix_bl([]) == []
    assert attentes_c5_c6.attentes_prix_bl(None) == []
    assert attentes_c5_c6.attentes_prix_bl([None]) == []
    sortie = attentes_c5_c6.attentes_prix_bl([{"materiau_id": "m", "prix_prevu": "10", "prix_bl": "12",
                                              "source_prix": "BON_LIVRAISON"}])
    assert len(sortie) == 1 and sortie[0]["type"] == "ecart_prix_bl_a_verifier"
    assert sortie[0]["niveau"] == "N3" and "m" in sortie[0]["resume"]


def test_attentes_achats_terrain_seulement_en_attente():
    from m6_material_control import attentes_c5_c6
    assert attentes_c5_c6.attentes_achats_terrain([]) == []
    assert attentes_c5_c6.attentes_achats_terrain([None]) == []
    assert attentes_c5_c6.attentes_achats_terrain([{"decision": {"statut": "accepte"}}]) == []
    sortie = attentes_c5_c6.attentes_achats_terrain([{"decision": {"statut": "en_attente_approbation",
                                                                  "motif": "plafond_depasse"}}])
    assert len(sortie) == 1 and sortie[0]["type"] == "achat_terrain_a_approuver"
    assert sortie[0]["niveau"] == "N3"
