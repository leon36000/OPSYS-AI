"""M2-C1, de bout en bout : un carnet de douze leads FICTIFS aux défauts variés (voir `filet_carnet.py`), les VRAIS
outils,
une horloge INJECTÉE (l'instant de référence est un argument, jamais l'heure de la machine).

Prouvé : le moteur sort EXACTEMENT les bonnes violations, avec leurs raisons ; aucune fausse alerte sur les leads sains
;
l'audit trouve exactement les données abîmées (et les doublons restent signalés, jamais fusionnés) ; le plan de
réparation propose, par urgence, des actions jamais exécutées dont les sensibles demandent l'approbation ; AUCUNE
écriture
dans aucun registre par les lectures ; sans délai déclaré les règles sont non évaluées et le disent ; les délais relus
changent le verdict sans redémarrage. Limites : SQLite, données fictives, aucune horloge réelle."""

from __future__ import annotations

import datetime as dt
import json

import filet_carnet as fc
import pytest
from ventes_aide import ADMIN

FICTIF = True


@pytest.fixture
def carnet(monde):
    fc.semer(monde)
    return monde


def _toutes_les_pages(monde, nom, cle, **plus):
    elements, decalage = [], 0
    while decalage is not None:
        page = monde.accepte(monde.appeler(nom, {"horodatage": fc.MAINT, "decalage": decalage, **plus}, ADMIN))
        elements += page[cle]
        decalage = page["suivant"]
    return elements, page


def test_le_moteur_sort_exactement_les_bonnes_violations_dans_l_ordre(carnet):
    violations, page = _toutes_les_pages(carnet, "m2_scanner_sla", "violations", limite=50)
    assert [(v["regle"], v["lead_id"]) for v in violations] == fc.VIOLATIONS_ATTENDUES
    assert page["total"] == 10 and page["leads_examines"] == 12
    assert [r["etat"] for r in page["regles"]] == ["evaluee"] * 7 and page["regles_non_evaluees"] == []


def test_aucune_fausse_alerte_sur_les_leads_sains(carnet):
    violations, _ = _toutes_les_pages(carnet, "m2_scanner_sla", "violations", limite=50)
    assert {v["lead_id"] for v in violations}.isdisjoint(fc.SAINS)
    assert {v["lead_id"] for v in violations} == {"L05", "L06", "L07", "L08", "L09", "L11"}


def test_chaque_violation_dit_sa_raison_son_seuil_declare_et_depuis_quand(carnet):
    violations, page = _toutes_les_pages(carnet, "m2_scanner_sla", "violations", limite=50)
    par = {(v["regle"], v["lead_id"]): v for v in violations}
    chaud = par[("lead_chaud_non_contacte", "L06")]
    assert chaud["seuil"] == {"cle": "heures_lead_chaud", "valeur": 4}
    assert dt.datetime.fromisoformat(chaud["depuis"]) == dt.datetime.fromisoformat(fc.il_y_a(6)), "ingéré 10 h + 4 h"
    assert chaud["ecoule_heures"] == 6 and "jamais contacté" in chaud["raison"]
    soumission = par[("soumission_non_relancee", "L07")]
    assert soumission["donnee"]["devis_id"] == "devis-L07" and soumission["ecoule_heures"] == 120
    assert par[("plainte_non_escaladee", "L08")]["ecoule_heures"] == 18
    assert par[("tache_en_retard", "L09")]["ecoule_heures"] == 24
    assert (
        par[("lead_sans_proprietaire", "L05")]["ecoule_heures"] == 48
        and par[("lead_sans_proprietaire", "L05")]["seuil"]["cle"] == "heures_assignation"
    )
    structurelle = par[("lead_sans_proprietaire", "L11")]
    assert structurelle["donnee"] == {"structurel": True} and structurelle["seuil"] is None
    assert set(page["enonces"]) <= set(__import__("m2_revenue_crm").sla.REGLES)


def test_les_leads_a_deux_defauts_sont_signales_par_chaque_regle_qui_les_concerne(carnet):
    violations, _ = _toutes_les_pages(carnet, "m2_scanner_sla", "violations", limite=50)
    par_lead = {}
    for v in violations:
        par_lead.setdefault(v["lead_id"], set()).add(v["regle"])
    assert par_lead["L05"] == {"prochaine_action_obligatoire", "lead_sans_proprietaire"}
    assert par_lead["L08"] == {"plainte_non_escaladee", "tache_en_retard"}
    assert par_lead["L11"] == {"prochaine_action_obligatoire", "lead_sans_proprietaire", "photos_non_recues"}
    assert par_lead["L06"] == {"lead_chaud_non_contacte"} and par_lead["L07"] == {"soumission_non_relancee"}


def test_l_audit_trouve_exactement_les_donnees_abimees_et_signale_le_doublon_sans_le_fusionner(carnet):
    anomalies, page = _toutes_les_pages(carnet, "m2_auditer_integrite", "anomalies", limite=50)
    assert sorted(
        (a["controle"], a["lead_id"] if a["controle"] in ("activite_sans_lead", "pipeline_incoherent") else None)
        for a in anomalies
    ) == sorted(fc.ANOMALIES_ATTENDUES)
    assert [c["etat"] for c in page["controles"]] == ["evalue"] * 8
    assert {c["controle"]: c["anomalies"] for c in page["controles"]} == {
        "lead_sans_statut": 0,
        "client_sans_contact": 1,
        "tache_sans_proprietaire": 0,
        "soumission_orpheline": 1,
        "activite_sans_lead": 1,
        "lead_sans_client": 0,
        "pipeline_incoherent": 2,
        "doublon_probable": 0,
    }
    assert sorted(a["nature"] for a in anomalies if a["controle"] == "pipeline_incoherent") == [
        "qualifie_sans_action",
        "qualifie_sans_proprietaire",
    ]
    # L04 et L06 (même ville, mêmes travaux, 2 h d'écart) : signalés à l'ingestion, en attente d'une personne
    assert page["doublons_en_attente"] == 1
    assert [(d["lead_id_a"], d["lead_id_b"], d["signale"], d["arbitrage"]) for d in page["doublons_probables"]] == [
        ("L04", "L06", True, "en_attente")
    ]
    assert all(
        carnet.registre("principal")[i]["type_entree"] != "fusion" for i in range(len(carnet.registre("principal")))
    )


def test_le_plan_de_reparation_propose_par_urgence_et_ne_fait_rien(carnet):
    avant = carnet.instantane()
    cibles, page = _toutes_les_pages(carnet, "m2_planifier_reparations", "plan", limite=30)
    assert carnet.instantane() == avant, "le plan est une lecture : aucune table ne change"
    assert [(c["cible"]["type"], c["cible"]["id"]) for c in cibles][:6] == [
        ("lead", "L08"),
        ("lead", "L06"),
        ("lead", "L05"),
        ("lead", "L11"),
        ("lead", "L07"),
        ("lead", "L09"),
    ]
    assert {(c["cible"]["type"]) for c in cibles[6:]} == {"client", "lead"} and page["total"] == 8
    assert page["execute"] is False
    par = {c["cible"]["id"]: c for c in cibles}
    assert [a["action_id"] for a in par["L08"]["actions"]] == ["escalader_plainte", "faire_ou_replanifier_action"]
    assert all(a["execute"] is False for c in cibles for a in c["actions"])
    # sensible : passe par un outil N3 -> approbation requise ; lecture N0 ou action humaine sans outil -> non
    sensibles = {a["action_id"] for c in cibles for a in c["actions"] if a["approbation_requise"]}
    libres = {a["action_id"] for c in cibles for a in c["actions"] if not a["approbation_requise"]}
    assert {"assigner_proprietaire", "relancer_soumission", "fixer_prochaine_action"} <= sensibles
    assert {"escalader_plainte", "appeler_maintenant", "faire_ou_replanifier_action"} <= libres
    relancer = next(a for a in par["L07"]["actions"] if a["action_id"] == "relancer_soumission")
    assert (relancer["outil"], relancer["niveau"]) == ("m2_preparer_relance", "N3")


def test_la_prochaine_meilleure_action_existante_accompagne_chaque_lead_du_plan(carnet):
    cibles, _ = _toutes_les_pages(carnet, "m2_planifier_reparations", "plan", limite=30)
    par = {c["cible"]["id"]: c for c in cibles if c["cible"]["type"] == "lead"}
    assert par["L06"]["prochaine_action_suggeree"]["regle"] == "doublon_en_attente", "le doublon d'abord"
    assert par["L05"]["prochaine_action_suggeree"]["regle"] == "assigner_owner"
    assert par["L08"]["prochaine_action_suggeree"]["regle"] == "suivre_paiement"
    assert par["L13"]["prochaine_action_suggeree"] is None, "un lead inconnu n'a pas de suggestion"


def test_aucune_ecriture_dans_aucun_registre_par_les_trois_lectures(carnet):
    avant = carnet.instantane()
    registres = {
        n: carnet.registre(n)
        for n in (
            "principal",
            "relances_preparees",
            "devis_envoyes_recus",
            "satisfactions_recues",
            "consentements_contact",
            "profils_propriete",
        )
    }
    for nom in ("m2_scanner_sla", "m2_auditer_integrite", "m2_planifier_reparations"):
        carnet.accepte(carnet.appeler(nom, {"horodatage": fc.MAINT}, ADMIN))
        carnet.accepte(carnet.appeler(nom, {"horodatage": fc.MAINT}))
    assert carnet.instantane() == avant
    assert {n: carnet.registre(n) for n in registres} == registres


def test_aucun_message_n_est_envoye_ni_prepare_et_aucune_approbation_n_est_creee(carnet):
    avant = carnet.instantane()
    for nom in ("m2_scanner_sla", "m2_auditer_integrite", "m2_planifier_reparations"):
        carnet.accepte(carnet.appeler(nom, {"horodatage": fc.MAINT}))
    apres = carnet.instantane()
    for table in ("approbations", "evenements_sortants", "evenements_recus"):
        assert apres[table] == avant[table], table
    assert carnet.registre("relances_preparees") == []


def test_les_sorties_ne_portent_aucune_donnee_personnelle(carnet):
    texte = ""
    for nom in ("m2_scanner_sla", "m2_auditer_integrite", "m2_planifier_reparations"):
        pages, _ = _toutes_les_pages(
            carnet,
            nom,
            {"m2_scanner_sla": "violations", "m2_auditer_integrite": "anomalies", "m2_planifier_reparations": "plan"}[
                nom
            ],
            limite=30,
        )
        texte += json.dumps(pages, ensure_ascii=False)
    for personnel in ("Client L", "Injoignable", "example.test", "418-555", "@", "Appel fait au client"):
        assert personnel not in texte


def test_sans_delai_declare_les_regles_a_delai_sont_non_evaluees_et_le_plan_le_dit(carnet):
    carnet.configurer()  # le vrai manifeste est vide
    violations, page = _toutes_les_pages(carnet, "m2_scanner_sla", "violations", limite=50)
    assert {(v["regle"], v["lead_id"]) for v in violations} == {
        ("prochaine_action_obligatoire", "L11"),
        ("lead_sans_proprietaire", "L11"),
    }, "seules les incohérences immédiates"
    etats = {r["regle"]: r["etat"] for r in page["regles"]}
    assert sorted(k for k, v in etats.items() if v == "non_evaluee") == sorted(
        [
            "lead_chaud_non_contacte",
            "photos_non_recues",
            "soumission_non_relancee",
            "plainte_non_escaladee",
            "tache_en_retard",
        ]
    )
    assert sorted(page["regles_non_evaluees"]) == sorted(k for k, v in etats.items() if v == "non_evaluee")
    plan = carnet.accepte(carnet.appeler("m2_planifier_reparations", {"horodatage": fc.MAINT}))
    assert len(plan["regles_non_evaluees"]) == 5


@pytest.mark.parametrize(
    "cle,regle",
    [
        ("heures_lead_chaud", "lead_chaud_non_contacte"),
        ("heures_demande_photos", "photos_non_recues"),
        ("heures_relance_soumission", "soumission_non_relancee"),
        ("heures_escalade_plainte", "plainte_non_escaladee"),
        ("heures_retard_tolerance", "tache_en_retard"),
        ("heures_assignation", "lead_sans_proprietaire"),
        ("heures_premiere_action", "prochaine_action_obligatoire"),
    ],
)
def test_retirer_un_seul_delai_rend_exactement_sa_regle_non_evaluee_et_epargne_les_autres(carnet, cle, regle):
    carnet.configurer(sla={k: v for k, v in fc.FICTIF_SLA.items() if k != cle})
    violations, page = _toutes_les_pages(carnet, "m2_scanner_sla", "violations", limite=50)
    etats = {r["regle"]: r["etat"] for r in page["regles"]}
    assert etats[regle] in ("non_evaluee", "partielle")
    assert [r for r, e in etats.items() if e != "evaluee"] == [regle]
    attendues = [(r, lead) for r, lead in fc.VIOLATIONS_ATTENDUES if r != regle or etats[regle] == "partielle"]
    if etats[regle] == "partielle":  # seule la partie sans délai (donnée abîmée L11) reste
        attendues = [(r, lead) for r, lead in fc.VIOLATIONS_ATTENDUES if r != regle or lead == "L11"]
    assert [(v["regle"], v["lead_id"]) for v in violations] == attendues


def test_les_delais_relus_a_chaque_appel_changent_le_verdict_sans_redemarrage(carnet):
    carnet.configurer(sla={**fc.FICTIF_SLA, "heures_lead_chaud": 5})
    v, _ = _toutes_les_pages(carnet, "m2_scanner_sla", "violations", limite=50)
    assert ("lead_chaud_non_contacte", "L06") in [(x["regle"], x["lead_id"]) for x in v]  # 10 h > 5 h
    carnet.configurer(sla={**fc.FICTIF_SLA, "heures_lead_chaud": 10})
    v, _ = _toutes_les_pages(carnet, "m2_scanner_sla", "violations", limite=50)
    assert ("lead_chaud_non_contacte", "L06") not in [(x["regle"], x["lead_id"]) for x in v], "pile à 10 h : tenu"
    carnet.configurer(sla={**fc.FICTIF_SLA, "heures_lead_chaud": 9})
    v, _ = _toutes_les_pages(carnet, "m2_scanner_sla", "violations", limite=50)
    assert ("lead_chaud_non_contacte", "L06") in [(x["regle"], x["lead_id"]) for x in v]


def test_un_instant_plus_tot_ne_voit_pas_les_violations_futures_un_instant_plus_tard_en_voit_davantage(carnet):
    def total(instant):
        page = carnet.accepte(carnet.appeler("m2_scanner_sla", {"horodatage": instant, "limite": 1}, ADMIN))
        return page["total"]

    assert total(fc.il_y_a(24)) < total(fc.MAINT) < total(fc.il_y_a(-200))
