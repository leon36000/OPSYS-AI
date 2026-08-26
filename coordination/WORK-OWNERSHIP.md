# Work ownership — snapshot quotidien

Dernière mise à jour UTC : `2026-08-26T10:59Z`

Sync owner de cette mise au point : **CLAUDE**. L'ownership de l'installation de `coordination/` est **en cours d'arbitrage**, pas acquise : le commit `ad38bfd` (« chore(core): install controlled coordination overlays », auteur leon36000) installe les 9 mêmes fichiers `coordination/` + le même ADR proposé + `.codex/agents/*.toml` + `.codex/config.toml`, et il est porté par la **PR #566** (DRAFT, branche `forgeai/manual-opsys-ai-r12-canon-integration-20260826021235`, état OPEN — vérifié via `git show --stat ad38bfd` et `gh pr view 566 --json state,files`). Cette PR-ci (**#564**) est retenue comme installeur unique côté Claude en attendant tranchage ; #566 reste ouverte et pourrait encore être mergée en parallèle si l'arbitrage n'aboutit pas avant.

Snapshot réconcilié contre le live GitHub (`gh pr list --state open`, `gh issue list`) le **2026-08-26T10:59Z**, HEAD local `b552f87` (avant le commit qui corrige les objections de revue ci-dessous — ce commit-là ne change aucun état GitHub live, seulement des fichiers locaux). **Ce tableau périme dès le prochain commit/push/merge sur l'une ou l'autre plateforme : aucune resynchronisation automatique n'existe.** Traiter toute ligne de plus de 24 h comme non fiable sans re-vérification (`gh pr view <n>` / `gh issue view <n>`).

| Work ID | Owner | Branch | Path scope | Status | Updated UTC | Next |
|---|---|---|---|---|---|---|
| OPS-OVERLAY-INSTALL | CLAUDE | claude/ops/install-coordination-overlay | coordination; docs/decisions/ADR-0004-independent-agent-ownership.md; .claude/agents; .claude/settings.example.json; tools/check_coordination.py | REVIEW | 2026-08-26T10:59Z | PR #564 ouverte ; revue aveugle scellée = REJECT (8 majeures, 4 mineures) ; corrections committées localement, non poussées — push puis re-revue restants |
| LIVE-ISSUE-RECONCILIATION | CLAUDE | n/a | read-only | ACTIVE | 2026-08-26T10:59Z | 3 candidats livrés (PR #567 = AUD-CI-003+004, issue #568 = AUD-CORE-005 bloquée en investigation, PR #571 = AUD-CORE-006) ; poursuivre la reconnaissance live (notamment #569) |
| AUD-CI-003 | CLAUDE | claude/aud-ci-003-004-gating-bloquant | .github/workflows/ci.yml; core/tests/bootstrap/test_ci_gating_contract.py | BLOCKED | 2026-08-26T10:59Z | PR #567 ouverte, CI vert hors `proof-sealed` ; gelée par #569 (capacité de revue 1 vendor/11, seuil de 3 inatteignable) — attente restauration du routeur ou arbitrage |
| AUD-CI-004 | CLAUDE | claude/aud-ci-003-004-gating-bloquant | .github/workflows/ci.yml | BLOCKED | 2026-08-26T10:59Z | Couvert par la même PR #567 que AUD-CI-003, même blocage #569 |
| AUD-CI-002 | CLAUDE | claude/aud-ci-002-pin-actions-sha | .github/workflows/ci.yml | QUEUED | 2026-08-26T10:59Z | Après merge d'AUD-CI-003/004 (jamais en parallèle, même fichier) ; de plus gelé tant que #569 dure (même périmètre scellé) |
| AUD-CORE-005 | CLAUDE | n/a | read-only | BLOCKED | 2026-08-26T10:59Z | Issue #568 publiée : fragment orphelin (`.opsys/tools/github-control`), correction TDD impossible en l'état ; décision demandée (restaurer / retirer / requalifier) avant tout code |
| AUD-CORE-006 | CLAUDE | claude/aud-core-006-chemins-hote-en-dur | audit/core-baseline | REVIEW | 2026-08-26T10:59Z | PR #571 ouverte, CI vert y compris `proof-sealed` (hors périmètre scellé : seul `audit/core-baseline/` touché) ; en attente de revue scellée |
| AUD-CANON-001 | CLAUDE | n/a | read-only | BLOCKED | 2026-08-26T10:59Z | Gate #541 : décision Nathan sur le layout du canon |
| AUD-CANON-002 | CLAUDE | n/a | read-only | BLOCKED | 2026-08-26T10:59Z | Gate #541 : décision Nathan sur le layout du canon |

Valeurs Owner : `CODEX`, `CLAUDE`, `CHATGPT`, `NATHAN`, `UNASSIGNED`.

Valeurs Status : `QUEUED`, `ACTIVE`, `BLOCKED`, `REVIEW`, `READY_TO_MERGE`, `MERGED`, `TRANSFER`.

Les scopes multiples sont séparés par `;`. Chemins relatifs uniquement.

Aucune ligne `CODEX_BOUND`, `PARKED_*` ou `NATHAN_DECISION` du backlog Claude n'est prise ici.
