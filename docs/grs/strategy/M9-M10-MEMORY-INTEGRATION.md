# M9.20 — intégration à la mémoire M10

Statut : **DONE_VERIFIED** (écriture proposée par la file native, vérification sans mémoire fantôme).
[Architecture M9](M9-STRATEGIC-INTELLIGENCE-ARCHITECTURE.md) · [intelligence de décision](M9-DECISION-INTELLIGENCE.md) ·
[exécution et actions](M9-EXECUTION-OKR.md) · [table d'audit](M9-AUDIT-INITIAL-QUADRUPLE-A.md).

## Objectif

Consigner dans M10 les décisions issues du conseil de direction, avec leur version et leur fondement, puis vérifier que
ce que M10 retient correspond à ce que M9 croit y avoir mis — sans que M9 écrive jamais lui-même dans la mémoire.

## Pourquoi

M10 est l'unique propriétaire de la mémoire (ADR-0010) ; une seconde mémoire dans M9 ou une écriture directe
contournerait sa chaîne append-only et la validation humaine. Une décision « consignée » que M10 ne porte pas
(mémoire fantôme) doit se voir, pas se supposer.

## État actuel

`memoire_m10.py` (version `2026-10-28.1`) :

- **Préparer** (`preparer`) les arguments exacts de `m10_journaliser_decision` pour une session de conseil **close**
  (`REJ-MEMOIRE-SESSION` sinon) : `decision_id` stable par session (`m9:<session_id>`), `raison` qui cite l'issue, la
  session, le `rapport_id` (la version), le `dossier_id`, le verdict de gouvernance et le motif éventuel
  (`REJ-MEMOIRE-RAISON` au-delà de 1 200 caractères), `statut`, `options_ecartees` (≤ 400, `REJ-MEMOIRE-OPTIONS`).
- **Statuts** préparables : `proposee`, `validee`, `remplacee`, `annulee`, `indetermine` ; `validee` exige
  `validation_humaine_declaree` (`REJ-MEMOIRE-VALIDATION`) ; une abstention du conseil ne se consigne pas `proposee` ni
  `validee` ; une correction est `remplacee` ou `annulee` avec motif (`REJ-MEMOIRE-STATUT`, `REJ-MEMOIRE-MOTIF`). Une
  correction réutilise le même identifiant : M10 reste append-only.
- **Consigner** : l'outil de préparation rend `ecrit: false` et un bloc `a_proposer` (département `m10-memoire`, outil,
  arguments, source `conseil:<rapport_id>`) ; l'écriture passe par `m9_proposer_action` puis l'approbation humaine dans
  la file native (demande N3), puis `m9_reconcilier_action`.
- **Vérifier** (`verifier`) : lit la dernière capture de `m10.statut_decision` connue à l'instant et la compare à
  l'attendu et à l'état de l'action : `COHERENT`, `DIVERGENT`, `MEMOIRE_FANTOME` (action `EXECUTEE_CONFIRMEE`, M10 sans
  trace), `NON_ENREGISTREE` (rien consigné, M10 le confirme), `NON_ATTRIBUABLE` (M10 porte la décision sans action
  exécutée côté M9), `INCONNU` (lecture absente, refusée, partielle, contradictoire ou illisible). Une lecture absente
  n'est jamais lue comme fantôme.

## Architecture

Module pur, sans écriture : M9 prépare et compare. M10 calcule le statut par relecture de sa propre chaîne ; M9 le lit par
le port privé `lecteurs_m9` et le fige dans une capture (M9.1). Un écart se corrige par une nouvelle journalisation
approuvée, jamais par M9.

## Fichiers

[memoire_m10.py](../../../departments/m09-strategic-intelligence/src/m9_strategic_intelligence/memoire_m10.py),
[outils_memoire.py](../../../departments/m09-strategic-intelligence/src/m9_strategic_intelligence/outils_memoire.py),
`sessions_conseil.py` (session close), `orchestrateur.py` (état de l'action),
`catalogue_producteurs.py` (lectures M10), [actions_m9.py](../../../src/opsys/actions_m9.py),
[lecteurs_m9.py](../../../src/opsys/lecteurs_m9.py).

## Outils et pages de console

| Outil | Accès |
|---|---|
| `m9_preparer_memoire_decision` (`session_id`, `statut`, `horodatage`, `options_ecartees`, `motif`, `validation_humaine_declaree`, `correction`) | admin strict, T0/N0, n'écrit rien |
| `m9_verifier_memoire_decision` (`decision_id`, `connaissance`, `attendu`, `action_id`) | admin strict, T0/N0 |
| `m9_proposer_action` vers `m10_journaliser_decision` | admin strict ; exécution après approbation humaine |

Aucune page de console dédiée : la demande se décide dans la file native `/approbations`, l'état se lit sur
`/direction/actions`.

## Données et registres

Lecture de `sessions_conseil`, `captures_strategiques` et `actions` (chaînes vérifiées :
`REJ-SESSION-CHAINE-INVALIDE`, `REJ-CAPTURE-CHAINE-INVALIDE`, `REJ-ACTION-CHAINE-INVALIDE`). Écriture chez M10
uniquement, par l'outil M10 approuvé.

## Workflows

1. Clore la session de conseil (rapport v2).
2. Préparer la consignation ; proposer l'action ; un humain approuve ; réconcilier.
3. Capturer `m10.statut_decision` ; vérifier ; corriger au besoin par `remplacee` / `annulee`.

## Intégrations

**Lectures M10** (catalogue, liste blanche du port privé) : `m10.statut_decision` (`m10_statut_decision`, argument
`decision_id`), utilisée par la vérification ; `m10.paquet_affaire` (`m10_paquet_contexte_affaire`, `affaire_id` +
`horodatage`, pages marquées incomplètes si une couche est tronquée), capturable mais **non relié** au rapport de
décision : la section `memoire_m10` du rapport v2 reste `NON_DISPONIBLE` (« contexte M10 non encore relié à la
session »). Écriture proposée : `m10_journaliser_decision`.

## Risques

- La vérification ne vaut qu'à l'instant de la dernière capture : sans nouvelle capture, un effacement n'est pas vu.
- Le contexte M10 n'alimente pas encore la délibération du conseil.
- `validee` repose sur une déclaration explicite de la validation humaine, non sur un constat automatique.

## Gates Nathan

Approbation de chaque journalisation dans la file native ; décision de consigner une décision comme `validee`.

## Tests

`departments/m09-strategic-intelligence/tests/test_memoire_m10.py` (préparation exacte sans écriture, correction même
identifiant, refus, `validee` et abstention, verdicts, lecture absente ou illisible jamais fantôme, connaissance
antérieure) ; `tests/test_m9_memoire_integre.py` (vrais M10 et file native : `NON_ENREGISTREE` puis `COHERENT`,
correction `annulee`, `DIVERGENT`, `MEMOIRE_FANTOME` après effacement du registre M10, refus nommés et identités).

## Statut

DONE_VERIFIED en processus (SQLite, vrai M10, vraie file d'approbation) ; contexte M10 non relié au conseil.

## Prochaines étapes

1. Relier `m10.paquet_affaire` au dossier de décision pour renseigner la section `memoire_m10` du rapport v2.
2. Capturer `m10.statut_decision` à chaque revue pour détecter plus tôt une mémoire fantôme.
