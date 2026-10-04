# R20 — preuves des reprises (EN COURS)

Mise à jour documentaire le 1er octobre 2026 UTC. **Ce lot reste ouvert** : M3 R9 est archivé comme preuve historique dans r11 (48/49, échec documentaire); le pont M4/M5 reste hors collecte.
Les heures régulières M4 et les contrats horaires M5 sont intégrés; leur commande ciblée
complète r3 passe 4 962 cas, sans valider une nouvelle suite globale du produit. C01 possède maintenant une preuve locale
par appels TS natifs, sans Gateway ni tour LLM; cette portée est détaillée dans r9. Le socle intégré achevé porte
2324 PASS/84 SKIP, sources sélectionnées stables; le ciblé actionlint de 1 PASS est séparé.
Core couvre les 158 fichiers par six groupes distincts, avec cinq skips Windows.
Les anciens Core r2/r3 partiels, socle CFO rouge et M3 R7/R8 interrompus restent conservés
et qualifiés historiquement. Aucun résultat futur n’est certifié ici.
R20 est distinct de [R19 scellé](../R19-2026-09-30/README.md), qui n'a pas été modifié.

Les **1356 archives** sont des artefacts, pas un nombre de tests. [MANIFEST.json](MANIFEST.json)
consigne les chemins exacts, dates, SHA-256 brut et gzip, tailles, `mtime=0` et égalité après
décompression. Les copies source sont archivées comme preuves, sans modification de code actif.

| Preuve | Résultat | Portée |
|---|---:|---|
| [R5 manifeste](preuves/m3-revision-5-manifest.json.gz), [plan](preuves/m3-revision-5-plan.md.gz), [tests légers finaux](preuves/m3-revision-5-final-r5-tests.xml.gz) | 9 PASS | Six sources exactes. Les ciblés antérieurs de 9 cas sont conservés séparément, sans addition. Le scénario rouge R5 était défectueux : la copie ne contenait pas le test rouge. |
| [Nominal prix R5](preuves/m3-revision-5-nominal-prix-r5-prix.xml.gz), [log](preuves/m3-revision-5-nominal-prix-r5-prix.log.gz) | 1 PASS; 10/10 mutants | 301,069 s JUnit. Référence et dix mutants réellement exécutés, reçu durable exit 0 et captures identiques. Cette preuve est rattachée à R5; elle n'est pas un nominal R6 ou R7. |
| [Revue root R5](preuves/revue-m3-campagne-r5-root.md.gz) | Défaut de fixture | Absence du test rouge dans la copie de scénario. Le nominal prix et les ciblés légers ne couvraient pas cette branche. Original conservé. |
| [R6 manifeste](preuves/m3-revision-6-manifest.json.gz), [rapport corrigé](preuves/m3-revision-6-rapport.md.gz), [sources exactes](preuves/m3-r6-exact-archive-manifest.json.gz), [rapport original](preuves/m3-r6-exact-rapport-original.md.gz) | Reprise sur copie | Sept fichiers sources exacts, dont l'adaptateur. Copies conservées sous `revision-7/r6-exact` par le producteur; elles appartiennent à R6. Le rapport original disait neuf unitaires plus deux intégrations pour dix cas : correction explicite à huit plus deux, sans écraser l'original. |
| [R6 léger](preuves/m3-revision-6-light-r6-light.xml.gz), [log](preuves/m3-revision-6-light-r6-light.log.gz) | 10 PASS | Huit tests unitaires et deux intégrations, 0 échec/erreur/saut, 0,915 s JUnit. Module sans garde et réconciliation des captures de source. |
| [R6 référence rouge finale](preuves/m3-revision-6-final-r6-red.xml.gz), [log](preuves/m3-revision-6-final-r6-red.log.gz), [revue root](preuves/m3-r6-revue-root-2026-10-01.json.gz) | 1 PASS; 2 processus | 55,071 s JUnit. Mutateur prix et énumérateur abandonnent sur la référence volontairement rouge, chacun exit 1. Le test relit ensuite les mêmes reçus avec `processus_lance_ici=False`; ce réemploi n'est pas présenté comme une exécution supplémentaire. La reprise antérieure de 54,929 s reste distincte. |
| [Contrôle documentaire](preuves/r20-m3-r5-r6-capture.json.gz) | Lecture seule | Checksums des trois reçus principaux, captures avant/après et six/sept copies source concordantes. Aucun test lancé par le collecteur. Les alias dans les captures ne sont pas un compte de fichiers physiques uniques. |

Les refus rouges R6 ne prouvent pas dix mutants nominaux : `0/10 mordent` reflète l'abandon sur
une référence déjà rouge. Deux outils rouges ont été réellement exercés; pas l'ensemble des dix.
Le budget **126 sous-pytests** et l'économie face au budget historique 273 restent estimés pour
R5/R6. Aucun gain de campagne complète n'est mesuré par cette collecte.

Les groupes se recouvrent et gardent leur compte propre. Aucun total cumulé avec R19, les suites
départementales ou les futures reprises. Le collecteur effectue seulement des lectures et de
l'archivage. Les épreuves M3 utilisent des copies et des sous-processus Python, sans prouver un
déploiement. Les producteurs CFO/Core ont exercé le HTTP Python loopback réel, et le socle a
lancé de vrais conteneurs PostgreSQL; leurs résultats, dont les échecs, sont conservés.

## Grant CFO — intégration et preuves distinctes

| Preuve | Résultat | Portée |
|---|---:|---|
| [Backend r2](preuves/cfo-grant-rapport-final-r2.md.gz), [manifeste](preuves/cfo-grant-hashes-scratch-r2.sha256.gz), [log](preuves/cfo-grant-tests-cfo-final-r2.log.gz) | 28 annoncés verts | Prototype sur copie, log sans JUnit ni durée native conservée. Stockage/migration r1 : 24 annoncés verts, preuve distincte réutilisée, pas somme. Manifestes des sources et historique r1 conservés. |
| [Core r3](preuves/cfo-grant-core-client-r3-resultat.json.gz), [patch](preuves/cfo-grant-core-client-r3.patch.gz), [log final](preuves/cfo-grant-core-client-r3-vitest-final-r3.log.gz) | 12 annoncés verts | Loopback MCP privé puis handler canonique M5 sur copie. Typecheck incrémental ciblé, aucun graph global; les anciennes reprises restent séparées. La mention de 27 Python dans le rapport Core précède la preuve backend r2 de 28. |
| [Revue d'autorité r2](preuves/revue-cfo-autorite-r2.md.gz), [intégration root](preuves/cfo-grant-integration-root-r1.json.gz) | Lecture; 18 fichiers exacts | 11 backend/tests + 7 Core intégrés, onze préimages archivées et vérifiées. Pas de commit/déploiement ni migration d'une base métier réelle. Les rapports «scratch» décrivent leurs captures antérieures, sans annuler cette intégration ultérieure. |
| [Console RED r1](preuves/cfo-console-red-root-r1-2026-10-01.xml.gz), [RED r2](preuves/cfo-console-profils-root-r2-2026-10-01.xml.gz), [GREEN r3](preuves/cfo-console-profils-root-r3-2026-10-01.xml.gz), [résultat r3](preuves/cfo-console-profils-root-r3-2026-10-01-resultat.json.gz) | 1 FAIL → 3 PASS/1 FAIL → 4 PASS | RED initial : UI de grant absente avant intégration. R2 : fixture conservait une révision 1 après activation qui avait créé la révision 2. R3 relit la révision canonique, 0F/E/S, 2,424 s JUnit. Snapshots distincts : 1023 puis 1034 chemins, stables durant chaque run. |
| [Core actif root](preuves/cfo-core-actif-root-r1-2026-10-01.xml.gz), [résultat](preuves/cfo-core-actif-root-r1-2026-10-01-resultat.json.gz) | 12 PASS | Deux fichiers Vitest, HTTP Python loopback réel et unité. 1034 empreintes avant/après identiques; 1,791 s est la somme des durées JUnit des deux fichiers, pas la durée murale de la commande. Recoupe la preuve Core sur copie. |
| [M5 complet post-grant](preuves/m5-cfo-integre-root-r3-2026-10-01.xml.gz), [résultat](preuves/m5-cfo-integre-root-r3-2026-10-01-resultat.json.gz), [avant](preuves/m5-cfo-integre-root-r3-2026-10-01-avant.json.gz), [après](preuves/m5-cfo-integre-root-r3-2026-10-01-apres.json.gz) | 2028 PASS | 0F/E/S, 117,113 s JUnit, 1034 empreintes sélectionnées identiques avant/après. Full actif distinct du full CFO de R19; les ciblés précédents se recouvrent, aucun total additionné. |

Le droit CFO ne concerne que les deux outils préparatoires et SQLite mono-instance. Il dépend du
bearer MCP réservé au Core de confiance : une compromission du Gateway obtenant ce bearer sort de
cette frontière. La plage porte sur la date du rapport, sans filtrer les lignes historiques; le quota
compte les tickets émis. Un clone/restauration conserve l'UUID de la base et ne crée pas une frontière
multitenant. `profileRevision` ne certifie pas le provider/modèle/fallback finalement sélectionné.
La revue de code/configuration n'est pas une preuve de bac OS/Docker réellement déployé.

## M3 R7 — résultat partiel conservé

[Rapport](preuves/m3-r7-revision-7-full-rapport-interrompu.md.gz),
[manifeste](preuves/m3-r7-revision-7-full-r7-manifest.json.gz),
[JUnit](preuves/m3-r7-revision-7-full-r7-full.xml.gz),
[log](preuves/m3-r7-revision-7-full-r7-full.log.gz),
[trace](preuves/m3-r7-revision-7-full-r7-execve.log.gz).

42 cas collectés; 12 cas annoncés réussis avant KeyboardInterrupt/exit 2. L'XML contient un
treizième élément non finalisé, sans lui attribuer de réussite. 256,298 s JUnit contre 257,28 s
console. Les 1705 entrées de fermeture sont identiques avant/après. La trace documente sept
`python -m pytest` démarrés, dont le parent et six enfants; cinq reçus complets, dernier outil
`muter_digest` interrompu sans reçu final.

Le prix rouge a été relancé : même commande et fermeture, mais clé d'environnement différente.
Le hash de tout `os.environ` inclut `PYTEST_CURRENT_TEST`, variable différente entre consommateurs,
et empêche le partage attendu. Les cinq reçus et le diagnostic sont conservés. **R7 ne valide pas
la campagne et ne prouve aucun gain de coût.** La correction R8 sur une image distincte reste en cours. Le socle CFO complet rouge est
désormais archivé ci-dessous, sans convertir les résultats partiels M3 en succès global.

Le [contrôle documentaire r2](preuves/r20-cfo-m3-r7-capture-r2-2026-10-01.json.gz) relit les JUnit,
empreintes et reçus sans lancer de test. Les 47 archives initiales et tout R19 restent inchangés.

## Socle CFO complet rouge et reprises ciblées

| Preuve | Résultat | Portée |
|---|---:|---|
| [Socle CFO r3 JUnit](preuves/socle-cfo-integre-root-r3-2026-10-01.xml.gz), [résultat](preuves/socle-cfo-integre-root-r3-2026-10-01-resultat.json.gz), [avant](preuves/socle-cfo-integre-root-r3-2026-10-01-avant.json.gz), [après](preuves/socle-cfo-integre-root-r3-2026-10-01-apres.json.gz), [log](preuves/socle-cfo-integre-root-r3-2026-10-01.log.gz) | **2282 PASS / 3 FAIL / 35 ERROR / 83 SKIP** | 2403 cas, exit 1, 1743,215 s JUnit. 1034 empreintes sélectionnées identiques avant/après. Résultat complet rouge, aucun socle vert déduit des ciblés suivants. |
| [Raccord fixtures r4](preuves/cfo-raccord-fixtures-root-r4-2026-10-01.xml.gz), [résultat](preuves/cfo-raccord-fixtures-root-r4-2026-10-01-resultat.json.gz) | 45 PASS | Cinq fichiers ciblés, 0F/E/S, 13,691 s JUnit; 1034 empreintes sélectionnées stables. Corrige deux attentes de fixture du full rouge, sans remplacer sa portée et sans résoudre les 36 cas PostgreSQL indisponibles. |
| [Lint RED r1](preuves/lint-cfo-integre-root-r1-2026-10-01.log.gz), [résultat r1](preuves/lint-cfo-integre-root-r1-2026-10-01-resultat.json.gz), [GREEN r2](preuves/lint-cfo-integre-root-r2-2026-10-01.log.gz), [résultat r2](preuves/lint-cfo-integre-root-r2-2026-10-01-resultat.json.gz) | exit 1 → exit 0 | Ruff `src tests departments` : import inutilisé, puis contrôle global Python vert. Aucun compte de tests; captures sélectionnées 1034 stables dans chaque run. |
| [Diagnostic PostgreSQL](preuves/socle-postgres-diagnostic-root-r3-review.md.gz) | Cause non résolue | 35 erreurs et un échec PostgreSQL liés à quatre services sortis avec code 1. Journaux perdus après auto-suppression; pression disque observée ensuite plausible, sans preuve causale. Aucun OOM observé dans la fenêtre consultée, sans garantie générale. Pas de conversion en skips ni reproduction exécutée par cette revue. |
| [Addendum autorité CFO r3](preuves/revue-cfo-autorite-r3.md.gz) | Lecture seule | Référence recalée sur le manifeste backend r2 et sa preuve de restauration des grants/tickets/historique. Les anciennes revues restent intactes; aucune suite indépendamment relancée par l'auteur de l'addendum. |

## Core — prévol arrêté et régression de fixture

| Preuve | Résultat | Portée |
|---|---:|---|
| [Core 158 r1](preuves/core158-r1-result.json.gz), [index natif](preuves/core158-r1-vitest.json.reports-PnrTRm-index.json.gz), [diagnostic observé](preuves/core158-r1-runner-diagnostic.txt.gz), [log partiel](preuves/core158-r1-run.log.gz), [sources avant](preuves/core158-r1-sources-before.sha256.gz), [après](preuves/core158-r1-sources-after.sha256.gz) | **0 tests lancés**, exit 1 | 158 fichiers cibles et 22 invocations planifiées, toutes `unstarted`. Prévol E2E exigeait un build; `tsdown` s'arrête avant Vitest parce que la limite mémoire cgroup n'est pas visible et aucun plafond explicite n'était fourni. Manifestes identiques de 22346 entrées. Aucun JUnit produit. Le log brut complet manque à cause d'un mauvais chemin tee; le diagnostic observé est distinct du log partiel et ne le reconstitue pas. |
| [Hook C02 JUnit](preuves/core-c02-hook-junit.xml.gz), [résultat](preuves/core-c02-hook-resultat.json.gz), [patch de fixture](preuves/core-c02-hook-mcp-call-meta-test.patch.gz) | 8 PASS / 1 FAIL | Trois fichiers ciblés, neuf cas, zéro erreur/saut. Le test de métadonnées omettait personne/rôle et rencontre le refus d'identité incomplète; les deux cas HTTP ticket cible passent. Huit empreintes avant/après identiques. Patch complète l'identité synthétique et exige une égalité stricte; son existence ne certifie pas la portée globale Core 158. |
| [Contrôle documentaire r3](preuves/r20-socle-core-diagnostics-capture-r3-2026-10-01.json.gz) | Lecture seule | JUnit comptés, snapshots et index natif relus. Aucun test/build/Docker lancé; 149 archives antérieures et tout R19 préservés. |

## Core r2 qualifié et reprise r3 partielle

| Preuve | Résultat | Portée |
|---|---:|---|
| [Core r2 original](preuves/core158-r2-result.json.gz), [XML original](preuves/core158-r2-junit-partial.xml.gz), [qualification](preuves/core158-r2-qualification-r2-correction.json.gz), [XML qualifié](preuves/core158-r2-junit-partial-qualified.xml.gz), [résultat final](preuves/core158-r2-result-final.json.gz) | **1073 PASS / 5 FAIL / 1 SKIP** | 1079 assertions dans quatre rapports natifs; 18/22 projets non lancés, exit 1. Les exports originaux 1074P/0S sont conservés avec leur défaut de conversion, pas certifiés. Aucune exécution supplémentaire pour corriger les métadonnées. |
| [Cinq cleanup/subreaper](preuves/core158-r2-tooling-5-r3.json.gz), [log](preuves/core158-r2-tooling-5-r3.log.gz), [commande](preuves/core158-r2-tooling-5-r3-command.txt.gz), [launcher](preuves/core158-r2-child-subreaper-r3.py.gz), [qualification ciblée](preuves/core158-r2-result-r2-final.json.gz) | **5 PASS** | Les cinq cas ayant échoué sont sélectionnés; 236 autres assertions filtrées dans les deux fichiers, sans les compter comme exécutions réussies. Launcher init externe et neuf descendants récoltés; aucun changement source/test Core. 22346 entrées de manifeste identiques avant r2, après r2 et après ciblé. |
| [Core r3 log final](preuves/core158-r3-run.log.gz), [index natif](preuves/core158-r3-vitest.json.reports-swCKWt-index.json.gz), [commande](preuves/core158-r3-command.txt.gz), [sources avant](preuves/core158-r3-sources-before.sha256.gz) | **1078 PASS / 1 SKIP observés; run exit 1** | Quatre projets ont un rapport d’assertions achevé sans échec. L’index compte une cinquième tentative Gateway terminée code 1 mais sans rapport JSON/blob, puis 17 projets non lancés. Collecteur JSON bloqué : aucun résultat Gateway ni succès de suite complète. Aucune capture source après n’était disponible lors de cette collecte. |

Les [rapports natifs r2](preuves/core158-r2-vitest.json.reports-6fvLle-index.json.gz) font foi pour les
statuts. Les zombies PPID 1/RSS 0 expliquent le diagnostic proposé des cinq attentes de nettoyage,
sans rendre la campagne r2 verte. La reprise ciblée sous subreaper et les quatre projets r3 se
recouvrent; leurs comptes ne s’ajoutent pas.

## PostgreSQL — reproduction unique, fixture puis reprise ciblée

| Preuve | Résultat | Portée |
|---|---:|---|
| [Rapport r4](preuves/postgres-fixture-r4-resultat.md.gz), [reproduction](preuves/postgres-fixture-r4-reproduction-pgvector-pg17-one-shot-20261001T032659Z.json.gz), [hashes](preuves/postgres-fixture-r4-hashes-r4.json.gz) | **SELECT 1 → 1** | Un seul conteneur réel PostgreSQL 17.11/image pgvector locale; état et logs expurgés capturés avant retrait avec volume anonyme. Ancien chemin r4 docker run. Ne détermine pas la cause des quatre anciennes sorties code 1 et ne valide pas à lui seul le chemin r5 create/start. |
| [Fixture r5](preuves/postgres-fixture-r5-resultat-r5.md.gz), [patch](preuves/postgres-fixture-r5-fixture-and-tests-r5.patch.gz), [log simulé](preuves/postgres-fixture-r5-tests-r5-20261001T0406Z.log.gz), [hashes](preuves/postgres-fixture-r5-hashes-r5.json.gz), [intégration root](preuves/postgres-fixture-r5-integration-root-r1.json.gz), [préimage](preuves/postgres-fixture-r5-preimage-integration-root-r1-tests-fixtures-memoire-doubles.py.gz) | **5 PASS simulés** | Création/démarrage/port/readiness/nettoyage et expurgation, 0,05 s console; pas de JUnit ni PostgreSQL r5 réel dans ce ciblé scratch. Deux fichiers intégrés exactement par root ensuite; rapport scratch antérieur conservé. |
| [Ciblé actif](preuves/postgres-fixture-cas-affectes-root-r1-2026-10-01.xml.gz), [résultat](preuves/postgres-fixture-cas-affectes-root-r1-2026-10-01-resultat.json.gz), [avant](preuves/postgres-fixture-cas-affectes-root-r1-2026-10-01-avant.json.gz), [après](preuves/postgres-fixture-cas-affectes-root-r1-2026-10-01-apres.json.gz), [correspondance](preuves/postgres-36-correspondance-root-r1-2026-10-01.json.gz) | **47 PASS / 0F/E/S** | 20,426 s JUnit; 1027 fichiers Python sélectionnés stables, sans les extras Core des anciens snapshots. Inclut les cinq tests simulés fixture; les 36 anciens cas PG en échec/erreur sont tous présents et passés sous les mêmes identifiants classname/name. Ne remplace pas le socle complet rouge. |

## M3 R8 et préparation paie

[Rapport R8](preuves/m3-r8-r8-partial-report.md.gz), [manifeste](preuves/m3-r8-r8-manifest-before.json.gz),
[avant](preuves/m3-r8-r8-before.json.gz), [après partiel](preuves/m3-r8-r8-after-partial.json.gz),
[log figé](preuves/m3-r8-r8-final.log.gz), [trace figée](preuves/m3-r8-r8-execve.log.gz).

R8 a disparu sans cause ni code de sortie établi : **28 marqueurs dans le log ne constituent pas
28 tests validés**. Aucun XML final et aucun reçu de campagne persistant. Trace : 90 lignes execve
pytest, 89 PID uniques; 87 sorties enregistrées (76 code 1, 11 code 0), outer et dernier enfant
sans fin enregistrée. Ces sorties enfants ne constituent pas un verdict de mutations. Les 1705
entrées avant/après et les six sources exactes archivées concordent; aucune campagne complète ni
économie mesurée. La [tentative combinée antérieure](preuves/m3-r8-r8-combined-interrupted.md.gz),
interrompue après modification source concurrente, reste un historique non probant.

[Paie Québec — rapport](preuves/paie-qc-2026-rapport.md.gz),
[provenance](preuves/paie-qc-2026-provenance-r1.json.gz),
[vérification documentaire](preuves/paie-qc-2026-verification-livraison-r1.json.gz).

Dix requêtes directes, dix HTTP403, aucun PDF brut Québec obtenu. Les onze captures Exa de pages
officielles épinglent du texte nettoyé, pas les octets des tables PDF. Quatre sources ARC R16
rehashées conformes; dates CCQ/FSS/RQAP et guide RL‑1 encore millésimé 2025 qualifiés. Aucun barème
copié dans du code ni moteur de paie livré; première tranche préparatoire et données manquantes
décrites. Les corps HTTP403 archivés ne sont jamais traités comme tables officielles.

Le [contrôle documentaire r4](preuves/r20-core-pg-paie-m3-capture-r4-2026-10-01.json.gz) consigne
les lectures indépendantes de comptes natifs/JUnit, les identifiants PG et la conservation des
190 archives antérieures et de tout R19. Aucun test ou service lancé par ce collecteur.

**R20 demeure EN COURS** : campagnes Core/M3 et validation globale du socle non finalisées.
Aucun total cumulé ni verdict global de succès; preuves rouges, interrompues et ciblées gardent
leur portée et leurs versions distinctes.

## Collecte r5 — M5.10a et M10 achevés, portée séparée

Le [snapshot avant r5](preuves/r20-entry-index-before-r5-2026-10-01.json.gz) conserve les 314 IDs et
hashes antérieurs. [MANIFEST r4](preuves/r20-r4-manifest-before-r5-2026-10-01.json.gz),
[README r4](preuves/r20-r4-readme-before-r5-2026-10-01.md.gz) et
[lecteur root r4](preuves/r20-lecteur-independant-root-r4-2026-10-01.json.gz) sont figés.
Les 314 archives et sources brutes restent identiques; R19 reste scellé. Core, M3 R9 et documents
actifs mutables sont exclus de r5.

| Preuve | Résultat | Portée |
|---|---:|---|
| [M5.10a manifeste](preuves/m510a-final-final-manifest.json.gz), [patch](preuves/m510a-final-M5-10a-final.patch.gz), [RED précision/budget](preuves/m510a-final-red-precision-budget-r1.log.gz), [GREEN ciblé](preuves/m510a-final-green-regression-r6.xml.gz), [relecture root](preuves/m510a-relecture-root-r1-2026-10-01.json.gz) | **601 PASS / 0F/E/S** | 48,785 s JUnit sur dix modules pertinents scratch, pas full M5. Huit sources exactes, six préimages vérifiées; patch bbf0232b…; RED conservé. |
| [Promotion M5.10a](preuves/m510a-integration-root-r1-integration.json.gz), [suite active](preuves/m5-scenarios-integres-root-r1-2026-10-01.xml.gz), [résultat/commande](preuves/m5-scenarios-integres-root-r1-2026-10-01-resultat.json.gz), [avant](preuves/m5-scenarios-integres-root-r1-2026-10-01-avant.json.gz), [après](preuves/m5-scenarios-integres-root-r1-2026-10-01-apres.json.gz) | **2071 PASS / 0F/E/S** | 2037 département M5 + 34 socle, 134,333 s JUnit; 1029 chemins sélectionnés de plusieurs formats stables. Full M5 et quatre modules socle, pas full socle ou Core. |
| [Commande incorrecte r1](preuves/m5-scenarios-manifestes-root-r1-2026-10-01-resultat.json.gz), [log](preuves/m5-scenarios-manifestes-root-r1-2026-10-01.log.gz), [CLI r2](preuves/m5-scenarios-manifestes-root-r2-2026-10-01-resultat.json.gz), [log r2](preuves/m5-scenarios-manifestes-root-r2-2026-10-01.log.gz) | **exit 1 → exit 0** | R1 : appel erroné de `python -m opsys` avec l'argument `verifier`, sans opsys.__main__. La commande exacte reste dans la preuve r1. R2 : opsys-metier verifier, 195 outils, 111 déclarés aux appareils; autres fermés. Aucun compte pytest; snapshots 1029 stables. |
| [M10 r4 résultat](preuves/m10-selection-r4-final-resultat-r4.json.gz), [rapport](preuves/m10-selection-r4-final-rapport-r4.md.gz), [log](preuves/m10-selection-r4-final-tests-r4.log.gz), [RED losange](preuves/m10-selection-r4-red-diamond.log.gz), [patch source](preuves/m10-selection-r4-final-patch-cumulatif-developpement-vers-actif-r4.diff.gz), [patch tests](preuves/m10-selection-r4-final-patch-cumulatif-tests-vers-actif-r4.diff.gz), [hashes](preuves/m10-selection-r4-final-hashes-r4.sha256.gz) | **36 PASS par log** | 35 tests copiés r3 + losange de convergence; 8,66 s console, pas de JUnit ciblé. DFS distingue convergence/vrai cycle, plafonds conservés; deux sources exactes. **E05 reste précision30/30, rappel30/32, cible0/1**, pas un score global. |
| [Promotion M10](preuves/m10-selection-integration-root-r1-integration.json.gz), [actif RED r1](preuves/m10-selection-integree-root-r1-2026-10-01.xml.gz), [résultat](preuves/m10-selection-integree-root-r1-2026-10-01-resultat.json.gz) | **972 PASS / 2 FAIL / 0E/S** | 974 cas, 37,774 s JUnit. PG : initdb No space left on device visible dans ce run, sans attribution aux anciens logs PG perdus; console : horloge réelle avant 03h Toronto. Rouge complet conservé. |
| [Horloge fixture](preuves/m10-console-horloge-root-r1-modification.json.gz), [préimage](preuves/m10-console-horloge-root-r1-test_console_memoire_jobs.py.gz), [GREEN r2](preuves/m10-selection-integree-root-r2-2026-10-01.xml.gz), [résultat/commande](preuves/m10-selection-integree-root-r2-2026-10-01-resultat.json.gz), [avant](preuves/m10-selection-integree-root-r2-2026-10-01-avant.json.gz), [après](preuves/m10-selection-integree-root-r2-2026-10-01-apres.json.gz) | **974 PASS / 0F/E/S** | 959 département M10 + 11 console jobs + 4 cron, 38,959 s JUnit; 1029 chemins sélectionnés de plusieurs formats stables. Heure fixée avant grant/exécution; production not_due conservée. Copie archivée = préimage; aucun total avec les 945/954/963 historiques. |

M5.10a rend des scénarios datés facultatifs sous Decimal local et budget de sortie; références et
couverture sont déclarées manuellement, non vérifiées. Minimum parmi les soldes de fin de semaine,
pas au jour le jour. Aucun paiement, paie ou écriture financière créé par ces calculs.

[Ruff M10 RED r1](preuves/m10-ruff-integre-root-r1-2026-10-01-resultat.json.gz),
[GREEN global r2](preuves/m10-ruff-integre-root-r2-2026-10-01-resultat.json.gz),
[modification d’import](preuves/m10-ruff-import-root-r1-modification.json.gz),
[préimage](preuves/m10-ruff-import-root-r1-test_developpement.py.gz) et
[source après formatage](preuves/r20-m10-postformat-source-r5-2026-10-01.py.gz) restent distincts.
I001 corrigé le 05:04:37 UTC par un saut de ligne; AST avant/après strictement identiques,
SHA 3533f83d… recontrôlé. La preuve 974 précède cette mise en forme : elle testait le SHA92f40f…,
pas le SHA6d14d6… courant. Ruff global r2 est vert sur 1029 sources stables; aucune suite pytest
supplémentaire n’est revendiquée sur le nouveau hash. Le
[script rootable](preuves/m10-preflight-selection-2026-10-01-r4-commandes-rootable-r1.sh.gz) et le
[diff documentaire](preuves/m10-preflight-selection-2026-10-01-r4-docs-selection-r1.diff.gz)
sont des adaptateurs root figés; les artefacts final/r4 originaux restent identiques.

[Design paie r1](preuves/m54-paie-preparatoire-design-r1-design.md.gz) et
[design r2](preuves/m54-paie-preparatoire-design-r2-design.md.gz) sont des copies documentaires,
**pas une implémentation**. R2 distingue heures M4 validées, lecteur privé autorisé et contrat
individuel. WCT vérifié et taux d’équipe ne constituent pas la paie. Net/DAS/coût employeur inconnus.

[Relocation PowerShell](preuves/pwsh-relocation-ressources-root-r1-2026-10-01.json.gz),
[M7](preuves/m7-workspace-relocation-root-r1-2026-10-01.json.gz) et
[installateur Docker](preuves/docker-install-workspace-relocation-root-r1-2026-10-01.json.gz)
gardent les comparaisons producteur et les chemins originaux par symlinks vers les copies
préservées. Le collecteur vérifie ces liens et les sources des 314 anciennes archives; il ne
refait pas les trois inventaires complets.

Le [contrôle r5](preuves/r20-m510a-m10-capture-r5-2026-10-01.json.gz) consigne commandes, JUnit,
sources exactes et exclusions. M3 R8 reste sans XML final ni reçus de campagne persistés; ses
marqueurs ne deviennent pas des tests passés. **R20 reste EN COURS**, sans somme des campagnes
recouvrantes ni verdict global Core/M3/socle.


## Collecte r6 — Core par groupes et garde CI M3

[Index avant r6](preuves/r20-entry-index-before-r6-2026-10-01.json.gz),
[MANIFEST r5](preuves/r20-r5-manifest-before-r6-2026-10-01.json.gz),
[README r5](preuves/r20-r5-readme-before-r6-2026-10-01.md.gz) et
[lecteur indépendant r5](preuves/r20-lecteur-independant-root-r5-2026-10-01.json.gz)
conservent le lot 406 archives/152 liens. Les 406 archives et leurs sources restent identiques,
R19 demeure scellé. Aucun journal vivant du socle, de M3 R9 ou de M4 n’est collecté.

Le [résultat Core final R5](preuves/core158-r5-core158-r5-current-result.json.gz), SHA79b2d4ac…,
et sa [relecture root](preuves/core158-lecteur-independant-root-r5-2026-10-01.json.gz)
établissent **158 fichiers distincts par union de six groupes**. Ce n’est pas une commande
globale unique. Les quatre projets initiaux sont les rapports JSON natifs du préfixe R3;
son collecteur s’est ensuite arrêté sur Gateway, sans succès du processus R3 complet.

| Groupe | Fichiers | Résultat dans la fenêtre documentée | Preuve |
|---|---:|---:|---|
| R3, projets 1–4 | 32 | 1078 PASS / 1 SKIP | Rapports natifs [1](preuves/core158-r3-vitest.json.reports-swCKWt-1-1-report.json.gz), [2](preuves/core158-r3-vitest.json.reports-swCKWt-2-1-report.json.gz), [3](preuves/core158-r3-vitest.json.reports-swCKWt-3-1-report.json.gz), [4](preuves/core158-r3-vitest.json.reports-swCKWt-4-1-report.json.gz), déjà figés; arrêt du collecteur conservé. |
| R4, projet 5 | 37 | 780 PASS | [log natif](preuves/core158-r4-config-5.log.gz), [commande](preuves/core158-r4-config-5-command.txt.gz), [exit0](preuves/core158-r4-config-5.exit-code.txt.gz) |
| R4, projets 6–11 | 20 | 823 PASS | [log](preuves/core158-r4-configs-6-11.log.gz), [commande](preuves/core158-r4-configs-6-11-command.txt.gz) |
| R5 final, projets 12–13 | 22 | 570 PASS / 4 SKIP | [log final](preuves/core158-r5-configs-12-13-generation-reset-final.log.gz), [exit0](preuves/core158-r5-configs-12-13-generation-reset-final.exit-code.txt.gz), [cibles22](preuves/core158-r5-configs-12-13-targets.txt.gz), commande structurée dans le résultat final |
| R4, projets 14–16 | 35 | 1342 PASS | [log](preuves/core158-r4-configs-14-16.log.gz), [commande](preuves/core158-r4-configs-14-16-command.txt.gz) |
| R4, projets 17–22 | 12 | 399 PASS | [log](preuves/core158-r4-configs-17-22.log.gz), [commande](preuves/core158-r4-configs-17-22-command.txt.gz) |

Le résultat producteur de ces groupes distincts est **4992 PASS / 0 FAIL / 5 SKIP**.
Il n’est additionné ni aux diagnostics et rejeux Core, ni aux suites Python ou départementales.
Le log 17–22 imprime deux fois le résumé118P du même shard e2e (même Start04:38:33);
ce doublon de reporter est conservé et ne représente pas118 tests supplémentaires.
Les quatre skips de 12–13 sont les cas `describeWin` du
[prévol exec](preuves/core158-r5-final-source-src-agents-bash-tools.exec.script-preflight.test.ts.gz)
sur Linux. Le cinquième est précisément `Claw projects does not report a differently cased
selected file as excluded` dans [project.test.ts](preuves/core158-r5-final-source-src-claws-project.test.ts.gz),
conditionné par `it.runIf(process.platform === "win32")`. **Aucun Windows réel qualifié.**

[R4 rouge initial](preuves/core158-r4-configs-12-13.log.gz) garde 498P/3F/4S;
[rapport R4](preuves/core158-r4-core158-r4-result.json.gz) conserve sa causalité non confirmée.
R5 archive aussi les rejoués rouges et [diagnostic minimal](preuves/core158-r5-diagnostic-module-reset-minimal.log.gz) :
après `vi.resetModules`, le singleton manager pouvait conserver la fabrique d’une génération
antérieure, dont le store différait du store réimporté. Le reset du fixture dispose le manager
et retire son slot global; production et assertions sont conservées. La course hypothétique
avec le `clear` n’est pas présentée comme cause établie.

[Avant Core](preuves/core158-r5-core-sources-before.sha256.gz),
[après final](preuves/core158-r5-core-sources-after-r5.sha256.gz) et
[diff](preuves/core158-r5-core-source-hash-diff-r5.txt.gz) portent 34029 entrées et seulement
deux changements de fixtures ticket; ce sont des manifestes textuels, aucun arbre de cache,
dist ou node_modules n’est archivé. Les trois fixtures finales exactes sont conservées :
[device](preuves/core158-r5-final-source-src-agents-opsys-device-mcp-target.test.ts.gz),
[ticket](preuves/core158-r5-final-source-src-agents-agent-bundle-mcp-runtime.opsys-cible-ticket.test.ts.gz),
[HTTP](preuves/core158-r5-final-source-src-agents-agent-bundle-mcp-runtime.opsys-cible-ticket.python-http.integration.test.ts.gz).
Les deux dernières ont [7 tests PASS après formatage](preuves/core158-r5-ticket-fixtures-formatted-final.log.gz),
[exit0](preuves/core158-r5-ticket-fixtures-formatted-final.exit-code.txt.gz). Le check oxfmt est
déclaré dans le rapport final, sans log dédié conservé; ce n’est pas une nouvelle vérification
effectuée par le collecteur. Les [hashes Python avant](preuves/core158-r5-python-http-sources-before.sha256.gz)
et [après](preuves/core158-r5-python-http-sources-after-r5.sha256.gz) sont identiques, sur 198
chemins sélectionnés pour HTTP. Ces intégrations emploient un serveur Python HTTP réel local;
elles ne prouvent aucun fournisseur, déploiement ou isolation OS de production.

Le [nettoyage du cache](preuves/core-cache-compilation-nettoyage-root-r1-2026-10-01.json.gz)
est l’action du producteur sur le cache généré, après ENOSPC; aucune suppression n’est effectuée
par le collecteur. Les [préimages documentaires](preuves/programme-m5-m10-core-root-r1-avant.json.gz)
et [modification](preuves/programme-m5-m10-core-root-r1-modification.json.gz) décrivent huit
documents et leurs hashes; aucun document actif mutable après modification n’est copié.

[Qualification du skip M3](preuves/m3-skip-qualification-2026-10-01.md.gz) conserve l’observation
historique `garde de CI seulement`, distincte de la disponibilité du rendu PDF local.
Le ciblé narratif 1P/0,36s n’avait pas de JUnit dédié. La
[reprise indépendante root](preuves/m3-garde-ci-root-r1-2026-10-01.xml.gz) prouve **1 PASS / 0F/E/S**
en **0,304s JUnit**, [commande/log](preuves/m3-garde-ci-root-r1-2026-10-01.log.gz),
[résultat](preuves/m3-garde-ci-root-r1-2026-10-01-resultat.json.gz),
[avant](preuves/m3-garde-ci-root-r1-2026-10-01-avant.json.gz) et
[après](preuves/m3-garde-ci-root-r1-2026-10-01-apres.json.gz) : 1029 sources sélectionnées stables.
`GITHUB_ACTIONS=true` active seulement cette garde dans la commande; l’installation du workflow
GitHub n’est pas émulée. Les anciens JUnit gardent leur skip et ce cas n’est additionné à aucune
suite M3. Le [contrôle r6](preuves/r20-core-m3-garde-capture-r6-2026-10-01.json.gz) consigne les
limites. **R20 reste EN COURS**, sans verdict global du socle/M3/M4.


## Collecte r7 — socle intégré complet et actionlint distinct

[Index avant r7](preuves/r20-entry-index-before-r7-2026-10-01.json.gz),
[MANIFEST r6](preuves/r20-r6-manifest-before-r7-2026-10-01.json.gz),
[README r6](preuves/r20-r6-readme-before-r7-2026-10-01.md.gz) et
[lecteur indépendant r6](preuves/r20-lecteur-independant-root-r6-2026-10-01.json.gz)
préservent le lot de 529 archives et 199 liens. Les 529 archives et leurs bruts restent identiques;
R19 reste scellé. Les journaux de M3 R9, M4, M5 contrat et C01 OS en cours restent exclus.

| Preuve | Résultat | Portée |
|---|---:|---|
| [Socle complet](preuves/socle-m5-m10-integres-root-r1-2026-10-01.xml.gz), [log](preuves/socle-m5-m10-integres-root-r1-2026-10-01.log.gz), [commande/résultat](preuves/socle-m5-m10-integres-root-r1-2026-10-01-resultat.json.gz) | **2408 cas = 2324 PASS / 84 SKIP / 0F/E** | Commande pytest tests complète, 1322,698 s JUnit. [Avant](preuves/socle-m5-m10-integres-root-r1-2026-10-01-avant.json.gz) et [après](preuves/socle-m5-m10-integres-root-r1-2026-10-01-apres.json.gz) :1037 chemins sélectionnés, delta vide. Pas une suite départementale complète ou l’exécution Core158. |
| [Réconciliation root](preuves/socle-m5-m10-reconciliation-root-r1-2026-10-01.json.gz), [ancien socle rouge](preuves/socle-cfo-integre-root-r3-2026-10-01.xml.gz) | **38 anciens FAIL/ERROR désormais PASS** | Identifiants classname/name comparés un par un au nouveau JUnit. Aucun ancien cas rouge manquant ou sauté; cinq nouveaux cas de fixture PostgreSQL listés. Les rouges précédents restent archivés. |
| [Actionlint ciblé](preuves/socle-actionlint-root-r1-2026-10-01.xml.gz), [log](preuves/socle-actionlint-root-r1-2026-10-01.log.gz), [commande/résultat](preuves/socle-actionlint-root-r1-2026-10-01-resultat.json.gz), [avant](preuves/socle-actionlint-root-r1-2026-10-01-avant.json.gz), [après](preuves/socle-actionlint-root-r1-2026-10-01-apres.json.gz) | **1 PASS / 0F/E/S** | 0,235 s JUnit, 1029 chemins sélectionnés stables. Actionlint trouvé dans le PATH de cette commande. Le skip actionlint du socle demeure dans son JUnit; ce ciblé n’est pas ajouté au total de 2324. |

La [liste Core supplémentaire](preuves/socle-m5-m10-core-sources-root-r1-2026-10-01.json.gz)
contient huit chemins exacts. 1037 signifie1029 chemins de domaines de plusieurs formats
(`.py/.yaml/.toml/.sh/.ps1/.json`) plus 8 Core explicitement sélectionnés; cela ne signifie
pas 1037 fichiers Python. Les formulations anciennes « fichiers Python » des captures documentaires
R5/R6 sont imprécises; leurs snapshots de données et hashes restent inchangés et déterminent
la portée exacte. Aucune fermeture exhaustive de tous les fichiers du dépôt n’est revendiquée.

Les 84 skips sont conservés avec leurs motifs et nodeids dans la réconciliation :

- **82 PowerShell** (41scripts +41faux) : chacun des 82 nodeids a déjà passé dans le
  [compagnon historique de 87 PASS](../R19-2026-09-30/preuves/pwsh-linux-r3/pwsh-linux-r3-run2-green.xml.gz).
  C’est une concordance d’identifiants avec cet ancien arbre, pas une nouvelle exécution de
  l’arbre actuel. Pas de somme entre 2324 et 87, ni preuve Windows réel.
- **1 Docker QA opt-in** : `tests.test_deploy_backup_restore::test_restauration_reelle_volumes_docker_qa_jetables`,
  motif «intégration Docker explicite requise». Sa reprise ciblée est documentée dans r8 ci-dessous, avec portée limitée; le skip original reste intact.
- **1 actionlint absent du PATH du socle** : reprise indépendante de 1 PASS ci-dessus, sans convertir
  le skip original ou certifier un nouveau socle de 2408 PASS.

[Avant documentaire](preuves/programme-socle-verifie-root-r2-avant.json.gz) et préimages
[BILAN](preuves/programme-socle-verifie-root-r2-preimages-docs-programme-BILAN-RESTRUCTURATION-2026-09-30.md.gz),
[plan](preuves/programme-socle-verifie-root-r2-preimages-docs-programme-RESTRUCTURATION-2026-09-30.md.gz),
[REGISTRE](preuves/programme-socle-verifie-root-r2-preimages-docs-programme-REGISTRE-AUDIT-2026-09-30.md.gz)
conservent les trois documents avant mise à jour; aucun document actif ni mutation future
n’est copié. Le [contrôle r7](preuves/r20-socle-actionlint-capture-r7-2026-10-01.json.gz)
consigne les commandes, comptes JUnit et limites. **R20 reste EN COURS**, sans total formé
par mélange de ces suites ou verdict des campagnes encore actives.


## Collecte r8 — restauration de volumes Docker QA, portée limitée

[Index avant r8](preuves/r20-entry-index-before-r8-2026-10-01.json.gz),
[MANIFEST r7](preuves/r20-r7-manifest-before-r8-2026-10-01.json.gz),
[README r7](preuves/r20-r7-readme-before-r8-2026-10-01.md.gz) et
[lecteur indépendant r7](preuves/r20-lecteur-independant-root-r7-2026-10-01.json.gz)
conservent le lot de 550 archives et 222 liens. Ces archives et leurs bruts restent identiques;
R19 demeure scellé. Aucun test ou service n’est lancé par le collecteur.

[JUnit Docker QA terminé](preuves/docker-restauration-volumes-qa-r1-reprise1-2026-10-01-junit.xml.gz),
[log](preuves/docker-restauration-volumes-qa-r1-reprise1-2026-10-01.log.gz),
[commande/résultat](preuves/docker-restauration-volumes-qa-r1-reprise1-2026-10-01-resultat.json.gz),
[rapport](preuves/docker-restauration-volumes-qa-r1-reprise1-2026-10-01-rapport.md.gz) et
[relecture root](preuves/docker-restauration-lecteur-root-r1-2026-10-01.json.gz)
prouvent **1 PASS / 0F/E/S, 382,729 s JUnit**, sur cinq volumes Docker réels portant des
marqueurs synthétiques. Les [1032 chemins avant](preuves/docker-restauration-volumes-qa-r1-reprise1-2026-10-01-avant.json.gz)
et [après](preuves/docker-restauration-volumes-qa-r1-reprise1-2026-10-01-apres.json.gz) sont
identiques; la [liste complémentaire](preuves/docker-restauration-volumes-qa-r1-reprise1-2026-10-01-sources.json.gz)
sélectionne le test et trois fichiers deploy. Il s’agit de chemins multi-formats, pas d’un
inventaire exhaustif du dépôt ou de 1032 fichiers Python.

Le test écrit la génération synthétique, la sauvegarde, la remplace puis restaure et relit
les marqueurs dans **opsys_data, openclaw_config, openclaw_auth_secrets, caddy_data et
caddy_config**. La [liste créée](preuves/docker-restauration-volumes-qa-r1-reprise1-2026-10-01-volumes-crees.txt.gz)
est distincte des [inventaires avant](preuves/docker-restauration-volumes-qa-r1-reprise1-2026-10-01-volumes-avant.txt.gz)
et [après](preuves/docker-restauration-volumes-qa-r1-reprise1-2026-10-01-volumes-apres.txt.gz),
identiques. Root ne relève aucun volume de ce préfixe restant après nettoyage. L’
[image locale par ID SHA complet](preuves/docker-restauration-volumes-qa-r1-reprise1-2026-10-01-image-id.txt.gz)
est conservée; aucun build/pull n’a été demandé dans cette preuve.

**Compose config et opérations ciblées volumes/conteneurs sont réels; Compose stop/up et
pg_dump/psql sont interceptés/simulés.** Cette passe ne prouve ni restauration SQL/PostgreSQL,
ni démarrage/arrêt réel d’une stack, ni VPS, CoreOS ou sauvegarde distante. Elle n’est pas
additionnée au socle; son ancien skip Docker demeure dans le JUnit 2408 cas.

La [première invocation échouée](preuves/docker-restauration-volumes-qa-r1-2026-10-01-launcher.log.gz)
a transmis `--core-sources` comme exécutable et produit FileNotFoundError avant pytest et
les opérations du test Docker. Son [log de test vide](preuves/docker-restauration-volumes-qa-r1-2026-10-01.log.gz)
et ses captures préparatoires sont conservés. Aucun JUnit ni résultat pytest n’existe pour
cette invocation; ce n’est pas un échec de code du test de restauration.

La [note C01 locale en lecture seule](preuves/c01-os-sandbox-local-qualification-2026-10-01.md.gz)
documente capacités et sources consultées avant préparation : Docker Linux disponible, image
sandbox alors absente, épreuve minimale proposée mais non exécutée. Elle ne certifie aucun
conteneur lancé par Core ou frontière OS. Les futurs builds et journaux de harness restent
hors collecte. Le [contrôle r8](preuves/r20-docker-qa-capture-r8-2026-10-01.json.gz) consigne
commandes, hashes, inventaires et limites. **R20 reste EN COURS**; M3 R9, M4/M5 candidates et
documents actifs mutables ne sont pas collectés.


## Collecte r9 — C01 local natif, chronologie réelle conservée

[Index avant r9](preuves/r20-entry-index-before-r9-2026-10-01.json.gz),
[MANIFEST r8](preuves/r20-r8-manifest-before-r9-2026-10-01.json.gz),
[README r8](preuves/r20-r8-readme-before-r9-2026-10-01.md.gz) et
[lecteur indépendant r8](preuves/r20-lecteur-independant-root-r8-2026-10-01.json.gz)
préservent les 575 archives/242 liens précédents; bruts et R19 restent identiques.

Le [build standard sandbox](preuves/c01-os-sandbox-build-2026-10-01.log.gz),
[exit0](preuves/c01-os-sandbox-build-2026-10-01.exit.gz) et
[Dockerfile exact de 606 octets](preuves/c01-os-build-context-2026-10-01-Dockerfile.gz), SHA 12f32a47…,
portent uniquement sur `openclaw-sandbox:bookworm-slim`. L’image construite est
`sha256:41967c20fe83f102390d7ddcfc0b2c47e81bc0b36fb62aaf07f3cea58b0bd3bb`.
Le Dockerfile et le contexte sont identiques; aucun checkout, image serveur OPSYS, cache,
image Docker ou node_modules n’est archivé. Le producteur a réellement construit cette image
standard depuis la base Debian épinglée et ses paquets; le collecteur n’a rien construit.

| Essai | Statut brut et chronologie | Preuves distinctes |
|---|---|---|
| r1, 624d0719… | started=true, conteneur f478fe1d… créé et inspecté; erreur d’invariant inspect puis erreur de schéma key id au nettoyage. Ce n’est pas un arrêt avant Docker. | [JSON](preuves/c01-os-sandbox-run-624d0719-49e8-4948-954f-4440d0d9804d.json.gz), [harness](preuves/c01-os-sandbox-probe-2026-10-01.mjs.gz), [log](preuves/c01-os-sandbox-probe-2026-10-01.log.gz), [exit1](preuves/c01-os-sandbox-probe-2026-10-01.exit.gz) |
| r2, 07d1425a… | Conteneur b7a15b5c… créé; inspect montre no-new-privileges, erreur d’invariant enregistrée. Le récit attribue l’attente à no-new-privileges:true; le harness exact r2 est indisponible. | [JSON](preuves/c01-os-sandbox-run-07d1425a-4d11-4507-bb35-bdf6ce021251.json.gz), [log](preuves/c01-os-sandbox-probe-r2-2026-10-01.log.gz), [exit1](preuves/c01-os-sandbox-probe-r2-2026-10-01.exit.gz) |
| r3, 986f9fe8… | Conteneur d1a08f6a… créé; la sonde shell sort 1, aucune preuve positive. | [JSON](preuves/c01-os-sandbox-run-986f9fe8-f057-42f8-acf1-54c9b2bf822c.json.gz), [harness](preuves/c01-os-sandbox-probe-r3-2026-10-01.mjs.gz), [log](preuves/c01-os-sandbox-probe-r3-2026-10-01.log.gz), [exit1](preuves/c01-os-sandbox-probe-r3-2026-10-01.exit.gz) |
| r4, 2ec9a897… | GREEN du harness et commande exec exit0; conteneur 03df7ce3… retiré, cleanup sans erreur. | [JSON](preuves/c01-os-sandbox-run-2ec9a897-a635-4302-aa31-301822bf1766.json.gz), [harness exact](preuves/c01-os-sandbox-probe-r4-2026-10-01.mjs.gz), [log](preuves/c01-os-sandbox-probe-r4-2026-10-01.log.gz), [exit0](preuves/c01-os-sandbox-probe-r4-2026-10-01.exit.gz), [config](preuves/c01-os-sandbox-config-2ec9a897-a635-4302-aa31-301822bf1766.json.gz) |

Le fichier de base livré sous le nom r1 est archivé, mais aucune empreinte prise lors de
l’exécution r1 ne prouve qu’il n’a pas changé entre r1 et r2. Aucun script r2 n’est reconstruit
depuis r1/r3. Les scripts historiques présents restent des copies livrées; **seul le script
r4 est lié à la preuve positive par son hash exact et la relecture indépendante**.

Seul r4 est une preuve positive. Le
[rapport final distinct 5b18…](preuves/c01-os-sandbox-local-qualification-final-r4-2026-10-01.md.gz)
contient encore un récit «r1 rejeté par schéma avant Docker» : **le JSON/harness r1 prime ce
récit**, comme qualifié dans le tableau. Son début et l’image alors absente décrivent le relevé
préparatoire historique; la mise à jour finale consigne le build/probe ensuite autorisés.
Le [rapport de réparation 39bc…](preuves/c01-os-sandbox-report-version-repair-2026-10-01.json.gz)
conserve cette nouvelle version à un nom distinct et restaure le document initial 2011… au
chemin de la source archivée r8. Aucun raw n’est réécrit par le collecteur.

Le [lecteur root indépendant](preuves/c01-os-sandbox-lecteur-root-r1-2026-10-01.json.gz)
vérifie 14 chemins sélectionnés (Dockerfile compris), leurs hashes inchangés, l’image courante
et l’absence du conteneur final. Le harness importe le TS natif via tsx puis appelle
`resolveSandboxContext` et `createExecTool(...).execute(...)` avec configuration/session
synthétiques et garde OPSYS active. **Aucun Gateway, tour LLM, VPS ou instance de production.**

Dans ce parcours : UID:GID 1000:1000, root RO, réseau none/lo seul, CapDrop ALL,
NoNewPrivs=1 et Seccomp=2. Il y a **deux montages Core privés**, workspace RW et skills RO,
résolus par realpath sous le workspace privé; aucun bind supplémentaire configuré ni montage
du workspace hôte synthétique. `binds=[]` et `workspaceAccess=none` ne signifient donc pas
zéro montages. Le marqueur hôte choisi est absent après retrait explicite des noms OPSYS_*
fictifs; cela ne prouve pas l’absence automatique de toutes variables, un balayage exhaustif
de l’hôte, ou une isolation multi-tenant. Aucun secret ou donnée métier réel n’est utilisé.

[Modification documentaire programme r2](preuves/programme-socle-verifie-root-r2-modification.json.gz)
complète l’avant et les trois préimages déjà r7, sans copier aucun document actif ou futur.
Le [contrôle r9](preuves/r20-c01-os-capture-r9-2026-10-01.json.gz) consigne chronologie,
hashes et limites. **R20 reste EN COURS**; les promotions/full M4/M5, M3 R9 vivant et l’étude
du pont M5 non terminée ne sont pas collectés. Aucun test ou service lancé par le collecteur.


## Collecte r10 — intégration M4/M5, rouges et préimages conservés

[Index avant r10](preuves/r20-entry-index-before-r10-2026-10-01.json.gz),
[MANIFEST r9](preuves/r20-r9-manifest-before-r10-2026-10-01.json.gz),
[README r9](preuves/r20-r9-readme-before-r10-2026-10-01.md.gz) et
[lecteur root r9](preuves/r20-lecteur-independant-root-r9-2026-10-01.json.gz)
préservent les 606 archives/270 liens précédents. Tous ces enregistrements, leurs gzip et
leurs sources brutes restent intacts; R19 reste scellé et inchangé.

L’intégration [M4, cinq fichiers](preuves/m54-m4-integration-root-r1--integration.json.gz)
porte sur les heures régulières approuvées, avec journal/registre et validation humaine N4.
L’intégration [M5, huit fichiers](preuves/m54-m5-integration-root-r1--integration.json.gz)
porte sur le contrat salarial horaire déclaré humainement et son journal distinct, sans
extension de grant CFO ni migration de schéma. Les avant et préimages exactes de chaque
fichier déjà présent sont archivés. Les nouveaux fichiers ont un avant absent, pas une
préimage reconstruite. **Aucun pont heures→brut, calcul de paie/fiscal ou paiement n’est
certifié par ce lot**; les taux/sources déclarés ne rendent pas leurs documents authentiques.
Les hashes non signés ne protègent pas d’un opérateur privilégié qui réécrit toute la chaîne.

| Commande / preuve | Résultat lu dans le JUnit | Portée et chronologie |
|---|---:|---|
| [r1 résultat](preuves/m54-m4-m5-integres-root-r1-2026-10-01-resultat.json.gz), [XML](preuves/m54-m4-m5-integres-root-r1-2026-10-01.xml.gz), [log](preuves/m54-m4-m5-integres-root-r1-2026-10-01.log.gz) | Six erreurs de collecte; 0 PASS, exit2 | Le `-o addopts=` de cette commande retire `--import-mode=importlib`; six collisions de noms de modules, aucun cas métier exécuté. Ce n’est pas un échec métier. |
| [r2 résultat](preuves/m54-m4-m5-integres-root-r2-2026-10-01-resultat.json.gz), [XML](preuves/m54-m4-m5-integres-root-r2-2026-10-01.xml.gz), [log](preuves/m54-m4-m5-integres-root-r2-2026-10-01.log.gz) | 4 957 PASS, 5 FAIL, 0 ERROR/SKIP; 295,503 s | 4 962 cas, exit1; chaque fenêtre avant/après conserve les mêmes 1 033 chemins sélectionnés. Les cinq échecs de catalogue/ordre sont conservés. |
| [r3 résultat](preuves/m54-m4-m5-integres-root-r3-2026-10-01-resultat.json.gz), [XML](preuves/m54-m4-m5-integres-root-r3-2026-10-01.xml.gz), [log](preuves/m54-m4-m5-integres-root-r3-2026-10-01.log.gz) | 4 962 PASS, 0 FAIL/ERROR/SKIP; 294,638 s | Exactement les mêmes identifiants que r2; cinq anciens échecs désormais réussis. Les 1 033 chemins restent stables pendant cette nouvelle exécution. |
| [Cibles intermédiaires](preuves/m54-catalogues-cibles-root-r1-2026-10-01-resultat.json.gz), [log](preuves/m54-catalogues-cibles-root-r1-2026-10-01.log.gz) | Exit0; aucun XML généré | Cinq fichiers de tests catalogue. Aucun nombre de cas JUnit inventé; leurs cas se recouvrent avec r3. |

Les [corrections de catalogue r2](preuves/m54-catalogues-integration-root-r2--modification.json.gz)
touchent cinq fichiers et conservent leurs cinq préimages. La
[préparation r1 interrompue avant mutation](preuves/m54-catalogues-integration-root-r1--preparation-rouge.json.gz)
et ses préimages sont distinctes. Entre r2 et r3, ces cinq hashes ont changé; «stables»
signifie **chaque fenêtre d’exécution avant/après**, pas l’absence de correction entre les runs.
La [réconciliation root](preuves/m54-m4-m5-reconciliation-root-r1-2026-10-01.json.gz)
et la [ventilation du même run r3](preuves/m54-m4-m5-ventilation-root-r1-2026-10-01.json.gz)
confirment **2 854 M4 + 2 074 M5 + 34 socle CFO = 4 962**. Il s’agit d’une ventilation
de cette commande unique, pas d’une somme de suites antérieures. Les quatre fichiers du socle
sont `test_agent_cfo_grants`, `test_console_agent_cfo_grants`, `test_openclaw_profils` et
`test_console_cfo`. Les commandes exactes et timestamps figurent dans chaque résultat JSON.

Les probes root historiques restent séparés : [M4 r1 rouge](preuves/m54-m4-relecture-root-r1-2026-10-01.json.gz)
acceptait une chaîne altérée et un intervalle traversant toute la fenêtre;
[M4 r2 corrigé](preuves/m54-m4-relecture-root-r2-2026-10-01.json.gz) refuse ces cas sous identité
canonique SQLite synthétique, sans transport HTTP. [M5 bornes r1](preuves/m54-m5-bornes-relecture-root-r1-2026-10-01.json.gz)
refusait à tort une seule date civile; [r2](preuves/m54-m5-bornes-relecture-root-r2-2026-10-01.json.gz)
accepte les bornes inclusives et refuse ordre inversé/couverture absente. Ces lecteurs purs
ne prouvent pas seuls l’autorité N4, les personnes ou le runtime HTTP.

[Ruff ciblé](preuves/m54-ruff-integre-root-r1-2026-10-01.json.gz) est exit0 sur les onze fichiers
enregistrés; [CLI verifier](preuves/m54-verifier-integre-root-r1-2026-10-01.json.gz),
[log](preuves/m54-verifier-integre-root-r1-2026-10-01.log.gz), est exit0 avec **201 outils et
116 déclarés aux appareils**. Ces commandes sont antérieures à la correction de catalogue;
leurs hashes et timestamps propres sont conservés, sans les rattacher à tort à un nouveau lint
ou un nouveau passage du catalogue final. Aucun XML ni test supplémentaire n’en est déduit.

Le [lecteur des quatre conteneurs C01](preuves/c01-os-quatre-conteneurs-lecteur-root-r1-2026-10-01.json.gz)
constate les quatre IDs absents à son instant de lecture et le seul PostgreSQL préexistant
inchangé. Le conteneur r1 avait été créé/inspecté et son nettoyage avait échoué : son absence
ultérieure ne transforme pas cet échec historique en succès. La qualification r9 du récit
erroné r1 et du harness exact r2 indisponible reste applicable.

L’[actualisation des quatre docs C01](preuves/c01-docs-actives-actualisation-r1-2026-10-01--modification.json.gz),
[diff](preuves/c01-docs-actives-actualisation-r1-2026-10-01--modification.patch.gz),
[vérification](preuves/c01-docs-actives-actualisation-r1-2026-10-01--verification.json.gz) et
[lecteur root](preuves/c01-docs-lecteur-root-r1-2026-10-01.json.gz) conservent **C01 PARTIEL**,
67 liens valides, les quatre préimages et les compteurs M4/M5/socle. Leurs hashes correspondent
à la fenêtre documentaire datée, sans copier les docs actives qui peuvent évoluer ensuite.
La portée reste sandbox standard local, factories Core exec bash synthétiques, deux montages
privés RW/RO, UID:GID 1000:1000, root RO, réseau none, NNP1/seccomp2/caps0 et suppression
explicite du marqueur fictif d’environnement; aucun serveur complet, Gateway LLM, SaaS multi-tenant
ou VPS n’est validé. Les échecs C01 r1–r3 sont conservés.

Le [contrôle r10](preuves/r20-m54-integration-capture-r10-2026-10-01.json.gz) vérifie comptes,
identifiants, hashes des préimages et liens entre fenêtres. **R20 reste EN COURS**; aucun run
lourd, service ou test n’a été lancé par le collecteur. Le pont/brut scratch, les sources/docs
actives évolutives et M3 vivant sont exclus. Les 4 962 cas ne sont pas ajoutés aux autres
suites de ce lot; le socle antérieur conserve sa date et sa portée propres.


## Collecte r11-agent — campagne M3 historique et documents programme

[Index avant r11](preuves/r11-agent-r20-snapshot--r20-entry-index-before-r11-agent-2026-10-01.json.gz), [manifest r10](preuves/r11-agent-r20-snapshot--r20-r10-manifest-before-r11-agent-2026-10-01.json.gz), [README r10](preuves/r11-agent-r20-snapshot--r20-r10-readme-before-r11-agent-2026-10-01.md.gz).

Le full scratch R9b compte **49 tests : 48 PASS, 1 échec documentaire, 0 erreur/saut**, exit 1; [JUnit](preuves/r11-agent-m3-r9--full-r9b--full2.xml.gz) et [log](preuves/r11-agent-m3-r9--full-r9b--full2.log.gz). L’unique échec portait sur le seuil de longueur d’une docstring. Les **38 reçus durables** et les [rapport initial](preuves/r11-agent-m3-r9--full-r9b--rapport-r9b.md.gz) et [rapport corrigé](preuves/r11-agent-m3-r9--full-r9b--rapport-r9b-r2.md.gz) sont conservés. Le rapport initial avait un compte 10/10 erroné; r2 donne les vrais comptes, soit **94/94** mutations tuées et restaurées sur neuf outils (9/9, 15/15, 9/9, 10/10, 12/12, 6/6, 10/10, 13/13, 10/10). L’énumérateur a une preuve nominale sans dénominateur. Le [lecteur indépendant des reçus](preuves/r11-agent-m3-r9--docfix--receipt-reader-result.json.gz) valide checksums/clés, retours et fermetures avant-après.

Le prévol 06c demeure une déclaration erronée conservée; reçus nominaux et diagnostic pendant run concordent sur l’environnement enfant 5a11e8a7. Aucune valeur brute d’environnement n’est publiée. Le test documentaire ciblé sur copie candidate fait **1 PASS séparé**, et root a exécuté **16 tests actifs ciblés**, tous PASS. Aucun de ces résultats ne transforme le full historique en 49/49. Le [patch limité à 19 chemins M3](preuves/r11-agent-m3-r9--docfix--m3-r9-active-patch.diff.gz) est fourni pour revue.

Les trois documents de l’actualisation programme M54 r1, archivés comme instantanés historiques et **pas comme état final courant**, sont le [bilan](preuves/r11-agent-programme-docs--historical-r1-current-snapshot--docs--programme--BILAN-RESTRUCTURATION-2026-09-30.md.gz), le [plan](preuves/r11-agent-programme-docs--historical-r1-current-snapshot--docs--programme--RESTRUCTURATION-2026-09-30.md.gz) et le [registre](preuves/r11-agent-programme-docs--historical-r1-current-snapshot--docs--programme--REGISTRE-AUDIT-2026-09-30.md.gz). Le [résultat d’intégration M3 root](preuves/r11-agent-m3-r9--root-integration--resultat.json.gz), le [lecteur root des reçus](preuves/r11-agent-m3-r9--root-receipt-reader--m3-r9-recus-lecteur-root-r1-2026-10-01.json.gz) et son log sont conservés. Le [journal d’actualisation programme M54](preuves/r11-agent-programme-docs--update-proof--modification.json.gz), son [patch](preuves/r11-agent-programme-docs--update-proof--modification.patch.gz), sa [vérification](preuves/r11-agent-programme-docs--update-proof--verification.json.gz) et le [lecteur indépendant root](preuves/r11-agent-programme-docs--update-proof--m54-docs-programme-lecteur-root-r1-2026-10-01.json.gz) documentent les préimages et les liens vérifiés; aucun document n’a été modifié par le collecteur. R20 reste **EN COURS**; nouveaux changements M54/runtime, paie scratch et validation globale sont exclus.


## Collecte r12 — preuves root et documents candidats (jalon 09:34 UTC)

Les snapshots externes README et MANIFEST r11 (SHA-256 respectifs `a503e7cca1e4e597a33d675c350880a974e06272c6d6a027cc2fc78158cdc590` et `5f7a7afd33aabc9241f9c71be219ea11ca011deef13dbe49cb80ab1aa9eeb23a`) avec leur index de contenu conservent l’état exact précédant cette collecte. Les 792 enregistrements antérieurs et leurs octets gzip restent inchangés; R19 reste scellé. R12 ajoute 70 sources compactes; le total est 862 archives.

Le jalon documentaire du programme est arrêté au 1er octobre 2026 à 09:34 UTC. Le fullsocle root r3 initial reste rouge : **2 478 cas, 2 363 PASS, 1 échec, 30 erreurs, 84 skips**, 1 223,835 s, avec 1 094 chemins sélectionnés sans delta. Les 31 cas rouges PostgreSQL mentionnent ENOSPC. La reprise exacte des 31 nodeids sur les mêmes sources passe **31/31**, 0F/E/S, 199,136 s. Le lecteur réconcilie une union dédupliquée de 2 478 cas uniques (**2 394 PASS + 84 skips**) sans rouge résiduel, mais ce n’est pas une commande globale verte. Les skips et la fermeture de 1 094 chemins restent limités. Les références sont le [résultat rouge initial](preuves/socle-integre-root-r3-2026-10-01-resultat.json.gz), sa [reprise ciblée](preuves/socle-reprise-postgresql-root-r1-2026-10-01-resultat.json.gz) et le [lecteur d’union](preuves/socle-union-root-r1-2026-10-01.json.gz). Le [Ruff global](preuves/ruff-socle-departements-root-r1-2026-10-01-resultat.json.gz) est une commande séparée, exit 0 sur 1 094 chemins; il précède la modification ultérieure de `pyproject.toml`. Après cette modification native, le bootstrap ciblé sans override passe **29/29** en 9,027 s sur 1 094 chemins ([résultat](preuves/pytest-retention-bootstrap-root-r1-2026-10-01-resultat.json.gz)); aucun run global sur l’arbre après modification n’est revendiqué ici.

Les autres reçus root restent des commandes bornées : le run M1/M4/M5/runtime passe **6 723/6 723** ([JUnit](preuves/metier-m1-m4-m5-runtime-root-r1-2026-10-01.xml.gz), [résultat](preuves/metier-m1-m4-m5-runtime-root-r1-2026-10-01-resultat.json.gz)); M7/CMO/bootstrap passe **1 261/1 261** ([JUnit](preuves/m7-bootstrap-forme-integres-root-r1-2026-10-01.xml.gz), [résultat](preuves/m7-bootstrap-forme-integres-root-r1-2026-10-01-resultat.json.gz)); le lecteur Core runtime constate **73/73 tests sur huit fichiers** ([lecteur](preuves/runtime-core-lecteur-root-r2-2026-10-01.json.gz)). Le typecheck natif Core s’est achevé avant la capture initiale; aucune immutabilité pendant ce typecheck n’est revendiquée. Ces suites ne s’additionnent pas et ne ferment pas les modules entiers. Le compte `opsys-metier verifier` de **10 départements, 202 outils et 116 outils appareil** est daté du jalon 09:34 UTC, pas présenté comme un compte durable après changements ultérieurs.

Le reçu de relocation du 09:12 (`archives-ressources-relocation-root-r1-2026-10-01.json.gz`) confirme les copies SHA-vérifiées avant le retrait de deux anciens fichiers et leurs chemins logiques devenus symlinks. Les hashes exacts sont Core QA `25003d0710378bdeb2086156243047b62b64394d1c6e6c66e6d93e9ea7a0ea14` (143 664 748 octets) et socle root r2 `c9f4f8ef6c5dc45959c7762ae31f987e13aee1eb544514e3bf53fa1849d4f780` (580 786 990 octets). Le reçu C01 de 09:45 (`c01-copie-relocation-ressources-root-r1-2026-10-01-resultat.json.gz`) rapporte 40 171 entrées / 614 827 229 octets, hashes/métadonnées égaux, source logique symlink, checkout actif inchangé et Docker intact. Seuls les reçus et manifestes compacts sont archivés; tars et inventaires lourds sont exclus.

Les quatre [documents programme R12 r4 candidats](preuves/r12-r4-candidat-BILAN-RESTRUCTURATION-2026-09-30.md.gz), [plan](preuves/r12-r4-candidat-RESTRUCTURATION-2026-09-30.md.gz), [registre](preuves/r12-r4-candidat-REGISTRE-AUDIT-2026-09-30.md.gz) et [rapport CFO](preuves/r12-r4-candidat-M5-CFO-IA-FISCALITE-PAIE-STRATEGIE-AUDIT.md.gz) sont des copies de préparation; aucune n’est promue dans `docs/programme/` ou `docs/grs/compta/`. Elles conservent 47 IDs. L’append décrit les preuves fermées au jalon 09:34 plus les deux reçus de relocation postérieurs; les promotions M54/M10/observatoire ultérieures et les vérifications encore en cours restent hors R12. Aucun global green, déploiement ou achèvement produit n’est affirmé.


## Collecte r13 — preuves intégrées et documentaire (jalon 10:14 UTC)

Cette collecte ajoute **71 artefacts compacts**, portant R20 de 862 à **933 archives**. Elle conserve 50 références primaires du manifeste R13, quatre éléments du reçu de forme/AST `m54c-imports-root-r1` (résultat et trois préimages) et 17 compléments uniques de la preuve E09. Le lecteur root R12 reste la preuve de contrôle des 862 archives précédentes. Les snapshots externes README/MANIFEST R12 et leurs SHA avant append sont conservés dans `/workspace/restructuration-opsys-2026-10-01/preuves/r20-append-r13-root-2026-10-01`. Les 444 fichiers R19 restent scellés.

La lecture indépendante E09 a vérifié 22 artefacts, l’intégrité SQLite (`ok`) et les checksums du bundle sans rejouer les 15 assertions. R20 contient les 21 membres non-SQLite de ce bundle répartis entre les références primaires et les compléments; la base SQLite fictive n’est pas archivée. Les liens archivés comprennent le [rapport d’intégration M5/M10/admission](preuves/m5-m10-admission-integres-root-r1-2026-10-01-resultat.json.gz), son [JUnit](preuves/m5-m10-admission-integres-root-r1-2026-10-01.xml.gz), le [lecteur E09](preuves/m10-e09-persisted-lecteur-root-r1-2026-10-01.json.gz), la [qualification M5.4.d](preuves/m5-4d-paie-qualification-r1.md.gz), le [bootstrap r2](preuves/permissions-bootstrap-integres-root-r2-2026-10-01-resultat.json.gz) et le [vérificateur départements r3](preuves/verifier-departements-integres-root-r3-2026-10-01-resultat.json.gz).

La campagne M5/M10/admission passe **3 294/3 294** (2 127 M5, 968 M10, 199 socle), 0F/E/S, 239,031 s, avec 1 099 chemins stables. La suite permissions/bootstrap passe 286/287 avec un skip `actionlint` absent, 160,989 s, sur 1 115 chemins stables; l’écrivain local observe EUID 1000 et les modes 700/600. La commande `opsys-metier verifier` confirme dix départements, 203 outils et 116 outils appareil, sans compter de tests. Ruff r2 avait trois `I001`; trois séparations d’import ont corrigé le lint avec AST identique, puis Ruff r3 passe sur 1 115 chemins sans relancer la suite fonctionnelle pour ce formatage. Les résultats détaillés de ces commandes restent séparés.

M5.4.c inventorie les références ARC T4127 et RQ : les sept hashes RQ concordent avec le catalogue; les deux nouveaux PDF ARC diffèrent des anciennes empreintes catalogue R16. Les neuf entrées restent `NON_QUALIFIEE`; cette capture ne fournit ni tables de calcul, ni retenues, ni net. La revue de qualification des références/vecteurs reste à compléter, sans mission CPA engagée; la revue professionnelle s’applique avant les actions officielles. Les réservations d’admission UI ne sont pas libérées automatiquement. Le test d’ancien propriétaire de volume simule ses métadonnées : il ne prouve pas un build d’image Docker ou un VPS.

Les changements M54c (neuf chemins), M10 E09 (quatre chemins code + un document), observatoire/admission (quatre chemins) et bootstrap Compose (sept chemins) ont été promus par root le 1er octobre entre 10:03 et 10:09 UTC. R13 ne comprend pas les travaux de réconciliation des agents, l’oracle/golden de paie ou la qualification complète Compose, encore en cours. Les cas PostgreSQL ENOSPC et l’union limitée du socle R12 restent inchangés; aucune commande globale verte n’est ajoutée par ces tests ciblés.


## Collecte r14 — preuves closes au jalon du 1er octobre 2026

Cette collecte ajoute 102 sources dont les SHA et tailles correspondent au paquet R14; les gzip utilisent `mtime=0`. Elle conserve les 933 archives antérieures et le R19 scellé. Les documents candidats restent soumis à la revue et à la promotion root. Aucun total de tests global n’est revendiqué.

Les preuves R14 archivées :
- [actionlint-installer-root-r1-2026-10-01-apres.json](preuves/r14-preuves--actionlint-installer-root-r1-2026-10-01-apres.json.gz)
- [actionlint-installer-root-r1-2026-10-01-avant.json](preuves/r14-preuves--actionlint-installer-root-r1-2026-10-01-avant.json.gz)
- [actionlint-installer-root-r1-2026-10-01-resultat.json](preuves/r14-preuves--actionlint-installer-root-r1-2026-10-01-resultat.json.gz)
- [actionlint-installer-root-r1-2026-10-01.log](preuves/r14-preuves--actionlint-installer-root-r1-2026-10-01.log.gz)
- [actionlint-installer-root-r1-2026-10-01.xml](preuves/r14-preuves--actionlint-installer-root-r1-2026-10-01.xml.gz)
- [admission-trace-retour-root-r1-2026-10-01-apres.json](preuves/r14-preuves--admission-trace-retour-root-r1-2026-10-01-apres.json.gz)
- [admission-trace-retour-root-r1-2026-10-01-avant.json](preuves/r14-preuves--admission-trace-retour-root-r1-2026-10-01-avant.json.gz)
- [admission-trace-retour-root-r1-2026-10-01-resultat.json](preuves/r14-preuves--admission-trace-retour-root-r1-2026-10-01-resultat.json.gz)
- [admission-trace-retour-root-r1-2026-10-01.log](preuves/r14-preuves--admission-trace-retour-root-r1-2026-10-01.log.gz)
- [admission-trace-retour-root-r1-2026-10-01.xml](preuves/r14-preuves--admission-trace-retour-root-r1-2026-10-01.xml.gz)
- [budgets-pg-int32-red-root-r1-2026-10-01-apres.json](preuves/r14-preuves--budgets-pg-int32-red-root-r1-2026-10-01-apres.json.gz)
- [budgets-pg-int32-red-root-r1-2026-10-01-avant.json](preuves/r14-preuves--budgets-pg-int32-red-root-r1-2026-10-01-avant.json.gz)
- [budgets-pg-int32-red-root-r1-2026-10-01-resultat.json](preuves/r14-preuves--budgets-pg-int32-red-root-r1-2026-10-01-resultat.json.gz)
- [budgets-pg-int32-red-root-r1-2026-10-01.log](preuves/r14-preuves--budgets-pg-int32-red-root-r1-2026-10-01.log.gz)
- [budgets-pg64-migration-root-r1-2026-10-01-apres.json](preuves/r14-preuves--budgets-pg64-migration-root-r1-2026-10-01-apres.json.gz)
- [budgets-pg64-migration-root-r1-2026-10-01-avant.json](preuves/r14-preuves--budgets-pg64-migration-root-r1-2026-10-01-avant.json.gz)
- [budgets-pg64-migration-root-r1-2026-10-01-resultat.json](preuves/r14-preuves--budgets-pg64-migration-root-r1-2026-10-01-resultat.json.gz)
- [budgets-pg64-migration-root-r1-2026-10-01.log](preuves/r14-preuves--budgets-pg64-migration-root-r1-2026-10-01.log.gz)
- [budgets-pg64-migration-root-r2-2026-10-01-apres.json](preuves/r14-preuves--budgets-pg64-migration-root-r2-2026-10-01-apres.json.gz)
- [budgets-pg64-migration-root-r2-2026-10-01-avant.json](preuves/r14-preuves--budgets-pg64-migration-root-r2-2026-10-01-avant.json.gz)
- [budgets-pg64-migration-root-r2-2026-10-01-resultat.json](preuves/r14-preuves--budgets-pg64-migration-root-r2-2026-10-01-resultat.json.gz)
- [budgets-pg64-migration-root-r2-2026-10-01.log](preuves/r14-preuves--budgets-pg64-migration-root-r2-2026-10-01.log.gz)
- [jetons-pg-concurrence-root-r1-2026-10-01-apres.json](preuves/r14-preuves--jetons-pg-concurrence-root-r1-2026-10-01-apres.json.gz)
- [jetons-pg-concurrence-root-r1-2026-10-01-avant.json](preuves/r14-preuves--jetons-pg-concurrence-root-r1-2026-10-01-avant.json.gz)
- [jetons-pg-concurrence-root-r1-2026-10-01-resultat.json](preuves/r14-preuves--jetons-pg-concurrence-root-r1-2026-10-01-resultat.json.gz)
- [jetons-pg-concurrence-root-r1-2026-10-01.log](preuves/r14-preuves--jetons-pg-concurrence-root-r1-2026-10-01.log.gz)
- [m1-normalisation-rejeu-root-r1-2026-10-01-apres.json](preuves/r14-preuves--m1-normalisation-rejeu-root-r1-2026-10-01-apres.json.gz)
- [m1-normalisation-rejeu-root-r1-2026-10-01-avant.json](preuves/r14-preuves--m1-normalisation-rejeu-root-r1-2026-10-01-avant.json.gz)
- [m1-normalisation-rejeu-root-r1-2026-10-01-resultat.json](preuves/r14-preuves--m1-normalisation-rejeu-root-r1-2026-10-01-resultat.json.gz)
- [m1-normalisation-rejeu-root-r1-2026-10-01.log](preuves/r14-preuves--m1-normalisation-rejeu-root-r1-2026-10-01.log.gz)
- [m1-normalisation-rejeu-root-r1-2026-10-01.xml](preuves/r14-preuves--m1-normalisation-rejeu-root-r1-2026-10-01.xml.gz)
- [m1-reutilisation-stt-integres-root-r1-2026-10-01-apres.json](preuves/r14-preuves--m1-reutilisation-stt-integres-root-r1-2026-10-01-apres.json.gz)
- [m1-reutilisation-stt-integres-root-r1-2026-10-01-avant.json](preuves/r14-preuves--m1-reutilisation-stt-integres-root-r1-2026-10-01-avant.json.gz)
- [m1-reutilisation-stt-integres-root-r1-2026-10-01-resultat.json](preuves/r14-preuves--m1-reutilisation-stt-integres-root-r1-2026-10-01-resultat.json.gz)
- [m1-reutilisation-stt-integres-root-r1-2026-10-01.log](preuves/r14-preuves--m1-reutilisation-stt-integres-root-r1-2026-10-01.log.gz)
- [m1-reutilisation-stt-integres-root-r1-2026-10-01.xml](preuves/r14-preuves--m1-reutilisation-stt-integres-root-r1-2026-10-01.xml.gz)
- [m54d-admission-integres-root-r1-2026-10-01-apres.json](preuves/r14-preuves--m54d-admission-integres-root-r1-2026-10-01-apres.json.gz)
- [m54d-admission-integres-root-r1-2026-10-01-avant.json](preuves/r14-preuves--m54d-admission-integres-root-r1-2026-10-01-avant.json.gz)
- [m54d-admission-integres-root-r1-2026-10-01-resultat.json](preuves/r14-preuves--m54d-admission-integres-root-r1-2026-10-01-resultat.json.gz)
- [m54d-admission-integres-root-r1-2026-10-01.log](preuves/r14-preuves--m54d-admission-integres-root-r1-2026-10-01.log.gz)
- [m54d-admission-integres-root-r1-2026-10-01.xml](preuves/r14-preuves--m54d-admission-integres-root-r1-2026-10-01.xml.gz)
- [m54d-admission-jetons-integres-root-r2-2026-10-01-apres.json](preuves/r14-preuves--m54d-admission-jetons-integres-root-r2-2026-10-01-apres.json.gz)
- [m54d-admission-jetons-integres-root-r2-2026-10-01-avant.json](preuves/r14-preuves--m54d-admission-jetons-integres-root-r2-2026-10-01-avant.json.gz)
- [m54d-admission-jetons-integres-root-r2-2026-10-01-resultat.json](preuves/r14-preuves--m54d-admission-jetons-integres-root-r2-2026-10-01-resultat.json.gz)
- [m54d-admission-jetons-integres-root-r2-2026-10-01.log](preuves/r14-preuves--m54d-admission-jetons-integres-root-r2-2026-10-01.log.gz)
- [m54d-admission-jetons-integres-root-r2-2026-10-01.xml](preuves/r14-preuves--m54d-admission-jetons-integres-root-r2-2026-10-01.xml.gz)
- [m54d-admission-ruff-root-r1-2026-10-01-apres.json](preuves/r14-preuves--m54d-admission-ruff-root-r1-2026-10-01-apres.json.gz)
- [m54d-admission-ruff-root-r1-2026-10-01-avant.json](preuves/r14-preuves--m54d-admission-ruff-root-r1-2026-10-01-avant.json.gz)
- [m54d-admission-ruff-root-r1-2026-10-01-resultat.json](preuves/r14-preuves--m54d-admission-ruff-root-r1-2026-10-01-resultat.json.gz)
- [m54d-admission-ruff-root-r1-2026-10-01.log](preuves/r14-preuves--m54d-admission-ruff-root-r1-2026-10-01.log.gz)
- [m54d-verifier-root-r1-2026-10-01-apres.json](preuves/r14-preuves--m54d-verifier-root-r1-2026-10-01-apres.json.gz)
- [m54d-verifier-root-r1-2026-10-01-avant.json](preuves/r14-preuves--m54d-verifier-root-r1-2026-10-01-avant.json.gz)
- [m54d-verifier-root-r1-2026-10-01-resultat.json](preuves/r14-preuves--m54d-verifier-root-r1-2026-10-01-resultat.json.gz)
- [m54d-verifier-root-r1-2026-10-01.log](preuves/r14-preuves--m54d-verifier-root-r1-2026-10-01.log.gz)
- [pg-upsert-rowcount-root-r1-2026-10-01-apres.json](preuves/r14-preuves--pg-upsert-rowcount-root-r1-2026-10-01-apres.json.gz)
- [pg-upsert-rowcount-root-r1-2026-10-01-avant.json](preuves/r14-preuves--pg-upsert-rowcount-root-r1-2026-10-01-avant.json.gz)
- [pg-upsert-rowcount-root-r1-2026-10-01-resultat.json](preuves/r14-preuves--pg-upsert-rowcount-root-r1-2026-10-01-resultat.json.gz)
- [pg-upsert-rowcount-root-r1-2026-10-01.log](preuves/r14-preuves--pg-upsert-rowcount-root-r1-2026-10-01.log.gz)
- [provenance.json](preuves/r14-actionlint-reutilisation-root-r1--provenance.json.gz)
- [patch.diff](preuves/r14-admission-reconciliation-integration-root-r1--patch.diff.gz)
- [preparation.json](preuves/r14-admission-reconciliation-integration-root-r1--preparation.json.gz)
- [resultat.json](preuves/r14-admission-reconciliation-integration-root-r1--resultat.json.gz)
- [patch.diff](preuves/r14-admission-returning-pg-integration-root-r1--patch.diff.gz)
- [preparation.json](preuves/r14-admission-returning-pg-integration-root-r1--preparation.json.gz)
- [resultat.json](preuves/r14-admission-returning-pg-integration-root-r1--resultat.json.gz)
- [patch.diff](preuves/r14-admission-trace-depassement-integration-root-r1--patch.diff.gz)
- [preparation.json](preuves/r14-admission-trace-depassement-integration-root-r1--preparation.json.gz)
- [resultat.json](preuves/r14-admission-trace-depassement-integration-root-r1--resultat.json.gz)
- [diagnostic.json](preuves/r14-budgets-pg-int32-red-root-r1--diagnostic.json.gz)
- [reproduire.py](preuves/r14-budgets-pg-int32-red-root-r1--reproduire.py.gz)
- [legacy-after.json](preuves/r14-budgets-pg64-green-root-r2--legacy-after.json.gz)
- [legacy-before.json](preuves/r14-budgets-pg64-green-root-r2--legacy-before.json.gz)
- [qualifier.py](preuves/r14-budgets-pg64-green-root-r2--qualifier.py.gz)
- [resultat.json](preuves/r14-budgets-pg64-green-root-r2--resultat.json.gz)
- [patch.diff](preuves/r14-jetons-int64-integration-root-r1--patch.diff.gz)
- [preparation.json](preuves/r14-jetons-int64-integration-root-r1--preparation.json.gz)
- [resultat.json](preuves/r14-jetons-int64-integration-root-r1--resultat.json.gz)
- [qualifier.py](preuves/r14-jetons-pg-concurrence-root-r1--qualifier.py.gz)
- [resultat.json](preuves/r14-jetons-pg-concurrence-root-r1--resultat.json.gz)
- [patch.diff](preuves/r14-m1-normalisation-rejeu-integration-root-r1--patch.diff.gz)
- [preparation.json](preuves/r14-m1-normalisation-rejeu-integration-root-r1--preparation.json.gz)
- [resultat.json](preuves/r14-m1-normalisation-rejeu-integration-root-r1--resultat.json.gz)
- [patch.diff](preuves/r14-m1-reutilisation-stt-doc-integration-root-r1--patch.diff.gz)
- [preparation.json](preuves/r14-m1-reutilisation-stt-doc-integration-root-r1--preparation.json.gz)
- [resultat.json](preuves/r14-m1-reutilisation-stt-doc-integration-root-r1--resultat.json.gz)
- [patch.diff](preuves/r14-m1-reutilisation-stt-integration-root-r1--patch.diff.gz)
- [preparation.json](preuves/r14-m1-reutilisation-stt-integration-root-r1--preparation.json.gz)
- [resultat.json](preuves/r14-m1-reutilisation-stt-integration-root-r1--resultat.json.gz)
- [patch.diff](preuves/r14-m54d-webras-integration-root-r1--patch.diff.gz)
- [preparation.json](preuves/r14-m54d-webras-integration-root-r1--preparation.json.gz)
- [resultat.json](preuves/r14-m54d-webras-integration-root-r1--resultat.json.gz)
- [observations.json](preuves/r14-pg-upsert-rowcount-root-r1--observations.json.gz)
- [probe.py](preuves/r14-pg-upsert-rowcount-root-r1--probe.py.gz)
- [jetons-m54d-ruff-root-r2-2026-10-01-resultat.json](preuves/r14-preuves--jetons-m54d-ruff-root-r2-2026-10-01-resultat.json.gz)
- [jetons-m54d-ruff-root-r2-2026-10-01.log](preuves/r14-preuves--jetons-m54d-ruff-root-r2-2026-10-01.log.gz)
- [jetons-m54d-ruff-root-r2-2026-10-01-avant.json](preuves/r14-preuves--jetons-m54d-ruff-root-r2-2026-10-01-avant.json.gz)
- [jetons-m54d-ruff-root-r2-2026-10-01-apres.json](preuves/r14-preuves--jetons-m54d-ruff-root-r2-2026-10-01-apres.json.gz)
- [resultat.json](preuves/r14-economie-tokens-doc-integration-root-r1--resultat.json.gz)
- [preparation.json](preuves/r14-economie-tokens-doc-integration-root-r1--preparation.json.gz)
- [patch.diff](preuves/r14-economie-tokens-doc-integration-root-r1--patch.diff.gz)
- [liens.json](preuves/r14-economie-tokens-doc-integration-root-r1--liens.json.gz)
- [manifest-root.json](preuves/r14-economie-tokens-doc-r3-root--manifest-root.json.gz)


## Collecte r15 — rootless R3 et contrôle R14

Cette collecte ajoute 22 références vérifiées au point R14 de 1 035 archives, pour un total de 1 057. Les résultats rootless sont ciblés et n’établissent ni démarrage réel, ni VPS/runtime complet. TOCTOU reste hors de cette collecte.

Références R15 :
- [resultat.json](preuves/r15-rootless-integration-root-r1--resultat.json.gz)
- [preparation.json](preuves/r15-rootless-integration-root-r1--preparation.json.gz)
- [patch.diff](preuves/r15-rootless-integration-root-r1--patch.diff.gz)
- [application.log](preuves/r15-rootless-integration-root-r1--application.log.gz)
- [check.log](preuves/r15-rootless-integration-root-r1--check.log.gz)
- [rootless-qualification-root-r1-2026-10-01-resultat.json](preuves/r15-preuves--rootless-qualification-root-r1-2026-10-01-resultat.json.gz)
- [rootless-qualification-root-r1-2026-10-01.xml](preuves/r15-preuves--rootless-qualification-root-r1-2026-10-01.xml.gz)
- [rootless-qualification-root-r1-2026-10-01.log](preuves/r15-preuves--rootless-qualification-root-r1-2026-10-01.log.gz)
- [rootless-qualification-root-r1-2026-10-01-avant.json](preuves/r15-preuves--rootless-qualification-root-r1-2026-10-01-avant.json.gz)
- [rootless-qualification-root-r1-2026-10-01-apres.json](preuves/r15-preuves--rootless-qualification-root-r1-2026-10-01-apres.json.gz)
- [rootless-ruff-root-r1-2026-10-01-resultat.json](preuves/r15-preuves--rootless-ruff-root-r1-2026-10-01-resultat.json.gz)
- [rootless-ruff-root-r1-2026-10-01.log](preuves/r15-preuves--rootless-ruff-root-r1-2026-10-01.log.gz)
- [rootless-ruff-root-r1-2026-10-01-avant.json](preuves/r15-preuves--rootless-ruff-root-r1-2026-10-01-avant.json.gz)
- [rootless-ruff-root-r1-2026-10-01-apres.json](preuves/r15-preuves--rootless-ruff-root-r1-2026-10-01-apres.json.gz)
- [application.log](preuves/r15-programme-r14-integration-root-r1--application.log.gz)
- [check.log](preuves/r15-programme-r14-integration-root-r1--check.log.gz)
- [patch.diff](preuves/r15-programme-r14-integration-root-r1--patch.diff.gz)
- [preparation.json](preuves/r15-programme-r14-integration-root-r1--preparation.json.gz)
- [resultat.json](preuves/r15-programme-r14-integration-root-r1--resultat.json.gz)
- [append-r14-receipt.json](preuves/r15-r20-append-r14-root-capture--append-r14-receipt.json.gz)
- [r20-independant-root-r14-2026-10-01.json](preuves/r15-preuves--r20-independant-root-r14-2026-10-01.json.gz)
- [coherence.json](preuves/r15-programme-r14-revue-root-r1--coherence.json.gz)


## Collecte r16 — MCP runtime, finance préparatoire et sources documentaires

Cette collecte ajoute des références root-close au point R15 de 1 057 archives. Les résultats couvrent uniquement les périmètres annoncés dans les preuves; ils ne constituent pas une validation globale du produit, un calcul officiel de paie, un fournisseur de production ou un VPS. Les PDF publics ne sont pas inclus.

Références R16 :
- [patch.diff](preuves/r16-runtime-dispatch-integration-root-r1--patch-diff-234b770062.gz)
- [agent-bundle-mcp-runtime.test.ts](preuves/r16-agents--agent-bundle-mcp-runtime-test-ts-b58964ea30.gz)
- [agent-bundle-mcp-runtime.ts](preuves/r16-agents--agent-bundle-mcp-runtime-ts-3484d08467.gz)
- [admission_agents.py](preuves/r16-opsys--admission-agents-py-977358f37b.gz)
- [capacites.py](preuves/r16-opsys--capacites-py-0050bf50d4.gz)
- [serveur_mcp.py](preuves/r16-opsys--serveur-mcp-py-7068c43ff2.gz)
- [test_serveur_mcp_http.py](preuves/r16-tests--test-serveur-mcp-http-py-8df7bcc964.gz)
- [preparation.json](preuves/r16-runtime-dispatch-integration-root-r1--preparation-json-8364de84a9.gz)
- [resultat.json](preuves/r16-runtime-dispatch-integration-root-r1--resultat-json-45be1a53e4.gz)
- [patch.diff](preuves/r16-runtime-dispatch-test-portable-integration-root-r1--patch-diff-ee3ae6c0d4.gz)
- [test_serveur_mcp_http.py](preuves/r16-tests--test-serveur-mcp-http-py-25352c2000.gz)
- [preparation.json](preuves/r16-runtime-dispatch-test-portable-integration-root-r1--preparation-json-590ef3e180.gz)
- [resultat.json](preuves/r16-runtime-dispatch-test-portable-integration-root-r1--resultat-json-007269c410.gz)
- [patch.diff](preuves/r16-m58a-integration-root-r1--patch-diff-a87a541893.gz)
- [outils.py](preuves/r16-m5-financecore--outils-py-7baa974468.gz)
- [registre.py](preuves/r16-m5-financecore--registre-py-f5fe9d8554.gz)
- [validation.py](preuves/r16-m5-financecore--validation-py-63e4803c27.gz)
- [preparation.json](preuves/r16-m58a-integration-root-r1--preparation-json-3b60c21b14.gz)
- [resultat.json](preuves/r16-m58a-integration-root-r1--resultat-json-78aeaf885b.gz)
- [patch.diff](preuves/r16-m58a-classement-integration-root-r1--patch-diff-6e501e713e.gz)
- [analyse.py](preuves/r16-m5-financecore--analyse-py-7b10680cda.gz)
- [test_analyse_mention.py](preuves/r16-tests--test-analyse-mention-py-b8308bd93a.gz)
- [test_brut_regulier.py](preuves/r16-tests--test-brut-regulier-py-aa76f1720e.gz)
- [preparation.json](preuves/r16-m58a-classement-integration-root-r1--preparation-json-0e98a52adc.gz)
- [resultat.json](preuves/r16-m58a-classement-integration-root-r1--resultat-json-4d5161c1a6.gz)
- [expected.json](preuves/r16-m58a-classement-revue-root-r1--expected-json-005af0a778.gz)
- [review.json](preuves/r16-m58a-classement-revue-root-r1--review-json-b9647ac261.gz)
- [patch.diff](preuves/r16-imports-runtime-m58a-integration-root-r2--patch-diff-3df370d70e.gz)
- [outils.py](preuves/r16-m5-financecore--outils-py-c344a664da.gz)
- [test_echeanciers_contrats_prevision.py](preuves/r16-tests--test-echeanciers-contrats-prevision-py-83056ba2d2.gz)
- [test_serveur_mcp_http.py](preuves/r16-tests--test-serveur-mcp-http-py-851b68a6ec.gz)
- [preparation.json](preuves/r16-imports-runtime-m58a-integration-root-r2--preparation-json-a411ffa8c6.gz)
- [resultat.json](preuves/r16-imports-runtime-m58a-integration-root-r2--resultat-json-9c8aa2ba1d.gz)
- [runtime-dispatch-core-probe-cwd-core-root-r1-2026-10-01-resultat.json](preuves/r16-preuves--runtime-dispatch-core-probe-cwd-core-root-r1-2026-10-01-resultat-json-82d4d35e9b.gz)
- [runtime-dispatch-core-probe-cwd-core-root-r1-2026-10-01-avant.json](preuves/r16-preuves--runtime-dispatch-core-probe-cwd-core-root-r1-2026-10-01-avant-json-c72c47502b.gz)
- [runtime-dispatch-core-probe-cwd-core-root-r1-2026-10-01-apres.json](preuves/r16-preuves--runtime-dispatch-core-probe-cwd-core-root-r1-2026-10-01-apres-json-2e95fe0fdf.gz)
- [runtime-dispatch-core-probe-cwd-repo-root-r1-2026-10-01-resultat.json](preuves/r16-preuves--runtime-dispatch-core-probe-cwd-repo-root-r1-2026-10-01-resultat-json-94491b22d6.gz)
- [runtime-dispatch-core-probe-cwd-repo-root-r1-2026-10-01-avant.json](preuves/r16-preuves--runtime-dispatch-core-probe-cwd-repo-root-r1-2026-10-01-avant-json-cd4337c56d.gz)
- [runtime-dispatch-core-probe-cwd-repo-root-r1-2026-10-01-apres.json](preuves/r16-preuves--runtime-dispatch-core-probe-cwd-repo-root-r1-2026-10-01-apres-json-0e5c1968c4.gz)
- [runtime-dispatch-core-root-r1-2026-10-01-resultat.json](preuves/r16-preuves--runtime-dispatch-core-root-r1-2026-10-01-resultat-json-4f6046dbd2.gz)
- [runtime-dispatch-core-root-r1-2026-10-01-avant.json](preuves/r16-preuves--runtime-dispatch-core-root-r1-2026-10-01-avant-json-2951477956.gz)
- [runtime-dispatch-core-root-r1-2026-10-01-apres.json](preuves/r16-preuves--runtime-dispatch-core-root-r1-2026-10-01-apres-json-f7b3217498.gz)
- [runtime-dispatch-core-root-r2-2026-10-01-resultat.json](preuves/r16-preuves--runtime-dispatch-core-root-r2-2026-10-01-resultat-json-f42f81d502.gz)
- [runtime-dispatch-core-root-r2-2026-10-01-avant.json](preuves/r16-preuves--runtime-dispatch-core-root-r2-2026-10-01-avant-json-8df110bd12.gz)
- [runtime-dispatch-core-root-r2-2026-10-01-apres.json](preuves/r16-preuves--runtime-dispatch-core-root-r2-2026-10-01-apres-json-af0ba7f106.gz)
- [runtime-dispatch-core-root-r3-2026-10-01-resultat.json](preuves/r16-preuves--runtime-dispatch-core-root-r3-2026-10-01-resultat-json-45b1b9d928.gz)
- [runtime-dispatch-core-root-r3-2026-10-01-avant.json](preuves/r16-preuves--runtime-dispatch-core-root-r3-2026-10-01-avant-json-3dcf907d85.gz)
- [runtime-dispatch-core-root-r3-2026-10-01-apres.json](preuves/r16-preuves--runtime-dispatch-core-root-r3-2026-10-01-apres-json-4dfabdc8bd.gz)
- [runtime-dispatch-python-root-r1-2026-10-01-resultat.json](preuves/r16-preuves--runtime-dispatch-python-root-r1-2026-10-01-resultat-json-d72551c8a6.gz)
- [runtime-dispatch-python-root-r1-2026-10-01-avant.json](preuves/r16-preuves--runtime-dispatch-python-root-r1-2026-10-01-avant-json-e3980c0b53.gz)
- [runtime-dispatch-python-root-r1-2026-10-01-apres.json](preuves/r16-preuves--runtime-dispatch-python-root-r1-2026-10-01-apres-json-81fe9994fa.gz)
- [runtime-dispatch-python-root-r2-2026-10-01-resultat.json](preuves/r16-preuves--runtime-dispatch-python-root-r2-2026-10-01-resultat-json-497beee037.gz)
- [runtime-dispatch-python-root-r2-2026-10-01-avant.json](preuves/r16-preuves--runtime-dispatch-python-root-r2-2026-10-01-avant-json-a6eb5d4945.gz)
- [runtime-dispatch-python-root-r2-2026-10-01-apres.json](preuves/r16-preuves--runtime-dispatch-python-root-r2-2026-10-01-apres-json-3e28c34f89.gz)
- [profile-runtime-toctou-pg-root-r3-2026-10-01-resultat.json](preuves/r16-preuves--profile-runtime-toctou-pg-root-r3-2026-10-01-resultat-json-d686cbefe7.gz)
- [profile-runtime-toctou-pg-root-r3-2026-10-01-avant.json](preuves/r16-preuves--profile-runtime-toctou-pg-root-r3-2026-10-01-avant-json-c9e8b00928.gz)
- [profile-runtime-toctou-pg-root-r3-2026-10-01-apres.json](preuves/r16-preuves--profile-runtime-toctou-pg-root-r3-2026-10-01-apres-json-4b4b8e73f0.gz)
- [README.md](preuves/r16-profile-runtime-toctou-pg-r3--readme-md-cf4c3a18cc.gz)
- [docker](preuves/r16-profile-runtime-toctou-pg-r3--docker-880778ec01.gz)
- [preparation.json](preuves/r16-profile-runtime-toctou-pg-r3--preparation-json-39a39dc116.gz)
- [result.json](preuves/r16-profile-runtime-toctou-pg-r3--result-json-0307c507b4.gz)
- [root-verification.json](preuves/r16-profile-runtime-toctou-pg-r3--root-verification-json-33294e3607.gz)
- [probe_profile_runtime_toctou_pg.py](preuves/r16-profile-runtime-toctou-pg-r2--probe-profile-runtime-toctou-pg-py-e7aab00e02.gz)
- [m58a-finance-runtime-integres-root-r1-2026-10-01-resultat.json](preuves/r16-preuves--m58a-finance-runtime-integres-root-r1-2026-10-01-resultat-json-f89264f9e4.gz)
- [m58a-finance-runtime-integres-root-r1-2026-10-01-avant.json](preuves/r16-preuves--m58a-finance-runtime-integres-root-r1-2026-10-01-avant-json-e522e699d6.gz)
- [m58a-finance-runtime-integres-root-r1-2026-10-01-apres.json](preuves/r16-preuves--m58a-finance-runtime-integres-root-r1-2026-10-01-apres-json-cb43a4d8c6.gz)
- [m58a-finance-runtime-integres-root-r2-2026-10-01-resultat.json](preuves/r16-preuves--m58a-finance-runtime-integres-root-r2-2026-10-01-resultat-json-9573718f4e.gz)
- [m58a-finance-runtime-integres-root-r2-2026-10-01-avant.json](preuves/r16-preuves--m58a-finance-runtime-integres-root-r2-2026-10-01-avant-json-a8b87ce701.gz)
- [m58a-finance-runtime-integres-root-r2-2026-10-01-apres.json](preuves/r16-preuves--m58a-finance-runtime-integres-root-r2-2026-10-01-apres-json-c6cc0861d0.gz)
- [runtime-m58a-verifier-root-r2-2026-10-01-resultat.json](preuves/r16-preuves--runtime-m58a-verifier-root-r2-2026-10-01-resultat-json-d8f2cf1145.gz)
- [runtime-m58a-verifier-root-r2-2026-10-01-avant.json](preuves/r16-preuves--runtime-m58a-verifier-root-r2-2026-10-01-avant-json-b0f62e937e.gz)
- [runtime-m58a-verifier-root-r2-2026-10-01-apres.json](preuves/r16-preuves--runtime-m58a-verifier-root-r2-2026-10-01-apres-json-7453dbcbc4.gz)
- [runtime-m58a-ruff-root-r2-2026-10-01-resultat.json](preuves/r16-preuves--runtime-m58a-ruff-root-r2-2026-10-01-resultat-json-0815a4df93.gz)
- [runtime-m58a-ruff-root-r2-2026-10-01-avant.json](preuves/r16-preuves--runtime-m58a-ruff-root-r2-2026-10-01-avant-json-460ac2963c.gz)
- [runtime-m58a-ruff-root-r2-2026-10-01-apres.json](preuves/r16-preuves--runtime-m58a-ruff-root-r2-2026-10-01-apres-json-9b6a6df7a9.gz)
- [runtime-m58a-diff-check-root-r1-2026-10-01-resultat.json](preuves/r16-preuves--runtime-m58a-diff-check-root-r1-2026-10-01-resultat-json-12106b1886.gz)
- [runtime-m58a-diff-check-root-r1-2026-10-01-avant.json](preuves/r16-preuves--runtime-m58a-diff-check-root-r1-2026-10-01-avant-json-89d848c536.gz)
- [runtime-m58a-diff-check-root-r1-2026-10-01-apres.json](preuves/r16-preuves--runtime-m58a-diff-check-root-r1-2026-10-01-apres-json-d9d7a320fb.gz)
- [tests-r2.xml](preuves/r16-proofs--tests-r2-xml-515b7a6771.gz)
- [tests-r2.log](preuves/r16-proofs--tests-r2-log-22e63aa4de.gz)
- [manifest.json](preuves/r16-proofs--manifest-json-1abb947c58.gz)
- [sources-officielles-verification-root-r1.json](preuves/r16-preuves--sources-officielles-verification-root-r1-json-d9dbb33c26.gz)
- [manifest.sha256](preuves/r16-opsys-m5-sources-officielles-20261001-r1--manifest-sha256-29a0518481.gz)
- [rapport.md](preuves/r16-opsys-m5-sources-officielles-20261001-r1--rapport-md-b2d3d67831.gz)
- [doc-version-index.md](preuves/r16-opsys-m5-sources-officielles-20261001-r1--doc-version-index-md-9f58aeda87.gz)
- [capture-metadata-r1.txt](preuves/r16-opsys-m5-sources-officielles-20261001-r1--capture-metadata-r1-txt-68df40504e.gz)
- [capture-time-utc.txt](preuves/r16-opsys-m5-sources-officielles-20261001-r1--capture-time-utc-txt-5faeaaf69f.gz)
- [fetch-command.txt](preuves/r16-opsys-m5-sources-officielles-20261001-r1--fetch-command-txt-e54af0469f.gz)
- [http-page-probes.tsv](preuves/r16-opsys-m5-sources-officielles-20261001-r1--http-page-probes-tsv-89d4f6ac42.gz)
- [http-pdf-results.tsv](preuves/r16-opsys-m5-sources-officielles-20261001-r1--http-pdf-results-tsv-7492fdf146.gz)
- [pdf-cover-excerpts.txt](preuves/r16-opsys-m5-sources-officielles-20261001-r1--pdf-cover-excerpts-txt-6350435707.gz)
- [pdfinfo.tsv](preuves/r16-opsys-m5-sources-officielles-20261001-r1--pdfinfo-tsv-d4df9a7514.gz)
- [CRA-T4127-Jan-2026-landing.html](preuves/r16-reference-pages--cra-t4127-jan-2026-landing-html-ebfe521718.gz)
- [CRA-T4127-Jul-2026-landing.html](preuves/r16-reference-pages--cra-t4127-jul-2026-landing-html-c7197a6372.gz)
- [Canada-terms.html](preuves/r16-reference-pages--canada-terms-html-697ab598e5.gz)
- [7.html](preuves/r16-officiel--7-html-fe89856203.gz)
- [8.html](preuves/r16-officiel--8-html-cbd818498f.gz)
- [core-symlinks-circulaires-root-r1-avant.json](preuves/r16-preuves--core-symlinks-circulaires-root-r1-avant-json-6f3acb9f2c.gz)
- [core-symlinks-circulaires-root-r1-resultat.json](preuves/r16-preuves--core-symlinks-circulaires-root-r1-resultat-json-0e8757033e.gz)
- [core-symlinks-circulaires-root-r1-sources-avant.json](preuves/r16-preuves--core-symlinks-circulaires-root-r1-sources-avant-json-be381139e2.gz)
- [cache-pnpm-nettoyage-root-r1-avant.json](preuves/r16-preuves--cache-pnpm-nettoyage-root-r1-avant-json-4ad4058116.gz)
- [cache-pnpm-nettoyage-root-r2-resultat.json](preuves/r16-preuves--cache-pnpm-nettoyage-root-r2-resultat-json-0857315948.gz)
- [manifest.json](preuves/r16-pnpm-store-cache-audit-r1--manifest-json-e7010670e2.gz)
- [rapport.md](preuves/r16-pnpm-store-cache-audit-r1--rapport-md-2195f5a72f.gz)
- [resultat.json](preuves/r16-pnpm-store-cache-audit-r1--resultat-json-968e6d2119.gz)
- [BILAN-RESTRUCTURATION-2026-09-30.md](preuves/r16-programme--bilan-restructuration-2026-09-30-md-4039052ef7.gz)
- [BILAN-RESTRUCTURATION-2026-09-30.md](preuves/r16-programme--bilan-restructuration-2026-09-30-md-6c072d039f.gz)
- [RESTRUCTURATION-2026-09-30.md](preuves/r16-programme--restructuration-2026-09-30-md-f0f004a906.gz)
- [RESTRUCTURATION-2026-09-30.md](preuves/r16-programme--restructuration-2026-09-30-md-228b260be2.gz)
- [M5-CFO-IA-FISCALITE-PAIE-STRATEGIE-AUDIT.md](preuves/r16-compta--m5-cfo-ia-fiscalite-paie-strategie-audit-md-b6466339f8.gz)
- [M5-CFO-IA-FISCALITE-PAIE-STRATEGIE-AUDIT.md](preuves/r16-compta--m5-cfo-ia-fiscalite-paie-strategie-audit-md-7a8e1b107f.gz)
- [patch-r16-docs.diff](preuves/r16-programme-r16-preparation-root-r2--patch-r16-docs-diff-b173e378cb.gz)
- [append-r16-root-execute-only.py](preuves/r16-programme-r16-preparation-root-r2--append-r16-root-execute-only-py-916f7fdee0.gz)
- [tranche-profils-contrats-reconciliation-root-r1.json](preuves/r16-preuves--tranche-profils-contrats-reconciliation-root-r1-json-b45c23b63c.gz)


## Complément r16a — artefacts JUnit et note M5.8a

Ce complément rattache les journaux/JUnit finaux manquants au point R16 de 1 171 archives. Les résultats couvrent uniquement les périmètres annoncés dans les preuves; ils ne constituent pas une validation globale du produit, un calcul officiel de paie, un fournisseur de production ou un VPS. Les PDF publics ne sont pas inclus.

Références R16a :
- [m58a-finance-runtime-integres-root-r2-2026-10-01.log](preuves/r16a-preuves--m58a-finance-runtime-integres-root-r2-2026-10-01-log-eb1e23ba09.gz)
- [m58a-finance-runtime-integres-root-r2-2026-10-01.xml](preuves/r16a-preuves--m58a-finance-runtime-integres-root-r2-2026-10-01-xml-d704805d0d.gz)
- [runtime-dispatch-core-root-r3-2026-10-01.log](preuves/r16a-preuves--runtime-dispatch-core-root-r3-2026-10-01-log-3cbc9dbe13.gz)
- [runtime-dispatch-core-root-r3-2026-10-01.xml](preuves/r16a-preuves--runtime-dispatch-core-root-r3-2026-10-01-xml-9d63c54e28.gz)
- [M5.8a-echeanciers-contrats.md](preuves/r16a-m05-financecore--m5-8a-echeanciers-contrats-md-8f46d5aaaa.gz)
- [M5.8a-echeanciers-contrats.md](preuves/r16a-m05-financecore--m5-8a-echeanciers-contrats-md-2349a28dcd.gz)
- [patch-r16a-m58a-doc.diff](preuves/r16a-r16a-complement-root-r1--patch-r16a-m58a-doc-diff-d9e89a870c.gz)
- [append-r16a-root-execute-only.py](preuves/r16a-r16a-complement-root-r1--append-r16a-root-execute-only-py-04db285005.gz)


## Collecte R17 — M5.3a rapprochement bancaire préparatoire

Cette collecte ajoute des preuves root ciblées au point de départ de 1 179 archives. La campagne M5.3a compte 2 444 cas, dont les 24 tests moteur inclus dans M5 et les 19 tests console inclus dans 262 tests socle; ces sous-totaux ne s’ajoutent pas. Les cas dont le nom correspond à `-k not postgresql` sont exclus; concurrence bancaire PostgreSQL non qualifiée. Aucun connecteur bancaire, paiement, approbation finale ou qualification globale n’est revendiqué.

Références R17 :
- [m53a-finance-console-integres-root-r1-2026-10-01-resultat.json](preuves/r17-preuves--m53a-finance-console-integres-root-r1-2026-10-01-resultat-json-ecb703a783.gz)
- [m53a-finance-console-integres-root-r1-2026-10-01.xml](preuves/r17-preuves--m53a-finance-console-integres-root-r1-2026-10-01-xml-cfcc4c08f3.gz)
- [m53a-finance-console-integres-root-r1-2026-10-01.log](preuves/r17-preuves--m53a-finance-console-integres-root-r1-2026-10-01-log-fa1f35f466.gz)
- [verification.json](preuves/r17-m53a-cloture-independante-root-r2--verification-json-cde5e4f5ab.gz)
- [m53a-ruff-root-r1-2026-10-01-resultat.json](preuves/r17-preuves--m53a-ruff-root-r1-2026-10-01-resultat-json-3e10e6ab0b.gz)
- [m53a-verifier-root-r1-2026-10-01-resultat.json](preuves/r17-preuves--m53a-verifier-root-r1-2026-10-01-resultat-json-c2d98b6da7.gz)
- [m53a-verifier-root-r1-2026-10-01.log](preuves/r17-preuves--m53a-verifier-root-r1-2026-10-01-log-2535ad9f06.gz)
- [resultat.json](preuves/r17-m53a-moteur-integration-root-r1--resultat-json-bb3f5d4811.gz)
- [patch.diff](preuves/r17-m53a-moteur-integration-root-r1--patch-diff-6f9f2c0895.gz)
- [resultat.json](preuves/r17-m53a-console-integration-root-r3--resultat-json-79ecb98ca1.gz)
- [patch.diff](preuves/r17-m53a-console-integration-root-r3--patch-diff-6577b204cd.gz)
- [revue.md](preuves/r17-m53a-moteur-revue-root-r1--revue-md-4e97fb246e.gz)
- [revue.md](preuves/r17-m53a-console-revue-root-r3--revue-md-a4507cf71a.gz)
- [manifest-root.json](preuves/r17-m53a-console-revue-root-r3--manifest-root-json-555522a0c3.gz)
- [verification-refusee.json](preuves/r17-m53a-cloture-independante-root-r1--verification-refusee-json-fb06594e42.gz)
- [m53a-finance-console-integres-root-r1-2026-10-01-avant.json](preuves/r17-preuves--m53a-finance-console-integres-root-r1-2026-10-01-avant-json-75b8097fb5.gz)
- [m53a-finance-console-integres-root-r1-2026-10-01-apres.json](preuves/r17-preuves--m53a-finance-console-integres-root-r1-2026-10-01-apres-json-22e06775f5.gz)
- [expected.json](preuves/r17-m53a-console-revue-root-r3--expected-json-6083095949.gz)
- [BILAN-RESTRUCTURATION-2026-09-30.md](preuves/r17-programme--bilan-restructuration-2026-09-30-md-f362789cce.gz)
- [RESTRUCTURATION-2026-09-30.md](preuves/r17-programme--restructuration-2026-09-30-md-c21837c83f.gz)
- [M5-CFO-IA-FISCALITE-PAIE-STRATEGIE-AUDIT.md](preuves/r17-compta--m5-cfo-ia-fiscalite-paie-strategie-audit-md-44d6bf99c5.gz)
- [M5.3-a-CSV-AR.md](preuves/r17-docs--m5-3-a-csv-ar-md-23881af2e0.gz)
- [patch-r17-docs.diff](preuves/r17-programme-r17-preparation-root-r1--patch-r17-docs-diff-fa1a90467f.gz)
- [R17-preparation.md](preuves/r17-programme-r17-preparation-root-r1--r17-preparation-md-c9dd45607c.gz)
- [append-r17-root-execute-only.py](preuves/r17-programme-r17-preparation-root-r1--append-r17-root-execute-only-py-3d257565a5.gz)
- [M5.3-a-CSV-AR.md](preuves/r17-preimages--m5-3-a-csv-ar-md-ecaeb9f75e.gz)


## Complément R17a — rectifications documentaires R17

Ce complément rattache les reçus root de l’append R17 et les corrections documentaires R2 au R20 de 1 205 archives. Il ne contient ni nouvelle campagne de tests ni nouvelle qualification produit; les 1 205 archives antérieures sont conservées octet pour octet et R19 reste scellé.

Références R17a :
- [append-r17-receipt.json](preuves/r17a-r20-append-r17-root-capture--append-r17-receipt-json-9d1c5f29ee.gz)
- [resultat.json](preuves/r17a-programme-r17-integration-root-r2--resultat-json-4652c6e132.gz)
- [archives-verifiees.json](preuves/r17a-programme-r17-revue-root-r1--archives-verifiees-json-293f23a1e2.gz)
- [documents-integres-verifies.json](preuves/r17a-programme-r17-revue-root-r1--documents-integres-verifies-json-137ae31921.gz)
- [revue.json](preuves/r17a-programme-r17-revue-root-r1--revue-json-ab7d3dc239.gz)
- [manifest-root.json](preuves/r17a-programme-r17-documentation-root-r2--manifest-root-json-ccc699952f.gz)
- [patch.diff](preuves/r17a-programme-r17-documentation-root-r2--patch-diff-7d6176abe5.gz)
- [BILAN-RESTRUCTURATION-2026-09-30.md](preuves/r17a-programme--bilan-restructuration-2026-09-30-md-c59c276773.gz)
- [M5.3-a-CSV-AR.md](preuves/r17a-docs--m5-3-a-csv-ar-md-b60e372436.gz)


## Complément R18 — médias privés M7.3a

Ce complément rattache les preuves root closes de M7.3a et les cinq documents R18 au R20 de 1 214 archives. Il ne qualifie pas M7 au complet ni aucun fournisseur, navigateur, VPS ou usage PostgreSQL; les 1 214 archives antérieures sont conservées octet pour octet et R19 reste scellé.

Références R18 :
- [m73a-marketing-console-integres-root-r1-2026-10-01-avant.json](preuves/r18-preuves--m73a-marketing-console-integres-root-r1-2026-10-01-avant-json-9d573ac286.gz)
- [m73a-marketing-console-integres-root-r1-2026-10-01-apres.json](preuves/r18-preuves--m73a-marketing-console-integres-root-r1-2026-10-01-apres-json-b66019e9e7.gz)
- [m73a-marketing-console-integres-root-r1-2026-10-01-resultat.json](preuves/r18-preuves--m73a-marketing-console-integres-root-r1-2026-10-01-resultat-json-aab3d9c2e7.gz)
- [m73a-marketing-console-integres-root-r1-2026-10-01.xml](preuves/r18-preuves--m73a-marketing-console-integres-root-r1-2026-10-01-xml-d4c76cecab.gz)
- [m73a-marketing-console-integres-root-r1-2026-10-01.log](preuves/r18-preuves--m73a-marketing-console-integres-root-r1-2026-10-01-log-1c43560d7a.gz)
- [m73a-ruff-root-r1-2026-10-01-avant.json](preuves/r18-preuves--m73a-ruff-root-r1-2026-10-01-avant-json-ed5ec44e8b.gz)
- [m73a-ruff-root-r1-2026-10-01-apres.json](preuves/r18-preuves--m73a-ruff-root-r1-2026-10-01-apres-json-716257fd4c.gz)
- [m73a-ruff-root-r1-2026-10-01-resultat.json](preuves/r18-preuves--m73a-ruff-root-r1-2026-10-01-resultat-json-8bb466cbf1.gz)
- [m73a-verifier-root-r1-2026-10-01-avant.json](preuves/r18-preuves--m73a-verifier-root-r1-2026-10-01-avant-json-7e418ac131.gz)
- [m73a-verifier-root-r1-2026-10-01-apres.json](preuves/r18-preuves--m73a-verifier-root-r1-2026-10-01-apres-json-b38e40bfc0.gz)
- [m73a-verifier-root-r1-2026-10-01-resultat.json](preuves/r18-preuves--m73a-verifier-root-r1-2026-10-01-resultat-json-5e77c4ab23.gz)
- [verification.json](preuves/r18-m73a-cloture-independante-root-r1--verification-json-061d6a4c0f.gz)
- [resultat.json](preuves/r18-m73a-integration-root-r4--resultat-json-f24b78b5dc.gz)
- [preparation.json](preuves/r18-m73a-integration-root-r4--preparation-json-57dfa31147.gz)
- [patch.diff](preuves/r18-m73a-integration-root-r4--patch-diff-8984d2392c.gz)
- [manifest-root.json](preuves/r18-m73a-candidate-integration-root-r3--manifest-root-json-1dffd73029.gz)
- [patch.diff](preuves/r18-m73a-candidate-integration-root-r3--patch-diff-c6d97bfced.gz)
- [expected.json](preuves/r18-m73a-candidate-integration-root-r3--expected-json-9a0e9148ef.gz)
- [manifest-root.json](preuves/r18-m73a-candidate-integration-root-r4--manifest-root-json-55b78db085.gz)
- [fichiers.py](preuves/r18-opsys--fichiers-py-1c24c091a3.gz)
- [test_fichiers.py](preuves/r18-tests--test-fichiers-py-8eb815b307.gz)
- [test_console_calendrier_marketing.py](preuves/r18-tests--test-console-calendrier-marketing-py-24b835d693.gz)
- [m73a-manifest-candidate-final-r1.json](preuves/r18-preuves--m73a-manifest-candidate-final-r1-json-7d2616430e.gz)
- [m73a-red-cas.xml](preuves/r18-preuves--m73a-red-cas-xml-84a8f9a505.gz)
- [m73a-red-pliage-malforme-r1.xml](preuves/r18-preuves--m73a-red-pliage-malforme-r1-xml-f1d842574b.gz)
- [r2-red-reemission.xml](preuves/r18-preuves--r2-red-reemission-xml-0e4550e8ba.gz)
- [r2-red-reemission.log](preuves/r18-preuves--r2-red-reemission-log-c26f689856.gz)
- [r2-red-texte-sur-r1.xml](preuves/r18-preuves--r2-red-texte-sur-r1-xml-d4d4887767.gz)
- [r2-red-texte-sur-r1.log](preuves/r18-preuves--r2-red-texte-sur-r1-log-85930ec13b.gz)
- [r2-green-integrated-reemission-texte.xml](preuves/r18-preuves--r2-green-integrated-reemission-texte-xml-2db53b5fcb.gz)
- [r2-green-integrated-reemission-texte.log](preuves/r18-preuves--r2-green-integrated-reemission-texte-log-57be52af46.gz)
- [manifest-r3-integrite.json](preuves/r18-preuves--manifest-r3-integrite-json-fe755d7733.gz)
- [patch-r3-integrite.diff](preuves/r18-preuves--patch-r3-integrite-diff-eb766cd1eb.gz)
- [r3-red-foreign-remise.xml](preuves/r18-preuves--r3-red-foreign-remise-xml-b6a5371165.gz)
- [r3-red-foreign-remise.log](preuves/r18-preuves--r3-red-foreign-remise-log-fdeeb2e902.gz)
- [r3-green-fold-regression.xml](preuves/r18-preuves--r3-green-fold-regression-xml-19a24a6a9c.gz)
- [r3-green-fold-regression.log](preuves/r18-preuves--r3-green-fold-regression-log-ee09f6debd.gz)
- [resultat-r3.json](preuves/r18-proofs--resultat-r3-json-9de3b2cade.gz)
- [command-r1.sh](preuves/r18-proofs--command-r1-sh-d9f492952c.gz)
- [patch-tests-only-r3.diff](preuves/r18-proofs--patch-tests-only-r3-diff-4c20c065ea.gz)
- [red-direct.log](preuves/r18-proofs--red-direct-log-1ab9905d8b.gz)
- [ruff-fix.log](preuves/r18-proofs--ruff-fix-log-aac3a0503d.gz)
- [sources-before.sha256](preuves/r18-proofs--sources-before-sha256-67e79d0247.gz)
- [artifacts-r3.sha256](preuves/r18-proofs--artifacts-r3-sha256-252cea207d.gz)
- [tests-final-r1.xml](preuves/r18-proofs--tests-final-r1-xml-9ebf92b604.gz)
- [tests-final-r1.log](preuves/r18-proofs--tests-final-r1-log-400f81f024.gz)
- [resultat-r2-retry1.json](preuves/r18-proofs--resultat-r2-retry1-json-0b1919a9ab.gz)
- [tests-final-r2.xml](preuves/r18-proofs--tests-final-r2-xml-d1811bc212.gz)
- [tests-final-r2.log](preuves/r18-proofs--tests-final-r2-log-3664ef923d.gz)
- [tests-final-retry1.xml](preuves/r18-proofs--tests-final-retry1-xml-19bf4d6fe5.gz)
- [tests-final-retry1.log](preuves/r18-proofs--tests-final-retry1-log-2f10f4b7a8.gz)
- [artifacts-retry1.sha256](preuves/r18-proofs--artifacts-retry1-sha256-fa7df07982.gz)
- [revue.json](preuves/r18-m73a-revue-finale-root-r1--revue-json-d709afba6b.gz)
- [starlette-parser-observe.py](preuves/r18-m73a-revue-finale-root-r1--starlette-parser-observe-py-ae9a35c5cb.gz)
- [BILAN-RESTRUCTURATION-2026-09-30.md](preuves/r18-programme--bilan-restructuration-2026-09-30-md-7c4ac635a8.gz)
- [RESTRUCTURATION-2026-09-30.md](preuves/r18-programme--restructuration-2026-09-30-md-232af8e1dd.gz)
- [M7-MATRICE-CAPACITES-2026-09-30.md](preuves/r18-marketing--m7-matrice-capacites-2026-09-30-md-68724f724a.gz)
- [M7-AUDIT-INITIAL.md](preuves/r18-marketing--m7-audit-initial-md-aac349cedb.gz)
- [M7-3A-MEDIAS.md](preuves/r18-docs--m7-3a-medias-md-bfe6b541bb.gz)
- [M7-MATRICE-CAPACITES-2026-09-30.md](preuves/r18-marketing--m7-matrice-capacites-2026-09-30-md-8ed7f7df48.gz)
- [M7-AUDIT-INITIAL.md](preuves/r18-marketing--m7-audit-initial-md-89c55c86db.gz)
- [M7-3A-MEDIAS.md](preuves/r18-docs--m7-3a-medias-md-902e69b1f8.gz)
- [docs-r18.diff](preuves/r18-programme-r18-final-root-r1--docs-r18-diff-8af3c64b60.gz)
- [manifest-r18.json](preuves/r18-programme-r18-final-root-r1--manifest-r18-json-65bbe67eaf.gz)
- [evidence-inventory.json](preuves/r18-programme-r18-final-root-r1--evidence-inventory-json-ca36e1f605.gz)
- [expected-paths-root-r3.json](preuves/r18-programme-r18-final-root-r1--expected-paths-root-r3-json-6afda2623f.gz)
- [append-r18-root-execute-only-r2.py](preuves/r18-programme-r18-final-root-r1--append-r18-root-execute-only-r2-py-9773ccbc30.gz)
- [root-review-docs-r1.json](preuves/r18-programme-r18-final-root-r1--root-review-docs-r1-json-731025f597.gz)
- [verifier_m73a_cloture_root_r1.py](preuves/r18-restructuration-opsys-2026-10-01--verifier-m73a-cloture-root-r1-py-40c81f9af3.gz)


## Complément R19 — lecture privée M7.4a Growth

Ce complément rattache les preuves root closes de M7.4a et les documents ROOT gelés R19 au R20 de 1283 archives. Il ne qualifie pas M7 au complet ni aucun fournisseur, navigateur, VPS ou usage PostgreSQL; les 1283 archives antérieures sont conservées octet pour octet et R19 reste scellé.

Références R19 :
- [manifest-root-r4.json](preuves/r19-opsys-m74a-growth-console-root-r1-2026-10-01--manifest-root-r4-json-6369648caa.gz)
- [expected-root-r4.json](preuves/r19-opsys-m74a-growth-console-root-r1-2026-10-01--expected-root-r4-json-ee377e6b68.gz)
- [patch-root-r4.diff](preuves/r19-opsys-m74a-growth-console-root-r1-2026-10-01--patch-root-r4-diff-2196dfaa87.gz)
- [manifest-root-r5.json](preuves/r19-opsys-m74a-growth-console-root-r1-2026-10-01--manifest-root-r5-json-875ad403ef.gz)
- [patch-root-r5.diff](preuves/r19-opsys-m74a-growth-console-root-r1-2026-10-01--patch-root-r5-diff-74798876d3.gz)
- [manifest-root-r6.json](preuves/r19-opsys-m74a-growth-console-root-r1-2026-10-01--manifest-root-r6-json-9424ef0dd3.gz)
- [patch-root-r6.diff](preuves/r19-opsys-m74a-growth-console-root-r1-2026-10-01--patch-root-r6-diff-a00936d443.gz)
- [growth_lecture.py](preuves/r19-m7-marketing--growth-lecture-py-ccbb72373f.gz)
- [test_growth_lecture.py](preuves/r19-tests--test-growth-lecture-py-f0228c8fa7.gz)
- [application.py](preuves/r19-console--application-py-d7c23a8ae4.gz)
- [frontoffice_marketing.py](preuves/r19-console--frontoffice-marketing-py-67865fc01b.gz)
- [marketing_cmo_ui.py](preuves/r19-console--marketing-cmo-ui-py-cad2577678.gz)
- [marketing_growth_ui.py](preuves/r19-console--marketing-growth-ui-py-6ebed20ab2.gz)
- [test_console_growth.py](preuves/r19-tests--test-console-growth-py-74a84377e2.gz)
- [growth_lecture.py](preuves/r19-m7-marketing--growth-lecture-py-5b9f73e9c8.gz)
- [test_growth_lecture.py](preuves/r19-tests--test-growth-lecture-py-cbbc771076.gz)
- [test_console_growth.py](preuves/r19-tests--test-console-growth-py-e79e779cde.gz)
- [red-codec-r5-resultat.json](preuves/r19-proofs--red-codec-r5-resultat-json-7b6fe0e1d8.gz)
- [red-codec-r5.log](preuves/r19-proofs--red-codec-r5-log-d2b2b50967.gz)
- [red-codec-r5.xml](preuves/r19-proofs--red-codec-r5-xml-f937441319.gz)
- [red-pseudo-plan-r6-resultat.json](preuves/r19-proofs--red-pseudo-plan-r6-resultat-json-8bb2446302.gz)
- [red-pseudo-plan-r6.log](preuves/r19-proofs--red-pseudo-plan-r6-log-bb508a7a3a.gz)
- [red-pseudo-plan-r6.xml](preuves/r19-proofs--red-pseudo-plan-r6-xml-14660cbb80.gz)
- [green-composition-r5-resultat.json](preuves/r19-proofs--green-composition-r5-resultat-json-56a0344c20.gz)
- [green-composition-r5.log](preuves/r19-proofs--green-composition-r5-log-89e2c6d118.gz)
- [green-composition-r5.xml](preuves/r19-proofs--green-composition-r5-xml-346d3eb37d.gz)
- [green-composition-r6-resultat.json](preuves/r19-proofs--green-composition-r6-resultat-json-f5907d0df1.gz)
- [green-composition-r6.log](preuves/r19-proofs--green-composition-r6-log-7d02b4ecc6.gz)
- [green-composition-r6.xml](preuves/r19-proofs--green-composition-r6-xml-73d978cbfe.gz)
- [composition-importable-r1.json](preuves/r19-opsys-m74a-growth-console-root-r1-2026-10-01--composition-importable-r1-json-610050d5cd.gz)
- [expected-preimages.json](preuves/r19-opsys-m74a-growth-console-root-r1-2026-10-01--expected-preimages-json-a1827b33ab.gz)
- [lint-initial-r2.json](preuves/r19-opsys-m74a-growth-console-root-r1-2026-10-01--lint-initial-r2-json-5020096992.gz)
- [ui-candidate-frozen-r3.json](preuves/r19-opsys-m74a-growth-console-root-r1-2026-10-01--ui-candidate-frozen-r3-json-57615afe7f.gz)
- [run_composition_root.py](preuves/r19-opsys-m74a-growth-console-root-r1-2026-10-01--run-composition-root-py-2479120d6b.gz)
- [resultat.json](preuves/r19-m74a-integration-root-r6--resultat-json-1909dc8172.gz)
- [preparation.json](preuves/r19-m74a-integration-root-r6--preparation-json-cd0a0ef82e.gz)
- [m74a-marketing-console-integres-root-r1-2026-10-01-avant.json](preuves/r19-preuves--m74a-marketing-console-integres-root-r1-2026-10-01-avant-json-47be570308.gz)
- [m74a-marketing-console-integres-root-r1-2026-10-01-apres.json](preuves/r19-preuves--m74a-marketing-console-integres-root-r1-2026-10-01-apres-json-1f76d8667b.gz)
- [m74a-marketing-console-integres-root-r1-2026-10-01-resultat.json](preuves/r19-preuves--m74a-marketing-console-integres-root-r1-2026-10-01-resultat-json-39d3b4870b.gz)
- [m74a-marketing-console-integres-root-r1-2026-10-01.log](preuves/r19-preuves--m74a-marketing-console-integres-root-r1-2026-10-01-log-8c7e9f181c.gz)
- [m74a-marketing-console-integres-root-r1-2026-10-01.xml](preuves/r19-preuves--m74a-marketing-console-integres-root-r1-2026-10-01-xml-c8db58b5f3.gz)
- [m74a-ruff-root-r1-2026-10-01-avant.json](preuves/r19-preuves--m74a-ruff-root-r1-2026-10-01-avant-json-3f03230243.gz)
- [m74a-ruff-root-r1-2026-10-01-apres.json](preuves/r19-preuves--m74a-ruff-root-r1-2026-10-01-apres-json-ca54b2c2b5.gz)
- [m74a-ruff-root-r1-2026-10-01-resultat.json](preuves/r19-preuves--m74a-ruff-root-r1-2026-10-01-resultat-json-3fb7557c96.gz)
- [m74a-verifier-root-r1-2026-10-01-avant.json](preuves/r19-preuves--m74a-verifier-root-r1-2026-10-01-avant-json-b70f03a60b.gz)
- [m74a-verifier-root-r1-2026-10-01-apres.json](preuves/r19-preuves--m74a-verifier-root-r1-2026-10-01-apres-json-6c973bce07.gz)
- [m74a-verifier-root-r1-2026-10-01-resultat.json](preuves/r19-preuves--m74a-verifier-root-r1-2026-10-01-resultat-json-032e699528.gz)
- [append-r18-receipt.json](preuves/r19-r20-append-r18-root-capture--append-r18-receipt-json-ce33338240.gz)
- [documents-integres-verifies-r2.json](preuves/r19-programme-r18-revue-root-r3--documents-integres-verifies-r2-json-36913a364b.gz)
- [archives-verifiees.json](preuves/r19-programme-r18-revue-root-r3--archives-verifiees-json-d8a0457ec3.gz)
- [append-r18-root-execute-only-root-r3.py](preuves/r19-programme-r18-final-root-r1--append-r18-root-execute-only-root-r3-py-8bf7092732.gz)
- [append-root-r3.log](preuves/r19-programme-r18-final-root-r1--append-root-r3-log-0456673c7c.gz)
- [rapport.md](preuves/r19-growth-audit-r1-2026-10-01--rapport-md-3524c49cd1.gz)
- [sources.json](preuves/r19-growth-audit-r1-2026-10-01--sources-json-d10061a394.gz)
- [rapport.md](preuves/r19-growth-revue-statique-core-r1-2026-10-01--rapport-md-7b4f104582.gz)
- [sources-et-preuves.json](preuves/r19-growth-revue-statique-core-r1-2026-10-01--sources-et-preuves-json-b3441b534c.gz)
- [rapport.json](preuves/r19-m74a-cloture-independante-r1--rapport-json-190e148f67.gz)
- [growth-human-entry-audit-r1-2026-10-01.md](preuves/r19-restructuration-opsys-2026-10-01--growth-human-entry-audit-r1-2026-10-01-md-4cf7c50cfa.gz)
- [manifest-docs-root-r2.json](preuves/r19-programme-r19-final-root-r1--manifest-docs-root-r2-json-07496daf03.gz)
- [expected-paths-root-r2.json](preuves/r19-programme-r19-final-root-r1--expected-paths-root-r2-json-6781b1f158.gz)
- [docs-r19-root-r2.diff](preuves/r19-programme-r19-final-root-r1--docs-r19-root-r2-diff-3bc5585a9a.gz)
- [links-review-root-r2.json](preuves/r19-programme-r19-final-root-r1--links-review-root-r2-json-2b3fa36b19.gz)
- [manifest-final.json](preuves/r19-opsys-m74a-growth-docs-r19-r1-2026-10-01--manifest-final-json-8bce33ba2c.gz)
- [lecture-cloture-docs-r1.json](preuves/r19-opsys-m74a-growth-docs-r19-r1-2026-10-01--lecture-cloture-docs-r1-json-fc2eb7e4f4.gz)
- [growth_lecture.py](preuves/r19-m7-marketing--growth-lecture-py-4f2f1df0d1.gz)
- [test_growth_lecture.py](preuves/r19-tests--test-growth-lecture-py-06155aaa23.gz)
- [test_console_growth.py](preuves/r19-tests--test-console-growth-py-72d359215b.gz)
- [M7-4A-GROWTH-LECTURE.md](preuves/r19-docs--m7-4a-growth-lecture-md-3205c4c6c5.gz)
- [M7-AUDIT-INITIAL.md](preuves/r19-marketing--m7-audit-initial-md-b85b9186f8.gz)
- [M7-MATRICE-CAPACITES-2026-09-30.md](preuves/r19-marketing--m7-matrice-capacites-2026-09-30-md-4dcf4ae490.gz)
- [BILAN-RESTRUCTURATION-2026-09-30.md](preuves/r19-programme--bilan-restructuration-2026-09-30-md-9fac58fd73.gz)
- [RESTRUCTURATION-2026-09-30.md](preuves/r19-programme--restructuration-2026-09-30-md-bbb27f08c7.gz)
- [docs-r19.diff](preuves/r19-append-packet-donnees-r1--docs-r19-diff-1d181a1558.gz)
