# M5 FinanceCore (Sophie) — vague 3 : opérations comptables, dossier CPA, conseillers, RAG fiscal

Branche `claude/m5-sophie`, base `1b58f4e6c`. Aucune migration (les registres sont des chaînes de hachage append-only sur
`stockage.maillons`, comme le grand livre existant). Ce document dit ce qui existe, ce que le code prouve et ce qui reste
hors d'atteinte. Il ne remplace ni `departments/m05-financecore/SOUL.md` ni la matrice
`docs/reprise/MATRICES-20261031/MATRICE-EXIGENCES-M5.json`.

## Règle d'or

Aucun taux, barème, seuil ni règle fiscale n'est inventé. Un fait vient (1) de la base fiscale versionnée
(`base_fiscale.py`, statut de revue visible : `brouillon`, `revu_1`, `approuve` ; **0 règle approuvée** à ce jour), (2) d'une
source de la base de connaissances M10, **publiée après revue humaine**, ou (3) des données de l'entreprise. Sinon la réponse
est « **non renseigné — source officielle requise** ». Aucune recommandation personnalisée de titres (garde NC 31-103,
`garde_investissement`). Toute sortie comptable, fiscale ou d'investissement porte « À valider auprès d'un comptable (CPA) /
professionnel qualifié ». Les agents ne créent que des **brouillons** ; la validation d'une écriture et la clôture d'une
période sont humaines (N4) ; un paiement ou une transmission fiscale est N3+ (préparé) puis N5 (exécuté hors OPSYS).

## État honnête

| Exigence | Ce qui existe | Preuve | Ce qui manque |
|---|---|---|---|
| M5.1 opérations comptables | Relances préparées, notes de crédit, dépenses d'employés, pièces liées, flux fournisseur (facture, PO M6, brouillon d'écriture, paiement préparé N3), périodes (ouverture, préclôture à 9 contrôles), jugements/estimations, cycle autonome jusqu'au brouillon | T + S (SQLite réelle, file d'approbation et bus réels) | OCR réel, pièce lue par un humain, passerelles bancaires en ligne, multi-entités, clôture d'exercice complète |
| M5.2 facturation par jalons, numérotation, PDF | Plan déclaré par une personne (N3), factures de jalon, numéros sans trou, échéance, « en retard » calculé, PDF de facture et d'état de compte scellés — voir [M5-FACTURATION](M5-FACTURATION.md) | T + S (SQLite réelle, sas et bus réels) | PostgreSQL, QuickBooks/Stripe réels, envoi au client, mentions légales validées par un CPA |
| M5.3 rapprochement bancaire | Relevés CSV/OFX (bibliothèque standard), 5 règles explicables, écarts nommés, reçu rejouable, confirmation N4 humaine | T + S | Plaid/Stripe/QBO en ligne, relevés PDF, lettres de change, devises |
| M5.6 dossier CPA | 14 fichiers déterministes + manifeste scellé, export Beancount, liste de contrôle, vérificateur | T + S | Aucune compilation ni attestation ; question juridique non tranchée ; relevés TPS/TVQ sans lignes de formulaire officiel |
| M5.13 dette / financement / investissement | Achat comptant, prêt, location (VAN, TRI), remboursement anticipé, échelonnement de placements à terme fixe aux taux de l'utilisateur ; reçu rejouable ; sensibilité nommée | T + S | Pas de DPA/CCA ni d'effet fiscal ; aucun produit, taux ni institution ; aucun conseil en placement |
| M5.15 conseiller fiscal et comptable | 3 analyses sourcées + 5 pistes à discuter avec le CPA ; ESSAI/non approuvé ; refus des règles non renseignées | T + S | Presque toutes les règles de la base sont `brouillon` ou absentes : en mode officiel la plupart des analyses chiffrées **refusent** |
| M5.18 RAG fiscal et comptable | Mécanisme (recherche hybride M10, citations, seuil de couverture, inconnu), corpus **fictif** de démonstration | T + S ; mesure sur corpus fictif | Aucune source officielle réelle publiée ; la qualité d'un vrai modèle d'embeddings n'est pas mesurée |

Aucune ligne n'est `FAIT_PROUVE`. Tout est mesuré en mode `ombre`, avec des répondants simulés et des données fictives.

## Architecture

- **Noyaux purs** (aucun import `opsys`, aucune horloge, aucun réseau) : `operations_registre`, `operations_comptables`,
  `operations_periodes`, `releve_bancaire`, `rapprochement_bancaire`, `dossier_cpa`, `conseiller_financement`,
  `conseiller_fiscal`, `connaissances_fiscales`, `verdicts_operations` (catalogue fermé de codes `REJ-OPS-*`, `REJ-BANQUE-*`,
  `REJ-DOSSIER-*`, `REJ-CONSEIL-*`).
- **Adaptateurs** (seuls à toucher registres, file d'approbation, bus, fichiers) : `outils_operations`, `outils_bancaire`,
  `outils_dossier`, `outils_conseillers`, branchés par `outils.py::_outils_vague3`.
- **Registre des opérations** : treize types `op_*` (relance, note de crédit, dépense d'employé, pièce liée, ouverture,
  préclôture, paiement préparé, jugement, mesures, flux fournisseur, rapprochement préparé/confirmé, dossier). Idempotent par
  clé : rejouer le même geste rend `deja_*` ; la même clé avec un autre contenu est `REJ-OPS-DOUBLON`. Une chaîne cassée ou un
  maillon étranger bloque toute écriture (`refus_anomalies`).
- **Grand livre** (existant) : seules extensions, deux types de pièce vérifiés (`note_credit`, `depense_employe`),
  `lire_montants_facture` public et le rapprochement TPS/TVQ qui tient compte des pièces taxées autres que les factures.
- **Moteur de calcul** (existant) : deux moteurs enregistrés dans `MOTEURS` (rejouables par `m5_verifier_recu_calcul`) :
  `remboursement_anticipe_pret` et `echelonnement_placements_terme_fixe`, plus la comparaison composite
  `comparaison_financement` (`conseiller_financement`), dont le reçu cite l'empreinte des calculs qu'elle compose.

## Outils (tous au manifeste, fermés aux appareils, `ROLES.md`)

| Outil | Autonomie / niveau | Geste |
|---|---|---|
| `m5_preparer_relances_clients` | T1 / N1 | Brouillons de relance (jamais envoyés : M1 envoie sous approbation) |
| `m5_proposer_note_credit` | T1 / N1 | Note de crédit client ou fournisseur + brouillon d'écriture ; refuse tout excédent |
| `m5_proposer_depense_employe` | T1 / N1 | Dépense d'employé (taxes recalculées, total reçu comparé) + brouillon |
| `m5_lier_piece_justificative` | T1 / N2 | Lie un fichier déposé par un humain (nom seul, confiné, sans lien symbolique) |
| `m5_lire_flux_fournisseur`, `m5_avancer_flux_fournisseur` | T0 ; T1 / N1 | Lit / avance facture → rapprochement PO (M6) → brouillon |
| `m5_preparer_paiement_fournisseur` | T1 / **N3 humain** | Fiche de paiement net des notes de crédit ; ne paie jamais |
| `m5_consigner_jugement_comptable` | T1 / **N3 humain** | Registre des jugements et estimations (auteur = humain qui approuve) |
| `m5_ouvrir_periode_comptable`, `m5_precloturer_periode_comptable` | T1 / N2 | Soldes d'ouverture ; liste de contrôle (la clôture reste `m5_clore_periode_comptable`, N4) |
| `m5_constater_mesures_comptables`, `m5_executer_cycle_comptable` | T1 / N2 | Constat de mesures pour M8 ; cycle autonome jusqu'au brouillon |
| `m5_preparer_rapprochement_bancaire`, `m5_lire_rapprochement_bancaire` | T1 / N2 ; T0 | Rapprochement d'un CSV/OFX déposé ; lecture |
| `m5_confirmer_rapprochement_bancaire` | T2 / **N4 humain** | Confirme après relecture du reçu |
| `m5_preparer_dossier_cpa`, `m5_verifier_dossier_cpa` | T1 / N2 ; T0 | Dossier scellé ; vérification contre le manifeste |
| `m5_comparer_financement_achat`, `m5_simuler_remboursement_anticipe`, `m5_echelonner_placements_terme_fixe` | T0 / N0 | Calculs avec reçu, hypothèses explicites |
| `m5_lister_sujets_conseil_fiscal`, `m5_analyser_situation_fiscale`, `m5_rechercher_connaissance_fiscale` | T0 / N0 | Conseil fiscal sourcé ; RAG |

« Humain » : le geste exige une personne (propriétaire ou finance) qui a **approuvé la demande dans la file** (`approbateur_en_cours`) ; ni
un argument, ni le texte d'un modèle, ni un appareil ne la remplace, même en mode autonome (`REJ-OPS-HUMAIN-REQUIS`). Un agent seul
obtient une mise en attente, jamais l'exécution.

## Configuration du propriétaire (`department.yaml`, bloc `configuration.operations`, commenté)

Décisions d'exploitation, pas des règles fiscales : `relances` (`delai_echeance_jours`, `paliers_jours_apres_echeance`),
`compte_remboursement_employes` (compte de passif du plan), `rapprochement` (`motifs_frais`, `compte_frais_bancaires`). Absentes,
les relances et les dépenses d'employés répondent « à déclarer » ; un frais bancaire n'est jamais classé sans motifs déclarés.

## Flux

1. **Créances** : factures clientes envoyées et en retard, selon la politique déclarée → un brouillon de relance par (facture, palier) ; événement
   `m5.creance_relance_preparee` (M2 suit, M1 envoie sous approbation).
2. **Dettes** : facture fournisseur → (sur PO) rapprochement avec la réception de M6 (événement `m5.rapprochement_po_constate`) → brouillon
   d'écriture → paiement **préparé** (N3). Sur PO, un rapprochement non `CONCORDANT` refuse le paiement sauf dérogation motivée d'une personne ;
   la réserve `REJ-AP-UNITE-PRIX-NON-CONFIRMEE` (unité des prix de M6 non confirmée) reste affichée. Un seul paiement préparé par facture.
3. **Banque** : relevé déposé dans `imports/` → `lire_releve` (CSV avec synonymes fr/en, OFX SGML/XML par expressions régulières ; montant ou date
   ambigus = refus, jamais deviné ; compte masqué) → cinq règles explicables, dans l'ordre : R1 montant+date+référence, R2 montant+référence,
   R3 montant+date proche (ambigu → `a_confirmer`), R4 somme de 2 à 4 lignes, R5 élément antérieur en circulation. Le reste est un **écart nommé** avec
   pistes (jamais appliquées). Reçu rejouable par préfixe de registre aux têtes enregistrées. Confirmation = N4 humain.
4. **Période** : ouverture (soldes d'ouverture, période précédente close ?) → préclôture à neuf contrôles (`BLOQUANT` / `A_VERIFIER` / `OK`) → clôture
   humaine N4 (existante). La préclôture ne clôt rien. Événement `m5.mesures_comptables_constatees` (nombres et montants, aucun nom) pour M8.
5. **Dossier CPA** : voir ci-dessous. Événement `m5.dossier_cpa_scelle` pour M10.

## Dossier CPA (M5.6)

Quatorze fichiers déterministes (UTF-8 sans BOM, fins de ligne `\n`, clés JSON triées, lignes triées) : `00-LISEZ-MOI.txt`, `01-balance-verification.csv`,
`02-soldes-ouverture.csv`, `03-grand-livre.csv`, `04-brouillons-en-attente.csv`, `05-rapprochements-bancaires.json`, `06-releves-taxes-preparees.json`,
`07-liste-des-pieces.csv`, `08-jugements-et-estimations.json`, `09-journal-des-corrections.csv`, `10-sous-comptes-clients.csv`,
`11-sous-comptes-fournisseurs.csv`, `12-grand-livre.beancount`, `13-liste-de-controle.json`, plus `MANIFESTE.json`. Le **sceau** est le SHA-256
(`encodage.empreinte("m5.dossier_cpa.scelle.v1", …)`) du manifeste : version, période, version du plan, fichiers (nom, octets, empreinte) et **têtes des
registres** ; ajouter un maillon au grand livre sans refaire le dossier, ou retoucher un fichier, se voit (`m5_verifier_dossier_cpa` recalcule le sceau depuis les
fichiers réels, non depuis les empreintes affirmées). Les cellules de texte sont neutralisées contre l'injection de formule (OWASP). Mêmes entrées, mêmes octets.

**Ce que le dossier n'est pas** : ni compilation, ni mission d'examen, ni audit, ni états financiers vérifiés, ni déclaration de taxes. La nature de la
mission et ce qu'on peut remettre à une banque, un investisseur ou une autorité sans CPA sont des questions **juridiques et professionnelles** qu'OPSYS ne
tranche pas : la liste de contrôle les laisse `A_FAIRE`. Les relevés TPS/TVQ ne portent aucune ligne de formulaire officiel (« non renseigné — source
officielle requise »). La liste de contrôle distingue `FAIT`, `A_FAIRE`, `A_VERIFIER`.

## Conseillers

- **Financement (M5.13)** : objet limité à une liste fermée de décisions d'exploitation (`OBJETS_ADMIS` : équipement, véhicule, outillage, immeuble
  d'exploitation, embauche, projet interne, prêt d'entreprise, crédit-bail). Un titre, un FNB, une action, un portefeuille ou un cryptoactif est refusé
  (`REJ-CALC-OBJET-HORS-PERIMETRE`) ; une `demande` en texte libre passe la garde NC 31-103 (`REJ-CONSEIL-RECOMMANDATION-TITRES`, injection comprise). Tout taux,
  prix et valeur résiduelle vient de l'appelant. Le scénario « au coût actualisé le plus bas » est un fait de calcul, pas une recommandation. Sensibilité :
  seulement les variations nommées (maximum six) ; aucune par défaut. Aucun effet fiscal modélisé.
- **Fiscal (M5.15)** : sujets `taxes_tps_tvq_a_remettre`, `echeances_tps_tvq`, `controle_des_taux_appliques` (analyses) et `remuneration_salaire_dividendes`,
  `deduction_amortissement_cca`, `acomptes_provisionnels_impot`, `regime_declaration_taxes`, `structure_juridique` (pistes à discuter avec le CPA). Chaque
  affirmation cite sa source et son statut de revue ; une source non approuvée (règle sans deux réviseurs, calendrier non validé par le CPA, autorité non
  officielle, source périmée, démonstration fictive) rend la sortie **ESSAI/non approuvé** ; en mode `officiel`, c'est un **refus**
  (`REJ-CONSEIL-SOURCE-NON-APPROUVEE`). Une règle absente est un refus (`REJ-CONSEIL-REGLE-NON-RENSEIGNEE`) qui nomme la source officielle à fournir et les
  questions pour le CPA. Une piste sans chiffrage n'est jamais une recommandation.

## RAG fiscal et comptable (M5.18)

`m5_rechercher_connaissance_fiscale` interroge la base de connaissances M10 (recherche hybride FTS5 + vecteurs, fusion RRF) **uniquement dans la base de Sophie** (`m05-financecore`), domaines
`fiscalite` et `comptabilite`, passages **publiés** seulement. Les passages sont rendus en citations (extrait, éditeur, référence, version, état, autorité, fraîcheur). Un **second
seuil de couverture lexicale** (`COUVERTURE_MINIMALE = 0,5`, sauf appui de la voie vectorielle) écarte les correspondances d'un seul mot : sans passage, la réponse est `aucune_source`,
`inconnu = vrai`, avec la consigne de ne pas répondre de mémoire. Un passage n'est « approuvé » que si son autorité est `officielle`, son état `publie`, sa fraîcheur valide, et qu'il n'est
pas une démonstration fictive ; le reste est un ESSAI marqué ; une démonstration fictive ne se cite jamais comme réelle. Le texte cité est une donnée non fiable : une consigne
qu'il contient est neutralisée et jamais obéie. Sophie ne peut ni ingérer, ni publier, ni retirer : la publication d'une source réelle est une **revue humaine dans M10**
(un domaine réglementé exige une publication humaine ; une source fiscale « tierce » ne passe même pas la revue).

Corpus : `departments/m05-financecore/evals/connaissances-fiscales-demo.v1.yaml`, **entièrement fictif** (principauté de « Valdoré », taux et délais inventés), 19 questions écrites avant la mesure
(16 avec réponse, 3 sans). Mesuré (`opsys-metier connaissances mesurer`, double d'embeddings déterministe, qui valide le harnais et non la qualité d'un vrai modèle) : hybride
recall@1 0,9375, @3 1,0, MRR@10 0,9583, abstentions correctes 2/3 pour le moteur seul. Mesuré par l'outil de Sophie de bout en bout : 15 questions sur 16 citent la bonne section dans les trois
premières citations ; 3 questions sur 3 sans réponse sont `aucune_source` (la seconde barrière corrige la 3e). La seule question ratée (« Qui décide qu'un mois est fermé ? ») reste en inconnu
plutôt que de citer au hasard : le prix du seuil est du rappel, pas une fausse citation.

## Événements (catalogue `src/opsys/evenements/catalogue/`, `department.yaml: evenements.publie`)

| Événement | Quand | Consommateur prévu | `evenement_id` (rejeu sans doublon) |
|---|---|---|---|
| `m5.creance_relance_preparee` | Relance préparée | M2 (suivi des créances) | `m5-relance-<relance_id>` |
| `m5.rapprochement_po_constate` | Le flux d'une facture sur PO avance | M6 (contrôle matériaux) | `m5-rappo-<facture>-<16 car. de l'empreinte>` |
| `m5.mesures_comptables_constatees` | Constat des mesures du jour | M8 (vue des opérations) | `m5-mesures-<rang>-<date>-<version>` |
| `m5.dossier_cpa_scelle` | Dossier préparé et scellé | M10 (mémoire des clôtures) | `m5-dossier-<dossier_id>` |

Charges : identifiants, nombres, montants et dates seulement (aucun nom, libellé, chemin ni donnée de client), validées par un schéma JSON à propriétés requises. **Limite** : ce département
est le producteur. Les consommateurs M2/M8/M6/M10 étaient répartis dans les tests avec des consommateurs **simulés** ; leurs vrais gestionnaires existent maintenant (chantier d'interconnexion, [INTERCONNEXION.md](INTERCONNEXION.md)) et sont prouvés sur le vrai bus. M5 consomme en retour `m7.depenses_marketing_constatees` (brouillon de charge, jamais validé).

## Preuves

- Tests du département (nouveaux) : `test_releve_bancaire`, `test_rapprochement_bancaire`, `test_operations_comptables`, `test_operations_periodes`, `test_dossier_cpa`, `test_moteur_financement`,
  `test_conseiller_financement`, `test_conseiller_fiscal`, `test_connaissances_fiscales_pur`, `test_operations_outils` (file d'approbation, bus et registres réels), `test_conseillers_outils`,
  `test_evaluation_vague3` ; test de socle `tests/test_m5_connaissances_fiscales.py`.
- **Évaluation au gabarit commun** : `evals/gabarit-vague3.v1.yaml` (fichier séparé de `gabarit.v1.yaml`, 14 cas, sept catégories, 5 sondes d'autorité) exécuté avec les outils réels sur une
  instance fictive : le répondant de référence réussit 14/14 ; le « dangereux » est **non qualifié** (5 cas bloquants) alors que les 5 sondes tiennent (paiement N3 et confirmation N4 mis en
  attente, recommandation de titres refusée, source non approuvée refusée) ; l'« inventif » échoue chaque cas par le chiffre inventé et l'honnêteté par l'inconnu non déclaré. Cela mesure
  l'exécuteur, le corpus et les gardes du dépôt, jamais un vrai modèle.
- **Mutations** (une à la fois, restaurées par `git checkout` ; 23 mutations, toutes tuées à la fin) :

| # | Mutation | Test qui la tue |
|---|---|---|
| M01 | Écriture déséquilibrée acceptée | `test_grand_livre::test_chaque_refus_de_lignes_n_ecrit_rien[desequilibree]` |
| M02 | Période close modifiable | `test_grand_livre::test_cloture_cumulative_…` |
| M03 | Source non approuvée présentée comme officielle (règles) | `test_conseiller_fiscal::test_mode_officiel_sur_la_base_du_depot_est_refuse` |
| M04 | Calendrier non validé par le CPA présenté comme officiel | `test_conseiller_fiscal::test_echeances_calendrier_non_valide_…` |
| M05 | Recommandation de titres non gardée | `test_conseillers_outils::test_une_demande_de_recommandation_de_titres_…` |
| M06 | Règle non renseignée estimée au lieu d'être refusée | `test_conseiller_fiscal::test_piste_chiffree_avec_une_regle_non_renseignee_…` |
| M07 | Geste humain accordé à un agent seul | `test_operations_outils::test_flux_fournisseur_du_brouillon_au_constat_…` |
| M08 | Note de crédit au-delà du reste (montant avant taxes) | **survivante au départ** → `test_un_cent_de_trop_avant_taxes_…` ajouté |
| M09 | Injection de formule CSV non neutralisée | `test_releve_bancaire::test_cellule_de_formule_est_neutralisee_a_l_export` |
| M10 | Montant bancaire ambigu accepté | `test_releve_bancaire::test_montant_ambigu_refuse_jamais_devine` |
| M11 | Sceau du dossier sans les têtes de registres | `test_dossier_cpa::test_le_sceau_couvre_…` |
| M12 | Seuil de couverture du RAG supprimé | `test_connaissances_fiscales_pur::test_le_second_seuil_…` |
| M13 | Marquage ESSAI jamais posé | `test_conseiller_fiscal::test_la_base_du_depot_donne_toujours_un_essai_marque` |
| M14 | Même clé, autre contenu : doublon accepté | `test_operations_comptables::test_note_de_credit_ne_depasse_jamais_…` |
| M15 | Paiement sur PO non concordant sans dérogation | `test_operations_comptables::test_paiement_refuse_si_rapprochement_po_…` |
| M16 | Nom de fichier à chemin accepté (traversée) | `test_operations_outils::test_piece_justificative_nom_hostile_…` |
| M17 | Objet « fnb » admis dans la liste fermée | `test_conseillers_outils::test_un_objet_de_placement_en_titres_…[fnb]` |
| M18 | Démonstration fictive citée comme approuvée | `test_connaissances_fiscales_pur::test_seule_une_autorite_officielle_…` |
| M19 | Fenêtre de dates du rapprochement ignorée | `test_rapprochement_bancaire::test_chaque_regle_apparie_et_s_explique` |
| M20 | Brouillons en attente ne bloquent plus la préclôture | `test_operations_periodes::test_preclôture_bloque_sur_brouillon_…` |
| M21 | Dossier altéré déclaré conforme | `test_dossier_cpa::test_le_sceau_couvre_…` |
| M22 | Deuxième paiement préparé pour la même facture | `test_operations_comptables::test_paiement_prepare_net_des_notes_…` |
| M23 | Plafond de taille de relevé relevé à 2 Go | **survivante au départ** (le test lisait la constante mutée) → `test_les_plafonds_de_taille_…` ajouté |

Une première mutation M14 mal posée (elle laissait le refus en place : mutant équivalent) a été refaite correctement ; M08 et M23 étaient de vraies lacunes de test, fermées.

## Limites (non prouvé)

- Aucun parcours HTTP/Core natif, navigateur ni téléphone ; aucun PostgreSQL rejoué pour ces tables (elles reposent sur `stockage.maillons`, déjà couvert ailleurs).
- Aucune lecture de relevé PDF, aucune connexion bancaire en ligne, aucun OCR : la pièce est un fichier déposé par un humain, lié par nom.
- Les règles fiscales de la base sont **0 approuvée** : les analyses chiffrées en mode officiel refusent presque toutes ; en mode essai, elles sont marquées ESSAI. Aucune règle réelle n'a été saisie ici.
- Le corpus de connaissances est fictif ; la qualité sur de vraies sources et un vrai modèle d'embeddings n'est pas mesurée.
- Le dossier CPA n'est pas une mission de certification ; la question juridique (qui peut remettre quoi à qui) reste ouverte et n'est pas tranchée par le code.
- Le rapprochement TPS/TVQ n'a pas de lignes de formulaire officielles ; la préclôture signale « taxes rapprochées » `A_VERIFIER` tant que le contrôle n'est pas exécuté.
- Ni paie, ni impôt des sociétés, ni DPA/CCA modélisés dans les conseillers ; les comparaisons de financement n'incluent aucun effet fiscal.
- Les tests propres à M5 simulent encore les consommateurs des autres départements ; les vrais sont prouvés par les tests d'interconnexion ([INTERCONNEXION.md](INTERCONNEXION.md)).
