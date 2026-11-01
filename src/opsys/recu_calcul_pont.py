"""Pont du REÇU DE CALCUL de M5 vers les autres départements (`docs/architecture/M2-VICTOR.md`, « Reçu rejouable »).

Le moteur de calcul de M5 (`m5_financecore.moteur_calcul`, `docs/moteur-calcul.md`) a défini le reçu `recu-calcul.v1`
: des entrées normalisées, une méthode et une précision déclarées, un résultat en texte décimal, des avertissements et
deux empreintes SHA-256 — de quoi REFAIRE le calcul et constater qu'on obtient la même chose. Un département ne
réécrit pas ce format et n'importe pas le code d'un autre département (#109) : il passe par ce pont du socle, qui
appelle les mêmes fonctions (`construire`, `verifier`, `compacter`). Un reçu produit ici est donc vérifiable tel quel
par l'outil de M5 (`m5_verifier_recu_calcul`) : même format, mêmes empreintes.

Ce pont ne CALCULE rien et ne REJOUE rien : chaque département garde ses propres moteurs et sa table de rejeu (le
rejeu d'un reçu appartient au moteur qui l'a produit). Import à la demande, comme `capacites.py` le fait pour M5 : si
M5 est introuvable, l'erreur est franche (`ImportError`), jamais un reçu à un autre format.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

__all__ = ["FORMAT", "compacter", "construire", "verifier"]

FORMAT = "recu-calcul.v1"


def _recu() -> Any:
    from m5_financecore import recu_calcul

    if recu_calcul.FORMAT != FORMAT:
        raise RuntimeError(f"format de reçu inattendu {recu_calcul.FORMAT!r} (attendu {FORMAT!r})")
    return recu_calcul


def construire(
    *,
    moteur: str,
    version_moteur: str,
    methode: str,
    precision: Mapping[str, Any],
    parametres: Mapping[str, Any],
    entrees: Mapping[str, Any],
    resultat: Mapping[str, Any],
    avertissements: list[str],
) -> dict[str, Any]:
    """Le reçu complet (avec `entrees`) : `m5_financecore.recu_calcul.construire`. Lève `TypeError` sur un flottant."""
    return _recu().construire(
        moteur=moteur,
        version_moteur=version_moteur,
        methode=methode,
        precision=precision,
        parametres=parametres,
        entrees=entrees,
        resultat=resultat,
        avertissements=avertissements,
    )


def verifier(recu: Any) -> tuple[bool, str]:
    """`(True, "")` si les deux empreintes correspondent au contenu du reçu, `(False, raison)` sinon."""
    return _recu().verifier(recu)


def compacter(recu: Mapping[str, Any]) -> dict[str, Any]:
    """Le reçu sans ses `entrees` : même empreinte, toujours vérifiable (jamais rejouable seul)."""
    return _recu().compacter(recu)
