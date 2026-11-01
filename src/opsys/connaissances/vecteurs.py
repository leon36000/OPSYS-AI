"""Vecteurs : empaquetage, normalisation et similarité exacte en Python (stdlib seulement). Module pur.

Phase 1 sans `sqlite-vec` : la recherche vectorielle est une similarité cosinus exacte sur les vecteurs normalisés d'un
SEUL espace, avec un plafond de volume (`modele.VECTEURS_PLAFOND`). La cible de production (pgvector, HNSW) remplace ce
module ; elle n'a pas ce plafond.
"""

from __future__ import annotations

import math
import struct
from collections.abc import Sequence

from .codes import EMBEDDINGS_INVALIDE, ErreurConnaissances


def valider(vecteur: object, dimension: int) -> list[float]:
    """Vecteur de la bonne dimension, fini, non nul ; sinon refus typé. Ne fait jamais confiance à un adaptateur."""
    if not isinstance(vecteur, (list, tuple)) or len(vecteur) != dimension:
        raise ErreurConnaissances(EMBEDDINGS_INVALIDE, f"vecteur de dimension {dimension} attendu")
    valeurs: list[float] = []
    for x in vecteur:
        if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
            raise ErreurConnaissances(EMBEDDINGS_INVALIDE, "vecteur : nombres finis seulement")
        valeurs.append(float(x))
    if not any(valeurs):
        raise ErreurConnaissances(EMBEDDINGS_INVALIDE, "vecteur nul refusé")
    return valeurs


def normaliser(vecteur: Sequence[float]) -> list[float]:
    norme = math.sqrt(sum(x * x for x in vecteur))
    if not norme or not math.isfinite(norme):
        raise ErreurConnaissances(EMBEDDINGS_INVALIDE, "vecteur de norme nulle ou infinie")
    return [x / norme for x in vecteur]


def empaqueter(vecteur: Sequence[float]) -> bytes:
    """Float32 petit-boutiste, indépendant de la machine."""
    return struct.pack(f"<{len(vecteur)}f", *vecteur)


def depaqueter(octets: bytes, dimension: int) -> tuple[float, ...]:
    if len(octets) != 4 * dimension:
        raise ErreurConnaissances(EMBEDDINGS_INVALIDE, "vecteur stocké de taille incohérente")
    return struct.unpack(f"<{dimension}f", octets)


def produit_scalaire(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))
