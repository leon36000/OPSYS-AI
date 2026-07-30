import json
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import m4_field_ops.pointage as pointage_mod
import m4_field_ops.registre as registre_mod
import m4_field_ops.etats as etats_mod
import m4_field_ops.cedule as cedule_mod

# ------------------------------------------------------------------ constantes de test
H_VALIDE = "2025-06-02T08:00:00+00:00"
H_VALIDE2 = "2025-06-02T09:00:00+00:00"
H_VALIDE3 = "2025-06-02T10:00:00+00:00"
H_VALIDE4 = "2025-06-02T11:00:00+00:00"
H_VALIDE5 = "2025-06-02T12:00:00+00:00"

SEL = "sel-de-test"
VILLE = "Montreal"

# Référentiel avec token, pas la ville en clair
REFERENTIEL = {
    cedule_mod.tokeniser_ville(SEL, VILLE): {
        "latitude": 45.5017,
        "longitude": -73.5673,
        "rayon_km": 25.0,
    }
}

GPS_PROCHE = {"latitude": 45.5088, "longitude": -73.5878}   # ~2 km du centre
GPS_LOIN = {"latitude": 46.8139, "longitude": -71.2080}      # ~230 km

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

def _registre_en_route():
    """Crée un registre avec une intervention en_route."""
    reg = registre_mod.Registre()
    accusé, verdict = etats_mod.inscrire_intervention(CONTRAT_VALIDE, MARQUEUR_VALIDE, reg, H_VALIDE, SEL)
    assert accusé is not None, f"Échec inscription: {verdict}"
    i_id = accusé["intervention_id"]
    accusé2, v2 = etats_mod.transitionner(i_id, "en_route", reg, H_VALIDE2)
    assert accusé2 is not None, f"Échec transition vers en_route: {v2}"
    return reg, i_id

def _registre_sur_site():
    """Crée un registre avec une intervention sur_site."""
    reg, i_id = _registre_en_route()
    accusé, verdict = etats_mod.transitionner(i_id, "sur_site", reg, H_VALIDE3)
    assert accusé is not None, f"Échec transition vers sur_site: {verdict}"
    return reg, i_id

def ASSIGNATION(intervention_id):
    return {"intervention_id": intervention_id, "technicien_id": "T1"}

# ------------------------------------------------------------------ 1. distance_km
def test_distance_km_meme_point():
    d = pointage_mod.distance_km(45.5, -73.5, 45.5, -73.5)
    assert d == 0.0

def test_distance_km_symetrique():
    d1 = pointage_mod.distance_km(45.5, -73.5, 46.8, -71.2)
    d2 = pointage_mod.distance_km(46.8, -71.2, 45.5, -73.5)
    assert d1 == pytest.approx(d2, rel=1e-9)

def test_distance_km_montreal_quebec():
    d = pointage_mod.distance_km(45.5017, -73.5673, 46.8139, -71.2080)
    assert 200 <= d <= 260

# ------------------------------------------------------------------ 2. Nominal arrivée cohérente
def test_arrivee_coherente():
    reg, i_id = _registre_en_route()
    assign = ASSIGNATION(i_id)
    # horodatage pendant la fenêtre
    horo = "2025-06-02T10:00:00+00:00"
    token = cedule_mod.tokeniser_ville(SEL, VILLE)
    accusé, verdict = pointage_mod.enregistrer_pointage(
        i_id, assign["technicien_id"], "arrivee", horo,
        GPS_PROCHE, ATTESTATION, assign, FENETRE, REFERENTIEL, VILLE, SEL, reg
    )
    assert accusé is not None, f"enregistrement échoué: {verdict}"
    assert set(accusé.keys()) == {"intervention_id", "technicien_id", "action", "horodatage",
                                  "ligne_id", "gps_coherent", "statut", "demande_id", "tete_chaine"}
    assert accusé["gps_coherent"] is True
    assert accusé["demande_id"] is None
    assert accusé["statut"] == "sur_site"
    assert reg.valider_chaine() is True
    # Le maillon de pointage n'est PAS le dernier après une arrivée cohérente :
    # la transition vers sur_site est écrite APRÈS lui. On le localise par son
    # ligne_id (mesuré — lire()[-1] renvoyait la transition).
    maillon = next(m for m in reg.lire() if m["ligne_id"] == accusé["ligne_id"])
    expected_keys = {"type_entree", "intervention_id", "technicien_id", "action",
                     "horodatage", "latitude", "longitude", "appareil_id", "fictif",
                     "ville_tokenisee", "gps_coherent"}
    assert set(maillon.keys()) >= expected_keys
    assert maillon["ville_tokenisee"] == token
    assert maillon["type_entree"] == pointage_mod.TYPE_POINTAGE

# ------------------------------------------------------------------ 3. Ville en clair absente
def test_ville_en_clair_absente_apres_pointage():
    reg, i_id = _registre_en_route()
    horo = "2025-06-02T10:00:00+00:00"
    accusé, _ = pointage_mod.enregistrer_pointage(
        i_id, "T1", "arrivee", horo,
        GPS_PROCHE, ATTESTATION, ASSIGNATION(i_id), FENETRE, REFERENTIEL, VILLE, SEL, reg
    )
    assert accusé is not None
    for maillon in reg.lire():
        str_maillon = str(maillon)
        assert VILLE not in str_maillon

# ------------------------------------------------------------------ 4. Arrivée INCOHÉRENTE (GPS_LOIN)
def test_arrivee_incoherente():
    reg, i_id = _registre_en_route()
    horo = "2025-06-02T10:00:00+00:00"
    accusé, verdict = pointage_mod.enregistrer_pointage(
        i_id, "T1", "arrivee", horo,
        GPS_LOIN, ATTESTATION, ASSIGNATION(i_id), FENETRE, REFERENTIEL, VILLE, SEL, reg
    )
    assert accusé is not None
    assert accusé["gps_coherent"] is False
    assert accusé["demande_id"] is not None
    # statut ne doit PAS avoir changé, reste en_route
    assert etats_mod.statut_courant(reg, i_id) == "en_route"
    # présence demande_revue
    maillons = reg.lire()
    demande = None
    for m in maillons:
        if m.get("type_entree") == pointage_mod.TYPE_DEMANDE_REVUE:
            demande = m
            break
    assert demande is not None
    assert demande["type_demande"] == "anomalie_pointage"
    assert demande["statut_arbitrage"] == "en_attente"
    assert list(demande["causes_possibles"]) == list(pointage_mod.CAUSES_NEUTRES)
    assert demande["pointage_ligne_id"] == accusé["ligne_id"]

# ------------------------------------------------------------------ 5. Départ INCOHÉRENT depuis sur_site
def test_depart_incoherent():
    reg, i_id = _registre_sur_site()
    horo = "2025-06-02T11:00:00+00:00"
    accusé, verdict = pointage_mod.enregistrer_pointage(
        i_id, "T1", "depart", horo,
        GPS_LOIN, ATTESTATION, ASSIGNATION(i_id), FENETRE, REFERENTIEL, VILLE, SEL, reg
    )
    assert accusé is not None
    assert accusé["gps_coherent"] is False
    assert accusé["demande_id"] is not None
    assert etats_mod.statut_courant(reg, i_id) == "en_revue"
    # demande_revue existe
    maillons = reg.lire()
    demande = None
    for m in maillons:
        if m.get("type_entree") == pointage_mod.TYPE_DEMANDE_REVUE:
            demande = m
            break
    assert demande is not None

# ------------------------------------------------------------------ 6. Départ cohérent depuis sur_site
def test_depart_coherent():
    reg, i_id = _registre_sur_site()
    horo = "2025-06-02T11:00:00+00:00"
    accusé, verdict = pointage_mod.enregistrer_pointage(
        i_id, "T1", "depart", horo,
        GPS_PROCHE, ATTESTATION, ASSIGNATION(i_id), FENETRE, REFERENTIEL, VILLE, SEL, reg
    )
    assert accusé is not None
    assert accusé["gps_coherent"] is True
    assert accusé["demande_id"] is None
    # statut doit rester sur_site (pas de transition automatique vers terminee)
    assert etats_mod.statut_courant(reg, i_id) == "sur_site"

# ------------------------------------------------------------------ 7. CA-M4-20 (neutralité)
def test_causes_neutres_sans_terme_accusateur():
    termes_interdits = ["fraude", "faute", "coupable", "mensonge", "triche"]
    for cause in pointage_mod.CAUSES_NEUTRES:
        for terme in termes_interdits:
            assert terme not in cause.lower(), f"'{terme}' trouvé dans '{cause}'"

def test_aucun_maillon_contenant_fraude_ni_culpabilite():
    # vérification sur un registre quelconque (après pointage incohérent)
    reg, i_id = _registre_en_route()
    horo = "2025-06-02T10:00:00+00:00"
    pointage_mod.enregistrer_pointage(
        i_id, "T1", "arrivee", horo,
        GPS_LOIN, ATTESTATION, ASSIGNATION(i_id), FENETRE, REFERENTIEL, VILLE, SEL, reg
    )
    for m in reg.lire():
        # parcourir toutes les clés et valeurs en chaînes
        str_repr = json.dumps(m, default=str)  # si dict
        bas = str_repr.lower()
        for terme in ("fraude", "culpabilit", "coupable", "triche", "mensonge", "faute"):
            assert terme not in bas, f"terme accusatoire '{terme}' dans un maillon : {m}"
        if m.get("type_entree") == pointage_mod.TYPE_DEMANDE_REVUE:
            # whitelist GELÉE des clés d'une demande de revue (CA-M4-20) : toute clé
            # supplémentaire doit être un acte conscient, jamais une fuite silencieuse.
            assert set(m.keys()) == {
                "type_entree", "intervention_id", "horodatage", "type_demande",
                "pointage_ligne_id", "causes_possibles", "statut_arbitrage", "demande_id",
                "ligne_id", "precedent_ligne_id",
            }, f"clés inattendues dans la demande de revue : {sorted(m.keys())}"

# ------------------------------------------------------------------ 8. CA-M4-19 / Loi 25
def test_pointage_hors_fenetre_avant():
    reg, i_id = _registre_en_route()
    taille_avant = len(reg.lire())
    horo_avant = "2025-06-02T06:55:00+00:00"  # avant début fenêtre
    assign = ASSIGNATION(i_id)
    accusé, verdict = pointage_mod.enregistrer_pointage(
        i_id, "T1", "arrivee", horo_avant,
        GPS_PROCHE, ATTESTATION, assign, FENETRE, REFERENTIEL, VILLE, SEL, reg
    )
    assert accusé is None
    assert verdict["code"] == "REJ-PUNCH-HORS-HEURES"
    assert len(reg.lire()) == taille_avant
    str_verdict = str(verdict)
    assert str(GPS_PROCHE["latitude"]) not in str_verdict
    assert str(GPS_PROCHE["longitude"]) not in str_verdict
    for m in reg.lire():
        str_m = str(m)
        assert str(GPS_PROCHE["latitude"]) not in str_m
        assert str(GPS_PROCHE["longitude"]) not in str_m

def test_pointage_hors_fenetre_apres():
    reg, i_id = _registre_en_route()
    taille_avant = len(reg.lire())
    horo_apres = "2025-06-02T19:05:00+00:00"  # après fin
    assign = ASSIGNATION(i_id)
    accusé, verdict = pointage_mod.enregistrer_pointage(
        i_id, "T1", "arrivee", horo_apres,
        GPS_PROCHE, ATTESTATION, assign, FENETRE, REFERENTIEL, VILLE, SEL, reg
    )
    assert accusé is None
    assert verdict["code"] == "REJ-PUNCH-HORS-HEURES"
    assert len(reg.lire()) == taille_avant
    str_verdict = str(verdict)
    assert str(GPS_PROCHE["latitude"]) not in str_verdict
    assert str(GPS_PROCHE["longitude"]) not in str_verdict

# ------------------------------------------------------------------ 9. Fenêtre invalide AVANT examen
def test_fenetre_debut_superieur_fin():
    reg, i_id = _registre_en_route()
    fenetre_invalide = {"debut": "2025-06-02T12:00:00+00:00", "fin": "2025-06-02T11:00:00+00:00"}
    taille_avant = len(reg.lire())
    accusé, verdict = pointage_mod.enregistrer_pointage(
        i_id, "T1", "arrivee", "2025-06-02T10:00:00+00:00",
        GPS_PROCHE, ATTESTATION, ASSIGNATION(i_id), fenetre_invalide, REFERENTIEL, VILLE, SEL, reg
    )
    assert accusé is None
    assert verdict["code"] == "REJ-FENETRE-INVALIDE"
    assert len(reg.lire()) == taille_avant

def test_fenetre_cles_fausses():
    reg, i_id = _registre_en_route()
    fenetre_invalide = {"start": "2025-06-02T07:00:00+00:00", "end": "2025-06-02T19:00:00+00:00"}
    taille_avant = len(reg.lire())
    accusé, verdict = pointage_mod.enregistrer_pointage(
        i_id, "T1", "arrivee", "2025-06-02T10:00:00+00:00",
        GPS_PROCHE, ATTESTATION, ASSIGNATION(i_id), fenetre_invalide, REFERENTIEL, VILLE, SEL, reg
    )
    assert accusé is None
    assert verdict["code"] == "REJ-FENETRE-INVALIDE"
    assert len(reg.lire()) == taille_avant

def test_fenetre_borne_sans_fuseau():
    reg, i_id = _registre_en_route()
    fenetre_invalide = {"debut": "2025-06-02T07:00:00", "fin": "2025-06-02T19:00:00+00:00"}  # pas de tz
    taille_avant = len(reg.lire())
    accusé, verdict = pointage_mod.enregistrer_pointage(
        i_id, "T1", "arrivee", "2025-06-02T10:00:00+00:00",
        GPS_PROCHE, ATTESTATION, ASSIGNATION(i_id), fenetre_invalide, REFERENTIEL, VILLE, SEL, reg
    )
    assert accusé is None
    assert verdict["code"] == "REJ-FENETRE-INVALIDE"
    assert len(reg.lire()) == taille_avant

# ------------------------------------------------------------------ 10. CA-M4-07 horodatage anterieur
def test_pointage_anterieur_et_egal():
    reg, i_id = _registre_en_route()
    assign = ASSIGNATION(i_id)
    # premier pointage
    acc1, _ = pointage_mod.enregistrer_pointage(
        i_id, "T1", "arrivee", H_VALIDE3,
        GPS_PROCHE, ATTESTATION, assign, FENETRE, REFERENTIEL, VILLE, SEL, reg
    )
    assert acc1 is not None
    # deuxième pointage avec horodatage antérieur
    taille_avant = len(reg.lire())
    acc2, verdict = pointage_mod.enregistrer_pointage(
        i_id, "T1", "depart", "2025-06-02T09:00:00+00:00",  # antérieur
        GPS_PROCHE, ATTESTATION, assign, FENETRE, REFERENTIEL, VILLE, SEL, reg
    )
    assert acc2 is None
    assert verdict["code"] == "REJ-HORODATAGE-ANTERIEUR"
    assert len(reg.lire()) == taille_avant
    # troisième pointage au même horodatage que le dernier (H_VALIDE3)
    acc3, _ = pointage_mod.enregistrer_pointage(
        i_id, "T1", "depart", H_VALIDE3,  # égal
        GPS_PROCHE, ATTESTATION, assign, FENETRE, REFERENTIEL, VILLE, SEL, reg
    )
    assert acc3 is not None

# ------------------------------------------------------------------ 11. CA-M4-12
def test_pointage_depuis_planifiee_arrivee():
    reg = registre_mod.Registre()
    acc, _ = etats_mod.inscrire_intervention(CONTRAT_VALIDE, MARQUEUR_VALIDE, reg, H_VALIDE, SEL)
    i_id = acc["intervention_id"]
    assign = ASSIGNATION(i_id)
    accusé, verdict = pointage_mod.enregistrer_pointage(
        i_id, "T1", "arrivee", H_VALIDE2,
        GPS_PROCHE, ATTESTATION, assign, FENETRE, REFERENTIEL, VILLE, SEL, reg
    )
    assert accusé is None
    assert verdict["code"] == "REJ-PUNCH-SANS-INTERVENTION"

def test_depart_alors_que_en_route():
    reg, i_id = _registre_en_route()
    assign = ASSIGNATION(i_id)
    accusé, verdict = pointage_mod.enregistrer_pointage(
        i_id, "T1", "depart", H_VALIDE3,
        GPS_PROCHE, ATTESTATION, assign, FENETRE, REFERENTIEL, VILLE, SEL, reg
    )
    assert accusé is None
    assert verdict["code"] == "REJ-PUNCH-SANS-INTERVENTION"

def test_assignation_autre_technicien():
    reg, i_id = _registre_en_route()
    assign = {"intervention_id": i_id, "technicien_id": "AUTRE_TECH"}
    accusé, verdict = pointage_mod.enregistrer_pointage(
        i_id, "T1", "arrivee", H_VALIDE3,
        GPS_PROCHE, ATTESTATION, assign, FENETRE, REFERENTIEL, VILLE, SEL, reg
    )
    assert accusé is None
    assert verdict["code"] == "REJ-PUNCH-SANS-INTERVENTION"

def test_assignation_autre_intervention():
    reg, i_id = _registre_en_route()
    assign = {"intervention_id": "FAKE_ID", "technicien_id": "T1"}
    accusé, verdict = pointage_mod.enregistrer_pointage(
        i_id, "T1", "arrivee", H_VALIDE3,
        GPS_PROCHE, ATTESTATION, assign, FENETRE, REFERENTIEL, VILLE, SEL, reg
    )
    assert accusé is None
    assert verdict["code"] == "REJ-PUNCH-SANS-INTERVENTION"

# ------------------------------------------------------------------ 12. Attestation
@pytest.mark.parametrize("attestation_bad", [
    "string",
    [1, 2],
    {"fictif": False},  # clés fausses, manque appareil_id
    {"appareil_id": "X"},  # manque fictif
    {"fictif": False, "appareil_id": "APP-1"},
    {"fictif": 1, "appareil_id": "APP-1"},
    {"fictif": True, "appareil_id": ""},
])
def test_attestation_rejet(attestation_bad):
    reg, i_id = _registre_en_route()
    assign = ASSIGNATION(i_id)
    taille_avant = len(reg.lire())
    accusé, verdict = pointage_mod.enregistrer_pointage(
        i_id, "T1", "arrivee", H_VALIDE3,
        GPS_PROCHE, attestation_bad, assign, FENETRE, REFERENTIEL, VILLE, SEL, reg
    )
    assert accusé is None
    assert verdict["code"] == "REJ-CONTRAT-INVALIDE"
    assert len(reg.lire()) == taille_avant

# ------------------------------------------------------------------ 13. fix_gps
@pytest.mark.parametrize("gps_bad", [
    "string",
    [45.0, -73.0],
    {"lat": 45, "lon": -73},
    {"latitude": True, "longitude": -73.0},
    {"latitude": "45", "longitude": -73.0},
    {"latitude": 91, "longitude": -73},
    {"latitude": 45, "longitude": -181},
])
def test_gps_rejet(gps_bad):
    reg, i_id = _registre_en_route()
    assign = ASSIGNATION(i_id)
    taille_avant = len(reg.lire())
    accusé, verdict = pointage_mod.enregistrer_pointage(
        i_id, "T1", "arrivee", H_VALIDE3,
        gps_bad, ATTESTATION, assign, FENETRE, REFERENTIEL, VILLE, SEL, reg
    )
    assert accusé is None
    assert verdict["code"] == "REJ-CONTRAT-INVALIDE"
    assert len(reg.lire()) == taille_avant

# ------------------------------------------------------------------ 14. Référentiel
def test_referentiel_token_absent():
    reg, i_id = _registre_en_route()
    # token correspondant à une ville inconnue
    ref_bad = {cedule_mod.tokeniser_ville(SEL, "Inconnue"): {"latitude": 40, "longitude": -74, "rayon_km": 10}}
    accuse, verdict = pointage_mod.enregistrer_pointage(
        i_id, "T1", "arrivee", H_VALIDE3,
        GPS_PROCHE, ATTESTATION, ASSIGNATION(i_id), FENETRE, ref_bad, VILLE, SEL, reg
    )
    assert accuse is None
    assert verdict["code"] == "REJ-CONTRAT-INVALIDE"
    assert "périmètre" in verdict["detail"].lower()

def test_referentiel_entree_cles_fausses():
    reg, i_id = _registre_en_route()
    token = cedule_mod.tokeniser_ville(SEL, VILLE)
    ref_bad = {token: {"lat": 45.5, "lon": -73.5}}  # clés manquantes
    accuse, verdict = pointage_mod.enregistrer_pointage(
        i_id, "T1", "arrivee", H_VALIDE3,
        GPS_PROCHE, ATTESTATION, ASSIGNATION(i_id), FENETRE, ref_bad, VILLE, SEL, reg
    )
    assert accuse is None
    assert verdict["code"] == "REJ-CONTRAT-INVALIDE"

def test_referentiel_rayon_zero():
    reg, i_id = _registre_en_route()
    token = cedule_mod.tokeniser_ville(SEL, VILLE)
    ref_bad = {token: {"latitude": 45.5, "longitude": -73.5, "rayon_km": 0}}
    accuse, verdict = pointage_mod.enregistrer_pointage(
        i_id, "T1", "arrivee", H_VALIDE3,
        GPS_PROCHE, ATTESTATION, ASSIGNATION(i_id), FENETRE, ref_bad, VILLE, SEL, reg
    )
    assert accuse is None
    assert verdict["code"] == "REJ-CONTRAT-INVALIDE"

def test_referentiel_rayon_non_numerique():
    reg, i_id = _registre_en_route()
    token = cedule_mod.tokeniser_ville(SEL, VILLE)
    ref_bad = {token: {"latitude": 45.5, "longitude": -73.5, "rayon_km": "grand"}}
    accuse, verdict = pointage_mod.enregistrer_pointage(
        i_id, "T1", "arrivee", H_VALIDE3,
        GPS_PROCHE, ATTESTATION, ASSIGNATION(i_id), FENETRE, ref_bad, VILLE, SEL, reg
    )
    assert accuse is None
    assert verdict["code"] == "REJ-CONTRAT-INVALIDE"

# ------------------------------------------------------------------ 15. Action invalide, horodatage invalide
def test_action_hors_enum():
    reg, i_id = _registre_en_route()
    assign = ASSIGNATION(i_id)
    accuse, verdict = pointage_mod.enregistrer_pointage(
        i_id, "T1", "pause", H_VALIDE3,
        GPS_PROCHE, ATTESTATION, assign, FENETRE, REFERENTIEL, VILLE, SEL, reg
    )
    assert accuse is None
    assert verdict["code"] == "REJ-ENUM-INVALIDE"

def test_horodatage_sans_fuseau():
    reg, i_id = _registre_en_route()
    assign = ASSIGNATION(i_id)
    accuse, verdict = pointage_mod.enregistrer_pointage(
        i_id, "T1", "arrivee", "2025-06-02T10:00:00",
        GPS_PROCHE, ATTESTATION, assign, FENETRE, REFERENTIEL, VILLE, SEL, reg
    )
    assert accuse is None
    assert verdict["code"] == "REJ-HORODATAGE-INVALIDE"

# ------------------------------------------------------------------ 16. Ordre des contrôles
def test_ordre_controle_action_avant_horodatage():
    reg, i_id = _registre_en_route()
    assign = ASSIGNATION(i_id)
    # action invalide + horodatage invalide -> REJ-ENUM-INVALIDE
    accuse, verdict = pointage_mod.enregistrer_pointage(
        i_id, "T1", "pause", "bad",
        GPS_PROCHE, ATTESTATION, assign, FENETRE, REFERENTIEL, VILLE, SEL, reg
    )
    assert accuse is None
    assert verdict["code"] == "REJ-ENUM-INVALIDE"

def test_ordre_controle_hors_fenetre_avant_assignation():
    reg, i_id = _registre_en_route()
    # assignation mauvais technicien, mais horodatage hors fenêtre
    assign_bad = {"intervention_id": i_id, "technicien_id": "AUTRE"}
    accuse, verdict = pointage_mod.enregistrer_pointage(
        i_id, "T1", "arrivee", "2025-06-02T06:00:00+00:00",
        GPS_PROCHE, ATTESTATION, assign_bad, FENETRE, REFERENTIEL, VILLE, SEL, reg
    )
    assert accuse is None
    assert verdict["code"] == "REJ-PUNCH-HORS-HEURES"

# ------------------------------------------------------------------ 17. Chaîne intacte après parcours
def test_chaine_intacte():
    # Parcours complet sur un registre neuf : arrivée cohérente puis départ incohérent.
    reg2, i_id2 = _registre_en_route()
    assign = ASSIGNATION(i_id2)
    # arrivée cohérente
    acc1, _ = pointage_mod.enregistrer_pointage(
        i_id2, "T1", "arrivee", H_VALIDE3,
        GPS_PROCHE, ATTESTATION, assign, FENETRE, REFERENTIEL, VILLE, SEL, reg2
    )
    assert acc1 is not None
    # départ incohérent
    acc2, _ = pointage_mod.enregistrer_pointage(
        i_id2, "T1", "depart", H_VALIDE4,
        GPS_LOIN, ATTESTATION, assign, FENETRE, REFERENTIEL, VILLE, SEL, reg2
    )
    assert acc2 is not None
    assert reg2.valider_chaine() is True
    reg2.assert_chaine()  # ne doit pas lever
