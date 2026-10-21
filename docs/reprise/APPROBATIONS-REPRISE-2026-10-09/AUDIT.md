# Audit — reprise d’une décision d’approbation à confirmation inconnue

Date Toronto : 2026-10-09T03:57:27.634579-04:00. Parent exact : b069f7453648ac8651ce9e203dbead664fece581. **Proposition hors dépôt qualifiée localement : revue indépendante et CI exacte du parent admises ; publication et CI du futur commit correctif en attente.** Trois sources mobiles et trois préimages Git exactes, registre exhaustif. Aucun backend, SDK ou vidangeur générique changé. Aucun effet stock, coût, statut M4, M5 ou M10 ajouté. OPSYS-AI reste PARTIEL ; la future jonction typée M6 → M4 N4 reste non livrée.

## Défaut et correction

Le vrai SDK, descripteur, dépôt mémoire et vidangeur sur b069, avec fetch fictif contrôlé, ont terminalisé un ACK HTTP 200 illisible : un test rouge et deux intentions D visant la même demande tentées. Aucun effet backend n’est démontré par cette simulation. Le correctif remappe uniquement les confirmations illisibles ou tronquées et les trois ERREURS_PASSAGERES canoniques vers accuse_invalide ; le descripteur conserve aussi les refus HTTP incertains.

La correction conserve l’intention quand la confirmation est illisible ou technique ; les refus métier legacy restent interprétés comme auparavant et n’acquièrent aucune nouvelle preuve indépendante. Les ACK valides executee, refusee et echec restent reconnus. Aucune nouvelle association D → maillon M4, ni tuple durable de destination d’origine, n’est introduite. La reprise démontrée conserve UUID, corps, heure et destination dans une session fictive inchangée. Les états echec_permanent historiques ne sont pas migrés.

La sérialisation utilise le namespace technique constant approbations : une confirmation inconnue bloque aussi les décisions suivantes d’autres demandes de ce groupe. C’est un compromis conservateur explicite, sans nouvel identifiant métier. Le rôle SQL nathan_owner reste nécessaire pour décider N4 depuis l’app ; admin seul ne suffit pas. Les Meta P/D ne deviennent pas l’autorité de l’action approuvée, le motif ne devient pas un contrôle de révision et aucune approbation automatique n’est ajoutée.

## Preuves et disposition des rouges

Le diagnostic initial, un test rouge, reste scellé séparément. Les nouveaux tests ont donné 11 échecs et 121 succès, dont dix écarts pertinents et un oracle lead_note modifié par erreur d’édition puis immédiatement restauré. Le ciblé a ensuite donné 132 succès dans deux suites. Un détail hérité contradictoire a produit un échec, deux succès et 66 cas exclus par filtre ; il a été corrigé uniquement dans l’adaptateur. Les premières globales r1 restent historiques.

Qualification finale r2 : **5 149 tests réussis dans 221 suites, TypeScript sans erreur** ; digest des 577 chemins mobiles : 98d86ccddbd6207c70b932542803e1c2b77a6f1069a90a0398e448e61f804dcf. Les 574 autres chemins B et les 577 chemins R sont inchangés ; les autres descripteurs sont byte-identiques après retrait exact du delta autorisé. Logs v2 clos avec EOF et processus observés arrêtés ; descendants jamais observés non qualifiés.

ROOT a rehashé les 29 membres mobiles, les trois sources et leurs préimages, puis obtenu un export Android avec code 0. Le premier contrôle de marqueur hex/Unicode a été classé infrastructure et conservé ; il n’est pas présenté comme bug produit. La revue indépendante a donné 132 succès dans deux suites et aucun finding dans le scope des trois sources. Ces preuves ne qualifient ni SQL, ni Gateway, ni téléphone, Hermes ou ExpoSQLite.

## Continuité et publication

Audits déjà présents dans les blobs Git du parent b069, SHA détaillées dans le registre : [Transmission historique](../TRANSFERT-INFRA-2026-10-05/AUDIT-TRANSMISSION.md) ; [Reprise historique](../TRANSFERT-INFRA-2026-10-05/AUDIT-REPRISE-INFRA-2026-10-06.md) ; [Rappels M1](../RAPPELS-M1-2026-10-09/AUDIT-RAPPELS-M1-2026-10-09-r1.md) ; [Intentions M6](../INTENTIONS-M6-2026-10-09/AUDIT.md). Ils assurent la continuité de provenance ; aucune qualification historique n’est héritée par le futur commit correctif. Les 302 sources et 124 supports du transfert restent ceux des audits précédents ; **104 références demeurent indisponibles**, sans preuve ou conversation reconstruite.

La capsule copie les allowlists exactes Mobile 29, diagnostic 9, ROOT 5 et revue 10, leurs manifestes, les trois sources et les trois préimages. Le readback ROOT additionnel est sélectionné séparément sans réécrire un manifeste clos. Aucun auth runtime, configuration, DB, header ou token opérationnel n’est exporté. Les literals d’authentification des tests et du probe sont explicitement des fixtures non opérationnelles. Roundtrip et scanner conformes ; le scanner n’est pas une garantie absolue contre un secret arbitraire. CAPSULE.json reste extérieur à l’archive pour éviter un hash récursif.

Root seul intégrateur et publisher. La CI exacte du parent est terminale et réussie ; elle ne qualifie pas le futur commit correctif. Le smoke primaire de 132 tests sera distinct après copie par ROOT. Les départements profonds, les huit familles d’alertes M6 et les évolutions M4/M5/M10 ne sont pas déclarés achevés.


## CI exacte du parent, distincte du correctif

Run 37896917430 sur b069f7453648ac8651ce9e203dbead664fece581 : un appelant CI et cinq appels de workflows réutilisables, 40 jobs dont 38 réussis et deux Docker opt-in ignorés, gates success. Reçu terminal SHA 4ce4011438db9ad3382ebb38f181b59be1710419965de5d8fa35c3677f2416b5 ; manifeste SHA 81a91b9e02a9281c6576891ae1dc8234aeba38480d99d6fdd38ff18b37d00195, 60 membres publics rehashés et copiés exactement.

Les résultats du parent comprennent 14 776 tests fast et 31 omissions, 5 135 tests mobiles dans 221 suites avec types/export Android, 4 938 tests socle et 17 omissions, un test PostgreSQL, 232 outils et 140 DEVICE. Les raisons de skip et les jobs/steps exacts restent dans les projections CI, pas des causes reconstruites. L’artefact Core 11602466512, SHA c562d4a8c513817334dc83badf40d40dc66d9c581f7d980df6fe9bafd7b1c494, a 40 phases et 38 paires selon son reçu exact.

La dernière activité était le socle, pas l’installation : la précédente inférence d’une installation bloquée a été corrigée dans installation-timing-disposition-r1.json, SHA 5e8786ad6ad961bc6c9a82fb09edc62dffe6af03fe5aa27b6b0a6f046ca30d26. Aucun diagnostic de durée n’est inventé. Ces chiffres parent restent distincts des 5 149 tests locaux du candidat. Le smoke primaire de 132 tests, puis la CI du nouveau HEAD, appartiendront à l’intégration ROOT.
