# Status Claude Code

Updated UTC : `2026-08-26T10:59Z`

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
  ce fichier est *créé par* ce commit (`b552f87`, seul commit de la branche sur
  `31fa5497`) — il n'existait dans aucun commit du dépôt avant lui. C'est le travail de
  l'orchestrateur (session lead), pas un rejeu du fichier commité.
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

## `.claude/settings.example.json` — ne jamais écraser `.claude/settings.json`

`.claude/settings.json` (le fichier réel, pas l'exemple) porte les 3 hooks
d'enforcement de ce dépôt : `SessionStart` (injecte `00-DIGEST.md`), `UserPromptSubmit`
(rappel périodique via `inject_digest.sh`) et `PreToolUse` sur `Bash`
(`guard_forbidden.sh`, bloque `--no-verify` et le force-push sur `main`). Copier
`settings.example.json` par-dessus `settings.json` supprimerait ces trois hooks sans
avertissement. Voir la mise en garde portée dans `coordination/README.md`.

## Active

| Work ID | Branche | État |
|---|---|---|
| OPS-OVERLAY-INSTALL | `claude/ops/install-coordination-overlay` | PR #564 ouverte ; revue aveugle #1 = REJECT (8 majeures, 4 mineures) → corrigée par `17d653c` ; revue aveugle #2 = REJECT (le correctif #1 avait lui-même introduit des défauts) → corrections dans ce commit |
| LIVE-ISSUE-RECONCILIATION | read-only | triage live en cours ; 3 candidats déjà livrés (PR #567, issue #568, PR #571) |

## Merged since last sync

Aucune.

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
