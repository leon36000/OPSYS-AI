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
- `WORK-OWNERSHIP.md`, `DAILY-SYNC.md` et `OVERLAY-VERSION.json` sont modifiés par un seul sync
  owner désigné pour la mise au point ; `24H-UPDATE-TEMPLATE.md` reste un gabarit vide, non
  édité par la mise au point elle-même (cf. `DAILY-SYNC.md`).
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
    `--json-output` écrite, si elle a été demandée). `-h`/`--help` rend lui aussi exit 0, mais
    stdout y porte le texte d'aide, pas cette ligne — un appelant qui teste `== 0` doit lire
    stdout, pas supposer qu'il porte `COORDINATION_OK`.
  - **exit 1** — une erreur par ligne sur la sortie standard : `HEADER_MISSING`,
    `MALFORMED_ROW:<ligne>:<nombre-de-cellules>`, `WORK_ID_EMPTY`, `DUPLICATE_WORK:<id>`,
    `OWNER:<id>:<valeur>`, `STATUS:<id>:<valeur>`, `SCOPE:<id>:<valeur>`, `BRANCH:<id>`,
    `MODULE_CODE_DURING_CORE:<id>`, `CORE_OWNER:<id>:<valeur>`,
    `ISSUE_OWNER:<id>:<valeur>`, `BRANCH_COLLISION:<a>:<b>`,
    `PATH_COLLISION:<a>:<b>:<scope-a>:<scope-b>`. La table a été lue,
    elle n'est pas conforme — et si `--json-output` a été demandée, elle est écrite quand
    même, portant alors cette même liste d'erreurs dans son champ `errors` (mesuré). **Ce
    code est réservé à ce cas, pour toute entrée couverte par
    le contrat ci-dessous** : aucun échec de lecture ou d'écriture ordinaire ne s'y retrouve,
    et aucun traceback ne remplace ces lignes — une entrée hors contrat (périphérique
    caractère sans fin de fichier, tube sans écrivain, stdout indisponible — limites
    nommées plus bas, pas par position, qu'un ajout ultérieur à cette liste rendrait fausse)
    y échappe.
  - **exit 2** — **aucun verdict de conformité exploitable**. Les causes interceptées par
    le validateur portent un préfixe sur la sortie standard, jamais un traceback :
    - `LECTURE_IMPOSSIBLE:<raison>` — la cible n'a pas pu être lue (chemin inexistant,
      répertoire fourni à la place d'un fichier, permission refusée…) ni décodée en UTF-8.
      La table n'a jamais été lue.
    - `SORTIE_IMPOSSIBLE:<raison>` — la table a été lue et validée, mais la sortie
      `--json-output` n'a pas pu être écrite. Le verdict existe, il n'a pas été livré —
      y compris, si la table était NON conforme, la liste d'erreurs elle-même :
      l'écriture `--json-output` est tentée avant le test qui déciderait de l'exit 1,
      donc un échec d'écriture sur une table non conforme rend exit 2 sans jamais
      imprimer les lignes d'erreur (mesuré : `MODULE_CODE_DURING_CORE:<id>` sur une
      table portant l'interdit dur de l'ADR-0004, non affiché dans ce cas précis).
      Pas un faux vert (exit 2 ≠ 0, jamais confondu avec un succès), mais un
      diagnostic perdu — mesuré, pas encore refermé.

    Aucun décompte de causes n'est donné, et ces préfixes ne les épuisent pas : `argparse`
    rend lui aussi exit 2 quand l'argument `ownership` manque, **sans préfixe** — sortie
    standard vide, `usage:` sur la sortie d'erreur. Un appelant qui teste `== 2` doit donc
    lire stdout, pas le supposer non vide.

  L'exit 2 et ces préfixes n'existent pas dans la version du pack, qui laissait remonter
  l'exception avec un traceback et un exit 1 indiscernable, pour l'appelant, d'une table
  lue et non conforme. Motif du changement : voir `coordination/CLAUDE-STATUS.md`.

  **Câbler ce validateur en CI est hors mandat de #564** (installer l'overlay de coordination,
  pas ajouter une porte CI qui bloquerait potentiellement les PR futures — mission séparée,
  dédiée). Affirmation sur `.github/workflows/**`, hors de cette PR : re-vérifiable sans la
  croire — `grep -rn check_coordination .github/workflows/`, jamais figée ici. Tant qu'il
  n'a pas lieu, l'exécution reste manuelle et déclarative, à la charge de qui active une
  mission. Autre
  limite, plus décisive, à ne pas taire non plus :
  `COORDINATION_OK` atteste uniquement la **forme** de la table — toutes les vérifications
  listées au point exit 1 ci-dessus, ni plus ni moins — jamais sa concordance avec l'état réel
  sur GitHub. Une ligne `QUEUED` dont la PR citée est en fait déjà ouverte, une PR fictive, ou
  une date `Updated UTC` remontant à des années ne font échouer aucune de ces vérifications :
  le validateur ne consulte jamais `gh`. Seule la re-vérification manuelle (`gh pr view <n>` /
  `gh issue view <n>`, cf. `WORK-OWNERSHIP.md`) donne la concordance GitHub ;
  `COORDINATION_OK` n'en tient pas lieu. Troisième limite, mesurée et héritée du pack, pas
  refermée ici : une ligne de données privée de son pipe **initial** (ex. `ISS-A | CLAUDE |
  br-a | coordination | ACTIVE | 2026-01-01T00:00Z | x` sans le `|` de tête, en-tête et
  séparateur par ailleurs intacts) n'est jamais lue comme une ligne de table — donc jamais
  vérifiée, collisions comprises. Aucun bloc de code ni aucune indentation n'a de traitement
  spécial : ce qui est écrit dans ce fichier, fence ou pas, indenté ou pas, est lu comme
  n'importe quelle autre ligne. D'autres limites, mesurées, ni exercées par un fichier
  livré ni fermées : une ligne de séparation espacée ou porteuse des deux-points d'alignement
  Markdown (`| --- | --- |` ou `|:---|:---|` au lieu de `|---|---|`) n'est pas reconnue
  (`HEADER_MISSING` + des `OWNER`/`STATUS` parasites, fail-closed — pas un faux
  `COORDINATION_OK`) ; `overlaps()` normalise casse et séparateur puis compare des chemins
  par égalité ou parenté (`PurePosixPath`), sans aucune sémantique de glob — `**` y est un
  composant de chemin ordinaire, pas un joker : deux scopes `.github/workflows/**` et
  `.github/workflows/ci.yml` ne sont donc pas vus en collision, et un scope dont la
  résolution en joker serait nécessaire pour ATTEINDRE `modules m` (`**` seul, `*/M7`)
  échappe pareillement à `MODULE_CODE_DURING_CORE`, même absence de sémantique — un scope
  qui reste un DESCENDANT littéral de `modules m` (`modules m/*`, `modules m/**`), lui,
  y est intercepté normalement, `modules m` en étant déjà l'ancêtre littéral sans qu'aucun
  joker n'ait besoin d'être développé (vérifié) ; un périphérique caractère sans fin de fichier
  (`/dev/zero`) ou un tube nommé sans écrivain sortent tous deux du contrat 0/1/2
  ci-dessus — blocage ou trace non interceptée, jamais l'une des lignes énumérées à
  exit 1 ni un `LECTURE_IMPOSSIBLE` propre ; même famille, un stdout indisponible AVANT
  toute écriture (`>&-`, descripteur fermé) ou rompu EN COURS d'écriture (tube lu puis
  refermé, `| head -0`) échappe lui aussi, respectivement en silence (`print()` sur un
  flux clos ne lève rien) et en `BrokenPipeError`, exit 120 — condition du canal de
  SORTIE, générique à tout script Python qui imprime, ni ouverte ni fermée par cette PR ;
  et un BOM UTF-8 en tête de la ligne d'en-tête fait échouer sa comparaison stricte avec
  l'en-tête attendu — `HEADER_MISSING`, fail-closed, pas un faux `COORDINATION_OK`.
- `.claude/settings.example.json` est un **exemple** à copier puis adapter. Ne jamais
  l'écraser sur `.claude/settings.json` : ce dernier est un fichier préexistant du dépôt,
  que cette PR ne modifie pas, et une copie brute de l'exemple en remplacerait le contenu
  **quel qu'il soit**, sans avertissement. Son contenu n'est pas recopié ici. Détail des
  écarts entre l'exemple et son homologue du pack dans `coordination/CLAUDE-STATUS.md`.
