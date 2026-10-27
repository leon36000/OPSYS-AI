# Fournisseurs et tarifs → M10 : audit avant raccord

27 octobre 2026, source `04da87660d290ffb294b8a4eaff2f1cbb72b4705`.
Statut : **PARTIAL**, conception du prochain raccord; aucun nouvel événement livré par ce document.

## Objectif et état mesuré

Une modification admin du fournisseur ou du coût matériau doit laisser une référence
durable dans M10, sans recopier coordonnées ou prix dans une mémoire accessible hors M6.
Les formulaires HTTP/SQLite sont qualifiés; leurs ports écrivent journal, audit et reçu.
Ils ne publient pas encore les changements fournisseurs/tarifs vers M10.

Réutiliser `opsys.catalogues_memoire`, l’outbox, le répartiteur et le registre M10
`references_configuration` déjà qualifiés pour modèles, lignes et matériaux. Les événements
d’affaire ne conviennent pas à une fiche fournisseur : aucune affaire artificielle.

## Sources réelles et différences

`fournisseurs.py` garde un journal vivant : création puis mises à jour, fusion dans l’ordre,
no-op si le contenu est identique. Les entrées possèdent `horodatage`, mais ni révision,
ni chaîne de hashes, ni `source_id`. Le hash de fiche courante utilisé par le CAS console
ne désigne pas nécessairement un maillon historique : une ancienne mise à jour partielle
peut fusionner des champs antérieurs. Un consommateur différé doit vérifier la source à
son rang d’origine, même après une correction ultérieure.

`livre_prix.py` écrit des entrées append-only avec `date_effet`; il ne stocke aucun
horodatage de réception serveur. `date_effet` est une date commerciale, pas une date
d’écriture. Le lecteur `tarif_soumission.py` ferme les clés autorisées du maillon : lui
ajouter silencieusement `horodatage` ferait refuser les nouveaux tarifs. Les métadonnées
SQL exposent `cree_le`, dont la copie conserve explicitement la présence ou l’absence de
fuseau. Ajouter UTC à un datetime naïf serait une invention. Le nouveau raccord ne doit
ni modifier le format historique de prix ni transformer une date effective en minuit UTC.

## Décision et tranche minimale

Commencer par **fournisseurs**, dont l’horodatage source existe déjà. Ajouter au propriétaire
M6 une projection pure de référence pour un préfixe de journal borné : rang réel, numéro
de version de la fiche dans ce préfixe, hash déterministe du préfixe validé et horodatage
de l’entrée. Le hash couvre aussi les champs fusionnés : altérer un ancien champ hérité
doit invalider la référence, même si la dernière entrée reste intacte. Conserver les valeurs
historiques acceptées par le domaine, sans leur imposer les nouvelles limites du formulaire.

Le courtier du socle utilisera cette projection du propriétaire pour produire et relire
la référence; M10 reste pur et aucun département n’importe un autre département. Étendre
explicitement les genres fermés du schéma M6 et de M10. Publier seulement après un append
réel du port privé, dans son savepoint source/audit/reçu. Une panne de publication annule
tout. Le reçu exact retourné après une correction ultérieure ne republie rien. Un no-op
ne crée pas de version mémoire. Aucun rattrapage automatique des écritures anciennes.

Le payload garde les six champs existants de référence : fait, genre, rang, version, hash,
horodatage. Aucun nom, identifiant libre, contact, condition fournisseur ou coût. La preuve
de réception doit rester distincte de la publication. Les lecteurs ne gagnent aucun droit.

**Tarifs ensuite**, avec une provenance de réception durable explicite qui ne change pas
le contrat fermé du livre de prix. Cette décision demande un choix de stockage et des tests
sur la transaction complète; le présent audit n’autorise pas un timestamp dérivé arbitraire.
Ce travail est technique et réversible, sans gate humain supplémentaire tant qu’il conserve
les permissions, les données fictives et les limites de la session.

## Preuves requises

- Création puis correction fournisseur par HTTP → deux publications → vrai répartiteur
  → deux références M10 privées, sources relues et chaîne valide après réouverture SQL.
- Livraison différée de la première version après la seconde; rejeu du reçu original et
  second identifiant de livraison sans nouveau maillon.
- Hash/version/rang/horodatage altérés, champ hérité du préfixe corrompu, source absente,
  champ supplémentaire ou chaîne M10 invalide : refus sans mémoire ajoutée.
- Panne outbox : aucun fournisseur, audit ou reçu partiellement validé. No-op, rôle révoqué,
  quota et concurrence gardent les propriétés déjà qualifiées des ports.
- Contacts et prix canaris absents de l’événement et de M10; les anciennes trois familles
  et leurs badges restent fonctionnels. Populations non additionnées.

Fichiers concernés : nouvelle projection pure M6, `fournisseurs_console.py`,
`src/opsys/catalogues_memoire.py`, schéma `m6.catalogue_reference.json`,
`m10_memoire/references_configuration.py`, tests ciblés de cascade et de console.
QA privée habituelle, Source en lecture seule pendant l’exécution. Pas de modèle requis.
M6, M10 et OPSYS restent PARTIAL; import courriel, historique de prix navigable,
PostgreSQL, navigateur natif et mobile ne sont pas qualifiés par cette préparation.

## Réalisation fournisseurs et qualification locale

`references_fournisseurs.projeter` valide les fiches fusionnées de chaque préfixe avec le
domaine historique, puis calcule un hash JSON déterministe couvrant toutes ses entrées.
La version compte les entrées de la fiche concernée, indépendamment du rang global. Les
catégories nombreuses et coordonnées historiques acceptées par M6 restent conservées.
Le courtier lit les rangs SQL réels, refuse un trou et borne la source à 10 000 entrées et
8 Mio avant décodage; la projection pure possède aussi sa borne d’octets. Les écritures
ultérieures ne modifient pas une référence ancienne. Ce hash détecte une incohérence du
contenu relu; ce n’est pas une authentification cryptographique de toute la base.

Le port fournisseur publie seulement s’il a réellement ajouté un maillon. Le schéma M6 et
le registre M10 admettent explicitement `m6_fournisseurs`. Le consommateur revalide le
préfixe par son propriétaire avant de mémoriser la référence en `SENSITIVE`. Les trois
familles précédentes et leurs badges sont conservés. Aucun nouvel outil ni droit appareil.

Le test HTTP initial échouait réellement avant code : zéro publication au lieu de deux
(`supplier-memory-red-v1`). Puis `supplier-memory-v1` : **207 PASS, 0 FAIL/SKIP, 19,98 s**,
avec deux erreurs Ruff dans le seul fichier de tests pur. Ces imports et le nom de variable
ont été corrigés; les sept autres fichiers empreintés n’ont pas changé. Reprise ciblée
`supplier-memory-v2` : **9 PASS, 0 FAIL/SKIP, 0,46 s**, Ruff de tous les fichiers du lot et
vérificateur 297 outils/173 portées PASS. Les neuf cas sont inclus dans les 207, non ajoutés.
Revue statique indépendante du préfixe, rang, atomicité et confidentialité : aucun constat.

Les preuves traversent HTTP → outbox → répartiteur SQL → chaîne M10, après deux versions
déjà écrites puis réouverture SQL. Rejeux sous deux identifiants de livraison, no-op, absence
de backfill, horodatage/version/rang/hash forgés, préfixe hérité altéré, trou SQL et panne
outbox sont contrôlés. Les canaris de coordonnées restent absents des événements et de M10.
Source en lecture seule pendant QA; limites habituelles effectives, commandes/JUnit/reçus
distincts conservés. Ni mémoire sémantique ni badge fournisseur admin revendiqué ici.

La CI du parent publié `04da8766` a signalé une attente de manifeste M10 devenue obsolète :
le tuple du test omettait les deux événements de catalogue déjà déclarés. L’attente exacte
est mise à jour en conservant tous les anciens événements et l’égalité des consommateurs.
`memory-manifest-v1` : cinq tests passent en 0,98 s, Ruff et vérificateur passent. Le rouge
CI reste historique; cette correction locale n’est pas une CI verte transférée au parent.

## Décision de provenance pour les tarifs, avant code

Analyse indépendante puis relecture de `idempotence.reclamer/finaliser` : le champ texte
`MUTATIONS_APPLIQUEES.recu_le` conserve la réception serveur avec son fuseau, à la seconde.
`finaliser` ne la réécrit pas. C’est la source à réutiliser, sans recréer des microsecondes.
Le reçu tarif actuel ne relie toutefois pas une empreinte complète du maillon à cette
réception. Son rang, son montant et son unité ne couvrent pas fournisseur/date/document.

Tranche suivante : registre compagnon M6 privé `receptions_tarifs`, sans migration de table
ni champ ajouté au livre de prix. Lier rang SQL et hash complet du tarif à la clé de mutation,
à l’empreinte des arguments et au texte exact de réception relu. Source, liaison, audit,
finalisation du reçu et outbox partagent le savepoint existant. Lors d’une livraison différée,
relire la mutation exacte, exiger outil tarif, statut `ok`, empreinte, réponse et réception
concordants, puis le maillon original par rang SQL. Absence, doublon ou contradiction refuse.
Les clés de mutation, montants et identifiants libres restent dans M6/socle, hors événement M10.

Réutiliser le patron de reçu borné de `console/fusion_ap_m5_reference.py::_recu`, sans importer
le domaine M5. Garder les tests de rejeu avant nouvelle publication, rollback de chaque étape,
altération du reçu ou de la liaison, concurrence et vieux tarifs sans backfill. Cette décision
ne livre pas encore `receptions_tarifs` ni la mémoire des tarifs. OPSYS reste **PARTIAL**.

## Fondation tarif/réception désormais qualifiée localement

`src/opsys/receptions_tarifs.py` et le port `prix_console.confirmer` écrivent le compagnon
privé dans le savepoint existant. L’heure vient du texte exact `MUTATIONS_APPLIQUEES.recu_le`,
fuseau conservé, précision réelle à la seconde. Aucun champ n’est ajouté au livre de prix.
Le résultat durable finalisé inclut maintenant `tarif_source_sha256`, hash du rang SQL et
du maillon complet. La lecture confronte cette ancre au compagnon, au prix et au reçu final
`ok` : outil, empreinte des arguments, réception, rang, montant, unité, devise et marquage.
Les vieux tarifs sans liaison restent explicitement non prouvés, sans écriture de rattrapage.

Le compagnon est borné à 10 000 lignes/8 Mio; une entrée prix à 8 Kio et une réponse de reçu
à 64 Kio sont bornées avant décodage. Rangs réels, clés fermées, doublons et dates naïves
sont contrôlés. Aucune route ni permission supplémentaire; lecteur interne SQLite seulement.

La revue a trouvé une véritable faiblesse de la première candidate : réécrire le document,
fournisseur ou date du prix, puis recalculer les hashes du seul compagnon, restait accepté
avec un reçu intact. Les trois rouges `tariff-anchor-red-v1` la reproduisent. L’ancre du
hash complet dans le reçu final corrige ce défaut; ces trois cas passent ensuite. Cela
détecte les incohérences contre le reçu durable, sans prétendre authentifier un hôte compromis.

`tariff-receipt-v2` : **87 PASS, 0 FAIL/SKIP, 22,38 s**, une ligne de test trop longue.
Après correction de cette seule ligne, `tariff-receipt-v3` : **24 PASS, 0 FAIL/SKIP, 8,62 s**,
Ruff de tous les fichiers et vérificateur 297/173 PASS. Les deux fichiers produit sont
empreintés identiques entre ces exécutions; les 24 tests sont inclus dans les 87.
La cohorte contient les parcours HTTP tarif et fournisseur → matériau → tarif → devis.
Les reprises gardent le premier reçu après un nouveau prix; prix, compagnon, audit et reçu
s’annulent ensemble après une panne injectée à chacune des trois étapes. Reçus absents,
faux outils/statuts/dates/réponses/types, source modifiée, doublon et substitution de reçu
sont refusés sans écriture. Les anciens rouges baseline/lint restent conservés.

Prochaine tranche : projection M10 de cette provenance démontrée et publication **après**
finalisation du reçu, dans le même savepoint. Le consommateur devra refaire les vérifications
ci-dessus. Aucun événement ni mémoire M10 de tarif n’est encore revendiqué par cette fondation.

## Raccord tarifs → M10 qualifié localement

La projection `receptions_tarifs.projeter` utilise le **rang SQL du compagnon** comme
`source_rang`. `source_revision` est l’ordinal du rang SQL du prix + 1, pas une version
commerciale par fournisseur : il peut commencer à 2 si un prix ancien sans liaison existe.
La source reste le hash de la liaison vérifiée, avec le texte exact de réception serveur.
Prix, coordonnées, clé de mutation et identifiants libres ne passent pas dans la référence.

Le courtier et les genres fermés M6/M10 admettent maintenant `m6_tarifs`. Le port finalise
le reçu **avant** publication, dans le même savepoint. La projection exige déjà un reçu
finalisé valide; une finalisation oubliée refuse la publication et annule toute l’opération.
M10 répète la vérification de la liaison, du prix et du reçu lors d’une livraison différée.
Rejouer la confirmation d’origine retourne son ancien reçu avant ces écritures.

Le test HTTP était rouge avant ce raccord (`tariff-memory-red-v1`, zéro publication au lieu
de deux). Après raccord, `tariff-memory-v1` : **139 PASS, 0 FAIL/SKIP, 29,84 s**, Ruff de tous
les fichiers touchés et vérificateur 297 outils/173 portées PASS. Inclut les régressions de
provenance tarif, références fournisseurs et anciennes familles M3/M6, HTTP tarif, manifeste
et conformité M10/M6. Les populations se recoupent avec les jalons précédents, sans addition.
Revue statique indépendante de l’ordre transactionnel, source/rang/réception : aucun constat.

Le parcours traverse deux confirmations HTTP puis le vrai répartiteur SQL vers la chaîne
M10; il conserve les deux versions après réouverture. Autre ID de livraison, rejeu original,
absence de backfill, source/réception/rang SQL altérés, référence forgée, champ coût injecté,
oubli de finalisation et panne de publication sont vérifiés sans effet partiel. Les canaris
coût, document fournisseur, identité admin et intention sont absents d’outbox/M10.

Statut : références serveur fournisseurs **et** tarifs prouvées sur SQLite. Les badges admin
pour ces deux familles, l’historique de prix navigable et l’import courriel restent ouverts,
ainsi que navigateur natif, PostgreSQL, mobile et consolidation sémantique. Aucun prix reçu
par courriel, achat, paiement ou donnée réelle traité ici. M6/M10/OPSYS restent **PARTIAL**.
