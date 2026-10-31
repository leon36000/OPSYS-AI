"""M9.4/M9.23 — réaudit des citations d'un conseil clos : une source plus récente et différente le rend à revoir.

Réel : outils M9, registres durables, producteur M2, profils et admission de budget natifs. Simulé et dit tel : le
tour de modèle (réservation puis réconciliation natives, sortie prédéfinie qui cite de vrais faits). Fictif.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from m2_revenue_crm import outils as m2

from opsys import admission_agents, identite, stockage
from opsys.capacites import Capacites
from opsys.departements import charger_departements

_TESTS = Path(__file__).resolve().parent
_SPEC = importlib.util.spec_from_file_location("test_m9_conseil_integre", _TESTS / "test_m9_conseil_integre.py")
C = importlib.util.module_from_spec(_SPEC)
sys.modules["test_m9_conseil_integre"] = C
_SPEC.loader.exec_module(C)

FICTIF = True
M9 = "m09-strategic-intelligence"
PLUS_TARD = "2026-10-22T09:00:00Z"
REF_TARD = "2026-10-22T09:10:00Z"


@pytest.fixture
def monde(tmp_path, monkeypatch):
    monkeypatch.setenv(stockage.ENV_URL, f"sqlite:///{tmp_path / 'reaudit.db'}")
    stockage.migrer()
    m2.utiliser_stockage_durable()
    departements = charger_departements()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "admin.fictif", "Admin", "mot-de-passe-admin-12345", ["admin"])
        identite.creer_personne(cnx, "vendeur.fictif", "Vendeur", "mot-de-passe-vendeur-123", ["seller"])
        admission_agents.configurer_plafonds_entreprise(
            cnx, 500_000, 5_000_000, par="admin.fictif", revision_attendue=0
        )
    capacites = Capacites(
        departements, stockage.transaction, filtre={M9, "m02-revenue-crm", "m06-material-control"}, memoire=False
    )
    yield capacites, departements
    m2.reinitialiser_registre()
    stockage.liberer()


def _conseil_clos(capacites, departements):
    """Conseil complet dont chaque tour cite le total de leads M2 de la capture n° 0 (valeur « 1 »)."""
    C._preparer(capacites, departements)
    ouverture = C._ouvrir(capacites)
    session_id = ouverture["session_id"]
    roles = [t["role"] for t in ouverture["tours"]]
    C._creer_profils(departements, roles)
    faits = C._tous_les_faits(capacites)
    adresse = next(a for a in faits if a.startswith("m2.leads#0:") and a.endswith(".total"))
    for role in roles:
        reservation = C._runtime_natif_simule(departements, role, f"exec-{session_id[:8]}-{role}", 1234)
        sortie = {
            "affirmations": [
                {"id": "A1", "nature": "observation_source", "reference": adresse, "valeur": faits[adresse]},
                {"id": "H1", "nature": "hypothese", "enonce": "la demande reste stable"},
                {"id": "I1", "nature": "inference", "enonce": "suivre les leads", "premisses": ["A1", "H1"]},
            ]
        }
        if role == "conseiller_pdg":
            sortie["recommandation"] = {
                "decision": "Suivre les leads",
                "refs": ["I1"],
                "actions": [{"id": "a1", "type": "suivi_interne", "description": "suivi"}],
            }
        C._ok(
            C._appel(
                capacites,
                "m9_deposer_tour_conseil",
                {
                    "session_id": session_id,
                    "role": role,
                    "sortie": sortie,
                    "reservation_id": reservation,
                    "horodatage": C.T,
                },
            )
        )
    C._ok(C._appel(capacites, "m9_cloturer_conseil", {"session_id": session_id, "horodatage": C.T}))
    return session_id, adresse, faits[adresse]


def _reaudit(capacites, session_id, connaissance):
    return C._ok(C._appel(capacites, "m9_reauditer_conseil", {"session_id": session_id, "connaissance": connaissance}))


def test_sources_a_jour_puis_source_plus_recente_differente_rend_le_conseil_a_revoir(monde):
    capacites, departements = monde
    session_id, adresse, valeur = _conseil_clos(capacites, departements)
    avant = _reaudit(capacites, session_id, C.T)
    assert avant["verdict"] == "SOURCES_A_JOUR" and avant["citations_a_revoir_total"] == 0
    assert avant["par_statut"] == {"A_JOUR": avant["citations_total"]} and avant["citations_total"] >= 3
    assert avant["recommandation"]["statut"] == "ANCREE_SUR_DES_SOURCES_A_JOUR" and avant["inferences_a_revoir"] == []
    # Un lead de plus arrive chez M2 et M9 le recapture : la source citée n'est plus celle du propriétaire.
    assert m2.ingerer_lead(
        {"lead_id": "lead-2", "conversation_id": "c-2", "contact": {"nom": "D", "courriel": "d@example.test"},
         "type_travaux": "extension", "ville": "Lévis", "urgence_declaree": False, "canal": "courriel"},
        "2026-10-22T08:00:00-04:00",
    )["accepte"]  # fmt: skip
    capture = C._capturer(capacites, "m2.leads", {"horodatage": "2026-10-21T12:00:00Z"}, PLUS_TARD)
    assert capture["capture"]["verdict"] == "ACCEPTEE"
    apres = _reaudit(capacites, session_id, REF_TARD)
    assert apres["verdict"] == "A_REVOIR" and apres["citations_a_revoir_total"] >= 3
    ligne = apres["citations_a_revoir"][0]
    assert ligne["statut"] == "SOURCE_PLUS_RECENTE_DIFFERENTE" and ligne["valeur_citee"] == valeur
    assert ligne["valeur_plus_recente"] != valeur and ligne["adresse_plus_recente"].startswith("m2.leads#")
    assert {i["id"] for i in apres["inferences_a_revoir"]} == {"I1"} and apres["recommandation"]["statut"] == "A_REVOIR"
    # Connaissance antérieure à la nouvelle capture : elle n'existe pas encore pour M9.
    assert _reaudit(capacites, session_id, "2026-10-21T13:00:00Z")["verdict"] == "SOURCES_A_JOUR"
    assert "float" not in json.dumps(apres) and len(apres["reaudit_id"]) == 64


def test_reaudit_refuse_session_inconnue_instant_invalide_et_autres_profils(monde):
    capacites, departements = monde
    session_id, _a, _v = _conseil_clos(capacites, departements)
    inconnue = C._appel(capacites, "m9_reauditer_conseil", {"session_id": "inconnue", "connaissance": C.T})
    assert C._refuse(inconnue) and "REJ-SESSION-INCONNUE" in json.dumps(inconnue)
    sans_fuseau = C._appel(
        capacites, "m9_reauditer_conseil", {"session_id": session_id, "connaissance": "2026-10-21T12:00:00"}
    )
    assert C._refuse(sans_fuseau)
    vendeur = C.IdentiteAppelante("vendeur.fictif", "employee", source="appareil")
    for qui in (vendeur, None):
        assert C._refuse(
            C._appel(capacites, "m9_reauditer_conseil", {"session_id": session_id, "connaissance": C.T}, qui)
        )
