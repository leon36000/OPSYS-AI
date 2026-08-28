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
modules m/M7 | ACTIVE | ... | ... |` → `MODULE_CODE_DURING_CORE:---X`, exit 1 (au lieu de
`COORDINATION_OK rows=0 active=0` à tort, l'interdit dur de l'ADR-0004 non testé compris).

### `overlaps()` — casse et séparateur normalisés

Normalise casse et séparateur des scopes avant comparaison, cohérent avec
`MODULE_CODE_DURING_CORE`. Ferme un fail-open du pack (`Coordination` vs `coordination`, ou
`a\b` vs `a/b` : collision manquée côté pack). Mesuré : `PATH_COLLISION:ISS-A:ISS-B:
Coordination:coordination`, exit 1 ; `PATH_COLLISION:ISS-A:ISS-B:coordination\sub:
coordination/sub`, exit 1.

### `MODULE_CODE_DURING_CORE` — scope multiple, normalisé par élément

Découpe la cellule `scope` sur `;` et teste chaque élément via `PurePosixPath` (égalité ou
parenté avec `modules m`, même mécanisme que `overlaps()`), pas une comparaison de chaîne sur
la cellule entière. Ferme deux fail-opens sur le seul interdit dur de l'ADR-0004 (aucun code
métier M avant handoff Core) : `coordination;modules m/M7` (cellule entière testée, pas ses
éléments) et `./modules m/M7` (préfixe `./`, que `valid_scope()` accepte et qu'une comparaison
de chaîne brute ne reconnaît pas comme équivalent à `modules m/M7`). Mesuré à HEAD : les deux
fixtures et `./coordination;./modules m/M7` → `MODULE_CODE_DURING_CORE:<id>`, exit 1.

### `BRANCH_COLLISION` — sentinelle `n/a` exemptée

`WORK-OWNERSHIP.md` utilise `n/a` comme branche des missions `read-only` (`BRANCH` l'autorise
explicitement en ligne active). `BRANCH_COLLISION` comparait les branches brutes sans cette
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
octet nul refusé, `resolve()`, boucle de liens symboliques reconvertie en `OSError` (sinon
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

Fermé aussi ici (tour 8) : un chemin argv non-UTF-8 (décodé par Python avec
`surrogateescape`, PEP 383) faisait échapper les trois messages `OSError` propres à cette
fonction (répertoire de sortie inexistant, cible non régulière, cible = répertoire) —
`str(chemin)` y porte alors des surrogates bas, et le `print()` de `main()` sur
`LECTURE_IMPOSSIBLE`/`SORTIE_IMPOSSIBLE` levait `UnicodeEncodeError`, non intercepté :
exit 1 avec traceback, stdout vide, indiscernable d'une table non conforme — le fail-open
que ce fichier existe pour fermer, réintroduit sur une classe d'entrée non testée jusque
-là. Les `OSError` levées par le système (`FileNotFoundError`, etc.), elles, n'ont jamais
ce problème : leur `str()` interne repr déjà le nom de fichier. Fermé en formatant le
chemin par `repr()` (`!r`) plutôt que `str()` dans ces trois messages précis. Mesuré :
répertoire cible et `--json-output` de nom non-UTF-8 → `LECTURE_IMPOSSIBLE`/
`SORTIE_IMPOSSIBLE`, exit 2 dans les deux cas (au lieu d'exit 1 avec traceback à tort).

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
| LIVE-ISSUE-RECONCILIATION | read-only | triage live — issues #565, #568, #576 ; PR #567, #571 |

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
