# Audit M8 — Business Truth & Analytics

**Auditeur :** Claude (session `session_01V5Nu4HTRqHAjT1HJqArVEa`) · **Date :** 2026-09-28
**Portée :** `departments/m08-analytics/` uniquement. Aucun autre fichier du dépôt n'a été modifié.
**Sources lues intégralement :** `docs/produit/DEFINITION-PRODUIT.md` (§1, §5, §6, §7-M8, §8, §9, §10,
§13), `AGENTS.md`, `docs/architecture/ARCHITECTURE.md`, `docs/architecture/DEPARTEMENTS.md`,
`docs/research/INGREDIENTS.md`, `docs/research/R9-m7-m8.md`, tout le code source et tous les tests de
`departments/m08-analytics/`, les trois documents BMAD (`docs/bmad/01…03`), `department.yaml`,
`SOUL.md`, `README.md`, la skill, `core/UPSTREAM.md`, `docs/decisions/` (liste), et les modules du
socle `src/opsys/{tableau_de_bord,console/pages,capacites,departements,openclaw}.py`.

## 0. Verdict en une phrase

M8 v1 est une **fondation de plomberie de métriques rigoureuse et bien testée** (contrats gelés,
provenance, XmR, hash-chaînage, filtrage par rôle fail-closed) mais **aucune des 18 fonctions
produit (M8.1-M8.18) n'est complète** : ce qui existe est déterministe et bien couvert par tests,
ce qui manque (collecte, entrepôt persistant, qualité, badges, tous les tableaux de bord, wallboard,
score de santé, copilote, ponts BI, mobile, preuves M9, mémoire) est **entièrement absent**, pas
juste incomplet. Le statut « PARTIEL — ~379 lignes, tableau de bord/score de santé existants » de
`DEFINITION-PRODUIT.md` §7/§11 date de juin 2026 et **ne décrit plus le code actuel** : le
département a été entièrement reconstruit (commit unique `ec973b6`, six stories S001-S006) selon
une architecture stdlib-only différente, qui n'a ni tableau de bord ni score de santé. Ce fichier
met à jour cette lacune de connaissance sans modifier `DEFINITION-PRODUIT.md` (hors périmètre).

## 1. Inventaire M8.1 – M8.18

Statuts : **PRÉSENT** = la capacité du produit existe sous une forme testée et utilisable telle
quelle. **PARTIEL** = un composant réel et testé sert une partie précise de la capacité ; le reste
est absent. **ABSENT** = aucun code ne sert spécifiquement cette capacité (même si un composant
générique voisin pourrait un jour être réutilisé).

Commande d'exécution des tests (une seule fois pour tout le tableau, résultat identique pour
chaque ligne « Tests ») : `/opt/opsys-venv/bin/python -m pytest departments/m08-analytics/tests -q
--import-mode=importlib -p no:cacheprovider` → **108 tests, 0 échec, code de sortie 0** (§ PREUVE).

| # | Fonction (résumé DEFINITION-PRODUIT §7) | Statut | Fichiers | Tests qui en font la preuve |
|---|---|---|---|---|
| M8.1 | Hub de collecte, connecteurs M1-M7/M9/M10 avec état | **ABSENT** | — | — (hors périmètre assumé, PRD §7.5 : « M8 reçoit un snapshot déjà construit ») |
| M8.2 | Entrepôt : faits, dimensions, marts | **PARTIEL** | `registre.py`, `encodage.py` | `test_registre.py` (9), `test_encodage.py` (5) |
| M8.3 | Couche sémantique + registre de métriques | **PARTIEL** | `dictionnaire.py`, `contrats.py`, `validation.py`, `semantique.py` | `test_dictionnaire.py` (10), `test_validation.py` (10), `test_semantique.py` (9) |
| M8.4 | Qualité des données (non nul, unicité, plage, cohérence…) | **ABSENT** | — | — |
| M8.5 | Fraîcheur, lignée, score de confiance, 8 badges | **PARTIEL** | `semantique.py` (fraîcheur seulement) | `test_semantique.py` |
| M8.6 | Tableau de bord exécutif | **ABSENT** | — | — |
| M8.7 | Tableaux de bord par département | **ABSENT** | — (mécanisme de filtrage seul, pas d'écran) | — |
| M8.8 | Wallboards temps réel | **ABSENT** | — | — |
| M8.9 | Alertes avec action proposée | **PARTIEL** | `xmr.py`, `digest.py`, `conformite.py` (garde anti-cause) | `test_xmr.py` (10), `test_digest.py` (8), `test_conformite.py` (4 sur la garde anti-cause) |
| M8.10 | Tendances, prévisions, écarts prévu/réel | **ABSENT** | — | — |
| M8.11 | Score de santé transparent | **ABSENT** | — | — |
| M8.12 | Copilote NL→SQL sûr | **ABSENT** | — | — |
| M8.13 | Générateur de rapports | **PARTIEL** | `rapports.py`, `digest.py` | `test_rapports.py` (9), `test_digest.py` (8) |
| M8.14 | Pont vers BI externe (Superset/Metabase/Grafana) | **ABSENT** | — | — |
| M8.15 | Analytique mobile par profil | **ABSENT** | — (0 référence dans `docs/architecture/MOBILE.md`) | — |
| M8.16 | Sécurité et accès par métrique | **PARTIEL** | `rapports.py` (filtrage fail-closed) | `test_rapports.py` (dont `test_role_sans_liste_d_autorisations_est_refuse_fail_closed`) |
| M8.17 | Fournisseur de preuves pour M9 | **ABSENT** | — (contrat générique existant, aucun consommateur ni emballage M9-spécifique) | — |
| M8.18 | Intégration mémoire (M10) | **ABSENT** | — (`department.yaml: memoire.*` déclaré mais non consommé par `openclaw.py`) | — |

**Scaffolding de département (hors numérotation M8.x, exigé par `DEPARTEMENTS.md`) :** présent et
conforme — `department.yaml` valide (`schema: opsys.departement/v1`), `SOUL.md` (une page, ce que
l'agent fait/ne fait jamais), `skills/rapport-analytique-quotidien/SKILL.md`, outil composé
`m8_rapport_metriques` + 4 outils unitaires exposés via `outils.py::outils()`, testés dans
`test_outils_agent.py` (9 cas : nominal, snapshot refusé, `metric_id` non déclaré, signal XmR
détecté après plusieurs ingestions, rôle sans liste refusé côté outil composé **et** côté outil
unitaire, devise non-CAD refusée par le dictionnaire réel, type invalide refusé par le schéma JSON).
Taille : 1 483 lignes de code (11 modules dont `conformite.py` à 745 lignes) + 1 951 lignes de
tests (11 fichiers).

## 2. Écarts (détail)

**Registre de métriques (définition, source, grain, fraîcheur, permissions, version).**
`contrats.py::CHAMPS_DEFINITION_METRIQUE` fige 7 champs : `id, nom, definition, unite,
source_donnees, frequence, consommateur`. **`grain` et `permissions` n'existent pas comme champs du
contrat** — le grain (par chantier, par jour, par équipe…) n'est nulle part déclaré et doit être
deviné dans le texte libre de `definition` ; les permissions ne sont pas un attribut de la métrique
mais une liste blanche que l'appelant refournit à chaque rapport (`metric_ids_autorises`), donc
aucune source de vérité persistée « qui a le droit de voir cette métrique ». `version` existe, mais
sous forme de hash de contenu (`semantique.py::deriver_metrique` → `version_definition =
encodage.empreinte(definition)`), pas un numéro sémantique ni un historique de versions. Enfin,
**le compilateur n'est alimenté que par M7** — les 9 autres départements n'ont qu'un `.gitkeep`
dans leur `metrics/` (vérifié : `find departments -path "*/metrics/*" -type f`), donc le registre
canonique réel du produit ne couvre aujourd'hui qu'une fraction de l'entreprise (14 métriques M7
selon `docs/research/R9-m7-m8.md` §0). C'est un manque **hors du périmètre de M8** (chaque
département doit livrer son propre fichier, PRD §2.5) mais qui bloque tout usage réel de M8 tant
qu'il n'est pas comblé.

**Trou de la garde de devise.** `dictionnaire.py::_MOTIF_UNITE_MONETAIRE =
re.compile(r"^([A-Z]{3})/\w+$")` ne détecte une devise non-CAD que si l'unité a la forme
`XXX/quelquechose` (ex. `EUR/soumission`, déjà corrigé pour M7 par cette même garde). **Une unité
monétaire « nue » comme `CAD` ou `EUR` (sans dénominateur) ne matche pas le motif et traverse la
garde sans contrôle** — `_devise_non_autorisee` retourne `None` faute de correspondance. C'est
précisément la forme que prendront les métriques de marge/coût réel de M5 (« marge réelle », unité
probable `CAD`, pas `CAD/quelquechose`). Risque concret documenté en §5.

**Entrepôt (faits, dimensions, marts).** `registre.py::RegistreSnapshots` est une liste chaînée par
hash en mémoire — un vrai « fait » horodaté, testé, avec détection d'altération (`valider_chaine`),
mais **non persistant** : c'est un singleton du processus MCP, sa portée est la session du serveur
(documenté explicitement dans `outils.py`, lignes 9-13). Aucune dimension, aucun mart. DuckDB/Parquet
sont une story GATED déjà tracée par l'architecture (`03-ARCHITECTURE.md` §0, §7.2), pas une
substitution silencieuse — décision correcte à conserver telle quelle.

**Tests de qualité.** `validation.py` ne teste que la forme du contrat d'entrée (4 verdicts :
structure invalide, module inconnu, `metric_id` inconnu, valeur non texte) — ce n'est pas une suite
de tests de qualité (non-nullité, unicité, plage, cohérence inter-tables) au sens M8.4. Aucun module
`qualite.py`, aucun rapport de taux de passage n'existe.

**Lignée.** Le hash-chaînage prouve l'**intégrité** (rien n'a été altéré) mais ne trace pas la
**lignée** au sens BI (quelle transformation, quelle exécution, quel consommateur a utilisé telle
valeur) — ces deux notions sont souvent confondues. Rien ne répond aujourd'hui à « quel rapport a
utilisé cette valeur, calculée à partir de quels maillons ».

**Badges de fraîcheur.** Recherche exhaustive dans `departments/m08-analytics/` : **aucun des 8
badges nommés par DEFINITION-PRODUIT.md §7 M8.5 (`LIVE, FRESH, STALE, PARTIAL, ESTIMATED, MISSING,
QUALITY_FAIL, GATED`) n'apparaît dans le code** (les seules occurrences de « GATED » dans
`departments/m08-analytics/` sont un statut de story dans les docs BMAD, pas une valeur de badge sur
une métrique). Seule la fraîcheur brute (nombre de jours, jamais binaire, conforme PRD §7.2) est
calculée.

**Tableaux de bord exécutif, par département, wallboard (M8.6-M8.8).** Recherche dans
`src/opsys/console/` et `src/opsys/tableau_de_bord.py` : c'est une **console d'exploitation OPSYS**
(départements, modes d'autonomie, approbations, budgets, paliers de modèles) — zéro référence à un
`RapportAnalytique` ou à une métrique métier. À ne pas confondre : la console pilote les agents, elle
ne montre pas la vérité chiffrée de l'entreprise. Rien ne rend `RapportAnalytique`/
`DigestAnalyticsQuotidien` visible à un humain aujourd'hui, ni en web ni en mode TV.

**Alertes avec action proposée.** `xmr.py` produit un `SignalXmR` — un **constat** statistique pur,
et `conformite.py::verifier_aucune_cause_signalee` interdit par garde AST tout champ `cause`,
`responsable` ou `raison_signalee` dans le paquet (DA-M8-07, testé). C'est la moitié « constat » de
M8.9, solide. La moitié « action proposée » exigée par le produit **n'a aucun objet, aucune table,
aucune fonction** — et ne peut pas être ajoutée à `SignalXmR` lui-même sans violer DA-M8-07. Voir
§4 T5 pour la résolution retenue (objet de présentation séparé).

**Score de santé transparent.** Absent. L'ancien score (« ~379 lignes », DEFINITION-PRODUIT §7/§11)
n'existe plus dans le code actuel — voir §0.

**Copilote analytique SQL sûr.** Absent : il n'y a même pas de moteur SQL en v1 (stockage
`list[dict]`, pas encore DuckDB), donc rien à brancher avant la story GATED de l'entrepôt.

**Contrôle d'accès par métrique.** Le mécanisme de filtrage est réel et fail-closed
(`rapports.py::construire_rapport` lève `ValueError` si un `role` est fourni sans
`metric_ids_autorises` — jamais une vue complète devinée, testé par
`test_role_sans_liste_d_autorisations_est_refuse_fail_closed`). Mais c'est une **fonction pure** :
rien ne persiste « le rôle `employee` voit `{m3_duree, …}` » — chaque appelant doit refournir la
bonne liste à chaque appel. Aucun lien avec les rôles réels du produit
(`nathan_owner, admin, finance, manager, seller, employee, client, system_agent`, P8) ni avec un
moteur d'autorisation fine — `OpenFGA` (cité comme service transversal D-010 dans les docs BMAD de
M8 et de M5) n'est implémenté nulle part dans le dépôt (recherche confirmée), pas seulement hors
périmètre de M8.

**Écrans mobiles par profil (§9).** Aucune des routes proposées par §9.8
(`analytics-dashboard`, `analytics-wallboard`, `analytics-alerts`, `analytics-departments`,
`analytics-reports`, `field-performance-summary`, `sales-analytics`) n'existe. Contrainte de
conception à respecter dès leur création : le profil employé doit rester « limité et non punitif »
(§9.3) — voir §5.

**Paquets de preuves pour M9.** `03-ARCHITECTURE.md` §3.4 le dit explicitement : « Aucun contrat
gelé v1 — M9 consommera la couche sémantique quand il sera construit ». `RapportAnalytique` est le
substrat naturel (déterministe, sourcé, filtré) mais rien n'emballe fraîcheur agrégée + couverture +
contradictions pour un consommateur M9, et M9 reste `STUB` (aucun code n'y lit quoi que ce soit de
M8).

**E2E exigés.** Les 108 tests de M8 sont unitaires/contrat, jamais inter-département — cohérent
avec la garde stricte « M8 n'importe aucun paquet `mX_*` » (DA-M8-01, testée). Aucun test simulant
la chaîne complète « travaux terminés → M8 » n'existe encore ; c'est exactement la cible de la
Phase 1 (§4, tâche T10).

## 3. Briques open source candidates

Licences vérifiées le 2026-09-28 (fichier `LICENSE` brut ou API GitHub ; `docs/research/R9-m7-m8.md`
avait déjà vérifié DuckDB/Parquet/dbt-core/MetricFlow/Cube/Evidence/Superset/Metabase/Grafana/
WrenAI/Vanna/PyMC-Marketing à la même date — repris tel quel ci-dessous sans redemander. Great
Expectations, Soda Core et Apache ECharts, absents de R9, ont été vérifiés pour cet audit).

### 3.1 Entrepôt persistant (M8.2)

| Brique | Licence | Version/date | Maturité | Empreinte | Verdict |
|---|---|---|---|---|---|
| DuckDB | MIT (vérifié) | push 2026-09-27 | 41 750⭐, très mature | Embarqué, zéro serveur, dizaines de Mo | **Retenu** — story GATED déjà tracée (`03-ARCHITECTURE.md` §0), MCP officiel `mcp-server-motherduck` disponible |
| Apache Parquet (via `pyarrow`) | Apache-2.0 | push 2026-09-27 | 2 595⭐ | Format fichier, pas un service | **Retenu** en compagnon de DuckDB |

Raison : contrat `metric_id`/`snapshot_id` déjà gelé comme seule interface de migration
(`registre.py` reste le seul point d'écriture) ; DuckDB remplace le stockage sans toucher
`semantique.py`/`xmr.py`/`rapports.py`. Cohérent avec la décision #2 de l'ingénieur en chef
(installable sur un VPS modeste, zéro service réseau).

### 3.2 Couche sémantique à l'échelle (M8.3, une fois plusieurs départements alimentés)

| Brique | Licence | Version/date | Maturité | Empreinte | Verdict |
|---|---|---|---|---|---|
| MetricFlow | Apache-2.0 | push 2026-09-11 | 1 809⭐ | CLI/pip, léger, batch | **Candidat n°1** si dbt-core est adopté — même philosophie déclarative que `dictionnaire.py`/`contrats.py` |
| Cube (Core) | Apache-2.0/MIT selon fichier, aucune clause copyleft (LICENSE brut vérifié par R9) | push 2026-09-27 | 20 919⭐ | Service Node/Rust résident (sidecar) | Candidat n°2 si l'objectif dominant est de servir plusieurs outils BI par une API unique |
| dbt-core | Apache-2.0 | push 2026-09-28 | 13 938⭐ | CLI, batch | Prérequis de MetricFlow, sinon non nécessaire tant que `semantique.py` (fonctions Python pures) suffit |

Verdict : **ne rien adopter avant que 2-3 départements alimentent réellement le dictionnaire** (§2).
Aujourd'hui, `dictionnaire.py`/`contrats.py` (91+17 lignes stdlib, testés) suffisent largement au
volume réel (14 métriques). Une brique ici serait de l'infrastructure sans département, contraire au
principe §14.4 de `DEFINITION-PRODUIT.md`.

### 3.3 Tests de qualité de données (M8.4)

| Brique | Licence | Version/date | Maturité | Empreinte | Verdict |
|---|---|---|---|---|---|
| Great Expectations (GX Core) | **Apache-2.0** (page officielle greatexpectations.io, vérifié 2026-09-28) | dépôt déplacé sous l'org **`fivetran`** (rachat), 11 847⭐, push **2026-09-28**, PyPI `great-expectations 1.23.1` | Très mature, standard de facto | pip, mais arbre de dépendances large (pandas, sqlalchemy, jinja2…) — nettement plus lourd qu'un module stdlib, s'exécute en batch (pas résident) | **Retenu pour Phase 2**, quand l'entrepôt DuckDB existe (§3.1) |
| Soda Core | **Elastic License 2.0** — **vérifié par lecture du fichier `LICENSE` brut** de `sodadata/soda-core` le 2026-09-28 (l'ancienne doc/le fork `canonical/soda-core-v3` affichent encore « Apache 2.0 », résidu d'avant un changement de licence en amont) | 2 430⭐, push 2026-09-24 | Mature | pip/CLI léger | **REFUSÉ** — Elastic License 2.0 est explicitement dans la liste de refus d'`AGENTS.md` (« BSL, Elastic, SSPL : refus sauf décision humaine ») |

Raison du verdict GX Core : c'est la seule des deux options compatible avec la contrainte de licence
du dépôt. Pas de brique de qualité aujourd'hui (v1) : tant que l'entrepôt reste un `list[dict]` en
mémoire non persistant, un moteur de tests de qualité externe n'a rien de columnar à tester — la
priorité immédiate est la garde de devise (§2, corrigible en quelques lignes dans `dictionnaire.py`
sans aucune brique), pas GX Core.

### 3.4 Dashboards, wallboard, rendu graphique (M8.6-M8.8, M8.14)

| Brique | Licence | Version/date | Maturité | Empreinte | Verdict |
|---|---|---|---|---|---|
| Evidence | MIT (vérifié R9) | push 2026-02-18 (cadence plus lente, à surveiller) | 6 847⭐ | Build-time seulement, zéro service runtime après génération | **Retenu Phase 1** — rapports figés versionnés, cohérent avec `digest.py` déjà déterministe |
| Apache Superset | Apache-2.0 (vérifié R9) | push 2026-09-28 | 74 944⭐, le plus mature | Service Flask+React résident, le plus lourd des choix dashboard | Retenu Phase 2 si un dashboard interactif self-service est requis ; licence la plus sûre du lot |
| Apache ECharts | **Apache-2.0** (vérifié 2026-09-28, API GitHub) | push **2026-09-28** | 67 406⭐, très mature | Bibliothèque JS **côté client** (~1 Mo min/gzip), **zéro empreinte serveur** | **Retenu** pour tout rendu de graphique (courbes XmR, tendances) dans une page interne ou un futur wallboard — s'intègre sans service supplémentaire, cohérent VPS modeste |
| Metabase (OSS) | AGPL-3.0 (confirmé R9 via metabase.com/license) | — | Très mature | Sidecar Docker | **Écarté pour tout usage client-facing** (licence commerciale requise en plus de l'AGPL) ; usage interne seul (Nathan/terrain) resterait gratuit — non prioritaire face à Superset (licence plus sûre) |
| Grafana | AGPLv3 (déjà classé `INGREDIENTS.md`, Phase 2) | — | Mature | Sidecar Docker | Utilisable en **service séparé non modifié**, usage interne uniquement (observabilité système), pas une vue métier M8 |

Raison : Evidence pour le premier tableau de bord exécutif figé (aucun service à opérer, VPS
modeste) ; Superset seulement si le besoin interactif self-service dépasse ce qu'Evidence permet.
Apache ECharts s'impose dans les deux cas pour le rendu (licence la plus permissive du lot, aucune
alternative n'a été identifiée avec une empreinte serveur aussi faible).

### 3.5 Copilote NL→SQL sûr (M8.12)

| Brique | Licence | Version/date | Maturité | Empreinte | Verdict |
|---|---|---|---|---|---|
| WrenAI (core/sdk/skills) | Apache-2.0 (`docs/` CC-BY-4.0 ; module AGPL-3.0 réservé, non présent — vérifié R9) | push 2026-09-25 | 17 763⭐ | Service Docker (moteur core), MCP natif | **Retenu** — couche sémantique explicite (MDL) entre le LLM et la base : le LLM ne voit jamais le schéma brut, le plus proche de « le LLM ne calcule jamais » |
| Vanna | MIT (vérifié R9) | — | Mature, large traction | pip, pas de service séparé | Alternative légère pour un usage interne outillé (Nathan pose une question ponctuelle, sortie toujours relue) |

Dans les deux cas : rôle DB **read-only strict**, jamais le rôle d'écriture de `registre.py`, et le
`metric_id` retourné doit être revalidé contre `dictionnaire.py` avant présentation — non
applicable avant la story GATED DuckDB (§3.1), puisqu'il n'y a aujourd'hui aucune base SQL à
interroger.

### 3.6 Ce qui n'a besoin d'aucune brique

Badges de fraîcheur (§4 T8), écart prévu/réel simple (§4 T1), score de santé pondéré (§4 T7),
association signal→action fixe (§4 T5) : ce sont des fonctions pures de quelques dizaines de lignes
chacune, du même calibre que `xmr.py` (49 lignes, déjà jugé suffisant par R9 face à toute
bibliothèque SPC externe). Ajouter une brique ici empilerait de la dépendance pour un calcul
trivial — contraire au principe AGENTS.md « les briques sont des ingrédients, pas à empiler ».

## 4. Plan par phases

### Phase 1 — tranche verticale : travaux terminés → métriques temps réel vs prévu et marge prévue vs réelle → alerte avec action → paquet de preuves M9

**T0 (préalable, hors périmètre de ce dépôt d'audit, à confier à M3/M4/M5).** Chaque module publie
un `metrics/*.yaml` minimal déclarant au moins une paire prévu/réel (ex. `m3_duree_estimee_h` /
`m4_duree_reelle_h`, `m3_marge_prevue_cad` / `m5_marge_reelle_cad`). Sans ce fichier,
`m8_compiler_dictionnaire` reste muet sur ces modules par construction (CA-M8-02) et aucun snapshot
n'est validable (CA-M8-03/04) — pas un défaut de M8, un prérequis externe à signaler à Nathan
séparément (PRD §2.5). Attention immédiate requise sur l'unité des métriques monétaires de M5 : voir
le trou de garde de devise (§2, §5) avant que M5 ne publie son fichier.

**T1 — `semantique.py::deriver_ecart(module_prevu, metric_id_prevu, module_reel, metric_id_reel,
registre, horodatage_reference)`.** Nouvelle fonction pure, même patron que `deriver_metrique` :
renvoie `{metric_id_prevu, metric_id_reel, valeur_prevue, valeur_reelle, ecart_absolu, ecart_pct,
n_prevu, n_reel}`, `None` fail-closed si l'une des deux séries est vide (jamais un zéro par défaut).
~40 lignes. Tests : nominal, prévu manquant, réel manquant, les deux manquants, écart positif/négatif,
valeur non numérique exclue du compte (6-8 cas, même style que `test_semantique.py`).

**T2 — `contrats.py` : geler `EcartMetrique`** comme extension additive (jamais un remplacement de
`ValeurMetrique` — P5 additive-only).

**T3 — `rapports.py` : champ optionnel `ecarts: list[EcartMetrique]`** dans `RapportAnalytique`,
filtré par le même mécanisme fail-closed déjà prouvé (`metric_ids_autorises` couvre
`metric_id_prevu` et `metric_id_reel`). Test de non-régression obligatoire : les 9 tests existants
de `test_rapports.py` doivent rester verts sans modification.

**T4 — `outils.py::rapport_metriques`** étendu pour calculer un `EcartMetrique` en option, quand
l'appelant fournit une paire prévu/réel. Ordre des contrôles inchangé (validation → écriture →
dérivation → écart → XmR → rapport) — aucun signal XmR calculé sur un snapshot refusé (garantie déjà
en place, à ne pas casser).

**T5 — Alerte avec action proposée (résout la tension §2).** Nouveau module `actions.py` : une table
statique `{ (type_signal, motif_metric_id) → texte d'action fixe }`, maintenue à la main (jamais
générée), et une fonction pure `associer_action(signal, table_actions)` qui renvoie un **objet de
présentation séparé** `{signal, action_proposee}` — sans jamais ajouter de champ à `SignalXmR`
lui-même (préserve DA-M8-07, testé par `verifier_aucune_cause_signalee`). Signal sans correspondance
connue → `action_proposee: None` + texte « aucune action définie », jamais une action inventée.
Tests : une correspondance connue par entrée de la table, plus le cas sans correspondance.

**T6 — `digest.py` : champ `actions` additif** en parallèle de `signaux_actifs` (inchangé, garde la
compatibilité).

**T7 — Score de santé minimal et paquet de preuves M9.** Deux fonctions pures : `score_sante(
metriques, signaux)` → `{score, facteurs: {...}}` (toujours les facteurs, jamais un nombre seul —
exigence « transparent » de M8.11) pondérant couverture (part des `metric_id` demandés qui ont une
valeur) et part des signaux dans les limites ; `construire_paquet_preuve(rapport,
horodatage_reference)` → `RapportAnalytique` enrichi de la fraîcheur la plus ancienne citée et d'un
indicateur de couverture booléen. Objet additif, exposé et testé même si M9 (STUB) ne le consomme
pas encore.

**T8 — Badges de fraîcheur.** `badge_fraicheur(valeur, n, fraicheur, seuils)`, `seuils` fourni par
l'appelant (jamais un défaut interne, même discipline que `n_minimal`) → un des 8 badges du produit.
Tests : un cas construit par badge, plus `MISSING`/`ESTIMATED` liés à `n=0`/`valeur=None`.

**T9 — `test_outils_agent.py` étendu** : cas nominal/refus/blocage pour le nouvel outil composé
(écart + action + badge), même patron que les 9 cas déjà présents.

**T10 — E2E de la tranche verticale.** `tests/test_e2e_travaux_termines.py` : à partir de fixtures
`fictif: true` simulant un snapshot M3 (« prévu ») et un snapshot M4/M5 (« réel ») déjà valides
contre leurs propres `metrics/*.yaml` (T0), rejoue la chaîne complète (validation → registre →
écart → XmR → action → rapport filtré rôle `admin` → paquet de preuve) et vérifie le résultat de
bout en bout — premier vrai test multi-module de M8, sans jamais importer un paquet `mX_*` de
domaine (les fixtures simulent ce que les autres modules enverraient).

Chaque tâche T1-T10 est petite (une fonction pure ou une extension additive), testable isolément, et
respecte les invariants déjà prouvés du paquet (fail-closed, additive-only, zéro import de domaine,
zéro horloge/aléa/réseau, zéro cause signalée, zéro défaut inventé).

### Phases suivantes (hors Phase 1, non détaillées ici)

Phase 2 : entrepôt DuckDB/Parquet (story GATED, §3.1) + garde de devise corrigée (§5) + Great
Expectations sur l'entrepôt réel + premier tableau de bord Evidence consommant `RapportAnalytique`.
Phase 3 : Superset self-service, copilote WrenAI (lecture seule), écrans mobiles §9.8, contrôle
d'accès persisté par rôle réel, branchement M9 (quand M9 sort de `STUB`) et M10.

## 5. Risques et points ouverts

1. **Trou de la garde de devise (§2)** — une unité monétaire nue (`CAD` sans dénominateur) n'est pas
   couverte par `_MOTIF_UNITE_MONETAIRE`. À corriger avant que M5 (T0) publie ses métriques de marge
   réelle, sans quoi le même bug EUR/CAD que R9 a trouvé et corrigé pour M7 (§1.3) peut se reproduire
   silencieusement sur les chiffres financiers.
2. **M8 consomme M5 sans recalculer (P13/§8) — discipline non encore éprouvée sur de vraies
   données.** La garde structurelle (aucun import de paquet `mX_*`, DA-M8-01, testée) empêche
   *techniquement* M8 de recalculer, mais aucun snapshot M5 réel n'a encore traversé le pipeline :
   le jour où M5 publie ses métriques, un désaccord d'unité, de devise ou d'arrondi entre le calcul
   M5 et ce qu'un rapport M8 affiche resterait invisible tant qu'aucun test ne compare les deux
   côte à côte. Recommandation : le test E2E T10 doit vérifier explicitement que la valeur citée par
   M8 est bit-à-bit celle du snapshot fourni, jamais une valeur recalculée.
3. **Vues non punitives pour l'employé (§9.3).** Structurellement protégé au niveau de `SignalXmR`
   (DA-M8-07 interdit toute cause/blâme) mais rien n'encode encore la contrainte « limité et non
   punitif » au niveau d'un futur écran mobile — c'est une règle de conception à appliquer
   consciemment quand M8.15 sera construit, pas quelque chose que le code actuel garantit tout seul.
4. **`OpenFGA` absent du dépôt entier**, pas seulement hors périmètre M8 (recherche confirmée sur
   tout le code et toute la documentation) : le filtrage par rôle de M8 restera une liste blanche
   ad hoc tant qu'aucun moteur d'autorisation fine n'existe côté Core.
5. **Champ `memoire` du manifeste déclaré mais non câblé.** `departements.py` parse
   `memoire_lecture`/`memoire_ecriture` depuis `department.yaml`, mais `openclaw.py::generer()` ne
   lit jamais ces deux champs (recherche confirmée) — lacune du Core héritée par les 10
   départements, pas spécifique à M8, mais elle bloque M8.18 en pratique.
6. **M9 reste `STUB`.** Le paquet de preuves (T7) sera testé et exposé sans consommateur réel tant
   que M9 n'existe pas — travail utile mais dont la valeur produit reste hypothétique jusqu'à ce que
   M9 soit construit.
7. **Un seul module (M7) alimente le registre de métriques.** Le mécanisme de M8.3 est solide, mais
   sa couverture réelle est étroite ; toute démonstration de M8 aujourd'hui ne peut porter que sur
   des métriques marketing, jamais sur les métriques opérationnelles (chantiers, marge) que la
   Phase 1 vise — d'où l'importance de T0.
8. **Grain et permissions absents du schéma `DefinitionMetrique` (§2).** À trancher avant que le
   nombre de métriques grandisse : ajouter ces deux champs maintenant coûte une story T2-like
   (~30 min, patron déjà connu) ; les ajouter après que dix départements aient publié leurs fichiers
   coûterait une migration de dix fichiers YAML.
9. **Historique git compressé.** Le département entier est un unique commit (`ec973b6`), donc aucune
   granularité de blâme/historique en dessous du niveau « refonte v2 » pour un futur audit.
10. **Empreinte de Great Expectations (§3.3)** à surveiller face à la décision #2 de l'ingénieur en
    chef (installable partout, y compris un VPS modeste) : son arbre de dépendances est nettement
    plus lourd que le reste du paquet M8, à réserver au moment où l'entrepôt DuckDB existe
    réellement, jamais avant.

---

**PREUVE :**
Commandes exécutées (lecture seule, aucune modification hors ce fichier) :
- `/opt/opsys-venv/bin/python -m pytest departments/m08-analytics/tests -q --import-mode=importlib
  -p no:cacheprovider` → 108 tests collectés, **108 passés, 0 échec**, code de sortie `0` (deux
  lignes de points `.` sans `F`/`E`, confirmé par une seconde exécution avec redirection complète et
  `echo $?`).
- `find departments -path "*/metrics/*" -type f` → confirme qu'un seul fichier réel existe
  (`departments/m07-marketing/metrics/m7-metrics.v1.yaml`), tous les autres départements (dont M8
  lui-même) n'ont qu'un `.gitkeep`.
- `grep` exhaustif sur `departments/m08-analytics/` pour les 8 badges de fraîcheur, `openfga`,
  `lignage`/`lineage`/`score_confiance` → aucune occurrence hors documentation de statut de story.
- `grep memoire src/opsys/openclaw.py` → aucune occurrence (champ non consommé).
- Vérification de licence par lecture directe du fichier `LICENSE` amont (`firecrawl_scrape` sur
  `raw.githubusercontent.com/sodadata/soda-core/main/LICENSE` → Elastic License 2.0, contredisant la
  documentation dérivée ; `api.github.com/repos/great-expectations/great_expectations` → Apache-2.0,
  dépôt déplacé sous `fivetran`, push 2026-09-28 ; `api.github.com/repos/apache/echarts` →
  Apache-2.0, push 2026-09-28).
- Lecture complète de tous les fichiers cités dans « Sources lues » en tête de document.
