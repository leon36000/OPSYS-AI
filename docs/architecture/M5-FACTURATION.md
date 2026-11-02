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
| `m5_etablir_plan_facturation` | T1 / **N3 humain** | Déclare le plan d'un devis ACCEPTÉ (2 à 12 jalons : acompte(s) à l'acceptation, jalons de chantier, au plus un solde à la fin des travaux) ; pourcentages OU montants ; idempotent |
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

### Comptes avant → après

- Suite complète du département M5 : **3 824 passés, 0 échec** sur `e0424b040` (copie propre de la base) → **4 095 passés, 1 sauté, 0 échec**
  (+271 ; le sauté est la garde « en CI » de `test_facture_pdf.py`, qui ne s'exécute que lorsque la variable `CI` est posée).
- Tests nouveaux du chantier : 146 (module pur) + 71 (PDF) + 49 (outils, vrai socle) + 5 (échéance et relances) + 3 (parcours entier) +
  1 (PostgreSQL 17, opt-in) ; trois fichiers `test_*_sans_decaissement.py` et `test_analyse_mention.py` mis à jour (modules et outils
  nouveaux déclarés), `tests/test_extra_soumission.py` étendu au job M5.
- **Rouge avant** : sur `e0424b040`, les tests du chantier échouent (ou ne s'importent pas : les trois fichiers qui nomment
  `facturation_jalons` et `facture_pdf`) ; les 4 tests d'échéance/relance qui n'utilisent que des fonctions d'avant échouent par
  assertion, et le parcours entier échoue (3/3). Journaux conservés sous `scratchpad/rouge-avant-fact-*.txt`.

### Tests (noms et rôle)

| Fichier | Prouve |
|---|---|
| `departments/m05-financecore/tests/test_facturation_jalons.py` (pur) | somme au cent (40 répartitions aléatoires à graine fixe), arrondi du demi-cent, solde qui absorbe l'arrondi, refus de somme (montants, pourcentages, jalon nul, mode mixte), délai/chantier/ordre à déclarer, plan déterministe et empreinte, idempotence et révocation, numérotation (suite, rejeu, trou, doublon, altération, premier numéro), échéance, retard (jour même ≠ en retard), factures de jalon (ordre, solde après travaux, plafond, doublon, facture globale), agrégat de rentabilité, résumé et écart d'arrondi des taxes |
| `departments/m05-financecore/tests/test_echeance_retard_relances.py` (pur) | échéance propre, « en retard » à la date injectée, relance sur l'échéance propre et numéro cité — **rouge sur la ligne d'avant** |
| `departments/m05-financecore/tests/test_facture_pdf.py` (pur) | texte relu par `pypdf` (montants, TPS/TVQ, numéros, échéance, récapitulatif), bilingue, octets identiques, PDF identique après paiement, scellé rejouable/conflit, données déclarées absentes une à une, numéros mal formés, destinataire, caractères hors police, injection de balises, montants jamais arrondis, longue facture (plusieurs pages), brique absente, état de compte |
| `departments/m05-financecore/tests/test_facturation_jalons_outils.py` (vrai socle) | niveaux et portée fermée, N3 par la file (agent seul refusé, employé refusé), refus lisibles, plan→jalon→émission→numéro, **panne et reprise**, **demi-écriture reprise**, **deux émissions simultanées**, précondition de rang, plafond d'envoi zéro en mode autonome, retard et relance, lecture du plan, PDF scellé/rejouable/conflit de fichier/dossier lien symbolique, rien de personnel au bus ni aux journaux |
| `tests/test_facturation_jalons_bout_en_bout.py` (vrai bus, vrai sas, M2 et M8 réels) | le parcours entier : devis accepté → plan → acompte → approbation → numéro (panne puis reprise, puis deux émissions simultanées) → échéance dépassée → en retard → relance M2 → paiement partiel (relance reste) → paiement total (relance levée) → PDF ; somme fausse refusée ; données absentes bloquantes |
| `tests/e2e/test_m5_numerotation_concurrente.py` (PostgreSQL 17, opt-in `OPSYS_QUALIFIER_M9_PG17=1`) | deux émissions qui se disputent le même numéro : le perdant est rejoué et reçoit le suivant |

### Mutations (une à la fois, restaurées par `git checkout` ; 41, 40 tuées, 1 équivalente expliquée)

| # | Mutation | Test qui la tue |
|---|---|---|
| M01 | somme des montants déclarés non contrôlée | `test_facturation_jalons.py::test_une_somme_de_montants_qui_ne_tombe_pas_juste_est_refusee_avec_l_ecart` |
| M02 | somme des pourcentages non contrôlée | `test_facturation_jalons.py::test_des_pourcentages_qui_ne_totalisent_pas_100_sont_refuses` |
| M03 | arrondi du jalon : demi-cent au pair (banquier) au lieu de vers le haut | `test_facturation_jalons.py::test_arrondi_demi_cent_vers_le_haut_et_non_vers_le_banquier` |
| M04 | le dernier jalon n'est plus le solde (arrondi propre, la somme peut manquer) | `test_facturation_jalons.py::test_le_dernier_jalon_est_le_solde_et_absorbe_l_arrondi` |
| M05 | jalon de moins d'un cent accepté | `test_facturation_jalons.py::test_un_jalon_qui_vaudrait_moins_d_un_cent_est_refuse_dans_les_deux_modes` |
| M06 | numérotation : un numéro saute (trou) | `test_facturation_jalons.py::test_les_numeros_se_suivent_sans_trou_a_partir_du_premier_declare` |
| M07 | numérotation : attribuer deux fois ne rend plus le même numéro | `test_facturation_jalons.py::test_attribuer_deux_fois_au_meme_document_rend_le_meme_numero_sans_rien_ecrire` |
| M08 | vérification de la suite : les trous ne sont plus dits | `test_facturation_jalons.py::test_un_trou_un_doublon_ou_une_alteration_sont_dits_et_bloquent_toute_attribution` |
| M09 | changement du premier numéro déclaré toléré | `test_facturation_jalons.py::test_le_premier_numero_ne_peut_plus_changer_une_fois_la_suite_commencee` |
| M10 | ordre des jalons non contrôlé | `test_facturation_jalons.py::test_les_jalons_se_facturent_dans_l_ordre` |
| M11 | solde « fin des travaux » facturé d'avance | `test_facturation_jalons.py::test_le_solde_de_fin_de_travaux_n_est_jamais_facture_d_avance` |
| M12 | plafond du prix du devis supprimé | `test_facturation_jalons.py::test_le_total_facture_n_excede_jamais_le_prix_du_devis` |
| M12b | plafond : le cas limite (égal au prix) devient un refus | `test_facturation_jalons.py::test_le_solde_de_fin_de_travaux_n_est_jamais_facture_d_avance` |
| M13 | révocation d'un plan déjà facturé permise | `test_facturation_jalons.py::test_revoquer_un_plan_sans_facture_permet_d_en_declarer_un_autre_mais_pas_avec_une_facture` |
| M14 | redéclarer le même plan n'est plus reconnu | `test_facturation_jalons.py::test_declarer_deux_fois_le_meme_plan_ne_cree_rien_et_un_autre_plan_actif_est_refuse` |
| M15 | échéance : le délai de paiement est ignoré | `test_facturation_jalons.py::test_l_echeance_est_le_jour_d_emission_plus_le_delai_declare` |
| M16 | en retard dès le jour de l'échéance (>= au lieu de >) | `test_echeance_retard_relances.py::test_une_facture_est_en_retard_seulement_apres_son_echeance_a_la_date_injectee` |
| M17 | une facture payée peut être « en retard » | `test_facturation_jalons.py::test_payee_brouillon_et_annulee_ne_sont_jamais_en_retard_et_sans_echeance_le_retard_n_est_pas_calculable` |
| M18 | numérotation non déclarée : la facture de jalon est émise sans numéro | `test_facturation_jalons_outils.py::test_sans_numerotation_declaree_une_facture_de_jalon_ne_s_emet_pas_et_dit_quoi_declarer` |
| M19 | numéros de TPS/TVQ de l'entreprise plus exigés | `test_facturation_jalons_outils.py::test_le_pdf_de_la_facture_approuvee_est_scelle_rejouable_et_ne_porte_aucun_envoi` |
| M20 | niveau d'approbation : déclarer un plan descend à N1 | `test_facturation_jalons_outils.py::test_niveaux_autonomie_et_portee_des_outils_de_facturation` |
| M21 | plafond d'envoi automatique : émettre sans personne | `test_facturation_jalons_outils.py::test_emettre_exige_une_personne_meme_quand_le_departement_est_autonome` |
| M22 | scellé du PDF : une empreinte différente passe pour rejouée | `test_facturation_jalons_outils.py::test_un_scelle_qui_ne_correspond_plus_au_rendu_est_un_conflit_jamais_reecrit` |
| M23 | PDF non déterministe (mode invariant retiré) | `test_facturation_jalons_outils.py::test_le_pdf_de_la_facture_approuvee_est_scelle_rejouable_et_ne_porte_aucun_envoi` |
| M24 | PDF : un montant à 3 décimales est arrondi sans refus | `test_facture_pdf.py::test_aucun_montant_n_est_arrondi_a_l_affichage` |
| M25 | PDF : le texte du client n'est plus échappé (balises interprétées) | `test_facture_pdf.py::test_les_balises_et_les_controles_du_client_sont_des_donnees_jamais_interpretes` |
| M26 | hachage lié à la facture : l'empreinte scellée n'est plus celle des octets du PDF | `test_facturation_jalons_outils.py::test_le_pdf_de_la_facture_approuvee_est_scelle_rejouable_et_ne_porte_aucun_envoi` |
| M27 | facture globale permise pour un devis facturé par jalons (outil) | `test_facturation_jalons_outils.py::test_la_facture_globale_est_refusee_ou_non_creee_pour_un_devis_facture_par_jalons` |
| M28 | facture globale automatique créée à la fin des travaux malgré le plan | `test_facturation_jalons_outils.py::test_la_facture_globale_est_refusee_ou_non_creee_pour_un_devis_facture_par_jalons` |
| M29 | relance : l'échéance propre de la facture est ignorée | `test_echeance_retard_relances.py::test_la_relance_suit_l_echeance_propre_de_la_facture_pas_le_delai_general` |
| M30 | rentabilité : le prix facturé est celui du premier acompte | `test_facturation_jalons.py::test_l_agregat_pour_la_rentabilite_est_le_prix_du_contrat_et_definitif_seulement_si_tous_les_jalons_sont_emis` |
| M31 | émission : le numéro s'écrit sans précondition de rang | `test_facturation_jalons_outils.py::test_les_ecritures_de_l_emission_portent_la_precondition_de_rang` |
| M32 | scellé de la facture : un rendu différent n'est plus un conflit | `test_facturation_jalons_outils.py::test_un_scelle_qui_ne_correspond_plus_au_rendu_est_un_conflit_jamais_reecrit` |
| M33 | fichier PDF du même nom aux autres octets écrasé sans refus | `test_facturation_jalons_outils.py::test_un_fichier_du_meme_nom_aux_autres_octets_n_est_jamais_ecrase` |
| M34 | facture de jalon permise à côté d'une facture globale | `test_facturation_jalons.py::test_jalon_inconnu_et_facture_globale_existante` |
| M35 | chantier du devis écrasé par un autre déclaré | `test_facturation_jalons.py::test_le_chantier_vient_du_devis_ou_se_declare_jamais_inventé` |
| M36 | déclarer un plan sans personne (N3) : agent seul accepté | `test_facturation_jalons_outils.py::test_declarer_un_plan_passe_par_la_file_et_une_personne_l_ecrit_un_agent_seul_jamais` |
| M37 | comptage : le compte des factures en retard n'augmente plus | `test_echeance_retard_relances.py::test_une_facture_est_en_retard_seulement_apres_son_echeance_a_la_date_injectee` |
| M38 | numéro de facture absent de la relance (identifiant interne cité) | `test_echeance_retard_relances.py::test_la_relance_cite_le_numero_de_facture_quand_il_existe` |
| M39 | émission d'une facture déjà envoyée : le numéro est consommé avant la vérification | **survivante, équivalente** (voir ci-dessous) |
| M40 | `relire_si_conflit` retiré de l'émission (PostgreSQL : le perdant de la course n'est plus rejoué) | `tests/e2e/test_m5_numerotation_concurrente.py` (**sans effet sur SQLite**, qui sérialise les écrivains : seule l'épreuve PostgreSQL la tue) |

La mutation **M39** survit parce qu'elle est **équivalente** : le numéro n'est écrit qu'APRÈS l'acceptation de la transition par
`facturation.envoyer_facture` ; déplacer la vérification d'envoi avant ou après l'attribution (copie en mémoire) ne change aucun
registre. La garde qu'elle visait (ne jamais consommer un numéro pour une facture déjà envoyée) est prouvée par
`test_emettre_deux_fois_ou_une_facture_inconnue_ne_consomme_aucun_numero`. La précondition de rang (M31) n'est tuée que par un
test espion (la clé primaire du registre porte la même garde sur SQLite) ; `relire_si_conflit` (M40) n'est tué que par l'épreuve
PostgreSQL.

### Commandes

```
pytest departments/m05-financecore/tests/test_facturation_jalons.py departments/m05-financecore/tests/test_facture_pdf.py \
       departments/m05-financecore/tests/test_facturation_jalons_outils.py departments/m05-financecore/tests/test_echeance_retard_relances.py \
       tests/test_facturation_jalons_bout_en_bout.py
OPSYS_QUALIFIER_M9_PG17=1 pytest tests/e2e/test_m5_numerotation_concurrente.py     # Docker requis
```

## Limites (sans euphémisme)

- **PostgreSQL** : seule la course de numérotation est éprouvée (une épreuve, PostgreSQL 17 éphémère). Le plan, les scellés, le PDF et
  le reste du parcours n'ont tourné que sur SQLite ; ils reposent sur les mêmes primitives (`stockage.maillons`, clé primaire du
  registre), mais rien ne le prouve ici.
- **Rien d'envoyé ni de payé pour de vrai** : pas de courriel de facture (M1 n'est pas raccordé à la facture : le PDF est écrit dans
  `exports/factures/` et l'envoi reste une décision humaine hors de ce chantier), pas de QuickBooks, de Stripe ni de vrai client.
- **Déclarations du propriétaire** : plan, numérotation, conditions de paiement, raison sociale, adresse et numéros de TPS/TVQ sont
  déclarés, jamais vérifiés ; seule leur **forme** l'est. Les mentions du PDF n'ont **pas** été validées par un CPA ; M5 ne prétend
  pas satisfaire toutes les exigences légales d'une facture selon les seuils de montant (à valider auprès d'un comptable (CPA) /
  professionnel qualifié). Le nom et l'adresse du client sont fournis à chaque appel (M5 ne les garde pas ; M2 n'est pas lu).
- **Taxes** : arrondies facture par facture ; l'écart avec les taxes du total est dit, pas corrigé. Le traitement comptable d'un
  **acompte** (produit ou dépôt de client) n'est pas tranché : le brouillon d'écriture de chaque facture suit le comportement existant.
- **Pas d'annulation de facture client** (limite connue d'avant ce chantier) : un numéro émis reste dans la suite ; un plan ne se
  révoque donc plus dès sa première facture, et un plan erroné après une première facture se corrige par note de crédit (brouillon,
  N4) ou à la main, pas par OPSYS. Un devis déjà facturé en bloc (facture globale automatique de la fin des travaux, ou manuelle) ne
  reçoit plus de plan : le déclarer AVANT la fin des travaux.
- **Un seul jeu de numéros** par instance (un seul préfixe actif à la fois, la largeur et le préfixe peuvent changer en cours de
  route ; la suite, elle, ne repart jamais à zéro : pas de remise à zéro annuelle).
- **Retard** : calculé à la demande ou par `m5_preparer_relances_clients` ; rien ne le publie seul au bus. Les relances de M2
  n'existent qu'après l'exécution de cet outil (ou du cycle comptable) ; le planificateur durable ne les déclenche pas encore.
- **PDF** : « mêmes octets » vaut pour une même version de ReportLab (4.5.1, épinglée) et de zlib ; sur une autre machine ou version
  l'empreinte peut changer et le rejeu dira `REJ-PDF-SCELLE-DIFFERENT` (jamais un écrasement). Police standard Helvetica : les
  caractères hors Windows-1252 sont refusés. Aucun logo, aucun lien de paiement. Pas de gabarit HTML ni de rendu WeasyPrint (non installé).
- **Mobile et console** : aucune surface (outils fermés aux appareils) ; l'app mobile continue de lire `m5_lire_comptes_a_recevoir`,
  dont les entrées ont de nouveaux champs (`numero_facture`, `echeance`, `statut_effectif`, `jours_de_retard`) et dont le résumé a
  `en_retard` : ajouts seulement.
