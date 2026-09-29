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

from opsys import approbations, approbations_appareil, identite, stockage
from opsys.departements import lire_manifeste
from opsys.outils import Niveau, executer_atomique

_M4_RACINE = Path(__file__).resolve().parents[1]

SEL = "sel-approbations-m4"
VILLE = "Montreal"
FIX_GPS = {"latitude": 45.5088, "longitude": -73.5878}
ATTESTATION = {"fictif": True, "appareil_id": "APP-REVUE"}
FENETRE = {"debut": "2025-06-02T07:00:00+00:00", "fin": "2025-06-02T19:00:00+00:00"}


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


def _completion_en_revue(par_nom, lead_id, deposer_photo_test, avec_ecart_metier_ouvert=False):
    """Mène une intervention jusqu'à `completed_pending_review`, par les VRAIS outils (comme un
    agent le ferait) : `m4_completer_intervention` ne rend jamais `completed_verified`
    directement (vérification en attente, T1.5-c) — c'est exactement l'état que la revue humaine
    doit ensuite trancher. `avec_ecart_metier_ouvert` : une demande d'écart métier est ouverte
    avant la complétion (le WCT dit alors `ecart_signale` vrai)."""
    plan = executer_atomique(par_nom["m4_planifier_intervention"], {
        "contrat": _contrat(lead_id), "marqueur": _marqueur(lead_id),
        "horodatage": "2025-06-02T08:00:00+00:00", "sel": SEL,
        "techniciens_disponibles": ["T1"], "fenetres_disponibles": [FENETRE],
    })
    assert plan["ok"] is True, plan
    i_id = plan["resultat"]["intervention_id"]

    # PLAN T4.2 (POLITIQUE-geolocalisation.md §4) : m4_pointer n'enregistre un fix GPS QUE si le
    # consentement est actif — précondition nécessaire avant tout pointage à fix réel ci-dessous.
    consentement = executer_atomique(par_nom["m4_definir_consentement_gps"], {
        "technicien_id": "T1", "action": "donne", "horodatage": "2025-06-02T07:00:00+00:00",
        "version_politique": "POLITIQUE-geolocalisation-v1-test",
        "preuve": {"fictif": True, "reference": "consentement-test"},
    })
    assert consentement["ok"] is True and consentement["resultat"]["accepte"] is True, consentement

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

    if avec_ecart_metier_ouvert:
        demande = executer_atomique(par_nom["m4_creer_demande_ecart"], {
            "intervention_id": i_id,
            "version_prevue": {"duree_minutes": 120, "perimetre": "gouttières", "materiaux": ["gouttière"]},
            "version_declaree": {"duree_minutes": 150, "perimetre": "gouttières et soffite",
                                 "materiaux": ["gouttière", "soffite"]},
            "horodatage": "2025-06-02T11:32:00+00:00",
        })
        assert demande["ok"] is True and demande["resultat"]["accepte"] is True, demande
    preuves_ok = {
        "checklist_complete": True, "photos_apres": [deposer_photo_test(par_nom)],
        "notes": "RAS.", "signature": None,
    }
    completion = executer_atomique(par_nom["m4_completer_intervention"], {
        "intervention_id": i_id, "horodatage": "2025-06-02T11:35:00+00:00",
        "preuves_completion": preuves_ok,
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


def test_revue_par_personne_autorisee_mene_a_completed_verified(base_durable, deposer_photo_test):
    dep = _dep_m4()
    par_nom = {o.nom: o for o in outils()}
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "gerant", "Une Gérante", "mot-de-passe-gerante-1234", ["manager"])
        i_id = _completion_en_revue(par_nom, "L-REVUE-AUTORISEE", deposer_photo_test)
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


def test_revue_par_employe_refusee_rien_execute(base_durable, deposer_photo_test):
    """Fail-closed (ADR-0009 §5) : un employé n'est autorisé pour AUCUN niveau N3/N4 de M4,
    même si la demande est par ailleurs légitime — jamais un agent seul, jamais un rôle qui ne
    figure pas explicitement dans department.yaml/approbations.n4."""
    dep = _dep_m4()
    par_nom = {o.nom: o for o in outils()}
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "employe1", "Un Employé", "mot-de-passe-employe-1234", ["employee"])
        i_id = _completion_en_revue(par_nom, "L-REVUE-EMPLOYE", deposer_photo_test)
        ident = _demande_revue(cnx, i_id, "verifiee")

        with pytest.raises(ValueError, match="aucun rôle autorisé"):
            approbations.decider(cnx, ident, True, "employe1", par_nom, {"m04-field-ops": dep})
        [encore] = approbations.lister(cnx, "en_attente")
        assert encore["id"] == ident  # rien exécuté, la demande reste en attente

    statut = executer_atomique(par_nom["m4_statut_intervention"], {"intervention_id": i_id})
    assert statut["resultat"]["statut"] == "completed_pending_review"  # inchangé


def test_decision_citee_personne_role_socle_et_motif_metier_m4(base_durable, deposer_photo_test):
    """« La décision cite la personne, le rôle et le motif » (PLAN T1.3-b) — vérifié aux DEUX
    endroits où c'est écrit : la demande d'approbation du socle (decide_par/decide_role, signée
    par `decider`) ET le maillon de M4 (motif_revue, le contenu métier de la décision)."""
    dep = _dep_m4()
    par_nom = {o.nom: o for o in outils()}
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "admin1", "Une Admin", "mot-de-passe-admin1-1234", ["admin"])
        i_id = _completion_en_revue(par_nom, "L-REVUE-SIGNEE", deposer_photo_test)
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


def test_attentes_liste_la_completion_en_revue_avant_tout_signal_m6(base_durable, deposer_photo_test):
    dep = _dep_m4()
    par_nom = {o.nom: o for o in outils()}
    i_id = _completion_en_revue(par_nom, "L-ATTENTE-SANS-M6", deposer_photo_test)

    with stockage.transaction() as cnx:
        file = approbations.file_proprietaire(cnx, {"m04-field-ops": dep})
    [item] = [i for i in file if i["id"] == i_id]
    assert item["type"] == "completion_en_revue"
    assert item["departement"] == "m04-field-ops"
    assert item["niveau"] == "N4"
    assert set(item) == {"type", "id", "resume", "niveau", "depuis", "action_proposee", "departement"}
    assert "non encore reçue" in item["resume"]
    # T1.5-c : rien n'est à décider avant la variance de M6, et aucun écart n'est signalé (le WCT dit faux).
    assert "aucun écart signalé" in item["resume"]
    assert item["action_proposee"].startswith("Rien à décider") and "verifiee" not in item["action_proposee"]


def _attente_apres_signal(par_nom, dep, i_id, **signal):
    boite = executer_atomique(par_nom["m4_lire_outbox"], {})
    wct = next(e["wct"] for e in boite["resultat"] if e["wct"]["intervention_id"] == i_id)
    with stockage.transaction():
        consommateurs()["m6.variance_chantier"]({
            "evenement_id": f"m6-variance-{signal['statut_variance']}", "wct_id": wct["wct_id"],
            "intervention_id": i_id, "chantier_id": "C-TEST", "seuil_pourcentage": 0.30,
            "horodatage_completion": wct["horodatage_completion"], **signal,
        })
    with stockage.transaction() as cnx:
        file = approbations.file_proprietaire(cnx, {"m04-field-ops": dep})
    [item] = [i for i in file if i["id"] == i_id]
    return item


def test_attentes_declaration_absente_dit_qu_on_attend_le_formulaire_sans_offrir_verifiee(
    base_durable, deposer_photo_test,
):
    """T1.5-c, décision écrite (`outils.attentes`) : entre « Terminer » et le formulaire des matériaux,
    la complétion en revue est une information juste (§6), pas une revue à trancher : « verifiee »
    court-circuiterait la comparaison de M6."""
    dep = _dep_m4()
    par_nom = {o.nom: o for o in outils()}
    i_id = _completion_en_revue(par_nom, "L-ATTENTE-DECLARATION", deposer_photo_test)

    item = _attente_apres_signal(par_nom, dep, i_id, statut_variance="declaration_absente", signal_critique=None)

    assert "variance M6 non finalisée (declaration_absente)" in item["resume"]
    assert "formulaire des matériaux de l'employé attendu, aucun écart signalé" in item["resume"]
    assert "CRITIQUE" not in item["resume"]
    assert item["action_proposee"].startswith("Rien à décider")
    assert "verifiee" not in item["action_proposee"] and "m4_resoudre_revue_completion" in item["action_proposee"]
    # Bornes de l'écran de l'app : au-delà, le socle tronque le texte (`approbations_appareil`).
    assert len(item["resume"]) <= approbations_appareil.LIMITE_RESUME_ATTENTE
    assert len(item["action_proposee"]) <= approbations_appareil.LIMITE_ACTION_ATTENTE


@pytest.mark.parametrize("signal", [
    {"statut_variance": "prevu_absent", "signal_critique": None},
    {"statut_variance": "seuil_absent", "signal_critique": None, "seuil_pourcentage": None},
    {"statut_variance": "evaluee", "signal_critique": True},
])
def test_attentes_offre_la_revue_quand_une_personne_doit_intervenir(base_durable, deposer_photo_test, signal):
    """Le prévu ou le seuil manquent, ou l'écart est critique : ce n'est pas l'employé qui bloque, une
    personne doit intervenir — le geste proposé est la revue (`verifiee` ou `correction`)."""
    dep = _dep_m4()
    par_nom = {o.nom: o for o in outils()}
    i_id = _completion_en_revue(par_nom, f"L-ATTENTE-{signal['statut_variance']}", deposer_photo_test)

    item = _attente_apres_signal(par_nom, dep, i_id, **signal)

    assert "verifiee" in item["action_proposee"] and "m4_resoudre_revue_completion" in item["action_proposee"]
    assert not item["action_proposee"].startswith("Rien à décider")


def test_attentes_un_ecart_metier_ouvert_a_la_completion_reste_a_trancher(base_durable, deposer_photo_test):
    """Une demande d'écart ouverte à la complétion (`wct.ecart_signale` vrai) n'attend pas seulement le
    formulaire : le résumé ne dit jamais « aucun écart » et la revue reste proposée."""
    dep = _dep_m4()
    par_nom = {o.nom: o for o in outils()}
    i_id = _completion_en_revue(par_nom, "L-ATTENTE-ECART-OUVERT", deposer_photo_test, avec_ecart_metier_ouvert=True)
    wct = next(e["wct"] for e in executer_atomique(par_nom["m4_lire_outbox"], {})["resultat"]
               if e["wct"]["intervention_id"] == i_id)
    assert wct["ecart_signale"] is True

    with stockage.transaction() as cnx:
        [item] = [i for i in approbations.file_proprietaire(cnx, {"m04-field-ops": dep}) if i["id"] == i_id]
    assert "écart métier ouvert à la complétion" in item["resume"] and "aucun écart" not in item["resume"]
    assert "verifiee" in item["action_proposee"]

    item = _attente_apres_signal(par_nom, dep, i_id, statut_variance="declaration_absente", signal_critique=None)
    assert "écart métier ouvert à la complétion" in item["resume"] and "aucun écart" not in item["resume"]
    assert "verifiee" in item["action_proposee"]


def test_attentes_signale_le_signal_critique_de_m6_une_fois_recu(base_durable, deposer_photo_test):
    dep = _dep_m4()
    par_nom = {o.nom: o for o in outils()}
    i_id = _completion_en_revue(par_nom, "L-ATTENTE-AVEC-M6", deposer_photo_test)

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


def test_attentes_ne_liste_plus_apres_une_revue_verifiee(base_durable, deposer_photo_test):
    dep = _dep_m4()
    par_nom = {o.nom: o for o in outils()}
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "nathan", "Nathan St-Louis", "mot-de-passe-nathan-1234", ["nathan_owner"])
        i_id = _completion_en_revue(par_nom, "L-ATTENTE-RESOLUE", deposer_photo_test)
        ident = _demande_revue(cnx, i_id, "verifiee", motif="Conforme.")
        approbations.decider(cnx, ident, True, "nathan", par_nom, {"m04-field-ops": dep})
        file = approbations.file_proprietaire(cnx, {"m04-field-ops": dep})
    assert not any(item["id"] == i_id for item in file)


def test_attentes_reste_listee_apres_une_correction(base_durable, deposer_photo_test):
    """Une correction NOMME un problème sans jamais réouvrir le chantier (FSM) : la complétion
    reste `completed_pending_review`, donc reste dans la file — le propriétaire sait qu'il reste
    quelque chose à trancher."""
    dep = _dep_m4()
    par_nom = {o.nom: o for o in outils()}
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "admin1", "Une Admin", "mot-de-passe-admin1-1234", ["admin"])
        i_id = _completion_en_revue(par_nom, "L-ATTENTE-CORRIGEE", deposer_photo_test)
        ident = _demande_revue(cnx, i_id, "correction", motif="Signature client manquante.")
        approbations.decider(cnx, ident, True, "admin1", par_nom, {"m04-field-ops": dep})
        file = approbations.file_proprietaire(cnx, {"m04-field-ops": dep})
    [item] = [i for i in file if i["id"] == i_id]
    assert item["type"] == "completion_en_revue"
