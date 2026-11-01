# Grand livre en partie double — M5, tranche 1

Code : `src/m5_financecore/grand_livre.py` (noyau pur), `plan_comptable.py`, `grand_livre_beancount.py`, adaptateur et
outils dans `outils.py` (section « grand livre »). Plan par défaut : `contracts/plan_comptable_pme_qc.v1.yaml`.
Tests : `tests/test_grand_livre.py` (noyau), `tests/test_grand_livre_outils.py` (vrai socle, file N4),
`tests/test_grand_livre_fournisseurs.py` et `tests/test_grand_livre_fournisseurs_outils.py` (factures fournisseurs,
CTI/RTI), `tests/test_ingestion_onboarding_grand_livre.py` à la racine (facture d'onboarding jusqu'au grand livre).

Toute sortie porte la mention obligatoire de M5 et « À valider auprès d'un comptable (CPA) / professionnel qualifié ».
Ce grand livre prépare la tenue des livres ; il ne remplace ni le CPA ni des états financiers vérifiés.

## Stockage

Registre DÉDIÉ `m05-financecore/grand_livre`, append-only et hash-chaîné (`registre.py` sur `opsys.stockage.maillons`,
la table de registres déjà migrée) : **aucune migration**. Le registre suffit parce qu'une écriture n'est jamais
modifiée (immuabilité par construction), que chaque appel d'outil est une transaction (une écriture et sa validation
réussissent ou échouent entières), que le rang unique protège des écritures concurrentes, et que la chaîne
(`valider_chaine`) et l'empreinte de contenu de chaque écriture font refuser toute lecture d'un registre altéré
(`REJ-GL-CHAINE-INVALIDE`). Coût accepté : chaque lecture relit le registre en entier (volume d'une PME ; des tables
indexées viendront si la mesure l'exige). Le registre des mouvements n'est jamais lu ni écrit
(`conformite.verifier_aucun_decaissement`, strict).

Concurrence : deux appels qui auraient lu le même état et écrit la même proposition (ou la même validation) laissent
un doublon ; le premier maillon fait foi, le suivant est ignoré et compté (`doublons_ignores`), la lecture continue.
Le numéro d'une définitive est recalculé à la lecture (rang parmi les validations).

Maillons : `gl_ecriture_proposee` (le brouillon complet), `gl_ecriture_validee` (qui, quand, voie, numéro, empreinte du
brouillon validé), `gl_periode_cloturee` (mois, fin, qui, totaux).

## Contrat d'une écriture

| Champ | Règle |
|---|---|
| `date_effet` | `AAAA-MM-JJ` ; postérieure à la date de verrouillage (fin du dernier mois clos). |
| `piece` | `facture_client` ou `facture_fournisseur` (existence vérifiée dans le registre M5) ; `paie_preparatoire`, `releve_bancaire`, `recu`, `manuelle` (déclarées : `verification = declaree_non_verifiee`) ; `import_quickbooks` (déclarée, créée par l'import seulement, `import-quickbooks.md`). |
| `cle_piece` | Idempotence : `auto:facture_client:<id>:emission|paiement`, `auto:facture_fournisseur:<id>:saisie`, `saisie:<type>:<référence>`, `contre_passation:<écriture>`. Une clé = une écriture. |
| `lignes` | Au moins deux ; chacune un débit OU un crédit, texte décimal, strictement positif, au cent, sur un compte ACTIF du plan. |
| Équilibre | Somme des débits = somme des crédits, sinon rien n'est écrit. |
| `devise` | CAD seulement. |
| `plan_comptable_version` | Version effective du plan au moment de la proposition. |

Cycle : **BROUILLON** (T1/N1, automatique) → **DÉFINITIVE** par `m5_valider_ecriture_comptable` (T2/**N4**, écriture
finale) : l'appel attend dans la file ; l'outil n'agit que pour l'humain qui l'a approuvée (`nathan_owner` ou
`finance`, dit par `approbations.approbateur_en_cours`), jamais pour un agent seul, y compris en mode `autonome`. La
validation revérifie l'équilibre, les comptes au plan courant et la période. Une définitive ne se modifie jamais : elle
se corrige par `m5_proposer_contre_passation` (brouillon aux lignes inversées, lié, motif obligatoire, à valider).

Périodes : mensuelles, clôture cumulative (`m5_clore_periode_comptable`, N4) : clore septembre verrouille tout ce qui
est daté au plus tard le 30 septembre (proposition et validation). Les brouillons laissés en plan sont listés ; ils ne
sont plus validables. Pas de réouverture en tranche 1.

## Brouillons générés depuis les faits M5

`m5_generer_brouillons_comptables` (idempotent, borné par appel) :

| Fait M5 | Écriture brouillon |
|---|---|
| Facture client émise (ENVOYEE ou PAYEE, `date_envoi`) | Dt 1100 Comptes clients (après taxes) / Ct 4100 Revenus (avant taxes) / Ct 2300 TPS à percevoir / Ct 2310 TVQ à percevoir (taxes facturées) |
| Paiement reçu (PAYEE, `date_paiement` ; dépôt déjà contrôlé égal au dû) | Dt 1010 Banque / Ct 1100 Comptes clients |
| Facture fournisseur saisie (comptes à payer, état courant `SAISIE` ou `CORRIGEE`, `date_facture`) — avec ou sans PO, saisie à la main ou validée depuis l'ingestion d'onboarding | Dt compte de charge (correspondance ci-dessous) du montant avant taxes / Dt 1400 CTI de la TPS payée / Dt 1410 RTI de la TVQ payée / Ct 2100 Comptes fournisseurs du total après taxes |
| Paiement fournisseur | **Aucun brouillon** : le registre des comptes à payer ne porte aucun paiement (payer un fournisseur est N5, hors de M5). Le paiement se saisit à la main (`m5_proposer_ecriture_comptable`, pièce `releve_bancaire` ou `recu` : Dt 2100 / Ct 1010). |

Les montants sont **relus de la pièce**, jamais recalculés : avant taxes + total des taxes = après taxes, somme des
taxes détaillées (TPS, TVQ seulement) = total des taxes, chaque taxe positive ou nulle, au cent. Une facture illisible
ou incohérente (montants, taxes, date) est ignorée avec `REJ-GL-SOURCE-ILLISIBLE` ; une facture fournisseur sans compte
de charge déclaré est ignorée avec `REJ-GL-CATEGORIE-SANS-COMPTE` ; jamais complétée. La réponse dit aussi
`categories_sans_compte` : les catégories de `configuration.categories_depense_sans_po` que la correspondance ne range
nulle part. Une facture fournisseur ANNULÉE ne donne aucun brouillon ; si elle en avait déjà un, il reste (brouillon :
ne pas le valider ; définitif : le contre-passer), et le rapprochement CTI/RTI le signale. Une facture CORRIGÉE après
son brouillon produit `REJ-GL-PIECE-CONFLIT` à la génération suivante (même règle que les factures clients) :
contre-passer puis saisir la bonne écriture à la main. Les crédits sont supposés récupérables à 100 % (comme le cash
libre) : à valider par le CPA.

### Correspondance catégorie de dépense → compte de charge

Déclarée dans le plan versionné (`correspondance_charges`, depuis `2026-v2`), jamais supposée :

| Pièce | Compte de charge proposé |
|---|---|
| Facture sur PO (bon de commande M6, gestion des matériaux : aucune catégorie) | `factures_sur_po` : 5100 Matériaux utilisés |
| Facture sans PO, catégorie `carburant` | 5400 Carburant et entretien des véhicules |
| Facture sans PO, catégorie `materiaux` | 5100 Matériaux utilisés |
| Facture sans PO, catégorie `marketing` | 5950 Publicité et marketing |
| Facture sans PO, catégorie `outils` | 5500 Outils et petit équipement |

Ces entrées sont les catégories que le dépôt connaît (exemples de `department.yaml`, ingestion d'onboarding, coûts
marketing) ; la liste fermée réelle est celle du propriétaire (`categories_depense_sans_po`, GATE NATHAN). **Les noms et
le choix des comptes de charge sont proposés, à valider par le CPA de l'entreprise** (par exemple, des achats sur PO
mis en stock relèvent peut-être de 1200 Stocks de matériaux plutôt que d'une charge). Au chargement, chaque compte visé
doit exister au plan effectif, y être actif et de type charges (5xxx à 9xxx), et le plan doit déclarer les rôles
`comptes_fournisseurs`, `tps_cti` et `tvq_rti` ; sinon le plan entier est refusé (`REJ-GL-CORRESPONDANCE-INVALIDE`).
Une catégorie absente de la correspondance n'a pas de compte : ses factures sont ignorées
(`REJ-GL-CATEGORIE-SANS-COMPTE`).

Extension par le client (`department.yaml/configuration.grand_livre`, relue à chaque appel, change la version effective
comme les comptes) :

```yaml
configuration:
  grand_livre:
    comptes_ajoutes:
      - {numero: "5450", nom: "Location d'équipement", type: charges}
    correspondance_charges:
      categories_depense: {location: "5450", carburant: "5990"}   # ajoute « location », redirige « carburant »
      factures_sur_po: "5100"                                      # facultatif : redirige les factures sur PO
    categories_depense_retirees: [marketing]                       # ses factures n'auront plus de brouillon
```

Désactiver un compte encore visé par la correspondance est refusé (`REJ-GL-CORRESPONDANCE-INVALIDE`) : rediriger ou
retirer l'entrée dans la même extension.

## Lectures

- `m5_lire_balance_verification(au)` : par compte, débits, crédits, solde et côté ; `equilibree` prouve débits =
  crédits ; brouillons comptés à part, jamais additionnés.
- `m5_lire_grand_livre_compte(compte, debut, fin)` : solde d'ouverture, lignes et solde courant, solde de clôture.
- `m5_rapprocher_grand_livre(debut, fin)` : équilibre total et par écriture ; TPS/TVQ à percevoir du grand livre contre
  `taxes.calculer_taxes` sur les factures émises de la même période, écart par facture ; **CTI/RTI** (`intrants`) :
  mouvement net débiteur de 1400 et 1410 dans la période contre la TPS et la TVQ PAYÉES que portent les factures
  fournisseurs vivantes datées dans la période (relues, pas recalculées), écart par facture fournisseur (sans écriture
  définitive, montant différent, mouvement sans facture vivante de la période — une facture annulée après coup —, ou
  mouvement d'une autre pièce : un reçu saisi à la main est un écart nommé, jamais absorbé), et le solde débiteur à la
  fin. Une facture fournisseur illisible est listée (`factures_fournisseurs_illisibles`) et rend le verdict `ECART`.
- Export Beancount (`grand_livre_beancount.exporter_beancount` / `ecrire_fichier_beancount`) : `open` par compte, une
  transaction par écriture définitive, somme nulle. Base de la contre-vérification nocturne future (processus séparé) ;
  aucune dépendance à beancount ici.

Portée d'appareil : **fermée** pour les huit outils ; une identité d'appareil est refusée dans le code.

Reprise d'un historique QuickBooks Online (exports CSV/Excel, brouillons en lot, validation en lot N4) : `import-quickbooks.md`. Les lots passent par `proposer_ecritures_lot` et `valider_ecritures_lot` (tout ou rien, mêmes règles que l'écriture unitaire) ; la pièce `import_quickbooks` n'est jamais saisie à la main.

## Plan comptable

Base versionnée (`2026-v2` ; les comptes sont ceux de `2026-v1`, la version ajoute la correspondance des charges) : actif, passif, capitaux propres, produits, charges ; TPS à percevoir (2300) / CTI (1400),
TVQ à percevoir (2310) / RTI (1410), retenues à la source (2400, 2410), cotisations de l'employeur (2420–2440), salaires
à payer (2200). Extension du client : `department.yaml/configuration.grand_livre` (`comptes_ajoutes`,
`comptes_desactives`, et la correspondance des charges ci-dessus) ; la version effective devient
`2026-v2+client.<empreinte>`.

## Codes de refus

| Code | Quand |
|---|---|
| `REJ-GL-ECRITURE-DESEQUILIBREE` | Débits ≠ crédits (aussi : balance à clôturer déséquilibrée). |
| `REJ-GL-LIGNES-INSUFFISANTES` | Moins de deux lignes. |
| `REJ-GL-LIGNE-INVALIDE` | Ligne mal formée, débit ET crédit, ni l'un ni l'autre, plus de 50 lignes. |
| `REJ-GL-MONTANT-INVALIDE` | Pas un texte décimal (nombre JSON), non fini, nul ou négatif, plus de deux décimales, hors domaine. |
| `REJ-GL-COMPTE-INCONNU` / `REJ-GL-COMPTE-INACTIF` | Compte absent du plan effectif / désactivé par le client. |
| `REJ-GL-DATE-INVALIDE` | Date mal formée ; contre-passation antérieure à l'original ; intervalle inversé. |
| `REJ-GL-PERIODE-CLOSE` | Date au plus tard à la fin du dernier mois clos. |
| `REJ-GL-PERIODE-INVALIDE` / `REJ-GL-PERIODE-DEJA-CLOSE` | Mois mal formé / déjà couvert par une clôture. |
| `REJ-GL-PIECE-INVALIDE` / `REJ-GL-PIECE-INTROUVABLE` | Type ou référence de pièce invalide / pièce M5 citée absente. |
| `REJ-GL-PIECE-CONFLIT` | Même pièce, autre contenu (contre-passer ou citer une autre pièce). |
| `REJ-GL-ECRITURE-INTROUVABLE` / `REJ-GL-ECRITURE-DEJA-VALIDEE` | Écriture inconnue / déjà définitive. |
| `REJ-GL-ECRITURE-NON-DEFINITIVE` | Contre-passation d'un brouillon. |
| `REJ-GL-DEJA-CONTRE-PASSEE` / `REJ-GL-CONTRE-PASSATION-INVALIDE` | Déjà contre-passée / contre-passation d'une contre-passation. |
| `REJ-GL-MOTIF-REQUIS` | Contre-passation sans motif. |
| `REJ-GL-CHAMP-INVALIDE` | Libellé ou horodatage invalide. |
| `REJ-GL-CHAINE-INVALIDE` | Registre altéré (chaîne, empreinte, maillon étranger). |
| `REJ-GL-SOURCE-ILLISIBLE` | Fait M5 inutilisable pour un brouillon (ignoré) : montants, taxes ou date illisibles ou incohérents. |
| `REJ-GL-CATEGORIE-SANS-COMPTE` | Facture fournisseur dont la catégorie (ou, sur PO, `factures_sur_po`) n'a pas de compte de charge déclaré (ignorée). |
| `REJ-GL-CORRESPONDANCE-INVALIDE` | Correspondance des charges invalide : forme, catégorie mal nommée, compte inconnu, désactivé ou hors des charges, rôles fournisseurs absents, retrait d'une catégorie inconnue. |
| `REJ-GL-HUMAIN-REQUIS` | Validation ou clôture sans approbation humaine en cours. |
| `REJ-GL-PLAN-INVALIDE` | Plan de base ou extension du client invalide. |
| `REJ-GL-LIMITE-INVALIDE` / `REJ-GL-STOCKAGE-NON-DURABLE` | Pagination invalide / registre durable absent. |
| `REJ-IDENTITE-APPAREIL-INVALIDE` | Appel d'appareil (portée fermée). |

## Ce qui n'est pas couvert (tranche 1)

États financiers complets (bilan, résultats, flux de trésorerie), écritures de fin d'exercice et report des résultats,
amortissement, consolidation, multi-devises, réouverture de période, génération depuis la paie, les paiements
fournisseurs (absents du registre des comptes à payer), le rapprochement bancaire CSV et les remises de taxes (saisie
manuelle seulement), taxes d'une facture fournisseur partiellement récupérables (crédit supposé à 100 %), ventilation
d'une facture fournisseur sur plusieurs comptes de charge (un compte par facture), contre-vérification par Beancount réel (`bean-check`, processus séparé à venir), lectures depuis l'app mobile.
