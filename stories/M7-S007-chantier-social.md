# M7-S007 — Workflow « chantier terminé → contenu social » (mode ombre)

## Manifeste
T2 · allowed: src/workflows/, tests/, fixtures/chantiers/ · deps M7-S006 + M7-S005 (API publique
seulement) · touches_ledger: false · zéro réseau · aucun contenu inventé (fixtures fictives Québec).

## Critères (testables — 6 tests)
1. Fixture sans fictif:true → refus (ValueError). 2. Chaîne complète RÉELLE sur
residence-quebec-2026 : charge/compose/propose/approuve/publication tous SUCCES, la publication
capture NotAutorise (porte PROFONDE S005 : enabled+dry_run=False), métriques {1,1,1}. 3.
Auto-approbation alice/alice → étape approuve ECHEC, chaîne stoppée. 4. Flag OFF → AdapterDisabled
tracé ECHEC, compteur gated=0 (seul NotAutorise prouve le gating profond). 5. Déterminisme (double
run identique). 6. Zéro réseau (getsource).

## Pipeline
ADR MiMo (prose, 1re passe conforme) → tests+fixtures crew → RED capturé → GREEN + 4 alignements
(sujet dict contrat S006, config adapter dict, rechaînage copies propose/approve — le proposer se
perdait et l'auto-approbation passait, canal .value, type d'exception au détail) → revue trio →
merge auto gates (délégation Nathan).
