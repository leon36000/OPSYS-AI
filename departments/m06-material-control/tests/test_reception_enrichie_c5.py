"""C5 — réception enrichie (tests ROUGES avant code).

Ce qui manque à `reception.py` / `receptionner_commande` (M6.7) : par ligne un
`statut_ligne` (conforme, manquant, substitué, endommagé), le matériau substitué,
la preuve photo CAS quand exigée, le lieu de livraison et le prix du bon de
livraison lu (donnée saisie, marquée source) dont l'écart au prix prévu déclenche
l'alerte au-delà du seuil DÉCLARÉ.
"""
from m6_material_control import details_reception


def _ligne(materiau_id="gouttiere-5po", statut="conforme", **champs):
    ligne = {"materiau_id": materiau_id, "statut_ligne": statut}
    ligne.update(champs)
    return ligne


def test_statut_manquant_juge_non_conforme_sans_inventer_de_quantite():
    verdict = details_reception.qualifier_livraison(
        lignes_commandees=[{"materiau_id": "gouttiere-5po", "quantite_demandee": 10.0}],
        lignes_recues=[{"materiau_id": "gouttiere-5po", "quantite_recue": 0.0}],
        details=[_ligne(statut="manquant")],
    )
    assert verdict["lignes"][0]["statut_ligne"] == "manquant"
    assert verdict["verdict_reception"] == "RECEPTION_INFERIEURE"


def test_substitue_sans_materiau_substitue_refuse_nomme():
    _, code = details_reception.valider_details([_ligne(statut="substitue")])
    assert code == "REJ-RECEPTION-SUBSTITUE-INCOMPLET"


def test_endommage_sans_photo_cas_refuse_nomme():
    _, code = details_reception.valider_details(
        [_ligne(statut="endommage", photos=[])]
    )
    assert code == "REJ-RECEPTION-PREUVE-MANQUANTE"


def test_reference_photo_non_cas_refusee():
    _, code = details_reception.valider_details(
        [_ligne(statut="endommage", photos=["/tmp/photo.jpg"])]
    )
    assert code == "REJ-RECEPTION-PREUVE-MANQUANTE"


def test_prix_bl_superieur_de_20_pourcent_signale_au_dela_du_seuil_declare():
    signaux = details_reception.detecter_ecarts_prix_bl(
        lignes_po=[{"materiau_id": "gouttiere-5po", "prix_unitaire_prevu": 10.0}],
        prix_bl={"gouttiere-5po": 12.0},
        seuil_pourcentage=0.15,
    )
    assert [s["materiau_id"] for s in signaux] == ["gouttiere-5po"]
    assert signaux[0]["source_prix"] == "BON_LIVRAISON"


def test_prix_bl_sans_source_reste_silencieux_fail_closed():
    assert details_reception.detecter_ecarts_prix_bl(
        lignes_po=[{"materiau_id": "gouttiere-5po", "prix_unitaire_prevu": 10.0}],
        prix_bl={},
        seuil_pourcentage=0.15,
    ) == []


def test_lieu_livraison_hors_liste_fermee_refuse():
    _, code = details_reception.valider_lieu({"type": "grenier"})
    assert code == "REJ-RECEPTION-LIEU-INVALIDE"


def test_injection_texte_dans_statut_refusee_sans_executer():
    _, code = details_reception.valider_details(
        [_ligne(statut="conforme'; DROP TABLE stock;--")]
    )
    assert code == "REJ-RECEPTION-STATUT-INCONNU"


def test_details_vides_ou_non_liste_refuses():
    for details in [[], {}, "conforme", [{"statut_ligne": "conforme"}], [{}], [None], "x", None, [[]]]:
        assert details_reception.valider_details(details)[1] in (
            "REJ-RECEPTION-DETAILS-INVALIDES", "REJ-RECEPTION-STATUT-INCONNU")


def test_substitue_blanc_et_endommage_photo_non_cas_refuses():
    _, code = details_reception.valider_details([_ligne(statut="substitue", materiau_substitue="  ")])
    assert code == "REJ-RECEPTION-SUBSTITUE-INCOMPLET"
    _, code = details_reception.valider_details(
        [_ligne(statut="endommage", photos=["fichier:sha256:" + "zz" * 32])])
    assert code == "REJ-RECEPTION-PREUVE-MANQUANTE"


def test_lieu_non_objet_et_lieu_sans_reference_refuses():
    assert details_reception.valider_lieu("depot")[1] == "REJ-RECEPTION-LIEU-INVALIDE"
    assert details_reception.valider_lieu({"type": "retour"})[1] == "REJ-RECEPTION-LIEU-INVALIDE"
    assert details_reception.valider_lieu({"type": "camion"})[1] == "REJ-RECEPTION-LIEU-INVALIDE"


def test_prix_bl_borne_15_pourcent_signale_baisse_signalee():
    signaux = details_reception.detecter_ecarts_prix_bl(
        [{"materiau_id": "gouttiere-5po", "prix_unitaire_prevu": "10.00"}],
        {"gouttiere-5po": "11.50"}, seuil_pourcentage=0.15)
    assert len(signaux) == 1 and signaux[0]["ecart_pourcentage"] >= 0.15
    assert signaux[0]["materiau_id"] == "gouttiere-5po"
    baisse = details_reception.detecter_ecarts_prix_bl(
        [{"materiau_id": "gouttiere-5po", "prix_unitaire_prevu": "10.00"}],
        {"gouttiere-5po": "8.00"}, seuil_pourcentage=0.15)
    assert len(baisse) == 1, "valeur absolue : une baisse se vérifie aussi"
    petit = details_reception.detecter_ecarts_prix_bl(
        [{"materiau_id": "gouttiere-5po", "prix_unitaire_prevu": "10.00"}],
        {"gouttiere-5po": "10.01"}, seuil_pourcentage=0.15)
    assert petit == [], "1 ‰ ne déclenche pas le seuil de 15 %"
    assert details_reception.detecter_ecarts_prix_bl(
        [{"materiau_id": "gouttiere-5po", "prix_unitaire_prevu": "1.00"}],
        {"gouttiere-5po": "1.16"}, seuil_pourcentage=0.15) != []


def test_prix_bl_seuil_absent_illisible_prix_prevu_zero_silencieux():
    lignes = [{"materiau_id": "gouttiere-5po", "prix_unitaire_prevu": "10.00"}]
    assert details_reception.detecter_ecarts_prix_bl(lignes, {"gouttiere-5po": "12.00"},
                                                     seuil_pourcentage=None) == []
    assert details_reception.detecter_ecarts_prix_bl(lignes, "12.00", seuil_pourcentage=0.15) == []
    assert details_reception.detecter_ecarts_prix_bl(lignes, {"gouttiere-5po": "texte"},
                                                     seuil_pourcentage=0.15) == []
    assert details_reception.detecter_ecarts_prix_bl(
        [{"materiau_id": "gouttiere-5po", "prix_unitaire_prevu": 0}],
        {"gouttiere-5po": "12.00"}, seuil_pourcentage=0.15) == []
    assert details_reception.detecter_ecarts_prix_bl(
        [{"materiau_id": "gouttiere-5po", "prix_unitaire_prevu": None}],
        {"gouttiere-5po": "12.00"}, seuil_pourcentage=0.15) == []


def test_verdicts_mixtes_superieurs_conformes_tues():
    commande = [{"materiau_id": "m", "quantite_demandee": 10.0}]
    assert details_reception.qualifier_livraison(
        commande, [{"materiau_id": "m", "quantite_recue": 12.0}], [])["verdict_reception"] == \
        "RECEPTION_SUPERIEURE"
    assert details_reception.qualifier_livraison(
        commande, [{"materiau_id": "m", "quantite_recue": 10.0}], [])["verdict_reception"] == "CONFORME"
    deux = [{"materiau_id": "a", "quantite_demandee": 10.0}, {"materiau_id": "b", "quantite_demandee": 10.0}]
    mixte = details_reception.qualifier_livraison(
        deux, [{"materiau_id": "a", "quantite_recue": 12.0}, {"materiau_id": "b", "quantite_recue": 8.0}],
        [])["verdict_reception"]
    assert mixte == "RECEPTION_MIXTE"
    tout_positif = details_reception.qualifier_livraison(
        deux, [{"materiau_id": "a", "quantite_recue": 11.0}, {"materiau_id": "b", "quantite_recue": 12.0}],
        [])["verdict_reception"]
    assert tout_positif == "RECEPTION_SUPERIEURE"
    tout_negatif = details_reception.qualifier_livraison(
        deux, [{"materiau_id": "a", "quantite_recue": 9.0}, {"materiau_id": "b", "quantite_recue": 8.0}],
        [])["verdict_reception"]
    assert tout_negatif == "RECEPTION_INFERIEURE"
    assert details_reception.qualifier_livraison(
        commande, [{"materiau_id": "m", "quantite_recue": 10.0}],
        [{"materiau_id": "m", "statut_ligne": "substitue",
          "materiau_substitue": "autre-fictif"}])["lignes"][0]["materiau_substitue"] == "autre-fictif"
    photo = "fichier:sha256:" + "ab" * 32
    assert details_reception.qualifier_livraison(
        commande, [{"materiau_id": "m", "quantite_recue": 10.0}],
        [{"materiau_id": "m", "statut_ligne": "endommage", "photos": [photo]}])["lignes"][0][
        "photos"] == [photo]


def test_validation_details_forme_et_statut():
    assert details_reception.valider_details(None)[1] == "REJ-RECEPTION-DETAILS-INVALIDES"
    assert details_reception.valider_details("x")[1] == "REJ-RECEPTION-DETAILS-INVALIDES"
    assert details_reception.valider_details([None])[1] == "REJ-RECEPTION-DETAILS-INVALIDES"
    assert details_reception.valider_details([{"materiau_id": "", "statut_ligne": "conforme"}])[1] == \
        "REJ-RECEPTION-DETAILS-INVALIDES"
    assert details_reception.valider_details(
        [{"materiau_id": "m", "statut_ligne": "perdu"}])[1] == "REJ-RECEPTION-STATUT-INCONNU"
    ok, _ = details_reception.valider_details(
        [{"materiau_id": "m", "statut_ligne": "substitue", "materiau_substitue": "autre"}])
    assert ok is not None
    photo = "fichier:sha256:" + "ab" * 32
    ok, _ = details_reception.valider_details(
        [{"materiau_id": "m", "statut_ligne": "endommage", "photos": [photo]}])
    assert ok is not None
