# Entrepôt de M8 : d'où vient chaque mesure, et ce qui n'y arrive pas encore

Statut (2026-11-01, constats planifiés) : les sept constats de la phase 2 sont **déclenchés par le planificateur durable** (déclarés par
les manifestes, [PLANIFICATION §9](PLANIFICATION.md)) ; inactifs par défaut, prouvés sur SQLite avec horloge injectée, jamais sur PostgreSQL.
Statut (2026-11-01) : **phase 1** = cartographie par lecture du code, puis branchement de tout ce qui se branche sans nouveau droit
d'appareil, sans nouvel outil, sans migration et sans écriture dans un autre département (38 mesures). **Phase 2** = exécution des
décisions D1 à D7 de l'architecte (r10, §5) : sept départements PUBLIENT un résumé agrégé et minimisé sur le bus et M8 le consomme
(59 mesures depuis M5-PRE-AUDIT) ; **sept outils de constat** (huit avec le filet anti-perte de M2, neuf avec le pré-audit de M5) (T1/N2, agent seulement, **aucun droit d'appareil**), **aucune migration**, aucune lecture
croisée. Prouvé sur le **vrai bus**, les `consommateurs()` réels et une base SQLite migrée, avec des charges conformes au catalogue
d'événements. Rien n'a été exécuté contre PostgreSQL pour ces mesures, ni contre un service externe. Chantier C5 (2026-11-04) :
M5 PUBLIE en plus son constat de trésorerie prévue (`m5.tresorerie_prevue_constatee`, N3 à la demande + variante N2 planifiée
`tresorerie-prevue`, inactif par défaut) ; M8 en tire trois mesures — solde minimal prévu, semaines sous le seuil, écart
prévu-réel — soit **62 mesures**, trois tuiles de plus sur le wallboard finance-opérations (plafond porté de 12 à 16 tuiles)
et la règle `ALERTE-TRESORERIE-SOUS-SEUIL` enrichie. Contexte : `INTERCONNEXION.md` (le
bus), `M8-OLIVIER.md` (la couche analytique).

## 1. Pourquoi ce chantier

M8 est la vue exécutive de toute l'entreprise. L'audit d'interconnexion disait honnêtement que les constats de M7, M5 et M3
n'alimentaient pas l'entrepôt : ils arrivaient bien chez M8 (registre `faits_operations`) mais ne servaient qu'à la section
`operations_recues` de la vue exécutive. Le catalogue fermé n'avait que 18 mesures, aucune ne venait de la marge, des créances, des
comptes à payer, des relevés publicitaires, des réceptions de matériaux ni des demandes de M1.

Il en a maintenant **62** (18 + 20 + 21 de la phase 2 + 3 du chantier C5, dont deux pour le filet anti-perte de M2 et une pour le pré-audit de M5), lues par le **même moteur** (`moteur_mesures.lire`) que les wallboards, le score de santé, le
copilote, la mémoire (M10) et le pont BI : une mesure n'a qu'une valeur, qu'une provenance et qu'une fraîcheur, quelle que soit la
surface qui la montre.

## 2. Règles (les mêmes pour toutes les sources)

1. **Le bus, pas la lecture directe.** Chaque mesure vient d'un événement du catalogue que le département propriétaire publie.
   Aucune lecture croisée n'a été ajoutée : le port de M9 (`lecteur_producteurs_m9`) exige l'admin authentifié via M9 et ne convient
   pas à un tour planifié de M8 ; en élargir un autre serait élargir un droit, ce que le brief interdit. Quand la donnée n'était pas
   publiée (phase 2, D1 à D3), c'est le PRODUCTEUR qui publie un résumé agrégé (nouvel événement, schéma fermé), jamais M8 qui lit.
2. **Propriété des données.** Un consommateur n'écrit que dans le registre de M8 (mesuré : le monde de test observe chaque écriture).
3. **Idempotent par clé de contenu**, pas par `evenement_id` (même constat rejoué sous un autre identifiant : rien de plus).
4. **Provenance.** Chaque constat rangé dans `faits_operations` porte `provenance` : type d'événement, identifiant d'événement quand la
   charge en porte un, **empreinte** SHA-256 de la charge reçue. Chaque mesure calculée porte `entrees.empreinte_faits` : l'empreinte
   des faits qu'elle a réellement utilisés, **indépendante de l'ordre de livraison** (un fait utilisé qui change la change ; un fait
   qu'elle n'utilise pas ne la change pas).
5. **Fraîcheur : la plus stricte des trois.** Fenêtre de M8 (catalogue, ou propriétaire), fenêtre du **département source** quand il en
   déclare une (M7 dit `fraicheur_fenetre_h` pour chacune de ses sources publicitaires : portée par la mesure `fenetre_source_s`) et
   fenêtre demandée par l'appelant. Origine dite : `catalogue`, `cadence`, `configuration`, `source`, `appelant`, `terminale`. La fenêtre
   du producteur est `max(fenetre_s, cadence)` (D7, §5).
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

## 3. Matrice : les 58 mesures

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
| `m8_cash_libre_cad` | M5 `m5.cash_libre_constate` | branché | à la demande de l'admin (`m5_constater_cash_libre`, N3) ou par le constat planifié `m5.constat.cash-libre` (inactif par défaut, variante N2 : voir PLANIFICATION §9) ; le digest de 7 h ne le fait pas |

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
| `m8_ecart_depense_pub_comptabilisee_cad` | CAD | M7 relevés contre **M5 dépense comptabilisée** | **écart** nommé | branché en phase 2 (D1, §3.3) ; non calculable tant que M5 n'a publié aucun constat | idem |
| `m8_heures_sur_site_chantiers` | heures | M4 `m4.travaux_termines` (`duree_reelle_minutes`) | somme des durées sur site en heures (pas des heures-personnes) ; durée illisible dite | branché | idem |
| `m8_receptions_materiaux` | réceptions | M6 `m6.reception_enregistree` (**nouveau consommateur**) | par bon de commande et mouvement de stock | branché | idem |
| `m8_receptions_avec_ecart` | réceptions | idem | verdict de M6 ≠ CONFORME | branché | idem |
| `m8_commandes_envoyees` | commandes | M1 `m1.commande_courriel_envoyee` (**nouveau consommateur**) | bons de commande distincts dont le courriel est parti après approbation | branché | idem |
| `m8_demandes_qualifiees_m1` | demandes | M1 `m1.lead_qualifie` | `lead_id` distincts | branché | idem |
| `m8_demandes_m1_sans_lead_m2` | demandes | M1 `m1.lead_qualifie` contre M2 `m2.client_associe` | **écart** : demandes de M1 sans lead reçu chez M2 | branché | idem |

Preuves : `departments/m08-analytics/tests/test_mesures_interdepartements.py` (pur, 46 tests), `…/test_entrepot_interdepartements.py`
(moteur, fraîcheur, entrepôt, wallboard, copilote, 19 tests), `tests/test_entrepot_m8_garanties.py` (les cinq garanties par source, 13 sources,
66 tests), `tests/test_entrepot_m8_scenarios.py` (bout en bout multi-départements et cas négatifs, 11 tests), plus l'ajustement des tests
existants qui épinglaient 18 mesures, 4 registres ou 2 wallboards.

### 3.3 Les 20 mesures de la phase 2 (D1 à D3, D5, D6, puis M2-C1)

Chaque ligne : un événement NOUVEAU du catalogue (le producteur le publie par un outil de constat T1/N2, agent seulement), un
consommateur réel de M8 (registre `faits_operations`), un module pur de mesure (`mesures_constats.py`). « Fait qui fait foi » : la version
publiée en dernier (`publie_le`), sauf indication.

| Mesure | Unité | Événement (producteur · outil) | Calcul | Fait qui fait foi |
|---|---|---|---|---|
| `m8_depense_pub_comptabilisee_cad` | CAD | `m5.depense_publicitaire_constatee` (M5 · `m5_constater_depense_publicitaire`) | solde net hors taxes des écritures DÉFINITIVES qui viennent d'un relevé de M7 (ou le contre-passent), tel quel ; brouillons en attente = couverture partielle | plus grand `sequence` |
| `m8_ecart_depense_pub_comptabilisee_cad` | CAD | idem + `m7.depenses_marketing_constatees` | **écart nommé** : somme des relevés HORS_TAXES de la période du constat moins le comptabilisé ; relevés à cheval et TAXES_INCLUSES écartés et dits | idem |
| `m8_factures_emises` | factures | `m5.facture_emise_constatee` (M5 · `m5_constater_factures_emises`) | factures distinctes envoyées, sans les annulées après envoi ; **sans client** | statut le plus avancé |
| `m8_facturation_emise_cad` | CAD | idem | somme avant taxes ; taxes et après-taxes dites dans les entrées | idem |
| `m8_clics_recherche`, `m8_impressions_recherche` | clics, impressions | `m7.performance_signaux_constatee` (M7 · `m7_constater_performance_signaux`) | somme sur Search Console et Bing Webmaster ; jours couverts sur jours de la période ; chevauchement = aucune somme | par (source, compte, période) |
| `m8_visites_site` | visites | idem | une seule source d'audience (Umami OU Matomo : deux outils se recoupent, aucune somme) | idem |
| `m8_capacite_heures_disponibles`, `m8_capacite_heures_planifiees` | heures | `m4.capacite_equipe_constatee` (M4 · `m4_constater_capacite_equipe`) | heures d'équipe DÉCLARÉES, heures de cédule planifiées, semaine la plus récente aux journées datées ; semaine non calculable = causes de M4 | par semaine |
| `m8_charge_planifiee_pct` | % | idem | planifiées / disponibles du MÊME constat ; sans heure disponible : non calculable | idem |
| `m8_pipeline_leads_ouverts`, `m8_taux_conversion_resolus_pct`, `m8_valeur_ponderee_pipeline_cad` | leads, %, CAD | `m2.pipeline_constate` (M2 · `m2_constater_pipeline`) | tels que `m2_analyser_pipeline` les établit ; un taux ou une valeur que M2 refuse d'établir = non calculable | par jour |
| `m8_violations_sla_commercial` | violations | `m2.filet_anti_perte_constate` (M2 · `m2_constater_filet`) | somme des violations des règles SLA que le propriétaire a DÉCLARÉES (`configuration.sla` de M2) ; une règle sans délai est non évaluée (`null`, jamais zéro) ; **non calculable tant qu'aucune règle n'est évaluée en entier**, couverture partielle dite sinon | par jour (dernière publication) |
| `m8_constats_preaudit` | constats | `m5.preaudit_constate` (M5 · `m5_constater_preaudit`) | somme des constats des règles du pré-audit que M5 a ÉVALUÉES (dix règles déterministes) ; une règle sans seuil déclaré est non évaluée (`null`, jamais zéro) ; **non calculable tant qu'aucune règle n'est évaluée** ; couverture partielle (« 7 règles sur 10 ») nommant les règles non évaluées ou partielles ; ni facture, ni fournisseur, ni montant | par jour (dernière publication) |
| `m8_anomalies_integrite_crm` | anomalies | idem | somme des anomalies de huit contrôles d'intégrité des données de M2 (aucun seuil nécessaire : zéro est un vrai zéro) ; un contrôle à source illisible = couverture partielle, nommé | idem |
| `m8_articles_en_rupture`, `m8_articles_sur_reserves`, `m8_reservations_incompletes` | articles, réservations | `m6.disponibilite_constatee` (M6 · `m6_constater_disponibilite`) | cinq comptes, jamais un article ni une quantité ; aucun article suivi = non calculable (sauf les réservations) | par jour |
| `m8_plaintes_periode` | plaintes | `m1.plaintes_constatees` (M1 · `m1_constater_plaintes`) | nombre SEULEMENT si l'état est CONNUE ; « aucune déclarée par la source » et « non branchée » = non calculable | par jour |
| `m8_leads_publicitaires` | leads | `m2.client_associe` (`utm.utm_source`) + déclaration du propriétaire | leads dont la source UTM correspond à un canal déclaré ; leads sans source = couverture partielle | — |
| `m8_cout_par_lead_pub_cad` | CAD | relevés de M7 ÷ leads rattachés de M2, sur la période de chaque canal | **jamais sans la correspondance `canaux_marketing`** ; division par zéro refusée | — |

Preuves : `departments/m08-analytics/tests/test_mesures_constats.py` (pur, 57 tests : positifs, absences, ordre, forgé, aucune personne),
`…/test_phase2_unites.py` (types rangés, source UTM, déclarations, cadence), `tests/test_entrepot_m8_garanties.py` (les cinq garanties pour les
SEPT sources de plus : 101 tests en tout), `tests/test_entrepot_m8_phase2.py` (bout en bout multi-départements, panne et reprise, retour à une
version antérieure, rejeu, fraîcheur par cadence), et un fichier par producteur (`m5` : `test_interconnexion_m5_depense_publicitaire.py`,
`test_constats_pour_m8.py`, `test_operations_outils.py` ; `m7` : `signaux/test_constat_performance.py` ; `m4` :
`test_constat_capacite_equipe.py` ; `m2` : `test_constat_pipeline.py` ; `m6` : `test_constat_disponibilite.py` ; `m1` :
`test_plaintes_structurees.py`). Les sept outils sont aussi à l'audit d'interconnexion (producteur et consommateur réels, 56 types). **M2-C1** ajoute `m2.filet_anti_perte_constate` (`test_constat_filet.py` du département M2, `tests/test_filet_anti_perte_planifie.py`) : 57 types. **M5-PRE-AUDIT** ajoute `m5.preaudit_constate` (`departments/m05-financecore/tests/test_controleur_preaudit.py`, `tests/test_rapports_preaudit_bout_en_bout.py`, et les cinq garanties dans `tests/test_entrepot_m8_garanties.py`, source `preaudit`) : 60 types, voir [M5-RAPPORTS-PREAUDIT](M5-RAPPORTS-PREAUDIT.md).

Wallboards : `acquisition`, `ventes-clientele`, `equipes-materiel` (six tuiles chacun). Copilote : 33 cas de plus au corpus
(`evals/copilote.v1.yaml`, dont 14 refus), « volume de demandes » → `m8_demandes_qualifiees_m1` (D5).

## 4. Ce que les départements produisent et que M8 ne reçoit pas (après la phase 2)

| Département | Donnée | Pourquoi elle n'est pas dans l'entrepôt | État |
|---|---|---|---|
| M1 | volume brut de courriels reçus (`m1.courriel_recu`, identifiants seulement) | un courriel reçu n'est pas une demande (pourriel, factures de fournisseurs) : D5 tranche, le volume de demandes est celui des demandes qualifiées | non branché (voulu) |
| M1 | plaintes par catégorie, par type, par statut | le constat publié (`m1.plaintes_constatees`) ne porte que l'état et le nombre : une catégorie ou un pseudonyme de plainte est un renseignement sur une personne | non branché (minimisation) |
| M2 | prévision (`m2_prevoir_pipeline`) | un intervalle de prévision n'est pas un fait ; non publié | non branché (voulu) |
| M2 | intervalle de la valeur pondérée | le constat ne porte que le centre de l'estimation | non branché (minimisation) |
| M3 | mesures de vision validées (`m3.mesure_vision_validee`) | déjà rangées (vue exécutive) ; surface et longueur d'objets différents ne s'additionnent pas : aucune mesure d'entreprise défendable | non branché (voulu) |
| M4 | capacité par équipe, cédule jour par jour | le constat ne porte que deux totaux : une équipe ou un jour ramène à des personnes | non branché (minimisation) |
| M4 | heures d'équipe | durée écoulée sur site (`m8_heures_sur_site_chantiers`) ; les heures-personnes et la paie restent chez M4 et M5 | branché (périmètre dit) |
| M5 | coût réel / coût certifié | **D4 maintenue** : M8 ne garde pas les coûts de M5 (décision antérieure, épinglée par `test_evenements_rentabilite_chantier`) | non branché (décision) |
| M5 | autres charges que la publicité, autres comptes du grand livre | le constat de la dépense ne couvre que les écritures qui viennent d'un relevé de M7 | non branché (portée) |
| M5 | paies, DAS, dettes, réserves (composantes du cash libre) | déclarations du propriétaire ; branchables comme `m8_comptes_a_payer_cad` | non branché (portée) |
| M6 | quantités, articles, fournisseurs, prix | le constat ne porte que cinq comptes | non branché (minimisation) |
| M6 | commandes créées mais non envoyées | un bon de commande brouillon n'est pas un fait du bus | non branché (voulu : seul l'envoi approuvé compte) |
| M7 | requêtes, pages, référents, campagnes | aucun nom de requête ni de page ne part : seulement des totaux | non branché (minimisation) |
| M7 | impressions et clics PAR CONTENU (`m8_impressions_par_contenu`, `m8_clics_par_contenu`) | le résumé de performance est par source et par période du SITE, pas par contenu ; un contenu n'a pas de valeur de signal | impossible (aucune source par contenu) |

## 5. Décisions de l'architecte (r10) et leur exécution

La phase 1 avait laissé sept décisions ouvertes sans en prendre aucune à la place du propriétaire. L'architecte les a tranchées ; voici
ce qui a été fait, et ce qui ne l'a pas été.

- **D1. Dépense publicitaire comptabilisée : M5 publie un constat périodique agrégé** (`m5.depense_publicitaire_constatee`, sans
  fournisseur nominatif). FAIT. `m5_constater_depense_publicitaire(debut, fin, aujourd_hui, horodatage)` calcule, sur le grand livre,
  le solde net hors taxes des écritures DÉFINITIVES du compte « marketing » dont la pièce vient d'un relevé de M7 (l'écriture d'origine
  et sa contre-passation, qui reprend la même pièce, s'annulent), à leur date d'effet ; les brouillons attendant la validation d'une
  personne sont comptés à part. Le `sequence` (rang du constat dans le registre d'opérations de M5) fait qu'un retour à une version
  antérieure des données publie un événement distinct. `m8_ecart_depense_pub_comptabilisee_cad` se calcule désormais. Limite : seuls les
  relevés HORS_TAXES sont comptabilisés par M5 (un relevé TAXES_INCLUSES attend une décision fiscale) : M8 les écarte et le dit.
- **D2. Aucune nouvelle lecture croisée ni droit d'appareil : les producteurs publient des résumés agrégés, M8 les consomme.** FAIT pour
  M7 (valeurs de signaux), M4 (capacité), M2 (pipeline), M6 (disponibilité) et M1 (plaintes) : un événement nouveau chacun, un outil de
  constat T1/N2 chacun, **aucun rôle d'appareil**. Chaque constat est un RÉSUMÉ (totaux, comptes) : aucune équipe, aucun lead, aucun
  article, aucune plainte, aucune requête. Registre MCP scellé (7 outils ajoutés, révision 13).
- **D3. Facture émise : M5 publie un constat (montants, identifiant, sans client).** FAIT (`m5.facture_emise_constatee`,
  `m5_constater_factures_emises`). Une facture BROUILLON n'est jamais publiée ; ENVOYEE, PAYEE et ANNULEE (après envoi) le sont, un
  événement par (facture, statut).
- **D4. « M8 ne garde pas les coûts de M5 » : MAINTENUE.** Rien n'a été ajouté de ce côté.
- **D5. « Volume de demandes » = demandes qualifiées.** FAIT : `m8_demandes_qualifiees_m1` porte « volume de demandes » et
  « nombre de demandes » comme synonymes ; le copilote répond par cette mesure (cas `v69`, et test de bout en bout).
- **D6. Correspondance source UTM → canal : déclarée par le propriétaire dans `entreprise.yaml`, clé `canaux_marketing`.** FAIT
  (`taxonomie.py`, `docs/architecture/TAXONOMIE.md`). Sans déclaration valide, `m8_leads_publicitaires` et `m8_cout_par_lead_pub_cad`
  sont NON CALCULABLES et le disent ; un profil invalide est un verdict distinct de l'absence. Le fait « lead reçu » garde maintenant
  la source UTM en minuscules (jamais la campagne) ; la déclaration est un registre de plus (`declarations`) et entre dans l'empreinte
  de l'entrepôt.
- **D7. Chaque mesure déclare sa cadence ; fenêtre = max(24 h, cadence) pour les sources sporadiques ; aucune fenêtre inventée.** FAIT :
  `fraicheur.cadence_s` est OBLIGATOIRE au catalogue pour toute mesure non terminale (un entier de secondes, ou `null` = source
  sporadique dont personne n'a déclaré la cadence), le propriétaire déclare ou corrige une cadence par mesure
  (`configuration.cadences_mesures_s`, vide à la livraison), et la fenêtre du producteur est `max(fenetre_s, cadence)`. Le catalogue
  ne déclare une cadence que là où la nature de la source la fixe : les trois mesures de capacité d'équipe (constat par semaine,
  604 800 s) ; toutes les autres sont `null`. L'origine de la fenêtre est dite (`cadence`). La fenêtre de la source (M7) et celle de
  l'appelant continuent de resserrer.

## 6. Ce qui a été écarté, et pourquoi

- **Un statut `partielle` dans l'entrepôt.** Il aurait exigé une migration (contrainte `statut IN ('calculee','non_calculable')`), un
  changement du schéma fermé de `m8.fait_consolide` (consommé par M9 et M10) et de chaque consommateur de `statut`. La couverture est
  dite par un champ à part, dans le `detail` persisté de l'entrepôt, dans la tuile et dans la phrase du copilote. Limite : la ligne de
  l'entrepôt porte la couverture en **texte** (`detail`), pas en colonne.
- **Des tables de faits ou de marts supplémentaires** (par canal, par mois) : migration non nécessaire pour les mesures ; à reprendre
  si le propriétaire veut des découpes (D6).
- **Un recalcul des montants de M5** : créances, comptes à payer, solde, taxes passent sans calcul ; la marge est **cumulée** chantier
  par chantier à partir de la marge que M5 a chiffrée et qui a passé les gardes de `mesures_chantier` (prix définitif, coût complet).

## 7. Ordre de livraison et `publie_le`

La revue adverse a fait départager les versions d'un constat comptable de M5 du même jour par l'**instant de publication** que le bus
donne (`repartiteur.instant_publication_livre()` → `publie_le`, gardé hors de toute clé de contenu). `dernier_constat_comptable`
(partagé par la vue exécutive et par les mesures `m8_creances_*` et `m8_ecritures_en_attente`) suit cette règle : plus grande date de
référence, puis publication la plus récente, puis dernier reçu (test : deux versions du même jour, livrées dans les deux ordres).
Les autres sources n'ont **pas** besoin de cet instant : rentabilité et cash libre s'ordonnent par leur `sequence` (M5), les relevés
par `revision`, les réceptions, commandes, conversions et anomalies sont des faits indépendants à clé de contenu (testés dans l'ordre
inverse de livraison).

**Phase 2.** Les sept résumés (§3.3) sont des versions successives d'un même objet (une semaine, un jour, une période, une facture) : leur
ordre ne se lit que par l'instant de PUBLICATION (`publie_le`, gardé sur le fait rangé, hors clé de contenu), sauf deux cas où le
producteur donne mieux : la dépense comptabilisée (le plus grand `sequence` de M5) et l'état d'une facture (le plus avancé : payée ou
annulée ne redevient pas « envoyée »). Prouvé au niveau du bus : M8 en panne à la première livraison, l'ancienne version est reprise
APRÈS la récente et ne la remplace pas (`tests/test_entrepot_m8_phase2.py`, cinq producteurs).

**Retour à une version antérieure (A, B, A).** Un identifiant déterministe fondé sur la seule version des données fait du troisième
constat un doublon du premier : le bus le ré-absorbe sans le republier et M8 resterait sur B. Pour M4, M2 et M6 (dont les données
peuvent revenir en arrière dans la journée), l'**instant du constat** (`constate_le`, donné à l'outil) entre dans l'identifiant et dans
la clé de contenu, jamais dans `version_donnees` : rejouer le MÊME constat (même instant) ne publie rien, un constat à un autre instant
est un événement de plus, et le dernier publié fait foi. M5 le fait par `sequence`, M7 par `derniere_observation_le` (dans la version),
M1 par l'empreinte du contenu lu (les plaintes ne reviennent pas en arrière). Coût : un événement par constat, pas par changement.

## 8. Limites (sans euphémisme)

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
- **Phase 2 : les constats sont maintenant DÉCLENCHÉS par le planificateur durable, mais ce n'est prouvé que pour ce qui suit.**
  Chaque département déclare son constat (bloc `constats_planifies` du manifeste) et le planificateur l'appelle à une cadence dérivée
  de la fraîcheur du catalogue de M8 ([PLANIFICATION §9](PLANIFICATION.md)). Prouvé (`tests/test_entrepot_m8_planifie.py`, SQLite, horloge
  injectée, données fictives) : les vrais outils des six producteurs publient, les événements traversent le vrai bus et le vrai
  répartiteur, M8 calcule les 16 mesures alimentées (valeurs recoupées avec la propre lecture de chaque département), les
  wallboards de la vraie console les affichent, le copilote répond, M10 et M9 reçoivent le fait consolidé ; rien ne part par défaut ni
  en ombre ; un redémarrage, une deuxième instance ou un double déclenchement ne publient pas deux fois ; une avance de plusieurs
  cadences ne rattrape pas en rafale ; la panne d'un département n'arrête pas les autres, rend sa mesure périmée après deux passages
  manqués puis se rétablit. **Reste vrai** : tout est **inactif par défaut** (un admin doit activer chaque constat : `ombre` puis `actif`) ;
  **rien n'a tourné sur PostgreSQL ni sur la boucle réelle du serveur pendant des jours** ; la valeur pondérée du pipeline reste
  non calculable tant que personne ne déclare de valeur sur les leads, et le coût par lead tant que le propriétaire ne déclare pas
  `canaux_marketing`. Le rythme reste réglable par le propriétaire (`cadences_mesures_s`, intervalle de l'exécuteur).
- **Phase 2 : la péremption des mesures de M7 et des factures n'est pas celle du constat.** Leur « dernier fait » est l'observation du
  signal (M7) ou le jour d'émission (factures) : un constat qui repasse sans fait nouveau ne les rend pas « à jour ». Les mesures de
  M4, M2, M6 et M1 sont datées de l'instant du constat, donc la planification les garde fraîches.
- **Phase 2 : « clics, impressions, visites du site » sont cumulatifs.** M8 somme tous les résumés mensuels de M7 qu'il a reçus (périodes
  sans chevauchement) : la mesure vaut « depuis le premier constat », pas « du mois en cours ». Définition de M8, non modifiée.
- **Phase 2 : les producteurs réels sont prouvés dans leurs suites ET, depuis la planification, enchaînés jusqu'au wallboard.** Les
  scénarios de `test_entrepot_m8_phase2.py` publient des charges conformes au catalogue (`tests/fixtures/interconnexion_charges.py`) ;
  chaque outil de constat est prouvé séparément sur son vrai registre (M5 : `test_interconnexion_m5_depense_publicitaire.py` et
  `test_operations_outils.py` ; M7, M4, M2, M6, M1 : un fichier chacun) ; `test_entrepot_m8_planifie.py` appelle les sept outils réels par
  le planificateur et suit leurs événements jusqu'au wallboard de la console, au copilote, à M10 et à M9 (SQLite, puis rejoué sur PostgreSQL 17
  réel depuis la vague 8 : `test_postgresql_rejeu_entrepot_m8_planifie.py`, et en vrais processus : `test_postgresql_planification_constats.py` ;
  un identifiant de plus de 256 caractères est refusé à la réception, il ne peut plus bloquer la construction sur PostgreSQL).
- **Phase 2 : seuls les relevés HORS_TAXES se comparent à la dépense comptabilisée** ; la dépense comptabilisée ne couvre que les
  écritures qui viennent d'un relevé de M7 (pas la publicité payée autrement). L'écart est donc un écart de DÉFINITION, pas une erreur.
- **Phase 2 : la capacité est celle de la semaine la plus récente constatée** aux journées datées ; la semaine type n'est pas la
  capacité de la semaine. Les heures sont celles des équipes DÉCLARÉES, jamais des heures-personnes.
- **Phase 2 : le coût par lead** divise la dépense des relevés par les leads que la correspondance déclarée rattache aux mêmes canaux
  sur la période de chaque canal ; un lead sans source UTM n'y est pas, et un canal sans lead dans sa période coûte quand même (sa
  dépense est au numérateur). Ce n'est pas un coût d'acquisition comptable.
- **Phase 2 : l'empreinte de provenance** d'un résumé porte la charge reçue ; le bus n'authentifie toujours pas le producteur (voir
  plus haut).
- `m8.fait_consolide` et ses consommateurs (M9 : `charges_athena.py`, M10 : `analytique.py`, `memoire.py`, `synthese_direction.py`)
  acceptaient 40 mesures : les bornes passent à 80 (changements 80, anomalies 160), sans autre changement de contrat.
- Prouvé sur **SQLite** ; la construction de l'entrepôt n'a pas été exécutée sur PostgreSQL pour ces mesures (aucune table ni colonne
  n'a changé, donc aucune migration à qualifier : seul le contenu des lignes de `m8_ent_mesures_*` change).
- Aucun wallboard n'a été affiché sur un écran réel, aucun copilote n'a été essayé avec un modèle de langage : c'est la couche
  déterministe qui est prouvée.
- Score de santé : **non modifié**. Ajouter la marge, les créances ou les comptes à payer comme indicateurs est une décision de
  pondération et de bornes du propriétaire (`configuration.sante`, vide) ; les mesures sont disponibles pour cela.

## 9. Mutations

**Phase 1.** Cinquante-trois mutations appliquées une à une dans un clone (témoin vert avant chaque série), sur le code de ce chantier :
somme et révisions des relevés, frontières de chevauchement et de jours sans relevé, bases de taxes, garde d'incohérence des créances,
tranche 90+, marge nulle, couverture partielle (module, entrepôt, tuile, copilote, bannière), fenêtre de M7 (plus stricte, égalité,
signal de démonstration, canal Meta), dernier fait, clés de contenu (réception, commande), provenance, fait de la réception/commande
minimisé, section de la vue exécutive, composantes du cash libre, écritures en attente, copilote (« comptes à payer » pris pour un
ordre), registre `operations` de l'empreinte. Quatre ont d'abord SURVÉCU (marge nulle comptée en perte, couverture « inconnue » des
mesures de la tranche 1, clé de contenu des commandes, clé de contenu des réceptions) : un test chacune les a fermées.

**Phase 2.** Quarante-huit mutations, une à une dans un clone (témoin vert avant chaque famille de cibles) : le consommateur et les
mesures de M8 (30), les calculs des producteurs (18). Plus grand `sequence` de la dépense, signe et bornes de l'écart (relevés TAXES_INCLUSES,
à cheval), statut d'une facture le plus avancé, annulées comptées, compte de démonstration, version la plus ancienne, deux outils
d'audience, chevauchement de périodes, semaine type, semaine la plus ancienne, rapport inversé, base nulle, taux refusé devenu zéro,
aucun article suivi, état des plaintes, doublon de lead, leads hors période, division par zéro, relevés qui se chevauchent,
déclaration absente, `publie_le` de la capacité, clé de contenu de la capacité, charge non réduite à la liste fermée, source UTM en
minuscules, cadence (sens, cadence du propriétaire, obligation), déclarations dans l'empreinte ; côté producteurs : solde net de M5,
brouillons, écritures hors relevé ou hors compte, bornes de la période, brouillon de facture publié, facture annulée sans envoi, jours
sans fait de M7, jours couverts, codes de manque de M4 et instant du constat dans l'identifiant, pourcentage de M2, garde du
périmètre global de M2, comptes de M6 (sur-réservé, rupture, incomplète), nombre des plaintes de M1. **Trois ont d'abord SURVÉCU** :
la borne incluse du chevauchement de périodes de M7 (un seul jour en commun), une écriture hors relevé comptée par M5, et une facture
en brouillon publiée (rattrapée seulement par une seconde garde) ; un test unitaire chacune les a fermées (borne d'un jour, module pur
`constats_pour_m8` testé directement, y compris les états forgés), puis **toutes ont été rejouées tuées** (48 sur 48). Une quatrième
(statut de la facture, ordre de publication) n'était tuée que par un test de bus lent : un test unitaire la tue maintenant en une
seconde.

**Constats planifiés.** Trente mutations, une à une dans un clone (témoin vert avant la série, restauration vérifiée par somme de
contrôle) : alignement du créneau sur minuit local, arrondi à l'intervalle, `lundi`, `fin_mois`, décalage de mois et de jours,
nombre de passages par fenêtre, mesure la plus stricte, cadence de la source et fenêtre du propriétaire dans la dérivation, borne
de l'intervalle par défaut, jeu d'appels qui échoue, refus rendu par l'outil, `NiveauInterdit` avalé, ombre qui appelle l'outil,
intervalle réglé par l'admin, arguments calculés sur l'horloge plutôt que sur le créneau, arrêt propre entre deux jeux, famille de la
console, définitions dynamiques, exécuteurs absents du tour, vérificateur du dépôt et son contrôle de niveau, grammaire des calculs,
décalage illimité, outil d'un autre département, et quatre erreurs de manifeste (mois précédent de M7, semaine de M4, période de M5,
mesure inconnue de M6). **Une a d'abord SURVÉCU** (le cache des définitions ne voyait pas une édition sur place du manifeste de M8) ;
un test l'a fermée, puis **30 sur 30 ont été rejouées tuées**. Rouge avant, démontré : sur la base `234bebe08`, les trois fichiers de
preuve échouent à l'import (le module et le bloc de manifeste n'existent pas) ; sur le code livré avec les blocs
`constats_planifies` retirés des six manifestes, 27 des 84 tests nouveaux échouent (aucun exécuteur, mesures non calculables).

## 9 bis. Pourquoi une mesure est vide : l'état de la collecte (chantier C2)

Une mesure « non calculable » ou « périmée » a plusieurs causes très différentes : un constat jamais activé, un constat en ombre
(il ne publie rien), une activation de 90 jours échue, un constat en erreur, un bus qui n'a rien livré, un département source qui
répond « non calculable, manque X » (une déclaration du propriétaire à fournir, pas un geste technique), un planificateur coupé.
Le même mot « vide » les cachait toutes. `m8_lire_etat_collecte` (T0/N0, `collecte.py` pur + un port vers le planificateur) dit
laquelle, par mesure, avec la phrase et l'action. (Le champ s'appelle `etat_collecte`, pas `cause` : la garde AST de M8, `verifier_aucune_cause_signalee`, interdit à M8 de signaler une cause d'affaires ; ici il s'agit de l'état du pipeline de collecte, jamais d'une explication du résultat de l'entreprise.)

| État de collecte (`etat_collecte`, ensemble fermé) | Quand | Action rendue |
|---|---|---|
| `planificateur_coupe` | `OPSYS_PLANIFICATEUR_CONNECTEURS=0` | retirer le coupe-circuit |
| `constat_inactif` / `constat_expire` | un constat déclaré nourrit la mesure et n'est pas actif (jamais activé / 90 jours échus) | activer (ou renouveler) en ombre, lire « aurait », passer en actif, à la page Connecteurs |
| `constat_en_ombre` | le constat dit ce qu'il ferait et ne publie rien | passer à l'actif |
| `constat_en_erreur` | le dernier passage a échoué (erreur, refus, plafond, attente de transport) | lire le code typé, corriger ; il repasse seul |
| `jamais_recue` | constat actif et sain, mais aucun fait reçu pour la mesure | attendre un créneau, vérifier le bus (livraison à M8) |
| `producteur_non_calculable` | reçue, mais le département source a répondu « non calculable » (le manque est dit) | fournir la déclaration demandée |
| `source_perimee` | reçue, calculée, plus vieille que sa fenêtre malgré des passages réussis (ou sans constat) | vérifier la date du fait et la fenêtre (`fraicheur_mesures_s`) |
| `sans_constat_planifie` | aucun constat déclaré ne nourrit la mesure (elle dépend d'un événement ou d'un geste humain) | vérifier le département source |
| `fraicheur_inconnue` | l'instant du dernier fait est illisible | vérifier l'instant publié |

Ordre des états : coupe-circuit, puis constat non actif, puis erreur de passage, puis le reste (une mesure à jour est `a_jour` quel que soit
le mode de son constat). Les constats nourrissant une mesure viennent des MANIFESTES (`constats.declarees()`), jamais d'une liste
recopiée ; l'état vient du planificateur lui-même (`etat.vue`) : M8 n'en garde aucune copie et n'active rien. Trois vues paginées
sous la limite du socle : `resume` (défaut : comptes par cause, un état par constat), `mesures` (cause, phrase, action,
constats), `liste_de_controle` (interrupteur général, puis pour chaque constat : activer en ombre, passer en actif, premier
passage réussi ; « fait » se lit de l'état, il ne se déclare pas). Aucune valeur de mesure n'est rendue. Aucun droit d'appareil :
l'identité d'un admin est revérifiée en base ; la console appelle l'outil sous le rôle `admin`.

La vue : **page Collecte** de la console (`/collecte`, `/api/collecte`, `console/collecte_ui.py`, lecture seule, admin relu en base,
sans formulaire ni script) et **wallboard `collecte`** (`wallboards/collecte.v1.yaml`, un témoin par constat planifié ; sa liste se
déduit des manifestes dans un test). Prouvé : `departments/m08-analytics/tests/test_collecte.py` (pur, 29 cas),
`tests/test_etat_collecte_m8.py` (vrai planificateur, bus et M8 : installation neuve, ombre, actif non livré, livré,
panne puis reprise, activation échue, coupe-circuit, lecture seule, aucune valeur, accès, arguments hostiles, pagination),
`tests/test_console_collecte.py` (accès, lecture seule, étapes, API, wallboard). Limites : SQLite seulement, horloge injectée ;
la cause d'une mesure nourrie par plusieurs constats est celle du premier non sain ; la page ne propose aucun bouton (l'activation
reste à la page Connecteurs) ; aucun parcours navigateur réel.

## 9 ter. La qualité des données branchée : `QUALITY_FAIL` et pastilles (chantier C4)

**Le défaut.** La qualité n'était pas branchée sur le catalogue : un revenu négatif, un total qui n'est pas la somme de ses tranches, des
clics plus nombreux que les impressions traversaient M8 (la tuile les montrait, le copilote les citait, le score les notait). Seul le
constat des créances avait sa garde locale (« non calculable » parmi d'autres).

**Le correctif.** `definitions/m8-qualite.v1.yaml` (fichier validé en entier, refusé au moindre écart : clé inconnue, mesure hors catalogue,
doublon, borne illisible, vérification inconnue) déclare des règles d'un ensemble FERMÉ, évaluées de façon DÉTERMINISTE, sans horloge, par
`qualite_mesures.py` dans `moteur_mesures.lire` :

| Genre | Ce qui doit être vrai | Exemples livrés |
|---|---|---|
| `plage` | une mesure reste dans [min, max] (au moins une borne, texte décimal) | comptes, durées, charge ≥ 0 ; revenu facturé, carnet, créances, valeur du pipeline ≥ 0 ; taux d'acceptation et de conversion entre 0 et 100 |
| `relation` | `gauche` ≤ `droite`, les deux calculées (l'échec bloque les deux : on ignore laquelle est fausse) | créances 90 jours et plus ≤ total ; clics ≤ impressions ; réceptions avec écart ≤ réceptions ; chantiers en perte ≤ chantiers à marge connue ; signaux de matériaux ≤ chantiers terminés ; demandes sans lead ≤ demandes qualifiées ; leads publicitaires ≤ leads |
| `controle` | une cohérence d'un FAIT source (ensemble fermé de vérifications du code) | total des créances = somme de ses tranches (aucune négative) ; facture : montants lisibles, ni négatifs, total = avant taxes + taxes ; cash libre : montant lisible, `en_deficit` = signe du montant, comptes à payer ≥ 0 |

**Aucune règle n'est un seuil d'affaires** (un cash libre bas est une ALERTE, §9 quater) : seulement des invariants qu'aucune entreprise ne
viole sans qu'une donnée soit fausse. Un déficit réel et cohérent n'est donc PAS une erreur de qualité (testé). Une mesure qu'aucune règle
ne couvre est « non évaluée » (jamais un « ok » par défaut).

**Un échec BLOQUE** les mesures que la règle nomme : `statut` = `non_calculable`, `valeur` et `entrees` vides (la valeur douteuse n'est
conservée nulle part), `manque` = `[{champ: qualite, raison: "contrôle de qualité en échec : …"}]`, `qualite` = `{statut: echec, echecs: [règle,
ce qu'elle vérifie, nombre de faits, références (identifiant de facture, jour du constat)]}`. Aucun chiffre tiré d'une donnée n'est repris.
Le blocage est une fonction des faits : une fois le constat corrigé et republié, la mesure se rétablit d'elle-même.

| Surface | Ce que fait un échec de qualité |
|---|---|
| Tuile et bannière du wallboard | pastille `QUALITY_FAIL` dite en toutes lettres (« Qualité en échec (QUALITY_FAIL) »), libellé « QUALITÉ EN ÉCHEC », classe et motif distincts, aucune valeur ; la bannière passe au moins à « attention » et le dit (pas comptée comme une donnée manquante) |
| Copilote | REFUS typé `REJ-COPILOTE-QUALITE-ECHEC` avec explication, `chiffres` vide, reçu authentique ; question mixte : les mesures saines sont données, la bloquée est dite « BLOQUÉE » ; fraîcheur et tendance ne citent rien |
| Score de santé | l'indicateur n'est pas noté, la composante est indéterminée avec la raison `qualite_echec` (distincte de « mesure non calculable ») ; le score global l'est aussi |
| Collecte (`m8_lire_etat_collecte`) | état `qualite_en_echec` (ni un manque ni un retard de collecte) avec l'action |
| Mémoire | anomalie `echec_qualite` dans `m8.fait_consolide` (additif : schéma + M10 + validateur de M9), répétée à chaque consolidation tant qu'elle dure ; M10 la mémorise sans valeur |
| Entrepôt, pont BI | la ligne est `non_calculable` avec le détail ; aucune valeur douteuse n'est exportée |

**Pastilles** (`pastilles.py`, DÉRIVÉES, aucune table) : `QUALITY_FAIL` > `GATED` (non calculable ET un geste humain la retient : constat jamais
activé, en ombre, expiré, planificateur coupé ; seulement quand l'état de collecte a pu être lu) > `MISSING` (non calculable autrement) >
`STALE` (périmée ou fraîcheur inconnue) > `PARTIAL` (couverture partielle) > `FRESH`. **Pas de `LIVE`** (aucune source n'est temps réel : le
rafraîchissement du wallboard relit des faits), **pas d'`ESTIMATED`** (M8 ne produit aucune estimation). Une donnée vieille n'est jamais
`QUALITY_FAIL` : c'est une autre dimension (`STALE`).

`m8_lire_rapport_qualite` (T0/N0, aucun droit d'appareil, admin relu en base) : par département source, les règles en échec, ce qu'elles
vérifient, le geste de correction (gabarit du fichier de règles), pages bornées, aucune valeur de mesure.

**Prouvé** : `departments/m08-analytics/tests/test_qualite_mesures.py` (règles, refus d'un fichier abusif, chaque genre en échec et en
succès, forme du blocage, rétablissement, pastilles et leur ordre, tuile, bannière, copilote, score, collecte, mémoire, rapport) et
`tests/test_m8_qualite_planifiee.py` (vrai bus, vrai planificateur à horloge injectée, vrais outils : un relevé de moteur de recherche dont les
clics dépassent les impressions bloque la mesure, la tuile de la vraie console, le copilote, le rapport et la mémoire de M10, puis tout se
rétablit à la correction ; un constat de cash libre incohérent bloque les quatre mesures et rend la composante « finance » indéterminée).

**Limites (sans euphémisme)** :
- Les contrôles sont ceux que les FAITS REÇUS permettent. Unicité, intégrité référentielle, « une soumission a un client », « un chantier a une
  adresse », « une fin a un horodatage » ne sont pas évaluables : M8 ne reçoit pas ces champs (ils restent chez les départements sources).
- Une valeur plausible mais fausse passe : le bus n'authentifie pas le producteur d'un événement (limite du socle), et aucune règle de M8 ne sait
  qu'un montant cohérent est inexact.
- Pour une règle `relation`, M8 ne sait pas laquelle des deux mesures est fausse : les deux sont bloquées.
- Aucun historique daté des échecs : le rapport est une fonction des faits d'aujourd'hui ; la trace durable est l'anomalie `echec_qualite` des
  consolidations (M10).
- `GATED` se dérive de l'état du planificateur : hors transaction d'outil ou sans les tables du planificateur, la pastille est `MISSING`.
- Prouvé sur SQLite, données fictives, horloge injectée ; PostgreSQL non rejoué pour ce chantier ; aucun parcours navigateur réel de la
  pastille (le script est exercé sous Node avec un faux DOM ; le rendu serveur est testé dans la vraie console).

## 9 quater. Les alertes métier : règles déclaratives, cycle de vie, action proposée (chantier C3)

**Le défaut.** M8 n'avait aucune alerte métier (trésorerie, baisse de leads, rupture, facture en retard), aucun cycle de vie (accusé, report,
résolution), aucune poussée vers un humain ; seules existaient les alertes de qualité d'une métrique d'agent et deux seuils de chantier.

**Le correctif.** `definitions/m8-alertes.v1.yaml` (validé en entier, mêmes refus que les règles de qualité, plus : gabarit d'action
inconnu, champ de gabarit inconnu, deux règles pour la même mesure ou le même seuil) déclare huit règles sur le catalogue fermé :

| Règle | Genre | Mesure | Sens | Gravité |
|---|---|---|---|---|
| `ALERTE-TRESORERIE-SOUS-SEUIL` | seuil | cash libre | atteint ou passe sous | critique |
| `ALERTE-CREANCES-90-JOURS` (facture en retard) | seuil | créances de 90 jours et plus | atteint ou dépasse | attention |
| `ALERTE-CONVERSION-SOUS-SEUIL` | seuil | taux d'acceptation | atteint ou passe sous | attention |
| `ALERTE-DEVIS-SANS-REPONSE` | seuil | soumissions sans réponse | atteint ou dépasse | attention |
| `ALERTE-RUPTURE-MATERIEL` | seuil | articles en rupture | atteint ou dépasse | attention |
| `ALERTE-PIPELINE-BAS` | seuil | leads ouverts (un NIVEAU, pas une variation) | atteint ou passe sous | attention |
| `ALERTE-DONNEE-PERIMEE` | péremption | cash libre, créances, leads ouverts, ruptures, plaintes (mesures rafraîchies par un constat) | périmée alors qu'elle était calculée | attention |
| `ALERTE-QUALITE-ECHEC` | qualité | toute mesure | bloquée par le contrôle de qualité | attention |

**Les seuils sont ceux de la direction, jamais ceux de M8** : six réglages de direction (`m8.seuil_alerte_*`, type décimal, N3, aucune
proposition, `configuration.alertes.seuils.<nom>`), adoptés depuis la console (retour arrière possible) ; vides à la livraison. Sans seuil, ou avec
un seuil illisible, la règle est **« non évaluée »** et `m8_lire_alertes_metier` le dit (`a_configurer` / `invalide`), jamais une alerte sur un
seuil deviné. La borne franchit (au_dessous : ≤ ; au_dessus : ≥). Une valeur périmée, de fraîcheur inconnue, non calculable ou bloquée par la
qualité n'alerte JAMAIS sur sa valeur et ne résout rien.

**Une alerte** dit la valeur courante et la référence franchie, propose une **action d'un gabarit fermé** (huit, dans le fichier ; la finance
porte « À valider auprès d'un comptable (CPA) / professionnel qualifié »), **nomme le département propriétaire** de la mesure au catalogue (dérivé,
jamais déclaré à part) et liste les mesures à consulter. **Jamais de cause** (la garde AST du paquet interdit la clé ; un test vérifie aussi les
objets produits).

**Cycle de vie** (registre append-only `alertes_metier`, chaîné) : `alerte_ouverte` (UNE par épisode, id `règle:mesure:rang`), `alerte_accusee`
(« vu » : sort de « À voir », l'épisode reste ouvert ; un double accusé n'écrit rien), `alerte_reportee` (cachée jusqu'à un instant futur, au plus 30
jours ; un report échu redonne l'alerte SANS rien écrire), `alerte_resolue` (retour dans la cible constaté sur une valeur à jour). Un report lève un accusé
et un accusé lève un report. Une rechute ouvre l'épisode SUIVANT. Borne : 30 ouvertures par 24 h (le surplus est compté et reviendra).

**Évaluation et proposition.** Quatrième étape du tour planifié `m8.entrepot` (`m8_evaluer_alertes_metier`, N2, agent seulement ; en ombre il dit
« aurait » et n'écrit rien). Chaque ouverture publie UNE FOIS `m8.alerte_proposee` (extension ADDITIVE : types `METIER-SEUIL-FRANCHI`,
`METIER-DONNEE-PERIMEE`, `METIER-QUALITE-ECHEC`, une forme de preuve, champs facultatifs `gravite`, `alerte_id`, `mesures_liees` ; identifiant
déterministe) que M9 reçoit (briefing). `attentes()` de M8 met les alertes OUVERTES dans « À voir » du propriétaire (niveau N3 si critique, N2 sinon ;
aucun montant dans le résumé). **Rien n'est poussé hors de l'application** (ni téléphone, ni courriel) : c'est une décision du propriétaire, en attente.

**Prouvé** : `departments/m08-analytics/tests/test_alertes_metier.py` (pur) et `tests/test_m8_alertes_metier_planifiees.py` (vrai planificateur à horloge
injectée, vrai bus, vrai sas N3 pour adopter le seuil, vraie section « À voir » du socle) : sans seuil rien ne s'ouvre ; trésorerie sous le seuil
déclaré → une alerte avec action et propriétaire, reçue par M9, visible dans « À voir » ; dix passages de plus n'ouvrent rien ; accusé, double accusé,
report, échéance, résolution, rechute (épisode 2) ; valeur périmée ; retour arrière du seuil ; ombre ; aucun envoi ni donnée personnelle.

**Limites (sans euphémisme)** :
- **« Baisse de leads » n'est pas couverte comme variation** : les comptes de leads sont cumulatifs et M8 n'a pas d'historique de période ; seule la règle
  `ALERTE-PIPELINE-BAS` (niveau de leads ouverts) existe. Une variation demandera les tendances déterministes (autre chantier).
- Aucun écran pour accuser ou reporter : les gestes passent par les outils N2 d'un AGENT (`par` = « agent », pas une identité de personne) ;
  les écrans mobiles sont un autre chantier (aucun droit d'appareil n'est ajouté). La résolution est automatique seulement (aucune résolution
  manuelle : elle se rouvrirait à l'évaluation suivante tant que la valeur reste franchie).
- Pas d'hystérésis : une valeur qui oscille autour du seuil ouvre des épisodes successifs (bornés à 30 par 24 h).
- Le seuil retiré (retour arrière) rend la règle non évaluée sans fermer l'épisode en cours.
- Aucune poussée externe, aucune escalade, aucun canal : « À voir » et le briefing de M9 seulement. Les seuils critiques et le canal de poussée sont une
  décision du propriétaire (ANALYSE-M8 §5, Q2) ; aucune valeur n'est proposée.
- Cadence : celle du tour `m8.entrepot` (3 600 s par défaut) et seulement une fois qu'un admin l'a activé (inactif par défaut).
- Prouvé sur SQLite, données fictives, horloge injectée ; PostgreSQL non rejoué pour ce chantier.

### Mutations de D0, C4 et C3 (64, une à une, dans un clone)

Chaque mutation est appliquée seule dans un CLONE du dépôt, les tests ciblés (pur + bout en bout) sont rejoués, le fichier est restauré et
son empreinte comparée à l'original (restaurations vérifiées). Résultat : **63 tuées, 1 survivante équivalente**. Une première passe avait laissé passer une vraie
mutation (les types d'alerte `METIER-DONNEE-PERIMEE` et `METIER-QUALITE-ECHEC` permutés ; une autre mutation était inapplicable, son texte
ayant été reformaté) : un test (`test_chaque_genre_de_regle_ouvre_son_propre_type_d_alerte_et_le_bon_departement`) tue la première et la seconde
est rejouée. Les mutations « mauvaise dimension » comptent :

| Famille | Exemples tués |
|---|---|
| D0, jour local (11) | jour dans le fuseau UTC au lieu du fuseau local ; décalage fixe de cinq heures sans heure d'été ; fuseau déclaré ignoré (synthèse, interdépartements, constats : trois chemins distincts) ; fuseau illisible replié sur l'UTC ; adaptateur qui déclare l'UTC ; défaut du planificateur en UTC ; fin de journée au lieu du début ; fenêtre doublée |
| C4, qualité et pastilles (25) | `QUALITY_FAIL` traité comme `STALE` ou comme `MISSING` ; `GATED` confondu avec `MISSING`, tout non calculable devenu `GATED`, `jamais_recue` comptée comme geste humain ; l'échec ne bloque plus la valeur ; relation à l'envers ; bornes de plage exclusives ; déficit incohérent, total des créances, total de facture, montant négatif non contrôlés ; règle en double acceptée ; copilote qui ne refuse plus ou cite la valeur ; score qui note une donnée bloquée ; tuile et bannière sans l'échec ; mémoire sans l'anomalie ou qui la double ; M10 qui refuse le nouveau type ; qualité appliquée hors du moteur ; collecte qui ne nomme plus l'échec |
| C3, alertes (28) | frontière stricte ; sens inversé ; seuil absent valant zéro ; valeur périmée qui alerte ; déduplication retirée ; règle non évaluée qui résout ; report sans échéance ou à échéance incluse ; double accusé écrit ; report dans le passé ; alerte rangée au MAUVAIS DÉPARTEMENT ; destinataire de l'événement altéré ; action d'un autre gabarit ; types d'alerte permutés ; clé `cause` dans la vue (garde AST) ; borne d'inondation retirée ; « À voir » qui inclut les accusées ou inverse les niveaux ; rechute qui réutilise le rang 1 ; accusé qui ne lève pas le report et inversement ; tour planifié qui n'évalue pas ; ouverture sans événement ; seuil textuel accepté ; péremption évaluée sur une mesure non calculable |

**Survivante équivalente** : `C4-24` (la bannière ne compte plus l'échec de qualité dans son niveau) : une tuile bloquée est aussi une tuile
non calculable, et la règle suivante (« non calculable donne au moins attention ») redonne le même niveau ; aucun comportement observable ne change.

## 10. Commandes

```bash
pytest departments/m08-analytics departments/m05-financecore departments/m07-marketing departments/m04-field-ops \
       departments/m02-revenue-crm departments/m06-material-control departments/m01-front-office
pytest tests/test_entrepot_m8_garanties.py tests/test_entrepot_m8_scenarios.py tests/test_entrepot_m8_phase2.py \
       tests/test_interconnexion_m5_depense_publicitaire.py tests/test_taxonomie_canaux_marketing.py tests/test_pont_bi.py \
       tests/test_m8_memoire_m10.py
pytest tests/test_entrepot_m8_planifie.py tests/test_constats_planifies.py \
       departments/m08-analytics/tests/test_cadence_constats.py tests/test_planification_*.py
python scripts/docs/interconnexion_evenements.py --verifier
opsys-metier registre-mcp verifier
```
