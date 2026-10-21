# R3 — Passerelle de modèles (cloud + locaux) et économie de tokens pour OPSYS-AI

Date : 2026-09-28. Méthode : licences vérifiées sur le fichier `LICENSE` brut de chaque dépôt
(`raw.githubusercontent.com`, contourne le blocage de `api.github.com`/`github.com` dans cette
session — voir note technique en fin de document), lecture de code source pour Hermes Agent
(clone local `NousResearch/hermes-agent`, complet) et OpenClaw (clone local `openclaw/openclaw`,
complet), et recherches web datées 2026 pour les faits changeants (pricing, statut de maintenance,
modèles locaux). Tout ce qui n'a pas pu être vérifié à la source est marqué **NON VÉRIFIÉ**.

---

## 0. Résumé exécutif

- **Passerelle réseau retenue : LiteLLM Proxy** (cœur MIT), en conteneur docker-compose sur le VPS,
  comme point d'entrée unique OpenAI-compatible pour les 10 modules. Alternative de repli : **Bifrost**
  (Apache-2.0, binaire Go unique, cache sémantique natif) si l'empreinte Postgres/Redis de LiteLLM
  s'avère trop lourde pour le tier VPS du client.
- **Deux couches, pas une seule** : (A) logique *in-process* par agent — cache-prompt, compaction de
  contexte, élagage des sorties d'outils, routage par tâche vers un modèle auxiliaire bon marché —
  vendorisée en Python depuis **Hermes Agent** (MIT, même stack Python 3.12 qu'OPSYS) ; (B) passerelle
  réseau partagée — budgets/clés virtuelles par département, cache Redis exact+sémantique de second
  niveau, dashboard admin — assurée par LiteLLM.
- **RouteLLM, GPTCache et TensorZero sont rejetés comme dépendances** : vérifiés à l'instant T comme
  abandonnés/archivés (RouteLLM : dernier commit août 2024 ; GPTCache : dernière release 0.1.40, août
  2023 ; TensorZero : dépôt archivé le 12 juin 2026). Leurs *concepts* (routage par classifieur,
  cache sémantique) sont réutilisés via d'autres briques activement maintenues.
- **LM Studio exclu** : licence propriétaire (Element Labs, Inc.), interdit explicitement l'usage
  « as a hosted service for third parties » — incompatible avec un SaaS PME sur VPS headless.
  Utiliser Ollama / llama.cpp / vLLM pour l'exécution locale.
- Hermes Agent et OpenClaw gèrent déjà, en production, à peu près tout ce que demande la mission
  (cache-prompt multi-fournisseurs, compaction de contexte, fallback en cascade, budgets/coûts,
  démarrage à la demande de serveurs locaux). La majeure partie du travail R3 est donc de **porter**
  ces mécanismes plutôt que de les réinventer — cf. §7.

---

## 1. Passerelles (gateways)

| Brique | URL | Licence (vérifiée) | Langage | Maturité | Apport OPSYS | Intégration | Effort | Risques |
|---|---|---|---|---|---|---|---|---|
| **LiteLLM (proxy+SDK)** | github.com/BerriAI/litellm | **MIT** pour tout le dépôt sauf `enterprise/` (licence distincte déclarée dans le `LICENSE` racine — le fichier `enterprise/LICENSE` renvoie 404 à ce commit, **NON VÉRIFIÉ** son contenu exact ; ne pas activer de fonctionnalité estampillée « enterprise » sans revérifier) | Python (cœur), Rust (couche perf optionnelle) | Très active, 140+ providers, standard de facto (citée comme dépendance par Hermes et OpenClaw) | Virtual keys + budgets hiérarchiques (par équipe/agent/modèle), admin UI `/ui`, cache exact+sémantique intégré, fallback multi-fournisseurs, callbacks vers Langfuse | Service sidecar docker-compose (image officielle + Postgres + Redis) | S (déploiement) / M (intégration budgets par département) | Nécessite Postgres pour la concurrence budgets/clés (SQLite déconseillé en prod) ; dossier `enterprise/` à éviter |
| **Portkey Gateway (OSS)** | github.com/Portkey-AI/gateway | **MIT** (vérifié) | TypeScript | Active, 250+ providers revendiqués | Guardrails de contenu par requête, config-driven routing | Service sidecar | M | Cache sémantique et certains guardrails **cloud-tier uniquement** d'après les comparatifs 2026 (le OSS self-hosted en fait moins que l'offre gérée) — affaiblit l'intérêt en self-host pur |
| **Bifrost (maximhq)** | github.com/maximhq/bifrost | **Apache-2.0** (vérifié) | Go | Active (v1.6.4 citée en 2026), ~20+ providers (moins large que LiteLLM) | Binaire unique, quasi sans dépendances externes, **cache sémantique natif** (LiteLLM et Kong ne l'ont pas nativement selon comparatifs 2026) | Un seul conteneur, aucune base de données requise | S | Couverture fournisseurs plus étroite ; un comparatif indépendant (enterpilot.io, 2026) mesure une latence ajoutée supérieure à LiteLLM/Portkey — à re-benchmarker en conditions OPSYS avant arbitrage définitif |
| **OpenRouter** | openrouter.ai (service, pas de dépôt à auto-héberger) | N/A (SaaS) | — | Agrégateur multi-fournisseurs déjà utilisé comme *provider* par Hermes et OpenClaw | Utile comme un fournisseur de plus derrière la passerelle, pas comme la passerelle elle-même | Clé API | S | Dépendance à un tiers commercial pour le routage, pas de contrôle sur les coûts de marge |
| **TensorZero** | github.com/tensorzero/tensorzero | Apache-2.0 (vérifié) | Rust | **Dépôt archivé le 12 juin 2026** (confirmé) — code figé, plus aucune maintenance | — | — | — | **Rejeté** comme fondation : aucun correctif de sécurité futur |
| **RouteLLM (lm-sys)** | github.com/lm-sys/RouteLLM | Apache-2.0 (vérifié) | Python | **Dernier commit août 2024**, non maintenu (non archivé formellement) | Concept de routeur par classifieur léger cascade « petit modèle d'abord » | — | — | **Rejeté comme dépendance** ; concept réimplémenté à la main (§3) |
| **Envoy AI Gateway** | github.com/envoyproxy/ai-gateway | Apache-2.0 (vérifié) | Go | Active, écosystème Envoy/Kubernetes | Routage/rate-limiting au niveau infra | Sidecar Envoy | L | Conçu pour K8s multi-cluster ; surdimensionné pour un VPS mono-nœud docker-compose — écarté pour OPSYS v1 |
| **Ramp Router (router.com)** / **Vercel AI Gateway** | proprietary SaaS | N/A | — | Déjà intégrés comme *providers* dans Hermes (`plugins/model-providers/router/`, `.../ai-gateway/`) | Fournisseurs de plus derrière LiteLLM si besoin | Clé API | S | SaaS propriétaire, coûts de marge, pas pour l'auto-hébergement |

**Choix retenu et justification (§9 détaille l'architecture) :** LiteLLM en couche B, pour la
profondeur de gouvernance (budgets hiérarchiques = mapping direct sur les 10 départements OPSYS),
la largeur de couverture fournisseurs, et parce que c'est déjà le point d'intégration que Hermes et
OpenClaw traitent comme un fournisseur ordinaire (donc zéro friction si le cœur applicatif final
s'inspire de l'un ou l'autre). Bifrost reste l'option de repli « VPS très contraint ».

---

## 2. Routage coût/qualité, cascades, fallbacks

- **RouteLLM** (rejeté comme dépendance, §1) : son papier/architecture — un classifieur léger prédit
  si un modèle faible suffira, sinon escalade — reste la référence conceptuelle. À réimplémenter
  petit (S) : un classifieur ou heuristique de règles par module (ex. M2 scoring lead = règles ;
  M9 stratégie = toujours le modèle fort), pas besoin du framework lui-même.
- **Hermes Agent** implémente déjà un vrai routage par tâche en production (vérifié dans le code) :
  chaque tâche auxiliaire (vision, compression, title-generation, approbation de commandes, revue)
  a sa propre résolution de fournisseur/modèle, indépendante du modèle principal — c'est *de facto*
  un routeur par difficulté/tâche déjà écrit, en Python, sous MIT
  (`website/docs/user-guide/features/fallback-providers.md`, section « Auxiliary Task Fallback »).
- **Cascades/fallback multi-fournisseurs** : Hermes et OpenClaw documentent tous deux des chaînes de
  secours complètes (rate-limit → erreur serveur → auth → réponse invalide) avec bascule
  transparente en cours de session et restauration du fournisseur primaire au tour suivant
  (`fallback-providers.md`). Point d'attention **directement réutilisable comme règle de conception**
  pour OPSYS : *un changement de fournisseur/modèle en cours de session invalide le cache-prompt* —
  documenté indépendamment par Hermes et OpenClaw comme le piège n°1 de coût caché.
- **LiteLLM** fournit le même mécanisme (fallback list par déploiement) au niveau de la passerelle —
  redondant mais complémentaire : Hermes gère le fallback *applicatif* (dans le tour de l'agent),
  LiteLLM gère le fallback *infra* (si tout un provider tombe pour tous les modules à la fois).

---

## 3. Caches

### 3.1 Cache exact
LiteLLM intègre nativement des back-ends mémoire / Redis / S3 / GCS / Qdrant-sémantique /
Redis-sémantique (docs.litellm.ai/docs/caching/all_caches, vérifié par recherche datée 2026). Redis
étant de toute façon un composant probable du stack OPSYS (files, sessions), le cache exact LiteLLM
sur Redis est un ajout quasi gratuit (effort **S**).

### 3.2 Cache sémantique
- **GPTCache (zilliztech)** — MIT, mais dernière release documentée 0.1.40 (août 2023) : **non
  maintenu en 2026** (vérifié). **Rejeté** comme dépendance.
- Remplacement recommandé : **cache Redis-sémantique de LiteLLM** (embeddings + similarité cosinus,
  intégré) ou le **cache sémantique natif de Bifrost** si Bifrost est la passerelle. Les guides 2026
  pointent aussi Redis Vector (RedisVL) comme brique de référence pour un cache sémantique partagé
  multi-instances — déjà compatible avec un Redis unique sur le VPS.

### 3.3 Cache natif des fournisseurs — comment le maximiser
Pricing vérifié par recherche datée septembre 2026 (sources en bas de section) :

| Fournisseur | Mécanique | Tarif cache-hit vs miss |
|---|---|---|
| Anthropic | `cache_control` explicite, 4 breakpoints max | lecture ≈ 0,1× le prix input de base ; écriture 1,25× (TTL 5 min) ou 2× (TTL 1 h) |
| OpenAI (GPT-5.x) | automatique, aucun marqueur requis | remise ~50–90 % selon la famille de modèle |
| Gemini | ressource `cachedContents` facturée au **stockage** (pas à la lecture) | 0,40 $/1M tok/h (<200k ctx) à 4,50 $/1M tok/h (>200k ctx) — donc rentable seulement si le préfixe est réellement réutilisé souvent |
| DeepSeek | automatique, le plus agressif du marché | ex. deepseek-v4-flash : 0,14 $/MTok miss vs 0,0028 $/MTok hit (~98 % de remise, coupe tarifaire avril 2026) |

**Comment maximiser (patron directement extrait du code Hermes + OpenClaw, tous deux MIT, à
vendoriser) :**
1. **Séparer préfixe stable / suffixe volatil** dans le prompt système : identité du module,
   définitions d'outils, skills, schémas JSON en haut (jamais modifiés d'un tour à l'autre) ;
   horodatage, contexte runtime, faits « vivants » en bas. C'est exactement la discipline
   documentée dans OpenClaw (`docs/reference/prompt-caching.md`, section « System-prompt cache
   boundary ») — y compris trier déterministiquement les catalogues d'outils MCP pour ne pas
   casser le préfixe par un simple changement d'ordre de découverte.
2. **Stratégie Anthropic « system_and_3 »** de Hermes (`agent/prompt_caching.py`) : breakpoint 1 =
   system prompt, breakpoints 2–4 = fenêtre glissante des 3 derniers messages non-système —
   directement portable.
3. **Ne jamais changer de modèle/fournisseur en milieu de session** sans accepter la perte du cache
   (les deux projets le documentent indépendamment comme la cause n°1 de facture qui explose).
4. **TTL adaptatif** : 5 min par défaut, 1 h pour les sessions humaines à rythme lent (M1 accueil
   omnicanal), « heartbeat » qui maintient le cache chaud entre deux appels espacés (M4/M8 cron).

Sources : [Prompt Caching 2026 — TokenCost](https://tokencost.app/blog/prompt-caching-pricing-2026),
[LLM API Pricing 2026 — Spheron](https://www.spheron.network/blog/llm-api-pricing-comparison-gpt-claude-gemini-deepseek-2026/),
[Anthropic vs OpenAI Prompt Caching 2026 — ofox.ai](https://ofox.ai/blog/prompt-caching-cost-math-anthropic-vs-openai-2026/).

---

## 4. Compression

| Brique | URL | Licence | Apport | Effort |
|---|---|---|---|---|
| **LLMLingua / LongLLMLingua** | github.com/microsoft/LLMLingua | **MIT** (vérifié) | Compression de prompt par élagage de tokens à faible information (via petit modèle) — utile pour compresser des extraits RAG ou de longues sorties d'outils avant envoi au modèle cher | M |
| **Compaction de contexte (Hermes)** | `agent/context_compressor.py`, `agent/context_engine.py` | MIT | Système à double seuil (garde-fou passerelle à 85 %, compacteur agent à 50 %), algorithme en 4 phases : élagage des vieilles sorties d'outils → détection de bornes → résumé structuré → réassemblage ; mode « lean » mesuré à ~49k tokens conservés vs ~162k en mode legacy sur une session de 500k tokens réelle | **Directement vendorisable** (Python) — L pour l'adaptation aux 10 modules, mais code de départ complet |
| **Élagage des sorties d'outils** | idem + OpenClaw `aggregateToolResultTruncation` | MIT | Remplacer les vieilles sorties d'outils (>200 car.) par un stub « effacé pour économiser le contexte », hors de la fenêtre protégée | S (règle simple, déjà écrite dans les deux projets) |
| **Mémoire procédurale (skills)** | Hermes `skills/`, OpenClaw `skills/` | MIT | Instructions réutilisables chargées à la demande plutôt que réexpliquées à chaque appel — le mécanisme est identique à celui que ce projet utilise déjà (skills projet dans `AGENTS.md`/`CLAUDE.md`). Recommandation : formaliser un dossier `skills/` par module OPSYS (M1..M10) | S/M |
| **RAG ciblé** | (hors périmètre R3) | — | Couvert par la mission dédiée « RAG premium » du plan (exigence dure #5 du propriétaire) — ne pas dupliquer ici ; se limiter à la règle d'architecture : ne jamais faire injecter à un agent un document brut complet quand un extrait top-k suffit | — |
| **Sorties structurées courtes** | patron, pas une brique | — | Schémas JSON validés (Pydantic, déjà dans l'écosystème Python d'OPSYS) pour toute communication inter-module — borne strictement les tokens de sortie, évite la prose libre | S |

---

## 5. Budgets, quotas, suivi des coûts, alertes

- **LiteLLM** (voir §1) : clés virtuelles avec budget mensuel, limites RPM/TPM, restriction de
  modèles, alertes de dépassement (soft via webhook, hard via blocage de la clé) — mapping direct
  « 1 département OPSYS (M1..M10) = 1 clé virtuelle + 1 budget » piloté depuis le dashboard central
  via l'API admin de LiteLLM plutôt que réinventer une gestion de clés. Source :
  [LiteLLM Budgets/Rate Limits](https://docs.litellm.ai/docs/proxy/users),
  [LiteLLM Docker Quickstart](https://docs.litellm.ai/docs/proxy/docker_quick_start).
- **Langfuse** — `github.com/langfuse/langfuse`. Cœur **« MIT Expat » (= MIT)** vérifié ; dossiers
  `ee/`, `web/src/ee/`, `worker/src/ee/` sous **licence Enterprise séparée** (source-available,
  vérifiée dans `ee/LICENSE` : usage/modif pour dev-test libre, mais toute exploitation en
  production de ces parties exige une licence payante) — **à signaler comme risque** si une
  fonctionnalité « ee » est activée par erreur ; le cœur MIT (traces, dashboards de coût, sessions)
  couvre déjà l'essentiel des besoins OPSYS. Copyright du fichier LICENSE daté « 2023-2026,
  ClickHouse, Inc. » (NON VÉRIFIÉ indépendamment au-delà de cette mention dans le fichier source —
  suggère un rachat/rapprochement ClickHouse à confirmer si contractuellement pertinent).
  Hermes Agent ship déjà un plugin d'observabilité Langfuse opt-in
  (`tests/plugins/test_langfuse_plugin.py`, module `plugins.observability.langfuse`) — donc si le
  cœur applicatif OPSYS dérive de Hermes, l'intégration Langfuse est déjà à moitié faite.
- **Helicone** — `github.com/Helicone/helicone`, **Apache-2.0** (vérifié), Rust, alternative
  d'observabilité par proxy. Redondant avec Langfuse pour OPSYS ; ne pas déployer les deux (coût
  d'exploitation double pour un bénéfice marginal) — **Langfuse retenu** par défaut du fait de
  l'intégration déjà existante côté Hermes.
- **Dashboard « Usage » d'OpenClaw** (`docs/reference/api-usage-costs.md`) : ventilation par
  fournisseur/modèle/agent/canal/plage de dates, calculée localement sans infra supplémentaire
  (SQLite) — bon patron d'UX pour l'onglet « Coûts » du dashboard central OPSYS, même si l'agrégation
  de fond reste Langfuse+LiteLLM.

---

## 6. Exécution locale

| Outil | URL | Licence | Empreinte VPS | Rôle recommandé |
|---|---|---|---|---|
| **Ollama** | github.com/ollama/ollama | **MIT** (vérifié) | CPU ou GPU, un seul binaire+démon, bibliothèque de modèles intégrée | UX la plus simple pour les modèles locaux (classification, extraction, embeddings) |
| **llama.cpp** (`llama-server`) | github.com/ggml-org/llama.cpp | **MIT** (vérifié) | La plus légère en CPU pur, contrôle fin de la quantization | Choix par défaut sur VPS CPU-only ; c'est littéralement ce que le provider « llama.cpp géré » de Hermes installe et pilote (`gateway/local-model-services.md`) |
| **vLLM** | github.com/vllm-project/vllm | **Apache-2.0** (vérifié) | Débit maximal mais optimisé GPU (CUDA) | À activer seulement si le client passe sur un VPS/serveur GPU ; sur VPS CPU pur, pas d'avantage décisif sur Ollama/llama.cpp |
| **LM Studio** | lmstudio.ai | **Propriétaire** (Element Labs, Inc. — vérifié via ToS août 2026) : usage commercial autorisé gratuitement, mais **interdit explicitement comme service hébergé pour des tiers** et pas de redistribution | Application desktop GUI, pas conçue pour un conteneur headless | **Exclu** pour OPSYS (VPS SaaS multi-tenant = exactement l'usage interdit par sa licence) |

**Patron d'exploitation à réutiliser** : le `localService` d'OpenClaw
(`docs/gateway/local-model-services.md`) démarre le serveur local **à la demande** (probe de santé,
démarrage du process, attente de disponibilité) et l'arrête après un délai d'inactivité configurable
— évite de garder un modèle local résident 24 h/24 sur un VPS à ressources comptées. Design
directement transposable en Python pour OPSYS (effort **M**), même si le code source est en
TypeScript.

**Modèles locaux recommandés 2026** (sources web datées ci-dessous — capacités/chiffres non
vérifiables autrement qu'en confiance des articles cités, à re-tester en interne avant mise en
prod) :
- **Classification / extraction / structuration** : Phi-4 Mini (3,8B, MIT, ~4 Go VRAM en Q4),
  Mistral Small 3.2 (Apache-2.0, 128K ctx, natif FR/EN — pertinent pour le contexte QC/FR d'OPSYS),
  Qwen3 8B/14B (Apache-2.0).
- **Embeddings** : Qwen3-Embedding-0.6B (Apache-2.0, ~1,5 Go VRAM, natif Ollama, MTEB 70,7) pour
  l'entrée de gamme ; BGE-M3 (BAAI — licence à reconfirmer avant usage commercial, historiquement
  MIT/Apache selon les versions BAAI, **NON VÉRIFIÉ** précisément ici) pour le multilingue 100+
  langues, cité comme choix par défaut RAG 2026.
- **Reranking** : BGE-reranker-v2, apparié à BGE-M3.

Sources : [Best Open-Source Small Language Models 2026 — BentoML](https://www.bentoml.com/blog/the-best-open-source-small-language-models),
[Best Self-Hosted Embedding Models 2026 — Mixpeek](https://mixpeek.com/curated-lists/best-self-hosted-embedding-models).

---

## 7. Hermes Agent et OpenClaw — quoi réutiliser plutôt que dupliquer

Les deux projets sont **MIT** (Hermes : `Copyright (c) 2025 Nous Research` ; OpenClaw :
`Copyright (c) 2026 OpenClaw Foundation` — vérifiés sur les `LICENSE` racines des deux clones
locaux). Le croisement MIT↔MIT est sans friction juridique quel que soit celui retenu comme cœur
applicatif par la mission dédiée à ce choix ; **pour R3 spécifiquement, la langue d'implémentation
fait la vraie différence** :

| Aspect token-economy | Hermes Agent (Python) | OpenClaw (TypeScript) | Portabilité vers OPSYS (Python 3.12) |
|---|---|---|---|
| Cache-prompt multi-fournisseurs | `agent/prompt_caching.py`, stratégie « system_and_3 » | Séparation préfixe stable/suffixe volatil, tri déterministe des catalogues d'outils | **Hermes vendorisable quasi tel quel** ; règles de conception d'OpenClaw à adopter en plus (langage-agnostiques) |
| Compaction de contexte | `agent/context_compressor.py` — algorithme 4 phases complet, mode « lean » mesuré | `contextPruning.mode: cache-ttl` (plus simple, orienté TTL) | Hermes = base de code à porter (effort L mais code de départ complet) |
| Routage par tâche/difficulté | Résolution de fournisseur indépendante par tâche auxiliaire (vision, compression, titres, approbation) — un vrai routeur multi-niveaux déjà en prod | Pas d'équivalent aussi granulaire documenté | Hermes = patron à répliquer directement pour les 10 modules |
| Cycle de vie modèle local | Pas de gestion de cycle de vie dédiée trouvée | `localService` : démarrage à la demande, probe santé, arrêt sur inactivité | Design d'OpenClaw à réimplémenter en Python (pas de code à copier, langage différent) |
| Dashboard coûts | Pas de dashboard web propre (CLI `/status`, `/usage`) | Control-UI → Usage, ventilé provider/modèle/agent/canal | Inspiration UX pour le dashboard central OPSYS, peu de code réutilisable tel quel (React/TS côté OpenClaw) |
| Fallback multi-fournisseurs | Chaîne complète documentée et testée, par tour, par tâche | Équivalent documenté (`concepts/model-failover.md`) | Les deux convergent ; prendre la logique Hermes (Python) comme référence d'implémentation |
| Fournisseurs déjà interfacés | 35+ profils (`plugins/model-providers/`), dont **ai-gateway** (Vercel AI Gateway), **router** (Ramp Router), **openrouter**, **litellm implicite via `custom`** | Extensions dédiées `extensions/litellm/`, `extensions/openrouter/` — **OpenClaw a un plugin LiteLLM de première classe** | Confirme LiteLLM comme point d'intégration neutre quel que soit le cœur retenu |

**Conclusion pratique** : si le cœur applicatif final d'OPSYS est un fork Python (Hermes ou du code
neuf en Python), **vendoriser directement** les modules Hermes de cache-prompt et de compaction de
contexte (gain de temps majeur, effort M au lieu de L). Si le fork retenu est OpenClaw (TypeScript),
réimplémenter en Python la *logique* de compaction/cache de Hermes plutôt que de garder la
compaction TS d'OpenClaw isolée du reste du stack Python (24k+41k LOC déjà en Python) — et récupérer
telles quelles les **règles de conception** cache-boundary d'OpenClaw (langage-agnostiques). Dans
les deux cas, le plugin LiteLLM déjà présent côté OpenClaw et le support `custom`/`ai-gateway` côté
Hermes confirment que brancher LiteLLM en amont ne demande de développement ni pour l'un ni pour
l'autre choix de cœur.

---

## 8. Architecture « token economy » retenue pour OPSYS

```
                          ┌───────────────────────────────────────────┐
                          │   Dashboard central OPSYS (existant/prévu) │
                          │   - Édite modèles/alias par module         │
                          │   - Édite budgets par département          │
                          │   - Lit coûts/cache-hit-rate (Langfuse +   │
                          │     API admin LiteLLM)                     │
                          └───────────────┬─────────────────────────────┘
                                          │ API admin
                                          ▼
                      ┌──────────────────────────────────────┐
   Couche B (réseau)  │   LiteLLM Proxy (docker-compose)      │  ← clés virtuelles + budget par module
                      │   - Postgres (spend, clés, logs)      │  ← cache exact + sémantique Redis
                      │   - Redis (cache L2, rate-limit)      │  ← fallback inter-fournisseurs (infra)
                      │   - endpoint unique OpenAI-compatible │
                      └───────┬───────────────┬────────────────┘
                              │               │
                 ┌────────────┘               └──────────────┐
                 ▼                                            ▼
      Fournisseurs CLOUD                             Fournisseurs LOCAUX
   (Anthropic, OpenAI, Gemini,                    (Ollama / llama.cpp server,
    DeepSeek, OpenRouter, …)                        démarrage à la demande,
    → cache natif maximisé (§3.3)                    arrêt sur inactivité — patron OpenClaw)

   ┌─────────────────────────────────────────────────────────────────────┐
   │ Couche A (in-process, par agent de module M1..M10 — vendorisée      │
   │ depuis Hermes Agent, Python) :                                       │
   │  - injection cache_control / préfixe stable-suffixe volatil         │
   │  - compaction de contexte dual-seuil (85 % garde-fou / 50 % agent)  │
   │  - élagage des sorties d'outils > 200 car. hors fenêtre protégée     │
   │  - routage par tâche : classification/extraction/embeddings →       │
   │    modèle local ; raisonnement moyen → modèle cloud bon marché ;     │
   │    stratégique (M9) / critique (M3, M5) → modèle cloud fort          │
   │  - skills/ par module = mémoire procédurale (jamais réexpliquer)     │
   └─────────────────────────────────────────────────────────────────────┘
```

### Règles et défauts codifiés

1. **Routeur de difficulté par défaut** (règles explicites + classifieur léger inspiré RouteLLM,
   réimplémenté maison — pas la dépendance abandonnée) :
   - Local (Ollama/llama.cpp, coût marginal ~0) : classification, extraction de champs, embeddings,
     rerank, résumés courts internes.
   - Cloud bon marché (DeepSeek/Gemini Flash via LiteLLM) : tâches de raisonnement moyen (M2
     scoring, aide à la planification M4).
   - Cloud fort (Claude/GPT haut de gamme) : M9 Stratégie, synthèse M3 (Monte Carlo + narratif),
     M5 Finance — réservé, override manuel toujours possible depuis le dashboard.
2. **Prompt système** de chaque module : bloc stable (identité, outils, skills, schémas) toujours
   au-dessus d'un bloc volatil (horodatage, faits runtime) — discipline OpenClaw.
3. **Jamais de changement de modèle/fournisseur en cours de session** sans notification explicite du
   coût de cache perdu (leçon Hermes+OpenClaw, §3.3).
4. **Budgets** : plafond mensuel $ par module (clé virtuelle LiteLLM), alerte à 80 %, dégradation
   automatique vers modèle local seul à 100 %, modifiable sans redéploiement depuis le dashboard.
5. **Compression** : seuil de compaction 50 % du contexte (défaut Hermes), garde-fou passerelle
   85 %, élagage des sorties d'outils anciennes par défaut activé.
6. **Cache** : TTL 5 min par défaut, 1 h pour sessions humaines lentes (M1), heartbeat de maintien
   pour tâches cron régulières (M4, M8).

### Métriques à exposer sur le dashboard (par module et globalement)

- Coût $ / 1000 requêtes, et coût $ / jour vs budget mensuel restant.
- Taux de cache-hit : exact, sémantique, natif-fournisseur (cacheRead/cacheWrite), par module.
- Répartition des requêtes : % servies en local vs cloud bon marché vs cloud fort.
- Nombre d'activations de fallback (signal d'instabilité fournisseur).
- Taille moyenne de contexte au déclenchement de la compaction (signal de dérive/verbosité des
  prompts).
- Tokens in/out cumulés par module par jour (alimente Langfuse + export vers `registries/ledger`).

---

## 9. INGRÉDIENTS RETENUS (classés par priorité d'intégration)

1. **LiteLLM Proxy** — MIT (cœur) — service docker-compose, effort **S/M** — passerelle réseau,
   budgets par département, cache Redis, admin UI.
2. **Modules de cache-prompt et compaction de contexte de Hermes Agent** (`agent/prompt_caching.py`,
   `agent/context_compressor.py`, `agent/context_engine.py`) — MIT — vendorisation Python, effort
   **M/L** — cœur de la couche A.
3. **Patron `localService` d'OpenClaw** (démarrage à la demande / arrêt sur inactivité des modèles
   locaux) — MIT, réimplémentation Python, effort **M**.
4. **Règles de conception cache-boundary d'OpenClaw** (préfixe stable/suffixe volatil, tri
   déterministe des catalogues d'outils) — MIT, patron de code, effort **S**.
5. **Langfuse (cœur MIT, hors `ee/`)** — observabilité/coûts, effort **S** (intégration déjà
   partiellement écrite si le cœur applicatif dérive de Hermes).
6. **LLMLingua** — MIT — compression de contexte RAG/outils, effort **M**, à activer sur les
   modules à gros volume de texte (M8 Analytics, M7 contenu).
7. **Ollama + llama.cpp server** — MIT — exécution locale VPS CPU, effort **S**, modèles :
   Phi-4 Mini / Mistral Small 3.2 / Qwen3 8-14B (classification/extraction), Qwen3-Embedding /
   BGE-M3 + BGE-reranker-v2 (RAG).
8. **Bifrost** — Apache-2.0 — option de repli passerelle si VPS très contraint, effort **S**.
9. **RouteLLM (concept, pas la dépendance)** — réimplémentation maison d'un classifieur de routage
   difficulté, effort **M**.

Écartés explicitement : GPTCache (non maintenu depuis 2023), TensorZero (archivé juin 2026), LM
Studio (licence propriétaire incompatible SaaS tiers), Envoy AI Gateway (surdimensionné mono-nœud),
Portkey OSS en position de passerelle principale (fonctions clés cloud-tier-only).

## 10. Recette d'intégration (Python-first, docker-compose VPS, dashboard central)

1. Ajouter `litellm` (image officielle) + `postgres` + réutiliser le `redis` existant du stack
   OPSYS dans `docker-compose.yml` ; `config.yaml` LiteLLM déclare un alias de modèle par
   « profil de difficulté » (local / cloud-bon-marché / cloud-fort) plutôt que par modèle brut, pour
   que les modules appellent des alias stables même si le modèle sous-jacent change.
2. Créer une clé virtuelle LiteLLM + budget par module M1..M10 ; exposer leur édition dans le
   dashboard central via l'API admin LiteLLM (pas de nouvelle UI de gestion de clés à écrire).
3. Extraire de Hermes Agent (licence MIT, attribution conservée) les fichiers de cache-prompt et de
   compaction, les adapter à la structure d'agents OPSYS existante (24k LOC) comme une bibliothèque
   partagée `opsys_token_economy/` important par tous les modules.
4. Écrire un petit service `local_model_manager` (inspiré du `localService` OpenClaw) qui démarre
   `llama-server`/Ollama à la demande pour les tâches classification/extraction/embeddings, avec
   arrêt après N minutes d'inactivité — réduit l'empreinte CPU/RAM permanente du VPS.
5. Brancher Langfuse (cœur MIT) en callback LiteLLM + SDK Python pour la traçabilité coût/latence
   par module ; exporter un résumé quotidien vers `registries/ledger/*.jsonl` via
   `scripts/ledger_append.py` (jamais à la main, conformément aux règles projet).
6. Activer le cache Redis-sémantique de LiteLLM (ou Bifrost natif si ce choix est fait) pour les
   requêtes répétitives inter-utilisateurs (FAQ, templates M7 marketing) en complément du
   cache-prompt natif fournisseur.

---

## Notes techniques et limites de vérification

- `api.github.com` et les pages HTML `github.com` sont bloqués dans cette session sauf dépôt
  explicitement attaché (erreur proxy « GitHub access to this repository is not enabled for this
  session »). `raw.githubusercontent.com` fonctionne sans restriction et a servi de source
  principale pour toutes les licences citées ci-dessus (fichiers `LICENSE` bruts, lus intégralement,
  pas résumés de mémoire). `img.shields.io` est également bloqué (403) dans cette session — **les
  nombres d'étoiles GitHub précis n'ont donc pas pu être vérifiés numériquement** ; la maturité est à
  la place étayée par clonage local complet (Hermes Agent, OpenClaw), par des articles comparatifs
  datés 2026 cités en lien, et par la mention de versions précises dans ces sources (ex. « Bifrost
  v1.6.4 »). Marqué explicitement plutôt que de citer un chiffre d'étoiles de mémoire.
- Le contenu exact de `enterprise/LICENSE` de LiteLLM n'a pas pu être résolu à ce commit (404) — la
  clause de renvoi dans le `LICENSE` racine est en revanche vérifiée verbatim.
- La licence précise des poids BAAI/BGE-M3 n'a pas été vérifiée à la source (recherche web
  seulement) — à confirmer avant intégration si BGE-M3 est retenu en production.
- Hermes Agent et OpenClaw ont été inspectés en profondeur uniquement sur les aspects
  fournisseurs/cache/compression/coûts pertinents pour R3 ; l'évaluation complète de l'un ou l'autre
  comme cœur applicatif (exigence dure #4 du propriétaire) relève d'une autre mission du plan.
