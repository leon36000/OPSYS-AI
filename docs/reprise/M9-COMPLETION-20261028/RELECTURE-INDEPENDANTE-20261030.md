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
