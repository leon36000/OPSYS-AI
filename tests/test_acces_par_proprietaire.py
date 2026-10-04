"""PLAN T1.4-k2, de bout en bout : la personne authentifiée d'un appel d'appareil traverse
`Capacites.appeler` (mode `ombre` réel, validation humaine au départ de T1.4-h) et le `_meta` MCP jusque dans
M2 et M3, qui n'en croient plus les arguments : `auteur` d'une interaction vient de la personne, un vendeur ne
voit que SES leads (M2) et que les devis de SES leads (M3).

Les tests par outil et par refus sont dans les départements (`departments/m02-revenue-crm/tests/
test_acces_appareil.py`, `departments/m03-estimation/tests/test_acces_par_proprietaire.py`) ; ici on prouve la
CHAÎNE, dont le maillon que aucun département ne peut prouver seul : M2 publie `m2.lead_assigne` dans la
transaction de la qualification, M3 le relit à la source du bus, sans jamais importer M2 (#109). Si l'identifiant
d'événement ou la charge divergeaient d'un côté, le vendeur ne verrait plus aucun devis : ce test l'attraperait.
Vrais manifestes, vrais outils, vraies personnes ; données fictives (AGENTS.md).
"""

from __future__ import annotations

import json
from pathlib import Path

import anyio
import pytest
from m2_revenue_crm import outils as outils_m2
from mcp import Client
from sqlalchemy import select

from opsys import approbations, contexte, evenements, idempotence, identite, openclaw, stockage
from opsys.capacites import Capacites
from opsys.departements import charger_departements
from opsys.outils import executer_atomique
from opsys.serveur_mcp import creer_serveur
from opsys.stockage.schema import META

FICTIF = True
RACINE_DEPARTEMENTS = Path(__file__).resolve().parents[1] / "departments"
DEPARTEMENTS_TESTES = {"m02-revenue-crm", "m03-estimation"}
H0 = "2026-09-01T09:00:00-04:00"
H1 = "2026-09-01T09:05:00-04:00"
H2 = "2026-09-02T10:00:00-04:00"
ACTION = {"description": "Appeler le client", "echeance": "2026-09-05T09:00:00-04:00"}

ADMIN = contexte.IdentiteAppelante(personne="admin.fictif", role="admin")
VENDEUR_UN = contexte.IdentiteAppelante(personne="vendeur.un", role="seller")
VENDEUR_DEUX = contexte.IdentiteAppelante(personne="vendeur.deux", role="seller")
MARC = contexte.IdentiteAppelante(personne="marc.fictif", role="employee")

CODE_NON_ASSIGNE = "REJ-LEAD-NON-ASSIGNE"
CODE_DIFFERENTE = "REJ-IDENTITE-FOURNIE-DIFFERENTE"
CODE_INVALIDE = "REJ-IDENTITE-APPAREIL-INVALIDE"
CODE_INTROUVABLE = "REJ-DEVIS-INTROUVABLE"

OUTILS_M2_DU_VENDEUR = {
    "m2_obtenir_client_360", "m2_trouver_client_de_lead", "m2_suggerer_prochaine_action", "m2_lister_leads",
    "m2_evaluer_readiness", "m2_transitionner_statut", "m2_enregistrer_interaction",
    # T4.9 : « relances autorisées » (§9.4), SES leads seulement ; le consentement est inscrit par une personne
    "m2_lister_relances", "m2_preparer_relance", "m2_enregistrer_consentement_contact",
}
OUTILS_M3_DU_VENDEUR = {
    "m3_lire_devis", "m3_generer_soumission_brouillon", "m3_qualifier_photos",
    "m3_demander_envoi_devis",  # DEMANDE l'envoi (N4, T4.7) : le propriétaire décide dans la file
}
OUTILS_M2_DE_L_ADMIN = {
    "m2_produire_digest", "m2_detecter_doublons", "m2_signaler_doublon", "m2_arbitrer_doublon",
    "m2_reassigner_lead", "m2_republier_assignations",  # T1.4-m
}


# -- installation ------------------------------------------------------------------------------------
@pytest.fixture
def capacites(session, nathan):
    """Vrais départements M2/M3 (mode `ombre` de leur manifeste), base migrée, M2 sur le stockage durable."""
    departements = charger_departements(RACINE_DEPARTEMENTS)
    assert all(departements[d].mode == "ombre" for d in DEPARTEMENTS_TESTES)
    outils_m2.utiliser_stockage_durable()
    try:
        yield Capacites(departements, session, filtre=DEPARTEMENTS_TESTES, memoire=False)
    finally:
        outils_m2.reinitialiser_registre()


@pytest.fixture
def personnes(session, capacites):
    with session() as cnx:
        identite.creer_personne(cnx, "admin.fictif", "Admin Fictive", "mot-de-passe-admin-12345", ["admin"])
        identite.creer_personne(cnx, "vendeur.un", "Vendeur Un", "mot-de-passe-vendeur-un-1", ["seller"])
        identite.creer_personne(cnx, "vendeur.deux", "Vendeur Deux", "mot-de-passe-vendeur-deux", ["seller"])
        identite.creer_personne(cnx, "marc.fictif", "Marc Fictif", "mot-de-passe-marc-1234", ["employee"])


def _outil(capacites, nom):
    return capacites.index[nom][1]


def _meta(cle: str) -> idempotence.Meta:
    return idempotence.Meta(cle=cle, appareil="tel-fictif-t1-4-k2", horodatage_appareil="2026-09-29T10:15:00-04:00")


def _appeler(capacites, nom, arguments, identite_appelante, cle):
    with contexte.appele_par_appareil(identite_appelante):
        return capacites.appeler(nom, arguments, _meta(cle))


def _lecture(capacites, nom, arguments, identite_appelante=None):
    """Un appel de lecture (T0) : `Capacites.appeler` sans clé d'idempotence, avec ou sans identité."""
    if identite_appelante is None:
        return capacites.appeler(nom, arguments)
    with contexte.appele_par_appareil(identite_appelante):
        return capacites.appeler(nom, arguments)


def _contrat(lead_id, contact):
    return {"lead_id": lead_id, "conversation_id": f"conv-{lead_id}", "contact": contact,
            "type_travaux": "renovation_totale", "ville": "Québec", "urgence_declaree": False, "canal": "telephone"}


def _verdict(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False, reponse
    return reponse["resultat"]["verdict"]


def _accepte(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]["resultat"]


def _maillons_m2():
    with stockage.transaction():
        return list(stockage.maillons("m02-revenue-crm", "principal"))


def _traces(session):
    with session() as cnx:
        return approbations.lister(cnx)


def _instantane_base():
    with stockage.transaction() as cnx:
        return {
            nom: sorted(tuple(map(str, ligne)) for ligne in cnx.execute(select(table)).fetchall())
            for nom, table in META.tables.items()
        }


@pytest.fixture
def scenario(capacites, personnes):
    """`lead-a` (à vendeur.un) et `lead-b` (à vendeur.deux) du MÊME client, `lead-c` sans propriétaire ; un
    devis chacun. Les leads sont ingérés par l'agent ; l'ADMIN les qualifie depuis son appareil (la vraie
    chaîne : validation au départ, propriétaire consigné, fait publié) ; les devis sont créés par l'agent."""
    partage = {"nom": "Cliente Partagée", "courriel": "partagee@example.test"}
    for lead_id, contact in (("lead-a", partage), ("lead-b", partage),
                             ("lead-c", {"nom": "Client C", "courriel": "c@example.test"})):
        reponse = executer_atomique(_outil(capacites, "m2_ingerer_lead"), {"contrat": _contrat(lead_id, contact),
                                                                           "horodatage": H0})
        assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    for lead_id, proprietaire in (("lead-a", "vendeur.un"), ("lead-b", "vendeur.deux")):
        reponse = _appeler(capacites, "m2_transitionner_statut", {
            "lead_id": lead_id, "statut_cible": "qualifie", "horodatage": H1, "owner": proprietaire,
            "prochaine_action": ACTION}, ADMIN, f"mut-qualif-{lead_id}")
        assert _accepte(reponse)["statut"] == "qualifie"
    for devis_id, lead_id in (("devis-a", "lead-a"), ("devis-b", "lead-b"), ("devis-c", "lead-c")):
        reponse = executer_atomique(_outil(capacites, "m3_creer_devis"), {
            "devis_id": devis_id, "lead_id": lead_id, "chantier_id": None,
            "lignes": [{"description": "Gouttière alu 5 po", "quantite": "30", "unite": "pi_lin",
                        "cout_unitaire": "10.00", "reference_besoin_materiau": "besoin-goutt-001"}],
            "taux_marge": "0.20", "horodatage": H1})
        assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse


# -- 1. la portée que le core applique : rien de retiré au vendeur, rien d'ajouté à l'employé ---------------
def test_le_core_garde_a_chaque_role_ses_outils_m2_et_m3(capacites):
    portees = {r: set(noms) for r, noms in openclaw.roles_outils(capacites.departements).items()}

    def de(role, prefixe):
        return {n for n in portees[role] if n.startswith(prefixe)}

    assert de("seller", "m2_") == OUTILS_M2_DU_VENDEUR and de("seller", "m3_") == OUTILS_M3_DU_VENDEUR
    assert de("admin", "m2_") == OUTILS_M2_DU_VENDEUR | OUTILS_M2_DE_L_ADMIN
    assert de("employee", "m2_") == set() and de("employee", "m3_") == set()


# -- 2. M2 -> bus -> M3 : le propriétaire de la qualification est celui que M3 relit --------------------------
def test_la_qualification_faite_par_l_admin_publie_le_proprietaire_que_m3_relit(scenario, session):
    with stockage.transaction():
        charge = evenements.charge_publiee("m2.lead_assigne", "m2-lead-assigne-lead-a")
    assert charge == {"lead_id": "lead-a", "proprietaire": "vendeur.un", "horodatage_assignation": H1}
    qualifications = [(t["outil"], t["niveau"], t["statut"], t["decide_par"]) for t in _traces(session)
                      if t["outil"] == "m2_transitionner_statut"]
    assert qualifications == [("m2_transitionner_statut", "N3", "executee", "admin.fictif")] * 2


def test_le_vendeur_lit_le_devis_de_son_lead_et_pas_celui_d_un_autre(scenario, capacites):
    lu = _accepte(_lecture(capacites, "m3_lire_devis", {"devis_id": "devis-a"}, VENDEUR_UN))
    assert lu["devis_id"] == "devis-a" and lu["prix_total"] == "360.00"

    avant = _instantane_base()
    d_un_autre = _verdict(_lecture(capacites, "m3_lire_devis", {"devis_id": "devis-b"}, VENDEUR_UN))
    sans_proprietaire = _verdict(_lecture(capacites, "m3_lire_devis", {"devis_id": "devis-c"}, VENDEUR_UN))
    inconnu = _verdict(_lecture(capacites, "m3_lire_devis", {"devis_id": "devis-fantome"}, VENDEUR_UN))
    brouillon = _verdict(_lecture(capacites, "m3_generer_soumission_brouillon", {"devis_id": "devis-b"}, VENDEUR_UN))

    assert {v["code"] for v in (d_un_autre, sans_proprietaire, inconnu, brouillon)} == {CODE_INTROUVABLE}
    assert d_un_autre["detail"].replace("devis-b", "?") == inconnu["detail"].replace("devis-fantome", "?")
    assert _instantane_base() == avant, "un refus de lecture n'écrit rien"
    # L'autre vendeur voit l'inverse ; l'admin voit tout ; l'agent n'est pas filtré.
    chez_deux = _lecture(capacites, "m3_lire_devis", {"devis_id": "devis-b"}, VENDEUR_DEUX)
    assert _accepte(chez_deux)["devis_id"] == "devis-b"
    assert _verdict(_lecture(capacites, "m3_lire_devis", {"devis_id": "devis-a"}, VENDEUR_DEUX))["code"] == (
        CODE_INTROUVABLE)
    for devis_id in ("devis-a", "devis-b", "devis-c"):
        assert _accepte(_lecture(capacites, "m3_lire_devis", {"devis_id": devis_id}, ADMIN))["devis_id"] == devis_id
        assert _accepte(_lecture(capacites, "m3_lire_devis", {"devis_id": devis_id}))["devis_id"] == devis_id


# -- 3. M2 : `auteur` vient de la personne, un vendeur n'agit que sur ses leads ---------------------------------
def test_le_vendeur_ecrit_sa_note_sous_son_nom_et_le_devis_de_son_lead_reste_lisible(scenario, capacites, session):
    reponse = _appeler(capacites, "m2_enregistrer_interaction",
                       {"lead_id": "lead-a", "resume": "Le client veut voir le devis", "horodatage": H2},
                       VENDEUR_UN, "mut-note-a")

    assert _accepte(reponse)["lead_id"] == "lead-a"
    notes = [m for m in _maillons_m2() if m.get("type_entree") == "interaction" and m["lead_id"] == "lead-a"]
    assert [(n["auteur"], n["resume"]) for n in notes] == [("vendeur.un", "Le client veut voir le devis")]
    assert ("m2_enregistrer_interaction", "N3", "executee", "vendeur.un") in [
        (t["outil"], t["niveau"], t["statut"], t["decide_par"]) for t in _traces(session)]


def test_un_auteur_different_ou_un_lead_d_un_autre_sont_refuses_sans_ecrire_dans_m2(scenario, capacites):
    avant = _maillons_m2()

    au_nom_d_un_autre = _appeler(capacites, "m2_enregistrer_interaction", {
        "lead_id": "lead-a", "auteur": "admin.fictif", "resume": "Faux", "horodatage": H2}, VENDEUR_UN, "mut-faux")
    sur_le_lead_d_un_autre = _appeler(capacites, "m2_enregistrer_interaction", {
        "lead_id": "lead-b", "resume": "Intrusion", "horodatage": H2}, VENDEUR_UN, "mut-intrusion")
    transition_d_un_autre = _appeler(capacites, "m2_transitionner_statut", {
        "lead_id": "lead-b", "statut_cible": "perdu", "horodatage": H2, "motif": "Sabotage"},
        VENDEUR_UN, "mut-sabotage")

    assert _verdict(au_nom_d_un_autre)["code"] == CODE_DIFFERENTE
    assert _verdict(sur_le_lead_d_un_autre)["code"] == CODE_NON_ASSIGNE
    assert _verdict(transition_d_un_autre)["code"] == CODE_NON_ASSIGNE
    assert _maillons_m2() == avant


def test_client_360_d_un_client_partage_ne_montre_au_vendeur_que_ses_opportunites(scenario, capacites):
    lien = _accepte(_lecture(capacites, "m2_trouver_client_de_lead", {"lead_id": "lead-a"}, VENDEUR_UN))
    client_id = lien["client_id"]

    vue_un = _accepte(_lecture(capacites, "m2_obtenir_client_360", {"client_id": client_id}, VENDEUR_UN))
    vue_admin = _accepte(_lecture(capacites, "m2_obtenir_client_360", {"client_id": client_id}, ADMIN))

    assert [o["lead_id"] for o in vue_un["opportunites"]] == ["lead-a"]
    assert sorted(o["lead_id"] for o in vue_admin["opportunites"]) == ["lead-a", "lead-b"]


# -- 4. par MCP : l'identité vient du `_meta`, jamais des arguments ---------------------------------------------
def _meta_mcp(personne, role, cle=None):
    meta = {"opsys/appareil": "tel-fictif-t1-4-k2", "opsys/horodatageAppareil": "2026-09-29T10:15:00-04:00",
            "opsys/personne": personne, "opsys/role": role}
    if cle is not None:
        meta["opsys/idempotencyKey"] = cle
    return meta


def test_mcp_le_jeton_decide_pas_l_auteur_ni_le_proprietaire_des_arguments(scenario, capacites, session):
    serveur = creer_serveur(capacites)

    async def appels(liste):
        async with Client(serveur) as client:
            reponses = []
            for nom, arguments, meta in liste:
                resultat = await client.call_tool(nom, arguments, meta=meta)
                reponses.append(json.loads(resultat.content[0].text))
            return reponses

    avant_m2 = _maillons_m2()
    devis_d_un_autre, devis_du_vendeur, faux_auteur, lead_d_un_autre, agent_lit, agent_ecrit = anyio.run(appels, [
        # Le jeton est celui de vendeur.un : devis-b n'est pas le sien, devis-a l'est.
        ("m3_lire_devis", {"devis_id": "devis-b"}, _meta_mcp("vendeur.un", "seller")),
        ("m3_lire_devis", {"devis_id": "devis-a"}, _meta_mcp("vendeur.un", "seller")),
        # Les arguments se disent admin.fictif ; le jeton dit vendeur.un : c'est le jeton qui décide.
        ("m2_enregistrer_interaction", {"lead_id": "lead-a", "auteur": "admin.fictif", "resume": "Faux",
                                        "horodatage": H2}, _meta_mcp("vendeur.un", "seller", "mut-mcp-faux")),
        ("m2_enregistrer_interaction", {"lead_id": "lead-b", "resume": "Intrusion", "horodatage": H2},
         _meta_mcp("vendeur.un", "seller", "mut-mcp-intrusion")),
        # La voie des agents (aucun jeton d'appareil) est inchangée : pas de filtre en lecture.
        ("m3_lire_devis", {"devis_id": "devis-b"}, None),
        ("m2_enregistrer_interaction", {"lead_id": "lead-b", "auteur": "agent-m2-fictif", "resume": "Suivi agent",
                                        "horodatage": H2}, None),
    ])

    assert devis_d_un_autre["resultat"]["verdict"]["code"] == CODE_INTROUVABLE
    assert devis_du_vendeur["resultat"]["resultat"]["devis_id"] == "devis-a"
    assert faux_auteur["resultat"]["verdict"]["code"] == CODE_DIFFERENTE
    assert lead_d_un_autre["resultat"]["verdict"]["code"] == CODE_NON_ASSIGNE
    assert agent_lit["resultat"]["resultat"]["devis_id"] == "devis-b"
    # Une mutation d'agent sans liaison et ticket ne crée même pas de demande d'approbation.
    # Les accès humains précédents gardent leur contrat; aucun des refus ne modifie M2.
    assert agent_ecrit["ok"] is False
    assert agent_ecrit["erreur"] == "ticket_cible_requis"
    assert _maillons_m2() == avant_m2


def test_mcp_une_personne_desactivee_ne_lit_plus_rien_avec_le_meme_jeton(scenario, capacites, session):
    serveur = creer_serveur(capacites)

    async def lire():
        async with Client(serveur) as client:
            resultat = await client.call_tool("m3_lire_devis", {"devis_id": "devis-a"},
                                              meta=_meta_mcp("vendeur.un", "seller"))
            return json.loads(resultat.content[0].text)

    assert anyio.run(lire)["resultat"]["resultat"]["devis_id"] == "devis-a"
    with session() as cnx:
        identite.activer(cnx, "vendeur.un", False)
    avant = _instantane_base()

    refuse = anyio.run(lire)

    assert refuse["resultat"]["verdict"]["code"] == CODE_INVALIDE
    assert _instantane_base() == avant


def test_l_employe_n_a_ni_les_outils_m2_ni_les_devis_meme_en_les_appelant_par_mcp(scenario, capacites):
    """La portée du core ferme M2 et M3 à l'employé ; si un appel la franchissait, M2 le refuse encore, et
    M3 ne lui rend jamais ni coût, ni marge, ni prix."""
    serveur = creer_serveur(capacites)

    async def appels():
        async with Client(serveur) as client:
            reponses = []
            for nom, arguments in (("m2_trouver_client_de_lead", {"lead_id": "lead-a"}),
                                   ("m3_lire_devis", {"devis_id": "devis-a"})):
                resultat = await client.call_tool(nom, arguments, meta=_meta_mcp("marc.fictif", "employee"))
                reponses.append(json.loads(resultat.content[0].text))
            return reponses

    lead, devis = anyio.run(appels)

    assert lead["resultat"]["verdict"]["code"] == CODE_INVALIDE
    assert devis["ok"] is True
    for cle in ("cout_total", "prix_total", "taux_marge"):
        assert cle not in devis["resultat"]["resultat"]
