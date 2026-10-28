# INGREDIENTS — Catalogue des briques open source retenues pour OPSYS-AI

## Bêta-tests par agents — 22 octobre 2026

Réutilisation initiale de **Playwright 1.63.0**, déjà installé/verrouillé dans le Core
(Apache-2.0), pour les parcours de la console serveur. Les
[agents officiels planner/generator](https://playwright.dev/docs/test-agents) ciblent Claude Code
et Codex. Les corrections automatiques de tests ne doivent pas masquer un défaut métier.
Licences, autres candidates (Schemathesis, Inspect AI, browser-use), recherche GitLab,
limites et décision d'intégration sont décrites dans le
[programme de bêta-tests](../programme/BETA-TESTS-SERVEUR-2026-10-22.md).
Ces autres candidates ne sont ni installées ni déclarées qualifiées par leur seule présence
dans cette recherche. Aucun paquet ou lockfile produit n'est modifié pour cette sélection.

## Correctifs ciblés de sécurité du 21 octobre 2026

Les dépendances existantes sont corrigées sans renouvellement global. Le contrôle de production
`pnpm audit --prod --json` passe de huit avis (un élevé, trois modérés, quatre faibles) à zéro
sur le verrou corrigé. Cela ne certifie ni absence de toute vulnérabilité ni exploitation antérieure.

- Core : markdown-it 15.0.2 → 15.0.3 (MIT), DOMPurify 3.4.15 → 3.4.16 (Apache-2.0/MPL-2.0),
  Hono 4.13.7 → 4.13.11 (MIT), Joi 18.2.6 → 18.2.9 (BSD-3-Clause), KaTeX 0.16.47 → 0.18.2 (MIT),
  MCP client/core 2.2.0 → 2.3.0 (Apache-2.0, core aligné sur la version exigée par le client).
  argparse 3.0.2 → 3.0.3 (PSF-2.0, licence conservée) est la seule autre version modifiée,
  exigée par markdown-it ; ses archives SHA-512 et le diff ont été vérifiés : correction d'une
  expression régulière, sans nouvelle dépendance ni script d'installation.
- La politique globale de maturation reste à 10 080 minutes. Seules les versions exactes examinées
  markdown-it 15.0.3 et argparse 3.0.3 sont explicitement admises pendant leurs délais respectifs,
  jusqu'aux 23 octobre 01:25:15 UTC et 22 octobre 21:58:50 UTC. Les autres gardes sont conservées.
- Python : Pillow 12.3.0 → 13.0.0 (MIT-CMU), certifi 2026.7.22 → 2026.10.19 (MPL-2.0),
  setuptools 81.0.0 → 83.0.0 (MIT). Les trois roues exactes sont acquises depuis les URL du verrou
  et vérifiées SHA-256. Les autres entrées du graphe sont conservées. Les onze avis distincts
  signalés dans ces trois anciennes versions ne sont plus signalés par OSV pour les versions corrigées.
  La racine emSign compromise présente dans l'ancien bundle certifi est absente du nouveau.

Sources : [markdown-it](https://github.com/advisories/GHSA-gfr2-rv44-r23c),
[Pillow](https://github.com/advisories/GHSA-8g5g-8vmr-9782),
[certifi](https://github.com/advisories/GHSA-6q48-6c7w-9gw2),
[setuptools](https://github.com/advisories/GHSA-h35f-9h28-mq5c).
Les versions, intégrités, licences et plages affectées ont été relues dans les métadonnées amont.
Les tests consommateurs Markdown/UI, les probes des bibliothèques réelles, le typage UI natif,
les tests photo/PDF ciblés et la construction Python sont vérifiés localement. La CI du commit
corrigé est une qualification distincte ; le rendu OCR Linux x86_64 n'est pas attesté sur l'hôte ARM.
La divergence NumPy préexistante de l'export ingestion-PDF est conservée, sans mise à jour adjacente.


## Recherche M3 du 5 octobre — métrologie, candidates non adoptées

La [revue nuages/échelle/incertitude GitHub/GitLab](REPRISE-2026-10-05/M3-METROLOGIE-NUAGES-GITHUB-GITLAB.md)
épingle Open3D (MIT), PDAL (BSD trois clauses), Eigen GitLab (MPL-2.0 principale) et Metric3D
(code BSD deux clauses ; poids non qualifiés). Premier banc proposé : Open3D borné après COLMAP,
avec contrôle terrain indépendant et échelle vérifiée. PDAL est reporté au besoin GIS/LiDAR ;
Eigen reste une transitive à qualifier. Les niveaux photo/Monte Carlo actuels ne prouvent aucune
précision géométrique. Les licences/options transitives, performances et intégration restent à qualifier.
Aucune nouvelle dépendance, mesure réelle ou capacité photo livrée annoncée.

## Recherche métrique M3 du 4 octobre — candidats non adoptés

La [comparaison multi-vues GitHub/GitLab](REPRISE-2026-10-04/M3-PHOTOGRAMMETRIE-GITHUB-GITLAB.md)
vérifie COLMAP 4.2.1 (`bd1fcf…`, BSD trois clauses pour le projet), OpenSfM v1.1
(`8b6b77…`, BSD deux clauses) et GigaMesh (`23d8cf…`, GPL-3+). Premier banc proposé :
COLMAP séparé, avec échelle/contrôles terrain, licences de dépendances et budgets
CPU/RAM à qualifier avant adoption. OpenSfM reste une piste GIS; GigaMesh n'est
pas retenu. Les captures et la correction d'un pin de développement initial sont
conservées. Aucun statut intégré, précision réelle ou dépendance supplémentaire
n'est attribué par ce travail de recherche.

## Recherche audiovisuelle 3D du 4 octobre — approfondissement non adopté

La [revue GitHub/GitLab des architectures avatar/audio](REPRISE-2026-10-04/AVATAR-AUDIO-3D-GITHUB-GITLAB.md)
approfondit seulement les composants déjà listés ici/R21 : clips TTS avec cues locaux d’abord;
LiveKit Agents et SDK React Native si un besoin micro/WebRTC est prouvé; NVIDIA Audio2Face/NIM
comme service GPU séparé et facultatif. Les licences du framework, des SDK, du modèle NVIDIA et
des actifs VRM restent distinctes; aucun coût, latence, qualité fr-CA ou statut intégré n’est
revendiqué. La recherche GitLab a identifié des miroirs NVIDIA, pas un upstream séparé; le seul
projet VRM distinct inspecté est webcam/MediaPipe AGPL et n’est pas retenu pour la synchronisation
TTS. Les sources primaires épinglées et captures sont reliées au rapport.

## Actif audiovisuel facultatif — RobotExpressive (2 octobre 2026)

Le catalogue local facultatif `robotexpressive-quaternius-cc0-v1` utilise le modèle
`RobotExpressive.glb` de Three.js, fichier épinglé au commit
[`b924f0cad4058dc4dde71445c796980c3cd5b5ed`](https://github.com/mrdoob/three.js/tree/b924f0cad4058dc4dde71445c796980c3cd5b5ed/examples/models/gltf/RobotExpressive).
Le README du modèle annonce Quaternius CC0 1.0 et les modifications de Don McCurdy ; le texte
juridique CC0 a été relu. L'actif inclus fait 463 988 octets, SHA-256
`047f5e5fb3bb6d378bd1df16ca6137f2a596c99b3a1b5690b4020c05aaf6f319`. L'actif est servi par une
route Control UI authentifiée et non par `ui/public`. Le GLB lui-même reste statique : pas d'audio
ni de synchronisation labiale, et l'attribution d'un modèle à un agent reste explicite. Le Core
embarque un README de provenance et le texte juridique CC0 à côté du modèle sous
`core/assets/avatar-models/`; le reçu borné et l'inspection structurelle sont conservés dans le
scratch R47. Aucune licence ou empreinte de modèle n'est extrapolée aux autres fichiers du dépôt
Three.js.

## Renderer Web Three.js — adoption préparatoire (2 octobre 2026)

Le code source du renderer chat utilise maintenant `three@0.186.1` comme dépendance UI directe
(runtime, MIT, copyright `© 2010-2026 three.js authors`) et son `GLTFLoader`; le chargement reste
paresseux et limité à l'avatar explicitement demandé. Le texte MIT exact (1 081 octets, SHA-256
`8b378ebe60e2fe500158cb0ac71cb5e8b7d92953c2abcc63a0eb90499653b5bc`) est conservé à
`core/ui/public/licenses/three-MIT.txt` pour être livré avec le bundle UI. `@types/three@0.186.0`
(MIT) sert seulement à TypeScript. ROOT a généré et revu le lock pnpm 12.4.0, SHA-256
`faf75ce21976f50b35a194d378a9b27af86b68bffbb8bd90fd7be212d210f395`, et confirmé une installation
frozen le 2026-10-02; la vérification structurelle du lock est en cours. Le build, la copie du texte
MIT dans `dist/control-ui`, le contenu de l'archive distribuée et le rendu en navigateur restent à
qualifier; aucune taille finale de chunk n'est revendiquée.

Les cinq nouvelles transitives du paquet de types ne sont ni importées ni prévues dans le runtime
navigateur. Leurs licences ont été vérifiées dans les fichiers des archives exactes conservées dans
la capture R47. Les pins observés dans le lock sont :

| Paquet | Version résolue | Licence | Usage / preuve de licence |
|---|---:|---|---|
| `three` | 0.186.1 | MIT | Runtime UI; license bytes SHA-256 `8b378ebe60e2fe500158cb0ac71cb5e8b7d92953c2abcc63a0eb90499653b5bc` |
| `@types/three` | 0.186.0 | MIT | Types/dev seulement; `c2cfccb812fe482101a8f04597dfc5a9991a6b2748266c47ac91b6a5aae15383` |
| `@dimforge/rapier3d-compat` | 0.12.0 | Apache-2.0 | Transitive de types seulement; `4c05555705e3efde601fb1252ae48f1d63992af8a8fb8947745b7fa834e8f519` |
| `@tweenjs/tween.js` | 23.1.3 | MIT | Transitive de types seulement; `c95fecd88f2709bfc34e4d1f1ccc36d17048990e6ba26c283cfecdef0432936b` |
| `@types/stats.js` | 0.17.4 | MIT | Transitive de types seulement; `c2cfccb812fe482101a8f04597dfc5a9991a6b2748266c47ac91b6a5aae15383` |
| `@types/webxr` | 0.5.24 | MIT | Transitive de types seulement; `c2cfccb812fe482101a8f04597dfc5a9991a6b2748266c47ac91b6a5aae15383` |
| `meshoptimizer` | 1.1.1 | MIT | Transitive de types seulement; `f03037ca7bad1e3eb7f4a63fa6084a8baabd5ba30d3c239a9a7f35705d873e26` |

`fflate@0.8.3` est la sixième dépendance de `@types/three` et existait déjà dans le lock avant
cette tranche. Les cinq nouveaux paquets ci-dessus sont les seules transitives inédites capturées;
Rapier/WASM, XR, tween, stats et meshoptimizer ne sont pas des fonctionnalités du renderer livrées.
Leur capture inclut métadonnées npm, SRI et fichier de licence exact; les dépendances de types ne
justifient pas de copier leurs notices dans le bundle runtime lorsqu'elles ne sont pas incorporées.

> Condensé des 10 rapports de recherche [`docs/research/R1`](R1-core-openclaw.md)…
> [`R10`](R10-m9-capabilities.md) (brief commun : [`00-BRIEF.md`](00-BRIEF.md)). Chaque licence est
> reprise **telle que le rapport source l'a vérifiée** (fichier `LICENSE` brut, fiche modèle Hugging
> Face, ou doc officielle citée dans le rapport) — ce document ne réévalue aucune licence lui-même.
> Contrainte produit (rappel `00-BRIEF.md`) : MIT/Apache-2.0/BSD/MPL = OK en dépendance ; LGPL = OK en
> liaison dynamique ; GPL/AGPL = service séparé non modifié uniquement ; source-available
> (BSL/Elastic/SSPL/RAIL/licences communautaires non-OSI) = signalé comme risque.

## Mise à jour de référence — 30 septembre 2026

Le [complément OCR du 5 octobre](REPRISE-2026-10-05/OCR-CANDIDATS-COMPLEMENT.md)
précise les extras Docling 2.133.0 au commit déjà étudié, sans installation ni benchmark.
Kreuzberg est non adopté : captures de licences/identités divergentes, dont Elastic 2.0 sur main;
Reimburse OCR (GitLab) reste non qualifié faute de licence littérale complète et de version.
Ces pistes ne sont pas des ingrédients intégrés et ne remplacent pas le parcours AP validé humainement.

### Qualification de reprise : protection des imports financiers

`cryptography` **50.0.2** est retenue pour AES-256-GCM dans le
[pilote CSV durable](../programme/LOT-FUSION-CSV-COMPTABLE.md), qualifié localement dans
[R22](R22-2026-10-02/README.md). La qualification SQLite ne couvre pas PostgreSQL.
La version est déjà verrouillée par `uv.lock` et le verrou runtime; son extra direct `ingestion`
rend ce besoin explicite. La roue Linux utilisée pour les tests fait 4,8 Mo, SHA-256
`9dab55f57c74c3cad24c323bacbbd04be4705ba6eb0d92e920b1fc4837ed5079`.
Les trois notices réelles de cette roue ont été relues : licence au choix Apache-2.0 ou
BSD-3-Clause, avis à conserver. GitHub `pyca/cryptography` est le primaire; GitLab Debian Salsa
est un emballage identifié par recherche, dont l'accès direct a échoué, pas une source adoptée.
Les dépendances installées de test `cffi` 2.1.1 (MIT No Attribution) et `pycparser` 3.0
(BSD-3-Clause) ont leurs notices conservées. Le rôle des bibliothèques natives embarquées reste
celui de la distribution upstream; aucune réimplémentation du chiffrement n'est ajoutée.

Le venv de qualification contient désormais 50.0.2, installé hors réseau depuis la roue vérifiée.
L'inventaire initial d'un Python global en 50.0.0 n'est pas celui des tests; les reçus distinguent
ces interpréteurs. Ce choix protège sources/résultats avec clé externe référencée et AAD lié au
lot; il ne constitue ni un coffre de secrets, ni un service OCR, ni une mémoire entraînée.
Le décompte historique ci-dessous reste celui des recherches R1–R15 et n'inclut pas cette reprise.

La [recherche de reprise R21](R21-2026-10-02/README.md) ajoute une **liste de candidats non
adoptés** pour ingestion documentaire (Docling), géospatial (Rasterio/py3dtiles/ODM), audio/3D
(Pipecat/LiveKit/TalkingHead/Audio2Face) et évaluation de mémoire/apprentissage. Elle distingue
licences du code, poids et actifs, sources primaires et résultats publiés. Aucun statut « Intégré »
du catalogue ci-dessous n'est accordé par cette recherche.

La [recherche R16](R16-2026-09-30/README.md) complète les rapports antérieurs avec sources/commits
et licences relus. Ce catalogue conserve leurs détails datés : une mention « Phase 2 » est une
candidate, pas une décision d'installer une nouvelle stack. L'état réel se vérifie dans le code
et le parcours ; les scénarios mock/export restent distincts des intégrations externes.

Le core est un **fork modifié**, pas une image officielle configurée exclusivement de l'extérieur;
provenance dans `core/PROVENANCE.md`. Hermes est une source d'ingrédients. Le mobile est Expo. Le
générateur configure les fournisseurs natifs par défaut; LiteLLM reste une compatibilité explicite.
Les paliers peuvent nommer les variables d'environnement des clés, jamais leurs valeurs en clair
dans le JSON. Le readiness refuse les clés requises manquantes; les tests sans credentials ne
prouvent pas les appels à un fournisseur externe. Voir R16 et le plan courant. La mémoire comprend
deux domaines isolés (affaires/développement), sans Forge requis.

Priorités : frontières de l'audit → installation cohérente → admission budget fournisseur et
profils spécialisés → M10 complet → parcours M1/M7/M5 profonds. Qualification nouvelle : code,
licence primaire et dépendances/poids, commit stable, maintenance, interface, coûts et preuve métier.
Les pourcentages et performances publiés par un projet tiers ne sont pas des résultats OPSYS.

## Légende « Phase »

| Phase | Sens |
|---|---|
| **Intégré** | Vérifié dans le code ou la configuration du dépôt aujourd'hui. |
| **Phase 2** | Retenue par le rapport de recherche ; pas encore câblée dans le dépôt (aucune dépendance, aucun service, aucun fichier de config correspondant trouvé au 2026-09-28). |
| **Référence** | Source d'inspiration ou patron de conception cité par le rapport ; explicitement **non vendorisée**. |

---

## Core

> **État courant : ADR-0008 et ADR-0012.** Base `openclaw/openclaw` v2026.9.6 forkée,
> renommée et greffée dans `core/`. Pas de synchronisation automatique. `core/UPSTREAM.md` a été
> retiré ; `PROVENANCE.md` et `NOTICE` font foi. Les tests historiques ci-dessous ne certifient
> pas l'installation, toutes les permissions, ni l'équivalence d'un runtime Hermes.

| Brique | Licence vérifiée | Rôle dans OPSYS | Intégration | Phase | Rapport source |
|---|---|---|---|---|---|
| **OpenClaw** (openclaw/openclaw) | MIT, avis à conserver | Runtime agents, canaux, mémoire native, Control UI ; app mobile OPSYS Expo distincte | Fork dur modifié dans `core/`, provenance `core/PROVENANCE.md` et greffes OPSYS ; code source maintenu par OPSYS, correctifs de sécurité ciblés | **Intégré** (fork ; limites de l’audit ouvertes) | R1 · R11 · ADR-0008 · R16 |
| **jsonschema** (python-jsonschema) | MIT (fichier `COPYING` lu dans le paquet installé) | Validation complète (Draft 2020-12) des charges du bus d'événements contre le catalogue `src/opsys/evenements/catalogue/*.json`, objets et tableaux imbriqués compris ; vérification des schémas au chargement | Dépendance déclarée dans `pyproject.toml` (`>=4.20,<5`), déjà tirée par `mcp` ; ses dépendances (`attrs`, `referencing`, `jsonschema-specifications`, `rpds-py`) sont MIT | **Intégré** | ADR-0009 §3 |
| **Hermes Agent** (NousResearch) | MIT | Ingrédients mémoire/context engine/compaction/skills/sous-agents ; adaptateur Python historique présent | Reprises étroites après preuve, pas un deuxième core obligatoire ; comparaison source R16 complète R2/ADR-0008 | **Référence** pour nouvelles greffes ; adaptateur historique à qualifier | R2 · R16/Hermes · ADR-0012 |

## Modèles / économie de tokens

| Brique | Licence vérifiée | Rôle dans OPSYS | Intégration | Phase | Rapport source |
|---|---|---|---|---|---|
| **LiteLLM Proxy** | MIT (cœur ; dossier `enterprise/` sous licence distincte, à éviter) | Gateway de compatibilité facultative, activée seulement par un choix explicite; paliers aliasés, clés virtuelles et contrôles de budget dans ce chemin | `src/opsys/passerelle.py` (`config_litellm`, `ClientLiteLLM.enregistrer_departement`) ; CLI `opsys-metier passerelle config` et `cles` ; **tests avec serveur factice** (`tests/test_openclaw_passerelle.py`), sans preuve d'appels à un fournisseur réel | **Intégré en compatibilité** | R3 (historique) · ADR-0008 · R16 |
| Cache-prompt et compaction **natifs d'OpenClaw** (`cacheRetention`, `contextPruning.mode:"cache-ttl"`, `compaction.*`, heartbeat keep-warm) | MIT (mécanisme du core OpenClaw) | Remplace, comme runtime par défaut, le rôle que jouaient les modules `agent/prompt_caching.py`/`context_compressor.py` de Hermes : cache multi-fournisseurs testé en direct (`cacheRetention`), compaction/troncature dynamique des résultats d'outils, suivi des coûts natif | Défauts OpenClaw actifs ; `src/opsys/openclaw.py::generer()` ne paramètre **pas encore** `cacheRetention`/`compaction`/`contextPruning` par département (seuls `name`/`workspace`/`model` sont écrits dans `agents.json`) — détail dans [`ECONOMIE-TOKENS.md`](../architecture/ECONOMIE-TOKENS.md) §2-3 | Phase 2 (mécanisme natif disponible, non encore paramétré par OPSYS) | R1 · ADR-0007 |
| Patron `localService` d'**OpenClaw** (démarrage à la demande / arrêt sur inactivité des modèles locaux) | MIT | Réduit l'empreinte VPS d'un modèle local (Ollama/llama.cpp) tenu résident 24 h/24 | Réimplémentation Python prévue (`local_model_manager`) ; `passerelle.py::modele_litellm()` sait déjà traduire un palier `custom`/`ollama` en paramètres LiteLLM, mais sans gestion de cycle de vie | Phase 2 | R3 |
| Règles de conception « cache-boundary » d'**OpenClaw** (préfixe stable / suffixe volatil, jamais changer de modèle en cours de session) | MIT | Discipline de rédaction des espaces de travail par agent — désormais **le comportement natif du runtime par défaut**, pas seulement une discipline appliquée manuellement | `src/opsys/openclaw.py::generer()` écrit `SOUL.md`+`AGENTS.md` (contenu stable) par agent, dans l'espace de travail que le système-prompt-cache-boundary natif d'OpenClaw sépare automatiquement du contexte volatil (runtime, timestamps) | **Intégré** | R1 · R3 · ADR-0007 |
| **Langfuse** (cœur) | MIT (dossiers `ee/`, `web/src/ee/`, `worker/src/ee/` sous licence Enterprise séparée) | Traçabilité coût/latence par appel LLM, complémentaire à la page native OpenClaw Control UI → Usage et à `/usage`/`/status` | Service sidecar (web + worker + ClickHouse + Postgres), callback LiteLLM + SDK Python | Phase 2 | R3 · R5 |
| **LLMLingua / LongLLMLingua** | MIT | Compression de prompt par élagage de tokens à faible information (extraits RAG, longues sorties) | Dépendance pip | Phase 2 | R3 |
| **Ollama** + **llama.cpp** (`llama-server`) | MIT (les deux) | Fournisseurs de modèles locaux; le propriétaire configure le palier et fait tourner le service séparément | Le générateur natif projette les fournisseurs et références de secrets déclarés dans `paliers.yaml`; aucun modèle ni service local n'est installé automatiquement | Intégré côté configuration native; exécution locale à configurer | R3 · R16 |
| **Bifrost** (maximhq) | Apache-2.0 | Option de repli passerelle réseau si l'empreinte Postgres/Redis de LiteLLM est trop lourde (binaire Go unique, cache sémantique natif) | Service sidecar (alternative à LiteLLM) | Référence (option de repli, non retenue par défaut) | R3 |
| **RouteLLM** (lm-sys) — concept uniquement, pas la dépendance | Apache-2.0 (dépôt non maintenu depuis août 2024) | Patron « classifieur léger décide si un modèle faible suffit, sinon escalade » | Réimplémentation maison prévue par règles/heuristiques par module ; aujourd'hui l'assignation palier↔usage est **statique** par manifeste (`department.yaml: modeles`), pas un classifieur dynamique | Phase 2 | R3 |

## Mémoire / RAG

| Brique | Licence vérifiée | Rôle dans OPSYS | Intégration | Phase | Rapport source |
|---|---|---|---|---|---|
| **pgvector** + **pgvectorscale** | PostgreSQL License (les deux) | Indexation vectorielle dans le Postgres métier déjà prévu (StreamingDiskANN pour pgvectorscale) | Extension SQL (`CREATE EXTENSION vector`) | Phase 2 | R4 · R5 |
| FTS natif Postgres (`tsvector`/GIN) | Licence PostgreSQL (composant du moteur, pas une brique tierce) | Recherche lexicale native ; `ts_rank`/`ts_rank_cd` ne sont pas BM25, qui exige une implémentation ou extension distincte | Natif Postgres | Phase 2 | R4 · correction R16 |
| **Mem0** (mode OSS) | Apache-2.0 | Mémoire de faits par agent/tenant, recherche hybride sémantique+BM25+entités | Dépendance pip (`mem0ai`), vector store = pgvector du Postgres OPSYS | Phase 2 | R4 |
| **Graphiti** (Zep) + **Neo4j Community** (backend graphe) | Graphiti : Apache-2.0 · Neo4j Community : GPLv3 (sidecar non modifié) | Graphe temporel (validité « quand c'était vrai » vs « quand invalidé ») pour clients/chantiers/décisions | Dépendance pip (`graphiti-core`) + service Neo4j sidecar consommé par Bolt | Candidate, backend à qualifier (pas driver PostgreSQL universel) | R4 · R16 |
| **Docling** | MIT | Ingestion/OCR/parsing de tableaux, exécution locale possible (air-gapped, pertinent Loi 25) | Dépendance pip ou service `docling-serve` | Phase 2 | R4 |
| **BAAI/bge-m3** + **BAAI/bge-reranker-v2-m3** | bge-m3 : MIT (fiche HF) · reranker : Apache-2.0 (fiche HF) | Embeddings/reranking FR multilingue par défaut, exécutables CPU/ONNX | Poids téléchargés, servis en local | Phase 2 | R4 |
| Service local R41 BGE-M3 ONNX quantifié | Modèle : fiche Xenova et carte BAAI déclarent MIT, mais aucun fichier `LICENSE` distinct trouvé pour les poids. Runtime : ONNX Runtime MIT, Tokenizers Apache-2.0, NumPy BSD-3-Clause | Endpoint privé OpenAI-compatible, CPU, un texte et 512 tokens max | Extra Python optionnel épinglé; assets externes fournis et vérifiés par taille/SHA, aucun téléchargement au démarrage | Implémentation opt-in; qualification VPS/RSS et juridique des poids encore ouvertes | R41 · R35 |
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
| **SQLAlchemy 2.1** (Core) + **Alembic 1.20** | MIT (les deux, fichiers LICENSE vérifiés le 2026-09-28) | Base de l'instance : même code pour SQLite (défaut) et PostgreSQL (option), migrations versionnées | Dépendances directes (`pyproject.toml`), paquet `opsys.stockage` | Adopté (ADR-0009) | R13 |
| **PostgreSQL 17** + **pgvector** | PostgreSQL License (les deux) | Base relationnelle métier + RAG, déjà la stack visée (psycopg) | Image officielle `pgvector/pgvector:pg17` | Phase 2 (dépendance `psycopg` déclarée en optionnelle dans `pyproject.toml`, mais aucun service déployé) | R5 |
| **uv** (Astral) | MIT ou Apache-2.0 (fichiers `LICENSE-MIT` et `LICENSE-APACHE` de la roue 0.8.17, vérifiés le 2026-09-29) | Installe le moteur Python 3.11+ dans un environnement dédié (Python géré au besoin) pour l'installateur une commande | Prérequis externe de `install/install.sh` et `install.ps1` : vérifié, jamais vendorisé, aucune dépendance Python ; installé par `pip` dans le job `installateur` | Intégré | PLAN T0.11 |
| **actionlint** (rhysd) | MIT (`LICENSE.txt` de l'archive 1.7.7, « the MIT License », vérifié le 2026-09-29) | Contrôle le workflow `installateur.yml` avant tout lancement : contextes disponibles par niveau (`runner` n'existe pas dans le `env` d'un job), expressions, noms d'entrées ; relit les `run` par shellcheck | Binaire téléchargé par le job `analyse` à version et empreinte SHA-256 épinglées, jamais vendorisé | Intégré | PLAN T0.11-d |
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

## Mobile

> Squelette Expo Router livré par PLAN T1.4-a (`mobile/`, aucun écran métier), étendu par
> T1.4-c3 (appairage), T1.4-d (punch) et **T1.4-e (chantier du jour, transitions, checklist,
> photos, signature)** — voir [`docs/architecture/MOBILE.md`](../architecture/MOBILE.md) et
> [`R12`](R12-app-mobile.md) §3 pour le détail. Licences vérifiées en lisant le fichier `LICENSE`
> de chaque paquet dans `mobile/node_modules/<paquet>/`, sauf mention contraire ci-dessous.

| Brique | Licence vérifiée | Rôle dans OPSYS | Intégration | Phase | Rapport source |
|---|---|---|---|---|---|
| **expo** 57.0.25 | MIT | SDK/runtime de l'app mobile | Dépendance directe `mobile/package.json`, version épinglée = celle de R12 §3 | **Intégré** | R12 |
| **expo-router** 57.0.23 | MIT (`package.json` ; le tarball publié n'inclut **pas** de fichier `LICENSE` — vérifiée en lisant celui, identique, de `expo` : même éditeur 650 Industries, même monorepo `expo/expo`) | Navigation par fichiers, groupes de routes gardés par rôle (R12 §5) | Dépendance directe, version épinglée = celle de R12 §3 | **Intégré** | R12 |
| **expo-sqlite** 57.0.3 | MIT | Stockage local de la file sortante (`src/outbox/depot.sqlite.ts`, DDL `outbox` de R12 §4) | Dépendance directe, version épinglée = celle de R12 §3 | **Intégré** | R12 |
| **@react-native-community/netinfo** 12.0.1 | MIT (fichier `LICENSE` lu dans le paquet installé) | Détection du retour du réseau : déclenche la vidange de la file sortante (`mobile/src/outbox/declencheurs.ts`, R12 §4) | Dépendance directe, version épinglée = celle de R12 §3 | **Intégré** (T1.4-d) | R12 |
| **expo-localization** 57.0.2 | MIT | Détection de la langue de l'appareil (`src/i18n`) | Dépendance directe, version épinglée = celle de R12 §3 | **Intégré** | R12 |
| **expo-crypto** 57.0.3 | MIT | `mutation_id` UUID généré sur l'appareil avant tout réseau (`src/outbox/id.ts`, `randomUUID()`) ; graine aléatoire de la clé d'appareil (`src/appairage/stockage.ts`, `getRandomBytes(32)`, T1.4-c3) | Dépendance directe — **écart** : R12 §3 cite la brique sans version pinnée (« à confirmer ») ; version choisie ici = dernière du train SDK 57 (`57.0.3`) | **Intégré** | R12 (version : mission T1.4-a) |
| **expo-secure-store** 57.0.4 | MIT | Stockage de la clé secrète d'appareil (Ed25519) et de la session appariée (jeton, rôle, `appareilId`) — `src/appairage/stockage.ts` — Keychain iOS / Keystore Android, jamais SQLite ni `AsyncStorage` (R12 §6, mission item 2 : jamais journalisée) | Dépendance directe, version épinglée = celle de R12 §3 | **Intégré** (T1.4-c3) | R12 |
| **@noble/curves** 2.4.0 | MIT | Ed25519 (EdDSA RFC 8032 pur, sans pré-hachage) pour la clé d'appareil et la signature du défi d'appairage (`src/appairage/identite.ts`) — algorithme EXACT confirmé en lisant `core/src/infra/ed25519-signature.ts:170-174,199-211` (Node `crypto.sign(null, ...)`/`crypto.verify(null, ...)` sur une clé Ed25519) ; vérifié octet pour octet contre Node `crypto` (`src/appairage/identite.test.ts` — clé, signature et `deviceId` calculés avec `@noble/curves`/`@noble/hashes` puis revérifiés avec `crypto.verify`/`crypto.createHash` de Node, jamais avec du code de `core/`) | Dépendance directe ; R12 §3 la citait comme « piste, à confirmer selon l'algorithme exact retenu par le fork (§1.3) » — confirmée par PLAN T1.4-c3 comme LE bon algorithme, version inchangée | **Intégré** (T1.4-c3) | R12 · PLAN T1.4-c3 |
| **@noble/hashes** 2.4.0 | MIT | SHA-256 pour dériver le `deviceId` de la clé publique (`src/appairage/identite.ts`, `deriverIdAppareil` — port de `core/src/infra/device-identity.ts:176-187`, `deriveDeviceIdFromPublicKey`) | Dépendance directe et explicite (dépendance de fait de `@noble/curves` pour Ed25519/SHA-512, mais utilisée ici directement pour SHA-256 : mieux vaut une dépendance déclarée qu'une transitive non vérifiée) | **Intégré** (T1.4-c3) | PLAN T1.4-c3 |
| **@types/node** 26.6.3 | MIT (Microsoft/DefinitelyTyped) | Types pour l'oracle indépendant `node:crypto`/`Buffer` utilisé UNIQUEMENT dans les tests d'appairage (`src/appairage/*.test.ts`, vecteurs croisés) — jamais dans le code d'app : `/// <reference types="node" />` posée fichier par fichier plutôt qu'ajoutée à `tsconfig.json` `types`, pour ne jamais rendre les globales Node (`Buffer`, `process`, ...) disponibles côté app RN/Hermes, où elles n'existent pas à l'exécution | Dépendance directe (dev) — déjà résolvable en transitif (`"@types/node": "*"` chez plusieurs paquets de test) ; épinglée en directe pour une résolution explicite | **Intégré** (T1.4-c3) | PLAN T1.4-c3 |
| **i18next** 26.4.2 + **react-i18next** 17.0.15 | MIT (les deux) | Moteur i18n + bindings React, fr-CA par défaut / en-CA en réserve | Dépendances directes, versions épinglées = celles de R12 §3 | **Intégré** | R12 |
| **react** 19.2.3 + **react-native** 0.86.3 | MIT (les deux, Meta) | Runtime requis par Expo SDK 57 | Dépendances directes — non listées par R12 §3 (choix de version délégué au SDK) ; versions = celles du gabarit officiel `expo-template-default@57.0.25` (React Native 0.86, conforme à R12 §3) | **Intégré** | R12 · gabarit SDK 57 |
| **react-native-screens** 4.26.2, **react-native-safe-area-context** 5.7.0, **react-native-gesture-handler** 2.32.0, **react-native-reanimated** 4.5.1 + **react-native-worklets** 0.10.1, **expo-linking** 57.0.11, **expo-constants** 57.0.19, **@expo/log-box** 57.0.4, **@expo/metro-runtime** 57.0.16 | MIT (tous, vérifié fichier par fichier) | Dépendances **requises** (peer non optionnels) d'`expo-router` pour la navigation par fichiers (écrans, pile, sécurité des zones, gestes) | Dépendances directes — non listées par R12 §3 (détail d'implémentation d'Expo Router, pas un choix produit) ; versions reprises du gabarit officiel `expo-template-default@57.0.25`, cohérentes avec `expo`/`expo-router` 57.0.25/57.0.23 | **Intégré** | Gabarit SDK 57 |
| **Jest** (fourni par Expo) 29.7.0 + **jest-expo** 57.0.5 | MIT (les deux) | Tests unitaires de la logique pure (`src/roles`, `src/outbox`, `src/protocole`, `src/i18n`) | Dépendances directes (dev) | **Intégré** | R12 |
| **babel-preset-expo** 57.0.13 | MIT | Préréglage Babel (Metro et Jest) | Dépendance transitive d'`expo` rendue **directe** (dev) : npm ne la hissait pas à la racine de `node_modules`, ce qui cassait la résolution Jest/Babel — épinglée à la version déjà résolue | **Intégré** | Détail d'implémentation |
| **@react-native/jest-preset** 0.86.3 | MIT (`package.json` ; le tarball publié n'inclut pas de fichier `LICENSE` — vérifiée en lisant celui, identique, de `react-native` : même éditeur Meta, même monorepo `facebook/react-native`) | Pair requis par `jest-expo` (config Jest React Native) | Dépendance directe (dev), version = celle de `react-native` 0.86.3 | **Intégré** | R12 |
| **TypeScript** 6.0.3 | Apache-2.0 | Mode strict (`strict: true`, R12 §5 et mission) | Dépendance directe (dev) — non pinnée par R12 §3 ; version reprise du gabarit officiel `expo-template-default@57.0.25` | **Intégré** | Gabarit SDK 57 |
| **@types/react** 19.2.18 + **@types/jest** 29.5.14 | MIT (les deux, Microsoft/DefinitelyTyped) | Typage | Dépendances directes (dev) | **Intégré** | — |
| **expo-camera** 57.0.5 | MIT (fichier `LICENSE` lu) | Capture photo avant/pendant/après (`CameraView`), bridage de résolution ≈1600 px de long côté + qualité JPEG 0,8 (`src/photos/`, R12 §4) — `CameraPictureOptions` n'offre pas de redimensionnement direct, voir MOBILE.md « Photos » pour la limite exacte lue dans les types | Dépendance directe, version épinglée = celle de R12 §3 | **Intégré** (T1.4-e) | R12 · PLAN T1.4-e |
| **expo-file-system** 57.0.7 | MIT (fichier `LICENSE` lu) | Stockage local géré des photos/signature (API `File`/`Directory`/`Paths` de SDK 57, pas l'ancienne API `FileSystem.*`) — copie hors du cache caméra vers `Paths.document`, lecture des octets pour le hachage SHA-256 (`src/photos/service.ts`, `src/signature/service.ts`) | Dépendance directe, version épinglée = celle de R12 §3 | **Intégré** (T1.4-e) | R12 · PLAN T1.4-e |
| **react-native-signature-canvas** 5.1.1 | MIT (fichier `LICENSE` lu) | Capture de la signature du client, rendu WebView (`signature.tsx`) — logique de décodage de sa DataURL isolée en fonction pure testée (`src/signature/dataUrl.ts`), la brique elle-même n'étant pas testable sous Jest (mission item 4) | Dépendance directe, version épinglée = celle de R12 §3 | **Intégré** (T1.4-e) | R12 · PLAN T1.4-e |
| **react-native-webview** 13.16.1 | MIT (fichier `LICENSE` lu) | Pair REQUIS de `react-native-signature-canvas` (`peerDependencies`, non listé par R12 §3) — `react-native-signature-canvas` rend sa capture dans une WebView | Dépendance directe — **écart de source** : non fournie par R12 §3 (péri­phérique d'une autre brique) ; version lue dans `node_modules/expo/bundledNativeModules.json` (le tableau que consulte `expo install` en interne), le CLI `expo install` lui-même étant indisponible ici (vérificateur de compatibilité en ligne bloqué par le proxy sortant du bac à sable) — installée explicitement car `legacy-peer-deps=true` n'installe jamais un pair automatiquement | **Intégré** (T1.4-e) | PLAN T1.4-e |

**`.npmrc` : `legacy-peer-deps=true`.** `react-dom` est un pair **optionnel** de
`expo`/`expo-router`/`@expo/metro-runtime` (support web, non utilisé — app mobile iOS/Android
seulement). Selon l'ordre de résolution, npm 10 le fait parfois échouer en erreur `ERESOLVE` dure
plutôt qu'en avertissement tolérable ; ce réglage évite ce faux blocage sans changer une seule
version réellement installée (toutes vérifiées une à une ci-dessus). Aucun paquet web
(`react-dom`, `react-native-web`) n'est installé.

## M1 — Front Office

| Brique | Licence vérifiée | Rôle dans OPSYS | Intégration | Phase | Rapport source |
|---|---|---|---|---|---|
| **Pipecat** (Daily) | BSD-2-Clause | Colonne vertébrale de l'orchestration voix temps réel (pipeline STT→LLM→TTS, connecteurs Twilio/Deepgram/faster-whisper/ElevenLabs) | Dépendance pip | Phase 2 | R6 |
| **faster-whisper** + checkpoint communautaire `whisper-large-v3-turbo-fr-quebecois` | faster-whisper : MIT · checkpoint : licence du fine-tune non vérifiée ligne à ligne (dérivé Whisper) | STT local, WER 6,65 % mesuré sur français québécois (vs ~19,5 % générique) | pip + poids local | Phase 2 | R6 |
| **whisper.cpp v1.8.0 / large-v3-turbo q5_0** — candidat R43 | Runtime MIT ; qualification des poids et redistribution à distinguer | Banc CPU HTTP réel : 20 locuteurs fr-CA, WER 29,02 %, p95 42,16 s | Recherche locale séparée, aucun raccord produit | Refusé pour le budget temps réel Core 4 s sur ce CPU ; parole lue seulement | [Mesures R43](R43-ASR-FRCA-MESURES-2026-10-02.md) |
| **Twilio** (Voice/SIP/SMS/WhatsApp BSP) | SaaS propriétaire (SDK usage courant MIT, non revérifié ligne à ligne) | Téléphonie + SMS + WhatsApp Business en un seul contrat | SDK API | Phase 2 | R6 |
| **ElevenLabs** | SaaS propriétaire | TTS client-facing : seul fournisseur à documenter des voix « Québec » natives | SDK API | Phase 2 | R6 |
| **Piper** (`piper1-gpl`) / **Kokoro-82M** — repli TTS gratuit non critique | Piper (dépôt maintenu) : GPL-3.0 (ancien dépôt MIT gelé/archivé) · Kokoro : Apache-2.0 | Messages internes/tests où l'accent québécois n'est pas critique | Piper : **service/process séparé uniquement** (jamais `import`é, GPL) · Kokoro : poids distincts du pipeline français eSpeak/GPL, liaison/service à qualifier (R16) | Phase 2 | R6 |
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
| PERT maison sur `random.Random.betavariate` (stdlib) | stdlib : aucune dépendance | Tirage PERT (bêta) de `monte_carlo.py` quand un poste du barème porte un mode (`cout_unitaire_mode`), sinon uniforme ; déterminisme bit à bit conservé | **Intégré (T4.11)** : stdlib seulement, scipy non requis | Phase 2 | R7 |
| **WeasyPrint** | BSD-3-Clause | Génération du devis PDF depuis le contrat gelé `EstimationV1` (Jinja2→HTML→PDF) | Dépendance pip ; exige Pango (bibliothèque système) : **écartée pour le PDF de la soumission brouillon de la v1** au profit de ReportLab ci-dessous, gardée en réserve pour un devis à mise en page riche | Phase 2 | R7 |
| **ReportLab** | BSD-3-Clause (fichier `LICENSE` de la roue 4.5.1, lu le 2026-09-29). La roue embarque aussi des polices avec leurs propres licences, lues dans `reportlab/fonts/` : Bitstream Vera (permissive, redistribuable), DarkGarden (GPL-2 ou plus avec exception de police) ; **aucune n'est utilisée par nous** (Helvetica standard, non incorporée) ni modifiée : simple présence de fichiers de données dans la roue, à savoir pour la revue GPL d'AGENTS.md | Rend la soumission brouillon de M3 en PDF (`soumission_pdf.py`, PLAN T2.3-f) : mêmes champs que le HTML, aucun coût ni marge, montants `Decimal` mis en forme à la québécoise, mention BROUILLON sur toute page. Python pur, aucune bibliothèque système (ni Pango ni Cairo) : l'installateur et l'image l'installent avec pip seul. Mode `invariant` + date de création tirée de l'horodatage du devis : mêmes entrées, mêmes octets | Extra `soumission` de `pyproject.toml` (`reportlab==4.5.1`), import paresseux, version épinglée vérifiée à l'exécution (`pdf_installe`) ; roue 2 Mo, `py3-none-any` ; dépendances déclarées, licences lues le 2026-09-29 : Pillow (MIT-CMU, déjà tiré par d'autres briques, roue avec ses bibliothèques), charset-normalizer (MIT). Extra absent : verdict « installer l'extra soumission », jamais un HTML renommé ; job M3 de la CI et image Docker l'installent | **Intégré** (extra optionnel ; exercé par les tests de M3 quand il est installé, toujours en CI) | R7 · T2.3-f |
| **pypdf** | BSD-3-Clause (fichier `LICENSE` de la roue 6.19.0, lu le 2026-09-29 et revérifié pour R28) | Relit les PDF M3 dans les tests; extrait aussi du texte paginé dans le worker natif financier isolé | Extras `dev` et `ingestion-pdf` (`pypdf==6.19.0`); exécution Linux/bubblewrap bornée, source et résultat chiffrés | **Intégré localement** (tests et backend natif; interface/installation VPS séparées) | T2.3-f · [R28](../programme/LOT-FUSION-PDF-NATIF.md) |
| **SAM 2** (Meta) + **Grounding DINO** (via `transformers`) | SAM 2 : Apache-2.0 · Grounding DINO : Apache-2.0 | Mesure par objet de référence réelle (segmentation + localisation par texte), vérifie par le pixel ce qui n'était que déclaré | Sidecar Python (FastAPI interne), poids séparés | Phase 2 | R7 |
| **Depth Anything V2** — checkpoint **Small** uniquement | Apache-2.0 (Small ; Base/Large/Giant en CC-BY-NC, voir Refusées) | Carte de profondeur relative → mesure métrique avec un point d'échelle | Sidecar Python | Phase 2 | R7 |
| **SAM 3** (Meta) | Licence « SAM License » personnalisée (source-available, commercial autorisé mais clauses anti-rétro-ingénierie/riposte) | Segmentation par concept texte en un appel | Sidecar Python isolé, jamais redistribué | Phase 2, **signalé** (validation juridique requise avant usage) | R7 |

## M4 — Field Ops

| Brique | Licence vérifiée | Rôle dans OPSYS | Intégration | Phase | Rapport source |
|---|---|---|---|---|---|
| **PyVRP** | MIT (`LICENSE.md` du dépôt PyVRP/PyVRP, lu le 2026-09-28) | Solveur de tournées avec fenêtres, quarts, flotte hétérogène, clients optionnels ; remplace le tourniquet de `cedule.py`. Compétences par profils de matrice (le natif est réservé à PyVRP Enterprise, non utilisé). Graine explicite, `MaxIterations` seulement | Extra `tournees` de `pyproject.toml` (`pyvrp==0.14.0`) ; adaptateur `tournees.py` (T4.1-c), import paresseux, version épinglée vérifiée à l'exécution ; roue 1,2 Mo cp311/cp312 x86_64 et arm64 ; dépendances déclarées de la roue, licences lues le 2026-09-29 dans les fichiers installés : numpy (BSD-3-Clause), matplotlib (licence de type PSF, non utilisée par nous), tqdm (MPL-2.0 et MIT), vrplib (MIT) ; toujours derrière `verifier_plan`, avec repli DP exact stdlib jusqu'à 12 chantiers | **Intégré** (extra optionnel ; exercé par les tests de M4 quand il est installé) | R15 |
| **Google OR-Tools** | Apache-2.0 (`LICENSE`, branche `stable`, lu) ; la roue embarque Cbc/Clp en EPL-2.0 (non listée dans AGENTS.md : décision humaine avant adoption), HiGHS (MIT), SCIP (Apache-2.0) | Alternative documentée si les contraintes de cédule deviennent riches (compétences natives) | Aucune dépendance aujourd'hui ; roue 30 Mo, exige numpy ≥ 2 et pandas | Référence | R15 |
| **OSRM** | BSD-2-Clause (`LICENSE.TXT`, lu) ; données OSM en ODbL 1.0 (attribution ; graphe dérivé non distribué) | Palier 1 optionnel : matrice routière (`Table`) sur extrait régional épinglé ; le palier 0 est l'haversine × détour, en mode bridé affiché | Sidecar Docker local ; estimé ≈ 2 Go de RAM pour tout le Québec (extrapolation du wiki OSRM), donc extrait régional | Phase 2 | R7 · R15 |
| **RQA — Référentiel québécois des adresses** | Données CC-BY 4.0 (fiche MRNF et Données Québec, lues 2026-09-28 ; attribution à afficher) | Géocodage local et hors ligne des adresses de chantier ; `qualite_positionnement_geometrique` gouverne « proposée » ou « à confirmer » ; confirmation humaine unique | Import mensuel du CSV (596 Mo) filtré par MRC dans l'index SQLite de l'instance (`<OPSYS_HOME>/rqa/index.sqlite`), livré en T4.1-a : `python -m m4_field_ops.localisation importer --csv … --index … [--mrc …]` ; aucun appel réseau (test aux sockets bloqués). Colonnes lues du guide d'utilisation v1.2 (le CSV réel n'a pas été téléchargé). **Attribution** : champ `attribution` de la réponse de `m4_proposer_localisation`, à afficher par l'écran de confirmation de l'app admin ; « données filtrées par MRC et arrondies au microdegré » y tient lieu de mention de modification | Phase 2 | R15 |
| **Haversine × détour** (patron maison, `pointage.distance_km`) | Code du dépôt | Palier 0 de la matrice de durées ; paramètres d'entreprise obligatoires (détour, vitesse, marge) | `distances.py` (T4.1-b) | Référence | R15 |
| **MSC GeoMet** (ECCC, `api.weather.gc.ca`) | « Environment and Climate Change Canada Data Services End-use Licence » v2.1.1 : mondiale, gratuite, perpétuelle, non exclusive, **usage commercial permis** ; à condition de citer la source (« Contains information licenced under the Data Server End-use Licence of Environment and Climate Change Canada. »), de lier la licence (https://eccc-msc.github.io/open-data/licence/readme_en/), de ne pas suggérer l'aval d'ECCC, et de ne reproduire un avertissement météo qu'en n'en altérant ni le contenu ni l'intention. **Lue le 2026-09-29 dans la page de licence d'ECCC, par une lecture de la documentation en ligne (aucun fichier `LICENSE` à lire : c'est une licence de service, pas un dépôt)** ; le texte n'a pas été relu par un juriste | Prévision horaire (température, vent, probabilité de précipitations) d'un chantier pour juger les règles météo d'un créneau de cédule ; **donne ni rafales, ni quantité de précipitations, ni verglas fiable** : les règles qui les demandent restent « inconnu », jamais « ok » | Adaptateur `meteo_geomet.py` (T4.13) de la collection `citypageweather-realtime` (marquée expérimentale par ECCC), **fermé par défaut** : ouvert seulement par `fournisseur: msc_geomet` dans le profil météo (`opsys-metier meteo declarer`) ; seule la position générale du chantier (dixième de degré) est envoyée ; l'attribution est rendue à chaque résultat ; aucune alerte n'est reproduite ; tests sans réseau (sockets bloqués, réponses fictives) | Intégré | R7 |
| **Open-Meteo** (API hébergée) | Code serveur self-host : AGPL-3.0 (non exécuté ici) · données : CC BY 4.0 (« Weather data by Open-Meteo.com », lien https://open-meteo.com/) · **API gratuite réservée à un usage non commercial** (conditions https://open-meteo.com/en/terms, lues le 2026-09-29 : un service à abonnements ou une intégration dans un produit commercial est un usage commercial) ; l'usage commercial exige un forfait payant, servi par `customer-api.open-meteo.com` avec `apikey` | Autre source de prévision (rafales, quantité de précipitations, code météo verglas) pour les règles météo d'un créneau, **si le propriétaire prend un forfait commercial (décision GATE NATHAN, non prise)** | Adaptateur `meteo_open_meteo.py` (T4.13) : **fermé par la configuration, deux fois** : le profil doit déclarer `fournisseur: open_meteo` ET `open_meteo.forfait: commercial`, et la clé d'API doit être dans la variable d'environnement que le profil nomme (jamais dans le profil) ; sans cela, aucune requête ne part ; l'hôte gratuit `api.open-meteo.com` n'est pas dans la liste fermée des hôtes ; l'attribution est rendue à chaque résultat | Intégré (fermé par défaut) | R7 |
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
| **Scrapy** | BSD-3-Clause (source primaire R16) | Alimente `competitive/*` en snapshots réels (au lieu de fixtures figées), configuration conforme aux accès/conditions applicables requise ; `robots.txt` seul ne prouve pas le droit de collecte | Dépendance pip directe | Phase 2 | R9 |
| **Postiz** | AGPL-3.0 | Planification sociale multi-canal + Google Business Profile (post et lecture des métriques) | **Service sidecar non modifié** ; adaptateur Python déjà écrit (`postiz_adapter.py`, GATED `enabled=False`/`dry_run=True`) | Phase 2 (adaptateur codé et gated ; service Postiz non déployé) | R9 |
| **Astro** | MIT | Rendu du site (îlots, zéro JS par défaut), remplacerait le générateur HTML-par-f-string actuel ; `guardrail.py`/`aeo_engine.py` restent les gates inchangés | Build-time (pas un service runtime) | Phase 2 | R9 |
| **Unlighthouse** + **SerpBear** | MIT (les deux) | SEO technique à l'échelle : Core Web Vitals réel sur tout le site + suivi de position mots-clés | CLI/sidecar Docker | Phase 2 | R9 |
| **geo-optimizer-skill** | MIT | Second avis réseau pour l'AEO/GEO (citation réelle dans ChatGPT/Perplexity/Gemini), consommé par `aeo_engine.py`, jamais l'inverse | Sidecar/serveur MCP | Phase 2 | R9 |
| **Listmonk** | AGPL-3.0 | Emailing (newsletters, annonces de chantier), binaire Go unique très léger | **Service sidecar non modifié** | Phase 2 | R9 |
| **FLUX.1-schnell** / **Qwen-Image** | Apache-2.0 (les deux) | Génération de visuels promotionnels sans condition commerciale | Poids locaux ou API | Phase 2 | R9 |
| **changedetection.io** | Apache-2.0 | Veille concurrentielle continue (alertes sur changement de page), complète le snapshot ponctuel Scrapy | Sidecar Docker | Phase 2 | R9 |
| **OpenCV** (`opencv-python-headless`, CODE) + **YuNet** (`face_detection_yunet_2023mar.onnx`, POIDS) | OpenCV ≥4.5.0 : Apache-2.0 (vérifié <https://opencv.org/license/>) · YuNet : **MIT** (vérifié dans `models/face_detection_yunet/LICENSE` du dépôt github.com/opencv/opencv_zoo, Shiqi Yu 2020 — distinct de la licence Apache-2.0 du dépôt `opencv_zoo` lui-même) | Détection de VISAGES avant floutage obligatoire de tout contenu public (`m7_marketing.moderation.detection`, PLAN T4.3, M7-audit.md §3.5), via `cv2.FaceDetectorYN` | Dépendance pip (non installée dans ce bac à sable — `ModuleNotFoundError` vérifié) ; interface `Detecteur` injectable déjà écrite et testée (images synthétiques), adaptateur réel à brancher une fois la dépendance disponible | Phase 2 (logique et interface livrées et testées ; adaptateur réel non branché) | M7-audit.md §3.5 |
| Cascade Haar `haarcascade_russian_plate_number.xml` | **Apache-2.0** (livré DANS le dépôt principal `github.com/opencv/opencv`, `data/haarcascades/` — même licence que le code OpenCV ci-dessus, aucun poids ni dépôt tiers séparé) | Détection de PLAQUES avant floutage obligatoire de tout contenu public, via `cv2.CascadeClassifier`. Limite documentée : entraîné sur les proportions des plaques russes, imprécis sur les plaques québécoises — mitigé par la revue humaine obligatoire sous le seuil de confiance (`moderation.floutage`), à réévaluer avant tout volume réel | Dépendance pip (même paquet OpenCV que ci-dessus) ; même statut d'adaptateur (interface prête, branchement réel à faire) | Phase 2 | M7-audit.md §3.5 |

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
| **DeepEval** / **Ragas** | Apache-2.0 (les deux) | Évaluations sur jeux « golden » par département, avec métriques adaptées ; aucun gate de consensus imposé | Dépendance optionnelle ou banc isolé | Candidate | R10 · ADR-0012 |
| Patron interne `civ_review.py` / `tally_reviews.py` (ancienne proof-method) | — | Historique de débat multi-fournisseurs ; ne prouve pas un composant M9 présent. ADR-0012 retire ce protocole comme prérequis ; déclencher un spécialiste ou critique seulement si la question le justifie | Aucune adoption automatique ni vote obligatoire | **Historique** | R10 · ADR-0012 |
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
| fpdf2 (roue 2.8.8) | M3 | Licence LGPL-3.0 admise en dépendance dynamique (fichier `LICENSE` de la roue, lu le 2026-09-29) : le refus est technique. Ses polices de base n'encodent que le Latin-1 : « œ » (main-d'œuvre), « — » et « ’ » lèvent `FPDFUnicodeEncodingException` (mesuré), et la roue ne livre aucune police TrueType à incorporer. ReportLab (WinAnsi) les rend sans police à livrer | T2.3-f |
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
| YOLOv8 / YOLO11 (Ultralytics) **en dépendance directe vendorisée**, pour la détection de visages/plaques | M7 | Licence **AGPL-3.0** du dépôt `ultralytics/ultralytics` ; incompatible avec AGENTS.md hors service séparé non modifié — OpenCV + YuNet (MIT) retenus à la place, voir tableau ci-dessus | M7-audit.md §3.5 (PLAN T4.3) |
| Metabase (OSS) en usage **client-facing** | M8 | AGPL-3.0 ; l'embedding vers des tiers exige une licence commerciale séparée même en restant AGPL en interne — usage interne seul reste gratuit | R9 |
| Robyn (Meta) | M8 | Le moins actif des trois candidats MMM (push 2026-01), historiquement R-first (Python en second plan) | R9 |
| `pyMCDM` | M9 | GPL-3.0 (contredit une source secondaire qui l'annonçait « MIT ») — incompatible en dépendance directe d'un produit commercial fermé | R10 |
| `langchain-ai/open_deep_research` | M9 | Dépôt **archivé** le 2026-08-21, lecture seule — référence de conception seulement | R10 |
| `cpgoncalves/strategy-analyzer` | M9 | 2 ★, dormant depuis ~2017, licence non-OSI standard (fichier « Creative Commons » en PDF) | R10 |
| ClawHub (OpenClaw) / HermesHub (Hermes) comme **sources d'installation automatique** de skills | M9 (transversal) | Incidents de sécurité vérifiés et massifs : 341-824+ skills malveillantes (« ClawHavoc »), CVE-2026-25253 (RCE, CVSS 8.8) — seul un fichier `SKILL.md` individuel, revu à la main, peut être vendorisé | R1 · R10 |
| pyvroom / VROOM **en processus** | M4 | La roue pyvroom embarque `libglpk` (GPL-3.0+, vérifié dans l'en-tête glpk.h) et libgmp, alors que sa métadonnée dit BSD-2 : contraire à AGENTS.md hors service séparé non modifié ; binaire de l'image Docker officielle non vérifié | R15 |
| Nominatim public (OSMF) et API de géocodage tierces hors Québec | M4 | La politique OSMF interdit de soumettre des renseignements personnels ; les autres imposent l'art. 17 de la Loi sur le privé (EFVP et entente écrite). Le géocodage reste local (RQA) | R15 |

---

## Décompte

- **Core** : 2 retenues (2 intégrées — OpenClaw comme core par défaut, Hermes Agent comme adaptateur optionnel, ADR-0007) + 1 refusée.
- **Modèles/tokens** : 9 retenues (2 intégrées, 6 phase 2, 1 référence) + 6 refusées.
- **Mémoire/RAG** : 16 retenues (14 phase 2/optionnelles, 2 référence) + 6 refusées.
- **Déploiement/observabilité** : 20 retenues (2 intégrées — uv, installateur de PLAN T0.11, et actionlint, contrôle du workflow de PLAN T0.11-d —, 16 phase 2, 2 référence — WAL-G, et le trio Coolify/Dokploy/Supabase en une seule ligne) + 2 refusées.
- **Mobile** : 23 retenues (23 intégrées — squelette Expo Router de PLAN T1.4-a, +4 pour le
  client d'appairage de PLAN T1.4-c3 : `expo-secure-store`, `@noble/curves`, `@noble/hashes`,
  `@types/node`, +4 pour le chantier du jour/checklist/photos/signature de PLAN T1.4-e :
  `expo-camera`, `expo-file-system`, `react-native-signature-canvas`, `react-native-webview`)
  + 0 refusée.
- **M1** : 11 retenues (1 intégrée — code interne conservé —, 10 phase 2) + 2 refusées.
- **M2** : 4 retenues (phase 2) + 2 refusées.
- **M3** : 8 retenues (2 intégrées — ReportLab, extra `soumission`, et pypdf, dépendance de test —, 6 phase 2) + 4 refusées (fpdf2, T2.3-f).
- **M4** : 8 retenues (3 intégrées — PyVRP, extra `tournees`, et, depuis T4.13, les adaptateurs météo MSC GeoMet et Open-Meteo, ce dernier fermé par défaut —, 5 phase 2 ou référence, dont le patron haversine × détour, et OR-Tools en référence) + 3 refusées (R15).
- **M5** : 8 retenues (7 phase 2, 1 référence) + 5 refusées.
- **M6** : 4 retenues (phase 2) + 1 refusée.
- **M7** : 11 retenues (phase 2) + 4 refusées.
- **M8** : 8 retenues (phase 2) + 2 refusées.
- **M9** : 13 retenues (2 intégrées — format Agent Skills et patron `civ_review.py` —, 11 phase 2) + 4 refusées.
- **M10** : renvoie au domaine Mémoire/RAG + 2 éléments propres (1 intégrée — modèle Département —, 1 phase 2).

**Total : 144 briques/patrons retenus** (dont 37 déjà intégrés au code ou à la méthode : **OpenClaw**
comme core par défaut, **Hermes Agent** comme adaptateur/runtime optionnel, **LiteLLM** comme
passerelle de compatibilité optionnelle, la discipline de cache-boundary (désormais native au runtime
OpenClaw), `garde_fou.py` M1 conservé, le format Agent Skills, le patron
`civ_review.py`/`tally_reviews.py`, le modèle « Département » de M10, les 15 briques du
squelette de l'app mobile — PLAN T1.4-a : Expo/Expo Router/expo-sqlite/expo-localization/
expo-crypto, i18next/react-i18next, React/React Native et les dépendances de navigation
requises par Expo Router, Jest/jest-expo/babel-preset-expo/@react-native/jest-preset,
TypeScript — et les 4 briques du client d'appairage mobile — PLAN T1.4-c3 :
`expo-secure-store`, `@noble/curves`, `@noble/hashes`, `@types/node` — et les 4 briques du
chantier du jour/checklist/photos/signature — PLAN T1.4-e : `expo-camera`, `expo-file-system`,
`react-native-signature-canvas`, `react-native-webview` — et PyVRP, le solveur de tournées de M4 —
PLAN T4.1-c — et ReportLab, le rendu PDF de la soumission de M3, avec pypdf qui le relit dans les tests — PLAN T2.3-f — et actionlint, qui contrôle le workflow de l'installateur — PLAN T0.11-d — et les adaptateurs météo MSC GeoMet et Open-Meteo (fermé par défaut) de M4 — PLAN T4.13) **et 41 refusées
explicitement**, sur les 10 rapports `docs/research/R1`–`R10` et
R12 ; mise à jour du choix de core par
[ADR-0007](../decisions/ADR-0007-core-openclaw.md), vérifiée directement dans le code, les tests et le
clone local d'OpenClaw (pas seulement relayée).

## Correctifs maintenus du tooling mobile — 4 octobre 2026

| Brique | Licence vérifiée | Adoption et preuve | Limites |
|---|---|---|---|
| braces, PR micromatch/braces #72, `28d440b5dd449dbf1fe6f3506cf94ecca4d02660` | MIT, LICENSE conservée | Copie privée `@opsys-ai/braces` 3.0.3-opsys.1, limite de profondeur et deux fixes de parseur amont; 940 cas réussis, résolution Metro réelle | Expansion cartésienne non bornée globalement; maintenance OPSYS |
| node-forge, PR digitalbazaar/forge #1152, `ceba34402e329f0365134f23fe19898756527d65` | BSD-3-Clause choisie, licence duale conservée | Copie privée `@opsys-ai/node-forge` 1.4.0-opsys.1 du runtime npm, correctif RSA ciblé; 829 tests réussis et 4 pending amont, consommateur Expo réel | Ni release officielle corrigée ni audit cryptographique exhaustif; maintenance OPSYS |

Sources, empreintes, graphes et résultats : [qualification mobile](REPRISE-2026-10-04/MOBILE-DEPENDANCES-FORKS.md).
Aucune autre version verrouillée n’est modifiée. Le seuil npm high reste actif;
13 alertes moderate restent ouvertes. Le catalogue npm ignore les identités privées :
la revue et les régressions qualifient les correctifs, pas le seul décompte d’audit.


## OCR de factures scannées — recherche du 4 octobre 2026

| Brique examinée | Pin et licence du code | Décision et limites |
|---|---|---|
| Docling | v2.133.0, `b0315ea356298e4659c9727e9f5191dd2001860a`, MIT | Candidat layout/table, non adopté. Licences des poids déclarées dans les cartes, vérification complète ouverte; extras/CPU/RAM à mesurer. |
| OCRmyPDF | v17.13.0, `1a1cfb595b9a504a4689b23193a76bae7c3a156d`, MPL-2.0 | Premier profil de benchmark CPU envisagé, non installé. Ghostscript optionnel; pipeline PDFium/Tesseract distinct du lecteur natif. |
| Tesseract et données `fra` | moteur5.5.1 `3b7c70e34dea179549ed3e995872e2e019eb8477`; tessdata_fast `87416418657359cb625c412a48b6e1d6d41c29bd`, Apache-2.0 distinctes | Langue disponible, précision fr-CA/AP non mesurée. Pack1130365octets selon métadonnées, non téléchargé. |
| pypdfium2/PDFium | stable5.13.0 `a4659102e4c258ee18c661232c0f9763f6c85ad0`, wrapper Apache/BSD, wheel Linux x64 exact et ses 19 notices vérifiés | [Identité d’artefact](REPRISE-2026-10-04/M5-OCR-ARTEFACT-PDFIUM-2026-10-04.md) : PDFium build 7999 identique au binaire de release amont; fonctionnement du candidat encore à qualifier, sans adoption. |
| GitLab do-invparse | `6c0205666604cd3acbe547110e9a02104d460cc4`, MIT OR Apache-2.0 | Source distincte, non retenue : OCR planifié, modèle européen EN16931; aucune preuve OCR CAD/TPS/TVQ. |

[Analyse, sources, contrats et profils](REPRISE-2026-10-04/M5-OCR-GITHUB-GITLAB.md).
Recherche bornée GitHub et GitLab; aucun moteur, modèle, fournisseur ou donnée client
exécuté. OCR prépare des fragments citables à revoir, sans approbation, saisie M5 ou paiement.


### Premier essai OCR CPU, versions existantes

[pilote isolé](REPRISE-2026-10-04/M5-OCR-PILOTE-CPU-2026-10-04.md): PDFium via
pypdfium2 5.3.0 (`04b411aa95642d5ff58244363326f761d51e2c10` pour le wrapper),
Tesseract 5.5.0 (`64eab6c457b2337dd690746a5fde5c222b40d5f8` amont), Leptonica 1.84.1
et `fra` fast épinglé. Deux fixtures : 10/10 puis 4/10 lignes strictement identiques,
avec erreur d’identifiant. Notices installées/bundle et limites conservées;
commit source PDFium natif non résolu. Prototype sans adoption ni automatisation AP.

## Recherche de raccord avatar/TTS — complément du 5 octobre, non adopté

Complément à l’étude audiovisuelle du 4 octobre, fondé sur les captures locales épinglées dans le manifeste `evidence/CAPTURES.json` dans la [capsule de recherche](REPRISE-2026-10-05/preuves/AVATAR-TTS-RECHERCHE-r2.tar.xz). Recherche uniquement : aucun paquet, modèle, TTS ou service n’a été adopté ou qualifié.

Le renderer chat existant valide et rend un modèle Three.js, mais n’anime pas les morphs et ne reçoit ni audio ni horloge. Le lecteur TTS existant possède déjà un unique `HTMLAudioElement`, son `currentTime` et les commandes lecture/seek; aucun événement de synchronisation n’est exposé au renderer. Sources locales et SHA-256 : `chat-agent-3d-avatar.ts` `942b0b63246ec8fb7c49dc751712980941ef0d1b5d52c59907f4ad53d4c398de`; `chat-audio-player.ts` `ddeefb7db7dd1cf68a33885bfe3c1c24deaae009ee50aea2a5628239933da90f`; catalogue de modèles `assistant-avatar-model-catalog.ts` `4af1932afe3be380c24f8002730f8ddd30908934e436674bf03c8b31ca1bb280` (reçus dans `evidence/LOCAL-SOURCES.json`).

**Décision recommandée :** raccorder d’abord le renderer existant au lecteur audio existant, avant toute nouvelle dépendance. Une réponse TTS unique associe même identité/source, clip et cues de visèmes; le temps média audio est l’horloge. `timeupdate` et seek recalculent le morph correspondant depuis `currentTime`; pause fige, interruption/changement de source/erreur invalide la génération, arrête l’audio et remet le visage au neutre. Fallback : conserver texte et lecteur normaux, plus un portrait HTML explicitement statique si le WebGL est indisponible. Aucun TTS supplémentaire, mouvement par amplitude, ou animation « parlante » fictive.

| Piste (non adoptée) | Version, code/modèle et preuve exacte | Limite déterminante |
|---|---|---|
| TalkingHead | `1.7.0`, commit `b3e277b3b46f88e557bf28a2c5612a5b04e075c3`; code MIT, fichier `LICENSE` 1 075 octets, SHA-256 `a168d1f90b70b313fb594ddb07e03c9dea08fe2a43df2b4f607db6920ce69cfa`. `speakAudio` accepte AudioBuffer/PCM et cues, `streamInterrupt()` existe. MPFB d’exemple déclaré CC0 dans README de même commit; brunette distincte CC BY-NC 4.0. | Three `^0.180.0`, WebGL navigateur, morphs Oculus/ARKit requis. Français générique documenté; fr-CA et qualité réelle non mesurés. |
| Rhubarb | `1.14.0`, commit `9b9573cd21b253c9ba58739bbd1aa0b50b991bff`; MIT dans `LICENSE.md`, 27 808 octets, SHA-256 `c9a10d99959990ec6802c5e2d519fb23665affa7ba32abbdea5b251ee5f93af6`. | CLI CPU hors ligne pour WAV final, cues A–H/X à 10 ms; pas de lecteur/avatar/seek. PocketSphinx anglais; `phonetic` non spécifique à une langue mais moins précis. fr-CA non qualifié. |
| NVIDIA Audio2Face-3D | SDK commit `1ca0f02535ed774f5dbcd724a31cd486368dc783`; MIT `LICENSE.txt`, 1 097 octets, SHA-256 `211c1b442d1d55e2989de4344d63e9e6b8896cb3bd91289a92da708597087dd6`. Modèle Audio2Face-3D-v3.0, révision HF `b74132732fd9a9d29b237bec193ded64c9745e91`; carte SHA-256 `cb824ad69b31f99e91f7f9b93ff0c19b5f00f296fdf0834ed359bb6191925905`, licence distincte NVIDIA Open Model License. API de métadonnées SHA-256 `119c700f950a0a12bc731afa9ba7a4f8ed40537ac35f1af75f1cceb0969084df`. | CUDA 12.8+, TensorRT 10.13, Python 3.8–3.10; 8 GB RAM, 4 GB+ VRAM recommandé, 10 GB disque. Diffusion prend 1 s et produit 0,5 s central; latence totale inconnue. GPU VPS/coût, retarget et qualité fr-CA non mesurés. La révision modèle est épinglée; aucun digest individuel des poids n’a été capturé. |

Aucun candidat n’a de latence end-to-end mesurée sur OPSYS ni de validation fr-CA. Les captures complètes (README/licences/modèle, en-têtes HTTP et SHA), l’historique de requêtes et les limites sont conservés dans cette même capsule, sous `research/evidence/`. La recherche GitLab a trouvé PassTheMic, spécification AGPL-3.0+, mais aucune implémentation/version utilisable prouvée; elle n’est pas retenue.

Publication : le README TalkingHead contient un JWT public d’exemple expurgé dans la capsule r2.
Son manifeste conserve le hash original et le hash expurgé. La capture brute r1 reste locale, exclue de publication.

## Conservation des preuves Core HTTP — 6 octobre 2026

Réutilisation du scénario métier durable et des installations Python/Node déjà verrouillées ; aucune dépendance d'application ajoutée. L'action officielle [actions/upload-artifact v4.6.2](https://github.com/actions/upload-artifact/releases/tag/v4.6.2), commit `ea165f8d65b6e75b540449e92b4886f43607fa02`, conserve JUnit, JSON et journal de qualification dans le dépôt privé pendant 30 jours, y compris après un échec. [Licence MIT vérifiée](https://github.com/actions/upload-artifact/blob/ea165f8d65b6e75b540449e92b4886f43607fa02/LICENSE). Action JavaScript précompilée, runtime déclaré Node20 dans son action.yml ; le scénario reste sous Node24. Aucun code de cette action n'est copié dans le Core. Une archive locale immuable complète la rétention limitée du runner. Les manifestes temporaires à jetons fictifs restent exclus de l'artefact.


## Réutilisation Pillow — aperçus M6.13, 2026-10-08

Pillow **12.3.0**, déjà verrouillé dans `requirements-runtime.lock.txt` et `uv.lock` via les briques existantes, est réutilisé pour vérifier la structure et charger les pixels PNG/JPEG avant transport des photos de pertes/bris. Aucun ajout ni renouvellement de dépendance. Licence **MIT-CMU** et notices codecs lues dans la roue locale ; elles restent distribuées avec le paquet. [Documentation primaire Image](https://pillow.readthedocs.io/en/stable/reference/Image.html). Le budget du produit est 10 MiB, 16 millions de pixels, 8192 pixels par dimension, une image fixe, sans désactiver les protections du décodeur. Runtime sans Pillow : aperçu fermé. Les essais négatifs distinguent fichier adressé par CAS et image effectivement décodable ; aucun résultat ne prouve la scène photographiée. [Contrat et limites M6.13](../architecture/PHOTOS-PREUVES-M6.md). Statut : tranche Python en qualification locale ; Gateway et mobile doivent apporter leurs preuves avant livraison.


## Mise à jour audio WhatsApp — 13 octobre 2026

Le consommateur Baileys du canal WhatsApp utilise désormais `music-metadata@11.16.0` par
l’override ciblé `baileys>music-metadata`, avec les autres résolutions conservées. Cette version
est la version corrigée indiquée par les avis primaires [GHSA-f94x-6692-553q](https://github.com/advisories/GHSA-f94x-6692-553q)
et [GHSA-5gfj-9q3v-qfp3](https://github.com/advisories/GHSA-5gfj-9q3v-qfp3). La [release officielle](https://github.com/Borewit/music-metadata/releases/tag/v11.16.0)
référence les correctifs MP4 et EBML (PR 2734 et 2735), au commit npm
`9e995a31c9e5526057a63936cb83d9f8b02e0fcc`. Publication npm vérifiée :
`2026-09-22T16:14:22.304Z`; le délai strict de 10 080 minutes est satisfait depuis le 29 septembre,
sans exception à la politique. L’archive npm de 135 711 octets a le SRI
`sha512-D5zZHjQUbfR+JhHjnwdbgeB4qj7zVJtisCB1I0GAI5sjSPGqPLoY14WMIzMeR8iA+4nSFswVLpO4crksZUybBg==`.
Le fichier MIT exact de 1 073 octets a le SHA-256
`ab27d7574bc6d292302b0b49c2e1ad6f0d88031822dce486257c085c7d83133c`; les exports,
la condition Node `>=18` et les dépendances déclarées sont identiques à ceux de 11.15.0.

La qualification locale du lot `music-metadata-safe-update-r1` sépare le calcul natif public de
durée sur audio ordinaire, les tests existants du canal et l’audit de production. Elle n’envoie
aucun message et ne lance aucun fournisseur; elle ne reproduit pas de fichier malveillant.
Ces contrôles de compatibilité ne constituent pas une preuve exhaustive contre toute entrée
malformée. Les avis DOMPurify, Joi et KaTeX restent suivis séparément; aucune autre dépendance
n’est renouvelée dans ce lot. La CI du commit intégré reste nécessaire.


## Correctif ciblé SDK MCP et redirections HTTP — 20 octobre 2026

Les overrides existants passent de `@modelcontextprotocol/sdk@1.31.0` à **1.32.0** et de
`follow-redirects@1.16.0` à **1.16.1**. Ils couvrent les consommateurs directs et transitifs,
notamment les liaisons de pairs de Google GenAI et les chemins Axios/Teams. Aucun autre paquet
ne change de version : le lockfile régénéré par pnpm **12.4.0** conserve ses **1534 paquets**,
**1535 snapshots** et le document du gestionnaire. Il actualise aussi **27 mentions de
dépréciation** de paquets existants, sans changement de leurs résolutions ni dépendances.

Avis primaires : [GHSA-22jm-h49p-29qw](https://github.com/advisories/GHSA-22jm-h49p-29qw)
pour l’isolation des tâches expérimentales du SDK ;
[GHSA-q3jh-wrc6-jgq8](https://github.com/advisories/GHSA-q3jh-wrc6-jgq8) et
[GHSA-8r9p-f939-6h3c](https://github.com/advisories/GHSA-8r9p-f939-6h3c) pour la suppression
des en-têtes sensibles lors des redirections. Le constat est un échec de l’audit du lockfile,
pas une démonstration d’exploitation dans OPSYS.

Publications npm vérifiées : SDK le **2 octobre à 17:32:51.427Z**, follow-redirects le
**1er octobre à 13:52:31.780Z**. Le délai strict de **10080 minutes** reste appliqué sans
exception. Dépendances et pairs déclarés sont identiques entre les versions comparées.
Archives npm contrôlées par leur SRI ; licences MIT exactes lues, inchangées : SDK **1071 octets**,
SHA-256 `5e13dbbc1d120fc2a03cecde7c91424ae2d7de11b63d58ded2f4431e261ee50d` ;
follow-redirects **1136 octets**, SHA-256
`bfa8a54bb952ccda79f0f1889721d108f5b605babbb2b8a3705ffb52f4132eb7`.

Qualification isolée : `pnpm install --lockfile-only --frozen-lockfile --ignore-scripts
--ignore-pnpmfile` réussit sur les 63 projets ; `pnpm audit --prod --audit-level=high` réussit
avec **zéro avis high**, mais conserve **3 low et 3 moderate**. Aucun paquet applicatif installé,
script tiers, service métier ou test Vitest exécuté dans cette vérification. Les fichiers
client MCP sélectionnés sont identiques ; le protocole partagé change pour l’isolation des
tâches. La compatibilité réelle du SDK et du lecteur historique exige encore la CI du commit
exact. Le lecteur reste sans appelant de réconciliation activé et la clôture Core reste inconnue.

## Manifestes de couverture du socle CI — 21 octobre 2026

La répartition du socle réutilise la collecte et les hooks natifs de pytest. Les deux runners
conservent l'inventaire complet et affectent chaque fichier par SHA-256 de son chemin relatif
POSIX. Le gate contrôle les deux manifestes du même commit, run et tentative avant de créditer
leur couverture. Le coût réel doit être mesuré sur la CI résultante ; le nombre de runners
ne constitue pas une preuve d'accélération.

La récupération de ces seuls manifestes utilise l'action officielle
[actions/download-artifact](https://github.com/actions/download-artifact) **v5**, fixée au commit
`634f93cb2916e3fdff6788551b99b062d0335ce0`. La licence MIT a été lue à ce commit :
blob Git `a67dca8b4f65d6bd351f6b1e333ce2cd84d843a5`, SHA-256
`3e855ffa704114a51628ef8f0bf3aeb41728adf9d9070e263bf58aa5640b0eb5`.
Le descripteur `action.yml` vérifié porte le blob
`7fc4fb55c7d0c7b198b1c7466e1efd7c7d05fb26`. Le dépôt d'artefacts conserve le pin existant
`actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02`.
Les manifestes sont des données JSON validées, conservées par tentative ; cette adoption
concerne le transport de preuves CI et laisse les dépendances applicatives inchangées.


### CRM-14 — préparation d’import de prix fournisseurs (27 octobre 2026)

Décision ciblée : réutiliser Decimal et les validateurs/projections/confirmations M6 existants
pour des lignes explicitement mappées; aucune nouvelle dépendance adoptée. Python `csv`
([documentation primaire](https://docs.python.org/3/library/csv.html)) reste candidat à un
adaptateur ultérieur borné, délimiteur/encodage/colonnes explicites, sans QUOTE_NONNUMERIC.
[Frictionless Python](https://github.com/frictionlessdata/frictionless-py),
[licence MIT examinée](https://github.com/frictionlessdata/frictionless-py/blob/main/LICENSE.md),
peut fournir extraction/validation CSV/Excel mais requiert maîtrise de l’inférence, quotas,
formats et traduction métier; coût disproportionné pour des lignes déjà mappées, non adopté.
Recherche GitLab primaire également effectuée, échantillon borné sans candidate suffisamment
qualifiée; aucune licence GitLab déclarée vérifiée. Aucun gain de temps chiffré ou format
fournisseur réel revendiqué. CSV/XLSX ne qualifient pas extraction PDF ni provenance courriel.


CRM-14 — confirmation du lot : composition des writers M6 natifs, des réclamations
idempotentes et de `stockage.transaction()` incluant rappels aprèsvalidation. Aucune
nouvelle dépendance, modèle ou orchestrateur introduit. Le reçu de lot ne remplace ni
les réceptions, ni l’audit, ni les références M10 de chaque writer. Les types JSON font
partie de la preuve; une égalité Python bool/int ne suffit pas pour valider un reçu.
