# Analyse des filtres de chemins de la CI (lecture seule, aucune modification de `.github/`)

Périmètre : `ci.yml`, `core.yml`, `e2e-core.yml`, `.github/ci/selection_workflows.py`, `workflows-applicables.json`,
`scripts/ci/tester_socle.py` et les tests de la CI. Rien n'a été exécuté. Toute décision de changement appartient au
coordinateur (CI commune à tous les agents, `gates` requis sur `main`), pas à M9.

Source des durées : une page de 30 jobs sur 37 (`total_count` = 37 dans le fichier, pas 38) du run 40969449140,
tentative 1, SHA `2851295f`, début 22:55:18 UTC. Quatre jobs étaient encore en cours (socle 0 et 1, m03-preuves gardes
5 et 6). Le fichier date de 23:31, soit environ 35,7 min après le début (inféré de l'heure du fichier). Les 7 jobs
absents de la page sont non mesurés. Ce n'est qu'un run : ni moyenne ni variance.

## 1. Jobs, déclencheurs, durées, dépendances réelles

| Job | Déclencheur | Durée mesurée | Dépendances réelles (lues) |
|---|---|---|---|
| `changements` (ci.yml:20) | toujours | 0,7 min | diff git complet |
| `socle` x2 (ci.yml:68-76) | toujours | non terminé (étape de tests en cours depuis 22:56:22 et 22:56:25) | voir ci-dessous |
| `departement` x10 (ci.yml:173-207) | toujours | 1,6 à 5,9 min par département, somme 28,6 ; M3 2,2 | voir ci-dessous |
| `m03-preuves` x9 (ci.yml:245-261) | toujours | 7 parts terminées : 13,3 à 32,6 min, somme 163,3 ; 2 parts en cours | voir ci-dessous |
| `frontiere-postgresql` (ci.yml:294) | toujours | 2,5 min | `tests/e2e/` (21 fichiers nommés, ci.yml:315), `src/opsys`, départements, `scripts/ci/preparer_pgvector.py` ; garde `len(cas) == 40` (ci.yml:322) |
| `core / construction` (core.yml:18) | `core` vrai | 20,4 min | `core/**` ; si `pnpm build` lit hors de `core/` : non vérifié |
| `core / tests` x6 (core.yml:47) | `core` vrai | 3 parts terminées : 4,5 à 8,1 min | `core/**` (`test:fast` exclut gateway et agents, core.yml:90-93) |
| `core / tests-opsys` x2 (core.yml:94) | `core` vrai | 24,2 et 21,1 min | `core/**` + Python réel : `OPSYS_TEST_PYTHON`, `src/`, `departments/*/src` |
| `core / verticale-core` (core.yml:314) | après `tests-opsys` | non mesuré (timeout 15 min) | `tests/fixtures/qualifier_verticale_core.py`, `.venv` |
| `e2e_core` (e2e-core.yml:28) | `e2e_core` vrai | 11,1 min | `core/**`, `src`, `departments`, `tests/e2e_core` |
| `mobile`, `installateur`, `dependency_audit` | flags faux dans ce run | non exécutés, non mesurés | `mobile/**`, `install/**`, `core/package.json` |
| `gates` (ci.yml:336) | `always()` | absent de la page | tous les résultats `needs` |

Total des jobs terminés de la page : 290,0 min-runner (hors socle, 2 parts m03 et les 7 jobs absents).

Constat qui corrige le cadrage : `core` et `e2e_core` ne sont pas filtrés « core seulement ». Leurs chemins incluent
`src/**`, `departments/**`, `tests/**` (workflows-applicables.json:13-22 et 46-55). Un test fige ce choix
(`tests/test_ci_workflows_applicables.py:78-83` : un fichier de M6 sélectionne `core` et `e2e_core`).

Dépendances vérifiées par lecture :
- **core/tests-opsys** exécute de vrais serveurs Python avec M9 sur le `PYTHONPATH`
  (`core/src/gateway/tools-invoke-http.opsys-m9-dossier.python-http.integration.test.ts:50,72`) ; la liste ciblée
  (`core/test/opsys-tests-cibles.txt`, 450 lignes) nomme des tests M9 (lignes 36-37, 442-450).
  Un changement dans `departments/m09-strategic-intelligence/src` doit donc exécuter ce job.
- **socle** : `testpaths = ["tests"]` et `pythonpath` de tous les départements (pyproject.toml:99-115). Le
  recensement exige des chemins sous `tests/` (tester_socle.py:52). Il lit `docs/{architecture,bmad,compliance,
  decisions,produit,research,departements}` (grep sur `"docs" /`), et un pont Python-mobile :
  `tests/e2e/test_admin_appareil.py:32` lit `mobile/src/admin/fixtures/reponses-moteur.json`.
- **departement** : chaque département importe `opsys` (18 à 51 fichiers selon le département) et des départements
  voisins (M9 importe `m6_material_control` et `m8_analytics` ; les tests de M8 et M10 citent M9). 83 fichiers de tests
  de départements appellent `charger_departements`, qui lit tous les manifestes.
- **m03-preuves** : `EnvironnementMutation` copie M3 et lie en lecture seule tous les autres départements, `src/`,
  `pyproject.toml`, `docs/` et `conftest.py` racine (`_environnement_mutation.py:111-141`). `test_politique_photos.py:98`
  lit `docs/compliance/politiques/*.md`. Les tests M3 importent M2, M4, M6 et M10. Cinq fichiers M3 appellent
  `charger_departements()` (donc le manifeste de M9 est lu).
- `departments/m03-estimation` importe bien `opsys` : `src/m3_estimation/outils.py:26-30` (18 lignes d'import `opsys` dans `src/`).

Les workflows `audit-*-fixed-f0b89cc.yml` ne se déclenchent que sur la branche `codex/restructuration-2026-09-30` et leur
propre fichier : hors sujet pour une PR M9.

## 2. Jobs filtrables sans omettre de contrôle

Mécanique actuelle des gates (selection_workflows.py:124-138) : `changements` et les 4 jobs Python doivent valoir
`success` ; chaque appel réutilisable doit valoir `success` s'il est applicable, `skipped` sinon. Un job Python ignoré
fait donc échouer `gates` (ligne 130), et le jeu de `needs` doit être exactement celui attendu (ligne 125).
`tests/test_ci_departements.py:78-115` fige le même contrat (10 `needs`, essais négatifs par job) ;
`tests/test_ci_socle_parts.py:171-185` exige 10 `needs`, la matrice socle à 2 parts et l'étape de vérification des reçus.
`tester_socle.py:156-206` exige les deux reçus de parts : le socle ne peut pas être sauté sans réécrire `gates`.

Un job conditionnel nouveau impose : un fichier de workflow réutilisable (la politique refuse `ci.yml` comme cible,
selection_workflows.py:83), une entrée dans `LABELS` (ligne 18) et dans le JSON (clés fermées, lignes 77-78), un `if` dans
`ci.yml`, et la mise à jour des 4 tests ci-dessus. Les motifs n'acceptent ni négation ni `?` (lignes 51-67,
test `["!a/**", ...]`) : on ne peut exprimer qu'une liste blanche d'inclusion, jamais « tout sauf ». Une règle « sauter si
tous les chemins sont inertes » exige donc un nouveau champ de politique.

| Candidat | Chemins propres | Dépendances transverses | Scénario de régression si le filtre est trop strict |
|---|---|---|---|
| Jobs Python si diff inerte (`docs/reprise/**`, `docs/grs/**`) | ces deux dossiers | aucun code ni test ne les lit (grep : 2 occurrences, des commentaires) | si `docs/**` entier était inerte : une modification de `docs/compliance/politiques/*.md` fait échouer `test_politique_photos.py` et le socle, sans que rien ne tourne |
| `m03-preuves` | `departments/m03-estimation/**` | `src/**`, tous les `departments/**` (liens et manifestes), `docs/compliance/**`, `tests/fixtures/**`, `conftest.py`, `pyproject.toml`, `uv.lock`, `scripts/ci/**`, `.github/**` | filtre « M3 seulement » : un manifeste M9 ou un changement `src/opsys` casse une assertion de catalogue ou un import dans la copie de mutation sans qu'aucune part ne tourne |
| `core` TS (`construction`, `tests` x6) | `core/**`, lockfiles | non établies hors `core/` | si le build lit un fichier racine non listé : build vert sur un état périmé (non vérifié) |
| `departement` en matrice dynamique | `departments/mNN/**` | imports croisés, `src/**`, manifestes | un changement de M6 casse M9 (qui importe M6) et M9 n'est pas rejoué |
| `frontiere-postgresql` | `tests/e2e/**`, `src/opsys/**` | départements M3, M5 à M9 | gain de 2,5 min : pas de filtre à justifier |

Conclusion de lecture : sur cette branche, un filtre ne change rien. Par rapport à `main` local (merge-base `54d89d35`,
21 octobre), la branche compte 429 commits et 681 fichiers, dont `src/opsys` (83), M4 (43), M6 (42), `core/src` (24),
M3 (22) : tout filtre raisonnable sélectionnerait tout. Seuls les poussoirs réellement inertes (le HEAD `4c961d5c` ne touche
que des preuves M9, non revérifié fichier par fichier) en profiteraient.
Filtre de départ piégeux : `GATES_PYTHON_OU_SELECTION_NON_REUSSIE` (ligne 131) devrait cesser d'exiger `success` pour des jobs
légitimement `skipped`, tout en refusant `skipped` quand le flag est vrai (même logique que lignes 135-138).

## 3. Concurrence sans annulation

`ci.yml:14-16` : groupe `ci-${{ github.ref }}`, `cancel-in-progress: false`. Pour une PR, `github.ref` vaut
`refs/pull/N/merge` ; pour un push, `refs/heads/<branche>`. Comportement documenté par GitHub (non rejoué ici) : au plus
une exécution en cours et une en attente par groupe ; une nouvelle exécution remplace l'attente précédente, qui est
annulée. Conséquences :
- le dernier push attend la fin du run courant puis sa propre durée : latence = reste du run courant + durée du nouveau run ;
- les pushes intermédiaires entre les deux sont annulés sans jamais tourner (sur `main`, des commits intermédiaires n'auront
  donc pas de `gates` complet) ;
- un push sur `claude/**` avec une PR ouverte déclenche deux groupes distincts (ci.yml:3-5), donc deux CI complètes en
  parallèle ; `tests/test_ci_departements.py:71-75` suppose cette coexistence (noms `gates` / `gates-push`). Fréquence réelle :
  non mesurée. La branche `mission/...` de ce run ne correspond pas à `claude/**` : un seul run, via la PR.
- `core.yml` et `e2e-core.yml` n'ont pas de groupe propre (commentaires lignes 9 et 19) : seul `ci.yml` sérialise.

Variantes, non appliquées :
1. `cancel-in-progress: ${{ github.event_name == 'pull_request' && github.event.pull_request.draft }}` : annule seulement
   les PR brouillon. Risque : le commentaire de ci.yml:10-13 rapporte qu'avec annulation « plus aucune exécution ne se
   terminait » ; il suffit qu'une PR brouillon reçoive un push toutes les moins de 25 min. Limite à des PR brouillon
   explicitement choisies.
2. Annulation conditionnée à une étiquette ou à un nom de branche (`mission/**` en brouillon uniquement). Risque : état
   caché ; un oubli d'étiquette rend le comportement imprévisible.
3. Concurrence au niveau job (`jobs.<id>.concurrency`) sur les seuls jobs lourds. Risque : un groupe commun à une matrice
   annule ses propres parts ; la clé doit inclure `matrix.*` ; un job annulé rend `gates` rouge pour ce SHA. Comportement
   exact : à éprouver sur un dépôt d'essai, non vérifié.
4. Réduire les pushes (regrouper les commits avant poussée) : aucune modification de CI, effet mesurable seulement par
   le nombre de runs, non mesuré.

## 4. Propositions classées (gain estimé / risque)

| Rang | Proposition | Gain | Risque | Fichiers | Garde qui prouve qu'aucun contrôle n'est omis | Décideur |
|---|---|---|---|---|---|---|
| 1 | Rééquilibrer les 8 parts `gardes` (index `i % PARTS`, ci.yml:287) selon les durées | rien retiré ; max actuel 32,6 min contre moyenne 25,0 des 6 parts terminées ; gain de mur ≤ environ 7 min, à confirmer sur un run complet | faible | `ci.yml` (matrice), éventuellement un script de partition | test d'union exacte des cas des parts = collecte complète (aujourd'hui seule `retenus > 0` est testé, ci.yml:290) | coordinateur |
| 2 | Sauter les 4 jobs Python quand tout le diff est dans une liste blanche inerte | un push de documentation n'exécute plus la CI complète (290 min-runner mesurés + socle) | moyen : touche `gates` | `selection_workflows.py`, JSON, `ci.yml`, 4 tests CI | test paramétré « diff inerte + un seul fichier de code = tout vrai » ; test qui parcourt `src`, `tests`, `departments`, `scripts`, `mobile`, `.github` et échoue si un chemin de la liste est lu ; le mode conservateur existant (lignes 177-179, 214-231) reste | coordinateur |
| 3 | Variante 1 de concurrence | non mesuré | moyen (famine déjà vécue) | `ci.yml:14-16` | essai sur une PR brouillon jetable | coordinateur |
| 4 | Filtre fin de `m03-preuves` | 163,3 min-runner pour les PR sans M3, `src`, départements, docs/compliance | élevé : liste de dépendances longue | politique, `ci.yml`, tests | test qui échoue si `_environnement_mutation.py` lie un chemin absent de la liste | coordinateur |
| 5 | Scinder `core.yml` en TS pur et TS + Python | 20,4 + 18,1 min-runner (3 parts de `tests`), aucun gain de mur (`tests-opsys` puis `verticale-core` dominent) | moyen | `core.yml`, JSON, `selection_workflows.py`, `test_ci_verticale_core.py` | test qui échoue si un test du core lit hors `core/` | coordinateur |
| 6 | Matrice dynamique des départements | environ 28,6 min-runner, aucun gain de mur | élevé : imports croisés | `ci.yml`, `tests/test_ci_departements.py:64-68` | non recommandé | coordinateur |

Toutes ces modifications touchent la CI commune et `gates` (requis sur `main`) : M9 transmet l'analyse, ne les applique pas.

## Ce que je n'ai pas pu vérifier

- Durée du socle (aucun terminé à la capture) : donc chemin critique du run non établi ; les 50 à 90 min annoncées ne sont ni
  confirmées ni infirmées. Un seul run, une page sur trois ; 7 jobs absents (dont `gates`, `verticale-core`, 3 parts de
  `core / tests`) et 2 jobs du total de 37 que je n'ai pas pu rattacher au YAML (35 identifiés).
- Temps d'attente en file : aucun run en attente dans le fichier ; non mesuré.
- Fréquence réelle des doubles runs push + PR sur `claude/**` : non mesurée.
- Comportement exact de GitHub sur annulation d'une exécution en attente, matrice vide (`fromJSON([])`) et concurrence au
  niveau job : cité de mémoire de la documentation, non rejoué.
- Lectures de `pnpm build` hors de `core/` ; lectures de `docs/` par `opsys-metier verifier` ; lectures par accès dynamique
  (grep des chaînes littérales seulement, pas d'analyse d'exécution).
- Absence de lecture de `docs/reprise` et `docs/grs` : établie par grep sur `src`, `tests` et `departments` (`*.py`,
  `*.yaml`), pas sur `core/` ni `scripts/`.
- Les imports croisés viennent d'un grep de lignes `from|import` ; les imports dynamiques (`importlib`) ne sont pas comptés.
