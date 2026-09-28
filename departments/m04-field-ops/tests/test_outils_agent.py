"""Capacités d'agent de M4 : contrat des outils et chaîne d'intervention composée."""

from __future__ import annotations

from pathlib import Path

from m4_field_ops.outils import outils
from m4_field_ops.registre import Registre

from opsys.departements import lire_manifeste
from opsys.outils import Autonomie, executer

SEL = "sel-de-test-agent"
VILLE = "Montreal"

CONTRAT_VALIDE = {
    "lead_id": "L-AGENT-1",
    "conversation_id": "C1",
    "type_travaux": "renovation_totale",
    "ville": VILLE,
    "canal": "telephone",
    "contact": {"nom": "Dupont", "telephone": "0102030405"},
    "urgence_declaree": True,
}
MARQUEUR_VALIDE = {
    "readiness_ok": True,
    "lead_id": "L-AGENT-1",
    "hash_tete_registre": None,
    "horodatage": "2025-06-01T12:00:00+00:00",
    "empreinte": "ab" * 32,
}
FENETRE = {"debut": "2025-06-02T07:00:00+00:00", "fin": "2025-06-02T19:00:00+00:00"}
FIX_GPS = {"latitude": 45.5088, "longitude": -73.5878}
ATTESTATION = {"fictif": True, "appareil_id": "APP-1"}


def _outils_par_nom():
    """Registre EN MÉMOIRE, explicite : `outils()` sans argument adosse le registre de
    production au stockage durable de l'instance (ADR-0009), qu'aucun test unitaire de ce
    fichier ne monte — voir `departments/m04-field-ops/tests/test_registre_durable.py` pour la
    preuve du branchement durable lui-même."""
    return {o.nom: o for o in outils(Registre())}


def _appeler(nom_a_outil, nom, **kwargs):
    return executer(nom_a_outil[nom], kwargs)


def test_manifeste_et_outils_coherents():
    dep = lire_manifeste(Path(__file__).resolve().parents[1])
    noms = [o.nom for o in dep.charger_outils()]
    assert noms[0] == "m4_planifier_intervention"
    assert all(nom.startswith("m4_") for nom in noms)


def test_autonomie_attendue_par_outil():
    par_nom = _outils_par_nom()
    ecritures_t1 = [
        "m4_planifier_intervention", "m4_demarrer_route", "m4_signaler_report",
        "m4_annuler_intervention", "m4_pointer", "m4_creer_demande_ecart",
        "m4_resoudre_demande", "m4_completer_intervention",
    ]
    lectures_t0 = [
        "m4_statut_intervention", "m4_lister_pending_review",
        "m4_volumetrie_pending_review", "m4_lire_outbox", "m4_produire_digest",
    ]
    for nom in ecritures_t1:
        assert par_nom[nom].autonomie == Autonomie.T1, nom
    for nom in lectures_t0:
        assert par_nom[nom].autonomie == Autonomie.T0, nom
    assert par_nom["m4_notifier_client_completion"].autonomie == Autonomie.T2


# ------------------------------------------------------------------ outil composé de bout en bout
def test_planifier_intervention_nominal_inscrit_et_cedule():
    par_nom = _outils_par_nom()
    reponse = _appeler(
        par_nom, "m4_planifier_intervention",
        contrat=CONTRAT_VALIDE, marqueur=MARQUEUR_VALIDE,
        horodatage="2025-06-02T08:00:00+00:00", sel=SEL,
        techniciens_disponibles=["T1"], fenetres_disponibles=[FENETRE],
    )
    assert reponse["ok"] is True, reponse
    resultat = reponse["resultat"]
    assert resultat["etape"] == "complet"
    assert resultat["statut"] == "planifiee"
    assert resultat["non_cedulee"] is False
    assert resultat["assignation"]["technicien_id"] == "T1"
    assert resultat["assignation"]["intervention_id"] == resultat["intervention_id"]


def test_planifier_intervention_refuse_contrat_invalide():
    par_nom = _outils_par_nom()
    contrat_invalide = dict(CONTRAT_VALIDE)
    contrat_invalide["prix"] = 100  # champ interdit (frontière M4)
    reponse = _appeler(
        par_nom, "m4_planifier_intervention",
        contrat=contrat_invalide, marqueur=MARQUEUR_VALIDE,
        horodatage="2025-06-02T08:00:00+00:00", sel=SEL,
        techniciens_disponibles=["T1"], fenetres_disponibles=[FENETRE],
    )
    assert reponse["ok"] is True
    assert reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "REJ-FRONTIERE-VIOLEE"


def test_planifier_intervention_sans_technicien_disponible_non_cedulee():
    par_nom = _outils_par_nom()
    reponse = _appeler(
        par_nom, "m4_planifier_intervention",
        contrat=CONTRAT_VALIDE, marqueur=MARQUEUR_VALIDE,
        horodatage="2025-06-02T09:00:00+00:00", sel=SEL,
        techniciens_disponibles=[], fenetres_disponibles=[],
    )
    assert reponse["ok"] is True
    resultat = reponse["resultat"]
    assert resultat["etape"] == "cedule"
    assert resultat["assignation"] is None
    assert "avertissement_cedule" in resultat


def test_type_hors_contrat_refuse_par_le_schema():
    par_nom = _outils_par_nom()
    reponse = executer(par_nom["m4_planifier_intervention"], {
        "contrat": CONTRAT_VALIDE, "marqueur": MARQUEUR_VALIDE,
        "horodatage": "2025-06-02T08:00:00+00:00", "sel": SEL,
        "techniciens_disponibles": "pas-une-liste", "fenetres_disponibles": [FENETRE],
    })
    assert reponse["erreur"] == "arguments_invalides"


# ------------------------------------------------------------------ chaîne complète via les outils unitaires
def test_chaine_complete_planification_pointage_completion_digest_notification():
    par_nom = _outils_par_nom()

    plan = _appeler(
        par_nom, "m4_planifier_intervention",
        contrat=CONTRAT_VALIDE, marqueur=MARQUEUR_VALIDE,
        horodatage="2025-06-02T08:00:00+00:00", sel=SEL,
        techniciens_disponibles=["T1"], fenetres_disponibles=[FENETRE],
    )["resultat"]
    i_id = plan["intervention_id"]

    depart = _appeler(
        par_nom, "m4_demarrer_route",
        intervention_id=i_id, technicien_id="T1", horodatage="2025-06-02T08:30:00+00:00",
    )
    assert depart["ok"] is True and depart["resultat"]["accepte"] is True

    import m4_field_ops.cedule as cedule_mod
    token = cedule_mod.tokeniser_ville(SEL, VILLE)
    referentiel_villes = {token: {"latitude": 45.5017, "longitude": -73.5673, "rayon_km": 25.0}}

    arrivee = _appeler(
        par_nom, "m4_pointer",
        intervention_id=i_id, technicien_id="T1", action="arrivee",
        horodatage="2025-06-02T09:00:00+00:00", fix_gps=FIX_GPS, attestation=ATTESTATION,
        fenetre_travail=FENETRE, referentiel_villes=referentiel_villes, ville=VILLE, sel=SEL,
    )
    assert arrivee["ok"] is True and arrivee["resultat"]["accepte"] is True
    assert arrivee["resultat"]["resultat"]["statut"] == "sur_site"

    statut = _appeler(par_nom, "m4_statut_intervention", intervention_id=i_id)
    assert statut["resultat"]["statut"] == "sur_site"

    depart_pointage = _appeler(
        par_nom, "m4_pointer",
        intervention_id=i_id, technicien_id="T1", action="depart",
        horodatage="2025-06-02T11:30:00+00:00", fix_gps=FIX_GPS, attestation=ATTESTATION,
        fenetre_travail=FENETRE, referentiel_villes=referentiel_villes, ville=VILLE, sel=SEL,
    )
    assert depart_pointage["ok"] is True and depart_pointage["resultat"]["accepte"] is True

    completion = _appeler(
        par_nom, "m4_completer_intervention",
        intervention_id=i_id, horodatage="2025-06-02T11:35:00+00:00",
    )
    assert completion["ok"] is True and completion["resultat"]["accepte"] is True
    assert completion["resultat"]["resultat"]["duree_reelle_minutes"] == 150

    boite = _appeler(par_nom, "m4_lire_outbox")
    assert boite["ok"] is True
    assert len(boite["resultat"]) == 1
    assert boite["resultat"][0]["wct"]["intervention_id"] == i_id

    notif = _appeler(par_nom, "m4_notifier_client_completion", intervention_id=i_id)
    assert notif["ok"] is True
    message = notif["resultat"]
    assert message["intervention_id"] == i_id
    assert message["duree_reelle_minutes"] == 150
    assert "technicien_id" not in message
    assert "fix_gps_completion" not in message
    assert "lead_id" not in message
    assert "hash_maillon" not in message
    serialise = str(message)
    assert str(FIX_GPS["latitude"]) not in serialise
    assert "L-AGENT-1" not in serialise

    digest_reponse = _appeler(
        par_nom, "m4_produire_digest",
        date_cible="2025-06-02", horodatage_reference="2025-06-02T20:00:00+00:00",
    )
    assert digest_reponse["ok"] is True
    digest_resultat = digest_reponse["resultat"]["resultat"]
    assert any(e["intervention_id"] == i_id for e in digest_resultat["interventions_terminees"])


def test_notifier_client_sans_wct_refus_metier():
    par_nom = _outils_par_nom()
    reponse = _appeler(par_nom, "m4_notifier_client_completion", intervention_id="INEXISTANT")
    assert reponse["ok"] is False
    assert reponse["erreur"] == "refus_metier"


# ------------------------------------------------------------------ écart métier vs anomalie de pointage
def test_resoudre_demande_ecart_metier_via_outils_complete_avec_wct():
    par_nom = _outils_par_nom()
    plan = _appeler(
        par_nom, "m4_planifier_intervention",
        contrat={**CONTRAT_VALIDE, "lead_id": "L-ECART"},
        marqueur={**MARQUEUR_VALIDE, "lead_id": "L-ECART"},
        horodatage="2025-06-02T08:00:00+00:00", sel=SEL,
        techniciens_disponibles=["T1"], fenetres_disponibles=[FENETRE],
    )["resultat"]
    i_id = plan["intervention_id"]
    _appeler(par_nom, "m4_demarrer_route", intervention_id=i_id, technicien_id="T1",
             horodatage="2025-06-02T08:30:00+00:00")

    import m4_field_ops.cedule as cedule_mod
    token = cedule_mod.tokeniser_ville(SEL, VILLE)
    referentiel_villes = {token: {"latitude": 45.5017, "longitude": -73.5673, "rayon_km": 25.0}}
    for action, horo in (("arrivee", "2025-06-02T09:00:00+00:00"), ("depart", "2025-06-02T11:30:00+00:00")):
        r = _appeler(
            par_nom, "m4_pointer", intervention_id=i_id, technicien_id="T1", action=action,
            horodatage=horo, fix_gps=FIX_GPS, attestation=ATTESTATION,
            fenetre_travail=FENETRE, referentiel_villes=referentiel_villes, ville=VILLE, sel=SEL,
        )
        assert r["resultat"]["accepte"] is True, r

    demande = _appeler(
        par_nom, "m4_creer_demande_ecart", intervention_id=i_id,
        version_prevue={"duree_minutes": 120, "perimetre": "sdb", "materiaux": ["carrelage"]},
        version_declaree={"duree_minutes": 150, "perimetre": "sdb et couloir", "materiaux": ["carrelage", "plinthes"]},
        horodatage="2025-06-02T11:40:00+00:00",
    )["resultat"]["resultat"]
    demande_id = demande["demande_id"]

    volumetrie = _appeler(par_nom, "m4_volumetrie_pending_review")["resultat"]
    assert volumetrie["ecart_metier"] == 1

    resolution = _appeler(
        par_nom, "m4_resoudre_demande", demande_id=demande_id, decision="validee",
        horodatage="2025-06-02T12:00:00+00:00",
    )
    assert resolution["ok"] is True and resolution["resultat"]["accepte"] is True
    assert resolution["resultat"]["resultat"]["statut"] == "terminee"

    boite = _appeler(par_nom, "m4_lire_outbox")["resultat"]
    assert any(e["wct"]["intervention_id"] == i_id and e["wct"]["ecart_signale"] is True for e in boite)
