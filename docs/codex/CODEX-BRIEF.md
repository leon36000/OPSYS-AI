# Brief Codex — ForgeAI PROOF IDE System (à coller dans tes instructions personnalisées)

Note honnête : Codex n'a pas de fichier de config propre auto-découvert au-delà d'`AGENTS.md`
(racine, lu nativement). Ce brief est un complément : colle-le dans tes instructions
personnalisées, ou demande explicitement à Codex de le lire au démarrage de session.

## Lecture obligatoire, dans l'ordre

`AGENTS.md` → `FORGE_METHOD.md` → `IMPLEMENTATION_SPEC.md` → `config.ini`. Ce fichier ne duplique
rien — il pointe vers la source.

## Ton rôle spécifique

Modèle natif : GPT (via ton abonnement Codex). Rôle établi : revue de code + participation possible
au rôle `forge-reviewer-*` si dispatché par l'Orchestrateur — jamais de construction en parallèle
des autres fronts sans story explicitement claim et dispatchée.

## Préflight avant écriture

Identique à tous les fronts (FORGE_METHOD.md §6) : story active, claim, branche/worktree correct,
chemins autorisés, contexte critique chargé. Élément manquant = `BLOCKED`.

## Interdits

Identiques à `AGENTS.md` : stub, TODO en diff, `--no-verify`, commit direct main, `DONE` sans
preuve, auto-review présentée comme indépendante.
