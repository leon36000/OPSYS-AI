# Status Claude Code

Updated UTC : `2026-08-26T02:14Z`

## Vérification runtime (07-RUNTIME-CHECK, constat unique de session)

- Lead observé : `claude-opus-5`. Le pack demande `claude-sonnet-5`.
  **Écart réel, ratifié explicitement par Nathan dans la session du 2026-08-26T02:14Z.**
  Aucun fallback silencieux : l'écart est consigné ici, pas masqué.
- Sous-agents : instanciés en `sonnet` (Claude Sonnet 5), conforme au pack.
  Les définitions `.claude/agents/opsys-issue-*.md` sont installées dans ce dépôt ;
  le dossier projet de la session courante étant distinct, les agents sont invoqués
  en injectant leur prompt et leurs contraintes verbatim.
- Effort `max` par sous-agent : non réglable depuis l'outil d'invocation courant.
  **Écart consigné**, non masqué.
- Écriture autorisée : oui (décision Nathan). `BLOCKED_RUNTIME_IDENTITY` non appliqué.

## Périmètre autorisé pour cette session

Jusqu'à la **PR ouverte** incluse. **Aucun merge**, aucune modification de branch
protection, aucun code métier M1–M10, aucune promotion canonique.

## Active

| Work ID | Branche | État |
|---|---|---|
| OPS-OVERLAY-INSTALL | `claude/ops/install-coordination-overlay` | overlay installé, commit + PR à suivre |
| LIVE-ISSUE-RECONCILIATION | read-only | triage live en cours |

## Merged since last sync

Aucune.

## Blocked

- `AUD-CANON-001` / `AUD-CANON-002` — gate de l'issue live #541 :
  « aucune promotion canonique avant validation Nathan et revue externe ».
  Collision de design avec #523 (CLR-006) : `CANON-INDEX.md` à la racine contre
  `docs/core/CANON-INDEX.md` dans le patch candidat. Preuve produite, promotion non exécutée.

## Next

Traiter `AUD-CI-003` + `AUD-CI-004` (gating CI bloquant), puis `AUD-CI-002`
(épinglage SHA des actions), puis `AUD-CORE-005` (validateur GitHub control).
