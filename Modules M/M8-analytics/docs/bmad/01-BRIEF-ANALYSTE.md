# BRIEF ANALYSTE — MODULE M8 (ANALYTICS)

Septième module de l'ordre ratifié ADR-0003 (M7→M1→M2→M4→M3→M6→**M8**→M5→M9). Fiche source :
`GRS_Plan_Squelette_Maitre_v1.1_PERFECTION.pdf`, page 9 ; décision transversale D-010
(« Registre de métriques »), page 4.

## 1. BESOIN MÉTIER

Nathan a besoin d'une couche de vérité chiffrée, transversale à tous les modules, qui ne fabrique
jamais un chiffre et ne cache jamais son incertitude. Chaque module (M1-M7, M6 vient de livrer)
enregistre des faits dans son propre registre append-only ; personne aujourd'hui ne les additionne,
ne les compare dans le temps, ni ne les remonte en alerte de façon honnête. Le risque sans M8 :
soit aucun chiffre consolidé (angles morts), soit un LLM narrateur qui « calcule » un total à la
volée et se trompe silencieusement (le risque nommé explicitement par la fiche source : « le LLM
ne calcule JAMAIS un chiffre »).

M8 n'est PAS un outil de décision (ça, c'est M9, plus tard dans l'ordre) : c'est la couche qui
rend les chiffres des sept modules précédents interrogeables, comparables, et honnêtes sur leur
propre incertitude — avant qu'un cerveau stratégique (M9) ou un humain ne s'en serve.

## 2. CONTRAINTES NON NÉGOCIABLES

### 2.1 Lecture seule stricte — aucune donnée source, aucune écriture en amont

M8 ne possède aucune donnée. Il lit les registres/exports d'autres modules par snapshots
horodatés, jamais en les modifiant. Une fonction de M8 qui appellerait `.ajouter()`/`.ajouter_lot()`
sur un registre d'un AUTRE module serait un défaut architectural majeur — M8 n'a même pas besoin
d'importer les modules de domaine d'autres modules pour cette raison (il consomme des fichiers,
pas du code).

### 2.2 Le LLM ne calcule JAMAIS un chiffre

Toute valeur numérique dans un rapport M8 provient d'une fonction pure de la couche sémantique,
jamais d'un texte généré. Un rapport ne fait que CITER une valeur déjà calculée, avec sa
provenance : `metric_id`, version de la définition, fraîcheur (âge du snapshot), et `n`
(taille de l'échantillon sous-jacent). Mesuré et déjà mécanisé dans le dépôt : `m7-metrics.v1.yaml`
(chaque métrique n'est QUE des chaînes de texte descriptives — jamais une valeur numérique) et
`test_metrics_knowledge.py::test_metrics_no_calculated_numbers`, qui vérifie mécaniquement
qu'aucune valeur du dictionnaire n'est un nombre.

### 2.3 Alertes = signaux XmR, jamais un seuil arbitraire ni une conclusion accusatoire

Une alerte n'est émise que lorsqu'un point sort des limites naturelles calculées à partir de
l'historique de la métrique elle-même (process behavior chart / XmR : moyenne mobile des écarts
successifs, limites à ±2.66×MR autour de la moyenne — méthode statistique standard, pas un seuil
choisi à la main). Sous un `n` minimal, le signal affiche explicitement « données insuffisantes »
plutôt qu'un faux positif ou un silence trompeur. Aucune alerte ne désigne une cause ni une
personne — parallèle direct avec R-020 (M6 : « une variance est un constat, jamais une
accusation »), appliqué ici aux séries temporelles.

### 2.4 Chaque rapport référence son `snapshot_id` — reproductibilité prouvée

« Mêmes maillons + mêmes arguments → mêmes octets » (le patron mesuré sur tous les digests
précédents M2/M3/M4/M6) s'applique ici au niveau du RAPPORT : deux appels sur le même ensemble de
snapshots produisent un rapport identique, `snapshot_id` inclus. Le mécanisme est déjà mesuré dans
le dépôt : `Modules M/M7-marketing/src/roi/roi_engine.py` calcule un `snapshot_id` par
`hashlib.sha256(json.dumps(rapport_sans_id, sort_keys=True, ensure_ascii=False))` — patron stdlib
pur, aucune dépendance externe.

### 2.5 Dictionnaire de métriques = metrics-as-code, jamais une métrique inventée par M8

D-010 (transversal, page 4 du plan) : chaque module DÉCLARE ses métriques dans son propre
`Modules M/<nom>/metrics/*.yaml` — M8 les COMPILE, il ne les invente jamais pour un module qui n'en
a pas déclaré. **Fait mesuré, pas supposé** : à ce jour, SEUL `M7-marketing` a un fichier réel
(`m7-metrics.v1.yaml`, 14 métriques). `M1, M2, M3, M4, M5, M6` n'ont qu'un `.gitkeep` dans leur
dossier `metrics/` — le principe « chaque module livre ses métriques à son build » n'a pas été
suivi lors des cadrages M3/M4/M6. **Ce n'est PAS à M8 de combler cette lacune** (cela reviendrait à
inventer un dictionnaire pour un module qui n'a rien déclaré, contraire à 2.5 elle-même) : M8 v1
compile ce qui EXISTE (M7 seul). Deux opérations distinctes, deux comportements distincts, à ne
pas confondre : **compiler** le dictionnaire ignore SILENCIEUSEMENT un module sans fichier
`metrics/*.yaml` (rien à rejeter — il n'y a simplement aucune entrée à produire pour lui,
CA-M8-02) ; **ingérer un snapshot** dont le `module_source` ne figure PAS dans le dictionnaire
compilé est, lui, un rejet NOMMÉ et explicite (il y a une entrée fournie par un appelant à
refuser, CA-M8-03) — la compilation ne s'exécute jamais deux fois pour « corriger » son silence.
Combler M1-M6 est un backlog distinct, signalé à Nathan séparément de ce cadrage.

### 2.6 Dashboards par rôle — l'employé ne voit jamais les marges

Même verrou que M6 (« l'employé terrain ne voit pas les coûts ») transposé aux chiffres agrégés :
un rapport destiné à un rôle terrain ne contient jamais de métrique de marge/coût. Mécanique par
autorisation (quel rapport EST construit pour quel rôle), jamais une convention de nommage
espérée.

### 2.7 v1 = mode ombre stdlib-only ; DuckDB/Parquet = décision tracée, jamais une substitution silencieuse

La fiche source mandate explicitement « snapshots Parquet → entrepôt DuckDB ». Décision
d'architecture prise AVANT ce brief (consultation `architecte`, citations vérifiées) : v1 prouve
les QUATRE COUCHES et le contrat `metric_id`/`snapshot_id` avec des types stdlib purs (JSON/JSONL
horodaté au lieu de Parquet, `list[dict]` en mémoire au lieu d'un entrepôt DuckDB, fonctions pures
au lieu de SQL) — cohérent avec le patron mesuré des six modules précédents et avec ADR-0003 Q4,
qui classe DuckDB comme un enrichissement NON bloquant (« Aucune approbation conditionnée à un
ajout »). DuckDB/Parquet réels deviennent une story GATED explicite, nommée comme telle — jamais
un JSON qui se fait passer pour un Parquet. Voir §6 et l'architecture pour le détail de la couture
de migration.

## 3. FRONTIÈRES DU MODULE

### 3.1 Ce que M8 fait

- Compile le dictionnaire de métriques canonique à partir des `metrics/*.yaml` réellement
  présents (v1 : M7 uniquement).
- Ingère des snapshots horodatés (v1 : construits par l'appelant à partir des registres/digests
  déjà exposés par les modules sources — M8 ne réimplémente pas leur logique de dérivation, il lit
  leur SORTIE déjà calculée).
- Dérive des valeurs de métriques par des fonctions pures indexées par `metric_id`, avec
  provenance complète (`metric_id`, version, fraîcheur, `n`).
- Détecte des signaux XmR sur l'historique d'une métrique.
- Produit des rapports déterministes, reproductibles, référençant leur `snapshot_id`.

### 3.2 Ce que M8 ne fait JAMAIS

- N'écrit jamais dans le registre d'un autre module.
- Ne calcule jamais un chiffre via un LLM — le LLM narre, ne calcule pas.
- N'invente jamais une métrique pour un module sans fichier `metrics/*.yaml` déclaré (échec
  nommé, jamais un chiffre fabriqué).
- Ne construit pas le MMM en v1 — la fiche source classe déjà le MMM en GATED vague 4 de M7
  (« MMM arrive avec M8 » signifie que M8 en devient le PROPRIÉTAIRE architectural, pas que la v1
  le construit ; PyMC-Marketing est hors périmètre stdlib de toute façon).
- Ne décide rien et ne recommande rien — M8 chiffre, M9 (plus tard) interprète et arbitre.
- Ne fixe aucun seuil d'alerte arbitraire — seulement des limites XmR calculées.

## 4. CONTRAT D'ENTRÉE — CE QUI EST MESURÉ, PAS SUPPOSÉ

- **Dictionnaire de métriques par module** : `Modules M/<nom>/metrics/*.yaml`, schéma mesuré dans
  `m7-metrics.v1.yaml` — 7 champs obligatoires par métrique, TOUS des chaînes de texte
  (`id, nom, definition, unite, source_donnees, frequence, consommateur`), `id` préfixé par le nom
  court du module. Validé par un test mécanique équivalent à
  `M7-marketing/tests/test_metrics_knowledge.py`.
- **Snapshot d'un module source** : en v1, un dict fourni par l'appelant (pas un accès direct au
  registre d'un autre module — M8 ne connaît structurellement aucun module de domaine). Contient
  au minimum : `module_source`, `horodatage`, et les valeurs mesurées pour les `metric_id` que ce
  module a déclarés. La forme exacte est un CONTRAT GELÉ à trancher en architecture (§5 esquisse
  seulement ici).
- **Patron de `snapshot_id` déjà mesuré** : `roi_engine.py::snapshot_id`/`calculer_snapshot_id`
  (sha256 du JSON canonique trié, sans le champ `snapshot_id` lui-même) — patron à réutiliser tel
  quel, pas à réinventer.

## 5. CONTRAT DE SORTIE — ESQUISSE (le PRD et l'architecture trancheront la forme gelée)

Un rapport M8 porte au minimum : la liste des valeurs de métriques citées (chacune avec
`metric_id`, valeur, version de définition, fraîcheur, `n`), la liste des signaux XmR actifs
(chacun avec le `metric_id` concerné, sans cause attribuée), et un `snapshot_id` couvrant
l'ensemble des snapshots ayant servi au calcul. Un dashboard par rôle est une VUE filtrée de ce
même contrat, jamais une source de données parallèle.

## 6. MODE OMBRE ET MODE GATED

### 6.1 En périmètre v1 (mode ombre, prouvable en CI Python, stdlib + PyYAML)

- Compilateur du dictionnaire de métriques (lecture des `metrics/*.yaml` existants, v1 : M7 seul).
- Ingestion de snapshots horodatés (JSON/JSONL, PAS Parquet), `snapshot_id` déterministe (patron
  `roi_engine.py`).
- Couche sémantique : dérivations pures indexées par `metric_id`.
- Détection XmR sur une série de valeurs déjà dérivées.
- Rapports déterministes avec provenance complète.

### 6.2 Repoussé GATED/T3

- **DuckDB + Parquet réels** : story GATED explicite et nommée (décision tracée §2.7), remplace le
  conteneur JSON/JSONL et la couche `list[dict]` par un vrai entrepôt colonnaire — sans changer le
  contrat `metric_id`/`snapshot_id` ni réécrire les fonctions sémantiques (contrat de migration à
  fixer en architecture).
- **MMM (Marketing Mix Model, PyMC-Marketing)** : GATED, déjà classé vague 4 par le plan M7 ;
  dépend d'une bibliothèque de modélisation bayésienne, hors stdlib.
- **Compilation des métriques pour M1-M6** : hors périmètre de CE cadrage (chaque module doit
  livrer son propre `metrics/*.yaml` — lacune signalée à Nathan séparément, pas comblée
  silencieusement par M8).
- **Dashboards temps réel / rafraîchissement horaire** : la fiche source dit elle-même « mode
  horaire quasi intégral (batch nightly) » — v1 ne construit pas d'ordonnanceur, un appel manuel
  suffit à prouver le contrat.

## 7. CE QUE L'ANALYSTE PROPOSE ET QUE LE PM TRANCHERA

### 7.1 Forme exacte du snapshot d'entrée

Un dict simple `{module_source, horodatage, valeurs: {metric_id: valeur}}` suffit-il, ou faut-il
porter une preuve d'origine (ex. hash de la source) dès v1 ? Proposition : dict simple v1, le hash
d'origine est une extension de roadmap (le `snapshot_id` du RAPPORT suffit à la reproductibilité
exigée par CA).

### 7.2 Fenêtre de fraîcheur avant « donnée périmée »

Combien de temps avant qu'une métrique soit signalée comme périmée dans un rapport ? Proposition :
pas de seuil dur en v1 — la fraîcheur est TOUJOURS affichée (âge réel), jamais binaire
fraîche/périmée ; un seuil de péremption est un paramètre de roadmap (même logique que le seuil de
bruit XmR différé, §7.3).

### 7.3 Paramètres XmR (n minimal, fenêtre historique)

Quel `n` minimal avant « données insuffisantes » ? Combien de points d'historique pour calculer
les limites naturelles ? Proposition : fournis par l'appelant à chaque appel (comme `seuils` chez
M6), jamais une constante interne devinée — cohérent avec « aucun coût codé en dur » appliqué ici
aux paramètres statistiques.

### 7.4 Granularité des rôles de dashboard

Un rôle fixe (`terrain`/`admin`) suffit-il en v1, ou faut-il un système de permissions plus fin
dès le départ ? Proposition : un rôle simple string en v1 avec une liste explicite de
`metric_id` autorisés par rôle, fournie par l'appelant — le moteur d'autorisation fine (OpenFGA,
service transversal D-010) est un service du CORE, pas une réinvention par M8.

### 7.5 Comment M8 obtient les snapshots des modules déjà livrés

M8 ne doit PAS importer `m1_front_office`, `m2_revenue_crm`, etc. (violation de #109 et de la
frontière lecture-seule). Qui construit le snapshot à partir du registre réel d'un module — un
script d'intégration hors du paquet M8, ou l'appelant du digest de chaque module ? Proposition :
hors périmètre de M8 lui-même (M8 reçoit un snapshot déjà construit ; la construction est un
service d'intégration distinct, pas une story M8).
