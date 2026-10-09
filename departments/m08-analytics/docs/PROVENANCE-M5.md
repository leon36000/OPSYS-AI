# Provenance des publications M5 reçues par M8

`m8_lire_provenance_m5_appareil` est une lecture T0/N0, admin, de portée globale.
Ses quatre arguments fermés et obligatoires sont `perimetre`, `wct_id`, `decalage` et
`limite`. `cash_global` exige `wct_id: null` ; `rentabilite_wct` exige le WCT exact.
Les indices sont des entiers stricts : décalage 0 à 10 000, limite 1 à 8. Un décalage
au-delà des publications existantes donne une page vide, sans déplacement implicite.
La vue exécutive historique et son accès restent inchangés.

La façade exige une identité ambiante de source `appareil`, un rôle `admin` et la
connexion canonique de la transaction. Elle relit en SQL la personne active et son
rôle avant les copies métier. Le corps ne peut fournir aucune identité, autorité,
date, appareil, ticket ou mode. Python fait confiance à l'adaptateur MCP interne
pour cette source ; cette garde ne constitue pas une authentification cryptographique
DEVICE autonome. Le Core et le Socle appliquent leurs admissions supplémentaires.

## Copies et diagnostic

Deux helpers Socle copient, dans la même connexion admise, les publications du type
M5 choisi et leurs reçus M8, puis le registre M8 correspondant. Les publications et
reçus sont décodés ; les rangs et dates SQL des faits sont conservés. Les empreintes
SHA-256 sont calculées sur les copies : elles ne sont pas des hashes natifs de chaîne.
Une nouvelle lecture observe de nouvelles copies, sans cache ni promesse de snapshot
immuable. La charge publiée complète est validée au catalogue réel avant projection.

Le domaine `provenance_m5.py` n'importe ni SQL, ni `opsys`, ni configuration ; il ne
calcule aucun montant, âge ou mesure financière. Il réutilise les projections pures
existantes de cash et de rentabilité. Ses index sont temporaires à chaque lecture.

Le cash est lié par ID exact seulement si l'ID du bus correspond à l'écho de charge,
si un unique fait persiste cet ID et la projection complète de M5, et si le reçu M8
`traite` porte un résumé cohérent. Un écho seul ne prouve aucune réception.
La rentabilité ne persiste pas l'ID d'événement : une projection correspondante
reste `CORRESPONDANCE_DE_PROJECTION`, jamais une liaison par ID. Une séquence
historique absente reste inconnue. Les versions et flags historiques absents ne
sont pas remplacés par des valeurs déduites. Plusieurs publications pour la même
clé historique de réception WCT/séquence rendent le lien ambigu.

La publication courante se détermine par séquence ; pour la rentabilité, seulement
au sein d'un devis. Plusieurs devis pour un WCT rendent la sélection globale
ambiguë, sans préférer un devis. Les rangs SQL ne sont pas des indices de page et
ne servent pas à choisir la publication courante.

Le résumé du reçu est fermé à huit champs. Les montants, mesures, résultats bruts,
erreurs libres du bus et données personnelles ne sont pas retournés. L'horodatage
de réception n'étant pas persisté, il reste `null`. Une date SQL SQLite sans fuseau
est explicitement `non_persiste` ; aucune UTC n'est ajoutée. Une absence de fait ou
publication est une absence dans ce corpus, jamais un zéro financier ni une preuve
de complétude de l'entreprise. Les obligations préparatoires M5 sont exclues.

## Bornes et refus

Le plafond de 10 000 porte sur la somme des publications, reçus et faits copiés,
avant leur validation métier et avant filtrage WCT ou pagination. Les copies et
décodages Socle précèdent ce comptage : ce plafond ne borne pas leur allocation.
Les valeurs JSON et identifiants sont stricts ; les booléens ne sont pas des entiers.
Les IDs bus/reçu sont bornés à 128 points et les identifiants métier à 256.

La taille porte sur l'enveloppe complète `ok/resultat/accepte/resultat`, avec le
JSON réel `ensure_ascii=False`, et sur le minimum de 5 400 caractères et du quota
Socle courant. La page peut contenir moins de lignes que demandé. Une première
ligne qui ne tient pas provoque un refus, sans ligne partielle ni artefact. Le Socle
nommé conserve aussi les refus sans donnée lorsque leur constante dépasse un quota
absurde ; il ne doit jamais créer d'ARTEFACTS pour ce lecteur T0.

Un refus métier est un unique COUPLE `accepte: false, verdict` dans `resultat`, avec
un code `REJ-M8-PROVENANCE-*` et un détail constant. Les admissions transport du
Socle restent distinctes. Un codec corrompu ne devient pas une projection réparée.
Aucune lecture de ce parcours ne réclame une clé idempotente, ne répartit le bus,
ne répare un registre et ne publie un événement.

## Qualification et limites

Les tests du département utilisent des charges fictives validées au catalogue,
le vrai bus, les consommateurs existants et SQLite. Ils vérifient les 49 tables
réelles (dont `alembic_version`), les reçus, les rangs, le redémarrage du stockage,
les erreurs de codec, les quotas et les droits SQL. Les identités sont injectées
explicitement : ces tests ne démontrent ni Gateway/HTTP authentifié, ni PostgreSQL,
ni téléphone, ni interface mobile. Les captures du producteur ont leur provenance
SQL séparée des futurs consommateurs et de toute future campagne Native.
