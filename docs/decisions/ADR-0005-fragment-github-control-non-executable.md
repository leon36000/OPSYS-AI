# ADR-0005 — Requalification du fragment GitHub-control (`.opsys/tools/github-control/`) en NON-EXECUTABLE

Statut: Proposé
Date: 2026-09-05

## Contexte

L'issue #568 (AUD-CORE-005) documente que `.opsys/tools/github-control/` — 4 scripts Python
installés par le commit `fac74ea` (2026-08-09, « installer le plan de contrôle Core v2.3.0 »,
copie partielle d'un pack externe) — est orphelin : le module `common.py` qu'ils importent tous
et les jeux de données qu'ils consomment (`github/catalog/*`, `github/issue-bodies/`) n'ont
jamais été versionnés. Exécuté, chacun des 4 scripts échoue avec
`ModuleNotFoundError: No module named 'common'` (après un premier échec intercepté sur
`No module named 'tools'`) — reproduction et détail dans
`.opsys/tools/github-control/README.md`.

Ce répertoire n'est pas un fragment isolable sans conséquence : c'est l'une des cinq racines
déclarées dans `core/quality-scopes.toml:9`, lues par les outils qualité du dépôt. Une décision
doit trancher entre retirer le fragment, restaurer une version fonctionnelle, ou le requalifier
en place.

## Options considérées

### 1. RETIRER le répertoire

Écarté. `core/scripts/run_security_scan.py:52-55` et `core/scripts/run_codeql_scan.py:136-140`
sont fail-closed sur l'EXISTENCE de chacune des racines du contrat (une racine manquante lève
respectivement `OutilSecuriteAbsent` et `OutilCodeQLAbsent`) ; `core/tests/bootstrap/test_security_tool_scope.py:29-30`
scelle `is_dir()` sur les cinq racines et `scripts/tests/test_quality_scope_contract.py:74-78`
scelle la liste exacte du contrat. Le job `security` de `.github/workflows/core-ci.yml`
(vérifié ici) invoque directement `run_security_scan.py` : retirer la racine casse ce gate CI.
Selon les précisions du lead (consultation Opus scellée), retirer le chemin partout où il est
engagé demande en outre l'édition d'environ 8 fichiers de gouvernance et touche un second job
CI, et entrerait en collision avec l'issue ouverte #573, qui planifie d'ajouter ce même chemin
au déclencheur `proof-sealed` plutôt que de l'en retirer. Le commit `9646437`
(« eliminate unallocated CodeQL findings ») avait par ailleurs corrigé dans ce répertoire des
findings CodeQL réels ; un retrait effacerait la trace de cette remédiation sans la rendre
caduque.

### 2. RESTAURER une version fonctionnelle

Écarté. `validate_github_control_pack.py` impose des comptes exacts sur le catalogue attendu
(ligne 14 : `(148,25,25,148,12,51,25)` ; lignes 45-46 : 186 entrées uniques attendues dans
`issue-creation-manifest.csv`) ainsi que des hachages SHA-256 par enregistrement. Aucune de ces
données n'existe dans ce dépôt. Les fabriquer pour faire passer le validateur reviendrait à
**inventer une source de vérité** plutôt qu'à en restaurer une réelle.

### 3. REQUALIFIER le fragment en NON-EXECUTABLE (retenue)

Rien n'est supprimé (le contrat qualité, les gates CI et les 4 scripts restent inchangés),
rien n'est inventé (aucune donnée fabriquée). Le fragment est déclaré NON-EXECUTABLE dans
`.opsys/tools/github-control/README.md`, et cette non-exécutabilité est scellée par
`core/tests/bootstrap/test_github_control_fragment_non_executable.py` : le test constate
l'échec réel des 4 scripts au lieu de le supposer, si bien qu'une livraison future du pack le
fait rougir au lieu de laisser le fragment glisser silencieusement au statut de capacité.

## Décision

**REQUALIFIER.** `.opsys/tools/github-control/` reste une racine scannée de
`core/quality-scopes.toml`, documentée comme fragment non exécutable par son propre README
co-localisé, et cet état est scellé par un test dans `core/tests/bootstrap/`.

## Conséquences

- Aucun gate CI existant n'est modifié : `core/quality-scopes.toml`, `core/scripts/*` et
  `.github/workflows/*` restent inchangés par cette décision.
- Le répertoire continue d'être scanné (ruff/bandit/CodeQL/no-stub) comme toute autre racine
  du contrat qualité, sans jamais être traité comme une capacité de contrôle Core active.
- Toute PR qui livre `common.py` et le catalogue doit mettre à jour, dans le même commit, le
  README du fragment et `test_github_control_fragment_non_executable.py` — sous peine de
  laisser une déclaration de non-exécutabilité mentir sur un pack devenu réel.
- Le test scellé documente un état constaté, pas une spécification cible : il rougira le jour
  où le pack sera livré, ce qui est le signal attendu, pas une régression à corriger sur place.

## Réversibilité

Entièrement réversible par un `git revert` du commit qui introduit cette requalification : il
n'ajoute que 3 fichiers nouveaux (le README du fragment, le test, cet ADR) et ne modifie ni ne
supprime aucun fichier existant. Si le pack externe dont ce fragment est une copie partielle
redevient disponible, la copie actuelle reste consultable à partir du commit `fac74ea` pour
comparaison — sans qu'aucune preuve n'établisse ici que ce pack existe ou est accessible
ailleurs que dans cet historique git.
