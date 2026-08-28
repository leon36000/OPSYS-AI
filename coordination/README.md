# Coordination minimale OPSYS-AI

- Les assignees, labels, branches et PR GitHub constituent la vérité live.
- `WORK-OWNERSHIP.md` est le snapshot humain de la mise au point approximativement quotidienne.
- Codex modifie seulement `CODEX-QUEUE.md` et `CODEX-STATUS.md`. Cette PR les installe
  identiques au pack **v1.2** — seule version qui porte encore un `repo-overlay/`, v1.4 ne
  l'a plus (`diff -q "$OPSYS_PACK_V1_2/repo-overlay/coordination/CODEX-QUEUE.md"
  coordination/CODEX-QUEUE.md`, silencieux — même commande pour `CODEX-STATUS.md`, où
  `$OPSYS_PACK_V1_2` désigne le répertoire où le pack `OPSYS-AI-CLAUDE-ISSUES-OPERATIONS-v1.2`
  a été dépaqueté) et ne les édite pas. **Exception assumée à la doctrine anti-décompte de ce
  dépôt** : `CODEX-QUEUE.md` fige « les 148 tâches » du pack, une valeur externe et mutable.
  Elle reste, verbatim, parce que ce fichier n'est pas de la prose de ce dépôt à maintenir —
  c'est une copie d'un fichier que seul Codex édite ; la corriger romprait l'identité au pack
  que la commande ci-dessus atteste.
- Claude Code modifie seulement `CLAUDE-QUEUE.md` et `CLAUDE-STATUS.md`.
- `WORK-OWNERSHIP.md` et `DAILY-SYNC.md` sont modifiés par un seul sync owner désigné pour la mise au point.
- Une tâche, une issue, une branche, un worktree et un owner. Aucun doublon.
- Entre deux syncs, une issue assignée ou une PR active réserve immédiatement la mission.
- Le validateur `tools/check_coordination.py` (versionné dans ce dépôt, dérivé du pack
  `OPSYS-AI-CLAUDE-ISSUES-AUTONOMOUS-v1.4` — **il n'en est pas une copie octet-exacte** ;
  `diff -u` entre les deux fichiers en donne le détail, écarts documentés dans
  `coordination/CLAUDE-STATUS.md`) est exécuté avant l'activation d'une nouvelle mission,
  pas à chaque commande :
  `PYTHONDONTWRITEBYTECODE=1 python3 -B tools/check_coordination.py coordination/WORK-OWNERSHIP.md`

  **Trois codes de sortie, trois significations distinctes.** Un appelant qui teste
  seulement `!= 0` confond les deux derniers, qui ne veulent pas dire la même chose :
  - **exit 0** — `COORDINATION_OK rows=<n> active=<n>` : table lue et conforme (et sortie
    `--json-output` écrite, si elle a été demandée).
  - **exit 1** — une erreur par ligne sur la sortie standard : `HEADER_MISSING`,
    `MALFORMED_ROW:<ligne>:<cellules>`, `WORK_ID_EMPTY`, `DUPLICATE_WORK:<id>`,
    `OWNER:<id>:<valeur>`, `STATUS:<id>:<valeur>`, `SCOPE:<id>:<valeur>`, `BRANCH:<id>`,
    `MODULE_CODE_DURING_CORE:<id>`, `CORE_OWNER:<id>:<valeur>`,
    `ISSUE_OWNER:<id>:<valeur>`, `BRANCH_COLLISION:<a>:<b>`,
    `PATH_COLLISION:<a>:<b>:<scope-a>:<scope-b>`. La table a été lue,
    elle n'est pas conforme. **Ce code est réservé à ce cas** : aucun échec de lecture ou
    d'écriture ne s'y retrouve, et aucun traceback ne remplace ces lignes.
  - **exit 2** — **aucun verdict de conformité exploitable**. Les causes interceptées par
    le validateur portent un préfixe sur la sortie standard, jamais un traceback :
    - `LECTURE_IMPOSSIBLE:<raison>` — la cible n'a pas pu être lue (chemin inexistant,
      répertoire fourni à la place d'un fichier, permission refusée…) ni décodée en UTF-8.
      La table n'a jamais été lue.
    - `SORTIE_IMPOSSIBLE:<raison>` — la table a été lue et validée, mais la sortie
      `--json-output` n'a pas pu être écrite. Le verdict existe, il n'a pas été livré.

    Aucun décompte de causes n'est donné, et ces préfixes ne les épuisent pas : `argparse`
    rend lui aussi exit 2 quand l'argument `ownership` manque, **sans préfixe** — sortie
    standard vide, `usage:` sur la sortie d'erreur. Un appelant qui teste `== 2` doit donc
    lire stdout, pas le supposer non vide.

  L'exit 2 et ces préfixes n'existent pas dans la version du pack, qui laissait remonter
  l'exception avec un traceback et un exit 1 indiscernable, pour l'appelant, d'une table
  lue et non conforme. Motif du changement : voir `coordination/CLAUDE-STATUS.md`.

  **Ce validateur n'est câblé dans aucun job CI.** Raison assumée, pas un oubli — mais pas
  non plus celle qu'une version antérieure de ce paragraphe donnait : un job CI câblé
  *pourrait* rester additif (un nouveau fichier de workflow porterait le statut `A` comme les
  autres fichiers de cette PR, tous en statut `A`, sans modifier `.github/workflows/ci.yml`),
  donc l'additivité de cette PR
  n'est pas, en soi, ce qui empêche le câblage — cette justification-là était fausse, trouvée
  et retirée en revue. La raison réelle est de mission : le mandat de #564 est d'installer
  l'overlay de coordination, pas d'ajouter une porte CI ; câbler une garde qui bloquerait
  potentiellement les PR futures mérite sa propre revue, dédiée, distincte de celle-ci. Le
  câblage relève donc d'une mission séparée, ouverte après le merge de #564, et non d'un
  ajout ici. Tant qu'il n'a pas lieu, l'exécution reste manuelle et
  déclarative, à la charge de qui active une mission. Présenter cette
  garde comme câblée en CI alors qu'elle ne l'est pas serait le défaut d'un validateur
  livré sans être branché nulle part — on ne le reproduit pas ici : la limite est écrite,
  pas cachée. Autre limite, plus décisive, à ne pas taire non plus :
  `COORDINATION_OK` atteste uniquement la **forme** de la table (en-tête présent,
  énumérations valides, Work ID unique, scopes relatifs bien formés, aucune collision de
  branche ou de chemin entre lignes actives) — jamais sa concordance avec l'état réel sur
  GitHub. Une ligne `QUEUED` dont la PR citée est en fait déjà ouverte, une PR fictive, ou
  une date `Updated UTC` remontant à des années ne font échouer aucune de ces vérifications :
  le validateur ne consulte jamais `gh`. Seule la re-vérification manuelle (`gh pr view <n>` /
  `gh issue view <n>`, cf. `WORK-OWNERSHIP.md`) donne la concordance GitHub ;
  `COORDINATION_OK` n'en tient pas lieu. Troisième limite, mesurée et héritée du pack, pas
  refermée ici : une ligne de données privée de son pipe **initial** (ex. `ISS-A | CLAUDE |
  br-a | coordination | ACTIVE | 2026-01-01T00:00Z | x` sans le `|` de tête, en-tête et
  séparateur par ailleurs intacts) n'est jamais lue comme une ligne de table — donc jamais
  vérifiée, collisions comprises. Aucun bloc de code ni aucune indentation n'a de traitement
  spécial : ce qui est écrit dans ce fichier, fence ou pas, indenté ou pas, est lu comme
  n'importe quelle autre ligne. Détail et mesure dans `coordination/CLAUDE-STATUS.md`.
- `.claude/settings.example.json` est un **exemple** à copier puis adapter. Ne jamais
  l'écraser sur `.claude/settings.json` : ce dernier est un fichier préexistant du dépôt,
  que cette PR ne modifie pas, et une copie brute de l'exemple en remplacerait le contenu
  **quel qu'il soit**, sans avertissement. Son contenu n'est pas recopié ici. Détail des
  écarts entre l'exemple et son homologue du pack dans `coordination/CLAUDE-STATUS.md`.
