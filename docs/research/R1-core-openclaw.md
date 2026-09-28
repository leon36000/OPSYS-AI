# R1 — OpenClaw comme base du code source d'OPSYS-CORE

Sources primaires : clone local `--depth 1` de `openclaw/openclaw` (HEAD `2d39f2f7`, 2026-09-27) et de
`Agnuxo1/OpenCLAW-2` (HEAD `1e9b30f`, 2026-06-15), tous deux conservés dans
`scratchpad/clones/`. Lecture directe du code, pas seulement des README. Compléments : pages GitHub
publiques et presse sécurité spécialisée (liens en fin de section concernée).

---

## 1. Identification précise de « openclaw2 »

**`Agnuxo1/OpenCLAW-2`** (https://github.com/Agnuxo1/OpenCLAW-2)
- **Ce que c'est, vérifié par le code** : `package.json` déclare `"name": "openclaw"`,
  `"repository": "git+https://github.com/openclaw/openclaw.git"`, `LICENSE` = MIT *Copyright (c) 2025
  Peter Steinberger* (texte identique à celui du vrai dépôt) — c'est une **copie vendorisée non mise à
  jour** du vrai OpenClaw (dernier commit inclus : 2026-06-15, donc ~3 mois de retard), sur laquelle le
  propriétaire a empilé ses propres projets persos à la racine : `P2P-system/`, `OpenCLAW-P2P-Launch/`,
  `p2pclaw-v1/`, `p2pclaw-mcp-server/`, `literary-agent-autonomous/`, `moltbook-agent-standalone/`,
  `openclaw-hive-skill/`, `HIVE_SUPER_PROMPT.md`, `papers/`, plus un `repos/` contenant des **dossiers
  vides** (`OpenCLAW-2-Literary-Agent/`, `OpenCLAW-2-moltbook-Agent/`, `ASIC-RAG-CHIMERA/`, etc.) et un
  `gh.zip` de 13 Mo commité brut. Un seul committer shallow : *Francisco Angulo de Lafuente*.
- **Lien réel avec OpenClaw** : aucun (pas listé comme fork GitHub — vérifié par lecture de la page :
  « does not appear to be forked from another repository »). C'est une copie manuelle, pas une relation
  officielle avec l'OpenClaw Foundation.
- **Maturité (vérifiée, page GitHub)** : **10 ⭐ / 5 forks**. Compte GitHub `Agnuxo1` = auteur prolifique
  d'une constellation de ~57 dépôts « OpenCLAW-2-* » à noms grandiloquents (plateforme de recherche
  scientifique autonome, agent littéraire, réseau P2P décentralisé avec « tribunal IA », papiers arXiv
  auto-publiés) — profil caractéristique d'un labo perso plutôt que d'un produit maintenu.
- **Verdict** : **ce n'est pas une base sérieuse**. À ignorer comme candidat de fork ; le nom
  « openclaw2 » du propriétaire désigne très vraisemblablement le **vrai projet OpenClaw en versions
  CalVer 2026.x** (le brief le confirme d'ailleurs explicitement), probablement confondu avec ce dépôt
  personnel trouvé en recherchant « openclaw 2 ».

**`openclaw/openclaw`** (https://github.com/openclaw/openclaw) — **la cible réelle**
- **391 000 ⭐ / 82 200 forks / 101 357 commits** (page GitHub, vérifié). `package.json` :
  `"version": "2026.9.6"` (CalVer), `LICENSE` MIT *Copyright (c) 2026 OpenClaw Foundation*. Dernier
  commit du dépôt cloné : **2026-09-27** (veille du jour de rédaction) — cadence quasi quotidienne.
  Gouvernance : OpenClaw Foundation, 501(c)(3) indépendante, donateurs incluant Amazon, OpenAI, Red Hat
  (page GitHub). Origine : prototype de Peter Steinberger (nov. 2025), passé à la Foundation le
  14/02/2026. C'est la base à utiliser.

---

## 2. Clone et mesures (openclaw/openclaw, dépôt conservé dans `scratchpad/clones/openclaw`)

| Mesure | Valeur | Méthode |
|---|---|---|
| Taille checkout (hors `.git`) | ~736 Mo (`.git` 167 Mo, total 903 Mo) | `du -sh` |
| Fichiers suivis par git | 50 240 | `git ls-files \| wc -l` |
| LOC brut (ts/tsx/js/mjs/cjs/mts/rs/swift/kt/py/go) | **~12,6 M lignes** tous langages | `git ls-files` + `cat` + `wc -l` (comptage brut, inclut tests et `.d.ts`, pas un `cloc` nettoyé) |
| … dont `src/` | ~6,52 M | idem, par répertoire |
| … dont `extensions/` (171 extensions) | ~2,66 M | idem |
| … dont `ui/` (dashboard) | ~1,25 M | idem |
| … dont `apps/` (natif macOS/iOS/Android) | ~0,75 M | idem |
| … dont `test/` (racine, hors tests colocalisés) | ~0,73 M | idem |
| … dont `scripts/` | ~0,41 M | idem |
| … dont `packages/` (25 paquets partagés) | ~0,235 M | idem |
| … dont `crates/` (2 crates Rust) | ~0,016 M | idem |
| Fichiers `*.test.ts` / `*.spec.ts` | **18 542** | `git ls-files` regex |
| Occurrences `it(`/`test(` (proxy nb de cas) | **~135 144** sur 16 372 fichiers | `rg -c` |
| Langages | TypeScript (41 320 fichiers, cœur), Swift (1 368, apps Apple), Kotlin (601, Android), Python (62), Rust (59, `crates/openclaw-gateway-client`, `openclaw-node-host`), Go (30) | `git ls-files` par extension |
| Licence | **MIT**, `LICENSE` vérifié + `THIRD_PARTY_NOTICES.md` (67 lignes) : uniquement attributions MIT (Pi/pi-mono, GitHub Octicons). **Aucune trace GPL/AGPL** (`grep -i gpl` = vide) | lecture directe |
| Monorepo | pnpm workspaces : `.` + `ui` + `packages/*` + `extensions/*` + `examples/*` (`pnpm-workspace.yaml`) | lecture |
| Dépendances runtime racine | 65 `dependencies` directes (dont `@modelcontextprotocol/sdk`, `@anthropic-ai/sdk`, `openai`, `@mistralai/mistralai`, `@google/genai`, `playwright-core`, `express`, `kysely`, `chrome-devtools-mcp`, `@trycua/cua-driver`) + 62 devDeps | `package.json` |
| Dépendances lourdes notables | LanceDB (vecteurs, via extension), `better-sqlite`/`node:sqlite` natif, `onnxruntime-node` (build désactivé par défaut), `sharp`/`rastermill` (images), Playwright/Chrome DevTools MCP (navigateur), Baileys (WhatsApp, patché) | `pnpm-workspace.yaml` overrides/patches |
| Node requis | `>=24.16.0 <25 \|\| >=26.1.0` | `package.json engines` + `SECURITY.md` |
| Supply-chain | `minimumReleaseAge: 10080` (cooldown npm de 7 jours) + `patchedDependencies` sur 7 paquets + overrides de versions vulnérables épinglées | `pnpm-workspace.yaml` |

**Note méthodologique** : le LOC total (~12,6 M) est un **comptage brut multi-plateforme** (Node/TS +
apps natives Swift/Kotlin + Rust), pas un LOC « produit livré » — le binaire Gateway réellement déployé
sur un VPS est un seul process Node (`dist/index.js`), bien plus compact ; voir empreinte ressources §3.

---

## 3. Architecture réelle (code lu, pas seulement doc)

- **Gateway** (`src/gateway/`, ~85 fichiers hors tests) : control-plane HTTP+WebSocket unique. Auth par
  secret partagé (`token`/`password`), bind par défaut **loopback**. Expose aussi des endpoints
  compatibles OpenAI (`/v1/chat/completions`, `/v1/responses`) et `/tools/invoke`.
- **Boucle agent** : runtime intégré dans `src/agents/embedded-agent-runner/` (boucle de tentatives,
  sélection modèle, compaction) + paquet réutilisable `packages/agent-core` (`@openclaw/agent-core`).
  Abstraction « **harness** » pluggable (`src/agents/harness/`) : runtime natif `openclaw`, ou harnais
  externes enregistrés — **Codex app-server** (OpenAI), **Copilot SDK**, **Claude Code CLI** — le tout
  documenté dans `docs/agent-runtime-architecture.md`.
- **Outils / Skills / Plugins-Extensions** : trois couches distinctes. *Tools* = fonctions typées
  natives (`src/agents/agent-tools*.ts`). *Skills* = Markdown avec métadonnées (`skills/`, 50 au
  premier niveau, chargées à la demande). *Extensions* = 171 paquets pnpm (`extensions/*`), chacun avec
  son `openclaw.plugin.json` — fournisseurs de modèles, canaux, mémoire, etc. **Confiance** : extensions
  chargées **in-process**, **non sandboxées**, même privilège OS que la Gateway (`SECURITY.md` §Trusted
  Plugins) — point de vigilance majeur (§4/§5).
- **MCP** : support natif **bidirectionnel**, profond (`src/mcp/*`, `src/agents/mcp-*`, page dashboard
  dédiée). Client MCP : transports **stdio, Streamable HTTP, SSE**, OAuth pour serveurs distants
  (`src/agents/mcp-oauth.ts`). Serveur MCP : OpenClaw expose ses propres outils/canaux en MCP
  (`plugin-tools-serve.ts`, `tools-stdio-server.ts`). C'est exactement le point d'ancrage pour le code
  métier Python d'OPSYS (§4).
- **Sous-agents / multi-agent** : `sessions_spawn` natif (`docs/tools/subagents/`), plusieurs agents
  configurables (`agents.entries.*`) dans une même Gateway, ownership/attribution de session par
  personne (`docs/concepts/multi-user.md`). Isolation forcée possible via `sandbox: "require"`.
  Sous-système `src/fleet/` (« fleet cells », multi-tenant par conteneur) existe mais est coté
  **Alpha** (67 % qualité, 71 % complétude) par le scorecard officiel — **immature, à ne pas fonder
  dessus aujourd'hui**.
- **Planificateur/cron** : `src/cron/` natif (jobs, gestion conversationnelle par un admin, tests
  dédiés `cron-*.test.ts`). Bon candidat pour déclencher M4→M5/M6/M2/M7/M8/M10.
- **Canaux** (pertinents front office) : **WhatsApp**, **Telegram**, **SMS** (via Twilio, vérifié dans
  `extensions/sms/src/*.ts`), **IMAP** (courriel entrant, automatisation dédiée
  `/automation/imap`), **chat web natif** (`src/channel-web.ts`, doc `docs/web/webchat.md`),
  **voix/téléphonie** (`voice-call`, `talk-voice`), plus Discord/Slack/Teams/Google Chat/Matrix/Line/
  Feishu/Zalo (moins utiles pour un front office PME QC).
- **Mémoire / RAG** : architecture propriétaire sophistiquée. `extensions/memory-lancedb` = mémoire
  long-terme officielle sur **LanceDB** (vecteurs embarqués, `memory_store/recall/forget`, embeddings
  configurables, sanitisation à la capture). `extensions/memory-core` (~90 fichiers) ajoute un cycle
  complet : promotion court→long terme, consolidation périodique (« dreaming », cron dédié),
  **`memory_forget` avec tombstones** (traçabilité de suppression — utile Loi 25), « standing
  intents ». Noté **Beta 75 %/76 %** par le scorecard officiel — fonctionnel, pas encore « stable ».
- **Persistance** : **SQLite uniquement**, deux bases (`docs/reference/database-schemas/layout.md`) :
  control-plane partagé (`~/.openclaw/state/openclaw.sqlite`) + plan de données par agent
  (`~/.openclaw/agents/<id>/agent/openclaw-agent.sqlite`, y compris sessions/mémoire/transcripts).
  **Aucun support Postgres natif** → cohabitation à architecturer avec le Postgres métier d'OPSYS
  (deux couches de persistance séparées, communication uniquement via API/MCP, pas de DB partagée).
- **Control UI / dashboard** : SPA (Lit/web components, patchs `lit-analyzer`/`webawesome` en
  atteste). Fonctions vérifiées dans `docs/web/control-ui/settings.md` : **Settings** (comptes/clés par
  fournisseur de modèle, agents, canaux), **page MCP dédiée** (ajout/activation de serveurs MCP
  stdio/HTTP/SSE directement dans l'UI), gestion des **plugins**, **Sessions/Activity** (ownership,
  présence, mentions), import de mémoire depuis Claude Code/Codex/Hermes. Un skill `control-ui` permet
  même à un agent de **construire ses propres widgets de dashboard** (pertinent pour M8 Analytics).
- **Fournisseurs de modèles** : catalogue extrêmement large (`extensions/`) — cloud : anthropic,
  openai, google, amazon-bedrock, azure, cohere, mistral, deepseek, groq, together, xai, qwen, etc.
  (~50). **Locaux/OpenAI-compatible confirmés** : `ollama`, `lmstudio`, `llama-cpp`, `vllm`, `sglang`,
  `onnx` — endpoint générique OpenAI-compatible également supporté. Extension `litellm` native (peut
  pointer vers le **même routeur LiteLLM** qu'OPSYS utilise déjà pour ses `crew-*`).
- **Économie de tokens** : la fonctionnalité la plus mature du projet. **Prompt caching** implémenté et
  testé en direct (régression live CI) sur Anthropic/OpenAI/Gemini/Bedrock-Nova/OpenRouter/DeepInfra/
  Qwen, avec `cacheRetention` par agent/modèle, cache-TTL pruning, heartbeat keep-warm. **Compaction**
  et troncature dynamique des résultats d'outils selon la fenêtre de contexte (16k/32k/64k car., cap à
  30 % du contexte). **Suivi des coûts** natif (`models.providers.*.cost`, tarification par palier,
  `/usage cost`). Plugin optionnel **`tokenjuice`** (compacte les sorties bash/exec bruyantes). Extension
  **`clawrouter`** (routage multi-fournisseur + reporting de quotas).
- **Sandbox** : multi-backend (`docs/gateway/sandboxing/` : Docker, Podman, SSH, « crabbox », « openshell »)
  mais **désactivé par défaut** (`agents.defaults.sandbox.mode = "off"`, exécution host-first) — à
  activer explicitement en production. Code Mode (exécution JS des outils) : exécuteur `node:vm` (non
  isolant) par défaut, exécuteur **QuickJS-WASM** disponible pour un vrai bac à sable.
- **Sécurité — posture actuelle** : `SECURITY.md` (397 lignes) très mature : CodeQL + OpenGrep(Semgrep)
  + scanner de secrets en CI, cooldown de dépendances 7 jours, image Docker non-root + `--cap-drop`,
  process GHSA actif avec ingénieurs sécurité nommés (NVIDIA, Tencent cités). **Modèle de confiance
  explicite : mono-opérateur / non multi-tenant** — tout appelant authentifié = opérateur complet ;
  toute extension installée = confiance OS complète.
- **Sécurité — incidents/CVE 2026 (vérifiés, sources indépendantes)** : **CVE‑2026‑25253** (CVSS 8.8,
  RCE zero-click par vol de token via paramètre `gatewayUrl` du Control UI), découverte fin janvier 2026,
  40 000+ instances exposées au moment de la divulgation (03/02/2026), **corrigée en 2026.1.29**
  ([runZero](https://www.runzero.com/blog/openclaw/),
  [The Hacker News](https://thehackernews.com/2026/05/four-openclaw-flaws-enable-data-theft.html),
  [avis Université de Toronto](https://security.utoronto.ca/advisories/openclaw-vulnerability-notification/)).
  Campagne **« ClawHavoc »** sur le marketplace **ClawHub** : 335-341 skills malveillants sur ~2 857,
  12 comptes compromis, 1 184 uploads, ~247 000 installations, ~2,3 M$ de cryptoactifs volés (malware
  AMOS), skills usurpant des marques (ByBit, Polymarket…)
  ([The Hacker News](https://thehackernews.com/2026/02/researchers-find-341-malicious-clawhub.html),
  [Unit42/Palo Alto](https://unit42.paloaltonetworks.com/openclaw-ai-supply-chain-risk/)). Ces deux
  incidents datent de la phase de croissance virale (~2 mois après le lancement) et sont antérieurs au
  transfert à la Foundation (14/02/2026) — cohérent avec le durcissement observé depuis (cooldown npm,
  SECURITY.md détaillé). Des compteurs agrégés « 138 » à « 543 CVE » circulent sur des blogs SEO de
  fiabilité non établie — **NON VÉRIFIÉ**, traité avec prudence, à ne pas citer tel quel.
- **Multi-utilisateur/multi-tenant** : `docs/concepts/multi-user.md` confirme un mode multi-personnes
  **au sein d'une même frontière de confiance** (attribution de session, mentions) mais répète que ce
  n'est **pas une frontière de sécurité**. Recommandation officielle explicite : **une Gateway par
  client/tenant** (VPS ou hôte séparé), jamais une Gateway partagée entre entités non mutuellement
  confiantes.
- **Déploiement VPS** : `docs/vps.md` documente 14 fournisseurs (DigitalOcean, Hetzner, Oracle Free
  Tier ARM 24 Go RAM, Fly.io, GCP, AWS, Raspberry Pi…), `docker-compose.yml` officiel (ports 18789/
  18790, healthcheck, `cap_drop: NET_RAW/NET_ADMIN`, `security_opt: no-new-privileges`), systemd via
  `openclaw onboard --install-daemon`, plus guides Ansible et Kubernetes/Kustomize.
- **Empreinte ressources (vérifié dans la doc)** : minimum absolu **1 vCPU / 1 Go RAM / ~500 Mo disque**
  (image pré-construite) ; **4 Go RAM confortable** pour Gateway + un node ; une **construction locale**
  de l'image nécessite ≥6 Go RAM (évitable avec l'image officielle pré-construite `node:24-bookworm-slim`
  épinglée par digest SHA256).
- **Scorecard de maturité officiel** (`docs/maturity/scorecard.md`, généré depuis `taxonomy.yaml` +
  `qa/maturity-scores.yaml`, 50 surfaces / 280 zones) — **score global 68 % (bande « Alpha »)**, mais
  très inégal et pertinent pour trier : **CLI = Stable (qualité 83 %, complétude 90 %)** ; **Gateway
  runtime = Stable (80 %/88 %)** ; **Linux Gateway host = Stable (75 %/89 %)** ; Agent Runtime = Beta
  (78 %/79 %) ; Control UI = Beta (74 %/79 %) ; Plugins = Beta (72 %/79 %) ; Sécurité/auth = Beta
  (72 %/79 %) ; canaux WhatsApp/Telegram/Slack = Alpha (66-68 % qualité) ; Fleet/conteneurs = Alpha
  (67 %/71 %). **Le cœur pertinent pour un déploiement VPS d'entreprise (Gateway + CLI + Linux host)
  est justement la partie la plus mature du projet.**

---

## 4. Adéquation OPSYS

**Mapping M1–M10** (résumé ; détail canaux/mémoire déjà en §3) :
- **M1 Front Office** : correspondance quasi directe — WhatsApp/SMS(Twilio)/IMAP/chat-web/voix natifs.
- **M2 Revenue CRM / M6 Material Control** : orchestration côté agent OpenClaw, logique métier (Postgres)
  100 % dans un serveur MCP Python d'OPSYS ; OpenClaw ne fait qu'appeler les outils exposés.
- **M3 Estimation** : OpenClaw gère l'intake photo multicanal ; le calcul (échelle, Monte Carlo, prix
  plancher) reste en Python, appelé en MCP avec l'image en pièce jointe.
- **M4 Field Ops** : `src/cron/` déclenche ; le fan-out réel (Work Completion Trigger → M2/M5/M6/M7/M8/M10)
  reste orchestré côté Python (OpenClaw n'est qu'un déclencheur/canal de notification).
- **M5 FinanceCore** : la frontière lecture-seule→dry-run→écriture-approuvée (T3 humain, ADR méthode)
  s'appuie sur les **exec approvals**/politiques d'outils natives d'OpenClaw pour le geste humain, mais
  l'écriture Postgres réelle reste dans le MCP Python, jamais dans une extension TS.
- **M7 Marketing** : bénéficie des canaux + mémoire ; Postiz (mentionné au brief) et Google Business
  Profile restent des sidecars/MCP séparés, pas des extensions OpenClaw existantes.
- **M8 Analytics** : extensions `diagnostics-otel`/`diagnostics-prometheus` peuvent nourrir le pipeline
  DuckDB/Parquet d'OPSYS ; le skill `control-ui` permet un rendu de dashboards partagé.
- **M9 Strategic Intelligence** : multi-agent natif (plusieurs `agents.entries`, harnais différents par
  agent) = bon substrat pour un « conseil » multi-agents.
- **M10 Mémoire** : le sous-système `memory-core`/`memory-lancedb` EST quasiment un M10 pré-construit
  (dreaming = POSTFLIGHT, standing-intents, tombstones) — à réutiliser/étendre plutôt que réécrire.

**Intégration du code métier Python** : **MCP stdio (ou HTTP pour services partagés) est le mode
recommandé**, natif des deux côtés, sans adaptation d'OpenClaw nécessaire, configurable depuis la page
MCP du dashboard. À éviter : écrire la logique métier comme extension TypeScript in-process (confiance
totale, non testable en Python, non aligné avec la stack 24k LOC existante).

**Garder / retirer / modifier** : garder Gateway+CLI+Control UI+MCP+mémoire+canaux+cron (cœur « Stable »
du scorecard). Retirer/ne jamais activer côté build : extensions non pertinentes pour un front-office QC
(ex. Zalo, Line, Nostr, Tlon…) — le build Docker accepte `OPENCLAW_EXTENSIONS` pour ne compiler que le
nécessaire. Modifier : rien en profondeur dans `src/` — passer par config, skills Markdown, et au
maximum de petites extensions maison pour du glue-code (jamais la logique métier).

**Stratégie de fork recommandée** : **dépendance vendorisée épinglée (subtree sur tag de release)**,
PAS un fork profond de `src/`. Justification : 101 357 commits, ~cadence quotidienne, migrations de
schéma déjà en version 19/23 — un fork divergent de `src/` générerait un coût de merge continu et
disproportionné face à un besoin qui se satisfait entièrement de config + skills + MCP. Réserver les
patches locaux (diffs minimes trackés) au cas rare d'un point d'extension manquant. Mise à jour
délibérée (mensuelle), jamais sur `main`/`dev`.

**Effort estimé** : S (jours) — VPS Docker Compose + canaux M1 + dashboard modèles. M (1-3 semaines) —
premiers serveurs MCP Python (M2/M5 dry-run) + politiques d'outils par agent + export OTel→M8. L (mois) —
couverture MCP des 10 départements, durcissement sécurité (sandbox on, audit provenance skills),
automatisation multi-VPS pour la phase SaaS multi-tenant.

**Risques** : (1) churn upstream élevé → gouvernance de mise à jour obligatoire ; (2) historique CVE/
supply-chain réel en 2026 (RCE + ClawHub) → n'installer **aucun skill ClawHub tiers non audité** en
production, activer le sandbox, suivre `openclaw security audit --deep` ; (3) modèle mono-tenant
strict → la phase SaaS multi-PME exige une Gateway/VPS par client, pas de mutualisation ; (4) confiance
totale des extensions in-process → toute extension maison doit être revue comme du code cœur ; (5) deux
piles de persistance (SQLite OpenClaw / Postgres OPSYS) → sauvegarde combinée à scripter.

---

## 5. Notes par exigence OPSYS (1-5, preuve à l'appui)

| Exigence | Note | Justification |
|---|---:|---|
| VPS (installable, docker compose, script) | **5/5** | `docs/vps.md` (14 fournisseurs), `docker-compose.yml`+`Dockerfile` officiels durcis (non-root, cap_drop, digests épinglés), systemd `onboard --install-daemon`, fonctionne dès 1 Go RAM (`docs/install/raspberry-pi.md`, `docs/help/faq-first-run/*`). |
| Dashboard / config modèles-clés-canaux-sessions | **5/5** | `docs/web/control-ui/settings.md` : comptes par fournisseur, page MCP dédiée, gestion plugins/canaux, sessions/activité/ownership — tout vérifié en lisant la doc produit. |
| Économie de tokens | **5/5** | Prompt caching multi-fournisseurs avec tests de régression live, cache-TTL pruning, tracking de coût par modèle/palier, plugin `tokenjuice`, extension `clawrouter` (`docs/reference/prompt-caching.md`, `docs/reference/token-use.md`). |
| Base source forkable (mature, licence, gouvernance) | **4/5** | MIT, 391k★, Foundation 501(c)3, mais churn massif (101k commits) et incident sécurité 2026 documenté → fork profond déconseillé, dépendance épinglée recommandée à la place (−1). |
| Mémoire / RAG | **5/5** | `memory-lancedb` (vecteurs) + `memory-core` (dreaming, forget-tombstones, standing-intents) lus dans le code ; noté Beta 75-76 % par le scorecard officiel — sophistiqué et fonctionnel, au-delà d'un RAG basique. |
| Capacités par département (M1-M10) | **4/5** | Excellent pour M1/M10/M9/M8 (canaux, mémoire, multi-agent, OTel) ; M3/M5/M6 nécessitent la logique Python d'OPSYS derrière MCP (attendu, mais pas « fourni » par OpenClaw) (−1). |
| Intégration Python (MCP) | **5/5** | MCP natif bidirectionnel (`src/mcp/*`), stdio/HTTP/SSE, OAuth, page dashboard dédiée — correspond exactement au besoin sans adaptation. |
| Sécurité | **3/5** | Posture actuelle mature (CI CodeQL/Semgrep, cooldown deps, non-root Docker) MAIS CVE-2026-25253 (RCE, CVSS 8.8) + campagne ClawHavoc (341 skills malveillants, 2,3M$ volés) vérifiés en 2026, et modèle non-multi-tenant explicite exigeant une discipline opérationnelle stricte. |
| Licence | **5/5** | MIT vérifié (`LICENSE`), `THIRD_PARTY_NOTICES.md` sans GPL/AGPL — pleinement compatible contrainte commerciale OPSYS. |

**Moyenne : 4,6/5 — recommandation forte** d'adopter `openclaw/openclaw` (pas `Agnuxo1/OpenCLAW-2`) comme
base, en dépendance vendorisée épinglée + intégration métier via MCP Python, jamais en fork profond du
cœur TypeScript.
