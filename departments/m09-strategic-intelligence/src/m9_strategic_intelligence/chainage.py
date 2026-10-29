"""Chaînage minimal des registres M9 : événements append-only liés par empreinte, vérifiables sans état caché.

Module pur. Chaque événement porte ``schema``, ``index``, ``hash_precedent`` et ``hash_maillon`` (empreinte de tout le
reste). Un registre est valide si les index se suivent, si chaque ``hash_precedent`` est celui du maillon d'avant et si
chaque empreinte se recalcule. Les registres de veille, de plans, d'actions et d'expériences s'en servent : une seule
règle d'intégrité, pas quatre.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence

from . import capture_strategique as cs

HASH_INITIAL = cs.HASH_INITIAL


def maillon(schema: str, precedent: str, index: int, corps: Mapping) -> dict:
    evenement = {"schema": schema, "index": index, "hash_precedent": precedent, **corps}
    evenement["hash_maillon"] = cs.empreinte({k: v for k, v in evenement.items() if k != "hash_maillon"})
    return evenement


def suivant(schema: str, chaine: Sequence[Mapping], corps: Mapping) -> dict:
    precedent = chaine[-1]["hash_maillon"] if chaine else HASH_INITIAL
    return maillon(schema, precedent, len(chaine), corps)


def valider(schema: str, types: Collection[str], chaine: Sequence[Mapping]) -> tuple[bool, str]:
    precedent = HASH_INITIAL
    for rang, evenement in enumerate(chaine):
        try:
            if (
                evenement["schema"] != schema
                or evenement["index"] != rang
                or evenement["hash_precedent"] != precedent
                or evenement["type"] not in types
                or evenement["hash_maillon"]
                != cs.empreinte({k: v for k, v in evenement.items() if k != "hash_maillon"})
            ):
                return False, f"maillon invalide à l'index {rang}"
        except (KeyError, TypeError):
            return False, f"maillon invalide à l'index {rang}"
        precedent = evenement["hash_maillon"]
    return True, ""
