# Status Claude Code

Updated UTC : `2026-08-27T04:41Z`

**Portée de la péremption : ce fichier entier, prose comprise** — et non une énumération de
sections, qui redeviendrait incomplète dès la prochaine section ajoutée. Toute affirmation
d'état GitHub portée ici, où qu'elle se trouve (PR ou issue ouverte, fermée, mergée,
bloquée), est datée de l'horodatage ci-dessus et soumise à la clause de péremption portée en
tête de `coordination/WORK-OWNERSHIP.md` — non dupliquée ici, pour que les deux ne dérivent
pas l'une de l'autre. En pratique : au-delà de 24 h, re-vérifier par `gh pr view <n>` /
`gh issue view <n>` plutôt que de faire confiance à la valeur écrite ici. Aucun numéro de
ligne n'est cité pour désigner cette clause : un renvoi par numéro de ligne se réfute dès la
prochaine édition du fichier visé.

## Vérification runtime (07-RUNTIME-CHECK, constat unique de session)

- Lead observé : `claude-opus-5`. Le pack v1.4 nomme désormais ce choix explicitement :
  `06-CLAUDE-LEAD-PROMPT.md` porte « le modèle du lead est celui explicitement sélectionné
  par Nathan ; ne transforme pas cette différence en erreur ». Ce n'est plus un écart.
  Aucun fallback silencieux : la valeur observée reste consignée ici, pas masquée.
- Sous-agents : instanciés en `sonnet` (Claude Sonnet 5), conforme au pack amont. Les
  fichiers livrés `.claude/agents/opsys-issue-*.md` portent la même valeur dans leur champ
  `model` (`grep -n '^model:' .claude/agents/opsys-issue-*.md`). Le canon désigné par la
  décision Nathan du 2026-08-27 est `docs/core/CANON-INDEX.md` (promotion portée par #566,
  pas encore fusionnée à HEAD) ; `CLAUDE.md`, fichier qui n'appartient pas à cette PR, en est
  un adaptateur dérivé, pas une autorité concurrente, et les noms de modèles en restent
  explicitement exclus. **Modèle non changé dans cette revue** :
  requalifier ces champs `model` est une décision produit (quel modèle par rôle) hors
  périmètre d'une correction de revue, à faire avec validation Nathan plutôt que
  silencieusement ici.
  Les définitions `.claude/agents/opsys-issue-*.md` sont installées dans ce dépôt ;
  le dossier projet de la session courante étant distinct, les agents sont invoqués
  en injectant leur prompt et leurs contraintes verbatim.
- Effort `max` par sous-agent : non réglable depuis l'outil d'invocation courant.
  **Écart consigné**, non masqué.
- Écriture autorisée : oui (décision Nathan). `BLOCKED_RUNTIME_IDENTITY` non appliqué.

## Périmètre autorisé pour cette session

Jusqu'à la **PR ouverte** incluse, avec merge autonome par le propriétaire si les huit
critères de la décision Nathan du 2026-08-27 sont réunis — trio de validation aveugle sur
le SHA final compris (`08-TRIO-AND-MERGE-AUTONOMY.md`) — sinon rien de plus qu'une PR
ouverte. Aucune modification de branch protection, aucun code métier M1–M10, aucune
promotion canonique.

## Capacité des agents `.claude/agents/opsys-issue-*.md` — ce qui est prouvé, ce qui ne l'est pas

Objection de revue : ces définitions n'ont jamais été exercées comme fichiers
`.claude/agents/` chargés nativement, et deviennent après merge chargeables avec
`maxTurns: 240`. Précision mesurée : `opsys-issue-triage` déclare
`tools: Read, Grep, Glob, Bash` et place Write/Edit/NotebookEdit dans
`disallowedTools`, cohérent avec son `permissionMode: plan` ; les autres portent
`tools` incluant Write/Edit. Aucune de ces définitions ne porte `permissionMode: auto` —
propriété stable, à rejouer plutôt qu'à croire :
`grep -n '^permissionMode:' .claude/agents/opsys-issue-*.md`. L'écart correspondant
vis-à-vis du pack amont est consigné en « Écarts volontaires » ci-dessous. Ne pas
dégrader en `.example` — mais ne pas non plus prétendre à une capacité non observée.
Détail :

**Ce qui EST prouvé** — le corps de prompt (hors frontmatter YAML) de ces rôles a été
exercé comme instruction de sous-agent, verbatim ou quasi-verbatim, sur des missions
réelles et vérifiables de ce dépôt. Aucun énoncé, contenu ni périmètre d'issue ou de PR
n'est recopié dans cette liste : seuls les numéros y figurent, et `gh issue view <n>` /
`gh pr view <n>` fait foi.

- **triage** (read-only, reconnaissance live) → `LIVE-ISSUE-RECONCILIATION`, sans issue
  ni PR propre (par construction : read-only) ; a produit les candidats repris ci-dessous.
- **ci-docs** (CI/docs/canon/manifest) → issue **#565** → PR **#567**.
- **security-quality** (sécurité/tests/qualité/portabilité) → issue **#570** → PR **#571**.
- L'installation de l'overlay elle-même → issue **#563** → PR **#564** (cette PR) est
  de la même famille de travail que le rôle **ci-docs** (coordination/docs/manifest),
  mais **ne peut pas** être citée comme une exécution du fichier `opsys-issue-ci-docs.md` :
  ce fichier est *créé par* cette branche, ce que montre le diff même de la PR
  (`git diff --name-status origin/main...HEAD`, où sa ligne porte le statut `A`). C'est le
  travail de l'orchestrateur (session lead), pas un rejeu du fichier commité.
- **restructure** (restructuration/packaging/nettoyage prouvé) : **aucune mission
  numérotée n'a encore exercé ce rôle**. Le candidat le plus proche est l'issue **#568**
  (AUD-CORE-005), mais l'investigation menée pendant cette campagne s'est arrêtée avant
  tout code — fait local et passé, qui ne se périme pas. Ne pas compter #568 comme une
  preuve d'exécution du rôle restructure.

**Ce qui N'EST PAS prouvé, et reste un écart nommé** — que le chargeur natif
`.claude/agents/` de Claude Code honore réellement, pour ces fichiers, les champs de
frontmatter `permissionMode`, `effort`, `background`, `maxTurns`, `disallowedTools`.
Toutes les exécutions listées ci-dessus sont passées par injection manuelle du corps de
prompt dans un autre outil d'invocation (le dossier projet de la session n'est pas ce
dépôt — cf. section runtime ci-dessus), jamais par le chargement natif du fichier
`.claude/agents/opsys-issue-*.md` tel qu'il serait lu par un `claude` lancé à la racine
de ce dépôt. Aucun binaire `claude` n'a été observé s'exécuter depuis ce dépôt pendant
cette campagne. En clair : le **contenu** des rôles a tourné en conditions réelles ; leur
**enveloppe de permissions déclarée** (le frontmatter YAML) n'a, à ce jour, jamais été
vérifiée en exécution — ni confirmée, ni infirmée.

## Écarts volontaires vis-à-vis du pack amont (permissions)

Cette section recense les écarts de permissions vis-à-vis du pack amont, dans
`.claude/settings.example.json` **et** dans `.claude/agents/opsys-issue-*.md`.
Référence côté pack : `$OPSYS_PACK/platform-overlay/.claude/settings.example.json`, qui
porte `defaultMode: "auto"` ; ni `availableModels` ni `model` n'y figurent (absents depuis
le pack v1.4, verrouillé par `tests/test_v14.py` côté pack : `assertNotIn`).

**Aucun décompte d'écarts n'est figé ici, et c'est délibéré** — même raison que pour le
validateur plus bas. Une version antérieure de ce paragraphe annonçait « trois points »
devant une liste qui n'en portait déjà plus trois : le point ajouté ensuite n'a pas mis le
décompte à jour, exactement la faute que cette politique a pour rôle de ne pas commettre.
`diff -u` entre chaque fichier et son homologue du pack fait autorité sur les écarts
réels ; cette liste n'en énumère que la signification.

1. **`defaultMode`** : `"auto"` → `"default"`, et ajout de `"disableAutoMode": "disable"`
   à côté de `"disableBypassPermissionsMode"`. Motif : faire approuver des actions par un
   modèle est l'inverse du principe d'autorité des outils déterministes. Sur ce point, voir
   aussi `AGENTS.md`, fichier qui n'appartient pas à cette PR.
2. **Règles `deny` Bash** : les règles `Read(./.env)`, `Read(./secrets/**)`,
   `Read(./credentials/**)` sont par outil — elles ne couvrent pas `Bash`, qui peut lire
   les mêmes fichiers via `cat`, `head`, etc. Des règles `Bash(cat .env*)`,
   `Bash(cat ./secrets/*)`, etc. ont été ajoutées pour combler ce trou évident.
   **Limite assumée et non maquillée : cette liste ne peut pas être exhaustive.** Une
   liste noire de préfixes de commande (`Bash(<mot> *)`, wildcard suffixe uniquement,
   cf. schéma officiel des règles de permission) ne couvre ni les autres commandes de
   lecture (`sed`, `awk`, `strings`, `xxd`, `od`, `find -exec`, `python3 -c`, `node -e`,
   `perl`, …), ni les variations de chemin (absolu, remonte-parent, guillemets,
   substitution de variable, lien symbolique), ni la lecture indirecte (copier le
   fichier sous un autre nom puis le lire). Elle réduit la surface la plus évidente,
   elle ne la ferme pas. La protection réelle reste : ne pas versionner de secret dans
   le dépôt, permissions OS / gestionnaire de secrets, et les hooks déterministes — pas
   cette liste, qui reste une politique côté client pour un agent coopératif.
3. **`env.ANTHROPIC_DEFAULT_SONNET_MODEL`** : présent dans l'exemple livré ici, absent du
   pack `OPSYS-AI-CLAUDE-ISSUES-AUTONOMOUS-v1.4` — mesuré, cette clé n'apparaît pas dans
   `$OPSYS_PACK/platform-overlay/.claude/settings.example.json`. `availableModels` et
   `model` sont eux absents des **deux** côtés désormais (v1.4 les a retirés) : ce n'est
   plus un écart sur ces deux clés. Ce qui reste est **inversé** par rapport à une
   formulation antérieure de ce point : c'est ce dépôt qui ajoute une clé absente du pack,
   pas le pack qui en fixe une que ce dépôt retirerait. Motif inchangé : exprimer « quand
   l'alias `sonnet` est demandé, cette version précise » sans figer `model` — **portée
   limitée à ce qui invoque l'alias**, pas à tout le dépôt. Les quatre définitions
   `.claude/agents/opsys-issue-*.md` livrées ici portent `model: claude-sonnet-5` en dur
   (identique au pack — `grep -n '^model:' "$OPSYS_PACK"/platform-overlay/.claude/agents/*.md`
   rend la même valeur), pas l'alias `sonnet` : ce point 3 ne les couvre donc pas, et ne
   prétend pas le contraire.
4. **`permissionMode` de `.claude/agents/opsys-issue-{ci-docs,restructure,security-quality}.md`**
   — écart portant sur d'autres fichiers que les points ci-dessus. Le pack amont porte
   `permissionMode: auto` pour ces définitions et `permissionMode: plan` pour
   `opsys-issue-triage.md` ; la copie de ce dépôt porte `default` pour les premières et
   `plan`, inchangé, pour `triage`. Les deux côtés sont re-mesurables sans citer aucun
   commit :
   `grep -n '^permissionMode:' "$OPSYS_PACK"/platform-overlay/.claude/agents/*.md` et
   `grep -n '^permissionMode:' .claude/agents/opsys-issue-*.md`.
   Motif : le point 1 ci-dessus ne portait que sur un fichier inerte
   (`.claude/settings.example.json` n'est chargé par rien) et pas sur les fichiers
   effectivement lus nativement par Claude Code (`.claude/agents/*.md`) — alors que ces
   définitions portent `tools` incluant Write/Edit/Bash, `maxTurns: 240` et
   `background: true`. Même raisonnement que le point 1. `triage` est déjà plus restrictif
   qu'`auto` et reste hors-sujet de cet écart. Le corps de ces fichiers diffère aussi du
   pack (ligne `PREUVE:`/`BLOCKED:` ajoutée en fin de prompt, description de `triage`
   réécrite) : là encore, `diff -u` fait foi, aucun décompte n'est figé ici.

## `tools/check_coordination.py` — écarts volontaires vis-à-vis du pack amont (validation)

Ce fichier **n'est pas une copie octet-exacte** du `tools/check_coordination.py` du pack
`OPSYS-AI-CLAUDE-ISSUES-AUTONOMOUS-v1.4`. C'est une propriété stable, vérifiable sans citer
ni commit, ni révision, ni décompte : `diff -q "$OPSYS_PACK/tools/check_coordination.py"
tools/check_coordination.py` signale que les fichiers diffèrent, et `diff -u` entre les deux
donne le détail exact.

**Décision Nathan (2026-08-27) : ramener ce validateur vers le minimal de la directive.**
Chaque écart de ce fichier vis-à-vis du pack a été repassé au tri suivant, fixture Markdown
hors dépôt par fixture, mesurée contre `tools/check_coordination.py` du pack **et** contre ce
fichier : le pack rend vert à tort et ce fichier rouge → l'écart ferme un fail-open mesuré,
gardé ci-dessous ; les deux rendent la même chose, ou le pack rendait déjà rouge sur une
entrée légitime → l'écart ne fermait rien de mesurable, retiré avec sa prose. Trois écarts
antérieurs (reconnaissance élargie des séparateurs Markdown, suivi des blocs de code clôturés,
`UNTERMINATED_FENCE`) ont été retirés sur ce critère — le premier parce que le pack n'était
jamais vert à tort sur ses fixtures (rouge des deux côtés, pour des raisons différentes) ; le
deuxième et le troisième parce que le fichier lui-même rendait vert à tort là où le pack
rendait rouge à raison (une paire de clôtures équilibrée autour d'une vraie collision
disparaissait en silence). Le détail de leur mesure ne survit pas ici, pour ne pas maintenir
une justification pour du code qui n'existe plus ; `diff -u` contre le pack fait foi de ce qui
reste. La validation du chemin d'argv, elle, n'a pas suivi ce sort — voir plus bas : retirée
un temps sur ce même critère, elle a dû être **réintroduite** pour une raison distincte
(SonarCloud), documentée là où le code vit, pas ici.

### `HEADER_MISSING`

Sans ce contrôle, un mauvais chemin ou un fichier tronqué/vidé rendent le même succès qu'une
vraie table. Mesuré : `python3 -B tools/check_coordination.py coordination/DAILY-SYNC.md`,
côté pack, rend `COORDINATION_OK rows=0 active=0`, exit 0, alors que ce fichier ne porte
aucune table de coordination. `rows == 0` n'est pas un discriminant valide : une vraie table
vide (en-tête et séparateur présents, zéro ligne de données) reste légitime. `parse_rows()`
retourne donc si l'en-tête a été rencontré **immédiatement suivi** d'une vraie ligne de
séparation ; `validate()` ajoute `HEADER_MISSING` sinon.

Mesuré à HEAD : `coordination/WORK-OWNERSHIP.md` de ce dépôt → `COORDINATION_OK rows=9
active=2` ; `coordination/DAILY-SYNC.md`, `coordination/24H-UPDATE-TEMPLATE.md` et
`coordination/README.md` → `HEADER_MISSING`, exit 1 — aucun des trois ne portant de table de
coordination ; un gabarit neuf (en-tête et séparateur, zéro ligne) → `COORDINATION_OK rows=0
active=0`, exit 0.

### `overlaps()` — casse et séparateur non normalisés, incohérent avec `MODULE_CODE_DURING_CORE`

Dans `validate()`, `MODULE_CODE_DURING_CORE` normalise déjà casse et séparateur du scope
avant comparaison ; `overlaps()`, lui, comparait les chemins de scope tels quels — incohérence
interne héritée du pack amont, pas introduite ici. Conséquence mesurée : deux lignes actives,
branches distinctes, portant les scopes `Coordination` et `coordination` → le pack rend
`COORDINATION_OK rows=2 active=2`, exit 0 (collision manquée). Même constat, séparateur plutôt
que casse : scopes `coordination\sub` et `coordination/sub` → même résultat côté pack.
`overlaps()` normalise maintenant casse **et** séparateur des deux chemins avant comparaison,
par le même principe que `MODULE_CODE_DURING_CORE`. Mesuré à HEAD sur les deux fixtures :
`PATH_COLLISION:ISS-A:ISS-B:Coordination:coordination`, exit 1, puis
`PATH_COLLISION:ISS-A:ISS-B:coordination\sub:coordination/sub`, exit 1.

### Lecture et écriture — interception au lieu d'un traceback

Sans interception, un chemin de lecture invalide (répertoire fourni à la place d'un fichier,
chemin inexistant, permission refusée, contenu non décodable en UTF-8) ou une sortie
`--json-output` inscriptible rendent, côté pack, une exception non captée : exit 1 avec
traceback sur stderr, stdout vide — indiscernable, pour un appelant qui teste `== 1`, d'une
table lue et non conforme. Plus net encore : une table lue **et conforme**, dont la sortie
`--json-output` échoue à l'écriture, rend le même exit 1 qu'une table non conforme. Mesuré :
table valide (gabarit neuf) + `--json-output` vers un répertoire non inscriptible → pack
`exit=1`, traceback, `PermissionError`, alors que `errors == []`.

`main()` intercepte `OSError` et `UnicodeDecodeError` à la lecture (`LECTURE_IMPOSSIBLE:
<raison>`, exit 2) et `OSError` à l'écriture JSON (`SORTIE_IMPOSSIBLE:<raison>`, exit 2).

**Historique de cet écart, corrigé ici après une revue scellée indépendante (3 sièges,
convergents) qui l'a trouvé faux.** Une version antérieure de ce tri avait retiré la
validation de chemin préalable (`_chemin_valide()`), la jugeant redondante avec
l'interception ci-dessus sur les quatre fixtures mesurées à l'époque (répertoire en lecture,
chemin inexistant, répertoire de sortie inexistant, cible de sortie = répertoire) — mêmes
exit 2, même absence de traceback sur ces quatre-là. Mais un critère mesuré sur des fixtures
*comportementales* ne couvre pas un motif détecté par *analyse statique* : SonarCloud a
rouvert `pythonsecurity:S8707` (chemin argv non validé avant accès disque) sur ce fichier
neuf, faisant échouer le gate CI — sans qu'aucune des quatre fixtures ci-dessus ne change de
verdict. `_chemin_sur()` (nom changé, motif identique) est donc **de retour**, appelée aux
deux points d'accès. Elle lève `OSError` nue plutôt qu'une classe dédiée : ce contrat
exit 2 / `LECTURE_IMPOSSIBLE` / `SORTIE_IMPOSSIBLE` ne change pas pour autant. Détail complet
(refus de l'octet nul, `resolve()`, portée volontairement non confinée à l'arborescence du
dépôt) dans son propre docstring, `tools/check_coordination.py` — pas recopié ici, pour ne
pas répéter l'erreur qui a motivé cette réécriture.

**Un vrai rétrécissement de comportement est passé avec elle, trouvé par la même revue et
fermé partiellement, l'autre part assumée** : la première version de `_chemin_sur()` exigeait
`is_file()` en lecture, donc rejetait un FIFO, `/dev/stdin` **et** une substitution de
processus (`<(...)`) — des entrées légitimes que `read_text()` seul lisait déjà sans encombre.
Pour le FIFO nommé et `/dev/stdin` : fermé, en n'excluant que les répertoires en lecture — un
FIFO résout normalement (chemin réel existant), donc passe. Pour la substitution de
processus : **non fermé, délibérément, après un aller-retour réel avec la CI**. Un premier
essai ajoutait un repli sur le chemin non résolu quand `resolve(strict=True)` échoue lui-même
sur ce type d'entrée (mesuré : `<(...)` résout vers un `pipe:[N]` synthétique, introuvable) —
`COORDINATION_OK` obtenu localement, mais SonarCloud a rouvert `pythonsecurity:S8707` sur le
code réel de ce dépôt : sur ce repli précis, le chemin qui atteint `read_text()` n'a traversé
aucune validation, exactement le motif que cette fonction existe pour fermer. Vérifié avant
de conclure : `sonar analyze` local, `--depth DEEP` inclus, **ne reproduit pas** ce
diagnostic sur ce fichier — seule l'analyse serveur réelle (taint inter-fonctions) le voit ;
un local vert n'est pas une preuve sur cette règle précise. Le repli est retiré : arbitrage
assumé entre un gate CI dur et une entrée légitime mais jamais observée dans l'usage
documenté de cet outil (toujours invoqué sur un chemin de fichier réel dans ce dépôt).

Mesuré à HEAD : chemin = répertoire → `LECTURE_IMPOSSIBLE:n'est pas un fichier regulier :
<chemin>`, exit 2 ; contenu non UTF-8 → `LECTURE_IMPOSSIBLE:'utf-8' codec can't decode byte
...`, exit 2 ; `--json-output` vers cible non inscriptible → `SORTIE_IMPOSSIBLE:...`, exit 2 ;
FIFO nommé lisible en entrée → `COORDINATION_OK`, comme avant `_chemin_sur()` ; substitution
de processus en entrée → `LECTURE_IMPOSSIBLE:[Errno 2] No such file or directory: '/proc/.../
pipe:[...]'`, exit 2 — limite assumée, ci-dessus ; boucle de liens symboliques, en entrée
comme en cible `--json-output` → `LECTURE_IMPOSSIBLE:Symlink loop from '<chemin>'` /
`SORTIE_IMPOSSIBLE:Symlink loop from '<chemin>'`, exit 2 des deux côtés — `resolve()` lève
`RuntimeError` sur ce cas précis, jamais `OSError` ; trouvé en revue scellée (le seul défaut
CRITIQUE/MAJEURE du tour suivant celui qui a fermé le FIFO), fermé en reconvertissant cette
`RuntimeError` en `OSError` dans `_chemin_sur()` elle-même plutôt qu'en élargissant les
`except` de `main()`, pour ne pas capturer au passage une `RuntimeError` sans rapport,
survenue plus loin dans `validate()`/`parse_rows()`. Contrat : 0 = table lue et conforme ;
1 = table lue, non conforme ; 2 = aucun verdict de conformité exploitable. Documenté dans
`coordination/README.md`, à côté de
`COORDINATION_OK`.

### Diff contre le pack

`valid_scope()` est la seule fonction du pack reprise inchangée. `parse_rows()`, `overlaps()`,
`validate()` et `main()` diffèrent tous ; `_chemin_sur()` n'a pas d'équivalent dans le pack du
tout — fonction neuve, pas un écart sur une fonction existante. Vérifiable fonction par
fonction sans décompte, contre le pack installé, plutôt que sur une liste recopiée ici — c'est
le diff qui fait foi.

## `.claude/settings.example.json` — ne jamais écraser `.claude/settings.json`

`.claude/settings.example.json` est livré par cette PR. `.claude/settings.json` (le fichier
réel, pas l'exemple) est un fichier **préexistant** du dépôt, que cette PR ne touche pas
(`git cat-file -e origin/main:.claude/settings.json` réussit, et il n'apparaît pas dans
`git diff --name-status origin/main...HEAD`). Copier l'exemple par-dessus le fichier réel en
remplacerait le contenu **quel qu'il soit**, sans avertissement : la mise en garde tient
sans dépendre de ce que ce fichier porte aujourd'hui, et rien de son contenu n'est recopié
ici. Voir la mise en garde portée dans `coordination/README.md`.

## Active

Ici comme dans les sections de suivi qui suivent, **seuls les numéros d'issue et de PR sont
écrits** : ni énoncé, ni périmètre, ni état ne sont recopiés. Ce qui reste est ce que ce
dépôt porte localement — un Work ID, une branche, un statut lisible dans
`coordination/WORK-OWNERSHIP.md`.

| Work ID | Branche | État |
|---|---|---|
| OPS-OVERLAY-INSTALL | `claude/ops/install-coordination-overlay` | PR #564 ; revue aveugle scellée itérée, verdict REJECT à chaque tour, majoritairement sur la **même classe de défaut** : une affirmation contenue dans un fichier livré, vérifiable et non re-mesurée contre HEAD. Corrigée site par site, elle réapparaissait au tour suivant, à côté — y compris sous une forme qu'aucune relecture n'aurait attrapée : exacte au tour où elle a été écrite, mesurée fausse au tour suivant sans qu'on y ait retouché. Le remède appliqué ici n'est donc plus la correction site par site mais la **réduction de surface** : ce qui porte sur autre chose que les fichiers livrés par cette PR est retiré, pas réécrit. Aucun décompte de tours n'est figé ici : il serait faux au tour suivant |
| LIVE-ISSUE-RECONCILIATION | read-only | triage live ; candidats suivis par numéro seul — issues #565, #568, #576 ; PR #567, #571 |

Deux lignes actives ici, cohérent avec `coordination/WORK-OWNERSHIP.md` et avec
`python3 -B tools/check_coordination.py coordination/WORK-OWNERSHIP.md` (`active=2` : les
statuts `REVIEW`/`ACTIVE` de `OPS-OVERLAY-INSTALL` et `LIVE-ISSUE-RECONCILIATION`).
`AUD-CORE-006`, `AUD-CI-003` et `AUD-CI-004` ne figurent pas dans cette table parce que leur
statut dans `WORK-OWNERSHIP.md` n'appartient pas à l'ensemble `ACTIVE` du validateur — c'est
une propriété locale des fichiers livrés, recalculable par la commande ci-dessus, et non un
relevé de l'état GitHub de leurs PR.

## Merged since last sync

Aucune liste de SHA de merge n'est figée ici, et aucun état de PR n'y est recopié. Motif
pour les SHA : un rebase de cette branche ne change pas quels merges ont eu lieu sur
`origin/main`, mais il change les SHA locaux disponibles pour les nommer — une valeur figée
à la place d'une commande devient fausse ou incomplète sans qu'aucun fait réel n'ait changé.
Ce qui se recense de façon stable :

- Missions dont le statut est passé à `MERGED` dans `coordination/WORK-OWNERSHIP.md` depuis
  la mise au point précédente : `AUD-CORE-006` (PR #571), `AUD-CI-003` et `AUD-CI-004`
  (PR #567). Ce statut est une valeur locale d'un fichier livré, relisible dans sa table ;
  l'état GitHub correspondant se vérifie par `gh pr view <n>`, jamais ici.
- Merges externes absorbés dans `origin/main` depuis la base connue à la mise au point
  précédente, hors missions suivies ici (ex. travaux Core) : à recenser via
  `git log --merges --oneline <base-de-la-dernière-sync>..origin/main`, jamais à recopier en
  valeur figée ici — cette commande reste valide après rebase, squash, amend ou avance de
  `main`, contrairement à toute liste de SHA écrite directement dans ce fichier.

## Blocked

Ce qui est consigné ici est la seule décision locale — la mission ne progresse pas, et ce
qu'elle attend de notre côté. Les numéros renvoient à la source.

- `AUD-CANON-001` / `AUD-CANON-002` — gate #541 : décision enregistrée côté pack
  (`docs/core/CANON-INDEX.md` comme canon, #564 propriétaire exclusif de `coordination/**`,
  #566 propriétaire de la promotion canonique — `live-guidance/ISSUE-541-DECISION.md` du
  pack v1.4). `gh issue view 541` fait foi de son état de fermeture sur GitHub, non recopié
  ici. Preuve produite, promotion non exécutée.
- `AUD-CI-003` / `AUD-CI-004` — ne sont plus tenues pour bloquées de notre côté ; leur statut
  dans `WORK-OWNERSHIP.md` est `MERGED`.
- Issue **#569**, citée de notre côté comme motif du gel des deux précédentes : ni son état,
  ni son énoncé, ni ses commentaires ne sont recopiés ici — `gh issue view 569` fait foi.
  **La distinction qui compte et qui reste : issue ouverte ≠ blocage constaté.** Ce sont deux
  faits séparément vérifiables, et ce fichier n'en affirme aucun.
- `AUD-CORE-005` — issue #568 : décision Nathan demandée (restaurer / retirer / requalifier)
  avant tout code. L'énoncé est dans l'issue, pas ici.

## Next

`AUD-CI-002` (épinglage SHA des actions) porte l'issue **#576** ; `gh issue view 576` fait
foi sur son énoncé, son périmètre et son état.

Ce fichier n'énonce **rien** sur ce qu'un oracle de tests de ce dépôt couvrirait ou ne
couvrirait pas. Motif, et il est mesuré : une version antérieure de ce paragraphe portait
une telle affirmation, assortie des trois commandes qui la rejouaient — et ces trois
commandes la **réfutent aujourd'hui**, alors même que rien de ce paragraphe n'avait été
touché depuis. Aucune relecture attentive n'aurait pu l'attraper : elle était exacte quand
elle a été écrite. Une affirmation sur l'état des tests n'appartient donc pas à un fichier
livré par cette PR ; elle se lit dans le dépôt.

Statut local d'`AUD-CI-002` : `QUEUED` dans `WORK-OWNERSHIP.md`, mission non activée.
Prochaine action utile : activer #576, et suivre la décision Nathan sur #568.
