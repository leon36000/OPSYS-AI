# Clôture indépendante — build complet PC1 Current18

**Build complet qualifié pour le snapshot exact compilé et son Core actuel.** Revue indépendante des 35 preuves exportées, de leur manifeste et du journal complet de 86 864 octets / 714 lignes. Aucune nouvelle exécution, connexion SSH, modification Source/Git ou consommation du dist local. `READBACK-r1.json`, les pins et le journal lisible donnent les faits vérifiés.

## Identité et conservation

Le snapshot `full-source-final.json`, SHA256 `098da3fa85222054c116a2e6a0d55b8e487f8fc34176f0dbd114b90d35d18856`, contient **43 803 fichiers Source**. Tous concordent avec les census PC1 pré/post. Les **36 398 fichiers Core** ont également été rehashés sur R actuel, sans écart, y compris Core4 : authority `9cdcdf22…`, claim-adapter `983f6cee…`, server-channels `f49c3bbf…`, task-runtime `9229118a…` (SHA complets dans le reçu).

Les trois écarts actuels parmi Source18 sont exactement `mobile/src/outbox/vidangeur.ts`, son test et `mobile/src/fichiers/envoiOrchestrateur.test.ts`, durcis **après** la copie. Ce build ne qualifie donc pas le dernier mobile. Son identité repose sur le snapshot, pas sur un HEAD inventé : frontière Git exit128/stdout vide, `.buildstamp.head=null` et `build-info.commit=null` ; les SHA des trois stamps correspondent au post-census.

Avant : **137 194 fichiers = 43 803 Source + 93 391 dépendances**, 4 060 liens. Après : **149 527 fichiers et 4 506 liens**. Aucun fichier ou lien préexistant modifié/supprimé ; zéro entrée `bad`. Les **12 333 fichiers ajoutés** sont uniquement dans OUTPUTS : 11 277 `core/dist`, 596 `core/dist-runtime`, 460 dans les 15 dist de packages. Les **446 liens nouveaux** respectent les préfixes et relations du propriétaire : 364 overlays runtime vers dist et 82 dépendances de plugins. Les relations sont contrôlées par le stage épinglé ; leur créateur syscall n’a pas été observé. Les 543 chemins d’assets imprimés existent au census final et leurs tailles affichées sont cohérentes avec une troncature à 0,01 kB (écart 0–9 octets), sans assimiler l’affichage à une empreinte.

Le census complet de l’ancien clone origine est identique avant/après : **149 509 fichiers / 4 506 liens**, SHA `d440b1c8ba28c4c5bbd15c9ac6888bd316c36334f94d4293b63ef44d7bcd0102`. Le stage fermé vérifie aussi les trois stamps c864, les pins runtime et les quarantaines historiques. Cela prouve ce périmètre d’immutabilité ; ce n’est pas un nouveau recensement intégral de tous les anciens clones c864/r2/r3. Aucun fichier de verrou `dist-artifacts.lock` ne subsiste dans le census du nouveau candidat ; les anciens verrous quarantinés sont conservés.

## Exécution et clôture

Commande canonique `scripts/build-all.mts full`, Node **24.16.0 Linux x64** épinglé `b2959781…`, environnement fermé ; `per-plugin`, concurrence unifiée1, cache0, heap5120 MiB. Plafonds : RSS7 GiB, 900 s, log48 MiB ; aucun install, renouvellement de lock ou allégement du graphe. Précondition observée juste avant lancement : RAM disponible **11 310 645 248** octets et disque **105 931 407 360**, au-dessus de 9/20 GiB. Les cinq pins de runtime/outils sont vérifiés par les stages avant/après ; aucune nouvelle invocation de version n’est revendiquée ici.

Précheck exit0 /36,028 s ; full **exit0 /561,904 s /RSS6 068 789 248** ; postcheck exit0 /33,904 s. Aucun guard ni failure. Les trois wrappers attestent leurs entrées stables, EOF et fermeture des propriétaires observés. Leur stratégie réelle est **`revalidated_pid`**, pas PIDFD. Les transports local et distant ont, eux, observé PIDFD et terminé sans timeout externe ni retry. Le full recense 69 processus observés ; ni absence de descendants non observés ni ventilation RSS par PID n’est déduite.

## Lecture complète du résultat

Les **18/18 partitions DTS**, **2/2 groupes SDK**, 15 plugins externes, garde CLI, 13 phases runtime-postbuild et UI se terminent. SDK : **158 sous-chemins**, graphe **4 228 379/5 315 536 octets**. UI : 3 969 modules transformés, **543 lignes d’assets**, 517 assets précompressés et 1 034 sidecars vérifiés. JS de démarrage **371 146 ≤ 371 332 octets**, sept requêtes ; CSS **51 165 ≤ 51 200**, marge **35 octets**. L’avertissement CSS au-dessus de la cible indicative46 080 reste explicite. Les avertissements `eval` de dépendances et `node:path` externalisé pour navigateur sont présents ; aucune erreur de compilation n’en découle dans ce run.

Cette clôture qualifie le build Core x64 complet. Elle ne constitue ni typage global autonome, ni tests métier, ni preuve OriginalC/OriginC, livraison SMS, Native, téléphone ou Expo. Les rouges ARM et précédents builds restent historiques, inchangés.
