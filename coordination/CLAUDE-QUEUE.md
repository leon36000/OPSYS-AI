# Queue Claude — issues et assainissement

| Priority | Work ID | Condition d'entrée | Candidate scope | Status |
|---|---|---|---|---|
| P0 | LIVE-ISSUE-RECONCILIATION | Reproduire l'état des issues/PR et éliminer les doublons | read-only | READY |
| P0 | AUD-CANON-002 | Défaut encore présent, aucun path Codex actif | README/docs/canon | WAITING_LIVE |
| P0 | AUD-CANON-003 | Défaut encore présent, aucun path Codex actif | START_HERE/docs | WAITING_LIVE |
| P1 | AUD-CANON-004 | Défaut encore présent, aucun path Codex actif | AGENTS/docs | WAITING_LIVE |
| P1 | R4-S04 | Reproduction live et issue distincte | CI/locks/supply-chain | WAITING_LIVE |
| P1 | R4-S05 | Reproduction live et issue distincte | tests/docs/CI | WAITING_LIVE |
| P1 | R4-S11 | Git history et proof disponibles | evidence/reviews/index | WAITING_LIVE |

La matrice d'assignation complète vit **hors dépôt**, dans le pack plateforme
`OPSYS-AI-CLAUDE-ISSUES-OPERATIONS-v1.2`, fichier `data/CLAUDE-BACKLOG.csv` (chemin hôte
d'installation, par exemple `/home/pc1/opsys-pack/OPSYS-AI-CLAUDE-ISSUES-OPERATIONS-v1.2/data/CLAUDE-BACKLOG.csv`
sur la machine où le pack a été dépaqueté — non versionné dans ce dépôt, chemin non
portable tel quel). Elle n'est donc pas résoluble depuis un checkout propre de ce dépôt ;
c'est un renvoi documenté vers une source externe, pas un fragment orphelin comme celui
décrit par l'issue #568. Les lignes `CODEX_BOUND` sont exclues de la queue Claude, même
si elles proviennent d'une issue d'audit.
