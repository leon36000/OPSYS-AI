# EXIGENCES — cockpit 3-en-1 : traçabilité CRM-01..16 et catalogue de rapports

Dérivé de `BRIEF-SECRETARIAT-20261027.md` et de `AUDIT-SECRETARIAT-3EN1.md` (même dossier). Rien ici n'est « complet » :
la colonne **Statut** dit l'état réel. Vocabulaire : **Livré-T1** (code de la tranche 1, non exécuté) · **Existant** (primitive de département
nommée, sans écran cockpit) · **Partiel** · **Manquant**. « Non exécuté » : aucun test n'a pu être lancé dans ce snapshot.

Mise à jour ROOT : la consultation T1 a été vérifiée séparément ; la tranche suivante ajoute les notes
internes authentifiées (voir [NOTES-CLIENT-AUTHENTIFIEES.md](NOTES-CLIENT-AUTHENTIFIEES.md)).
Les statuts Livré-T1 et la mention « non exécuté » ci-dessus décrivent le snapshot initial de Claude,
pas une absence de QA ultérieure. CRM-02 dispose maintenant d’une tranche M4 vérifiée localement (voir `ANNOTATIONS-CEDULE-M4.md`) ; CRM-05/06 gagnent la saisie
de note, mais pas le suivi des courriels ni leurs réponses.

Tranche consultation M3 : [SOUMISSIONS-DOSSIER-LECTURE.md](SOUMISSIONS-DOSSIER-LECTURE.md)
relie la liste admin par lead et le détail au dossier. CRM-05/07 restent partiels : consultation
uniquement, sans édition de clauses, génération de PDF ni envoi. Les constats T1 ci-dessous restent
l’état historique du snapshot initial.

Tranche recherche : [RECHERCHE-CLIENTS-M2.md](RECHERCHE-CLIENTS-M2.md) ajoute la recherche
nom/courriel/téléphone/lead dans M2 avant pagination, avec visibilité inchangée et masquage du terme
dans les journaux d’accès de la console. CRM-04 reste partiel : correction historisée SQLite ajoutée, voir [contrat et limites](CORRECTION-COORDONNEES-M2.md).

Principes transverses (critères d'acceptation communs à toute ligne)
- **CA-0** Le CRM soutient le travail de l'IA mais reste utilisable à la main : toute action de l'IA est visible, corrigeable et reprise par un humain autorisé.
- **CA-1** Aucune seconde vérité : le cockpit lit/écrit via les outils du département propriétaire (M2 commercial, M3 soumissions, M4 planning, M5 finance,
  M6 matériaux, M8 rapports, M10 mémoire).
- **CA-2** Une capacité n'est affichée que si sa primitive existe ; sinon la carte dit « non disponible » et nomme le contrat manquant. Aucun faux bouton d'envoi, aucun faux statut « envoyé/livré/synchronisé ».
- **CA-3** RBAC existant préservé (session par personne, CSRF, CSP, échappement `pages.e`), aucune identité venant des arguments.
- **CA-4** Fixtures fictives (`fictif: true`), aucun nom/adresse de client réel du brief. Fuseau d'affichage des agendas : `America/Montreal`.
- **CA-5** Accessibilité : aucune information portée par la couleur seule (texte de statut + légende).

## 1. CRM-01..16

| ID | Exigence (résumé) | Existant réel | Statut | Owner | Critère d'acceptation spécifique |
|---|---|---|---|---|---|
| CRM-01 | Cédule hebdomadaire équipes × jours, cartes cliquables, vue multi-mois, couleurs configurables + légende + texte | `m4_confirmer_dates_cedule`, `m4_lire_cedule_semaine` : source civile explicite après plan appliqué, révisions, conflits connus, dates invalidées par report/annulation/réassignation | **Partiel** (grille semaine et formulaire de dates internes, SQLite/HTTP qualifiés ; repères de couleur qualifiés localement ; aperçu trois mois sourcé qualifié localement ; pagination indépendante qualifiée en HTTP/SQLite ; visites multiples manquantes) | M4 (données), cockpit (rendu) | Grille semaine rendue depuis M4 uniquement ; carte → dossier ; légende textuelle ; couleur = préférence du cockpit stockée dans une collection de présentation M4 séparée **sans** altérer son registre opérationnel ; vue mois. Source, grille `/crm/cedule` et saisie `/crm/cedule/plan/{plan_id}` disponibles ; navigation lundi→dimanche, liens M2 vérifiés, statuts avec couleurs et texte, sans transformer une date interne en promesse client (contrat §3.1, [preuve et limites](CEDULE-HEBDOMADAIRE-M4.md)) |
| CRM-02 | Note rapide au clic sur job (pastille-note) | `m4_enregistrer_annotation_calendrier`, `m4_lire_annotations_calendrier`, `m4_resumer_annotations_calendrier` ; créneau exact, auteur serveur, versions conservées | **PARTIAL** : console privée SQLite ; qualification décrite dans `ANNOTATIONS-CEDULE-M4.md`, navigateur/agents/PostgreSQL ouverts | M4 | Pastille « note » = interprétation du message ; lien accessible + compteurs textuels ; ancienne date conservée sans transfert automatique. Aucune mutation planning/paie/notification |
| CRM-03 | Agenda par vendeur jour/semaine/mois, rendez-vous, sync, conflits, droits, America/Montreal, historique | Registre M2 agenda_vendeurs et console admin jour/semaine/mois | **Partiel — HTTP/SQLite qualifié localement** | M2, port admin privé | Distinguer vue (lecture) de synchronisation réelle (connecteur Google : approbation, journal, conflits). Un vendeur ne voit que son agenda. Voir §3.2 |
| CRM-04 | Répertoire clients/prospects permanent, recherche, coordonnées modifiables, multi-projets, historique, corrections tracées | `m2_lister_leads`, `m2_trouver_client_de_lead`, `m2_obtenir_client_360`, doublons | **Partiel** : répertoire recherché, dossier, correction historisée sur SQLite | M2 | Livré : liste paginée avec filtre statut, lien vers dossier, contact/ville depuis le contrat ingéré, opportunités multiples d'un même client visibles. Recherche et correction ajoutées ; historique visuel admin paginé, référence M10 minimisée et diagnostic de transmission ajoutés ; restent qualification PostgreSQL et propagation gouvernée |
| CRM-05 | Dossier client/projet : Activités, Suivi client, Rencontres, Soumissions, Bons de commande, Bons de travail, Coûts des travaux, Factures, Photos et fichiers | Voir lignes CRM-06..12 | **Partiel** (activités, soumissions et rencontres par projet raccordées ; les autres sections gardent leur statut réel) | M2 + départements | Les 9 sections sont présentes ; chacune dit sa source et son statut réel. « Vérification » **non** recopiée comme exigence (non validée) |
| CRM-06 | Activités = notes internes ; Suivi client = courriel exact, date/heure, destinataire, réponse dans le fil ; statut de livraison sourcé ; rendez-vous liés | Activités : interactions M2 (**Livré-T1** en lecture) ; courriels : aucun journal par client ; `m2_preparer_relance` = texte fixe, rien envoyé | **Partiel** (Activités) / **Manquant** (Suivi client) | M2 + M1 (canaux) | Un courriel n'apparaît « envoyé » que s'il existe une preuve d'envoi sourcée ; brouillon ≠ envoyé. Contrat §3.5 |
| CRM-07 | Soumissions préremplies, modèles/options/clauses éditables et **versionnés**, signée non réécrite | `m3_creer_devis`, `m3_generer_soumission_brouillon`, `soumission_pdf` | **Partiel** (catalogue versionné, version figée dans un nouveau devis et rendu HTML/PDF ; lignes et tarifs M6 raccordés en HTTP/SQLite ; sélection par libellé, navigateur et M10 ouverts) | M3 | Modifier un modèle crée une version ; un devis signé référence la version utilisée et reste identique. Contrat §3.6 |
| CRM-08 | Soumission acceptée → bon de travail planifiable avec contexte/matériaux ; readiness M4 avant confirmation | `m3_marquer_devis_accepte` → événement → M2 converti ; `m4_planifier_intervention`, `m4_verifier_preparation` | **Existant** (chaîne agents) / écran **Manquant** | M3→M2→M4 | Bouton « planifier » visible seulement après `devis_accepte` ; confirmation finale conditionnée par `m4_verifier_preparation` ; aucun report de date promis au client |
| CRM-09 | Note d’achat libre par chantier, structuration proposée puis validée | `m6_enregistrer_note_commande`, `m6_lire_note_commande`, `m6_lister_notes_commande` : formulaire, liste et historique depuis une soumission avec chantier M6 connu, admin actif, texte ≤20 000 car. | **Partiel** ; formulaire HTTP/SQLite vérifié, navigateur et PostgreSQL non qualifiés ; ancrage lead seul, structuration et conversion manquants | M6 (note/PO), M1 (envoi) | Aucune sélection d’articles requise pour la note ; aucun faux PO ni preuve d’envoi. Quotas, CAS, rejeu et audit vérifiés localement sur SQLite. [Contrat et limites](../inventory/M6-NOTES-COMMANDE.md) |
| CRM-10 | Coût réel en fin de job : MO, matériaux, extras, dépenses, pièces, prévu/réel | `m5_lire_rentabilite_chantier`, `m3_lire_ecarts_estime_reel`, `m6_evaluer_variance_chantier`, `m4_produire_brouillon_temps` | **Existant** (outils) / écran **Manquant** | M5 (+M6, M4) | Tableau prévu/réel par poste, chaque ligne avec sa source ; aucune addition faite par le cockpit |
| CRM-11 | Facture modifiable selon l'état : brouillon éditable ; émise → correction M5 tracée/versionnée ; période fermée protégée | `m5_creer_facture_brouillon`, `m5_envoyer_facture`, `m5_enregistrer_paiement_facture` ; correction seulement côté fournisseur | **Partiel** | M5 | Brouillon : édition ; émise : « corriger » ouvre un mécanisme M5 versionné (note de crédit/révision) ; jamais de suppression ni modification silencieuse. Contrat §3.8 |
| CRM-12 | Photos et PDF par dossier : dépôt, aperçu, classement, téléchargement autorisé, liens projet/bon/facture ; pas d'usage marketing auto | `m4_deposer_fichier`/`m4_etat_fichier`, M10 `m10_*_document_*_appareil`, politique photos M3 | **Partiel** (primitives) / écran **Manquant** | M10 (+M4) | Aucun fichier orphelin : un dépôt exige un rattachement ; téléchargement par rôle ; la politique marketing reste M7 (consentement) |
| CRM-13 | Tableau commercial chiffré gagnés/perdus, en cours, acceptés, volumes/montants, période/filtre, définitions | `m8_lire_vue_executive`, `m8_rapport_metriques`, définitions M8, `m2_lister_leads` (aucun montant), `m3_lister_devis` | **Partiel** | M8 (+M2, M3) | Chaque chiffre porte sa définition M8, sa période et sa source ; pas de montant calculé dans le cockpit |
| CRM-14 | Prix fournisseurs : réception de listes par courriel, détection, import annuel/catalogue, comparaison, historique, anomalies, mise à jour validable ; fournisseurs connus Gentek, Royal Solution de Bâtiment, O.A.M., Kaycan | M6 livre de prix manuel (`m6_enregistrer_prix`, `m6_resoudre_prix_materiau`, fournisseurs) | **Partiel** (livre de prix) / **Manquant** (détection courriel, import, anomalies) | M6 (+M1 pour la réception) | Variante dictée ≠ nouveau fournisseur (file de revue) ; ligne ambiguë → revue humaine ; aucun prix inventé ; les soumissions historiques gardent leur version. Contrat §3.9 |
| CRM-15 | Contrat employé annuel signé en ligne, profil à jour, permis + échéance en accès restreint, heures ; jamais visible du CRM vendeur/client | `m5_enregistrer_contrat_horaire`, `paie_admission_ui`, `m4_pointer` | **Partiel** (contrat horaire M5) / **Manquant** (signature en ligne, documents RH) | M5/M4 (RH à trancher) | Accès restreint propriétaire/admin ; absent du répertoire et du dossier client par conception (test négatif) ; Loi 25 |
| CRM-16 | Journal quotidien d'équipe : qui avec qui, prévu vs visité, terminé/reporté, extras, absences, heures ; historique annuel ; plusieurs visites conservées | `m4_pointer`, `m4_signaler_report`, `m4_completer_intervention`, `m4_lire_retards_incidents`, `m4_produire_digest` | **Partiel** (événements) / **Manquant** (journal par jour/équipe) | M4 | Une visite reportée puis reprise 4 jours plus tard donne deux entrées ; la première date n'est jamais écrasée (test) |

## 2. Modules/navigation visibles du brief (photos 9960–9965)

Rapprochement avec l'existant ; aucune entrée de navigation n'est créée sans page réelle.

| Module du brief | Rapprochement | Statut |
|---|---|---|
| Comptabilité : opérations bancaires, intégration, reçus, rapprochement, règles, plan comptable, récurrentes, espace comptable | `banque_ui` (prévisualisation/rapprochement), `obligations_rapprochement_ui`, M5 mouvements ; plan comptable/règles/récurrentes non repérés | Partiel |
| Dépenses & fournisseurs : opérations, fournisseurs, factures à payer, kilométrage | `fusion_ap_*`, M5 factures fournisseur, `m5_lister_comptes_a_payer`, M6 fournisseurs ; kilométrage non repéré | Partiel |
| Ventes & encaissements : aperçu, opérations, factures, liens de paiement, commandes de vente, paiements, produits/services | M5 factures/paiements, M3 devis ; liens de paiement : paiement = frontière humaine T3 | Partiel |
| Centre clients : aperçu, clients/prospects, occasions, devis, propositions, contrats, rendez-vous, évaluations | **Tranche 1** (clients/prospects), M2 pipeline, M3 devis, M7 avis ; rendez-vous internes admin M2 : agenda et dossier | Partiel (T1) |
| Paie : aperçu, employés, cotisations, conformité | `paie_ui`, `paie_admission_ui`, M5 `m54*` (préparatoire) | Partiel (préparatoire, validation CPA requise) |
| Équipe, projets, stock, taxe de vente, marketing | M4, M5 chantiers, M6 stock, M5 taxes, M7 (onglet Marketing) | Partiel |
| Barre latérale : création, signets, accueil, rapports, applications, favoris | Aucun équivalent (onglets fixes `pages.ONGLETS`) | Manquant |

## 3. Catalogue de rapports (photos 9965–9970)

Règle générale **RPT** : un rapport canonique, plusieurs raccourcis ; chaque rapport = source nommée (M5/M6/M8/M4), définition, période, filtres,
export, fixtures fictives ; sinon carte « non disponible ». Critère d'acceptation par ligne = **RPT** + précision de la colonne « Note ».
Statut par défaut : **Manquant** (aucun écran « Rapports » dans la console) ; la colonne « Primitive » nomme ce qui existe déjà côté département.
Libellés coupés/illisibles dans les photos : **non inventés** (§4).

### R-ENT Entreprise (owner M5, vue M8)
| Sous-rapport | Primitive | Statut / note |
|---|---|---|
| Journal de bord | `journaliser` (journal d'audit socle) à confirmer | Manquant — sens exact à clarifier |
| Bilan / provisoire, comparaison, détail, sommaire | aucune | Manquant (plan comptable M5 requis) |
| État des flux de trésorerie | `m5_etat_tresorerie`, `m5_prevoir_tresorerie` (prévision, pas état QuickBooks) | Partiel |
| Aperçu entreprise | `m8_lire_vue_executive` | Partiel |
| Variations des capitaux propres (libellé anglais visible) | aucune | Manquant |
| Compte de résultat ; par client / classe / mois / groupe de balise ; comparaison ; détail | aucune | Manquant |
| Taille commune (% du chiffre d'affaires) | aucune | Manquant |
| Comparaison annuelle cumulative ; sommaire trimestriel | aucune | Manquant |
| Rentabilité projet | `m5_lire_rentabilite_chantier` | Existant (sans écran) |

### R-AR Ce qu'on vous doit (owner M5)
| Sous-rapport | Primitive | Statut / note |
|---|---|---|
| Classement chronologique des comptes clients — sommaire / détail | `m5_lire_comptes_a_recevoir` (forme à relire) | Partiel |
| Perception / recouvrement | `m2_lister_relances` (relances commerciales) ≠ recouvrement | Manquant |
| Soldes clients — sommaire / détail | `m5_lire_comptes_a_recevoir` | Partiel |
| Liste de factures ; factures/paiements reçus ; factures impayées | M5 factures/paiements | Partiel |
| Relevés de compte ; modalités | aucune | Manquant |
| Activités/imputations et heures non facturées | `m4_produire_brouillon_temps`, `m5_lister_attentes_facturation` | Partiel |

### R-STOCK Stocks (owner M6)
| Sous-rapport | Primitive | Statut / note |
|---|---|---|
| Évaluation des stocks — détail / sommaire | `m6_lire_disponibilite`, `m6_produire_digest` | Partiel |
| Bons de commande en cours — détail / liste | M6 PO (`creer/approuver/annuler`) | Partiel |
| Feuille de calcul d'inventaire ; état des stocks | `m6_soumettre_comptage` | Partiel |

### R-VENTES Ventes et clients (owner M2/M3/M8)
| Sous-rapport | Primitive | Statut / note |
|---|---|---|
| Transactions de paiement / cashflow (libellé anglais visible) | M5 paiements | Partiel |
| Ventes par type de client | aucune | Manquant (taxonomie de type de client à définir) |
| Devis et facturation à l'avancement par client | `m3_lister_devis`, M5 contrats `m5_enregistrer_echeancier_contrat` | Partiel |
| Coordonnées et annuaire clients | **Tranche 1** (répertoire, contact du contrat ingéré) | Partiel — Livré-T1 |
| Revenus par client ; ventes par client sommaire / détail | M5 + M8 | Manquant |
| Dépôts | aucune | Manquant |
| Devis par client | `m3_lister_devis` | Partiel |
| Produits/services : liste ; ventes sommaire / détail | catalogue services (taxonomie) + M3 | Partiel |
| Ventes par classe — sommaire / détail | aucune (« classe » à définir) | Manquant |
| Modes de paiement ; heures par client | aucune ; `m4` heures | Manquant ; Partiel |
| Opérations par client / groupe de balise | aucune | Manquant |

### R-AP Ce que vous devez (owner M5)
| Sous-rapport | Primitive | Statut / note |
|---|---|---|
| Classement chronologique des comptes fournisseurs — sommaire / détail | `m5_lister_comptes_a_payer` | Partiel |
| Factures fournisseurs et paiements sortants ; liste de paiements | `m5_saisir_facture_fournisseur`, mouvements | Partiel |
| Factures non réglées ; soldes fournisseurs sommaire / détail | `m5_lister_comptes_a_payer` | Partiel |

### R-ACHATS Dépenses / fournisseurs (owner M5/M6)
| Sous-rapport | Primitive | Statut / note |
|---|---|---|
| Détails des chèques | aucune | Manquant |
| Achats par produit/service/classe ; liste des achats | M6 réceptions + M5 factures fournisseur | Partiel |
| Information T4A fournisseur ; détails feuillet T4A | aucune | Manquant — préparatoire, validation M5/CPA |
| Information T5018 fournisseur ; détails formulaire T5018 | aucune | Manquant — idem |
| Opérations par fournisseur ; achats par fournisseur ; dépenses par fournisseur (sommaire) | M5/M6 | Partiel |
| Coordonnées / annuaire fournisseurs | `m6_lister_fournisseurs` | Existant (sans écran) |

### R-TAXES (owner M5 — préparatoire, règles fiscales sourcées requises avant usage officiel)
| Sous-rapport | Primitive | Statut / note |
|---|---|---|
| Rapport détaillé / sommaire TPS/TVH–TVQ | `m5_calculer_taxes_tps_tvq` (calcul), `m5_lire_echeances_fiscales` | Partiel |
| Exceptions ; opérations sans taxe ; ventes taxables ; opérations par code taxe | aucune | Manquant |

### R-EMPLOYÉS (owner M4/M5)
| Sous-rapport | Primitive | Statut / note |
|---|---|---|
| Coordonnées des employés | `identite` (personnes) ; RH à cadrer | Partiel — accès restreint (CRM-15) |
| Heures travaillées récentes / modifiées ; détail des heures par employé | `m4_pointer`, `m4_lire_heures_regulieres_validees` | Partiel |

### R-COMPTABLE Pour le comptable (owner M5)
| Sous-rapport | Primitive | Statut / note |
|---|---|---|
| Liste des comptes ; classes | aucune (plan comptable) | Manquant |
| Exceptions à la clôture ; opérations automatiques récentes ; opérations récentes | `obligations_*`, journal socle | Partiel |
| Bilan et résultats (raccourcis vers R-ENT) | — | Manquant (raccourci seulement) |
| Journal non validé ; journal ; grand livre général / liste | aucune | Manquant |
| Modèles récurrents | M5 échéanciers de contrat (`m5_enregistrer_echeancier_contrat`) | Partiel |
| Rapprochement | `banque_ui`, `obligations_rapprochement_ui` | Partiel |
| Balance de vérification et ajustée ; opérations par compte/date ; opérations avec répartitions | aucune | Manquant |

### R-PAIE (owner M5 — préparatoire, validation CPA)
| Sous-rapport | Primitive | Statut / note |
|---|---|---|
| Historique des chèques de paie ; détail paie ; éléments de paie ; sommaire paie | `m5_preparer_brut_regulier`, `m5_preparer_dossier_webras` (préparatoire) | Partiel |
| Retenues/cotisations ; obligations et paiements de cotisations ; sommaire cotisations sociales/traitements | `m54e…m54h` (impôt, RRQ), `m5_lire_sources_regles_paie` | Partiel |
| Paie par employé (sommaire) ; répertoire/détail employés ; lieux de travail multiples | contrat horaire M5, M4 | Partiel / Manquant |
| Congés annuels et maladie ; régimes de retraite | aucune | Manquant |
| Coût total de la paie ; rémunération totale ; rémunération des travailleurs | aucune | Manquant |
| Téléchargement des rapports de paie | aucune | Manquant |
| Heures récentes/modifiées et détail par employé | voir R-EMPLOYÉS | Partiel |

### Navigation des rapports
Standards, personnalisés, direction, planification financière, aperçu/planificateur de flux de trésorerie, budgets, recherche, favoris :
**Manquant** (aucun écran rapports). Critère : aucun lien n'est affiché sans rapport derrière ; « favoris » exige un stockage de préférence par personne (cockpit, non métier).

## 4. Ambiguïtés et points ouverts (sans blocage)

1. **Pastille-note (CRM-02)** : hypothèse « pastille indiquant une note, clic pour lire/ajouter » ; non confirmée par la secrétaire.
2. **Couleurs** par état/équipe/service : règle non connue ; la configurabilité est exigée (CRM-01), la palette ne l'est pas.
3. **Terminologie dictée** (fournisseurs, rubriques) : toute variante incertaine passe en revue humaine (CRM-14).
4. **Édition/version QuickBooks visée** et libellés coupés en bas de photos : non inventés ; à compléter avec les prochaines photos.
5. **Agenda Google (CRM-03)** : vraie synchronisation bidirectionnelle vs agenda « similaire ». Les deux se cadrent séparément ; seule la vue est livrable sans connecteur.
6. **« Vérification »** (dossier, photo 9972) : non validé comme exigence métier.
7. **Qui est l'utilisateur du cockpit** : les outils M2 acceptent `seller` et `admin`. La console n'ouvre aujourd'hui que `nathan_owner`/`admin` ; la secrétaire n'a pas de rôle défini dans `ROLES.md` (à décider par ROOT : rôle dédié ou `admin`).
8. **Recherche** : l'absence de nom dans `m2_lister_leads` rend la recherche par nom impossible côté cockpit sans primitive M2 (§3.3).

## 5. Tranche 1 livrée (non exécutée)

**Répertoire et dossier client en lecture seule sur M2** — voir le HANDOFF pour fichiers et comportement.
Critères d'acceptation de la tranche : (1) accès refusé sans session, sans rôle `admin` ; (2) lecture uniquement par `metier.executer` (LECTURES) ; (3) aucune valeur
inventée : champ absent = « — » ; (4) échappement systématique (XSS) ; (5) chaque section non branchée dit « non disponible » avec l'outil/contrat visé ;
(6) aucune écriture, aucun bouton d'envoi ; (7) pagination fidèle au `decalage` de M2.

## Annexe A. Contrats proposés (primitives manquantes — non codés)

Chaque contrat : outil, entrées, sortie, propriétaire, approbation, journal. Les événements/auth/permissions/DB existants ne sont pas modifiés ;
ROOT décide de l'intégration.

- **3.1 `m4_lire_cedule_semaine`** (M4, lecture) — `{debut_semaine: date, equipes?: [id]}` → `{interventions:[{intervention_id, lead_id, equipe_id, debut, fin, statut, visites:[{prevue_le, reelle_le, issue}]}], fuseau:"America/Montreal"}`. Source : cédule M4. Aucune donnée de contact. Rôle admin.
- **3.2 Agenda** — M2 est propriétaire des rendez-vous commerciaux internes : `m2_lire_agenda_vendeur`, `m2_enregistrer_rendez_vous`, `m2_historique_rendez_vous` (port admin privé), conflits intégrés ; accès console vendeur à qualifier ; synchronisation Google = connecteur approuvé (T3 pour toute écriture externe), journal, version.
- **3.3 `m2_rechercher_clients`** (M2, lecture) — `{texte (≥3 car.), decalage, limite}` → `{clients:[{client_id, nom, ville, lead_ids}]}` ; même contrôle d'accès que `m2_lister_leads`.
- **3.4 `m2_corriger_contact`** (M2, écriture T1/T2) — `{client_id, champs, motif, revision_attendue}` → nouveau maillon append-only (ancienne valeur conservée), idempotent (`mutation_id`), auteur = session.
- **3.5 `m2_enregistrer_courriel`** (M2/M1) — `{lead_id, direction: sortant|entrant, destinataire, objet, corps_ref, instant, statut_livraison, source_preuve}` ; `statut_livraison ∈ {brouillon, en_attente, envoye, livre, echec, inconnu}` ; `envoye` exige `source_preuve`.
- **3.6 Modèles de soumission versionnés** (M3) — `m3_lister_modeles`, `m3_proposer_version_modele`, `m3_activer_version_modele` (approbation humaine) ; `m3_creer_devis` figé sur `version_modele_id`.
- **3.7 `m6_enregistrer_note_commande`** (M6) — `{lead_id|chantier_id, texte_libre ≤ N, auteur}` ; `m6_proposer_structuration_note` → lignes suggérées à approuver.
- **3.8 `m5_corriger_facture_emise`** (M5) — `{facture_id, motif, lignes_corrigees, revision_attendue}` → version/note de crédit M5 ; refus fermé si période close.
- **3.9 `m6_importer_liste_prix`** (M6) — `{fournisseur_id (connu), source_ref, lignes:[{item, unite, couleur, profil, prix, date_effet}]}` → écarts/anomalies/doublons en revue ; politique d'auto-validation configurable.

La tranche CRM-01 serveur rend `m4_lire_cedule_semaine(debut_semaine)` sans filtre équipes ni visites réelles multiples pour l'instant. Les champs `validite`, `revision`, `source_ligne_id`, `source_application_id`, les listes `sans_date`, les totaux et la troncature explicite complètent la source. `m4_confirmer_dates_cedule` exige un admin actif et une révision attendue ; une donnée non datée reste non datée. La grille HTML semaine et la saisie des dates internes depuis le détail borné `m4_lire_calendrier_plan` sont qualifiées par TestClient sur SQLite ; CSRF, révision attendue, identité active et rejeu contrôlés. Les données tronquées bloquent la saisie. Les couleurs sont des statuts fixes avec légende ; préférences personnalisées, visites successives et validation visuelle navigateur restent ouvertes. Voir [audit ciblé](CEDULE-HEBDOMADAIRE-M4.md).

## Annexe B. Capacités avancées des agents (cadre commun, à instancier par ROOT)

Pour chaque fonction du CRM : agent responsable (département propriétaire), outils réels (colonnes « Existant » ci-dessus), déclencheur (événement du bus
ou cron `department.yaml`), approbation (palier T0–T3 ; écriture externe/argent = humain), journal (registre append-only + `journaliser`), budget (`budget:`
du département), test (preuve fictive), résultat mesurable (ex. « note enregistrée en < N clics », « soumission préremplie en < N minutes »).
Tranche 1 n'ajoute **aucun** agent ni déclencheur : elle donne la visibilité humaine sur les dossiers que les agents M2 alimentent déjà.


Mise à jour CRM-01 couleurs : [COULEURS-CEDULE-M4.md](COULEURS-CEDULE-M4.md) décrit la palette manuelle, les références exactes, les versions et les preuves HTTP/SQLite. Les mentions historiques de couleurs manquantes ci-dessus restent datées de leurs tranches. Aucun classement automatique par service/équipe ni statut métier n’est déduit du repère.

Mise à jour CRM-01 multi-mois : [APERCU-MULTIMOIS-M4.md](APERCU-MULTIMOIS-M4.md) décrit la lecture privée `m4_lire_apercu_mois`, la route `/crm/cedule/mois`, les totaux depuis un instantané unique et les liens vers la semaine. Les anciens constats de vue mois absente restent historiques. Pas de disponibilité ni durée d’occupation déduite des comptes par date de début.

Évolution CRM-01 grand carnet : [PAGINATION-CEDULE-M4.md](PAGINATION-CEDULE-M4.md) décrit deux listes de 25 éléments navigables indépendamment, avec référence de source et reprise explicite si M4 change. Le contrat historique plafonné est conservé ; la qualification de cette tranche est consignée dans ce document.

CRM03 : [audit initial](AUDIT-AGENDA-VENDEURS.md), [contrat et limites de la tranche interne](AGENDA-VENDEURS-M2.md).

CRM05 : [rencontres par projet](RENCONTRES-DOSSIER-M2.md), pagination sourcée, anciens vendeurs conservés. Les courriels et autres sections restent ouverts.

CRM07 : [catalogue textuel versionné](MODELES-SOUMISSION-VERSIONNES-M3.md). [Version figée et rendu client](RATTACHEMENT-MODELE-DEVIS.md) raccordés; [lignes et tarifs préremplis](PREFILL-HTTP-M3-M6.md) qualifiés en HTTP/SQLite. M10 et navigateur restent ouverts.

CRM07 — [Rattachement explicite aux nouveaux devis](RATTACHEMENT-MODELE-DEVIS.md) : textes figés et documents;
les lignes et tarifs explicites sont raccordés en [HTTP/SQLite](PREFILL-HTTP-M3-M6.md); mobile/M10 et qualifications navigateur/PostgreSQL restent ouverts.
