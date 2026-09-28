# INGREDIENTS — Catalogue des briques open source retenues pour OPSYS-AI

> Condensé des 10 rapports de recherche [`docs/research/R1`](R1-core-openclaw.md)…
> [`R10`](R10-m9-capabilities.md) (brief commun : [`00-BRIEF.md`](00-BRIEF.md)). Chaque licence est
> reprise **telle que le rapport source l'a vérifiée** (fichier `LICENSE` brut, fiche modèle Hugging
> Face, ou doc officielle citée dans le rapport) — ce document ne réévalue aucune licence lui-même.
> Contrainte produit (rappel `00-BRIEF.md`) : MIT/Apache-2.0/BSD/MPL = OK en dépendance ; LGPL = OK en
> liaison dynamique ; GPL/AGPL = service séparé non modifié uniquement ; source-available
> (BSL/Elastic/SSPL/RAIL/licences communautaires non-OSI) = signalé comme risque.

## Légende « Phase »

| Phase | Sens |
|---|---|
| **Intégré** | Vérifié dans le code ou la configuration du dépôt aujourd'hui. |
| **Phase 2** | Retenue par le rapport de recherche ; pas encore câblée dans le dépôt (aucune dépendance, aucun service, aucun fichier de config correspondant trouvé au 2026-09-28). |
| **Référence** | Source d'inspiration ou patron de conception cité par le rapport ; explicitement **non vendorisée**. |

---

## Core

> **Mise à jour ADR-0007** (remplace le point 1 d'ADR-0006, seul) : le core bascule de Hermes Agent
> vers **OpenClaw**. Vérifié directement (clone local `--depth 1`, `scratchpad/clones/openclaw`,
> commit `2d39f2f7`, identique à celui déjà inspecté par R1) : `package.json` `"version": "2026.9.6"`,
> `LICENSE` MIT « OpenClaw Foundation » — cohérent avec `core/UPSTREAM.md` et ADR-0007. Code OPSYS
> réel et testé : `src/opsys/openclaw.py` (génère les fragments `$include` par département — agent,
> fournisseur de modèles, espace de travail `SOUL.md`/`AGENTS.md`/`skills/`, automatisations cron) +
> `src/opsys/serveur_mcp.py` (mode `--http` streamable, jeton obligatoire) ; 9 tests dédiés
> (`tests/test_openclaw_passerelle.py`, `tests/test_serveur_mcp_http.py`, dont un aller-retour MCP réel
> via un serveur uvicorn + le client MCP officiel) — exécutés, **tous verts**.

| Brique | Licence vérifiée | Rôle dans OPSYS | Intégration | Phase | Rapport source |
|---|---|---|---|---|---|
| **OpenClaw** (openclaw/openclaw) | MIT | OPSYS-CORE : canaux, **mémoire d'agent native à provenance** (owner/agent/untrusted/system, consolidation « dreaming » à portes déterministes, rappel sans appel de modèle, purge de bout en bout), **apps mobiles officielles iOS/Android + Wear OS** (voir [`docs/architecture/MOBILE.md`](../architecture/MOBILE.md)), Control UI, automatisations (cron), MCP natif (stdio **et** streamable HTTP), fournisseurs de modèles compatibles OpenAI (routés vers LiteLLM) | Dépendance vendorisée épinglée par tag + commit + digest sha256 (`core/UPSTREAM.md` : release `v2026.9.6`, commit `ce5bbdc2`, image `ghcr.io/openclaw/openclaw`) ; extension exclusivement par interfaces publiques (`$include`, `agents.entries`, `models.providers`, `mcp.servers`, automatisations, skills `SKILL.md`) — aucun patch amont à ce jour | **Intégré** | R1 · ADR-0007 |
| **Hermes Agent** (NousResearch) | MIT | Runtime alternatif optionnel : le serveur MCP OPSYS fonctionne aussi en stdio pour Hermes (et Claude Code, et les tests) ; source d'ingrédients (compacteur de contexte, patrons de plugins) | `src/opsys/hermes_plugin.py` + `src/opsys/profils.py` (génère des distributions de profil Hermes) **conservés et testés**, mais ne sont plus le chemin par défaut | **Intégré** (adaptateur optionnel — runtime par défaut = OpenClaw) | R2 · ADR-0006 pt.1 (remplacé) · ADR-0007 pt.8 |

## Modèles / économie de tokens

| Brique | Licence vérifiée | Rôle dans OPSYS | Intégration | Phase | Rapport source |
|---|---|---|---|---|---|
| **LiteLLM Proxy** | MIT (cœur ; dossier `enterprise/` sous licence distincte, à éviter) | Passerelle de modèles **par défaut** (ADR-0007 pt.4) : les paliers OPSYS deviennent des alias LiteLLM (`opsys-local/-rapide/-standard/-fort`), clé virtuelle + plafond `tpd_limit` (tokens/jour) par département, cache Valkey (exact + sémantique) | `src/opsys/passerelle.py` (`config_litellm`, `ClientLiteLLM.enregistrer_departement`) ; CLI `opsys passerelle config` (écrit le `proxy_config.yaml`) et `opsys passerelle cles` (enregistre les clés virtuelles) ; **testé** (`tests/test_openclaw_passerelle.py`, y compris cycle création→mise à jour de clé contre un faux serveur LiteLLM) | **Intégré** | R3 · ADR-0007 |
| Cache-prompt et compaction **natifs d'OpenClaw** (`cacheRetention`, `contextPruning.mode:"cache-ttl"`, `compaction.*`, heartbeat keep-warm) | MIT (mécanisme du core OpenClaw) | Remplace, comme runtime par défaut, le rôle que jouaient les modules `agent/prompt_caching.py`/`context_compressor.py` de Hermes : cache multi-fournisseurs testé en direct (`cacheRetention`), compaction/troncature dynamique des résultats d'outils, suivi des coûts natif | Défauts OpenClaw actifs ; `src/opsys/openclaw.py::generer()` ne paramètre **pas encore** `cacheRetention`/`compaction`/`contextPruning` par département (seuls `name`/`workspace`/`model` sont écrits dans `agents.json`) — détail dans [`ECONOMIE-TOKENS.md`](../architecture/ECONOMIE-TOKENS.md) §2-3 | Phase 2 (mécanisme natif disponible, non encore paramétré par OPSYS) | R1 · ADR-0007 |
| Patron `localService` d'**OpenClaw** (démarrage à la demande / arrêt sur inactivité des modèles locaux) | MIT | Réduit l'empreinte VPS d'un modèle local (Ollama/llama.cpp) tenu résident 24 h/24 | Réimplémentation Python prévue (`local_model_manager`) ; `passerelle.py::modele_litellm()` sait déjà traduire un palier `custom`/`ollama` en paramètres LiteLLM, mais sans gestion de cycle de vie | Phase 2 | R3 |
| Règles de conception « cache-boundary » d'**OpenClaw** (préfixe stable / suffixe volatil, jamais changer de modèle en cours de session) | MIT | Discipline de rédaction des espaces de travail par agent — désormais **le comportement natif du runtime par défaut**, pas seulement une discipline appliquée manuellement | `src/opsys/openclaw.py::generer()` écrit `SOUL.md`+`AGENTS.md` (contenu stable) par agent, dans l'espace de travail que le système-prompt-cache-boundary natif d'OpenClaw sépare automatiquement du contexte volatil (runtime, timestamps) | **Intégré** | R1 · R3 · ADR-0007 |
| **Langfuse** (cœur) | MIT (dossiers `ee/`, `web/src/ee/`, `worker/src/ee/` sous licence Enterprise séparée) | Traçabilité coût/latence par appel LLM, complémentaire à la page native OpenClaw Control UI → Usage et à `/usage`/`/status` | Service sidecar (web + worker + ClickHouse + Postgres), callback LiteLLM + SDK Python | Phase 2 | R3 · R5 |
| **LLMLingua / LongLLMLingua** | MIT | Compression de prompt par élagage de tokens à faible information (extraits RAG, longues sorties) | Dépendance pip | Phase 2 | R3 |
| **Ollama** + **llama.cpp** (`llama-server`) | MIT (les deux) | Exécution locale des tâches classification/extraction/embeddings à coût marginal ~0 | `passerelle.py::modele_litellm()` route déjà un palier `provider: "custom"`/`"ollama"` vers un tel serveur via LiteLLM ; aucun palier local n'est configuré par défaut | Phase 2 | R3 |
| **Bifrost** (maximhq) | Apache-2.0 | Option de repli passerelle réseau si l'empreinte Postgres/Redis de LiteLLM est trop lourde (binaire Go unique, cache sémantique natif) | Service sidecar (alternative à LiteLLM) | Référence (option de repli, non retenue par défaut) | R3 |
| **RouteLLM** (lm-sys) — concept uniquement, pas la dépendance | Apache-2.0 (dépôt non maintenu depuis août 2024) | Patron « classifieur léger décide si un modèle faible suffit, sinon escalade » | Réimplémentation maison prévue par règles/heuristiques par module ; aujourd'hui l'assignation palier↔usage est **statique** par manifeste (`department.yaml: modeles`), pas un classifieur dynamique | Phase 2 | R3 |

## Mémoire / RAG

| Brique | Licence vérifiée | Rôle dans OPSYS | Intégration | Phase | Rapport source |
|---|---|---|---|---|---|
| **pgvector** + **pgvectorscale** | PostgreSQL License (les deux) | Indexation vectorielle dans le Postgres métier déjà prévu (StreamingDiskANN pour pgvectorscale) | Extension SQL (`CREATE EXTENSION vector`) | Phase 2 | R4 · R5 |
| FTS natif Postgres (`tsvector`/GIN) | Licence PostgreSQL (composant du moteur, pas une brique tierce) | Recherche lexicale (≈BM25), zéro risque de licence | Natif Postgres | Phase 2 | R4 |
| **Mem0** (mode OSS) | Apache-2.0 | Mémoire de faits par agent/tenant, recherche hybride sémantique+BM25+entités | Dépendance pip (`mem0ai`), vector store = pgvector du Postgres OPSYS | Phase 2 | R4 |
| **Graphiti** (Zep) + **Neo4j Community** (backend graphe) | Graphiti : Apache-2.0 · Neo4j Community : GPLv3 (sidecar non modifié) | Seul framework OSS à offrir un graphe bi-temporel natif (validité « quand c'était vrai » vs « quand invalidé ») pour clients/chantiers/décisions | Dépendance pip (`graphiti-core`) + service Neo4j sidecar consommé par Bolt | Phase 2 | R4 |
| **Docling** | MIT | Ingestion/OCR/parsing de tableaux, exécution locale possible (air-gapped, pertinent Loi 25) | Dépendance pip ou service `docling-serve` | Phase 2 | R4 |
| **BAAI/bge-m3** + **BAAI/bge-reranker-v2-m3** | bge-m3 : MIT (fiche HF) · reranker : Apache-2.0 (fiche HF) | Embeddings/reranking FR multilingue par défaut, exécutables CPU/ONNX | Poids téléchargés, servis en local | Phase 2 | R4 |
| Contextual Retrieval (technique Anthropic) + **Late Chunking** (jina-ai) | Contextual Retrieval : technique, pas un paquet · Late Chunking : Apache-2.0 | Chunking : contexte de situation par chunk (cache de prompt) + préservation du contexte inter-chunks sans appel LLM supplémentaire | Patron de pipeline Python | Phase 2 | R4 |
| **RAGAS** + **TruLens** | RAGAS : Apache-2.0 · TruLens : MIT | Évaluation continue (faithfulness, context precision/recall, RAG triad) + jeu de tests maison | Dépendance pip + harnais interne | Phase 2 | R4 |
| Squelette `MemoryProvider`/`MemoryManager` de **Hermes Agent** | MIT | Patron du port mémoire M10 (lifecycle, hooks `on_session_end`/`on_pre_compress`/`on_memory_write`) | Squelette du core Hermes à étendre (lever la limite « un seul provider externe actif ») | Référence (patron à étendre, pas encore de providers OPSYS écrits) | R4 |
| **Qdrant** | Apache-2.0 | Option d'échappement si l'ANN Postgres sature à l'échelle | Service sidecar docker | Phase 2 (optionnel, niveau 2) | R4 |
| **Cognee** | Apache-2.0 | Graphe de connaissances construit depuis des documents statiques (contrats, catalogues), complémentaire à Graphiti | Dépendance pip (adaptateur déjà catalogué côté Hermes) | Phase 2 (optionnel, niveau 2) | R4 |
| **Honcho** (Plastic Labs) | Serveur : AGPL-3.0 · SDKs client : Apache-2.0 | Modélisation utilisateur cross-session (M1/M2), pertinent pour un profil client enrichi | **Service séparé uniquement** (cloud ou conteneur non modifié) ; seul le SDK Apache-2.0 est vendorisable | Phase 2 (optionnel, niveau 2) | R4 |
| **Weaviate** | BSD-3-Clause (module `wl/` en licence propriétaire séparée, à revérifier avant usage) | Fusion BM25+dense native « out of the box », multi-tenance physique forte | Service sidecar docker | Phase 2 (optionnel, niveau 2) | R4 |
| **Cohere Rerank** / API embeddings cloud | Propriétaire (service) | Secours cloud si la qualité self-host plafonne, jamais par défaut | Appel API | Phase 2 (optionnel, niveau 2) | R4 |
| **Letta** (ex-MemGPT) | Apache-2.0 | Patron d'architecture (mémoire hiérarchique auto-éditée par le modèle) — pas un composant à faire tourner tel quel | Lecture/inspiration seulement | Référence | R4 |
| **R2R** (SciPhi-AI) | MIT | Patron « exposer le RAG en API interne », recouvre ce que le port M10 doit de toute façon exposer | Lecture/inspiration seulement | Référence | R4 |

*(M10 — voir aussi le domaine ci-dessus : le port mémoire M10 EST cette liste, cf. §« M10 » plus bas.)*

## Déploiement / observabilité

| Brique | Licence vérifiée | Rôle dans OPSYS | Intégration | Phase | Rapport source |
|---|---|---|---|---|---|
| **Traefik** (défaut) | MIT | Reverse proxy + TLS auto, `forwardAuth` pour fédérer les logins (dashboard, Grafana, Langfuse…) | Service sidecar docker | Phase 2 | R5 |
| **Caddy** (profil minimal) | Apache-2.0 | Alternative plus simple si une seule interface est exposée | Service sidecar docker | Phase 2 (alternative) | R5 |
| **PostgreSQL 17** + **pgvector** | PostgreSQL License (les deux) | Base relationnelle métier + RAG, déjà la stack visée (psycopg) | Image officielle `pgvector/pgvector:pg17` | Phase 2 (dépendance `psycopg` déclarée en optionnelle dans `pyproject.toml`, mais aucun service déployé) | R5 |
| **Valkey** (jamais Redis) | BSD-3-Clause | Cache + files + pub/sub, protocole compatible Redis | Image officielle sidecar | Phase 2 | R5 |
| **pgBackRest** | MIT | Sauvegarde Postgres parallèle/incrémentale par bloc, multi-repo S3 | Sidecar/cron docker + repo S3 canadien | Phase 2 | R5 |
| **restic** | BSD-2-Clause | Sauvegarde chiffrée des volumes non-SQL (ClickHouse Langfuse, Uptime Kuma, secrets) | Sidecar/cron docker | Phase 2 | R5 |
| **WAL-G** | Apache-2.0 | Alternative plus légère à pgBackRest (binaire unique, pas de serveur repo) | Sidecar/cron docker | Référence (alternative non retenue par défaut) | R5 |
| **Pocket ID** (défaut, profil minimal) | BSD-2-Clause | OIDC/OAuth2 certifié, passkeys/WebAuthn uniquement (pas de base de mots de passe) | Service sidecar, binaire Go | Phase 2 | R5 |
| **Authentik** (profil « full ») | MIT (cœur ; `enterprise/` séparé, `website/` en CC-BY-SA) | OIDC/SAML/LDAP dès que la PME a besoin de fédération plus riche | Service sidecar docker | Phase 2 | R5 |
| **sops** + **age** | sops : MPL-2.0 · age : BSD-3-Clause | Chiffrement des secrets au repos (`.env`/YAML), diff Git lisible | Binaires CLI, aucun conteneur | Phase 2 | R5 |
| **Infisical** (profil « full », optionnel) | MIT (cœur ; `ee/` séparé) | Gestion de secrets en équipe (audit trail, rotation, RBAC) — seulement si multi-opérateurs | Service sidecar (Postgres propre) | Phase 2 (optionnel) | R5 |
| **OpenTelemetry Collector** | Apache-2.0 | Hub OTLP unique : reçoit traces LLM (→Langfuse) et métriques système (→Prometheus) | Sidecar docker | Phase 2 | R5 |
| **Prometheus** | Apache-2.0 | Métriques système/conteneurs (avec node-exporter + cAdvisor) | Sidecar docker | Phase 2 | R5 |
| **Grafana** | AGPLv3 (assumé service séparé non modifié) | Dashboards visuels Prometheus + Postgres | Sidecar docker, jamais patché | Phase 2 | R5 |
| **Uptime Kuma** | MIT | Sondes actives (HTTP/TCP/DNS), « qui surveille le surveillant » | Sidecar docker, SQLite interne | Phase 2 | R5 |
| ufw + fail2ban + unattended-upgrades + Docker rootless | ufw/fail2ban : paquets OS (GPLv2) · Docker rootless : Apache-2.0 (Moby) | Durcissement VPS de base (pare-feu, bannissement IP, correctifs auto, isolation défense-en-profondeur) | Paquets hôte + configuration Docker, hors image applicative | Phase 2 | R5 |
| Extension du dashboard **Hermes** (plugin `dashboard/` : manifest + bundle IIFE + `plugin_api.py`) | MIT (mécanisme du core Hermes, cf. domaine Core) | Onglets OPSYS (Départements, Budgets et coûts, Approbations, Entreprise, Mémoire) plutôt qu'une console séparée | Extension native du core, sans build | Phase 2 (mécanisme disponible côté Hermes, aucun plugin dashboard OPSYS écrit à ce jour) | R5 · ADR-0006 |
| **Coolify**, **Dokploy** (cœur), **Supabase** (self-host) | Coolify : Apache-2.0 · Dokploy : Apache-2.0 cœur (+ `/proprietary` à ne jamais copier) · Supabase : Apache-2.0 | Patrons d'installateur one-liner idempotent + profils `docker compose --profile` — aucun n'est vendorisé (langages/paradigmes hors stack Python, ou trop lourd) | Lecture/inspiration seulement | Référence | R5 |

## M1 — Front Office

| Brique | Licence vérifiée | Rôle dans OPSYS | Intégration | Phase | Rapport source |
|---|---|---|---|---|---|
| **Pipecat** (Daily) | BSD-2-Clause | Colonne vertébrale de l'orchestration voix temps réel (pipeline STT→LLM→TTS, connecteurs Twilio/Deepgram/faster-whisper/ElevenLabs) | Dépendance pip | Phase 2 | R6 |
| **faster-whisper** + checkpoint communautaire `whisper-large-v3-turbo-fr-quebecois` | faster-whisper : MIT · checkpoint : licence du fine-tune non vérifiée ligne à ligne (dérivé Whisper) | STT local, WER 6,65 % mesuré sur français québécois (vs ~19,5 % générique) | pip + poids local | Phase 2 | R6 |
| **Twilio** (Voice/SIP/SMS/WhatsApp BSP) | SaaS propriétaire (SDK usage courant MIT, non revérifié ligne à ligne) | Téléphonie + SMS + WhatsApp Business en un seul contrat | SDK API | Phase 2 | R6 |
| **ElevenLabs** | SaaS propriétaire | TTS client-facing : seul fournisseur à documenter des voix « Québec » natives | SDK API | Phase 2 | R6 |
| **Piper** (`piper1-gpl`) / **Kokoro-82M** — repli TTS gratuit non critique | Piper (dépôt maintenu) : GPL-3.0 (ancien dépôt MIT gelé/archivé) · Kokoro : Apache-2.0 | Messages internes/tests où l'accent québécois n'est pas critique | Piper : **service/process séparé uniquement** (jamais `import`é, GPL) · Kokoro : vendorisable | Phase 2 | R6 |
| **imap-tools** | Apache-2.0 | Lecture IMAP d'une boîte courriel existante (parsing MIME, IDLE) | Dépendance pip | Phase 2 | R6 |
| **Chatwoot** (cœur CE) | MIT (dossier `enterprise/` propriétaire séparé, à ne jamais toucher) | Widget web + inbox omnicanale, évite de réécrire un widget de chat | Service sidecar docker | Phase 2 | R6 |
| `garde_fou.py` (code interne existant) | — (code propriétaire OPSYS, pas une brique tierce) | Gate bloquant regex déterministe (interdits prix/date/engagement/aveu), zéro coût LLM — **conservé tel quel** | Déjà dans `departments/m01-front-office/src/m1_front_office/garde_fou.py` | **Intégré** (existant, mode ombre) | R6 |
| **NeMo Guardrails** (NVIDIA) | Apache-2.0 | Second rail conversationnel optionnel (dérive de sujet/ton), activé seulement sur cas ambigus | Dépendance pip, en aval de `garde_fou.py` | Phase 2 (roadmap) | R6 |
| **Microsoft Presidio** + spaCy FR | MIT (les deux) | Détection/masquage de renseignements personnels dans les transcriptions (renfort Loi 25) | Dépendance pip | Phase 2 (roadmap) | R6 |
| **LiveKit Agents** | Apache-2.0 | Alternative à Pipecat si le SIP natif/WebRTC devient prioritaire | Dépendance pip + service LiveKit sidecar | Phase 2 (roadmap) | R6 |

## M2 — Revenue CRM

| Brique | Licence vérifiée | Rôle dans OPSYS | Intégration | Phase | Rapport source |
|---|---|---|---|---|---|
| **Splink** | MIT | Dédup **probabiliste** (Fellegi-Sunter, DuckDB embarqué) en complément du matching exact `doublons.py` — jamais de fusion automatique | Dépendance pip, passage asynchrone/batch | Phase 2 | R6 |
| **scikit-learn** | BSD-3-Clause | Scoring de leads (régression logistique/gradient boosting léger sur features structurées), jamais un LLM pour ce calcul | Dépendance pip, module `scoring.py` | Phase 2 | R6 |
| **APScheduler** | MIT | Cadencement des relances/SLA depuis `prochaine_action` (déjà présent) | Dépendance pip | Phase 2 | R6 |
| **EspoCRM** (optionnel) | AGPLv3 | UI CRM classique (kanban, calendrier) en façade optionnelle pour représentants ; le registre M2 reste la source de vérité | **Service séparé non modifié uniquement** | Phase 2 (optionnel, roadmap) | R6 |

## M3 — Estimation

| Brique | Licence vérifiée | Rôle dans OPSYS | Intégration | Phase | Rapport source |
|---|---|---|---|---|---|
| **OpenCV** (`opencv-python-headless`) | Apache-2.0 | Contrôle qualité photo réel (variance du Laplacien, histogramme) au lieu d'un `eclairage` déclaré | Dépendance pip, fonction pure | Phase 2 | R7 |
| `random.Random.triangular` (stdlib) puis PERT maison sur `scipy.stats.beta` | stdlib : aucune dépendance · scipy : BSD-3-Clause | Remplace le tirage `uniform` actuel de `monte_carlo.py` par une vraie triangulaire/PERT, déterminisme bit-à-bit conservé | stdlib d'abord ; scipy en option seulement pour PERT | Phase 2 | R7 |
| **WeasyPrint** | BSD-3-Clause | Génération du devis PDF depuis le contrat gelé `EstimationV1` (Jinja2→HTML→PDF) | Dépendance pip | Phase 2 | R7 |
| **SAM 2** (Meta) + **Grounding DINO** (via `transformers`) | SAM 2 : Apache-2.0 · Grounding DINO : Apache-2.0 | Mesure par objet de référence réelle (segmentation + localisation par texte), vérifie par le pixel ce qui n'était que déclaré | Sidecar Python (FastAPI interne), poids séparés | Phase 2 | R7 |
| **Depth Anything V2** — checkpoint **Small** uniquement | Apache-2.0 (Small ; Base/Large/Giant en CC-BY-NC, voir Refusées) | Carte de profondeur relative → mesure métrique avec un point d'échelle | Sidecar Python | Phase 2 | R7 |
| **SAM 3** (Meta) | Licence « SAM License » personnalisée (source-available, commercial autorisé mais clauses anti-rétro-ingénierie/riposte) | Segmentation par concept texte en un appel | Sidecar Python isolé, jamais redistribué | Phase 2, **signalé** (validation juridique requise avant usage) | R7 |

## M4 — Field Ops

| Brique | Licence vérifiée | Rôle dans OPSYS | Intégration | Phase | Rapport source |
|---|---|---|---|---|---|
| **Google OR-Tools** ou **PyVRP** | OR-Tools : Apache-2.0 · PyVRP : MIT | VRP réel (fenêtres de temps, capacités) remplaçant le tri round-robin de `cedule.py` | Dépendance pip directe | Phase 2 | R7 |
| **OSRM** | BSD-2-Clause | Matrice temps/distance routière réelle, remplace l'Haversine à vol d'oiseau | Sidecar Docker (extrait `.osm.pbf` Québec) | Phase 2 | R7 |
| **Open-Meteo** (API hébergée) | Code serveur self-host : AGPL-3.0 · données : CC-BY-4.0 · API gratuite non-commerciale | Report météo pour ajuster la cédule (`motif=meteo`, déjà dans l'énuméré) | Appel HTTP de l'API hébergée (pas d'auto-hébergement du code) | Phase 2 | R7 |
| **Traccar** (optionnel) | Apache-2.0 | GPS/télémétrie **de flotte de véhicules** (distinct du pointage ponctuel déjà couvert par `pointage.py`) | Sidecar Docker, API REST | Phase 2 (seulement si suivi flotte demandé) | R7 |

## M5 — FinanceCore

| Brique | Licence vérifiée | Rôle dans OPSYS | Intégration | Phase | Rapport source |
|---|---|---|---|---|---|
| **python-quickbooks** + **xero-python** (officiel) | MIT (les deux) | Clients API QuickBooks Online / Xero pour la synchronisation batch | Dépendance pip directe | Phase 2 | R8 |
| **plaid-python** (officiel) | MIT | Agrégation bancaire, couverture Canada vérifiée (Big Six + Desjardins + Tangerine + Simplii + coopératives) | Dépendance pip directe | Phase 2 | R8 |
| **Flinks** | Propriétaire/commercial (agrégateur montréalais) | Meilleure couverture QC déclarée (Desjardins compris) | API tierce, lecture seule d'abord | Phase 2 | R8 |
| **statsforecast** (Nixtla) | Apache-2.0 | Prévision de trésorerie 5 ans — **activé seulement quand R-009 (historique insuffisant) est levé** | Dépendance pip directe | Phase 2, bloqué par décision produit existante | R8 |
| Parseur OFX maison (stdlib, ~100-150 lignes) | — (code interne, pas de dépendance) | Alternative à `ofxtools` (GPL-3.0) pour lire les relevés OFX/QFX sans risque de licence en import direct | À écrire | Phase 2 | R8 |
| **quickbooks-online-mcp-server** (Intuit) / **xero-mcp-server** (Xero) — tous deux officiels | Apache-2.0 / MIT | Mode agentique : un agent M5 interroge QBO/Xero en langage naturel, toujours après contrôle F0-F7 | Sidecar Node/MCP | Phase 2 | R8 |
| **Beancount** + **Fava** | Beancount : GPL-2.0 · Fava : MIT | Export d'audit CPA en lecture seule (référence de conception pour un futur vrai plan comptable) | **Service séparé non modifié uniquement**, jamais `import beancount` | Phase 2 | R8 |
| **python-accounting** | MIT | Référence pour la future story « vrai grand livre » (ORM double-entry conforme IFRS) | Lecture/inspiration | Référence | R8 |

## M6 — Material Control

| Brique | Licence vérifiée | Rôle dans OPSYS | Intégration | Phase | Rapport source |
|---|---|---|---|---|---|
| **InvenTree** | MIT | Meilleur modèle de données stock/fournisseur/PO du marché — au minimum miné pour enrichir `CatalogueMateriaux` | Service sidecar docker (Postgres propre) ou lecture de schéma seule | Phase 2 | R8 |
| **python-barcode** + **python-qrcode** | python-barcode : MIT · python-qrcode : BSD-3-Clause | Génération d'étiquettes codes-barres/QR (bacs, chantiers) | Dépendance pip directe | Phase 2 | R8 |
| **statsforecast** / **Darts** (réutilisés de M5) | Apache-2.0 (les deux) | Seuil de réapprovisionnement dynamique, toujours une simple suggestion (jamais liée à une création de PO automatique) | Dépendance pip (réutilisation) | Phase 2 | R8 |
| **Snipe-IT** (optionnel) | AGPL-3.0 | Outillage sérialisé (checkout/checkin par employé), périmètre distinct des matériaux consommables | **Service séparé non modifié uniquement** | Phase 2 (optionnel) | R8 |

## M7 — Marketing

| Brique | Licence vérifiée | Rôle dans OPSYS | Intégration | Phase | Rapport source |
|---|---|---|---|---|---|
| **Matomo** | GPL-3.0 | Analytics web déjà câblé implicitement dans les fixtures (`utm_source`), reporting UTM/attribution riche, conforme Loi 25 | **Service sidecar non modifié uniquement** | Phase 2 | R9 |
| **Scrapy** | Apache-2.0 | Alimente `competitive/*` en snapshots réels (au lieu de fixtures figées), respecte `robots.txt` | Dépendance pip directe | Phase 2 | R9 |
| **Postiz** | AGPL-3.0 | Planification sociale multi-canal + Google Business Profile (post et lecture des métriques) | **Service sidecar non modifié** ; adaptateur Python déjà écrit (`postiz_adapter.py`, GATED `enabled=False`/`dry_run=True`) | Phase 2 (adaptateur codé et gated ; service Postiz non déployé) | R9 |
| **Astro** | MIT | Rendu du site (îlots, zéro JS par défaut), remplacerait le générateur HTML-par-f-string actuel ; `guardrail.py`/`aeo_engine.py` restent les gates inchangés | Build-time (pas un service runtime) | Phase 2 | R9 |
| **Unlighthouse** + **SerpBear** | MIT (les deux) | SEO technique à l'échelle : Core Web Vitals réel sur tout le site + suivi de position mots-clés | CLI/sidecar Docker | Phase 2 | R9 |
| **geo-optimizer-skill** | MIT | Second avis réseau pour l'AEO/GEO (citation réelle dans ChatGPT/Perplexity/Gemini), consommé par `aeo_engine.py`, jamais l'inverse | Sidecar/serveur MCP | Phase 2 | R9 |
| **Listmonk** | AGPL-3.0 | Emailing (newsletters, annonces de chantier), binaire Go unique très léger | **Service sidecar non modifié** | Phase 2 | R9 |
| **FLUX.1-schnell** / **Qwen-Image** | Apache-2.0 (les deux) | Génération de visuels promotionnels sans condition commerciale | Poids locaux ou API | Phase 2 | R9 |
| **changedetection.io** | Apache-2.0 | Veille concurrentielle continue (alertes sur changement de page), complète le snapshot ponctuel Scrapy | Sidecar Docker | Phase 2 | R9 |

## M8 — Analytics

| Brique | Licence vérifiée | Rôle dans OPSYS | Intégration | Phase | Rapport source |
|---|---|---|---|---|---|
| **DuckDB** + **Apache Parquet** (`pyarrow`) | DuckDB : MIT · Parquet : Apache-2.0 | Story GATED déjà actée par le PM/l'architecte : remplace le `list[dict]` en mémoire de M8 v1, zéro service réseau | Dépendance pip directe | Phase 2 (GATED, déjà nommée au PRD) | R9 |
| **dbt-core** | Apache-2.0 | Transformations SQL versionnées si `semantique.py` (fonctions pures) ne suffit plus | CLI + `dbt-duckdb` | Phase 2 (optionnel) | R9 |
| **PyMC-Marketing** | Apache-2.0 | MMM bayésien — déjà nommé au PRD M8 §3.2, GATED vague 4 | Dépendance pip directe | Phase 2 (GATED, déjà nommée au PRD) | R9 |
| **MetricFlow** (si dbt adopté) ou **Cube** (Core) | MetricFlow : Apache-2.0 · Cube : Apache-2.0/MIT selon fichier, sans clause copyleft | Couche sémantique déclarative, prolonge `dictionnaire.py`/`contrats.py` | pip (MetricFlow) ou sidecar (Cube) | Phase 2 | R9 |
| **Evidence** | MIT | « BI as code » : rapports figés versionnés (cohérent avec `digest.py` déterministe) | Build-time, aucun service runtime | Phase 2 | R9 |
| **Apache Superset** | Apache-2.0 | Dashboard interactif self-service, licence la plus sûre du lot | Sidecar Docker | Phase 2 | R9 |
| **WrenAI** (core/sdk/skills) / **Vanna** (alternative légère) | WrenAI : Apache-2.0 (`docs/` CC-BY-4.0 ; module AGPL-3.0 réservé futur non présent) · Vanna : MIT | Text-to-SQL scopé par couche sémantique pour un agent, rôle DB read-only strict | Sidecar Docker (WrenAI) ou pip (Vanna) | Phase 2 | R9 |
| `motherduckdb/mcp-server-motherduck` + `dbt-labs/dbt-mcp` | Officiels, licences des projets parents (MIT/Apache-2.0) | MCP déjà écrits : agents interrogent DuckDB/dbt sans SQL manuel | Serveurs MCP à brancher | Phase 2 | R9 |

## M9 — Strategic Intelligence

| Brique | Licence vérifiée | Rôle dans OPSYS | Intégration | Phase | Rapport source |
|---|---|---|---|---|---|
| **statsforecast** (+ `mlforecast`/`neuralforecast`, réutilisés) | Apache-2.0 | Prévision pour le Council, GATED tant que M9 reste un harnais stdlib pur | Dépendance pip | Phase 2 (GATED) | R10 |
| **scikit-criteria** | BSD-3-Clause | Matrices de décision (TOPSIS, AHP, ELECTRE) pour le Decision Intelligence Engine | Dépendance pip | Phase 2 (GATED) | R10 |
| **GPT Researcher** | Apache-2.0 (⚠️ le site officiel dit à tort « MIT » ; le fichier `LICENSE` fait foi) | Agent de veille/recherche multi-source pour un futur rôle Data/Risk du Council | Dépendance pip ou sidecar (sortie re-tracée en `SnapshotModule` avant d'entrer dans M9) | Phase 2 (GATED) | R10 |
| **Agent Skills** (`SKILL.md`, agentskills.io) | Apache-2.0 (spécification ; skills de génération docx/pdf/pptx/xlsx du dépôt d'exemples officiel = source-available, pas OSS) | Format de capacité par département — **déjà le format utilisé** dans ce dépôt (`departments/*/skills/*/SKILL.md`, cf. `DEPARTEMENTS.md`) | Convention déjà appliquée | **Intégré** | R10 |
| **LangGraph** | MIT | Moteur d'orchestration du futur Strategic Supervisor (graphe d'état typé, checkpoints) — déjà nommé dans la fiche source M9 | Dépendance pip, isolée derrière une interface interne | Phase 2 (GATED) | R10 |
| **gVisor** (`runsc`) | Apache-2.0 | Sandbox des skills exécutant du code, sans nécessiter KVM (compatible VPS d'entrée de gamme) | `runtime: runsc` par service docker-compose | Phase 2 | R10 |
| **DeepEval** / **Ragas** | Apache-2.0 (les deux) | Gate CI `proof-eval` symétrique du `proof-review` existant, jeu de données « golden » par département | Dépendance pip + CI | Phase 2 | R10 |
| Patron interne `civ_review.py` / `tally_reviews.py` (proof-method) | — (outil méthode interne, pas une brique OSS tierce) | Mécanisme de débat/consensus multi-vendor déjà en production pour la revue de code — **à copier-adapter** pour le Council M9 plutôt qu'importer un framework de débat externe | Copie-adaptation interne (règle #109 du dépôt) | **Intégré** (méthode, hors périmètre M9 v1) | R10 |
| **STORM** / Co-STORM | MIT | Génération de rapport long structuré avec citations tracées | Dépendance pip | Phase 2 (GATED) | R10 |
| **local-deep-research** | MIT | Veille confidentielle 100 % locale (LLM local ou cloud au choix) | Dépendance pip ou sidecar | Phase 2 (GATED) | R10 |
| **EMA Workbench** (TU Delft) | BSD-3-Clause | Scenario discovery / décision robuste sous incertitude profonde (module de découverte de scénarios seulement, pas tout le framework) | Dépendance pip (module ciblé) | Phase 2 (GATED) | R10 |
| **CrewAI** / **AutoGen** | CrewAI : MIT · AutoGen : MIT (`LICENSE-CODE` ; `LICENSE` racine du dépôt = CC-BY-4.0 pour la doc) | Prototypage rapide du Council avant fixation sur LangGraph | Dépendance pip | Phase 2 (GATED, prototypage) | R10 |
| Sources publiques QC/Canada (StatCan WDS, Données Québec permis + RBQ, CMHC/SCHL, ISQ) | Licence du gouvernement ouvert – Canada / CC-BY 4.0 Québec | Connecteurs `SnapshotModule` pour le diagnostic M9 (marché, permis, démographie) | Appels API/CSV directs | Phase 2 (GATED) | R10 |

## M10 — Mémoire

Le port mémoire de M10 **est** le domaine « Mémoire / RAG » ci-dessus (R4) : Mem0, Graphiti+Neo4j,
pgvector/pgvectorscale, Docling, bge-m3/bge-reranker-v2-m3, Contextual Retrieval/Late Chunking,
RAGAS/TruLens, sur le squelette `MemoryProvider`/`MemoryManager` de Hermes Agent. R10 le confirme
explicitement hors de son propre périmètre (« la RAG premium… est un chantier à part entière,
hors périmètre strict de R10 ») et documente en plus, pour M10 spécifiquement :

| Élément | Rôle dans OPSYS | Phase | Rapport source |
|---|---|---|---|
| Modèle « Département » (manifeste `department.yaml`, cycle de vie `mode_ombre → gated_review → actif → retire`) | Formalise pour M10 (et les 9 autres départements) le vocabulaire déjà convergé 6 fois dans le dépôt (toolsets, skills, politiques T0-T3, budget, KPIs) | **Intégré** (le schéma `opsys.departement/v1` de `src/opsys/departements.py` applique déjà ce patron) | R10 §B.6 |
| RBAC hybride rôle-département + attribut, traçabilité « on-behalf-of » | Registre M10 comme couche de vérité pour les accès inter-département | Phase 2 (GATED) | R10 §B.5 |

## Refusées

| Brique | Domaine | Raison | Rapport source |
|---|---|---|---|
| `Agnuxo1/OpenCLAW-2` (« openclaw2 ») | Core | Faux candidat : copie personnelle non officielle et non à jour d'OpenClaw (10 ★), aucun lien avec le vrai projet | R1 · ADR-0006 |
| GPTCache (zilliztech) | Modèles/tokens | Non maintenu depuis 2023 (dernière release 0.1.40, août 2023) | R3 |
| TensorZero | Modèles/tokens | Dépôt **archivé** le 12 juin 2026, plus aucun correctif de sécurité futur | R3 |
| LM Studio | Modèles/tokens | Licence propriétaire, interdit explicitement l'usage « as a hosted service for third parties » — incompatible SaaS VPS | R3 |
| Envoy AI Gateway | Modèles/tokens | Conçu pour K8s multi-cluster, surdimensionné pour un VPS mono-nœud docker-compose | R3 |
| Portkey Gateway (OSS) en position de passerelle principale | Modèles/tokens | Cache sémantique et guardrails clés en cloud-tier uniquement d'après les comparatifs 2026 (le self-host OSS en fait moins) | R3 |
| RouteLLM en **dépendance directe** | Modèles/tokens | Dernier commit août 2024, non maintenu ; seul le concept est réimplémenté maison | R3 |
| jinaai/jina-embeddings-v3, jina-reranker-v2-base-multilingual | Mémoire/RAG | CC-BY-NC-4.0 : non-commercial, API payante Jina uniquement en usage commercial | R4 |
| jinaai/jina-embeddings-v4 | Mémoire/RAG | Hérite de la **Qwen Research License** (dérivé Qwen2.5-VL-3B) malgré un tag HF trompeur « cc-by-nc-4.0 » — usage commercial interdit même payant en self-host | R4 |
| ParadeDB (`pg_search`) | Mémoire/RAG | AGPL-3.0 + licence commerciale duale ; différé au profit du FTS natif Postgres (zéro risque) tant que le choix juridique n'est pas tranché | R4 |
| FalkorDB | Mémoire/RAG | SSPL v1 (MongoDB), source-available : risque si OPSYS revend une fonctionnalité équivalente en SaaS multi-clients | R4 |
| Kùzu | Mémoire/RAG | Signal de dépréciation trouvé (non confirmé officiellement) — statut de maintenance incertain | R4 |
| Dify | Déploiement | « Apache-2.0 modifié » : clause anti-SaaS-multi-tenant explicite, disqualifiant pour la trajectoire SaaS multi-PME du produit | R5 |
| Redis (depuis Redis 8) | Déploiement | Tri-licence RSALv2/SSPLv1/AGPLv3, non permissive — remplacé sans compromis technique par Valkey (BSD-3-Clause) | R5 |
| Coqui XTTS-v2 (poids) | M1 | Coqui Public Model License 1.0 : usage non-commercial uniquement ; éditeur fermé depuis janvier 2024, aucune licence commerciale disponible | R6 |
| Llama Guard 4 | M1 | Llama 4 Community License : non-OSI, restrictions d'usage acceptable Meta — signalé, pas totalement exclu, mais pas une licence open source classique | R6 |
| Twenty, Frappe CRM, SuiteCRM **vendorisés** | M2 | AGPL-3.0 : incompatible avec un import/fork dans le code propriétaire OPSYS (autorisés seulement en sidecar non modifié) | R6 |
| dedupe (dedupeio) | M2 | Fiabilité opérationnelle en question (bug d'épuisement disque relevé sur un benchmark récent) | R6 |
| RSMeans (Gordian) | M3 | Propriétaire (~2 268 $ US/an+), aucune alternative API ouverte équivalente trouvée | R7 |
| `tadamcz/betapert` | M3 | Aucun fichier LICENSE détecté (tous droits réservés par défaut), 1 ★, dernier push 2024-01-05 | R7 |
| Depth Anything V2 — checkpoints Base/Large/Giant | M3 | CC-BY-NC-4.0 : non-commercial (seul le checkpoint Small, Apache-2.0, est utilisable) | R7 |
| Field Service Management (Beveren, sur ERPNext) | M4 | AGPL-3.0 + suite lourde (Frappe/ERPNext+MariaDB), redondante avec le moteur M4 déjà bâti | R7 |
| Akaunting | M5 | Business Source License 1.1 : plafond « 2 utilisateurs OU 1 entreprise OU 1000 factures », interdiction de revente en service hébergé | R8 |
| Invoice Ninja | M5 | Elastic License 2.0 : interdit explicitement de fournir le logiciel à des tiers comme service hébergé/managé — bloque le modèle SaaS multi-PME visé | R8 |
| Crater | M5 | AGPL-3.0, développement actif **abandonné** depuis août 2023 (patchs sécurité seulement) | R8 |
| Odoo Accounting (app complète) | M5 | Le cœur du dépôt est LGPL-3.0, mais l'app Accounting complète est Enterprise sous licence propriétaire OEEL — seule l'« Invoicing » est dans le périmètre libre | R8 |
| `ofxtools` importé **directement** | M5 | GPL-3.0 (l'API GitHub affiche à tort « Other ») — importable seulement en sous-processus isolé, jamais `import` direct dans `m5_financecore` | R8 |
| PartKeepr | M6 | GPL-3.0, dépôt officiellement **archivé**, mort depuis 2023 | R8 |
| GetCito | M7 | Licence GitHub non standard (« Other »/NOASSERTION), non vérifiable sans revue juridique du LICENSE réel | R9 |
| FLUX.1-dev | M7 | Licence commerciale payante requise ; usage non-commercial gratuit seulement | R9 |
| SDXL / SD 1.5 | M7 | CreativeML OpenRAIL-M : clauses comportementales non-OSI, catégorie « source-available » à signaler | R9 |
| Mautic | M7 | Redondant avec le scoring de leads déjà couvert par M2, stack PHP plus lourde que Listmonk pour le besoin réel | R9 |
| Metabase (OSS) en usage **client-facing** | M8 | AGPL-3.0 ; l'embedding vers des tiers exige une licence commerciale séparée même en restant AGPL en interne — usage interne seul reste gratuit | R9 |
| Robyn (Meta) | M8 | Le moins actif des trois candidats MMM (push 2026-01), historiquement R-first (Python en second plan) | R9 |
| `pyMCDM` | M9 | GPL-3.0 (contredit une source secondaire qui l'annonçait « MIT ») — incompatible en dépendance directe d'un produit commercial fermé | R10 |
| `langchain-ai/open_deep_research` | M9 | Dépôt **archivé** le 2026-08-21, lecture seule — référence de conception seulement | R10 |
| `cpgoncalves/strategy-analyzer` | M9 | 2 ★, dormant depuis ~2017, licence non-OSI standard (fichier « Creative Commons » en PDF) | R10 |
| ClawHub (OpenClaw) / HermesHub (Hermes) comme **sources d'installation automatique** de skills | M9 (transversal) | Incidents de sécurité vérifiés et massifs : 341-824+ skills malveillantes (« ClawHavoc »), CVE-2026-25253 (RCE, CVSS 8.8) — seul un fichier `SKILL.md` individuel, revu à la main, peut être vendorisé | R1 · R10 |

---

## Décompte

- **Core** : 2 retenues (2 intégrées — OpenClaw comme core par défaut, Hermes Agent comme adaptateur optionnel, ADR-0007) + 1 refusée.
- **Modèles/tokens** : 9 retenues (2 intégrées, 6 phase 2, 1 référence) + 6 refusées.
- **Mémoire/RAG** : 16 retenues (14 phase 2/optionnelles, 2 référence) + 6 refusées.
- **Déploiement/observabilité** : 18 retenues (16 phase 2, 2 référence — WAL-G, et le trio Coolify/Dokploy/Supabase en une seule ligne) + 2 refusées.
- **M1** : 11 retenues (1 intégrée — code interne conservé —, 10 phase 2) + 2 refusées.
- **M2** : 4 retenues (phase 2) + 2 refusées.
- **M3** : 6 retenues (phase 2) + 3 refusées.
- **M4** : 4 retenues (phase 2) + 1 refusée.
- **M5** : 8 retenues (7 phase 2, 1 référence) + 5 refusées.
- **M6** : 4 retenues (phase 2) + 1 refusée.
- **M7** : 9 retenues (phase 2) + 3 refusées.
- **M8** : 8 retenues (phase 2) + 2 refusées.
- **M9** : 13 retenues (2 intégrées — format Agent Skills et patron `civ_review.py` —, 11 phase 2) + 4 refusées.
- **M10** : renvoie au domaine Mémoire/RAG + 2 éléments propres (1 intégrée — modèle Département —, 1 phase 2).

**Total : 114 briques/patrons retenus** (dont 8 déjà intégrés au code ou à la méthode : **OpenClaw**
comme core par défaut, **Hermes Agent** comme adaptateur/runtime optionnel, **LiteLLM** comme
passerelle de modèles par défaut, la discipline de cache-boundary (désormais native au runtime
OpenClaw), `garde_fou.py` M1 conservé, le format Agent Skills, le patron
`civ_review.py`/`tally_reviews.py`, et le modèle « Département » de M10) **et 38 refusées
explicitement**, sur les 10 rapports `docs/research/R1`–`R10` ; mise à jour du choix de core par
[ADR-0007](../decisions/ADR-0007-core-openclaw.md), vérifiée directement dans le code, les tests et le
clone local d'OpenClaw (pas seulement relayée).
