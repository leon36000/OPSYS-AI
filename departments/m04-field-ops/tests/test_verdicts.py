import m4_field_ops.verdicts as verdicts_mod
import pytest

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
