# Status Claude Code

Updated UTC : `2026-08-27T02:14Z`

## Vérification runtime (07-RUNTIME-CHECK, constat unique de session)

- Lead observé : `claude-opus-5`. Le pack demande `claude-sonnet-5`.
  **Écart réel, ratifié explicitement par Nathan dans la session du 2026-08-26T02:14Z.**
  Aucun fallback silencieux : l'écart est consigné ici, pas masqué.
- Sous-agents : instanciés en `sonnet` (Claude Sonnet 5), **conforme au pack amont, mais
  pas à `CLAUDE.md:9`**, qui prescrit pour les sous-agents des noms LiteLLM dédiés
  (`crew-coder-long`, `crew-coder-bulk`, etc.), jamais `opus`/`sonnet`/`haiku`. Le champ
  `model: claude-sonnet-5` des 4 fichiers `.claude/agents/opsys-issue-*.md` porte le même
  écart. **Écart consigné ici, modèle non changé dans cette revue** : requalifier ces
  4 champs `model` vers des noms LiteLLM dédiés est une décision produit (quel modèle par
  rôle) hors périmètre d'une correction de revue, à faire avec validation Nathan plutôt
  que silencieusement ici.
  Les définitions `.claude/agents/opsys-issue-*.md` sont installées dans ce dépôt ;
  le dossier projet de la session courante étant distinct, les agents sont invoqués
  en injectant leur prompt et leurs contraintes verbatim.
- Effort `max` par sous-agent : non réglable depuis l'outil d'invocation courant.
  **Écart consigné**, non masqué.
- Écriture autorisée : oui (décision Nathan). `BLOCKED_RUNTIME_IDENTITY` non appliqué.

## Périmètre autorisé pour cette session

Jusqu'à la **PR ouverte** incluse. **Aucun merge**, aucune modification de branch
protection, aucun code métier M1–M10, aucune promotion canonique.

## Capacité des 4 agents `.claude/agents/opsys-issue-*.md` — ce qui est prouvé, ce qui ne l'est pas

Objection de revue : ces 4 définitions n'ont jamais été exercées comme fichiers
`.claude/agents/` chargés nativement, et deviennent après merge chargeables avec
`tools` incluant Write/Edit, `maxTurns: 240` (jusqu'à ce commit, trois d'entre elles
portaient en plus `permissionMode: auto` ; corrigé en `default` — voir « Écarts
volontaires » ci-dessous). Ne pas dégrader en `.example` — mais ne pas non plus
prétendre à une capacité non observée. Détail :

**Ce qui EST prouvé** — le corps de prompt (hors frontmatter YAML) de ces 4 rôles a été
exercé comme instruction de sous-agent, verbatim ou quasi-verbatim, sur des missions
réelles et vérifiables de ce dépôt :
- **triage** (read-only, reconnaissance live) → `LIVE-ISSUE-RECONCILIATION`, sans issue
  ni PR propre (par construction : read-only) ; a produit les 3 candidats ci-dessous.
- **ci-docs** (CI/docs/canon/manifest) → issue **#565** → PR **#567** (gating CI
  bloquant, `.github/workflows/ci.yml`).
- **security-quality** (sécurité/tests/qualité/portabilité) → issue **#570** → PR
  **#571** (chemins hôte en dur dans `audit/core-baseline/`, défaut de portabilité).
- L'installation de l'overlay elle-même → issue **#563** → PR **#564** (cette PR) est
  de la même famille de travail que le rôle **ci-docs** (coordination/docs/manifest),
  mais **ne peut pas** être citée comme une exécution du fichier `opsys-issue-ci-docs.md` :
  ce fichier est *créé par* la branche `claude/ops/install-coordination-overlay` ; il
  n'existait dans aucun commit de `origin/main` avant cette branche — vérifiable par
  `git log origin/main -- .claude/agents/opsys-issue-ci-docs.md`, dont la sortie est vide.
  (Après le merge de cette PR, la même commande cessera d'être vide : elle listera alors
  l'historique de ce fichier sur `origin/main`, ce qui confirme le même fait sous une autre
  forme — la commande vérifie l'absence *avant* cette branche, pas une absence perpétuelle —
  et non son contraire.)
  Cette formulation ne nomme aucun SHA de cette branche, volontairement : un SHA de commit
  local ne survit ni à un rebase, ni à un squash, ni à un amend. Le troisième tour de revue
  avait corrigé ce paragraphe en nommant le SHA du premier commit d'alors, justifié par
  « reste vraie quel que soit le nombre de commits qui suivent » — vrai pour l'ajout de
  commits, silencieux sur la réécriture d'historique. Le rebase qui a suivi a rendu ce SHA
  inatteignable depuis toute ref (`git rev-list --all` ne le liste plus), ce qui a réfuté la
  phrase exactement au moment où un lecteur aurait pu la vérifier. Le fait qui importe — ce
  fichier appartient à cette branche, à aucun commit antérieur de `origin/main` — se dit sans
  SHA et reste vrai après rebase, squash, amend ou avance de `main` : c'est la formulation
  retenue ci-dessus. Une formulation qui dirait « seul commit de la branche » serait un
  défaut différent, non traité ici par accident mais par non-pertinence : elle cesserait
  d'être vraie dès le commit suivant sur cette branche, réécriture ou non, et n'est donc pas
  celle utilisée. C'est le travail de l'orchestrateur (session lead), pas un rejeu du fichier
  commité.
- **restructure** (restructuration/packaging/nettoyage prouvé) : **aucune mission
  numérotée n'a encore exercé ce rôle**. Le candidat le plus proche est l'issue **#568**
  (AUD-CORE-005, fragment de packaging orphelin `.opsys/tools/github-control`), mais
  cette investigation s'est arrêtée en `BLOCKED` — aucun fichier modifié, aucune PR.
  Ne pas compter #568 comme une preuve d'exécution du rôle restructure.

**Ce qui N'EST PAS prouvé, et reste un écart nommé** — que le chargeur natif
`.claude/agents/` de Claude Code honore réellement, pour ces 4 fichiers, les champs de
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

Le fichier livré par `OPSYS-AI-CLAUDE-ISSUES-OPERATIONS-v1.2` (vérifié identique à
`platform-overlay/.claude/settings.example.json` du pack) porte `defaultMode: "auto"`,
`availableModels: ["claude-sonnet-5"]` et `model: "claude-sonnet-5"`. La copie de ce
dépôt s'en écarte, délibérément, sur trois points :

1. **`defaultMode`** : `"auto"` → `"default"`, et ajout de `"disableAutoMode": "disable"`
   à côté de `"disableBypassPermissionsMode"`. `AGENTS.md` liste l'auto-approbation
   parmi ses interdits absolus et pose « Outils déterministes = autorité ; aucun LLM
   n'écrit un score » — l'auto-approbation par un modèle est exactement l'inverse de ce
   principe. L'exemple suit donc le canon du dépôt plutôt que le défaut amont.
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
   le dépôt, permissions OS / gestionnaire de secrets, et les hooks déterministes
   (`AGENTS.md` : « Outils déterministes = autorité ») — pas cette liste, qui reste une
   politique côté client pour un agent coopératif.
3. **`availableModels` et `model`** : retirés de l'exemple (le pack amont fixe les deux
   à `"claude-sonnet-5"`). `CLAUDE.md` documente un roster LiteLLM multi-modèles
   (opus/sonnet/haiku en passthrough Orchestrateur, `crew-coder-long`, `crew-coder-bulk`,
   etc.) que `availableModels: ["claude-sonnet-5"]` interdirait purement et simplement
   de sélectionner, et que `model: "claude-sonnet-5"` contredirait par défaut. La
   section runtime ci-dessus documente d'ailleurs un écart déjà observé en pratique
   (lead réel `claude-opus-5` malgré la demande `claude-sonnet-5`) : figer `model` dans
   l'exemple ne tiendrait même pas face au comportement réel constaté. La clé
   `env.ANTHROPIC_DEFAULT_SONNET_MODEL` suffit à exprimer « quand sonnet est utilisé,
   cette version précise » sans verrouiller tout le reste.
4. **`permissionMode` des 3 agents `.claude/agents/opsys-issue-{ci-docs,restructure,
   security-quality}.md`** : le pack amont porte `permissionMode: auto` pour ces trois
   fichiers (champ `permissionMode` vérifié identique à celui de
   `platform-overlay/.claude/agents/` du pack — le reste du corps de ces 3 fichiers
   diffère légèrement, cf. `PREUVE:`/`BLOCKED:` ajouté en fin de prompt) et
   `permissionMode: plan` pour `opsys-issue-triage.md`. La revue scellée n°2 (objection
   N3) a relevé que le point 1 ci-dessus n'avait été appliqué qu'à un fichier inerte
   (`.claude/settings.example.json` n'est chargé par rien) et pas aux fichiers
   effectivement lus nativement par Claude Code (`.claude/agents/*.md`) — alors que ces
   trois agents portent `tools` incluant Write/Edit/Bash, `maxTurns: 240`,
   `background: true`, et que `.claude/settings.json` (le fichier réel, pas l'exemple) ne
   porte aucune clé `permissions` qui aurait pu compenser côté session. Correction : les
   trois `permissionMode: auto` sont passés à `permissionMode: default` dans ce commit,
   par le même raisonnement que le point 1 (« Outils déterministes = autorité » ;
   `AGENTS.md` liste l'auto-approbation parmi ses interdits absolus). `triage` reste
   `plan`, déjà plus restrictif qu'`auto` et hors-sujet de cet écart, sans changement.

## `tools/check_coordination.py` — écarts volontaires vis-à-vis du pack amont (validation)

Depuis le premier commit de cette branche, ce fichier **n'est plus une copie octet-exacte**
du `tools/check_coordination.py` du pack `OPSYS-AI-CLAUDE-ISSUES-OPERATIONS-v1.2` —
`README.md` affirmait cette exactitude, corrigé dès ce premier commit. Deux écarts mesurés,
localisés à deux fonctions :

### 1. `HEADER_MISSING` — absence d'en-tête non détectée, puis un faux positif corrigé

- **Constat initial** : `parse_rows()` ne validait que la *forme* des lignes de données ;
  l'absence totale de la ligne d'en-tête `| Work ID | Owner | Branch | Path scope | Status |
  Updated UTC | Next |` n'était jamais détectée. Conséquence mesurée — un mauvais chemin ou
  un fichier tronqué/vidé rendaient exactement le même succès qu'une vraie table :
  `python3 -B tools/check_coordination.py coordination/DAILY-SYNC.md` →
  `COORDINATION_OK rows=0 active=0`, exit 0, alors que ce fichier ne porte aucune table de
  coordination. Idem pour `coordination/24H-UPDATE-TEMPLATE.md`.
- **Piège écarté** : `rows == 0` n'est **pas** un discriminant valide — le gabarit neuf du
  pack (`repo-overlay/coordination/WORK-OWNERSHIP.md`, zéro ligne de données, en-tête
  présent) est légitimement vide et `tools/daily_start.py` du pack le valide comme tel sur
  une installation neuve. Une règle `rows == 0 → erreur` aurait cassé ce cas légitime.
- **Premier correctif** : `parse_rows()` a commencé à retourner si l'en-tête a été rencontré
  (`header_found: bool`) ; `validate()` ajoute l'erreur `HEADER_MISSING` quand il ne l'a pas
  été, indépendamment du nombre de lignes de données.
- **Défaut résiduel trouvé et corrigé dans ce commit** : ce premier correctif mettait
  `header_found = True` dès qu'une ligne était *égale* à l'en-tête, sans regarder ce qui la
  suit — y compris citée seule, en bloc de code ou en prose, pour documenter le format sans
  qu'aucune vraie table ne suive. Une fixture ad hoc (hors dépôt, cf. preuve de ce commit) le
  démontre : un document qui ne fait que citer la ligne d'en-tête dans un bloc de code
  passait à tort `COORDINATION_OK rows=0 active=0`. Correctif : `parse_rows()` ignore
  désormais tout contenu entre deux clôtures de bloc de code (les lignes commençant par trois
  apostrophes inverses ou par `~~~`) — jamais compté comme en-tête, séparateur ou ligne de
  données — et n'accepte `header_found = True` que si la ligne d'en-tête est **immédiatement
  suivie** d'une vraie ligne de séparation Markdown (ex. `|---|---|`, avec ou sans espaces ou
  `:` d'alignement). Une table vide **avec** en-tête et séparateur reste valide ; une simple
  citation de l'en-tête, en bloc de code ou non, ne l'est plus.
- **Vérifié après ce commit** : gabarit du pack → toujours `COORDINATION_OK rows=0 active=0`
  (inchangé, en-tête immédiatement suivi de son séparateur) ; vraie table de ce dépôt →
  `COORDINATION_OK rows=9 active=2` (`active` recalculé dans ce commit — voir « Active »
  ci-dessus, `AUD-CORE-006` est passée `MERGED`) ; `DAILY-SYNC.md` et
  `24H-UPDATE-TEMPLATE.md` → toujours `HEADER_MISSING`, exit 1 ; fixture « en-tête cité dans
  un bloc de code » → désormais `HEADER_MISSING`, exit 1 (avant ce commit : faux succès,
  exit 0).
- **Limite non résolue par ce correctif, à ne pas taire** : un fichier inexistant fait déjà
  échouer l'appel (`FileNotFoundError` non interceptée, traceback, exit 1) — ce n'était donc
  pas un faux succès, seulement un échec peu lisible ; ce correctif ne change pas ce
  comportement.
- **Diff contre le pack, à ce stade** : les fonctions `parse_rows()` et `overlaps()` (écart 2
  ci-dessous) diffèrent de la version installée ; `valid_scope()`, le reste de `validate()`
  et `main()` restent identiques. Se référer à `git diff`/`git show` de ce fichier pour le
  détail exact plutôt qu'à un décompte de lignes recopié ici : un décompte figé deviendrait
  faux à la prochaine édition de ce même fichier, sans qu'aucune opération Git n'y soit pour
  rien — la même leçon que le reste de ce commit, appliquée à un futur diff plutôt qu'à un
  SHA ou une révision.

### 2. `overlaps()` — casse non normalisée, incohérente avec `MODULE_CODE_DURING_CORE`

- **Constat, trouvé et corrigé dans ce commit** : dans `validate()`, le contrôle
  `MODULE_CODE_DURING_CORE` normalise déjà la casse du scope avant comparaison. `overlaps()`,
  lui, comparait les chemins de scope tels quels, sans normaliser la casse. Conséquence :
  deux lignes actives portant les scopes `Coordination` et `coordination` ne déclenchaient
  aucun `PATH_COLLISION`, alors que `MODULE_CODE_DURING_CORE` les aurait traitées comme
  identiques quelques lignes plus loin dans la même fonction `validate()` — incohérence
  interne héritée du pack amont (pas introduite par ce dépôt), jamais corrigée avant ce
  commit. Fixture ad hoc (hors dépôt) : deux lignes actives, branches distinctes, scopes
  `Coordination` et `coordination` → avant ce commit, `COORDINATION_OK rows=2 active=2`
  (collision manquée) ; après ce commit, `PATH_COLLISION:...`, exit 1.
- **Correctif** : `overlaps()` normalise désormais la casse des deux chemins avant
  comparaison, par le même principe que `MODULE_CODE_DURING_CORE`. Les deux contrôles de
  scope partagent maintenant la même notion de « même chemin ».

## `.claude/settings.example.json` — ne jamais écraser `.claude/settings.json`

`.claude/settings.json` (le fichier réel, pas l'exemple) porte les 3 hooks
d'enforcement de ce dépôt : `SessionStart` (injecte `00-DIGEST.md`), `UserPromptSubmit`
(rappel périodique via `inject_digest.sh`) et `PreToolUse` sur `Bash`
(`guard_forbidden.sh`, bloque `--no-verify` et le force-push sur `main`). Copier
`settings.example.json` par-dessus `settings.json` supprimerait ces trois hooks sans
avertissement. Voir la mise en garde portée dans `coordination/README.md`.

## Active

Les états PR/issue cités dans cette section et dans « Blocked »/« Next » ci-dessous sont
datés de l'horodatage `Updated UTC` en tête de ce fichier et soumis à la même clause de
péremption que `coordination/WORK-OWNERSHIP.md:7` (périment dès le prochain commit/push/merge
sur l'une ou l'autre plateforme ; au-delà de 24 h, re-vérifier via `gh pr view <n>` / `gh issue
view <n>` plutôt que de faire confiance à la valeur écrite ici) — non dupliquée, pour éviter
que les deux dérivent l'une de l'autre.

| Work ID | Branche | État |
|---|---|---|
| OPS-OVERLAY-INSTALL | `claude/ops/install-coordination-overlay` | PR #564 ouverte ; premier tour de revue aveugle scellée = REJECT (8 majeures, 4 mineures), corrigé au premier tour ; deuxième tour = REJECT à nouveau (le correctif du premier tour avait lui-même introduit des défauts), corrigé au deuxième tour ; troisième tour : le défaut nommé n'était plus un site isolé mais un motif (« le défaut ponctuel est corrigé, la classe ne l'est pas »), mais sa justification (« reste vraie quel que soit le nombre de commits qui suivent ») ne couvrait que l'ajout de commits, pas la réécriture d'historique — le rebase qui a suivi a rendu inatteignables les SHA que ce tour citait ; quatrième tour (ce commit) : critère d'invariance explicite (rebase, squash, amend, avance de `main`), plus aucun SHA de cette branche cité dans ce fichier |
| LIVE-ISSUE-RECONCILIATION | read-only | triage live en cours ; 3 candidats déjà triés — PR #567 (ouverte), issue #568 (bloquée en investigation), PR #571 (**mergée** : `gh pr view 571` → `MERGED`, et son commit de merge apparaît dans `git log --oneline HEAD` en cherchant `#571`) |

Deux lignes actives ici, cohérent avec `WORK-OWNERSHIP.md` et avec
`python3 -B tools/check_coordination.py coordination/WORK-OWNERSHIP.md` (`active=2` : les
statuts `REVIEW`/`ACTIVE` de `OPS-OVERLAY-INSTALL` et `LIVE-ISSUE-RECONCILIATION`).
`AUD-CORE-006` a quitté cette table dans ce commit, pour la raison inverse de celle qui l'y
avait fait entrer au tour précédent : sa PR #571 est mergée, donc son statut dans
`WORK-OWNERSHIP.md` est passé à `MERGED`, hors de l'ensemble `ACTIVE` du validateur — voir
« Merged since last sync » ci-dessous. `DAILY-SYNC.md` renvoie ici pour le détail
d'exécution de ces deux missions.

## Merged since last sync

Ne pas figer de liste de SHA de merge ici : un rebase de cette branche ne change pas quels
merges ont réellement eu lieu sur `origin/main`, mais il change les SHA locaux disponibles
pour les nommer — une valeur figée à la place d'une commande devient donc fausse ou
incomplète sans qu'aucun fait réel n'ait changé. Ce que l'on peut recenser de façon stable :

- Missions suivies dans `WORK-OWNERSHIP.md` passées à `MERGED` depuis la mise au point
  précédente : au moment de cette réconciliation, `AUD-CORE-006` (PR #571 — `gh pr view 571`
  → `MERGED`, et le commit de merge de #571 est un ancêtre de cette branche, visible dans
  `git log --oneline HEAD` en cherchant `#571`).
- Merges externes absorbés dans `origin/main` depuis la base connue à la mise au point
  précédente, hors missions suivies ici (ex. travaux Core) : à recenser via
  `git log --merges --oneline <base-de-la-dernière-sync>..origin/main`, jamais à recopier en
  valeur figée ici — cette commande reste valide après rebase, squash, amend ou avance de
  `main`, contrairement à toute liste de SHA écrite directement dans ce fichier.

## Blocked

- `AUD-CANON-001` / `AUD-CANON-002` — gate de l'issue live #541 :
  « aucune promotion canonique avant validation Nathan et revue externe ».
  Collision de design avec #523 (CLR-006) : `CANON-INDEX.md` à la racine contre
  `docs/core/CANON-INDEX.md` dans le patch candidat. Preuve produite, promotion non exécutée.
- `AUD-CI-003` / `AUD-CI-004` — PR #567 ouverte, CI vert hors `proof-sealed` ; gelées par
  l'issue #569 (capacité de revue à 1 vendor sur 11, seuil de 3 vendors distincts
  inatteignable pour sceller toute PR touchant `core/`, `ci.yml`, `core-ci.yml` ou
  `scripts/`). Rouge honnête, pas un faux vert.
- `AUD-CORE-005` — issue #568 : fragment orphelin `.opsys/tools/github-control`,
  correction TDD impossible sans fabriquer des données absentes ; décision Nathan
  demandée (restaurer / retirer / requalifier) avant tout code.

## Next

`AUD-CI-002` (épinglage SHA des actions) reste `QUEUED` derrière `AUD-CI-003/004` (même
fichier, jamais en parallèle) et, de toute façon, derrière la résolution de #569 (même
périmètre scellé). Prochaine action utile : suivre la restauration du routeur LiteLLM
(#569) et la décision Nathan sur `#568`, plutôt que de commencer du nouveau travail sur
`.github/workflows/ci.yml`.
