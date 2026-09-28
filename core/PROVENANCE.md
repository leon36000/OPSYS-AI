# OPSYS-CORE — provenance du fork

OPSYS-CORE est un **fork dur** d'OpenClaw ([ADR-0008](../docs/decisions/ADR-0008-fork-openclaw-opsys-core.md)).
Il n'est plus synchronisé avec l'amont. Nous le modifions librement et publions nos propres versions.

| Champ | Valeur |
|---|---|
| Projet d'origine | [openclaw/openclaw](https://github.com/openclaw/openclaw) |
| Licence d'origine | MIT, © 2026 OpenClaw Foundation (`LICENSE` conservé tel quel, voir aussi `NOTICE`) |
| Release importée | `v2026.9.6`, tag annoté `ce5bbdc244ee937246cc1700d1b224d020c3b599` |
| Commit importé | `eb377ac59e6c9fd6c7705028034812becf00271b` (2026-09-22) |
| Date d'import | 2026-09-28 |
| Historique amont | non importé (instantané) |

## Transformation appliquée à l'import

Elle est reproductible depuis le tag. Le script est
[`outils/fork/elaguer_core.py`](../outils/fork/elaguer_core.py), et ses raisons sont détaillées dans
[R11](../docs/research/R11-fork-openclaw.md).

1. **Retiré au premier niveau** :
   - `.github/`, `.agents/`, `.claude/`, `.vscode/` ;
   - `apps/` : les apps natives. L'app OPSYS est en Expo, voir R12 ;
   - `crates/`, `CHANGELOG/`, `CHANGELOG.md`, `qa/`, `examples/` ;
   - `appcast.xml`, `fly.toml`, `render.yaml` ;
   - `git-hooks/`. Sans lui, le script `prepare` de pnpm ne reconfigure pas les hooks git du dépôt
     OPSYS-AI.
2. **Extensions** : 42 conservées sur 162, soit les 40 de R11 §3.2 et deux d'appui (`test-support`,
   `image-generation-core`).
3. **`docs/`** : élagué à trois sous-ensembles et un fichier individuel près (T0.6), lus par du
   code non-test ou par des tests de comportement produit que l'élagage des extensions ne suffit
   pas à neutraliser :
   - `docs/reference/templates/` (au complet, gabarits d'espace de travail des agents) : lu par
     `src/agents/workspace-templates.ts` et `src/agents/agent-roles.ts` (`roles/<role>/CLAW.md`,
     `roles/presets/team.json`) — sans lui, tout agent embarqué échoue à l'amorçage
     (« Bundled agent role is missing »).
   - `docs/.generated/` (les 4 fichiers suivis en amont seulement : `README.md`,
     `config-baseline.{counts.json,sha256}`, `sqlite-session-transcript-schema-baseline.sha256`) :
     ligne de base de configuration, lue par `src/config/doc-baseline.ts`.
   - `docs/assets/openclaw-hero-dark.png` : seule image de `docs/assets/` que lit la construction
     de l'UI (`ui/config/control-ui-social-card.ts`, plugin vite de `ui/vite.config.ts`) ; sans
     elle, `pnpm build` échoue sur `ui:build`.

   Même traitement pour un fichier individuel hors de ces trois sous-ensembles (T0.6, liste
   `DOCS_FICHIERS_GARDES` du script d'élagage, sur le modèle d'`APPS_FICHIERS_GARDES`) :
   - `docs/install/docker.md` : deux tests de `src/dockerfile.test.ts` comparent son contenu
     documenté au comportement réel — la commande de santé Compose du script de configuration et
     les arguments de provenance (`GIT_COMMIT`/`OPENCLAW_BUILD_TIMESTAMP`) du Dockerfile — pour
     détecter une dérive doc/produit. Ce sont des tests de comportement produit, pas de CI amont ;
     contrairement au test de `src/audit/message-delivery-progress-store.test.ts` qui lisait
     `.github/actions/git-owner/test-prerequisites.json` (retiré, pas restauré : ce test exécutait
     un `git fetch origin <commit historique d'OpenClaw>` puis un `git worktree add` pour lancer
     l'ancien code de ce commit — un mécanisme qui suppose une continuité d'historique avec l'amont
     qu'un fork dur sans dépendance aux mises à jour amont (ADR-0008) n'a pas : le commit épinglé
     n'existe ni dans ce dépôt ni sur son `origin` réel. Restaurer seul le fichier JSON n'aurait pas
     suffi à faire passer ce test ; il est supprimé plutôt qu'affaibli).

   Le reste de `docs/` (documentation produit amont) reste élagué : OPSYS écrit sa propre
   documentation dans `docs/` du dépôt OPSYS-AI. Les tests qui vérifiaient des pages non
   restaurées (`src/docs/*.test.ts`, huit fichiers) sont retirés, voir le commit qui introduit ce
   paragraphe.

   Même traitement pour deux fichiers partagés d'`apps/`, que la construction lit (T0.6, CI) :
   - `apps/shared/OpenClawKit/Sources/OpenClawKit/Resources/tool-display.json` : importé par
     `ui/src/lib/chat/tool-display.ts` ;
   - `apps/shared/mermaid/.gitignore` : dossier de sortie de `packages/mermaid-renderer`.

   Ils sont listés dans `APPS_FICHIERS_GARDES` du script d'élagage.
4. **Patch pnpm retiré** : `matrix-js-sdk`, avec l'extension Matrix.
5. **`pnpm-lock.yaml` régénéré sans exécuter aucun script de paquet** :
   `pnpm install --lockfile-only --ignore-scripts --ignore-pnpmfile` (pnpm 12.4.0). Résultat : 63
   projets de workspace, 1 687 entrées, contrôles de chaîne d'approvisionnement de pnpm passés.
6. **Fichiers suivis** : exactement ceux que la release suit, moins l'élagage, plus les 27 fichiers
   de `docs/` restaurés au point 3 (26 avant `docs/install/docker.md`, T0.6). Au total, environ
   36 213 fichiers sur 48 575 à l'import ; le chiffre se déplace légèrement à chaque vague
   d'élagage ultérieure de `scripts/`/`test/` et à chaque fichier restauré au cas par cas (T0.6,
   T0.7).

## Suite de la transformation

Elle se fait dans des commits séparés : renommage de la marque visible, greffes OPSYS, puis élagage
de `scripts/` et de `test/` guidé par la CI. Voir `docs/programme/PLAN.md` (T0.6, T0.7).

## Sécurité

Il n'y a plus de mises à jour automatiques. Une veille mensuelle des avis de sécurité d'OpenClaw
décide, correctif par correctif, s'il faut le reporter à la main. Chaque report est tracé dans ce
fichier.

## Surfaces consommées par la couche Python (transitoire)

`src/opsys/openclaw.py` génère encore la configuration du core de l'extérieur. Ce contrat vient de
l'ancien `core/UPSTREAM.md` (ADR-0007) et reste valable tant que les greffes natives ne l'ont pas
remplacé (ADR-0008, conséquences). Toute modification de ces surfaces dans `core/` doit mettre à
jour `src/opsys/openclaw.py` et ses tests dans le même commit.

| Surface | Usage OPSYS | Source dans le fork |
|---|---|---|
| `$include` (tableau, fusion profonde, chemins sous le dossier de config) | fragments `opsys/{models,agents,mcp}.json` | `src/config/includes.ts` |
| `agents.entries.<id>.{name,workspace,model}` | un agent par département | `src/config/zod-schema.agents.ts` |
| `models.providers.<id>.{baseUrl,apiKey,api:"openai-completions",request.allowPrivateNetwork,models[{id,name}]}` | un fournisseur par département vers LiteLLM, clé virtuelle dédiée | `src/config/zod-schema.core.ts` |
| `mcp.servers.opsys_mN.{url,transport:"streamable-http",headers}` | un serveur par département, `url` = `http://opsys:8765/mcp/<id>` : l'appelant est fixé par l'URL, jamais par le modèle | `src/config/zod-schema.mcp-server.ts` |
| `agents.entries.<id>.tools.deny` (globs `opsys_mN__*`) | chaque agent refuse les outils MCP des 9 autres départements | `src/config/zod-schema.agents.ts` |
| `agents.defaults.contextPruning.{mode:"cache-ttl",ttl}` | élagage des anciens résultats d'outils après inactivité | `src/config/zod-schema.agent-defaults-base.ts` |
| Substitution `${VAR}` | clés `OPSYS_CLE_Mx`, `OPSYS_MCP_JETON` | `src/config/env-substitution.ts` |
| `automations add --cron --tz --session isolated --agent --message` | planifications des départements | `src/cli/cron-cli.ts` |
| Espace de travail : `SOUL.md`, `AGENTS.md`, `skills/` | identité, règles, procédures | `src/agents/` (amorçage de l'espace de travail) |
