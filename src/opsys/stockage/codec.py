"""JSON typé pour la base de l'instance : ce qui entre ressort identique.

Les maillons des registres portent des montants `Decimal`, des tuples et des dates ; leur chaîne de
hash n'est vérifiable après relecture que si chaque valeur revient avec son type exact. Les types que
JSON ne connaît pas sont étiquetés `{"__opsys__": type, "v": valeur}` ; un dictionnaire métier qui
contiendrait lui-même la clé `__opsys__` est enveloppé, jamais confondu avec une étiquette.
"""

from __future__ import annotations

import base64
import datetime as dt
import json
from decimal import Decimal
from typing import Any

_ETIQUETTE = "__opsys__"


def encoder(valeur: Any) -> str:
    """Texte JSON compact. Refuse NaN et l'infini, les clés non textuelles et les types inconnus."""
    return json.dumps(_vers_json(valeur), ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def decoder(texte: str) -> Any:
    return _depuis_json(json.loads(texte))


def _etiqueter(type_: str, valeur: Any) -> dict[str, Any]:
    return {_ETIQUETTE: type_, "v": valeur}


def _vers_json(valeur: Any) -> Any:
    if valeur is None or isinstance(valeur, (bool, int, str)):
        return valeur
    if isinstance(valeur, float):
        if valeur != valeur or valeur in (float("inf"), float("-inf")):
            raise ValueError(f"nombre non fini non stockable : {valeur!r}")
        return valeur
    if isinstance(valeur, Decimal):
        if not valeur.is_finite():
            raise ValueError(f"Decimal non fini non stockable : {valeur!r}")
        return _etiqueter("decimal", str(valeur))
    if isinstance(valeur, dict):
        for cle in valeur:
            if not isinstance(cle, str):
                raise TypeError(f"clé de dictionnaire non textuelle : {cle!r}")
        contenu = {cle: _vers_json(v) for cle, v in valeur.items()}
        return _etiqueter("dict", contenu) if _ETIQUETTE in valeur else contenu
    if isinstance(valeur, list):
        return [_vers_json(v) for v in valeur]
    if isinstance(valeur, tuple):
        return _etiqueter("tuple", [_vers_json(v) for v in valeur])
    if isinstance(valeur, dt.datetime):
        return _etiqueter("datetime", valeur.isoformat())
    if isinstance(valeur, dt.date):
        return _etiqueter("date", valeur.isoformat())
    if isinstance(valeur, bytes):
        return _etiqueter("bytes", base64.b64encode(valeur).decode("ascii"))
    if isinstance(valeur, frozenset):
        return _etiqueter("frozenset", [_vers_json(v) for v in valeur])
    if isinstance(valeur, set):
        return _etiqueter("set", [_vers_json(v) for v in valeur])
    raise TypeError(f"type non stockable : {type(valeur).__name__}")


_RESTAURER = {
    "decimal": Decimal,
    "datetime": dt.datetime.fromisoformat,
    "date": dt.date.fromisoformat,
    "bytes": lambda v: base64.b64decode(v.encode("ascii")),
}


def _depuis_json(valeur: Any) -> Any:
    if isinstance(valeur, list):
        return [_depuis_json(v) for v in valeur]
    if not isinstance(valeur, dict):
        return valeur
    if set(valeur) == {_ETIQUETTE, "v"}:
        type_, contenu = valeur[_ETIQUETTE], valeur["v"]
        if type_ == "dict":
            return {cle: _depuis_json(v) for cle, v in contenu.items()}
        if type_ == "tuple":
            return tuple(_depuis_json(v) for v in contenu)
        if type_ == "frozenset":
            return frozenset(_depuis_json(v) for v in contenu)
        if type_ == "set":
            return {_depuis_json(v) for v in contenu}
        if type_ in _RESTAURER:
            return _RESTAURER[type_](contenu)
        raise ValueError(f"étiquette inconnue dans la base : {type_!r}")
    return {cle: _depuis_json(v) for cle, v in valeur.items()}
