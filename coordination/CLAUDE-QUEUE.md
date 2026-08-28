# Queue Claude — issues et assainissement

| Priority | Work ID | Condition d'entrée | Candidate scope | Status |
|---|---|---|---|---|
| P0 | LIVE-ISSUE-RECONCILIATION | Reproduire l'état des issues/PR et éliminer les doublons | read-only | ACTIVE |
| P1 | R4-S04 | Reproduction live et issue distincte | CI/locks/supply-chain | WAITING_LIVE |
| P1 | R4-S05 | Reproduction live et issue distincte | tests/docs/CI | WAITING_LIVE |
| P1 | R4-S11 | Git history et proof disponibles | evidence/reviews/index | WAITING_LIVE |

La matrice d'assignation complète vit **hors dépôt**, dans le pack plateforme
`OPSYS-AI-CLAUDE-ISSUES-AUTONOMOUS-v1.4`, fichier `data/CLAUDE-BACKLOG.csv` (chemin
d'installation dépendant de la machine, sous la forme
`$OPSYS_PACK/data/CLAUDE-BACKLOG.csv` où `$OPSYS_PACK` désigne le répertoire où le pack
a été dépaqueté — non versionné dans ce dépôt, chemin non portable tel quel). Elle n'est
donc pas résoluble depuis un checkout propre de ce dépôt ; c'est un renvoi documenté vers
une source externe. Qui, dans ce dépôt, mentionne ce chemin se relève par
`grep -rn --exclude-dir=.git 'CLAUDE-BACKLOG' .` — commande à rejouer plutôt qu'à croire,
aucune sortie n'étant figée ici. Les
lignes `CODEX_BOUND` sont exclues de la queue Claude, même si elles proviennent d'une
issue d'audit.

Scopes touchant `README.md` (à la racine du dépôt, hors de cette PR — à distinguer de
`coordination/README.md`, livré ici), `START_HERE.md`, `AGENTS.md` ou `docs/index.md` ne
sont pas mis en file ici : la décision Nathan du 2026-08-27 les attribue à la PR #566
(promotion canonique), pas à la queue Claude.

Aucun état ni contenu d'issue ou de PR n'est recopié dans ce fichier : les numéros cités
sont la clé vivante, `gh issue view <n>` / `gh pr view <n>` fait foi. La colonne `Status`
porte l'intention locale, comme dans `WORK-OWNERSHIP.md`, pas un miroir de l'état GitHub.
