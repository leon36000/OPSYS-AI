# Audit de reprise OPSYS-AI sur l'infrastructure — 6 octobre 2026, Toronto

Observation : 2026-10-06T04:54:57.683714-04:00. OPSYS-AI reste **PARTIEL**. Ce rapport qualifie la reprise et des raccords précis; il ne certifie pas les dix départements complets.

## Conservation et jonction Git

Clone isolé de la branche privée `codex/restructuration-2026-09-30`, base réelle `3f38364284a917239441b86b14e948dbdbaaac6f`, PR #623 en brouillon. Authentification locale de leon36000 obtenue par navigateur/keyring. Aucun checkout utilisateur recouvert, commit synthétique de transport importé, force-push, fusion ou déploiement.

Le vérificateur natif confirme **426 fichiers**. Rapprochement avant écriture : **302 sources**, **42 identiques**, **118 préimages conformes**, **142 nouveaux fichiers**, aucun conflit. Les 124 fichiers supports restent conservés dans le pack local. Les **104 preuves omises** sont toutes répertoriées avec tailles/SHA et restent absentes; elles ne sont pas annoncées réexécutées. Les nouveaux essais sont une autre campagne, avec leurs sources, logs, résultats et limites.

[Registre exhaustif](REGISTRE-REPRISE-2026-10-06.json) : chaque source, empreinte avant/transport/finale, disposition, suppléments de qualification et inventaire des preuves locales. Le bilan initial ci-dessous précède les corrections de CI. Le suivi daté retrace les passages à 25, 26, 27 puis 28 suppléments ; le bilan courant porte sur 295/302 sources identiques au transport et sept adaptations explicites. Ce reçu ne prétend pas reconstituer l'arbre complet du pack optionnel.

## Qualification fraîche

| Surface | Résultat direct | Portée et limite |
|---|---|---|
| Console M3 r392 reprise | 225 tests dans 7 fichiers complets, r392-r1 | ASGI/TestClient et SQLite fictif, aucune calibration activée |
| Python impacté + E2E | 1132 réussis / 27 ignorés, 62 fichiers, impactes-python-r2 | 26 PostgreSQL refusés faute Docker; 1 intégration Docker opt-in |
| Mobile | 2693 tests / 123 suites, mobile-jest-r3; types stricts et 17 contrôles dépendances verts | Node 24 ARM64 local; appareils réels et CI Node 22 distincts |
| Core POSTFLIGHT/admission/CLI | 305 tests / 16 fichiers complets / 7 partitions, core-tests-r3 | Routage canonique sans forcer globalement pool; source/tickets de certains E2E synthétiques |
| Cron/retrait/provenance | 270 tests / 6 fichiers, cron-behavior-r5; fichier retirement final 11/11 | ACK, perte de réponse, suppression, refus/révocation et preuve chiffrée fictifs |
| Routage broker hôte | Régression 5/5, routing-final-r1 | Sélection nommée;1540 cas tooling non sélectionnés, pas suite entière verte |
| Types et schémas | tsgo:core vert; db:kysely:check vert après générateur canonique | Déclaration state absente du pack régénérée; schémas métier inchangés |
| Build Core complet | exit0, core-build-r2,247,254 s, somme RSS arbre pic de 11 234 791 424 octets | Sources inchangées; inclut bibliothèque/SDK/UI, pas installation VPS |
| Lint | Ruff socle+7départements; Oxlint des composants de fermeture vert | Warning longueur worker : 1041 lignes pour une limite de 700 conservé; pas lint global du dépôt |

Les campagnes se recouvrent : leurs nombres ne s'additionnent pas. Logs/reçus sous `work/qualification` local et [capsule de cette reprise](PREUVES-REPRISE-2026-10-06-r1.tar.xz), aussi disponible localement, SHA256 `3cc62e5ad8f48101234475895dea348c0499de129c336e31af3afdb8c1afe797`. Aucun secret/profil personnel ou dépendance installée inclus dans cette capsule. Tous les rouges sont conservés. Certaines premières horloges de wrapper portent l'heure de fin dans `started_utc`; les durées mesurées sont conservées et les reçus suivants distinguent début/fin. Le JUnit rouge r1 a été préservé avant réutilisation involontaire du nom par le helper, puis le résultat r2 renommé distinctement; aucune preuve perdue.

## Corrections qualifiées

- Corrections du transport revalidées : compteurs ROLES depuis 217 outils / 125 portées, image PostgreSQL préparée explicitement dans la CI M10.
- Déclaration SQLite state régénérée depuis schéma canonique, sans substitution du supplément absent. Types Core durcis sans cast artificiel : réserve/délai invalide refusé, littéraux d'autorité exacts, créateur cron désactivé avant ACK, guards vivants répétés après attente.
- Deux tests consommateurs du broker SQLite classés dans leur pool hôte canonique. Régression rouge avant correction, puis verte, sans supprimer le garde du runtime.
- Préimage cron normalisée des deux côtés : le transport `structuredClone` ne bloque plus une preuve identique; absence, divergence, révision et révocation restent refusées. Fixtures corrigées pour relire le job canonique après wrapper d'ajout et filtrer les reçus par partition complète. Refus DELETE vérifié par erreur fermée nom/code/message; rollback conservé.
- OCR : modes explicites0700/0600 des fixtures, production inchangée. Vendeur : contrats de liste/détail distingués, propriété et catalogues exacts maintenus. Admin : facture E existante envoyée par outil M5 canonique sur données fictives avant observation définitive, facture A brouillon toujours non calculable; JSON mobile issu du vrai moteur, revalidé sans régénération.
- Doc ROLES dédupliquée : la réponse serveur vendeur contient la projection interne; la whitelist mobile retire coûts/marges avant affichage/cache. Aucune confidentialité serveur supplémentaire revendiquée. BOUCLE alignée sur permission réelle de tester/construire Core localement.

Revue indépendante GPT-6 Astra, lecture seule et passes ciblées : aucune nouvelle faille runtime confirmée, deux findings sur assertions partitionnées et promesse documentaire, corrigés et revérifiés. Cela reste une revue bornée, pas une certification exhaustive.

## Limites et ressources actuelles

Machine ARM64, Python 3.12.3, Node 24.16.0, pnpm 12.4.0, uv 0.12.19 installés seulement dans l'espace de travail. Aucun renouvellement général des dépendances produit ; le correctif ciblé du verrou mobile est décrit dans le suivi ci-dessous. Docker local refuse l'accès à la socket; aucun chmod global/groupe/sudo de contournement. LiteLLM/PC1, fournisseurs et modèles réellement configurés non établis ici : aucun hôte, credential ou endpoint inventé.

Le build rapporte **startup JavaScript 371 592 octets > 371 332 octets** et une alerte CSS proche du plafond; exit0 ne vaut pas gate performance verte. La suite tooling amont entière révèle 34 échecs sur surfaces privées/élaguées; sa régression de routage est vérifiée séparément, aucun test ignoré ajouté pour la rendre verte. Ces dettes restent ouvertes.

CI du nouveau commit à observer séparément; aucun succès du parent réattribué. PostgreSQL M3, restitution navigateur/TLS, fournisseur vocal réel, OCR/corpus client, précision/calibration indépendante, paie/fiscalité officielles, avatar audiovisuel complet et restauration VPS restent non qualifiés. Une intention incertaine n'est ni purgée ni rejouée; ACK M10 ne certifie pas exactement-une-fois métier. Aucun rapprochement humain des intentions livré par cette reprise.

## File de lots reprise

Les fenêtres H0/H24 du 5 octobre sont historiques ; elles ne désignent aucune exécution permanente. Reprise après intégration/CI :

1. **Verticale unique M7→M1→M2→M3→M4/M6→M5→M8/M9/M10** : composer les entrées/outils propriétaires existants sur une même affaire/lead/devis/WCT, quatre profils, reprise et absence d'effets doublés. Les E2E actuels qualifient des sous-parcours, pas encore l'ensemble unique.
2. **Exploitation** : PostgreSQL autorisé isolé, restauration indépendante, diagnostic/reconciliation sourcée des intentions, budgetUI et tooling hérités. Garder export/brouillon fonctionnel lorsqu'un fournisseur manque.
3. **Capacités profondes** : mémoire affaires/développement isolée et ingestion durable évaluée; réception réelle; CFO/paie/fiscalité préparatoires sourcées; CMO/canaux/ROI; mesure/calibrationM3 indépendante. RechercheGitHub/GitLab et licences avant capacité majeure, sans empilement de frameworks.
4. **Surfaces utilisateurs** : dashboard agents/modèles/outils/droits/secretrefs/coûts, mobile quatre profils hors ligne, texte/audio/avatar3D avec identité et permissions communes. Résultats/coûts/latence mesurés, aucun gain inventé.

Le Core OpenClaw, CRM, comptabilité, bus/outbox et ambitions des dix départements sont conservés. Donnée manquante=inconnue/refus nommé. Argent réel, déclarations, engagements, achats/publications sensibles et suppressions définitives gardent leurs validations humaines. Conversations absentes et mémoire personnelle du modèle ne sont pas déclarées archivées.

## Suivi de la première CI de reprise — 2026-10-06T05:12:10.680562-04:00

Le commit d'intégration `44e388245253b6697391002415b2d0212b1e60cb` est publié sans force. Sa première CI révèle deux causes corrigibles : verrou mobile `source-map-js1.2.1`, et catalogue historique M3 resté à13 outils avant les3 lectures transportées. Les résultats de ce parent demeurent séparés; le nouveau commit de correction exige sa propre CI.

- Mobile : correctif amont `source-map-js1.2.2` ([avis GitHub](https://github.com/advisories/GHSA-68fv-2mgg-jv7q)), seule entrée du verrou changée (version/URL/intégrité). Audit au seuilhigh passé de1 alerte élevée à 0,35 alertes modérées conservées, aucun seuil/exclusion abaissé; npmci puis2693tests/123suites, types et17régressions verts.
- M3 : ensemble exact du catalogue conservé, trois lectures explicitement nommées et contraintes àT0; aucune nouvelle mutation pour les scénarios. Rouge local1F/26P conservé; fichiers scénarios/preuves verts33/33, batterie de référence et captures réelles avant/après incluses. Département2240P/9S hors deux batteries réparties séparément dans la CI; aucun skip ajouté.
- CI Core :12 tests transportés et5 voisins cron ajoutés à la liste explicite,183 cibles sans doublon; vérification rouge17absents puis verte. Les suites locales305Core/270cron qualifient déjà ces fichiers via le même lanceur canonique; les runners restent une preuve séparée.
- PostgreSQL : jobM10 du parent réussi après téléchargement explicite `pgvector/pgvector:pg17`. Cela ne qualifie pas les testsPostgreSQL M3, les appareils réels ou une restauration VPS.

[Capsule de suivi](PREUVES-REPRISE-2026-10-06-r2.tar.xz), SHA256 `079c176e26ce9d1831fd61c487f831495b7fb22c38371d41004bbe52b03c51a5`, conserve les nouveaux reçus rouges/verts et les snapshots/journaux de la première CI. La capsule r1 reste intacte. Le registre distingue désormais25 suppléments de qualification. [File verticale et critères de jonction](CONTINUITE-VERTICALE-2026-10-06.md) : sous-parcours actuels distincts d'un scénario unique non livré. OPSYS-AI reste **PARTIEL**.

## Reçu canonique du voisin fallback — 2026-10-06T05:26:41.489779-04:00

La CI Core du premier commit de reprise révèle un unique cas rouge dans les13partitions OPSYS : fixture historique `run-entry.admission.integration.test.ts` restée au reçu partiel `reservation-0001`. Reproduction locale1F/35P; la fixture retourne désormais une identité hex32 et un reçu complet lié aux vrais arguments de capture, puis la même réservation conciliée. L'assertion fournisseur unique, candidat 0 après échec avant admission et les2 appels MCP exacts sont conservés. Les guards de production restent stricts et inchangés.

Le hook `beforeEach` retournait le mock de `mockReset`; Vitest5 l'appelait comme fonction de nettoyage sans argument. Hook à retour void et suppression de l'affectationunused, setup conservé. Reprise r2 rouge et r3 verte conservées : **93/93 sur5 fichiers complets**, y compris le véritable MCP Python HTTP, sources figées; lint ciblé vert. Aucun nouveau build requis pour cette fixture seule; les octets de production restent ceux déjà qualifiés.

[Capsule r3](PREUVES-REPRISE-2026-10-06-r3.tar.xz), SHA256 `30b298ff60bc318abc9ca01d8f52d94a6de612c632363512b192eab3f2ed6ddf`, avec journal CI et reçus rouges/verts. Registre **26 suppléments**; les302 sources du transport et104 absences restent rapprochées. Le commit de correction doit obtenir sa CI applicable propre; aucun succès du parent attribué. OPSYS-AI reste **PARTIEL**.

## Budget de la qualification du socle — 2026-10-06T06:34:03.351447-04:00

Le HEAD0753f4c3 réussit les dix départements et les neuf batteries M3. Son socle est interrompu par GitHub à45minutes, pytest vers68%, aucunF visible avant interruption : annotation « maximum execution time of45m0s ». Le statut est cancelled et gates échoue correctement; aucune qualification globale verte n'est déduite de ce journal incomplet. L'ancêtre44e avait obtenu4486P/17S en40m55 surunautrerunner; ce succès n'est pas attribué au HEAD0753.

Seul le budgetwallclock du socle passe à90minutes, comme les batteriesM3, pour conserver la suite complète. Commandepytest, collecte, tests, gardes, quotas et seuils inchangés; pas de tests ignorés/désélectionnés ajoutés. ContratsCI existants :10/10, sources figées. Le choix90min offre une marge après45min/0.68≈66min (estimation, pas une mesure de durée finale). Coût : occupationrunner pluslongue, un défaut réel peut toujours faireéchouer le job.

[Capsule r4](PREUVES-REPRISE-2026-10-06-r4.tar.xz), SHA256 `315ba335c909676ad618e7db74e86da1d9a482b133150971e25f6b7049eb4e92`, conserve l'annotation, le journal interrompu, la référence et la vérificationCI locale. Le registre distingue27suppléments;295/302sources restentidentiques autransport, septmodifiées parqualification. Les104absences restenttracées. Le nouveaucommit de budget doit obtenir sespropres workflows applicables; OPSYS-AI reste **PARTIEL**.

## Chronologie déterministe des traces M6 — 2026-10-06T07:36:30.992360-04:00

Le socle du HEAD228c91ef termine en37m30, avec1échec/4485réussites/17ignorés. L'unique échec attendait Léa→Marc alorsque le lecteurcanonical `approbations.lister` rend lesplusrécentesd'abord; lesdates àla seconde faisaientparfois passerunordreaccidentel. Lescontrôles d'accès/refus/absenceécritures métier et consommationM6 étaientdéjàcorrects. Aucun défaut d'autorisation déduit de cette seule comparaison.

Fixture avecdeuxsecondes distinctes : reproduction1F/6P, puis assertionexactedeuxtraces outil/acteur/statut/date, Marc/exécutée/date1 suivi de Léa/échec/date0. Aucuntriadditionnel ni ensemble qui cacheraitdoublons/manques; aucun lecteur, droit ou guardproduction changé. **202/202 surquatre fichiers complets d'accès M4/M6 et d'approbation**, Ruffvert et sourcesfigées. NouvelleCI aucommit de correction requise.

[Capsule r5](PREUVES-REPRISE-2026-10-06-r5.tar.xz), SHA256 `5a2f93f248a438754cb64ed69e33e4e24c30a2fd411155b45405ab893b0e7754`, conservejournalCI et rouges/verts. Registre28suppléments, toujours302sources rapprochées,295identiquesautransport et104absences conservées. OPSYS-AI reste **PARTIEL**.

## Refus de reprise avant observation de santé — 2026-10-06T08:33:30.424417-04:00

Le socle du HEAD `6d34a1d5` termine avec **1 échec / 4485 réussites / 17 ignorés** en 43 min 51 s. Le Core est réussi sur ce HEAD. L'échec vient d'une assertion de fixture qui exigeait `compose ps` après `start`, alors que le budget commun peut déjà être épuisé. Le script réel refuse correctement « reprise hors délai; archives conservées », sans recréer les conteneurs ni certifier une sauvegarde complète.

Un délai imposé au retour de la commande factice reproduit ce chemin : rouge local sur le nouveau cas, puis **51 réussites sur le fichier complet / 1 intégration Docker opt-in ignorée**, sources figées. La fixture exige explicitement zéro observation après expiration avant lecture, une erreur fermée nommée, un seul start des services initiaux, aucun up, aucune PREUVE de succès et les archives conservées. Les cas santé positive et unhealthy exigent toujours une observation. Le scénario timeout admet que la limite expire avant, pendant ou après la première observation; une lecture de santé supplémentaire ne peut pas être imposée après épuisement du budget. Aucun script, timeout ou garde de production modifié. Ruff final vert; son rouge de longueur puis correction de format restent conservés.

[Capsule r6](PREUVES-REPRISE-2026-10-06-r6.tar.xz), SHA256 `96467b842c76026bfc4257c34c3d5b005a4fc7e696cc878719afda0451bbf051`. Registre **29 suppléments**, **294/302 sources identiques au transport**, huit adaptations explicites, 104 omissions toujours tracées. Le nouveau commit de fixture exige ses propres workflows applicables. OPSYS-AI reste **PARTIEL**.
