"""C6 — achat sur place complet (tests ROUGES avant code).

Ligne `achat_terrain` portant fournisseur, montant, raison/urgence, photo du reçu
CAS OBLIGATOIRE, chantier, approbation selon un plafond DÉCLARÉ : tracé (mouvement
audité), limité (plafond), transmis à M5 en attente « dépense à saisir », sans
jamais payer.
"""
from m6_material_control import achats_terrain


def _achat(**champs):
    base = {
        "materiau_id": "scellant-fictif",
        "quantite": 3.0,
        "montant": "25.50",
        "devise": "CAD",
        "fournisseur": "Quincaillerie Fictive",
        "raison": "urgence chantier",
        "chantier_id": "CH-FICT-1",
        "recu": "fichier:sha256:" + "ab" * 32,
    }
    base.update(champs)
    return base


def test_sans_recu_photo_obligatoire_refus_nomme():
    _, code = achats_terrain.valider_achat({k: v for k, v in _achat().items() if k != "recu"})
    assert code == "REJ-ACHAT-TERRAIN-PREUVE-MANQUANTE"


def test_montant_non_decimal_refuse_pas_de_float():
    _, code = achats_terrain.valider_achat(_achat(montant=25.5))
    assert code == "REJ-ACHAT-TERRAIN-MONTANT-INVALIDE"


def test_sous_plafond_accepte_sans_approbation_et_attente_m5_sans_paiement():
    achat, code = achats_terrain.valider_achat(_achat())
    assert code is None
    decision = achats_terrain.decider(achat, plafond="150")
    assert decision["statut"] == "accepte"
    assert decision["approbation_requise"] is False
    attente = achats_terrain.attente_m5(achat)
    assert attente["type"] == "depense_terrain_a_saisir"
    assert "paiement" not in attente and "remboursement" not in attente


def test_au_dela_du_plafond_attente_admin_avant_entree_stock():
    achat, _ = achats_terrain.valider_achat(_achat(montant="200.00"))
    decision = achats_terrain.decider(achat, plafond="150")
    assert decision["statut"] == "en_attente_approbation"
    assert decision["niveau"] == "N3"


def test_plafond_absent_fail_closed_aucun_defaut_invente():
    achat, _ = achats_terrain.valider_achat(_achat())
    decision = achats_terrain.decider(achat, plafond=None)
    assert decision["statut"] == "en_attente_approbation"
    assert decision["motif"] == "plafond_absent"


def test_borne_plafond_incluse_sous_plafond_accepte():
    achat, _ = achats_terrain.valider_achat(_achat(montant="150.00"))
    decision = achats_terrain.decider(achat, plafond="150")
    assert decision["statut"] == "accepte"


def test_meme_achat_declare_deux_fois_second_refuse_idempotent():
    achat, _ = achats_terrain.valider_achat(_achat())
    premier, code_premier = achats_terrain.enregistrer(achat, registre=[])
    assert code_premier is None
    second = achats_terrain.enregistrer(achat, registre=premier["registre"])
    assert second[1] == "REJ-ACHAT-TERRAIN-DEJA-DECLARE"


def test_role_non_autorise_refuse_sans_ecriture():
    _, code = achats_terrain.valider_achat(_achat(), role="visiteur")
    assert code == "REJ-ACHAT-TERRAIN-ROLE-INTERDIT"


def test_montant_bool_refuse_pas_un_nombre():
    _, code = achats_terrain.valider_achat(_achat(montant=True))
    assert code == "REJ-ACHAT-TERRAIN-MONTANT-INVALIDE"


def test_montant_zero_negatif_infini_refuses():
    for montant in ["0", "-5.00", "NaN", "Infinity", "25.5.0", ""]:
        _, code = achats_terrain.valider_achat(_achat(montant=montant))
        assert code == "REJ-ACHAT-TERRAIN-MONTANT-INVALIDE", montant


def test_quantite_zero_bool_texte_refusees():
    for quantite in [0, 0.0, -1.0, True, "3"]:
        _, code = achats_terrain.valider_achat(_achat(quantite=quantite))
        assert code == "REJ-ACHAT-TERRAIN-QUANTITE-INVALIDE", repr(quantite)


def test_champs_incomplets_materiau_devises_fournisseur_raison_refuses():
    assert achats_terrain.valider_achat({})[1] == "REJ-ACHAT-TERRAIN-STRUCTURE-INVALIDE"
    assert achats_terrain.valider_achat(None)[1] == "REJ-ACHAT-TERRAIN-STRUCTURE-INVALIDE"
    assert achats_terrain.valider_achat([])[1] == "REJ-ACHAT-TERRAIN-STRUCTURE-INVALIDE"
    assert achats_terrain.valider_achat(_achat(materiau_id=""))[1] == "REJ-ACHAT-TERRAIN-STRUCTURE-INVALIDE"
    assert achats_terrain.valider_achat(_achat(materiau_id=5))[1] == "REJ-ACHAT-TERRAIN-STRUCTURE-INVALIDE"
    assert achats_terrain.valider_achat(_achat(devise=" "))[1] == "REJ-ACHAT-TERRAIN-DEVISE-INVALIDE"
    assert achats_terrain.valider_achat(_achat(fournisseur="  "))[1] == "REJ-ACHAT-TERRAIN-FOURNISSEUR-INVALIDE"
    assert achats_terrain.valider_achat(_achat(raison=""))[1] == "REJ-ACHAT-TERRAIN-RAISON-INVALIDE"
    assert achats_terrain.valider_achat(_achat(chantier_id=""))[1] == "REJ-ACHAT-TERRAIN-STRUCTURE-INVALIDE"
    assert achats_terrain.valider_achat(_achat(recu="fichier:sha256:zzzz"))[1] == \
        "REJ-ACHAT-TERRAIN-PREUVE-MANQUANTE"


def test_plafond_illisible_zero_negatif_attente_plafond_absent():
    achat, _ = achats_terrain.valider_achat(_achat())
    for plafond in ["150.0.0", "", "0", "-10", "NaN", 150]:
        decision = achats_terrain.decider(achat, plafond=plafond)
        assert decision["statut"] == "en_attente_approbation", repr(plafond)
        assert decision["motif"] == "plafond_absent", repr(plafond)


def test_juste_au_dela_du_plafond_attente_montant_et_plafond_dits():
    achat, _ = achats_terrain.valider_achat(_achat(montant="150.01"))
    decision = achats_terrain.decider(achat, plafond="150")
    assert decision["statut"] == "en_attente_approbation"
    assert decision["motif"] == "plafond_depasse"
    assert decision["montant"] == "150.01" and decision["plafond"] == "150"


def test_attente_m5_source_recu_terrain_sans_paiement_ni_remboursement():
    achat, _ = achats_terrain.valider_achat(_achat())
    attente = achats_terrain.attente_m5(achat)
    assert attente["source_prix"] == "RECU_TERRAIN"
    assert attente["recu"] == _achat()["recu"]
    assert attente["chantier_id"] == "CH-FICT-1"
    for cle in ("paiement", "remboursement", "ordre", "payer"):
        assert cle not in attente
