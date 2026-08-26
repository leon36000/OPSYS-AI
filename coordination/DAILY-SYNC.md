# Daily sync

Date UTC : `2026-08-26T10:59Z`

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

## Merges depuis le dernier sync

- aucun

## Codex

- active : aucun (aucune mission Codex déclarée — cf. `CODEX-STATUS.md`)
- blocked : aucun
- next : réconciliation Core live (`LIVE-CORE-RECONCILIATION`, `CODEX-QUEUE.md`)

## Claude

- active : `OPS-OVERLAY-INSTALL` (PR #564, en revue) ; `LIVE-ISSUE-RECONCILIATION`
  (triage live) ; `AUD-CORE-006` (PR #571, en revue) — détail par mission dans
  `WORK-OWNERSHIP.md`, statut d'exécution dans `CLAUDE-STATUS.md`
- blocked : `AUD-CI-003`/`AUD-CI-004` (gel #569), `AUD-CORE-005` (issue #568),
  `AUD-CANON-001`/`AUD-CANON-002` (gate #541)
- next : suivre la restauration du routeur LiteLLM (#569) et la décision Nathan sur #568

## Décisions Nathan requises

- Arbitrage PR #564 vs PR #566 (installeur unique de `coordination/`, cf.
  `WORK-OWNERSHIP.md`)
- Restauration du routeur LiteLLM ou arbitrage de l'issue #569
- Décision sur l'issue #568 (restaurer / retirer / requalifier le fragment orphelin)
- Gate #541 (layout du canon) pour `AUD-CANON-001`/`AUD-CANON-002`

## Ownership mis à jour

- oui — `WORK-OWNERSHIP.md` à `2026-08-26T10:59Z`
