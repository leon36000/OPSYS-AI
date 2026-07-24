# AGENTS.md — Méthode PROOF v2.0 — OPSYS-AI
<!-- Canonique cross-outils (Claude Code, OpenCode, Codex...). Claude Code l'importe via @AGENTS.md
     dans CLAUDE.md. ≤150 lignes. Consultatif ici; ENFORCEMENT dans hooks/scripts/CI; constitution
     longue dans CANON/ et PROTOCOLE-PROOF. -->

## Profil PROOF de ce projet : PROOF-Team

## La méthode PROOF
- **P — Preuve avant DONE** : DONE-avec-preuve ou BLOCKED-avec-raison. Rien d'autre.
- **R — Revue indépendante scellée** : Solo = 1 reviewer vendor ≠ codeur; Team = 3 reviewers /
  3 vendors, verdicts scellés, dépouillement par script (`~/proof-method/scripts/civ_review.py` →
  `tally_reviews.py`). Le tally VÉRIFIE mécaniquement (pas seulement compte) : **sceau** — tous les
  verdicts portent le même `prompt_sha256` (les reviewers ont vu le prompt byte-identique, sinon
  INVALIDE) ; **décorrélation** — N vendors DISTINCTS (`vendor_of`, anti-Sybil : deux modèles du
  même fournisseur ne comptent que pour un). Livraison par le script, JAMAIS à la main (le copier-
  coller change le prompt → sceau rompu).
- **O — Orchestrateur unique** : le modèle actif en session lead; ne se relit JAMAIS lui-même.
- **O — Outils déterministes = autorité** : hooks/gates bloquent; aucun LLM n'écrit un score.
- **C — CLAIMS UNVERIFIED** : toute sortie d'un modèle de l'équipe est une AFFIRMATION non vérifiée
  jusqu'à preuve par source objective (`gh api`/exécution réelle > mémoire de modèle). Un vote
  « fabrication/inventé » d'un reviewer sans navigation est de la mémoire, pas une preuve — arbitrer
  par la source. Vérifier avant de relayer ou merger.
- **F — Frontières humaines (T3)** : paiements, secrets prod, suppressions définitives,
  publication/déploiement public, engagements externes = humain seul.
Philosophie : liberté sur le chemin, rigueur sur les sorties. Le blocage honnête est un résultat
acceptable; l'exception silencieuse jamais.

## Projet
OPSYS-AI — core d'entreprise autonome clé en main, 10 modules (M1..M10), premier module M7 Marketing (D-008). Stack : Python 3.12 (stdlib d'abord ; PyYAML pour M7-S000).

## Commandes
- Tests : `python3 -m pytest scripts/tests -q` (TDD : RED → GREEN → REFACTOR — tests d'abord, toujours) ; les tests des modules s'ajoutent au fil des stories.
- Lint : `python3 scripts/structure_lint.py` — exporté en `PROOF_LINT_CMD` pour le pre-commit.
- Jamais de commit direct sur main. PR uniquement. Jamais `--no-verify` (hook le bloque).

## Couches d'exécution (qui fait quoi)
1. **LiteLLM** (routing) : `opus`/`sonnet`/`haiku` → passthrough Claude réel (Orchestrateur);
   `crew-*` → équipe; reviewers appelés en direct par script, hors alias. Logs = preuve.
2. **Claude Code** (cockpit) : Orchestrateur + dispatch des codeurs. Hooks = gates en session.

## Dispatch des codeurs crew-* — DEUX modes (choisir selon le passthrough)
- **Mode natif (subagent)** : `subagent_type: codeur-bulk|codeur-longues` — EXIGE le passthrough
  Bloc A câblé (`ANTHROPIC_BASE_URL`→LiteLLM + clé Anthropic). Sinon Claude Code envoie « crew-* » à
  api.anthropic.com qui répond « model may not exist » (prouvé 2026-07-16).
  ⚠️ COÛT : câbler le Bloc A reroute TOUTE la session par la clé API = facturation AU TOKEN, ce qui
  contourne un abonnement Max/Pro. Sur abonnement Claude Code → NE PAS câbler ; utiliser l'appel-direct.
- **Mode appel-direct (défaut sans Bloc A)** : `~/proof-method/scripts/crew_dispatch.py --model
  crew-coder-bulk --spec <tâche> --out <fichier>` — appelle LiteLLM en HTTP direct (comme
  civ_review pour la revue). Le codeur crew GÉNÈRE, l'Orchestrateur APPLIQUE + exécute les tests
  (TDD/gates inchangés). Les implémentations partent RÉELLEMENT sur crew-* (prouvable Langfuse :
  deepseek/kimi/glm, jamais Claude).
3. **Superpowers** (colonne workflow) : brainstorming → writing-plans → subagent-driven → TDD.
4. **Couche PROOF projet** (ce repo) : `skills/` overrident Superpowers là où PROOF diffère;
   hooks/scripts = enforcement. Priorité skills : projet > perso > vendor. Fichiers vendor JAMAIS édités.

## Overrides PROOF sur Superpowers (non négociables)
- Revue : JAMAIS de self-review inline. Fin d'implémentation ⇒ skill `proof-review`
  (revue aveugle scellée multi-vendor HORS session, dépouillée par script).
- Complétion : skill `proof-done` — preuve d'exécution réelle + entrée registre, sinon BLOCKED.
- Subagents : toute sortie se termine par `PREUVE:` ou `BLOCKED:` (hook SubagentStop renvoie sinon).

## Équipe (défauts roster — confirmer en Phase 0; Team = reviewers TOUJOURS 3 vendors distincts)
| Rôle | Modèle | Mécanisme |
|---|---|---|
| Orchestrateur (code le plus dur, signe sur pièces) | Modèle actif Claude Code | session lead |
| Architecte — revue AVANT code structurel | Kimi-K3 (GLM-5.2 RETIRÉ — fuit son raisonnement, ADR-0003 R-038) | dispatch `--difficulty difficile` |
| Codeur missions longues / multi-fichiers | Kimi K2.7 Code | subagent `model: crew-coder-long` |
| Codeur bulk / tâches mécaniques | DeepSeek V4 Pro | subagent `model: crew-coder-bulk` |
| Codeur TUI/UX · Codeur parallèle | Composer 2.5 · Grok 4.5 | sessions/worktrees dédiés |
| Reviewers aveugles ×3 | DeepSeek V4 Pro · Gemini 3.1 Pro · LongCat 2.0 | `civ_review.py` hors session |
| Pool rotation (route instable, journalisée) | Kimi K2.7 · Qwen 3.7 Max · MiMo 2.5 Pro | idem |
| Sentinelle qualité (jamais codeuse; peut ROUVRIR) | DeepSeek + Qwen3.7-Max tandem (ADR-0003) | script / CI |
| Synthétiseur de preuves (rapports d'étape) | MiMo 2.5 Pro (= MiMo-Pro-V2, nom canonique) | script |
| Documentaliste / canon | Qwen3.8-Max (ADR-0003 ; ex-Gemini-3.6-Flash) | `doc_keeper.py` |
Contraintes : reviewer jamais du même vendor que le codeur de la story — si conflit (ex. story
codée par haiku/DeepSeek), swap automatique vers le pool (vendor distinct), journalisé; Composer
et Grok (même vendor xAI) jamais appariés en review; le code de l'Orchestrateur relu par 3 vendors
≠ le sien. Équipe d'exécution = 100 % cloud (protocole Phase 2); locaux = infra seulement.
opus/sonnet/haiku = réservés au passthrough Claude réel (Orchestrateur); jamais réutilisés pour un
poste d'équipe (collision CIV directe sinon). JAMAIS CLAUDE_CODE_SUBAGENT_MODEL en global.

## Choix du codeur par DIFFICULTÉ (qualité) × COÛT — pas seulement par coût
La qualité finale est garantie par les GATES + la revue scellée, pas par le codeur ; mais le bon
codeur réduit les allers-retours. Assignation (abonnement Max = subagents Claude inclus, forfait) :
- **Tâche dure / structurelle / multi-fichiers / exploratoire → subagent `general-purpose` (Claude,
  Max, outils complets, TDD itératif) ou l'Orchestrateur.** Haute qualité, coût forfait, pas de
  clé API. Reviewers = 3 vendors NON-Anthropic (indépendance intacte : codeur Claude ≠ reviewers).
- **Tâche mécanique / bien spécifiée / bulk → `crew_dispatch.py` (DeepSeek/Kimi).** Bon marché ;
  génération single-shot, l'Orchestrateur applique + teste. Réserver au code sans exploration.
- **Story critique (T2/T3) → skill `proof-tdad`** (Spec→RED→GREEN→vérif exécution) + revue archi
  (`architecte`) AVANT code.
- **TOUJOURS → revue scellée 3 vendors** = l'autorité qualité réelle (un mauvais code échoue aux
  tests ou est REJETÉ). Ne jamais confondre « pas cher » et « bon » : le tier de difficulté décide.

## Pipeline par story (le seul chemin autorisé)
Story → context pack scopé → architecte si structurel → codeur assigné PAR DIFFICULTÉ (voir ci-dessus ;
PAS l'Orchestrateur par défaut pour le bulk, MAIS Claude/Max pour le dur) → TDD RED/GREEN/REFACTOR
→ gates locaux (lint, secrets, no-stub, sweep des symboles touchés)
→ PR → gates CI → `proof-review` (scellée) → tally script → [pas de consensus : Delphi anonymisé,
max 2 rounds, puis arbitrage sur pièces journalisé] → signature Orchestrateur SUR PIÈCES → merge
→ registre horodaté → doc à jour (gate BLOQUANT pre-commit docs-drift-scan : tout changement d'outil exige un artefact doc).

## Interdits absolus (hooks et no-stub-scan les bloquent)
Stubs (pass, NotImplementedError, ..., corps vides), TODO/FIXME/HACK dans un diff, tests sans
assertion, `assert True`, skip sans justification au registre, données inventées, DONE partiel,
affirmation factuelle sans source vérifiable, `--no-verify`, commit direct sur main, force-push
main, auto-approbation. Mocks : tests/ seulement, services externes seulement.

## Registres & périmètre
Registres append-only hash-chaînés dans `Registres/` via `scripts/ledger_append.py` (jamais à la
main); toute entrée DONE porte sa preuve (le gate rejette sinon). Confinement au workspace du repo.
Secrets : jamais dans Git ni registres. Sources contenu : web public + documents fournis explicitement.
Coexistence des registres : `registries/ledger/*.jsonl` = registre PROJET OPSYS-AI, vérifié en CI ; `Registres/*.jsonl` = registre MÉTHODE proof-method. Cf. ADR-0002.

## Méthodologie-as-code
Les métriques de gouvernance au registre (taux de rejet en revue par modèle, bugs introduits par
poste) sont la suite de tests de la méthode : réassignations pilotées par les DONNÉES. Amendements :
PR sur le repo proof-method + circuit de revue Team. Jamais de fork silencieux de la méthode.

