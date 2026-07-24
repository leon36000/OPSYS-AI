# Design — Cursor Method Enforcement (Hybride C / Approche 1)

**Date :** 2026-07-23  
**Statut :** DRAFT — en attente validation Nathan  
**Auteur lane :** Cursor (IDE secondaire)  
**Projet :** OPSYS-AI + projets futurs  
**Décision produit :** Hybride C — couche A opérationnelle maintenant ; chantier B (Phases 0–8 ForgeAI PROOF IDE System) reste Claude Code / stories pack

---

## 1. Problème

Les méthodologies ForgeAI / PROOF sont présentes en documents (`VISION.md`, `FORGE_METHOD.md`, `IMPLEMENTATION_SPEC.md`, pack VALIDATED) et partiellement en tooling (`~/proof-method`), mais **pas enforced** dans les sessions Cursor sur OPSYS-AI. Résultat : posture déclarative (« adopté ») ≠ comportement automatique fail-closed.

## 2. Objectif (couche A)

Rendre **100 % opérationnelle** la couche d’enforcement méthodologique pour Cursor sur :

1. **OPSYS-AI** (immédiat)
2. **Tout projet futur** via un template bootstrap portable

Sans :

- claimer ou modifier la story `P0-1-installation-kit`
- implémenter le CLI `forge` / Phases 1–8 du pack (chantier B)
- devenir un second orchestrateur concurrent de Claude Code

### Critère de succès A (testable)

```text
bash scripts/cursor-method-doctor.sh
→ exit 0
```

Et :

- règles Cursor `alwaysApply` présentes et non vides
- nouvelle session Cursor refuse l’écriture produit si préflight story/claim/chemins échoue (`BLOCKED`)
- template bootstrap documenté pour un repo neuf
- chemins claimés P0-1 inchangés par cette story Cursor

## 3. Non-objectifs (couche B — hors scope)

- `forge install|init|doctor|repair` Python complet
- Adaptateurs Codex / Copilot Phase 6
- Context Plane Headroom/LLMLingua runtime (Phase 5)
- Lab DSPy/GEPA exécutable (Phase 7)
- Remplir `model_id` LiteLLM / secrets keyring (Nathan / ops)
- Réécrire `AGENTS.md` / `CLAUDE.md` / `config.ini.example` (P0-1)

## 4. Contexte et contraintes

| Contrainte | Source |
|---|---|
| Claude Code lead Phase 0→2 pack + story P0-1 active | `START_HERE.md`, `stories/P0-1-installation-kit.md` |
| Cursor = secondaire ; pairing Nathan pour écriture hors story | `.cursor/rules/00-forge.mdc` |
| CIV : Grok natif exclu de self-review | `RECONCILIATION.md`, config role.parallel |
| Kit PROOF STACK v1.1 gouverne exécution produit OPSYS-AI ; pack = méthode IDE séparée | story P0-1 |
| Pas de secrets dans Git / config | `FORGE_METHOD.md`, security.ini |
| User rule : pas de commit sans demande explicite | Cursor user rules |

## 5. Architecture cible (A)

```text
OPSYS-AI/
├── .cursor/
│   ├── rules/
│   │   ├── 00-forge.mdc              # adaptateur Cursor (existant, conserver)
│   │   ├── 10-proof-operational.mdc  # NEW — PROOF + Forge Design + Superpowers + gates
│   │   └── 20-synergy-ide.mdc        # NEW — anti-collision multi-IDE + claims
│   ├── CURSOR-CALIBRATION.md         # existant, mettre à jour après doctor vert
│   └── templates/                    # optional mirror
├── scripts/
│   └── cursor-method-doctor.sh       # NEW — gate A
├── templates/
│   └── cursor-forge-method/          # NEW — bootstrap projets futurs
│       ├── README.md
│       ├── bootstrap.sh
│       └── rules/                    # copies des 00/10/20
└── docs/superpowers/specs/
    └── 2026-07-23-cursor-method-enforcement-design.md  # ce fichier
```

Pont optionnel (soft) : si `~/proof-method/scripts/` existe, `doctor` les détecte et les recommande ; **pas** de dépendance dure au path home.

## 6. Comportements enforceés (règles)

### 6.1 `10-proof-operational.mdc` (alwaysApply)

- Sorties autorisées uniquement : `DONE`, `BLOCKED`, `REOPENED`, `CANCELLED`
- Préflight obligatoire avant toute écriture code/docs produit (story, claim, branche, allowed_paths, critères, preuves attendues)
- Pipeline rappelé (pas de saut silencieux)
- Forge Design obligatoire pour non-trivial / T2+ (brief→stories) ; **sans** installer BMAD
- Superpowers : invoquer skills process applicables avant action
- TDD ; TDAD pour T2/T3
- No-stub / no-fake-done / no `--no-verify` / no commit direct `main`
- Context C0/C1 : jamais compression avec perte
- DSPy/GEPA : proposition lab only ; interdiction auto-promotion canon/gates/T3
- `DONE` exige preuves exécutées (commandes + exit codes) — pas de claim verbal

### 6.2 `20-synergy-ide.mdc` (alwaysApply)

- Avant écriture : lister `stories/*.md` et refuser claim concurrent sur story `CLAIMED` / branche déjà assignée à un autre IDE
- Claude Code = orchestrateur natif pack ; Cursor n’ouvre pas Phase 0–2 pack en parallèle
- Grok/Composer = modèles natifs ; jamais routés comme alias LiteLLM `forge-*`
- Exclusion CIV Grok de revue sur PR co-écrites Grok
- Chemins interdits tant que P0-1 ouverte (sauf amendement Nathan) :  
  `AGENTS.md`, `CLAUDE.md`, `config.ini.example`, `registries/ledger/*.jsonl`, `docs/decisions/ADR-0001-*.md`

### 6.3 `00-forge.mdc`

Inchangé sauf si contradiction détectée ; reste la note d’adaptateur mince.

## 7. `scripts/cursor-method-doctor.sh`

Vérifications (fail-closed, exit ≠ 0 si manquant) :

1. Fichiers méthode pack présents : `VISION.md`, `FORGE_METHOD.md`, `IMPLEMENTATION_SPEC.md`, `START_HERE.md`
2. Règles Cursor : `00-forge.mdc`, `10-proof-operational.mdc`, `20-synergy-ide.mdc`
3. `.forge/config.ini` existe ; **aucun** littéral `sk-` / `sk-forge-` dedans
4. Working tree : alerte (non bloquante si story P0-1 active) si `config.ini.example` contient encore `sk-forge-` — message pointe vers P0-1
5. Branche courante + stories claimées affichées (informational)
6. Soft-check : `~/proof-method/scripts/ledger_append.py` présent → OK_OPTIONAL
7. Soft-check : LiteLLM readiness URL depuis config (curl timeout court) → WARN si down, pas FAIL si offline volontaire

Sortie : résumé PASS/WARN/FAIL + code exit.

## 8. Template projets futurs

`templates/cursor-forge-method/bootstrap.sh <repo_root>` :

1. Crée `.cursor/rules/` avec 00/10/20
2. Copie `cursor-method-doctor.sh` → `scripts/`
3. Crée `.forge/` minimal si absent (config depuis `config.ini.example` **sanitisé**, jamais de clé)
4. Écrit un `CURSOR-CALIBRATION.md` stub
5. Affiche : « Ouvrir ce dossier comme racine workspace Cursor »

Ne modifie pas `AGENTS.md` existant sans flag `--force-agents` (désactivé par défaut).

## 9. Story Cursor (cette livraison)

Créer `stories/C-CUR-1-method-enforcement.md` :

- Tier : **T1**
- Owner : Cursor / Grok
- Branch suggérée : `story/C-CUR-1-method-enforcement` **ou** travail en worktree isolé si P0-1 occupe le checkout courant
- allowed_paths : `.cursor/**`, `scripts/cursor-method-doctor.sh`, `templates/cursor-forge-method/**`, `docs/superpowers/specs/**`, `stories/C-CUR-1-method-enforcement.md`
- forbidden_paths : périmètre P0-1 listé §6.2

**Anti-collision checkout :** si le working tree est déjà sur `story/P0-1-installation-kit` avec WIP Claude, Cursor doit :

1. créer une branche/worktree dédiée `story/C-CUR-1-method-enforcement`, **ou**
2. n’écrire que dans allowed_paths et laisser Claude merger/rebase — **préférer worktree** pour zéro collision index

## 10. Preuves attendues (DONE A)

| # | Preuve | Commande / artefact |
|---|---|---|
| 1 | Doctor vert | `bash scripts/cursor-method-doctor.sh` → 0 |
| 2 | Règles présentes | `test -f` ×3 rules |
| 3 | Template bootstrap dry-run | `bootstrap.sh /tmp/forge-method-smoke && doctor` → 0 |
| 4 | Aucun secret introduit | `rg 'sk-forge-'` sur allowed_paths Cursor → vide |
| 5 | P0-1 non altéré par ce diff | `git diff` hors allowed_paths vide pour fichiers P0-1 |

Revue : pas d’auto-approve ; tally CIV si merge vers main (profil Team) — hors scope immédiat si pas de merge demandé.

## 11. Risques

| Risque | Mitigation |
|---|---|
| Collision WIP P0-1 | Worktree / allowed_paths stricts |
| Règles Cursor non chargées si workspace = parent `Repo/` | Doc : ouvrir `OPSYS-AI` comme racine ; doctor WARN si cwd ≠ repo OPSYS |
| Double autorité AGENTS (kit vs pack) | Rules pointent FORGE_METHOD + story active ; ne pas réécrire AGENTS |
| Fausse impression que Phase 6 est DONE | Calibration + doctor affichent `LAYER_A_ONLY` |

## 12. Décisions figées (cette spec)

1. Approche **1** (pack portable Cursor) + pont soft `~/proof-method`
2. Hybride **C** (A now / B later)
3. Pas de commit automatique (attendre demande Nathan)
4. DSPy/GEPA = garde-fou only en A
5. Story id : `C-CUR-1`

## 13. Self-review checklist (spec)

- [x] Pas de placeholder `TODO` / `TBD` bloquant dans les livrables A
- [x] Périmètre A vs B explicite
- [x] Chemins allowed/forbidden listés
- [x] Critère doctor exit 0
- [x] Anti-collision P0-1
- [x] Projets futurs = template bootstrap
- [ ] Validation Nathan sur ce fichier avant implémentation

---

## 14. Prochaine étape après validation

1. Skill `writing-plans` → plan d’implémentation atomique  
2. Exécution TDD-light : doctor d’abord (RED si rules manquantes) → ajouter rules/template → GREEN  
3. Rapport `PREUVE:` / `BLOCKED:`

**Demande :** Nathan, valide ce fichier (`docs/superpowers/specs/2026-07-23-cursor-method-enforcement-design.md`) pour passer au plan + implémentation.
