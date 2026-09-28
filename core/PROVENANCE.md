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
   - `crates/`, `docs/`, `CHANGELOG/`, `CHANGELOG.md`, `qa/`, `examples/` ;
   - `appcast.xml`, `fly.toml`, `render.yaml` ;
   - `git-hooks/`. Sans lui, le script `prepare` de pnpm ne reconfigure pas les hooks git du dépôt
     OPSYS-AI.
2. **Extensions** : 42 conservées sur 162, soit les 40 de R11 §3.2 et deux d'appui (`test-support`,
   `image-generation-core`).
3. **Patch pnpm retiré** : `matrix-js-sdk`, avec l'extension Matrix.
4. **`pnpm-lock.yaml` régénéré sans exécuter aucun script de paquet** :
   `pnpm install --lockfile-only --ignore-scripts --ignore-pnpmfile` (pnpm 12.4.0). Résultat : 63
   projets de workspace, 1 687 entrées, contrôles de chaîne d'approvisionnement de pnpm passés.
5. **Fichiers suivis** : exactement ceux que la release suit, moins l'élagage. Au total, 36 213
   fichiers sur 48 575.

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
