"""Tests de l'estimé-vs-réel de M3 (PLAN T1.2-d, en second ordre, estime_vs_reel.py). Registres EN
MÉMOIRE (des listes Python) dans tout ce fichier — le câblage sur le bus réel (`evenements.repartir`,
en ne routant que M3) est éprouvé séparément par `test_estime_vs_reel_repartiteur.py`."""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m3_estimation import devis_durable, estime_vs_reel, verdicts  # noqa: E402

_CODES_EXERCES_PAR_CE_FICHIER = {
    "REJ-ECART-DEVIS-ID-ABSENT",
    "REJ-ECART-ESTIMATION-ORIGINE-ABSENTE",
    "REJ-ECART-DUREE-ESTIMEE-INVALIDE",
    "REJ-ECART-FILTRE-ABSENT",
    "REJ-ECART-PERIODE-INCOMPLETE",
    "REJ-ECART-PERIODE-INVALIDE",
}


def _verdict_attendu(reponse, code):
    assert code in _CODES_EXERCES_PAR_CE_FICHIER, f"{code} absent de _CODES_EXERCES_PAR_CE_FICHIER"
    assert reponse[1] is not None, f"rejet {code} attendu, obtenu {reponse}"
    assert reponse[0] is None
    assert reponse[1]["code"] == code, reponse[1]
    return reponse[1]


def _charge_wct(**surcharges):
    charge = {
        "wct_id": "wct-001",
        "intervention_id": "int-001",
        "lead_id": "lead-001",
        "technicien_id": "tech-001",
        "horodatage_completion": "2026-09-28T14:00:00-04:00",
        "fix_gps_completion": {},
        "duree_reelle_minutes": 120,
        "ecart_signale": False,
        "revue_id": None,
        "hash_maillon": "deadbeef",
        "consommateurs_cibles": ["M3"],
        "devis_id": "M3-DEVIS-001",
        "statut": "completed_verified",
    }
    charge.update(surcharges)
    return charge


def _charge_variance(**surcharges):
    charge = {
        "evenement_id": "m6-variance-wct-001-evaluee",
        "wct_id": "wct-001",
        "intervention_id": "int-001",
        "chantier_id": "chantier-001",
        "statut_variance": "evaluee",
        "signal_critique": False,
        "seuil_pourcentage": 10.0,
        "horodatage_completion": "2026-09-28T14:00:00-04:00",
        "lignes": [
            {
                "materiau": "gouttiere_alu",
                "unite": "pi_lin",
                "quantite_prevue": "30",
                "quantite_reelle": "32",
                "ecart_pourcentage": "0.0667",
                "critique": False,
            }
        ],
    }
    charge.update(surcharges)
    return charge


def _ligne_devis(**surcharges):
    ligne = {
        "description": "Gouttière alu 5 po",
        "quantite": "30",
        "unite": "pi_lin",
        "cout_unitaire": "10.00",
        "reference_besoin_materiau": None,
    }
    ligne.update(surcharges)
    return ligne


def _creer_devis(registre_devis, devis_id="M3-DEVIS-001", **surcharges):
    args = {
        "devis_id": devis_id,
        "lead_id": "lead-001",
        "chantier_id": None,
        "lignes": [_ligne_devis()],
        "taux_marge": "0.20",
        "horodatage": "2026-09-01T09:00:00-04:00",
        "registre_cible": registre_devis,
    }
    args.update(surcharges)
    devis, verdict = devis_durable.creer_devis(**args)
    assert verdict is None, verdict
    return devis


def _maillon_estimation(devis_id="M3-DEVIS-001", hash_maillon="x", **surcharges):
    """Maillon plausible de registre.py (S008) : la forme réelle {rang, charge, ...} — voir
    devis_durable/registre.py pour les 6 clés requises de charge."""
    charge = {
        "devis_id": devis_id,
        "lead_id": "lead-001",
        "empreinte_marqueur_m2": "a" * 64,
        "niveau_confiance": 0.9,
        "bareme_version": "2026.1",
        "graine_monte_carlo": 314159,
    }
    charge.update(surcharges)
    return {"rang": 0, "charge": charge, "hash_precedent": "0" * 64, "hash_maillon": hash_maillon,
            "cout_reel": None}


# -- ecart_relatif : formule citée -------------------------------------------------------------
def test_ecart_relatif_formule_reel_moins_estime_sur_estime():
    ecart, verdict = estime_vs_reel.ecart_relatif(Decimal("100"), Decimal("120"))
    assert verdict is None
    assert ecart == Decimal("0.2")  # (120-100)/100 = 20 % de dépassement


def test_ecart_relatif_negatif_si_sous_estime():
    ecart, verdict = estime_vs_reel.ecart_relatif(Decimal("100"), Decimal("80"))
    assert verdict is None
    assert ecart == Decimal("-0.2")


def test_ecart_relatif_exact_si_reel_egal_estime():
    ecart, verdict = estime_vs_reel.ecart_relatif(Decimal("100"), Decimal("100"))
    assert verdict is None
    assert ecart == Decimal("0")


def test_ecart_relatif_estime_non_positif_rejete():
    _verdict_attendu(estime_vs_reel.ecart_relatif(Decimal("0"), Decimal("10")), "REJ-ECART-DUREE-ESTIMEE-INVALIDE")
    _verdict_attendu(estime_vs_reel.ecart_relatif(Decimal("-5"), Decimal("10")), "REJ-ECART-DUREE-ESTIMEE-INVALIDE")


def test_ecart_relatif_types_non_decimal_rejetes():
    _verdict_attendu(estime_vs_reel.ecart_relatif(100, Decimal("120")), "REJ-ECART-DUREE-ESTIMEE-INVALIDE")
    _verdict_attendu(estime_vs_reel.ecart_relatif(Decimal("100"), 120.0), "REJ-ECART-DUREE-ESTIMEE-INVALIDE")


# -- enregistrer_travaux_termines : lien devis / estimation d'origine ----------------------------
def test_wct_sans_devis_id_verdict_nomme_mais_enregistrement_ecrit_quand_meme():
    registre_cible, registre_devis, maillons_estimations = [], [], []
    resultat = estime_vs_reel.enregistrer_travaux_termines(
        _charge_wct(devis_id=None), registre_devis, maillons_estimations, registre_cible
    )
    assert resultat["wct_id"] == "wct-001"
    assert resultat["devis_id"] is None
    assert resultat["main_doeuvre"]["duree_reelle_minutes"] == Decimal("120")
    assert resultat["main_doeuvre"]["duree_estimee_minutes"] is None
    assert resultat["main_doeuvre"]["ecart_relatif"] is None
    assert resultat["main_doeuvre"]["verdict"]["code"] == "REJ-ECART-DEVIS-ID-ABSENT"
    assert resultat["materiaux"] is None
    assert len(registre_cible) == 1, "l'absence de devis_id n'empêche pas l'enregistrement du WCT"


def test_wct_avec_devis_id_mais_aucune_source_de_duree_estimee():
    """Cas RÉEL du dépôt aujourd'hui : ni le devis (T2.3-a/b) ni registre.py (S008, zéro
    appelant) ne portent duree_estimee_minutes — verdict nommé, jamais une durée inventée."""
    registre_cible, registre_devis, maillons_estimations = [], [], []
    _creer_devis(registre_devis)
    resultat = estime_vs_reel.enregistrer_travaux_termines(
        _charge_wct(), registre_devis, maillons_estimations, registre_cible
    )
    assert resultat["main_doeuvre"]["duree_estimee_minutes"] is None
    assert resultat["main_doeuvre"]["verdict"]["code"] == "REJ-ECART-ESTIMATION-ORIGINE-ABSENTE"


def test_wct_devis_id_sans_devis_ni_estimation_connus_de_m3():
    """devis_id présent mais ni le devis ni une estimation d'origine n'existent dans les
    registres fournis (ex. orchestrateur pas encore branché) : même verdict, pas de plantage."""
    resultat = estime_vs_reel.enregistrer_travaux_termines(_charge_wct(), [], [], [])
    assert resultat["main_doeuvre"]["verdict"]["code"] == "REJ-ECART-ESTIMATION-ORIGINE-ABSENTE"


def test_duree_legacy_directement_sur_devis_ne_devient_pas_mesure():
    registre_cible, registre_devis, maillons_estimations = [], [], []
    _creer_devis(registre_devis)
    # Convention posée par ce module (cf. docstring) : duree_estimee_minutes en texte décimal,
    # directement sur le devis — ici simulée en écrivant un second maillon "devis_cree" alternatif
    # via la registre nue (le contrat gelé actuel de devis_durable ne porte pas encore ce champ ;
    # ce test documente la convention, prête pour un futur écrivain).
    registre_devis.clear()
    registre_devis.append(
        {
            "type_entree": "devis_cree",
            "devis_id": "M3-DEVIS-001",
            "lead_id": "lead-001",
            "chantier_id": None,
            "lignes": [],
            "taux_marge": Decimal("0.20"),
            "cout_total": Decimal("0"),
            "prix_total": Decimal("0"),
            "statut": "brouillon",
            "horodatage": "2026-09-01T09:00:00-04:00",
            "duree_estimee_minutes": "100",
        }
    )
    resultat = estime_vs_reel.enregistrer_travaux_termines(
        _charge_wct(duree_reelle_minutes=120), registre_devis, maillons_estimations, registre_cible
    )
    main_doeuvre = resultat["main_doeuvre"]
    assert main_doeuvre["verdict"]["code"] == "REJ-ECART-ESTIMATION-ORIGINE-ABSENTE"
    assert main_doeuvre["duree_estimee_minutes"] is None
    assert main_doeuvre["ecart_relatif"] is None


def test_duree_estimee_liee_par_hash_exact_si_absente_du_devis():
    registre_cible, registre_devis, maillons_estimations = [], [], []
    source_hash = "a" * 64
    _creer_devis(registre_devis, estimation_source_hash=source_hash)  # source explicite, durée pas copiée au devis
    maillons_estimations.append(_maillon_estimation(
        hash_maillon=source_hash, duree_estimee_minutes="80",
        trace_calibration_temps={
            "version_schema": 2, "semantique_temps": "duree_ecoulee_intervention", "duree_estimee_minutes": "80",
        },
    ))
    resultat = estime_vs_reel.enregistrer_travaux_termines(
        _charge_wct(duree_reelle_minutes=100), registre_devis, maillons_estimations, registre_cible
    )
    main_doeuvre = resultat["main_doeuvre"]
    assert main_doeuvre["verdict"] is None
    assert main_doeuvre["duree_estimee_minutes"] == Decimal("80")
    assert main_doeuvre["ecart_relatif"] == Decimal("0.25")


def test_wct_cross_lead_ne_recoit_pas_la_duree_du_devis_et_le_rejeu_reste_idempotent():
    registre_cible, registre_devis = [], []
    source_hash = "a" * 64
    _creer_devis(registre_devis, lead_id="lead-A", estimation_source_hash=source_hash)
    maillons_estimations = [
        _maillon_estimation(
            lead_id="lead-A",
            hash_maillon=source_hash,
            duree_estimee_minutes="80",
            trace_calibration_temps={
                "version_schema": 2,
                "semantique_temps": "duree_ecoulee_intervention",
                "duree_estimee_minutes": "80",
            },
        )
    ]

    resultat = estime_vs_reel.enregistrer_travaux_termines(
        _charge_wct(lead_id="lead-B", duree_reelle_minutes=100),
        registre_devis,
        maillons_estimations,
        registre_cible,
    )
    main_doeuvre = resultat["main_doeuvre"]
    assert resultat["lead_id"] == "lead-B"  # le travail réel reste enregistré pour son lead déclaré
    assert main_doeuvre["duree_reelle_minutes"] == Decimal("100")
    assert main_doeuvre["duree_estimee_minutes"] is None
    assert main_doeuvre["ecart_relatif"] is None
    assert "lead du WCT" in main_doeuvre["verdict"]["detail"]
    assert "lead-A" in main_doeuvre["verdict"]["detail"]

    resultat_rejoue = estime_vs_reel.enregistrer_travaux_termines(
        _charge_wct(lead_id="lead-B", duree_reelle_minutes=100),
        registre_devis,
        maillons_estimations,
        registre_cible,
    )
    assert resultat_rejoue == resultat
    assert len(registre_cible) == 1


def test_wct_du_meme_lead_que_devis_utilise_la_source_exacte():
    registre_cible, registre_devis = [], []
    source_hash = "a" * 64
    _creer_devis(registre_devis, lead_id="lead-A", estimation_source_hash=source_hash)
    maillons_estimations = [
        _maillon_estimation(
            lead_id="lead-A",
            hash_maillon=source_hash,
            duree_estimee_minutes="80",
            trace_calibration_temps={
                "version_schema": 2,
                "semantique_temps": "duree_ecoulee_intervention",
                "duree_estimee_minutes": "80",
            },
        )
    ]

    resultat = estime_vs_reel.enregistrer_travaux_termines(
        _charge_wct(lead_id="lead-A", duree_reelle_minutes=100),
        registre_devis,
        maillons_estimations,
        registre_cible,
    )
    assert resultat["main_doeuvre"]["duree_estimee_minutes"] == Decimal("80")
    assert resultat["main_doeuvre"]["ecart_relatif"] == Decimal("0.25")
    assert resultat["main_doeuvre"]["verdict"] is None


def test_duree_nonqualifiee_sur_un_devis_historique_ne_devient_pas_mesure():
    registre_cible, registre_devis, maillons_estimations = [], [], []
    registre_devis.append(
        {
            "type_entree": "devis_cree", "devis_id": "M3-DEVIS-001", "lead_id": "lead-001",
            "chantier_id": None, "lignes": [], "taux_marge": Decimal("0.20"),
            "cout_total": Decimal("0"), "prix_total": Decimal("0"), "statut": "brouillon",
            "horodatage": "2026-09-01T09:00:00-04:00", "duree_estimee_minutes": "100",
        }
    )
    maillons_estimations.append(_maillon_estimation(duree_estimee_minutes="999"))
    resultat = estime_vs_reel.enregistrer_travaux_termines(
        _charge_wct(duree_reelle_minutes=120), registre_devis, maillons_estimations, registre_cible
    )
    assert resultat["main_doeuvre"]["duree_estimee_minutes"] is None


def test_duree_estimee_source_exacte_retenue_si_estimation_plus_recente_existe():
    registre_cible, registre_devis = [], []
    source_hash = "a" * 64
    _creer_devis(registre_devis, estimation_source_hash=source_hash)
    maillons_estimations = [
        _maillon_estimation(hash_maillon=source_hash, duree_estimee_minutes="50",
                            trace_calibration_temps={"version_schema": 2,
                                                     "semantique_temps": "duree_ecoulee_intervention",
                                                     "duree_estimee_minutes": "50"}),
        _maillon_estimation(hash_maillon="b" * 64, duree_estimee_minutes="90",
                            trace_calibration_temps={"version_schema": 2,
                                                     "semantique_temps": "duree_ecoulee_intervention",
                                                     "duree_estimee_minutes": "90"}),
    ]
    resultat = estime_vs_reel.enregistrer_travaux_termines(
        _charge_wct(duree_reelle_minutes=90), registre_devis, maillons_estimations, registre_cible
    )
    assert resultat["main_doeuvre"]["duree_estimee_minutes"] == Decimal("50")


@pytest.mark.parametrize("brute", ["pas un nombre", "0", "-10"])
def test_duree_estimee_invalide_rejetee(brute):
    registre_devis = []
    source_hash = "a" * 64
    _creer_devis(registre_devis, estimation_source_hash=source_hash)
    maillons_estimations = [_maillon_estimation(
        hash_maillon=source_hash, duree_estimee_minutes=brute,
        trace_calibration_temps={"version_schema": 2, "semantique_temps": "duree_ecoulee_intervention",
                                 "duree_estimee_minutes": brute},
    )]
    resultat = estime_vs_reel.enregistrer_travaux_termines(_charge_wct(), registre_devis, maillons_estimations, [])
    assert resultat["main_doeuvre"]["verdict"]["code"] == "REJ-ECART-DUREE-ESTIMEE-INVALIDE"


def test_wct_idempotent_par_wct_id_ne_grossit_pas_le_registre():
    registre_cible, registre_devis = [], []
    _creer_devis(registre_devis)
    premier = estime_vs_reel.enregistrer_travaux_termines(_charge_wct(), registre_devis, [], registre_cible)
    assert len(registre_cible) == 1
    second = estime_vs_reel.enregistrer_travaux_termines(_charge_wct(), registre_devis, [], registre_cible)
    assert len(registre_cible) == 1, "un rejeu identique ne doit écrire aucun second maillon"
    assert second == premier


def test_wct_id_distincts_coexistent():
    registre_cible, registre_devis = [], []
    _creer_devis(registre_devis, devis_id="M3-DEVIS-001")
    _creer_devis(registre_devis, devis_id="M3-DEVIS-002")
    estime_vs_reel.enregistrer_travaux_termines(
        _charge_wct(wct_id="wct-001", devis_id="M3-DEVIS-001"), registre_devis, [], registre_cible
    )
    estime_vs_reel.enregistrer_travaux_termines(
        _charge_wct(wct_id="wct-002", devis_id="M3-DEVIS-002"), registre_devis, [], registre_cible
    )
    assert len(registre_cible) == 2


# -- enregistrer_variance_chantier : matériaux, seulement au statut evaluee ----------------------
def test_variance_non_evaluee_ne_touche_jamais_le_registre():
    registre_cible = []
    for statut in ("prevu_absent", "declaration_absente", "seuil_absent", "unites_indeterminees"):
        resultat = estime_vs_reel.enregistrer_variance_chantier(
            _charge_variance(statut_variance=statut), registre_cible
        )
        assert resultat is None
    assert registre_cible == []


def test_variance_evaluee_ecrit_les_lignes_telles_quelles():
    registre_cible = []
    estime_vs_reel.enregistrer_travaux_termines(_charge_wct(devis_id=None), [], [], registre_cible)
    resultat = estime_vs_reel.enregistrer_variance_chantier(_charge_variance(), registre_cible)
    assert resultat["materiaux"]["lignes"] == _charge_variance()["lignes"]  # jamais recalculé
    assert resultat["materiaux"]["chantier_id"] == "chantier-001"
    assert resultat["materiaux"]["signal_critique"] is False
    assert resultat["materiaux"]["seuil_pourcentage"] == 10.0


def test_variance_evaluee_sur_wct_inconnu_leve_lookuperror():
    with pytest.raises(LookupError):
        estime_vs_reel.enregistrer_variance_chantier(_charge_variance(), [])


def test_variance_evaluee_deux_fois_est_idempotente_evaluee_est_terminal():
    registre_cible = []
    estime_vs_reel.enregistrer_travaux_termines(_charge_wct(devis_id=None), [], [], registre_cible)
    estime_vs_reel.enregistrer_variance_chantier(_charge_variance(), registre_cible)
    taille_apres_premiere = len(registre_cible)
    resultat = estime_vs_reel.enregistrer_variance_chantier(_charge_variance(), registre_cible)
    assert len(registre_cible) == taille_apres_premiere, "un second evaluee ne doit rien réécrire"
    assert resultat["materiaux"] is not None


def test_declaration_absente_puis_evaluee_une_seule_ligne_finale():
    """Scénario explicite : la déclaration matériaux arrive après coup, M6 réévalue et republie
    au statut evaluee — le registre M3 ne garde qu'UNE ligne finale, matériaux renseignés."""
    registre_cible = []
    estime_vs_reel.enregistrer_travaux_termines(_charge_wct(devis_id=None), [], [], registre_cible)
    ignore = estime_vs_reel.enregistrer_variance_chantier(
        _charge_variance(
            statut_variance="declaration_absente", signal_critique=None, seuil_pourcentage=10.0, lignes=None
        ),
        registre_cible,
    )
    assert ignore is None
    assert estime_vs_reel._etat(registre_cible, "wct-001")["materiaux"] is None

    resultat = estime_vs_reel.enregistrer_variance_chantier(_charge_variance(), registre_cible)
    assert resultat["materiaux"] is not None
    # Une seule ligne wct_recu + une seule ligne variance_recue = un seul état final pour ce wct_id.
    assert len(estime_vs_reel._etats_courants(registre_cible)) == 1


# -- lire_ecarts : filtre par devis_id ou par période --------------------------------------------
def test_lire_ecarts_sans_aucun_filtre_rejete():
    _verdict_attendu(estime_vs_reel.lire_ecarts([], None, None, None), "REJ-ECART-FILTRE-ABSENT")


def test_lire_ecarts_periode_incomplete_rejetee():
    _verdict_attendu(
        estime_vs_reel.lire_ecarts([], None, "2026-09-01T00:00:00-04:00", None), "REJ-ECART-PERIODE-INCOMPLETE"
    )


def test_lire_ecarts_jusqua_avant_depuis_rejete():
    _verdict_attendu(
        estime_vs_reel.lire_ecarts([], None, "2026-09-02T00:00:00-04:00", "2026-09-01T00:00:00-04:00"),
        "REJ-ECART-PERIODE-INVALIDE",
    )


def test_lire_ecarts_horodatage_sans_fuseau_rejete():
    registre_cible = []
    estime_vs_reel.enregistrer_travaux_termines(
        _charge_wct(devis_id=None, horodatage_completion="2026-09-28T14:00:00"), [], [], registre_cible
    )
    _verdict_attendu(
        estime_vs_reel.lire_ecarts(
            registre_cible, None, "2026-09-01T00:00:00-04:00", "2026-09-30T00:00:00-04:00"
        ),
        "REJ-ECART-PERIODE-INVALIDE",
    )


def test_lire_ecarts_filtre_par_devis_id():
    registre_cible, registre_devis = [], []
    _creer_devis(registre_devis, devis_id="M3-DEVIS-001")
    _creer_devis(registre_devis, devis_id="M3-DEVIS-002")
    estime_vs_reel.enregistrer_travaux_termines(
        _charge_wct(wct_id="wct-001", devis_id="M3-DEVIS-001"), registre_devis, [], registre_cible
    )
    estime_vs_reel.enregistrer_travaux_termines(
        _charge_wct(wct_id="wct-002", devis_id="M3-DEVIS-002"), registre_devis, [], registre_cible
    )

    resultats, verdict = estime_vs_reel.lire_ecarts(registre_cible, "M3-DEVIS-001", None, None)
    assert verdict is None
    assert [r["wct_id"] for r in resultats] == ["wct-001"]


def test_lire_ecarts_filtre_par_periode():
    registre_cible = []
    estime_vs_reel.enregistrer_travaux_termines(
        _charge_wct(wct_id="wct-tot", devis_id=None, horodatage_completion="2026-09-15T10:00:00-04:00"),
        [],
        [],
        registre_cible,
    )
    estime_vs_reel.enregistrer_travaux_termines(
        _charge_wct(wct_id="wct-tard", devis_id=None, horodatage_completion="2026-10-15T10:00:00-04:00"),
        [],
        [],
        registre_cible,
    )

    resultats, verdict = estime_vs_reel.lire_ecarts(
        registre_cible, None, "2026-09-01T00:00:00-04:00", "2026-10-01T00:00:00-04:00"
    )
    assert verdict is None
    assert [r["wct_id"] for r in resultats] == ["wct-tot"]


def test_lire_ecarts_borne_jusqua_exclue():
    registre_cible = []
    estime_vs_reel.enregistrer_travaux_termines(
        _charge_wct(devis_id=None, horodatage_completion="2026-10-01T00:00:00-04:00"), [], [], registre_cible
    )
    resultats, verdict = estime_vs_reel.lire_ecarts(
        registre_cible, None, "2026-09-01T00:00:00-04:00", "2026-10-01T00:00:00-04:00"
    )
    assert verdict is None
    assert resultats == []


def test_lire_ecarts_rend_main_doeuvre_et_materiaux_compacts():
    registre_cible, registre_devis = [], []
    _creer_devis(registre_devis)
    estime_vs_reel.enregistrer_travaux_termines(_charge_wct(), registre_devis, [], registre_cible)
    estime_vs_reel.enregistrer_variance_chantier(_charge_variance(), registre_cible)

    resultats, verdict = estime_vs_reel.lire_ecarts(registre_cible, "M3-DEVIS-001", None, None)
    assert verdict is None
    assert len(resultats) == 1
    entree = resultats[0]
    assert entree["main_doeuvre"]["duree_reelle_minutes"] == Decimal("120")
    assert entree["materiaux"]["lignes"][0]["materiau"] == "gouttiere_alu"


# -- catalogue fermé de verdicts ------------------------------------------------------------------
def test_tous_les_codes_exerces_par_ce_fichier_appartiennent_au_catalogue():
    assert set(verdicts.CODES_M3_LIST) >= _CODES_EXERCES_PAR_CE_FICHIER


def test_tous_les_codes_rej_ecart_du_catalogue_sont_exerces_par_ce_fichier():
    codes_ecart_du_catalogue = {code for code in verdicts.CODES_M3_LIST if code.startswith("REJ-ECART-")}
    assert codes_ecart_du_catalogue == _CODES_EXERCES_PAR_CE_FICHIER
