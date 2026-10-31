# M9 — Rapport final (cahier GRS du 9 juin adapté à OPSYS-AI)

**Verdict : M9 est PARTIEL. M9 n'est pas complet.** 16 lignes sur 24 sont DONE_VERIFIED ; 7 restent PARTIEL avec un gate
nommé ; 1 (l'écran mobile) attend la phase mobile finale. Source de vérité des statuts :
`docs/reprise/M9-COMPLETION-20261028/MATRICE-EXIGENCES.json` (aucune ligne retirée).

Base `3ab7692f` · branche `mission/claude-m9-direction-complete-20261028` · PR draft #859 · jamais fusionnée.

## 1. Ce que le cahier demandait, et comment OPSYS-AI le porte

Le cahier décrit des routes REST `/api/strategy/*`, 18 tables `strategic_*`, LangGraph/Temporal/Langfuse. OPSYS-AI n'a rien de
cela et n'en ajoute pas (ADR-0012). Correspondance retenue — détail dans [l'audit](M9-AUDIT-INITIAL-QUADRUPLE-A.md) :

| Cahier | OPSYS-AI |
|---|---|
| Routes `/api/strategy/*` | 75 outils M9 (contrat d'outil, MCP/Core) et pages console `/direction/*` |
| Tables `strategic_*` | registres chaînés append-only (`stockage.maillons`), chaîne altérée refusée (`REJ-…-CHAINE-INVALIDE`) |
| Orchestration d'agents | conseil de 12 rôles, sorties de modèle admises ou refusées par le code, sans validation sémantique |
| Planification | cron natif (grants réels : hôte opérateur, M9.5) |
| 19 documents | `docs/grs/strategy/M9-*.md` (20 documents, plus l'audit et ce rapport) |
| 6 scénarios E2E | `tests/test_m9_e2e_cahier.py` (6 parcours, M9.24) |

## 2. Livré dans cette reprise (code, tests, navigateur)

- Indicateurs exécutifs : les 17 du cahier reliés à M8 ou à leur propriétaire, ou nommés sans définition (M9 ne calcule rien).
- Cadrage de décision (12 types), conseil réel à trois rondes, réaudit des citations d'un conseil clos.
- Revues hebdo/mensuelle/trimestrielle avec 20 sections de direction (faits cités ou NON_DISPONIBLE avec manques).
- Salle de guerre : risques actifs et changements depuis la veille. Radar à sept règles avec delta.
- 19 chocs de scénario, interpréteur de questions « et si… » borné, tendances extrapolées par le code (six points minimum).
- 17 playbooks, veille avec catégories et qualité des données, expériences sous cadre de gouvernance obligatoire.
- Pages console : indicateurs, décision, tendances ; garde d'accès admin strict testée statiquement.

## 2 bis. Suite des orientations du coordinateur
Liaison révision/empreinte côté M9 (M9.3), qualification fictive de la planification (M9.5), contrats attendus M4/M7/M1,
point de raccord Core et protocole PC1 non exécuté (M9.4), analyse de CI en lecture seule : voir
`docs/reprise/M9-COMPLETION-20261028/` (`CONTRATS-PRODUCTEURS-ATTENDUS.md`, `QUALIFICATION-PLANIFICATION-M9-5.md`,
`PROTOCOLE-QUALIFICATION-CORE-CONSEIL-PC1.md`, `ANALYSE-FILTRES-CI.md`). Les 7 lignes PARTIEL restent PARTIEL.

## 3. Preuves

Régression finale `final6` (code `a1fa7493`) : 1 776 tests, 0 échec, 0 ignoré. Voir `docs/reprise/M9-COMPLETION-20261028/preuves-execution/` et `RAPPORT.md` (commandes, JUnit et journaux
aux noms distincts, jamais écrasés). Conseil réel : `preuves-conseil-reel/RAPPORT-CONSEIL-REEL.md`. Évaluation : 61 cas, 61/61,
corpus écrit par la mission, couche déterministe seulement. Navigateur : Chromium bureau et 390 px, données fictives.
CI GitHub : lue par SHA sur la PR #859 ; un verdict postérieur à un commit n'est pas reporté sur un autre.

## 4. Lignes ouvertes et pourquoi

| Ligne | Gate | Qui peut le lever |
|---|---|---|
| M9.3 | contrat successeur prêt côté M9 (preuve propre par observation, historique vérifié) ; M8 ne publie ni historique ni preuve → `VERSION_NON_COMPARABLE` | M8 (producteur, Root, commits séparés) |
| M9.4 | raccord et protocole PC1 livrés, non exécutés ; écart d'identité à trancher ; conseil réel fait en session seulement | qualification Core sur PC1 |
| M9.5 | qualification fictive faite ; CronService natif et grants réels non qualifiés | hôte opérateur |
| M9.8 | simulations finance, capacité, stock : pas de port de simulation chez les producteurs | M4 / M5 / M7 |
| M9.9 | une seule prévision de propriétaire (trésorerie M5) | M4 / M5 / M7 |
| M9.11 | aucune capacité d'équipe exposée aux lectures | M4 |
| M9.18 | mesures et coûts non fournis par les producteurs | M5 / M7 / M8 |
| M9.22 | aucun écran mobile ; contrat serveur prêt (`CONTRAT-MOBILE-ADMIN-M9.md`) | phase mobile finale |

Autres limites connues : M1 n'expose les plaintes qu'en texte (aucun risque de réputation créé) ; M7 ne publie aucune dépense ;
PostgreSQL et Core/VPS non exécutés ici ; la liste des 21 sections est retenue par délégation (`RETENU_PAR_DELEGATION`),
jamais ratifiée.

## 5. Frontières humaines conservées

Aucun paiement, engagement externe, publication, déploiement, suppression de données ni extension de droits. Les actions
passent par la file d'approbation native, que M9 ne contourne ni n'exécute. Aucun merge.

## 6. Suite

Hôte opérateur (M9.5), décision M8 (M9.3), données M4/M5/M7 (M9.8, 9, 11, 18), Core (M9.4), écran mobile (M9.22).
