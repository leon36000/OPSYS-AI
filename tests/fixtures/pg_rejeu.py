"""Rejeu, sur un VRAI PostgreSQL 17, de fichiers de test existants écrits pour SQLite : « le même test, deux moteurs ».

Un test de console ou de service écrit pour SQLite bâtit son monde par `stockage.migrer()` / `stockage.transaction()`
sur la base par défaut (`OPSYS_BASE_URL`, sinon un fichier SQLite sous `OPSYS_HOME`). Ce module-ci charge le fichier de
test d'origine, en injecte les tests ET les fixtures dans le module appelant, et ajoute une fixture automatique qui fait
pointer `OPSYS_BASE_URL` vers une base PostgreSQL neuve, migrée (gabarit de `pg_parite`). Le test d'origine reste
exécuté tel quel sur SQLite par son propre fichier ; ici il l'est sur PostgreSQL, sans la moindre modification : aucune
duplication de scénario, aucune dérive possible entre les deux moteurs.

Usage, dans `tests/test_postgresql_rejeu_xxx.py` :

    from pg_rejeu import installer
    INJECTES = installer(globals(), "test_console_catalogue_m6.py", "test_console_prix_m6.py")

Sans Docker, chaque test est IGNORÉ avec la raison exacte (jamais un faux vert).
Limites : un test qui lit le fichier SQLite par `sqlite3`/`Path`, qui compte sur un écouteur SQLite ou qui attend le
refus d'un moteur autre que SQLite échoue pour une raison propre à SQLite : il n'a pas sa place dans un rejeu.
"""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Iterable
from pathlib import Path

import pytest
from _pytest.fixtures import FixtureFunctionDefinition
from pg_parite import base_pg, serveur_pg  # noqa: F401  (fixtures pytest)

from opsys import stockage

RACINE_TESTS = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _sur_postgresql(_instance_isolee, base_pg, monkeypatch):  # noqa: F811
    """Chaque test du rejeu s'exécute sur sa propre base PostgreSQL neuve, migrée jusqu'à la tête."""
    monkeypatch.setenv(stockage.ENV_URL, base_pg)
    yield base_pg
    stockage.liberer()


def _charger(fichier: str):
    chemin = Path(fichier)
    if not chemin.is_absolute():
        chemin = RACINE_TESTS / fichier
    nom = "rejeu_" + chemin.stem
    spec = importlib.util.spec_from_file_location(nom, chemin)
    assert spec is not None and spec.loader is not None, f"test introuvable : {chemin}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[nom] = module
    spec.loader.exec_module(module)
    return module


def installer(globales: dict, *fichiers: str, exclure: Iterable[str] = ()) -> list[str]:
    """Injecte tests et fixtures des `fichiers` dans `globales` ; rend les noms des tests injectés (pour les relire)."""
    exclus = set(exclure)
    injectes: list[str] = []
    for nom, objet in (("_sur_postgresql", _sur_postgresql), ("base_pg", base_pg), ("serveur_pg", serveur_pg)):
        globales[nom] = objet
    for fichier in fichiers:
        module = _charger(fichier)
        prefixe = Path(fichier).stem.removeprefix("test_")
        for nom, objet in list(vars(module).items()):
            if nom.startswith("_") and not isinstance(objet, FixtureFunctionDefinition):
                continue
            if isinstance(objet, FixtureFunctionDefinition):
                globales[nom] = objet  # même nom que dans le fichier d'origine : les tests le retrouvent
            elif nom.startswith("test_") and callable(objet) and nom not in exclus:
                if nom in globales:
                    raise AssertionError(f"nom de test en double dans le rejeu : {nom}")
                globales[nom] = objet
                injectes.append(f"{prefixe}::{nom}")
    return injectes
