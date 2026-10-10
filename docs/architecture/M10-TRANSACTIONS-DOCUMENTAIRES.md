# Transactions documentaires internes M10 — pilote SQLite

Cette tranche implémente `muter_document_m10(cnx, operation, commande, *, meta, quota,
mode_manifeste)`. Elle ne déclare aucun outil, façade RPC, permission de Gateway ou
consommateur mobile. Les trois noms présents dans le domaine pur restent proposés
pour le futur raccord. Les tests utilisent une instance SQLite fictive sur fichier,
un lead réellement mémorisé par M10 et une identité d'appareil injectée ; ils ne
prouvent pas une authentification DEVICE cryptographique.

## Admission et transaction

La connexion doit être celle de l'instance courante, ouverte dans une transaction
avec un SAVEPOINT déjà détenu par l'appelant. Aucun moteur, URL, factory ou connexion
de secours n'est créé. Tout dialecte autre que SQLite est fermé avant la lecture du
corpus et la réclamation. La sérialisation des transactions SQLite existantes utilise
`BEGIN IMMEDIATE` ; aucune affirmation PostgreSQL n'en est déduite.

L'identité ambiante doit être une `IdentiteAppelante` exacte, admin/source appareil.
Le signataire et son rôle sont revérifiés dans SQL ; le mode effectif de M10 doit
être `ombre`, y compris au replay. Les modes supervisé et autonome sont refusés.
Les scopes, tickets, appareil appairé et autorité cryptographique du transport
restent à raccorder séparément. Ces contrôles techniques internes ne les remplacent pas.

La commande est validée par l'API pure `valider_commande`, sans normalisation d'une
liste de paires. `Meta` doit être exacte ; appareil et clé sont des textes strict UTF8
non vides d'au plus 128 points, et l'heure déclarée reste le texte original valide
(dont `.000`), au plus 40 points. Aucun UUID n'est inféré depuis le corps ou l'heure.

La connaissance de l'affaire provient des copies canoniques M10 `evenements` et
`affaires`, des helpers existants de `recherche_affaire` et de `amont.situation`.
Une source financière seule ne constitue pas cette connaissance. Le lecteur borné
vérifie chaque registre séparément ; on n'emprunte ni recherche paginée ni budget
combiné du DTO d'un autre outil.

## Effet frais et preuve propre

Après admission et consultation prioritaire d'un claim propre déjà présent, le
chemin frais copie et valide documents/liaisons, prépare le CAS et le candidat, puis
mesure les deux frames complètes avant toute tentative d'INSERT du claim. Un quota
refusé ne tente donc pas même une réclamation destinée à être rollbackée.
L'acquisition nommée du claim réutilise exactement les colonnes,
valeurs, empreinte et `codec.encoder(None)` de `idempotence.reclamer`. Elle ne décode
aucune réponse. L'INSERT dispose seulement d'un sous-SAVEPOINT technique : après
collision PK, il est sorti puis la preuve durable complète est relue. Aucun plan
frais n'est réutilisé après collision. `idempotence.finaliser` reste inchangée.

Le document, la trace APP/J puis la liaison sont ajoutés dans le même SAVEPOINT
appelant. La capture native renvoie `APP.id` (texte de 12 caractères) et `J.id`
(entier positif i64) des vrais INSERT ; aucune recherche par corps, heure ou MAX(id)
n'est utilisée. La preuve est relue directement par les deux PK, dans SQL brut,
avec arguments, auteur, outil, niveau N3, statut exécuté et détails exacts. Le
`motif_demande` propre à cette capture doit être exactement vide, comme le défaut
SQL laissé par l'INSERT canonique. Aucun blanc n'est assimilé à cette valeur.
La projection publique masquée d'approbations n'est pas une source de preuve.

`documents_affaire_traces` contient un payload fermé à 11 clés : `version_schema=1`,
`type_entree=document_trace_liee`, `operation`, `affaire_id`, `document_ref`,
`mutation_ref`, `auteur`, `intention`, `horodatage_appareil_declare`, `horodatage`,
`trace`. Le sceau ajoute seulement `ligne_id` et `precedent_ligne_id`, calculés par
`encodage.empreinte` sans modifier l'enum historique ni appeler `Registre.ajouter`.
Aucun corps, extrait, titre ou référence à soi-même n'est incorporé dans ce payload.
L'intention associe appareil, clé, outil exact et empreinte de la commande originale.
La trace contient les deux PK et les trois heures SQL originales ; les heures
APP/J ne sont pas supposées égales à la réception du document.

Chaque paire appareil/clé, mutation, APP.id et J.id est unique dans les liaisons.
L'unicité du seul couple APP/J serait insuffisante : les tests préservent le rouge
d'une substitution APP1/J2 entre deux intentions de même corps et heure.

## Confirmation et quotas

Le succès public est la frame entière `{ok:true,resultat:{accepte:true,resultat:ACK},
rejoue:bool}`. L'ACK pur fermé à dix clés ne contient aucun corps/extrait. La réponse
persistée du claim ne porte pas le flag `rejoue`.

Une reprise confirme sa propre version, même après v2 ou retrait, sans refaire le
CAS frais. Elle conserve appareil/clé, empreinte, heure originale et auteur, relit
la liaison, le document et les deux lignes SQL originales. Un claim manquant,
négatif, malformé ou ambigu ne peut produire de refus certain : la confirmation
reste inconnue. Le rôle SQL, le corpus autorisé et le mode sont courants avant
restitution. Un changement du corps ou de l'heure ne devient pas une autre intention.

Le quota est un entier strict positif injecté, sans maximum imposé 6000/5400.
Un quota inférieur à 40 ferme techniquement avant claim. Les deux frames `rejoue`
false et true sont mesurées exactement selon le JSON public pur existant (espacé,
UTF8, caractères). La reprise peut rester inconnue si le quota courant ne permet
plus la confirmation. Aucune frame partielle ni artefact n'est produit. Une
projection ou limite postappend défaillante échappe au SAVEPOINT et annule tout.

Des budgets SQL raw distincts du quota public bornent les octets UTF8 reçus :

| Champ SQL | Maximum |
|---|---:|
| claim.reponse | 8 KiB |
| APP.arguments | 16 KiB |
| APP.resultat | 512 octets |
| APP.motif_demande | 512 octets, puis égalité exacte au texte vide |
| J.details | 4 KiB |
| appareil/clé (metadata SQL) | 512 octets chacun |
| outil/action/motif | 512 octets |
| auteur/département | 256 octets |
| rôle | 128 octets |
| heure SQL/déclarée | 160 octets |
| APP.id/cible J | 48 octets |
| hash claim | 64 octets |

Les metadata statut claim/APP et niveau sont respectivement bornées à 96/64/16
octets avant comparaison exacte. `attestation` et `ticket_cible_hash` doivent être
NULL dans la trace nommée. Un CASE SQLite masque tous les champs sélectionnés si
un type ou budget échoue ; le payload n'est pas retourné puis décodé à moitié.
Ces limites couvrent les modèles fermés : body 2000 points (au plus 12000 caractères
échappés en JSON), titre 120 et les autres références/metadata. Elles ne sont pas
une garantie de coût du planner, d'allocation du moteur SQL ou de RSS maximal.

Les metadata claim outil/hash/heure/statut sont contrôlées avant décodage et avant
lecture positive des documents. Le JSON du cache et des preuves APP/J refuse les
clés dupliquées et constantes non finies ; le codec canonique reste réutilisé après
ce garde, sans changement global.

## Erreurs, qualification et limites

`ErreurTransactionDocumentaire` est une `RuntimeError` avec code/detail constants
et `issue=inconnue`. Ses suffixes fermés sont CONNEXION-INVALIDE, DIALECTE-NON-ADMIS,
AUTORITE-INVALIDE, MODE-NON-ADMIS, FORME-INVALIDE, AFFAIRE-INCONNUE, REGISTRE-INVALIDE,
QUOTA-DEPASSE, PRECONDITION-REFUSEE, CONFIRMATION-INCONNUE et PANNE-TRANSACTION.
Aucun argument, texte documentaire ou détail SQL n'est inclus. Toute erreur sort du
SAVEPOINT appelant ; aucun négatif n'est finalisé, aucune APP/J d'échec volontaire
n'est créée par ce chemin interne. La traduction HTTP/stdio sera une phase ultérieure.

Les oracles comparent toutes les tables réellement présentes avant/après, les quatre
tables d'effet frais, les coupures après claim/document/APPJ/liaison/quota/finalisation,
les limites raw à cap−1/cap/cap+1, les JSON physiques ambigus, le listener SQL zéro
INSERT claim à quota 40 et taille de frame−1, deux connexions écrivaines,
la collision d'acquisition, les rôles et modes retirés et la reprise après fermeture
et réouverture du moteur. Une réouverture SQL locale n'est pas un redémarrage Node/Python.
PG, Core, Gateway, HTTPMCP, scopes serveur, téléphone, frontend, fidélité métier du
texte, effacement des copies APP et publication restent non qualifiés ici.

L'oracle de collision après préflight simule des lectures initiales anciennes des
documents/liaisons puis laisse réellement l'INSERT rencontrer la PK durable : le
candidat calculé est abandonné, la preuve OWN relue et aucun append tenté. C'est
une seam contrôlée, distincte des deux tests de concurrence réellement sérialisés
par BEGIN IMMEDIATE. La correction d'ordre préclaim est tracée en r2 ; les preuves
et sources r1 restent historiques.

La correction GEL3 ajoute seulement la sélection raw bornée et la comparaison
exacte de `APP.motif_demande` ; l'INSERT, son défaut schema et tous les chemins
historiques restent inchangés. Les corruptions SQL non vides, espaces seuls et
513 octets sont conservées RED puis GREEN, avec absence de décodage d'arguments
APP lorsque la borne raw est invalide. Les paquets GEL2 et avis modèles restent
leurs snapshots historiques, sans réattribution des nouvelles preuves.
