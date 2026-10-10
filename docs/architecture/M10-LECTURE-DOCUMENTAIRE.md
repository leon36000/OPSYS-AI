# Lecture documentaire interne d'instance — SQLite

`opsys.documents_affaire_lecture_appareil.lire_document_m10(cnx, operation,
commande, *, quota, mode_manifeste)` fournit les lectures `lister` et `lire`.
L'appelant possède déjà la connexion et la transaction. Le backend n'ouvre pas
de factory, transaction de repli, SAVEPOINT, bootstrap ou migration ; il ne fait
ni commit ni écriture. PostgreSQL reste hors du pilote qualifié ici.

L'ordre d'admission est explicite : connexion exactement canonique et ouverte en
transaction SQLite ; opération/commande plain fermées et quota entier positif ;
identité ambiante `IdentiteAppelante` de source appareil et rôle admin ; confirmation
SQL via `approbations.signataire_valide` de la personne encore active portant ce rôle ;
mode effectif SQL ou manifeste, limité aux trois modes de lecture. Aucune source
métier n'est copiée avant ces contrôles. L'admission ombre-only du writer n'est pas
réutilisée pour les lectures. Cette admission ne certifie pas cryptographiquement
un DEVICE : elle dépend de l'adaptateur fiable qui fixe le contexte d'appel.

L'affaire doit être connue du même corpus autorisé que le writer documentaire.
Le helper readonly protégé `_situation` est réutilisé, avec ses copies bornées
des registres `evenements` et `affaires`, validation de chaîne, exclusion des
projections financières/confidentielles et contrôle des consolidations déjà
persistées. Une consolidation n'est jamais produite au chargement. La présence
d'un document seule ne crée pas une affaire connue. Aucune référence financière,
origine, heure de lecture ou Meta n'est fabriquée.

La copie de `documents_affaire` passe par `copier_registre_m10`, inchangé : namespace
fixe, rangs/dates réels, contrôle physique SQL CASE des plafonds avant codec,
copies indépendantes. Le domaine pur valide ensuite la chaîne et ses liens avant
projection, y compris les lignes hors page. L'indice d'une version reste son indice
original dans le registre ; le décalage de page n'est pas un rang source.

Le backend crée le contexte pur T0 exactement à cinq clés : `affaire_id`, `auteur`,
`situation`, `mode`, `quota`. Il rend l'enveloppe entière
`{ok: true, resultat: {accepte: true, resultat: DTO}}`, sans `rejoue`. L'index courant
à sept clés contient des lignes fermées à seize clés, sans corps ; le détail
réutilise le DTO historique de treize/quatorze clés. Les préconditions du dernier
dépôt et de la dernière activation ne sont pas l'activation historique de la ligne.

Le quota réel est mesuré sur cette enveloppe entière avec le codec JSON du domaine,
`ensure_ascii=False`, séparateurs Python par défaut, en caractères JSON. Les octets
UTF-8 capturés ont un SHA séparé. Il n'y a ni plafond arbitraire ajouté au quota
injecté, ni raccourcissement, corps caché, fragment ou repli ARTEFACT. Un détail trop
grand est refusé même si son index de métadonnées tient. Le domaine/backend ne
garantit pas que toute erreur de protocole puisse tenir dans un quota minuscule.

Les erreurs ont le type `ErreurLectureDocumentaire(RuntimeError)` et deux attributs
`code`, `detail` constants. Préfixe `REJ-M10-LECTURE-`, suffixes fermés :
`CONNEXION-INVALIDE`, `DIALECTE-NON-ADMIS`, `AUTORITE-INVALIDE`, `MODE-NON-ADMIS`,
`FORME-INVALIDE`, `AFFAIRE-INCONNUE`, `REGISTRE-INVALIDE`, `REFERENCE-INVALIDE`,
`QUOTA-DEPASSE`. Aucune chaîne SQL, exception source ou donnée partielle n'est
interpolée ; les traductions utilisent `from None`. Un refus n'est jamais enregistré
comme claim, APP ou journal. La future route Cap/MCP établira sa propre frontière
de protocole avant d'exposer un refus nominal.

Les tests SQLite fictifs comparent le recensement dynamique de toutes les tables
avant/après chaque fenêtre importante de lecture ou refus. Ils couvrent notamment
retrait/rétablissement SQL, modes, références/codec, quota exact, copies et relecture
après dispose/reopen. Les écritures de préparation utilisent les APIs existantes
hors de ces fenêtres. Dispose/reopen ne prouve pas un redémarrage de processus.
Il n'y a ici ni outil de mutation nouveau, rôle étendu, effet APP/J/claim/bus,
qualification transport DEVICE, téléphone, client ou prétention de complétude M10.
