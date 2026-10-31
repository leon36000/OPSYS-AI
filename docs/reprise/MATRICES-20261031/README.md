# Matrices d'exigences M1–M8 et M10 — état vérifiable

Date : 2026-10-31. Base : `claude/integration-lignes-trial`, SHA `83efcd82bd86938d700887605124622e11efbeaa` (les lignes #861, les quatre producteurs M9 et la ligne M9 #859 y sont intégrées).
La matrice du département M9 existe déjà : `docs/reprise/M9-COMPLETION-20261028/MATRICE-EXIGENCES.json` (schéma repris ici).

Ces matrices documentent l'état **réel** de chaque capacité exigée par `docs/produit/DEFINITION-PRODUIT.md` §7 et `docs/produit/PERIMETRE-MODULES.md`, avec, pour chaque ligne, le statut, le niveau de preuve, les fichiers de tests ou de documents qui la prouvent (tous existants, vérifiés par `tests/test_matrices_exigences.py`), les limites, les gates ouverts et les décisions attendues de Nathan. Elles ne contiennent aucune logique produit.

Point de départ : l'analyse d'écarts du 2026-10-31 (`ANALYSE-ECARTS-MODULES.md`, rapport du coordinateur du chantier, hors dépôt : `chantier-opsys-20261010/claude-coordinator-20261031-r1/`), écrite sur la ligne `claude/integration-producteurs-m9`. Chaque statut y a été revérifié dans le code et les tests de la base ci-dessus ; la colonne `initial_status` de chaque ligne garde le statut de l'analyse, `current_status` le statut vérifié.

## Synthèse par module

| Module | Lignes | FAIT_PROUVE | PARTIEL | SIMULE | ABSENT | INCONNU | Département | Suite de tests du département rejouée (base ci-dessus) |
|---|---|---|---|---|---|---|---|---|
| M1 | 20 | 0 | 13 | 2 | 5 | 0 | Front Office | 1766 passed, 0 failed, 0 skipped |
| M2 | 15 | 1 | 10 | 0 | 4 | 0 | Revenue CRM | 1899 passed, 0 failed, 0 skipped |
| M3 | 18 | 1 | 13 | 1 | 3 | 0 | Estimation | 2491 passed, 0 failed, 9 skipped (8 tests de test_mesure_plan.py : extra vision-photo absent ; 1 garde de CI) en excluant test_gardes_des_outils.py (32 tests d'outils de preuve de mutation) : ce fichier échoue (« n'a pas restauré son entrée capturée ») aussi en exécution isolée, cause non investiguée, donc non concluant |
| M4 | 24 | 2 | 20 | 0 | 2 | 0 | Field Ops | 3304 passed, 0 failed, 20 skipped (pyvrp absent) |
| M5 | 18 | 0 | 13 | 0 | 5 | 0 | FinanceCore | 2702 passed, 0 failed, 0 skipped |
| M6 | 21 | 0 | 20 | 0 | 1 | 0 | Material Control | 1725 passed, 0 failed, 0 skipped |
| M7 | 15 | 0 | 13 | 2 | 0 | 0 | Marketing | 1210 passed, 0 failed, 0 skipped |
| M8 | 18 | 0 | 12 | 0 | 6 | 0 | Analytics | 862 passed, 0 failed, 0 skipped |
| M10 | 20 | 0 | 19 | 0 | 1 | 0 | Mémoire | 1464 passed, 0 failed, 0 skipped |
| Total | 169 | 4 | 133 | 5 | 27 | 0 | | |

Fichiers : `MATRICE-EXIGENCES-M1.json`, `MATRICE-EXIGENCES-M2.json`, `MATRICE-EXIGENCES-M3.json`, `MATRICE-EXIGENCES-M4.json`, `MATRICE-EXIGENCES-M5.json`, `MATRICE-EXIGENCES-M6.json`, `MATRICE-EXIGENCES-M7.json`, `MATRICE-EXIGENCES-M8.json`, `MATRICE-EXIGENCES-M10.json`.

Lecture : le produit reste PARTIEL (mode `ombre` partout). Aucun département n'atteint la « preuve de complétion » de DEFINITION-PRODUIT §7 (parcours navigateur, téléphone, Core natif, PostgreSQL de la verticale, gates fermés).

## Légende des statuts

- `FAIT_PROUVE` : toute la cible de la ligne est couverte par du code **et** au moins un test présent, rejoué vert ici, de niveau S ou plus ; le périmètre prouvé est dit dans `limite` (jamais natif, navigateur ou téléphone sans test correspondant).
- `PARTIEL` : une partie de la cible est prouvée ; `limite` dit ce qui manque.
- `SIMULE` : la capacité n'existe qu'à travers un double, une fixture, un mode ombre ou un dry-run.
- `ABSENT` : aucun code ni test de la capacité (la vérification faite est dans `verification` ou `limite`).
- `INCONNU` : non conclu ; la ligne dit quoi lire ou exécuter. (Aucune ligne n'est INCONNU à cette date : les sous-éléments non confirmés sont écrits dans `limite` d'une ligne PARTIEL.)

## Niveaux de preuve (`proofs[].niveau`)

`T` test unitaire ou de module ; `S` parcours en processus sur SQLite réelle et bus réel ; `H` HTTP MCP réel avec la porte d'appareil réécrite en Python (`tests/fixtures/harnais_e2e.py`), **pas** le Core natif ; `P` test PostgreSQL présent (son exécution CI n'est ni rejouée ni affirmée ici) ; `N` Core/Gateway natif TypeScript (tests présents, non rejoués ici) ; `B` navigateur réel (aucun pour M1–M8 et M10) ; `M` téléphone ou émulateur (jamais atteint). `Jest` = tests du client mobile, non rejoués, ne prouvant ni rendu téléphone ni pont natif.

## Règles de lecture

1. Un statut ne monte jamais au-dessus de ce que prouve un test réellement présent. « CI verte » n'est pas une preuve : la CI GitHub n'a pas été relue et aucune ligne ne s'appuie sur elle.
2. Les suites des départements ont été rejouées localement sur la base ci-dessus (colonne de droite). Les tests de socle cités sous `tests/` l'ont été aussi (voir « Exécution »). Les variantes PostgreSQL, les tests Core TypeScript et les tests Jest sont **cités mais non rejoués** : ils sont nommés `P`, `N` ou `Jest` dans le niveau.
3. Une cible qui énumère plusieurs éléments n'est `FAIT_PROUVE` que si tous le sont ; un élément absent ou non confirmé la rend `PARTIEL`.
4. Les décisions de Nathan encore ouvertes sont écrites dans `decisions_nathan` ; ni le code ni ces matrices ne les tranchent.

## Schéma d'une exigence (repris de la matrice M9)

`id`, `title`, `target`, `acceptance`, `reuse_read_first` (code à lire), `initial_status`, `gates_to_resolve_or_keep_open`, `decisions_nathan`, `proofs` (liste de `{tests: [chemins], docs: [chemins], niveau}`), `verified_commit`, `current_status`, `limite`, et selon le cas `ecart_analyse`, `verification`. Différences avec M9 : `tests` est une liste de chemins (contrôlable par le test de garde) au lieu d'une chaîne, `execution`/`sha_execution` sont portés une fois par matrice dans `run_summary`, et le vocabulaire de statuts est `FAIT_PROUVE`, `PARTIEL`, `SIMULE`, `ABSENT`, `INCONNU`.

## Divergences entre l'analyse d'écarts et la vérification (12 lignes)

- M1.14 (Pont CRM M2) : analyse = FAIT_PROUVE, vérifié = PARTIEL. L'analyse d'écarts la déclarait FAIT_PROUVE (périmètre lead). La cible PERIMETRE M1.14 cite aussi activité/tâche/transcription/photos, absents du contrat v2 (schéma m1.lead_qualifie.json) : rétrogradée PARTIEL.
- M1.15 (Boucle M7 (UTM → lead → qualité) et STOP → M7) : analyse = FAIT_PROUVE, vérifié = PARTIEL. L'analyse d'écarts la déclarait FAIT_PROUVE ; le retour qualité/conversion/perte de la cible n'existe pas (aucun événement M2→M7) : rétrogradée PARTIEL.
- M1.19 (Bac à sable vocal) : analyse = PARTIEL, vérifié = ABSENT. L'analyse d'écarts regroupait M1.19-M1.20 sous PARTIEL ; vérification : aucun bac à sable vocal dans M1 ni dans la console (grep sandbox|bac à sable|faux appel) : ABSENT.
- M3.14 (Revue et approbation humaine) : analyse = FAIT_PROUVE, vérifié = PARTIEL. L'analyse d'écarts la déclarait FAIT_PROUVE (mécanisme). Les critères de validation obligatoire de la cible restent « non évaluables » sans seuils : rétrogradée PARTIEL.
- M4.16 (Exécution du job (machine à états)) : analyse = PARTIEL, vérifié = PARTIEL. L'analyse d'écarts marquait l'écart de 18 statuts INCONNU ; vérifié dans etats.py : 9 états, correspondance partielle avec la définition.
- M6.4 (Besoins matériaux depuis M3) : analyse = FAIT_PROUVE, vérifié = PARTIEL. L'analyse d'écarts la déclarait FAIT_PROUVE tout en notant « recommandation fournisseur/coût estimé : partielle » : la cible cite ces deux éléments, rétrogradée PARTIEL.
- M6.7 (Réception et entrée en stock) : analyse = FAIT_PROUVE, vérifié = PARTIEL. L'analyse d'écarts la déclarait FAIT_PROUVE avec « photo/dommage : INCONNU » ; vérifié : aucune substitution/dommage/photo dans reception.py : rétrogradée PARTIEL.
- M6.12 (Moteur de variance estimé vs réel) : analyse = FAIT_PROUVE, vérifié = PARTIEL. L'analyse d'écarts la déclarait FAIT_PROUVE ; la cible inclut l'écart de prix, absent du moteur de variance (variance_chantier.py ne traite pas les prix) : rétrogradée PARTIEL.
- M6.21 (Mémoire M10) : analyse = FAIT_PROUVE, vérifié = PARTIEL. L'analyse d'écarts la déclarait FAIT_PROUVE ; la cible cite écarts, pertes, décisions admin, leçons (non consommés par M10) : rétrogradée PARTIEL.
- M10.5 (Décisions et ADR) : analyse = FAIT_PROUVE, vérifié = PARTIEL. L'analyse d'écarts classait la ligne « décisions à raison obligatoire, révision sans fusion, statuts » FAIT_PROUVE ; la cible PERIMETRE M10.5 inclut les contradictions proposées et le remplacement, partiellement exercés : PARTIEL.
- M10.11 (Postflight) : analyse = PARTIEL, vérifié = PARTIEL. L'en-tête du README M10 disait « POSTFLIGHT applicatif hors périmètre v1 » alors que faits_candidats.py et m10_deposer_faits_candidats existent : en-tête corrigé.
- M10.13 (Self model) : analyse = INCONNU, vérifié = PARTIEL. L'analyse d'écarts classait le modèle de soi INCONNU ; vérifié : self_model existe dans consolidation_developpement.py (domaine développement) et est testé : PARTIEL.

## Garde

`tests/test_matrices_exigences.py` : JSON valide, statuts dans le vocabulaire, chaque chemin cité existe, aucun `FAIT_PROUVE` sans test existant cité, aucun `ABSENT` avec test, aucun identifiant en double, comptes de ce tableau identiques à ceux des matrices. Après toute évolution du code ou des tests d'un département, mettre à jour la ligne concernée **et** ce tableau, puis relancer ce test.

## Exécution (2026-10-31, base ci-dessus, hors ligne)

- Suites de départements : `python -m pytest -p no:cacheprovider --import-mode=importlib departments/<mNN-…>/tests` (résultats dans la colonne de droite du tableau ; M3 : voir la note, un fichier de 32 tests d'outils de preuve de mutation n'a pas pu être conclu).
- Tests de socle cités sous `tests/` (97 fichiers) : 1597 passed, 0 failed, 22 skipped (opt-in PostgreSQL ou job CI dédié).
- `tests/test_matrices_exigences.py`, `tests/test_portees_appareil.py` (compteurs de `docs/architecture/ROLES.md`), tests qui lisent des README (`departments/m10-memoire/tests/test_paquet_affaire.py`, `departments/m01-front-office/tests/test_formulaire_site.py`, tests `test_module_structure.py` de M1 et M3) : verts après les corrections de statut périmé.
- `ruff check tests src departments` : vert.

## Limites

- Ces matrices sont une documentation d'état ; elles ne remplacent ni l'exécution des suites, ni la CI, ni les qualifications natives, navigateur et téléphone.
- La numérotation M1.x suit PERIMETRE-MODULES (M1.1–M1.20), M2–M6 et M8 suivent DEFINITION-PRODUIT §7, M7 suit PERIMETRE (M7.1–M7.15), M10 suit PERIMETRE (M10.1–M10.15) plus cinq lignes d'extension (M10.16–M10.20) tirées de la « preuve de complétion » de DEFINITION §7 M10.
- Les sous-éléments d'une cible que la lecture du code n'a pas pu confirmer sont nommés dans `limite` comme « non confirmés » ; ce ne sont pas des preuves d'absence.
