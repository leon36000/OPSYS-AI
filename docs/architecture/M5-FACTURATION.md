# M5 FinanceCore — facturation par jalons, numérotation, échéance et PDF (M5-FACT-1, M5-FACT-2)

Branche `claude/m5-facturation-jalons`, base `e0424b040`. Source d'exigences : l'analyse d'écart des anciens prompts de
Nathan (`docs/reprise/PROMPTS-NATHAN-ANCIENS/ANALYSE-M5.md`, lignes B2 et B3 et backlog M5-FACT-1/FACT-2). **Aucune migration** :
les trois nouveaux registres sont des chaînes de hachage append-only sur `stockage.maillons` (comme le grand livre), donc
portables SQLite et PostgreSQL sans garde. Aucun nouvel événement : le catalogue, `INTERCONNEXION.md` et les cinq garanties
d'événement sont inchangés (voir « Raccord avec M2 et M8 »).

## Règle d'or

Rien ne s'invente, rien ne s'envoie, rien ne se paie sans une personne.

- Le **plan** (jalons, pourcentages ou montants) est **déclaré par une personne** (N3, propriétaire ou finance). Absent ou faux,
  le refus dit quoi déclarer ; la somme des montants avant taxes des jalons égale le prix du devis **au cent**, exactement.
- Les **chiffres** viennent du code : montants des jalons (ROUND_HALF_UP, le solde absorbe l'arrondi), taxes TPS/TVQ du moteur
  fiscal existant (`taxes.py`, taux versionnés et sourcés ; aucun taux écrit ici), échéance, retard, totaux du PDF. Aucun
  modèle ne produit un chiffre.
- **Émettre** une facture reste `m5_envoyer_facture` : **N4, décision humaine du socle**, plafond d'envoi automatique **zéro**.
  C'est à l'émission que le numéro et l'échéance sont fixés. Un agent seul n'obtient jamais l'émission d'une facture
  numérotée ou de jalon, **même si le département passe en mode « autonome »** (`REJ-OPS-HUMAIN-REQUIS`).
- **Payer** reste `m5_enregistrer_paiement_facture` (N5, propriétaire et attestation). Un paiement partiel n'est jamais `PAYEE`.
- Aucune facture finale, remise ou crédit sans humain : le solde est une facture comme les autres (BROUILLON puis N4) ; il
  n'existe aucune remise ; une note de crédit reste `m5_proposer_note_credit` (brouillon, validation N4).
- Tout avis comptable ou fiscal porte « À valider auprès d'un comptable (CPA) / professionnel qualifié ».

## Ce qui a changé

| Avant | Maintenant |
|---|---|
| Une seule facture active par devis (`REJ-FACTURE-DEVIS-DEJA-FACTURE`) | Un devis facturé **par jalons** porte une facture active **par jalon**, chacune liée à son plan et à son rang ; la facture globale devient impossible (et l'inverse) |
| Identifiant de facture fourni, aucun numéro | **Numéro séquentiel** sans trou ni doublon (registre `numerotation_factures`), fixé à l'émission |
| Aucune échéance sur la facture (la politique de relance avait son délai général) | **Échéance** = jour d'émission + délai de paiement déclaré (celui du jalon, sinon `conditions_paiement`) |
| Statuts `BROUILLON`, `ENVOYEE`, `PAYEE`, `ANNULEE` | Même statut ENREGISTRÉ ; **« en retard » est une vue calculée** à une date injectée (`EN_RETARD` : échéance strictement dépassée) |
| Aucun PDF | **PDF déterministe** de la facture approuvée et de l'**état de compte**, empreinte SHA-256 **scellée** |

## Architecture

- **Noyaux purs** (aucun import `opsys`, aucune horloge, aucun réseau) : `facturation_jalons.py` (plan, factures de jalon,
  numérotation, résumé), `facture_pdf.py` (contenu structuré, rendu ReportLab, scellé), `verdicts_facturation.py` (catalogue
  fermé `REJ-PLAN-*`, `REJ-NUMEROTATION-*`, `REJ-CONDITIONS-*`, `REJ-PDF-*`, à part de `validation.py`, épinglé par empreinte pour
  la paie). Extensions de `facturation.py` : `rattachement_plan` (facture de jalon), `emission` (numéro/échéance dans le maillon
  d'envoi), `statut_effectif`, `echeance_apres`, agrégat du plan pour la rentabilité.
- **Adaptateur** : `outils_facturation.py` (sept outils, branchés par `outils.py::_outils_vague3`). `outils.envoyer_facture`
  attribue le numéro et l'échéance ; `outils.creer_facture_brouillon` et `_essayer_facture_brouillon` refusent la facture
  globale d'un devis facturé par jalons.
- **Registres DÉDIÉS** (append-only, hash-chaînés, durables, jamais le registre des mouvements : garde AST
  `conformite.verifier_aucun_decaissement` étendue aux quatre modules) :

| Registre | Contenu |
|---|---|
| `plans_facturation` | `plan_facturation_declare` (jalons calculés, empreinte du plan, personne qui l'a approuvée), `plan_facturation_revoque` |
| `numerotation_factures` | `numero_facture_attribue` : le **rang du maillon est la suite** ; la clé primaire du registre interdit deux fois le même numéro |
| `documents_facturation` | `facture_pdf_scellee`, `etat_compte_pdf_scelle` : empreintes du contenu et du PDF, **jamais les octets, le nom ni l'adresse du client** |

## Outils (portée d'appareil fermée, `ROLES.md`)

| Outil | Autonomie / niveau | Geste |
|---|---|---|
| `m5_declarer_plan_facturation` | T1 / **N3 humain** | Déclare le plan d'un devis ACCEPTÉ (2 à 12 jalons : acompte(s) à l'acceptation, jalons de chantier, au plus un solde à la fin des travaux) ; pourcentages OU montants ; idempotent |
| `m5_revoquer_plan_facturation` | T1 / **N3 humain** | Révoque un plan qui n'a donné AUCUNE facture (pas même un brouillon) ; motif obligatoire |
| `m5_creer_facture_jalon` | T1 / N1 | Brouillon de la facture d'un jalon : montant du plan, taxes du moteur ; ordre des jalons, « fin des travaux » seulement après `m4.travaux_termines`, jamais plus que le prix du devis ; idempotent |
| `m5_lire_plan_facturation` | T0 | Où en est le plan (facturé, solde, numéro, échéance, retard à `aujourd_hui`, écart d'arrondi des taxes) et la liste de ce que le propriétaire doit encore déclarer |
| `m5_verifier_numerotation_factures` | T0 | Relit la suite : trous, doublons, numéros sans facture émise, factures numérotées hors registre |
| `m5_preparer_pdf_facture` | T1 / N1 | PDF de la facture APPROUVÉE et NUMÉROTÉE ; français ou bilingue ; écrit sous `<OPSYS_HOME>/exports/factures/` (création exclusive, droits privés) ; scellé |
| `m5_preparer_etat_compte_client` | T1 / N1 | PDF de l'état de compte d'un client à une date : factures émises, crédits, payé, solde, retard calculé |
| `m5_envoyer_facture` (existant) | T2 / **N4 humain** | Émission : fixe le numéro et l'échéance dans le maillon d'envoi |
| `m5_lire_comptes_a_recevoir`, `m5_preparer_relances_clients` (existants) | T0 ; T1 / N1 | Retard calculé (`statut_effectif`, `jours_de_retard`, `en_retard`) ; la relance suit l'échéance PROPRE de la facture |

« Humain » : une personne (propriétaire ou finance) a approuvé la demande dans la file (`approbateur_en_cours`).

## Configuration du propriétaire (`department.yaml`, bloc `configuration.facturation`, commenté)

Décisions d'exploitation, pas des règles fiscales (GATE NATHAN) : `numerotation` (`prefixe`, `premier_numero`, `largeur`),
`conditions_paiement` (`delai_jours`), `entreprise` (`raison_sociale`, `adresse`, `numero_tps`, `numero_tvq`, `courriel`,
`telephone`). Relues à chaque appel. **Absentes ou mal formées, l'outil concerné refuse et dit quoi déclarer** :

| Manque | Verdict |
|---|---|
| Délai de paiement (ni sur le jalon ni dans `conditions_paiement`) | `REJ-PLAN-DELAI-A-DECLARER` (à la déclaration du plan) |
| Numérotation | `REJ-NUMEROTATION-A-DECLARER` (à l'émission d'une facture de jalon ; une facture ordinaire reste émise sans numéro tant que la numérotation n'est pas déclarée, mais une déclaration PRÉSENTE et mal formée est toujours un refus) |
| Raison sociale, adresse, numéro de TPS/TVQ (si la facture porte la taxe) | `REJ-PDF-ENTREPRISE-A-DECLARER` (au PDF) |
| Nom et adresse du client | `REJ-PDF-DESTINATAIRE-INVALIDE` (fournis à l'appel : M5 ne les garde pas) |

Le **profil d'entreprise** (`entreprise.yaml`) ne porte aucune identité légale aujourd'hui ; ces déclarations vivent donc dans
`configuration.facturation` de M5, comme toutes les décisions du propriétaire de ce département. Le chantier « réglages de
direction » pourra les déplacer sans changer les verdicts. Les numéros d'inscription sont validés dans leur **forme**
(`123456789 RT0001`, `1234567890 TQ0001`), jamais pour leur existence : à valider auprès d'un comptable (CPA).

## Le plan, au cent

- `mode = pourcentage` : chaque jalon sauf le dernier vaut `prix × pourcentage ÷ 100`, arrondi au cent (ROUND_HALF_UP) ; le
  **dernier jalon est le solde** (`prix − somme des précédents`) : la somme tombe toujours juste, et l'écart d'arrondi absorbé
  est écrit au plan (`ecart_arrondi_absorbe`). Les pourcentages totalisent exactement 100 (jusqu'à 4 décimales).
- `mode = montant` : la somme déclarée doit égaler le prix **exactement** (`REJ-PLAN-SOMME-INCORRECTE`, avec l'écart).
- Pas de mélange (`REJ-PLAN-MODE-MIXTE`), un jalon d'un cent au moins (`REJ-PLAN-JALON-NUL`), 2 à 12 jalons, déclencheurs dans l'ordre
  `acceptation` → `chantier` → `fin_travaux` (au plus un solde).
- **Taxes** : calculées **facture par facture** par `taxes.calculer_taxes` ; elles peuvent différer de quelques cents des taxes
  du total (3 jalons de 0,10 $ : 0,06 $ contre 0,05 $). `m5_lire_plan_facturation` rend cet écart tel quel : à valider auprès d'un
  comptable (CPA).
- **Rentabilité** : un devis facturé par jalons a pour prix facturé celui du **contrat** (jamais celui du premier acompte) ;
  il n'est définitif (`prix_definitif`) que lorsque TOUS les jalons ont une facture envoyée ou payée.

## Numérotation sans trou ni doublon

- Une attribution est le prochain rang du registre `numerotation_factures` ; **numéro = premier numéro déclaré + rang**.
  Écrite dans la **même transaction** que le maillon d'envoi (`outils.envoyer_facture`) : une panne annule les deux, **aucun
  numéro n'est consommé**.
- **Idempotente par facture** : attribuer deux fois à la même facture rend le même numéro (reprise après une demi-écriture
  hors transaction).
- **Concurrence** : SQLite sérialise les écrivains (`BEGIN IMMEDIATE`) ; PostgreSQL départage par la clé primaire du registre
  (`EcritureConcurrente`) et `relire_si_conflit` rejoue le corps. Le perdant n'obtient jamais le numéro du gagnant.
- `verifier_numerotation` dit tout trou, doublon, numéro incohérent ou premier numéro changé ; une suite altérée **bloque toute
  attribution** (`REJ-NUMEROTATION-CHAINE-INVALIDE`). Le premier numéro déclaré ne peut plus changer une fois la suite commencée.
- Une facture émise ne s'annule pas encore (aucun outil d'annulation de facture client) : un numéro émis reste dans la suite.

## Échéance et « en retard »

L'échéance est fixée à l'émission (`facturation.echeance_apres`) et écrite dans le maillon d'envoi. `statut_effectif(etat, date)`
est une **vue** : `EN_RETARD` seulement si la facture est `ENVOYEE` et l'échéance **strictement** dépassée à la date fournie
(l'horloge est celle de l'appelant ; M5 n'en a pas). Le statut ENREGISTRÉ ne change jamais, donc `m5.facture_emise_constatee`
(`ENVOYEE`) ne lève aucune relance. Sans échéance lisible, le retard n'est **pas calculable** (`retard_calculable: false`),
jamais « à temps » par défaut.

## Raccord avec M2 et M8 (aucun nouvel événement)

- `m5_preparer_relances_clients` calcule le retard depuis l'**échéance propre** de la facture (sinon le délai général de la
  politique, comme avant) et cite le numéro de facture dans le brouillon. L'événement existant `m5.creance_relance_preparee`
  porte déjà `echeance` : M2 reçoit la bonne.
- `m5_constater_factures_emises` publie `m5.facture_emise_constatee` pour chaque facture de jalon émise, comme pour toute
  autre : `PAYEE` ou `ANNULEE` lève la relance de M2 ; `ENVOYEE` ne la lève pas ; un paiement partiel est refusé
  (`REJ-FACTURE-PAIEMENT-PARTIEL`) et ne change rien. M8 compte chaque jalon comme une facture émise (avant taxes, sans client).
- **Aucune charge ni aucun journal ne porte de nom, d'adresse ou de numéro d'inscription** (preuve : bus et journaux scannés).

## PDF (M5-FACT-2)

- **Brique** : ReportLab 4.5.1 (BSD-3-Clause, Python pur), déjà intégrée pour la soumission de M3 (extra `soumission`,
  `docs/research/INGREDIENTS.md`) ; aucune dépendance ajoutée. Importée paresseusement, version épinglée vérifiée à l'exécution ;
  absente, `REJ-PDF-BRIQUE-ABSENTE` dit quoi installer (jamais un HTML renommé en PDF).
- **Contenu** : celui de la facture approuvée, repris du maillon (`Decimal`, aucun arrondi : un montant qui l'exigerait est
  refusé) — entreprise et numéros déclarés, client fourni, lignes, sous-total, TPS et TVQ (taux versionné affiché), total,
  échéance et conditions, **récapitulatif du contrat** pour un jalon (prix, facturé jusqu'à cette facture incluse, solde). Le
  PDF ne porte ni statut ni paiement : il reste identique après le paiement. Aucune marge, aucun coût.
- **Déterminisme** : mode `invariant`, date de création = émission de la facture, polices standard, aucun aléa : mêmes entrées,
  mêmes octets (pour une même version de ReportLab et de zlib).
- **Scellé rejouable** : `sha256` du PDF et du contenu structuré au registre `documents_facturation`. Rejouer rend `deja`
  sans rien écrire ; un rendu qui ne redonne pas l'empreinte scellée est `REJ-PDF-SCELLE-DIFFERENT` (jamais un écrasement).
- **Bilingue au besoin** : `fr` ou `bilingue` (chaque étiquette en français et en anglais ; dates ISO).
- **Texte libre = donnée** : échappé avant d'entrer dans un paragraphe (une balise `<img src=...>` s'afficherait telle quelle,
  sans ouvrir de fichier), contrôlé contre le jeu de caractères de la police (aucun carré silencieux).
- **Rien n'est envoyé** : le PDF est PRÉPARÉ dans un dossier confiné ; l'envoyer au client est une décision humaine.
- **État de compte** : factures émises du client à la date `au`, crédits des notes de crédit proposées, payé, solde, retard.

## Preuves

Voir la section « Preuves » de ce fichier mise à jour dans le rapport de livraison : tests, comptes avant → après, mutations.

PREUVES_A_COMPLETER

## Limites (sans euphémisme)

LIMITES_A_COMPLETER
