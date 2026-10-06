# Complément V1 — qualification et limites après la première CI

Date Toronto : 2026-10-06T15:13:12.981109-04:00. Premier commit V1 : `2210e75d177aec6ef20329982504829253f776c9`. La reprise antérieure au parent `e9c886a56f33f38c4ea32de107b1522e5327cc21` et la capsule r1 restent immuables. **OPSYS-AI reste PARTIEL.**

## PostgreSQL : blocage établi, preuve positive initiale non obtenue

La CI du premier commit a réellement exécuté les sept variantes PostgreSQL : **sept échecs** sur `REJ-LIAISON-CIBLE: liaison de cible temporairement désactivée hors de SQLite`. Installation et préparation de l’image ont réussi. Le socle complet conserve **7 échecs / 4499 réussites / 17 ignorés**, sans convertir le rouge en succès historique.

Le garde C02 de production est conservé. Les sept scénarios d’affaire sont désormais explicitement SQLite. Une frontière HTTP privée distincte vérifie le refus PostgreSQL exact et l’empreinte de toutes les tables META inchangée. Elle intervient avant validation de l’affaire : elle ne qualifie pas une demande métier complète valide. Le job requis `frontiere-postgresql` remplace la qualification positive initialement prévue ; JUnit non vide et zéro skip/failure/error restent obligatoires. Son résultat distant sur le prochain commit demeure à obtenir. L’import qualifié du test a été vérifié en collecte isolée après la découverte du problème importlib.

## Correctifs de sécurité ciblés

Les audits CI ont signalé [shell-quote critique](https://github.com/advisories/GHSA-pqg4-j6r4-53mv) et le [client OAuth MCP](https://github.com/advisories/GHSA-6qxp-vccf-f47h), ajoutés à la base GitHub le 6 octobre. Les anciennes CI vertes restent des observations datées. Reproductions locales rouges conservées.

`shell-quote` passe de 1.10.0 à 1.11.0 : une seule entrée du verrou mobile change. Le SDK MCP passe de 1.30.0 à 1.31.0 ; les paquets client/core UI passent de 2.0.0 à 2.2.0. Le lien peer Google suit le SDK, sa version ne change pas. Toutes les autres versions et intégrités sont conservées, comparaison machine archivée. Le délai de maturation de sept jours et les seuils d’audit sont inchangés ; aucune exception ajoutée. Installation finale du verrou réussie. Audits high locaux verts : **35 modérées mobile**, **3 faibles / 1 modérée Core** restent visibles.

Le SDK et shell-quote portent MIT. Les LICENSE client/core indiquent la transition MIT vers Apache-2.0 pour les nouvelles contributions de code, CC-BY-4.0 pour la documentation hors spécifications. Notices des paquets conservées ; empreintes du LICENSE dans le registre, aucune copie de nouveau source amont dans le fork.

Le provider conserve les objets issuer/tokens/extensions. Un ancien secret sans issuer valide n’est plus remis au SDK. Hors capacité interne de connexion explicite, son callback refuse de remplacer un client conservé. Il permet un objet identique ou seulement l’ajout d’un issuer déjà prouvé par l’ancien client ou la provenance des tokens ; la découverte courante ne suffit pas. La CLI utilise la capacité existante `allowAuthorizationRedirect:true`, son lifecycle login étant facultatif.

La revue a reproduit l’écrasement avant refus avec un nouvel émetteur offrant l’inscription dynamique. Tests rouges puis correction : client legacy et client lié, zéro requête token, ancien client/tokens/provenance conservés. **Un POST d’inscription distante peut précéder le callback**, son corps ne contient pas l’ancien secret dans ces tests. Aucune garantie de zéro effet réseau OAuth, de connexion réelle navigateur/fournisseur ou d’absence de fuite dans tout trafic réel n’est revendiquée. La découverte peut évoluer : le store entier n’est pas dit immuable.

## Vérifications locales finales

- Verticale SQLite et contrôles CI : **22 réussis / 1 refus PostgreSQL ignoré localement**, Docker inaccessible. Sept scénarios métier restent verts.
- OAuth après formatage : **74 réussis sur sept fichiers**, puis **10 réussis sur la préparation**, deux shards réellement terminés. Format, oxlint et empreintes des quatre fichiers verts. La première régression rouge interrompait le second shard ; aucun défaut de routage.
- Mobile : **2693 tests / 123 suites**, types stricts et **22 contrôles de dépendances** verts ; les quatre terminateurs de ligne après commentaire sont refusés par le consommateur réel React DevTools.
- Types Core/UI/extensions et build complet : exit0, sources figées pendant la campagne finale ; build 201.914s, pic RSS 10.39GiB, aucun garde déclenché.
- Cinq erreurs statiques avatar corrigées (override et champs inutilisés), **7 tests du composant** verts. Fixture voice-call alignée sur le défaut canonique `missedCallIngress:false`, **9 tests** config/webhook verts ; aucun changement du garde de production.
- Whitelist Core : **191 cibles uniques présentes**, huit fichiers OAuth ajoutés aux tests CI applicables. Ruff des fichiers Python et diff whitespace verts. Les campagnes se chevauchent et ne s’additionnent pas.

Le build ne vaut pas un budget performance vert : startup UI **371577B gzip**, limite **371332B**, dépassement **245B**. Aucun seuil ni baseline augmenté. Les 34 rouges historiques du tooling amont ne sont pas déclarés corrigés.

## Continuité et conservation

Les limites initiales V1 restent ouvertes : harnais appareil Python, pas Core TypeScript/téléphone ; admission/quotas/révocation runtimeProfile non exercés ; reçus M10 sans preuve de restitution mémoire autorisée ; estimation terrain, fournisseurs, professionnel, argent, appareils, publication/ROI et restauration indépendante non qualifiés. Le profil mobile client demeure un squelette.

La prochaine porte proposée est une lecture client par lien temporaire d’une soumission canonique, réutilisant `contenu_client`, stockage et audit, sans droit N5. Émission/révocation, échange HTTP et autorité limitée manquent : proposition conservée dans la capsule, aucune capacité client livrée.

Le registre rapproche à nouveau **302 sources**, conserve **124 supports** et **104 références de preuves exclues du pack léger**, sans récupération ni réexécution revendiquée. Chaque adaptation V1 figure dans le delta avec empreinte et limite. Les audits/capsules antérieurs restent octet pour octet conservés.

[Registre actuel](REGISTRE-VERTICALE-2026-10-06-V1-r2.json). [Nouveaux rouges/verts et CI initiale rouge](PREUVES-VERTICALE-2026-10-06-V1-r2.tar.xz), SHA256 `6ac2eae598255a89ab56b675cb101c0126b544af9760dce40197153d00925305`. Nouveau HEAD/CI exact à obtenir après publication normale sur la branche privée existante, sans force-push, fusion ni production. La revue indépendante ferme les findings de preuve N5, collecte PostgreSQL et conservation OAuth dans leurs périmètres.
