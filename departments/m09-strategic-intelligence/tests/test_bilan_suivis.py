"""Bilan de période FICTIF : vraies approbations SQL, jamais une preuve d'action terrain.

Le premier oracle prépare les données natives AVANT de constater la capacité absente.
L'horloge des approbations est fixée avant chaque création/décision : aucun maillon SQL
ni aucune empreinte de plan/clôture n'est réécrit pour fabriquer la chronologie.
"""

from __future__ import annotations

import copy
import importlib
import importlib.util
import json
from pathlib import Path

import pytest

from opsys import approbations, contexte, identite, stockage

_spec = importlib.util.spec_from_file_location(
    "_bilan_echeancier_base", Path(__file__).with_name("test_echeancier_suivis.py")
)
s = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(s)
h = s.h
b = s.b
installation = s.installation
NOM = "m9_bilan_suivis_decision"
DEBUT = "2026-10-05T00:00:00+00:00"
FIN = "2026-10-12T00:00:00+00:00"


def _pure(plans, clotures=(), **args):
    # Import pendant l'exécution : le module absent ne casse pas la collecte.
    module = importlib.import_module("m9_strategic_intelligence.bilan_suivis")
    return module.bilan_suivis_decision(
        plans, list(clotures), args.pop("debut", DEBUT), args.pop("fin", FIN),
        budget_caracteres=args.pop("budget_caracteres", 6000), **args,
    )


def _lire(cap, **args):
    return b._lire(cap, NOM, {"debut": DEBUT, "fin": FIN} | args)


def _toutes_pages(lire):
    page = lire()
    lignes = list(page["suivis"])
    while page["prochain_depart"] is not None:
        page = lire(depart=page["prochain_depart"], vue_attendue=page["vue"])
        lignes.extend(page["suivis"])
    return lignes


def _preparer_natif(installation, monkeypatch):
    def date(instant):
        monkeypatch.setattr(approbations, "_maintenant", lambda: instant)

    date("2026-10-01T12:00:00+00:00")
    cap, ids, alerte = s._preparer(installation, 1)
    plan = b._suivis()[0]
    arguments = {k: plan[k] for k in ("action", "responsable_id", "echeance")}
    arguments |= {"evenement_id": alerte["evenement_id"], "empreinte_source": b.empreinte(alerte)}
    for suffixe, instant in [("B", "2026-10-06T12:00:00+00:00"), ("C", FIN)]:
        date(instant)
        prop = cap.appeler(b.OUVRIR, arguments | {"action": "Revue fictive de période " + suffixe})
        assert prop["statut"] == "en_attente_approbation", prop
        ident = prop["demande_id"]
        decision = b._decider(cap, ident, "ouvrir-bilan-" + ident)
        assert decision["resultat"]["resultat"]["statut"] == "executee", decision
        ids.append(ident)
    date("2026-10-08T12:00:00+00:00")
    s._clore(cap, ids[1], alerte)
    date("2026-10-13T12:00:00+00:00")
    s._clore(cap, ids[0], alerte)
    return cap, ids


def test_bilan_natif_reconstitue_fin_passee_apres_vraies_approbations(installation, monkeypatch):
    cap, ids = _preparer_natif(installation, monkeypatch)
    plans = {p["suivi_id"]: p for p in b._suivis()}
    clotures = {c["suivi_id"]: c for c in h._clotures()}
    assert len(plans) == 3 and len(clotures) == 2
    assert plans[ids[0]]["decision"]["decide_le"] == "2026-10-01T12:00:00+00:00"
    assert plans[ids[2]]["decision"]["decide_le"] == FIN
    assert clotures[ids[0]]["decision"]["decide_le"] == "2026-10-13T12:00:00+00:00"
    assert clotures[ids[1]]["decision"]["decide_le"] == "2026-10-08T12:00:00+00:00"
    assert all(c["empreinte_suivi"] == b.empreinte(plans[i]) for i, c in clotures.items())
    assert NOM in cap.index, "M9_BILAN_PERIODE_CAPACITE_ABSENTE_APRES_PREPARATION_SQL_REELLE"
    avant = b._tables()
    premiere = _lire(cap)
    assert premiere["type"] == "BILAN_SUIVIS_DECISION"
    assert (premiere["debut"], premiere["fin"]) == (DEBUT, FIN)
    assert premiere["compteurs"] == {"ouverts_periode": 1, "clotures_periode": 1, "ouverts_fin": 1}
    lignes = _toutes_pages(lambda **kw: _lire(cap, **kw))
    assert [r["suivi"]["suivi_id"] for r in lignes] == ids[:2]
    a, c = lignes
    assert a["suivi"] == plans[ids[0]] and a["empreinte_suivi"] == b.empreinte(plans[ids[0]])
    assert (a["ouvert_dans_periode"], a["cloture_dans_periode"], a["ouvert_fin"]) == (False, False, True)
    assert "cloture" not in a, "La clôture postérieure ne doit pas être attribuée au bilan passé"
    assert (c["ouvert_dans_periode"], c["cloture_dans_periode"], c["ouvert_fin"]) == (True, True, False)
    assert c["suivi"] == plans[ids[1]] and c["cloture"] == clotures[ids[1]]
    assert b._tables() == avant
    stockage.liberer()
    assert _lire(b._capacites(installation)) == premiere


@pytest.mark.parametrize("cause", ["source_vide", "source_empreinte", "source_metrique", "preuve_vide",
                                    "preuve_empreinte", "preuve_chantier"])
def test_preuves_historiques_corrompues_refusees_meme_hors_periode(cause):
    plans = [_plan(ouverture="2026-11-01T00:00:00Z")]
    clotures = [_cloture(plans[0], "2026-11-02T00:00:00Z")]
    if cause == "source_vide":
        plans[0]["source"] = {}
    elif cause == "source_empreinte":
        plans[0]["source"]["empreinte_source"] = "0" * 64
    elif cause == "source_metrique":
        source = plans[0]["source"]
        source["alerte"]["preuve"]["metric_id"] = "autre-metrique-fictive"
        source["empreinte_source"] = b.empreinte(source["alerte"])
    elif cause == "preuve_vide":
        clotures[0]["preuve"] = {}
    elif cause == "preuve_empreinte":
        clotures[0]["preuve"]["empreinte_source"] = "0" * 64
    elif cause == "preuve_chantier":
        preuve = clotures[0]["preuve"]
        preuve["alerte"]["preuve"]["wct_id"] = "autre-chantier-fictif"
        preuve["empreinte_source"] = b.empreinte(preuve["alerte"])
    # Le fingerprint du plan concorde encore : le refus porte sur sa preuve réelle.
    clotures[0]["empreinte_suivi"] = b.empreinte(plans[0])
    avant = copy.deepcopy((plans, clotures))
    with pytest.raises(ValueError):
        _pure(plans, clotures)
    assert (plans, clotures) == avant


def _plan(ident="suivi-fictif-A", ouverture=DEBUT):
    alerte = {"evenement_id": "alerte-fictive", "metric_id": "m8_ecart_duree_pct",
              "type_alerte": "MESURE-SEUIL-FRANCHI", "quoi": "Durée fictive", "a_qui": "m04-field-ops",
              "pourquoi": "Seuil fictif", "source": "M4/M3 fictifs", "horodatage_reference": DEBUT,
              "preuve": {"metric_id": "m8_ecart_duree_pct", "wct_id": "wct-fictif",
                         "valeur": "100.00", "unite": "pourcentage", "sens": "au_dessus",
                         "seuil": "50.00", "version_definition": "a" * 64}}
    return {"schema": 1, "suivi_id": ident, "statut": "planifiee", "action": "Revue fictive " + ident,
            "responsable_id": "responsable-fictif", "echeance": "2026-10-10T09:00:00-04:00",
            "source": {"evenement_id": alerte["evenement_id"], "empreinte_source": b.empreinte(alerte),
                       "alerte": alerte, "nature": "historique_recue", "couverture": "non_evaluee"},
            "decision": {"demande_id": ident, "decide_par": "proprietaire-fictif",
                         "decide_role": "nathan_owner", "decide_le": ouverture}}


def _cloture(plan, instant=FIN):
    return {"schema": 1, "suivi_id": plan["suivi_id"], "statut": "cloturee_par_revue_humaine",
            "empreinte_suivi": b.empreinte(plan), "preuve": copy.deepcopy(plan["source"]),
            "bilan": "Revue humaine fictive, sans attestation terrain.",
            "decision": {"demande_id": "cloture-" + plan["suivi_id"], "decide_par": "proprietaire-fictif",
                         "decide_role": "nathan_owner", "decide_le": instant}}


def test_bornes_exclusives_et_instants_equivalents_sans_fuite_future():
    a = _plan("A", "2026-10-04T20:00:00-04:00")  # égal au début en UTC
    bplan = _plan("B", "2026-10-11T20:00:00-04:00")  # égal à fin, exclu
    c = _plan("C", "2026-10-01T00:00:00Z")
    d = _plan("D", "2026-10-01T00:00:00Z")
    clotures = [_cloture(a, "2026-10-11T20:00:00-04:00"), _cloture(c, DEBUT),
                _cloture(d, "2026-10-04T23:59:59Z")]
    plans = [bplan, d, c, a]
    avant = copy.deepcopy((plans, clotures))
    bilan = _pure(plans, clotures, budget_caracteres=20000)
    assert bilan["compteurs"] == {"ouverts_periode": 1, "clotures_periode": 1, "ouverts_fin": 1}
    assert [r["suivi"]["suivi_id"] for r in bilan["suivis"]] == ["C", "A"]
    avant_debut, a_fin = bilan["suivis"]
    assert avant_debut["cloture"] == clotures[1] and avant_debut["cloture_dans_periode"] is True
    assert a_fin["ouvert_fin"] is True and "cloture" not in a_fin
    assert (plans, clotures) == avant


def test_pagination_au_moins_trois_pages_compteurs_globaux_et_vue():
    plans = [_plan(str(i)) for i in range(8)]
    avant = copy.deepcopy(plans)
    def taille(obj):
        return len(json.dumps(obj, ensure_ascii=False, allow_nan=False))

    budget = max(taille(_pure([p], budget_caracteres=20000)) for p in plans) + 200
    page = _pure(plans, budget_caracteres=budget)
    vue = page["vue"]
    assert len(vue) == 64 and int(vue, 16) >= 0
    lignes, pages = [], 0
    while True:
        pages += 1
        assert taille(page) <= budget
        assert page["vue"] == vue and page["total"] == 8
        assert page["compteurs"] == {"ouverts_periode": 8, "clotures_periode": 0, "ouverts_fin": 8}
        assert page["affichees"] == len(page["suivis"])
        assert page["reste"] == 8 - page["depart"] - page["affichees"]
        lignes.extend(page["suivis"])
        if page["prochain_depart"] is None:
            break
        assert page["prochain_depart"] == page["depart"] + page["affichees"]
        page = _pure(plans, depart=page["prochain_depart"], vue_attendue=vue, budget_caracteres=budget)
    assert pages >= 3
    assert [r["suivi"] for r in lignes] == plans and plans == avant
    assert all(r["empreinte_suivi"] == b.empreinte(r["suivi"]) for r in lignes)
    assert _pure(plans, depart=8, vue_attendue=vue)["suivis"] == []
    with pytest.raises(ValueError):
        _pure(plans, depart=1)
    for jeu, kw in [(plans, {"vue_attendue": "0" * 64}),
                    (plans, {"fin": "2026-10-13T00:00:00Z", "vue_attendue": vue}),
                    (copy.deepcopy(plans), {"vue_attendue": vue})]:
        if jeu is not plans:
            jeu[-1]["action"] = "Autre revue fictive, total inchangé"
        with pytest.raises(ValueError):
            _pure(jeu, depart=1, **kw)
    future = [_cloture(plans[0], "2026-10-14T00:00:00Z")]
    with pytest.raises(ValueError):
        _pure(plans, future, depart=1, vue_attendue=vue)
    for donnees in ([], plans):
        with pytest.raises(ValueError):
            _pure(donnees, budget_caracteres=1)


@pytest.mark.parametrize("arguments", [
    {"debut": "2026-10-05"}, {"fin": "2026-10-12T00:00:00"},
    {"debut": "illisible"}, {"debut": FIN}, {"debut": "2026-10-13T00:00:00Z"},
    {"depart": True}, {"depart": -1}, {"depart": 2},
    {"vue_attendue": "invalide"}, {"budget_caracteres": 0}, {"budget_caracteres": True},
])
def test_arguments_invalides_refuses_sans_mutation(arguments):
    plans = [_plan()]
    avant = copy.deepcopy(plans)
    with pytest.raises(ValueError):
        _pure(plans, **arguments)
    assert plans == avant


@pytest.mark.parametrize("cause", [
    "plan_double", "orpheline", "cloture_double", "empreinte", "date_plan_naive", "date_cloture_naive",
    "cloture_avant_ouverture", "meme_demande", "demande_plan_discordante", "signature_vide",
    "schema_booleen", "statut_terrain", "bilan_vide", "preuve_absente",
])
def test_incoherences_hors_periode_refusees_avant_filtre(cause):
    plans = [_plan(ouverture="2026-11-01T00:00:00Z")]
    clotures = [_cloture(plans[0], "2026-11-02T00:00:00Z")]
    if cause == "plan_double":
        plans.append(copy.deepcopy(plans[0]))
    elif cause == "orpheline":
        clotures[0]["suivi_id"] = "inconnu-fictif"
    elif cause == "cloture_double":
        clotures.append(copy.deepcopy(clotures[0]))
    elif cause == "empreinte":
        clotures[0]["empreinte_suivi"] = "0" * 64
    elif cause == "date_plan_naive":
        plans[0]["decision"]["decide_le"] = "2026-11-01T00:00:00"
        clotures[0]["empreinte_suivi"] = b.empreinte(plans[0])
    elif cause == "date_cloture_naive":
        clotures[0]["decision"]["decide_le"] = "2026-11-02T00:00:00"
    elif cause == "cloture_avant_ouverture":
        clotures[0]["decision"]["decide_le"] = FIN
    elif cause == "meme_demande":
        clotures[0]["decision"]["demande_id"] = plans[0]["suivi_id"]
    elif cause == "demande_plan_discordante":
        plans[0]["decision"]["demande_id"] = "autre-fictive"
        clotures[0]["empreinte_suivi"] = b.empreinte(plans[0])
    elif cause == "signature_vide":
        clotures[0]["decision"]["decide_par"] = " "
    elif cause == "schema_booleen":
        plans[0]["schema"] = True
        clotures[0]["empreinte_suivi"] = b.empreinte(plans[0])
    elif cause == "statut_terrain":
        clotures[0]["statut"] = "action_terrain_executee"
    elif cause == "bilan_vide":
        clotures[0]["bilan"] = " "
    elif cause == "preuve_absente":
        clotures[0].pop("preuve")
    avant = copy.deepcopy((plans, clotures))
    with pytest.raises(ValueError):
        _pure(plans, clotures)
    assert (plans, clotures) == avant


def test_lecture_native_revalide_admin_sql_sans_aucune_ecriture(installation, monkeypatch):
    cap, _ = _preparer_natif(installation, monkeypatch)
    assert NOM in cap.index, "M9_BILAN_PERIODE_CAPACITE_ABSENTE"
    assert _lire(cap)["compteurs"]["ouverts_fin"] == 1
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, b.PROPRIO.personne, "admin")
    avant = b._tables()
    for acteur in [b.PROPRIO, contexte.IdentiteAppelante(b.RESPONSABLE, "employee")]:
        with contexte.appele_par_appareil(acteur):
            resultat = cap.appeler(NOM, {"debut": DEBUT, "fin": FIN})
        assert resultat.get("ok") is False, resultat
    assert b._tables() == avant
