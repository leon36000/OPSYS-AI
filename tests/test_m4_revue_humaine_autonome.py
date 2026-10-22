"""Frontière humaine M4, même en mode autonome ; SQLite et Capacites réels.

Le maillon de départ est une fixture fictive explicite, pas une preuve de la
cascade WCT. Seule l'autorité de résolution de cette revue est exercée ici.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from m4_field_ops import etats, registre
from m4_field_ops.outils import outils

from opsys import approbations, contexte, identite, stockage
from opsys.capacites import Capacites
from opsys.departements import charger_departements
from opsys.outils import Niveau, executer

DEP = "m04-field-ops"
OUTIL = "m4_resoudre_revue_completion"
INTERVENTION = "INTERVENTION-REVUE-FICTIVE"
DATE = "2026-10-22T03:00:00+00:00"


def _semer(reg):
    reg.ajouter({
        "type_entree": "transition_statut", "intervention_id": INTERVENTION,
        "statut_precedent": "sur_site", "statut": "completed_pending_review",
        "horodatage": DATE, "fictif": True,
    })


def _args(decision="verifiee"):
    return {"intervention_id": INTERVENTION, "decision": decision,
            "horodatage": DATE, "motif": "Vérification terrain fictive."}


def _lire(session):
    with session():
        reg = registre.Registre(stockage.maillons(DEP, "principal"))
        assert reg.valider_chaine()
        return reg.lire()


@pytest.fixture
def capacites(session, nathan):
    deps = charger_departements(Path(__file__).resolve().parents[1] / "departments")
    with session() as cnx:
        approbations.fixer_mode(cnx, DEP, "autonome", nathan)
        _semer(registre.Registre(stockage.maillons(DEP, "principal")))
    return Capacites(deps, session, filtre={DEP}, memoire=False)


@pytest.mark.parametrize("decision", ["verifiee", "correction"])
def test_agent_autonome_sans_signature_ne_resout_pas_la_revue(capacites, session, decision):
    avant = _lire(session)
    reponse = capacites.appeler(OUTIL, _args(decision))
    assert reponse["ok"] is True, reponse
    assert reponse["resultat"]["accepte"] is False, reponse
    assert reponse["resultat"]["verdict"]["code"] == "REJ-HUMAIN-REQUIS"
    assert _lire(session) == avant


def test_contexte_approbation_invente_ne_remplace_pas_signature_sql(capacites, session):
    avant = _lire(session)
    with contexte.executer_demande_approuvee("demande-inexistante-fictive"):
        reponse = capacites.appeler(OUTIL, _args())
    assert reponse["resultat"]["accepte"] is False, reponse
    assert reponse["resultat"]["verdict"]["code"] == "REJ-HUMAIN-REQUIS"
    assert _lire(session) == avant


def test_contexte_autre_demande_en_attente_ne_donne_pas_autorite(capacites, session):
    avant = _lire(session)
    with session() as cnx:
        # Une demande en attente ne vaut pas une signature, même si le rôle est humain.
        demande = approbations.creer_demande(cnx, DEP, "m4_resoudre_demande", {}, niveau=Niveau.N4)
        with contexte.executer_demande_approuvee(demande):
            reponse = capacites.appeler(OUTIL, _args())
    assert reponse["resultat"]["accepte"] is False, reponse
    assert reponse["resultat"]["verdict"]["code"] == "REJ-HUMAIN-REQUIS"
    assert _lire(session) == avant


def test_decision_humaine_legitime_reste_executable_en_autonome(capacites, session):
    with session() as cnx:
        identite.creer_personne(cnx, "manager-fictif", "Manager fictif", "mot-de-passe-fictif-123", ["manager"])
        demande = approbations.creer_demande(cnx, DEP, OUTIL, _args(), niveau=Niveau.N4)
        decision = approbations.decider(
            cnx, demande, True, "manager-fictif", {k: v[1] for k, v in capacites.index.items()},
            capacites.departements, motif="Revue humaine fictive.",
        )
    assert decision["statut"] == "executee", decision
    assert decision["reponse"]["resultat"]["resultat"]["statut"] == "completed_verified"
    maillons = _lire(session)
    assert len(maillons) == 2 and maillons[-1]["decision_revue"] == "verifiee"


def test_device_legacy_reste_refuse_sans_mutation(capacites, session):
    avant = _lire(session)
    with contexte.appele_par_appareil(contexte.IdentiteAppelante("admin-fictif", "admin", source="appareil")):
        reponse = capacites.appeler(OUTIL, _args())
    assert reponse["ok"] is False and reponse["erreur"] == "REJ-SOURCES-CHANGEES"
    assert _lire(session) == avant


def test_registre_injecte_reste_un_seam_pur_explicite():
    reg = registre.Registre()
    _semer(reg)
    outil = next(o for o in outils(registre_cible=reg) if o.nom == OUTIL)
    reponse = executer(outil, _args())
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    assert etats.statut_courant(reg, INTERVENTION) == "completed_verified"
