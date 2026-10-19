"""Synthèse de période FICTIVE : vrais producteurs M8/bus/SQLite, jamais une action terrain."""

from __future__ import annotations

import copy
import importlib
import importlib.util
import json
from datetime import datetime
from pathlib import Path

import pytest

from opsys import contexte, identite, stockage

_spec = importlib.util.spec_from_file_location(
    "_rapport_periode_bilan_base", Path(__file__).with_name("test_bilan_suivis.py")
)
p = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(p)
b = p.b
installation = p.installation
NOM = "m9_rapport_periode"


def test_rapport_natif_apres_trois_plans_deux_clotures_et_preuve_m8_reelle(installation, monkeypatch):
    cap, ids = p._preparer_natif(installation, monkeypatch)
    plans, clotures = b._suivis(), p.h._clotures()
    assert len(plans) == 3 and len(clotures) == 2
    assert p._lire(cap)["compteurs"] == {"ouverts_periode": 1, "clotures_periode": 1, "ouverts_fin": 1}
    alerte = plans[0]["source"]["alerte"]
    assert alerte["evenement_id"] and alerte["preuve"]["wct_id"]
    assert alerte["preuve"]["metric_id"] == alerte["metric_id"]
    assert NOM in cap.index, "M9_RAPPORT_PERIODE_ABSENT_APRES_3_PLANS_2_CLOTURES_ET_M8_REELS"
    avant = b._tables()
    rapport = b._lire(cap, NOM, {"debut": p.DEBUT, "fin": p.FIN})
    assert rapport["type"] == "RAPPORT_PERIODE"
    assert (rapport["debut"], rapport["fin"]) == (p.DEBUT, p.FIN)
    bilan = p._lire(cap)
    assert rapport["suivis"] == {"compteurs": bilan["compteurs"], "total": bilan["total"], "vue_bilan": bilan["vue"]}
    non_couverts = {"decisions_en_attente", "faits_veille", "faits_par_module", "etat_id", "briefing_id"}
    assert not non_couverts.intersection(rapport)
    instant = datetime.fromisoformat(alerte["horodatage_reference"].replace("Z", "+00:00"))
    retenue = datetime.fromisoformat(p.DEBUT) <= instant < datetime.fromisoformat(p.FIN)
    assert rapport["alertes_periode"]["total"] == int(retenue)
    if retenue:
        assert rapport["alertes_periode"]["alertes"] == [alerte]
    assert rapport["rapport_complet"] is False and rapport["actualite_metier"] == "NON_EVALUEE"
    assert b._tables() == avant


evenements = b.evenements
RESPONSABLE = b.RESPONSABLE
DEPARTEMENT = b.DEPARTEMENT

def _recevoir_alerte_fictive(departements, instant, suffix=""):
    jeu = {
        "fictif": True,
        "devis": {
            "devis_id": "devis-suivi-fictif" + suffix, "lead_id": "lead-suivi-fictif", "chantier_id": None,
            "lignes": [{"reference_ligne": "ligne-suivi-fictive", "description": "Gouttières fictives",
                        "quantite": "40", "unite": "pi", "prix_unitaire": "15.00", "prix_ligne": "600.00",
                        "reference_besoin_materiau": None}],
            "cout_total": "480.00", "prix_total": "600.00", "taux_marge": "0.25",
            "duree_estimee_minutes": "60", "horodatage_acceptation": "2026-09-20T09:00:00-04:00",
        },
        "wct": {
            "wct_id": "wct-suivi-fictif" + suffix, "intervention_id": "intervention-suivi-fictive",
            "lead_id": "lead-suivi-fictif", "technicien_id": RESPONSABLE,
            "horodatage_completion": "2026-09-27T15:00:00-04:00",
            "fix_gps_completion": {"latitude": 45.75, "longitude": -73.5},
            "duree_reelle_minutes": 120, "ecart_signale": False, "revue_id": None,
            "hash_maillon": "preuve-terrain-fictive", "consommateurs_cibles": ["M8"],
            "devis_id": "devis-suivi-fictif" + suffix, "statut": "completed_verified",
        },
    }
    assert jeu["fictif"] is True
    jeu["wct"]["horodatage_completion"] = instant
    evenements.publier("m3.devis_accepte", "m03-estimation", jeu["devis"])
    evenements.publier("m4.travaux_termines", "m04-field-ops", jeu["wct"])
    for _ in range(2):
        tour = evenements.repartir(departements, maintenant=instant)
        assert tour["echecs"] == tour["quarantaines"] == 0, tour
    with stockage.transaction():
        [alerte] = [a for a in stockage.maillons(DEPARTEMENT, "alertes_m8")
                    if a["preuve"].get("wct_id") == jeu["wct"]["wct_id"]]
    assert alerte["metric_id"] == "m8_ecart_duree_pct"
    assert alerte["type_alerte"] == "MESURE-SEUIL-FRANCHI"
    assert alerte["preuve"]["valeur"] == "100.00"
    assert alerte["preuve"]["wct_id"] == jeu["wct"]["wct_id"]
    return alerte


def _cap(installation):
    return b._capacites(installation)


def _rapport(cap, **args):
    return b._lire(cap, NOM, {"debut": p.DEBUT, "fin": p.FIN} | args)


def _refus(cap, code, **args):
    avant = b._tables()
    with contexte.appele_par_appareil(b.PROPRIO):
        r = cap.appeler(NOM, {"debut": p.DEBUT, "fin": p.FIN} | args)
    assert r.get("ok") is False and code in json.dumps(r, ensure_ascii=False), r
    assert b._tables() == avant


def test_file_courante_non_historisee_ne_change_ni_vue_ni_compteurs(installation):
    cap, arguments, _, _ = b._proposer(installation)
    avant = _rapport(cap)
    proposition = cap.appeler(b.OUVRIR, arguments | {"action": "Deuxième demande fictive non approuvée"})
    assert proposition["statut"] == "en_attente_approbation"
    assert not b._suivis()
    assert _rapport(cap) == avant
    assert not {"decisions_en_attente", "faits_veille", "faits_par_module", "etat_id"}.intersection(avant)


def test_alertes_m8_reelles_filtrees_par_instants_avec_bornes_et_fuseaux(installation):
    dates = ["2026-10-05T00:00:00-04:00", "2026-10-12T02:00:00+00:00", "2026-10-12T04:00:00Z"]
    alertes = [_recevoir_alerte_fictive(installation, d, "-fuseau-" + str(i)) for i, d in enumerate(dates)]
    rapport = _rapport(_cap(installation), debut=dates[0], fin="2026-10-12T00:00:00-04:00")
    section = rapport["alertes_periode"]
    assert section["total"] == 2
    assert [a["evenement_id"] for a in section["alertes"]] == [alertes[1]["evenement_id"], alertes[0]["evenement_id"]]
    assert section["alertes"] == [alertes[1], alertes[0]]


def test_snapshots_courants_non_substitues_aux_faits_de_periode(installation):
    cap = _cap(installation)
    avant = _rapport(cap)
    for i, date in enumerate(["2026-10-01T00:00:00Z", "2026-10-06T00:00:00Z", "2026-10-20T00:00:00Z"]):
        resultat = cap.appeler("m9_etat_consolide", {"snapshot": {
            "module_source": "M4", "horodatage": date,
            "valeurs": {"marqueur": "SNAPSHOT_FICTIF_NON_HISTORIQUE_" + str(i)},
        }})
        assert resultat.get("ok") is True, resultat
    apres = _rapport(cap)
    assert apres == avant
    assert "SNAPSHOT_FICTIF_NON_HISTORIQUE" not in json.dumps(apres)
    assert {x["section"] for x in apres["manques"]} >= {"faits_periode", "reception_alertes"}


@pytest.mark.parametrize("cause,code", [("preuve_vide", "REJ-RAPPORT-ALERTE"),
                                         ("metrique_discordante", "REJ-RAPPORT-ALERTE"),
                                         ("date_naive", "REJ-RAPPORT-ALERTE-FUSEAU")])
def test_alerte_hors_periode_corrompue_refusee_par_lecture_native(installation, cause, code):
    alerte = _recevoir_alerte_fictive(installation, "2026-11-01T12:00:00Z", "-corruption-" + cause)
    # Injection négative dans un registre de TEST : chaîne valide, charge corrompue après réception.
    mauvaise = copy.deepcopy(alerte)
    mauvaise["evenement_id"] += "-charge-corrompue-fictive"
    if cause == "preuve_vide":
        mauvaise["preuve"] = {}
    elif cause == "metrique_discordante":
        mauvaise["preuve"]["metric_id"] = "autre-metrique-fictive"
    else:
        mauvaise["horodatage_reference"] = "2026-11-01T12:00:00"
    with stockage.transaction():
        stockage.maillons(DEPARTEMENT, "alertes_m8").append(mauvaise)
    _refus(_cap(installation), code)


def test_huit_alertes_reelles_paginees_sans_perte_et_vue_lie_toutes_les_sources(installation, monkeypatch):
    alertes = [_recevoir_alerte_fictive(installation, f"2026-10-06T12:00:{i:02d}Z", "-page-" + str(i))
               for i in range(8)]
    module = importlib.import_module("m9_strategic_intelligence.outils")
    monkeypatch.setattr(module, "BUDGET_SORTIE", 2600)
    cap = _cap(installation)
    page = _rapport(cap)
    assert page["alertes_periode"]["prochain_depart"] is not None
    premiere = copy.deepcopy(page)
    attendues = {alerte["evenement_id"]: alerte for alerte in alertes}
    ids, pages, vus = [], 0, set()
    while True:
        pages += 1
        assert len(json.dumps(page, ensure_ascii=False, allow_nan=False)) <= 2600
        section = page["alertes_periode"]
        assert section["total"] == 8 and page["vue"] == premiere["vue"]
        assert section["affichees"] == len(section["alertes"])
        assert all(alerte == attendues[alerte["evenement_id"]] for alerte in section["alertes"])
        assert section["reste"] == 8 - section["depart"] - section["affichees"]
        ids.extend(a["evenement_id"] for a in section["alertes"])
        prochain = section["prochain_depart"]
        if prochain is None:
            break
        assert prochain not in vus
        vus.add(prochain)
        page = _rapport(cap, depart=prochain, vue_attendue=page["vue"])
    assert pages >= 3 and len(ids) == len(set(ids)) == 8
    assert set(ids) == {a["evenement_id"] for a in alertes}
    _recevoir_alerte_fictive(installation, "2026-11-01T12:00:00Z", "-nouvelle-hors-periode")
    _refus(cap, "REJ-RAPPORT-VUE-PERIMEE", depart=premiere["alertes_periode"]["prochain_depart"],
           vue_attendue=premiere["vue"])
    assert _rapport(cap)["alertes_periode"]["total"] == 8


def test_arrivee_tardive_connue_a_lecture_pas_un_instantane_a_fin(installation):
    cap = _cap(installation)
    avant = _rapport(cap)
    alerte = _recevoir_alerte_fictive(installation, "2026-10-06T12:00:00Z", "-arrivee-tardive")
    apres = _rapport(cap)
    assert avant["alertes_periode"]["total"] == 0
    assert apres["alertes_periode"]["total"] == 1 and apres["alertes_periode"]["alertes"] == [alerte]
    assert avant["vue"] != apres["vue"]
    for rapport in [avant, apres]:
        assert any(m["section"] == "reception_alertes" for m in rapport["manques"])
        assert not {"etat_a_fin", "fige_a_fin"}.intersection(rapport)
        assert rapport["rapport_complet"] is False


@pytest.mark.parametrize("args,code", [({"debut": "2026-10-05"}, "REJ-RAPPORT-PERIODE"),
    ({"fin": "2026-10-12T00:00:00"}, "REJ-RAPPORT-PERIODE"),
    ({"debut": p.FIN}, "REJ-RAPPORT-PERIODE"), ({"depart": -1}, "REJ-RAPPORT-ARGUMENT"),
    ({"depart": True}, "REJ-RAPPORT-ARGUMENT"), ({"depart": 1}, "REJ-RAPPORT-VUE"),
    ({"vue_attendue": "x" * 64}, "REJ-RAPPORT-ARGUMENT"), ({"budget_caracteres": 1}, "REJ-BILAN-BORNE")])
def test_arguments_et_squelette_purs_refuses_sans_horloge(args, code):
    module = importlib.import_module("m9_strategic_intelligence.rapport_periode")
    with pytest.raises(ValueError, match=code):
        module.assembler_rapport_periode([], [], [], args.get("debut", p.DEBUT), args.get("fin", p.FIN),
            **{k: v for k, v in args.items() if k not in {"debut", "fin", "budget_caracteres"}},
            budget_caracteres=args.get("budget_caracteres", 6000))


def test_admin_sql_courant_refuse_avant_registres(installation, monkeypatch):
    cap = _cap(installation)
    assert _rapport(cap)["rapport_complet"] is False
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, b.PROPRIO.personne, "admin")
    def interdit(*args, **kwargs):
        raise AssertionError("LECTURE_PRIVEE_AVANT_ADMIN_FICTIF")
    monkeypatch.setattr(stockage, "maillons", interdit)
    _refus(cap, "IDENTITE")
