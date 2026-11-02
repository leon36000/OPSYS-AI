# Veille open source : mémoire d'expérience des agents (apprendre des succès et des échecs, transférer d'un gros modèle vers un petit)

Statut : veille et évaluation d'architecture, **aucun code de production**. Date de consultation de toutes les sources : **2026-11-02**.
Ligne de base du dépôt : `e0424b040`. Auteur : agent de recherche pour l'architecte en chef. Données du relevé :
[`VEILLE-MEMOIRE-EXPERIENCE-2026-11/licences-verifiees.tsv`](VEILLE-MEMOIRE-EXPERIENCE-2026-11/licences-verifiees.tsv)
(générée par [`releve-depots.sh`](VEILLE-MEMOIRE-EXPERIENCE-2026-11/releve-depots.sh)). Proposition de conception qui en découle :
[`MEMOIRE-EXPERIENCE-AGENTS-PROPOSITION.md`](../architecture/MEMOIRE-EXPERIENCE-AGENTS-PROPOSITION.md).

**Niveaux de preuve utilisés partout dans ce document.**
**[L]** lu par moi dans le fichier source (code, licence, issue, tableau d'un article). **[R]** résumé ou abstract seulement lu (je n'ai pas lu le texte
complet). **[S]** source secondaire (page de l'éditeur, README, rapport interne du dépôt). **[D]** déduction de ma part, non vérifiée par une
exécution. Rien ici n'a été **exécuté** : aucun dépôt cloné n'a été installé ni lancé, aucun modèle n'a tourné.

---

## 0. Résumé (12 lignes)

1. **ReasoningBank** (Google Research, ICLR 2026) : bonne idée (extraire de courts « éléments de mémoire » titre/description/contenu depuis les réussites ET
   les échecs, en récupérer un seul au début de la tâche). Le dépôt (Apache-2.0) est un **code de démonstration** : ses propres auteurs l'écrivent, le
   dernier commit date du 2026-05-19, et **trois utilisateurs indépendants n'arrivent pas à reproduire les gains** (issues #2, #6, #11, toutes ouvertes).
   Verdict : **ADAPTER l'idée, IGNORER le code**. Le « MaTTS » (plusieurs essais de la même tâche) est **inutilisable en production** chez nous : nos tâches
   ont des effets de bord.
2. **Agent Memory Distillation (AMD)** (KAIST, août 2026) : l'idée la plus proche de notre besoin (mémoire en trois niveaux workflow / sous-tâche / fonction,
   construite par un gros modèle, lue par un petit, sans entraînement, injectée au début et **sur erreur d'outil**). Résultats forts sur trois bancs d'usage
   d'outils, mais : **article en relecture, version 1, aucune réplication trouvée, code sans licence** (donc inutilisable), gains **réduits de 3 à 8 points**
   quand on isole mémoire et évaluation, aucune échec utilisé (réussites de l'enseignant seulement), anglais seulement. Verdict : **ADAPTER l'architecture, SURVEILLER**.
3. **La littérature récente ajoute trois avertissements** : (a) beaucoup de systèmes de mémoire font **moins bien qu'un simple RAG** sur l'historique brut
   (« Memory Tax », [R]) ; (b) les bibliothèques de compétences écrites par un LLM valent **0 point** contre l'absence de compétences, et dérivent si on ne
   les borne pas (« Ratchet », [R]) ; (c) la mémoire d'expérience est une **surface d'attaque** persistante (une vingtaine d'articles de 2024 à 2026 trouvés, dont un
   visant OpenClaw et un le détournement d'outils par la mémoire, [R]).
4. **Ce qu'OPSYS-AI a déjà** : un cycle « proposition → mesure hors ligne → promotion humaine N3 → canari → retour arrière » (`opsys.mnemo`, M1, M9), des
   registres chaînés append-only, un gabarit d'évaluation commun, un registre MCP scellé par empreinte, un masquage des renseignements personnels, et des
   journaux de trace **sans contenu**. Ce qui manque : des **éléments d'expérience rédigés** (stratégie, exemple d'appel, piège d'outil), leur récupération au
   début de tâche et sur erreur, et la **mesure avec/sans mémoire** sur un petit modèle en français.
5. **Décision** : ne **rien adopter tel quel**. Construire en interne, sur les briques OPSYS existantes, une mémoire d'expérience **à schéma fermé, sans valeur,
   sans renseignement personnel**, alimentée d'abord par des trajectoires **fictives** (enseignant local ou réponses de référence écrites à la main), jugée par
   des **oracles déterministes** (jamais par un LLM seul), promue par une personne. **Pilote conditionnel** : le plugin local de MemOS (Apache-2.0) pour
   OpenClaw, en bac à sable fictif seulement. DSPy/GEPA restent **hors ligne** (décision r2 confirmée).

---

## 1. Ce qu'on cherche (contraintes OPSYS-AI qui filtrent tout)

Exécution locale d'abord (petits modèles sur GB10, données sensibles en local) ; SQLite et PostgreSQL portables ; 636 outils MCP exposés par un registre scellé ;
français (Québec) ; Loi 25 (aucun renseignement personnel dans une mémoire, effacement sur demande) ; « le code calcule, le LLM orchestre » (une mémoire peut
enseigner une **stratégie** ou une **convention d'appel**, jamais une **valeur**) ; promotion d'une leçon en règle = **approbation humaine** ; modes
ombre/supervisé/autonome ; retour arrière ; traçabilité de la provenance de chaque élément ; **aucun coût supplémentaire sans l'accord de Nathan** (donc
enseignant = modèle local fort ou trajectoires existantes, pas de crédits). Licences : MIT/Apache/BSD seulement pour du code intégré ; GPL/AGPL seulement en
service séparé non modifié ; BSL/Elastic/SSPL refusées (`AGENTS.md`, « Briques open source »).

## 2. Méthode suivie et limites de cette veille

- Recherche : GitHub (API officielle `gh`, lecture seule) pour chaque dépôt : commit de tête, étoiles, issues, présence de tests, **fichier `LICENSE` lu en entier**
  (empreinte SHA-256 dans le TSV) ; arXiv (pages `abs` et HTML complet pour ReasoningBank et AMD, abstracts pour le reste) ; outils de recherche web du poste.
- J'ai **cloné en lecture seule** (profondeur 1, hors du dépôt) les dépôts de ReasoningBank et d'AMD pour lire leur code. **Rien n'a été installé ni exécuté.**
- **Lu en entier** : l'article AMD (HTML v1), l'article ReasoningBank (HTML v2, sections 3 à 5 et annexes A à E), le code de récupération, d'induction et de jugement du
  dépôt ReasoningBank, le modèle de données et les scripts du dépôt AMD, les issues #2, #6, #11, #14, #17, #36, #40 de ReasoningBank. **Abstract seulement** : AWM, Reflexion,
  Voyager, ExpeL, A-MEM, SkillWeaver, Dynamic Cheatsheet, GEPA, Memp, ainsi que tous les articles de risque cités au § 6. **Résumé produit par l'outil de recherche** (donc [S]) :
  les chiffres d'ACE du § 3 (requête de synthèse sur la page HTML de l'article).
- Les chiffres de performance des projets de mémoire (Mem0, Hindsight, MemOS, Zep…) sont **déclarés par leurs éditeurs** : je les rapporte comme tels, sans les
  reprendre comme preuve. Le rapport de recherche R6 de la feuille de route note déjà un désaccord Mem0 (49 % mesuré par un tiers contre 93 % annoncé, [S] de R6 que je n'ai pas revérifié).
- **Non couvert** : mesure sur le français, sur nos outils MCP, sur nos modèles locaux (voir § 9). Les relevés d'étoiles et de dates sont ceux du 2026-11-02.
- Les outils web du poste (Firecrawl) consomment des crédits du compte configuré (une vingtaine d'appels) ; je n'ai rien acheté ni souscrit.

---

## 3. Tableau comparatif

Légende des verdicts : **ADOPTER** (on l'utilise tel quel, après qualification) ; **ADAPTER** (idée seulement : on réimplémente chez nous, sans dépendance) ;
**SURVEILLER** (rien à faire maintenant, conditions de réexamen indiquées) ; **IGNORER** (pas pour nous, raison dite). « Licence lue » = fichier `LICENSE` de la racine
lu en entier le 2026-11-02 (le champ `license` de l'API et la bannière du README ne font pas foi). « Tests » = fichiers de test détectés dans l'arbre git par motif de nom.

### 3.1 Les deux candidats nommés par Nathan

| Projet | Lien | Licence lue | Maturité | Ce que ça fait | Ce que ça prouve réellement | Coût et risque d'intégration | Verdict |
|---|---|---|---|---|---|---|---|
| **ReasoningBank** (Ouyang et al., Google Research ; ICLR 2026 ; arXiv 2509.25140 v2) | [github.com/google-research/reasoning-bank](https://github.com/google-research/reasoning-bank) | **Apache-2.0** (11 357 o) pour le code ; pas de licence séparée pour des données (le dépôt ne livre pas de banque de mémoire ; les tâches WebArena viennent d'ailleurs). Code « vendorisé » (`third_party/`) sans fichier de licence amont [L] | 632 ★, commit de tête `ed80611` du **2026-05-19** (« Update BibTeX »), **aucun test** du projet, 33 issues/PR ouverts dont 3 de reproduction, aucun des 50 PR les plus récents fusionné. README : « démonstration seulement, pas de production » [L] | Extrait ≤ 3 éléments (titre, description, contenu) par trajectoire, **réussie ou échouée** (juge LLM), les stocke avec l'embedding de la requête, récupère **l'élément de la tâche la plus proche (k=1)** au début de la tâche. « MaTTS » : N essais parallèles ou séquentiels de la même tâche pour enrichir la mémoire | Sur WebArena (684 tâches) : +8,3 / +7,2 / +4,6 points de taux de réussite pour Gemini-2.5-flash/pro et Claude-3.7 contre « sans mémoire » ; SWE-Bench-Verified : +4,6 et +3,4 points [L, article]. **Mais** : trois utilisateurs ne reproduisent pas ([L] issues), juge LLM exact à 72,7 % seulement [L], un seul passage par condition, gains non accompagnés d'intervalles | **Élevé** : Python ≥ 3.13, BrowserGym 0.14.1, torch, LangChain, Vertex AI (plongements `gemini-embedding-001` ou Qwen3-Embedding-8B), harnais WebArena à héberger ; rien de MCP ni de français. MaTTS = N× le coût d'inférence et **N exécutions de la même tâche** | **ADAPTER l'idée** ; **IGNORER le code** ; MaTTS : IGNORER en production, ADAPTER hors ligne sur scénarios fictifs |
| **Agent Memory Distillation (AMD)** (Kim, Kim, Hwang ; KAIST/DeepAuto.ai ; arXiv 2608.07169 v1 du 2026-08-07, CC BY 4.0, « Under review ») | [arxiv.org/abs/2608.07169](https://arxiv.org/abs/2608.07169) · [page](https://agent-memory-distillation.github.io/) · [github.com/taeilkim2465/agentic_memory_distillation](https://github.com/taeilkim2465/agentic_memory_distillation) | **Aucune licence** : l'API GitHub rend `null`, aucun fichier `LICENSE` ; donc **tous droits réservés par défaut** [L]. L'article est CC BY 4.0 (le texte, pas le code) | 9 ★, 3 forks, 0 issue, commit de tête `2895d10` du 2026-08-10, **aucun test**, ~26 000 lignes de Python en surcouche de trois autres dépôts (AppWorld, BFCL, ToolSandbox) [L] | Trois mémoires construites **par un enseignant** (GPT-5-mini) à partir de **ses seules réussites** : *Workflow* (stratégie en prose avec marques de substitution typées), *Sous-tâche* (segments d'exécution concrets : appels et observations), *Fonction* (appel réel + doc, indexé par nom d'outil). Workflow et sous-tâche **injectés au début** ; fonction **récupérée seulement après une erreur d'outil**. Récupération par similarité, k=1, seuil minimal | Étudiants 4B-8B (Qwen3-4B/8B, Gemma4-E4B, Llama3.1-8B), gain moyen +27,2 / +11,2 / +3,4 points sur AppWorld / BFCL V3 / ToolSandbox ; Qwen3-4B passe de 14,88 à 49,40 sur AppWorld (enseignant : 50,00). Ablation : **la sous-tâche porte l'essentiel**. **Évaluation « disjointe » : 41,07 (AppWorld), 30,65 (BFCL), 22,92 (ToolSandbox)** contre 49,40 / 38,50 / 20,16 en configuration principale, pour Qwen3-4B [L, annexe B.3] | **Faible pour l'idée** (peu de code, tout est de la prose et des index) ; **inutilisable pour le code** (aucune licence). Dépend d'un enseignant fort (ici un modèle sous contrat commercial), d'un petit modèle qui décompose lui-même la tâche, et d'un modèle d'embeddings (ici OpenAI) | **ADAPTER l'architecture** (trois niveaux, injection proactive + réactive sur erreur, k=1, prose pour le plan / exemple concret pour l'exécution) ; **IGNORER le code** ; **SURVEILLER** (version relue, réplications, licence) |

### 3.2 Voisins académiques (idées et petits dépôts de recherche)

| Projet | Lien | Licence lue | Maturité | Ce que ça fait | Ce que ça prouve réellement | Coût et risque | Verdict |
|---|---|---|---|---|---|---|---|
| **Agent Workflow Memory (AWM)** (Wang, Mao, Fried, Neubig ; 2409.07429) | [zorazrw/agent-workflow-memory](https://github.com/zorazrw/agent-workflow-memory) | Apache-2.0 | 480 ★, dernier commit 2025-12-22 (faute de frappe), 0 test | Induit des « workflows » réutilisables depuis des réussites (hors ligne ou en ligne) et les injecte | +24,6 % et +51,1 % de réussite relative sur Mind2Web et WebArena [R, abstract] ; dans le tableau de ReasoningBank, AWM n'apporte parfois rien ou nuit (Claude-3.7 : 41,7 → 40,8) [L] | Code lié au web (BrowserGym) ; inutile pour nos outils MCP | **ADAPTER** (idée « workflow de ≥ 2 étapes avec variables nommées ») ; code IGNORER |
| **Reflexion** (Shinn et al. ; 2303.11366) | [noahshinn/reflexion](https://github.com/noahshinn/reflexion) | MIT | 3 388 ★, dernier commit 2025-01-14, 1 fichier de test | Réflexion verbale après un échec, gardée dans un tampon épisodique pour l'essai suivant | 91 % pass@1 sur HumanEval [R] ; suppose un **signal de feedback fiable** (tests unitaires) | Faible, mais dépôt gelé | **ADAPTER** (c'est déjà le principe de nos leçons) ; code IGNORER |
| **Voyager** (Wang et al. ; 2305.16291) | [MineDojo/Voyager](https://github.com/MineDojo/Voyager) | MIT | 7 308 ★, **dernier commit 2023-07-27**, 0 test | Bibliothèque de compétences = **code exécutable vérifié par l'environnement**, indexée par description | 3,3× plus d'objets, 15,3× plus vite dans Minecraft [R] | Domaine sans rapport ; gelé | **ADAPTER** (idée : une compétence n'entre qu'après **vérification déterministe**) ; code IGNORER |
| **ExpeL** (Zhao et al. ; 2308.10144) | [LeapLabTHU/ExpeL](https://github.com/LeapLabTHU/ExpeL) | Apache-2.0 | 250 ★, dernier commit 2024-12-20, 0 test | Extrait des « insights » en langage naturel d'un ensemble de tâches d'entraînement ; ajouter/éditer/voter | Gains qui augmentent avec l'expérience accumulée [R] | Gelé | **ADAPTER** (votes utile/nuisible, voir ACE) ; code IGNORER |
| **ACE, Agentic Context Engineering** (2510.04618) | [ace-agent/ace](https://github.com/ace-agent/ace) (+ [ace-appworld](https://github.com/ace-agent/ace-appworld)) | `LICENSE.txt` : Apache-2.0 (11 357 o) | 1 418 ★, commit de tête `82709de` du 2026-08-24, **0 test**, 24 issues/PR dont « le playbook dépasse 100 000 jetons » (#11) et « pas d'opérations MISE À JOUR/FUSION/SUPPRESSION du curateur » (#26) | Un « playbook » de puces avec **compteurs utile/nuisible**, mis à jour par **deltas** (jamais réécrit en bloc), fusion et élagage déterministes, budget de jetons | Sur AppWorld (DeepSeek-V3.1) : 59,4 contre 42,4 (base) et 46,4 (GEPA) avec étiquettes ; 57,2 sans étiquettes ; **sans signal fiable le contexte peut être pollué** [S, synthèse d'outil sur la page HTML] | Moyen : code de recherche sans tests ; mais la **mécanique de compteurs et de deltas est simple à réécrire** | **ADAPTER** (compteurs, deltas, budget ; les compteurs viendront de signaux déterministes, pas d'un « réflecteur » LLM) |
| **Dynamic Cheatsheet** (2504.07952) | [suzgunmirac/dynamic-cheatsheet](https://github.com/suzgunmirac/dynamic-cheatsheet) | MIT | 279 ★, commit 2026-03-12, 0 test | Mémoire évolutive de stratégies/extraits de code, sans étiquette ni retour humain | Claude 3.5 : précision « plus que doublée » sur AIME ; GPT-4o 10 % → 99 % à Game of 24 en réutilisant un script [R] | Gains sur des tâches **à réponse vérifiable** ; pas d'outils métier | **SURVEILLER** |
| **Memp** (2508.06433) | [zjunlp/MemP](https://github.com/zjunlp/MemP) | MIT | 41 ★, commit 2026-01-30, 0 test | Mémoire procédurale (étapes fines + scripts abstraits) avec construction, récupération et **mise à jour/dépréciation** ; transfert d'un fort vers un faible | Gains sur TravelPlanner/ALFWorld ; la mémoire d'un modèle fort aide un modèle faible [R] | Petit dépôt de recherche | **ADAPTER** (cycle construire/récupérer/déprécier) ; code IGNORER |
| **SkillWeaver** (2504.07079) | [OSU-NLP-Group/SkillWeaver](https://github.com/OSU-NLP-Group/SkillWeaver) | MIT | 162 ★, dernier commit 2025-04-14 | Des compétences synthétisées sous forme d'**API** ; compétences d'un agent fort qui aident un agent faible (jusqu'à +54,3 % sur WebArena [R]) | Web seulement | Gelé | **ADAPTER** (transfert fort → faible par « API » = appel d'outil documenté) |
| **A-MEM** (2502.12110) | [WujiangXu/A-mem](https://github.com/WujiangXu/A-mem) · [agiresearch/A-mem](https://github.com/agiresearch/A-mem) | MIT (les deux) | 1 010 et 1 212 ★ ; commits 2026-10-28 / 2025-12-12 ; peu de tests (2 et 5) | Notes liées façon Zettelkasten ; **les anciennes notes sont réécrites** quand de nouvelles arrivent | Mémoire conversationnelle (LoCoMo) [R] | Réécriture des anciens souvenirs = **contraire à notre registre append-only** | **IGNORER** pour l'expérience (graphe déjà couvert par M10) |
| **ContraMem**, **Artifact Distillation**, **PLVR** (2608.22533, 2610.37680, 2610.19148) | arXiv seulement (aucun dépôt trouvé) | n/a | Articles d'août à octobre 2026 [R] | Mémoire procédurale à partir de **variations d'issue d'une même tâche** (cartes de fonction et de compétence) ; banque d'artefacts de l'enseignant ; **compilation des procédures de l'enseignant en programme vérifié** devant un petit modèle | Résultats annoncés forts sur des bancs d'agents [R] ; aucun code vérifiable | n/a | **SURVEILLER** (PLVR rejoint « le code calcule » ; réexaminer si un dépôt licencié paraît) |

### 3.3 Systèmes de mémoire (services ou bibliothèques)

| Projet | Lien | Licence lue | Maturité | Ce que ça fait | Ce que ça prouve réellement | Coût et risque | Verdict |
|---|---|---|---|---|---|---|---|
| **Mem0** | [mem0ai/mem0](https://github.com/mem0ai/mem0) | Apache-2.0 (+ licences Apache dans des sous-dossiers `integrations/`, `skills/`) | 68 260 ★, commit 2026-10-30, 898 issues ouvertes, 306 fichiers de test | Extraction de faits (ajouter/mettre à jour/supprimer), mémoire par utilisateur/agent | Scores LongMemEval **annoncés par l'éditeur** ; contestés par un tiers [S, R6] | Mémoire de **faits sur des personnes**, pas d'expérience d'outil ; faits personnels = Loi 25 | **SURVEILLER** (déjà « Phase 2 » dans INGREDIENTS ; inchangé) |
| **Letta** (ex-MemGPT) | [letta-ai/letta](https://github.com/letta-ai/letta) → [letta-ai/letta-code](https://github.com/letta-ai/letta-code) | Apache-2.0 | **Le serveur V1 est archivé** (branche `archive`, dernier commit 2026-08-14) ; le dépôt `letta` ne contient plus que de la documentation ; le code actif est `letta-code` (Node/Bun, 3 758 ★, v0.34.37, 1 107 fichiers de test) | Agents à mémoire auto-éditée, mémoire en fichiers | Vitrine produit | Doublon avec le Core ; **la fiche INGREDIENTS (« Référence ») doit être corrigée** | **IGNORER** comme runtime ; patron déjà en Référence |
| **Graphiti / Zep** | [getzep/graphiti](https://github.com/getzep/graphiti) · [getzep/zep](https://github.com/getzep/zep) | Apache-2.0 (les deux) | Graphiti : 32 424 ★, v0.31.2 (2026-10-20), 83 fichiers de test, 538 issues ; Zep : 4 985 ★, 168 tests | Graphe temporel de faits (validité) ; base graphe externe (Neo4j, FalkorDB…) | Annonces de l'éditeur | Autre problème (faits datés), pilote déjà prévu par la feuille de route (E5) | **SURVEILLER** (pilote E5, pas la mémoire d'expérience) |
| **Cognee** | [topoteretes/cognee](https://github.com/topoteretes/cognee) | Apache-2.0 | 32 995 ★, v1.6.6 (2026-10-29), 1 075 issues, 1 284 fichiers de test | Graphe de connaissances depuis des documents | — | Décision r2 : « pas comme socle » | **IGNORER** (décision existante) |
| **LangMem** | [langchain-ai/langmem](https://github.com/langchain-ai/langmem) | MIT | 1 743 ★, commit 2026-10-30, 8 tests, 81 issues | Outils de mémoire « dans le chemin chaud », gestionnaire d'arrière-plan, optimisation de prompts ; couplé au magasin LangGraph | — | Couplage LangGraph ; recoupe DSPy/GEPA | **IGNORER** |
| **MemOS** (MemTensor) et son **plugin local** pour OpenClaw/Hermes | [MemTensor/MemOS](https://github.com/MemTensor/MemOS) · `apps/memos-local-plugin` | Apache-2.0 (racine) ; sous-dossiers `apps/…` avec leur propre Apache-2.0 et un MIT (Accomplish) | 12 225 ★, v2.0.34, commit 2026-10-29, 394 fichiers de test, 151 issues. Plugin local : SQLite local, recherche FTS5 + vecteurs, couches L1 trace / L2 politique / L3 modèle du monde / compétences « cristallisées », **adaptateur OpenClaw** (testé contre 2026.9.x selon sa doc) [S, README et ARCHITECTURE lus] | Récompense propagée le long des traces par réflexion LLM + retours humains | Chiffres annoncés par l'éditeur (OpenClaw : 36,63 % → 50,87 % sur cinq tâches d'agent) [S] | Node ≥ 22, stocke **action + observation** (renseignements personnels), récompense par LLM ; compatibilité avec **notre fork** du Core non testée | **SURVEILLER fort / PILOTE CONDITIONNEL** en bac à sable fictif (§ 8) |
| **Hindsight** (Vectorize) | [vectorize-io/hindsight](https://github.com/vectorize-io/hindsight) | MIT (+ MIT dans `hindsight-integrations/*`) | 57 814 ★, v1.1.0 (2026-10-21), commit 2026-10-30, 1 189 fichiers de test, 178 issues | Mémoire à quatre types (faits, expériences, observations avec preuves comptées, modèles mentaux), PostgreSQL, 25 fournisseurs de LLM dont locaux | Premier sur LongMemEval **selon l'éditeur**, « reproduit » par des collaborateurs nommés [S] | Mémoire conversationnelle ; dépôt de 830 Mo ; LLM à chaque écriture | **SURVEILLER** (idée « observation = croyance + preuves comptées » déjà proche de notre modèle de soi) |
| **TencentDB Agent Memory** | [TencentCloud/TencentDB-Agent-Memory](https://github.com/TencentCloud/TencentDB-Agent-Memory) | MIT (texte propre à Tencent, MIT intégral lu) ; l'API rend `NOASSERTION` | 30 342 ★, v2.0.3 (2026-10-26), créé en avril 2026, **889 issues**, 3 fichiers de test détectés | Mémoire de conversation, **bibliothèque de compétences** extraites des tâches, wiki, graphe de code ; plugin pour OpenClaw/Hermes ; « Team Memory Beta » | Aucune mesure indépendante lue | Jeune, très changeant, Node ≥ 22.16, passage par un mandataire de LLM | **SURVEILLER** |
| **OpenViking** (Volcengine) | [volcengine/OpenViking](https://github.com/volcengine/OpenViking) | **AGPL-3.0** (34 568 o) | 41 328 ★, v0.5.2.1 | « Base de contexte » pour agents | — | AGPL : service séparé non modifié seulement ; aucun besoin | **IGNORER** (à inscrire dans « Refusées ») |
| **Hermes Agent** (Nous Research) | [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) | MIT | 259 581 ★, v0.22.5, commit 2026-11-02, ~9 970 fichiers de test, 52 261 issues/PR | « Curateur » de compétences : transitions d'état par inactivité, **archive, ne supprime jamais**, compétences épinglées intouchables, consolidation par LLM **désactivée par défaut** ; interface `MemoryProvider` | Code lu : docstring de `agent/curator.py` et `agent/memory_provider.py` [L] | Volume énorme ; déjà « Référence » (directives de Nathan) | **ADAPTER les invariants du curateur** (jamais supprimer, épingler, LLM optionnel) ; code : réutilisable (MIT) après audit ciblé |

### 3.4 Optimisation hors ligne et bancs de mesure

| Projet | Lien | Licence lue | Maturité | Rôle | Verdict |
|---|---|---|---|---|---|
| **DSPy** | [stanfordnlp/dspy](https://github.com/stanfordnlp/dspy) | MIT | 38 881 ★, 3.4.1 (2026-10-12), 186 fichiers de test | Programmes LLM déclaratifs et optimiseurs | **ADOPTER hors ligne** (décision r2 / E6 ; non installé ici) |
| **GEPA** | [gepa-ai/gepa](https://github.com/gepa-ai/gepa) | MIT (texte MIT sans titre, lu) | 7 238 ★, v0.1.4 (2026-07-15), 81 fichiers de test | Évolution réflexive de prompts à partir de raisons textuelles ; annonce 6 % de mieux que GRPO avec 35× moins d'essais [R] | **ADOPTER hors ligne**, après mesure sur nos corpus (E6) ; **ne remplace pas** la mémoire d'expérience (il optimise le prompt, pas une bibliothèque d'items) |
| **AppWorld**, **BFCL**, **τ²-bench**, **ToolSandbox** | [StonyBrookNLP/appworld](https://github.com/StonyBrookNLP/appworld), [ShishirPatil/gorilla](https://github.com/ShishirPatil/gorilla), [sierra-research/tau2-bench](https://github.com/sierra-research/tau2-bench), [apple/ToolSandbox](https://github.com/apple/ToolSandbox) | Apache-2.0 ; Apache-2.0 ; MIT ; **licence propre d'Apple** (non OSI) | Actifs (2026-09 à 2026-10) | Bancs d'usage d'outils **en anglais** | **SURVEILLER** : utiles comme **contrôle de santé de notre banc** (rejouer un petit modèle avec/sans mémoire), jamais comme mesure du produit ; ToolSandbox : licence à lire avant tout usage |

Autres dépôts de mémoire pour **agents de code** vus dans les recherches (par exemple `tigerless-labs/agent-memory`, `vshulcz/deja-vu`, `AVIDS2/memorix`) : jeunes,
non qualifiés, hors périmètre (domaine développement) : **non évalués**.
Dépôt communautaire `Lanerra/reasoning-bank-slm` : expérience de 107 ★ sur un modèle de 1,7 Md de paramètres (mathématiques), README annonçant « MIT » mais **aucun fichier
`LICENSE`** dans l'arbre (la bannière ne fait pas foi) ; il rapporte +8 points **non significatifs** (16 améliorations, 8 régressions) [L, README] : un bon exemple de ce qu'on doit
mesurer (régressions comprises).

---

## 4. ReasoningBank : analyse à fond

**Ce que dit l'article** [L]. Une trajectoire (réussie ou échouée selon un **juge LLM**) est distillée en au plus trois éléments {titre, description, contenu}. Avant chaque tâche,
l'agent embarque dans son prompt les éléments de la **tâche passée la plus proche** (k=1 par défaut). Les nouveaux éléments sont **simplement ajoutés** (« consolidation minimale », sans élagage).
MaTTS exécute k essais de la même tâche (en parallèle ou en séquence) et utilise leur **contraste** pour extraire de meilleurs éléments ; le choix du meilleur essai est lui aussi fait par un LLM.
Résultats : WebArena 684 tâches, 3 modèles, +4,6 à +8,3 points ; Mind2Web : gains faibles en valeur absolue (taux de tâche réussie de 1,6 à 5,1 % selon le réglage) ; SWE-Bench-Verified +4,6 / +3,4 points ; sur Gemma-3-12B
(sous-ensemble Shopping seulement) 17,1 → 24,1 %. Coût mesuré : +4,3 % de jetons au total sans MaTTS (49 306 jetons d'action + 2 186 de juge + 1 562 d'extraction par tâche). Plus d'éléments récupérés **dégrade**
(49,7 % à k=1, 46,0 à 2, 45,5 à 3, 44,4 à 4). La robustesse au juge est simulée en retournant des étiquettes au hasard, pas mesurée avec un vrai juge plus faible.

**Ce que contient réellement le dépôt** [L, clone en lecture seule]. Deux dossiers : `WebArena/` (agent BrowserGym, juge `autoeval`, scripts d'induction `induce_memory.py`, `induce_scaling.py`, `pipeline_memory.py`) et `SWE-Bench/`
(surcouche de mini-swe-agent). Les prompts d'extraction (réussite, échec, contraste parallèle, version « AWM ») sont dans `WebArena/prompts/memory_instruction.py`. La récupération (`memory_management.py`) calcule un
plongement de la requête (Vertex AI `gemini-embedding-001` à 3 072 dimensions, ou Qwen3-Embedding-8B en local), le compare au cache des requêtes passées et rend l'entrée de **la tâche** la plus proche (`select_memory(n=1, …)`).
Chaque entrée stocke **la requête, la trajectoire brute (pensées et actions) et les éléments** : le magasin contient donc du contenu brut. Les scripts d'exécution (`run.sh`) contiennent des chemins et un projet
cloud personnels de l'auteur. Le README écrit que le projet est « à des fins de démonstration, pas pour la production » et qu'il n'est pas un produit Google supporté.

**Reproductibilité : le point le plus important de la veille.** Trois issues **ouvertes** de tiers, la dernière du 2026-07 :
- **#2** (2026-03-27, 16 commentaires) : 36-37 % obtenus pour Gemini-2.5-Flash sur Shopping contre 49 % annoncés. Un mainteneur reconnaît des problèmes dans le code, publie une mise à jour le 2026-04-25 (harnais WebArena corrigé, pipeline consolidé) ; la question de savoir si les chiffres de l'article venaient du harnais modifié **reste sans réponse** dans l'issue.
- **#6** (2026-05-10) : avec la récompense de référence de WebArena, ReasoningBank donne **42,2 → 42,8 %** (+0,6 point) ; sont absents du dépôt le MaTTS séquentiel, le sélecteur « meilleur essai » par LLM, les étiquettes succès/échec dans le prompt parallèle.
- **#11** (2026-06-01) : cinq essais sans mémoire donnent **50,05 %** (plus que les 39,0 % de l'article) et deux essais ReasoningBank **45,99 %**, c'est-à-dire que la mémoire fait **moins bien**.
- **#17, #36, #37, #40** (PR et issues de tiers, ouverts) : le code ne **retire pas la tâche courante** des candidats de récupération et ajoute l'embedding courant au cache partagé : risque de « contamination par auto-récupération ». L'auteur de #17 précise que ce n'est **pas** une preuve de contamination des résultats publiés.

Ces rapports viennent d'utilisateurs, **je ne les ai pas rejoués**. Ils suffisent à écrire : *les gains annoncés ne sont pas établis pour un tiers au 2026-11-02*. Cela n'invalide pas l'idée ; cela interdit de s'appuyer sur ses chiffres pour planifier.

**Forces transférables.** (1) Apprendre des **échecs** comme contre-exemples (ablation de l'article : sur Shopping 46,5 % avec les seuls succès, 49,7 % avec les échecs ; les mémoires qui n'utilisent que les succès, Synapse et AWM, ne tirent rien des échecs). (2) Format minimal et lisible {titre, description « quand l'utiliser ou non », contenu de 1 à 3 phrases}, avec la consigne d'**écarter les noms de produits et chaînes littérales** de la tâche. (3) **k=1** : la mémoire est courte. (4) Coût de jetons faible hors MaTTS.

**Limites et hypothèses non prouvées pour nous.**
1. **Aucune preuve en français ni sur des outils MCP.** WebArena est du clic web en anglais ; nos tâches sont des appels d'outils JSON gouvernés (approbation N0-N5, refus typés `REJ-…`). [D]
2. **Le juge LLM** : exact à 72,7 % sur Shopping avec Gemini-2.5-flash [L] ; des travaux récents montrent que les verdicts de juge changent entre répétitions identiques à température 0 [R, 2610.12083]. Nos garde-fous interdisent de s'appuyer sur un LLM pour décider d'une promotion (principe 2 et § 9.4 de la proposition de conception).
3. **Le magasin contient des trajectoires brutes** : incompatible avec « aucun renseignement personnel dans une mémoire » tant qu'on ne les remplace pas par des éléments à schéma fermé. [D]
4. **MaTTS exige N exécutions de la même tâche** : acceptable pour naviguer sur des pages de test, **inacceptable** dans une instance qui envoie des courriels, crée des factures ou écrit au grand livre (même en brouillon, les écritures N2 sont des effets). Utilisable seulement dans l'instance fictive d'évaluation. [D]
5. **Pas de gouvernance** : pas d'approbation humaine, pas de canari, pas de retour arrière, pas de fraîcheur, pas de lien avec la version de l'outil. Ce sont précisément nos exigences.
6. **Petits modèles** : une seule mesure (Gemma-3-12B, un sous-ensemble) ; l'expérience communautaire à 1,7 Md n'est pas significative. Rien ne dit qu'un modèle de 4 à 8 Md utilise un élément récupéré. [D]

**Coût en jetons.** Mesuré par les auteurs : +4,3 % sans MaTTS ; avec MaTTS (k=5) les essais sont multipliés par ~5 [D à partir du principe]. Nos budgets : l'élément injecté est borné en caractères (paquet de contexte M10 : 4 000 caractères de faits partagés en quatre couches).

**Verdict ReasoningBank.** ADAPTER l'idée (éléments courts depuis succès **et** échecs, k=1, contraste) ; ne pas dépendre du dépôt ; ne pas retenir MaTTS en production. Inscription INGREDIENTS : **Référence**, pas Intégré.

---

## 5. Agent Memory Distillation : analyse à fond

**Ce que l'article démontre** [L, HTML complet]. Quatre étudiants (Qwen3-4B, Qwen3-8B, Gemma4-E4B, Llama3.1-8B), un enseignant (GPT-5-mini), trois bancs (AppWorld test_normal, 168 tâches ; BFCL V3 multi-tours base, 200 tâches ; ToolSandbox base, 129 scénarios).
Zéro-coup vs AMD, accuracy % :

| Étudiant | AppWorld | BFCL V3 | ToolSandbox |
|---|---|---|---|
| Enseignant GPT-5-mini | 50,00 | 36,50 | 28,68 |
| Qwen3-4B : sans / avec AMD | 14,88 / **49,40** | 15,50 / **38,50** | 16,28 / **20,16** |
| Gemma4-E4B | 24,40 / 54,17 | 37,25 / 46,00 | 18,22 / 21,71 |
| Qwen3-8B | 25,60 / 51,79 | 38,00 / 45,50 | 20,16 / 25,58 |
| Llama3.1-8B | 8,93 / 27,38 | 9,00 / 14,50 | 5,43 / 6,20 |

Les mémoires concurrentes adaptées (ReasoningBank, MemP, SASM) font parfois **moins bien que le zéro-coup** pour le petit modèle (ReasoningBank sur Qwen3-4B / AppWorld : 14,88 → 10,71). Ablation : le **niveau sous-tâche** (exemples d'exécution concrets) ajoute le plus (+25,0 points sur AppWorld pour Qwen3-4B) ;
la mémoire *fonction* ajoute peu au-dessus de workflow + sous-tâche (+0,6 à +2,4 points sur AppWorld, −3,0 pour Llama3.1-8B). **Prose pour le plan, code pour l'exécution** : remplacer le code des sous-tâches par de la prose fait tomber 49,40 → 23,21. **k=1** est quasi optimal ; k=5 fait chuter la mémoire sous-tâche de 49,4 à 33,3. L'effet est le plus grand à 4 Md (+34,5) et s'amenuise à 8 Md et 14 Md.
Un enseignant plus fort n'est pas forcément meilleur (GPT-5-mini bat DeepSeek V4 Pro pour Qwen3-4B : 49,40 contre 38,10). Cinq répétitions (Qwen3-4B) : écarts-types inférieurs à 1 point. Mémoire construite **à partir des seules réussites** de l'enseignant ; aucun usage des échecs.

**Ce que l'annexe B.3 corrige** [L] : dans les expériences principales, la mémoire est distillée et appliquée **sur le même banc**. Sous deux protocoles disjoints (7:3 ; ou récupération « hors soi »), pour Qwen3-4B la configuration complète donne **41,07 / 46,43** (AppWorld), **30,65 / 31,00** (BFCL), **22,92 / 23,26** (ToolSandbox), soit −8,3 / −3,0 points (AppWorld) et −7,9 / −7,5 points (BFCL) contre la configuration principale, mais +2,8 / +3,1 sur ToolSandbox. Les gains subsistent, mais le chiffre vedette (« équivalent à l'enseignant ») ne l'est plus dans la configuration disjointe (41-46 contre 50). Le papier ne dit pas si des tâches **sœurs d'un même gabarit** restent dans la banque dans le protocole « hors soi » [D : à vérifier avant d'y croire].

**Ce que démontrent les dépôts et la communauté.** Le dépôt `agentic_memory_distillation` existe (9 ★, 0 issue, publié 2026-08-10, **sans aucune licence**) : on peut le **lire** pour comprendre, on ne peut ni le copier ni s'en inspirer au-delà de l'idée sans autorisation de l'auteur [D juridique ; question pour un avocat si on voulait aller plus loin]. Je n'ai trouvé **aucune réplication, critique ou suite** (recherche GitHub et arXiv au 2026-11-02) ; des articles voisins la citent (ContraMem, Artifact Distillation, PLVR), sans la remettre en cause [R].

**Forces transférables à OPSYS.**
1. **Trois granularités avec trois formats** : plan en prose, exemples d'exécution concrets, fiche par fonction. C'est la structure que demandait Nathan (flux de travail / sous-tâche / appel d'outil MCP).
2. **Injection proactive + réactive** : le gros du contexte au début, un indice **seulement quand un outil échoue** (pas de gonflement du contexte en cas de succès).
3. **Marques de substitution typées** (`<ID>`, `<EMAIL>`, `<CHEMIN>`) : notre règle « jamais une valeur » est déjà dans leur méthode.
4. **Transfert sans entraînement** et **mesure d'efficacité** (tours d'interaction : 23,8 → 14,9 pour Qwen3-4B / AppWorld).
5. **Analyse de la dépendance enseignant-étudiant** : à nous de la mesurer plutôt que de supposer.

**Limites et hypothèses non prouvées pour notre cas.**
1. **Anglais seulement.** Aucune donnée en français ni en québécois ; le plan en prose et les descriptions de sous-tâches dépendent de la langue du modèle et de l'embedding. [L pour « anglais », D pour le risque]
2. **Appels d'outils ≠ MCP gouverné.** AppWorld = code Python exécuté contre des API d'applications simulées ; BFCL = appel de fonctions ; ToolSandbox = JSON. Chez nous : approbation N0-N5, refus `REJ-…`, registre scellé, empreintes. Une mémoire qui apprend « comment obtenir le résultat » pourrait apprendre à **chercher l'approbation par un détour**. [D]
3. **Exemples concrets = valeurs.** Le gain vient des exemples de code avec observations réelles ; chez nous une observation d'outil contient des données d'affaires (prix, noms). Notre version doit se contenter d'exemples **à substitutions** et d'observations **à schéma** : on n'a aucune mesure du gain qui reste. [D]
4. **PME de rénovation.** Les bancs sont des applications grand public (courriel, paiement, musique). Aucune tâche longue de PME (soumission, chantier, facture) ; le **vocabulaire sectoriel** est en dehors du cœur générique (décision r7 : le cœur reste neutre, le secteur est un *pack*). [D]
5. **Enseignant fort disponible.** Ils utilisent GPT-5-mini (API payante). Nous n'achetons rien : enseignant = modèle local fort sur GB10 (non mesuré) ou **réponses de référence écrites à la main** du gabarit d'évaluation (130 cas). Le papier montre que la **compatibilité** compte : un enseignant « plus fort » peut être pire. [L pour le papier, D pour la conséquence]
6. **Mémoire figée.** AMD ne se met pas à jour avec l'expérience de l'étudiant (limite avouée). Nous voulons au contraire des échecs réels comme source ; d'où la jonction avec ReasoningBank (§ 4).
7. **Décomposition de tâche par le petit modèle** : le niveau sous-tâche suppose que l'étudiant sait décomposer sa tâche en au plus six étiquettes ; c'est un appel de plus et une source d'erreur à mesurer. [L]
8. **Statistique** : deux passages par configuration (moyenne), cinq pour un seul modèle ; pas d'intervalles de confiance. [L]

**Verdict AMD.** ADAPTER : trois niveaux, injection proactive/réactive, k=1, prose/exemple selon le niveau. IGNORER le code (licence). SURVEILLER : version publiée, réplication, licence du code. Inscription INGREDIENTS : **Référence**.

---

## 6. Ce que la littérature récente ajoute (lu en abstract seulement, [R])

| Constat | Source | Ce que ça change pour nous |
|---|---|---|
| Beaucoup de systèmes de mémoire dédiés **font moins bien qu'un RAG naïf** sur l'historique brut (« taxe de mémoire ») | arXiv 2610.34073 | Le banc doit inclure comme témoin un **RAG brut sur trajectoires fictives**, pas seulement « sans mémoire » |
| Une bibliothèque de compétences **écrite par un LLM apporte +0,0 point** contre aucune compétence ; écrite par un humain +16,2 ; sans entretien elle **dérive** jusqu'à nuire ; un juge qui classe des échecs comme réussites ne peut retirer **aucune** compétence | arXiv 2605.22148 (Ratchet) | Bibliothèque **bornée** (plafond par département et par genre), retrait selon la **contribution mesurée**, jugement par oracle déterministe |
| Audit de AWM, ReasoningBank et SkillOpt dans un **e-banking simulé** : gain d'utilité, mais exposition aux contenus injectés et **changements d'état non autorisés** en hausse pour SkillOpt ; ReasoningBank ne hausse pas le taux d'attaque agrégé mais laisse les changements d'état non autorisés légèrement au-dessus du témoin | arXiv 2608.17684 | Test de sécurité obligatoire (non-régression des refus et de l'approbation) avant toute promotion |
| Les agents **suivent l'expérience** (entrée proche → sortie proche) ; erreurs qui se propagent, « rejeu mal aligné » même sur des exécutions apparemment correctes ; les évaluations futures servent d'étiquettes de qualité gratuites | arXiv 2505.16067 | Les compteurs utile/nuisible alimentés par les **issues ultérieures** (outils, approbations) |
| **Reproduction d'erreurs** : une abstraction fausse, exécutée, produit des trajectoires qui la ré-abstraient ; remède « anti-persistance » : conserver trajectoires et issues, reconstruire le conseil à la demande | arXiv 2610.27406 | Ne jamais **induire** à partir d'une trajectoire influencée par la mémoire sans témoin sans mémoire |
| Empoisonnement de la mémoire : **MemoryGraft** (expériences réussies malveillantes implantées par des artefacts ingérés), **MemMorph** (détournement du choix d'outil par des « faits techniques » forgés, jusqu'à 85,9 % de succès d'attaque), **Salami/MemCollusion** (fragments individuellement bénins, **contre OpenClaw**), **OEP** (expériences « localement correctes » mais non transférables), **MemForm** (cinq interfaces de formation), preuve que ni le contenu ni la lignée ne suffisent et qu'il faut **lier l'origine à l'écriture** | arXiv 2512.16962, 2605.26154, 2608.01637, 2605.18930, 2610.14431, 2606.24322 (et au moins douze autres sur les vingt résultats de la requête) | La mémoire d'expérience ne s'alimente **jamais** à partir de contenu non fiable (courriel, document ingéré, web) ; **origine liée à l'écriture** ; revue humaine N3 |
| Fiabilité des juges LLM : verdicts qui changent entre répétitions identiques, 51 % d'accord avec la vérité pour le juge « le plus déterministe » | arXiv 2610.12083 | Pas de LLM-juge comme décideur |
| Distillation d'un fort vers un petit **sans entraînement** par artefacts ou **programme compilé** (PLVR : Granite-4.2-8B de 43,0 % à 91,2 % sur τ²-Telecom) | arXiv 2610.37680, 2610.19148 | À surveiller ; PLVR confirme que la voie « le code vérifie, le petit modèle propose » est sérieuse |

---

## 7. Ce qu'OPSYS-AI a déjà, et ce qui manque

| Idée de la littérature | Équivalent déjà dans le dépôt [L] | Écart |
|---|---|---|
| Leçon proposée → mesure → promotion → retour arrière | `src/opsys/mnemo/lecons.py` (4 genres : écart matériaux, écart marge, refus récurrent, rejets du modèle de soi), `promotion.py` (canari de 1 à 50 % par hachage, un canari à la fois, retour arrière), outil `m10_decider_lecon` (N3 humain), événement `m10.lecon_decidee`, `m10_surveiller_lecons` | Le **texte d'une leçon est un gabarit du code**, sans chiffre ni identifiant ; il n'existe aucun genre « stratégie rédigée », « exemple d'appel » ou « piège d'outil » ; `opsys_lecons_actives` n'a **aucun lecteur** |
| Éléments mémoire dérivés de refus d'outil | genre `refus_recurrent` : un outil refusé avec le même code dans ≥ 3 affaires ; POSTFLIGHT `m10_deposer_faits_candidats` (outil, résultat ok/refus, code, rien d'autre ; jusqu'à 20 faits par dépôt) | Ni la forme des arguments, ni l'ordre des appels, ni la correction qui a réussi ensuite ne sont conservés ; aucune récupération sur erreur |
| Stratégies de l'enseignant | `reponse_reference` de chaque cas du gabarit d'évaluation (130 cas écrits à la main, 10 départements) | Pas exploitées comme « trajectoires expertes » |
| Récupération au début de tâche | `m10_contexte_preflight` / `m10_paquet_contexte_affaire` (4 couches, 4 000 caractères, provenance sur chaque fait) ; base de connaissances (FTS5 + similarité exacte + fusion RRF, reranker facultatif, anti-injection) | Aucun bloc « expérience » |
| Jugement | gabarit commun `opsys.evaluation` (7 catégories, attentes déterministes, répondants doubles, `RepondantPasserelle` déclaré, jamais exécuté) ; garde du gabarit pour une leçon | **Aucun modèle réel mesuré**, aucune comparaison avec/sans mémoire, aucun petit modèle |
| Provenance et registres | registres chaînés append-only (`registre.py`), Événements/Affaires/soi/leçons ; traces locales à chaîne HMAC **sans contenu** (`observabilite/traces.py` refuse les clés « arguments », « sortie », « résultat »…) | Les traces ne peuvent pas servir de source d'exemples d'appel (c'est voulu) |
| Gouvernance des outils | registre MCP scellé (636 outils, révision 13) : empreinte sha256 du triplet nom + description + schéma, niveau N0-N5, Rule of Two | Aucune mémoire n'est liée à l'empreinte d'un outil |
| Anti-PII et anti-injection | `mnemo/vie_privee.py` (pseudonymes, garde-fou de texte, refus d'une consigne glissée, refus de secret), `observabilite/pii.py` | À réutiliser tel quel pour le texte d'un élément |
| Boucle décision → résultat → leçon (M9) | `m9_consigner_decision_direction` (N3), `m9_mesurer_resultat_decision` (code compare deux décimaux), leçon `PROPOSEE_NON_VALIDEE` validée par la direction (N3), `m10_lire_faits_strategiques` (niveau FINANCIAL, jamais dans un paquet de contexte) | Concerne des **décisions d'affaires**, pas le comportement des agents ; à garder séparé |
| Apprentissage depuis les corrections humaines (M1.13) | `m1_front_office/apprentissage.py` : retours humains → propositions → mesure → promotion N3 | Seulement des règles de tri et des phrases de gabarit |
| Domaine développement | `developpement.py`, `consolidation_developpement.py` (modèle de soi du développement, isolé des affaires, ADR-0012) | Pas d'expérience de dev structurée |

**Lecture.** Le cycle de gouvernance (la partie difficile) est **déjà là**. Manquent la **matière** (éléments rédigés admissibles), la **récupération** (début de tâche, sur erreur d'outil), et la **mesure** (avec/sans, petit/grand, en français).

---

## 8. Risques et parades

| Risque | Mécanisme (source) | Parade proposée (détail dans la proposition) |
|---|---|---|
| **Dérive** (la bibliothèque grossit, se contredit, se périme) | ACE issue #11 (playbook > 100 000 jetons) ; Ratchet | Plafond par (département, genre) ; retrait par contribution mesurée ; **archiver, jamais supprimer** (invariant du curateur de Hermes) ; péremption liée à l'**empreinte de l'outil** |
| **Empoisonnement** | MemoryGraft, MemMorph, Salami (contre OpenClaw), OEP, MemForm | Origine liée à l'écriture ; **aucune induction depuis du contenu non fiable** ; admission par schéma fermé ; revue N3 de chaque promotion ; recherche d'éléments « collusifs » (même outil, conseils croisés) à l'évaluation |
| **Fuite de renseignements personnels** | trajectoires brutes de ReasoningBank ; observations d'AMD | Schéma fermé sans texte libre non filtré ; **aucun chiffre sauf identifiants du registre** ; garde-fou de texte + masquage PII + détecteur de secret ; trajectoires de départ **fictives seulement** ; EFVP avant tout contenu réel |
| **Renforcement d'erreurs** | arXiv 2610.27406, 2505.16067 | Chaque exécution étiquetée par les éléments injectés ; **pas d'induction** depuis une exécution influencée sans témoin sans mémoire ; compteurs utile/nuisible par signaux déterministes |
| **Auto-jugement non fiable** | juge à 72,7 % (RB) ; arXiv 2610.12083 ; Ratchet | Étiquettes de succès par **oracles** : issue d'outil (ok/refus typé), décision d'approbation humaine, attentes déterministes du gabarit, résultat mesuré par le code (M9) ; le LLM peut **proposer**, jamais **trancher** |
| **Copie de valeurs d'un exemple** | AMD (exemples concrets) ; règle « le code calcule » | Valeurs-sentinelles reconnaissables dans les exemples ; métrique « taux de copie » ; exemples à substitutions typées seulement |
| **Contournement d'approbation** | risque propre à OPSYS (N3-N5) | Un élément ne peut ni nommer un contournement ni abaisser un niveau ; test d'abus ; élément sur outil N3+ limité aux **conventions d'arguments** |
| **Contamination de l'évaluation** | issues #17/#36/#37/#40 de RB ; AMD annexe B.3 | Découpage par **gabarit de cas**, récupération qui exclut le gabarit courant, manifeste d'audit haché de la banque et des identifiants éligibles |
| **Dépendance à l'enseignant** | AMD tableau 3 | Plusieurs enseignants mesurés ; enseignant = modèle local ou réponses de référence ; versions et empreintes des invites consignées |
| **Fuite entre départements ou domaines** | principes M10 (confidentialité à sept niveaux) | Clé de partition (département, domaine) obligatoire ; lecture limitée à son propre espace ; partage seulement par décision humaine ; **jamais** de mélange développement / affaires |

---

## 9. Décisions et ordre

| # | Décision | Pourquoi | Conditions de réexamen |
|---|---|---|---|
| 1 | **Construire en interne** la mémoire d'expérience (schéma fermé, registre chaîné, promotion `opsys.mnemo.promotion`), sans dépendance nouvelle | Aucune brique n'a la gouvernance exigée ; les idées utiles sont petites ; licences (AMD) et maturité (ReasoningBank) l'interdisent | Un dépôt MIT/Apache avec tests et réplication indépendante |
| 2 | **Banc avec/sans mémoire avant tout item rédigé** (petit, moyen, grand ; RAG brut et mémoire placebo comme témoins) | Les gains publiés ne sont pas répliqués ; Memory Tax | — |
| 3 | **Fiches de convention d'outil déterministes** (dérivées des schémas du registre et des codes `REJ-…`) comme premier niveau « fonction » | 0 donnée personnelle, 0 modèle, liées à l'empreinte ; mais le gain attendu est le **plus faible** d'AMD, donc on le mesure | Gain nul au banc : s'arrêter là |
| 4 | **Stratégies et exemples de sous-tâche** issus de trajectoires **fictives** de l'enseignant (local ou références écrites) | Seul le niveau « sous-tâche » porte le gain chez AMD ; la fiction évite tout renseignement personnel | Mesure positive en français sur ≥ 2 paliers de modèle |
| 5 | **Pilote conditionnel MemOS (plugin local)** : bac à sable OpenClaw fictif, hors production | Seule brique qui ressemble à ce qu'on veut, déjà adaptée à OpenClaw, SQLite local ; sert de **témoin « boîte noire »** pour le banc | Compatibilité avec le fork du Core, PII, récompense par LLM |
| 6 | **DSPy/GEPA hors ligne** : confirmé (E6), indépendant de ceci | Optimisent des prompts, pas une bibliothèque d'items | Résultats E6 |
| 7 | **IGNORER** ReasoningBank (code), AMD (code), A-MEM, LangMem, Cognee, OpenViking (AGPL), Letta comme runtime | Voir § 3 | — |
| 8 | **SURVEILLER** ContraMem, PLVR, Artifact Distillation, Hindsight, TencentDB Agent Memory, Graphiti/Zep (pilote E5), Mem0 | Voir § 3 | Dépôts licenciés, réplication, mesures indépendantes |

**Ordre de réalisation (détail et preuves exigées dans la proposition).** (1) Schéma et garde d'admission. (2) Corpus fictif et banc avec/sans mémoire, avec un répondant double sensible à la mémoire
pour valider le banc lui-même. (3) Fiches de convention d'outil. (4) Mesure réelle sur les paliers locaux (bloquée : modèles non mesurés). (5) Éléments dérivés de l'enseignant. (6) Canari, promotion, retour
arrière, console. (7) Signaux de production sans contenu. (8) Pilote MemOS optionnel.

---

## 10. Ce que cette veille ne prouve pas (sans euphémisme)

- **Rien n'a été exécuté.** Aucun dépôt n'a été installé, aucun test lancé, aucun modèle appelé. Tous les chiffres de performance sont ceux des auteurs, des éditeurs ou d'utilisateurs rapportant dans des issues.
- Les **abstracts** ne sont pas des résultats : AWM, Reflexion, Voyager, ExpeL, A-MEM, SkillWeaver, Dynamic Cheatsheet, Memp, GEPA et tous les articles de risque ne sont connus que par leur résumé. Les chiffres d'ACE viennent d'une synthèse produite par un outil sur la page de l'article.
- Les **trois rapports de non-reproduction** de ReasoningBank sont des déclarations d'utilisateurs, non vérifiées. Les mainteneurs ont dit en avril 2026 avoir trouvé des problèmes dans le code et l'ont mis à jour ; je n'ai pas d'élément pour dire si les chiffres de l'article tiennent avec la version corrigée.
- **Aucune évidence en français ni sur MCP** pour aucune méthode. Aucun modèle local n'est mesuré dans le dépôt (le répondant passerelle du gabarit est déclaré, pas exécuté ; la qualification de vLLM sur GB10 est ouverte).
- Pas d'examen juridique : la lecture des licences est la mienne (texte lu), l'usage d'idées d'un dépôt **sans licence** (AMD) reste une question pour un avocat (`docs/compliance/QUESTIONS-AVOCAT.md`).
- Les sous-dossiers à licence propre de MemOS, Mem0 et Hindsight n'ont été lus que par leur première ligne.
- La recherche GitHub par mots-clés a une couverture limitée ; un projet mature que mes requêtes n'ont pas fait remonter a pu m'échapper.

---

## 11. Sources (consultées le 2026-11-02)

**Articles.** ReasoningBank, arXiv 2509.25140 v2 (2026-03-16), <https://arxiv.org/abs/2509.25140> et HTML v2. AMD, arXiv 2608.07169 v1 (2026-08-07), <https://arxiv.org/abs/2608.07169>, HTML v1,
page <https://agent-memory-distillation.github.io/>. ACE, arXiv 2510.04618. AWM 2409.07429. Reflexion 2303.11366. Voyager 2305.16291. ExpeL 2308.10144. A-MEM 2502.12110. SkillWeaver 2504.07079.
Dynamic Cheatsheet 2504.07952. GEPA 2507.19457. Memp 2508.06433. Risques : 2505.16067, 2610.27406, 2610.34073, 2605.22148, 2608.17684, 2512.16962, 2605.26154, 2608.01637, 2605.18930, 2610.14431, 2606.24322, 2610.12083.
Voisins récents : 2608.22533 (ContraMem), 2610.37680 (Artifact Distillation), 2610.19148 (PLVR).

**Dépôts (commit de tête, date).** `google-research/reasoning-bank` `ed80611` 2026-05-19 · `taeilkim2465/agentic_memory_distillation` `2895d10` 2026-08-10 · `zorazrw/agent-workflow-memory` `8c0ff8c` 2025-12-22 ·
`noahshinn/reflexion` `218cf0e` 2025-01-14 · `MineDojo/Voyager` `55e45a8` 2023-07-27 · `LeapLabTHU/ExpeL` `e41ec9a` 2024-12-20 · `ace-agent/ace` `82709de` 2026-08-24 · `WujiangXu/A-mem` `f9a173d` 2026-10-28 ·
`agiresearch/A-mem` `ceffb86` 2025-12-12 · `mem0ai/mem0` `753496c` 2026-10-30 · `letta-ai/letta` `8816d3a` 2026-10-18 · `letta-ai/letta-code` `3b7e3ff` 2026-11-02 · `getzep/graphiti` `16bf514` 2026-11-01 ·
`getzep/zep` `d1cbb1c` 2026-11-01 · `topoteretes/cognee` `525b1d1` 2026-10-29 · `langchain-ai/langmem` `839c3fa` 2026-10-30 · `MemTensor/MemOS` `64388b5` 2026-10-29 · `stanfordnlp/dspy` `25162c4` 2026-10-29 ·
`gepa-ai/gepa` `8c7b697` 2026-10-31 · `OSU-NLP-Group/SkillWeaver` `f2a63d6` 2025-04-14 · `suzgunmirac/dynamic-cheatsheet` `5cfe3c3` 2026-03-12 · `zjunlp/MemP` `3066a1b` 2026-01-30 · `vectorize-io/hindsight` `bc5ea19` 2026-10-30 ·
`TencentCloud/TencentDB-Agent-Memory` `ecc01a5` 2026-10-28 · `volcengine/OpenViking` `15c4783` 2026-11-02 · `NousResearch/hermes-agent` `f45d3aa` 2026-11-02 · `Lanerra/reasoning-bank-slm` `f25696b` 2025-10-14 ·
`apple/ToolSandbox` `c8571d7` · `ShishirPatil/gorilla` `6ea5797` · `StonyBrookNLP/appworld` `42b5bcf` · `sierra-research/tau2-bench` `da0835f`. (Chiffres complets : TSV joint.)

**Issues ReasoningBank lues** : <https://github.com/google-research/reasoning-bank/issues/2>, `/6`, `/11`, `/14`, `/17`, `/36`, `/40`.

**Internes.** `AGENTS.md` (Briques open source), `docs/produit/DIRECTIVES-NATHAN.md`, `docs/architecture/M10-SOI-GRAPHE.md` (§ 5 apprentissage continu), `docs/architecture/M9-ATHENA.md` (§ 7), `docs/architecture/EVALUATION.md`,
`docs/architecture/OBSERVABILITE-MCP.md`, `src/opsys/mnemo/`, `departments/m10-memoire/src/m10_memoire/faits_candidats.py`, `src/opsys/registre_mcp/registre.v1.json`, feuille de route technologique r1 (R6, § 3.3-3.4, E5-E6, hors dépôt).

---

## Annexe : méthode de veille en 10 lignes

(Version réutilisable, avec fiche à remplir : [`METHODE-VEILLE.md`](METHODE-VEILLE.md).)

1. **Fixer la question et les filtres durs avant de chercher** : cas d'usage, licences admises, exécution locale, Loi 25, « le code calcule ». Écrire ce qui ferait **rejeter** une brique.
2. **Chercher large puis étroit** : GitHub (mots-clés, sujets, étoiles), arXiv, listes à jour, issues ; noter les requêtes pour que d'autres les rejouent. Ne pas se fier à un classement par étoiles.
3. **Lire le fichier `LICENSE` lui-même** (et les sous-dossiers) ; relever l'empreinte ; une bannière ou un champ d'API n'est pas une licence. Pas de licence = pas d'usage du code.
4. **Mesurer la maturité** : commit de tête et date, version, tests, issues ouvertes (lire les titres), PR fusionnés, dépendances, poids, mise en garde du README (« démonstration »).
5. **Chercher les échecs avant les succès** : issues de reproduction, critiques, audits de sécurité, articles qui comparent à des témoins simples (RAG brut, sans mémoire).
6. **Distinguer lu / résumé / déduit** ([L] [R] [S] [D]) ; ne jamais écrire qu'une méthode « marche » à partir d'un résumé ou d'un chiffre d'éditeur ; dire ce qui n'a pas été exécuté.
7. **Regarder le protocole** : jeux d'essai et de mémoire séparés ? plusieurs passages ? intervalles ? juge humain ou LLM ? même modèle pour agir, juger et apprendre ?
8. **Confronter à l'existant** : que fait déjà le dépôt (code lu) ? L'écart est-il la brique ou la matière ? Préférer réutiliser nos mécanismes de gouvernance.
9. **Décider par verdict daté** : ADOPTER / ADAPTER (idée seulement) / SURVEILLER (avec condition de réexamen) / IGNORER (avec raison) ; inscrire seulement ce qui est qualifié dans `INGREDIENTS.md`, à la fin du fichier.
10. **Rendre reproductible et honnête** : fichier de relevé (commit, licence, empreinte), sources avec URL et date de consultation, limites sans euphémisme, questions ouvertes pour Nathan ; relancer la veille à date fixe ou sur événement.
