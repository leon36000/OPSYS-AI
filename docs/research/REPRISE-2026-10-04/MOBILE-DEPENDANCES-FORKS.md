# Mobile : dépendances adaptées et qualifiées — 4 octobre 2026

## Décision et périmètre

Les audits natifs de la PR #623 échouaient sur deux chemins du tooling Expo/Metro :
`braces` 3.0.3 (GHSA-vfj7-8cjw-p6xm) et `node-forge` 1.4.0
(GHSA-86w9-cpqp-85rv). Aucune release npm stable corrigée n’était disponible lors
de cette reprise. OPSYS reprend des correctifs amont inspectés, sous leurs licences,
avec deux copies privées explicitement maintenues dans `mobile/vendor/`.
Le seuil `npm audit --audit-level=high` reste en vigueur. Aucun `audit fix --force`,
aucun changement du SDK Expo, aucune fausse version officielle corrigée.

La publication cible exclusivement la branche de travail et la PR privée
[#623](https://github.com/leon36000/OPSYS-AI/pull/623). Le résultat natif du
nouveau commit reste à obtenir. Cette livraison ne termine ni le mobile ni OPSYS-AI.

## Sources et adaptation

| Copie OPSYS | Source inspectée | Licence et adaptation |
|---|---|---|
| `@opsys-ai/braces` `3.0.3-opsys.1` | [PR #72](https://github.com/micromatch/braces/pull/72), commit `28d440b5dd449dbf1fe6f3506cf94ecca4d02660`, base `e53730e6f935498326c72d768889ac194eedc0e0` | MIT, avis conservé. Profondeur maximale de 100 dans parse/compile/expand/stringify, options invalides ne désactivant pas la limite, chaînes de parents cycliques refusées. |
| `@opsys-ai/node-forge` `1.4.0-opsys.1` | [PR #1152](https://github.com/digitalbazaar/forge/pull/1152), commit `ceba34402e329f0365134f23fe19898756527d65`, parent `7a43db987bd0ecdc5b41f6d73f58ba6ca5bf9ae1` | BSD-3-Clause choisie dans la licence duale et avis conservés. Cinq lignes de contrôle dans `lib/rsa.js` sur le nombre d’éléments ASN.1 du DigestAlgorithm; les règles OID/NULL existantes sont préservées. |

La base Git de `braces` comporte deux corrections de parseur absentes du paquet npm
3.0.3 : remise à zéro du marqueur invalid à la virgule (`9a446a8`) et guillemet
sans fermeture traité comme texte (`ac60bdb`). La pile de la PR applique également les limites fractionnaires maxDepth et
préserve le stringify des accolades imbriquées valides. Ces deux corrections de base sont également
incluses et tracées; les 42 échecs observés sans elles étaient déjà présents dans
la comparaison canonique npm/base. Aucun test ni assertion n’a été retiré pour les éviter.

`node-forge` reprend le runtime npm 1.4.0, avec le seul correctif RSA ciblé,
pas l’ensemble du master non publié. Les anciens bundles minifiés et Flash ne sont
pas redistribués. Les dépendances et scripts de développement amont ne sont pas
importés. Le fichier [PROVENANCE](../../../mobile/vendor/PROVENANCE.json) précise
les identités, licences, limites, sources et SHA256 de tous les fichiers distribués.

## Intégration vérifiable

Les dépendances locales directes de développement `file:./vendor/braces` et
`file:./vendor/node-forge` sont utilisées par les overrides npm `$braces` et
`$node-forge`. Le verrou comporte deux liens vers ces copies, sans autre changement
de version, d’URL resolved ou d’intégrité des paquets existants. Des overrides de
fichiers seuls avaient produit des chemins imbriqués incohérents : cette approche
n’est pas retenue.

`npm run test:dependencies` vérifie la résolution réelle depuis `micromatch`,
`@expo/code-signing-certificates` et `@expo/cli`, puis les empreintes du runtime,
les options de profondeur malformées, les cycles, les patterns Metro courants,
le vecteur public RSA malformé et une signature SHA256 valide via le consommateur
Expo. Les clés privées du dernier test sont générées en mémoire, sans stockage.
Ce contrôle est ajouté au workflow mobile après l’installation et avant TypeScript/Jest.

## Qualification ROOT conservée

Node **22.23.3**, npm **10.9.9**, archive officielle vérifiée par SHA256, comme le
runner mobile observé. Installation fraîche en RAM, environnement limité,
processus, mémoire, durée et logs bornés; sources gelées et aucun nouveau OOM.

| Campagne | Résultat | Portée |
|---|---|---|
| `qa-r72` / `qa-r73` | Régression rouge sur l’original puis verte sur la copie | Rejet du DigestAlgorithm RSA malformé. |
| `qa-r87` | 829 réussis, 4 pending amont, zéro échec | 833 tests du corpus Forge, exécutés avec `--forbid-only`. |
| `qa-r88` | 940 réussis, aucun pending | 904 cas du corpus braces et 36 contrôles adversariaux supplémentaires. |
| `qa-r84` | Réussi | Verrou actualisé, aucune autre dépendance modifiée. |
| `qa-r85` | Zéro high/critical, 13 moderate | Audit npm du graphe verrouillé avec son seuil initial. |
| `qa-r93` | Réussi | `npm ci` normal, scripts d’installation exécutés; pas seulement ignore-scripts. |
| `qa-r95` puis `qa-r99` | 17 réussis, aucun ignoré | Résolution réelle, empreintes, cas négatifs et signatures valides. |
| `qa-r96` | Réussi | TypeScript strict après installation normale. |
| `qa-r97` | 2 607 réussis, 118 suites, aucun ignoré | Toute la suite Jest mobile après installation normale. |

Le workflow modifié passe actionlint (`qa-r98`). Gitleaks conserve deux alertes
brutes sur du code public amont : un alias de fonction PKCS12 et un exemple fictif
de seed ED25519 dans le README. Elles sont classifiées avec lignes et empreintes;
aucune règle ni baseline modifiée. Ce scan n’est pas annoncé sans alerte.

Le corpus Forge contenait un `describe.only`, qui faisait exécuter cinq tests
seulement. Ce modificateur exclusif a été retiré uniquement de la copie de QA,
sans changer les assertions, puis `--forbid-only` imposé. Les quatre pending
préexistants restent documentés. Les verdicts incomplets de découverte, les sorties
rouges de comparaison, les interruptions par budget mémoire 512 MiB et l’appel
initial erroné de l’API de test Expo sont conservés, pas transformés en succès.
Les reprises TypeScript et installation normales ont un budget explicite de
1 GiB; les gardes de temps, empreintes et OOM restent actives.

Les [preuves archivées](preuves/MOBILE-DEPENDANCES-r1.tar.xz) et leur
[inventaire](preuves/MOBILE-DEPENDANCES-r1.json) relient reçus, sources, logs,
comparaisons et corrections. Les comptes ne s’additionnent pas en une couverture
fonctionnelle globale du produit.

## Limites et maintenance

Un paquet privé renommé n’est pas connu du catalogue d’advisories npm.
L’audit vert ne certifie donc pas la sécurité cryptographique du fork : sa
qualification repose aussi sur la revue du code, les régressions et sa provenance.
Les 13 alertes modérées restent ouvertes. La limite de profondeur de braces ne
borne pas globalement le produit cartésien d’une expansion. Les corpus amont ne
constituent pas un audit cryptographique exhaustif ni une preuve iOS/Android réelle.

OPSYS assume la maintenance de ces copies. À chaque changement : vérifier les
empreintes, exécuter les consommateurs réels et les tests négatifs, réévaluer les
advisories et les correctifs amont. Une release officielle ultérieure doit être
inspectée et comparée avant remplacement; aucune synchronisation automatique.

## Mémoire d’entreprise et CI du socle

La campagne indépendante `qa-r71` exécute **23 tests** complets de
`test_memoire_autorite_postgres.py` et `test_memoire_outils.py` sur PostgreSQL 17
avec pgvector réel, aucun ignoré. L’image déjà disponible est utilisée sans pull;
les conteneurs temporaires sont supprimés par la fixture. Ses preuves sont
conservées dans la même capsule, sans prétendre livrer l’assimilation massive.

Sur le head précédent `d943c5d`, le prévol PDF natif Ubuntu réussit avec le
profil AppArmor ciblé. Les dix départements réussissent; la suite complète du
socle et une partition M3 sont encore en cours au moment de cette qualification.
Ces résultats concernent ce head, pas le prochain commit mobile.
