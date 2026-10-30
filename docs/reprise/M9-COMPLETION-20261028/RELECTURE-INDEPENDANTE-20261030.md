# Relecture indépendante du 30 octobre (commits `b51b38be`…`5fc21927`)

Relecture en lecture seule, par un agent distinct, des modules ajoutés pour la liaison M9.3, les contrats attendus,
le raccord Core du conseil et la qualification de planification. Démonstrations conservées :
`preuves-execution/revue-independante-20261030-demonstrations.py` (exécutable depuis la racine avec
`PYTHONPATH=departments/m09-strategic-intelligence/src`). Corrigé dans `d6bbd3dc`…`29aac432` ; régression `final5`.

| # | Constat (gravité) | Correction | Test |
|---|---|---|---|
| 1 | Vérificateur : une entrée et un dépôt sans lien (session, rôle, ordre) donnaient `COMPLETE` (grave) | R5 exige une entrée admin PUIS un dépôt de même session et même rôle | `test_r5_exige_entree_puis_depot_admis…` |
| 2 | Un dépôt dont la sortie était refusée par l'admission comptait comme cycle (grave, plausible) | la trace porte `issue` ; seul `ADMIS` ferme un cycle ; issue absente = écart | idem |
| 3 | Un agent réussissant un autre outil M9 (ouvrir, clôturer) passait (grave) | R1 : tout succès d'agent sur un outil `m9_*` est un écart | `test_r1_tout_succes_d_agent…` |
| 4–5 | Réservation sans identifiant, usage négatif, dépôt sans session, rôle non hachable (`TypeError`) | forme complète vérifiée ; défauts nommés, jamais d'exception non nommée | `test_r2_forme_complete…` |
| 6 | L'acteur `runtime` de la séquence était refusé | `ACTEURS` inclut `runtime` ; garde séquence ⊆ acteurs | `test_une_trace_fidele…` |
| 7 | Contrats : type non hachable → `TypeError` | contrôle de type avant appartenance | `test_types_non_hachables…` |
| 8 | Contradictions, doublons, total ≠ somme jugés conformes | règles entre champs (`_coherence`) | `test_incoherences_entre_champs…` |
| 9 | Dates impossibles, période inversée, montants et heures négatifs, `calculable` faux sans manque, octets pour textes | dates civiles réelles, décimaux non négatifs, textes = liste de chaînes non vides | idem |
| 10 | Révision liée inférieure mais absente du registre → `VERSION_PERIMEE` (faible) | hypothèse citée : M8 numérote 1..N sans trou (`registre_metriques.lister`) | docstring |
| 11 | `True == 1`, `1.0 == 1` → `COMPATIBLE` (antérieur au diff) | booléen ou flottant = `VERSION_NON_DECLAREE` | `test_une_version_booleenne…` |
| 12 | Borne des trois reprises non testée ; code de refus trop large | 4e reprise refusée (`TENTATIVES-EPUISEES`) ; `LEASE-PERIMEE` exact | `test_reprises_bornees_a_trois_prises…` |
| 13 | Verdict d'intégration sur une trace écrite à la main | événement dérivé de la réponse réelle de `Capacites` | `test_m9_raccord_core_conseil_integre.py` |

Non retenus comme défauts : groupes `COMPATIBLE` distincts pour une version entière et une empreinte liée (jamais
fusionnés, conforme au principe) ; unité non déclarée prise à la définition (comportement antérieur documenté).

Également corrigé hors relecture : les profils proposés du conseil n'ont plus d'outil que leur agent ne pourrait pas
appeler (`3b28afd5`), sans élargir de droits.

## Tableau consolidé au commit `a1fa7493` (13 constats + 3 écarts de la revue du coordinateur sur `328fbd88`)

Statuts : **CT** corrigé et testé · **OG** restant ouvert avec gate · **DJ** documenté et justifié.

| # | Constat | Statut | Commit | Preuve ou gate |
|---|---|---|---|---|
| 1 | Entrée et dépôt sans lien → `COMPLETE` | CT | `d6bbd3dc` | `test_r5_exige_entree_puis_depot_admis…` |
| 2 | Dépôt à sortie refusée compté comme cycle | CT | `d6bbd3dc` | même test (`issue` exigée, seul `ADMIS` ferme un cycle) |
| 3 | Succès d'agent sur un autre outil M9 non vu | CT | `d6bbd3dc` | `test_r1_tout_succes_d_agent…` |
| 4 | Réservation sans identifiant, usage négatif, dépôt sans session | CT | `d6bbd3dc` | `test_r2_forme_complete…` |
| 5 | Rôle non hachable → `TypeError` | CT | `d6bbd3dc` | `test_r2_forme_complete…` |
| 6 | Acteur `runtime` de la séquence refusé | CT | `d6bbd3dc` | `test_une_trace_fidele…` |
| 7 | Contrats : type non hachable → `TypeError` | CT | `214453b1` | `test_types_non_hachables…` |
| 8 | Contrats : doublons, total ≠ somme, liaisons contradictoires conformes | CT | `214453b1`, `a1fa7493` | `test_incoherences_entre_champs…` ; la partie « liaisons » a quitté ce module (remplacée par `preuves_definition`, où une même révision publiée deux fois est `REJ-HISTORIQUE-CORROMPU`) |
| 9 | Dates impossibles, négatifs, calcul faux sans manque, octets | CT | `214453b1` | `test_types_non_hachables…`, `test_incoherences…` |
| 10 | Révision liée inférieure mais absente du registre → périmée | CT | `0089537a` | remplacé : l'historique complet est exigé (`REVISION_INCONNUE`, `REJ-HISTORIQUE-TROU`) — `test_revision_inconnue_ou_historique_troue…` |
| 11 | `True`/`1.0` pris pour la version `1` | CT | `32f33a4f` | `test_une_version_booleenne_ou_flottante…` |
| 12 | Borne des trois reprises non testée | CT | `29aac432` | `test_reprises_bornees_a_trois_prises…` |
| 13 | Verdict d'intégration sur trace écrite à la main | CT | `d6bbd3dc` | événement dérivé de la réponse réelle de `Capacites` |
| R1 | Observation ancienne sans preuve propre rendue `COMPATIBLE` par une liaison globale | CT (consommateur) | `0089537a` | `test_historique_sans_preuve_propre…`, `test_une_empreinte_sans_preuve_propre…`, parcours intégré |
| R2 | A(v1)→B(v2)→A(v3) refusé ; révision choisie arbitrairement | CT (consommateur) | `0089537a` | `test_aba_une_meme_empreinte…`, parcours intégré |
| R3 | Révisions dictionnaire (famille/module/id) et surveillance (`metric_id`) transposables | CT (consommateur) + **OG** (producteur) | `0089537a` | `test_registres_jamais_transposes`, `test_collision_d_identifiants…` ; gate : publication M8 de l'historique et de la preuve par mesure, raccord commun du catalogue — coordonné par Root |

Non retenus comme défauts : groupes distincts pour version entière et empreinte (jamais fusionnés) ; unité non
déclarée prise à la définition (comportement antérieur, documenté).
