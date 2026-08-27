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
| P2 | DOC-ADR0004-INDEX | Après merge de #564 | docs/index.md | WAITING_LIVE |

La matrice d'assignation complète vit **hors dépôt**, dans le pack plateforme
`OPSYS-AI-CLAUDE-ISSUES-OPERATIONS-v1.2`, fichier `data/CLAUDE-BACKLOG.csv` (chemin
d'installation dépendant de la machine, sous la forme
`$OPSYS_PACK/data/CLAUDE-BACKLOG.csv` où `$OPSYS_PACK` désigne le répertoire où le pack
a été dépaqueté — non versionné dans ce dépôt, chemin non portable tel quel). Elle n'est
donc pas résoluble depuis un checkout propre de ce dépôt ; c'est un renvoi documenté vers
une source externe, et aucun outil versionné ici ne tente de l'ouvrir — propriété
re-mesurable : `grep -rn --exclude-dir=.git 'CLAUDE-BACKLOG' .` ne renvoie que ce
paragraphe. Les
lignes `CODEX_BOUND` sont exclues de la queue Claude, même si elles proviennent d'une
issue d'audit.

`DOC-ADR0004-INDEX` : mission volontairement retirée du périmètre de la PR #564 (revue
scellée n°2, objection N2) — `docs/index.md` est un fichier **préexistant** du dépôt
(`git cat-file -e origin/main:docs/index.md` réussit) et cette PR maintient la propriété
d'être purement additive (`git diff --name-status origin/main...HEAD`, dont toutes les
lignes portent le statut `A`). C'est aussi ce qu'exige l'issue **#563**, mais les deux
propriétés se vérifient sans elle : son énoncé n'est pas recopié ici. La référence à
ADR-0004 dans `docs/index.md` reste à faire, mais dans une mission séparée, ouverte après
que #564 soit mergée (sinon la même propriété est rompue).
Scope exact : `docs/index.md` uniquement. Pas d'issue GitHub créée par cette PR — au lead
de la créer s'il retient cette mission.

Aucun état ni contenu d'issue ou de PR n'est recopié dans ce fichier : les numéros cités
sont la clé vivante, `gh issue view <n>` / `gh pr view <n>` fait foi. C'est ce qui dispense
ce fichier d'une clause de péremption — il n'affirme rien qui puisse se périmer côté
GitHub. La colonne `Status` porte l'intention locale, comme dans `WORK-OWNERSHIP.md`, pas
un miroir de l'état GitHub.
