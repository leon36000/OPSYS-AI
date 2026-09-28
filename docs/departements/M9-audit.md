# Audit M9 — Strategic Intelligence

**Date :** 28 septembre 2026. **Auditeur :** agent d'audit (lecture seule + `pytest` M9).
**Sources de vérité utilisées :** `docs/produit/DEFINITION-PRODUIT.md` (§1, §5, §6, §7-M9, §8, §9,
§10, §13 — fait foi en cas de conflit), `AGENTS.md`, `docs/architecture/{ARCHITECTURE,DEPARTEMENTS,
ECONOMIE-TOKENS,MOBILE}.md`, `core/UPSTREAM.md`, `departments/m09-strategic-intelligence/**`,
`docs/research/{R10-m9-capabilities,INGREDIENTS}.md`, `pyproject.toml`. Aucune autre source de
vérité n'est contredite ci-dessous ; là où un chiffre manque, c'est marqué `ABSENT`/`À CONFIRMER`,
jamais inventé.

## 0. Verdict global

M9 v1 est un **harnais déterministe pur, livré et vert** (87/87 tests) : contrats gelés, registre
append-only hash-chaîné, agrégation « dernier fait par module », détection d'une seule catégorie de
contradiction, validation structurelle d'un rapport stratégique, garde de conformité statique. C'est
nettement plus que les « ~169 lignes, proxy `dept_financier.py` » de l'état connu de juin 2026
(§11 DEFINITION-PRODUIT.md, explicitement marqué « à revérifier ») : **813 lignes de `src/`**, 10
fichiers de tests, 1 skill. Mais c'est **0 % du contenu délibératif** que la mission M9 décrit :
aucun conseil d'agents, aucune salle de guerre, aucun scénario, aucun radar, aucun playbook, aucun
orchestrateur d'actions, aucune gouvernance spécifique, aucune évaluation, aucun écran mobile. Sur
les 23 fonctions M9.1–M9.23, **0 PRÉSENT, 5 PARTIEL, 18 ABSENT**.

**Écart le plus important, à trancher par un humain avant tout code** : le contrat gelé
`CHAMPS_RAPPORT_STRATEGIQUE` du code (**15 clés**, `contrats.py:3-7`) et le « rapport de décision en
**21 sections** » de M9.10 (DEFINITION-PRODUIT.md, qui fait foi) ne sont **pas le même contrat**. Le
code vient d'un PRD BMAD antérieur (fiche source « GRS_Plan_Squelette_Maitre… », ordre de
construction M7→M1→M2→M4→M3→M6→M8→M5→M9) ; DEFINITION-PRODUIT.md ne détaille que ~12 des 21 sections
et aucun autre fichier du dépôt n'énumère les 21. Personne ne doit inventer les champs manquants
(détail §2.6).

## 1. Inventaire M9.1–M9.23

Statuts : **PRÉSENT** (fait, testé), **PARTIEL** (fondation réelle, portée incomplète),
**ABSENT** (rien dans `departments/m09-strategic-intelligence/src`).

| # | Fonction (DEFINITION-PRODUIT.md §7) | Statut | Fichiers | Preuve |
|---|---|---|---|---|
| M9.1 | Tissu de données stratégique (snapshots M1–M8, fraîcheur, contradictions) | PARTIEL | `contrats.py`, `validation.py`, `registre.py`, `encodage.py`, `etat_consolide.py` | `pytest -q` ci-dessous : `test_registre.py`, `test_etat_consolide.py`, `test_contrat_snapshot_m8_m9.py` verts. Fraîcheur absente ; connecteurs M1–M7 absents ; registre en mémoire seulement |
| M9.2 | Graphe d'état de l'entreprise (impacts inter-modules) | PARTIEL | `etat_consolide.py::construire_etat_consolide` | `faits_par_module` est un dict plat (nœuds), zéro arête/impact. « Business State Graph minimal » = nom, pas un graphe |
| M9.3 | Couche sémantique exécutive (alignée M8) | ABSENT | — | Aucun `semantique.py` (M8 en a un) |
| M9.4 | Conseil d'agents (12 rôles + critique) | ABSENT | `rapport_strategique.py` (structure du produit final seulement) | Aucun agent, aucun débat, aucun superviseur. `department.yaml` déclare un seul agent M9 |
| M9.5 | Salle de guerre quotidienne (briefing du matin) | ABSENT | `department.yaml::planifications` (cron déclaré, en pause) | Pas de `digest.py` (contrairement à M1/M2/M4/M6/M8) ; rien n'exécute la consigne |
| M9.6 | Rapport exécutif hebdomadaire | ABSENT | — | — |
| M9.7 | Revues mensuelle et trimestrielle | ABSENT | — | — |
| M9.8 | Moteur de scénarios et tests de stress | ABSENT | — | — |
| M9.9 | Prévisions consolidées | ABSENT | — | — |
| M9.10 | Rapport de décision (21 sections — DÉFINITION-PRODUIT) | PARTIEL | `contrats.py`, `rapport_strategique.py` | Contrat figé à **15 clés**, pas 21 (écart §0/§2.6). Valide la structure, jamais le contenu |
| M9.11 | Priorisation et allocation de ressources | ABSENT | — | — |
| M9.12 | Radar de risques | ABSENT | — | — |
| M9.13 | Radar d'occasions | ABSENT | — | — |
| M9.14 | Veille de marché | ABSENT | — | R10 nomme des sources QC/Canada, rien de câblé |
| M9.15 | Playbooks stratégiques | ABSENT | — | — |
| M9.16 | Planification d'exécution et OKR | ABSENT | — | — |
| M9.17 | Orchestrateur d'actions (tâches contrôlées) | ABSENT | — | Fondation Core réutilisable existe (`src/opsys/approbations.py`), non appelée par M9 (§3.9) |
| M9.18 | Expériences et ROI | ABSENT | — | — |
| M9.19 | Gouvernance et validation humaine | PARTIEL | `department.yaml` (`mode: ombre`), `conformite.py` | Mécanisme Core T0–T3 générique s'applique par défaut ; aucune politique M9-spécifique (seuils de §7 M9 « règles dures ») |
| M9.20 | Mémoire (M10) | PARTIEL | `department.yaml::memoire`, clé `memoire_m10` du contrat | Présence structurelle seulement ; aucun test croisé M9↔M10 (contrairement à `test_contrat_snapshot_m8_m9.py` pour M8) |
| M9.21 | Tableau de bord exécutif | ABSENT | — | Seuls les 3 KPI du manifeste sont exposables par la console générique (`src/opsys/tableau_de_bord.py`) |
| M9.22 | Briefing mobile | ABSENT | — | Aucun écran `strategy-*` ; app OpenClaw officielle n'a que chat/approbations génériques |
| M9.23 | Évaluation et confiance (taux d'hallucination) | ABSENT | — | Aucun `proof-eval`, aucun jeu golden, DeepEval/Ragas non câblés |

**Commande exécutée (mandat de cet audit) :**
`/opt/opsys-venv/bin/python -m pytest departments/m09-strategic-intelligence/tests -q
--import-mode=importlib -p no:cacheprovider` → **exit 0, 87/87 tests verts**, 0 échec, 0 erreur (voir
PREUVE).

## 2. Écarts en détail

### 2.1 Tissu de données (M9.1) — fraîcheur, contradictions, connecteurs réels

- **Présent, réel** : `SnapshotModule` (`module_source, horodatage, valeurs`) est **identique** au
  contrat de sortie de M8 (`m8_analytics.contrats`) — vérifié par `test_contrat_snapshot_m8_m9.py`
  (une valeur numérique est rejetée par les deux modules, jamais l'un sans l'autre). Le registre est
  hash-chaîné (`encodage.empreinte` sur 5 champs), l'ordre « dernier fait par module » est calculé
  par comparaison **chronologique** de `datetime` ISO-8601 (fuseaux compris), jamais alphabétique —
  patron copié de `m8_analytics/semantique.py`, testé (`test_etat_consolide.py`, cas de fuseaux
  contradictoires).
- **Absent** : aucune notion de fraîcheur/péremption (les badges `LIVE/FRESH/STALE/MISSING/GATED`
  que M8 (§8.5 DEFINITION-PRODUIT.md) et la mission de cet audit attendent). Aucun connecteur réel
  vers M1–M7 : M9 accepte n'importe quel `SnapshotModule` structurellement valide, mais rien ne
  construit ce snapshot à partir des vrais registres de M1–M7 (dont plusieurs sont encore `STUB`
  selon §11 — à revérifier département par département, hors périmètre de cet audit).
- **Contradiction détectée = un seul cas** (même `module_source` + même `horodatage`, `valeurs`
  différentes). Une contradiction **sémantique** inter-modules (« M2 dit 10 conversions, M8 dit 8 »)
  n'est pas détectable en v1 — nécessite un mapping métier, explicitement hors périmètre (PRD §2.6).
- **Persistance** : le registre est un singleton en mémoire du **processus MCP** (`outils.py:24`),
  identique à la limite déjà connue de M8. Rien ne survit à un redémarrage. Tant que ce n'est pas
  levé (transversal, hors M9 seul), toute promesse de « tissu de données » doit porter ce repli.

### 2.2 Graphe d'état de l'entreprise et impacts (M9.2)

`EtatConsolide` est un dict `{module_source: dernier_maillon}` + une liste de contradictions — un
**index**, pas un **graphe**. La question de référence de la mission (« si M6 est en rupture, quel
effet sur M4, M5, M2 ? ») n'a aucune réponse possible aujourd'hui : il n'existe ni arête, ni
dépendance déclarée entre modules, ni propagation d'impact. C'est cohérent avec le PRD (« Business
State Graph **minimal** »), mais c'est un vrai trou fonctionnel vis-à-vis de DEFINITION-PRODUIT.md.

### 2.3 Conseil d'agents — agent, outil, critique (M9.4)

Rien n'existe comme **agent**. Ce qui existe :
- comme **contrat de sortie** attendu d'un futur Council : `CHAMPS_RAPPORT_STRATEGIQUE` (15 clés,
  validées structurellement par `m9_valider_rapport_strategique`) ;
- comme **méthode documentée à copier-adapter**, jamais importée : R10/INGREDIENTS.md pointent vers
  `~/proof-method/scripts/civ_review.py` + `tally_reviews.py` — un mécanisme de revue à 3 votants
  distincts, verdicts scellés par `prompt_sha256`, anti-Sybil, Delphi anonymisé max 2 tours. **Ce
  fichier n'est pas dans ce dépôt** (il vit dans l'infra personnelle de Nathan) : P10 (indépendance)
  interdit de l'importer tel quel — il faut le **réécrire** dans `m9_strategic_intelligence` à partir
  du patron décrit, jamais le copier depuis un chemin personnel hors dépôt.
- comme **rôles nommés** (DEFINITION-PRODUIT.md M9.4) : conseiller PDG, opérations, liaison finance,
  croissance marketing, stratégie de vente, rentabilité d'estimation, contraintes d'inventaire,
  expérience client, responsable des risques, auditeur de données, planificateur d'exécution,
  **critique de décisions** — aucun n'a de définition d'agent, de prompt, ni de politique
  d'autonomie dans `department.yaml` (un seul agent M9 y est déclaré, `mode: ombre`).
- « Aucun agent ne décide seul » (DEFINITION-PRODUIT.md) : la chaîne superviseur → agents →
  auditeur de données → critique → gouvernance → recommandation finale n'est ni câblée ni testable
  aujourd'hui, faute des maillons eux-mêmes.

### 2.4 Salle de guerre du matin, rapports, revues (M9.5–M9.7)

`department.yaml::planifications` déclare `digest-etat-consolide` (cron `0 7 * * 1-5`, livré en
pause par convention du dépôt) dont la consigne demande à l'agent de résumer `m9_lire_etat_consolide`
en 5 lignes, sans ingérer ni rédiger de diagnostic. C'est une **intention**, pas un livrable : il
manque un `digest.py` déterministe (patron présent dans M1, M2, M4, M6, M8 — `produire_digest`), un
outil `m9_produire_digest`, et l'activation réelle du cron (hors périmètre stdlib pur, nécessite
l'ordonnanceur OpenClaw). Rapport hebdomadaire et revues mensuelle/trimestrielle : rien.

### 2.5 Scénarios et tests de stress (M9.8–M9.9)

Aucun code. M3 a son propre Monte Carlo (`m3_estimation/monte_carlo.py`) mais M9 ne peut pas
l'importer (`DA-M9-04`, #109) — un futur moteur de scénarios M9 devra soit copier-adapter ce patron
localement, soit consommer un `SnapshotModule` produit par un connecteur séparé qui, lui, a le droit
de lire M3. Aucune prévision consolidée (M9.9) n'existe — `statsforecast` est nommé comme candidat
(§3) mais rien n'est câblé.

### 2.6 Rapport de décision — 15 clés vs 21 sections (M9.10)

Voir §0. Le contrat actuel (`contrats.py:3-7`) : `etat, diagnostic, preuves, hypotheses,
incertitudes, scenarios, recommandations, priorites, impacts, risques, actions, validation,
taches_par_departement, suivi, memoire_m10` — 15 clés, validation d'ensemble exacte (`REJ-RAPPORT-
CLE-MANQUANTE` / `REJ-RAPPORT-CLE-EN-TROP`, testé dans `test_rapport_strategique.py`). Le libellé
M9.10 de DEFINITION-PRODUIT.md (qui fait foi, §0.3) parle de 21 sections et n'en cite que 12 en
exemple (question, décision recommandée, options, données utilisées et manquantes, hypothèses,
scénarios, impacts, dépendances, conditions, validation, plan d'action, mesure du succès). **Aucun
fichier du dépôt n'énumère les 21** (grep négatif sur tout `docs/` et `departments/`). Recommandation
: ne pas coder de nouveau contrat avant qu'un humain n'ait produit (ou retrouvé, prompt maître M9 du
9 juin 2026 cité en Annexe A de DEFINITION-PRODUIT.md) la liste exacte des 21 sections ; documenter
alors la correspondance/l'extension du contrat 15→21 comme une story dédiée, avec tests de
non-régression sur les 15 clés existantes.

### 2.7 Radars, veille, playbooks (M9.12–M9.15)

Rien. R10 documente des sources publiques QC/Canada exploitables (StatCan WDS, Données Québec
permis + RBQ, CMHC/SCHL, ISQ) mais aucune n'est appelée. Aucun gabarit de playbook (crise de
trésorerie, chute de leads, semaine de mauvais temps…) n'existe dans `departments/
m09-strategic-intelligence`.

### 2.8 Priorisation et OKR (M9.11, M9.16)

Rien. Aucune matrice de décision, aucun objet OKR (objectif/résultat clé/progression). Voir §3 pour
le verdict sur les briques candidates (rejet d'un OKR externe).

### 2.9 Orchestrateur d'actions (M9.17)

**Absent côté M9, mais la fondation existe déjà côté Core** et est directement réutilisable :
`src/opsys/approbations.py::creer_demande(cnx, departement, outil, arguments, motif)` enregistre une
demande `en_attente` pour **n'importe quel département et outil déjà déclaré**, sans jamais importer
le paquet de ce département (seulement son nom et le nom de son outil, en chaînes) — donc compatible
avec `DA-M9-04` (aucun import de domaine). `decider()` exécute l'outil exact avec les arguments
exacts enregistrés, jamais d'autres, et journalise. C'est **exactement** le patron « orchestrateur
d'actions → tâche contrôlée dans un département, validée par un humain » que M9.17 demande ; il ne
manque qu'un outil M9 qui appelle `creer_demande` avec les bons arguments (§4, tâche T5).

### 2.10 Gouvernance (M9.19)

Le mécanisme T0–T3 (`src/opsys/outils.py::Autonomie`, `src/opsys/politiques.py`) s'applique déjà à
M9 par défaut (`mode: ombre` → tout T1+ demande approbation). `conformite.py` fait respecter
statiquement « jamais de chiffre inventé », « jamais d'import de domaine », « jamais de cause
attribuée à une contradiction » (`verifier_aucune_cause_signalee`, testé 4 fois dans le dépôt dont
une fois pour M9). Ce qui manque est **spécifique au contenu stratégique** : les seuils de
DEFINITION-PRODUIT.md §7-M9 (« validation obligatoire pour dépense réelle, changement de budget
marketing, embauche, achat majeur, dette, modification globale des prix, décision fiscale ou
légale ») n'ont aucune politique codée — ils ne peuvent pas encore exister puisque rien ne produit
de recommandation à gouverner.

### 2.11 Évaluation — taux d'hallucination (M9.23)

Rien. Aucun jeu de données golden, aucun gate CI `proof-eval`, aucune intégration DeepEval/Ragas.
C'est le point le plus risqué à laisser pour plus tard : dès qu'un Council (même GATED/prototype)
produira du texte, `conformite.py` (garde AST statique) ne peut **rien** dire sur une hallucination
narrative dans un champ texte libre (`diagnostic`, `recommandations`…) — seule une évaluation
sémantique le peut. Ordre recommandé : livrer l'évaluation **avant ou en même temps** que le premier
prototype de Council, jamais après.

### 2.12 Écrans mobiles admin (§9.5) et E2E

**Mobile.** DEFINITION-PRODUIT.md §9.5 attend, profil admin/Nathan seulement : briefing du matin,
alertes critiques, **décisions en attente**, scénarios, rapports, question stratégique. §9.8 propose
des routes (`strategy-dashboard`, `strategy-daily-brief`, `strategy-decisions`, `strategy-risks`,
`strategy-opportunities`, `strategy-scenarios`, `strategy-reports`) — **aucune n'existe**. Selon
`docs/architecture/MOBILE.md`, la phase 1 (app OpenClaw officielle, sans développement) couvre déjà
**une partie** de « décisions en attente » via ses approbations natives génériques (§4) : une demande
créée par `opsys.approbations.creer_demande` apparaît dans l'app sans écran M9 dédié. Le reste
(briefing du matin sourcé, radars, scénarios) demande soit la phase 2 (fork d'app), soit un minimum
de rendu côté console web (`src/opsys/tableau_de_bord.py`) avant l'app.

**E2E.** DEFINITION-PRODUIT.md exige pour M9 : « E2E verts » et cite implicitement le flux paquets de
preuves M8 → décision → tâche contrôlée. Aujourd'hui, `departments/m09-strategic-intelligence/tests`
ne contient que des tests unitaires/structure (10 fichiers) — aucun test d'intégration inter-
départements (M9↔M8 existe pour le **contrat**, `test_contrat_snapshot_m8_m9.py`, mais pas pour un
scénario M8→M9→approbation→exécution de bout en bout).

## 3. Briques candidates par écart

Licences vérifiées par lecture directe (R10, septembre 2026) ou re-confirmées aujourd'hui via l'API
PyPI (`pypi.org/pypi/<paquet>/json`, marqué *RCV*). `opsys-ai` (`pyproject.toml`) ne dépend que de
`PyYAML` et `mcp` : toute brique de science des données est un poids neuf, à isoler en **sidecar
docker-compose**, jamais dans le venv partagé du socle (confirmé par lecture directe, pas supposé).

### 3.1 Écart « Conseil d'agents + débat/critique » (M9.4)

| Brique | Licence | Dernière version (date) | Maturité | Verdict |
|---|---|---|---|---|
| [LangGraph](https://github.com/langchain-ai/langgraph) | MIT (R10, fichier `LICENSE`) | **1.2.12** (2026-09-21, *RCV*) | 42,4k★, actif, déjà nommé par la fiche source M9 | **Retenir** — moteur d'orchestration du futur superviseur, en sidecar, derrière une interface interne fine |
| Patron interne `civ_review.py`/`tally_reviews.py` | — (méthode interne, pas OSS) | — | Prouvé en production ailleurs (revue de code) | **Retenir, réécrire** — ne pas importer le fichier personnel (§2.3, P10) ; c'est le mécanisme débat/critique, LangGraph n'en fait que le séquencement |
| CrewAI / AutoGen | MIT (R10) | — | 59,1k★ / 61,2k★, actifs | Prototypage rapide seulement, avant fixation sur LangGraph — ne pas figer dessus |

### 3.2 Écart « Scénarios et tests de stress » (M9.8–M9.9)

| Brique | Licence | Dernière version (date) | Maturité | Verdict |
|---|---|---|---|---|
| [EMA Workbench](https://github.com/quaquel/EMAworkbench) | BSD-3-Clause (R10) | **3.0.0** (2026-03-12, *RCV*) | 154★, académique mais actif | **Retenir, vendoriser le module scenario-discovery seulement** — ⚠️ exige **Python ≥3.12** (*RCV*), incompatible avec le plancher `>=3.11` de `pyproject.toml` : sidecar isolé obligatoire, jamais dans le venv du socle |
| Monte Carlo maison (patron `m3_estimation/monte_carlo.py`) | — (interne) | — | Prouvé (M3, vert) | **Retenir en repli** — stdlib pur, copié-adapté localement (pas d'import), cohérent avec DA-M9-04 |
| [statsforecast](https://github.com/Nixtla/statsforecast) | Apache-2.0 (R10) | **2.1.1** (2026-07-16, *RCV*) | 4,9k★, très actif | **Retenir** pour M9.9 (prévisions consolidées), nommé explicitement par la fiche source |

### 3.3 Écart « Évaluation / taux d'hallucination » (M9.23)

| Brique | Licence | Dernière version (date) | Maturité | Verdict |
|---|---|---|---|---|
| [DeepEval](https://github.com/confident-ai/deepeval) | Apache-2.0 (R10 + *RCV*) | **4.2.6** (2026-09-24, *RCV*, 4 jours avant cet audit) | Actif, releases fréquentes | **Retenir** — gate CI `proof-eval`, jeu golden par département |
| [Ragas](https://github.com/explodinggradients/ragas) | Apache-2.0 (R10 + *RCV*) | **0.4.3** (2026-01-13, *RCV*) | Actif | **Retenir en complément** — fidélité aux sources (faithfulness), pertinent puisque chaque champ narratif de M9 doit tracer un `snapshot_id` |

### 3.4 Écart « Priorisation / matrices de décision » (M9.11)

| Brique | Licence | Dernière version (date) | Maturité | Verdict |
|---|---|---|---|---|
| [scikit-criteria](https://github.com/quatrope/scikit-criteria) | BSD-3-Clause (R10 + *RCV*, `LICENSE.txt`) | **0.10** (2026-08-06, *RCV*) | 105★, CI active | **Retenir** — TOPSIS/AHP/ELECTRE ; dépend de numpy/pandas/scipy/scikit-learn (*RCV*, `requires_dist`) → sidecar, pas le venv du socle |
| pyMCDM | GPL-3.0 (R10, vérifié) | — | Actif | **REJETÉ** — copyleft fort, incompatible en dépendance directe d'un produit commercial fermé (AGENTS.md) |

### 3.5 Écart « OKR » (M9.16) — piste explicitement demandée, absente de R10/INGREDIENTS.md

| Brique | Licence | Dernière info | Maturité | Verdict |
|---|---|---|---|---|
| [OpenOKR](https://github.com/openokr/openokr) | **GPL-3.0** (*RCV*, `LICENSE` du dépôt) | Plateforme Java/Vue autonome | — | **REJETÉ** — copyleft fort (même motif que pyMCDM) *et* architecture monolithique incompatible avec « moteur métier Python exposé en outil MCP » (décision de l'ingénieur en chef #2) |
| Contrat interne (patron `contrats.py`) | — | — | — | **Retenir, construire** — un OKR est un petit contrat de champs (`objectif, resultats_cles, progression, periode`) + un calcul de progression déterministe ; même discipline que `CHAMPS_RAPPORT_STRATEGIQUE`, pas de dépendance externe |

### 3.6 Écart « Radar de risques / veille de marché » (M9.12–M9.14)

| Source | Licence | Apport | Verdict |
|---|---|---|---|
| Données Québec — permis de construction, licences RBQ | CC-BY 4.0 Québec (R10) | Signal marché rénovation extérieure QC, `SnapshotModule(module_source="veille_marche")` | **Retenir** — données, zéro risque logiciel, attribution requise |
| StatCan WDS, CMHC/SCHL | Licence du gouvernement ouvert – Canada (R10) | Indicateurs macro/mise en chantier | **Retenir en phase 2** |
| [GPT Researcher](https://github.com/assafelovic/gpt-researcher) | Apache-2.0 (R10, `LICENSE` — le site officiel dit à tort MIT) | Agent de veille concurrentielle multi-source | **Retenir en sidecar**, sortie re-tracée en `SnapshotModule` avant d'entrer dans M9 (jamais consommée telle quelle) |

## 4. Plan par phases

### Phase 1 — tranche verticale (petites tâches testables, dans l'ordre)

Objectif : **paquets de preuves M8 → briefing du matin sourcé → décision en attente sur mobile →
tâche contrôlée créée dans un département après validation**, avec des fixtures `fictif: true` de
bout en bout.

| # | Tâche | Où | Test de complétion |
|---|---|---|---|
| T1 | Pont M8→M9 réel : script/outil d'intégration (hors `m9_strategic_intelligence`, respecte DA-M9-04) qui lit le registre M8 déjà produit et pousse chaque `SnapshotModule` dans `m9_etat_consolide` | Intégration (pas dans le paquet M9) | Fixture 2-3 snapshots M8 réels → `faits_par_module` correct, `contradictions` vide sur un cas sans conflit |
| T2 | Fraîcheur par fait consolidé (patron `deriver_metrique`, horodatage de référence injecté, jamais d'horloge) | `etat_consolide.py` (nouvelle fonction) | 4 cas : `LIVE/FRESH/STALE/MISSING`, testés unitairement |
| T3 | `digest.py` déterministe (patron M1/M2/M4/M6/M8) + outil `m9_produire_digest` : texte factuel (nb modules à jour, fraîcheur, contradictions nommées) — zéro contenu délibératif | `src/m9_strategic_intelligence/digest.py`, `outils.py` | Golden text sur un état consolidé fixe ; garde `conformite.py` toujours verte |
| T4 | Trancher 15 vs 21 clés (§2.6) — **décision humaine, pas de code avant** | `docs/decisions/` (nouvel ADR ou note ratifiée) | Aucun test — c'est un blocage documenté (`BLOCKED` si non tranché) |
| T5 | Orchestrateur minimal : outil `m9_proposer_tache_departement` (T2) qui appelle `opsys.approbations.creer_demande(departement, outil, arguments, motif)` — jamais d'import du département cible | `outils.py` (nouvel outil M9) | Fixture pointant vers un outil T1 réel existant (ex. `m4_creer_demande_ecart`) → la demande apparaît `en_attente`, jamais exécutée sans `decider()` |
| T6 | Vérification mobile : la demande de T5 apparaît dans les approbations natives de l'app OpenClaw officielle (phase 1 MOBILE.md) | VPS de test | E2E manuel documenté (pas de nouveau code d'app) |
| T7 | Test d'intégration bout en bout T1→T5 avec fixtures `fictif: true` | `tests/` (socle) ou `departments/m09-strategic-intelligence/tests/test_integration_m8_m9.py` | `pytest` vert, chaîne complète tracée (snapshot → état consolidé → digest → demande d'approbation) |

Chaque tâche reste dans l'esprit « harnais » actuel : aucune n'exige de LLM, toutes restent
prouvables en CI Python pur, aucune n'importe un paquet `mX_*` de domaine.

### Phase 2 — contenu délibératif (GATED, après T1–T7 verts)

1. Couche sémantique exécutive alignée M8 (M9.3, absente — voir tableau §1).
2. Graphe d'impact minimal : règles déterministes explicites (« M6 rupture → alerte M4/M5/M2 »),
   codées et testées avant tout LLM — pas un graphe inféré par un modèle.
3. Scénarios (Monte Carlo maison d'abord, EMA Workbench en sidecar si le besoin dépasse le patron
   M3) + `statsforecast` pour M9.9.
4. Radars (sources QC/Canada §3.6) et playbooks (gabarits + déclenchement par seuils, toujours
   sans LLM pour le déclenchement lui-même).
5. Contrat OKR interne (§3.5) et priorisation (`scikit-criteria`, sidecar).
6. Prototype de Council **derrière un flag explicite**, revue scellée obligatoire (patron
   `proof-review`), LangGraph + patron débat réécrit (§3.1) — jamais avant que T4 (15 vs 21) soit
   tranché et que M9.23 (évaluation) ait au moins un gate `proof-eval` (DeepEval/Ragas) en place.
7. Écrans mobiles phase 2 (fork d'app, routes `strategy-*` de §9.8) une fois le contenu réel à
   afficher.

## 5. Risques et points ouverts

1. **Ne jamais contredire une source de vérité (P13/§8).** Aujourd'hui le risque est nul (M9 ne lit
   rien de réel), mais devient réel dès T1 : ajouter un test de garde qui interdit à M9 d'écrire une
   valeur numérique dans `valeurs` autre qu'une copie exacte, chaîne pour chaîne, de ce que le module
   source a rapporté — jamais une valeur recalculée.
2. **`conformite.py` ne protège que du code, pas du texte.** La garde AST empêche un chiffre codé en
   dur en Python ; elle ne peut rien dire d'une hallucination dans un champ narratif libre
   (`diagnostic`, `recommandations`) une fois qu'un Council existera. M9.23 doit être livré avant ou
   avec le premier prototype de Council, jamais après (§2.11).
3. **Économie de tokens du conseil d'agents.** `department.yaml` ne porte qu'un budget global
   (`tokens_jour: 200000`) pour tout M9. Un Council à 12 rôles + superviseur + critique, s'il devient
   12+ agents OpenClaw séparés (system prompt + mémoire chacun), multiplie le coût par un facteur à
   deux chiffres. Recommandation : les « rôles » sont des appels de fonction/outil dans **un seul**
   agent M9 (ou un petit nombre), modèle local/rapide pour la synthèse de chaque rôle, modèle
   standard réservé à la synthèse finale + critique — cohérent avec les paliers de
   `ECONOMIE-TOKENS.md` (§7 P11). À chiffrer par un budget par rôle avant tout prototype, pas après.
4. **`civ_review.py`/`tally_reviews.py` n'est pas dans ce dépôt** (§2.3). Toute implémentation doit
   partir de la description du patron, jamais d'un accès au chemin personnel `~/proof-method/` de
   Nathan (P10, indépendance vis-à-vis de son infra personnelle).
5. **Persistance transversale.** Le registre M9 (et celui de M8, dont M9 dépend) vit en mémoire du
   processus MCP ; rien ne survit à un redémarrage. C'est hors périmètre de M9 seul, mais bloque
   toute promesse de « tissu de données stratégique » durable tant que ce n'est pas explicitement
   levé ou documenté comme repli.
6. **EMA Workbench exige Python ≥3.12**, vérifié aujourd'hui contre un plancher `>=3.11` pour tout le
   dépôt (`pyproject.toml`) — à isoler en sidecar, jamais dans le venv partagé, ou à rouvrir la
   question du plancher Python si cette brique devient centrale.
7. **Drift 15 clés / 21 sections (§0, §2.6, T4).** Point ouvert bloquant pour tout code touchant le
   contenu du rapport de décision — nécessite soit le prompt maître M9 original (9 juin 2026, cité en
   Annexe A de DEFINITION-PRODUIT.md, non retrouvé dans ce dépôt), soit une décision explicite de
   Nathan qui retranche ou étend le contrat actuel.
8. **M10 encore incomplet et sans contrat croisé avec M9.** `memoire_m10` n'est validé qu'en
   présence, jamais en contenu ; aucun test symétrique à `test_contrat_snapshot_m8_m9.py` n'existe
   pour M10 — la mémorisation réelle des décisions M9 n'est pas prouvée aujourd'hui.
9. **Portée de cet audit.** Seule la commande `pytest` sur `departments/m09-strategic-intelligence/
   tests` a été exécutée dans le cadre de ce mandat ; les états cités pour M8/M10 (nombre de
   fichiers, présence de fonctions) viennent d'une lecture directe des fichiers, pas d'une ré-
   exécution de leurs suites — à re-vérifier par un audit dédié à chacun de ces départements avant
   toute dépendance forte.

---

PREUVE:
- Commande exécutée (mandat de l'audit) :
  `/opt/opsys-venv/bin/python -m pytest departments/m09-strategic-intelligence/tests -q
  --import-mode=importlib -p no:cacheprovider`
  → exit code `0`, sortie `............[…]` = **87 tests, 87 succès, 0 échec, 0 erreur** (10
  fichiers de tests, 813 lignes de `src/m9_strategic_intelligence`).
- Lecture directe (pas d'exécution) : `docs/produit/DEFINITION-PRODUIT.md` (§1, §5, §6, §7 M8/M9,
  §8, §9, §10, §11, §13), `AGENTS.md`, `docs/architecture/{ARCHITECTURE,DEPARTEMENTS,
  ECONOMIE-TOKENS,MOBILE}.md`, `core/UPSTREAM.md`, `pyproject.toml`, tous les fichiers de
  `departments/m09-strategic-intelligence/{department.yaml,SOUL.md,README.md,docs/bmad/*,
  skills/*/SKILL.md,src/m9_strategic_intelligence/*.py}`, `docs/research/{R10-m9-capabilities,
  INGREDIENTS}.md`, `src/opsys/{approbations.py,outils.py,tableau_de_bord.py}`, listing des outils
  de `departments/m0{1..8}-*/src/*/outils.py`.
- Vérification de licences/versions en ligne (aujourd'hui, PyPI JSON, requêtes en lecture seule) :
  `langgraph` 1.2.12 (2026-09-21), `ragas` 0.4.3 (2026-01-13), `deepeval` 4.2.6 (2026-09-24),
  `statsforecast` 2.1.1 (2026-07-16), `scikit-criteria` 0.10 (2026-08-06, BSD-3-Clause confirmée
  dans `license`), `ema-workbench` 3.0.0 (2026-03-12, `requires_python >=3.12`) ; `openokr/openokr`
  confirmé GPL-3.0 (recherche web, page GitHub du dépôt).
- Aucun autre fichier que `docs/departements/M9-audit.md` n'a été modifié.
