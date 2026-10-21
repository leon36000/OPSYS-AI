"""Validation structurelle d'un contrat et de son marqueur de readiness.

Deux versions du LeadQualifie sont acceptées (PLAN T0.13-b), comme chez M2 : la v1 GELÉE
(`type_travaux`, énuméré fermé, copie ci-dessous) et la v2 (`service`, code de la taxonomie du socle,
`opsys.taxonomie`). La version est EXPLICITE : un lead qui porte `schema_version` est validé en v2 ; sans
ce champ (le contrat v1 n'en a pas), en v1. Elle n'est jamais devinée à partir des autres champs : un lead
sans version qui porte `service`, ou un lead v2 qui porte `type_travaux`, est refusé.
"""
from typing import Any

from opsys import taxonomie

from . import frontieres, horodatage, verdicts

CHAMPS_CONTRAT_GELE = (
    "lead_id", "conversation_id", "type_travaux", "ville", "canal",
    "contact", "urgence_declaree",
)
TYPES_TRAVAUX = (
    "renovation_totale", "extension", "ravalement", "isolation_thermique", "autre",
)
# Contrat LeadQualifie v2 (`departments/m01-front-office/contracts/m1-lead-qualifie.v2.yaml`, gelé) :
# `service` remplace `type_travaux` ; `schema_version` porte la version. Copie de celle de M2
# (`CHAMPS_CONTRAT_GELE_V2`) : `tests/test_taxonomie_derive.py` la confronte au fichier gelé.
VERSION_CONTRAT_V2 = 2
CHAMPS_CONTRAT_GELE_V2 = (
    "schema_version", "lead_id", "conversation_id", "service", "ville", "canal",
    "contact", "urgence_declaree",
)
CANAUX = ("telephone", "courriel", "formulaire", "texte")
CLES_CONTACT = ("nom", "telephone", "courriel")
# Clés OPTIONNELLES du LeadQualifie (PLAN T2.2), copiées de M2 (CHAMPS_CONTRAT_OPTIONNELS et
# CLES_UTM de departments/m02-revenue-crm/src/m2_revenue_crm/contrats.py) : M2 les accepte si
# elles sont fournies ; M4 les accepte à l'identique (même forme exigée, même code de refus), sans
# jamais les exiger ni leur inventer de valeur. Le contrat gelé reste celui des sept clés.
CHAMPS_CONTRAT_OPTIONNELS = ("source", "utm", "campagne")
CLES_UTM = ("utm_source", "utm_medium", "utm_campaign", "utm_content")

__all__ = [
    "valider_structure",
    "valider_structure_avec_detail",
    "valider_marqueur_readiness",
    "valider_entree",
]


def _identifiants_invalides(contrat: dict) -> str | None:
    """lead_id, conversation_id, ville : chaînes non vides (communs aux versions v1 et v2)."""
    for champ_str in ("lead_id", "conversation_id", "ville"):
        valeur = contrat[champ_str]
        if not isinstance(valeur, str):
            return "REJ-CONTRAT-INVALIDE"
        if valeur == "":
            return "REJ-CHAMP-VIDE"
    return None


def _canal_contact_urgence_invalides(contrat: dict) -> str | None:
    """canal, contact, urgence_declaree (communs aux versions v1 et v2). None si conformes."""
    if contrat["canal"] not in CANAUX:
        return "REJ-ENUM-INVALIDE"

    # Contact
    contact = contrat["contact"]
    if not isinstance(contact, dict):
        return "REJ-CONTRAT-INVALIDE"
    # Clés permises
    if not set(contact.keys()).issubset(set(CLES_CONTACT)):
        return "REJ-CONTRAT-INVALIDE"
    # Au moins une valeur non vide parmi les trois (nom, telephone, courriel)
    # si les trois sont absentes ou vides -> REJ-CHAMP-VIDE
    # Égalité stricte avec "" (pas de strip) : sémantique IDENTIQUE au contrat
    # gelé amont — une valeur blanche non vide y est acceptée, elle l'est donc ici.
    vals = [contact.get(cle, "") for cle in CLES_CONTACT]
    if all(not isinstance(v, str) or v == "" for v in vals):
        return "REJ-CHAMP-VIDE"

    # urgence_declaree doit être un booléen strict (True/False, pas int)
    if type(contrat["urgence_declaree"]) is not bool:
        return "REJ-CONTRAT-INVALIDE"
    return None


def _valider_structure_v1(contrat: Any) -> tuple[bool, str]:
    """Valide la structure d'un contrat v1 (gelé) selon les règles M4.

    Retourne (True, "") si valide, sinon (False, code_verdict).
    Ordre des vérifications épinglé : première faute rencontrée.
    """
    # 1. Type dict requis
    if not isinstance(contrat, dict):
        return False, "REJ-CONTRAT-INVALIDE"

    # 2. Champs obligatoires présents dans l'ordre de CHAMPS_CONTRAT_GELE
    for champ in CHAMPS_CONTRAT_GELE:
        if champ not in contrat:
            return False, "REJ-CHAMP-MANQUANT"

    # 3. Aucune clé étrangère hors des 7 gelées et des 3 optionnelles (PLAN T2.2)
    if not set(contrat.keys()) <= set(CHAMPS_CONTRAT_GELE) | set(CHAMPS_CONTRAT_OPTIONNELS):
        return False, "REJ-CONTRAT-INVALIDE"

    # 4. Validation des chaînes non vides (lead_id, conversation_id, ville)
    code_identifiants = _identifiants_invalides(contrat)
    if code_identifiants is not None:
        return False, code_identifiants

    # 5. Enumérations (type_travaux, puis canal), 6. contact, 7. urgence_declaree
    if contrat["type_travaux"] not in TYPES_TRAVAUX:
        return False, "REJ-ENUM-INVALIDE"
    code_commun = _canal_contact_urgence_invalides(contrat)
    if code_commun is not None:
        return False, code_commun

    # 8. source/utm/campagne (PLAN T2.2) : validés seulement s'ils sont fournis, comme chez M2
    if _champ_optionnel_invalide(contrat):
        return False, "REJ-CONTRAT-INVALIDE"

    # 9. Succès
    return True, ""


def _valider_structure_v2(contrat: dict) -> tuple[bool, str, str]:
    """Valide un contrat v2 (`schema_version` == 2, `service` de la taxonomie du socle).

    Même ordre qu'en v1 : version, champs manquants, champs inconnus (dont l'ancien `type_travaux`),
    types et valeurs, puis source/utm/campagne si présents. Retourne `(True, "", "")` ou `(False,
    code_verdict, detail)` ; le détail dit quoi corriger ou configurer (service hors du profil
    d'entreprise de l'instance : `opsys.taxonomie`, jamais un repli sur une valeur par défaut).
    """
    # 1. Version explicite : l'entier 2 exactement (ni True, ni "2", ni 2.0).
    version = contrat["schema_version"]
    if type(version) is not int or version != VERSION_CONTRAT_V2:
        return False, "REJ-CONTRAT-INVALIDE", f"schema_version doit valoir {VERSION_CONTRAT_V2}"

    # 2. Champs obligatoires présents.
    for champ in CHAMPS_CONTRAT_GELE_V2:
        if champ not in contrat:
            return False, "REJ-CHAMP-MANQUANT", f"champ manquant : {champ}"

    # 3. Aucune clé étrangère hors des 8 de la v2 et des 3 optionnelles.
    for champ in contrat:
        if champ not in CHAMPS_CONTRAT_GELE_V2 and champ not in CHAMPS_CONTRAT_OPTIONNELS:
            return False, "REJ-CONTRAT-INVALIDE", f"champ inconnu en v2 : {champ}"

    # 4. Chaînes non vides, puis service : code d'un service DÉCLARÉ par le profil de l'instance.
    code_identifiants = _identifiants_invalides(contrat)
    if code_identifiants is not None:
        return False, code_identifiants, ""
    if not isinstance(contrat["service"], str):
        return False, "REJ-CONTRAT-INVALIDE", "service doit être une chaîne"
    if contrat["service"] == "":
        return False, "REJ-CHAMP-VIDE", "service ne doit pas être vide"
    _, verdict_service = taxonomie.valider_service(contrat["service"])
    if verdict_service is not None:
        return False, "REJ-ENUM-INVALIDE", f"{verdict_service['code']} : {verdict_service['detail']}"

    # 5. canal, contact, urgence_declaree.
    code_commun = _canal_contact_urgence_invalides(contrat)
    if code_commun is not None:
        return False, code_commun, ""

    # 6. source/utm/campagne : validés seulement s'ils sont fournis.
    if _champ_optionnel_invalide(contrat):
        return False, "REJ-CONTRAT-INVALIDE", ""

    return True, "", ""


def valider_structure_avec_detail(contrat: Any) -> tuple[bool, str, str]:
    """`(ok, code_verdict, detail)` : valide le contrat dans la version qu'il DÉCLARE.

    `schema_version` présent : v2. Absent : v1 (le contrat gelé v1 n'a pas ce champ). Le détail est
    vide pour la v1 (le code suffit) ; en v2 il dit quoi corriger, dont la configuration du profil
    d'entreprise quand le service n'y est pas déclaré.
    """
    if isinstance(contrat, dict) and "schema_version" in contrat:
        return _valider_structure_v2(contrat)
    ok, code = _valider_structure_v1(contrat)
    return ok, code, ""


def valider_structure(contrat: Any) -> tuple[bool, str]:
    """Valide la structure d'un LeadQualifie, v1 (gelé) ou v2 selon sa version déclarée.

    Retourne (True, "") si valide, sinon (False, code_verdict). Voir `valider_structure_avec_detail`
    pour le détail du refus.
    """
    ok, code, _detail = valider_structure_avec_detail(contrat)
    return ok, code


def _champ_optionnel_invalide(contrat: dict) -> bool:
    """Vrai si une clé optionnelle FOURNIE n'a pas la forme exigée par M2 : `source` et
    `campagne` chaînes non vides ; `utm` dictionnaire non vide, sous-clés dans CLES_UTM,
    valeurs chaînes non vides. Une clé absente n'est jamais une faute."""
    for champ in ("source", "campagne"):
        if champ in contrat and (not isinstance(contrat[champ], str) or contrat[champ] == ""):
            return True
    if "utm" not in contrat:
        return False
    utm = contrat["utm"]
    if not isinstance(utm, dict) or not utm:
        return True
    return any(
        cle not in CLES_UTM or not isinstance(valeur, str) or valeur == ""
        for cle, valeur in utm.items()
    )


def valider_marqueur_readiness(marqueur: Any, lead_id: str) -> tuple[bool, str]:
    """Validation structurelle du marqueur de readiness.

    Limitation : cette validation est purement structurelle. Le module ne possède pas
    le registre amont ; la vérification cryptographique de bout en bout appartient à
    la couche d'intégration qui dispose des deux arbres.
    """
    # 1. dict
    if not isinstance(marqueur, dict):
        return False, "REJ-READINESS-NON-FRANCHIE"

    # 2. Clés exactes
    if set(marqueur.keys()) != {"readiness_ok", "lead_id", "hash_tete_registre",
                                "horodatage", "empreinte"}:
        return False, "REJ-READINESS-NON-FRANCHIE"

    # 3. readiness_ok strictement True (utilisation de l'identité)
    if marqueur["readiness_ok"] is not True:
        return False, "REJ-READINESS-NON-FRANCHIE"

    # 4. lead_id correspond
    if marqueur["lead_id"] != lead_id:
        return False, "REJ-READINESS-NON-FRANCHIE"

    # 5. horodatage valide
    try:
        horodatage.valider_horodatage(marqueur["horodatage"])
    except ValueError:
        return False, "REJ-HORODATAGE-INVALIDE"

    # 6. empreinte : str len 64 hex minuscules
    emp = marqueur["empreinte"]
    if not isinstance(emp, str) or len(emp) != 64 or \
       not all(c in "0123456789abcdef" for c in emp):
        return False, "REJ-READINESS-NON-FRANCHIE"

    # 7. hash_tete_registre : None ou str hex 64 minuscules
    htr = marqueur["hash_tete_registre"]
    if htr is not None and (
        not isinstance(htr, str) or len(htr) != 64
        or not all(car in "0123456789abcdef" for car in htr)
    ):
        return False, "REJ-READINESS-NON-FRANCHIE"

    # 8. Succès
    return True, ""


def valider_entree(contrat: Any, marqueur: Any) -> tuple[bool, dict | None]:
    """Validation complète d'une entrée (contrat + marqueur).

    L'ordre est déterminé par la priorité des verdicts : toute intervention dont
    le contrat contient un champ interdit est rejetée avec le verdict de frontière,
    avant tout autre contrôle structurel.
    """
    # 1. Frontières (contrat) -> verdict dédié
    ok_front, verdict_front = frontieres.verifier_frontieres(contrat)
    if not ok_front:
        return False, verdict_front  # verdict déjà construit

    # 2. Structure du contrat (v1 ou v2 selon la version qu'il déclare)
    ok_struct, code_struct, detail_struct = valider_structure_avec_detail(contrat)
    if not ok_struct:
        return False, verdicts.construire_verdict(code_struct, detail=detail_struct)

    # 3. Marqueur de readiness
    ok_read, code_read = valider_marqueur_readiness(marqueur, contrat["lead_id"])
    if not ok_read:
        return False, verdicts.construire_verdict(code_read)

    # 4. Succès
    return True, None
