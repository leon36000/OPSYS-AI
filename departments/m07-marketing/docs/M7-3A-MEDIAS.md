# M7.3a — Préparation privée des médias de chantier

Statut : **PARTIEL**, intégré localement le 1er octobre 2026 à 16:51:59 UTC (promotion root R4). Cette tranche accepte des photos JPEG/PNG réelles
liées aux WCT déjà reçus, consigne une préparation fournie et attestée par un humain, puis permet une
revue du propriétaire et une remise manuelle privée. Elle n'effectue aucune publication, transformation,
modération automatisée ou analyse des pixels.

## Parcours et données

Le service recapture le WCT M4 complet depuis le registre reçu et épingle son SHA, la révision et le
texte M7 courant, le profil de marque, les références de photos vérifiées dans le CAS et le consentement
marketing courant. Un retrait de consentement ou une modification de ces sources ferme l'ancienne revue.
Avant une première remise, une nouvelle préparation peut ouvrir une nouvelle révision; l'historique reste
append-only et les anciennes décisions cessent d'être courantes.

Le propriétaire transmet une variante JPEG/PNG, jusqu'à 10 MiB, puis atteste sa préparation. OPSYS
vérifie les octets réels, la signature JPEG/PNG, les blocs et le SHA-256; il ne décode pas l'image et ne
retire ni ne valide EXIF, visages, plaques ou adresses. Le snapshot ne contient pas le créneau éditorial; ce dernier est contrôlé séparément à la remise et à la lecture des octets remis. Une décision N3 du propriétaire atteste une revue
humaine complète du dossier. Le pliage vérifie le SHA du préfixe exact visé par la décision, sa révision,
son rôle et la provenance d'approbation.

La remise exige simultanément le texte courant approuvé, dont le SHA-256 correspond aux octets UTF-8 du
texte réellement enregistré et dont le contrôle courant passe, un créneau courant approuvé, le consentement
actif, chaque photo du WCT représentée par une variante préparée et une revue média courante approuvée.
Elle réutilise l'export texte M7 existant et lui lie un identifiant média distinct; son contenu historique
reste intact. Une nouvelle clé de mutation peut réémettre le même dossier remis au même créneau sans écrire
un maillon ni un export supplémentaire. Le dossier reste figé après cette remise. La route privée renvoie
ensuite les octets vérifiés seulement au propriétaire, si le texte approuvé demeure le texte courant.

## Accès et limites

La métadonnée du dossier est accessible par la console propriétaire sur
`GET /api/marketing/calendrier/medias/{contenu_id}`. Elle expose les références, SHA, type et taille des
photos, sans retourner la charge WCT complète ni des octets. Les médias binaires passent seulement par
`GET /marketing/calendrier/medias/{contenu_id}?reference=…&mode=apercu|remise`. L'import privé utilise un
multipart en flux borné à 10 MiB + 32 KiB, un fichier, huit champs et 1 KiB par champ textuel; CSRF et
propriétaire sont vérifiés aux frontières de la console. Le verrou d'exécution épingle Starlette 1.7.0;
son parseur ferme ses fichiers temporaires en cas d'exception pendant le traitement multipart. La limite
de flux reste testée sans `Content-Length`; une mise à jour du parseur doit préserver cette fermeture.

Les écritures M7.3a refusent PostgreSQL, faute de qualification de la concurrence pour ce nouveau
registre. Aucun outil agent/MCP, rôle mobile, grant d'appareil, intégration de plateforme ou export public
n'est ajouté. Les photos sources et variantes vivent dans le CAS existant; le journal `dossiers_medias`
réutilise les maillons OPSYS et conserve préparation, reprise d'epoch, décision et remise. Les SHA
détectent une altération locale non rehashée; ils ne protègent pas contre un opérateur privilégié qui
réécrit toute la chaîne.

## Vérification ciblée

Les tests ciblés couvrent la lecture CAS et ses corruptions, les formes malformées du pliage, la liaison
de revue au préfixe, double revue, nouvelle epoch sans effacer l'historique, gel après remise, réémission
du même créneau sans nouvel append, altération du texte avant remise/lecture binaire, fuite WCT,
préparation multipart, approbations texte/créneau/média et lecture des octets remis. Ces tests ciblés seuls ne constituent pas une qualification complète. La campagne intégrée post-promotion est décrite ci-dessous; aucun parcours PostgreSQL, navigateur réel, désidentification d’image ou remise à une plateforme externe n’est qualifié.

## Clôture intégrée root — R18

La campagne intégrée root du 1er octobre 2026, exécutée de **16:52:48 à 16:54:58 UTC**, passe **1 377 cas**, sans échec, erreur ni skip, en **128,406 s JUnit** : **1 038 M7**, **248 console**, **82 fichiers/stockage/idempotence** et **9 E2E chantier par MCP sur SQLite**. Les sept cas du pliage média sont inclus dans M7 et les dix-neuf cas de console média dans la console; aucun de ces sous-comptes ne s’ajoute au total. Deux cas PostgreSQL ont été désélectionnés par `-k not postgresql`, ce ne sont pas des skips. L’ensemble surveillé de **1 066 chemins sources sélectionnés** est identique avant/après; il ne constitue pas une fermeture de tout le dépôt. Les dix-neuf cas média comprennent des tests HTTP, un test direct du parseur ASGI et un oracle de garde substituée; ils ne sont pas dix-neuf parcours complets de bout en bout.

Le pliage refuse les références CAS étrangères : `prepared_refs` est exactement l’ensemble trié et dédupliqué des variantes du dossier. Le cas de deux photos sources partageant la même variante conserve les deux mappings et une seule référence de fichier; cette déduplication est démontrée par test pur, pas par un parcours HTTP multi-photo. La remise contrôle le SHA des octets UTF-8 du texte enregistré avant tout append. Sa réémission, même avec une nouvelle clé de mutation, reprend les identifiants existants sans écrire un export ou maillon supplémentaire.

Preuves : [résultat](../../../docs/research/R20-2026-10-01/preuves/r18-preuves--m73a-marketing-console-integres-root-r1-2026-10-01-resultat-json-aab3d9c2e7.gz) · [JUnit](../../../docs/research/R20-2026-10-01/preuves/r18-preuves--m73a-marketing-console-integres-root-r1-2026-10-01-xml-d4c76cecab.gz) · [journal](../../../docs/research/R20-2026-10-01/preuves/r18-preuves--m73a-marketing-console-integres-root-r1-2026-10-01-log-1c43560d7a.gz) · [lecture indépendante](../../../docs/research/R20-2026-10-01/preuves/r18-m73a-cloture-independante-root-r1--verification-json-061d6a4c0f.gz) · [promotion R4](../../../docs/research/R20-2026-10-01/preuves/r18-m73a-integration-root-r4--resultat-json-f24b78b5dc.gz) · [Ruff](../../../docs/research/R20-2026-10-01/preuves/r18-preuves--m73a-ruff-root-r1-2026-10-01-resultat-json-8bb466cbf1.gz) · [catalogue](../../../docs/research/R20-2026-10-01/preuves/r18-preuves--m73a-verifier-root-r1-2026-10-01-resultat-json-5e77c4ab23.gz). Les SHA vérifiés par le lecteur indépendant correspondent aux onze chemins au jalon de code, avant la présente actualisation documentaire. Ruff a contrôlé dix fichiers Python; la commande catalogue confirme 10 départements, 207 outils et 116 outils déclarés aux appareils. Les campagnes antérieures scratch (72, 91 et 19 cas) se recouvrent et ne s’ajoutent pas à 1 377. Les défauts démontrés et corrections R1–R4 restent archivés; le nom « green » d’un fichier n’est pas à lui seul une preuve de succès.

La tranche demeure **PARTIELLE** : aucune publication ou connexion fournisseur, transformation automatique des images, analyse des pixels, suppression EXIF, surface mobile M7 dédiée, essai navigateur réel ou qualification VPS. Les attestations de préparation et de revue restent humaines. Les nouvelles écritures médias refusent PostgreSQL; aucune concurrence PostgreSQL pour ce registre n’est qualifiée. Le catalogue reste à **10 départements, 207 outils et 116 outils déclarés aux appareils**; aucun outil MCP n’a été ajouté.
