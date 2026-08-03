# PRD — MODULE M9 (STRATEGIC INTELLIGENCE)

## 0. TRANCHÉ SUR LES POINTS OUVERTS DE L'ANALYSTE

- **§7.1 (Supervisor)** : **entièrement GATED en v1**, choix PRUDENT plutôt que la mécanique
  minimale esquissée par l'analyste. Une mécanique de séquencement n'a de sens que comme
  préparation au Council réel — la construire avant que le Council n'existe risquerait de créer
  une pièce non testable en conditions réelles et de brouiller la frontière « v1 = harnais pur,
  zéro contenu délibératif ». v1 = Strategic Data Fabric + validation structurelle seulement.
- **§7.2 (contradiction)** : un seul cas déterministe — même `module_source` + même `horodatage`,
  `valeurs` différentes pour une même clé. Contradiction sémantique inter-modules hors v1.
- **§7.3 (15 éléments)** : constante `CHAMPS_RAPPORT_STRATEGIQUE` (frozenset) dans `contrats.py`,
  pas un fichier déclaratif séparé — les 15 éléments sont fixes et gelés par la fiche source.
- **§7.4 (obtention des snapshots)** : hors périmètre M9. Reçoit un snapshot déjà construit,
  jamais d'import de `m1_front_office`...`m8_analytics`/`m5_financecore` (cohérent avec #109).
- **§7.5 (`memoire_m10`)** : le champ fait partie du contrat structurel (présence obligatoire,
  validation de PRÉSENCE seulement) ; la validation de son CONTENU (référence réelle à M10) est
  un GATED futur, dépendant de la construction de M10 (pas encore commencée, position tardive).

## 1. PERSONAS

- **Nathan (dirigeant)** : consulte l'état consolidé pour voir en un coup d'œil les derniers
  faits connus de chaque module et toute contradiction interne détectée — sans qu'aucun chiffre
  ne soit jamais inventé par M9 lui-même.
- **Futur Council d'agents (consommateur, hors périmètre v1)** : consommera l'état consolidé
  (Business State Graph) comme source de vérité factuelle avant de produire un rapport
  stratégique — M9 doit donc exposer un contrat stable, pas un format ad hoc.
- **Futur rédacteur d'un rapport stratégique (humain ou LLM, hors périmètre v1)** : doit se
  conformer aux 15 clés obligatoires ou voir son rapport rejeté par un verdict nommé.

## 2. PARCOURS PRINCIPAUX

### 2.1 Agrégation d'un snapshot dans l'état consolidé

Un appelant fournit un `SnapshotModule` (forme réutilisée de M8 : `module_source, horodatage,
valeurs`). M9 valide sa structure, l'ajoute au registre append-only, et met à jour l'état
consolidé indexé par `module_source` (dernier snapshot connu par module).

### 2.2 Détection de contradiction interne

Lorsqu'un nouveau snapshot est ajouté pour un `module_source` et un `horodatage` DÉJÀ présents
dans le registre avec des `valeurs` différentes, une contradiction est signalée nommant les deux
`ligne_id` en conflit — jamais une cause, jamais une résolution automatique.

### 2.3 Validation structurelle d'un rapport stratégique

Un rapport stratégique (fourni par un futur Council, hors périmètre v1) est validé contre
`CHAMPS_RAPPORT_STRATEGIQUE` (15 clés exactes). Une clé manquante ou une clé en trop est un rejet
nommé — v1 ne valide QUE la structure, jamais la pertinence du contenu de chaque champ.

## 3. PÉRIMÈTRE V1 vs ROADMAP

### 3.1 En périmètre v1 (mode ombre, prouvable en CI Python, stdlib + PyYAML)

| Élément | Statut |
|---|---|
| Contrats gelés (`SnapshotModule` réutilisé, `CHAMPS_RAPPORT_STRATEGIQUE` 15 clés) + validation d'entrée | v1 |
| Registre append-only hash-chaîné des snapshots consolidés | v1 |
| Business State Graph : agrégation pure par `module_source` | v1 |
| Détection de contradiction interne déterministe (même source+horodatage, valeurs différentes) | v1 |
| Validation structurelle du rapport stratégique (15/15 clés, rejet nommé) | v1 |
| Conformité statique transversale (anti-invention, anti-import, déterminisme) | v1 |

### 3.2 Repoussé GATED/T3

| Élément | Raison du report |
|---|---|
| Council d'agents réel (CEO, COO, CFO, CMO, Sales, Ops, Risk, Data, Execution) | Nécessite de vrais appels LLM, hors périmètre déterministe |
| Strategic Supervisor (orchestration du Council) | N'a de sens qu'en préparation du Council réel (§0) — choix prudent, reporté entièrement |
| Scénarios narratifs (7j/30j/90j/6mois/12mois), stress tests, playbooks | Contenu délibératif, dépend du Council |
| Decision Intelligence Engine, Action Orchestrator | Contenu délibératif + effets de bord réels |
| LangGraph/Temporal/Langfuse/Ragas/DeepEval réels | Hors stdlib, story GATED tracée (patron DuckDB de M8) |
| Rythme exécutif (War Room, rapports, board memo) | Nécessite un ordonnanceur externe |
| Notification Nathan, Approval Engine unifié réel | Infra/service central pas encore construits |
| Détection de contradiction sémantique inter-modules | Nécessite un mapping métier hors périmètre v1 |
| Validation du CONTENU de `memoire_m10` | Dépend de la construction de M10 (pas commencée) |

## 4. ÉNUMÉRÉS FERMÉS

M9 v1 n'a AUCUN énuméré fermé nécessitant une échappatoire D-032 : `SnapshotModule` et
`RapportStrategique` sont des contrats de STRUCTURE (ensembles de clés attendues), pas des
classifications que M9 déduit d'une entrée ambiguë — aucune valeur à classer parmi un ensemble
nommé n'existe dans le périmètre v1 (mesuré : contrairement à M3/M6/M8/M5, aucune des données de
M9 v1 n'est un type/statut catégoriel inféré). La conformité statique de M9 (S005) devra donc
documenter explicitement cette absence plutôt que d'en fabriquer une artificiellement — cohérent
avec le gap de conception trouvé et corrigé chez M5-S007 (ne pas exiger une échappatoire là où
aucune classification n'existe).

## 5. CONTRATS GELÉS

### 5.1 Entrée — `SnapshotModule` (réutilisé tel quel de `m8_analytics`, patron mesuré)

```yaml
SnapshotModule:
  module_source: str
  horodatage: str         # fourni par l'appelant — M9 n'a pas d'horloge
  valeurs:
    <cle>: str             # valeur brute rapportée par le module source
```

### 5.2 Maillon du registre append-only — `MaillonSnapshotConsolide`

```yaml
MaillonSnapshotConsolide:
  index: int
  module_source: str
  horodatage: str
  valeurs: dict
  hash_precedent: str      # chaîne vide au premier maillon (patron M8 EXACT — RegistreSnapshots,
  hash_maillon: str         # PAS le patron générique M4/M5 : M9 v1 n'a qu'UN SEUL type de
                             # maillon, la classe générique à discriminateur type_entree
                             # n'apporterait aucune garantie supplémentaire, cf. DA-M8 « aucun
                             # fichier materiel.py-équivalent » appliqué ici à la classe Registre)
```

### 5.3 Sortie — `EtatConsolide` (Business State Graph minimal)

```yaml
EtatConsolide:
  type: str                    # toujours "ETAT_CONSOLIDE"
  faits_par_module: dict         # {module_source: dernier MaillonSnapshotConsolide connu}
  contradictions: list            # [{ligne_id_a, ligne_id_b, module_source, horodatage}]
  etat_id: str                     # sha256 déterministe (patron roi_engine.py)
```

### 5.4 Contrat — `CHAMPS_RAPPORT_STRATEGIQUE` (15 clés exactes, copie mot pour mot de la fiche
source)

```python
CHAMPS_RAPPORT_STRATEGIQUE = frozenset({
    "etat", "diagnostic", "preuves", "hypotheses", "incertitudes", "scenarios",
    "recommandations", "priorites", "impacts", "risques", "actions", "validation",
    "taches_par_departement", "suivi", "memoire_m10",
})
```

Un rapport stratégique valide en v1 est un `dict` dont `set(rapport.keys()) ==
CHAMPS_RAPPORT_STRATEGIQUE` exactement — v1 ne contraint PAS le type/contenu de chaque valeur
(un futur GATED le fera), seulement leur présence structurelle complète.

## 6. CRITÈRES D'ACCEPTATION

- **CA-M9-01** : un `SnapshotModule` structurellement valide est accepté ; un snapshot
  structurellement invalide est rejeté par un verdict nommé.
- **CA-M9-02** : le registre append-only des snapshots consolidés est hash-chaîné (patron
  M2/M4/M5/M6/M8) ; toute altération d'un maillon est détectée à la re-validation.
- **CA-M9-03** : l'état consolidé (Business State Graph) reflète TOUJOURS le dernier snapshot
  connu par `module_source`, calculé par relecture pure du registre — jamais un compteur maintenu
  à part.
- **CA-M9-04** : deux snapshots partageant `module_source` ET `horodatage` mais des `valeurs`
  différentes sont signalés comme une contradiction interne, nommant les deux `ligne_id` en
  conflit — jamais une cause ni une résolution automatique.
- **CA-M9-05** : un rapport stratégique contenant EXACTEMENT les 15 clés de
  `CHAMPS_RAPPORT_STRATEGIQUE` est accepté structurellement ; une clé manquante ou en trop est un
  rejet nommé et distinct.
- **CA-M9-06** : `etat_id` d'un état consolidé est déterministe (mêmes snapshots + mêmes
  arguments → mêmes octets), patron `roi_engine.py`/`snapshot_id`.
- **CA-M9-07** : aucun chiffre, revenu ou capacité n'est codé en dur en Python — garde AST
  transversale (patron `conformite.py::LITTERAL_COUT_INTERDIT`).
- **CA-M9-08** : aucune fonction de M9 n'importe un paquet `mX_*` de domaine (garde structurelle,
  patron DA-M8-01/DA-M5-04).
- **CA-M9-09** : aucun appel `random` non ensemencé, horloge, ni réseau dans tout le paquet
  (garde AST, patron `conformite.py` M3/M5/M6/M8).
- **CA-M9-10** : aucune contradiction interne détectée ne porte de champ de cause, de responsable
  ou de résolution attribuée — un constat, jamais un verdict de faute (R-020 transposé une 4e
  fois).

Les 10 critères sont en séquence complète, chacun porté par exactement une story.

## 7. STORIES

Cinq stories — périmètre délibérément MINCE (harnais seulement, aucun contenu délibératif), plus
étroit que M5/M8 (7/6 stories) car v1 ne fait aucun calcul sémantique riche, seulement structure,
agrégation et détection de contradiction.

### S001 — Contrats gelés, validation d'entrée

| Attribut | Valeur |
|---|---|
| **Périmètre** | `SnapshotModule` (réutilisé de M8), `CHAMPS_RAPPORT_STRATEGIQUE` (15 clés), validation structurelle d'un snapshot, verdicts de rejet nommés. |
| **Critères portés** | CA-M9-01 |
| **Tier** | T2 (contrat d'entrée transversal à tout le module, comme M5-S001/M8-S001) |
| **Dépendances** | Aucune |
| **Estimation (D-044)** | ~40 min (cible ≤1h) |

### S002 — Registre append-only hash-chaîné des snapshots consolidés

| Attribut | Valeur |
|---|---|
| **Périmètre** | Copie-adaptation du patron M8 (`RegistreSnapshots`, UN SEUL type de maillon — pas besoin de la classe générique M4/M5, M9 v1 n'a qu'un seul type d'écriture). |
| **Critères portés** | CA-M9-02 |
| **Tier** | T1 |
| **Dépendances** | S001 |
| **Estimation (D-044)** | ~30 min (copie-adaptation mécanique, patron 5 fois prouvé) |

### S003 — Business State Graph et détection de contradiction

| Attribut | Valeur |
|---|---|
| **Périmètre** | État consolidé par relecture pure du registre (dernier snapshot par `module_source`) ; détection de contradiction interne déterministe (même source+horodatage, valeurs différentes) ; `etat_id` déterministe. |
| **Critères portés** | CA-M9-03, CA-M9-04, CA-M9-06, CA-M9-10 |
| **Tier** | T2 (mécanisme nouveau — détection de contradiction n'a pas d'équivalent direct dans un module précédent) |
| **Dépendances** | S001, S002 |
| **Estimation (D-044)** | ~45 min (cible ≤1h) |

### S004 — Validation structurelle du rapport stratégique

| Attribut | Valeur |
|---|---|
| **Périmètre** | Validation qu'un rapport stratégique contient EXACTEMENT les 15 clés de `CHAMPS_RAPPORT_STRATEGIQUE` — rejet nommé sur clé manquante ou en trop, jamais une validation du contenu. |
| **Critères portés** | CA-M9-05 |
| **Tier** | T2 (frontière de contrat structurel critique — c'est la garantie centrale de la fiche source) |
| **Dépendances** | S001 |
| **Estimation (D-044)** | ~30 min (cible ≤1h) |

### S005 — Conformité statique transversale

| Attribut | Valeur |
|---|---|
| **Périmètre** | Copie-adaptation de `conformite.py` (M3/M5/M6/M8) : garde littéral de chiffre/coût codé en dur, garde anti-import de domaine, 3 familles d'appels interdits (random/horloge/réseau), garde anti-cause sur les contradictions. AUCUNE échappatoire D-032 requise (§4 — M9 v1 n'a aucun énuméré de domaine à classer), documenté explicitement plutôt que fabriqué. |
| **Critères portés** | CA-M9-07, CA-M9-08, CA-M9-09 |
| **Tier** | T1 (patron désormais mesuré 5 fois) |
| **Dépendances** | S001, S002, S003, S004 |
| **Estimation (D-044)** | ~50 min (cible ≤1h) — périmètre large (scanne tout le paquet) ; découpage obligatoire au-delà de 3h (D-044), pas une option. |

## 8. DÉCISIONS TRANSVERSALES APPLICABLES

#109 (copie-adaptation, jamais d'import inter-modules — M9 n'importe aucun paquet `mX_*` de
domaine, patron le plus strict avec M8/M5) ; R-020 (constat neutre, jamais d'accusation —
transposé une 4e fois aux contradictions internes) ; patron mesuré `roi_engine.py`
(`etat_id`/`snapshot_id` stdlib) réutilisé tel quel ; R-009 (position tardive dans l'ordre —
risque de « projection sur du vide » mitigé par le fail-closed, pas par l'attente).

## 9. PARAMÈTRES CONFIGURABLES

Aucun seuil numérique arbitraire en v1 : la détection de contradiction est une comparaison exacte
(égalité stricte de `valeurs`), jamais un seuil de tolérance devinable ; la validation du rapport
stratégique est une comparaison d'ensembles de clés exacte, jamais une liste partielle acceptée.

## 10. FRONTIÈRES RATIFIÉES (rappel)

M9 ne possède aucune donnée source, n'écrit jamais dans le registre d'un autre module, ne calcule
ni n'invente jamais un chiffre/revenu/capacité, ne produit AUCUN contenu délibératif en v1
(diagnostic, recommandation, scénario — tous GATED), n'invoque jamais un LLM, et n'importe jamais
un paquet `mX_*` de domaine.
