---
name: rapport-analytique-quotidien
description: Procédure pour ingérer un snapshot d'un module, dériver ses métriques, détecter les signaux XmR et produire un rapport analytique ou le digest quotidien, sans jamais calculer un chiffre de tête.
---

# Produire un rapport analytique

1. Si le dictionnaire canonique n'est pas déjà en main, appelle `m8_compiler_dictionnaire`
   avec la racine des départements. Un `module_source` ou un `metric_id` absent du
   dictionnaire n'est PAS une métrique à inventer : signale l'absence, stop.
2. Rassemble : le snapshot reçu (`module_source`, `horodatage`, `valeurs` — toujours du
   texte), la liste des `metric_ids` à surveiller pour ce module, l'horodatage de référence
   (fourni par l'appelant, M8 n'a pas d'horloge) et le `n_minimal` XmR (fourni par l'appelant,
   jamais un défaut). N'en invente aucun.
3. Appelle `m8_rapport_metriques` une seule fois avec toutes les données. Ajoute `role` et
   `metric_ids_autorises` seulement si le rapport est destiné à un rôle nommé — un rôle sans
   liste est refusé (fail-closed), ce n'est pas une erreur à contourner.
4. Lis la réponse :
   - `etape` différent de `"complet"` → un `verdict` explique quoi corriger (snapshot refusé,
     ou `metric_id` non déclaré). N'insiste pas sans corriger l'entrée signalée.
   - `etape: "complet"` → présente chaque métrique avec sa provenance (`fraicheur`, `n`), puis
     les signaux XmR actifs (jamais les `DONNEES_INSUFFISANTES` comme une alerte).
5. Pour le digest planifié : n'ingère AUCUN nouveau snapshot ; appelle
   `m8_produire_digest_quotidien` avec les signaux déjà calculés dans la journée, et ne
   présente que `signaux_actifs`.
