import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import m4_field_ops.etats as etats_mod
import m4_field_ops.cedule as cedule_mod
import m4_field_ops.outbox as outbox_mod
import m4_field_ops.pointage as pointage_mod
import m4_field_ops.registre as registre_mod

# ------------------------------------------------------------------ constantes de test
H_VALIDE = "2025-06-02T08:00:00+00:00"
SEL = "sel-de-test-m4"

# Chemin RÉEL de complétion (S008) : seule l'outbox écrit vers terminee, et elle
# calcule la durée depuis les pointages — d'où ces constantes ici.
VILLE_TEST = "Montreal"
REFERENTIEL_TEST = {
    cedule_mod.tokeniser_ville(SEL, VILLE_TEST): {
        "latitude": 45.5017, "longitude": -73.5673, "rayon_km": 25.0,
    }
}
GPS_PROCHE_TEST = {"latitude": 45.5088, "longitude": -73.5878}
ATTESTATION_TEST = {"fictif": True, "appareil_id": "APP-1"}
FENETRE_TEST = {"debut": "2025-06-02T07:00:00+00:00", "fin": "2025-06-02T19:00:00+00:00"}


def _completer_par_outbox(registre, intervention_id, horodatage, ecart_detecte=False):
    """Amène une intervention à completed_pending_review/completed_verified
    par le chemin RÉEL de production (T1.1-b#2, ex-`terminee`).

    Depuis S008, `transitionner` REFUSE les deux cibles de complétion : la
    transition et l'événement WCT doivent être écrits par UNE SEULE opération
    d'ajout (CA-M4-11), donc par l'outbox. Fabriquer le maillon à la main
    validerait un chemin qui n'existe pas en production.
    """
    assert etats_mod.statut_courant(registre, intervention_id) == "en_route", (
        "ce helper part de en_route : le pointage d'arrivée l'exige"
    )
    assign = {"intervention_id": intervention_id, "technicien_id": "T1"}
    for action, horo in (("arrivee", "2025-06-02T09:00:00+00:00"),
                         ("depart", "2025-06-02T11:30:00+00:00")):
        acc, verd = pointage_mod.enregistrer_pointage(
            intervention_id, "T1", action, horo, GPS_PROCHE_TEST, ATTESTATION_TEST,
            assign, FENETRE_TEST, REFERENTIEL_TEST, VILLE_TEST, SEL, registre,
        )
        assert acc is not None, f"pointage {action} refusé : {verd}"
    acc, verd = outbox_mod.completer_intervention(
        intervention_id, horodatage, registre, ecart_detecte=ecart_detecte,
    )
    assert acc is not None, f"complétion refusée : {verd}"
    return acc
H_VALIDE2 = "2025-06-02T10:00:00+00:00"
H_VALIDE3 = "2025-06-03T08:00:00+00:00"

# ------------------------------------------------------------------ fixtures
@pytest.fixture
def contrat_valide():
    return {
        "lead_id": "L1",
        "conversation_id": "C1",
        "type_travaux": "renovation_totale",
        "ville": VILLE_TEST,
        "canal": "telephone",
        "contact": {"nom": "Dupont", "telephone": "0102030405"},
        "urgence_declaree": True,
    }

@pytest.fixture
def marqueur_valide(contrat_valide):
    return {
        "readiness_ok": True,
        "lead_id": contrat_valide["lead_id"],
        "hash_tete_registre": None,
        "horodatage": "2025-06-01T12:00:00+00:00",
        "empreinte": "ab" * 32,  # 64 hex minuscule
    }

@pytest.fixture
def registre_vide():
    return registre_mod.Registre()

# ------------------------------------------------------------------ helpers pour chemins
# Chaque entrée : état -> liste de tuples (statut_cible, motif) à jouer depuis planifiee
CHEMINS = {
    "planifiee": [],
    "en_route": [("en_route", None)],
    "sur_site": [("en_route", None), ("sur_site", None)],
    "en_revue": [("en_route", None), ("sur_site", None), ("en_revue", None)],
    "reportee": [("reportee", "meteo")],
    # completed_pending_review/completed_verified sont ABSENTS : ils ne sont
    # plus atteignables par transitionner (S008) — voir preparer_chemin.
    "annulee": [("annulee", None)],
}

def ASSIGNATION_ETATS(intervention_id):
    return {"intervention_id": intervention_id, "technicien_id": "T1"}


def preparer_chemin(registre, contrat, marqueur, etat_cible, horodatage_inscription=H_VALIDE):
    """Inscrit une intervention puis applique les transitions jusqu'à etat_cible.
    Retourne l'intervention_id et le registre (modifié sur place)."""
    accuse, verdict = etats_mod.inscrire_intervention(
        contrat, marqueur, registre, horodatage_inscription
    , SEL)
    assert accuse is not None, f"Échec d'inscription : {verdict}"
    intervention_id = accuse["intervention_id"]
    if etat_cible in ("completed_pending_review", "completed_verified"):
        # Chemin RÉEL : en_route, puis pointages, puis outbox (transitionner
        # refuse les deux cibles de complétion depuis S008).
        acc, verd = etats_mod.transitionner(
            intervention_id, "en_route", registre, "2025-06-02T08:30:00+00:00",
            assignation=ASSIGNATION_ETATS(intervention_id),
        )
        assert acc is not None, f"transition en_route refusée : {verd}"
        _completer_par_outbox(
            registre, intervention_id, "2025-06-02T12:00:00+00:00",
            ecart_detecte=(etat_cible == "completed_pending_review"),
        )
        return intervention_id, registre
    chemin = CHEMINS.get(etat_cible, [])
    horo = horodatage_inscription
    # On ajoute 1 heure à chaque étape pour éviter collision d'horodatage
    from datetime import datetime, timedelta
    base = datetime.fromisoformat(horodatage_inscription)
    for i, (statut_cible, motif) in enumerate(chemin, start=1):
        nouveau_horo = (base + timedelta(hours=i)).isoformat()
        assignation = ASSIGNATION_ETATS(intervention_id) if statut_cible == "en_route" else None
        accuse, verdict = etats_mod.transitionner(
            intervention_id, statut_cible, registre, nouveau_horo, motif=motif,
            assignation=assignation,
        )
        assert accuse is not None, f"Échec transition vers {statut_cible} : {verdict}"
    return intervention_id, registre

# ------------------------------------------------------------------ tests

# 1. Épinglage des constantes
def test_constantes_epinglage():
    assert etats_mod.ETATS == (
        "planifiee", "en_route", "sur_site", "en_revue", "reportee",
        "completed_pending_review", "completed_verified", "annulee",
    )
    assert etats_mod.ETATS_TERMINAUX == (
        "completed_pending_review", "completed_verified", "annulee",
    )
    assert etats_mod.MOTIFS_REPORT == ("client_absent", "meteo", "decision_admin")
    assert etats_mod.TRANSITIONS_AUTORISEES == (
        ("planifiee", "en_route"),
        ("planifiee", "reportee"),
        ("planifiee", "annulee"),
        ("en_route", "sur_site"),
        ("en_route", "reportee"),
        ("en_route", "annulee"),
        ("sur_site", "en_revue"),
        ("sur_site", "completed_pending_review"),
        ("sur_site", "completed_verified"),
        ("en_revue", "completed_pending_review"),
        ("en_revue", "completed_verified"),
        ("en_revue", "annulee"),
        ("en_revue", "sur_site"),
        ("en_route", "en_revue"),
        ("reportee", "planifiee"),
        ("reportee", "annulee"),
    )
    assert etats_mod.TYPE_INSCRIPTION == "intervention_inscrite"
    assert etats_mod.TYPE_TRANSITION == "transition_statut"

# 2. Cohérence structurelle de la table
def test_coherence_table():
    etats = set(etats_mod.ETATS)
    terminaux = set(etats_mod.ETATS_TERMINAUX)
    transitions = etats_mod.TRANSITIONS_AUTORISEES
    # chaque couple utilise des états de ETATS
    for a, b in transitions:
        assert a in etats, f"{a} n'est pas un état valide"
        assert b in etats, f"{b} n'est pas un état valide"
    # aucun départ depuis un état terminal
    for a, _ in transitions:
        assert a not in terminaux, f"Transition interdite depuis l'état terminal {a}"
    # aucun doublon
    assert len(set(transitions)) == len(transitions), "Doublon dans la table des transitions"

# 3. Inscription valide
def test_inscription_valide(contrat_valide, marqueur_valide, registre_vide):
    accuse, verdict = etats_mod.inscrire_intervention(
        contrat_valide, marqueur_valide, registre_vide, H_VALIDE
    , SEL)
    assert verdict is None
    # accusé contient toutes les clés
    expected_keys = {"intervention_id", "ligne_id", "statut", "empreinte_maillon", "tete_chaine", "horodatage"}
    assert set(accuse.keys()) == expected_keys
    assert accuse["statut"] == "planifiee"
    # valider_chaine() retourne True
    assert registre_vide.valider_chaine() is True
    # le maillon de tête porte TYPE_INSCRIPTION et l'intervention_id
    tete = registre_vide.lire()[-1]
    assert tete["type_entree"] == etats_mod.TYPE_INSCRIPTION
    assert tete["intervention_id"] == accuse["intervention_id"]

# 4. Loi 25 – pas de contact ni ses valeurs dans le registre
def test_inscription_loi25(contrat_valide, marqueur_valide, registre_vide):
    etats_mod.inscrire_intervention(contrat_valide, marqueur_valide, registre_vide, H_VALIDE, SEL)
    for maillon in registre_vide.lire():
        # Pas la clé 'contact'
        assert "contact" not in maillon, f"Clé 'contact' trouvée dans {maillon}"
        # Aucune valeur "Dupont" ou "0102030405" dans la sérialisation
        str_maillon = str(maillon)
        assert "Dupont" not in str_maillon, f"Valeur 'Dupont' trouvée dans {maillon}"
        assert "0102030405" not in str_maillon, f"Valeur '0102030405' trouvée dans {maillon}"

# 5. Verdict de validation d'entrée transmis, rien écrit
@pytest.mark.parametrize("modif_contrat, modif_marqueur, code_attendu", [
    ({"prix": 1}, None, "REJ-FRONTIERE-VIOLEE"),
    ({"lead_id": None}, None, "REJ-CHAMP-MANQUANT"),   # lead_id absent -> champ manquant
    (None, {"readiness_ok": False}, "REJ-READINESS-NON-FRANCHIE"),
])
def test_inscription_rejet_validation(contrat_valide, marqueur_valide, registre_vide,
                                       modif_contrat, modif_marqueur, code_attendu):
    c = contrat_valide.copy()
    if modif_contrat:
        for k, v in modif_contrat.items():
            if v is None:
                del c[k]
            else:
                c[k] = v
    m = marqueur_valide.copy()
    if modif_marqueur:
        m.update(modif_marqueur)
    taille_avant = len(registre_vide.lire())
    accuse, verdict = etats_mod.inscrire_intervention(c, m, registre_vide, H_VALIDE, SEL)
    assert accuse is None
    assert verdict["code"] == code_attendu
    assert len(registre_vide.lire()) == taille_avant

# 6. Ré-inscription : même contrat/horo -> rejet, horo différent -> accepté
def test_reinscription_meme_horodatage(contrat_valide, marqueur_valide, registre_vide):
    accuse1, _ = etats_mod.inscrire_intervention(contrat_valide, marqueur_valide, registre_vide, H_VALIDE, SEL)
    taille_avant = len(registre_vide.lire())
    accuse2, verdict2 = etats_mod.inscrire_intervention(contrat_valide, marqueur_valide, registre_vide, H_VALIDE, SEL)
    assert accuse2 is None
    assert verdict2["code"] == "REJ-TRANSITION-ILLEGALE"
    assert "déjà inscrite" in verdict2["detail"].lower()
    assert len(registre_vide.lire()) == taille_avant

def test_reinscription_horodatage_different(contrat_valide, marqueur_valide, registre_vide):
    accuse1, _ = etats_mod.inscrire_intervention(contrat_valide, marqueur_valide, registre_vide, H_VALIDE, SEL)
    accuse2, verdict2 = etats_mod.inscrire_intervention(contrat_valide, marqueur_valide, registre_vide, H_VALIDE2, SEL)
    assert accuse2 is not None
    assert accuse2["intervention_id"] != accuse1["intervention_id"]

# 7. Les 13 transitions légales acceptées
COUPLES_LEGAUX = [
    ("planifiee", "en_route"),
    ("planifiee", "reportee"),
    ("planifiee", "annulee"),
    ("en_route", "sur_site"),
    ("en_route", "reportee"),
    ("en_route", "annulee"),
    ("sur_site", "en_revue"),
    ("en_revue", "annulee"),
    ("en_revue", "sur_site"),
    ("en_route", "en_revue"),
    ("reportee", "planifiee"),
    ("reportee", "annulee"),
]

@pytest.mark.parametrize("etat_courant, etat_cible", COUPLES_LEGAUX)
def test_transition_legale(contrat_valide, marqueur_valide, registre_vide, etat_courant, etat_cible):
    # Préparer l'état courant
    i_id, reg = preparer_chemin(registre_vide, contrat_valide, marqueur_valide, etat_courant)
    statut_avant = etats_mod.statut_courant(reg, i_id)
    assert statut_avant == etat_courant
    # Effectuer la transition
    motif = "meteo" if etat_cible == "reportee" else None
    assignation = ASSIGNATION_ETATS(i_id) if etat_cible == "en_route" else None
    accuse, verdict = etats_mod.transitionner(
        i_id, etat_cible, reg, H_VALIDE3, motif=motif, assignation=assignation
    )
    assert accuse is not None, f"La transition {etat_courant}->{etat_cible} a échoué : {verdict}"
    assert accuse["statut"] == etat_cible
    assert accuse["statut_precedent"] == etat_courant
    nouveau_statut = etats_mod.statut_courant(reg, i_id)
    assert nouveau_statut == etat_cible

# 8. Balayage exhaustif des transitions illégales
COUPLES_ILLEGAUX = [
    (a, b) for a in etats_mod.ETATS for b in etats_mod.ETATS
    if (a, b) not in etats_mod.TRANSITIONS_AUTORISEES
]

@pytest.mark.parametrize("etat_courant, etat_cible", COUPLES_ILLEGAUX)
def test_transition_illegale(contrat_valide, marqueur_valide, registre_vide, etat_courant, etat_cible):
    # On ne peut pas atteindre tous les états directement (ex: terminee -> autre), mais le dictionnaire
    # CHEMINS couvre tous les états possibles comme cible. Pour les états terminaux qu'on veut
    # comme état courant, on a un chemin défini (ex: annulee: [("annulee", None)]). OK.
    i_id, reg = preparer_chemin(registre_vide, contrat_valide, marqueur_valide, etat_courant)
    taille_avant = len(reg.lire())
    motif = "meteo" if etat_cible == "reportee" else None
    accuse, verdict = etats_mod.transitionner(i_id, etat_cible, reg, H_VALIDE3, motif=motif)
    assert accuse is None
    assert verdict["code"] == "REJ-TRANSITION-ILLEGALE"
    assert len(reg.lire()) == taille_avant

# 9. Transition depuis intervention inexistante
def test_transition_inexistante(registre_vide):
    accuse, verdict = etats_mod.transitionner("i-inexistant", "en_route", registre_vide, H_VALIDE)
    assert accuse is None
    assert verdict["code"] == "REJ-TRANSITION-ILLEGALE"

# 10. statut_cible hors enum
def test_transition_statut_invalide(contrat_valide, marqueur_valide, registre_vide):
    i_id, reg = preparer_chemin(registre_vide, contrat_valide, marqueur_valide, "planifiee")
    accuse, verdict = etats_mod.transitionner(i_id, "etat_pirate", reg, H_VALIDE2)
    assert accuse is None
    assert verdict["code"] == "REJ-ENUM-INVALIDE"

# 11. Motifs
@pytest.mark.parametrize("motif", ["client_absent", "meteo", "decision_admin"])
def test_report_motif_valide(contrat_valide, marqueur_valide, registre_vide, motif):
    i_id, reg = preparer_chemin(registre_vide, contrat_valide, marqueur_valide, "planifiee")
    accuse, verdict = etats_mod.transitionner(i_id, "reportee", reg, H_VALIDE2, motif=motif)
    assert accuse is not None
    # Le maillon contient le motif
    dernier_maillon = reg.lire()[-1]
    assert dernier_maillon.get("motif") == motif

def test_report_sans_motif(contrat_valide, marqueur_valide, registre_vide):
    i_id, reg = preparer_chemin(registre_vide, contrat_valide, marqueur_valide, "planifiee")
    accuse, verdict = etats_mod.transitionner(i_id, "reportee", reg, H_VALIDE2, motif=None)
    assert accuse is None
    assert verdict["code"] == "REJ-ENUM-INVALIDE"

def test_report_motif_invalide(contrat_valide, marqueur_valide, registre_vide):
    i_id, reg = preparer_chemin(registre_vide, contrat_valide, marqueur_valide, "planifiee")
    accuse, verdict = etats_mod.transitionner(i_id, "reportee", reg, H_VALIDE2, motif="vacances")
    assert accuse is None
    assert verdict["code"] == "REJ-ENUM-INVALIDE"

def test_motif_sur_transition_non_report(contrat_valide, marqueur_valide, registre_vide):
    i_id, reg = preparer_chemin(registre_vide, contrat_valide, marqueur_valide, "planifiee")
    accuse, verdict = etats_mod.transitionner(i_id, "en_route", reg, H_VALIDE2, motif="meteo")
    assert accuse is None
    assert verdict["code"] == "REJ-ENUM-INVALIDE"

# ------------------------------------------------------------------ 11 bis. PRD §4 — assignation exigée pour en_route
def test_en_route_sans_assignation_refuse(contrat_valide, marqueur_valide, registre_vide):
    """BUG CORRIGÉ : planifiee -> en_route était acceptée SANS AUCUNE preuve
    d'assignation (PRD §4 : « conditionnée à l'assignation effective d'un
    technicien »). N'importe quel appelant pouvait donc faire « partir » un
    technicien fictif."""
    i_id, reg = preparer_chemin(registre_vide, contrat_valide, marqueur_valide, "planifiee")
    taille_avant = len(reg.lire())
    accuse, verdict = etats_mod.transitionner(i_id, "en_route", reg, H_VALIDE2)
    assert accuse is None
    assert verdict["code"] == "REJ-PUNCH-SANS-INTERVENTION"
    assert len(reg.lire()) == taille_avant
    assert etats_mod.statut_courant(reg, i_id) == "planifiee"


@pytest.mark.parametrize("assignation_bad", [
    {"intervention_id": "AUTRE", "technicien_id": "T1"},
    {"technicien_id": "T1"},
    {"intervention_id": "SERA_REMPLACE"},
    {"intervention_id": "SERA_REMPLACE", "technicien_id": ""},
    {"intervention_id": "SERA_REMPLACE", "technicien_id": 42},
    "T1",
    None,
])
def test_en_route_assignation_invalide_refuse(contrat_valide, marqueur_valide, registre_vide, assignation_bad):
    i_id, reg = preparer_chemin(registre_vide, contrat_valide, marqueur_valide, "planifiee")
    if isinstance(assignation_bad, dict) and assignation_bad.get("intervention_id") == "SERA_REMPLACE":
        assignation_bad = dict(assignation_bad)
        assignation_bad["intervention_id"] = i_id
    taille_avant = len(reg.lire())
    accuse, verdict = etats_mod.transitionner(
        i_id, "en_route", reg, H_VALIDE2, assignation=assignation_bad
    )
    assert accuse is None
    assert verdict["code"] == "REJ-PUNCH-SANS-INTERVENTION"
    assert len(reg.lire()) == taille_avant


def test_en_route_assignation_valide_persiste_technicien_id(contrat_valide, marqueur_valide, registre_vide):
    i_id, reg = preparer_chemin(registre_vide, contrat_valide, marqueur_valide, "planifiee")
    accuse, verdict = etats_mod.transitionner(
        i_id, "en_route", reg, H_VALIDE2,
        assignation={"intervention_id": i_id, "technicien_id": "T1"},
    )
    assert accuse is not None, f"transition refusée à tort : {verdict}"
    maillon = reg.lire()[-1]
    assert maillon["technicien_id"] == "T1"


def test_assignation_sur_transition_non_en_route_refuse(contrat_valide, marqueur_valide, registre_vide):
    """``assignation`` est réservé à en_route, symétrique de ``motif`` pour reportee."""
    i_id, reg = preparer_chemin(registre_vide, contrat_valide, marqueur_valide, "en_route")
    accuse, verdict = etats_mod.transitionner(
        i_id, "sur_site", reg, H_VALIDE3,
        assignation={"intervention_id": i_id, "technicien_id": "T1"},
    )
    assert accuse is None
    assert verdict["code"] == "REJ-ENUM-INVALIDE"

# 12. Horodatage invalide sur transition
def test_transition_horodatage_invalide(contrat_valide, marqueur_valide, registre_vide):
    i_id, reg = preparer_chemin(registre_vide, contrat_valide, marqueur_valide, "planifiee")
    taille_avant = len(reg.lire())
    accuse, verdict = etats_mod.transitionner(i_id, "en_route", reg, "2025-06-02T08:00:00")
    assert accuse is None
    assert verdict["code"] == "REJ-HORODATAGE-INVALIDE"
    assert len(reg.lire()) == taille_avant

# 13. statut_courant
def test_statut_courant_inexistant(registre_vide):
    assert etats_mod.statut_courant(registre_vide, "i-inexistant") is None

def test_statut_courant_apres_inscription(contrat_valide, marqueur_valide, registre_vide):
    accuse, _ = etats_mod.inscrire_intervention(contrat_valide, marqueur_valide, registre_vide, H_VALIDE, SEL)
    statut = etats_mod.statut_courant(registre_vide, accuse["intervention_id"])
    assert statut == "planifiee"

def test_statut_courant_independant(contrat_valide, marqueur_valide, registre_vide):
    # Deux interventions distinctes
    accuse1, _ = etats_mod.inscrire_intervention(contrat_valide, marqueur_valide, registre_vide, H_VALIDE, SEL)
    # Changer lead_id pour seconde intervention
    contrat2 = contrat_valide.copy()
    contrat2["lead_id"] = "L2"
    marqueur2 = marqueur_valide.copy()
    marqueur2["lead_id"] = "L2"
    accuse2, _ = etats_mod.inscrire_intervention(contrat2, marqueur2, registre_vide, H_VALIDE2, SEL)
    assert etats_mod.statut_courant(registre_vide, accuse1["intervention_id"]) == "planifiee"
    assert etats_mod.statut_courant(registre_vide, accuse2["intervention_id"]) == "planifiee"
    # Transition sur la première
    etats_mod.transitionner(
        accuse1["intervention_id"], "en_route", registre_vide, H_VALIDE3,
        assignation=ASSIGNATION_ETATS(accuse1["intervention_id"]),
    )
    assert etats_mod.statut_courant(registre_vide, accuse1["intervention_id"]) == "en_route"
    assert etats_mod.statut_courant(registre_vide, accuse2["intervention_id"]) == "planifiee"

# 14. Parcours complet, valider_chaine et assert_chaine
def test_parcours_complet_valider(contrat_valide, marqueur_valide, registre_vide):
    accuse, _ = etats_mod.inscrire_intervention(contrat_valide, marqueur_valide, registre_vide, H_VALIDE, SEL)
    i_id = accuse["intervention_id"]
    # Les transitions que la machine à états ÉCRIT elle-même.
    for cible, horo in (("en_route", "2025-06-02T08:30:00+00:00"),
                        ("reportee", "2025-06-02T08:40:00+00:00"),
                        ("planifiee", "2025-06-02T08:50:00+00:00"),
                        ("en_route", "2025-06-02T08:55:00+00:00")):
        motif = "meteo" if cible == "reportee" else None
        assignation = ASSIGNATION_ETATS(i_id) if cible == "en_route" else None
        acc, verd = etats_mod.transitionner(
            i_id, cible, registre_vide, horo, motif=motif, assignation=assignation
        )
        assert acc is not None, f"transition {cible} échouée : {verd}"
        assert acc["statut"] == cible
    # La complétion, elle, appartient à l'outbox (S008) : le parcours se termine
    # par le chemin RÉEL, ce qui prouve que les deux écrivains composent sans
    # rompre la chaîne.
    accuse_wct = _completer_par_outbox(registre_vide, i_id, "2025-06-02T12:00:00+00:00")
    assert accuse_wct["statut"] == "completed_verified"
    assert etats_mod.statut_courant(registre_vide, i_id) == "completed_verified"
    assert registre_vide.valider_chaine() is True
    # assert_chaine ne lève pas
    registre_vide.assert_chaine()   # doit passer sans exception

# ------------------------------------------------------------------ durcissements (mutations non mordues)

def test_transition_depuis_terminal_diagnostic_dedie(contrat_valide, marqueur_valide, registre_vide):
    """Le refus depuis un état TERMINAL porte son diagnostic dédié (« terminal »),
    distinct du refus générique de table. Sans ce test, retirer le contrôle
    terminal est invisible (aucune paire (terminal, x) dans la table — mutation
    mesurée non détectée) : le diagnostic actionnable serait perdu en silence."""
    i_id, reg = preparer_chemin(registre_vide, contrat_valide, marqueur_valide, "completed_verified")
    accuse, verdict = etats_mod.transitionner(i_id, "en_route", reg, H_VALIDE3)
    assert accuse is None
    assert verdict["code"] == "REJ-TRANSITION-ILLEGALE"
    assert "terminal" in verdict["detail"], (
        "le refus depuis un état terminal doit nommer sa cause, pas se rabattre "
        "sur le refus générique de table"
    )


def test_deux_leads_meme_horodatage_ids_distincts(contrat_valide, marqueur_valide, registre_vide):
    """L'intervention_id incorpore le lead_id : deux leads distincts inscrits au
    MÊME horodatage obtiennent des ids distincts (mutation « dérivation sans
    lead_id » mesurée non détectée avec des horodatages différents)."""
    accuse1, verdict1 = etats_mod.inscrire_intervention(contrat_valide, marqueur_valide, registre_vide, H_VALIDE, SEL)
    assert accuse1 is not None, f"première inscription : {verdict1}"
    contrat2 = contrat_valide.copy()
    contrat2["lead_id"] = "L2"
    marqueur2 = marqueur_valide.copy()
    marqueur2["lead_id"] = "L2"
    accuse2, verdict2 = etats_mod.inscrire_intervention(contrat2, marqueur2, registre_vide, H_VALIDE, SEL)
    assert accuse2 is not None, (
        f"deuxième lead au même horodatage rejeté à tort : {verdict2}"
    )
    assert accuse2["intervention_id"] != accuse1["intervention_id"]


def test_maillon_inscription_porte_traceabilite(contrat_valide, marqueur_valide, registre_vide):
    """Le CONTENU du maillon d'inscription est épinglé : empreintes de
    traçabilité recalculées exactement (lient le maillon aux données validées)
    et champs métier repris du contrat — sans jamais le contact (mutation
    « empreinte_contrat retirée » mesurée non détectée sans cet épinglage)."""
    import m4_field_ops.encodage as encodage_mod
    accuse, _ = etats_mod.inscrire_intervention(contrat_valide, marqueur_valide, registre_vide, H_VALIDE, SEL)
    maillon = registre_vide.lire()[-1]
    assert maillon["empreinte_contrat"] == encodage_mod.empreinte(contrat_valide)
    assert maillon["empreinte_marqueur"] == encodage_mod.empreinte(marqueur_valide)
    assert maillon["lead_id"] == contrat_valide["lead_id"]
    assert maillon["conversation_id"] == contrat_valide["conversation_id"]
    assert maillon["type_travaux"] == contrat_valide["type_travaux"]
    import m4_field_ops.cedule as cedule_mod
    assert "ville" not in maillon, "la ville en clair ne doit JAMAIS entrer au registre"
    assert maillon["ville_tokenisee"] == cedule_mod.tokeniser_ville(SEL, contrat_valide["ville"])
    assert maillon["urgence_declaree"] is contrat_valide["urgence_declaree"]
    assert maillon["statut"] == "planifiee"


def test_maillon_transition_porte_statut_precedent(contrat_valide, marqueur_valide, registre_vide):
    """Le MAILLON (vérité durable) porte le statut_precedent réel — pas
    seulement l'accusé (éphémère). Mutation mesurée : falsifier
    statut_precedent dans le maillon était invisible, l'accusé étant construit
    séparément."""
    i_id, reg = preparer_chemin(registre_vide, contrat_valide, marqueur_valide, "en_route")
    accuse, _ = etats_mod.transitionner(i_id, "sur_site", reg, H_VALIDE3)
    maillon = reg.lire()[-1]
    assert maillon["type_entree"] == etats_mod.TYPE_TRANSITION
    assert maillon["statut"] == "sur_site"
    assert maillon["statut_precedent"] == "en_route", (
        "le maillon doit consigner l'état d'origine réel de la transition"
    )

def test_aucune_ville_en_clair_dans_le_registre(contrat_valide, marqueur_valide, registre_vide):
    """Architecture §2 : l'entité Intervention porte la ville TOKENISÉE. Le
    registre étant immuable, une ville en clair y serait irrattrapable — d'où
    l'assertion globale sur TOUS les maillons, et pas seulement sur celui de
    l'inscription (défaut trouvé par le test Loi 25 de la story de pointage)."""
    accuse, verdict = etats_mod.inscrire_intervention(
        contrat_valide, marqueur_valide, registre_vide, H_VALIDE, SEL
    )
    assert accuse is not None, f"inscription refusée : {verdict}"
    etats_mod.transitionner(
        accuse["intervention_id"], "en_route", registre_vide, H_VALIDE2,
        assignation=ASSIGNATION_ETATS(accuse["intervention_id"]),
    )
    for maillon in registre_vide.lire():
        assert contrat_valide["ville"] not in str(maillon), (
            f"ville en clair trouvée dans un maillon : {maillon}"
        )


def test_sel_de_tokenisation_obligatoire(contrat_valide, marqueur_valide, registre_vide):
    """Sans sel, l'empreinte d'un nom de ville est attaquable par dictionnaire
    (quelques milliers de villes) : le sel est donc EXIGÉ, pas optionnel."""
    for sel_invalide in ("", None, 42):
        accuse, verdict = etats_mod.inscrire_intervention(
            contrat_valide, marqueur_valide, registre_vide, H_VALIDE, sel_invalide
        )
        assert accuse is None
        assert verdict["code"] == "REJ-CONTRAT-INVALIDE"
        assert registre_vide.taille() == 0, "aucune écriture sur sel invalide"


def test_sels_differents_donnent_des_tokens_differents(contrat_valide, marqueur_valide):
    """Le token dépend du sel : deux déploiements aux sels distincts ne
    produisent pas le même token pour la même ville (pas de table arc-en-ciel
    partagée entre installations)."""
    tokens = []
    for sel in ("sel-A", "sel-B"):
        reg = registre_mod.Registre()
        accuse, _ = etats_mod.inscrire_intervention(
            contrat_valide, marqueur_valide, reg, H_VALIDE, sel
        )
        assert accuse is not None
        tokens.append(reg.lire()[-1]["ville_tokenisee"])
    assert tokens[0] != tokens[1]

def test_en_route_vers_en_revue_est_legale(contrat_valide, marqueur_valide, registre_vide):
    """AMENDEMENT #145 : une anomalie de pointage à l'arrivée doit pouvoir router
    l'intervention en revue. Sans cette entrée, CA-M4-08 était insatisfiable pour
    l'arrivée — passer sur_site aurait menti sur la présence (le PRD la conditionne
    à un fix GPS COHÉRENT), en_revue violait la table, et ne rien faire laissait
    l'anomalie sans arbitrage."""
    accuse, verdict = etats_mod.inscrire_intervention(
        contrat_valide, marqueur_valide, registre_vide, H_VALIDE, SEL
    )
    assert accuse is not None, f"inscription refusée : {verdict}"
    i_id = accuse["intervention_id"]
    acc, v = etats_mod.transitionner(
        i_id, "en_route", registre_vide, H_VALIDE2, assignation=ASSIGNATION_ETATS(i_id)
    )
    assert acc is not None, f"transition en_route refusée : {v}"
    acc, v = etats_mod.transitionner(i_id, "en_revue", registre_vide, H_VALIDE3)
    assert acc is not None, f"en_route -> en_revue doit être légale : {v}"
    assert acc["statut"] == "en_revue"
    assert acc["statut_precedent"] == "en_route"
    # le chemin de sortie ratifié reste ouvert : l'arbitrage peut relancer le travail
    acc, v = etats_mod.transitionner(i_id, "sur_site", registre_vide, "2025-06-02T14:00:00+00:00")
    assert acc is not None, f"en_revue -> sur_site doit rester légale : {v}"
    assert registre_vide.valider_chaine() is True


# ------------------------------------------------------------------ T1.1-b#1 : devis_id (M3)
def test_devis_id_omis_reste_null(contrat_valide, marqueur_valide, registre_vide):
    """Omis, devis_id reste None — rétrocompatibilité avec les appels à 5
    arguments positionnels (les 451 tests d'origine)."""
    accuse, verdict = etats_mod.inscrire_intervention(
        contrat_valide, marqueur_valide, registre_vide, H_VALIDE, SEL
    )
    assert accuse is not None, f"inscription refusée : {verdict}"
    assert registre_vide.lire()[-1]["devis_id"] is None


def test_devis_id_fourni_porte_sur_le_maillon(contrat_valide, marqueur_valide, registre_vide):
    accuse, verdict = etats_mod.inscrire_intervention(
        contrat_valide, marqueur_valide, registre_vide, H_VALIDE, SEL, devis_id="DEVIS-42",
    )
    assert accuse is not None, f"inscription refusée : {verdict}"
    assert registre_vide.lire()[-1]["devis_id"] == "DEVIS-42"
    # jamais recopié dans l'accusé : l'accusé reste épinglé (test #3 ci-dessus)
    assert "devis_id" not in accuse


@pytest.mark.parametrize("devis_id_bad, code_attendu", [
    ("", "REJ-CHAMP-VIDE"),
    (42, "REJ-CONTRAT-INVALIDE"),
    (["D1"], "REJ-CONTRAT-INVALIDE"),
])
def test_devis_id_invalide_refuse(contrat_valide, marqueur_valide, registre_vide, devis_id_bad, code_attendu):
    taille_avant = registre_vide.taille()
    accuse, verdict = etats_mod.inscrire_intervention(
        contrat_valide, marqueur_valide, registre_vide, H_VALIDE, SEL, devis_id=devis_id_bad,
    )
    assert accuse is None
    assert verdict["code"] == code_attendu
    assert registre_vide.taille() == taille_avant


# ------------------------------------------------------------------ T1.1-b#4 : m4_lister_interventions
def test_lister_interventions_vide(registre_vide):
    assert etats_mod.lister_interventions(registre_vide) == []


def test_lister_interventions_toutes_sans_filtre(contrat_valide, marqueur_valide, registre_vide):
    acc1, _ = etats_mod.inscrire_intervention(
        contrat_valide, marqueur_valide, registre_vide, H_VALIDE, SEL, devis_id="D1",
    )
    contrat2 = contrat_valide.copy()
    contrat2["lead_id"] = "L2"
    marqueur2 = marqueur_valide.copy()
    marqueur2["lead_id"] = "L2"
    acc2, _ = etats_mod.inscrire_intervention(contrat2, marqueur2, registre_vide, H_VALIDE2, SEL)

    resultat = etats_mod.lister_interventions(registre_vide)
    assert [e["intervention_id"] for e in resultat] == sorted(
        [acc1["intervention_id"], acc2["intervention_id"]]
    )
    par_id = {e["intervention_id"]: e for e in resultat}
    assert par_id[acc1["intervention_id"]]["statut"] == "planifiee"
    assert par_id[acc1["intervention_id"]]["lead_id"] == "L1"
    assert par_id[acc1["intervention_id"]]["type_travaux"] == contrat_valide["type_travaux"]
    assert par_id[acc1["intervention_id"]]["devis_id"] == "D1"
    assert par_id[acc2["intervention_id"]]["devis_id"] is None
    # aucune donnée de contact
    for entree in resultat:
        assert "contact" not in entree
        for cle_interdite in ("nom", "telephone", "courriel"):
            assert cle_interdite not in entree


def test_lister_interventions_filtre_par_statut(contrat_valide, marqueur_valide, registre_vide):
    acc1, _ = etats_mod.inscrire_intervention(contrat_valide, marqueur_valide, registre_vide, H_VALIDE, SEL)
    contrat2 = contrat_valide.copy()
    contrat2["lead_id"] = "L2"
    marqueur2 = marqueur_valide.copy()
    marqueur2["lead_id"] = "L2"
    acc2, _ = etats_mod.inscrire_intervention(contrat2, marqueur2, registre_vide, H_VALIDE2, SEL)
    etats_mod.transitionner(
        acc2["intervention_id"], "en_route", registre_vide, H_VALIDE3,
        assignation=ASSIGNATION_ETATS(acc2["intervention_id"]),
    )

    planifiees = etats_mod.lister_interventions(registre_vide, statut="planifiee")
    assert [e["intervention_id"] for e in planifiees] == [acc1["intervention_id"]]

    en_route = etats_mod.lister_interventions(registre_vide, statut="en_route")
    assert [e["intervention_id"] for e in en_route] == [acc2["intervention_id"]]

    assert etats_mod.lister_interventions(registre_vide, statut="annulee") == []


def test_lister_interventions_statut_inconnu_leve_valueerror(registre_vide):
    with pytest.raises(ValueError):
        etats_mod.lister_interventions(registre_vide, statut="statut_pirate")


# ------------------------------------------------------------------ T1.4-e2 : technicien_assigne/fenetre_planifiee
def test_lister_interventions_technicien_assigne_seulement_apres_en_route(
    contrat_valide, marqueur_valide, registre_vide,
):
    """`technicien_assigne` vient UNIQUEMENT du registre (la transition en_route, seul endroit où
    ce fait est écrit) : null avant, le technicien de l'assignation effective après. Jamais
    inventé — voir docstring de `lister_interventions`."""
    acc1, _ = etats_mod.inscrire_intervention(contrat_valide, marqueur_valide, registre_vide, H_VALIDE, SEL)
    contrat2 = contrat_valide.copy()
    contrat2["lead_id"] = "L2"
    marqueur2 = marqueur_valide.copy()
    marqueur2["lead_id"] = "L2"
    acc2, _ = etats_mod.inscrire_intervention(contrat2, marqueur2, registre_vide, H_VALIDE2, SEL)
    etats_mod.transitionner(
        acc2["intervention_id"], "en_route", registre_vide, H_VALIDE3,
        assignation=ASSIGNATION_ETATS(acc2["intervention_id"]),
    )

    par_id = {e["intervention_id"]: e for e in etats_mod.lister_interventions(registre_vide)}
    assert par_id[acc1["intervention_id"]]["technicien_assigne"] is None
    assert par_id[acc2["intervention_id"]]["technicien_assigne"] == "T1"
    # Jamais inventée aujourd'hui : le registre ne porte aucune fenêtre, pour aucune intervention.
    assert par_id[acc1["intervention_id"]]["fenetre_planifiee"] is None
    assert par_id[acc2["intervention_id"]]["fenetre_planifiee"] is None


def test_lister_interventions_technicien_assigne_reste_apres_report(
    contrat_valide, marqueur_valide, registre_vide,
):
    """Fait HISTORIQUE, pas un statut d'assignation courante : un report après en_route laisse
    `technicien_assigne` tel quel (à lire aux côtés de `statut`, ici `reportee`)."""
    acc, _ = etats_mod.inscrire_intervention(contrat_valide, marqueur_valide, registre_vide, H_VALIDE, SEL)
    i_id = acc["intervention_id"]
    etats_mod.transitionner(
        i_id, "en_route", registre_vide, H_VALIDE2, assignation=ASSIGNATION_ETATS(i_id),
    )
    etats_mod.transitionner(i_id, "reportee", registre_vide, H_VALIDE3, motif="meteo")

    [entree] = etats_mod.lister_interventions(registre_vide)
    assert entree["statut"] == "reportee"
    assert entree["technicien_assigne"] == "T1"

