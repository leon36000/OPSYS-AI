# M6.13 — fichiers, preuves de lignes et aperçu protégé

Décision ROOT, 8 octobre 2026, Toronto. Base publiée : `28c467c8f88ed48fb089367d1e06f5a67ff896d2`. Cette conception met en œuvre la file autorisée ; elle ne présente aucune nouvelle façade comme livrée. OPSYS-AI reste PARTIEL.

Le contexte M3/M4/M6, le prévu et l’ACK matériaux restent ceux du lot publié et qualifié. Le worktree B est réutilisé après préservation des 29 sources, copie exacte et stash identifié dans `continuation-post-m6-contexte-workspace-r1.json`. Aucun renouvellement de dépendances, fournisseur, donnée client ou production. La CI de 28c continue séparément.

Sources de conception : `qualification/M6-13-mobile-conception-r1/proposition-r1.md`, `qualification/M6-13-backend-transport-conception-r1/proposition-r1.md` et leurs reçus SHA. Les quatre rouges de `qualification/M6-13-fichiers-ack-readonly-r1` sont des reproductions du lecteur actuel ; ils ne qualifient pas le sender, le CAS serveur ou un téléphone.

## A — reçu de fichier lié au bloc

Quatre surfaces initiales mobiles : `fichiers/protocole.ts`, son test, `outbox/descripteurs.ts` et son test. Validation JSON fermée de la réponse et du contexte avant accès aux propriétés : getters, prototypes et cycles ne s’exécutent pas. Le descripteur transmet la mutation persistée. Un contexte absent ou malformé, des indices hors compte, un bloc demandé absent et une référence finale discordante gardent la même intention en attente ; aucun UUID neuf.

Le contrat serveur actuel expose seulement `{reference,complet,blocs_recus}`. Un ACK partiel confirme le contexte RPC et les indices reçus, sans prouver un SHA absent de la réponse. Un ACK complet exige la référence déterministe attendue et les indices exhaustifs. Le CAS serveur vérifie les octets. Une validation du résumé local ne devient pas une signature cryptographique. L’ancien statut `envoyee` sans reçu vérifiable restera traité dans les callers et la barrière du lot B ; ajouter le hook seul ne ferme pas cette frontière.

Un second exécutant produit les réponses canoniques de M4 avec un vrai fichier PNG/JPEG fictif en deux blocs, Cap DEVICE et SQLite. Les lectures/rejeux sont comparés sans effet ; les dépôts ont leurs effets attendus explicitement distingués. Les arguments, réponses UTF-8, sources et limites sont scellés avant consommation client. Ce parcours SQL est distinct de HTTP/Gateway.

Sortie A : rouges pertinents puis lecteur/descripteur/vidangeur ciblés verts, types et sources protégées vérifiés, contrat confronté aux captures réelles. Un seul propriétaire par fichier ; aucun élargissement du sender ou de l’orchestrateur dans cette tranche.

## B — toutes les pièces avant une seule intention métier

Relire les octets et l’état serveur sous une capture d’autorité vivante. Le statut local de tous les blocs ne suffit pas à déclarer le fichier prêt. Les callbacks de stockage, hash, réconciliation et RPC gardent personne, appareil, instance, jeton, réseau et génération de saisie avant/après await. Les anciens propriétaires sont conservés en quarantaine.

Une barrière asynchrone bornée dans le sender existant vérifiera tous les fichiers de la mutation figée. Un `dependsOn` unique ou le dernier bloc créé ne représente pas cette barrière. La sérialisation par objet couvre les deux types M6, avec terminalité vérifiée par leur descripteur propre ; une ancienne déclaration inconnue bloque la nouvelle. Les objets distincts continuent. Ni note, ordre des lignes, référence ni payload ne changent après gel de l’UUID.

Les preuves suivent l’ID local pendant la saisie, puis la position finale exacte après gel. Cette position est distincte de `position_source` du prévu. Deux pertes identiques gardent deux positions. Le brouillon conserve les notes et métadonnées locales ; pas de DTO courant, de jeton, de permission ou d’URL bearer persistée.

Sortie B : dernier fichier incomplet/inconnu/corrompu donne zéro appel déclaration, mêmes UUID au rejeu/redémarrage, isolation d’autorité et groupe commun prouvés avec le vrai sender et les dépôts concernés.

## C — writer et preuves atomiques

Façade proposée `m6_declarer_materiaux_avec_preuves_appareil`, DEVICE employee/admin T1/N3, arguments fermés `{wct_id,formulaire,preuves_lignes}`. Formulaire historique réutilisé, 24 lignes maximum ; achat terrain reste sa voie historique. Chaque PERTE/BRIS a exactement une entrée `{position_ligne,note,photos}`, huit entrées maximum, note non blanche de 500 points de code maximum, zéro à trois références CAS distinctes. Une note seule est admise et affichée comme telle. Auteur, rôle, date/lieu de dommage et authenticité photographique ne viennent pas du body.

Identité et cible actuelles avant sources, approbation/rejeu ou effets. Préflight de l’ACK entier au quota Cap réellement admis ; chaque CAS est ensuite vérifié séquentiellement avant stock. Le writer M6 et ses cascades sont réutilisés. Les preuves append-only se lient aux vrais ajouts principal, indices, prédécesseurs et hashes observés dans la même transaction ; aucune correspondance par matériau/quantité seule et aucune clé photo inventée. Acteur et heures serveur/appareil restent distincts.

Savepoint explicite pour writer+cascades+preuves. Un refus métier `accepte:false` encapsulé dans `ok:true` ne prouve pas l’annulation d’`executer_atomique`. Toute postcondition refusée après écriture doit sortir du savepoint par exception avant traduction en verdict. Panne technique/concurrence propagée : réclamation d’idempotence également annulée. Même UUID/body rejoue une seule écriture ; conflit d’arguments ne reçoit pas une nouvelle clé automatique.

Une réponse déjà acceptée qui ne tient plus dans un quota réduit reste une issue de transport inconnue. Elle ne doit pas être présentée comme un refus métier qui autoriserait un second effet. Aucun artefact ni troncature de confirmation de ce parcours.

Sortie C : dépôts CAS réels, stock et preuves associés, dernière preuve invalide et panne post-writer annulant tout le lot, rejeu/close-reopen/conflit et rôles retirés avant les frontières pertinentes, ACK borné avant effets et après écriture vérifiés.

## D — lecture et vrais pixels

Lecteur admin JSON proposé `m6_lire_preuves_pertes_wct_appareil`, pages courantes bornées et refus sans artefact. Note seule, ancienne preuve absente, photo vérifiée à l’enregistrement et fichier actuellement indisponible/corrompu sont des états distincts. Absence ne signifie pas zéro perte.

Choix : route Gateway DEVICE binaire et bridge Python interne privé avec credential distinct du MCP public. Sélecteur fermé WCT + référence de preuve index/hash + position de photo ; aucun hash CAS libre, rôle, agent, URL ou jeton en query. Destination fixe configurée pour cette instance. Bridge absent : aperçu indisponible explicite. Le téléphone ne reçoit ni son secret ni son URL interne.

Le Core revalide le vrai jeton DEVICE et la même identité avant émission ; une simple génération générique ne suffit pas. Python vérifie le lien métier et le CAS avant les headers puis refait l’autorité dans des transactions fraîches pendant l’émission. Révocation/abort arrête les octets suivants, sans promettre de retirer ceux déjà reçus. Headers image, taille/SHA exacts, `no-store`, `nosniff`, pas de redirect ni erreur JSON injectée dans les pixels après headers.

Le client assemble dans un emplacement temporaire privé, vérifie taille/SHA/MIME avant rendu et purge au changement d’autorité/cible/refus. Les limites de décodage/pixels et la mémoire doivent être exercées ; une magic JPEG/PNG seule n’est pas un décodage complet. Le fichier vérifié prouve son intégrité et son association déclarée, pas la scène, la cause, le lieu, la date ou l’auteur de la prise de vue.

Les fragments JSON5400 nécessitent au moins 2 590 RPC pour 10 MiB, même sans overhead ; ce calcul est une borne statique, pas un benchmark. Réutiliser les uploads M4 en blocs 256 KiB, puis une requête binaire nominale pour l’aperçu. Le changement Core réutilise sa licence MIT et les briques existantes ; build complet frais, checks HTTP/auth/routage et Native du nouveau tree obligatoires.

## Intégration et limites

Ordre : A → B → C → D → qualification ROOT intégrée → audit/registres/capsule → publication privée normale et CI du commit exact. Des tâches indépendantes derrière interfaces scellées peuvent avancer en parallèle ; une seule intégration et un seul propriétaire par surface.

La livraison du lot complet exige le parcours fichier→déclaration→lecture→pixels via Gateway réel, les preuves de reprise, rollback et révocation, les checks proportionnés, le build Core frais et la CI applicable. Tests purs et transports fetch de rejeu restent distingués de SQL, Native et téléphone. Les huit familles complètes d’alertes M6.13, les causes humaines, les coûts nouveaux, la rétention et la production restent leurs propres dépendances. Les dix départements profonds et la verticale complète demeurent les critères du programme.
