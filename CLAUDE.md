@AGENTS.md

# CLAUDE.md — OPSYS-AI

- Lire `AGENTS.md`, puis `docs/architecture/ARCHITECTURE.md` avant toute modification structurelle.
- Nouveau département ou nouvel outil : suivre `docs/architecture/DEPARTEMENTS.md`. La référence
  vivante est `departments/m03-estimation/`.
- Avant chaque commit : `pytest`, `ruff check src tests`, `opsys verifier`.
- Sous-agents : chaque sortie se termine par `PREUVE:` (commandes exécutées + résultats) ou
  `BLOCKED:` (raison).
- Ne jamais exécuter du code amont non épinglé. OpenClaw se met à jour uniquement selon
  `core/UPSTREAM.md`.
