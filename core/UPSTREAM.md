# OPSYS-CORE — provenance amont

OPSYS-CORE est **OpenClaw**, épinglé à une release, plus :
- la configuration générée par OPSYS (`opsys openclaw configurer`) ;
- les capacités MCP des départements ;
- les éventuels patchs de `core/patches/`.

Décision : [ADR-0007](../docs/decisions/ADR-0007-core-openclaw.md).

| Champ | Valeur |
|---|---|
| Projet | [openclaw/openclaw](https://github.com/openclaw/openclaw) |
| Licence | MIT (fichier `LICENSE` amont, vérifié le 2026-09-28) |
| Release épinglée | `v2026.9.6` |
| Commit | `ce5bbdc244ee937246cc1700d1b224d020c3b599` |
| Image officielle | `ghcr.io/openclaw/openclaw:2026.9.6@sha256:0a5ff5e682e62afa19149df126aa50063bf65ef885b5c94713ce32dc0eb12e15` |
| Apps mobiles | `apps/ios`, `apps/android` (officielles, App Store et Google Play) : voir `docs/architecture/MOBILE.md` |

## Principe : épingler et étendre, ne pas copier

L'amont est un monorepo très actif (plusieurs millions de lignes TypeScript, releases fréquentes).
Le copier dans ce dépôt figerait une dette de fusion ingérable. On passe dans cet ordre :
1. **Interfaces publiques** :
   - `mcp.servers` (un serveur OPSYS par département, en streamable HTTP) ;
   - `agents.entries` ;
   - `models.providers` (compatible OpenAI, via LiteLLM) ;
   - `$include` ;
   - skills `SKILL.md` ;
   - automatisations (`openclaw automations add`) ;
   - bindings de canaux.
2. **Patch versionné** dans `core/patches/NNNN-sujet.patch`, seulement si une interface publique ne
   suffit pas. Il porte sa raison en tête de fichier. Aucun à ce jour. Le premier patch imposera
   une image dérivée (`deploy/Dockerfile.core`, `FROM` l'image épinglée par digest) qui l'applique
   au build. D'ici là, `deploy/docker-compose.yml` consomme l'image officielle telle quelle.

## Surfaces amont utilisées (contrat à revérifier à chaque montée de version)

| Surface | Usage OPSYS | Doc amont |
|---|---|---|
| `$include` (tableau, fusion profonde, chemins sous le dossier de config) | fragments `opsys/{models,agents,mcp}.json` | `docs/gateway/config-secrets-env.md` |
| `agents.entries.<id>.{name,workspace,model}` | un agent par département | `docs/concepts/multi-agent.md` |
| `models.providers.<id>.{baseUrl,apiKey,api:"openai-completions",request.allowPrivateNetwork,models[{id,name}]}` | un fournisseur par département → LiteLLM, clé virtuelle dédiée | `docs/gateway/local-models.md`, `src/config/zod-schema.core.ts` |
| `mcp.servers.opsys_mN.{url,transport:"streamable-http",headers}` | un serveur par département, `url` = `http://opsys:8765/mcp/<id>` : le département appelant est fixé par l'URL, jamais par le modèle | `docs/tools/mcp.md`, `src/config/zod-schema.mcp-server.ts` |
| `agents.entries.<id>.tools.deny` (globs `opsys_mN__*`) | chaque agent refuse les outils MCP des 9 autres départements (noms d'outils MCP `<serveur>__<outil>`) | `docs/tools/mcp.md`, `docs/concepts/multi-agent.md` |
| `agents.defaults.contextPruning.{mode:"cache-ttl",ttl}` | élagage des anciens résultats d'outils après inactivité (économie de tokens) | `docs/reference/prompt-caching.md` |
| Substitution `${VAR}` | clés `OPSYS_CLE_Mx`, `OPSYS_MCP_JETON` | `docs/gateway/config-secrets-env.md` |
| `openclaw automations add --cron --tz --session isolated --agent --message` | planifications des départements | `docs/cli/cron.md` |
| Espace de travail : `SOUL.md`, `AGENTS.md`, `skills/` | identité, règles, procédures | `docs/concepts/agent-workspace.md` |

## Mettre à jour l'amont

1. Lire les notes de release : configuration, MCP, agents, mémoire, apps.
2. Mettre à jour le tag, le commit et le digest ici et dans `deploy/docker-compose.yml`.
3. Revérifier le tableau ci-dessus, en lisant le schéma de configuration.
4. Déployer sur un VPS de préproduction et exécuter la recette de `docs/ops/EXPLOITATION.md`.

## Hermes Agent (runtime alternatif, MIT)

[NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) (v2026.9.24 évaluée)
reste utilisable :
- le serveur MCP OPSYS fonctionne en stdio ;
- `src/opsys/hermes_plugin.py` et `src/opsys/profils.py` sont testés.
C'est aussi une source d'ingrédients : compacteur de contexte, patrons de plugins.
