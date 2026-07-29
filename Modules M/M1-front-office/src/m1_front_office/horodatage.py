from datetime import datetime


def valider_horodatage(iso: str) -> bool:
    """Valide une chaîne ISO-8601 avec fuseau horaire obligatoire.
    Retourne True si valide, lève ValueError sinon.
    """
    if not isinstance(iso, str):
        raise ValueError("REJ-HORODATAGE-INVALIDE: la valeur doit être une chaîne")
    try:
        dt = datetime.fromisoformat(iso)
    except (ValueError, TypeError, OverflowError):
        raise ValueError("REJ-HORODATAGE-INVALIDE: format ISO-8601 invalide") from None
    if dt.tzinfo is None:
        raise ValueError("REJ-HORODATAGE-INVALIDE: fuseau horaire manquant")
    return True
