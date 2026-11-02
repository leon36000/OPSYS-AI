# Interconnexion des départements par le bus d'événements

Statut (2026-11-01) : consommateurs réels écrits et prouvés **sur le vrai bus** (`evenements.repartir`, `consommateurs()` réels,
base SQLite migrée) ; **aucune** preuve contre un service externe réel ni contre PostgreSQL (voir « Limites »). Code d'audit :
`src/opsys/evenements/interconnexion.py`, script `scripts/docs/interconnexion_evenements.py`. Tests : `tests/test_interconnexion_*.py`.

## 1. Principe

Les dix départements sont **autonomes** (chacun écrit seulement dans ses registres) **et interconnectés** (ils se parlent par des
événements du catalogue `src/opsys/evenements/catalogue/*.json` et, pour quelques lectures nommées, par des ports). Un événement
« producteur seulement » n'a de valeur que s'il a un consommateur ; l'audit refuse donc, par un test, qu'un type du catalogue soit
sans consommateur RÉEL **et** sans justification écrite.

Ce que l'audit croise, sans croire une seule source : le **catalogue** (les types qui existent), les `evenements.publie` /
`evenements.consomme` des `department.yaml` (ce qui est déclaré) et les **`consommateurs()` réels** de chaque module (ce que
`repartir` appellera). Quatre familles d'écarts : type sans consommateur (et sans fiche), consommateur déclaré sans handler,
handler sans déclaration (code mort), type consommé que personne ne publie ; plus la lecture croisée non déclarée (section 5).

Contrat commun de chaque consommateur ajouté (prouvé par `tests/test_interconnexion_consommateurs.py`, 21 consommateurs x 5 garanties) :

1. **Charge validée** par le schéma du catalogue à la publication ; une charge hors schéma n'est jamais écrite.
2. **Idempotent par clé de CONTENU**, pas par `evenement_id` : le même constat rejoué sous un autre identifiant n'ajoute aucun
   maillon et ne met rien en quarantaine. **La même clé avec un contenu DIFFÉRENT est une contradiction** (M2, M5, M8, voir §2 bis) :
   le premier état reste, la contradiction est rangée et dite ; le rejeu identique reste silencieux.
3. **Tolérant à la panne du destinataire** : l'écriture échoue -> le reçu du bus passe à `echec` avec recul (jamais perdu, jamais
   en quarantaine à la première panne) ; la relivraison écrit UNE fois. Un refus déterministe (période close, lead inconnu...)
   est rangé avec son code, pas retenté.
4. **Propriété des données** : un consommateur n'écrit que dans le registre de SON département (mesuré, pas supposé : le monde
   de test observe chaque écriture de registre faite pendant un handler).
5. **Aucune action N3+** : un consommateur prépare, range, avertit ; il n'envoie, ne publie, ne paie et ne valide rien.
6. **Minimisation** : seuls des identifiants, des comptes, des montants arrêtés par le propriétaire de la donnée ; le reçu du bus
   ne garde aucun champ personnel. Le journal est le registre du destinataire (append-only) plus le reçu du bus.

<!-- interconnexion:debut -->

60 types au catalogue : 51 ont au moins un consommateur réel, 9 n'en ont pas (chacun avec sa justification datée).

| Type | Producteur | Consommateurs réels | Sans consommateur : justification |
|---|---|---|---|
| `m1.approbation_envoi_demandee` | M1 | — | Notification du sas d'approbation : la demande d'envoi (N3) est lue par la direction dans la file d'approbation du socle (approbations.file_proprie... (revue 2026-11-01) |
| `m1.brouillon_courriel_pret` | M1 | — | Notification interne du fil de réponse de M1 (brouillon préparé, rien d'envoyé) : l'état du brouillon se lit dans le sas d'envoi (courriel_connecte... (revue 2026-11-01) |
| `m1.commande_courriel_envoyee` | M1 | M6, M8 |  |
| `m1.courriel_aiguille` | M1 | M5, M6 |  |
| `m1.courriel_envoye` | M1 | M1 |  |
| `m1.courriel_recu` | M1 | M1 |  |
| `m1.envoi_courriel_echoue` | M1 | — | Alerte pour un humain (refus de garde, échec définitif, issue INCERTAINE : vérifier la boîte Envoyés, jamais de reprise automatique). Elle est lue... (revue 2026-11-01) |
| `m1.lead_qualifie` | M1 | M2, M8, M10 |  |
| `m1.plaintes_constatees` | M1 | M8 |  |
| `m1.retrait_consentement` | M1 | M2, M7 |  |
| `m10.arete_en_attente` | M10 | — | File « à confirmer » de la direction (N3, Loi 25) : l'arête personnelle en brouillon ne répond à aucune requête avant la confirmation d'une personn... (revue 2026-11-01) |
| `m10.lecon_decidee` | M10 | — | Une leçon promue est lisible par le département visé par tirage (opsys_lecons_actives) et ne s'applique jamais seule. La mesure d'amélioration par... (revue 2026-11-01) |
| `m10.soi_revision_proposee` | M10 | — | Révision du modèle de soi en attente de la décision d'une personne (N3) : lue par la console de la direction. M9 (revue) la relira par le registre... (revue 2026-11-01) |
| `m2.client_associe` | M2 | M3, M4, M5, M7, M8, M10 |  |
| `m2.contact_corrige` | M2 | M10 |  |
| `m2.filet_anti_perte_constate` | M2 | M8 |  |
| `m2.lead_assigne` | M2 | M8 |  |
| `m2.pipeline_constate` | M2 | M8 |  |
| `m2.profil_propriete_confirme` | M2 | M3, M4, M10 |  |
| `m3.besoins_materiaux` | M3 | M6 |  |
| `m3.catalogue_reference` | M3 | M10 |  |
| `m3.contexte_site_pret` | M3 | M2 |  |
| `m3.devis_accepte` | M3 | M2, M4, M5, M6, M7, M8, M10 |  |
| `m3.devis_envoye` | M3 | M2, M8, M10 |  |
| `m3.devis_sans_reponse` | M3 | M2, M8, M10 |  |
| `m3.mesure_vision_validee` | M3 | M8 |  |
| `m4.capacite_equipe_constatee` | M4 | M8 |  |
| `m4.consentement_suivi_retire` | M4 | M1 |  |
| `m4.message_client_brouillon_pret` | M4 | M1 |  |
| `m4.travaux_termines` | M4 | M2, M3, M5, M6, M7, M8, M10 |  |
| `m5.cash_libre_constate` | M5 | M8 |  |
| `m5.creance_relance_preparee` | M5 | M2 |  |
| `m5.depense_publicitaire_constatee` | M5 | M8 |  |
| `m5.dossier_cpa_scelle` | M5 | M10 |  |
| `m5.facture_emise_constatee` | M5 | M2, M8 |  |
| `m5.mesures_comptables_constatees` | M5 | M8 |  |
| `m5.preaudit_constate` | M5 | M8 |  |
| `m5.rapprochement_po_constate` | M5 | M6 |  |
| `m5.rentabilite_chantier` | M5 | M7, M8, M10 |  |
| `m6.catalogue_reference` | M6 | M10 |  |
| `m6.disponibilite_constatee` | M6 | M8 |  |
| `m6.materiel_pret` | M6 | M4 |  |
| `m6.note_commande_referencee` | M6 | M10 |  |
| `m6.po_courriel_pret` | M6 | M1 |  |
| `m6.reception_enregistree` | M6 | M5, M8 |  |
| `m6.variance_chantier` | M6 | M3, M4, M5, M8, M10 |  |
| `m7.anomalie_depense_detectee` | M7 | M8, M9 |  |
| `m7.apprentissage_marketing_constate` | M7 | M10 |  |
| `m7.contenu_exporte` | M7 | M8 |  |
| `m7.conversion_hors_ligne_importee` | M7 | M2, M8 |  |
| `m7.depenses_marketing_constatees` | M7 | M5, M8 |  |
| `m7.performance_signaux_constatee` | M7 | M8 |  |
| `m7.publication_echouee` | M7 | — | Alerte du planificateur (refus typé, approbation expirée, issue incertaine) pour un humain : relue dans l'état du planificateur et le sas d'approba... (revue 2026-11-01) |
| `m7.publication_faite` | M7 | — | Constat du planificateur après une publication approuvée (WordPress ou réseau social) : l'état de la publication se lit dans le registre de M7 et l... (revue 2026-11-01) |
| `m7.signaux_marketing_constates` | M7 | M8 |  |
| `m8.alerte_proposee` | M8 | M9 |  |
| `m8.fait_consolide` | M8 | M9, M10 |  |
| `m8.snapshot_chantier` | M8 | M9 |  |
| `m9.fait_strategique` | M9 | M10 |  |
| `opsys.demo_complete` | — | — | Type fictif réservé aux tests du bus (tests/test_evenements.py) et aux départements de démonstration ; il ne décrit aucun flux métier. (revue 2026-11-01) |

### Lectures croisées déclarées (hors événements)

| Lecteur | Source | Voie | Outils ou registres lus |
|---|---|---|---|
| M9 | M1 | `port:lecteur_producteurs_m9` | `m1_lire_plaintes_structurees`, `m1_produire_digest` |
| M9 | M2 | `port:lecteur_producteurs_m9` | `m2_analyser_pipeline`, `m2_lister_leads`, `m2_lister_relances`, `m2_prevoir_pipeline`, `m2_rejouer_recu_commercial`, `m2_scanner_sla` |
| M9 | M3 | `port:lecteur_producteurs_m9` | `m3_lire_ecarts_estime_reel` |
| M9 | M4 | `port:lecteur_producteurs_m9` | `m4_lire_capacite_equipe`, `m4_lire_cedule_semaine`, `m4_lire_meteo_intervention`, `m4_lire_retards_incidents`, `m4_lister_interventions`, `m4_projeter_capacite_hypotheses`, `m4_verifier_recu_projection_capacite` |
| M9 | M5 | `port:lecteur_producteurs_m9` | `m5_comparer_credit_bail_achat`, `m5_lire_calendrier_obligations`, `m5_lire_comptes_a_recevoir`, `m5_lire_rentabilite_chantier`, `m5_lire_statut_revue_fiscale`, `m5_lister_comptes_a_payer`, `m5_prevoir_tresorerie`, `m5_simuler_tresorerie_monte_carlo`, `m5_verifier_recu_calcul` |
| M9 | M6 | `port:lecteur_producteurs_m9` | `m6_lire_disponibilite` |
| M9 | M7 | `port:lecteur_producteurs_m9` | `m7_lire_depenses_marketing`, `m7_lire_performance_campagnes` |
| M9 | M8 | `port:lecteur_producteurs_m9` | `m8_lire_mesures_chantier`, `m8_lire_synthese_direction`, `m8_lire_vue_executive`, `m8_lister_definitions_metriques` |
| M9 | M10 | `port:lecteur_producteurs_m9` | `m10_lire_faits_analytiques`, `m10_paquet_contexte_affaire`, `m10_statut_decision` |
| M1 | M4 | `port:lecteur_capacite_m4` | `m4_lire_capacite_equipe`, `m4_lire_cedule_semaine` |
| M5 | M4 | `port:lecteur_heures_m4` | `m4_lire_heures_regulieres_validees` |
| M5 | M7 | `port:lecteur_campagne_m7` | `m7_lire_campagne_locale` |
| M2 | M10 | `registre` | `evenements` |
| M3 | M2 | `registre` | `principal` |
| M3 | M6 | `registre` | `livre_prix`, `fournisseurs` |
| M5 | M6 | `registre` | `livre_prix` |
| M4 | M6 | `registre` | `contrats_variance_m6.REGISTRE`, `contrats_variance_m6.REGISTRE_REFUS` |
| M6 | M4 | `registre` | `principal` |
| M3 | M4 | `port:capacites_m3_vers_m4` | `m4_lire_faits_calibration_m3`, `m4_lire_equipes_faits_m3` |
| M4 | M3 | `port:capacites_m4_vers_m3` | `m3_lire_performance_equipes` |

Lectures sans entrée dans `dependances` (volontairement non élargi) : m01-front-office lit m04-field-ops; m02-revenue-crm lit m10-memoire; m05-financecore lit m07-marketing; m09-strategic-intelligence lit m01-front-office; m09-strategic-intelligence lit m02-revenue-crm; m09-strategic-intelligence lit m03-estimation; m09-strategic-intelligence lit m04-field-ops; m09-strategic-intelligence lit m05-financecore; m09-strategic-intelligence lit m06-material-control; m09-strategic-intelligence lit m07-marketing.

<!-- interconnexion:fin -->

La justification de chaque ligne « sans consommateur » (raison + date de revue) est dans
`docs/architecture/evenements-sans-consommateur.json` ; `a_revoir_avant` échu = avertissement de `--audit`, jamais un échec (le
test n'a pas d'horloge).

## 2. Consommateurs ajoutés par ce chantier

| Destinataire | Événement | Ce que le consommateur fait (et ne fait pas) | Registre du destinataire |
|---|---|---|---|
| M8 | `m7.signaux_marketing_constates`, `m7.depenses_marketing_constatees`, `m7.anomalie_depense_detectee`, `m7.conversion_hors_ligne_importee`, `m5.mesures_comptables_constatees`, `m3.mesure_vision_validee`, `m6.reception_enregistree`, `m1.commande_courriel_envoyee` | Range le constat tel quel, avec sa **provenance** (type d'événement, identifiant, empreinte de la charge) ; la vue exécutive gagne la section `operations_recues` (une seule somme : les relevés de dépense reçus, par canal, dernière révision, bases de taxes non mélangées, jamais « dépense totale »). Réduite par paliers dits (`omis`) puis à son compte si la borne du socle l'exige : elle ne fait jamais échouer la vue de base. Fictifs exclus et comptés. Vision sans photo ni modèle. **Depuis le chantier « entrepôt interdépartements »**, ces constats (et ceux de M5 déjà reçus : rentabilité, cash libre) alimentent aussi **20 mesures du catalogue fermé** lues par le moteur de l'entrepôt, des wallboards, du copilote, de la mémoire et du pont BI : voir [`M8-ENTREPOT-SOURCES.md`](M8-ENTREPOT-SOURCES.md). Réception de M6 : bon de commande, mouvement, verdict, instant (ni fournisseur ni ligne de prix). Commande de M1 : bon de commande et instant. | `faits_operations` |
| M5 | `m7.depenses_marketing_constatees` | **Brouillon** d'écriture (compte « marketing » du plan, contrepartie Comptes fournisseurs), pièce déclarée jamais vérifiée. `TAXES_INCLUSES` : aucune ventilation (décision fiscale), rangé « à compléter » ; révision > 1 : jamais un second brouillon (rangé « à revoir ») ; montant nul, période close, horodatage sans fuseau : refus rangés. Rien n'est validé (N4 humain). À valider auprès d'un comptable (CPA) / professionnel qualifié. | `charges_marketing_recues` + `grand_livre` (brouillon) |
| M2 | `m7.conversion_hors_ligne_importee` | Lecture seule : le score voit « source connue » pour CE lead si M7 a une source normalisée ; le contrat du lead n'est jamais réécrit. | `conversions_hors_ligne_recues` |
| M2 | `m5.creance_relance_preparee` | Avertissement de coordination sur les relances commerciales du même client et phrase du coach ; rien n'est supprimé, retardé ni envoyé ; aucun montant au coach. Levée par le paiement ou l'annulation de la facture (ligne suivante). | `creances_relances_recues` |
| M2 | `m3.contexte_site_pret` | Comptes du contexte de site (connus, inconnus, à vérifier, en conflit) dits au coach, dernière version. | `contextes_site_recus` |
| M3 | `m2.client_associe`, `m2.profil_propriete_confirme` | `m3_construire_contexte_site` reprend le profil CONFIRMÉ (étages, année) quand l'appelant n'en fournit pas ; plusieurs propriétés = « ambigu », rien deviné ; le profil de l'appelant l'emporte ; faits hors bornes écartés. | `liens_lead_client`, `profils_propriete_recus` |
| M4 | `m2.client_associe`, `m2.profil_propriete_confirme` | Bloc `contexte_propriete` de `m4_verifier_preparation`, HORS verdict (l'empreinte de préparation n'en dépend pas, aucun nouveau volet). | `liens_lead_client`, `profils_propriete_recus` |
| M1 | `m4.message_client_brouillon_pret` | **Brouillon** dans le sas d'envoi (courriel), vers l'adresse du lead chez M1, texte de M4 tel quel ; l'envoi reste une demande N3 d'une personne. SMS : « à reprendre » (l'assistant SMS ne prend que ses gabarits). Retrait de consentement depuis, lead inconnu, adresse absente, échéance : refus rangés. Aucun compte d'envoi connecté : échec avec recul, puis quarantaine visible (même patron que la commande de M6). | `messages_clients_m4` |
| M1 | `m4.consentement_suivi_retire` | **Retrait du consentement de suivi** (Loi 25 : le retrait vaut tout de suite pour ce que M1 n'a pas envoyé). Range le retrait (`retrait_suivi_m4`, append-only), refuse tout message qu'il vise (brouillon livré APRÈS le retrait : ligne `suivi_retire`, aucun brouillon créé), marque `suivi_retire` les messages déjà rangés qui ne sont pas partis, fait retomber en `BROUILLON` un brouillon qui attendait une demande ou une approbation (approbation caduque : `modifier_brouillon` sans changer le texte), refuse `m1_demander_envoi_courriel` pour un message retiré (`REJ-M1-MESSAGE-SUIVI-RETIRE`), dit `suivi_retire` dans `m1_lire_reponse_courriel` et publie dans la file de la direction une attente `suivi_retire_a_refuser` pour une demande N3 déjà ouverte. Un message visé = même maillon de consentement que le retrait (`consentement_ligne_id`), OU publié avant ou à l'instant de publication du retrait, OU un instant manque (fail-closed) ; un brouillon publié APRÈS un retrait suppose un nouveau consentement et n'est pas visé. Aucun contact : le `lead_id` pseudonyme. Un message déjà réservé, envoyé ou d'issue incertaine ne se rappelle pas : la ligne dit `neutralise: false` et l'état d'envoi. | `messages_clients_m4` |
| M2 | `m5.facture_emise_constatee` | Une facture **PAYÉE ou ANNULÉE lève la relance de créance** de cette facture (calculé à la lecture : ni l'ordre de livraison ni un rejeu ne la rouvrent). `ENVOYEE` ne range rien. M2 ne garde que l'identifiant de facture et le statut. Un paiement partiel n'est jamais `PAYEE` chez M5 : la relance reste. Réutilise le type de la phase 2 (M8 le consomme toujours) au lieu d'en créer un. Les factures de JALON (M5-FACT-1, [M5-FACTURATION](M5-FACTURATION.md)) suivent la même règle, sans nouvel événement : chaque jalon émis est un constat, et la relance de M2 porte l'`echeance` PROPRE de la facture (celle de son jalon), le statut « en retard » restant une vue calculée de M5 qui ne lève rien. | `factures_closes_recues` |
| M6 | `m5.rapprochement_po_constate` | Attente « À voir » de l'admin quand le dernier état d'une facture est `ECART` ou `INCOMPLET` ; M6 ne modifie jamais la facture ; aucun montant dans l'attente. | `rapprochements_facture_recus` |
| M9 | `m7.anomalie_depense_detectee`, `m8.fait_consolide` | Section `signaux_de_gestion` du briefing du matin : anomalies de la fenêtre (les plus graves d'abord, au plus 5) et RÉSUMÉ de la dernière consolidation de M8 (comptes et identifiants, aucune valeur). Le briefing reste sous la limite du socle. M9 lit, ne décide pas. | `signaux_gestion_recus` |
| M10 | `m5.dossier_cpa_scelle` | Mémoire (FINANCIAL, hors de tout paquet de contexte) qu'un dossier de période a été scellé ; même `dossier_id` sous un autre sceau = refus nommé (quarantaine visible), le premier sceau reste. M10 ne rouvre ni ne juge le dossier. | `dossiers_cpa_scelles` |
| M10 | `m7.apprentissage_marketing_constate` | **Mémoire marketing** (M7-MEMOIRE) : range chaque observation minimale annoncée par M7 après son rapport hebdomadaire (contenu gagnant ou faible, signal d'objection tiré des catégories d'avis, avis de la semaine) : liste blanche stricte, un maillon par `observation_id`, même identifiant avec un autre contenu = contradiction nommée (la première reste), charge hors forme = refus nommé (le CHAMP, jamais la valeur). Aucun texte de contenu ni d'avis, aucune coordonnée, aucun identifiant de lead ou de chantier. Ce n'est pas une leçon : `m10_extraire_lecons` en tire des leçons GOUVERNÉES de genre `apprentissage_marketing` après trois semaines distinctes ; la décision est humaine ([M7-MARQUE-RAPPORT](M7-MARQUE-RAPPORT.md) §4). | `faits_marketing` |

Aucun outil, aucun rôle d'appareil, aucune politique d'approbation, aucune migration n'est ajouté : le compteur d'outils, la portée
des appareils et le registre MCP ne changent pas.

### 2 bis. Constat rejoué avec la même clé mais un contenu différent (M2, M5, M8)

Avant : ignoré sans alerte (seul M10 nommait la contradiction de sceau, par un refus nommé puis la quarantaine). Règle commune
(`src/opsys/evenements/constats.py`, module pur) : le **premier état est gardé**, rien n'est écrasé ; la contradiction est rangée
au registre `constats_contradictoires` du destinataire (append-only : le type du constat, sa clé, les **noms** des champs qui
diffèrent, jamais leur valeur, deux empreintes et l'instant de publication donné par le bus), une seule fois par contenu
contradictoire ; le consommateur répond `contradiction: CONSTAT_CONTRADICTOIRE` au bus (le reçu passe à `traite`, **sans reprise** : c'est un
refus déterministe, pas une panne) ; le **rejeu identique reste silencieux**.

| Département | Constats couverts | Clé | Où la contradiction est dite |
|---|---|---|---|
| M2 | `m5.creance_relance_preparee` (`relance_id`), `m7.conversion_hors_ligne_importee` (`conversion_id`), `m3.contexte_site_pret` (`lead_id` + `version`) | clé de contenu du fait | `constats_contradictoires` + `m2_lister_relances` (`constats_contradictoires`, `avertissement_constats`, seulement s'il y en a) |
| M5 | `m7.depenses_marketing_constatees` (`releve_id` + `revision`) | la ligne du journal garde l'empreinte du contenu reçu (jamais le montant en clair) | `constats_contradictoires` (champs : non listés, seule l'empreinte est gardée) + `m5_executer_cycle_comptable` (`en_attente_d_une_personne.constats_contradictoires_m7_a_examiner`, seulement s'il y en a) |
| M8 | les 15 constats de `faits_operations` (clé propre à chacun) | contenu du fait sans provenance ni instant de publication | `constats_contradictoires` + `m8_lire_vue_executive` (`constats_contradictoires`, seulement s'il y en a) |

Différence assumée avec M10 : M10 lève (réessais puis quarantaine visible dans le bus) ; ici la contradiction est un constat
rangé, visible dans l'état de lecture du département, sans boucle de reprise. M10 est inchangé. Preuve :
`tests/test_constats_contradictoires.py`.

## 3. Scénarios de bout en bout (`tests/test_interconnexion_scenarios.py`)

Vrai bus, consommateurs réels, outils réels en aval. Les maillons amont qui exigeraient un service externe ou un long montage
(connecteur publicitaire de M7, réception de M6) sont publiés avec la charge du catalogue ; tout le reste est exécuté par les
vrais outils.

| # | Parcours | Départements |
|---|---|---|
| S1 | signaux, dépenses et anomalie de M7 -> entrepôt de M8 -> `m8_publier_faits_consolides` -> briefing de M9 et mémoire de M10 ; M7 -> brouillon de charge de M5 | M7, M8, M9, M10, M5 |
| S2 | réception de M6 -> à payer de M5 -> facture fournisseur saisie -> rapprochement (ECART) -> attente « À voir » de M6 ; mesures comptables de M5 -> vue de M8 | M6, M5, M8 |
| S3 | courriel entrant de M1 -> lead et client de M2 -> profil de propriété proposé d'après le courriel et confirmé par une personne -> M3, M4, M10 -> contexte de site de M3 (profil repris) -> M2 (coach) -> `m3_estimer_projet` avec le contexte | M1, M2, M3, M4, M10 |
| S4 | M1 -> client de M2 ; facture en retard de M5 -> relance préparée (rien envoyé) -> avertissement du coach de M2 ; mesures de M5 -> M8 | M1, M2, M5, M8 |
| S5 | conversion hors ligne de M7 -> score de M2 (en lecture, contrat intact) et vue de M8 | M7, M2, M8 |
| S6 | panne de M8 en pleine chaîne : M5 et M9 livrent quand même, M8 reprend une seule fois, puis consolidation -> M9, M10 | M7, M8, M5, M9, M10 |
| S7 | dossier CPA scellé et rapprochement de M5 -> M10, M8, M6, sans donnée de client | M5, M10, M8, M6 |
| S1b | tout le flux S1 rejoué sous d'autres identifiants : aucun maillon de plus, aucune quarantaine | M7, M8, M5, M9 |
| S9 | M4 (outils réels : consentement N3, message d'arrivée, retrait) -> brouillon dans le sas de M1 -> demande N3 ouverte -> retrait -> brouillon neutralisé, attente « à refuser », M4 refuse tout nouveau message ; ordre inversé (brouillon livré après le retrait) ; nouveau consentement après le retrait servi puis second retrait ; un canal ne touche pas l'autre (`tests/test_consentement_suivi_retire_scenario.py`) | M4, M1 |
| S10 | M5 (facture envoyée, relance préparée, paiement, cycle comptable) -> M2 (relance levée) et M8 (même constat qu'avant) ; paiement partiel : la relance reste ; deux factures du même client ; A -> B -> A (`tests/test_creance_levee_paiement.py`) | M5, M2, M8 |

Charge (`tests/test_interconnexion_charge.py`) : 1 000 événements de cinq types, 1 800 livraisons réelles ; comptes exacts des
registres (ni perte ni doublon), tous les reçus `traite`, aucune quarantaine ; rejeu complet sous d'autres identifiants sans
aucun maillon de plus ; panne de M8 au milieu du lot puis reprise. Durée mesurée de l'ordre de 10 s sur SQLite.

## 4. Mutations (preuve que les tests tuent)

Dix-neuf mutations appliquées une à une au code livré, chacune TUÉE par au moins un test (aucune ne survit) : consommateur
non idempotent (M8), taxes incluses ventilées et doublon sur révision (M5), journal rejoué sans clé de contenu (M5), écriture dans
le registre d'un autre département (M6 -> M5), déclaration sans handler (M9) et handler sans déclaration (M2), rejeu du même sceau
refusé donc quarantaine (M10), propriété ambiguë devinée (M3), profil repris sans lien lead -> client (M3), retrait de
consentement ignoré (M1), source non normalisée comptée (M2), vue de M8 sans réduction de borne, attente M6 aussi pour un état
concordant, dossier CPA non FINANCIAL, pièce du brouillon M5 faussement « vérifiée », anomalie fictive admise (M9), audit qui
compte un déclaré comme réel, audit qui ne voit plus une lecture directe.

Entrepôt de M8 (chantier « entrepôt interdépartements ») : cinquante-trois mutations de plus, sur les mesures, la couverture, la fenêtre de
M7, les clés de contenu et le copilote, quatre d'abord survivantes puis fermées par un test chacune (détail : [`M8-ENTREPOT-SOURCES.md`](M8-ENTREPOT-SOURCES.md) §9).
Les cinq garanties ci-dessus sont rejouées pour les treize sources qui nourrissent l'entrepôt (`tests/test_entrepot_m8_garanties.py`).

### 4 bis. Chantier « consentement et paiement » : rouge avant, mutations

**Rouge avant** (clone `git archive` de `234bebe08`, mêmes tests) : une sonde de comportement écrite avec les seules API de la base
(6 tests sur 6 en échec : aucun événement de retrait au catalogue, relance jamais levée, aucune contradiction dite par M2, M5
ni M8) ; les nouveaux fichiers de test posés sur la base : 60 échecs et 1 erreur de collecte (`test_constats_contradictoires.py`).
Après : tous au vert.

**Trente-sept mutations** appliquées une à une (restauration vérifiée par `git diff` identique avant et après), **toutes tuées** (deux
d'abord survivantes ou inapplicables, fermées par un test ou une correction de la mutation) :
- retrait de consentement (19) : règle « même maillon » retirée ; instant égal non visé ; comparaison inversée ; instant manquant
  non visé ; brouillon livré après le retrait non refusé ; approbation en attente non rendue caduque ; message déjà envoyé dit
  neutralisé ; retrait rejoué rangé deux fois ; retrait qui vise les autres canaux ; qui vise les autres chantiers ; SMS non retiré ;
  demande d'envoi acceptée pour un suivi retiré ; attente non vidée après décision ; dernier état lu comme le premier ; instant de
  publication non gardé (d'abord SURVIVANTE : fermée par `test_un_retrait_plus_ancien_livre_apres_un_brouillon_plus_recent_ne_le_vise_pas`) ;
  échec du sas avalé ; M4 ne publie plus ; consentement expiré non visé ; identifiant d'événement sans le maillon visé ;
- créance levée (5) : levée retirée ; ANNULEE ignorée ; ENVOYEE rangée comme close ; lecture qui ignore les factures closes ;
  levée limitée à la relance la plus récente ;
- contradictions (13) : champ jamais différent ; rejeu identique signalé ; même contradiction rangée à chaque rejeu ; premier état
  écrasé (d'abord NON APPLICABLE après un renommage, mutation corrigée puis tuée) ; contradiction non rangée ; état de lecture
  muet (M2, M5, M8) ; empreinte non comparée ; montant hors de l'empreinte ; empreinte non gardée ; provenance comptée comme du
  contenu ; détection M8 coupée.

Les cinq garanties (livré, idempotent, panne et reprise, charge hors catalogue refusée, rien de personnel) sont rejouées pour les deux
consommateurs nouveaux (`m1-suivi-retire`, `m2-facture-close`) dans `tests/test_interconnexion_consommateurs.py`.

## 5. Lectures croisées (hors événements)

`dependances` du manifeste ne gouverne que la lecture des **bases de connaissances** (`connaissances.service.bases_lisibles`) ; les
lectures de données d'un département par un autre passent par des **ports à liste blanche** ou par une copie SQL en lecture
déclarée. `docs/architecture/lectures-croisees.json` les déclare toutes (voie, outils ou registres lus, raison) ; l'audit vérifie
que chaque outil d'un port existe et est T0/N0, qu'aucune lecture directe d'un registre étranger (`maillons("autre", ...)`,
`REGISTRES.c.departement == "autre"`, `_copies(cnx, "autre", ...)`, constante `dept = "autre"`) ni aucun `import` du code d'un autre
département n'existe sans être déclaré, et qu'une lecture déclarée n'a pas disparu du code.

**Écarts constatés et laissés tels quels, volontairement** : plusieurs lecteurs lisent une source absente de leur `dependances`
(M1 lit M4, M2 lit M10, M5 lit M7, M9 lit M1 à M7 par son port). Ajouter ces départements à `dependances` ouvrirait aussi leur base
de connaissances au lecteur : ce serait élargir un droit, ce que le brief interdit. Aucun droit d'appareil n'est touché.

## 6. Ce qui reste non raccordé (et pourquoi)

- **`m1.approbation_envoi_demandee`, `m1.brouillon_courriel_pret`, `m1.envoi_courriel_echoue`, `m7.publication_faite`,
  `m7.publication_echouee`** : notifications pour un humain (sas, console, planificateur) ; un consommateur serait un couplage
  gratuit. Fiches datées dans `evenements-sans-consommateur.json`.
- **`m10.arete_en_attente`, `m10.soi_revision_proposee`** : file « à confirmer » de la direction (N3, Loi 25). **`m10.lecon_decidee`** :
  attend une métrique gouvernée d'amélioration chez M8 qui n'existe pas.
- **`m3.contexte_site_pret` vers M10** : non mémorisé. Le journal de site chaîné de M3 est la mémoire de ce contexte ; M10 n'a pas
  de clé de propriété pour le rattacher sans lier un lead à une personne (graphe personnel, Loi 25).
- **Relance de créance vers M1** : `m5.creance_relance_preparee` ne porte qu'un `client_id` ; M1 n'a pas de lien client -> contact
  (le `client_id` est dérivé du contact par M2, et la séparation interdit à M1 de copier l'algorithme). Seul M2 la consomme ; la
  suite (texte, canal, envoi N3) reste un geste de la direction.
- **M8 : entrepôt dérivé et score de santé** : ~~les constats de M7/M5/M3 sont dans la vue exécutive, pas dans l'entrepôt~~ **levé** : ils
  alimentent 20 mesures gouvernées du catalogue fermé (sans migration : les lignes de `m8_ent_mesures_*` changent de contenu, pas de
  forme). Ce qui reste hors de l'entrepôt, mesure par mesure et décision par décision : [`M8-ENTREPOT-SOURCES.md`](M8-ENTREPOT-SOURCES.md) §4 et §5.
  Le **score de santé** n'est pas modifié (pondérations et bornes : décision du propriétaire).
- **Réglages de direction (CFG-1)** : aucun événement, volontairement. Les départements (M2, M8) relisent à chaque appel la couche du socle
  `opsys.reglages.lecture` (valeur adoptée > `department.yaml` > absence) ; rien n'est mis en cache, donc rien à invalider ni personne à
  prévenir, et l'audit des lectures croisées n'a rien de nouveau à déclarer (aucun département n'y lit le registre d'un autre).
  [`REGLAGES-DIRECTION.md`](REGLAGES-DIRECTION.md) §6.
- **M10 : aucun outil de lecture dédié** pour `dossiers_cpa_scelles` (aucun nouvel outil, par choix) ; le registre existe et est
  append-only, sa lecture passera par un outil à venir.

## 7. Limites (sans euphémisme)

- Les consommateurs sont prouvés sur **SQLite** avec le bus et les vrais handlers ; **PostgreSQL** n'a pas été exercé pour ces
  consommateurs.
- **Fin de chantier avec réserves (P4-07).** `m4.travaux_termines` d'une fin dont la preuve est incomplète n'est publié QU'APRÈS
  la revue humaine N4 de M4 (même WCT, même `evenement_id` ; les réserves n'y figurent pas) : jusque-là, M6, M5 (aucune facture),
  M2, M7, M8, M10 et M3 ne reçoivent rien. `m3.devis_accepte` porte en plus `duree_origine` (provenance de la durée : barème ou
  calibration appliquée), lue par M4. Prouvé dans `tests/test_m4_duree_multijours_bout_en_bout.py` (SQLite, vrai bus).
- Les maillons amont de M7 (connecteurs publicitaires) et de M6 (réception) sont publiés avec des charges du catalogue : leurs
  producteurs réels ne sont pas relancés ici, ni aucun service externe (Google Ads, Gmail, etc.).
- L'envoi (courriel de M1) est prouvé jusqu'au brouillon du sas et à la demande N3 ; **l'approbation humaine et l'envoi réel**
  n'ont pas été rejoués ici.
- Le brouillon de charge de M5 suppose le plan comptable par défaut (compte 5950, contrepartie 2100) : à valider auprès d'un
  comptable (CPA) / professionnel qualifié ; la ventilation des taxes d'un fournisseur étranger n'est pas faite.
- La somme des relevés de M8 est une somme des relevés **reçus**, pas la dépense publicitaire de l'entreprise. Depuis la mesure
  `m8_releves_depense_pub_cad`, les jours sans relevé **à l'intérieur de la période couverte** sont comptés et dits (couverture
  partielle) ; ceux avant le premier relevé, après le dernier ou d'un canal jamais relevé restent invisibles. L'écart avec la dépense
  comptabilisée par M5 est une mesure nommée, **non calculable par construction** tant que M5 ne publie pas ce total.
- L'ordre de livraison du bus n'est pas garanti : chaque consommateur choisit son « dernier état » par une clé de contenu
  (révision, date de référence, version), pas par l'ordre d'arrivée. Revue adverse rvi : deux états du MÊME jour (M6, rapprochement
  de facture ; M8, constats comptables) se départagent par l'instant de PUBLICATION que le bus donne au consommateur
  (`repartiteur.instant_publication_livre`), et M5 ne propose jamais de brouillon pour une révision de relevé plus ancienne
  qu'une révision déjà reçue (`REVISION_PERIMEE`) ; M3 et M4 gardent le PREMIER lien lead -> client et refusent un lien contradictoire.
- L'audit ne sait pas démontrer qu'un producteur *publie réellement* son type : il vérifie que le nom complet du type apparaît dans
  son propre code, ou dans un fichier du socle qui appelle `publier(` (un suffixe nu cherché dans tout le socle y trouvait toujours une
  coïncidence). Il écarte le handler qui ne référence aucun nom (`handlers_inertes`) mais ne prouve pas le comportement des autres :
  seuls les tests de chaque consommateur le font. Les lectures directes de registre ne sont vues que par les formes décrites en
  section 5 (littéral, constante de n'importe quel nom du même fichier) ; une constante importée d'un autre fichier n'est pas résolue.
- Le bus ne lie pas le préfixe d'un type (`m5.…`) au producteur qui le publie : seul l'audit statique `publications_hors_espace` voit un
  département qui publie dans l'espace d'un autre, et seulement quand le type est un littéral ou une constante du même fichier.
- **Corrigés par le chantier « consentement et paiement »** (retirés de cette liste) : le retrait du consentement de suivi chez M4
  atteint M1 (`m4.consentement_suivi_retire`) ; une facture payée ou annulée lève la relance de créance de M2
  (`m5.facture_emise_constatee`, réutilisé) ; un constat rejoué avec la même clé mais un contenu différent est dit par M2, M5 et M8.
  **Ce qui reste, sans euphémisme :**
  - *Le retrait vaut à la LIVRAISON de l'événement, pas à l'instant où M4 l'inscrit.* L'effet est « tout de suite » seulement au sens
    du bus : entre le retrait chez M4 et le passage du répartiteur chez M1 (cadence du planificateur, plus le recul d'une panne), une
    demande peut être approuvée et partir. La politique de consentement SMS (§4) dit « appliqué dans les 48 heures » ; le code vise
    plus sévère (même choix que le STOP de M1, ADR-0011) mais cette fenêtre existe et n'est pas mesurée en exploitation.
  - Un message déjà réservé, envoyé ou d'issue incertaine ne se rappelle pas : la ligne dit `neutralise: false` et l'état d'envoi, rien de plus.
  - La demande N3 déjà ouverte reste dans le sas (une ligne du socle ne se réécrit pas) : elle ne peut plus s'exécuter, mais c'est
    l'attente `suivi_retire_a_refuser` de la file de la direction, et non la page de la demande elle-même, qui le dit. Sa lecture
    passe par `approbations.file_proprietaire` ; l'écran réel de l'application n'a pas été rejoué ici.
  - Un brouillon publié APRÈS un retrait n'est pas visé (nouveau consentement supposé). Deux garde-fous le contiennent (même maillon
    de consentement que le retrait ; M4 ne publie rien sans consentement actif), mais la règle repose sur le fait que M4 n'a pas
    publié avec un état périmé : une course entre la lecture du consentement et le retrait, sur PostgreSQL, n'a pas été exercée.
  - Les lignes de M1 écrites avant ce chantier n'ont ni instant de publication ni maillon de consentement : un retrait les vise par
    prudence (jamais l'inverse).
  - *Créance* : la levée ne dépend que de `PAYEE` et `ANNULEE`. Une facture soldée par une note de crédit reste `ENVOYEE` (aucun
    événement) ; aucun outil n'annule encore une facture CLIENT (le statut existe au catalogue, la voie ANNULEE n'est prouvée que par
    la charge que M5 construirait) ; un paiement ANNULÉ après coup (chèque sans provision) n'existe pas chez M5 et ne rouvrirait rien
    chez M2 par construction. La levée attend le cycle comptable de M5 (ou `m5_constater_factures_emises`) : tant qu'il n'a pas
    tourné après le paiement, l'avertissement reste.
  - *Contradictions* : détectées sur le contenu GARDÉ. M8 ne compare que les champs qu'il conserve (une réception de M6 garde six
    champs, pas les lignes) ; M5 ne garde que l'empreinte du contenu et ne peut pas nommer les champs ; une ligne de journal M5 écrite
    avant ce chantier n'a pas d'empreinte et n'est jamais comparée. Les autres consommateurs à clé de contenu (M3, M4, M6, M9 ; les
    autres faits de M8 hors `faits_operations` ; M5 hors relevés de M7) gardent l'ancien comportement (rejeu silencieux). La
    contradiction est RANGÉE et dite dans l'état de lecture, jamais résolue ni signalée à un humain par une attente : personne n'est
    notifié, et le compteur ne se remet pas à zéro tant qu'aucun outil d'acquittement n'existe (aucun outil de plus n'a été ajouté).
  - Prouvé sur SQLite, bus et handlers réels, **puis sur PostgreSQL 17 réel (vague 8)** : rejeux à deux moteurs de ces consommateurs
    et courses déterministes entre deux événements de même clé de contenu (`test_postgresql_bus_course_consommateurs.py`). Le défaut
    trouvé (le même constat rangé deux fois quand deux événements d'identifiants différents se croisent) est fermé par un verrou de
    livraison par consommateur dans le répartiteur (QUALIFICATION-POSTGRESQL §17.2). Aucune garde « SQLite seulement » ajoutée,
    aucune migration.

## 8. Commandes

```bash
python scripts/docs/interconnexion_evenements.py --audit      # écarts bloquants (sortie 1 s'il y en a)
python scripts/docs/interconnexion_evenements.py --ecrire     # régénère le bloc ci-dessus
python scripts/docs/interconnexion_evenements.py --verifier   # échoue si le bloc est périmé
pytest tests/test_interconnexion_*.py
```
