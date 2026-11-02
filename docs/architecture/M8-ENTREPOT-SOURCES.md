# Entrepôt de M8 : d'où vient chaque mesure, et ce qui n'y arrive pas encore

Statut (2026-11-01, constats planifiés) : les sept constats de la phase 2 sont **déclenchés par le planificateur durable** (déclarés par
les manifestes, [PLANIFICATION §9](PLANIFICATION.md)) ; inactifs par défaut, prouvés sur SQLite avec horloge injectée, jamais sur PostgreSQL.
Statut (2026-11-01) : **phase 1** = cartographie par lecture du code, puis branchement de tout ce qui se branche sans nouveau droit
d'appareil, sans nouvel outil, sans migration et sans écriture dans un autre département (38 mesures). **Phase 2** = exécution des
décisions D1 à D7 de l'architecte (r10, §5) : sept départements PUBLIENT un résumé agrégé et minimisé sur le bus et M8 le consomme
(56 mesures) ; **sept outils de constat** (T1/N2, agent seulement, **aucun droit d'appareil**), **aucune migration**, aucune lecture
croisée. Prouvé sur le **vrai bus**, les `consommateurs()` réels et une base SQLite migrée, avec des charges conformes au catalogue
d'événements. Rien n'a été exécuté contre PostgreSQL pour ces mesures, ni contre un service externe. Contexte : `INTERCONNEXION.md` (le
bus), `M8-OLIVIER.md` (la couche analytique).

## 1. Pourquoi ce chantier

M8 est la vue exécutive de toute l'entreprise. L'audit d'interconnexion disait honnêtement que les constats de M7, M5 et M3
n'alimentaient pas l'entrepôt : ils arrivaient bien chez M8 (registre `faits_operations`) mais ne servaient qu'à la section
`operations_recues` de la vue exécutive. Le catalogue fermé n'avait que 18 mesures, aucune ne venait de la marge, des créances, des
comptes à payer, des relevés publicitaires, des réceptions de matériaux ni des demandes de M1.

Il en a maintenant **56** (18 + 20 + 18 de la phase 2), lues par le **même moteur** (`moteur_mesures.lire`) que les wallboards, le score de santé, le
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

## 3. Matrice : les 56 mesures

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

### 3.3 Les 18 mesures de la phase 2 (D1 à D3, D5, D6)

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
`test_plaintes_structurees.py`). Les sept outils sont aussi à l'audit d'interconnexion (producteur et consommateur réels, 56 types).

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
  le planificateur et suit leurs événements jusqu'au wallboard de la console, au copilote, à M10 et à M9 (SQLite seulement).
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
