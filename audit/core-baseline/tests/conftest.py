"""Fixture anti auto-référence pour C00-001.

TARGET.json ne peut jamais déclarer correctement le SHA du commit qui le
contient (le SHA dépend du contenu de l'arbre, qui inclut TARGET.json
lui-même). Cette fixture génère les 5 sorties fraîchement juste avant que
la classe qui exerce la PRODUCTION ne s'exécute — jamais committées entre
génération et vérification. Une classe séparée vérifie la propreté AVANT
que cette fixture ne s'exécute.
"""
from __future__ import annotations

from pathlib import Path

# parents[3] = racine réelle du worktree (parents[2] pointe sur audit/, pas la
# racine — mesuré en revue avant soumission, cf. test_target_custody.py).
WORKTREE = Path(__file__).resolve().parents[3]
SORTIE_DIR = Path(__file__).resolve().parent.parent


# Revue scellée tour 2 (DeepSeek-V4-Pro, MINEURE, confirmée) : la fixture
# `custody_produite` définie ici était toujours masquée par la fixture locale
# de même nom dans `TestProductionSorties` (résolution de portée pytest —
# closer scope gagne) — code mort, jamais exécuté. Retirée. `WORKTREE` et
# `SORTIE_DIR` restent : ce sont les constantes qui documentent le motif
# anti-auto-référence, utilisées ailleurs si un futur fichier de tests
# s'ajoute sous audit/core-baseline/tests/.
