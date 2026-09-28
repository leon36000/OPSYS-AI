# Documentation OPSYS-AI — carte

Ce document recense ce qui existe sous `docs/` (et ce qui en dépend directement à la racine du
dépôt), classé par sujet. Décisions fondatrices de l'état courant :
[ADR-0006](decisions/ADR-0006-restructuration-v2-core-hermes.md) (restructuration v2) et
[ADR-0007](decisions/ADR-0007-core-openclaw.md) (core = OpenClaw, remplace le point 1 d'ADR-0006).

## Au-dessus de `docs/` — la couche constitutionnelle

Avant tout document ci-dessous, trois fichiers à la racine du dépôt gouvernent l'exécution :

| Fichier | Rôle |
|---|---|
| [`AGENTS.md`](../AGENTS.md) | Règles v2 : le produit, l'arborescence, les commandes, les principes (PROOF allégé), les interdits, la provenance des briques open source, l'économie de tokens, Git. |
| [`CLAUDE.md`](../CLAUDE.md) | `@AGENTS.md` + rappels pour Claude Code : lectures préalables, référence M3, gates avant commit, sorties `PREUVE:`/`BLOCKED:` des sous-agents. |
| [`00-DIGEST.md`](../00-DIGEST.md) | Rappel d'une page : preuve avant DONE, le code calcule, frontières T3, interdits, économie de tokens, provenance des briques. |

## Architecture

| Document | Contenu |
|---|---|
| [`architecture/ARCHITECTURE.md`](architecture/ARCHITECTURE.md) | Vue d'ensemble : couches (OPSYS-CORE, capacités MCP, départements, profils, modèles, mémoire, déploiement), principes non négociables, flux type d'une demande de soumission. |
| [`architecture/DEPARTEMENTS.md`](architecture/DEPARTEMENTS.md) | Comment construire un département : arborescence, `department.yaml`, contrat d'outil (`outils.py`), politiques d'autonomie T0-T3, `SOUL.md`, skills, tests exigés. Référence vivante : `departments/m03-estimation/`. |
| [`architecture/ECONOMIE-TOKENS.md`](architecture/ECONOMIE-TOKENS.md) | Stratégie en couches : déterministe d'abord, cache de prompt (natif OpenClaw), compaction, budgets par département (SQLite OPSYS + `tpd_limit` LiteLLM), paliers de modèles, passerelle LiteLLM (intégrée), métriques, règles d'écriture. Chaque mécanisme distingue implémenté / prévu. |
| [`architecture/TAXONOMIE.md`](architecture/TAXONOMIE.md) | Taxonomie métier partagée (T0.13) : catalogue des services (gouttières, revêtement, soffite/fascia, réparation), profil d'entreprise `$OPSYS_HOME/entreprise.yaml`, fail-closed, contrat `LeadQualifie` v2 (version explicite), garde de dérive. |
| [`architecture/MOBILE.md`](architecture/MOBILE.md) | Application mobile OPSYS : phase 1 (apps officielles OpenClaw iOS/Android/Wear OS appairées à la passerelle OPSYS, sans développement), phase 2 (fork rebrandé par profil : Patron, Estimateur, Chef d'équipe, Réception). Publication sur les stores = frontière T3. |

## Décisions (ADR)

| Document | Contenu |
|---|---|
| [`decisions/README.md`](decisions/README.md) | Index des 7 ADR, ce qui fait autorité aujourd'hui (ADR-0006 + ADR-0007), nuances de statut des ADR historiques et de la supersession partielle. |
| `decisions/ADR-0001` … `ADR-0005` | Historiques, conservés pour la traçabilité, remplacés par ADR-0006 (voir l'index). |
| `decisions/ADR-0006` | Restructuration v2 (départements, règle d'or, économie de tokens, déploiement, méthode allégée) ; son point 1 (choix du core) est remplacé par ADR-0007. |
| `decisions/ADR-0007` | Décision en vigueur pour le core : OPSYS-CORE = **OpenClaw** épinglé (Hermes Agent devient runtime alternatif optionnel). |

## Recherche

| Document | Contenu |
|---|---|
| [`research/00-BRIEF.md`](research/00-BRIEF.md) | Brief commun aux 10 missions de recherche de briques open source (exigences dures, contraintes de licence, règles de vérification). |
| `research/R1-core-openclaw.md` … `research/R10-m9-capabilities.md` | Les 10 rapports de recherche complets, domaine par domaine (core, passerelle/tokens, mémoire/RAG, déploiement, M1..M10), licences vérifiées à la source. |
| [`research/INGREDIENTS.md`](research/INGREDIENTS.md) | Catalogue condensé des briques **retenues** (et refusées) extrait des 10 rapports, avec licence, rôle, mode d'intégration et phase (intégré / phase 2 / référence). |

## Mémoire (RAG)

`docs/memory/RAG-PREMIUM.md` (prérequis explicite d'ADR-0006 point 6) **vient d'être rédigé** — statut
qu'il se donne lui-même : *« conception de référence… la phase 1 est implémentée et testée dans
`src/opsys/memoire/` »*, fondée sur R4 + la documentation mémoire d'OpenClaw (`memory-architecture.md`,
`dreaming.md`, `memory-provenance.md`…) + la LPRPSP (Loi 25) citée article par article. **Non audité
dans le cadre de cette mise à jour** (hors des 4 fichiers confiés) — à vérifier indépendamment avant de
le citer comme définitif. Catalogue de briques source : [`research/INGREDIENTS.md`](research/INGREDIENTS.md)
§« Mémoire / RAG », lui-même issu de [`research/R4-memory-rag.md`](research/R4-memory-rag.md).

## Ops / déploiement

`docs/ops/` et `deploy/` viennent d'être complétés (agents en cours au moment de cette carte,
non audités ici au-delà de leur existence) :

| Document | Contenu |
|---|---|
| [`../core/PROVENANCE.md`](../core/PROVENANCE.md) | Provenance du fork dur OPSYS-CORE (release et commit OpenClaw d'origine, élagage reproductible, veille de sécurité — ADR-0008) et surfaces de configuration consommées par la couche Python. |
| [`../core/patches/README.md`](../core/patches/README.md) | Patchs pnpm de dépendances tierces du core, hérités de la release d'origine (texte d'origine en anglais). |
| `ops/INSTALLATION-VPS.md` | Installation sur un VPS neuf (public : opérateur), renvoie à `ARCHITECTURE.md` et ADR-0007. |
| `ops/EXPLOITATION.md` | Commandes d'exploitation courantes depuis `deploy/` (`docker compose logs`, etc.), suite d'INSTALLATION-VPS.md. |
| `../deploy/` (hors `docs/`) | `docker-compose.yml`, `Dockerfile`, `install.sh`, `backup.sh`/`restore.sh`, `Caddyfile`, `.env.example` — plus câblé que ce que R5 anticipait comme entièrement prévu. |
| [`research/R5-deploy-dashboard.md`](research/R5-deploy-dashboard.md) | Recherche complète : empaquetage VPS, reverse proxy, données/sauvegardes, auth, secrets, observabilité, durcissement — écrite avant ADR-0007 ; comparer à `deploy/` réel plutôt que la relayer telle quelle pour ce qui est aujourd'hui construit. |

## Conformité (Loi 25)

| Document | Contenu |
|---|---|
| [`compliance/politiques/README.md`](compliance/politiques/README.md) | Index des politiques de protection des renseignements personnels (statut : propositions, validation finale = Nathan, T3). |
| `compliance/politiques/POLITIQUE-consentement-sms.md` | Consentement SMS/WhatsApp (M1/M7). |
| `compliance/politiques/POLITIQUE-enregistrements-appels.md` | Enregistrements d'appels (M1 Front Office). |
| `compliance/politiques/POLITIQUE-geolocalisation.md` | Géolocalisation et pointage géorepéré (M4). |
| `compliance/politiques/POLITIQUE-session-replay.md` | Session replay et CRO (M7). |
| [`compliance/efvp/GABARIT-EFVP.md`](compliance/efvp/GABARIT-EFVP.md) | Gabarit d'évaluation des facteurs relatifs à la vie privée (ÉFVP) et calendrier de destruction. |

Politiques encore en backlog (Plan maître §14.2, hors périmètre livré) : tracking client, profilage,
photos non contractuelles.

## Plan maître

| Document | Contenu |
|---|---|
| [`plan/GRS_Plan_Squelette_Maitre_v1.1_PERFECTION.pdf`](plan/GRS_Plan_Squelette_Maitre_v1.1_PERFECTION.pdf) | Source de vérité historique (D-001…D-045, R-001…R-033, REG-01…13, C-01…C-16), adoptée par [ADR-0001](decisions/ADR-0001-adoption-squelette.md). Conservée telle quelle après la restructuration v2. |

## Historique

| Document | Contenu |
|---|---|
| [`history/README.md`](history/README.md) | Ce que la restructuration v2 (septembre 2026) a retiré du dépôt et pourquoi (reviews, registres, outillage de méthode, canon/core/phase-c, produit-méthode ForgeAI…), comment le retrouver dans git (`fcb65bc`), leçons retenues de l'audit du 2026-09-28. |
