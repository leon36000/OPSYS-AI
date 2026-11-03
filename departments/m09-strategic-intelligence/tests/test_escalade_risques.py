"""M9.12 (M9-C1) — l'escalade INTERNE d'un risque critique : avis, tâche, mémoire ; jamais externe (fictif)."""

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest
from m9_strategic_intelligence import escalade_risques as esc
from m9_strategic_intelligence import plans as plans_module
from m9_strategic_intelligence import risques as rk


def _charger_aide():
    if "aide_radar" in sys.modules:
        return sys.modules["aide_radar"]
    spec = importlib.util.spec_from_file_location("aide_radar", Path(__file__).with_name("aide_radar.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules["aide_radar"] = module
    spec.loader.exec_module(module)
    return module


A = _charger_aide()
FICTIF = True
CONN = A.CONNAISSANCE


def _radar(*, plaintes=6, cash="-50.00"):
    chaine: list = []
    A.capturer(chaine, "m1.plaintes_structurees", A.page_plaintes(plaintes), 0)
    A.capturer(chaine, "m8.vue_executive", A.page_cash_libre(cash), 1)
    return A.radar(chaine, seuils=A.SEUILS)


def test_seuls_les_risques_actifs_et_critiques_sont_selectionnes():
    radar = _radar(plaintes=3)  # 3 plaintes = ELEVE (pas critique) ; cash libre négatif = CRITIQUE
    assert [(r["regle"], r["gravite"]) for r in esc.selection(radar)] == [("cash_libre_deficit", "CRITIQUE")]
    ancien = copy.deepcopy(radar)
    for r in ancien["risques"]:
        r["statut"] = "LEVE"
    assert esc.selection(ancien) == []
    inconnu = copy.deepcopy(radar)
    for r in inconnu["risques"]:
        r["gravite"] = "INCONNU"
    assert esc.selection(inconnu) == []


def test_l_avis_cite_regle_mesure_seuil_source_et_dit_qu_aucun_message_externe_n_est_envoye():
    radar = _radar()
    risque = next(r for r in esc.selection(radar) if r["regle"] == "plaintes_afflux")
    maillon = esc.avis([], risque, radar, connaissance=CONN, par="admin.fictif")
    assert maillon["type"] == "AVIS" and maillon["canal"] == "interne" and maillon["externe"] is False
    assert maillon["gravite"] == "CRITIQUE" and maillon["regle"] == "plaintes_afflux"
    assert maillon["origine_etablie"] is False and maillon["radar_id"] == radar["radar_id"]
    assert maillon["source"]["lecture_id"] == "m1.plaintes_structurees"
    texte = maillon["texte"]
    assert "plaintes_afflux" in texte and "valeur = 6" in texte and "m9.plaintes_seuil_nombre" in texte
    assert "Aucune cause établie" in texte and "aucun message externe" in texte
    assert esc.valider_chaine([maillon]) == (True, "")


def test_un_avis_par_regle_sujet_et_jour_le_rejeu_du_meme_jour_n_ajoute_rien_le_lendemain_oui():
    radar = _radar()
    risque = esc.selection(radar)[0]
    premier = esc.avis([], risque, radar, connaissance=CONN, par="admin.fictif")
    assert esc.avis([premier], risque, radar, connaissance="2026-10-28T20:00:00Z", par="admin.fictif") is None
    lendemain = esc.avis([premier], risque, radar, connaissance="2026-10-29T08:00:00Z", par="admin.fictif")
    assert lendemain is not None and lendemain["avis_id"] != premier["avis_id"]
    assert lendemain["tache_id"] != premier["tache_id"] and lendemain["suivi_ref"] == premier["suivi_ref"]


@pytest.mark.parametrize(
    "modif", [{"statut": "LEVE"}, {"statut": "A_RECONFIRMER"}, {"gravite": "ELEVE"}, {"gravite": "INCONNU"}]
)
def test_un_risque_non_critique_ou_non_actif_ne_s_escalade_pas(modif):
    radar = _radar()
    risque = {**esc.selection(radar)[0], **modif}
    with pytest.raises(ValueError, match="REJ-ESCALADE-RISQUE"):
        esc.avis([], risque, radar, connaissance=CONN, par="admin.fictif")


def test_la_tache_est_un_plan_valide_pour_la_direction_avec_un_resultat_cle_manuel():
    radar = _radar()
    risque = esc.selection(radar)[0]
    plan = esc.tache(risque, connaissance=CONN)
    assert plan["porteur"].startswith("direction") and plan["echeance"] == "2026-10-28"
    assert [r["operateur"] for r in plan["resultats_cles"]] == ["manuel"]
    maillon = plans_module.enregistrer([], plan, {}, recu_a=CONN, par="admin.fictif")
    etat = plans_module.etat_plans([maillon])[plan["plan_id"]]
    assert etat["versions"][0]["plan"]["decision_ref"] == esc.identifiants(risque, CONN)["suivi_ref"]
    assert plans_module.valider_chaine([maillon]) == (True, "")


def test_la_trace_de_memoire_est_une_charge_m9_fait_strategique_de_genre_risque_sans_personne():
    radar = _radar()
    risque = esc.selection(radar)[0]
    maillon = esc.avis([], risque, radar, connaissance=CONN, par="admin.fictif")
    charge = esc.evenement_memoire(maillon)
    assert charge["genre"] == "risque" and charge["statut"] == "signale_par_le_radar"
    assert (
        charge["evenement_id"] == "m9-strat-" + maillon["hash_maillon"] and charge["decision_id"] == maillon["avis_id"]
    )
    assert charge["attendus"] == [] and charge["observations"] == [] and charge["decide_role"] is None
    assert "admin.fictif" not in json.dumps(charge), "aucun nom de personne dans l'évènement"
    assert len(charge["texte"]) <= 1200 and len(charge["mention"]) <= 400
    assert "professionnel qualifié" in charge["mention"]
    # la charge passe le catalogue d'évènements du socle (schéma fermé)
    from opsys.evenements import schemas

    assert schemas.erreurs_charge(esc.TYPE_EVENEMENT, charge) == []


def test_une_chaine_d_avis_falsifiee_est_refusee():
    radar = _radar()
    risque = esc.selection(radar)[0]
    maillon = esc.avis([], risque, radar, connaissance=CONN, par="admin.fictif")
    falsifie = {**maillon, "externe": True}
    assert esc.valider_chaine([falsifie])[0] is False
    assert esc.valider_chaine([{**maillon, "type": "ENVOI"}])[0] is False


def test_la_vue_pagine_du_plus_recent_au_plus_ancien():
    radar = _radar()
    risque = esc.selection(radar)[0]
    chaine: list = []
    for jour in ("2026-10-26", "2026-10-27", "2026-10-28"):
        chaine.append(esc.avis(chaine, risque, radar, connaissance=f"{jour}T08:00:00Z", par="a"))
    vue = esc.vue(chaine, depart=0, limite=2)
    assert [a["jour"] for a in vue["avis"]] == ["2026-10-28", "2026-10-27"] and vue["prochain_depart"] == 2
    assert all(a["externe"] is False for a in vue["avis"]) and rk is not None


def test_le_texte_de_l_avis_ignore_les_valeurs_nulles_et_les_blocs_imbriques():
    radar = _radar()
    risque = copy.deepcopy(esc.selection(radar)[0])
    risque["mesure"] = {
        "valeur": "6",
        "unite": "plaintes",
        "periode_jours": None,
        "periode": {"debut": "2026-10-21", "fin": "2026-10-28"},
    }
    risque["seuil"] = {"valeur": "3", "unite": "plaintes", "note": None, "details": {"multiple": "1.5"}}
    texte = esc.texte_avis(risque)
    assert "valeur = 6" in texte and "unite = plaintes" in texte and "valeur = 3" in texte
    assert "periode_jours" not in texte and "note" not in texte and "details" not in texte
    assert "periode = " not in texte


def test_la_vue_par_defaut_rend_les_dix_derniers_et_le_prochain_depart_suit_la_page():
    radar = _radar()
    risque = esc.selection(radar)[0]
    chaine: list = []
    for jour in range(1, 13):
        chaine.append(esc.avis(chaine, risque, radar, connaissance=f"2026-09-{jour:02d}T08:00:00Z", par="a"))
    vue = esc.vue(chaine)
    assert vue["depart"] == 0 and len(vue["avis"]) == 10 and vue["prochain_depart"] == 10
    assert [a["jour"] for a in vue["avis"]][0] == "2026-09-12"
    fin = esc.vue(chaine, depart=10, limite=5)
    assert len(fin["avis"]) == 2 and fin["prochain_depart"] is None


def test_le_prochain_depart_est_nul_quand_la_page_atteint_exactement_la_fin():
    radar = _radar()
    risque = esc.selection(radar)[0]
    chaine: list = []
    for jour in ("01", "02", "03"):
        chaine.append(esc.avis(chaine, risque, radar, connaissance=f"2026-09-{jour}T08:00:00Z", par="a"))
    vue = esc.vue(chaine, depart=1, limite=2)
    assert len(vue["avis"]) == 2 and vue["prochain_depart"] is None
