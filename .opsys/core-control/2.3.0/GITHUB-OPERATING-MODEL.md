# Modèle opérationnel GitHub du Core OPSYS-AI v2.3.0

## Objets

- 1 issue META de bootstrap GitHub.
- 25 milestones C00–C24.
- 25 issues EPIC de phase.
- 148 issues atomiques, une par mission du plan.
- 12 issues de bugs confirmés différés aux modules propriétaires.
- 1 Project GitHub recommandé, avec champs de statut/preuve/phase/risque.

Total prévu : **186 issues**.

## Cycle d’une issue

`BACKLOG/BLOCKED → READY → IN_PROGRESS → IN_REVIEW → VERIFIED → CLOSED`

- `READY` exige toutes les dépendances `VERIFIED` et intégrées.
- `IN_PROGRESS` exige worktree/branche propre et preflight lié au numéro d’issue.
- `IN_REVIEW` exige Evidence Bundle soumis et PR ouverte.
- `VERIFIED` exige tests, postconditions, revue, merge et cohérence ledger/GitHub.
- Un label ou une fermeture manuelle ne constitue jamais une preuve.

## Parallélisme

C00 et C01 restent séquentiels. À partir de C02, plusieurs issues `READY` peuvent être exécutées en parallèle uniquement si le DAG v2.3.0 les rend indépendantes, avec worktrees, branches, DBs et volumes séparés.

## PR

- Titre : `[Cxx-yyy] description`.
- Corps : `Closes #<issue>`, hash du Task Spec, tests RED/GREEN, Evidence Bundle, rollback, limites.
- Une PR ne mélange pas plusieurs tâches sauf issue d’intégration explicitement créée.

## GitHub Project

Le projet est recommandé mais ne doit jamais être créé sous un autre owner. Si le scope `project` manque, enregistrer un blocker et poursuivre avec issues + milestones sans créer un projet ailleurs.

## Utilisation avancée de GitHub

- Milestones : gates C00–C24.
- Project v2 : file visuelle, non source de preuve; création idempotente si le scope `project` est disponible.
- Pull requests : une mission par PR, sauf issue d’intégration explicite.
- GitHub Actions : checks réellement required seulement après `C02-005`; actions épinglées par SHA.
- Artifacts : Evidence Bundles, résultats de tests et reçus; hashes recroisés avec le ledger.
- Branch protection/rulesets : configurés dans `C02-005`, jamais supposés.
- Releases : Core RC seulement à `C24`, avec SBOM, provenance et notes de limites.
