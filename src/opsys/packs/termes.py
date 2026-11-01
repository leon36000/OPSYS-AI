"""Recherche d'un terme sectoriel dans un texte : la même règle pour le test de garde et pour les tests de sortie.

Un terme est cherché sans accent ni casse, au DÉBUT d'un mot (la lettre ou le chiffre qui précède ne doit pas en
faire partie ; `_` compte comme séparateur, donc `mot_cle_x` contient `mot`). Le pluriel et les
dérivés d'un mot suivent sans règle propre (`terme` trouve `termes`, `termerie`). C'est volontairement large : un terme
sectoriel qui se glisse dans le cœur doit être vu, et une exception se déclare, elle ne se devine pas.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable


def normaliser(texte: str) -> str:
    """Minuscules, sans accent, apostrophes typographiques ramenées à `'`."""
    decompose = unicodedata.normalize("NFKD", texte.replace("’", "'"))
    return "".join(c for c in decompose if not unicodedata.combining(c)).casefold()


def motif_terme(terme: str) -> re.Pattern[str]:
    """Motif d'un terme (déjà normalisé ou non) ; les espaces internes admettent `_`, `-` et les espaces multiples."""
    mots = [re.escape(m) for m in re.split(r"[\s_-]+", normaliser(terme).strip()) if m]
    return re.compile(r"(?<![a-z0-9])" + r"[\s_-]+".join(mots))


def termes_trouves(texte: str, termes: Iterable[str]) -> list[str]:
    """Les termes de `termes` présents dans `texte`, dans l'ordre de `termes`, sans doublon."""
    normal = normaliser(texte)
    vus: list[str] = []
    for terme in termes:
        if terme not in vus and motif_terme(terme).search(normal):
            vus.append(terme)
    return vus


def lignes_avec_termes(texte: str, termes: Iterable[str]) -> list[tuple[int, str, list[str]]]:
    """`(numéro de ligne, ligne, termes)` pour chaque ligne qui en contient (numérotation à partir de 1)."""
    termes = list(termes)
    trouvees = []
    for numero, ligne in enumerate(texte.splitlines(), start=1):
        presents = termes_trouves(ligne, termes)
        if presents:
            trouvees.append((numero, ligne, presents))
    return trouvees
