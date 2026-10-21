"""Consommateur de démonstration qui échoue toujours (tests du bus d'événements, T1.2-a).

Écrit avant d'échouer : le répartiteur doit annuler cette écriture à chaque tentative (point de
sauvegarde), jamais la laisser orpheline. Département fictif du socle, jamais un département réel.
"""

from __future__ import annotations

from opsys import stockage

TENTATIVES: list[str] = []


def _recevoir_demo_complete(charge: dict) -> dict:
    stockage.maillons("m-demo-evenements-echec", "recus").append({"message": charge["message"]})
    TENTATIVES.append(charge["message"])
    raise RuntimeError("échec de démonstration : consommateur toujours en échec")


def consommateurs() -> dict:
    return {"opsys.demo_complete": _recevoir_demo_complete}
