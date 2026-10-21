# ADR-0006 — Restructuration v2 : OPSYS-CORE bâti sur le code source de Hermes Agent

- Statut : **Accepté** (chef de projet, mandat du propriétaire du 2026-09-28)
- Remplace : ADR-0001 à ADR-0005 (conservés à titre historique), programme « Core-first » C00–C24
- Date : 2026-09-28

## Contexte

L'audit du 2026-09-28 a montré trois choses.
- Le produit était arrêté depuis mi-août : l'effort partait dans l'outillage de méthode.
- Les 10 départements étaient des bibliothèques de règles en mémoire, sans Core, sans persistance
  et sans point d'entrée.
- Le Core maison était à 10–20 %.

Le propriétaire exige :
- une installation sur VPS ;
- un dashboard qui gère tout, y compris les modèles cloud et locaux ;
- une économie de tokens maximale ;
- une mémoire de premier ordre (RAG premium) ;
- des départements qui octroient aux agents les capacités dont ils ont besoin ;
- un Core fondé sur le code source d'un agent open source mature (candidats : « openclaw2 »,
  OpenClaw, Hermes Agent).

## Options évaluées (rapports dans `docs/research/`)

| Option | Constat vérifié | Verdict |
|---|---|---|
| `Agnuxo1/OpenCLAW-2` (« openclaw2 ») | 10 ★. Copie personnelle, non à jour, d'OpenClaw plus des expériences P2P. Aucun lien officiel | Écartée |
| `openclaw/openclaw` | MIT, 391k ★, fondation. MCP natif, canaux front-office complets. TypeScript : ≈ 6,5 M lignes dans `src/`, persistance SQLite seulement. Mono-tenant. CVE-2026-25253 et campagne ClawHavoc en 2026 | Excellente, mais un fork profond est irréaliste et le métier Python n'y entre que par IPC (MCP). **Gardée comme source d'ingrédients et référence de conception** |
| `NousResearch/hermes-agent` | MIT, Python (≥ 3.11), release hebdomadaire (v2026.9.24), image officielle. Surfaces d'extension couvrant tout le besoin : outils, 27 hooks, prompts, skills, fournisseurs de modèles (≈ 40 dont Ollama/vLLM/llama.cpp en « custom »), fournisseurs mémoire, moteurs de contexte, canaux (SMS, WhatsApp, courriel, Teams…), transports d'approbation. Dashboard web extensible **sans fork** (onglets, slots, routes FastAPI). Profils + « distributions » + Kanban multi-profils | **Retenue** |

Raisons décisives :
- même langage que les 24k lignes de règles métier existantes, donc une seule « sauce » ;
- chaque exigence du propriétaire a déjà un point d'extension natif ;
- un département correspond exactement à une « distribution de profil » Hermes.

## Décision

1. **OPSYS-CORE = Hermes Agent épinglé + file de patchs OPSYS + pack de plugins OPSYS.**
   - L'amont est épinglé par tag et commit (`core/UPSTREAM.md`).
   - Les modifications du code source amont sont des patchs versionnés (`core/patches/`), appliqués au
     build. On modifie le source quand il le faut, et une montée de version reste faisable.
   - Tout ce qui peut passer par une extension passe par le paquet Python `opsys`, et non par un patch.
2. **Départements = profils Hermes générés depuis `departments/<id>/department.yaml`.** Chacun comprend :
   - SOUL (mission, interdits) ;
   - outils déterministes (le code métier existant) ;
   - skills `SKILL.md` ;
   - cron ;
   - politiques d'autonomie T0–T3, appliquées par le hook `pre_tool_call` ;
   - budgets de tokens et KPIs.
   La coordination inter-départements passe par le Kanban Hermes, plus un journal d'événements métier
   dans PostgreSQL.
3. **Règle d'or : le code calcule, le LLM orchestre.** Prix, soldes, scores et cédules sont calculés
   par des outils déterministes testés. Le LLM qualifie, rédige et décide quel outil appeler.
4. **Modèles.** On s'appuie sur les fournisseurs Hermes, cloud et locaux, configurés depuis le
   dashboard. OPSYS ajoute des paliers (`local`, `rapide`, `standard`, `fort`) par département. La
   passerelle LiteLLM (cœur MIT) est optionnelle, pour les clés virtuelles et les budgets durs.
5. **Économie de tokens** en couches (`docs/architecture/ECONOMIE-TOKENS.md`) :
   - déterministe d'abord ;
   - cache de prompt (préfixe stable) ;
   - compaction Hermes ;
   - recherche d'outils à la demande ;
   - troncature des sorties d'outils ;
   - RAG ciblé ;
   - budgets par département ;
   - modèles locaux pour les tâches simples.
6. **Mémoire.** Un fournisseur mémoire OPSYS : PostgreSQL + pgvector + plein texte, fusion RRF et
   rerank. La conception premium (`docs/memory/RAG-PREMIUM.md`) est le prérequis. Mem0 et Graphiti
   sont des options de phase 2.
7. **Dashboard.** Dashboard Hermes, plus un thème OPSYS et un plugin UI OPSYS (Départements, Budgets
   et coûts, Approbations, Entreprise, Mémoire), avec ses routes API.
8. **Déploiement VPS.** Docker compose : image OPSYS construite `FROM` l'image officielle Hermes
   épinglée par digest, avec PostgreSQL 17 + pgvector, Valkey et Caddy (TLS). Ollama et LiteLLM sont
   des profils optionnels. `deploy/install.sh` fait l'installation en une commande.
9. **Méthode allégée** (`AGENTS.md` v2) : preuve avant DONE, CI comme autorité, frontières humaines
   T3. Fin des registres, des trios scellés obligatoires et du méta-outillage.
10. **Licences.** Le code amont MIT est conservé avec ses mentions. Les composants AGPL/GPL ne sont
    admis qu'en service séparé, non modifié. Les briques retenues sont listées dans
    `docs/research/INGREDIENTS.md`.

## Conséquences

- Le dépôt passe d'un monolithe de gouvernance à : `core/` (épinglage et patchs), `opsys/` (plugins),
  `departments/` (M1–M10), `deploy/` et `docs/`.
- Une montée de version de Hermes = changer le tag et le digest, rejouer les patchs, lancer la CI
  d'intégration.
- Risque : churn amont hebdomadaire. Mitigation : épinglage, patchs minimaux, tests de contrat du
  plugin.
- Risque : Hermes est pensé mono-utilisateur. Mitigation : une installation OPSYS = une entreprise
  = un VPS.
- Les briques OpenClaw restent des ingrédients : patrons de services locaux à la demande, discipline
  de cache, consolidation mémoire.
