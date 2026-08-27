# OPSYS-AI Global Codex Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebaseline OPSYS-AI at the exact current GitHub state, complete the master audit, then repair the highest-risk reproducible findings through small Codex-only loops.

**Architecture:** The work is strictly staged: custody and read-only audit first, then a machine-readable finding register and dependency DAG, then one reversible production fix at a time. A single Codex worktree is the only writer; every change follows RED → minimal fix → GREEN → broad gates → independent review.

**Tech Stack:** Python 3.12, pytest, mypy, Bandit, pip-audit, CodeQL, GitHub Actions, `gh`, the repository audit harness, and the local LiteLLM gateway.

**Spec:** `AGENTS.md`, `README.md`, `docs/canon/REGLES.md`, issue #539 and its child issues #541–#558, issue #560, `core/quality-scopes.toml`, and the user’s Codex-only execution decision.

## Global Constraints

- `origin/main` is the immutable audit baseline until a reviewed PR is merged.
- Do not modify `main`, rewrite history, force-push, or close issues based on narrative status.
- Audit missions #539 and #541–#546 are read-only until their evidence and boundaries are recorded.
- Do not treat passing skeleton tests as proof that M1–M10 product behavior is complete.
- GPT‑5.6 Sol approval is required for material implementation decisions once its route is available; its absence is recorded as `PENDING_ROUTE`, never simulated.
- Daybreak Blue is required for security approval once its route is available; local Bandit/CodeQL results remain evidence, not Daybreak approval.
- No Claude/Ralph implementation or delegation is used.

### Task 1: Rebaseline custody and route admission

**Files:**
- Inspect: `AGENTS.md`, `README.md`, `START_HERE.md`, `.github/workflows/`, `audit/`, `.opsys/core-control/2.3.0/`.
- Create: an external snapshot under `/tmp` and a machine-readable audit receipt only if the repository’s existing harness supports it.

**Interfaces:**
- Consumes: `origin/main`, current local candidate, GitHub API, and local gateway metadata.
- Produces: exact commit/tree, divergence, issue DAG, route availability, and a no-secret custody receipt.

- [ ] **Step 1: Capture exact GitHub custody.**

  Run `git fetch --prune origin main`, `git rev-parse origin/main`, `git rev-parse origin/main^{tree}`, and `gh repo view leon36000/OPSYS-AI`.

- [ ] **Step 2: Record the active issue DAG.**

  Read #539–#558 and #560; classify each issue as executable, read-only audit, blocked dependency, or external approval boundary.

- [ ] **Step 3: Admit reviewer routes without exposing secrets.**

  Query `/v1/models` using the local credential file without printing the key. Record GPT‑5.6 Sol and Daybreak Blue as available only when their exact model IDs are returned and smoke calls succeed.

### Task 2: Revalidate the master audit read-only

**Files:**
- Inspect: `audit/`, `registries/`, `reviews/`, `evidence/`, `core/`, `scripts/`, `tools/`, and `Modules M/`.
- Test: existing `audit/tests/` and `audit/core-baseline/tests/`.

**Interfaces:**
- Consumes: the current exact tree, not old issue conclusions.
- Produces: fresh A1/A2/A3/A4/A5/A6 findings with evidence refs and explicit `NEEDS_EVIDENCE` boundaries.

- [ ] **Step 1: Run the audit harness against the current tree.**

  Use the repository’s documented audit commands and capture exit codes, output hashes, and the exact tree in `/tmp` receipts.

- [ ] **Step 2: Revalidate authority and canon claims.**

  Compare `README.md`, `START_HERE.md`, `AGENTS.md`, `00-DIGEST.md`, `docs/canon/REGLES.md`, `audit/core-baseline/AUTHORITY-MAP.csv`, and live issue #523 requirements. Keep historical text classified; do not silently promote it.

- [ ] **Step 3: Measure Core and M1–M10 maturity.**

  Trace public seams, persistence, security, idempotence, tests, and integrations. Report `PARTIAL` or `NEEDS_EVIDENCE` where a passing skeleton test does not exercise product behavior.

- [ ] **Step 4: Audit CI, proof, security, supply chain, and license boundaries.**

  Inspect required checks, action pinning, lock usage, SAST/SCA scope, evidence binding, secrets, CODEOWNERS, and license obligations. Keep security approval pending Daybreak Blue.

### Task 3: Build the master finding register and repair DAG

**Files:**
- Create or update only the repository’s canonical audit artifacts after confirming their schema and ownership.
- Inspect: `audit/contrats.py`, `audit/rapport.py`, `audit/constats/*.json`, `.opsys/core-control/2.3.0/TASK-REGISTRY.jsonl`, and `DEPENDENCY-GRAPH.json`.

**Interfaces:**
- Consumes: fresh Task 2 receipts.
- Produces: deduplicated findings, severity, confidence, owner, prerequisite, rollback, evidence status, and one next action.

- [ ] **Step 1: Validate existing finding schemas before writing.**
- [ ] **Step 2: Reproduce each critical/high finding or mark it `NEEDS_EVIDENCE`.**
- [ ] **Step 3: Order fixes by dependency, starting with governance/security correctness before product breadth.**
- [ ] **Step 4: Do not close or relabel GitHub issues until the exact evidence and required external approvals exist.**

### Task 4: Execute one repair loop at a time

**Files:**
- Modify only the files named by the selected issue’s contract.
- Test: the selected issue’s named RED suite, then the proportionate repository gates.

**Interfaces:**
- Consumes: one finding with a deterministic reproduction and an approved scope.
- Produces: one small commit, fresh tests, rollback receipt, and review-ready diff.

- [ ] **Step 1: Write the named regression test and observe RED for the intended cause.**
- [ ] **Step 2: Implement the smallest fail-closed fix without suppressions or unrelated cleanup.**
- [ ] **Step 3: Run focused GREEN checks and inspect the diff.**
- [ ] **Step 4: Run broad gates, security checks, and rollback before opening a PR.**
- [ ] **Step 5: Obtain GPT‑5.6 Sol approval and Daybreak Blue security approval when the routes are available; otherwise keep the change explicitly pending.**

### Task 5: Publish only an evidence-backed result

**Files:**
- Inspect: GitHub PR status, branch protection, evidence verifier, and current issue state.
- Create: a final checkpoint under `outputs/` with exact commit/tree/hash values.

**Interfaces:**
- Consumes: integrated branch plus independent review receipts.
- Produces: a PR/merge only when all required checks and approvals are real; otherwise a precise blocker.

- [ ] **Step 1: Re-run verification on the exact candidate head.**
- [ ] **Step 2: Verify review identities, prompt/diff hashes, security approval, and required checks.**
- [ ] **Step 3: Push and merge only through the protected PR path after all gates are green.**
- [ ] **Step 4: Capture post-merge replay and the next single action.**
