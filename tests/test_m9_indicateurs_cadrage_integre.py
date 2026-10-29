"""M9.3/M9.10 — indicateurs exécutifs et cadrage de décision par les vrais outils, producteurs M8 réels (fictif)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from m8_analytics import registre_metriques

from opsys import stockage

_TESTS = Path(__file__).resolve().parent


def _charger(nom: str):
    spec = importlib.util.spec_from_file_location(nom, _TESTS / f"{nom}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[nom] = module
    spec.loader.exec_module(module)
    return module


H = _charger("m9_producteurs_b")
FICTIF = True
CONNAISSANCE = "2026-10-28T13:00:00Z"
M8 = "m08-analytics"


def _recu(n: int) -> str:
    return f"2026-10-28T12:00:{n:02d}Z"


@pytest.fixture
def monde(tmp_path, monkeypatch):
    H.installer_base(tmp_path, monkeypatch)
    H.declarer_m5(tmp_path, monkeypatch)
    H.alimenter_m8()
    yield H.capacites(H.M8)
    H.desinstaller_base()


def _appel(cap, nom, arguments, identite=H.ADMIN):
    if identite is None:
        return cap.appeler(nom, arguments)
    with H.contexte.appele_par_appareil(identite):
        return cap.appeler(nom, arguments)


def _ok(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]


def _refuse(reponse, code=None):
    echec = reponse["ok"] is False or reponse["resultat"].get("accepte") is False
    return echec and (code is None or code in json.dumps(reponse))


def _capturer(cap, lecture, arguments, rang):
    reponse = H.capturer(cap, H.ADMIN, lecture, arguments, _recu(rang))
    assert reponse["ok"] is True and reponse["resultat"]["capture"]["verdict"] == "ACCEPTEE", reponse


def _definir(metric_id):
    with stockage.transaction():
        verdict = registre_metriques.enregistrer_definition(
            {
                "metric_id": metric_id,
                "departement_proprietaire": M8,
                "unite": "CAD",
                "source": "m8_lire_mesures_chantier",
                "fraicheur_attendue_jours": 30,
                "regles_qualite": {"plage_min": None, "plage_max": None},
            },
            stockage.maillons(M8, "definitions_metriques"),
        )
    assert verdict["enregistree"] is True, verdict


def _tous_les_indicateurs(cap):
    lignes, depart = [], 0
    while depart is not None:
        page = _ok(_appel(cap, "m9_indicateurs_executifs", {"connaissance": CONNAISSANCE, "depart": depart}))
        lignes += page["indicateurs"]
        depart = page["prochain_depart"]
    return lignes, page


def test_indicateurs_sans_capture_nomment_les_absences_et_ne_calculent_rien(monde):
    lignes, derniere = _tous_les_indicateurs(monde)
    assert [i["id"] for i in lignes][:3] == ["revenue", "gross_margin", "net_margin"] and len(lignes) == 17
    assert derniere["registre_m8_capture"] is False and derniere["par_statut"]["A_DEFINIR_PAR_LE_PROPRIETAIRE"] == 9
    assert all(i["calcule_par_m9"] is False for i in lignes)
    marge = next(i for i in lignes if i["id"] == "gross_margin")
    assert set(marge["metriques_m8"].values()) == {"REGISTRE_NON_CAPTURE"} and marge["faits"] == []


def test_indicateurs_avec_les_vraies_mesures_et_le_vrai_registre_m8(monde):
    _capturer(monde, "m8.mesures_chantier", {"wct_id": H.WCT_ID}, 1)
    _definir("m8_marge_reelle_cad")
    _capturer(monde, "m8.definitions_metriques", {}, 2)
    lignes, entete = _tous_les_indicateurs(monde)
    par_id = {i["id"]: i for i in lignes}
    assert entete["registre_m8_capture"] is True
    marge = par_id["gross_margin"]
    assert marge["metriques_m8"]["m8_marge_reelle_cad"] == "AU_REGISTRE"
    assert marge["metriques_m8"]["m8_marge_prevue_cad"] == "ABSENTE_DU_REGISTRE"
    reelle = [f for f in marge["faits"] if f["metric_id"] == "m8_marge_reelle_cad"]
    assert reelle and reelle[0]["valeur"] == "114.00" and reelle[0]["adresse"].startswith("m8.mesures_chantier#")
    assert (
        par_id["revenue"]["statut_definition"] == "A_DEFINIR_PAR_LE_PROPRIETAIRE" and "faits" not in par_id["revenue"]
    )
    assert par_id["cost_per_lead"]["lignage"] == "AUCUN_FAIT_CAPTURE", "M7 n'a pas été capturé : rien n'est cité"


def test_indicateurs_refus_non_admin_voie_d_agent_instant_et_depart(monde):
    vendeur = H.IdentiteAppelante("vendeur.fictif", "employee", source="appareil")
    assert _refuse(_appel(monde, "m9_indicateurs_executifs", {"connaissance": CONNAISSANCE}, vendeur))
    assert _refuse(_appel(monde, "m9_indicateurs_executifs", {"connaissance": CONNAISSANCE}, None))
    assert _refuse(_appel(monde, "m9_indicateurs_executifs", {"connaissance": "demain"}), "REJ-INDICATEURS-INSTANT")
    assert _refuse(
        _appel(monde, "m9_indicateurs_executifs", {"connaissance": CONNAISSANCE, "depart": 99}),
        "REJ-INDICATEURS-DEPART",
    )


def test_cadrage_sans_lecture_capturee_nomme_les_manques_et_ne_decide_rien(monde):
    res = _ok(
        _appel(monde, "m9_cadrer_decision", {"question": "Dois-je acheter un camion ?", "reference": CONNAISSANCE})
    )
    assert res["decision"]["id"] == "achat_vehicule" and res["pret_pour_conseil"] is False
    assert {m["statut"] for m in res["manques"]} == {"ABSENTE"} and res["decision_prise_par_m9"] is False
    assert res["validation"]["requiert_nathan"] is True
    assert res["validation"]["classes_sensibles"]["achat_majeur"]["verdict"] == "VALIDATION_HUMAINE_REQUISE"
    assert res["brouillon_approbation"]["statut"] == "BROUILLON_NON_SOUMIS"


def test_cadrage_lectures_presentes_et_questions_non_reconnues_ou_refusees(monde):
    _capturer(monde, "m8.vue_executive", {"aujourd_hui": "2026-10-28"}, 1)
    res = _ok(
        _appel(monde, "m9_cadrer_decision", {"question": "Dois-je augmenter les prix ?", "reference": CONNAISSANCE})
    )
    statuts = {c["lecture_id"]: c["statut"] for c in res["couverture"]}
    assert statuts["m8.vue_executive"] != "ABSENTE" and statuts["m5.rentabilite_chantier"] == "ABSENTE"
    inconnue = _ok(_appel(monde, "m9_cadrer_decision", {"question": "Quel temps demain ?", "reference": CONNAISSANCE}))
    assert inconnue["classement"]["statut"] == "TYPE_NON_RECONNU" and inconnue["pret_pour_conseil"] is False
    assert _refuse(_appel(monde, "m9_cadrer_decision", {"question": "", "reference": CONNAISSANCE}))
    assert _refuse(_appel(monde, "m9_cadrer_decision", {"question": "x" * 501, "reference": CONNAISSANCE}))
    assert _refuse(_appel(monde, "m9_cadrer_decision", {"question": "Camion ?", "reference": "hier"}))
    vendeur = H.IdentiteAppelante("vendeur.fictif", "employee", source="appareil")
    assert _refuse(_appel(monde, "m9_cadrer_decision", {"question": "Camion ?", "reference": CONNAISSANCE}, vendeur))
    assert _refuse(_appel(monde, "m9_cadrer_decision", {"question": "Camion ?", "reference": CONNAISSANCE}, None))


def test_peremption_demandee_au_cadrage_et_a_la_couverture_est_validee_par_les_vrais_outils(monde):
    ok = _ok(
        _appel(
            monde,
            "m9_cadrer_decision",
            {"question": "Dois-je réduire les dépenses ?", "reference": CONNAISSANCE, "perime_apres_jours": 30},
        )
    )
    assert ok["perime_apres_jours"] == 30
    assert _refuse(
        _appel(
            monde,
            "m9_cadrer_decision",
            {"question": "Dois-je réduire les dépenses ?", "reference": CONNAISSANCE, "perime_apres_jours": 0},
        )
    )
    couverture = _ok(_appel(monde, "m9_couverture_strategique", {"reference": CONNAISSANCE, "perime_apres_jours": 30}))
    assert couverture["lectures"] and couverture["complete"] is False
    assert _refuse(_appel(monde, "m9_couverture_strategique", {"reference": CONNAISSANCE, "perime_apres_jours": 3651}))
