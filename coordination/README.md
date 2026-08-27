# Coordination minimale OPSYS-AI

- Les assignees, labels, branches et PR GitHub constituent la vérité live.
- `WORK-OWNERSHIP.md` est le snapshot humain de la mise au point approximativement quotidienne.
- Codex modifie seulement `CODEX-QUEUE.md` et `CODEX-STATUS.md`.
- Claude Code modifie seulement `CLAUDE-QUEUE.md` et `CLAUDE-STATUS.md`.
- `WORK-OWNERSHIP.md` et `DAILY-SYNC.md` sont modifiés par un seul sync owner désigné pour la mise au point.
- Une tâche, une issue, une branche, un worktree et un owner. Aucun doublon.
- Entre deux syncs, une issue assignée ou une PR active réserve immédiatement la mission.
- Le validateur `tools/check_coordination.py` (versionné dans ce dépôt, dérivé du pack
  `OPSYS-AI-CLAUDE-ISSUES-OPERATIONS-v1.2` — **il n'en est pas une copie octet-exacte** ;
  `diff -u` entre les deux fichiers en donne le détail, écarts documentés dans
  `coordination/CLAUDE-STATUS.md`) est exécuté avant l'activation d'une nouvelle mission,
  pas à chaque commande :
  `PYTHONDONTWRITEBYTECODE=1 python3 -B tools/check_coordination.py coordination/WORK-OWNERSHIP.md`

  **Trois codes de sortie, trois significations distinctes.** Un appelant qui teste
  seulement `!= 0` confond les deux derniers, qui ne veulent pas dire la même chose :
  - **exit 0** — `COORDINATION_OK rows=<n> active=<n>` : table lue et conforme.
  - **exit 1** — une erreur par ligne sur la sortie standard : `HEADER_MISSING`,
    `MALFORMED_ROW:<ligne>:<cellules>`, `WORK_ID_EMPTY`, `DUPLICATE_WORK:<id>`,
    `OWNER:<id>:<valeur>`, `STATUS:<id>:<valeur>`, `SCOPE:<id>:<valeur>`, `BRANCH:<id>`,
    `MODULE_CODE_DURING_CORE:<id>`, `CORE_OWNER:<id>:<valeur>`,
    `ISSUE_OWNER:<id>:<valeur>`, `BRANCH_COLLISION:<a>:<b>`,
    `PATH_COLLISION:<a>:<b>:<scope-a>:<scope-b>`, `UNTERMINATED_FENCE`. La table a été lue,
    elle n'est pas conforme.
  - **exit 2** — `CHEMIN_INVALIDE:<raison>` : la table n'a **jamais été lue**, l'argument de
    chemin n'a pas passé la validation préalable (fichier inexistant, répertoire fourni à la
    place d'un fichier, octet nul dans le chemin, ou `--json-output` dont le répertoire
    parent n'existe pas).

  Le code `2` et le préfixe `CHEMIN_INVALIDE` n'existent pas dans la version du pack, qui
  laissait remonter un `FileNotFoundError` avec traceback. Motif du changement et portée
  volontairement **non** confinée à l'arborescence du dépôt — `tools/daily_start.py` du pack
  valide son propre gabarit, hors dépôt, sur une installation neuve : voir
  `coordination/CLAUDE-STATUS.md`, écart « `_chemin_valide()` ».

  **Ce validateur n'est câblé dans aucun job CI.** Raison assumée, pas un oubli : le câbler
  modifierait `.github/workflows/ci.yml`, un fichier **existant** du dépôt, alors que le
  cinquième critère d'acceptation de l'issue #563 exige « aucun fichier existant du dépôt
  n'est modifié ». Le câblage relève donc d'une mission séparée, ouverte après le merge de
  #564, et non d'un ajout ici. Tant qu'il n'a pas lieu, l'exécution reste manuelle et
  déclarative, à la charge de qui active une mission. Présenter cette
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
