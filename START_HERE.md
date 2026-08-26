# SUPERSEDED — START_HERE.md historique

> **Ne pas utiliser comme point de départ opérationnel.** Le programme actif est
> Core v2.3.0 ; commencer par `docs/core/CANON-INDEX.md`. Ce fichier est
> conservé uniquement pour provenance et migration des anciennes sessions.

# START_HERE.md — Démarrage

## Ordre d'invocation — PAS simultané (règle de la spec elle-même)

`IMPLEMENTATION_SPEC.md`, dernière ligne : « Ne pas paralléliser les adaptateurs avant que le
noyau et Claude Code soient réellement démontrés de bout en bout. » Donc, malgré les 4 fichiers
prêts dans les 4 IDE :

1. **Claude Code d'abord, seul.** Phase 0 (consolidation) → Phase 1 (noyau PROOF) → Phase 2
   (tranche verticale complète, DESIGN → DONE, avec reprise de session prouvée).
2. **Puis Cursor, Codex, GitHub Copilot** — seulement une fois la Phase 2 fermée avec preuve.

## Prompt universel (Claude Code / Cursor / Codex — coller tel quel)

```text
Lis AGENTS.md, puis les documents qu'il exige. Commence par la Phase 0 de
IMPLEMENTATION_SPEC.md. N'écris aucun code avant d'avoir produit l'état des lieux,
la matrice de capacités vérifiée et les décisions bloquantes.
```

## GitHub Copilot natif — pas pour démarrer

Le coding agent (assignation d'issue à `@copilot`) est conçu pour des tâches bien bornées de
backlog (bug fix, tests, petit refactor) — pas pour une phase de consolidation ouverte comme la
Phase 0. Ne l'utilise qu'une fois le pipeline prouvé sur Claude Code (étape 1 ci-dessus), sur une
story `T0`/`T1` claire, avec le manifeste `story_id`/`risk_tier`/`allowed_paths` dans le corps de
l'issue (voir `.github/copilot-instructions.md`).

## Avant de coller quoi que ce soit

1. Copier ce paquet à la racine du dépôt.
2. `cp config.ini.example .forge/config.ini` puis remplir les `model_id` (alias LiteLLM propres à
   ton infrastructure — non fournis ici, voir `RECONCILIATION.md`).
3. Ajouter la clé LiteLLM réelle via le mécanisme de coffre du système — jamais dans `config.ini`.
4. Ouvrir Claude Code à la racine du dépôt, coller le prompt universel ci-dessus.
