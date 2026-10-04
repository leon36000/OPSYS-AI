# Audit M3 — Estimation Intelligence

> Audit historique du 28 septembre 2026, conservé pour traçabilité. Les évolutions ultérieures
> ne sont pas inventoriées ici. Consulter le [plan de consolidation](../programme/RESTRUCTURATION-2026-09-30.md)
> et les [recherches actuelles](../research/R16-2026-09-30/README.md) pour M1/M5/M7/M10. Un statut
> ancien et un nombre de tests ne certifient pas le périmètre cible complet.


**Date :** 28 septembre 2026. **Auditeur :** agent d'audit (lecture seule + `pytest` M3).
**Sources de vérité utilisées :** `docs/produit/DEFINITION-PRODUIT.md` (§1, §5, §6, §7-M3, §8, §9,
§10, §13 — fait foi en cas de conflit), `AGENTS.md`, `docs/architecture/{ARCHITECTURE,DEPARTEMENTS,
MOBILE}.md`, `core/UPSTREAM.md`, `departments/m03-estimation/**` (code, `docs/bmad/*`, tests),
`departments/m06-material-control/src/m6_material_control/{contrats,frontieres}.py` (frontière
M3→M6, lecture seule), `docs/research/{R7-m3-m4,INGREDIENTS}.md`, `pyproject.toml`,
`src/opsys/{outils,approbations,console/application}.py`. Recherche web pour les briques absentes
de R7 (géocodage, Florence-2, OWLv2), licences vérifiées à la source. Aucune autre source n'est
contredite ci-dessous ; un chiffre manquant est marqué `ABSENT`, jamais inventé.

## 0. Verdict global

M3 est, comme l'affirme `README.md`, le département **le plus mûr et le mieux outillé du dépôt** :
15 fichiers/3 122 lignes de logique pure (stdlib + PyYAML, zéro réseau, zéro horloge, zéro modèle),
22 fichiers/9 401 lignes de tests, plus 13 fichiers/3 074 lignes d'un outillage de preuve par
mutation unique dans le dépôt (neutralisation de gardes, batteries de mutations métier, bilan des
gates — voir §1). **577 tests collectés, 577 réussis, 0 échec** (commande imposée, §PREUVE),
conforme à l'énoncé (≈ 6 minutes, dominées par les sous-processus de mutation). Chaque story S001 à
S009 du PRD BMAD est réellement implémentée, testée et, pour 9 des 15 modules, mutée.

**Mais l'écart le plus important, à corriger avant tout autre travail, n'est dans aucune story
individuelle : c'est leur COMPOSITION.** L'outil exposé aux agents, `m3_estimer_projet`
(`src/m3_estimation/outils.py::estimer_projet`), n'importe que 6 des 15 modules du paquet
(`blocage_prix, contrats, hierarchie_echelle, monte_carlo, plancher, qualite_photos`). Il
**n'appelle jamais** `validation.py` (S001, contrat `LeadQualifie` + marqueur M2), `devis.py` (S007,
`devis_id` + assemblage du contrat gelé `EstimationV1`), `registre.py` (S008, registre append-only
estimé-vs-réel) ni `signaux.py` (relance vers M2). Résultat mesuré :

- **`m3_estimer_projet` n'émet jamais de `devis_id`.** M4 en a besoin pour associer une intervention
  à son estimation (§6, §7-M3, §8 DEFINITION-PRODUIT.md ; PRD M3 §5). Le champ n'existe même pas
  dans la sortie actuelle (`grep devis_id tests/test_outils_agent.py` → 0 résultat).
- **Aucune estimation n'est jamais inscrite au registre estimé-vs-réel.** Le mécanisme hash-chaîné
  (`registre.py`, 24 tests + mutation) est solide mais orphelin : `grep -rn "registre\." src/` ne le
  trouve appelé que par `digest.py`, lui-même jamais appelé.
- **Le point connu du mandat est expliqué par cette même cause.** `VERDICT_REFERENCE_ECHELLE_ABSENTE`
  n'est jamais construit par `outils.py` parce que celui-ci ne consulte jamais
  `motifs["photos_avec_reference"]` (disponible depuis `hierarchie_echelle.classifier_niveau_confiance`)
  pour le cas `MULTI_VUES`/`MONO_VUE_BORNES_LARGES` sans référence certifiée. Le seul endroit du
  paquet qui sait sélectionner ce verdict est `devis._selectionner_verdict` — jamais appelé.
  **Le code le documente lui-même** : `verdicts.py` (lignes 16-19) dit texto qu'« ce dépôt compte
  déjà deux valeurs de `VERDICTS_ESTIMATION` sans producteur, c'est un défaut connu qu'il ne faut pas
  reproduire ». Le second verdict orphelin est `CONTRAT_ENTREE_INVALIDE` : `validation.py` rejette
  bien un contrat malformé, mais avec des codes `REJ-*` du catalogue `CODES_M3` (technique), jamais
  avec le verdict métier `VerdictEstimation.CONTRAT_ENTREE_INVALIDE` — et `validation.py` n'est de
  toute façon appelé par personne.
- **La réponse ad hoc de `estimer_projet` ne respecte pas le contrat gelé `EstimationV1`.** Elle
  utilise `intervalle` au lieu de `intervalle_confiance`, omet `devis_id`, `empreinte_marqueur_m2`,
  `hash_maillon`, et porte `bareme_version` seulement sur la branche non bloquée. Les tests qui
  l'exercent (`test_outils_agent.py`) valident donc une forme différente de celle que M4/M6
  attendent d'après le PRD.

Recommandation immédiate (détaillée en Plan par phases) : écrire l'orchestrateur qui manque —
`estimation.py`, nommé et décrit dans `docs/bmad/03-ARCHITECTURE.md` §1 mais absent du dépôt — pour
composer les 15 modules dans l'ordre déjà prouvé par les tests unitaires de chacun, et faire de
`estimer_projet` un simple appelant de cet orchestrateur. C'est un travail de câblage, pas de
nouvelle logique métier : chaque brique existe déjà, testée.

## 1. Inventaire M3.1–M3.18

Statuts : **PRÉSENT** (fait, testé, câblé jusqu'à l'outil agent), **PARTIEL** (logique réelle et
testée mais non composée dans `m3_estimer_projet`, ou portée incomplète), **ABSENT** (rien dans
`src/m3_estimation`).

| # | Fonction (§7-M3 DEFINITION-PRODUIT.md) | Statut | Fichiers | Tests / preuve |
|---|---|---|---|---|
| M3.1 | Intake M2 + vérification readiness | PARTIEL | `validation.py` (320 l.), `contrats.py` | `test_validation_entrees.py` (25 tests), `test_gate_brief_contrat.py`/`test_gate_contrat_consomme_types.py`/`test_gate_copies_declarees.py`/`test_gate_renvois_internes.py`/`test_gate_grandeurs_fournies.py` (30 tests de cohérence BMAD). **Non appelé par `outils.py`** ; aucun script `muter_validation.py` |
| M3.2 | Contexte propriété/site (adresse, distance, accès, historique) | ABSENT | — | Le contrat `LeadQualifie` porte `ville: str` et rien d'autre ; aucune distance, aucun historique de propriété |
| M3.3 | Pipeline vision : qualité, classification, détection, segmentation, annotation | PARTIEL | `qualite_photos.py`, `hierarchie_echelle.py` | Qualité et classification **sur métadonnées déclarées** seulement (résolution, éclairage 0-10, angle, `reference_echelle` booléenne) ; **aucun pixel lu** (confirmé R7 §0). Détection/segmentation/annotation réelles : ABSENTES |
| M3.4 | Qualité photos + confiance mesures (résolution, flou, angles, échelle, complétude) | PRÉSENT | `qualite_photos.py` (180 l.) | `test_qualite_photos.py` (17 tests) + `muter_qualite_photos.py`. Couvre résolution/éclairage/angles/échelle/complétude déclarés ; **le flou n'est pas détecté** (nécessiterait une lecture pixel, cf. OpenCV en §3) |
| M3.5 | Détection/segmentation (Grounding DINO+SAM2+géométrie), replis | ABSENT | — | Le « repli » (règles sur métadonnées, mesure manuelle) **est le seul chemin existant**, par construction et non par bascule programmée — cf. §10 DEFINITION-PRODUIT.md. Zéro dépendance vision dans `pyproject.toml` |
| M3.6 | Moteur de mesure avec bornes d'incertitude | PRÉSENT | `hierarchie_echelle.py` (171 l.), `outils.py::NIVEAUX_STATISTIQUES_PAR_CONFIANCE` | `test_hierarchie_echelle.py` (22 tests) + mutation ; `test_intervalle_plus_etroit_avec_reference_echelle_quavec_multi_vues_ou_mono_vue` (test_outils_agent.py) prouve l'élargissement mécanique de l'intervalle par palier de confiance |
| M3.7 | Estimation géospatiale QC (adresse, distance, région) | ABSENT | — | Aucun code de géocodage/distance/région dans `src/m3_estimation` |
| M3.8 | Estimateurs par service (gouttières, revêtement, soffite/fascia, réparation) | ABSENT | `monte_carlo.py` (générique) | Le moteur Monte Carlo est générique (coût unitaire × quantité), pas spécialisé par service. **Écart d'énuméré** : `contrats.TYPES_TRAVAUX = (renovation_totale, extension, ravalement, isolation_thermique, autre)` — copié de M2 — ne contient AUCUN des 4 services réels de GRS (§1, §7-M1 DEFINITION-PRODUIT.md). Le système ne peut littéralement pas accepter `"gouttières"` aujourd'hui |
| M3.9 | Matériaux/main-d'œuvre (prix M6 ; repli `fallback_price_book`) | PARTIEL | `contrats.py::CHAMPS_BAREME` (via `BaremeCouts`), consommé par `monte_carlo.py` | Mécanisme fail-closed correct (CA-M3-21, testé) mais **aucune intégration M6** (M6 a son propre `catalogue.py`/prix, aucun appel croisé) et le champ n'est jamais étiqueté `fallback_price_book` (terme du glossaire, absent du code) — tout barème fourni aujourd'hui EST de facto le repli, silencieusement |
| M3.10 | Risque et complexité (hauteur, accès, pente, arbres, distance, urgence, petit chantier) | ABSENT | — | `urgence_declaree` est validé structurellement (`validation.py:179`) puis **jamais relu** ailleurs dans `src/`. Aucune notion de hauteur/accès/pente/arbres |
| M3.11 | Prix et marge (plancher, scénarios prudent/normal/agressif, jamais sous plancher sans validation) | PARTIEL | `plancher.py` (151 l.) | `test_plancher.py` (18 tests) + mutation. Alerte correcte et non bloquante par conception. **Manquent** : un seul scénario est produit (pas 3), **aucun champ marge/prix recommandé** distinct du coût (§2.6 ci-dessous), et l'alerte n'atteint jamais un humain (digest et dashboard non câblés → pas de garantie de validation Nathan) |
| M3.12 | Monte Carlo (P50, P80, facteurs dominants) | PARTIEL | `monte_carlo.py` (216 l.) | `test_monte_carlo.py` (20 tests) + mutation ; déterminisme bit-à-bit prouvé (CA-M3-10/11). Tirage **uniforme** seulement (pas triangulaire/PERT) ; pas de P50 explicite (un seul niveau/intervalle) ; pas de ventilation par facteur dominant |
| M3.13 | Génération soumission brouillon (description, matériaux, exclusions, hypothèses, prix, délai, options) | ABSENT | `devis.py` (mal nommé pour ce rôle) | `devis.py` assemble un **contrat de données** interne (`EstimationV1`), pas un document client. Aucun gabarit, aucun PDF/HTML, aucune dépendance de rendu |
| M3.14 | Revue et approbation humaine | ABSENT | — | Aucun import de `opsys.approbations` dans `src/m3_estimation` ; les 5 outils exposés sont tous à `Autonomie.T0` par défaut (défaut de la classe `Outil`, `src/opsys/outils.py:38`) |
| M3.15 | Apprentissage estimé vs réel | PARTIEL | `registre.py` (222 l.) | `test_registre.py` (24 tests) + mutation ; chaînage de hash et détection d'altération prouvés (CA-M3-17/18). **Zéro appelant** hors ses propres tests et `digest.py` (lui-même orphelin) ; aucune voie M5/M6 → `cout_reel` |
| M3.16 | Base de connaissances construction QC (RAG, prix fournisseurs, historique) | ABSENT | — | Aucune base, aucun appel réseau (interdit par conception, CA-M3-20) |
| M3.17 | Tableau de bord et mobile | ABSENT | — | Console OPSYS générique (`src/opsys/console/`) n'a aucune page M3 (grep vide) ; app mobile phase 1 = relais générique caméra→agent (MOBILE.md), écran dédié « Estimateur » = phase 2, non construit |
| M3.18 | Intégration mémoire (M10) | ABSENT | — | Déclaré dans `department.yaml::memoire` (métadonnées seulement) ; aucun appel à un module mémoire dans `src/m3_estimation` |

**Comptes exacts (mesurés)** : 15 fichiers/3 122 lignes dans `src/m3_estimation/` ; 22 fichiers
Python sous `tests/` (20 `test_*.py` + 2 utilitaires partagés)/9 401 lignes/274 fonctions `def test_`
(plusieurs paramétrées) ; 13 fichiers/3 074 lignes sous `tests/outils_preuve/` (mutation/preuve,
invoqués en sous-processus par `test_gardes_des_outils.py` et `test_outils_de_preuve.py`, jamais
collectés directement par pytest). **5 outils d'agent** exposés (`outils()` dans `outils.py`) :
`m3_estimer_projet`, `m3_qualifier_photos`, `m3_classifier_confiance`, `m3_simuler_intervalle`,
`m3_confronter_plancher`. Mutation-testée (`muter_<module>.py` présent) : `plancher`,
`blocage_prix`, `digest`, `monte_carlo`, `hierarchie_echelle`, `conformite`, `devis`, `registre`,
`qualite_photos` — **9 modules sur 15**. Non mutée : `validation.py`, `signaux.py`, `outils.py`,
`verdicts.py`, `contrats.py`, `__init__.py`.

**Commande exécutée (mandat de cet audit) :**
`/opt/opsys-venv/bin/python -m pytest departments/m03-estimation/tests -q --import-mode=importlib
-p no:cacheprovider` → **exit code 0, 577 tests collectés, 577 réussis, 0 échec** (voir PREUVE).

## 2. Écarts en détail

### 2.1 Modèle de données — le contrat `EstimationV1` couvre ~7 des ~12 champs attendus

DEFINITION-PRODUIT.md §5 exige que chaque estimation porte : l'estimation, une plage de confiance,
**les hypothèses**, les données utilisées, les données manquantes, **les risques**, les incertitudes,
les prochaines infos à collecter, **la marge attendue**, **le prix recommandé**, les preuves
visuelles et géospatiales, le statut de validation humaine. Le contrat gelé réel
(`contrats.CHAMPS_ESTIMATION_V1`, 12 clés) couvre : `devis_id`, `lead_id`, `empreinte_marqueur_m2`,
`niveau_confiance`, `verdict_estimation`, `bareme_version`, `prix_bloque`, `intervalle_confiance`,
`alerte_plancher`, `raison_blocage`, `graine_monte_carlo`, `hash_maillon`. **Absents comme champs
structurés** : hypothèses, risques, scénarios (prudent/normal/agressif), preuves
visuelles/géospatiales, statut de validation humaine. `elements_manquants` (la liste des « prochaines
infos à collecter ») existe dans la réponse ad hoc de `outils.py` mais **pas dans le contrat gelé**
`EstimationV1` lui-même.

**Constat le plus concret, non documenté ailleurs dans le dépôt** : `BaremeCouts.postes.<type>` ne
porte que `cout_unitaire_min`/`cout_unitaire_max` — un **coût**, jamais un prix. `monte_carlo.py`
simule donc un intervalle de **coût**, que `plancher.py` compare ensuite à `plancher_rentable`. Nulle
part le paquet n'applique une marge pour produire un **prix client recommandé** distinct du coût :
soit le barème fourni par l'appelant est censé déjà inclure la marge (non déclaré, non testé), soit
la fonction M3.11 « prix et marge » n'est tout simplement pas construite. Aucun champ `marge`,
`taux_marge` ni `prix_recommande` n'existe dans `contrats.py`. À trancher explicitement avant
d'exposer un intervalle à un client : aujourd'hui, le mot « prix » de l'interface (`m3_estimer_projet`)
désigne en réalité un **coût**.

`fallback_price_book` (terme du glossaire §15 DEFINITION-PRODUIT.md) n'existe nulle part comme
identifiant dans le code — seul `bareme_version: str | null` joue ce rôle, sans distinguer un barème
« interne versionné en repli » d'un futur barème fourni par M6.

### 2.2 API — aucune, en dehors des outils MCP

Décision de l'ingénieur en chef n°2 : les moteurs métier sont « exposés aux agents comme outils et
à l'app/dashboard par API ». M3 respecte la première moitié (5 outils MCP T0, `outils.py`) mais pas
la seconde : `grep -rl "fastapi\|FastAPI" src/ departments/` ne trouve que
`src/opsys/console/application.py` (console générique départements/approbations/budgets/modèles),
**aucune route `/api/m3`**. `departments/m03-estimation/contracts/` ne contient qu'un `.gitkeep` :
aucun schéma JSON exporté que l'app mobile ou un futur service HTTP pourrait consommer sans relire
le code Python.

### 2.3 Événements — le flux matériaux M3 → M6 (§6) n'existe d'aucun côté

Recherche croisée (lecture seule de M6, hors périmètre de modification) : `m6_material_control/
contrats.py` ne définit **aucun** contrat `BesoinsMateriauxM3` ; son seul champ de traçabilité vers
M3 est `devis_id` dans `CHAMPS_WCT` (le ticket de fin de travaux transmis par M4), pas un message de
besoins matériaux entrant. Côté M3, aucun code n'émet « items, quantités estimées, unité, facteur de
perte, confiance » (M3.9/§6). **Les deux bouts du flux central décrit en §6 DEFINITION-PRODUIT.md
(« M3 finalise l'estimation et envoie les besoins matériaux à M6 ») sont absents.** De même, aucun
événement « estimé vs réel » n'est reçu par M3 depuis M4/M5/M6 (le registre existe mais rien ne
l'alimente en provenance de l'extérieur, §1 M3.15).

Le signal de relance vers M2 sur photos faibles (M3.2 du PRD, `signaux.py`) est écrit et testé
(8 tests) mais, comme `devis.py`/`registre.py`, jamais appelé — aucun lead ne reçoit aujourd'hui de
`SignalRelanceM2` réel.

### 2.4 Outils d'agent — 5 outils T0, aucun T1/T2, aucun garde-fou d'envoi client

Les 5 outils (`m3_estimer_projet` et les 4 unitaires) sont tous à l'autonomie par défaut `T0`
(lecture/calcul pur), ce qui est cohérent avec leur absence actuelle d'effet de bord — mais devient
faux dès que le câblage du §0 est corrigé : écrire au registre est une action `T1` (écriture interne)
au sens de `docs/architecture/DEPARTEMENTS.md`, et le PRD BMAD classe déjà S007/S008 en T1/T2. Il
n'existe **aucun outil `m3_envoyer_devis_client`** (SOUL.md l'interdit explicitement sans approbation
— l'interdiction est donc respectée par absence totale de la fonction, pas par une porte construite
et testée).

### 2.5 Écrans mobiles vendeur/admin/employé (§9) — phase 1 seulement, par relais générique

`docs/architecture/MOBILE.md` (qui fait foi sur la stratégie mobile actuelle, et diverge du
« forge-app » React Native/Expo décrit en §9 DEFINITION-PRODUIT.md — point ouvert, §5) documente une
phase 1 : l'app officielle OpenClaw sert de nœud générique, et une photo de chantier devient un
message à l'agent M3 qui appelle `m3_estimer_projet` via le chat. **Aucun écran dédié n'existe** :
pas de prise de photo guidée avec référence d'échelle, pas de retour visuel « prix bloqué : il
manque… » (M3.4 pourtant PRÉSENT côté logique), pas d'écran vendeur pour comparer des scénarios
(inexistants, §2.1) ou approuver une soumission (inexistante, §1 M3.13/M3.14), pas d'écran employé
« matériel réel après chantier » côté M3 (celui-ci relève de M6.10, non audité ici). Phase 2 (fork
d'app, écran « Estimateur ») est documentée mais non commencée.

### 2.6 Vues dashboard — aucune

`src/opsys/console/{application,pages,tableau_de_bord}.py` ne contiennent aucune référence à M3 ou
« estimation » (`grep` vide). Le digest quotidien vers Nathan (`digest.py`, testé isolément,
21-planification déclarée dans `department.yaml` avec cron `0 7 * * 1-5`, **en pause** par défaut
comme tout le dépôt) n'est exécuté par rien : ni planificateur actif, ni page console.

### 2.7 Portes et replis (SAM2 GPU, Cognee, API géo)

| Porte | État constaté | Repli documenté | Repli réellement câblé |
|---|---|---|---|
| SAM2/vision en production sur GPU | Aucune dépendance vision dans `pyproject.toml`, aucun sidecar dans `deploy/docker-compose.yml` (`grep -i "sam2\|vision\|sidecar" deploy/` → vide) | Règles/OpenCV/mesure manuelle (§10) | **Oui, de facto** — c'est le seul mode existant, pas un choix basculable |
| Cognee (mémoire/graphe) | Aucun appel dans `src/m3_estimation` | Relations en base, graphe local | Sans objet pour M3 seul (dépend de M10, ABSENT — hors périmètre) |
| API géo (géocodage, Street View) | Aucun code, aucune clé, aucun appel réseau (interdit par `conformite.py`) | Non spécifié pour M3 dans §10 (seul M4 y a un repli documenté pour le routage) | Absent des deux côtés — **aucun repli n'est même défini** pour M3.7 |

Le mode « bridé » est donc le mode réel et unique de M3 aujourd'hui, ce qui respecte P10 par défaut
— mais aucune des trois portes n'a de bascule construite (flag de config, détection de service
disponible) : brancher SAM2 demain exigerait un vrai développement, pas un simple retrait d'un drapeau.

### 2.8 E2E exigés — aucun

`grep -rl "m3_estimer_projet\|m3_estimation" departments/m0{1,2,4,6}-*/**/*.py tests/*.py` ne
retourne aucun fichier hors de `departments/m03-estimation` lui-même. **Aucun test ne simule le flux
M2 → M3 → M4/M6** décrit en §6. Les 6 scénarios E2E exigés par la preuve de complétion de M3
(§7-M3 : gouttières avec photos suffisantes, photos insuffisantes, revêtement, estimation risquée,
estimé vs réel, contexte géospatial) sont **tous absents** ; ce que le dépôt appelle « tests » pour
M3 sont des tests unitaires et des gates de cohérence documentaire, pas des E2E inter-départements.

## 3. Briques candidates par écart

`docs/research/R7-m3-m4.md` (28 sept. 2026, licences vérifiées API GitHub/`LICENSE`) couvre déjà
vision, distributions Monte Carlo et génération PDF pour M3 ; repris ici avec verdict, complété par
le géocodage (absent de R7/INGREDIENTS.md) et par Florence-2/OWLv2 (alternatives à Grounding DINO
demandées par le mandat, non couvertes par R7).

### 3.1 Écart « mesure par pixel » (M3.3, M3.5) — vérifier la référence d'échelle déclarée

| Brique | Licence vérifiée | Rôle | Verdict |
|---|---|---|---|
| [SAM 2](https://github.com/facebookresearch/sam2) (Meta) | Apache-2.0 | Segmentation zéro-shot de la cible et de l'objet de référence | **Retenir**, Phase 2, sidecar FastAPI isolé ; poids séparés du dépôt |
| [Grounding DINO](https://github.com/IDEA-Research/GroundingDINO) (via `transformers`) | Apache-2.0 | Localisation par texte libre de l'objet de référence | **Retenir** via `transformers` (dépôt d'origine peu actif depuis 2024-08) |
| [Florence-2](https://huggingface.co/microsoft/Florence-2-large) (Microsoft) | **MIT** (vérifié, fichier `LICENSE` du repo HF) | Alternative unifiée détection+légende+segmentation en un seul modèle, prompts texte | **Retenir comme alternative simplifiante** à Grounding DINO+SAM2 (un seul modèle, licence encore plus permissive) ; à comparer en Phase 2 sur qualité réelle |
| [OWLv2](https://huggingface.co/docs/transformers/model_doc/owlv2) (Google, via `transformers`) | **Apache-2.0** (vérifié) | Détection zéro-shot par texte, alternative à Grounding DINO | **Retenir comme alternative** ; licence la plus permissive du trio détection |
| [SAM 3](https://github.com/facebookresearch/sam3) (Meta) | « SAM License » personnalisée, source-available, clause anti-rétro-ingénierie | Détection+segmentation par concept texte en un appel | **Signaler seulement** — validation juridique requise avant usage (licence non-OSI) |
| [Depth Anything V2](https://github.com/DepthAnything/Depth-Anything-V2) — **Small uniquement** | Small = Apache-2.0 ; **Base/Large/Giant = CC-BY-NC-4.0** | Profondeur relative → mesure métrique avec point d'échelle | **Retenir Small seulement** ; exclure Base/Large/Giant du produit (licence non commerciale) — exemple canonique cité par le mandat où la licence des POIDS diffère de celle du code |
| [OpenCV](https://github.com/opencv/opencv) (`opencv-python-headless`) | Apache-2.0 | Netteté (Laplacien) + exposition réels, remplace `eclairage` déclaré | **Retenir en priorité (effort S)** — seule brique de cette liste utilisable sans sidecar ni GPU, corrige directement la lacune « flou » de M3.4 |

### 3.2 Écart « P50/P80, distribution réaliste » (M3.12)

| Brique | Licence | Rôle | Verdict |
|---|---|---|---|
| `random.Random.triangular` (stdlib) | — | Remplace `uniform(min,max)` par une triangulaire, déterminisme bit-à-bit conservé, **zéro nouvelle dépendance** | **Retenir en premier** (effort S) |
| [scipy](https://github.com/scipy/scipy) `stats.beta` | BSD-3-Clause (vérifié) | Formule PERT fermée (~15 lignes) si une triangulaire ne suffit pas | **Retenir en option** seulement si PERT devient un besoin validé |
| [betapert](https://github.com/tadamcz/betapert) | **Aucun fichier LICENSE détecté**, 1⭐, stale | Implémentation PERT toute faite | **Écarter** — réimplémenter la formule plutôt que dépendre d'un paquet sans licence |
| SymPy (piste du mandat) | BSD-3-Clause | Calcul symbolique | **Non pertinent** : M3 fait de la simulation numérique déterministe (échantillonnage), pas de résolution symbolique ; aucun besoin identifié dans `monte_carlo.py` |

### 3.3 Écart « soumission brouillon » (M3.13)

| Brique | Licence | Rôle | Verdict |
|---|---|---|---|
| [WeasyPrint](https://github.com/Kozea/WeasyPrint) | BSD-3-Clause | HTML/CSS → PDF depuis un gabarit Jinja2 alimenté uniquement par `EstimationV1` figé | **Retenir** (effort S, pur Python) |
| [Typst](https://github.com/typst/typst) | Apache-2.0 | Alternative sans dépendance système (Pango/cairo) | **Retenir en secours** si WeasyPrint pose problème de paquet système sur le VPS |

### 3.4 Écart « estimation géospatiale QC » (M3.7) — absent de R7/INGREDIENTS.md, recherché pour cet audit

| Brique | Licence vérifiée | Rôle | Verdict |
|---|---|---|---|
| [Nominatim](https://nominatim.org/) (OSM) | **Code GPL-2.0/GPL-3.0** (vérifié, wiki OSM) ; données OSM en ODbL (partage à l'identique) | Géocodage/reverse générique auto-hébergeable | **Retenir seulement en service séparé non modifié**, interrogé en HTTP (règle AGENTS.md GPL/AGPL) ; jamais `import` direct |
| [Photon](https://github.com/komoot/photon) (komoot) | **Apache-2.0** (vérifié) ; moteur de recherche interne migré d'Elasticsearch vers **OpenSearch** (Apache-2.0) dans les versions récentes | Géocodeur OSM prêt à l'emploi, API REST simple | **Retenir en premier choix** — licence la plus propre du trio, et évite l'ancien risque Elastic License (explicitement refusée par AGENTS.md) que les vieilles versions basées Elasticsearch auraient posé |
| Adresses Québec / AQgéobâti (MRNF, service REST ESRI) | Licence du gouvernement ouvert – Québec/Canada, usage commercial permis | Géobase d'adresses officielle du Québec, la plus précise pour ce marché | **Retenir pour la précision QC, mais signaler un risque calendrier majeur** : la diffusion des produits Adresses Québec **se termine en décembre 2026** ; migration prévue vers le **Référentiel québécois du transport terrestre (RQTT)**, évolution d'AQréseau+ — à re-vérifier avant toute intégration, le service actuel n'a qu'environ 3 mois de vie restante à la date de cet audit |

Recette suggérée : Photon (Apache-2.0) comme géocodeur par défaut auto-hébergé (sidecar Docker),
Adresses Québec/RQTT comme source d'enrichissement régional QC une fois la transition 2026 stabilisée,
jamais Street View qu'en contexte (§7-M3 : « jamais de remplacement des photos du client »).

### 3.5 OR-Tools / SymPy — piste du mandat, non pertinente pour M3 en l'état

`docs/produit/DEFINITION-PRODUIT.md` §7/§11 mentionne « OR-Tools, SymPy et Monte Carlo partiellement
présents » pour l'état de juin 2026 — **mesure contredite par le code actuel** : ni `ortools` ni
`sympy` n'apparaissent dans `pyproject.toml` ni dans `src/m3_estimation/` (`grep` vide). OR-Tools est
un solveur de tournées (VRP), pertinent pour **M4**, pas pour M3 (confirmé par R7 §1, qui le classe
dans les briques M4). Cette phrase du document de référence est donc **obsolète** et devrait être
mise à jour plutôt que guider un choix de brique pour M3 (voir Risques, point 5).

## 4. Plan par phases

### Phase 1 — tranche verticale « lead prêt → estimation honnête → soumission brouillon →
### approbation », avec besoins matériaux vers M6 (petites tâches testables)

1. **Écrire l'orchestrateur `estimation.py`** (nommé par `docs/bmad/03-ARCHITECTURE.md` §1, absent du
   dépôt) : `valider_entrees` → `qualifier_photos` → `classifier_niveau_confiance` →
   `decider_blocage` → `simuler_intervalle` → `confronter_au_plancher` →
   `assembler_estimation` → `Registre.ajouter`. Réutilise les 15 modules existants tels quels,
   aucune nouvelle règle métier. Test : un appel nominal retourne un `EstimationV1` complet avec
   `devis_id` stable et `hash_maillon` non vide.
2. **Faire de `m3_estimer_projet` un simple appelant de cet orchestrateur**, en retirant la forme ad
   hoc actuelle (`intervalle`, absence de `devis_id`). Test de non-régression : les 9 tests actuels
   de `test_outils_agent.py` sont adaptés à la forme réelle du contrat, jamais affaiblis.
3. **Calculer et émettre `REFERENCE_ECHELLE_ABSENTE`** comme alerte non bloquante : dans
   l'orchestrateur, quand `niveau_confiance ∈ {MULTI_VUES, MONO_VUE_BORNES_LARGES}` et
   `motifs["photos_avec_reference"] == 0`, passer ce verdict à `devis.assembler_estimation` en plus
   du verdict de plancher/blocage (l'assembleur sait déjà arbitrer par `_PRIORITE_VERDICTS`). Test :
   3 photos multi-vues sans référence → `verdict_estimation == REFERENCE_ECHELLE_ABSENTE`,
   `prix_bloque is False`. Referme le point connu du mandat.
4. **Câbler `signaux.construire_signal_relance`** dans l'orchestrateur quand `prix_bloque is True` :
   un signal réel part vers M2 au lieu d'un module orphelin. Test : blocage photos faibles → un
   `SignalRelanceM2` est retourné, `emission_count == 1`.
5. **Ajouter le contrat de sortie `BesoinsMateriauxM3`** (`items`, `quantite_estimee`, `unite`,
   `facteur_perte`, `confiance`) à `contrats.py`, émis par l'orchestrateur uniquement quand
   `prix_bloque is False`. Fail-closed sur quantité négative ou item vide. Test unitaire côté M3
   seulement (la réception côté M6 est hors périmètre de cet audit, mais la forme doit être stable
   pour que M6 puisse la consommer sans deviner).
6. **Clarifier coût vs prix** : ajouter `taux_marge` comme entrée fournie par l'appelant (jamais codée
   en dur, même discipline que `plancher_rentable`) et un champ `prix_recommande` dérivé, distinct du
   coût. Sans taux fourni, bloquer plutôt qu'inventer une marge (cohérent avec CA-M3-21). Referme
   l'écart §2.1.
7. **Générer la soumission brouillon** via un nouvel outil `m3_generer_soumission_brouillon` (T1,
   WeasyPrint, gabarit alimenté uniquement par `EstimationV1` déjà validé, aucun champ libre). Test :
   un PDF non vide est produit à partir d'un contrat figé ; un contrat invalide est refusé sans PDF.
8. **Reclasser l'autonomie des outils** : `m3_estimer_projet` → `Autonomie.T1` (écrit désormais au
   registre) ; documenter (sans l'implémenter, gate volontaire) un outil futur
   `m3_envoyer_devis_client` en `T2`, absent tant que l'engagement externe n'est pas explicitement
   demandé — cohérent avec SOUL.md.
9. **Un test E2E socle** (`tests/test_e2e_m2_m3.py` ou équivalent) qui construit un `LeadQualifie` et
   un marqueur conformes à ce que M2 émet réellement (déjà garanti par les gates de cohérence
   existantes), appelle l'orchestrateur, et vérifie `devis_id` + `BesoinsMateriauxM3`. Referme une
   partie de l'écart §2.8.
10. **Écrire la politique Loi 25 « Photos non contractuelles »**, déjà identifiée comme backlog dans
    `docs/compliance/politiques/README.md`, **avant** toute collecte réelle de photos client en
    production (voir Risques, point 2).

Chaque tâche est indépendamment testable et n'exige aucune nouvelle dépendance externe : la Phase 1
est un exercice de câblage et de complétion de contrat, pas de nouvelle recherche.

### Phase 2 — briques externes (GATED, après la Phase 1 verte)

OpenCV (contrôle qualité réel) en premier (effort S, zéro sidecar) ; puis SAM2 + Grounding DINO ou
Florence-2/OWLv2 (mesure par pixel, sidecar GPU/CPU) ; Photon en sidecar pour M3.7 ; dashboard/écran
mobile dédiés une fois l'orchestrateur et le contrat stabilisés en Phase 1 (construire un écran sur
un contrat encore mouvant serait du travail jeté).

## 5. Risques et points ouverts

1. **Précision inventée par construction actuelle, pas par accident — mais fragile.** La garde
   anti-précision-inventée (blocage sur photos faibles/indéterminé, bornes toujours dans le barème)
   est réelle et bien testée. Le risque n'est pas dans ce qui existe, mais dans la confusion
   coût/prix (§2.1) : présenter aujourd'hui `intervalle`/`intervalle_confiance` comme un **prix**
   alors que le barème ne documente qu'un **coût** serait, si non corrigé avant mise en production,
   exactement la précision inventée que P2 interdit — un chiffre juste sur le coût mais faux sur ce
   qu'il représente commercialement.
2. **Photos clients et Loi 25.** M3 collecte des métadonnées de photos de propriétés clientes
   (résolution, éclairage, angle — pas les images elles-mêmes en v1, confirmé PRD §8 « minimisation »).
   Mais la politique dédiée existe seulement en **backlog déclaré**
   (`docs/compliance/politiques/README.md` : « Photos non contractuelles — à rédiger avant
   l'activation des fonctions concernées »). Tant qu'elle n'est pas écrite et validée par Nathan
   (T3), toute collecte réelle de photos en production expose l'entreprise sans cadre documenté —
   à traiter avant la Phase 1, tâche 10 ci-dessus, pas après.
3. **GPU.** Aucune infrastructure GPU/sidecar n'existe dans `deploy/` aujourd'hui (§2.7). SAM2/Depth
   Anything V2 *small* sont praticables CPU (2-5 s/photo, R7), mais un volume de production réel
   (plusieurs estimations/jour, plusieurs photos chacune) n'a pas été mesuré à cette échelle ; à
   chiffrer avant d'annoncer un SLA de délai de réponse à l'estimateur.
4. **Deux verdicts métier orphelins, documentés par le code lui-même** (`verdicts.py`) mais **non
   gardés par CI** : rien dans `conformite.py` ni dans les gates de cohérence n'empêche un troisième
   verdict de devenir orphelin à la prochaine story. Une garde de couverture (« chaque valeur de
   `VERDICTS_ESTIMATION` a au moins un site de production atteint par un test ») serait peu coûteuse
   et fermerait la classe de défaut, pas seulement l'instance actuelle.
5. **`docs/produit/DEFINITION-PRODUIT.md` §7-M3/§11 est mesurablement périmé sur l'état du code** :
   « ~1 294 lignes », « OR-Tools, SymPy et Monte Carlo partiellement présents » ne correspondent à
   rien dans le dépôt actuel (3 122 lignes, zéro OR-Tools/SymPy, Monte Carlo complet et testé). Le
   document dit lui-même que les états de sa section 11 datent de juin 2026 et doivent être
   revérifiés (règle P6) — cet audit constitue cette revérification pour M3 ; une mise à jour du
   document de référence serait cohérente avec sa propre règle 4 (« rien ici ne dit qu'un département
   est terminé »), mais reste hors périmètre de modification de ce mandat.
6. **M6, destinataire du flux matériaux, n'a pas non plus de contrat d'entrée pour le recevoir**
   (§2.3) — corriger M3 seul (Phase 1, tâche 5) ne suffira pas à fermer le flux §6 tant que M6 n'a
   pas son propre contrat miroir ; à coordonner avec un audit M6 dédié, hors périmètre ici.
7. **Portée de cet audit.** Seule la commande `pytest` sur `departments/m03-estimation/tests` a été
   exécutée. Les constats sur M6 (`contrats.py`, `frontieres.py`) et sur l'app mobile OpenClaw
   viennent d'une lecture directe de fichiers, pas d'une exécution de leurs suites — à confirmer par
   un audit dédié à M6 avant toute dépendance forte sur ses contrats actuels.
8. **Fragilité opérationnelle de l'outillage de preuve par mutation.** Les scripts
   `tests/outils_preuve/muter_*.py` écrivent chaque mutation **directement dans la source réelle**
   (`src/m3_estimation/*.py`) et ne la restaurent que dans un bloc `finally`, qui **ne s'exécute pas
   si le processus est tué** (par ex. un délai d'outil trop court — la suite complète prend
   ≈ 6 min 30, dominées par ces sous-processus). Une exécution interrompue peut donc laisser une
   mutation de logique métier silencieusement présente dans l'arbre de travail. Constaté pendant cet
   audit : une exécution tuée par un délai a laissé une mutation dans `blocage_prix.py`, restaurée
   par le coordinateur depuis le commit avant la fin de ce mandat ; `git status --porcelain
   departments/m03-estimation/src` est **vide** au moment de la remise de cet audit (arbre propre,
   vérifié, non modifié par cet agent). Recommandation : soit augmenter le délai de tout appelant à
   ≥ 900 000 ms pour cette suite, soit faire écrire les mutants dans une copie temporaire du paquet
   plutôt que dans la source réelle (cohérent avec la discipline « aucune exclusion, aucun leurre »
   déjà revendiquée par `tests/outils_preuve/README.md`).

---

PREUVE:
- Commande exécutée (mandat de l'audit) :
  `/opt/opsys-venv/bin/python -m pytest departments/m03-estimation/tests -q --import-mode=importlib
  -p no:cacheprovider`
  → exit code `0` ; sortie `577` caractères `.` sur 9 lignes de barre de progression = **577 tests
  collectés, 577 réussis, 0 échec, 0 erreur** (15 fichiers/3 122 lignes de `src/m3_estimation`,
  22 fichiers/9 401 lignes de `tests/`, 13 fichiers/3 074 lignes de `tests/outils_preuve/`).
- Lecture directe (pas d'exécution) : `docs/produit/DEFINITION-PRODUIT.md` (§0, §1, §5, §6, §7-M1,
  §7-M3, §8, §9, §10, §11, §13, §15), `AGENTS.md`, `docs/architecture/{ARCHITECTURE,DEPARTEMENTS,
  MOBILE}.md`, `core/UPSTREAM.md`, `pyproject.toml`, tous les fichiers de
  `departments/m03-estimation/{department.yaml,SOUL.md,README.md,docs/bmad/*,
  skills/estimer-un-projet/SKILL.md,src/m3_estimation/*.py,tests/*.py,tests/outils_preuve/*.py}`,
  `docs/research/{R7-m3-m4,INGREDIENTS,00-BRIEF}.md`, `src/opsys/{outils.py,approbations.py,
  console/application.py}`, `departments/m06-material-control/src/m6_material_control/
  {contrats.py,frontieres.py}` (frontière M3→M6 seulement, lecture seule), `docs/compliance/
  politiques/README.md`.
- Vérification de licences en ligne (aujourd'hui, recherche web, sources primaires) : Nominatim —
  code GPL-2.0/GPL-3.0, données ODbL (wiki OpenStreetMap, nominatim.org) ; Photon (komoot) —
  Apache-2.0, backend migré vers OpenSearch (dépôt GitHub `komoot/photon`) ; Adresses Québec/MRNF —
  licence gouvernementale ouverte, **diffusion se terminant en décembre 2026**, migration vers le
  Référentiel québécois du transport terrestre (mrnf.gouv.qc.ca, donneesquebec.ca) ; Florence-2
  (Microsoft) — MIT (fichier `LICENSE`, huggingface.co/microsoft/Florence-2-large) ; OWLv2 (Google) —
  Apache-2.0 (huggingface.co/docs/transformers/model_doc/owlv2). Briques vision/Monte
  Carlo/PDF/M4 reprises de `docs/research/R7-m3-m4.md` (déjà vérifiées à la source le 2026-09-28),
  non re-vérifiées indépendamment ici.
- Vérification post-suite : `git status --porcelain departments/m03-estimation/src` → sortie vide
  (arbre de travail propre, aucune mutation résiduelle au moment de la remise).
- Aucun autre fichier que `docs/departements/M3-audit.md` n'a été modifié.
