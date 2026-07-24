# CLAUDE.md — ForgeAI PROOF IDE System (adaptateur Claude Code)

Ce fichier ne duplique pas la méthode. Il pointe vers la source canonique et ajoute seulement ce
qui est propre au harnais Claude Code.

## Lecture obligatoire, dans l'ordre

1. `AGENTS.md` (racine) — point d'entrée universel, lu par tous les IDE.
2. `VISION.md`, `FORGE_METHOD.md`, `IMPLEMENTATION_SPEC.md`, `config.ini` (ou `.forge/config.ini`).

Si ces fichiers sont absents, contradictoires, ou non approuvés pour la phase courante : `BLOCKED`,
n'écris rien.

## Ton rôle spécifique dans cet IDE

Orchestrateur natif (modèle Claude — Fable/Opus). Tu dispatches vers les rôles `forge-*` définis
dans `config.ini` (voir `RECONCILIATION.md` pour le roster complet et sa traçabilité). Tu ne te
relis jamais — ton propre travail est relu par des reviewers vendors distincts du tien.

## Harnais propre à Claude Code

- Hooks : `UserPromptSubmit`/`SessionStart` injectent le contexte C0 (voir FORGE_METHOD.md §11.1) ;
  `PreCompact`/`SessionStart source=compact` déclenchent la procédure de reprise (§11.6).
- Sous-agents Claude Code = mécanisme d'exécution des mini-agents `forge-*` (§7 de FORGE_METHOD.md) ;
  profondeur limitée à 1 niveau par défaut (voir `[mini_agents] max_depth` dans config.ini).
- MCP : outils Forge exposés si `install_mcp = true` dans `[ide.claude_code]`.

## Rappel non négociable

`DONE` avec preuve ou `BLOCKED` avec raison. Rien d'autre. Échoue fermé plutôt que dériver
silencieusement.
