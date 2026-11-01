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

Contrat commun de chaque consommateur ajouté (prouvé par `tests/test_interconnexion_consommateurs.py`, 18 consommateurs x 5 garanties) :

1. **Charge validée** par le schéma du catalogue à la publication ; une charge hors schéma n'est jamais écrite.
2. **Idempotent par clé de CONTENU**, pas par `evenement_id` : le même constat rejoué sous un autre identifiant n'ajoute aucun
   maillon et ne met rien en quarantaine.
3. **Tolérant à la panne du destinataire** : l'écriture échoue -> le reçu du bus passe à `echec` avec recul (jamais perdu, jamais
   en quarantaine à la première panne) ; la relivraison écrit UNE fois. Un refus déterministe (période close, lead inconnu...)
   est rangé avec son code, pas retenté.
4. **Propriété des données** : un consommateur n'écrit que dans le registre de SON département (mesuré, pas supposé : le monde
   de test observe chaque écriture de registre faite pendant un handler).
5. **Aucune action N3+** : un consommateur prépare, range, avertit ; il n'envoie, ne publie, ne paie et ne valide rien.
6. **Minimisation** : seuls des identifiants, des comptes, des montants arrêtés par le propriétaire de la donnée ; le reçu du bus
   ne garde aucun champ personnel. Le journal est le registre du destinataire (append-only) plus le reçu du bus.

<!-- interconnexion:debut -->

49 types au catalogue : 40 ont au moins un consommateur réel, 9 n'en ont pas (chacun avec sa justification datée).

| Type | Producteur | Consommateurs réels | Sans consommateur : justification |
|---|---|---|---|
| `m1.approbation_envoi_demandee` | M1 | — | Notification du sas d'approbation : la demande d'envoi (N3) est lue par la direction dans la file d'approbation du socle (approbations.file_proprie... (revue 2026-11-01) |
| `m1.brouillon_courriel_pret` | M1 | — | Notification interne du fil de réponse de M1 (brouillon préparé, rien d'envoyé) : l'état du brouillon se lit dans le sas d'envoi (courriel_connecte... (revue 2026-11-01) |
| `m1.commande_courriel_envoyee` | M1 | M6 |  |
| `m1.courriel_aiguille` | M1 | M5, M6 |  |
| `m1.courriel_envoye` | M1 | M1 |  |
| `m1.courriel_recu` | M1 | M1 |  |
| `m1.envoi_courriel_echoue` | M1 | — | Alerte pour un humain (refus de garde, échec définitif, issue INCERTAINE : vérifier la boîte Envoyés, jamais de reprise automatique). Elle est lue... (revue 2026-11-01) |
| `m1.lead_qualifie` | M1 | M2, M8, M10 |  |
| `m1.retrait_consentement` | M1 | M2, M7 |  |
| `m10.arete_en_attente` | M10 | — | File « à confirmer » de la direction (N3, Loi 25) : l'arête personnelle en brouillon ne répond à aucune requête avant la confirmation d'une personn... (revue 2026-11-01) |
| `m10.lecon_decidee` | M10 | — | Une leçon promue est lisible par le département visé par tirage (opsys_lecons_actives) et ne s'applique jamais seule. La mesure d'amélioration par... (revue 2026-11-01) |
| `m10.soi_revision_proposee` | M10 | — | Révision du modèle de soi en attente de la décision d'une personne (N3) : lue par la console de la direction. M9 (revue) la relira par le registre... (revue 2026-11-01) |
| `m2.client_associe` | M2 | M3, M4, M5, M7, M8, M10 |  |
| `m2.contact_corrige` | M2 | M10 |  |
| `m2.lead_assigne` | M2 | M8 |  |
| `m2.profil_propriete_confirme` | M2 | M3, M4, M10 |  |
| `m3.besoins_materiaux` | M3 | M6 |  |
| `m3.catalogue_reference` | M3 | M10 |  |
| `m3.contexte_site_pret` | M3 | M2 |  |
| `m3.devis_accepte` | M3 | M2, M4, M5, M6, M7, M8, M10 |  |
| `m3.devis_envoye` | M3 | M2, M8, M10 |  |
| `m3.devis_sans_reponse` | M3 | M2, M8, M10 |  |
| `m3.mesure_vision_validee` | M3 | M8 |  |
| `m4.message_client_brouillon_pret` | M4 | M1 |  |
| `m4.travaux_termines` | M4 | M2, M3, M5, M6, M7, M8, M10 |  |
| `m5.cash_libre_constate` | M5 | M8 |  |
| `m5.creance_relance_preparee` | M5 | M2 |  |
| `m5.dossier_cpa_scelle` | M5 | M10 |  |
| `m5.mesures_comptables_constatees` | M5 | M8 |  |
| `m5.rapprochement_po_constate` | M5 | M6 |  |
| `m5.rentabilite_chantier` | M5 | M7, M8, M10 |  |
| `m6.catalogue_reference` | M6 | M10 |  |
| `m6.materiel_pret` | M6 | M4 |  |
| `m6.note_commande_referencee` | M6 | M10 |  |
| `m6.po_courriel_pret` | M6 | M1 |  |
| `m6.reception_enregistree` | M6 | M5 |  |
| `m6.variance_chantier` | M6 | M3, M4, M5, M8, M10 |  |
| `m7.anomalie_depense_detectee` | M7 | M8, M9 |  |
| `m7.contenu_exporte` | M7 | M8 |  |
| `m7.conversion_hors_ligne_importee` | M7 | M2, M8 |  |
| `m7.depenses_marketing_constatees` | M7 | M5, M8 |  |
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
| M9 | M2 | `port:lecteur_producteurs_m9` | `m2_analyser_pipeline`, `m2_lister_leads`, `m2_lister_relances`, `m2_prevoir_pipeline` |
| M9 | M3 | `port:lecteur_producteurs_m9` | `m3_lire_ecarts_estime_reel` |
| M9 | M4 | `port:lecteur_producteurs_m9` | `m4_lire_capacite_equipe`, `m4_lire_cedule_semaine`, `m4_lire_meteo_intervention`, `m4_lire_retards_incidents`, `m4_lister_interventions` |
| M9 | M5 | `port:lecteur_producteurs_m9` | `m5_lire_calendrier_obligations`, `m5_lire_comptes_a_recevoir`, `m5_lire_rentabilite_chantier`, `m5_lire_statut_revue_fiscale`, `m5_lister_comptes_a_payer`, `m5_prevoir_tresorerie` |
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

Lectures sans entrée dans `dependances` (volontairement non élargi) : m01-front-office lit m04-field-ops; m02-revenue-crm lit m10-memoire; m05-financecore lit m07-marketing; m09-strategic-intelligence lit m01-front-office; m09-strategic-intelligence lit m02-revenue-crm; m09-strategic-intelligence lit m03-estimation; m09-strategic-intelligence lit m04-field-ops; m09-strategic-intelligence lit m05-financecore; m09-strategic-intelligence lit m06-material-control; m09-strategic-intelligence lit m07-marketing.

<!-- interconnexion:fin -->

La justification de chaque ligne « sans consommateur » (raison + date de revue) est dans
`docs/architecture/evenements-sans-consommateur.json` ; `a_revoir_avant` échu = avertissement de `--audit`, jamais un échec (le
test n'a pas d'horloge).

## 2. Consommateurs ajoutés par ce chantier

| Destinataire | Événement | Ce que le consommateur fait (et ne fait pas) | Registre du destinataire |
|---|---|---|---|
| M8 | `m7.signaux_marketing_constates`, `m7.depenses_marketing_constatees`, `m7.anomalie_depense_detectee`, `m7.conversion_hors_ligne_importee`, `m5.mesures_comptables_constatees`, `m3.mesure_vision_validee` | Range le constat tel quel ; la vue exécutive gagne la section `operations_recues` (une seule somme : les relevés de dépense reçus, par canal, dernière révision, bases de taxes non mélangées, jamais « dépense totale »). Réduite par paliers dits (`omis`) puis à son compte si la borne du socle l'exige : elle ne fait jamais échouer la vue de base. Fictifs exclus et comptés. Vision sans photo ni modèle. | `faits_operations` |
| M5 | `m7.depenses_marketing_constatees` | **Brouillon** d'écriture (compte « marketing » du plan, contrepartie Comptes fournisseurs), pièce déclarée jamais vérifiée. `TAXES_INCLUSES` : aucune ventilation (décision fiscale), rangé « à compléter » ; révision > 1 : jamais un second brouillon (rangé « à revoir ») ; montant nul, période close, horodatage sans fuseau : refus rangés. Rien n'est validé (N4 humain). À valider auprès d'un comptable (CPA) / professionnel qualifié. | `charges_marketing_recues` + `grand_livre` (brouillon) |
| M2 | `m7.conversion_hors_ligne_importee` | Lecture seule : le score voit « source connue » pour CE lead si M7 a une source normalisée ; le contrat du lead n'est jamais réécrit. | `conversions_hors_ligne_recues` |
| M2 | `m5.creance_relance_preparee` | Avertissement de coordination sur les relances commerciales du même client et phrase du coach ; rien n'est supprimé, retardé ni envoyé ; aucun montant au coach. | `creances_relances_recues` |
| M2 | `m3.contexte_site_pret` | Comptes du contexte de site (connus, inconnus, à vérifier, en conflit) dits au coach, dernière version. | `contextes_site_recus` |
| M3 | `m2.client_associe`, `m2.profil_propriete_confirme` | `m3_construire_contexte_site` reprend le profil CONFIRMÉ (étages, année) quand l'appelant n'en fournit pas ; plusieurs propriétés = « ambigu », rien deviné ; le profil de l'appelant l'emporte ; faits hors bornes écartés. | `liens_lead_client`, `profils_propriete_recus` |
| M4 | `m2.client_associe`, `m2.profil_propriete_confirme` | Bloc `contexte_propriete` de `m4_verifier_preparation`, HORS verdict (l'empreinte de préparation n'en dépend pas, aucun nouveau volet). | `liens_lead_client`, `profils_propriete_recus` |
| M1 | `m4.message_client_brouillon_pret` | **Brouillon** dans le sas d'envoi (courriel), vers l'adresse du lead chez M1, texte de M4 tel quel ; l'envoi reste une demande N3 d'une personne. SMS : « à reprendre » (l'assistant SMS ne prend que ses gabarits). Retrait de consentement depuis, lead inconnu, adresse absente, échéance : refus rangés. Aucun compte d'envoi connecté : échec avec recul, puis quarantaine visible (même patron que la commande de M6). | `messages_clients_m4` |
| M6 | `m5.rapprochement_po_constate` | Attente « À voir » de l'admin quand le dernier état d'une facture est `ECART` ou `INCOMPLET` ; M6 ne modifie jamais la facture ; aucun montant dans l'attente. | `rapprochements_facture_recus` |
| M9 | `m7.anomalie_depense_detectee`, `m8.fait_consolide` | Section `signaux_de_gestion` du briefing du matin : anomalies de la fenêtre (les plus graves d'abord, au plus 5) et RÉSUMÉ de la dernière consolidation de M8 (comptes et identifiants, aucune valeur). Le briefing reste sous la limite du socle. M9 lit, ne décide pas. | `signaux_gestion_recus` |
| M10 | `m5.dossier_cpa_scelle` | Mémoire (FINANCIAL, hors de tout paquet de contexte) qu'un dossier de période a été scellé ; même `dossier_id` sous un autre sceau = refus nommé (quarantaine visible), le premier sceau reste. M10 ne rouvre ni ne juge le dossier. | `dossiers_cpa_scelles` |

Aucun outil, aucun rôle d'appareil, aucune politique d'approbation, aucune migration n'est ajouté : le compteur d'outils, la portée
des appareils et le registre MCP ne changent pas.

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

Charge (`tests/test_interconnexion_charge.py`) : 1 000 événements de cinq types, 1 800 livraisons réelles ; comptes exacts des
registres (ni perte ni doublon), tous les reçus `traite`, aucune quarantaine ; rejeu complet sous d'autres identifiants sans
aucun maillon de plus ; panne de M8 au milieu du lot puis reprise. Durée mesurée de l'ordre de 10 s sur SQLite.

## 4. Mutations (preuve que les tests tuent)

Voir le rapport de livraison : dix mutations et plus, chacune faisant échouer au moins un test nommé.

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
- **M8 : entrepôt dérivé et score de santé** : les constats de M7/M5/M3 sont dans la vue exécutive, PAS dans les marts
  `m8_ent_*` ni dans les métriques gouvernées du catalogue (ce serait une nouvelle définition de métrique et une migration).
- **M10 : aucun outil de lecture dédié** pour `dossiers_cpa_scelles` (aucun nouvel outil, par choix) ; le registre existe et est
  append-only, sa lecture passera par un outil à venir.

## 7. Limites (sans euphémisme)

- Les consommateurs sont prouvés sur **SQLite** avec le bus et les vrais handlers ; **PostgreSQL** n'a pas été exercé pour ces
  consommateurs.
- Les maillons amont de M7 (connecteurs publicitaires) et de M6 (réception) sont publiés avec des charges du catalogue : leurs
  producteurs réels ne sont pas relancés ici, ni aucun service externe (Google Ads, Gmail, etc.).
- L'envoi (courriel de M1) est prouvé jusqu'au brouillon du sas et à la demande N3 ; **l'approbation humaine et l'envoi réel**
  n'ont pas été rejoués ici.
- Le brouillon de charge de M5 suppose le plan comptable par défaut (compte 5950, contrepartie 2100) : à valider auprès d'un
  comptable (CPA) / professionnel qualifié ; la ventilation des taxes d'un fournisseur étranger n'est pas faite.
- La somme des relevés de M8 est une somme des relevés **reçus**, pas la dépense publicitaire de l'entreprise : un jour sans
  relevé n'est pas un zéro et M8 ne sait pas quels jours manquent.
- L'ordre de livraison du bus n'est pas garanti : chaque consommateur choisit son « dernier état » par une clé de contenu
  (révision, date de référence, version), pas par l'ordre d'arrivée, sauf mention contraire.
- L'audit ne sait pas démontrer qu'un producteur *publie réellement* son type (il vérifie seulement que le nom du type apparaît
  dans son code ou dans le socle) ; les scénarios prouvent les producteurs qu'ils exécutent.

## 8. Commandes

```bash
python scripts/docs/interconnexion_evenements.py --audit      # écarts bloquants (sortie 1 s'il y en a)
python scripts/docs/interconnexion_evenements.py --ecrire     # régénère le bloc ci-dessus
python scripts/docs/interconnexion_evenements.py --verifier   # échoue si le bloc est périmé
pytest tests/test_interconnexion_*.py
```
