# Publication et corrections de CI — 4 octobre 2026

Les résultats récents du head `b005c4e6`, le diagnostic des 79 échecs du socle
et son correctif qualifié sont dans [Socle : contrats et mutations M7](SOCLE-CONTRATS-M7.md).
Les observations historiques ci-dessous restent rattachées à leurs commits.

La reprise suivante identifie le refus AppArmor du runner PDF et qualifie
une exception ciblée par binaire : [diagnostic et correctif](PDF-RUNNER-UBUNTU.md).
Les résultats natifs du head `e7f96d3` y sont distingués de la validation
du prochain head, encore à obtenir.

La reprise est publiée dans la [PR privée #623](https://github.com/leon36000/OPSYS-AI/pull/623),
branche `codex/restructuration-2026-09-30`, sur la base de Claude
`claude/opsys-ai-analysis-x4jt87`. Aucun merge de `main`, déploiement ni action métier externe.
Le premier commit publié est `4a3759753dd7e34333bb5e9b925489f98edc4d8d` ; son arbre
`04ef17df29b897bff87124dd74e5573ff9b1e9e5` est identique à l'instantané local vérifié.
Le transfert Git natif a reçu HTTP 401 ; la publication a utilisé les objets Git de l'API,
avec vérification de l'arbre, création d'une nouvelle branche et sans force-push.

## Ce que la première CI prouve

- Construction complète du core réussie : [job 111322246369](https://github.com/leon36000/OPSYS-AI/actions/runs/37163712515/job/111322246369).
- M1, M2, M6, M7, M8, M9 et les huit partitions de gardes M3 consultées réussissent.
  Les autres partitions M3 ne sont pas assimilées à un résultat acquis.
- Cinq des six partitions unitaires du core réussissent. La sixième refuse la directive
  Dockerfile qui imposait le téléchargement d'un frontend extérieur.
- L'audit général des dépendances réussit ; l'audit npm mobile échoue. Ces deux résultats
  concernent des graphes différents.
- Les workflows dans leur ensemble ne sont pas verts : installation, socle, M3/M4/M5/M10 et
  E2E signalent les défauts détaillés ci-dessous. Une construction réussie ne vaut pas une
  qualification intégrale du produit.

## Correctif consécutif à ces résultats

1. Les installations Python du workflow core partent de `github.workspace`, où se trouve
   `pyproject.toml`. Les trois installateurs testent avec l'interpréteur géré par `uv`, y
   compris dans l'étape qui vient de l'installer.
2. Le script shell consomme sa liste d'extras centrale ; les extras ingestion/PDF/embeddings
   restent optionnels. Les tests Docker vérifient les deux choix de verrou et les hashes.
3. Le verrou runtime est réexporté depuis le `uv.lock` existant avec les extras exacts de CI.
   Aucune mise à jour de résolution ni dépendance supplémentaire dans ce correctif.
4. Le parcours E2E utilise `/mcp/v1/<département>` comme le serveur et la configuration.
5. Le test API M10 charge explicitement le double PostgreSQL canonique. Cela corrige la
   collecte isolée du département sans recopier une infrastructure PostgreSQL.
6. Le test de persistance M3 lance deux interpréteurs neufs dans un répertoire temporaire
   unique. Il exécute un calcul de prix réel et vérifie la reprise exacte du reçu durable,
   sa commande, ses sources, son environnement et son intégrité. Les gardes de corruption
   et les campagnes complètes de mutations restent distinctes et conservées.
7. M5 utilise l'horloge centrale et le nonce de demande N4 approuvée pour les coûts marketing.
   L'arrondi monétaire est explicite. Les contrôles génériques ne sont pas assouplis ; un test
   HTTP lie l'identifiant produit à la demande approuvée et conserve les refus/rejeux.
8. La directive frontend du Dockerfile du core est retirée conformément à son test existant.
   Le workflow ajoute le profil mémoire vocal natif après une construction fraîche ; son
   résultat est à obtenir sur le nouveau commit, pas présumé.

## Vérifications ROOT du correctif

| Campagne | Résultat | Portée |
|---|---|---|
| `qa-r3` | 162 réussis, 1 ignoré | Cinq fichiers entiers : installation, répétition E2E, extras et modes Docker PDF. Le cas ignoré manque d'actionlint ; le reçu brut ne combinait pas `junit.ok`, un verdict séparé corrige explicitement cette interprétation. |
| `qa-r4` | 238 réussis, aucun ignoré | Sept fichiers entiers M4/M5, dont conformité, absence de décaissement, autorité N4, sources et rejeu. Ruff réussit. |
| `qa-r4` collecte | 978 cas collectés | Département M10 entier : import corrigé. Les tests PostgreSQL ne sont pas exécutés dans cette campagne. |
| `qa-r5` | Non qualifié | Contrôle natif Dockerfile core interrompu par le plancher de mémoire local avant résultat. Aucun succès déduit. |
| `qa-r7` | 55 réussis, aucun ignoré | Persistance M3, gardes du registre de campagnes et workflow installateur complets. Actionlint officiel v1.7.7 vérifié par SHA256 valide aussi les deux workflows modifiés. |

Les anciennes campagnes rouges (`qa-r1`, `qa-r2`, `qa-r5`, `qa-r6`) sont conservées avec leurs
reprises. Les sources restent identiques pendant chaque campagne ; les compteurs OOM restent
`10/3/0`, sans nouveau OOM ni processus de test survivant. Les ensembles se recouvrent : leurs
comptes ne représentent pas un nombre global de fonctionnalités ni la couverture du dépôt.
Les reçus, logs, JUnit et empreintes sont dans [l'archive de preuves](preuves/ARCHIVE.tar.gz),
avec [inventaire vérifiable](preuves/INVENTAIRE.json).

Le scan Gitleaks 8.30.1 des fichiers du correctif conserve une alerte brute : le littéral
API_KEY d'un test de refus HTTP M10, identique à celui du premier commit publié. Le rapport
expurgé et sa classification sont conservés ; aucune règle ni baseline n'est modifiée, et
ce résultat n'est pas annoncé comme un scan brut sans alerte.

## Limites et suite obligatoire

L'audit mobile du premier commit signale notamment `braces` (GHSA-vfj7-8cjw-p6xm) et
`node-forge` (GHSA-86w9-cpqp-85rv). Au moment de la recherche, il n'existe pas de publication
stable compatible vérifiée qui corrige ces deux chemins Expo/Metro :
[braces #70](https://github.com/micromatch/braces/issues/70),
[forge #1152](https://github.com/digitalbazaar/forge/pull/1152).
Ni `npm audit fix --force`, ni version de développement imposée, ni réduction du seuil d'audit.
Le gate mobile demeure rouge et bloque une promotion globale.

La nouvelle CI doit encore confirmer les installateurs réels, PostgreSQL, le Gateway construit,
la suite core complète et le profil vocal. Le manque de disque local empêche une nouvelle image
PostgreSQL et une construction complète locale ; les résultats GitHub servent de preuve dans
leur périmètre exact. Aucun module ni OPSYS-AI dans son ensemble n'est déclaré terminé.

## Résultats du second commit et reprise Windows

Le second commit publié est `df76940ff3fce10670f4e195a7228a89ca5e4028`, arbre
`78ce4a9bb431e2e0d01af2480ab82956ca5008e0`, vérifié identique à l'index de qualification.
Sa CI confirme la construction du core, le profil mémoire vocal natif après cette
construction et les six partitions unitaires. L'analyse de l'installateur, son job macOS
et l'audit général des dépendances réussissent aussi. Cela requalifie le défaut Dockerfile
de la première CI ; l'interruption locale `qa-r5` reste conservée comme telle.

Le job Windows révèle quatorze échecs de portabilité. Le [correctif Windows](WINDOWS-ACL.md)
ajoute des assertions d'ACL natives et passe 113 cas locaux sous Linux ; Windows reste à
confirmer sur le nouveau commit. Le job supplémentaire `tests-opsys` et le parcours E2E
échouent encore ; le gate mobile reste rouge. Les observations précédentes de ce document
décrivent leurs commits respectifs et ne sont pas transformées en succès global.

Le troisième commit `c6422b1ece5b7b0c77c1d759cb58e5ec96dcfa8c`, arbre
`86bbd64652b7a355fa332537ae7b0254974f599d`, est publié et vérifié. Sa CI Windows démontre
une conservation d'ACE explicites étrangères par le helper de production. Le
[durcissement Windows/MCP](DURCISSEMENT-WINDOWS-MCP.md) corrige ce helper, le refus des
lectures authentifiées et les tests Linux qui retrouvaient le vrai Docker du runner.
Ses preuves locales ne remplacent pas la nouvelle CI native.

## Reprise mobile avec copies maintenues — 4 octobre 2026

La [qualification des dépendances mobile](MOBILE-DEPENDANCES-FORKS.md) traite
les deux chemins sans release stable corrigée, avec des identités privées et des
correctifs amont sous licence. Les résultats rouges historiques ci-dessus demeurent
rattachés à leurs commits. Après installation normale sous Node 22 : TypeScript,
17 tests de consommateurs et 2 607 tests Jest passent localement; audit npm
zéro high/critical, 13 moderate, seuil inchangé. Le prochain résultat natif reste
à obtenir. La même capsule conserve 23 tests PostgreSQL/mémoire réussis en réel.

## Résultats natifs confirmés après la reprise mobile

Le commit mobile publié est `d2669faac3f423dca336e34382eab1b758863ad3`,
arbre `f9f1bd2eab4a3bd03720cb9901d105130a70b110`, quatorzième commit.
Son [workflow mobile](https://github.com/leon36000/OPSYS-AI/actions/runs/37189707458)
réussit : audit sans high/critical (13 moderate), installation normale,
17 régressions des consommateurs, TypeScript et 2 607 tests Jest dans 118 suites.

Le [socle du head précédent d943c5d](https://github.com/leon36000/OPSYS-AI/actions/runs/37187354743)
réussit aussi : prévol PDF, 3 773 tests réussis, 17 ignorés et un warning en
41 min 59 s. Les dix départements et neuf partitions M3 de ce head réussissent.
Ces exclusions natives restent explicites; aucun verdict de zéro ignoré global.
Les [logs et reçus distants](preuves/CI-NATIVE-d2669fa-r1.tar.xz) sont conservés
avec leur [inventaire](preuves/CI-NATIVE-d2669fa-r1.json).
Les autres workflows du nouveau head poursuivent leur exécution; ces résultats
ne certifient pas tous les parcours fonctionnels de la vision produit.

## Tranche suivante — imports internes M10 reprenables

Le [rapport M10](../../grs/memory/M10-IMPORT-LOTS-REPRISE-2026-10-04.md) décrit
le manifeste PostgreSQL, les emplacements stables et les réponses partielles privées.
ROOT r106 passe **82/82 cas, zéro skip**, avec Ruff vert, 1 224 sources stables,
aucune garde déclenchée et aucun OOM; Gitleaks r107 trouve zéro alerte.
L'oubli générique, la rétention et l'ordre des verrous ont leurs régressions PostgreSQL
réelles, conservées en rouge r105 puis vert r106. Les tests antérieurs ne sont pas
additionnés pour présenter un nombre de cas uniques artificiel.

Capsule [M10-IMPORT-LOTS-r1.tar.xz](preuves/M10-IMPORT-LOTS-r1.tar.xz),
SHA-256 `e6cbe872089339e686871946869d03020dc1b8eb9f60b599a0b4df878bfde42b`,
[inventaire](preuves/M10-IMPORT-LOTS-r1.json) et
[versions exactes de l'environnement](preuves/M10-IMPORT-LOTS-ENV-r1.json).
La CI native de cette nouvelle tranche reste à obtenir sur son commit publié.
**PARTIEL** : procédures internes M03; ni import client universel, ni OCR/PDF,
ni assimilation sur corpus d'entreprise réel, ni entraînement automatique.
