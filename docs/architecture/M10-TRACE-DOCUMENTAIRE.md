# Capture technique et restitution publique M10

Cette étape ne livre ni writer documentaire, claim, liaison métier, autorité
SQL/DEVICE, mode ombre, RPC ou quota. Les trois noms restent proposés pour les
writers futurs. La capture ne valide que leur corrélation technique donnée.

`approbations.tracer_validation_documentaire_m10(cnx, departement, outil,
arguments, *, niveau, signataire, reponse, appareil)` rend une dataclass frozen
`TraceDocumentaireM10(approbation_id, journal_id)`. Elle exige la connexion
canonique courante, ouverte, dans sa transaction **et un SAVEPOINT déjà ouvert
par l'appelant**, sans créer de factory, transaction ou SAVEPOINT de repli.
La corrélation est `m10-memoire`, N3, l'un des trois noms ci-dessous, un
`IdentiteAppelante` admin/source appareil avec personne et appareil non vides.
Ces valeurs injectées ne prouvent pas une permission SQL ou un jeton DEVICE.

- `m10_deposer_version_document_appareil`
- `m10_activer_version_document_appareil`
- `m10_retirer_document_appareil`

Les PK sont capturées directement depuis `inserted_primary_key` : APP est une
chaîne plain de douze caractères égale à l'identifiant inséré ; J est un entier
plain positif au plus `2**63-1`. Le helper privé
`etat._journaliser_documentaire_m10` partage l'INSERT historique mais ne fait
aucun SELECT/scan journal, `max(id)` ou rapprochement par corps/horodatage. Il ne
fabrique pas une unicité globale du journal. La capture seule n'est pas une
preuve durable de liaison ; une future façade devra conserver/relire les PK
raw dans la même transaction métier.

`CaptureTraceDocumentaireErreur` est un `RuntimeError` indépendant des erreurs
métier `ValueError`/`TypeError`/`KeyError`. Une panne de capture après APP/J doit
**sortir du SAVEPOINT appelant**, qui annule les écritures. Aucun refus métier
certain n'est retourné après append. Le helper ne commit rien lui-même.
Les retours historiques `journaliser -> None` et
`tracer_validation_au_depart -> str12`, leurs colonnes et JSON, sont conservés ;
la validation nouvelle des PK n'est pas exécutée sur ces voies historiques.

## Projection publique statique

`arguments_documentaires_publics(outil, arguments)` est appliqué dans
`_demande_depuis_ligne` après décodage JSON. Pour les seuls trois noms ci-dessus,
les champs plats `corps` et `extrait`, s'ils existent et ne sont pas null, sont
remplacés par `[contenu documentaire masqué]`. Une valeur null reste null ; les
clés ne sont pas supprimées. Le titre demeure une métadonnée visible. La copie
est indépendante, même pour les structures imbriquées restantes.

Cette règle ne dépend ni de l'index des outils ni de l'activation/retrait du
document : elle s'applique avant et après retrait, même à une fixture APP en
attente. Les arguments SQL, empreinte et résultat SQL restent inchangés.
`decider` lit les arguments raw SQL, pas cette projection. Les anciens outils
conservent leur restitution. Aucun chiffrement ou purge n'est prétendu ; la
constante historique de géolocalisation n'est pas réutilisée. Le masque ne
couvre pas des champs arbitraires, ni du texte volontairement mis dans titre,
motif ou attestation. Les futures preuves doivent relire les colonnes raw par
PK, sans utiliser `lire` comme source probante.

## Qualification et limites

Les tests utilisent SQLite et des identités/arguments fictifs. Ils exercent les
INSERT réels et annulations du SAVEPOINT, la projection liste/détail/dashboard/
file, APPapp avec rôle SQL fictif, et les routes API/HTML via ASGI TestClient.
Ce n'est pas un téléphone, un jeton DEVICE, Core, HTTPMCP ou un writer complet.
Le retrait documentaire reste une condition de fixture, pas un retrait métier
exécuté. Aucune qualification PostgreSQL n'est livrée ici. Quotas avant claim,
après trace et replay, liaison document/APP/J, modes et autorité courante
appartiennent aux phases suivantes. L'absence de contenu dans ces restitutions
ne prouve pas son effacement de la base ou d'une copie durable.

### Fermeture de la projection sur corruption APP

Pour les trois noms uniquement, les arguments issus de `json.loads` doivent
être un dictionnaire plain avant la copie. Un tableau, une chaîne, null ou un
scalaire persistés sont refusés avec `ValueError("projection documentaire
indisponible")`, sans écho ni objet inventé. Une panne de copie produit la même
erreur constante avec contexte supprimé. Il s'agit d'une erreur de restitution
publique, distincte de l'erreur RuntimeError de capture/postappend. Les futures
preuves backend continuent de relire le SQL raw par PK et ne passent pas par ce
helper. La restitution historique étrangère reste inchangée, y compris un
JSON profond valide : aucun nouveau deepcopy/validateur ne lui est imposé.
Les limitations des champs arbitraires, du titre, du résultat ou des attestations
restent celles du masque statique décrit plus haut. Cette fermeture ne prouve
ni effacement du corps ni incident RPC/writer ; le rouge est un APP SQL fictif
corrompu puis relu par les voies liste/détail.
