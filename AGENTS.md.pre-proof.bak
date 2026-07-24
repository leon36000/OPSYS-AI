# AGENTS.md — ForgeAI PROOF IDE System

**Statut :** conception consolidée, avant implémentation  
**Autorité humaine :** Nathan  
**Sorties autorisées :** `DONE`, `BLOCKED`, `REOPENED`, `CANCELLED`

## Lecture obligatoire

Avant toute proposition ou modification, lire :

1. `VISION.md`
2. `FORGE_METHOD.md`
3. `IMPLEMENTATION_SPEC.md`
4. `config.ini.example`

Ne code pas si ces fichiers sont absents, contradictoires ou non approuvés pour la phase courante.

## Produit

Nous construisons un système intégré à Claude Code, Codex, Cursor et VS Code/Copilot qui applique automatiquement :

- PROOF pour la gouvernance et les preuves;
- Forge Design, inspiré de BMAD mais sans framework BMAD;
- le framework Superpowers réel, modifié par ForgeAI;
- des mini-agents automatiques;
- Headroom et LLMLingua-2 pour le contexte;
- DSPy et GEPA dans un laboratoire contrôlé;
- un mode autonome et un mode LiteLLM connecté.

ForgeAI Toolkit reste un produit distinct.

## Règle fondamentale

La conversation n'est jamais la mémoire du projet. Stories, claims, décisions, context manifests, état et preuves vivent dans des artefacts structurés et versionnés.

## Préflight avant écriture

Confirmer :

- story, objectif et critères;
- tier T0-T3;
- claim, branche et worktree;
- dépendances;
- code existant et travail similaire recherchés;
- chemins autorisés;
- tests et preuves attendus;
- contexte critique chargé.

Un élément manquant = `BLOCKED` avant écriture.

## Pipeline obligatoire

```text
CALIBRATE → DESIGN → SPEC → STORY → CLAIM → CONTEXT → RED
→ IMPLEMENT → VERIFY → REVIEW → TALLY → APPROVE → MERGE
→ LEDGER → DONE
```

Aucune étape ne peut être sautée silencieusement.

## Mini-agents automatiques

- `forge-context-scout` : zone inconnue ou reprise;
- `forge-design-analyst` : besoin ambigu ou non trivial;
- `forge-architect` : structure, schéma, interface ou T2;
- `forge-hard-coder` : tâche difficile, longue ou multi-fichiers;
- `forge-test-runner` : après modification;
- `forge-drift-checker` : après compactage et avant merge;
- `forge-docs-canon` : après changement fonctionnel ou documentaire;
- `forge-security-reviewer` : auth, secrets, réseau, T2/T3;
- reviewers indépendants : avant approbation;
- `forge-evidence-synthesizer` : avant `DONE`.

Ne simule jamais une délégation non exécutée.

## Modèles

Les rôles sont des alias configurables. Profil interne déclaré (roster complet — voir
RECONCILIATION.md pour la traçabilité de chaque assignation) :

- architecte : GLM-5.2;
- code compliqué/long/1M ctx : Kimi K3;
- code facile/standard : Kimi Code 2.7;
- documentation/canon : Gemini Flash 3.6, proposition uniquement (ne pas sous-estimer);
- reviewer 1 : DeepSeek V4 Pro;
- reviewer 2 : Gemini 3.1 Pro;
- reviewer 3 / sécurité : LongCat 2.0;
- sentinelle (tandem) : DeepSeek V4 Pro + GLM-5.2;
- parallélisme/worktrees : Grok 4.5 (double rôle possible avec Cursor natif — CIV);
- synthèse de preuves : MiMo 2.5 Pro;
- pool rotation : Kimi, Qwen 3.7 Max, MiMo 2.5 Pro, MiniMax M3;
- autres rôles : modèles configurés et vérifiés par vendor.

Aucun identifiant de modèle en dur dans le noyau. Aucune indépendance multi-vendor sans preuve de routage.

## Contexte

Le contexte est rare. Ne jamais compresser avec perte : canon, règles, story, critères, code, diff, tests, erreurs exactes, reviews, verdicts et preuves.

Headroom cible d'abord sorties d'outils et logs. LLMLingua-2 cible seulement les documents longs autorisés. Pas de double compression sans benchmark.

## Superpowers

Utiliser le framework Superpowers réel. Conserver les parties utiles; remplacer ou renforcer le routage, l'auto-review, la propagation des règles, les context packs, les hooks, les gates et les preuves. Toute modification amont est isolée, testée et réversible.

## DSPy et GEPA

Ils proposent des optimisations testées. Ils ne modifient jamais automatiquement canon, invariants, gates, critères `DONE`, T3 ou indépendance. Aucune promotion sans benchmark, holdout, revue, canary et rollback.

## Interdits

- commit direct sur la branche principale ou `--no-verify`;
- stub ou marqueur de travail inachevé destiné au merge;
- test sans assertion utile;
- donnée inventée présentée comme réelle;
- modification hors story;
- secret dans Git, prompt, log ou diagnostic;
- auto-review présentée comme indépendante;
- `DONE` sans preuve;
- modification silencieuse du canon;
- second orchestrateur concurrent.

## Sorties

Pour `DONE`, fournir critères, commandes, codes de sortie, tests, gates, diff/commit, reviews, preuves/hashes, état docs/canon et risques résiduels.

Pour `BLOCKED`, fournir cause exacte, preuve, impact, prochaine action minimale et décision humaine requise.

## Ordre immédiat

1. valider les documents;
2. vérifier les capacités réelles;
3. construire PROOF Core;
4. prouver une tranche verticale Claude Code;
5. intégrer LiteLLM et Superpowers;
6. ajouter Context Plane;
7. porter vers Codex, Cursor et VS Code/Copilot;
8. ajouter DSPy/GEPA après les benchmarks de référence.

**Échoue fermé plutôt que dériver silencieusement.**
