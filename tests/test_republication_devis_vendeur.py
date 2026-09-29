"""PLAN T1.4-m (partie 2), de bout en bout : republier le fait de propriété rend au vendeur les devis de ses leads
qualifiés avant T1.4-k2.

Le trou, décrit par T1.4-k2 dans ROLES.md : M2 montre à un vendeur ses leads d'après le registre (`owner`), mais M3 ne
reconnaît le propriétaire d'un lead que par le fait `m2.lead_assigne` qu'il relit au bus. Un lead qualifié avant T1.4-k2
n'a jamais publié ce fait : son vendeur voit le lead et se voit REFUSER ses devis. Ici, une base qui contient de tels
leads (le maillon de qualification de l'ancien code, sans aucun fait), les vrais manifestes M2 et M3 en mode `ombre`,
la vraie file d'approbation (validation au départ de l'admin), et l'outil `m2_republier_assignations`. M3 n'est pas
modifié : il relit le rang 1 du fait, sous l'identifiant d'origine.
Vrais manifestes, vrais outils, vraies personnes ; données fictives (AGENTS.md).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from m2_revenue_crm import outils as outils_m2
from m2_revenue_crm import statuts
from sqlalchemy import select

from opsys import approbations, contexte, evenements, idempotence, identite, stockage
from opsys.capacites import Capacites
from opsys.departements import charger_departements
from opsys.outils import executer_atomique
from opsys.stockage.schema import EVENEMENTS_SORTANTS

FICTIF = True
RACINE_DEPARTEMENTS = Path(__file__).resolve().parents[1] / "departments"
DEPARTEMENTS_TESTES = {"m02-revenue-crm", "m03-estimation"}
H0 = "2026-09-01T09:00:00-04:00"
H1 = "2026-09-01T09:05:00-04:00"
ACTION = {"description": "Appeler le client", "echeance": "2026-09-05T09:00:00-04:00"}

ADMIN = contexte.IdentiteAppelante(personne="admin.fictif", role="admin")
VENDEUR_UN = contexte.IdentiteAppelante(personne="vendeur.un", role="seller")
VENDEUR_DEUX = contexte.IdentiteAppelante(personne="vendeur.deux", role="seller")
CODE_INTROUVABLE = "REJ-DEVIS-INTROUVABLE"


@pytest.fixture
def capacites(session, nathan):
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


def _outil(capacites, nom):
    return capacites.index[nom][1]


def _contrat(lead_id):
    return {"lead_id": lead_id, "conversation_id": f"conv-{lead_id}",
            "contact": {"nom": f"Client {lead_id}", "courriel": f"{lead_id}@example.test"},
            "type_travaux": "renovation_totale", "ville": "Québec", "urgence_declaree": False, "canal": "telephone"}


def _lecture(capacites, nom, arguments, identite_appelante):
    with contexte.appele_par_appareil(identite_appelante):
        return capacites.appeler(nom, arguments)


def _appareil(capacites, nom, arguments, identite_appelante, cle):
    meta = idempotence.Meta(cle=cle, appareil="tel-fictif-t1-4-m", horodatage_appareil="2026-09-29T10:15:00-04:00")
    with contexte.appele_par_appareil(identite_appelante):
        return capacites.appeler(nom, arguments, meta)


def _lit(capacites, devis_id, identite_appelante):
    """Vrai si le vendeur lit ce devis ; sinon le refus est celui d'un devis introuvable (jamais un autre)."""
    reponse = _lecture(capacites, "m3_lire_devis", {"devis_id": devis_id}, identite_appelante)
    assert reponse["ok"] is True, reponse
    if reponse["resultat"]["accepte"]:
        return True
    assert reponse["resultat"]["verdict"]["code"] == CODE_INTROUVABLE
    return False


def _fait(lead_id):
    with stockage.transaction():
        return evenements.charge_publiee("m2.lead_assigne", f"m2-lead-assigne-{lead_id}")


def _qualifier_comme_avant_t1_4_k2(lead_id, owner):
    """Ce que l'ancien code faisait à la qualification : le maillon de transition, et RIEN au bus."""
    with stockage.transaction():
        accuse, verdict = statuts.transitionner(
            lead_id, "qualifie", outils_m2._obtenir_registre(), H1, owner=owner, prochaine_action=ACTION)
    assert verdict is None and accuse["statut"] == "qualifie", verdict


@pytest.fixture
def base_d_avant(capacites, personnes):
    """`lead-un` (à vendeur.un) et `lead-deux` (à vendeur.deux), qualifiés comme avant T1.4-k2 (aucun fait au bus),
    chacun avec un devis ; `lead-recent` (à vendeur.un), qualifié par l'ADMIN depuis son appareil avec l'outil
    actuel."""
    for lead_id in ("lead-un", "lead-deux", "lead-recent"):
        reponse = executer_atomique(
            _outil(capacites, "m2_ingerer_lead"), {"contrat": _contrat(lead_id), "horodatage": H0})
        assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    _qualifier_comme_avant_t1_4_k2("lead-un", "vendeur.un")
    _qualifier_comme_avant_t1_4_k2("lead-deux", "vendeur.deux")
    reponse = _appareil(capacites, "m2_transitionner_statut", {
        "lead_id": "lead-recent", "statut_cible": "qualifie", "horodatage": H1, "owner": "vendeur.un",
        "prochaine_action": ACTION}, ADMIN, "mut-qualif-recent")
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    for devis_id, lead_id in (("devis-un", "lead-un"), ("devis-deux", "lead-deux"), ("devis-recent", "lead-recent")):
        reponse = executer_atomique(_outil(capacites, "m3_creer_devis"), {
            "devis_id": devis_id, "lead_id": lead_id, "chantier_id": None,
            "lignes": [{"description": "Gouttière alu 5 po", "quantite": "30", "unite": "pi_lin",
                        "cout_unitaire": "10.00", "reference_besoin_materiau": "besoin-goutt-001"}],
            "taux_marge": "0.20", "horodatage": H1})
        assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse


def test_avant_la_republication_le_vendeur_voit_son_lead_mais_M3_refuse_ses_devis(capacites, base_d_avant):
    """L'état que T1.4-k2 a laissé : le fait manque, donc M3 ne reconnaît pas le propriétaire (fail-closed)."""
    assert _fait("lead-un") is None and _fait("lead-deux") is None
    assert _fait("lead-recent") is not None
    vu = _lecture(capacites, "m2_trouver_client_de_lead", {"lead_id": "lead-un"}, VENDEUR_UN)
    assert vu["resultat"]["accepte"] is True, "M2 lit le propriétaire au registre : le lead est visible"

    assert _lit(capacites, "devis-un", VENDEUR_UN) is False
    assert _lit(capacites, "devis-deux", VENDEUR_DEUX) is False
    assert _lit(capacites, "devis-recent", VENDEUR_UN) is True, "un lead qualifié par l'outil actuel n'a pas ce défaut"


def test_l_admin_republie_depuis_son_appareil_et_le_vendeur_lit_enfin_les_devis_de_ses_leads(
        capacites, base_d_avant, session):
    republication = _appareil(capacites, "m2_republier_assignations", {}, ADMIN, "mut-republier-1")

    assert republication["ok"] is True and "statut" not in republication, "validation au départ : aucune file"
    resultat = republication["resultat"]["resultat"]
    assert resultat["faits_republies"] == 2 and resultat["faits_deja_publies"] == 1
    assert sorted(resultat["leads_republies"]) == ["lead-deux", "lead-un"]
    with session() as cnx:
        (trace,) = [t for t in approbations.lister(cnx) if t["outil"] == "m2_republier_assignations"]
    assert (trace["niveau"], trace["statut"], trace["decide_par"]) == ("N3", "executee", "admin.fictif")

    assert _fait("lead-un") == {"lead_id": "lead-un", "proprietaire": "vendeur.un", "horodatage_assignation": H1}
    assert _lit(capacites, "devis-un", VENDEUR_UN) is True
    assert _lit(capacites, "devis-deux", VENDEUR_DEUX) is True
    # Le refus reste celui d'un devis introuvable pour le vendeur qui n'en est pas le propriétaire.
    assert _lit(capacites, "devis-un", VENDEUR_DEUX) is False and _lit(capacites, "devis-deux", VENDEUR_UN) is False
    brouillon = _lecture(capacites, "m3_generer_soumission_brouillon", {"devis_id": "devis-un"}, VENDEUR_UN)
    assert brouillon["ok"] is True and brouillon["resultat"]["accepte"] is True
    refus = _lecture(capacites, "m3_generer_soumission_brouillon", {"devis_id": "devis-un"}, VENDEUR_DEUX)
    assert refus["resultat"]["verdict"]["code"] == CODE_INTROUVABLE


def test_un_second_appel_de_l_admin_ne_republie_rien_et_ne_double_aucun_evenement(capacites, base_d_avant, session):
    _appareil(capacites, "m2_republier_assignations", {}, ADMIN, "mut-republier-1")
    with session() as cnx:
        avant = cnx.execute(select(EVENEMENTS_SORTANTS.c.evenement_id)).all()

    seconde = _appareil(capacites, "m2_republier_assignations", {}, ADMIN, "mut-republier-2")

    resultat = seconde["resultat"]["resultat"]
    assert resultat["faits_republies"] == 0 and resultat["faits_deja_publies"] == 3
    with session() as cnx:
        assert cnx.execute(select(EVENEMENTS_SORTANTS.c.evenement_id)).all() == avant


def test_un_agent_qui_republie_attend_une_personne_en_mode_ombre_puis_le_vendeur_lit(capacites, base_d_avant, session):
    """La validation au départ vaut pour l'admin qui agit lui-même ; un agent, lui, propose et attend."""
    proposition = capacites.appeler("m2_republier_assignations", {})

    assert proposition["ok"] is True and proposition["statut"] == "en_attente_approbation"
    assert _fait("lead-un") is None and _lit(capacites, "devis-un", VENDEUR_UN) is False
    with session() as cnx:
        approbations.decider(
            cnx, proposition["demande_id"], True, "nathan",
            {o.nom: o for o in capacites.lister()}, capacites.departements)
    assert _fait("lead-un") is not None and _lit(capacites, "devis-un", VENDEUR_UN) is True
