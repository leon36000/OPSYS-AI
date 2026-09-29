# Tests de m4_field_ops.ecarts — M4-S007 (écarts, file pending_review, arbitrage).
import copy
import json

import m4_field_ops.cedule as cedule_mod
import m4_field_ops.ecarts as ecarts_mod
import m4_field_ops.etats as etats_mod
import m4_field_ops.outbox as outbox_mod
import m4_field_ops.pointage as pointage_mod
import m4_field_ops.registre as registre_mod
import pytest

# ------------------------------------------------------------------ helpers
SEL = "sel-de-test"
H1 = "2025-06-02T08:00:00+00:00"
H2 = "2025-06-02T09:00:00+00:00"
H3 = "2025-06-02T10:00:00+00:00"
H4 = "2025-06-02T11:00:00+00:00"
H5 = "2025-06-02T12:00:00+00:00"

CONTRAT_VALIDE = {
    "lead_id": "L1",
    "conversation_id": "C1",
    "type_travaux": "renovation_totale",
    "ville": "Montreal",
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


VILLE = CONTRAT_VALIDE["ville"]
REFERENTIEL = {
    cedule_mod.tokeniser_ville(SEL, VILLE): {
        "latitude": 45.5017, "longitude": -73.5673, "rayon_km": 25.0,
    }
}
GPS_PROCHE = {"latitude": 45.5088, "longitude": -73.5878}
GPS_LOIN = {"latitude": 46.8139, "longitude": -71.2080}
ATTESTATION = {"fictif": True, "appareil_id": "APP-1"}
FENETRE = {"debut": "2025-06-02T07:00:00+00:00", "fin": "2025-06-02T19:00:00+00:00"}


def _registre_sur_site():
    """Registre neuf avec une intervention sur_site ET ses deux pointages.

    Les pointages ne sont pas décoratifs : depuis S008, la complétion calcule la
    durée réelle depuis les pointages et REFUSE fail-closed sans eux. Une
    intervention terrain ne peut donc pas être complétée sans ses pointages —
    conséquence assumée, et c'est le chemin RÉEL de production.
    """
    reg = registre_mod.Registre()
    acc, ver = etats_mod.inscrire_intervention(CONTRAT_VALIDE, MARQUEUR_VALIDE, reg, H1, SEL)
    assert acc is not None, f"Inscription echouee: {ver}"
    i_id = acc["intervention_id"]
    assign = {"intervention_id": i_id, "technicien_id": "T1"}
    acc2, ver2 = etats_mod.transitionner(i_id, "en_route", reg, H2, assignation=assign)
    assert acc2 is not None, f"Transition en_route echouee: {ver2}"
    acc3, ver3 = pointage_mod.enregistrer_pointage(
        i_id, "T1", "arrivee", H2, GPS_PROCHE, ATTESTATION,
        assign, FENETRE, REFERENTIEL, VILLE, SEL, reg,
    )
    assert acc3 is not None, f"Pointage arrivee echoue: {ver3}"
    assert etats_mod.statut_courant(reg, i_id) == "sur_site"
    acc4, ver4 = pointage_mod.enregistrer_pointage(
        i_id, "T1", "depart", H3, GPS_PROCHE, ATTESTATION,
        assign, FENETRE, REFERENTIEL, VILLE, SEL, reg,
    )
    assert acc4 is not None, f"Pointage depart echoue: {ver4}"
    return reg, i_id


def _registre_en_revue_par_anomalie():
    """Registre neuf, intervention en_revue via une ANOMALIE DE POINTAGE réelle
    (arrivée hors périmètre GPS déclaré) : chemin CA-M4-08, distinct d'un écart
    métier. Retourne (registre, intervention_id, demande_id)."""
    reg = registre_mod.Registre()
    acc, ver = etats_mod.inscrire_intervention(CONTRAT_VALIDE, MARQUEUR_VALIDE, reg, H1, SEL)
    assert acc is not None, f"Inscription echouee: {ver}"
    i_id = acc["intervention_id"]
    assign = {"intervention_id": i_id, "technicien_id": "T1"}
    acc2, ver2 = etats_mod.transitionner(i_id, "en_route", reg, H2, assignation=assign)
    assert acc2 is not None, f"Transition en_route echouee: {ver2}"
    acc3, ver3 = pointage_mod.enregistrer_pointage(
        i_id, "T1", "arrivee", H2, GPS_LOIN, ATTESTATION,
        assign, FENETRE, REFERENTIEL, VILLE, SEL, reg,
    )
    assert acc3 is not None, f"Pointage arrivee (anomalie) echoue: {ver3}"
    assert etats_mod.statut_courant(reg, i_id) == "en_revue"
    demande_id = acc3["demande_id"]
    assert demande_id is not None
    return reg, i_id, demande_id


VERSION_PREVUE = {
    "duree_minutes": 120,
    "perimetre": "salle de bain",
    "materiaux": ["carrelage"],
}
VERSION_DECLAREE = {
    "duree_minutes": 180,
    "perimetre": "salle de bain et couloir",
    "materiaux": ["carrelage", "plinthes"],
}


# ------------------------------------------------------------------ 15. Constantes epinglees
def test_constantes_types_demande():
    assert ecarts_mod.TYPES_DEMANDE == ("ecart_metier", "anomalie_pointage")


def test_constantes_decisions():
    assert ecarts_mod.DECISIONS == ("validee", "rejetee")


def test_constantes_statuts_arbitrage():
    assert ecarts_mod.STATUTS_ARBITRAGE == ("en_attente", "validee", "rejetee")


def test_constantes_cles_version():
    assert ecarts_mod.CLES_VERSION == ("duree_minutes", "perimetre", "materiaux")


# ------------------------------------------------------------------ 1. CA-M4-09 — versions conservees intactes
def test_versions_intactes_et_copies_profondes():
    reg, i_id = _registre_sur_site()
    prevue = copy.deepcopy(VERSION_PREVUE)
    declaree = copy.deepcopy(VERSION_DECLAREE)
    accuse, verdict = ecarts_mod.creer_demande_ecart(
        i_id, prevue, declaree, H4, reg
    )
    assert accuse is not None, f"Echec creation: {verdict}"
    maillon = next(m for m in reg.lire() if m.get("type_entree") == pointage_mod.TYPE_DEMANDE_REVUE)
    assert maillon["version_prevue"] == VERSION_PREVUE
    assert maillon["version_declaree"] == VERSION_DECLAREE
    assert "diff" not in maillon
    assert "fusion" not in maillon
    assert "version_finale" not in maillon

    # Muter les dicts de l'appelant ne change pas le registre
    prevue["duree_minutes"] = 999
    prevue["perimetre"] = "modifie"
    prevue["materiaux"].append("parquet")
    declaree["duree_minutes"] = 0
    declaree["materiaux"] = []
    maillon2 = next(m for m in reg.lire() if m.get("type_entree") == pointage_mod.TYPE_DEMANDE_REVUE)
    assert maillon2["version_prevue"] == VERSION_PREVUE
    assert maillon2["version_declaree"] == VERSION_DECLAREE


# ------------------------------------------------------------------ 2. Accuse complet et transition en_revue
def test_accuse_complet_et_transition():
    reg, i_id = _registre_sur_site()
    accuse, _ = ecarts_mod.creer_demande_ecart(
        i_id, VERSION_PREVUE, VERSION_DECLAREE, H4, reg
    )
    assert accuse is not None
    assert set(accuse.keys()) == {
        "demande_id", "intervention_id", "ligne_id", "type_demande",
        "statut_arbitrage", "statut", "tete_chaine",
    }
    assert accuse["statut_arbitrage"] == "en_attente"
    assert accuse["type_demande"] == "ecart_metier"
    assert etats_mod.statut_courant(reg, i_id) == "en_revue"
    assert reg.valider_chaine() is True


# ------------------------------------------------------------------ 3. Versions identiques -> refus
def test_versions_identiques_refus():
    reg, i_id = _registre_sur_site()
    taille_avant = len(reg.lire())
    accuse, verdict = ecarts_mod.creer_demande_ecart(
        i_id, VERSION_PREVUE, copy.deepcopy(VERSION_PREVUE), H4, reg
    )
    assert accuse is None
    assert verdict["code"] == "REJ-CONTRAT-INVALIDE"
    assert "identiques" in verdict["detail"].lower()
    assert len(reg.lire()) == taille_avant


# ------------------------------------------------------------------ 4. Validation des versions
@pytest.mark.parametrize("prevue, declaree, code_attendu, mot_detail", [
    # non-dict
    ("string", VERSION_DECLAREE, "REJ-CONTRAT-INVALIDE", None),
    (VERSION_PREVUE, 42, "REJ-CONTRAT-INVALIDE", None),
    # clé manquante
    ({"duree_minutes": 120, "perimetre": "sdb"}, VERSION_DECLAREE, "REJ-CONTRAT-INVALIDE", None),
    (VERSION_PREVUE, {"duree_minutes": 180, "perimetre": "hall"}, "REJ-CONTRAT-INVALIDE", None),
    # clé étrangère
    ({"duree_minutes": 120, "perimetre": "sdb", "materiaux": [], "extra": 1},
     VERSION_DECLAREE, "REJ-CONTRAT-INVALIDE", None),
    (VERSION_PREVUE, {"duree_minutes": 180, "perimetre": "hall", "materiaux": [], "autre": True},
     "REJ-CONTRAT-INVALIDE", None),
    # duree_minutes booléen
    ({"duree_minutes": True, "perimetre": "sdb", "materiaux": []}, VERSION_DECLAREE, "REJ-CONTRAT-INVALIDE", None),
    # duree_minutes négatif
    ({"duree_minutes": -1, "perimetre": "sdb", "materiaux": []}, VERSION_DECLAREE, "REJ-CONTRAT-INVALIDE", None),
    # perimetre vide
    ({"duree_minutes": 120, "perimetre": "", "materiaux": []}, VERSION_DECLAREE, "REJ-CHAMP-VIDE", None),
    (VERSION_PREVUE, {"duree_minutes": 180, "perimetre": "", "materiaux": []}, "REJ-CHAMP-VIDE", None),
    # materiaux non-liste
    ({"duree_minutes": 120, "perimetre": "sdb", "materiaux": "string"},
     VERSION_DECLAREE, "REJ-CONTRAT-INVALIDE", None),
    (VERSION_PREVUE, {"duree_minutes": 180, "perimetre": "hall", "materiaux": 123}, "REJ-CONTRAT-INVALIDE", None),
    # materiaux contient élément vide
    ({"duree_minutes": 120, "perimetre": "sdb", "materiaux": [""]}, VERSION_DECLAREE, "REJ-CONTRAT-INVALIDE", None),
    (VERSION_PREVUE, {"duree_minutes": 180, "perimetre": "hall", "materiaux": ["ok", ""]},
     "REJ-CONTRAT-INVALIDE", None),
    # materiaux contient non-str
    ({"duree_minutes": 120, "perimetre": "sdb", "materiaux": [1]}, VERSION_DECLAREE, "REJ-CONTRAT-INVALIDE", None),
])
def test_validation_versions(prevue, declaree, code_attendu, mot_detail):
    reg, i_id = _registre_sur_site()
    taille_avant = len(reg.lire())
    accuse, verdict = ecarts_mod.creer_demande_ecart(
        i_id, prevue, declaree, H4, reg
    )
    assert accuse is None
    assert verdict["code"] == code_attendu
    if mot_detail:
        assert mot_detail in verdict["detail"].lower()
    assert len(reg.lire()) == taille_avant


# ------------------------------------------------------------------ 5. Intervention inexistante / terminale
def test_intervention_inexistante():
    reg, i_id = _registre_sur_site()
    taille_avant = len(reg.lire())
    accuse, verdict = ecarts_mod.creer_demande_ecart(
        "FAKE_ID", VERSION_PREVUE, VERSION_DECLAREE, H4, reg
    )
    assert accuse is None
    assert verdict["code"] == "REJ-TRANSITION-ILLEGALE"
    assert len(reg.lire()) == taille_avant


def test_intervention_terminale():
    reg, i_id = _registre_sur_site()
    # amener à un état terminal (T1.1-b#2 : completed_verified ici)
    # Depuis S008, seule l'outbox écrit vers une issue de complétion (maillon composite, CA-M4-11).
    acc, _ = outbox_mod.completer_intervention(i_id, H4, reg, ecart_detecte=False)
    assert acc is not None
    statut = etats_mod.statut_courant(reg, i_id)
    assert statut in etats_mod.ETATS_TERMINAUX
    taille_avant = len(reg.lire())
    accuse, verdict = ecarts_mod.creer_demande_ecart(
        i_id, VERSION_PREVUE, VERSION_DECLAREE, H5, reg
    )
    assert accuse is None
    assert verdict["code"] == "REJ-TRANSITION-ILLEGALE"
    assert "terminal" in verdict["detail"].lower()
    assert len(reg.lire()) == taille_avant


# ------------------------------------------------------------------ 6. Demande en double
def test_demande_en_double():
    reg, i_id = _registre_sur_site()
    # premier appel OK
    acc1, _ = ecarts_mod.creer_demande_ecart(
        i_id, VERSION_PREVUE, VERSION_DECLAREE, H4, reg
    )
    assert acc1 is not None
    taille_avant = len(reg.lire())
    # second appel identique -> rejet
    accuse, verdict = ecarts_mod.creer_demande_ecart(
        i_id, VERSION_PREVUE, VERSION_DECLAREE, H4, reg
    )
    assert accuse is None
    assert verdict["code"] == "REJ-CONTRAT-INVALIDE"
    assert "déjà ouverte" in verdict["detail"].lower()
    assert len(reg.lire()) == taille_avant


# ------------------------------------------------------------------ 7. CA-M4-21 — append-only resolution
def test_resolution_append_only():
    reg, i_id = _registre_sur_site()
    # creer demande ecart
    acc_demande, _ = ecarts_mod.creer_demande_ecart(
        i_id, VERSION_PREVUE, VERSION_DECLAREE, H4, reg
    )
    assert acc_demande is not None
    demande_id = acc_demande["demande_id"]
    # capturer le maillon de demande avant resolution
    maillons_avant = list(reg.lire())
    demande_avant = next(m for m in maillons_avant if m.get("type_entree") == pointage_mod.TYPE_DEMANDE_REVUE)
    taille_avant = len(maillons_avant)
    # resoudre
    acc_res, _ = ecarts_mod.resoudre_demande(demande_id, "validee", H5, reg)
    assert acc_res is not None
    maillons_apres = list(reg.lire())
    # Une résolution écrit DEUX maillons, et c'est voulu : la machine à états
    # reste la SEULE autorité qui écrit l'état (son propre maillon
    # transition_statut), la résolution est une entrée distincte. Compter « +1 »
    # supposerait que le module des écarts écrive l'état lui-même — ce serait
    # une seconde autorité sur le même invariant. On épingle donc la COMPOSITION
    # exacte, pas un total.
    ajoutes = maillons_apres[taille_avant:]
    assert len(ajoutes) == 2
    types_ajoutes = [m["type_entree"] for m in ajoutes]
    assert types_ajoutes.count(etats_mod.TYPE_TRANSITION) == 1
    assert types_ajoutes.count(ecarts_mod.TYPE_RESOLUTION) == 1
    assert all(m["intervention_id"] == i_id for m in ajoutes)
    # la demande d'origine est toujours presente et inchangee
    demande_apres = next(m for m in maillons_apres if m.get("type_entree") == pointage_mod.TYPE_DEMANDE_REVUE)
    assert demande_avant == demande_apres
    # nouvelle entree resolution_revue existe
    resolutions = [m for m in maillons_apres if m.get("type_entree") == ecarts_mod.TYPE_RESOLUTION]
    assert len(resolutions) == 1
    resolution = resolutions[0]
    assert resolution["demande_id"] == demande_id
    assert reg.valider_chaine() is True


# ------------------------------------------------------------------ 8. Resolutions validee/rejetee
def test_resolution_validee_completed_pending_review():
    """Un écart métier validé EST un écart détecté : ecarts.py fixe
    ecart_detecte=True, l'issue est donc completed_pending_review (T1.1-b#2),
    jamais completed_verified."""
    reg, i_id = _registre_sur_site()
    acc, _ = ecarts_mod.creer_demande_ecart(
        i_id, VERSION_PREVUE, VERSION_DECLAREE, H4, reg
    )
    demande_id = acc["demande_id"]
    ecarts_mod.resoudre_demande(demande_id, "validee", H5, reg)
    assert etats_mod.statut_courant(reg, i_id) == "completed_pending_review"


def test_resolution_rejetee_annulee():
    reg, i_id = _registre_sur_site()
    acc, _ = ecarts_mod.creer_demande_ecart(
        i_id, VERSION_PREVUE, VERSION_DECLAREE, H4, reg
    )
    demande_id = acc["demande_id"]
    ecarts_mod.resoudre_demande(demande_id, "rejetee", H5, reg)
    assert etats_mod.statut_courant(reg, i_id) == "annulee"


# ------------------------------------------- 8 bis. anomalie_pointage validee -> reprise sur_site (PRD §4)
def test_resolution_anomalie_pointage_validee_reprend_sur_site():
    """BUG CORRIGÉ : une anomalie de pointage 'validee' tentait TOUJOURS la
    complétion (outbox.completer_intervention), qui échouait fail-closed
    ('durée réelle indéterminable' : aucun départ n'existe pour une arrivée en
    anomalie) — et en_revue -> sur_site restait de fait inatteignable par ce
    chemin. Le PRD §4 prévoit précisément cette reprise (amendement #145)."""
    reg, i_id, demande_id = _registre_en_revue_par_anomalie()
    taille_avant = len(reg.lire())
    acc_res, verdict = ecarts_mod.resoudre_demande(demande_id, "validee", H5, reg)
    assert acc_res is not None, f"résolution refusée à tort : {verdict}"
    assert etats_mod.statut_courant(reg, i_id) == "sur_site"
    assert len(reg.lire()) == taille_avant + 2  # transition_statut + resolution_revue
    dernier_transition = next(
        m for m in reversed(reg.lire()) if m.get("type_entree") == etats_mod.TYPE_TRANSITION
    )
    assert dernier_transition["statut"] == "sur_site"
    assert dernier_transition["statut_precedent"] == "en_revue"
    assert reg.valider_chaine() is True
    # Depuis sur_site, l'intervention peut désormais reprendre normalement :
    # un nouveau départ cohérent complète le travail.
    assign = {"intervention_id": i_id, "technicien_id": "T1"}
    acc_dep, ver_dep = pointage_mod.enregistrer_pointage(
        i_id, "T1", "depart", H5, GPS_PROCHE, ATTESTATION,
        assign, FENETRE, REFERENTIEL, VILLE, SEL, reg,
    )
    assert acc_dep is not None, f"départ après reprise refusé : {ver_dep}"
    assert etats_mod.statut_courant(reg, i_id) == "sur_site"


def test_resolution_anomalie_pointage_rejetee_annule():
    reg, i_id, demande_id = _registre_en_revue_par_anomalie()
    acc_res, verdict = ecarts_mod.resoudre_demande(demande_id, "rejetee", H5, reg)
    assert acc_res is not None, f"résolution refusée : {verdict}"
    assert etats_mod.statut_courant(reg, i_id) == "annulee"


# ------------------------------------------------------------------ 9. Double resolution refus
def test_double_resolution_refus():
    reg, i_id = _registre_sur_site()
    acc, _ = ecarts_mod.creer_demande_ecart(
        i_id, VERSION_PREVUE, VERSION_DECLAREE, H4, reg
    )
    demande_id = acc["demande_id"]
    ecarts_mod.resoudre_demande(demande_id, "validee", H5, reg)
    taille_avant = len(reg.lire())
    accuse, verdict = ecarts_mod.resoudre_demande(demande_id, "rejetee", H5, reg)
    assert accuse is None
    assert verdict["code"] == "REJ-CONTRAT-INVALIDE"
    assert "déjà résolue" in verdict["detail"].lower()
    assert len(reg.lire()) == taille_avant


# ------------------------------------------------------------------ 11. lister_pending_review
def test_lister_vide_au_depart():
    reg, i_id = _registre_sur_site()
    result = ecarts_mod.lister_pending_review(reg)
    assert result == []
    result_ecart = ecarts_mod.lister_pending_review(reg, type_demande="ecart_metier")
    assert result_ecart == []


def test_lister_contient_apres_creation():
    reg, i_id = _registre_sur_site()
    ecarts_mod.creer_demande_ecart(i_id, VERSION_PREVUE, VERSION_DECLAREE, H4, reg)
    pending = ecarts_mod.lister_pending_review(reg)
    assert len(pending) == 1
    assert pending[0]["type_demande"] == "ecart_metier"
    assert pending[0]["statut_arbitrage"] == "en_attente"


def test_lister_ne_contient_plus_apres_resolution():
    reg, i_id = _registre_sur_site()
    acc, _ = ecarts_mod.creer_demande_ecart(i_id, VERSION_PREVUE, VERSION_DECLAREE, H4, reg)
    demande_id = acc["demande_id"]
    ecarts_mod.resoudre_demande(demande_id, "validee", H5, reg)
    pending = ecarts_mod.lister_pending_review(reg)
    assert len(pending) == 0


def test_lister_filtre_type():
    reg, i_id = _registre_sur_site()
    ecarts_mod.creer_demande_ecart(i_id, VERSION_PREVUE, VERSION_DECLAREE, H4, reg)
    pending_ecart = ecarts_mod.lister_pending_review(reg, type_demande="ecart_metier")
    assert len(pending_ecart) == 1
    pending_anomalie = ecarts_mod.lister_pending_review(reg, type_demande="anomalie_pointage")
    assert len(pending_anomalie) == 0


def test_lister_type_inconnu_leve_valueerror():
    reg, _ = _registre_sur_site()
    with pytest.raises(ValueError, match="type_demande inconnu"):
        ecarts_mod.lister_pending_review(reg, type_demande="inconnu")


def test_lister_retourne_copie():
    reg, i_id = _registre_sur_site()
    ecarts_mod.creer_demande_ecart(i_id, VERSION_PREVUE, VERSION_DECLAREE, H4, reg)
    pendings = ecarts_mod.lister_pending_review(reg)
    assert len(pendings) == 1
    pendings[0]["falsified"] = True
    # Re-lire pour confirmer que le registre est intact
    pendings2 = ecarts_mod.lister_pending_review(reg)
    assert "falsified" not in pendings2[0]


# ------------------------------------------------------------------ 11 bis. ecart_metier_ouvert (PLAN T1.5-c)
def test_ecart_metier_ouvert_faux_sans_demande():
    reg, i_id = _registre_sur_site()
    assert ecarts_mod.ecart_metier_ouvert(reg, i_id) is False


def test_ecart_metier_ouvert_vrai_apres_creation_de_la_demande():
    reg, i_id = _registre_sur_site()
    ecarts_mod.creer_demande_ecart(i_id, VERSION_PREVUE, VERSION_DECLAREE, H4, reg)
    assert ecarts_mod.ecart_metier_ouvert(reg, i_id) is True


def test_ecart_metier_ouvert_faux_une_fois_la_demande_resolue():
    reg, i_id = _registre_sur_site()
    acc, _ = ecarts_mod.creer_demande_ecart(i_id, VERSION_PREVUE, VERSION_DECLAREE, H4, reg)
    ecarts_mod.resoudre_demande(acc["demande_id"], "validee", H5, reg)
    assert ecarts_mod.ecart_metier_ouvert(reg, i_id) is False


def test_ecart_metier_ouvert_ne_compte_pas_la_demande_d_une_autre_intervention():
    reg, i_id = _registre_sur_site()
    ecarts_mod.creer_demande_ecart(i_id, VERSION_PREVUE, VERSION_DECLAREE, H4, reg)
    assert ecarts_mod.ecart_metier_ouvert(reg, "autre-intervention") is False


def test_ecart_metier_ouvert_ne_compte_pas_une_anomalie_de_pointage():
    """Deux concepts qui ne confluent jamais (TYPES_DEMANDE) : une anomalie de cohérence terrain
    n'est pas un écart sur les faits déclarés."""
    reg, i_id, _ = _registre_en_revue_par_anomalie()
    assert len(ecarts_mod.lister_pending_review(reg, type_demande="anomalie_pointage")) == 1
    assert ecarts_mod.ecart_metier_ouvert(reg, i_id) is False


# ------------------------------------------------------------------ 12. Les deux types ne confluent jamais
def test_types_ne_confluent_pas():
    reg, i_id = _registre_sur_site()
    # Creer une demande ecart via la fonction
    ecarts_mod.creer_demande_ecart(i_id, VERSION_PREVUE, VERSION_DECLAREE, H4, reg)
    # Creer une anomalie pointage via enregistrer_pointage (GPS LOIN)
    # Pour cela, il faut que l'intervention soit en_route? Mais elle est en_revue après la demande ecart.
    # On va plutôt créer un nouveau registre avec intervention en_route et utiliser enregistrer_pointage.
    reg2, i_id2 = _registre_sur_site()
    # remettre en_route? Non, on part d'un registre en_route.
    # Re-utilisons le helper _registre_en_route de fait nous n'avons pas -> on va le construire localement.
    # On peut juste changer l'état pour le pointage: on repart de _registre_sur_site et on fait
    # transitionner vers en_route (non, illégal depuis sur_site).
    # On va créer un troisieme registre avec intervention en_route (inscrire, transition en_route)
    # et appeler enregistrer_pointage avec GPS_LOIN.
    reg3 = registre_mod.Registre()
    acc, _ = etats_mod.inscrire_intervention(CONTRAT_VALIDE, MARQUEUR_VALIDE, reg3, H1, SEL)
    i_id3 = acc["intervention_id"]
    etats_mod.transitionner(
        i_id3, "en_route", reg3, H2,
        assignation={"intervention_id": i_id3, "technicien_id": "T1"},
    )
    # Enregistrer pointage avec GPS_LOIN pour créer une anomalie
    # On a besoin d'assignation, fenêtre, référentiel, etc.
    # On reprend les constantes de test_pointage.
    # On importe cedule_mod? Mais on ne doit pas importer autre chose. On peut le faire via le module
    # cedule importé? Non.
    # On va devoir créer un token, etc. Pour rester simple, on peut juste créer manuellement un maillon d'anomalie
    # en utilisant pointage_mod.TYPE_DEMANDE_REVUE directement.
    # L'énoncé dit: "ET une demande anomalie_pointage (en ecrivant directement au registre un maillon ...)"
    # Donc on peut faire reg.ajouter(...) avec le bon maillon.
    # Construisons un maillon minimal d'anomalie.
    maillon_anomalie = {
        "type_entree": pointage_mod.TYPE_DEMANDE_REVUE,
        "intervention_id": i_id,
        "type_demande": "anomalie_pointage",
        "demande_id": "fake-anomaly-1",
        "statut_arbitrage": "en_attente",
        "causes_possibles": [],
        "pointage_ligne_id": "fake-ligne",
        "horodatage": H4,
    }
    reg.ajouter(maillon_anomalie)
    # Maintenant on teste le filtrage
    result_ecart = ecarts_mod.lister_pending_review(reg, "ecart_metier")
    result_anomalie = ecarts_mod.lister_pending_review(reg, "anomalie_pointage")
    assert len(result_ecart) == 1
    assert len(result_anomalie) == 1
    assert result_ecart[0]["type_demande"] == "ecart_metier"
    assert result_anomalie[0]["type_demande"] == "anomalie_pointage"


# ------------------------------------------------------------------ 13. Volumetrie
def test_volumetrie_avant_creation():
    reg, i_id = _registre_sur_site()
    vol = ecarts_mod.volumetrie_pending_review(reg)
    assert vol == {"total": 0, "ecart_metier": 0, "anomalie_pointage": 0}
    # determinisme
    vol2 = ecarts_mod.volumetrie_pending_review(reg)
    assert vol == vol2


def test_volumetrie_apres_creation():
    reg, i_id = _registre_sur_site()
    ecarts_mod.creer_demande_ecart(i_id, VERSION_PREVUE, VERSION_DECLAREE, H4, reg)
    vol = ecarts_mod.volumetrie_pending_review(reg)
    assert vol == {"total": 1, "ecart_metier": 1, "anomalie_pointage": 0}


def test_volumetrie_apres_resolution():
    reg, i_id = _registre_sur_site()
    acc, _ = ecarts_mod.creer_demande_ecart(i_id, VERSION_PREVUE, VERSION_DECLAREE, H4, reg)
    ecarts_mod.resoudre_demande(acc["demande_id"], "validee", H5, reg)
    vol = ecarts_mod.volumetrie_pending_review(reg)
    assert vol == {"total": 0, "ecart_metier": 0, "anomalie_pointage": 0}


# ------------------------------------------------------------------ 14. CA-M4-20 — neutralite et whitelist de cles
def test_neutralite_absence_termes_accusateurs():
    reg, i_id = _registre_sur_site()
    ecarts_mod.creer_demande_ecart(i_id, VERSION_PREVUE, VERSION_DECLAREE, H4, reg)
    termes_interdits = ["fraude", "faute", "coupable", "mensonge", "triche", "culpabilit"]
    for maillon in reg.lire():
        str_repr = json.dumps(maillon, default=str).lower()
        for terme in termes_interdits:
            assert terme not in str_repr, f"terme accusatoire '{terme}' dans un maillon : {maillon}"


def test_whitelist_cles_demande_ecart():
    reg, i_id = _registre_sur_site()
    ecarts_mod.creer_demande_ecart(i_id, VERSION_PREVUE, VERSION_DECLAREE, H4, reg)
    demande = None
    for m in reg.lire():
        if m.get("type_entree") == pointage_mod.TYPE_DEMANDE_REVUE:
            demande = m
            break
    assert demande is not None
    cles_attendues = {
        "type_entree", "intervention_id", "horodatage", "type_demande",
        "demande_id", "version_prevue", "version_declaree", "statut_arbitrage",
        "ligne_id", "precedent_ligne_id",
    }
    assert set(demande.keys()) == cles_attendues, f"cles inattendues: {sorted(demande.keys())}"


def test_whitelist_cles_resolution():
    reg, i_id = _registre_sur_site()
    acc, _ = ecarts_mod.creer_demande_ecart(i_id, VERSION_PREVUE, VERSION_DECLAREE, H4, reg)
    ecarts_mod.resoudre_demande(acc["demande_id"], "validee", H5, reg)
    resolution = next(m for m in reg.lire() if m.get("type_entree") == ecarts_mod.TYPE_RESOLUTION)
    cles_attendues = {
        "type_entree", "intervention_id", "horodatage", "demande_id",
        "decision", "statut_arbitrage", "resolution_id", "ligne_id", "precedent_ligne_id",
    }
    # motif absent, donc pas dans les clés
    assert set(resolution.keys()) == cles_attendues, f"cles inattendues: {sorted(resolution.keys())}"


# ------------------------------------------------------------------ 10 suite (motif vide)
# On doit avoir un test spécifique : nous l'avons dans parametrize, mais il faut corriger parametrize bug

@pytest.mark.parametrize("decision, horodatage, demande_id_prov, motif, code_attendu, detail_partiel", [
    ("inconnue", H5, "fake", None, "REJ-ENUM-INVALIDE", None),
    ("validee", "2025-06-02", "fake", None, "REJ-HORODATAGE-INVALIDE", None),
    ("validee", H5, "INCONNUE", None, "REJ-CONTRAT-INVALIDE", "introuvable"),
    ("validee", H5, "fake", "", "REJ-CONTRAT-INVALIDE", None),
])
def test_rejets_args_resolution(decision, horodatage, demande_id_prov, motif, code_attendu, detail_partiel):
    reg, i_id = _registre_sur_site()
    # Pour les cas où on a besoin d'un vrai demande_id, on le crée sauf si on simule une inconnue
    if demande_id_prov != "INCONNUE":
        acc, _ = ecarts_mod.creer_demande_ecart(i_id, VERSION_PREVUE, VERSION_DECLAREE, H4, reg)
        demande_id = acc["demande_id"]
    else:
        demande_id = "INCONNUE"
    taille_avant = len(reg.lire())
    accuse, verdict = ecarts_mod.resoudre_demande(
        demande_id, decision, horodatage, reg, motif=motif
    )
    assert accuse is None
    assert verdict["code"] == code_attendu
    if detail_partiel:
        assert detail_partiel in verdict["detail"].lower()
    assert len(reg.lire()) == taille_avant

def test_resolution_refusee_si_la_transition_est_illegale():
    """FAIL-OPEN mesuré : ignorer le verdict de la machine à états écrivait une
    résolution alors que l'état ne changeait pas — un arbitrage consigné comme
    fait, sans effet. Chemin réel : une intervention encore `planifiee` porte
    une demande (planifiee -> en_revue n'est pas dans la table, donc aucune
    transition n'a lieu à la création), et `terminee` n'est pas atteignable
    depuis `planifiee`."""
    reg = registre_mod.Registre()
    accuse, verdict = etats_mod.inscrire_intervention(CONTRAT_VALIDE, MARQUEUR_VALIDE, reg, H1, SEL)
    assert accuse is not None, f"inscription refusée : {verdict}"
    i_id = accuse["intervention_id"]
    assert etats_mod.statut_courant(reg, i_id) == "planifiee"

    acc_demande, v_demande = ecarts_mod.creer_demande_ecart(
        i_id, VERSION_PREVUE, VERSION_DECLAREE, H4, reg
    )
    assert acc_demande is not None, f"demande refusée : {v_demande}"
    assert etats_mod.statut_courant(reg, i_id) == "planifiee", (
        "aucune transition ne doit avoir lieu : planifiee -> en_revue est hors table"
    )

    taille_avant = reg.taille()
    acc_res, v_res = ecarts_mod.resoudre_demande(
        acc_demande["demande_id"], "validee", H5, reg
    )
    assert acc_res is None, "une résolution sans transition légale doit être REFUSÉE"
    assert v_res["code"] == "REJ-TRANSITION-ILLEGALE"
    assert reg.taille() == taille_avant, (
        "aucune résolution ne doit être écrite si l'état ne peut pas suivre"
    )
    assert ecarts_mod.lister_pending_review(reg), "la demande reste EN ATTENTE"

@pytest.mark.parametrize("decision, statut_attendu", [
    ("validee", "completed_pending_review"),
    ("rejetee", "annulee"),
])
def test_maillon_resolution_porte_la_decision_arbitree(decision, statut_attendu):
    """Le maillon de résolution consigne la DÉCISION arbitrée dans son
    statut_arbitrage — pas « en_attente » figé (mutation mesurée non détectée :
    seule la file, qui filtre sur l'EXISTENCE d'une résolution, était observée).
    Une file vidée ne dit pas ce qui a été décidé ; le maillon, si."""
    reg, i_id = _registre_sur_site()
    acc_demande, _ = ecarts_mod.creer_demande_ecart(
        i_id, VERSION_PREVUE, VERSION_DECLAREE, H4, reg
    )
    acc_res, verdict = ecarts_mod.resoudre_demande(
        acc_demande["demande_id"], decision, H5, reg
    )
    assert acc_res is not None, f"résolution refusée : {verdict}"
    resolution = next(
        m for m in reg.lire() if m.get("type_entree") == ecarts_mod.TYPE_RESOLUTION
    )
    assert resolution["decision"] == decision
    assert resolution["statut_arbitrage"] == decision, (
        "le maillon doit consigner la décision arbitrée, pas rester « en_attente »"
    )
    assert resolution["statut_arbitrage"] in ecarts_mod.STATUTS_ARBITRAGE
    assert resolution["statut_arbitrage"] != "en_attente"
    assert etats_mod.statut_courant(reg, i_id) == statut_attendu
    # la demande d'origine, elle, garde son propre statut_arbitrage intact
    demande = next(
        m for m in reg.lire() if m.get("type_entree") == pointage_mod.TYPE_DEMANDE_REVUE
    )
    assert demande["statut_arbitrage"] == "en_attente", (
        "append-only : la demande d'origine n'est jamais réécrite"
    )

