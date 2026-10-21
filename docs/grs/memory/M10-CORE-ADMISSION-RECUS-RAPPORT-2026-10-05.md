# Core — cohérence des reçus d’admission

Statut : garde vérifié localement, reprise POSTFLIGHT et cron complet non livrés par cette tranche.

Le Core vérifie désormais le reçu du serveur MCP Python avant le dispatch fournisseur : identifiant
hexadécimal de 32 caractères, profil réellement lié à la route, exécution, tentative, cycle et clé,
index candidat, ordinal, plafond, état réservé, absence d’usage déjà concilié et marqueur de reprise.
Le département vient du serveur lié au profil; son format est contrôlé et sa valeur est conservée
pour les vérifications de libération et de conciliation. Il n’est pas reconstruit depuis le prompt.
Le schéma Python courant ne retourne pas la révision du profil : le Core conserve la révision de
sa capture et Python vérifie la révision demandée; le garde vérifie aussi tout écho de révision s’il apparaît.

Une réponse incohérente bloque le fournisseur. Après dispatch, une conciliation incohérente provoque
un échec explicite. Un usage inconnu conserve la réserve; ce patch n’invente pas un coût zéro.
La libération avant dispatch conserve la même provenance. L’API historique de conciliation reste
compatible; le flux principal utilise sa capture immuable et contrôle tous les marqueurs.

## Vérification

ROOT r274 : **30 tests, deux fichiers complets, aucun échec, erreur ni saut**, puis Oxlint et
Oxfmt verts. Deux tests emploient le véritable serveur MCP Python HTTP et SQLite avec un
fournisseur fictif : admission, usage, budget insuffisant, refus du même cycle sans second dispatch
et révocation d’outil sur ancienne révision. Les tests unitaires couvrent les reçus d’autres profils,
exécutions, tentatives, cycles, clés et ordinals, ainsi que plafond ou reprise incohérents.
Les sources sont figées et inchangées pendant l’exécution; aucun OOM ni installation.

Les exécutions r270–r273 restent conservées. La pile r272 démontre une erreur du montage de test :
trois callbacks `beforeEach` retournaient la fonction mock produite par `mockReset`. Vitest la
traitait comme fonction de nettoyage et l’appelait sans argument. Des callbacks en blocs retournant
`void` corrigent la cause; le contournement provisoire par réponses one-shot a été abandonné.
La validation JUnit de ROOT a également été adaptée aux noms de fichiers TypeScript explicites.

## Limites et suite

Aucun fournisseur payant, client réel ou fonctionnement continu de 24 heures n’a été testé.
Le reçu n’est pas encore transmis à un collecteur de faits POSTFLIGHT. La persistance, la reprise
après ACK perdu et le raccord cron doivent être intégrés et vérifiés séparément avant de déclarer
un cycle autonome complet. Les conceptions sont conservées sous
[reprise](../../research/REPRISE-2026-10-05/conceptions/LOT5-REPRISE-CONCEPTION-r1.md),
[outbox](../../research/REPRISE-2026-10-05/conceptions/LOT5-OUTBOX-CONCEPTION-r1.md) et
[provenance](../../research/REPRISE-2026-10-05/conceptions/LOT5-PROVENANCE-CONCEPTION-r1.md).

Preuve durable : [capsule Core](../../research/REPRISE-2026-10-05/preuves/CORE-ADMISSION-RECUS-r1.tar.xz)
(SHA-256 `5f2d2d456fc1cf85c45365742dbbff9e4279644e33868605317db40a7c8885a6`).
La capsule conserve le rapport avant cet ajout de lien, les sources, préimages et exécutions rouges/vertes.
