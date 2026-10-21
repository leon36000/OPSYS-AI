# Autorité de lecture des sessions client — R33

Le serveur distingue explicitement `client_session` et `global` dans le fragment généré
`opsys/memoire-autorites.json` version 1. Les départements exposés sur un canal public ou configurés
avec `affaire_par_session` sont classés client ; les autres restent globaux. Les profils d'agents
héritent du mode de leur département. Ce lot ne permet donc pas encore deux modes indépendants
pour un agent M1 interne et un agent M1 client du même département.

Les URLs générées utilisent `/mcp/v1/<département>`. Les anciennes URLs `/mcp/<département>` et
l'agrégat `/mcp` restent montés pour compatibilité des autres outils, mais ne servent pas de lecture
client implicite. Une classification absente, invalide ou supprimée refuse la lecture sur le transport
public. Il faut régénérer les fragments avec la CLI `opsys-metier openclaw configurer` et les options
de contexte déjà utilisées par l'instance ; ne pas modifier seulement l'URL dans un ancien fragment.

Pour `opsys_memoire_rechercher`, Core prend la session réellement routée et le snapshot des arguments
finaux. Il demande au serveur privé de contexte un ticket opaque de lecture, distinct des neuf tickets
de mutation C02 et des grants CFO. Ce serveur exige le bearer de contexte distinct ; son outil privé
`opsys_contexte_creer_ticket_memoire` n'est pas au catalogue du modèle. Aucun client ou lead fourni
par le modèle ne constitue l'autorité. Python résout la liaison M10 active, vérifie sa chaîne complète,
puis la référence `client_associe` du lead M2 existant et la chaîne M2. Une référence absente refuse ;
aucun `client:<lead>` n'est fabriqué.

Le ticket porte une empreinte des arguments, de la classification, et l'identifiant exact de liaison.
Seule son empreinte est conservée dans `liaisons_tickets`, avec un purpose de lecture distinct,
une durée de 120 secondes et aucun résultat personnel en cache. Le magasin canonique d'autorité
doit être SQLite ; un backend canonique différent refuse l'émission/consommation. Le magasin RAG
reste PostgreSQL. Les lectures globales autorisées des départements restent multi-clients.

Avant les embeddings et le SQL, Python vérifie l'autorité. L'omission de `sujet` impose quand même
le client M2 ; un autre sujet est refusé. La clause SQL exige des sujets présents et tous inclus dans
l'autorité : un fragment A+B ou sans sujet métier ne passe pas. Les procédures globales forment une
branche séparée, seulement publiques/internes et sans sujet `client:` ou `chantier:`. Une demande
`portees=["procedures"]` autorisée par le manifeste peut employer cette branche sans affaire liée,
avec recherche locale plein texte et aucun embedding. Les citations documentaires existantes restent
vérifiées et liées à leur version/source.

Après la lecture, la classification, l'expiration, la liaison et la référence client sont relues avant
consommation. Un lien révoqué/remplacé, une référence modifiée ou un ticket déjà consommé refuse la
sortie. Un rejeu ne renvoie aucun ancien résultat personnel. Les appareils restent fermés à cet outil,
y compris avec un rôle administrateur ; les procédures ne contournent pas cette fermeture.

La transaction SQLite sérialise le contrôle canonique et la consommation. Elle ne rend pas atomiques
la base PostgreSQL, le fichier de classification et SQLite entre eux. Ce lot ne qualifie ni isolation
SaaS multitenant, ni modèle réel, ni Gateway/provider de production. Les fonctions internes Python
hors transport conservent leur contrat départemental historique ; elles ne sont pas une entrée client.

Les preuves ciblées R33 comprennent SQLite/M2/M10, MCP HTTP officiel en ASGI, transport Core natif
avec serveurs stdio fictifs, et PostgreSQL/pgvector jetable réel en RAM. Les données, auteurs et clés
des fixtures sont fictifs. Le graphe TypeScript large interrompu avec exit 137 demeure une limite
distincte ; les tests Core ne sont pas présentés comme sa réussite.
