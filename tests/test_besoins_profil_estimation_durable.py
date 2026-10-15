"""FICTITIOUS profile → M3 source → M6 needs → human acceptance → reservation.

SQLite business integration and native N5 backend, not Core authentication,
physical material measurement, external purchases, or PostgreSQL HTTP qualification.
"""
from __future__ import annotations

import copy
import json

import pytest
from m2_revenue_crm import assignation
from m2_revenue_crm import outils as m2
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

from opsys import admission_agents, agents, approbations, evenements, identite, liaison_cibles, stockage
from opsys.capacites import outils_executables
from opsys.stockage import codec
from opsys.stockage.schema import APPROBATIONS, EVENEMENTS_RECUS, EVENEMENTS_SORTANTS, REGISTRES

M6 = "m06-material-control"
SKU = "revetement-fictif"
VIS = "Vis fictives"
OUTILS_PROFIL = ("m3_estimer_projet", "m3_creer_devis", "m3_marquer_devis_accepte")


@pytest.fixture
def flux(session, monkeypatch):
    return preparer_m2_m3(session, monkeypatch, outils_profil=OUTILS_PROFIL)


def _lignes(session, table, *conditions):
    with session() as cnx:
        rows = cnx.execute(select(table).where(*conditions)).mappings().all()
    return sorted((dict(row) for row in rows), key=lambda row: json.dumps(row, default=str, sort_keys=True))


def _registres(session, departement):
    return _lignes(session, REGISTRES, REGISTRES.c.departement == departement)


def _autorite(session, prep):
    with session() as cnx:
        assert identite.personne_active(cnx, ADMIN) is not None
        assert identite.personne_active(cnx, OWNER) is not None
        profile = agents.obtenir(cnx, PROFILE)
        assert profile["actif"] is True
        assert profile["revision"] == prep["profile"]["revision"]
        for tool in OUTILS_PROFIL:
            assert admission_agents.verifier_outil_generique_runtime(
                cnx, PROFILE, prep["deps"], "opsys_m3__" + tool, profile["revision"],
            )["autorise"] is True
        for contract in prep["contracts"].values():
            assert assignation.proprietaire_du_lead(m2._obtenir_registre(), contract["lead_id"]) == OWNER


def test_profil_estimation_livre_besoins_sources_sans_achat_et_rejoue_sans_doublon(session, flux):
    prep = flux
    lead = prep["contracts"]["A"]["lead_id"]
    marker = _accepted(prep["device"]("m2_evaluer_readiness", {
        "lead_id": lead, "horodatage": H3,
    }, "besoins-readiness-fictive", reading=True))["resultat"]
    arguments = {
        "contrat": prep["contracts"]["A"], "marqueur": marker,
        "photos": [{"photo_id": "materiaux-fictifs", "resolution_largeur": 3000,
                    "resolution_hauteur": 2000, "eclairage": 7, "angle": "face",
                    "reference_echelle": {"type": "porte", "dimensions_connues": True}}],
        "seuils": {"resolution_minimale": 1000, "eclairage_minimal": 4},
        "bareme": {"version": "besoins-fictifs-v1", "unite": "pi2", "postes": {
            "ravalement": {"cout_unitaire_min": 8.0, "cout_unitaire_max": 14.0,
                           "materiaux": [
                               {"materiau": "Revêtement fictif", "sku": SKU, "quantite_par_unite": "1",
                                "unite": "pi2", "facteur_perte": "0.08"},
                               {"materiau": VIS, "quantite_par_unite": "0.25", "unite": "boite"},
                           ]}}},
        "quantite": 40, "plancher_rentable": 1, "graine": 42,
    }

    def appeler(tool, args, ticket=None):
        return prep["cap3"].appeler_profil_runtime(
            tool, args, None, ticket, profile_id=PROFILE,
            profile_revision=prep["profile"]["revision"], server="opsys_m3",
        )

    def estimer(args):
        return appeler("m3_estimer_projet", args)

    _autorite(session, prep)
    resultat = _accepted(estimer(arguments))
    besoins = resultat["besoins_materiaux"]
    estimation = resultat["estimation"]
    assert besoins["lead_id"] == estimation["lead_id"] == lead
    assert besoins["devis_id"] == estimation["devis_id"]
    assert besoins["estimation_id"] == estimation["hash_maillon"]
    with session():
        sources = [row for row in m3.registre_production().lire()
                   if row["hash_maillon"] == besoins["estimation_id"]]
    assert len(sources) == 1
    source = sources[0]
    assert source["rang"] == besoins["rang_registre"]
    assert source["charge"]["lead_id"] == lead
    assert source["charge"]["devis_id"] == besoins["devis_id"]
    assert source["charge"]["besoins_materiaux"]["lignes"] == besoins["lignes"]
    assert [(line.get("sku", line["materiau"]), line["quantite_estimee"], line["unite"])
            for line in besoins["lignes"]] == [(SKU, "40", "pi2"), (VIS, "10", "boite")]
    assert besoins["facteurs_perte_absents"] == [VIS]
    events = _lignes(session, EVENEMENTS_SORTANTS, EVENEMENTS_SORTANTS.c.type_evenement == "m3.besoins_materiaux")
    assert len(events) == 1
    event = events[0]
    assert codec.decoder(event["charge"]) == besoins
    assert not _lignes(session, EVENEMENTS_SORTANTS, EVENEMENTS_SORTANTS.c.type_evenement == "m3.devis_accepte")
    assert _registres(session, M6) == []
    amont = {dep: _registres(session, dep) for dep in ("m02-revenue-crm", "m03-estimation")}

    def livrer():
        return evenements.repartir({M6: prep["deps"][M6]}, maintenant=H3)

    delivery = livrer()
    assert delivery["traites"] == 1 and delivery["echecs"] == delivery["quarantaines"] == 0, delivery
    with session():
        prevus = list(stockage.maillons(M6, "besoins_prevus"))
    assert len(prevus) == 1
    prevu = prevus[0]
    for key in ("devis_id", "lead_id", "estimation_id", "rang_registre", "bareme_version", "niveau_confiance"):
        assert prevu[key] == besoins[key]
    assert prevu["source"] == "estimation_m3" and prevu["chantier_id"] is None
    assert prevu["lignes"] == [
        {"materiau_id": SKU, "quantite_estimee": 40.0, "unite": "pi2"},
        {"materiau_id": VIS, "quantite_estimee": 10.0, "unite": "boite"},
    ]
    assert prevu["detail_lignes"][0]["facteur_perte"] == "0.08"
    assert prevu["facteurs_perte_absents"] == [VIS]
    # Only a provisional need was added. No stock, PO, reservation, or actual usage was attested.
    m6_apres = _registres(session, M6)
    assert len(m6_apres) == 1 and m6_apres[0]["registre"] == "besoins_prevus"
    assert {dep: _registres(session, dep) for dep in amont} == amont

    # Replay the actual producer payload, not a fabricated estimation or WCT.
    with session():
        evenements.publier("m3.besoins_materiaux", "m03-estimation", besoins,
                           evenement_id=event["evenement_id"])
    assert _lignes(
        session, EVENEMENTS_SORTANTS, EVENEMENTS_SORTANTS.c.type_evenement == "m3.besoins_materiaux",
    ) == events
    assert livrer()["livres"] == 0
    with session():
        evenements.publier("m3.besoins_materiaux", "m03-estimation", besoins,
                           evenement_id="besoins-retransmission-fictive")
    assert livrer()["traites"] == 1
    receipts = _lignes(session, EVENEMENTS_RECUS,
                      EVENEMENTS_RECUS.c.evenement_id == "besoins-retransmission-fictive",
                      EVENEMENTS_RECUS.c.consommateur == M6)
    assert len(receipts) == 1 and receipts[0]["statut"] == "traite"
    assert codec.decoder(receipts[0]["resultat"])["statut"] == "deja_recu"
    assert _registres(session, M6) == m6_apres

    # A still-authorized profile cannot invent the missing material unit.
    invalid = copy.deepcopy(arguments)
    del invalid["bareme"]["postes"]["ravalement"]["materiaux"][0]["unite"]
    before_refusal = {dep: _registres(session, dep) for dep in (*amont, M6)}
    before_events = _lignes(session, EVENEMENTS_SORTANTS)
    refusal = estimer(invalid)
    assert refusal["ok"] is True and refusal["resultat"]["accepte"] is False, refusal
    assert refusal["resultat"]["etape"] == "besoins_materiaux"
    assert "unite" in refusal["resultat"]["verdict"]["detail"]
    assert {dep: _registres(session, dep) for dep in before_refusal} == before_refusal
    assert _lignes(session, EVENEMENTS_SORTANTS) == before_events
    _autorite(session, prep)

    # Continue the SAME native source into an actual accepted quote, never publish a
    # fabricated m3.devis_accepte. The human signer is separate from seller/profile.
    signataire = "signataire.materiaux.fictif"
    with session() as cnx:
        identite.creer_personne(cnx, signataire, "Signataire FICTIF",
                               "mot-de-passe-signataire-fictif", ["nathan_owner"])

    def ticket_cible(tool, args):
        alias = "opsys-agent-" + PROFILE
        with session() as cnx:
            issued = liaison_cibles.emettre_ticket(
                cnx, departement="m03-estimation", agent_id=alias,
                cle_session=f"agent:{alias}:webchat:direct:readiness-a-fictif",
                affaire_id=lead, origine_affaire="session", outil=tool, arguments=args,
            )
        return liaison_cibles.TicketMeta(issued["ticket"])

    quote_args = {
        "devis_id": besoins["devis_id"], "lead_id": lead, "chantier_id": lead,
        "estimation_source_hash": besoins["estimation_id"], "horodatage": H3,
        "lignes": [
            {"description": "Revêtement fictif", "quantite": "40", "unite": "pi2",
             "cout_unitaire": "8.00", "reference_besoin_materiau": SKU},
            {"description": VIS, "quantite": "10", "unite": "boite",
             "cout_unitaire": "2.00", "reference_besoin_materiau": VIS},
        ],
        "taux_marge": "0.25",
    }
    quote = _accepted(appeler(
        "m3_creer_devis", quote_args, ticket_cible("m3_creer_devis", quote_args),
    ))["resultat"]
    assert quote["statut"] == "brouillon" and quote["estimation_source_hash"] == besoins["estimation_id"]
    accept_args = {"devis_id": besoins["devis_id"], "approbateur": signataire, "horodatage": H3}
    pending = appeler(
        "m3_marquer_devis_accepte", accept_args, ticket_cible("m3_marquer_devis_accepte", accept_args),
    )
    assert pending["statut"] == "en_attente_approbation", pending
    with session() as cnx:
        assert cnx.scalar(select(APPROBATIONS.c.niveau).where(
            APPROBATIONS.c.id == pending["demande_id"],
        )) == "N5"
    assert not _lignes(session, EVENEMENTS_SORTANTS, EVENEMENTS_SORTANTS.c.type_evenement == "m3.devis_accepte")
    assert _registres(session, M6) == m6_apres
    executable = outils_executables(prep["deps"], session)
    before_decision = {dep: _registres(session, dep) for dep in (*amont, M6)}
    before_decision_events = _lignes(session, EVENEMENTS_SORTANTS)
    with pytest.raises(ValueError, match="attestation"), session() as cnx:
        approbations.decider(cnx, pending["demande_id"], True, signataire, executable, prep["deps"])
    assert {dep: _registres(session, dep) for dep in before_decision} == before_decision
    assert _lignes(session, EVENEMENTS_SORTANTS) == before_decision_events
    with session() as cnx:
        decision = approbations.decider(
            cnx, pending["demande_id"], True, signataire, executable, prep["deps"],
            attestation={"nom": "Signataire fictif", "profession": "Représentant client fictif",
                         "reference_document": "acceptation-materiaux-fictive"},
        )
    assert decision["statut"] == "executee", decision
    accepted_events = _lignes(
        session, EVENEMENTS_SORTANTS, EVENEMENTS_SORTANTS.c.type_evenement == "m3.devis_accepte",
    )
    assert len(accepted_events) == 1
    accepted_quote = codec.decoder(accepted_events[0]["charge"])
    assert accepted_quote["devis_id"] == besoins["devis_id"]
    assert accepted_quote["lead_id"] == lead and accepted_quote["chantier_id"] == lead
    assert accepted_quote["estimation_source_hash"] == besoins["estimation_id"]
    delivery = livrer()
    assert delivery["traites"] == 1 and delivery["echecs"] == delivery["quarantaines"] == 0, delivery
    with session():
        needs = list(stockage.maillons(M6, "besoins_prevus"))
        reservations = list(stockage.maillons(M6, "reservations"))
        assert list(stockage.maillons(M6, "principal")) == []
        assert list(stockage.maillons(M6, "bons_commande")) == []
    assert len(needs) == 2 and needs[0] == prevu
    assert needs[1]["devis_id"] == besoins["devis_id"] and needs[1]["chantier_id"] == lead
    assert len(reservations) == 1
    reservation = reservations[0]
    assert reservation["devis_id"] == besoins["devis_id"] and reservation["chantier_id"] == lead
    assert reservation["actif"] is True and reservation["revision"] == 1
    assert reservation["lignes"] == [
        {"materiau_id": SKU, "unite": "pi2", "quantite_besoin": "40", "quantite_reservee": "0"},
        {"materiau_id": VIS, "unite": "boite", "quantite_besoin": "10", "quantite_reservee": "0"},
    ]
    ready_events = _lignes(
        session, EVENEMENTS_SORTANTS, EVENEMENTS_SORTANTS.c.type_evenement == "m6.materiel_pret",
    )
    assert len(ready_events) == 1
    ready = codec.decoder(ready_events[0]["charge"])
    assert ready["devis_id"] == besoins["devis_id"] and ready["chantier_id"] == lead
    assert ready["statut"] == "a_commander" and ready["reservation_active"] is True
    assert [(line["materiau_id"], line["quantite_manquante"]) for line in ready["lignes_manquantes"]] == [
        (SKU, "40"), (VIS, "10"),
    ]
    final_m6 = _registres(session, M6)
    assert livrer()["livres"] == 0
    with session():
        evenements.publier("m3.devis_accepte", "m03-estimation", accepted_quote,
                           evenement_id="devis-materiaux-retransmission-fictive")
    replay = livrer()
    assert replay["traites"] == 1 and replay["echecs"] == replay["quarantaines"] == 0, replay
    assert _registres(session, M6) == final_m6
    assert _lignes(
        session, EVENEMENTS_SORTANTS, EVENEMENTS_SORTANTS.c.type_evenement == "m6.materiel_pret",
    ) == ready_events
    _autorite(session, prep)
