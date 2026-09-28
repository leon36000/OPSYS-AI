import copy
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import m4_field_ops.outbox as outbox_mod
import m4_field_ops.etats as etats_mod
import m4_field_ops.ecarts as ecarts_mod
import m4_field_ops.pointage as pointage_mod
import m4_field_ops.registre as registre_mod
import m4_field_ops.encodage as encodage_mod
import m4_field_ops.cedule as cedule_mod

# ------------------------------------------------------------------ module-level constants / helpers
SEL = "sel-de-test"
VILLE = "Montreal"
REFERENTIEL = {
    cedule_mod.tokeniser_ville(SEL, VILLE): {
        "latitude": 45.5017,
        "longitude": -73.5673,
        "rayon_km": 25.0,
    }
}
GPS_PROCHE = {"latitude": 45.5088, "longitude": -73.5878}
GPS_LOIN = {"latitude": 46.8139, "longitude": -71.2080}
ATTESTATION = {"fictif": True, "appareil_id": "APP-1"}
FENETRE = {"debut": "2025-06-02T07:00:00+00:00", "fin": "2025-06-02T19:00:00+00:00"}

CONTRAT_VALIDE = {
    "lead_id": "L1",
    "conversation_id": "C1",
    "type_travaux": "renovation_totale",
    "ville": VILLE,
    "canal": "telephone",
    "contact": {"nom": "Dupont", "telephone": "0102030405"},
    "urgence_declaree": True,
}

MARQUEUR_VALIDE = {
    "readiness_ok": True,
    "lead_id": "L1",
    "hash_tete_registre": None,
    "horodatage": "2025-06-01T12:00:00+00:00",
    "empreinte": "ab" * 32,
}

H1 = "2025-06-02T08:00:00+00:00"
H_ARRIVEE = "2025-06-02T09:00:00+00:00"
H_DEPART = "2025-06-02T11:30:00+00:00"          # 150 minutes after arrival
H_COMPLETION = "2025-06-02T11:35:00+00:00"
H_ANOMALIE = "2025-06-02T11:40:00+00:00"   # départ incohérent postérieur
H_APRES_ANOMALIE = "2025-06-02T11:45:00+00:00"

def _ajouter_intervention_sur_site(reg, lead_id, horodatage_inscription):
    """Inscrit une intervention DISTINCTE dans un registre existant.

    L'intervention_id est dérivé de (lead_id, horodatage) : réutiliser les deux
    donne le MÊME identifiant, donc la même intervention — piège mesuré, le test
    du consommateur croyait créer deux interventions et n'en créait qu'une.
    """
    contrat = dict(CONTRAT_VALIDE)
    contrat["lead_id"] = lead_id
    marqueur = dict(MARQUEUR_VALIDE)
    marqueur["lead_id"] = lead_id
    acc, ver = etats_mod.inscrire_intervention(contrat, marqueur, reg, horodatage_inscription, SEL)
    assert acc is not None, f"Inscription {lead_id} echouee: {ver}"
    i_id = acc["intervention_id"]
    assign = {"intervention_id": i_id, "technicien_id": "T1"}
    acc2, ver2 = etats_mod.transitionner(i_id, "en_route", reg, H_ARRIVEE, assignation=assign)
    assert acc2 is not None, f"Transition en_route echouee: {ver2}"
    for action, horo in (("arrivee", H_ARRIVEE), ("depart", H_DEPART)):
        acc_p, ver_p = pointage_mod.enregistrer_pointage(
            i_id, "T1", action, horo, GPS_PROCHE, ATTESTATION,
            assign, FENETRE, REFERENTIEL, VILLE, SEL, reg
        )
        assert acc_p is not None, f"Pointage {action} echoue: {ver_p}"
    return i_id


def _intervention_sur_site_avec_pointages():
    """Cree un registre avec inscription, transitions et deux pointages (arrivee, depart).
    Retourne (registre, intervention_id)."""
    reg = registre_mod.Registre()
    acc, ver = etats_mod.inscrire_intervention(CONTRAT_VALIDE, MARQUEUR_VALIDE, reg, H1, SEL)
    assert acc is not None, f"Inscription échouée: {ver}"
    i_id = acc["intervention_id"]
    assign = {"intervention_id": i_id, "technicien_id": "T1"}
    acc2, ver2 = etats_mod.transitionner(i_id, "en_route", reg, H_ARRIVEE, assignation=assign)
    assert acc2 is not None, f"Transition en_route échouée: {ver2}"

    acc_arr, ver_arr = pointage_mod.enregistrer_pointage(
        i_id, "T1", "arrivee", H_ARRIVEE, GPS_PROCHE, ATTESTATION,
        assign, FENETRE, REFERENTIEL, VILLE, SEL, reg
    )
    assert acc_arr is not None, f"Pointage arrivée échoué: {ver_arr}"

    acc_dep, ver_dep = pointage_mod.enregistrer_pointage(
        i_id, "T1", "depart", H_DEPART, GPS_PROCHE, ATTESTATION,
        assign, FENETRE, REFERENTIEL, VILLE, SEL, reg
    )
    assert acc_dep is not None, f"Pointage départ échoué: {ver_dep}"

    return reg, i_id

ASSIGNATION = lambda i_id: {"intervention_id": i_id, "technicien_id": "T1"}

# ======================================================================= Tests

def test_constantes_epinglees():
    assert outbox_mod.CONSOMMATEURS_CIBLES == ("M6", "M5", "M2", "M7", "M8", "M10")
    assert outbox_mod.CHAMPS_WCT == (
        "wct_id", "intervention_id", "lead_id", "technicien_id", "horodatage_completion",
        "fix_gps_completion", "duree_reelle_minutes", "ecart_signale", "revue_id",
        "hash_maillon", "consommateurs_cibles", "devis_id", "statut",
    )
    assert outbox_mod.STATUTS_COMPLETION == ("completed_pending_review", "completed_verified")

# ------------------------------------------------------------------ 1. CA-M4-11 — UN SEUL maillon
def test_completer_un_seul_maillon():
    reg, i_id = _intervention_sur_site_avec_pointages()
    taille_avant = len(reg.lire())
    accuse, verdict = outbox_mod.completer_intervention(i_id, H_COMPLETION, reg, ecart_detecte=False)
    assert accuse is not None, f"completer_intervention échec: {verdict}"
    assert len(reg.lire()) == taille_avant + 1

    dernier = reg.lire()[-1]
    assert dernier["type_entree"] == etats_mod.TYPE_TRANSITION
    assert dernier["statut"] == "completed_verified"
    assert dernier["statut_precedent"] == "sur_site"
    assert outbox_mod.CLE_WCT in dernier

    # Aucun autre maillon complété sans wct
    for m in reg.lire():
        if m.get("statut") in outbox_mod.STATUTS_COMPLETION:
            assert outbox_mod.CLE_WCT in m

    # Aucun wct hors d'un maillon complété
    for m in reg.lire():
        if outbox_mod.CLE_WCT in m:
            assert m["statut"] in outbox_mod.STATUTS_COMPLETION

# ------------------------------------------------------------------ 2. CA-M4-10 — rien avant terminee
def test_lire_outbox_vide_avant_completion():
    reg, i_id = _intervention_sur_site_avec_pointages()
    assert outbox_mod.lire_outbox(reg) == []
    for m in reg.lire():
        assert outbox_mod.CLE_WCT not in m

# ------------------------------------------------------------------ 3. Contrat WCT complet
def test_contrat_wct_complet():
    reg, i_id = _intervention_sur_site_avec_pointages()
    accuse, _ = outbox_mod.completer_intervention(i_id, H_COMPLETION, reg, ecart_detecte=False)
    maillon = reg.lire()[-1]
    wct = maillon[outbox_mod.CLE_WCT]

    # T1.2-f : type_travaux (CHAMPS_WCT_OPTIONNELS) s'ajoute désormais AU-DESSUS de CHAMPS_WCT,
    # toujours connu ici puisque CONTRAT_VALIDE en porte un — jamais deviné, voir test dédié
    # (test_type_travaux_absent_si_intervention_ne_le_connait_pas) pour le cas absent.
    assert set(wct.keys()) == set(outbox_mod.CHAMPS_WCT) | {"type_travaux"}
    assert wct["type_travaux"] == CONTRAT_VALIDE["type_travaux"]
    assert wct["consommateurs_cibles"] == list(outbox_mod.CONSOMMATEURS_CIBLES)
    assert wct["devis_id"] is None
    assert wct["ecart_signale"] is False
    assert wct["revue_id"] is None
    assert wct["statut"] == "completed_verified"
    assert wct["duree_reelle_minutes"] == 150
    assert wct["horodatage_completion"] == H_DEPART
    assert wct["fix_gps_completion"] == {"latitude": 45.5088, "longitude": -73.5878}
    assert wct["lead_id"] == CONTRAT_VALIDE["lead_id"]
    assert wct["technicien_id"] == "T1"

# ------------------------------------------------------------------ 4. hash_maillon non circulaire et EXACT
def test_hash_maillon_exact():
    reg, i_id = _intervention_sur_site_avec_pointages()
    accuse, _ = outbox_mod.completer_intervention(i_id, H_COMPLETION, reg, ecart_detecte=False)
    maillon = reg.lire()[-1]
    wct = maillon[outbox_mod.CLE_WCT]

    # Reconstruire la partie transition SEULE
    partie_transition = {
        k: v for k, v in maillon.items()
        if k not in (outbox_mod.CLE_WCT, "ligne_id", "precedent_ligne_id")
    }
    recalcul = encodage_mod.empreinte(partie_transition)
    assert wct["hash_maillon"] == recalcul

# ------------------------------------------------------------------ 5. wct_id dérivé
def test_wct_id_derive():
    reg, i_id = _intervention_sur_site_avec_pointages()
    accuse, _ = outbox_mod.completer_intervention(i_id, H_COMPLETION, reg, ecart_detecte=False)
    wct = reg.lire()[-1][outbox_mod.CLE_WCT]
    attendu = encodage_mod.empreinte("wct", i_id, H_COMPLETION)
    assert wct["wct_id"] == attendu


# ------------------------------------------------------------------ 5 bis. T1.1-b#1 — devis_id porté par le WCT
def test_devis_id_fourni_a_inscription_porte_tel_quel_par_le_wct():
    reg = registre_mod.Registre()
    acc, ver = etats_mod.inscrire_intervention(
        CONTRAT_VALIDE, MARQUEUR_VALIDE, reg, H1, SEL, devis_id="DEVIS-M3-42",
    )
    assert acc is not None, f"inscription refusée : {ver}"
    i_id = acc["intervention_id"]
    assign = ASSIGNATION(i_id)
    acc2, ver2 = etats_mod.transitionner(i_id, "en_route", reg, H_ARRIVEE, assignation=assign)
    assert acc2 is not None, f"transition en_route échouée : {ver2}"
    for action, horo in (("arrivee", H_ARRIVEE), ("depart", H_DEPART)):
        acc_p, ver_p = pointage_mod.enregistrer_pointage(
            i_id, "T1", action, horo, GPS_PROCHE, ATTESTATION, assign, FENETRE, REFERENTIEL, VILLE, SEL, reg,
        )
        assert acc_p is not None, f"{action} refusé : {ver_p}"

    accuse, verdict = outbox_mod.completer_intervention(i_id, H_COMPLETION, reg, ecart_detecte=False)
    assert accuse is not None, f"complétion refusée : {verdict}"
    wct = reg.lire()[-1][outbox_mod.CLE_WCT]
    assert wct["devis_id"] == "DEVIS-M3-42"


def test_devis_id_omis_reste_null_dans_le_wct():
    """Omis à l'inscription (comportement historique), le WCT porte null —
    jamais une valeur inventée, jamais le commentaire périmé « M3 n'existe pas
    en v1 »."""
    reg, i_id = _intervention_sur_site_avec_pointages()
    accuse, verdict = outbox_mod.completer_intervention(i_id, H_COMPLETION, reg, ecart_detecte=False)
    assert accuse is not None, f"complétion refusée : {verdict}"
    wct = reg.lire()[-1][outbox_mod.CLE_WCT]
    assert wct["devis_id"] is None


# ------------------------------------------------------------------ 6. transitionner refuse la complétion directe
@pytest.mark.parametrize("statut_depart", ["sur_site", "en_revue"])
@pytest.mark.parametrize("statut_cible", ["completed_pending_review", "completed_verified"])
def test_transitionner_refuse_completion(statut_depart, statut_cible):
    reg, i_id = _intervention_sur_site_avec_pointages()
    if statut_depart == "en_revue":
        # Mettre l'intervention en_revue (pointage incohérent)
        # Depuis sur_site, seul un DÉPART incohérent route en revue (une arrivée
        # exigerait en_route) — mesuré.
        accuse, verd = pointage_mod.enregistrer_pointage(
            i_id, "T1", "depart", H_ANOMALIE, GPS_LOIN, ATTESTATION,
            ASSIGNATION(i_id), FENETRE, REFERENTIEL, VILLE, SEL, reg
        )
        assert accuse is not None, f"pointage d'anomalie refusé : {verd}"
        assert etats_mod.statut_courant(reg, i_id) == "en_revue"

    taille_avant = len(reg.lire())
    acc, verdict = etats_mod.transitionner(i_id, statut_cible, reg, H_COMPLETION)
    assert acc is None
    assert verdict["code"] == "REJ-TRANSITION-ILLEGALE"
    assert "outbox" in verdict["detail"].lower()
    assert len(reg.lire()) == taille_avant

# ------------------------------------------------------------------ 7. La table reste l'autorité
def test_transitions_autorisees_contenant_completion():
    assert ("sur_site", "completed_pending_review") in etats_mod.TRANSITIONS_AUTORISEES
    assert ("sur_site", "completed_verified") in etats_mod.TRANSITIONS_AUTORISEES
    assert ("en_revue", "completed_pending_review") in etats_mod.TRANSITIONS_AUTORISEES
    assert ("en_revue", "completed_verified") in etats_mod.TRANSITIONS_AUTORISEES

# ------------------------------------------------------------------ 8. Chemin illégal (completer sans pointages)
def test_completer_illegal_planifiee():
    reg = registre_mod.Registre()
    acc, _ = etats_mod.inscrire_intervention(CONTRAT_VALIDE, MARQUEUR_VALIDE, reg, H1, SEL)
    i_id = acc["intervention_id"]
    taille_avant = len(reg.lire())
    accuse, verdict = outbox_mod.completer_intervention(i_id, H_COMPLETION, reg, ecart_detecte=False)
    assert accuse is None
    assert verdict["code"] == "REJ-TRANSITION-ILLEGALE"
    assert len(reg.lire()) == taille_avant

def test_completer_illegal_en_route():
    reg = registre_mod.Registre()
    acc, _ = etats_mod.inscrire_intervention(CONTRAT_VALIDE, MARQUEUR_VALIDE, reg, H1, SEL)
    i_id = acc["intervention_id"]
    acc_tr, ver_tr = etats_mod.transitionner(
        i_id, "en_route", reg, H_ARRIVEE,
        assignation={"intervention_id": i_id, "technicien_id": "T1"},
    )
    assert acc_tr is not None, f"transition en_route refusée : {ver_tr}"
    taille_avant = len(reg.lire())
    accuse, verdict = outbox_mod.completer_intervention(i_id, H_COMPLETION, reg, ecart_detecte=False)
    assert accuse is None
    assert verdict["code"] == "REJ-TRANSITION-ILLEGALE"
    assert len(reg.lire()) == taille_avant


# ------------------------------------------------------------------ 8 bis. ecart_detecte : contrat explicite (T1.1-b#2)
@pytest.mark.parametrize("ecart_bad", [None, 1, 0, "true", "false"])
def test_completer_ecart_detecte_non_booleen_refuse(ecart_bad):
    reg, i_id = _intervention_sur_site_avec_pointages()
    taille_avant = len(reg.lire())
    accuse, verdict = outbox_mod.completer_intervention(i_id, H_COMPLETION, reg, ecart_detecte=ecart_bad)
    assert accuse is None
    assert verdict["code"] == "REJ-CONTRAT-INVALIDE"
    assert len(reg.lire()) == taille_avant


def test_completer_ecart_detecte_obligatoire_sans_defaut():
    """T1.1-b#2 : « jamais déduit » se prouve aussi par l'ABSENCE de défaut —
    omettre ecart_detecte est une TypeError, pas un faux silencieux."""
    reg, i_id = _intervention_sur_site_avec_pointages()
    with pytest.raises(TypeError):
        outbox_mod.completer_intervention(i_id, H_COMPLETION, reg)


def test_completer_ecart_detecte_true_donne_completed_pending_review():
    reg, i_id = _intervention_sur_site_avec_pointages()
    accuse, verdict = outbox_mod.completer_intervention(i_id, H_COMPLETION, reg, ecart_detecte=True)
    assert accuse is not None, f"complétion refusée : {verdict}"
    assert accuse["statut"] == "completed_pending_review"
    assert reg.lire()[-1]["statut"] == "completed_pending_review"
    assert reg.lire()[-1][outbox_mod.CLE_WCT]["ecart_signale"] is True


def test_completer_ecart_detecte_false_donne_completed_verified():
    reg, i_id = _intervention_sur_site_avec_pointages()
    accuse, verdict = outbox_mod.completer_intervention(i_id, H_COMPLETION, reg, ecart_detecte=False)
    assert accuse is not None, f"complétion refusée : {verdict}"
    assert accuse["statut"] == "completed_verified"
    assert reg.lire()[-1]["statut"] == "completed_verified"
    assert reg.lire()[-1][outbox_mod.CLE_WCT]["ecart_signale"] is False


def test_completer_revue_id_sans_ecart_detecte_refuse():
    """Une revue_id fournie sans ecart_detecte=true est une incohérence fermée
    fail-closed : une demande d'écart métier validée EST un écart détecté."""
    reg, i_id = _intervention_sur_site_avec_pointages()
    acc_demande, ver_demande = ecarts_mod.creer_demande_ecart(
        i_id, _VERSION_PREVUE_OUTBOX, _VERSION_DECLAREE_OUTBOX, H_ANOMALIE, reg
    )
    assert acc_demande is not None, f"demande d'écart refusée : {ver_demande}"
    taille_avant = len(reg.lire())
    accuse, verdict = outbox_mod.completer_intervention(
        i_id, H_COMPLETION, reg, ecart_detecte=False, revue_id=acc_demande["demande_id"],
    )
    assert accuse is None
    assert verdict["code"] == "REJ-CONTRAT-INVALIDE"
    assert "ecart_detecte" in verdict["detail"].lower()
    assert len(reg.lire()) == taille_avant

# ------------------------------------------------------------------ 9. Durée fail-closed — registre inchangé
@pytest.mark.parametrize("scenario", [
    "aucun_pointage",
    "arrivee_seule",
    "depart_seul",
])
def test_duree_fail_closed(scenario):
    reg = registre_mod.Registre()
    acc, _ = etats_mod.inscrire_intervention(CONTRAT_VALIDE, MARQUEUR_VALIDE, reg, H1, SEL)
    i_id = acc["intervention_id"]
    etats_mod.transitionner(
        i_id, "en_route", reg, H_ARRIVEE,
        assignation={"intervention_id": i_id, "technicien_id": "T1"},
    )
    # Forcer l'état sur_site en écrivant un maillon de transition directement
    # pour que l'intervention soit éligible à la complétion si la durée était valide
    maillon_sur_site = {
        "type_entree": etats_mod.TYPE_TRANSITION,
        "intervention_id": i_id,
        "statut": "sur_site",
        "statut_precedent": "en_route",
        "horodatage": H_ARRIVEE,
    }
    reg.ajouter(maillon_sur_site)

    if scenario == "aucun_pointage":
        pass  # aucun pointage
    elif scenario == "arrivee_seule":
        # Ajouter directement un maillon de pointage arrivée (simule)
        maillon = {
            "type_entree": pointage_mod.TYPE_POINTAGE,
            "intervention_id": i_id,
            "action": "arrivee",
            "technicien_id": "T1",
            "horodatage": H_ARRIVEE,
            "latitude": GPS_PROCHE["latitude"],
            "longitude": GPS_PROCHE["longitude"],
        }
        reg.ajouter(maillon)
    elif scenario == "depart_seul":
        maillon = {
            "type_entree": pointage_mod.TYPE_POINTAGE,
            "intervention_id": i_id,
            "action": "depart",
            "technicien_id": "T1",
            "horodatage": H_DEPART,
            "latitude": GPS_PROCHE["latitude"],
            "longitude": GPS_PROCHE["longitude"],
        }
        reg.ajouter(maillon)
    taille_avant = len(reg.lire())
    accuse, verdict = outbox_mod.completer_intervention(i_id, H_COMPLETION, reg, ecart_detecte=False)
    assert accuse is None
    assert verdict["code"] == "REJ-CONTRAT-INVALIDE"
    assert "durée" in verdict["detail"].lower()
    assert len(reg.lire()) == taille_avant

# ------------------------------------------------------------------ 10. calculer_duree_reelle directement
def test_calculer_duree_reelle_nominal():
    reg, i_id = _intervention_sur_site_avec_pointages()
    minutes, code = outbox_mod.calculer_duree_reelle(reg, i_id)
    assert code is None
    assert minutes == 150
    assert isinstance(minutes, int)

def test_calculer_duree_reelle_echoue_aucun_pointage():
    reg = registre_mod.Registre()
    acc, _ = etats_mod.inscrire_intervention(CONTRAT_VALIDE, MARQUEUR_VALIDE, reg, H1, SEL)
    i_id = acc["intervention_id"]
    minutes, code = outbox_mod.calculer_duree_reelle(reg, i_id)
    assert minutes is None
    assert code == "REJ-CONTRAT-INVALIDE"

def test_calculer_duree_reelle_echoue_arrivee_seule():
    reg = registre_mod.Registre()
    acc, _ = etats_mod.inscrire_intervention(CONTRAT_VALIDE, MARQUEUR_VALIDE, reg, H1, SEL)
    i_id = acc["intervention_id"]
    etats_mod.transitionner(i_id, "sur_site", reg, H_ARRIVEE)  # bypass pour avoir sur_site
    # Ajouter maillon pointage arrivée uniquement
    reg.ajouter({
        "type_entree": pointage_mod.TYPE_POINTAGE, "intervention_id": i_id,
        "action": "arrivee", "horodatage": H_ARRIVEE, "latitude": 0, "longitude": 0,
    })
    minutes, code = outbox_mod.calculer_duree_reelle(reg, i_id)
    assert minutes is None
    assert code == "REJ-CONTRAT-INVALIDE"

def test_calculer_duree_reelle_arrivee_apres_depart():
    reg, i_id = _intervention_sur_site_avec_pointages()
    # Supprimer les pointages existants et en mettre avec depart avant arrivee
    # Pour simplifier, on crée un nouveau registre avec des pointages inversés
    reg2 = registre_mod.Registre()
    acc, _ = etats_mod.inscrire_intervention(CONTRAT_VALIDE, MARQUEUR_VALIDE, reg2, H1, SEL)
    i_id2 = acc["intervention_id"]
    etats_mod.transitionner(i_id2, "sur_site", reg2, H_ARRIVEE)
    reg2.ajouter({
        "type_entree": pointage_mod.TYPE_POINTAGE, "intervention_id": i_id2,
        "action": "depart", "horodatage": H_ARRIVEE, "latitude": 0, "longitude": 0,
    })
    reg2.ajouter({
        "type_entree": pointage_mod.TYPE_POINTAGE, "intervention_id": i_id2,
        "action": "arrivee", "horodatage": H_DEPART, "latitude": 0, "longitude": 0,
    })
    minutes, code = outbox_mod.calculer_duree_reelle(reg2, i_id2)
    assert minutes is None
    assert code == "REJ-HORODATAGE-ANTERIEUR"


# ------------------------------------------------------------------ 10 bis. T1.1-c#1 — pauses, sans effet sur le statut
def test_deux_pauses_de_15_min_reduisent_la_duree_de_30():
    """T1.1-c#1, littéral : deux pauses de 15 min réduisent la durée réelle de
    30 min. Fixture : arrivée 09:00, départ 11:30 (150 minutes brutes, la même
    fixture que les tests existants), avec deux pauses interposées."""
    reg = registre_mod.Registre()
    acc, _ = etats_mod.inscrire_intervention(CONTRAT_VALIDE, MARQUEUR_VALIDE, reg, H1, SEL)
    i_id = acc["intervention_id"]
    assign = ASSIGNATION(i_id)
    acc_route, ver_route = etats_mod.transitionner(i_id, "en_route", reg, H_ARRIVEE, assignation=assign)
    assert acc_route is not None, f"transition en_route échouée : {ver_route}"

    sequence = (
        ("arrivee", H_ARRIVEE),                               # 09:00
        ("pause_debut", "2025-06-02T09:30:00+00:00"),
        ("pause_fin", "2025-06-02T09:45:00+00:00"),           # pause 1 : 15 min
        ("pause_debut", "2025-06-02T10:30:00+00:00"),
        ("pause_fin", "2025-06-02T10:45:00+00:00"),           # pause 2 : 15 min
        ("depart", H_DEPART),                                 # 11:30
    )
    for action, horo in sequence:
        acc_p, ver_p = pointage_mod.enregistrer_pointage(
            i_id, "T1", action, horo, GPS_PROCHE, ATTESTATION, assign, FENETRE, REFERENTIEL, VILLE, SEL, reg,
        )
        assert acc_p is not None, f"{action} refusé : {ver_p}"
        assert acc_p["statut"] == "sur_site", f"{action} doit être SANS EFFET sur le statut"

    minutes_pause, code_pause = outbox_mod.calculer_minutes_pause(reg, i_id)
    assert code_pause is None
    assert minutes_pause == 30

    duree, code = outbox_mod.calculer_duree_reelle(reg, i_id)
    assert code is None
    assert duree == 120, "150 minutes brutes (09:00 -> 11:30) moins 30 de pause"

    # La complétion elle-même porte la durée NETTE.
    accuse, verdict = outbox_mod.completer_intervention(i_id, H_COMPLETION, reg, ecart_detecte=False)
    assert accuse is not None, f"complétion refusée : {verdict}"
    assert accuse["duree_reelle_minutes"] == 120


def test_aucune_pause_duree_inchangee():
    """Aucune pause : la durée réelle reste celle déjà prouvée par les tests
    existants (150 minutes) — non-régression."""
    reg, i_id = _intervention_sur_site_avec_pointages()
    minutes_pause, code_pause = outbox_mod.calculer_minutes_pause(reg, i_id)
    assert code_pause is None
    assert minutes_pause == 0
    duree, code = outbox_mod.calculer_duree_reelle(reg, i_id)
    assert code is None
    assert duree == 150


def test_pause_debut_sans_fin_fail_closed():
    reg = registre_mod.Registre()
    acc, _ = etats_mod.inscrire_intervention(CONTRAT_VALIDE, MARQUEUR_VALIDE, reg, H1, SEL)
    i_id = acc["intervention_id"]
    assign = ASSIGNATION(i_id)
    etats_mod.transitionner(i_id, "en_route", reg, H_ARRIVEE, assignation=assign)
    for action, horo in (("arrivee", H_ARRIVEE), ("pause_debut", "2025-06-02T09:30:00+00:00")):
        acc_p, ver_p = pointage_mod.enregistrer_pointage(
            i_id, "T1", action, horo, GPS_PROCHE, ATTESTATION, assign, FENETRE, REFERENTIEL, VILLE, SEL, reg,
        )
        assert acc_p is not None, f"{action} refusé : {ver_p}"
    minutes, code = outbox_mod.calculer_minutes_pause(reg, i_id)
    assert minutes is None
    assert code == "REJ-CONTRAT-INVALIDE"


def test_pause_fin_sans_debut_fail_closed():
    reg = registre_mod.Registre()
    acc, _ = etats_mod.inscrire_intervention(CONTRAT_VALIDE, MARQUEUR_VALIDE, reg, H1, SEL)
    i_id = acc["intervention_id"]
    assign = ASSIGNATION(i_id)
    etats_mod.transitionner(i_id, "en_route", reg, H_ARRIVEE, assignation=assign)
    for action, horo in (("arrivee", H_ARRIVEE), ("pause_fin", "2025-06-02T09:30:00+00:00")):
        acc_p, ver_p = pointage_mod.enregistrer_pointage(
            i_id, "T1", action, horo, GPS_PROCHE, ATTESTATION, assign, FENETRE, REFERENTIEL, VILLE, SEL, reg,
        )
        assert acc_p is not None, f"{action} refusé : {ver_p}"
    minutes, code = outbox_mod.calculer_minutes_pause(reg, i_id)
    assert minutes is None
    assert code == "REJ-CONTRAT-INVALIDE"


def test_pause_sans_fermeture_bloque_la_completion():
    """Une pause ouverte sans pause_fin bloque fail-closed la complétion —
    jamais une durée inventée."""
    reg = registre_mod.Registre()
    acc, _ = etats_mod.inscrire_intervention(CONTRAT_VALIDE, MARQUEUR_VALIDE, reg, H1, SEL)
    i_id = acc["intervention_id"]
    assign = ASSIGNATION(i_id)
    etats_mod.transitionner(i_id, "en_route", reg, H_ARRIVEE, assignation=assign)
    for action, horo in (
        ("arrivee", H_ARRIVEE),
        ("pause_debut", "2025-06-02T09:30:00+00:00"),
        ("depart", H_DEPART),
    ):
        acc_p, ver_p = pointage_mod.enregistrer_pointage(
            i_id, "T1", action, horo, GPS_PROCHE, ATTESTATION, assign, FENETRE, REFERENTIEL, VILLE, SEL, reg,
        )
        assert acc_p is not None, f"{action} refusé : {ver_p}"
    taille_avant = len(reg.lire())
    accuse, verdict = outbox_mod.completer_intervention(i_id, H_COMPLETION, reg, ecart_detecte=False)
    assert accuse is None
    assert verdict["code"] == "REJ-CONTRAT-INVALIDE"
    assert len(reg.lire()) == taille_avant


# ------------------------------------------------------------------ 10 ter. T1.1-c#2 — temps de déplacement
def test_calculer_minutes_deplacement_nul_sur_fixture_existante():
    """Sur la fixture existante (transition en_route et arrivée au MÊME
    horodatage), le déplacement est nul : déplacement + travail == la durée
    DÉJÀ PROUVÉE par les tests existants (150 minutes, T1.1-c#2)."""
    reg, i_id = _intervention_sur_site_avec_pointages()
    minutes_deplacement, code = outbox_mod.calculer_minutes_deplacement(reg, i_id)
    assert code is None
    assert minutes_deplacement == 0
    duree_travail, code2 = outbox_mod.calculer_duree_reelle(reg, i_id)
    assert code2 is None
    assert duree_travail == 150
    assert minutes_deplacement + duree_travail == 150


def test_calculer_minutes_deplacement_nominal_distinct_du_travail():
    reg = registre_mod.Registre()
    acc, _ = etats_mod.inscrire_intervention(CONTRAT_VALIDE, MARQUEUR_VALIDE, reg, H1, SEL)
    i_id = acc["intervention_id"]
    assign = ASSIGNATION(i_id)
    h_route = "2025-06-02T08:00:00+00:00"
    h_arr = "2025-06-02T08:25:00+00:00"    # 25 minutes de trajet
    h_dep = "2025-06-02T11:00:00+00:00"
    acc_route, ver_route = etats_mod.transitionner(i_id, "en_route", reg, h_route, assignation=assign)
    assert acc_route is not None, f"transition en_route échouée : {ver_route}"
    for action, horo in (("arrivee", h_arr), ("depart", h_dep)):
        acc_p, ver_p = pointage_mod.enregistrer_pointage(
            i_id, "T1", action, horo, GPS_PROCHE, ATTESTATION, assign, FENETRE, REFERENTIEL, VILLE, SEL, reg,
        )
        assert acc_p is not None, f"{action} refusé : {ver_p}"

    minutes_deplacement, code = outbox_mod.calculer_minutes_deplacement(reg, i_id)
    assert code is None
    assert minutes_deplacement == 25

    duree_travail, code2 = outbox_mod.calculer_duree_reelle(reg, i_id)
    assert code2 is None
    assert duree_travail == 155  # 08:25 -> 11:00
    assert minutes_deplacement != duree_travail, "déplacement et travail restent deux nombres distincts"


def test_calculer_minutes_deplacement_sans_transition_en_route_fail_closed():
    reg = registre_mod.Registre()
    acc, _ = etats_mod.inscrire_intervention(CONTRAT_VALIDE, MARQUEUR_VALIDE, reg, H1, SEL)
    i_id = acc["intervention_id"]
    minutes, code = outbox_mod.calculer_minutes_deplacement(reg, i_id)
    assert minutes is None
    assert code == "REJ-CONTRAT-INVALIDE"


def test_calculer_minutes_deplacement_sans_arrivee_fail_closed():
    reg = registre_mod.Registre()
    acc, _ = etats_mod.inscrire_intervention(CONTRAT_VALIDE, MARQUEUR_VALIDE, reg, H1, SEL)
    i_id = acc["intervention_id"]
    assign = ASSIGNATION(i_id)
    etats_mod.transitionner(i_id, "en_route", reg, H_ARRIVEE, assignation=assign)
    minutes, code = outbox_mod.calculer_minutes_deplacement(reg, i_id)
    assert minutes is None
    assert code == "REJ-CONTRAT-INVALIDE"


def test_calculer_minutes_deplacement_arrivee_avant_en_route_fail_closed():
    reg = registre_mod.Registre()
    acc, _ = etats_mod.inscrire_intervention(CONTRAT_VALIDE, MARQUEUR_VALIDE, reg, H1, SEL)
    i_id = acc["intervention_id"]
    reg.ajouter({
        "type_entree": etats_mod.TYPE_TRANSITION, "intervention_id": i_id,
        "statut": "en_route", "statut_precedent": "planifiee", "horodatage": H_DEPART,
        "technicien_id": "T1",
    })
    reg.ajouter({
        "type_entree": pointage_mod.TYPE_POINTAGE, "intervention_id": i_id,
        "action": "arrivee", "horodatage": H_ARRIVEE, "latitude": 0, "longitude": 0,
    })
    minutes, code = outbox_mod.calculer_minutes_deplacement(reg, i_id)
    assert minutes is None
    assert code == "REJ-HORODATAGE-ANTERIEUR"

# ------------------------------------------------------------------ 11. CA-M4-13 — wct sans données sensibles
def test_wct_sans_donnees_sensibles():
    reg, i_id = _intervention_sur_site_avec_pointages()
    accuse, _ = outbox_mod.completer_intervention(i_id, H_COMPLETION, reg, ecart_detecte=False)
    wct = reg.lire()[-1][outbox_mod.CLE_WCT]
    wct_str = str(wct)
    # Pas de ville en clair
    assert VILLE not in wct_str
    for cle in ("adresse", "rue", "code_postal"):
        assert cle not in wct
    # lead_id en clair
    assert wct["lead_id"] == CONTRAT_VALIDE["lead_id"]

# ------------------------------------------------------------------ 12. verifier_invariants_outbox
def test_verifier_invariants_sain():
    reg, i_id = _intervention_sur_site_avec_pointages()
    outbox_mod.completer_intervention(i_id, H_COMPLETION, reg, ecart_detecte=False)
    ok, msg = outbox_mod.verifier_invariants_outbox(reg)
    assert ok
    assert msg == ""

@pytest.mark.parametrize("falsification", [
    "retirer_wct",
    "greffer_wct_sur_pointage",
    "alterer_hash",
])
def test_verifier_invariants_falsifies(falsification):
    reg, i_id = _intervention_sur_site_avec_pointages()
    outbox_mod.completer_intervention(i_id, H_COMPLETION, reg, ecart_detecte=False)
    chain = reg._chain
    if falsification == "retirer_wct":
        # supprimer la clé wct du dernier maillon (terminee)
        del chain[-1][outbox_mod.CLE_WCT]
    elif falsification == "greffer_wct_sur_pointage":
        # ajouter une clé wct bidon sur un maillon de pointage
        for m in chain:
            if m.get("type_entree") == pointage_mod.TYPE_POINTAGE:
                m[outbox_mod.CLE_WCT] = chain[-1].get(outbox_mod.CLE_WCT, {"faux": True})
                break
    elif falsification == "alterer_hash":
        # modifier le hash_maillon dans le wct
        wct = chain[-1][outbox_mod.CLE_WCT]
        wct["hash_maillon"] = "0000...0000"
    ok, msg = outbox_mod.verifier_invariants_outbox(reg)
    assert not ok
    assert msg != ""

# ------------------------------------------------------------------ 13. garde_ecriture_unique
def test_garde_ecriture_unique_reel():
    ok, msg = outbox_mod.garde_ecriture_unique()
    assert ok
    assert msg == ""

def test_garde_ecriture_unique_violation_ajouter(tmp_path):
    # Créer un faux module avec un appel à ajouter avec dict contenant CLE_WCT
    fake_module = tmp_path / "fake.py"
    # La garde AST inspecte les LITTÉRAUX : un violateur réaliste écrit la clé
    # "wct" en clair. La forme indirecte (outbox.CLE_WCT) lui échapperait,
    # limitation DÉCLARÉE dans sa docstring — le refus au runtime dans
    # transitionner en est la défense en profondeur.
    fake_module.write_text(
        'def violer(registre):\n    registre.ajouter({"wct": {}, "type_entree": "transition_statut"})\n',
        encoding="utf-8",
    )
    # Modifier temporairement le chemin pour qu'il contienne tmp_path ?
    # L'implémentation de garde_ecriture_unique doit scanner le dossier source, pas tmp_path.
    # On va créer un dossier temporaire et y placer des modules, puis appeler la fonction en lui passant le chemin.
    ok, msg = outbox_mod.garde_ecriture_unique(chemin_source=str(tmp_path))
    assert not ok
    assert msg != ""

@pytest.mark.parametrize("statut_vise", ["completed_pending_review", "completed_verified"])
def test_garde_ecriture_unique_violation_transitionner_completion(tmp_path, statut_vise):
    fake_module2 = tmp_path / "fake2.py"
    fake_module2.write_text(f"""
def violer():
    etats.transitionner(x, "{statut_vise}", r, h)
""")
    ok, msg = outbox_mod.garde_ecriture_unique(chemin_source=str(tmp_path))
    assert not ok
    assert msg != ""

@pytest.mark.parametrize("statut_vise", ["completed_pending_review", "completed_verified"])
def test_garde_ecriture_unique_violation_transitionner_completion_forme_mot_cle(tmp_path, statut_vise):
    """BUG CORRIGÉ : la forme mot-clé échappait à la garde.

    ``kw.value`` est le nœud ``ast.Constant`` lui-même : comparé DIRECTEMENT à
    la chaîne visée, il n'est JAMAIS égal (objet AST vs str), donc la
    condition ne se déclenchait jamais — seule ``kw.value.value`` porte la
    constante Python réelle. Avant correction, ce fichier passait la garde
    alors qu'il appelle bien ``transitionner(..., statut_cible=...)``.
    """
    fake_module3 = tmp_path / "fake3.py"
    fake_module3.write_text(f"""
def violer():
    etats.transitionner(x, r, h, statut_cible="{statut_vise}")
""")
    ok, msg = outbox_mod.garde_ecriture_unique(chemin_source=str(tmp_path))
    assert not ok, f"la forme mot-clé statut_cible=\"{statut_vise}\" doit être détectée"
    assert statut_vise in msg.lower()

# ------------------------------------------------------------------ 14. lire_outbox
def test_lire_outbox_un_element():
    reg, i_id = _intervention_sur_site_avec_pointages()
    outbox_mod.completer_intervention(i_id, H_COMPLETION, reg, ecart_detecte=False)
    resultat = outbox_mod.lire_outbox(reg)
    assert len(resultat) == 1
    index, wct = resultat[0]
    assert isinstance(index, int)
    assert wct["intervention_id"] == i_id

def test_lire_outbox_depuis_index():
    reg, i_id = _intervention_sur_site_avec_pointages()
    outbox_mod.completer_intervention(i_id, H_COMPLETION, reg, ecart_detecte=False)
    # Créer une deuxième intervention complétée pour avoir un index plus loin
    reg2, i_id2 = _intervention_sur_site_avec_pointages()
    # Copier les maillons dans reg (artificiel mais suffisant)
    for m in reg2.lire()[1:]:  # skip le premier (marqueur)
        reg.ajouter(m)
    outbox_mod.completer_intervention(i_id2, H_COMPLETION, reg, ecart_detecte=False)

    tout = outbox_mod.lire_outbox(reg)
    assert len(tout) == 2
    # Filtrer avec depuis_index = premier_index_du_deuxième
    premier_index = tout[0][0]
    resultat = outbox_mod.lire_outbox(reg, depuis_index=premier_index)
    assert len(resultat) == 2  # les deux sont >=
    resultat2 = outbox_mod.lire_outbox(reg, depuis_index=premier_index+1)
    assert len(resultat2) == 1

def test_lire_outbox_index_negatif():
    reg, _ = _intervention_sur_site_avec_pointages()
    with pytest.raises(ValueError, match="depuis_index négatif"):
        outbox_mod.lire_outbox(reg, depuis_index=-1)

def test_lire_outbox_copie_profonde():
    reg, i_id = _intervention_sur_site_avec_pointages()
    outbox_mod.completer_intervention(i_id, H_COMPLETION, reg, ecart_detecte=False)
    resultat = outbox_mod.lire_outbox(reg)
    wct_original = reg.lire()[-1][outbox_mod.CLE_WCT]
    wct_resultat = resultat[0][1]
    # Modifier la copie ne doit pas altérer le registre
    wct_resultat["intervention_id"] = "bidon"
    assert reg.lire()[-1][outbox_mod.CLE_WCT]["intervention_id"] == i_id

# ------------------------------------------------------------------ 15. Consommateur idempotent (CA-M4-11 preuve 3)
def test_consommateur_idempotent():
    reg, i_id1 = _intervention_sur_site_avec_pointages()
    outbox_mod.completer_intervention(i_id1, H_COMPLETION, reg, ecart_detecte=False)

    # Deuxième intervention, RÉELLEMENT distincte (autre lead_id)
    i_id2 = _ajouter_intervention_sur_site(reg, "L2", H1)
    acc2, ver2 = outbox_mod.completer_intervention(i_id2, H_COMPLETION, reg, ecart_detecte=False)
    assert acc2 is not None, f"complétion 2 refusée : {ver2}"

    cons = outbox_mod.ConsommateurReference()
    nb1 = cons.consommer(reg)
    assert nb1 == 2
    assert len(cons.effets) == 2

    nb2 = cons.consommer(reg)
    assert nb2 == 0
    assert len(cons.effets) == 2

    nb3 = cons.consommer(reg, depuis_index=0)  # resoumission totale
    assert nb3 == 0
    assert len(cons.effets) == 2

    assert cons.wct_vus == {e["wct_id"] for e in cons.effets}

    # Troisième intervention, consommation incrémentale
    i_id3 = _ajouter_intervention_sur_site(reg, "L3", H1)
    acc3, ver3 = outbox_mod.completer_intervention(i_id3, H_COMPLETION, reg, ecart_detecte=False)
    assert acc3 is not None, f"complétion 3 refusée : {ver3}"

    nb4 = cons.consommer(reg)
    assert nb4 == 1
    assert len(cons.effets) == 3

# ------------------------------------------------------------------ 16. Écart validé -> complétion avec WCT
_VERSION_PREVUE_OUTBOX = {"duree_minutes": 120, "perimetre": "salle de bain", "materiaux": ["carrelage"]}
_VERSION_DECLAREE_OUTBOX = {
    "duree_minutes": 180, "perimetre": "salle de bain et couloir",
    "materiaux": ["carrelage", "plinthes"],
}

def test_ecart_valide_produit_wct():
    """Un écart MÉTIER (versions prévue/déclarée divergentes) validé complète
    l'intervention avec un WCT. Distinct d'une anomalie de POINTAGE (GPS
    incohérent) : celle-ci, validée, reprend seulement sur_site — voir
    test_ecart_metier_vs_anomalie_pointage_resolution_validee_diverge."""
    reg, i_id = _intervention_sur_site_avec_pointages()
    acc_demande, ver_demande = ecarts_mod.creer_demande_ecart(
        i_id, _VERSION_PREVUE_OUTBOX, _VERSION_DECLAREE_OUTBOX, H_ANOMALIE, reg
    )
    assert acc_demande is not None, f"demande d'écart refusée : {ver_demande}"
    demande_id = acc_demande["demande_id"]

    # Résoudre validee -> doit créer la transition de complétion (avec wct).
    # Un écart métier validé EST un écart détecté (ecarts.py fixe
    # ecart_detecte=True) : l'issue est donc completed_pending_review, jamais
    # completed_verified (T1.1-b#2).
    acc, ver = ecarts_mod.resoudre_demande(demande_id, "validee", H_COMPLETION, reg)
    assert acc is not None, f"resoudre_demande échec: {ver}"
    # Le composite n'est PAS le dernier maillon : l'entrée de résolution est
    # écrite après lui. On le localise par sa clé wct.
    composites = [m for m in reg.lire() if outbox_mod.CLE_WCT in m]
    assert len(composites) == 1
    dernier = composites[0]
    assert dernier["type_entree"] == etats_mod.TYPE_TRANSITION
    assert dernier["statut"] == "completed_pending_review"
    wct = dernier[outbox_mod.CLE_WCT]
    assert wct["ecart_signale"] is True
    assert wct["revue_id"] == demande_id
    assert wct["statut"] == "completed_pending_review"
    ok, _ = outbox_mod.verifier_invariants_outbox(reg)
    assert ok

# ------------------------------------------------------------------ 17. Écart rejeté -> annulation SANS WCT
def test_ecart_rejete_pas_de_wct():
    reg, i_id = _intervention_sur_site_avec_pointages()
    acc_demande, ver_demande = ecarts_mod.creer_demande_ecart(
        i_id, _VERSION_PREVUE_OUTBOX, _VERSION_DECLAREE_OUTBOX, H_ANOMALIE, reg
    )
    assert acc_demande is not None, f"demande d'écart refusée : {ver_demande}"
    demande_id = acc_demande["demande_id"]

    acc, _ = ecarts_mod.resoudre_demande(demande_id, "rejetee", H_COMPLETION, reg)
    assert acc is not None
    assert etats_mod.statut_courant(reg, i_id) == "annulee"
    assert outbox_mod.lire_outbox(reg) == []
    for m in reg.lire():
        assert outbox_mod.CLE_WCT not in m

# ---------------------------------------- 17 bis. écart métier vs anomalie pointage : résolutions distinctes
def test_ecart_metier_vs_anomalie_pointage_resolution_validee_diverge():
    """BUG CORRIGÉ (ecarts.py) : resoudre_demande('validee', ...) tentait
    TOUJOURS outbox.completer_intervention, quel que soit le type de la
    demande. Pour une anomalie_pointage, cela échouait fail-closed (« durée
    réelle indéterminable » : une arrivée en anomalie n'a par construction pas
    de départ), et en_revue -> sur_site (PRD §4, amendement #145) restait
    inatteignable par ce chemin. Un écart_metier validé, lui, produit
    toujours un WCT (composite terminee) — les deux résolutions divergent."""
    reg, i_id = _intervention_sur_site_avec_pointages()
    # Anomalie de pointage : départ incohérent (GPS_LOIN).
    acc_anomalie, verd_anomalie = pointage_mod.enregistrer_pointage(
        i_id, "T1", "depart", H_ANOMALIE, GPS_LOIN, ATTESTATION,
        ASSIGNATION(i_id), FENETRE, REFERENTIEL, VILLE, SEL, reg
    )
    assert acc_anomalie is not None, f"pointage d'anomalie refusé : {verd_anomalie}"
    demande_anomalie = next(
        m for m in reg.lire() if m.get("type_entree") == pointage_mod.TYPE_DEMANDE_REVUE
    )
    assert demande_anomalie["type_demande"] == pointage_mod.TYPE_REVUE_ANOMALIE
    demande_id = demande_anomalie["demande_id"]

    acc_res, ver_res = ecarts_mod.resoudre_demande(demande_id, "validee", H_COMPLETION, reg)
    assert acc_res is not None, f"reprise après arbitrage refusée : {ver_res}"
    assert etats_mod.statut_courant(reg, i_id) == "sur_site", (
        "une anomalie_pointage validée REPREND sur_site (PRD §4), elle ne complète jamais"
    )
    assert outbox_mod.lire_outbox(reg) == [], "aucun WCT pour une simple reprise de pointage"
    for m in reg.lire():
        assert outbox_mod.CLE_WCT not in m

# ------------------------------------------------------------------ 18. revue_id inconnu
def test_completer_revue_id_inconnu():
    reg, i_id = _intervention_sur_site_avec_pointages()
    taille_avant = len(reg.lire())
    accuse, verdict = outbox_mod.completer_intervention(
        i_id, H_COMPLETION, reg, ecart_detecte=True, revue_id="inconnu",
    )
    assert accuse is None
    assert verdict["code"] == "REJ-CONTRAT-INVALIDE"
    assert "revue" in verdict["detail"].lower()
    assert len(reg.lire()) == taille_avant

# ------------------------------------------------------------------ 19. Chaîne intacte après parcours complet
def test_chaine_intacte_apres_completion():
    reg, i_id = _intervention_sur_site_avec_pointages()
    outbox_mod.completer_intervention(i_id, H_COMPLETION, reg, ecart_detecte=False)
    assert reg.valider_chaine() is True
    reg.assert_chaine()  # ne doit pas lever

def test_duree_du_premier_arrivee_au_dernier_depart():
    """DISCRIMINANT de la règle de durée : deux départs, dont un incohérent qui a
    ouvert une revue. La durée doit courir jusqu'au DERNIER départ — prendre le
    premier donnerait 150 minutes au lieu de 160 (mutation mesurée non détectée
    tant qu'un seul départ existait).

    Ce cas n'est pas théorique : c'est exactement ce que produit le chemin de
    revue, et c'est pourquoi la règle « exactement une paire » a été écartée —
    elle rendait toute intervention arbitrée impossible à compléter.
    """
    reg, i_id = _intervention_sur_site_avec_pointages()   # arrivée 09:00, départ 11:30
    acc_anom, verd_anom = pointage_mod.enregistrer_pointage(
        i_id, "T1", "depart", H_ANOMALIE, GPS_LOIN, ATTESTATION,
        ASSIGNATION(i_id), FENETRE, REFERENTIEL, VILLE, SEL, reg,
    )
    assert acc_anom is not None, f"second départ refusé : {verd_anom}"
    assert etats_mod.statut_courant(reg, i_id) == "en_revue"

    duree, code = outbox_mod.calculer_duree_reelle(reg, i_id)
    assert code is None, f"durée refusée à tort : {code}"
    # 09:00 -> 11:40 = 160 minutes (et non 150, qui serait le PREMIER départ)
    assert duree == 160, f"attendu 160 (premier arrivée -> dernier départ), obtenu {duree}"

    # et la complétion qui en découle porte bien cette durée
    acc, verd = outbox_mod.completer_intervention(i_id, H_APRES_ANOMALIE, reg, ecart_detecte=False)
    assert acc is not None, f"complétion refusée : {verd}"
    assert acc["duree_reelle_minutes"] == 160

# ------------------------------------------------------------------ 15. confirmer_verification (PLAN T1.2, point 4)
def _intervention_en_pending_review():
    reg, i_id = _intervention_sur_site_avec_pointages()
    acc, verd = outbox_mod.completer_intervention(i_id, H_COMPLETION, reg, ecart_detecte=True)
    assert acc is not None, f"complétion refusée : {verd}"
    assert acc["statut"] == "completed_pending_review"
    return reg, i_id


def test_confirmer_verification_nominal_passe_a_completed_verified():
    reg, i_id = _intervention_en_pending_review()
    acc, verd = outbox_mod.confirmer_verification(
        i_id, H_COMPLETION, reg, evenement_id_variance="m6-variance-abc",
    )
    assert acc is not None, f"confirmation refusée : {verd}"
    assert acc["statut"] == "completed_verified"
    assert acc["deja_verifie"] is False
    assert acc["evenement_id_variance"] == "m6-variance-abc"
    assert etats_mod.statut_courant(reg, i_id) == "completed_verified"


def test_confirmer_verification_ne_porte_jamais_de_wct():
    """Le WCT vit déjà sur le premier maillon (complétion) : la confirmation n'en écrit
    jamais un second (garde_ecriture_unique le vérifie statiquement)."""
    reg, i_id = _intervention_en_pending_review()
    outbox_mod.confirmer_verification(i_id, H_COMPLETION, reg, evenement_id_variance="m6-variance-abc")
    maillon_confirmation = reg.lire()[-1]
    assert outbox_mod.CLE_WCT not in maillon_confirmation
    assert maillon_confirmation["statut"] == "completed_verified"
    assert maillon_confirmation["statut_precedent"] == "completed_pending_review"


def test_confirmer_verification_idempotente_redelivrance_ne_change_rien():
    reg, i_id = _intervention_en_pending_review()
    acc1, _ = outbox_mod.confirmer_verification(i_id, H_COMPLETION, reg, evenement_id_variance="m6-variance-abc")
    taille_apres_premiere = reg.taille()
    tete_apres_premiere = reg.tete()

    acc2, verd2 = outbox_mod.confirmer_verification(
        i_id, H_COMPLETION, reg, evenement_id_variance="m6-variance-abc-second-envoi",
    )
    assert verd2 is None, f"une redélivrance ne doit jamais être un refus : {verd2}"
    assert acc2["deja_verifie"] is True
    assert acc2["statut"] == "completed_verified"
    assert reg.taille() == taille_apres_premiere, "une redélivrance n'écrit rien de plus"
    assert reg.tete() == tete_apres_premiere
    assert acc1["statut"] == acc2["statut"]


def test_confirmer_verification_refuse_hors_pending_review():
    reg, i_id = _intervention_sur_site_avec_pointages()   # encore sur_site, jamais complétée
    acc, verd = outbox_mod.confirmer_verification(i_id, H_COMPLETION, reg, evenement_id_variance="m6-variance-x")
    assert acc is None
    assert verd["code"] == "REJ-TRANSITION-ILLEGALE"
    assert etats_mod.statut_courant(reg, i_id) == "sur_site"


def test_confirmer_verification_evenement_id_variance_requis():
    reg, i_id = _intervention_en_pending_review()
    with pytest.raises(TypeError):
        outbox_mod.confirmer_verification(i_id, H_COMPLETION, reg)  # mot-clé obligatoire, aucun défaut


def test_verifier_invariants_outbox_sain_apres_confirmation():
    reg, i_id = _intervention_en_pending_review()
    outbox_mod.confirmer_verification(i_id, H_COMPLETION, reg, evenement_id_variance="m6-variance-abc")
    ok, msg = outbox_mod.verifier_invariants_outbox(reg)
    assert ok, msg


def test_garde_ecriture_unique_reel_couvre_confirmer_verification():
    """La garde réelle (aucun chemin_source fourni) reste verte MAINTENANT que
    confirmer_verification écrit, elle aussi, un maillon `statut=completed_verified`."""
    ok, msg = outbox_mod.garde_ecriture_unique()
    assert ok, msg


def test_garde_ecriture_unique_violation_statut_hors_fonctions_autorisees(tmp_path):
    """Un TROISIÈME chemin d'écriture (hors completer_intervention/confirmer_verification)
    qui pose directement `statut="completed_verified"` doit être détecté."""
    fake = tmp_path / "fake4.py"
    fake.write_text(
        'def autre_fonction(registre):\n'
        '    registre.ajouter({"type_entree": "transition_statut", "statut": "completed_verified"})\n',
        encoding="utf-8",
    )
    ok, msg = outbox_mod.garde_ecriture_unique(chemin_source=str(tmp_path))
    assert not ok
    assert "completed_verified" in msg


# ==================================================================================
# 14. T1.2-f — CHAMPS_WCT_OPTIONNELS : type_travaux (tiré de l'inscription) et les quatre
# faits CLIENT (photos, description_factuelle, consentement_marketing, client_satisfait).
# La forme (types) est vérifiée ICI, dans outbox.py (module pur) ; la garde d'appel
# d'appareil (Loi 25) appartient à outils.py — voir test_evenements_m4.py.
# ==================================================================================
def test_type_travaux_absent_si_intervention_ne_le_connait_pas():
    """Compat : un maillon d'inscription SANS type_travaux (antérieur à T1.2-f, ou tout
    autre chemin d'entrée qui ne le porte pas) laisse le WCT SANS ce champ — jamais une
    valeur devinée, exactement ce que le catalogue permet (champ optionnel)."""
    reg = registre_mod.Registre()
    i_id = encodage_mod.empreinte("intervention", "L-SANS-TYPE", H1)
    reg.ajouter({
        "type_entree": etats_mod.TYPE_INSCRIPTION, "intervention_id": i_id, "lead_id": "L-SANS-TYPE",
        "devis_id": None, "statut": "planifiee", "horodatage": H1,
    })
    assign = {"intervention_id": i_id, "technicien_id": "T1"}
    acc2, ver2 = etats_mod.transitionner(i_id, "en_route", reg, H_ARRIVEE, assignation=assign)
    assert acc2 is not None, f"transition en_route échouée : {ver2}"
    for action, horo in (("arrivee", H_ARRIVEE), ("depart", H_DEPART)):
        acc_p, ver_p = pointage_mod.enregistrer_pointage(
            i_id, "T1", action, horo, GPS_PROCHE, ATTESTATION, assign, FENETRE, REFERENTIEL, VILLE, SEL, reg,
        )
        assert acc_p is not None, f"{action} refusé : {ver_p}"

    accuse, verdict = outbox_mod.completer_intervention(i_id, H_COMPLETION, reg, ecart_detecte=False)
    assert accuse is not None, f"complétion refusée : {verdict}"
    wct = reg.lire()[-1][outbox_mod.CLE_WCT]
    assert "type_travaux" not in wct
    assert set(wct.keys()) == set(outbox_mod.CHAMPS_WCT)
    ok, msg = outbox_mod.verifier_invariants_outbox(reg)
    assert ok, msg


def test_ville_jamais_dans_le_wct_meme_avec_les_champs_optionnels():
    """Loi 25 : ``ville`` n'appartient PAS à CHAMPS_WCT_OPTIONNELS — même en fournissant les
    quatre champs client, le WCT ne porte jamais la ville en clair (test_wct_sans_donnees_
    sensibles le prouve déjà pour le cas nu ; ceci le reconfirme avec les champs T1.2-f)."""
    assert "ville" not in outbox_mod.CHAMPS_WCT_OPTIONNELS
    reg, i_id = _intervention_sur_site_avec_pointages()
    accuse, verdict = outbox_mod.completer_intervention(
        i_id, H_COMPLETION, reg, ecart_detecte=False,
        photos=["photo-1.jpg"], description_factuelle="Gouttières posées.",
        consentement_marketing=True, client_satisfait=True,
    )
    assert accuse is not None, f"complétion refusée : {verdict}"
    wct = reg.lire()[-1][outbox_mod.CLE_WCT]
    assert "ville" not in wct
    assert VILLE not in str(wct)


@pytest.mark.parametrize("champ,mauvaise_valeur", [
    ("consentement_marketing", "true"),
    ("consentement_marketing", 1),
    ("client_satisfait", "oui"),
    ("client_satisfait", 1),
    ("photos", "photo.jpg"),
    ("photos", [1, 2]),
    ("description_factuelle", 123),
])
def test_completer_champs_optionnels_mal_types_refuse_rien_ecrit(champ, mauvaise_valeur):
    reg, i_id = _intervention_sur_site_avec_pointages()
    taille_avant = len(reg.lire())
    accuse, verdict = outbox_mod.completer_intervention(
        i_id, H_COMPLETION, reg, ecart_detecte=False, **{champ: mauvaise_valeur},
    )
    assert accuse is None
    assert verdict["code"] == "REJ-CONTRAT-INVALIDE"
    assert len(reg.lire()) == taille_avant


def test_completer_champs_optionnels_fournis_valides_portes_par_le_wct():
    reg, i_id = _intervention_sur_site_avec_pointages()
    accuse, verdict = outbox_mod.completer_intervention(
        i_id, H_COMPLETION, reg, ecart_detecte=False,
        photos=["chantier-apres-1.jpg", "chantier-apres-2.jpg"],
        description_factuelle="Installation de gouttières en aluminium 5po.",
        consentement_marketing=True, client_satisfait=True,
    )
    assert accuse is not None, f"complétion refusée : {verdict}"
    wct = reg.lire()[-1][outbox_mod.CLE_WCT]
    assert wct["photos"] == ["chantier-apres-1.jpg", "chantier-apres-2.jpg"]
    assert wct["description_factuelle"] == "Installation de gouttières en aluminium 5po."
    assert wct["consentement_marketing"] is True
    assert wct["client_satisfait"] is True
    assert set(wct.keys()) == set(outbox_mod.CHAMPS_WCT) | {
        "type_travaux", "photos", "description_factuelle", "consentement_marketing", "client_satisfait",
    }
    ok, msg = outbox_mod.verifier_invariants_outbox(reg)
    assert ok, msg


def test_completer_client_satisfait_null_explicite_distinct_d_absent():
    """catalogue : client_satisfait est ``[boolean, null]`` — null (« demandé mais non
    recueilli ») DOIT rester distinct d'une simple absence de clé (« jamais demandé »)."""
    reg, i_id = _intervention_sur_site_avec_pointages()
    accuse, verdict = outbox_mod.completer_intervention(
        i_id, H_COMPLETION, reg, ecart_detecte=False, client_satisfait=None,
    )
    assert accuse is not None, f"complétion refusée : {verdict}"
    wct = reg.lire()[-1][outbox_mod.CLE_WCT]
    assert "client_satisfait" in wct
    assert wct["client_satisfait"] is None


def test_completer_sans_champs_optionnels_wct_nu_inchange():
    """Non-régression : un appel qui ne fournit AUCUN des quatre champs client (comme avant
    T1.2-f) laisse le WCT exactement à CHAMPS_WCT plus type_travaux — jamais une clé fantôme."""
    reg, i_id = _intervention_sur_site_avec_pointages()
    accuse, verdict = outbox_mod.completer_intervention(i_id, H_COMPLETION, reg, ecart_detecte=False)
    assert accuse is not None, f"complétion refusée : {verdict}"
    wct = reg.lire()[-1][outbox_mod.CLE_WCT]
    for champ in ("photos", "description_factuelle", "consentement_marketing", "client_satisfait"):
        assert champ not in wct


def test_verifier_invariants_rejette_cle_optionnelle_inconnue():
    """Défense en profondeur : une clé qui n'appartient ni à CHAMPS_WCT ni à
    CHAMPS_WCT_OPTIONNELS reste un wct incohérent, même après T1.2-f."""
    reg, i_id = _intervention_sur_site_avec_pointages()
    outbox_mod.completer_intervention(i_id, H_COMPLETION, reg, ecart_detecte=False)
    chain = reg._chain
    chain[-1][outbox_mod.CLE_WCT]["champ_etranger"] = "intrus"
    ok, msg = outbox_mod.verifier_invariants_outbox(reg)
    assert not ok
    assert msg != ""

