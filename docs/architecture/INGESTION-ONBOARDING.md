# Ingestion d'onboarding — socle (chantier 4, tranche 1)

À l'onboarding, le client dépose en masse ses documents : factures fournisseurs et clients, soumissions, contrats,
listes de clients (CSV, `.xlsx`). OPSYS les ingère, les classe, en extrait les champs et **peuple en brouillon** les
comptes à payer de M5 et le CRM de M2. **Aucune donnée financière ni aucune fiche client n'est définitive sans la
décision d'un humain** (file d'approbation, niveau N3, comme la saisie d'une facture sans PO).

Feuille de route : lignes « Parsing/OCR », « Factures », « Orchestration d'ingestion » de
`FEUILLE-DE-ROUTE-TECHNO-r1` ; recherche R3 §2.2, §6.3, §8.1. Code : `src/opsys/ingestion_onboarding/`,
`departments/m05-financecore/src/m5_financecore/validation_facture_onboarding.py`,
`departments/m02-revenue-crm/src/m2_revenue_crm/clients_importes.py`, migration `0038_ingestion_onboarding`.

## 1. Parcours

```
<OPSYS_HOME>/imports/onboarding/<nom>  (fichier ou .zip)
   │ m5_deposer_lot_onboarding / opsys metier onboarding deposer      (N1 : préparation)
   ▼
LOT ─► DOCUMENTS (SHA-256, dédoublonnage exact, original chiffré) ─► 7 TÂCHES par document
   │ m5_avancer_lot_onboarding / opsys metier onboarding avancer      (N1)
   ▼
empreinte → type → texte → classement → extraction → validation → proposition
   ▼
BROUILLONS : ap_facture_fournisseur (M5)  ·  crm_client (M2)          PRET | A_VERIFIER (raisons exactes)
   │ m5_valider_brouillon_onboarding_ap · m2_valider_brouillon_onboarding_client   (N3 : file d'approbation)
   ▼
DÉFINITIF : facture sans PO SAISIE (registre comptes_a_payer de M5) · fiche client_importe (registre clients_importes de M2)
```

## 2. Dépôt sûr (`depot.py`)

- **Nom seul** : `[A-Za-z0-9][A-Za-z0-9._ -]{0,119}` + extension de la liste fermée, sans `..` ; le dossier de dépôt ne
  peut pas être un lien ; le fichier est ouvert avec `O_NOFOLLOW`, doit être ordinaire, non vide, ≤ 32 Mio.
- **Types fermés** : `.pdf`, `.png`, `.jpg`/`.jpeg`, `.txt`, `.csv`, `.xlsx`, et `.zip` au premier niveau. L'extension
  ET la signature doivent concorder (un `.pdf` qui n'est pas un PDF est `REJ-ING-TYPE-INCOHERENT`).
- **Archive** — refusée EN ENTIER au premier signe d'attaque : nom absolu, `..`, `\`, lettre de lecteur, nom non
  imprimable (`REJ-ING-ZIP-TRAVERSEE`) ; lien symbolique (`REJ-ING-ZIP-LIEN`) ; deux noms égaux à la casse près
  (`REJ-ING-ZIP-NOM-REPETE`) ; plus de 500 membres, plus de 128 Mio décompressés, ratio > 100 sur un membre de plus de
  64 Kio, taille déclarée mensongère (`REJ-ING-ZIP-BOMBE`) ; archive illisible (`REJ-ING-ZIP-ILLISIBLE`). Refus d'un
  MEMBRE seulement : chiffré (`REJ-ING-ZIP-CHIFFRE`), archive imbriquée (`REJ-ING-ZIP-IMBRIQUE`), type non accepté,
  plus de 8 Mio (`REJ-ING-FICHIER-TROP-GROS`). `__MACOSX/`, `.DS_Store`, `Thumbs.db`, `desktop.ini` sont ignorés.
- **Dédoublonnage exact** : un seul ORIGINAL conservé par SHA-256 (index unique partiel) ; une copie, dans le même lot
  ou un autre, devient un document `DOUBLON` qui pointe vers l'original, sans contenu ni tâche.
- **Idempotence** : (acteur, `mutation_id`) ; même clé et même fichier = rejeu du lot ; autre fichier =
  `REJ-ING-MUTATION-CONFLIT`.
- **Chiffrement au repos** : originaux, résultats d'étape et contenus des brouillons sont scellés en AES-256-GCM avec
  la clé externe du pilote Fusion (`OPSYS_INGESTION_CLE`, ou la référence `OPSYS_INGESTION_CLE_REFERENCE`, ou le
  fichier privé `OPSYS_INGESTION_ENV_FILE`) ; l'AAD lie nature, identifiant et empreinte. Les colonnes en clair ne
  portent que des métadonnées (statuts, types, codes, compteurs). Clé absente : `REJ-ING-CLE-INDISPONIBLE`.
- **Quotas** (`taches.QUOTAS`) : 8 lots en cours, 500 documents et 64 Mio par lot, 20 000 documents et 2 Gio conservés
  au total, 3 tentatives par tâche, bail de 120 s, délai de reprise 30 s doublé à chaque tentative.

## 3. Table de tâches durable (`taches.py`) — choix « table » plutôt que « registre »

Les registres hash-chaînés des départements sont append-only : parfaits pour les faits définitifs, inadaptés à une file
dont les lignes changent d'état (bail, tentative, résultat). La phase 1 utilise donc **cinq tables SQLite** (migration
`0038`, additive ; rétrogradation refusée dès qu'une ligne existe) ; les faits définitifs restent dans les registres
existants de M5 et de M2.

| Table | Rôle |
|---|---|
| `ingestion_lots` | Un dépôt : acteur, clé de mutation, source SHA-256, statut `EN_COURS`/`TERMINE`, référence de clé. |
| `ingestion_documents` | Un document : rang, nom, type, classe, statut, code, `doublon_de`, original chiffré. |
| `ingestion_taches` | Une tâche par (document, étape) — **clé d'idempotence unique** ; statut, tentatives, porteur, échéance de bail, disponibilité, résultat chiffré et son empreinte. |
| `ingestion_journal` | Journal append-only (déclencheurs SQLite et PostgreSQL) : identifiants, étapes, codes, compteurs ; jamais un contenu. |
| `ingestion_brouillons` | Un brouillon : genre, clé métier unique, statut, raisons (codes), clés fortes (empreintes), contenu chiffré, révision (CAS), décision humaine, référence définitive. |

États d'une tâche : `EN_ATTENTE` → `BAIL` → `TERMINEE` ; `BAIL` → `ECHEC_REPRENABLE` (panne temporaire, délai croissant)
→ `BAIL` … ; tentatives épuisées ou échec définitif → `FILE_MORTE` ; les étapes suivantes d'un document arrêté → `SAUTEE`.
Un **bail expiré** rend la tâche réservable (même ligne, tentative suivante). Une étape n'est réservable que si la
précédente du même document est `TERMINEE`.

**Exactement une fois.** Chaque tâche s'exécute en trois temps : réserver (transaction 1) ; travailler HORS
transaction (worker PDF isolé, fournisseur) ; conclure (transaction 2) par **CAS** sur (statut `BAIL`, porteur,
révision), ses effets (brouillons) écrits dans la même transaction. Un arrêt brutal entre 1 et 2 laisse la tâche en bail
(reprise à l'échéance) ; un arrêt pendant 2 annule la transaction avec son brouillon ; un porteur dont le bail a été
repris ne peut plus rien écrire. Les étapes sont déterministes : refaire une étape interrompue donne le même résultat.

**Interface DBOS.** Le service ne parle qu'au protocole `PortTaches` (`creer_lot`, `reserver`, `terminer`, `echouer`,
`sauter_suivantes`, `resultat`, `journaliser`, `rafraichir_lot`…). À la bascule PostgreSQL, un adaptateur DBOS Transact
(MIT) le remplacera : l'identifiant de workflow DBOS sera la clé `(document, étape)`, le bail son verrou d'exécution,
`ECHEC_REPRENABLE` sa politique de reprise. **Non implémenté ici.**

Dans un appel d'outil, tout l'avancement tient dans la transaction de l'outil (points de sauvegarde imbriqués) ; la
CLI `opsys metier onboarding avancer` valide chaque tâche dans sa propre transaction : c'est le chemin conseillé pour un
gros lot.

## 4. Étapes

1. **empreinte** — l'original déchiffré a toujours son SHA-256 (`REJ-ING-CONTENU-CORROMPU` sinon).
2. **type** — signature et extension revérifiées.
3. **texte** — réutilise l'existant : PDF natif par le worker isolé de `opsys.fusion_pdf` (pypdf dans bubblewrap) ;
   PDF scanné (`PDF_IMAGE_OU_MIXTE`, `PDF_SANS_TEXTE`) par l'OCR local `opsys.ocr_runtime` (Tesseract dans bubblewrap)
   si `OPSYS_OCR_BUNDLE` est configuré, sinon `REJ-ING-OCR-INDISPONIBLE` ; image PNG/JPEG :
   `REJ-ING-IMAGE-NON-TRAITEE` ; texte UTF-8/UTF-16/Windows-1252 ; CSV et `.xlsx` par le lecteur de tableaux de
   l'import QuickBooks (M5). Isolation absente : `REJ-ING-ISOLATION-INDISPONIBLE`, reprenable.
4. **classement** — règles déterministes : premier mot-clé de genre dans les 5 premières lignes (facture, soumission,
   contrat), en-tête de liste de clients pour un tableau. Soumissions et contrats : `REJ-ING-CLASSE-NON-PEUPLEE` ;
   rien reconnu : `REJ-ING-CLASSE-INCONNUE`. Le document reste au lot, classé, non traité.
5. **extraction** — facture : **port** `port_extraction` ; le fournisseur est celui que le registre de fournisseurs
   résout pour la capacité `llm` de M5 (sélection de M5, sinon défaut global) ; inactif, devenu non conforme à la
   politique de licence ou absent : `REJ-ING-FOURNISSEUR-REFUSE` (avec le code du registre), **jamais un autre**.
   Un fournisseur conforme n'est appelé que par un adaptateur raccordé à son point d'accès : **aucun n'est raccordé en
   production dans cette tranche** (`REJ-ING-EXTRACTEUR-NON-RACCORDE`, aucun appel réseau). Les tests raccordent un
   fournisseur SIMULÉ déterministe déclaré, activé et sélectionné au vrai registre. Liste de clients : lecture des
   lignes par M2 (sans fournisseur).
6. **validation** — facture : `validation_facture_onboarding.valider` de M5 (§5) ; liste : fiches proposées par M2 (§6).
   Une facture émise par l'entreprise elle-même (facture client) : `REJ-ING-CLASSE-NON-PEUPLEE`.
7. **proposition** — brouillons, avec dédoublonnage : une facture de même fournisseur (normalisé) et même numéro qu'un
   brouillon existant s'y rattache ; une fiche client dont une clé forte égale celle d'un brouillon ou d'un client déjà
   importé s'y rattache, sans nouveau brouillon.

## 5. Validation déterministe des factures (M5)

Schéma strict `opsys.facture/v1` (clés exactes, montants en TEXTE décimal, jamais un nombre JSON) ; chaque ligne
quantité × prix arrondi au cent = montant ; somme des lignes = sous-total ; TPS 5 % et TVQ 9,975 % **recalculées** sur
le sous-total par `taxes.calculer_taxes` (taux versionnés, `ROUND_HALF_UP` au cent, la règle citée dans `taxes.py`) et
comparées au cent ; total imprimé = sous-total + taxes recalculées ; numéros TPS `123456789 RT 0001` et TVQ
`1234567890 TQ 0001` (forme seulement, aucun appel à l'ARC ni à Revenu Québec, aucun chiffre de contrôle supposé) ;
taxe facturée sans numéro ; date réelle, pas après le dépôt, pas plus de 10 ans avant ; échéance pas avant la date ;
émetteur nommé ; CAD ; sous-total > 0 ; sens de la facture contre l'identité fiscale déclarée
(`entreprise.yaml`, clé `identite_fiscale: {nom_legal, tps, tvq}`). Toute incohérence est une raison avec les deux
chiffres ; le brouillon est `A_VERIFIER` ; **rien n'est corrigé**. Aucune tolérance : un cent est un écart.

Codes (`CODES_VALIDATION`) : `REJ-ING-FACTURE-SCHEMA`, `-DEVISE`, `-FOURNISSEUR-NON-IDENTIFIABLE`, `-NUMERO-INVALIDE`,
`-DATE-INVALIDE`, `-DATE-FUTURE`, `-DATE-ANCIENNE`, `-ECHEANCE-AVANT-DATE`, `-LIGNE-MONTANT`, `-SOMME-LIGNES`,
`-MONTANT-NON-POSITIF`, `-TPS-ECART`, `-TVQ-ECART`, `-TOTAL-ECART`, `-NO-TPS-FORME`, `-NO-TVQ-FORME`,
`-NO-TPS-ABSENT`, `-NO-TVQ-ABSENT`, `-TAUX-INDISPONIBLES`, `-EMISE-PAR-L-ENTREPRISE`, `-DESTINATAIRE-NON-RECONNU`.

**Validation humaine** : `m5_valider_brouillon_onboarding_ap` (T1/N3, file d'approbation, finance ou propriétaire).
Le brouillon doit être `PRET` et le rester à la **revalidation** (taux et identité relus au moment de décider) ; il
devient alors la facture **sans PO** saisie par le même chemin que `m5_saisir_facture_sans_po` (`_ranger_sans_po` :
catégorie de la liste configurée, taxes et total recalculés une troisième fois, doublon refusé) ; le brouillon passe
`VALIDE` avec la référence de la facture, dans la même transaction. Un brouillon `A_VERIFIER` ne se valide jamais tel
quel : la saisie manuelle reste le repli, puis on l'écarte (motif obligatoire). **Grand livre** : la facture saisie
est une facture fournisseur comme une autre ; `m5_generer_brouillons_comptables` en tire le brouillon (Dt charge de sa
catégorie / Dt CTI / Dt RTI / Ct comptes fournisseurs, montants relus de la pièce) par la correspondance DÉCLARÉE du
plan comptable (`correspondance_charges`, `departments/m05-financecore/docs/grand-livre.md`) ; une catégorie sans
compte déclaré n'a pas de brouillon (`REJ-GL-CATEGORIE-SANS-COMPTE`), jamais un compte supposé. Validation N4 humaine.

## 6. Clients importés et dédoublonnage (M2)

En-tête reconnu (FR/EN : nom ou prénom + nom de famille, et courriel, téléphone ou adresse) dans les 10 premières
lignes. Normalisation : nom (accents, casse, ponctuation, `&`, suffixes légaux inc/ltée/enr… retirés), courriel
(minuscules, forme vérifiée), téléphone (`+1XXXXXXXXXX`, extension retirée), adresse (abréviations rue/boul./ch./St…),
code postal canadien (`H2X 1Y4`). Règles FORTES (fusion proposée, expliquée : règle, lignes, valeur normalisée) :
courriel identique ; téléphone ET nom identiques ; nom ET adresse identiques. Règles FAIBLES (signalées, jamais
fondues) : téléphone seul, nom seul. Une valeur mal formée reste telle qu'écrite ; deux valeurs différentes d'un même
champ dans un groupe fondu sont un conflit. Splink n'est pas installé : aucune pondération probabiliste.

Codes (`CODES_RAISONS`) : `REJ-ING-CLIENT-NOM-ABSENT`, `-COURRIEL-INVALIDE`, `-TELEPHONE-INVALIDE`,
`-CODE-POSTAL-INVALIDE`, `-CONFLIT`, `-DOUBLON-PROBABLE`, `-ENTETE-INTROUVABLE`, `-TROP-DE-LIGNES`.

**Validation humaine** : `m2_valider_brouillon_onboarding_client` (T1/N3, file d'approbation). Valider crée un maillon
`client_importe` au registre DÉDIÉ `clients_importes` de M2 (append-only, hash-chaîné ; jamais le registre des leads),
`client_id` du Client 360 (`clients.identifiant_client`). Un conflit exige un `choix` parmi les valeurs OBSERVÉES ; une
valeur mal formée n'est jamais validée. Verdicts M2 : `REJ-CLIENT-IMPORT-INVALIDE`, `REJ-CLIENT-IMPORT-CHOIX-INVALIDE`,
`REJ-CLIENT-DEJA-IMPORTE`, et `REJ-HUMAIN-REQUIS`. M2 ne fusionne jamais deux leads ni deux clients connus : il ne fond
que des LIGNES d'un fichier importé, avant qu'aucune fiche n'existe.

## 7. Outils, CLI, console

| Outil | Autonomie / niveau | Rôle |
|---|---|---|
| `m5_deposer_lot_onboarding` | T1 / N1 | Créer (ou rejouer) le lot d'un fichier déposé. |
| `m5_avancer_lot_onboarding` | T1 / N1 | Exécuter au plus `budget` tâches ; rend compteurs et issues. |
| `m5_lire_lot_onboarding` | T0 | Compteurs ; `vue` documents ou brouillons (pages de 15) ; contenu d'un brouillon. |
| `m5_valider_brouillon_onboarding_ap` | T1 / N3 | Valider (saisie sans PO) ou écarter une facture proposée. |
| `m2_valider_brouillon_onboarding_client` | T1 / N3 | Valider (fiche définitive) ou écarter une fiche proposée. |
| `m2_lister_clients_importes` | T0 | Fiches définitives importées, paginées. |

Portée d'appareil **fermée** pour les six (aucune déclaration ; `docs/architecture/ROLES.md` : 232 outils déclarés sur
387). CLI : `opsys metier onboarding deposer <fichier> --mutation-id … --par …`, `avancer <lot> --par …`,
`lire <lot> [--vue documents|brouillons] [--brouillon <id> --par …]`, `lots`, `journal <lot>` (mutations et contenu :
authentification personnelle `nathan_owner`, `admin` ou `finance`). Console : `/onboarding`,
`/onboarding/lots/{lot}` et leurs pendants `/api/onboarding/…`, en lecture, métadonnées seulement, rôle
d'administration relu avant et après la lecture.

## 8. Codes du socle (`codes.CODES_ING`, liste fermée)

Dépôt : `REJ-ING-NOM-INVALIDE`, `REJ-ING-DOSSIER-INVALIDE`, `REJ-ING-FICHIER-ABSENT`, `REJ-ING-FICHIER-TROP-GROS`,
`REJ-ING-FICHIER-VIDE`, `REJ-ING-TYPE-NON-ACCEPTE`, `REJ-ING-TYPE-INCOHERENT`, `REJ-ING-ZIP-ILLISIBLE`,
`REJ-ING-ZIP-TRAVERSEE`, `REJ-ING-ZIP-LIEN`, `REJ-ING-ZIP-BOMBE`, `REJ-ING-ZIP-NOM-REPETE`, `REJ-ING-ZIP-CHIFFRE`,
`REJ-ING-ZIP-IMBRIQUE`, `REJ-ING-LOT-VIDE`.
Lot : `REJ-ING-MUTATION-INVALIDE`, `REJ-ING-MUTATION-CONFLIT`, `REJ-ING-QUOTA-LOTS`, `REJ-ING-QUOTA-DOCUMENTS`,
`REJ-ING-QUOTA-OCTETS`, `REJ-ING-CLE-INDISPONIBLE`, `REJ-ING-CHIFFREMENT-INDISPONIBLE`, `REJ-ING-CONTENU-CORROMPU`,
`REJ-ING-LOT-INCONNU`, `REJ-ING-ACTEUR-INVALIDE`, `REJ-ING-ARGUMENT-INVALIDE`.
Étapes : `REJ-ING-TEXTE-ILLISIBLE`, `REJ-ING-PDF-REFUSE`, `REJ-ING-ISOLATION-INDISPONIBLE`, `REJ-ING-OCR-INDISPONIBLE`,
`REJ-ING-OCR-REFUSE`, `REJ-ING-IMAGE-NON-TRAITEE`, `REJ-ING-TABLEAU-ILLISIBLE`, `REJ-ING-CLASSE-INCONNUE`,
`REJ-ING-CLASSE-NON-PEUPLEE`, `REJ-ING-FOURNISSEUR-REFUSE`, `REJ-ING-EXTRACTEUR-NON-RACCORDE`,
`REJ-ING-EXTRACTION-INVALIDE`, `REJ-ING-PROFIL-INVALIDE`, `REJ-ING-FILE-MORTE`.
Brouillons : `REJ-ING-BROUILLON-INCONNU`, `REJ-ING-BROUILLON-GENRE`, `REJ-ING-BROUILLON-REVISION`,
`REJ-ING-BROUILLON-A-VERIFIER`, `REJ-ING-BROUILLON-DEJA-DECIDE`, `REJ-ING-DECISION-INVALIDE`, `REJ-ING-MOTIF-REQUIS`.

Statut d'un document selon son verdict : `REFUSE` (type, contenu corrompu, PDF refusé, texte ou tableau illisible),
`NON_TRAITE` (classe inconnue ou non peuplée, image, OCR indisponible, fournisseur refusé, file morte…), `A_VERIFIER`
(au moins un brouillon à vérifier ou une ligne refusée), `TERMINE`, `DOUBLON`.

## 9. Ce qui n'est pas fait (limites)

- **Docling** n'est pas installé : aucun parsing de mise en page ; le texte vient du worker natif pypdf et de l'OCR
  Tesseract existants. Pas de positions ni de boîtes englobantes par champ.
- **VLM / LLM réel** : aucun adaptateur raccordé, aucun appel réseau. Les images PNG/JPEG ne sont pas traitées.
- **PostgreSQL / DBOS** : la table de tâches est qualifiée sur SQLite seulement ; l'adaptateur DBOS n'existe pas.
- **Courriels historiques** (mbox, PST, EML) et connecteurs (Gmail, Graph, Drive) : non traités.
- **Apprentissage du profil d'entreprise** et pack sectoriel : non faits ; l'identité fiscale se déclare à la main.
- **Factures clients, soumissions, contrats** : classés, non peuplés (aucun brouillon AR, M3 ni contrat).
- **Grand livre** : le brouillon vient de la génération du grand livre, pas de l'ingestion (voir §5) ; les comptes de
  charge proposés sont à valider par le CPA.
- Splink non installé ; dédoublonnage par règles déterministes seulement. Une fiche d'un lot suivant qui recoupe un
  brouillon existant s'y rattache sans l'enrichir. Une tâche en file morte ne se relance pas encore (nouveau dépôt).
- Le fournisseur simulé des tests (`tests/fixtures/ingestion_onboarding_qa.py`) n'est pas une capacité livrée ; le
  corpus (`tests/fixtures/ingestion_onboarding/`) est fictif et ne mesure aucune précision sur de vraies factures.
