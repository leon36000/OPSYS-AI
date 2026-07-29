import hashlib
import json
from uuid import UUID
from datetime import date, datetime, time
from decimal import Decimal

__all__ = ["encoder_canonique", "empreinte"]


def _normaliser(obj):
    """Normalise récursivement un objet Python vers une forme canonique stable ET injective."""
    if isinstance(obj, dict):
        items = []
        for k, v in obj.items():
            items.append((_normaliser(k), _normaliser(v)))
        items.sort(key=lambda pair: json.dumps(pair[0], separators=(",", ":"), ensure_ascii=True))
        return ["__dict__", [[k, v] for k, v in items]]
    if isinstance(obj, set):
        elements = [_normaliser(e) for e in obj]
        elements.sort(key=lambda e: json.dumps(e, separators=(",", ":"), ensure_ascii=True))
        return ["__set__", elements]
    if isinstance(obj, frozenset):
        elements = [_normaliser(e) for e in obj]
        elements.sort(key=lambda e: json.dumps(e, separators=(",", ":"), ensure_ascii=True))
        return ["__frozenset__", elements]
    if isinstance(obj, list):
        return ["__list__", [_normaliser(e) for e in obj]]
    if isinstance(obj, tuple):
        return ["__tuple__", [_normaliser(e) for e in obj]]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    if isinstance(obj, Decimal):
        return ["__decimal__", str(obj)]
    if isinstance(obj, datetime):
        return ["__datetime__", obj.isoformat()]
    if isinstance(obj, date):
        return ["__date__", obj.isoformat()]
    if isinstance(obj, time):
        return ["__time__", obj.isoformat()]
    if isinstance(obj, UUID):
        return ["__uuid__", str(obj)]
    if isinstance(obj, bytes):
        return ["__bytes__", obj.hex()]
    if isinstance(obj, bytearray):
        return ["__bytearray__", bytes(obj).hex()]
    if isinstance(obj, complex):
        return ["__complex__", [repr(obj.real), repr(obj.imag)]]
    raise TypeError(
        f"Type non supporté : {type(obj).__name__}. "
        f"Types supportés : dict, set, frozenset, list, tuple, str, int, float, bool, None, "
        f"Decimal, datetime, date, time, UUID, bytes, bytearray, complex. "
        f"L'appelant doit sérialiser la valeur avant de l'incorporer."
    )


def encoder_canonique(*valeurs):
    """
    Encode les arguments de manière injective (préfixage de longueur) et déterministe
    (normalisation récursive). Retourne une empreinte SHA256 hex.
    """
    segments = []
    for v in valeurs:
        norm = _normaliser(v)
        serial = json.dumps(norm, separators=(",", ":"), ensure_ascii=True)
        segments.append(f"{len(serial)}:{serial}")
    payload = "".join(segments)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def empreinte(valeur):
    """Empreinte d'une valeur unique (commodité)."""
    return encoder_canonique(valeur)
