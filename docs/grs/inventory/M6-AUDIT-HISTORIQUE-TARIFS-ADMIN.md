# M6 / CRM-14 — historique des tarifs : audit et contrat avant code

Source auditée : `1fe5f4c6249a8e31e6ef5f6fb735714969a51c2a`. Statut PARTIAL.
Aucun historique navigable n’est livré par l’audit; import courriel reste une exigence distincte.

## Objectif et pourquoi

La secrétaire doit retrouver les versions de prix d’un matériau et d’un fournisseur, comprendre
la dernière écriture et voir quelle référence documentaire a été déclarée. Une nouvelle version
ne doit pas réévaluer une soumission passée ou cacher un tarif illisible en réutilisant le précédent.

## Existant réel, données et intégrations

`livre_prix.py` conserve un journal append-only par fournisseur. Le DERNIER ÉCRIT du couple exact
fait foi; `date_effet` est une information commerciale déclarée, jamais l’axe de tri ou une date
de réception. Le livre accepte historiquement unité absente et devise non CAD. Il ne porte ni
horodatage serveur ni chaîne de hash métier. Ses métadonnées SQL et les réceptions de saisie sont
des sources distinctes; ne pas inventer une heure à partir de la date commerciale.

`tarif_soumission.selectionner_tarif` ferme les clés et vérifie devise CAD, unité exacte, date
non future et montant représentable. Cette fonction sélectionne un coût pour une soumission;
elle n’est pas un historique. `prix_console.py` prépare/confirme un tarif avec CAS/réception/
audit et référence M10. Son helper `_livre` borne les rangs mais vise l’écriture, pas un lecteur
paginé. `tarifs_ui.py` permet la saisie comparée; son alias catalogue désigne précisément
`catalogue_materiaux_ui.py`, pas catalogue.py/catalogue_ui.py. Les fiches fournisseurs et matériaux
existent; aucun contact ou tarif officiel trouvé ailleurs n’est inventé ou remplacé.

M10 conserve des références vérifiables, pas une copie de prix/coordonnées. M3 garde ses coûts
sélectionnés historiques. Cet historique ne déclenche aucune écriture M3/M5/M8/M10.

## Décision minimale et architecture

Fondation pure propriétaire `m6_material_control/historique_prix.py`, puis raccord SQL privé/T0/
console dans une tranche suivante. Le lecteur pur reçoit la liste complète de paires rang SQL/
entrée, vérifie continuité et schéma, réutilise la validation d’entrée du livre sans effet, puis
filtre par couple exact. Rangs croissants, versions du couple à partir de 1; « dernière écriture »
signifie seulement dernière ligne du livre, pas prix utilisable ou document authentifié.

Ne pas convertir une unité ou une devise. Afficher les valeurs source; unité absente reste
explicitement non documentée. Le prix est formaté par Decimal depuis la représentation canonique
stockée, sans arrondi. Un montant positif hors de la capacité de présentation (64 caractères)
est signalé non représentable, sans zéro ni reprise du précédent. Une date non ISO historique
reste déclarée et signalée; aucune éligibilité temporelle n’est déduite. `source_document` est
SOURCE_DECLAREE, jamais vérifiée par sa seule présence; absence = FALLBACK_PRICE_BOOK.

Les clés inattendues, identités ambiguës, prix booléen/non fini/négatif et structures corrompues
font refuser la source entière, même sur une autre page. Le lecteur ne répare pas le livre.
Chaque ligne porte rang et empreinte de son entrée originale; le snapshot et le curseur sont
hachés. Ces hashes détectent des modifications relues, sans authentifier une base réécrite.

Pagination liée au snapshot entier et au couple, maximum 50 versions par page, 10 000 sources,
8 Mio UTF-8 avant copie et 64 Kio en sortie. Continuer exige le curseur exact; page terminale
vide distincte de couple sans tarif. Retour indépendant des entrées, sans mutation des arguments.

## Fichiers, routes, workflows et permissions prévus

Cette première tranche touche seulement le domaine pur et ses tests. Pas de nouvelle route,
outil, droit, table ou connexion. Raccord futur : capture SQLite canonique bornée avant décodage,
projection indépendante comparée au vrai T0 privé M6, admin SQL/session et origine console non MCP,
recapture livre/fiches avant restitution puis après rendu, HTML échappé/no-store/CSP borné.
La route devra partir du matériau exact et d’un fournisseur explicite, sans choix automatique.
L’interface distinguera les noms actuels des références historiques et n’exposera aucun contact.

Workflow futur : choisir matériau/fournisseur → capturer sources → valider → paginer historique
→ afficher provenance et avertissements. Aucun changement de définition de prix, achat ou envoi.

## Risques, tests, gates et suites

Tests avant code : écriture tardive à date plus ancienne, deux fournisseurs/plusieurs matériaux,
absence de tarif, unité manquante, USD sans conversion, référence/fallback, source périmée ou
curseur d’un autre couple, page terminale, corruption hors page, types/rangs/quotas, copies,
petit prix exact et entier immense non représentable. Réutiliser tests livre/sélection existants,
sans relancer les anciennes cohortes CRM/M4 ou modèles. QA privée, Source RO et réseau refusé.

Gates Nathan : aucun nouveau gate pour la fondation réversible; confirmations d’achats, envoi
fournisseur, connexion externe, droits et finance gardent les limites de la session. Ni réception
courriel, extraction PDF, synchronisation automatique, navigateur, PostgreSQL, mobile ou M6
complet ne sont prouvés par ce travail. Prochaine étape après fondation : port privé SQL borné,
puis GET admin et tests réels. Statut global PARTIAL, aucune publication anticipée durant CI.


## Fondation propriétaire qualifiée localement

`historique_prix.lire` reçoit les paires rang/entrée complètes. Le filtre de couple exact et les
versions suivent l’ordre d’écriture; une date plus ancienne écrite ensuite reste la dernière
écriture. La validation du livre existant s’exécute sur une liste privée, sans effet. Les bornes
comptes/octets précèdent la copie; toute la source est vérifiée avant pagination. L’enveloppe et
chaque page conservent hashes de snapshot/couple/entrée, pas de timestamp fictif ou preuve externe.

Montant Decimal sans arrondi depuis le nombre source, USD conservé sans conversion, unité absente
non héritée du catalogue et date non ISO explicitement déclarée. Montants hors présentation : None
avec PRIX_NON_REPRESENTABLE, jamais zéro ou montant précédent. La dernière ligne peut ainsi être
non représentable; le lecteur ne la remplace pas par son prédécesseur. Coordonnées supplémentaires,
type/prix/rang corrompus refusent la source, y compris hors de la page demandée.

`price-history-pure-v2` : **85 PASS, 0 FAIL/SKIP, 0,81 s**, dont 23 nouveaux tests et les 62
régressions livre/sélection/unité. Ruff et catalogue natif303/177 passent, aucun outil ajouté.
Les refus de lint initiaux et le rouge réel module absent sont conservés. Revue indépendante
statique : aucun constat concret, aucune exécution du relecteur. Preuve privée :
`PRICE-HISTORY-PURE-LOCAL-QUALIFIED.json`. Ancien livre et sélecteur inchangés.

**PARTIAL — fondation pure seulement.** Aucun port SQL privé, route GET, écran, droit ou source
connectée ajouté par cette tranche. Les preuves de saisie existantes ne deviennent pas des preuves
d’historique navigable. Suite précise : capture canonique bornée avant décodage, outil T0 console
seulement, droits inchangés, projection indépendante/recapture/source-session-admin, puis UI privée
par matériau/fournisseur explicites. Import de listes par courriel, achats et M6 complet restent
ouverts. Pas de publication anticipée tant que la CI parent n’est pas terminale.
