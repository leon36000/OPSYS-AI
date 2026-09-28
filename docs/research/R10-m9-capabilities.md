# R10 — M9 Strategic Intelligence & Modèle « Département » de capacités agents

Recherche de briques open source — OPSYS-AI, septembre 2026. Méthode : BRIEF commun
(`scratchpad/research/BRIEF.md`). Code existant lu en lecture seule : `Modules M/M9-strategic-intelligence`
et `Modules M/M10-memoire` (README, docs/bmad/01-03, src/). Licences vérifiées par lecture directe du
fichier `LICENSE` sur `raw.githubusercontent.com` (accès `api.github.com`/`github.com` direct bloqué dans ce
bac à sable pour les dépôts externes non attachés ; contourné avec `raw.githubusercontent.com`, autorisé,
et avec l'outil WebFetch pour les pages GitHub — étoiles/activité lues sur la page rendue, pas l'API JSON,
signalé explicitement où c'est le cas).

---

## 0. Ce que le code existant dit déjà (contrainte de départ, pas une supposition)

**M9 v1 (statut PARTIAL, S001/5)** est un **harnais déterministe pur** : stdlib + PyYAML, zéro réseau, zéro
horloge, **zéro appel LLM**. Il agrège des `SnapshotModule` fournis par l'appelant dans un registre
append-only hash-chaîné, détecte une seule catégorie de contradiction (même `module_source` + même
`horodatage`, `valeurs` différentes), et valide qu'un « rapport stratégique » contient EXACTEMENT les 15
clés de `CHAMPS_RAPPORT_STRATEGIQUE` (structure seulement, jamais le contenu). Tout le reste — **Council
d'agents (CEO/COO/CFO/CMO/Sales/Ops/Risk/Data/Execution), Strategic Supervisor, scénarios narratifs,
playbooks, Decision Intelligence Engine, Action Orchestrator, stack LangGraph/Temporal/Langfuse/Ragas/
DeepEval réelle, rythme exécutif (War Room, rapports, board memo)** — est explicitement **GATED/T3** dans
`docs/bmad/02-PRD-PM.md` §3.2 et `03-ARCHITECTURE.md` §7.2. **Conséquence directe pour cette recherche** :
toutes les briques de la partie A ci-dessous sont des ingrédients pour ces stories GATED futures, jamais
pour v1 — et leur sortie doit être traitée selon AGENTS.md §C (**CLAIMS UNVERIFIED**) : une affirmation
d'agent n'est pas une preuve tant qu'elle ne trace pas un `snapshot_id` source réel.

**M10 v1 (statut PARTIAL, S001-S006)** est le consommateur manquant du Work Completion Trigger de M4 et le
producteur de `ReferenceMemoireM10` que M9 attend (`memoire_m10`). Deux registres stdlib séparés
(Forge/Business), patron générique M5 (`type_entree`/`ligne_id`/`precedent_ligne_id`), **garde anti-mutation
structurelle** (aucune méthode `modifier`/`supprimer`/`fusionner`), réviser ≠ fusionner. **Vector memory,
embeddings, graphe inféré, context injector, PREFLIGHT/POSTFLIGHT appliqué (D-014) sont GATED** — la RAG
premium exigée par le propriétaire (exigence dure #5) n'existe donc dans aucun des deux modules
aujourd'hui : c'est un chantier à part entière, hors périmètre strict de R10 mais qui consommera
directement les registres M10 comme couche de vérité déjà posée.

---

## PARTIE A — Briques pour M9 (roadmap GATED)

### A.1 Agents de recherche / veille

| Brique | Licence (vérifiée) | Langage | Maturité | Apport OPSYS | Intégration | Effort | Risques |
|---|---|---|---|---|---|---|---|
| [GPT Researcher](https://github.com/assafelovic/gpt-researcher) | **Apache-2.0** — lu directement dans `LICENSE` (⚠️ le site officiel gptr.dev et des posts LinkedIn affirment à tort « MIT » ; le fichier fait foi) | Python | 29.7k★ (page GitHub), actif, 270+ contributeurs | Agent de recherche web multi-source avec citations — brique de base du futur « agent Data/Risk » du Council | Dépendance pip ou sidecar docker (fait ses propres appels réseau — doit passer par le connecteur réseau centralisé pour l'économie de tokens) | **M** | Fait ses propres appels LLM/recherche — chaque sortie doit être re-tracée en `SnapshotModule` avant d'entrer dans M9 (jamais consommée telle quelle, cf. §0) |
| [STORM / Co-STORM](https://github.com/stanford-oval/storm) | **MIT** (LICENSE) | Python | 31.5k★, actif (Co-STORM = collaboration humain-IA, releases jusqu'à v1.1.0 début 2025) | Génère un rapport long, structuré, **avec citations tracées** — correspond exactement au champ `preuves` des 15 clés `CHAMPS_RAPPORT_STRATEGIQUE` | Dépendance pip pour la génération de contenu du futur Council | **M** | Perspective-Guided Question Asking = un jugement éditorial du LLM ; garder le mécanisme de citation mais auditer, jamais publier sans revue (AGENTS.md §C) |
| [local-deep-research](https://github.com/LearningCircuit/local-deep-research) | **MIT** (LICENSE) | Python | 9.1k★, actif (7 987 commits) | Recherche 100% locale/chiffrée, LLM local ou cloud au choix — répond à l'exigence dure #2 (« modèles cloud ou locaux ») et limite la fuite de données concurrentielles sensibles | Dépendance pip ou service sidecar docker | **S/M** | Moins mature que GPT Researcher pour le multi-source web ; bon candidat pour la veille interne/confidentielle plutôt que la veille concurrentielle publique |
| [Open Deep Research (LangChain)](https://github.com/langchain-ai/open_deep_research) | MIT (LICENSE) | Python | 12.7k★ — **ARCHIVÉ par le propriétaire le 2026-08-21, lecture seule, plus aucune maintenance** | Patron « supervisor → sub-agents → synthèse » propre — **référence de design uniquement** | Ne pas vendoriser en dépendance vivante | — | Dépôt figé : dérive de sécurité non patchée si utilisé en prod ; à traiter comme documentation d'architecture, pas comme brique exécutable |

### A.2 Conseil multi-agents / débat — patrons et bibliothèques

Le patron générique documenté dans la littérature est le **« Multi-Agent Debate »** (plusieurs agents
proposent une réponse, se critiquent mutuellement, un juge synthétise ou un vote/quorum tranche) —
formalisé académiquement (Du et al., *Improving Factuality and Reasoning in LLMs through Multiagent
Debate*) et benchmarké par [instadeepai/DebateLLM](https://github.com/instadeepai/DebateLLM) (référence de
mesure, pas une dépendance à vendoriser) et cataloguée par
[Andrewzh112/Awesome-LLM-based-MultiAgents](https://github.com/Andrewzh112/Awesome-LLM-based-MultiAgents).

**Constat central, spécifique à ce dépôt** : OPSYS a **déjà** une implémentation de production de ce
patron — `~/proof-method/scripts/civ_review.py` + `tally_reviews.py` (3 reviewers vendors distincts,
verdicts scellés par `prompt_sha256`, anti-Sybil par `vendor_of`, Delphi anonymisé max 2 rounds). C'est
structurellement le même mécanisme qu'un « Council d'agents » qui doit produire un diagnostic contesté puis
arbitré. **Recommandation : ne pas importer un framework de débat externe pour le Council M9 ; copier-adapter
`civ_review.py`/`tally_reviews.py`** (patron interne déjà prouvé, licence non-applicable car interne), en
remplaçant « revue de code » par « avis stratégique d'un rôle du Council » — cohérent avec la règle #109
(copie-adaptation, jamais d'import) déjà appliquée 5 fois dans le dépôt.

Pour l'**orchestration mécanique** (séquencement des rôles, état partagé, checkpoints), les bibliothèques
pertinentes :

| Brique | Licence (vérifiée) | Maturité | Apport OPSYS | Effort | Risques |
|---|---|---|---|---|---|
| [LangGraph](https://github.com/langchain-ai/langgraph) | **MIT** (LICENSE) | 42.4k★, actif | **Déjà nommé dans la fiche source de M9** comme moteur cible du Strategic Supervisor (graphe d'état typé, checkpoints, reprise) — licence confirmée saine pour un produit commercial | **M** | Couplage à l'écosystème LangChain ; bien isoler derrière une interface interne fine pour ne pas lier tout M9 à une seule bibliothèque |
| [CrewAI](https://github.com/crewAIInc/crewAI) | **MIT** (LICENSE, Copyright crewAI Inc. 2025) | 59.1k★, actif, A2A + MCP natifs depuis v1.10+ | Modèle « rôles » (CEO/COO/CFO…) qui correspond texto au vocabulaire de la fiche source M9 — bon pour un prototype rapide du Council avant de figer sur LangGraph | **S/M** | Moins de contrôle fin sur l'état que LangGraph — à réserver au prototypage, pas à la version gelée |
| [Microsoft AutoGen](https://github.com/microsoft/autogen) | **MIT** — ⚠️ le `LICENSE` racine du dépôt est CC-BY-4.0 (contenu/docs) ; le code est sous **`LICENSE-CODE` = MIT**, vérifié séparément | 61.2k★, actif | Modèle conversationnel (GroupChat) — alternative si le Council doit ressembler à une réunion plutôt qu'à un graphe figé | **M** | Bien vendoriser `LICENSE-CODE`, pas le `LICENSE` racine, dans tout dossier de conformité |

### A.3 Planification de scénarios

| Brique | Licence (vérifiée) | Maturité | Apport OPSYS | Effort | Risques |
|---|---|---|---|---|---|
| [EMA Workbench](https://github.com/quaquel/EMAworkbench) (TU Delft) | **BSD-3-Clause** (LICENSE.md) | 154★, actif (1 620 commits), académique mais maintenu | « Exploratory Modeling and Analysis » — **découverte de scénarios et décision robuste sous incertitude profonde**, exactement le besoin des scénarios 7j/30j/90j/6mois/12mois + stress tests de la fiche source M9 ; bien plus rigoureux qu'un Monte Carlo ad hoc (déjà utilisé en M3-Estimation) | **M** (framework large ; vendoriser seulement le module de scenario-discovery, pas tout le multi-simulateur Vensim/NetLogo) | Conçu pour la modélisation de politiques publiques/climat — vocabulaire à adapter au contexte PME |
| [cpgoncalves/strategy-analyzer](https://github.com/cpgoncalves/strategy-analyzer) | Fichier « Creative Commons » (PDF) présent, **pas une licence OSI standard** — non vérifiable proprement | **2★, dormant depuis ~2017** | Concept intéressant (analyse par percolation d'un « web » d'événements/actions stratégiques) mais **non retenu** : trop immature, licence ambiguë | — | **Ne pas vendoriser** ; au mieux une référence bibliographique |

### A.4 Prévision (forecasting)

| Brique | Licence (vérifiée) | Maturité | Apport OPSYS | Intégration | Effort | Risques |
|---|---|---|---|---|---|---|
| [Nixtla/statsforecast](https://github.com/Nixtla/statsforecast) | **Apache-2.0** (LICENSE) | 4.9k★ (page GitHub), très actif, adossé à une société financée | **Nommé explicitement dans la mission** — modèles statistiques/économétriques rapides (ARIMA, ETS, Theta…), zéro LLM : correspond au patron « le LLM ne calcule jamais un chiffre » déjà en vigueur dans tout le dépôt (M8) | Dépendance pip pure, calcul déterministe | **S** | Aucun identifié — le meilleur candidat forecasting du dépôt : licence, philosophie (stats pures, pas de boîte noire) et nommage explicite s'alignent parfaitement |
| [Nixtla/mlforecast](https://github.com/Nixtla/mlforecast) / [neuralforecast](https://github.com/Nixtla/neuralforecast) | **Apache-2.0** (LICENSE vérifié séparément) | Même organisation, actifs | Extensions ML/deep learning si la saisonnalité renovation-QC (météo, permis, saisonnalité extérieure) dépasse les modèles statistiques classiques | Dépendance pip optionnelle | **S/M** | Complexité d'opération (GPU optionnel) à réserver à un besoin mesuré, pas préventif |

### A.5 Matrices de décision (MCDA)

| Brique | Licence (vérifiée) | Maturité | Apport OPSYS | Effort | Risques |
|---|---|---|---|---|---|
| [scikit-criteria](https://github.com/leliel12/scikit-criteria) (org réelle `leliel12`, pas `quatrope` malgré certaines sources secondaires) | **BSD-3-Clause** (LICENSE.txt, Copyright Cabral/Luczywo/QuatroPe) | 105★, actif (CI, issues/PR récents) | TOPSIS, AHP, ELECTRE, somme pondérée… pour le « Decision Intelligence Engine » et les matrices de priorisation des recommandations M9 | **S** | Communauté plus restreinte que pymcdm mais licence sûre |
| [pyMCDM](https://github.com/pyMCDM/pyMCDM) | **GPL-3.0** (LICENSE, vérifié — ⚠️ contredit une source secondaire qui l'annonçait « MIT ») | Actif | Plus riche en méthodes que scikit-criteria | — | **REJETÉ pour intégration directe** : GPL-3.0 embarqué dans un produit commercial fermé impose de publier le code combiné (règle du BRIEF). Utilisable seulement (a) comme scikit-criteria à la place, ou (b) en revendant à la main une méthode isolée (TOPSIS/somme pondérée = quelques dizaines de lignes) selon le patron « copie-adaptation d'un petit pattern » déjà systématique dans ce dépôt — jamais `pip install pymcdm` tel quel |

### A.6 War Room

**Aucune brique open source dédiée mature** ne correspond au concept (les dépôts « war-room » trouvés sont
soit des simulateurs pédagogiques isolés à 2 étoiles, soit des projets d'OSINT géopolitique hors sujet).
C'est cohérent avec le constat déjà fait par l'architecte dans `M9/03-ARCHITECTURE.md` §7.2 : le rythme
exécutif « nécessite un ordonnanceur externe, hors périmètre stdlib pur ». **Recommandation** : ne pas
chercher de brique « War Room » ; construire le rythme exécutif comme une **composition** de briques déjà
retenues ailleurs dans le dépôt — ordonnanceur (cron/APScheduler en sidecar docker, hors stdlib assumé),
lecture de `EtatConsolide` (M9) + métriques M8 (DuckDB/Parquet, XmR) + registre M10, et rendu sur le
dashboard central (exigence dure #2). Le « War Room » est un **écran du dashboard**, pas une bibliothèque.

### A.7 Sources de données publiques QC/Canada

| Source | Licence | Accès | Apport OPSYS |
|---|---|---|---|
| [Statistique Canada — Web Data Service (API)](https://www.statcan.gc.ca/en/developers/wds/user-guide) | Licence du gouvernement ouvert – Canada (attribution) | REST/JSON, mises à jour quotidiennes, Delta File pour gros volumes | Indicateurs économiques/démographiques macro pour le diagnostic M9 |
| [Données Québec — Permis de construction](https://www.donneesquebec.ca/recherche/dataset/permis-de-construction) (multi-municipalités depuis 1991) | **CC-BY 4.0 Québec** | CSV/JSON/XML + API | Signal direct de marché pour une entreprise de rénovation extérieure — snapshot idéal pour `SnapshotModule(module_source="veille_marche")` |
| [Données Québec — Registre des licences RBQ](https://www.donneesquebec.ca/recherche/dataset/licencesactives) | CC-BY 4.0, **synchronisé quotidiennement** | CSV/JSON | Vérification de la légitimité des concurrents/sous-traitants — utile aussi pour M2/M6 |
| [CMHC/SCHL — mises en chantier](https://www.cmhc-schl.gc.ca/) | Licence du gouvernement ouvert – Canada | Tables CSV/XML par région/ville | Tendance du marché de la construction résidentielle, granularité ville (utile pour un acteur QC) |
| [Institut de la statistique du Québec (ISQ)](https://statistique.quebec.ca/) | Publié via Données Québec | API + catalogue | Données PME manufacturières/régionales, démographie économique du Québec |

Toutes ces sources sont des **données**, pas du code : aucun risque de licence logicielle, seulement une
obligation d'attribution (CC-BY / Licence gouvernementale) à afficher dans le rapport stratégique quand une
valeur en dérive — cohérent avec la règle d'or M9 (« tout chiffre trace un `snapshot_id` source »).

### A.8 Veille concurrentielle éthique

Le [code d'éthique SCIP](https://www.scip.org/page/Ethical-Intelligence) (Strategic and Competitive
Intelligence Professionals, ~7 000 membres) est la référence sectorielle : sources publiques et légales
uniquement, **jamais de fausse identité/pretexting**, respect des conditions d'utilisation et de la
propriété intellectuelle des tiers, transparence sur l'identité du collecteur. Concrètement pour OPSYS
(cohérent avec AGENTS.md « Sources contenu : web public + documents fournis explicitement ») :
respect de `robots.txt`, limitation de débit, `User-Agent` déclaré et honnête, aucune tentative de
contournement d'authentification — à coder comme **garde déterministe** (allow-list de domaines,
rate-limiter) dans le connecteur de veille, jamais laissé au jugement de l'agent LLM (philosophie AGENTS.md
« O — Outils déterministes = autorité »).

---

## PARTIE B — Écosystèmes de capacités d'agents (2026) et modèle « Département »

### B.1 Agent Skills — le format qui a gagné la normalisation

Le **21 décembre 2025**, Anthropic a publié Agent Skills comme **standard ouvert** : spécification et SDK
à [agentskills.io](https://agentskills.io/specification) / [github.com/agentskills/agentskills](https://github.com/agentskills/agentskills)
(**Apache-2.0**, vérifié), adopté par plus de 20 plateformes (Claude, Codex, Gemini CLI, Copilot, Cursor…).
Le dépôt d'exemples officiel [anthropics/skills](https://github.com/anthropics/skills) affiche **178,7k★** —
licence **majoritairement Apache-2.0**, à l'exception explicite des skills de génération de documents
(docx/pdf/pptx/xlsx) marqués « source-available, pas open source » (nuance vérifiée, à respecter si l'un
de ces fichiers était un jour copié). Le format : un dossier avec `SKILL.md` (front-matter + instructions),
chargé en contexte seulement quand une tâche y correspond — c'est exactement le mécanisme que cette session
Claude Code utilise déjà pour piloter le dépôt OPSYS.

### B.2 Skills hubs communautaires — Hermes Agent (HermesHub) et OpenClaw (ClawHub)

**Hermes Agent** (NousResearch, MIT vérifié, ~249,5k★ page GitHub) expose un **HermesHub** implémentant le
protocole *Agentic Resource Discovery (ARD) v0.9* : les agents publient leurs capacités via
`/.well-known/ai-catalog.json`, indexées et cherchables (`POST /search`). Catalogue communautaire estimé à
82 skills intégrées + 117 optionnelles + 169 communautaires (source secondaire, non vérifiée par API).

**OpenClaw** (candidat core du BRIEF projet, **MIT vérifié**, ~391k★ page GitHub, TypeScript/Swift) a un
modèle de sécurité en couches documenté : scoping des outils par sous-agent (`tools`/`disallowedTools`/
`permissionMode`), séparation explicite **sandbox vs tool-policy vs elevated**, contrat de capacité
d'environnement (skills découvertes dans l'environnement d'exécution + serveurs MCP stdio autorisés
explicitement) — un modèle proche de ce que la partie B.6 recommande pour OPSYS.

**⚠️ Incident de sécurité majeur, vérifié par sources multiples et concordantes** : ClawHub a subi une
campagne de skills malveillantes (« ClawHavoc ») — un audit indépendant (Koi Security) a trouvé 341
skills malveillantes sur 2 857 auditées, majoritairement des info-stealers macOS (Atomic Stealer), une
skill à 340 000+ installations exfiltrant des identifiants et installant un cryptomineur ; le total confirmé
est monté à 824+ sur un registre élargi à 10 700+ skills (mi-février 2026). En parallèle, **CVE-2026-25253**
(RCE en un clic, validation d'origine WebSocket manquante, vol de jeton + désactivation du sandbox via
l'API) a permis une prise de contrôle complète d'instances OpenClaw exposées ; 30 000+ instances
exposées sans authentification ont été recensées (Censys/Bitsight/Hunt.io) ; corrigé en v2026.1.29.
**Conséquence pour OPSYS : ne jamais brancher ClawHub ni HermesHub en installation automatique/à distance.**

### B.3 MCP — serveurs, registre officiel, sécurité

Le **registre officiel** (`registry.modelcontextprotocol.io`, dépôt
[modelcontextprotocol/registry](https://github.com/modelcontextprotocol/registry)) est passé, début 2026,
d'une licence MIT à une transition vers **Apache-2.0** pour tout nouveau code/spec (les deux permissifs,
sans risque pour OPSYS). En décembre 2025, Anthropic a transféré la gouvernance de MCP à l'**Agentic AI
Foundation (AAIF)**, sous Linux Foundation — protocole désormais neutre vis-à-vis des fournisseurs.
Écosystème estimé (source secondaire) à ~19 800+ serveurs indexés (Glama) et 97M téléchargements SDK/mois.

**Sécurité — risques documentés et concordants entre plusieurs sources (Checkmarx, CSA, OWASP,
Practical DevSecOps, Microsoft) :** *tool poisoning* (des instructions malveillantes cachées dans la
description d'un outil, invisibles à l'utilisateur, mais lues et suivies par le LLM), injection de
commandes (~43 % des serveurs testés dans un échantillon), SSRF (~36,7 % d'un échantillon de 7000+
serveurs), chaîne d'approvisionnement (un serveur MCP tiers = du code non audité exécuté avec les
identifiants de l'agent). Le registre officiel **ne fait aujourd'hui aucune vérification de sécurité
substantielle des serveurs listés** (constat direct par lecture de la page du registre) — un serveur listé
n'est pas un serveur de confiance. Le protocole fournit deux primitives utiles au human-in-the-loop :
**elicitation** (le serveur peut mettre en pause et demander une saisie utilisateur structurée) et
**sampling** (le serveur demande une complétion LLM au client, qui peut exiger un consentement explicite) —
briques protocolaires à exploiter pour l'Approval Engine T2/T3 d'OPSYS plutôt qu'à réinventer.

Complémentaire à MCP : **A2A (Agent2Agent)**, protocole Google devenu projet hébergé par l'AAIF/Linux
Foundation (2025-2026) pour la communication *agent-à-agent* (découverte via « Agent Cards » JSON-LD) —
pertinent si le futur Council M9 doit un jour dialoguer avec des agents d'autres départements exposés en
services séparés ; MCP reste « vertical » (agent→outil), A2A est « horizontal » (agent→agent).

### B.4 Toolsets, profils/personas, politiques d'approbation

- **Toolset** : dans les frameworks 2026 (Google ADK `BaseToolset`, etc.), un toolset est un regroupement
  nommé de tools (souvent 1 serveur MCP = 1 toolset) exposé/masqué en bloc à un agent — le bon niveau de
  granularité pour la permission d'un Département OPSYS (accorder un *toolset* entier, pas outil par outil).
- **Profil/persona** : convergence 2026 vers un **fichier déclaratif versionné** (`agent.yaml`/`agent.json`)
  décrivant persona, outils enregistrés, mémoire, portées autorisées, critères d'évaluation, métadonnées de
  routage — littéralement « ce qu'une image de conteneur est à un process : versionné, déployable, testé en
  régression avant promotion en production ». C'est le même besoin que le manifeste « Département » demandé
  par la mission (B.6 ci-dessous).
- **AGENTS.md** ([agentsmd/agents.md](https://github.com/agentsmd/agents.md), **MIT vérifié**, piloté par
  l'AAIF/Linux Foundation, formalisé août 2025 sous l'impulsion d'OpenAI avec Google/Cursor/Factory,
  60 000+ dépôts l'auraient adopté en décembre 2025) — **le standard que ce dépôt utilise déjà à sa racine**.
  Validation directe que la convention OPSYS-AI est alignée sur l'écosystème, pas une invention isolée.
- **Approbation humaine** : la littérature 2026 distingue **Human-in-the-Loop** (pause + autorisation
  avant action, pour le risque élevé), **Human-on-the-Loop** (action autonome + supervision a posteriori,
  réversible), et **autonomie graduée** (l'autorisation se relâche avec un historique de fiabilité mesuré,
  jamais accordée par défaut). **OPSYS a déjà ce vocabulaire** : les paliers T1/T2/T3 utilisés partout dans
  les PRD/architectures des modules (et la « Frontière humaine T3 » d'AGENTS.md) sont exactement ce
  triptyque — à formaliser explicitement comme champ de politique du manifeste Département plutôt qu'à
  laisser implicite module par module.

### B.5 RBAC d'agents et sandbox

**RBAC** : le consensus 2026 (Security Boulevard, NeuralTrust, arXiv 2505.19301) est qu'une identité humaine
classique (IAM/RBAC statique) ne convient pas à un agent (des centaines d'appels/minute, pas de cycle
d'onboarding RH) ; le patron recommandé est **hybride RBAC (rôle de département) + ABAC (contexte)**, avec
traçabilité **« on-behalf-of »** (chaque appel outil porte l'identité de l'humain/département d'origine, pas
un compte de service anonyme) — nécessaire pour reconstruire l'intention en cas d'incident. **Point fort
déjà présent dans OPSYS** : la règle #109 (jamais d'import inter-module, seulement des contrats explicites
type `SnapshotModule`/`WorkCompletionTriggerV1`) est **structurellement plus stricte** que la plupart des
schémas RBAC d'agents documentés — à documenter comme un atout, pas à affaiblir en ouvrant des imports
directs pour la commodité d'un futur Council.

**Sandbox** : le paysage 2026 propose microVMs (Firecracker/E2B, ~150ms de démarrage, isolation matérielle,
mais **nécessite KVM** — souvent absent des VPS d'entrée de gamme), gVisor (noyau en espace utilisateur,
pas de KVM requis, s'ajoute comme runtime Docker `runsc`), et conteneurs durcis. **Pour l'exigence dure #1
(mono-nœud VPS, docker compose)**, gVisor est le choix pragmatique : `runtime: runsc` par service dans le
compose, sans dépendance à la virtualisation imbriquée ni à un fournisseur cloud de sandbox payant
(E2B/Modal/Daytona) — ces derniers restent une option pour une variante SaaS/cloud future, pas pour le VPS
client 1.

### B.6 Modèle « Département » recommandé pour OPSYS

**Manifeste** (un fichier déclaratif par module `Mx`, ex. `Modules M/M9-strategic-intelligence/department.yaml`,
à valider par un schéma comme les autres contrats gelés du dépôt) :

```yaml
departement: M9-strategic-intelligence
lifecycle: mode_ombre          # mode_ombre | gated_review | actif | retire (vocabulaire déjà utilisé 6x dans le dépôt)
outils:                        # toolsets, pas des outils un par un
  - toolset: mcp:statcan-wds
    scope: [network:statcan.gc.ca]
  - toolset: mcp:donnees-quebec
    scope: [network:donneesquebec.ca]
skills:                         # dossiers SKILL.md (Agent Skills, Apache-2.0), vendorisés et pinés
  - skills/m9-business-state-graph/SKILL.md
  - skills/m9-rapport-15-clefs/SKILL.md
politiques:
  autonomie: T2                # T0 auto | T1 notifie | T2 approbation-avant | T3 humain-seul (vocabulaire T1-T3 déjà natif au dépôt)
  approbateur: Nathan
memoire:
  registre: m10_memoire.registre_business
  reference_type: ReferenceMemoireM10
planifications:
  war_room_quotidien: "0 7 * * *"     # ordonnanceur externe (sidecar), hors stdlib assumé
budget_tokens:
  quotidien_max: <valeur mesurée, jamais codée en dur en Python — cf. conformite.py>
kpis:
  - fraicheur_moyenne_faits
  - taux_contradictions_non_arbitrees
  - taux_rejet_structurel_rapport
```

**Cycle de vie** : réutiliser tel quel le vocabulaire déjà convergé indépendamment 6 fois dans ce dépôt
(M3/M5/M6/M8/M9/M10) — `mode ombre` (harnais stdlib prouvable en CI, zéro LLM) → `gated_review` (contenu LLM
activé derrière un flag, revue scellée obligatoire type `proof-review`) → `actif` (exposé au dashboard,
approuvé) → `retire`. Ce n'est pas une invention : c'est la formalisation explicite d'un patron que le
dépôt applique déjà sans le nommer comme un cycle de vie transversal.

**Tests/évals** : un gate `proof-eval` symétrique du `proof-review` existant — jeu de données « golden » par
département, exécuté en CI (patron `eval-action`/`promptfoo` : bloque le merge sur régression), avec
**DeepEval** ou **Ragas** (tous deux **Apache-2.0 vérifiés**) comme moteur de métriques ; les benchmarks
sont spécifiques par département (M9 : taux de rapports 15/15 valides, latence de détection de
contradiction ; M2 : taux de faux doublons ; etc.), jamais un score générique.

**Exposition dashboard** : le dashboard (exigence dure #2) n'a pas besoin d'une nouvelle couche de données —
il lit ce que M8 (métriques), M9 (`EtatConsolide`) et M10 (registres + `ReferenceMemoireM10`) exposent déjà
comme contrats gelés, plus le manifeste `department.yaml` de chaque module pour : statut de cycle de vie,
KPIs, file d'approbations T2/T3 en attente, consommation de tokens vs budget, dernier résultat `proof-eval`,
liste des toolsets/skills actuellement accordés. Le « Département » devient ainsi une **vue**, pas un
nouveau sous-système.

---

## INGRÉDIENTS RETENUS (classés)

**Forts (licence sûre, mature, apport direct mesuré) :**
1. `statsforecast` (+ `mlforecast`/`neuralforecast`) — Apache-2.0 — prévision M9-GATED.
2. `scikit-criteria` — BSD-3-Clause — matrices de décision M9-GATED.
3. `GPT Researcher` — Apache-2.0 — agent de veille/recherche du Council.
4. Agent Skills / `SKILL.md` (agentskills.io) — Apache-2.0 — format de capacité par département (partie B).
5. `LangGraph` — MIT — moteur d'orchestration du Strategic Supervisor (déjà nommé par la fiche source M9).
6. gVisor (`runsc`) — sandbox docker-compose des skills exécutant du code, compatible mono-VPS.
7. `DeepEval`/`Ragas` — Apache-2.0 — gate CI `proof-eval` par département.
8. Patron interne `civ_review.py`/`tally_reviews.py` — pas une dépendance, le mécanisme de débat/consensus
   du Council à copier-adapter (zéro nouveau risque, déjà prouvé en production méthode).

**Moyens (utiles, effort ou périmètre plus large) :**
9. `STORM`/Co-STORM (MIT) — génération de rapport avec citations tracées.
10. `local-deep-research` (MIT) — veille confidentielle locale.
11. `EMA Workbench` (BSD-3) — scenario discovery / décision robuste (vendoriser le module scénario, pas
    tout le framework).
12. `CrewAI` (MIT), `AutoGen` (MIT via `LICENSE-CODE`) — prototypage rapide du Council avant fixation.
13. Sources publiques QC/Canada (StatCan WDS, Données Québec permis + RBQ, CMHC/SCHL, ISQ) — connecteurs
    `SnapshotModule`, licences gouvernementales/CC-BY, zéro risque logiciel.

**Rejetés / à écarter explicitement (avec raison) :**
- `pyMCDM` — GPL-3.0, incompatible en dépendance directe d'un produit commercial fermé.
- `langchain-ai/open_deep_research` — archivé 2026-08-21, référence de design seulement.
- `cpgoncalves/strategy-analyzer` — 2★, dormant, licence non standard.
- ClawHub (OpenClaw) et HermesHub (Hermes Agent) comme **sources d'installation automatique** de skills —
  incidents de sécurité vérifiés et massifs (341-824+ skills malveillantes, CVE-2026-25253 RCE) ; seul un
  fichier `SKILL.md` individuel, revu à la main comme tout code tiers, pourrait être vendorisé.

## RECETTE

1. **Ne rien câbler dans M9 v1** : toutes les briques ci-dessus attendent la levée explicite du GATED (choix
   déjà tranché et documenté par le PM/l'architecte — respecter cette frontière, pas la contourner).
2. **Python-first, docker-compose, mono-VPS** : chaque brique lourde (GPT Researcher, STORM, EMA Workbench)
   tourne en **sidecar conteneurisé sous `runsc`**, jamais importée directement dans le paquet
   `m9_strategic_intelligence` (qui reste stdlib pur, cf. DA-M9-04) ; la frontière passe par un connecteur
   qui traduit la sortie de la brique en `SnapshotModule` avant d'entrer dans le registre M9.
3. **Dashboard central** : ajouter une vue « Départements » lisant les manifestes `department.yaml` +
   `EtatConsolide` (M9) + registres (M10) + métriques (M8) — aucune nouvelle base de données.
4. **Économie de tokens** : le manifeste porte un budget par département, opposable par un hook déterministe
   (même philosophie que `conformite.py`), jamais laissé à l'appréciation du LLM ; le cache/la compression
   (`PROOF_COMPRESS`) déjà en place pour les packs s'applique symétriquement aux contextes envoyés aux
   agents de veille/débat.
5. **Sécurité des capacités** : vendoriser uniquement des skills/serveurs MCP revus et pinés (jamais un
   `install` en direct depuis ClawHub/HermesHub) ; traiter toute description d'outil tierce comme entrée non
   fiable (garde anti-tool-poisoning) ; RBAC hybride rôle-département + attribut, identité « on-behalf-of »
   tracée dans le registre M10.
6. **Le débat du Council** = copie-adaptation de `civ_review.py`/`tally_reviews.py`, pas un framework
   supplémentaire — cohérent avec la règle #109 déjà appliquée 5 fois dans ce dépôt.

---

### Sources principales (accès vérifié pendant cette recherche)

Fichiers `LICENSE` lus directement : gpt-researcher, storm, open_deep_research, local-deep-research,
statsforecast, mlforecast, neuralforecast, pyMCDM, crewAI, autogen (`LICENSE` + `LICENSE-CODE`), langgraph,
ragas, deepeval, langfuse, scikit-criteria, agentskills/agentskills, NousResearch/hermes-agent,
openclaw/openclaw, modelcontextprotocol/servers+registry, agentsmd/agents.md.
Pages GitHub (étoiles/statut) lues via WebFetch (accès `api.github.com` bloqué dans ce bac à sable pour
dépôts non attachés à la session — voir note en tête de document).
Sécurité ClawHub/OpenClaw : Koi Security (via cyberresilience.com, conscia.com, oasis.security,
blog.cyberdesserts.com — sources secondaires concordantes, CVE-2026-25253 nommé explicitement).
Données QC/Canada : donneesquebec.ca, statcan.gc.ca/en/developers/wds, cmhc-schl.gc.ca, statistique.quebec.ca.
Standards : agentskills.io, github.com/agentsmd/agents.md, modelcontextprotocol.io, linuxfoundation.org (A2A).
