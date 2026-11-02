# Analyse d'écart M10 — Mémoire long terme, intelligence et conscience opérationnelle (Mnémo)

Date : 2026-11-02. Base : ligne architecte `e0424b040` + condensés de Nathan (branche `claude/analyse-prompts-nathan`).
Auteur : analyste/architecte (lecture seule du dépôt ; aucun code de production modifié).
Exigences comparées : [`M10-MEMOIRE.md`](M10-MEMOIRE.md) (condensé du prompt de Nathan, juin 2026).
État réel lu dans : `departments/m10-memoire/` (manifeste, SOUL, skills, `src/m10_memoire/*`, tests, evals), `src/opsys/{mnemo,connaissances,memoire,
evenements,retention,connecteurs_planification,observabilite,console}`, `core/src/context-engine/`, `mobile/src/m10`, `docs/produit/DEFINITION-PRODUIT.md`
(§7 M10), `docs/produit/{DIRECTIVES-NATHAN,VISION-ENTREPRISE-APPRENANTE,PERIMETRE-MODULES}.md`, `docs/reprise/MATRICES-20261031/MATRICE-EXIGENCES-M10.json`,
`docs/architecture/{M10-SOI-GRAPHE,CONNAISSANCES,INTERCONNEXION,PLANIFICATION,OBSERVABILITE-MCP}.md`, `docs/memory/RAG-PREMIUM.md`,
`docs/qualification/QUALIFICATION-POSTGRESQL.md`, `docs/utilisation/LIMITES-CONNUES.md`.

## 0. Légende et règles de lecture

Statuts : PRÉSENT_PROUVÉ (test pertinent exécuté par moi dans cette analyse, il passe ; niveau T = module, S = processus Python sur SQLite réelle + bus
+ sas réels, H = HTTP MCP via harnais Python ; jamais un vrai modèle, une vraie donnée, un vrai téléphone), PRÉSENT_NON_PROUVÉ, PARTIEL, SIMULÉ,
ABSENT (« non trouvé après recherche de X »), OBSOLÈTE_PAR_CONCEPTION (le dépôt fait autrement et aussi bien), BLOQUÉ_NATHAN.

**Exécutions de cette analyse** (`PYTHONPATH` = `src` + `departments/*/src`, `.venv/bin/python -m pytest -p no:cacheprovider --import-mode=importlib`) :
- `departments/m10-memoire/tests` : **1524 passed** en 173 s (matrice du 31 octobre : 1464 ; Mnémo a porté la suite à 1498 puis davantage).
- Socle, fichier par fichier : voir l'annexe A.
- Non exécutés : Jest du mobile, vitest du Core (pas de `node_modules`), variantes PostgreSQL, suite complète du socle.

Précaution : la matrice M10 date du 31 octobre ; les vagues 4 à 8 (Mnémo, connaissances, planification, interconnexion) ont changé plusieurs lignes. J'ai
suivi le code et les tests exécutés. Le dépôt a **deux mondes** (ADR-0012) qu'il faut lire séparément :
- **Mémoire d'affaires** : registres hash-chaînés `evenements` / `affaires` / `faits_analytiques` / `faits_strategiques` / `dossiers_cpa_scelles` / `soi` /
  `lecons`, graphe d'entités natif (migration 0052), bases de connaissances par département (0041), couche B PostgreSQL pgvector (`src/opsys/memoire`).
- **Mémoire du développement** : `developpement.py` (prompts, plans, décisions, postflight, scan du dépôt Git, preflight, audit), CLI
  `opsys-metier memoire-developpement`, console `/memoire` et `/api/memoire-developpement`, magasin SQLite fichier, consolidation par worker à grant.

## 1. Résumé honnête (une demi-page)

M10 est le département où l'**ingénierie de la preuve** est la plus avancée : chaînes append-only vérifiables, décisions à raison obligatoire, révisions
sans fusion, signaux critiques décidés par un humain seulement, sept niveaux de confidentialité appliqués aux paquets, filtre anti-injection, modèle de
soi sourcé dont la dérive devient une *proposition*, graphe explicite avec validité temporelle et confirmation humaine des arêtes sensibles, leçons
mesurées hors ligne et promues par une personne, mémoire de développement avec preflight, postflight, lignées de remplacement, contradictions et
audit. 1524 tests du département et les suites socle exécutées (annexe A) passent. Les « dix règles de non-oubli » sont **majoritairement tenues par
du code testé**, sur un modèle de données plus sobre que celui du prompt.

Mais le **cerveau permanent** que Nathan décrit n'existe pas encore comme système qui *fonctionne tout seul* :

1. **Presque rien ne tourne sans qu'un humain ou un agent le déclenche.** La consolidation nocturne d'affaires est inscrite « à construire » dans
   l'inventaire du planificateur (il manque l'énumérateur des affaires touchées la veille) : aujourd'hui c'est un tour d'agent livré en pause. L'audit
   « non-oubli » n'est pas planifié. Seul `mnemo-quotidien` a un exécuteur déterministe.
2. **M10 n'apprend presque rien du front office ni du terrain** : il consomme le lead qualifié, le client associé, les devis, les travaux terminés, la
   variance, la rentabilité, des faits M8/M9. Il ne reçoit ni plaintes, ni transferts, ni promesses humaines, ni préférences, ni objections, ni notes
   de chantier, ni erreurs de réception, et aucun écran employé/vendeur ne permet de lui écrire.
3. **Pas de récupération unifiée** : lexical littéral pour l'affaire, hybride mots+vecteurs pour les connaissances, pgvector pour la couche B, SQL pour
   le graphe — quatre voies sans routeur qui pondère statut, fraîcheur, autorité et module, et **aucun vrai modèle d'embeddings ou de reranker n'a jamais
   été raccordé ni mesuré** (doubles déterministes).
4. **Pas de résolveur de vérité ni de détecteur de contradictions transversal** pour les affaires (les contradictions n'existent que dans le preflight
   et l'audit du domaine développement, dans les constats rejoués du bus, et par signalement manuel).
5. **Le « aucun agent ne code sans contexte » n'est pas appliqué** : le preflight de développement existe mais exige une authentification humaine
   interactive ; aucun garde ne l'impose. Pour les agents de département, le moteur de contexte du Core pose le PREFLIGHT et refuse un outil N3+ sans
   paquet — mais ce TypeScript n'a pas été rejoué ici.
6. **Gouvernance Loi 25 inachevée** : rétention et effacement par sujet non décidés ; les KPI du manifeste ne sont pas calculés ; la mémoire n'a jamais
   tourné sur une donnée réelle, ni avec un vrai modèle.

Aucun statut `FAIT_PROUVE` n'est justifié (la matrice : 0 sur 20).

## 2. Tableau exigence → état réel

### 2.1 Les dix politiques de non-oubli

| # | Exigence | Statut | Ce qui le prouve | Ce qui manque exactement |
|---|---|---|---|---|
| P1 | Tout travail produit une trace (événement, résumé, fichiers, raison, preuve, tests, statut, auteur, horodatage, dépendances, impact, prochaine action) | PARTIEL | affaires : `registre.py`, `wct.py`, `variance.py`, `rentabilite.py`, `etapes.py`/`amont.py` (`tests/test_cascade_amont_m10.py` 6, `test_cascade_opportunite_m10.py` 8, `departments/m10-memoire/tests/test_{wct,variance,amont,evenements}.py`) ; développement : `enregistrer_prompt/plan/decision/postflight` (`test_developpement.py`) | impact et « prochaine action » non structurés ; 12 types d'événements consommés, mais pas `m5.cash_libre_constate`, `m6.reception_enregistree`, `m6.materiel_pret`, `m7.contenu_exporte` (INTERCONNEXION : « M10 n'a pas de clé… ») ni, surtout, rien du front office hors le lead |
| P2 | Aucun agent ne code/agit sans contexte (preflight) | PARTIEL | agents de département : moteur de contexte Core `core/src/context-engine/opsys-contexte-engine.ts` (PREFLIGHT + POSTFLIGHT, jamais bloquant, garde N3+ `opsys-contexte-garde.ts`) — côté Python `tests/test_openclaw_contexte.py` (59 passed), `tests/test_runtime_depot_postflight.py` (26) ; agents de dév : `preflight()` + CLI (`test_developpement.py` : ancre de fichier exacte, lignées, contradictions) | TypeScript du Core : PRÉSENT_NON_PROUVÉ ici ; **aucun mécanisme n'impose** le preflight aux agents de développement ; il exige une session humaine interactive (`memoire_developpement_cli._authentifier_interactif`) ; pas de feu vert/rouge « avec risque » : le preflight rend un paquet + limites |
| P3 | Rien n'est écrasé sans mémoire | PRÉSENT_PROUVÉ (T/S) | chaînes hash (`test_registre.py`, `test_registre_durable.py`, `test_revision.py`, `test_dossier_revision.py`) ; `m10_arbitrer_revision` sans fusion ; documents d'affaire versionnés, retrait doux (`test_documents_affaire.py`) | le « snapshot avant écrasement de fichier » du prompt n'a pas d'équivalent (le Git et le hash des sources le remplacent) |
| P4 | Toute décision a une raison (contexte, options, risques, conséquences, responsable, statut) | PRÉSENT_PROUVÉ (T/S) | `test_decisions.py`, `m10_journaliser_decision` (raison obligatoire, statut calculé par relecture) ; `enregistrer_decision` du développement | options/risques/conséquences ne sont pas des champs obligatoires de la décision d'affaires (raison + statut) |
| P5 | Mémoire révisable : fusion de doublons, remplacement, « dépassé », archive, **redact, tombstone, jamais de suppression dure** | PARTIEL | statuts du domaine développement (`STATUTS` : 10 valeurs de la définition produit) et relation `superseded_by` avec lignée bornée (`test_developpement.py`) ; révision signalée/arbitrée ; sources de connaissances retirées avec raison (`tests/test_connaissances_outils.py`) ; retrait doux de documents | pas de tombstone/redaction générique des registres d'affaires ; **fusion de doublons** : ABSENT (recherche : `rg "doublon\|dedup" departments/m10-memoire/src` → aucune détection de contenu ; connaissances : « doublons entre sources non détectés ») |
| P6 | Toute information importante est sourcée | PRÉSENT_PROUVÉ (T/S) | `ReferenceMemoireM10` vérifiable (`m10_verifier_reference`, `test_contexte.py`) ; provenance obligatoire des connaissances (`tests/test_connaissances_pipeline.py` 109) ; énoncé de soi à 1–5 sources vérifiables (`tests/test_mnemo_soi.py`, `test_mnemo_soi_sources.py`) ; chaque fait de paquet cite sa source (`test_paquets.py`) | — |
| P7 | Le système se connaît (identité, mission, limites, architecture, modules, état, valeurs, règles, modes, qualité, interdits) | PARTIEL | modèle de soi « affaires » (onze dimensions, énoncés sourcés/versionnés, confirmés par une personne : `tests/test_mnemo_soi.py` 41, `test_mnemo_outils.py`) ; `self_model` du développement (`consolidation_developpement.py`) | quatre dimensions sans alimentation automatique (clients types, ton de marque, règles et préférences de la direction) → « inconnu » tant que la direction ne les déclare pas ; aucun lecteur de modèle de soi mesuré avec un vrai modèle |
| P8 | Mémoire avant génération | PARTIEL | paquet d'affaire en 4 couches (`paquets.py`, `test_paquets.py` 18, `test_paquet_affaire.py`) injecté par le moteur de contexte du Core | seulement pour l'agent lié à une affaire (canal client / `affaire_id`) ; TS non rejoué ; autres départements non qualifiés (matrice M10.9) |
| P9 | Mémoire après action (postflight) | PARTIEL | `m10_deposer_faits_candidats` (statut `candidat`, idempotent, jamais promu : `test_faits_candidats.py`, `tests/test_runtime_depot_postflight.py`) ; `enregistrer_postflight` du développement avec diagnostic | les candidats n'entrent ni dans le paquet ni dans la consolidation ; hook natif non qualifié ; mise à jour automatique de la matrice/instantanés : ABSENT |
| P10 | Pas de mémoire magique | PRÉSENT_PROUVÉ | tout est explicite : registres, hash, tests ; `m10_auditer_non_oubli` (`test_audit.py`) | — |

### 2.2 Couches, fonctions et gouvernance

| # | Exigence (condensé) | Statut | Ce qui le prouve (chemins) | Ce qui manque exactement |
|---|---|---|---|---|
| C-1 | Journal d'événements immuable, typé (prompt, plan, tâche, fichier, décision, test, bug corrigé, statut de module, route, doc, config, gate, instruction utilisateur, observation, échec runtime, validation) | PARTIEL | affaires : registres hash-chaînés ; développement : `events(event_type…)` avec prompt, plan, décision, postflight (changements, tests, diagnostic) | vocabulaire d'événements de développement limité à 4 familles ; pas de « instruction de l'utilisateur », « gate bloqué », « route ajoutée », « statut de module » comme types |
| C-2 | Mémoire structurée canonique (entités, relations) | PARTIEL | `liaison.py` (session ↔ affaire, humain), `affaire.py` (forme commune), `catalogue_references.py`, relations `relations(…relation_type)` du développement | pas de modèle d'entités du système (module, route, fichier) hors ce que le scan range par chemin |
| C-3 | Mémoire vectorielle filtrée, collections par type, jamais orpheline | PARTIEL | connaissances : FTS5/tsvector + vecteurs exacts jusqu'à 20 000, RRF, reranker facultatif (`tests/test_connaissances_pipeline.py`, `…_mesure.py`) ; couche B `src/opsys/memoire` (pgvector 1024, `tests/test_memoire_store.py` 28, `test_memoire_query_confidentialite.py` 3) ; cloisonnement par département (`tests/test_memoire_autorite.py`) | **aucun vrai modèle d'embeddings ni reranker raccordé** (doubles) ; pas de collections « événements/code/prompts/plans/clients/CRM/compta » : seules des procédures M3 sont ingérées dans la couche B ; la mémoire d'affaires des registres n'est pas indexée vectoriellement |
| C-4 | Graphe de connaissances (DEPENDS_ON, IMPLEMENTS, MODIFIES, BREAKS, FIXES, TESTS, DOCUMENTS, SUPERSEDES, CONTRADICTS, SUPPORTS, REQUIRES_GATE…) avec validité temporelle | PARTIEL — ET en partie OBSOLÈTE_PAR_CONCEPTION | graphe d'entités d'affaires natif : 8 types de nœuds, 10 d'arêtes, validité, provenance, pseudonymes, confirmation humaine des sensibles (`tests/test_mnemo_graphe.py` 71, `test_mnemo_graphe_alimentation.py` 20, `test_mnemo_abus.py` 45, `test_mnemo_migration.py` 23) ; banc de 31 questions multi-sauts (`test_mnemo_mesure.py`) | le vocabulaire d'arêtes du prompt est celui d'une *usine logicielle* : côté développement, le « graphe » est `relations` (`prompt_for`, `plan_for`, `superseded_by`…) — **repli prévu par la définition produit**, pas Cognee/Neo4j (écarté, décision r1) ; arêtes DEPENDS_ON/IMPLEMENTS/FIXES/TESTS/BREAKS : ABSENTES ; équipes, fournisseurs, documents, décisions non alimentés par événement ; pas de purge ; pilote LightRAG documenté, non exécuté |
| C-5 | Points de reprise de workflows | OBSOLÈTE_PAR_CONCEPTION | planificateur durable (baux, journal, coupe-circuit : `PLANIFICATION.md`), idempotence (`IDEMPOTENCE.md`), jobs de consolidation à grant avec reprise (`test_consolidation_developpement.py` : backlog de nuits, ancien worker expiré) | LangGraph/Temporal remplacés ; aucune lacune propre à M10 |
| C-6 | Registre de prompts et de plans (hash, version, liens prompt→plan→changements) | PRÉSENT_PROUVÉ (T/S, domaine développement) | `enregistrer_prompt` (expurgation de secrets), `enregistrer_plan`, `enregistrer_postflight`, restauration (`test_prompt_plan_preflight_postflight_sont_sourcables_apres_restauration`, `test_prompts_expurgent_secrets…`) ; API `departments/m10-memoire/tests/test_memoire_developpement_api.py` | **le registre est vide en pratique** : rien n'ingère les directives, ADR, prompts et condensés de Nathan du dépôt (DIRECTIVES-NATHAN : « ne prétend pas être déjà ingéré par M10 ») |
| C-7 | Registre de décisions (ADR) | PRÉSENT_PROUVÉ | `test_decisions.py`, `test_signaux.py`, `test_humain.py` ; ADR du dépôt en Markdown (`docs/decisions/`) | les ADR Markdown ne sont pas reliés au registre `m10_journaliser_decision` |
| C-8 | Mémoire de code (fichiers, symboles, routes, imports, dépendances, diff, analyse d'impact) | PARTIEL | `scanner_depot` borné (500 fichiers/8 Mo, refuse symlinks et chemins privés, hash, fraîcheur : `test_scan_*`) | **symboles, routes, imports, résumés de diff, analyse d'impact : ABSENTS** (recherche : `rg "symbol\|ast\.\|import " developpement.py` → rien d'analytique) ; extraits lexicaux seulement |
| C-9 | Mémoire d'erreurs (symptôme, cause racine, correctif, test de non-régression, prévention) | PARTIEL | diagnostic de postflight : `incident_id`, `symptom`, `cause`, `cause_status` (5 valeurs), `prevention`, `source_refs` (`test_diagnostic_*`, `test_incident_id_est_ancre_exacte…`) | pas de champ « correctif » ni « test de non-régression » dédié (couverts par `changements` et `tests` du postflight) ; aucune mémoire d'erreurs *métier* (erreurs de réception, de chiffrage) hors la leçon d'écart |
| C-10 | Mémoire de validation (tests, commandes, résultats, preuves) | PARTIEL | `tests` du postflight ; matrices `docs/reprise/MATRICES-20261031/` hors M10 | pas de registre de commandes/environnements/résultats exécutés |
| C-11 | Mémoire d'agents (rôle, outils, permissions, historique, forces/faiblesses, critères d'escalade) | ABSENT dans M10 | recherche : `rg -i "forces\|faiblesses\|critères d'escalade" departments/m10-memoire src/opsys/agents*.py` → 0 ; la configuration/budget/état d'un agent vit dans `agents*.py` et la console `agents_ui.py` | historique de performance d'un agent ; seuls des KPI déclarés |
| C-12 | Mémoire temporelle (vrai à telle date, changé quand/pourquoi/par qui) | PARTIEL | graphe « à une date » (`m10_graphe_chemin`), fermeture d'arête par une personne, énoncés versionnés/obsolètes, chaînes datées | pas de requête générale « quelle était la vérité le jour X » sur les registres d'affaires |
| C-13 | Routeur de récupération (sémantique + mots-clés + module + domaine + fraîcheur + importance + statut + autorité + graphe + permissions ; pondération code vs affaires) | PARTIEL | quatre voies distinctes : `m10_rechercher_affaire_appareil` (littéral NFC), `m10_rechercher_connaissances` (hybride sourcé, âge, « périmée »), `opsys_memoire_rechercher` (couche B), `m10_graphe_*` | **aucun routeur unique** ; pas de pondération par statut/fraîcheur/autorité/module ; pas de profil de poids « code » vs « affaires » ; rappel de production non mesuré |
| C-14 | Injecteur de contexte | PRÉSENT_NON_PROUVÉ (TS) / PARTIEL | Core `opsys-contexte-engine.ts` (+ `*.test.ts` non rejoués) ; côté Python `tests/test_openclaw_contexte.py` (59 passed) | couverture : agents liés à une affaire ; un seul tour natif avec réponse de modèle déclarée (M9) ; hook de développement : GATED (D-014) |
| C-15 | Auditeur de mémoire | PARTIEL | `m10_auditer_non_oubli` (intégrité des deux chaînes + faits attendus par affaire : WCT, variance, amont : `test_audit.py`) ; `auditer_developpement` (liens incomplets, contradictions, fraîcheur : `test_audit_*`) ; console `/memoire/audit` | pas de questions-tests, pas de scores rappel/précision/fraîcheur/qualité de paquet ; pas planifié |
| C-16 | Gouvernance : permissions par domaine, confidentialité, rétention, oubli contrôlé, audit des accès, export contrôlé | PARTIEL | sept niveaux appliqués au paquet (`confidentialite.py`, `test_confidentialite.py`, `test_classification.py`) ; domaines isolés (`test_composition_domaines_journal_dev.py`) ; admin/owner relus en base (`test_garde_mobile_admin.py`) ; effacement par destruction de clé (`tests/test_effacement_cles.py` 8) ; `opsys_memoire_oublier` N3 + `journal_effacements` (couche B) | **rétention configurable et effacement par sujet** non décidés (gate Loi 25, BLOQUÉ_NATHAN) ; l'accès en lecture aux registres n'est pas journalisé comme audit d'accès ; export de paquet CLI ABSENT |
| C-17 | Banc d'évaluation | PARTIEL | recall@k/MRR sur corpus fictif de connaissances (`tests/test_connaissances_mesure.py` 17, `evals/connaissances-recherche.v1.yaml`) ; banc du graphe (`evals/soi-graphe.v1.yaml`) ; `tests/test_memoire_evaluation.py` 15 ; gabarit d'évaluation avec répondants simulés | aucun modèle réel mesuré ; corpus petits, fictifs, rédigés par l'équipe du moteur ; pas de « golden set » de non-oubli |
| F-1 | Paquets de contexte automatiques en couches (indispensable / important / preuves / approfondissement ; résumé, puces critiques, sources, fichiers, risques, tests, TODO) | PARTIEL | `paquets.py` : 4 couches ordonnées, budget 4 000 caractères, 5 faits par couche, provenance, omissions déclarées, blocs `affaire` et `consolidation` (`test_paquets.py`, `test_paquet_affaire.py`, `test_paquet_appareil_borne.py`, `test_preparation_paquets.py`, `tests/test_console_capture_paquets_m10.py` 16 + 2 skipped) | pas de paquets nommés « identité entreprise », « contexte par module », « bugs et pièges », « préparation au codage » ; pas de champs risques/tests/TODO dans le paquet d'affaire |
| F-2 | Récupération intelligente (cf. C-13) | PARTIEL | idem C-13 | idem C-13 |
| F-3 | **Résolveur de vérité canonique** (constitution > décisions Nathan > matrice > rapports > tests/sondes > code > docs > journaux > anciennes mémoires > hypothèses) ; contradiction = créer, marquer, proposer, valider | ABSENT (le principe est écrit, pas le code) | recherche : `rg -i "vérité canonique\|résolveur de vérité\|ordre de vérité\|AUTORITE_SOURCE"` dans `src/` et `departments/m10-memoire` → 0 ; l'ordre est décrit dans `DEFINITION-PRODUIT.md` §7 M10 ; briques voisines : `m10_signaler_revision` (manuel), constats contradictoires du bus (`src/opsys/evenements/constats.py`, `tests/test_interconnexion_scenarios.py` à jour), contradictions du preflight de développement | tout le moteur ; **et l'ordre lui-même diffère du prompt** (voir §3, point 5) |
| F-4 | Détection de contradictions et de mémoires obsolètes | PARTIEL | développement : `claims_contradictoires`, `cause_status` `disputed`, fraîcheur par hash (`test_preflight_signale_contradiction…`) ; bus : un constat rejoué avec contenu différent est dit par M2/M5/M8 (le premier état reste) | **aucun détecteur transversal automatique** sur les registres d'affaires (matrice M10.5) ; péremption : sources de connaissances seulement (`peremptions.balayage`) |
| F-5 | Preflight / postflight pour agents de dév (go/no-go avec risque, paquet, « ne pas casser », fichiers, pièges, tests requis, approbation requise) | PARTIEL | `preflight()` : must-know, preuves, fraîcheur, contradictions, lignées, ancres exactes, troncature annoncée ; `enregistrer_postflight` ; audit d'un postflight dont le plan manque (`test_developpement.py` 45 passed) | aucun go/no-go ni « tests requis » calculé ; aucun enforcement ; auth interactive obligatoire ; mise à jour des statuts de module/matrice : manuelle |
| F-6 | Consolidation nocturne (dépôt, Git, prompts, plans, rapports, journaux, tests, traces LLM, santé runtime, matrice) | PARTIEL | affaires : `m10_consolider_affaire` (un fait durable par (affaire, jour), idempotent, sources citées : `test_consolidation.py`) ; développement : worker à grant, rapport, reprise, fuseau (`test_consolidation_developpement.py`, 29 tests dont backlog de nuits et ancien worker) ; `mnemo-quotidien` (exécuteur `m10.mnemo`) | **la consolidation d'affaires n'a pas d'exécuteur** (`inventaire.py` : « a_construire », aucun énumérateur d'affaires touchées la veille) ; traces LLM, santé runtime, matrice, orphelins, modules sans tests : non scannés |
| F-7 | Audit hebdomadaire « pas d'oubli » avec questions-tests et scores | PARTIEL | `m10_auditer_non_oubli` ; KPI `nb_oublis_detectes_audit` (déclaré) | pas de batterie de questions-tests, pas de scores, pas de planification, pas de rapport alerte ; **KPI du manifeste non calculés** (`rg` des 5 identifiants dans `src/`, `departments/`, `tests/`, `mobile/` hors manifeste → 0) |
| F-8 | Modèles de soi générés et tenus à jour (usine ; entreprise) | PRÉSENT_PROUVÉ (S) pour l'entreprise ; PARTIEL pour l'usine | `tests/test_mnemo_soi*.py` (54), `test_mnemo_outils.py` (23), `test_mnemo_console.py` (11) ; exécuteur `m10.mnemo` ; `self_model` du développement | jamais exécuté avec un vrai modèle ni sur des données réelles ; énoncés sensibles/financiers filtrés par département (prouvé), pas par un vrai agent |
| F-9 | Gouvernance : jamais de secret en clair, masquage PII dans l'index, permissions par domaine, audit d'accès, export contrôlé, droit à l'oubli client, rétention, 7 niveaux | PARTIEL | secrets expurgés (`test_redaction_par_cle_json_masque_secrets…`) ; M10 ne garde que des identifiants et faits d'étape, jamais le contact du lead (Loi 25, `amont.py`) ; masquage PII par motifs (`src/opsys/observabilite`, `OBSERVABILITE-MCP.md`) ; niveaux (`confidentialite.py`) ; `CLIENT_PRIVATE` réservé à M1/M2 | oubli par sujet et rétention : BLOQUÉ_NATHAN ; pas d'audit d'accès en lecture ; masquage PII dans l'index vectoriel de la couche B non prouvé |
| F-10 | Observabilité (contexte utilisé, mémoire, prompt, modèle, coût, latence ; métriques événements/jour, latence de récupération, taille des paquets, taux de succès, contradictions, périmées, orphelines, score de non-oubli) | PARTIEL | journal de traces d'appels d'outils MCP (`OPSYS_TRACES=1`) | « Aucun tour d'agent n'est émis par le runtime » (OBSERVABILITE-MCP §8) ; aucune des métriques listées n'est calculée |
| F-11 | CLI (statut, ingestion dépôt/Git/prompts/plans, préparation, clôture, question, contexte de module, audit, contradictions, orphelins, nuit, export de paquet) | PARTIEL | `opsys-metier memoire-developpement {scanner,preflight,enregistrer,verifier,auditer,autoriser-job,configurer-cron}` ; CLI Mnémo et connaissances | pas de commande `question`, `contradictions`, `orphelins`, `export de paquet` ; ingestion des prompts/plans en lot : ABSENTE |
| F-12 | Tableau de bord admin (recherche, modèle de soi, mémoire de module, registres, mémoire de code/erreurs, visionneuse de paquets, rapports d'audit, revue des contradictions, revue de la mémoire sensible, santé des magasins) | PARTIEL | `/memoire` (recherche, audit, consolidation, scan, procédures, imports), `/plateforme/mnemo`, `/plateforme/connaissances`, `catalogue_memoire_ui`, capture de paquets (`tests/test_console_memoire_chantier.py` 18, `test_console_capture_paquets_m10.py`) | pas de revue des contradictions, de la mémoire sensible, ni de santé des magasins en un écran ; vue des registres prompts/plans limitée à l'API |
| F-13 | App mobile : admin (recherche, derniers changements, décisions à valider, contradictions, rapport) ; employé (note de chantier, « chose à ne pas oublier », erreur terrain) ; vendeur (mémoire client autorisée, apprentissage de vente, objection) | PARTIEL | admin : `mobile/app/(admin)/memoire.tsx`, `mobile/src/m10/*` (arbitrage durable, recherche d'affaire, documents, dossier de révision) + `tests/e2e/test_memoire_admin_appareil.py` (8 passed, harnais Python) ; tests Jest NON rejoués | **employé et vendeur : ABSENTS** (recherche : `rg -i "ne pas oublier\|note de chantier\|apprentissage de vente\|objection" mobile/src mobile/app src departments` → aucune fonction ; une seule occurrence, dans une grille d'évaluation M4) ; phase mobile reportée |
| F-14 | Tests d'intégration et E2E listés (prompt→plan→fichiers→tests→mémoire ; préparation de M7 récupère décisions/fichiers/pièges ; décision obsolète remplacée ; contradiction rapport ancien vs matrice récente ; secret non stocké ; impact CRM→compta ; test échoué→mémoire d'erreur ; question→réponse sourcée ; « ne jamais oublier un prompt » ; « travail minuscule ») | PARTIEL | ✓ prompt→plan→postflight sourçables après restauration ; ✓ secret expurgé ; ✓ lignée de remplacement ; ✓ erreur→diagnostic ; ✓ question→réponse sourcée *dans les connaissances* (`test_connaissances_mesure.py`) | ✗ « avant de coder M7 » sur un dépôt peuplé ; ✗ contradiction rapport vs matrice ; ✗ impact CRM→compta (pas d'analyse d'impact) ; ✗ question générale → réponse sourcée sur toute la mémoire |

### 2.3 Livré au-delà du condensé (à ne pas oublier dans le bilan)

Documents d'affaire versionnés et provenance PDF (`test_documents_affaire*.py`, `tests/test_trace_documentaire_m10.py` 49 passed) ; bases de connaissances
par département (neuf outils, migration 0041, recherche hybride sourcée, cycle brouillon → revu → publié, N3 humain pour les domaines réglementés) ;
leçons gouvernées (mesure hors ligne, canari, promotion humaine, surveillance : `tests/test_mnemo_lecons.py` 26, `test_mnemo_promotion.py` 16) ; faits
analytiques de M8 et stratégiques de M9 (`tests/test_m8_memoire_m10.py`, `test_m9_memoire_integre.py`, `test_interconnexion_m6_m9_m10.py`) ; signaux
critiques décidés par un humain ; liaison session ↔ affaire ; catalogue de références et dossier de révision pour le mobile.

## 3. Contradictions entre le prompt de Nathan et les décisions actuelles (arbitrage d'architecte)

| # | Vieux prompt | Décision/état actuel | Arbitrage |
|---|---|---|---|
| 1 | Cognee, Qdrant, Langfuse, LangGraph, Temporal, Cursor preflight/postflight, FastAPI `grs_api` | SQLite/PostgreSQL portables, FTS5/tsvector + vecteurs exacts, pgvector pour la couche B, graphe natif derrière le port `MoteurGraphe`, planificateur durable, outils MCP, console, Core TypeScript | **Le dépôt gagne.** Cognee « non décidé » (DEFINITION §10) → repli en place. Neo4j et graphe inféré par modèle écartés (r1). |
| 2 | Une seule « mémoire de l'usine » qui sert aussi les affaires | deux domaines isolés par permissions (ADR-0012) | **Conserver l'isolation.** Mais le domaine développement est aujourd'hui SQLite-seulement (garde typée sur PostgreSQL, 1 des 4 gardes restantes) : acceptable pour un outil d'ingénierie, à ne pas présenter comme produit client. |
| 3 | « Aucun agent ne code sans contexte » (preflight obligatoire, arrêt + alerte) | le preflight de développement exige une identité humaine interactive ; les agents de département ont le moteur de contexte | **Distinguer deux publics.** (a) Agents de département : déjà gardés (N3+ refusé sans paquet). (b) Agents qui codent le dépôt : proposer un *grant en lecture seule* pour le preflight (modèle de `autoriser-job`) ; écritures restant humaines → question 2. Pas d'enforcement par hook tant que ce n'est pas décidé. |
| 4 | « Rien n'est trop petit pour être mémorisé » ; vecteurs de clients, CRM, compta | minimisation Loi 25 : M10 ne garde que des identifiants et faits d'étape ; `CLIENT_PRIVATE` à M1/M2 ; `FINANCIAL` hors de tout paquet ; économie de tokens (paquet de 4 000 caractères) | **Loi 25 et budget l'emportent** : mémoriser les faits, pas les textes ni les contacts ; récupérer à la demande. |
| 5 | Ordre de vérité : constitution > décisions de Nathan > **matrice vivante > rapports validés > tests/sondes** > code > docs … | `DEFINITION-PRODUIT` §7 : exigences = directives actuelles de Nathan → décisions → règles ; **état réel = preuves reproductibles, code et sondes du commit ; « un label ancien ou une suite verte ne peut nier un défaut reproduit »** | **Adopter l'ordre de la définition produit**, qui place la preuve exécutée *au-dessus* des étiquettes de matrice. C'est lui que le futur résolveur (M10-04) doit coder. |
| 6 | « Pas de suppression dure » (supersede/archive/redact/tombstone) | idem définition produit ; **mais** Loi 25 impose l'effacement ou l'anonymisation sur demande ; l'effacement actuel passe par destruction de clé (courriel, voix) et `opsys_memoire_oublier` (couche B) | Registres append-only + **crypto-effacement par sujet** : conserver le fait pseudonymisé, détruire le lien. Procédure à décider (question 1). |
| 7 | Consolidation nocturne par scan + analyse de traces LLM | consolidation déterministe, sans LLM, idempotente ; « un chiffre vient de l'outil, jamais du modèle » | **Conserver le déterminisme** ; un modèle ne résume jamais seul un fait de mémoire. |
| 8 | Points de reprise LangGraph | planificateur durable + baux + journal | Équivalent, à ne pas reconstruire (C-5). |
| 9 | Mémoire d'agents (forces/faiblesses) | le dashboard configure modèle, outils, droits, budget par agent | Hors périmètre M10 aujourd'hui ; si voulu, un registre d'*observations sourcées* d'agent alimenté par l'évaluation, pas par auto-description. |
| 10 | Tableau de bord et app mobile d'emblée | mobile en dernière phase (directive du 21 octobre) | Les écrans employé/vendeur sont hors chemin critique ; la **voie d'écriture** (outil humain) peut précéder l'écran. |

## 4. Backlog priorisé de chantiers livrables

Ordre = valeur pour une PME de rénovation extérieure (**ne rien oublier**, **apprendre**, ne perdre aucune demande) pondérée par le risque. Preuve
commune exigée : tests rouges avant le code, ≥ 5 mutations personnelles, cas négatifs et d'abus (entrée hostile, double soumission, injection dans les
données, secret fuyant dans un journal, dépassement de quota), scénario de bout en bout fictif (`@example.test`), limites dites sans euphémisme.
Tout nouvel outil : manifeste, niveau, portées d'appareil, `registre-mcp verifier/sceller` ; nouvelle table : migration (tête 0058, 0059+ libres) et
portabilité SQLite/PostgreSQL sans nouvelle garde.

| Rang | Chantier | Périmètre et fichiers | Dépendances | Preuve exigée (scénario E2E fictif) | Risques | Exige Nathan |
|---|---|---|---|---|---|---|
| **M10-01** | **Consolidation nocturne d'affaires planifiée + audit « non-oubli » hebdomadaire** : énumérateur des affaires touchées la veille (lecture du registre `evenements`), exécuteur `m10.consolidation` et `m10.audit_non_oubli` (N2/N0), rapport lisible à la console, alerte dans « À voir » si un fait attendu manque | nouveaux `src/opsys/connecteurs_planification/exec_m10.py` (+ une ligne dans `exec_departements.py` et `inventaire.py` : passer `a_construire` → branché), fonction d'énumération dans `departments/m10-memoire/src/m10_memoire/consolidation.py`, planification du manifeste remplacée | aucune | 3 affaires fictives avec événements à J-1, 1 sans : 3 faits durables, 1 rien ; rejeu = aucune écriture ; panne au milieu → reprise sans doublon ; affaire forgée dans un événement → refus ; audit hebdo trouve un WCT sans trace (oubli injecté) | double déclenchement (agent cron actuel) ; coût linéaire par page de l'énumération | non (activation = geste admin) |
| **M10-02** | **Mémoire des plaintes, transferts et promesses humaines** : consommer les événements d'ouverture/clôture de transfert et de plainte de M1 (identifiants + catégorie, jamais de texte ni de contact), `CLIENT_PRIVATE`, visibles dans le paquet d'affaire de M1/M2 seulement ; outil humain `m10_consigner_promesse` (N2/N3, admin) pour « promesse humaine » ; liens vers le graphe (arête `concerne`) | `departments/m10-memoire/src/m10_memoire/{etapes,amont,outils}.py`, manifeste M10, catalogue d'événements (2 types), côté M1 `transferts.py` ; **transversal M10 + M1 + M2** (= M1-E) | accord sur le contrat d'événement | plainte fictive → transfert → fait de mémoire → le paquet d'affaire d'un lead de M1 la montre, celui de M3 non ; promesse consignée → rappelée au préflight ; événement rejoué = no-op ; charge sans donnée personnelle (test d'abus) ; tentative d'employé de lire le fait : refusée | contrat gelé après publication ; chevauchement avec M1-E | non |
| **M10-03** | **Ingérer la mémoire de projet dans la mémoire de développement** (directives de Nathan, ADR, condensés `PROMPTS-NATHAN-ANCIENS`, matrices, `AGENTS.md`) + E2E « ne jamais oublier un prompt », « avant de coder M7 », « décision obsolète remplacée », « travail minuscule » | nouveau module `departments/m10-memoire/src/m10_memoire/ingestion_projet.py`, commande `opsys-metier memoire-developpement ingerer-projet`, fixtures de dépôt fictif ; règle : ne jamais ingérer de secrets, expurgation existante | décision du preflight pour agents (question 2) pour l'usage ; le code ne la requiert pas | dépôt fictif avec 3 ADR dont un remplacé : preflight sur « M7 » rend la directive en vigueur, le remplacement et son ancre ; fichier de config minuscule modifié puis retrouvé ; secret factice expurgé ; réingestion = no-op | volume (bornes 500 fichiers/8 Mo existantes) ; SQLite seulement | question 2 |
| **M10-04** | **Détecteur de contradictions/péremptions transversal + résolveur d'ordre de vérité** : fonction pure qui applique l'ordre de la définition produit (preuve exécutée > étiquette ; décision de Nathan > règle) ; détecte sur les registres d'affaires deux faits d'une même clé de sujet de valeurs incompatibles (statut, date, quantité), décisions obsolètes sans successeur, références orphelines ; **propose** (`m10_signaler_revision`) sans jamais trancher | nouveau `departments/m10-memoire/src/m10_memoire/{contradictions,verite}.py`, tool N2 `m10_detecter_contradictions`, extension de `audit.py` ; console `/memoire/audit` | M10-01 pour la cadence | deux faits fictifs contradictoires (devis accepté vs sans réponse) → révision signalée, jamais écrasée ; ordre : un rapport ancien « terminé » contre un test rouge exécuté → le test l'emporte ; décision humaine préserve l'historique ; mutations sur l'ordre des autorités | faux positifs → bruit ; le résolveur ne doit pas décider seul (N3 humain) | non |
| **M10-05** | **Audit « pas d'oubli » avec questions-tests et scores** : entreprise fictive amorcée (affaires, décisions, leçons) + batterie de questions sourcées (« pourquoi cette marge ? », « qu'a-t-on convenu avec ce lead ? ») ; scores rappel/précision/fraîcheur/couverture ; rapport hebdomadaire ; KPI du manifeste réellement calculés | `departments/m10-memoire/src/m10_memoire/audit.py`, `evals/`, `tests/` ; calcul des 5 KPI + exposition à M8 si pertinent | M10-01 | amorce fictive → score 100 % ; suppression d'un fait → le score baisse et nomme l'oubli ; mutation : désactiver une vérification → le test échoue | corpus écrit par l'équipe (biais) : demander un second rédacteur | non |
| **M10-06** | **Leçons consommées par un département** (boucle « apprendre ») : brancher `opsys_lecons_actives` sur le bloc de prévision de M3 (écart de quantités) puis de M5 (marge) avec leurs gardes ; aucune leçon ne s'applique seule | M3/M5 (fichiers hors M10), `src/opsys/mnemo/` ; **transversal** | leçons promues par une personne ; peu de chantiers réels (seuil 6) | chantiers fictifs terminés → leçon proposée → promue (humain) → l'estimation M3 affiche la prévision ajustée *et sa source*, jamais le prix ; retrait → disparition | extrapolation sur peu de données ; interférence avec calcul déterministe | validation des seuils (déjà prévue) |
| **M10-07** | **Routeur de récupération unifié** : une fonction de fusion (RRF) au-dessus des quatre voies, pondérée par statut/fraîcheur/autorité/module, profils « affaires » et « développement », citations ; outil N0 `m10_rechercher_memoire` ; mesure sur banc | `departments/m10-memoire/src/m10_memoire/routeur.py`, evals ; réutilise les ports existants | M10-04 (autorité) ; embeddings réels pour la partie hybride | questions fictives multi-sources : la décision de Nathan prime sur un rapport ancien ; fait `FINANCIAL` jamais renvoyé à M7 ; sortie bornée au budget | double comptage de sources ; surface de fuite entre départements → matrice d'abus | non |
| **M10-08** | **Qualifier un vrai modèle d'embeddings et un reranker** sur les corpus de mesure (recall@k, MRR) et sur un banc rédigé par un tiers | `evals/`, profil local `src/opsys/memoire/profil_embeddings_local.py` ; **exige réseau pour les poids et lecture des licences** (impossible en bac à sable) | accord matériel (CPU/GPU) | rapports de mesure, avec intervalles | licences de poids ; coût d'inférence | **Oui** (question 4) |
| **M10-09** | **Notes humaines de terrain** : outil `m10_consigner_note_affaire` (employé/vendeur/admin selon portée d'appareil, texte borné, classifié, jamais visible de l'employé en relecture) ; écran mobile en phase finale | `departments/m10-memoire`, `ROLES.md` (portées), `mobile/src/m10` plus tard | M10-02 ; décision d'architecte sur les portées | note d'employé fictive → dans le paquet de l'affaire pour l'admin, invisible de l'employé ; injection dans le texte neutralisée | élargissement de droits d'appareil : revue adverse requise | non |
| **M10-10** | **Rétention et effacement par sujet (Loi 25)** : procédure, outils N3/N5, crypto-effacement du lien pseudonyme ↔ sujet, journal d'effacement ; extension du planificateur de rétention | `src/opsys/retention/`, `src/opsys/mnemo/vie_privee.py`, registres M10 | décision de Nathan | sujet fictif effacé → ses faits ne sont plus rattachables, la chaîne reste vérifiable ; effacement non autorisé refusé | irréversible → N5 ; sauvegardes existantes non couvertes | **Oui** (question 1) |
| **M10-11** | **Mémoire de code : symboles, routes (déclarations d'outils des manifestes), imports, tests ↔ modules, analyse d'impact** (stdlib `ast`) ; intégrée au preflight (« fichiers à lire », « tests requis ») | `developpement.py`/nouveau module, tests | M10-03 | modification fictive d'un module → impact listé (importeurs, tests) | faible valeur PME, forte valeur ingénierie | non |
| **M10-12** | Graphe : alimenter équipes/fournisseurs/documents/décisions par événements ; purge ; port PostgreSQL du magasin de développement | `src/opsys/mnemo/graphe/`, `developpement.py` | M10-10 pour la purge | — | — | non |

**Parallélisables sans conflit de fichiers** : M10-01 (`exec_m10.py`, `consolidation.py`) ∥ M10-03 (`ingestion_projet.py`) ∥ M10-11 (module de
code) ∥ M10-08 (evals, hors code). **À séquencer** : M10-02 avec M1-E (même événement) ; M10-04 puis M10-07 ; M10-05 après M10-01 ; M10-09 après
M10-02. Conflit léger : `exec_departements.py`/`inventaire.py` partagés avec M1-B (mettre chaque exécuteur dans son propre fichier). Ordre
d'attaque recommandé : **M10-01 et M10-03 ensemble, puis M10-02, M10-04, M10-05**.

## 5. Questions réellement bloquantes pour Nathan

1. **Rétention et effacement par sujet (Loi 25).** Quelles durées de conservation par catégorie (lead, client, plainte, note), et quand un client demande
   l'effacement, accepte-t-on de *pseudonymiser et détruire le lien* (le fait agrégé reste, la personne n'est plus identifiable) plutôt que de
   supprimer la ligne ? *Recommandation : oui (crypto-effacement), 7 ans pour ce qui touche la facturation, 24 mois pour un lead sans suite, avec avis
   d'une avocate.*
2. **Agents qui codent le dépôt.** Voulez-vous qu'un agent de développement puisse lire le preflight de la mémoire de développement sous un *grant en
   lecture seule* (écritures toujours humaines), ou que tout reste derrière une connexion humaine interactive ? *Recommandation : grant en lecture
   seule, révocable, journalisé ; aucune écriture automatique.*
3. **Contenu réel des bases de connaissances** : qui fournit et valide les documents de référence (garanties, procédures, normes de pose) ? Le système
   ne contient aucun contenu réel ; fiscal/comptable/juridique restent à valider par un professionnel. *Recommandation : vous fournissez les garanties
   et procédures de l'entreprise ; M10 les ingère en N2 et vous les publiez en N3.*
4. **Modèle d'embeddings et reranker** : autorisez-vous l'exécution locale d'un modèle d'embeddings (CPU du VPS ou GPU) et le téléchargement de ses
   poids sous licence MIT/Apache, pour enfin mesurer le rappel réel ? *Recommandation : oui, CPU d'abord, mesure sur un banc rédigé par un tiers.*
5. **Ce que vous voulez voir au quotidien** : acceptez-vous que la consolidation nocturne et l'audit hebdomadaire produisent leur rapport dans « À voir
   » (console/mobile) sans notification poussée tant que vous n'avez pas choisi un canal d'alerte interne (Telegram/Signal/courriel) ? *Recommandation :
   oui pour commencer ; choisir le canal d'alerte avec M1-B.*

## 6. Écarts de documentation à corriger par l'architecte

- `MATRICE-EXIGENCES-M10.json` : M10.12 (« cron natif non démarré ») et M10.16 (« WCT et variance seulement ») ne reflètent plus l'audit élargi aux faits de
  l'amont ; `LIMITES-CONNUES.md` ligne « Planification autonome » ne précise pas que la consolidation d'affaires reste « a_construire ».
- Le `README.md` de M10 contient une ligne de qualification mobile sans espaces (« 3140tests mobiles/154suites ») : à reformater.
- `PLANIFICATION.md` §1 et `inventaire.py` disent « consolidation d'affaires à construire », alors que le manifeste annonce une planification
  `consolidation-nocturne` : une des deux phrases est trompeuse pour un lecteur (c'est un tour d'agent, pas un exécuteur).
- Les cinq KPI du manifeste M10 (et les deux de M1) sont déclarés, jamais calculés.

## Annexe A — Résultats d'exécution (cette analyse, 2026-11-02)

Commande type : `PYTHONPATH=src:departments/*/src` + `.venv/bin/python -m pytest -p no:cacheprovider --import-mode=importlib -rfE <fichier>` (un fichier à la fois ; machine chargée par d'autres suites, durées indicatives). Aucun échec, aucune erreur.

- Département : `departments/m10-memoire/tests` : **1524 passed en 173 s**.
- Socle (35 fichiers, **856 tests passés**) :

```
tests/test_cascade_amont_m10.py => 6 passed in 6.76s
tests/test_cascade_opportunite_m10.py => 8 passed in 10.04s
tests/test_mnemo_soi.py => 41 passed in 0.30s
tests/test_mnemo_soi_sources.py => 13 passed in 0.40s
tests/test_mnemo_graphe.py => 71 passed in 22.32s
tests/test_mnemo_graphe_alimentation.py => 20 passed in 6.41s
tests/test_mnemo_lecons.py => 26 passed in 3.20s
tests/test_mnemo_promotion.py => 16 passed in 0.33s
tests/test_mnemo_mesure.py => 17 passed in 1.89s
tests/test_mnemo_outils.py => 23 passed in 11.77s
tests/test_mnemo_abus.py => 45 passed in 0.81s
tests/test_mnemo_console.py => 11 passed in 5.88s
tests/test_mnemo_migration.py => 23 passed in 7.65s
tests/test_connaissances_pur.py => 43 passed in 0.50s
tests/test_connaissances_pipeline.py => 109 passed in 31.66s
tests/test_connaissances_outils.py => 35 passed in 16.03s
tests/test_connaissances_mesure.py => 17 passed in 3.03s
tests/test_connaissances_lecture_admin.py => 12 passed in 8.51s
tests/test_connaissances_migration.py => 27 passed in 22.04s
tests/test_memoire_evaluation.py => 15 passed in 0.98s
tests/test_memoire_query_confidentialite.py => 3 passed in 0.90s
tests/e2e/test_memoire_admin_appareil.py => 8 passed in 60.87s (0:01:00)
tests/test_openclaw_contexte.py => 59 passed in 33.36s
tests/test_runtime_depot_postflight.py => 26 passed in 21.91s
tests/test_effacement_cles.py => 8 passed in 3.96s
tests/test_trace_documentaire_m10.py => 49 passed in 17.02s
tests/test_console_memoire_chantier.py => 18 passed in 30.46s
tests/test_console_capture_paquets_m10.py => 16 passed, 2 skipped in 26.13s
tests/test_interconnexion_m6_m9_m10.py => 12 passed in 7.38s
tests/test_m8_memoire_m10.py => 7 passed in 4.79s
tests/test_m9_memoire_integre.py => 2 passed in 3.04s
tests/test_memoire_outils.py => 17 passed in 11.21s
tests/test_memoire_store.py => 28 passed in 5.55s
tests/test_memoire_autorite.py => 17 passed in 7.09s
tests/test_interconnexion_scenarios.py => 8 passed in 8.17s
```

Non exécutés : Jest du mobile, vitest du Core, variantes PostgreSQL, suite complète du socle. Aucune mutation n'a été lancée : cette analyse ne modifie aucun code.
