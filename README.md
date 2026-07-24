# OPSYS-AI / Systèmes complets d'automatisation d'entreprise par intelligence artificielle

Core d'entreprise autonome, clé en main. Ce repo exécute la méthode **PROOF STACK v1.1** (kit `GRS_KIT_DEMARRAGE_v1.0`, ratifié D-039). Source de vérité : le plan maître `docs/GRS_Plan_Squelette_Maitre_v1.1_PERFECTION.pdf`.

## Profils d'installation (D-043)

- **infra-existante** : branchement sur passerelle LLM, Langfuse, base vectorielle et PostgreSQL fournis par l'hôte.
- **starter** : auto-déploiement des prérequis en conteneurs (à venir en Phase 0/P0-2).

## Démarrage

Le repo est déjà câblé, `main` est protégée. Ordre d'exécution :

1. Phase C — consensus outillé (`python3 scripts/consensus_run.py --mock`, puis mode live après configuration de la passerelle et rotation de la clef).
2. Phase 0 — dans l'ordre v1.1 (P0-1 → P0-4 → P0-2 → P0-3/P0-6 → tests des scripts de méthode → harnais e2e → … → P0-10).
3. Story pilote **M7-S000** (mode ombre, ≤ 1 h).
4. M7 vague 1 — fondations sans dépendances.

Suivre `PROMPT_BOOTSTRAP_CLAUDE_CODE.md` sans sauter d'étape.

## Sources de vérité

- Plan maître : `docs/GRS_Plan_Squelette_Maitre_v1.1_PERFECTION.pdf` (28 p., nom historique GRS).
- Pack Phase C : `PACK_CONSENSUS_GRS_v2.md`.
- Constitution d'exécution : `00-DIGEST.md` + `docs/canon/REGLES.md`.

## ForgeAI PROOF IDE System

Les fichiers `VISION.md`, `FORGE_METHOD.md`, `IMPLEMENTATION_SPEC.md`, `RECONCILIATION.md`, `START_HERE.md` et `config.ini.example` présents à la racine sont le référentiel d'un **produit-méthode distinct** (chantier séparé). Ils ne gouvernent pas l'exécution de ce repo, qui suit PROOF STACK v1.1 du kit (cf. ADR-0002).

## Licence

Apache-2.0

