# `.opsys/tools/github-control/` — fragment NON-EXECUTABLE

**Statut : NON-EXECUTABLE.** Les 4 scripts de ce répertoire ne s'exécutent pas : chacun échoue
à l'import avec `ModuleNotFoundError: No module named 'common'`. Ce répertoire est un fragment
livré partiellement, pas une capacité en service.

## Origine

Copie partielle d'un pack externe, installée par le commit `fac74ea` (2026-08-09,
« installer le plan de contrôle Core v2.3.0 »). Seuls les 4 scripts Python ont été versionnés ;
le module partagé qu'ils importent et les données qu'ils lisent ne l'ont jamais été.

## Ce qui manque

- **`common.py`** — absent du dépôt. Les 4 scripts l'importent en repli après l'échec de
  `tools.common` (`validate_github_control_pack.py` lignes 5 et 7 :
  `from tools.common import ...` puis `from common import ...`, même schéma dans
  `github_issue_sync.py`, `github_project_sync.py`, `github_task_status.py`). Il doit fournir
  au minimum `PACK`, `EXPECTED_REPO`, `EXPECTED_OWNER`, `canonical_bytes`, `load_tasks`,
  `load_phases` (signatures lues dans `validate_github_control_pack.py`).
- **Les jeux de données `github/catalog/*`** que `validate_github_control_pack.py` lit sous la
  racine `PACK` (jamais versionnée) : `phase-epics.jsonl`, `task-issues.jsonl`,
  `deferred-bugs.jsonl`, `labels.json`, `milestones.json`, `issue-creation-manifest.csv` — et,
  côté `github_project_sync.py`, `project-spec.json`. Sept fichiers au total.
- **`github/issue-bodies/`** — les corps d'issues (ex. `META-CORE-GITHUB-CONTROL.md`) que le
  validateur vérifie un par un (marqueur `OPSYS_..._ID:`, hash SHA-256 du corps).

## Reproduction

```
$ python3 .opsys/tools/github-control/validate_github_control_pack.py
Traceback (most recent call last):
  File ".../validate_github_control_pack.py", line 5, in <module>
    from tools.common import PACK, EXPECTED_REPO, EXPECTED_OWNER, canonical_bytes, load_tasks, load_phases
ModuleNotFoundError: No module named 'tools'

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File ".../validate_github_control_pack.py", line 7, in <module>
    from common import PACK, EXPECTED_REPO, EXPECTED_OWNER, canonical_bytes, load_tasks, load_phases
ModuleNotFoundError: No module named 'common'
```

Le même repli (`tools.common` absent, puis `common` absent) échoue à l'identique, exécuté
directement, pour les 3 autres scripts : `github_issue_sync.py`, `github_project_sync.py`,
`github_task_status.py`.

## Pourquoi ce fragment n'est pas restauré

Fabriquer `common.py` et les sept jeux de données pour faire passer le validateur reviendrait
à **inventer une source de vérité** : les comptes que le validateur impose littéralement
(`validate_github_control_pack.py:14`, catalogue attendu à `(148,25,25,148,12,51,25)` ;
lignes 45-46, 186 entrées attendues dans `issue-creation-manifest.csv`) n'ont aucune donnée
réelle derrière eux tant que le pack externe correspondant n'est pas livré. Ce document
n'affirme pas que ce pack externe existe ou reste récupérable ailleurs que dans l'historique
git de ce dépôt (`fac74ea`) — aucune preuve de cela n'a été établie.

## Statut dans le périmètre qualité

Ce répertoire **reste** l'une des racines de `core/quality-scopes.toml` (ligne 9) : il est
scanné par ruff, bandit, CodeQL et le gate no-stub comme toute autre racine Python du contrat.
Cela n'en fait à aucun moment une **capacité de contrôle Core active** — seulement une source
qui doit rester propre pendant qu'elle attend son pack.

## Consigne de reprise

Toute PR qui livre `common.py` et le catalogue (`github/catalog/*` + `github/issue-bodies/`)
**met à jour ce README ET**
`core/tests/bootstrap/test_github_control_fragment_non_executable.py` **dans le même commit**.

Ce test est une **déclaration d'état** — « aujourd'hui ce fragment n'exécute rien » — pas une
spécification de ce que le pack doit devenir. Le jour où les 4 scripts s'exécutent réellement,
`test_les_quatre_scripts_sont_reellement_inexecutables` rougit ; c'est ce rougissement qui
interdit de promouvoir silencieusement le fragment en capacité.

## Référence

Issue #568 (AUD-CORE-005), ADR-0005
(`docs/decisions/ADR-0005-fragment-github-control-non-executable.md`).
