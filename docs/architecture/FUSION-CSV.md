# Fusion opérationnelle : import comptable CSV

Ce pilote transforme un relevé bancaire en propositions préparatoires de rapprochement,
en réutilisant le parseur M5. Il conserve la source et la reprise dans la base de l'instance.
Il ne modifie aucune facture, aucun paiement ni aucune écriture comptable finale.

## Utilisation

Un administrateur ou propriétaire actif ouvre **Fusion opérationnelle** dans la console,
sélectionne un compte interne configuré dans `configuration.banque_csv.comptes_internes`
du département M5, puis indique les colonnes date, montant et référence de facture.
Le fichier doit être un CSV UTF-8, en CAD, de **1 Mio et 2 000 lignes au maximum**.
Les descriptions et colonnes ignorées ne sont pas affichées ni copiées dans M10.

L'import crée un lot `RECU`. L'action **Préparer le lot** enchaîne au plus vingt tranches
de cent lignes, dans des transactions indépendantes. **Traiter / reprendre** reste disponible
pour avancer une seule tranche. Les seuils de deux secondes par tranche et huit secondes au total
sont contrôlés entre transactions : ils ne garantissent pas un délai HTTP maximal.
Le parseur prépare une fois son résultat complet, chiffré; les tranches suivantes reprennent
ce résultat sans refaire l'extraction. Le curseur et la révision empêchent une double tranche.
Une panne annule la transaction en cours; la dernière tranche validée reste disponible.
Une déconnexion observée ou une annulation demande l'arrêt après la tranche courante.
Pour reprendre, recharger le lot et utiliser sa révision actuelle; une ancienne révision est refusée.
Le travail progresse à la demande : aucun ordonnanceur de fond n'est livré par ce pilote.

`PROPOSITIONS` indique des candidats à examiner; `AUCUNE_PROPOSITION` indique un relevé
accepté sans candidat; `REFUSE` conserve un refus borné sans cellules. Si la vue complète des
factures M5 change, le lot devient `SNAPSHOT_OBSOLETE` et ses candidats ne sont plus consultables.
Une nouvelle évaluation exige un nouvel import avec un nouvel identifiant de mutation.
Les anciens résultats restent conservés et chiffrés.

## Protection et exploitation

Installer l'extra `ingestion` verrouillé à `cryptography==50.0.2`. Fournir côté serveur une clé
AES-256 de 32 octets, encodée en base64, dans la variable référencée. La référence par défaut
est `OPSYS_INGESTION_CLE`; `OPSYS_INGESTION_CLE_REFERENCE` permet de choisir un autre nom
de variable serveur. Aucune clé n'est créée automatiquement ni conservée dans la base.

Chaque lot retient sa référence de clé d'origine. Une rotation affecte les nouveaux lots;
les anciennes clés restent nécessaires à la lecture et à la reprise des anciens lots.
Sauvegarder séparément la base et ces clés via le dispositif de secrets de l'exploitant.
Sans ancienne clé, une restauration ne permet pas de déchiffrer le lot. L'effacement individuel
par clé enveloppée et la purge gouvernée restent à construire.

AES-GCM authentifie la source, le résultat complet et les lignes avec des nonces aléatoires
distincts et une liaison au lot, à la source et à la version du format. Clé absente, format
inconnu ou échec d'authentification produisent un refus explicite. Un échec d'authentification
ne permet pas de distinguer une mauvaise clé d'une altération du chiffré.

Le quota transactionnel couvre **64 lots et 64 Mio de chiffrés binaires**, source, résultat
complet et segments inclus. Le résultat normalisé est limité à 4 Mio avant chiffrement.
Le codage base64 et les métadonnées ajoutent du stockage en base : 64 Mio n'est pas une
limite de taille du fichier de base. Ce quota n'est pas un moteur d'ingestion massive.

La portée est une instance OPSYS sur SQLite. PostgreSQL pour ce pilote reste non qualifié
et doit refuser l'exécution; les autres fonctionnalités PostgreSQL du produit gardent leur
qualification propre. Aucune isolation SaaS entre entreprises n'est revendiquée ici.

## Mémoire et interfaces

La provenance va dans le registre documentaire M10 sous le genre `m5.releve_bancaire_csv` :
lot, source SHA-256, référence locale opaque, classe `FINANCIAL`, auteur source, compte,
snapshot M5, compteurs, statut et date. Elle ne crée pas de faux lead ou chantier et ne contient
aucun montant. Les audits des opérations doivent identifier la personne qui les exécute.
Aucune source financière n'est envoyée aux embeddings, LLM ou fournisseurs par cette ingestion.

Routes privées sous le préfixe de la console :

- `GET /fusion-operationnelle` et `GET /fusion-operationnelle/lots/{id}`;
- `POST /fusion-operationnelle/lots` et `POST /fusion-operationnelle/lots/{id}/traiter`;
- `GET /api/fusion-operationnelle/lots` et `GET /api/fusion-operationnelle/lots/{id}`;
- `GET /api/fusion-operationnelle/lots/{id}/provenance`;
- `POST /api/fusion-operationnelle/lots` et `POST /api/fusion-operationnelle/lots/{id}/traiter`.
- `POST /fusion-operationnelle/lots/{id}/preparer` et `POST /api/fusion-operationnelle/lots/{id}/preparer`.

Les créations API acceptent un objet JSON fermé ou un multipart borné; les formulaires HTML
exigent le CSRF de la session. Le traitement API reçoit seulement `revision_attendue` et le
CSRF en en-tête. Les employés, clients et identités devenues inactives n'accèdent pas aux lots.

## Qualification

Qualification ROOT locale de la préparation en une action dans [R23](../research/R23-2026-10-02/README.md) :
496 cas Python intégrés, dont les 19 cas Fusion antérieurs et 29 nouveaux cas de préparation;
aucun échec, erreur ou skip, 1 093 empreintes sélectionnées identiques avant/après.
[R22](../research/R22-2026-10-02/README.md) conserve la qualification initiale distincte.
Le cas de 2 000 lignes utilise une horloge injectée pour qualifier le plafond, pas la performance.
Déconnexion et annulation sont exercées par injection contrôlée, sans panne réelle de navigateur.
Ces chiffres ne s'ajoutent pas aux campagnes précédentes.
Le [contrat de préparation](../programme/LOT-PREPARATEUR-CSV-BORNE.md) détaille les arrêts et la reprise.
Le [contrat du lot](../programme/LOT-FUSION-CSV-COMPTABLE.md)
définit les essais de chiffrement, reprise, quotas, droits, snapshot et absence d'écriture finale.
PDF/OCR, classement multi-format, recherche documentaire, import massif et apprentissage continu
conservent leurs critères séparés dans le [plan de reprise](../programme/REPRISE-PLAN-2026-10-02.md).
