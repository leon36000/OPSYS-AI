# OPSYS-AI Codex Loop Continuation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reprendre OPSYS-AI avec Codex comme seul implémenteur, transformer le candidat CLR-001 en livraison vérifiable, puis ne fusionner que si les preuves locales et GitHub sont réellement vertes.

**Architecture:** Une boucle séquentielle et répétable gère un seul worktree writer : état exact → reproduction ciblée → correction minimale → tests étroits → gates complets → revue indépendante scellée → PR → CI → fusion. Les reviewers externes servent uniquement d’oracle indépendant; aucun code n’est délégué à Claude, Ralph ou un autre agent.

**Tech Stack:** Python 3.12, pytest, mypy, Bandit, pip-audit, CodeQL, GitHub Actions, LiteLLM local authentifié, `civ_review.py`, `tally_reviews.py`, et `verify_proof_sealed.py`.

**Spec:** `AGENTS.md`, `START-HERE.md`, issue GitHub #518, `.opsys/core-control/2.3.0/REPOSITORY-CONTRACT.md`, `core/scripts/verify_proof_sealed.py`, et le candidat local CLR-001.

## Global Constraints

- Dépôt exact : `leon36000/OPSYS-AI`; compte GitHub : `leon36000`.
- Aucun commit direct sur `main`; fusion uniquement via une PR vérifiée.
- Aucun `--no-verify`, `|| true`, stub, secret committé ou preuve reconstruite après coup.
- Un seul worktree writer; les tests indépendants peuvent être parallélisés sans partager d’état.
- La revue PROOF reste indépendante : même prompt octet-identique, trois routes distinctes, raw outputs conservés, tally scripté.
- Une absence de preuve produit `BLOCKED-avec-raison`, jamais `DONE` implicite.

### Task 1: Rebase-free custody and loop setup

**Files:**
- Inspect: `AGENTS.md`, `.opsys/core-control/2.3.0/REPOSITORY-CONTRACT.md`, issue #518, `.github/workflows/core-ci.yml`.
- Create: `docs/superpowers/plans/2026-08-20-codex-loop-continuation.md`.

**Interfaces:**
- Consumes: `origin/main`, candidate `codex/clr-001-completion`, GitHub identity, authenticated LiteLLM metadata.
- Produces: exact commit/tree/diff identity and one active worktree writer.

- [x] **Step 1: Confirm repository, branch, worktree, and remote custody.**
- [x] **Step 2: Confirm no Claude/Ralph worker is required for the implementation loop.**
- [x] **Step 3: Confirm authenticated LiteLLM health and route metadata without printing secrets.**

### Task 2: Complete the CLR-001 evidence loop

**Files:**
- Inspect: `core/scripts/verify_proof_sealed.py`, `/home/pc1/proof-method/scripts/civ_review.py`, `/home/pc1/proof-method/scripts/tally_reviews.py`, `/home/pc1/proof-method/reviews/TEMPLATE-prompt-revue-neutre.md`.
- Create only after unanimous approval: `evidence/tasks/CLR-001/evidence.json`, `evidence/tasks/CLR-001/reviews/*.json`.

**Interfaces:**
- Consumes: final candidate diff, issue requirements, exact test receipts, three authenticated routes.
- Produces: a fresh evidence bundle linked to the exact final sealed diff, or a fail-closed blocker.

- [ ] **Step 1: Build a neutral context pack from the exact issue and diff.**
- [ ] **Step 2: Scan the final prompt pack for reviewer identity leakage and record its SHA-256.**
- [ ] **Step 3: Run `civ_review.py` with the three proven non-Claude routes.**
- [ ] **Step 4: Accept the evidence directory only if `tally_reviews.py` returns unanimous approval.**
- [ ] **Step 5: Populate the manifest with the fresh sealed code-diff SHA-256 and verify it locally.**

### Task 3: Publish a clean Codex PR and run the loop against CI

**Files:**
- Modify only through the active branch/PR and generated evidence files.
- Inspect: `.github/workflows/core-ci.yml`, `.github/workflows/ci.yml`, branch protection/rulesets.

**Interfaces:**
- Consumes: a verified local candidate and proof bundle.
- Produces: a remote PR whose checks run against the exact candidate.

- [ ] **Step 1: Run the final deterministic suite after evidence is added.**
- [ ] **Step 2: Push a dedicated `opsys-core/task/clr-001-codex-loop` branch.**
- [ ] **Step 3: Open/update one PR for issue #518 and wait for all checks.**
- [ ] **Step 4: Repair only fresh CI/Sonar findings attributed to this exact head, looping through RED → GREEN.**
- [ ] **Step 5: Merge only after proof-sealed, CI, Sonar exact-head status, and repository protection are verified.**

### Task 4: Final proof and handoff

**Files:**
- Update: `docs/superpowers/plans/2026-08-20-codex-loop-continuation.md`.
- Create: user-facing handoff under the projectless `outputs/` directory.

**Interfaces:**
- Consumes: merged or explicitly blocked final state.
- Produces: exact commit/tree, receipts, remaining risks, and next loop entry point.

- [ ] **Step 1: Re-run verification from the final remote head.**
- [ ] **Step 2: Append only an evidence-backed ledger entry or a BLOCKED reason.**
- [ ] **Step 3: Deliver the handoff without claiming unverified completion.**
