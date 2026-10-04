"""Parcours C02 sur les vraies routes MCP HTTP: ticket privé, outil M3 et approbation N3."""

from __future__ import annotations

import json
import socket
import threading
import time
from pathlib import Path

import anyio
import pytest
import uvicorn
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client
from sqlalchemy import func, select

from opsys import stockage
from opsys.serveur_mcp import application_http_departements

JETON_METIER_C02_HTTP_FICTIF = "jeton-metier-c02-http-fictif-suffisamment-long"
JETON_CONTEXTE_C02_HTTP_FICTIF = "jeton-contexte-c02-http-fictif-distinct-long"
LEAD_C02_HTTP_FICTIF = "LEAD-C02-HTTP-FICTIF"
CLE_SESSION_C02_HTTP_FICTIF = "agent:m03-estimation:webchat:direct:contact-c02-http-fictif"
HORODATAGE_C02_HTTP_FICTIF = "2026-10-02T12:00:00+00:00"
TICKET_CIBLE_META = "opsys/cibleTicket"


@pytest.fixture
def serveur_mcp_c02(session):
    """Même application Uvicorn et transports MCP streamable HTTP que le harnais HTTP existant."""
    from opsys.departements import charger_departements

    departements = charger_departements(Path(__file__).resolve().parents[1] / "departments")
    port = _port_libre()
    app = application_http_departements(
        departements,
        session,
        JETON_METIER_C02_HTTP_FICTIF,
        hote="127.0.0.1",
        jeton_contexte=JETON_CONTEXTE_C02_HTTP_FICTIF,
    )
    serveur = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    fil = threading.Thread(target=serveur.run, daemon=True)
    fil.start()
    for _ in range(100):
        if serveur.started:
            break
        time.sleep(0.05)
    assert serveur.started, "le vrai serveur MCP HTTP de test doit démarrer"
    yield f"http://127.0.0.1:{port}", departements
    serveur.should_exit = True
    fil.join(timeout=5)
    assert not fil.is_alive(), "le serveur MCP HTTP de test doit s'arrêter"


def _port_libre() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _preparer_lead_et_liaison_m10(session) -> None:
    from m2_revenue_crm import ingestion
    from m2_revenue_crm import registre as registre_m2
    from m10_memoire import liaison as liaison_m10
    from m10_memoire import registre as registre_m10

    contrat_fictif = {
        "fictif": True,
        "lead": {
            "lead_id": LEAD_C02_HTTP_FICTIF,
            "conversation_id": "CONV-C02-HTTP-FICTIF",
            "contact": {
                "nom": "Client fictif C02 HTTP",
                "telephone": "555-0102",
                "courriel": "c02-http@example.test",
            },
            "type_travaux": "renovation_totale",
            "ville": "Québec",
            "urgence_declaree": False,
            "canal": "telephone",
        },
    }
    registre_source = registre_m2.Registre()
    accuse, verdict = ingestion.ingerer(contrat_fictif["lead"], registre_source, HORODATAGE_C02_HTTP_FICTIF)
    assert accuse is not None and verdict is None

    with session():
        stockage.maillons("m02-revenue-crm", "principal").extend(registre_source.lire())
        registre_affaires = registre_m10.Registre(maillons=stockage.maillons("m10-memoire", "affaires"))
        lien, refus = liaison_m10.lier_session_affaire(
            CLE_SESSION_C02_HTTP_FICTIF,
            LEAD_C02_HTTP_FICTIF,
            "nathan-fictif-c02-http",
            "admin",
            "appareil",
            "Liaison fictive pour le test d'intégration C02 HTTP.",
            HORODATAGE_C02_HTTP_FICTIF,
            registre_affaires,
        )
    assert lien is not None and refus is None


def _lire_enveloppe(resultat) -> dict:
    assert len(resultat.content) == 1
    assert resultat.content[0].type == "text"
    return json.loads(resultat.content[0].text)


def _arguments_devis(devis_id: str) -> dict:
    return {
        "devis_id": devis_id,
        "lead_id": LEAD_C02_HTTP_FICTIF,
        "chantier_id": None,
        "lignes": [
            {
                "description": "Gouttières fictives C02 HTTP",
                "quantite": "10",
                "unite": "pi_lin",
                "cout_unitaire": "10.00",
                "reference_besoin_materiau": None,
            }
        ],
        "taux_marge": "0.20",
        "horodatage": HORODATAGE_C02_HTTP_FICTIF,
    }


def test_mcp_http_emet_un_ticket_prive_execute_le_vrai_m3_et_refuse_modification_ou_retrait(serveur_mcp_c02, session):
    from m3_estimation import devis_durable
    from m10_memoire import liaison as liaison_m10
    from m10_memoire import registre as registre_m10

    from opsys import approbations, identite
    from opsys.stockage.schema import EVENEMENTS_SORTANTS

    racine, departements = serveur_mcp_c02
    departement_m3 = departements["m03-estimation"]
    outil_creation = next(outil for outil in departement_m3.charger_outils() if outil.nom == "m3_creer_devis")
    _preparer_lead_et_liaison_m10(session)
    arguments = _arguments_devis("DEV-C02-HTTP-FICTIF")
    arguments_retires = _arguments_devis("DEV-C02-HTTP-REVOQUE-FICTIF")

    with session() as cnx:
        approbations.fixer_mode(cnx, departement_m3.id, "ombre", "admin-c02-http-fictif")
        identite.creer_personne(
            cnx,
            "nathan-c02-http-fictif",
            "Nathan fictif C02 HTTP",
            "mot-de-passe-c02-http-fictif-suffisant",
            ["nathan_owner"],
        )
        nombre_m3_avant = len(stockage.maillons("m03-estimation", "devis"))
        nombre_factures_avant = len(stockage.maillons("m05-financecore", "factures"))

    async def scenario():
        url_contexte = f"{racine}/mcp/contexte/m03-estimation"
        url_m3 = f"{racine}/mcp/m03-estimation"
        http_contexte = create_mcp_http_client(headers={"Authorization": f"Bearer {JETON_CONTEXTE_C02_HTTP_FICTIF}"})
        http_m3 = create_mcp_http_client(headers={"Authorization": f"Bearer {JETON_METIER_C02_HTTP_FICTIF}"})
        async with (
            http_contexte,
            http_m3,
            streamable_http_client(url_contexte, http_client=http_contexte) as flux_contexte,
            streamable_http_client(url_m3, http_client=http_m3) as flux_m3,
            ClientSession(flux_contexte[0], flux_contexte[1]) as client_contexte,
            ClientSession(flux_m3[0], flux_m3[1]) as client_m3,
        ):
            await client_contexte.initialize()
            await client_m3.initialize()
            outils_contexte = {outil.name for outil in (await client_contexte.list_tools()).tools}
            outils_m3 = {outil.name for outil in (await client_m3.list_tools()).tools}
            assert "opsys_contexte_creer_ticket_cible" in outils_contexte
            assert {"m3_creer_devis", "m3_lire_devis"} <= outils_m3

            async def emettre(arguments_appel: dict) -> dict:
                reponse = await client_contexte.call_tool(
                    "opsys_contexte_creer_ticket_cible",
                    {
                        "agent_id": "m03-estimation",
                        "cle_session": CLE_SESSION_C02_HTTP_FICTIF,
                        "affaire_id": LEAD_C02_HTTP_FICTIF,
                        "origine_affaire": "session",
                        "outil": "m3_creer_devis",
                        "arguments": arguments_appel,
                    },
                )
                enveloppe = _lire_enveloppe(reponse)
                assert reponse.is_error is False and enveloppe["ok"] is True
                assert enveloppe["resultat"].get("ticket")
                return enveloppe["resultat"]

            ticket = await emettre(arguments)
            meta = {TICKET_CIBLE_META: ticket["ticket"]}
            arguments_modifies = {**arguments, "taux_marge": "0.21"}
            refuse_modification = await client_m3.call_tool("m3_creer_devis", arguments_modifies, meta=meta)
            enveloppe_modifiee = _lire_enveloppe(refuse_modification)
            assert refuse_modification.is_error is True
            assert enveloppe_modifiee["erreur"] == "cible_refusee"
            assert "arguments" in enveloppe_modifiee["details"]
            with session():
                assert len(stockage.maillons("m03-estimation", "devis")) == nombre_m3_avant

            demande = await client_m3.call_tool("m3_creer_devis", arguments, meta=meta)
            enveloppe_demande = _lire_enveloppe(demande)
            assert demande.is_error is False
            assert enveloppe_demande["ok"] is True
            assert enveloppe_demande["statut"] == "en_attente_approbation"
            with session() as cnx:
                devis, verdict = devis_durable.lire_devis(
                    stockage.maillons("m03-estimation", "devis"), arguments["devis_id"]
                )
            assert devis is None and verdict is not None

            with session() as cnx:
                decision = approbations.decider(
                    cnx,
                    enveloppe_demande["demande_id"],
                    True,
                    "nathan-c02-http-fictif",
                    {outil_creation.nom: outil_creation},
                    departements,
                )
            assert decision["statut"] == "executee"

            lecture = await client_m3.call_tool("m3_lire_devis", {"devis_id": arguments["devis_id"]})
            enveloppe_lecture = _lire_enveloppe(lecture)
            assert lecture.is_error is False and enveloppe_lecture["ok"] is True
            devis_reel = enveloppe_lecture["resultat"]["resultat"]
            assert devis_reel["devis_id"] == arguments["devis_id"]
            assert devis_reel["lead_id"] == LEAD_C02_HTTP_FICTIF
            assert devis_reel["statut"] == "brouillon"

            ticket_revoque = await emettre(arguments_retires)
            with session():
                registre_affaires = registre_m10.Registre(maillons=stockage.maillons("m10-memoire", "affaires"))
                lien = liaison_m10.liaison_courante(CLE_SESSION_C02_HTTP_FICTIF, registre_affaires)
                assert lien is not None
                maillon, refus = liaison_m10.revoquer_session_affaire(
                    CLE_SESSION_C02_HTTP_FICTIF,
                    lien["ligne_id"],
                    "nathan-fictif-c02-http",
                    "admin",
                    "appareil",
                    "Révocation fictive avant tools/call HTTP C02.",
                    "2026-10-02T12:01:00+00:00",
                    registre_affaires,
                )
            assert maillon is not None and refus is None
            refuse_retrait = await client_m3.call_tool(
                "m3_creer_devis",
                arguments_retires,
                meta={TICKET_CIBLE_META: ticket_revoque["ticket"]},
            )
            enveloppe_retrait = _lire_enveloppe(refuse_retrait)
            assert refuse_retrait.is_error is True
            assert enveloppe_retrait["erreur"] == "cible_refusee"
            assert "révoquée ou remplacée" in enveloppe_retrait["details"]

    anyio.run(scenario)

    with session() as cnx:
        devis, verdict = devis_durable.lire_devis(stockage.maillons("m03-estimation", "devis"), arguments["devis_id"])
        devis_revoque, verdict_revoque = devis_durable.lire_devis(
            stockage.maillons("m03-estimation", "devis"), arguments_retires["devis_id"]
        )
        nombre_apres = len(stockage.maillons("m03-estimation", "devis"))
        nombre_factures_apres = len(stockage.maillons("m05-financecore", "factures"))
        nb_acceptations = cnx.execute(
            select(func.count())
            .select_from(EVENEMENTS_SORTANTS)
            .where(EVENEMENTS_SORTANTS.c.type_evenement == "m3.devis_accepte")
        ).scalar_one()
    assert verdict is None and devis is not None and devis["statut"] == "brouillon"
    assert devis_revoque is None and verdict_revoque is not None
    assert nombre_apres == nombre_m3_avant + 1
    assert nombre_factures_apres == nombre_factures_avant == 0
    assert nb_acceptations == 0
