# Daily sync

Date UTC : `2026-08-27T04:41Z`

Choix éditorial (revue scellée n°2, mineure) : ce fichier avait été mergé avec `UNSET` et
« active : aucun » partout alors que le sync owner de cette même mise au point
(`WORK-OWNERSHIP.md`, `CLAUDE-STATUS.md`) déclarait déjà 3 lignes actives — contradiction
interne au même commit. Choix retenu ici : **renseigner ce fichier en cohérence avec
`WORK-OWNERSHIP.md`, `CLAUDE-STATUS.md` et `CODEX-STATUS.md`**, plutôt que le neutraliser
en gabarit vide, parce que README.md confie explicitement ce fichier au sync owner de la
mise au point (« modifié par un seul sync owner désigné ») et que cette mise au point a
déjà produit un état daté et réconcilié dans ces trois fichiers : le dupliquer ici
n'ajoute aucune affirmation nouvelle, seulement un résumé compact. Le fichier
`24H-UPDATE-TEMPLATE.md` du même dossier reste le gabarit vide réutilisable pour la
prochaine mise au point ; il n'est pas touché par ce choix.

Ce résumé hérite donc aussi de la péremption de ses sources : tous les états PR/issue
cités ci-dessous (« en revue », `#564` vs `#566`, etc.) sont datés du `Date UTC` ci-dessus
et soumis à la même clause que `coordination/WORK-OWNERSHIP.md:7` — périment dès le
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
- Issue #569 : **toujours `OPEN`** au `Date UTC` ci-dessus, mais le gel qu'elle décrivait ne
  se constate plus (PR #567 mergée à travers le périmètre scellé). Cause réelle documentée
  en commentaire par le propriétaire du dépôt : la table d'alias du pont de modèles, pas le
  routeur. Reste à trancher : fermer #569, ou la garder ouverte pour le défaut distinct
  qu'elle porte désormais (`FORGE_MODEL_BRIDGE_MAX_TOKENS` à 4096)
- Décision sur l'issue #568 (restaurer / retirer / requalifier le fragment orphelin)
- Gate #541 (layout du canon) pour `AUD-CANON-001`/`AUD-CANON-002`

## Ownership mis à jour

- oui — `WORK-OWNERSHIP.md` à `2026-08-27T02:14Z`
