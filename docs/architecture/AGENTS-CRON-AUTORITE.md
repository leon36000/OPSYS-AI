# Autorité privée des remises cron de profils

Ce sous-lot Python conserve et contrôle une remise. Il ne raccorde ni transport MCP,
CronService, admission de tokens, provider, finance, publication ni ordonnanceur Python.
Le registre des profils et les intentions humaines restent canoniques. La migration additive
`0021` suit `0020` sans modifier les tables d'intentions `0019` ou de brouillons AP `0020`;
`0022` ajoute les empreintes natives SHA-256 sans convertir les révisions entières historiques.
Sources : [propriétaire privé](../../src/opsys/agents_cron_autorite.py),
[contrôle canonique](../../src/opsys/agents_declencheurs.py),
[table compagne](../../src/opsys/stockage/schema.py),
[migration 0021](../../src/opsys/stockage/migrations/versions/0021_agents_cron_autorite.py).

## Frontière d'identité

`ProprietaireCron(departements, profil_id)` est une façade **interne**. Sa construction est
réservée à l’hôte/transport authentifié ; le profil est fixé par cet hôte, jamais par
un argument d'outil, une requête agent, un rôle déclaré ou le seul identifiant d'intention.
Ce constructeur n'authentifie pas un réseau et aucun endpoint ne l'expose dans ce lot.

Les opérations ne reçoivent aucune personne ou rôle. Elles relisent le demandeur original de
l'intention et sa personne active en DB (admin/propriétaire), sans lui attribuer l'appel du
contrôleur. Le journal utilise `controleur-cron-prive`, avec action/époque/intention seulement ;
aucune capacité, empreinte de capacité, déclaration ou responsabilité privée n'y figure.
Les wrappers humains existants conservent leur contrôle de l'humain courant.

## Contrat du propriétaire

- `preparer(intention_id, empreinte_capacite, declaration, epoch_attendue, …)` : l'hôte crée
  aléatoirement **32 octets**, conserve la capacité privée, et fournit seulement son SHA-256.
  Une première préparation exige l'époque précédente `0`. Son rejeu exact relit les sources et
  rend la même lease sans la prolonger. Changer hash, révision native attendue ou durée refuse.
- `accuser(…, capabilite, epoch, lease_epoch, job_id, config_revision, declaration)` : la capacité
  privée est représentée par 64 caractères hexadécimaux minuscules. `config_revision` accepte soit
  un entier positif historique, soit le format Core exact `sha256:` suivi des 43 caractères Base64URL
  sans padding produits par `hashCronJobDefinition`. Les colonnes entières restent isolées des
  colonnes d'empreinte; aucune conversion ni comparaison d'ordre entre formats n'est faite. L'ACK
  enregistre le job et la révision cible après comparaison de la déclaration entière au mandat
  canonique. Son empreinte est conservée ; aucun deuxième registre de déclarations n'est créé. Un rejeu exact
  ne produit aucun deuxième journal. Un autre job/révision à la même époque refuse.
- `valider(…, capabilite, epoch, job_id, config_revision, declaration)` : relit le grant acquitté,
  le mandant et toutes les sources. Son succès est uniquement un contrôle durable ; il
  n'effectue **aucune admission runtime** et n'est pas un reçu d'exécution.
- `renouveler(…, capabilite, epoch, lease_epoch, declaration, lease_secondes)` : reprise explicite
  d'une lease échue, avec fencing de la lease précédente. Trois prises maximum par époque.
  Le rejeu exact de la dernière reprise encore vivante ne crée pas une autre prise.
- `tourner(…, capabilite, epoch, nouvelle_empreinte, declaration)` : rotation explicite avec
  l'ancienne capacité valide. L'époque augmente ; l'ancienne capacité ne peut plus acquitter
  ni valider. Un nouvel ACK est obligatoire et garde le job connu. Une rotation explicite peut
  fournir `revision_native_attendue` comme préimage native (entier historique ou empreinte Core)
  pour changer de format; sans argument, la préimage reprend la cible du dernier ACK. Une rotation
  d'un job déjà connu ne peut pas effacer cette préimage en la remplaçant par `null`. Les empreintes
  n'ont aucun ordre numérique et peuvent différer entre préimage et cible, car le propriétaire Python
  n'exécute pas le CAS Core. La réponse privée de rotation
  perdue peut être réconciliée par `preparer` avec la nouvelle empreinte et l'époque précédente ;
  aucun secret n'est renvoyé. Ce n'est pas une récupération d'une capacité perdue.
- `revoquer(…, capabilite, epoch)` : état durable révoqué, sans effacer intention ni ACK historique.
  Permis après retrait/désactivation du profil tant que le mandant humain est encore actif.
  Le rejeu exact reste sans nouvelle mutation. Un mandant révoqué bloque déjà toute validation,
  même lorsque l'état historique du grant indique encore `remise`.

Les signatures Python emploient des arguments nommés ; les points de suspension ci-dessus
abrègent seulement les paramètres documentés, ils ne décrivent pas des implémentations futures.
Une capacité perdue n'est ni restituée depuis sa hash ni remplacée implicitement : un nouveau
mandat humain/révision est nécessaire. Aucune capacité ne passe dans argv, statuts ou erreurs.

## Données, leases et revalidation

Seule `agents_declencheurs_remises` est ajoutée : FK intention, hash de capacité et déclaration,
époque de grant, job, révisions natives, état, époque/durée/expiration de lease, nombre de prises,
dates. `0022` conserve les entiers historiques et ajoute deux colonnes nullables `sha256:<43 Base64URL>`;
des contraintes empêchent qu'une même révision soit simultanément entière et empreinte et imposent
exactement un format sur les ACK. La contrainte SQL portable borne taille, préfixe et dernier symbole;
le propriétaire valide strictement les 43 symboles à chaque lecture. Le downgrade est refusé dès
qu'il perdrait une empreinte. La compilation offline PostgreSQL du DDL de schéma est couverte, mais
aucune migration réelle PostgreSQL n'est qualifiée. Les leases
de 1 à 120 secondes portent l'IO de remise, pas les créneaux récurrents.
Une remise acquittée n'expire pas par sa lease : elle reste subordonnée aux sources vivantes.
L'ACK ne change pas `a_declarer` et ne libère pas les plafonds de 16 déclarations/100 attentes.

Chaque opération exige SQLite **avant ouverture ou effet**. Le moteur ouvre `BEGIN IMMEDIATE` ;
les contrôles DB, écritures et journal sont dans la même transaction. Avant et après l'écriture
ou la construction, le propriétaire relit intention/instance, mandant, version et empreinte du
profil, déclencheur et fuseau, classification mémoire `global` explicite et outils réels T0/T1
N0–N2. Il compare aussi l'époque/ligne durable et la lease avant un ACK nouveau. Une panne ou
un retrait injecté après écriture annule grant et journal. Les tests injectés dans une transaction
ne constituent pas une preuve de course PostgreSQL ; PostgreSQL est refusé dans ce lot.

La déclaration est un objet JSON de types natifs, borné à 16 KiB UTF-8, 512 nœuds et profondeur 8
avant sérialisation/restauration. Les nombres non finis, cycles, chaînes invalides et champs
supplémentaires refusent. La déclaration native entière doit correspondre au constructeur
existant : agent/profil/révision, calendrier/fuseau, payload/outils/timeout et delivery `none`.
Le contrôle ne certifie pas que le job existe dans Core : le pont doit fournir une
capture native actuelle, son autorité privée et le fencing natif, puis contrôler avant stream.

## Vérification et limites

[Tests dédiés](../../tests/test_agents_cron_autorite.py) : SQLite réelle, catalogue M3 T0/T1,
rejeu/conflit, capacité perdue/rotation, ACK/job/époques, leases/crash, mandant et sources retirés,
rollback grant/journal, bornes de données et refus PG avant transaction.
Les migrations réelles `0019 → 0020 → 0021` conservent les intentions et les octets AP fictifs ;
une panne après `CREATE TABLE` garde la révision `0020` et annule la table nouvelle.
Les fixtures migratoires conservent des ciphertexts fictifs : elles ne valident pas un PDF,
un chiffrement AP ou un traitement comptable.

Le client privé Core, le producteur hôte, la réconciliation des jobs et le contrôle avant
provider sont maintenant écrits. Leurs qualifications distinctes et leurs limites figurent dans
[le raccordement hôte courant](CRON-RACCORDEMENT-HOTE-2026-10-03.md). Le retrait terminal Python
et la migration additive `0023` sont qualifiés séparément dans 185 cas; la preuve de suppression
native y est simulée. Les parcours CronService/SQLite, CAS natif, cycle de vie hôte et stream SDK
restent non qualifiés. Ces tests du propriétaire ne qualifient aucun fournisseur réel, tour de
modèle ou déploiement VPS. Aucun verrou distribué, arrêt instantané d'un stream ou isolation SaaS
multitenant n'est revendiqué.
