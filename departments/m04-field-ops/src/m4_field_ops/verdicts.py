"""Catalogue des verdicts M4 et utilitaires de validation."""

CODES_M4_LIST = [
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
    "REJ-CONSENTEMENT-INVALIDE",       # §4 : enregistrement de consentement mal formé.
    "REJ-RETENTION-DONNEE-MANQUANTE",  # §5 : fin de contrat inconnue, fail-closed, aucune purge.
    "REJ-RETENTION-NON-ECHUE",         # §5 : échéance (12 mois) pas encore atteinte.
    "REJ-POSITION-INTROUVABLE",        # §7 : aucun fix GPS chiffré à cette ligne du registre.
    "REJ-POSITION-DETRUITE",           # §5 : clé détruite par une purge antérieure (succès de la
                                        # destruction, pas une anomalie).
    # Groupe 5 — PLAN T1.4-e2 : dépôt de fichiers adressé par contenu (m4_deposer_fichier).
    "REJ-FICHIER-PARAMETRES-INVALIDES",
    "REJ-FICHIER-TROP-VOLUMINEUX",
    "REJ-FICHIER-INCOHERENT",
    "REJ-FICHIER-EMPREINTE-DISCORDANTE",
    "REJ-FICHIER-TYPE-NON-PERMIS",
    # Groupe 5 bis — PLAN T1.4-e2 : m4_completer_intervention vérifie chaque référence de fichier.
    "REJ-PREUVE-FICHIER-INTROUVABLE",
    # Groupe 6 — PLAN T1.4-k : contrôle d'accès par intervention et par personne authentifiée.
    "REJ-IDENTITE-APPAREIL-INVALIDE",         # l'identité du jeton n'est pas confirmée par la base.
    "REJ-INTERVENTION-NON-ASSIGNEE",          # un employé agit sur l'intervention d'un autre.
    "REJ-IDENTITE-FOURNIE-DIFFERENTE",         # technicien_id ou accede_par != personne authentifiée.
    # Groupe 7 — PLAN T4.1-a : localisation des chantiers (localisation.py, R15 §3 et §4)
    "REJ-COORDONNEES-A-CONFIRMER",   # « coordonnées manquantes : à confirmer » : jamais une position inventée.
    "REJ-INDEX-RQA-ABSENT",          # l'index local du RQA n'est pas importé : dit quoi faire, pas « introuvable ».
    "REJ-LOCALISATION-DETRUITE",     # clé du chantier détruite : la position n'est plus lisible (voulu).
    # Groupe 8 — PLAN T4.1-d : matrice de distances (distances.py), tournées (tournees.py) et cédule par
    # tournées (cedule_tournees.py). Les huit premiers étaient déjà produits par T4.1-b et T4.1-c ;
    # les quatre suivants sont propres aux deux outils m4_proposer_cedule et m4_appliquer_cedule.
    "REJ-MATRICE-FOURNISSEUR-INDISPONIBLE",       # le fournisseur de routage ne répond pas (repli marqué).
    "REJ-MATRICE-REPONSE-INVALIDE",               # sa réponse n'est pas une matrice d'entiers carrée.
    "REJ-MATRICE-TRAJET-INTROUVABLE",             # aucune route entre deux points : donnée à corriger.
    "REJ-TOURNEES-SOLVEUR-ABSENT",                # « installer l'extra tournees ».
    "REJ-TOURNEES-DP-TROP-GRAND",                 # le repli exact n'accepte pas autant de chantiers.
    "REJ-TOURNEES-CRENEAU-FIGE-INCOMPATIBLE",     # un créneau confirmé au client ne peut être tenu.
    "REJ-TOURNEES-SOLVEUR-ECHEC",                 # le solveur a levé une exception ou rendu un plan absurde.
    "REJ-TOURNEES-PLAN-INVALIDE",                 # le plan échoue à verifier_plan : jamais appliqué.
    "REJ-CEDULE-RIEN-A-PLANIFIER",                # aucune intervention planifiable, ou un plan sans visite.
    "REJ-CEDULE-INTERVENTION-NON-PLANIFIABLE",    # intervention inconnue ou plus au statut planifiee.
    "REJ-CEDULE-PLAN-INTROUVABLE",                # aucun plan proposé sous cet identifiant.
    "REJ-CEDULE-ENTREE-CHANGEE",                  # l'état a bougé depuis la proposition : proposer de nouveau.
    # Groupe 9 — PLAN T4.12 : profil des équipes de l'entreprise et sortie de a_planifier par la cédule.
    "REJ-PROFIL-INVALIDE",                        # le profil des équipes est illisible ou invalide : jamais « absent ».
    "REJ-CEDULE-PREPARATION-NON-PRETE",           # une intervention a_planifier n'est pas prête : dit ce qui manque.
    # Groupe 10 — PLAN T4.13 : météo des créneaux (meteo.py, meteo_http.py, adaptateurs de prévisions).
    "REJ-METEO-FOURNISSEUR-INDISPONIBLE",         # le fournisseur ne répond pas : créneau « inconnu », jamais « ok ».
    "REJ-METEO-REPONSE-INVALIDE",                 # sa réponse n'a pas la forme du port : rien n'est jugé dessus.
    "REJ-METEO-FOURNISSEUR-FERME",                # aucun fournisseur ouvert, ou ouvert sans droit (forfait gratuit).
    "REJ-METEO-LIEU-TROP-PRECIS",                 # un lieu de chantier plus fin que le dixième de degré : jamais envoyé
    # Groupe 11 — préparation M5.4 : aperçu et validation N4 privée des heures individuelles.
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
    "REJ-ABSENCE-MUTATION-ABSENTE",
    "REJ-ABSENCE-MUTATION-CONFLIT",
    "REJ-ABSENCE-REVISION-PERIMEE",
    "REJ-ABSENCE-CIBLE-NON-CONFIRMEE",
    "REJ-ABSENCE-DECLARATION-INVALIDE",
    # Groupe 3 — succès
    "OK",
]

CODES_M4 = set(CODES_M4_LIST)


class CodeVerdictInconnu(Exception):
    """Le code verdict fourni n'appartient pas au catalogue CODES_M4."""


def est_verdict(code):
    """Retourne True si `code` est un verdict du catalogue M4."""
    return code in CODES_M4


def construire_verdict(code, statut="", detail=""):
    """Construit un dictionnaire verdict si `code` est catalogue.

    Lève CodeVerdictInconnu sinon.
    """
    if not est_verdict(code):
        raise CodeVerdictInconnu(f"Code verdict invalide : {code!r}")
    return {"code": code, "statut": statut, "detail": detail}


__all__ = [
    "CODES_M4_LIST",
    "CODES_M4",
    "CodeVerdictInconnu",
    "est_verdict",
    "construire_verdict",
]
