# M9 — architecture d'ensemble de la Direction IA

Statut : **PARTIAL** (module pris dans son ensemble ; statut de chaque sous-module dans la
[table d'audit](M9-AUDIT-INITIAL-QUADRUPLE-A.md) §3). Reprise : [rapport de livraison](../../reprise/M9-COMPLETION-20261028/RAPPORT.md).

## Objectif

Donner à Nathan (admin) une lecture de direction de l'entreprise bâtie uniquement sur ce que les départements
propriétaires (M1–M8, M10) exposent : sources, couverture, risques, scénarios, revues, décisions et suites. M9 lit,
relie, cite et propose ; il ne calcule pas à la place d'un propriétaire, ne décide pas et n'exécute aucune action.

## Pourquoi

Le cahier d'origine décrivait M9 pour l'ancien dépôt (routes `/api/strategy/*`, tables `strategic_*`, LangGraph).
OPSYS-AI a déjà un contrat d'outil, une file d'approbation native, un stockage chaîné commun et une console : M9 les
réutilise (ADR-0012) au lieu d'empiler un second moteur. Règle dure : le code calcule, le modèle explique ; une donnée
absente produit un manque nommé, jamais une valeur.

## État actuel

- 74 outils déclarés (`outils*.py`) ; 16 routes de console sur 15 chemins sous `/direction`.
- 15 lignes de la matrice sont `DONE_VERIFIED` ; M9.3, 8, 9, 11, 18 restent partielles, M9.4 à durcir (jonction Core),
  M9.5 bloquée par l'hôte opérateur, M9.22 (mobile) reportée à la phase mobile.
- Vérifié en processus (SQLite, producteurs réels appelés par le port privé, HTTP console, navigateur) ; PostgreSQL,
  Core et VPS non exécutés dans le bac à sable (voir le rapport de livraison).

## Architecture

Couches, de bas en haut :

1. **Port privé de lecture** (`src/opsys/lecteurs_m9.py`) : liste blanche `LECTURES_AUTORISEES` de 19 outils T0/N0
   chez M1, M2, M3, M4, M5, M6, M7, M8 et M10 ; appelant = admin authentifié (console ou appareil), rôle relu en base à
   chaque lecture ; l'appel est attribué à M9 et chaque producteur revérifie ses propres portées. Le catalogue pur
   `catalogue_producteurs` reproduit cette liste ; `tests/test_lecteurs_m9.py` impose l'égalité.
2. **Registres chaînés** (`opsys.stockage.maillons`, SQLite/PostgreSQL) : append-only, hash chaîné, `rang_attendu`
   pour la concurrence ; une chaîne altérée est refusée (`REJ-…-CHAINE-INVALIDE`) avant toute lecture.
3. **Modules purs** (ADR-0009) : aucun import d'`opsys`, aucune horloge ; chaque instant est fourni par l'appelant.
   `conformite.py` porte les gardes (dont `HORLOGE_INTERNE`) vérifiées par `test_conformite.py`.
4. **Adaptateurs d'outils** (`outils_*.py`) : lisent les registres, vérifient l'identité, bornent la sortie sous
   `BUDGET_SORTIE` (limite du socle `jetons.LIMITE_SORTIE_DEFAUT` moins une réserve) ; ce qui ne tient pas se pagine.
5. **Port privé d'actions** (`src/opsys/actions_m9.py`) : `proposer` dépose une demande `en_attente` dans la file
   `approbations` pour une liste blanche `ACTIONS_AUTORISEES` (M2, M4, M10 ; outils T1 de niveau N3 ou plus), avec les
   arguments exacts validés ; `lire` rend l'état natif sans les arguments en clair. M9 n'exécute jamais.
6. **Console** (`src/opsys/console/direction_ui.py`) : pages HTML admin, presque toutes en lecture ; deux commandes
   internes (suivi et annulation de plan) avec CSRF, corps borné et `mutation_id` idempotent.

Identité : les outils des modules récents appellent `exiger_admin_strict` (admin humain seulement, agent refusé) ; la
plupart des outils historiques de `outils.py` (état consolidé, briefing, suivis, rapports de période) appellent
`_exiger_admin_pour_appareil`, qui conserve la voie agent sans identité d'appareil ; les deux outils d'approbation
passent par `opsys.approbations_appareil`. Aucun droit n'est élargi.

## Fichiers

Carte des modules (`departments/m09-strategic-intelligence/src/m9_strategic_intelligence/`) :

| Sous-module | Modules purs | Outils |
|---|---|---|
| M9.1 tissu de données | `capture_strategique`, `catalogue_producteurs`, `dossier_strategique` | `outils_tissu`, `outils_conseil` |
| M9.2 graphe d'impacts | `graphe_impacts`, `relations_catalogue` | `outils_graphe` |
| M9.3 couche sémantique | `semantique_metriques`, `metriques_executives` | `outils_semantique`, `outils_metriques_executives` |
| M9.4 conseil | `conseil`, `sessions_conseil`, `audit_affirmations` | `outils_conseil`, `outils` |
| M9.5–7 direction | `briefing_matin`, `revue_periodique`, `rapport_direction`, `risques` | `outils`, `outils_direction` |
| M9.8 scénarios | `scenarios`, `question_scenario` | `outils_conseil`, `outils_questions_scenario` |
| M9.9 prévisions | `previsions`, `tendances` | `outils_previsions`, `outils_tendances` |
| M9.10 décision | `decision_cadrage`, `rapport_decision_v2`, `memoire_m10` | `outils_cadrage_decision`, `outils_memoire` |
| M9.11–18 | `priorisation`, `occasions`, `veille`, `playbooks`, `plans`, `orchestrateur`, `experiences` | `outils_priorites`, `outils_radars`, `outils_veille`, `outils_playbooks`, `outils_plans`, `outils_actions`, `outils_experiences` |

Raccords communs : [lecteurs_m9.py](../../../src/opsys/lecteurs_m9.py), [actions_m9.py](../../../src/opsys/actions_m9.py),
[direction_ui.py](../../../src/opsys/console/direction_ui.py). Assemblage : `outils.outils()` concatène toutes les fabriques.

## Outils et pages de console

Pas de route REST `/api/strategy/*`. Pages (admin seulement, `prefixe` de la console) : `/direction`,
`/direction/risques`, `/direction/sources`, `/direction/plans` (+ POST `/plans/suivi`, `/plans/annuler`),
`/direction/actions`, `/direction/conseil` (hors barre de navigation), `/direction/revues`, `/direction/revue`,
`/direction/veille`, `/direction/indicateurs`, `/direction/decision`, `/direction/tendances`, `/direction/scenarios`
(GET + POST). Chaque panneau appelle un outil par `metier.executer` et affiche le code `REJ-…` d'un refus. La décision
d'une action passe par la file native `/approbations`.

## Données et registres

Registres du département `m09-strategic-intelligence` : `captures_strategiques`, `sessions_conseil`,
`publications_revue`, `actions`, `plans`, `experiences`, `veille` ; historiques : `snapshots`, `alertes_m8`,
`suivi_decisions`, `clotures_suivi_decisions`. Radars, scénarios, prévisions et graphes sont recalculés à la demande,
jamais stockés comme vérité. Aucune donnée réelle d'entreprise dans le dépôt : fixtures fictives seulement.

## Workflows

Capture (port privé) → couverture et dossier → graphe, indicateurs, radars, scénarios, prévisions → conseil (tours
déposés par le runtime) → rapport de décision v2 → action proposée à la file native → décision humaine → réconciliation.
En parallèle : salle de guerre et briefing (lecture), revues publiées en versions immuables.

## Intégrations

Lecture : 19 outils producteurs (dont `m10_statut_decision`, `m10_paquet_contexte_affaire`). Bus : `m8.alerte_proposee`,
`m8.snapshot_chantier`. Écriture proposée seulement : `m2_preparer_relance`, `m2_reassigner_lead`,
`m4_planifier_intervention`, `m4_creer_demande_ecart`, `m10_journaliser_decision`. Admission de budget :
`opsys.admission_agents` (réservations réconciliées des tours de conseil).

## Risques

- Toute la profondeur dépend des lectures exposées par les producteurs ; une lecture absente n'est jamais remplacée.
- Le bac à sable n'exécute pas `core/` : la jonction Core du conseil et la planification ne sont pas qualifiées.
- Validité sémantique non prouvée : une citation exacte prouve la correspondance au texte, pas le raisonnement.
- Deux régimes d'identité coexistent (strict et historique) : tout nouvel outil doit choisir explicitement.

## Gates Nathan

Liste des 21 sections retenue par délégation (révisable) ; planification quotidienne par l'hôte opérateur ; lien
registre ↔ mesures chez M8 ; prévisions et capacité chez leurs propriétaires ; écran mobile (phase mobile).

## Tests

Département : `departments/m09-strategic-intelligence/tests/` (dont `test_module_structure.py`, `test_conformite.py`).
Intégration : `tests/test_m9_*.py`, `tests/test_lecteurs_m9.py`, `tests/test_console_direction_m9.py`.
Dernière exécution archivée : 1 445 tests verts (rapport de livraison, `preuves-execution/`).

## Statut

PARTIAL : architecture en place et vérifiée en processus ; lignes ouvertes listées ci-dessus. M9 n'est pas complet.

## Prochaines étapes

1. Qualifier en CI/VPS la jonction Core du conseil et la planification (hôte opérateur).
2. Obtenir des producteurs les lectures manquantes (capacité M4, prévisions M2/M4/M6, coûts M5/M7).
3. Décider chez M8 du lien registre ↔ définitions ; réviser au besoin la liste des 21 sections.
