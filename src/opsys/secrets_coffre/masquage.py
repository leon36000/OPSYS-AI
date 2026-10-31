"""Masquage des secrets dans les journaux et les réponses.

- Toute valeur déchiffrée est enregistrée ici le temps de son usage (`coffre.utiliser`) : tant qu'elle est en
  mémoire, chaque enregistrement de journal (fabrique `logging` installée par `installer`) et chaque réponse
  passée à `masquer` la remplacent par `•••`.
- Les jetons opaques `opsys-jeton:v1:…` et les formes usuelles de clés (en-tête Bearer, sk-…, AIza…, ya29.…)
  sont masqués en permanence, même hors usage.
Limite : une valeur copiée par un tiers dans un autre format (base64, découpée) n'est pas reconnue.
"""

from __future__ import annotations

import logging
import re
import threading
from collections import Counter
from typing import Any

MASQUE = "•••"
_MOTIFS = re.compile(
    r"opsys-jeton:v1:[A-Za-z0-9_-]{16,}"
    r"|(?i:bearer)\s+[A-Za-z0-9._~+/=-]{8,}"
    r"|\bsk-[A-Za-z0-9_-]{8,}"
    r"|\bAIza[0-9A-Za-z_-]{20,}"
    r"|\bya29\.[0-9A-Za-z_.-]{10,}"
)
_VERROU = threading.Lock()
_ACTIVES: Counter[str] = Counter()
_INSTALLE = False


def enregistrer(valeur: str) -> None:
    if len(valeur) >= 4:
        with _VERROU:
            _ACTIVES[valeur] += 1


def oublier(valeur: str) -> None:
    with _VERROU:
        if _ACTIVES.get(valeur):
            _ACTIVES[valeur] -= 1
            if not _ACTIVES[valeur]:
                del _ACTIVES[valeur]


def masquer_texte(texte: str) -> str:
    with _VERROU:
        actives = sorted(_ACTIVES, key=len, reverse=True)
    for valeur in actives:
        texte = texte.replace(valeur, MASQUE)
    return _MOTIFS.sub(MASQUE, texte)


def masquer(objet: Any) -> Any:
    """Copie de `objet` (texte, octets décodables, listes, dictionnaires) où toute valeur active est masquée."""
    if isinstance(objet, str):
        return masquer_texte(objet)
    if isinstance(objet, bytes):
        try:
            return masquer_texte(objet.decode("utf-8")).encode("utf-8")
        except UnicodeDecodeError:
            return objet
    if isinstance(objet, dict):
        return {masquer(k): masquer(v) for k, v in objet.items()}
    if isinstance(objet, (list, tuple)):
        return type(objet)(masquer(v) for v in objet)
    return objet


def contient_secret(texte: str) -> bool:
    return masquer_texte(texte) != texte


def installer() -> None:
    """Fabrique d'enregistrements masquante pour TOUS les journaux du processus (idempotent)."""
    global _INSTALLE
    with _VERROU:
        if _INSTALLE:
            return
        _INSTALLE = True
    precedente = logging.getLogRecordFactory()

    def fabrique(*args: Any, **kwargs: Any) -> logging.LogRecord:
        enregistrement = precedente(*args, **kwargs)
        try:
            message = enregistrement.getMessage()
        except Exception:  # noqa: BLE001 — un message mal formé reste traité par logging
            return enregistrement
        masque = masquer_texte(message)
        if masque != message:
            enregistrement.msg, enregistrement.args = masque, None
        return enregistrement

    logging.setLogRecordFactory(fabrique)
