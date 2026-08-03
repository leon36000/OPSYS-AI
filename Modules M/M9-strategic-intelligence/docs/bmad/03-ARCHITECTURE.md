# ARCHITECTURE — MODULE M9 (STRATEGIC INTELLIGENCE)

## 0. CONSENSUS RATIFIÉ

Décision de fondation prise AVANT ce document, par consultation de l'agent `architecte` (Claude
Opus, subagent natif) sur la question : M9 v1 — quel périmètre est RÉELLEMENT prouvable en CI
Python déterministe, sachant que la fiche source décrit un « Council d'agents orchestré par un
Strategic Supervisor déterministe » qui semble intrinsèquement nécessiter de vrais appels LLM ?
Citations vérifiées avant adoption (pas prises pour argent comptant) :

- `m8_analytics/registre.py:8-64` — `RegistreSnapshots` (hash-chaîné, indexé par `module_source`)
  et `contrats.CHAMPS_SNAPSHOT_MODULE` SONT déjà l'agrégation multi-module dont M9 a besoin pour
  sa Strategic Data Fabric — patron à copier-adapter, pas à réinventer.
- `m8_analytics/conformite.py:665-709` (`verifier_aucun_import_domaine`) — confirme que M9 ne
  peut PAS `import m8_analytics` : la réutilisation du patron d'agrégation se fait par
  copie-adaptation locale, jamais par import.
- `m8_analytics/semantique.py:49-53` (`deriver_metrique`) — la fraîcheur se calcule depuis un
  `horodatage_reference` INJECTÉ, jamais l'horloge ; patron à calquer pour M9.
- `m8_analytics/tests/test_semantique.py:117-135` — le fail-closed (`valeur: null, n: 0` sans
  donnée suffisante) EST la réponse déjà mesurée à R-009 (« lirait du vide ») ; M9 applique le
  même principe plutôt que d'attendre.

**Décision retenue : v1 = le HARNAIS déterministe uniquement.** Le mot « déterministe » de la
fiche source s'applique à l'ORCHESTRATION (séquencement, scoring, quorum, validation de schéma),
jamais au raisonnement des agents (l'appel LLM lui-même). Le Strategic Supervisor et le Council
d'agents sont ENTIÈREMENT GATÉS en v1 (choix prudent, PRD §0 — pas même une mécanique de
séquencement minimale, pour ne pas construire une pièce qui n'a de sens qu'en préparation d'un
Council qui n'existe pas encore). v1 ne revendique AUCUNE « intelligence » — seulement structure,
fraîcheur, détection de contradiction, validation.

**Correction factuelle actée** (l'architecte a réfuté une hypothèse initiale) : `conformite.py`
n'est PAS hérité automatiquement par tout module — mesuré : seuls M3/M5/M6/M8 le portent ; M1/M2/
M4/M7 ne l'ont pas (M7 n'a que `urllib.parse`, `utm_engine.py:3`). M9 le construit explicitement
(S005), comme un choix délibéré cohérent avec le patron des modules les plus rigoureux.

## 1. PAQUET `m9_strategic_intelligence` — MODULES INTERNES

Le paquet est autonome, copie-adaptation (#109) — comme M8/M5, il n'importe **aucun** paquet
`mX_*` de domaine, même en lecture : il ne connaît structurellement aucun module source, seulement
le format générique `SnapshotModule` que l'appelant lui fournit.

| Fichier | Rôle | Story |
|---|---|---|
| `__init__.py` | Identité de paquet — docstring seule, aucune logique (patron #109). | — |
| `contrats.py` | Constantes gelées : `CHAMPS_SNAPSHOT_MODULE` (réutilisé de M8), `CHAMPS_RAPPORT_STRATEGIQUE` (15 clés). | S001 |
| `validation.py` | Valide la structure d'un `SnapshotModule` ; **foyer UNIQUE du vocabulaire `REJ-*`** de tout le paquet (DA-M9-03, patron DA-M5-03). | S001 |
| `encodage.py` | Copie EXACTE de `m8_analytics/encodage.py` (encodage canonique injectif, préfixage de longueur) — AUCUNE simplification, leçon de M5-S002 (le crew avait dévié d'une copie exacte, perdant l'injectivité list/tuple). | S002 |
| `registre.py` | `RegistreSnapshots` — copie-adaptation EXACTE du patron `m8_analytics/registre.py` (spécifique à UN SEUL type de maillon, PAS la classe générique `Registre` de M4/M5 : M9 v1 n'a qu'un seul type d'écriture, DA-M9-01). | S002 |
| `etat_consolide.py` | Agrège l'état par relecture pure du registre (dernier snapshot par `module_source`) ; détecte les contradictions internes déterministes ; calcule `etat_id`. | S003 |
| `rapport_strategique.py` | Valide qu'un rapport stratégique contient EXACTEMENT les 15 clés de `CHAMPS_RAPPORT_STRATEGIQUE` — structure seulement, jamais le contenu. | S004 |
| `conformite.py` | Contrôle statique AST transversal : copie-adaptation de `m8_analytics/conformite.py`, SANS entrée `_DEROGATIONS_ECHAPPATOIRE` (DA-M9-02 — aucun énuméré de domaine à classer en v1, documenté explicitement). | S005 |

Aucun fichier `materiel.py`-équivalent (orchestrateur unique) : M9 v1 n'a qu'UN SEUL type
d'écriture (l'ajout d'un snapshot consolidé) — la discipline « point d'écriture unique » est déjà
satisfaite par construction, `registre.py::ajouter` (ou son équivalent `RegistreSnapshots`) est le
seul point d'écriture du paquet (patron M8, section 1 de son architecture).

## 2. SCHÉMAS DE DONNÉES

### 2.1 Entrée — `SnapshotModule` (réutilisé tel quel, patron mesuré `m8_analytics`)

```yaml
SnapshotModule:
  module_source: str
  horodatage: str
  valeurs:
    <cle>: str
```

### 2.2 Maillon du registre append-only — `MaillonSnapshotConsolide`

```yaml
MaillonSnapshotConsolide:
  index: int
  module_source: str
  horodatage: str
  valeurs: dict
  hash_precedent: str      # chaîne vide au premier maillon — patron M8 EXACT (DA-M8-05),
  hash_maillon: str         # PAS le patron générique M4/M5/precedent_ligne_id=None : M9 v1
                             # réutilise RegistreSnapshots (un seul type de maillon), pas la
                             # classe Registre générique (DA-M9-01).
```

### 2.3 Sortie — `EtatConsolide` (Business State Graph minimal)

```yaml
EtatConsolide:
  type: str                     # toujours "ETAT_CONSOLIDE"
  faits_par_module: dict          # {module_source: dernier MaillonSnapshotConsolide connu}
  contradictions: list             # [{ligne_id_a: index_a, ligne_id_b: index_b, module_source, horodatage}]
  etat_id: str                      # sha256 déterministe (patron roi_engine.py), SANS son propre champ
```

Note : les maillons de M9 utilisent `index` (patron M8), pas `ligne_id` — la clé de référence
d'une contradiction est donc l'`index` du maillon en conflit, pas un `ligne_id` au sens M4/M5.

### 2.4 Contrat — `CHAMPS_RAPPORT_STRATEGIQUE` (copie mot pour mot du PRD §5.4)

```python
CHAMPS_RAPPORT_STRATEGIQUE = frozenset({
    "etat", "diagnostic", "preuves", "hypotheses", "incertitudes", "scenarios",
    "recommandations", "priorites", "impacts", "risques", "actions", "validation",
    "taches_par_departement", "suivi", "memoire_m10",
})
```

### 2.5 Énumérés fermés — AUCUN en v1 (DA-M9-02)

Contrairement à M3/M5/M6/M8, M9 v1 ne définit AUCUN énuméré de domaine nécessitant une
échappatoire D-032 : `SnapshotModule` et `RapportStrategique` sont des contrats de STRUCTURE
(ensembles de clés), jamais une classification que M9 déduit d'une entrée ambiguë. `conformite.py`
(S005) devra documenter explicitement cette absence — patron `verifier_conformite` adapté pour ne
PAS exiger `AUCUN_ENUMERE_EXAMINE` comme une violation ici (voir DA-M9-02).

## 3. INTERFACES ET CONTRATS

### 3.1 Ce que M9 reçoit de l'appelant (jamais d'un module de domaine directement)

`SnapshotModule` à chaque agrégation ; un rapport stratégique (fourni par un futur Council, hors
périmètre v1) à chaque validation structurelle.

### 3.2 Ce que M9 émet vers un futur Council d'agents (hors périmètre v1)

`EtatConsolide` — Business State Graph minimal, source de vérité factuelle avant toute
délibération.

### 3.3 Ce que M9 émet vers Nathan / le dashboard exécutif (hors périmètre v1)

Aucun contrat gelé v1 — le rythme exécutif (War Room, rapports) est GATED, nécessite un
ordonnanceur externe.

### 3.4 État interne faisant autorité

Le registre append-only de `MaillonSnapshotConsolide` est la source de vérité unique des
snapshots reçus. `EtatConsolide` est une **dérivation pure** de ce registre, jamais un compteur
maintenu à part (même discipline que DA-M6-09/DA-M8, « état interne faisant autorité »).

## 4. DÉCISIONS D'ARCHITECTURE TRANCHÉES

### DA-M9-01 — `RegistreSnapshots` (patron M8 spécifique), PAS la classe `Registre` générique (M4/M5)

**Décision** : M9 copie-adapte `m8_analytics/registre.py::RegistreSnapshots` (un seul type de
maillon, champs `index`/`hash_precedent`/`hash_maillon`) plutôt que la classe générique
`Registre` de `m4_field_ops`/`m5_financecore` (`type_entree`/`ligne_id`/`precedent_ligne_id`,
réutilisable pour plusieurs familles de maillons).

**Justification** : la classe générique M4/M5 se justifie quand un module a PLUSIEURS familles de
maillons à faire coexister dans un même registre (M5 : mouvements ET approbations). M9 v1 n'a
qu'UN SEUL type d'écriture (snapshot consolidé) — le discriminateur `type_entree` n'apporterait
aucune garantie supplémentaire ici, exactement le raisonnement déjà tranché pour M8 elle-même
(« M8 n'a qu'UN SEUL type de maillon », architecture M8 §1).

### DA-M9-02 — Aucune échappatoire D-032 en v1, documenté explicitement (pas fabriqué)

**Décision** : `conformite.py` de M9 n'a AUCUNE entrée dans `_DEROGATIONS_ECHAPPATOIRE`, et sa
garde d'énumérés (`_est_enumere_domaine`/équivalent) ne doit PAS être forcée à trouver un énuméré
qui n'existe pas.

**Justification** : `SnapshotModule` et `CHAMPS_RAPPORT_STRATEGIQUE` sont des ensembles de NOMS
de champs (comme `CHAMPS_*` chez M5/M8, déjà exclus de la détection), jamais des valeurs
catégorielles que M9 classe. Inventer un énuméré artificiel pour satisfaire une garde générique
serait exactement l'erreur inverse du gap trouvé chez M5-S007 (où la garde traitait à tort des
enums caller-spécifiés comme nécessitant une échappatoire) — ici, il n'y a simplement RIEN à
classer. Le gate de cohérence du cadrage (`verif_coherence.py`) ne doit donc PAS exiger la
présence d'un énuméré fermé avec échappatoire pour M9, contrairement à M3/M5/M6/M8.

### DA-M9-03 — Foyer unique du vocabulaire de verdicts (`validation.py`), patron DA-M5-03

**Décision** : tout verdict nommé (`REJ-*`) du paquet est construit via un constructeur défini
dans `validation.py`, jamais un dict de rejet improvisé localement.

**Justification** : patron désormais établi 2 fois (M8, M5) — évite la dispersion du vocabulaire
de rejet entre `validation.py`/`etat_consolide.py`/`rapport_strategique.py`.

### DA-M9-04 — Aucun import de paquet de domaine, même en lecture

**Décision** : `m9_strategic_intelligence` n'importe JAMAIS `m1_front_office`, `m2_revenue_crm`,
`m3_estimation`, `m4_field_ops`, `m5_financecore`, `m6_material_control`, `m7_marketing`,
`m8_analytics`, ni `m10_*` futur. Garde AST dédiée dans `conformite.py` (copie-adaptation directe
de `verifier_aucun_import_domaine`).

**Justification** : #109, frontière la plus stricte du dépôt aux côtés de M8/M5 — M9 ne consomme
que des `SnapshotModule` génériques fournis par l'appelant, jamais une structure de module connue
à l'avance (cohérent avec PRD §7.4).

### DA-M9-05 — Détection de contradiction : comparaison pure, jamais une cause

**Décision** : deux maillons partageant `module_source` ET `horodatage` mais des `valeurs`
différentes sont signalés comme contradiction, nommant uniquement leurs deux `index` — jamais un
champ de cause, de responsable, ni de résolution suggérée.

**Justification** : R-020 transposé une 4e fois (M6 stock, M8 signaux XmR, M5 ajustements, M9
contradictions) — une contradiction entre deux sources est un FAIT à investiguer par un humain ou
un futur Council, jamais un verdict de faute attribué automatiquement par M9.

### DA-M9-06 — Déterminisme total (zéro horloge, zéro aléa non ensemencé, zéro réseau)

**Décision** : aucun module de M9 n'appelle `time.time`, `datetime.now`/`today`/`utcnow`,
`random` sans graine, `uuid`, `secrets`, `os.urandom`, ni aucune primitive réseau. Tout
horodatage provient de l'appelant, reproduit tel quel.

**Justification** : reproductibilité bit-à-bit de `etat_id` exigée (CA-M9-06) — garde par
`conformite.py`, copie-adaptation directe de M3/M5/M6/M8.

## 5. CE QUE CHAQUE STORY PROUVE

| Story | Ce qu'elle prouve | Critères | Tier |
|---|---|---|---|
| **S001** — Contrats gelés, validation | Snapshot structurellement valide accepté, invalide rejeté par verdict nommé. | CA-M9-01 | T2 |
| **S002** — Registre append-only des snapshots consolidés | Chaîne préservée à l'ajout, altération détectée. | CA-M9-02 | T1 |
| **S003** — Business State Graph et contradiction | État consolidé par relecture pure ; contradiction interne détectée sans cause attribuée ; `etat_id` déterministe. | CA-M9-03, 04, 06, 10 | T2 |
| **S004** — Validation du rapport stratégique | Rejet nommé sur clé manquante ou en trop parmi les 15 attendues. | CA-M9-05 | T2 |
| **S005** — Conformité statique transversale | Anti-invention, anti-import de domaine, déterminisme — sans échappatoire D-032 fabriquée. | CA-M9-07, 08, 09 | T1 |

## 6. PARAMÈTRES CONFIGURABLES

Aucun seuil numérique arbitraire en v1 — la détection de contradiction est une égalité stricte,
la validation du rapport stratégique une comparaison d'ensembles exacte (PRD §9).

## 7. PÉRIMÈTRE V1 vs GATED/T3

### 7.1 En périmètre v1 (mode ombre, prouvable en CI Python)

| Élément | Fichier(s) responsable(s) |
|---|---|
| Contrats gelés, validation d'entrée | `contrats.py`, `validation.py` |
| Registre append-only hash-chaîné | `registre.py`, `encodage.py` |
| Business State Graph, détection de contradiction | `etat_consolide.py` |
| Validation structurelle du rapport stratégique | `rapport_strategique.py` |
| Conformité statique (anti-invention, anti-import, déterminisme) | `conformite.py` |

**Stack technique** : stdlib Python + PyYAML, zéro réseau, zéro horloge interne, zéro LLM.

### 7.2 Repoussé GATED/T3

| Élément | Raison du report |
|---|---|
| Council d'agents réel, Strategic Supervisor | Nécessite de vrais appels LLM ; choix prudent, entièrement GATED même pour la mécanique de séquencement (PRD §0) |
| Scénarios narratifs, playbooks, Decision Intelligence Engine, Action Orchestrator | Contenu délibératif, dépend du Council |
| LangGraph/Temporal/Langfuse/Ragas/DeepEval réels | Hors stdlib, story GATED tracée (patron DuckDB M8) |
| Rythme exécutif (War Room, rapports, board memo) | Nécessite un ordonnanceur externe |
| Notification Nathan, Approval Engine unifié réel | Infra/service central pas encore construits |
| Détection de contradiction sémantique inter-modules | Nécessite un mapping métier hors périmètre v1 |
| Validation du CONTENU de `memoire_m10` | Dépend de la construction de M10 |

## 8. RISQUES MESURÉS DANS LE CODE LU (vigilance requise en implémentation et en revue)

1. `RegistreSnapshots` de M8 (`registre.py:8-64`) calcule `hash_maillon` sur les 4 champs
   `index, module_source, horodatage, valeurs` PLUS `hash_precedent` — la copie-adaptation de M9
   doit reproduire EXACTEMENT cette liste d'arguments à `encodage.empreinte(...)`, sinon le hash
   ne serait pas comparable au patron mesuré et `valider_chaine` échouerait de façon incohérente.
2. Le premier jet du crew pour `encodage.py` chez M5-S002 avait dévié d'une instruction explicite
   de copie exacte, perdant l'injectivité list/tuple (deux types distincts sérialisés
   identiquement). La spec de dispatch de S002 doit fournir le fichier RÉEL de M8 comme contexte
   et exiger une copie MÉCANIQUE, pas une réécriture « simplifiée ».
3. Le gate de cohérence (`verif_coherence.py`) ne doit PAS reproduire aveuglément le contrôle
   « énuméré fermé avec échappatoire D-032 » des cadrages précédents (M3/M5/M6/M8) : M9 v1 n'a
   aucun tel énuméré (DA-M9-02) — un contrôle qui l'exigerait serait un faux négatif garanti,
   symétrique au gap réel trouvé chez M5-S007 dans l'autre sens.
