# M9.23 — évaluation et couche de confiance

Statut : **DONE_VERIFIED** (couche déterministe mesurée ; validité sémantique non prouvée).
[Architecture M9](M9-STRATEGIC-INTELLIGENCE-ARCHITECTURE.md) · [conseil](M9-DEPARTMENT-COUNCIL-AGENTS.md) ·
[plan de test](M9-TEST-PLAN.md) · [rapport du conseil réel](../../reprise/M9-COMPLETION-20261028/preuves-conseil-reel/RAPPORT-CONSEIL-REEL.md) ·
[table d'audit](M9-AUDIT-INITIAL-QUADRUPLE-A.md).

## Objectif

Mesurer, avec des attentes écrites avant l'exécution, si les garde-fous de M9 tiennent : citation fidèle, inférence
déclarée, demandes et injections écartées, gouvernance, sémantique des métriques, abstention quand une donnée manque ; et
dire ce que la mesure ne prouve pas.

## Pourquoi

Le cahier citait Ragas, DeepEval ou DSPy. Le critère de M9 n'est pas un score de modèle mais la tenue de règles
déterministes ; un corpus maison, versionné et rejouable, suffit sans nouveau paquet (ADR-0012). Un taux de 100 % sur
quelques dizaines de cas ne vaut pas confiance générale : l'intervalle et les biais doivent l'accompagner.

## État actuel

- **Corpus** `evals/corpus-v1.json` : 61 cas, chacun avec `entree`, `attente` (verdict, code de refus, champs `extra`),
  `justification` et `regle` du contrat dont l'attente est dérivée — pas de la sortie du code. Répartition :
  `fidelite_citation` 16, `gouvernance` 13, `inference` 10, `abstention_donnees_manquantes` 8, `semantique` 8,
  `demandes_et_injection` 6.
- **Exécution** dans la vraie couche : admission des propositions du conseil (`conseil.admettre_proposition`),
  `conseil.gouverner`, `semantique_metriques`, et pour l'abstention `priorisation`, `occasions`, `previsions`,
  `playbooks`. Une exception `REJ-…` devient le verdict `REFUSE` avec son code ; une autre, `ERREUR-NON-NOMMEE`.
- **Rapport** (`evaluer`) : par catégorie, effectif, réussites, taux, **intervalle de Wilson à 95 %** (`wilson`), échecs
  listés avec l'attendu et l'observé (jamais moyennés ni effacés) ; `corpus_sha256` ; `modele_reel: false` ;
  `cout_modele` à 0 jeton ; `biais_connus` (auteur unique, petit effectif, couche déterministe seule, règles absentes du
  contrat non testées).
- **Preuve archivée** : `preuves-evaluation/EVAL-corpus-v1-20261029T003830Z.json` — 61/61, Wilson 95 %
  [0,9408 ; 1,0000] ; par catégorie, la borne basse va de 0,6097 (`demandes_et_injection`, 6 cas) à 0,8064
  (`fidelite_citation`, 16 cas).

**Conseil réel** (M9.4, rapport `RAPPORT-CONSEIL-REEL.md`) : trois rondes, six sorties d'un vrai modèle (sous-agent
Claude « sonnet » lancé en session, **pas** le runtime Core natif), sur une question fictive avec des faits M2 et M6
réellement capturés. Ronde 1 : deux refus de forme (`REJ-CONSEIL-SORTIE`, `REJ-CONSEIL-AFFIRMATION`) ; ronde 2 : une
admission, un refus de borne ; ronde 3 : deux admissions et la clôture `RECOMMANDATION` sans autorité d'effet. Le budget
réel (~80 000–87 000 jetons rapportés par tour, plafond réservé 6 000) a fait refuser le dépôt (`REJ-TOUR-RESERVATION`) ;
les dépôts suivants ont réconcilié une estimation déterministe déclarée telle. Wilson non calculé : trop peu de sorties.

## Architecture

Module pur `evaluation.py` ; le corpus est validé avant exécution (`REJ-EVAL-CORPUS` : champs requis, catégorie connue,
identifiants uniques) ; un genre d'abstention inconnu : `REJ-EVAL-CAS`. Rapport déterministe : même corpus, même rapport ;
corpus modifié, autre empreinte. Un second oracle naïf, dans les tests, recoupe les cas de citation.

## Fichiers

[evaluation.py](../../../departments/m09-strategic-intelligence/src/m9_strategic_intelligence/evaluation.py),
[corpus-v1.json](../../../departments/m09-strategic-intelligence/evals/corpus-v1.json),
[preuve d'évaluation](../../reprise/M9-COMPLETION-20261028/preuves-evaluation/EVAL-corpus-v1-20261029T003830Z.json),
`preuves-conseil-reel/` (entrées, sorties, dépôts, estimation d'usage par ronde, synthèse).

## Outils et pages de console

Aucun outil ni page : l'évaluation se lance par le test (voir [plan de test](M9-TEST-PLAN.md)). Les garde-fous mesurés
sont ceux des outils du conseil (`m9_deposer_tour_conseil`, `m9_cloturer_conseil`, `m9_auditer_affirmations_conseil`).

## Données et registres

Aucun registre. Corpus fictif versionné dans le dépôt ; preuves JSON sous un nom horodaté distinct, jamais écrasées (le
test refuse d'écrire sur un fichier existant).

## Workflows

1. Ajouter un cas : entrée, attente dérivée d'une règle écrite, justification.
2. Lancer le test ; lire les échecs par catégorie ; corriger le code ou l'attente selon la règle, jamais l'inverse.
3. Archiver la preuve avec `M9_EVAL_SORTIE` vers un nouveau nom.

## Intégrations

Conseil (M9.4), gouvernance (M9.19), couche sémantique (M9.3), priorisation (M9.11), occasions (M9.13), prévisions
(M9.9), playbooks (M9.15).

## Risques

- Biais d'auteur : corpus écrit par la mission qui a écrit le code.
- Une citation exacte prouve la correspondance au texte, pas la vérité d'une inférence (`validation_semantique:
  NON_PROUVEE`) ; le conseil réel l'a montré (« disponibilité des équipes » lue dans `m6.disponibilite`, qui porte sur les
  matériaux).
- Un seul modèle, un seul scénario, six sorties : indicatif, pas statistique.

## Gates Nathan

Décider s'il faut une qualification du conseil sur le runtime Core natif, avec plusieurs scénarios réels et un budget
dédié.

## Tests

`departments/m09-strategic-intelligence/tests/test_evaluation.py` (six catégories avec justification et règle, toutes
les attentes tiennent avec intervalle, second oracle naïf, attente fausse ou code cassé = échec conservé, reproductibilité,
corpus invalide refusé, bornes de Wilson, latence et écriture de preuve sur demande) ; `test_audit_affirmations_conseil.py`,
`tests/test_m9_conseil_integre.py` pour l'admission réelle.

## Statut

DONE_VERIFIED pour la couche déterministe ; qualité de conseil d'un modèle non établie.

## Prochaines étapes

1. Faire écrire des cas par une autre personne (diversité d'auteurs) et élargir les petites catégories.
2. Rejouer le conseil réel sur Core natif, avec plusieurs modèles, et calculer l'intervalle sur l'admission.
