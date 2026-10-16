"""Local-only fixture for the Core -> real Python target ticket HTTP test."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from m2_revenue_crm import ingestion
from m2_revenue_crm import registre as registre_m2
from m10_memoire import liaison as liaison_m10
from m10_memoire import registre as registre_m10

from opsys import approbations, identite, stockage
from opsys.departements import charger_departements, tous_les_outils

LEAD_ID = "LEAD-CORE-C02"
SESSION_KEY = "agent:m02-revenue-crm:webchat:direct:core-c02"
M3_SESSION_KEY = "agent:m03-estimation:webchat:direct:core-c02-n4"
M3_QUOTE_ID = "DEV-CORE-C02-N4"
M3_REVOKED_QUOTE_ID = "DEV-CORE-C02-N4-REVOKED"
TIMESTAMP = "2026-09-30T12:00:00+00:00"
M9 = "m09-strategic-intelligence"
M9_SESSION_KEY = "agent:m09-strategic-intelligence:webchat:direct:core-m9-fictif"
M9_RESPONSIBLE = "responsable-core-m9-fictif"
M9_OPEN = "m9_ouvrir_suivi_decision"
M9_TOOLS = (M9_OPEN, "m9_preparer_suivi_decision", "m9_lire_suivi_decision")


def _m9_source(suffix: str) -> dict:
    """Fictive M3/M4 inputs; their actual M8 publication and M10 receipts are mandatory."""
    return {
        "fictif": True,
        "devis": {
            "devis_id": "devis-core-m9-fictif-" + suffix,
            "lead_id": "lead-core-m9-fictif-" + suffix, "chantier_id": None,
            "lignes": [{"reference_ligne": "ligne-fictive", "description": "Gouttières fictives",
                        "quantite": "40", "unite": "pi", "prix_unitaire": "15.00",
                        "prix_ligne": "600.00", "reference_besoin_materiau": None}],
            "cout_total": "480.00", "prix_total": "600.00", "taux_marge": "0.25",
            "duree_estimee_minutes": "60", "horodatage_acceptation": "2026-09-20T09:00:00-04:00",
        },
        "wct": {
            "wct_id": "wct-core-m9-fictif-" + suffix,
            "intervention_id": "intervention-core-m9-fictive-" + suffix,
            "lead_id": "lead-core-m9-fictif-" + suffix, "technicien_id": M9_RESPONSIBLE,
            "horodatage_completion": "2026-09-27T15:00:00-04:00",
            "fix_gps_completion": {"latitude": 45.75, "longitude": -73.5},
            "duree_reelle_minutes": 120, "ecart_signale": False, "revue_id": None,
            "hash_maillon": "preuve-terrain-core-fictive-" + suffix,
            "consommateurs_cibles": ["M8", "M10"],
            "devis_id": "devis-core-m9-fictif-" + suffix, "statut": "completed_verified",
        },
    }


def _link_m9(suffix: str) -> None:
    with stockage.transaction():
        line, refused = liaison_m10.lier_session_affaire(
            M9_SESSION_KEY, "lead-core-m9-fictif-" + suffix, "nathan-fixture",
            "admin", "appareil", "Liaison Core M9 fictive", TIMESTAMP,
            registre_m10.Registre(maillons=stockage.maillons("m10-memoire", "affaires")),
        )
        if refused is not None or line is None:
            raise RuntimeError(f"canonical M9 affair link refused: {refused!r}")


def prepare_m9() -> None:
    import yaml
    from m8_analytics import outils as outils_m8
    from m9_strategic_intelligence.encodage import empreinte

    from opsys import evenements, openclaw

    prepare()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, M9_RESPONSIBLE, "Responsable fictif",
                                "mot-de-passe-responsable-core-fictif", ["employee"])
    manifest = Path(os.environ["OPSYS_HOME"]) / "m8-seuil-core-fictif.yaml"
    manifest.write_text(yaml.safe_dump({"configuration": {
        "seuils_alerte": {"m8_ecart_duree_pct": {"sens": "au_dessus", "valeur": 50}},
    }}), encoding="utf-8")
    manifest.chmod(0o600)
    # Process-local fixture override; no repository manifest or live provider is modified.
    outils_m8._MANIFESTE = manifest
    departments = charger_departements(Path(__file__).resolve().parents[2] / "departments")
    active = {name: departments[name] for name in ("m08-analytics", M9, "m10-memoire")}
    for suffix in ("A", "B"):
        source = _m9_source(suffix)
        assert source["fictif"] is True
        evenements.publier("m3.devis_accepte", "m03-estimation", source["devis"])
        evenements.publier("m4.travaux_termines", "m04-field-ops", source["wct"],
                           evenement_id=source["wct"]["wct_id"])
    for _ in range(3):
        result = evenements.repartir(active, maintenant="2026-09-27T20:00:00+00:00")
        assert result["echecs"] == result["quarantaines"] == 0, result
    arguments = {}
    with stockage.transaction():
        for suffix in ("A", "B"):
            [alert] = [a for a in stockage.maillons(M9, "alertes_m8")
                       if a["preuve"].get("wct_id") == "wct-core-m9-fictif-" + suffix]
            assert alert["type_alerte"] == "MESURE-SEUIL-FRANCHI"
            assert alert["preuve"]["valeur"] == "100.00"
            arguments[suffix] = {
                "evenement_id": alert["evenement_id"], "empreinte_source": empreinte(alert),
                "action": "Revoir les causes de durée du chantier fictif",
                "responsable_id": M9_RESPONSIBLE, "echeance": "2026-10-20T09:00:00-04:00",
            }
    _link_m9("A")
    generated = openclaw._configuration_contexte(departments, {M9: []}, [M9])
    assert generated is not None
    print(json.dumps({
        "fictif": True, "session_key": M9_SESSION_KEY,
        "affairs": {suffix: "lead-core-m9-fictif-" + suffix for suffix in ("A", "B")},
        "arguments": arguments,
        "generated_context": {
            "agent": generated["agents"][M9],
            "niveaux": {name: generated["niveaux"][name] for name in M9_TOOLS},
            "cibles": {name: generated["cibles"][name] for name in M9_TOOLS
                       if name in generated["cibles"]},
        },
    }))


def inspect_m9() -> None:
    from sqlalchemy import func, select

    from opsys.stockage.schema import LIAISONS_TICKETS, META

    with stockage.transaction() as cnx:
        owner = identite.personne_active(cnx, "nathan-fixture")
        owner_active = owner is not None and {"admin", "nathan_owner"} <= owner.roles
        link = liaison_m10.liaison_courante(
            M9_SESSION_KEY,
            registre_m10.Registre(maillons=stockage.maillons("m10-memoire", "affaires")),
        )
        requests = [{"id": d["id"], "status": d["statut"]}
                    for d in approbations.lister(cnx) if d["outil"] == M9_OPEN]
        followups = list(stockage.maillons(M9, "suivi_decisions"))
        tickets = int(cnx.execute(select(func.count()).select_from(LIAISONS_TICKETS)).scalar_one())
        snapshot = {name: sorted(json.dumps(dict(row), sort_keys=True, default=str)
                                 for row in cnx.execute(select(table)).mappings())
                    for name, table in META.tables.items()}
    print(json.dumps({
        "owner_active": owner_active, "linked_affair": link["affaire_id"] if link else None,
        "requests": requests, "followups": followups, "tickets": tickets,
        "tables_digest": hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest(),
    }))


def refuse_m9_approval(request_id: str) -> None:
    from opsys import liaison_cibles

    try:
        approve(request_id)
    except liaison_cibles.CibleRefusee as error:
        with stockage.transaction() as cnx:
            owner = identite.personne_active(cnx, "nathan-fixture")
            assert owner is not None and {"admin", "nathan_owner"} <= owner.roles
        assert any(word in str(error) for word in ("révoquée", "remplacée"))
        print(json.dumps({"refused": True, "reason": str(error), "owner_active": True}))
    else:
        raise RuntimeError("stale M9 approval unexpectedly succeeded")


def prepare() -> None:
    stockage.migrer()
    contrat = {
        "lead_id": LEAD_ID,
        "conversation_id": "CONV-CORE-C02",
        "contact": {"nom": "Client fictif", "telephone": "555-0101", "courriel": "x@example.test"},
        "type_travaux": "renovation_totale",
        "ville": "Québec",
        "urgence_declaree": False,
        "canal": "telephone",
    }
    registre = registre_m2.Registre()
    _, refus = ingestion.ingerer(contrat, registre, TIMESTAMP)
    if refus is not None:
        raise RuntimeError("synthetic M2 lead fixture was refused")
    with stockage.transaction() as cnx:
        identite.creer_personne(
            cnx,
            "nathan-fixture",
            "Nathan Fixture",
            "synthetic-password-never-used-1234",
            ["admin", "nathan_owner"],
        )
        stockage.maillons("m02-revenue-crm", "principal").extend(registre.lire())
        affaires = registre_m10.Registre(maillons=stockage.maillons("m10-memoire", "affaires"))
        lien, refus = liaison_m10.lier_session_affaire(
            SESSION_KEY,
            LEAD_ID,
            "nathan-fixture",
            "admin",
            "appareil",
            "liaison de test synthétique",
            TIMESTAMP,
            affaires,
        )
    if refus is not None or lien is None:
        raise RuntimeError(f"synthetic M10 case link fixture was refused: {refus!r}")


def revoke() -> None:
    with stockage.transaction():
        affaires = registre_m10.Registre(maillons=stockage.maillons("m10-memoire", "affaires"))
        courant = liaison_m10.liaison_courante(SESSION_KEY, affaires)
        if courant is None:
            raise RuntimeError("expected an active synthetic M10 link")
        _, refus = liaison_m10.revoquer_session_affaire(
            SESSION_KEY,
            courant["ligne_id"],
            "nathan-fixture",
            "admin",
            "appareil",
            "révocation de test synthétique",
            "2026-09-30T12:01:00+00:00",
            affaires,
        )
    if refus is not None:
        raise RuntimeError("synthetic M10 link revocation was refused")


def prepare_m3() -> None:
    """Seed one canonical M3 draft and a seller-linked M10 session for the N4 HTTP scenario."""
    prepare()
    from m3_estimation import outils as outils_m3

    from opsys import approbations
    from opsys.outils import executer_atomique

    outil_creation = next(outil for outil in outils_m3.outils() if outil.nom == "m3_creer_devis")
    for devis_id in (M3_QUOTE_ID, M3_REVOKED_QUOTE_ID):
        resultat = executer_atomique(
            outil_creation,
            {
                "devis_id": devis_id,
                "lead_id": LEAD_ID,
                "chantier_id": None,
                "lignes": [
                    {
                        "description": "Travaux synthétiques de test",
                        "quantite": "1",
                        "unite": "forfait",
                        "cout_unitaire": "100.00",
                        "reference_besoin_materiau": None,
                    }
                ],
                "taux_marge": "0.20",
                "horodatage": TIMESTAMP,
            },
        )
        if not resultat.get("ok") or not resultat.get("resultat", {}).get("accepte"):
            raise RuntimeError("synthetic M3 quote fixture was refused")

    with stockage.transaction() as cnx:
        identite.creer_personne(
            cnx,
            "seller-fixture",
            "Seller Fixture",
            "synthetic-password-never-used-5678",
            ["seller"],
        )
        affaires = registre_m10.Registre(maillons=stockage.maillons("m10-memoire", "affaires"))
        lien, refus = liaison_m10.lier_session_affaire(
            M3_SESSION_KEY,
            LEAD_ID,
            "nathan-fixture",
            "admin",
            "appareil",
            "liaison M3 de test synthétique",
            TIMESTAMP,
            affaires,
        )
        approbations.fixer_mode(cnx, "m03-estimation", "autonome", "nathan-fixture")
    if refus is not None or lien is None:
        raise RuntimeError(f"synthetic M3 M10 link fixture was refused: {refus!r}")


def inspect_m3() -> None:
    from m3_estimation import outils as outils_m3
    from sqlalchemy import func, select

    from opsys import approbations
    from opsys.stockage.schema import LIAISONS_TICKETS

    with stockage.transaction() as cnx:
        statuses = {}
        for devis_id in (M3_QUOTE_ID, M3_REVOKED_QUOTE_ID):
            devis, verdict = outils_m3.devis_durable.lire_devis(
                outils_m3.registre_devis_production(), devis_id
            )
            if verdict is not None or devis is None:
                raise RuntimeError("synthetic M3 quote could not be read")
            statuses[devis_id] = devis["statut"]
        demandes = [
            demande
            for demande in approbations.lister(cnx)
            if demande["outil"] == "m3_demander_envoi_devis"
            and demande["arguments"].get("devis_id") in (M3_QUOTE_ID, M3_REVOKED_QUOTE_ID)
        ]
        tickets = int(cnx.execute(select(func.count()).select_from(LIAISONS_TICKETS)).scalar_one())
    print(json.dumps({
        "quote_statuses": statuses,
        "requests": [{"status": d["statut"], "devis_id": d["arguments"]["devis_id"]} for d in demandes],
        "tickets": tickets,
    }))


def revoke_seller_role() -> None:
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, "seller-fixture", "seller")


def inspect_state() -> None:
    with stockage.transaction():
        principal = registre_m2.Registre(maillons=stockage.maillons("m02-revenue-crm", "principal"))
        interactions = [
            maillon
            for maillon in principal.lire()
            if maillon.get("type_entree") == "interaction" and maillon.get("lead_id") == LEAD_ID
        ]
        cases = registre_m10.Registre(maillons=stockage.maillons("m10-memoire", "affaires"))
        linked = liaison_m10.liaison_courante(SESSION_KEY, cases) is not None
    print(json.dumps({"interactions": len(interactions), "linked": linked}))


def approve(demande_id: str) -> None:
    departements = charger_departements()
    outils = {nom: outil for nom, (_, outil) in tous_les_outils(departements.values()).items()}
    with stockage.transaction() as cnx:
        decision = approbations.decider(
            cnx,
            demande_id,
            True,
            "nathan-fixture",
            outils,
            departements,
            "approbation synthétique du test d'intégration",
            role="nathan_owner",
        )
    print(json.dumps({
        "statut": decision.get("statut"),
        "reponse": decision.get("reponse"),
    }))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=("prepare", "prepare-m3", "prepare-m9", "switch-m9-b", "inspect-m9",
                 "refuse-m9-approval", "revoke", "inspect", "inspect-m3", "revoke-seller-role", "approve"),
    )
    parser.add_argument("--request-id")
    args = parser.parse_args()
    command = args.command
    if command == "prepare":
        prepare()
    elif command == "prepare-m3":
        prepare_m3()
    elif command == "prepare-m9":
        prepare_m9()
    elif command == "switch-m9-b":
        _link_m9("B")
    elif command == "inspect-m9":
        inspect_m9()
    elif command == "refuse-m9-approval":
        if not args.request_id:
            raise RuntimeError("refuse-m9-approval requires the synthetic request id")
        refuse_m9_approval(args.request_id)
    elif command == "revoke":
        revoke()
    elif command == "inspect":
        inspect_state()
    elif command == "inspect-m3":
        inspect_m3()
    elif command == "revoke-seller-role":
        revoke_seller_role()
    else:
        if not args.request_id:
            raise RuntimeError("approve requires the synthetic request id")
        approve(args.request_id)


if __name__ == "__main__":
    main()
