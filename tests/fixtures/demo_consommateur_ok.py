"""Consommateur de démonstration qui réussit toujours (tests du bus d'événements, T1.2-a).

Département fictif du socle, jamais un département réel : voir `tests/test_evenements.py` et
`docs/architecture/DEPARTEMENTS.md` (section Événements). `APPELS` permet de vérifier en mémoire,
en plus de l'état de la base, qu'une relivraison ne réexécute jamais un événement déjà traité.
"""

from __future__ import annotations

from opsys import stockage

APPELS: list[str] = []


def _recevoir_demo_complete(charge: dict) -> dict:
    stockage.maillons("m-demo-evenements-ok", "recus").append({"message": charge["message"]})
    APPELS.append(charge["message"])
    return {"traite": True, "message": charge["message"]}


def consommateurs() -> dict:
    return {"opsys.demo_complete": _recevoir_demo_complete}
