# M2-S003 — Validation structurelle du contrat LeadQualifie
# Respecte la liste blanche stricte et l'ordre de contrôle imposé.

CHAMPS_CONTRAT_GELE = (
    "lead_id",
    "conversation_id",
    "type_travaux",
    "ville",
    "canal",
    "contact",
    "urgence_declaree",
)

TYPES_TRAVAUX = (
    "renovation_totale",
    "extension",
    "ravalement",
    "isolation_thermique",
    "autre",
)

CANAUX = (
    "telephone",
    "courriel",
    "formulaire",
    "texte",
)

CLES_CONTACT = ("nom", "telephone", "courriel")


def valider_structure(contrat) -> tuple[bool, str]:
    """Valide la structure d’un contrat LeadQualifie selon la spec M2-S003.

    Ordre d’évaluation (la première faute rencontrée détermine le code) :
        1. type de l’entrée (doit être un dict)
        2. champs obligatoires manquants
        3. champs inconnus (hors des 7 autorisés)
        4. types et valeurs des champs individuels

    Retourne (True, "") si le contrat est conforme,
    sinon (False, code_verdict) avec un code du catalogue.
    """
    # 1. L’entrée doit être un dictionnaire.
    if not isinstance(contrat, dict):
        return False, "REJ-CONTRAT-INVALIDE"

    # 2. Champs manquants.
    for champ in CHAMPS_CONTRAT_GELE:
        if champ not in contrat:
            return False, "REJ-CHAMP-MANQUANT"

    # 3. Champs inconnus.
    for champ in contrat:
        if champ not in CHAMPS_CONTRAT_GELE:
            return False, "REJ-CONTRAT-INVALIDE"

    # 4. Types et valeurs.
    # lead_id, conversation_id, ville : str non vide.
    for champ in ("lead_id", "conversation_id", "ville"):
        valeur = contrat[champ]
        if not isinstance(valeur, str):
            return False, "REJ-CONTRAT-INVALIDE"
        if valeur == "":
            return False, "REJ-CHAMP-VIDE"

    # type_travaux : énumération fermée.
    if contrat["type_travaux"] not in TYPES_TRAVAUX:
        return False, "REJ-ENUM-INVALIDE"

    # canal : énumération fermée.
    if contrat["canal"] not in CANAUX:
        return False, "REJ-ENUM-INVALIDE"

    # contact : dict autorisant uniquement les clés de CLES_CONTACT.
    contact = contrat["contact"]
    if not isinstance(contact, dict):
        return False, "REJ-CONTRAT-INVALIDE"
    for cle in contact:
        if cle not in CLES_CONTACT:
            return False, "REJ-CONTRAT-INVALIDE"

    # Au moins une des trois valeurs de contact doit être une chaîne non vide.
    non_vide = False
    for cle in CLES_CONTACT:
        if cle in contact:
            val = contact[cle]
            if isinstance(val, str) and val != "":
                non_vide = True
                break
    if not non_vide:
        return False, "REJ-CHAMP-VIDE"

    # urgence_declaree : booléen strict (True/False, pas 1/0).
    if type(contrat["urgence_declaree"]) is not bool:
        return False, "REJ-CONTRAT-INVALIDE"

    return True, ""
