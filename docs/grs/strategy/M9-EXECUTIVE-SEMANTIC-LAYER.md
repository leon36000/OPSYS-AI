# M9.3 — couche sémantique exécutive

Statut : **PARTIAL** (gate M8 : registre et mesures sans lien de conception). [Architecture M9](M9-STRATEGIC-INTELLIGENCE-ARCHITECTURE.md) ·
[tissu de données](M9-DATA-FABRIC.md) · [table d'audit](M9-AUDIT-INITIAL-QUADRUPLE-A.md).

## Objectif

Relier chaque valeur de métrique citée par la direction à la définition de son propriétaire (identifiant, unité,
version, propriétaire) et refuser de réunir ce qui n'est pas comparable. Tenir le registre des indicateurs exécutifs du
cahier en disant, pour chacun, s'il existe une définition officielle et qui la possède.

## Pourquoi

Le cahier proposait une couche dbt/MetricFlow. OPSYS-AI a déjà un propriétaire unique des définitions : M8
(`departments/m08-analytics/metrics/*.yaml` et son registre durable). M9 doit relier et citer, jamais redéfinir ni
recalculer ; sinon deux chiffres « marge » divergents circuleraient dans la direction.

## État actuel

- `semantique_metriques` classe chaque observation : `COMPATIBLE`, `SANS_DEFINITION`, `UNITE_DIVERGENTE`,
  `VERSION_PERIMEE`, `VERSION_NON_DECLAREE`, `VERSION_NON_COMPARABLE`. Groupes clés par (métrique, unité, version) ;
  `agregable` reste faux, aucun groupe n'est additionné, moyenné ni comparé.
- `metriques_executives` (version `2026-10-29.1`) : 17 indicateurs. Statuts : 4 `DEFINIE_M8` (`gross_margin`,
  `qualified_lead`, `quote_to_win_rate`, `job_profitability`), 3 `DEFINIE_CHEZ_LE_PROPRIETAIRE` (`cash_free_real`,
  `marketing_roi`, `cost_per_lead`), 1 `SIGNAL_M9` (`risk_score`, grade et non score numérique, grille proposée non
  validée), 9 `A_DEFINIR_PAR_LE_PROPRIETAIRE` (`revenue`, `net_margin`, `pipeline_value`, `conversion_rate`,
  `estimate_to_quote_rate`, `cost_per_sale`, `team_capacity`, `inventory_readiness`, `customer_satisfaction`).
- **Version non comparable** : les mesures de M8 portent une empreinte SHA-256 de la définition chargée
  (`version_definition`), alors que le registre M8 numérote ses versions en entiers. Les deux schémas ne sont pas reliés
  par conception ; M9 rend donc `VERSION_NON_COMPARABLE` — verdict correct, jamais fusionné, ni « périmé » ni
  « compatible ».

## Architecture

- `cataloguer(definitions)` garde la version courante de chaque métrique et refuse deux définitions différentes pour une
  même version (`REJ-SEMANTIQUE-CONTRADICTION`).
- `classer(observation, catalogue)` : une valeur doit être un texte (`REJ-SEMANTIQUE-OBSERVATION`), jamais convertie.
- L'outil `m9_rapprocher_metriques` lit la dernière capture complète, acceptée et non contradictoire de
  `m8.definitions_metriques` (sinon `REJ-SEMANTIQUE-REGISTRE-ABSENT` : aucune définition supposée), puis les lignes
  `resultat.mesures[*]` des captures complètes de `m8.mesures_chantier`. Une mesure sans valeur textuelle est rendue
  comme non calculable avec son manque, jamais comme observation.
- `lignage(captures, connaissance=…)` : pour un indicateur défini, cite les faits des captures complètes
  (`<lecture>#<rang>:p<page>.<chemin>`) dont la clé ou l'identifiant de métrique correspond, au plus 6 par indicateur ;
  pour `DEFINIE_M8`, dit si chaque métrique est `AU_REGISTRE`, `ABSENTE_DU_REGISTRE` ou `REGISTRE_NON_CAPTURE`.
  `calcule_par_m9` vaut toujours faux.

## Fichiers

- [semantique_metriques.py](../../../departments/m09-strategic-intelligence/src/m9_strategic_intelligence/semantique_metriques.py),
  [metriques_executives.py](../../../departments/m09-strategic-intelligence/src/m9_strategic_intelligence/metriques_executives.py)
- [outils_semantique.py](../../../departments/m09-strategic-intelligence/src/m9_strategic_intelligence/outils_semantique.py),
  [outils_metriques_executives.py](../../../departments/m09-strategic-intelligence/src/m9_strategic_intelligence/outils_metriques_executives.py)

## Outils et pages de console

| Outil | Rôle |
|---|---|
| `m9_rapprocher_metriques` | classe les mesures M8 face au registre M8 capturé, par pages (`depart`) |
| `m9_indicateurs_executifs` | 17 indicateurs, statut de définition, présence au registre, faits cités, par pages |

Lecture seule, admin strict ; refus d'instant sans fuseau (`REJ-INDICATEURS-INSTANT`) et de départ hors bornes
(`REJ-INDICATEURS-DEPART`, `REJ-SEMANTIQUE-DEPART`). Page `/direction/indicateurs` (connaissance explicite, pagination) ;
panneau « Indicateurs exécutifs » de `/direction` (dénombrement par statut). Le rapprochement n'a pas de page dédiée.

## Données et registres

Lit `captures_strategiques` (lectures `m8.definitions_metriques`, `m8.mesures_chantier`, `m8.vue_executive`,
`m5.rentabilite_chantier`, `m7.performance_campagnes`). N'écrit rien.

## Workflows

1. Capturer `m8.definitions_metriques` puis les mesures (`m8.mesures_chantier`, une capture par WCT).
2. Rapprocher : lire les statuts ; seules les observations `COMPATIBLE` d'un même groupe sont comparables entre elles.
3. Lire les indicateurs : un indicateur `A_DEFINIR_PAR_LE_PROPRIETAIRE` n'a aucune valeur citable ; l'absence n'est jamais
   un zéro.

## Intégrations

M8 (définitions et mesures), M5 et M7 (valeurs publiées par le propriétaire). Les indicateurs alimentent le panneau de
`/direction` et la section correspondante des revues (`rapport_direction` importe `metriques_executives`).

## Risques

- Tant que M8 ne relie pas registre et définitions, aucune mesure M8 n'est `COMPATIBLE` par version.
- Le lignage par clé terminale peut citer plusieurs faits homonymes : il les cite tous (bornés), sans choisir.
- `cash_free_real` est défini chez M5 mais aucune lecture T0 n'est autorisée : aucune valeur n'est citée.

## Gates Nathan

Décision de conception chez M8 (ex. consigner l'empreinte de la définition source dans l'enregistrement du registre),
hors périmètre de M9. Définitions des 9 indicateurs `A_DEFINIR_PAR_LE_PROPRIETAIRE` par leurs propriétaires.

## Tests

`departments/m09-strategic-intelligence/tests/test_semantique_metriques.py` (empreinte face à version entière ni périmée
ni compatible, aucun groupe fusionné, valeur non textuelle refusée), `test_metriques_executives.py` (17 indicateurs,
métriques M8 existantes dans le dictionnaire, aucun lignage sur capture refusée/partielle/future, aucun flottant),
`tests/test_m9_semantique_integre.py`, `tests/test_m9_indicateurs_cadrage_integre.py`, `tests/test_console_direction_m9.py`.

## Statut

PARTIAL : classement et registre vérifiés sur vraies mesures et vrai registre M8 ; réconciliation de version bloquée
chez M8.

## Prochaines étapes

1. M8 : relier version de registre et empreinte de définition ; M9 n'aura qu'à relire.
2. Propriétaires : définir ou refuser explicitement les 9 indicateurs à définir.
3. M5 : exposer une lecture T0 du cash libre réel si Nathan veut la voir en direction.
