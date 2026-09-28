# R11 — Fork dur d'OpenClaw → OPSYS-CORE

Décision actée (propriétaire, 28 septembre 2026) : OpenClaw **devient** OPSYS-AI. On importe son code
source, on l'élague, on le renomme, on le transforme, et OPSYS publie ses propres versions sans
dépendre des mises à jour amont. Ce document **remplace** l'approche « OpenClaw épinglé » décrite dans
`docs/architecture/ARCHITECTURE.md` et `core/UPSTREAM.md` (ADR-0007) et dans R1 (`docs/research/R1-core-openclaw.md`,
qui recommandait une dépendance vendorisée épinglée plutôt qu'un fork profond) : ces deux fichiers devront
être remplacés par une nouvelle décision (ADR-0008 suggéré) quand le travail de fork commencera. Je ne les
modifie pas ici.

## 0. Sources et méthode

- Clone superficiel lisible : `scratchpad/clones/openclaw`, `main` à `2d39f2f7` (2026-09-27), **737 Mo**
  hors `.git` (`du -sm`, confirmé exactement). **Ce n'est pas le tag `v2026.9.6`** (commit `ce5bbdc2…`
  selon `core/UPSTREAM.md`) : à re-fetcher et re-vérifier avant l'import réel (§6.1). Les chiffres ci-dessous
  décrivent l'état `main` du 27 septembre, à quelques commits près du tag.
- Aucun code du dépôt OpenClaw exécuté ; aucun paquet npm installé. Analyse = lecture de fichiers,
  `du`/`git grep`/`find`, et deux scripts Python maison (lecture seule, `json.loads` + regex sur les
  `.ts`), conservés dans `scratchpad/analysis/` : `classify_extensions.py` (manifestes des 171 extensions)
  et `reachability.py` (graphe d'imports statique depuis les points d'entrée).
- Chaque chiffre cité est reproductible par la commande indiquée entre parenthèses.

## 1. Carte du monorepo

| Dossier | Ko | Fichiers utiles | Langage | Rôle |
|---|---:|---|---|---|
| `src/` | 285 308 | ~24 700 `.ts` (11 716 hors tests) | TypeScript | Gateway, CLI, boucle agents, MCP, mémoire-cadre, cron, canaux natifs |
| `ui/` | 144 588 | 4 642 fichiers, dont `ui/src/i18n/.i18n/*.tm.jsonl` = 25 langues × ~4,3 Mo | TS/Lit (web components) | Control UI (dashboard) |
| `extensions/` | 130 076 | 171 dossiers (162 réels, 9 fichiers isolés) | TypeScript | Canaux, fournisseurs de modèles, mémoire, outils — paquets pnpm indépendants |
| `apps/` | 70 132 | ios, android, macos, linux, shared, swabble, macos-mlx-tts | Swift/Kotlin/Tauri | Apps natives (compagnons `role: node`) — **hors workspace pnpm** |
| `test/` | 36 908 | ~200+ fichiers `*.e2e/integration/live.test.ts` à la racine + `fixtures/`, `helpers/` | TypeScript (Vitest) | Suite de tests du monorepo |
| `docs/` | 28 416 | 29 sous-dossiers | Markdown | Documentation produit amont |
| `scripts/` | 21 184 | ~260 scripts | `.mts`/`.mjs`/`.sh`/`.ps1` | Release engineering (Android/iOS/macOS, npm, ClawHub, CI) |
| `packages/` | 11 596 | 23 paquets `@openclaw/*` | TypeScript | Librairies partagées (ai, agent-core, llm-core, gateway-protocol…) |
| `CHANGELOG/` + `CHANGELOG.md` | 7 596 | 1 fichier/version depuis 2026.1.10 | Markdown | Historique amont |
| `qa/` | 3 772 | scénarios, `maturity-scores.yaml` | Markdown/YAML | QA interne amont |
| `.github/` | 6 144 | 60+ workflows, `actions/`, `codeql/` | YAML | CI amont (Android/iOS/macOS release, npm, Discord/Slack bots « mantis ») |
| `crates/` | 688 | `openclaw-gateway-client`, `openclaw-node-host` | Rust | Runtime headless pour compagnons « node » |
| `skills/` | ~1 024 | 50 skills | Markdown | Skills intégrées (productivité perso, dev) |
| `custodian-skills/` | ~1 024 | 4 skills (add-model-provider, configure-channel, diagnose-gateway, cloud-image-bake) | Markdown | Skills d'auto-administration de la Gateway |
| `config/`, `security/`, `deploy/`, `examples/`, `patches/`, `.agents/`, `.vscode/` | ~4 100 | outillage dev (knip, oxlint, opengrep, fly.toml) | mixte | Non-produit |

**Build.** pnpm workspaces (`pnpm-workspace.yaml` : `packages = [".", "ui", "packages/*", "extensions/*", "examples/*"]` —
**`apps/*` n'y figure pas**, confirmé : ce sont des projets Xcode/Gradle/Tauri autonomes, sans lien avec le
graphe de build Node). Bundler : **tsdown** (`tsdown.config.ts`, 39 Ko, `pnpm build` → `scripts/build-all.mts`).
`pnpm-lock.yaml` unique (592 Ko), 7 `patchedDependencies` (baileys, chrome-devtools-mcp, matrix-js-sdk,
`@novnc/novnc`, vitest, webawesome, `@openclaw/proxyline`), `minimumReleaseAge: 10080` (cooldown npm 7 j).

**Points d'entrée.**
- CLI/daemon : `openclaw.mjs` (bin racine, 24 Ko) → importe `dist/entry.js` (compilé depuis `src/entry.ts`).
  `package.json` : `"bin": {"openclaw": "openclaw.mjs"}`, `"main": "dist/index.js"`.
- Gateway : commande `gateway` du même binaire (`docker-compose.yml` : `node dist/index.js gateway --bind …`),
  ports **18789** (HTTP/WS) et **18790**.
- Service de fond : `openclaw onboard --install-daemon` génère le systemd/launchd/Windows-service au moment
  de l'installation (pas de fichier statique trouvé pour le démon principal dans ce clone ; seul
  `scripts/systemd/openclaw-auth-monitor.{service,timer}` est statique — à vérifier sur VPS réel, cf. §4).
- Docker : `docker-entrypoint.mjs` (adaptateur tini : lance `doctor --fix --non-interactive` puis `execve`
  la vraie commande).

**Node/pnpm.** `engines.node`: `>=24.16.0 <25 || >=26.1.0` ; `packageManager`: `pnpm@12.5.1` (intégrité
sha512 épinglée). L'installateur choisit **Node 24** par défaut sur Linux (`NODE_LINUX_DEFAULT_MAJOR=24`
dans `scripts/install.sh`).

**Tests.** Vitest (`vitest.config.ts` racine délègue à `test/vitest/vitest.config.ts` ; projets multiples :
unit, unit-fast, projects, ui-e2e — noms confirmés par les fichiers `test/vitest-*-config.test.ts`).
18 542 fichiers `*.test.ts`/`*.spec.ts` recensés par R1. `test/` (racine) contient les tests
d'intégration/e2e transverses ; les tests unitaires sont colocalisés dans `src/**/*.test.ts`.

## 2. À garder (vérifié par manifeste + graphe d'imports)

L'analyse d'atteignabilité (`reachability.py`, BFS depuis `src/entry.ts`, `index.ts`, `runtime.ts`,
`library.ts`, résolution des alias `tsconfig.json` `paths` et du motif ESM `./x.js` → `./x.ts`) donne
**10 307 / 11 716 fichiers `src/` atteignables (88 %)** — le cœur est bien connecté, peu de code mort.
Détail par sous-dossier (script conservé dans `scratchpad/analysis/reachability.py`) :

| Sous-système | Fichiers | Atteint | À garder pour |
|---|---:|---:|---|
| `src/gateway/` | 1 750 | 91 % | Gateway HTTP/WS, approbations, canaux, MCP côté serveur |
| `src/agents/` | 2 171 | 92 % | Boucle agents multi-agents (`sessions_spawn`), harnais, outils, sandbox |
| `src/mcp/` + `src/agents/mcp-*` | 12+ | 58 %* | Client/serveur MCP stdio+HTTP+SSE, OAuth |
| `src/cron/` | 254 | 90 % | Automatisations planifiées |
| `src/context-engine/` | 15 | **100 %** | « RAM » / moteur de contexte (troncature, pruning) |
| `src/plugins/` | 768 | 92 % | Registre de plugins (scan manifestes, **pas** d'import statique — §3.1) |
| `src/channels/` | 297 | 81 % | Cadre canal commun (webchat natif y compris) |
| `src/config/`, `src/cli/` | 712, 523 | 96 %, 96 % | Schéma de config, CLI |
| `src/plugin-sdk/` | 521 | 13 %* | Contrat exposé **aux extensions** (`exports."./plugin-sdk/*"` de `package.json`) — atteignable depuis les extensions, pas depuis `entry.ts` ; normal |

\* `mcp` et `plugin-sdk` sont des surfaces consommées par un autre point d'entrée (respectivement le
protocole MCP entrant et les extensions) ; leur faible score ici ne signale pas du code mort.

**Mémoire / RAM.** Extensions `memory-core` (4 660 Ko), `memory-lancedb` (528 Ko, vecteurs LanceDB),
`memory-wiki` (1 388 Ko), `active-memory` (564 Ko) + `src/context-engine/` (100 % atteint). Le
« dreaming » (consolidation périodique) est du code interne à `memory-core`, pas une extension séparée.

**Outils/MCP.** Natif dans `src/mcp/*`, `src/agents/mcp-*` : stdio, Streamable HTTP, SSE, OAuth serveurs
distants. C'est exactement la surface déjà consommée par `src/opsys/serveur_mcp.py` (`mcp.servers.*.transport:
"streamable-http"`) — **aucun changement requis côté OPSYS pour ce point**.

**Fournisseurs de modèles à garder (9 sur 56, classification par manifeste ci-dessous) :** `anthropic`,
`openai` (supporte un `baseUrl` custom — `extensions/openai/base-url.ts::classifyOpenAIBaseUrl` — couvre
« OpenAI-compatible » sans extension dédiée), `google`, `openrouter`, `mistral`, `ollama`, `lmstudio`,
`llama-cpp`, `litellm` (déjà la passerelle d'OPSYS).

**Canaux à garder (8 sur 24) :** `sms` (Twilio), `whatsapp`, `telegram`, `signal`, `msteams`, `slack`,
`googlechat`, `imessage` — plus `imap` (courriel entrant) et `voice-call`+`talk-voice` (voix/appels
Twilio/Telnyx/Plivo). Le webchat n'est **pas** une extension séparée : il est natif dans `src/channels/`
(confirmé — absent de la liste des 171 extensions).

**Control UI.** `ui/` (144 588 Ko) en totalité — base du dashboard OPSYS. Pages : `ui/src/pages/` (24 Mo),
routage : `ui/src/app/` (4 Mo), widgets : `ui/src/components/` (8 Mo). Un skill `control-ui` (dans `skills/`)
laisse déjà un agent construire ses propres widgets — pertinent pour M8.

**Sécurité.** `crabbox` (1 376 Ko, sandbox), `code-mode-quickjs` (184 Ko, exécution JS bac-à-sable
QuickJS-WASM), `policy` (1 072 Ko, contrôles de conformité), `device-pair` (256 Ko, **appairage mobile** —
§7.5), `vault` (120 Ko, secrets HashiCorp). Approbations natives : `src/gateway/operator-approval-*.ts`,
`exec-approval-manager.ts`, `exec-approval-expiry.ts` ; policy par outil : `src/claws/tool-policy-runtime.ts`
(§7.2).

**Installateurs.** `scripts/install.sh`, `scripts/install.ps1`, `Dockerfile`, `docker-compose.yml` — à
garder et adapter (§4), pas à réécrire : logique de détection Node/plateforme mûre et testée
(`test/docker-entrypoint.test.ts`, `src/dockerfile.test.ts`, `install-smoke.yml`).

## 3. À élaguer

### 3.1 Méthode et fait architectural clé

`classify_extensions.py` lit `extensions/*/package.json` (champ `openclaw.channel`/`openclaw.extensions`)
et `extensions/*/openclaw.plugin.json` (`categories`, `description`) — **sans** exécuter de code. Le BFS
d'imports (`reachability.py`) confirme que **0 des 10 307 fichiers `src/` atteints n'importe le dossier
`extensions/`** : les 25 « hits » sur le mot `extensions/` dans le graphe atteint pointent tous vers
`src/agents/sessions/extensions/` (un sous-dossier local sans rapport, le harnais d'outils bash/edit/grep
interne). **Conclusion vérifiée** : les extensions ne sont jamais reliées par un import TypeScript statique ;
elles sont découvertes à l'exécution/au build par un registre qui scanne les manifestes
(`src/plugins/location-bridges.ts`, `plugin-metadata-env.ts`, `registry-refresh.test.ts`) et par l'argument
de build `OPENCLAW_EXTENSIONS`/`OPENCLAW_BUNDLED_PLUGIN_DIR` (`Dockerfile` lignes 1-40,
`scripts/lib/docker-plugin-selection.mjs`). **L'élagage se fait donc en supprimant des dossiers de
manifestes, pas en traquant des arêtes d'import** — méthode déjà utilisée par OpenClaw lui-même pour ses
builds Docker allégés, qu'un fork dur rend simplement permanente au lieu d'optionnelle.

### 3.2 `extensions/` — 129 868 Ko mesurés (`du -sk`), 162 dossiers réels

| Catégorie (déclarée) | n | Ko | Garder | Ko gardés | Élaguer (échantillon) |
|---|---:|---:|---|---:|---|
| channels | 24 | 46 968 | 8 : sms, whatsapp, telegram, signal, msteams, slack, googlechat, imessage | 21 340 | discord (7 720), matrix (4 476), feishu (3 504), mattermost, line, clickclack, buzz, zalouser, tlon, nextcloud-talk, zalo, nostr, synology-chat, irc, twitch, raft |
| models | 56 | 15 588 | 9 (§2) | 7 376 | amazon-bedrock, anthropic-vertex, xai, deepinfra, opencode, qwen, moonshot, clawrouter, zai, deepseek, apple-fm, xiaomi, venice, tencent, chutes, meta, huggingface, nvidia, radius, synthetic, volcengine, baseten, together, arcee, sglang, byteplus, cerebras, fireworks, kilocode, cloudflare-ai-gateway, longcat, qianfan, vercel-ai-gateway, cohere, groq, stepfun, vllm, featherless, copilot-proxy, gmi, novita, github-copilot, minimax, microsoft-foundry, kimi-coding, opencode-go, amazon-bedrock-mantle |
| agent-runtimes | 4 | 17 260 | — | 0 | codex (14 640, harnais Codex app-server), copilot (1 156), acpx (1 056), agentsapi (408) — harnais code, hors sujet business |
| developer-tools | 8 | 11 828 | — | 0 | qa-lab (9 896), qa-channel, diffs, github, beam, onnx, typesafe, diffs-language-pack |
| web | 10 | 9 180 | 2 : browser, firecrawl | 7 980 | exa, brave, duckduckgo, tavily, parallel, perplexity, searxng, web-readability |
| memory | 5 | 7 240 | 4 (§2) | 7 140 | voyage (embeddings, redondant) |
| voice | 15 | 5 952 | 5 : voice-call, talk-voice, elevenlabs, deepgram, tts-local-cli | 2 692 | google-meet, facetime, teams-meetings, zoom-meetings, senseaudio, inworld, fish-audio-speech, azure-speech, gradium, microsoft |
| infrastructure | 8 | 3 112 | 5 : diagnostics-otel, diagnostics-prometheus, geolocation, code-mode-quickjs, crabbox | 2 644 | bonjour (mDNS, surface exposée inutile sur VPS), linux-node, admin-http-rpc |
| security | 7 | 2 684 | 3 : policy, device-pair, vault | 1 448 | openshell, mxc (Windows-only), onepassword, visitor-access |
| productivity | 2 | 2 968 | — | 0 | workboard (redondant avec kanban M2), logbook (captures d'écran périodiques — risque Loi 25) |
| documents-files | 4 | 1 956 | 1 : document-extract | 144 | file-transfer, oc-path, canvas (macOS) |
| agent-orchestration | 4 | 1 596 | 1 : llm-task | 156 | reef, a2a, lobster (approbations redondantes avec OPSYS) |
| data-analytics | 1 | 1 024 | — | 0 | team-reports (GitHub/Discord, hors sujet) |
| media | 6 | 880 | — | 0 | vydra, fal, comfy, pixverse, runway, alibaba (génération image/vidéo) |
| integrations | 2 | 668 | — | 0 | migrate-hermes, migrate-claude (utile mais non requis — à réévaluer, coût faible) |
| computer-use | 1 | 436 | — | 0 | cua-computer (contrôle bureau distant — risque) |
| inbox-collaboration | 2 | 364 | 1 : imap | 200 | session-share |
| context | 1 | 120 | 1 : tokenjuice (compaction — économie de tokens) | 120 | — |
| sans catégorie | 2 | 44 | — | 0 | test-support, image-generation-core (orphelin si média élagué) |
| **Total** | **162** | **129 868** | **40 dossiers** | **51 240** | **122 dossiers, 78 628 Ko (−61 %)** |

### 3.3 Autres dossiers

| Dossier | Décision | Gain | Risque |
|---|---|---:|---|
| `apps/` (70 132 Ko) | **Élaguer en totalité, phase 1.** Hors workspace pnpm (aucune dépendance de build). La phase 1 de `docs/architecture/MOBILE.md` utilise les apps **officielles** OpenClaw (App Store/Google Play), pas ce code. `apps/ios`+`apps/android`+`apps/shared` (46 Mo) seront ré-importés du même tag en phase 2 **si** le choix natif l'emporte sur Expo (tension ouverte, §7.5). `apps/macos`, `macos-mlx-tts`, `linux`, `swabble` (19 Mo) : compagnons desktop hors périmètre produit. | −70 Mo | Faible (aucun lien de build). Point ouvert produit : natif vs Expo. |
| `crates/` (688 Ko) | Élaguer. `openclaw-node-host` sert le runtime headless des compagnons « node » (desktop/linux) — hors périmètre tant qu'`apps/linux`/`apps/macos` sont élagués. | −0,7 Mo | Nul |
| `docs/` (28 416 Ko) | Élaguer en totalité du fork livré. OPSYS écrit sa propre doc dans `docs/` du dépôt OPSYS-AI. Utile en lecture pendant la transformation, non copiée dans `core/`. | −28 Mo | Nul |
| `CHANGELOG/` + `CHANGELOG.md` (7 596 Ko) | Élaguer. Historique amont sans valeur pour OPSYS. | −7,6 Mo | Nul |
| `qa/` (3 772 Ko) | Élaguer. QA interne amont (`maturity-scores.yaml`, scénarios propres à OpenClaw). | −3,8 Mo | Nul |
| `.github/` (6 144 Ko, 60+ workflows) | **Ne pas migrer — remplacer** par 3-5 workflows OPSYS (§6.3). Quasi-totalité = release engineering multi-plateforme amont (android-release, ios-release, macos-release, docker-release, mantis-*-bots Discord/Slack). | −6 Mo | Nul (remplacement, pas fusion) |
| `scripts/` (21 184 Ko, ~260 fichiers) | Élaguer ~80-85 %. Garder : `install.sh`/`install.ps1` (adaptés), la chaîne de build (`build-all.mts`, `tsdown-build.mts`, `lib/docker-plugin-selection.mjs`), les scripts Docker e2e génériques. Élaguer : signing iOS/Android/macOS, ClawHub publish, Sparkle/appcast, bots Discord/Slack « mantis ». | ~−17,7 Mo (estimation) | Moyen : certains scripts de build s'entre-appellent — élaguer par vagues testées, pas d'un coup |
| `test/` (36 908 Ko) | Élaguer les tests des canaux/fournisseurs/apps supprimés : ex. `discord-live-policy.integration.test.ts`, `matrix-*-authority.integration.test.ts`, `feishu-message-*.integration.test.ts`, `twitch-message-tool-delivery.test.ts`, `buzz-account-config-mutation.test.ts`, `linux-dashboard-recovery.test.ts`, `huggingface-local-app-openclaw.e2e.test.ts`, `codex-*.integration.test.ts` (6 fichiers), `copilot-tool-policy-handoff.*.test.ts`, `provider-auth-method.radius.integration.test.ts`, `qa-channel-*.test.ts`. Garder tout ce qui touche gateway/cli/config/mcp/cron/mémoire/les 8 canaux et 9 fournisseurs gardés. | ~−18,9 Mo (estimation, ~50 %) | **Élevé si mal fait** — c'est le filet de sécurité ; élaguer fichier par fichier après avoir confirmé l'extension correspondante absente, jamais en bloc |
| `config/`, `examples/`, `.agents/`, `.vscode/`, `.claude/`, `.openclaw/` (~11 Mo) | Élaguer (outillage dev amont : knip, oxlint, opengrep, `fly.toml`, agents de contribution). | ~−11 Mo | Nul |
| `appcast*.xml` (828 Ko) | Élaguer (flux Sparkle macOS, lié à `apps/macos` élagué). | −0,8 Mo | Nul |
| `skills/` (1 024 Ko, 50 skills) | Curer, pas pour la taille (négligeable) mais pour la pertinence/surface : garder `control-ui`, `github`, `healthcheck`, `diagram-maker` ; élaguer les skills grand public (`apple-notes`, `apple-reminders`, `bear-notes`, `1password`, `clawhub`, `gifgrep`, `goplaces`, `himalaya`…) — cohérent avec le principe ARCHITECTURE.md #7 (aucune capacité non revue). | négligeable | Nul |
| `custodian-skills/` (1 024 Ko) | **Garder**, rebrander. Skills d'auto-administration (ajout de fournisseur, canal, diagnostic Gateway) — utile à un OPSYS-admin. | — | — |
| `patches/` (7 fichiers pnpm) | Garder les patches liés à des dépendances conservées (baileys→whatsapp, chrome-devtools-mcp→browser, vitest, webawesome→ui, proxyline→crabbox). Élaguer `matrix-js-sdk` (matrix élagué) et `@novnc/novnc` (lié à un usage bureau à distance non retenu). | négligeable | Nul si aligné avec §3.2 |

## 4. Surface de renommage

Mesures `git grep` sur le clone (reproductibles) :

| Surface | Occurrences mesurées | Méthode recommandée | Risque |
|---|---:|---|---|
| Variables d'env `OPENCLAW_*` | **3 322 identifiants distincts, 48 253 occurrences** (`git grep -ohE "OPENCLAW_[A-Z0-9_]+" \| sort -u \| wc -l`) | **Ne pas renommer en interne.** Fixer les valeurs OPSYS via l'environnement (Docker/systemd) : `OPENCLAW_HOME`, `OPENCLAW_STATE_DIR`, `OPENCLAW_CONFIG_PATH`, `OPENCLAW_CONFIG_DIR` sont déjà des points de surcharge officiels (vus dans `docker-compose.yml` et `.env.example`) | **Élevé** si renommage en masse — c'est le piège n°1 |
| Dossier `~/.openclaw` / fichier `openclaw.json` | 1 245 fichiers référencent `.openclaw`, 1 337 `openclaw.json` | Surcharger `OPENCLAW_STATE_DIR`/`OPENCLAW_CONFIG_PATH` dans l'image/l'installateur OPSYS (zéro patch source). Si le nom de fichier littéral doit changer : imiter le **précédent existant** — `openclaw.mjs::resolveLauncherConfigPaths()` accepte déjà un deuxième nom hérité, `clawdbot.json`/`~/.clawdbot` (**76 occurrences** de `clawdbot` dans le dépôt — OpenClaw s'appelait autrefois Clawdbot). Ajouter un troisième alias `opsys.json` au même endroit suit un patron déjà testé. | Faible si on suit le précédent, élevé si renommage global |
| Paquets npm `@openclaw/*` | **183 `package.json`** déclarent `"name": "@openclaw/…"` sur 184 manifestes du workspace | Laisser le scope interne tel quel (jamais publié en dehors du monorepo ; invisible du client PME). Renommer uniquement `package.json` racine (`"name"`, `"bin": {"opsys": "openclaw.mjs"}` ou un wrapper renommé) | Élevé si renommage massif (48k+ références croisées), nul si on laisse le scope interne |
| Binaire/CLI | `bin: {"openclaw": "openclaw.mjs"}` | Republier sous un nouveau nom de commande (`opsys`), fichier `openclaw.mjs` conservé tel quel ou renommé une fois, un seul point de vérité | Faible |
| Chaînes UI (« OpenClaw ») | **508 fichiers, 8 652 occurrences** dans `ui/src` (`git grep -oh "OpenClaw" -- ui/src \| wc -l`) | Script de remplacement ciblé + revue visuelle (captures d'écran Control UI avant/après) | Moyen — mécanique mais volumineux |
| Domaine `openclaw.ai` | 692 fichiers au total, concentrés dans `CHANGELOG/` (24, élagué), `docs/` (élagué), `test/scripts` (13, élagué), `.github/workflows` (7, remplacé). **Résiduel critique : `scripts/install.sh`** (10 lignes en dur, ex. `curl -fsSL https://openclaw.ai/install.sh`, `https://docs.openclaw.ai/start/faq`, `https://openclaw.ai/install-cli.sh`) et `scripts/install.ps1` (5 lignes) | Remplacer les URLs dans les 2 installateurs conservés ; le reste disparaît avec l'élagage | Faible (localisé) |
| Registre Docker `ghcr.io/openclaw` | 10 fichiers (surtout `docs/`, élagués) | `docker-compose.yml`/`Dockerfile` OPSYS pointent vers son propre registre (`ghcr.io/<org>/opsys-core`) — fichiers déjà réécrits pour OPSYS | Nul |
| Identifiant de protocole `openclaw://` | 52 fichiers, concentrés dans `apps/.i18n/*` (élagué en phase 1) | Décision différée à la phase 2 (apps natives) | Faible en phase 1 |
| Service système | 1 fichier statique trouvé : `scripts/systemd/openclaw-auth-monitor.{service,timer}` (renommage direct). Le démon principal est **généré** par `openclaw onboard --install-daemon` — nom exact non trouvé dans les sources statiques lues ici | Renommer le fichier statique ; **vérifier sur VPS réel** le nom généré du service principal avant de le considérer réglé | Moyen — dépend d'un run réel, hors bac à sable |
| Marques/logos | `ui/public/{app-art,community-art,favicon.*,apple-touch-icon.png,manifest.webmanifest}` (mascotte homard, thème « EXFOLIATE! »), bannières `README.md` (images hébergées sur `raw.githubusercontent.com/openclaw/openclaw`), badges npm/Discord/CI | Remplacer intégralement par les assets OPSYS ; les icônes **par extension gardée** (`extensions/<id>/assets/icon.png`, marques tierces avec attribution, cf. `extensions/ICON_SOURCES.md`) restent légitimes (fair use d'interopérabilité) et voyagent avec l'extension | Faible, mécanique |

**Pièges vérifiés (tests qui vérifient des noms) :** `test/official-channel-catalog.test.ts` (énumère
vraisemblablement les 24 canaux), `test/npm-publish-plan.test.ts`, `test/package-scripts.test.ts`
(énumèrent probablement les 183 paquets) — casseront après élagage tant qu'ils ne sont pas mis à jour/
supprimés avec l'extension correspondante. Baselines chiffrées à régénérer après élagage :
`config/env-var-count-budget.txt`, `config/max-lines-baseline.txt`, `config/assertion-safety-baseline.txt`,
`config/ci-test-timings.json` (sinon la CI amont — non reprise — aurait signalé un écart ; sans objet une
fois `.github/` remplacé, mais logique à retenir si OPSYS réutilise le principe).

## 5. Licences

- **`LICENSE`** (1 170 octets) : MIT, *Copyright (c) 2026 OpenClaw Foundation*. **À conserver texte et
  copyright inchangés** (obligation MIT : notice de copyright + notice de permission dans toute copie
  substantielle). Recommandation : garder `LICENSE` tel quel, ajouter un `core/PROVENANCE.md` séparé
  (§6.2) déclarant le fork et une éventuelle notice de copyright OPSYS pour les modifications — ne pas
  réécrire `LICENSE` lui-même.
- **`THIRD_PARTY_NOTICES.md`** (2,8 Ko) : deux entrées, toutes deux MIT — Pi/pi-mono (`@earendil-works/pi-tui`,
  Copyright Mario Zechner 2025 ; **dépendance active confirmée**, 37 références dans le graphe d'imports
  atteint) et GitHub Octicons (Copyright GitHub Inc. 2026, deux icônes dans Control UI). **À garder tel
  quel** tant que `ui/` et le rendu terminal sont conservés.
- **Dépendances non permissives.** `grep -i gpl pnpm-lock.yaml` (592 Ko) → 1 seule occurrence, dans un
  hash d'intégrité base64 (`sha512-bCbX9ZEyFkWPsRz7Bl3NuQUJohmwGSev…`), pas une licence — **faux positif,
  aucune trace GPL/AGPL confirmée** (recoupe R1, qui avait fait la même vérification sur
  `THIRD_PARTY_NOTICES.md`). `package.json` racine : 65 `dependencies` + 62 `devDependencies`, toutes des
  paquets npm courants (SDK des fournisseurs de modèles, `express`, `kysely`, `zod`, `commander`…) sans
  signal de licence copyleft forte.
- **Marques/logos à retirer** : mascotte homard et thème visuel (`ui/public/*`), bannières `README.md`
  hébergées sur le dépôt GitHub amont, badges liés à `openclaw.ai`/Discord/npm. Voir §4 (dernière ligne).
  Les icônes *par extension* (Slack, WhatsApp, Telegram…) documentées dans `extensions/ICON_SOURCES.md`
  restent légitimes pour les extensions conservées (usage nominatif d'interopérabilité).

## 6. Stratégie d'import

### 6.1 Récupération du tag exact

```bash
# Dans un clone de travail séparé (jamais le clone read-only du bac à sable)
git clone --filter=blob:none https://github.com/openclaw/openclaw.git /tmp/import-openclaw
cd /tmp/import-openclaw
git fetch --depth 1 origin tag v2026.9.6
git checkout FETCH_HEAD
git rev-parse HEAD                       # doit imprimer ce5bbdc244ee937246cc1700d1b224d020c3b599
git log -1 --format=%cI                  # date du commit taggé, pour provenance
```

Vérifier `HEAD` contre `core/UPSTREAM.md` (déjà à jour : commit `ce5bbdc2…`) **avant** de continuer — les
chiffres de ce document viennent d'un `main` à `2d39f2f7`, quelques commits après le tag ; une divergence
de détail (tailles, noms de fichiers) est possible et doit être revérifiée à ce moment-là.

### 6.2 Import instantané + provenance

```bash
rm -rf /tmp/import-openclaw/.git          # pas d'historique amont importé
mkdir -p /home/user/OPSYS-AI/core/vendor
rsync -a --delete /tmp/import-openclaw/ /home/user/OPSYS-AI/core/vendor/
```

Remplacer `core/UPSTREAM.md` par `core/PROVENANCE.md` (nouvelle ADR-0008 à écrire séparément) consignant :
dépôt (`github.com/openclaw/openclaw`), tag (`v2026.9.6`), commit (`ce5bbdc2…`), date du commit, date
d'import, licence (MIT, copyright OpenClaw Foundation 2026), et le commit du script d'élagage/renommage
utilisé (traçabilité de la transformation elle-même).

### 6.3 Ordre des opérations (commits séparés, bisectables)

1. **Import brut** — copie intégrale du tag, aucune modification, un seul commit « import brut
   openclaw@v2026.9.6 ». Vérifier `git ls-files | wc -l` contre le nombre de fichiers du tag amont.
2. **Élagage** — supprimer par vagues testées (§3), dans l'ordre : `apps/`, `crates/`, `docs/`, `CHANGELOG/`,
   `qa/`, `.github/workflows` (remplacés), `config/`/`examples/`/dossiers dev ; puis `extensions/`
   (122 dossiers, §3.2) ; puis `scripts/`+`test/` en dernier (dépendent de ce qui reste). Un commit par
   vague. Après l'élagage des extensions : `pnpm install` (régénère `pnpm-lock.yaml` sans `--frozen-lockfile`,
   une seule fois) pour purger les entrées orphelines.
3. **Renommage** — script de remplacement ciblé (§4), en 3 passes séparées : (a) UI/branding (508 fichiers
   `ui/src`, mécanique), (b) 2 installateurs (URLs), (c) `package.json` racine + nom de binaire. **Ne pas**
   toucher aux 3 322 identifiants `OPENCLAW_*` ni aux 183 scopes `@openclaw/*` internes (§4). Tests
   complets après chaque passe.
4. **Greffes OPSYS** (§7) — ajout des pages Control UI, du point de pairage département↔MCP, etc.

### 6.4 CI GitHub Actions (le bac à sable de développement n'exécute pas le code amont)

| Paramètre | Valeur |
|---|---|
| Node | `24.16.x` (ligne par défaut Linux de l'installateur amont ; respecte `engines: ">=24.16.0 <25 \|\| >=26.1.0"`) |
| pnpm | `12.5.1` exact (`corepack enable`, lu depuis `packageManager` du `package.json` OPSYS) |
| Installation | `pnpm install --frozen-lockfile` |
| Build | `pnpm build` (= `scripts/build-all.mts`, conservé) ; `pnpm build:docker` pour l'image |
| Tests | Projet Vitest « unit-fast » sur chaque PR (job `gates`, obligatoire selon `AGENTS.md`) ; projet e2e/live en tâche nocturne séparée (ressources Docker) |
| Cache | Cache pnpm store (clé = hash de `pnpm-lock.yaml`, via `actions/setup-node` `cache: pnpm` ou `actions/cache`) ; envisager le cache du compile-cache Node natif (`node-compile-cache.mjs`, déjà présent en amont) |
| Durée estimée | Install (cache chaud) 1-3 min ; build (tsdown, 40 extensions au lieu de 162) 3-8 min ; tests unit-fast 3-10 min ; image Docker 5-10 min → **~15-25 min** pour le job `gates` — **estimation**, à mesurer au premier run réel (aucune exécution possible ici) |

## 7. Points de greffe pour OPSYS

1. **Départements (registre, outils).** **Aucun changement requis immédiatement.**
   `src/opsys/openclaw.py::generer()` écrit déjà uniquement des fragments `$include` consommant des
   surfaces publiques (`agents.entries`, `models.providers`, `mcp.servers`) — ces clés de config restent
   valides après le fork puisqu'elles ne sont pas touchées par le renommage (§4). Le gain du fork ici est
   la possibilité, plus tard, de faire de `departments/mNN-*/department.yaml` un concept natif de
   `src/config/` plutôt qu'un générateur de JSON — non nécessaire pour livrer une v1.
2. **Événements inter-départements.** Le schéma `department.yaml` actuel (`departments/m03-estimation/department.yaml`)
   n'a pas de champ « événements » — la cascade « travaux terminés » (`DEFINITION-PRODUIT.md` §6) est déjà
   pensée comme des appels d'outil MCP directs entre départements (M4 appelle un outil exposé par M6), pas
   un bus pub/sub. Point de greffe secondaire côté OpenClaw : `src/agents/agent-hooks/` (hooks de session,
   pré/post-outil) pour déclencher une notification Console quand un T2/T3 est créé — complémentaire, pas
   le mécanisme principal.
3. **Approbations humaines N0–N5.** Graphe natif précis : `src/gateway/exec-approval-manager.ts`,
   `operator-approval-store.{native,rows,transitions}.ts`, `operator-approval-authorization.ts`,
   `operator-approval-standing-grants.ts`, `exec-approval-expiry.ts`, plus
   `src/agents/agent-tools.before-tool-call.approval.ts` (interception avant exécution) et
   `src/claws/tool-policy-runtime.ts`/`tool-policy-candidates.ts` (politique par outil). C'est la même
   mécanique que R1 appelait « exec approvals » — à faire correspondre aux niveaux N0-N5
   (`DEFINITION-PRODUIT.md` §5 P1) dans la politique d'autonomie déjà écrite côté OPSYS
   (`departments/*/department.yaml::mode`, `Outil.autonomie` T0-T3 dans `docs/architecture/DEPARTEMENTS.md`) :
   T0/T1 → outils MCP exécutés directement ; T2/T3 → une approbation native `operator-approval-store`
   créée par le serveur MCP OPSYS au lieu d'exécuter, résolue depuis la Console ou l'app mobile
   (extension `device-pair`, approbations natives déjà dans les apps officielles).
4. **RBAC (rôles, `DEFINITION-PRODUIT.md` §5 P8).** OpenClaw a un `src/gateway/operator-role-policy.ts`
   natif, mais c'est une distinction **opérateur de la Gateway vs invité** (mono-tenant, cf. R1), pas les
   8 rôles métier (`nathan_owner`, `admin`, `finance`, `manager`, `seller`, `employee`, `client`,
   `system_agent`). **Les deux couches restent séparées** : les 8 rôles métier s'appliquent dans la couche
   Python d'OPSYS (`src/opsys/capacites.py` selon `ARCHITECTURE.md`), qui décide quels outils `mN_*` un
   appelant peut invoquer et quels champs il voit (ex. un `employee` ne voit jamais de marge) ; le
   `operator-role-policy` natif reste la frontière plus grossière « qui est opérateur de la Gateway »
   (typiquement `nathan_owner`/`admin` seulement — employés/clients/vendeurs n'ont jamais de session
   opérateur directe, seulement l'app mobile → MCP département).
5. **RAM / context engine.** `src/context-engine/` (15 fichiers, 100 % atteint depuis `entry.ts`) — module
   dédié, déjà nommé « context engine » comme dans la définition produit. Aucune extension à ajouter ;
   configuration via `agents.defaults.contextPruning` (déjà utilisé par `src/opsys/openclaw.py`, ligne
   `"contextPruning": {"mode": "cache-ttl", "ttl": "1h"}`).
6. **Mémoire M10.** Architecture à deux couches déjà actée (`ARCHITECTURE.md` ligne 39) : mémoire d'agent
   native (`memory-core`+`memory-lancedb`+`memory-wiki`+`active-memory`, §2) pour l'épisodique/personnel,
   et base de connaissances d'entreprise Postgres/pgvector d'OPSYS (`src/opsys/memoire/`) exposée en MCP
   pour le M10 canonique — **communication uniquement via MCP, jamais de base partagée** (déjà la
   décision ; le fork ne la change pas). Point d'intérêt réutilisable : le mécanisme de purge par
   tombstone de `memory-core` (`memory_forget`) est un bon patron pour la purge Loi 25 déjà exigée par
   `ARCHITECTURE.md`/P8.
7. **Dashboard (pages OPSYS).** Ajouter des routes dans `ui/src/pages/` (24 Mo, plus gros sous-dossier de
   `ui/src`) en suivant le patron Lit/web-components existant, enregistrées dans `ui/src/app/` (4 Mo,
   coquille de routage), widgets partagés dans `ui/src/components/` (8 Mo). Le skill `control-ui`
   (`skills/control-ui/`) documente déjà comment un agent construit ses propres widgets — réutilisable
   pour les wallboards M8.
8. **Appairage de l'app mobile.** Extension `device-pair` (256 Ko, « Generate setup codes and approve
   device pairing requests ») — mécanisme natif exact. Phase 1 (`MOBILE.md`) : appairage direct des apps
   officielles OpenClaw (`role: node`) à la Gateway OPSYS via QR code/code de configuration, aucune
   modification requise. Phase 2 (fork `apps/ios`/`apps/android`) : décision produit **non tranchée** —
   `ADR-0007` (2026-09-28, postérieure) prévoit explicitement un fork natif Swift/Kotlin de
   `apps/ios`+`apps/android` ; `DEFINITION-PRODUIT.md` §9.1 mentionne une « forge-app » antérieure
   « probablement React Native/Expo ». **Tension à trancher avant la phase 2** — ce document ne tranche
   pas, il documente les deux options et leur coût : natif = ré-importer `apps/ios`+`android`+`shared`
   (46 Mo) du même tag et les rebrander (écrans par profil déjà esquissés dans `MOBILE.md`) ; Expo = pas
   de code amont à importer du tout, mais perte de l'appairage `role: node` natif et de ses capacités
   (approbations, voix, localisation) déjà prêtes à l'emploi.

## 8. Récapitulatif chiffré

| | Avant | Après (estimé) | Δ |
|---|---:|---:|---:|
| Taille totale (hors `.git`) | 737 Mo (`du -sm`, exact) | ≈ 508 Mo | **−229 Mo (−31 %)** |
| … dont `src/`+`ui/` (cœur produit, gardé ~intégral) | 430 Mo | ≈ 430 Mo | 58 % du total, volontairement non élagué |
| … dont `extensions/` | 130 Mo (162 dossiers) | 50 Mo (40 dossiers) | **−78 Mo (−61 %), −122 dossiers** |
| … dont `apps/` | 70 Mo | 0 (phase 1) | −70 Mo |
| … dont `docs/`+`CHANGELOG/`+`qa/` | 40 Mo | 0 | −40 Mo |
| … dont `test/`+`scripts/` | 58 Mo | ≈ 22 Mo | −36 Mo (estimation, dépend du détail §3.3) |
| Manifestes de paquets npm internes | 184 (`git grep -c '"name": "@openclaw/'` = 183 + racine) | ≈ 64 (23 `packages/*` + 40 extensions + racine) | **−65 %** |
| Identifiants `OPENCLAW_*` distincts | 3 322 | 3 322 (non renommés, §4) | 0 — risque évité, pas réduit |

**Risques principaux, par ordre :**
1. **Suite de tests couplée aux noms/quantités** (`official-channel-catalog.test.ts`,
   `npm-publish-plan.test.ts`, baselines chiffrées `config/*.txt`) — casse silencieuse si l'élagage/
   renommage n'est pas accompagné de la mise à jour de ces tests.
2. **Divergence tag vs clone lu ici** (`main@2d39f2f7` vs `v2026.9.6@ce5bbdc2`) — à revérifier avant
   l'import réel (§6.1).
3. **Décision produit non tranchée** sur les apps natives vs Expo (§7.8) — bloque le dimensionnement de
   la phase 2 mobile, pas la livraison d'OPSYS-CORE v1 (Gateway + Control UI + départements).
4. **Nom du service système principal** non trouvé statiquement (généré par `openclaw onboard
   --install-daemon`) — à vérifier sur un VPS réel avant de considérer le renommage du service complet.
5. **Élagage de `scripts/`/`test/` par vagues, jamais en bloc** — dépendances internes entre scripts de
   build non cartographiées ligne à ligne ici (volume trop grand pour une lecture exhaustive) ; chaque
   vague doit être suivie d'un `pnpm build && pnpm test` avant la suivante.

PREUVE:
- Fichier écrit : `/home/user/OPSYS-AI/docs/research/R11-fork-openclaw.md` (aucun autre fichier modifié).
- Lu avant rédaction : `docs/produit/DEFINITION-PRODUIT.md` (§1, §3, §4, §5 P1/P8, §6, §7, §8, §9),
  `docs/architecture/ARCHITECTURE.md`, `docs/architecture/DEPARTEMENTS.md`, `docs/architecture/MOBILE.md`,
  `core/UPSTREAM.md`, `src/opsys/openclaw.py`, `docs/decisions/ADR-0007-core-openclaw.md`,
  `docs/research/R1-core-openclaw.md`, `docs/research/00-BRIEF.md`, `departments/m03-estimation/*`.
- Clone OpenClaw exploré en lecture seule : `du -sm`/`du -sk` par dossier (chiffres du §1, total 737 Mo
  confirmé par `du -sm --exclude=.git`), `git grep -c/-l/-oh` pour les surfaces de renommage (§4),
  `git ls-files`, lecture de `package.json`, `pnpm-workspace.yaml`, `tsconfig.json`, `openclaw.mjs`,
  `docker-entrypoint.mjs`, `docker-compose.yml`, `Dockerfile`, `LICENSE`, `THIRD_PARTY_NOTICES.md`,
  `.env.example`, `extensions/sms/{package.json,openclaw.plugin.json}`, `extensions/ICON_SOURCES.md`,
  `README.md`, `scripts/install.sh`/`install.ps1`, `pnpm-lock.yaml` (`grep -i gpl`).
- Scripts Python maison écrits et exécutés (lecture seule, zéro code amont exécuté, zéro paquet npm
  installé), conservés dans `scratchpad/analysis/` :
  - `classify_extensions.py` → sortie complète capturée, base du tableau §3.2 (129 868 Ko, 162 dossiers,
    18 catégories).
  - `reachability.py` → BFS d'imports depuis `src/entry.ts`/`index.ts`/`runtime.ts`/`library.ts` ;
    10 307/11 716 fichiers `src/` atteints (88 %), 0 arête statique vers `extensions/` (25 faux positifs
    identifiés et expliqués, tous dans `src/agents/sessions/extensions/`) — base du §3.1 et du tableau §2.
- Aucune commande destructive, aucun fichier hors `docs/research/R11-fork-openclaw.md` modifié dans
  `/home/user/OPSYS-AI`.
