# ADR-0010 — Mémoire : deux magasins, M10 gouverne, la « RAM » est le moteur de contexte

- Statut : **Accepté** (ingénieur en chef, 2026-09-28).
- Complète : [ADR-0008](ADR-0008-fork-openclaw-opsys-core.md) (décision 7) et
  [ADR-0009](ADR-0009-socle-metier.md) (base de l'instance).
- Fondé sur : [audit M10](../departements/M10-audit.md), [RAG-PREMIUM](../memory/RAG-PREMIUM.md),
  documentation mémoire du core (`docs/concepts/memory*.md`, `context-engine.md`, `plugins/hooks.md`).

## Contexte

La définition (P4, P11, M10) exige une mémoire gouvernée, sourcée, versionnée, à paquets de contexte
en couches, qui n'oublie rien et n'injecte que l'utile. Aujourd'hui il existe trois magasins de fait :
- la mémoire des agents du core (SQLite par agent) ;
- la mémoire d'entreprise (PostgreSQL) ;
- le registre M10, en mémoire du processus et perdu au redémarrage.

OPSYS n'écrit aucune configuration mémoire pour les agents. Le partage entre agents
(`tools.agentToAgent`) est actif par défaut.

## Décisions

1. **Deux magasins physiques, pas trois.**
   - **Couche A**, mémoire native de chaque agent du core : paliers, provenance, « dreaming »,
     rappel en deux voies. Mémoire de travail de l'agent, jamais source de vérité d'un fait
     d'entreprise.
   - **Couche B**, mémoire d'entreprise dans la base de l'instance (ADR-0009) : SQLite + FTS5 +
     sqlite-vec par défaut, PostgreSQL + pgvector en option. Même API et mêmes tests que
     `src/opsys/memoire` aujourd'hui.
2. **M10 gouverne, il ne stocke pas.** Ses registres (événements, décisions, révisions) deviennent
   des lignes de la Couche B, chaîne de hash conservée. Il porte :
   - les statuts (10 valeurs de la définition) ;
   - l'ordre de vérité ;
   - la détection des contradictions ;
   - l'audit « non-oubli ».
   Les sept niveaux de confidentialité de la définition deviennent la taxonomie canonique. Les
   quatre sensibilités actuelles de la Couche B s'y rattachent ; la donnée « personnelle » Loi 25
   devient `CLIENT_PRIVATE`, avec échéance et sujet obligatoires. `registre_forge` est renommé
   `registre_evenements` (point ouvert 5 de la définition).
3. **La « RAM » est un moteur de contexte natif du core**, dans le slot `contextEngine`
   (`core/extensions/opsys-context-engine`).
   - `assemble()` compose à chaque tour, sous un budget de tokens, quatre paquets :
     « doit savoir », important, preuves, et approfondissement, chargé seulement sur demande.
   - La compaction est déléguée au runtime.
   - `afterTurn()` est le POSTFLIGHT.
   - Rien n'est stocké entre deux tours : la mémoire durable reste A et B.
4. **PREFLIGHT et POSTFLIGHT sur les hooks du core.**
   - `before_prompt_build` : contexte suffisant, et injection.
   - `before_tool_call` : blocage d'une action N3 ou plus si le contexte est insuffisant.
   - `after_tool_call` : journal de décision et fait mémorisé avec `source = outil + identifiant
     d'approbation`.
   - `agent_end`.
5. **Un seul service d'embeddings local pour les deux couches** : bge-m3 servi en compatible
   OpenAI sur la machine, `memory.search.provider: "openai-compatible"`. Un endpoint cloud
   n'est possible qu'avec une politique explicite (Loi 25, art. 17) ; les données `CLIENT_PRIVATE`
   n'y partent jamais.
6. **Cloisonnement.**
   - Le partage entre agents de département est désactivé par défaut.
   - Un département lit la mémoire d'un autre seulement par la Couche B, dans ses portées de
     lecture.
   - Le contenu des outils, des pages web et des clients reste une donnée non fiable, jamais une
     consigne.
7. **Graphe de connaissances** :
   - par défaut, une table de relations temporelle (sujet, prédicat, objet, source, confiance,
     validité), dans la même base ;
   - en option, Graphiti avec Neo4j, adopté seulement si le repli sature et que la mesure le
     justifie.

## Conséquences

- Porter `src/opsys/memoire` sur SQLite (FTS5 + sqlite-vec) en gardant PostgreSQL en option, avec
  le même jeu d'or et les mêmes tests sur les deux moteurs.
- OPSYS écrit la configuration mémoire des agents du core : provider d'embeddings, dreaming,
  provenance, cloisonnement.
- Première tranche (audit M10, phase 1) : la fin de travaux s'inscrit en mémoire avec sa provenance,
  et le paquet de contexte est injecté à la prochaine estimation de M3 (estimé contre réel).

## Mise en œuvre

### T3.3-suite : greffe du moteur de contexte dans le core (PREFLIGHT et POSTFLIGHT)

Faite le 2026-09-29. Le détail des fichiers est dans `core/PROVENANCE.md` (« Greffes OPSYS »).

Ce qui existe (activable pour tout agent nommé ; le cas visé est M3, avant `m3_estimer_projet`) :
- **Décision 3, `assemble()`.** Le moteur `opsys` (slot `contextEngine`) demande à M10 le paquet de
  l'affaire (`m10_paquet_contexte_affaire`) et le rend en `systemPromptAddition`. L'assemblage des messages et
  la compaction restent ceux du lanceur (`LegacyContextEngine`, `delegateCompactionToRuntime`).
- **Décision 3, `afterTurn()` = POSTFLIGHT.** Il dépose chez M10 ce que les outils listés ont fait pendant le
  tour (`m10_deposer_faits_candidats`) : outil, résultat `ok` ou `refus`, code. Jamais un texte de modèle.
  Un fait déposé est un **candidat** : hors du paquet, hors de la consolidation nocturne.
- **Appel au moteur métier.** Par la voie existante : `mcp.servers.opsys_m10` (HTTP `streamable`, en-tête
  `Bearer ${OPSYS_MCP_JETON}`, point d'accès `/mcp/m10-memoire`). Jamais d'accès direct à la base. Un appel
  ouvre sa connexion et la referme : rien n'est gardé entre deux tours.
- **Budget.** M10 calcule le budget de caractères et la troncature ; le core valide la cohérence du paquet
  (compteurs, quatre couches dans l'ordre, total sous le budget de M10) et le refuse en entier au moindre écart.
  Il ne le tronque jamais. Un paquet plus grand que le budget de tokens que le lanceur laisse est refusé de la
  même façon.
- **Fail-closed et sans blocage.** Moteur injoignable, trop lent (`delai_ms`, 4 s par défaut), réponse
  tronquée par le serveur, paquet invalide ou hors budget, aucune affaire dans la demande : le tour continue
  sans paquet, avec le marqueur « contexte d'entreprise indisponible » dans le contexte et une ligne du
  journal `opsys-contexte`.
- **Désactivé par défaut.** `opsys/contexte.json` (`"actif": true`) et `plugins.slots.contextEngine: "opsys"`
  s'écrivent ensemble par `opsys openclaw configurer --contexte-entreprise AGENT[:OUTIL,OUTIL]`. Sans l'option,
  le fichier porte `{"actif": false}` et aucun moteur n'est choisi.
- **Mémoire native conservée.** Le lanceur retire du prompt système la section mémoire de `memory-core` pour
  tout moteur autre que « legacy ». Le moteur `opsys` la rajoute (`buildMemorySystemPromptAddition`) même
  quand `contexte.json` est inactif ou ne nomme pas l'agent : choisir ce moteur ne prive aucun agent de sa
  couche A. En prompt minimal (sous-agents), il la met aussi, ce que le lanceur ne ferait pas.
- **Niveau du dépôt.** `m10_deposer_faits_candidats` est T1 mais **N2** (tâche interne automatique), comme
  `m4_deposer_fichier`. En N3, le mode `ombre` de M10 mettrait chaque tour d'agent en attente d'approbation ;
  `openclaw.generer` refuse d'activer le moteur si le dépôt en exigerait une. Le dépôt est append-only, ne
  décide rien, n'engage personne, et reste fermé aux appareils.

Écarts avec le texte des décisions 3 et 4, voulus :
- **Emplacement.** `core/src/context-engine/`, et non `core/extensions/opsys-context-engine`. Une extension
  n'importe que le SDK de plugins, qui n'expose aucun client MCP ; elle aurait apporté le sien (importeur neuf
  du lockfile) et de nouvelles entrées dans des inventaires que le bac à sable ne régénère pas. La greffe est
  isolée et se déplace en extension telle quelle.
- **Hooks.** Le PREFLIGHT est dans `assemble()` et le POSTFLIGHT dans `afterTurn()`, pas dans
  `before_prompt_build` et `after_tool_call` : ces deux points du moteur de contexte portent déjà la
  permission d'injection et le résultat du tour, sans plugin ni permission de conversation.

Reste (rien de ce qui suit n'est fait) :
1. **Blocage `before_tool_call`** d'une action N3 ou plus si le contexte est insuffisant : le moteur n'observe
   que le début et la fin d'un tour.
2. **Résolution des signaux critiques.** M10 ne sait pas clore un signal : la couche « signaux non résolus »
   les liste tous, et le core le dit dans son titre sans rien résoudre. Il manque une clôture tracée
   (outil M10, décision humaine) et la lecture de cette clôture par le paquet.
3. **Affaire du tour.** Elle vient d'une ligne `affaire_id: <lead_id>` de la demande. Ce n'est acceptable que pour
   un agent qui ne reçoit que des demandes internes : un canal client direct pourrait nommer l'affaire d'un
   autre. À remplacer par une affaire liée à la session par l'orchestrateur avant d'activer M1. Les appelants
   de M3 (M1, M9) doivent écrire cette ligne ; le skill `estimer-un-projet` le dit.
4. **Consolidation des candidats.** La consolidation nocturne ne lit que les événements du bus ; les faits
   candidats attendent une validation puis une intégration à `m10_consolider_affaire` et au paquet.
5. **Paquet « avant une estimation ».** Le paquet est celui de l'affaire (règles, faits, événements, signaux).
   Le paquet par type de travaux (`paquet_contexte_estimation`, estimé contre réel) n'existe pas encore.
6. **Réutilisation de la connexion MCP** d'un tour à l'autre (quatre allers-retours HTTP par appel
   aujourd'hui), et **confidentialité** : le paquet ne porte aujourd'hui aucune donnée `CLIENT_PRIVATE` ; il
   faudra filtrer par niveau avant d'y en mettre.
7. **Déploiement.** `deploy/entrypoint.sh` et `deploy/install.sh` appellent `opsys openclaw configurer` sans
   l'option : rien n'est activé à l'installation. Le choix du propriétaire (quels agents, quels outils) reste à
   brancher.
8. **Preuve en réel.** Les tests du core tournent en CI seulement ; aucun tour d'agent n'a encore été
   exécuté de bout en bout avec un moteur métier lancé.
