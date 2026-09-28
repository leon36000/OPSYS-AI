from m6_material_control import materiel

CLES_MONETAIRES_INTERDITES = {
    "cout_unitaire",
    "cout",
    "prix",
    "montant",
    "devise",
    "unite_monetaire",
    "montant_total_estime",
}


class RegistreFactice:
    def __init__(self, mouvements):
        self._mouvements = mouvements

    def lire(self):
        return self._mouvements

    def ajouter_lot(self, mouvements):
        self._mouvements.extend(mouvements)
        return mouvements, None


def wct_valide():
    return {
        "wct_id": "wct-1", "intervention_id": "intervention-1", "lead_id": "lead-1",
        "technicien_id": "tech-1", "horodatage_completion": "2025-01-01T00:00:00Z",
        "fix_gps_completion": {"latitude": 1.0, "longitude": 2.0},
        "duree_reelle_minutes": 30, "ecart_signale": False, "revue_id": None,
        "hash_maillon": "a" * 64, "consommateurs_cibles": ["M6"], "devis_id": None,
    }


def formulaire_valide():
    return {
        "wct_id": "wct-1", "intervention_id": "intervention-1", "chantier_id": "CHANTIER-1",
        "lignes_consommees": [{"materiau_id": "MAT-1", "quantite": 3.0}],
    }


def registre_avec_reception_prealable():
    return RegistreFactice(
        [
            {
                "type_mouvement": "RECEPTION",
                "chantier_id": "CHANTIER-1",
                "materiau_id": "MAT-1",
                "quantite": 10.0,
                # Fix NEW-PROD-006 : une RECEPTION utilisée comme base de coût
                # pour une consommation ultérieure doit porter un cout_unitaire tracé.
                "cout_unitaire": 12.5,
            }
        ]
    )


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


def test_consommer_materiaux_retourne_confirmation_et_stock_restant_projete():
    confirmation, code_verdict = materiel.consommer_materiaux(
        wct_valide(),
        formulaire_valide(),
        registre_avec_reception_prealable(),
    )

    assert code_verdict is None
    assert confirmation["materiaux_confirmes"] == [
        {"materiau_id": "MAT-1", "quantite_declaree": 3.0}
    ]
    assert confirmation["stock_restant"] == [
        {"materiau_id": "MAT-1", "quantite": 7.0}
    ]


def test_consommer_materiaux_ne_retourne_aucune_cle_monetaire():
    confirmation, code_verdict = materiel.consommer_materiaux(
        wct_valide(),
        formulaire_valide(),
        registre_avec_reception_prealable(),
    )

    assert code_verdict is None
    assert confirmation is not None
    assert not collecter_cles_recursivement(confirmation).intersection(
        CLES_MONETAIRES_INTERDITES
    )


def test_consommer_materiaux_rejette_un_wct_sans_consommateur_m6():
    wct = wct_valide()
    wct["consommateurs_cibles"] = ["M5"]

    confirmation, code_verdict = materiel.consommer_materiaux(
        wct,
        formulaire_valide(),
        registre_avec_reception_prealable(),
    )

    assert confirmation is None
    assert code_verdict == "REJ-WCT-CONSOMMATEUR-M6-ABSENT"


def test_consommer_materiaux_rejette_un_formulaire_incoherent_avec_le_wct():
    formulaire = formulaire_valide()
    formulaire["wct_id"] = "wct-2"

    confirmation, code_verdict = materiel.consommer_materiaux(
        wct_valide(),
        formulaire,
        registre_avec_reception_prealable(),
    )

    assert confirmation is None
    assert code_verdict == "REJ-FORMULAIRE-WCT-INCOHERENT"


def test_consommer_materiaux_rejette_quantite_negative():
    formulaire = formulaire_valide()
    formulaire["lignes_consommees"] = [{"materiau_id": "MAT-1", "quantite": -1}]

    confirmation, code_verdict = materiel.consommer_materiaux(
        wct_valide(),
        formulaire,
        registre_avec_reception_prealable(),
    )

    assert confirmation is None
    assert code_verdict == "REJ-FORMULAIRE-LIGNE-INVALIDE"


def test_consommer_materiaux_rejette_quantite_nulle():
    formulaire = formulaire_valide()
    formulaire["lignes_consommees"] = [{"materiau_id": "MAT-1", "quantite": 0}]

    confirmation, code_verdict = materiel.consommer_materiaux(
        wct_valide(),
        formulaire,
        registre_avec_reception_prealable(),
    )

    assert confirmation is None
    assert code_verdict == "REJ-FORMULAIRE-LIGNE-INVALIDE"


def test_consommer_materiaux_rejette_quantite_nan():
    formulaire = formulaire_valide()
    formulaire["lignes_consommees"] = [{"materiau_id": "MAT-1", "quantite": float("nan")}]

    confirmation, code_verdict = materiel.consommer_materiaux(
        wct_valide(),
        formulaire,
        registre_avec_reception_prealable(),
    )

    assert confirmation is None
    assert code_verdict == "REJ-FORMULAIRE-LIGNE-INVALIDE"


def test_consommer_materiaux_rejette_quantite_infinie():
    formulaire = formulaire_valide()
    formulaire["lignes_consommees"] = [{"materiau_id": "MAT-1", "quantite": float("inf")}]

    confirmation, code_verdict = materiel.consommer_materiaux(
        wct_valide(),
        formulaire,
        registre_avec_reception_prealable(),
    )

    assert confirmation is None
    assert code_verdict == "REJ-FORMULAIRE-LIGNE-INVALIDE"

    formulaire = formulaire_valide()
    formulaire["lignes_consommees"] = [{"materiau_id": "MAT-1", "quantite": float("-inf")}]

    confirmation, code_verdict = materiel.consommer_materiaux(
        wct_valide(),
        formulaire,
        registre_avec_reception_prealable(),
    )

    assert confirmation is None
    assert code_verdict == "REJ-FORMULAIRE-LIGNE-INVALIDE"
