# PRD — MODULE M10 (MÉMOIRE LONG TERME & CONSCIENCE OPÉRATIONNELLE)

## 0. TRANCHÉ SUR LES POINTS OUVERTS DE L'ANALYSTE

- **§7.1 (patron de registre)** : **patron générique M5** (`type_entree`/`ligne_id`/
  `precedent_ligne_id`), PAS `RegistreSnapshots` de M8. Justification mesurée : le critère de
  DA-M9-01 est « la classe générique se justifie quand un module a PLUSIEURS familles de maillons »
  — M10 en a trois (`evenement_memorise`, `decision_enregistree`, `revision_signalee`), là où M8
  et M9 n'en avaient qu'une. Acté DA-M10-01 pour couper court au mimétisme.
- **§7.2 (combien de registres)** : **deux instances du même type**, `registre_forge` et
  `registre_business`, les trois familles cohabitant dans chacune via `type_entree`. Aucune
  fonction n'accepte les deux registres en argument (DA-M10-02).
- **§7.3 (prédicat « contexte suffisant »)** : liste FERMÉE de 5 champs obligatoires
  (`evenement`, `resume`, `preuves`, `impact`, `prochaine_action`) PLUS au moins une référence de
  décision non vide. Testable, jamais « au jugé ».
- **§7.4 (référence `memoire_m10`)** : dict à 3 clés exactes — `ligne_id`, `registre`
  (`"forge"`/`"business"`), `hash_tete` (empreinte de la chaîne au moment de l'écriture).
  Vérifiable par relecture, jamais un texte libre.
- **§7.5 (D-014 sans exécutant)** : documenté comme écart RÉEL et nommé. v1 code le prédicat et
  trace le refus ; le hook applicatif est une story GATED explicite (§3.2). Prétendre que M10 v1
  « implémente la loi du harnais » est explicitement REFUSÉ.

## 1. PERSONAS

- **M4 Field Ops (consommateur amont, RÉEL et déjà mergé)** : émet un Work Completion Trigger
  dont `consommateurs_cibles` contient `"M10"` (`m4_field_ops/outbox.py:24`) — attend depuis son
  merge un consommateur qui valide sans re-signer.
- **M9 Strategic Intelligence (consommateur aval, RÉEL et déjà mergé)** : porte la clé gelée
  `memoire_m10` dont la validation de contenu est parquée en attente de ce module.
- **Nathan (dirigeant)** : doit pouvoir prouver qu'une décision passée a une raison tracée, et
  qu'aucune vérité n'a été écrasée en silence.
- **Futur agent de développement (consommateur GATED)** : consommera le prédicat « contexte
  suffisant » via un hook, hors périmètre v1.

## 2. PARCOURS PRINCIPAUX

### 2.1 Consommation d'un Work Completion Trigger

M4 émet un WCT. M10 le valide structurellement (12 champs exacts, `"M10"` présent dans
`consommateurs_cibles`) et l'inscrit dans le registre Forge comme événement mémorisé — **sans
jamais recalculer son `hash_maillon`**, qui reste la preuve de M4.

### 2.2 Enregistrement d'une décision avec sa raison

Un appelant fournit une décision (identifiant, raison, statut parmi l'énuméré fermé). M10
l'inscrit dans le registre append-only. Le statut courant d'une décision est TOUJOURS calculé par
relecture de la chaîne — jamais lu depuis un champ positionnable (patron `m5_financecore/
approbation.py::statut_courant`).

### 2.3 Signalement d'une révision — sans jamais fusionner

Deux souvenirs se ressemblent, ou une vérité devient obsolète. M10 inscrit un **signalement**
nommant les deux `ligne_id` concernés, et consigne ensuite l'arbitrage humain. Les deux maillons
d'origine demeurent intacts et distincts. Aucune fusion, aucune suppression, aucune mutation.

### 2.4 Calcul du prédicat « contexte suffisant » et trace du refus

Un appelant soumet un dossier de contexte. M10 retourne un verdict `(bool, code)` et, si le
contexte est insuffisant, **écrit l'alerte au registre** — puis rend la main. M10 n'interrompt
rien : l'application est un hook GATED.

### 2.5 Production de la référence `memoire_m10`

Après écriture, M10 produit la référence vérifiable (`ligne_id`, `registre`, `hash_tete`) que M9
pourra valider contre le registre réel.

## 3. PÉRIMÈTRE V1 vs ROADMAP

### 3.1 En périmètre v1 (mode ombre, prouvable en CI Python, stdlib pur)

| Élément | Statut |
|---|---|
| Contrats gelés (WCT reçu, événement, décision, référence `memoire_m10`) + validation d'entrée | v1 |
| Registre append-only hash-chaîné générique, deux instances (Forge / Business) | v1 |
| Consommation du WCT sans recalcul de hash (le consommateur manquant de M4) | v1 |
| Registre de décisions : raison obligatoire, statut par relecture, énuméré fermé + échappatoire D-032 | v1 |
| Révision : signalement + arbitrage, jamais fusion ni mutation | v1 |
| Prédicat « contexte suffisant » + trace du refus au registre | v1 |
| Référence `memoire_m10` vérifiable par relecture | v1 |
| Conformité statique transversale (anti-invention, anti-import, déterminisme, **anti-mutation**) | v1 |

### 3.2 Repoussé GATED/T3

| Élément | Raison du report |
|---|---|
| Vector memory (embeddings, base vectorielle) | Hors stdlib ; `registries/frameworks.yaml` est vide et `structure_lint.py` exige la bijection registre↔disque → build rouge garanti |
| Arêtes de knowledge graph INFÉRÉES | Inférence = jugement, hors périmètre déterministe (v1 n'accepte que les arêtes explicites de l'appelant) |
| Context injector (production d'un prompt) | Destiné à un LLM, hors périmètre |
| Code memory | Aucun appelant produit ; lire l'arbre git n'est pas reproductible en CI |
| Evaluation harness | Hors stdlib (patron M9) |
| **Application du PREFLIGHT/POSTFLIGHT (D-014)** | Loi déclarée sans exécutant (mesuré : 0 occurrence dans `~/proof-method` et dans les scripts du dépôt). Le prédicat est v1 ; le hook applicatif vit hors dépôt produit — story GATED nommée |
| Purge / rétention effective (Loi 25) | Suppression définitive = frontière T3 Nathan |
| Consommation de `core/src/authz/` | NO-GO v1 mesuré : le job CI qui teste `authz` porte `continue-on-error: true` — une frontière de confidentialité ne peut pas reposer sur une garantie non bloquante |
| **Fusion réelle de doublons** | **Écartée par conception, pas reportée** — une fusion est irréversible dans un registre append-only |

## 4. ÉNUMÉRÉS FERMÉS

Contrairement à M9 (qui n'en avait aucun, DA-M9-02), **M10 possède de VRAIS énumérés de domaine**,
chacun avec son échappatoire D-032 obligatoire :

```python
STATUT_DECISION = ("proposee", "validee", "remplacee", "annulee", "indetermine")
#                                                                  ^^^^^^^^^^^^ échappatoire D-032

STATUT_REVISION = ("en_attente", "distincts_confirmes", "obsolete_marquee", "indetermine")
#                                                                            ^^^^^^^^^^^^ échappatoire D-032
```

`STATUT_DECISION` reprend les quatre statuts de la règle 4 de la fiche source. `STATUT_REVISION`
reprend le vocabulaire mesuré de `m2_revenue_crm/doublons.py` (`en_attente`,
`distincts_confirmes`) étendu au marquage d'obsolescence — **aucune valeur `fusionnes` n'existe**,
par conception (CA-M10-08).

L'échappatoire `indetermine` est une valeur EXPLICITEMENT choisie par l'appelant, jamais une
coercition automatique : une valeur hors énuméré reste un rejet nommé (leçon M5-S001, où
l'ambiguïté du libellé avait causé un REJECT 3/3 unanime).

## 5. CONTRATS GELÉS

### 5.1 Entrée — Work Completion Trigger (forme gelée par M4, reçue telle quelle)

```yaml
WorkCompletionTriggerV1:   # 12 champs EXACTS, ni plus ni moins
  wct_id: str
  intervention_id: str
  lead_id: str
  technicien_id: str
  horodatage_completion: str
  fix_gps_completion: dict
  duree_reelle_minutes: int
  ecart_signale: bool
  revue_id: str
  hash_maillon: str          # preuve de M4 — JAMAIS recalculée par M10
  consommateurs_cibles: tuple # doit contenir "M10"
  devis_id: str
```

### 5.2 Entrée — `EvenementMemoire` (règle 1 : trace complète)

```yaml
EvenementMemoire:
  evenement: str          # ce qui s'est produit
  resume: str             # synthèse
  preuves: str            # référence de preuve
  impact: str             # conséquence constatée
  prochaine_action: str   # suite prévue
```

### 5.3 Entrée — `DecisionMemorisee` (règle 4 : toute décision a une raison)

```yaml
DecisionMemorisee:
  decision_id: str
  raison: str             # obligatoire, non vide — c'est la règle
  statut: str             # dans STATUT_DECISION
  options_ecartees: str   # ce qui n'a pas été retenu
```

### 5.4 Maillon du registre — patron générique M5 (DA-M10-01)

```yaml
MaillonMemoire:
  ligne_id: str
  precedent_ligne_id: str | None   # None au premier maillon (sentinel M5, PAS chaîne vide M8)
  type_entree: str                  # evenement_memorise | decision_enregistree | revision_signalee
  contenu: dict
  horodatage: str                   # fourni par l'appelant — M10 n'a pas d'horloge
  hash_maillon: str
```

### 5.5 Sortie — `ReferenceMemoireM10` (celle que M9 attend, §7.4 tranché)

```yaml
ReferenceMemoireM10:
  ligne_id: str
  registre: str        # "forge" | "business"
  hash_tete: str       # empreinte de la chaîne au moment de l'écriture
```

### 5.6 Contrat — `CHAMPS_DOSSIER_CONTEXTE` (§7.3 tranché)

Un dossier de contexte est SUFFISANT si et seulement si il porte exactement les 5 champs de
`EvenementMemoire` (§5.2) ET au moins une référence de décision non vide. Toute autre forme est un
refus nommé, tracé au registre.

## 6. CRITÈRES D'ACCEPTATION

- **CA-M10-01** : un `EvenementMemoire` structurellement valide est accepté ; un événement
  invalide est rejeté par un verdict nommé et distinct par catégorie de défaut.
- **CA-M10-02** : le registre de mémoire est append-only et hash-chaîné (patron générique M5,
  `type_entree`/`ligne_id`/`precedent_ligne_id`) ; toute altération d'un maillon est détectée à la
  re-validation.
- **CA-M10-03** : un Work Completion Trigger portant `"M10"` dans `consommateurs_cibles` est
  accepté et mémorisé ; un WCT sans `"M10"`, ou aux champs non conformes, est rejeté par un
  verdict nommé — et le `hash_maillon` du WCT n'est **JAMAIS** recalculé par M10.
- **CA-M10-04** : une décision sans raison non vide est rejetée ; le statut courant d'une décision
  est TOUJOURS calculé par relecture de la chaîne, jamais lu depuis un champ positionnable.
- **CA-M10-05** : `STATUT_DECISION` et `STATUT_REVISION` sont des énumérés fermés portant chacun
  l'échappatoire D-032 `indetermine` ; une valeur hors énuméré est un rejet nommé, jamais une
  coercition silencieuse vers l'échappatoire.
- **CA-M10-06** : les registres Forge et Business sont deux instances DISTINCTES ; aucune fonction
  publique n'accepte les deux en argument, et aucun maillon ne porte de champ de permission.
- **CA-M10-07** : un dossier de contexte incomplet produit un verdict de refus nommé ET une trace
  écrite au registre ; M10 ne lève aucune exception d'interruption et ne bloque aucun appelant.
- **CA-M10-08** : une révision signalée nomme les deux `ligne_id` concernés et consigne
  l'arbitrage ; **aucune fusion, aucune suppression, aucune mutation d'un maillon existant n'est
  possible** — garde structurelle, pas seulement comportementale.
- **CA-M10-09** : une `ReferenceMemoireM10` désigne un maillon réellement écrit et est vérifiable
  par relecture du registre ; une référence forgée est détectée.
- **CA-M10-10** : aucun chiffre, revenu ou capacité n'est codé en dur en Python — garde AST
  transversale (patron `conformite.py::LITTERAL_COUT_INTERDIT`).
- **CA-M10-11** : aucune fonction de M10 n'importe un paquet `mX_*` de domaine ni `core` — garde
  structurelle.
- **CA-M10-12** : aucun appel `random` non ensemencé, horloge, ni réseau dans tout le paquet ; et
  aucune méthode de mutation (`modifier`/`supprimer`/`fusionner`) n'existe sur les registres —
  garde AST.

Les 12 critères sont en séquence complète, chacun porté par exactement une story.

## 7. STORIES

Six stories. Périmètre plus large que M9 (5 stories) car M10 porte deux registres, trois familles
de maillons et un consommateur inter-module réel ; plus étroit que M5 (7) car aucun calcul
métier.

### S001 — Contrats gelés, validation d'entrée, énumérés fermés

| Attribut | Valeur |
|---|---|
| **Périmètre** | `CHAMPS_EVENEMENT_MEMOIRE`, `CHAMPS_DECISION`, `CHAMPS_WCT`, `CHAMPS_REFERENCE_MEMOIRE`, `STATUT_DECISION`, `STATUT_REVISION` (avec échappatoire D-032), validation structurelle d'un événement, verdicts de rejet nommés. Foyer UNIQUE du vocabulaire `REJ-*` (patron DA-M5-03). |
| **Critères portés** | CA-M10-01, CA-M10-05 |
| **Tier** | T2 (contrat d'entrée transversal + énumérés fermés — le point qui a causé un REJECT 3/3 sur M5-S001) |
| **Dépendances** | Aucune |
| **Estimation (D-044)** | ~45 min (cible ≤1h) |

### S002 — Registre append-only hash-chaîné générique, deux instances

| Attribut | Valeur |
|---|---|
| **Périmètre** | Copie-adaptation du patron générique `m5_financecore/registre.py` (classe `Registre`, `type_entree`/`ligne_id`/`precedent_ligne_id`, sentinel `None`), `encodage.py` copie EXACTE, deux instances distinctes Forge/Business. |
| **Critères portés** | CA-M10-02, CA-M10-06 |
| **Tier** | T1 (patron 6 fois prouvé) |
| **Dépendances** | S001 |
| **Estimation (D-044)** | ~40 min |

### S003 — Consommation du Work Completion Trigger (le consommateur manquant de M4)

| Attribut | Valeur |
|---|---|
| **Périmètre** | `valider_wct` avec `CONSOMMATEUR_ATTENDU = "M10"` (copie-adaptation de `m6_material_control/validation.py:4-19`), mémorisation du WCT comme événement, garde anti-recalcul du `hash_maillon`. |
| **Critères portés** | CA-M10-03 |
| **Tier** | **T2** (frontière inter-module réelle — M4 a gelé ce contrat dans du code mergé et testé) |
| **Dépendances** | S001, S002 |
| **Estimation (D-044)** | ~45 min |

### S004 — Registre de décisions : raison obligatoire, statut par relecture

| Attribut | Valeur |
|---|---|
| **Périmètre** | `enregistrer_decision`, `statut_courant` par relecture pure de la chaîne (patron `m5_financecore/approbation.py`), rejet d'une décision sans raison non vide. |
| **Critères portés** | CA-M10-04 |
| **Tier** | **T2** (le statut d'une décision ne doit JAMAIS être un champ positionnable — l'erreur exacte invalidée par l'architecte sur M5) |
| **Dépendances** | S001, S002 |
| **Estimation (D-044)** | ~45 min |

### S005 — Révision sans fusion, prédicat de contexte, référence `memoire_m10`

| Attribut | Valeur |
|---|---|
| **Périmètre** | Signalement de révision nommant deux `ligne_id` + arbitrage consigné (jamais fusion) ; prédicat `contexte_suffisant` + trace du refus ; production et vérification de `ReferenceMemoireM10`. |
| **Critères portés** | CA-M10-07, CA-M10-08, CA-M10-09 |
| **Tier** | **T2** (porte le piège central du module : réviser ≠ fusionner) |
| **Dépendances** | S001, S002, S004 |
| **Estimation (D-044)** | ~50 min (cible ≤1h) |

### S006 — Conformité statique transversale

| Attribut | Valeur |
|---|---|
| **Périmètre** | Copie-adaptation de `conformite.py` : garde littéral de coût, anti-import de domaine **ET de `core`**, 3 familles d'appels interdits, échappatoire D-032 EXIGÉE sur les deux énumérés (contrairement à M9), **garde anti-mutation** (aucune méthode `modifier`/`supprimer`/`fusionner` sur les registres — nouvelle, sans équivalent dans les modules précédents). |
| **Critères portés** | CA-M10-10, CA-M10-11, CA-M10-12 |
| **Tier** | T1 (patron mesuré 5 fois — mais la garde anti-mutation est nouvelle) |
| **Dépendances** | S001, S002, S003, S004, S005 |
| **Estimation (D-044)** | ~50 min |

## 8. DÉCISIONS TRANSVERSALES APPLICABLES

#109 (copie-adaptation, jamais d'import inter-modules — étendu ici à `core`, §2.3 du brief) ;
R-020 (constat neutre, jamais d'accusation — transposé une 5e fois aux signalements de révision) ;
D-032 (échappatoire obligatoire sur tout énuméré fermé — s'applique pleinement ici, contrairement
à M9) ; D-014 (contrat gelé, dont l'APPLICATION est reconnue comme non implémentée, §3.2) ;
D-044 (cible ≤1h par story, découpage obligatoire au-delà de 3h).

## 9. PARAMÈTRES CONFIGURABLES

Aucun seuil numérique arbitraire en v1 : la détection de révision est une comparaison exacte
fournie par l'appelant, jamais un seuil de similarité devinable ; le prédicat de contexte est une
comparaison d'ensembles de clés exacte, jamais un score.

## 10. FRONTIÈRES RATIFIÉES (rappel)

M10 ne fusionne jamais, ne supprime jamais, ne mute jamais un maillon existant ; n'interrompt
jamais un agent ; n'invoque jamais un LLM ; ne calcule aucun embedding ; n'infère aucune arête ;
ne purge jamais (T3) ; ne recalcule jamais le hash d'un WCT ; n'importe ni `mX_*` ni `core`.
