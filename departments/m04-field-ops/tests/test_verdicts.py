import m4_field_ops.verdicts as verdicts_mod
import pytest
from m4_field_ops import distances, tournees

EXPECTED_CODES_M4_LIST = [
    # Groupe 1 — verdicts ratifiés par le PRD M4 (CA-M4-01 à CA-M4-21)
    "REJ-READINESS-NON-FRANCHIE",
    "REJ-FRONTIERE-VIOLEE",
    "REJ-TRANSITION-ILLEGALE",
    "REJ-FENETRE-INVALIDE",
    "REJ-HORODATAGE-ANTERIEUR",
    "REJ-PUNCH-HORS-HEURES",
    "REJ-PUNCH-SANS-INTERVENTION",
    # Groupe 2 — invariants transversaux de validation structurelle
    "REJ-CONTRAT-INVALIDE",
    "REJ-CHAMP-MANQUANT",
    "REJ-CHAMP-VIDE",
    "REJ-ENUM-INVALIDE",
    "REJ-HORODATAGE-INVALIDE",
    # Groupe 2 bis — T1.2-f : faits CLIENT (Loi 25) hors d'un appel d'appareil
    "REJ-CHAMPS-CLIENT-HORS-APPAREIL",
    # Groupe 4 — PLAN T4.2 (POLITIQUE-geolocalisation.md) : consentement, rétention et destruction
    "REJ-CONSENTEMENT-INVALIDE",
    "REJ-RETENTION-DONNEE-MANQUANTE",
    "REJ-RETENTION-NON-ECHUE",
    "REJ-POSITION-INTROUVABLE",
    "REJ-POSITION-DETRUITE",
    # Groupe 5 — PLAN T1.4-e2 : dépôt de fichiers adressé par contenu (m4_deposer_fichier)
    "REJ-FICHIER-PARAMETRES-INVALIDES",
    "REJ-FICHIER-TROP-VOLUMINEUX",
    "REJ-FICHIER-INCOHERENT",
    "REJ-FICHIER-EMPREINTE-DISCORDANTE",
    "REJ-FICHIER-TYPE-NON-PERMIS",
    # Groupe 5 bis — PLAN T1.4-e2 : m4_completer_intervention vérifie chaque référence de fichier
    "REJ-PREUVE-FICHIER-INTROUVABLE",
    # Groupe 6 — PLAN T1.4-k : contrôle d'accès par intervention et par personne authentifiée
    "REJ-IDENTITE-APPAREIL-INVALIDE",
    "REJ-INTERVENTION-NON-ASSIGNEE",
    "REJ-IDENTITE-FOURNIE-DIFFERENTE",
    # Groupe 7 — PLAN T4.1-a : localisation des chantiers (localisation.py, R15 §3 et §4)
    "REJ-COORDONNEES-A-CONFIRMER",
    "REJ-INDEX-RQA-ABSENT",
    "REJ-LOCALISATION-DETRUITE",
    # Groupe 8 — PLAN T4.1-d : matrice de distances, tournées et cédule par tournées
    "REJ-MATRICE-FOURNISSEUR-INDISPONIBLE",
    "REJ-MATRICE-REPONSE-INVALIDE",
    "REJ-MATRICE-TRAJET-INTROUVABLE",
    "REJ-TOURNEES-SOLVEUR-ABSENT",
    "REJ-TOURNEES-DP-TROP-GRAND",
    "REJ-TOURNEES-CRENEAU-FIGE-INCOMPATIBLE",
    "REJ-TOURNEES-SOLVEUR-ECHEC",
    "REJ-TOURNEES-PLAN-INVALIDE",
    "REJ-CEDULE-RIEN-A-PLANIFIER",
    "REJ-CEDULE-INTERVENTION-NON-PLANIFIABLE",
    "REJ-CEDULE-PLAN-INTROUVABLE",
    "REJ-CEDULE-ENTREE-CHANGEE",
    # Groupe 9 — PLAN T4.12 : profil des équipes et sortie de a_planifier par la cédule
    "REJ-PROFIL-INVALIDE",
    "REJ-CEDULE-PREPARATION-NON-PRETE",
    # Groupe 10 — PLAN T4.13 : météo des créneaux (meteo.py, meteo_http.py, adaptateurs de prévisions)
    "REJ-METEO-FOURNISSEUR-INDISPONIBLE",
    "REJ-METEO-REPONSE-INVALIDE",
    "REJ-METEO-FOURNISSEUR-FERME",
    "REJ-METEO-LIEU-TROP-PRECIS",
    # Groupe 11 — M5.4 : heures individuelles, sources, révisions et validation N4.
    "REJ-IDENTITE-HUMAINE-REQUISE",
    "REJ-TECHNICIEN-INVALIDE",
    "REJ-HUMAIN-REQUIS",
    "REJ-ATTESTATION-MANQUANTE",
    "REJ-DECISION-CATEGORIE-INCOMPLETE",
    "REJ-SOURCES-CHANGEES",
    "REJ-MOTIF-CORRECTION-REQUIS",
    "REJ-VALIDATION-ABSENTE",
    "REJ-VALIDATION-PERIMEE",
    "REJ-PRECISION-MINUTE",
    "REJ-PERIODE-INVALIDE",
    "REJ-SOURCES-ABSENTES",
    "REJ-INTERVENTION-AMBIGUE",
    "REJ-POINTAGE-INCONNU",
    "REJ-SOURCE-INVALIDE",
    "REJ-TECHNICIEN-AMBIGU",
    "REJ-INTERVALLE-HORS-PERIODE",
    "REJ-POINTAGES-AMBIGUS",
    "REJ-PAUSE-INCOMPLETE",
    "REJ-PAUSE-AMBIGUE",
    "REJ-DEPLACEMENT-AMBIGU",
    "REJ-DEPLACEMENT-HORS-PERIODE",
    "REJ-INTERVENTIONS-CHEVAUCHEES",
    "REJ-REGISTRE-INVALIDE",
    "REJ-VALIDATION-INCOHERENTE",
    "REJ-APPROBATION-INCOHERENTE",
    "REJ-VALIDATION-COURANTE-CHANGE",
    # CRM-16 : refus fermés du journal SQL privé.
    "REJ-JOURNAL-IDENTITE",
    "REJ-JOURNAL-INSTANCE-NON-QUALIFIEE",
    "REJ-JOURNAL-SOURCE-TROP-VOLUMINEUSE",
    "REJ-JOURNAL-SORTIE-TROP-VOLUMINEUSE",
    "REJ-JOURNAL-SOURCE-MODIFIEE",
    "REJ-JOURNAL-SOURCE-INVALIDE",
    # CRM-16 : composition déclarée, lecture console privée.
    "REJ-COMPOSITION-IDENTITE",
    "REJ-COMPOSITION-INSTANCE-NON-QUALIFIEE",
    "REJ-COMPOSITION-SOURCE-TROP-VOLUMINEUSE",
    "REJ-COMPOSITION-SORTIE-TROP-VOLUMINEUSE",
    "REJ-COMPOSITION-SOURCE-MODIFIEE",
    "REJ-COMPOSITION-SOURCE-INVALIDE",
    "REJ-COMPOSITION-MUTATION-ABSENTE",
    "REJ-COMPOSITION-MUTATION-CONFLIT",
    "REJ-COMPOSITION-REVISION-PERIMEE",
    "REJ-COMPOSITION-IDENTITES-NON-CONFIRMEES",
    "REJ-COMPOSITION-DECLARATION-INVALIDE",
    # CRM-16 : absences signalées, lecteur console privé.
    "REJ-ABSENCE-IDENTITE",
    "REJ-ABSENCE-INSTANCE-NON-QUALIFIEE",
    "REJ-ABSENCE-SOURCE-TROP-VOLUMINEUSE",
    "REJ-ABSENCE-SORTIE-TROP-VOLUMINEUSE",
    "REJ-ABSENCE-SOURCE-MODIFIEE",
    "REJ-ABSENCE-SOURCE-INVALIDE",
    # Groupe 3 — succès
    "OK",
]


def test_codes_m4_list_epingle_exact():
    assert verdicts_mod.CODES_M4_LIST == EXPECTED_CODES_M4_LIST


def test_codes_m4_list_sans_doublon():
    assert len(verdicts_mod.CODES_M4_LIST) == len(set(verdicts_mod.CODES_M4_LIST))


def test_codes_m4_est_set_de_la_liste():
    assert isinstance(verdicts_mod.CODES_M4, set)
    assert set(verdicts_mod.CODES_M4_LIST) == verdicts_mod.CODES_M4


def test_est_verdict_vrai_pour_tous_les_codes_catalogue():
    for code in verdicts_mod.CODES_M4_LIST:
        assert verdicts_mod.est_verdict(code) is True


def test_est_verdict_faux_hors_catalogue():
    assert verdicts_mod.est_verdict("REJ-INCONNU") is False
    assert verdicts_mod.est_verdict("") is False
    assert verdicts_mod.est_verdict(None) is False


def test_construire_verdict_ok_structure_exacte():
    resultat = verdicts_mod.construire_verdict("OK")
    assert resultat == {"code": "OK", "statut": "", "detail": ""}


def test_construire_verdict_avec_statut_et_detail():
    resultat = verdicts_mod.construire_verdict("OK", statut="succès", detail="tout va bien")
    assert resultat == {"code": "OK", "statut": "succès", "detail": "tout va bien"}


def test_construire_verdict_code_inconnu_leve_exception():
    with pytest.raises(verdicts_mod.CodeVerdictInconnu):
        verdicts_mod.construire_verdict("REJ-INCONNU")


def test_code_verdict_inconnu_herite_exception():
    assert issubclass(verdicts_mod.CodeVerdictInconnu, Exception)


def test_les_codes_de_matrice_et_de_tournees_sont_au_catalogue():
    """T4.1-d : les verdicts que ``distances.py`` et ``tournees.py`` produisent sont inscrits (ils ne
    l'étaient pas quand aucun outil ne les exposait) ; un code ajouté à l'un sans l'autre est refusé ici."""
    assert set(distances.CODES_MATRICE) <= verdicts_mod.CODES_M4
    assert set(tournees.CODES_TOURNEES) <= verdicts_mod.CODES_M4
    assert len(distances.CODES_MATRICE) == 3 and len(tournees.CODES_TOURNEES) == 5
    for code in (*distances.CODES_MATRICE, *tournees.CODES_TOURNEES):
        assert verdicts_mod.construire_verdict(code, detail="x")["code"] == code
