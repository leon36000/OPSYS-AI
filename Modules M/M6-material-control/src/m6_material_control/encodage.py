"""Encodage canonique injectif et déterministe pour M6 (CA-M6-21).

Utilise un préfixage de longueur et une normalisation récursive stable pour garantir
l'injectivité et la reproductibilité des empreintes. Cette approche est héritée d'un patron
éprouvé et corrigé à deux reprises (le registre CRM voisin (2026-07), #111) pour refuser explicitement les types
non supportés plutôt que d'utiliser repr(), dont l'adresse mémoire rendrait l'identifiant
irreproductible. Les appelants doivent sérialiser les valeurs personnalisées avant de les
incorporer.
"""
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
    """Forme canonique INSPECTABLE des arguments : normalisation récursive
    (types tagués), sérialisation JSON déterministe, préfixage par longueur.

    Retourne la FORME, pas un hash : l'injectivité se teste ainsi sur la
    représentation réelle (deux tuples distincts -> deux chaînes distinctes,
    collisions par concaténation incluses), et non sur l'absence statistique
    de collision d'un condensat. Les identifiants courts se dérivent par
    empreinte() ci-dessous.
    """
    segments = []
    for v in valeurs:
        norm = _normaliser(v)
        serial = json.dumps(norm, separators=(",", ":"), ensure_ascii=True)
        segments.append(f"{len(serial)}:{serial}")
    return "".join(segments)


def empreinte(*valeurs):
    """Condensat sha256 hex (64) de la forme canonique — pour les identifiants.

    Accepte les mêmes arguments qu'encoder_canonique : un identifiant est
    toujours dérivé de la MÊME forme injective que celle qui se teste.
    """
    return hashlib.sha256(encoder_canonique(*valeurs).encode("utf-8")).hexdigest()


