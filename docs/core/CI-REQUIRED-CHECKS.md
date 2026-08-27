# Checks CI Core — état réel et noms à rendre required (C02-005 + chantier CI-hardening)

Ce document accompagne `.github/workflows/core-ci.yml`. Il ne modifie **aucune**
configuration GitHub réelle (branch protection) — bascule en check *required*
= décision humaine séparée.

## Constat mesuré avant C02-005

Le workflow existant `.github/workflows/ci.yml` (job `gates`, seul check
`required` actuel en branch protection sur `main`) exécute `scripts/tests` et
chaque `Modules M/*/tests` en pytest séparé, mais **ne touche jamais
`core/tests/bootstrap/`** — vérifié en lisant les steps réels d'un run GitHub
Actions récent (PR #494, C02-004). Les tests C02-001→C02-004 (61 tests au
moment de la mesure) n'étaient donc exécutés par AUCUN CI réel : uniquement
vérifiés localement par l'Orchestrateur avant chaque merge. `core-ci.yml`
a fermé ce trou pour `types` et `tests` ; les 3 autres catégories exigées par
C02-005 sont restées honnêtement bloquées (placeholders `exit 1`) jusqu'au
chantier CI-hardening (ci-dessous) qui leur a construit un mécanisme réel.

## MISE À JOUR (chantier CI-hardening, PR #516) — les 3 placeholders sont désormais réels

Les 3 jobs listés ci-dessous comme "🔴 ROUGE explicite (voulu)" dans la
version originale de ce document (C02-005) sont **remplacés par des
mécanismes réels, VERTS**, revus par 4 voix indépendantes (consensus 3
vendors distincts, cf. `evidence/tasks/CI-HARDENING-001/`) :

- **`security`** : bandit 1.9.4 + pip-audit 2.10.1 (`core/scripts/run_security_scan.py`),
  scope `core/src/` + `core/scripts/`.
- **`pack-validation`** : rejoue toolchain (C02-001) + dépendances (C02-002) +
  runner hermétique (C02-003) + `structure_lint.py`
  (`core/scripts/run_pack_validation.py`).
- **`proof-sealed`** : le vérificateur lie le hash de diff à `core/`,
  `tools/proof/`, `.opsys/tools/github-control/`, aux 2 workflows CI et à
  `scripts/`. Il exige un Evidence Bundle committé sous
  `evidence/tasks/<ID>/`, cryptographiquement lié au diff réel
  (`code_diff_sha256`) et à un manifeste bijectif des verdicts de revue
  (`reviews{nom:sha256}`) (`core/scripts/verify_proof_sealed.py`). Les alias
  de reviewer connus y sont associés explicitement à leur fournisseur ; un
  alias inconnu ne doit jamais être présenté comme une identité fournisseur
  prouvée.

  Le déclencheur `CODE_CHANGE` de `core-ci.yml` reste temporairement plus
  étroit pour les modifications limitées à `tools/proof/` ou au contrôle GitHub
  : le fichier est possédé par la PR #515. Ce n'est pas un vert implicite ;
  l'alignement est tracé et bloqué par ownership dans l'issue #573 avant toute
  affirmation de couverture CI complète.

**CodeQL** (SAST approfondi) a aussi été ajouté — mais **local uniquement**
(`core/scripts/run_codeql_scan.py`), **pas câblé en CI** : le bundle CLI
(578 Mo, installation manuelle) ajouterait un coût réel à chaque run,
question non tranchée unilatéralement (voir « Câblage CI de CodeQL » ci-dessous).

### Mise à jour #572 — dette CodeQL de `main`

Sur `origin/main` `5a155f9`, le scan local mesurait 36 findings bruts : 13
justifiés et 23 non alloués. Le correctif #572 élimine les 23 causes sans
ajouter de baseline, d'allowlist ou de suppression de contrôle. Le résultat
attendu sur son SHA candidat est donc 13 justifiés et **0 non alloué**.

## Jobs de `core-ci.yml` (état courant)

| Job (context GitHub) | État | Mécanisme réel |
|---|---|---|
| `types` | ✅ VERT | `mypy==2.1.0` sur `core/`, gate `mypy-core` de `core/quality-gates.toml` via `evaluer_matrice()` (C02-004) — baseline 2 erreurs connues, jamais masquées. |
| `tests` | ✅ VERT | `pytest -q core/tests/bootstrap core/tests/architecture core/tests/persistence` — scope `core/` isolé, jamais combiné à `Modules M/*`. |
| `security` | ✅ VERT | Voir « MISE À JOUR » ci-dessus. |
| `pack-validation` | ✅ VERT | Voir « MISE À JOUR » ci-dessus. |
| `proof-sealed` | ✅ VERT | Voir « MISE À JOUR » ci-dessus. |

## Ce qui peut devenir `required`

Les 5 jobs sont désormais des mécanismes réels, déterministes, vérifiés VERT
— tous candidats à `required`. **Décision de bascule non exécutée par ce
chantier** (modification de la configuration de sécurité du dépôt, réservée
à une décision humaine explicite — même discipline que C02-005).

```bash
gh api -X PUT repos/leon36000/OPSYS-AI/branches/main/protection/required_status_checks \
  -f strict=true \
  -f 'contexts[]=gates' \
  -f 'contexts[]=types' \
  -f 'contexts[]=tests' \
  -f 'contexts[]=security' \
  -f 'contexts[]=pack-validation' \
  -f 'contexts[]=proof-sealed'
```

(`gates` reconduit — ne jamais le retirer de la liste en l'ajoutant, sous
peine de désactiver le seul check déjà required aujourd'hui.)

## Câblage CI de CodeQL — question ouverte pour Nathan

CodeQL fonctionne réellement en LOCAL (`core/scripts/run_codeql_scan.py`,
VERT — 13 faux positifs justifiés individuellement, 0 finding non alloué)
mais n'est PAS câblé dans `core-ci.yml`. Le câbler exigerait soit (a)
télécharger le bundle CLI (578 Mo) à chaque run CI (coût réel, répété), soit
(b) utiliser l'action GitHub officielle `github/codeql-action` (gratuite sur
dépôt privé selon le plan GitHub, mécanisme différent de ce script local).
Décision délibérément non tranchée par ce chantier — signalée, pas résolue
en silence.
