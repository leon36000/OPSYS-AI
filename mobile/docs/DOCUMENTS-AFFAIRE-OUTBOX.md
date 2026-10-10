# Intentions documentaires M10 — raccord client opt-in

Ce raccord prépare trois mutations DEVICE admin par affaire : `document_m10_depot`,
`document_m10_activation`, `document_m10_retrait`. Il réutilise le SDK et le dépôt sortant,
sans écran de dépôt/activation/retrait ni nouvel outil de lecture documentaire.

`creerMutationDocumentM10(operation, commande, genererId, horloge, destination)` fige une
commande fermée 6/4/4 et `_document_m10_local` (personne, appareil_id, url_base). Le compartiment
local n'est pas un argument d'autorité RPC ; le jeton n'y est pas enregistré. Corps Unicode exact,
1..2000 points / 8000 octets ; corps composé d'espaces admis, titre non vide selon le strip Python,
120 points. Références documents_affaire/index 0..511/ligne_id SHA256 hex. INTERNAL au dépôt,
RETRAIT_ACCES au retrait. Les getters, cycles, prototypes non JSON, surrogates isolés,
clés supplémentaires et entiers unsafe sont refusés avant la création.

`argumentsRpcDocumentM10` relit et copie la charge originale. Il lie type/opération, affaire et
cible technique `document-m10:<affaire_id>`, propriétaire et destination. UUID et heure initiale
avec décalage sont les métadonnées du SDK lors de chaque reprise ; aucune milliseconde forcée,
aucun nouveau UUID. `verifierDestinationDocumentM10` compare personne/appareil/URL d'origine.
Le service vérifie une session admin actuelle, son jeton et la génération ; le vidangeur
revérifie session, payload et ordre après les attentes avant un nouveau RPC.

Les trois descripteurs partagent `documents-m10`, une série par affaire. Une inconnue, une
quarantaine ou un ordre illisible garde les opérations suivantes bloquées. Tous les refus M10,
y compris les enveloppes négatives et les erreurs HTTP incertaines, conservent la même intention
avec recul ; un refus d'appareil arrête la passe. L'option `echecPermanentBloqueSerie` est vraie
uniquement pour les trois types M10 : un état permanent importé ne devient pas une preuve
sans effet. Les descripteurs historiques conservent leur terminalité.

`interpreterDocumentM10` admet seulement la wholeframe fermée
`{ok:true,resultat:{accepte:true,resultat:ACK10},rejoue:boolean}`. ACK10 contient exactement
version_schema, operation, document_ref, reference, version_source, source_sha256, auteur,
intention, horodatage_appareil_declare, horodatage. Auteur admin/appareil/personne, intention
appareil/clé/outil/empreinte et heure déclarée sont liés à l'intention originale. L'empreinte
reprend le JSON compact trié récursivement de Python, chaînes UTF8 exactes, sans normalisation.

Au dépôt initial les trois références sont égales ; sur une version ultérieure document_ref
reste celui de la commande et reference == version_source. Au dépôt le SHA source est celui
des octets du corps. À l'activation, version_source et document_ref sont liés à la commande,
mais source_sha256 n'est vérifiable que structurellement sans corps disponible. Au retrait,
version_source/source_sha256 sont nuls. Aucun contrôle de dernière tête n'invalide un propre
ACK historique après une version suivante ou un retrait.

Le reçu positif admis est persisté séparément de la commande. `validerRecuDocumentM10` valide
ce reçu ACK10 local contre la charge originale ; il ne reconstitue pas une capture transport.
Un statut envoyé avec reçu absent/falsifié ne libère pas la série. Les seules références et
formes client ne prouvent pas le hash du maillon entier, APP/J, l'autorité SQL ou la vérité du
texte. L'autorité actuelle et les preuves de stockage restent au serveur.

Les tests utilisent des oracles SHA issus de l'encodeur Python courant, explicitement RAM,
et des ACK fictifs. Ils exercent SDK/descripteurs/vidangeur, dépôt mémoire et SQL réel via
node:sqlite avec fermeture/réouverture de connexion. Ce n'est pas un restart de processus,
un téléphone ni une qualification du pont natif ExpoSQLite, Gateway, Cap/MCP ou PostgreSQL.
Aucune nouvelle dépendance, migration, activation financière ou lecture documentaire livrée.
