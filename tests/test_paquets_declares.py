"""Tout paquet Python du socle et des départements est déclaré dans `pyproject.toml` (`[tool.setuptools] packages`).

La liste est explicite : un sous-paquet oublié marche en installation éditable (la seule utilisée aujourd'hui :
installateur et image), mais disparaît d'une roue construite pour être distribuée. `m7_marketing.usine` (T4.17)
l'a été sans que rien ne le voie. Données : l'arborescence du dépôt, rien d'autre.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]


def _paquets_reels() -> set[str]:
    reels = set()
    for racine_src in [RACINE / "src", *sorted((RACINE / "departments").glob("*/src"))]:
        for init in racine_src.rglob("__init__.py"):
            if "__pycache__" in init.parts:
                continue
            reels.add(".".join(init.parent.relative_to(racine_src).parts))
    return reels


def test_chaque_paquet_du_depot_est_declare_et_chaque_declaration_existe():
    configuration = tomllib.loads((RACINE / "pyproject.toml").read_text(encoding="utf-8"))
    declares = set(configuration["tool"]["setuptools"]["packages"])
    reels = _paquets_reels()

    assert "m7_marketing.usine" in reels and "opsys" in reels  # le balayage voit bien le socle et les départements
    assert sorted(reels - declares) == [], "paquets absents de pyproject.toml (packages)"
    assert sorted(declares - reels) == [], "paquets déclarés sans dossier (__init__.py) dans le dépôt"
