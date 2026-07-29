"""Module de vérification du consentement et de conservation des enregistrements.

FAIL-CLOSED : toute absence ou valeur non explicitement "accorde" est refusée.
Aucune horloge ni réseau n'est utilisé.
"""

import hashlib
from typing import Any

# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------

def _construire_verdict(code: str) -> dict[str, str]:
    """Retourne un verdict dict minimal avec la clé 'code'."""
    return {"code": code}


def _ecrire_alerte_registre(registre, horodatage: str) -> None:
    """Inscrit une alerte d'absence de consentement dans le registre."""
    registre.ajouter({
        "type_entree": "alerte",
        "marqueur": "absence_consentement",
        "horodatage": horodatage,
    })


# ----------------------------------------------------------------------
# API publique
# ----------------------------------------------------------------------

def verifier_consentement(
    conversation: dict[str, Any],
    registre: Any = None,
    horodatage: str | None = None,
) -> dict[str, str]:
    """Vérifie le consentement explicite dans la conversation.

    Args:
        conversation: dict contenant au moins la clé 'consentement_enregistrement'.
        registre: instance Registre (optionnelle) où écrire une alerte en cas de refus.
        horodatage: horodatage fourni par l'appelant (obligatoire si registre est fourni).

    Returns:
        Verdict avec code 'OK' ou 'REJ-CONSENTEMENT-ABSENT'.

    Raises:
        ValueError: si registre est fourni sans horodatage.
    """
    if registre is not None and horodatage is None:
        raise ValueError("L'horodatage est obligatoire quand un registre est fourni.")

    # Récupération avec get + vérification stricte
    consentement = conversation.get("consentement_enregistrement")

    if consentement != "accorde":
        verdict = _construire_verdict("REJ-CONSENTEMENT-ABSENT")
        if registre is not None:
            _ecrire_alerte_registre(registre, horodatage)
        return verdict

    return _construire_verdict("OK")


def conserver_enregistrement(
    conversation: dict[str, Any],
    contenu: Any,
    registre: Any = None,
    horodatage: str | None = None,
) -> dict[str, str]:
    """Conserve un enregistrement si le consentement est accordé.

    Si le consentement est refusé, aucune trace du contenu n'est conservée
    et une alerte est écrite dans le registre (si fourni).

    Args:
        conversation: dict avec la clé 'consentement_enregistrement'.
        contenu: contenu à conserver.
        registre: instance Registre (optionnelle).
        horodatage: horodatage fourni par l'appelant.

    Returns:
        Verdict OK si conservation réussie, REJ-CONSENTEMENT-ABSENT sinon.

    Raises:
        ValueError: si registre est fourni sans horodatage.
    """
    # Vérification préalable
    verdict = verifier_consentement(conversation, registre=registre, horodatage=horodatage)
    if verdict["code"] != "OK":
        return verdict

    # Consentement accordé : conservation sans écriture du contenu dans le registre
    if registre is not None:
        # Métadonnées non identifiantes uniquement
        contenu_bytes = contenu.encode('utf-8') if isinstance(contenu, str) else str(contenu).encode('utf-8')
        empreinte = hashlib.sha256(contenu_bytes).hexdigest()
        entree = {
            "type_entree": "alerte",
            "marqueur": "conservation_acceptee",
            "horodatage": horodatage,
            "payload": {
                "empreinte_contenu": empreinte,
                "longueur_contenu": len(contenu_bytes),
            },
        }
        # Ajout de l'identifiant conversation si présent
        if "id" in conversation:
            entree["payload"]["conversation_id"] = conversation["id"]
        registre.ajouter(entree)

    return _construire_verdict("OK")


def rescue_autorise(conversation: dict[str, Any]) -> bool:
    """Vérifie l'opt-in explicite pour le rescue.

    Seul le booléen True est accepté comme consentement explicite.
    Toute autre valeur (chaîne, None, False, etc.) est refusée (FAIL-CLOSED).

    Args:
        conversation: dict pouvant contenir la clé 'optin_rescue'.

    Returns:
        True uniquement si l'opt-in est présent et est le booléen True.
    """
    valeur = conversation.get("optin_rescue")
    return valeur is True
