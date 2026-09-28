# AGENTS.md — OPSYS-AI v2

Instructions pour tout agent (Claude Code, Codex, Cursor, Copilot…) qui travaille dans ce dépôt.

## Le produit

OPSYS-AI (anciennement GRS) est un système d'exploitation d'entreprise piloté par IA : dix
départements virtuels qui opèrent sur une seule vérité partagée. Premier client : Gouttières et
Revêtements Synergy (rénovation extérieure, Québec) ; ensuite, SaaS pour PME québécoises.
- **Le QUOI fait foi dans [`docs/produit/DEFINITION-PRODUIT.md`](docs/produit/DEFINITION-PRODUIT.md).**
  Lire §1, §5, §6 et la section du département (§7) avant toute livraison.
- **Test de dérive** : un livrable qui pourrait décrire n'importe quelle entreprise, sans leads,
  soumissions, chantiers, équipes, factures ou matériaux, est de l'infrastructure. Retour à §1.
- OPSYS-CORE = **fork dur d'OpenClaw**, renommé, sans dépendance aux mises à jour amont (ADR-0008).
- L'app mobile (4 profils, hors ligne d'abord) est un pilier du produit, pas un complément (§9).
- Architecture : `docs/architecture/ARCHITECTURE.md`. Plan d'exécution : `docs/programme/PLAN.md`.

## Arborescence

| Chemin | Contenu |
|---|---|
| `src/opsys/` | Couche OPSYS : contrat d'outil, manifestes, politiques, capacités MCP (stdio/HTTP), approbations, tokens, paliers, passerelle LiteLLM, configuration OpenClaw, console, mémoire, CLI (adaptateur Hermes optionnel) |
| `departments/mNN-*/` | Départements : `department.yaml`, `SOUL.md`, `skills/`, `src/`, `tests/` (guide : `docs/architecture/DEPARTEMENTS.md`) |
| `core/` | OPSYS-CORE (TypeScript) : fork dur d'OpenClaw v2026.9.6, provenance `core/PROVENANCE.md` ; construit et testé en CI (`core.yml`) |
| `deploy/` | Image, docker compose, `install.sh`, sauvegardes |
| `docs/` | Architecture, décisions, recherche (ingrédients), mémoire/RAG, exploitation, conformité Loi 25, plan maître |
| `tests/` | Tests du socle `opsys` |

## Commandes

```bash
python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev,postgres]"
pytest                               # socle (tests/)
pytest departments/m03-estimation    # un département
ruff check src tests                 # lint du socle
opsys verifier                       # manifestes, outils, dépendances
opsys openclaw configurer --config-dir /tmp/oc   # fragments OpenClaw des départements
```

## Principes (PROOF allégé)

- **Preuve avant DONE.** DONE = tests verts + commande de démonstration exécutée. Sinon
  `BLOCKED: <raison>`. Jamais de faux vert.
- **Le code calcule, le LLM orchestre.** Aucun prix, solde, score, date ou quantité produit par un
  modèle. Toujours par un outil déterministe testé.
- **Fail-closed.** Une donnée manquante produit un verdict qui dit quoi demander, jamais une valeur
  par défaut inventée.
- **La CI est l'autorité.** Tests, lint, `opsys verifier`. Revue de PR par un humain ou par un
  modèle d'un autre fournisseur que l'auteur pour le code critique (M5, politiques, approbations).
- **Frontières humaines (T3).** Paiements, secrets de production, suppression définitive de
  données, publication ou déploiement public, engagements externes : humain seul.

## Interdits

- Stubs dans `src/` (`pass`, `...`, `NotImplementedError` en corps de fonction).
- TODO/FIXME dans un diff.
- Test sans assertion, `assert True`.
- Données inventées (les fixtures portent `fictif: true`).
- Secret dans git, `--no-verify`, commit direct ou force-push sur `main`.
- Ajouter à `core/` du code d'une autre source sans licence vérifiée ni trace dans `core/PROVENANCE.md`.

## Briques open source

Réutiliser plutôt que réécrire. Les briques sont des ingrédients à adapter, pas à empiler.
- Avant d'adopter une brique :
  - vérifier sa licence dans son fichier `LICENSE` ;
  - l'inscrire dans `docs/research/INGREDIENTS.md`.
- MIT/Apache/BSD/MPL : OK.
- LGPL : OK en dépendance dynamique.
- GPL/AGPL : service séparé non modifié uniquement.
- BSL, Elastic, SSPL : refus sauf décision humaine.

## Économie de tokens (pour les agents qui codent ici aussi)

- Lire le minimum : `rg` ciblé, lectures partielles.
- Pas de relecture de fichiers déjà en contexte.
- Sorties courtes.
- Déléguer les recherches larges à un sous-agent qui ne rend que la conclusion.

## Git

- Branche + PR.
- Le job CI `gates` est requis sur `main`.
- Messages de commit en français, décrivant le pourquoi.
