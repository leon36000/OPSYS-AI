# Audit de reprise OPSYS-AI sur l'infrastructure — 6 octobre 2026, Toronto

Observation : 2026-10-06T04:54:57.683714-04:00. OPSYS-AI reste **PARTIEL**. Ce rapport qualifie la reprise et des raccords précis; il ne certifie pas les dix départements complets.

## Conservation et jonction Git

Clone isolé de la branche privée `codex/restructuration-2026-09-30`, base réelle `3f38364284a917239441b86b14e948dbdbaaac6f`, PR #623 en brouillon. Authentification locale de leon36000 obtenue par navigateur/keyring. Aucun checkout utilisateur recouvert, commit synthétique de transport importé, force-push, fusion ou déploiement.

Le vérificateur natif confirme **426 fichiers**. Rapprochement avant écriture : **302 sources**, **42 identiques**, **118 préimages conformes**, **142 nouveaux fichiers**, aucun conflit. Les 124 fichiers supports restent conservés dans le pack local. Les **104 preuves omises** sont toutes répertoriées avec tailles/SHA et restent absentes; elles ne sont pas annoncées réexécutées. Les nouveaux essais sont une autre campagne, avec leurs sources, logs, résultats et limites.

[Registre exhaustif](REGISTRE-REPRISE-INFRA-2026-10-06.json) : chaque source, empreinte avant/transport/finale, disposition, suppléments de qualification et inventaire des preuves locales. 296/302 sources demeurent identiques au transport; les autres modifications ainsi que les 22 chemins de suppléments sont distingués explicitement. Ce reçu ne prétend pas reconstituer l'arbre complet du pack optionnel.

## Qualification fraîche

| Surface | Résultat direct | Portée et limite |
|---|---|---|
| Console M3 r392 reprise | 225 tests dans 7 fichiers complets, r392-r1 | ASGI/TestClient et SQLite fictif, aucune calibration activée |
| Python impacté + E2E | 1132 réussis / 27 ignorés, 62 fichiers, impactes-python-r2 | 26 PostgreSQL refusés faute Docker; 1 intégration Docker opt-in |
| Mobile | 2693 tests / 123 suites, mobile-jest-r3; types stricts et17 contrôles dépendances verts | Node24 ARM64 local; appareils réels et CI Node22 distincts |
| Core POSTFLIGHT/admission/CLI | 305 tests /16fichiers complets /7shards, core-tests-r3 | Routage canonique sans forcer globalement pool; source/tickets de certains E2E synthétiques |
| Cron/retrait/provenance | 270 tests /6fichiers, cron-behavior-r5; fichier retirement final11/11 | ACK, perte de réponse, suppression, refus/révocation et preuve chiffrée fictifs |
| Routage broker hôte | Régression5/5, routing-final-r1 | Sélection nommée;1540 cas tooling non sélectionnés, pas suite entière verte |
| Types et schémas | tsgo:core vert; db:kysely:check vert après générateur canonique | Déclaration state absente du pack régénérée; schémas métier inchangés |
| Build Core complet | exit0, core-build-r2,247.254s, somme RSS arbre pic11234791424B | Sources inchangées; inclut bibliothèque/SDK/UI, pas installation VPS |
| Lint | Ruff socle+7départements; Oxlint des composants de fermeture vert | Warning longueur worker1041lignes/700 conservé; pas lint global du dépôt |

Les campagnes se recouvrent : leurs nombres ne s'additionnent pas. Logs/reçus sous `work/qualification` local et [capsule de cette reprise](PREUVES-REPRISE-2026-10-06-r1.tar.xz), aussi disponible localement, SHA256 `3cc62e5ad8f48101234475895dea348c0499de129c336e31af3afdb8c1afe797`. Aucun secret/profil personnel ou dépendance installée inclus dans cette capsule. Tous les rouges sont conservés. Certaines premières horloges de wrapper portent l'heure de fin dans `started_utc`; les durées mesurées sont conservées et les reçus suivants distinguent début/fin. Le JUnit rouge r1 a été préservé avant réutilisation involontaire du nom par le helper, puis le résultat r2 renommé distinctement; aucune preuve perdue.

## Corrections qualifiées

- Corrections du transport revalidées : compteurs ROLES depuis217outils/125portées, image PostgreSQL préparée explicitement dans la CI M10.
- Déclaration SQLite state régénérée depuis schéma canonique, sans substitution du supplément absent. Types Core durcis sans cast artificiel : réserve/délai invalide refusé, littéraux d'autorité exacts, créateur cron désactivé avant ACK, guards vivants répétés après attente.
- Deux tests consommateurs du broker SQLite classés dans leur pool hôte canonique. Régression rouge avant correction, puis verte, sans supprimer le garde du runtime.
- Préimage cron normalisée des deux côtés : le transport `structuredClone` ne bloque plus une preuve identique; absence, divergence, révision et révocation restent refusées. Fixtures corrigées pour relire le job canonique après wrapper d'ajout et filtrer les reçus par partition complète. Refus DELETE vérifié par erreur fermée nom/code/message; rollback conservé.
- OCR : modes explicites0700/0600 des fixtures, production inchangée. Vendeur : contrats de liste/détail distingués, propriété et catalogues exacts maintenus. Admin : factureE existante envoyée par outilM5 canonique sur données fictives avant observation définitive, factureA brouillon toujours non calculable; JSON mobile issu du vrai moteur, revalidé sans régénération.
- Doc ROLES dédupliquée : la réponse serveur vendeur contient la projection interne; la whitelist mobile retire coûts/marges avant affichage/cache. Aucune confidentialité serveur supplémentaire revendiquée. BOUCLE alignée sur permission réelle de tester/construire Core localement.

Revue indépendante GPT-6 Astra, lecture seule et passes ciblées : aucune nouvelle faille runtime confirmée, deux findings sur assertions partitionnées et promesse documentaire, corrigés et revérifiés. Cela reste une revue bornée, pas une certification exhaustive.

## Limites et ressources actuelles

Machine ARM64, Python3.12.3, Node24.16.0, pnpm12.4.0, uv0.12.19 installés seulement dans l'espace de travail. Pas de versions/dépendances produit renouvelées. Docker local refuse l'accès à la socket; aucun chmod global/groupe/sudo de contournement. LiteLLM/PC1, fournisseurs et modèles réellement configurés non établis ici : aucun hôte, credential ou endpoint inventé.

Le build rapporte **startup JS371592B >371332B** et une alerte CSS proche du plafond; exit0 ne vaut pas gate performance verte. La suite tooling amont entière révèle34rouges sur surfaces privées/élaguées; sa régression de routage est vérifiée séparément, aucun test ignoré ajouté pour la rendre verte. Ces dettes restent ouvertes.

CI du nouveau commit à observer séparément; aucun succès du parent réattribué. PostgreSQLM3, restitution navigateur/TLS, fournisseur vocal réel, OCR/corpus client, précision/calibration indépendante, paie/fiscalité officielles, avatar audiovisuel complet et restaurationVPS restent non qualifiés. Une intention incertaine n'est ni purgée ni rejouée; ACKM10 ne certifie pas exactement-une-fois métier. Aucun rapprochement humain des intentions livré par cette reprise.

## File de lots reprise

Les fenêtresH0/H24 d'octobre5 sont historiques, pas un daemon24h. Reprise après intégration/CI :

1. **Verticale unique M7→M1→M2→M3→M4/M6→M5→M8/M9/M10** : composer les entrées/outils propriétaires existants sur une même affaire/lead/devis/WCT, quatre profils, reprise et absence d'effets doublés. Les E2E actuels qualifient des sous-parcours, pas encore l'ensemble unique.
2. **Exploitation** : PostgreSQL autorisé isolé, restauration indépendante, diagnostic/reconciliation sourcée des intentions, budgetUI et tooling hérités. Garder export/brouillon fonctionnel lorsqu'un fournisseur manque.
3. **Capacités profondes** : mémoire affaires/développement isolée et ingestion durable évaluée; réception réelle; CFO/paie/fiscalité préparatoires sourcées; CMO/canaux/ROI; mesure/calibrationM3 indépendante. RechercheGitHub/GitLab et licences avant capacité majeure, sans empilement de frameworks.
4. **Surfaces utilisateurs** : dashboard agents/modèles/outils/droits/secretrefs/coûts, mobile quatre profils hors ligne, texte/audio/avatar3D avec identité et permissions communes. Résultats/coûts/latence mesurés, aucun gain inventé.

Le CoreOpenClaw, CRM, comptabilité, bus/outbox et ambitions des dix départements sont conservés. Donnée manquante=inconnue/refus nommé. Argent réel, déclarations, engagements, achats/publications sensibles et suppressions définitives gardent leurs validations humaines. Conversations absentes et mémoire personnelle du modèle ne sont pas déclarées archivées.

## Suivi de la première CI de reprise — 2026-10-06T05:12:10.680562-04:00

Le commit d'intégration `44e388245253b6697391002415b2d0212b1e60cb` est publié sans force. Sa première CI révèle deux causes corrigibles : verrou mobile `source-map-js1.2.1`, et catalogue historique M3 resté à13outils avant les3lectures transportées. Les résultats de ce parent demeurent séparés; le nouveau commit de correction exige sa propre CI.

- Mobile : correctif amont `source-map-js1.2.2` ([avis GitHub](https://github.com/advisories/GHSA-68fv-2mgg-jv7q)), seule entrée du verrou changée (version/URL/intégrité). Audit au seuilhigh passé de1high à0high,35moderates conservées, aucun seuil/exclusion abaissé; npmci puis2693tests/123suites, types et17régressions verts.
- M3 : ensemble exact du catalogue conservé, trois lectures explicitement nommées et contraintes àT0; aucune nouvelle mutation pour les scénarios. Rouge local1F/26P conservé; fichiers scénarios/preuves verts33/33, batterie de référence et captures réelles avant/après incluses. Département2240P/9S hors deux batteries réparties séparément dans la CI; aucun skip ajouté.
- CI Core :12tests transportés et5voisins cron ajoutés à la liste explicite,183cibles sans doublon; vérification rouge17absents puis verte. Les suites locales305Core/270cron qualifient déjà ces fichiers via le même lanceur canonique; les runners restent une preuve séparée.
- PostgreSQL : jobM10 du parent réussi après téléchargement explicite `pgvector/pgvector:pg17`. Cela ne qualifie pas les testsPostgreSQLM3, les appareils réels ou une restaurationVPS.

[Capsule de suivi](PREUVES-REPRISE-2026-10-06-r2.tar.xz), SHA256 `079c176e26ce9d1831fd61c487f831495b7fb22c38371d41004bbe52b03c51a5`, conserve les nouveaux reçus rouges/verts et les snapshots/journaux de la première CI. La capsule r1 reste intacte. Le registre distingue désormais25suppléments de qualification. [File verticale et critères de jonction](CONTINUITE-VERTICALE-2026-10-06.md) : sous-parcours actuels distincts d'un scénario unique non livré. OPSYS-AI reste **PARTIEL**.

## Reçu canonique du voisin fallback — 2026-10-06T05:26:41.489779-04:00

La CI Core du premier commit de reprise révèle un unique cas rouge dans les13partitions OPSYS : fixture historique `run-entry.admission.integration.test.ts` restée au reçu partiel `reservation-0001`. Reproduction locale1F/35P; la fixture retourne désormais une identité hex32 et un reçu complet lié aux vrais arguments de capture, puis la même réservation conciliée. L'assertion fournisseur unique, candidat0 après échec avant admission et les2appels MCP exacts sont conservés. Les guards de production restent stricts et inchangés.

Le hook `beforeEach` retournait le mock de `mockReset`; Vitest5 l'appelait comme fonction de nettoyage sans argument. Hook à retourvoid et suppression de l'affectationunused, setup conservé. Reprise r2 rouge et r3 verte conservées : **93/93 sur5fichiers complets**, y compris le véritable MCP Python HTTP, sources figées; lint ciblé vert. Aucun nouveau build requis pour cette fixture seule; les octets de production restent ceux déjà qualifiés.

[Capsule r3](PREUVES-REPRISE-2026-10-06-r3.tar.xz), SHA256 `30b298ff60bc318abc9ca01d8f52d94a6de612c632363512b192eab3f2ed6ddf`, avec journal CI et reçus rouges/verts. Registre **26 suppléments**; les302sources du transport et104absences restent rapprochées. Le commit de correction doit obtenir sa CI applicable propre; aucun succès du parent attribué. OPSYS-AI reste **PARTIEL**.

## Budget de la qualification du socle — 2026-10-06T06:34:03.351447-04:00

Le HEAD0753f4c3 réussit les dix départements et les neuf batteries M3. Son socle est interrompu par GitHub à45minutes, pytest vers68%, aucunF visible avant interruption : annotation « maximum execution time of45m0s ». Le statut est cancelled et gates échoue correctement; aucune qualification globale verte n'est déduite de ce journal incomplet. L'ancêtre44e avait obtenu4486P/17S en40m55 surunautrerunner; ce succès n'est pas attribué au HEAD0753.

Seul le budgetwallclock du socle passe à90minutes, comme les batteriesM3, pour conserver la suite complète. Commandepytest, collecte, tests, gardes, quotas et seuils inchangés; pas de tests ignorés/désélectionnés ajoutés. ContratsCI existants :10/10, sources figées. Le choix90min offre une marge après45min/0.68≈66min (estimation, pas une mesure de durée finale). Coût : occupationrunner pluslongue, un défaut réel peut toujours faireéchouer le job.

[Capsule r4](PREUVES-REPRISE-2026-10-06-r4.tar.xz), SHA256 `315ba335c909676ad618e7db74e86da1d9a482b133150971e25f6b7049eb4e92`, conserve l'annotation, le journal interrompu, la référence et la vérificationCI locale. Le registre distingue27suppléments;295/302sources restentidentiques autransport, septmodifiées parqualification. Les104absences restenttracées. Le nouveaucommit de budget doit obtenir sespropres workflows applicables; OPSYS-AI reste **PARTIEL**.
