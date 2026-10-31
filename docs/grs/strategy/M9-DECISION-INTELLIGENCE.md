# M9.10 — intelligence de décision

Statut : **DONE_VERIFIED** (liste des 21 sections retenue par délégation, révisable).
[Architecture M9](M9-STRATEGIC-INTELLIGENCE-ARCHITECTURE.md) · [conseil](M9-DEPARTMENT-COUNCIL-AGENTS.md) ·
[contrat 21 sections](../../reprise/M9-COMPLETION-20261028/CONTRAT-RAPPORT-21-SECTIONS.md) ·
[table d'audit](M9-AUDIT-INITIAL-QUADRUPLE-A.md).

## Objectif

Mener une question de direction (« Dois-je acheter un camion ? ») du cadrage à la décision humaine : type de décision,
lectures nécessaires et manques, validation applicable, délibération du conseil, rapport de décision en 21 sections
ancrées, puis action proposée à la file d'approbation native et consignée dans M10.

## Pourquoi

La définition produit (§M9.10) annonce « un rapport en 21 sections » sans les énumérer, et le prompt maître du 9 juin
2026 n'est pas versionné. Il fallait un schéma vérifiable, compatible avec le contrat historique à 15 clés, qui
interdise toute recommandation sans source ni hypothèse et laisse la décision à un humain.

## État actuel

- **Cadrage** (`decision_cadrage`, version `2026-10-29.1`) : 12 types — `budget_publicitaire`, `embauche`,
  `achat_vehicule`, `achat_batiment`, `hausse_prix`, `nouveau_service`, `refus_petits_contrats`, `priorite_ville`,
  `reduction_depenses`, `investissement_equipement`, `strategie_marketing`, `ajout_equipe`.
- **Rapport v2** (`rapport_decision_v2`, schéma `opsys.m9.rapport_decision/v2`, statut `RETENU_PAR_DELEGATION`) :
  21 sections, dont 15 correspondent une à une aux clés historiques et 6 sont des extensions (`question`,
  `donnees_manquantes`, `contradictions`, `options_alternatives`, `dependances`, `conditions`). Retenu le 2026-10-29
  sur la réponse de Nathan « Oui tu as toutes les autorisations » ; jamais `RATIFIE`.
- Le rapport assemblé à la clôture d'un conseil renseigne question, état, données utilisées et manquantes,
  contradictions, hypothèses, incertitudes, diagnostic, décision recommandée et validation ; options, scénarios,
  impacts, dépendances, risques, priorités, conditions, plan d'action, tâches et mesure du succès restent
  `NON_DISPONIBLE` (« non produit par cette session »), de même que `memoire_m10` (contexte non encore relié).

## Architecture

- `classer(question)` : motifs normalisés ; un seul type `RECONNU`, sinon `AMBIGU` (candidats) ou `TYPE_NON_RECONNU`
  (types connus) — jamais une devinette ; question vide ou au-delà de 500 caractères : `REJ-DECISION-QUESTION`.
- `cadrer(...)` : départements, lectures requises et leur couverture réelle, manques, contradictions ;
  `pret_pour_conseil` faux tant qu'une lecture requise manque ; validation (`requiert_nathan` toujours, comptable ou
  juriste selon le type, classes sensibles de la gouvernance) ; critères `PROPOSE_NON_VALIDE` ; scénarios et playbooks à
  examiner ; ce que la personne doit déclarer ; **brouillon d'approbation** `BROUILLON_NON_SOUMIS` (montant nul, risque
  `INCONNU`). `decision_prise_par_m9` = faux.
- `valider_rapport_decision_v2` : enveloppe exacte, 21 sections exactes, empreinte `rapport_id` ; une section manquante dit
  `NON_DISPONIBLE`/`NON_APPLICABLE` avec raison et aucun contenu ; aucune option, scénario, impact, risque, recommandation,
  condition, action, tâche ni mesure sans référence ancrée dans `donnees_utilisees` ou `hypotheses`, vérifiée de proche en
  proche (référence inconnue, ultérieure ou circulaire refusée : `REJ-RAPPORT-V2-REFERENCE`, `REJ-RAPPORT-V2-SANS-ANCRAGE`) ;
  une valeur exige texte, unité et `source_calcul` (`REJ-RAPPORT-V2-VALEUR`). Une abstention complète est valide.
- `vers_contrat_historique` projette exactement vers les 15 clés et passe le validateur historique inchangé.
- **Approbation** : la gouvernance du conseil n'autorise aucun effet ; `m9_proposer_action` dépose une demande native
  (port `actions_m9`, liste blanche) ; la décision se prend dans `/approbations` ou par `m9_decider_demande_approbation`
  (propriétaire `nathan_owner` sur son appareil, N3/N4 seulement ; N5 et T3 restent à la console) ;
  `m9_reconcilier_action` relit l'état natif sans rejouer.
- **Mémoire M10** (`memoire_m10`) : arguments exacts de `m10_journaliser_decision` préparés (identifiant
  `m9:<session_id>`, version = `rapport_id`), proposés par la file native, puis vérifiés par `m10.statut_decision` :
  `COHERENT`, `MEMOIRE_FANTOME`, `DIVERGENT`, `NON_ENREGISTREE`, `NON_ATTRIBUABLE`, `INCONNU`.

## Fichiers

[decision_cadrage.py](../../../departments/m09-strategic-intelligence/src/m9_strategic_intelligence/decision_cadrage.py),
[rapport_decision_v2.py](../../../departments/m09-strategic-intelligence/src/m9_strategic_intelligence/rapport_decision_v2.py),
[memoire_m10.py](../../../departments/m09-strategic-intelligence/src/m9_strategic_intelligence/memoire_m10.py),
`sessions_conseil.py` (`assembler_rapport`), `contrats.py` et `rapport_strategique.py` (contrat historique),
`outils_cadrage_decision.py`, `outils_memoire.py`, `outils_actions.py`, [actions_m9.py](../../../src/opsys/actions_m9.py).

## Outils et pages de console

`m9_cadrer_decision` (T0/N0), outils du conseil jusqu'à `m9_cloturer_conseil` et `m9_lire_rapport_conseil`,
`m9_proposer_action`, `m9_reconcilier_action`, `m9_lire_actions`, `m9_preparer_memoire_decision`,
`m9_verifier_memoire_decision`, `m9_lister_demandes_approbation`, `m9_decider_demande_approbation`. Pages
`/direction/decision` (question + référence → cadrage affiché), `/direction/conseil` (rapport v2 par tranches),
`/direction/actions` (renvoie à la file `/approbations`, M9 ne décide pas).

## Données et registres

`sessions_conseil` (rapport v2 dans l'événement `CLOTURE`), `actions` (empreinte des arguments, jamais leur contenu),
file `approbations` du socle, M10 (propriétaire de la mémoire). Le cadrage n'est pas stocké.

## Workflows

1. Cadrer la question ; capturer les lectures manquantes jusqu'à `pret_pour_conseil`.
2. Ouvrir le conseil, déposer les tours, clôturer : rapport v2.
3. Proposer l'action et la journalisation M10 à la file native ; un humain décide.
4. Réconcilier l'action, vérifier la mémoire M10.

## Intégrations

Conseil (M9.4), gouvernance et classes sensibles (M9.19), actions (M9.17), M10 (M9.20), scénarios et playbooks nommés
par le cadrage (M9.8, M9.15).

## Risques

- Le schéma ne juge ni la vérité ni l'actualité d'un contenu, seulement forme et ancrage.
- Dix sections du rapport ne sont pas encore composées depuis les autres sous-modules ; un rapport de conseil reste
  donc partiel par construction, ce qu'il dit.
- Les rapports antérieurs à la délégation (statut `PROPOSITION_NON_RATIFIEE`) ne passent plus le validateur actuel ; ils
  sont conservés comme historique.

## Gates Nathan

Confirmer ou amender la liste des 21 sections, ou verser le prompt maître M9 ; valider les critères proposés par type ;
toute décision et toute action restent humaines (file native).

## Tests

`departments/m09-strategic-intelligence/tests/test_decision_cadrage.py` (douze questions du cahier, inconnue ou ambiguë
jamais devinée, injection sans effet), `test_rapport_decision_v2.py` (21 sections, projection 15 clés, ancrage, valeur
avec unité et propriétaire), `test_sessions_conseil.py`, `test_memoire_m10.py` ; `tests/test_m9_indicateurs_cadrage_integre.py`,
`tests/test_m9_actions_integre.py`, `tests/test_m9_memoire_integre.py`, `tests/test_m9_gouvernance.py`,
`tests/test_console_direction_m9.py`.

## Statut

DONE_VERIFIED : cadrage, schéma, ancrage, approbation native et vérification M10 prouvés ; rapport complet dépendant
des sections encore non composées.

## Prochaines étapes

1. Composer les dix sections manquantes depuis scénarios, graphe, radars, priorités et plans, en faits cités.
2. Relier le contexte M10 (`m10.paquet_affaire`) à la section `memoire_m10`.
3. Soumettre le brouillon d'approbation seulement par une action humaine explicite.
