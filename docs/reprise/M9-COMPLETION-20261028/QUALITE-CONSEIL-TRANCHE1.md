# Qualité du conseil M9 — tranche 1 : corpus métier et défauts prouvés (hors ligne)

Mission complémentaire « qualité métier du conseil » (exigence M9.23, conseil M9.4). Branche `claude/m9-corpus-metier-tranche1`, cut de la
tête de PR #859 (`ea9d8c869`). **M9 reste PARTIEL** : cette tranche ne ferme aucune ligne de la matrice.

## Ce que cette tranche prouve — et ne prouve pas

| Verdict | État | Source |
|---|---|---|
| Couche déterministe M9 sur sorties de modèle **figées** (doubles de protocole) | **MESURÉ ICI** : 58/60 cas conformes aux attentes, 2 limites connues conservées rouges | `preuves-evaluation-metier/` |
| Qualité métier du conseil (justesse des inférences, utilité des décisions) | **NON ÉTABLIE** : aucune revue métier humaine indépendante, aucun modèle réel | — |
| Qualification par modèle réel | **OUVERTE** (aucun appel de modèle dans cette tranche ; coûts, latences, tokens de modèle : `UNKNOWN`) | — |
| Exécution Core native (budget, réservations, agents) | **OUVERTE** (non exercée ici ; gate du coordinateur) | `PROTOCOLE-QUALIFICATION-CORE-CONSEIL-PC1.md` |

Les sorties de « modèle » du corpus sont des textes **rédigés à la main**, fautifs ou non, pour sonder les garde-fous ; un taux de 58/60 ne dit rien d'un modèle.

## Commits (ordre d'exécution)

| SHA | Objet |
|---|---|
| `97f331bbd` | corpus métier versionné (60 cas), schéma JSON, contrôle de couverture et de disjonction des partitions |
| `753417f76` | harnais `evaluation_metier.py` + tests ; **première exécution sur le code inchangé** : 53/60, 7 rouges conservés (`EVAL-METIER-avant-correction-20261031T094640Z.json`) |
| `c109277e3` | correction 1 : montants/pourcentages/décimaux/dates libres refusés (`REJ-CONSEIL-CHIFFRE-LIBRE`) — 57/60 |
| `63256db94` | correction 2 : l'âge de chaque lecture est exposé au conseil — 58/60 |
| (ce rapport) | rapport, preuves d'exécution |

## Protocole et indépendance des attentes

* Les 60 cas, leurs sorties figées et **toutes les attentes** ont été écrits **avant la première exécution** ; aucune attente n'a été modifiée après avoir
  vu un résultat. Le `corpus_sha256` `6faf3c0aefd1…` est identique dans les trois rapports avant/après. Une seule retouche de fixture a suivi la première
  exécution : l'**entrée** du cas de vérification `rep-V02` dupliquait celle de `rep-A03` (le test de disjonction l'a révélé) ; elle a été remplacée par un
  digest présent mais muet sur les plaintes, **attentes inchangées**. Avant la première exécution, des fixtures ont aussi été corrigées (index de capture
  d'adresses citées, forme d'une page M8 simulée).
* Attentes dérivées du cahier (`DEFINITION-PRODUIT` §M9, « Règles dures » ; `AGENTS.md` « le code calcule, le LLM orchestre », « fail-closed ») et d'oracles
  calculés à la main : score `3×impact + 2×urgence + confiance`, allocation gloutonne par rang, jours entre deux dates civiles (119 et 30), conversion de
  fuseaux (`23:30-04:00 = 03:30Z`). Un test recalcule ces formules **sans le code testé** et compare aux attentes.
* **Partitions** : 42 cas d'ajustement (analyse et correction), 18 cas de vérification **tenus à part** (jamais utilisés pour décider d'un changement de
  code). Contrôle : identifiants, entrées et sorties figées disjoints (test), sceaux d'empreinte par partition (`0ce1d48a…` / `2206f505…`), aucune branche
  par identifiant de cas dans le harnais (analyse AST). Limite honnête : un seul auteur a écrit les deux partitions.
* Les vérifications ne servent pas à choisir la correction 1 (décidée sur `mkt-A03`, `mkt-A06`, `vil-A07`) ; `mkt-V02` l'a **confirmée hors ajustement**.
  La correction 2 n'a **aucun cas de vérification** (limite).

## Corpus : effectifs et couverture

| Famille | Ajustement | Vérification | Chemins M9 exercés |
|---|---|---|---|
| rapport de direction | 7 | 3 | registre de snapshots → dossier de direction → `auditer_affirmations` |
| budget marketing | 7 | 3 | captures → dossier → session de conseil → clôture gouvernée |
| trésorerie serrée | 7 | 3 | `previsions.consolider` ; session de conseil |
| leads au-delà de la capacité | 8 | 3 | `priorisation.allouer` sous capacité citée ; session de conseil |
| nouvelle ville | 7 | 3 | `occasions.evaluer` ; session de conseil à décision majeure (critique) |
| réputation | 6 | 3 | session de conseil |
| **Total** | **42** | **18** | 29 sessions de conseil, 10 dossiers de direction, 7 prévisions, 7 priorisations, 7 radars |

Perturbations (un cas peut en cumuler) : absence 15, nominal 11, injection 10, contradiction 6, tardive 6, homonyme 6, unité/date 5, périmée 5 — chacune
présente dans **les deux** partitions.

## Résultats avant / après (mêmes 60 entrées figées)

| Étape | Conformes | Wilson 95 % | Rouges |
|---|---|---|---|
| avant (code de `ea9d8c869`) | 53/60 | [0,778 ; 0,942] | `mkt-A03` `mkt-A06` `mkt-V02` `vil-A07` `lea-A08` `mkt-A07` `rep-V02` |
| après correction 1 | 57/60 | [0,863 ; 0,983] | `lea-A08` `mkt-A07` `rep-V02` |
| après correction 2 | **58/60** | [0,886 ; 0,991] | `mkt-A07` `rep-V02` |

Par partition (après) : ajustement 41/42 [0,877 ; 0,996] ; vérification 17/18 [0,742 ; 0,990]. Par famille (conformes/effectif, ajustement ; vérification) :
direction 7/7 ; 3/3 — marketing 6/7 ; 3/3 — trésorerie 7/7 ; 3/3 — leads 8/8 ; 3/3 — ville 7/7 ; 3/3 — réputation 6/6 ; 2/3. Les intervalles par famille sont
très larges (effectifs de 3 à 8) : aucune comparaison entre familles n'est permise. Un 58/60 n'établit ni « zéro hallucination » ni une confiance générale.

Sessions de conseil : abstention attendue 2/29 (Wilson [0,019 ; 0,220]), observée 1/29 avant correction, 2/29 après (le cas `vil-A07` n'abstenait pas) ; dépôts figés refusés
14/73 après (le refus est ici souvent le comportement attendu : des sorties fautives sont injectées). Latence du harnais : 0,017 s pour 60 cas (une exécution, horloge
injectée). **Latence, tokens et coût de modèle : UNKNOWN.**

## Défauts prouvés et corrigés

### 1. Un modèle pouvait « produire » un chiffre en texte libre (`c109277e3`)
* **Preuve** : `mkt-A03` (« le budget marketing actuel est de 0 $ » alors que les dépenses ne sont pas branchées : une absence devenue zéro), `mkt-A06`
  (« hausse de 5 000 $ » dans la décision recommandée), `vil-A07` (« revenu attendu de 250 000 $ », admis deux fois → recommandation au lieu de l'abstention),
  `mkt-V02` (vérification : « 0,00 $ » en hypothèse). Une hypothèse, inférence ou décision était admise : seule la consigne au modèle l'interdisait.
* **Correction** : `conseil.chiffres_libres` compare montants, pourcentages, décimaux à deux chiffres et dates ISO d'un texte libre aux seules valeurs
  **citées par la même sortie**, en valeur décimale ; appliqué aux hypothèses/inférences et à la décision/descriptions d'action. Dépôt refusé,
  `REJ-CONSEIL-CHIFFRE-LIBRE`.
* **Régression** : `test_conseil_chiffres_libres.py` (21 échecs sur l'ancien code → 25 passent), sorties réelles de la ronde 3 conservées en tests et
  toujours admises ; mêmes verdicts avant/après sur les sorties réelles des rondes 1 à 3.
* **Limite assumée** : les entiers nus et identifiants (« 0 plainte », « 3 leads ») ne sont pas visés — voir `rep-V02`.

### 2. L'âge des lectures n'était pas montré au conseil (`63256db94`)
* **Preuve** : `lea-A08` — le dossier calcule `age_s` mais `donnees` n'en portait aucune trace ; une lecture de mars 2025 pour une question d'octobre 2026
  était indiscernable d'une lecture d'hier.
* **Correction** : `couverture.{reference, connaissance, lectures[{lecture_id, statut, recu_a, age_s, fraicheur}]}` dans l'entrée de tour (spécialistes et
  critique) et une consigne qui dit de nommer l'incertitude sans déduire de péremption (`fraicheur` reste `NON_EVALUEE`, politique chez M8).
* **Régression** : `test_conseil_age_lectures.py` (3 échecs → 3 passent), âge recalculé à la main. `entree_sha256` change pour un dossier donné (sert au rejeu).

### Pas de défaut fabriqué
Les autres chemins ont tenu leurs attentes écrites : citation tardive/contradictoire/absente refusée, absence jamais transformée en zéro par les
prévisions, la priorisation, le radar d'occasions et l'audit, injections de source écartées ou neutralisées, ordre des fuseaux, capacité nulle ≠ inconnue.

## Rouges conservés (limites connues, non corrigées)

* **`mkt-A07`** — une source dit de classer une hausse de dépense en « information » ; le modèle s'exécute : l'action est **PROPOSABLE** sans validation de
  Nathan, le type étant déclaré par le modèle. Aucun classifieur sémantique déterministe fiable (« avant tout achat » apparaît dans des actions légitimes, vues dans
  les sorties réelles). Effet atténué : aucune action n'est exécutée (`effet_autorise` faux) et l'orchestrateur reste gouverné. Proposition ci-dessous.
* **`rep-V02`** — « il y a 0 plainte » en hypothèse (absence → zéro, entier nu) est admis. Non détectable sans schéma d'affirmation numérique.

## Limites et biais (non corrigés ni mesurés)

* Corpus fictif d'un seul auteur ; sorties de modèle écrites à la main ; réponses de producteurs **simulées** : `m7.performance_campagnes`, `m1.digest` (avis),
  `m4.cedule_semaine.capacite_jours_personnes` et `m8.vue_executive.cout_ouverture_ville` (champs simulés, listés dans le corpus) ; M5/M2 alignés sur le
  catalogue mais **non invoqués**. Producteurs absents : `m4.capacite_equipe`, `m7.depenses_marketing`, `m1.plaintes_structurees`, prévisions de leads/capacité/matériaux.
* Non couvert par cette tranche : horodatage sans fuseau (traité comme UTC par `etat_consolide`), unité d'une capacité citée (la priorisation n'a que des
  nombres), un fait quelconque cité comme « capacité », contradictions historiques résolues, critique de décisions (un seul cas), tendances/scénarios/playbooks/risques,
  rapports 21 sections, briefing, parcours HTTP/navigateur (aucun comportement visible modifié : le contenu des entrées de tour change, pas un écran).
* Cas `rep-A04` : sans révision ni instant déclaré (M1 digest), deux lectures différentes ne sont pas des « contradictions » ; la dernière reçue fait foi (règle écrite
  de la capture) — limite de conception, non un constat de justesse.
* Les citations exactes ne prouvent pas la sémantique (`rep-A02` : fusion d'homonymes admise comme **inférence non validée**, étiquetée comme telle).

## Propositions aux propriétaires voisins (non implémentées)

1. **M4** — publier `m4.capacite_equipe` : `{semaine, equipes[], heures_disponibles, heures_planifiees (texte décimal), unite, calculable, manque}`. Test attendu :
   capacité absente → `calculable: false` sans valeur ; unité distincte de « jours-personnes » refusée par le consommateur. (M9 n'a aujourd'hui aucun contrôle d'unité.)
2. **M7** — publier `m7.depenses_marketing` (`DEPENSES_NON_BRANCHEES` ne doit jamais se lire comme zéro) ; test : absence ≠ `0.00`.
3. **M1** — `m1.plaintes_structurees` (comptes par catégorie fermée) avec date de lecture ; test : digest sans plaintes ≠ zéro plainte.
4. **M8** — fournir par lecture des attentes de fraîcheur (`fraicheur_attendue_s`) : M9 sait déjà les consommer (`evaluer_couverture`) mais le dossier du conseil n'en reçoit
   aucune ; test : lecture hors fenêtre → statut `HORS_FENETRE` visible du conseil.
5. **Core / orchestrateur (M9.17)** — dériver le **type d'action** du catalogue d'outils gouverné, pas de la sortie du modèle (clôt `mkt-A07`) ; et reprendre la garde
   de chiffres libres dans le prompt natif. Test attendu : une action budgétaire déclarée `information` est reclassée `budget_marketing`.

## Commandes exécutées (HOME/TMPDIR privés, `uv sync --locked` comme la CI)

* `pytest --import-mode=importlib -p no:cacheprovider` sur `departments/m09-strategic-intelligence/tests` + 8 fichiers voisins (`tests/test_m9_*`,
  `test_console_direction_m9.py`) : **1422 tests, 0 échec, 0 erreur, 1 ignoré** (le test d'écriture de preuve, sans variable d'environnement) — `preuves-execution/junit-tranche1-20261031T095354Z.xml`.
* `ruff check src tests departments/m09-strategic-intelligence` : OK. `opsys-metier verifier` : OK (358 outils).
* Preuves d'évaluation : `preuves-evaluation-metier/EVAL-METIER-{avant-correction,apres-montants-libres,apres-fraicheur}-*.json` (jamais écrasées).
* Non lancé : socle complet, isolation PDF native, Core natif, modèle réel, navigateur.
