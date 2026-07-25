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
