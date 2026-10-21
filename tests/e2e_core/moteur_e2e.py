"""Le moteur `opsys-mcp`, avec le seul seuil de réapprovisionnement de M6 que le scénario configure (PLAN T1.5-f).

Le manifeste réel de M6 ne fixe aucun seuil : M6 le dit par une attente « seuil à configurer », qui s'ajoute à
l'alerte d'écart et à la facture dans « À voir » et, avec elles, dépasse le budget de l'écran du propriétaire
(`BUDGET_ATTENTES`) : l'alerte d'écart n'y tient plus (constat de T1.5-f, voir `journee.py`). Comme `tests/e2e/`
(fixture `reappro`), le scénario joue donc le cas où Nathan a renseigné le seuil de l'article du chantier, sans
toucher au manifeste du dépôt : ce script remplace le chemin du manifeste que lit M6, puis lance le moteur tel quel.

`OPSYS_E2E_M6_MANIFESTE` : chemin du manifeste de M6 à lire ; absent, rien n'est remplacé. Les arguments sont ceux
de `opsys-mcp`. C'est la commande que `opsys/metier.json` donne au superviseur du core, ou que le scénario lance.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def main(argv: list[str]) -> None:
    chemin = os.environ.get("OPSYS_E2E_M6_MANIFESTE")
    if chemin:
        import m6_material_control.outils as m6_outils

        m6_outils._MANIFESTE = Path(chemin)
    from opsys.serveur_mcp import main as serveur

    serveur(argv)


if __name__ == "__main__":
    main(sys.argv[1:])
