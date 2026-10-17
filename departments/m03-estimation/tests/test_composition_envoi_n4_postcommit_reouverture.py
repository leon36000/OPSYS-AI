"""Composition M3 : la réponse d'une approbation N4 d'envoi est perdue APRÈS le COMMIT, puis un NOUVEAU processus.

Risque utilisateur (aucun défaut produit affirmé) : après une coupure réseau/CLI, le propriétaire (ou l'agent) renvoie
un devis déjà approuvé. Reconstruire l'état d'un processus neuf ne doit ni ajouter un second envoi, ni changer
l'instant réel de l'approbation, ni publier un second `m3.devis_envoye`, ni faire partir la relance CRM de M2 d'une
date inventée plus tardive.

Deux processus OS réels (`envoi_n4_process_fixture.py`) sur la même base SQLite :

- A : devis sourcé (readiness M2 -> estimation -> devis), demande N4 par `Capacites.appeler` avec ticket de session
  M10, approbation du propriétaire par l'app dans un `stockage.transaction` externe. Le COMMIT est vu par une connexion
  indépendante `mode=ro` AVANT que la réponse de décision soit perdue, hors transaction ; A s'arrête (code connu).
- B : identité de processus distincte, API reconstruites ; à un instant T1 strictement plus tardif (horloge canonique
  des approbations, attente bornée, jamais remplacée), rejeu de la demande d'origine (même ticket, mêmes arguments) et
  de la décision d'origine ; livraison réelle à M2 par le répartiteur, deux fois ; puis un devis B neuf, approuvé
  légitimement par le même propriétaire, porte T1.

Les preuves fermées (même processus, PG6, cold9, native7) ne sont pas rouvertes. Pas de livraison au client, de
fournisseur, de crash OS ni de fsync. Le contrôle négatif mute une COPIE jetable : sensibilité de l'oracle seulement.
Données FICTIVES.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))

import envoi_n4_process_fixture as processus  # noqa: E402

from opsys import approbations_appareil  # noqa: E402
from opsys.stockage import codec  # noqa: E402

FICTIF = True
DEP, M2 = processus.DEP, processus.M2


@pytest.fixture(scope="module")
def scenario(tmp_path_factory):
    return processus.executer_scenario(tmp_path_factory.mktemp("envoi-n4-postcommit"))


def _faits_m2(etat, devis_id):
    return [m for m in processus.maillons(etat, M2, "devis_envoyes_recus") if m.get("devis_id") == devis_id]


def test_reponse_n4_perdue_apres_commit_nouveau_processus_garde_t0_lignee_et_un_seul_fait_m2(scenario):
    obs, oracle = scenario, scenario["oracle"]
    t0 = oracle["t0"]
    t0_dt = dt.datetime.fromisoformat(t0)
    assert t0_dt.tzinfo is not None
    devis_a, lead_a = oracle["devis_id"], oracle["lead_id"]

    # 1. A est un vrai processus enfant ; son COMMIT est vu par le témoin indépendant `mode=ro` AVANT la perte.
    a_id = obs["a_demarre"]
    assert a_id["pid"] != os.getpid() and a_id["ticks"] is not None
    assert (obs["a_sortie"]["pid"], obs["a_sortie"]["ticks"]) == (a_id["pid"], a_id["ticks"])
    assert a_id["ticks"] == obs["a_ticks_parent"] == obs["a_ticks_avant_perte"]
    assert obs["a_sortie"]["connexion_ouverte"] is False and obs["uri_temoin"] == "mode=ro"
    avant = obs["a_demande"]["devis_avant"]
    assert (avant["statut"], avant["prix_total"], avant["estimation_source_hash"]) == (
        "brouillon", "5400.00", oracle["source_hash"])
    approbation = oracle["approbation"]
    assert (approbation["statut"], approbation["decide_par"], approbation["decide_role"], approbation["niveau"]) == (
        "executee", "proprio", "nathan_owner", "N4")
    reponse = json.loads(approbation["resultat"])
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True
    envoi = reponse["resultat"]["resultat"]
    assert (envoi["devis_id"], envoi["statut"], envoi["horodatage_envoi"], envoi["deja_envoye"]) == (
        devis_a, "envoye", t0, False)
    [creation] = [m for m in oracle["lignes_devis_a"] if m.get("statut") != "envoye"]
    [transition] = [m for m in oracle["lignes_devis_a"] if m.get("statut") == "envoye"]
    assert (creation["lead_id"], creation["estimation_source_hash"]) == (lead_a, oracle["source_hash"])
    assert (transition["horodatage"], transition["envoi_approuve_par"], transition["envoi_approuve_role"]) == (
        t0, "proprio", "nathan_owner")
    assert [m["charge"]["lead_id"] for m in processus.maillons(obs["etat_avant"], DEP, "principal")
            if m.get("hash_maillon") == oracle["source_hash"]] == [lead_a]
    assert oracle["outbox_a"]["producteur"] == DEP
    assert processus.charge(oracle["outbox_a"]) == {
        "devis_id": devis_a, "lead_id": lead_a, "chantier_id": None, "horodatage_envoi": t0}
    assert oracle["ticket_a"]["statut"] == "consomme" and json.loads(oracle["ticket_a"]["reponse"]) == reponse

    # 2. Perte nommée, hors transaction, après la sortie réussie du `with` ; A fermé avec son code connu et EOF.
    assert {k: v for k, v in obs["a_perte"].items() if k != "etape"} == {
        "type": "ReponsePerdueApresCommit", "connexion_ouverte": False}
    assert obs["a_rc"] == processus.EXIT_REPONSE_PERDUE
    assert obs["a_ticks_apres_fin"] != a_id["ticks"]
    assert processus.controler_cible_a(obs["etat_apres_a"], oracle, livre=False) == []

    # 3. B : autre processus OS, même base, même propriétaire toujours actif et légitime.
    b_id = obs["b_demarre"]
    assert (b_id["pid"], b_id["ticks"]) != (a_id["pid"], a_id["ticks"]) and b_id["ticks"] == obs["b_ticks_parent"]
    depot = processus.RACINE_DEPOT
    for source in (a_id["source"], b_id["source"]):
        assert Path(source["opsys"]).is_relative_to(depot / "src") and Path(source["m3"]).is_relative_to(depot)
    assert obs["b_reconstruit"]["proprietaire_actif"] is True
    assert {"admin", "nathan_owner"} <= set(obs["b_reconstruit"]["roles"])

    # 4. À T1 > T0 : la demande d'origine rejoue la réponse enregistrée, la décision d'origine est DEJA_DECIDEE.
    rejeux = obs["b_rejeux"]
    assert dt.datetime.fromisoformat(rejeux["t_rejeu"]) > t0_dt
    assert rejeux["rejeu"] == {**reponse, "rejoue": True}, "aucun accusé inventé : la réponse commise, rejouée"
    redecision = rejeux["redecision"]
    assert redecision["resultat"] is None
    verdict = redecision["verdict"]
    assert (verdict["code"], verdict["statut"], verdict["decide_par"], verdict["decide_le"]) == (
        approbations_appareil.DEJA_DECIDEE, "executee", "proprio", t0)
    assert rejeux["devis_a"] == {**avant, "statut": "envoye", "horodatage": t0, "envoi_approuve_par": "proprio",
                                 "envoi_approuve_role": "nathan_owner"}
    etat = obs["etat_apres_rejeux"]
    assert processus.controler_cible_a(etat, oracle, livre=False) == []
    assert etat["approbations"] == oracle["prefixe"]["approbations"], "aucune nouvelle demande ni décision"
    assert etat["evenements_sortants"] == oracle["prefixe"]["evenements_sortants"]
    journal_t0 = max((j["id"] for j in oracle["prefixe"]["journal"]), default=0)
    audit_a = [j for j in etat["journal"] if j["id"] > journal_t0 and j["cible"] == oracle["demande_id"]]
    assert not [j for j in audit_a if j["action"] in {"approbation.approuver", "approbation.refuser"}]

    # 5. Le vrai répartiteur livre l'envoi d'origine au consommateur durable de M2 ; la seconde passe ne livre rien.
    repartitions = obs["b_repartitions"]
    premiere, seconde = repartitions["premiere"], repartitions["seconde"]
    assert premiere["traites"] >= 1 and (premiere["echecs"], premiere["quarantaines"]) == (0, 0)
    assert seconde["livres"] == 0
    oracle_client = repartitions["client_a"]
    assert oracle["client_id"] is None and oracle_client is None
    etat = obs["etat_apres_repartitions"]
    assert processus.controler_cible_a(etat, oracle, livre=True) == []
    assert _faits_m2(etat, devis_a) == [{
        "devis_id": devis_a, "lead_id": lead_a, "chantier_id": None, "horodatage_envoi": t0,
        "client_id": oracle_client}]
    [recu] = [r for r in etat["evenements_recus"] if r["evenement_id"] == oracle["evenement_a"]]
    assert codec.decoder(recu["resultat"]) == {
        "traite": True, "lead_id": lead_a, "devis_id": devis_a, "client_id": oracle_client, "horodatage_envoi": t0}

    # 6. Positif légitime : devis B neuf, mêmes contrats N4/ticket, même propriétaire, approuvé à T1 > T0.
    b = obs["b_devis_b"]
    assert b["devis_id"] != devis_a and b["demande"]["demande_id"] != oracle["demande_id"] and b["ticket_distinct"]
    assert b["source_hash"] != oracle["source_hash"]
    assert b["verdict"] is None
    resultat_b = b["resultat"]
    assert (resultat_b["statut"], resultat_b["decide_par"], resultat_b["role"], resultat_b["issue"]) == (
        "executee", "proprio", "nathan_owner", {"ok": True, "accepte": True})
    t1 = resultat_b["decide_le"]
    t1_dt = dt.datetime.fromisoformat(t1)
    assert t1_dt.tzinfo is not None and t1_dt > t0_dt
    assert (b["devis_b"]["statut"], b["devis_b"]["horodatage"], b["devis_b"]["lead_id"]) == (
        "envoye", t1, processus.LEAD_B)
    etat = obs["etat_b_vivant"]
    assert [r["decide_le"] for r in etat["approbations"] if r["id"] == b["demande"]["demande_id"]] == [t1]
    [sortie_b] = [r for r in etat["evenements_sortants"] if r["evenement_id"] == f"m3-devis-envoye-{b['devis_id']}"]
    assert processus.charge(sortie_b) == {
        "devis_id": b["devis_id"], "lead_id": processus.LEAD_B, "chantier_id": None, "horodatage_envoi": t1}
    # Ajouts légitimes de B (audit, ticket, reçus) séparés ; la cible A reste exactement celle de T0.
    assert processus.controler_cible_a(etat, oracle, livre=True) == []
    assert (b["troisieme"]["echecs"], b["troisieme"]["quarantaines"]) == (0, 0)
    assert _faits_m2(etat, b["devis_id"]) == [{
        "devis_id": b["devis_id"], "lead_id": processus.LEAD_B, "chantier_id": None, "horodatage_envoi": t1,
        "client_id": b["client_b"]}]

    # 7. B s'arrête proprement ; une connexion rouverte après sa fin relit exactement le même état.
    assert obs["b_rc"] == 0 and (obs["b_fin"]["pid"], obs["b_fin"]["ticks"]) == (b_id["pid"], b_id["ticks"])
    assert obs["etat_rouvert"] == obs["etat_b_vivant"]
    assert processus.controler_cible_a(obs["etat_rouvert"], oracle, livre=True) == []


@pytest.mark.parametrize(("mutation", "anomalie"), [
    ("doublon_transition", "A_TRANSITION_ENVOYE_DOUBLE"),
    ("doublon_fait_m2", "M2_FAIT_DOUBLE"),
    ("date_recalculee", "A_DATE_T0"),
    ("lead_recalcule", "A_LEAD"),
])
def test_negatif_copie_jetable_doublon_ou_date_lead_recalcules_est_rejetee(scenario, tmp_path, mutation, anomalie):
    """Sensibilité de l'oracle sur une COPIE jetable (mutation de fixture, jamais une preuve de défaut produit).

    La copie non mutée passe ; chaque mutation est rejetée par la comparaison à l'oracle fixé avant la perte, même
    quand la date ou le lead est réécrit de façon cohérente aux quatre endroits vérifiés."""
    oracle = scenario["oracle"]
    temoin = processus.copie_jetable(scenario["chemin_db"], tmp_path / "temoin-non-mute.db")
    assert processus.controler_cible_a(processus.temoin_lecture_seule(temoin), oracle, livre=True) == []

    copie = processus.copie_jetable(scenario["chemin_db"], tmp_path / f"copie-{mutation}.db")
    processus.muter_copie(copie, oracle, mutation)
    etat = processus.temoin_lecture_seule(copie)
    anomalies = processus.controler_cible_a(etat, oracle, livre=True)

    assert anomalie in anomalies, anomalies
    if mutation.startswith("doublon_"):
        assert "PREFIXE_MODIFIE" not in anomalies, "ajout en fin de registre : seul le comptage par cible le voit"
    if mutation == "date_recalculee":
        dates = processus.dates_internes_a(etat, oracle)
        assert len(dates) == 1 and dates != {oracle["t0"]}, (
            "quatre champs temporels cohérents, différents du T0 fixé avant la perte")
    # La base du scénario n'est jamais touchée par le contrôle négatif.
    assert processus.controler_cible_a(processus.temoin_lecture_seule(scenario["chemin_db"]), oracle, livre=True) == []
