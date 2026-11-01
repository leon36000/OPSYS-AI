---
name: analyser-et-prevoir-le-pipeline
description: Procédure pour analyser le pipeline commercial (taux, délai de cycle, valeur pondérée) et prévoir les volumes par intervalle, avec reçu rejouable, en refusant de conclure sous le seuil d'échantillon déclaré et en ne donnant jamais un chiffre sans son effectif.
---

# Analyser et prévoir le pipeline

Tout chiffre vient d'un moteur déterministe avec un reçu ; tu ne calcules jamais de tête.

1. **Analyser.** `m2_analyser_pipeline` rend le pipeline par statut, l'entonnoir, le taux de qualification, le taux de conversion
   des leads RÉSOLUS, le délai de cycle (jours), la probabilité de conversion par étape et la valeur pondérée avec son
   intervalle. Chaque mesure porte son effectif (`n`) et son seuil : cite toujours les deux.
2. **Sous le seuil, on ne conclut pas.** Une mesure à `valeur: null` avec un `refus` n'est pas « zéro » ni « faible » : c'est
   « pas assez de données ». Dis combien il en faut, n'estime rien à la place.
3. **La valeur pondérée** utilise la valeur DÉCLARÉE par le vendeur (estimation commerciale), jamais un prix de M3. Sans valeur
   déclarée : « non calculable, manque la valeur déclarée ».
4. **Prévoir.** `m2_prevoir_pipeline` (série hebdomadaire de leads ingérés, qualifiés, convertis ou perdus ; moyenne mobile ou
   lissage exponentiel ; horizon ; niveau d'intervalle ; graine) rend un INTERVALLE. Le « centre » est un repère, pas une promesse.
   Sous 12 semaines d'historique ou 20 événements, elle refuse : redis le refus et ce qu'il faut.
5. **Reçu.** `avec_recu` rend le reçu `recu-calcul.v1` ; `m2_rejouer_recu_commercial` le refait et dit s'il est identique. Un reçu
   compact (sans entrées) se vérifie mais ne se rejoue pas : relance l'outil avec les mêmes arguments.
6. Ces chiffres informent ; ils ne changent aucun statut, n'écartent aucun lead et ne promettent rien au client. Tout usage
   comptable ou budgétaire : À valider auprès d'un comptable (CPA) / professionnel qualifié.
