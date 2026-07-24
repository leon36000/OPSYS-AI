# GitHub Copilot Instructions — ForgeAI PROOF IDE System

Ce fichier est lu par les DEUX surfaces de GitHub Copilot : Copilot Chat/revue sur github.com, et
le coding agent (cloud agent) lorsqu'une issue lui est assignée. Il ne duplique pas la méthode —
lis `AGENTS.md` (racine) d'abord.

## Deux rôles distincts, pas le même niveau d'autorité

### 1. Cockpit (Copilot Chat, revue de code automatique, suivi des checks)

Rôle passif de gouvernance. Aucune écriture autonome hors d'une story explicitement dispatchée par
l'Orchestrateur. Ne jamais approuver/merger une PR sans que le tally (`forge tally` / dépouillement
par script) soit `APPROVED`.

### 2. Coding agent (assignation d'issue à `@copilot`)

**Ce n'est PAS un passe-droit.** C'est un cinquième front de construction, soumis aux mêmes règles
PROOF que Cursor ou Claude Code, sans exception :

- L'issue assignée DOIT porter dans son corps : `story_id`, `risk_tier` (T0-T3), `allowed_paths`,
  `forbidden_paths`, critères d'acceptation — le manifeste minimal de FORGE_METHOD.md §5.1.
- Story CLAIMÉE avant assignation — jamais deux fronts sur la même story.
- Le PR produit passe par le MÊME pipeline (gates locaux, revue indépendante scellée, tally par
  script, merge queue) que n'importe quel autre front — aucun raccourci parce que « c'est Copilot ».
- Pour T2/T3 : approbation humaine explicite avant merge, sans exception.

## Interdits (identiques à AGENTS.md)

Commit direct sur la branche principale, stub, TODO en diff, `DONE` sans preuve, auto-review
présentée comme indépendante, secret dans un prompt/log/diagnostic.

## Rappel

`DONE` avec preuve ou `BLOCKED` avec raison exploitable. Échoue fermé plutôt que dériver
silencieusement.
