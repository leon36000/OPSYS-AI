# Import QuickBooks Online par les exports — M5, onboarding comptable

Reprise de l'historique d'un client tenu sur QuickBooks Online (QBO) dans le grand livre OPSYS (`grand-livre.md`), par
le repli « exports » du connecteur QuickBooks : des fichiers que l'humain exporte lui-même depuis QBO et dépose sur le
serveur OPSYS. **Aucune API QuickBooks, aucun appel réseau, aucun jeton QBO.**

Code : `src/m5_financecore/import_quickbooks.py` (noyau pur : lecture, correspondance, vérification, propositions),
`grand_livre.py` (`proposer_ecritures_lot`, `valider_ecritures_lot`), adaptateur et outils dans `outils.py` (section
« import QuickBooks Online »). Tests : `tests/test_import_quickbooks.py` (noyau), `tests/test_import_quickbooks_outils.py`
(vrai socle, file N4, parcours complet). Exports fictifs : `tests/fixtures/quickbooks/` (`MANIFESTE.yaml`, `fictif: true`).

Toute sortie porte la mention de M5 et « À valider auprès d'un comptable (CPA) / professionnel qualifié ». L'import
prépare une reprise ; il ne remplace ni le CPA ni la revue des soldes repris.

## Parcours

| Étape | Outil | Niveau | Effet |
|---|---|---|---|
| 1. Déposer les exports | — | — | L'humain copie les fichiers dans `<OPSYS_HOME>/imports/quickbooks/` (défaut `~/.opsys/imports/quickbooks/`). |
| 2. Analyser | `m5_analyser_exports_quickbooks` | T0 | Lecture expliquée de chaque fichier, correspondance PROPOSÉE (brouillon), comptes non appariés, vérification de la balance. Rien n'est écrit. |
| 3. Valider la correspondance | `m5_valider_correspondance_quickbooks` | T2/**N4** | Proposition + choix manuels ; versionnée au registre `import_quickbooks`. |
| 4. Importer | `m5_importer_quickbooks` | T1/N1 | Vérification au cent, puis écritures en **BROUILLON** au grand livre, tout ou rien. |
| 5. Relire | `m5_lire_import_quickbooks` | T0 | Fichiers, vérification, soldes OPSYS attendus, écritures et statut, arguments exacts de la validation en lot. |
| 6. Valider | `m5_valider_import_quickbooks` (lot) ou `m5_valider_ecriture_comptable` (une à une) | T2/**N4** | Les brouillons deviennent définitifs. |

Les outils ne reçoivent qu'un **nom** de fichier (lettres, chiffres, `.`, `_`, `-`, espace ; `.csv`, `.txt`,
`.xlsx`), jamais un chemin : un nom avec `/` ou `..`, un fichier absent, un lien symbolique, autre chose qu'un fichier
ordinaire ou plus de 5 Mio sont refusés (`REJ-QBO-FICHIER-INVALIDE`). Portée d'appareil **fermée** pour les cinq
outils (refus `REJ-IDENTITE-APPAREIL-INVALIDE` dans le code). Le registre des mouvements n'est jamais lu ni écrit
(`conformite.verifier_aucun_decaissement`, strict). Registres : `grand_livre` (écritures) et `import_quickbooks`
(maillons `qbo_correspondance_validee`, `qbo_import_propose`, `qbo_lot_valide`), append-only hash-chaînés sur la table
de registres existante : **aucune migration**.

## Exports acceptés et procédure côté QuickBooks

Menus de QuickBooks Online Canada (libellés français, puis anglais ; ils varient selon la version de QBO). Toujours
exporter en **comptabilité d'exercice** (« Comptabilité d'exercice » / « Accrual »), en CSV ou en Excel (`.xlsx`).

| Fichier | Rapport QBO | Réglages | Rôle |
|---|---|---|---|
| Liste des comptes (requis) | Rapports › « Liste des comptes » (ou Plan comptable › Exécuter le rapport) / Reports › « Account List » | Toutes les colonnes par défaut ; le numéro de compte s'il est activé | Comptes, type QBO, type de détail, numéro |
| Balance de clôture (requis) | Rapports › « Balance de vérification » / « Trial Balance » | Date de fin = **date de reprise** ; comptabilité d'exercice | Soldes à atteindre au cent |
| Journal (mode `detail`, et vérification) | Rapports › « Journal » / « Journal » | Du lendemain de la balance d'ouverture (ou de l'ouverture de l'entreprise) à la date de reprise ; colonnes Date, Type de transaction, N°, Nom, Mémo/Description, Compte, Débit, Crédit | Une écriture par transaction |
| Balance d'ouverture (facultative) | « Balance de vérification » / « Trial Balance » | Date de fin = veille du premier jour du journal, idéalement la **fin de l'exercice précédent** | Soldes de départ |

Les clients et fournisseurs (« Liste des clients », « Vendor Contact List ») ne sont pas importés par cette tranche :
le nom présent sur chaque transaction du journal est repris dans le libellé de l'écriture.

### Lecture (ce qui est compris, et rien d'autre)

- **Format** : CSV, ou classeur `.xlsx` (première feuille, lu avec la bibliothèque standard ; nombres sans passer par
  un flottant, artefact binaire de moins d'un millionième ramené au cent ; date en numéro de série Excel acceptée dans
  la colonne Date). `.xls` binaire, PDF, classeur illisible : refus.
- **Séparateur** : `,`, `;` ou tabulation ; retenu parce qu'UN SEUL fait apparaître l'en-tête attendu.
- **Encodage** : UTF-8 (avec ou sans BOM), UTF-16 avec BOM, sinon Windows-1252 ; l'encodage retenu est rendu.
- **En-têtes** reconnus en français et en anglais (accents, casse et ponctuation ignorés : « Débit »/« Debit »,
  « N° »/« Num », « Type de transaction »/« Transaction Type », « Compte »/« Account »...) ; colonnes non reconnues
  ignorées et nommées (`colonnes_ignorees`).
- **Montants** : `1,234.56`, `$1,234.56`, `1 234,56 $` (espace, espace insécable ou point de milliers), `(1,234.56)`
  ou `-1 234,56` pour un négatif, au cent. Une seule lecture possible par chaîne (groupes de milliers de trois chiffres,
  deux décimales au plus) ; une seule convention par fichier (`REJ-QBO-MONTANT-AMBIGU` si point et virgule décimaux se
  mêlent). Un débit négatif compte comme un crédit (le solde est débit moins crédit).
- **Dates** du journal : `AAAA-MM-JJ`, `JJ/MM/AAAA` ou `MM/JJ/AAAA`, déduit des données (un jour au-delà de 12) ;
  indécidable : `REJ-QBO-DATE-AMBIGUE`, préciser `format_dates`. Date de la balance : la ligne de titre (« As of
  December 31, 2025 », « Au 31 décembre 2025 », ou ISO).
- **Lignes ignorées explicitement, et comptées** (`lignes_ignorees`) : titres (avant l'en-tête, une seule cellule),
  lignes vides, totaux (TOTAL de la balance — exigé —, total de chaque transaction et TOTAL du journal : chacun
  contrôlé contre la somme recalculée), pied de rapport (méthode, horodatage), lignes à zéro et transactions toutes à
  zéro. Toute autre ligne est `REJ-QBO-LIGNE-INCOMPRISE` avec son numéro.
- Une balance en **méthode de caisse** est refusée ; une colonne de devise autre que CAD aussi.

## Correspondance des comptes QBO -> plan OPSYS

Proposée automatiquement, de façon déterministe (mêmes fichiers et même plan : même proposition), avec la méthode et
l'explication de chaque ligne, dans cet ordre :

1. **numéro** : le numéro QBO est un compte OPSYS actif de la même classe ;
2. **nom** : le nom QBO (complet ou dernier segment d'un sous-compte `Parent:Enfant`) est le nom d'un compte OPSYS, ou
   figure dans la table de synonymes versionnée `qbo-synonymes-v1` (Chequing, Comptes clients, GST/HST Payable, TVQ à
   payer, Retained Earnings, Ventes...) ;
3. **type** : le type QBO n'a qu'un compte naturel (Banque -> rôle `banque`, Comptes clients -> `comptes_clients`,
   Comptes fournisseurs -> `comptes_fournisseurs`) ET la liste n'a qu'UN compte de ce type.

Classes : Banque, Comptes clients, Autres actifs à court terme, Immobilisations, Autres actifs -> actif ; Comptes
fournisseurs, Carte de crédit, Autres passifs à court terme, Passifs à long terme -> passif ; Capitaux propres ;
Revenus, Autres revenus -> produits ; Coût des marchandises vendues, Dépenses, Autres dépenses -> charges. Un type QBO
inconnu est refusé.

Sinon le compte est **NON APPARIÉ** (avec la raison, par exemple « 2 comptes QBO de type Bank : choisir ») : jamais un
compte « divers » par défaut. La proposition est un **brouillon** ; la correspondance **validée** (N4) applique les
choix manuels `{compte_qbo, compte_opsys}` (un compte OPSYS actif de la même classe), n'a plus aucun compte non
apparié, et reçoit un numéro de version. Plusieurs comptes QBO peuvent viser le même compte OPSYS (regroupement
décidé par l'humain). Une correspondance identique à la dernière version n'est pas réécrite. L'import exige la
DERNIÈRE version, et une liste des comptes dont l'ensemble (nom, type) n'a pas changé depuis (un nouvel export de la
même liste, aux soldes différents, garde son empreinte) ; un compte visé devenu inactif rend la correspondance périmée.

## Vérification au cent

L'import n'est accepté que si la **balance recalculée** égale **au cent** la balance de clôture exportée, **compte QBO
par compte QBO et au total** ; sinon `REJ-QBO-BALANCE-ECART` avec chaque écart (`balance_qbo`, `recalcule`,
`ecart`), et rien n'est importé. Balance recalculée = soldes d'ouverture + chaque transaction du journal (chacune
équilibrée, sinon `REJ-QBO-TRANSACTION-DESEQUILIBREE`).

Report des résultats : QBO présente les produits et charges de l'exercice en cours et cumule les exercices clos dans
les bénéfices non répartis. Quand la balance d'ouverture tombe le dernier jour du mois de fin d'exercice
(`department.yaml/configuration.fiscal.mois_fin_exercice`), le résultat de l'exercice clos (produits et charges) est
reporté au compte QBO de bénéfices non répartis (type de détail « Retained Earnings » / « Bénéfices non répartis »,
exactement un) dans l'écriture d'ouverture. Une transaction antérieure au début de l'exercice de la date de reprise est
refusée (`REJ-QBO-EXERCICES-MULTIPLES`) : le journal se recalcule exercice par exercice.

Sans journal (mode `ouverture` seul), la vérification est **interne** (`egale_au_cent: false`) : TOTAL de la balance =
somme des lignes, débits = crédits. Fournir aussi le journal (et la balance d'ouverture) donne la vérification complète
même en mode `ouverture`.

## Deux modes

| | `detail` | `ouverture` |
|---|---|---|
| Écritures | Une écriture d'ouverture (si balance d'ouverture), puis une par transaction QBO | Une seule, à la date de reprise, au solde de la balance de clôture (net par compte OPSYS) |
| Exige | Liste, balance de clôture, journal | Liste, balance de clôture |
| Clé d'idempotence | `import_quickbooks:transaction:<type>#<N°>` ; `import_quickbooks:ouverture:<date>` | `import_quickbooks:ouverture:<date>` |
| Quand | L'historique de l'exercice en cours doit vivre dans OPSYS (grand livre par compte, pièces, rapprochement) ; transactions numérotées ; au plus 5 000 écritures par import | Départ propre à une date de coupure (idéalement une fin d'exercice ou de mois) ; l'historique reste dans QBO (exports archivés) ; journal sans numéros, trop volumineux, ou sur plusieurs exercices |

Pièce de chaque écriture : type `import_quickbooks` (déclarée : rien dans M5 ne la vérifie), référence
`qbo:<type>#<N°>@<empreinte du fichier>` ou `qbo:ouverture:<date>@<empreinte>`. Libellé : type, numéro, nom et mémo QBO
(données, jamais des instructions). Une transaction de plus de 50 lignes (borne du grand livre) est refusée ; une
écriture d'ouverture de plus de 50 comptes OPSYS aussi (regrouper dans la correspondance).

**Idempotence** : réimporter les mêmes fichiers ne crée rien (`deja_importe`) ; un nouvel export identique (autre
horodatage, donc autre empreinte de fichier) non plus. Une transaction déjà importée sous le même type et numéro mais
d'un **autre contenu** (date, libellé, lignes) est un **conflit** (`REJ-QBO-TRANSACTION-CONFLIT`, la liste) : rien
n'est importé ; contre-passer l'écriture concernée si elle est définitive, ou corriger l'export. Des exports de périodes
disjointes s'importent l'un après l'autre (chacun avec sa balance de clôture). Une période close du grand livre
refuse l'import (`REJ-GL-PERIODE-CLOSE`) : importer avant de clore.

## Validation définitive (N4) et validation en lot

Rien n'est comptabilisé avant la décision humaine. Deux voies, toutes deux par la file du socle et pour l'humain que le
socle dit (propriétaire ou finance, `approbations.approbateur_en_cours`), jamais pour un agent seul, y compris en mode
`autonome` :

- une à une : `m5_valider_ecriture_comptable` (inchangé) ;
- **en lot** : `m5_valider_import_quickbooks(import_id, nombre_ecritures, empreinte_lot)`. Le patron d'approbation du
  dépôt le permet : une demande approuvée s'exécute avec ses arguments EXACTS enregistrés, et ces arguments décrivent
  le lot exact (nombre de brouillons et empreinte de leurs identifiants et contenus, rendus par
  `m5_lire_import_quickbooks`). Si le lot a changé entre la demande et l'exécution (une écriture validée seule,
  contre-passée), l'outil refuse (`REJ-QBO-LOT-PERIME`). Tout ou rien ; chaque écriture repasse les contrôles de
  `valider_ecriture` (équilibre, comptes actifs, période ouverte) ; une contre-passation ne se valide jamais en lot.
  Un maillon `qbo_lot_valide` garde la décision ; chaque écriture garde son `gl_ecriture_validee`.

Une fois validé, la balance OPSYS à la date de reprise égale la balance de vérification QBO regroupée par compte OPSYS
(`attendu_opsys_apres_validation`), si aucune autre écriture n'a été passée sur la période ; l'export Beancount
(`grand_livre_beancount`) rend une transaction équilibrée par écriture.

## Codes de refus

| Code | Quand |
|---|---|
| `REJ-QBO-FICHIER-INVALIDE` | Nom hors gabarit, fichier absent, lien symbolique, pas un fichier ordinaire, vide, plus de 5 Mio, classeur trop gros décompressé. |
| `REJ-QBO-FORMAT-NON-PRIS-EN-CHARGE` | `.xls` binaire, PDF, classeur `.xlsx` illisible ou à cellules d'erreur. |
| `REJ-QBO-ENCODAGE` | Ni UTF-8, ni UTF-16 avec BOM, ni Windows-1252 ; caractère nul. |
| `REJ-QBO-CSV-ILLISIBLE` | CSV mal formé (guillemets) quel que soit le séparateur. |
| `REJ-QBO-ENTETES-INCONNUES` | En-tête du rapport attendu introuvable (mauvais rapport, colonnes requises absentes). |
| `REJ-QBO-SEPARATEUR-AMBIGU` | Plusieurs séparateurs font apparaître l'en-tête. |
| `REJ-QBO-LIGNE-INCOMPRISE` | Ligne de titre à plusieurs cellules, montants sans compte, ligne après le TOTAL, ligne hors transaction (numéro de ligne rendu). |
| `REJ-QBO-MONTANT-INVALIDE` | Montant illisible, au-delà du cent, hors domaine ; débit ET crédit sur la même ligne. |
| `REJ-QBO-MONTANT-AMBIGU` | Point décimal et virgule décimale mêlés dans un fichier. |
| `REJ-QBO-DATE-INVALIDE` | Date de transaction illisible ou impossible. |
| `REJ-QBO-DATE-AMBIGUE` | JJ/MM et MM/JJ indécidables ou mêlés (préciser `format_dates`). |
| `REJ-QBO-DATE-INTROUVABLE` | Balance sans date dans son titre. |
| `REJ-QBO-TOTAL-ABSENT` | Balance sans ligne TOTAL. |
| `REJ-QBO-TOTAL-INCOHERENT` | TOTAL (ou total d'une transaction) différent de la somme recalculée. |
| `REJ-QBO-BALANCE-DESEQUILIBREE` | Balance dont débits ≠ crédits. |
| `REJ-QBO-METHODE-CAISSE` | Rapport en méthode de caisse. |
| `REJ-QBO-DEVISE-NON-GEREE` | Devise autre que CAD. |
| `REJ-QBO-TYPE-COMPTE-INCONNU` | Type QBO non reconnu (comptes nommés). |
| `REJ-QBO-COMPTE-DUPLIQUE` | Compte ou numéro répété dans la liste ou la balance. |
| `REJ-QBO-COMPTE-HORS-LISTE` | Compte de la balance ou du journal absent de la liste des comptes. |
| `REJ-QBO-TRANSACTION-SANS-NUMERO` | Transaction sans N° (le mode `ouverture` reste possible). |
| `REJ-QBO-TRANSACTION-DUPLIQUEE` | Même type et même N° pour deux transactions. |
| `REJ-QBO-TRANSACTION-DESEQUILIBREE` | Transaction dont débits ≠ crédits. |
| `REJ-QBO-TRANSACTION-TROP-LONGUE` | Transaction de plus de 50 lignes. |
| `REJ-QBO-CHAMP-INVALIDE` | `format_dates` inconnu ; type ou N° de plus de 40 caractères ; nom de compte trop long. |
| `REJ-QBO-MODE-INVALIDE` | Mode inconnu ; `detail` sans journal ; balance d'ouverture sans journal. |
| `REJ-QBO-DATE-REPRISE-DIFFERENTE` | `date_reprise` ≠ date de la balance de clôture. |
| `REJ-QBO-DATE-HORS-PERIODE` | Transaction après la date de reprise ou pas après la balance d'ouverture ; ouverture pas avant la clôture. |
| `REJ-QBO-EXERCICE-INCONNU` | Balance d'ouverture avec produits ou charges sans `mois_fin_exercice` déclaré (ou invalide). |
| `REJ-QBO-EXERCICES-MULTIPLES` | Transaction antérieure à l'exercice de la date de reprise. |
| `REJ-QBO-BNR-INTROUVABLE` | Report du résultat sans exactement un compte de bénéfices non répartis. |
| `REJ-QBO-COMPTES-NON-APPARIES` | Correspondance à valider avec des comptes sans compte OPSYS (la liste). |
| `REJ-QBO-CORRESPONDANCE-INVALIDE` | Choix manuel mal formé, répété, compte QBO ou OPSYS inconnu, inactif, autre classe. |
| `REJ-QBO-CORRESPONDANCE-INTROUVABLE` | Version de correspondance inconnue (aucune validée). |
| `REJ-QBO-CORRESPONDANCE-PERIMEE` | Version remplacée, liste des comptes changée, compte visé devenu inactif. |
| `REJ-QBO-BALANCE-ECART` | Balance recalculée ≠ balance exportée, compte par compte ou au total (écarts rendus). |
| `REJ-QBO-ECRITURE-TROP-LONGUE` | Écriture d'ouverture de plus de 50 comptes OPSYS. |
| `REJ-QBO-TRANSACTION-CONFLIT` | Même transaction QBO déjà importée avec un autre contenu. |
| `REJ-QBO-IMPORT-INTROUVABLE` | `import_id` inconnu. |
| `REJ-QBO-LOT-PERIME` | Le lot décrit par les arguments n'est plus le lot en attente (ou aucun brouillon). |

S'y ajoutent ceux du grand livre (`grand-livre.md`) : `REJ-GL-HUMAIN-REQUIS`, `REJ-GL-PERIODE-CLOSE`,
`REJ-GL-CHAINE-INVALIDE`, `REJ-GL-STOCKAGE-NON-DURABLE`, `REJ-GL-PLAN-INVALIDE`, `REJ-GL-LIMITE-INVALIDE` (lot de plus
de 5 000 écritures, pagination), et `REJ-IDENTITE-APPAREIL-INVALIDE`.

## Limites

- Pas d'API QuickBooks Online réelle (ni OAuth, ni synchronisation) : exports manuels seulement.
- Pas de pièces jointes (factures PDF, reçus) : seules les références (type, N°, empreinte du fichier) sont reprises.
- Pas de taxes détaillées par ligne si l'export ne les porte pas : les montants de TPS/TVQ sont repris tels que les
  comptes de taxes QBO les portent (le rapprochement TPS/TVQ du grand livre ne vaut que pour les factures M5).
- Multi-devises non géré (CAD seulement) ; pas de soldes en devise.
- Rapport « Grand livre » (General Ledger) détaillé non lu par cette tranche : utiliser le rapport « Journal », qui porte
  les mêmes transactions groupées.
- Clients, fournisseurs, articles, sous-registres (comptes clients par client) non importés.
- Un exercice à la fois en mode `detail` ; la clôture d'exercice dans OPSYS (report des résultats après l'import)
  reste une écriture de fin d'exercice à passer avec le CPA.
- Au plus 5 000 écritures par import et 5 Mio par fichier : découper par périodes disjointes.
- La provenance des fichiers (vraiment exportés du dossier QBO du client) est attestée par l'humain qui les dépose ;
  OPSYS en garde l'empreinte.
