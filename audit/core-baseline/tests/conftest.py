"""Fixture anti auto-référence pour C00-001.

TARGET.json ne peut jamais déclarer correctement le SHA du commit qui le
contient (le SHA dépend du contenu de l'arbre, qui inclut TARGET.json
lui-même). Cette fixture génère les 5 sorties fraîchement juste avant que
la classe qui exerce la PRODUCTION ne s'exécute — jamais committées entre
génération et vérification. Une classe séparée vérifie la propreté AVANT
que cette fixture ne s'exécute.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

# parents[3] = racine réelle du worktree (parents[2] pointe sur audit/, pas la
# racine — mesuré en revue avant soumission, cf. test_target_custody.py).
WORKTREE = Path(__file__).resolve().parents[3]
SORTIE_DIR = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="class", autouse=False)
def custody_produite():
    """Génère les 5 sorties via custody._produire_sorties() avant les tests de production."""
    # Import local pour éviter les effets de bord au collect
    sys.path.insert(0, str(SORTIE_DIR))
    try:
        import custody
        custody._produire_sorties(WORKTREE, SORTIE_DIR)
    finally:
        if str(SORTIE_DIR) in sys.path:
            sys.path.remove(str(SORTIE_DIR))
    yield
    # Pas de nettoyage : les fichiers restent pour inspection manuelle
