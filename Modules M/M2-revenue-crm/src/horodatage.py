from datetime import datetime

__all__ = ["valider_horodatage"]


def valider_horodatage(texte):
    """
    Valide un horodatage ISO-8601 avec fuseau horaire.
    Retourne la chaîne si valide, lève ValueError sinon.
    Lève ValueError avec le préfixe REJ-HORODATAGE-INVALIDE, sans jamais laisser fuir
    un message brut de datetime (from None).
    """
    if not isinstance(texte, str):
        raise ValueError("REJ-HORODATAGE-INVALIDE") from None
    try:
        dt = datetime.fromisoformat(texte)
    except (ValueError, TypeError):
        raise ValueError("REJ-HORODATAGE-INVALIDE") from None
    if not isinstance(dt, datetime) or dt.tzinfo is None:
        raise ValueError("REJ-HORODATAGE-INVALIDE") from None
    return texte
