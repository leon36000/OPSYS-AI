# Work ownership — snapshot quotidien

Dernière mise à jour UTC : `2026-08-26T02:14Z`

Sync owner de cette mise au point : **CLAUDE** (amorçage de l'overlay ; Codex n'avait
encore jamais installé `coordination/` dans ce dépôt).

Réconcilié contre le live : HEAD `31fa5497`, tree `41772beb`, `origin/main` identique.

| Work ID | Owner | Branch | Path scope | Status | Updated UTC | Next |
|---|---|---|---|---|---|---|
| OPS-OVERLAY-INSTALL | CLAUDE | claude/ops/install-coordination-overlay | coordination; docs/decisions/ADR-PROPOSED-INDEPENDENT-AGENT-OWNERSHIP.md; .claude/agents; .claude/settings.example.json | ACTIVE | 2026-08-26T02:14Z | Commit puis PR |
| LIVE-ISSUE-RECONCILIATION | CLAUDE | n/a | read-only | ACTIVE | 2026-08-26T02:14Z | Rapport de triage et trois candidats d'avance |
| AUD-CI-003 | CLAUDE | claude/aud-ci-003-004-gating-bloquant | .github/workflows/ci.yml; core/tests/bootstrap/test_ci_gating_contract.py | QUEUED | 2026-08-26T02:14Z | RED puis GREEN puis PR |
| AUD-CI-004 | CLAUDE | claude/aud-ci-003-004-gating-bloquant | .github/workflows/ci.yml | QUEUED | 2026-08-26T02:14Z | Couvert par la même PR atomique que AUD-CI-003 |
| AUD-CI-002 | CLAUDE | claude/aud-ci-002-pin-actions-sha | .github/workflows/ci.yml | QUEUED | 2026-08-26T02:14Z | Après AUD-CI-003/004, jamais en parallèle (même fichier) |
| AUD-CORE-005 | CLAUDE | claude/aud-core-005-github-control-validator | .opsys/tools/github-control | QUEUED | 2026-08-26T02:14Z | Reproduire depuis checkout propre puis décider |
| AUD-CANON-001 | CLAUDE | n/a | read-only | BLOCKED | 2026-08-26T02:14Z | Gate #541 : décision Nathan sur le layout du canon |
| AUD-CANON-002 | CLAUDE | n/a | read-only | BLOCKED | 2026-08-26T02:14Z | Gate #541 : décision Nathan sur le layout du canon |

Valeurs Owner : `CODEX`, `CLAUDE`, `CHATGPT`, `NATHAN`, `UNASSIGNED`.

Valeurs Status : `QUEUED`, `ACTIVE`, `BLOCKED`, `REVIEW`, `READY_TO_MERGE`, `MERGED`, `TRANSFER`.

Les scopes multiples sont séparés par `;`. Chemins relatifs uniquement.

Aucune ligne `CODEX_BOUND`, `PARKED_*` ou `NATHAN_DECISION` du backlog Claude n'est prise ici.
