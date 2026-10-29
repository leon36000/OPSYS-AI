# Rapport de livraison M9

## Identité et portée
- Mission / responsable / outil : M9-COMPLETION-INTEGRALE-20261028 / Claude Code (session cloud) / Claude Code.
- Base / branche : `3ab7692f041892ec2af0cab6f241a715edac2d50` (`codex/restructuration-2026-09-30`) / `mission/claude-m9-direction-complete-20261028`.
- SHA final de code vérifié : `29f67b6a` (les commits ultérieurs ne touchent que la documentation et les preuves). PR draft : voir la PR liée à la branche.
- Résultat utilisateur observé : Nathan, admin, ouvre « Direction IA », saisit instant et jour civil, voit briefing, risques, prévisions des
  propriétaires, plans, actions et veille avec sources manquantes nommées ; il note un suivi ou annule un plan ; les actions passent par
  la file d'approbation native. Observé en navigateur Chromium (bureau, mobile 390 px) sur données fictives.
- **Périmètre visé : M9.1–M9.23. Lignes encore ouvertes : M9.3, 4, 5, 8, 9, 10, 11, 18, 23 (PARTIEL) et M9.22 (PHASE_MOBILE_FINALE). M9 n'est pas complet.**

## Exigences et preuves
Voir `MATRICE-EXIGENCES.json` (aucune ligne retirée) : par ligne, statut, commit vérifié, tests et limite.
Code prêt ≠ intégration réelle ≠ qualification installée : les 13 DONE_VERIFIED sont prouvés en processus (SQLite, producteurs réels
appelés par le port privé, HTTP console) ; aucune qualification installée (VPS/Core) n'a été faite.

## Qualité et reprises
- Commandes : `preuves-execution/cmd-*.txt` (pytest sous `taskset` 2 CPU, `ulimit -v` 6 Gio, HOME/OPSYS_HOME privés). Exécution finale :
  1 445 passed, 0 failed, 0 skipped, 274 s. `opsys-metier verifier` exit 0. `ruff check src tests departments/m09-strategic-intelligence` OK.
- Rouges : régression console élargie = 46 échecs, tous fusion PDF/AP, identiques sur la base sans changements (46/46) ; conservés.
- Défauts trouvés et corrigés pendant la QA : refus M9 pris pour un succès par le tableau (corrigé, testé) ; lecture d'une commande
  datée par l'horloge serveur ; lint vu en cours d'édition (relancé vert).
- Refus et reprises prouvés : rôle admin retiré après connexion -> 403 ; CSRF absent/faux -> 403 sans écriture ; mutation_id rejoué ->
  une seule écriture, données différentes -> 409 ; plan annulé -> refus nommé ; chaîne altérée -> REJ-…-CHAINE-INVALIDE ; effets inconnus
  (INCONNU) jamais rejoués.
- Conseil réel : **non exécuté** (aucun backend/budget autorisé ici). Seuls l'admission déterministe et des doubles de protocole.
- Évaluation : 61 cas, 6 catégories, attentes indépendantes, 61/61, Wilson 95 % [0,9408 ; 1,0000] ; biais : corpus écrit par la mission,
  couche déterministe seulement, aucun modèle réel mesuré.
- SQLite : vérifié. PostgreSQL : non exécuté ici (CI). HTTP : vérifié. MCP : non vérifié séparément. Navigateur : vérifié. Core/VPS : non
  vérifiés (le sandbox n'exécute pas `core/`). Mobile : non démarré (M9.22).
- Processus possédés (serveurs QA éphémères) arrêtés ; preuves archivées dans `preuves-*`.

## Coordination
- Raccords communs en commits séparés : `actions_m9.py`, `lecteurs_m9.py`, `departements.py`, `capacites.py`, `ROLES.md`,
  `test_portees_appareil.py`, puis console : `application.py`, `metier.py`, `pages.py`. Aucune extension réelle de droits (tout `admin` strict).
- Contrat 21 sections : source introuvable ; proposition v2 non ratifiée, 15 clés historiques inchangées ; décision humaine requise.
- CI du SHA final : à lire sur la PR draft ; SKIP/UNKNOWN conservés.

## Verdict et suite
- Démontré : couches déterministes M9.1–2, 6–7, 12–17, 19–21 ; gouvernance par les vraies approbations ; tableau exécutif en navigateur.
- Implémenté mais pas démontré en réel : conseil d'agents (backend), planification native, Core/VPS.
- À construire : mobile admin (M9.22) ; réconciliation de version M8 ; prévisions/capacité/coûts chez les propriétaires.
- Décision humaine : énumération canonique des 21 sections (proposition prête dans `CONTRAT-RAPPORT-21-SECTIONS.md`).
- Prochaine action : CI de la PR draft, puis arbitrage des 21 sections.

Aucun merge, déploiement, acte réel ou validation professionnelle n'est implicite.
