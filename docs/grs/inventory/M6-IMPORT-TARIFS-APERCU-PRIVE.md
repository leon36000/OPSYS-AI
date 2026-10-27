# M6 / CRM-14 — préparation CSV privée sur sources canoniques

Audit/contrat avant code : source7fd27519, statut initial non implémenté. Les candidats purs et
CSV existent; ils ne connaissent ni catalogue courant, ni répertoire, ni dernier prix SQL.
`prix_console._preparer` est la référence de saisie sans écriture; le writer final conserve
CAS/idempotence/réception/audit/M10. Aucun nouvel achat, import officiel ou prix appliqué ici.

## Architecture et contrat

Ajouter `import_tarifs_console.py`, T0 privé `m6_preparer_import_tarifs_console` sans rôle appareil,
raccord `prix_console.outils/NOMS`, DEUX fermetures génériques anticipées et dispatcher console.
Paramètres fermés : source_csv_utf8, mapping_colonnes, separateur, fournisseur_id, source_document,
source_attendue(null ouhash). Le jour vient de la réception serveur actuelle, jamais de l’appelant.
UTF-8 réencodé strictement conserve octets/BOM/CRLF;1Mio réel après encodage. Aucun I/O, chemin,
URL fetch, envoi ou SQL fourni par l’appelant. Le CSV et ses colonnes restent explicitement choisis.

Admin SQL actif, origine console, absence MCP et réception liée console:<auteur> AVANT source.
SQLite canonique seulement. Parse CSV borné avant lecture des journaux. Capturer catalogue,
fournisseurs et livre : compte10000/octets8Mio chacun avant décodage, rangs réels continus,
métadonnées SQL. Valider catalogue chaîné avec propriétaire, répertoire historique avec propriétaire,
livre entier avec validateur historique. Projection indépendante depuis ces snapshots, aucune
relecture de tables transactionnelles d’autres départements, aucune écriture de journal.

Par ligne : erreurs pures conservées; matériau existant/actif et unité source EXACTE du catalogue,
fournisseur exact connu; nom courant ne remplace pas une identité historique. Une entrée inconnue,
inactive ou incompatible est A_CORRIGER, jamais créée implicitement. Répertoire dont un nom
historique dépasse le contrat du writer prix (200caractères) : signal REPERTOIRE_HORS_CONTRAT_SAISIE,
pas fausse promesse de confirmation; l’historique reste consultable. Aucun contact dans le résultat.
Si admissible : reproduire la préparation de saisie existante depuis sources indépendantes,
avec noms actuels, montant fourni, ancre matériau/fournisseur et dernier rang/prix (ou absence).
Prix précédent inutilisable signalé; jamais reprendre un ancien prix en remplacement du dernier.
La comparaison ne propose ni prix de vente, ni devise/unité convertie, ni hausse inventée.

Source de l’aperçu = préparation CSV +jour serveur+snapshots SQL des trois familles. Cursor optionnel
source_attendue impose identité, sinon SOURCE-PERIMEE. Après projection et enveloppe bornée64Kio
ou limite contextuelle inférieure : relire autorité, recapturer3sources, refuser toute modification
même de métadonnées, relire autorité. Session actuelle vérifiée aussi par dispatcher après T0,
petit quota préservé. Statuts A_REVOIR/A_CORRIGER; confirmation non implémentée explicitement.

## Tests, permissions, risques et suites

Rouge nom/dispatcher absents, vraiT0/SQLite comparé aux fonctions pures et au vrai prepare tarif,
relecture après libérationSQL, toutes tables inchangées. Cas négatifs : agent/appareil/MCP,
réception absente/fauxadmin/expiry/connexion non canonique, portes génériques avant factory,
quota brut avant décodage, quota sortie hérité, sourceattendue périmée, corruption horscouple,
source/métadonnées changées pendant projection, révocation après dernière capture. Variantes de
catalogue/fournisseur/unité/ancienprix, aucune note libre/copied contact. Réutiliser preuves
candidats/CSV/historique et contrôle de conformité; pas de nouvelles dépendances ou agents modèles.

M10 préflight privé et sources versionnées du même chantier conservés (instance vide ≠mémoire
projet). Aucun fait M5/M8/M9/M10 émis par ce T0. Pas de nouvelle permission utilisateur/appareil;
une nouvelle entrée de catalogue d’outil reste privée. Générique, profils et MCP fermés.

Gates Nathan inchangés : aucune donnée réelle, connexion courriel, confirmation officielle,
finance, achat, droits, publication publique ou déploiement. Suites après qualification : upload
et aperçu CRM privés gardant cnx jusqu’après rendu, source/autorité finales et hash de préparation;
confirmation de lot atomique/idempotente à concevoir via writer existant. Mobile/PG/PDF/XLSX et
formats réels fournisseurs non qualifiés. Produit/CRM-14 restent PARTIAL.

## Qualification locale du T0 privé

Le T0 et son dispatcher privé sont raccordés. Sur vrais writers/SQLite, la préparation canonique
reproduit le vrai `m6_preparer_tarif_console`, y compris ancienprix et ancres. Ordre des clés du
codec conservé pour les reçus existants; le validateur historique sert à vérifier le livre sans
remplacer les données décodées par une sérialisation aux clés triées. Dernierprix USD/inutilisable
ne fait pas ressurgir un ancienprix. Noms actuels et prix restent sourcés; aucune note libre,
coordonnée fournisseur, écriture ou date commerciale transformée en réception.

Revue indépendante : deux constats reproduits (copie de source avant longueur, préparation
acceptée à10000tarifs alors que le writer refuse). Le contrôle explicite avant encodage et la
borne livre9999 maximum corrigent ces écarts. Un troisième rouge du root montre que le validateur
commun ne vérifie pas pattern; source_attendue est désormais contrôlée explicitement avantSQL.
Le validateur commun et les writers restent inchangés. Les refus de lint sont séparés des rouges
fonctionnels. Relecture statique de fermeture : les trois corrections sont résolues.

Qualification finale ciblée : **82PASS/24,08s dont23nouveaux** avec historique, saisie et conformité.
Première cohorte195PASS dont20nouveaux et116portées, sources compatibles réutilisées sans addition.
Ruff et vérificateur natif **305outils/177déclarés** réussis; aucune portée de compte/appareil ajoutée.
Quotas3familles avant toutdécodage, métadonnées relues, révocation à dernièrecapture, session expirant
aprèsT0, quota contextuel10octets, sourcepérimée, BOM/CRLF, corruption horscouple et10kprix testés.
Source lectureseule pendantQA, CPU1/1Gio/96tâches/600s, homes privés/réseau refusé avantimports.

Statut : préparation privée sur SQLite qualifiée localement. Aucun upload/écran CRM nouveau,
confirmationlot, importofficiel, courriel, PDF/XLSX, données réelles ou production dans cette tranche.
Prochaineétape : aperçu HTTP privé et borné depuisCSV, comparaisonindépendante auT0 puis source/
autorité aprèsrendu, requêteprivéemasquée, sans ajouter deconfirmationprix. Produit restePARTIAL.
