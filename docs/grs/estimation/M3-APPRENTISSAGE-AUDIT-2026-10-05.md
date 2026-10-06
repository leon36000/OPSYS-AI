# Audit M3 — apprentissage estimations / résultats réels

Date : 5 octobre 2026 UTC. Audit délégué en lecture seule ; ROOT a revérifié les 30 empreintes et relu les frontières de finalité M5 et de qualification empirique M3. Aucun résultat de test nouveau n’est annoncé.

**Périmètre :** lecture seule du dépôt `/workspace/OPSYS-AI-recent`, sans tests, exécution de code, réseau ni modification du dépôt. Les références sont au chemin dans ce checkout; les empreintes SHA256 ci-dessous lient le constat aux octets lus.

## Constat produit

M3 n’est pas dépourvu de calibration. La durée possède une verticale raccordée et gouvernée : `m3_estimer_projet` inscrit une trace de barème/hash; `m4.travaux_termines` est reçu et stocké dans le registre séparé `m03-estimation/estime_vs_reel`; un consommateur M4 projette les faits depuis ses maillons/bus et recalcule la durée; `calibration_raccord` joint le WCT au devis accepté et au maillon M3 par hash exact, devis et lead. Le rapport de cohortes, la proposition train-only, le holdout ultérieur, les seuils versionnés et le journal de promotion/rollback existent dans `outils.py`, `calibration_cohortes.py` et `calibration_versions.py`. Activation et rollback sont N4 du propriétaire. L’état actif est relu par l’estimateur et la trace schéma 3 lie taux source et version candidate. C’est de la calibration descriptive candidate, non un modèle entraîné par LLM.

Cette protection ne constitue pas encore une qualification empirique. `department.yaml` marque explicitement la politique `non_qualifiee_empiriquement`. Les seuils fixes exigent 30 chantiers de train et 30 de holdout, couverture minimale 90 %, amélioration minimale relative de 10 % et absolue d’une minute, bootstrap 10 000 réplications et limite de régression P80 5 %. Les cohortes sont segmentées par service, unité, version du barème, quantité et taux exacts : aucune interpolation entre quantités. Les modules/tests consultés emploient des fixtures fictives; aucune mesure de qualité sur le corpus réel d’entreprise n’est établie dans cet audit. Le contrat indique aussi que `completude_corpus_m4` reste non prouvée et qu’un hash n’est pas une signature d’origine.

M4 fournit à cette boucle le WCT `completed_verified`, les horodatages et une durée recalculée des pointages, sémantique `duree_ecoulee_intervention`, unité minute. Elle exclut pauses et déplacement; ce n’est ni durée-personne ni temps salarial. Le chemin de calibration ne doit donc pas prendre la somme `minutes_regulieres` (qui vient d’une validation humaine N4 distincte, avec choix de catégories et couverture complète) comme interchangeable avec la durée d’intervention.

M6 est branché comme source de variance réelle des matériaux, mais pas comme source d’ajustement appris : le consommateur M3 n’enregistre que `statut_variance == evaluee`, associe les lignes à l’état WCT et `m3_lire_ecarts_estime_reel` les restitue telles quelles. L’évaluation M6 compare les besoins prévus avec la déclaration de matériaux utilisés (ou mouvements du registre), émet des écarts neutres et laisse `cause_possible=None`; une cause d’erreur exige une classification humaine. Les unités peuvent rester inconnues dans le chemin relu depuis le registre. « evaluee » signifie que la variance est calculable, pas que sa cause est confirmée ni que chaque écart vient d’une mauvaise estimation. Reprendre seulement les lignes compatibles, de même unité, et distinguer changement terrain, gaspillage, bris, retour, achat et erreur de saisie avant tout apprentissage.

M5 calcule coût réel, coût incomplet/manquant, marge prévue/réelle et `version_entrees`; le coût n’est `CALCULEE` que si les coûts sont complets et qu’un montant de facture est présent. Le code expose séparément `prix_definitif`, vrai seulement si le statut de facture est `ENVOYEE` ou `PAYEE`. La charge de l’événement `m5.rentabilite_chantier` contient les champs monétaires en liste blanche mais n’inclut pas cette distinction de finalité. M3 ne consomme actuellement ni cet événement ni l’outil `m5_lire_rentabilite_chantier` : son `department.yaml` déclare M4/M6, pas M5, et son évaluateur construit une capacité vers M3/M4 seulement. Il n’existe donc pas de liaison M3 démontrée entre erreur de durée/matériau, rentabilité finale, état de facture et version des coûts. Une facture brouillon ne doit pas servir d’étiquette d’apprentissage du prix encaissable; une rentabilité M5 partielle ne doit jamais être appelée « marge réelle ».

## Géospatial et confidentialité

M4 a déjà un contrat utile à réutiliser : localisation du chantier versionnée/chiffrée et confirmée humainement (la proposition de coordonnées ne vaut pas confirmation); les tournées n’acceptent que des coordonnées confirmées et masquent adresses/coordonnées dans les plans. Le routage OSRM est un composant de M4 séparé. M3, en revanche, n’a pas de source géospatiale d’estimation raccordée : `revue_devis` reçoit `distance_km` dans son contexte fourni par l’appelant et compare à un seuil configuré, sans attester cette distance contre la localisation M4. Il ne faut pas transformer ce champ en signal de calibration ni exporter des coordonnées GPS vers un jeu d’apprentissage. Garder des agrégats par zone seulement après contrat de liaison, minimisation et autorisation explicites. La règle produit exclut les données clients privées non anonymisées des jeux d’entraînement externes.

## Lacune prioritaire et tranche minimale

La priorité n’est pas un second algorithme d’apprentissage ni l’ajustement des prix. C’est un **rapport M3 de résultats de chantier en lecture seule**, qui réutilise les liens exacts existants et met côte à côte, par WCT/devis puis en agrégats, (a) écart de durée M3/M4, (b) écart quantitatif M6 admissible et sa classification/missingness, (c) état de complétude et finalité de rentabilité M5. Garder la politique de temps actuelle, les estimations et les écritures M5/M6 inchangées; le rapport ne promeut rien.

Minimum de contrat avant code : clé de jointure immuable `(wct_id, devis_id, estimation_source_hash)` et hash/version d’entrée M5; M4 `completed_verified` seulement; M6 `evaluee` mais lignes matériau affichées en statut « non classée » tant qu’une cause humaine manque; unités exactes obligatoires pour les statistiques; M5 complet ET `prix_definitif` pour toute métrique de marge finale, sinon motif d’exclusion explicite. Autorisation admin/propriétaire confirmée avant lecture des montants, sortie agrégée bornée, aucun GPS/adresse/identité d’employé, aucun texte privé. Les tests doivent couvrir divergence de hash ou versions, doublons WCT, facture brouillon, rentabilité partielle, causes M6 non classées, unités inconnues, données manquantes, permissions et absence d’écriture. Une campagne réelle, consentie et anonymisée/agrégée pourra ensuite mesurer erreurs et couverture par service/matériau; seulement après ce résultat une politique de calibration matériau/coût pourra être conçue et versionnée.

**État observé : PARTIEL.** La calibration temps est raccordée et dispose d’un chemin d’activation/rollback; la boucle multivariée M4/M6/M5, sa preuve de complétude et sa qualification empirique ne le sont pas. Aucun AP automatique, prix, engagement ou paiement n’est autorisé par ces calculs.

## Sources consultées et SHA256

| Chemin (relatif au dépôt) | SHA256 |
|---|---|
| `AGENTS.md` | `2cd33157c33a8c75cde4d83c10b4180224fb365bbd1ebb69427a17eb03350cc1` |
| `docs/produit/DIRECTIVES-NATHAN.md` | `4d41a6a062e62da836c5e5c4ac78eead5810b1047966667439967fa1cc5e765b` |
| `docs/produit/DEFINITION-PRODUIT.md` | `187205e887aecc6e7f127581b7ece1fed44d92b0e48528fb8bfbfad163d6cd98` |
| `departments/m03-estimation/department.yaml` | `c5708fc826dca4577d4abb8e9f8eb1ed7422506463aaa927101a78c8185b986b` |
| `departments/m03-estimation/src/m3_estimation/outils.py` | `3cf1742fcf725cd3c87e15e56c5b0e81fb979bca00ba3da25afa659867af0d05` |
| `departments/m03-estimation/src/m3_estimation/estime_vs_reel.py` | `b66bcde8e1133963e489baf2ce2fad654f353981caa9ae8ff38edc66dbfb4fb8` |
| `departments/m03-estimation/src/m3_estimation/calibration_cohortes.py` | `925ac23c816c2428126969ebbbe676f48e3e5c57473e90678050bf40dcd705b9` |
| `departments/m03-estimation/src/m3_estimation/calibration_raccord.py` | `1caa8c96641db499cda06d2fab99b17356f8df1aade538491156a7f7ce570aae` |
| `departments/m03-estimation/src/m3_estimation/calibration_versions.py` | `c4ac0a09338cfe913c19ef5c90291961af4c652a6e904dd419478066dec3b461` |
| `departments/m03-estimation/src/m3_estimation/trace_calibration_temps.py` | `65e0a4373b21cdcfbe52f797bb63efd7529e3c5223db67fefcc0cf6a3144ea1e` |
| `departments/m03-estimation/src/m3_estimation/revue_devis.py` | `4254829bb096bf04e3a95a404bf51875724fa4d2fe561a329619dcde2049c90a` |
| `departments/m03-estimation/tests/test_calibration_cohortes.py` | `82c7b1dd45a07b8c7a157dabba178de63abcc9eabb2b663d8b07c8da9221bcc4` |
| `departments/m03-estimation/tests/test_calibration_raccord.py` | `21beca1224a39929c99db42ac126b636b772f0d1af6d484662bc7eae4b4cb628` |
| `departments/m03-estimation/tests/test_calibration_promotion.py` | `c2892902446ef17777cfd91a284dd9ebb588db44811dac7c31614b720ba1a6d6` |
| `departments/m03-estimation/tests/test_calibration_promotion_sdk.py` | `86248e14ce152562601030aef2deb9d59a51d217fd52abd029a9417664023148` |
| `departments/m04-field-ops/src/m4_field_ops/calibration_projection.py` | `c5818b65c3dad37933db175f6eb359b3e28fde38521974ead342a50f556d88a6` |
| `departments/m04-field-ops/src/m4_field_ops/heures_regulieres.py` | `97ba0c7e48862f81061f5f4e34c9187cb09f4a8c42e81edd3c6be4c2462dca39` |
| `departments/m04-field-ops/docs/heures-regulieres-validees.md` | `55b9470563f32f4cf41bde0641426a5de1cd457abcd58054e83f534e12567c24` |
| `departments/m04-field-ops/src/m4_field_ops/outils.py` | `7303a22f610c8a6bd9b1e7454e99d0bd3f0b5427882c2fe10370ea9d3f68cfad` |
| `departments/m04-field-ops/src/m4_field_ops/localisation.py` | `84ba426a4931bc324dd6f04f3859a036db999ec3e777bc1a41be1ed8737850f3` |
| `departments/m04-field-ops/src/m4_field_ops/tournees.py` | `247a638fbc7e4a15d40224ac03ad50eb6dd46add27353d466e796cc930c3431f` |
| `departments/m04-field-ops/src/m4_field_ops/distances_osrm.py` | `15d58bca13f4366e4bb1186e1b4616ff74c7f27a09ead58289f0f65e79fade28` |
| `departments/m06-material-control/src/m6_material_control/variance_chantier.py` | `b876c9b79dce6c59953aa9a12667d3441b97719e113fae5f6230a62872969df9` |
| `departments/m06-material-control/src/m6_material_control/outils.py` | `30618011ed5e4b46bb75f16bf5d88c70f272026af4106bba1de0f3469b002509` |
| `departments/m06-material-control/tests/test_variance_chantier.py` | `e3d476ac7101f29b9dc648dd56ee6438c4233fc551247cfa0f229f1979e5b0e1` |
| `departments/m05-financecore/src/m5_financecore/cout_reel.py` | `6c6192a6e5581be2dabcd9299e43e4e89fdeb6fc84889bdc741d3dc7f4ce2fbb` |
| `departments/m05-financecore/src/m5_financecore/outils.py` | `4a33dd9925e54ddb32c788fb2dcbec9e4d31714ef4eb21cc3ca1e7f484158067` |
| `departments/m05-financecore/tests/test_evenement_rentabilite.py` | `efd3e94ff57569b4d03c9d4a01b26571e923ff2cff30b0e8e045600e1fbdc3c3` |
| `docs/architecture/CALIBRATION-COHORTES-TEMPS.md` | `505464065c76a41aee679fafba776400b5c71a783e26cea21c9a9810ec1addd5` |
| `docs/departements/M3-audit.md` | `73f36b8ee4c1334627867df56801602befbbf16ceb5277d6c5060ee913bb74e6` |

Note : `docs/departements/M3-audit.md` est daté du 28 septembre et ses constats « aucun appelant » / « aucune boucle M4/M6 » sont dépassés par les raccords de calibration actuels. Je l’ai conservé comme historique, non comme état courant.
