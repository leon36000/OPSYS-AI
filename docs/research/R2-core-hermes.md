# R2 — Hermes Agent (NousResearch) comme base du code source d'OPSYS-CORE

Repo cloné (`--depth 1`, conservé) : `<scratchpad>/clones/hermes-agent`
Commit HEAD au clone : `68fa7e9f840d24c72774508cc4dc99e8fcceb26f` (2026-09-27).
Sources : [github.com/NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent), `api.github.com/repos/NousResearch/hermes-agent` (interrogé par deux voies indépendantes : Firecrawl scrape + outil MCP GitHub `search_repositories`, résultats identiques), lecture directe du code cloné.

## 1. Fiche d'identité

| Champ | Valeur | Source |
|---|---|---|
| Nom / URL | Hermes Agent — https://github.com/NousResearch/hermes-agent | repo |
| Licence | **MIT** (fichier `LICENSE` racine, `Copyright (c) 2025 Nous Research`) ; confirmée aussi par `license.spdx_id="mit"` côté API GitHub | [LICENSE](https://github.com/NousResearch/hermes-agent/blob/main/LICENSE) |
| Langage principal (GitHub) | Python | API GitHub |
| Créé | 2025-07-22 | API GitHub (`created_at`) |
| Dernier push | 2026-09-28 (aujourd'hui, activité continue) | API GitHub (`pushed_at`) |
| Étoiles / forks / issues ouvertes | 249 546 / 53 078 / 44 620 | API GitHub, **vérifié par 2 sources indépendantes** (Firecrawl + outil GitHub officiel) — chiffres cohérents entre les deux |
| Dernière release | **v2026.9.24** (tag calver ; version interne "v0.21.5"), publiée 2026-09-24, soit **4 jours avant cette recherche** | `api.github.com/.../releases` |
| Cadence de release | ~1 release tous les 3-10 jours (9.24, 9.21, 9.14, 9.11, 9.7 observées) | idem |
| Éditeur | Nous Research (org., fabricant des modèles Hermes) | repo |

**Note de prudence méthodologique (PROOF-C, CLAIMS UNVERIFIED)** : les notes de release elles-mêmes revendiquent une vélocité extrême (ex. fenêtre v0.21.3→v0.21.4 : **5 071 commits non-merge, 1 812 PR mergées, 140 contributeurs, en ~7 jours**). Je n'ai pas de moyen indépendant de vérifier l'authenticité de cette vélocité (hors mémoire de modèle — donc **NON VÉRIFIABLE** avec les outils disponibles ici) ; je la traite comme fait rapporté par la source primaire (GitHub Releases API), pas comme vérité absolue, et j'en tire une conséquence directe pour le risque de churn (§4).

## 2. Mesures du code (clone réel)

- **Polyglotte, très volumineux** : ~16 545 fichiers versionnés, taille repo (API) 1 085 841 Ko (~1,06 Go avec historique).
- **Python** : 2 129 448 lignes / 7 862 fichiers `.py` (dont **1 242 667 lignes dans `tests/`** — suite de tests massive). Code applicatif non-test ≈ **886 800 lignes**.
- **TypeScript/TSX/JS** : 960 012 lignes (dashboard `web/` = 31 707 lignes ; le reste = app desktop Electron `apps/desktop`, site doc Docusaurus `website/`, package TUI `ui-tui/`).
- **Rust/C natif** : ~5 900 lignes (`native/fts5_cjk/` — extension SQLite FTS5 pour tokenisation CJK, compilée au build Docker).
- **LOC par paquet Python (mesure corrigée, `cat|wc -l`)** :

| Paquet | LOC | Rôle |
|---|---:|---|
| `hermes_cli/` | 244 340 | CLI, setup wizard, config, auth |
| `agent/` | 128 952 | boucle agent, providers, compression, tools dispatch |
| `tools/` | 120 068 | implémentation des ~40+ outils (terminal, MCP, fichiers, browser…) |
| `gateway/` | 95 168 | gateway messagerie multi-canal |
| `plugins/` | 89 765 | tous les plugins (providers, mémoire, dashboard-auth, etc.) |
| `tui_gateway/` | 40 422 | backend RPC pour TUI/Desktop |
| `scripts/` | 33 398 | scripts build/release/install |
| racine (`run_agent.py`, `hermes_state*.py`, `cli.py`…) | 32 269 | état SQLite, bootstrap, constants |
| `optional-skills/` | 31 388 | skills catalogue optionnel |
| `evals/` | 20 025 | tooling recherche NousResearch (génération trajectoires) — **hors scope OPSYS** |
| `cron/` | 17 274 | scheduler |
| `skills/` | 11 595 | skills bundlées (peu de code, surtout `SKILL.md`) |
| `pm/` | 11 424 | package manager interne (« PM ») |
| `acp_adapter/` | 4 571 | pont Agent Client Protocol (Zed, etc.) |
| `hermes_platform/` | 1 216 | abstraction OS |
| `providers/` | 1 067 | registre ABC des providers modèles |
| `optional-mcps/` | 0 (pur YAML) | 65 connecteurs MCP catalogués |

- **Tests** : **5 217 fonctions `test_*`** (grep) réparties sur **40 sous-dossiers** de `tests/` (agent, gateway, cron, security, providers, plugins, honcho_plugin, openviking_plugin, e2e, conformance, install…) + 15 fichiers `tests-js` (Vitest, `web/`). Suite très large et catégorisée (`tests/security/`, `tests/conformance/` existent explicitement).
- **Structure top-level** (24 dossiers de 1er niveau) : `agent/ apps/ acp_adapter/ cron/ docker/ evals/ gateway/ hermes_cli/ hermes_platform/ native/ nix/ optional-mcps/ optional-skills/ plugin-catalog/ plugins/ pm/ providers/ scripts/ skills/ tests/ tests-js/ tools/ tui_gateway/ ui-tui/ web/ website/`.
- **Dépendances runtime (`pyproject.toml`)** : ~30 deps **cœur** exact-pinnées (openai, httpx[socks], pydantic 2.13, prompt_toolkit, **croniter** [cron natif], snowballstemmer [BM25 tool_search], Markdown, PyJWT[crypto], requests, jinja2, firecrawl-anydoc…), + **~60 extras optionnels** eux-mêmes pinnés (anthropic, telegram=`python-telegram-bot`, discord=`discord.py`, slack=`slack-bolt`+`slack-sdk`, matrix, wecom, google-chat, teams, sms, homeassistant, feishu, dingtalk, acp=`agent-client-protocol`, mcp, bedrock=`boto3`, vertex=`google-auth`, azure-identity, mistral, honcho=`honcho-ai`, mem0, supermemory, voice/wake-word (openwakeword/sherpa/porcupine), stt-whisper, tts-premium=`elevenlabs`, neutts/kittentts/piper (TTS locaux), computer-use, otlp/langfuse (observabilité), modal/daytona/vercel (sandboxes cloud)…). Politique de sécurité supply-chain explicite : épinglage strict exact (`==X.Y.Z`), justifié en commentaire par un incident réel cité (« Mini Shai-Hulud worm » sur `mistralai` 2.4.6).
- **Version Python requise** : `>=3.11,<3.15` (`pyproject.toml`) ; environnement dev pinné sur **3.14** (`.python-version`). Bien au-dessus du 3.12 utilisé par OPSYS (compatible, 3.12 ⊂ [3.11,3.15)).
- **Licence — signal d'alerte mineur** : plusieurs sous-dossiers de skills/plugins embarquent leur **propre** fichier LICENSE distinct de la racine (`skills/productivity/{pdf,docx,xlsx,pptx}/`, `skills/creative/humanizer/`, `optional-skills/software-development/{ast-grep,pr-lens}/`, `optional-skills/creative/*`, `plugins/hermes-achievements/`, `plugins/security-guidance/`). Échantillon vérifié (5 fichiers lus intégralement) : tous **MIT ou Apache-2.0** — conformes à la politique OPSYS. Le reste (~10 fichiers non lus individuellement) est **NON VÉRIFIÉ** ; recommandation : passer un scanner de licence (`pip-licenses`/`scancode`) avant vendoring si ces skills précis sont retenus.

## 3. Architecture réelle (lecture du code)

**Boucle agent** — `run_agent.py` (91 Ko) + `agent/conversation_loop.py` orchestrent un tour : `agent/turn_preflight*.py` → `agent/turn_api_request.py`/`turn_api_call.py` (appel modèle) → `agent/turn_tool_round.py` (dispatch outils) → `agent/turn_finalizer.py`, avec compression de contexte (`context_compressor.py`), cache prompt (`prompt_caching.py`), garde anti-répétition (`repetition_guard.py`), fallback multi-provider (`fallback_cooldown.py`, `credential_pool*.py`). Design très décomposé (~200 fichiers dans `agent/`, un fichier = une préoccupation).

**Outils/toolsets** — `toolsets.py` (racine) définit des groupes nommés d'outils (ex. `_HERMES_CORE_TOOLS` : `web_search`, `terminal`, `read_file/write_file/patch`, `vision_analyze`, `image_generate`, `browser_*`, `text_to_speech`, `memory`, `session_search`, `execute_code`, **`delegate_task`**, `cronjob_manage`, `ha_*` (Home Assistant), `kanban_*`, `computer_use`…). Implémentation dans `tools/` (120k LOC, ~40+ outils).

**Skills** — format = **`SKILL.md`** par dossier (+ `references/`, `templates/`, scripts) — **compatible standard ouvert [agentskills.io](https://agentskills.io)**, le même format que Claude. Deux couches : `skills/` (bundlées, 13 catégories) et `optional-skills/` (22 catégories, catalogue élargi : devops, finance, payments, security, smart-home, mcp, migration…). Hub public = agentskills.io. Auto-amélioration : skills créées/affinées automatiquement après usage (`agent/learn_prompt.py`, `agent/skill_commands.py`).

**Plugins** — extension point générique : `plugins/<kind>/<name>/{__init__.py, plugin.yaml}`, chargés par `plugins/plugin_loader.py` (découverte par dossier, `register(ctx)` ou fallback ABC), à la fois côté dépôt (`plugins/`) et côté utilisateur (`$HERMES_HOME/plugins/`). 18 catégories officielles : `browser, context_engine, cron_providers, dashboard_auth, disk-cleanup, google_meet, hermes-achievements, image_gen, kanban, memory, model-providers, observability, platforms, security-guidance, spotify, teams_pipeline, video_gen, web`. C'est le point d'ancrage naturel pour du code OPSYS.

**MCP — client ET serveur, tous deux présents** :
- *Client* : `tools/mcp_tool*.py` (13 fichiers — discovery, oauth, transport, sampling, lifecycle, schema cache…) ; catalogue pré-configuré de **65 serveurs MCP** dans `optional-mcps/` (Airtable, Atlassian, Cloudflare, Datadog, Dropbox, Figma, GitLab, Grafana, HuggingFace…).
- *Serveur* : `mcp_serve.py` — `hermes mcp serve` expose les conversations Hermes comme outils MCP pour un client externe (Claude Code, Cursor, Codex). Doc en tête de fichier : « Matches OpenClaw's 9-tool channel bridge surface ».

**Sous-agents / délégation** — 3 couches distinctes et bien documentées (`website/docs/user-guide/profiles.md`) :
1. **Profile** = agent persistant complet (config/mémoire/skills/gateway propres, process séparé) — `hermes profile create <nom>`.
2. **Subagent** = enfant éphémère lancé par l'outil `delegate_task` pour UNE tâche, conversation fraîche (`agent/subagent_lifecycle.py`, `agent/delegation_context.py`).
3. **Kanban** = orchestrateur de tâches routées automatiquement vers les profils selon leur `--description` (`kanban_*` tools, `plugins/kanban/`) — mécanisme multi-agents avec board.

**Cron/planificateur** — natif, riche : `cron/scheduler.py` + 15 fichiers dédiés (worker détaché, preflight, diagnostics, file de livraison, gestion des incidents/quota), dépendance `croniter` en cœur (pas une extension).

**Gateway de messagerie** — process unique multi-canal, **canaux confirmés dans le code** (`gateway/platforms/`) : Telegram, Discord, Slack, WhatsApp (Cloud API), Signal, Matrix, Microsoft Teams (`msgraph_webhook.py`), Google Chat, BlueBubbles/iMessage, WeChat (`weixin.py`), QQ (`qqbot/`), Tencent Yuanbao, Home Assistant, **API OpenAI-compatible native** (`api_server_openai_routes.py`), webhook générique. **Email** et **Home Assistant** confirmés par le README/docs. **SMS + téléphonie** = via **skill Twilio** dédiée (`productivity-telephony`, doc `messaging/sms.md`) — outbound/skill-driven, pas un canal gateway natif au même titre que Telegram. Transcription vocale des messages audio (voice notes) intégrée. **Pas de vraie téléphonie IP/SIP entrante native** — à combler côté OPSYS si M1 l'exige strictement (Twilio Voice via la skill couvre l'essentiel : appels sortants/IVR).

**Mémoire** :
- *Intégré (cœur, sans plugin)* : FTS5 SQLite (`hermes_state_fts.py`) + mémoire « curée » par le LLM lui-même dans `MEMORY.md`/`USER.md`, avec nudges périodiques (`agent/curator.py`).
- *Fournisseurs pluggables* (`plugins/memory/`, extension documentée `developer-guide/memory-provider-plugin.md`) : **Honcho** (plastic-labs, modélisation utilisateur « dialectique »), **Mem0** (`mem0/`, vectoriel, backends multiples y compris self-host), **byterover, openviking, holographic, retaindb, supermemory** (services tiers, non audités en détail).
- **Aucune recherche vectorielle native en cœur** — le vectoriel vient exclusivement d'un plugin mémoire (Mem0 étant le plus pertinent pour un RAG self-hosted Postgres/pgvector).
- API pour RAG externe : le contrat de plugin mémoire (`config_schema.py`, `query_rewrite.py`) est le point d'entrée documenté pour brancher un fournisseur maison.

**Persistance** — **SQLite uniquement** côté état-agent (`hermes_state_dbfile.py` importe `sqlite3`, gestion WAL avancée `hermes_state_wal.py`, réparation `hermes_state_repair.py`). **Aucun support Postgres natif détecté** dans le cœur (les rares occurrences de « postgres » trouvées sont dans des *skills* d'exemple, pas dans l'état Hermes). Sans conflit pour OPSYS : les données métier des 10 modules restent dans le Postgres existant, indépendant du `state.db` conversationnel d'Hermes.

**Profils (multi-agents/personas)** — Oui, nativement, cf. ci-dessus (§sous-agents). Chaque profil = home dir isolé (`~/.hermes/profiles/<nom>/`), process gateway propre, alias CLI dédié, peut être exporté/importé/publié comme dépôt git (« Profile Distributions »).

**Web dashboard** — `web/` = SPA React+TypeScript (Vite, `vitest`), **17 pages identifiées** dans `web/src/pages/` qui couvrent quasi tous les besoins OPSYS : `ModelsPage` (modèles/clés/fournisseurs), `ChannelsPage` (canaux), `EnvPage`/`PairingPage` (credentials/appairage), `WebhooksPage`, `McpPage` (**catalogue MCP**), `AnalyticsPage`, `CronPage`, `ProfilesPage`/`ProfileBuilderPage`, `SkillsPage`, `PluginsPage`, `SessionsPage`, `ConfigPage`, `LogsPage`, `SystemPage`, `FilesPage`, `ChatPage`, `DocsPage`. **Le dashboard lui-même est pluggable** : `web/src/plugins/` + `PluginsPage.tsx` → onglets/widgets custom confirmés (exigence explicite du brief). **Auth dashboard** = `plugins/dashboard_auth/` avec **4 providers** : `self_hosted` (**OIDC générique PKCE** — Authentik/Keycloak/Zitadel/Authelia/Auth0/Okta via découverte `.well-known/openid-configuration`), `nous` (OAuth Nous Portal), `basic`, `drain`. **OIDC self-hosted disponible nativement** — répond directement à l'exigence dashboard du brief. Dashboard bind `127.0.0.1` par défaut (accès distant via tunnel SSH ou reverse-proxy — posture sûre par défaut).

**Fournisseurs de modèles** — registre `providers/` (ABC `ProviderProfile`) + **40 plugins `model-providers/`** : cloud (anthropic, openai-codex, gemini, vertex, bedrock, azure-foundry, xai, deepseek, alibaba, minimax, fireworks, deepinfra, nvidia, novita, openrouter, huggingface…) + **`custom/`** (endpoint OpenAI-compatible arbitraire — c'est la voie pour **vLLM/llama.cpp/LM Studio locaux**, confirmé aussi par `agent/lmstudio_reasoning.py`) + **`ollama-cloud/`** (Ollama hébergé — Ollama **local** passe par `custom` via `base_url`). Routage/fallback : `agent/fallback_cooldown.py`, `agent/credential_pool*.py`, `/model` slash-command switch sans redémarrage.

**Économie de tokens** — plusieurs mécanismes natifs : compression de contexte automatique et manuelle (`agent/context_compressor.py`, `conversation_compression*.py`, commande `/compress`), **prompt caching** natif (`agent/prompt_caching.py`, `prompt_cache_boundary.py`, `prompt_cache_scope.py` — gère `cache_control` Anthropic et équivalents), suivi coûts/usage (`agent/usage_pricing.py`, `credits_tracker.py`, `billing_usage.py`, commande `/usage`, `/insights --days N`), `trajectory_compressor.py` dédié. **Pas de système de « budget » dur par département/agent identifié en cœur** (pas de limite de dépense configurable par profil trouvée dans le temps imparti) — à construire côté OPSYS si requis strictement.

**Sécurité** — posture explicitée et honnête dans `SECURITY.md` : *« Hermes Agent is a single-tenant personal agent […] The only security boundary against an adversarial LLM is the operating system »* — l'approval gate et les scanners internes sont traités comme heuristiques, PAS comme frontière de sécurité. Isolation réelle = choix du **terminal backend** : `local, docker, singularity, modal, daytona, vercel_sandbox, ssh` (`tools/terminal_tool_backends.py`, 7 backends). Approbation de commandes (`tools/approval.py`, `agent/terminal_approval_batch.py`), coffre d'identifiants sans exposition au LLM (« password-blind credential vault », release notes v0.21.2 : 1Password/Bitwarden/vault local). Docker officiel : multi-stage, image `debian:13.4` **épinglée par digest sha256**, exécution non-root via s6-overlay + remap UID/GID hôte.

**Multi-utilisateur/multi-tenant** — **auto-déclaré mono-tenant** (`SECURITY.md` §2). « Bot Mode rooms » (`gateway/hosted_rooms*.py`) permettent plusieurs utilisateurs humains dans une même conversation/room, mais c'est du multi-*utilisateur* sur un seul agent/tenant, pas de l'isolation multi-*tenant* (pas de séparation de données par organisation). Pour du SaaS multi-PME, OPSYS devra déployer **une instance Hermes par client** (cohérent avec le modèle VPS mono-nœud visé en phase 1).

**Installation VPS** — `setup-hermes.sh` (installeur source, géré par un package-manager interne « PM », pas de `pip` direct), `docker-compose.yml` (2 services : `gateway` + `dashboard`, `network_mode: host`, volumes `~/.hermes`), `Dockerfile` (multi-stage : build SQLite custom → deps Python → build frontend Node → image finale), doc dédiée `docs/user-guide/security.md`, `docs/getting-started/installation`. Marketing : « Run it on a $5 VPS ». **Empreinte ressources non mesurée directement ici** (pas d'exécution réelle du conteneur dans cette recherche) — **NON VÉRIFIÉ** au-delà de l'affirmation du README ; à valider par un PoC réel avant engagement. Point d'attention architecture : chaque **profil** = process gateway séparé → 10 profils (un par département M1-M10) multiplierait l'empreinte par ~10 ; préférer 1-3 profils + `delegate_task`/kanban pour router en interne (voir §5).

## 4. Adéquation OPSYS

**Mapping M1-M10** : le triptyque **Profile / Subagent(`delegate_task`) / Skill+Toolset** offre plusieurs granularités :
- *Option A (recommandée)* : **1 profil OPSYS unique** (ou 2-3 max, ex. séparant Front Office temps-réel du reste) exposant 10 **toolsets** nommés (un par module M1-M10, cf. `toolsets.py`) + 10 familles de **skills** (`SKILL.md` par procédure métier : qualification M1, scoring M2, Monte Carlo M3…) + **kanban** pour la coordination inter-département. Empreinte process minimale, cohérent avec « core d'entreprise » unique.
- *Option B* : 1 profil par département (isolation forte, alias CLI par département, mémoire/config séparées) — plus proche de « 10 agents » mais coûte 10× le footprint et 10× la supervision (systemd/s6 par profil déjà géré nativement, donc faisable, mais plus lourd).

**Brancher le code métier Python existant (~24k LOC + 41k tests)** — trois voies, non exclusives :
1. **Serveur MCP maison** (recommandé en premier) : envelopper les modules M1-M10 en un ou plusieurs serveurs MCP (stdio/HTTP) exposant leurs fonctions ; Hermes les consomme via son client MCP déjà mature — **aucune modification du cœur Hermes**, immunité totale au churn upstream, mode « service séparé » propre. C'est le mode d'intégration le plus aligné avec la philosophie « ingrédients, pas empilement ».
2. **Plugin `memory` custom** : implémenter le fournisseur mémoire OPSYS (Postgres+pgvector, RAG maison) via le contrat documenté `developer-guide/memory-provider-plugin.md`, en s'inspirant du plugin `mem0` existant (déjà pgvector-compatible — à évaluer avant de tout réécrire).
3. **Skills + script wrapper** : pour des procédures ponctuelles (ex. génération d'un devis M3), une skill avec un script Python appelant directement le module OPSYS via `execute_code`/`terminal`.

**Garder tel quel** : boucle agent, gestion multi-provider + fallback + cache prompt, gateway multi-canal (Telegram/WhatsApp/courriel/chat web/voix-mémo couvrent M1), cron natif (M4/M5 rapports), MCP client/serveur, format skills, terminal-backends sandbox (Docker/SSH pour M4 terrain), dashboard (auth OIDC self-host + pages config/MCP/webhooks/analytics), Docker/installeur VPS.

**Retirer/ignorer** (hors périmètre QC-PME, réduit la surface à maintenir) : canaux QQ/WeChat/Yuanbao/BlueBubbles, plugins `spotify`, `google_meet`, `hermes-achievements`, `teams_pipeline` (sauf si client utilise Teams), la quasi-totalité des `optional-skills` non pertinentes (blockchain, gaming, mlops…), `evals/` (tooling recherche NousResearch), la majorité des 40 model-providers cloud exotiques (garder Anthropic/OpenAI/Gemini/Bedrock/Vertex/OpenRouter/custom-local + Nous éventuellement).

**Modifier/construire** : fournisseur mémoire RAG maison (exigence dure #5 du brief — doc de conception à faire séparément), toolsets M1-M10, skills métier FR-QC (TPS/TVQ, Loi 25), éventuellement un vrai mécanisme de **budgets tokens durs par département** (non trouvé en cœur), durcissement multi-tenant si SaaS multi-PME (une instance par tenant, orchestrée en dehors de Hermes — pas dans Hermes).

**Stratégie de fork — recommandation : dépendance versionnée + plugins, PAS de subtree vendorisé massif.** Vu l'échelle (2,1M lignes Python, ~1 release/semaine, ~1000-5000 commits/fenêtre de release), vendoriser-et-patcher le cœur serait très coûteux à maintenir en synchro. Le design plugin/skill/MCP de Hermes est justement fait pour éviter ça : **installer Hermes en dépendance pinnée sur un tag de release** (ex. `v2026.9.24`), étendre exclusivement via `plugins/`, `skills/`, un serveur MCP maison et `$HERMES_HOME` overrides côté OPSYS (dossier utilisateur, jamais le code vendor). Ne forker le cœur (`agent/`, `hermes_state_*.py`) qu'en dernier recours ciblé, avec patchs minimaux tenus à part.

**Effort** (ordre de grandeur, PoC exclu) :
- Installation + configuration de base (dashboard, 1 profil, providers cloud) : **S**.
- Intégration code métier via serveur(s) MCP maison pour les 10 modules : **M-L** (dépend du nombre de fonctions exposées).
- Fournisseur mémoire RAG Postgres/pgvector maison : **L** (c'est le prérequis explicite « doc de conception » du brief).
- Skills FR-QC + toolsets par département : **M**.
- Durcissement sécurité (budgets, audit approvals) : **S-M**.

**Risques** :
- **Churn upstream très élevé** (des centaines à milliers de commits/fenêtre de release) → toute intégration qui touche des chemins internes (au-delà de l'API plugin publique) risque de casser à chaque mise à jour ; le projet a même un mécanisme officiel de dépréciation d'imports internes (`COMPAT_MANIFEST.md`) qui **confirme** que les chemins internes bougent activement — rester strictement sur les points d'extension publics (plugins/skills/MCP) atténue ce risque.
- **Mono-tenant auto-déclaré** : SaaS multi-PME (objectif phase 2 du produit) nécessitera une instance par tenant, pas un Hermes multi-tenant partagé — à anticiper dans l'architecture de déploiement, pas dans Hermes lui-même.
- **Sécurité "boundary = OS uniquement"** (assumé par le projet) : pour un contexte entreprise (accès banque en lecture, données clients Loi 25), imposera un choix de terminal-backend conteneurisé/isolé strict dès le jour 1, pas le backend `local` par défaut.
- **Empreinte ressources non mesurée** dans cette recherche (affirmation "$5 VPS" non vérifiée par exécution) — à valider par PoC avant engagement budgétaire VPS.
- **Vélocité des chiffres GitHub eux-mêmes** (étoiles/PR/commits) rapportée par la source mais non re-vérifiable indépendamment avec les outils de cette session — traité comme fait de source primaire, pas comme certitude absolue (voir §1).

## 5. Notes par exigence OPSYS (1-5)

| Exigence | Note | Justification (preuve) |
|---|:-:|---|
| VPS (mono-nœud, docker compose, script) | **5** | `docker-compose.yml` (2 services gateway+dashboard), `setup-hermes.sh`, Dockerfile multi-stage production-grade, doc dédiée. Empreinte réelle non mesurée ici (léger bémol). |
| Dashboard config totale (modèles/clés/fournisseurs/canaux/credentials/webhooks/MCP/analytics/OIDC/plugins) | **5** | 17 pages `web/src/pages/` couvrant explicitement chaque item du brief ; auth OIDC self-host native (`plugins/dashboard_auth/self_hosted/`) ; dashboard lui-même pluggable (`web/src/plugins/`). |
| Économie de tokens (compression, cache, coûts, budgets) | **4** | Compression contexte + prompt caching natifs + suivi coûts/usage riches et confirmés en code ; absence constatée d'un système de **budgets durs** configurables par agent/département (à construire). |
| Base source forkable (mature, licence compatible) | **4** | MIT confirmé, très actif, très documenté, architecture plugin exemplaire — mais taille/churn tels qu'un fork classique (subtree+patch massif) est déconseillé ; note tempérée par cette réserve stratégique plutôt que par la qualité intrinsèque. |
| Mémoire/RAG | **3** | Cœur = FTS5 + mémoire curée LLM seulement (pas de vecteurs natifs) ; RAG vectoriel = toujours un plugin tiers (Mem0/Honcho/autres, non audités en détail) ; interface plugin mémoire bien documentée pour brancher un RAG maison — correspond exactement au besoin « doc de conception prérequis » du brief plutôt qu'à une solution clé en main. |
| Capacités par département (M1-M10) | **4** | Couverture directe forte pour M1 (gateway omnicanal quasi complète), M4 (terminal/cron/approvals), M9 (kanban/subagents/profils) ; nécessite construction pour M3 (vision/Monte Carlo métier), M5 (compta/banque), M6/M8 — mais tous branchables proprement via MCP/skills. |
| Intégration code Python existant | **4** | Client MCP mature + `execute_code`/`terminal` + skills avec scripts = plusieurs voies propres et non intrusives ; aucun exemple officiel « import direct comme module » trouvé (le pattern privilégié par le projet est MCP/plugin, pas l'import Python direct dans `agent/`). |
| Sécurité (sandbox, approbations, isolation) | **4** | 7 backends terminal dont conteneurs/cloud-sandbox, approbations de commandes, coffre d'identifiants "password-blind", posture documentée avec franchise (`SECURITY.md`) ; note non-5 car le projet lui-même dit que la seule vraie frontière est l'OS — donc la rigueur du déploiement OPSYS portera l'essentiel de la charge. |
| Licence | **5** | MIT racine vérifié à deux reprises par sources indépendantes ; échantillon de sous-licences embarquées 100% MIT/Apache-2.0 dans les 5 fichiers lus. Reste des sous-licences non exhaustivement audité (mineur). |

## 6. INGRÉDIENTS RETENUS (classés) + RECETTE

**RETENIR (cœur, tel quel, en dépendance pinnée)** :
1. Runtime agent + boucle + multi-provider/fallback/cache (`agent/`, `providers/`, `run_agent.py`).
2. Gateway multi-canal (`gateway/`) — Telegram/WhatsApp/courriel/chat web/voix pour M1 Front Office.
3. Cron natif (`cron/`) — rapports M5/M8, relances M2.
4. MCP client + serveur (`tools/mcp_*`, `mcp_serve.py`) — porte d'entrée du code métier OPSYS.
5. Format skills (`SKILL.md`, agentskills.io) + toolsets (`toolsets.py`) — pour procédures FR-QC.
6. Dashboard web + son auth OIDC self-host + son système de plugins (`web/`, `plugins/dashboard_auth/self_hosted/`).
7. Terminal backends sandboxés (`tools/terminal_tool_backends.py`) pour M4 (Docker/SSH).
8. Docker/installeur VPS (`docker-compose.yml`, `Dockerfile`, `setup-hermes.sh`).

**ADAPTER/CONSTRUIRE (côté OPSYS, hors cœur Hermes)** :
9. Serveur(s) MCP maison enveloppant les 10 modules Python/Postgres existants.
10. Plugin mémoire RAG maison (Postgres+pgvector), à documenter d'abord (exigence dure #5), en s'inspirant du plugin `mem0` existant.
11. Toolsets + skills métier par département M1-M10 (mapping via **1-3 profils + `delegate_task`/kanban**, pas 10 profils séparés).
12. Budgets tokens durs par département (absent du cœur).

**RETIRER/IGNORER** : canaux QQ/WeChat/Yuanbao, plugins `spotify`/`google_meet`/`hermes-achievements`, `evals/` (recherche NousResearch), la majorité des `optional-skills` et `model-providers` exotiques non pertinents pour une PME QC.

**RECETTE (ordre d'exécution suggéré)** : (1) PoC VPS 1 profil + dashboard + 1 provider cloud + mesure empreinte réelle → (2) doc de conception RAG (exigence #5) → (3) plugin mémoire Postgres/pgvector → (4) serveur MCP OPSYS exposant M1-M10 (départ M7, déjà scopé par le projet en cours) → (5) skills FR-QC (TPS/TVQ, Loi 25) + toolsets par département → (6) durcissement sécurité (terminal-backend conteneurisé par défaut, budgets tokens) → (7) évaluation SaaS multi-tenant = multi-instance orchestrée, hors Hermes.
