# Work ownership — snapshot quotidien

Dernière mise à jour UTC : `2026-08-27T04:41Z`

Snapshot réconcilié contre le live GitHub (`gh pr view <n>`, `gh issue view <n>`, `gh api repos/<owner>/<repo>/issues/<n>`) le **2026-08-27T04:41Z**. Cet horodatage avance parce qu'une réconciliation live a réellement eu lieu à cette date, pas pour refléter une date d'édition. **Ce fichier entier — prose comprise, pas seulement le tableau — périme dès le prochain commit/push/merge sur l'une ou l'autre plateforme : aucune resynchronisation automatique n'existe — y compris pour la synchronisation de cette branche elle-même avec `origin`.** Aucune cellule de ce fichier n'affirme un tel état de synchronisation avec le remote : un fichier versionné sur la branche qu'il décrit ne peut pas rapporter de façon fiable son propre degré d'avancement par rapport à `origin`, un nouveau commit sur cette branche rendant l'affirmation caduque immédiatement. Traiter toute affirmation d'état GitHub de ce fichier — ligne de tableau comme phrase de prose — datée de plus de 24 h comme non fiable sans re-vérification (`gh pr view <n>` / `gh issue view <n>`).

Sync owner de cette mise au point : **CLAUDE**. L'ownership de l'installation de `coordination/` est **en cours d'arbitrage**, pas acquise : une autre PR, la **#566**, est candidate à l'installation des mêmes chemins. Ni son contenu ni son état ne sont recopiés ici — `gh pr view 566` fait foi, et `git show --stat` sur ses commits une fois sa branche récupérée (`git fetch origin`). Cette PR-ci (**#564**) est retenue comme installeur unique côté Claude en attendant tranchage.

Aucune cellule `Next` de la table ci-dessous ne recopie l'énoncé, le périmètre ou l'état d'une issue ou d'une PR : seuls les numéros y figurent, et `gh issue view <n>` / `gh pr view <n>` fait foi. Ce qui est écrit dans `Next` est l'intention locale — ce que cette mise au point retient comme prochaine action de notre côté.

| Work ID | Owner | Branch | Path scope | Status | Updated UTC | Next |
|---|---|---|---|---|---|---|
| OPS-OVERLAY-INSTALL | CLAUDE | claude/ops/install-coordination-overlay | coordination; docs/decisions/ADR-0004-independent-agent-ownership.md; .claude/agents; .claude/settings.example.json; tools/check_coordination.py | REVIEW | 2026-08-27T04:41Z | PR #564 ; revue aveugle scellée itérée, REJECT à chaque tour, majoritairement sur la **même classe de défaut** : une affirmation vérifiable contenue dans un fichier livré, non re-mesurée contre HEAD. Corrigée site par site aux tours précédents, elle réapparaissait au suivant, à côté — y compris exacte au tour où elle a été écrite puis mesurée fausse au tour suivant sans qu'on y ait retouché, cas qu'aucune relecture ne pouvait attraper. Le remède retenu n'est donc plus la correction site par site mais la **réduction de surface** : ce qui porte sur autre chose que les fichiers livrés par cette PR est retiré, pas réécrit. Aucun décompte de tours n'est figé ici : il serait faux au tour suivant. Détail et preuves dans `coordination/CLAUDE-STATUS.md` ; re-revue attendue |
| LIVE-ISSUE-RECONCILIATION | CLAUDE | n/a | read-only | ACTIVE | 2026-08-27T04:41Z | Candidats suivis par numéro seul — issues #565, #568, #576 ; PR #567, #571. Poursuivre la reconnaissance live |
| AUD-CI-003 | CLAUDE | claude/aud-ci-003-004-gating-bloquant | .github/workflows/ci.yml; core/tests/bootstrap/test_ci_gating_contract.py | MERGED | 2026-08-27T04:41Z | PR #567. Mission terminée côté Claude ; le gel invoqué par #569 n'est plus opposé de notre côté |
| AUD-CI-004 | CLAUDE | claude/aud-ci-003-004-gating-bloquant | .github/workflows/ci.yml | MERGED | 2026-08-27T04:41Z | Couvert par la même PR #567 que AUD-CI-003 ; même levée de gel |
| AUD-CI-002 | CLAUDE | claude/aud-ci-002-pin-actions-sha | .github/workflows/ci.yml | QUEUED | 2026-08-27T04:41Z | Issue **#576**. Aucune affirmation sur ce que couvre ou ne couvre pas un oracle du dépôt n'est portée ici : une version antérieure de cette cellule en portait une, exacte au tour où elle a été écrite et mesurée fausse au tour suivant — cela se lit dans le dépôt, pas ici. Statut local `QUEUED` : mission non activée |
| AUD-CORE-005 | CLAUDE | n/a | read-only | BLOCKED | 2026-08-26T10:59Z | Issue #568 publiée ; décision demandée (restaurer / retirer / requalifier) avant tout code |
| AUD-CORE-006 | CLAUDE | claude/aud-core-006-chemins-hote-en-dur | audit/core-baseline | MERGED | 2026-08-27T02:14Z | PR #571. Mission terminée côté Claude, rien à suivre |
| AUD-CANON-001 | CLAUDE | n/a | read-only | BLOCKED | 2026-08-26T10:59Z | Gate #541 — décision Nathan attendue avant toute promotion canonique |
| AUD-CANON-002 | CLAUDE | n/a | read-only | BLOCKED | 2026-08-26T10:59Z | Gate #541 — décision Nathan attendue avant toute promotion canonique |

Valeurs Owner : `CODEX`, `CLAUDE`, `CHATGPT`, `NATHAN`, `UNASSIGNED`.

Valeurs Status : `QUEUED`, `ACTIVE`, `BLOCKED`, `REVIEW`, `READY_TO_MERGE`, `MERGED`, `TRANSFER`.

La colonne `Status` porte l'intention locale connue à `Updated UTC`, pas un miroir en direct de l'état GitHub d'une PR ou d'une issue : une ligne `REVIEW`/`ACTIVE` peut correspondre à une PR déjà mergée sans que cette table le reflète avant la prochaine mise au point, et le cas s'est déjà produit sur ce fichier. Le numéro de PR/issue donné dans `Next` est la clé vivante ; `gh pr view <n>` / `gh issue view <n>` fait foi, jamais la seule lecture de cette colonne.

Les scopes multiples sont séparés par `;`. Chemins relatifs uniquement.

Aucune ligne `CODEX_BOUND`, `PARKED_*` ou `NATHAN_DECISION` du backlog Claude n'est prise ici.
