@AGENTS.md

# CLAUDE.md — Projet OPSYS-AI

La constitution globale (`~/.claude/CLAUDE.md`) et les hooks globaux s'appliquent déjà.
Ici : uniquement le spécifique projet.

- Profil PROOF : voir `AGENTS.md` (PROOF-Team). Team ⇒ CIV_MODELS 3 vendors.
- Subagents (noms LiteLLM dédiés, jamais opus/sonnet/haiku) : crew-architect=GLM-5.2 · crew-coder-long=Kimi K2.7 Code · crew-coder-bulk=DeepSeek V4 Pro. opus/sonnet/haiku = passthrough Claude réel réservé à l'Orchestrateur (toi, cette session).
- Packs : `pack_build.sh` (doc compressée si `PROOF_COMPRESS=1` ; diff toujours verbatim ; revue = 0).

## Arrêts durs projet

- Lire `00-DIGEST.md` puis `docs/canon/REGLES.md` avant toute story ; plan maître PDF = source de vérité.
- `python3 scripts/structure_lint.py` VERT avant tout commit (arborescence D-038).
- Registres projet : `registries/ledger/*.jsonl` via `scripts/ledger_append.py` UNIQUEMENT (jamais à la main) ; registre méthode : `Registres/` (proof-method). Cf. ADR-0002.
- Story pilote : `Modules M/M7-marketing/stories/M7-S000-story-pilote.md`. Ne JAMAIS sauter une phase (ordre : `PROMPT_BOOTSTRAP_CLAUDE_CODE.md`).
- Les fichiers ForgeAI PROOF IDE System à la racine = référence produit distinct, ne gouvernent pas cette exécution (ADR-0002).

