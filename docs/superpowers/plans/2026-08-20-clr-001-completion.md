# CLR-001 Completion Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Revalidate the exact CLR-001 candidate, close only reproducible defects, and produce a replayable local handoff that is either evidence-backed or explicitly blocked.

**Architecture:** Keep the existing 19-file CLR-001 change scoped to Core quality enforcement, with `core/quality-scopes.toml` as the single scope contract. Work from commit `5d9a721442f77a6cb930f9fe053197adf51bcb11` in the isolated `codex/clr-001-completion` worktree; every change must be TDD-backed and validated against the exact `main` base `86cd9b3bf98d67824621a4bf70ced47659181bc1`.

**Tech Stack:** Python 3.12, pytest 9.1.1, PyYAML 6.0.1, psycopg 3.2.3, uv, mypy, Bandit, pip-audit, CodeQL when available, GitHub Actions contracts, and the repository PROOF evidence tooling.

**Spec:** `/home/pc1/Bureau/dossier-reprise-projets/04-opsys-ai/START-HERE.md`, PR #526 body, issue #518 contract, `AGENTS.md`, `.opsys/core-control/2.3.0/REPOSITORY-CONTRACT.md`, and `docs/core/NO-STUB-QUALITY-POLICY.md`.

## Global Constraints

- Work only from the exact candidate commit `5d9a721442f77a6cb930f9fe053197adf51bcb11` until a new candidate is deliberately created.
- Never modify the existing ForgeAI/Claude worktrees or the clean `main` checkout.
- Never add an Evidence Bundle until the exact final diff, rollback, prompt neutrality, and three-vendor routing are proven.
- Never rewrite an old `evidence/tasks/CI-HARDENING-001/` proof to cover CLR-001; a new task ID and fresh reviewer outputs are required.
- Preserve the scope boundary: no M1–M10 business logic and no silent dependency or workflow exemptions.
- Never use `--no-verify`, `|| true`, direct pushes to `main`, or a merge before all deterministic gates and sealed review requirements are green.

---

### Task 1: Freeze the exact candidate and establish a reproducible baseline

**Files:**
- Create: `docs/superpowers/plans/2026-08-20-clr-001-completion.md`
- Inspect: `AGENTS.md`, `.opsys/core-control/2.3.0/REPOSITORY-CONTRACT.md`, `core/quality-scopes.toml`, `.github/workflows/core-ci.yml`

**Interfaces:**
- Consumes: candidate commit `5d9a721…`, base commit `86cd9b3…`, local GitHub repository `leon36000/OPSYS-AI`.
- Produces: exact commit/tree/diff identity, clean worktree status, installed locked test environment, and baseline receipts.

- [ ] **Step 1: Verify identity and cleanliness**

```bash
git rev-parse HEAD
git rev-parse HEAD^{tree}
git status --short --branch
gh api user --jq .login
gh repo view leon36000/OPSYS-AI --json nameWithOwner,defaultBranchRef
```

Expected: `5d9a721442f77a6cb930f9fe053197adf51bcb11`, tree `99a6c145f4670a89a06f5bd12637ca27e422c2ba`, clean branch, login `leon36000`, and repository `leon36000/OPSYS-AI`.

- [ ] **Step 2: Install and verify the locked local dependencies**

```bash
uv sync --project core
python3 -m pytest --version
python3 -c 'import yaml, psycopg; print(yaml.__version__, psycopg.__version__)'
```

Expected: pytest `9.1.1`, PyYAML `6.0.1`, and psycopg `3.2.3` are importable.

- [ ] **Step 3: Record the initial deterministic baseline**

```bash
python3 -m pytest -q scripts/tests core/tests/bootstrap core/tests/architecture core/tests/persistence
python3 scripts/structure_lint.py
git diff --check 86cd9b3bf98d67824621a4bf70ced47659181bc1..HEAD
```

Expected: baseline failures, if any, are classified as product, test, or environment failures before edits; no failure is silently reclassified.

### Task 2: Reproduce and close the named CLR-001 RED contracts

**Files:**
- Inspect: `core/tests/bootstrap/test_clr001_review_regressions.py`, `core/tests/bootstrap/test_ci_contract.py`, `scripts/tests/test_no_stub_gate.py`, `scripts/tests/test_quality_scope_contract.py`, `core/scripts/run_codeql_scan.py`, `core/scripts/run_pack_validation.py`
- Modify only if a fresh RED is confirmed: the smallest affected implementation and its regression test

**Interfaces:**
- Consumes: the exact candidate and issue #518’s named scanner-scope and rollback contracts.
- Produces: focused GREEN evidence for scanner argument coverage, scope omission detection, fail-closed parsing, and any confirmed regression.

- [ ] **Step 1: Locate the named RED tests and execute them independently**

```bash
rg -n "SCOPE_ROOT_OMITTED|scanner|CodeQL|LGTM_INDEX_FILTERS|rollback|base_ref|ORIG_HEAD" core/tests scripts/tests docs
python3 -m pytest -q core/tests/bootstrap/test_clr001_review_regressions.py
python3 -m pytest -q scripts/tests/test_quality_scope_contract.py
python3 -m pytest -q scripts/tests/test_no_stub_gate.py
```

Expected: each result is captured with its exit status; a green result is not changed merely to add redundant code.

- [ ] **Step 2: If and only if a test fails for a product cause, add the smallest failing regression test**

```bash
python3 -m pytest -q path/to/test.py -k exact_regression_name
```

Expected: the test fails against the unchanged candidate for the intended reason, not because of a missing package or malformed fixture.

- [ ] **Step 3: Implement the minimal correction and rerun the focused test**

```bash
python3 -m pytest -q path/to/test.py -k exact_regression_name
git diff --check
```

Expected: focused GREEN with no unrelated files or scope changes.

- [ ] **Step 4: Re-run all affected contract tests after any refactor**

```bash
python3 -m pytest -q core/tests/bootstrap scripts/tests
```

Expected: zero failures and no skipped tests introduced by the candidate change.

### Task 3: Prove exact rollback and final candidate identity

**Files:**
- Inspect: PR #526 commits/body, issue #518 comments, `core/quality-scopes.toml`, `evidence/tasks/CI-HARDENING-001/evidence.json`
- Create only if the rollback protocol is genuinely executed: an external receipt under `/tmp` or the configured proof-method receipt directory

**Interfaces:**
- Consumes: final local candidate and its exact diff against `86cd9b3…`.
- Produces: reversible patch check, RED-before-GREEN transcript, matching final tree, and a fresh diff SHA-256.

- [ ] **Step 1: Capture the final diff and verify reverse applicability without mutating the worktree**

```bash
git diff --binary 86cd9b3bf98d67824621a4bf70ced47659181bc1..HEAD > /tmp/opsys-clr001-final.patch
git apply -R --check /tmp/opsys-clr001-final.patch
```

Expected: reverse check succeeds; the original tree remains unchanged.

- [ ] **Step 2: Execute the documented rollback only in a disposable clone/worktree**

```bash
git apply -R /tmp/opsys-clr001-final.patch
python3 -m pytest -q path/to/the_named_red_test.py -k exact_regression_name
git apply /tmp/opsys-clr001-final.patch
python3 -m pytest -q path/to/the_named_red_test.py -k exact_regression_name
```

Expected: the named RED is observed on the reverted tree, GREEN is restored after reapplying, and commit/tree hashes before and after match the recorded candidate.

- [ ] **Step 3: Recompute the candidate hash from the exact final diff**

```bash
python3 - <<'PY'
import hashlib, subprocess
diff = subprocess.run(
    ['git', 'diff', '86cd9b3bf98d67824621a4bf70ced47659181bc1..HEAD', '--',
     'core/', '.github/workflows/core-ci.yml', '.github/workflows/ci.yml', 'scripts/'],
    check=True, capture_output=True, text=True,
).stdout.encode()
print(hashlib.sha256(diff).hexdigest())
PY
```

Expected: the value is saved as a candidate fact, never copied from an old evidence file.

### Task 4: Run the complete local quality gates

**Files:**
- Inspect only: `.github/workflows/ci.yml`, `.github/workflows/core-ci.yml`, `core/scripts/run_security_scan.py`, `core/scripts/run_pack_validation.py`

**Interfaces:**
- Consumes: the final exact candidate.
- Produces: fresh outputs for types, tests, security, pack validation, gates, isolation, style, and diff cleanliness.

- [ ] **Step 1: Run the project’s deterministic quality gates**

```bash
python3 scripts/structure_lint.py
python3 scripts/ledger_append.py verify
python3 scripts/statut_lint.py
python3 -m pytest -q scripts/tests
python3 core/scripts/check_module_isolation.py
```

- [ ] **Step 2: Run Core tests, type checks, security, and pack validation**

```bash
python3 -m pytest -q core/tests/bootstrap core/tests/architecture core/tests/persistence
python3 core/scripts/run_security_scan.py
python3 core/scripts/run_pack_validation.py
```

Expected: each command exits zero; missing optional tools such as CodeQL remain an explicit blocker rather than a fabricated pass.

- [ ] **Step 3: Run the full repository test matrix in the same isolated environment**

```bash
python3 -m pytest -q scripts/tests
python3 -m pytest -q "Modules M/M7-marketing/tests"
for module in M1-front-office M2-revenue-crm M3-estimation M4-field-ops M5-financecore M6-material-control M8-analytics M9-strategic-intelligence M10-memoire; do
  python3 -m pytest -q "Modules M/$module/tests"
done
```

Expected: all configured suites pass, or every failure is reported with a precise product/environment classification.

### Task 5: Prove or block the sealed review admission

**Files:**
- Create only after all earlier tasks are green: `evidence/tasks/CLR-001/evidence.json`, `evidence/tasks/CLR-001/reviews/*.json`, and the raw review receipts outside the repository
- Inspect: `/home/pc1/proof-method/scripts/civ_review.py`, `/home/pc1/proof-method/scripts/tally_reviews.py`, `reviews/TEMPLATE-prompt-revue-neutre.md`

**Interfaces:**
- Consumes: exact final commit/tree/diff, task specification, raw reviewer responses, and three distinct upstream vendor routes.
- Produces: a new evidence bundle whose hashes bind to the final diff, or a machine-readable BLOCKED result if the reviewer runtime or routing proof is unavailable.

- [ ] **Step 1: Verify reviewer runtime admission before any review call**

```bash
test -n "$LITELLM_BASE_URL"
test -n "$LITELLM_API_KEY"
python3 - <<'PY'
import os, urllib.request
base = os.environ['LITELLM_BASE_URL'].rstrip('/')
with urllib.request.urlopen(base + '/health', timeout=10) as response:
    print(response.status)
PY
```

Expected: the gateway is reachable, authenticated, and able to expose three distinct upstream routes; otherwise stop with `BLOCKED_REVIEW_RUNTIME`.

- [ ] **Step 2: Build a byte-identical neutral review pack for the exact final candidate**

```bash
sha256sum /tmp/opsys-clr001-final.patch
python3 - <<'PY'
from pathlib import Path
print(Path('reviews/TEMPLATE-prompt-revue-neutre.md').read_text(encoding='utf-8'))
PY
```

Expected: the pack includes the exact commit, tree, diff hash, requirements, test outputs, known limits, and no reviewer identity or previous verdict.

- [ ] **Step 3: Run the repository’s sealed reviewer dispatcher with three distinct vendors**

```bash
python3 /home/pc1/proof-method/scripts/civ_review.py \
  --story /tmp/opsys-clr001-reviews \
  --pack /tmp/opsys-clr001-pack.md \
  --models "$CIV_MODELS" \
  --attendu 3
```

Expected: three raw outputs, three tracked serving identities, a common prompt SHA, and exactly three distinct vendors; any fallback, missing trace, malformed verdict, or vendor collision is a blocker.

- [ ] **Step 4: Tally the sealed reviews and create the new bundle only on unanimous approval**

```bash
python3 /home/pc1/proof-method/scripts/tally_reviews.py /tmp/opsys-clr001-reviews --min-vendors 3
```

Expected: `3/3 APPROVE`, zero CRITICAL/MAJOR objections, and a task evidence manifest whose `code_diff_sha256` equals the freshly computed final diff hash.

### Task 6: Final verification and handoff

**Files:**
- Modify only the isolated worktree branch and local evidence receipts authorized by the preceding tasks
- Create: `/home/pc1/Bureau/OPSYS-AI-CLR-001-HANDOFF-2026-08-20` only as a final user-facing handoff if all required evidence exists

**Interfaces:**
- Consumes: final candidate, gate outputs, and evidence verdict.
- Produces: a precise handoff with commit/tree/diff, changed files, verification commands, blockers, and explicitly unperformed GitHub mutations.

- [ ] **Step 1: Run final source and repository checks**

```bash
git diff --check
git status --short --branch
python3 -m pytest -q scripts/tests core/tests/bootstrap core/tests/architecture core/tests/persistence
python3 core/scripts/verify_proof_sealed.py --task CLR-001 --min-vendors 3 --diff-base 86cd9b3bf98d67824621a4bf70ced47659181bc1
```

Expected: all local gates are green and proof verification binds to the same exact candidate; otherwise status is BLOCKED, not DONE.

- [ ] **Step 2: Re-read the final diff and classify every remaining gap**

```bash
git diff --stat 86cd9b3bf98d67824621a4bf70ced47659181bc1..HEAD
git diff --name-status 86cd9b3bf98d67824621a4bf70ced47659181bc1..HEAD
```

Expected: no unrelated files, no M1–M10 logic, no new secrets, no undocumented bypass, and no stale proof hash.

- [ ] **Step 3: Prepare the handoff without publishing externally**

The handoff must state the exact candidate identity, tests and exit codes, proof verdict, unresolved blockers, and that no push, merge, deployment, or GitHub issue mutation was performed unless explicitly authorized in a later step.
