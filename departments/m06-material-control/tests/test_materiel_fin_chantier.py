"""PLAN T1.1-d/d2 — formulaire de fin de chantier enrichi
(materiel.soumettre_materiaux_utilises), NOUVELLE fonction distincte de
consommer_materiaux (m6_consommer_materiaux). T1.1-d2 : la déclaration validée est
persistée au registre (mouvements typés, tout-ou-rien, idempotente par wct_id)."""


from m6_material_control import materiel, stock
from m6_material_control.registre import Registre

CLES_MONETAIRES_INTERDITES = {
    "cout_unitaire",
    "cout",
    "prix",
    "montant",
    "devise",
    "unite_monetaire",
    "montant_total_estime",
}


def collecter_cles_recursivement(valeur):
    cles = set()
    if isinstance(valeur, dict):
        for cle, sous_valeur in valeur.items():
            cles.add(cle)
            cles.update(collecter_cles_recursivement(sous_valeur))
    elif isinstance(valeur, list):
        for element in valeur:
            cles.update(collecter_cles_recursivement(element))
    return cles


def wct_valide(wct_id="wct-1"):
    return {
        "wct_id": wct_id, "intervention_id": "intervention-1", "lead_id": "lead-1",
        "technicien_id": "tech-1", "horodatage_completion": "2025-01-01T00:00:00Z",
        "fix_gps_completion": {"latitude": 1.0, "longitude": 2.0},
        "duree_reelle_minutes": 30, "ecart_signale": False, "revue_id": None,
        "hash_maillon": "a" * 64, "consommateurs_cibles": ["M6"], "devis_id": None,
    }


def ligne_prevu(materiau_id="MAT-1", quantite=8.0, quantite_estimee=10.0, unite="boite"):
    return {
        "type_ligne": "prevu", "materiau_id": materiau_id, "quantite": quantite,
        "unite": unite, "quantite_estimee": quantite_estimee,
    }


def ligne_non_prevu(materiau_id="MAT-2", quantite=3.0, unite="piece"):
    return {"type_ligne": "non_prevu", "materiau_id": materiau_id, "quantite": quantite, "unite": unite}


def ligne_retour(materiau_id="MAT-1", quantite=1.0, unite="boite"):
    return {"type_ligne": "retour", "materiau_id": materiau_id, "quantite": quantite, "unite": unite}


def ligne_perte(materiau_id="MAT-3", quantite=2.0, unite="rouleau"):
    return {"type_ligne": "perte", "materiau_id": materiau_id, "quantite": quantite, "unite": unite}


def ligne_bris(materiau_id="MAT-4", quantite=1.0, unite="panneau"):
    return {"type_ligne": "bris", "materiau_id": materiau_id, "quantite": quantite, "unite": unite}


def ligne_achat_terrain(materiau_id="MAT-5", quantite=5.0, unite="vis", photo=True, recu=False):
    return {
        "type_ligne": "achat_terrain", "materiau_id": materiau_id, "quantite": quantite,
        "unite": unite, "photo_fournie": photo, "recu_fourni": recu,
    }


def formulaire_valide(lignes=None, wct_id="wct-1", chantier_id="CHANTIER-1"):
    return {
        "wct_id": wct_id, "intervention_id": "intervention-1", "chantier_id": chantier_id,
        "lignes_materiaux": lignes if lignes is not None else [
            ligne_prevu(), ligne_non_prevu(), ligne_retour(), ligne_perte(),
            ligne_bris(), ligne_achat_terrain(),
        ],
    }


def registre_avec_receptions(chantier_id="CHANTIER-1", materiaux=None, cout=5.0):
    """Registre réel pré-alimenté d'une RECEPTION par matériau (résolution de coût,
    NEW-PROD-006/_dernier_cout_unitaire_connu — la même règle que consommer_materiaux)."""
    registre = Registre()
    materiaux = materiaux or ["MAT-1", "MAT-2", "MAT-3", "MAT-4", "MAT-5"]
    for materiau_id in materiaux:
        registre.ajouter({
            "type_mouvement": "RECEPTION", "chantier_id": chantier_id, "materiau_id": materiau_id,
            "quantite": 100.0, "cout_unitaire": cout,
        })
    return registre


# --- Cas nominal ---------------------------------------------------------------------


def test_soumettre_materiaux_utilises_accepte_les_six_types_de_ligne():
    registre = registre_avec_receptions()

    confirmation, code = materiel.soumettre_materiaux_utilises(wct_valide(), formulaire_valide(), registre)

    assert code is None
    assert confirmation["intervention_id"] == "intervention-1"
    assert confirmation["chantier_id"] == "CHANTIER-1"
    types_confirmes = {ligne["type_ligne"] for ligne in confirmation["lignes_declarees"]}
    assert types_confirmes == {"prevu", "non_prevu", "retour", "perte", "bris", "achat_terrain"}


def test_ligne_prevu_porte_la_quantite_estimee_dans_la_confirmation():
    registre = registre_avec_receptions()

    confirmation, code = materiel.soumettre_materiaux_utilises(
        wct_valide(), formulaire_valide([ligne_prevu(quantite=8.0, quantite_estimee=10.0)]), registre,
    )

    assert code is None
    ligne = confirmation["lignes_declarees"][0]
    assert ligne == {
        "type_ligne": "prevu", "materiau_id": "MAT-1", "quantite": 8.0,
        "unite": "boite", "quantite_estimee": 10.0,
    }


def test_ligne_non_prevu_ne_porte_pas_de_quantite_estimee():
    registre = registre_avec_receptions()

    confirmation, code = materiel.soumettre_materiaux_utilises(
        wct_valide(), formulaire_valide([ligne_non_prevu()]), registre,
    )

    assert code is None
    assert "quantite_estimee" not in confirmation["lignes_declarees"][0]


def test_achat_terrain_avec_photo_seule_est_accepte():
    registre = registre_avec_receptions()

    confirmation, code = materiel.soumettre_materiaux_utilises(
        wct_valide(), formulaire_valide([ligne_achat_terrain(photo=True, recu=False)]), registre,
    )

    assert code is None
    assert confirmation["lignes_declarees"][0]["photo_fournie"] is True
    assert confirmation["lignes_declarees"][0]["recu_fourni"] is False


def test_achat_terrain_avec_recu_seul_est_accepte():
    registre = registre_avec_receptions()

    confirmation, code = materiel.soumettre_materiaux_utilises(
        wct_valide(), formulaire_valide([ligne_achat_terrain(photo=False, recu=True)]), registre,
    )

    assert code is None


def test_confirmation_ne_contient_aucune_cle_monetaire():
    registre = registre_avec_receptions()

    confirmation, code = materiel.soumettre_materiaux_utilises(wct_valide(), formulaire_valide(), registre)

    assert code is None
    assert not collecter_cles_recursivement(confirmation).intersection(CLES_MONETAIRES_INTERDITES)


# --- Rejets fail-closed nommés ---------------------------------------------------------


def test_rejette_achat_terrain_sans_photo_ni_recu_par_un_verdict_fail_closed_nomme():
    registre = registre_avec_receptions()
    formulaire = formulaire_valide([ligne_achat_terrain(photo=False, recu=False)])

    confirmation, code = materiel.soumettre_materiaux_utilises(wct_valide(), formulaire, registre)

    assert confirmation is None
    assert code == "REJ-ACHAT-TERRAIN-PREUVE-MANQUANTE"
    assert registre.taille() == 5  # aucune écriture au-delà des RECEPTION du fixture


def test_rejette_un_wct_sans_consommateur_m6():
    registre = registre_avec_receptions()
    wct = wct_valide()
    wct["consommateurs_cibles"] = ["M5"]

    confirmation, code = materiel.soumettre_materiaux_utilises(wct, formulaire_valide(), registre)

    assert confirmation is None
    assert code == "REJ-WCT-CONSOMMATEUR-M6-ABSENT"


def test_rejette_un_formulaire_incoherent_avec_le_wct():
    registre = registre_avec_receptions()
    formulaire = formulaire_valide()
    formulaire["wct_id"] = "wct-2"

    confirmation, code = materiel.soumettre_materiaux_utilises(wct_valide(), formulaire, registre)

    assert confirmation is None
    assert code == "REJ-FORMULAIRE-MATERIAUX-WCT-INCOHERENT"


def test_rejette_une_cle_de_formulaire_manquante():
    registre = registre_avec_receptions()
    formulaire = formulaire_valide()
    del formulaire["chantier_id"]

    confirmation, code = materiel.soumettre_materiaux_utilises(wct_valide(), formulaire, registre)

    assert confirmation is None
    assert code == "REJ-FORMULAIRE-MATERIAUX-STRUCTURE-INVALIDE"


def test_rejette_une_liste_de_lignes_vide():
    registre = registre_avec_receptions()
    formulaire = formulaire_valide([])

    confirmation, code = materiel.soumettre_materiaux_utilises(wct_valide(), formulaire, registre)

    assert confirmation is None
    assert code == "REJ-FORMULAIRE-MATERIAUX-STRUCTURE-INVALIDE"


def test_rejette_un_type_de_ligne_hors_liste_et_jamais_vol():
    registre = registre_avec_receptions()
    formulaire = formulaire_valide([{
        "type_ligne": "vol", "materiau_id": "MAT-1", "quantite": 1.0, "unite": "boite",
    }])

    confirmation, code = materiel.soumettre_materiaux_utilises(wct_valide(), formulaire, registre)

    assert confirmation is None
    assert code == "REJ-LIGNE-MATERIAUX-TYPE-INVALIDE"


def test_rejette_une_ligne_prevu_sans_quantite_estimee():
    registre = registre_avec_receptions()
    formulaire = formulaire_valide([{
        "type_ligne": "prevu", "materiau_id": "MAT-1", "quantite": 1.0, "unite": "boite",
    }])

    confirmation, code = materiel.soumettre_materiaux_utilises(wct_valide(), formulaire, registre)

    assert confirmation is None
    assert code == "REJ-LIGNE-MATERIAUX-STRUCTURE-INVALIDE"


def test_rejette_une_ligne_non_prevu_avec_une_quantite_estimee_en_trop():
    registre = registre_avec_receptions()
    formulaire = formulaire_valide([{
        "type_ligne": "non_prevu", "materiau_id": "MAT-1", "quantite": 1.0,
        "unite": "boite", "quantite_estimee": 5.0,
    }])

    confirmation, code = materiel.soumettre_materiaux_utilises(wct_valide(), formulaire, registre)

    assert confirmation is None
    assert code == "REJ-LIGNE-MATERIAUX-STRUCTURE-INVALIDE"


def test_rejette_quantite_nulle_ou_negative():
    for quantite in (0, -1.0):
        registre = registre_avec_receptions()
        formulaire = formulaire_valide([ligne_non_prevu(quantite=quantite)])
        confirmation, code = materiel.soumettre_materiaux_utilises(wct_valide(), formulaire, registre)
        assert confirmation is None
        assert code == "REJ-LIGNE-MATERIAUX-QUANTITE-INVALIDE"


def test_rejette_quantite_nan_et_infinie():
    for quantite in (float("nan"), float("inf"), float("-inf")):
        registre = registre_avec_receptions()
        formulaire = formulaire_valide([ligne_non_prevu(quantite=quantite)])
        confirmation, code = materiel.soumettre_materiaux_utilises(wct_valide(), formulaire, registre)
        assert confirmation is None
        assert code == "REJ-LIGNE-MATERIAUX-QUANTITE-INVALIDE"


def test_rejette_une_unite_vide():
    registre = registre_avec_receptions()
    formulaire = formulaire_valide([ligne_non_prevu(unite="")])

    confirmation, code = materiel.soumettre_materiaux_utilises(wct_valide(), formulaire, registre)

    assert confirmation is None
    assert code == "REJ-LIGNE-MATERIAUX-UNITE-INVALIDE"


def test_rejette_une_cle_interdite_glissee_dans_une_ligne():
    registre = registre_avec_receptions()
    formulaire = formulaire_valide([{**ligne_non_prevu(), "virement": "v-1"}])

    confirmation, code = materiel.soumettre_materiaux_utilises(wct_valide(), formulaire, registre)

    assert confirmation is None
    assert code == "REJ-FRONTIERE-VIOLEE"


def test_consommer_materiaux_reste_inchange_apres_l_ajout_du_formulaire_enrichi():
    """m6_consommer_materiaux garde son contrat {materiau_id, quantite} exact : la
    nouvelle fonction ne le remplace pas (PLAN T1.1-d point 1)."""
    registre = Registre()
    registre.ajouter({
        "type_mouvement": "RECEPTION", "chantier_id": "C1", "materiau_id": "MAT-1",
        "quantite": 10.0, "cout_unitaire": 5.0,
    })
    formulaire = {
        "wct_id": "wct-1", "intervention_id": "intervention-1", "chantier_id": "C1",
        "lignes_consommees": [{"materiau_id": "MAT-1", "quantite": 3.0}],
    }

    confirmation, code = materiel.consommer_materiaux(wct_valide(), formulaire, registre)

    assert code is None
    assert confirmation["stock_restant"] == [{"materiau_id": "MAT-1", "quantite": 7.0}]


# --- Écriture au registre (PLAN T1.1-d2 point 1) ---------------------------------------


def test_prevu_non_prevu_et_achat_terrain_ecrivent_une_consommation_signee_negativement():
    registre = registre_avec_receptions()
    formulaire = formulaire_valide([
        ligne_prevu(materiau_id="MAT-1", quantite=6.0),
        ligne_non_prevu(materiau_id="MAT-2", quantite=3.0),
        ligne_achat_terrain(materiau_id="MAT-5", quantite=2.0),
    ])

    confirmation, code = materiel.soumettre_materiaux_utilises(wct_valide(), formulaire, registre)

    assert code is None
    nouveaux = registre.lire()[5:]
    assert {m["type_mouvement"] for m in nouveaux} == {"CONSOMMATION"}
    par_materiau = {m["materiau_id"]: m["quantite"] for m in nouveaux}
    assert par_materiau == {"MAT-1": -6.0, "MAT-2": -3.0, "MAT-5": -2.0}
    assert all(m["cout_unitaire"] == 5.0 for m in nouveaux)
    assert all(m["wct_id"] == "wct-1" for m in nouveaux)


def test_retour_ecrit_un_mouvement_retour_signe_positivement():
    registre = registre_avec_receptions()
    formulaire = formulaire_valide([ligne_retour(materiau_id="MAT-1", quantite=4.0)])

    confirmation, code = materiel.soumettre_materiaux_utilises(wct_valide(), formulaire, registre)

    assert code is None
    nouveau = registre.lire()[5]
    assert nouveau["type_mouvement"] == "RETOUR"
    assert nouveau["quantite"] == 4.0


def test_perte_et_bris_ecrivent_leur_propre_type_signe_negativement():
    registre = registre_avec_receptions()
    formulaire = formulaire_valide([
        ligne_perte(materiau_id="MAT-3", quantite=2.0),
        ligne_bris(materiau_id="MAT-4", quantite=1.5),
    ])

    confirmation, code = materiel.soumettre_materiaux_utilises(wct_valide(), formulaire, registre)

    assert code is None
    nouveaux = registre.lire()[5:]
    types_et_quantites = {(m["type_mouvement"], m["materiau_id"]): m["quantite"] for m in nouveaux}
    assert types_et_quantites == {("PERTE", "MAT-3"): -2.0, ("BRIS", "MAT-4"): -1.5}
    # PERTE/BRIS sortent du stock SANS être comptés comme CONSOMMATION (type distinct).
    assert "CONSOMMATION" not in {m["type_mouvement"] for m in nouveaux}


def test_ecriture_est_tout_ou_rien_si_une_ligne_echoue_le_cout():
    registre = registre_avec_receptions(materiaux=["MAT-1"])  # MAT-2 n'a jamais été reçu
    taille_avant = registre.taille()
    formulaire = formulaire_valide([
        ligne_prevu(materiau_id="MAT-1", quantite=1.0),
        ligne_non_prevu(materiau_id="MAT-2", quantite=1.0),
    ])

    confirmation, code = materiel.soumettre_materiaux_utilises(wct_valide(), formulaire, registre)

    assert confirmation is None
    assert code == "REJ-COUT-UNITAIRE-INTROUVABLE"
    # Rien n'a été écrit pour MAT-1 non plus : tout ou rien (ajouter_lot n'est jamais
    # appelé si une seule ligne échoue la résolution de coût).
    assert registre.taille() == taille_avant


def test_achat_terrain_reussit_quand_le_cout_est_resolu_et_echoue_sinon():
    """Même règle de coût unitaire fail-closed que consommer_materiaux, appliquée
    uniformément aux six types de ligne — y compris achat_terrain (PLAN T1.1-d2)."""
    registre_avec_historique = registre_avec_receptions(materiaux=["MAT-5"])
    confirmation, code = materiel.soumettre_materiaux_utilises(
        wct_valide(), formulaire_valide([ligne_achat_terrain(materiau_id="MAT-5")]), registre_avec_historique,
    )
    assert code is None

    registre_sans_historique = Registre()  # aucune RECEPTION préalable pour MAT-9
    confirmation, code = materiel.soumettre_materiaux_utilises(
        wct_valide(wct_id="wct-2"),
        formulaire_valide([ligne_achat_terrain(materiau_id="MAT-9")], wct_id="wct-2"),
        registre_sans_historique,
    )
    assert confirmation is None
    assert code == "REJ-COUT-UNITAIRE-INTROUVABLE"


# --- Stock théorique cohérent après écriture (PLAN T1.1-d2 point 1) --------------------


def test_stock_theorique_apres_declaration_complete_reflete_les_six_types():
    registre = registre_avec_receptions(cout=5.0)  # 100.0 reçu par matériau
    formulaire = formulaire_valide([
        ligne_prevu(materiau_id="MAT-1", quantite=8.0, quantite_estimee=10.0),
        ligne_retour(materiau_id="MAT-1", quantite=3.0),
        ligne_perte(materiau_id="MAT-3", quantite=2.0),
        ligne_bris(materiau_id="MAT-4", quantite=1.0),
    ])

    confirmation, code = materiel.soumettre_materiaux_utilises(wct_valide(), formulaire, registre)

    assert code is None
    # MAT-1 : 100 reçu - 8 consommé (prevu) + 3 réintégré (retour) = 95.
    assert stock.deriver_stock_theorique("CHANTIER-1", "MAT-1", registre) == 95.0
    # MAT-3 : 100 reçu - 2 perdu = 98 (sortie du stock, mais aucune CONSOMMATION écrite).
    assert stock.deriver_stock_theorique("CHANTIER-1", "MAT-3", registre) == 98.0
    # MAT-4 : 100 reçu - 1 brisé = 99.
    assert stock.deriver_stock_theorique("CHANTIER-1", "MAT-4", registre) == 99.0


def test_un_retour_isole_reintegre_exactement_le_stock():
    registre = Registre()
    registre.ajouter({
        "type_mouvement": "RECEPTION", "chantier_id": "CHANTIER-1", "materiau_id": "MAT-1",
        "quantite": 10.0, "cout_unitaire": 5.0,
    })
    registre.ajouter({
        "type_mouvement": "CONSOMMATION", "chantier_id": "CHANTIER-1", "materiau_id": "MAT-1",
        "quantite": -10.0, "cout_unitaire": 5.0,
    })
    assert stock.deriver_stock_theorique("CHANTIER-1", "MAT-1", registre) == 0.0

    formulaire = formulaire_valide([ligne_retour(materiau_id="MAT-1", quantite=4.0)])
    confirmation, code = materiel.soumettre_materiaux_utilises(wct_valide(), formulaire, registre)

    assert code is None
    assert stock.deriver_stock_theorique("CHANTIER-1", "MAT-1", registre) == 4.0


# --- Idempotence (PLAN T1.1-d2 point 4) -------------------------------------------------


def test_une_seconde_declaration_pour_le_meme_wct_id_est_rejetee_nommement():
    registre = registre_avec_receptions()
    formulaire = formulaire_valide([ligne_prevu(materiau_id="MAT-1", quantite=1.0)])

    premiere, code_premiere = materiel.soumettre_materiaux_utilises(wct_valide(), formulaire, registre)
    taille_apres_premiere = registre.taille()
    seconde, code_seconde = materiel.soumettre_materiaux_utilises(wct_valide(), formulaire, registre)

    assert code_premiere is None
    assert seconde is None
    assert code_seconde == "REJ-DECLARATION-DEJA-SOUMISE"
    # Rien n'a été ajouté par la tentative rejetée.
    assert registre.taille() == taille_apres_premiere


def test_deux_wct_id_distincts_sur_le_meme_chantier_sont_tous_deux_acceptes():
    registre = registre_avec_receptions()
    formulaire_1 = formulaire_valide([ligne_prevu(materiau_id="MAT-1", quantite=1.0)], wct_id="wct-1")
    formulaire_2 = formulaire_valide([ligne_prevu(materiau_id="MAT-1", quantite=1.0)], wct_id="wct-2")

    _, code_1 = materiel.soumettre_materiaux_utilises(wct_valide(wct_id="wct-1"), formulaire_1, registre)
    _, code_2 = materiel.soumettre_materiaux_utilises(wct_valide(wct_id="wct-2"), formulaire_2, registre)

    assert code_1 is None
    assert code_2 is None
