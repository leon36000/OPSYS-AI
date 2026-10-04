# AGENTS.md — OPSYS-AI v2

Instructions pour tout agent (Claude Code, Codex, Cursor, Copilot…) qui travaille dans ce dépôt.
Les instructions explicites actuelles du propriétaire priment sur les règles et documents anciens.
Lire [`docs/produit/DIRECTIVES-NATHAN.md`](docs/produit/DIRECTIVES-NATHAN.md) : réutiliser d'abord,
préserver la profondeur des départements, plusieurs agents configurables, autonomie sous permissions.

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
- Architecture : `docs/architecture/ARCHITECTURE.md`. Consolidation actuelle :
  `docs/programme/RESTRUCTURATION-2026-09-30.md` ; historique d'exécution : `docs/programme/PLAN.md`.

## Arborescence

| Chemin | Contenu |
|---|---|
| `src/opsys/` | Couche OPSYS : contrat d'outil, manifestes, politiques, capacités MCP (stdio/HTTP), approbations, tokens, paliers, passerelle LiteLLM, configuration OpenClaw, console, mémoire, CLI (adaptateur Hermes optionnel) |
| `departments/mNN-*/` | Départements : `department.yaml`, `SOUL.md`, `skills/`, `src/`, `tests/` (guide : `docs/architecture/DEPARTEMENTS.md`) |
| `core/` | OPSYS-CORE (TypeScript) : fork dur d'OpenClaw v2026.9.6, provenance `core/PROVENANCE.md` ; construit et testé en CI (`core.yml`) |
| `install/` | Installateur une commande (`install.sh`, `install.ps1`), désinstallation ; `docs/exploitation/INSTALLATION.md` |
| `deploy/` | Image, docker compose, `install.sh`, sauvegardes (option serveur) |
| `docs/` | Architecture, décisions, recherche (ingrédients), mémoire/RAG, exploitation, conformité Loi 25, plan maître |
| `tests/` | Tests du socle `opsys` |

## Commandes

```bash
python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev,postgres]"
pytest                               # socle (tests/)
pytest departments/m03-estimation    # un département
ruff check src tests                 # lint du socle
opsys-metier verifier                                    # manifestes, outils, dépendances
opsys-metier openclaw configurer --config-dir /tmp/oc   # fragments OpenClaw des départements
```

`opsys` est la commande du **core** (T0.7 lot 2, `openclaw` en est l'alias) ; la CLI du moteur Python est `opsys-metier`,
et `opsys metier <commande>` la lance depuis le core. Ne jamais redonner le nom `opsys` à un point d'entrée Python.
Une ancienne invocation (`opsys verifier`) ne fait rien : elle dit la nouvelle (`opsys metier verifier`).

## Principes (PROOF allégé)

- **Preuve avant livraison.** Indiquer périmètre, résultat, vérification et limites. Pour une
  fonctionnalité, tests pertinents + parcours démontré ; pour un document, cohérence + liens + diff.
  Une simulation n'est pas une preuve d'intégration réelle. Aucun « terminé » sans critères de sortie.
- **Preuves conservées.** Chaque exécution utilise des noms d'artefacts distincts. Ne jamais
  écraser un log, un JUnit ou un reçu antérieur, même rouge ; lier toute reprise à ses sources.
- **Le code calcule, le LLM orchestre.** Aucun prix, solde, score, date ou quantité produit par un
  modèle. Toujours par un outil déterministe testé.
- **Fail-closed.** Une donnée manquante produit un verdict qui dit quoi demander, jamais une valeur
  par défaut inventée.
- **Contrôles proportionnés.** Tests du comportement touché, lint des fichiers de code et
  `opsys-metier verifier` si manifestes/contrats changent ; CI applicable avant intégration.
  Argent, accès, rejeu, migrations et restauration exigent des vérifications négatives ciblées.
  Aucun consensus de trois modèles, autre fournisseur imposé ni attente d'un modèle extérieur.
  Une revue supplémentaire répond à un risque concret ; elle reste facultative (ADR-0012).
- **Frontières humaines (T3).** Paiements, secrets de production, suppression définitive de
  données, publication ou déploiement public, engagements externes : humain seul.

## Interdits

- Stubs dans `src/` (`pass`, `...`, `NotImplementedError` en corps de fonction).
- Présenter un TODO, un mock ou un squelette comme une capacité livrée. Les tâches incomplètes
  sont suivies explicitement ; un TODO/FIXME relié au plan est permis.
- Test sans assertion, `assert True`.
- Données inventées (les fixtures portent `fictif: true`).
- Secret dans git, `--no-verify`, commit direct ou force-push sur `main`.
- Ajouter à `core/` du code d'une autre source sans licence vérifiée ni trace dans `core/PROVENANCE.md`.

## Briques open source

Réutiliser plutôt que réécrire : c'est le premier chemin à examiner, pas une étape facultative
après développement. Inspecter l'existant puis rechercher GitHub **et** GitLab pour les capacités
importantes. Les briques sont des ingrédients à adapter, pas à empiler.
- Avant d'adopter une brique :
  - vérifier sa licence dans son fichier `LICENSE` ;
  - qualifier commit/version, dépendances/poids, maintenance, tests, données et coût d'adaptation ;
  - l'inscrire dans `docs/research/INGREDIENTS.md`, puis prouver son intégration métier.
- MIT/Apache/BSD : respecter avis, attribution et obligations de redistribution ; MPL : obligations
  sur les fichiers concernés. Vérifier aussi les sous-dossiers Enterprise et licences des modèles.
- LGPL : OK en dépendance dynamique.
- GPL/AGPL : service séparé non modifié uniquement.
- BSL, Elastic, SSPL : refus sauf décision humaine.

## Économie de tokens (pour les agents qui codent ici aussi)

- Lire le minimum : `rg` ciblé, lectures partielles.
- Pas de relecture de fichiers déjà en contexte.
- Sorties courtes.
- Déléguer les recherches larges à un sous-agent qui ne rend que la conclusion.
- Déclencher les agents utiles sur événements, réutiliser les résultats et limiter contexte,
  outils, tours, retries et concurrence. Mesurer coût/qualité par parcours ; pas de débat permanent.
- Mémoire de projet : directives, décisions, plans, erreurs et preuves dans Git ; M10 doit aussi
  gérer le domaine développement, isolé des données d'affaires (ADR-0012). Aucun secret en mémoire.

## Git

- Branche + PR.
- Le job CI `gates` est requis sur `main`.
- Messages de commit en français, décrivant le pourquoi.
- Préparer les changements localement. Commit, push, merge, publication et déploiement suivent
  l'autorisation explicite de la session ; la boucle de travail ne les autorise pas à elle seule.
