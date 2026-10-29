# M9.8 — scénarios et tests de stress

Statut : **PARTIAL** (simulations finance, capacité et stock chez leurs propriétaires).
[Architecture M9](M9-STRATEGIC-INTELLIGENCE-ARCHITECTURE.md) · [tissu de données](M9-DATA-FABRIC.md) ·
[table d'audit](M9-AUDIT-INITIAL-QUADRUPLE-A.md).

## Objectif

Répondre à « et si… » par des sensibilités arithmétiques transparentes : une hypothèse nommée (paramètre avec unité et
bornes) appliquée à une base qui est un fait cité d'une capture, comparée à la référence inchangée — et dire, pour tout
le reste, quel propriétaire doit calculer quoi avec quelles entrées.

## Pourquoi

Un scénario chiffré par un modèle, ou sur une base saisie à la main, serait une invention. Les effets de trésorerie, de
marge, de capacité ou de stock appartiennent à M5, M4, M6 et M8 ; M9 ne doit pas devenir une seconde finance.

## État actuel

- 19 chocs dans `scenarios.CHOCS` (version `2026-10-28.1`) : les neuf de la définition produit (`hausse_budget_marketing`,
  `baisse_leads`, `hausse_cout_materiaux`, `absences`, `meteo`, `achat_camion`, `nouvel_employe`, `perte_gros_client`,
  `nouvelle_ville`) et dix ajoutés (`achat_equipement`, `achat_batisse`, `gain_gros_client`, `retard_paiement_client`,
  `saison_morte_faible`, `nouveau_service`, `concurrent_agressif`, `cashflow_serre`, `rupture_inventaire`,
  `trop_de_demandes`).
- 17 chocs portent au moins un effet arithmétique ; `cashflow_serre` et `rupture_inventaire` n'en ont aucun : jamais
  `calculable`, ils ne rendent que leurs `a_calculer_par` (ex. trésorerie face au seuil → `m5_prevoir_tresorerie`).
- Interpréteur « et si… » (`question_scenario`, version `2026-10-29.1`) : chaque choc a au moins un exemple reconnu.
- La matrice d'exigences parle encore de « neuf chocs » ; le code et `test_scenarios.py` en comptent dix-neuf.

## Architecture

- **Évaluation** (`scenarios.evaluer`, module pur) : nombres en `Decimal` à partir de textes sobres (jamais flottant,
  NaN ni exposant : `REJ-SCENARIO-NOMBRE`), arrondi demi-supérieur à l'échelle déclarée. Chaque effet est `CALCULE`,
  `NON_CALCULE` (base absente ou illisible : ce qui manque et qui le possède) ou `INFAISABLE` (hypothèse incompatible
  avec la base, jamais tronquée à zéro).
- **Bases** : mapping nom → adresse de fait citable du dossier (`<lecture>#<rang>:<chemin>`), dont l'unité est celle que
  le choc exige ; aucune base saisie à la main.
- **Comparaison** (`comparer`) : référence = base inchangée ; écarts signés de mêmes unités, aucune moyenne.
- **Interpréteur** (`question_scenario.interpreter`) : question normalisée (casse, accents, apostrophes), motifs fixes
  par choc ; un paramètre n'est retenu que s'il est dit (« 25 % », « 48 000 $ », « deux employés »), validé par
  `scenarios.valider_parametre`, sinon listé dans `parametres_a_fournir`. Refus nommés : `REJ-QUESTION-POURCENTAGE-EN-LETTRES`,
  `REJ-QUESTION-NOMBRE-SIGNE`, `REJ-QUESTION-AMBIGUE`, `REJ-QUESTION-VIDE`, `REJ-QUESTION-LONGUEUR`, `REJ-QUESTION-TYPE`.
  Sans correspondance : `QUESTION_NON_RECONNUE` et la liste des chocs. Le texte est une donnée, jamais une instruction.

## Fichiers

[scenarios.py](../../../departments/m09-strategic-intelligence/src/m9_strategic_intelligence/scenarios.py),
[question_scenario.py](../../../departments/m09-strategic-intelligence/src/m9_strategic_intelligence/question_scenario.py),
`outils_conseil.py` (`m9_evaluer_scenarios`), `outils_questions_scenario.py` (`m9_interpreter_question_scenario`).

## Outils et pages de console

| Outil | Rôle |
|---|---|
| `m9_interpreter_question_scenario` | question → propositions de chocs ; n'évalue rien (T0/N0) |
| `m9_evaluer_scenarios` | 1 à `MAX_CHOCS` = 12 chocs `{choc, parametres}` sur bases citées, comparaison à la référence |

Admin strict (`REJ-SCENARIO-CHOC`, `REJ-SCENARIO-COMPARAISON` pour une entrée mal formée). Page `/direction/scenarios` :
formulaire POST avec jeton CSRF, référence, bases et chocs en JSON borné (4 096 caractères), refus `REJ-DIRECTION-JSON`
pour un JSON illisible. L'interpréteur n'est pas branché sur cette page (non livré) : il est appelable comme outil.

## Données et registres

Aucun registre propre : scénarios et comparaisons sont recalculés, déterministes et rejouables. Les bases viennent du
dossier construit sur `captures_strategiques` à la référence demandée.

## Workflows

1. Interpréter la question ; compléter les `parametres_a_fournir` avec la personne.
2. Capturer la lecture qui porte la base (ex. `m2.leads` pour `trop_de_demandes`) et choisir l'adresse du fait.
3. Évaluer ; lire `a_calculer_par` pour tout effet financier, de capacité, de stock ou de mesure.

## Intégrations

Ce qui reste chez les propriétaires : trésorerie projetée (M5, `m5_prevoir_tresorerie`), marge et rentabilité (M5),
pipeline et revenus (M2/M5), capacité d'équipe (M4), disponibilité et rupture (M6), mesures (M8). Aucun port de
simulation métier n'existe chez eux aujourd'hui ; M9 nomme les entrées à leur fournir. Le cadrage de décision (M9.10)
liste les scénarios à examiner par type de décision.

## Risques

- Une sensibilité d'une seule hypothèse n'est pas une prévision ; la lire comme telle surestime sa portée.
- Les motifs de l'interpréteur ne reconnaissent que les formulations prévues : une question non prévue est refusée,
  jamais devinée.

## Gates Nathan

Ports de simulation chez M5 (trésorerie sous hypothèses), M4 (capacité) et M6 (stock) : décisions de leurs propriétaires.
Les bornes des paramètres sont des propositions de code, non validées comme politiques d'affaires.

## Tests

`departments/m09-strategic-intelligence/tests/test_scenarios.py` (dix-neuf chocs, oracles exacts, base absente refusée,
infaisable sans troncature, aucune marge, trésorerie, capacité ni ROI calculés), `test_question_scenario.py` (paramètre
non dit à fournir, injection ignorée, temps borné) ; `tests/test_m9_questions_scenario_integre.py` (question interprétée
puis évaluée sur une capture réelle de M2, dispatcher réel, refus hors admin) ; `tests/test_console_direction_m9.py`
(POST CSRF, JSON borné, calcul sur fait cité).

## Statut

PARTIAL : moteur arithmétique et interpréteur vérifiés ; effets métier non simulés faute de ports chez les propriétaires.

## Prochaines étapes

1. Brancher l'interpréteur sur `/direction/scenarios` (proposition puis évaluation).
2. Raccorder un port de simulation M5 lorsqu'il existe, en lecture T0, et le citer comme fait.
3. Mettre à jour la matrice d'exigences (dix-neuf chocs).
