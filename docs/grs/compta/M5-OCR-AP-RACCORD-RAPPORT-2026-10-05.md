# M5 — candidat OCR, revue humaine et saisie financière

Statut : raccord console et services vérifié localement sur données fictives SQLite.

Le candidat OCR d’un PDF image/mixte ouvre explicitement un brouillon AP avec huit champs
vides. Une personne saisit les valeurs et choisit les tokens cités; le serveur empreinte les
citations et relit le PDF, le run, leurs révisions, le profil et le contenu authentifié.
Les résultats restent `A_REVOIR`; la confiance OCR brute n’est pas une mesure de précision.
La liste AP ne déchiffre rien et conduit au bon run, qui doit être revalidé lors de la consultation.

Le raccord réutilise les contrôles M5 et leurs formulaires existants. La vérification préparatoire
ne crée ni facture, dette ni approbation. Une confirmation humaine N3 distincte autorise une
saisie fournisseur interne après relecture de la source et du snapshot attendu. Le rejeu conserve
une seule saisie. La référence durable conserve les marqueurs OCR et la preuve financière.
Aucun paiement, envoi client ou engagement externe n’est exécuté par cette filière.

Les administrateurs sans droit finance peuvent revoir le candidat; les références financières
restent réservées aux acteurs autorisés. La révocation finance pendant une attente de lecture,
une relecture ou avant émission du rendu bloque la référence même si le rôle admin demeure.
Les sources périmées, citations invalides et contenus non authentifiés restent refusés.
Le trajet PDF natif garde ses contrôles et le format historique de sa preuve.

## Vérification et preuves

ROOT **r279 : 331/331 tests dans seize fichiers complets**, aucun échec, erreur ni saut,
Ruff et vérification des manifestes verts. Le gel des sources est identique avant/après;
aucun OOM ni installation. La campagne inclut PDF natif, OCR, migrations, conservation,
interfaces privées, vérification pure, confirmation N3 réelle interne, référence et rejeu.
Les fournisseurs de modèle et le candidat OCR sont fictifs; les services console, transactions,
chiffrement, contrôle de citations et chaîne d’approbation sont ceux du produit.

Les exécutions r261–r263 et r276–r278 sont conservées. Elles révèlent des défauts de montage :
clé du bundle fictif incompatible avec le décodeur, assertions sur des textes absents,
préfixe HTTPX doublé dans les redirections, identifiant de mutation N3 au mauvais format,
et attente d’un conflit de révision pour un run dont l’AAD avait été directement altérée.
Les protections de production n’ont pas été relâchées pour corriger ces cas. Un PDF périmé
est refusé en 409; une révision de run altérée sans rechiffrement est refusée comme contenu
corrompu en 503. Dans les deux cas, aucune saisie, approbation ni référence n’est ajoutée.

## Limites et suite

Aucune nouvelle qualification PostgreSQL, précision sur factures clientes, moteur OCR réel
ou ingestion universelle n’est démontrée par cette campagne. L’autorité d’une dette interne
ne vaut pas autorité de paiement. Le corpus réel et les mesures d’extraction restent à qualifier.
Voir le [domaine et sa migration](M5-OCR-AP-DOMAINE-RAPPORT-2026-10-05.md)
et le [programme de reprise](../../programme/PROGRAMME-24H-2026-10-04.md).

Preuve durable : [capsule du raccord](../../research/REPRISE-2026-10-05/preuves/OCR-AP-M5-RACCORD-r1.tar.xz)
(SHA-256 `cd3191b945e1f3892bf18557773f8fec1113cf27f4137a4f350e220f9a9e540c`).
La capsule conserve le rapport avant cet ajout, sources, préimages et exécutions historiques.
