# OPSYS-AI — Core d'automatisation d'entreprise

OPSYS-AI construit un Core d'entreprise autoritatif et installable avant la
complétion des modules métier. Le programme actif est **Core v2.3.0**.

## Commencer ici

1. Lire `docs/core/CANON-INDEX.md`.
2. Lire les ADR actives sous `docs/decisions/`.
3. Pour une mission Core, utiliser
   `.opsys/core-control/2.3.0/TASK-REGISTRY.jsonl` et
   `.opsys/core-control/2.3.0/DEPENDENCY-GRAPH.json`.
4. Travailler depuis l'issue GitHub unique, une branche et un worktree dédiés ;
   prouver RED, GREEN, rollback et résultat lié au commit/tree exacts.

## Ordre du programme

```text
Core C00 → C24
→ M7 → M1 → M2 → M4 → M3 → M6 → M8 → M10 → M5 → M9
→ surfaces mobile, cockpit et avatar finales
```

Pendant le Core, aucune logique métier M1–M10 n'est complétée. La recherche et
les plans candidats restent permis ; chaque module sera ensuite traité un par
un, intégré, testé et prouvé.

## Architecture de référence

- modular monolith Python/PostgreSQL ;
- ports explicites et workers isolés seulement lorsque nécessaires ;
- DomainEvent, ActionIntent, Query et Receipt/Postcondition ;
- outbox/inbox, idempotence, déduplication, DLQ, compensation,
  réconciliation et `IN_DOUBT` ;
- frameworks soumis à tournoi et aucun downgrade silencieux.

Voir `docs/core/CORE-CANON-v2.md` et
`docs/core/CORE-NON-GOALS-v2.md` pour les frontières exactes.

## Développement et preuve

- jamais de push direct sur la branche par défaut ;
- tests ciblés pendant la boucle, contrôles lourds au gate de phase/release ;
- aucun stub, faux succès, timeout masqué ou dépendance non qualifiée ;
- une issue fermée ou un consensus LLM ne constituent pas une preuve ;
- PostgreSQL de test dédié, éphémère et isolé ; jamais les bases d'un autre
  service présent sur l'hôte.

## Historique conservé

Le plan GRS/PROOF STACK v1.1, la Phase C historique, `START_HERE.md` et
`PROMPT_BOOTSTRAP_CLAUDE_CODE.md` sont conservés pour provenance. Ils sont
**superseded comme points d'entrée opérationnels** par
`docs/core/CANON-INDEX.md`.

Les fichiers `VISION.md`, `FORGE_METHOD.md`, `IMPLEMENTATION_SPEC.md` et
`RECONCILIATION.md` décrivent un produit-méthode distinct ; ils ne gouvernent
pas l'exécution du Core OPSYS-AI.

## Licence

Voir `LICENSE`. Toute contradiction entre le fichier de licence et les
métadonnées de packaging doit être résolue explicitement avant publication.
