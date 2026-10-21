# Cohortes de temps — couche pure et candidate inactive

R30, 2 octobre 2026. `m3_estimation.calibration_cohortes.construire_rapport`
calcule un rapport sur des observations **déjà préparées**. La fonction ne lit
aucun registre, n'expose aucune API et n'écrit aucun barème. Elle n'authentifie
ni les hashes fournis ni les drapeaux de liaison ou de chaîne valide. Une
candidate désigne ici une proposition descriptive inactive, sans gain terrain
prouvé et sans intervention d'un LLM.

Le [contrat de provenance R27](PROVENANCE-ESTIMATION-TEMPS.md) décrit le lien
durable entre devis et estimation. R30 ne raccorde pas ce lecteur aux WCT :
l'adaptateur réel, l'admission des faits et la qualification du sens M4 restent
à livrer. Le [lot R30](../programme/LOT-COHORTES-TEMPS.md) distingue ces limites
des vérifications locales déjà réalisées.

## Entrées et refus

L'appel reçoit une liste ou un tuple, une `coupure_utc` explicite et une
`protocole_version` non vide de 32 caractères au maximum. Aucune horloge n'est
lue. La limite est de 2 000 observations et 500 chantiers distincts normalisés;
son dépassement produit `refuse`.

Chaque observation possède exactement les champs attendus : identifiants WCT,
chantier, intervention et devis; début et complétion UTC; statut
`completed_verified`; service; quantité, unité, taux minutes/unité et version
du barème; durées estimée et réelle; bloc `preuve`. Celui-ci exige deux
SHA-256 minuscules de 64 caractères, `liaison_exacte=True`,
`chaine_m3_valide=True`, schéma 2, sémantiques estimée/réelle
`duree_ecoulee_intervention` et unités `minute`. Il s'agit d'attestations
fournies, dont cette couche contrôle la forme et la valeur déclarée.

Les durées signifient l'intervention, hors déplacement et pauses; ce sens
déclaré ne prouve pas une mesure réelle. La durée réelle est un entier strict
positif, au plus 1 000 000 minutes. Estimation et taux sont des `Decimal` ou
textes décimaux stricts positifs, au plus 1 000 000; la quantité est au plus
1 000 000 000. Les entrées décimales sont finies, limitées à six décimales et
16 chiffres; booléens et flottants sont refusés. La durée estimée doit égaler
exactement `quantité × taux`. Aucune conversion d'unité ni interpolation
n'est effectuée.

Une ligne invalide est exclue avec ses motifs. Un rejeu de même `wct_id` et de
contenu normalisé identique compte une seule observation. Un contenu divergent,
y compris une version invalide de la même identité, produit un conflit et
rend le rapport `refuse`, sans segments candidats. Ce contrôle par WCT ne
prouve pas l'absence de doublons métier entre identités WCT différentes.

## Coupure par chantier et segments exacts

La partition porte sur toutes les observations normalisées admissibles d'un
chantier : `fin_chantier=max(fins)` et `début_chantier=min(débuts)`.

| Condition | Partition |
|---|---|
| Toutes les fins sont `<= coupure` | Train |
| Tous les débuts sont `> coupure` | Holdout |
| `début_chantier <= coupure < fin_chantier` | Toutes les lignes du chantier exclues |

Un contrôle supplémentaire exige des ensembles de chantiers disjoints. Les
segments utilisent service, unité exacte, version de barème, quantité exacte
et taux source exact. Les décimaux numériquement égaux sont normalisés; aucune
bande découverte après observation, variable d'employé ou remontée d'un petit
segment vers un parent n'est ajoutée.

Le minimum global exige 30 observations retenues, au moins 20 chantiers train
et 10 holdout. Chaque segment candidat exige au moins 12 chantiers train et
8 holdout. Sous ces minima, le statut est `insuffisant`; aucun nombre candidat
n'est produit. Ces portes fixes ne garantissent pas une puissance statistique.

## Calcul, précision et sortie

Par partition et segment : médianes des durées, erreur signée `réel − estimé`,
erreur absolue, MAD des erreurs et P50/P80 nearest-rank; effectifs et étendue
des quantités sont explicites. L'ajustement est la médiane des résidus train
en minutes. Le taux descriptif est `taux source + ajustement / quantité`.
Le rapport compare le holdout de référence à son recalcul arithmétique avec
l'ajustement; cette comparaison fictive ne démontre aucune amélioration terrain.
Un taux non positif ou une durée holdout corrigée non positive empêche la
candidate du segment. `candidate_active` demeure `False`.

Tous les calculs publics utilisent un contexte Decimal **local de 64 chiffres**,
`ROUND_HALF_EVEN`, exposants −999 à 999, indépendant du contexte appelant.
Les exceptions Decimal interceptées produisent `calcul_decimal_invalide`.
Une division de taux non exacte est arrondie à cette précision et signalée
par segment et dans `arithmetique_decimal`; 64 chiffres de calcul ne représentent
pas 64 chiffres de précision terrain.

Le rapport conserve protocole, coupure, motifs, compteurs, identités WCT,
hash du chantier, hashes M3/M4 et partition, sans charges sources intégrales.
Son `rapport_sha256` est l'empreinte du contenu sérialisé, pas une signature
d'origine ni une chaîne inviolable. Les états sont `refuse`, `insuffisant` ou
`candidate`; aucun ne modifie prix, registre, estimateur actif ou modèle appris.

Sources : [module](../../departments/m03-estimation/src/m3_estimation/calibration_cohortes.py)
et [tests fictifs](../../departments/m03-estimation/tests/test_calibration_cohortes.py).
