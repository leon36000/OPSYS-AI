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
