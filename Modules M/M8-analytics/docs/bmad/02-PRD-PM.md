# PRD — MODULE M8 (ANALYTICS)

## 0. TRANCHÉ SUR LES POINTS OUVERTS DE L'ANALYSTE

- **§7.1 (forme du snapshot d'entrée)** : dict simple `{module_source, horodatage, valeurs}` en
  v1. Le hash de provenance de la source n'est pas nécessaire : le `snapshot_id` du RAPPORT
  (calculé sur l'ensemble des snapshots + arguments) suffit à la reproductibilité exigée.
- **§7.2 (fraîcheur)** : jamais de seuil dur périmée/fraîche. La fraîcheur est un NOMBRE
  (âge en secondes ou en jours, dérivé de l'horodatage du snapshot vs un horodatage de référence
  fourni par l'appelant — M8 n'a pas d'horloge) toujours affiché, jamais binaire.
- **§7.3 (paramètres XmR)** : `n` minimal et fenêtre d'historique sont fournis par l'appelant à
  chaque appel de détection, jamais une constante interne. Aucune valeur par défaut : un défaut
  serait un seuil arbitraire inventé, contraire à la règle d'or de la fiche source.
- **§7.4 (rôles de dashboard)** : rôle = chaîne simple + liste explicite de `metric_id` autorisés,
  fournie par l'appelant. Le moteur d'autorisation fine réel (OpenFGA, D-010) reste un service du
  core, hors périmètre M8.
- **§7.5 (obtention des snapshots)** : hors périmètre de M8. M8 reçoit un snapshot déjà construit ;
  la construction à partir du registre réel d'un module source est un service d'intégration
  distinct (pas une story M8, pas un import inter-modules — cohérent avec #109).

## 1. PERSONAS

- **Nathan (dirigeant)** : reçoit un digest quotidien des métriques et des signaux XmR actifs,
  veut savoir CE QUI a changé sans qu'un LLM lui invente un chiffre.
- **Rôle admin/dirigeant (dashboard)** : voit toutes les métriques autorisées à son rôle, y
  compris les marges/coûts.
- **Rôle terrain (dashboard)** : voit un sous-ensemble filtré — jamais une métrique de coût/marge.
- **M9 (futur consommateur, hors périmètre v1)** : consommera la couche sémantique de M8 comme
  source de vérité chiffrée pour ses scénarios — M8 doit donc exposer un contrat stable, pas un
  format ad hoc.

## 2. PARCOURS PRINCIPAUX

### 2.1 Compilation du dictionnaire de métriques

Un opérateur (ou une tâche planifiée, hors périmètre v1) déclenche la compilation : M8 lit tous
les `Modules M/<nom>/metrics/*.yaml` présents, valide leur schéma (7 champs texte obligatoires par
métrique), et produit un dictionnaire canonique indexé par `metric_id`. Un module sans fichier
n'apparaît simplement pas au dictionnaire — silence, jamais une métrique fabriquée pour lui.

### 2.2 Ingestion d'un snapshot et calcul de son empreinte

Un appelant fournit un snapshot `{module_source, horodatage, valeurs}`. M8 valide que
`module_source` est un module CONNU du dictionnaire et que chaque clé de `valeurs` est un
`metric_id` DÉCLARÉ par ce module — un `metric_id` inconnu est un rejet nommé, jamais une entrée
silencieusement ignorée. Le snapshot validé est ajouté au registre append-only, avec un
`snapshot_id` déterministe.

### 2.3 Dérivation de métrique et provenance

Une fonction de la couche sémantique, indexée par `metric_id`, lit les snapshots pertinents du
registre et renvoie une valeur accompagnée de sa provenance complète (`metric_id`, version de la
définition, fraîcheur, `n`). Aucune fonction ne renvoie un nombre sans cette provenance.

### 2.4 Détection de signal XmR et rapport

Sur une série de valeurs déjà dérivées pour un `metric_id`, une fonction calcule les limites
naturelles (moyenne + amplitude mobile moyenne) et signale les points hors limites — jamais un
seuil deviné. Un rapport assemble les métriques citées et les signaux actifs, filtré par rôle si
demandé, et référence son `snapshot_id`.

## 3. PÉRIMÈTRE V1 vs ROADMAP

### 3.1 En périmètre v1 (mode ombre, prouvable en CI Python, stdlib + PyYAML)

| Élément | Statut |
|---|---|
| Compilateur du dictionnaire de métriques (`metrics/*.yaml`, M7 seul aujourd'hui) | v1 |
| Validation structurelle du snapshot d'entrée | v1 |
| `snapshot_id` déterministe (patron `roi_engine.py`) | v1 |
| Registre append-only hash-chaîné des snapshots | v1 |
| Couche sémantique (dérivations pures, provenance) | v1 |
| Détection XmR (limites naturelles, `n` minimal fourni) | v1 |
| Rapports déterministes filtrés par rôle | v1 |
| Conformité statique transversale (AST) + digest quotidien | v1 |

### 3.2 Repoussé GATED/T3

| Élément | Raison du report |
|---|---|
| DuckDB + Parquet réels | Décision tracée (brief §2.7, ADR-0003 Q4 : enrichissement non bloquant) ; story GATED nommée, contrat `metric_id`/`snapshot_id` gelé comme seule interface de migration |
| MMM (PyMC-Marketing) | Déjà classé GATED vague 4 par le plan M7 ; bibliothèque de modélisation bayésienne hors stdlib |
| Compilation des métriques M1-M6 | Chaque module doit livrer son propre fichier ; lacune signalée à Nathan séparément |
| Ordonnancement horaire/nightly réel | v1 = appel manuel prouvant le contrat ; l'ordonnanceur est une infra, pas une story de domaine |
| Moteur d'autorisation fine réel (OpenFGA) | Service transversal du core (D-010), hors périmètre M8 |

## 4. ÉNUMÉRÉS FERMÉS

### 4.1 `TypeSignalXmR`

| Valeur | Condition d'obtention |
|---|---|
| `HORS_LIMITE_SUPERIEURE` | Point strictement au-dessus de la limite naturelle supérieure. |
| `HORS_LIMITE_INFERIEURE` | Point strictement au-dessous de la limite naturelle inférieure. |
| `DONNEES_INSUFFISANTES` | **Échappatoire D-032** (nom domaine-spécifique, patron `TYPES_TRAVAUX`/`"autre"` de M3 : ici la donnée insuffisante EST l'indétermination elle-même) — moins de `n` minimal de points d'historique pour calculer des limites naturelles fiables. |

Un point DANS les limites naturelles n'émet simplement AUCUN signal (silence, comme le reorder de
M6 : pas de quatrième valeur « stable »).

## 5. CONTRATS GELÉS

### 5.1 Entrée — `DefinitionMetrique` (mesurée dans `m7-metrics.v1.yaml`, pas supposée)

```yaml
DefinitionMetrique:
  id: str              # préfixé par le nom court du module, ex. "m7_cpl"
  nom: str
  definition: str
  unite: str
  source_donnees: str
  frequence: str
  consommateur: str    # "entrepôt M8" mesuré, mais le champ reste un texte libre du module
```
Toutes les valeurs sont des CHAÎNES — jamais un nombre (mesuré : `test_metrics_no_calculated_numbers`).

### 5.2 Entrée — `SnapshotModule` (fourni par l'appelant à chaque ingestion)

```yaml
SnapshotModule:
  module_source: str      # doit correspondre à un module du dictionnaire compilé
  horodatage: str         # fourni par l'appelant, reproduit tel quel, jamais généré par M8
  valeurs:
    <metric_id>: str      # valeur brute mesurée par le module source, TEXTE (voir DA-M8, la
                           # conversion numérique n'a lieu QUE dans la couche sémantique, jamais
                           # avant — un snapshot est un fait rapporté, pas encore un calcul)
```

### 5.3 Maillon du registre append-only — `MaillonSnapshot`

```yaml
MaillonSnapshot:
  index: int
  module_source: str
  horodatage: str
  valeurs: dict            # copie du snapshot validé
  hash_precedent: str       # convention PROPRE à M8, tranchée en architecture
  hash_maillon: str
```

### 5.4 Sortie — `ValeurMetrique` (unité de la couche sémantique)

```yaml
ValeurMetrique:
  metric_id: str
  valeur: float | null      # null SSI n insuffisant pour dériver (échappatoire, jamais une valeur inventée)
  version_definition: str   # ex. schema_version du dictionnaire au moment du calcul
  fraicheur: float          # âge du snapshot le plus ancien utilisé, en jours, TOUJOURS affiché
  n: int                    # taille de l'échantillon ayant servi à la dérivation
```

### 5.5 Sortie — `SignalXmR`

```yaml
SignalXmR:
  metric_id: str
  type_signal: str          # enum TypeSignalXmR
  valeur_observee: float | null   # null SSI DONNEES_INSUFFISANTES
  limite_naturelle_haute: float | null
  limite_naturelle_basse: float | null
  n: int
```
Ne porte JAMAIS de champ de cause ni de désignation — même discipline que `note_investigation`
de M6 (DA-M6-07), transposée aux séries temporelles.

### 5.6 Sortie — `RapportAnalytique` (destination : dashboards, digest)

```yaml
RapportAnalytique:
  type: str                 # toujours "RAPPORT_ANALYTIQUE"
  role: str | null           # null = non filtré (vue complète)
  metriques: list[ValeurMetrique]
  signaux: list[SignalXmR]
  snapshot_id: str           # sha256 déterministe du contenu (patron roi_engine.py)
```

### 5.7 Sortie — `DigestAnalyticsQuotidien` (destination Nathan, distribué par M1)

```yaml
DigestAnalyticsQuotidien:
  type: str                  # toujours "DIGEST_ANALYTICS"
  nb_signaux_actifs: int
  signaux_actifs: list[SignalXmR]     # UNIQUEMENT les signaux hors limites, jamais DONNEES_INSUFFISANTES
  hash_digest: str
```

## 6. CRITÈRES D'ACCEPTATION

- **CA-M8-01** : le compilateur du dictionnaire lit tous les `metrics/*.yaml` présents et valide
  les 7 champs texte obligatoires ; un fichier malformé produit un rejet nommé.
- **CA-M8-02** : un module sans fichier `metrics/*.yaml` n'apparaît pas au dictionnaire — aucune
  métrique n'est fabriquée pour lui.
- **CA-M8-03** : un snapshot dont `module_source` est inconnu du dictionnaire est rejeté (verdict
  nommé).
- **CA-M8-04** : un snapshot portant un `metric_id` non déclaré par son `module_source` est rejeté
  (verdict nommé, distinct du rejet précédent).
- **CA-M8-05** : `snapshot_id` d'un rapport est déterministe — mêmes snapshots + mêmes arguments
  → mêmes octets (patron `roi_engine.py`, testé par appel double).
- **CA-M8-06** : le registre append-only des snapshots est hash-chaîné (patron M4/M6) ; toute
  altération d'un maillon est détectée à la re-validation.
- **CA-M8-07** : aucune fonction de la couche sémantique ne renvoie un nombre sans provenance
  complète (`metric_id`, version, fraîcheur, `n`).
- **CA-M8-08** : une dérivation sans donnée suffisante renvoie `valeur: null` avec `n` réel affiché
  — jamais une valeur substituée (zéro, moyenne devinée, etc.).
- **CA-M8-09** : la détection XmR calcule des limites naturelles à partir de l'historique fourni,
  jamais un seuil codé en dur ; sous le `n` minimal fourni par l'appelant, le signal est
  `DONNEES_INSUFFISANTES`.
- **CA-M8-10** : aucun `SignalXmR` ne porte de champ de cause ou d'accusation (garde AST,
  transversale au paquet).
- **CA-M8-11** : un rapport filtré par rôle ne contient jamais une métrique hors de la liste
  autorisée à ce rôle.
- **CA-M8-12** : `TypeSignalXmR` porte son échappatoire D-032 (`DONNEES_INSUFFISANTES`) — garde
  AST transversale, patron `conformite.py` de M6.
- **CA-M8-13** : aucun appel `random` non ensemencé, horloge, réseau, ni littéral numérique en
  contexte de coût dans tout le paquet — garde AST (patron `conformite.py`).
- **CA-M8-14** : aucune fonction de M8 n'écrit dans le registre d'un autre module (garde
  structurelle : M8 n'importe aucun paquet `mX_*` de domaine).
- **CA-M8-15** : le digest quotidien est déterministe et ne contient que les signaux ACTIFS
  (hors limites), jamais les `DONNEES_INSUFFISANTES`.

Les 15 critères sont en séquence complète, chacun porté par exactement une story.

## 7. STORIES

Six stories (au lieu de neuf chez M6) : M8 v1 est un pipeline plus linéaire (une seule famille de
snapshot, pas de cycle multi-entités comme le PO→réception de M6), donc moins de frontières
distinctes à prouver séparément.

### S001 — Contrats gelés, validation d'entrée, dictionnaire de métriques

| Attribut | Valeur |
|---|---|
| **Périmètre** | Valide la structure d'un `SnapshotModule`, compile le dictionnaire canonique à partir des `metrics/*.yaml` réellement présents (M7 seul aujourd'hui), rejette un `module_source`/`metric_id` inconnu par un verdict nommé et distinct. |
| **Critères portés** | CA-M8-01, CA-M8-02, CA-M8-03, CA-M8-04 |
| **Tier** | T2 (contrat d'entrée transversal à tout le module, comme M6-S001) |
| **Dépendances** | Aucune |
| **Estimation (D-044)** | ~45 min (cible ≤1h) |

### S002 — Registre append-only hash-chaîné des snapshots

| Attribut | Valeur |
|---|---|
| **Périmètre** | Copie-adaptation du patron M4/M6 (`encodage.py`/`registre.py`) ; `snapshot_id` déterministe, patron `roi_engine.py`. |
| **Critères portés** | CA-M8-05, CA-M8-06 |
| **Tier** | T1 |
| **Dépendances** | S001 |
| **Estimation (D-044)** | ~30 min (copie-adaptation mécanique, patron déjà prouvé) |

### S003 — Couche sémantique : dérivations pures et provenance

| Attribut | Valeur |
|---|---|
| **Périmètre** | Fonctions indexées par `metric_id`, provenance complète (`metric_id`, version, fraîcheur, `n`), `null` fail-closed si `n` insuffisant. |
| **Critères portés** | CA-M8-07, CA-M8-08 |
| **Tier** | T1 |
| **Dépendances** | S001, S002 |
| **Estimation (D-044)** | ~40 min (cible ≤1h) |

### S004 — Détection de signaux XmR

| Attribut | Valeur |
|---|---|
| **Périmètre** | Limites naturelles calculées à partir de l'historique fourni, `n` minimal fourni par l'appelant, `DONNEES_INSUFFISANTES` sous le seuil, aucune cause attribuée. |
| **Critères portés** | CA-M8-09, CA-M8-10 |
| **Tier** | T1 |
| **Dépendances** | S003 |
| **Estimation (D-044)** | ~45 min (cible ≤1h) |

### S005 — Rapports filtrés par rôle

| Attribut | Valeur |
|---|---|
| **Périmètre** | `RapportAnalytique`, filtrage par liste de `metric_id` autorisés fournie par l'appelant, jamais une métrique hors liste dans un rapport filtré. |
| **Critères portés** | CA-M8-11 |
| **Tier** | T2 (frontière de destinataire par rôle, patron M6-S007) |
| **Dépendances** | S003, S004 |
| **Estimation (D-044)** | ~40 min (cible ≤1h) |

### S006 — Conformité statique transversale et digest quotidien

| Attribut | Valeur |
|---|---|
| **Périmètre** | Copie-adaptation de `conformite.py` (M6) : échappatoire D-032 sur `TypeSignalXmR`, 4 familles d'appels interdits, garde structurelle « aucun import de module de domaine », garde « aucun champ de cause dans `SignalXmR` ». `DigestAnalyticsQuotidien` déterministe, signaux actifs seulement. |
| **Critères portés** | CA-M8-12, CA-M8-13, CA-M8-14, CA-M8-15 |
| **Tier** | T1 |
| **Dépendances** | S001, S002, S003, S004, S005 |
| **Estimation (D-044)** | ~1h (cible atteinte, pas de marge) — mesuré : la story équivalente chez M6 (S009, conformité + digest) a exigé 2 tours de revue scellée avant APPROVE ; si l'implémentation dépasse le cap dur de 3h, la découper en deux stories (conformité seule, puis digest seul) est obligatoire (D-044), pas une option. |

## 8. DÉCISIONS TRANSVERSALES APPLICABLES

D-010 (metrics-as-code, dictionnaire canonique) ; D-032 (échappatoire INDETERMINE obligatoire,
ici `DONNEES_INSUFFISANTES`) ; #109 (copie-adaptation, jamais d'import inter-modules — M8 est
l'exemple le plus strict : il ne doit importer AUCUN paquet `mX_*` de domaine) ; R-020 (constat
neutre, jamais d'accusation — transposé aux séries temporelles) ; patron mesuré `roi_engine.py`
(`snapshot_id` stdlib) réutilisé tel quel plutôt que réinventé.

## 9. PARAMÈTRES CONFIGURABLES

| Paramètre | Description | Valeur par défaut |
|---|---|---|
| `n_minimal_xmr` | Taille d'échantillon minimale avant `DONNEES_INSUFFISANTES`. | **Fourni par l'appelant à chaque détection. Aucun défaut : un défaut serait un seuil arbitraire inventé.** |
| `horodatage_reference` | Instant de référence pour calculer la fraîcheur. | **Fourni par l'appelant — M8 n'a aucune horloge.** |
| `metric_ids_autorises` (par rôle) | Liste blanche de métriques visibles pour un rôle donné. | **Fournie par l'appelant. Absence = rapport non filtré (vue complète), jamais un rôle deviné.** |

## 10. FRONTIÈRES RATIFIÉES (rappel)

M8 ne possède aucune donnée source, n'écrit jamais dans un registre d'un autre module, ne calcule
jamais un chiffre par LLM, n'invente jamais une métrique pour un module sans dictionnaire déclaré,
ne fixe aucun seuil d'alerte arbitraire, ne décide et ne recommande rien (position de M9), ne
construit pas le MMM en v1 (GATED), et n'introduit DuckDB/Parquet que par une story GATED tracée —
jamais une substitution silencieuse d'un format par un autre qui se ferait passer pour l'original.
