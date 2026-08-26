# Coordination minimale OPSYS-AI

- Les assignees, labels, branches et PR GitHub constituent la vérité live.
- `WORK-OWNERSHIP.md` est le snapshot humain de la mise au point approximativement quotidienne.
- Codex modifie seulement `CODEX-QUEUE.md` et `CODEX-STATUS.md`.
- Claude Code modifie seulement `CLAUDE-QUEUE.md` et `CLAUDE-STATUS.md`.
- `WORK-OWNERSHIP.md` et `DAILY-SYNC.md` sont modifiés par un seul sync owner désigné pour la mise au point.
- Une tâche, une issue, une branche, un worktree et un owner. Aucun doublon.
- Entre deux syncs, une issue assignée ou une PR active réserve immédiatement la mission.
- Le validateur `tools/check_coordination.py` (versionné dans ce dépôt, dérivé du pack
  `OPSYS-AI-CLAUDE-ISSUES-OPERATIONS-v1.2` — n'en est plus une copie octet-exacte depuis ce
  commit ; écart fonctionnel documenté dans `coordination/CLAUDE-STATUS.md`) est exécuté
  avant l'activation d'une nouvelle mission, pas à chaque commande :
  `PYTHONDONTWRITEBYTECODE=1 python3 -B tools/check_coordination.py coordination/WORK-OWNERSHIP.md`
  (sortie attendue : `COORDINATION_OK rows=<n> active=<n>`).
  **Ce validateur n'est câblé dans aucun job CI.** Raison assumée, pas un oubli : le
  câbler toucherait `.github/workflows/`, qui fait partie du périmètre scellé
  actuellement gelé par l'issue #569 (gate `proof-sealed`, capacité de revue à 1 vendor
  sur 11, seuil de 3 vendors distincts inatteignable). Tant que ce gel dure, l'exécution
  reste manuelle et déclarative, à la charge de qui active une mission. Présenter cette
  garde comme câblée en CI serait exactement le défaut que l'issue #568 a documenté pour
  un autre validateur (fragment jamais branché nulle part) — on ne le reproduit pas ici :
  la limite est écrite, pas cachée. Autre limite, plus décisive, à ne pas taire non plus :
  `COORDINATION_OK` atteste uniquement la **forme** de la table (en-tête présent,
  énumérations valides, Work ID unique, scopes relatifs bien formés, aucune collision de
  branche ou de chemin entre lignes actives) — jamais sa concordance avec l'état réel sur
  GitHub. Une ligne `QUEUED` dont la PR citée est en fait déjà ouverte, une PR fictive, ou
  une date `Updated UTC` remontant à des années ne font échouer aucune de ces vérifications :
  le validateur ne consulte jamais `gh`. Seule la re-vérification manuelle (`gh pr view <n>` /
  `gh issue view <n>`, cf. `WORK-OWNERSHIP.md`) donne la concordance GitHub ;
  `COORDINATION_OK` n'en tient pas lieu.
- `.claude/settings.example.json` est un **exemple** à copier puis adapter. Ne jamais
  l'écraser sur `.claude/settings.json` : ce dernier porte les 3 hooks d'enforcement
  réels de la session (`SessionStart`, `UserPromptSubmit`, `PreToolUse` sur `Bash`) ; une
  copie brute de l'exemple les supprimerait silencieusement. Détail des écarts entre les
  deux fichiers dans `coordination/CLAUDE-STATUS.md`.
