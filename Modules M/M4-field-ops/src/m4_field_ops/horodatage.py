"""Validation stricte des horodatages selon le contrat M4-S003."""

from datetime import datetime

__all__ = ["valider_horodatage"]


def valider_horodatage(texte):
    """Retourne `texte` inchangé s'il est un horodatage ISO 8601 avec fuseau.

    Accepte le séparateur espace documenté par datetime.fromisoformat.
    Lève ValueError("REJ-HORODATAGE-INVALIDE") from None dans tous les autres cas.
    """
    if not isinstance(texte, str):
        raise ValueError("REJ-HORODATAGE-INVALIDE") from None
    try:
        dt = datetime.fromisoformat(texte)
    except (TypeError, ValueError):
        raise ValueError("REJ-HORODATAGE-INVALIDE") from None
    if dt.tzinfo is None:
        raise ValueError("REJ-HORODATAGE-INVALIDE") from None
    return texte
