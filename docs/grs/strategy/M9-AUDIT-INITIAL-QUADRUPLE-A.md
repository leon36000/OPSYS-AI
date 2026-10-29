# M9 — audit d'adaptation du cahier « Intelligence stratégique » (version du 9 juin 2026)

> Le cahier d'origine (« GRS M9 — Intelligence stratégique, Direction IA… », 2026-06-09) décrit M9 pour l'ancien dépôt
> Forge/GRS/Andromeda (`grs_api/modules/module9_intelligence/…`, `dept_financier.py`, routes `/api/strategy/*`, LangGraph,
> n8n…). Ce document le **traduit en OPSYS-AI réel**, sans retirer aucune fonctionnalité : chaque exigence est soit livrée,
> soit adaptée avec la raison, soit ouverte avec son gate. Direction durable : `docs/produit/DIRECTIVES-NATHAN.md` et
> ADR-0012 (réutiliser d'abord, ne pas empiler les frameworks).

## 1. Réponses aux quinze questions d'audit du cahier

| # | Question | Réponse (état OPSYS-AI actuel) |
|---|---|---|
| 1 | Où est M9 ? | `departments/m09-strategic-intelligence/` (modules `src/m9_strategic_intelligence/`, tests, évaluations, contrats, métriques) ; raccords communs `src/opsys/actions_m9.py`, `src/opsys/lecteurs_m9.py` ; console `src/opsys/console/direction_ui.py`. |
| 2 | Que contient `dept_financier.py` ? | Ce fichier n'existe pas dans OPSYS-AI : il appartenait à l'ancien dépôt. Le M9 d'OPSYS-AI était un harnais pur de 813 lignes (audit du 28 sept. 2026, `docs/departements/M9-audit.md`) ; il compte aujourd'hui plus de 16 000 lignes de code et plus de 80 modules. |
| 3 | Existe-t-il `module7_strategie` ? | Non, notion de l'ancien dépôt. La stratégie transversale est portée par les modules M9.1–M9.23 ci-dessous. |
| 4 | Quelles routes existent ? | Pas de routes REST `/api/strategy/*` : OPSYS expose ses capacités en **outils** (contrat d'outil, MCP/Core) — plus de 70 outils M9, tous `admin` strict — et en **pages de console** `/direction/*` (admin seulement). Table de correspondance au §3. |
| 5 | Quels modèles de base de données ? | Pas de dix-huit tables `strategic_*` : des **registres chaînés append-only** (hash, rang attendu) sur le stockage commun SQLite/PostgreSQL (`opsys.stockage`) : captures, sessions de conseil, publications de revue, veille, actions, plans, expériences. §4. |
| 6 | Quels tests ? | Département : plus de 60 fichiers de tests ; socle : tests d'intégration `tests/test_m9_*.py` et console `tests/test_console_*m9.py`. Chiffres exacts dans `RAPPORT.md` du dossier de reprise. |
| 7 | Quelles intégrations M1–M8 ? | 19 lectures T0/N0 de producteurs par un port privé en lecture (`lecteurs_m9`), liste blanche : M1, M2, M3, M4, M5, M6, M7, M8, M10. |
| 8 | M10 est-il appelé ? | Oui : lecture (`m10.statut_decision`, `m10.paquet_affaire`) et écriture **proposée** par la file d'approbation native (`m10_journaliser_decision`), vérifiée sans mémoire fantôme (M9.20). |
| 9 | Un rapport hebdo existe-t-il ? | Oui : revue hebdomadaire/mensuelle/trimestrielle publiée en versions immuables, avec les **vingt sections de direction** (M9.6–7). |
| 10 | Des projections existent-elles ? | Oui : prévisions des propriétaires consolidées (M9.9), tendances extrapolées par le code (`m9_projeter_tendance`) et scénarios (19 chocs). |
| 11 | Quelles données sont disponibles ? | Uniquement ce que les producteurs exposent par leurs lectures autorisées. Aucune donnée réelle d'entreprise dans le dépôt ; tous les tests utilisent des fixtures fictives. |
| 12 | Quelles données sont périmées ? | Dites par la couverture (âge, fraîcheur attendue M8, péremption demandée) ; une lecture absente, refusée, partielle ou contradictoire n'est jamais citée. |
| 13 | Quels risques techniques ? | §6. |
| 14 | Quels gates Nathan ? | §7. |
| 15 | Quelle phase minimale ? | Les phases 0 à 12 du cahier sont livrées (§5), sauf les gates nommés. |

## 2. Décisions d'adaptation transversales

| Cahier | Réalité OPSYS-AI | Pourquoi |
|---|---|---|
| LangGraph, Temporal, Prefect/Dagster, CrewAI, AutoGen, ADK, Semantic Kernel | Orchestration par les **registres chaînés**, la **file d'approbation native** et le runtime Core (fork OpenClaw, ADR-0008) ; workflows déterministes en Python pur | ADR-0012 : « une brique est un ingrédient à adapter, pas à empiler » ; un second moteur d'orchestration Python doublerait Core |
| Langfuse, OpenTelemetry | Piste d'audit native : chaque dépôt, clôture, approbation et publication est un maillon chaîné (hash, réservation, jetons réels) ; observabilité de Core dans `core/` | Pas de dépendance externe nouvelle ; la preuve est vérifiable hors ligne |
| Qdrant / RAG / Cognee / NetworkX | M10 (ADR-0010) tient la mémoire et le RAG ; le graphe d'impacts M9 est un graphe de règles sur les captures (`graphe_impacts`) | Pas de seconde mémoire ; M9 lit M10 |
| dbt Semantic Layer / MetricFlow | Dictionnaire de métriques de M8 (`departments/m08-analytics/metrics/*.yaml`) + registre des indicateurs exécutifs M9 (`metriques_executives`) | Un seul propriétaire des définitions (M8) ; M9 relie, cite, ne définit pas |
| Superset / BI | Tableau de bord `/direction` de la console OPSYS | Réutilise la console existante |
| n8n | Aucun n8n dans le dépôt : la planification passe par les grants/remises cron natifs (hôte opérateur) — gate M9.5 | Aucun scheduler global ; pas de nouvelle surface |
| Ragas, DeepEval, DSPy | Corpus d'évaluation maison à attentes indépendantes (61 cas) + conseil réel mesuré (3 rondes) | Aucun nouveau paquet ; le critère est la tenue des garde-fous, pas un score de modèle |
| Notification Nathan, MCP broker, sandbox d'actions | Droits natifs : `exiger_admin_strict`, `roles_appareil`, approbations N3, liste blanche d'actions (`actions_m9`) | Pas de canal sortant dans M9 : il propose, la file native décide |
| Chiffres/probabilités produits par un modèle | Interdit : le code calcule, le modèle explique ; tout chiffre est un fait cité ou un calcul déterministe testé | AGENTS.md ; règle dure M9 |

## 3. Correspondance des vingt-quatre sous-modules

Statuts : `DONE_VERIFIED`, `NEEDS_HARDENING`, `PARTIAL`, `GATED_NATHAN`, `GATED_EXTERNAL_API`, `STUB`. Les preuves exactes
(commits, tests, exécutions) sont dans `docs/reprise/M9-COMPLETION-20261028/MATRICE-EXIGENCES.json`.

| Sous-module | Livré dans OPSYS-AI (modules → outils / page console) | Statut |
|---|---|---|
| M9.1 Data Fabric | `capture_strategique`, `catalogue_producteurs` (19 lectures), `dossier_strategique` → `m9_capturer_producteur`, `m9_lire_capture`, `m9_lister_captures`, `m9_verifier_captures`, `m9_couverture_strategique`, `m9_apercu_dossier_strategique` ; `/direction/sources` | DONE_VERIFIED |
| M9.2 Business State Graph | `graphe_impacts`, `relations_catalogue` → `m9_apercu_graphe_impacts`, `m9_propager_impacts` | DONE_VERIFIED |
| M9.3 Executive Semantic Layer | `semantique_metriques`, `metriques_executives` (17 indicateurs) → `m9_rapprocher_metriques`, `m9_indicateurs_executifs` ; `/direction/indicateurs` | PARTIAL (gate M8 : registre et mesures sans lien de conception) |
| M9.4 Department Council | `conseil` (12 rôles), `sessions_conseil`, `audit_affirmations` → outils `m9_ouvrir_conseil`…`m9_cloturer_conseil` ; conseil réel exécuté (3 rondes) | NEEDS_HARDENING (jonction Core native) |
| M9.5 Daily War Room | `briefing_matin`, `outils_direction` (risques, changements depuis la veille) → `m9_salle_de_guerre`, `m9_produire_briefing_matin` ; `/direction` | GATED_NATHAN (planification : hôte opérateur) |
| M9.6 Weekly Executive Report | `revue_periodique`, `rapport_direction` (20 sections) → `m9_apercu_revue`, `m9_publier_revue`, `m9_lister_revues`, `m9_lire_revue` ; `/direction/revues` | DONE_VERIFIED |
| M9.7 Monthly / Quarterly | idem, granularités mensuelle et trimestrielle | DONE_VERIFIED |
| M9.8 Scenario Planning | `scenarios` (19 chocs), `question_scenario` → `m9_evaluer_scenarios`, `m9_interpreter_question_scenario` ; `/direction/scenarios` | PARTIAL (simulations finance/capacité/stock chez leurs propriétaires) |
| M9.9 Forecast & Projection | `previsions`, `tendances` → `m9_previsions_consolidees`, `m9_projeter_tendance` ; `/direction/tendances` | PARTIAL (une seule prévision de propriétaire : M5) |
| M9.10 Decision Intelligence | `decision_cadrage`, `conseil`, `rapport_decision_v2` (21 sections, retenu par délégation) → `m9_cadrer_decision` ; `/direction/decision` | DONE_VERIFIED |
| M9.11 Priority & Allocation | `priorisation` → `m9_prioriser_options` | PARTIAL (aucune capacité d'équipe exposée) |
| M9.12 Risk Radar | `risques` (+ `delta`) → `m9_radar_risques` ; `/direction/risques` | DONE_VERIFIED |
| M9.13 Opportunity Radar | `occasions` → `m9_radar_occasions` | DONE_VERIFIED |
| M9.14 Market Intelligence | `veille` (import explicite, quarantaine) → `m9_declarer_source_veille`, `m9_importer_document_veille`, `m9_lire_veille` | DONE_VERIFIED (aucun accès externe) |
| M9.15 Strategic Playbooks | `playbooks` (17 gabarits) → `m9_lister_playbooks`, `m9_evaluer_playbook` | DONE_VERIFIED |
| M9.16 OKR / Execution | `plans` → `m9_enregistrer_plan`, `m9_lire_plans`, `m9_noter_suivi_plan`, `m9_annuler_plan` ; `/direction/plans` | DONE_VERIFIED |
| M9.17 Action Orchestrator | `orchestrateur`, `actions_m9` → `m9_proposer_action`, `m9_reconcilier_action`, `m9_lire_actions` | DONE_VERIFIED |
| M9.18 Experiments / ROI | `experiences` (cadre de gouvernance obligatoire) → `m9_definir_experience`, `m9_evaluer_experience`, `m9_lire_experiences` | PARTIAL (mesures et coûts chez M5/M7/M8) |
| M9.19 Governance | `conseil.gouverner`, approbations natives N3, `m9_decider_demande_approbation` | DONE_VERIFIED |
| M9.20 M10 Memory | `memoire_m10` → `m9_preparer_memoire_decision`, `m9_verifier_memoire_decision` | DONE_VERIFIED |
| M9.21 Dashboard | `/direction` (panneaux indépendants) | DONE_VERIFIED |
| M9.22 Mobile | contrat serveur admin (`CONTRAT-MOBILE-ADMIN-M9.md`), aucun écran | PHASE_MOBILE_FINALE |
| M9.23 Eval & Trust | `evaluation`, corpus `evals/corpus-v1.json`, conseil réel (`preuves-conseil-reel/`) | DONE_VERIFIED |
| M9.24 E2E | parcours de bout en bout avec vrais producteurs (`tests/test_m9_e2e_cahier.py`) | voir §8 |

## 4. Registres (remplacent les tables `strategic_*`)

| Table du cahier | Registre / source OPSYS-AI |
|---|---|
| strategic_snapshot, strategic_metric_value | `captures_strategiques` (captures de lectures, quatre temps distincts) |
| strategic_decision, _option, _impact, strategic_report | `sessions_conseil` (ouverture, tours, clôture, rapport v2) ; `publications_revue` |
| strategic_approval_request | file d'approbation **native** (`approbations`) + `actions` (propositions M9 et constats) ; brouillon de demande dans `m9_cadrer_decision` |
| strategic_risk, strategic_opportunity | calculés à la demande depuis les captures (radars), jamais stockés comme vérité |
| strategic_action | `actions` |
| strategic_playbook(_run) | gabarits dans `playbooks` ; instanciation calculée |
| strategic_scenario, strategic_forecast | calculés à la demande (déterministes, rejouables) |
| strategic_experiment | `experiences` |
| strategic_okr | `plans` |
| strategic_memory_link | `memoire_m10` + M10 |
| strategic_eval_result | `evals/` + preuves archivées |

Chaque registre : append-only, hash chaîné, `rang_attendu` (concurrence), altération → `REJ-…-CHAINE-INVALIDE`.

## 5. Roadmap du cahier (phases 0–12)

Phase 0 audit — ce document. Phases 1–2 (Data Fabric, couche sémantique), 3 (Daily War Room), 4 (rapport hebdo), 5 (décision),
6 (scénarios / prévisions), 7 (risques / occasions), 8 (conseil), 9 (playbooks / OKR / actions), 10 (tableau de bord ; mobile =
contrat), 11 (évaluation / confiance), 12 (QA finale) : livrées, voir §3 et le dossier de reprise.

## 6. Risques techniques

- Dépendance aux lectures des producteurs : une lecture absente n'est jamais remplacée (couverture et manques nommés).
- Le bac à sable n'exécute pas `core/` : la jonction Core native du conseil n'est pas qualifiée ici.
- Un modèle réel produit parfois des sorties de forme invalide : le code les refuse en entier (mesuré en conseil réel).
- Validité sémantique non prouvée : une citation exacte prouve la correspondance au texte, pas la vérité ni le raisonnement.

## 7. Gates Nathan

Voir `docs/reprise/M9-COMPLETION-20261028/` : liste des 21 sections retenue par délégation (révisable) ; planification
quotidienne (hôte opérateur) ; lien registre ↔ mesures M8 ; données des producteurs pour M9.8, 9, 11, 18 ; écran mobile.

## 8. Tests de bout en bout du cahier

Les six parcours (rapport hebdomadaire, budget marketing, cashflow serré, trop de leads pour la capacité, nouvelle ville,
risque de réputation) sont couverts par `tests/test_m9_e2e_cahier.py` avec de vrais producteurs ; ce qu'un producteur ne
fournit pas est nommé dans le test.
