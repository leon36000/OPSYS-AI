# Rapport de livraison M9

## Identité et portée
- Mission / responsable / outil : M9-COMPLETION-INTEGRALE-20261028 / Claude Code (session cloud) / Claude Code.
- Base / branche : `3ab7692f041892ec2af0cab6f241a715edac2d50` (`codex/restructuration-2026-09-30`) / `mission/claude-m9-direction-complete-20261028`.
- SHA de code vérifié localement : `f258a344` (1 456 tests, exécution `final2-m9`), puis `7a0a01d9` (corrections de la relecture : 26 tests du tableau) ; la CI GitHub se lit sur la PR draft #859. Les commits ultérieurs ne touchent que la documentation et les preuves.
- Résultat utilisateur observé : Nathan, admin, ouvre « Direction IA », saisit instant et jour civil, voit briefing, risques, prévisions des
  propriétaires, plans, actions et veille avec sources manquantes nommées ; il note un suivi ou annule un plan ; les actions passent par
  la file d'approbation native. Observé en navigateur Chromium (bureau, mobile 390 px) sur données fictives.
- **Périmètre visé : M9.1–M9.23 + M9.24 (parcours du cahier GRS du 9 juin, ajouté). Lignes encore ouvertes : M9.3, 4, 5, 8, 9, 11, 18 (PARTIEL) et M9.22 (PHASE_MOBILE_FINALE). 16 lignes DONE_VERIFIED sur 24. M9 n'est pas complet.**
- Cahier GRS M9 du 9 juin adapté à OPSYS-AI (outils et pages `/direction/*` au lieu de routes REST, registres chaînés au lieu de tables) : audit `docs/grs/strategy/M9-AUDIT-INITIAL-QUADRUPLE-A.md`, 20 documents `docs/grs/strategy/M9-*.md`, rapport final `docs/grs/strategy/M9-FINAL-REPORT.md`. Ajouts : indicateurs exécutifs, cadrage de décision, 20 sections de direction, réaudit du conseil, tendances, interpréteur de questions « et si… », 19 chocs, 17 playbooks, six parcours de bout en bout.

## Exigences et preuves
Voir `MATRICE-EXIGENCES.json` (aucune ligne retirée) : par ligne, statut, commit vérifié, tests et limite.
Code prêt ≠ intégration réelle ≠ qualification installée : les 15 DONE_VERIFIED sont prouvés en processus (SQLite, producteurs réels
appelés par le port privé, HTTP console) ; aucune qualification installée (VPS/Core) n'a été faite.

## Qualité et reprises
- Commandes : `preuves-execution/cmd-*.txt` (pytest sous `taskset` 2 CPU, `ulimit -v` 6 Gio, HOME/OPSYS_HOME privés). Exécution finale :
  1 445 passed, 0 failed, 0 skipped, 274 s. `opsys-metier verifier` exit 0. `ruff check src tests departments/m09-strategic-intelligence` OK.
- Rouges : régression console élargie = 46 échecs, tous fusion PDF/AP, identiques sur la base sans changements (46/46) ; conservés.
- Relecture indépendante du tableau (lecture seule) : rien de grave ; deux défauts réels corrigés avec test (filtre perdu à la page suivante des sources, code de refus de repli) ; limite connue : champ POST répété accepté en silence (non exploitable, CSRF).
- Défauts trouvés et corrigés pendant la QA : refus M9 pris pour un succès par le tableau (corrigé, testé) ; lecture d'une commande
  datée par l'horloge serveur ; lint vu en cours d'édition (relancé vert).
- Refus et reprises prouvés : rôle admin retiré après connexion -> 403 ; CSRF absent/faux -> 403 sans écriture ; mutation_id rejoué ->
  une seule écriture, données différentes -> 409 ; plan annulé -> refus nommé ; chaîne altérée -> REJ-…-CHAINE-INVALIDE ; effets inconnus
  (INCONNU) jamais rejoués.
- Conseil réel : **exécuté en session** (3 rondes, 6 sorties de vrais modèles Claude via l'outil Agent, hors runtime Core natif) : voir `preuves-conseil-reel/RAPPORT-CONSEIL-REEL.md`. Refus de forme puis de borne trouvés et corrigés, admission en ronde 3, recommandation gouvernée, budget réel appliqué (usage rapporté ~85 000 jetons > plafond 6 000 : dépôt refusé). Estimation déterministe non mesurée utilisée ensuite, dite telle. Vérité des inférences non prouvée.
- Évaluation : 61 cas, 6 catégories, attentes indépendantes, 61/61, Wilson 95 % [0,9408 ; 1,0000] ; biais : corpus écrit par la mission,
  couche déterministe seulement, aucun modèle réel mesuré.
- SQLite : vérifié. PostgreSQL : non exécuté ici (CI). HTTP : vérifié. MCP : non vérifié séparément. Navigateur : vérifié. Core/VPS : non
  vérifiés (le sandbox n'exécute pas `core/`). Mobile : contrat serveur prêt et testé, aucun écran (M9.22).
- Processus possédés (serveurs QA éphémères) arrêtés ; preuves archivées dans `preuves-*`.

## Coordination
- Raccords communs en commits séparés : `actions_m9.py`, `lecteurs_m9.py`, `departements.py`, `capacites.py`, `ROLES.md`,
  `test_portees_appareil.py`, puis console : `application.py`, `metier.py`, `pages.py`. Aucune extension de droits : les 52 outils des modules `outils_*` sont `admin` strict (garde statique `tests/test_m9_acces_strict.py`) ; les 23 outils historiques d'`outils.py` gardent leur voie d'origine (portée d'appareil `admin` ou fermée, voie agent inchangée).
- Contrat 21 sections : source canonique introuvable ; liste v2 retenue par délégation de Nathan le 2026-10-29 (réponse « Oui tu as toutes les autorisations » à la demande d'arbitrage), statut RETENU_PAR_DELEGATION, jamais RATIFIE, révisable, 15 clés historiques inchangées.
- CI du SHA de code final `7a0a01d9` : verte (run 2323, 39 checks dont `gates` requis sur `main`, `socle`, `frontiere-postgresql`, 10 `departement`) ; `installateur`, `mobile` et `dependency_audit` ignorés par le workflow, donc non prouvés. Verdict posté en commentaire sur la PR #859. Les commits postérieurs à `7a0a01d9` ne touchent que la documentation.

## Verdict et suite
- Démontré : couches déterministes M9.1–2, 6–7, 12–17, 19–21 ; gouvernance par les vraies approbations ; tableau exécutif en navigateur.
- Implémenté mais pas démontré en réel : conseil d'agents (backend), planification native, Core/VPS.
- À construire : écran mobile admin (M9.22 ; contrat serveur prêt dans `CONTRAT-MOBILE-ADMIN-M9.md`) ; réconciliation de version M8 ; prévisions/capacité/coûts chez les propriétaires.
- Décision humaine : confirmer ou amender la liste des 21 sections retenue par délégation, ou verser le prompt maître M9 ; M9.5 demande l'hôte opérateur (grants cron réels) ; M9.3 une décision de conception chez M8.
- Prochaine action : CI de la PR draft sur le SHA final ; lignes restantes = producteurs (M4 capacité, M5/M7/M8 données), hôte opérateur (M9.5), phase mobile (M9.22).

Aucun merge, déploiement, acte réel ou validation professionnelle n'est implicite.
