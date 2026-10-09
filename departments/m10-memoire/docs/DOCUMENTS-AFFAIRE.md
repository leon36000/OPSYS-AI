# Documents internes par affaire — domaine pur du pilote

Cette phase fournit seulement `m10_memoire.documents_affaire`. Elle ne déclare aucun
outil RPC, n'ouvre aucune connexion, n'écrit aucun registre et ne livre ni droits
DEVICE/SQL, ni ingestion, ni UI. Les trois noms dans `OUTILS` sont des identifiants
proposés pour l'association d'intention, pas des outils présents dans la factory.
Le contrat Root gouverne les adaptations ultérieures.

## Sources et références

Le texte est un `str` UTF-8 valide exact : aucune normalisation NFC, suppression de
blancs ou modification de CR/LF/TAB. Les tailles et le SHA portent sur ce texte et
ses octets. Le marquage `INTERNAL` est obligatoire ; aucune conversion de taxonomie
M03, développement ou finance M5. Le contenu admis n'est pas déclaré vrai.

Quatre payloads fermés sont proposés : `document_depose`,
`document_version_deposee`, `document_version_activee`, `document_retire`.
Le premier ne contient **pas** `document_ref`. Son hash est calculé puis la
référence `{registre: documents_affaire, index, ligne_id}` est projetée ; les
versions suivantes portent cette référence. Aucun hash n'est incorporé dans le
payload qui le produit. Chaque maillon porte la preuve d'intention, l'auteur
injecté, l'heure déclarée originale et l'heure de réception fournie.

La chaîne réutilise l'encodage canonique et la validation de `Registre` existants.
L'enum de `Registre.ajouter` n'est pas étendu ici : les préparateurs construisent
seulement un candidat scellé, indépendant des entrées reçues. La validation
recoupe aussi l'empreinte JSON compacte des arguments reconstitués depuis le
payload. Une chaîne réempreintée dont le corps/titre ne correspond plus à
l'intention est refusée. Le serializer de l'empreinte trie les clés, préserve
Unicode et emploie les séparateurs compacts, comme la convention Socle actuelle ;
son appairage réel avec le futur RPC reste à qualifier. Les erreurs de
sérialisation ou d'encodage de cette empreinte deviennent un refus fermé, aussi
bien pour une commande que pour un maillon reçu. Un entier démesuré dans un corps
mal typé ne laisse donc pas sortir une exception JSON lors d'un appel Python pur.
Une référence vers une ligne non dictionnaire ou sans `ligne_id` est également
refusée avant toute indexation de son contenu.

## États et citations

Une version déposée mais jamais activée est `DEPOSEE_NON_ACTIVEE` : son corps est
lisible pour revue, mais elle n'est pas citable. Une version visée par la dernière
activation est `COURANTE`. Une version déjà activée puis remplacée est
`HISTORIQUE_NON_COURANTE` et demeure citable avant retrait. Un nouveau dépôt seul
ne remplace pas la version actuellement activée.

La citation porte la propre référence de source et une `activation_ref` qui vise
réellement cette version dans la chaîne. Ses offsets `[debut_octet, fin_octet)`
sont des offsets UTF-8 ; la tranche doit décoder strictement et correspondre
exactement à l'extrait, sans `strip` ou comparaison normalisée. Une frontière
coupant un caractère, un SHA, une référence ou un extrait contradictoire donne
un refus constant, jamais un fragment partiel ni la version suivante.

Le CAS frais vise la référence exacte de la dernière activation, pas le SHA du
corps. Une séquence A→B→A ne rend donc pas un ancien jeton d'activation valable.
Le retrait d'accès est définitif pour ce premier pilote : tous les corps et
extraits sont fermés, y compris historiques ; seules les métadonnées bornées
restent accessibles sous un futur garde admin courant. Les anciennes sources et
les preuves ne sont pas supprimées. Un nouvel ajout ou une activation du même
document retiré est refusé.

## Contextes purs, sans autorité inventée

Le contexte de lecture comporte exactement :
`affaire_id`, `auteur`, `situation`, `mode`, `quota`.
Aucune intention/clé ou heure Meta n'est fabriquée pour T0.
Le contexte writer/rejeu comporte ces cinq clés plus `intention`,
`horodatage_appareil_declare`, `horodatage`.

L'auteur a la forme admin/appareil ; sa forme n'établit ni SQL courant ni
l'authenticité cryptographique DEVICE. La situation injectée reprend exactement
`amont.situation` : `connue`, `origine_recue`, `origine`, `verdict`, avec les
origines et verdicts fermés. Une affaire inconnue est refusée ; une affaire connue
sans origine reçue reste explicitement dans cet état, sans inférence depuis son ID.
Les arguments de commande ne contiennent aucune autorité ni heure de serveur.

Les writers **et leur rejeu** exigent le mode courant `ombre`. Les lectures
acceptent les trois modes fermés déclarés. Avant un vrai appel futur, Root devra
revérifier rôle, portée, personne, appareil et mode avant sources/claim/cache et
restitution ; aucun test RAM de cette phase ne prouve ces gardes réelles.

## Reprise et incertitude

L'acquittement est une projection de son propre maillon ; il ne contient ni
corps, ni statut « courant ». Le rejeu positif compare la paire appareil/clé,
l'outil, l'empreinte des arguments, l'heure déclarée originale, l'auteur et la
preuve unique, puis toute la réponse de claim avec comparaison typée stricte.
La réponse de claim modélisée est le préfixe `ok/resultat` sans flag transport
`rejoue` ; la future façade doit qualifier cette forme exacte.

Après v2 ou après retrait, le rejeu propre de v1 peut confirmer uniquement son
ancienne mutation, sans refaire le CAS ni réactiver ni exposer le corps. L'heure
de réception du nouvel appel ne remplace pas celle du maillon. Une négation de
cache, même marquée `refus_metier`, reste confirmation inconnue en l'absence de
preuve négative propre. Un même corps/instant avec une autre clé n'est jamais
une association. Un cache mal formé, contradictoire ou sans preuve ne produit
pas de nouvel effet ; la future intention durable doit conserver la même clé.
Une paire appareil/clé déjà présente est signalée comme confirmation inconnue
avant de refuser un nouveau candidat au plafond de 512 maillons : ce plafond ne
prouve pas l'absence d'un effet antérieur. Le rejeu positif de sa propre ancienne
activation reste possible sur une chaîne pleine, sans refaire un CAS frais.

## Bornes et quotas

Plafonds locaux du pilote : 2000 points de code / 8000 octets UTF-8 par source,
120 points pour le titre, 1024 octets par extrait, huit documents par affaire,
huit versions par document et 512 maillons pour ce registre. Les bornes locales
appareil/clé de 256 points ne modifient pas le contrat Meta historique du Socle.
Les horodatages fournis sont des chaînes avec fuseau, au plus 40 caractères ;
l'heure déclarée est conservée exactement, notamment `.000`.

Le quota est obligatoire, positif et injecté. Le défaut global de référence est
**6000 caractères**, pas une réserve implicite de 5900 ou 5400. La mesure est
`len(json.dumps(frame, ensure_ascii=False, allow_nan=False))` avec séparateurs
usuels, sur l'enveloppe entière. L'empreinte des arguments utilise séparément les
séparateurs compacts ; les deux unités ne sont pas confondues. Les deux valeurs
de `rejoue` sont contrôlées avant de rendre un candidat et à sa confirmation.

Une entrée autorisée ne garantit pas que toute lecture tiendra : les échappements
JSON peuvent dépasser le quota. Le domaine lève alors un refus constant sans
omission, troncature ou ARTEFACT. L'oracle quota 40 ne prétend pas que la future
trame minimale de refus tiendra elle-même dans 40 ; ce framing de transport sera
publié et qualifié séparément. Le nombre de lignes et les allocations des copies
SQL ne sont pas qualifiés par une limite portant sur une liste RAM déjà reçue.

## Copies durables et étapes restantes

Le corps append-only et la future copie dans `APP.arguments` restent durables.
APP est une trace, pas une source citable. Cette phase ne promet aucune purge,
aucun chiffrement ni effacement des sauvegardes. Le corps devra rester hors du
journal, de l'ACK/cache, des motifs libres, d'une demande APP en attente et des
ARTEFACTS. Ces canaris et la trace réelle sont des contrôles de phase ultérieure.

Restent à qualifier : adaptateur de la transaction canonique d'instance,
snapshots/rang attendu, claim et trace APP/J dans le même rollback, garde nommée
admin DEVICE/affaire/mode avant effets et rejeu, quotas post-trace, concurrence,
restart, SQLite et PG d'instance séparément, HTTP/Core Native puis CI du commit
exact et consommateur mobile. Aucun PG mémoire indépendant, provider ou dossier/
recherche existant n'est modifié. Les 104 preuves absentes, le supplément et les
conversations absentes ne deviennent pas disponibles grâce à ce prototype.

## Oracles de la contre-revue pure

Les citations manuelles couvrent le vecteur `41c3a9f09f98800d0a5a` :
`Aé😀\r\nZ`, six points de code et dix octets. Les tranches `[2,7)` et `[1,6)`
coupent respectivement é et 😀 ; même un extrait forgé avec U+FFFD est refusé.
Le décodage strict est conservé, sans réparation par remplacement.

Le premier maillon possède un vecteur attendu littéral issu d'un oracle séparé
qui n'importe pas l'encodeur testé : payload sans référence propre, préfixes de
longueur de la convention canonique existante et précédent `None`. Son SHA est
`e5d3a33e38968a83bf23b00efeaaeee8f7724108f33ba8092b3ad452e84450cb`.
Ces oracles qualifient seulement le domaine RAM, pas l'écriture SQL ou la liaison
DEVICE/APP. Les anciennes qualifications et les erreurs d'oracle sont conservées
avec leurs dispositions, sans requalification rétroactive.
