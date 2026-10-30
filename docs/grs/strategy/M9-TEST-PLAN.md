# M9 — plan de test par couche

Statut : **PARTIAL** (couches pure, intégration, console HTTP, navigateur et évaluation vérifiées en processus ;
PostgreSQL des nouveaux registres, MCP séparé, Core/VPS et appareil mobile non exécutés).
[Architecture M9](M9-STRATEGIC-INTELLIGENCE-ARCHITECTURE.md) · [évaluation](M9-EVAL-TRUST-LAYER.md) ·
[rapport de livraison](../../reprise/M9-COMPLETION-20261028/RAPPORT.md) · [table d'audit](M9-AUDIT-INITIAL-QUADRUPLE-A.md).

## Objectif

Dire, pour quelqu'un qui reprend M9, quoi lancer, dans quel ordre, ce que chaque couche prouve, et où sont conservées les
preuves déjà produites.

## Pourquoi

AGENTS.md exige preuve avant livraison, preuves conservées sous des noms distincts et vérifications négatives ciblées
(accès, rejeu). Une simulation n'est pas une intégration réelle : chaque couche dit ce qu'elle ne couvre pas.

## État actuel

| Couche | Ce qui est prouvé | Où |
|---|---|---|
| Pure | modules sans `opsys`, sans horloge ni réseau ; règles, refus `REJ-…`, chaînes altérées | `departments/m09-strategic-intelligence/tests/` |
| Intégration | vrais producteurs par le port privé, vraie file d'approbation, SQLite, identités et rôles relus | `tests/test_m9_*.py`, `tests/test_lecteurs_m9.py`, `tests/test_portees_appareil.py` |
| Console HTTP | pages `/direction`, sécurité, CSRF, idempotence, échappement | `tests/test_console_direction_m9.py`, `tests/test_console_*_m9.py` |
| Navigateur | Chromium réel, bureau et 390 px | `preuves-navigateur/` |
| Conseil réel | vraies sorties de modèle admises ou refusées par le code | `preuves-conseil-reel/` |
| Évaluation | 61 cas à attentes indépendantes, Wilson 95 % | `test_evaluation.py`, `preuves-evaluation/` |
| CI | jobs `departement` (m09), `socle`, `frontiere-postgresql`, `gates` | `.github/workflows/ci.yml` |

Dernières exécutions archivées (JUnit) : `final-m9` 1 445 tests, puis `final2-m9` sur le SHA `f258a344` 1 456 tests,
0 échec, 0 ignoré ; CI verte sur `7a0a01d9` (PR draft #859) selon le rapport de livraison. `tests/test_m9_e2e_cahier.py` (six parcours du cahier) existe et passe dans l'arbre de
travail du 29 octobre ; il n'est pas encore commité.

## Architecture

- Couche pure : fixtures fictives construites en mémoire ; garde `test_conformite.py` (horloge interne, aléa non
  ensemencé, réseau interdit, littéral de coût, aucune cause signalée) ; `test_module_structure.py`.
- Intégration : base SQLite privée par test (`stockage.ENV_URL`), départements chargés par `charger_departements()`,
  `Capacites` filtrées ; chaque test refait au moins un refus (agent, vendeur, rôle retiré, chaîne falsifiée).
- Garde statique d'accès : `tests/test_m9_acces_strict.py` (AST : chaque outil des modules `outils_*` appelle
  `exiger_admin_strict` ; `outils.py` garde `_exiger_admin_pour_appareil`).
- Console : client HTTP de test, session réelle, jeton CSRF, mesure des registres avant et après pour prouver l'absence
  d'écriture.

## Fichiers

Tests du département (60 fichiers `test_*.py`), tests d'intégration et de console listés ci-dessus,
[ci.yml](../../../.github/workflows/ci.yml), preuves sous
[preuves-execution/](../../reprise/M9-COMPLETION-20261028/preuves-execution/index-executions.txt).

## Outils et pages de console

Tous les outils M9 sont appelés par `Capacites.appeler` dans les tests d'intégration ; toutes les pages `/direction/*`
par le client HTTP ; le tableau, les plans et six autres pages par le navigateur.

## Données et registres

Aucune donnée réelle : fixtures fictives (`FICTIF = True`), comptes `admin.fictif`, `vendeur.fictif`… ; chaque exécution
a son propre `HOME`, `OPSYS_HOME` et sa base.

## Workflows

Commandes exactes (depuis la racine, environnement `pip install -e ".[dev,postgres]"`) :

```bash
python -m pytest departments/m09-strategic-intelligence/tests -q --import-mode=importlib -p no:cacheprovider
ruff check src tests departments/m09-strategic-intelligence
opsys-metier verifier
pytest -p no:cacheprovider tests/test_m9_acces_strict.py tests/test_m9_gouvernance.py tests/test_m9_radars_integre.py \
  tests/test_m9_veille_integre.py tests/test_m9_playbooks_integre.py tests/test_m9_plans_integre.py \
  tests/test_m9_actions_integre.py tests/test_m9_memoire_integre.py tests/test_m9_contrat_mobile_admin.py \
  tests/test_m9_direction_integre.py tests/test_lecteurs_m9.py tests/test_portees_appareil.py -q
pytest -p no:cacheprovider tests/test_console_direction_m9.py tests/test_console_suivis_m9.py -q
pytest -p no:cacheprovider tests/test_m9_e2e_cahier.py -q
M9_EVAL_SORTIE=<nouveau-fichier>.json pytest -p no:cacheprovider \
  departments/m09-strategic-intelligence/tests/test_evaluation.py -q -k latence
```

La commande complète de l'exécution `final2-m9` (toutes les suites M9 et voisines) est dans
`preuves-execution/cmd-final2-m9-20261029T035103Z.txt`. Exécutions de la mission : sous `taskset` 2 CPU, `ulimit -v`
6 Gio, `HOME`/`OPSYS_HOME` privés, JUnit et log nommés par étiquette et horodatage.

Navigateur : `QA_DIR=<dossier neuf> python M9-21-serveur-qa-….py` (affiche `PRET`, serveur local 127.0.0.1:8765),
puis `QA_DIR=… node M9-21-qa-….js` (Playwright Chromium), puis créer `$QA_DIR/stop`. Le script serveur et le script
navigateur portent des chemins codés en dur (`/home/user/OPSYS-AI-m9`, `/opt/node-tools`) : à adapter avant reprise.

## Intégrations

Producteurs M1–M8 et M10 réels dans les tests d'intégration ; file `approbations` du socle ; console OPSYS. Core
(`core/`) n'est pas exécuté dans le bac à sable : il se construit et se teste en CI (`core.yml`).

## Risques

- PostgreSQL : la CI `frontiere-postgresql` couvre `tests/e2e/test_m9_snapshot_concurrent.py` et
  `tests/e2e/test_m9_ingestion_concurrent.py` (registres historiques) ; les tests d'intégration M9 fixent eux-mêmes
  `stockage.ENV_URL` sur SQLite : aucun test repéré n'exerce les nouveaux registres (`captures_strategiques`, `plans`,
  `actions`, `veille`…) sur PostgreSQL.
- Régression console élargie : 46 échecs de fusion PDF/AP, identiques sur la base sans changement (conservés, hors M9).
- Le corpus d'évaluation et la plupart des tests sont écrits par la même mission que le code.

## Gates Nathan

Qualification installée (VPS/Core), planification réelle (M9.5), tests sur appareil (M9.22).

## Tests

Ce document est lui-même le plan ; les fichiers cités ci-dessus sont les tests. Vérification de cette rédaction : e2e,
accès strict et tests purs des radars, veille, playbooks, plans, orchestrateur, mémoire et évaluation relancés
(205 verts), puis intégration et console des mêmes modules (verts), le 29 octobre 2026, sans écrire dans le dépôt.

## Statut

PARTIAL : couches locales prouvées ; PostgreSQL des nouveaux registres, MCP séparé, Core/VPS et mobile non exécutés.

## Prochaines étapes

1. Commiter `tests/test_m9_e2e_cahier.py` et l'ajouter à la commande d'intégration de référence.
2. Ajouter un test PostgreSQL de concurrence sur `rang_attendu` pour `plans` et `actions`.
3. Paramétrer les chemins des scripts navigateur et rejouer la QA avec le panneau « Indicateurs exécutifs ».
