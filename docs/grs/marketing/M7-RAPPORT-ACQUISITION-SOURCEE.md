# Rapport privé d’acquisition observée

Depuis la page CMO, choisissez explicitement les deux dates de la période métier
(366 jours inclusifs maximum). Le rapport privé rapproche les faits M7 reçus de
M2/M3/M5 avec des lectures actuelles par les outils publics des départements.
Aucune campagne, publication, facture ni dépense n’est modifiée.

Les campagnes présentent les associations de leads, devis acceptés et marges M5
publiées observées. Une marge absente reste inconnue. Les dépenses publicitaires
ne sont pas branchées : coût par lead et ROI restent inconnus. L’attribution ne
prouve aucune causalité. Les exclusions et références sont disponibles dans le
GET privé `/api/marketing/cmo/rapport?debut=AAAA-MM-JJ&fin=AAAA-MM-JJ`.

La période filtre les dates métier. Les faits sont ceux disponibles à la lecture,
pas ceux qui étaient connus à la fin de cette période. Ainsi une correction M5
arrivée en octobre avec une complétion de septembre peut modifier le rapport de
septembre. La séquence M5 la plus récente reste l’oracle existant. Le rapport
sépare l’horodatage métier, la dernière insertion SQL en M7 et l’heure serveur de
lecture. `cree_le` SQLite est exprimé en UTC ; PostgreSQL restitue son fuseau.

Le registre M7 historique n’a pas de signature ni de chaîne persistée. Sa lecture
est explicitement `historique_non_scelle`. L’empreinte de lecture SHA-256 lie les
octets du préfixe observé à cette lecture ; elle n’authentifie ni l’ancien
producteur, ni l’intégrité antérieure, ni l’exhaustivité des sources. Aucun fait
ancien n’est réécrit ou scellé après coup.

L’administrateur actif peut consulter M2 et M8. Le propriétaire sans rôle admin
voit ces sources comme non autorisées ; le serveur ne lui invente pas ce rôle.
M7 et M5 conservent leur accès propriétaire console. L’identité et le rôle sont
relus avant chaque source et après composition ; un retrait refuse la réponse
sans montant. Aucune réponse n’est mise en cache. Le navigateur ne choisit ni
outil, ni rôle, ni drapeau financier.

M2 montre seulement le statut courant des leads rencontrés dans les pages lues.
Son item public ne fournit ni UTM ni référence de devis. M8 montre ses contenus
cumulés sans fenêtre de période, avec les dernières dates de faits reçus : on ne
les additionne pas à la cohorte M7. M5 montre le calcul courant des seuls devis
référencés, avec prix provisoire/définitif, manque et fraîcheur de trace ; ce n’est
pas une nouvelle rentabilité recalculée par M7.

La composition est limitée à neuf appels : un M7, deux pages M2 de vingt leads,
deux pages M8, quatre devis M5. Une source illisible ou un curseur incohérent reste
inconnu, sans boucle. Les lecteurs amont peuvent encore parcourir leur historique
entier : le budget borne les appels et le rendu, pas toutes leurs requêtes SQL.
Le JSON complet est limité à 32 Kio UTF-8, cinquante campagnes et cent références
M7 explicites. Chaque élément retiré du rendu est compté ; les quotas ne prouvent
pas une couverture complète. Les identifiants, statuts et montants utiles sont
projetés sans adresses, contacts ni dossiers CRM bruts.
La page HTML entière est également limitée à 32 Kio après échappement. Si elle
dépasse cette borne, elle refuse et propose de consulter le JSON privé borné.

La lecture SQL M7 refuse avant décodage au-delà de 10 000 lignes, 8 Mio UTF-8
cumulés ou 64 Kio par ligne. SQLite mesure le BLOB du texte ; PostgreSQL utilise
`octet_length(convert_to(maillon, 'UTF8'))`. Les autres dialectes refusent. Tous
les faits du préfixe sont validés avant filtrage de période, avec profondeur
seize et 2 048 nœuds par ligne. Les faits normalisés sont JSON ordinaires ; aucune
étiquette du codec n’est restaurée. Leur forme invalide refuse sans charge brute.
Un rang maximum borne le préfixe ; il ne constitue pas un verrou PostgreSQL contre
UPDATE/DELETE. Aucune photographie atomique multidépartement, isolation SaaS ou
authenticité historique universelle n’est promise.

La campagne indépendante ROOT du 2 octobre 2026, de 16:18:09 à 16:19:35 UTC,
passe **1 261 cas**, sans échec, erreur ni skip, en **85,835 s JUnit**. Elle couvre
le département M7 et neuf fichiers de tests console/socle ; les 44 cas ciblés et
les deux fixtures corrigées y sont inclus, sans addition. Les **1 134 chemins
sélectionnés** restent identiques avant/après, dont les huit fichiers du gel R2.
Les sept fichiers Python modifiés passent Ruff dans une commande distincte.

Preuves : [résultat ROOT](/workspace/restructuration-opsys-2026-09-30/preuves/marketing-acquisition-root-r2-20261002-resultat.json),
[JUnit](/workspace/restructuration-opsys-2026-09-30/preuves/marketing-acquisition-root-r2-20261002.xml),
[gel R2](/workspace/restructuration-opsys-2026-10-02/marketing-rapport-acquisition-implementation-r1/gel-final-r2.json)
et [Ruff ciblé](/workspace/restructuration-opsys-2026-10-02/marketing-rapport-acquisition-implementation-r1/ruff-final-r2.log).
Le rouge ROOT précédent (**1 259 passés, deux échecs**) est conservé : deux
fixtures simulaient encore l’ancienne lecture des maillons, sans table SQLite
migrée. Leur raccord à une vraie base temporaire conserve les assertions métier.

Cette qualification est locale sur SQLite et données fictives. La branche SQL
PostgreSQL a été inspectée/compilée, sans exécution PostgreSQL de ce parcours.
Aucun navigateur réel, fournisseur, OAuth, publication ou VPS n’est qualifié.
Le rapport n’est pas un instantané historique à la fin de période ni une
photographie atomique multidépartement. Cette actualisation du guide est
postérieure à la campagne ; son ancienne empreinte est conservée dans le gel.
