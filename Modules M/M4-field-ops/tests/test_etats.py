import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import m4_field_ops.etats as etats_mod
import m4_field_ops.registre as registre_mod

# ------------------------------------------------------------------ constantes de test
H_VALIDE = "2025-06-02T08:00:00+00:00"
H_VALIDE2 = "2025-06-02T10:00:00+00:00"
H_VALIDE3 = "2025-06-03T08:00:00+00:00"

# ------------------------------------------------------------------ fixtures
@pytest.fixture
def contrat_valide():
    return {
        "lead_id": "L1",
        "conversation_id": "C1",
        "type_travaux": "renovation_totale",
        "ville": "Paris",
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
    "terminee": [("en_route", None), ("sur_site", None), ("terminee", None)],
    "annulee": [("annulee", None)],
}

def preparer_chemin(registre, contrat, marqueur, etat_cible, horodatage_inscription=H_VALIDE):
    """Inscrit une intervention puis applique les transitions jusqu'à etat_cible.
    Retourne l'intervention_id et le registre (modifié sur place)."""
    accuse, verdict = etats_mod.inscrire_intervention(
        contrat, marqueur, registre, horodatage_inscription
    )
    assert accuse is not None, f"Échec d'inscription : {verdict}"
    intervention_id = accuse["intervention_id"]
    chemin = CHEMINS.get(etat_cible, [])
    horo = horodatage_inscription
    # On ajoute 1 heure à chaque étape pour éviter collision d'horodatage
    from datetime import datetime, timedelta
    base = datetime.fromisoformat(horodatage_inscription)
    for i, (statut_cible, motif) in enumerate(chemin, start=1):
        nouveau_horo = (base + timedelta(hours=i)).isoformat()
        accuse, verdict = etats_mod.transitionner(
            intervention_id, statut_cible, registre, nouveau_horo, motif=motif
        )
        assert accuse is not None, f"Échec transition vers {statut_cible} : {verdict}"
    return intervention_id, registre

# ------------------------------------------------------------------ tests

# 1. Épinglage des constantes
def test_constantes_epinglage():
    assert etats_mod.ETATS == (
        "planifiee", "en_route", "sur_site", "en_revue", "reportee", "terminee", "annulee"
    )
    assert etats_mod.ETATS_TERMINAUX == ("terminee", "annulee")
    assert etats_mod.MOTIFS_REPORT == ("client_absent", "meteo", "decision_admin")
    assert etats_mod.TRANSITIONS_AUTORISEES == (
        ("planifiee", "en_route"),
        ("planifiee", "reportee"),
        ("planifiee", "annulee"),
        ("en_route", "sur_site"),
        ("en_route", "reportee"),
        ("en_route", "annulee"),
        ("sur_site", "en_revue"),
        ("sur_site", "terminee"),
        ("en_revue", "terminee"),
        ("en_revue", "annulee"),
        ("en_revue", "sur_site"),
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
    )
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
    etats_mod.inscrire_intervention(contrat_valide, marqueur_valide, registre_vide, H_VALIDE)
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
    accuse, verdict = etats_mod.inscrire_intervention(c, m, registre_vide, H_VALIDE)
    assert accuse is None
    assert verdict["code"] == code_attendu
    assert len(registre_vide.lire()) == taille_avant

# 6. Ré-inscription : même contrat/horo -> rejet, horo différent -> accepté
def test_reinscription_meme_horodatage(contrat_valide, marqueur_valide, registre_vide):
    accuse1, _ = etats_mod.inscrire_intervention(contrat_valide, marqueur_valide, registre_vide, H_VALIDE)
    taille_avant = len(registre_vide.lire())
    accuse2, verdict2 = etats_mod.inscrire_intervention(contrat_valide, marqueur_valide, registre_vide, H_VALIDE)
    assert accuse2 is None
    assert verdict2["code"] == "REJ-TRANSITION-ILLEGALE"
    assert "déjà inscrite" in verdict2["detail"].lower()
    assert len(registre_vide.lire()) == taille_avant

def test_reinscription_horodatage_different(contrat_valide, marqueur_valide, registre_vide):
    accuse1, _ = etats_mod.inscrire_intervention(contrat_valide, marqueur_valide, registre_vide, H_VALIDE)
    accuse2, verdict2 = etats_mod.inscrire_intervention(contrat_valide, marqueur_valide, registre_vide, H_VALIDE2)
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
    ("sur_site", "terminee"),
    ("en_revue", "terminee"),
    ("en_revue", "annulee"),
    ("en_revue", "sur_site"),
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
    accuse, verdict = etats_mod.transitionner(i_id, etat_cible, reg, H_VALIDE3, motif=motif)
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
    accuse, _ = etats_mod.inscrire_intervention(contrat_valide, marqueur_valide, registre_vide, H_VALIDE)
    statut = etats_mod.statut_courant(registre_vide, accuse["intervention_id"])
    assert statut == "planifiee"

def test_statut_courant_independant(contrat_valide, marqueur_valide, registre_vide):
    # Deux interventions distinctes
    accuse1, _ = etats_mod.inscrire_intervention(contrat_valide, marqueur_valide, registre_vide, H_VALIDE)
    # Changer lead_id pour seconde intervention
    contrat2 = contrat_valide.copy()
    contrat2["lead_id"] = "L2"
    marqueur2 = marqueur_valide.copy()
    marqueur2["lead_id"] = "L2"
    accuse2, _ = etats_mod.inscrire_intervention(contrat2, marqueur2, registre_vide, H_VALIDE2)
    assert etats_mod.statut_courant(registre_vide, accuse1["intervention_id"]) == "planifiee"
    assert etats_mod.statut_courant(registre_vide, accuse2["intervention_id"]) == "planifiee"
    # Transition sur la première
    etats_mod.transitionner(accuse1["intervention_id"], "en_route", registre_vide, H_VALIDE3)
    assert etats_mod.statut_courant(registre_vide, accuse1["intervention_id"]) == "en_route"
    assert etats_mod.statut_courant(registre_vide, accuse2["intervention_id"]) == "planifiee"

# 14. Parcours complet, valider_chaine et assert_chaine
def test_parcours_complet_valider(contrat_valide, marqueur_valide, registre_vide):
    accuse, _ = etats_mod.inscrire_intervention(contrat_valide, marqueur_valide, registre_vide, H_VALIDE)
    i_id = accuse["intervention_id"]
    for cible, horo in (("en_route", "2025-06-02T09:00:00+00:00"),
                        ("sur_site", "2025-06-02T10:00:00+00:00"),
                        ("terminee", "2025-06-02T11:00:00+00:00")):
        acc, verd = etats_mod.transitionner(i_id, cible, registre_vide, horo)
        assert acc is not None, f"transition {cible} échouée : {verd}"
        assert acc["statut"] == cible
    assert registre_vide.valider_chaine() is True
    # assert_chaine ne lève pas
    registre_vide.assert_chaine()   # doit passer sans exception

# ------------------------------------------------------------------ durcissements (mutations non mordues)

def test_transition_depuis_terminal_diagnostic_dedie(contrat_valide, marqueur_valide, registre_vide):
    """Le refus depuis un état TERMINAL porte son diagnostic dédié (« terminal »),
    distinct du refus générique de table. Sans ce test, retirer le contrôle
    terminal est invisible (aucune paire (terminal, x) dans la table — mutation
    mesurée non détectée) : le diagnostic actionnable serait perdu en silence."""
    i_id, reg = preparer_chemin(registre_vide, contrat_valide, marqueur_valide, "terminee")
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
    accuse1, verdict1 = etats_mod.inscrire_intervention(contrat_valide, marqueur_valide, registre_vide, H_VALIDE)
    assert accuse1 is not None, f"première inscription : {verdict1}"
    contrat2 = contrat_valide.copy()
    contrat2["lead_id"] = "L2"
    marqueur2 = marqueur_valide.copy()
    marqueur2["lead_id"] = "L2"
    accuse2, verdict2 = etats_mod.inscrire_intervention(contrat2, marqueur2, registre_vide, H_VALIDE)
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
    accuse, _ = etats_mod.inscrire_intervention(contrat_valide, marqueur_valide, registre_vide, H_VALIDE)
    maillon = registre_vide.lire()[-1]
    assert maillon["empreinte_contrat"] == encodage_mod.empreinte(contrat_valide)
    assert maillon["empreinte_marqueur"] == encodage_mod.empreinte(marqueur_valide)
    assert maillon["lead_id"] == contrat_valide["lead_id"]
    assert maillon["conversation_id"] == contrat_valide["conversation_id"]
    assert maillon["type_travaux"] == contrat_valide["type_travaux"]
    assert maillon["ville"] == contrat_valide["ville"]
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

