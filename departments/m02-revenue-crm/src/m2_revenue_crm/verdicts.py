"""Catalogue des identifiants de verdicts stables du module M2."""

__all__ = [
    "CODES_M2_LIST",
    "CODES_M2",
    "CodeVerdictInconnu",
    "est_verdict",
    "construire_verdict",
]


class CodeVerdictInconnu(Exception):
    """
    Levée par construire_verdict lorsque le code demandé ne figure pas dans
    le catalogue M2. Hérite d'Exception pour rester attrapable par les tests
    existants qui font pytest.raises(Exception).
    """


# Identifiants stables du catalogue M2 (épinglés par des tests existants :
# contenu et ordre inchangés)
CODES_M2_LIST = [
    # Groupe 1 — catalogue d'origine (M2-S001), ordre épinglé par les tests
    "REJ-FRONTIERE-VIOLEE",
    "REJ-TRANSITION-ILLEGALE",
    "REJ-OWNER-ABSENT",
    "REJ-ACTION-ABSENTE",
    "REJ-DEVIS-ABSENT",
    "REJ-MOTIF-ABSENT",
    "REJ-ADAPTATEUR-INDISPONIBLE",
    "OK",
    # Groupe 2 — repris du catalogue voisin, invariant transversal
    "REJ-CONVERSATION-CLOSE",
    "REJ-CONTRAT-INVALIDE",
    "REJ-CHAMP-MANQUANT",
    "REJ-CHAMP-VIDE",
    "REJ-ENUM-INVALIDE",
    # Groupe 3 — addition M2, addendum architecture
    "REJ-LEAD-DEJA-INGERE",
    # Groupe 4 — émis par les modules du présent arbre
    "REJ-FIXTURE-NON-FICTIVE",
    "REJ-HORODATAGE-INVALIDE",
    # Groupe 5 — PLAN T1.4-k2 : identité authentifiée d'un appel d'appareil. Les deux premiers reprennent
    # tels quels les identifiants de M4 et de M5 (même faute, même nom) ; les deux suivants sont propres
    # à M2 (docs/architecture/ROLES.md).
    "REJ-IDENTITE-APPAREIL-INVALIDE",
    "REJ-IDENTITE-FOURNIE-DIFFERENTE",
    "REJ-LEAD-NON-ASSIGNE",
    "REJ-OWNER-INCONNU",
    # Groupe 6 — PLAN T4.6 : liste des leads et segments (M2.11). Un segment sans la donnée qui le calcule
    # est refusé avec ce qui manque (jamais une liste vide qui se lirait « aucun lead ») ; un décalage ou
    # une limite de page invalide dit quoi corriger.
    "REJ-SEGMENT-NON-CALCULABLE",
    "REJ-PAGINATION-INVALIDE",
    # Groupe 7 — PLAN T1.4-m : réassignation d'un lead (décision humaine, motif obligatoire) et republication du
    # fait m2.lead_assigne. REJ-OWNER-ABSENT, REJ-OWNER-INCONNU, REJ-MOTIF-ABSENT et REJ-HORODATAGE-INVALIDE
    # servent aussi, avec leur détail propre : aucun doublon de sens n'est ajouté.
    "REJ-HUMAIN-REQUIS",
    "REJ-MOTIF-INVALIDE",
    "REJ-LEAD-INCONNU",
    "REJ-PROPRIETAIRE-INCHANGE",
    "REJ-BUS-INDISPONIBLE",
    # Groupe 8 — PLAN T4.9 : relances dues, consentement de contact et fréquence limitée (M2.7, M2.13). Une fréquence
    # non configurée dit quoi configurer ; une relance non due, ou trop proche de la précédente, dit pourquoi et
    # quand ; un message sans consentement actif (absent) ou après un STOP (retiré) est refusé, l'appel reste permis ;
    # une saisie de consentement mal formée dit ce qui manque. REJ-SEGMENT-NON-CALCULABLE, REJ-ENUM-INVALIDE,
    # REJ-PAGINATION-INVALIDE, REJ-HORODATAGE-INVALIDE, REJ-HUMAIN-REQUIS, REJ-LEAD-INCONNU, REJ-LEAD-NON-ASSIGNE et
    # REJ-BUS-INDISPONIBLE servent aussi, avec leur détail propre : aucun doublon de sens n'est ajouté.
    "REJ-RELANCES-A-CONFIGURER",
    "REJ-RELANCE-NON-DUE",
    "REJ-RELANCE-TROP-PROCHE",
    "REJ-CONSENTEMENT-ABSENT",
    "REJ-CONSENTEMENT-RETIRE",
    "REJ-CONSENTEMENT-INVALIDE",
]
CODES_M2 = set(CODES_M2_LIST)


def est_verdict(code):
    """Retourne True si le code fait partie du catalogue M2."""
    return code in CODES_M2


def construire_verdict(code, statut="", detail=""):
    """
    Construit un verdict dictionnaire si le code est reconnu.
    Lève CodeVerdictInconnu dans le cas contraire.
    """
    if not est_verdict(code):
        raise CodeVerdictInconnu(f"Code verdict invalide : {code!r}")
    return {"code": code, "statut": statut, "detail": detail}
