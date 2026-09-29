"""PLAN T1.4-m (partie 1), de bout en bout : après une réassignation, le devis déjà fait SUIT le lead.

La chaîne : l'admin réassigne (M2, décision humaine, validation au départ), M2 publie le fait de rang 2 dans la même
transaction que son maillon, M3 le relit au bus (le plus grand rang publié) et ne rend plus au vendeur d'avant les
devis du lead, mais les rend au nouveau. Sans cette lecture par rang, M3 lirait toujours le rang 1 : il refuserait le
nouveau vendeur et continuerait de montrer le devis à l'ancien.
Vrais manifestes, vrais outils, vraies personnes ; données fictives (AGENTS.md).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from m2_revenue_crm import outils as outils_m2
from m2_revenue_crm import statuts

from opsys import contexte, idempotence, identite, stockage
from opsys.capacites import Capacites
from opsys.departements import charger_departements
from opsys.outils import executer_atomique

FICTIF = True
RACINE_DEPARTEMENTS = Path(__file__).resolve().parents[1] / "departments"
DEPARTEMENTS_TESTES = {"m02-revenue-crm", "m03-estimation"}
H0 = "2026-09-01T09:00:00-04:00"
H1 = "2026-09-01T09:05:00-04:00"
H2 = "2026-09-02T10:00:00-04:00"
H3 = "2026-09-03T10:00:00-04:00"
ACTION = {"description": "Appeler le client", "echeance": "2026-09-05T09:00:00-04:00"}
MOTIF = "Le vendeur part en congé, le dossier passe à un collègue."

ADMIN = contexte.IdentiteAppelante(personne="admin.fictif", role="admin")
VENDEUR_UN = contexte.IdentiteAppelante(personne="vendeur.un", role="seller")
VENDEUR_DEUX = contexte.IdentiteAppelante(personne="vendeur.deux", role="seller")
CODE_INTROUVABLE = "REJ-DEVIS-INTROUVABLE"


@pytest.fixture
def capacites(session, nathan):
    departements = charger_departements(RACINE_DEPARTEMENTS)
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
    reponse = _lecture(capacites, "m3_lire_devis", {"devis_id": devis_id}, identite_appelante)
    assert reponse["ok"] is True, reponse
    if reponse["resultat"]["accepte"]:
        return True
    assert reponse["resultat"]["verdict"]["code"] == CODE_INTROUVABLE
    return False


def _devis(capacites, devis_id, lead_id):
    reponse = executer_atomique(_outil(capacites, "m3_creer_devis"), {
        "devis_id": devis_id, "lead_id": lead_id, "chantier_id": None,
        "lignes": [{"description": "Gouttière alu 5 po", "quantite": "30", "unite": "pi_lin",
                    "cout_unitaire": "10.00", "reference_besoin_materiau": "besoin-goutt-001"}],
        "taux_marge": "0.20", "horodatage": H1})
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse


def _reassigner(capacites, lead_id, cible, cle, horodatage=H2):
    reponse = _appareil(capacites, "m2_reassigner_lead", {
        "lead_id": lead_id, "nouveau_proprietaire": cible, "motif": MOTIF, "horodatage": horodatage}, ADMIN, cle)
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]["resultat"]


@pytest.fixture
def scenario(capacites, personnes):
    for lead_id in ("lead-a", "lead-b"):
        reponse = executer_atomique(
            _outil(capacites, "m2_ingerer_lead"), {"contrat": _contrat(lead_id), "horodatage": H0})
        assert reponse["resultat"]["accepte"] is True, reponse
    for lead_id, proprietaire in (("lead-a", "vendeur.un"), ("lead-b", "vendeur.deux")):
        reponse = _appareil(capacites, "m2_transitionner_statut", {
            "lead_id": lead_id, "statut_cible": "qualifie", "horodatage": H1, "owner": proprietaire,
            "prochaine_action": ACTION}, ADMIN, f"mut-qualif-{lead_id}")
        assert reponse["resultat"]["accepte"] is True, reponse
    _devis(capacites, "devis-a", "lead-a")
    _devis(capacites, "devis-b", "lead-b")


def test_le_devis_deja_fait_suit_le_lead_reassigne(scenario, capacites):
    assert _lit(capacites, "devis-a", VENDEUR_UN) and not _lit(capacites, "devis-a", VENDEUR_DEUX)

    accuse = _reassigner(capacites, "lead-a", "vendeur.deux", "mut-reassigner-a")

    assert accuse["rang"] == 2
    assert _lit(capacites, "devis-a", VENDEUR_DEUX) is True, "le nouveau vendeur lit le devis"
    assert _lit(capacites, "devis-a", VENDEUR_UN) is False, "l'ancien ne le lit plus (même refus qu'un devis inconnu)"
    brouillon = _lecture(capacites, "m3_generer_soumission_brouillon", {"devis_id": "devis-a"}, VENDEUR_DEUX)
    assert brouillon["resultat"]["accepte"] is True
    refus = _lecture(capacites, "m3_generer_soumission_brouillon", {"devis_id": "devis-a"}, VENDEUR_UN)
    assert refus["resultat"]["verdict"]["code"] == CODE_INTROUVABLE
    # Le devis de l'autre lead n'a pas bougé.
    assert _lit(capacites, "devis-b", VENDEUR_DEUX) and not _lit(capacites, "devis-b", VENDEUR_UN)


def test_reassigner_deux_fois_puis_revenir_le_devis_suit_chaque_fois(scenario, capacites):
    _reassigner(capacites, "lead-a", "vendeur.deux", "mut-reassigner-a-1")
    accuse = _reassigner(capacites, "lead-a", "vendeur.un", "mut-reassigner-a-2", H3)

    assert accuse["rang"] == 3
    assert _lit(capacites, "devis-a", VENDEUR_UN) is True and _lit(capacites, "devis-a", VENDEUR_DEUX) is False


def test_un_lead_qualifie_avant_t1_4_k2_puis_reassigne_avant_la_republication_suit_aussi(capacites, personnes):
    """Le rang 1 n'a jamais été publié, le rang 2 l'est : M3 lit quand même le propriétaire courant."""
    reponse = executer_atomique(
        _outil(capacites, "m2_ingerer_lead"), {"contrat": _contrat("lead-ancien"), "horodatage": H0})
    assert reponse["resultat"]["accepte"] is True
    with stockage.transaction():
        accuse, verdict = statuts.transitionner(
            "lead-ancien", "qualifie", outils_m2._obtenir_registre(), H1, owner="vendeur.un", prochaine_action=ACTION)
    assert verdict is None
    _devis(capacites, "devis-ancien", "lead-ancien")
    assert _lit(capacites, "devis-ancien", VENDEUR_UN) is False, "le fait manque : refusé (fail-closed)"

    _reassigner(capacites, "lead-ancien", "vendeur.deux", "mut-reassigner-ancien")

    assert _lit(capacites, "devis-ancien", VENDEUR_DEUX) is True
    assert _lit(capacites, "devis-ancien", VENDEUR_UN) is False
