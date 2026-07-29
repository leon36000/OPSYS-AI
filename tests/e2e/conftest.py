"""Rend le harnais e2e importable, quel que soit le mode d'import de pytest.

Les tests de ce dossier font ``from _harness import ...``. Cela fonctionnait
tant que pytest utilisait son mode d'import historique (« prepend »), qui ajoute
implicitement le dossier du fichier de test à ``sys.path``.

Depuis le passage à ``--import-mode=importlib`` (chore #109, rendu nécessaire par
la coexistence de ``tests/test_registre.py`` dans M1 et M2), cet ajout implicite
n'a plus lieu : chaque fichier de test est importé sous un nom dérivé de son
chemin complet, sans toucher à ``sys.path``. L'ajout doit donc être EXPLICITE, et
un ``conftest.py`` est le bon endroit puisqu'il est chargé avant la collecte des
tests du dossier.
"""

import sys
from pathlib import Path

_ICI = Path(__file__).resolve().parent
if str(_ICI) not in sys.path:
    sys.path.insert(0, str(_ICI))
