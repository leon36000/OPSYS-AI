# Status Claude Code

Updated UTC : `2026-08-27T04:41Z`

**Péremption : ce fichier entier, prose comprise**, daté de l'horodatage ci-dessus et soumis à
la clause portée en tête de `coordination/WORK-OWNERSHIP.md` (non dupliquée ici). Au-delà de
24 h, re-vérifier par `gh pr view <n>` / `gh issue view <n>` plutôt que faire confiance à ce
texte.

## Vérification runtime

- Lead : `claude-opus-5` — choix explicite Nathan (`06-CLAUDE-LEAD-PROMPT.md`, hors dépôt).
- Sous-agents : `sonnet` (Claude Sonnet 5), conforme au champ `model` des 4 fichiers
  `.claude/agents/opsys-issue-*.md` livrés ici. Canon désigné : `docs/core/CANON-INDEX.md`
  (porté par #566, pas encore fusionné) ; `CLAUDE.md` (hors de cette PR) en est un adaptateur.
- Effort `max` par sous-agent : non réglable depuis l'outil d'invocation courant — écart
  consigné, non masqué.
- Écriture autorisée (décision Nathan) ; `BLOCKED_RUNTIME_IDENTITY` non appliqué.

## Périmètre autorisé pour cette session

Jusqu'à la PR ouverte incluse, avec merge autonome par le propriétaire si les critères de la
décision Nathan du 2026-08-27 sont réunis — trio de validation sur le SHA final compris
(critères énumérés dans `08-TRIO-AND-MERGE-AUTONOMY.md`, hors dépôt, non recomptés ici).
Aucune modification de branch protection, aucun code métier
M1–M10, aucune promotion canonique.

## Capacité des agents `.claude/agents/opsys-issue-*.md`

Le corps de prompt de ces rôles a été exercé par injection manuelle du texte dans un autre
outil d'invocation (le dossier projet de la session n'est pas ce dépôt ; aucun chargement
natif `.claude/agents/` n'a été observé) :

- **triage** (read-only) → `LIVE-ISSUE-RECONCILIATION`, sans issue ni PR propre ; candidats
  produits.
- **ci-docs** → issue #565 → PR #567.
- **security-quality** → issue #570 → PR #571.
- **restructure** : aucune mission n'a encore exercé ce rôle.
- L'installation de l'overlay (cette PR, #564) est de la même famille que **ci-docs**, mais
  n'est pas une exécution du fichier `opsys-issue-ci-docs.md` : ce fichier est créé *par*
  cette branche (statut `A`), pas rejoué depuis elle.

Non prouvé, écart nommé : que le chargeur natif `.claude/agents/` honore, pour ces fichiers,
aucun champ de leur en-tête YAML (`tools`, `permissionMode`, `effort`, `background`, `maxTurns`,
`disallowedTools`, `isolation`) — `tools` compris, le plus load-bearing (c'est lui qui porte le
blocage Write/Edit/NotebookEdit annoncé par `opsys-issue-triage.md`). Le **contenu** des rôles a
tourné en conditions réelles ; leur **enveloppe de permissions déclarée** n'a jamais été
vérifiée en exécution.

## Écarts de permissions vis-à-vis du pack amont

`diff -u` entre chaque fichier livré et son homologue du pack (`$OPSYS_PACK/platform-overlay/
...`, où `$OPSYS_PACK` désigne le répertoire où le pack `OPSYS-AI-CLAUDE-ISSUES-AUTONOMOUS-v1.4`
a été dépaqueté) fait autorité sur les écarts réels ; ce qui suit résume leur signification, pas
un décompte figé.

1. **`defaultMode`** : `"auto"` → `"default"`, ajout de `"disableAutoMode": "disable"`. Motif :
   l'autorité des outils déterministes prime sur l'approbation par un modèle. Voir aussi
   `AGENTS.md` (hors de cette PR).
2. **`deny` Bash** : `Bash(cat .env*)` etc. ajoutés en miroir des règles `Read(...)` par outil,
   qui ne couvrent pas `Bash`. Limite assumée, non exhaustive : ne couvre ni les autres
   commandes de lecture (`sed`, `awk`, `python3 -c`, …) ni les variantes de chemin
   (absolu, `..`, lien symbolique). La protection réelle reste : ne pas versionner de secret,
   permissions OS, hooks déterministes.
3. **`env.ANTHROPIC_DEFAULT_SONNET_MODEL`** : ajouté ici, absent du pack. Exprime la version
   exacte de l'alias `sonnet` sans figer `model` — portée limitée à ce qui invoque l'alias.
   Les 4 fichiers `.claude/agents/opsys-issue-*.md` portent `model: claude-sonnet-5` en dur,
   identique au pack : hors de la portée de ce point.
4. **`permissionMode`** : `auto` (pack) → `default` pour les 3 agents non-`triage`, `plan`
   inchangé pour `triage`. Même motif que le point 1, appliqué cette fois aux fichiers
   *destinés* au chargeur natif `.claude/agents/` — pas à un chargement natif constaté : voir
   la section « Capacité des agents » ci-dessus, qui reste la source sur ce point.

## `tools/check_coordination.py` — écarts vis-à-vis du pack amont

`diff -q "$OPSYS_PACK/tools/check_coordination.py" tools/check_coordination.py` signale une
différence ; `diff -u` donne le détail exact. Critère de conservation (décision Nathan) : un
écart n'est gardé que s'il ferme un fail-open mesuré (le pack rend vert à tort, ce fichier
rouge) — sinon retiré avec sa prose. Les sous-sections suivantes ne sont pas une énumération
exhaustive ligne à ligne ; `diff -u` reste la seule source qui ne peut pas devenir incomplète
en silence.

### `HEADER_MISSING`

`parse_rows()` exige l'en-tête suivi **immédiatement** d'une vraie ligne de séparation, sinon
`validate()` ajoute `HEADER_MISSING`. Ferme un fail-open du pack (fichier sans table →
`COORDINATION_OK rows=0` à tort). Mesuré à HEAD : `WORK-OWNERSHIP.md` →
`COORDINATION_OK rows=9 active=2` ; `DAILY-SYNC.md`/`24H-UPDATE-TEMPLATE.md`/`README.md` →
`HEADER_MISSING` exit 1 ; gabarit neuf (en-tête + séparateur, zéro ligne) →
`COORDINATION_OK rows=0 active=0`.

`SEPARATOR_RE` (tour 8) : l'ancien test vérifiait seulement que la ligne COMMENÇAIT par
`|---`, donc une ligne de DONNÉES dont la première cellule débute aussi par `---`
(Work ID `---X`) était prise pour une ligne de séparation et silencieusement exclue de la
table — `MODULE_CODE_DURING_CORE` et les collisions y compris. Fermé par un motif sur la
ligne ENTIÈRE (`^\|(-+\|)+$`), sans faire régresser les deux limites déjà nommées dans
`coordination/README.md` (séparateur espacé ou aligné par deux-points toujours non
reconnu — vérifié inchangé après ce correctif). Mesuré : `|---X | NATHAN | main |
modules m/M7 | ACTIVE | ... | ... |` → deux lignes, `BRANCH:---X` (branche `main` en ligne
ACTIVE, incident à cette fixture précise, pas au correctif) puis `MODULE_CODE_DURING_CORE:
---X`, exit 1 (au lieu de `COORDINATION_OK rows=0 active=0` à tort, l'interdit dur de
l'ADR-0004 non testé compris).

### `overlaps()` — casse et séparateur normalisés

Normalise casse et séparateur des scopes avant comparaison, cohérent avec
`MODULE_CODE_DURING_CORE`. Ferme un fail-open du pack (`Coordination` vs `coordination`, ou
`a\b` vs `a/b` : collision manquée côté pack). Mesuré : `PATH_COLLISION:ISS-A:ISS-B:
Coordination:coordination`, exit 1 ; `PATH_COLLISION:ISS-A:ISS-B:coordination\sub:
coordination/sub`, exit 1.

### `MODULE_CODE_DURING_CORE` — scope multiple, normalisé par élément

Découpe la cellule `scope` sur `;` et teste chaque élément via `PurePosixPath` (égalité, ou
parenté avec `modules m` dans les DEUX sens — descendant et ancêtre —, même mécanisme que
`overlaps()`), pas une comparaison de chaîne sur la cellule entière. Ferme plusieurs
fail-opens sur le seul interdit dur de l'ADR-0004 (aucun code métier M avant handoff Core),
pas de décompte figé ici — `tools/check_coordination.py` porte le détail et `diff -u` reste
la source qui ne peut pas devenir incomplète en silence : `coordination;modules m/M7`
(cellule entière testée, pas ses éléments), `./modules m/M7` (préfixe `./`, que
`valid_scope()` accepte et qu'une comparaison de chaîne brute ne reconnaît pas comme
équivalent à `modules m/M7`), et un scope `.` ou `./` (tour 10 — couvre tout l'arbre,
`modules m/` compris, mais le test ne portait que sur le sens descendant/égalité, jamais
sur le sens ANCÊTRE manquant, symétrique de celui déjà présent dans `overlaps()`). Mesuré à
HEAD : les deux premières fixtures et `./coordination;./modules m/M7` →
`MODULE_CODE_DURING_CORE:<id>`, exit 1 ; scope `.` ou `./` → `MODULE_CODE_DURING_CORE:<id>`,
exit 1 (tour 10).

### `BRANCH_COLLISION` — sentinelle `n/a` exemptée

**Exception assumée au critère de conservation ci-dessus** (revue scellée, tour 9) : cet
écart va dans le sens INVERSE des autres — le pack rend `BRANCH_COLLISION` à tort sur deux
missions `read-only` actives, ce fichier le lève. Gardé pour la même raison que les « 148
tâches » de `CODEX-QUEUE.md` sont gardées verbatim malgré la doctrine anti-décompte : un
correctif d'expressivité mesuré, pas la fermeture d'un fail-open, mais nécessaire pour que
deux missions `read-only` actives restent exprimables.

`WORK-OWNERSHIP.md` utilise `n/a` comme branche des missions `read-only`. Le contrôle `BRANCH`
ne le refuse pas — il rejette seulement `main`/`master`/vide en ligne active (`branch.lower()
in {"main", "master", ""}`), une liste de refus où `n/a` n'apparaît pas, ce qui n'équivaut
pas à une autorisation explicite. `BRANCH_COLLISION` comparait les branches brutes sans cette
exemption, symétrique de celle que `SCOPES_HORS_COLLISION` donne déjà à `read-only` côté scope
— deux missions `read-only` actives, toutes deux `n/a`, devenaient donc inexprimables. Fermé :
`n/a` (casefold) exempté, comme `read-only` l'est pour `PATH_COLLISION`. Mesuré à HEAD : deux
lignes actives `read-only`/`n/a` → `COORDINATION_OK`, exit 0.

`valid_scope()` rendait aussi `True` sur une cellule composée uniquement de `;` et d'espaces
(`;`, `; ;`) : non vide au sens de `scope.strip()`, mais sans aucun item après découpage — la
boucle de validation ne s'exécutait alors jamais. Fermé : liste d'items vide après découpage
→ `False`, donc `SCOPE:<id>:<valeur>`. Mesuré à HEAD : scope `;` ou `; ;` → `SCOPE:<id>:...`,
exit 1 (au lieu de `COORDINATION_OK` à tort, collisions et interdit M non testés compris).

### Lecture et écriture — `_chemin_sur()`

`main()` intercepte `(OSError, UnicodeDecodeError)` en lecture (`LECTURE_IMPOSSIBLE:<raison>`,
exit 2) et `OSError` en écriture (`SORTIE_IMPOSSIBLE:<raison>`, exit 2) — ferme le fail-open du
pack où une table lue et conforme, mais dont `--json-output` échoue à l'écriture, rendait le
même exit 1 qu'une table non conforme.

`_chemin_sur()` valide le chemin avant tout accès disque (SonarCloud `pythonsecurity:S8707`) :
octet nul refusé (garde défensive, non mesurable en CLI — `execve`/Python refuse un tel
octet dans un argument avant même le lancement du script ; atteignable seulement en usage
bibliothèque), `resolve()`, boucle de liens symboliques reconvertie en `OSError` (sinon
`RuntimeError`, non intercepté par `main()`). En lecture, seuls les répertoires sont refusés —
un FIFO nommé passe ; `/dev/stdin` ne passe QUE sur redirection depuis un fichier régulier
(`tool /dev/stdin < f`), pas adossé à un tube (`cat f | tool /dev/stdin`, l'usage courant) : ce
dernier cas, comme la substitution de processus (`<(...)`), reste refusé
(`LECTURE_IMPOSSIBLE`) — les deux résolvent vers le même `pipe:[N]` synthétique que `resolve()`
ne peut pas résoudre sans emprunter un chemin de code que SonarCloud refuse (détail dans le
docstring de la fonction) — limite assumée, ces deux formes n'étant jamais observées dans
l'usage documenté de ce dépôt. En écriture, la cible doit être un fichier régulier ou un
chemin inexistant.

Mesuré à HEAD : répertoire → `LECTURE_IMPOSSIBLE:est un repertoire`, exit 2 ;
non-UTF-8 → `LECTURE_IMPOSSIBLE:'utf-8' codec can't decode...`, exit 2 ; sortie non
inscriptible → `SORTIE_IMPOSSIBLE:...`, exit 2 ; FIFO nommé → `COORDINATION_OK` ; substitution
de processus → `LECTURE_IMPOSSIBLE:[Errno 2]...`, exit 2 ; boucle de liens (lecture et sortie)
→ `LECTURE_IMPOSSIBLE`/`SORTIE_IMPOSSIBLE:Symlink loop from '<chemin>'`, exit 2. Contrat :
0 = table lue et conforme, 1 = table lue et non conforme, 2 = aucun verdict exploitable.

Fermé aussi ici (tour 8, corrigé pour de bon au tour 10 — voir plus bas) : un chemin argv
non-UTF-8 (décodé par Python avec `surrogateescape`, PEP 383) faisait échapper les trois
messages `OSError` propres à cette fonction (répertoire de sortie inexistant, cible non
régulière, cible = répertoire) — `str(chemin)` y porte alors des surrogates bas, et le
`print()` de `main()` sur `LECTURE_IMPOSSIBLE`/`SORTIE_IMPOSSIBLE` levait
`UnicodeEncodeError`, non intercepté : exit 1 avec traceback, stdout vide, indiscernable
d'une table non conforme. Fermé au tour 8 en formatant le chemin par `repr()` (`!r`) dans
ces trois messages précis.

**Le tour 9 a introduit une régression de raisonnement, corrigée au tour 10.** Il affirmait
que « les `OSError` levées par le système (`FileNotFoundError`, etc.) n'ont jamais ce
problème : leur `str()` interne repr déjà le nom de fichier » — **faux**, réfuté par sa
propre mesure adjacente : `str(OSError)` passe justement par un `repr()` interne, et le
tour 9 venait de mesurer que `repr()` laisse passer tel quel tout caractère non-ASCII
VALIDE (pas seulement les surrogates), qui casse sous `PYTHONIOENCODING=ascii`. La
correction du tour 9 (`ascii()`/`!a` sur les messages construits à la main) posait donc
la protection au mauvais étage : aux sites `raise` de `_chemin_sur()` (leur nombre exact
n'est pas figé ici, un `grep` sur `!r}"` en donne le compte courant — décompte déjà pris
en défaut une fois : le tour 9 en comptait trois de mémoire alors qu'il venait, dans le
même commit, de scinder un message en deux), jamais
aux sites `print()` de `main()` où l'encodage a réellement lieu — ni aux `OSError` système,
ni au troisième `print()` (`"\n".join(errors)`), atteignable sans aucun argv exotique dès
qu'une CELLULE de table porte un accent (réaliste : ce dépôt rédige ses tables en français).
Revue scellée (tour 10, 2 sièges convergents), mesuré sous `PYTHONIOENCODING=ascii` avant
correction : chemin argv inexistant accentué, permission refusée sur répertoire accentué,
`--json-output` non inscriptible de nom accentué, et une simple cellule `scope` accentuée →
les quatre rendaient exit 1, stdout VIDE, traceback, au lieu de `LECTURE_IMPOSSIBLE`/
`SORTIE_IMPOSSIBLE` exit 2 ou d'une ligne `SCOPE:`/`PATH_COLLISION:` exit 1 propre — le
fail-open que ce fichier existe pour fermer. **Fermé pour de bon** en sécurisant STDOUT
lui-même, une seule fois, en tête de `main()` : `sys.stdout.reconfigure(errors=
"backslashreplace")` — couvre les quatre `print()` de `main()` sans exception, sans effet
sous UTF-8 (mesuré : aucun caractère de ce dépôt n'est inencodable en UTF-8). `!a` est donc
redevenu inutile aux sites où le tour 9 l'avait introduit et a été repris en `!r` (plus
lisible), la protection réelle vivant désormais au seul point d'impression. Mesuré après
correction : les quatre cas ci-dessus rendent tous un exit et un préfixe propres, message
lisible (accents échappés en `\xHH`), sans traceback.

**Régression introduite par ce correctif lui-même, fermée au tour 11** (revue scellée,
2 sièges convergents) : `sys.stdout.reconfigure(...)` est la toute première instruction
de `main()`, or CPython met `sys.stdout` à `None` quand le descripteur de sortie standard
est déjà fermé au lancement (`... >&-`) — `reconfigure()` levait alors `AttributeError`,
non intercepté : exit 1 avec traceback, stdout vide, sur une entrée qui ne l'atteignait
PAS avant ce commit (mesuré par contre-épreuve : sans cette ligne, les quatre `print()`
de `main()` no-opent silencieusement sur un flux clos, table conforme comme non conforme).
Fermé par une garde `if sys.stdout is not None:` — rien à reconfigurer quand il n'y a pas
de flux, et le silence d'avant ce commit est restauré pour ce cas précis.

Deux affinages supplémentaires au tour 9, restés valides et non affectés par ce qui
précède, tous deux mesurés avant correction : le message « répertoire de sortie
inexistant » sortait aussi quand le parent de la cible EXISTE mais n'est pas un répertoire
(`is_dir()` est faux dans les deux cas) — distingué par un test `exists()` séparé, message
dédié « le parent de la sortie n'est pas un répertoire » pour ce second cas. Et
`--json-output` pointant sur le même chemin (résolu) que l'argument
`ownership` écrasait silencieusement la table qui venait d'être validée par le JSON de son
propre résultat, exit 0 — même famille que l'écrasement documenté pour
`.claude/settings.json` plus bas, mais non gardé ici jusqu'ici. Fermé : `SORTIE_IMPOSSIBLE`,
exit 2, si les deux chemins résolus coïncident. Mesuré : `tool w.md --json-output w.md`,
avant correctif → `COORDINATION_OK` exit 0 et `w.md` réduit au JSON de résultat ; après
correctif → `SORTIE_IMPOSSIBLE:la sortie --json-output ecraserait le fichier ownership
lui-meme`, exit 2, fichier d'entrée intact.

### Diff contre le pack

`valid_scope()` diffère du pack sur plusieurs points, pas seulement cosmétiques : la
constante `SCOPES_HORS_COLLISION` (extraction SonarCloud `S1192`) ; la normalisation
antislash avant `PurePosixPath` (`item.replace("\\", "/")`) — sans elle, `foo\..\modules
m\M7` passe ce contrôle puis échappe aussi à `MODULE_CODE_DURING_CORE`, fixture mesurée,
donc pas sémantiquement identique au pack sur ce point ; et le refus d'une liste d'items
vide après découpage (section précédente). `parse_rows()`, `overlaps()`, `validate()`,
`main()` diffèrent tous aussi, pas seulement cosmétiquement. `_chemin_sur()` n'a pas
d'équivalent dans le pack.

## `.claude/settings.example.json` — ne jamais écraser `.claude/settings.json`

`.claude/settings.json` (le fichier réel, pas l'exemple) est préexistant, hors de cette PR.
Copier l'exemple par-dessus remplacerait son contenu, quel qu'il soit, sans avertissement.

## Active

Seuls les numéros d'issue et de PR sont écrits ; `gh issue view <n>` / `gh pr view <n>` fait
foi de l'état GitHub.

| Work ID | Branche | État |
|---|---|---|
| OPS-OVERLAY-INSTALL | `claude/ops/install-coordination-overlay` | PR #564 |
| LIVE-ISSUE-RECONCILIATION | `n/a` | triage live, scope `read-only` — issues #565, #568, #576 ; PR #567, #571 |

Cohérent avec `WORK-OWNERSHIP.md` et `python3 -B tools/check_coordination.py
coordination/WORK-OWNERSHIP.md` (`active=2`).

## Merged since last sync

- `AUD-CORE-006` (PR #571), `AUD-CI-003` + `AUD-CI-004` (PR #567) — statut `MERGED` dans
  `WORK-OWNERSHIP.md`.
- Merges externes absorbés dans `origin/main` hors missions suivies ici :
  `git log --merges --oneline <base-de-la-dernière-sync>..origin/main`.

## Blocked

- `AUD-CANON-001` / `AUD-CANON-002` — gate #541 tranché côté pack (canon
  `docs/core/CANON-INDEX.md`, #566 propriétaire de la promotion) ; promotion non exécutée.
- Issue #569 : `gh issue view 569` fait foi ; issue ouverte ≠ blocage constaté.
- `AUD-CORE-005` — issue #568 : décision Nathan demandée (restaurer / retirer / requalifier)
  avant tout code.

## Next

`AUD-CI-002` (épinglage SHA des actions) — issue #576, statut `QUEUED` dans
`WORK-OWNERSHIP.md`, mission non activée.
