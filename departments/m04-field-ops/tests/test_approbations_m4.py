"""Revue humaine d'une complétion, par les VRAIES approbations du socle (ADR-0009 §5, PLAN
T1.3-b) : politique `department.yaml`, signature personne + rôle de `opsys.approbations.decider`,
et `attentes()` (file du propriétaire) — sur le VRAI manifeste et les VRAIS outils de M4, jamais
une doublure.

Complète `test_outbox.py` (mécanique pure de `resoudre_revue_completion`, sans identité) : ici,
le sujet est « qui peut décider », pas « ce que la décision écrit ».
"""

from __future__ import annotations

from pathlib import Path

import pytest
from m4_field_ops import cedule
from m4_field_ops import registre as registre_mod
from m4_field_ops.outils import consommateurs, outils

from opsys import approbations, identite, stockage
from opsys.departements import lire_manifeste
from opsys.outils import Niveau, executer_atomique

_M4_RACINE = Path(__file__).resolve().parents[1]

SEL = "sel-approbations-m4"
VILLE = "Montreal"
FIX_GPS = {"latitude": 45.5088, "longitude": -73.5878}
ATTESTATION = {"fictif": True, "appareil_id": "APP-REVUE"}
FENETRE = {"debut": "2025-06-02T07:00:00+00:00", "fin": "2025-06-02T19:00:00+00:00"}
_PREUVES_OK = {
    "checklist_complete": True, "photos_apres": ["photo-apres.jpg"], "notes": "RAS.", "signature": None,
}


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    """Base SQLite temporaire migrée, comme au démarrage de l'instance (ADR-0009)."""
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


def _dep_m4():
    """Le VRAI manifeste de M4 — pas une doublure — tel que `opsys verifier` le lirait."""
    return lire_manifeste(_M4_RACINE)


def _contrat(lead_id):
    return {
        "lead_id": lead_id, "conversation_id": "C1", "type_travaux": "renovation_totale",
        "ville": VILLE, "canal": "telephone",
        "contact": {"nom": "Client", "telephone": "0102030405"}, "urgence_declaree": False,
    }


def _marqueur(lead_id):
    return {
        "readiness_ok": True, "lead_id": lead_id, "hash_tete_registre": None,
        "horodatage": "2025-06-01T12:00:00+00:00", "empreinte": "ab" * 32,
    }


def _completion_en_revue(par_nom, lead_id):
    """Mène une intervention jusqu'à `completed_pending_review`, par les VRAIS outils (comme un
    agent le ferait) : `m4_completer_intervention` fixe toujours `ecart_detecte=True` (T1.1-b),
    jamais `completed_verified` directement — c'est exactement l'état que la revue humaine doit
    ensuite trancher."""
    plan = executer_atomique(par_nom["m4_planifier_intervention"], {
        "contrat": _contrat(lead_id), "marqueur": _marqueur(lead_id),
        "horodatage": "2025-06-02T08:00:00+00:00", "sel": SEL,
        "techniciens_disponibles": ["T1"], "fenetres_disponibles": [FENETRE],
    })
    assert plan["ok"] is True, plan
    i_id = plan["resultat"]["intervention_id"]

    depart = executer_atomique(par_nom["m4_demarrer_route"], {
        "intervention_id": i_id, "technicien_id": "T1", "horodatage": "2025-06-02T08:30:00+00:00",
    })
    assert depart["ok"] is True and depart["resultat"]["accepte"] is True, depart

    token = cedule.tokeniser_ville(SEL, VILLE)
    referentiel = {token: {"latitude": 45.5017, "longitude": -73.5673, "rayon_km": 25.0}}
    for action, horo in (("arrivee", "2025-06-02T09:00:00+00:00"), ("depart", "2025-06-02T11:30:00+00:00")):
        r = executer_atomique(par_nom["m4_pointer"], {
            "intervention_id": i_id, "technicien_id": "T1", "action": action, "horodatage": horo,
            "fix_gps": FIX_GPS, "attestation": ATTESTATION, "fenetre_travail": FENETRE,
            "referentiel_villes": referentiel, "ville": VILLE, "sel": SEL,
        })
        assert r["ok"] is True and r["resultat"]["accepte"] is True, r

    completion = executer_atomique(par_nom["m4_completer_intervention"], {
        "intervention_id": i_id, "horodatage": "2025-06-02T11:35:00+00:00",
        "preuves_completion": _PREUVES_OK,
    })
    assert completion["ok"] is True and completion["resultat"]["accepte"] is True, completion
    assert completion["resultat"]["resultat"]["statut"] == "completed_pending_review"
    return i_id


def _demande_revue(cnx, i_id, decision, motif="Motif de test."):
    return approbations.creer_demande(
        cnx, "m04-field-ops", "m4_resoudre_revue_completion",
        {"intervention_id": i_id, "decision": decision, "horodatage": "2025-06-02T12:00:00+00:00",
         "motif": motif},
        niveau=Niveau.N4,
    )


# -- l'outil déclare N4 (ADR-0009 §4) -----------------------------------------------------------


def test_outil_resoudre_revue_completion_declare_n4():
    par_nom = {o.nom: o for o in outils()}
    assert par_nom["m4_resoudre_revue_completion"].niveau_effectif is Niveau.N4


# -- politique department.yaml (ADR-0009 §5, PLAN T1.3-b) ----------------------------------------


def test_department_yaml_declare_n3_n4_manager_admin_nathan_owner():
    dep = _dep_m4()
    assert dep.roles_autorises(Niveau.N3) == {"manager", "admin", "nathan_owner"}
    assert dep.roles_autorises(Niveau.N4) == {"manager", "admin", "nathan_owner"}
    # N5 reste une frontière FIXE de l'ADR, jamais configurable par un manifeste.
    assert dep.roles_autorises(Niveau.N5) == frozenset({"nathan_owner"})


# -- decider : rôle autorisé ou non, jamais un agent seul -----------------------------------------


def test_revue_par_personne_autorisee_mene_a_completed_verified(base_durable):
    dep = _dep_m4()
    par_nom = {o.nom: o for o in outils()}
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "gerant", "Une Gérante", "mot-de-passe-gerante-1234", ["manager"])
        i_id = _completion_en_revue(par_nom, "L-REVUE-AUTORISEE")
        ident = _demande_revue(cnx, i_id, "verifiee", motif="Photos et checklist conformes.")

        decision = approbations.decider(cnx, ident, True, "gerant", par_nom, {"m04-field-ops": dep},
                                        motif="Vérifié en personne sur place.")
    assert decision["statut"] == "executee"
    assert decision["reponse"]["ok"] is True
    assert decision["reponse"]["resultat"]["accepte"] is True
    assert decision["reponse"]["resultat"]["resultat"]["statut"] == "completed_verified"

    # SES traces : le VRAI registre durable de M4, pas seulement la réponse de decider.
    statut = executer_atomique(par_nom["m4_statut_intervention"], {"intervention_id": i_id})
    assert statut["resultat"]["statut"] == "completed_verified"


def test_revue_par_employe_refusee_rien_execute(base_durable):
    """Fail-closed (ADR-0009 §5) : un employé n'est autorisé pour AUCUN niveau N3/N4 de M4,
    même si la demande est par ailleurs légitime — jamais un agent seul, jamais un rôle qui ne
    figure pas explicitement dans department.yaml/approbations.n4."""
    dep = _dep_m4()
    par_nom = {o.nom: o for o in outils()}
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "employe1", "Un Employé", "mot-de-passe-employe-1234", ["employee"])
        i_id = _completion_en_revue(par_nom, "L-REVUE-EMPLOYE")
        ident = _demande_revue(cnx, i_id, "verifiee")

        with pytest.raises(ValueError, match="aucun rôle autorisé"):
            approbations.decider(cnx, ident, True, "employe1", par_nom, {"m04-field-ops": dep})
        [encore] = approbations.lister(cnx, "en_attente")
        assert encore["id"] == ident  # rien exécuté, la demande reste en attente

    statut = executer_atomique(par_nom["m4_statut_intervention"], {"intervention_id": i_id})
    assert statut["resultat"]["statut"] == "completed_pending_review"  # inchangé


def test_decision_citee_personne_role_socle_et_motif_metier_m4(base_durable):
    """« La décision cite la personne, le rôle et le motif » (PLAN T1.3-b) — vérifié aux DEUX
    endroits où c'est écrit : la demande d'approbation du socle (decide_par/decide_role, signée
    par `decider`) ET le maillon de M4 (motif_revue, le contenu métier de la décision)."""
    dep = _dep_m4()
    par_nom = {o.nom: o for o in outils()}
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "admin1", "Une Admin", "mot-de-passe-admin1-1234", ["admin"])
        i_id = _completion_en_revue(par_nom, "L-REVUE-SIGNEE")
        ident = _demande_revue(cnx, i_id, "correction", motif="Photo après-chantier manquante.")
        approbations.decider(cnx, ident, True, "admin1", par_nom, {"m04-field-ops": dep},
                              motif="Écart confirmé au téléphone avec le technicien.")

    with stockage.transaction() as cnx:
        [traitee] = approbations.lister(cnx, "executee")
    assert (traitee["decide_par"], traitee["decide_role"]) == ("admin1", "admin")
    assert traitee["motif_decision"] == "Écart confirmé au téléphone avec le technicien."

    with stockage.transaction():
        reg = registre_mod.Registre(stockage.maillons("m04-field-ops", "principal"))
    dernier = reg.lire()[-1]
    assert dernier["intervention_id"] == i_id
    assert dernier["decision_revue"] == "correction"
    assert dernier["motif_revue"] == "Photo après-chantier manquante."
    assert dernier["statut"] == "completed_pending_review"  # correction : jamais réouvert (FSM)


# -- attentes() : file du propriétaire (ADR-0009 §5, PLAN T1.3-b §2) -----------------------------


def test_attentes_liste_la_completion_en_revue_avant_tout_signal_m6(base_durable):
    dep = _dep_m4()
    par_nom = {o.nom: o for o in outils()}
    i_id = _completion_en_revue(par_nom, "L-ATTENTE-SANS-M6")

    with stockage.transaction() as cnx:
        file = approbations.file_proprietaire(cnx, {"m04-field-ops": dep})
    [item] = [i for i in file if i["id"] == i_id]
    assert item["type"] == "completion_en_revue"
    assert item["departement"] == "m04-field-ops"
    assert item["niveau"] == "N4"
    assert set(item) == {"type", "id", "resume", "niveau", "depuis", "action_proposee", "departement"}
    assert "non encore reçue" in item["resume"]


def test_attentes_signale_le_signal_critique_de_m6_une_fois_recu(base_durable):
    dep = _dep_m4()
    par_nom = {o.nom: o for o in outils()}
    i_id = _completion_en_revue(par_nom, "L-ATTENTE-AVEC-M6")

    boite = executer_atomique(par_nom["m4_lire_outbox"], {})
    wct = next(e["wct"] for e in boite["resultat"] if e["wct"]["intervention_id"] == i_id)

    with stockage.transaction():
        resultat = consommateurs()["m6.variance_chantier"]({
            "evenement_id": "m6-variance-critique-test", "wct_id": wct["wct_id"],
            "intervention_id": i_id, "chantier_id": "C-TEST",
            "statut_variance": "evaluee", "signal_critique": True, "seuil_pourcentage": 0.30,
            "horodatage_completion": wct["horodatage_completion"],
        })
    assert resultat["traite"] is True and resultat["verifie"] is False

    with stockage.transaction() as cnx:
        file = approbations.file_proprietaire(cnx, {"m04-field-ops": dep})
    [item] = [i for i in file if i["id"] == i_id]
    assert "CRITIQUE" in item["resume"]

    # Toujours completed_pending_review : le signal critique seul n'a RIEN exécuté (fail-closed,
    # confirmé par _recevoir_variance_chantier ci-dessus).
    statut = executer_atomique(par_nom["m4_statut_intervention"], {"intervention_id": i_id})
    assert statut["resultat"]["statut"] == "completed_pending_review"


def test_attentes_ne_liste_plus_apres_une_revue_verifiee(base_durable):
    dep = _dep_m4()
    par_nom = {o.nom: o for o in outils()}
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "nathan", "Nathan St-Louis", "mot-de-passe-nathan-1234", ["nathan_owner"])
        i_id = _completion_en_revue(par_nom, "L-ATTENTE-RESOLUE")
        ident = _demande_revue(cnx, i_id, "verifiee", motif="Conforme.")
        approbations.decider(cnx, ident, True, "nathan", par_nom, {"m04-field-ops": dep})
        file = approbations.file_proprietaire(cnx, {"m04-field-ops": dep})
    assert not any(item["id"] == i_id for item in file)


def test_attentes_reste_listee_apres_une_correction(base_durable):
    """Une correction NOMME un problème sans jamais réouvrir le chantier (FSM) : la complétion
    reste `completed_pending_review`, donc reste dans la file — le propriétaire sait qu'il reste
    quelque chose à trancher."""
    dep = _dep_m4()
    par_nom = {o.nom: o for o in outils()}
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "admin1", "Une Admin", "mot-de-passe-admin1-1234", ["admin"])
        i_id = _completion_en_revue(par_nom, "L-ATTENTE-CORRIGEE")
        ident = _demande_revue(cnx, i_id, "correction", motif="Signature client manquante.")
        approbations.decider(cnx, ident, True, "admin1", par_nom, {"m04-field-ops": dep})
        file = approbations.file_proprietaire(cnx, {"m04-field-ops": dep})
    [item] = [i for i in file if i["id"] == i_id]
    assert item["type"] == "completion_en_revue"
