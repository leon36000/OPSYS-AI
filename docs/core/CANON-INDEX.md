# OPSYS-AI — Index du canon Core actif

Ce fichier est la porte d'entrée documentaire **exécutable dans ce dépôt**.
Il remplace comme point de départ les anciens parcours GRS/PROOF STACK et les
prompts historiques conservés à la racine.

## Priorité locale

En cas de contradiction dans l'arbre versionné :

1. ADR ratifiée la plus récente sous `docs/decisions/` ;
2. documents Core actifs ci-dessous ;
3. registre et graphe exécutables du plan Core ;
4. tests, runtime et preuves liés au commit exact ;
5. documentation historique explicitement marquée comme telle.

Une issue, un label GitHub, une fermeture manuelle ou un consensus de modèles
ne remplace jamais une preuve exécutable.

## Canon Core

- `docs/core/CORE-CANON-v2.md` — invariants et autorités du Core ;
- `docs/core/CORE-NON-GOALS-v2.md` — limites explicites du programme C00–C24 ;
- `docs/core/MODULE-ORDER-AND-DEFERRED-SURFACES.md` — ordre Core-first puis
  `M7 → M1 → M2 → M4 → M3 → M6 → M8 → M10 → M5 → M9` ;
- `.opsys/core-control/2.3.0/TASK-REGISTRY.jsonl` — 148 missions atomiques ;
- `.opsys/core-control/2.3.0/DEPENDENCY-GRAPH.json` — dépendances et
  parallélisme autorisé ;
- `.opsys/core-control/2.3.0/REPOSITORY-CONTRACT.md` — dépôt, owner et règles
  GitHub ;
- `.opsys/core-control/2.3.0/GITHUB-OPERATING-MODEL.md` — cycle des issues et
  preuves ;
- `docs/core/CI-REQUIRED-CHECKS.md` — checks Core attendus et frontière avec
  la protection de branche.

## Programme courant

Le programme actif construit et qualifie le Core avant toute complétion métier
M1–M10. Les modules peuvent faire l'objet de recherches et de plans candidats,
mais leur implémentation reste gelée jusqu'au handoff correspondant. Après
`CORE_RC_VERIFIED` et ratification humaine, les modules sont traités un par un,
en commençant par M7.

## Documents historiques ou produits distincts

Les fichiers suivants sont conservés pour provenance, mais ne gouvernent pas le
programme Core courant :

- `docs/GRS_Plan_Squelette_Maitre_v1.1_PERFECTION.pdf` ;
- `PACK_CONSENSUS_GRS_v2.md` ;
- `START_HERE.md` ;
- `PROMPT_BOOTSTRAP_CLAUDE_CODE.md` ;
- `VISION.md`, `FORGE_METHOD.md`, `IMPLEMENTATION_SPEC.md` et
  `RECONCILIATION.md`, qui décrivent un produit-méthode distinct.

Leur contenu ne doit pas être supprimé sans analyse de provenance. Toute
réactivation exige une ADR explicite et une réconciliation avec ce canon.
