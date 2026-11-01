# Grand livre en partie double — M5, tranche 1

Code : `src/m5_financecore/grand_livre.py` (noyau pur), `plan_comptable.py`, `grand_livre_beancount.py`, adaptateur et
outils dans `outils.py` (section « grand livre »). Plan par défaut : `contracts/plan_comptable_pme_qc.v1.yaml`.
Tests : `tests/test_grand_livre.py` (noyau), `tests/test_grand_livre_outils.py` (vrai socle, file N4).

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
| `piece` | `facture_client` ou `facture_fournisseur` (existence vérifiée dans le registre M5) ; `paie_preparatoire`, `releve_bancaire`, `recu`, `manuelle` (déclarées : `verification = declaree_non_verifiee`). |
| `cle_piece` | Idempotence : `auto:facture_client:<id>:emission|paiement`, `saisie:<type>:<référence>`, `contre_passation:<écriture>`. Une clé = une écriture. |
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

Une facture illisible ou incohérente est ignorée avec `REJ-GL-SOURCE-ILLISIBLE`, jamais complétée.

## Lectures

- `m5_lire_balance_verification(au)` : par compte, débits, crédits, solde et côté ; `equilibree` prouve débits =
  crédits ; brouillons comptés à part, jamais additionnés.
- `m5_lire_grand_livre_compte(compte, debut, fin)` : solde d'ouverture, lignes et solde courant, solde de clôture.
- `m5_rapprocher_grand_livre(debut, fin)` : équilibre total et par écriture ; TPS/TVQ à percevoir du grand livre contre
  `taxes.calculer_taxes` sur les factures émises de la même période, écart par facture. CTI/RTI rendus en solde, non
  rapprochés.
- Export Beancount (`grand_livre_beancount.exporter_beancount` / `ecrire_fichier_beancount`) : `open` par compte, une
  transaction par écriture définitive, somme nulle. Base de la contre-vérification nocturne future (processus séparé) ;
  aucune dépendance à beancount ici.

Portée d'appareil : **fermée** pour les huit outils ; une identité d'appareil est refusée dans le code.

## Plan comptable

Base versionnée (`2026-v1`) : actif, passif, capitaux propres, produits, charges ; TPS à percevoir (2300) / CTI (1400),
TVQ à percevoir (2310) / RTI (1410), retenues à la source (2400, 2410), cotisations de l'employeur (2420–2440), salaires
à payer (2200). Extension du client : `department.yaml/configuration.grand_livre` (`comptes_ajoutes`,
`comptes_desactives`) ; la version effective devient `2026-v1+client.<empreinte>`.

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
| `REJ-GL-SOURCE-ILLISIBLE` | Fait M5 inutilisable pour un brouillon (ignoré). |
| `REJ-GL-HUMAIN-REQUIS` | Validation ou clôture sans approbation humaine en cours. |
| `REJ-GL-PLAN-INVALIDE` | Plan de base ou extension du client invalide. |
| `REJ-GL-LIMITE-INVALIDE` / `REJ-GL-STOCKAGE-NON-DURABLE` | Pagination invalide / registre durable absent. |
| `REJ-IDENTITE-APPAREIL-INVALIDE` | Appel d'appareil (portée fermée). |

## Ce qui n'est pas couvert (tranche 1)

États financiers complets (bilan, résultats, flux de trésorerie), écritures de fin d'exercice et report des résultats,
amortissement, consolidation, multi-devises, réouverture de période, génération depuis les factures fournisseurs, la
paie, le rapprochement bancaire CSV et les remises de taxes (saisie manuelle seulement), rapprochement des CTI/RTI,
contre-vérification par Beancount réel (`bean-check`, processus séparé à venir), lectures depuis l'app mobile.
