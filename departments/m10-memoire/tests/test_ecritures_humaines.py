"""Signaux critiques et liaison de session : jamais écrits par le modèle seul (PLAN T3.3-suite-b).

Ces tests passent par les VRAIS outils de M10, `Capacites` (mode `ombre` du manifeste), la file
d'approbation réelle (`approbations.decider`) et l'identité d'appareil posée comme le fait le serveur MCP
(`contexte.appele_par_appareil`), sur une base SQLite migrée. Ils prouvent la phrase de la tâche : un signal
critique est clos par un humain (outil N3, portée admin, identité authentifiée pour un appel d'appareil) et
jamais par le modèle seul — y compris dans un mode (`supervise`, `autonome`) où un N3 s'exécute sans file.

Données fictives (`fictif: true`) : personnes, appareils, affaires, événements.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import socket
import threading
import time
from pathlib import Path

import anyio
import pytest
import uvicorn
from m10_memoire import amont, etapes, liaison, signaux, wct
from m10_memoire import outils as outils_m10
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client
from sqlalchemy import update

from opsys import approbations, contexte, idempotence, identite, openclaw, stockage
from opsys.capacites import Capacites, outils_executables
from opsys.departements import PolitiqueApprobation, charger_departements
from opsys.outils import Niveau, executer, executer_atomique
from opsys.serveur_mcp import application_http_departements
from opsys.stockage.schema import APPROBATIONS

FICTIF = True
RACINE_DEPARTEMENTS = Path(__file__).resolve().parents[2]
ADMIN = contexte.IdentiteAppelante(personne="admin.fictif", role="admin")
EMPLOYE = contexte.IdentiteAppelante(personne="employe.fictif", role="employee")
CLE_CLIENT = "agent:m01-front-office:whatsapp:direct:+15145550101"
MOTIF = "Écart expliqué avec le client : la gouttière a été refaite."
HORLOGE_APPAREIL_DEREGLEE = "2000-01-01T00:00:00+00:00"
HORODATAGE = "2030-01-01T12:00:00+00:00"


def _port_libre():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


# -- installation -----------------------------------------------------------------------------------
@pytest.fixture
def instance(tmp_path, monkeypatch):
    (tmp_path / "home").mkdir()
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "home"))
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "nathan", "Nathan Fictif", "mot-de-passe-nathan-12345", ["nathan_owner"])
        identite.creer_personne(cnx, "admin.fictif", "Admin Fictive", "mot-de-passe-admin-12345", ["admin"])
        identite.creer_personne(cnx, "employe.fictif", "Employé Fictif", "mot-de-passe-employe-1234", ["employee"])
    yield tmp_path
    stockage.liberer()


@pytest.fixture
def capacites(instance):
    return Capacites(charger_departements(RACINE_DEPARTEMENTS), stockage.transaction, filtre={"m10-memoire"},
                     memoire=False)


@pytest.fixture
def par_nom(capacites):
    return {o.nom: o for o in capacites.lister()}


def _wct(wct_id="WCT-1", lead_id="LEAD-1"):
    return {
        "wct_id": wct_id, "intervention_id": f"int-{wct_id}", "lead_id": lead_id, "technicien_id": "TECH-1",
        "horodatage_completion": "2026-09-15T14:00:00-04:00",
        "fix_gps_completion": {"latitude": 46.8, "longitude": -71.2},
        "duree_reelle_minutes": 90, "ecart_signale": False, "revue_id": None, "hash_maillon": "a" * 64,
        "consommateurs_cibles": ["M10"], "devis_id": f"devis-{wct_id}",
    }


def _variance(evenement_id="EVT-1", wct_id="WCT-1", critique=True):
    return {
        "evenement_id": evenement_id, "wct_id": wct_id, "intervention_id": f"int-{wct_id}", "chantier_id": "CH-1",
        "statut_variance": "evaluee", "signal_critique": critique, "seuil_pourcentage": 0.1,
        "horodatage_completion": "2026-09-15T14:00:00-04:00", "lignes": [],
    }


@pytest.fixture
def signal(instance):
    """Un signal critique OUVERT (EVT-1) de l'affaire LEAD-1, arrivé par le bus comme en production."""
    consommateurs = outils_m10.consommateurs()
    with stockage.transaction():
        consommateurs["m4.travaux_termines"](_wct())
        consommateurs["m6.variance_chantier"](_variance())
    return "EVT-1"


def _args_signal(signal_id="EVT-1", motif=MOTIF, horodatage=HORODATAGE):
    return {"signal_id": signal_id, "motif": motif, "horodatage": horodatage}


def _meta(cle="mut-1") -> idempotence.Meta:
    return idempotence.Meta(cle=cle, appareil="tel-admin-fictif-1", horodatage_appareil=HORLOGE_APPAREIL_DEREGLEE)


def _appareil(capacites, nom, arguments, identite_appelante, cle="mut-1"):
    with contexte.appele_par_appareil(identite_appelante):
        return capacites.appeler(nom, arguments, _meta(cle))


def _signaux(capacites, affaire="LEAD-1"):
    reponse = capacites.appeler("m10_lister_signaux", {"affaire_id": affaire})
    assert reponse["ok"] is True, reponse
    return {s["signal_id"]: s for s in reponse["resultat"]["signaux"]}


def _traitements():
    with stockage.transaction():
        maillons = outils_m10._REGISTRE_AFFAIRES.lire()
    return [m for m in maillons if m["type_entree"] == signaux.TYPE_ENTREE_SIGNAL_TRAITE]


def _liens():
    with stockage.transaction():
        maillons = outils_m10._REGISTRE_AFFAIRES.lire()
    return [m for m in maillons if m["type_entree"] == liaison.TYPE_ENTREE_LIAISON]


def _approuver(capacites, demande_id, approuve_par="nathan"):
    with stockage.transaction() as cnx:
        return approbations.decider(
            cnx, demande_id, True, approuve_par,
            outils_executables(capacites.departements, stockage.transaction), capacites.departements,
        )


def _demandes(statut=None):
    with stockage.transaction() as cnx:
        return approbations.lister(cnx, statut)


# -- 1. l'agent propose, l'humain approuve : la seule voie non-appareil -----------------------------
def test_les_trois_ecritures_humaines_sont_des_n3_de_la_portee_admin(par_nom):
    for nom in ("m10_prendre_en_compte_signal", "m10_clore_signal", "m10_lier_session_affaire"):
        outil = par_nom[nom]
        assert outil.niveau_effectif is Niveau.N3, nom
        assert outil.roles_appareil == {"admin"}, nom
        assert outil.frontiere_humaine is False


def test_un_agent_en_mode_ombre_ne_fait_que_proposer_et_rien_n_est_ecrit(capacites, signal):
    assert capacites.departements["m10-memoire"].mode == "ombre"

    reponse = capacites.appeler("m10_prendre_en_compte_signal", _args_signal())

    assert reponse["ok"] is True and reponse["statut"] == "en_attente_approbation"
    assert _traitements() == []
    assert _signaux(capacites)["EVT-1"]["etat"] == "ouvert"
    [demande] = _demandes("en_attente")
    assert (demande["outil"], demande["niveau"]) == ("m10_prendre_en_compte_signal", "N3")


def test_l_approbation_du_proprietaire_ecrit_son_nom_sa_voie_et_le_motif(capacites, signal):
    demande = capacites.appeler("m10_prendre_en_compte_signal", _args_signal())["demande_id"]

    resultat = _approuver(capacites, demande)

    assert resultat["statut"] == "executee" and resultat["reponse"]["resultat"]["accepte"] is True
    [maillon] = _traitements()
    assert (maillon["etat_resultant"], maillon["par"], maillon["role"], maillon["source_decision"]) == (
        "pris_en_compte", "nathan", "nathan_owner", "approbation")
    assert (maillon["motif"], maillon["horodatage"]) == (MOTIF, HORODATAGE)
    assert _signaux(capacites)["EVT-1"]["etat"] == "pris_en_compte"


def test_cycle_complet_par_approbations_ouvert_pris_en_compte_clos(capacites, signal):
    _approuver(capacites, capacites.appeler("m10_prendre_en_compte_signal", _args_signal())["demande_id"])
    motif_clos = "Le client a accepté la facture révisée du chantier."
    demande = capacites.appeler("m10_clore_signal", _args_signal(motif=motif_clos))["demande_id"]

    resultat = _approuver(capacites, demande)

    assert resultat["statut"] == "executee"
    clos = _signaux(capacites)["EVT-1"]
    assert (clos["etat"], clos["traite_par"], clos["motif"]) == ("clos", "nathan", motif_clos)
    assert [m["etat_resultant"] for m in _traitements()] == ["pris_en_compte", "clos"]


def test_une_demande_de_cloture_approuvee_trop_tot_est_refusee_par_l_ordre_du_cycle(capacites, signal):
    demande = capacites.appeler("m10_clore_signal", _args_signal())["demande_id"]

    resultat = _approuver(capacites, demande)

    assert resultat["reponse"]["resultat"]["accepte"] is False
    assert resultat["reponse"]["resultat"]["verdict"]["code"] == signaux.REJ_SIGNAL_PAS_PRIS_EN_COMPTE
    assert _traitements() == []


def test_un_role_qui_n_est_pas_autorise_pour_n3_ne_peut_pas_approuver(capacites, signal):
    demande = capacites.appeler("m10_clore_signal", _args_signal())["demande_id"]

    with pytest.raises(ValueError, match="aucun rôle autorisé"):
        _approuver(capacites, demande, approuve_par="admin.fictif")  # M10 : N3 = nathan_owner seul par défaut

    assert _traitements() == []
    assert [d["statut"] for d in _demandes()] == ["en_attente"]


# -- 2. le modèle seul ne clôt jamais, même sans file d'approbation ---------------------------------
@pytest.mark.parametrize("mode", ["supervise", "autonome"])
@pytest.mark.parametrize("nom", ["m10_prendre_en_compte_signal", "m10_clore_signal"])
def test_un_agent_seul_est_refuse_dans_un_mode_ou_le_n3_s_execute_sans_file(capacites, signal, mode, nom):
    with stockage.transaction() as cnx:
        approbations.fixer_mode(cnx, "m10-memoire", mode, "nathan")

    reponse = capacites.appeler(nom, _args_signal())

    assert reponse["ok"] is True and "statut" not in reponse  # exécuté, pas mis en attente...
    assert reponse["resultat"]["accepte"] is False  # ...et refusé par l'outil
    verdict = reponse["resultat"]["verdict"]
    assert verdict["code"] == "REJ-HUMAIN-REQUIS" and "un agent ne peut pas la faire seul" in verdict["detail"]
    assert _traitements() == []
    assert _signaux(capacites)["EVT-1"]["etat"] == "ouvert"
    assert _demandes() == []


def test_un_appel_direct_sans_aucun_contexte_est_refuse(par_nom, signal):
    reponse = executer_atomique(par_nom["m10_prendre_en_compte_signal"], _args_signal())

    assert reponse["ok"] is True and reponse["resultat"]["verdict"]["code"] == "REJ-HUMAIN-REQUIS"
    assert _traitements() == []


def test_un_appel_direct_hors_transaction_est_refuse_meme_avec_une_identite(par_nom, signal):
    with contexte.appele_par_appareil(ADMIN):
        reponse = executer(par_nom["m10_prendre_en_compte_signal"], _args_signal())  # ni transaction ni base jointe

    assert reponse["resultat"]["verdict"]["code"] == "REJ-HUMAIN-IDENTITE-INVALIDE"
    assert _traitements() == []


# -- 2 bis. ce que le SOCLE dit d'une approbation (T4.15-d : M10 ne lit plus la table des approbations) --------------
# `approbations.decider` pose la demande qu'il exécute et `approbations.approbateur_en_cours` dit qui l'a approuvée : la
# matrice complète (autre outil, personne inactive, rôle d'agent, pointeur contrefait) est dans
# `tests/test_approbateur_en_cours.py`. Ici : ce que M10 en fait, par le VRAI `decider` chaque fois qu'il peut le faire.
def _forcer_une_decision_en_cours(nom_outil, arguments, *, decide_par="nathan", decide_role="nathan_owner",
                                  statut="en_cours", departement="m10-memoire"):
    """Écrit à la main, dans la file, la ligne que `approbations.decider` écrit au moment d'exécuter, SANS que
    `decider` s'exécute : ce que ferait un agent qui parviendrait à écrire dans la table. Rend l'identifiant."""
    with stockage.transaction() as cnx:
        ident = approbations.creer_demande(cnx, departement, nom_outil, arguments, niveau=Niveau.N3)
        cnx.execute(update(APPROBATIONS).where(APPROBATIONS.c.id == ident).values(
            statut=statut, decide_par=decide_par, decide_role=decide_role))
    return ident


def _appel_dans_la_meme_transaction(par_nom, nom_outil, arguments):
    with stockage.transaction():
        return executer(par_nom[nom_outil], arguments)


def _personnes_de_roles_larges():
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "gestion", "Gestionnaire Fictive", "mot-de-passe-gestion-1234", ["manager"])
        identite.creer_personne(cnx, "robot", "Agent Fictif", "mot-de-passe-robot-123456", ["system_agent"])


def _approuver_sous_une_politique_elargie(capacites, nom_outil, arguments, par, roles_n3):
    """Le VRAI `decider`, dans un département dont la politique N3 admet `roles_n3` : la file accepte alors ces
    rôles, et l'outil décide seul lesquels il reconnaît comme humains."""
    dep = dataclasses.replace(
        capacites.departements["m10-memoire"],
        politique_approbation=PolitiqueApprobation(roles={Niveau.N3: frozenset(roles_n3)}))
    departements = {dep.id: dep}
    with stockage.transaction() as cnx:
        ident = approbations.creer_demande(cnx, dep.id, nom_outil, arguments, niveau=Niveau.N3)
    with stockage.transaction() as cnx:
        return approbations.decider(
            cnx, ident, True, par, outils_executables(departements, stockage.transaction), departements)


@pytest.mark.parametrize(
    "cas",
    [
        {},  # exactement la ligne que `decider` écrit : approbateur humain actif, cet outil, ce département
        {"statut": "en_attente"},  # une demande que personne n'a encore approuvée
        {"statut": "refusee"},
        {"statut": "executee"},
        {"decide_par": None, "decide_role": None},
        {"decide_par": "employe.fictif", "decide_role": "employee"},  # un rôle qui n'est pas humain-décideur
        {"decide_par": "inconnu.fictif", "decide_role": "nathan_owner"},  # personne inconnue
        {"decide_par": "employe.fictif", "decide_role": "nathan_owner"},  # ne porte pas le rôle
        {"departement": "m03-estimation"},  # une demande d'un autre département
    ],
    ids=["bien_formee", "en_attente", "refusee", "executee", "sans_approbateur", "role_employe", "personne_inconnue",
         "sans_le_role", "autre_departement"],
)
def test_une_ligne_ecrite_a_la_main_ne_donne_aucun_droit_meme_bien_formee(par_nom, signal, cas):
    """Ce que M10 acceptait avant T4.15-d (une demande `en_cours` de cet outil, aux mêmes arguments, d'un approbateur
    humain actif) ne vaut plus rien sans que `decider` soit en train d'exécuter."""
    _forcer_une_decision_en_cours("m10_prendre_en_compte_signal", _args_signal(), **cas)

    reponse = _appel_dans_la_meme_transaction(par_nom, "m10_prendre_en_compte_signal", _args_signal())

    assert reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "REJ-HUMAIN-REQUIS"
    assert _traitements() == []


def test_l_approbation_d_une_demande_ne_sert_ni_apres_elle_ni_a_un_autre_outil(capacites, par_nom, signal):
    """Le socle ne dit qui a approuvé que PENDANT `decider` : le même outil appelé ensuite avec un autre motif, ou
    l'autre outil du cycle, n'y gagne rien."""
    demande = capacites.appeler("m10_prendre_en_compte_signal", _args_signal())["demande_id"]
    assert _approuver(capacites, demande)["statut"] == "executee"

    autre_motif = executer_atomique(
        par_nom["m10_prendre_en_compte_signal"], _args_signal(motif="Un autre motif, approuvé."))
    cloture = executer_atomique(par_nom["m10_clore_signal"], _args_signal())

    assert autre_motif["resultat"]["verdict"]["code"] == "REJ-HUMAIN-REQUIS"
    assert cloture["resultat"]["verdict"]["code"] == "REJ-HUMAIN-REQUIS"
    assert [m["etat_resultant"] for m in _traitements()] == ["pris_en_compte"]


@pytest.mark.parametrize("par, role", [("gestion", "manager"), ("employe.fictif", "employee"),
                                       ("robot", "system_agent")])
def test_un_role_que_la_file_admet_mais_que_l_outil_ne_reconnait_pas_n_ecrit_rien(capacites, signal, par, role):
    """Le manifeste peut élargir la politique N3 : le moteur appelle l'outil, qui refuse et fait échouer la demande;
    il n'admet comme
    humains que `admin` et `nathan_owner` (`humain.roles_humains()`)."""
    _personnes_de_roles_larges()

    decision = _approuver_sous_une_politique_elargie(
        capacites, "m10_prendre_en_compte_signal", _args_signal(), par, {role, "nathan_owner"})

    assert decision["statut"] == "echec", decision
    assert decision["reponse"]["resultat"]["accepte"] is False
    assert decision["reponse"]["resultat"]["verdict"]["code"] == "REJ-HUMAIN-REQUIS"
    assert _traitements() == []


def test_un_admin_que_la_file_admet_ecrit_sous_son_role_par_la_voie_approbation(capacites, signal):
    decision = _approuver_sous_une_politique_elargie(
        capacites, "m10_prendre_en_compte_signal", _args_signal(), "admin.fictif", {"admin", "nathan_owner"})

    assert decision["reponse"]["resultat"]["accepte"] is True
    [maillon] = _traitements()
    assert (maillon["par"], maillon["role"], maillon["source_decision"]) == ("admin.fictif", "admin", "approbation")


def test_une_demande_d_un_autre_departement_n_autorise_pas_l_outil_de_m10(capacites, signal):
    """`decider` appelle l'outil nommé, mais échoue le résultat car la demande porte sur `m03-estimation` : M10 ne
    reconnaît que les demandes de son propre département."""
    with stockage.transaction() as cnx:
        ident = approbations.creer_demande(
            cnx, "m03-estimation", "m10_prendre_en_compte_signal", _args_signal(), niveau=Niveau.N3)
    with stockage.transaction() as cnx:
        decision = approbations.decider(
            cnx, ident, True, "nathan", outils_executables(capacites.departements, stockage.transaction),
            capacites.departements)

    assert decision["statut"] == "echec", decision
    assert decision["reponse"]["resultat"]["accepte"] is False
    assert decision["reponse"]["resultat"]["verdict"]["code"] == "REJ-HUMAIN-REQUIS"
    assert _traitements() == []


def test_un_approbateur_desactive_depuis_la_reservation_ne_donne_plus_de_droit(capacites, signal):
    """`decider` a réservé la demande sous `nathan`, alors actif ; l'outil relit la base à l'instant d'écrire."""
    executables = outils_executables(capacites.departements, stockage.transaction)
    reel = executables["m10_prendre_en_compte_signal"]

    def _desactiver_puis_ecrire(**arguments):
        identite.activer(stockage.connexion_courante(), "nathan", False)
        return reel.fonction(**arguments)

    executables["m10_prendre_en_compte_signal"] = dataclasses.replace(reel, fonction=_desactiver_puis_ecrire)
    demande = capacites.appeler("m10_prendre_en_compte_signal", _args_signal())["demande_id"]
    with stockage.transaction() as cnx:
        decision = approbations.decider(cnx, demande, True, "nathan", executables, capacites.departements)

    assert decision["reponse"]["resultat"]["verdict"]["code"] == "REJ-HUMAIN-REQUIS"
    assert _traitements() == []


# -- 3. l'appareil : l'identité authentifiée décide, jamais un argument ------------------------------
def test_l_admin_authentifie_prend_en_compte_depuis_son_appareil_sans_file_et_avec_sa_trace(capacites, signal):
    reponse = _appareil(capacites, "m10_prendre_en_compte_signal", _args_signal(horodatage=HORLOGE_APPAREIL_DEREGLEE),
                        ADMIN)

    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True
    assert "statut" not in reponse  # pas de mise en attente : il a validé au départ en agissant
    [maillon] = _traitements()
    assert (maillon["par"], maillon["role"], maillon["source_decision"]) == ("admin.fictif", "admin", "appareil")
    # L'heure de RÉCEPTION du serveur fait foi, jamais celle, déréglée, de l'appareil.
    assert maillon["horodatage"] != HORLOGE_APPAREIL_DEREGLEE
    assert dt.datetime.fromisoformat(maillon["horodatage"]).year >= 2026
    # La validation au départ laisse sa trace dans le journal des approbations, comme pour tout N3.
    [trace] = _demandes("executee")
    assert (trace["decide_par"], trace["decide_role"], trace["outil"]) == (
        "admin.fictif", "admin", "m10_prendre_en_compte_signal")


def test_l_admin_authentifie_clot_apres_la_prise_en_compte(capacites, signal):
    assert _appareil(capacites, "m10_prendre_en_compte_signal", _args_signal(), ADMIN, "mut-1")["ok"] is True

    reponse = _appareil(capacites, "m10_clore_signal", _args_signal(motif="Facture révisée acceptée par le client."),
                        ADMIN, "mut-2")

    assert reponse["resultat"]["accepte"] is True
    clos = _signaux(capacites)["EVT-1"]
    assert (clos["etat"], clos["traite_par"]) == ("clos", "admin.fictif")


def test_un_nom_fourni_dans_les_arguments_n_est_pas_une_identite(capacites, signal):
    arguments = {**_args_signal(), "par": "nathan", "role": "nathan_owner"}

    reponse = _appareil(capacites, "m10_prendre_en_compte_signal", arguments, ADMIN)

    assert reponse["ok"] is False and reponse["erreur"] == "arguments_invalides"
    assert _traitements() == []


def test_un_employe_ne_peut_pas_prendre_en_compte_un_signal_depuis_son_appareil(capacites, signal):
    reponse = _appareil(capacites, "m10_prendre_en_compte_signal", _args_signal(), EMPLOYE)

    assert reponse["ok"] is False and reponse["erreur"] == "hors_portee_role"
    assert _traitements() == []


@pytest.mark.parametrize("mode", ["supervise", "autonome"])
def test_un_role_d_appareil_autre_qu_admin_est_refuse_par_l_outil_lui_meme(capacites, signal, mode):
    """Défense en profondeur : si un jeton d'employé arrivait jusqu'à l'outil dans un mode sans file, l'outil
    refuse encore (le core l'aurait déjà refusé en amont)."""
    with stockage.transaction() as cnx:
        approbations.fixer_mode(cnx, "m10-memoire", mode, "nathan")

    reponse = _appareil(capacites, "m10_prendre_en_compte_signal", _args_signal(), EMPLOYE)

    assert reponse["resultat"]["verdict"]["code"] == "REJ-HUMAIN-ROLE-INSUFFISANT"
    assert _traitements() == []


@pytest.mark.parametrize("perte", ["role_retire", "personne_desactivee", "personne_inconnue"])
def test_une_identite_d_appareil_que_la_base_ne_confirme_plus_ne_decide_rien(capacites, signal, perte):
    """`_meta` dit `admin`, la base dit autre chose : en mode sans file, l'outil refuse ; en mode `ombre`, la
    voie « humain qui agit » n'est pas prise et l'appel suit la file (rien n'est exécuté)."""
    identite_appelante = ADMIN
    with stockage.transaction() as cnx:
        if perte == "role_retire":
            identite.ajouter_role(cnx, "admin.fictif", "employee")
            identite.retirer_role(cnx, "admin.fictif", "admin")
        elif perte == "personne_desactivee":
            identite.activer(cnx, "admin.fictif", False)
        else:
            identite_appelante = contexte.IdentiteAppelante(personne="fantome.fictif", role="admin")

    en_ombre = _appareil(capacites, "m10_prendre_en_compte_signal", _args_signal(), identite_appelante, "mut-1")
    assert en_ombre["ok"] is True and en_ombre["statut"] == "en_attente_approbation"
    assert _traitements() == []

    with stockage.transaction() as cnx:
        approbations.fixer_mode(cnx, "m10-memoire", "supervise", "nathan")
    sans_file = _appareil(capacites, "m10_prendre_en_compte_signal", _args_signal(), identite_appelante, "mut-2")
    assert sans_file["resultat"]["verdict"]["code"] == "REJ-HUMAIN-IDENTITE-INVALIDE"
    assert _traitements() == []


# -- 4. la liste, la liaison de session, le marquage ------------------------------------------------
def test_la_liste_des_signaux_est_une_lecture_sans_approbation_ni_ecriture(capacites, signal, par_nom):
    assert par_nom["m10_lister_signaux"].niveau_effectif is Niveau.N0
    reponse = _appareil(capacites, "m10_lister_signaux", {"affaire_id": "LEAD-1"}, ADMIN)

    assert reponse["ok"] is True
    [un] = reponse["resultat"]["signaux"]
    assert (un["signal_id"], un["etat"], un["affaire_id"]) == ("EVT-1", "ouvert", "LEAD-1")
    assert reponse["resultat"]["nb_ouverts"] == 1
    assert _traitements() == [] and _demandes() == []


def test_lier_une_session_par_approbation_puis_la_lire(capacites, instance):
    arguments = {"cle_session": CLE_CLIENT, "affaire_id": "LEAD-1", "motif": "Le client a écrit depuis ce numéro.",
                 "horodatage": HORODATAGE}
    assert capacites.appeler("m10_affaire_de_la_session", {"cle_session": CLE_CLIENT})["resultat"] == {
        "lie": False, "affaire_id": None}

    demande = capacites.appeler("m10_lier_session_affaire", arguments)["demande_id"]
    assert _liens() == []
    _approuver(capacites, demande)

    lu = capacites.appeler("m10_affaire_de_la_session", {"cle_session": CLE_CLIENT})["resultat"]
    assert lu == {"lie": True, "affaire_id": "LEAD-1", "lie_par": "nathan", "lie_le": HORODATAGE}
    [lien] = _liens()
    assert (lien["par"], lien["source_decision"]) == ("nathan", "approbation")


def test_lier_une_session_depuis_l_appareil_de_l_admin(capacites, instance):
    arguments = {"cle_session": CLE_CLIENT, "affaire_id": "LEAD-7", "motif": "Le client a écrit depuis ce numéro.",
                 "horodatage": HORLOGE_APPAREIL_DEREGLEE}

    reponse = _appareil(capacites, "m10_lier_session_affaire", arguments, ADMIN)

    assert reponse["resultat"]["accepte"] is True
    lu = capacites.appeler("m10_affaire_de_la_session", {"cle_session": CLE_CLIENT})["resultat"]
    assert (lu["affaire_id"], lu["lie_par"]) == ("LEAD-7", "admin.fictif")


@pytest.mark.parametrize("mode", ["supervise", "autonome"])
def test_un_agent_seul_ne_lie_jamais_une_session_a_une_affaire(capacites, instance, mode):
    with stockage.transaction() as cnx:
        approbations.fixer_mode(cnx, "m10-memoire", mode, "nathan")
    arguments = {"cle_session": CLE_CLIENT, "affaire_id": "LEAD-AUTRE-CLIENT", "motif": "Le client dit que c'est lui.",
                 "horodatage": HORODATAGE}

    reponse = capacites.appeler("m10_lier_session_affaire", arguments)

    assert reponse["resultat"]["verdict"]["code"] == "REJ-HUMAIN-REQUIS"
    assert _liens() == []
    assert capacites.appeler("m10_affaire_de_la_session", {"cle_session": CLE_CLIENT})["resultat"]["lie"] is False


def test_lire_l_affaire_d_une_cle_invalide_est_un_refus_metier(capacites, instance):
    reponse = capacites.appeler("m10_affaire_de_la_session", {"cle_session": "agent:m01-front-office:main"})

    assert reponse["ok"] is False and reponse["erreur"] == "refus_metier"


def test_la_lecture_de_la_liaison_est_fermee_aux_appareils_et_l_ecriture_est_reservee_a_l_admin(capacites):
    roles = openclaw.roles_outils(capacites.departements)

    assert "m10_affaire_de_la_session" not in {nom for noms in roles.values() for nom in noms}
    assert set(roles["admin"]) >= {"m10_lier_session_affaire", "m10_lister_signaux", "m10_clore_signal",
                                   "m10_prendre_en_compte_signal"}
    assert not (set(roles["employee"]) | set(roles["seller"])) & {n for n in roles["admin"] if n.startswith("m10_")}


def test_le_paquet_de_l_outil_montre_l_etat_des_signaux_et_le_filtre_de_l_agent(capacites, signal, par_nom):
    _approuver(capacites, capacites.appeler("m10_prendre_en_compte_signal", _args_signal())["demande_id"])

    reponse = capacites.appeler("m10_paquet_contexte_affaire",
                                {"affaire_id": "LEAD-1", "horodatage": HORODATAGE})

    paquet = reponse["resultat"]
    assert paquet["signaux"] == {"nb_ouverts": 0, "nb_pris_en_compte": 1, "nb_clos": 0}
    assert paquet["confidentialite"] == {"agent": "m10-memoire", "regle": "v1", "nb_retenus": 0}
    couche = next(c for c in paquet["couches"] if c["nom"] == "signaux_non_resolus")
    assert couche["faits"][0]["etat"] == "pris_en_compte" and couche["faits"][0]["traite_par"] == "nathan"
    assert json.dumps(paquet)  # sérialisable tel quel pour le core


def test_le_paquet_derive_le_destinataire_du_contexte_et_ignore_une_usurpation(capacites, instance):
    amont.memoriser(
        etapes.TYPE_CLIENT_ASSOCIE,
        {"lead_id": "LEAD-PRIVE", "client_id": "CLIENT-PRIVE", "horodatage_association": HORODATAGE},
        outils_m10._REGISTRE_EVENEMENTS,
    )
    args = {"affaire_id": "LEAD-PRIVE", "horodatage": HORODATAGE}

    # Le répartiteur prend l'origine de sa configuration serveur; le propriétaire de l'outil
    # M10 n'écrase pas cette origine fiable.
    origine_m1 = Capacites(charger_departements(RACINE_DEPARTEMENTS), stockage.transaction,
                           appelant="m01-front-office", memoire=False)
    origine_m3 = Capacites(charger_departements(RACINE_DEPARTEMENTS), stockage.transaction,
                           appelant="m03-estimation", memoire=False)
    refuse_argument = origine_m3.appeler("m10_paquet_contexte_affaire", {**args, "agent": "m01-front-office"})
    paquet_m1 = origine_m1.appeler("m10_paquet_contexte_affaire", args)["resultat"]
    paquet_m3 = origine_m3.appeler("m10_paquet_contexte_affaire", args)["resultat"]

    assert refuse_argument["ok"] is False and refuse_argument["erreur"] == "arguments_invalides"
    assert paquet_m1["confidentialite"]["agent"] == "m01-front-office"
    assert paquet_m1["confidentialite"]["nb_retenus"] == 0
    assert "CLIENT-PRIVE" in json.dumps(paquet_m1)
    assert paquet_m3["confidentialite"]["agent"] == "m03-estimation"
    assert paquet_m3["confidentialite"]["nb_retenus"] == 1
    assert "CLIENT-PRIVE" not in json.dumps(paquet_m3)


def test_consolidation_persistante_reprend_un_wct_arrive_apres(capacites, instance):
    with stockage.transaction():
        wct.memoriser_wct(_wct("WCT-TARDIF-1"), outils_m10._REGISTRE_EVENEMENTS)
        premier = outils_m10.consolider_affaire("LEAD-1", "2026-09-15", HORODATAGE)
        wct.memoriser_wct(_wct("WCT-TARDIF-2"), outils_m10._REGISTRE_EVENEMENTS)
        tardif = outils_m10.consolider_affaire("LEAD-1", "2026-09-15", HORODATAGE)
        rejoue = outils_m10.consolider_affaire("LEAD-1", "2026-09-15", HORODATAGE)
        paquet = outils_m10.paquet_contexte_affaire("LEAD-1", HORODATAGE)
        faits_persistes = [
            m for m in outils_m10._REGISTRE_AFFAIRES.lire()
            if m.get("cle_consolidation") == "LEAD-1:2026-09-15"
        ]

    assert premier["ecrit"] is True and tardif["ecrit"] is True
    assert [s["identifiant"] for s in tardif["fait"]["sources"]] == ["WCT-TARDIF-1", "WCT-TARDIF-2"]
    assert rejoue["ecrit"] is False and rejoue["fait"]["ligne_id"] == tardif["fait"]["ligne_id"]
    assert len(faits_persistes) == 2  # maillon initial conservé, une nouvelle version agrégée
    couche_faits = next(c for c in paquet["couches"] if c["nom"] == "faits_affaire")
    assert couche_faits["nb_total"] == 1 and "2 travaux terminés" in couche_faits["faits"][0]["resume"]


def test_transport_contexte_lie_vue_privee_a_la_route_et_refuse_le_bearer_public(instance, monkeypatch):
    monkeypatch.setenv("OPSYS_EVENEMENTS_REPARTITEUR", "0")
    with stockage.transaction():
        amont.memoriser(
            etapes.TYPE_CLIENT_ASSOCIE,
            {"lead_id": "LEAD-HTTP", "client_id": "CLIENT-HTTP", "horodatage_association": HORODATAGE},
            outils_m10._REGISTRE_EVENEMENTS,
        )
    public_token = "public-bearer-fictif-1234567890"
    context_token = "context-bearer-fictif-1234567890"
    with pytest.raises(ValueError, match="doit être distinct"):
        application_http_departements(
            charger_departements(RACINE_DEPARTEMENTS), stockage.transaction, public_token,
            hote="127.0.0.1", jeton_contexte=public_token,
        )
    port = _port_libre()
    app = application_http_departements(
        charger_departements(RACINE_DEPARTEMENTS), stockage.transaction, public_token,
        hote="127.0.0.1", jeton_contexte=context_token,
    )
    serveur = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    fil = threading.Thread(target=serveur.run, daemon=True)
    fil.start()
    for _ in range(100):
        if serveur.started:
            break
        time.sleep(0.05)

    async def appeler(chemin, jeton, arguments):
        client = create_mcp_http_client(headers={"Authorization": f"Bearer {jeton}"})
        async with (
            client,
            streamable_http_client(f"http://127.0.0.1:{port}{chemin}", http_client=client) as flux,
            ClientSession(flux[0], flux[1]) as session_mcp,
        ):
            await session_mcp.initialize()
            outils_disponibles = {o.name for o in (await session_mcp.list_tools()).tools}
            resultat = await session_mcp.call_tool("m10_paquet_contexte_affaire", arguments)
            return outils_disponibles, resultat

    try:
        outils_m1, reponse_m1 = anyio.run(
            appeler, "/mcp/contexte/m01-front-office", context_token,
            {"affaire_id": "LEAD-HTTP", "horodatage": HORODATAGE},
        )
        outils_m3, reponse_m3 = anyio.run(
            appeler, "/mcp/contexte/m03-estimation", context_token,
            {"affaire_id": "LEAD-HTTP", "horodatage": HORODATAGE},
        )
        _, usurpation = anyio.run(
            appeler, "/mcp/contexte/m03-estimation", context_token,
            {"affaire_id": "LEAD-HTTP", "horodatage": HORODATAGE, "agent": "m01-front-office"},
        )
        _, usurpation_publique = anyio.run(
            appeler, "/mcp/m10-memoire", public_token,
            {"affaire_id": "LEAD-HTTP", "horodatage": HORODATAGE, "agent": "m01-front-office"},
        )
        import httpx

        with httpx.Client() as client_http:
            public_vers_route_contexte = client_http.get(
                f"http://127.0.0.1:{port}/mcp/contexte/m01-front-office",
                headers={"Authorization": f"Bearer {public_token}"},
            )
    finally:
        serveur.should_exit = True
        fil.join(timeout=5)

    paquet_m1 = json.loads(reponse_m1.content[0].text)["resultat"]
    paquet_m3 = json.loads(reponse_m3.content[0].text)["resultat"]
    assert outils_m1 == outils_m3 == {
        "m10_paquet_contexte_affaire", "opsys_contexte_creer_ticket_cible"
    }
    assert paquet_m1["confidentialite"] == {"agent": "m01-front-office", "regle": "v1", "nb_retenus": 0}
    assert paquet_m3["confidentialite"] == {"agent": "m03-estimation", "regle": "v1", "nb_retenus": 1}
    assert "CLIENT-HTTP" in json.dumps(paquet_m1)
    assert "CLIENT-HTTP" not in json.dumps(paquet_m3)
    assert reponse_m1.is_error is False and reponse_m3.is_error is False
    assert usurpation.is_error is True and usurpation_publique.is_error is True
    assert public_vers_route_contexte.status_code == 401


def test_un_agent_qui_n_est_pas_un_departement_est_un_refus_metier_de_l_outil(par_nom, instance):
    reponse = executer(par_nom["m10_paquet_contexte_affaire"],
                       {"affaire_id": "LEAD-1", "horodatage": HORODATAGE, "agent": "un-texte-de-client"})

    assert reponse["ok"] is False and reponse["erreur"] == "arguments_invalides"


def test_journaliser_une_decision_marquee_et_refuser_un_niveau_inconnu(par_nom, instance):
    decision = {"decision_id": "DEC-1", "raison": "Le client préfère être joint après 17 h.", "statut": "validee",
                "options_ecartees": ""}

    inconnu = executer_atomique(par_nom["m10_journaliser_decision"],
                                {"decision": decision, "horodatage": HORODATAGE, "confidentialite": "SECRET"})
    valide = executer_atomique(par_nom["m10_journaliser_decision"],
                               {"decision": decision, "horodatage": HORODATAGE, "confidentialite": "CLIENT_PRIVATE"})
    sans_marque = executer_atomique(par_nom["m10_journaliser_decision"],
                                    {"decision": {**decision, "decision_id": "DEC-2"}, "horodatage": HORODATAGE})

    assert inconnu["ok"] is False and inconnu["erreur"] == "arguments_invalides"  # hors de l'énuméré du schéma
    assert valide["resultat"]["accepte"] is True
    assert valide["resultat"]["decision"]["confidentialite"] == "CLIENT_PRIVATE"
    assert "confidentialite" not in sans_marque["resultat"]["decision"]
