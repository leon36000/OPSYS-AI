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
- [x] T0.5 CI du core : job GitHub qui installe Node et pnpm, construit et teste le core tel
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
        correction à la source est en cours (T0.6) ;
      - run 13 (7a43c25) : l'erreur avalée, capturée sans effet de minutage, est un dépassement
        du délai de requête de `sessions.delete` ;
      - **run 14 (6503887) : CI du core entièrement verte**, construction et 6 morceaux de tests,
        sans artifice. Le `beforeAll` précharge les deux modules du chemin `sessions.delete` qui
        manquaient, comme le prévoyait déjà l'amont.
- [x] T0.6 Élagage selon R11 (canaux et fournisseurs inutiles, docs, apps natives…), CI verte.
      Fait à l'import (T0.4) : apps, docs, 120 extensions. Reste : `scripts/` et `test/` qui visent
      des chemins élagués (scripts iOS, Android et macOS orphelins, R14), guidé par la CI du core.

      Preuve (run 14, 6503887), en six itérations guidées par la CI :
      - données de test adaptées à une extension conservée, assertions inchangées : google au
        lieu de venice et de codex, imap au lieu d'acpx, openai au lieu de groq ;
      - tests de la CI ou de la publication amont supprimés (`.github/` élagué, SHA amont
        introuvable dans un fork dur) ;
      - fichiers de données du produit rétablis et gardés par `outils/fork/elaguer_core.py`
        (`tool-display.json`, `docs/install/docker.md`…) ;
      - banc de test mis à la racine git (monorepo) ;
      - préchargement du graphe de nettoyage ACP.

      Les deux cas `setup-inference-turn` propres au harnais codex sont supprimés : aucune
      extension conservée ne porte ce contrat. Suivi : `scripts/` orphelins à nettoyer avec T0.7.
- [ ] T0.7 Renommage OpenClaw → OPSYS en quatre lots (R14), CI verte à chaque lot. L'API interne
      du fork (`openclaw/plugin-sdk/*`, `@openclaw/*`, `OPENCLAW_*`) reste telle quelle (R14, décision 2).
  - [ ] Lot 1 : marque visible (interface, locales `fr-CA` par défaut et glossaires, invites système,
        bannière, notifications) et les 539 assertions qui la figent.
        Livré, à cocher sur la CI du core (`tests`, `tests-opsys`, `construction`) : 38a3463, efdd019, 2bbbcff
        (276 fichiers sous `core/`).
        - Interface : titre, manifeste PWA, 114 valeurs `en*.ts` ; `fr-CA` créée depuis `fr` et
          langue par défaut, chargée à la demande (aucun octet de plus au démarrage).
        - Invites système, voix, bannière et `--version` (`OPSYS <version> (<commit>)`),
          notifications, pages de partage, nom Bonjour ; les lecteurs de la bannière acceptent
          `OpenClaw` et `OPSYS`.
        - Gardés exprès (PROVENANCE.md) : marqueurs de protocole, textes d'aide figés par
          `config-baseline.sha256`, ligne de licence, identifiants internes.
        - À faire relire : les textes fr-CA par un locuteur québécois ; `pnpm ui:i18n:sync --write`
          ne doit changer que `generatedAt`.
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
- [x] T0.10 Superviseur : le core lance et surveille le moteur métier Python (via `uv`), santé et
      journaux unifiés, une seule authentification.
      Preuve (096512f, 533f6a6 ; CI core 22, job `tests-opsys` vert : 28 fichiers sur 28 cibles,
      dont `opsys-metier-config` 30 tests, `opsys-metier-env` 11, `opsys-metier-supervisor` 19,
      `health.owner-routing` 17) :
      - réutilise `ProcessSupervisor` (lancement, sortie relayée, arrêt de l'arbre) et
        `RetrySupervisor` du fork ; désactivé par défaut (`opsys/metier.json`, `"actif": true`) ;
      - `uv run opsys-mcp --http` sur 127.0.0.1 ; sonde `GET /sante` (sans jeton ni donnée
        métier) ; relance avec recul borné, `failed` après dix relances ; état `opsysMetier` dans
        les RPC `health` et `status` ; journaux sous `opsys-metier`, lignes masquées ;
      - jeton `OPSYS_MCP_JETON` lu ou généré, passé par l'environnement de l'enfant seulement ;
        l'enfant ne reçoit ni `OPENCLAW_*` ni les clés de fournisseurs ;
      - socle 548 (dont 14 pour `/sante` sur un vrai uvicorn), ruff, verifier.

      Limite : `${OPSYS_MCP_JETON}` doit exister dans l'environnement ou le `.env` de
      l'installation (T0.11) ; un jeton généré ne sert qu'au moteur.
- [x] T0.12 M3 : l'outillage de mutation (`tests/outils_preuve/muter_*.py`) travaille sur une copie
      temporaire, jamais sur la vraie source. Une exécution tuée avait laissé une mutation dans
      `blocage_prix.py`, et elle a été commitée par erreur (899bbad). Elle est corrigée par 7ad0377.
      Preuve (96ebd73) : `EnvironnementMutation` copie le département, lie les voisins en lecture
      seule et ne les supprime jamais. Preuves structurelle (AST) et dynamique (SHA-256 de `src/`).
      La suite M3 donne 583 réussis ; l'empreinte de `src/` est identique avant et après la batterie.
  - [x] T0.12-suite M3 : l'épreuve des gardes de `tests/test_gardes_des_outils.py` dépose encore
        ses fichiers volontairement rouges (`test_epreuve_garde_suite_rouge.py`,
        `epreuve_module_sans_garde.py`) dans les vrais dossiers de M3. Si une exécution est
        interrompue, le fichier reste, la suite suivante échoue, et un `git add -A` le
        commiterait. La faire travailler sur une copie temporaire, comme `EnvironnementMutation`.
        Preuve (a2dc2a0 intégré) :
        - les trois artefacts rouges (dont une copie non compilable oubliée) sont écrits dans une
          copie jetable créée par `EnvironnementMutation`, jamais sous la vraie racine ;
        - preuve structurelle (AST : aucun appel d'écriture sur une racine du département) et
          dynamique (SHA-256 de `src/` et `tests/` identique après une épreuve) ;
        - épreuve tuée par `SIGKILL` : `git status` de M3 inchangé, suite suivante verte ;
        - M3 823 (outils de mutation compris).
- [ ] T0.11 Installateur en une commande (dérivé de `install.sh` / `install.ps1`), désinstallation
      et export documentés ; Docker Compose en option serveur.
      Avancement (non coché : le job `installateur` n'a pas encore tourné en CI) :
      a045b08 (`opsys instance initialiser|exporter|restaurer`), be22f0c (`configurer` ne supprime
      plus l'espace de travail des agents : `MEMORY.md` et `memory/` survivaient mal au rejeu de
      300 s du VPS), bcdc611 (`install/install.sh` et `.ps1`, désinstallation, job `installateur`),
      394238d (`docs/exploitation/INSTALLATION.md`). Socle 977 (86 nouveaux), shellcheck OK.
      - Construit depuis le dépôt (aucune version publiée : T3) ; un secret existant n'est jamais
        régénéré ni affiché ; exit 3 et quoi fournir si un palier ou le service d'embeddings manque.
      - Export en liste blanche avec manifeste SHA-256 (sans `.env`) ; restauration vérifiée avant
        toute écriture ; désinstallation sans jamais toucher aux données.
      Reste : job `installateur` vert (le core lit-il `core/.env` ? unité `systemd --user` sans
      secret ?), puis macOS et Windows par une exécution manuelle ; LiteLLM, PostgreSQL et console
      restent à Docker Compose.

- [x] T0.13 Taxonomie métier partagée : M1, M2 et M3 utilisent un même `TYPES_TRAVAUX` qui ne
      contient aucun des 4 services réels (gouttières, revêtement, soffite-fascia, réparation). Une
      seule taxonomie, dans le socle, paramétrable par le profil d'entreprise (audits M1, M2, M3).
  - [x] T0.13-a Socle, M1, M2, M3.
        Preuve (022a61f à 37fbbe8, intégrés) :
        - `opsys.taxonomie` : catalogue de référence (`gouttieres`, `revetement`,
          `soffite_fascia`, `reparation`, libellés fr-CA, mots-clés) ; profil de l'instance
          `$OPSYS_HOME/entreprise.yaml` (même mécanisme que `paliers.yaml`, écriture tracée) ;
          `opsys services lister|declarer` ; sans profil, aucun service accepté (verdict qui dit
          quoi configurer), jamais de repli sur `autre` ;
        - contrat `LeadQualifie` v2 gelé (`service`, `schema_version: 2`, `source`, `utm`,
          `campagne` optionnels), v1 intact (SHA épinglé) ; M1 émet le v2 ; M2 accepte v1 et v2
          (version lue, jamais devinée) ; M3 valide `service` par la taxonomie, barème indexé par
          service (« barème du service X absent : à fournir ») ;
        - garde de dérive : `opsys verifier` (« taxonomie sans copie locale »),
          `tests/test_taxonomie_derive.py`, contrôle 13 ter du gate BMAD de M3 ;
        - socle 700, M1 414, M2 729, M3 908 (suite complète), M4 à M10 verts, verifier.

        Choix : plusieurs services évoqués dans une demande → M1 ne qualifie pas et demande
        lequel (la précédence est une décision du propriétaire).
  - [x] T0.13-b M4 et M7 (7e81d88) : M4 accepte v1 et v2 (règle unique `etats.travaux_de`,
        jamais l'un déduit de l'autre), `service` en clé additive du WCT et de
        `m4.travaux_termines` ; cédule par tournées avec `durees_par_service` pour un lot v2 ;
        `chantier_social.py` de M7 accepte v1 et v2 ; l'app garde les interventions v2 ; E2E v2
        par la porte d'appareil jusqu'à `completed_verified` ; M4 1667, M7 585, E2E 11,
        Jest 992. Reste : M7 lit encore `type_travaux` pour ses demandes d'avis (textes sans
        type pour un lead v2) ; `m1-demande-chiffrage.v1.yaml` reste en v1. Énoncé d'origine :
        `cedule.py` et `contrats.py` de M4 portent encore la copie v1 de
        `TYPES_TRAVAUX` et refusent un lead v2 ; l'événement `m4.travaux_termines` porte
        `type_travaux` (version avec `service` à décider) ; `chantier_social.py` de M7 valide les
        types v1 ; `m1-demande-chiffrage.v1.yaml` reste en v1. Une fois migrés, les ajouter à
        `tests/test_taxonomie_derive.py` et au gate.

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
- [x] T1.2 Événements (`completed_verified` calculé par le code : preuves complètes et aucune variance
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
  - [x] T1.2-e Test de bout en bout : de la complétion jusqu'à la cascade, avec une relivraison
        idempotente et un consommateur en échec mis en quarantaine sans bloquer les autres.

        Preuve (`tests/test_cascade_travaux_termines.py`, 6cbfa29, 362e380, et la correction
        M2 qui suit) :
        - vrais départements, vrai bus, drainé jusqu'au repos ;
        - nominal : completed_verified, facture exacte, variance évaluée, M2 à facture, M8, M10
          et M3 alimentés ;
        - écart de 40 % : reste en revue, et la facture brouillon est créée quand même ;
        - relivraison sous un autre id : aucun doublon, et aucune quarantaine. Deux défauts
          corrigés : M10 mémorisait deux fois le même WCT ; M2 partait en quarantaine ;
        - lead inconnu : M2 en quarantaine, sans bloquer les autres ;
        - complétion avant l'acceptation du devis : même état final ;
        - socle 281, M2 590, M10 265.
  - [x] T1.2-f Le WCT porte les champs de M7 :
    - `ville` et `type_travaux`, tirés du contrat de l'intervention, déterministes ;
    - le consentement, la satisfaction, les photos et la description factuelle, tirés du
      formulaire de complétion (T1.4-f), jamais inventés.

    Aujourd'hui, aucun chemin réel ne les produit : aucune demande d'avis ne naît de la cascade.

    Preuve (3c7b7ca, et la correction M6 qui suit) :
    - `type_travaux` est tiré de l'intervention ;
    - le consentement, la satisfaction, les photos et la description ne sont acceptés que pendant
      un appel d'appareil. Venant d'un agent, ils donnent le refus `REJ-CHAMPS-CLIENT-HORS-APPAREIL` ;
    - M6 accepte ces champs sans les lire ;
    - M4 628, M6 293, M7 503 ; socle 362.

    Décision : la ville reste hors du WCT. M4 ne la garde que hachée (Loi 25, invariant déjà
    testé sur tous ses maillons). M7 devra la tenir de M2 (lead), par un événement ou une
    décision d'architecture à prendre.

    Relevés à reprendre :
    - M3 n'a aucune durée estimée de main-d'œuvre (`duree_estimee_minutes`) (T2.3) ;
    - un second chantier pour un lead déjà à `facture` part en quarantaine chez M2 (cycle de vie
      par chantier, T2.2) ;
    - la file du propriétaire doit montrer le signal de variance à côté de la facture brouillon
      (T1.3-c).
- [x] T1.3 Approbations N3–N4 (complétion, facture, écart matériaux), file du propriétaire.
      Envoi et paiement de facture exposés en T3 seulement, par les approbations du socle : la
      vérification de forme du maillon F4 de `facturation.envoyer_facture` ne suffit pas seule.
      Les approbations internes de M5 (F0–F7) rejoignent l'échelle unique (ADR-0009).
  - [x] T1.3-a Socle (ADR-0009 §4 et §5) :
    - échelle unique N0–N5, avec la correspondance T et F ;
    - décision signée par une personne et son rôle, jamais un mot de passe partagé ;
    - rôles approbateurs de chaque niveau N déclarés dans `department.yaml` ;
    - N5 exige la signature de `nathan_owner` et l'attestation du professionnel ;
    - file du propriétaire, par CLI et console : demandes du socle plus attentes déclarées par
      les départements.

    Preuve (718b9bb) :
    - niveau N explicite ou déduit de T sans régression ;
    - personnes et rôles (migration `0005`) : mot de passe haché `scrypt`, jamais en clair ;
    - CLI `opsys personnes` ;
    - console avec une connexion par personne ; le mot de passe partagé est retiré, et l'on
      amorce par la CLI ;
    - politique `approbations: {n3, n4}` par département, `nathan_owner` seul par défaut ;
    - N5 : `nathan_owner` seul, avec l'attestation obligatoire ;
    - décision signée par la personne et le rôle ;
    - file du propriétaire (`opsys approbations file`, `GET /api/approbations/file`) ;
    - socle 362, 10 départements verts, PostgreSQL réel.

    Code critique, revue externe requise avant `main`, en priorité :
    - N5 non délégable ;
    - le retrait du mot de passe partagé ;
    - l'ordre des vérifications dans `decider`.

  - [x] T1.3-b M4 : revue humaine d'une complétion `completed_pending_review` (vérifiée ou
        corrigée), décision signée ; l'alerte d'écart matériaux (signal critique M6) entre dans
        la file.

        Preuve (5b4b92c) :
        - `m4_resoudre_revue_completion` (N4 : `manager`, `admin` ou `nathan_owner`) mène à
          verified ou à une correction motivée ;
        - c'est le troisième et dernier chemin d'écriture d'un statut de complétion, gardé par
          l'AST ;
        - `attentes()` : complétions en revue, avec le signal de variance critique ;
        - M4 670.

  - [x] T1.3-c M5 :
    - envoi et paiement de facture par les approbations du socle ;
    - attentes de facturation dans la file ;
    - les approbations internes F0–F7 rejoignent l'échelle unique.

    Preuve (commit « T1.3-c » ci-dessous, 96d8546 dans l'agent) :
    - `m5_envoyer_facture` (N4 : `finance` ou `nathan_owner`) ne dépend plus de la forme d'un
      maillon F4, seulement de la décision signée du socle ;
    - `m5_enregistrer_paiement_facture` (N5 : `nathan_owner` et une attestation) compare par le
      code le montant payé au montant dû. Un écart est nommé, jamais toléré ;
    - correspondance F→N en un seul endroit ; les outils F0–F7 sont retirés des agents
      (`approbation.py` reste sans appelant, à trancher) ;
    - `attentes()` : attentes de facturation, factures prêtes à envoyer et signal de variance
      critique à côté, sans blocage ;
    - M5 318, M6 293, M4 628 ; socle 362.

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

  - [x] T1.4-c Core, après T0.5 (CI du core verte) (c1 à c6 cochées sur la CI du core) :
    - rôles d'opérateur nommés (`admin`, `employee`, `seller`) sur le jeton d'appareil ;
    - portées d'outils par rôle ;
    - le rôle d'une projection vient de l'identité authentifiée, jamais d'un paramètre de l'appelant.
      Exemple : `m3_lire_devis(role=...)` retire coût, marge et prix pour un employé, mais c'est
      aujourd'hui l'appelant qui choisit le rôle ;
    - appairage mobile, avec l'algorithme de signature lu dans le fork.
    - [x] T1.4-c1 Core : `/tools/invoke` transmet au moteur, dans le `_meta` MCP, la clé
          d'idempotence, l'appareil et son heure (`IDEMPOTENCE.md` §7).
          Recochée avec T1.4-c6 (CI core 23, 71471f9) : la porte d'appareil appelle l'outil MCP
          du département avec ce `_meta`, prouvé par deux vrais serveurs MCP stdio
          (`opsys-device-mcp-target.test.ts`, 16 tests). Historique : décochée une seconde fois (T1.4-c6) : la lecture du fork montre que `/tools/invoke` ne
          voyait AUCUN outil MCP (sa liste vient de `createOpenClawTools` : core, plugins,
          canaux ; les outils de `mcp.servers` n'existent que pendant un tour d'agent). Les tests
          de c1, c2 et c4 remplaçaient cette liste par un faux outil : ils prouvaient le
          `_meta` d'un tour d'agent, pas celui d'un appel d'appareil. À recocher avec T1.4-c6.
          Livré (6dffd04) : contexte `AsyncLocalStorage` jusqu'au `tools/call`, tests vitest (dont
          un vrai sous-processus MCP).
          Correction : d'abord cochée sur la foi d'une CI du core verte, alors que
          `pnpm test:fast`, seule suite de cette CI, exclut `src/agents/**`, `src/gateway/**` et
          `packages/gateway-protocol/**` : ces tests, comme ceux de T1.4-c2 et T1.4-c4, n'avaient
          jamais tourné. Le job `tests-opsys` de `core.yml` les lance
          (`core/test/opsys-tests-cibles.txt`, 23 fichiers).

          Preuve (CI core 21, d7d77d5, job `tests-opsys` vert, 4 morceaux vitest) : le premier
          passage a révélé un vrai défaut, le `_meta` perdu quand le module est chargé deux fois
          (deux `AsyncLocalStorage`) ; corrigé par un singleton de processus
          (`resolveGlobalSingleton(Symbol.for("opsys.mcpCallMeta"))`). Correctifs de mise en place
          des tests : 376d742, 8b5cb01.
    - [x] T1.4-c2 Core et socle :
      - rôles nommés sur le jeton d'appareil, attribués à l'approbation de l'appairage avec la
        personne OPSYS ;
      - outils permis par rôle, générés par `opsys openclaw configurer` ;
      - `opsys/personne` et `opsys/role` transmis au moteur, qui s'en sert pour les projections
        et les signatures.
      Avancement (49584ea), partiel :
      - fragments `opsys/roles.json` et `opsys/appareils.json` générés par OPSYS ;
      - refus fermé hors de la portée du rôle ;
      - `opsys/personne` et `opsys/role` transmis au moteur.

      Preuve finale : job `tests-opsys` vert (CI core 21, d7d77d5), dont
      `tools-invoke-http.opsys-roles.test.ts` et `opsys-device-roles`. L'attribution existe
      depuis T1.4-c4 (42bbf6a) :
      `opsys appareils appairer`, `lister` et `revoquer` attribuent la personne et le rôle (refus
      fermé) et régénèrent `opsys/appareils.json`, en second temps après l'approbation native de
      l'appairage par le core.
    - [x] T1.4-c4 Core : `/tools/invoke` authentifie l'appareil par son jeton d'appairage, et non
          par le secret partagé (accès complet).
      - L'identité (appareil, personne, rôle) vient du jeton vérifié, jamais du corps.
      - Tant que ce n'est pas fait, `opsys/personne` n'est pas authentifié : aucun outil ne s'en
        sert pour signer ou projeter, et le téléphone ne reçoit jamais le secret partagé.
      - Aussi : un identifiant de client OPSYS dans `GATEWAY_CLIENT_IDS`.

      Livré (42bbf6a), prouvé par le job `tests-opsys` vert (CI core 21, d7d77d5 ; la CI core 16
      ne lançait pas ces tests, voir T1.4-c1). `tools-invoke-http.device-token-auth.test.ts`
      tourne dans le projet à processus séparé (courtier SQLite de l'hôte) :
      - `/tools/invoke` accepte le jeton d'appareil par le mécanisme natif du fork
        (`verifyHttpOperatorDeviceToken`, qui rend aussi le `deviceId`) ; le secret partagé ne
        porte jamais `opsys/personne` ni `opsys/role`, quel que soit le corps ;
      - un `deviceId` de corps différent de l'appareil authentifié est refusé (403) ; le contrôle de
        rôle est obligatoire pour tout appel par jeton ;
      - `GATEWAY_CLIENT_IDS.OPSYS_MOBILE` ajouté, pas encore câblé ;
      - socle 392, ruff, verifier ; démonstration de la CLI (personne, appairage, refus d'un rôle
        non porté, révocation) ; vitest (7 et 11 tests), à exécuter par le job `tests-opsys`.

      Code critique : revue externe (liste plus bas). Le reste passe à T1.4-c5.
    - [x] T1.4-c5 Core et mobile : le rôle nommé sur la poignée de main WebSocket (l'app ne
          l'apprend pas encore) ; `opsys-mobile` câblé dans l'app et dans la classification de
          confiance du core.
          Preuve CI : core 25 (b2838a3), job `tests-opsys` vert, 40 fichiers ciblés sur 40, dont
          `opsys-device-identity-http`, `server-http.opsys-device-identity` et
          `opsys-mobile-trust`. Livré (cf5ac31, b7dd582, 677610e) :
          - `GET /opsys/identite` plutôt que `hello-ok` (trame gelée, envoyée avant l'attribution
            de la personne, et l'app ne se reconnecte pas en WebSocket) : `deviceId` tiré du jeton
            vérifié, personne et rôle lus dans `appareils.json` par le même code que la porte
            d'outils ; 401 jeton inconnu, 403 appareil sans attribution, rôle non déclaré ou
            secret partagé ;
          - mobile `src/identite/` : identité lue après l'appairage, au démarrage, au premier plan
            et au retour du réseau, gardée dans `expo-secure-store` « à reconfirmer », effacée
            dès un refus ; rôle inconnu → écran d'erreur, jamais un profil par défaut ; pointage,
            chantier et consentement envoient la personne confirmée (plus de saisie à la main) ;
            l'app s'annonce `opsys-mobile` ; Jest 874, `tsc` propre.
          Choix à confirmer (revue externe) : `opsys-mobile` n'entre PAS dans
          `isNativeAppUiClient` (cela élargirait la confiance sans bénéfice pour un téléphone),
          épinglé par `opsys-mobile-trust.test.ts`.
    - [x] T1.4-l Mobile : après un nouvel appairage, le vidangeur de la file sortante garde
          l'ancien jeton (`src/outbox/service.ts`) jusqu'au redémarrage de l'app ; le reconstruire
          au changement de jeton, avec test.
          Preuve (b87bf63, d0e44a6 intégrés) : le vidangeur relit la session avant chaque envoi ;
          chaque mutation porte sa personne (colonne `proprietaire`, migration au démarrage) ;
          même personne → envoyée avec le nouveau jeton et la même clé ; autre personne ou
          propriétaire inconnu → quarantaine visible, jamais envoyée ni supprimée ; refus
          d'appareil (401, 403 `device_unknown`/`role_unknown`) → arrêt de la passe sans
          tentative comptée, retour à l'écran d'identité ; corrige au passage un 401 qui rendait
          chaque mutation perdue (`echec_permanent`) ; Jest 987, `tsc` propre, vrai SQL sur
          `node:sqlite`.
          Limites : raison du 403 lue dans le texte du message du core (un champ `reason`
          structuré serait plus sûr) ; la quarantaine n'a pas d'écran de gestion.
    - [x] T1.4-c6 Core et mobile : noms d'outils de bout en bout.
          Preuve CI : core 23 (71471f9), job `tests-opsys` vert, 30 fichiers ciblés sur 30,
          dont `opsys-device-mcp-target` 16 tests, `tools-invoke-http.opsys-device-mcp` 9,
          `opsys-roles` 22, `device-token-auth` 8, `opsys-device-roles` 11. Revue externe : liste
          plus bas (1b7e14f).
          Livré (190bcc5, 1b7e14f, b9b1477) :
          - constat : aucun nom ne pouvait marcher ; sans `agentId`, une configuration à dix
            agents sans défaut refuse la requête (400) avant toute résolution d'outil ; les
            `tools.deny` par agent ne s'appliquent pas à un outil MCP ; l'enveloppe
            `{ok, resultat|erreur, rejoue}` du moteur doit arriver telle quelle à l'app ;
          - porte d'appareil dédiée (`opsys-device-mcp-target.ts`) : le nom nu partout ; le
            serveur vient de `roles.json` (clé sœur `serveurs`), jamais de la requête ; session MCP
            limitée à ce serveur, outil vérifié dans son catalogue, appel avec le `_meta`
            (identité et idempotence) ; jamais un outil natif du core ; `gateway.tools.deny` et le
            hook `before_tool_call` s'appliquent ; injoignable → 500 (l'app réessaie avec la même
            clé), absent → 404, refus → 403 ;
          - tests vitest : jeton d'appareil réel et vrais fragments de configuration, et deux
            vrais serveurs MCP stdio dont un homonyme qui ne démarre jamais ; socle 646.
          Limites : une session MCP par appel (à mesurer en T1.5) ; un défaut permanent du serveur
          (500) est réessayé jusqu'à la limite de la file sortante. Le core matérialise un outil MCP
          sous `serveur__outil` (`agent-bundle-mcp-names.ts`, p. ex. `opsys_m4__m4_pointer`),
          alors que l'app appelle `/tools/invoke` avec le nom nu (`m4_pointer`) et que la portée
          par rôle (`opsys/roles.json`, `authorizeOpsysDeviceTool`) compare ce nom nu. Vérifier
          dans le fork comment `/tools/invoke` résout un nom d'outil MCP pour un appel d'appareil
          (quel agent, quelle liste d'outils), puis aligner l'app, `roles.json` et le contrôle de
          portée sur un seul nom ; test du core qui appelle un vrai outil MCP d'un département par
          un jeton d'appareil. Tant que ce n'est pas prouvé, aucun écran mobile n'est réputé
          fonctionner de bout en bout.
    - [x] T1.4-c3 Mobile : client d'appairage (QR ou code, défi signé selon l'algorithme du
          fork, jeton dans `expo-secure-store`), testé contre le protocole lu dans le core.

          Preuve (c171a2a) :
          - défi `connect.challenge`, charge v3 et signature Ed25519 pure (RFC 8032), établis par
            lecture du fork avec références ;
          - `deviceId` = sha256 de la clé publique ;
          - vecteurs vérifiés octet pour octet, dont un vecteur croisé avec Node `crypto` ;
          - code `oc-pair://` ; jeton dans `expo-secure-store` ;
          - Jest 312, `@noble/curves` et `@noble/hashes` (MIT) inscrits.

          Reste (dépend de T1.4-c2) : le core ne renvoie que le rôle générique `operator`, que la
          garde refuse. Le catalogue des clients du core n'a pas d'identifiant OPSYS. L'écran de
          pointage garde un identifiant d'appareil provisoire, à relier à la vraie identité.

  - [x] T1.4-d `punch.tsx` (M4.4) de bout en bout par la file sortante (R12 §5, étape 2).
    Cochée : le trajet réel est prouvé par `e2e-core` (T1.5-b, vrai core) : `m4_pointer` par la
    porte d'appareil avec `idempotencyKey`, `deviceId` et `deviceTimestamp`, heure du serveur au
    pointage, rejeu sans effet.

    Avancement :
    - mobile (b178178, bdd0ac8) : écran, vidangeur de la file (recul, reprise avec la même clé,
      verdict métier lu), déclencheurs de premier plan et de réseau ; Jest 227 ;
    - serveur (5c3c7ee) : pendant un appel d'appareil, l'heure de réception fait foi pour la
      paie, et l'heure de l'appareil est gardée à côté.

    Reste : le trajet réel appareil → core → moteur contre un core réel (T1.5).
    `m4_demarrer_route` lit l'heure serveur depuis T4.2 (ff0c118).
  - [x] T1.4-e Chantier du jour, transitions, checklist, photos et signature (étapes 3 et 4).

    Preuve (873f3d3) :
    - `today.tsx` (statuts actifs de `m4_lister_interventions`, cache SQLite lu hors ligne) ;
    - `job/[id]` : en route par `m4_demarrer_route`, arrivée et pause par le pointage, verdict du
      serveur affiché ;
    - `checklist.tsx`, `photos.tsx`, `signature.tsx` : fichier local et SHA-256 des octets ;
    - un seul identifiant d'appareil dans l'app : l'identité d'appairage réelle ;
    - Jest 446 (312 avant), `tsc` sans erreur ; `expo-camera`, `expo-file-system`,
      `react-native-signature-canvas` et `react-native-webview` (MIT) inscrits.

    Reste : « chantiers du jour » filtre par statut, faute de date et de technicien dans
    `m4_lister_interventions` ; les photos et la signature ne partent pas encore (T1.4-e2).
  - [x] T1.4-e2 Serveur : recevoir l'envoi binaire des photos et de la signature (reprise par
    empreinte, SHA-256 vérifié, référence stable rendue) ; exposer la date et le technicien assigné
    dans `m4_lister_interventions`.

    Preuve (7eea631, 1527c34) :
    - dépôt adressé par contenu dans le socle (`opsys.fichiers`, migration 0008) : blocs de taille
      fixe, idempotents, assemblage vérifié (taille, SHA-256, octets magiques JPEG ou PNG) ;
    - `m4_deposer_fichier` (N2, tâche interne) et `m4_etat_fichier` (lecture) ; cinq refus nommés ;
    - `m4_completer_intervention` refuse toute référence de photo ou de signature qui n'est pas un
      fichier déposé et complet (`REJ-PREUVE-FICHIER-INTROUVABLE`) ; les tests et cascades déposent
      de vrais PNG ;
    - `m4_lister_interventions` rend le technicien assigné ;
    - socle 406 (38 tests PostgreSQL ignorés faute de Docker, la CI les exécute), M4 761, M6 382,
      M5 321, verifier 119 outils ; `docs/architecture/FICHIERS.md`.

    Reste : la fenêtre planifiée reste `null` (la cédule n'est pas persistée) ; ni rétention ni
    purge des fichiers ; aucune politique « photos » pour M4 ; ni contrôle d'accès par
    intervention, ni quota.
  - [x] T1.4-f « Terminer », qui lance la cascade §9.7, puis le formulaire des matériaux (étape 5).
    Cochée : écrans et file sortante (Jest), outils du moteur, E2E moteur (T1.5 : « Terminer »,
    matériaux, alerte et décision du propriétaire), et porte d'appareil du vrai core (T1.5-b).
    Reste hors de cette case : le rendu des écrans n'est testé par rien (pas de tests de rendu) ;
    `e2e-core` ne joue pas encore « Terminer » ni l'approbation (T1.5-f).
    Approbations côté propriétaire après T1.3 (étape 6).

    Avancement (fc8f269) : étape 5 côté mobile. Envoi des fichiers par blocs dans la file
    sortante, avec reprise et SHA-256 relu avant envoi ; `complete.tsx` ne part jamais avant que
    ses fichiers soient complets ; `materials.tsx` sans quantité ni prix par défaut ; contrat
    confronté à T1.4-e2 ; Jest 587, `tsc` propre.

    Avancement (étape 6, ed0af65, ff7cc63) : le propriétaire liste et décide N3 et N4 depuis son
    téléphone.
    - socle `opsys.approbations_appareil`, même chemin que la console (`approbations.decider`) :
      identité authentifiée seule, relue en base ; N3 et N4 exigent une personne `nathan_owner`,
      qui signe la décision ; N5, demande sans niveau et outil T3 jamais décidables (lecture seule,
      « à décider à la console ») ; appareil au journal d'audit ; rejeu de la même clé sans
      effet, autre clé sur une demande décidée → `deja_decidee` ; l'outil approuvé s'exécute
      sans l'identité ni l'horloge de l'appareil du propriétaire ;
    - outils `m9_lister_demandes_approbation` (T0) et `m9_decider_demande_approbation` (N2, l'outil
      est la décision), portée `admin` (ROLES.md, 50 outils déclarés sur 121) ;
    - mobile `(admin)/approvals` par la file sortante (`approval_decision`), verdicts du serveur
      montrés tels quels, aucun cache hors ligne ;
    - socle 628, M9 125, M4, M5, M6 verts, verifier 121 outils, Jest 697, `tsc` propre ;
      80 tests socle, 3 mutations détectées ; démonstration par les vrais outils M9 via
      `Capacites` (proposition, approbation, écriture unique, rejeu, `deja_decidee`).

    Les blocages de T1.4-h et T1.4-i sont levés (intégrées). Reste avant de cocher : prouver le
    trajet réel appareil → core → moteur (T1.4-c6 puis T1.5). Code critique : revue externe.
    Décision attendue de Nathan : un `admin` non propriétaire ne décide rien depuis l'app, même un
    N3 que la console lui permet (ROLES.md).
  - [x] T1.4-h Appels d'appareil et approbations : une action qu'un humain authentifié (T1.4-c4)
    lance lui-même depuis l'app, dans la portée de son rôle, vaut la « validation humaine au
    départ » d'un N3 (ADR-0009 §4) ; les N4 et N5 restent au propriétaire. Code critique : revue
    externe, et confirmation par Nathan (GATE ci-dessous).

    Preuve (intégrée après T1.4-j) : plafond N3 ; identité relue en base (personne active portant
    ce rôle), sinon file d'approbation comme avant ; portée tirée de `openclaw.roles_outils`
    (désormais déclarée outil par outil), sinon refus `hors_portee_role` ; exécution et trace dans
    le même point de sauvegarde du journal des approbations (fix GPS masqué dans la trace) ;
    idempotence intacte ; addendum ADR-0009 §4 (statut « proposé ») ; 28 tests, socle 519.
    Revue externe et confirmation de Nathan requises avant la mise en service.
  - [x] T1.4-i M6 lit le WCT à la source : `m6_declarer_materiaux_utilises` prend le `wct_id` et
    lit la charge publiée par M4 dans le magasin d'événements du socle, au lieu de la recevoir de
    l'appelant.
    Preuve (bbd08df) :
    - socle : `evenements.charge_publiee(type, evenement_id)` lit le magasin du bus, sans copie ;
    - M6 : `wct_id` inconnu, fabriqué ou d'un autre type → `REJ-WCT-INCONNU`, avant toute
      écriture ; la charge lue passe par les mêmes validations qu'avant ;
    - mobile : plus de relecture de l'outbox ni de cache du WCT, seul le `wct_id` est gardé ;
    - socle 412, M6 394, M4 761, M5 321, Jest 585, verifier 119.

    Reste (T1.4-k) : M6 sait que le WCT existe, pas que l'appareil a le droit d'y déclarer.
  - [x] T1.4-j Portée par outil des rôles d'appareil : chaque outil déclare les rôles qui peuvent
    l'appeler (manifeste), fermé par défaut ; `openclaw.roles_outils` en devient la seule source
    (core et socle). Aujourd'hui `employee` reçoit tous les outils M4 et M6 hors T3, dont
    `m4_lire_outbox` (positions GPS de tous les techniciens), `m6_approuver_po` et
    `m6_consommer_materiaux` (qui prend encore un WCT fourni par l'appelant). Profils : définition
    §9.
    Preuve (00afa6e intégré) : `Outil.roles_appareil`, vide par défaut, fermé pour les trois rôles
    (`admin` compris) ; jamais un outil T3/N5 ; `opsys verifier` refuse un rôle inconnu ou une
    portée sur T3 ; 48 outils déclarés sur 119 (employé 10, vendeur 9, admin 48), justifiés ligne
    à ligne dans `docs/architecture/ROLES.md` ; `m4_lire_outbox`, `m6_consommer_materiaux` et
    `m6_approuver_po` (admin seulement) hors de portée de l'employé ; socle 491, tous les
    départements verts.
  - [x] T1.4-k Contrôle d'accès par intervention : M4 lie la personne authentifiée au pointage et
    à la complétion ; M6 et M4 refusent une action sur l'intervention d'un autre technicien, sauf
    rôle `admin` ; `chantier_id` et `intervention_id` du formulaire des matériaux confrontés au
    WCT. Même travail pour les champs encore fournis par l'appelant : `technicien_id`, `auteur`
    (M2), `accede_par` (M4), `role` et `autorise_couts` (M5) ; filtrer `m4_lister_interventions`
    et les leads (M2, M3) par personne ; retrait du consentement GPS par l'employé depuis l'app.
    - [x] T1.4-k1 M4, M6 et mobile.
      Preuve (69e0251, 2aad731) :
      - l'identifiant de technicien EST celui de la personne OPSYS pour un appel d'appareil ;
        identité relue en base à chaque appel (`signataire_valide`, règle de T1.4-h) ;
      - `m4_planifier_intervention` consigne l'assignation (maillon `assignation_technicien`) :
        « assignée à cette personne » devient vérifiable avant le départ ;
      - employé : seulement ses interventions, sous son propre identifiant ; une intervention d'un
        autre et une inconnue donnent le même refus ; un `technicien_id` ou un `accede_par`
        différent de la personne est refusé, jamais remplacé ; contrôle avant toute écriture ;
        liste et statut filtrés ; admin : tout ;
      - M6 : un employé ne déclare que pour son WCT ; `intervention_id` du formulaire = celui du
        WCT ; le WCT ne porte pas de `chantier_id` : il est confronté au prévu du devis quand il
        le connaît ;
      - retrait du consentement GPS par l'employé depuis l'app (file sortante, trié avant les
        pointages en attente) ;
      - socle 531, M4 852, M6 425, M5 321, M8 à M10 verts, verifier OK, gate BMAD de M4 vert,
        Jest 609, `tsc` propre ; 13 mutations du contrôle, toutes détectées.

      Limites connues (ROLES.md) : une intervention inscrite avant ce changement et jamais
      partie `en_route` n'a pas d'assignation, elle est invisible aux employés jusqu'à ce que
      l'admin la replanifie (à connaître avant la mise en service) ; l'app ne connaît pas encore
      la personne appairée (saisie à la main, confrontée par le serveur : T1.4-c5) ; aucun
      rattachement fichier → intervention ; le motif `decision_admin` n'est pas refusé à un
      employé par le code ; l'employé n'accède pas encore à ses propres positions.
    - [x] T1.4-k2 M2 (`auteur` de `m2_enregistrer_interaction`, leads filtrés par propriétaire),
      M3 (filtre par propriétaire de lead) et M5 (`role` et `autorise_couts` de
      `m5_etat_tresorerie` tirés de l'identité authentifiée).
      Avancement, M5 fait (1ef9499, 688b199) :
      - `acces.py` pur ; identité relue en base à chaque appel ; `admin` voit les coûts (§9.5),
        `employee` et `seller` non ; un argument ne peut que restreindre la vue, l'élargir donne
        `REJ-ROLE-ELARGI` ; un `role` différent du jeton est refusé ; refus avant toute lecture et
        sans écriture ; `m5_lister_attentes_facturation` exige aussi l'identité confirmée ;
      - sans identité d'appareil : comportement d'avant (`autorise_couts` obligatoire, désormais
        un verdict `REJ-AUTORISE-COUTS-REQUIS` au lieu d'`arguments_invalides`) ;
      - M5 395, gate BMAD vert, socle 636, 18 mutations détectées.

      M2 et M3 faits (17ea2f3, 18940a6, bd80cf1 intégrés) : la propriété d'un lead existait
      (`owner` de la qualification) ; pour un appel d'appareil, `owner` est l'identifiant d'une
      personne active vendeur ou admin ; `auteur` vient de la personne confirmée (différent →
      refus) ; le vendeur n'agit que sur ses leads (lead d'un autre, sans propriétaire ou inconnu
      → même refus) ; M2 publie `m2.lead_assigne` dans la transaction de la qualification, que
      M3 relit à la source pour ne rendre au vendeur que les devis de ses leads ; M2 817, M3 1200
      (rapide ; 935 complet chez l'agent), socle 811, E2E 16, gates BMAD de M2 et M3, 20
      mutations détectées. Suite : T1.4-m. À revoir en externe : la règle « `admin` voit les coûts »
      (un `admin` n'est pas toujours Nathan) ; l'`approbateur` de
      `m5_enregistrer_paiement_facture` vient de la demande, pas du décideur (le socle ne
      transmet pas l'identité du décideur à l'outil) ; `mouvements_historique` encore accepté
      d'un appareil. `_acteur_appareil` est dupliqué dans M3, M4, M5 et M6 : un seul helper du
      socle serait plus sûr.
  - [ ] T1.4-m Suites de T1.4-k : réassignation d'un lead (outil d'admin, fait `m2.lead_assigne`
        versionné) ; republication du fait pour les leads qualifiés avant T1.4-k2 (leurs devis
        sont aujourd'hui refusés au vendeur) ; un seul contrôle d'identité d'appareil dans le socle
        au lieu de cinq copies (M2, M3, M4, M5, M6).
- [x] T1.5 E2E : travaux terminés normaux ; écart de 40 % → `completed_pending_review` et alerte
      sur le mobile de l'admin.
      Preuve (19de4bb, 16cd96f, 08d0b29 intégrés ; `tests/e2e/`, 7 verts, PostgreSQL sauté sans
      Docker) : vraie application HTTP MCP du moteur sur un vrai uvicorn, dix départements, client
      MCP HTTP réel ; chaque geste de l'app passe par la règle de la porte d'appareil du core
      refaite en Python (nom nu, serveur de `roles.json`, `_meta` de `buildOpsysMcpCallMeta`) ;
      personnes et appareils créés par la CLI.
      - A (+5 %) : trajet complet de l'employé (consentement, en route, arrivée, 2 fichiers,
        « Terminer », matériaux) ; `completed_verified` après la variance livrée par le bus ;
        stock 158 ; facture brouillon 689,85 $ (TPS et TVQ) ; aucune approbation en attente
        (validation au départ) ; heure du serveur au pointage ; rejeu des 10 appels 6 h plus
        tard : `rejoue`, empreinte de la base identique ;
      - B (+40 %) : `completed_pending_review`, signal critique ; l'alerte est visible par l'outil
        de l'app admin (`m9_lister_demandes_approbation`, section « À voir », ajoutée : elle n'y
        était pas), l'employé reçoit 403 ; boucle complète jusqu'à `completed_verified` après
        décision du propriétaire ;
      - journée de l'employé : 9 appels, 0,8 à 1,1 s en local ; aucune troncature.
  - [x] T1.5-b E2E avec le vrai core en CI (workflow `e2e-core`, run 4 sur 0edbc61, vert : « E2E
        avec le vrai core : tout est vrai ») : core construit, configuration générée validée par
        `openclaw config validate`, Gateway démarré, moteur lancé par le superviseur T0.10,
        appairage comme l'app (Ed25519, approbation par `openclaw devices approve`), attribution par
        `opsys appareils appairer`, puis 20 appels chronométrés : 403 avant attribution ;
        `GET /opsys/identite` 200, 401 sans jeton ou faux jeton, 403 avec le secret partagé ;
        `m4_lister_interventions`, consentement GPS, en route et pointage (200) ; rejeux sans effet ;
        clé réutilisée pour autre chose refusée dans l'enveloppe ; 403 hors portée et pour le
        `deviceId` d'un autre appareil ; médiane 38,5 ms, max 504 ms (faux jeton). Le premier
        passage avait trouvé un vrai défaut (roster sans `ownership: "explicit"`, corrigé
        0edbc61). Énoncé d'origine : construire le core, démarrer le Gateway et le moteur
        (superviseur T0.10), appairer un appareil de test (signature Ed25519), appeler
        `/tools/invoke` et `GET /opsys/identite` avec son jeton ; mesurer la latence réelle.
        Avancement (non coché : la CI du core n'a pas encore exécuté le scénario) : écrit dans
        `tests/e2e_core/` (`scenario.py`, `trajet.py`, `appairer.mjs`, `README.md`) et job
        `.github/workflows/e2e-core.yml` (construit le core, `--moteur superviseur` ou `direct`). Le
        script joue le trajet réel : `opsys openclaw configurer`, `openclaw config validate`,
        `openclaw gateway run` (le superviseur T0.10 lance le moteur), `openclaw qr`, poignée de main
        de l'app en Node (`opsys-mobile`, charge v3, Ed25519), `openclaw devices approve`,
        `opsys appareils appairer`, puis identité, lecture, trois écritures avec `idempotencyKey`, `_meta`
        prouvé dans la base du moteur, rejeu, conflit, refus hors portée ; latence de chaque appel dans le
        journal et le résumé du job. Répété sans core (`tests/e2e_core/test_repetition_sans_core.py`,
        passerelle factice) : ce test prouve le script, pas le core. À cocher quand la CI du core est verte.
  - [ ] T1.5-f Étendre `e2e-core` (vrai core) à « Terminer », au formulaire des matériaux et à la
        décision du propriétaire depuis un second appareil `admin`/`nathan_owner`.
        Livré (1972a6d intégré), à cocher sur `e2e-core` vert : photo en deux blocs, signature,
        départ et « Terminer » datés par le serveur, matériaux +40 % (écart critique), second
        appareil pour `nathan` qui lit l'alerte dans « À voir », ouvre la revue N4 et la décide ;
        décision signée `nathan_owner` avec l'appareil au journal, `completed_verified`, rejeu sans
        effet, seconde décision refusée, employé refusé (403) ; 43 appels chronométrés. Constat
        corrigé : les attentes se triaient par ancienneté seule (revue critique hors de la
        première page) ; elles se trient maintenant par niveau, puis par ancienneté.
        Avancement (non coché : la CI du core n'a pas encore exécuté la suite) : `tests/e2e_core/journee.py`
        et `moteur_e2e.py`. Un second appareil s'appaire pour `nathan` (`nathan_owner`, rôle `admin`) ; la
        photo est déposée en deux blocs, « Terminer » est daté par le serveur, le formulaire déclare 56 pi
        pour 40 prévus (+40 %), l'alerte est lue dans « À voir », la revue N4 est décidée avec une clé, la
        base dit que la personne authentifiée signe et que l'appareil est au journal, le rejeu est sans effet,
        l'employé reçoit 403. Répété sans core, moteur réel : 43 appels chronométrés.
        Constat : avec le manifeste réel de M6 (aucun seuil), l'attente « seuil à configurer » pousse l'alerte
        d'écart hors de `m9_lister_demandes_approbation` (`BUDGET_ATTENTES` 1500, tri par `depuis`) : 4 attentes,
        3 montrées, l'alerte comptée dans `attentes_reste` mais illisible sur l'écran. Le scénario renseigne
        le seuil (comme `tests/e2e/`) ; l'ordre des attentes par gravité reste à trancher.
  - [x] T1.5-c M4, défauts trouvés par l'E2E (65c8bc4 : heure de réception du serveur à la
        complétion, `wct_id` indépendant du téléphone ; `ecart_signale` vrai seulement si une
        demande d'écart métier est ouverte ; attente « formulaire de matériaux à venir » au lieu
        d'une revue à trancher) : `m4_completer_intervention` date avec l'heure de
        l'appareil (le `wct_id` en dépend) au lieu de l'heure de réception du serveur, contrairement
        à `m4_pointer` ; `ecart_signale` vaut toujours vrai pour un WCT venu de l'appareil ; entre
        « Terminer » et le formulaire, la complétion paraît déjà « en revue » chez l'admin.
  - [ ] T1.5-d Écarts à §6 dans la cascade.
    - [x] M6 : stock bas et besoin de commande à « travaux terminés » (bf35bf3, 4b77218) : règle
          pure `reapprovisionnement.py` (stock sous le seuil → besoin de `cible − stock`, décimal
          exact) ; seuil et cible par article dans `department.yaml` de M6, vides par défaut ;
          seuil absent → constat « seuil à configurer », jamais un seuil inventé ; constat
          idempotent par article et WCT ; visible par `attentes()` (app admin, file du
          propriétaire, briefing) ; aucun bon de commande ni mouvement créé (tests, AST) ;
          M6 715, E2E moteur 10 (scénarios C, D, E), socle 758, gate BMAD de M6.
          Limite : stock évalué « en main » par article, pas « disponible » (ni dépôt ni
          réservation dans M6).
    - [x] M5 : coût réel, rentabilité et comptes à recevoir (b217aea, ed001b0) : `cout_reel.py`
          pur (Decimal, `ROUND_HALF_UP`) ; matériaux réels de la variance M6 × prix du livre de
          prix M6 lu à la source ; main-d'œuvre = durée réelle du WCT × taux configuré (absent du
          manifeste livré → « taux à configurer ») ; prix absent ou ambigu → coût PARTIEL, sans
          marge ; rentabilité = prix facturé avant taxes − coût réel, contre la marge prévue du
          devis, tracée par devis et version des entrées, sans écriture comptable ; comptes à
          recevoir = factures envoyées seulement ; `m5_lire_rentabilite_chantier` et
          `m5_lire_comptes_a_recevoir` (T0, `admin`, identité confirmée) ; E2E : A → coût
          486,00 $, marge 114,00 $ contre 120,00 $ prévus ; B (+40 %) → marge 2,00 $ ; M5 592,
          E2E 16, socle 780, 19 mutations détectées. Revue externe (argent) : le livre de prix
          M6 ne porte pas d'unité ; le WCT ne porte pas l'effectif (taux par équipe ou par
          personne, à dire par Nathan) ; `admin` voit les coûts ; `aujourd_hui` fourni par
          l'appelant pour l'âge des créances ; défaut existant de `variance_recus.pour_wct_id`
          (un réessai `declaration_absente` écrase `evaluee`).
    - [x] M8 et M9 (a2274b1, 911158e, 742f3b1) : huit métriques gouvernées
          (`m8-metrics.v1.yaml`, Decimal, garde de devise CAD) remesurées à chaque arrivée de
          `m4.travaux_termines`, `m3.devis_accepte` et `m6.variance_chantier` ; donnée absente →
          « non calculable, manque X » ; seuils vides par défaut → rappel « seuil à configurer »,
          jamais une alerte inventée ; seuil franchi → `m8.alerte_proposee` avec preuve chiffrée ;
          performance d'équipe par technicien sans classement, nominative pour l'admin seul ;
          M9 : briefing borné sous la limite de `Capacites` avec « N autres » et
          `m9_lire_suite_briefing`, `file_proprietaire` ne perd plus les demandes au-delà de 100,
          `m9_produire_lecture_strategique` cite les preuves sans décider ; bout en bout par le
          vrai bus (M4 → M8 → M9) ; M8 339, M9 207, socle 782.
          Reste pour M8 : M3 ne publie pas `duree_estimee_minutes` dans `m3.devis_accepte` (temps
          prévu « non calculable ») ; aucun événement de M5 ne porte la marge réelle vers M8 ;
          `m9_lire_alertes_m8` n'est pas borné.
    - [x] M7 : demande d'avis depuis l'app (531d704, 358d2cc, 34b5f91, f69359e).
        - Deux consentements distincts (Loi 25) : `consentement_demande_avis` à côté de
          `consentement_marketing` (photos), clés additives de `m4.travaux_termines` ; M6 les admet
          (`CHAMPS_WCT_OPTIONNELS`).
        - M4 : l'appareil envoie le choix et la version du texte ; le serveur pose seul la preuve
          (personne du jeton, heure du serveur) ; hors appareil, toujours refusé.
        - M7 : brouillon `PROPOSE` seulement si consentement ET preuve ; jamais envoyé ;
          `m7_lister_demandes_avis` (T0, `admin`).
        - Mobile : deux cases non cochées par défaut, énoncés fr-CA versionnés
          (`consentement-client-fr-CA-v1`, empreinte épinglée par un test).
        - Preuve : E2E `tests/e2e/test_demande_d_avis_appareil.py` (7 tests, vraie porte
          d'appareil) ; M4 1711, M6 717, M7 625, socle 991 (43 sautés), Jest 1058, tsc OK, gate
          BMAD de M4 vert, verifier 139 outils (65 déclarés).
    - [ ] Reste : la marge réelle de M5 vers M8 et M10 (agent en cours). M5, M6, M7, M8 et M9 :
        faits ci-dessus.
  - [x] T1.5-e App du propriétaire : la section « À voir » est bornée à 1 500 caractères
        (`BUDGET_ATTENTES`, `approbations_appareil.py`) sans pagination : au-delà de trois alertes,
        les suivantes ne sont que comptées (`attentes_reste`). Paginer (décalage demandé par
        l'app) plutôt que relever le budget, sous la limite de 6 000 caractères de `Capacites`.
        Preuve (c8727e4, 27f1938, 51304ad) : `decalage_attentes` (rang, jamais une personne),
        `attentes_decalage` et `attentes_suivant` ; ordre stable (`depuis`, puis `id`, département,
        type), hérité par la console ; rang hors plage → page vide ; bouton « Voir plus » dans
        l'app (un changement du total fait tout relire) ; E2E : huit attentes réelles (M4, M5, M6)
        lues en trois pages, chacune une seule fois, sans troncature ni écriture ; socle 838,
        M9 217, Jest 1029.

## T2 — Du lead à la soumission (§6, flux principal)

- [ ] T2.1 M1 : intake omnicanal par les canaux du core, qualification, appel manqué. Câbler les
      extensions du fork (`voice-call` Twilio, `sms`, `imap`, `tts-local-cli`) au lieu de reconstruire la
      voix ; taxonomie des 4 services réels (gouttières, revêtement, soffite-fascia, réparation) ; contrat
      M1→M2 avec `source`, `utm`, `campagne` ; tests qui passent par `Capacites` (approbations réelles)
      (audit M1).
      - [x] T2.1-a Canal SMS du fork vers M1 (020d4fd, fc80869, b945582). Conception :
            `docs/departements/M1-canaux.md`.
            - `m1_recevoir_message_canal` (N2) : correspondant, conversation, idempotence, contact et
              heure tirés de la plateforme par le code ; `source` = canal ; STOP inscrit comme retrait ;
              lead v2 publié à `m1.lead_qualifie` dans la même transaction que le registre.
            - `zone_desservie` lue dans `entreprise.yaml`, jamais passée par l'agent.
            - `opsys openclaw configurer` : canal `sms` éteint tant que les 4 identifiants Twilio et
              l'attestation des politiques SMS et photos manquent ; session par client
              (`per-channel-peer`) ; `session.sendPolicy` refuse toute réponse automatique ; outil
              `message` du core retiré à l'agent (un message sortant reste `m1_emettre_notification`, N4).
            - Preuve : M1 524, M2 817, M10 566, socle 890 (43 sautés), ruff OK, verifier 138 outils
              (64 déclarés aux appareils).
            - Revue externe conseillée : `src/opsys/canaux.py` (politique d'approbation).
      - [ ] T2.1-b M2 consomme `m1.lead_qualifie` ; lien session → affaire automatique (aujourd'hui par
            une approbation humaine).
      - [ ] T2.1-c Envoi réel au client (après approbation N4) ; greffe du crochet `message_received`.
      - [ ] T2.1-d Appel manqué (`voice-call`) et courriel (`imap`).
- [x] T2.2 M2 : lead structuré, Client 360, préparation à l'estimation, prochaine action.
      Preuve (commit « T2.2 » ci-dessous) :
      - Client 360 : identifiant stable tiré du contact seulement ; vue sans donnée inventée ;
      - un second chantier pour un client ouvre une nouvelle opportunité, au lieu d'une
        quarantaine ; un cas ambigu donne `OpportuniteAmbigue` ;
      - `source`, `utm` et `campagne` sont acceptés et validés ;
      - `m2_suggerer_prochaine_action`, table de règles citée, jamais appliquée seule ;
      - `m2.client_associe` : M5 facture le vrai `client_id`, et retombe sur le lead sinon ;
      - M2 656, M5 321, verifier 110 outils.

      Reste : M1 n'envoie pas encore ces champs (son contrat v1 est gelé, T2.1) ; les
      14 segments de M2.11. M3 et M4 acceptent ces trois clés à l'identique de M2 depuis e3b910c
      (le gate BMAD de M3 les confronte à M2 séparément des clés gelées).
- [ ] T2.3 M3 : estimation honnête, soumission brouillon, approbation, besoins matériaux vers M6.
      L'outil `m3_estimer_projet` n'assemble que 6 des 15 modules : écrire l'orchestrateur qui compose
      validation, devis (`devis_id` requis par M4), registre estimé vs réel, signal de relance M2, et
      émet `REFERENCE_ECHELLE_ABSENTE` en alerte non bloquante ; séparer coût et prix (taux de marge
      fourni, jamais codé en dur) ; contrat `BesoinsMateriauxM3` ; soumission brouillon PDF ; politique
      Loi 25 « photos » avant toute collecte réelle (audit M3).
  - [x] T2.3-b Orchestrateur de `m3_estimer_projet`, durée de main-d'œuvre, relance des devis sans
        réponse, soumission brouillon, politique « photos ».
        Preuve (cc28f4a) :
        - `estimation.py` compose validation, qualité des photos, hiérarchie d'échelle, blocage,
          Monte Carlo, plancher, alerte `REFERENCE_ECHELLE_ABSENTE`, `devis_id` déterministe et
          registre ; une estimation bloquée porte aussi son `devis_id` ;
        - durée de main-d'œuvre = quantité × durée par unité du barème, jamais codée en dur ;
          l'estimé vs réel la relit ;
        - `m3.devis_sans_reponse` (délai et instant fournis, idempotent par devis) ; soumission
          brouillon HTML sans coût ni marge ; garde fermée tant que la politique « photos » n'est
          pas validée ;
        - M3 821 (outils de mutation compris, correction e3b910c incluse) ; socle, M5 et M6
          verts.

        Reste de T2.3 : PDF de la soumission ; `niveau_confiance` est un nombre dans le code et
        une chaîne dans le PRD (à trancher : v2 ou clé sœur). Coût et prix séparés, et
        `signaux.py` branché : T2.3-d. Contrat `BesoinsMateriauxM3` : T2.3-e.
  - [x] T2.3-e Contrat `BesoinsMateriauxM3` (M3 → M6).
        Preuve (f2e40bc, b6d5add, e8b9d40, 92a09ca intégrés) :
        - module pur `besoins_materiaux.py` : lignes calculées par le code (quantité de l'ouvrage
          × `quantite_par_unite` du barème, Decimal en texte, nettes) ; facteur de perte absent
          → signalé, jamais inventé ; aucune clé de prix, coût ou marge admise ; `EstimationV1`
          intact (clé sœur) ;
        - événement `m3.besoins_materiaux` publié par `m3_estimer_projet` dans la même
          transaction, versionné par estimation (rejeu sans effet, version périmée ignorée) ;
        - M6 valide seul et range le prévu provisoire dans `besoins_prevus` existant ; le prévu
          définitif du devis accepté l'emporte ; aucun bon de commande créé ;
        - bout en bout par le vrai bus (`tests/test_cascade_besoins_materiaux.py`) ; gate M3
          qui confronte les quatre descriptions du contrat ; M3 1173 (rapide, 1146 complet chez
          l'agent), M6 638, M4 1559, socle 755, gates M3 et M6, verifier.

        Questions ouvertes (architecture M3 §2.9) : qui fournit les `materiaux` du barème (livre
        de prix M6 ou Nathan) ; M6 garde `facteur_perte` sans l'appliquer à la commande ; M6 n'a
        pas de catalogue persisté pour vérifier un `sku`.
  - [x] T2.3-d M3 : vue d'un devis tirée de l'identité authentifiée, prix recommandé distinct du
        coût, signal de relance branché.
        Preuve (5767836) : pendant un appel d'appareil, la vue découle du rôle authentifié et
        revérifié (employé : ni coût, ni marge, ni prix) ; `role` ne peut que restreindre
        (`REJ-ROLE-ELARGI`) ; prix recommandé = coût × (1 + taux de marge fourni), `ROUND_HALF_UP`,
        clé sœur d'`EstimationV1` qui reste gelé ; `signaux.py` rend la demande de photos quand la
        qualité d'entrée est insuffisante ; M3 847 (agent), 817 hors mutation après intégration.
        Enquête `BesoinsMateriauxM3` : `m3.devis_accepte` porte matériau, quantité et unité, mais ni
        facteur de perte ni confiance, et seulement à l'acceptation ; le contrat reste à faire.
  - [x] T2.3-c (M2.7) M2 consomme `m3.devis_sans_reponse` et propose une relance, jamais appliquée.
        Preuve (ecee75a, e832b74) :
        - une interaction système rattache le fait au lead et au Client 360, sans transition de
          statut ; idempotent par `evenement_id` et par `devis_id` ;
        - devis envoyé : « relancer le client » ; brouillon : « envoyer ou abandonner », jamais
          « relancer » un client qui n'a rien reçu ; délai et horodatages recopiés du fait ;
        - lead perdu : fait gardé (`lead_clos`), sans interaction ni quarantaine ;
        - bout en bout par le vrai bus avec les outils de M3 ; M2 671, socle 392, verifier 116.

        Reste : aucun outil ne liste encore les relances en attente (visibles dans le Client 360).
- [x] T2.4 M6 : catalogue, livre de prix, PO brouillon, courriel fournisseur via M1 (repli manuel).
      Preuve (fbe272a) :
      - livre de prix versionné, daté et par fournisseur, jamais inventé (`PRIX_LIVRE` ou
        `INDETERMINE`) ;
      - outil `m6_enregistrer_prix` ;
      - courriel au fournisseur produit comme texte seulement, avec un repli manuel si l'adresse
        est inconnue ; l'envoi réel attend M1.
- [x] T2.5 M6 : lever la décision interne DA-M6-12 (« M6 ne persiste pas les PO »), contraire à la
      définition (moteur de PO à 12 statuts) ; ajouter le moteur de variance estimé M3 vs réel M4, distinct
      de la variance d'inventaire physique existante ; registre des fournisseurs (Gentek, Royal, O.A.M.,
      Kaycan) (audit M6).
      Preuve (bc3dbf0) :
      - DA-M6-12 révisée : bons de commande persistés, avec exactement les 12 statuts de §7 M6.5
        et une table de transitions testée en entier ;
      - registre des fournisseurs (identité seulement, rien d'inventé) ;
      - bon de commande brouillon calculé comme l'écart entre le prévu et le stock ;
      - l'approbation est refusée tant qu'un prix est indéterminé ;
      - envoi N4 (`admin` ou `nathan_owner`) ;
      - la réception est rattachée au bon, avec un signal d'écart de prix ;
      - M6 382 ; verifier 107 outils.

      Reste : les outils pour `supplier_confirmed`, `disputed`, `invoiced` et `closed` ; la
      réception cumulée sur plusieurs livraisons ; l'enrichissement du catalogue (M6.1).

## T3 — Mesure, direction, mémoire

- [x] T3.1 M8 : registre de métriques, qualité et fraîcheur, alertes qui proposent une action.
      Preuve (c8d515e) :
      - registre des définitions versionné et durable, unité validée par le dictionnaire ;
      - qualité calculée par le code : donnée absente (verdict nommé), fraîcheur, plage ;
      - alertes structurées (quoi, à qui, pourquoi, preuve), jamais exécutées ;
      - 3 outils : `m8_enregistrer_definition_metrique` (T1), `m8_resoudre_definition_metrique`
        et `m8_evaluer_qualite_metrique` (T0) ;
      - M8 202, M9 92, verifier 90 outils.
  - [x] T3.1-suite : règles d'unicité et de cohérence entre tables ; alertes dans le digest
        quotidien ; listage compact du registre.
        Preuve (commit « T3.1-suite » ci-dessous) :
        - doublons (`REJ-QUALITE-DOUBLON`) ;
        - cohérence d'une métrique dérivée avec ses composantes, recalculées par le code et
          jamais reçues de l'appelant (`REJ-QUALITE-INCOHERENCE`, tolérance fournie) ;
        - alertes dédupliquées dans le digest ;
        - outil `m8_lister_definitions_metriques` paginé ;
        - M8 243, M9 119.

        Reste : ces deux alertes ne sont pas encore publiées sur `m8.alerte_proposee`, dont le
        catalogue fige les types.
- [x] T3.4 M8 : la garde de devise ne contrôle que les unités « DEVISE/x » ; une unité nue non CAD
      (ex. « USD ») passe. Correction TDD (audit M8, vérifié dans `dictionnaire.py`).
      Preuve (988c62d) :
      - unité nue ou préfixée, sans égard à la casse, comparée aux 178 codes ISO 4217 actifs ;
      - verdict `REJ-DEVISE-NON-AUTORISEE` ;
      - aucun faux positif sur toutes les unités du dictionnaire réel.
- [x] T3.2 M9 : briefing du matin sourcé, décisions en attente sur mobile.
      Preuve (commit « M9 : briefing du matin » ci-dessous) :
      - assemblage déterministe pour une date fournie, en quatre sections : décisions en attente
        (file du propriétaire), alertes de M8, faits de la veille, ce qui manque ;
      - chaque élément porte sa source ; une section vide est déclarée vide ;
      - M8 publie `m8.alerte_proposee` (catalogue strict) et M9 le consomme sans doublon ;
      - forme des décisions exposée pour l'écran admin mobile ;
      - M9 119, M8 205, verifier 97 outils.

      À suivre : le pont de M8 vers les faits de la veille de M9 (preuves métier, T1).
- [x] T3.3 M10 : paquets de contexte en couches, consolidation nocturne, audit « non-oubli ».
      Preuve (d239485) :
      - paquet en 4 couches avec provenance, budget calculé par le code, troncature déclarée ;
      - consolidation idempotente par (affaire, jour), `maintenant` fourni ;
      - audit des faits attendus et des deux chaînes de hachage ;
      - consommation de `m6.variance_chantier` ;
      - M10 263, verifier 93 outils.
  - [x] T3.3-suite : greffe du moteur de contexte dans le core (PREFLIGHT et POSTFLIGHT) ;
        paquet injecté avant une estimation M3 (la résolution des signaux critiques, d'abord
        incluse ici, devient T3.3-suite-b).
        Preuve CI : core 24 (f6cd858), job `tests-opsys` vert, 36 fichiers ciblés sur 36, dont
        les 6 du moteur de contexte (config 25, dépôt 19, moteur 44, paquet 44, fil MCP réel 5,
        enregistrement 3). La résolution des signaux critiques reste à faire (ci-dessous).
        Livré (8c745c7, f6435ef, 5bbe527, c1db4ad) :
        - point d'extension natif du fork (`plugins.slots.contextEngine`, contrat
          `ContextEngine`) ; moteur `opsys` dans `core/src/context-engine/` : `assemble()`
          demande à M10 le paquet de l'affaire par MCP (jamais la base) et l'ajoute au prompt
          système ; `afterTurn()` dépose les faits des outils listés, lus dans leur réponse
          structurée, jamais dans le texte du modèle ; délai borné (4 s) ; moteur injoignable,
          lent, paquet invalide ou hors budget → marqueur « contexte d'entreprise
          indisponible », jamais de paquet tronqué ni de tour bloqué ; ne lève jamais ;
          la mémoire native des agents est gardée ;
        - M10 : `m10_deposer_faits_candidats` (N2, idempotent, lot refusé en entier) ; un
          candidat n'entre ni au paquet ni à la consolidation ;
        - désactivé par défaut ; `opsys openclaw configurer --contexte-entreprise
          m03-estimation:m3_estimer_projet` écrit `contexte.json` et le slot ensemble ;
        - socle 727, M10 301, verifier 124 outils ; TypeScript relu, `tsc` sur stubs et
          132 tests sur un banc maison : la CI seule fait foi.

        Reste (ADR-0010, « Mise en œuvre ») : blocage `before_tool_call` d'un N3 si le contexte
        est insuffisant ; résolution des signaux critiques (affichés seulement) ; affaire lue
        dans une ligne de la demande (à lier à la session avant d'activer M1) ; consolidation des
        candidats ; une connexion MCP par appel ; aucun filtre `CLIENT_PRIVATE` ; l'installation
        n'active rien. Emplacement `core/src/context-engine/` au lieu d'une extension (raison dans
        PROVENANCE.md).
  - [ ] T3.3-suite-b : résolution des signaux critiques (M10 ne sait pas les clore ; le core les
        affiche seulement) ; blocage `before_tool_call` d'une action N3 ou plus quand le contexte
        est insuffisant ; affaire liée à la session avant d'activer M1 ; filtre `CLIENT_PRIVATE`.
        Livré (b1206c3, 33e1789, 4ad239c, 3378650, a5b9537 intégrés, plus la greffe du garde dans
        `runBeforeToolCallHook` et son test direct 9b0772e : vraie chaîne, vrai `contexte.json`,
        chaque cas « laisse passer » doublé d'un contrôle refusé), à cocher sur le job
        `tests-opsys` du core :
        - M10 : cycle ouvert → pris en compte → clos ; `m10_prendre_en_compte_signal` et
          `m10_clore_signal` (N3, `admin`, motif) refusent tout appel qui n'est ni un humain
          authentifié ni l'exécution d'une demande qu'un humain vient d'approuver ; le paquet
          montre les ouverts et les derniers clos (qui, pourquoi) ;
        - core : garde (`opsys-contexte-garde.ts`) appelé depuis `runBeforeToolCallHook` : outil
          OPSYS N3+ refusé si le paquet de la session était indisponible, périmé (15 min) ou porte
          un signal ouvert ; niveaux lus dans `contexte.json` généré ; inactif par défaut ;
        - affaire de la session : lien écrit par un humain (`m10_lier_session_affaire`), lu par le
          moteur sans jamais lire le texte du client ; option `--affaire-par-session` ;
        - filtre de confidentialité : niveaux fermés jamais dans un paquet ; `CLIENT_PRIVATE`
          seulement vers M1 et M2 ; éléments retenus comptés, jamais rendus ;
        - M10 566, socle 802, verifier 137 outils (64 déclarés), 17 mutations tuées.
        Reste : lien automatique session → affaire à la création d'un lead (M1) ;
        `session.dmScope: "per-channel-peer"` avant d'activer M1 ; aucun producteur de clôture
        automatique (M6 ne republie pas une variance résolue).

## T4 — Profondeur des départements

Détaillée à partir des audits (T0.3) : voix M1 par étapes, CFO IA M5, usine à contenu M7, VRP,
météo et GPS M4, vision M3, conseil d'agents M9…

- [x] T4.1 M4 : la cédule trie sur un hachage de ville, sans sens géographique ; la remplacer par
      de vraies coordonnées et un VRP (audit M4).
      Conception : `docs/research/R15-cedule-vrp.md` (PyVRP, MIT ; distances par paliers,
      haversine × détour puis OSRM local en option ; géocodage local par le Référentiel québécois
      des adresses, CC-BY 4.0 ; pyvroom refusé en processus, sa roue embarque GLPK sous GPL).
      `cedule.py` reste le repli « sans coordonnées », affiché comme mode bridé.
  - [x] T4.1-a Localisation : `localisation.py`, maillon `localisation_chantier` chiffré et
        versionné (patron T4.2), `m4_proposer_localisation` et `m4_confirmer_localisation` (rôle
        `admin`) ; aucune coordonnée n'entre au solveur sans confirmation humaine ; aucun accès
        réseau.
        Preuve (4349de4, fbb1af3) :
        - normalisation d'adresse québécoise, import du CSV du RQA en index SQLite (remplacement
          atomique, un import vide garde l'index), correspondance exacte ; une seule adresse de
          bonne qualité → proposition en microdegrés ; sinon `REJ-COORDONNEES-A-CONFIRMER` avec
          les candidats, jamais une position choisie ; index absent → `REJ-INDEX-RQA-ABSENT` ;
        - maillon `localisation_chantier` : coordonnées chiffrées par chantier (clé détruite →
          position illisible, chaîne valide), `empreinte_adresse` en HMAC d'une clé dérivée de
          celle du chantier, jamais l'adresse en clair ; source `rqa` relue dans l'index, jamais
          des arguments ; dernier maillon gagne ;
        - `m4_confirmer_localisation` N3, `admin` seulement, contrôles avant toute écriture ;
          la trace « validation au départ » masque adresse et coordonnées
          (`ARGUMENTS_MASQUES_DANS_LA_TRACE`) ; attribution CC-BY rendue par la proposition ;
        - aucun accès réseau (sockets bloqués), 12 mutations tuées ; démonstration : import (MRC
          60), proposition, adresse inconnue « à confirmer », confirmation par un admin
          authentifié ; M4 1316, M6 425, socle 640, verifier 123 outils (52 déclarés).

        Limites : format du RQA lu dans son guide v1.2, pas sur un vrai fichier (téléchargement
        bloqué dans le bac à sable) ; en mode `supervise` ou `autonome`, un appel d'agent N3
        s'exécute sans file et « un humain a confirmé » ne repose plus que sur `confirme_par` ;
        l'adresse saisie reste en clair dans la file d'approbation tant que l'appel n'est pas
        validé ; aucun outil d'effacement de la clé d'un chantier.
  - [x] T4.1-b Matrice : `distances.py` (haversine entier, détour, vitesse et marge fournis par
        l'entreprise, sinon verdict), port `FournisseurMatrice`, adaptateur OSRM optionnel.
        Preuve (4ad01f6) :
        - haversine en virgule fixe sur entiers (séries, `isqrt`) : indépendante de la `libm`,
          identique à une référence `Decimal` à 90 chiffres sur 100 paires, et à
          `pointage.distance_km` à 1 m près ; aucun flottant ni `/` dans le code (test AST) ;
        - détour, vitesse et marge obligatoires et bornés, sinon verdict ; matrice triée,
          `mode_distance`, `mode_bride`, empreinte SHA-256 qui couvre les paramètres ;
          `verifier_matrice` refuse toute falsification ;
        - adaptateur OSRM (`distances_osrm.py`) : URL locale seulement, sans redirection ni
          mandataire, délai et taille bornés ; panne → repli explicite sur le palier 0, inscrit
          dans l'empreinte ; trajet introuvable → verdict, jamais de route inventée ;
        - M4 1083 (+231), ruff, gate BMAD, verifier ; 100 points en 0,07 s.

        Reste pour T4.1-d : inscrire au catalogue de verdicts les trois codes propres à la
        matrice ; aucun vrai sidecar OSRM essayé ; la fixture d'étalonnage est fictive (30 paires
        réelles à mesurer avant de fixer le détour).
  - [x] T4.1-c Solveur et validateur : `tournees.py`, adaptateur PyVRP (extra `tournees`), DP exact
        de repli et oracle, `verifier_plan`, raisons de non-cédule calculées par notre code ;
        mêmes octets d'une exécution à l'autre.
        Preuve (b48530b) :
        - `resoudre(entree, moteur)` : PyVRP 0.14.0 (import paresseux, `MaxIterations` seulement,
          graine dérivée de l'empreinte d'entrée, compétences et jours par profils) ou DP exact
          jusqu'à 12 chantiers ; sans PyVRP au-delà, verdict « installer l'extra tournees » ;
        - toute donnée métier est une entrée (durée, fenêtre, compétences, dépôt, quarts, graine,
          itérations, coût de non-cédule), sinon un seul verdict qui liste tout ; raisons de
          non-cédule calculées et revérifiées par `verifier_plan` ; plan invalide → refus ;
        - écart 0 avec le DP sur 6 instances fictives (8 à 12 chantiers) et 100 aléatoires ; le DP
          égale une énumération exhaustive ; mêmes octets sous `PYTHONHASHSEED` 1, 2, 3, 4242 ;
          compétence rare jamais donnée à une équipe non admissible ; 8 chantiers : DP 0,002 s,
          PyVRP 0,08 s ; 9 mutations détectées ; M4 1455, ruff, gate BMAD ;
        - CI : l'extra `tournees` est installé dans le job de M4 (sinon 20 tests seraient sautés).

        Limites : PyVRP exécuté en Python 3.11 x86_64 seulement (la CI dira pour 3.12 ; arm64 non
        essayé) ; un créneau figé sans coordonnées refuse toute l'entrée (choix réversible) ;
        `urgence` est un entier 0 à 3 alors que LeadQualifie n'a qu'un booléen (conversion en
        T4.1-d) ; les codes `REJ-TOURNEES-*` et `REJ-MATRICE-*` restent à inscrire au catalogue.
  - [x] T4.1-d Outils et E2E : `m4_proposer_cedule` (brouillon) et `m4_appliquer_cedule` (N3,
        refus si l'entrée a changé) ; scénario fictif Repentigny–Joliette, kilomètres en baisse
        contre le tourniquet sur la même fixture.
        Preuve (intégrée après ee08b3a, 0871624, 07d5778) :
        - `cedule_tournees.py` pur ; `m4_proposer_cedule` (N1) stocke `cedule_proposee` sans
          coordonnée de chantier, rend `plan_id`, `mode_bride` et les non-cédulées avec raisons ;
          `m4_appliquer_cedule` (N3, `admin`) revérifie l'état des interventions, l'empreinte de
          l'entrée reconstruite avec les coordonnées du jour et `verifier_plan`, sinon
          `REJ-CEDULE-ENTREE-CHANGEE` ; assigne par `etats.assigner_technicien`, idempotent ;
        - urgence : règle écrite (vrai = 1, faux = 0, source absente → verdict) ; 12 codes au
          catalogue ; extra `tournees` dans `deploy/Dockerfile` ; skill `optimiser-la-cedule` ;
        - démonstration (fictive) : plan 26 785 m contre 187 601 m pour le tourniquet sur la
          même matrice (−85 %), meilleur sur 13 graines sur 13 ; créneau figé tenu ; coordonnée
          modifiée → refus sans écriture ; employé → hors portée ; application rejouée → une
          seule ;
        - M4 1559, M6 425, socle 731, gate BMAD, verifier 126 outils (54 déclarés), 44 mutations
          tuées.

        Limites : M4 ne connaît ni équipes, dépôts, quarts, durées, compétences ni fenêtres
        client : tout est argument (à alimenter par la configuration de l'entreprise) ; les
        jours et heures des visites restent dans le maillon (`fenetre_planifiee` toujours
        `null`) ; N3 en mode `supervise` ou `autonome` s'exécute sans file.
- [x] T4.2 M4 : consentement et rétention du GPS (`POLITIQUE-geolocalisation.md`) non câblés dans
      le pointage (audit M4) ; bloquant avant tout GPS continu.
      Preuve (ff0c118, 7e5ccab) :
      - consentement donné ou retiré, tenu dans le registre de M4 ; sans consentement actif, le fix
        est ignoré et le pointage passe en mode manuel, en revue ;
      - positions chiffrées avant écriture ; une clé par technicien dans `opsys.cles_chiffrement`
        (migration 0007), détruite à l'échéance : le maillon ne change pas et la position devient
        irrécupérable ;
      - échéance citée de la politique (12 mois) ; `fin_contrat_travail` fournie par l'appelant,
        sinon purge refusée ; la purge est N5 (propriétaire et attestation) ;
      - chaque lecture d'une position est journalisée ; `m4_demarrer_route` suit l'heure serveur ;
      - M4 741, M6 382, socle 392, gate BMAD de M4 vert.

      Reste : les décisions « Rétention du GPS » ci-dessous ; la ligne GPS de l'EFVP (§6) ; la
      revue externe du chiffrement.
- [x] T4.3 M7 : consentement client et floutage visages et plaques avant tout contenu public ;
      profil de marque par défaut remplacé par celui du client (audit M7).
      Preuve (cc8a64a, 92a843a) :
      - le consentement est lu dans le WCT reçu par le bus (registre `wct_recus` de M7), jamais
        dans les arguments de l'outil ; `wct_id` inconnu ou consentement faux : aucun brouillon ;
      - floutage par pixellisation déterministe, détecteur injectable ; sous le seuil de confiance
        fourni, le brouillon exige une revue humaine ; rien n'est jamais publié par M7 ;
      - briques retenues : OpenCV (Apache-2.0), YuNet (MIT), cascade Haar d'OpenCV (Apache-2.0) ;
        YOLO d'Ultralytics refusé (AGPL-3.0) ;
      - profil de marque fermé tant que l'identité n'est pas configurée (nom commercial en GATE
        NATHAN) ; l'identité d'OPSYS-AI n'y figure plus ;
      - M7 568, socle 392, M4 741, verifier 117 outils.

      Reste : brancher l'adaptateur OpenCV réel (`opencv-python-headless` n'est pas installable
      dans le bac à sable) et le décodage des photos déposées (T1.4-e2) ; un registre de retrait
      du consentement marketing (Loi 25) ; les consommateurs du bus ne voient pas l'`evenement_id`
      (contrat du répartiteur).

## T5 — Durcissement et SaaS

Secrets chiffrés, RBAC par métrique, Loi 25 (consentements, rétention, export, effacement),
multi-instances, sauvegardes, observabilité, veille de sécurité du fork (mensuelle).

- [ ] T5.1 Lint des départements : `ruff` ne couvre aujourd'hui que le socle (`src`, `tests`) ; l'audit M1
      relève 122 avertissements dans M1. Étendre la CI aux départements après correction.
      Avancement, partiel (T5.1 reste ouverte : M3 à corriger) :
      - M5 à zéro (20 avertissements avant, dont 14 `sys.path.insert` de tests), M5 321 verts, gate
        BMAD de M5 vert ; ajoutée à `DEPARTEMENTS_LINT` ;
      - M7 à M10 passent `ruff check` à zéro (M7 257, M8 18, M9 22, M10 46 avertissements avant) ;
        sans `noqa`, sans changement de configuration. Le contournement `sys.path.insert` des
        tests M8 à M10 est retiré : `pythonpath` de `pyproject.toml` suffit (M7 l'avait déjà fait).
      - M4 (139 avertissements avant) et M6 (57 avant) passent `ruff check` à zéro ; M4 852 et M6 425
        verts (mêmes effectifs qu'avant), gates BMAD de M4 et de M6 à sortie identique à l'avant
        (TOUT VERT) ; ajoutées à `DEPARTEMENTS_LINT`. Le contournement `sys.path.insert` de 34 tests
        est retiré (79 des 196 avertissements étaient des E402 qu'il causait) ; sans `noqa`, sans
        changement de configuration, aucun texte d'outil ni de verdict touché. Hors tests, la logique
        ne bouge pas : imports triés, annotations modernisées, conditions imbriquées fusionnées
        (`ecarts.py`, `digest.py`), un if/else en ternaire et une variable morte retirée
        (`pointage.py`) ; les visiteurs AST des
        gardes (`digest.py`, `outbox.py` de M4 ; `conformite.py` de M6) reçoivent leur état par le
        constructeur au lieu d'une fermeture sur la variable de boucle (B023). Le contrôle d'accès par
        intervention (T1.4-k1, `acces.py`) n'est pas touché.
      - M1 (118 avertissements avant) passe `ruff check` à zéro ; M1 414 verts (même effectif qu'avant,
        même répartition par fichier). M1 n'a pas de gate BMAD (`docs/bmad` ne porte que les trois
        artefacts de cadrage) ; ajoutée à `DEPARTEMENTS_LINT`. Le contournement `sys.path.insert` de
        9 tests est retiré (`pythonpath` de `pyproject.toml` suffit ; la garde
        `test_aucun_sys_path_insert_vise_le_paquet` reste verte) et les 2 blocs d'imports collés au
        milieu de `test_consentement.py` sont remontés en tête. Sans `noqa`, sans changement de
        configuration, aucune logique touchée : imports triés, annotations `X | Y`, deux
        `.format` passés en f-string (`garde_fou.py`), un `if` final et une boucle réduits à
        `return`/`any` ; trois variables mortes de tests retirées, `zip(strict=True)`, `contextlib.suppress` et
        un `if` fusionné dans trois tests. Preuve de valeur identique : les 27
        motifs compilés de M1 (`pattern` et drapeaux) et toutes les constantes de module sont égaux
        avant/après (dont `MONTANT_MONETAIRE` et `VERBES_EXECUTION`, où la ligne de 230 caractères est
        coupée entre deux littéraux adjacents, sans saut de ligne dans la chaîne) ; `outils.py`
        (descriptions d'outils) a un AST identique. Seuls des docstrings (`contrats.py`, 4 tests) sont
        reformatés sur plusieurs lignes.
      - M2 (140 avertissements avant) passe `ruff check` à zéro ; M2 817 verts (mêmes effectif et
        mêmes identifiants de test qu'avant), gate BMAD de M2 à sortie identique à l'avant (TOUT VERT),
        deux scripts `preuve_*.py` à sortie identique ; ajoutée à `DEPARTEMENTS_LINT`. Le contournement
        `sys.path.insert` de 14 tests est retiré (`pythonpath` de `pyproject.toml` suffit ; les
        sous-processus de test gardent le leur, la garde `test_aucun_sys_path_insert_vise_le_paquet`
        reste verte) ; les deux scripts `preuve_*.py`, qui tournent hors pytest, gardent l'insertion et
        importent le paquet par `importlib` après elle. Sans `noqa`, sans changement de configuration.
        `verdicts.py` et `horodatage.py` (gelés par empreinte SHA-256, CA-M2-13) n'avaient aucun
        avertissement et restent octet pour octet ; `acces.py` (T1.4-k2) et `outils.py` ne sont pas
        touchés. Hors tests, la logique ne bouge pas : imports triés, `datetime.UTC`, un import mort
        retiré (`statuts.py`), un `if` imbriqué fusionné (`digest.py`), un if/else en ternaire
        (`readiness.py`), le mode `"r"` redondant de `open` retiré (`fixtures_garde.py`) ; `verif_coherence.py` remonte son import et renomme `l`. Preuve de valeur
        identique : toutes les constantes de module et les chaînes des fonctions de `src/` sont égales
        avant/après (seul `"r"` disparaît), les descriptions, paramètres, autonomies et rôles des 12
        outils aussi ; l'AST de chaque module est identique hors imports, sauf ces trois fichiers.
        Dans les tests : quatre variables mortes retirées, `pytest.raises(CodeVerdictInconnu)` au lieu
        de `Exception`, `zip(strict=True)`, un if/else en ternaire, trois docstrings recoupés sur deux
        lignes, les messages d'assertion coupés entre littéraux adjacents (valeurs identiques).
      - CI : l'étape « Lint du département » du job `departement` ne tourne que pour les dossiers de
        `DEPARTEMENTS_LINT` (M1, M2 et M4 à M10). Pour étendre : corriger un département, puis ajouter son
        dossier à cette liste unique ; `tests/test_ci_departements.py` vérifie qu'il est propre.

## Décisions attendues de Nathan (GATE NATHAN, ne bloquent pas la boucle)

- Nom commercial : « Gouttières et Revêtements Synergy » ou « … Lanaudière » (définition §13.4).
- Portée SaaS de M5 (§13.8).
- Licence d'OPSYS (`LICENSE` Apache-2.0 ou propriétaire, ADR-0003).
- Identifiants : Twilio, QuickBooks, CCube, Stripe, Plaid, Google (Ads, Search Console, Business
  Profile), Meta, TikTok, LinkedIn, YouTube.
- Rotation de la clé fuitée (#612).
- **Localisation des chantiers (T4.1-a)** : garder `m4_confirmer_localisation` en N3, exiger une
  identité d'appareil, ou passer en N4 avant de promouvoir M4 hors du mode ombre ; échéance de
  rétention des adresses et coordonnées de chantier (aucune politique ne la fixe encore).
- **Cédule et géocodage (R15 §7)** : confirmation humaine de chaque correspondance d'adresse
  « Bâtiment » en v1 (recommandée) ; RAM et disque du VPS pour un sidecar OSRM et l'extrait
  régional ; avis d'un juriste sur le graphe OSRM dérivé (ODbL), l'attribution CC-BY du RQA et
  un éventuel géocodeur gouvernemental ; fond de carte pour confirmer sur carte (EFVP §5).
- **Coût réel (T1.5-d, M5)** : taux horaire de main-d'œuvre (par équipe ou par personne) et unité
  de chaque prix du livre de prix M6 ; seuils de réapprovisionnement par article (M6).
- **Confidentialité du contexte (T3.3-suite-b)** : `CLIENT_PRIVATE` visible de M1 et M2 seulement
  (choix par défaut à valider).
- **Demande d'avis (T1.5-d, M7)** :
  - un client insatisfait (`client_satisfait=false`) ne reçoit pas de demande d'avis (règle de
    T1.2-c) ; or les plateformes d'avis interdisent de ne solliciter que les clients satisfaits
    (P9) ; garder ou retirer ?
  - les énoncés de consentement `consentement-client-fr-CA-v1` sont une proposition, à valider
    par Nathan ou un juriste (T3) ;
  - le retrait d'un consentement n'a encore aucun mécanisme dans le moteur.
- **Lien automatique session → affaire (T2.1-b)** : aujourd'hui, un humain lie la session d'un
  client à son lead (`m10_lier_session_affaire`, N3). Faut-il qu'une règle écrite le fasse à la
  création du lead ? La clé de session contient le numéro du client : elle ne voyage jamais dans
  l'événement. Le lien donne à l'agent le paquet de contexte de l'affaire et lève le blocage N3+.
- **Seuils métier** (définition §13.11) :
  - M6 démarre avec un seuil de variance de chantier de 30 % ;
  - M6 signale un écart de prix à la réception au-delà de 15 % (`department.yaml`) ;
  - ces valeurs sont à confirmer par le propriétaire, et elles deviendront des réglages par
    instance (tableau de bord).
- **Mode autonome et N4** : ADR-0009 fait exécuter automatiquement un N4 (engagement : envoi de
  facture, prix, dépense) en mode autonome, alors qu'AGENTS.md réserve les engagements externes
  aux humains.
  - Proposition : aucun mode n'exécute un N4 sans approbation, et le seuil du mode autonome passe
    à N4.
  - Aucun risque immédiat : les dix départements sont en mode ombre, qui exige une approbation dès
    N3.
- **Revue externe du code critique** (AGENTS.md), avant tout passage sur `main` :
  - M5 : 119a594, 23df6eb, T1.3-c ; vue financière d'un appel d'appareil (T1.4-k2) : 1ef9499 ;
    coût réel et rentabilité (T1.5-d) : b217aea ;
  - idempotence du socle : 764c292, 2474cd1 ;
  - approbations : 718b9bb ; décision depuis l'appareil du propriétaire (T1.4-f étape 6) : ed0af65 ; exécution directe des actions d'un humain authentifié (T1.4-h) :
    688b1a4 ; portées d'outils par rôle d'appareil (T1.4-j) : a0e5150 ;
  - validation du bus : 4c9fbff ;
  - authentification de `/tools/invoke` par jeton d'appareil : 42bbf6a ; `_meta` MCP unique par
    processus : d7d77d5 ; porte d'appareil vers l'outil MCP du département (T1.4-c6) : 1b7e14f ;
  - chiffrement et purge des positions GPS : ff0c118 ; localisation chiffrée des chantiers et
    masquage de la trace (T4.1-a) : 4349de4 ;
  - commits plus anciens déjà listés dans les preuves de T1.0 et T1.1.
- **Arrondi monétaire** : M5 arrondissait au pair (mode par défaut de Python) alors que M3
  arrondit au demi supérieur. La correction cite la règle de l'ARC (TPS) et de Revenu Québec
  (TVQ) ; elle passera par la revue externe du code critique.
- **Géolocalisation** : `POLITIQUE-geolocalisation.md` interdit tout suivi continu (points au punch
  seulement) alors que la définition §9.2 prévoit la localisation en arrière-plan pendant le travail.
  Proposition R12 : arrière-plan seulement pendant la fenêtre « en route » d'un chantier. À valider
  (Nathan ou juriste) avant toute livraison du GPS. Même besoin : une politique pour les photos et les
  signatures.
- **Rétention du GPS (T4.2)** :
  - la politique fixe 12 mois avec la mention « À VÉRIFIER — juriste » ; le code l'applique telle
    quelle ;
  - aucun département ne connaît la date de fin du contrat de travail : elle est demandée à chaque
    purge ; un futur registre RH pourrait la fournir ;
  - sans fix GPS, un pointage part en revue (choix prudent) ; l'autre option est de croire la
    déclaration manuelle ;
  - une clé détruite survit dans les sauvegardes (14 jours en local ; avec restic, jusqu'à 12
    copies mensuelles), et une restauration la ressusciterait : durée des sauvegardes et
    réapplication des purges après restauration à décider ;
  - `GABARIT-EFVP.md` §6 n'a pas encore de ligne pour les positions GPS.
- **Portées des rôles d'appareil (T1.4-j, `docs/architecture/ROLES.md`)** :
  - `admin` déclaré outil par outil plutôt que « tout hors T3 » ;
  - le vendeur voit coût et marge de ses devis (§9.4 « voir risques et marge ») ; une vue
    « vendeur » sans coût est possible ;
  - l'employé ne peut pas encore retirer son consentement GPS depuis l'app (T1.4-k) ;
  - aucun filtre par propriétaire de lead : tous les vendeurs voient tous les leads (T1.4-k).
- **Actions d'un employé depuis l'app (T1.4-h)** : en mode ombre, chaque pointage et chaque
  complétion d'un employé part en approbation chez le propriétaire, ce qui rend l'app inutilisable.
  Proposition : l'employé authentifié qui agit lui-même dans la portée de son rôle valide au départ
  les N3 ; les N4 et N5 restent au propriétaire.
- **Politique « photos »** : `POLITIQUE-photos-non-contractuelles.md` est une proposition ; la
  garde de M3 refuse toute collecte réelle tant qu'elle n'est pas validée (Nathan ou juriste).
- **Prompts maîtres d'origine des départements** (annexe A de la définition) : ils portent le
  détail fonctionnel (routes, tables, KPI, scénarios de test). Exemple : les 21 sections du rapport
  de décision M9, dont la définition ne liste qu'une douzaine (audit M9).
