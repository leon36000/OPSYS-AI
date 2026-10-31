# Contrat successeur M8 → M9.3 : historique versionné des définitions et preuve propre par observation

**Côté consommateur M9 : livré et testé (`0089537a`). Côté producteur M8 : non intégré.** Le candidat privé GitLab
MR !1 (`d22e0ce0b455e80adecbb2484efa89899eafec01`) n'a pas pu être lu depuis cette session (proxy : `CONNECT tunnel
failed, response 403`) ; sa compatibilité avec ce contrat n'est donc PAS vérifiée. Root coordonne le producteur en
commits séparés. M9.3 reste PARTIEL.

## Pourquoi un successeur
La revue du coordinateur sur `328fbd88` a relevé trois écarts du premier contrat (liaisons globales) :
1. une ancienne observation sans preuve propre devenait `COMPATIBLE` dès qu'une liaison de même empreinte était publiée ;
2. une même empreinte à deux révisions était refusée, alors que le producteur conserve A(v1) → B(v2) → A(v3) ;
3. les révisions du dictionnaire YAML (clé famille/module/id) et du registre de surveillance (clé `metric_id`) pouvaient
   être transposées sans correspondance prouvée.
La projection de liaisons globales est **retirée** : l'outil `m9_rapprocher_metriques` ne lit plus `liaisons_versions`,
annonce `historique_definitions = NON_CONSOMME`, et toute mesure à empreinte y reste `VERSION_NON_COMPARABLE`.

## Ce que le producteur publie (proposition de format, à valider avec M8)
Pages d'historique, une par appel, toutes du même historique :
```json
{"registre": "dictionnaire|surveillance", "vue": "<sha256>", "total": 4, "depart": 0, "prochain_depart": 2,
 "publications": [{"cle": {"famille": "finance", "module": "m08", "id": "m8_marge_reelle_cad"}, "revision": 1, "empreinte": "<sha256>"}]}
```
- `cle` : `{famille, module, id}` pour `dictionnaire`, `{metric_id}` pour `surveillance` — exactement ces champs.
- `revision` : révision de PUBLICATION, 1..N sans trou par clé ; `empreinte` : identité du CONTENU de la définition.
- `vue` = SHA-256 du JSON canonique (clés triées, séparateurs `,` `:`, UTF-8) de `{"registre", "publications"}` dans
  l'ordre publié (`preuves_definition.vue_de`).

## Ce que porte chaque observation
`preuve_definition = {registre, cle, revision, empreinte}` : la définition sous laquelle CETTE valeur a été calculée.
L'empreinte doit égaler `version_definition` de l'observation et l'identifiant de la clé son `metric_id`.

## Verdicts (`preuves_definition.verifier_preuve`)
| Situation | Statut | Raison |
|---|---|---|
| Aucun historique consommé | `VERSION_NON_COMPARABLE` | `HISTORIQUE_ABSENT` |
| Empreinte présente dans l'historique, mais aucune preuve propre (historique sans preuve) | `VERSION_NON_COMPARABLE` | `PREUVE_PROPRE_ABSENTE` |
| Preuve de forme invalide (champs, clé sans module, révision 0, booléen…) | `VERSION_NON_COMPARABLE` | `PREUVE_MAL_FORMEE` |
| Preuve d'une autre empreinte ou d'une autre métrique que l'observation | `VERSION_NON_COMPARABLE` | `PREUVE_INCOHERENTE` |
| Preuve d'un autre registre que l'historique | `VERSION_NON_COMPARABLE` | `REGISTRE_DIFFERENT` |
| Clé absente (y compris homonyme d'une autre famille/module) | `VERSION_NON_COMPARABLE` | `CLE_INCONNUE` |
| Révision absente pour la clé | `VERSION_NON_COMPARABLE` | `REVISION_INCONNUE` |
| La révision prouvée porte une autre empreinte | `VERSION_NON_COMPARABLE` | `EMPREINTE_DIFFERENTE_A_CETTE_REVISION` |
| Preuve vérifiée à une révision antérieure (A/B/A : `meme_contenu_que_la_courante` dit si le contenu est identique) | `VERSION_PERIMEE` | — |
| Preuve vérifiée à la révision courante (recalcul explicitement lié) | `COMPATIBLE` | — |
Dans tous les cas `valeur_verifiee = false` : une preuve de définition ne prouve ni le montant ni une inférence.

## Refus de l'historique entier (`assembler_historique`)
`REJ-HISTORIQUE-PAGES` (forme des pages) · `REJ-HISTORIQUE-PAGINATION` (vue/total/registre différents entre pages,
départ non contigu, recouvrement, page manquante, dernière page non close, total ≠ reçu) · `REJ-HISTORIQUE-FORME`
(publication mal formée) · `REJ-HISTORIQUE-CORROMPU` (vue ≠ contenu, même révision publiée deux fois) ·
`REJ-HISTORIQUE-TROU` (révisions non contiguës depuis 1). Aucune réparation, aucun choix de révision.

## Preuves
- `departments/m09-strategic-intelligence/tests/test_preuves_definition.py` (historiques simulés) : A/B/A, historique
  sans preuve de même empreinte, recalcul lié, collision famille/module, registres non transposés, révision inconnue ou
  trouée, corruption (vue, doublon, forme), pagination (trou, recouvrement, autre vue, page non close, total faux),
  preuve mal formée sans exception, valeur jamais vérifiée.
- `tests/test_m9_semantique_integre.py` : mesure RÉELLE de M8 (empreinte calculée par M8, aucune preuve propre) →
  `HISTORIQUE_ABSENT` dans l'outil ; même mesure face à un historique simulé au format ci-dessus → sans preuve
  `PREUVE_PROPRE_ABSENTE`, recalcul lié `COMPATIBLE`, ancienne publication de même contenu `VERSION_PERIMEE`, homonyme
  d'un autre module refusé, révision inconnue refusée, page altérée `REJ-HISTORIQUE-CORROMPU`.

## Reste à faire (coordonné par Root)
Publication par M8 de l'historique et de la preuve par mesure ; ajout de la lecture au catalogue et au port privé
(`lecteurs_m9`, raccord commun) ; consommation dans `m9_rapprocher_metriques`. Rien de cela n'est activé ici.
