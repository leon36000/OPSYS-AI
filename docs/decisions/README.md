# Décisions d'architecture (ADR) — index

Les décisions d'architecture d'OPSYS-AI sont numérotées et immuables : réviser une décision veut dire
écrire un **nouvel** ADR qui la remplace explicitement, jamais éditer un ADR déjà accepté. Statut et
date ci-dessous sont repris tels quels de l'en-tête de chaque fichier.

| ADR | Titre | Statut (tel qu'écrit dans le fichier) | Date | Résumé |
|---|---|---|---|---|
| [0001](ADR-0001-adoption-squelette.md) | Adoption du squelette v1.1 + méthode PROOF STACK | Accepted (immuable) | 2026-07-17 | Le plan `GRS_Plan_Squelette_Maitre_v1.1_PERFECTION.pdf` (D-001…D-045, R-001…R-033, REG-01…13, C-01…C-16) et le TEMPLATE PROOF STACK v1.1 sont la constitution d'exécution ; pipeline A→G = seul chemin autorisé. |
| [0002](ADR-0002-continuite-opsys-ai.md) | Continuité OPSYS-AI (renommage GRS) | Accepted (immuable) | 2026-07-23 | GRS renommé OPSYS-AI, continuité totale. Répartit les registres (`registries/ledger/` = projet, `Registres/` = méthode) et les dépouillements (`civ_review.py`/`tally_reviews.py` = revues de code, `scripts/tally.py` = Phase C). Les fichiers ForgeAI PROOF IDE System à la racine sont un référentiel produit-méthode **distinct**, sans lien avec l'exécution d'OPSYS-AI. |
| [0003](ADR-0003-RATIFICATION.md) | Ratification du consensus Phase C (décisions Nathan, T3) | Accepted (T3 — autorité Nathan) | 2026-07-24 | Tranche Q1–Q9 du consensus Phase C (11/11 APPROVED, 9 vendors) : roster CIV + règle anti-deadlock, ordre des modules (M7→M1→M2→M4→M3→M6→M8→M5→M9, M10 après M8), canaux SMS/WhatsApp en feature-flag OFF, licence **propriétaire**, profil **PROOF-Team**. Ajoute R-037/038/039 au registre des risques et la clause de **portabilité** (zéro dépendance à l'infra personnelle de Nathan). |
| [0004](ADR-0004-independent-agent-ownership.md) | Équipes indépendantes et ownership explicite (Codex / Claude Code) | Proposé (directive appliquée opérationnellement ; enregistrement canon différé) | 2026-08-26 | GitHub = source mutable partagée ; Codex avance le Core, Claude Code traite les issues et l'assainissement transversal ; exactement un owner par mission ; aucun code métier M avant le handoff Core. |
| [0005](ADR-0005-fragment-github-control-non-executable.md) | Requalification du fragment `.opsys/tools/github-control/` en NON-EXECUTABLE | Proposé | 2026-09-05 | Le fragment reste une racine scannée du contrat qualité mais est déclaré non-exécutable dans son propre README, état scellé par un test dédié — rien n'est retiré ni inventé. |
| [0006](ADR-0006-restructuration-v2-core-hermes.md) | Restructuration v2 : OPSYS-CORE bâti sur le code source de Hermes Agent | **Accepté** (chef de projet, mandat du propriétaire) ; **point 1 remplacé par ADR-0007** | 2026-09-28 | **Remplace ADR-0001 à ADR-0005** (conservés ci-dessous à titre historique) et le programme « Core-first » C00–C24. Décision courante (hors point 1, voir ADR-0007) : départements = agents/profils générés depuis `department.yaml` ; économie de tokens en couches ([`ECONOMIE-TOKENS.md`](../architecture/ECONOMIE-TOKENS.md)) ; mémoire = Postgres+pgvector (RAG premium en conception) ; déploiement = docker compose VPS ; méthode allégée (`AGENTS.md` v2). Briques retenues : [`INGREDIENTS.md`](../research/INGREDIENTS.md). |
| [0007](ADR-0007-core-openclaw.md) | OPSYS-CORE bâti sur OpenClaw (remplace le choix Hermes de l'ADR-0006) | **Accepté** (chef de projet, sur objection argumentée du propriétaire) | 2026-09-28 | **Remplace le seul point 1 de l'ADR-0006** (« OPSYS-CORE = Hermes Agent ») ; le reste d'ADR-0006 reste en vigueur. Décision courante : OPSYS-CORE = **OpenClaw** épinglé (`v2026.9.6`, commit `ce5bbdc2`) — mémoire d'agent native à provenance, apps mobiles officielles iOS/Android ([`MOBILE.md`](../architecture/MOBILE.md)), Control UI, automatisations, MCP natif (stdio + streamable HTTP). Départements = agents OpenClaw (`opsys-metier openclaw configurer`). **LiteLLM devient la passerelle de modèles par défaut** (alias de paliers, clé virtuelle + `tpd_limit` par département). Hermes Agent devient un **runtime alternatif optionnel** (`hermes_plugin.py`/`profils.py` conservés et testés). |
| [0008](ADR-0008-fork-openclaw-opsys-core.md) | OpenClaw devient OPSYS-CORE (fork dur) et l'architecture produit s'unifie | **Accepté** (ingénieur en chef, mandat du propriétaire) | 2026-09-28 | **Remplace ADR-0007 et le point 1 d'ADR-0006.** Fork dur de la release v2026.9.6 dans `core/`, renommé et élagué, sans synchronisation amont. Trois couches, une installation : core TypeScript (passerelle, agents, canaux, mémoire, dashboard), moteur métier Python (sources de vérité, services partagés), app mobile Expo à 4 profils. Répond aux points ouverts 1, 5, 6, 7, 9, 10 et 11 de la définition produit. |
| [0009](ADR-0009-socle-metier.md) | Socle métier : une base par instance, événements, approbations N0–N5, rôles et audit | **Accepté** (ingénieur en chef) | 2026-09-28 | SQLite par défaut et PostgreSQL en option (SQLAlchemy 2 Core + Alembic) ; métier, outbox, approbations et audit dans une même transaction ; échelle d'autonomie unique N0–N5 (correspondances T, F, M7) ; rôles P8 et signature par personne. |
| [0010](ADR-0010-memoire.md) | Mémoire : deux magasins, M10 gouverne, la « RAM » est le moteur de contexte | **Accepté** (ingénieur en chef) | 2026-09-28 | Couche A = mémoire native des agents ; Couche B = mémoire d'entreprise dans la base de l'instance (SQLite + FTS5 + sqlite-vec, PostgreSQL en option) ; M10 = gouvernance (statuts, confidentialité, ordre de vérité) ; RAM = moteur de contexte natif (4 paquets sous budget) ; PREFLIGHT/POSTFLIGHT sur les hooks du core ; embeddings locaux partagés ; cloisonnement entre agents. |
| [0011](ADR-0011-canaux-reception-envoi.md) | Canaux : réception sans modèle et envoi réel au client après approbation N4 | **Proposé** (décision du propriétaire, GATE NATHAN) | 2026-09-29 | Réception : le core appelle lui-même `m1_recevoir_message_canal` avant le tour, sous la file durable du canal (le crochet `message_received`, « fire and forget », est écarté) ; le modèle lit, il ne recopie plus. Envoi : le moteur tient le registre des envois (proposer en N2, envoyer en N4), le core exécute le texte exact, au plus une fois ; une issue inconnue va à « À voir », jamais rejouée ; STOP ne se lève jamais. Aucun appel du moteur vers le core, aucun secret de plus. Tranches T2.1-c1 à c9. |

## Ce qui fait autorité aujourd'hui

**La [définition produit](../produit/DEFINITION-PRODUIT.md) fixe le QUOI ; [ADR-0008](ADR-0008-fork-openclaw-opsys-core.md)
fixe le core et l'architecture.** ADR-0008 remplace ADR-0007 en entier et le point 1 d'ADR-0006 ;
le reste d'ADR-0006 (départements, règle d'or, politiques, économie de tokens, méthode allégée) reste
en vigueur tant qu'il ne contredit ni la définition ni ADR-0008. Les ADR 0001 à 0005 restent dans ce dossier **à titre
historique** (traçabilité de comment on en est arrivé là — voir aussi
[`docs/history/README.md`](../history/README.md), qui documente ce que la restructuration v2 a retiré
du dépôt et pourquoi) ; ils ne gouvernent plus l'exécution courante. En cas de désaccord apparent entre
un ADR historique et ADR-0006/0007, **le plus récent des deux (0007) prévaut** sur ce qu'il remplace
explicitement, et ADR-0006 prévaut sur tout le reste qu'il remplace.

Deux nuances de statut à connaître en lisant les fichiers eux-mêmes :
- ADR-0001, 0002 et 0003 se déclarent chacun *« Accepted (immuable — changer = nouvel ADR qui
  supersede) »* — ADR-0006 est précisément cet ADR qui supersède.
- ADR-0004 et 0005 sont restés au statut **Proposé** (leur propre en-tête le précise : enregistrement
  canon différé pour le premier, pas de mention de ratification pour le second) — ADR-0006 les
  remplace au même titre que les trois autres, sans que leur passage par un statut « Accepted » ait
  jamais eu lieu.

- ADR-0007 illustre la **supersession partielle** : au lieu de remplacer tout ADR-0006 (comme ADR-0006
  l'avait fait pour 0001-0005), il ne touche que le point 1 (choix du core) et le dit explicitement en
  en-tête (« Remplace : le point 1 de l'ADR-0006 »). Lire le point remplacé exige donc de lire les deux
  fichiers, pas seulement le plus récent.

Toute nouvelle décision d'architecture se numérote **ADR-0008** et suit le même principe : un fichier
neuf, jamais une édition d'un ADR existant.
