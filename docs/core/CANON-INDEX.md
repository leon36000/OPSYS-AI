# OPSYS-AI — Index du canon Core actif

`CANON_STATUS: ACTIVE`

`CANON_VERSION: Core v2.3.0`

Ce document est l'unique point d'entrée du canon Core versionné. Il indexe les
documents qui font autorité ; il ne les recopie pas et ne remplace pas leurs
contrats détaillés.

## Ordre d'autorité

En cas de contradiction dans le dépôt :

1. la décision ratifiée la plus récente sous `docs/decisions/` ;
2. les documents Core actifs indexés ci-dessous ;
3. le registre, le graphe et le contrat exécutables du Core ;
4. les tests, contrôles et preuves liés au commit et à l'arbre mesurés ;
5. les portails racine, qui sont dérivés et ne peuvent pas créer une règle.

Une issue, une étiquette, une fermeture manuelle ou un avis de modèle ne
remplace jamais une preuve exécutable ni une décision humaine requise.

## Documents Core actifs

- `docs/core/CORE-CANON-v2.md` — invariants et autorités du Core ;
- `docs/core/CORE-NON-GOALS-v2.md` — frontières du programme `C00` à `C24` ;
- `docs/core/MODULE-ORDER-AND-DEFERRED-SURFACES.md` — ordre des modules et
  surfaces différées ;
- `docs/core/CI-REQUIRED-CHECKS.md` — contrat des contrôles Core ;
- `.opsys/core-control/2.3.0/TASK-REGISTRY.jsonl` — registre des missions ;
- `.opsys/core-control/2.3.0/DEPENDENCY-GRAPH.json` — dépendances et
  parallélisme autorisé ;
- `.opsys/core-control/2.3.0/REPOSITORY-CONTRACT.md` — identité et limites du
  dépôt ;
- `.opsys/core-control/2.3.0/GITHUB-OPERATING-MODEL.md` — cycle des issues,
  preuves et intégration.

## Programme et frontières

Le programme actif qualifie d'abord le Core `C00` à `C24`. Aucun code métier
`M1` à `M10` ne doit être complété avant `CORE_RC_VERIFIED` et les gates
humains ou professionnels applicables. Ensuite, l'ordre ratifié est :

```text
M7 → M1 → M2 → M4 → M3 → M6 → M8 → M10 → M5 → M9
```

Les contrats et surfaces différées restent ceux définis par les documents Core
ci-dessus ; cet index ne les élargit pas.

## Portails et documents non autoritatifs

`README.md`, `START_HERE.md`, `PROMPT_BOOTSTRAP_CLAUDE_CODE.md`, `AGENTS.md` et
`CLAUDE.md` servent de portails ou d'adaptateurs courts vers cet index. Ils ne
doivent pas contenir un second canon.

Les anciens plans, packs, prompts et documents de provenance restent
consultables à leur emplacement, mais ne gouvernent pas l'exécution Core tant
qu'ils ne sont pas explicitement réadoptés par une décision ratifiée.
