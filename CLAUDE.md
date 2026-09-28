@AGENTS.md

# CLAUDE.md — OPSYS-AI

- Lire `AGENTS.md`, puis `docs/produit/DEFINITION-PRODUIT.md` (§1, §5, §6, et §7 du département
  concerné) avant toute livraison, et `docs/architecture/ARCHITECTURE.md` avant toute modification
  structurelle.
- Travail en cours : `docs/programme/PLAN.md` (boucle d'exécution, une tâche vérifiée par itération).
- Nouveau département ou nouvel outil : suivre `docs/architecture/DEPARTEMENTS.md`. La référence
  vivante est `departments/m03-estimation/`.
- Avant chaque commit : `pytest`, `ruff check src tests`, `opsys verifier`.
- Sous-agents : chaque sortie se termine par `PREUVE:` (commandes exécutées + résultats) ou
  `BLOCKED:` (raison).
- `core/` est un fork dur d'OpenClaw (ADR-0008) : on le modifie librement, mais le bac à sable
  n'exécute pas son code ; il se construit et se teste en CI.
