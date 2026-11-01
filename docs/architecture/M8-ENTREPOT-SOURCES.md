# Entrepôt de M8 : d'où vient chaque mesure, et ce qui n'y arrive pas encore

Statut (2026-11-01) : cartographie établie par lecture du code, puis branchement de tout ce qui se branche **sans nouveau droit
d'appareil, sans nouvel outil, sans migration et sans écriture dans un autre département**. Prouvé sur le **vrai bus**, les
`consommateurs()` réels et une base SQLite migrée, avec des charges fictives conformes au catalogue d'événements. Rien n'a été
exécuté contre PostgreSQL pour ces mesures, ni contre un service externe. Contexte : `INTERCONNEXION.md` (le bus),
`M8-OLIVIER.md` (la couche analytique).

## 1. Pourquoi ce chantier

M8 est la vue exécutive de toute l'entreprise. L'audit d'interconnexion disait honnêtement que les constats de M7, M5 et M3
n'alimentaient pas l'entrepôt : ils arrivaient bien chez M8 (registre `faits_operations`) mais ne servaient qu'à la section
`operations_recues` de la vue exécutive. Le catalogue fermé n'avait que 18 mesures, aucune ne venait de la marge, des créances, des
comptes à payer, des relevés publicitaires, des réceptions de matériaux ni des demandes de M1.

Il en a maintenant **38** (18 + 20), lues par le **même moteur** (`moteur_mesures.lire`) que les wallboards, le score de santé, le
copilote, la mémoire (M10) et le pont BI : une mesure n'a qu'une valeur, qu'une provenance et qu'une fraîcheur, quelle que soit la
surface qui la montre.

## 2. Règles (les mêmes pour toutes les sources)

1. **Le bus, pas la lecture directe.** Chaque mesure vient d'un événement du catalogue que le département propriétaire publie déjà.
   Aucune lecture croisée n'a été ajoutée : le port de M9 (`lecteur_producteurs_m9`) exige l'admin authentifié via M9 et ne convient
   pas à un tour planifié de M8 ; en élargir un autre serait élargir un droit, ce que le brief interdit.
2. **Propriété des données.** Un consommateur n'écrit que dans le registre de M8 (mesuré : le monde de test observe chaque écriture).
3. **Idempotent par clé de contenu**, pas par `evenement_id` (même constat rejoué sous un autre identifiant : rien de plus).
4. **Provenance.** Chaque constat rangé dans `faits_operations` porte `provenance` : type d'événement, identifiant d'événement quand la
   charge en porte un, **empreinte** SHA-256 de la charge reçue. Chaque mesure calculée porte `entrees.empreinte_faits` : l'empreinte
   des faits qu'elle a réellement utilisés, **indépendante de l'ordre de livraison** (un fait utilisé qui change la change ; un fait
   qu'elle n'utilise pas ne la change pas).
5. **Fraîcheur : la plus stricte des trois.** Fenêtre de M8 (catalogue, ou propriétaire), fenêtre du **département source** quand il en
   déclare une (M7 dit `fraicheur_fenetre_h` pour chacune de ses sources publicitaires : portée par la mesure `fenetre_source_s`) et
   fenêtre demandée par l'appelant. Origine dite : `catalogue`, `configuration`, `source`, `appelant`, `terminale`.
6. **Jamais un zéro inventé.** Source absente : `non_calculable`, avec `manque` (quoi, de qui). M8 ne sait pas distinguer « rien
   publié » de « rien livré par le bus » et le dit.
7. **Couverture dite.** Une valeur calculée sur une partie seulement de ce qu'elle devrait couvrir (« 2 chantiers sur 4 », « 2 jours
   sans relevé ») garde sa valeur, porte `couverture = {etat: partielle, couverts, attendus, manquants, raison}` et son `detail` le dit
   (« couverture partielle : … »). Wallboard (tuile `partielle`, bannière jamais « ok »), copilote (« Couverture PARTIELLE ») et
   entrepôt (`detail`) la montrent. Une mesure sans source est `inconnue`. Il n'y a **pas** de nouveau statut `partielle` : le schéma
   de l'entrepôt, de `m8.fait_consolide` et des consommateurs ne le connaît pas (voir §6).
8. **Écart de définition = mesure nommée**, pas une moyenne : marge réelle (M5) moins marge prévue (M3), demandes qualifiées par M1
   sans lead chez M2, relevés de dépense (M7) contre dépense comptabilisée (M5).
9. **Loi 25.** Aucun nom, courriel, téléphone, fournisseur ni technicien dans une mesure ni dans l'entrepôt. La demande de M1 porte le
   contact dans sa charge : M8 n'en garde que `lead_id`, `utm_content` et l'instant. La réception de M6 porte le fournisseur et les
   lignes de prix : M8 n'en garde que le bon de commande, le mouvement de stock, l'instant, le verdict et le statut.

## 3. Matrice : les 38 mesures

État : **branché** = alimenté par un événement réel du bus et prouvé par un test exécuté ; **non branché** = la donnée existe mais la
mesure n'est pas faite (raison dite) ; **impossible sans décision** = aucun événement ni lecture autorisée ne porte la donnée.
« Entrepôt » : `m8_ent_mesures_courantes` et `m8_ent_mesures_hist` (une ligne par mesure, par construction).

### 3.1 Les 18 mesures de la tranche 1

| Mesure | Source (événement du bus) | État | Remarque |
|---|---|---|---|
| `m8_leads_recus` | M2 `m2.client_associe` | branché | `client_id` non gardé |
| `m8_leads_qualifies` | M2 `m2.lead_assigne` (rang 1) | branché | une réassignation est ignorée |
| `m8_devis_envoyes` | M3 `m3.devis_envoye` | branché | envoi approuvé, pas livré |
| `m8_devis_acceptes` | M3 `m3.devis_accepte` | branché | |
| `m8_devis_sans_reponse` | M3 `m3.devis_sans_reponse` | branché | constat de M3 repris |
| `m8_taux_acceptation_pct` | M3 envoyé + accepté | branché | |
| `m8_delai_lead_acceptation_jours` | M2 arrivée + M3 accepté | branché | médiane |
| `m8_carnet_signe_cad` | M3 `prix_total` + M4 (sortir le terminé) | branché | prix de M3, jamais le coût |
| `m8_contenus_exportes` | M7 `m7.contenu_exporte` | branché | |
| `m8_leads_par_contenu` | M1 `m1.lead_qualifie` (`utm_content`) + M7 | branché | attribution à la clé |
| `m8_devis_envoyes_par_contenu`, `m8_devis_acceptes_par_contenu` | + M3 | branché | |
| `m8_impressions_par_contenu`, `m8_clics_par_contenu` | aucune | **impossible sans décision** | `m7.signaux_marketing_constates` ne porte aucune valeur de mesure par construction (« M8 lit les faits eux-mêmes par `m7_lire_signaux_marketing` »). Il faudrait soit autoriser une lecture M8 → M7 de cet outil T0, soit que M7 publie un résumé par contenu. Voir décision D2. |
| `m8_chantiers_termines` | M4 `m4.travaux_termines` | branché | |
| `m8_ecart_duree_equipe_pct` | M4 durée réelle + M3 `duree_estimee_minutes` | branché | agrégat d'équipe, jamais par technicien |
| `m8_chantiers_signal_materiaux` | M6 `m6.variance_chantier` + M4 | branché | verdict de M6 repris |
| `m8_cash_libre_cad` | M5 `m5.cash_libre_constate` | branché | n'existe que si l'admin fait constater M5 (le digest de 7 h ne le fait pas) |

### 3.2 Les 20 mesures interdépartements (cette tranche)

| Mesure | Unité | Source (département · événement) | Calcul | État | Preuve |
|---|---|---|---|---|---|
| `m8_chantiers_marge_reelle` | chantiers | M5 `m5.rentabilite_chantier` + M4 | nombre de chantiers terminés dont M5 a chiffré la marge (verdict CALCULÉE, coût complet, **prix définitif**) ; couverture n sur N | branché | pur, bus, entrepôt |
| `m8_marge_reelle_cumulee_cad` | CAD | idem | somme des marges chiffrées ; **pas** la marge de l'entreprise | branché | idem |
| `m8_chantiers_en_perte` | chantiers | idem | marge < 0 parmi les chiffrés | branché | idem |
| `m8_ecart_marge_cumule_cad` | CAD | M5 + M3 `m3.devis_accepte` | **écart** : marge réelle (M5) moins marge prévue (prix − coût de M3) | branché | idem |
| `m8_creances_ouvertes_cad` | CAD | M5 `m5.mesures_comptables_constatees` | total du dernier constat (plus grande date de référence), tel quel ; constat incohérent (total ≠ somme des tranches) refusé | branché | idem |
| `m8_creances_90_jours_plus_cad` | CAD | idem | tranche « 90+ » | branché | idem |
| `m8_ecritures_en_attente` | écritures | idem | brouillons d'écriture non validés (N4) | branché | idem |
| `m8_comptes_a_payer_cad` | CAD | M5 `m5.cash_libre_constate` (composante) | tel quel ; non calculable avec code de M5 et plancher dit | branché | idem |
| `m8_solde_tresorerie_cad` | CAD | idem (composante `solde`) | tel quel | branché | idem |
| `m8_taxes_a_remettre_cad` | CAD | idem (composante) | tel quel | branché | idem |
| `m8_releves_depense_pub_cad` | CAD | M7 `m7.depenses_marketing_constatees` (+ `m7.signaux_marketing_constates` pour la fenêtre) | somme des **dernières révisions** des relevés ; refusée si bases de taxes mêlées ou relevés qui se chevauchent ; jours sans relevé = couverture partielle ; **n'est pas la dépense réelle** | branché | idem |
| `m8_conversions_hors_ligne` | conversions | M7 `m7.conversion_hors_ligne_importee` | `conversion_id` distincts ; sans source normalisée dite | branché | idem |
| `m8_anomalies_depense_critiques` | anomalies | M7 `m7.anomalie_depense_detectee` | sévérité critique, comptes de démonstration exclus | branché | idem |
| `m8_ecart_depense_pub_comptabilisee_cad` | CAD | M7 relevés contre **M5 dépense comptabilisée** | **écart** nommé | **impossible sans décision** (non calculable par construction) | le test pose qu'il le dit |
| `m8_heures_sur_site_chantiers` | heures | M4 `m4.travaux_termines` (`duree_reelle_minutes`) | somme des durées sur site en heures (pas des heures-personnes) ; durée illisible dite | branché | idem |
| `m8_receptions_materiaux` | réceptions | M6 `m6.reception_enregistree` (**nouveau consommateur**) | par bon de commande et mouvement de stock | branché | idem |
| `m8_receptions_avec_ecart` | réceptions | idem | verdict de M6 ≠ CONFORME | branché | idem |
| `m8_commandes_envoyees` | commandes | M1 `m1.commande_courriel_envoyee` (**nouveau consommateur**) | bons de commande distincts dont le courriel est parti après approbation | branché | idem |
| `m8_demandes_qualifiees_m1` | demandes | M1 `m1.lead_qualifie` | `lead_id` distincts | branché | idem |
| `m8_demandes_m1_sans_lead_m2` | demandes | M1 `m1.lead_qualifie` contre M2 `m2.client_associe` | **écart** : demandes de M1 sans lead reçu chez M2 | branché | idem |

Preuves : `departments/m08-analytics/tests/test_mesures_interdepartements.py` (pur, 55 tests), `…/test_entrepot_interdepartements.py`
(moteur, fraîcheur, entrepôt, wallboard, copilote), `tests/test_entrepot_m8_garanties.py` (les cinq garanties par source, 13 sources),
`tests/test_entrepot_m8_scenarios.py` (bout en bout multi-départements et cas négatifs).

## 4. Ce que les départements produisent et que M8 ne reçoit pas

| Département | Donnée | Pourquoi elle n'est pas dans l'entrepôt | État |
|---|---|---|---|
| M1 | volume brut de courriels reçus (`m1.courriel_recu`, identifiants seulement) | branchable, mais un courriel reçu n'est pas une demande (pourriel, factures de fournisseurs) : ce qu'on compte est une décision (D5) | non branché |
| M1 | plaintes structurées (`m1_lire_plaintes_structurees`) | aucun événement ; lecture T0 d'un autre département | impossible sans décision (D2) |
| M2 | pipeline, prévision (`m2_analyser_pipeline`, `m2_prevoir_pipeline`) | aucun événement ne publie les étapes ni la valeur du pipeline | impossible sans décision (D2 ou D3) |
| M2 | conversions et créances | via `m2.client_associe`, `m2.lead_assigne`, M3 et M5 : déjà dans les mesures ci-dessus | branché |
| M3 | mesures de vision validées (`m3.mesure_vision_validee`) | déjà rangées (vue exécutive) ; surface et longueur d'objets différents ne s'additionnent pas : aucune mesure d'entreprise défendable | non branché (voulu) |
| M4 | capacité d'équipe, cédule (`m4_lire_capacite_equipe`) | aucun événement | impossible sans décision (D2) |
| M4 | heures d'équipe | durée écoulée sur site (`m8_heures_sur_site_chantiers`) ; les heures-personnes et la paie restent chez M4 et M5 | branché (périmètre dit) |
| M5 | revenus facturés | `m5.rentabilite_chantier` ne porte pas le prix facturé ; aucune facture n'est publiée | impossible sans décision (D3) |
| M5 | coût réel / coût certifié | M8 **ne garde pas** les coûts de M5 : décision antérieure, épinglée par `test_evenements_rentabilite_chantier` (« M8 ne garde pas les coûts de M5 ») | impossible sans levée de cette décision (D4) |
| M5 | dépense publicitaire comptabilisée | M5 range un brouillon de charge pour chaque relevé de M7 mais ne publie aucun total | impossible sans décision (D1) |
| M5 | paies, DAS, dettes, réserves (composantes du cash libre) | déclarations du propriétaire ; branchables comme `m8_comptes_a_payer_cad` | non branché (portée) |
| M6 | disponibilité du stock (`m6_lire_disponibilite`) | aucun événement | impossible sans décision (D2) |
| M6 | commandes créées mais non envoyées | un bon de commande brouillon n'est pas un fait du bus | non branché (voulu : seul l'envoi approuvé compte) |
| M7 | leads par canal / par source | `m2.client_associe` porte `utm` mais M8 ne le garde pas ; associer `utm_source` à un canal de dépense est une décision d'affaires | impossible sans décision (D6) |
| M7 | valeurs de signaux (impressions, clics, performance) | `m7.signaux_marketing_constates` ne porte aucune valeur | impossible sans décision (D2) |

## 5. Décisions à prendre (aucune n'a été prise à la place du propriétaire)

- **D1. Dépense publicitaire comptabilisée (M5 → M8).** Pour que `m8_ecart_depense_pub_comptabilisee_cad` se calcule : M5 publie un
  total des charges de marketing **validées** (écritures définitives du compte de marketing) par période, soit en ajoutant un champ
  optionnel à `m5.mesures_comptables_constatees`, soit par un nouvel événement. Changement de code chez M5 et de catalogue.
- **D2. Lectures croisées M8 → départements.** Impressions et clics (M7), capacité (M4), pipeline (M2), disponibilité (M6), plaintes
  (M1) n'existent que comme outils de lecture T0. Il faudrait un port privé pour M8 (comme `lecteur_capacite_m4` pour M1) **qui n'élargit
  aucun droit d'appareil** et qui n'a pas besoin de l'admin authentifié pour un tour planifié. À décider avec l'architecte du socle.
- **D3. Factures émises (M5).** Ajouter `prix_facture_cad` (optionnel) à `m5.rentabilite_chantier`, ou publier un constat des factures,
  pour mesurer les revenus. M8 ne reconstruit pas le prix facturé à partir de la marge et du coût : ce serait refaire un chiffre de M5.
- **D4. Coût réel de M5 chez M8.** Levée de la règle « M8 ne garde pas les coûts de M5 » (ou non). Si levée : une mesure « coût réel
  cumulé des chantiers à coût complet » se fait en une demi-journée avec le même patron.
- **D5. Ce que « volume de demandes » veut dire** (demandes qualifiées, courriels, appels, toutes sources).
- **D6. Correspondance source UTM → canal de dépense** (par exemple `google` → `google_ads`) pour un coût par lead par canal.
- **D7. Fenêtres de fraîcheur.** Toutes les nouvelles mesures reprennent la fenêtre de 24 h du catalogue (décision d'architecte r1) ;
  pour des sources sporadiques (conversions importées à la main, réceptions) cette fenêtre les rend souvent « périmées » : au
  propriétaire de la fixer (`configuration.fraicheur_mesures_s`, vide). Aucune n'a été inventée.

## 6. Ce qui a été écarté, et pourquoi

- **Un statut `partielle` dans l'entrepôt.** Il aurait exigé une migration (contrainte `statut IN ('calculee','non_calculable')`), un
  changement du schéma fermé de `m8.fait_consolide` (consommé par M9 et M10) et de chaque consommateur de `statut`. La couverture est
  dite par un champ à part, dans le `detail` persisté de l'entrepôt, dans la tuile et dans la phrase du copilote. Limite : la ligne de
  l'entrepôt porte la couverture en **texte** (`detail`), pas en colonne.
- **Des tables de faits ou de marts supplémentaires** (par canal, par mois) : migration non nécessaire pour les mesures ; à reprendre
  si le propriétaire veut des découpes (D6).
- **Un recalcul des montants de M5** : créances, comptes à payer, solde, taxes passent sans calcul ; la marge est **cumulée** chantier
  par chantier à partir de la marge que M5 a chiffrée et qui a passé les gardes de `mesures_chantier` (prix définitif, coût complet).

## 7. Limites (sans euphémisme)

- Les producteurs réels de M5, M6, M7 et M1 ne sont **pas relancés** par les scénarios de ce chantier : leurs charges sont celles du
  catalogue (validées à la publication). La preuve des producteurs réels est dans leurs suites et, pour la marge et le cash libre,
  dans `test_cascade_marge_m5_m8_m10.py` et `test_cascade_cash_libre_m5_m8.py` (rejoués).
- **Le bus n'authentifie pas le producteur d'un événement** : un événement forgé qui respecte le schéma est livré. Les défenses de M8
  sont celles qu'elle peut avoir : schéma fermé (aucun champ personnel ne passe), clé de contenu, garde de cohérence (total des
  créances = somme des tranches), prix définitif et coût complet pour la marge, provenance et empreinte pour la preuve. Une
  authentification du producteur est un chantier du socle.
- La clé de contenu de `m7.signaux_marketing_constates` ne comprend pas `fraicheur_fenetre_h` : un second signal de même lecture avec
  une autre fenêtre est vu comme un doublon (il faut une nouvelle lecture pour qu'une nouvelle fenêtre s'applique).
- Les relevés publicitaires : un canal que M7 n'a jamais relevé est invisible (M8 ne sait pas si l'entreprise y dépense) ; la somme
  est celle des relevés **reçus**, jamais « la dépense ».
- Aucune de ces mesures n'est un chiffre comptable : toutes portent « À valider auprès d'un comptable (CPA) / professionnel
  qualifié » quand elles sont financières.
- Prouvé sur **SQLite** ; la construction de l'entrepôt n'a pas été exécutée sur PostgreSQL pour ces mesures (aucune table ni colonne
  n'a changé, donc aucune migration à qualifier : seul le contenu des lignes de `m8_ent_mesures_*` change).
- Aucun wallboard n'a été affiché sur un écran réel, aucun copilote n'a été essayé avec un modèle de langage : c'est la couche
  déterministe qui est prouvée.
- Score de santé : **non modifié**. Ajouter la marge, les créances ou les comptes à payer comme indicateurs est une décision de
  pondération et de bornes du propriétaire (`configuration.sante`, vide) ; les mesures sont disponibles pour cela.

## 8. Commandes

```bash
pytest departments/m08-analytics
pytest tests/test_entrepot_m8_garanties.py tests/test_entrepot_m8_scenarios.py tests/test_pont_bi.py tests/test_m8_memoire_m10.py
python scripts/docs/interconnexion_evenements.py --verifier
```
