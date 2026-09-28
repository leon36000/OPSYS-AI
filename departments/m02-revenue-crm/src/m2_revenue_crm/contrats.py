# M2-S003 — Validation structurelle du contrat LeadQualifie
# Respecte la liste blanche stricte et l'ordre de contrôle imposé.
#
# Deux versions du contrat sont acceptées (PLAN T0.13) : la v1 GELÉE (`type_travaux`, énuméré
# fermé) et la v2 (`service`, code de la taxonomie du socle). La version est EXPLICITE : un lead
# qui porte `schema_version` est validé en v2 ; sans ce champ (le contrat v1 n'en a pas), en v1.
# Elle n'est jamais devinée à partir des autres champs.

from opsys import taxonomie

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

# Contrat LeadQualifie v2 (`departments/m01-front-office/contracts/m1-lead-qualifie.v2.yaml`) :
# `service` remplace `type_travaux` ; `schema_version` porte la version. Les trois clés
# optionnelles ci-dessous (CHAMPS_CONTRAT_OPTIONNELS) sont communes aux deux versions.
VERSION_CONTRAT_V2 = 2
CHAMPS_CONTRAT_GELE_V2 = (
    "schema_version",
    "lead_id",
    "conversation_id",
    "service",
    "ville",
    "canal",
    "contact",
    "urgence_declaree",
)

CANAUX = (
    "telephone",
    "courriel",
    "formulaire",
    "texte",
)

CLES_CONTACT = ("nom", "telephone", "courriel")

# PLAN T2.2 (lead structuré ; audit du front office et docs/research/R6-m1-m2.md) :
# DEFINITION-PRODUIT §6/§7 M1/M2 disent que M2 « reçoit de M7 (source, UTM, campagne) », mais le
# contrat GELÉ v1 (les 7 CHAMPS_CONTRAT_GELE ci-dessus, `departments/m01-front-office/
# contracts/m1-lead-qualifie.v1.yaml`) ne les porte pas et ne doit PAS être modifié en place (P5,
# bannière du fichier : « évolution = v2 »). Le correctif ici est côté RÉCEPTION seulement : M2
# valide indépendamment la même forme que le front office et ACCEPTE ces trois champs s'ils sont
# fournis — sans exiger que M1 les envoie déjà. Tous les trois restent OPTIONNELS : leur ABSENCE
# n'est jamais une erreur ni une valeur par défaut inventée (AGENTS.md, fail-closed) ; leur
# PRÉSENCE est validée comme toute autre donnée du contrat, avec la même discipline stricte.
CHAMPS_CONTRAT_OPTIONNELS = ("source", "utm", "campagne")

# Sous-clés fermées de `utm`, alignées sur la convention déjà en vigueur côté M7
# (`departments/m07-marketing/contracts/utm-convention.v1.yaml` : utm_source, utm_medium,
# utm_campaign obligatoires pour M7 ; utm_content optionnel). M2 ne revalide PAS les énumérations
# propres à M7 (utm_source/utm_medium fermés côté M7) : M2 n'est pas propriétaire de cette
# taxonomie, seulement du champ d'accueil — voir docs §8 « qui est source de vérité de quoi ».
CLES_UTM = ("utm_source", "utm_medium", "utm_campaign", "utm_content")


def _champ_optionnel_invalide(contrat) -> str | None:
    """Valide `source`/`campagne`/`utm` SI PRÉSENTS. Retourne None si conforme (y compris
    absents), sinon un code verdict. Chaîne fournie mais vide = même refus qu'une chaîne
    absente serait une VALEUR par défaut inventée en silence : mieux vaut le dire (fail-closed,
    cohérent avec le traitement de ville/lead_id/conversation_id ci-dessous)."""
    for champ in ("source", "campagne"):
        if champ not in contrat:
            continue
        valeur = contrat[champ]
        if not isinstance(valeur, str) or valeur == "":
            return "REJ-CONTRAT-INVALIDE"
    if "utm" not in contrat:
        return None
    utm = contrat["utm"]
    if not isinstance(utm, dict) or not utm:
        return "REJ-CONTRAT-INVALIDE"
    for cle, valeur in utm.items():
        if cle not in CLES_UTM:
            return "REJ-CONTRAT-INVALIDE"
        if not isinstance(valeur, str) or valeur == "":
            return "REJ-CONTRAT-INVALIDE"
    return None


def _identifiants_invalides(contrat) -> str | None:
    """lead_id, conversation_id, ville : chaînes non vides (communs aux versions v1 et v2)."""
    for champ in ("lead_id", "conversation_id", "ville"):
        valeur = contrat[champ]
        if not isinstance(valeur, str):
            return "REJ-CONTRAT-INVALIDE"
        if valeur == "":
            return "REJ-CHAMP-VIDE"
    return None


def _canal_contact_urgence_invalides(contrat) -> str | None:
    """canal, contact, urgence_declaree (communs aux versions v1 et v2). None si conformes."""
    # canal : énumération fermée.
    if contrat["canal"] not in CANAUX:
        return "REJ-ENUM-INVALIDE"

    # contact : dict autorisant uniquement les clés de CLES_CONTACT.
    contact = contrat["contact"]
    if not isinstance(contact, dict):
        return "REJ-CONTRAT-INVALIDE"
    for cle in contact:
        if cle not in CLES_CONTACT:
            return "REJ-CONTRAT-INVALIDE"

    # Au moins une des trois valeurs de contact doit être une chaîne non vide.
    non_vide = False
    for cle in CLES_CONTACT:
        if cle in contact:
            val = contact[cle]
            if isinstance(val, str) and val != "":
                non_vide = True
                break
    if not non_vide:
        return "REJ-CHAMP-VIDE"

    # urgence_declaree : booléen strict (True/False, pas 1/0).
    if type(contrat["urgence_declaree"]) is not bool:
        return "REJ-CONTRAT-INVALIDE"
    return None


def _valider_structure_v1(contrat) -> tuple[bool, str]:
    """Valide la structure d’un contrat LeadQualifie v1 (gelé) selon la spec M2-S003.

    Ordre d’évaluation (la première faute rencontrée détermine le code) :
        1. type de l’entrée (doit être un dict)
        2. champs obligatoires manquants
        3. champs inconnus (hors des 7 gelés + les 3 optionnels de structuration, PLAN T2.2)
        4. types et valeurs des champs individuels (obligatoires)
        5. types et valeurs de source/utm/campagne SI PRÉSENTS (PLAN T2.2, jamais requis)

    Retourne (True, "") si le contrat est conforme,
    sinon (False, code_verdict) avec un code du catalogue.
    """
    # 1. L’entrée doit être un dictionnaire.
    if not isinstance(contrat, dict):
        return False, "REJ-CONTRAT-INVALIDE"

    # 2. Champs manquants (parmi les 7 gelés seulement : les 3 optionnels n'ont rien à vérifier ici).
    for champ in CHAMPS_CONTRAT_GELE:
        if champ not in contrat:
            return False, "REJ-CHAMP-MANQUANT"

    # 3. Champs inconnus (hors des 7 gelés ET des 3 optionnels).
    for champ in contrat:
        if champ not in CHAMPS_CONTRAT_GELE and champ not in CHAMPS_CONTRAT_OPTIONNELS:
            return False, "REJ-CONTRAT-INVALIDE"

    # 4. Types et valeurs.
    # lead_id, conversation_id, ville : str non vide.
    code_identifiants = _identifiants_invalides(contrat)
    if code_identifiants is not None:
        return False, code_identifiants

    # type_travaux : énumération fermée.
    if contrat["type_travaux"] not in TYPES_TRAVAUX:
        return False, "REJ-ENUM-INVALIDE"

    # canal, contact, urgence_declaree : mêmes contrôles qu'en v2.
    code_commun = _canal_contact_urgence_invalides(contrat)
    if code_commun is not None:
        return False, code_commun

    # 5. source/utm/campagne (PLAN T2.2) : optionnels, validés seulement s'ils sont fournis.
    code_optionnel = _champ_optionnel_invalide(contrat)
    if code_optionnel is not None:
        return False, code_optionnel

    return True, ""


def _valider_structure_v2(contrat) -> tuple[bool, str, str]:
    """Valide un contrat LeadQualifie v2 (`schema_version` == 2, `service` de la taxonomie du socle).

    Même ordre d'évaluation qu'en v1 : version, champs manquants, champs inconnus (dont l'ancien
    `type_travaux`), types et valeurs, puis source/utm/campagne si présents. Retourne
    `(True, "", "")` ou `(False, code_verdict, detail)` ; le détail dit quoi corriger ou configurer
    (service hors du profil d'entreprise).
    """
    # 1. Version explicite : l'entier 2 exactement (ni True, ni "2", ni 2.0).
    if type(contrat["schema_version"]) is not int or contrat["schema_version"] != VERSION_CONTRAT_V2:
        return False, "REJ-CONTRAT-INVALIDE", f"schema_version doit valoir {VERSION_CONTRAT_V2}"

    # 2. Champs manquants.
    for champ in CHAMPS_CONTRAT_GELE_V2:
        if champ not in contrat:
            return False, "REJ-CHAMP-MANQUANT", f"champ manquant : {champ}"

    # 3. Champs inconnus (hors des huit de la v2 ET des trois optionnels).
    for champ in contrat:
        if champ not in CHAMPS_CONTRAT_GELE_V2 and champ not in CHAMPS_CONTRAT_OPTIONNELS:
            return False, "REJ-CONTRAT-INVALIDE", f"champ inconnu en v2 : {champ}"

    # 4. Types et valeurs.
    code_identifiants = _identifiants_invalides(contrat)
    if code_identifiants is not None:
        return False, code_identifiants, ""

    # service : chaîne non vide, code d'un service déclaré par le profil d'entreprise de l'instance.
    if not isinstance(contrat["service"], str):
        return False, "REJ-CONTRAT-INVALIDE", "service doit être une chaîne"
    if contrat["service"] == "":
        return False, "REJ-CHAMP-VIDE", "service ne doit pas être vide"
    _, verdict_service = taxonomie.valider_service(contrat["service"])
    if verdict_service is not None:
        return False, "REJ-ENUM-INVALIDE", f"{verdict_service['code']} : {verdict_service['detail']}"

    code_commun = _canal_contact_urgence_invalides(contrat)
    if code_commun is not None:
        return False, code_commun, ""

    # 5. source/utm/campagne : optionnels, validés seulement s'ils sont fournis.
    code_optionnel = _champ_optionnel_invalide(contrat)
    if code_optionnel is not None:
        return False, code_optionnel, ""

    return True, "", ""


def valider_structure_avec_detail(contrat) -> tuple[bool, str, str]:
    """`(ok, code_verdict, detail)` : valide le contrat dans la version qu'il DÉCLARE.

    `schema_version` présent : v2. Absent : v1 (le contrat gelé v1 n'a pas ce champ). Le détail est
    vide pour la v1 (le code suffit) ; en v2 il dit quoi corriger, dont la configuration du profil
    d'entreprise quand le service n'y est pas déclaré.
    """
    if isinstance(contrat, dict) and "schema_version" in contrat:
        return _valider_structure_v2(contrat)
    ok, code = _valider_structure_v1(contrat)
    return ok, code, ""


def valider_structure(contrat) -> tuple[bool, str]:
    """Valide la structure d'un contrat LeadQualifie, v1 (gelé) ou v2 selon sa version déclarée.

    Retourne (True, "") si le contrat est conforme, sinon (False, code_verdict) avec un code du
    catalogue. Voir `valider_structure_avec_detail` pour le détail du refus.
    """
    ok, code, _detail = valider_structure_avec_detail(contrat)
    return ok, code
