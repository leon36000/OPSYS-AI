"""Catalogue versionné des types d'événements (`opsys.evenement/v1`), en JSON Schema.

Un fichier par type dans `catalogue/*.json`, nommé `<type_evenement>.json`. Chaque schéma porte
`$id: opsys.evenement/v1/<type_evenement>` : le nom de fichier et le `$id` doivent s'accorder, pour
qu'un type ne puisse pas être chargé sous un autre nom que celui qu'il déclare lui-même.

La validation d'une charge contre ces schémas réutilise `opsys.outils.valider_arguments` (JSON
Schema minimal déjà utilisé par les outils d'agent) : aucune nouvelle dépendance.
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

_DOSSIER = Path(__file__).parent / "catalogue"
_PREFIXE_ID = "opsys.evenement/v1/"
TYPE_EVENEMENT = re.compile(r"^(m(?:10|[1-9])|opsys)\.[a-z][a-z0-9_]*$")

_VERROU = threading.Lock()
_CACHE: dict[str, Mapping[str, Any]] | None = None


class TypeEvenementInconnu(ValueError):
    """`type_evenement` absent du catalogue (`src/opsys/evenements/catalogue/`)."""


def _charger_tout() -> dict[str, Mapping[str, Any]]:
    global _CACHE
    with _VERROU:
        if _CACHE is not None:
            return _CACHE
        catalogue: dict[str, Mapping[str, Any]] = {}
        for chemin in sorted(_DOSSIER.glob("*.json")):
            type_evenement = chemin.stem
            if not TYPE_EVENEMENT.match(type_evenement):
                raise ValueError(f"{chemin} : nom de type invalide {type_evenement!r} (attendu <prefixe>.<nom>)")
            schema = json.loads(chemin.read_text(encoding="utf-8"))
            id_attendu = _PREFIXE_ID + type_evenement
            if schema.get("$id") != id_attendu:
                raise ValueError(f"{chemin} : $id attendu {id_attendu!r}, trouvé {schema.get('$id')!r}")
            if schema.get("type") != "object":
                raise ValueError(f"{chemin} : schéma racine doit être de type 'object'")
            catalogue[type_evenement] = schema
        _CACHE = catalogue
        return _CACHE


def types_connus() -> frozenset[str]:
    """Types déclarés au catalogue (noms de fichiers `catalogue/*.json`)."""
    return frozenset(_charger_tout())


def schema(type_evenement: str) -> Mapping[str, Any]:
    """Schéma JSON du type, ou `TypeEvenementInconnu` s'il n'est pas au catalogue."""
    trouve = _charger_tout().get(type_evenement)
    if trouve is None:
        raise TypeEvenementInconnu(f"type d'événement inconnu au catalogue : {type_evenement!r}")
    return trouve
