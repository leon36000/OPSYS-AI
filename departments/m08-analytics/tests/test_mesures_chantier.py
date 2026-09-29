"""Mesures d'un chantier terminé (PLAN T1.5-d) : module pur `mesures_chantier`, sans base ni bus.

Chaque test porte sur un fait précis : métriques gouvernées (registre, devise), calcul par le code,
« non calculable, manque X » à la place d'une valeur inventée, seuils (absent = pas d'alerte et un
signal « seuil à configurer »), charges d'alerte conformes au catalogue, performance d'équipe sans
classement. Identifiants et montants fictifs.
"""

from __future__ import annotations

import json

import pytest
from m8_analytics import dictionnaire, encodage
from m8_analytics import mesures_chantier as mc

from opsys.evenements import schemas as catalogue

_DEFINITIONS = mc.charger_definitions()
_HORODATAGE = "2026-09-28T14:00:00-04:00"


def _wct(**surcharges):
    base = {
        "type_entree": "wct", "wct_id": "wct-fictif-1", "intervention_id": "int-fictif-1",
        "devis_id": "devis-fictif-1", "technicien_id": "tech-fictif-a", "horodatage_completion": _HORODATAGE,
        "duree_reelle_minutes": 120, "statut": "completed_pending_review",
    }
    base.update(surcharges)
    return base


def _devis(**surcharges):
    base = {
        "type_entree": "devis", "devis_id": "devis-fictif-1", "prix_total": "600.00", "cout_total": "480.00",
        "duree_estimee_minutes": "100", "horodatage_acceptation": "2026-09-20T09:00:00-04:00",
    }
    base.update(surcharges)
    return base


def _variance(**surcharges):
    base = {
        "type_entree": "variance", "wct_id": "wct-fictif-1", "statut_variance": "evaluee",
        "signal_critique": True, "seuil_pourcentage": 0.3,
        "lignes": [
            {"materiau": "gouttiere-fictif", "unite": "pi", "quantite_prevue": "40", "quantite_reelle": "56",
             "ecart_pourcentage": "0.4", "critique": True},
            {"materiau": "crochet-fictif", "unite": "u", "quantite_prevue": "20", "quantite_reelle": "22",
             "ecart_pourcentage": "0.1", "critique": False},
        ],
    }
    base.update(surcharges)
    return base


def _rentabilite(**surcharges):
    base = {"type_entree": "rentabilite", "wct_id": "wct-fictif-1", "marge_reelle_cad": "90.00"}
    base.update(surcharges)
    return base


def _mesures(*entrees, wct_id="wct-fictif-1"):
    faits = mc.assembler_faits(wct_id, list(entrees))
    assert faits is not None
    return {m["metric_id"]: m for m in mc.mesurer_chantier(faits, _DEFINITIONS)}


# ---------------------------------------------------------------------------
# Registre gouverné : nom, formule, source, unité ; devise CAD
# ---------------------------------------------------------------------------
def test_le_registre_definit_les_huit_metriques_de_mesure_de_chantier():
    assert list(_DEFINITIONS) == [
        "m8_ecart_duree_minutes", "m8_ecart_duree_pct", "m8_marge_prevue_cad", "m8_marge_reelle_cad",
        "m8_ecart_marge_cad", "m8_ecart_marge_pct", "m8_ecart_materiaux_max_pct",
        "m8_ecart_duree_technicien_pct",
    ]
    for metric_id, definition in _DEFINITIONS.items():
        assert definition["id"] == metric_id
        for champ in ("nom", "definition", "unite", "source_donnees"):  # nom, formule, unité, source
            assert definition[champ].strip()


def test_toute_unite_monetaire_du_registre_est_cad_et_aucune_devise_etrangere():
    for definition in _DEFINITIONS.values():
        assert dictionnaire.devise_non_autorisee(definition["unite"]) is None
    assert {i: d["unite"] for i, d in _DEFINITIONS.items() if d["unite"] == "CAD"} == {
        "m8_marge_prevue_cad": "CAD", "m8_marge_reelle_cad": "CAD", "m8_ecart_marge_cad": "CAD",
    }


def test_un_registre_avec_une_devise_etrangere_est_refuse_pas_charge_a_moitie(tmp_path):
    fichier = tmp_path / "m8-metrics.v1.yaml"
    fichier.write_text(
        "schema_version: 1\nmodule: m08-analytics\nmetrics:\n"
        "  - {id: m8_x, nom: X, definition: d, unite: USD, source_donnees: s, frequence: f, consommateur: c}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="REJ-DEVISE-NON-AUTORISEE"):
        mc.charger_definitions(fichier)


def test_chaque_metrique_du_registre_a_un_calcul_sauf_la_performance_d_equipe():
    """Aucun trou entre le registre et le code : une métrique définie sans calcul serait rendue
    « non calculable » à jamais, sans que personne le voie."""
    assert set(_DEFINITIONS) - {mc.METRIQUE_EQUIPE} == set(mc._CALCULS)


def test_une_metrique_du_registre_sans_calcul_est_non_calculable_nommement():
    definitions = {**_DEFINITIONS, "m8_sans_calcul": {**_DEFINITIONS["m8_marge_prevue_cad"], "id": "m8_sans_calcul"}}
    faits = mc.assembler_faits("wct-fictif-1", [_wct()])
    mesure = next(m for m in mc.mesurer_chantier(faits, definitions) if m["metric_id"] == "m8_sans_calcul")
    assert mesure["statut"] == mc.STATUT_NON_CALCULABLE and mesure["valeur"] is None
    assert mesure["manque"][0]["champ"] == "calcul"


# ---------------------------------------------------------------------------
# Assemblage des faits
# ---------------------------------------------------------------------------
def test_un_chantier_inconnu_n_a_pas_de_faits():
    assert mc.assembler_faits("wct-inconnu", [_wct(), _devis()]) is None


def test_le_devis_est_joint_par_le_devis_id_du_chantier_pas_par_un_autre():
    autre_devis = _devis(devis_id="devis-fictif-2", prix_total="999.00")
    faits = mc.assembler_faits("wct-fictif-1", [_wct(), autre_devis, _devis()])
    assert faits["devis"]["devis_id"] == "devis-fictif-1"
    assert faits["devis"]["prix_total"] == "600.00"


def test_une_variance_evaluee_l_emporte_sur_les_statuts_precedents_et_suivants():
    attente = _variance(statut_variance="declaration_absente", signal_critique=None, lignes=None)
    faits = mc.assembler_faits("wct-fictif-1", [_wct(), _variance(), attente])
    assert faits["variance"]["statut_variance"] == "evaluee"
    seule = mc.assembler_faits("wct-fictif-1", [_wct(), attente])
    assert seule["variance"]["statut_variance"] == "declaration_absente"


def test_wcts_du_devis_liste_les_chantiers_deja_termines_de_ce_devis():
    entrees = [_wct(), _wct(wct_id="wct-fictif-2"), _wct(wct_id="wct-fictif-3", devis_id="devis-fictif-9"), _devis()]
    assert mc.wcts_du_devis(entrees, "devis-fictif-1") == ["wct-fictif-1", "wct-fictif-2"]
    assert mc.wcts_du_devis(entrees, "devis-absent") == []


def test_fait_devis_ne_porte_la_duree_estimee_que_si_m3_la_fournit():
    charge = {
        "devis_id": "d", "prix_total": "1.00", "cout_total": "0.50", "horodatage_acceptation": "2026-09-20T09:00:00Z",
    }
    assert "duree_estimee_minutes" not in mc.fait_devis(charge)
    assert mc.fait_devis({**charge, "duree_estimee_minutes": "90"})["duree_estimee_minutes"] == "90"


# ---------------------------------------------------------------------------
# Calcul par le code, entrées complètes
# ---------------------------------------------------------------------------
def test_toutes_les_entrees_presentes_chaque_mesure_est_calculee_par_le_code():
    m = _mesures(_wct(), _devis(), _variance(), _rentabilite())

    assert m["m8_ecart_duree_minutes"]["valeur"] == "20.00"  # 120 - 100
    assert m["m8_ecart_duree_pct"]["valeur"] == "20.00"  # 20 / 100 x 100
    assert m["m8_marge_prevue_cad"]["valeur"] == "120.00"  # 600 - 480
    assert m["m8_marge_reelle_cad"]["valeur"] == "90.00"  # reprise de M5 telle quelle
    assert m["m8_ecart_marge_cad"]["valeur"] == "-30.00"  # 90 - 120
    assert m["m8_ecart_marge_pct"]["valeur"] == "-25.00"  # -30 / 120 x 100
    assert m["m8_ecart_materiaux_max_pct"]["valeur"] == "40.00"  # 0.4 de M6 x 100
    assert {x["statut"] for x in m.values()} == {mc.STATUT_CALCULEE}
    assert all(x["manque"] == [] and x["detail"] is None for x in m.values())


def test_chaque_mesure_porte_nom_unite_et_la_version_de_sa_definition_gouvernee():
    m = _mesures(_wct(), _devis())["m8_marge_prevue_cad"]
    definition = _DEFINITIONS["m8_marge_prevue_cad"]
    assert m["nom"] == definition["nom"] and m["unite"] == "CAD"
    assert m["version_definition"] == encodage.empreinte(definition)


def test_la_mesure_de_materiaux_cite_le_materiau_et_le_verdict_de_m6_sans_le_recalculer():
    entrees = _mesures(_wct(), _variance())["m8_ecart_materiaux_max_pct"]["entrees"]
    assert entrees == {
        "materiau": "gouttiere-fictif", "quantite_prevue": "40", "quantite_reelle": "56",
        "signal_critique_m6": True,
    }


def test_les_entrees_lues_sont_rendues_en_texte_decimal():
    entrees = _mesures(_wct(), _devis())["m8_ecart_duree_minutes"]["entrees"]
    assert entrees == {"duree_reelle_minutes": "120.00", "duree_estimee_minutes": "100.00"}


def test_arrondi_au_centieme_moitie_vers_le_haut_et_jamais_moins_zero():
    assert _mesures(_wct(), _devis(prix_total="0.125", cout_total="0"))["m8_marge_prevue_cad"]["valeur"] == "0.13"
    assert _mesures(_wct(), _devis(prix_total="100.001", cout_total="100.003"))["m8_marge_prevue_cad"][
        "valeur"] == "0.00"


def test_un_depassement_negatif_est_signe_sous_l_estimation():
    m = _mesures(_wct(duree_reelle_minutes=80), _devis())
    assert m["m8_ecart_duree_minutes"]["valeur"] == "-20.00"
    assert m["m8_ecart_duree_pct"]["valeur"] == "-20.00"


# ---------------------------------------------------------------------------
# Donnée absente : « non calculable, manque X », jamais une valeur inventée
# ---------------------------------------------------------------------------
def test_sans_devis_temps_prevu_et_marge_prevue_sont_non_calculables_et_disent_ce_qui_manque():
    m = _mesures(_wct())
    duree = m["m8_ecart_duree_pct"]
    assert duree["statut"] == mc.STATUT_NON_CALCULABLE
    assert duree["valeur"] is None  # jamais un zéro
    assert duree["manque"] == [{
        "champ": "duree_estimee_minutes", "source": "M3 (m3.devis_accepte)",
        "raison": "aucun devis accepté reçu pour devis-fictif-1",
    }]
    assert duree["detail"].startswith("non calculable, manque duree_estimee_minutes — M3 (m3.devis_accepte)")
    assert {c["champ"] for c in m["m8_marge_prevue_cad"]["manque"]} == {"prix_total", "cout_total"}


def test_un_chantier_sans_devis_id_dit_qu_il_n_est_lie_a_aucun_devis():
    m = _mesures(_wct(devis_id=None), _devis())
    raison = m["m8_ecart_duree_minutes"]["manque"][0]["raison"]
    assert "aucun devis" in raison and "devis_id absent" in raison


def test_devis_sans_duree_estimee_le_temps_prevu_manque_mais_la_marge_prevue_est_calculee():
    devis = _devis()
    del devis["duree_estimee_minutes"]
    m = _mesures(_wct(), devis)
    assert m["m8_ecart_duree_minutes"]["statut"] == mc.STATUT_NON_CALCULABLE
    assert m["m8_ecart_duree_minutes"]["manque"][0]["champ"] == "duree_estimee_minutes"
    assert m["m8_ecart_duree_minutes"]["manque"][0]["raison"] == "absent du fait reçu"
    assert m["m8_marge_prevue_cad"]["valeur"] == "120.00"


def test_une_duree_estimee_nulle_donne_l_ecart_en_minutes_mais_pas_le_pourcentage():
    m = _mesures(_wct(), _devis(duree_estimee_minutes="0"))
    assert m["m8_ecart_duree_minutes"]["valeur"] == "120.00"
    assert m["m8_ecart_duree_pct"]["statut"] == mc.STATUT_NON_CALCULABLE
    assert m["m8_ecart_duree_pct"]["manque"][0]["raison"] == "doit être strictement positive"


def test_une_valeur_illisible_est_un_manque_nomme_pas_une_valeur_devinee():
    m = _mesures(_wct(), _devis(duree_estimee_minutes="beaucoup"))
    manque = m["m8_ecart_duree_minutes"]["manque"][0]
    assert manque["champ"] == "duree_estimee_minutes" and "illisible" in manque["raison"]
    assert m["m8_ecart_duree_minutes"]["valeur"] is None
    for illisible in ("NaN", "Infinity", True):
        assert _mesures(_wct(), _devis(duree_estimee_minutes=illisible))["m8_ecart_duree_minutes"][
            "statut"] == mc.STATUT_NON_CALCULABLE


def test_sans_marge_reelle_de_m5_la_marge_reelle_et_ses_ecarts_sont_non_calculables_manque_m5():
    m = _mesures(_wct(), _devis())
    for metric_id in ("m8_marge_reelle_cad", "m8_ecart_marge_cad", "m8_ecart_marge_pct"):
        assert m[metric_id]["statut"] == mc.STATUT_NON_CALCULABLE
        assert m[metric_id]["valeur"] is None
        assert [c["champ"] for c in m[metric_id]["manque"]] == ["marge_reelle_cad"]
        assert m[metric_id]["manque"][0]["source"] == "M5 (rentabilité du chantier)"
    assert m["m8_marge_prevue_cad"]["statut"] == mc.STATUT_CALCULEE  # le prévu n'attend pas M5


def test_une_marge_prevue_nulle_rend_l_ecart_relatif_indefini_pas_une_division_par_zero():
    m = _mesures(_wct(), _devis(prix_total="480.00", cout_total="480.00"), _rentabilite())
    assert m["m8_ecart_marge_cad"]["valeur"] == "90.00"
    assert m["m8_ecart_marge_pct"]["statut"] == mc.STATUT_NON_CALCULABLE
    assert "indéfini" in m["m8_ecart_marge_pct"]["manque"][0]["raison"]


def test_sans_variance_de_m6_ou_non_evaluee_l_ecart_de_materiaux_est_non_calculable():
    absent = _mesures(_wct())["m8_ecart_materiaux_max_pct"]
    assert absent["statut"] == mc.STATUT_NON_CALCULABLE
    assert absent["manque"][0]["champ"] == "variance_chantier" and "M6" in absent["manque"][0]["source"]

    en_attente = _variance(statut_variance="declaration_absente", signal_critique=None, lignes=None)
    non_evaluee = _mesures(_wct(), en_attente)["m8_ecart_materiaux_max_pct"]
    assert non_evaluee["statut"] == mc.STATUT_NON_CALCULABLE
    assert "declaration_absente" in non_evaluee["manque"][0]["raison"]


def test_aucun_materiau_avec_un_ecart_defini_rend_la_mesure_non_calculable():
    lignes = [{"materiau": "m", "unite": "u", "quantite_prevue": "0", "quantite_reelle": "3",
               "ecart_pourcentage": None, "critique": False}]
    mesure = _mesures(_wct(), _variance(lignes=lignes))["m8_ecart_materiaux_max_pct"]
    assert mesure["statut"] == mc.STATUT_NON_CALCULABLE
    assert mesure["manque"][0]["raison"] == "aucun matériau avec un écart défini"


# ---------------------------------------------------------------------------
# Seuils : absent = pas d'alerte et un signal « seuil à configurer »
# ---------------------------------------------------------------------------
def _evaluations(seuils, *entrees):
    faits = mc.assembler_faits("wct-fictif-1", list(entrees))
    mesures = mc.mesurer_chantier(faits, _DEFINITIONS)
    return mesures, {e["metric_id"]: e for e in mc.evaluer_seuils(mesures, seuils)}


def test_sans_aucun_seuil_chaque_mesure_surveillee_calculee_dit_seuil_a_configurer():
    _, evaluations = _evaluations({}, _wct(), _devis(), _variance(), _rentabilite())
    assert set(evaluations) == {"m8_ecart_duree_pct", "m8_ecart_marge_pct", "m8_ecart_materiaux_max_pct"}
    assert {e["statut"] for e in evaluations.values()} == {mc.SEUIL_A_CONFIGURER}
    assert all(e["seuil"] is None and e["sens"] is None for e in evaluations.values())


def test_une_mesure_non_calculable_n_est_pas_evaluee_et_une_mesure_non_surveillee_non_plus():
    _, evaluations = _evaluations({}, _wct(), _devis())
    assert set(evaluations) == {"m8_ecart_duree_pct"}  # ni la marge (M5 absent), ni les matériaux (M6 absent)
    # m8_marge_prevue_cad est calculée mais n'est pas une mesure surveillée par seuil.


def test_seuil_au_dessus_est_franchi_quand_la_valeur_atteint_ou_depasse():
    seuils = {"m8_ecart_duree_pct": {"sens": "au_dessus", "valeur": 20}}
    _, egal = _evaluations(seuils, _wct(), _devis())  # 20.00 %
    assert egal["m8_ecart_duree_pct"]["statut"] == mc.SEUIL_FRANCHI
    assert (egal["m8_ecart_duree_pct"]["sens"], egal["m8_ecart_duree_pct"]["seuil"]) == ("au_dessus", "20.00")
    _, dessous = _evaluations({"m8_ecart_duree_pct": {"sens": "au_dessus", "valeur": 20.01}}, _wct(), _devis())
    assert dessous["m8_ecart_duree_pct"]["statut"] == mc.SEUIL_NON_FRANCHI


def test_seuil_au_dessous_est_franchi_quand_la_valeur_atteint_ou_passe_sous():
    seuils = {"m8_ecart_marge_pct": {"sens": "au_dessous", "valeur": -25}}
    _, egal = _evaluations(seuils, _wct(), _devis(), _rentabilite())  # -25.00 %
    assert egal["m8_ecart_marge_pct"]["statut"] == mc.SEUIL_FRANCHI
    _, plus_bas = _evaluations({"m8_ecart_marge_pct": {"sens": "au_dessous", "valeur": -30}}, _wct(), _devis(),
                               _rentabilite())
    assert plus_bas["m8_ecart_marge_pct"]["statut"] == mc.SEUIL_NON_FRANCHI


@pytest.mark.parametrize("seuil_invalide", [
    {"sens": "dessus", "valeur": 20},          # sens inconnu
    {"sens": "au_dessus"},                       # valeur absente
    {"valeur": 20},                              # sens absent
    {"sens": "au_dessus", "valeur": "20"},       # texte, pas un nombre
    {"sens": "au_dessus", "valeur": True},       # un booléen n'est pas un nombre
    {"sens": "au_dessus", "valeur": float("nan")},
    {"sens": "au_dessus", "valeur": 20, "extra": 1},
    20,
    [],
])
def test_un_seuil_invalide_n_alerte_jamais_et_le_dit(seuil_invalide):
    _, evaluations = _evaluations({"m8_ecart_duree_pct": seuil_invalide}, _wct(), _devis())
    assert evaluations["m8_ecart_duree_pct"]["statut"] == mc.SEUIL_INVALIDE


def test_seuils_absents_ou_mal_formes_sont_traites_comme_absents():
    for seuils in (None, [], "20"):
        _, evaluations = _evaluations(seuils, _wct(), _devis())
        assert evaluations["m8_ecart_duree_pct"]["statut"] == mc.SEUIL_A_CONFIGURER


# ---------------------------------------------------------------------------
# Charges d'alerte : conformes au catalogue, action proposée, sans cause ni responsable
# ---------------------------------------------------------------------------
def _charges(seuils, *entrees, wct_id="wct-fictif-1", horodatage=_HORODATAGE):
    faits = mc.assembler_faits(wct_id, list(entrees))
    mesures = mc.mesurer_chantier(faits, _DEFINITIONS)
    evaluations = mc.evaluer_seuils(mesures, seuils)
    return mc.charges_alertes(wct_id, mesures, evaluations, _DEFINITIONS, horodatage)


def test_un_seuil_franchi_propose_une_alerte_conforme_au_catalogue_avec_sa_preuve():
    charges = _charges({"m8_ecart_duree_pct": {"sens": "au_dessus", "valeur": 15}}, _wct(), _devis())

    assert len(charges) == 1
    charge = charges[0]
    assert catalogue.erreurs_charge("m8.alerte_proposee", charge) == []
    assert charge["type_alerte"] == mc.TYPE_ALERTE_SEUIL_FRANCHI
    assert charge["metric_id"] == "m8_ecart_duree_pct"
    assert charge["a_qui"] == "m04-field-ops"
    assert charge["horodatage_reference"] == _HORODATAGE
    assert charge["preuve"] == {
        "metric_id": "m8_ecart_duree_pct", "wct_id": "wct-fictif-1", "valeur": "20.00", "unite": "pourcentage",
        "sens": "au_dessus", "seuil": "15.00",
        "version_definition": encodage.empreinte(_DEFINITIONS["m8_ecart_duree_pct"]),
    }
    assert "20.00 %" in charge["pourquoi"] and "15.00 %" in charge["pourquoi"]
    assert "wct-fictif-1" in charge["action_proposee"] and "m04-field-ops" in charge["action_proposee"]
    assert charge["source"] == _DEFINITIONS["m8_ecart_duree_pct"]["source_donnees"]


def test_le_destinataire_de_chaque_alerte_est_le_departement_du_processus_mesure():
    seuils = {
        "m8_ecart_duree_pct": {"sens": "au_dessus", "valeur": 1},
        "m8_ecart_marge_pct": {"sens": "au_dessous", "valeur": 0},
        "m8_ecart_materiaux_max_pct": {"sens": "au_dessus", "valeur": 1},
    }
    charges = _charges(seuils, _wct(), _devis(), _variance(), _rentabilite())
    assert {c["metric_id"]: c["a_qui"] for c in charges} == {
        "m8_ecart_duree_pct": "m04-field-ops", "m8_ecart_marge_pct": "m05-financecore",
        "m8_ecart_materiaux_max_pct": "m06-material-control",
    }
    assert all(catalogue.erreurs_charge("m8.alerte_proposee", c) == [] for c in charges)


def test_un_seuil_non_franchi_ne_propose_aucune_alerte():
    assert _charges({"m8_ecart_duree_pct": {"sens": "au_dessus", "valeur": 50}}, _wct(), _devis()) == []


def test_sans_seuil_pas_d_alerte_de_franchissement_mais_un_signal_seuil_a_configurer():
    charges = _charges({}, _wct(), _devis())

    assert [c["type_alerte"] for c in charges] == [mc.TYPE_ALERTE_SEUIL_A_CONFIGURER]
    signal = charges[0]
    assert catalogue.erreurs_charge("m8.alerte_proposee", signal) == []
    assert signal["metric_id"] == "m8_ecart_duree_pct"
    assert signal["preuve"] == {"metric_id": "m8_ecart_duree_pct", "manque": "seuil"}
    assert "aucune alerte n'est possible" in signal["quoi"]
    assert "configuration.seuils_alerte.m8_ecart_duree_pct" in signal["action_proposee"]


def test_un_seuil_invalide_est_signale_comme_tel():
    charges = _charges({"m8_ecart_duree_pct": {"sens": "n'importe", "valeur": 5}}, _wct(), _devis())
    assert charges[0]["preuve"] == {"metric_id": "m8_ecart_duree_pct", "manque": "seuil_invalide"}
    assert "invalide" in charges[0]["pourquoi"]
    assert catalogue.erreurs_charge("m8.alerte_proposee", charges[0]) == []


def test_identifiants_le_franchissement_est_par_chantier_le_rappel_de_seuil_par_metrique_et_par_jour():
    seuil = {"m8_ecart_duree_pct": {"sens": "au_dessus", "valeur": 1}}
    un = _charges(seuil, _wct(), _devis())[0]
    rejoue = _charges(seuil, _wct(), _devis())[0]
    autre = _charges(seuil, _wct(wct_id="wct-fictif-2"), _devis(), wct_id="wct-fictif-2")[0]
    assert un["evenement_id"] == rejoue["evenement_id"]  # rejeu : no-op du bus
    assert un["evenement_id"] != autre["evenement_id"]  # un chantier de plus : une alerte de plus
    assert len(un["evenement_id"]) < 128  # PK du bus, wct_id haché (64 hex) ou non

    rappel_1 = _charges({}, _wct(), _devis())[0]
    rappel_meme_jour = _charges({}, _wct(wct_id="wct-fictif-2"), _devis(), wct_id="wct-fictif-2",
                                horodatage="2026-09-28T17:00:00-04:00")[0]
    rappel_autre_jour = _charges({}, _wct(wct_id="wct-fictif-3"), _devis(), wct_id="wct-fictif-3",
                                 horodatage="2026-09-29T09:00:00-04:00")[0]
    assert rappel_1["evenement_id"] == rappel_meme_jour["evenement_id"]
    assert rappel_1["evenement_id"] != rappel_autre_jour["evenement_id"]


def test_aucune_alerte_ne_nomme_une_cause_ni_un_responsable():
    """DA-M8-07 : un constat chiffré et une action, jamais un coupable."""
    seuils = {"m8_ecart_duree_pct": {"sens": "au_dessus", "valeur": 1}}
    for charge in _charges(seuils, _wct(technicien_id="tech-fictif-secret"), _devis()) + _charges({}, _wct(), _devis()):
        texte = json.dumps(charge, ensure_ascii=False).lower()
        assert "tech-fictif" not in texte  # le technicien n'apparaît dans aucune alerte
        for interdit in ("cause", "responsable", "coupable", "faute"):
            assert interdit not in texte
        assert not {"cause", "responsable", "raison_signalee"} & set(charge)


# ---------------------------------------------------------------------------
# Performance d'équipe : la plus petite métrique honnête
# ---------------------------------------------------------------------------
def _chantier(wct, technicien, reel, estime, devis_id=None):
    devis_id = devis_id or f"devis-{wct}"
    faits = [_wct(wct_id=wct, technicien_id=technicien, duree_reelle_minutes=reel, devis_id=devis_id)]
    if estime is not None:
        faits.append(_devis(devis_id=devis_id, duree_estimee_minutes=estime))
    return faits


def _entrees_equipe():
    entrees = []
    for faits in (
        _chantier("w1", "tech-fictif-b", 150, "100"),   # b : +50 %
        _chantier("w2", "tech-fictif-b", 100, "100"),   # b : cumul 250 / 200 = +25 %
        _chantier("w3", "tech-fictif-a", 90, "100"),    # a : -10 % (le meilleur, mais listé en premier par id)
        _chantier("w4", "tech-fictif-a", 60, None),     # a : sans temps prévu, compté à part
        _chantier("w5", "tech-fictif-c", 60, "0"),      # c : estimé nul, compté à part
    ):
        entrees.extend(faits)
    return entrees


def test_ecart_par_technicien_cumule_sur_les_seuls_chantiers_mesures_et_compte_les_autres():
    resultat = mc.performance_equipe(_entrees_equipe(), 2)
    par_id = {t["technicien_id"]: t for t in resultat["techniciens"]}

    assert par_id["tech-fictif-b"] == {
        "technicien_id": "tech-fictif-b", "n_chantiers_mesures": 2, "n_chantiers_sans_temps_prevu": 0,
        "duree_reelle_totale_minutes": "250.00", "duree_estimee_totale_minutes": "200.00",
        "ecart_pct": "25.00", "suffisant": True,
    }
    assert par_id["tech-fictif-a"]["ecart_pct"] == "-10.00"
    assert par_id["tech-fictif-a"]["n_chantiers_mesures"] == 1
    assert par_id["tech-fictif-a"]["n_chantiers_sans_temps_prevu"] == 1
    assert par_id["tech-fictif-a"]["suffisant"] is False  # 1 chantier mesuré < minimum configuré de 2
    assert par_id["tech-fictif-c"]["ecart_pct"] is None  # aucun chantier mesuré : pas de chiffre inventé
    assert par_id["tech-fictif-c"]["n_chantiers_sans_temps_prevu"] == 1


def test_les_techniciens_sont_listes_par_identifiant_jamais_classes_par_ecart():
    resultat = mc.performance_equipe(_entrees_equipe(), 2)
    identifiants = [t["technicien_id"] for t in resultat["techniciens"]]
    assert identifiants == sorted(identifiants) == ["tech-fictif-a", "tech-fictif-b", "tech-fictif-c"]
    # a a le meilleur écart (-10) et b le pire (+25) : l'ordre ne suit aucun des deux.
    ecarts = [t["ecart_pct"] for t in resultat["techniciens"]]
    assert ecarts != sorted(ecarts, key=lambda e: float(e) if e else 0.0)


def test_l_equipe_est_anonyme_et_agrege_tous_les_chantiers():
    resultat = mc.performance_equipe(_entrees_equipe(), 2)
    equipe = resultat["equipe"]
    assert equipe["n_techniciens"] == 3
    assert equipe["n_chantiers_mesures"] == 3 and equipe["n_chantiers_sans_temps_prevu"] == 2
    assert equipe["duree_reelle_totale_minutes"] == "340.00"  # 150 + 100 + 90
    assert equipe["duree_estimee_totale_minutes"] == "300.00"
    assert equipe["ecart_pct"] == "13.33"
    assert "technicien_id" not in equipe
    assert "tech-fictif" not in json.dumps(equipe)


def test_sans_minimum_configure_suffisant_reste_nul_jamais_vrai_suppose():
    for minimum in (None, 0, -1, True, "3", 2.5):
        resultat = mc.performance_equipe(_entrees_equipe(), minimum)
        assert resultat["chantiers_minimum_a_configurer"] is True
        assert resultat["equipe"]["suffisant"] is None
        assert all(t["suffisant"] is None for t in resultat["techniciens"])
    assert mc.performance_equipe(_entrees_equipe(), 1)["chantiers_minimum_a_configurer"] is False


def test_un_chantier_relivre_n_est_compte_qu_une_fois_et_sans_chantier_l_equipe_est_vide():
    entrees = _chantier("w1", "tech-fictif-a", 120, "100")
    doublon = mc.performance_equipe(entrees + [_wct(wct_id="w1", technicien_id="tech-fictif-a",
                                                    duree_reelle_minutes=120, devis_id="devis-w1")], 1)
    assert doublon["equipe"]["n_chantiers_mesures"] == 1

    vide = mc.performance_equipe([], 1)
    assert vide["techniciens"] == [] and vide["equipe"]["n_techniciens"] == 0
    assert vide["equipe"]["ecart_pct"] is None and vide["equipe"]["n_chantiers_mesures"] == 0


def test_la_performance_d_equipe_ne_produit_jamais_de_charge_d_alerte():
    """Aucun employé alerté ni accusé automatiquement : la métrique d'équipe n'est pas surveillée."""
    assert mc.METRIQUE_EQUIPE not in mc._DESTINATAIRE_ALERTE
    mesures = _mesures(_wct(), _devis())
    assert mc.METRIQUE_EQUIPE not in mesures  # pas une mesure de chantier
