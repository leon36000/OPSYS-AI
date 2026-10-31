# M9.9 — prévisions consolidées et tendances extrapolées

Statut : **PARTIAL** (une seule prévision de propriétaire : M5). [Architecture M9](M9-STRATEGIC-INTELLIGENCE-ARCHITECTURE.md) ·
[scénarios](M9-SCENARIO-PLANNING.md) · [table d'audit](M9-AUDIT-INITIAL-QUADRUPLE-A.md).

## Objectif

Montrer à la direction ce que les propriétaires ont **prévu** (versions, âge, réserves, ce qui n'est pas calculable),
et, séparément, une tendance extrapolée par le code à partir des valeurs capturées — étiquetée comme telle, jamais
présentée comme une prévision de propriétaire.

## Pourquoi

La définition produit est explicite : M9 consolide et interprète, le détail de trésorerie reste à M5. Une absence de
prévision ne doit pas devenir un chiffre de modèle ; une extrapolation doit dire sa méthode, ses bornes et ses limites.

## État actuel

- **Prévisions consolidées** (`previsions`, version `2026-10-28.1`) : quatre domaines. `tresorerie` (M5,
  `m5.prevision_tresorerie`) est la seule prévision publiée par un propriétaire ; `leads` (M2), `capacite` (M4) et
  `materiaux` (M6) restent `AUCUNE_PREVISION_PRODUITE`, propriétaire attendu nommé.
- **Tendances** (`tendances`, version `2026-10-29.1`) : projection déterministe d'un fait numérique d'une lecture,
  origine `tendance_extrapolee`, libellé « tendance extrapolée, pas une prévision de propriétaire ».
- L'incertitude de M5 n'est pas chiffrée (M5 ne publie ni intervalle ni probabilité) : elle est décrite par ses
  réserves et ses manques.

## Architecture

Prévisions (`previsions.consolider`) :

- statut du domaine trésorerie : `ABSENTE`, `AUCUNE_VERSION_UTILISABLE` (aucune capture complète et non
  contradictoire), `DISPONIBLE` ou `PERIMEE` (âge au-delà de `perime_apres_jours`, fourni par l'appelant) ;
- versions successives (au plus `max_versions`, 1 à 20) avec statut `COMPLETE`, `PARTIELLE`, `REFUSEE`,
  `CONTRADICTOIRE`, changements nommés entre versions (ex. statut d'alerte) sans différence d'argent ;
- faits cités en texte exact (`<lecture>#<rang>:p<page>.<chemin>`) : horizon, fin d'horizon, calculable, non calculable à
  partir de, statut d'alerte, première semaine en déficit, `prevision_id`, solde initial ; semaines lues et manquantes,
  réserves, encaissements non comptés, âge en jours. Refus : `REJ-PREVISION-VERSIONS`, `REJ-PREVISION-PEREMPTION`.

Tendances (`tendances.projeter`) :

- série : une valeur par capture acceptée, complète, non contradictoire et connue, pour une lecture, un chemin
  `resultat.…` sans joker et un jeu d'arguments ; abscisse = jour civil UTC de réception par M9 ;
- méthodes en `Decimal` : `moyenne_mobile` (3 dernières valeurs, à plat), `droite` (moindres carrés ordinaires),
  `saisonnier_naif` (seulement avec `saison_jours` fourni et au moins deux saisons complètes) ;
- intervalle = projection ± 1,96 × écart-type résiduel : approximation, pas une probabilité calibrée ; il ne s'élargit
  pas avec l'horizon ;
- horizons `7j`, `30j`, `13s`, `6m`, `12m`, `24m` ; un horizon au-delà de l'historique n'a pas de valeur
  (`HORIZON_AU_DELA_DE_L_HISTORIQUE`) ;
- minimum de 6 points (`HISTORIQUE_INSUFFISANT` en dessous), politique proposée non validée par Nathan ; série constante
  et abscisses identiques nommées ; valeur non numérique refusée avec son adresse (`REJ-TENDANCE-VALEUR-NON-NUMERIQUE`).

## Fichiers

[previsions.py](../../../departments/m09-strategic-intelligence/src/m9_strategic_intelligence/previsions.py),
[tendances.py](../../../departments/m09-strategic-intelligence/src/m9_strategic_intelligence/tendances.py),
`outils_previsions.py`, `outils_tendances.py`.

## Outils et pages de console

| Outil | Paramètres principaux |
|---|---|
| `m9_previsions_consolidees` | `connaissance`, `perime_apres_jours`, `max_versions` |
| `m9_projeter_tendance` | `lecture_id`, `chemin`, `connaissance`, `horizons`, `saison_jours`, `arguments`, `decimales` |

Lecture seule, admin strict. Panneau « Prévisions des propriétaires » de `/direction` (statut et propriétaire par
domaine) ; page `/direction/tendances` (formulaire lecture, chemin, connaissance, horizons, saison facultative, avec
l'avertissement que la tendance ne remplace jamais la trésorerie de M5). Les revues citent les prévisions à 4 et 13
semaines dans leurs sections dédiées.

## Données et registres

Lit `captures_strategiques` seulement ; rien n'est stocké. Chaque résultat porte un identifiant d'empreinte (rejouable).

## Workflows

1. Capturer `m5.prevision_tresorerie` (et, pour une tendance, plusieurs captures d'une même lecture dans le temps).
2. Consolider les prévisions à l'instant de connaissance ; fixer une péremption si on veut l'évaluer.
3. Projeter une tendance seulement avec un historique suffisant ; lire ses limites avant de la montrer.

## Intégrations

M5 (prévision de trésorerie ; le test intégré lit deux versions, dont une page de 26 semaines) ; toute autre lecture numérique
du catalogue pour les tendances (ex. totaux de `m2.leads`). Les scénarios (M9.8) restent séparés : une sensibilité
n'est ni une prévision ni une tendance.

## Risques

- Une tendance sur peu de points ou sur une série bruitée donne un intervalle trompeur ; la borne de 6 points est une
  proposition.
- L'abscisse est la réception par M9, pas l'instant métier : des captures irrégulières déforment la droite.
- Lire une tendance de trésorerie comme une prévision contredirait M5.

## Gates Nathan

Prévisions réellement produites par les propriétaires (leads M2, capacité M4, matériaux M6) ; validation de la politique
du minimum de points.

## Tests

`departments/m09-strategic-intelligence/tests/test_previsions.py` (domaines sans prévision sans chiffre, versions,
partielle non utilisable, refus), `test_tendances.py` (oracles calculés à la main, saisonnier, historique insuffisant,
aucun flottant, limites) ; `tests/test_m9_previsions_integre.py` (prévision réelle de M5, deux versions dont une page de
26 semaines), `tests/test_m9_tendances_integre.py` (droite des totaux réels de M2, refus vendeur et agent).

## Statut

PARTIAL : consolidation et extrapolation vérifiées ; trois domaines sans prévision de propriétaire.

## Prochaines étapes

1. Obtenir de M2, M4 et M6 une prévision publiée en lecture T0, puis l'ajouter à `DOMAINES` et au catalogue.
2. Faire valider par Nathan le minimum de points et la présentation de l'intervalle.
