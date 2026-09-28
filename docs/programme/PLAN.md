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

      Avancement :
      - run 7 (555828a) : **construction du fork élagué verte** (12 min) ;
      - tests découpés en six morceaux : le morceau 6 est vert ; les autres échouent encore sur des
        tests liés au code élagué (par exemple les chemins de config du plugin codex, ou un
        propriétaire de manifeste pour le banc d'inférence), traités par T0.6 ;
      - run 10 (9b34a6d) : construction verte et morceaux 1, 2, 4 et 6 verts. Il reste 3 tests :
        - un import `fs` retiré à tort ;
        - un cas de tarification (« native owner ») ;
        - le nettoyage ACP « live Gateway ownership », en échec identique aux runs 9 et 10 ;
      - run 11 (e3c4151) : seul ce cas ACP échoue encore ;
      - run 12 (2474cd1) : CI entièrement verte, mais seulement parce que ce cas active la
        journalisation verbeuse. Ce vert n'est pas retenu comme preuve : la journalisation change
        le minutage, et l'on soupçonne une écriture tardive qui recrée la session supprimée. La
        correction à la source est en cours (T0.6).
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
- [x] T1.1 Données et API : jobs et machine à états (M4), sessions de travail et punch (M4.4),
      matériaux prévus et utilisés (M6.10–M6.12), facture brouillon (M5.2), activité client (M2).
      Preuve : les sous-tâches a à e ci-dessous. Socle 222, 83 outils. Suites :
      M2 581, M4 585, M5 272, M6 242.
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
  - [x] T1.1-b M4 :
        - `devis_id` réel propagé jusqu'au WCT (toujours `None` aujourd'hui) ;
        - complétion `completed_pending_review` ou `completed_verified`, selon un `ecart_detecte`
          explicite ;
        - contrat `PreuvesCompletion` (checklist, photos après, notes, signature), fail-closed ;
        - `m4_lister_interventions` en lecture.
  - [x] T1.1-c M4.4 :
        - pauses (`pause_debut`, `pause_fin`) et temps de déplacement distinct ;
        - `m4_produire_brouillon_temps` : minutes par technicien et chantier, aucun taux ni montant ;
        - dépassement signalé sur un seuil fourni par l'appelant.

        Preuve de T1.1-b et T1.1-c (f148950 et 19a99e6, puis le correctif de l'outil) :
        - `devis_id` porté de l'inscription au WCT ;
        - `terminee` scindé en `completed_pending_review` et `completed_verified` (paramètre
          explicite, sans défaut) ;
        - `PreuvesCompletion` validé avant toute écriture ;
        - pauses et déplacement ;
        - `temps.py` gardé contre tout montant ;
        - `m4_lister_interventions` et `m4_produire_brouillon_temps` (T0) ;
        - 585 tests M4, 83 outils.

        Un agent n'obtient jamais `completed_verified` : l'outil complète toujours en revue.
  - [x] T1.1-d M6 :
        - formulaire de fin de chantier enrichi (prévu, non prévu, retour, perte, bris, achat
          terrain avec photo ou reçu) ;
        - `variance_chantier.py`, prévu contre réel, distinct de la variance d'inventaire ;
        - les 6 causes de §7 M6.12, jamais attribuées seules ;
        - signal d'écart critique sur un seuil fourni par l'appelant.

        Fait (5488b49) : formulaire validé (`REJ-ACHAT-TERRAIN-PREUVE-MANQUANTE`), verdicts neutres,
        `cause_possible` toujours nul avec `classification_requise`, signal sur seuil,
        `m6_evaluer_variance_chantier` (T0). 213 tests.

        T1.1-d2 fait (cea3b64) :
        - la déclaration est persistée en `CONSOMMATION`, `RETOUR`, `PERTE` et `BRIS`, tout ou
          rien, par la garde d'écriture autorisée ;
        - même règle de coût fail-closed ;
        - `wct_id` est optionnel dans le maillon : absent, le hash est inchangé bit à bit ;
        - `m6_declarer_materiaux_utilises` (T1) ;
        - la variance relit le réel en base ;
        - `REJ-DECLARATION-DEJA-SOUMISE`.

        242 tests M6, 81 outils.
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
- [ ] T1.2 Événements (`completed_verified` calculé par le code : preuves complètes et aucune variance
      critique de M6 pour ce WCT ; sinon, revue humaine en T1.3) : l'événement de fin de travaux de M4 porte les montants (M5) et les champs
      marketing (photos, ville, consentement : M7) ; M3 et M9 la reçoivent en second ordre (M6/M5 et
      M8, ADR-0009) (audits M4, M5, M7). `job.completed` déclenche la cascade (M6 variance, M5 facture brouillon, M2
      activité et prochaine action, M7 demande d'avis, M3 estimé vs réel, M8 métriques, M10 mémoire).
  - [x] T1.2-a Socle, bus d'événements (ADR-0009 §3) :
        - `evenements_sortants` et `evenements_recus`, avec l'unicité (événement, consommateur),
          migration 0003 ;
        - `publier()` dans la transaction métier ;
        - catalogue JSON Schema `opsys.evenement/v1` ;
        - consommateurs déclarés par les départements et vérifiés par `opsys verifier` ;
        - répartiteur idempotent : réessais espacés, quarantaine, sondage de secours ;
        - `opsys evenements etat|repartir` ;
        - parité PostgreSQL.

        Preuve (aee1041) :
        - chaque paire (événement, consommateur) est livrée dans sa propre transaction et réclamée
          sous verrou ;
        - un échec annule les écritures mais garde le reçu ; réessai après `2**n` s, quarantaine au
          5e échec ;
        - `m4.travaux_termines` : 13 champs requis égaux au WCT, champs optionnels de M7 cités de
          l'audit ;
        - socle 252 verts, dont PostgreSQL réel ; verifier « événements cohérents ».
  - [x] T2.3-a (préalable à T1.2-d, extrait de T2.3) M3, devis durable :
        - lignes, coût et prix calculés par le code, avec un taux de marge fourni, jamais codé en
          dur ;
        - statuts brouillon, envoyé et accepté ; l'envoi est derrière une approbation ;
        - lecture par `devis_id`, pour M5 (facture) et M4 (`devis_id` du WCT).

        Preuve (f793ff1) :
        - registre durable `devis`, distinct du registre des estimations ;
        - montants en `Decimal` à partir de texte, arrondis `ROUND_HALF_UP` ;
        - trois outils : `m3_creer_devis` (T1), `m3_lire_devis` (T0), `m3_marquer_devis_accepte`
          (T3, un humain constate l'acceptation) ; aucun outil d'envoi exposé ;
        - `m3.devis_accepte` publié dans la même transaction ; un échec après l'acceptation annule
          aussi l'écriture ;
        - `role="employe"` retire coût, marge et prix ;
        - suite M3 : 652 réussis ; socle 252 ; verifier « 87 outils, événements cohérents ».

        À suivre (T1.2-d) :
        - prix unitaire arrondi avant la multiplication, comme la facture M5 le recalcule ;
        - `reference_ligne`, `prix_unitaire` et `prix_ligne` par ligne dans l'événement ;
        - `horodatage_acceptation` ;
        - `evenement_id` déterministe.
  - [x] T1.2-b M4 : publier `m4.travaux_termines/v1` avec le WCT, dans la même transaction ; porter
        dans la charge ce que les audits M5 et M7 exigent. Passer de `completed_pending_review` à
        `completed_verified` quand le code a sa base : preuves complètes et variance M6 sans signal
        critique.

        Preuve (9ab0894, 96bc031, 8991331, f885bf3) :
        - M4 publie le WCT dans la transaction de la complétion (`evenement_id` = `wct_id`) ;
        - M6 garde le prévu (`m6_enregistrer_besoins_prevus`, T1), consomme la complétion et
          publie `m6.variance_chantier` (`evaluee`, `prevu_absent`, `declaration_absente` ou
          `seuil_absent`), avec le détail par matériau quand elle est évaluée ;
        - une déclaration ou un prévu arrivé après la complétion relance l'évaluation, sous un id
          qui encode l'état ; `evaluee` est terminal ;
        - M4 passe à `completed_verified` seulement sur `evaluee` sans signal critique ; un écart
          de 40 % reste en revue ;
        - suites : M4 611, M6 279, M2 589, M10 194 ; socle 253 ; verifier « événements
          cohérents ».
  - [x] T1.2-c Consommateurs de premier ordre :
        - M2 : activité et prochaine action, par une table de règles déterministe ;
        - M10 : mémoire du WCT ;
        - M8 : métriques ;
        - M7 : demande d'avis, soumise au consentement.

        Preuve :
        - M2 (1a5ed10) : avance jusqu'au chantier, puis `marquer_chantier_termine` ; prochaine
          action par une table de règles citée ; lead introuvable mis en quarantaine ;
        - M10 : WCT mémorisé ;
        - M8 (99a5dcb) : faits mesurés, sans coût ;
        - M7 : brouillon de demande d'avis seulement avec le consentement, jamais d'envoi.

        Suites : M2 589, M7 503, M8 116, M10 194.

        À suivre : le répartiteur transmet la charge, mais pas la provenance (`evenement_id`,
        producteur). M10 déduit l'identifiant du `wct_id` ; il faudrait passer la provenance aux
        consommateurs qui la demandent.
  - [x] T1.2-d Consommateurs à données amont :
        - M6 : variance, où un prévu absent donne un verdict qui le demande ;
        - M5 : facture brouillon, où des lignes de devis absentes donnent un verdict qui les
          demande, jamais un montant inventé ;
        - M3, en second ordre : estimé contre réel.

        Preuve :
        - M6 (7f78797) : le prévu vient de `m3.devis_accepte`. Un devis sans matériau est un prévu
          vide connu, jamais un prévu absent. Un chantier nul se résout depuis la déclaration ;
        - M5 (119a594, 23df6eb) :
          - arrondi `ROUND_HALF_UP` cité (ARC RC4022, Revenu Québec) ;
          - facture brouillon quel que soit l'ordre d'arrivée, montant égal au prix du devis ;
          - attentes nommées ;
        - M3 (50b88da, 2d7b17f) : prix unitaire arrondi comme la facture ; estimé contre réel
          (écart relatif signé, aucun barème ajusté) ;
        - socle (4c9fbff) : toute charge du bus est validée par son JSON Schema complet. Un coût
          par ligne de devis ne peut plus sortir de M3 ;
        - suites : M3 698, M5 290, M6 291, M4 611 ; socle 275.
  - [ ] T1.2-e Test de bout en bout : de la complétion jusqu'à la cascade, avec une relivraison
        idempotente et un consommateur en échec mis en quarantaine sans bloquer les autres.
- [ ] T1.3 Approbations N3–N4 (complétion, facture, écart matériaux), file du propriétaire.
      Envoi et paiement de facture exposés en T3 seulement, par les approbations du socle : la
      vérification de forme du maillon F4 de `facturation.envoyer_facture` ne suffit pas seule.
      Les approbations internes de M5 (F0–F7) rejoignent l'échelle unique (ADR-0009).
  - [ ] T1.3-a Socle (ADR-0009 §4 et §5) :
    - échelle unique N0–N5, avec la correspondance T et F ;
    - décision signée par une personne et son rôle, jamais un mot de passe partagé ;
    - rôles approbateurs de chaque niveau N déclarés dans `department.yaml` ;
    - N5 exige la signature de `nathan_owner` et l'attestation du professionnel ;
    - file du propriétaire, par CLI et console : demandes du socle plus attentes déclarées par
      les départements.
  - [ ] T1.3-b M4 : revue humaine d'une complétion `completed_pending_review` (vérifiée ou
        corrigée), décision signée ; l'alerte d'écart matériaux (signal critique M6) entre dans
        la file.
  - [ ] T1.3-c M5 :
    - envoi et paiement de facture par les approbations du socle ;
    - attentes de facturation dans la file ;
    - les approbations internes F0–F7 rejoignent l'échelle unique.
- [ ] T1.4 App mobile Expo : squelette, appairage, profils, punch, chantier du jour, « Terminer »,
      formulaire des matériaux, hors ligne ; approbations côté propriétaire. Pile et ordre de livraison :
      R12 (Expo SDK 57, expo-sqlite + file sortante maison, client de protocole TypeScript du core,
      `POST /tools/invoke` sans tour de modèle). Rôles d'opérateur nommés dans le core d'abord : le jeton
      partagé d'OpenClaw donne un accès complet (R12). Réécrire `docs/architecture/MOBILE.md` (périmé).
  - [x] T1.4-a Squelette `mobile/` (R12 §5, étape 1) :
    - Expo SDK 57, Expo Router et TypeScript strict ; i18n fr-CA ;
    - groupes de routes par rôle, gardés par une fonction pure testée ;
    - file sortante (R12 §4) en logique pure testée, avec un adaptateur expo-sqlite :
      - `mutation_id` créé sur l'appareil ;
      - statuts ;
      - recul de 1 s à 30 s ;
      - `depends_on` ;
      - reprise avec la même clé ;
    - client typé de `POST /tools/invoke` ;
    - job CI `mobile` (tsc, jest) ;
    - `MOBILE.md` réécrit et briques inscrites dans INGREDIENTS.md.

    Aucun écran métier.

    Preuve (a6964d6, 5b8896c) :
    - versions de R12 §3 vérifiées une à une, sans écart ;
    - licences lues dans chaque `LICENSE` (MIT, TypeScript Apache-2.0) ;
    - file sortante :
      - recul appliqué à la sélection ;
      - ordre par `sequence` monotone, sûr au changement d'heure ;
      - mutations bloquées par un ancêtre en échec définitif identifiées ;
    - client `/tools/invoke` conforme au code du fork ;
    - typecheck propre, Jest 169 réussis ; CI `mobile` verte sur GitHub.

  - [x] T1.4-b Socle : idempotence des mutations d'appareil.
    - Table `mutations_appliquees`, de clé `(appareil, idempotencyKey)`.
    - Un renvoi rejoue le même résultat, dans la même transaction que l'outil.
    - L'heure du serveur fait foi ; celle de l'appareil est gardée à côté.
    - Le chemin de la clé, du core jusqu'au moteur, est établi en lisant le code du fork
      (`/tools/invoke`, client MCP).

    Preuve (764c292, 2474cd1) :
    - la clé voyage dans le `_meta` MCP (`opsys/idempotencyKey`, `opsys/appareil`,
      `opsys/horodatageAppareil`), jamais dans les arguments ;
    - réclamation et exécution dans une seule transaction, migration `0004` ;
    - un renvoi rejoue la réponse, et une clé réutilisée pour un autre outil ou d'autres arguments
      est refusée (`mutation_conflit`) ;
    - une panne interne ou un refus passager n'est pas enregistré ;
    - un appel d'appareil n'est pas soumis au budget de jetons ;
    - concurrence : une seule exécution (SQLite et PostgreSQL réels) ;
    - heure de réception exposée par `contexte.horodatage_reception()` ;
    - changement requis dans le core documenté (`IDEMPOTENCE.md` §7) ;
    - socle 275.

  - [ ] T1.4-c Core, après T0.5 (CI du core verte) :
    - rôles d'opérateur nommés (`admin`, `employee`, `seller`) sur le jeton d'appareil ;
    - portées d'outils par rôle ;
    - le rôle d'une projection vient de l'identité authentifiée, jamais d'un paramètre de l'appelant.
      Exemple : `m3_lire_devis(role=...)` retire coût, marge et prix pour un employé, mais c'est
      aujourd'hui l'appelant qui choisit le rôle ;
    - appairage mobile, avec l'algorithme de signature lu dans le fork.
  - [ ] T1.4-d `punch.tsx` (M4.4) de bout en bout par la file sortante (R12 §5, étape 2).
  - [ ] T1.4-e Chantier du jour, transitions, checklist, photos et signature (étapes 3 et 4).
  - [ ] T1.4-f « Terminer », qui lance la cascade §9.7, puis le formulaire des matériaux (étape 5).
    Approbations côté propriétaire après T1.3 (étape 6).
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

- [x] T3.1 M8 : registre de métriques, qualité et fraîcheur, alertes qui proposent une action.
      Preuve (c8d515e) :
      - registre des définitions versionné et durable, unité validée par le dictionnaire ;
      - qualité calculée par le code : donnée absente (verdict nommé), fraîcheur, plage ;
      - alertes structurées (quoi, à qui, pourquoi, preuve), jamais exécutées ;
      - 3 outils : `m8_enregistrer_definition_metrique` (T1), `m8_resoudre_definition_metrique`
        et `m8_evaluer_qualite_metrique` (T0) ;
      - M8 202, M9 92, verifier 90 outils.
  - [ ] T3.1-suite : règles d'unicité et de cohérence entre tables ; alertes dans le digest
        quotidien ; listage compact du registre.
- [x] T3.4 M8 : la garde de devise ne contrôle que les unités « DEVISE/x » ; une unité nue non CAD
      (ex. « USD ») passe. Correction TDD (audit M8, vérifié dans `dictionnaire.py`).
      Preuve (988c62d) :
      - unité nue ou préfixée, sans égard à la casse, comparée aux 178 codes ISO 4217 actifs ;
      - verdict `REJ-DEVISE-NON-AUTORISEE` ;
      - aucun faux positif sur toutes les unités du dictionnaire réel.
- [ ] T3.2 M9 : briefing du matin sourcé, décisions en attente sur mobile.
- [x] T3.3 M10 : paquets de contexte en couches, consolidation nocturne, audit « non-oubli ».
      Preuve (d239485) :
      - paquet en 4 couches avec provenance, budget calculé par le code, troncature déclarée ;
      - consolidation idempotente par (affaire, jour), `maintenant` fourni ;
      - audit des faits attendus et des deux chaînes de hachage ;
      - consommation de `m6.variance_chantier` ;
      - M10 263, verifier 93 outils.
  - [ ] T3.3-suite : greffe du moteur de contexte dans le core (PREFLIGHT et POSTFLIGHT) ;
        résolution des signaux critiques ; paquet injecté avant une estimation M3.

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
- **Seuils métier** (définition §13.11) : M6 démarre avec un seuil de variance de chantier de
  30 % (`department.yaml`, `configuration`). La valeur est à confirmer par le propriétaire, et elle
  deviendra un réglage par instance (tableau de bord).
- **Arrondi monétaire** : M5 arrondissait au pair (mode par défaut de Python) alors que M3
  arrondit au demi supérieur. La correction cite la règle de l'ARC (TPS) et de Revenu Québec
  (TVQ) ; elle passera par la revue externe du code critique.
- **Géolocalisation** : `POLITIQUE-geolocalisation.md` interdit tout suivi continu (points au punch
  seulement) alors que la définition §9.2 prévoit la localisation en arrière-plan pendant le travail.
  Proposition R12 : arrière-plan seulement pendant la fenêtre « en route » d'un chantier. À valider
  (Nathan ou juriste) avant toute livraison du GPS. Même besoin : une politique pour les photos et les
  signatures.
- **Prompts maîtres d'origine des départements** (annexe A de la définition) : ils portent le
  détail fonctionnel (routes, tables, KPI, scénarios de test). Exemple : les 21 sections du rapport
  de décision M9, dont la définition ne liste qu'une douzaine (audit M9).
