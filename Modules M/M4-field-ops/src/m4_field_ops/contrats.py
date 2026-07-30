"""Validation structurelle d'un contrat et de son marqueur de readiness."""
from typing import Any, Optional, Tuple

from . import frontieres
from . import horodatage
from . import verdicts

CHAMPS_CONTRAT_GELE = (
    "lead_id", "conversation_id", "type_travaux", "ville", "canal",
    "contact", "urgence_declaree",
)
TYPES_TRAVAUX = (
    "renovation_totale", "extension", "ravalement", "isolation_thermique", "autre",
)
CANAUX = ("telephone", "courriel", "formulaire", "texte")
CLES_CONTACT = ("nom", "telephone", "courriel")

__all__ = [
    "valider_structure",
    "valider_marqueur_readiness",
    "valider_entree",
]


def valider_structure(contrat: Any) -> Tuple[bool, str]:
    """Valide la structure d'un contrat selon les règles M4.

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

    # 3. Aucune clé étrangère hors des 7
    if set(contrat.keys()) != set(CHAMPS_CONTRAT_GELE):
        return False, "REJ-CONTRAT-INVALIDE"

    # 4. Validation des chaînes non vides (lead_id, conversation_id, ville)
    for champ_str in ("lead_id", "conversation_id", "ville"):
        valeur = contrat[champ_str]
        if not isinstance(valeur, str):
            return False, "REJ-CONTRAT-INVALIDE"
        if valeur == "":
            return False, "REJ-CHAMP-VIDE"

    # 5. Enumérations
    if contrat["type_travaux"] not in TYPES_TRAVAUX:
        return False, "REJ-ENUM-INVALIDE"
    if contrat["canal"] not in CANAUX:
        return False, "REJ-ENUM-INVALIDE"

    # 6. Contact
    contact = contrat["contact"]
    if not isinstance(contact, dict):
        return False, "REJ-CONTRAT-INVALIDE"
    # Clés permises
    if not set(contact.keys()).issubset(set(CLES_CONTACT)):
        return False, "REJ-CONTRAT-INVALIDE"
    # Au moins une valeur non vide parmi les trois (nom, telephone, courriel)
    # si les trois sont absentes ou vides -> REJ-CHAMP-VIDE
    # Égalité stricte avec "" (pas de strip) : sémantique IDENTIQUE au contrat
    # gelé amont — une valeur blanche non vide y est acceptée, elle l'est donc ici.
    vals = [contact.get(cle, "") for cle in CLES_CONTACT]
    if all(not isinstance(v, str) or v == "" for v in vals):
        return False, "REJ-CHAMP-VIDE"

    # 7. urgence_declaree doit être un booléen strict (True/False, pas int)
    if type(contrat["urgence_declaree"]) is not bool:
        return False, "REJ-CONTRAT-INVALIDE"

    # 8. Succès
    return True, ""


def valider_marqueur_readiness(marqueur: Any, lead_id: str) -> Tuple[bool, str]:
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


def valider_entree(contrat: Any, marqueur: Any) -> Tuple[bool, Optional[dict]]:
    """Validation complète d'une entrée (contrat + marqueur).

    L'ordre est déterminé par la priorité des verdicts : toute intervention dont
    le contrat contient un champ interdit est rejetée avec le verdict de frontière,
    avant tout autre contrôle structurel.
    """
    # 1. Frontières (contrat) -> verdict dédié
    ok_front, verdict_front = frontieres.verifier_frontieres(contrat)
    if not ok_front:
        return False, verdict_front  # verdict déjà construit

    # 2. Structure du contrat
    ok_struct, code_struct = valider_structure(contrat)
    if not ok_struct:
        return False, verdicts.construire_verdict(code_struct)

    # 3. Marqueur de readiness
    ok_read, code_read = valider_marqueur_readiness(marqueur, contrat["lead_id"])
    if not ok_read:
        return False, verdicts.construire_verdict(code_read)

    # 4. Succès
    return True, None
