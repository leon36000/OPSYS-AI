# FIRST2 — runtime capturé à la création du registre

État : PARTIEL, snapshot qualifié et blocages avant publication sur le parent `76c77ead6b9d39582b2d57c0db17ebc8522937b5`. Date : 11 octobre 2026, Toronto. Le commit de cette tranche et sa CI restent inconnus avant publication normale dans la PR privée draft 623.

Le RED initial (session 9916 : 47 succès, 1 échec) montrait qu’un getter `runtime` commutant pouvait donner au resolver une valeur différente de celle liée à la création du registre. `registry-state.ts` capture désormais une fois cette valeur dans une WeakMap privée ; `registry-runtime.ts` la réemploie pour le canal, subagent et Proxy. Cette cohérence de construction n’accorde aucune permission.

La tranche comporte cinq chemins Git effectifs : deux produits, le test participant, le nouveau test state-coherence et le sélecteur CI. Le fichier historique registry-runtime.channel-ingress.test.ts est restauré identique au parent : ses 37 cas ne constituent pas un sixième changement. Le sélecteur contient 254 cibles uniques, dix ajouts ordonnés.

Les preuves liées à Source51d5 sont fermées : composite48 sur trois fichiers (channel9 de r4, puis registry37 et coherence2 de r5), 63 voisins sur sept fichiers, lint5 et format5, deux ordres d’import réels. Les propriétaires observés sont channels/plugins/unit-fast ; voisins : six plugins et un infra. Le typage canonique TS7 est vert, zéro diagnostic, 16 306 entrées liées dont 17 produits obligatoires. Les tests ne sont pas implicitement typés. Les imports prouvent l’initialisation des exports, pas l’absence de tout effet interne.

Le full build session90959 est fermé NONQUAL : exit143 après 474,574 s, interruption du superviseur « observed descendant identity could not be pinned », sans timeout ni dépassement RSS. Le PID refusé n’est pas enregistré : disparition, réutilisation ou lecture impossible restent inconnues. Les 18 DTS sont annoncés terminés ; UI, SDK et stamps finaux ne sont pas qualifiés. Le post-census indépendant confirme les sources, dépendances et liens originaux intacts. Les 9 785 fichiers et 446 liens générés partiellement sont conservés. Ce résultat rouge ne devient pas un PASS.

Le profil SMS sur ce Source reste bloqué par cette qualification complète ; les anciennes preuves Source9 ne le qualifient pas. Les deux présents documents sont ajoutés après qualification des 43 849 fichiers, sans changement supplémentaire de code. Ce snapshot précède le commit : une preuve externe lie ensuite ses 43 851 fichiers Git. La CI réussie du parent76 demeure historique ; la nouvelle CI doit porter le commit publié exact et peut lever le blocage Core sur ses runners.

Les rouges restent conservés : premier GREEN arrêté au RSS, format/lint max-lines, extraction des deux cas et refus JUnit multi-invocation r4. La correction conserve les assertions ; 48 n’est pas une unique campagne. Les modes des copies Q scellées ne décrivent pas les modes Git.

Avis modèles NONQUAL (629/648 mots hors plafonds), utiles uniquement après confrontation primaire ; aucun P1/P2 démontré dans ce périmètre. Les lecteurs externes peuvent encore relire le getter ; les deux cas nouveaux ne couvrent pas le Proxy. Naissance d’état ≠ H/M/T, keeper, appareil, provider ou verticale SMS livrés. Aucun crédit fonctionnel global n’en découle. Voir PREUVES.json et les références Q liées.
