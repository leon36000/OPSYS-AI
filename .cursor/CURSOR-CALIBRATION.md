# Cursor — calibration session OPSYS-AI

**Date :** 2026-07-23  
**IDE :** Cursor (secondaire — pas l'orchestrateur)  
**Modèle natif déclaré :** Grok 4.5 (Cursor) — ne pas router via LiteLLM  
**Dépôt :** https://github.com/leon36000/OPSYS-AI  
**Clone local :** `/media/pc1/Storage/Repo/OPSYS-AI`  
**Branche active observée :** `story/P0-1-installation-kit` (CLAIM Claude Code / crew)

## Autorité suivie (ordre)

1. Décisions humaines Nathan (T3)
2. Pack `ForgeAI-PROOF-IDE-System-v0.2-VALIDATED` (`START_HERE.md`, `AGENTS.md` pack, `FORGE_METHOD.md`, `IMPLEMENTATION_SPEC.md`)
3. Story active OPSYS-AI (`stories/P0-1-installation-kit.md`) — kit PROOF STACK v1.1 gouverne l'exécution produit
4. Conversation courante = jamais source de vérité

## Rôle Cursor (synergie)

- Orchestrateur principal : **Claude Code** (Phase 0→2 du pack ; story P0-1 en cours)
- Cursor : adaptateur secondaire — lecture, revue de diff, navigation ; écriture hors story dispatchée **seulement** si Nathan présent (pairing)
- CIV Grok : si Grok co-écrit une PR, Grok est **exclu** de `forge-reviewer-*` / revue de cette PR
- **Ne pas** claimer `P0-1`, ni modifier `AGENTS.md` / `CLAUDE.md` / `config.ini.example` / ledgers pendant le claim Claude

## Méthodologies actives

| Couche | Statut Cursor |
|---|---|
| PROOF Core (DONE/BLOCKED, CIV, ledger) | Adopté — fail-closed |
| Forge Design (inspiré BMAD, sans runtime BMAD) | Adopté pour conception non triviale |
| Superpowers (réel) | Actif dans harness Cursor/Claude plugins — pas encore Forge-patched (Phase 4) |
| Headroom / LLMLingua-2 | Config déclarée ; mode audit — pas d'implémentation Cursor avant Phase 5/6 |
| DSPy / GEPA | Lab seulement — interdit auto-promotion (Phase 7) |
| Mini-agents forge-* | Déclarés ; exécution réelle = Claude Code d'abord |

## Probe capacités (vérifié cette session)

| Capacité | Preuve | Verdict |
|---|---|---|
| GitHub repo OPSYS-AI accessible | `gh repo view leon36000/OPSYS-AI` → private, main | OK |
| Clone local + remote origin | `origin=https://github.com/leon36000/OPSYS-AI.git` | OK |
| Branche story claimée | `story/P0-1-installation-kit` + story file | OK — **ne pas écraser** |
| LiteLLM readiness | `http://192.168.1.149:4000/health/readiness` → healthy | OK |
| Python 3.12+ | 3.12.3 | OK |
| Cursor CLI | `/usr/bin/cursor` | OK |
| MCP Forge (parent cockpit) | filesystem, k8s, firecrawl, memory, atomic, self-knowledge, model-bridge | OK (workspace parent) |
| `.cursor/rules/00-forge.mdc` | installé depuis pack VALIDATED | OK |
| `.forge/config.ini` | créé, `api_key_env` assaini (pas de littéral `sk-`) | OK — `model_id` encore vides (Nathan) |
| Secrets LiteLLM en keyring | non configuré ici | **BLOCKED** côté secrets (Nathan : `forge secrets set litellm` / keyring) |
| Phase 2 PROOF-IDE fermée | non | Cursor **n'implémente pas** adaptateur complet (START_HERE) |
| Story P0-1 DONE | non | Cursor en **veille synergique** |

## Sortie calibration

`BLOCKED` pour écriture produit / claim concurrent.  
`READY` pour revue, navigation, et tâches Cursor **explicitement dispatchées** hors chemins claimés.
