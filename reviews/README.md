# Convention d'archivage des verdicts scellés (`reviews/<story>/`)

- **Niveau story** (`reviews/<story>/*.verdict.json`) = l'emplacement d'ÉCRITURE de
  `civ_review.py` : il contient toujours le **DERNIER round** de revue. Ces fichiers sont des
  sorties machine scellées (`prompt_sha256`) — **jamais édités à la main**.
- **`round-N/`** = archive verbatim de chaque round antérieur, déplacée telle quelle
  (`mv`, zéro modification) avant la relance suivante. Un REJECT n'est donc JAMAIS effacé :
  il vit dans son `round-N/` et dans l'historique git.
- **Vérification d'intégrité** (déterministe) : le contenu du niveau story d'un commit
  antérieur doit être byte-identique à un `round-N/` du commit suivant
  (`git show <ancien>:reviews/<story>/X.verdict.json | sha256sum` vs le fichier archivé).
- Un diff qui montre le niveau story passer de REJECT à APPROVE n'est PAS une falsification :
  c'est le rafraîchissement du pointeur « dernier round », l'ancien round étant archivé
  byte-exact dans le même diff (ou déjà sur main).

## Ce que ces verdicts attestent — et n'attestent pas (AUD-PROOF-006, #591)

Statut : ARCHIVE. Mesuré sur `origin/main` `07106d8` (2026-08-27), 711 verdicts, 711/711 parsés :

- **Aucun champ ne lie un verdict au code jugé** — neuf clés rencontrées en tout (`verdict`, `objections`, `date_heure`,
  `prompt_sha256`, `reviewer_model`, `modele_servi`, `gateway_resilience`, `reponses_Q`, `objectives`), aucune n'est un commit,
  un arbre, un diff ou un `code_diff_sha256`. Le seul indice de code est `objections[].fichier`, un chemin nu sans révision,
  absent de 349 verdicts sur 711.
- **`prompt_sha256` scelle le texte soumis aux relecteurs, pas l'arbre de code** : 275 sceaux distincts, groupes de 3 dans
  196 cas (signature d'un tour de revue à trois voix) — et **aucune préimage n'est committée** : aucun de ces sceaux n'est
  recalculable, nul ne peut établir quel texte a été lu.
- Ancrage rétroactif tenté : 95 verdicts sur 711 sont rattachables à un commit par préfixe de sceau cité (adjacence, non
  attestée) ; **616 n'ont aucune ancre** — les migrer vers un bundle lié au code est impossible, seul un rejeu produirait un lien.

Ce que ces fichiers attestent : que plusieurs voix ont lu un texte identique et rendu ces verdicts. Ce qu'ils n'attestent
pas : quel code a été jugé, ni qu'un code non approuvé n'a pas été fusionné. Ils ne franchiraient pas le premier contrôle de
`core/scripts/verify_proof_sealed.py` (« code_diff_sha256 absent — evidence non liée au code »).

Toute revue scellée nouvelle vit dans `evidence/tasks/<ID>/` (manifeste + `full.diff` + `prompt.txt` + verdicts liés par
`code_diff_sha256`), jamais ici. Le test `scripts/tests/test_reviews_archive_declaration.py` re-mesure l'invariant « aucune
clé liant au code sous reviews/ » : le jour où un verdict lié au code y apparaît, il rougit et force la mise à jour de cette
section. Un rejeu ciblé (option 1 de #591) reste possible, PR par PR, sans toucher à cette archive.
