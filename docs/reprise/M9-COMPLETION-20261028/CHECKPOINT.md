# Checkpoint M9 — mission M9-COMPLETION-INTEGRALE-20261028

Mise à jour atomique à chaque jalon (une seule version courante ; l'historique est dans Git).

- Base publiée vérifiée : `3ab7692f041892ec2af0cab6f241a715edac2d50` (arbre `deda206f…`, arbre M9 `5f384abd…`, identiques à `BASE.json`).
- Branche : `mission/claude-m9-direction-complete-20261028` (worktree privé `/home/user/OPSYS-AI-m9`), aucune branche M9 antérieure.
- Pack : ZIP sha256 `0ebf0e09ce4475ff6b8ca0c964104d02b23b7d3bfdd4743994385b9d9907a607`, `MANIFEST-SHA256.json` vérifié (103 fichiers, 0 écart).
- Enveloppe QA : HOME/OPSYS_HOME/XDG/TMP privés 0700 par exécution, `taskset` 2 CPU, `ulimit -v` 6 Gio, 1200 s, venv privé
  (dépendances figées reprises de l'environnement validé de la mission précédente ; `opsys` installé en éditable depuis le worktree).
  Machine réelle : 4 CPU / 15 Gio ; l'enveloppe du pack (2 CPU, 2 Gio de départ) est respectée pour les CPU, la mémoire est bornée à 6 Gio.

## Baseline (SHA `3ab7692f`, avant toute modification de code)
| Commande | Exit | Résultat |
|---|---|---|
| `pytest departments/m09-strategic-intelligence/tests -q` | 0 | 673 tests, 0 échec, 0 erreur, 0 skip (111 s) |
| 11 fichiers `tests/*m9*` du socle (suivis, rapports, bus, cible Core) | voir `PREUVES.md` | en cours à la rédaction |

## Baseline complémentaire (SHA `3ab7692f`)
| 11 fichiers `tests/*m9*` du socle (suivis, rapports, bus, cible Core) | 0 | 267 tests, 0 échec, 0 skip (192 s) |

## Livré (commits de la branche, tous poussés sauf mention)
- Lot 0 : schéma proposé à 21 sections (`rapport_decision_v2`, non ratifié), matrice requalifiée, inventaire.
- M9.1 : captures de producteurs (`capture_strategique`, `catalogue_producteurs`, `outils_tissu`), port privé socle `lecteurs_m9`
  (raccord commun séparé), lectures réelles M2/M3/M4/M5/M6/M7/M8/M10 capturées et testées par des agents de fixtures.
- M9.2–3 : `graphe_impacts` (règles réelles en cours), `semantique_metriques`.
- M9.4/M9.10 : `conseil` (12 rôles, sélection sous budget, admission, gouvernance), `sessions_conseil`, `outils_conseil`
  (dépôt exigeant une réservation native réconciliée), rapport v2 assemblé.
- M9.8 : `scenarios` (9 chocs, sensibilités arithmétiques sur bases citées).
- M9.6–7 : `revue_periodique` (en cours : outils et publication durable à brancher).

## Étape courante
Régression complète après adoption du catalogue ; puis outils de revue périodique, règles réelles du graphe (agent A à reprendre),
tableau exécutif console (seam metier.py séparé), Lots 5–9.

## Prochaine action
Valider la régression, committer catalogue+tests B, brancher `revue_periodique`.
