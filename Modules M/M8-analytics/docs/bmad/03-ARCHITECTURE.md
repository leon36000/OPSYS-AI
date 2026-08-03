# ARCHITECTURE — MODULE M8 (ANALYTICS)

## 0. CONSENSUS RATIFIÉ

Décision de fondation prise AVANT ce document, par consultation de l'agent `architecte` (Claude
Opus, subagent natif) sur la question : DuckDB/Parquet réels dès v1, ou stdlib-only avec DuckDB
en story GATED tracée ? Citations vérifiées avant adoption (pas prises pour argent comptant) :

- `Modules M/M7-marketing/src/roi/roi_engine.py:155-166` — `snapshot_id` calculé par
  `hashlib.sha256(json.dumps(rapport_sans_id, sort_keys=True, ensure_ascii=False))`, stdlib pur,
  déjà mesuré et fonctionnel.
- `docs/decisions/ADR-0003-RATIFICATION.md`, Q4 — « DuckDB+PyMC (déjà D-012/D-029) » classé parmi
  les enrichissements NON bloquants, « Aucune approbation conditionnée à un ajout ».
- `Modules M/M6-material-control/docs/bmad/03-ARCHITECTURE.md:245` — le patron « repoussé en
  roadmap, activable sans réécriture grâce au registre append-only » déjà appliqué au seuil de
  bruit XmR (ici : le filtrage statistique lui-même).

**Décision retenue : v1 stdlib-only, DuckDB/Parquet = story GATED explicite et nommée** (jamais
une substitution silencieuse). Le contrat `metric_id`/`snapshot_id`/schéma de ligne est gelé
comme SEULE interface entre la couche de stockage (JSON/JSONL v1, Parquet plus tard) et la couche
sémantique — pour que la story GATED soit un remplacement de moteur, pas une réécriture des
fonctions de dérivation. Risque assumé et journalisé : une structure `list[dict]` en mémoire peut
encoder des hypothèses (scan complet, forme des clés) qui ne survivent pas telles quelles au
passage à un moteur colonnaire — mitigé en gelant le contrat de ligne dès maintenant et en exigeant
que la story GATED rejoue les MÊMES tests sémantiques contre le nouveau moteur pour prouver
l'équivalence, plutôt que d'inventer de nouveaux tests qui masqueraient une régression.

## 1. PAQUET `m8_analytics` — MODULES INTERNES

Le paquet est autonome. Comme M2/M3/M4/M6, il réutilise des patrons prouvés par
**copie-adaptation**, jamais par import inter-modules (#109) — avec une garde PLUS STRICTE que ses
prédécesseurs : M8 n'importe **aucun** paquet `mX_*` de domaine, même en lecture (§DA-M8-01) — il
ne connaît structurellement aucun module source, seulement le format générique `SnapshotModule`
que l'appelant lui fournit.

| Fichier | Rôle | Story |
|---|---|---|
| `__init__.py` | Identité de paquet — docstring seule, aucune logique (patron #109). | — |
| `contrats.py` | Constantes gelées : champs attendus, `TYPE_SIGNAL_XMR`, échappatoire D-032. | S001 |
| `dictionnaire.py` | Compile `Modules M/<nom>/metrics/*.yaml` existants vers un dictionnaire canonique indexé par `metric_id`. Silence sur un module sans fichier — jamais une métrique fabriquée. | S001 |
| `validation.py` | Valide la structure d'un `SnapshotModule` contre le dictionnaire compilé : `module_source` connu, chaque `metric_id` déclaré par ce module. | S001 |
| `encodage.py` | Copie-adaptation de `m6_material_control/encodage.py` (lui-même adapté de `m4_field_ops`) : `encoder_canonique(*valeurs)`, `empreinte(*valeurs)`. | S002 |
| `registre.py` | `RegistreSnapshots` append-only hash-chaîné des `MaillonSnapshot` validés. Copie-adaptation du patron M4/M6. | S002 |
| `semantique.py` | Fonctions de dérivation PURES indexées par `metric_id`, renvoient `ValeurMetrique` (valeur + provenance complète), `null` fail-closed si `n` insuffisant. | S003 |
| `xmr.py` | Détection de signaux XmR : limites naturelles calculées à partir d'un historique de `ValeurMetrique`, jamais un seuil codé en dur. | S004 |
| `rapports.py` | Assemble `RapportAnalytique` à partir de métriques + signaux, filtre par rôle (liste blanche fournie par l'appelant), calcule `snapshot_id` du rapport. | S005 |
| `conformite.py` | Contrôle statique AST transversal : copie-adaptation de `m6_material_control/conformite.py`, + garde structurelle « aucun import `mX_*` ». | S006 |
| `digest.py` | `DigestAnalyticsQuotidien` — signaux actifs seulement, déterministe. | S006 |

Aucun fichier `materiel.py`-équivalent (orchestrateur unique) : contrairement à M6 (trois types de
mouvement, un point d'écriture chacun), M8 n'a qu'UN SEUL type d'écriture (l'ingestion d'un
snapshot validé). La discipline « point d'écriture unique » est déjà satisfaite par construction
— `registre.py::ajouter` est le seul point d'écriture du paquet, sans qu'un orchestrateur
supplémentaire soit nécessaire pour l'imposer. Ne PAS ajouter cette couche : elle n'apporterait
aucune garantie que la structure du paquet n'offre déjà.

## 2. SCHÉMAS DE DONNÉES

### 2.1 Entrée — `DefinitionMetrique` (mesurée dans `m7-metrics.v1.yaml`, pas supposée)

```yaml
DefinitionMetrique:
  id: str
  nom: str
  definition: str
  unite: str
  source_donnees: str
  frequence: str
  consommateur: str
```
Toutes les valeurs sont des chaînes (mesuré : `M7-marketing/tests/test_metrics_knowledge.py::test_metrics_no_calculated_numbers`).

### 2.2 Entrée — `SnapshotModule` (fourni par l'appelant)

```yaml
SnapshotModule:
  module_source: str
  horodatage: str
  valeurs:
    <metric_id>: str
```

### 2.3 Maillon du registre append-only — `MaillonSnapshot`

```yaml
MaillonSnapshot:
  index: int
  module_source: str
  horodatage: str
  valeurs: dict
  hash_precedent: str    # chaîne vide à l'index 0 — convention PROPRE à M8 (voir DA-M8-05)
  hash_maillon: str
```

### 2.4 Sortie — `ValeurMetrique`

```yaml
ValeurMetrique:
  metric_id: str
  valeur: float | null
  version_definition: str
  fraicheur: float | null   # null SSI valeur est null (S003) : aucun snapshot dont dériver un âge
  n: int
```

### 2.5 Sortie — `SignalXmR`

```yaml
SignalXmR:
  metric_id: str
  type_signal: str        # enum TypeSignalXmR
  valeur_observee: float | null
  limite_naturelle_haute: float | null
  limite_naturelle_basse: float | null
  n: int
```

### 2.6 Sortie — `RapportAnalytique`

```yaml
RapportAnalytique:
  type: str                # toujours "RAPPORT_ANALYTIQUE"
  role: str | null
  metriques: list[ValeurMetrique]
  signaux: list[SignalXmR]
  snapshot_id: str
```

### 2.7 Sortie — `DigestAnalyticsQuotidien`

```yaml
DigestAnalyticsQuotidien:
  type: str                # toujours "DIGEST_ANALYTICS"
  nb_signaux_actifs: int
  signaux_actifs: list[SignalXmR]
  hash_digest: str
```

### 2.8 Énuméré fermé (copie mot pour mot du PRD §4)

#### `TypeSignalXmR`

| Valeur | Condition d'obtention |
|---|---|
| `HORS_LIMITE_SUPERIEURE` | Point strictement au-dessus de la limite naturelle supérieure. |
| `HORS_LIMITE_INFERIEURE` | Point strictement au-dessous de la limite naturelle inférieure. |
| `DONNEES_INSUFFISANTES` | **Échappatoire D-032**, nom domaine-spécifique (patron `TYPES_TRAVAUX`/`"autre"` de M3, `_DEROGATIONS_ECHAPPATOIRE` dans `conformite.py`) — moins de `n` minimal fourni par l'appelant. |

## 3. INTERFACES ET CONTRATS

### 3.1 Ce que M8 reçoit de l'appelant (jamais d'un module de domaine directement)

`SnapshotModule` à chaque ingestion ; `n_minimal`/fenêtre d'historique à chaque détection XmR ;
`horodatage_reference` à chaque calcul de fraîcheur ; `metric_ids_autorises` par rôle à chaque
rapport filtré.

### 3.2 Ce que M8 émet vers les dashboards

`RapportAnalytique`, filtré ou non selon le rôle demandé.

### 3.3 Ce que M8 émet vers Nathan (distribué par M1, hors périmètre M8)

`DigestAnalyticsQuotidien` quotidien, déterministe.

### 3.4 Ce que M8 émet vers M9 (futur, hors périmètre v1)

Aucun contrat gelé v1 — M9 consommera la couche sémantique quand il sera construit (position
tardive dans l'ordre ratifié).

### 3.5 État interne faisant autorité

Le registre append-only de `MaillonSnapshot` est la source de vérité unique des snapshots reçus.
Toute valeur de métrique est une **dérivation pure** de ce registre, jamais un compteur maintenu
à part (même discipline que DA-M6-09).

## 4. DÉCISIONS D'ARCHITECTURE TRANCHÉES

### DA-M8-01 — Aucun import de paquet de domaine, même en lecture

**Décision** : `m8_analytics` n'importe JAMAIS `m1_front_office`, `m2_revenue_crm`,
`m3_estimation`, `m4_field_ops`, `m6_material_control`, `m7_marketing`, ni aucun futur `m5_*`/
`m9_*`/`m10_*`. Garde AST dédiée dans `conformite.py` (recherche de `import mX_` ou
`from . mX_ import` — en pratique, `from m\d+_\w+`).

**Justification** : #109 protège le code de PRODUCTION du couplage inter-modules ; M8 va plus
loin que ses prédécesseurs (qui ne s'importent pas entre PAIRS mais consomment parfois des
contrats mesurés d'un voisin précis, ex. M6 lisant le `WctRecu` de M4) — M8 ne consomme QUE des
snapshots génériques fournis par l'appelant, jamais une structure de module connue à l'avance.
C'est la frontière la plus stricte du dépôt, cohérente avec « M8 ne possède aucune donnée
source ».

### DA-M8-02 — Le LLM ne calcule jamais un chiffre (règle d'or de la fiche source)

**Décision** : toute valeur numérique visible (`ValeurMetrique.valeur`, `SignalXmR.*`) provient
d'une fonction pure de `semantique.py`/`xmr.py`, jamais d'un texte généré. Aucune fonction du
paquet n'appelle de passerelle LLM (garde AST : aucun appel réseau, §DA-M8-04, en est une
conséquence directe — sans réseau, aucun appel LLM n'est possible).

**Justification** : risque nommé explicitement dans la fiche source. Un LLM qui « calcule » un
total en le décrivant se trompe silencieusement — invérifiable sans revenir à la source. Le
narrateur (hors périmètre M8 : une couche de présentation ultérieure) doit CITER
`metric_id`+version+fraîcheur+`n`, jamais recalculer.

### DA-M8-03 — Fail-closed sur les données insuffisantes, jamais une valeur substituée

**Décision** : une dérivation sans échantillon suffisant renvoie `valeur: null`, `n` réel affiché
— jamais zéro, jamais une moyenne devinée, jamais une extrapolation. Même logique pour XmR :
`DONNEES_INSUFFISANTES` plutôt qu'un signal fabriqué sur trop peu de points.

**Justification** : une valeur fabriquée en cas de doute serait indiscernable d'une vraie mesure
en aval (dashboard, digest, futur M9) — parallèle direct avec D-032 et avec le FALLBACK de M6
(`INDETERMINE` plutôt qu'un prix à zéro).

### DA-M8-04 — Déterminisme total (zéro horloge, zéro aléa non ensemencé, zéro réseau)

**Décision** : aucun module de M8 n'appelle `time.time`, `datetime.now`/`today`/`utcnow`,
`random` sans graine, `uuid`, `secrets`, `os.urandom`, ni aucune primitive réseau. Tout horodatage
(snapshot, référence de fraîcheur) provient de l'appelant, reproduit tel quel.

**Justification** : reproductibilité bit-à-bit du `snapshot_id` exigée (CA-M8-05). Garde par
`conformite.py`, copie-adaptation directe de celui de M6 (lui-même copie-adaptation de M3).

### DA-M8-05 — Convention `hash_precedent` propre à M8 : chaîne vide à l'index 0

**Décision** : `HASH_PREDECESSEUR_INITIAL = ""` (chaîne vide), PAS 64 zéros (M2/M3) ni `None`
(M4). Choix délibéré, pas une copie aveugle du voisin le plus récent (M6) : la chaîne vide est le
sentinel le plus simple à comparer et à sérialiser (pas de longueur à retenir comme pour 64
zéros, pas de branchement de type comme pour `None` dans une fonction qui attend par ailleurs des
chaînes).

**Justification** : cohérence interne du paquet (toutes les valeurs de `hash_precedent`/
`hash_maillon` sont des chaînes, sans exception à l'index 0) ; le choix est documenté ici pour
qu'une revue ne le prenne pas pour un oubli de recopie.

### DA-M8-06 — Snapshot validé AVANT écriture, aucune écriture partielle

**Décision** : `validation.py` vérifie la structure ENTIÈRE d'un `SnapshotModule` (module connu,
tous les `metric_id` déclarés) AVANT tout appel à `registre.ajouter`. Un snapshot invalide ne
produit AUCUNE écriture, jamais un maillon partiel.

**Justification** : « valider toutes les clés avant la première écriture, sinon fichier à moitié
corrigé et vert » — leçon `applicateur-refuse-en-bloc` déjà appliquée à l'atomicité multi-lignes
de M6 (DA-M6-08), transposée ici à un snapshot unique (M8 n'a pas de notion de lot multi-lignes
en v1 : un snapshot = un maillon).

### DA-M8-07 — Aucune cause ni accusation dans un signal XmR (R-020 transposé)

**Décision** : `SignalXmR` ne porte aucun champ de cause, de responsable, ni de conclusion. Un
signal est un CONSTAT statistique (point hors limites naturelles), jamais une désignation.
Garde AST dans `conformite.py` : aucune clé `cause`/`responsable`/`raison_signalee` dans les
dict-littéraux du paquet.

**Justification** : R-020 (« jamais vol automatique » chez M6, § DA-M6-07) transposé aux séries
temporelles — un signal XmR (ex. un coût par lead qui grimpe) n'implique JAMAIS une faute humaine
identifiée ; c'est une variation statistique à investiguer, pas un verdict de blâme.

### DA-M8-08 — Digest quotidien : signaux ACTIFS seulement, jamais le bruit

**Décision** : `DigestAnalyticsQuotidien.signaux_actifs` exclut explicitement tout `SignalXmR` de
type `DONNEES_INSUFFISANTES` — seuls `HORS_LIMITE_SUPERIEURE`/`HORS_LIMITE_INFERIEURE` y figurent.

**Justification** : contrairement à M6 (où « aucun seuil de bruit » signifie que TOUTES les
variances remontent), un signal `DONNEES_INSUFFISANTES` n'est PAS une anomalie à remonter à
Nathan — c'est un état neutre d'insuffisance de données, sa présence dans un digest quotidien
noierait le signal réel sous du bruit administratif. Différence assumée et documentée pour
qu'une revue ne la prenne pas pour une omission par rapport au patron M6.

## 5. CE QUE CHAQUE STORY PROUVE

| Story | Ce qu'elle prouve | Critères | Tier |
|---|---|---|---|
| **S001** — Contrats gelés, validation, dictionnaire de métriques | Compilation du dictionnaire depuis les `metrics/*.yaml` présents (M7 seul) ; rejet nommé d'un module/`metric_id` inconnu ; silence sur un module sans fichier. | CA-M8-01, 02, 03, 04 | T2 |
| **S002** — Registre append-only hash-chaîné des snapshots | Chaîne préservée à l'ajout, altération détectée ; `snapshot_id` déterministe. | CA-M8-05, 06 | T1 |
| **S003** — Couche sémantique | Provenance complète sur toute valeur ; `null` fail-closed si `n` insuffisant. | CA-M8-07, 08 | T1 |
| **S004** — Détection XmR | Limites naturelles calculées, jamais un seuil codé en dur ; `DONNEES_INSUFFISANTES` sous `n` minimal fourni. | CA-M8-09, 10 | T1 |
| **S005** — Rapports filtrés par rôle | Aucune métrique hors liste autorisée dans un rapport filtré. | CA-M8-11 | T2 |
| **S006** — Conformité statique et digest quotidien | Échappatoire D-032 sur `TypeSignalXmR` ; 4 familles d'appels interdits + garde anti-import de domaine ; digest déterministe, signaux actifs seulement. | CA-M8-12, 13, 14, 15 | T1 |

## 6. PARAMÈTRES CONFIGURABLES

| Paramètre | Description | Valeur par défaut |
|---|---|---|
| `n_minimal_xmr` | Taille d'échantillon minimale avant `DONNEES_INSUFFISANTES`. | **Fourni par l'appelant. Aucun défaut.** |
| `horodatage_reference` | Instant de référence pour la fraîcheur. | **Fourni par l'appelant — aucune horloge interne.** |
| `metric_ids_autorises` (par rôle) | Liste blanche de métriques visibles par rôle. | **Fournie par l'appelant. Absence = vue complète non filtrée.** |

## 7. PÉRIMÈTRE V1 vs GATED/T3

### 7.1 En périmètre v1 (mode ombre, prouvable en CI Python)

| Élément | Fichier(s) responsable(s) |
|---|---|
| Dictionnaire de métriques, validation d'entrée | `dictionnaire.py`, `validation.py`, `contrats.py` |
| Registre append-only hash-chaîné, `snapshot_id` | `registre.py`, `encodage.py` |
| Dérivations pures, provenance complète | `semantique.py` |
| Détection XmR | `xmr.py` |
| Rapports filtrés par rôle | `rapports.py` |
| Digest quotidien déterministe | `digest.py` |
| Conformité statique (D-032, déterminisme, anti-import de domaine, anti-accusation) | `conformite.py` |

**Stack technique** : stdlib Python + PyYAML, zéro réseau, zéro horloge interne, zéro LLM.

### 7.2 Repoussé GATED/T3

| Élément | Raison du report |
|---|---|
| DuckDB + Parquet réels | Décision tracée §0 ; enrichissement non bloquant (ADR-0003 Q4) ; contrat `metric_id`/`snapshot_id` gelé pour migration sans réécriture des fonctions sémantiques |
| MMM (PyMC-Marketing) | Déjà classé GATED vague 4 par le plan M7 ; bibliothèque bayésienne hors stdlib |
| Compilation des métriques M1-M6 | Chaque module doit livrer son propre fichier (D-010) ; lacune signalée à Nathan, pas comblée silencieusement par M8 |
| Ordonnancement nightly réel | v1 = appel manuel prouvant le contrat |
| Moteur d'autorisation fine (OpenFGA) | Service transversal du core, hors périmètre M8 |

## 8. RISQUES MESURÉS DANS LE CODE LU (vigilance requise en implémentation et en revue)

1. Seul `Modules M/M7-marketing/metrics/m7-metrics.v1.yaml` existe réellement à ce jour ; M1-M6
   n'ont qu'un `.gitkeep`. Toute story M8 qui supposerait des métriques déclarées pour un autre
   module serait un contrat fantôme (parallèle #166/M6-risque-1). M8 doit rester silencieux, pas
   inventif, sur les modules sans fichier.
2. `duckdb` n'est PAS installé dans l'environnement de développement/CI actuel ; `pyarrow` est
   présent mais seulement comme dépendance transitive non garantie — aucune story v1 ne doit
   supposer leur disponibilité.
3. Le patron `snapshot_id` de `roi_engine.py` calcule le hash sur le dict SANS le champ
   `snapshot_id` lui-même (`calculer_snapshot_id` retire la clé avant de sérialiser) — la
   copie-adaptation de M8 doit reproduire cette exclusion, sinon le hash serait auto-référentiel
   et non reproductible par un tiers qui recalculerait à partir du rapport complet.
