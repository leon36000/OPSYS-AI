# Préparation M2 vérifiée avant estimation durable M3

15 octobre 2026, Toronto. OPSYS-AI demeure **PARTIEL**.

Le [lot historique](M2-PREPARATION-M3-DESIGN-2026-10-05.md) déclarait explicitement
la limite structurelle du marqueur. Cette évolution ferme cette limite à l’entrée
durable `m3_estimer_projet` ; elle ne réécrit pas la preuve historique.

Un appel déjà autorisé ne peut plus faire persister une estimation à partir d’un
marqueur M2 périmé ou falsifié. Le pont `opsys.readiness_m2` relit le registre M2
canonique et appelle son vérificateur. Un refus retourne
`REJ-READINESS-NON-CONSTATEE`, sans estimation ni publication M3. Un marqueur
courant reste accepté. Les règles de calcul, photos, prix et permissions restent
celles des composants existants ; le validateur pur M3 reste structurel.

La vérification et les effets M3 partagent la transaction courante, sur les voies
directe, atomique et profil admis. SQLite utilise son `BEGIN IMMEDIATE` existant.
Sur PostgreSQL, une garde transactionnelle partagée protège la lecture et l’effet ;
les écritures canoniques M2/principal prennent la garde exclusive. Après attente,
un producteur préparé sur une ancienne tête est refusé par `EcritureConcurrente` ;
sa transaction doit être annulée puis l’opération réévaluée. Aucun rejeu automatique.
Les autres registres ne prennent pas cette garde.

La garde PostgreSQL exige **READ COMMITTED sans autocommit**, contrôlé sur la
connexion réelle. Un autre mode est refusé avant la prise de verrou. Un rollback
de savepoint peut libérer un verrou nouvellement acquis ; il annule aussi les effets
de son périmètre. La publication des besoins reste dans la transaction M3.

## Qualification et limites

Les tests ciblés refusent les marqueurs périmés, falsifiés ou d’un autre lead,
préservent les propriétaires valides et acceptent le contexte courant. Régressions
locales : M2 1 813 réussites ; M3 2 252 réussites et neuf exclusions explicites
(huit pour vision optionnelle, une garde CI). Les contrôles stockage/capacités/CI,
Ruff et le vérificateur métier passent. Les reçus rouges et les préparations
invalides sont conservés séparément ; ces comptes ne sont pas des capacités livrées.

Le commit `847e0485b40f4289e1746e8fcc0c5eb7174e8ef3` a exécuté **31 cas PostgreSQL
natifs réussis, sans exclusion**, dont les sept nouveaux cas ci-dessous (CI
`38749365671`, tentative 1, 61,15 s). Sa CI a aussi révélé des fixtures de mini-dépôts
M3 et un ancien faux marqueur M4 : les corrections de ces tests et de la fermeture
des entrées de preuve restent à qualifier sur le commit de continuation. Le code
de production et les contre-tests PG restent inchangés dans ce suivi.

Sept cas sont
sélectionnés dans le job existant : les deux ordres M2/M3, deux producteurs M2,
rollback de savepoint, deux niveaux de snapshot refusés et autocommit refusé.
Le contrôle strict passe de 24 à 31 cas au total, sans accepter skip, erreur ou échec.
Docker local inaccessible ne fournit aucune preuve PostgreSQL.

L’ancre M2 est globale : une mutation d’un autre lead peut imposer de réémettre
le marqueur. La garde coopérative ne couvre pas du SQL administratif hors protocole,
une restauration concurrente ni la modification du fichier de profil d’entreprise.
Cette qualification ne prouve pas une session Core, le transport, un mobile physique,
les fournisseurs externes ni la complétion des départements.

Référence de sémantique SQL : [PostgreSQL 17, isolation des transactions](https://www.postgresql.org/docs/17/transaction-iso.html).
