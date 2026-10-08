"""T4.24 : trois lectures M7 HTTP/SQLite, sans publication et avec leurs enveloppes natives.

Le harnais expose le vrai serveur MCP ; sa porte Core est rejouée en Python.
Les sources fictives viennent d'un vrai parcours de complétion M4 et d'un profil M7 durable.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from m7_marketing.content import approval
from m7_marketing.social import postiz_adapter
from sqlalchemy import select
from tests.e2e.test_briefing_admin_appareil import empreinte_tables
from tests.e2e.test_usine_contenu_appareil import PROFIL_DU_CLIENT, _chantier_termine

from opsys import contexte, identite, stockage
from opsys.outils import executer_atomique
from opsys.stockage.schema import EVENEMENTS_SORTANTS, REGISTRES

FICTIF = True
SQLITE = pytest.mark.parametrize("moteur", ["sqlite"], indirect=True)
LISTES = ("m7_lister_file_approbation", "m7_lister_demandes_avis", "m7_lister_contenus_chantier")
RACINE = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def publication_interdite(monkeypatch):
    def interdit(*args, **kwargs):
        raise AssertionError("aucune publication externe dans le contrat des listes M7")

    monkeypatch.setattr(postiz_adapter.PostizAdapter, "publier", interdit)
    approval.reset()
    yield
    approval.reset()


def _preparer_sources(moteur, equipe):
    outils = {o.nom: o for o in moteur.departements["m07-marketing"].charger_outils()}
    with contexte.appele_par_appareil(contexte.IdentiteAppelante("nathan", "admin")):
        profil = executer_atomique(outils["m7_configurer_profil_marque"], {
            "profil": PROFIL_DU_CLIENT, "horodatage": moteur.horloge.maintenant.isoformat(),
        })
    assert profil["ok"] and profil["resultat"]["statut"] == "configure", profil
    propose = executer_atomique(outils["m7_proposer_contenu"], {
        "surface": "google_aio", "type": "post_social",
        "sujet": {"titre": "Gouttières à Repentigny (fictif)", "description": "Préparation de travaux fictifs."},
        "timestamp": moteur.horloge.maintenant.isoformat(),
    })
    assert propose["ok"] and propose["resultat"]["approval_status"] == "PROPOSE", propose
    chantier, _, completion = _chantier_termine(moteur, equipe, "M7-CONTRAT-FICTIF", 15, {
        "consentement_marketing": True, "consentement_demande_avis": True,
        "consentement_version_texte": "consentement-client-fr-CA-v1-fictif", "client_satisfait": True,
    })
    return chantier, completion.resultat["wct_id"]


@SQLITE
def test_trois_listes_directes_natives_pagination_consentement_et_fixture(moteur, equipe):
    chantier, wct_id = _preparer_sources(moteur, equipe)
    captures = {}
    admin = equipe["admin"]

    def lire(label, outil, args):
        avant = empreinte_tables()
        reponse = admin.appeler(outil, args)
        assert reponse.statut == 200 and reponse.ok, reponse.corps
        assert reponse.enveloppe["ok"] is True and not reponse.mesure.tronque, reponse.enveloppe
        assert reponse.mesure.octets_texte < 6000
        assert empreinte_tables() == avant
        if label is not None:
            assert label not in captures
            captures[label] = {"outil": outil, "args": args, "enveloppe": reponse.enveloppe}
        return reponse.enveloppe["resultat"]

    file = lire("file_propose", LISTES[0], {"statut": "PROPOSE"})
    avis = lire("avis", LISTES[1], {"limite": 8})
    premiere = lire("contenus", LISTES[2], {"limite": 8})
    assert isinstance(file, list) and len(file) == 1
    assert "accepte" not in avis and "accepte" not in premiere, "enveloppes DIRECTES, jamais un couple inventé"
    assert avis["total"] == 1 and avis["reste"] == 0
    assert avis["demandes"][0]["wct_id"] == wct_id
    assert avis["demandes"][0]["consentement"]["recueilli_par"] == "etienne"
    assert premiere["total"] == 5 and premiere["marque_courante"]["source"] == "brand_profiles"
    contenus = list(premiere["contenus"])
    page = premiere
    while page["suivant"] is not None:
        page = lire("contenus_suite" if "contenus_suite" not in captures else None, LISTES[2], {
            "limite": 8, "decalage": page["suivant"],
        })
        contenus.extend(page["contenus"])
    assert len({c["contenu_id"] for c in contenus}) == len(contenus) == 5
    assert all(c["approval_status"] == "PROPOSE" and c["fraicheur_marque"] == "courante" for c in contenus)
    assert all(c["consentement"]["recueilli_par"] == "etienne" for c in contenus)
    assert all("lead_id" not in c and "photos" not in c for c in contenus)

    # Un nouveau processus relit la même DB : file historique perdue, registres durables présents.
    avant = empreinte_tables()
    nouveau_processus = subprocess.run([
        sys.executable, "-c",
        "import json; from m7_marketing.outils import outils; from opsys.outils import executer_atomique; "
        "print(json.dumps({o.nom:executer_atomique(o,{})['resultat'] for o in outils() "
        "if o.nom in ('m7_lister_file_approbation','m7_lister_demandes_avis','m7_lister_contenus_chantier')}))",
    ], cwd=RACINE, capture_output=True, text=True, timeout=30, check=True)
    relues = json.loads(nouveau_processus.stdout)
    assert relues[LISTES[0]] == [] and relues[LISTES[1]]["total"] == 1 and relues[LISTES[2]]["total"] == 5
    assert empreinte_tables() == avant

    # Préparation interne de fixture : retrait marketing, sans effet sur le consentement distinct aux avis.
    retrait = admin.appeler("m7_enregistrer_retrait_consentement_marketing", {
        "wct_id": wct_id, "canal": "telephone", "horodatage": moteur.horloge.maintenant.isoformat(),
    }, cle="m7-contrat-retrait-fictif", horodatage_appareil=moteur.horloge.maintenant.isoformat())
    assert retrait.ok and retrait.metier["accepte"] is True, retrait.corps
    retirees = lire("consentement_retire", LISTES[2], {"wct_id": wct_id, "statut": "CONSENTEMENT_RETIRE", "limite": 8})
    assert retirees["total"] == 5 and all(c["approval_status"] == "CONSENTEMENT_RETIRE" for c in retirees["contenus"])
    assert lire(None, LISTES[1], {})["total"] == 1

    with stockage.transaction() as cnx:
        identite.activer(cnx, "nathan", False)
    for numero, nom in enumerate(LISTES):
        refus = lire(f"identite_revoquee_{numero}", nom, {})
        assert refus["accepte"] is False and refus["verdict"]["code"] == "REJ-IDENTITE-APPAREIL-INVALIDE"

    assert len(captures) <= 10
    destination = os.environ.get("OPSYS_M7_CONTRACT_FIXTURE_OUTPUT")
    if destination:
        sources = [
            "departments/m07-marketing/src/m7_marketing/outils.py",
            "departments/m07-marketing/src/m7_marketing/usine/service.py",
            "tests/e2e/test_marketing_admin_appareil.py", "tests/fixtures/harnais_e2e.py",
        ]
        export = {
            "fictif": True,
            "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=RACINE, text=True).strip(),
            "source": "HTTP MCP réel sur SQLite migrée ; porte Core rejouée en Python ; aucun téléphone/Core natif",
            "preparation": "profil marque durable + proposition legacy + parcours public M4 travaux terminés",
            "sources_sha256": {p: hashlib.sha256((RACINE / p).read_bytes()).hexdigest() for p in sources},
            "lead_id": chantier.lead_id, "wct_id": wct_id, "captures": captures,
            "limites": ["file legacy volatile attestée en nouveau processus", "avis sans curseur",
                        "contenus paginés par décalage et budget texte ; aucun snapshot figé"],
        }
        with Path(destination).open("x", encoding="utf-8") as fichier:
            json.dump(export, fichier, ensure_ascii=False, indent=2)
            fichier.write("\n")


@SQLITE
@pytest.mark.parametrize("role", ["employee", "seller"])
def test_les_autres_profils_ne_passent_pas_la_porte_m7(moteur, monkeypatch, role):
    personne = f"m7-{role}-fictif"
    moteur.creer_personne(personne, "Profil M7 fictif", [role], monkeypatch)
    porte = moteur.appairer(personne, role)
    for nom in LISTES:
        avant = empreinte_tables()
        assert porte.appeler(nom, {}).statut == 403
        assert empreinte_tables() == avant


@SQLITE
def test_admin_non_proprietaire_lit_les_trois_listes(moteur, monkeypatch):
    moteur.creer_personne("m7-gestionnaire", "Gestionnaire M7 fictive", ["admin"], monkeypatch)
    porte = moteur.appairer("m7-gestionnaire", "admin")
    for nom in LISTES:
        avant = empreinte_tables()
        reponse = porte.appeler(nom, {})
        assert reponse.ok and reponse.enveloppe["ok"] is True
        assert not isinstance(reponse.metier, dict) or reponse.metier.get("accepte") is not False
        assert empreinte_tables() == avant


DECIDER = "m7_decider_contenu"
CLE_DECISION = "7ab13215-9d9c-48fc-bd51-1737f50bc111"
CHAMPS_ACK = {
    "contenu_id", "plateforme", "approval_status", "par", "source", "horodatage",
    "empreinte_texte", "prochaine_etape",
}


def _etat_metier():
    """Les refus N3 peuvent écrire des audits, jamais un nouvel effet métier."""
    with stockage.transaction() as cnx:
        return {
            "registres": [dict(ligne) for ligne in cnx.execute(
                select(REGISTRES).order_by(REGISTRES.c.departement, REGISTRES.c.registre, REGISTRES.c.rang)
            ).mappings()],
            "evenements": [dict(ligne) for ligne in cnx.execute(
                select(EVENEMENTS_SORTANTS).order_by(EVENEMENTS_SORTANTS.c.evenement_id)
            ).mappings()],
        }


def _contenu_propose(admin):
    page = admin.appeler(LISTES[2], {"statut": "PROPOSE", "limite": 8})
    assert page.ok and not page.mesure.tronque
    contenu = page.resultat["contenus"][0]
    assert contenu["approval_status"] == "PROPOSE" and contenu["fraicheur_marque"] == "courante"
    return contenu


def _maillons_decision():
    with stockage.transaction():
        return list(stockage.maillons("m07-marketing", "decisions_contenu"))


def _appel_decision(porte, args, horodatage_appareil, cle=CLE_DECISION):
    reponse = porte.appeler(DECIDER, args, cle=cle, horodatage_appareil=horodatage_appareil)
    assert reponse.statut == 200 and reponse.ok and not reponse.mesure.tronque, reponse.corps
    return reponse


@SQLITE
def test_decision_owner_ack_couple_reprise_et_redemarrage_http(moteur, equipe):
    _, wct_id = _preparer_sources(moteur, equipe)
    admin = equipe["admin"]
    contenu = _contenu_propose(admin)
    heure_appareil = (moteur.horloge.maintenant - dt.timedelta(minutes=5)).isoformat()
    args = {"contenu_id": contenu["contenu_id"], "decision": "approuver", "horodatage": heure_appareil}

    # Simulation explicite d'une réponse perdue : le serveur répond, le client l'ignore puis reprend la même clé.
    premiere = _appel_decision(admin, args, heure_appareil)
    assert premiere.enveloppe["rejoue"] is False and premiere.metier["accepte"] is True
    assert set(premiere.metier) == {"accepte", "resultat"}
    ack = premiere.resultat
    assert set(ack) == CHAMPS_ACK
    assert (ack["contenu_id"], ack["plateforme"], ack["approval_status"], ack["par"], ack["source"]) == (
        contenu["contenu_id"], contenu["plateforme"], "APPROVED", "nathan", "appareil",
    )
    assert dt.datetime.fromisoformat(ack["horodatage"]) == moteur.horloge.maintenant
    assert ack["horodatage"] != heure_appareil and len(ack["empreinte_texte"]) == 64
    (maillon,) = _maillons_decision()
    assert maillon["contenu_id"] == contenu["contenu_id"] and maillon["role"] == "nathan_owner"
    avant_rejeu = empreinte_tables()
    reprise = _appel_decision(admin, args, heure_appareil)
    assert reprise.enveloppe["rejoue"] is True and reprise.metier == premiere.metier
    assert empreinte_tables() == avant_rejeu and _maillons_decision() == [maillon]

    # Arrêt et démarrage RÉELS du serveur HTTP, même base SQLite et même appareil.
    moteur.arreter()
    stockage.liberer()
    moteur.demarrer()
    avant_redemarrage_rejeu = empreinte_tables()
    apres_redemarrage = _appel_decision(admin, args, heure_appareil)
    assert apres_redemarrage.enveloppe["rejoue"] is True and apres_redemarrage.metier == premiere.metier
    assert empreinte_tables() == avant_redemarrage_rejeu and _maillons_decision() == [maillon]

    avant_conflit = empreinte_tables()
    conflit = _appel_decision(admin, {
        **args, "decision": "rejeter", "motif": "Autre décision fictive avec la même clé",
    }, heure_appareil)
    assert conflit.enveloppe["ok"] is False and conflit.enveloppe["erreur"] == "mutation_conflit"
    assert empreinte_tables() == avant_conflit and _maillons_decision() == [maillon]

    destination = os.environ.get("OPSYS_M7_DECISION_FIXTURE_OUTPUT")
    if destination:
        sources = [
            "tests/e2e/test_marketing_admin_appareil.py", "tests/fixtures/harnais_e2e.py",
            "departments/m07-marketing/src/m7_marketing/usine/service.py",
            "src/opsys/idempotence.py", "src/opsys/capacites.py",
        ]
        export = {
            "fictif": True, "wct_id": wct_id, "cle": CLE_DECISION,
            "source": "serveur HTTP MCP réel/SQLite ; porte Core simulée Python, aucun mobile/Core natif",
            "reponse_perdue": "simulée : première réponse HTTP reçue puis ignorée par le client du test",
            "redemarrage": "serveur uvicorn arrêté/redémarré, moteur SQL libéré, même base SQLite",
            "args": args, "horodatage_appareil": heure_appareil,
            "captures": {"premiere": premiere.enveloppe, "reprise": reprise.enveloppe,
                         "apres_redemarrage": apres_redemarrage.enveloppe, "conflit": conflit.enveloppe},
            "sources_sha256": {p: hashlib.sha256((RACINE / p).read_bytes()).hexdigest() for p in sources},
        }
        with Path(destination).open("x", encoding="utf-8") as fichier:
            json.dump(export, fichier, ensure_ascii=False, indent=2)
            fichier.write("\n")


@SQLITE
@pytest.mark.parametrize(("cas", "code"), [
    ("admin_non_owner", "REJ-HUMAIN-ROLE-INSUFFISANT"),
    ("owner_retire", "REJ-HUMAIN-ROLE-INSUFFISANT"),
    ("consentement_retire", "REJ-CONSENTEMENT-RETIRE"),
    ("marque_perimee", "REJ-MARQUE-PERIMEE"),
])
def test_decision_refusee_ne_cree_aucun_effet_metier(moteur, equipe, monkeypatch, cas, code):
    _, wct_id = _preparer_sources(moteur, equipe)
    porte = equipe["admin"]
    contenu = _contenu_propose(porte)
    horodatage = moteur.horloge.maintenant.isoformat()
    if cas == "admin_non_owner":
        moteur.creer_personne("gestionnaire-decision", "Gestionnaire fictive", ["admin"], monkeypatch)
        porte = moteur.appairer("gestionnaire-decision", "admin")
    elif cas == "owner_retire":
        with stockage.transaction() as cnx:
            identite.retirer_role(cnx, "nathan", "nathan_owner")
    elif cas == "consentement_retire":
        retrait = porte.appeler("m7_enregistrer_retrait_consentement_marketing", {
            "wct_id": wct_id, "canal": "telephone", "horodatage": horodatage,
        }, cle="m7-decision-retrait-fictif", horodatage_appareil=horodatage)
        assert retrait.ok and retrait.metier["accepte"] is True
    else:
        outil = next(o for o in moteur.departements["m07-marketing"].charger_outils()
                     if o.nom == "m7_configurer_profil_marque")
        with contexte.appele_par_appareil(contexte.IdentiteAppelante("nathan", "admin")):
            marque = executer_atomique(outil, {
                "profil": {**PROFIL_DU_CLIENT, "tagline": "Nouvelle accroche fictive"}, "horodatage": horodatage,
            })
        assert marque["ok"] and marque["resultat"]["statut"] == "configure"
    avant = _etat_metier()
    avant_socle = moteur.empreinte_etat()
    args = {"contenu_id": contenu["contenu_id"], "decision": "approuver", "horodatage": horodatage}
    refus = _appel_decision(porte, args, horodatage)
    assert refus.enveloppe["ok"] is True and refus.metier["accepte"] is False, refus.enveloppe
    assert refus.metier["verdict"]["code"] == code
    assert _etat_metier() == avant and _maillons_decision() == []
    apres_socle = moteur.empreinte_etat()
    assert apres_socle["mutations"] == avant_socle["mutations"] + 1
    assert apres_socle["approbations"] == avant_socle["approbations"] + 1
    assert apres_socle["journal"] > avant_socle["journal"], "la tentative refusée N3 est auditée"
    # Le même refus repris n'ajoute même pas une seconde trace.
    avant_rejeu = empreinte_tables()
    rejoue = _appel_decision(porte, args, horodatage)
    assert rejoue.enveloppe["rejoue"] is True and rejoue.metier == refus.metier
    assert empreinte_tables() == avant_rejeu
