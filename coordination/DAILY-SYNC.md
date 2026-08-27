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

Ce résumé hérite donc aussi de la péremption de ses sources : tous les états PR/issue
cités ci-dessous (« en revue », `#564` vs `#566`, etc.) sont datés du `Date UTC` ci-dessus
et soumis à la clause de péremption portée en tête de `coordination/WORK-OWNERSHIP.md`
(désignée par sa section, pas par un numéro de ligne, qu'une simple édition réfuterait) —
périment dès le
prochain commit/push/merge, re-vérifier via `gh` au-delà de 24 h plutôt que de faire
confiance à la valeur écrite ici. Non répétée en détail à chaque ligne, pour la même
raison que ci-dessus : un résumé qui redit sa propre péremption à chaque phrase cesse
d'être un résumé.

## Merges depuis le dernier sync

- `AUD-CORE-006` (PR #571) — mergée.
- `AUD-CI-003` + `AUD-CI-004` (PR #567) — mergée le 2026-08-27T04:11:06Z, issue #565 fermée.
Détail et méthode de vérification dans
  `coordination/CLAUDE-STATUS.md` (section « Merged since last sync »). Ne pas figer cette
  liste par SHA lors des prochains sync : un rebase change les SHA locaux disponibles pour
  nommer un merge, pas le fait qu'il a eu lieu — recenser via `git log --merges --oneline
  <base-de-la-dernière-sync>..origin/main` plutôt que de recopier une valeur ici.

## Codex

- active : aucun (aucune mission Codex déclarée — cf. `CODEX-STATUS.md`)
- blocked : aucun
- next : réconciliation Core live (`LIVE-CORE-RECONCILIATION`, `CODEX-QUEUE.md`)

## Claude

- active : `OPS-OVERLAY-INSTALL` (PR #564, en revue) ; `LIVE-ISSUE-RECONCILIATION`
  (triage live) — détail par mission dans `WORK-OWNERSHIP.md`, statut d'exécution dans
  `CLAUDE-STATUS.md`. `AUD-CORE-006`, `AUD-CI-003` et `AUD-CI-004` ont quitté cette liste :
  leurs PR #571 et #567 sont mergées (cf. « Merges depuis le dernier sync » ci-dessus)
- blocked : `AUD-CORE-005` (issue #568), `AUD-CANON-001`/`AUD-CANON-002` (gate #541).
  `AUD-CI-003`/`AUD-CI-004` ne sont plus bloquées
- queued : `AUD-CI-002`, issue #576 ouverte — plus aucune condition d'attente mesurable,
  reste `QUEUED` faute d'activation
- next : activer #576, suivre la décision Nathan sur #568

## Décisions Nathan requises

- Arbitrage PR #564 vs PR #566 (installeur unique de `coordination/`, cf.
  `WORK-OWNERSHIP.md`)
- Issue #569 : `OPEN` au `Date UTC` ci-dessus, mais le gel qu'elle décrivait ne
  se constate plus (PR #567 mergée à travers le périmètre scellé). Cause réelle et défaut
  d'infrastructure distinct : documentés en commentaire de #569 par le propriétaire du
  dépôt, à lire à la source plutôt que recopiés ici — un commentaire GitHub se modifie sans
  que ce fichier en sache rien. Reste à trancher : fermer #569, ou la garder ouverte pour ce
  défaut distinct
- Décision sur l'issue #568 (restaurer / retirer / requalifier le fragment orphelin)
- Gate #541 (layout du canon) pour `AUD-CANON-001`/`AUD-CANON-002`

## Ownership mis à jour

- oui — cf. l'horodatage en tête de `coordination/WORK-OWNERSHIP.md`. Valeur non recopiée
  ici, volontairement : deux fichiers qui ne recopient rien l'un de l'autre ne peuvent pas
  diverger. Une version antérieure de cette ligne recopiait cette date, et c'est la seule
  valeur de ce fichier qui avait divergé de sa source.
