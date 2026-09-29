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

# Mesurer un chantier terminé

M8 reçoit tout seul, par le bus, le chantier terminé (M4), le devis accepté (M3), la variance de
matériaux (M6) et la rentabilité du chantier (M5), et mesure le chantier à chaque arrivée. Pour le lire, appelle
`m8_lire_mesures_chantier` avec le `wct_id` (admin seulement).

- chaque mesure porte sa `version_definition` ; un chiffre sans elle n'est pas présentable ;
- une mesure `non_calculable` dit ce qui manque (`manque`, `detail`) et de quelle source : présente-la
  telle quelle. Ne la remplace jamais par un zéro, une moyenne ou une estimation de tête. La marge
  réelle reste non calculable tant que M5 ne l'a pas chiffrée (coût réel complet et facture connue) : le
  `detail` donne alors les codes de ce qui manque chez M5 ;
- `seuils_a_configurer` nomme les métriques sans seuil valide : aucune alerte n'existe pour elles.
  N'en fixe jamais un toi-même ; signale-le au propriétaire (`department.yaml`, `configuration`) ;
- `m8_performance_equipe` donne l'écart de temps de l'équipe, et par technicien seulement à l'admin
  authentifié. Présente-le comme un indicateur non punitif : aucun classement, aucune alerte, jamais
  un nom hors du rôle admin.

# Lire la vue exécutive

`m8_lire_vue_executive` (admin seulement, un paramètre facultatif : `aujourd_hui`, AAAA-MM-JJ, la date du jour de
l'appelant) remet au propriétaire l'entonnoir, la marge réelle des chantiers, le stock à commander et le cash libre. M8 reçoit tout seul, par le bus, les faits de M2 (lead reçu et
qualifié) et de M3 (devis envoyé, accepté, sans réponse). Présente la réponse telle quelle :

- chaque métrique de l'entonnoir porte sa `version_definition` et son `proprietaire` ; une métrique `non_calculable`
  dit ce qui manque (`manque`, détaillé une fois dans `manques`). Ne la remplace jamais par un zéro, une moyenne ou
  une estimation de tête. Sans aucun fait reçu (`sources` à zéro), l'entonnoir entier est non calculable : ce n'est
  pas « aucun lead », c'est « rien reçu » ;
- `sources` dit combien de faits M8 a reçus par événement et jusqu'à quel instant : c'est la fraîcheur de l'entonnoir ;
- `marge_reelle` est le texte que M5 a publié, chantier par chantier. N'additionne rien, ne calcule aucune moyenne
  ni aucun écart : si une marge est `non_calculable`, cite la `raison` (les codes de M5) ;
- `stock_a_commander` est ce que M6 met à la file du propriétaire, avec son résumé et son action proposée ;
  `seuils_a_configurer` vrai veut dire que M6 attend des seuils de réapprovisionnement ;
- `cash_libre` est le DERNIER constat que M5 a publié (`constat`), tel quel : montants en texte, `statut`, `manque`
  (« composante : code »), `reserves`, `lecture` et `mention` de M5, montant de chaque composante (`null` : M5 n'a pas pu
  la chiffrer). N'additionne, ne compare et n'arrondis rien. Donne `aujourd_hui` pour avoir l'`age` du constat ; sans
  lui l'âge est « non calculable » (dis-le, ne devine pas la date). Un `statut` non calculé (M5 dit « non calculable ») se
  présente comme tel avec ce qui manque, et `au_plus_cad` n'est pas de l'argent disponible. Sans constat (`statut` =
  `manque`), dis-le, renvoie à `m5_etat_tresorerie` (admin) et propose de faire constater le cash libre
  (`m5_constater_cash_libre`, décision du propriétaire) ; n'en invente aucun chiffre. `non_repris` dit ce que la vue ne
  reprend pas (source, fraîcheur, hypothèses) ; `composantes_omises` dit que la décomposition n'a pas tenu dans la
  réponse : `m5_etat_tresorerie` la rend ;
- `seuils.a_configurer` nomme les métriques de l'entonnoir sans seuil valide : aucun franchissement n'existe pour
  elles. N'en fixe jamais un toi-même ; le propriétaire le définit dans `department.yaml` (`seuils_entonnoir`) ;
- une liste plus courte que son total dit `reste` : ce qui ne tient pas dans la réponse est compté, jamais perdu.

# Lire la mesure par contenu

`m8_lire_mesures_contenus` (admin seulement) dit quels contenus de M7 amènent des leads, puis des devis. M8 reçoit tout
seul, par le bus, les contenus exportés (M7, avec leur clé `utm_content`), les leads qualifiés (M1, avec la clé qu'ils
portaient) et les devis (M3). Présente la réponse telle quelle :

- `metriques` : six métriques gouvernées, chacune avec sa `version_definition` et son `proprietaire` ; `valeur` est le
  total sur tous les contenus, et `entrees` dit ce qui l'explique : leads sans clé (`n_leads_sans_utm_content`), clé
  inconnue, clé ambiguë. Un lead sans clé n'est attribué à aucun contenu : ne le mets jamais sur un contenu ;
- `contenus` : une ligne par contenu, `suivi` dit comment il se mesure. `sans_lien` (aucun lien de suivi n'a porté sa
  clé : site absent du profil, ou message privé) et `ambigu` (deux contenus ont la même clé) donnent des décomptes vides :
  « non mesurable », pas zéro. Le plus utile d'abord ; `affichage.prochain_depart` donne la page suivante (`depart`) ;
- une métrique `non_calculable` dit ce qui manque (`manque`, détaillé une fois dans `manques`). Sans lead reçu de M1,
  « zéro lead » serait faux : c'est « rien reçu ». `sources` dit combien de faits M8 a reçus et jusqu'à quand ;
- **impressions et clics n'ont aucune source** : `m8_impressions_par_contenu` et `m8_clics_par_contenu` sont toujours
  non calculables, avec « manque source des impressions et des clics ». N'en invente aucun chiffre, ne les estime pas à
  partir des leads ; dis que le connecteur (statistiques des plateformes, Matomo) reste à décider ;
- M8 mesure, il ne décide pas : ne recommande pas de publier plus ou moins un contenu à partir d'un compte (M9 décide).
