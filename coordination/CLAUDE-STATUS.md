# Status Claude Code

Updated UTC : `2026-08-27T04:41Z`

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
`maxTurns: 240`. Précision mesurée, corrigée en revue : **3 des 4** portent `tools`
incluant Write/Edit — `opsys-issue-triage` déclare `tools: Read, Grep, Glob, Bash` et
place Write/Edit/NotebookEdit dans `disallowedTools`, cohérent avec son
`permissionMode: plan`. Les 3 autres portaient aussi `permissionMode: auto` jusqu'à ce
commit ; corrigé en `default` — voir « Écarts volontaires » ci-dessous. Ne pas dégrader en `.example` — mais ne pas non plus
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

Ce fichier **n'est pas une copie octet-exacte** du `tools/check_coordination.py` du pack
`OPSYS-AI-CLAUDE-ISSUES-OPERATIONS-v1.2`. C'est une propriété stable, vérifiable sans citer
ni commit, ni révision, ni décompte : `diff -q "$OPSYS_PACK/tools/check_coordination.py"
tools/check_coordination.py` signale que les fichiers diffèrent, et `diff -u` entre les deux
donne le détail exact.

**Aucun décompte d'écarts, de fonctions, de hunks ou de lignes n'est figé ci-dessous, et
c'est délibéré.** Un décompte est une affirmation de plus à maintenir, invalidée par la
prochaine édition de ce même fichier sans qu'aucune opération Git n'y soit pour rien. Une
version antérieure de cette section annonçait « deux écarts mesurés, localisés à deux
fonctions » ; le commit qui a ajouté la validation de chemin d'argv (écart
« `_chemin_valide()` » ci-dessous) a rendu ce décompte faux sans le mettre à jour — la faute
même que cette section a pour rôle de ne pas commettre. La formulation qui remplace un
décompte est celle-ci : **la commande `diff -u` fait autorité sur le diff réel ; cette
section n'en énumère que la signification.** Une version antérieure affirmait aussi que ce
fichier différait du pack « depuis le premier commit de cette branche » et que
`coordination/README.md` « affirmait cette exactitude, corrigé dès ce premier commit » :
mesuré, ce fichier n'existait pas dans ce commit-là, et le `README.md` de ce commit ne
mentionnait pas ce validateur. Cette phrase est retirée plutôt que recorrigée — une
affirmation ancrée sur un rang de commit se réfute par un `git ls-tree` ordinaire, alors que
la propriété « diffère du pack » survit à un rebase, un squash, un amend et à toute avance de
`main`.

Écarts, par ordre d'apparition dans le fichier :

### `est_ligne_separatrice()` / `_est_cellule_separatrice()` — une seule notion de « ligne de séparation »

- **Constat** : ces deux fonctions sont absentes du pack. Elles acceptent les formes
  Markdown standard `|---|---|`, `| --- | --- |`, `|:---|---:|`, et la documentation
  l'annonce. Mais `parse_rows()` ne sautait que les lignes commençant **littéralement** par
  `|---` — deux notions de séparateur dans le même fichier, dont une seule était documentée.
  Conséquence mesurée : une table écrite avec un séparateur espacé ou aligné voyait son
  en-tête confirmé (ce contrôle-là utilisait déjà le détecteur), puis sa propre ligne de
  séparation recomptée en ligne de données. Fixture ad hoc (hors dépôt) :
  `| --- | --- | ... |` → `OWNER:---:---` + `STATUS:---:---`, exit 1 ; `|:---|:---:|...|` →
  `OWNER::---::---:` + `STATUS::---::---:`, exit 1. Une table Markdown parfaitement
  légitime, rejetée avec un diagnostic trompeur.
- **Correctif** : le filtre de `parse_rows()` appelle `est_ligne_separatrice()` au lieu de
  tester le préfixe. Un seul détecteur décide désormais, pour le filtre comme pour
  le contrôle d'en-tête.
- **Mode de défaillance nommé avant d'être écrit** : élargir ce qui est sauté peut faire
  disparaître **en silence** une vraie ligne de données. Le sous-ensemble nouvellement sauté
  est exactement celui des lignes dont *toutes* les cellules sont `---`/`:---`/`---:`/`:---:` ;
  aucune ne porte de Work ID, donc aucune ne peut être une entrée de coordination réelle.
  Mesuré des deux côtés : les lignes de données plausibles (cellules vides, `-`, `--`, une
  seule cellule non conforme, l'en-tête lui-même) sont toutes refusées par
  `est_ligne_separatrice()` ; et sur l'intégralité des fichiers `.md` du dépôt et du pack
  réunis, les seules lignes séparatrices à 7 cellules sont les séparateurs des deux vraies tables
  (`coordination/WORK-OWNERSHIP.md` et le gabarit du pack), que l'ancien filtre sautait déjà.
- **Sens inverse mesuré aussi** : sur ce même balayage, aucune ligne ne commence par
  `|---` sans être par ailleurs une ligne de séparation valide. Remplacer le préfixe par le
  détecteur ne retire donc le saut à aucune ligne réelle : le correctif élargit sans retirer.
  C'est cette mesure, et non un jugement, qui a fait préférer le remplacement à l'autre
  correctif possible (restreindre la documentation à la seule forme `|---|`) : restreindre la
  documentation aurait laissé le validateur rejeter des tables Markdown valides.

### `HEADER_MISSING` — absence d'en-tête non détectée, puis un faux positif corrigé

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
- **Défaut résiduel de ce premier correctif, corrigé depuis** : il mettait
  `header_found = True` dès qu'une ligne était *égale* à l'en-tête, sans regarder ce qui la
  suit — y compris citée seule, en bloc de code ou en prose, pour documenter le format sans
  qu'aucune vraie table ne suive. Une fixture ad hoc (hors dépôt, cf. preuve du commit
  correspondant) le démontre : un document qui ne fait que citer la ligne d'en-tête dans un bloc de code
  passait à tort `COORDINATION_OK rows=0 active=0`. Correctif : `parse_rows()` ignore
  désormais tout contenu entre deux clôtures de bloc de code (les lignes commençant par trois
  apostrophes inverses ou par `~~~`) — jamais compté comme en-tête, séparateur ou ligne de
  données — et n'accepte `header_found = True` que si la ligne d'en-tête est **immédiatement
  suivie** d'une vraie ligne de séparation Markdown (ex. `|---|---|`, avec ou sans espaces ou
  `:` d'alignement). Une table vide **avec** en-tête et séparateur reste valide ; une simple
  citation de l'en-tête, en bloc de code ou non, ne l'est plus.
- **Comportement mesuré à HEAD** (et non « après tel commit » : ces valeurs sont
  re-mesurables à tout instant, la formulation ne dépend d'aucun rang de commit) —
  gabarit du pack `repo-overlay/coordination/WORK-OWNERSHIP.md` →
  `COORDINATION_OK rows=0 active=0`, exit 0 ; `coordination/WORK-OWNERSHIP.md` de ce dépôt →
  `COORDINATION_OK rows=9 active=2` (les deux lignes `REVIEW`/`ACTIVE`, cf. « Active »
  ci-dessus) ; `coordination/DAILY-SYNC.md`, `coordination/24H-UPDATE-TEMPLATE.md` et
  `coordination/README.md` → `HEADER_MISSING`, exit 1 ; fixture « en-tête cité dans un bloc
  de code » → `HEADER_MISSING`, exit 1, là où la version du pack rend
  `COORDINATION_OK rows=0 active=0`, exit 0.
  La non-régression sur le gabarit du pack est la plus critique de la liste : la casser
  interdirait toute installation neuve, `tools/daily_start.py` du pack validant ce gabarit
  quand `coordination/WORK-OWNERSHIP.md` n'existe pas encore.
- **Cas du fichier inexistant — comportement réel, re-mesuré** : une version antérieure de
  cette section le donnait comme une « limite non résolue », avec `FileNotFoundError` non
  interceptée, traceback et exit 1, en ajoutant que « ce correctif ne change pas ce
  comportement ». C'était vrai jusqu'à ce que la validation de chemin d'argv soit ajoutée
  (écart `_chemin_valide()` ci-dessous), et faux depuis, sans que la phrase soit reprise.
  Comportement mesuré à ce jour :
  `python3 -B tools/check_coordination.py <chemin-inexistant>` →
  `CHEMIN_INVALIDE:chemin non resolvable : [Errno 2] No such file or directory: '<chemin>'`,
  **exit 2**, aucun traceback. Le traceback n'existe plus que dans la version du pack.
- **Diff contre le pack** : `valid_scope()` est la seule fonction du pack reprise inchangée.
  `parse_rows()`, `overlaps()`, `validate()` et `main()` diffèrent tous, et le fichier ajoute
  des définitions absentes du pack (`est_ligne_separatrice`, `_est_cellule_separatrice`,
  la classe `CheminInvalide`, `_chemin_valide`). `main()` en particulier **ne fait pas** partie
  des fonctions identiques au pack : une version antérieure de cette phrase l'y rangeait, et
  le commit qui a fait passer `main()` par `_chemin_valide()` ne l'a pas retirée de la liste.
  Vérifiable fonction par fonction sans décompte, contre le pack installé, plutôt que sur une
  liste recopiée ici — c'est le diff qui fait foi.

### `overlaps()` — casse non normalisée, incohérente avec `MODULE_CODE_DURING_CORE`

- **Constat** : dans `validate()`, le contrôle
  `MODULE_CODE_DURING_CORE` normalise déjà la casse du scope avant comparaison. `overlaps()`,
  lui, comparait les chemins de scope tels quels, sans normaliser la casse. Conséquence :
  deux lignes actives portant les scopes `Coordination` et `coordination` ne déclenchaient
  aucun `PATH_COLLISION`, alors que `MODULE_CODE_DURING_CORE` les aurait traitées comme
  identiques quelques lignes plus loin dans la même fonction `validate()` — incohérence
  interne héritée du pack amont, pas introduite par ce dépôt. Fixture ad hoc (hors dépôt) :
  deux lignes actives, branches distinctes, scopes `Coordination` et `coordination` → la
  version du pack rend `COORDINATION_OK rows=2 active=2`, exit 0 (collision manquée) ; la
  version de ce dépôt rend `PATH_COLLISION:ISS-A:ISS-B:Coordination:coordination`, exit 1.
- **Correctif** : `overlaps()` normalise la casse **et le séparateur** des deux chemins
  avant comparaison, par le même principe que `MODULE_CODE_DURING_CORE`. La normalisation de
  casse seule ne suffisait pas : une revue a mesuré que `coordination\sub` et
  `coordination/sub`, deux lignes actives, ne déclenchaient toujours aucune collision, alors
  que `MODULE_CODE_DURING_CORE` traitait bien ces deux écritures comme le même chemin.
  Mesuré à HEAD sur la fixture correspondante :
  `PATH_COLLISION:ISS-A:ISS-B:coordination\sub:coordination/sub`, exit 1, là où la version
  du pack rend `COORDINATION_OK rows=2 active=2`, exit 0. Les deux contrôles de scope partagent maintenant la
  même notion de « même chemin » — casse et séparateur.

### `_chemin_valide()` — validation des chemins d'argv, et le code de sortie 2

- **Motif** : SonarCloud remonte le motif `pythonsecurity:S8707` sur ce module — un chemin
  venu d'`argv` atteignait le système de fichiers sans validation préalable, à la lecture
  (`Path(args.ownership)`) comme à l'écriture (`Path(args.json_output).write_text(...)`).
  Les deux lignes viennent du pack amont, mais le fichier étant neuf dans ce dépôt, la
  totalité de son contenu compte comme *new code*. **Le verdict SonarCloud lui-même n'est
  pas re-mesurable depuis ce dépôt** (il vient du service, pas d'un outil local) : il est
  cité comme le motif du changement, pas comme une mesure de cette section.
- **Portée volontairement NON confinée à l'arborescence du dépôt.** C'est l'écart à
  comprendre avant tout le reste : `tools/daily_start.py` du pack appelle ce même validateur
  sur **son propre gabarit**, qui vit hors du dépôt. Mesuré dans le source du pack — deux
  invocations, l'une sur `<repo>/coordination/WORK-OWNERSHIP.md`, l'autre sur
  `<pack>/repo-overlay/coordination/WORK-OWNERSHIP.md` quand la première n'existe pas encore.
  Confiner la validation à l'arborescence du dépôt **casserait l'installation neuve** : le
  défaut qu'on cherche à éviter, en pire. La validation porte donc sur la **forme** et la
  **nature** de la cible, jamais sur son emplacement.
- **Ce qui est refusé, mesuré** : octet nul dans le chemin ; chemin non résolvable ;
  cible de lecture qui n'est pas un fichier régulier (un répertoire, notamment) ; en
  écriture, répertoire parent inexistant, ou cible existante qui n'est pas un fichier
  régulier. Les `..` et les liens symboliques sont aplatis par `resolve()` **avant** tout
  accès, de sorte qu'un lien menant hors d'un périmètre attendu devient visible dans le
  chemin résolu au lieu d'être suivi à l'aveugle.
- **Nouveau code de sortie, et nouveau préfixe de message** : un chemin refusé rend
  `CHEMIN_INVALIDE:<raison>` sur la sortie standard et **exit 2**, distinct de l'exit 1 des
  erreurs de contenu (`HEADER_MISSING`, `PATH_COLLISION`, `UNTERMINATED_FENCE`, …) et de
  l'exit 0 de `COORDINATION_OK`. Trois codes, trois significations : 0 = table conforme,
  1 = table lue mais non conforme, 2 = table jamais lue, l'argument n'a pas passé la
  validation. Documenté aussi dans `coordination/README.md`, à côté de `COORDINATION_OK` —
  un appelant qui teste `!= 0` ne voit pas la différence, un appelant qui teste `== 1` la
  voit.
- **Conséquence sur `main()`** : c'est ce changement qui fait que `main()` diffère du pack,
  et donc qui a invalidé la phrase « `main()` reste identique » corrigée plus haut. L'écart
  est consigné ici pour que la prochaine édition de `main()` trouve une entrée à mettre à
  jour, au lieu d'une liste qui prétend le contraire.

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
| OPS-OVERLAY-INSTALL | `claude/ops/install-coordination-overlay` | PR #564 ouverte ; cinq tours de revue aveugle scellée = REJECT, dont quatre sur la **même classe de défaut** : une affirmation d'un fichier livré portant sur du code livré, non re-mesurée contre HEAD dans le commit qui modifie ce code. Corrigée site par site à chaque tour, elle réapparaissait au suivant — le tour 5 l'a réintroduite via le commit de validation de chemin d'argv, qui a modifié `tools/check_coordination.py` sans reprendre le registre décrivant ce fichier. Ce tour applique le critère à la classe entière : balayage de toutes les affirmations vérifiables portant sur ce fichier, re-mesure de chacune contre HEAD, et retrait des décomptes figés — un décompte étant lui-même une affirmation à maintenir |
| LIVE-ISSUE-RECONCILIATION | read-only | triage live en cours ; candidats re-mesurés à l'horodatage de ce fichier — PR #567 (**mergée** le 2026-08-27T04:11:06Z, `gh pr view 567` → `MERGED`) et son issue #565 (**fermée**) ; issue #568 (`OPEN`, bloquée en investigation) ; PR #571 (**mergée**, `gh pr view 571` → `MERGED`) ; issue #576 (**ouverte** le 2026-08-27T04:29:11Z, AUD-CI-002) |

Deux lignes actives ici, cohérent avec `WORK-OWNERSHIP.md` et avec
`python3 -B tools/check_coordination.py coordination/WORK-OWNERSHIP.md` (`active=2` : les
statuts `REVIEW`/`ACTIVE` de `OPS-OVERLAY-INSTALL` et `LIVE-ISSUE-RECONCILIATION`).
`AUD-CORE-006`, `AUD-CI-003` et `AUD-CI-004` ne figurent pas dans cette table : leurs PR
(#571 et #567) sont mergées, leur statut dans `WORK-OWNERSHIP.md` est `MERGED`, donc hors de
l'ensemble `ACTIVE` du validateur — voir « Merged since last sync » ci-dessous. Cette table
ne liste que les missions dont le statut appartient à cet ensemble ; c'est ce qui la rend
recalculable au lieu d'être tenue à la main. `DAILY-SYNC.md` renvoie ici pour le détail
d'exécution de ces deux missions.

## Merged since last sync

Ne pas figer de liste de SHA de merge ici : un rebase de cette branche ne change pas quels
merges ont réellement eu lieu sur `origin/main`, mais il change les SHA locaux disponibles
pour les nommer — une valeur figée à la place d'une commande devient donc fausse ou
incomplète sans qu'aucun fait réel n'ait changé. Ce que l'on peut recenser de façon stable :

- Missions suivies dans `WORK-OWNERSHIP.md` passées à `MERGED` depuis la mise au point
  précédente, au moment de cette réconciliation :
  - `AUD-CORE-006` (PR #571 — `gh pr view 571` → `MERGED`, et le commit de merge de #571 est
    un ancêtre de cette branche, visible dans `git log --oneline HEAD` en cherchant `#571`).
  - `AUD-CI-003` et `AUD-CI-004` (PR #567 — `gh pr view 567` → `MERGED`, `mergedAt`
    2026-08-27T04:11:06Z, commit de merge `b9ced941e` ; `git merge-base --is-ancestor
    b9ced941e HEAD` réussit, donc ce merge est un ancêtre de cette branche). Issue #565
    fermée à 2026-08-27T04:12:07Z. Ce SHA-ci est celui d'un merge de `origin/main`, pas un
    commit de cette branche : il survit au rebase, au squash et à l'amend de cette
    branche-ci, contrairement aux SHA que les tours précédents citaient.
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
- `AUD-CI-003` / `AUD-CI-004` — **ne sont plus bloquées** : leur PR #567 est mergée, cf.
  « Merged since last sync » ci-dessus. Elles figuraient ici comme « gelées par l'issue
  #569 » ; cette ligne était périmée et l'est encore le jour où elle est corrigée, faute de
  resynchronisation automatique.
- État mesuré de l'issue **#569**, qui portait ce gel : elle est **toujours `OPEN`**
  (`gh issue view 569` → `OPEN`, `closed_at` nul, `state_reason` nul). Le gel qu'elle
  décrivait, en revanche, ne se constate plus : la PR #567 touchait
  `.github/workflows/ci.yml` et `core/tests/bootstrap/test_ci_gating_contract.py` — donc le
  périmètre scellé — et a franchi `proof-sealed` pour être mergée. Un commentaire du
  propriétaire du dépôt sur #569 documente la cause réelle : ce n'était pas le routeur
  LiteLLM, qui servait déjà les trois routes, mais la **table d'alias du pont de modèles**,
  restée sur d'anciens noms ; sept alias ajoutés, les trois routes répondent. Le
  commentaire signale aussi un défaut d'infrastructure distinct et non résolu
  (`FORGE_MODEL_BRIDGE_MAX_TOKENS` à 4096, trop court pour les prompts de diff volumineux).
  **La distinction compte et n'est pas cosmétique : issue ouverte ≠ blocage constaté.**
  Écrire « #569 est close » serait faux ; écrire « le gel dure » le serait aussi. Les deux
  faits sont consignés séparément parce qu'ils sont séparément vérifiables.
- `AUD-CORE-005` — issue #568 : fragment orphelin `.opsys/tools/github-control`,
  correction TDD impossible sans fabriquer des données absentes ; décision Nathan
  demandée (restaurer / retirer / requalifier) avant tout code.

## Next

`AUD-CI-002` (épinglage SHA des actions) porte désormais l'issue **#576**, ouverte le
2026-08-27T04:29:11Z (`gh issue view 576` → `OPEN`) : `actions/setup-python` n'est pas
épinglé par SHA dans `ci.yml`, et aucun oracle ne couvre ce workflow. Les deux conditions
d'attente qui la retenaient sont levées et mesurées : `AUD-CI-003/004` sont mergées (même
fichier, donc plus de risque de parallélisme), et le gel du périmètre scellé ne se constate
plus (cf. « Blocked » ci-dessus). Elle reste `QUEUED` faute d'activation, pas faute de
blocage. Prochaine action utile : activer #576, et suivre la décision Nathan sur `#568`.
