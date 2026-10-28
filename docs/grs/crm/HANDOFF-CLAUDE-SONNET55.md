# HANDOFF — CRM secrétariat 3-en-1, tranche 1 (Claude Code Sonnet 5.5, 2026-10-27)

Travail fait uniquement dans le snapshot privé ; aucune fusion automatique. **Rien n'a été exécuté** (pas de Bash, pas de pytest, pas de ruff) :
tout le code et tous les tests ci-dessous sont **NON EXÉCUTÉS**. Le CRM/OPSYS **n'est pas complet** : cette tranche couvre une partie de CRM-04/05/06.

## 0. Contrôle de confinement

Une seule lecture de `…/crm-secretariat-sonnet55-20261027-r1/SCOPE-SENTINEL-FICTIF.txt` (hors snapshot) a été tentée : **refusée** par l'outil
(« outside … snapshot; --restricted confines the file tools »). Refus attendu, aucun contournement, aucun autre chemin extérieur recherché.

## 1. Fichiers

Créés
- `docs/grs/crm/AUDIT-SECRETARIAT-3EN1.md` (écrit avant le code)
- `docs/grs/crm/EXIGENCES-SECRETARIAT-3EN1.md` (CRM-01..16, modules visibles, tous les rapports R-ENT/AR/STOCK/VENTES/AP/ACHATS/TAXES/EMPLOYÉS/COMPTABLE/PAIE
  sous-rapport par sous-rapport, ambiguïtés, 9 contrats de primitives manquantes, cadre des capacités d'agents)
- `docs/grs/crm/HANDOFF-CLAUDE-SONNET55.md` (ce fichier)
- `src/opsys/console/crm_ui.py` (routeur + rendu pur)
- `tests/test_console_crm.py`

Modifiés (tous sous `src/opsys/console/`, aucun fichier M3/M4/M5/M6/M8/M10, aucun contrat d'événement/auth/permission/DB)
- `src/opsys/console/application.py` : import `crm_ui` + `app.include_router(crm_ui.creer_router(...))` (mêmes callbacks que `reception_digest_ui`).
- `src/opsys/console/pages.py` : `("crm", "CRM")` ajouté à `ONGLETS` (2ᵉ position).
- `src/opsys/console/metier.py` : **à relire en priorité**. Ajout à la surface fermée `LECTURES` de trois lectures M2 (`m2_lister_leads`,
  `m2_trouver_client_de_lead`, `m2_obtenir_client_360`), nouveau `_LECTURES_ADMIN_M2`, union `_LECTURES_ADMIN` utilisée aux deux endroits où
  `_LECTURES_ADMIN_M9` décidait (exigence du rôle `admin` en base ; appel d'outil sous le rôle `admin`, jamais `nathan_owner` seul). Le message
  d'erreur devient « admin SQL requis pour les lectures M9 et M2 ». Ce n'est pas un changement de contrat d'auth du socle, mais c'est une
  extension de l'allowlist de la console : ROOT peut la refuser et déplacer l'appel dans `crm_ui` si préférable.

## 2. Choix de la tranche et pourquoi

**Répertoire (`/crm`) + dossier client/projet (`/crm/lead/{lead_id}`), lecture seule, sur la vérité M2.** C'est la seule surface qui (a) a des primitives
réelles (`m2_lister_leads`, `m2_trouver_client_de_lead`, `m2_obtenir_client_360`), (b) ne force aucune modification d'un département interdit,
(c) n'invente aucune donnée, (d) sert d'ancrage à CRM-05/06/08/09/10/11/12. La cédule (CRM-01) et l'agenda (CRM-03) sont bloqués faute de primitive
(`m4_lister_interventions.fenetre_planifiee` toujours nul ; aucun agenda) : contrats proposés dans EXIGENCES annexe A, **pas de stub codé**.

## 3. Comportement réel (attendu, non vérifié par exécution)

- `GET /crm?statut=<statut>&decalage=<n>` : appelle `m2_lister_leads` (20 par page, filtre statut, ordre « plus ancien d'abord » de M2). Tableau :
  dossier (lien), statut en toutes lettres, propriétaire, travaux, ville, reçu, dernière activité (heure de Montréal), prochaine action, segments.
  Pagination : « Page suivante » utilise le `suivant` renvoyé par M2 (pas de calcul local) ; « Revenir au début » ; message M2 et segments non calculables
  affichés tels quels (« aucune valeur devinée »). Paramètres inconnus/invalides → 400.
- `GET /crm/lead/{lead_id}` : `m2_trouver_client_de_lead` puis `m2_obtenir_client_360`. Affiche : contact du contrat ingéré (nom/courriel/téléphone/adresse
  si présents), tous les projets/opportunités du même client (liens), tableau des **9 sections de CRM-05** avec état réel
  (Affichée / Source existante pas encore branchée / Source partielle / Non disponible) et source de vérité, puis les Activités (≤ 10 interactions M2,
  tous projets confondus). « Vérification » n'est pas recopiée. Lead inconnu ou identifiant invalide → 404 sans écho.
- Sécurité : `session_page` (redirection connexion), rôle `owner|admin` puis **rôle `admin` exigé par `metier.executer`** (nathan_owner seul → 403 :
  les outils M2 n'ouvrent que `seller|admin`) ; aucun `appele_par_appareil(None)` ; pas d'écriture, pas de route POST/PUT/DELETE, pas de bouton d'envoi,
  pas de `mailto:` ; tout échappé par `pages.e` ; CSP/no-store inchangés ; erreurs sobres (403/404/400/503) sans détail interne.
- Aucune donnée stockée côté console ; aucun second CRM ; horodatage créé par le serveur (règle de `metier.executer`).

## 4. Limites connues

- **Pas de recherche** (la liste M2 ne porte ni nom ni client_id) ; **pas d'édition de coordonnées** ni de correction tracée (aucune primitive M2) → CRM-04 partiel.
- **Pas d'ajout de note** ni de pastille-note : `m2_enregistrer_interaction` existe (écriture T1) mais n'est pas branchée ; une écriture exige CSRF + `mutation_id`
  via `COMMANDES` — c'est la tranche suivante. Ambiguïté CRM-02 conservée.
- Les 8 autres sections du dossier **ne montrent aucune donnée** (soumissions M3, bons de travail M4, coûts/factures M5, bons de commande M6, fichiers M10) : elles
  disent leur état. Aucun `LECTURES` n'a été ajouté pour M3/M4/M5/M6/M10.
- Les activités sont celles du **client** (≤ 10), pas filtrées par lead ; le contact vient du premier contrat du client (comportement de M2).
- L'accès exige le rôle `admin` : la secrétaire n'a pas de rôle défini (décision ROOT : `admin` ou nouveau rôle ; EXIGENCES §4 point 7). Un vendeur (`seller`) n'a pas accès
  à la console (déjà le cas) : l'agenda/pipeline personnel du vendeur n'est pas livré.
- Pas de version JSON `/api/crm/*` (volontairement, pour borner la surface non testée).
- Vocabulaire des statuts dupliqué dans `crm_ui.STATUTS` (affichage) ; un test le compare à `m2_revenue_crm.statuts.STATUTS`.
- `.table-defilante` n'a pas de CSS (comme ailleurs) ; ressources CSS non modifiées. Mobile : non traité (dernière phase).
- Risques d'exécution à vérifier en premier (non éprouvés) : (1) le nom piégé `<script>` dans le contact fictif est-il accepté par la validation du contrat M2 ? sinon
  remplacer par un nom à entités (`Client &lt;b&gt;`) ; (2) `ingerer_lead` appelé dans `with session():` ; (3) format exact d'`ingere_le` (assertion `2026-09-01 09:00`) ;
  (4) `tableau_de_bord.nombre_en_attente` appelé dans `rendre`.

## 5. Tests proposés — NON EXÉCUTÉS

`tests/test_console_crm.py` (11 fonctions, 16 cas avec la paramétrisation) : accès (anonyme, employé, nathan_owner sans rôle admin → 403), onglet CRM + en-têtes, répertoire (liens, propriétaire, prochaine action,
heure de Montréal), filtre statut + paramètres invalides, pagination (pur), dossier (échappement XSS du contact et de la note, multi-projets, 9 sections, aucun faux bouton,
aucun nom d'outil), 404 sans fuite, lecture seule (instantané de toutes les tables avant/après), absence de route d'écriture (POST/PUT/DELETE → 404/405), alignement des statuts sur M2,
sections honnêtes, conversion America/Montreal.

Commandes ciblées pour ROOT (dans un venv `pip install -e ".[dev,postgres]"`) :

```bash
pytest tests/test_console_crm.py -q
pytest tests/test_console_metier.py tests/test_console_reception_digest.py tests/test_console.py -q          # non-régression console/nav/metier
pytest departments/m05-financecore/tests/test_outil_admission_paie_preparatoire.py -q                       # lit metier.LECTURES
pytest tests/test_console_bilan_suivis_m9.py tests/test_console_rapport_periode_m9.py -q                    # lectures M9 : rôle admin inchangé
ruff check src/opsys/console/crm_ui.py src/opsys/console/metier.py src/opsys/console/pages.py src/opsys/console/application.py tests/test_console_crm.py
```

## 6. Prochaine tranche précise (recommandée)

**T2 — Notes de dossier et soumissions en lecture** (toujours M2/M3, sans nouvelle primitive) :
1. Brancher `m2_enregistrer_interaction` (CRM-02/06 « Activités ») : formulaire POST avec CSRF, `mutation_id` côté serveur, auteur = session, limite 300 caractères affichée,
   ajout à `metier.COMMANDES`, test de rejeu idempotent et d'auteur non falsifiable. La pastille-note reste une hypothèse.
2. Ajouter `m3_lister_devis` / `m3_lire_devis` à `LECTURES` (vérifier d'abord son contrôle d'accès/rôle d'appareil) et remplir la section « Soumissions » (statut, montant fourni par M3,
   jamais recalculé).
3. Ensuite : `m4_lister_interventions` pour « Bons de travail » (sans fenêtre planifiée tant que M4 ne la publie pas), `m5_lire_rentabilite_chantier` / `m5_lire_comptes_a_recevoir` pour coûts et factures.
Parallèlement, demander à ROOT/M2 : `m2_rechercher_clients` et `m2_corriger_contact` (contrats EXIGENCES 3.3/3.4), et à M4 : `m4_lire_cedule_semaine` (3.1), prérequis de CRM-01/02/16.

## 7. Résumé des statuts (voir EXIGENCES pour le détail)

Livré-T1 partiel : CRM-04, CRM-05, CRM-06 (Activités en lecture). Existant sans écran : CRM-08, CRM-10, tout le catalogue de rapports qui a une primitive (comptes à recevoir/à payer,
rentabilité projet, trésorerie, taxes, paie préparatoire). Manquant (primitive à créer) : CRM-01 (fenêtre planifiée), CRM-03 (agenda), CRM-07 (modèles/clauses versionnés),
CRM-09 (note libre de PO), CRM-11 (correction de facture émise), CRM-14 (import de listes), CRM-15 (signature/documents RH), CRM-16 (journal quotidien), et la majorité des rapports comptables.
