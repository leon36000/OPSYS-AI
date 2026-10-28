# AUDIT — cockpit CRM 3-en-1 (secrétariat) : état réel du dépôt au 2026-10-27

Écrit AVANT tout code, dans le snapshot privé. Source des exigences : `BRIEF-SECRETARIAT-20261027.md`
(interprétation dépersonnalisée de 13 photos ; aucune donnée client réelle). Ce document constate, il ne promet rien.

## 0. Méthode et limites

- Lectures ciblées seulement (Read/Glob/Grep) : `AGENTS.md`, `src/opsys/console/{application,pages,metier,reception_digest_ui}.py`,
  `departments/m02-revenue-crm/{department.yaml, outils.py, acces.py, clients.py, liste_leads.py}`, listes d'outils
  (`nom="m…"`) de M3/M4/M5/M6/M8/M10, `tests/test_console_metier.py`, `tests/conftest.py`.
- Rien n'a été exécuté (pas de Bash, pas de pytest). Les départements M5/M6/M8/M10 et la plupart des écrans console
  (finance, banque, fusion AP, paie, CFO) ont été **inventoriés par noms d'outils/routes**, pas relus en profondeur :
  « existant » signifie « un outil ou une route porte ce nom », pas « le parcours secrétaire fonctionne ».
- `core/ui/src` (UI TypeScript du fork OpenClaw) n'a pas été exploré en détail : un grep de comptage sur « agenda/calendrier/cédule »
  ne montre que des occurrences génériques (tests de navigation, plugins, appareils) ; aucun agenda métier identifié. À confirmer.
- Le dossier `docs/grs/crm/` était vide : cet audit et les exigences en sont les premiers fichiers.

## 1. Cockpit actuel (`src/opsys/console/`)

Architecture : application FastAPI (`application.creer_application`), HTML rendu côté serveur par fonctions pures (`pages.py`,
échappement `pages.e()`), une `APIRouter` par module (`creer_router(session_page=…, cnx_factory=…, deps=…, prefixe=…)`),
CSP stricte (`default-src 'none'; style-src 'self'; script-src 'self'`), cookie de session signé, CSRF sur toute écriture,
connexion par personne (`opsys.identite`), rôles relus en base à chaque requête (`session_de`).

| Onglet (`pages.ONGLETS`) | Module console | Nature |
|---|---|---|
| Départements, Approbations, Budgets, Modèles, Agents | `application.py`, `agents_ui.py` | pilotage IA (admin/owner) |
| Connecteurs | `connecteurs_ui.py` | |
| Mémoire | `memoire_*` | M10 |
| Réception | `reception_digest_ui.py`, `voicemail_ui.py`, `frontoffice_marketing.py` | M1 (lecture bornée, appels manuels) |
| Marketing | `marketing_*`, `brand_ui`, `calendrier_marketing_ui` | M7 |
| Finance | `finance_ui`, `cfo_ui`, `banque_ui`, `paie_ui`, `obligations_rapprochement_ui` | M5 (cash libre, obligations, rapprochement bancaire, paie préparatoire) |
| Fusion opérationnelle | `fusion_ui`, `fusion_ap_*`, `fusion_pdf*`, `fusion_synthese` | rapprochement AP/PDF/OCR |
| Suivis stratégiques | `strategie_suivis_ui` | M9 |

**Constat borné de la première passe : aucun répertoire M2 ni dossier client unifié identifié dans la console.**
Les pages finance, rapports marketing/stratégiques et apprentissage estimation existent déjà ; cette passe
ne permet pas de conclure à l’absence de tout écran M3/M6/M8 ni de tous les rapports. La parité
secrétariat nécessite une revue fonctionnelle des primitives, pas seulement un inventaire de noms.
Le CRM métier possède déjà des outils de département appelables par les agents.

### Mécanisme d'accès aux outils de département depuis la console

`console/metier.py::executer(cnx, deps, session, nom, arguments, …)` :
- surface **fermée** : `LECTURES` (dict nom → département) en lecture, `COMMANDES` seulement avec `mutation_id` (idempotence) ;
- exige une personne active `nathan_owner` ou `admin` (relue en base) ; l'horodatage est **créé par le serveur** ;
- appelle l'outil via `executer_atomique` sous `contexte.appele_par_appareil(IdentiteAppelante(personne, rôle, source="console"))` ;
- les lectures M9 imposent le rôle `admin` (les outils revérifient le rôle d'appareil). **Le même piège s'applique à M2** :
  `m2_revenue_crm.acces.ROLES_LEADS = {seller, admin}` → un appelant `nathan_owner` seul est refusé par l'outil
  (`REJ-IDENTITE-APPAREIL-INVALIDE`). Voie propre : exiger le rôle `admin` en base et appeler avec le rôle `admin`
  (jamais `appele_par_appareil(None)`, qui contournerait l'identité).
- Aucune lecture M2/M3/M4 n'est aujourd'hui dans `LECTURES`.

## 2. Départements : vérité et primitives réelles

### M2 Revenue CRM — vérité commerciale (`m02-revenue-crm`)
Outils : `m2_lister_leads` (pagination, filtres statut/segment, vendeur = ses leads), `m2_trouver_client_de_lead`,
`m2_obtenir_client_360` (contact, opportunités, interactions récentes ≤ 10, prochaines actions), `m2_enregistrer_interaction`
(note ≤ 300 car., auteur = personne authentifiée), `m2_transitionner_statut`, `m2_reassigner_lead`, doublons
(`detecter/signaler/arbitrer`), `m2_lister_relances`, `m2_preparer_relance` (texte fixe, **rien n'est envoyé**),
`m2_enregistrer_consentement_contact`, `m2_evaluer_readiness`, `m2_suggerer_prochaine_action`, `m2_produire_digest`.
Registre append-only durable ; Client 360 = projection, pas de seconde base. Segments configurables (`department.yaml` vide à dessein).
**Manques côté M2** : recherche textuelle (nom/téléphone/courriel/adresse) ; **édition des coordonnées** (aucun outil de correction
du contact : le contact vient du contrat ingéré) ; la liste ne porte pas `client_id` ni le nom (il faut `m2_trouver_client_de_lead` +
360 par lead) ; liens multi-projets = « opportunités d'un client » (présent), mais pas de projet/dossier chantier distinct du lead ;
interactions de type « courriel envoyé/reçu » absentes (seulement des notes).

### M3 Estimation — soumissions
`m3_creer_devis`, `m3_lire_devis`, `m3_lister_devis`, `m3_generer_soumission_brouillon`, `m3_marquer_devis_accepte`,
`m3_detecter_devis_sans_reponse` ; `soumission_pdf.py`. Aucun modèle de soumission/clauses **versionnés** et éditables par une
secrétaire repéré (recherche « clause|modele_soumission » : seulement `soumission_pdf` et `hierarchie_echelle`). Non modifiable ici (M3 interdit).

### M4 Field-ops — planning et exécution
`m4_planifier_intervention`, `m4_lister_interventions` (id, statut, lead, technicien assigné ; **`fenetre_planifiee` toujours `null`**
d'après sa description : le registre ne porte pas encore la fenêtre → pas de grille semaine/équipe/jour possible sans cette primitive),
`m4_proposer_cedule`/`m4_appliquer_cedule` (cédule/tournées), `m4_verifier_preparation` (readiness), `m4_signaler_report`,
`m4_completer_intervention`, `m4_pointer`, `m4_produire_brouillon_temps`, `m4_valider_heures_regulieres`, `m4_deposer_fichier`/`m4_etat_fichier`
(preuves/photos), `m4_lire_retards_incidents`. Pas d'agenda par vendeur ni de rendez-vous commerciaux.

### M5 FinanceCore — vérité financière
Factures client : `m5_creer_facture_brouillon`, `m5_envoyer_facture`, `m5_enregistrer_paiement_facture`, `m5_lister_attentes_facturation`,
`m5_lire_comptes_a_recevoir`, `m5_lire_rentabilite_chantier` (base de CRM-10), `m5_lire_comptes_a_payer`/`m5_lister_comptes_a_payer`,
factures fournisseur (`saisir/corriger/annuler`), taxes (`m5_calculer_taxes_tps_tvq`, échéances), trésorerie, paie préparatoire.
**Manque** : correction tracée d'une facture **client émise** (seule la facture fournisseur a `corriger/annuler`) ; grand livre, balance de
vérification, bilan, compte de résultat (aucun fichier source ne les nomme) ; états de compte clients ; journal comptable consultable.

### M6 Material-control — matériaux et achats
Bons de commande : `m6_creer_po_brouillon`, `approuver_po`, `annuler_po`, `generer_courriel_po`, `marquer_po_envoye` ; livre de prix
(`m6_enregistrer_fournisseur`, `m6_enregistrer_prix`, `m6_resoudre_prix_materiau`, `m6_lister_fournisseurs`) ; réception, stock, variance, pertes.
Les noms Gentek/Kaycan/Royal/O.A.M. n'apparaissent que dans des **tests** M6 : aucune détection de listes de prix reçues par courriel ni import
annuel. La « grosse note libre » CRM-09 n'a pas de champ dédié identifié (PO structuré par articles). M6 est hors périmètre d'édition (ROOT).

### M8 Analytics — rapports
`m8_lire_vue_executive`, `m8_rapport_metriques`, `m8_construire_rapport`, `m8_produire_digest_quotidien`, définitions de métriques versionnées
(`m8_enregistrer/resoudre/lister_definitions_metriques`), `m8_lire_mesures_chantier`, `m8_performance_equipe`, provenance M5 appareil.
Base crédible du tableau commercial (CRM-13) ; aucune relecture n'a vérifié la présence de « ventes gagnées/perdues par période ».

### M10 Mémoire — documents d'affaire
`m10_deposer_version_document_appareil`, `m10_activer_version_document_appareil`, `m10_retirer_document_appareil`,
`m10_lister_documents_affaire_appareil`, `m10_lire_version_document_affaire_appareil`, `m10_rechercher_affaire_appareil`,
`m10_paquet_contexte_affaire` : base de CRM-12 (photos/PDF par dossier) et du contexte d'une affaire. Console : `memoire_*_ui`.

## 3. Frontières sources de vérité (à conserver)

M2 = commercial (leads, clients, interactions) · M3 = soumissions · M4 = planning/exécution/heures · M5 = argent, factures, paie ·
M6 = matériaux/achats/prix fournisseurs · M8 = rapports/métriques · M10 = mémoire/documents. Le cockpit **projette et relaie**
(lecture via `metier.executer`, écritures via outils idempotents/approuvés) ; il ne recalcule ni solde, ni prix, ni statut, et ne
stocke aucune donnée métier propre. Les dossiers de la secrétaire (activités, notes) passent par `m2_enregistrer_interaction`.

## 4. Écarts majeurs par rapport au brief (synthèse)

1. Pas de **primitive de planification affichable** (fenêtre d'intervention, équipes, jours) → CRM-01 bloqué en amont (contrat à proposer, M4).
2. Pas d'**agenda par vendeur / rendez-vous / synchronisation** → CRM-03 : primitive entière manquante (M2 ou module agenda dédié + connecteur).
3. **Édition de contact** et **recherche** manquantes dans M2 → CRM-04 partiel (consultation réelle possible, correction non).
4. **Suivi client = courriel exact + livraison + réponse** : M1/M2 n'exposent pas de journal de courriels par client → CRM-06 partiel.
5. **Modèles/clauses versionnés** (M3), **note libre de PO** (M6), **correction de facture émise** (M5), **import de listes fournisseurs** (M6),
   **contrat employé signé en ligne** (M5/M4), **journal quotidien d'équipe** (M4) : primitives manquantes.
6. **Catalogue de rapports** : la quasi-totalité des rapports comptables type QuickBooks (R-ENT, R-COMPTABLE, R-PAIE…) n'a pas de source M5
   identifiée ; aucun écran « Rapports » dans la console. Ne pas afficher de cartes factices.
7. **Surface console M2 absente** : la tranche réaliste immédiate est le répertoire + dossier client en lecture sur M2, avec sections
   honnêtement marquées (réelle / à venir / manquante).

## 5. Choix de la première tranche

Voir `EXIGENCES-SECRETARIAT-3EN1.md` §Tranche 1 et `HANDOFF-CLAUDE-SONNET55.md`. En bref : **Répertoire (`/crm`) + dossier client/projet
(`/crm/lead/{lead_id}`)**, lecture seule, adossés à `m2_lister_leads` / `m2_trouver_client_de_lead` / `m2_obtenir_client_360` via
`metier.executer`, rôle `admin` requis, avec le tableau des 9 sections de CRM-05 dont chacune dit sa source et son statut réel.
Justification : c'est la seule surface qui (a) s'appuie sur une primitive existante, (b) ne demande aucune modification d'un département
interdit, (c) n'invente aucune donnée, (d) alimente tout le reste (CRM-05/06/08/09/10/11/12 se rattachent au dossier).
