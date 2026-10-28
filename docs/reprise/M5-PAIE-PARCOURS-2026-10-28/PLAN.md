# Plan et état réel des tranches

| Tranche | Livré | Preuve principale |
|---|---|---|
| P1 Audit + contrat du dossier | `dossier_paie_preparatoire.py` (entrées fermées, grain, séparation heures/assiettes/cumuls/crédits/preuves, CCQ jamais déduit) | `test_dossier_paie_preparatoire.py` |
| P2 Composition + console privée | `composer`, `paie_dossier_ui.py`, huit outils, raccord `metier.py` séparé | `test_console_paie_dossier.py`, QA navigateur |
| P3 Versions, corrections, cumuls | `journal_dossiers_paie.py`, `service_dossier_paie.py` | `test_service_dossier_paie.py` (CAS, rejeu, panne, altération, concurrence) |
| P4 Postes et totaux sous couverture | `cotisations_employeur_2026.py`, matrice, totaux conditionnels | `test_cotisations_employeur_2026.py` (oracles Fraction) |
| P5 Revue + export CPA | revue liée à version/hash, `export_paie_preparatoire.py` JSON + HTML | tests service + HTTP + navigateur |
| P6 Parcours intégré | HTTP réel M4 → export, dispatcher, MCP HTTP, QA navigateur privé | `test_console_paie_dossier.py`, `test_paie_preparatoire_integree.py` |

Travail restant explicite (non couvert, jamais présenté comme fait) : surtemps, vacances et fériés, primes, avantages
imposables, rétroactif, changement d'emploi ou de province, régime CCQ, années à 27 paies, autres années que 2026,
base hebdomadaire CNESST, FDRCMO au-delà de 2 M$, bulletin/T4/RL-1/RE, qualification fiscale, accès agent, PostgreSQL et VPS.
