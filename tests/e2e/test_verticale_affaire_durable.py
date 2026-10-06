"""Une affaire fictive traverse les outils existants, sans événement métier fabriqué.

Première couche : moteur HTTP MCP réel, base durable et répartiteur dans un processus neuf.
La porte d'appareil du harnais reproduit la règle Core en Python : elle ne prouve pas le
Core TypeScript, un téléphone physique, un fournisseur ni une publication marketing.
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
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import anyio
import pytest
import yaml
from fastapi.testclient import TestClient
from harnais_e2e import DT_TZ, JETON_MCP, iso
from harnais_e2e_chantier import MATERIAU_ID, AppEmploye, Chantier, receptionner_materiel_args
from m1_front_office import outils as m1_outils
from m5_financecore import outils as m5_outils
from m8_analytics import outils as m8_outils
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client
from sqlalchemy import select

from opsys import approbations, cli, evenements, liaison_cibles, stockage, taxonomie
from opsys.capacites import Capacites, outils_executables
from opsys.console.application import creer_application
from opsys.console.securite import Configuration
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
    devis_id = "devis-vertical-fictif"
    _agent(
        moteur,
        admin,
        "m03-estimation",
        "m3_creer_devis",
        {
            "devis_id": devis_id,
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


@pytest.mark.parametrize(
    "quantite,prix_present,marge_attendue",
    [
        (42.0, True, "114.00"),
        (56.0, True, "2.00"),
        (42.0, False, None),
    ],
)
def test_affaire_unique_reprise_rejoint_facture_mesures_strategie_et_memoire(
    moteur, affaire, finance_fictive, quantite, prix_present, marge_attendue
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
    declaration = app.declarer_materiaux(wct_id, quantite)
    assert declaration.metier["accepte"] is True, declaration.corps
    _drainer(moteur)
    statut = app.statut().resultat["statut"]
    assert statut == ("completed_pending_review" if quantite == 56 else "completed_verified")
    if quantite == 56:
        avant = _empreinte(moteur)
        lecture = _app(moteur, admin, "m9_produire_lecture_strategique", {"maintenant": iso(moteur.horloge.maintenant)})
        assert lecture.resultat["decision"]["prise_par_m9"] is False
        item = next(item for item in lecture.resultat["lectures"] if item["chantier"] == wct_id)
        assert (item["valeur"], item["seuil"]) == ("40.00", "30.00")
        assert _empreinte(moteur) == avant
        revue = _app(
            moteur,
            admin,
            "m4_resoudre_revue_completion",
            {
                "intervention_id": chantier.intervention_id,
                "decision": "verifiee",
                "horodatage": iso(moteur.horloge.maintenant),
                "motif": "Écart fictif documenté et accepté.",
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
