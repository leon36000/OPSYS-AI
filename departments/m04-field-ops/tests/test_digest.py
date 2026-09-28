import copy
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import m4_field_ops.digest as digest_mod
import m4_field_ops.ecarts as ecarts_mod
import m4_field_ops.etats as etats_mod
import m4_field_ops.outbox as outbox_mod
import m4_field_ops.pointage as pointage_mod
import m4_field_ops.registre as registre_mod
import m4_field_ops.cedule as cedule_mod
import m4_field_ops.encodage as encodage_mod


# ==============================================================================
# Constants and helpers
# ==============================================================================
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

H_INSCRIPTION = "2025-06-02T08:00:00+00:00"
H_ARRIVEE = "2025-06-02T09:00:00+00:00"
H_DEPART = "2025-06-02T11:30:00+00:00"
H_COMPLETION = "2025-06-02T11:35:00+00:00"
H_ANOMALIE = "2025-06-02T12:00:00+00:00"   # for pointage anomalies
H_REFERENCE = "2025-06-02T20:00:00+00:00"
DATE_CIBLE = "2025-06-02"

# Distinct intervention until sur_site with two pointages
def _ajouter_intervention_du_jour(reg, lead_id, jour, fin_fenetre="23:00:00"):
    """Mène une intervention DISTINCTE jusqu'à sur_site, entièrement située le
    jour donné, avec la fenêtre de travail du technicien ce jour-là.

    Nécessaire pour construire une demande de revue datée de la VEILLE : un
    pointage hors fenêtre est refusé (CA-M4-19) et un horodatage antérieur au
    précédent l'est aussi (CA-M4-07) — dater l'anomalie d'hier tout en gardant la
    fenêtre d'aujourd'hui est donc IMPOSSIBLE par le chemin réel (mesuré).
    """
    fenetre = {"debut": f"{jour}T07:00:00+00:00", "fin": f"{jour}T{fin_fenetre}+00:00"}
    contrat = dict(CONTRAT_VALIDE)
    contrat["lead_id"] = lead_id
    marqueur = dict(MARQUEUR_VALIDE)
    marqueur["lead_id"] = lead_id
    acc, ver = etats_mod.inscrire_intervention(
        contrat, marqueur, reg, f"{jour}T08:00:00+00:00", SEL
    )
    assert acc is not None, f"Inscription {lead_id} échouée: {ver}"
    i_id = acc["intervention_id"]
    assign = {"intervention_id": i_id, "technicien_id": "T1"}
    acc2, ver2 = etats_mod.transitionner(
        i_id, "en_route", reg, f"{jour}T08:30:00+00:00", assignation=assign
    )
    assert acc2 is not None, f"Transition en_route échouée: {ver2}"
    for action, heure in (("arrivee", "09:00:00"), ("depart", "11:30:00")):
        acc_p, ver_p = pointage_mod.enregistrer_pointage(
            i_id, "T1", action, f"{jour}T{heure}+00:00", GPS_PROCHE, ATTESTATION,
            assign, fenetre, REFERENTIEL, VILLE, SEL, reg
        )
        assert acc_p is not None, f"Pointage {action} échoué: {ver_p}"
    return i_id, fenetre


def _ouvrir_anomalie(reg, i_id, fenetre, horodatage):
    """Ouvre une demande de revue par le chemin RÉEL : un départ incohérent."""
    acc, verd = pointage_mod.enregistrer_pointage(
        i_id, "T1", "depart", horodatage, GPS_LOIN, ATTESTATION,
        {"intervention_id": i_id, "technicien_id": "T1"},
        fenetre, REFERENTIEL, VILLE, SEL, reg,
    )
    assert acc is not None, f"anomalie refusée : {verd}"
    assert acc["demande_id"] is not None
    return acc["demande_id"]


def _ajouter_intervention(reg, lead_id, horodatage_inscription):
    contrat = dict(CONTRAT_VALIDE)
    contrat["lead_id"] = lead_id
    marqueur = dict(MARQUEUR_VALIDE)
    marqueur["lead_id"] = lead_id
    acc, ver = etats_mod.inscrire_intervention(contrat, marqueur, reg, horodatage_inscription, SEL)
    assert acc is not None, f"Inscription {lead_id} échouée: {ver}"
    i_id = acc["intervention_id"]
    assign = {"intervention_id": i_id, "technicien_id": "T1"}
    acc2, ver2 = etats_mod.transitionner(i_id, "en_route", reg, H_ARRIVEE, assignation=assign)
    assert acc2 is not None, f"Transition en_route échouée: {ver2}"
    for action, horo in (("arrivee", H_ARRIVEE), ("depart", H_DEPART)):
        acc_p, ver_p = pointage_mod.enregistrer_pointage(
            i_id, "T1", action, horo, GPS_PROCHE, ATTESTATION,
            assign, FENETRE, REFERENTIEL, VILLE, SEL, reg
        )
        assert acc_p is not None, f"Pointage {action} échoué: {ver_p}"
    return i_id


# ==============================================================================
# Tests
# ==============================================================================

# 1. Épinglage
def test_constantes_epinglees():
    assert digest_mod.CHAMPS_DIGEST == (
        "date_cible", "horodatage_reference", "ancre_registre",
        "interventions_terminees", "interventions_en_revue",
        "count_pending_review", "pending_par_type",
        "interventions_bloquees_en_revue", "empreinte",
    )
    assert digest_mod.SEUIL_BLOCAGE_HEURES == 24


# 2. CA-M4-17 – Déterminisme
def test_determinisme():
    reg = registre_mod.Registre()
    i_id = _ajouter_intervention(reg, "L1", H_INSCRIPTION)
    outbox_mod.completer_intervention(i_id, H_COMPLETION, reg, ecart_detecte=False)

    d1, err1 = digest_mod.produire_digest(reg, DATE_CIBLE, H_REFERENCE)
    d2, err2 = digest_mod.produire_digest(reg, DATE_CIBLE, H_REFERENCE)
    assert err1 is None and err2 is None
    assert d1 == d2
    assert d1["empreinte"] == d2["empreinte"]


# 3. Clés exactes
def test_cles_exactes():
    reg = registre_mod.Registre()
    i_id = _ajouter_intervention(reg, "L1", H_INSCRIPTION)
    outbox_mod.completer_intervention(i_id, H_COMPLETION, reg, ecart_detecte=False)
    digest, err = digest_mod.produire_digest(reg, DATE_CIBLE, H_REFERENCE)
    assert err is None
    assert set(digest.keys()) == set(digest_mod.CHAMPS_DIGEST)


# 4. CA-M4-14 – count_pending_review
def test_count_pending_review():
    reg = registre_mod.Registre()
    i_id = _ajouter_intervention(reg, "L1", H_INSCRIPTION)

    digest0, _ = digest_mod.produire_digest(reg, DATE_CIBLE, H_REFERENCE)
    assert digest0["count_pending_review"] == 0

    # Create an anomaly (pointage incohérent) → demande en attente
    acc_anom, _ = pointage_mod.enregistrer_pointage(
        i_id, "T1", "depart", H_ANOMALIE, GPS_LOIN, ATTESTATION,
        {"intervention_id": i_id, "technicien_id": "T1"},
        FENETRE, REFERENTIEL, VILLE, SEL, reg,
    )
    assert acc_anom is not None
    digest1, _ = digest_mod.produire_digest(reg, DATE_CIBLE, H_REFERENCE)
    assert digest1["count_pending_review"] == 1

    # Resolve → count back to 0
    demande = next(m for m in reg.lire() if m.get("type_entree") == pointage_mod.TYPE_DEMANDE_REVUE)
    demande_id = demande["demande_id"]
    acc_res, _ = ecarts_mod.resoudre_demande(demande_id, "validee", H_COMPLETION, reg)
    assert acc_res is not None
    digest2, _ = digest_mod.produire_digest(reg, DATE_CIBLE, H_REFERENCE)
    assert digest2["count_pending_review"] == 0


# 5. pending_par_type
def test_pending_par_type():
    reg = registre_mod.Registre()
    i_id = _ajouter_intervention(reg, "L1", H_INSCRIPTION)

    # Initial state: both keys present, zero
    digest0, _ = digest_mod.produire_digest(reg, DATE_CIBLE, H_REFERENCE)
    pending0 = digest0["pending_par_type"]
    assert set(pending0.keys()) == set(ecarts_mod.TYPES_DEMANDE)
    for v in pending0.values():
        assert v == 0

    # Produce an anomaly (pointage) → get its type
    acc_anom, _ = pointage_mod.enregistrer_pointage(
        i_id, "T1", "depart", H_ANOMALIE, GPS_LOIN, ATTESTATION,
        {"intervention_id": i_id, "technicien_id": "T1"},
        FENETRE, REFERENTIEL, VILLE, SEL, reg,
    )
    assert acc_anom is not None
    anomaly_maillon = next(
        m for m in reg.lire() if m.get("type_entree") == pointage_mod.TYPE_DEMANDE_REVUE
    )
    anomaly_type = anomaly_maillon["type_demande"]

    # Fabricate a second demand of the OTHER type (not via pointage)
    other_type = next(t for t in ecarts_mod.TYPES_DEMANDE if t != anomaly_type)
    ecart_maillon = {
        "type_entree": pointage_mod.TYPE_DEMANDE_REVUE,
        "demande_id": "ecart-fabrique",
        "intervention_id": i_id,
        "type_demande": other_type,
        "statut_arbitrage": "en_attente",
        "horodatage": H_ANOMALIE,
    }
    reg.ajouter(ecart_maillon)

    digest1, _ = digest_mod.produire_digest(reg, DATE_CIBLE, H_REFERENCE)
    pending1 = digest1["pending_par_type"]
    assert pending1[anomaly_type] == 1
    assert pending1[other_type] == 1
    assert set(pending1.keys()) == set(ecarts_mod.TYPES_DEMANDE)


# 6. interventions_terminees – tri, contenu
def test_interventions_terminees_tri():
    reg = registre_mod.Registre()
    # Insert in order that is NOT sorted by intervention_id
    i_id1 = _ajouter_intervention(reg, "C", H_INSCRIPTION)
    i_id2 = _ajouter_intervention(reg, "A", H_INSCRIPTION)
    i_id3 = _ajouter_intervention(reg, "B", H_INSCRIPTION)

    outbox_mod.completer_intervention(i_id1, H_COMPLETION, reg, ecart_detecte=False)
    outbox_mod.completer_intervention(i_id2, H_COMPLETION, reg, ecart_detecte=False)
    outbox_mod.completer_intervention(i_id3, H_COMPLETION, reg, ecart_detecte=False)

    digest, err = digest_mod.produire_digest(reg, DATE_CIBLE, H_REFERENCE)
    assert err is None
    term = digest["interventions_terminees"]
    assert len(term) == 3

    ids = [e["intervention_id"] for e in term]
    assert ids == sorted(ids)                     # tri garanti
    # Confirms the original order was not already sorted
    original_order = [i_id1, i_id2, i_id3]
    assert original_order != sorted(original_order)

    for elem in term:
        for champ in ("intervention_id", "wct_id", "duree_reelle_minutes", "ecart_signale"):
            assert champ in elem


# 7. Filtre par date
def test_filtre_par_date():
    reg = registre_mod.Registre()
    # Intervention completed within DATE_CIBLE
    i_id_ok = _ajouter_intervention(reg, "L_OK", H_INSCRIPTION)
    outbox_mod.completer_intervention(i_id_ok, H_COMPLETION, reg, ecart_detecte=False)

    # Intervention completed on another day (June 3rd)
    H_INSCR_3 = "2025-06-03T08:00:00+00:00"
    H_ARR_3   = "2025-06-03T09:00:00+00:00"
    H_DEP_3   = "2025-06-03T11:30:00+00:00"
    H_COMP_3  = "2025-06-03T11:35:00+00:00"

    contrat3 = dict(CONTRAT_VALIDE)
    contrat3["lead_id"] = "L3"
    marqueur3 = dict(MARQUEUR_VALIDE)
    marqueur3["lead_id"] = "L3"
    acc, ver = etats_mod.inscrire_intervention(contrat3, marqueur3, reg, H_INSCR_3, SEL)
    assert acc is not None
    i_id3 = acc["intervention_id"]
    assign3 = {"intervention_id": i_id3, "technicien_id": "T1"}
    etats_mod.transitionner(i_id3, "en_route", reg, H_ARR_3, assignation=assign3)
    pointage_mod.enregistrer_pointage(
        i_id3, "T1", "arrivee", H_ARR_3, GPS_PROCHE, ATTESTATION,
        assign3, FENETRE, REFERENTIEL, VILLE, SEL, reg)
    pointage_mod.enregistrer_pointage(
        i_id3, "T1", "depart", H_DEP_3, GPS_PROCHE, ATTESTATION,
        assign3, FENETRE, REFERENTIEL, VILLE, SEL, reg)
    outbox_mod.completer_intervention(i_id3, H_COMP_3, reg, ecart_detecte=False)

    digest, err = digest_mod.produire_digest(reg, DATE_CIBLE, H_REFERENCE)
    assert err is None
    ids = [e["intervention_id"] for e in digest["interventions_terminees"]]
    assert i_id_ok in ids
    assert i_id3 not in ids


# 8. interventions_en_revue
def test_interventions_en_revue():
    reg = registre_mod.Registre()
    i_id = _ajouter_intervention(reg, "L1", H_INSCRIPTION)

    digest0, _ = digest_mod.produire_digest(reg, DATE_CIBLE, H_REFERENCE)
    assert digest0["interventions_en_revue"] == []

    # Create anomaly → status becomes "en_revue"
    pointage_mod.enregistrer_pointage(
        i_id, "T1", "depart", H_ANOMALIE, GPS_LOIN, ATTESTATION,
        {"intervention_id": i_id, "technicien_id": "T1"},
        FENETRE, REFERENTIEL, VILLE, SEL, reg,
    )
    digest1, _ = digest_mod.produire_digest(reg, DATE_CIBLE, H_REFERENCE)
    assert digest1["interventions_en_revue"] == [i_id]

    # Another intervention also in review → verifies sort & no duplicate
    i_id2 = _ajouter_intervention(reg, "L2", H_INSCRIPTION)
    pointage_mod.enregistrer_pointage(
        i_id2, "T1", "depart", H_ANOMALIE, GPS_LOIN, ATTESTATION,
        {"intervention_id": i_id2, "technicien_id": "T1"},
        FENETRE, REFERENTIEL, VILLE, SEL, reg,
    )
    digest2, _ = digest_mod.produire_digest(reg, DATE_CIBLE, H_REFERENCE)
    revues = digest2["interventions_en_revue"]
    assert revues == sorted(revues)
    assert len(revues) == len(set(revues)) == 2

    # Resolve one → disappears
    demande = next(m for m in reg.lire() if m.get("type_entree") == pointage_mod.TYPE_DEMANDE_REVUE
                   and m.get("intervention_id") == i_id)
    ecarts_mod.resoudre_demande(demande["demande_id"], "validee", H_COMPLETION, reg)
    digest3, _ = digest_mod.produire_digest(reg, DATE_CIBLE, H_REFERENCE)
    assert digest3["interventions_en_revue"] == [i_id2]


# 9. interventions_bloquees_en_revue
def test_interventions_bloquees_en_revue():
    """Seuil de 24 h SIMULÉES, compté depuis l'horodatage de référence fourni.

    Les trois demandes sont ouvertes par le chemin RÉEL (départ incohérent), et
    celles de la veille ont tout leur cycle de vie ce jour-là : un pointage hors
    fenêtre ou antérieur au précédent est refusé, donc antidater une anomalie est
    impossible autrement (mesuré).
    """
    reg = registre_mod.Registre()
    # 25 h avant la référence (2025-06-02T20:00) -> BLOQUÉE
    i_id1, fen1 = _ajouter_intervention_du_jour(reg, "L1", "2025-06-01")
    d1 = _ouvrir_anomalie(reg, i_id1, fen1, "2025-06-01T19:00:00+00:00")
    # exactement 24 h -> BLOQUÉE (seuil INCLUSIF)
    i_id3, fen3 = _ajouter_intervention_du_jour(reg, "L3", "2025-06-01")
    d3 = _ouvrir_anomalie(reg, i_id3, fen3, "2025-06-01T20:00:00+00:00")
    # 2 h avant -> PAS bloquée
    i_id2, fen2 = _ajouter_intervention_du_jour(reg, "L2", "2025-06-02")
    _ouvrir_anomalie(reg, i_id2, fen2, "2025-06-02T18:00:00+00:00")

    digest, verdict = digest_mod.produire_digest(reg, DATE_CIBLE, H_REFERENCE)
    assert digest is not None, f"digest refusé : {verdict}"
    bloques = digest["interventions_bloquees_en_revue"]

    assert {b["intervention_id"] for b in bloques} == {i_id1, i_id3}
    par_demande = {b["demande_id"]: b["heures_ecoulees"] for b in bloques}
    assert par_demande[d1] == 25
    assert par_demande[d3] == 24, "le seuil de 24 h est INCLUSIF"
    assert [b["demande_id"] for b in bloques] == sorted(par_demande), "trié par demande_id"


def test_ancre_registre():
    reg = registre_mod.Registre()
    digest_vide, _ = digest_mod.produire_digest(reg, DATE_CIBLE, H_REFERENCE)
    assert digest_vide["ancre_registre"] is None

    i_id = _ajouter_intervention(reg, "L1", H_INSCRIPTION)
    outbox_mod.completer_intervention(i_id, H_COMPLETION, reg, ecart_detecte=False)
    digest_plein, _ = digest_mod.produire_digest(reg, DATE_CIBLE, H_REFERENCE)
    assert digest_plein["ancre_registre"] == reg.tete()

    # Adding another intervention changes the anchor
    _ajouter_intervention(reg, "L2", H_INSCRIPTION)
    digest_apres, _ = digest_mod.produire_digest(reg, DATE_CIBLE, H_REFERENCE)
    assert digest_apres["ancre_registre"] == reg.tete()
    assert digest_apres["ancre_registre"] != digest_plein["ancre_registre"]


# 11. empreinte non circulaire
def test_empreinte_non_circulaire():
    reg = registre_mod.Registre()
    i_id = _ajouter_intervention(reg, "L1", H_INSCRIPTION)
    outbox_mod.completer_intervention(i_id, H_COMPLETION, reg, ecart_detecte=False)
    digest, _ = digest_mod.produire_digest(reg, DATE_CIBLE, H_REFERENCE)

    without_empr = {k: v for k, v in digest.items() if k != "empreinte"}
    expected = encodage_mod.empreinte(without_empr)
    assert digest["empreinte"] == expected


# 12. verifier_digest
def test_verifier_digest_sain():
    reg = registre_mod.Registre()
    i_id = _ajouter_intervention(reg, "L1", H_INSCRIPTION)
    outbox_mod.completer_intervention(i_id, H_COMPLETION, reg, ecart_detecte=False)
    digest, _ = digest_mod.produire_digest(reg, DATE_CIBLE, H_REFERENCE)
    ok, msg = digest_mod.verifier_digest(digest)
    assert ok
    assert msg == ""

def test_verifier_digest_empreinte_falsifiee():
    reg = registre_mod.Registre()
    i_id = _ajouter_intervention(reg, "L1", H_INSCRIPTION)
    outbox_mod.completer_intervention(i_id, H_COMPLETION, reg, ecart_detecte=False)
    digest, _ = digest_mod.produire_digest(reg, DATE_CIBLE, H_REFERENCE)
    fals = copy.deepcopy(digest)
    fals["empreinte"] = "falsified"
    ok, msg = digest_mod.verifier_digest(fals)
    assert not ok
    assert msg != ""

def test_verifier_digest_cle_retiree():
    reg = registre_mod.Registre()
    i_id = _ajouter_intervention(reg, "L1", H_INSCRIPTION)
    outbox_mod.completer_intervention(i_id, H_COMPLETION, reg, ecart_detecte=False)
    digest, _ = digest_mod.produire_digest(reg, DATE_CIBLE, H_REFERENCE)
    fals = copy.deepcopy(digest)
    del fals["interventions_terminees"]
    ok, msg = digest_mod.verifier_digest(fals)
    assert not ok

def test_verifier_digest_non_dict():
    ok, msg = digest_mod.verifier_digest(None)
    assert not ok


# 13. Rejets
@pytest.mark.parametrize("date_cible, code_attendu", [
    (DATE_CIBLE, None),
    (None, "REJ-CONTRAT-INVALIDE"),
    ("", "REJ-CONTRAT-INVALIDE"),
    ("02-06-2025", "REJ-CONTRAT-INVALIDE"),
    ("2025-13-45", "REJ-CONTRAT-INVALIDE"),
])
def test_rejet_date_cible(date_cible, code_attendu):
    reg = registre_mod.Registre()
    i_id = _ajouter_intervention(reg, "L1", H_INSCRIPTION)
    outbox_mod.completer_intervention(i_id, H_COMPLETION, reg, ecart_detecte=False)
    digest, verdict = digest_mod.produire_digest(reg, date_cible, H_REFERENCE)
    if code_attendu is None:
        assert verdict is None
    else:
        assert digest is None
        assert verdict["code"] == code_attendu

def test_rejet_horodatage_sans_fuseau():
    reg = registre_mod.Registre()
    i_id = _ajouter_intervention(reg, "L1", H_INSCRIPTION)
    outbox_mod.completer_intervention(i_id, H_COMPLETION, reg, ecart_detecte=False)
    digest, verdict = digest_mod.produire_digest(reg, DATE_CIBLE, "2025-06-02T20:00:00")
    assert digest is None
    assert verdict["code"] == "REJ-HORODATAGE-INVALIDE"


# 14. CA-M4-15 – garde d'horloge
def test_garde_absence_horloge_reelle():
    ok, msg = digest_mod.garde_absence_horloge()
    assert ok
    assert msg == ""

def test_garde_absence_horloge_violation_now(tmp_path):
    faux = tmp_path / "faux_now.py"
    faux.write_text("from datetime import datetime\ndatetime.now()\n")
    ok, msg = digest_mod.garde_absence_horloge(chemin_source=str(tmp_path))
    assert not ok
    assert msg != ""

def test_garde_absence_horloge_violation_time_time(tmp_path):
    faux = tmp_path / "faux_time.py"
    faux.write_text("import time\ntime.time()\n")
    ok, msg = digest_mod.garde_absence_horloge(chemin_source=str(tmp_path))
    assert not ok

def test_garde_absence_horloge_violation_import_time(tmp_path):
    faux = tmp_path / "faux_import.py"
    faux.write_text("import time\n")
    ok, msg = digest_mod.garde_absence_horloge(chemin_source=str(tmp_path))
    assert not ok

def test_garde_absence_horloge_autorise_fromisoformat(tmp_path):
    faux = tmp_path / "faux_iso.py"
    faux.write_text("from datetime import datetime\nx = datetime.fromisoformat('2025-06-02')\n")
    ok, msg = digest_mod.garde_absence_horloge(chemin_source=str(tmp_path))
    assert ok
    assert msg == ""


# 15. CA-M4-16 – garde de scoring
def test_garde_conformite_r020_reelle():
    ok, msg = digest_mod.garde_conformite_r020()
    assert ok
    assert msg == ""

def test_garde_conformite_r020_dict_cle(tmp_path):
    faux = tmp_path / "dict_cle.py"
    faux.write_text('data = {"score_technicien": 5}\n')
    ok, msg = digest_mod.garde_conformite_r020(chemin_source=str(tmp_path))
    assert not ok

def test_garde_conformite_r020_fonction(tmp_path):
    faux = tmp_path / "fonction.py"
    faux.write_text("def calculer_score(): pass\n")
    ok, _ = digest_mod.garde_conformite_r020(chemin_source=str(tmp_path))
    assert not ok

def test_garde_conformite_r020_affectation(tmp_path):
    faux = tmp_path / "affectation.py"
    faux.write_text("note_technicien = 5\n")
    ok, _ = digest_mod.garde_conformite_r020(chemin_source=str(tmp_path))
    assert not ok

def test_garde_conformite_r020_chaine_hors_cle(tmp_path):
    # Allowed: terms inside a string constant that is not a dict key
    faux = tmp_path / "chaine.py"
    faux.write_text('msg = "le score de scoring est interdit"\n')
    ok, msg = digest_mod.garde_conformite_r020(chemin_source=str(tmp_path))
    assert ok
    assert msg == ""


# 16. Digest without scoring terms
def test_digest_sans_termes_scoring():
    reg = registre_mod.Registre()
    i_id = _ajouter_intervention(reg, "L1", H_INSCRIPTION)
    outbox_mod.completer_intervention(i_id, H_COMPLETION, reg, ecart_detecte=False)
    digest, _ = digest_mod.produire_digest(reg, DATE_CIBLE, H_REFERENCE)
    representation = str(digest).lower()
    for terme in digest_mod.TERMES_INTERDITS_R020:
        assert terme not in representation

@pytest.mark.parametrize("date_hors_contrat", [
    "2025-06-02T12:00:00+00:00",
    "2025-06-02T12:00:00",
    "2025-06-02 12:00:00+00:00",
])
def test_date_cible_avec_heure_refusee(date_hors_contrat):
    """fromisoformat SEUL accepte une date-heure, ce qui fausserait le filtre par
    préfixe des interventions terminées (objection de revue, mesurée : le digest
    était produit sans broncher). La date doit être EXACTEMENT AAAA-MM-JJ."""
    reg = registre_mod.Registre()
    digest, verdict = digest_mod.produire_digest(reg, date_hors_contrat, H_REFERENCE)
    assert digest is None, "une date_cible portant une heure doit être REFUSÉE"
    assert verdict["code"] == "REJ-CONTRAT-INVALIDE"
    assert "AAAA-MM-JJ" in verdict["detail"]


@pytest.mark.parametrize("identifiant_majuscule, fabrique", [
    ("SCORE_TECHNICIEN", "SCORE_TECHNICIEN = 5\n"),
    ("NOTE_TECHNICIEN", "NOTE_TECHNICIEN = {'a': 1}\n"),
    ("PERFORMANCE", "def f():\n    PERFORMANCE = 1\n    return PERFORMANCE\n"),
])
def test_garde_r020_ne_laisse_pas_passer_les_majuscules(tmp_path, identifiant_majuscule, fabrique):
    """Objection de revue trouvée par DEUX relecteurs indépendamment : la garde
    exemptait les identifiants tout en majuscules, échappatoire discrète. Cette
    exemption n'était même pas nécessaire — le nom de la liste de termes ne
    contient aucun terme interdit, et les valeurs chaînes sont déjà hors portée."""
    (tmp_path / "faux.py").write_text(fabrique, encoding="utf-8")
    ok, msg = digest_mod.garde_conformite_r020(chemin_source=str(tmp_path))
    assert not ok, f"{identifiant_majuscule} en majuscules doit être DÉTECTÉ"
    assert msg


def test_gardes_inspectent_aussi_init(tmp_path):
    """Objection de revue : les gardes sautaient __init__.py — un fichier exempté
    est un fichier où l'on peut tout cacher."""
    (tmp_path / "__init__.py").write_text(
        "def calculer_score(x):\n    return x\n", encoding="utf-8"
    )
    ok, msg = digest_mod.garde_conformite_r020(chemin_source=str(tmp_path))
    assert not ok, "un terme interdit caché dans __init__.py doit être DÉTECTÉ"
    (tmp_path / "__init__.py").write_text(
        "import datetime\ndef maintenant():\n    return datetime.datetime.now()\n",
        encoding="utf-8",
    )
    ok2, msg2 = digest_mod.garde_absence_horloge(chemin_source=str(tmp_path))
    assert not ok2, "une horloge cachée dans __init__.py doit être DÉTECTÉE"


@pytest.mark.parametrize("appel_horloge", [
    "import time\ndef f():\n    return time.time_ns()\n",
    "import time\ndef f():\n    return time.process_time()\n",
    "import calendar\ndef f():\n    return calendar.timegm(())\n",
    "import os\ndef f():\n    return os.times()\n",
])
def test_garde_horloge_liste_completee(tmp_path, appel_horloge):
    """Objection de revue : la liste des fonctions d'horloge n'était pas
    exhaustive. Ces quatre appels interrogent bien une horloge et doivent être
    refusés."""
    (tmp_path / "faux.py").write_text(appel_horloge, encoding="utf-8")
    ok, msg = digest_mod.garde_absence_horloge(chemin_source=str(tmp_path))
    assert not ok, f"appel d'horloge non détecté : {appel_horloge!r}"
    assert msg

@pytest.mark.parametrize("attribut_interdit, fabrique", [
    ("SCORE_TECHNICIEN", "def f(obj):\n    obj.SCORE_TECHNICIEN = 1\n"),
    ("note_technicien", "def f(obj):\n    return obj.note_technicien\n"),
    ("PERFORMANCE", "def f(obj):\n    return obj.PERFORMANCE\n"),
])
def test_garde_r020_inspecte_aussi_les_attributs(tmp_path, attribut_interdit, fabrique):
    """La garde a DEUX branches : les identifiants et les noms d'ATTRIBUT. Mes
    premiers tests de durcissement ne couvraient que la première — la mutation
    « exemption des majuscules réintroduite » sur la branche attribut ne mordait
    donc pas. Un terme interdit passé par un attribut est aussi efficace qu'un
    passé par une variable."""
    (tmp_path / "faux.py").write_text(fabrique, encoding="utf-8")
    ok, msg = digest_mod.garde_conformite_r020(chemin_source=str(tmp_path))
    assert not ok, f"attribut {attribut_interdit} non détecté"
    assert msg

@pytest.mark.parametrize("cas, fabrique", [
    # Paramètres JAMAIS utilisés dans le corps : un paramètre utilisé apparaît
    # aussi comme ast.Name, donc une autre branche l'attraperait et la branche
    # « paramètre » ne serait pas discriminée (mutation mesurée non détectée).
    ("parametre_inutilise", "def f(score_technicien):\n    return 1\n"),
    ("parametre_majuscule_inutilise", "def f(NOTE_TECHNICIEN):\n    return 1\n"),
    ("mot_cle_appel", "def g(**kw):\n    return kw\ndef f():\n    return g(performance=1)\n"),
    ("coroutine", "async def calculer_score(x):\n    return x\n"),
])
def test_garde_r020_couvre_signatures_motscles_et_coroutines(tmp_path, cas, fabrique):
    """Objections MAJEURES du round 2 (Grok-4.5) : un terme interdit pouvait vivre
    dans une SIGNATURE de fonction, dans un mot-clé d'appel, ou dans le nom d'une
    coroutine — trois portes que la portée annoncée (« noms d'identifiants »)
    prétendait couvrir sans les inspecter."""
    (tmp_path / "faux.py").write_text(fabrique, encoding="utf-8")
    ok, msg = digest_mod.garde_conformite_r020(chemin_source=str(tmp_path))
    assert not ok, f"cas non détecté : {cas}"
    assert msg


def test_garde_horloge_clock_gettime_ns(tmp_path):
    """Objection mineure r2 : clock_gettime_ns interroge une horloge et manquait."""
    # SANS importer time : « import time » ferait échouer la garde par une autre
    # voie et la présence de clock_gettime_ns dans la liste ne serait pas
    # discriminée (mutation mesurée non détectée).
    (tmp_path / "faux.py").write_text(
        "def f(horloge):\n    return horloge.clock_gettime_ns(0)\n", encoding="utf-8"
    )
    ok, msg = digest_mod.garde_absence_horloge(chemin_source=str(tmp_path))
    assert not ok
    assert msg


def test_docstring_de_la_garde_ne_promet_aucune_exemption():
    """La documentation d'une garde EST une promesse : la docstring annonçait
    encore l'exemption des majuscules après son retrait (objection MAJEURE r2 —
    une spec inline qui contredit le code est un piège pour le prochain lecteur,
    qui croira l'échappatoire ouverte ou la réintroduira)."""
    doc = digest_mod.garde_conformite_r020.__doc__
    assert doc, "la garde doit documenter sa portée"
    bas = doc.lower()
    assert "majuscules" not in bas or "sans aucune exemption" in bas
    for promesse in ("paramètres", "coroutines", "limite inhérente"):
        assert promesse in bas, f"la docstring doit annoncer : {promesse}"

