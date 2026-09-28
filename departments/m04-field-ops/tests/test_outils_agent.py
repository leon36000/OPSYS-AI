"""Capacités d'agent de M4 : contrat des outils et chaîne d'intervention composée."""

from __future__ import annotations

from pathlib import Path

from m4_field_ops.outils import outils
from m4_field_ops.registre import Registre

from opsys.departements import lire_manifeste
from opsys.outils import Autonomie, Niveau, executer

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
        "m4_resoudre_demande", "m4_completer_intervention", "m4_resoudre_revue_completion",
    ]
    lectures_t0 = [
        "m4_statut_intervention", "m4_lister_pending_review",
        "m4_volumetrie_pending_review", "m4_lire_outbox", "m4_produire_digest",
        "m4_lister_interventions", "m4_produire_brouillon_temps",
    ]
    for nom in ecritures_t1:
        assert par_nom[nom].autonomie == Autonomie.T1, nom
    for nom in lectures_t0:
        assert par_nom[nom].autonomie == Autonomie.T0, nom
    assert par_nom["m4_notifier_client_completion"].autonomie == Autonomie.T2
    # PLAN T1.3-b : seul outil M4 dont le niveau N est EXPLICITE (N4, pas le défaut T1->N3) —
    # revue humaine d'une complétion, écriture finale (ADR-0009 §4), jamais un agent seul.
    assert par_nom["m4_resoudre_revue_completion"].niveau_effectif is Niveau.N4
    for nom in ecritures_t1:
        if nom != "m4_resoudre_revue_completion":
            assert par_nom[nom].niveau is None, f"{nom} : niveau devrait rester implicite (N3 via T1)"


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
        preuves_completion={
            "checklist_complete": True,
            "photos_apres": ["photo-apres-1.jpg"],
            "notes": "Aucun imprévu.",
            "signature": None,
        },
    )
    assert completion["ok"] is True and completion["resultat"]["accepte"] is True
    assert completion["resultat"]["resultat"]["duree_reelle_minutes"] == 150
    assert completion["resultat"]["resultat"]["statut"] == "completed_pending_review"

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
    # Un écart métier validé EST un écart détecté (ecarts.py fixe ecart_detecte=True) :
    # l'issue est completed_pending_review, jamais completed_verified (T1.1-b#2).
    assert resolution["resultat"]["resultat"]["statut"] == "completed_pending_review"

    boite = _appeler(par_nom, "m4_lire_outbox")["resultat"]
    assert any(e["wct"]["intervention_id"] == i_id and e["wct"]["ecart_signale"] is True for e in boite)


# ------------------------------------------------------------------ T1.1-b#3 : PreuvesCompletion
_PREUVES_OK = {
    "checklist_complete": True,
    "photos_apres": ["photo-apres-1.jpg"],
    "notes": "Aucun imprévu.",
    "signature": None,
}


def _mener_a_sur_site(par_nom, lead_id="L-PREUVES"):
    plan = _appeler(
        par_nom, "m4_planifier_intervention",
        contrat={**CONTRAT_VALIDE, "lead_id": lead_id},
        marqueur={**MARQUEUR_VALIDE, "lead_id": lead_id},
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
    return i_id


def test_completer_intervention_preuves_valides_accepte():
    par_nom = _outils_par_nom()
    i_id = _mener_a_sur_site(par_nom)
    completion = _appeler(
        par_nom, "m4_completer_intervention",
        intervention_id=i_id, horodatage="2025-06-02T11:35:00+00:00",
        preuves_completion=_PREUVES_OK,
    )
    assert completion["ok"] is True and completion["resultat"]["accepte"] is True
    assert completion["resultat"]["resultat"]["statut"] == "completed_pending_review"


def test_un_agent_ne_peut_pas_declarer_l_absence_d_ecart():
    """Le code calcule, le modèle orchestre : completed_verified n'est pas à la portée d'un
    argument d'outil. `ecart_detecte` ne fait plus partie du schéma : le fournir est refusé."""
    par_nom = _outils_par_nom()
    i_id = _mener_a_sur_site(par_nom, lead_id="L-SANS-ECART-AFFIRME")
    completion = executer(par_nom["m4_completer_intervention"], {
        "intervention_id": i_id, "horodatage": "2025-06-02T11:35:00+00:00",
        "preuves_completion": _PREUVES_OK, "ecart_detecte": False,
    })
    assert completion["ok"] is False and completion["erreur"] == "arguments_invalides"
    statut = _appeler(par_nom, "m4_statut_intervention", intervention_id=i_id)
    assert statut["resultat"]["statut"] == "sur_site"


def test_completer_intervention_checklist_incomplete_refuse_rien_ecrit():
    par_nom = _outils_par_nom()
    i_id = _mener_a_sur_site(par_nom, lead_id="L-PREUVES-CHECKLIST")
    preuves_incompletes = {**_PREUVES_OK, "checklist_complete": False}
    completion = _appeler(
        par_nom, "m4_completer_intervention",
        intervention_id=i_id, horodatage="2025-06-02T11:35:00+00:00",
        preuves_completion=preuves_incompletes,
    )
    assert completion["ok"] is True
    assert completion["resultat"]["accepte"] is False
    assert completion["resultat"]["verdict"]["code"] == "REJ-CHAMP-VIDE"
    # Rien n'a été écrit : aucun WCT, l'intervention reste sur_site.
    statut = _appeler(par_nom, "m4_statut_intervention", intervention_id=i_id)
    assert statut["resultat"]["statut"] == "sur_site"
    boite = _appeler(par_nom, "m4_lire_outbox")["resultat"]
    assert not any(e["wct"]["intervention_id"] == i_id for e in boite)


def test_completer_intervention_photos_apres_vide_refuse():
    par_nom = _outils_par_nom()
    i_id = _mener_a_sur_site(par_nom, lead_id="L-PREUVES-PHOTOS")
    completion = _appeler(
        par_nom, "m4_completer_intervention",
        intervention_id=i_id, horodatage="2025-06-02T11:35:00+00:00",
        preuves_completion={**_PREUVES_OK, "photos_apres": []},
    )
    assert completion["resultat"]["accepte"] is False
    assert completion["resultat"]["verdict"]["code"] == "REJ-CHAMP-VIDE"


def test_completer_intervention_signature_requise_absente_refuse():
    par_nom = _outils_par_nom()
    i_id = _mener_a_sur_site(par_nom, lead_id="L-PREUVES-SIGNATURE")
    completion = _appeler(
        par_nom, "m4_completer_intervention",
        intervention_id=i_id, horodatage="2025-06-02T11:35:00+00:00",
        preuves_completion=_PREUVES_OK, signature_requise=True,
    )
    assert completion["resultat"]["accepte"] is False
    assert completion["resultat"]["verdict"]["code"] == "REJ-CHAMP-MANQUANT"


def test_completer_intervention_signature_requise_fournie_accepte():
    par_nom = _outils_par_nom()
    i_id = _mener_a_sur_site(par_nom, lead_id="L-PREUVES-SIGNATURE-OK")
    completion = _appeler(
        par_nom, "m4_completer_intervention",
        intervention_id=i_id, horodatage="2025-06-02T11:35:00+00:00",
        preuves_completion={**_PREUVES_OK, "signature": "Client X"},
        signature_requise=True,
    )
    assert completion["resultat"]["accepte"] is True
    assert completion["resultat"]["resultat"]["statut"] == "completed_pending_review"


def test_completer_intervention_sans_preuves_arguments_invalides():
    """Les preuves sont REQUISES par le schéma de l'outil : les omettre est un refus
    de schéma, pas une exécution silencieuse."""
    par_nom = _outils_par_nom()
    i_id = _mener_a_sur_site(par_nom, lead_id="L-PREUVES-MANQUANTES")
    completion = executer(par_nom["m4_completer_intervention"], {
        "intervention_id": i_id, "horodatage": "2025-06-02T11:35:00+00:00",
    })
    assert completion["ok"] is False
    assert completion["erreur"] == "arguments_invalides"


# ------------------------------------------------------------------ T1.1-b#4 : m4_lister_interventions
def test_lister_interventions_sans_donnee_de_contact():
    par_nom = _outils_par_nom()
    plan = _appeler(
        par_nom, "m4_planifier_intervention",
        contrat={**CONTRAT_VALIDE, "lead_id": "L-LISTE"},
        marqueur={**MARQUEUR_VALIDE, "lead_id": "L-LISTE"},
        horodatage="2025-06-02T08:00:00+00:00", sel=SEL,
        techniciens_disponibles=["T1"], fenetres_disponibles=[FENETRE],
        devis_id="DEVIS-LISTE-1",
    )["resultat"]
    i_id = plan["intervention_id"]

    toutes = _appeler(par_nom, "m4_lister_interventions")
    assert toutes["ok"] is True
    entrees = {e["intervention_id"]: e for e in toutes["resultat"]}
    assert entrees[i_id]["statut"] == "planifiee"
    assert entrees[i_id]["lead_id"] == "L-LISTE"
    assert entrees[i_id]["devis_id"] == "DEVIS-LISTE-1"
    for e in toutes["resultat"]:
        assert "contact" not in e
        for cle_interdite in ("nom", "telephone", "courriel"):
            assert cle_interdite not in e

    filtrees = _appeler(par_nom, "m4_lister_interventions", statut="planifiee")
    assert i_id in {e["intervention_id"] for e in filtrees["resultat"]}

    vides = _appeler(par_nom, "m4_lister_interventions", statut="annulee")
    assert vides["resultat"] == []


def test_lister_interventions_statut_hors_schema_arguments_invalides():
    par_nom = _outils_par_nom()
    reponse = executer(par_nom["m4_lister_interventions"], {"statut": "statut_pirate"})
    assert reponse["ok"] is False
    assert reponse["erreur"] == "arguments_invalides"


# ------------------------------------------------------------------ T1.1-c#3/#4 : m4_produire_brouillon_temps
def test_produire_brouillon_temps_nominal():
    par_nom = _outils_par_nom()
    i_id = _mener_a_sur_site(par_nom, lead_id="L-TEMPS")
    completion = _appeler(
        par_nom, "m4_completer_intervention",
        intervention_id=i_id, horodatage="2025-06-02T11:35:00+00:00",
        preuves_completion=_PREUVES_OK,
    )
    assert completion["resultat"]["accepte"] is True

    brouillon = _appeler(
        par_nom, "m4_produire_brouillon_temps",
        periode={"debut": "2025-06-02", "fin": "2025-06-02"},
    )
    assert brouillon["ok"] is True and brouillon["resultat"]["accepte"] is True
    lignes = brouillon["resultat"]["resultat"]["lignes"]
    assert any(ligne["intervention_id"] == i_id and ligne["minutes_travail"] == 150 for ligne in lignes)
    assert brouillon["resultat"]["resultat"]["depassements"] == []


def test_produire_brouillon_temps_seuil_minutes_signale_depassement():
    par_nom = _outils_par_nom()
    i_id = _mener_a_sur_site(par_nom, lead_id="L-TEMPS-DEPASSEMENT")
    _appeler(
        par_nom, "m4_completer_intervention",
        intervention_id=i_id, horodatage="2025-06-02T11:35:00+00:00",
        preuves_completion=_PREUVES_OK,
    )
    brouillon = _appeler(
        par_nom, "m4_produire_brouillon_temps",
        periode={"debut": "2025-06-02", "fin": "2025-06-02"}, seuil_minutes=100,
    )
    assert brouillon["ok"] is True and brouillon["resultat"]["accepte"] is True
    depassements = {d["technicien_id"]: d for d in brouillon["resultat"]["resultat"]["depassements"]}
    assert depassements["T1"]["depassement_detecte"] is True


def test_produire_brouillon_temps_periode_invalide_refuse():
    par_nom = _outils_par_nom()
    reponse = _appeler(par_nom, "m4_produire_brouillon_temps", periode={"debut": "2025-06-02"})
    assert reponse["ok"] is True
    assert reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "REJ-CONTRAT-INVALIDE"
