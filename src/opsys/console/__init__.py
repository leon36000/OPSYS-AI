"""Console web OPSYS : départements, approbations, budgets et paliers de modèles.

Point d'entrée `opsys-console` (0.0.0.0:8700). Dépendances web : extra `console` (fastapi, uvicorn).
"""

from __future__ import annotations

import sys

_DEPENDANCES_WEB = {"fastapi", "starlette", "uvicorn"}


def main(argv: list[str] | None = None) -> int:
    try:
        from .application import lancer
    except ModuleNotFoundError as exc:
        if exc.name not in _DEPENDANCES_WEB:
            raise
        print(f"opsys-console : dépendance absente ({exc.name}) ; installer l'extra : pip install 'opsys-ai[console]'",
              file=sys.stderr)
        return 2
    return lancer(argv)
