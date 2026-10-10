"""Une affaire fictive traverse les outils existants, sans événement métier fabriqué.

Première couche : moteur HTTP MCP réel, base durable et répartiteur dans un processus neuf.
La porte d'appareil du harnais reproduit la règle Core en Python : elle ne prouve pas le
Core TypeScript, un téléphone physique, un fournisseur ni une publication marketing.
Photos descriptives, barème de temps et montants sont fictifs : aucune mesure pixel,
calibration empirique, provenance économique des lignes ni opération d'argent réel.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import os
import subprocess
import sys
import time
from collections import Counter
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import anyio
import pytest
import yaml
from fastapi.testclient import TestClient
from harnais_e2e import DT_TZ, JETON_MCP, iso
from harnais_e2e_chantier import MATERIAU_ID, AppEmploye, Chantier, receptionner_materiel_args
from m1_front_office import outils as m1_outils
from m5_financecore import facturation as m5_facturation
from m5_financecore import outils as m5_outils
from m5_financecore import registre as m5_registre
from m8_analytics import outils as m8_outils
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client
from sqlalchemy import MetaData, Table, inspect, select

from opsys import approbations, cli, evenements, identite, liaison_cibles, stockage, taxonomie
from opsys.capacites import Capacites, outils_executables
from opsys.console.application import creer_application
from opsys.console.securite import Configuration
from opsys.departements import charger_departements
from opsys.stockage import codec
from opsys.stockage.schema import APPROBATIONS, EVENEMENTS_RECUS, EVENEMENTS_SORTANTS, META, REGISTRES

# La liaison C02 de production refuse PostgreSQL : qualifier ce parcours sur SQLite.
# La frontière PostgreSQL demeure couverte séparément par son refus HTTP sans mutation.
pytestmark = pytest.mark.parametrize("moteur", ["sqlite"], indirect=True)

ROOT = Path(__file__).resolve().parents[2]
JETON_CONTEXTE_FICTIF = "jeton-contexte-vertical-fictif-distinct-long"
CLE_SESSION_FICTIVE = "agent:m03-estimation:webchat:direct:verticale-fictive"
EQUIPES_FICTIVES = {
    "liste": [
        {
            "id": "eq-verticale-fictive",
            "membres": ["etienne"],
            "competences": ["gouttieres"],
            "depot": {"id": "depot-fictif", "latitude_microdegres": 45735000, "longitude_microdegres": -73455000},
            "quarts": [{"jour": 0, "debut_min": 480, "fin_min": 1020}],
        }
    ],
    "services": {"gouttieres": {"duree_min": 90, "competences": ["gouttieres"]}},
    "cedule": {
        "facteur_detour_milliemes": 1300,
        "vitesse_moyenne_kmh": 50,
        "marge_par_trajet_secondes": 600,
        "iterations": 500,
        "cout_non_cedule_m": 500000,
    },
    "fenetre_par_defaut": {"jours": [0], "debut_min": 480, "fin_min": 1020},
}
METEO_FICTIVE = {
    "fuseau": "America/Toronto",
    "services": {
        "gouttieres": {
            "seuils": {
                "vent_kmh": {"validation": 35, "blocage": 50},
                "pluie_mm_h": {"blocage": 5},
                "gel_c": {"blocage": 0},
                "verglas": {"blocage": True},
            },
            "sans_objet": ["chaleur"],
        }
    },
}


def _empreinte(moteur):
    """Contenu durable intégral, pas seulement le nombre de lignes : détecte aussi les UPDATE."""
    with stockage.transaction() as cnx:
        lignes = {
            table.name: [
                dict(ligne._mapping) for ligne in cnx.execute(select(table).order_by(*table.primary_key.columns))
            ]
            for table in META.sorted_tables
        }
    donnees = json.dumps(lignes, sort_keys=True, default=str, separators=(",", ":")).encode()
    return {"compteurs": moteur.empreinte_etat(), "contenu_sha256": hashlib.sha256(donnees).hexdigest()}


def _donnee(enveloppe):
    assert enveloppe["ok"] is True, enveloppe
    resultat = enveloppe["resultat"]
    if isinstance(resultat, dict) and "accepte" in resultat:
        assert resultat["accepte"] is True, resultat
        return resultat.get("resultat", resultat)
    return resultat


def _app(moteur, porte, outil, args, *, cle=None):
    reponse = porte.appeler(outil, args, cle=cle, horodatage_appareil=iso(moteur.horloge.maintenant) if cle else None)
    assert reponse.statut == 200, reponse.corps
    assert not reponse.mesure.tronque, reponse.corps
    return reponse


def _sources_pour_revue(appeler, intervention_id, wct_id, prefixe):
    """Fictif : lecture M6 puis causes humaines déclarées, sans vérité photo inférée."""
    liste = appeler("m6_lister_variances_classables_wct_appareil",
                    {"wct_id": wct_id, "decalage": 0, "limite": 8})
    assert liste.metier["accepte"] is True, liste.corps
    dto = liste.resultat
    assert dto["wct"]["wct_id"] == wct_id and dto["wct"]["intervention_id"] == intervention_id
    assert dto["pagination"]["reste"] == 0 and dto["pagination"]["decalage_suivant"] is None
    critiques = [ligne for ligne in dto["lignes"] if ligne["source_ligne"]["critique"] is True]
    assert critiques, "ce scénario doit publier une variance critique, pas inventer une cause"
    for ligne in critiques:
        assert ligne["classement_courant"] is None, "source initiale de cette fixture"
        classement = appeler("m6_classer_cause_variance_appareil", {
            "selection": ligne["selection"], "cause": "breakage",
            "motif": "FICTIF : cause de bris déclarée pour le scénario, sans attestation photo.",
            "classement_attendu": None, "references_pieces": [],
        }, cle=f"{prefixe}-{ligne['selection']['position_ligne']}")
        assert classement.metier["accepte"] is True, classement.corps
    dossier = appeler("m4_lire_dossier_revue_completion_appareil",
                      {"intervention_id": intervention_id, "demande_id": None})
    assert dossier.metier["accepte"] is True, dossier.corps
    assert dossier.resultat["wct"] == dto["wct"]
    assert dossier.resultat["couverture"]["positions_sans_classement"] == []
    return dossier.resultat["sources"]


def _appeler_agent(moteur, departement, outil, args):
    async def appeler():
        http = create_mcp_http_client(headers={"Authorization": f"Bearer {JETON_MCP}"})
        async with (
            http,
            streamable_http_client(
                f"http://127.0.0.1:{moteur.port}/mcp/{departement}",
                http_client=http,
            ) as flux,
            ClientSession(flux[0], flux[1]) as client,
        ):
            await client.initialize()
            meta = None
            if outil in liaison_cibles.OUTILS_CIBLES:
                prive = create_mcp_http_client(headers={"Authorization": f"Bearer {JETON_CONTEXTE_FICTIF}"})
                async with (
                    prive,
                    streamable_http_client(
                        f"http://127.0.0.1:{moteur.port}/mcp/contexte/{departement}",
                        http_client=prive,
                    ) as flux_prive,
                    ClientSession(flux_prive[0], flux_prive[1]) as contexte,
                ):
                    await contexte.initialize()
                    emission = await contexte.call_tool(
                        "opsys_contexte_creer_ticket_cible",
                        {
                            "agent_id": departement,
                            "cle_session": f"agent:{departement}:webchat:direct:verticale-fictive",
                            "affaire_id": args.get("lead_id")
                            or _evenements("m1.lead_qualifie")[0][1]["lead"]["lead_id"],
                            "origine_affaire": "session",
                            "outil": outil,
                            "arguments": args,
                        },
                    )
                    assert len(emission.content) == 1 and emission.content[0].type == "text"
                    ticket = _donnee(json.loads(emission.content[0].text))
                    meta = {liaison_cibles.TICKET_CIBLE_META: ticket["ticket"]}
            resultat = await client.call_tool(outil, args, meta=meta)
            assert len(resultat.content) == 1 and resultat.content[0].type == "text"
            return json.loads(resultat.content[0].text)

    return anyio.run(appeler)


def _agent(moteur, admin, departement, outil, args, *, niveau_attendu=None):
    reponse = _appeler_agent(moteur, departement, outil, args)
    niveau = None
    if reponse.get("statut") == "en_attente_approbation":
        with stockage.transaction() as cnx:
            niveau = cnx.scalar(select(APPROBATIONS.c.niveau).where(APPROBATIONS.c.id == reponse["demande_id"]))
    if niveau_attendu is not None:
        assert niveau == niveau_attendu, (outil, niveau, niveau_attendu, reponse)
    if niveau == "N5":
        # Backend réel de décision console; aucune signature/client professionnel réel n'est revendiqué.
        outils = outils_executables(moteur.departements, stockage.transaction)
        avant = _empreinte(moteur)
        with pytest.raises(ValueError, match="attestation"), stockage.transaction() as cnx:
            approbations.decider(cnx, reponse["demande_id"], True, "nathan", outils, moteur.departements)
        assert _empreinte(moteur) == avant
        with stockage.transaction() as cnx:
            decision = approbations.decider(
                cnx,
                reponse["demande_id"],
                True,
                "nathan",
                outils,
                moteur.departements,
                attestation={
                    "nom": "Signataire fictif",
                    "profession": "Représentant client fictif",
                    "reference_document": "acceptation-client-fictive",
                },
            )
        assert decision["statut"] == "executee", decision
        return decision
    if reponse.get("statut") == "en_attente_approbation":
        decision = _app(
            moteur,
            admin,
            "m9_decider_demande_approbation",
            {"demande_id": reponse["demande_id"], "decision": "approuver", "motif": "Cas fictif de verticale."},
            cle=f"decision-verticale-{reponse['demande_id']}",
        )
        assert decision.metier["accepte"] is True, decision.corps
        assert decision.resultat["statut"] == "executee", decision.resultat
        return decision.resultat
    return _donnee(reponse)


def _evenements(type_evenement):
    with stockage.transaction() as cnx:
        lignes = cnx.execute(
            select(EVENEMENTS_SORTANTS.c.evenement_id, EVENEMENTS_SORTANTS.c.charge).where(
                EVENEMENTS_SORTANTS.c.type_evenement == type_evenement
            )
        ).all()
    return [(ligne.evenement_id, codec.decoder(ligne.charge)) for ligne in lignes]


def _drainer(moteur):
    for _ in range(15):
        moteur.horloge.avancer(seconds=90)
        resume = evenements.repartir(moteur.departements, maintenant=iso(moteur.horloge.maintenant))
        assert resume["echecs"] == resume["quarantaines"] == 0, resume
        if resume["livres"] == 0:
            return
    raise AssertionError("Le bus de l'affaire ne rejoint pas le repos.")


def _livrer_dans_un_processus_neuf(moteur):
    code = """
import datetime as dt,json,sys
from m2_revenue_crm import outils as m2
from m5_financecore import outils as m5
from opsys import stockage,evenements
from opsys.departements import charger_departements
stockage.migrer()
m2.utiliser_stockage_durable();m5.utiliser_stockage_durable()
deps=charger_departements();maintenant=dt.datetime.fromisoformat(sys.argv[1]);total=0
for tour in range(15):
    resume=evenements.repartir(deps,maintenant=maintenant.isoformat())
    assert resume['echecs']==resume['quarantaines']==0,resume
    total+=resume['livres']
    if resume['livres']==0:break
    maintenant+=dt.timedelta(seconds=90)
else:raise AssertionError('bus non convergent dans le processus neuf')
stockage.liberer()
print(json.dumps({'livres':total,'pid':__import__('os').getpid()}))
"""
    moteur.arreter()
    stockage.liberer()
    env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            [str(ROOT / "src"), *[str(p) for p in sorted((ROOT / "departments").glob("*/src"))]]
        ),
    }
    resultat = subprocess.run(
        [sys.executable, "-c", code, iso(moteur.horloge.maintenant)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert resultat.returncode == 0, resultat.stderr
    preuve = json.loads(resultat.stdout)
    assert preuve["livres"] > 0 and preuve["pid"] != os.getpid(), preuve
    moteur.demarrer()
    return preuve


@pytest.fixture
def affaire(moteur, equipe, monkeypatch, tmp_path):
    """Entrées/configuration fictives; les identifiants métier proviennent ensuite des outils."""
    moteur.arreter()
    moteur.jeton_contexte = JETON_CONTEXTE_FICTIF
    moteur.demarrer()
    moteur.creer_personne("vendeur.vertical", "Vendeur verticale (fictif)", ["seller"], monkeypatch)
    moteur.creer_personne("vendeur.autre", "Autre vendeur (fictif)", ["seller"], monkeypatch)
    vendeur = moteur.appairer("vendeur.vertical", "seller")
    taxonomie.enregistrer_services(taxonomie.codes_catalogue())
    taxonomie.enregistrer_zone_desservie(["Repentigny"])
    taxonomie.enregistrer_fenetre_conversation(30)
    m1_outils.utiliser_stockage_durable()
    for commande, contenu in (("equipes", EQUIPES_FICTIVES), ("meteo", METEO_FICTIVE)):
        fichier = tmp_path / f"{commande}-verticale-fictive.yaml"
        fichier.write_text(yaml.safe_dump(contenu), encoding="utf-8")
        assert cli.main([commande, "declarer", "--depuis", str(fichier), "--par", "nathan"]) == 0
    try:
        yield {**equipe, "vendeur": vendeur, "autre": moteur.appairer("vendeur.autre", "seller")}
    finally:
        m1_outils.reinitialiser_registre()


def _lead_recu(moteur):
    cap = Capacites({"m07-marketing": moteur.departements["m07-marketing"]}, stockage.transaction, memoire=False)
    lien = _donnee(
        cap.appeler(
            "m7_generer_lien_utm",
            {
                "url_base": "https://verticale-fictive.test/",
                "source": "facebook",
                "medium": "social",
                "campaign": "workflow-verticale-fictive-2026",
                "content": None,
            },
        )
    )
    assert lien["conforme"] is True, lien
    utm = dict(parse_qsl(urlsplit(lien["lien"]).query))
    charge = {
        "nom": "",
        "courriel": "cliente-verticale@exemple.test",
        "telephone": "",
        "message": "Bonjour, mes gouttières fuient à Repentigny, je souhaite une soumission (fictif).",
        **utm,
    }
    corps = json.dumps(charge, ensure_ascii=False, separators=(",", ":")).encode()
    chemin, site, date, nonce = (
        "/interne/m1/formulaire",
        "site-vertical-fictif",
        str(int(time.time())),
        "nonce-vertical-fictif-0001",
    )
    secret = b"secret-pont-vertical-fictif-" + b"v" * 32
    signe = f"v1\nPOST\n{chemin}\n{site}\n{date}\n{nonce}\n".encode() + corps
    entetes = {
        "content-type": "application/json",
        "x-m1-site": site,
        "x-m1-timestamp": date,
        "x-m1-nonce": nonce,
        "x-m1-signature": hmac.new(secret, signe, hashlib.sha256).hexdigest(),
    }
    configuration = Configuration("cle-console-verticale-fictive-" + "x" * 32, cookie_securise=False)
    with TestClient(
        creer_application(
            configuration, moteur.departements, stockage.transaction, site_formulaire=site, secret_formulaire=secret
        )
    ) as client:
        avant = _empreinte(moteur)
        refus = client.post(chemin, content=corps, headers={**entetes, "x-m1-signature": "0" * 64})
        assert refus.status_code == 403 and _empreinte(moteur) == avant
        recu = client.post(chemin, content=corps, headers=entetes)
        assert recu.status_code == 202, recu.text
    ((_, evenement),) = _evenements("m1.lead_qualifie")
    lead = evenement["lead"]
    assert lead["utm"] == utm and lead["service"] == "gouttieres"
    moteur.horloge.maintenant = dt.datetime.fromtimestamp(int(date), DT_TZ)
    _drainer(moteur)
    return lead


def _preparer_affaire(moteur, affaire):
    admin = affaire["admin"]
    lead = _lead_recu(moteur)
    lead_id = lead["lead_id"]
    heure = iso(moteur.horloge.maintenant)
    qualifie = _app(
        moteur,
        admin,
        "m2_transitionner_statut",
        {
            "lead_id": lead_id,
            "statut_cible": "qualifie",
            "horodatage": heure,
            "owner": "vendeur.vertical",
            "prochaine_action": {"description": "Estimer le chantier fictif", "echeance": heure},
        },
        cle="qualifier-verticale",
    )
    assert qualifie.metier["accepte"] is True, qualifie.corps
    note = _app(
        moteur,
        affaire["vendeur"],
        "m2_enregistrer_interaction",
        {
            "lead_id": lead_id,
            "auteur": "vendeur.vertical",
            "resume": "Visite de qualification fictive.",
            "horodatage": heure,
        },
        cle="visite-verticale",
    )
    assert note.metier["accepte"] is True, note.corps
    avant = _empreinte(moteur)
    readiness = _app(
        moteur, affaire["vendeur"], "m2_evaluer_readiness", {"lead_id": lead_id, "horodatage": heure}
    )
    assert _empreinte(moteur) == avant, "la préparation commerciale est une lecture pure"
    marqueur = readiness.resultat
    assert marqueur["readiness_ok"] is True and marqueur["lead_id"] == lead_id
    liaison = _app(
        moteur,
        admin,
        "m10_lier_session_affaire",
        {
            "cle_session": CLE_SESSION_FICTIVE,
            "affaire_id": lead_id,
            "motif": "Liaison humaine de cette affaire fictive pour estimation.",
            "horodatage": heure,
        },
        cle="liaison-verticale",
    )
    assert liaison.metier["accepte"] is True, liaison.corps
    # Adaptation déclarée de test_estimation.BAREME_AVEC_DUREE (8..14 et 2.5 minutes/unité)
    # au service gouttieres et à l'unité pi de CE scénario. Ce n'est pas un tarif terrain.
    # Sans matières dans le barème : le besoin définitif M6 vient encore des lignes acceptées.
    bareme_fictif = {
        "version": "verticale-m3-temps-fictif/1", "unite": "pi",
        "semantique_temps": "duree_ecoulee_intervention",
        "postes": {"gouttieres": {
            "cout_unitaire_min": 8.0, "cout_unitaire_max": 14.0, "duree_minutes_par_unite": 2.5,
        }},
    }

    def estimer(photos):
        decision = _agent(moteur, admin, "m03-estimation", "m3_estimer_projet", {
            "contrat": lead, "marqueur": marqueur, "photos": photos,
            "seuils": {"resolution_minimale": 1000, "eclairage_minimal": 4},
            "bareme": bareme_fictif, "quantite": 40, "plancher_rentable": 0,
            "graine": 7000, "taux_marge": "0.25",
        }, niveau_attendu="N3")
        # Mode ombre conservé : la demande seule ne serait pas une estimation exécutée.
        assert decision["statut"] == "executee", decision
        # La projection M9 appareil garde une issue bornée, pas la réponse M3 complète.
        # Assertion serveur du test seulement : reçu canonique de CETTE décision HTTP.
        with stockage.transaction() as cnx:
            recue = approbations.lire(cnx, decision["demande_id"])
        assert recue is not None and recue["statut"] == "executee"
        assert (recue["outil"], recue["departement"], recue["niveau"]) == (
            "m3_estimer_projet", "m03-estimation", "N3",
        )
        return _donnee(recue["resultat"])

    sans_photos = estimer([])
    assert sans_photos["etape"] == "complet" and sans_photos["estimation"]["lead_id"] == lead_id
    assert sans_photos["estimation"]["prix_bloque"] is True
    assert sans_photos["estimation"]["verdict_estimation"] == "QUALITE_ENTREE_INSUFFISANTE"
    assert sans_photos["estimation"]["intervalle_confiance"]["borne_basse"] is None
    assert sans_photos["estimation"]["intervalle_confiance"]["borne_haute"] is None
    assert sans_photos["elements_manquants"] == ["aucune entrée visuelle n'a été fournie"]
    assert sans_photos["signal_relance_m2"]["lead_id"] == lead_id
    assert _evenements("m3.devis_accepte") == []
    # Métadonnées synthétiques issues de test_estimation._photo / scénario formulaire M3,
    # sans image/pixel ni preuve géométrique réelle. Même lead, readiness et UTM.
    corrigee = estimer([{
        "photo_id": "photo-verticale-m3-fictive", "resolution_largeur": 3000,
        "resolution_hauteur": 2000, "eclairage": 7, "angle": "face",
        "reference_echelle": {"type": "porte", "dimensions_connues": True},
    }])
    estimation = corrigee["estimation"]
    assert corrigee["etape"] == "complet" and estimation["lead_id"] == lead_id
    assert estimation["prix_bloque"] is False
    assert estimation["devis_id"] == sans_photos["estimation"]["devis_id"]
    assert 0 < estimation["intervalle_confiance"]["borne_basse"] <= estimation["intervalle_confiance"]["borne_haute"]
    assert Decimal(corrigee["duree_estimee_minutes"]) == Decimal("100")
    devis_id, source_hash = estimation["devis_id"], estimation["hash_maillon"]
    assert source_hash != sans_photos["estimation"]["hash_maillon"]
    assert len(source_hash) == 64
    # Le hash lie l'estimation au lead/devis ; il n'atteste PAS la provenance économique
    # des lignes/coûts ci-dessous. Elles restent les entrées commerciales fictives existantes.
    _agent(
        moteur,
        admin,
        "m03-estimation",
        "m3_creer_devis",
        {
            "devis_id": devis_id,
            "estimation_source_hash": source_hash,
            "lead_id": lead_id,
            "chantier_id": lead_id,
            "lignes": [
                {
                    "description": "Gouttières alu (fictif)",
                    "quantite": "40",
                    "unite": "pi",
                    "cout_unitaire": "8.00",
                    "reference_besoin_materiau": MATERIAU_ID,
                },
                {
                    "description": "Main d'œuvre (fictif)",
                    "quantite": "1",
                    "unite": "forfait",
                    "cout_unitaire": "160.00",
                    "reference_besoin_materiau": None,
                },
            ],
            "taux_marge": "0.25",
            "horodatage": heure,
        },
    )
    _agent(
        moteur,
        admin,
        "m03-estimation",
        "m3_marquer_devis_accepte",
        {"devis_id": devis_id, "approbateur": "nathan", "horodatage": heure},
        niveau_attendu="N5",
    )
    preuve = _livrer_dans_un_processus_neuf(moteur)
    evenement_id, devis = _evenements("m3.devis_accepte")[0]
    assert (devis["lead_id"], devis["devis_id"], devis["prix_total"]) == (lead_id, devis_id, "600.00")
    assert devis["estimation_source_hash"] == source_hash
    assert Decimal(devis["duree_estimee_minutes"]) == Decimal("100")
    assert _evenements("m3.besoins_materiaux") == [], "aucune matière provisoire ajoutée à cette tranche"
    with stockage.transaction() as cnx:
        recu = cnx.execute(
            select(EVENEMENTS_RECUS).where(
                EVENEMENTS_RECUS.c.evenement_id == evenement_id, EVENEMENTS_RECUS.c.consommateur == "m04-field-ops"
            )
        ).one()
    assert recu.statut == "traite"
    intervention_id = codec.decoder(recu.resultat)["intervention_id"]
    lendemain = moteur.horloge.maintenant + dt.timedelta(days=1)
    moteur.horloge.maintenant = lendemain.replace(hour=7, minute=0, second=0, microsecond=0)
    chantier = Chantier(
        lead_id, devis["devis_id"], devis["chantier_id"], intervention_id, "etienne", moteur.horloge.maintenant
    )
    avant = _empreinte(moteur)
    preparation = _app(moteur, admin, "m4_verifier_preparation", {"intervention_id": intervention_id})
    assert preparation.metier["accepte"] is True and preparation.resultat["pret"] is False
    assert _empreinte(moteur) == avant
    _agent(moteur, admin, "m06-material-control", "m6_receptionner_commande", receptionner_materiel_args(chantier))
    _drainer(moteur)
    localisation = _app(
        moteur,
        admin,
        "m4_confirmer_localisation",
        {
            "chantier_id": lead_id,
            "action": "confirmee",
            "horodatage": iso(moteur.horloge.maintenant),
            "confirme_par": "nathan",
            "adresse": {"numero_municipal": "1", "odonyme": "Rue Fictive", "municipalite": "Repentigny"},
            "source": "manuel",
            "latitude_microdegres": 45740117,
            "longitude_microdegres": -73454833,
            "motif": "Coordonnées de test fictives confirmées.",
        },
        cle="localisation-verticale",
    )
    assert localisation.metier["accepte"] is True, localisation.corps
    avant = _empreinte(moteur)
    preparation = _app(moteur, admin, "m4_verifier_preparation", {"intervention_id": intervention_id})
    assert preparation.resultat["pret"] is True, preparation.resultat
    assert _empreinte(moteur) == avant
    plan = _app(
        moteur,
        admin,
        "m4_proposer_cedule",
        {"horodatage": iso(moteur.horloge.maintenant), "intervention_ids": [intervention_id]},
        cle="cedule-proposee-verticale",
    )
    assert plan.metier["accepte"] is True, plan.corps
    applique = _app(
        moteur,
        admin,
        "m4_appliquer_cedule",
        {"plan_id": plan.resultat["plan_id"], "horodatage": iso(moteur.horloge.maintenant), "confirme_par": "nathan"},
        cle="cedule-appliquee-verticale",
    )
    assert applique.metier["accepte"] is True, applique.corps
    avant = _empreinte(moteur)
    _drainer(moteur)
    assert _empreinte(moteur) == avant and preuve["livres"] > 0
    return chantier, lead, preuve


def test_affaire_recue_cree_une_seule_intervention_et_reprend_sa_preparation(moteur, affaire):
    chantier, lead, preuve = _preparer_affaire(moteur, affaire)
    assert chantier.lead_id == lead["lead_id"] and preuve["livres"] > 0
    _, devis = _evenements("m3.devis_accepte")[0]
    assert isinstance(devis.get("estimation_source_hash"), str), "la verticale doit conserver sa source M3"
    assert len(devis["estimation_source_hash"]) == 64
    assert Decimal(devis["duree_estimee_minutes"]) == Decimal("100")


@pytest.fixture
def finance_fictive(tmp_path, monkeypatch):
    for module, nom, configuration in (
        (m5_outils, "m5", {"taux_horaire_main_d_oeuvre": "50.00"}),
        (m8_outils, "m8", {"seuils_alerte": {"m8_ecart_materiaux_max_pct": {"sens": "au_dessus", "valeur": 30}}}),
    ):
        manifeste = tmp_path / f"{nom}-configuration-fictive.yaml"
        manifeste.write_text(yaml.safe_dump({"configuration": configuration}), encoding="utf-8")
        monkeypatch.setattr(module, "_MANIFESTE", manifeste)


def _mesures(moteur, admin, wct_id):
    reponse = _app(moteur, admin, "m8_lire_mesures_chantier", {"wct_id": wct_id})
    donnees = _donnee(reponse.enveloppe)
    return {mesure["metric_id"]: mesure for mesure in donnees["mesures"]}


def _apprentissage(moteur, admin, wct_id):
    """Lecture native T0 du WCT courant ; aucun fait, paiement ou barème n'est écrit."""
    avant = _empreinte(moteur)
    coupure = moteur.horloge.maintenant.astimezone(dt.UTC).isoformat()
    reponse = _app(moteur, admin, "m3_lire_apprentissage_chantier", {
        "wct_id": wct_id, "coupure_utc": coupure,
    })
    assert _empreinte(moteur) == avant
    rapport = _donnee(reponse.enveloppe)
    if rapport["statut"] == "observee":
        assert rapport["sources"]["wct_id"] == wct_id
    else:
        assert rapport["wct_id"] == wct_id
    assert rapport["cause"] is None
    texte = json.dumps(rapport, ensure_ascii=False)
    for interdit in ("latitude", "longitude", "Rue Fictive", "etienne"):
        assert interdit not in texte
    return rapport


# Compte et identité de qualification fictifs, distincts du Nathan de l'affaire.
_OWNER_PARTIEL = "finance-verticale-fictive"
_PASSWORD_PARTIEL = "mot-de-passe-verticale-finance-fictif"
_SECRET_PARTIEL = "secret-console-verticale-partielle-fictif-" + "x" * 32
_ROUTE_PARTIEL = "/api/finance/rapprochement-bancaire/proposer"


def _tables_partiel():
    """Toutes les tables SQL réelles, y compris celles hors META ; aucun filtre métier."""
    with stockage.transaction() as cnx:
        meta = MetaData()
        return {
            nom: Counter(tuple(row) for row in cnx.execute(select(Table(nom, meta, autoload_with=cnx))))
            for nom in inspect(cnx).get_table_names()
        }


def _hashes_partiel(tables):
    return {
        nom: {"lignes": sum(rows.values()), "sha256": hashlib.sha256(json.dumps(
            sorted(((list(row), nombre) for row, nombre in rows.items()),
                   key=lambda item: json.dumps(item, sort_keys=True, default=str)),
            sort_keys=True, default=str, separators=(",", ":"),
        ).encode()).hexdigest()}
        for nom, rows in tables.items()
    }


def _console_partiel(racine):
    deps = dict(charger_departements())
    deps["m05-financecore"] = replace(deps["m05-financecore"], racine=Path(racine))
    return creer_application(Configuration(_SECRET_PARTIEL, cookie_securise=False), deps, stockage.transaction)


def _login_partiel(client):
    retour = client.post("/connexion", data={
        "identifiant": _OWNER_PARTIEL, "mot_de_passe": _PASSWORD_PARTIEL,
    }, follow_redirects=False)
    assert retour.status_code == 303, "connexion de la personne fictive requise"
    return {"x-csrf-token": client.get("/api/session").json()["csrf"]}


def _ar_partiel():
    with stockage.transaction():
        registre = m5_registre.Registre(maillons=stockage.maillons("m05-financecore", "factures"))
        assert registre.valider_chaine()[0] is True
        vue, verdict = m5_facturation.comptes_a_recevoir(registre)
    assert verdict is None and vue["total_complet"] is True
    return vue


def _rejouer_partiel_processus(manifeste):
    """Entrée de test dans un Python neuf, sans migration ni modification de source."""
    demande = json.loads(Path(manifeste).read_text())
    assert Path(stockage.__file__).resolve().is_relative_to(ROOT)
    avant_login = _hashes_partiel(_tables_partiel())
    try:
        with TestClient(_console_partiel(demande["racine"]), base_url="http://testserver/opsys") as client:
            headers = _login_partiel(client)
            avant = _tables_partiel()  # Authentification hors fenêtre de rejeu.
            retour = client.post(_ROUTE_PARTIEL, json=demande["commande"], headers=headers)
            assert retour.status_code == 200, retour.text
            enveloppe = retour.json()
            assert enveloppe["rejoue"] is True and enveloppe["resultat"]["accepte"] is True
            assert _tables_partiel() == avant
            return {"pid": os.getpid(), "avant_login": avant_login,
                    "apres_login_et_rejeu": _hashes_partiel(avant), "reponse": enveloppe}
    finally:
        stockage.liberer()


def _qualifier_partiel_affaire(moteur, facture_id, chantier, wct_id, tmp_path, monkeypatch, record_property):
    vue = _ar_partiel()
    facture = next(f for f in vue["factures"] if f["facture_id"] == facture_id)
    assert facture["devis_id"] == chantier.devis_id
    du = facture["montant_apres_taxes"]
    assert Decimal("10.00") < du  # Dû M5 réel, taxes jamais reconstruites par le test.
    racine = tmp_path / "m5-banque-verticale-fictive"
    racine.mkdir()
    (racine / "department.yaml").write_text(
        "configuration:\n  banque_csv:\n    comptes_internes: [compte-vertical-fictif]\n", encoding="utf-8",
    )
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, _OWNER_PARTIEL, "Finance fictive", _PASSWORD_PARTIEL, ["nathan_owner", "admin"])
    commande = {
        "mutation_id": "partiel-affaire-verticale-fictif", "compte_interne_id": "compte-vertical-fictif",
        "devise": "CAD", "mapping_colonnes": {"date": "Date", "montant": "Montant", "reference_facture": "Facture"},
        "csv_utf8": f"Date,Montant,Facture\n2026-09-30,10.00,{facture_id}\n",
    }
    with TestClient(_console_partiel(racine), base_url="http://testserver/opsys") as client:
        headers = _login_partiel(client)
        avant = _tables_partiel()  # Configuration, identité et login hors fenêtre métier.
        retour = client.post(_ROUTE_PARTIEL, json=commande, headers=headers)
        assert retour.status_code == 200, retour.text
        premiere = retour.json()
        projection = _donnee(premiere)
        assert projection["propositions"] == [{
            "ligne": 2, "facture_id": facture_id, "montant": "10.00", "statut": "PROPOSE_PARTIEL",
        }]
        assert projection["lignes"][0]["montant_du"] == format(du, ".2f")
        assert projection["version_rapprochement"] == "m5.3-partiel-unique/v1"
        apres = _tables_partiel()
        assert avant.keys() == apres.keys()
        assert {nom for nom in avant if avant[nom] != apres[nom]} == {
            "registres_maillons", "journal", "mutations_appliquees",
        }
        ajouts = {}
        with stockage.transaction() as cnx:
            meta = MetaData()
            for nom in ("registres_maillons", "journal", "mutations_appliquees"):
                assert not (avant[nom] - apres[nom]), f"ancienne ligne modifiée : {nom}"
                delta = apres[nom] - avant[nom]
                assert sum(delta.values()) == 1
                table = Table(nom, meta, autoload_with=cnx)
                ajouts[nom] = dict(zip(table.columns.keys(), next(iter(delta)), strict=True))
        maillon = ajouts["registres_maillons"]
        assert (maillon["departement"], maillon["registre"]) == ("m05-financecore", "rapprochements_bancaires_proposes")
        corps = json.loads(maillon["maillon"])
        assert corps["type_entree"] == "rapprochement_bancaire_propose"
        assert corps["resultat"] == projection and corps["auteur"] == _OWNER_PARTIEL
        audit, recu = ajouts["journal"], ajouts["mutations_appliquees"]
        assert (audit["par"], audit["action"], audit["cible"]) == (
            _OWNER_PARTIEL, "console.rapprochement_bancaire.propose", projection["lot_id"],
        )
        assert (recu["appareil"], recu["cle_idempotence"], recu["outil"], recu["statut"]) == (
            f"console:{_OWNER_PARTIEL}", commande["mutation_id"], "console_rapprochement_bancaire", "ok",
        )
        assert json.loads(recu["reponse"]) == premiere
    assert _ar_partiel() == vue
    manifeste = tmp_path / "rejeu-partiel-fictif.json"
    manifeste.write_text(json.dumps({"racine": str(racine), "commande": commande}))
    manifeste.chmod(0o600)
    moteur.arreter()
    stockage.liberer()
    try:
        environnement = {
            "PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1",
            stockage.ENV_URL: moteur.url_base, "OPSYS_HOME": os.environ["OPSYS_HOME"],
            "PYTHONPATH": os.pathsep.join([str(ROOT / "src"), str(ROOT / "tests/fixtures"),
                                          *[str(p) for p in sorted((ROOT / "departments").glob("*/src"))]]),
        }
        processus = subprocess.run([
            sys.executable, "-c",
            "import runpy,json,sys; m=runpy.run_path(sys.argv[1]); "
            "print(json.dumps(m['_rejouer_partiel_processus'](sys.argv[2])))",
            str(Path(__file__).resolve()), str(manifeste),
        ], cwd=ROOT, env=environnement, capture_output=True, text=True, timeout=60, check=False)
        assert processus.returncode == 0, processus.stderr
        preuve = json.loads(processus.stdout)
        assert preuve["pid"] != os.getpid()
        assert preuve["reponse"] == {**premiere, "rejoue": True}
        assert preuve["avant_login"] == preuve["apres_login_et_rejeu"] == _hashes_partiel(apres)
        assert _tables_partiel() == apres
    finally:
        manifeste.unlink(missing_ok=True)
        moteur.demarrer()
    assert _ar_partiel() == vue
    with TestClient(_console_partiel(racine), base_url="http://testserver/opsys") as client:
        headers = _login_partiel(client)
        with stockage.transaction() as cnx:
            identite.retirer_role(cnx, _OWNER_PARTIEL, "nathan_owner")
            identite.retirer_role(cnx, _OWNER_PARTIEL, "admin")
        avant_refus = _tables_partiel()  # Retrait explicite séparé du POST refusé.
        with monkeypatch.context() as garde:
            def interdit(*args, **kwargs):
                raise AssertionError("révocation doit précéder registre et reçu")
            garde.setattr(stockage, "maillons", interdit)
            garde.setattr("opsys.idempotence.reclamer", interdit)
            refus = client.post(_ROUTE_PARTIEL, json=commande, headers=headers)
            assert refus.status_code == 403
        assert _tables_partiel() == avant_refus
    record_property("m5_partiel_affaire", json.dumps({
        "fictif": True, "facture_id": facture_id, "devis_id": chantier.devis_id, "wct_id": wct_id,
        "du_snapshot": format(du, ".2f"), "montant_propose": "10.00", "lot_id": projection["lot_id"],
        "pid_parent": os.getpid(), "pid_rejeu": preuve["pid"], "tables": len(avant),
        "avant_proposition": _hashes_partiel(avant), "apres_proposition": _hashes_partiel(apres),
        "rejeu_sans_mutation": True, "revocation_sans_mutation": True, "manifeste_supprime": not manifeste.exists(),
    }, sort_keys=True))


@pytest.mark.parametrize(
    "quantite,prix_present,marge_attendue",
    [
        (42.0, True, "114.00"),
        (56.0, True, "2.00"),
        (42.0, False, None),
    ],
)
def test_affaire_unique_reprise_rejoint_facture_mesures_strategie_et_memoire(
    moteur, affaire, finance_fictive, quantite, prix_present, marge_attendue, tmp_path, monkeypatch, record_property
):
    chantier, lead, _ = _preparer_affaire(moteur, affaire)
    admin = affaire["admin"]
    if prix_present:
        _agent(
            moteur,
            admin,
            "m06-material-control",
            "m6_enregistrer_prix",
            {
                "materiau_id": MATERIAU_ID,
                "fournisseur_id": "fournisseur-vertical-fictif",
                "prix_unitaire": 8.0,
                "devise": "CAD",
                "date_effet": chantier.debut.date().isoformat(),
                "source_document": None,
            },
        )
    app = AppEmploye(moteur, affaire["employe"], chantier)
    completion = app.journee_jusqu_a_la_completion()
    assert completion.metier["accepte"] is True, completion.corps
    wct_id = completion.resultat["wct_id"]
    assert completion.resultat["intervention_id"] == chantier.intervention_id
    origine = _evenements("m1.lead_qualifie")[0][1]["lead"]
    assert origine["lead_id"] == chantier.lead_id and origine["utm"] == lead["utm"]
    wcts = [charge for _, charge in _evenements("m4.travaux_termines") if charge["wct_id"] == wct_id]
    assert len(wcts) == 1
    assert (wcts[0]["lead_id"], wcts[0]["devis_id"]) == (lead["lead_id"], chantier.devis_id)
    declaration = app.declarer_materiaux(wct_id, quantite)
    assert declaration.metier["accepte"] is True, declaration.corps
    _drainer(moteur)
    statut = app.statut().resultat["statut"]
    assert statut == ("completed_pending_review" if quantite == 56 else "completed_verified")
    if quantite == 56:
        non_verifie = _apprentissage(moteur, admin, wct_id)
        assert non_verifie["statut"] == "exclu", non_verifie
        assert "statut_courant_non_verifie" in non_verifie["exclusions"]
        avant = _empreinte(moteur)
        lecture = _app(moteur, admin, "m9_produire_lecture_strategique", {"maintenant": iso(moteur.horloge.maintenant)})
        assert lecture.resultat["decision"]["prise_par_m9"] is False
        item = next(item for item in lecture.resultat["lectures"] if item["chantier"] == wct_id)
        assert (item["valeur"], item["seuil"]) == ("40.00", "30.00")
        assert _empreinte(moteur) == avant
        def appeler_revue(outil, arguments, *, cle=None):
            avant_lecture = _empreinte(moteur) if cle is None else None
            reponse = _app(moteur, admin, outil, arguments, cle=cle)
            if cle is None:
                assert _empreinte(moteur) == avant_lecture, "lecture de sources sans mutation"
            return reponse

        sources = _sources_pour_revue(appeler_revue, chantier.intervention_id, wct_id, "classement-verticale")
        revue = _app(
            moteur,
            admin,
            "m4_resoudre_revue_completion_sources",
            {
                "intervention_id": chantier.intervention_id,
                "decision": "verifiee",
                "horodatage": iso(moteur.horloge.maintenant),
                "motif": "Revue fictive des sources M4/M6 relues.",
                "sources": sources,
            },
            cle="revue-verticale",
        )
        assert revue.enveloppe["statut"] == "en_attente_approbation", revue.corps
        with stockage.transaction() as cnx:
            assert cnx.scalar(
                select(APPROBATIONS.c.niveau).where(APPROBATIONS.c.id == revue.enveloppe["demande_id"])
            ) == "N4"
        decision = _app(
            moteur,
            admin,
            "m9_decider_demande_approbation",
            {"demande_id": revue.enveloppe["demande_id"], "decision": "approuver", "motif": "Revue fictive."},
            cle="decision-revue-verticale",
        )
        assert decision.resultat["statut"] == "executee", decision.corps
        preuve = decision.resultat["preuve_completion"]
        assert preuve["sources"] == sources and preuve["wct_id"] == wct_id
        assert preuve["demande_approbation_id"] == revue.enveloppe["demande_id"]
        assert preuve["association_decision"]["intention_uuid"] == "decision-revue-verticale"
        assert preuve["association_decision"]["appareil_id"] == admin.appareil_id
        assert preuve["association_decision"]["horodatage_appareil_declare"] == iso(moteur.horloge.maintenant)
        assert app.statut().resultat["statut"] == "completed_verified"
        _drainer(moteur)

    with stockage.transaction():
        factures = list(stockage.maillons("m05-financecore", "factures"))
    facture = next(f for f in factures if f.get("devis_id") == chantier.devis_id)
    assert facture["facture_id"] == f"fac-{chantier.devis_id}"
    assert facture["statut"] == "BROUILLON"
    avant = _empreinte(moteur)
    provisoire = _mesures(moteur, admin, wct_id)
    assert provisoire["m8_marge_reelle_cad"]["valeur"] is None
    assert provisoire["m8_marge_reelle_cad"]["statut"] == "non_calculable"
    assert _empreinte(moteur) == avant
    apprentissage_provisoire = _apprentissage(moteur, admin, wct_id)
    assert apprentissage_provisoire["statut"] == "observee", apprentissage_provisoire
    assert apprentissage_provisoire["rentabilite"]["statut"] == "exclue"
    assert apprentissage_provisoire["rentabilite"]["montant_marge_reelle_cad"] is None
    assert "facture_brouillon_ou_prix_non_definitif" in apprentissage_provisoire["rentabilite"]["exclusions"]
    lien = _app(
        moteur,
        admin,
        "m10_lier_session_affaire",
        {
            "cle_session": "agent:m05-financecore:webchat:direct:verticale-fictive",
            "affaire_id": lead["lead_id"],
            "motif": "Liaison humaine pour la finalité de cette affaire fictive.",
            "horodatage": iso(moteur.horloge.maintenant),
        },
        cle="liaison-finance-verticale",
    )
    assert lien.metier["accepte"] is True, lien.corps
    _agent(
        moteur,
        admin,
        "m05-financecore",
        "m5_envoyer_facture",
        {"facture_id": facture["facture_id"], "horodatage": iso(moteur.horloge.maintenant)},
        niveau_attendu="N4",
    )
    _drainer(moteur)
    avant = _empreinte(moteur)
    finales = _mesures(moteur, admin, wct_id)
    # Attendu indépendant : 600 - (quantité × 8 + 3 h × 50), ou inconnu sans prix.
    assert finales["m8_marge_reelle_cad"]["valeur"] == marge_attendue, finales["m8_marge_reelle_cad"]
    if not prix_present:
        assert finales["m8_marge_reelle_cad"]["statut"] == "non_calculable"
    assert _empreinte(moteur) == avant
    apprentissage_final = _apprentissage(moteur, admin, wct_id)
    assert apprentissage_final["statut"] == "observee", apprentissage_final
    _, devis_accepte = _evenements("m3.devis_accepte")[0]
    assert apprentissage_final["sources"]["devis_id"] == chantier.devis_id
    assert apprentissage_final["sources"]["estimation_hash"] == devis_accepte["estimation_source_hash"]
    assert apprentissage_final["sources"]["partition_calibration"] in {"train", "holdout"}
    assert Decimal(apprentissage_final["temps"]["estime_minutes"]) == Decimal("100")
    assert apprentissage_final["temps"]["ecoule_reel_minutes"] == 180
    assert apprentissage_final["temps"]["unite"] == "minute"
    assert apprentissage_final["temps"]["semantique"] == "duree_ecoulee_intervention"
    assert apprentissage_final["temps"]["trace_m3"]["unite_quantite"] == "pi"
    assert apprentissage_final["temps"]["paie_heures_personnes"] == "non mesurees par ces sources"
    assert apprentissage_final["variance_materiaux"]["cause"] is None
    rentabilite = apprentissage_final["rentabilite"]
    assert rentabilite["prix_definitif"] is True
    assert rentabilite["montant_marge_reelle_cad"] == marge_attendue
    assert rentabilite["statut"] == ("qualifiee" if prix_present else "exclue")
    if prix_present:
        assert rentabilite["cout_reel_complet"] is True and rentabilite["exclusions"] == []
        assert rentabilite["version_entrees_m5"] == rentabilite["version_entrees_m8"]
    else:
        assert "cout_reel_incomplet_ou_inconnu" in rentabilite["exclusions"]
    rentabilites = _evenements("m5.rentabilite_chantier")
    assert rentabilites and all(charge["wct_id"] == wct_id for _, charge in rentabilites)
    with stockage.transaction() as cnx:
        for evenement_id, charge in rentabilites:
            for consommateur in ("m08-analytics", "m10-memoire"):
                recu = cnx.execute(
                    select(EVENEMENTS_RECUS.c.statut).where(
                        EVENEMENTS_RECUS.c.evenement_id == evenement_id, EVENEMENTS_RECUS.c.consommateur == consommateur
                    )
                ).scalar_one()
                assert recu == "traite", (evenement_id, consommateur, charge)
    if (quantite, prix_present, marge_attendue) == (42.0, True, "114.00"):
        strategie = _app(moteur, admin, "m9_produire_lecture_strategique", {
            "maintenant": iso(moteur.horloge.maintenant),
        }).resultat
        _qualifier_partiel_affaire(
            moteur, facture["facture_id"], chantier, wct_id, tmp_path, monkeypatch, record_property,
        )
        assert _mesures(moteur, admin, wct_id) == finales
        assert _app(moteur, admin, "m9_produire_lecture_strategique", {
            "maintenant": iso(moteur.horloge.maintenant),
        }).resultat == strategie
        assert _apprentissage(moteur, admin, wct_id) == apprentissage_final
    avant = _empreinte(moteur)
    for appel in app.appels:
        rejeu = app.rejouer(appel)
        assert rejeu.enveloppe["rejoue"] is True, rejeu.corps
    _drainer(moteur)
    assert _empreinte(moteur) == avant


def test_affaire_recue_reste_privee_au_vendeur_assigne(moteur, affaire):
    chantier, _, _ = _preparer_affaire(moteur, affaire)
    avant = _empreinte(moteur)
    for outil, cle_id, connu, inconnu in (
        ("m2_trouver_client_de_lead", "lead_id", chantier.lead_id, "lead-absent-fictif"),
        ("m3_lire_devis", "devis_id", chantier.devis_id, "devis-absent-fictif"),
    ):
        existe = _app(moteur, affaire["autre"], outil, {cle_id: connu})
        absent = _app(moteur, affaire["autre"], outil, {cle_id: inconnu})
        assert existe.metier["accepte"] is absent.metier["accepte"] is False
        verdict_existe = dict(existe.metier["verdict"])
        verdict_absent = dict(absent.metier["verdict"])
        verdict_existe["detail"] = verdict_existe["detail"].replace(connu, "?")
        verdict_absent["detail"] = verdict_absent["detail"].replace(inconnu, "?")
        assert verdict_existe == verdict_absent
    assert _empreinte(moteur) == avant


def test_affaire_reprise_refuse_un_appareil_revoque_avant_son_geste(moteur, affaire):
    chantier, _, _ = _preparer_affaire(moteur, affaire)
    employe = affaire["employe"]
    assert cli.main(["appareils", "revoquer", employe.appareil_id, "--config-dir", str(moteur.config_dir)]) == 0
    avant = _empreinte(moteur)
    refus = employe.appeler(
        "m4_demarrer_route",
        {
            "intervention_id": chantier.intervention_id,
            "technicien_id": "etienne",
            "horodatage": iso(moteur.horloge.maintenant),
        },
        cle="route-apres-revocation-fictive",
        horodatage_appareil=iso(moteur.horloge.maintenant),
    )
    assert refus.statut == 403 and refus.ok is False
    assert _empreinte(moteur) == avant


def test_facture_de_cette_affaire_rollback_si_sa_publication_echoue(moteur, affaire, finance_fictive, monkeypatch):
    chantier, lead, _ = _preparer_affaire(moteur, affaire)
    admin = affaire["admin"]
    _agent(
        moteur,
        admin,
        "m06-material-control",
        "m6_enregistrer_prix",
        {
            "materiau_id": MATERIAU_ID,
            "fournisseur_id": "fournisseur-vertical-fictif",
            "prix_unitaire": 8.0,
            "devise": "CAD",
            "date_effet": chantier.debut.date().isoformat(),
            "source_document": None,
        },
    )
    app = AppEmploye(moteur, affaire["employe"], chantier)
    completion = app.journee_jusqu_a_la_completion()
    app.declarer_materiaux(completion.resultat["wct_id"], 42.0)
    _drainer(moteur)
    _app(
        moteur,
        admin,
        "m10_lier_session_affaire",
        {
            "cle_session": "agent:m05-financecore:webchat:direct:verticale-fictive",
            "affaire_id": lead["lead_id"],
            "motif": "Liaison financière fictive pour preuve de rollback.",
            "horodatage": iso(moteur.horloge.maintenant),
        },
        cle="liaison-rollback-fictive",
    )
    demande = _appeler_agent(
        moteur,
        "m05-financecore",
        "m5_envoyer_facture",
        {"facture_id": f"fac-{chantier.devis_id}", "horodatage": iso(moteur.horloge.maintenant)},
    )
    assert demande["statut"] == "en_attente_approbation", demande
    with stockage.transaction() as cnx:
        assert cnx.scalar(select(APPROBATIONS.c.niveau).where(APPROBATIONS.c.id == demande["demande_id"])) == "N4"

    def metier():
        with stockage.transaction() as cnx:
            return (
                [
                    dict(row._mapping)
                    for row in cnx.execute(
                        select(REGISTRES).order_by(REGISTRES.c.departement, REGISTRES.c.registre, REGISTRES.c.rang)
                    )
                ],
                _evenements("m5.rentabilite_chantier"),
            )

    def panne(*_args):
        raise RuntimeError("Publication financière en panne (fictif).")

    avant = metier()
    with monkeypatch.context() as injection:
        injection.setattr(m5_outils, "_publier_rentabilite", panne)
        decision = _app(
            moteur,
            admin,
            "m9_decider_demande_approbation",
            {"demande_id": demande["demande_id"], "decision": "approuver", "motif": "Finalité fictive."},
            cle="decision-panne-financiere-fictive",
        )
    assert decision.resultat["statut"] == "echec", decision.corps
    assert metier() == avant  # Registres métier et événements de rentabilité intégralement conservés.
    with stockage.transaction():
        facture = list(stockage.maillons("m05-financecore", "factures"))[-1]
    assert facture["statut"] == "BROUILLON"
