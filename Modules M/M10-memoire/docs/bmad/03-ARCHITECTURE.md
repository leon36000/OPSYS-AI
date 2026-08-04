# ARCHITECTURE — MODULE M10 (MÉMOIRE LONG TERME & CONSCIENCE OPÉRATIONNELLE)

## 0. CONSENSUS RATIFIÉ

Décision de fondation prise AVANT ce document, par consultation de l'agent `architecte` (Claude
Opus, subagent natif) sur la question : M10 v1 est-il un paquet produit ou la méthode
elle-même — et si c'est un paquet, comment éviter qu'il soit une coquille cérémonielle qui
duplique un registre pour personne ? **Les affirmations structurantes ont été re-mesurées avant
adoption** (l'avis d'un architecte est un CLAIM, jamais une preuve) :

- **`m4_field_ops/outbox.py:24`** (relu, confirmé) :
  `CONSOMMATEURS_CIBLES = ("M6", "M5", "M2", "M7", "M8", "M10")` — M10 est un consommateur
  **DÉCLARÉ du WCT, sans implémentation**. Le module n'est donc pas construit « pour personne » :
  un contrat mergé et testé l'attend.
- **`grep -rE "^\s*(from|import)\s+core" "Modules M/"` → 0 résultat** (exécuté) : aucun module
  n'importe `core`. Le précédent est déjà écrit dans `M5/docs/bmad/01-BRIEF-ANALYSTE.md`.
- **`.github/workflows/ci.yml`** (relu) : le job `e2e` porte `continue-on-error: true` et c'est
  CE job qui exécute `pytest "core/src/authz/tests"`. Les tests d'`authz` ne sont pas bloquants →
  adosser la frontière Forge/Business à `authz` reposerait sur une garantie non bloquante.
  **NO-GO v1.**
- **`grep -rli "preflight\|postflight" ~/proof-method/` → 0 fichier** (exécuté) : **D-014 est une
  loi déclarée sans exécutant**. Ni le dépôt ni le harnais ne l'implémentent.

**Décision retenue : M10 v1 est le CONSOMMATEUR MANQUANT du WCT et le PRODUCTEUR de la référence
`memoire_m10`** — pas « un event log de plus ». Les deux trous qu'il bouche sont nommés dans du
code déjà mergé (M4 amont, M9 aval). Tout ce qui relève du vecteur, du graphe inféré, de
l'injection de contexte ou de l'application du PREFLIGHT est GATED et tracé.

## 1. PAQUET `m10_memoire` — MODULES INTERNES

Le paquet est autonome, copie-adaptation (#109) — il n'importe **aucun** paquet `mX_*` de domaine,
**ni `core`** (§0, NO-GO mesuré).

| Fichier | Rôle | Story |
|---|---|---|
| `__init__.py` | Identité de paquet — docstring seule, aucune logique (patron #109). | — |
| `contrats.py` | Constantes gelées : `CHAMPS_EVENEMENT_MEMOIRE`, `CHAMPS_DECISION`, `CHAMPS_WCT`, `CHAMPS_REFERENCE_MEMOIRE`, `CONSOMMATEUR_ATTENDU = "M10"`, `STATUT_DECISION`, `STATUT_REVISION` (les deux avec échappatoire D-032). | S001 |
| `validation.py` | Valide événement, décision, WCT ; **foyer UNIQUE du vocabulaire `REJ-*`** de tout le paquet (DA-M10-04, patron DA-M5-03). | S001 |
| `encodage.py` | Copie EXACTE de `m5_financecore/encodage.py` (encodage canonique injectif, préfixage de longueur) — AUCUNE simplification, leçon M5-S002. | S002 |
| `registre.py` | Classe générique `Registre` — copie-adaptation du patron `m5_financecore/registre.py:34-87` (`type_entree`/`ligne_id`/`precedent_ligne_id`, sentinel `None`), **PAS** `RegistreSnapshots` de M8 (DA-M10-01). | S002 |
| `wct.py` | Consommation du Work Completion Trigger : `valider_wct` (`CONSOMMATEUR_ATTENDU`), mémorisation, **garde anti-recalcul du `hash_maillon`** (DA-M10-03). | S003 |
| `decisions.py` | `enregistrer_decision`, `statut_courant` par relecture pure (patron `m5_financecore/approbation.py:22-24`). | S004 |
| `revision.py` | Signalement de révision (deux `ligne_id`), arbitrage consigné, marquage d'obsolescence — **aucune fusion, aucune mutation** (DA-M10-05). | S005 |
| `contexte.py` | Prédicat `contexte_suffisant` + trace du refus au registre ; production et vérification de `ReferenceMemoireM10`. | S005 |
| `conformite.py` | Contrôle statique AST : littéral de coût, anti-import (`mX_*` **et `core`**), 3 familles d'appels interdits, échappatoire D-032 **EXIGÉE**, **garde anti-mutation** (DA-M10-06). | S006 |

Aucun fichier `materiel.py`-équivalent : le point d'écriture unique est `registre.py::ajouter`,
tous les autres modules passent par lui.

## 2. SCHÉMAS DE DONNÉES

### 2.1 Maillon du registre — patron générique M5 (DA-M10-01)

```yaml
MaillonMemoire:
  ligne_id: str                    # empreinte(entree_sans_ids, precedent) — patron M5 exact
  precedent_ligne_id: str | None   # None au PREMIER maillon (sentinel M5, PAS "" comme M8)
  type_entree: str                 # evenement_memorise | decision_enregistree | revision_signalee
  horodatage: str                  # fourni par l'appelant, ISO 8601 avec fuseau (validé)
  <champs du contenu>              # à plat, selon type_entree
  hash_maillon: str
```

Note : le patron M5 valide l'horodatage (fuseau obligatoire) et REFUSE un `type_entree` inconnu
en levant `ValueError` — comportement copié tel quel (`m5_financecore/registre.py:34-52`).

### 2.2 Entrée — Work Completion Trigger (12 champs gelés par M4, reçus tels quels)

```yaml
WorkCompletionTriggerV1:
  wct_id · intervention_id · lead_id · technicien_id · horodatage_completion
  fix_gps_completion · duree_reelle_minutes · ecart_signale · revue_id
  hash_maillon              # preuve de M4 — JAMAIS recalculée (DA-M10-03)
  consommateurs_cibles      # doit contenir "M10"
  devis_id
```

### 2.3 Entrées de contenu

```yaml
EvenementMemoire:   evenement · resume · preuves · impact · prochaine_action
DecisionMemorisee:  decision_id · raison (non vide) · statut ∈ STATUT_DECISION · options_ecartees
```

### 2.4 Sortie — `ReferenceMemoireM10` (celle que M9 attend)

```yaml
ReferenceMemoireM10:
  ligne_id: str
  registre: str      # "forge" | "business"
  hash_tete: str     # empreinte de la chaîne au moment de l'écriture
```

### 2.5 Énumérés fermés — DEUX, avec échappatoire D-032 OBLIGATOIRE

```python
STATUT_DECISION = ("proposee", "validee", "remplacee", "annulee", "indetermine")
STATUT_REVISION = ("en_attente", "distincts_confirmes", "obsolete_marquee", "indetermine")
```

**Aucune valeur `fusionnes` n'existe** — par conception (DA-M10-05), pas par oubli.

Contrairement à M9 (DA-M9-02 : aucun énuméré, absence documentée), M10 a de VRAIS énumérés de
domaine : le gate de cohérence et `conformite.py` doivent **EXIGER** l'échappatoire, et surtout
**ne pas copier `M9/docs/bmad/verif_coherence.py`** dont `check_absence_enum_documentee` exige
l'ABSENCE d'énuméré — appliqué ici, ce serait un faux négatif garanti (§8.1).

## 3. INTERFACES ET CONTRATS

### 3.1 Ce que M10 reçoit

Un WCT émis par M4 (jamais construit par M10) ; des événements, décisions et signalements fournis
par l'appelant ; un horodatage à chaque écriture ; **le registre cible en argument** (Forge ou
Business — M10 ne décide jamais de la visibilité, patron `m8_analytics/rapports.py` où
l'autorisation est fournie par l'appelant).

### 3.2 Ce que M10 émet

Des `MaillonMemoire` (via le point d'écriture unique) et des `ReferenceMemoireM10` vérifiables
par relecture — c'est le contrat que M9 pourra enfin valider.

### 3.3 État interne faisant autorité

La chaîne append-only est la source de vérité unique. Le statut courant d'une décision et l'état
d'une révision sont des **dérivations pures** de cette chaîne, jamais des champs positionnables
(même discipline que DA-M5-01/DA-M6-09/DA-M8).

## 4. DÉCISIONS D'ARCHITECTURE TRANCHÉES

### DA-M10-01 — Classe `Registre` générique (patron M5), PAS `RegistreSnapshots` (patron M8/M9)

**Décision** : M10 copie-adapte `m5_financecore/registre.py` (`type_entree`/`ligne_id`/
`precedent_ligne_id`, sentinel `None` au premier maillon).

**Justification** : le critère est déjà écrit en `M9/03-ARCHITECTURE.md` §4 (DA-M9-01) — la classe
générique se justifie quand un module a **PLUSIEURS familles de maillons**. M10 en a trois
(`evenement_memorise`, `decision_enregistree`, `revision_signalee`), là où M8 et M9 n'en avaient
qu'une. Cette DA est écrite explicitement pour couper court au **mimétisme** : un reviewer qui
appliquerait DA-M9-01 par analogie se tromperait de critère.

### DA-M10-02 — Deux registres DISTINCTS, jamais un champ de permission

**Décision** : `registre_forge` et `registre_business` sont deux instances séparées. Aucune
fonction publique n'accepte les deux en argument. Aucun maillon ne porte de champ de permission.

**Justification** : dans un registre append-only, un maillon mal classé est **indélébile** —
raisonnement déjà tenu dans `m2_revenue_crm/frontieres.py:8-11` (« un faux négatif indélébile »).
La séparation doit être structurelle (deux chaînes), pas déclarative (un champ). Et `core/authz`
est écarté en v1 par la mesure CI du §0, pas par principe.

### DA-M10-03 — Le consommateur VÉRIFIE le WCT, il ne le RE-SIGNE jamais

**Décision** : `valider_wct` contrôle les 12 champs exacts et la présence de
`CONSOMMATEUR_ATTENDU = "M10"` dans `consommateurs_cibles` ; le `hash_maillon` reçu est mémorisé
tel quel, **jamais recalculé**. Garde statique dédiée dans `conformite.py`.

**Justification** : copie-adaptation directe de `m6_material_control/validation.py:4-19` et de sa
garde `verifier_non_recalcul_hash_wct`. Un consommateur qui reforge la preuve qu'il consomme
détruit la valeur de cette preuve.

### DA-M10-04 — Foyer unique du vocabulaire de verdicts (`validation.py`), patron DA-M5-03

**Décision** : tout verdict nommé (`REJ-*`) du paquet est construit via un constructeur défini
dans `validation.py`, jamais un dict de rejet improvisé localement.

**Justification** : patron établi 3 fois (M8, M5, M9) — évite la dispersion du vocabulaire entre
6 fichiers.

### DA-M10-05 — Réviser n'est JAMAIS fusionner : détecter, signaler, consigner l'arbitrage

**Décision** : une révision produit un **signalement** nommant les deux `ligne_id` concernés, puis
un maillon d'arbitrage. Les maillons d'origine demeurent intacts et distincts. Aucune valeur
`fusionnes` dans `STATUT_REVISION`. Le marquage d'obsolescence écrit un NOUVEAU maillon, jamais
une mutation.

**Justification** : le dépôt a déjà tranché, dans du code mergé —
`m2_revenue_crm/doublons.py:1-8` : « Ce module ne regroupe jamais deux leads : il détecte les
ressemblances, inscrit un signalement […] les seuls états d'arbitrage existants sont `en_attente`
et `distincts_confirmes`. » Une fusion irréversible dans un registre append-only est
structurellement **pire** que le doublon qu'elle prétend corriger. C'est **le piège central de ce
module** : la fiche source emploie le mot « fusion », le dépôt l'interdit — le dépôt gagne.

### DA-M10-06 — Garde anti-mutation : structurelle, pas seulement comportementale

**Décision** : `conformite.py` porte une garde AST NOUVELLE (sans équivalent dans les 9 modules
précédents) vérifiant qu'**aucune méthode `modifier`/`supprimer`/`fusionner` n'existe** sur les
classes de registre du paquet.

**Justification** : la règle 3 (« rien n'est écrasé sans mémoire ») ne se prouve pas seulement par
des tests de comportement — un test ne peut pas prouver l'absence d'une méthode qu'on n'appelle
pas. Le dépôt sait faire ce type de contrôle statique (`m4_field_ops/outbox.py`,
`garde_ecriture_unique`).

### DA-M10-07 — M10 rend le refus CALCULABLE et TRACÉ ; il n'interrompt personne

**Décision** : `contexte_suffisant(dossier)` retourne `(bool, code_verdict)` et écrit l'alerte au
registre si le contexte est insuffisant. M10 ne lève aucune exception d'interruption, ne bloque
aucun appelant.

**Justification** : la règle 2 de la fiche source dit « AUCUN agent ne code sans contexte — sinon
STOP + alerte ». Le STOP est l'affaire d'un **hook de méthode**, pas d'un paquet produit — et ce
hook **n'existe nulle part** (§0, mesure). Écrire « M10 empêche un agent de coder » serait
invérifiable en CI. Le patron du verdict + maillon d'alerte est mesuré :
`m1_front_office/garde_fou.py:307-315`.

### DA-M10-08 — Aucun import de domaine, ni `core`

**Décision** : `m10_memoire` n'importe JAMAIS `m1_front_office`…`m9_strategic_intelligence`, ni
`core.*`. Garde AST dédiée (le patron `PATRON_MODULE_DOMAINE = re.compile(r"^m\d+_")` est étendu
pour couvrir `core`).

**Justification** : #109 pour les modules de domaine ; pour `core`, la raison est la mesure CI du
§0 (tests `authz` non bloquants) — c'est un NO-GO v1 documenté, pas un interdit éternel : un ADR
futur pourra le lever quand `authz` sera couvert par un job bloquant.

### DA-M10-09 — Déterminisme total (zéro horloge, zéro aléa non ensemencé, zéro réseau)

**Décision** : aucun module de M10 n'appelle `time.time`, `datetime.now`/`today`/`utcnow`,
`random` sans graine, `uuid`, `secrets`, `os.urandom`, ni aucune primitive réseau. Tout horodatage
provient de l'appelant (le patron M5 le VALIDE — fuseau obligatoire — sans jamais le produire).

**Justification** : reproductibilité exigée des `ligne_id` et des empreintes de chaîne — garde par
`conformite.py`, copie-adaptation de M3/M5/M6/M8/M9.

## 5. CE QUE CHAQUE STORY PROUVE

| Story | Ce qu'elle prouve | Critères | Tier |
|---|---|---|---|
| **S001** — Contrats, validation, énumérés | Événement valide accepté, invalide rejeté par verdict nommé ; deux énumérés fermés portent leur échappatoire D-032 ; une valeur hors énuméré est rejetée, jamais coercée. | CA-M10-01, 05 | T2 |
| **S002** — Registre générique, deux instances | Chaîne préservée à l'ajout, altération détectée ; Forge et Business sont deux chaînes distinctes qu'aucune fonction ne mêle. | CA-M10-02, 06 | T1 |
| **S003** — Consommation du WCT | WCT avec `"M10"` accepté et mémorisé ; sans `"M10"` ou mal formé, rejeté ; `hash_maillon` jamais recalculé. | CA-M10-03 | T2 |
| **S004** — Décisions | Décision sans raison rejetée ; statut courant TOUJOURS par relecture, jamais un champ positionnable. | CA-M10-04 | T2 |
| **S005** — Révision, contexte, référence | Révision signalée sans fusion ni mutation ; contexte insuffisant = verdict + trace, sans interruption ; référence vérifiable, référence forgée détectée. | CA-M10-07, 08, 09 | T2 |
| **S006** — Conformité statique | Anti-invention, anti-import (`mX_*` et `core`), déterminisme, échappatoire D-032 exigée, **anti-mutation**. | CA-M10-10, 11, 12 | T1 |

## 6. PARAMÈTRES CONFIGURABLES

Aucun seuil numérique arbitraire en v1 — la détection de révision est une comparaison exacte
fournie par l'appelant (jamais un score de similarité), le prédicat de contexte une comparaison
d'ensembles de clés exacte (PRD §9).

## 7. PÉRIMÈTRE V1 vs GATED/T3

### 7.1 En périmètre v1 (mode ombre, prouvable en CI Python)

| Élément | Fichier(s) porteur(s) |
|---|---|
| Contrats gelés, validation, énumérés fermés | `contrats.py`, `validation.py` |
| Registre append-only hash-chaîné, deux instances | `registre.py`, `encodage.py` |
| Consommation du WCT sans recalcul | `wct.py` |
| Décisions : raison obligatoire, statut par relecture | `decisions.py` |
| Révision sans fusion, prédicat de contexte, référence `memoire_m10` | `revision.py`, `contexte.py` |
| Conformité statique (dont anti-mutation) | `conformite.py` |

**Stack technique** : stdlib Python + PyYAML, zéro réseau, zéro horloge interne, zéro LLM, zéro
embedding.

### 7.2 Repoussé GATED/T3

| Élément | Raison du report |
|---|---|
| Vector memory (embeddings, base vectorielle) | `registries/frameworks.yaml` vide + bijection exigée par `structure_lint.py` → build rouge garanti |
| Arêtes de knowledge graph INFÉRÉES | Inférence = jugement ; v1 n'accepte que les arêtes explicites de l'appelant |
| Context injector | Produit un prompt destiné à un LLM |
| Code memory | Aucun appelant produit ; lire l'arbre git n'est pas reproductible en CI |
| Evaluation harness | Hors stdlib (patron M9) |
| **Application du PREFLIGHT/POSTFLIGHT (D-014)** | Loi déclarée SANS EXÉCUTANT (mesuré §0). Prédicat = v1, hook applicatif = hors dépôt produit, story GATED nommée |
| Purge / rétention effective (Loi 25) | Suppression définitive = T3 Nathan |
| Consommation de `core/src/authz/` | NO-GO v1 : job CI `e2e` non bloquant (§0). Levable par ADR futur |
| Fusion réelle de doublons | **Écartée par conception** (DA-M10-05), pas reportée |

## 8. RISQUES MESURÉS DANS LE CODE LU (vigilance requise en implémentation et en revue)

1. **Le gate de cohérence ne doit PAS être copié de M9.**
   `M9/docs/bmad/verif_coherence.py::check_absence_enum_documentee` **exige l'ABSENCE** d'énuméré
   fermé (correct pour M9, DA-M9-02). Appliqué à M10 qui a DEUX vrais énumérés, ce contrôle serait
   un faux négatif garanti — symétrique exact du risque nommé en `M9/03-ARCHITECTURE.md` §8.3. Le
   gate de M10 doit au contraire **EXIGER** l'échappatoire D-032 sur les deux énumérés (patron
   M5/M8).
2. **Le patron de registre à copier est celui de M5, pas celui de M8/M9.** Les deux sont
   incompatibles (`ligne_id`/`precedent_ligne_id`/`type_entree` avec sentinel `None` vs
   `index`/`hash_precedent`/`hash_maillon` avec chaîne vide). Les deux stories les plus récentes
   (M9-S002) ont utilisé le patron M8 — le risque de mimétisme est élevé. La spec de dispatch de
   S002 doit fournir le fichier RÉEL de M5 comme contexte et exiger une copie MÉCANIQUE.
3. **`encodage.py` : copie EXACTE exigée.** Le premier jet du crew pour M5-S002 avait dévié d'une
   instruction explicite de copie exacte, perdant l'injectivité list/tuple. Même consigne ici.
4. **La garde anti-mutation (DA-M10-06) est NOUVELLE** — aucun des 9 modules précédents n'en a
   d'équivalent exact. Elle ne peut donc pas être copiée : elle doit être écrite et surtout
   **prouvée par un témoin RED** (un registre doté d'une méthode `supprimer` doit faire échouer la
   garde), sinon elle ne prouve rien.
5. **`CONSOMMATEURS_CIBLES` de M4 est un contrat gelé dont l'ordre compte** (`outbox.py:23` : « L'ordre
   exact des tuples ci-dessous fait partie du contrat Ratifié »). M10 lit `"M10" in
   consommateurs_cibles` — il ne doit jamais dépendre de la POSITION dans le tuple.
