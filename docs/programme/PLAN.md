# Plan d'exécution OPSYS-AI

Source du QUOI : [définition produit](../produit/DEFINITION-PRODUIT.md). Décision d'architecture :
[ADR-0008](../decisions/ADR-0008-fork-openclaw-opsys-core.md). Mode de travail : [BOUCLE.md](BOUCLE.md).

Règle d'ordre (définition §13 point 6, ADR-0008) : on livre par **tranches verticales rattachées aux
flux de §6**, jamais une couche d'infrastructure sans département qui s'en sert (§14.4).

Légende : `[x]` fait avec preuve · `[ ]` à faire · `BLOQUÉ :` raison · `GATE NATHAN` : décision ou
identifiants du propriétaire, repli livré en attendant.

## T0 — Fondations (le core et le socle, au service de T1)

- [x] T0.1 Définition produit injectée (`docs/produit/`, révision 3 annotée). Preuve : commit du 2026-09-28.
- [x] T0.2 ADR-0008 : fork dur d'OpenClaw, trois couches, points ouverts décidés. Preuve : même commit.
- [x] T0.3 Audits sans modification M1–M10 (`docs/departements/`) et études R11 (fork), R12 (mobile),
      R13 (socle métier) ; vérifier chaque sortie, puis détailler T1–T4 ci-dessous. Preuve : 13 documents
      commités, suites de tests des départements vertes pendant les audits, constats intégrés ci-dessous.
- [x] T0.4 Import du fork : instantané de `v2026.9.6` (commit `eb377ac5`) dans `core/`,
      `core/NOTICE` (MIT, © OpenClaw Foundation), `core/PROVENANCE.md` ; retrait de `core/UPSTREAM.md`.
      Preuve : `ls-remote` confirme le tag (`ce5bbdc2`, pointant sur `eb377ac5`) ; l'élagage rejoué
      depuis le tag (`outils/fork/elaguer_core.py`) redonne exactement les 36 213 fichiers suivis de
      `core/`, octet pour octet, sauf `pnpm-lock.yaml` (régénéré sans script de paquet) ; fermeture des
      dépendances de workspace vérifiée ; aucun fichier de plus de 5 Mo, aucun LFS.
- [ ] T0.5 CI du core : job GitHub qui installe Node et pnpm, construit et teste le core tel
      qu'importé (référence verte avant toute modification). En cours : `.github/workflows/core.yml`
      (Node 24, pnpm 12.4, `pnpm build`, `pnpm test:fast`, réglages de la CI d'origine) ; la release
      intacte s'est construite en 9 min ; il construit maintenant `core/`.
- [ ] T0.6 Élagage selon R11 (canaux et fournisseurs inutiles, docs, apps natives…), CI verte.
      Fait à l'import (T0.4) : apps, docs, 120 extensions. Reste : `scripts/` et `test/` qui visent
      des chemins élagués (scripts iOS, Android et macOS orphelins, R14), guidé par la CI du core.
- [ ] T0.7 Renommage OpenClaw → OPSYS en quatre lots (R14), CI verte à chaque lot. L'API interne
      du fork (`openclaw/plugin-sdk/*`, `@openclaw/*`, `OPENCLAW_*`) reste telle quelle (R14, décision 2).
  - [ ] Lot 1 : marque visible (interface, locales `fr-CA` par défaut et glossaires, invites système,
        bannière, notifications) et les 539 assertions qui la figent.
  - [ ] Lot 2 : une seule commande `opsys` (le core, alias `openclaw`), `opsys metier` pour le moteur
        Python (renommé `opsys-metier`) ; AGENTS.md et CI mis à jour.
  - [ ] Lot 3 : dossier d'instance `~/.opsys` (état du core dans `core/`), `opsys.json`, anciens noms
        relus par la migration Doctor existante.
  - [ ] Lot 4 : services système `opsys-gateway`, anciens noms nettoyés.
- [x] T0.8 ADR-0009 socle métier (base de données, événements, workflows à validation humaine,
      RBAC, audit, observabilité) d'après R13. Doit unifier les échelles d'autonomie aujourd'hui
      disjointes : N0–N5 (définition), T0–T3 (socle), F0–F7 (M5), niveaux 0–6 (M7) (audit M5).
      Preuve : `docs/decisions/ADR-0009-socle-metier.md` (SQLite par défaut, PostgreSQL en option,
      une transaction métier + événement + audit, échelle N unique, rôles P8).
- [x] T0.9 ADR-0010 mémoire (RAM par moteur de contexte, M10 gouvernance, RAG d'entreprise)
      d'après l'audit M10 : RAM dans `assemble()`, PREFLIGHT/POSTFLIGHT sur les hooks du core,
      registre M10 = validation au-dessus de la mémoire d'entreprise, SQLite + FTS5 + sqlite-vec par
      défaut, embedding local partagé.
      Preuve : `docs/decisions/ADR-0010-memoire.md`.
- [x] T0.14 Cloisonnement de la mémoire des agents : désactiver le partage entre agents de
      département (`tools.agentToAgent`, actif par défaut) et écrire la configuration mémoire des
      agents (embeddings, dreaming, provenance) (ADR-0010, audit M10).
      Preuve (commit 8c1cc41) :
      - `tools.agentToAgent.enabled=false` ;
      - `tools.sessions.visibility="tree"`, la valeur la plus restrictive qui garde les sous-agents
        natifs (lu dans `session-visibility-internal.ts`) ;
      - `memory.search` en `openai-compatible` depuis `OPSYS_EMBEDDINGS_*`, fail-closed si absent ;
      - dreaming au fuseau des automatisations ;
      - la provenance n'est pas configurable : structurelle au plugin.

      Résultats : 20 tests, dont chaque clé retrouvée dans le schéma du fork ; socle 208 verts ;
      verifier OK.
- [ ] T0.10 Superviseur : le core lance et surveille le moteur métier Python (via `uv`), santé et
      journaux unifiés, une seule authentification.
- [x] T0.12 M3 : l'outillage de mutation (`tests/outils_preuve/muter_*.py`) travaille sur une copie
      temporaire, jamais sur la vraie source. Une exécution tuée avait laissé une mutation dans
      `blocage_prix.py`, et elle a été commitée par erreur (899bbad). Elle est corrigée par 7ad0377.
      Preuve (96ebd73) : `EnvironnementMutation` copie le département, lie les voisins en lecture
      seule et ne les supprime jamais. Preuves structurelle (AST) et dynamique (SHA-256 de `src/`).
      La suite M3 donne 583 réussis ; l'empreinte de `src/` est identique avant et après la batterie.
- [ ] T0.11 Installateur en une commande (dérivé de `install.sh` / `install.ps1`), désinstallation
      et export documentés ; Docker Compose en option serveur.

- [ ] T0.13 Taxonomie métier partagée : M1, M2 et M3 utilisent un même `TYPES_TRAVAUX` qui ne
      contient aucun des 4 services réels (gouttières, revêtement, soffite-fascia, réparation). Une
      seule taxonomie, dans le socle, paramétrable par le profil d'entreprise (audits M1, M2, M3).

## T1 — « Travaux terminés » : la chorégraphie centrale (§6, §9.7)

Première tranche métier : elle traverse neuf départements et l'app mobile.

- [x] T1.0-a Socle de stockage `opsys.stockage` (ADR-0009) : base de l'instance SQLite ou PostgreSQL,
      transaction par appel d'outil avec points de sauvegarde (`executer_atomique` dans `Capacites` et
      les approbations), codec JSON typé, maillons durables « comme une liste », migrations Alembic au
      démarrage, `opsys base migrer|etat`. Preuve : `pytest tests/test_stockage.py` 11 verts (dont
      PostgreSQL réel), socle 188 verts.
- [x] T1.0-b Registres des départements branchés sur `opsys.stockage.maillons` (M1, M2, M3, M4, M5, M6,
      M8, M9, M10), état dérivé recalculé au chargement, non-régression des hash mémoire contre base.
      Preuve : commits 3ab2cc3 à bd689e9, puis cd55663 pour M3. Chaque département a un
      `test_registre_durable.py` qui couvre :
      - les mêmes hash en mémoire et en base ;
      - la relecture par une nouvelle instance ;
      - la détection d'une altération SQL.

      Suites vertes : M1 369, M2 566, M3 583, M4 455, M5 183, M6 163, M8 113, M9 92, M10 191.

      Règles communes :
      - durable par défaut, relu à chaque appel, aucune base ouverte au chargement ;
      - réponses sans historique complet (tête et taille) ;
      - tests unitaires en mémoire ou sur une base temporaire, jamais `~/.opsys`.
- [x] T1.0-c Plan de contrôle (`etat.db` : approbations, journal, usage, modes) migré dans la base de
      l'instance, pour que décision humaine et exécution soient dans la même transaction.
      - `etat.session` devient un alias de `stockage.transaction`.
      - `decider` réserve la demande, exécute l'outil par `executer_atomique` (point de sauvegarde),
        puis clôt le statut, le tout dans cette seule transaction.
      - Migration 0002, dont la rétrogradation est refusée.
      - L'ancien `etat.db` est importé une fois, puis renommé et jamais supprimé (T3).

      Preuve : `pytest tests` 202 verts, dont l'atomicité, la panne après réservation, deux décisions
      concurrentes, l'import de l'ancien `etat.db` et la parité PostgreSQL réelle ; `ruff` propre ;
      `opsys verifier` OK. Code critique : revue externe requise avant `main`.

      Réserve pour T1.2 : l'outil approuvé s'exécute dans la transaction et garde le verrou
      d'écriture. Un effet externe (SMS, courriel, paiement) passe donc par l'outbox, jamais dans la
      transaction.
- [ ] T1.1 Données et API : jobs et machine à états (M4), sessions de travail et punch (M4.4),
      matériaux prévus et utilisés (M6.10–M6.12), facture brouillon (M5.2), activité client (M2).
      Analyse d'écart du 2026-09-28 (définition §6, §7, §9.7 contre le code) ; la cascade entre
      départements reste T1.2.
  - [x] T1.1-a M2 (une correction, donc en premier) :
        - « converti » est terminal et interdit toute interaction, alors que §6 exige qu'après le
          chantier M2 écrive l'activité et la prochaine action ;
        - statuts après conversion (`chantier_en_cours`, `chantier_termine`, `facture_envoyee`,
          `payee`) ;
        - `m2_marquer_chantier_termine` : prochaine action fournie par l'appelant, fail-closed ;
        - dépendance à M4.

        Preuve (7ddd751) :
        - statuts `cedule`, `chantier`, `facture`, `paiement`, `avis` (définition l. 319) ; seul
          `perdu` reste terminal ; le retour de « converti » vers `nouveau` ou `qualifie` reste
          interdit ;
        - la prochaine action est exigée dans la transition elle-même ;
        - deux maillons, tout ou rien ;
        - 581 tests M2, 80 outils.

        Le cycle de dépendances M2 → M4 → M3 → M2 est sans effet : les dépendances ne servent
        qu'à vérifier l'existence ; c'est une boucle de rétroaction voulue (§6).
  - [ ] T1.1-b M4 :
        - `devis_id` réel propagé jusqu'au WCT (toujours `None` aujourd'hui) ;
        - complétion `completed_pending_review` ou `completed_verified`, selon un `ecart_detecte`
          explicite ;
        - contrat `PreuvesCompletion` (checklist, photos après, notes, signature), fail-closed ;
        - `m4_lister_interventions` en lecture.
  - [ ] T1.1-c M4.4 :
        - pauses (`pause_debut`, `pause_fin`) et temps de déplacement distinct ;
        - `m4_produire_brouillon_temps` : minutes par technicien et chantier, aucun taux ni montant ;
        - dépassement signalé sur un seuil fourni par l'appelant.
  - [ ] T1.1-d M6 :
        - formulaire de fin de chantier enrichi (prévu, non prévu, retour, perte, bris, achat
          terrain avec photo ou reçu) ;
        - `variance_chantier.py`, prévu contre réel, distinct de la variance d'inventaire ;
        - les 6 causes de §7 M6.12, jamais attribuées seules ;
        - signal d'écart critique sur un seuil fourni par l'appelant.

        Fait (5488b49) : formulaire validé (`REJ-ACHAT-TERRAIN-PREUVE-MANQUANTE`), verdicts neutres,
        `cause_possible` toujours nul avec `classification_requise`, signal sur seuil,
        `m6_evaluer_variance_chantier` (T0). 213 tests.

        Reste (T1.1-d2) :
        - persister la déclaration en mouvements typés, tout ou rien, par le chemin d'écriture
          autorisé ;
        - `m6_declarer_materiaux_utilises` ;
        - la variance lit le réel persisté ;
        - idempotence par `wct_id`.
  - [x] T1.1-e M5 :
        - `FactureBrouillonV1` sur un registre dédié, idempotente par `devis_id` ;
        - aucun `ENCAISSEMENT` avant `PAYEE` ;
        - `m5_creer_facture_brouillon` ;
        - âge des créances ;
        - envoi seulement par approbation F4 ; `PAYEE` seulement par un approbateur humain (T3).

        Preuve (7493ca5, puis la garde de non-exposition) :
        - totaux et taxes recalculés, un total fourni divergent est rejeté ;
        - 17 codes `REJ-FACTURE-*` et `REJ-CREANCES-*` ;
        - le piège de l'ENCAISSEMENT est testé en pur et sur la base réelle ;
        - 272 tests M5, 79 outils.

        Code critique, revue externe requise. Envoi et paiement non exposés tant que T1.3 ne les
        met pas derrière les approbations du socle.
- [ ] T1.2 Événements : l'événement de fin de travaux de M4 porte les montants (M5) et les champs
      marketing (photos, ville, consentement : M7) ; M3 et M9 la reçoivent en second ordre (M6/M5 et
      M8, ADR-0009) (audits M4, M5, M7). `job.completed` déclenche la cascade (M6 variance, M5 facture brouillon, M2
      activité et prochaine action, M7 demande d'avis, M3 estimé vs réel, M8 métriques, M10 mémoire).
- [ ] T1.3 Approbations N3–N4 (complétion, facture, écart matériaux), file du propriétaire.
      Envoi et paiement de facture exposés en T3 seulement, par les approbations du socle : la
      vérification de forme du maillon F4 de `facturation.envoyer_facture` ne suffit pas seule.
      Les approbations internes de M5 (F0–F7) rejoignent l'échelle unique (ADR-0009).
- [ ] T1.4 App mobile Expo : squelette, appairage, profils, punch, chantier du jour, « Terminer »,
      formulaire des matériaux, hors ligne ; approbations côté propriétaire. Pile et ordre de livraison :
      R12 (Expo SDK 57, expo-sqlite + file sortante maison, client de protocole TypeScript du core,
      `POST /tools/invoke` sans tour de modèle). Rôles d'opérateur nommés dans le core d'abord : le jeton
      partagé d'OpenClaw donne un accès complet (R12). Réécrire `docs/architecture/MOBILE.md` (périmé).
- [ ] T1.5 E2E : travaux terminés normaux ; écart de 40 % → `completed_pending_review` et alerte
      sur le mobile de l'admin.

## T2 — Du lead à la soumission (§6, flux principal)

- [ ] T2.1 M1 : intake omnicanal par les canaux du core, qualification, appel manqué. Câbler les
      extensions du fork (`voice-call` Twilio, `sms`, `imap`, `tts-local-cli`) au lieu de reconstruire la
      voix ; taxonomie des 4 services réels (gouttières, revêtement, soffite-fascia, réparation) ; contrat
      M1→M2 avec `source`, `utm`, `campagne` ; tests qui passent par `Capacites` (approbations réelles)
      (audit M1).
- [ ] T2.2 M2 : lead structuré, Client 360, préparation à l'estimation, prochaine action.
- [ ] T2.3 M3 : estimation honnête, soumission brouillon, approbation, besoins matériaux vers M6.
      L'outil `m3_estimer_projet` n'assemble que 6 des 15 modules : écrire l'orchestrateur qui compose
      validation, devis (`devis_id` requis par M4), registre estimé vs réel, signal de relance M2, et
      émet `REFERENCE_ECHELLE_ABSENTE` en alerte non bloquante ; séparer coût et prix (taux de marge
      fourni, jamais codé en dur) ; contrat `BesoinsMateriauxM3` ; soumission brouillon PDF ; politique
      Loi 25 « photos » avant toute collecte réelle (audit M3).
- [ ] T2.4 M6 : catalogue, livre de prix, PO brouillon, courriel fournisseur via M1 (repli manuel).
- [ ] T2.5 M6 : lever la décision interne DA-M6-12 (« M6 ne persiste pas les PO »), contraire à la
      définition (moteur de PO à 12 statuts) ; ajouter le moteur de variance estimé M3 vs réel M4, distinct
      de la variance d'inventaire physique existante ; registre des fournisseurs (Gentek, Royal, O.A.M.,
      Kaycan) (audit M6).

## T3 — Mesure, direction, mémoire

- [ ] T3.1 M8 : registre de métriques, qualité et fraîcheur, alertes qui proposent une action.
- [ ] T3.4 M8 : la garde de devise ne contrôle que les unités « DEVISE/x » ; une unité nue non CAD
      (ex. « USD ») passe. Correction TDD (audit M8, vérifié dans `dictionnaire.py`).
- [ ] T3.2 M9 : briefing du matin sourcé, décisions en attente sur mobile.
- [ ] T3.3 M10 : paquets de contexte en couches, consolidation nocturne, audit « non-oubli ».

## T4 — Profondeur des départements

Détaillée à partir des audits (T0.3) : voix M1 par étapes, CFO IA M5, usine à contenu M7, VRP,
météo et GPS M4, vision M3, conseil d'agents M9…

- [ ] T4.1 M4 : la cédule trie sur un hachage de ville, sans sens géographique ; la remplacer par
      de vraies coordonnées et un VRP (audit M4).
- [ ] T4.2 M4 : consentement et rétention du GPS (`POLITIQUE-geolocalisation.md`) non câblés dans
      le pointage (audit M4) ; bloquant avant tout GPS continu.
- [ ] T4.3 M7 : consentement client et floutage visages et plaques avant tout contenu public ;
      profil de marque par défaut remplacé par celui du client (audit M7).

## T5 — Durcissement et SaaS

Secrets chiffrés, RBAC par métrique, Loi 25 (consentements, rétention, export, effacement),
multi-instances, sauvegardes, observabilité, veille de sécurité du fork (mensuelle).

- [ ] T5.1 Lint des départements : `ruff` ne couvre aujourd'hui que le socle (`src`, `tests`) ; l'audit M1
      relève 122 avertissements dans M1. Étendre la CI aux départements après correction.

## Décisions attendues de Nathan (GATE NATHAN, ne bloquent pas la boucle)

- Nom commercial : « Gouttières et Revêtements Synergy » ou « … Lanaudière » (définition §13.4).
- Portée SaaS de M5 (§13.8).
- Licence d'OPSYS (`LICENSE` Apache-2.0 ou propriétaire, ADR-0003).
- Identifiants : Twilio, QuickBooks, CCube, Stripe, Plaid, Google (Ads, Search Console, Business
  Profile), Meta, TikTok, LinkedIn, YouTube.
- Rotation de la clé fuitée (#612).
- **Géolocalisation** : `POLITIQUE-geolocalisation.md` interdit tout suivi continu (points au punch
  seulement) alors que la définition §9.2 prévoit la localisation en arrière-plan pendant le travail.
  Proposition R12 : arrière-plan seulement pendant la fenêtre « en route » d'un chantier. À valider
  (Nathan ou juriste) avant toute livraison du GPS. Même besoin : une politique pour les photos et les
  signatures.
- **Prompts maîtres d'origine des départements** (annexe A de la définition) : ils portent le
  détail fonctionnel (routes, tables, KPI, scénarios de test). Exemple : les 21 sections du rapport
  de décision M9, dont la définition ne liste qu'une douzaine (audit M9).
