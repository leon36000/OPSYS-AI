# R44a — marque canonique dans l’usine de chantier

État au 2026-10-02 : implémentation locale en cours de qualification ROOT. Ce guide
décrit ce lot ; les campagnes antérieures R16/R19 ne prouvaient pas le raccord
console marque → usine. R44b, édition humaine des textes, reste séparée.

## Parcours

Le propriétaire actif ouvre `/marketing/marque`, renseigne les cinq champs Brand
v1 et, si connus, le site HTTPS, les garanties déclarées, mots-clics, mentions et
horaires suggérés. Ces déclarations ne sont pas vérifiées auprès d’un tiers.
Un WCT reçu avec consentement marketing alimente ensuite `/marketing/calendrier` :
Facebook, Instagram, fiche Google, vidéo courte et demande privée de témoignage.
Ce sont cinq brouillons, jamais cinq publications.

La matière de chantier et chaque nouvelle proposition portent `marque_source` :
source, révision et SHA-256 du profil JSON fini. La console montre cette preuve et
sa fraîcheur. Le propriétaire décide du texte, puis du créneau, puis demande la
remise du paquet manuel. Les décisions et exports nouveaux gardent leur preuve.
Les fonctions et journaux existants sont réutilisés ; aucun outil ni catalogue
appareil supplémentaire n’est créé.

## Priorité et erreurs

[Le lecteur](../../../departments/m07-marketing/src/m7_marketing/brand/registre.py)
utilise entièrement la version canonique `brand_profiles` quand des lignes DB
existent. Révisions, forme, options consommées, empreinte et lien des nouvelles
lignes sont vérifiés. Une ligne canonique invalide refuse, sans repli YAML.
Les anciennes lignes Brand v1 valides restent inchangées ; leur avertissement
signale l’absence d’empreinte historique persistée. Une chaîne recalculée par un
auteur qui contrôle toute la base ne constitue pas la menace couverte.

Seulement sans ligne DB, un YAML valide et configuré peut alimenter l’usine sous
`source=yaml_legacy`, révision inconnue et avertissement. Aucun profil n’est copié
automatiquement vers la base. Placeholder, fichier absent, YAML malformé ou erreur
de lecture produisent un diagnostic fermé, sans identité commerciale inventée.
Les erreurs du codec canonique sont aussi des refus métier.

La lecture canonique borne le nombre de révisions, leur longueur SQL et le volume
de caractères avant décodage ; le profil normalisé est borné à 64 Kio UTF-8. La
page de contenus réserve une enveloppe autour du budget de lignes de 5 400
caractères, garde le texte complet et refuse une première ligne trop volumineuse.
La marque courante n’est répétée qu’une fois par page.

## Mise à jour et reprise explicites

Le formulaire lie la modification à `revision_attendue`. L’API JSON accepte les
mêmes champs métier et cette révision séparée ; aucun éditeur de JSON technique
n’est demandé à l’humain. Une modification existante sans révision attendue ou
avec une révision périmée refuse. Les options omises sont conservées depuis le
seul snapshot serveur correspondant, dans la transaction ; aucune fusion avec
YAML n’a lieu. Pour vider une liste via API, fournir explicitement `[]` ; une
option omise, y compris un champ formulaire vide, est conservée. La suppression
du site par ce formulaire n’est pas fournie dans R44a.

La révision attendue entre dans l’empreinte du reçu console via `preuve_commande`
interne, sans changer les arguments publics de l’outil. Même clé/profil/preuve :
reçu historique ; même clé avec une autre preuve : conflit. Deux écritures réelles
SQLite depuis la même révision ne créent qu’une nouvelle révision.

Une marque changée, une autre révision même à profil identique, ou une ancienne
proposition sans preuve empêchent une nouvelle approbation/remise/export. Le
consentement retiré et le rôle révoqué restent bloquants. Un rejet motivé peut
conserver sa fonction de refus sans qualifier l’ancienne marque.

« Reproposer avec la marque courante » est une mutation explicite : nouvelles
révisions non approuvées, nouveaux identifiants, historique et anciennes décisions
intacts. Un GET et un rejeu de consommation du bus ne renouvellent pas les
brouillons. Les revues médias restent distinctes de l’approbation du texte et
sont liées au snapshot WCT entier, aux blobs vérifiés et à la révision de marque.

## Portée de la preuve

La console revalide la source avant son cache ; un reçu d’export après retrait ou
changement de marque ne remet plus le paquet. Les appels frais de retrait restent
tracés par les demandes humaines en échec du socle existant.

Le dispatcher MCP générique et certains tickets cibles peuvent rejouer un ancien
reçu avant le service : cela ne lance ni nouvelle revue ni nouvel export, mais
cette route n’offre pas le refus actualisé de la console. Le comportement est
documenté et testé ; un hook SDK relève d’un lot séparé. Aucun changement de
Capacites/SDK n’est compris ici.

La qualification prévue utilise SQLite et HTTP TestClient réels, avec personnes,
marques et WCT explicitement fictifs ; elle n’atteste pas une publication, OAuth,
modèle, fournisseur, apprentissage M10, VPS ou atomicité concurrente PostgreSQL.
Les départements, permissions propriétaire/admin et catalogue appareil restent
dans leur périmètre existant.
