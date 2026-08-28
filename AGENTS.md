# AGENTS.md — Constitution opérationnelle cross-outils

L'autorité active du projet est [`docs/core/CANON-INDEX.md`](docs/core/CANON-INDEX.md).
Ce fichier contient seulement les règles stables nécessaires aux outils ; il
ne constitue pas un second canon.

## Périmètre

- Le programme actif qualifie le Core `C00` à `C24`.
- Aucun code métier `M1` à `M10` n'est complété avant `CORE_RC_VERIFIED` et les
  gates humains ou professionnels applicables.
- Les portails racine renvoient au canon ; les contrats détaillés restent dans
  les documents indexés.

## Preuve et revue

- Une tâche est `DONE` uniquement avec une preuve exécutable et reproductible ;
  sinon elle reste `BLOCKED` avec une cause concrète.
- Une revue indépendante est requise selon le niveau de risque ; une revue
  d'équipe utilise trois vendors distincts et des verdicts scellés.
- Les contrôles déterministes, les tests et les sources mesurées font autorité.
  Une sortie de modèle est une affirmation jusqu'à sa vérification.
- Les frontières humaines et professionnelles ne sont jamais remplacées par
  un modèle ou par une étiquette.

## Méthode de travail

- Avant d'écrire : vérifier l'issue, le scope, le worktree et les changements
  déjà présents.
- Utiliser une branche et un worktree dédiés par mission ; ne jamais pousser
  directement sur la branche par défaut.
- Écrire d'abord un test contractuel ciblé, observer le RED, implémenter le
  minimum, observer le GREEN, puis exécuter les non-régressions pertinentes.
- Garder le diff borné, sans stub, dette volontaire, secret ou faux succès.
- Ne jamais utiliser `--no-verify` ni contourner un contrôle rouge.

## Vérifications de base

- `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest scripts/tests -q`
- `PYTHONDONTWRITEBYTECODE=1 python3 -m pytest core/tests/bootstrap -q`
- `python3 scripts/structure_lint.py`

Toute affirmation de réussite doit être accompagnée de la sortie fraîche de la
commande qui la démontre. Toute sous-tâche se termine par `PREUVE:` ou
`BLOCKED:`.
