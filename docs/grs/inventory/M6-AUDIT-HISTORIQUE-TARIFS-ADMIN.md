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


## Contrat SQL/T0 arrêté avant code

1. Ajouter historique_prix_console.py : capturer(cnx) exige la connexion courante SQLite,
   compte les lignes et SUM(length(CAST(maillon AS BLOB))) de livre_prix avant décodage,
   bornes du domaine 10 000/8 Mio; copier_maillons_avec_metadonnees après ces gardes.
   Le pur reçoit [(rang réel, maillon)] et vérifie aussi la continuité. Ne pas utiliser
   _livre de prix_console : son refus >=10 000 vise l’écriture et il ne pré-compte pas
   les octets bruts avant la copie. Aucun nouveau registre ou cache.
2. Un T0 m6_lire_historique_prix_console, paramètres fermés : materiau_id,
   fournisseur_id (texte exact 1..200), debut0..10000, limite1..50 et
   source_attendue null ou64hex requis quanddebut>0. Pas de source injectée,
   mutation_id, devise/unité de remplacement ou date de sélection dans les arguments.
3. Réutiliser catalogue_console._autoriser avant capture, avant recapture et après :
   admin SQL actif, identité source console, origine console, MCP absent, réception
   serveur liée à console:<auteur>, SQLite. Les autres chemins ne gagnent aucun droit.
4. Résultat pur borné via catalogue_console._borner (enveloppe et quota contextuel).
   Retourner distinctement le hash du snapshot SQL/métadonnées de cette requête;
   source/source_snapshot purs couvrent contenu du livre et couple exact. Le curseur
   ne prétend pas dater ou signer le contenu. La vue ne présente aucun timestamp SQL
   ou fournisseur courant dans cette tranche; ne pas confondre date_effet et réception.
   Recapturer le snapshot SQL complet après projection, refuser toute différence même
   de métadonnées pendant l’appel. Ne jamais remplacer une ancienne entrée.
5. Raccorder outil au catalogue retourné par prix_console.outils (appel délégué au
   nouveau module) et sa liste NOMS; ajouter le nom dans les DEUX fermetures précoces
   de src/opsys/capacites.py et dans le dispatch _executer_catalogue_m6 de metier.py.
   roles_appareil absent : aucun grant appareil. Native devrait304 outils/177déclarés;
   vérifier plutôt que supposer. Après executer_atomique, seulement pour ce lecteur,
   vérifier à nouveau session expire et admin SQL par memoire_chantier._admin dans
   la connexion courante avant retour. L’_autoriser natif ne connaît pas Session.
   Garder les autres opérations inchangées. Étendre docs/architecture/ROLES.md.
6. Tests rouges : nom/T0 manquant, vrai dispatcher inconnu. Réutiliser les fixtures
   tests/test_console_prix_m6.py (c.catalogue, c.executer et sources). Ajouter deux prix
   via le VRAI writer console avec CAS/réceptions privées, puis lire par vrai T0 et
   dispatcher; distinguer prix/date inversée et relire après libération SQL.
   Comparer au pur sur snapshot indépendant; aucune table modifiée par lecture/refus.
   Cas : curseur périmé après autre fournisseur; agent/appareil/MCP même nominaladmin;
   factory interdite avant admission générique avec/sansprofil; fauxadmin/expiry;
   pas de source substituée; quota avant décodage; corruption horspage; métadonnées
   changées pendant projection; dernière capture révoquant admin; enveloppe trop petite.
7. Exécuter uniquement nouvelles phases privées exclusives, avec les regressions ciblées
   du livre/tarif et port privé existant. Réutiliser la preuve pure85sansaddition des
   populations. Une erreur de fixture/lint ne devient pas un bug produit.

Suite UI, après ce lecteur qualifié : GET privé /crm/materiaux/{materiau_id}/tarifs/historique
avec fournisseur explicite et pages/source; nom actuel clairement distinct du livre, pas de
contacts copiés. Garder cnx jusqu’au rendu, comparaison indépendante vraiT0, recapture et
session/admin finale, HTML128Kio/no-store/CSP, querymasquée. Pas de fausse preuve HTTP tirée
des tests du T0. Import courriel/extraction annuelle restent une tranche de production séparée.

Aucune production, achat, paiement, export sensible, connexion de source, droits, merge,
forcepush, modèles payés ou nouveau runtime autorisé par ce contrat. Source demeure propre.



Contrôle complémentaire de quota : la nouvelle lecture doit respecter une borne de sortie
plus petite déjà présente dans le contexte du dispatcher, jamais la remplacer par 64 Kio.
Ce contrôle concerne seulement le nouveau lecteur; les anciennes opérations restent inchangées.
La première attente de test « 14 » était incorrecte : le vrai writer stocke 14.0, que la fondation
affiche exactement « 14.0 ». Cette attente est corrigée sans changer la représentation source.


## Lecteur privé SQL/T0 qualifié localement

`m6_lire_historique_prix_console` est maintenant disponible par le dispatcher de console privé,
avec paires matériau/fournisseur et pagination explicites. `historique_prix_console.capturer`
compte lignes/octets SQL avant décodage, puis le pur valide les rangs et les données. Le résultat
ajoute source_sql, empreinte des métadonnées de CET appel, distincte des hashes de contenu/curseur.
Deux captures encadrent la projection; mutation de métadonnées ou de contenu pendant la lecture
est refusée. L’autorité SQL est revérifiée avant/après la recapture et la session après le T0.

Les deux chemins génériques ferment avant factory et normalisation. Identité console, admin SQL,
origine console, réception serveur et absence de MCP requis. La source ne peut pas être injectée;
aucune intention de mutation admise. Pas de rôle appareil ni droit de compte ajouté. La borne
d’une sortie déjà présente dans le contexte est conservée : le rouge réel followup-v1 montrait
que le dispatcher la remplaçait par 64 Kio; le nouveau lecteur prend désormais leur minimum.
Les autres opérations gardent leur comportement. Natif : **304 outils, 177 déclarés**.

`price-history-port-v1` : 177 PASS/1 FAIL, ce dernier étant une attente de représentation de test
incorrecte (« 14 » au lieu du 14.0 réellement stocké par le writer). Le contrôle corrigé passe
isolément; cette reprise prouve aussi réouverture SQL et égalité avec le pur. La même reprise
reproduit séparément le défaut de quota avant correction. `price-history-port-v2` : **40 PASS,
0 FAIL/SKIP, 17,94 s**, dont 19 nouveaux contrôles et les 21 anciens cas de ports tarifs.
Les 116 tests de portées, 23 purs et autres cas compatibles du premier lot sont réutilisés :
les populations se recoupent et ne sont jamais additionnées. Ruff et vérificateur natif passent.
Revue statique indépendante du raccord : aucun constat concret; aucune exécution du relecteur.

Prix créés par vrai writer privé avec préparation/CAS/réception, puis vrai T0 et dispatcher,
lecture après réouverture, source périmée après autre couple, corruption hors page, quotas avant
décodage, origine/MCP, faux admin/expiration tardive, connexion étrangère, factory interdite et
révocation à la dernière capture sont contrôlés. Tables inchangées par lectures/refus, hors
mutations de contrôle injectées. Source RO Landlock, homes/tmp privés avant imports, réseau refusé,
CPU1/mémoire1Gio/swap0/PIDs96. Preuve : `PRICE-HISTORY-PORT-LOCAL-QUALIFIED.json`.

**PARTIAL — lecteur privé SQLite/T0 qualifié, aucun nouvel écran HTTP.** Le fixture client utilisé
par les tests ne constitue pas un parcours de consultation GET. Suite : GET admin et navigation
matériau/fournisseur, comparaison indépendante et recapture après rendu, source des noms actuels
séparée du livre, champs déclaratifs échappés et pagination fiable. Import courriel, navigateur,
PostgreSQL, mobile, production et M6 complet restent ouverts. Pas d’achat, paiement, changement de
prix officiel externe, export, connexion, droits ou publication anticipée durant CI parent.

## Contrat GET admin — audit sur 0a5dccdf avant implémentation

Le domaine et le T0 privé sont qualifiés localement; aucun GET n’existe à cette révision.
Ajouter `historique_tarifs_ui.py` : GET `/crm/materiaux/{materiau_id}/tarifs/historique`,
raccord depuis le routeur des tarifs et lien sur toute fiche matériau, même inactive/historique.
Lecture seule, admin SQL/session courants, connexion canonique gardée jusqu’après rendu.

Choix explicite fournisseur : 25 premiers noms ACTUELS du répertoire, complétés par saisie
exacte d’identifiant et lien au répertoire complet. Aucun choix automatique, contact copié,
profil inventé ou prétention de liste exhaustive. Avant décodage fournisseurs : compte/8 Mio
SQL, rangs continus, validation propriétaire et projection minimale comparée au vrai T0 privé.
Capturer/recapturer les métadonnées fournisseurs. Pour le livre : capture propriétaire,
projection pure indépendante puis vrai T0 via dispatcher privé, égalité JSON typée, quota
combiné 64 Kio. Recapturer les deux sources et l’autorité avant et après rendu HTML (128 Kio).

Paramètres fermés/uniques : fournisseur_id, debut, limite, source_attendue. Identifiant matériau
canonique 100 caractères; identifiant fournisseur propriétaire exact sans normalisation.
Continuer exige le curseur du couple/snapshot entier. Périmé : 409 avec invitation à recommencer;
corruption/incohérence/changement en cours : 503 sans ancien prix. Auth : 403, saisie : 400.
Pas de conversion devise/unité ni revalorisation de devis. Date commerciale distincte de rang;
document échappé comme texte, jamais ouvert. Unité inconnue et prix non représentable restent
signalés, jamais zéro. Noms actuels explicitement séparés de la provenance des prix.

Tests réels GET avant implémentation : deux écritures natives, pagination et source périmée,
permissions, corruption hors page, réponse T0 substituée, source/autorité changée après rendu,
quotas avant décodage et sortie, liens/échappement, POST 405, paramètres fermés, masquage intégral
de query Uvicorn y compris slash final. Les preuves pures/T0 inchangées sont réutilisées;
aucune installation, connexion externe, import courriel ou extension de droit.


## GET privé qualifié localement — résultat et limites

`historique_tarifs_ui.py` raccordé par `tarifs_ui.py`, liens dans
`catalogue_materiaux_ui.py`, query privée masquée dans `journaux_http.py`.
Le GET utilise réellement le dispatcher privé, compare le résultat à la projection sur
snapshot SQL indépendant, puis relit sources/autorité après rendu. Seules les suggestions de
noms actuels sont proposées : `m6_lister_fournisseurs_console`, compatible avec les noms
historiques longs, et projection propriétaire sur la page25. Le précédent choix de lecteur
tarif refusait un nom legacy201 même sur un autre couple : constat indépendant, vrai rouge,
correction et régression conservés. Aucun changement du lecteur tarif d’écriture existant.

QA finale privée Linux : 61 PASS (29 nouveaux cas GET et 32 régressions fournisseurs), lint et
vérification native 304 outils /177 déclarés réussis. La cohorte précédente 57 PASS (23 nouveaux
cas +ports prix/catalogue) et les preuves pures/T0 inchangées sont réutilisées sans addition.
Historique des rouges : 404 GET, query non masquée, nom201 bloquant; les refus de lint restent
distincts des bugs produit. Tests réels via TestClient/SQLite/T0, pas un navigateur visuel.

Source lecture seule pendant QA, réseau interdit, CPU1/1Gio/96tâches/600s et homes privés.
Le GET n’ajoute aucun droit, outil, table, événement mémoire, prix ou écriture métier.
Une référence documentaire reste du texte échappé. Un prix historique sans fiche fournisseur
actuelle reste consultable par identifiant explicite. Noms longs valides préservés sous les
quotas globaux; aucun contact n’est copié dans le résultat affiché.

Gates inchangés : pas de vrai courriel/import, achat/commande/finance, données réelles, nouvelle
connexion ou publication publique. Mobile/PostgreSQL/navigateur et automatisation des listes
courriel non qualifiés. M6/CRM-14 restent PARTIAL; prochaine capacité : préparation gouvernée
d’un import de liste fournisseur en données fictives, audit du flux existant avant tout code.
