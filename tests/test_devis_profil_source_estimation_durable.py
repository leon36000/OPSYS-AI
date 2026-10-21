"""FICTITIOUS native profile: same-lead estimation source and draft replay.

SQLite business integration, not a Core authentication or PostgreSQL concurrency
qualification. The source remains optional for other preparatory drafts.
"""
from __future__ import annotations

import copy
import hashlib
import json
from decimal import Decimal

import pytest
from m2_revenue_crm import assignation, readiness
from m2_revenue_crm import outils as m2
from m3_estimation import devis
from m3_estimation import outils as m3
from sqlalchemy import select
from tests.test_estimation_readiness_m2_durable import (
    ADMIN,
    H3,
    OWNER,
    PROFILE,
    _accepted,
    preparer_m2_m3,
)

from opsys import admission_agents, agents, identite, liaison_cibles
from opsys.stockage.schema import EVENEMENTS_SORTANTS


@pytest.fixture
def profil_devis(session, monkeypatch):
    return preparer_m2_m3(
        session, monkeypatch, outils_profil=("m3_estimer_projet", "m3_creer_devis"),
    )


def _instantane(session):
    with session() as cnx:
        values = {
            "m2": list(m2._obtenir_registre().lire()),
            "estimations": list(m3.registre_production().lire()),
            "devis": list(m3.registre_devis_production()),
            "bus": [dict(row) for row in cnx.execute(select(EVENEMENTS_SORTANTS)
                    .order_by(EVENEMENTS_SORTANTS.c.evenement_id)).mappings()],
        }
    return {
        name: {"count": len(rows), "sha256": hashlib.sha256(json.dumps(
            rows, ensure_ascii=False, sort_keys=True, default=str,
        ).encode()).hexdigest()}
        for name, rows in values.items()
    }


def _autorite_valide(session, prep):
    with session() as cnx:
        assert identite.personne_active(cnx, ADMIN) is not None
        assert identite.personne_active(cnx, OWNER) is not None
        profile = agents.obtenir(cnx, PROFILE)
        assert profile["actif"] is True
        assert profile["revision"] == prep["profile"]["revision"]
        for contract in prep["contracts"].values():
            assert assignation.proprietaire_du_lead(
                m2._obtenir_registre(), contract["lead_id"],
            ) == OWNER
        for tool in ("m3_estimer_projet", "m3_creer_devis"):
            admission = admission_agents.verifier_outil_generique_runtime(
                cnx, PROFILE, prep["deps"], "opsys_m3__" + tool, profile["revision"],
            )
            assert admission["autorise"] is True, admission


def test_profil_devis_lie_source_exacte_rejeu_et_refus_autre_lead(session, profil_devis):
    prep = profil_devis
    lead_a = prep["contracts"]["A"]["lead_id"]
    lead_b = prep["contracts"]["B"]["lead_id"]
    # Both M2 leads exist before this read: unrelated M2 writes change its global anchor.
    marker = _accepted(prep["device"]("m2_evaluer_readiness", {
        "lead_id": lead_a, "horodatage": H3,
    }, "quote-marker-A-fictif", reading=True))["resultat"]
    with session():
        assert readiness.verifier_marqueur(marker, m2._obtenir_registre()) is True
    _autorite_valide(session, prep)

    def appeler(tool, arguments, ticket=None):
        return prep["cap3"].appeler_profil_runtime(
            tool, arguments, None, ticket, profile_id=PROFILE,
            profile_revision=prep["profile"]["revision"], server="opsys_m3",
        )

    estimation = _accepted(appeler("m3_estimer_projet", {
        "contrat": prep["contracts"]["A"], "marqueur": marker,
        "photos": [{"photo_id": "photo-devis-fictive", "resolution_largeur": 3000,
                    "resolution_hauteur": 2000, "eclairage": 7, "angle": "face",
                    "reference_echelle": {"type": "porte", "dimensions_connues": True}}],
        "seuils": {"resolution_minimale": 1000, "eclairage_minimal": 4},
        "bareme": {"version": "2026.1-fictif", "unite": "pi2", "postes": {
            "ravalement": {"cout_unitaire_min": 8.0, "cout_unitaire_max": 14.0}}},
        "quantite": 1200, "plancher_rentable": 9000, "graine": 42,
    }))["estimation"]
    assert estimation["lead_id"] == lead_a
    source_hash = estimation["hash_maillon"]
    with session():
        source = [row for row in m3.registre_production().lire()
                  if row["hash_maillon"] == source_hash]
        assert len(source) == 1
        assert source[0]["charge"]["lead_id"] == lead_a
        assert source[0]["charge"]["devis_id"] == estimation["devis_id"]
    arguments = {
        "devis_id": estimation["devis_id"], "lead_id": lead_a, "chantier_id": None,
        "estimation_source_hash": source_hash, "horodatage": H3,
        "lignes": [{"description": "Travaux préparatoires FICTIFS", "quantite": "2",
                    "unite": "pi2", "cout_unitaire": "10.00", "reference_besoin_materiau": None}],
        "taux_marge": "0.20", "prix_total": "24.00",
    }
    def ticket(arguments, label):
        # Real M10 linkage and host-issued opaque authority; never bypass target policy.
        avant = _instantane(session)
        alias = "opsys-agent-" + PROFILE
        with session() as cnx:
            issued = liaison_cibles.emettre_ticket(
                cnx, departement="m03-estimation", agent_id=alias,
                cle_session=f"agent:{alias}:webchat:direct:readiness-{label.lower()}-fictif",
                affaire_id=arguments["lead_id"], origine_affaire="session",
                outil="m3_creer_devis", arguments=arguments,
            )
        assert _instantane(session) == avant
        return liaison_cibles.TicketMeta(issued["ticket"])

    # Draft lines are explicit inputs, not a claim that Monte-Carlo quantities are final.
    before = _instantane(session)
    quote = _accepted(appeler("m3_creer_devis", arguments, ticket(arguments, "A")))["resultat"]
    after = _instantane(session)
    assert quote["devis_id"] == estimation["devis_id"]
    assert quote["lead_id"] == lead_a and quote["estimation_source_hash"] == source_hash
    assert quote["statut"] == "brouillon"
    assert Decimal(str(quote["prix_total"])) == Decimal("24.00")
    assert after["devis"]["count"] == before["devis"]["count"] + 1
    for name in ("m2", "estimations", "bus"):
        assert after[name] == before[name]

    # A fresh target ticket forces business replay, rather than a cached ticket reply.
    replay = _accepted(appeler(
        "m3_creer_devis", copy.deepcopy(arguments), ticket(arguments, "A"),
    ))["resultat"]
    assert replay == quote
    assert _instantane(session) == after
    _autorite_valide(session, prep)
    marker_b = _accepted(prep["device"]("m2_evaluer_readiness", {
        "lead_id": lead_b, "horodatage": H3,
    }, "quote-marker-B-fictif", reading=True))["resultat"]
    # A valid B target/ticket is reachable: reusing existing devis_id A would be
    # correctly refused by target issuance before reaching the source-hash guard.
    foreign = {
        **arguments, "lead_id": lead_b,
        "devis_id": devis.deriver_devis_id(lead_b, marker_b["empreinte"]),
    }
    refused = appeler("m3_creer_devis", foreign, ticket(foreign, "B"))
    assert refused["ok"] is True, refused
    assert refused["resultat"]["accepte"] is False, refused
    assert refused["resultat"]["verdict"]["code"] == "REJ-CONTRAT-INVALIDE"
    assert "estimation_source_hash" in refused["resultat"]["verdict"]["detail"]
    assert _instantane(session) == after
    _autorite_valide(session, prep)
