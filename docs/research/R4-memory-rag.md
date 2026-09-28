# R4 — Mémoire « exceptionnelle » et RAG PREMIUM pour OPSYS-AI

Mission R4. Méthode : chaque licence a été vérifiée soit sur le fichier `LICENSE` brut du repo
(`raw.githubusercontent.com/<owner>/<repo>/<branche>/LICENSE*`, HTTP 200 cité), soit sur la fiche
modèle Hugging Face (champ `license` des metadata), sauf mention explicite « NON VÉRIFIÉ ». `api.github.com`
et `github.com` sont bloqués sans rattachement du repo dans cette session (`add_repo`) ; les signaux de
maturité (stars, activité) viennent donc de WebSearch (daté, approximatif, recoupé si possible) plutôt que
de l'API GitHub. Le clone déjà présent `scratchpad/clones/hermes-agent/` (Hermes Agent, NousResearch, MIT
— vérifié) a été inspecté directement (code source, pas de mémoire de modèle).

---

## 0. Résumé exécutif

OPSYS a déjà deux atouts pour la mémoire : PostgreSQL (psycopg) en place, et — si le core est forké depuis
**Hermes Agent** (candidat de l'exigence #4) — une abstraction `MemoryProvider` **déjà écrite, testée et
branchée sur un catalogue de 7+ providers** (Mem0, Honcho, Supermemory, OpenViking, Hindsight, Holographic,
RetainDB en carte plugins). C'est le levier le plus fort trouvé dans cette recherche : ne pas réinventer le
port mémoire, le fusionner à partir de `agent/memory_provider.py` + `agent/memory_manager.py`.

Recommandation en une phrase : **Postgres (pgvector + pgvectorscale + FTS natif) comme moteur unique
d'indexation par défaut, Mem0 (OSS) comme couche faits/mémoire agent, Graphiti comme graphe de connaissances
temporel, BGE-M3 + BGE-reranker-v2-m3 comme paire embeddings/reranker FR multilingue permissive, Docling
comme ingestion/OCR, chunking par « Contextual Retrieval » (Anthropic) avec cache de prompts pour l'économie
de tokens, RAGAS + un jeu de tests maison pour l'évaluation continue.** Qdrant reste l'échappatoire sidecar
si un module dépasse l'ANN Postgres mono-nœud.

Deux alertes licence majeures découvertes et à ne pas rater :
- **jinaai/jina-embeddings-v4** n'est PAS en CC-BY-NC comme son tag HF le laisse penser en premier lieu :
  il hérite de la **Qwen Research License** (dérivé de Qwen2.5-VL-3B) — usage commercial interdit, même
  payant, en self-host. À proscrire pour un produit commercial auto-hébergé.
- **FalkorDB** (backend graphe candidat pour Graphiti) est en **SSPL v1** (MongoDB), catégorie
  « source-available » que le brief demande de signaler comme risque — plus restrictif qu'AGPL si OPSYS
  revend une fonctionnalité équivalente en SaaS à ses futurs clients PME. Neo4j Community (GPLv3, vérifié)
  est plus sûr comme service réseau non modifié.

---

## 1. Mémoire d'agents

| Brique | URL | Licence (vérifiée) | Langage | Maturité | Apport pour OPSYS | Intégration | Effort | Risques |
|---|---|---|---|---|---|---|---|---|
| **Mem0** | github.com/mem0ai/mem0 | **Apache-2.0** (raw LICENSE, 200) | Python/TS | ~66k★ (WebSearch, daté 23/09/2026, [releasealert.dev](https://releasealert.dev/github/mem0ai/mem0), [dev.to](https://dev.to/_cbd692d476c5faf3b61bcf/mem0-memory-layer-5-hidden-uses-of-the-60k-star-agent-memory-engine-4g9p)), release il y a ~4h au moment du search, très actif | Extraction de faits par LLM + recherche hybride (sémantique+BM25+entités) ; mode OSS branchable sur **pgvector ou Qdrant**, LLM/embedder OpenAI ou **Ollama** (donc 100% local possible) | Dépendance pip (`mem0ai`) en mode OSS ; adaptateur déjà écrit dans Hermes Agent (`plugins/memory/mem0/`, MIT, v1.3.0) | **S** (mode OSS + pgvector = même Postgres qu'OPSYS) | Mode « Platform » = cloud tiers (à éviter, Loi 25) ; en mode OSS le LLM d'extraction fait un appel par tour → budgeter |
| **Graphiti** (Zep) | github.com/getzep/graphiti | **Apache-2.0** (raw LICENSE, 200) | Python | Zep a arrêté Zep Community Edition (gelée, Apache-2.0, dossier `legacy/`) et concentre tout l'open-source sur Graphiti ; ~14k★ selon [blog.getzep.com](https://blog.getzep.com/graphiti-knowledge-graphs-falkordb-support/) | **Seul framework OSS à offrir un graphe bi-temporel natif** (validité « quand c'était vrai » vs « quand invalidé ») — correspond exactement au besoin « clients, chantiers, décisions » du brief | Dépendance pip (`graphiti-core`) + un backend graphe séparé (voir §3) | **M** | Zep (le produit cloud) ≠ Graphiti (la lib OSS) — ne pas confondre en devis ; qualité dépend du LLM d'extraction d'entités (coût par ingestion) |
| **Letta** (ex-MemGPT) | github.com/letta-ai/letta | **Apache-2.0** (raw LICENSE, 200) | Python | Lignée MemGPT (papier 2023, très cité) ; nombre d'étoiles exact NON VÉRIFIÉ cette session | Mémoire hiérarchique auto-éditée par le modèle (bloc « core » + « archival ») — un **patron d'architecture** plus qu'un composant à vendoriser tel quel | Faire tourner tout le serveur Letta entrerait en conflit avec l'architecture 10-modules d'OPSYS (agents spécialisés, pas un agent MemGPT monolithique) | — (patron, pas dépendance) | Adopter Letta entier = dupliquer l'orchestration que fait déjà Hermes Agent/OPSYS |
| **Cognee** | github.com/topoteretes/cognee | **Apache-2.0** (raw LICENSE, 200) | Python | ~17.9k★ (WebSearch, [github.com/topoteretes/cognee](https://github.com/topoteretes/cognee)) | Pipeline « Extract‑Cognify‑Load » : construit un graphe de connaissances **à partir de documents** (contrats, catalogues) plutôt que du flux conversationnel — complémentaire à Graphiti, pas redondant | Adaptateur déjà présent dans le catalogue Hermes Agent (`cognee.yaml`, mode local détaché uvicorn ou Cognee Cloud) | **M** | Mode local par défaut démarre un serveur détaché + télémétrie anonyme sauf `TELEMETRY_DISABLED=1` (à désactiver) |
| **Honcho** (Plastic Labs) | github.com/plastic-labs/honcho | **AGPL-3.0** le serveur (raw LICENSE, 200) / **Apache-2.0** les SDKs client (`honcho-python`, `honcho-node`, vérifiés) | Python | ~4.3–5.2k★, croissance rapide (+644/sem. en mai 2026, WebSearch) | Modélisation utilisateur cross-session (raisonnement dialectique, cartes « peer ») — pertinent pour M2 CRM / M1 Front Office (profil client enrichi) | **Service séparé uniquement** (cloud app.honcho.dev, ou conteneur Docker non modifié derrière frontière réseau) ; vendoriser seulement le SDK Apache-2.0 | **S** si cloud/service ; **interdit** de forker le serveur AGPL | Le brief classe AGPL = service séparé non modifié obligatoire — respecté seulement si Honcho reste un sidecar/API, jamais un fork |
| **Hermes Agent — providers mémoire** | clone local (`scratchpad/clones/hermes-agent`) | **MIT** (Hermes Agent lui-même, vérifié) | Python/TS | Projet actif (338 plugins au catalogue au moment du clone) | Architecture `MemoryProvider` (ABC) + `MemoryManager` déjà écrite : `initialize → system_prompt_block/prefetch → sync_turn → tool_dispatch → shutdown`, hooks `on_session_end`, `on_pre_compress`, `on_memory_write`, `backup_paths`. **7 providers in-tree** (Mem0, Honcho, Supermemory, OpenViking, Hindsight, Holographic, RetainDB) + catalogue communautaire (LanceDB, mem-os, Hindsight, hors-arbre) | **C'est le meilleur point de départ pour le « port mémoire » de M10** si le core forké est Hermes Agent | **S** (copier le squelette, écrire les adaptateurs OPSYS) | Un seul provider externe actif à la fois dans le design Hermes actuel — OPSYS devra probablement lever cette limite (besoin simultané Mem0 + Graphiti) |
| **OpenClaw** (mémoire) | github.com/openclaw/openclaw | **MIT** (raw LICENSE, 200, « OpenClaw Foundation ») | NON VÉRIFIÉ (repo non cloné cette session) | Assistant grand public multi-plateforme, mémoire décrite (WebSearch) comme locale simple « state/memory/credentials live on your hardware » | Pas d'écosystème de providers pluggables comparable à Hermes (NON VÉRIFIÉ en détail faute de clone) — si OpenClaw est retenu comme core, M10 devra construire le port mémoire depuis zéro | — | **L** si core = OpenClaw (vs **S** si core = Hermes Agent, cf. ci-dessus) | Argument concret pour la décision « core agent » (hors scope R4) : Hermes Agent a une longueur d'avance mesurable sur la mémoire |

---

## 2. Moteurs RAG

| Brique | URL | Licence (vérifiée) | Langage | Maturité (WebSearch) | Apport | Intégration | Effort | Risques |
|---|---|---|---|---|---|---|---|---|
| **LightRAG** | github.com/HKUDS/LightRAG | **MIT** (raw LICENSE, 200) | Python | Issu d'un papier EMNLP 2025 (HKU), forte traction académique | RAG graphe léger, rapide à déployer, bon pour un premier POC department-level | Dépendance pip | **S** | Moins « production-grade » que RAGFlow sur l'ingestion documentaire |
| **RAGFlow** | github.com/infiniflow/ragflow | **Apache-2.0** (raw LICENSE, 200) | Python | ~85k★ mi-2026 (WebSearch, [Github-Ranking-AI](https://github.com/yuxiaopeng/Github-Ranking-AI/blob/main/Top100/RAG.md)), partie de ~10k★ il y a 2 ans → forte croissance | Focus « deep document understanding » : parsing/chunking de qualité avant indexation — recoupe le besoin ingestion d'OPSYS (devis, factures, photos de chantier) | Service sidecar docker (stack complète : app + moteur + UI) | **M** (c'est une plateforme, pas une lib) | Plus lourd qu'une lib Python pure ; UI qu'OPSYS n'utilisera pas (dashboard déjà prévu côté OPSYS) |
| **R2R** | github.com/SciPhi-AI/R2R | **MIT** (`LICENSE.md`, raw, 200 ; copyright EmergentAGI Inc.) | Python | Croissance ralentie selon comparatifs 2026 (WebSearch) ; API-first agentic RAG | Bon patron pour exposer le RAG en API interne, mais recouvre ce que M10 doit de toute façon exposer en port Python | Service sidecar ou juste patron d'architecture | **S** (patron) | Momentum communautaire NON VÉRIFIÉ précisément — à re-jauger avant d'investir dessus |
| **Haystack** (deepset) | github.com/deepset-ai/haystack | **Apache-2.0** (raw LICENSE, 200) | Python | ~24k★ (WebSearch, [florinelchis Medium](https://florinelchis.medium.com/top-10-rag-frameworks-on-github-by-stars-january-2026-e6edff1e0d91)) ; réécriture 2.x (pipelines DAG async, YAML déclaratif) | Le plus « entreprise » des orchestrateurs RAG — bon candidat pour le glue-code M10 (pipelines déclaratifs versionnés) | Dépendance pip | **M** | Framework généraliste large — risque de sur-ingénierie si utilisé pour tout |
| **LlamaIndex** | github.com/run-llama/llama_index | **MIT** (raw LICENSE, 200) | Python | ~46.5k★ (WebSearch, même source Medium) | Riche en connecteurs/index (dont *property graph index*, utile en complément léger de Graphiti/Cognee pour un besoin document→graphe simple) | Dépendance pip | **S/M** | Sur-large si seule une fraction est utilisée — importer à la carte |
| **GraphRAG** (Microsoft) | github.com/microsoft/graphrag | **MIT** (raw LICENSE, 200) | Python | Portée par Microsoft Research ; rythme de release variable (NON VÉRIFIÉ précisément) | Méthode de référence pour construire un graphe de communautés à partir d'un corpus + résumés hiérarchiques (« global search ») — utile pour M9 Strategic Intelligence (synthèse multi-documents) | Dépendance pip ou patron (le pipeline est ré-implémentable) | **M** | Coût LLM élevé à l'indexation (résumés récursifs) — à réserver aux corpus stratégiques, pas au RAG courant |
| **txtai** (NeuML) | github.com/neuml/txtai | **Apache-2.0** (raw LICENSE, 200) | Python | Mature, maintenu en continu par NeuML (maturité exacte NON VÉRIFIÉ précisément cette session) | « Tout-en-un » embeddings+RAG+pipeline très léger, embarquable, bon candidat pour un POC ou un module à faible volume sans dépendance lourde | Dépendance pip | **S** | Moins de traction communautaire que LlamaIndex/Haystack → moins de patrons/exemples disponibles |

---

## 3. Stockage (vecteurs, hybride, graphe)

| Brique | URL | Licence (vérifiée) | Maturité | Apport | Intégration | Effort | Risques |
|---|---|---|---|---|---|---|---|
| **pgvector** | github.com/pgvector/pgvector | **PostgreSQL License** (permissive type BSD/MIT, raw LICENSE 200) | Extension standard de facto de l'écosystème Postgres | ANN dans la base déjà utilisée par OPSYS — zéro service en plus, RLS Postgres réutilisable pour le multi-tenant et le cloisonnement Loi 25 | Extension SQL (`CREATE EXTENSION vector`) | **S** | Perf ANN pure inférieure à un moteur dédié à très grande échelle (mitigé par pgvectorscale, ligne suivante) |
| **pgvectorscale** | github.com/timescale/pgvectorscale | **PostgreSQL License** (raw LICENSE, 200) | Timescale, actif | Index **StreamingDiskANN** (inspiré DiskANN/Microsoft) + **Statistical Binary Quantization** + filtrage par labels ; benchmark cité dans le README : **28× moins de latence p95, 16× plus de débit** vs Pinecone s1 à 99 % recall sur 50M embeddings Cohere 768-d, auto-hébergé sur EC2, -75 % de coût ([README timescale/pgvectorscale](https://github.com/timescale/pgvectorscale)) | Extension SQL en plus de pgvector | **S** | Écrit en Rust/pgrx — build un peu plus complexe qu'une extension C pure sur un VPS minimal (image Docker officielle disponible, atténue le risque) |
| **Qdrant** | github.com/qdrant/qdrant | **Apache-2.0** (raw LICENSE, 200) | Très mature, référence du secteur | Hybride dense+sparse natif (fusion RRF via Query API), filtrage payload multi-tenant, un seul binaire Docker, ~8 Go RAM suffisent sur VPS ($30-50/mois, WebSearch) | Service sidecar docker | **S** | Aucun majeur — reste le meilleur point d'échappement si Postgres ANN sature |
| **Weaviate** | github.com/weaviate/weaviate | **Mixte** : BSD-3-Clause pour la majorité du code, **« Weaviate License »** propriétaire pour le dossier `wl/` uniquement (raw LICENSE, 200 — à re-vérifier module par module avant usage) | Mature, hybride BM25+vecteur natif, multi-tenance physique forte | Le seul des trois à fusionner BM25+dense en un seul opérateur de requête « out of the box » | Service sidecar docker | **M** | Vérifier quels modules tombent sous `wl/` avant d'en dépendre en prod (licence non-open pour cette partie) |
| **LanceDB** | github.com/lancedb/lancedb | **Apache-2.0** (raw LICENSE, 200) | Plus jeune, communauté plus petite (WebSearch) | Embarquable (bibliothèque, pas de serveur) — pertinent pour un M4/M6 en périphérie (edge) ou un cache local, moins pour le corpus central | Dépendance pip/lib | **S** | Accès concurrent multi-process limité (NON VÉRIFIÉ précisément, signalé par plusieurs comparatifs 2026) — pas pour la charge centrale multi-agents |
| **ParadeDB** (`pg_search`, BM25 dans Postgres) | github.com/paradedb/paradedb | **AGPL-3.0 + licence commerciale duale** (raw LICENSE 200 ; contact sales@paradedb.com confirmé par WebSearch) | Actif, BM25/agrégations prod-ready, hybride natif "bientôt" (WebSearch 2026) | Donnerait un vrai BM25 (Tantivy/Lucene-like) directement dans Postgres, au lieu du `tsvector` natif | **Risque AGPL signalé** : soit conteneur Postgres séparé non modifié derrière frontière réseau, soit licence commerciale avant vendoring | **M** (si isolé en sidecar) | Ne pas l'intégrer dans le même processus Postgres que le reste sans lever le doute AGPL/juridique d'abord — **par défaut, différer au profit du FTS natif Postgres (zéro risque)** |
| **Neo4j Community** (backend Graphiti) | github.com/neo4j/neo4j | **GPLv3** (raw `LICENSE.txt`, 200, vérifié branche `dev`) | Très mature, Cypher standard | Backend graphe le plus documenté pour Graphiti | Conteneur Docker séparé, consommé via Bolt (GPL n'a **pas** la clause réseau de l'AGPL → consommer un Neo4j non modifié par API est encore plus sûr qu'un AGPL en réseau) | **S** | Empreinte mémoire plus lourde qu'une base graphe embarquée |
| **FalkorDB** (backend Graphiti alternatif) | github.com/FalkorDB/FalkorDB | **SSPL v1** (MongoDB) — raw LICENSE, 200 | Contribué nativement à Graphiti (blog.getzep.com), léger, module Redis | Perf/latence intéressantes pour un usage agent-memory | idem sidecar | **S** techniquement | **Licence source-available à signaler explicitement** (catégorie que le brief demande de flaguer) : la clause de service de la SSPL peut se déclencher si OPSYS revend une fonctionnalité équivalente en SaaS à ses clients PME — **faire trancher par juriste avant SaaS multi-clients** ; en interne mono-client (le rénovateur), risque faible mais non nul |
| **Kùzu** (backend Graphiti embarqué) | github.com/kuzudb/kuzu | **MIT** (raw LICENSE, 200) | **Signal de dépréciation trouvé** (titre d'article tiers « Kuzu Is Deprecated », NON VÉRIFIÉ officiellement — à confirmer avant d'y bâtir quoi que ce soit) | Aurait été l'option idéale (embarqué, un seul fichier, MIT, pas de conteneur en plus) | — | — | **Ne pas retenir tant que le statut de maintenance n'est pas confirmé** sur le repo officiel |

---

## 4. Embeddings et rerankers (FR multilingue)

Toutes les licences ci-dessous sont vérifiées via les **metadata Hugging Face** (`license:` dans les tags du
modèle, source primaire et faisant foi pour un poids de modèle).

| Modèle | Licence (vérifiée HF) | Contexte | Apport | Risque |
|---|---|---|---|---|
| **BAAI/bge-m3** | **MIT** | 8192 tokens, dense+sparse+ColBERT multi-vecteurs en un seul modèle, 100+ langues dont le FR | **Choix par défaut auto-hébergé** : permissif, tourne en CPU pour un volume modéré (quantifiable en ONNX/int8) | Aucun de licence |
| **intfloat/multilingual-e5-large** | **MIT** | 100+ langues | Alternative plus légère à bge-m3 si CPU très contraint | Aucun de licence |
| **nomic-ai/nomic-embed-text-v1.5** | **Apache-2.0** | Anglais principalement (la variante multilingue est `nomic-embed-text-v2-moe`, non vérifiée cette session) | Embeddings Matryoshka (troncature dimensionnelle sans réentraînement) — utile si l'anglais domine un sous-corpus (docs techniques fournisseurs) | Ne pas l'utiliser comme *seul* embedder FR sans vérifier v2-moe |
| **jinaai/jina-embeddings-v3** | **CC-BY-NC-4.0** | 8192 tokens, très bon en FR | — | **Non-commercial** : utilisable seulement via l'API payante Jina (pas de vendoring des poids en usage commercial auto-hébergé) |
| **jinaai/jina-embeddings-v4** | **Qwen Research License** (hérité de Qwen2.5-VL-3B — le tag HF `cc-by-nc-4.0` initial était une erreur, cf. [discussion HF](https://huggingface.co/jinaai/jina-embeddings-v4) et WebSearch) | Multimodal (texte+image) | — | **À proscrire totalement en self-host commercial** — aucune licence commerciale n'existe pour cette base, contrairement à v3 |
| **BAAI/bge-reranker-v2-m3** | **Apache-2.0** | Multilingue, cross-encoder léger | **Choix par défaut auto-hébergé** — tourne en CPU pour un reranking top-50→top-8 | Aucun de licence |
| **jinaai/jina-reranker-v2-base-multilingual** | **CC-BY-NC-4.0** | — | — | Même restriction que jina-embeddings-v3 : API payante uniquement |
| **Cohere Rerank** (API) | Propriétaire (service, pas un poids à vendoriser) | — | Qualité de pointe en option cloud de secours si le budget tokens/appels le permet | Coût par appel — à router via le budget/cache déjà prévu par le projet, jamais en défaut |
| **API cloud génériques** (OpenAI `text-embedding-3-*`, Voyage AI `voyage-3`/`voyage-multilingual-2`) | Propriétaire | — | Option « tier GPU/cloud » quand la qualité self-host plafonne | Coût récurrent, sortie de données hors VPS (vérifier Loi 25 avant d'envoyer des données clients) |

---

## 5. Chunking, ingestion de documents, OCR

| Brique | URL / source | Licence | Apport | Intégration | Effort | Risque |
|---|---|---|---|---|---|---|
| **Contextual Retrieval** (Anthropic) | Technique + cookbook officiel ([anthropic.com/engineering/contextual-retrieval](https://www.anthropic.com/engineering/contextual-retrieval), [platform.claude.com/cookbook](https://platform.claude.com/cookbook/capabilities-contextual-embeddings-guide)) | N/A (technique, pas un package) | Un LLM génère 50-100 tokens de « contexte de situation » par chunk (à partir du document entier en cache) avant embedding + indexation BM25. Chiffres publiés : **-35 %** d'échec de récupération top-20 (contextual embeddings seuls), **-49 %** (+ BM25 contextuel), **-67 %** (+ reranking) | Patron de pipeline à coder en Python, appel LLM **avec cache de prompt** (le document entier reste en cache, seul le chunk change) | **S** (patron) | Coût si mal implémenté sans cache — l'économie de tokens (exigence dure #3) dépend entièrement de l'usage effectif du cache de prompts |
| **Late Chunking** (Jina AI) | github.com/jina-ai/late-chunking | **Apache-2.0** (raw LICENSE, 200) | Encode le document entier d'abord (embedder long-contexte type bge-m3), puis pool par chunk — préserve le contexte inter-chunks **sans appel LLM supplémentaire**, donc moins cher que Contextual Retrieval | Patron de code, réutilisable avec bge-m3 (licence propre, contrairement aux modèles Jina) | **S** | Nécessite un embedder à grand contexte (bge-m3 8192 convient) |
| **Docling** | github.com/docling-project/docling (ex DS4SD, désormais LF AI & Data) | **MIT** (raw LICENSE + badge README, 200) | Parsing PDF/DOCX/XLSX/PPTX/HTML/images/e-mails/audio, compréhension de mise en page + **structure de tableaux**, **OCR étendu**, VLM (GraniteDocling), **exécution locale pour données sensibles** (air-gapped — clé pour Loi 25), serveur API (`docling-serve`), serveur MCP, intégrations LangChain/LlamaIndex/Haystack | Dépendance pip, ou service sidecar via `docling-serve` | **S** | Coût CPU pour l'OCR/VLM sur gros volumes — prévoir la file d'attente asynchrone (M8 Analytics existant gère déjà ce genre de traitement batch) |
| **Unstructured** | github.com/Unstructured-IO/unstructured | **Apache-2.0** (`LICENSE.md`, raw, 200) | Alternative mature à Docling, bon support des formats bureautiques hétérogènes | Dépendance pip | **S** | Redondant avec Docling — n'en garder qu'un des deux en défaut (Docling recommandé pour l'OCR+tableaux+local) |
| **MarkItDown** (Microsoft) | github.com/microsoft/markitdown | **MIT** (raw LICENSE, 200) | Conversion rapide et légère Office/HTML → Markdown, utile pour les cas simples ne nécessitant pas la compréhension de mise en page de Docling | Dépendance pip | **S** | Moins riche que Docling sur les PDF scannés/tableaux complexes — à réserver aux formats simples |

---

## 6. Mémoire temporelle / graphe d'entreprise, oubli, provenance et droits d'accès (Loi 25)

**Temporel/graphe** : Graphiti (§1, Apache-2.0) est la seule brique OSS trouvée avec un **modèle bi-temporel
natif** (distinction entre le moment où un fait était vrai et le moment où il a été invalidé) — exactement
la sémantique requise pour « client a changé d'adresse », « prix du matériau a changé le X », « décision
Y a été révisée le Z ». Cognee (Apache-2.0) complète en amont pour construire un graphe à partir de documents
statiques (contrats, catalogues) — rôle distinct, pas redondant.

**Oubli/consolidation** : aucune des briques évaluées n'offre un « forget » réglementaire prêt à l'emploi ;
c'est un mécanisme à construire dans le port M10 lui-même :
- Chaque écriture mémoire porte des métadonnées de provenance obligatoires (`source_doc_id`, `ingested_at`,
  `access_scope` — tenant/département/rôle, `retention_until`).
- Un job de **consolidation** périodique (M8 Analytics héberge déjà DuckDB/Parquet pour ce type de batch)
  résume/compacte les faits Mem0 anciens et referme les intervalles de validité Graphiti expirés — logique
  d'« oubli actif » plutôt que suppression brutale, sauf demande d'effacement.
- Une **suppression en cascade** sur `retention_until` ou sur demande d'effacement (Loi 25, art. 28) doit
  toucher en une seule transaction : ligne Postgres (pgvector), fait Mem0, nœud/arête Graphiti, chunk source
  Docling — d'où l'intérêt de garder Postgres comme registre de vérité (clé étrangère unique) même quand
  Qdrant/Graphiti sont utilisés en aval.

**Provenance et droits d'accès** : filtrage multi-tenant appliqué à *toutes* les couches de la recette
(RLS Postgres pour pgvector/FTS, `payload` filtré pour Qdrant, `tenant`/`workspace` pour Mem0/Graphiti/Honcho)
— jamais une seule couche qui isole, par défense en profondeur.

**Loi 25 (vérifié WebSearch, [CAI Québec](https://www.cai.gouv.qc.ca/protection-renseignements-personnels/sujets-et-domaines-dinteret/principaux-changements-loi-25), [augureai.ca](https://augureai.ca/fr/blog/law-25-ai-compliance-guide-quebec))** : toutes les dispositions sont en
vigueur en 2026 (volets sept. 2023 et sept. 2024). Exigences directement actionnables pour M10 :
- **Minimisation** : la collecte se limite aux fins déclarées — le port mémoire doit exposer une politique
  explicite « pourquoi cette info est mémorisée » par département, pas une ingestion tout-venant.
- **Retrait du consentement / droit à l'effacement (art. 28)** : mécanisme de suppression ci-dessus.
- **Décision automatisée** : si un agent M10/M3/M9 influence une décision ayant un effet sur une personne,
  informer et permettre une révision humaine — cohérent avec la règle déjà en place chez OPSYS (« M3 : prix
  bloqué sans référence d'échelle » = un humain reste dans la boucle sur les décisions à enjeu).

---

## 7. Évaluation RAG

| Outil | URL | Licence (vérifiée) | Rôle | Statut 2026 |
|---|---|---|---|---|
| **RAGAS** | github.com/explodinggradients/ragas | **Apache-2.0** (raw LICENSE, 200) | Métriques sans référence notées par LLM : *faithfulness*, *answer relevancy*, *context precision*, *context recall* — pour scorer en batch un échantillon de trafic réel | Maintenu par ExplodingGradients (WebSearch, actif) |
| **TruLens** | github.com/truera/trulens | **MIT** (raw LICENSE, 200) | « RAG triad » (context relevance, groundedness, answer relevance) + traçage/dashboard local pour déboguer une exécution précise | **Racheté par Snowflake (ex-TruEra), toujours open source et auto-hébergeable** (WebSearch) — pas abandonné |
| **Jeu de tests maison** | — | — | Recall@k, faithfulness, latence p50/p95, coût par requête (tokens+appels reranker) sur un jeu de questions/réponses **propre à OPSYS** (devis types, questions Loi 25, cas M3/M5) | — |

Point de méthode important, cohérent avec le principe **« C — CLAIMS UNVERIFIED »** déjà inscrit dans
`AGENTS.md` de ce projet : les chiffres de benchmarks mémoire trouvés en recherche sont contradictoires
d'une source à l'autre (ex. Zep annonce 63.8 % sur LongMemEval contre 49.0 % pour Mem0, mais un tiers
indépendant — Maximem — retrouve 73.8 % pour Mem0 avec son propre harnais). **Aucun chiffre vendor ne doit
être relayé comme acquis** : RAGAS + jeu de tests maison sur les cas réels d'OPSYS est la seule preuve
recevable avant un choix définitif de fournisseur mémoire, exactement comme le tally scellé fait déjà
autorité sur le code plutôt que la mémoire d'un modèle.

---

## 8. Architecture RAG PREMIUM recommandée

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  M1..M9 (départements)  ──►  PORT MÉMOIRE (M10, Python, interface stable)    │
└─────────────────────────────────────────────────────────────────────────────┘
        │ ingest()            │ remember()/recall()        │ query()
        ▼                     ▼                             ▼
┌───────────────┐   ┌──────────────────────┐   ┌─────────────────────────────┐
│  INGESTION     │   │  MÉMOIRE D'AGENT      │   │  RAG (recherche documentaire)│
│  Docling (MIT) │   │  Mem0 OSS (Apache-2.0)│   │  chunking : Contextual       │
│  OCR+tableaux  │   │   → faits par tenant   │   │  Retrieval (cache prompts)   │
│  local/air-gap │   │  Graphiti (Apache-2.0) │   │  + Late Chunking (bge-m3)    │
│                │   │   → graphe temporel    │   │                              │
└───────┬────────┘   └──────────┬───────────┘   └───────────────┬─────────────┘
        │                       │                                │
        ▼                       ▼                                ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  INDEXATION — PostgreSQL existant (psycopg)                                  │
│  • pgvector + pgvectorscale (StreamingDiskANN)  : vecteurs denses            │
│  • FTS natif (tsvector/GIN)                     : lexical (BM25≈), 0 risque  │
│  • RLS Postgres                                 : multi-tenant + provenance │
│  • Graphiti → Neo4j Community (GPLv3, sidecar Docker, service réseau OK)     │
│  option scale-out : Qdrant (Apache-2.0) sidecar si l'ANN Postgres sature     │
└─────────────────────────────────────────────────────────────────────────────┘
        │
        ▼  fusion RRF (dense pgvector ⊕ FTS lexical)
┌─────────────────────────────────────────────────────────────────────────────┐
│  EMBEDDINGS : BAAI/bge-m3 (MIT, CPU/ONNX)      RERANK : bge-reranker-v2-m3   │
│  fallback léger : multilingual-e5-large (MIT)  fallback cloud : Cohere Rerank│
└─────────────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  GÉNÉRATION — inchangé : routage LiteLLM existant (crew-*/opus/sonnet/haiku) │
└─────────────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  ÉVALUATION continue : RAGAS + TruLens (dashboard) + jeu de tests maison     │
│  (recall@k, faithfulness, latence, coût) — job périodique, alimente M8      │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Profil VPS sans GPU (par défaut)** : tout ce qui précède tourne en CPU — bge-m3/bge-reranker-v2-m3
quantifiés ONNX/int8, Docling en mode CPU (OCR plus lent mais fonctionnel), Postgres+pgvectorscale et Neo4j
Community en conteneurs docker-compose classiques. Volumes visés : quelques dizaines de milliers de
documents/chantiers, débit modéré — largement dans l'enveloppe d'un VPS 8-16 Go RAM / 4-8 vCPU.

**Option GPU** : bascule progressive, module par module, sans changer l'interface du port mémoire —
embedder plus gros (nomic-embed-text-v2-moe ou un embedder API), Docling en mode VLM accéléré, reranking
par lots plus larges. Le port mémoire expose un adaptateur, jamais un appel en dur à un modèle — c'est ce
qui rend la bascule CPU→GPU (ou self-host→API) transparente pour M1..M9.

---

## 9. Recette d'intégration dans le Core (port mémoire M10)

1. **Vendoriser le squelette Hermes Agent** : copier/adapter `agent/memory_provider.py` (ABC) et
   `agent/memory_manager.py` (fan-out, lifecycle, hooks `on_session_end`/`on_pre_compress`/`on_memory_write`)
   comme base du port M10. Lever la limite « un seul provider externe actif » du design d'origine — OPSYS a
   besoin de Mem0 (faits) **et** Graphiti (graphe temporel) simultanément, chacun sur son propre hook.
2. **Écrire 3 adaptateurs (providers) OPSYS** suivant cette interface :
   - `PgMemoryProvider` : Mem0 en mode OSS, LLM+embedder configurables (Ollama local par défaut, API en
     option), vector store = pgvector du Postgres existant.
   - `GraphitiProvider` : écritures d'événements/décisions (Work Completion Trigger de M4, décisions de M9,
     etc.) vers Graphiti → Neo4j Community sidecar.
   - `RagProvider` : pipeline ingestion (Docling) → chunking (Contextual Retrieval / Late Chunking) →
     indexation (pgvector+FTS, RRF) → rerank (bge-reranker-v2-m3) → `query()`.
3. **Un seul schéma de provenance** partagé par les trois adaptateurs (`tenant_id`, `source_doc_id`,
   `access_scope`, `retention_until`) porté par des colonnes Postgres — la suppression Loi 25 et
   l'expiration de rétention deviennent une seule transaction SQL qui se propage aux trois.
4. **Cache de prompts** systématique sur tout appel LLM du pipeline (contexte de chunking, extraction Mem0,
   extraction d'entités Graphiti) — c'est le principal levier d'économie de tokens (exigence dure #3) sur
   cette brique, avant même le choix de modèle.
5. **Docker compose** : ajoute 1-2 services au stack existant (Neo4j Community ; Qdrant en option seulement
   si activé) — pgvector/pgvectorscale vivent dans le Postgres déjà présent, zéro service supplémentaire.
6. **Dashboard central** (exigence dure #2) : M10 expose un panneau de config unique — provider mémoire actif
   par département, budget tokens par pipeline (ingestion/rerank/génération), état de rétention/effacement en
   attente, métriques RAGAS/TruLens du dernier run.

---

## 10. Ce que M10 doit fournir aux autres départements

- **Une API Python unique** (`remember()`, `recall()`, `forget()`, `query()`, `ingest()`) — les modules
  M1-M9 ne connaissent jamais Mem0/Graphiti/pgvector directement, seulement le port.
- **PREFLIGHT/POSTFLIGHT** (déjà prévu pour M10) : hooks avant/après chaque action d'agent qui lisent le
  contexte pertinent (recall) et écrivent la trace de décision (remember) — calqués sur les hooks
  `on_turn_start`/`on_session_end` déjà présents dans le patron Hermes Agent.
- **Journal de décisions** horodaté et bi-temporel (Graphiti) consultable par M9 (scénarios stratégiques)
  et par l'audit Loi 25.
- **Budgets tokens par département**, appliqués au niveau du port (pas laissés à la discrétion de chaque
  module) — condition de l'exigence dure #3.
- **Garanties de cloisonnement** : aucun module ne peut lire la mémoire d'un autre tenant/département sans
  déclaration explicite d'`access_scope` — vérifiable par un test d'intégration dédié dans `scripts/tests`.
- **Effacement en cascade** exposé comme une fonction unique (`forget(subject_id)`) que M2 (droit à
  l'oubli d'un client) ou M5 (fin de rétention comptable légale) peuvent appeler sans connaître l'implémentation.

---

## Ingrédients retenus (classés)

**Niveau 1 — cœur, day-1** :
1. pgvector + pgvectorscale (PostgreSQL License) — indexation vectorielle, dans le Postgres existant.
2. FTS natif Postgres — lexical, zéro risque de licence.
3. Mem0 OSS (Apache-2.0) — mémoire de faits par agent/tenant.
4. Graphiti (Apache-2.0) + Neo4j Community (GPLv3, sidecar) — graphe temporel d'entreprise.
5. Docling (MIT) — ingestion, OCR, tableaux, exécution locale.
6. BAAI/bge-m3 (MIT) + BAAI/bge-reranker-v2-m3 (Apache-2.0) — embeddings/reranking FR multilingue.
7. Contextual Retrieval (technique Anthropic, cache de prompts) + Late Chunking (Apache-2.0, jina-ai/late-chunking) — chunking.
8. RAGAS (Apache-2.0) + TruLens (MIT) + jeu de tests maison — évaluation continue.
9. Squelette `MemoryProvider`/`MemoryManager` de Hermes Agent (MIT) — patron du port mémoire M10.

**Niveau 2 — options d'échappement, activées si un besoin dépasse le niveau 1** :
10. Qdrant (Apache-2.0) — sidecar si l'ANN Postgres sature à l'échelle.
11. Cognee (Apache-2.0) — graphe de connaissances issu de documents statiques (contrats/catalogues).
12. Honcho (AGPL serveur / Apache-2.0 SDK) — modélisation utilisateur cross-session pour M1/M2, en service séparé uniquement.
13. Weaviate (BSD-3-Clause + module `wl/` propriétaire à vérifier) — si le besoin de multi-tenance physique ou de fusion BM25+dense native dépasse ce que Postgres+Qdrant offrent.
14. Cohere Rerank / API embeddings (propriétaire) — secours cloud si la qualité self-host plafonne, jamais par défaut (coût + sortie de données).

**Écarté / à ne pas retenir en l'état** :
- jina-embeddings-v3/v4 et jina-reranker-v2 en self-host commercial (licences CC-BY-NC-4.0 / Qwen Research License — non commercial).
- ParadeDB (`pg_search`) tant que le choix AGPL-vs-licence-commerciale n'est pas tranché — le FTS natif Postgres couvre le besoin de départ.
- FalkorDB tant que la lecture juridique de la clause de service SSPL (risque en scénario SaaS multi-clients) n'est pas validée.
- Kùzu tant que son statut de maintenance n'est pas confirmé sur le repo officiel.
- Letta et R2R comme dépendances lourdes — retenus seulement comme patrons d'architecture à lire, pas à vendoriser.

---

## Sources principales (non exhaustif — voir liens en ligne dans les tableaux ci-dessus)

- Licences vérifiées en direct : `raw.githubusercontent.com/{mem0ai/mem0, getzep/graphiti, letta-ai/letta,
  topoteretes/cognee, plastic-labs/honcho, plastic-labs/honcho-python, plastic-labs/honcho-node,
  HKUDS/LightRAG, infiniflow/ragflow, SciPhi-AI/R2R, deepset-ai/haystack, run-llama/llama_index,
  microsoft/graphrag, neuml/txtai, pgvector/pgvector, timescale/pgvectorscale, qdrant/qdrant,
  weaviate/weaviate, lancedb/lancedb, paradedb/paradedb, docling-project/docling,
  Unstructured-IO/unstructured, microsoft/markitdown, explodinggradients/ragas, truera/trulens,
  openclaw/openclaw, jina-ai/late-chunking, FalkorDB/FalkorDB, kuzudb/kuzu, neo4j/neo4j}/LICENSE*` (HTTP 200 sur chacun).
- Fiches modèles Hugging Face (champ `license`) : BAAI/bge-m3, intfloat/multilingual-e5-large,
  nomic-ai/nomic-embed-text-v1.5, jinaai/jina-embeddings-v3, jinaai/jina-embeddings-v4, BAAI/bge-reranker-v2-m3,
  jinaai/jina-reranker-v2-base-multilingual.
- Inspection directe du code : `scratchpad/clones/hermes-agent/agent/memory_provider.py`,
  `agent/memory_manager.py`, `plugins/memory/mem0/*`, `plugin-catalog/*.yaml`,
  `website/docs/user-guide/features/memory-providers.md`.
- [Anthropic — Contextual Retrieval](https://www.anthropic.com/engineering/contextual-retrieval) ;
  [Timescale — pgvectorscale README](https://github.com/timescale/pgvectorscale) ;
  [Zep — Graphiti FalkorDB support](https://blog.getzep.com/graphiti-knowledge-graphs-falkordb-support/) ;
  [CAI Québec — Loi 25](https://www.cai.gouv.qc.ca/protection-renseignements-personnels/sujets-et-domaines-dinteret/principaux-changements-loi-25).
- Signaux de maturité (stars/activité), datés et approximatifs car `api.github.com` bloqué sans `add_repo`
  dans cette session : florinelchis (Medium, Top 10 RAG Frameworks Jan. 2026), releasealert.dev, dev.to,
  Github-Ranking-AI — recoupés quand plusieurs sources concordaient, marqués « NON VÉRIFIÉ précisément » sinon.
