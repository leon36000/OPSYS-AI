"""Current canonical M2 readiness before durable M3 estimation.

These tests exercise public profiled capability, generic atomic tool execution,
and the internal durable wrapper. Direct calls do not prove Core authentication.
All identities, leads, photos and amounts are FICTITIOUS.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from collections.abc import Mapping
from pathlib import Path

import pytest
from m2_revenue_crm import assignation, readiness, statuts
from m2_revenue_crm import outils as m2
from m3_estimation import outils as m3
from m10_memoire import liaison, registre
from sqlalchemy import select

from opsys import admission_agents, agents, approbations, contexte, idempotence, identite, stockage
from opsys.capacites import Capacites
from opsys.departements import charger_departements
from opsys.outils import executer_atomique
from opsys.stockage.schema import EVENEMENTS_SORTANTS

FICTIF = True
# Source tests discover the repository normally; only the isolated Q prototype needs env.
RACINE = (
    Path(__file__).resolve().parents[1]
    if Path(__file__).resolve().parent.name == "tests"
    else Path(os.environ["OPSYS_READINESS_TEST_SOURCE"])
)
ADMIN = "readiness.admin.fictif"
OWNER = "readiness.vendeur.fictif"
PROFILE = "readiness-durable-fictif"
H0 = "2026-10-15T08:00:00-04:00"
H1 = "2026-10-15T08:01:00-04:00"
H2 = "2026-10-15T08:02:00-04:00"
H3 = "2026-10-15T08:03:00-04:00"
H4 = "2026-10-15T08:04:00-04:00"


def _accepted(response):
    assert isinstance(response, Mapping), response
    assert response.get("ok", True) is True, response
    assert response.get("statut") != "en_attente_approbation", response
    body = response.get("resultat", response) if "ok" in response else response
    assert isinstance(body, Mapping) and body.get("accepte") is True, response
    return body


def _refused(outcome):
    """Accept established named business refusals without fixing one transport shape."""
    if "exception" in outcome:
        return outcome["exception"]["type"] in {"ValueError", "PermissionError"} and bool(
            outcome["exception"]["detail"].strip()
        )
    response = outcome["response"]
    if not isinstance(response, Mapping):
        return False
    if response.get("ok") is False:
        # Generic executor converts native business exceptions into this named channel.
        return response.get("erreur") == "refus_metier" and bool(str(response.get("details", "")).strip())
    body = response.get("resultat", response) if "ok" in response else response
    if not isinstance(body, Mapping) or body.get("accepte") is not False:
        return False
    verdict = body.get("verdict")
    return isinstance(verdict, Mapping) and isinstance(verdict.get("code"), str) and bool(verdict["code"].strip())


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def _effects(session):
    with session() as cnx:
        entries = list(m3.registre_production().lire())
        events = [dict(row) for row in cnx.execute(
            select(EVENEMENTS_SORTANTS).order_by(EVENEMENTS_SORTANTS.c.evenement_id)
        ).mappings()]
    return {"m3_count": len(entries), "m3_sha256": _digest(entries),
            "events_count": len(events), "events_sha256": _digest(events), "m3_entries": entries}


def preparer_m2_m3(session, monkeypatch, *, outils_profil=("m3_estimer_projet",)):
    """Native reusable preparation; default preserves the PG bootstrap contract."""
    monkeypatch.setenv("OPSYS_EVENEMENTS_REPARTITEUR", "0")
    deps = charger_departements(RACINE / "departments")
    m2.utiliser_stockage_durable()
    cap2 = Capacites(deps, session, filtre={"m02-revenue-crm"}, memoire=False)
    cap3 = Capacites(deps, session, filtre={"m03-estimation"}, appelant="m03-estimation", memoire=False)
    with session() as cnx:
        identite.creer_personne(cnx, ADMIN, "Admin FICTIF", "mot-de-passe-readiness-fictif-admin", ["admin"])
        identite.creer_personne(cnx, OWNER, "Vendeur FICTIF", "mot-de-passe-readiness-fictif-vendeur", ["seller"])
        approbations.fixer_mode(cnx, "m03-estimation", "autonome", ADMIN)
        agents.creer(cnx, deps, {
            "id": PROFILE, "departement": "m03-estimation", "responsabilite": "Readiness durable FICTIVE.",
            "palier_modele": "standard", "outils": list(outils_profil),
            "budget_jour": 200000, "budget_mois": 200000, "limite_tours": 4,
            "limite_reessais": 1, "limite_concurrence": 1, "declencheurs": [{"type": "manuel"}],
        }, par=ADMIN, mutation_id="readiness-create-fictif")
        agents.definir_actif(cnx, PROFILE, deps, True, par=ADMIN,
                            mutation_id="readiness-active-fictif", revision_attendue=1)
        admission_agents.configurer_plafonds_entreprise(cnx, 500000, 5000000, par=ADMIN, revision_attendue=0)
        profile = agents.obtenir(cnx, PROFILE)
    records = []

    def device(name, arguments, key, *, reading=False):
        with contexte.appele_par_appareil(contexte.IdentiteAppelante(personne=ADMIN, role="admin")):
            response = cap2.appeler(name, arguments, None if reading else idempotence.Meta(
                cle=key, appareil="readiness-fictif-device", horodatage_appareil=H4,
            ))
        records.append({"tool": name, "arguments": arguments, "response": response})
        return response

    contracts = {}
    for label in ("A", "B"):
        lead = "lead-readiness-" + label.lower() + "-fictif"
        contract = {
            "lead_id": lead, "conversation_id": "conv-" + lead,
            "contact": {"nom": "Client " + label + " FICTIF", "courriel": label.lower() + "@example.test"},
            "type_travaux": "ravalement", "ville": "Québec", "urgence_declaree": False, "canal": "telephone",
        }
        response = executer_atomique(cap2.index["m2_ingerer_lead"][1], {"contrat": contract, "horodatage": H0})
        _accepted(response)
        records.append({"tool": "m2_ingerer_lead", "arguments": contract, "response": response})
        _accepted(device("m2_transitionner_statut", {
            "lead_id": lead, "statut_cible": "qualifie", "horodatage": H1, "owner": OWNER,
            "prochaine_action": {"description": "Visite FICTIVE", "echeance": "2026-10-16T08:00:00-04:00"},
        }, "qualifier-" + label))
        _accepted(device("m2_enregistrer_interaction", {
            "lead_id": lead, "resume": "Qualification humaine FICTIVE.", "horodatage": H2,
        }, "interaction-" + label))
        with session():
            matches = [row for row in m2._obtenir_registre().lire()
                       if row.get("type_entree") == "lead_ingere" and row.get("lead_id") == lead]
            assert len(matches) == 1
            contracts[label] = copy.deepcopy(matches[0]["contrat"])
        alias = "opsys-agent-" + PROFILE
        session_key = f"agent:{alias}:webchat:direct:readiness-{label.lower()}-fictif"
        with session():
            linked, refusal = liaison.lier_session_affaire(
                session_key, lead, ADMIN, "admin", "appareil", "Liaison de qualification FICTIVE", H2,
                registre.Registre(maillons=stockage.maillons("m10-memoire", "affaires")),
            )
            assert linked and refusal is None, (linked, refusal)
    return {"contracts": contracts, "device": device, "profile": profile, "cap3": cap3,
            "records": records, "deps": deps}


@pytest.fixture
def preparation_m2_m3(session, monkeypatch):
    # PG bootstrap also calls this fixture.__wrapped__(session, monkeypatch).
    return preparer_m2_m3(session, monkeypatch)


def _current(session, contracts, marker_a, marker_b):
    with session() as cnx:
        reg = m2._obtenir_registre()
        return {"A": {"ready": readiness.evaluer(reg, contracts["A"]["lead_id"]),
                      "verified": readiness.verifier_marqueur(marker_a, reg),
                      "status": statuts.statut_courant(reg, contracts["A"]["lead_id"]),
                      "owner": assignation.proprietaire_du_lead(reg, contracts["A"]["lead_id"])},
                "B": {"ready": readiness.evaluer(reg, contracts["B"]["lead_id"]),
                      "verified": readiness.verifier_marqueur(marker_b, reg),
                      "status": statuts.statut_courant(reg, contracts["B"]["lead_id"]),
                      "owner": assignation.proprietaire_du_lead(reg, contracts["B"]["lead_id"])},
                "head": reg.tete(), "admin_active": identite.personne_active(cnx, ADMIN) is not None,
                "owner_active": identite.personne_active(cnx, OWNER) is not None}


CASES = [(seam, scenario) for seam in ("direct", "atomic", "profile")
         for scenario in ("fresh", "stale", "forged")] + [("profile", "mismatched")]


@pytest.mark.parametrize(("seam", "scenario"), CASES)
def test_estimation_requires_current_m2_readiness(session, preparation_m2_m3, seam, scenario):
    prep = preparation_m2_m3
    contracts, device = prep["contracts"], prep["device"]
    marker_a = _accepted(device("m2_evaluer_readiness", {
        "lead_id": contracts["A"]["lead_id"], "horodatage": H3,
    }, "marker-A", reading=True))["resultat"]
    with session():
        assert readiness.verifier_marqueur(marker_a, m2._obtenir_registre()) is True
    if scenario == "stale":
        _accepted(device("m2_transitionner_statut", {
            "lead_id": contracts["A"]["lead_id"], "statut_cible": "perdu", "horodatage": H4,
            "motif": "Dossier clos sur demande FICTIVE",
        }, "perdu-A"))
    # M2 has ONE GLOBAL anchor. B is emitted after any write invalidating A.
    marker_b = _accepted(device("m2_evaluer_readiness", {
        "lead_id": contracts["B"]["lead_id"], "horodatage": H4,
    }, "marker-B", reading=True))["resultat"]
    before_m2 = _current(session, contracts, marker_a, marker_b)
    assert before_m2["admin_active"] and before_m2["owner_active"]
    assert before_m2["A"]["owner"] == before_m2["B"]["owner"] == OWNER
    assert before_m2["B"]["ready"] is True and before_m2["B"]["verified"] is True
    assert before_m2["A"]["ready"] is (scenario != "stale")
    assert before_m2["A"]["verified"] is (scenario != "stale")
    with session() as cnx:
        admitted = admission_agents.verifier_outil_generique_runtime(
            cnx, PROFILE, prep["deps"], "opsys_m3__m3_estimer_projet", prep["profile"]["revision"],
        )
        assert admitted["autorise"] is True
        assert agents.obtenir(cnx, PROFILE)["actif"] is True
    contract = contracts["A"] if scenario in {"stale", "mismatched"} else contracts["B"]
    marker = copy.deepcopy(marker_a if scenario == "stale" else marker_b)
    if scenario == "forged":
        marker["empreinte"] = ("0" if marker["empreinte"][0] != "0" else "1") + marker["empreinte"][1:]
        with session():
            assert readiness.evaluer(m2._obtenir_registre(), contract["lead_id"]) is True
            assert readiness.verifier_marqueur(marker, m2._obtenir_registre()) is False
    if scenario == "mismatched":
        assert marker["lead_id"] != contract["lead_id"]
        assert before_m2["A"]["ready"] is True and before_m2["A"]["verified"] is True
    arguments = {
        "contrat": contract, "marqueur": marker,
        "photos": [{"photo_id": "photo-fictive", "resolution_largeur": 3000, "resolution_hauteur": 2000,
                    "eclairage": 7, "angle": "face",
                    "reference_echelle": {"type": "porte", "dimensions_connues": True}}],
        "seuils": {"resolution_minimale": 1000, "eclairage_minimal": 4},
        "bareme": {"version": "2026.1-fictif", "unite": "pi2", "postes": {
            "ravalement": {"cout_unitaire_min": 8.0, "cout_unitaire_max": 14.0}}},
        "quantite": 1200, "plancher_rentable": 9000, "graine": 42,
    }
    before = _effects(session)
    try:
        if seam == "direct":
            response = m3.estimer_projet(**arguments)
        elif seam == "atomic":
            response = executer_atomique(prep["cap3"].index["m3_estimer_projet"][1], arguments)
        else:
            response = prep["cap3"].appeler_profil_runtime(
                "m3_estimer_projet", arguments, None, None, profile_id=PROFILE,
                profile_revision=prep["profile"]["revision"], server="opsys_m3",
            )
        outcome = {"response": response}
    except (ValueError, PermissionError) as exc:
        outcome = {"exception": {"type": type(exc).__name__, "detail": str(exc)}}
    after = _effects(session)
    after_m2 = _current(session, contracts, marker_a, marker_b)
    evidence = {"fictif": True, "seam": seam, "scenario": scenario, "m2_before": before_m2,
                "m2_after": after_m2, "before_effects": before, "after_effects": after,
                "outcome": outcome, "arguments": arguments, "native_m2_calls": prep["records"]}
    output_dir = os.environ.get("OPSYS_READINESS_ORACLE_OUTPUT_DIR")
    if output_dir:
        (Path(output_dir) / f"{seam}-{scenario}.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2, default=str)
        )
    assert before_m2 == after_m2, "Estimation mutated M2 or its authority."
    assert before["events_sha256"] == after["events_sha256"], "Unexpected publication."
    if scenario == "fresh":
        assert "response" in outcome, outcome
        _accepted(outcome["response"])
        assert after["m3_count"] == before["m3_count"] + 1
        assert after["m3_entries"][-1]["charge"]["lead_id"] == contract["lead_id"]
    else:
        assert _refused(outcome), ("CURRENT_M2_READINESS_REQUIRED", seam, scenario, outcome)
        assert after["m3_sha256"] == before["m3_sha256"], "Refusal must leave M3 unchanged."
