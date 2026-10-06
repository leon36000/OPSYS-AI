# Renouvellement OAuth sans inscription implicite

Date Toronto : 2026-10-06T19:18:27.833772-04:00. Parent exact `00b56a439de04809bee2a91e78cb59d098decd56`. OPSYS-AI reste **PARTIEL**.

Le renouvellement en arrière-plan pouvait laisser le SDK inscrire un nouveau client avant que le callback refuse. Le coordinateur active maintenant un mode privé `refreshOnly` : il exige un client existant et une provenance d'issuer déjà établie, concordante avec la découverte courante. Les secrets sans issuer valide, les clients absents, les changements d'issuer et les stamps malformés sont refusés avant l'inscription ou la requête token OAuth. La CLI conserve sa capacité explicite de connexion. Aucune dépendance renouvelée ni garde de lease/lifecycle retirée.

La revue a reproduit deux variantes : issuer vide/blanc, puis NBSP/BOM autour d'une URL que `trim()` rend valide mais que le SDK refuse sous sa forme brute. La validation porte également sur l'URL brute. L'ancienne provenance des tokens ne peut enrichir qu'un client public dont l'issuer est réellement absent ; la découverte courante ne crée pas de provenance.

## Qualification locale fraîche

- Trois scénarios legacy/bound/missing : rouge initial **3 échecs/10 réussites**.
- Issuer public vide/blanc/invalide : rouge **2 échecs/14 réussites**.
- NBSP/BOM : rouge **2 échecs/16 réussites**. Tous les logs/reçus et reprises vertes restent conservés.
- Finale OAuth/CLI : **93 + 10 tests réussis sur 10 fichiers complets**. Huit scénarios négatifs exigent zéro POST registration et zéro POST token OAuth, credentials et provenance préservés. Les campagnes se recouvrent ; pas d'addition avec les historiques.
- Types Core/UI/extensions, format, oxlint et build complet : exit0, sources globales figées, ressources bornées. Régressions des trois ponts Core→Python HTTP réexécutées séparément ; leur périmètre précis figure dans le reçu et la note de continuité.
- Startup UI : **371568B**, budget **371332B**, écart **236B**. Un build réussi ne clôt pas ce budget. Tooling amont34rouges historiques conservés.

La découverte peut encore effectuer des GET et actualiser le store ; seuls credentials/tokens/provenance sont dits conservés dans les refus testés. L'invocation MCP initiale ne devient pas une preuve de zéro réseau général. Fournisseurs réels, navigateur et tout trafic réel restent non qualifiés. **CI à obtenir sur le nouveau commit exact**, distincte des six workflows verts du parent.

## Conservation et suite

Les **302 sources transportées** sont relues et restent au contenu V1r2 ; les trois adaptations OAuth existantes sont tracées à part avec préimages/empreintes. **124 supports et 104 références absentes** restent conservés, sans récupération ni réexécution inventée. Tous les 24 artefacts antérieurs restent immuables. Les états intermédiaires ont reçus/logs/empreintes, mais pas chacun un snapshot intégral distinct.

Le prochain raccord de qualification joint le profil d'exécution M8 au WCT de l'affaire déjà traversée par M7→M10, puis prouve retrait/révision/redémarrage avec le vrai runtime Core→HTTP Python. Les quotas gouvernent l'appel fournisseur, pas chaque lecture T0. Les preuves existantes sont détaillées dans la capsule ; aucune jonction complète ni fournisseur réel revendiqué. Le profil client nécessite encore son contrat et son implémentation ; la recherche GitHub/GitLab recommande les primitives locales, aucune nouvelle brique adoptée.

[Registre](REGISTRE-OAUTH-RENOUVELLEMENT-2026-10-06-r1.json), [preuves rouges/vertes](PREUVES-OAUTH-RENOUVELLEMENT-2026-10-06-r1.tar.xz), SHA256 `0bfbbdea3b000898a2e79dcf0f4923ae1e5f0948a8c4554840a93a43b6763c2d`. Branche privée/PR brouillon, aucun force-push, fusion ou production.
