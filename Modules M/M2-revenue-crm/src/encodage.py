import hashlib
import json

__all__ = ["encoder_canonique", "empreinte"]


def _normaliser(obj):
    """Normalise récursivement un objet Python vers une forme canonique stable ET injective."""
    if isinstance(obj, dict):
        # Trier les clés en fonction de leur représentation JSON normalisée
        items = []
        for k, v in obj.items():
            items.append((_normaliser(k), _normaliser(v)))
        items.sort(key=lambda pair: json.dumps(pair[0], separators=(",", ":"), ensure_ascii=True))
        # Balise de type explicite pour garantir l'injectivité
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
    raise TypeError(
        f"Type non supporté : {type(obj).__name__}. "
        f"Types supportés : dict, set, frozenset, list, tuple, str, int, float, bool, None. "
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
