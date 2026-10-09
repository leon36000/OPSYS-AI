# Qualification des ressources Core — 8 octobre 2026

Daté Toronto : 2026-10-08T20:30:23.817414-04:00. Parent exact `e041f3802f34890da76649225a5798464d9db5fd`. OPSYS-AI reste **PARTIEL**.

Le job [Core tests5 du parent](https://github.com/leon36000/OPSYS-AI/actions/runs/37862563225/job/113601724767)
s'est arrêté avec code 137 et `Killed`, après 655 lignes de cas réussis, sans résumé final ni diagnostic
d'assertion échouée. Le PID initial, l'émetteur et les compteurs OOM ne sont pas connus. Le marqueur de
cleanup suit l'attente du processus Vitest ; sa proximité ne prouve pas un défaut de cleanup.
L'ancien parent 20731 avait passé 167 fichiers et 2 728 tests avec quatre skips, sous les mêmes 8192/workers2.
Ces preuves sont conservées et ne qualifient pas le nouveau commit.

## Correction minimale et qualification

Les six shards rapides gardent leur sélection, leurs sources, leur configuration et leurs assertions.
Le seul step `test:fast` reçoit un worker explicite et 4096 Mio de tas Node. Retirer l'override donnerait
trois workers en CI Linux. Les reporters natifs verbose/GitHub sont conservés ; le reporter de ressources
déjà présent expose le pool effectif, les ressources du host et les événements des modules.
`logHeapUsage` mesure le tas, pas le RSS global. Pipefail conserve tout échec Vitest.
Le job `tests-opsys`, le build, les caches et les contrôles de génération restent identiques au parent.

| Exécution locale, Linux ARM / Node 24.16 | Résultat | Pic RSS arbre | Durée |
| --- | --- | --- | --- |
| Shard 5, 8192 Mio/workers2 | arrêt contrôlé par garde 7 Gio, −15 | 7 553 040 384 octets | 96,970 s |
| Même shard 5, 4096 Mio/worker1, CI=true | 167 fichiers, 2 731 réussites, un skip, 2 732 au total | 4 620 288 000 octets | 172,402 s |
| Commande avec les trois reporters, un fichier | Sept réussites | 4 164 825 088 octets | 14,701 s |

Les sources sont inchangées pendant chaque exécution ; les deux shards locaux ont la même empreinte.
Le shard complet utilise logHeapUsage ; la combinaison des trois reporters est qualifiée sur un fichier.
Le harnais échantillonne la somme des RSS des processus toutes les 0,5 s ; des pages partagées peuvent
être comptées plusieurs fois. Ces pics observés ne sont pas une mesure PSS ni un compteur OOM.
Les résultats locaux/runner diffèrent par architecture et version Node ; les3skips de différence avec
20731 ne sont pas attribués à une cause sans preuve. La baseline locale démontre une pression mémoire
dans la configuration historique, pas l'OOM du runner. [La spécification officielle GitHub](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)
annonce deux CPU et 8 GB de RAM pour Ubuntu 24.04 privé ; elle n'est pas une télémétrie de cette VM.
Un plafond de 4 Gio par isolate ne garantit pas un RSS agrégé inférieur à 8 GB.

Le garde de configuration est rouge avant correction, puis les 154 tests des quatre suites CI passent.
Ruff est vert et actionlint 1.7.12 valide les workflows ; ses contrôles externes ShellCheck/Pyflakes
sont désactivés dans cette invocation. Le premier smoke avec garde3Gio a interrompu le compiler :
c'est un rouge du harnais conservé, corrigé avec garde7Gio, pas un échec de produit.
La revue indépendante et son éventuel addendum de métadonnées sont inclus, sans écraser le diagnosticr1.

## Conservation et critères de sortie

Le registre rapproche les deux sources et leurs préimages. La capsule contient 60 membres,
SHA256 `fdef966b3bf170fac7f0c5688acca0d86e713056c546e5f0bb59c84b8b02bce4`, vérifiés au roundtrip avec manifeste excluant sa propre empreinte.
Les journaux rouges/verts et projections CI bornées restent distincts ; credentials, CLI brut,
bases et archivesCI brutes sont exclus. Le scan borné ne promet pas une absence absolue de secret.
Le contrôle initial de capsule a refusé le journal de baseline : son empreinte initiale correspond
exactement aux 499 934 premiers octets, suivis de 88 octets de clôture ajoutés tardivement. Ce préfixe,
le suffixe, le fichier complet observé et le reçu initial sont conservés dans un addendum distinct.
La capsule utilise le préfixe dont l'empreinte est conforme. La première préparation refusée est
tracée ; les huit autres journaux correspondent aux reçus. Le harnais n'établissait pas la fin de
tous les descendants au scellement de cette baseline interrompue. Aucune assertion verte n'en est déduite.

La CI du nouveau commit exact doit qualifier les six shards et leur durée, le build complet, les tests
OPSYS et la verticale réelle sur runner, PostgreSQL M10 et le `gates` requis. L'échec 137 du parent reste
visible. Aucune assertion supprimée, skip ajouté, rerun aveugle, force-push, fusion ou production.
La reprise T4.27-b sera poursuivie après cette qualification ; ses recherches préparatoires sont distinctes.
Les 104 références exclues du transfert, téléphone/N5 et frontières mémoire restent aux limites de l'audit
[de direction](../AUDIT-DIRECTION-2026-10-08/AUDIT-DIRECTION-2026-10-08-r1.md).
