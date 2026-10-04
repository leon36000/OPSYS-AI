"""Local-only fixture for the Core -> real Python target ticket HTTP test."""

from __future__ import annotations

import argparse
import json

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
        choices=("prepare", "prepare-m3", "revoke", "inspect", "inspect-m3", "revoke-seller-role", "approve"),
    )
    parser.add_argument("--request-id")
    args = parser.parse_args()
    command = args.command
    if command == "prepare":
        prepare()
    elif command == "prepare-m3":
        prepare_m3()
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
