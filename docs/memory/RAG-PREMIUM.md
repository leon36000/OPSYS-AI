# RAG PREMIUM — mémoire d'entreprise OPSYS

> **Statut** : conception de référence, prérequis de la couche mémoire (ADR-0006 §6). La phase 1 est
> implémentée et testée dans `src/opsys/memoire/`.
> **Décision** : [ADR-0007](../decisions/ADR-0007-core-openclaw.md) — le Core OPSYS est **OpenClaw**
> (release épinglée `v2026.9.6`), plus Hermes.
> **Sources** :
> - R4 : `docs/research/R4-memory-rag.md` (licences vérifiées, ingrédients) ;
> - docs OpenClaw lues dans le clone `openclaw/openclaw`, commit `2d39f2f` du 2026-09-27 (branche
>   principale ; à recontrôler contre la release épinglée `v2026.9.6` avant la mise en production) :
>   `docs/concepts/memory-architecture.md`, `dreaming.md`, `memory-provenance.md`, `active-memory.md`,
>   `memory-search.md`, `memory-builtin.md`, `memory-honcho.md`, `docs/reference/memory-config.md`,
>   `docs/plugins/hooks.md` ;
> - LPRPSP (RLRQ c. P-39.1, LegisQuébec) : articles 3.3, 12.1, 17, 23 et 28 cités mot pour mot au §6.
>
> Les chiffres de performance ci-dessous sont des **cibles** à mesurer au banc, jamais des résultats
> annoncés par un fournisseur.

## 1. Objectifs mesurables

| Axe | Métrique | Cible phase 1 | Cible phase 2 | Mesure |
|---|---|---|---|---|
| Rappel | rappel@5 : part des questions du jeu d'or dont au moins un fragment attendu figure dans les 5 premiers | ≥ 0,85, et hybride > plein texte seul | ≥ 0,92 (avec rerank) | banc jeu d'or FR (§9) |
| Ordre | MRR@10 | ≥ 0,70 | ≥ 0,80 | idem |
| Fidélité | RAGAS *faithfulness* : part des affirmations de la réponse appuyées par le contexte cité | sans objet (pas de génération dans la couche B) | ≥ 0,90 | RAGAS sur échantillon réel |
| Exactitude | chiffres (prix, date, quantité) d'une réponse qui ne viennent pas d'un outil déterministe | 0 | 0 | revue d'échantillon + TruLens |
| Latence | p95 de `rechercher` côté serveur, 100 k fragments, VPS 4 vCPU sans GPU | ≤ 150 ms hors embedding de la requête ; ≤ 600 ms avec | ≤ 1,5 s avec rerank du top-30 | banc de charge (mesure indicative au §10) |
| Coût de rappel | tokens injectés par appel de `opsys_memoire_rechercher` | ≤ 1 300 (≤ 4 000 caractères de texte) | idem | calcul sur la sortie de l'outil |
| Coût d'indexation | tokens LLM par document ingéré | 0 | ≤ 100 tokens générés par fragment, document en cache de prompt | `jetons.enregistrer_usage` |
| Conformité | fragments résiduels après un effacement Loi 25 | 0 dans la couche B | 0 dans les deux couches, à la limite près décrite au §6.3 | test automatisé + procédure §6.3 |

## 2. Architecture à deux couches

```
 Canaux (SMS, courriel, chat, patron)
        │
        ▼
 ┌─ OpenClaw (Core) : un agent par département (m01…m10) ────────────────────────────────────┐
 │ COUCHE A — mémoire d'agent native, par agent, non modifiée                                 │
 │   instructions AGENTS.md · noyau curé MEMORY.md / USER.md · épisodique (notes datées,       │
 │   transcriptions) · intentions permanentes · revue DREAMS.md                                │
 │   provenance owner | agent | untrusted | system · dreaming light → REM → deep               │
 │   rappel voie 1 (0 appel modèle) · voie 2 Active Memory (escalade)                          │
 │   plugin OPSYS : hooks before_prompt_build / before_tool_call / after_tool_call / agent_end │
 └──────────────┬─────────────────────────────────────────────────────────────────────────────┘
                │ MCP « opsys » (streamable HTTP + jeton, ou stdio) — sortie = contenu untrusted
                ▼
 ┌─ COUCHE B — base de connaissances d'entreprise OPSYS (src/opsys/memoire) ─────────────────┐
 │ opsys_memoire_rechercher (T0) · opsys_memoire_ajouter (T1) · opsys_memoire_oublier (T3)    │
 │   → Capacites : politique T0–T3, file d'approbation, budget, troncature                    │
 │ PostgreSQL 17, schéma `memoire` : documents · fragments · journal_effacements              │
 │   plein texte FR (tsvector `memoire.francais` = unaccent + french_stem, GIN)               │
 │   vecteurs bge-m3 1024 d (pgvector, HNSW cosinus) → fusion RRF → rerank (phase 2)          │
 │ ingestion Docling → découpage → embeddings (/v1/embeddings, local par défaut)              │
 └────────────────────────────────────────────────────────────────────────────────────────────┘
```

### 2.1 Couche A — mémoire d'agent OpenClaw (native)

OPSYS l'utilise telle quelle, par configuration. Ce qu'elle apporte :

| Mécanisme | Comportement (docs OpenClaw) | Usage OPSYS |
|---|---|---|
| **Niveaux** | Instructions (humain seul) ; noyau curé `MEMORY.md`/`USER.md`, écrit par la consolidation ou sur demande directe, injecté si sa provenance est éligible ; épisodique (notes `memory/AAAA-MM-JJ.md`, transcriptions), jamais injecté, cherchable ; prospectif (intentions en SQLite, cron) ; revue (`DREAMS.md`) | Mémoire de travail de chaque département : préférences du patron, façons de faire, contexte des conversations |
| **Provenance** | Colonnes SQLite que le modèle ne peut pas écrire : origine `owner` / `agent` / `untrusted` / `system`, type de session, horodatage observé, clé de supplantation. Provenance indéterminable : jamais `owner`. Les sessions cron, heartbeat et sous-agent ne produisent aucun candidat durable. Le contenu rappelé n'est jamais ré-extrait. | Base de la frontière de confiance entre couches (§2.3) |
| **Dreaming** | Balayage planifié (défaut `0 3 * * *`) : light et REM préparent sans écrire ; deep promeut dans `MEMORY.md` après une porte déterministe (score, fréquence de rappel, diversité des requêtes), les candidats `untrusted`/`system` étant exclus **avant** tout prompt. Réécriture validée (perte ≤ 25 % des entrées par défaut, budget bootstrap), pré-image conservée, résumé dans `DREAMS.md`. | Consolidation de la mémoire de travail. Modèle de dreaming sur un palier `rapide` ou `local` |
| **Rappel à deux voies** | Voie 1 sans appel modèle : injection du noyau curé, `memory_search` hybride (BM25 + vecteur) × décroissance de récence (demi-vie 30 jours) × importance, puis MMR ; déclencheurs (score ≥ 0,72, au plus 3 par tour) réservés au noyau curé. Voie 2 (Active Memory, mode `escalate`) : sous-agent de rappel seulement si le message montre une intention de rappel et que la voie 1 n'a rien de fort. | Voie 1 par défaut. Voie 2 activée pour M1 (réception) et M2 (CRM), où les questions « on s'était dit quoi ? » sont fréquentes |
| **Oubli** | `openclaw memory forget --agent <id> --session / --participant / --hook-source [--dry-run] --json` retire les entrées tracées, lignes de corpus, fragments d'index (plein texte et vecteurs), pré-images, et marque les sessions « oubliées » pour les ingestions futures. Politique d'admission `memoryPolicy.excludeSessions` : exclusion prospective. | Volet A de la procédure d'effacement Loi 25 (§6.3) |

Limites documentées par OpenClaw, reprises telles quelles : l'oubli ne supprime ni les transcriptions
d'origine (`openclaw sessions delete` est une opération distincte), ni les paraphrases non tracées, ni les
copies externes. « Un aperçu vide n'est pas un certificat. » Par défaut, `tools.sessions.visibility` vaut
`all` et l'accès inter-agents est actif : OPSYS doit régler `tools.agentToAgent.enabled: false` (ou une liste
d'autorisations) pour cloisonner les départements.

### 2.2 Couche B — base de connaissances d'entreprise OPSYS

C'est le système de référence des connaissances de l'entreprise : clients, chantiers, estimations,
barèmes, décisions, documents ingérés. Elle est gouvernée (portée, sensibilité, rétention, effacement
journalisé) et exposée en MCP par trois outils, soumis aux politiques T0–T3 de `Capacites`.

### 2.3 Coopération des deux couches

1. **Autorité.** Un fait d'entreprise vit dans la couche B. La couche A ne détient qu'une mémoire de
   travail. Un agent ne recopie pas un renseignement personnel de la couche B dans `MEMORY.md` : il le
   redemande à la couche B, qui applique alors la rétention et l'effacement.
2. **Frontière de confiance.** OpenClaw marque le texte des outils MCP comme contenu externe non fiable
   (notes de version 2026.8.1, « security-and-privacy »). Ce contenu :
   - est classé `untrusted` ;
   - n'est jamais injecté automatiquement par la voie 1 ;
   - n'est jamais promu par dreaming dans `MEMORY.md`/`USER.md` : la porte est structurelle, pas un score.

   Aucune promotion en mémoire curée sans validation humaine. C'est voulu : cela empêche les copies non
   gouvernées et l'empoisonnement de la mémoire par un document ingéré.
3. **Remontée A → B.** Uniquement par `opsys_memoire_ajouter`, outil T1 : il passe par la file
   d'approbation en mode `ombre`. La provenance est explicite, par exemple
   `source = "openclaw:m03-estimation:session:<id>"`. Un fragment `personnelle` exige `sujets` et `expire_le`.
4. **Descente B → A.** À la demande (outil) ou par le PREFLIGHT de M10 (§8). Le texte rendu est une
   donnée à citer, jamais une instruction.
5. **Un seul service d'embeddings.** bge-m3, servi par un endpoint `/v1/embeddings` OpenAI-compatible
   sur le VPS, alimente les deux couches :
   - OpenClaw : `memory.search.provider: "openai-compatible"`, `model`, `remote.baseUrl` ;
   - OPSYS : `OPSYS_EMBEDDINGS_URL` et `OPSYS_EMBEDDINGS_MODELE`.

   Un seul modèle est chargé en RAM. OpenClaw échoue fermé si un fournisseur explicite tombe ; la
   couche B passe en mode plein texte explicite (§3.5).
6. **Effacement dans les deux couches** : procédure unique au §6.3.
7. **M10 orchestre** le PREFLIGHT et le POSTFLIGHT (§8).

### 2.4 Mémoire d'agent : faits, épisodes, procédures

| Type | Couche A (OpenClaw) | Couche B (OPSYS) | Phase |
|---|---|---|---|
| **Faits** | `MEMORY.md` (promu par dreaming), `USER.md` (directives du patron, supplantées en place) | Fragments par portée (`clients`, `chantiers`, `baremes`…), attributs, sujets | 1 |
| Faits temporels | Clé de supplantation | **Graphiti** (Apache-2.0) + Neo4j Community (GPLv3, service séparé non modifié) : validité « vrai de… à… » pour adresses, prix, décisions révisées | 2 |
| **Épisodes** | Notes datées, transcriptions (cherchables, jamais injectées) | Registre de décisions append-only de M10 + fragments de portée `decisions` écrits au POSTFLIGHT | 1 (registre), 2 (fragments) |
| **Procédures** | `AGENTS.md`, skills, intentions permanentes | Skills des départements versionnées dans git ; la couche B ne les indexe pas | 1 |
| Faits extraits par LLM | — | **Mem0** OSS (Apache-2.0) sur le même pgvector : option seulement, car il recouvre dreaming | option |

## 3. Pipeline de la couche B

1. **Ingestion — Docling (MIT).**
   - Exécution locale, via `docling-serve` en service séparé : les documents ne quittent pas le VPS.
   - PDF, DOCX, XLSX, HTML, images, OCR.
   - Tableaux restitués en Markdown.
   - Un fichier donne un document (`source` = URI stable, `titre`). Réingérer est idempotent (§4).
2. **Découpage.**
   - Fragments structurels issus de Docling (section, tableau), 300 à 800 tokens.
   - Phase 1 : **préfixe de contexte déterministe** (titre › chemin de section) ajouté au texte indexé.
     Coût LLM nul.
   - Phase 2, **Contextual Retrieval** (technique Anthropic) pour les corpus à forte valeur (contrats,
     devis) : 50 à 100 tokens de contexte par fragment, générés avec le document entier en cache de
     prompt. Chiffres publiés par Anthropic, à revérifier sur notre jeu d'or : −35 % d'échecs top-20
     (embeddings contextuels), −49 % (+ BM25), −67 % (+ rerank).
   - Phase 2, **Late Chunking** (patron jina-ai, Apache-2.0) : il exige les embeddings de *tokens*, ce qu'un
     endpoint `/v1/embeddings` standard ne fournit pas. Il suppose donc un worker local bge-m3
     (FlagEmbedding/ONNX), coûteux en CPU sur 8 192 tokens.
   - L'API refuse un fragment de plus de 20 000 caractères.
3. **Embeddings — BAAI/bge-m3 (MIT).**
   - Dense, 1 024 dimensions, 8 192 tokens de contexte, multilingue dont le français.
   - Client stdlib `embeddings.py` : `POST {OPSYS_EMBEDDINGS_URL}/embeddings`, modèle et clé par variables
     d'environnement, lots de 32. Les erreurs sont explicites : HTTP, délai, JSON, dimension, valeurs
     non finies.
   - Serveur local : Ollama ou `llama-server` (MIT, déjà inscrits dans `INGREDIENTS.md`), ou TEI/Infinity.
     La licence et le support de bge-m3 sont à vérifier et à inscrire dans `INGREDIENTS.md` avant
     adoption.
   - Option cloud : un endpoint OpenAI-compatible qui sert bge-m3. Les données quittent le VPS : EFVP
     obligatoire (§6).
4. **Stockage — PostgreSQL 17 + pgvector** (§4).
   - Option **pgvectorscale** (StreamingDiskANN, PostgreSQL License) au-delà d'environ 1 M de fragments
     ou si la RAM manque.
   - Option `halfvec` : 2 056 octets au lieu de 4 104 par vecteur.
5. **Recherche hybride**, en une requête SQL :
   - voie lexicale : requête OU sur les lexèmes de la question (`memoire.francais`), classée par
     `ts_rank` ;
   - voie vectorielle : distance cosinus, HNSW, `hnsw.iterative_scan = relaxed_order` pour ne pas
     appauvrir les résultats filtrés, puis retri exact ;
   - fusion **RRF** (Cormack et al., SIGIR 2009) : `score = Σ 1/(60 + rang)` sur `max(4k, 20)` candidats
     par voie ;
   - fragments expirés invisibles dès l'échéance, même avant la purge ;
   - **mode `plein_texte` explicite** : sans embedding de requête (service non configuré ou en panne),
     la réponse porte `mode = "plein_texte"` et un avertissement. Jamais de dégradation silencieuse.
6. **Rerank — BAAI/bge-reranker-v2-m3 (Apache-2.0)**, phase 2 : cross-encoder CPU, top-30 → top-k,
   derrière un endpoint local.
7. **Génération.** Hors de la couche B : l'agent OpenClaw cite `source`. Tout chiffre vient d'un outil
   déterministe.

## 4. Modèle de données et API (phase 1)

`src/opsys/memoire/schema.sql` est idempotent. Il s'applique avec `python -m opsys.memoire migrer`, par un
rôle administrateur : l'extension `vector` n'est pas « trusted », `unaccent` l'est.

| Table | Colonnes clés | Contraintes |
|---|---|---|
| `memoire.documents` | `source` (unique), `titre`, `cree_le` | `source` non vide |
| `memoire.fragments` | `texte`, `empreinte` (sha256), `embedding vector(1024) NULL`, `tsv` (généré, `memoire.francais`), `departement`, `portee`, `sensibilite`, `sujets text[]`, `metadonnees jsonb`, `cree_le`, `expire_le` | unique `(document_id, empreinte)` ; `sensibilite ∈ {publique, interne, confidentielle, personnelle}` ; `personnelle` ⇒ `expire_le` et au moins un sujet ; `expire_le > cree_le` |
| `memoire.journal_effacements` | `effectue_le`, `demandeur`, `motif`, `filtres jsonb`, `fragments`, `documents` | jamais le texte effacé |

Index :
- HNSW `vector_cosine_ops` sur `embedding` ;
- GIN sur `tsv`, sur `sujets` et sur `metadonnees` (`jsonb_path_ops`) ;
- B-tree sur `(portee, departement)` ;
- B-tree partiel sur `expire_le`.

Les métadonnées de gouvernance sont des colonnes typées, contraintes par `CHECK`. Les attributs libres
(`client_id`, `numero_devis`…) vont dans `metadonnees`.

**API Python** (`opsys.memoire.MemoireEntreprise(url)`) :

| Méthode | Contrat |
|---|---|
| `migrer()` | Applique le schéma sous verrou consultatif. Idempotente. |
| `ajouter(texte, meta, embedding=None) -> int` | Upsert idempotent sur (source, empreinte). Refuse : clé inconnue, portée ou département mal formés, `personnelle` sans `expire_le`/`sujets`, échéance passée, vecteur de mauvaise dimension, non fini ou nul. |
| `rechercher(requete, embedding_requete, k, filtres) -> Recherche` | `filtres["portee"]` obligatoire (cloisonnement), k de 1 à 50. Renvoie `mode` (`hybride` ou `plein_texte`) et les résultats (score RRF, rangs lexical et vectoriel, provenance). |
| `oublier(filtres, *, demandeur, motif) -> int` | Effacement Loi 25 en une transaction : fragments, puis documents orphelins, puis journal. Refuse des filtres vides. |
| `purger_expires() -> int` | Supprime les fragments échus. Journalisée si elle supprime quelque chose. |
| `completer_embeddings(plongeur, *, inclure_personnelles, lot=32) -> int` | Rattrape les fragments sans vecteur après une panne du service d'embeddings. |
| `etat() -> dict` | Compteurs : documents, fragments, sans embedding, échus, personnels. |

Filtres acceptés (liste blanche ; clé inconnue = refus) : `departement`, `portee`, `sensibilite`, `source`,
`sujet` (recouvrement de `sujets`), `attributs` (contenance jsonb), `document_id`.

**Outils MCP** (`opsys.memoire.outils.outils()`) :

| Outil | Autonomie | Effet |
|---|---|---|
| `opsys_memoire_rechercher` | T0 | Recherche dans les portées de **lecture** du département appelant. k ≤ 10, extraits ≤ 800 caractères, total ≤ 4 000. |
| `opsys_memoire_ajouter` | T1 | Mémorise dans une portée d'**écriture** du département, avec provenance, sensibilité et rétention. Un fragment `personnelle` n'est vectorisé que si l'endpoint est local (`OPSYS_EMBEDDINGS_LOCAL=1`). |
| `opsys_memoire_oublier` | T3 | Efface par `sujet`, `source` ou `document_id`. Frontière humaine : toujours approuvé. |

**Configuration** :

| Variable | Rôle |
|---|---|
| `OPSYS_DATABASE_URL` | Connexion PostgreSQL. Si elle est absente, l'outil refuse explicitement. |
| `OPSYS_DEPARTEMENT` | Département appelant par défaut du processus. La plateforme peut le fixer par requête avec `outils.appeler_en_tant_que(id)`, qui est prioritaire : serveur MCP, console qui exécute une approbation. Jamais un argument du modèle. Sans lui, les outils refusent. |
| `OPSYS_EMBEDDINGS_URL` | Base OpenAI-compatible (ex. `http://embeddings:11434/v1`). Absente = mode plein texte explicite. |
| `OPSYS_EMBEDDINGS_MODELE` | Obligatoire si l'URL est définie. Aucun modèle par défaut. |
| `OPSYS_EMBEDDINGS_CLE` | Jeton Bearer, facultatif. |
| `OPSYS_EMBEDDINGS_LOCAL` | `1` si l'endpoint tourne sur le VPS. Sinon, les fragments `personnelle` ne sont pas envoyés. |

Commandes d'exploitation : `python -m opsys.memoire migrer | purger | etat | completer`.

## 5. Portées et cloisonnement

| Dimension | Porteur | Application |
|---|---|---|
| **Portée** (catégorie de connaissance) | Colonne `portee`, vocabulaire des manifestes `memoire.lecture` / `memoire.ecriture` (ex. M3 lit `clients, chantiers, estimations, baremes` et écrit `estimations`) | Outils : lecture ⊆ `memoire.lecture`, écriture ∈ `memoire.ecriture`. API : `portee` obligatoire dans `rechercher`. |
| **Département** (auteur, propriétaire) | Colonne `departement` = département appelant (`appeler_en_tant_que` ou `OPSYS_DEPARTEMENT`) | Provenance de chaque écriture ; filtre possible en lecture |
| **Client, chantier** | `sujets` = `client:<id>`, `chantier:<id>` (identifiants internes, jamais un nom ni un téléphone) | Filtre `sujet` : l'agent qui sert le client X ne voit que X. Clé de l'effacement. |
| **Agent OpenClaw** | Un agent par département, mémoire A propre | `tools.agentToAgent` restreint, `tools.sessions.visibility: "agent"` |

Phase 2 : **RLS PostgreSQL**, un rôle par département, politique sur `portee`. C'est une défense en
profondeur : aucune couche n'isole seule.

## 6. Loi 25 (LPRPSP)

### 6.1 Exigences et mécanismes

| Exigence | Texte (LPRPSP) | Couche B | Couche A |
|---|---|---|---|
| **EFVP** | Art. 3.3 : EFVP de « tout projet d'acquisition, de développement et de refonte de système d'information […] impliquant la collecte, l'utilisation, la communication, la conservation ou la destruction de renseignements personnels » | EFVP de la mémoire avant la mise en production (`docs/compliance/efvp/GABARIT-EFVP.md`) | idem |
| **Communication hors Québec** | Art. 17 : « Avant de communiquer à l'extérieur du Québec un renseignement personnel, […] doit procéder à une évaluation des facteurs relatifs à la vie privée. » | Embeddings et rerank locaux par défaut. Endpoint cloud = EFVP. `OPSYS_EMBEDDINGS_LOCAL` bloque l'envoi des fragments `personnelle`. | Idem pour `memory.search.provider` et le modèle de dreaming |
| **Minimisation** | Finalités déclarées | Portées déclarées par département. Aucune ingestion de transcriptions brutes. Clés de métadonnées en liste blanche. | Politique d'admission. Rédaction des renseignements personnels avant l'ingestion par dreaming (native). |
| **Conservation limitée** | Art. 23 : « Lorsque les fins […] sont accomplies, la personne qui exploite une entreprise doit le détruire ou l'anonymiser […] » | `expire_le` obligatoire pour `personnelle`. Fragment invisible dès l'échéance. `purger_expires` quotidien (conteneur `opsys`, `deploy/entrypoint.sh`). | Rotation des transcriptions (`sessions`) |
| **Rectification, suppression** | Art. 28 : droit d'exiger la rectification d'un renseignement « inexact, incomplet ou équivoque » ou dont la conservation n'est pas autorisée (avec l'art. 40 C.c.Q.) | Suppression : `opsys_memoire_oublier` (T3). Rectification : `oublier` le fragment erroné (par `source` ou `document_id`), puis `ajouter` la version corrigée. | `memory forget` et `sessions delete` |
| **Décision automatisée** | Art. 12.1 : informer la personne d'une décision « fondée exclusivement sur un traitement automatisé » | La mémoire n'est jamais seule à décider : prix par outil déterministe, envoi T2/T3 approuvé | — |
| **Traçabilité** | Responsabilité | `memoire.journal_effacements` (qui, quand, pourquoi, filtres, compteurs) + table `approbations` (qui a approuvé) | Rapports JSON de `memory forget` archivés |

### 6.2 Sensibilité

- `publique` : aucune contrainte.
- `interne` : réservée à l'entreprise.
- `confidentielle` : contrats, marges.
- `personnelle` : contient au moins un renseignement personnel. Elle exige `expire_le` et au moins un
  sujet, et n'est jamais vectorisée hors du VPS.

### 6.3 Procédure d'effacement d'une personne (deux couches)

Déclenchée par M2 sur demande du client ou par M5 en fin de rétention légale :

1. **Couche B** : identifier les sujets (`client:<id>`), puis demander
   `opsys_memoire_oublier(sujet=…, motif=…, demandeur=…)`. C'est un T3 : un humain approuve dans le
   dashboard. Exécution en une transaction et journalisation.
2. **Couche A**, pour chaque agent concerné : lancer
   `openclaw memory forget --agent <id> --participant <actor-id> --dry-run --json`, relire
   `sessionResolutions`, `entryKeys` et `mixedLineageEntryKeys`, puis relancer sans `--dry-run`.
3. **Transcriptions** : `openclaw sessions delete <clé> --agent <id>`. L'oubli ne les touche pas.
4. **Admission** : ajouter une règle `memoryPolicy.excludeSessions` si la source doit rester exclue.
5. **Stockage physique et sauvegardes** :
   - un `DELETE` laisse des lignes mortes jusqu'au passage d'autovacuum. Après un effacement sensible,
     lancer `VACUUM memoire.fragments` ;
   - l'effacement devient complet à la fin de la rotation des sauvegardes PostgreSQL et de l'espace de
     travail. La durée maximale de rotation est documentée dans l'EFVP.
6. **Vérification** : `rechercher(..., filtres={"portee": [...], "sujet": "client:<id>"})` doit renvoyer
   0 résultat. Relancer les aperçus `--dry-run`, archiver les rapports et consigner la clôture.

Limite assumée, reprise d'OpenClaw : les paraphrases non tracées et les copies externes échappent à la
recherche par lignée. C'est pourquoi la règle 2.3-1 interdit de recopier des renseignements personnels
dans la mémoire curée.

## 7. Budgets tokens du RAG

| Poste | Budget | Mécanisme |
|---|---|---|
| Sortie de `opsys_memoire_rechercher` | ≤ 4 000 caractères de texte (≈ 1 000 à 1 300 tokens), k ≤ 10 (défaut 5), extrait ≤ 800 caractères, métadonnées compactes | Constantes de `outils.py`. La troncature `Capacites` (6 000 caractères) sert de filet. |
| Paquet de contexte de l'affaire (M10, `m10_paquet_contexte_affaire`) | 4 000 caractères de faits, 1 000 par couche (quatre couches), au plus 5 faits par couche ; le plus ancien est omis d'abord et compté (`nb_omis`) | `paquets.py` (`BUDGET_CARACTERES_DEFAUT`, `budget_par_couche`) ; le core valide et ne tronque jamais. Détail et chiffres : ADR-0010, « T4.18-b » |
| Voie 1 OpenClaw | 0 appel modèle ; `MEMORY.md` dans le budget bootstrap | Préfixe stable, donc cache de prompt |
| PREFLIGHT M10 | 1 recherche par tâche (pas par tour), résultats réutilisés | Hook `before_prompt_build` |
| Indexation phase 1 | 0 token LLM | Préfixe déterministe |
| Contextual Retrieval (phase 2) | ≤ 100 tokens générés par fragment, document en cache | Imputé au département ingérant |
| Embeddings, rerank | 0 token LLM si local ; si cloud, coût par token d'entrée compté | Service local par défaut |
| Dreaming, Active Memory | Complétions de fond (au plus 3 simultanées côté OpenClaw) | Palier `rapide`/`local`, compté au département |

Les budgets journaliers et mensuels par département (`department.yaml`) s'appliquent au niveau de
`Capacites` : budget épuisé, seul le T0 reste permis.

## 8. Rôle de M10 : PREFLIGHT et POSTFLIGHT

M10 ne stocke pas une troisième mémoire : il orchestre les deux couches autour de chaque action.

- **PREFLIGHT**, hooks OpenClaw `before_prompt_build` (contexte) et `before_tool_call` (garde). Avant
  une tâche ou une action T1 et plus :
  1. rappel ciblé dans la couche B (portées de lecture, sujet de la tâche), budgeté ;
  2. vérification des prérequis par les prédicats M10 : une donnée manque, alors verdict « quoi
     demander », jamais une valeur inventée ;
  3. injection du contexte encadré comme donnée non fiable.
- **POSTFLIGHT**, hooks `after_tool_call` et `agent_end` :
  1. trace de la décision dans le registre append-only de M10 (`m10_memoire.registre`/`decisions`) ;
  2. fait durable dans la couche B par `opsys_memoire_ajouter`, avec
     `source = outil + id d'approbation` ;
  3. métriques (rappel, latence, tokens) vers M8.

La purge quotidienne de `purger_expires` ne dépend pas de ces hooks : le conteneur `opsys` la planifie déjà (phase 1b).

Le branchement de ces hooks dans le plugin OPSYS pour OpenClaw est en phase 2. Les prédicats et le
registre de M10 existent déjà (v1).

## 9. Évaluation

- **Jeu d'or FR maison.**
  - Graine versionnée : `tests/fixtures/memoire/jeu_or_fr.json`, fictif, marqué `fictif: true`. On y
    trouve des questions de rénovation résidentielle au Québec, avec fautes de frappe, sans accents et
    en variantes morphologiques, et 9 questions dont plusieurs rédigées comme des textos. Le test exige
    hybride > plein texte seul et rappel@3 hybride = 1. Avec le double déterministe des tests, on
    obtient 9/9 contre 5/9.
  - Ce test valide la **mécanique** de fusion (RRF, filtres, modes). Il ne mesure pas bge-m3 : le double
    est un sac haché de mots et de trigrammes.
  - Cible phase 2 : au moins 200 questions réelles anonymisées, réparties par département et par portée,
    chacune annotée des fragments attendus.
- **Métriques de recherche** (sans LLM) : rappel@k, MRR@10, latence p50/p95, part des résultats en
  mode `plein_texte`.
- **RAGAS** (Apache-2.0) : *faithfulness*, *context precision*, *context recall*, en lot hebdomadaire
  sur un échantillon.
- **TruLens** (MIT) : triade RAG et traces pour déboguer un cas.
- **Règle** : aucun chiffre de benchmark fournisseur n'est retenu (R4 §7). Seul notre banc fait foi.
  Tout changement de modèle, de découpage ou de fusion se juge sur ce banc avant fusion.

## 10. Dimensionnement

**VPS sans GPU**, profil par défaut (4 à 8 vCPU, 8 à 16 Go de RAM, cohérent avec R4) :
- **Stockage.** Un `vector(1024)` occupe 4 × 1 024 + 8 = 4 104 octets (format pgvector ;
  `pg_column_size` mesure 4 100). Mesure au banc sur 50 k fragments courts (≈ 300 caractères) :
  - 727 Mo au total (table, TOAST et index), dont 391 Mo d'index HNSW et 11 Mo de GIN plein texte ;
  - pour 100 k fragments, compter environ 1,5 Go, plus le texte réel (≈ 0,2 Go pour 2 000 caractères
    par fragment) ;
  - `halfvec` divise par deux les vecteurs et l'index.
- **Modèles.** bge-m3 et bge-reranker-v2-m3 ont chacun environ 568 M de paramètres : environ 2,3 Go en
  fp32, environ 0,6 Go quantifiés int8 (ONNX).
- **RAM.** Avec 8 Go : PostgreSQL (`shared_buffers` 2 Go), bge-m3 int8, OpenClaw, et pas de rerank. Avec
  16 Go : ajouter le rerank et Docling OCR. La mémoire de pointe de l'OCR reste à mesurer.
- **Latence mesurée** sur le banc de développement (bac à sable, pas le VPS cible), avec 50 k
  fragments, un filtre sur 2 portées, k = 10, connexion comprise et hors embedding de la requête :
  - hybride : p50 46 ms, p95 54 ms (index HNSW utilisé, parcours itératif) ;
  - plein texte seul : p50 29 ms, p95 38 ms.

  La jointure vers `documents` n'est faite que pour le filtre `source` : elle doublait le coût de la
  voie vectorielle.
- **Débit.** L'embedding CPU de la requête domine la latence. Le débit d'ingestion (fragments/s) est à
  mesurer sur le VPS cible.

**Option GPU** : bascule par service, sans changer l'API. Les URL d'embeddings et de rerank pointent vers
un service GPU. On peut alors envisager un embedder plus gros, Docling en mode VLM, et un rerank du
top-100.

## 11. Plan de mise en œuvre et critères de sortie

| Phase | Contenu | Critères de sortie |
|---|---|---|
| **1 (fait)** | Schéma, `MemoireEntreprise` (hybride RRF, filtres, oubli, purge, rattrapage), client d'embeddings, 3 outils MCP, CLI d'exploitation, tests réels PostgreSQL + pgvector | Tests verts contre `pgvector/pgvector:pg17` : hybride > plein texte sur le jeu d'or FR, cloisonnement, effacement, expiration, mode dégradé. Ruff vert. |
| **1b (fait)** | Outils branchés dans `Capacites` : politique T0–T3 appliquée aussi aux outils `opsys_*`. Département appelant fixé par la plateforme : un point d'accès MCP par département (`/mcp/<id>`) et `appeler_en_tant_que` à l'exécution d'une approbation (CLI et console). Embeddings locaux : profil `ollama` (bge-m3). `migrer` au démarrage, `purger` et `completer` chaque jour (`deploy/entrypoint.sh`) | `tests/test_departement_appelant.py` vert. Recette en conteneur contre `pgvector/pgvector:pg17` : écriture T1 mise en file (mode ombre), approuvée puis exécutée au nom de M3, relue par M3, refusée à M7 hors de ses portées et refusée sans département ; schéma et purge journalisés au démarrage. |
| **2** | Ingestion Docling, préfixes de contexte, rerank bge-reranker-v2-m3, plugin OpenClaw PREFLIGHT/POSTFLIGHT, jeu d'or réel ≥ 200 questions, RAGAS/TruLens, RLS | rappel@5 ≥ 0,92, faithfulness ≥ 0,90, p95 ≤ 1,5 s, EFVP signée |
| **3** | Graphiti + Neo4j (faits temporels), Contextual Retrieval sur corpus choisis, pgvectorscale si > 1 M fragments, option GPU | Gain mesuré sur le banc (sinon non retenu) |

## 12. Licences

| Composant | Licence | Statut |
|---|---|---|
| PostgreSQL, pgvector, pgvectorscale, `unaccent` (contrib) | PostgreSQL License | Retenus |
| OpenClaw | MIT | Core |
| bge-m3 | MIT | Retenu |
| bge-reranker-v2-m3 | Apache-2.0 | Retenu (phase 2) |
| Docling | MIT | Retenu (phase 2) |
| Graphiti, Mem0 OSS, RAGAS | Apache-2.0 | Phase 2 ou option |
| TruLens | MIT | Phase 2 |
| Neo4j Community | GPLv3 | Service séparé non modifié uniquement |
| psycopg 3 | LGPL-3.0 | Dépendance dynamique (extra `postgres`), admise par `AGENTS.md` |

**Alertes** (R4, à ne pas lever sans décision humaine) :
- **jina-embeddings-v4** : Qwen Research License, héritée de Qwen2.5-VL-3B malgré un tag HF
  `cc-by-nc-4.0`. Usage commercial interdit, même en auto-hébergé. Proscrit. jina-embeddings-v3 et
  jina-reranker-v2 : CC-BY-NC-4.0, non commercial.
- **FalkorDB** : SSPL v1, source-available. La clause de service peut s'appliquer si OPSYS est revendu
  en SaaS multi-clients. Refusé sauf avis juridique. Neo4j Community est préféré.
- **ParadeDB (`pg_search`)** : AGPL-3.0 ou licence commerciale. Différé : le plein texte natif PostgreSQL
  couvre le besoin. Un service séparé non modifié reste possible après décision.
