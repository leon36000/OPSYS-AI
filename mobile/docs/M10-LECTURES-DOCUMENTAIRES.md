# Lectures documentaires du client M10

Le client lit les pages courantes et les versions avec les deux outils T0 nommés.
L'index transporte sept champs et des lignes de seize champs, sans corps. Le
détail transporte treize champs après retrait, quatorze avec le corps avant
retrait. Les enveloppes positives restent le couple fermé de deux puis deux
champs ; aucune Meta de mutation, clé d'intention, date de fraîcheur locale ou
valeur de cache n'est ajoutée.

`documentsAffaireLecture.ts` valide les références, les liens de statut et les
arguments demandés. Les références du dernier dépôt et de la dernière activation
restent distinctes de l'activation historique de chaque version. Une version v2
déposée peut donc laisser v1 courante. Le corps reçu conserve ses caractères,
CRLF et Unicode sans NFC : le nombre de points, les octets UTF-8 et le SHA-256
sont vérifiés, sans remplacer de surrogate isolé. Cette vérification ne prouve
ni le contenu physique ni un hash de chaîne absent du DTO. L'auteur historique
peut être différent du lecteur admin courant.

Les deux builders exigent trois arguments. Seul le chargeur choisit les valeurs
initiales de pagination 0 et 1 ; le RPC les transporte toujours explicitement.
Les objets sont copiés sans appeler de getter avant toute attente réseau.
`documentsAffaireLectureService.ts` expose le chargeur injectable et les deux
bindings UI. Il capture la session admin et sa destination, puis contrôle son
époque et le réseau après chaque attente. Un aller-retour A→B→A invalide la
réponse ancienne. Hors ligne, aucun corps ni cache n'est servi ; une réponse
illisible ne devient pas une donnée partielle.

Les tests embarquent les octets exacts des huit frames Cap/SQLite fictives de
`CAPTURES-CAP-SQL-T0-r1.json` (SHA-256
`1100ad5fb553b43acce4b5edd3be4cbb7047ef77680b95712836c4eb08f80828`).
Leur identité admin est injectée : ils ne qualifient pas HTTP, DEVICE opaque,
Gateway, PostgreSQL ou téléphone. Les contre-exemples modifiés portent le label
RAM et ne constituent pas de nouvelles captures SQL. Le conseil Opus/Sonnet/
Haiku reste un avis statique ; les tests du client et la disposition Root sont
des preuves séparées. La navigation et le contrôleur ont un autre propriétaire.
