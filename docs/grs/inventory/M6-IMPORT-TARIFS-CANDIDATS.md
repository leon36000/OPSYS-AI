# M6 / CRM-14 — préparation gouvernée des listes de prix

Source auditée : `9c4df1d1`. Contrat écrit avant tests/code. Statut initial : non implémenté.
Voir [audit initial](M6-AUDIT-INITIAL-QUADRUPLE-A.md) et
[historique des tarifs](M6-AUDIT-HISTORIQUE-TARIFS-ADMIN.md).

## Objectif et décision minimale

Transformer des lignes explicitement mappées d’une liste fournisseur en candidats de saisie
M6, avec références et erreurs actionnables. Cette tranche prépare; le livre reste inchangé.
Réutiliser Decimal, validation propriétaire du livre, règles du port privé et hashes déterministes.
Aucun besoin d’ajouter un moteur BI/ETL à cette première frontière. La recherche de briques pour
les adaptateurs CSV/XLSX/PDF est conservée séparément; aucune dépendance adoptée par ce contrat.

## Données et interface pure

`import_tarifs.preparer(lignes, fournisseur_id=..., source_document=..., source_octets=...,
jour_reference=..., limite_sortie=65536)` reçoit un seul fournisseur explicite et une source
binaire non vide ≤1Mio, plus au plus50 lignes mappées (256Kio UTF-8 au total). Cette fonction
n’extrait pas des lignes d’un PDF/CSV : la correspondance document→lignes demeure déclarée.
SHA-256 du binaire, du mapping complet et de l’enveloppe identifient l’intention; un hash ne
prouve ni l’expéditeur d’un courriel, ni l’exactitude de l’extraction, ni un prix officiel.

Clés exactes de chaque ligne : numero_ligne, materiau_id, unite, prix_unitaire_decimal,
devise, date_effet. Valeurs scalaires bornées, clés inconnues ou structure imbriquée refusent
le mapping entier; champ métier invalide donne une ligne A_CORRIGER, candidat absent et code
fixe sans recopier la valeur libre. Numéro de ligne entier1..50000, matériau canonique du port
privé, unité explicite, devise CAD sans conversion, date ISO non future par rapport au jour
fourni. Montant texte positif jusqu’à9 chiffres entiers/6décimales, égalité Decimal→float→Decimal
requise par le livre actuel. Aucune normalisation d’identifiant, de séparateur décimal ou d’unité.

Un même matériau ou numéro de ligne apparaît deux fois : les deux lignes sont à corriger,
sans choix automatique de dernière ligne. L’ordre source est conservé. Les lignes admissibles
sont PRET_POUR_REVUE; le lot est A_REVOIR ou A_CORRIGER, jamais approuvé/appliqué. Catalogue,
fournisseur, unité du catalogue et prix courant ne sont pas encore vérifiés par cette fonction
pure; l’aperçu privé suivant les revalidera sur snapshots canoniques.

## Fichiers, routes et workflows

Fondation dans `departments/m06-material-control/src/m6_material_control/import_tarifs.py`,
tests du département. Aucun nouvel outil, route, table, worker, hook courriel ou appel modèle.
Workflow : source mappée explicite→validation/candidats/erreurs→revue privée ultérieure→
confirmation via les ports M6 existants. M3 garde ses devis figés; M5/M8/M9/M10 ne reçoivent
aucun fait financier ou mémoire depuis la simple préparation pure.

## Risques, permissions, tests et gates

JSON64Kio ou quota plus petit, source/hash complets, copies indépendantes, refus avant hash de
source trop volumineuse, pas d’horloge/IO/SQL/opsys dans le domaine. Cas tests : ordre, exactitude
monétaire, doublons symétriques, mauvais mapping, booléens/non-finis, identités/unités/devise/date,
source/quota, indépendance et rejet des prix non représentables par le writer. Comparer un
candidat valide au vrai prepare/confirm existant dans la tranche d’aperçu suivante; ne pas
présenter des tests purs comme une intégration courriel ou mise à jour officielle.

Aucune demande Nathan supplémentaire pour préparer ces données fictives. La future application
du lot doit respecter autorité courante, approbation/politique et atomicité/idempotence, sans
contourner la réception/audit/M10. Formats fournisseurs inconnus, OCR, CSV/XLSX, courriel réel,
aperçu/confirmation HTTP, PostgreSQL/mobile demeurent non qualifiés. Prochaines étapes : rouge
fonctionnel, fondation pure, regressions propriétaires, puis raccord privé avant élargissement.


## Qualification locale de la fondation

La fondation pure `import_tarifs.preparer` est implémentée. Snapshot plat privé avant hash et
projection : une modification des lignes de l’appelant pendant la validation ne peut plus
faire diverger le candidat du mapping haché. Le défaut a été reproduit (92PASS/1FAIL), puis
corrigé et conservé en régression. Première cohorte93PASS, puis82PASS ciblés sur candidats,
historique, digest et conformité. Les cohortes recoupées ne s’additionnent pas.

Suite entière M6 : **1700 PASS, 0 FAIL/SKIP, 71,70s**, dont39nouveaux candidats. Ruff sur le
paquet entier et vérificateur natif304outils/177déclarés réussis. Sources en lecture seule,
réseau refusé, CPU1/1Gio/96tâches/600s et homes privés avant imports. Relecture indépendante
statique de la frontière pure : aucun constat concret résiduel; ce n’est pas une seconde QA.

La CI de la tête antérieure9c4df1d1 a révélé un autre problème : la constante publique de
messages `AVERTISSEMENTS` de l’historique était classée comme énuméré métier sans échappatoire.
Reproduit localement, corrigé en constante privée; le nouveau jeu de noms de champs utilise
`CHAMPS_LIGNE`. Le contrôleur de conformité est inchangé et ses tests restent actifs. Les rouges
et la CI précédente sont conservés, sans présenter la validation locale comme une CI verte.

Réutilisation étudiée : [Python CSV](https://docs.python.org/3/library/csv.html),
[Decimal](https://docs.python.org/3/library/decimal.html) et
[Frictionless](https://github.com/frictionlessdata/frictionless-py) (MIT examinée, non adopté).
Recherche GitHub et GitLab bornée; aucun candidat GitLab pertinent suffisamment qualifié dans
l’échantillon, sans prétendre à l’absence universelle de brique. Aucun nouvel outil installé.

Statut : fondation pure qualifiée localement; import opérationnel/CRM-14 restent PARTIAL.
Prochaine tranche concrète : adaptateur CSV UTF-8 borné avec séparateur et correspondance de
colonnes explicites, puis aperçu privé revalidant catalogue/fournisseur/unité/prix courant.
Déclarer séparément identité du binaire, mapping sémantique et configuration d’extraction;
ne pas prétendre que les hashes authentifient les lignes extraites. Aucun format réel de
Gentek/Royal/O.A.M./Kaycan n’est présumé. Confirmation idempotente/atomique et courriel restent
à raccorder/qualifier sous les permissions existantes.
