"""Les deux registres append-only de Mnémo, câblés sur le stockage durable de l'instance.

`soi` (énoncés du modèle de soi) et `leçons` (propositions, évaluations, décisions) sont des registres chaînés de M10
: ils ont la même garantie que les registres Événements et Affaires (chaîne de hash, ajout seulement). Ce module est
le seul endroit du socle qui sait comment on les ouvre ; il importe M10 à la demande (comme la console des faits
candidats).
"""

from __future__ import annotations

from typing import Any

from .. import stockage

DEPARTEMENT = "m10-memoire"


def _registre(nom: str) -> Any:
    from m10_memoire import registre

    return registre.Registre(maillons=stockage.maillons(DEPARTEMENT, nom))


def soi() -> Any:
    return _registre("soi")


def lecons() -> Any:
    return _registre("lecons")


def evenements() -> Any:
    return _registre("evenements")


def affaires() -> Any:
    return _registre("affaires")


def faits_analytiques() -> Any:
    return _registre("faits_analytiques")


def faits_marketing() -> Any:
    return _registre("faits_marketing")
