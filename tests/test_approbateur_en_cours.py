"""Le socle dit à l'outil QUI a approuvé la demande qu'il exécute (PLAN T4.15-c ; ADR-0009 §4 et §5).

Avant : M1, M5 et M10 recopiaient chacun une lecture de la table `approbations` (une demande `en_cours` du même outil
aux mêmes arguments, de rôle humain). Maintenant : `approbations.decider` pose l'identifiant de la demande qu'il exécute
(`contexte.executer_demande_approuvee`) autour de l'outil, et `approbations.approbateur_en_cours` lit cette demande en
base. Ce que ces tests fixent :

1. l'outil exécuté par `decider` voit la personne et le rôle qui ont approuvé (lus de la ligne réservée), et rien
   d'autre ne le lui donne ;
2. hors de `decider` (agent, appareil, ligne de commande), et pour un autre outil ou un autre département : None ;
3. un pointeur contrefait (contexte posé à la main, ligne écrite à la main) ne vaut rien : la demande doit être
   `en_cours`, de cet outil et de ce département, la personne active et portant encore le rôle ;
4. un rôle d'agent ou de client, ou hors de la liste de l'outil, n'est pas un humain qui approuve ;
5. le contexte est levé après l'exécution, réussie ou non.

Personnes et identifiants fictifs (AGENTS.md).
"""

from __future__ import annotations

import dataclasses

import pytest
from sqlalchemy import update

from opsys import approbations, contexte, identite
from opsys.contexte import IdentiteAppelante
from opsys.departements import PolitiqueApprobation
from opsys.outils import Autonomie, Niveau, Outil
from opsys.stockage.moteur import connexion_courante
from opsys.stockage.schema import APPROBATIONS

FICTIF = True
DEPARTEMENT = "m09-demo"
OUTIL = "m9_qui_a_approuve"
_SCHEMA = {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]}


def _outil_qui_demande(nom_outil=OUTIL, departement=DEPARTEMENT, roles=None, avant=None, sortie=None):
    """Un outil N4 dont le seul travail est de demander au socle qui a approuvé. `avant` s'exécute d'abord (pour
    changer la base sous ses pieds) ; `sortie` reçoit ce que le socle a répondu."""
    def _fonction(x: int) -> dict:
        if avant is not None:
            avant(connexion_courante())
        trouve = approbations.approbateur_en_cours(connexion_courante(), nom_outil, departement, roles=roles)
        if sortie is not None:
            sortie.append(trouve)
        return {"x": x, "approbateur": None if trouve is None else [trouve.personne, trouve.role]}
    return Outil(OUTIL, "Dit qui a approuvé.", _SCHEMA, _fonction, Autonomie.T2)


@pytest.fixture
def personnes(session):
    with session() as cnx:
        identite.creer_personne(cnx, "nathan", "Nathan (fictif)", "mot-de-passe-nathan-1234", ["nathan_owner"])
        identite.creer_personne(cnx, "compta", "Comptable (fictive)", "mot-de-passe-compta-1234", ["finance"])
        identite.creer_personne(cnx, "robot", "Agent (fictif)", "mot-de-passe-robot-12345", ["system_agent"])
        identite.creer_personne(cnx, "gestion", "Gestionnaire (fictive)", "mot-de-passe-gestion-123",
                                ["manager", "admin"])


@pytest.fixture
def deps(departements_demo):
    politique = PolitiqueApprobation(roles={
        Niveau.N4: frozenset({"nathan_owner", "finance", "system_agent", "manager"})})
    return {DEPARTEMENT: dataclasses.replace(departements_demo[DEPARTEMENT], politique_approbation=politique)}


def _approuver(session, deps, outil, decideur, *, role=None, x=1):
    with session() as cnx:
        ident = approbations.creer_demande(cnx, DEPARTEMENT, OUTIL, {"x": x}, niveau=Niveau.N4)
        decision = approbations.decider(cnx, ident, True, decideur, {OUTIL: outil}, deps, role=role)
    return ident, decision


# ------------------------------------------------------------------------ 1. l'outil voit qui a approuvé
def test_l_outil_execute_par_decider_voit_la_personne_et_le_role_qui_ont_approuve(session, personnes, deps):
    vus = []

    _ident, decision = _approuver(session, deps, _outil_qui_demande(sortie=vus), "compta")

    assert decision["statut"] == "executee", decision
    assert vus == [IdentiteAppelante(personne="compta", role="finance")]
    assert decision["reponse"]["resultat"]["approbateur"] == ["compta", "finance"]


def test_le_role_signe_est_celui_que_decider_a_retenu_pas_un_autre_de_la_personne(session, personnes, deps):
    """Une personne qui porte deux rôles autorisés signe sous celui qu'elle nomme : l'outil voit ce rôle-là."""
    with session() as cnx:
        identite.creer_personne(cnx, "double", "Double (fictive)", "mot-de-passe-double-1234",
                                ["nathan_owner", "finance"])
    vus = []

    _approuver(session, deps, _outil_qui_demande(sortie=vus), "double", role="finance")
    _approuver(session, deps, _outil_qui_demande(sortie=vus), "double", role="nathan_owner", x=2)

    assert [v.role for v in vus] == ["finance", "nathan_owner"] and {v.personne for v in vus} == {"double"}


# ------------------------------------------------------------ 2. hors de `decider`, ou pour un autre outil
def test_hors_de_decider_personne_n_a_approuve_rien(session, personnes):
    with session() as cnx:
        assert contexte.demande_approuvee_en_cours() is None
        assert approbations.approbateur_en_cours(cnx, OUTIL, DEPARTEMENT) is None


def test_un_appel_d_appareil_n_est_pas_une_approbation(session, personnes):
    with session() as cnx, contexte.appele_par_appareil(IdentiteAppelante(personne="nathan", role="admin")):
        assert approbations.approbateur_en_cours(cnx, OUTIL, DEPARTEMENT) is None


def test_une_ligne_en_cours_ecrite_a_la_main_ne_suffit_pas(session, personnes):
    """Ce que l'ancienne lecture de table acceptait (une demande `en_cours` aux bons arguments, de rôle humain) ne vaut
    plus rien sans que `decider` soit en train d'exécuter : un agent qui parviendrait à écrire la ligne n'obtient
    rien."""
    with session() as cnx:
        ident = approbations.creer_demande(cnx, DEPARTEMENT, OUTIL, {"x": 1}, niveau=Niveau.N4)
        cnx.execute(update(APPROBATIONS).where(APPROBATIONS.c.id == ident).values(
            statut="en_cours", decide_par="nathan", decide_role="nathan_owner"))
        assert approbations.approbateur_en_cours(cnx, OUTIL, DEPARTEMENT) is None


def test_sans_connexion_rien_n_est_verifiable(session, personnes, deps):
    reponses = []

    def _sans_connexion(_cnx):
        reponses.append(approbations.approbateur_en_cours(None, OUTIL, DEPARTEMENT))

    _approuver(session, deps, _outil_qui_demande(avant=_sans_connexion), "nathan")

    assert reponses == [None]


@pytest.mark.parametrize("nom_outil, departement", [
    ("m9_un_autre_outil", DEPARTEMENT), (OUTIL, "m05-financecore"), ("m9_un_autre_outil", "m05-financecore")],
    ids=["autre_outil", "autre_departement", "les_deux"])
def test_une_decision_ne_se_reutilise_pas_pour_un_autre_outil_ou_un_autre_departement(
        session, personnes, deps, nom_outil, departement):
    vus = []

    _approuver(session, deps, _outil_qui_demande(nom_outil=nom_outil, departement=departement, sortie=vus), "nathan")

    assert vus == [None]


def test_un_outil_appele_par_le_precedent_ne_herite_pas_de_la_decision(session, personnes, deps):
    """Dans `decider`, un autre outil (nom différent) qui interroge le socle n'obtient rien : la décision porte sur
    l'outil approuvé."""
    interne = []

    def _appelle_un_autre(_cnx):
        interne.append(approbations.approbateur_en_cours(_cnx, "m9_autre_outil", DEPARTEMENT))

    _approuver(session, deps, _outil_qui_demande(avant=_appelle_un_autre), "nathan")

    assert interne == [None]


# ---------------------------------------------------------------------------------- 3. tout se relit en base
def test_un_pointeur_pose_a_la_main_sur_une_demande_en_attente_ne_vaut_rien(session, personnes):
    with session() as cnx:
        ident = approbations.creer_demande(cnx, DEPARTEMENT, OUTIL, {"x": 1}, niveau=Niveau.N4)
        with contexte.executer_demande_approuvee(ident):
            assert contexte.demande_approuvee_en_cours() == ident
            assert approbations.approbateur_en_cours(cnx, OUTIL, DEPARTEMENT) is None, "c'est `en_attente`"


@pytest.mark.parametrize("statut", ["executee", "refusee", "echec"])
def test_un_pointeur_sur_une_demande_deja_decidee_ne_vaut_rien(session, personnes, deps, statut):
    """Une demande DÉCIDÉE garde son approbateur (`decide_par`) : seule une demande `en_cours` (celle que `decider`
    exécute à l'instant) donne le droit d'agir."""
    with session() as cnx:
        ident = approbations.creer_demande(cnx, DEPARTEMENT, OUTIL, {"x": 1}, niveau=Niveau.N4)
        cnx.execute(update(APPROBATIONS).where(APPROBATIONS.c.id == ident).values(
            statut=statut, decide_par="nathan", decide_role="nathan_owner"))
        with contexte.executer_demande_approuvee(ident):
            assert approbations.approbateur_en_cours(cnx, OUTIL, DEPARTEMENT) is None


def test_un_pointeur_sur_une_autre_demande_ou_une_demande_inconnue_ne_donne_pas_l_approbateur_de_l_autre(
        session, personnes, deps):
    """Pendant l'exécution de la demande de `compta`, un pointeur détourné vers une demande `en_attente`, vers une
    demande décidée par `nathan`, ou vers rien, ne rend personne ; le vrai pointeur, lui, rend `compta`."""
    resultats = []

    def _detourne(cnx):
        vraie = contexte.demande_approuvee_en_cours()
        en_attente = approbations.creer_demande(cnx, DEPARTEMENT, OUTIL, {"x": 9}, niveau=Niveau.N4)
        decidee = approbations.creer_demande(cnx, DEPARTEMENT, OUTIL, {"x": 8}, niveau=Niveau.N4)
        cnx.execute(update(APPROBATIONS).where(APPROBATIONS.c.id == decidee).values(
            statut="executee", decide_par="nathan", decide_role="nathan_owner"))
        for faux in (en_attente, decidee, "demande-qui-n-existe-pas", None):
            with contexte.executer_demande_approuvee(faux):
                resultats.append(approbations.approbateur_en_cours(cnx, OUTIL, DEPARTEMENT))
        resultats.append(contexte.demande_approuvee_en_cours() == vraie)
        resultats.append(approbations.approbateur_en_cours(cnx, OUTIL, DEPARTEMENT))

    _approuver(session, deps, _outil_qui_demande(avant=_detourne), "compta")

    assert resultats == [None, None, None, None, True, IdentiteAppelante(personne="compta", role="finance")]


def test_une_personne_desactivee_pendant_l_execution_n_est_plus_un_approbateur(session, personnes, deps):
    def _desactiver(cnx):
        identite.activer(cnx, "compta", False)

    vus = []

    _approuver(session, deps, _outil_qui_demande(avant=_desactiver, sortie=vus), "compta")

    assert vus == [None]


def test_une_personne_qui_perd_le_role_pendant_l_execution_n_est_plus_un_approbateur(session, personnes, deps):
    def _retirer_le_role(cnx):
        identite.retirer_role(cnx, "compta", "finance")

    vus = []

    _approuver(session, deps, _outil_qui_demande(avant=_retirer_le_role, sortie=vus), "compta")

    assert vus == [None]


# --------------------------------------------------------------------------- 4. qui compte comme un humain
@pytest.mark.parametrize("decideur, role", [("robot", "system_agent")], ids=["agent"])
def test_un_role_d_agent_n_est_jamais_un_humain_qui_approuve(session, personnes, deps, decideur, role):
    """Le manifeste (ici, de démonstration) peut nommer `system_agent` : `decider` l'accepte, mais l'outil qui exige
    un humain ne le reconnaît pas."""
    vus = []

    _ident, decision = _approuver(session, deps, _outil_qui_demande(sortie=vus), decideur)

    assert decision["statut"] == "executee" and vus == [None]
    assert role in approbations.ROLES_NON_HUMAINS and "client" in approbations.ROLES_NON_HUMAINS


def test_l_outil_peut_etre_plus_strict_que_la_politique_du_departement(session, personnes, deps):
    """`manager` peut décider N4 dans ce département ; l'outil, lui, n'accepte que la finance et le propriétaire."""
    vus = []
    strict = frozenset({"finance", "nathan_owner"})

    _approuver(session, deps, _outil_qui_demande(roles=strict, sortie=vus), "gestion", role="manager")
    _approuver(session, deps, _outil_qui_demande(roles=strict, sortie=vus), "compta", x=2)
    _approuver(session, deps, _outil_qui_demande(roles=strict, sortie=vus), "nathan", x=3)

    assert vus == [None, IdentiteAppelante("compta", "finance"), IdentiteAppelante("nathan", "nathan_owner")]


# ------------------------------------------------------------------------------ 5. le contexte est levé
def test_le_contexte_est_leve_apres_l_execution_reussie(session, personnes, deps):
    _approuver(session, deps, _outil_qui_demande(), "nathan")

    assert contexte.demande_approuvee_en_cours() is None


def test_le_contexte_est_leve_meme_si_l_outil_echoue(session, personnes, deps):
    def _echec(x: int) -> dict:
        assert contexte.demande_approuvee_en_cours() is not None
        raise RuntimeError("panne")

    outil = Outil(OUTIL, "Échoue.", _SCHEMA, _echec, Autonomie.T2)

    _ident, decision = _approuver(session, deps, outil, "nathan")

    assert decision["statut"] == "echec" and contexte.demande_approuvee_en_cours() is None


def test_une_decision_refusee_n_execute_rien_et_ne_pose_aucun_contexte(session, personnes, deps):
    vus = []
    outil = _outil_qui_demande(sortie=vus)

    with session() as cnx:
        ident = approbations.creer_demande(cnx, DEPARTEMENT, OUTIL, {"x": 1}, niveau=Niveau.N4)
        refus = approbations.decider(cnx, ident, False, "nathan", {OUTIL: outil}, deps, "non merci")

    assert refus["statut"] == "refusee" and vus == [] and contexte.demande_approuvee_en_cours() is None
