# Checks CI Core — état réel et noms à rendre required (C02-005)

Ce document accompagne `.github/workflows/core-ci.yml`. Il ne modifie **aucune**
configuration GitHub réelle (branch protection) — bascule en check *required*
= décision humaine séparée, hors périmètre de l'implémentation strictement
bornée de C02-005 (« documenter les noms exacts à rendre required dans GitHub »,
pas les rendre required par appel API).

## Constat mesuré avant cette tâche

Le workflow existant `.github/workflows/ci.yml` (job `gates`, seul check
`required` actuel en branch protection sur `main`) exécute `scripts/tests` et
chaque `Modules M/*/tests` en pytest séparé, mais **ne touche jamais
`core/tests/bootstrap/`** — vérifié en lisant les steps réels d'un run GitHub
Actions récent (PR #494, C02-004). Les tests C02-001→C02-004 (61 tests au
moment de la mesure) n'étaient donc exécutés par AUCUN CI réel : uniquement
vérifiés localement par l'Orchestrateur avant chaque merge. `core-ci.yml`
ferme ce trou pour `types` et `tests` ; les 3 autres catégories exigées par la
tâche restent honnêtement bloquées (voir tableau).

## Jobs de `core-ci.yml`

| Job (context GitHub) | État | Mécanisme réel |
|---|---|---|
| `types` | ✅ VERT (mécanisme réel) | `mypy==2.1.0` (version mesurée localement lors de l'établissement de la baseline C02-004) sur `core/`, gate `mypy-core` de `core/quality-gates.toml` via `evaluer_matrice()` (C02-004) — baseline 2 erreurs connues, jamais masquées ; seules les erreurs AU-DELÀ bloquent. |
| `tests` | ✅ VERT (mécanisme réel) | `pytest -q core/tests/bootstrap` — scope `core/` isolé, jamais combiné à `Modules M/*` (collision de noms de modules mesurée en C02-004 : `verif_coherence.py` dupliqué dans plusieurs `Modules M/*/docs/bmad/`). |
| `proof-sealed` | 🔴 ROUGE explicite (voulu) | Aucun mécanisme de vérification de scellement des Evidence Bundles/revues n'est câblé en CI à ce jour. Bloque avec message clair plutôt que de simuler un vert. |
| `security` | 🔴 ROUGE explicite (voulu) | Aucun scanner de sécurité (bandit, pip-audit, semgrep, …) n'est référencé nulle part dans ce dépôt (grep exhaustif au moment de C02-005). Le seul mécanisme de sécurité existant (gitleaks) tourne en hook git pré-commit **local**, hors CI GitHub Actions, jamais testé sur ce runner. |
| `pack-validation` | 🔴 ROUGE explicite (voulu) | Aucune validation de cohérence globale du pack bootstrap Core (toolchain lock C02-001 + dependency lock C02-002 + test runner C02-003 + quality gates C02-004, réunis) n'est câblée. |

Les 3 jobs ROUGE ne sont **pas des bugs** : c'est le comportement voulu de
cette tâche — « rendre les checks CI réellement bloquants » signifie qu'une
catégorie sans mécanisme réel doit être visiblement rouge, jamais un `pass`
silencieux qui ferait croire à une garantie qui n'existe pas (PROOF invariant
#4). Chacun est un point d'entrée explicite pour une tâche future dédiée.

## Ce qui devrait devenir `required` — et ce qui ne le peut pas encore

**Peuvent devenir `required` dès aujourd'hui** (mécanisme réel, déterministe,
déjà vert sur `main`) :
- `types`
- `tests`

**Ne doivent PAS devenir `required` avant qu'un mécanisme réel les remplace**
— les rendre required aujourd'hui bloquerait TOUT merge, en permanence, sans
qu'aucun code puisse jamais les satisfaire :
- `proof-sealed`
- `security`
- `pack-validation`

## Procédure pour rendre `types`/`tests` required (action humaine, hors périmètre C02-005)

```bash
gh api -X PUT repos/leon36000/OPSYS-AI/branches/main/protection/required_status_checks \
  -f strict=true \
  -f 'contexts[]=gates' \
  -f 'contexts[]=types' \
  -f 'contexts[]=tests'
```

(`gates` reconduit — ne jamais le retirer de la liste en l'ajoutant, sous
peine de désactiver le seul check déjà required aujourd'hui.) Cette commande
n'a **pas** été exécutée par C02-005 : c'est une modification de la
configuration de sécurité du dépôt, réservée à une décision humaine explicite.
