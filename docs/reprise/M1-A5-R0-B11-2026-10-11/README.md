# Core natif A5 / R0 / B11 — qualification et publication privée

Mémoire arrêtée le 2026-10-11T02:17:00.272411-04:00 (Toronto). **Produit PARTIEL. Qualifications du socle fermées ; CI du nouveau commit à établir.**

Le registre conserve20 dispositions :19 chemins effectifs,5 nouveaux,1 auxiliaire byte-identique. La base reste `ab2613b0b64200335db6b9fc135577f510de8b6a`. Root a adopté trois annotations TypeScript dans deux modules et trois entrées CI. Le nouveau snapshot comprend43836 Sources/745655010 octets, SHA `3ed2e1557bc2ca9e07d8a706b4bc65222b8eda06451de81072246fbba181a0f7`. Root adopte les quatre documents de cette capsule pour le commit privé. Leur ajout change l’identité complète ; les43836 entrées qualifiées restent séparément liées au snapshot3ed2. Le commit publié et sa CI exacte sont suivis dans la PR [#623](https://github.com/leon36000/OPSYS-AI/pull/623), sans prétendre connaître ici un hash de commit auto-référentiel.

## Delta adopté et revue indépendante

`runtime-publication.ts:7` nomme explicitement le type `unique symbol` de la marque privée, sans l’exporter. `runtime-snapshot.ts:376–384` annote les signatures des deux lecteurs existants avec `RuntimeConfigPublicationReceipt | null`. Les affectations vers le même tracker, les contrôles, l’ordre, les retours et les permissions sont inchangés ; aucun cast nouveau. La comparaison TS6.0.3 des deux fichiers complets donne du JavaScript identique octet par octet (6219 et23086 octets), exit0/0,460s/RSS171524096, EOF/owners fermés. Elle ne valide ni le graphe ni l’émission DTS.

SHA actuels : publication `9368c56e55f4cb123a327ba91a5b592bdafed479510bed618ee49c2c75f71965` ; snapshot `9cc3f2033bcfa75b7061c05e4fdee54b406b59c766ca567d149bc69bd7600325` ; sélecteur `c682e30b5a3de111eb29610f8dfed53813a1c3f3266ca811c2821c455e7f2b72`. Les20 lignes du [registre](REGISTRE.json) portent leur SHA actuel et séparent leurs preuves historiques.

Le sélecteur contient désormais243 cibles uniques, toutes présentes : +3/−0 depuis240. Ajouts : `src/gateway/config-reload.operation-policy.test.ts`, `src/gateway/config-reload.decisions.test.ts`, `src/gateway/server-reload-handlers.hot-reload-status.test.ts`. Cela ferme l’omission dans la liste utilisée par `tests-opsys`, pas une preuve d’exécution en CI. La politique unit-fast exclut Gateway ; aucune compensation implicite invoquée.

## CI à établir — snapshot qualifié3ed2

**La CI du futur commit exact reste NOT_RUN.** La copie, le typage canonique, les24 suites, les styles18 et le build complet Core ont désormais des preuves fermées sur3ed2. L’ajout documentaire change l’identité complète ; Root lie le commit publié et sa CI séparément dans la PR. La campagne complète24 et les styles18 sont désormais fermés sur3ed2, avec la portée ci-dessous. Aucun PASS0c197 n’est transféré automatiquement au nouveau fullSHA. Aucun commit candidat/CI future n’est annoncé.

## Tests et styles actuels — acquis à l’addendum r5

La campagne native intégrée R est fermée : **1184 enregistrements passés sur24 fichiers entiers**, zéro échec/erreur/skip,200,714s/RSS5046603776, EOF/PIDFD et descendants observés fermés. Elle comporte1152 paires classe/titre distinctes et32 répétitions paramétrées ; ne pas annoncer1184 identités nommées uniques. Les quatre appels officiels `scripts/test-projects.mts` routent vers Gateway15 fichiers/932 cas, runtime-config5/88, secrets2/77 et channels2/87. Les fichiers sont disjoints et les JUnit/JSON concordent ; l'ancien current4 n'est pas ajouté une seconde fois.

Les trois suites ajoutées à CI243 sont réellement passées **localement** : operation-policy80, decisions10, hot-reload-status1. Le handler entier269 inclut les cas on-exit ; runtime-policy-owner19, auxiliaire20, restart8, snapshot37, secrets-state75 et receiver38 figurent dans cette campagne. Le log montre le propriétaire compilé natif11551 entrées/15717 sorties et sa vérification pour chacun des quatre groupes, avec réemploi de cache natif après le premier. Aucun nouveau census complet des dépendances/imports n'est revendiqué par cette lecture documentaire.

Les18 TS effectifs passent format strict2,444s/RSS174346240 et lint3,285s/RSS267689984, exit0. Le sélecteur et l'auxiliaire byte-identique restent hors styles18. Reçus/logs complets et JUnit sont liés au même fullSHA3ed2 avant/après ; l'auditeur vérifie les manifestes et les pins nommés, sans prétendre avoir refait une campagne de scan des43836 Sources sur disque. La portée est celle des tests exécutés, pas une preuve globale P0, OriginalC/allSenders, fournisseur, livraison SMS, build ou CI.

## Copie et typage actuels — addendum r6

Les27 exports copie et40 exports types ont été relus indépendamment. La copie physique x64 contient43836 Sources+93391 dépendances,4060 liens ; aucun changement lors du typage. L’oracle exécuté contrôle les modes canoniques644/755 ; les census portent les tailles/empreintes, sans champ mode. Les anciens clones, stamps et verrous restent préservés.

Le typage officiel `run-tsgo.mjs --project tsconfig.core.json --noEmit --incremental false --listFiles --pretty false` passe : **0 diagnostic**,79,710s/RSS5698412544,16306 chemins listés (13112 Sources/3194 dépendances) liés au census,13 productions requises présentes. Politique native TS7.0.2 throttled inchangée. Ce n’est ni une preuve de typage des fichiers tests exclus, ni une émission DTS. Logs/pins/EOF et descendants observés fermés ; wrappers distants revalidated_pid et transport/bootstrap PIDFD restent distingués.

## Build Core complet actuel — addendum r7

Les38 exports ont été rehashés et le log intégral714 lignes/86850 octets relu : **exit0,534,914s/RSS5979484160**, sans garde déclenchée, sous7GiB/900s. La commande canonique `build-all.mts full` conserve cache0, partition per-plugin, concurrence1 et heap5120MiB. Le build confirme18/18 groupes DTS,2/2 SDK et158 sous-chemins publics ; graphe de déclarations4232006/5315536 octets. UI assemblée :3969 modules,517 assets précompressés/1034 sidecars,543 lignes d’assets liées au census final.

Les43836 Sources,93391 dépendances et4060 liens initiaux sont inchangés. Ajouts autorisés uniquement :12342 fichiers/446 liens, post149569 fichiers/4506 liens/0bad. Les relations physiques des liens sont vérifiées, sans prétendre observer le syscall créateur. Les13 productions actuelles R correspondent aux pins du build ; cette revue ne refait pas un scan distant ni un scan complet R. Les modes sont contrôlés par le propriétaire de stage. Les trois stamps sont liés aux empreintes du post-census ; head/commit restent null, sans faux GitHEAD.

Le JS initial vaut371182/371332 octets (marge150). Le CSS initial vaut51165/51200 (marge35), avec l’avertissement advisory46080 **conservé**. Les avertissements eval de dépendances et externalisation navigateur node:path sont également conservés. Les seuils n’ont pas été relevés. La portée est compilation/assemblage ; pas téléphone/Expo, fournisseur, livraison SMS, OriginalC/allSenders ou permission P0 globale.

Les fermetures EOF/descendants observés et les stratégies revalidated_pid/PIDFD sont distinctes. Le typage sans émission0c197 et son build rouge TS2527/TS4023 restent historiques ; aucun résultat ancien n’est réécrit. Les avis de modèles ne remplacent ni ces preuves ni la future CI.

## Preuves historiques — exclusivement snapshot0c197

L’ancien snapshot `0c197d9329ff1f9834864cca8bbdcc07db6e958950588ec058780ea3fbc134bd` comprend43836 Sources/745654618 octets. Il demeure lié aux preuves suivantes :

- Copie physique PC1 puis TS7 canonique noEmit :0 diagnostic/16306 entrées,13 productions requises,61,860s/RSS5685719040. Aucun crédit d’émission DTS.
- Receiver R canonique :38 passes,23,170s/RSS3226345472 ; préparation compilée10598 entrées/15717 sorties, Sources stables.
- Quatre cas handler R canoniques :4 passes/265 désélectionnés,68,977s/RSS4919398400 ; ni269 cas complets ni rétroqualification F22.
- Format/lint18 : exit0 aux SHA historiques. A5 :165 enregistrements JUnit/7 suites,157 paires de titres distinctes. B11 Q47/config575 : PASS historiques limités, propriétaires natifs incomplets.
- Build complet : **CLOSED NONQUAL**, exit1/84,311s/RSS5021970432, aucun guard. DTS1/18 TS2527 sur la marque et TS4023 sur les deux exports. Sources/dépendances/liens stables ;7881 sorties partielles conservées. UI/CSS/stamps non atteints. Le nouveau correctif de types ne transforme pas ce rouge en vert.

Les preuves et leurs empreintes figurent dans [PROOF-SUMMARY.json](PROOF-SUMMARY.json). [RED-HISTORY.json](RED-HISTORY.json) est préservé byte-exact : aucun rouge ni résultat incomplet effacé. L’ancien `Source_after=null` n’est ni preuve de mutation ni preuve de stabilité. Les wrappers remote revalidated_pid et transport/bootstrap PIDFD ont des portées distinctes.

## Limites produit et historique

La publication native repose sur son instance privée, ses clones publiés et une lignée bornée. Le setter public SDK reste `void` ; aucune permission P0 globale n’est créée. L’epoch n’est pas restauré par rollback. Context3, leaf6, OriginalC et allSenders restent des dépendances de raccord/qualification ; le receiver ne prouve pas une livraison SMS au modèle.

OPSYS-AI reste PARTIEL : dix départements, Core OpenClaw, outils déterministes, permissions, dashboard, mobile quatre profils/hors ligne, avatars, mémoires métier/développement séparées ; verticale M7→M1→M2→M3→M4/M6→M5→M8/M9/M10. Cette orientation ne certifie pas tout le produit.

CI ab2613b0 historique uniquement :38 succès/2 skips Docker conditionnels, socle5873 passes/17 skips/1 warning. Les cinq cas PG locaux ne sont pas déduits passés du total runner. Les104 références exclues, supplément indisponible et conversations inconnues restent tels quels, sans prétendre leur disponibilité/retrait. Aucun flux modèle privé, auth ou census volumineux inclus. Root seul décide intégration et publication.
