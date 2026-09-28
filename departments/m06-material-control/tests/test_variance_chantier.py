"""PLAN T1.1-d points 2 et 3 — variance_chantier.py, DISTINCT de variance.py.

variance.py = comptage physique vs stock théorique (audit d'inventaire, inchangé).
variance_chantier.py = besoins matériaux estimés (M3) vs réel déclaré au formulaire de
fin de chantier (M4) — verdict neutre, cause_possible jamais attribuée par le code,
SignalVarianceChantierCritique sur un seuil fourni par l'appelant.
"""

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m6_material_control import contrats, variance_chantier


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


def besoin(materiau_id="MAT-1", quantite_estimee=100.0, unite="boite"):
    return {"materiau_id": materiau_id, "quantite_estimee": quantite_estimee, "unite": unite}


def ligne(type_ligne, materiau_id="MAT-1", quantite=100.0, unite="boite", **extra):
    donnees = {"type_ligne": type_ligne, "materiau_id": materiau_id, "quantite": quantite, "unite": unite}
    if type_ligne == "prevu" and "quantite_estimee" not in extra:
        # Champ exigé par la structure du formulaire (validation.py) mais jamais lu par
        # comparer()/_comparer_materiau (qui compare au besoin fourni séparément) : une
        # valeur par défaut ici ne fausse aucune assertion sur le verdict calculé.
        donnees["quantite_estimee"] = quantite
    donnees.update(extra)
    return donnees


# --- comparer() : verdict neutre par matériau (point 2) -----------------------------


def test_aucun_ecart_quand_le_reel_egale_l_estime():
    verdicts = variance_chantier.comparer([besoin(quantite_estimee=10.0)], [ligne("prevu", quantite=10.0)])

    assert verdicts == [{
        "materiau_id": "MAT-1", "unite": "boite", "quantite_estimee": 10.0, "quantite_reelle": 10.0,
        "ecart": 0.0, "ecart_pourcentage": 0.0, "verdict_variance": "AUCUN_ECART",
        "cause_possible": None, "classification_requise": False,
    }]


def test_ecart_reel_superieur_quand_plus_utilise_que_prevu():
    verdicts = variance_chantier.comparer([besoin(quantite_estimee=100.0)], [ligne("prevu", quantite=140.0)])

    assert verdicts[0]["verdict_variance"] == "ECART_REEL_SUPERIEUR"
    assert verdicts[0]["ecart"] == 40.0
    assert verdicts[0]["ecart_pourcentage"] == 0.4
    assert verdicts[0]["classification_requise"] is True
    assert verdicts[0]["cause_possible"] is None


def test_ecart_reel_inferieur_quand_moins_utilise_que_prevu():
    verdicts = variance_chantier.comparer([besoin(quantite_estimee=100.0)], [ligne("prevu", quantite=60.0)])

    assert verdicts[0]["verdict_variance"] == "ECART_REEL_INFERIEUR"
    assert verdicts[0]["ecart"] == -40.0
    assert verdicts[0]["ecart_pourcentage"] == 0.4


def test_non_utilise_quand_rien_de_declare_pour_un_materiau_estime():
    verdicts = variance_chantier.comparer([besoin(quantite_estimee=10.0)], [])

    assert verdicts[0]["verdict_variance"] == "NON_UTILISE"
    assert verdicts[0]["quantite_reelle"] == 0.0
    assert verdicts[0]["ecart_pourcentage"] == 1.0
    assert verdicts[0]["classification_requise"] is True


def test_non_prevu_quand_declare_sans_aucun_besoin_estime():
    verdicts = variance_chantier.comparer([], [ligne("non_prevu", materiau_id="MAT-9", quantite=3.0)])

    assert verdicts[0]["materiau_id"] == "MAT-9"
    assert verdicts[0]["verdict_variance"] == "NON_PREVU"
    assert verdicts[0]["quantite_estimee"] == 0.0
    assert verdicts[0]["ecart_pourcentage"] is None
    assert verdicts[0]["classification_requise"] is True


def test_indetermine_quand_l_unite_declaree_ne_correspond_pas_a_l_unite_estimee():
    verdicts = variance_chantier.comparer(
        [besoin(quantite_estimee=10.0, unite="boite")],
        [ligne("prevu", quantite=10.0, unite="piece")],
    )

    assert verdicts[0]["verdict_variance"] == "INDETERMINE"
    assert verdicts[0]["ecart"] is None
    assert verdicts[0]["ecart_pourcentage"] is None
    assert verdicts[0]["classification_requise"] is True


def test_indetermine_quand_deux_lignes_declarees_du_meme_materiau_ont_des_unites_differentes():
    verdicts = variance_chantier.comparer(
        [besoin(quantite_estimee=10.0, unite="boite")],
        [ligne("prevu", quantite=5.0, unite="boite"), ligne("non_prevu", quantite=2.0, unite="piece")],
    )

    assert verdicts[0]["verdict_variance"] == "INDETERMINE"


def test_retour_diminue_la_quantite_reelle_nette():
    verdicts = variance_chantier.comparer(
        [besoin(quantite_estimee=10.0)],
        [ligne("prevu", quantite=10.0), ligne("retour", quantite=3.0)],
    )

    assert verdicts[0]["quantite_reelle"] == 7.0
    assert verdicts[0]["verdict_variance"] == "ECART_REEL_INFERIEUR"


def test_perte_et_bris_comptent_dans_la_quantite_reelle_sortie():
    verdicts = variance_chantier.comparer(
        [besoin(quantite_estimee=10.0)],
        [ligne("prevu", quantite=8.0), ligne("perte", quantite=1.0), ligne("bris", quantite=1.0)],
    )

    assert verdicts[0]["quantite_reelle"] == 10.0
    assert verdicts[0]["verdict_variance"] == "AUCUN_ECART"


def test_deux_materiaux_independants_sont_compares_separement_et_tries():
    verdicts = variance_chantier.comparer(
        [besoin(materiau_id="MAT-B", quantite_estimee=5.0), besoin(materiau_id="MAT-A", quantite_estimee=5.0)],
        [ligne("prevu", materiau_id="MAT-A", quantite=5.0), ligne("prevu", materiau_id="MAT-B", quantite=5.0)],
    )

    assert [v["materiau_id"] for v in verdicts] == ["MAT-A", "MAT-B"]


# --- Règles dures : cause_possible, pas de nom, jamais « vol » ----------------------


def test_cause_possible_est_toujours_none_quel_que_soit_le_verdict():
    verdicts = variance_chantier.comparer(
        [besoin(quantite_estimee=10.0)],
        [ligne("prevu", quantite=140.0)],
    )
    for v in verdicts:
        assert v["cause_possible"] is None


def test_les_six_causes_exactes_de_la_definition_produit_sont_disponibles_en_reference():
    causes_attendues = {
        "estimation_error", "field_change", "waste",
        "breakage", "data_entry_error", "unexplained_usage",
    }
    assert causes_attendues == contrats.CAUSES_VARIANCE_CHANTIER


def test_aucun_champ_ni_valeur_lie_a_un_employe_dans_le_verdict():
    verdicts = variance_chantier.comparer([besoin()], [ligne("prevu", quantite=100.0)])

    cles = collecter_cles_recursivement(verdicts)
    assert not any("employe" in cle or "technicien" in cle for cle in cles)


def test_le_mot_vol_n_apparait_jamais_dans_un_resultat_produit_par_le_module():
    """Règle dure (DEFINITION-PRODUIT.md §7 M6) : le SYSTÈME ne dit jamais « vol ». La
    définition produit elle-même emploie le mot pour documenter l'interdiction (comme le
    docstring de ce module) — seule compte l'absence du mot dans ce que le module
    PRODUIT (verdicts, signal), jamais dans les commentaires qui expliquent la règle."""
    resultat, code = variance_chantier.evaluer(
        "CHANTIER-1", [besoin(quantite_estimee=10.0)], [ligne("prevu", quantite=14.0)], 0.30,
    )
    assert code is None
    assert "vol" not in repr(resultat).lower()

    for verdict in contrats.VERDICT_VARIANCE_CHANTIER:
        assert "vol" not in verdict.lower()
    for cause in contrats.CAUSES_VARIANCE_CHANTIER:
        assert "vol" not in cause.lower()


# --- evaluer() : validation fail-closed + SignalVarianceChantierCritique (point 3) --


def test_evaluer_rejette_un_chantier_id_manquant():
    resultat, code = variance_chantier.evaluer("", [besoin()], [ligne("prevu", quantite=100.0)], 0.30)

    assert resultat is None
    assert code == "REJ-VARIANCE-CHANTIER-CHANTIER-MANQUANT"


def test_evaluer_rejette_un_besoin_duplique():
    resultat, code = variance_chantier.evaluer(
        "CHANTIER-1", [besoin(), besoin()], [ligne("prevu", quantite=100.0)], 0.30,
    )

    assert resultat is None
    assert code == "REJ-BESOIN-CHANTIER-DUPLIQUE"


def test_evaluer_rejette_un_seuil_negatif_ou_nul():
    for seuil in (0, -0.1):
        resultat, code = variance_chantier.evaluer(
            "CHANTIER-1", [besoin()], [ligne("prevu", quantite=100.0)], seuil,
        )
        assert resultat is None
        assert code == "REJ-SEUIL-VARIANCE-CHANTIER-INVALIDE"


def test_evaluer_rejette_un_seuil_non_numerique():
    resultat, code = variance_chantier.evaluer(
        "CHANTIER-1", [besoin()], [ligne("prevu", quantite=100.0)], "0.30",
    )

    assert resultat is None
    assert code == "REJ-SEUIL-VARIANCE-CHANTIER-INVALIDE"


def test_quarante_pourcent_d_ecart_declenche_le_signal_sur_seuil_trente_pourcent():
    resultat, code = variance_chantier.evaluer(
        "CHANTIER-1", [besoin(quantite_estimee=100.0)], [ligne("prevu", quantite=140.0)], 0.30,
    )

    assert code is None
    signal = resultat["signal_variance_critique"]
    assert signal is not None
    assert signal["chantier_id"] == "CHANTIER-1"
    assert signal["seuil_pourcentage"] == 0.30
    assert signal["ecart_maximal_pourcentage"] == 0.4
    assert signal["materiaux_en_ecart_critique"] == ["MAT-1"]


def test_cinq_pourcent_d_ecart_ne_declenche_aucun_signal_sur_seuil_trente_pourcent():
    resultat, code = variance_chantier.evaluer(
        "CHANTIER-1", [besoin(quantite_estimee=100.0)], [ligne("prevu", quantite=105.0)], 0.30,
    )

    assert code is None
    assert resultat["signal_variance_critique"] is None
    # Le verdict par matériau reste disponible même sans signal (revue de routine).
    assert resultat["verdicts_materiaux"][0]["verdict_variance"] == "ECART_REEL_SUPERIEUR"


def test_ecart_exactement_au_seuil_declenche_le_signal():
    resultat, code = variance_chantier.evaluer(
        "CHANTIER-1", [besoin(quantite_estimee=100.0)], [ligne("prevu", quantite=130.0)], 0.30,
    )

    assert code is None
    assert resultat["signal_variance_critique"] is not None


def test_un_materiau_non_prevu_ne_declenche_jamais_automatiquement_le_signal():
    """Le seuil décide seul (jamais codé en dur) : un ratio non défini (NON_PREVU,
    estimee=0) ne peut pas être comparé à un seuil, donc il ne déclenche jamais le
    signal par lui-même — il reste néanmoins visible dans verdicts_materiaux."""
    resultat, code = variance_chantier.evaluer(
        "CHANTIER-1", [], [ligne("non_prevu", materiau_id="MAT-9", quantite=1000.0)], 0.30,
    )

    assert code is None
    assert resultat["signal_variance_critique"] is None
    assert resultat["verdicts_materiaux"][0]["verdict_variance"] == "NON_PREVU"
    assert resultat["verdicts_materiaux"][0]["classification_requise"] is True


def test_seuil_jamais_code_en_dur_le_meme_ecart_change_de_verdict_selon_le_seuil_fourni():
    besoins = [besoin(quantite_estimee=100.0)]
    lignes = [ligne("prevu", quantite=140.0)]

    resultat_seuil_bas, _ = variance_chantier.evaluer("CHANTIER-1", besoins, lignes, 0.10)
    resultat_seuil_haut, _ = variance_chantier.evaluer("CHANTIER-1", besoins, lignes, 0.90)

    assert resultat_seuil_bas["signal_variance_critique"] is not None
    assert resultat_seuil_haut["signal_variance_critique"] is None


def test_resultat_de_evaluer_ne_contient_aucune_cle_monetaire():
    resultat, code = variance_chantier.evaluer(
        "CHANTIER-1", [besoin(quantite_estimee=100.0)], [ligne("prevu", quantite=140.0)], 0.30,
    )

    assert code is None
    assert not collecter_cles_recursivement(resultat).intersection(CLES_MONETAIRES_INTERDITES)
