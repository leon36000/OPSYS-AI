from m6_material_control import materiel


def wct_valide():
    return {
        "wct_id": "wct-1",
        "intervention_id": "intervention-1",
        "lead_id": "lead-1",
        "technicien_id": "tech-1",
        "horodatage_completion": "2025-01-01T00:00:00Z",
        "fix_gps_completion": {"latitude": 1.0, "longitude": 2.0},
        "duree_reelle_minutes": 30,
        "ecart_signale": False,
        "revue_id": None,
        "hash_maillon": "a" * 64,
        "consommateurs_cibles": ["M6"],
        "devis_id": None,
    }


class RegistreVide:
    def lire(self):
        return []


def test_une_ligne_consommee_malformee_produit_un_rejet_nomme_jamais_une_exception():
    formulaire = {
        "wct_id": "wct-1",
        "intervention_id": "intervention-1",
        "chantier_id": "CHANTIER-1",
        "lignes_consommees": [{"champ_inconnu": "valeur"}],
    }

    confirmation, code_verdict = materiel.consommer_materiaux(
        wct_valide(),
        formulaire,
        RegistreVide(),
    )

    assert confirmation is None
    assert code_verdict == "REJ-FORMULAIRE-LIGNE-INVALIDE"


def test_consommation_materiaux_nominale_continue_de_fonctionner():
    # CORRECTION NEW-PROD-006 : RegistreVide ne convient plus comme cas nominal.
    # Le fix source vérifie désormais la disponibilité réelle en stock AVANT de
    # confirmer une consommation (stock.verifier_disponibilite_consommation).
    # Consommer sans RECEPTION préalable n'est plus un cas nominal : c'est
    # exactement la classe de bug fermée par le fix (confirmer une sortie sans
    # vérité de stock -> REJ-STOCK-INSUFFISANT). On initialise donc un vrai
    # Registre avec une RECEPTION suffisante pour MAT-1/CHANTIER-1 avant l'appel,
    # et on ajuste stock_restant en conséquence (10.0 - 3.0 = 7.0).
    from m6_material_control.registre import Registre

    registre = Registre()
    registre.ajouter(
        {
            "type_mouvement": "RECEPTION",
            "chantier_id": "CHANTIER-1",
            "materiau_id": "MAT-1",
            "quantite": 10.0,
            "cout_unitaire": 12.5,
        }
    )

    formulaire = {
        "wct_id": "wct-1",
        "intervention_id": "intervention-1",
        "chantier_id": "CHANTIER-1",
        "lignes_consommees": [
            {"materiau_id": "MAT-1", "quantite": 3.0}
        ],
    }

    confirmation, code_verdict = materiel.consommer_materiaux(
        wct_valide(),
        formulaire,
        registre,
    )

    assert code_verdict is None
    assert confirmation == {
        "intervention_id": "intervention-1",
        "chantier_id": "CHANTIER-1",
        "materiaux_confirmes": [
            {"materiau_id": "MAT-1", "quantite_declaree": 3.0}
        ],
        "stock_restant": [
            {"materiau_id": "MAT-1", "quantite": 7.0}
        ],
    }


def test_lignes_consommees_none_produit_un_rejet_nomme_jamais_une_exception():
    formulaire = {
        "wct_id": "wct-1",
        "intervention_id": "intervention-1",
        "chantier_id": "CHANTIER-1",
        "lignes_consommees": None,
    }

    confirmation, code_verdict = materiel.consommer_materiaux(
        wct_valide(),
        formulaire,
        RegistreVide(),
    )

    assert confirmation is None
    assert code_verdict == "REJ-FORMULAIRE-LIGNE-INVALIDE"


def test_quantite_chaine_produit_un_rejet_nomme_jamais_une_exception():
    formulaire = {
        "wct_id": "wct-1",
        "intervention_id": "intervention-1",
        "chantier_id": "CHANTIER-1",
        "lignes_consommees": [
            {"materiau_id": "MAT-1", "quantite": "trois"}
        ],
    }

    confirmation, code_verdict = materiel.consommer_materiaux(
        wct_valide(),
        formulaire,
        RegistreVide(),
    )

    assert confirmation is None
    assert code_verdict == "REJ-FORMULAIRE-LIGNE-INVALIDE"


def test_quantite_bool_produit_un_rejet_nomme_jamais_une_exception():
    for quantite in (True, False):
        formulaire = {
            "wct_id": "wct-1",
            "intervention_id": "intervention-1",
            "chantier_id": "CHANTIER-1",
            "lignes_consommees": [
                {"materiau_id": "MAT-1", "quantite": quantite}
            ],
        }

        confirmation, code_verdict = materiel.consommer_materiaux(
            wct_valide(),
            formulaire,
            RegistreVide(),
        )

        assert confirmation is None
        assert code_verdict == "REJ-FORMULAIRE-LIGNE-INVALIDE"


def test_consommer_materiaux_rejette_si_stock_insuffisant():
    from m6_material_control.registre import Registre

    registre = Registre()
    # Stock initial 2.0 pour MAT-1 sur CHANTIER-1
    registre.ajouter(
        {
            "type_mouvement": "RECEPTION",
            "chantier_id": "CHANTIER-1",
            "materiau_id": "MAT-1",
            "quantite": 2.0,
            "cout_unitaire": 10.0,
        }
    )
    formulaire = {
        "wct_id": "wct-1",
        "intervention_id": "intervention-1",
        "chantier_id": "CHANTIER-1",
        "lignes_consommees": [{"materiau_id": "MAT-1", "quantite": 5.0}],
    }
    longueur_avant = len(registre.lire())
    confirmation, code_verdict = materiel.consommer_materiaux(
        wct_valide(), formulaire, registre
    )
    assert confirmation is None
    assert code_verdict is not None
    assert "STOCK" in code_verdict or "INSUFFISANT" in code_verdict
    # Aucune persistance ne doit avoir eu lieu en cas de stock insuffisant
    assert len(registre.lire()) == longueur_avant


def test_consommer_materiaux_persiste_un_mouvement_consommation_au_registre():
    from m6_material_control.registre import Registre

    registre = Registre()
    registre.ajouter(
        {
            "type_mouvement": "RECEPTION",
            "chantier_id": "CHANTIER-1",
            "materiau_id": "MAT-1",
            "quantite": 10.0,
            "cout_unitaire": 12.5,
        }
    )
    longueur_avant = len(registre.lire())
    formulaire = {
        "wct_id": "wct-1",
        "intervention_id": "intervention-1",
        "chantier_id": "CHANTIER-1",
        "lignes_consommees": [{"materiau_id": "MAT-1", "quantite": 3.0}],
    }
    confirmation, code_verdict = materiel.consommer_materiaux(
        wct_valide(), formulaire, registre
    )
    assert code_verdict is None
    assert confirmation is not None
    maillons = registre.lire()
    assert len(maillons) == longueur_avant + 1
    dernier = maillons[-1]
    assert dernier["type_mouvement"] == "CONSOMMATION"
    assert dernier["chantier_id"] == "CHANTIER-1"
    assert dernier["materiau_id"] == "MAT-1"
    assert dernier["quantite"] == -3.0
    assert dernier["cout_unitaire"] == 12.5
    # Le hash doit être chaîné correctement
    assert dernier["hash_precedent"] == maillons[-2]["hash_maillon"]
    # La confirmation reflète le stock théorique après persistance
    assert confirmation["stock_restant"] == [{"materiau_id": "MAT-1", "quantite": 7.0}]


def test_consommer_materiaux_rejette_si_cout_unitaire_introuvable():
    # Convention NEW-PROD-006 : dernier RECEPTION connu, sinon REJ-COUT-UNITAIRE-INTROUVABLE
    # On force le passage du garde stock pour isoler le cas coût introuvable
    from m6_material_control import stock as stock_module

    class RegistreSansReceptionPourMat1:
        def __init__(self):
            self._ajouter_lot_appele = False

        def lire(self):
            # Aucune RECEPTION pour (CHANTIER-1, MAT-1) -> coût introuvable
            # On met une RECEPTION pour un autre matériau pour prouver le filtrage par materiau_id
            return [
                {
                    "type_mouvement": "RECEPTION",
                    "chantier_id": "CHANTIER-1",
                    "materiau_id": "MAT-AUTRE",
                    "quantite": 10.0,
                    "cout_unitaire": 99.0,
                    "hash_precedent": "",
                    "hash_maillon": "a" * 64,
                    "index": 0,
                }
            ]

        def ajouter(self, mouvement):
            self._ajouter_lot_appele = True
            return None, None

        def ajouter_lot(self, mouvements):
            self._ajouter_lot_appele = True
            return None, None

    registre = RegistreSansReceptionPourMat1()
    formulaire = {
        "wct_id": "wct-1",
        "intervention_id": "intervention-1",
        "chantier_id": "CHANTIER-1",
        "lignes_consommees": [{"materiau_id": "MAT-1", "quantite": 1.0}],
    }

    # Neutraliser la garde stock pour atteindre la résolution de coût
    original_verifier = stock_module.verifier_disponibilite_consommation
    stock_module.verifier_disponibilite_consommation = lambda *a, **k: (True, None)
    try:
        confirmation, code_verdict = materiel.consommer_materiaux(
            wct_valide(), formulaire, registre
        )
    finally:
        stock_module.verifier_disponibilite_consommation = original_verifier

    assert confirmation is None
    assert code_verdict == "REJ-COUT-UNITAIRE-INTROUVABLE"
    assert registre._ajouter_lot_appele is False
