"""Catalogue versionné des types d'événements (`opsys.evenement/v1`), en JSON Schema.

Un fichier par type dans `catalogue/*.json`, nommé `<type_evenement>.json`. Chaque schéma porte
`$id: opsys.evenement/v1/<type_evenement>` : le nom de fichier et le `$id` doivent s'accorder, pour
qu'un type ne puisse pas être chargé sous un autre nom que celui qu'il déclare lui-même.

Une charge est validée contre son schéma par `jsonschema` (Draft 2020-12, licence MIT, déjà tiré
par `mcp`) : objets et tableaux imbriqués compris. Le validateur minimal des outils d'agent
(`opsys.outils.valider_arguments`) ne regarde que le premier niveau ; il ne suffisait pas pour des
charges comme les lignes de `m6.variance_chantier` ou de `m3.devis_accepte`. Chaque schéma du
catalogue est lui-même vérifié au chargement : un schéma invalide empêche le démarrage.
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

_DOSSIER = Path(__file__).parent / "catalogue"
_PREFIXE_ID = "opsys.evenement/v1/"
TYPE_EVENEMENT = re.compile(r"^(m(?:10|[1-9])|opsys)\.[a-z][a-z0-9_]*$")

_VERROU = threading.Lock()
_CACHE: dict[str, Mapping[str, Any]] | None = None
_VALIDATEURS: dict[str, Draft202012Validator] = {}


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
            Draft202012Validator.check_schema(schema)
            catalogue[type_evenement] = schema
            _VALIDATEURS[type_evenement] = Draft202012Validator(schema)
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


def erreurs_charge(type_evenement: str, charge: Mapping[str, Any]) -> list[str]:
    """Écarts de `charge` à son schéma, avec le chemin de chaque écart ; vide si conforme.

    Lève `TypeEvenementInconnu` si le type n'est pas au catalogue.
    """
    schema(type_evenement)
    erreurs = []
    for erreur in sorted(_VALIDATEURS[type_evenement].iter_errors(charge), key=lambda e: list(e.absolute_path)):
        chemin = "/".join(str(partie) for partie in erreur.absolute_path) or "(racine)"
        erreurs.append(f"{chemin} : {erreur.message}")
    return erreurs
