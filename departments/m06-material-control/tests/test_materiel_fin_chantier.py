"""PLAN T1.1-d point 1 — formulaire de fin de chantier enrichi
(materiel.soumettre_materiaux_utilises), NOUVELLE fonction distincte de
consommer_materiaux (m6_consommer_materiaux)."""

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

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


def wct_valide():
    return {
        "wct_id": "wct-1", "intervention_id": "intervention-1", "lead_id": "lead-1",
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


def formulaire_valide(lignes=None):
    return {
        "wct_id": "wct-1", "intervention_id": "intervention-1", "chantier_id": "CHANTIER-1",
        "lignes_materiaux": lignes if lignes is not None else [
            ligne_prevu(), ligne_non_prevu(), ligne_retour(), ligne_perte(),
            ligne_bris(), ligne_achat_terrain(),
        ],
    }


# --- Cas nominal --------------------------------------------------------------------


def test_soumettre_materiaux_utilises_accepte_les_six_types_de_ligne():
    confirmation, code = materiel.soumettre_materiaux_utilises(wct_valide(), formulaire_valide())

    assert code is None
    assert confirmation["intervention_id"] == "intervention-1"
    assert confirmation["chantier_id"] == "CHANTIER-1"
    types_confirmes = {ligne["type_ligne"] for ligne in confirmation["lignes_declarees"]}
    assert types_confirmes == {"prevu", "non_prevu", "retour", "perte", "bris", "achat_terrain"}


def test_ligne_prevu_porte_la_quantite_estimee_dans_la_confirmation():
    confirmation, code = materiel.soumettre_materiaux_utilises(
        wct_valide(), formulaire_valide([ligne_prevu(quantite=8.0, quantite_estimee=10.0)])
    )

    assert code is None
    ligne = confirmation["lignes_declarees"][0]
    assert ligne == {
        "type_ligne": "prevu", "materiau_id": "MAT-1", "quantite": 8.0,
        "unite": "boite", "quantite_estimee": 10.0,
    }


def test_ligne_non_prevu_ne_porte_pas_de_quantite_estimee():
    confirmation, code = materiel.soumettre_materiaux_utilises(
        wct_valide(), formulaire_valide([ligne_non_prevu()])
    )

    assert code is None
    assert "quantite_estimee" not in confirmation["lignes_declarees"][0]


def test_achat_terrain_avec_photo_seule_est_accepte():
    confirmation, code = materiel.soumettre_materiaux_utilises(
        wct_valide(), formulaire_valide([ligne_achat_terrain(photo=True, recu=False)])
    )

    assert code is None
    assert confirmation["lignes_declarees"][0]["photo_fournie"] is True
    assert confirmation["lignes_declarees"][0]["recu_fourni"] is False


def test_achat_terrain_avec_recu_seul_est_accepte():
    confirmation, code = materiel.soumettre_materiaux_utilises(
        wct_valide(), formulaire_valide([ligne_achat_terrain(photo=False, recu=True)])
    )

    assert code is None


def test_confirmation_ne_contient_aucune_cle_monetaire():
    confirmation, code = materiel.soumettre_materiaux_utilises(wct_valide(), formulaire_valide())

    assert code is None
    assert not collecter_cles_recursivement(confirmation).intersection(CLES_MONETAIRES_INTERDITES)


# --- Rejets fail-closed nommés --------------------------------------------------------


def test_rejette_achat_terrain_sans_photo_ni_recu_par_un_verdict_fail_closed_nomme():
    formulaire = formulaire_valide([ligne_achat_terrain(photo=False, recu=False)])

    confirmation, code = materiel.soumettre_materiaux_utilises(wct_valide(), formulaire)

    assert confirmation is None
    assert code == "REJ-ACHAT-TERRAIN-PREUVE-MANQUANTE"


def test_rejette_un_wct_sans_consommateur_m6():
    wct = wct_valide()
    wct["consommateurs_cibles"] = ["M5"]

    confirmation, code = materiel.soumettre_materiaux_utilises(wct, formulaire_valide())

    assert confirmation is None
    assert code == "REJ-WCT-CONSOMMATEUR-M6-ABSENT"


def test_rejette_un_formulaire_incoherent_avec_le_wct():
    formulaire = formulaire_valide()
    formulaire["wct_id"] = "wct-2"

    confirmation, code = materiel.soumettre_materiaux_utilises(wct_valide(), formulaire)

    assert confirmation is None
    assert code == "REJ-FORMULAIRE-MATERIAUX-WCT-INCOHERENT"


def test_rejette_une_cle_de_formulaire_manquante():
    formulaire = formulaire_valide()
    del formulaire["chantier_id"]

    confirmation, code = materiel.soumettre_materiaux_utilises(wct_valide(), formulaire)

    assert confirmation is None
    assert code == "REJ-FORMULAIRE-MATERIAUX-STRUCTURE-INVALIDE"


def test_rejette_une_liste_de_lignes_vide():
    formulaire = formulaire_valide([])

    confirmation, code = materiel.soumettre_materiaux_utilises(wct_valide(), formulaire)

    assert confirmation is None
    assert code == "REJ-FORMULAIRE-MATERIAUX-STRUCTURE-INVALIDE"


def test_rejette_un_type_de_ligne_hors_liste_et_jamais_vol():
    formulaire = formulaire_valide([{
        "type_ligne": "vol", "materiau_id": "MAT-1", "quantite": 1.0, "unite": "boite",
    }])

    confirmation, code = materiel.soumettre_materiaux_utilises(wct_valide(), formulaire)

    assert confirmation is None
    assert code == "REJ-LIGNE-MATERIAUX-TYPE-INVALIDE"


def test_rejette_une_ligne_prevu_sans_quantite_estimee():
    formulaire = formulaire_valide([{
        "type_ligne": "prevu", "materiau_id": "MAT-1", "quantite": 1.0, "unite": "boite",
    }])

    confirmation, code = materiel.soumettre_materiaux_utilises(wct_valide(), formulaire)

    assert confirmation is None
    assert code == "REJ-LIGNE-MATERIAUX-STRUCTURE-INVALIDE"


def test_rejette_une_ligne_non_prevu_avec_une_quantite_estimee_en_trop():
    formulaire = formulaire_valide([{
        "type_ligne": "non_prevu", "materiau_id": "MAT-1", "quantite": 1.0,
        "unite": "boite", "quantite_estimee": 5.0,
    }])

    confirmation, code = materiel.soumettre_materiaux_utilises(wct_valide(), formulaire)

    assert confirmation is None
    assert code == "REJ-LIGNE-MATERIAUX-STRUCTURE-INVALIDE"


def test_rejette_quantite_nulle_ou_negative():
    for quantite in (0, -1.0):
        formulaire = formulaire_valide([ligne_non_prevu(quantite=quantite)])
        confirmation, code = materiel.soumettre_materiaux_utilises(wct_valide(), formulaire)
        assert confirmation is None
        assert code == "REJ-LIGNE-MATERIAUX-QUANTITE-INVALIDE"


def test_rejette_quantite_nan_et_infinie():
    for quantite in (float("nan"), float("inf"), float("-inf")):
        formulaire = formulaire_valide([ligne_non_prevu(quantite=quantite)])
        confirmation, code = materiel.soumettre_materiaux_utilises(wct_valide(), formulaire)
        assert confirmation is None
        assert code == "REJ-LIGNE-MATERIAUX-QUANTITE-INVALIDE"


def test_rejette_une_unite_vide():
    formulaire = formulaire_valide([ligne_non_prevu(unite="")])

    confirmation, code = materiel.soumettre_materiaux_utilises(wct_valide(), formulaire)

    assert confirmation is None
    assert code == "REJ-LIGNE-MATERIAUX-UNITE-INVALIDE"


def test_rejette_une_cle_interdite_glissee_dans_une_ligne():
    formulaire = formulaire_valide([{**ligne_non_prevu(), "virement": "v-1"}])

    confirmation, code = materiel.soumettre_materiaux_utilises(wct_valide(), formulaire)

    assert confirmation is None
    assert code == "REJ-FRONTIERE-VIOLEE"


def test_consommer_materiaux_reste_inchange_apres_l_ajout_du_formulaire_enrichi():
    """m6_consommer_materiaux garde son contrat {materiau_id, quantite} exact : la
    nouvelle fonction ne le remplace pas (PLAN T1.1-d point 1)."""

    class RegistreFactice:
        def __init__(self, mouvements):
            self._mouvements = mouvements

        def lire(self):
            return self._mouvements

        def ajouter_lot(self, mouvements):
            self._mouvements.extend(mouvements)
            return mouvements, None

    registre = RegistreFactice([{
        "type_mouvement": "RECEPTION", "chantier_id": "C1", "materiau_id": "MAT-1",
        "quantite": 10.0, "cout_unitaire": 5.0,
    }])
    formulaire = {
        "wct_id": "wct-1", "intervention_id": "intervention-1", "chantier_id": "C1",
        "lignes_consommees": [{"materiau_id": "MAT-1", "quantite": 3.0}],
    }

    confirmation, code = materiel.consommer_materiaux(wct_valide(), formulaire, registre)

    assert code is None
    assert confirmation["stock_restant"] == [{"materiau_id": "MAT-1", "quantite": 7.0}]
