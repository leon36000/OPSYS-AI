# Daily sync

Date UTC : `2026-08-27T04:41Z`

Choix éditorial (revue scellée n°2, mineure) : ce fichier portait `UNSET` et
« active : aucun » partout alors que le sync owner de cette même mise au point
(`WORK-OWNERSHIP.md`, `CLAUDE-STATUS.md`) déclarait déjà des lignes actives —
contradiction interne. Choix retenu ici : **renseigner ce fichier en cohérence avec
`WORK-OWNERSHIP.md`, `CLAUDE-STATUS.md` et `CODEX-STATUS.md`**, plutôt que le neutraliser
en gabarit vide, parce que README.md confie explicitement ce fichier au sync owner de la
mise au point (« modifié par un seul sync owner désigné ») et que cette mise au point a
déjà produit un état daté et réconcilié dans ces trois fichiers : le dupliquer ici
n'ajoute aucune affirmation nouvelle, seulement un résumé compact. Le fichier
`24H-UPDATE-TEMPLATE.md` du même dossier reste le gabarit vide réutilisable pour la
prochaine mise au point ; il n'est pas touché par ce choix.

Ce résumé hérite donc aussi de la péremption de ses sources. **La clause couvre ce fichier
entier, prose comprise** — pas une énumération de sections ni d'exemples, qui redeviendrait
incomplète à la prochaine ligne ajoutée : toute valeur écrite ici est datée du `Date UTC`
ci-dessus et soumise à la clause portée en tête de `coordination/WORK-OWNERSHIP.md`
(désignée par sa section, pas par un numéro de ligne, qu'une simple édition réfuterait) —
elle périme dès le prochain commit/push/merge ; au-delà de 24 h, re-vérifier via `gh` plutôt
que de faire confiance à la valeur écrite ici. Non répétée à chaque ligne, pour la même
raison que ci-dessus : un résumé qui redit sa propre péremption à chaque phrase cesse
d'être un résumé. Ce que ce fichier ne fait pas non plus : recopier l'énoncé, le périmètre
ou l'état d'une issue ou d'une PR — seuls les numéros y figurent.

## Merges depuis le dernier sync

Missions passées à `MERGED` dans `WORK-OWNERSHIP.md` depuis le sync précédent, par numéro
seul — aucun état, aucune date de merge, aucun SHA n'est recopié ici, `gh pr view <n>` fait
foi :

- `AUD-CORE-006` — PR #571.
- `AUD-CI-003` + `AUD-CI-004` — PR #567.

Ne pas figer cette liste par SHA lors des prochains sync : un rebase change les SHA locaux
disponibles pour nommer un merge, pas le fait qu'il a eu lieu — recenser via
`git log --merges --oneline <base-de-la-dernière-sync>..origin/main` plutôt que de recopier
une valeur ici.

## Codex

- active : aucun (aucune mission Codex déclarée — cf. `CODEX-STATUS.md`)
- blocked : aucun
- next : réconciliation Core live (`LIVE-CORE-RECONCILIATION`, `CODEX-QUEUE.md`)

## Claude

- active : `OPS-OVERLAY-INSTALL` (PR #564) ; `LIVE-ISSUE-RECONCILIATION` (triage live) —
  détail par mission dans `WORK-OWNERSHIP.md`, statut d'exécution dans `CLAUDE-STATUS.md`.
  `AUD-CORE-006`, `AUD-CI-003` et `AUD-CI-004` ont quitté cette liste : leur statut local
  est `MERGED` (cf. « Merges depuis le dernier sync » ci-dessus)
- blocked : `AUD-CORE-005` (issue #568), `AUD-CANON-001`/`AUD-CANON-002` (gate #541).
  `AUD-CI-003`/`AUD-CI-004` ne sont plus tenues pour bloquées de notre côté
- queued : `AUD-CI-002`, issue #576 — statut local `QUEUED`, mission non activée
- next : activer #576, suivre la décision Nathan sur #568

## Décisions Nathan requises

- Arbitrage PR #564 vs PR #566 (installeur unique de `coordination/`, cf.
  `WORK-OWNERSHIP.md`)
- Issue #569 : à trancher — la fermer, ou la garder ouverte. Ni son état, ni son énoncé, ni
  ses commentaires ne sont recopiés ici ; `gh issue view 569` fait foi
- Décision sur l'issue #568 (restaurer / retirer / requalifier)
- Gate #541 pour `AUD-CANON-001`/`AUD-CANON-002`

## Ownership mis à jour

- oui — cf. l'horodatage en tête de `coordination/WORK-OWNERSHIP.md`. Valeur non recopiée
  ici, volontairement : deux fichiers qui ne recopient rien l'un de l'autre ne peuvent pas
  diverger. Une version antérieure de cette ligne recopiait cette date, et c'est la seule
  valeur de ce fichier qui avait divergé de sa source.
