# Queue Codex — Core

| Priority | Work ID | Condition d'entrée | Candidate scope | Status |
|---|---|---|---|---|
| P0 | LIVE-CORE-RECONCILIATION | Vérifier GitHub et les tâches déjà mergées | read-only | READY |
| P0 | NEXT-READY-CORE | Première tâche C00–C24 non VERIFIED dont les dépendances sont VERIFIED | task spec exact | WAITING_LIVE |
| P1 | SECOND-INDEPENDENT-CORE | Seulement si DAG et paths sont indépendants | task spec exact | WAITING_LIVE |
| P1 | CORE-VERIFICATION | Revue/tests de la mission active | read-only | READY |

La queue détaillée des tâches Core est dans le pack Codex, pas dans ce fichier quotidien.
