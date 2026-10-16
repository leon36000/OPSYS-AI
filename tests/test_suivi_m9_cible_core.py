"""Frontière du suivi M9 : natif dédié, transport MCP et cible canonique fictive.

Le producteur M8, le bus, M10 et SQLite sont réels ; les charges M3/M4 sont
des fixtures explicites, pas une preuve de complétion métier M3/M4 ou mobile.
"""

from __future__ import annotations

import hashlib
import json
import socket
import threading
import time
from pathlib import Path

import anyio
import pytest
import uvicorn
import yaml
from m8_analytics import outils as outils_m8
from m9_strategic_intelligence.encodage import empreinte
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client
from sqlalchemy import delete, select, update

from opsys import approbations, contexte, etat, evenements, idempotence, identite, liaison_cibles, openclaw, stockage
from opsys.capacites import Capacites
from opsys.departements import charger_departements
from opsys.serveur_mcp import ENV_CRON_OPERATEUR_JETON, application_http_departements
from opsys.stockage import codec
from opsys.stockage.schema import (
    APPROBATIONS,
    EVENEMENTS_RECUS,
    EVENEMENTS_SORTANTS,
    LIAISONS_TICKETS,
    META,
    REGISTRES,
)

M9 = "m09-strategic-intelligence"
M10 = "m10-memoire"
OUVRIR = "m9_ouvrir_suivi_decision"
PROPRIO = "proprietaire-cible-m9-fictif"
RESPONSABLE = "responsable-cible-m9-fictif"
JETON_METIER = "jeton-metier-cible-m9-fictif-suffisamment-long"
JETON_CONTEXTE = "jeton-contexte-cible-m9-fictif-distinct-long"
CLE_SESSION = "agent:m09-strategic-intelligence:webchat:direct:cible-m9-fictive"


def _jeu_fictif(suffixe):
    return {
        "fictif": True,
        "devis": {
            "devis_id": "devis-cible-fictif-" + suffixe,
            "lead_id": "lead-cible-fictif-" + suffixe, "chantier_id": None,
            "lignes": [{"reference_ligne": "ligne-fictive", "description": "Gouttières fictives",
                        "quantite": "40", "unite": "pi", "prix_unitaire": "15.00",
                        "prix_ligne": "600.00", "reference_besoin_materiau": None}],
            "cout_total": "480.00", "prix_total": "600.00", "taux_marge": "0.25",
            "duree_estimee_minutes": "60", "horodatage_acceptation": "2026-09-20T09:00:00-04:00",
        },
        "wct": {
            "wct_id": "wct-cible-fictif-" + suffixe,
            "intervention_id": "intervention-cible-fictive-" + suffixe,
            "lead_id": "lead-cible-fictif-" + suffixe, "technicien_id": RESPONSABLE,
            "horodatage_completion": "2026-09-27T15:00:00-04:00",
            "fix_gps_completion": {"latitude": 45.75, "longitude": -73.5},
            "duree_reelle_minutes": 120, "ecart_signale": False, "revue_id": None,
            "hash_maillon": "preuve-terrain-fictive-" + suffixe,
            "consommateurs_cibles": ["M8", "M10"],
            "devis_id": "devis-cible-fictif-" + suffixe, "statut": "completed_verified",
        },
    }


@pytest.fixture
def installation(session, tmp_path, monkeypatch):
    monkeypatch.delenv(ENV_CRON_OPERATEUR_JETON, raising=False)
    with session() as cnx:
        identite.creer_personne(cnx, PROPRIO, "Propriétaire fictif", "mot-de-passe-cible-fictif",
                                ["admin", "nathan_owner"])
        identite.creer_personne(cnx, RESPONSABLE, "Responsable fictif", "mot-de-passe-cible-fictif",
                                ["employee"])
    manifeste = tmp_path / "m8-seuil-fictif.yaml"
    manifeste.write_text(yaml.safe_dump({"configuration": {
        "seuils_alerte": {"m8_ecart_duree_pct": {"sens": "au_dessus", "valeur": 50}},
    }}), encoding="utf-8")
    monkeypatch.setattr(outils_m8, "_MANIFESTE", manifeste)
    tous = charger_departements(Path(__file__).resolve().parents[1] / "departments")
    actifs = {nom: tous[nom] for nom in ("m08-analytics", M9, M10)}
    for suffixe in ("A", "B"):
        jeu = _jeu_fictif(suffixe)
        assert jeu["fictif"] is True
        evenements.publier("m3.devis_accepte", "m03-estimation", jeu["devis"])
        evenements.publier("m4.travaux_termines", "m04-field-ops", jeu["wct"],
                           evenement_id=jeu["wct"]["wct_id"])
    for _ in range(3):
        tour = evenements.repartir(actifs, maintenant="2026-09-27T20:00:00+00:00")
        assert tour["echecs"] == tour["quarantaines"] == 0, tour
    return actifs


def _arguments(suffixe="A"):
    with stockage.transaction():
        [alerte] = [a for a in stockage.maillons(M9, "alertes_m8")
                    if a["preuve"].get("wct_id") == "wct-cible-fictif-" + suffixe]
    assert alerte["type_alerte"] == "MESURE-SEUIL-FRANCHI"
    assert alerte["preuve"]["valeur"] == "100.00"
    return {"evenement_id": alerte["evenement_id"], "empreinte_source": empreinte(alerte),
            "action": "Revoir les causes de durée du chantier fictif",
            "responsable_id": RESPONSABLE, "echeance": "2026-10-20T09:00:00-04:00"}


def _tables():
    with stockage.transaction() as cnx:
        return {nom: sorted(json.dumps(dict(row), sort_keys=True, default=str)
                            for row in cnx.execute(select(table)).mappings())
                for nom, table in META.tables.items()}


@pytest.fixture
def serveur_http(installation, session):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    app = application_http_departements(installation, session, JETON_METIER, hote="127.0.0.1",
                                       jeton_contexte=JETON_CONTEXTE)
    serveur = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    fil = threading.Thread(target=serveur.run, daemon=True)
    fil.start()
    try:
        for _ in range(100):
            if serveur.started:
                break
            time.sleep(0.05)
        assert serveur.started, "Le serveur MCP fictif doit démarrer"
        yield f"http://127.0.0.1:{port}"
    finally:
        serveur.should_exit = True
        fil.join(timeout=5)
        assert not fil.is_alive(), "Le serveur MCP possédé doit s'arrêter"


@pytest.mark.parametrize("chemin", ["/mcp", "/mcp/m09-strategic-intelligence"])
def test_mcp_sans_ticket_refuse_la_proposition_mais_le_natif_reste_dedie(
    installation, serveur_http, session, chemin,
):
    """Un marqueur client ne doit jamais déguiser une requête MCP en appel natif."""
    arguments = _arguments()
    native = Capacites(installation, session, memoire=False).appeler(OUVRIR, arguments)
    assert native["statut"] == "en_attente_approbation", native
    with session() as cnx:
        personne = identite.personne_active(cnx, PROPRIO)
        assert personne is not None and {"admin", "nathan_owner"} <= personne.roles
    avant = _tables()

    async def scenario():
        http = create_mcp_http_client(headers={"Authorization": f"Bearer {JETON_METIER}"})
        async with (
            http,
            streamable_http_client(serveur_http + chemin, http_client=http) as flux,
            ClientSession(flux[0], flux[1]) as client,
        ):
            await client.initialize()
            reponse = await client.call_tool(OUVRIR, arguments, meta={
                "opsys/provenanceMcp": False, "via_mcp": False, "opsys/appelant": None,
            })
            assert len(reponse.content) == 1 and reponse.content[0].type == "text"
            return json.loads(reponse.content[0].text)

    reponse = anyio.run(scenario)
    apres = _tables()
    assert reponse.get("ok") is False and reponse.get("erreur") == "ticket_cible_requis", reponse
    assert apres == avant, "Le refus MCP ne crée ni demande supplémentaire ni suivi ni effet du bus"


def _lier(suffixe="A"):
    from m10_memoire import liaison, registre

    with stockage.transaction():
        ligne, refus = liaison.lier_session_affaire(
            CLE_SESSION, "lead-cible-fictif-" + suffixe, PROPRIO, "admin", "appareil",
            "Liaison de session fictive dédiée au suivi M9", "2026-09-28T09:00:00-04:00",
            registre.Registre(maillons=stockage.maillons(M10, "affaires")),
        )
    assert refus is None and ligne is not None
    return ligne


async def _appeler_http(racine, chemin, nom, arguments, jeton, meta=None):
    http = create_mcp_http_client(headers={"Authorization": f"Bearer {jeton}"})
    async with (
        http,
        streamable_http_client(racine + chemin, http_client=http) as flux,
        ClientSession(flux[0], flux[1]) as client,
    ):
        await client.initialize()
        reponse = await client.call_tool(nom, arguments, meta=meta)
        assert len(reponse.content) == 1 and reponse.content[0].type == "text"
        return json.loads(reponse.content[0].text)


def test_ticket_m9_lie_la_preuve_reelle_et_scelle_sa_propre_approbation(
    installation, serveur_http, session,
):
    _lier()
    arguments = _arguments()

    async def scenario():
        emission = await _appeler_http(
            serveur_http, "/mcp/contexte/" + M9, "opsys_contexte_creer_ticket_cible",
            {"agent_id": M9, "cle_session": CLE_SESSION, "affaire_id": "lead-cible-fictif-A",
             "origine_affaire": "session", "outil": OUVRIR, "arguments": arguments},
            JETON_CONTEXTE,
        )
        assert emission["ok"] is True, emission
        meta = {"opsys/cibleTicket": emission["resultat"]["ticket"]}
        demande = await _appeler_http(serveur_http, "/mcp/" + M9, OUVRIR, arguments,
                                     JETON_METIER, meta)
        assert demande["statut"] == "en_attente_approbation", demande
        return demande

    demande = anyio.run(scenario)
    with session():
        assert list(stockage.maillons(M9, "suivi_decisions")) == []
    outils = {nom: entree[1] for nom, entree in Capacites(installation, session, memoire=False).index.items()}
    with session() as cnx:
        decision = approbations.decider(cnx, demande["demande_id"], True, PROPRIO, outils, installation)
    assert decision["statut"] == "executee", decision
    with session():
        [suivi] = list(stockage.maillons(M9, "suivi_decisions"))
    assert suivi["suivi_id"] == demande["demande_id"]
    assert suivi["source"]["evenement_id"] == arguments["evenement_id"]
    assert suivi["source"]["empreinte_source"] == arguments["empreinte_source"]
    assert suivi["decision"]["decide_par"] == PROPRIO
    assert suivi["decision"]["decide_role"] == "nathan_owner"


def _emettre(session, arguments, suffixe="A"):
    with session() as cnx:
        return liaison_cibles.emettre_ticket(
            cnx, departement=M9, agent_id=M9, cle_session=CLE_SESSION,
            affaire_id="lead-cible-fictif-" + suffixe, origine_affaire="session",
            outil=OUVRIR, arguments=arguments,
        )


def _proposer(installation, session, arguments, ticket):
    cap = Capacites(installation, session, filtre={M9}, appelant=M9, memoire=False)
    demande = cap.appeler(OUVRIR, arguments, ticket_cible=liaison_cibles.TicketMeta(ticket["ticket"]))
    assert demande["statut"] == "en_attente_approbation", demande
    return demande


def _approuver(installation, session, demande):
    outils = {nom: entree[1] for nom, entree in Capacites(installation, session, memoire=False).index.items()}
    with session() as cnx:
        personne = identite.personne_active(cnx, PROPRIO)
        assert personne is not None and {"admin", "nathan_owner"} <= personne.roles
        return approbations.decider(cnx, demande["demande_id"], True, PROPRIO, outils, installation)


def test_le_proprietaire_approuve_le_suivi_scelle_par_appareil_et_rejoue_sans_effet(installation, session):
    """Composition native réelle ; identité Core simulée, aucun téléphone ni jeton Core qualifié."""
    liaison = _lier()
    arguments = _arguments()
    ticket = _emettre(session, arguments)
    demande = _proposer(installation, session, arguments, ticket)
    with session() as cnx:
        hash_scelle = cnx.execute(select(APPROBATIONS.c.ticket_cible_hash).where(
            APPROBATIONS.c.id == demande["demande_id"],
        )).scalar_one()
        assert hash_scelle == hashlib.sha256(ticket["ticket"].encode()).hexdigest(), (
            "Le ticket émis doit rester lié à cette approbation avant la décision"
        )
        scelle = cnx.execute(select(LIAISONS_TICKETS).where(
            LIAISONS_TICKETS.c.ticket_hash == hash_scelle,
        )).mappings().one()
        assert (scelle["statut"], scelle["demande_id"], scelle["departement"], scelle["outil"]) == (
            "scelle", demande["demande_id"], M9, OUVRIR,
        )
        assert (scelle["affaire_id"], scelle["cle_session"], scelle["ligne_liaison_id"]) == (
            "lead-cible-fictif-A", CLE_SESSION, liaison["ligne_id"],
        )
    capacites = Capacites(installation, session, memoire=False)
    proprietaire = contexte.IdentiteAppelante(personne=PROPRIO, role="admin")
    appareil = "appareil-proprietaire-m9-fictif"
    meta = idempotence.Meta(cle="decision-suivi-m9-fictive", appareil=appareil,
                            horodatage_appareil="2026-09-28T10:15:00-04:00")
    avant_lecture = _tables()
    with contexte.appele_par_appareil(proprietaire):
        liste = capacites.appeler("m9_lister_demandes_approbation", {})
    assert liste["ok"] is True and liste["resultat"]["accepte"] is True, liste
    [item] = liste["resultat"]["resultat"]["demandes"]
    assert item["id"] == demande["demande_id"] and item["outil"] == OUVRIR
    assert item["decidable"] is True and item["arguments"] == arguments, item
    assert _tables() == avant_lecture, "Relire la demande ne décide rien et ne modifie aucune table"
    with session():
        assert list(stockage.maillons(M9, "suivi_decisions")) == []

    choix = {"demande_id": demande["demande_id"], "decision": "approuver"}
    with contexte.appele_par_appareil(proprietaire):
        decision = capacites.appeler("m9_decider_demande_approbation", choix, meta)
    assert decision["ok"] is True and decision["rejoue"] is False, decision
    assert decision["resultat"]["accepte"] is True, decision
    resultat = decision["resultat"]["resultat"]
    assert resultat["statut"] == "executee" and resultat["outil"] == OUVRIR
    assert resultat["decide_par"] == PROPRIO and resultat["role"] == "nathan_owner"
    assert resultat["issue"] == {"ok": True, "accepte": True}, resultat
    with session():
        [suivi] = list(stockage.maillons(M9, "suivi_decisions"))
    assert suivi["suivi_id"] == demande["demande_id"] and suivi["statut"] == "planifiee"
    assert suivi["source"]["evenement_id"] == arguments["evenement_id"]
    assert suivi["source"]["empreinte_source"] == arguments["empreinte_source"]
    assert suivi["decision"]["decide_par"] == PROPRIO and suivi["decision"]["decide_role"] == "nathan_owner"
    with session() as cnx:
        ligne = approbations.lire(cnx, demande["demande_id"])
        assert ligne["statut"] == "executee" and ligne["decide_role"] == "nathan_owner"
        assert [d["outil"] for d in approbations.lister(cnx)] == [OUVRIR]
        [audit] = [e for e in etat.lire_journal(cnx) if e["action"] == "approbation.approuver"]
        assert audit["par"] == PROPRIO and audit["details"]["appareil"] == appareil

    apres_decision = _tables()
    with contexte.appele_par_appareil(proprietaire):
        rejeu = capacites.appeler("m9_decider_demande_approbation", choix, meta)
    assert rejeu["rejoue"] is True, rejeu
    assert {k: v for k, v in rejeu.items() if k != "rejoue"} == {
        k: v for k, v in decision.items() if k != "rejoue"
    }
    assert _tables() == apres_decision, "Même clé : aucun second suivi, audit, effet de bus ni écriture SQL"


def test_le_changement_de_liaison_m10_refuse_a_mais_permet_la_vraie_preuve_b(installation, session):
    _lier("A")
    arguments_a = _arguments("A")
    ticket_a = _emettre(session, arguments_a)
    demande_a = _proposer(installation, session, arguments_a, ticket_a)
    _lier("B")
    avant = _tables()
    with pytest.raises(liaison_cibles.CibleRefusee, match="révoquée|remplacée"):
        _approuver(installation, session, demande_a)
    assert _tables() == avant
    with session():
        assert list(stockage.maillons(M9, "suivi_decisions")) == []
    with session() as cnx:
        assert approbations.lire(cnx, demande_a["demande_id"])["statut"] == "en_attente"
    arguments_b = _arguments("B")
    ticket_b = _emettre(session, arguments_b, "B")
    demande_b = _proposer(installation, session, arguments_b, ticket_b)
    assert _approuver(installation, session, demande_b)["statut"] == "executee"
    with session():
        [suivi] = list(stockage.maillons(M9, "suivi_decisions"))
    assert suivi["suivi_id"] == demande_b["demande_id"]
    assert suivi["source"]["evenement_id"] == arguments_b["evenement_id"]
    assert suivi["decision"]["decide_par"] == PROPRIO


@pytest.mark.parametrize("defaut", [
    "affaire_etrangere", "empreinte", "producteur_m8", "recu_m8", "charge_m8",
    "producteur_m4", "recu_m4", "charge_m4", "chaine_evenements", "chaine_affaires", "wct_ambigu",
])
def test_la_cible_m9_refuse_une_jointure_non_prouvee_sans_ticket_ni_effet(installation, session, defaut):
    from m10_memoire import classification, registre

    _lier("A")
    arguments = _arguments()
    suffixe = "A"
    if defaut == "affaire_etrangere":
        _lier("B")
        suffixe = "B"
    elif defaut == "empreinte":
        arguments["empreinte_source"] = "0" * 64
    elif defaut.startswith(("producteur_", "charge_", "recu_")):
        est_m8 = defaut.endswith("m8")
        evenement_id = arguments["evenement_id"] if est_m8 else "wct-cible-fictif-A"
        with session() as cnx:
            if defaut.startswith("producteur_"):
                cnx.execute(update(EVENEMENTS_SORTANTS).where(
                    EVENEMENTS_SORTANTS.c.evenement_id == evenement_id,
                ).values(producteur="m07-communication"))
            elif defaut.startswith("recu_"):
                cnx.execute(delete(EVENEMENTS_RECUS).where(
                    EVENEMENTS_RECUS.c.evenement_id == evenement_id,
                    EVENEMENTS_RECUS.c.consommateur == (M9 if est_m8 else M10),
                ))
            else:
                brut = cnx.execute(select(EVENEMENTS_SORTANTS.c.charge).where(
                    EVENEMENTS_SORTANTS.c.evenement_id == evenement_id,
                )).scalar_one()
                charge = codec.decoder(brut)
                if est_m8:
                    charge["quoi"] = "Autre contenu fictif sous la même publication"
                else:
                    charge["duree_reelle_minutes"] = 240  # hash_maillon M4 reste inchangé.
                cnx.execute(update(EVENEMENTS_SORTANTS).where(
                    EVENEMENTS_SORTANTS.c.evenement_id == evenement_id,
                ).values(charge=codec.encoder(charge)))
    elif defaut == "wct_ambigu":
        with session():
            reg = registre.Registre(maillons=stockage.maillons(M10, "evenements"))
            [copie] = [m for m in reg.lire() if m.get("wct_id") == "wct-cible-fictif-A"
                       and classification.type_evenement(m) == classification.TYPE_WCT]
            reg.ajouter({**copie, "lead_id": "lead-cible-fictif-B"})
            assert reg.valider_chaine()[0] is True, "Une chaîne valide n'est pas un mandat"
    else:
        nom_registre = "evenements" if defaut == "chaine_evenements" else "affaires"
        with session() as cnx:
            ligne = cnx.execute(select(REGISTRES.c.rang, REGISTRES.c.maillon).where(
                REGISTRES.c.departement == M10, REGISTRES.c.registre == nom_registre,
            ).order_by(REGISTRES.c.rang)).first()
            maillon = codec.decoder(ligne.maillon)
            maillon["horodatage"] = "2026-09-29T09:00:00-04:00"
            cnx.execute(update(REGISTRES).where(
                REGISTRES.c.departement == M10, REGISTRES.c.registre == nom_registre,
                REGISTRES.c.rang == ligne.rang,
            ).values(maillon=codec.encoder(maillon)))
    with session() as cnx:
        personne = identite.personne_active(cnx, PROPRIO)
        assert personne is not None and {"admin", "nathan_owner"} <= personne.roles
    avant = _tables()
    with pytest.raises(liaison_cibles.CibleRefusee):
        _emettre(session, arguments, suffixe)
    assert _tables() == avant


def test_la_portee_mcp_se_retablit_apres_exception_et_ne_fuit_pas_au_natif(installation, session):
    cap = Capacites(installation, session, memoire=False)
    arguments = _arguments()
    avant = _tables()
    with pytest.raises(RuntimeError, match="panne fictive"), contexte.transport_mcp():
        reponse = cap.appeler(OUVRIR, arguments)
        assert reponse["erreur"] == "ticket_cible_requis", reponse
        raise RuntimeError("panne fictive")
    assert _tables() == avant
    assert cap.appeler(OUVRIR, arguments)["statut"] == "en_attente_approbation"


def test_la_configuration_core_demande_un_ticket_m9_sans_rendre_les_lectures_n3(installation):
    configuration = openclaw._configuration_contexte(installation, {M9: []})
    assert configuration["cibles"][OUVRIR] == {"type": "ticket"}
    assert configuration["niveaux"][OUVRIR] == "N3"
    for nom in ("m9_preparer_suivi_decision", "m9_lire_suivi_decision"):
        assert configuration["niveaux"][nom] == "N0"
        assert nom not in configuration["cibles"]


def test_le_profil_runtime_valide_ne_remplace_pas_le_ticket_cible_m9(
    installation, serveur_http, session,
):
    from opsys import agents

    profil_id = "m09-suivi-cible-fictif"
    with session() as cnx:
        agents.creer(
            cnx, installation,
            {"id": profil_id, "departement": M9,
             "responsabilite": "Suivi fictif de chantier sous approbation dédiée",
             "palier_modele": "standard", "outils": [OUVRIR],
             "budget_jour": 100, "budget_mois": 1000, "limite_tours": 2,
             "limite_reessais": 1, "limite_concurrence": 1, "declencheurs": [{"type": "manuel"}]},
            par=PROPRIO, mutation_id="profil-cible-fictif-creer",
        )
        agents.definir_actif(cnx, profil_id, installation, True, par=PROPRIO,
                             mutation_id="profil-cible-fictif-activer", revision_attendue=1)
    _lier()
    arguments = _arguments()
    ticket = _emettre(session, arguments)
    meta = {"opsys/runtimeProfileId": profil_id, "opsys/runtimeProfileRevision": "2",
            "opsys/runtimeServer": "opsys_m9", "opsys/provenanceMcp": False}
    avant = _tables()

    async def scenario():
        refus = await _appeler_http(serveur_http, "/mcp/" + M9, OUVRIR, arguments, JETON_METIER, meta)
        assert refus.get("ok") is False and refus.get("erreur") == "ticket_cible_requis", refus
        assert _tables() == avant, "Le profil valide ne suffit pas à créer une demande M9"
        demande = await _appeler_http(
            serveur_http, "/mcp/" + M9, OUVRIR, arguments, JETON_METIER,
            {**meta, "opsys/cibleTicket": ticket["ticket"]},
        )
        assert demande["statut"] == "en_attente_approbation", demande
        return demande

    demande = anyio.run(scenario)
    assert _approuver(installation, session, demande)["statut"] == "executee"


@pytest.mark.parametrize("defaut", ["publication_m4", "chaine_evenements"])
def test_le_ticket_scelle_revalide_la_provenance_au_point_effet(installation, session, defaut):
    _lier()
    arguments = _arguments()
    demande = _proposer(installation, session, arguments, _emettre(session, arguments))
    with session() as cnx:
        if defaut == "publication_m4":
            brut = cnx.execute(select(EVENEMENTS_SORTANTS.c.charge).where(
                EVENEMENTS_SORTANTS.c.evenement_id == "wct-cible-fictif-A",
            )).scalar_one()
            charge = codec.decoder(brut)
            charge["duree_reelle_minutes"] = 240
            cnx.execute(update(EVENEMENTS_SORTANTS).where(
                EVENEMENTS_SORTANTS.c.evenement_id == "wct-cible-fictif-A",
            ).values(charge=codec.encoder(charge)))
        else:
            ligne = cnx.execute(select(REGISTRES.c.rang, REGISTRES.c.maillon).where(
                REGISTRES.c.departement == M10, REGISTRES.c.registre == "evenements",
            ).order_by(REGISTRES.c.rang)).first()
            maillon = codec.decoder(ligne.maillon)
            maillon["horodatage"] = "2026-09-29T09:00:00-04:00"
            cnx.execute(update(REGISTRES).where(
                REGISTRES.c.departement == M10, REGISTRES.c.registre == "evenements",
                REGISTRES.c.rang == ligne.rang,
            ).values(maillon=codec.encoder(maillon)))
    avant = _tables()
    with pytest.raises(liaison_cibles.CibleRefusee, match="WCT mémorisé|chaîne.*M10"):
        _approuver(installation, session, demande)
    assert _tables() == avant
