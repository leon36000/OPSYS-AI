# PRD — MODULE M5 (FINANCECORE)

## 0. TRANCHÉ SUR LES POINTS OUVERTS DE L'ANALYSTE

- **§7.1 (CFO Decision Report)** : M5 v1 produit l'**état financier** — la primitive factuelle
  (solde, argent disponible, taux utilisés, référence déterministe). Le « CFO Decision Report » à
  25 points, qui interprète et priorise, est un livrable **M9** qui consommera cet état financier —
  même relation que M7.11/M8 pour le MMM. M5 ne construit aucune interprétation ni priorisation.
- **§7.2 (forme du mouvement)** : v1 reste PLAT — un mouvement porte un montant, un type, un
  horodatage, une classe de rétention, une source — aucun plan comptable multi-niveaux en v1.
- **§7.3 (échelle F0-F7)** : énuméré fermé ordonné à 8 valeurs, **caller-spécifié** (celui qui crée
  une demande choisit son palier ; ce n'est pas une classification inférée par M5, donc pas
  d'échappatoire D-032 sur cet énuméré précis — voir §4 pour l'énuméré qui EN a besoin). Règle
  structurelle uniforme, plus simple que la proposition initiale de l'analyste (pas de F0
  spécial auto-approuvé — non justifié par la fiche source) : **F0-F5** exigent un `approbateur`
  non vide pour atteindre `APPROUVE` ; **F6-F7** exigent EN PLUS une `preuve` non vide (MFA pour
  F6, mention CPA pour F7).
- **§7.4 (déclaration des taux fiscaux)** : fichier dédié
  `Modules M/M5-financecore/contracts/taux_fiscaux.v1.yaml` (pas `metrics/*.yaml` — un taux fiscal
  est une donnée réglementaire versionnée avec une valeur numérique directement utilisable, pas une
  métadonnée descriptive textuelle comme `DefinitionMetrique`).
- **§7.5 (obtention des faits amont)** : hors périmètre M5. M5 reçoit un mouvement déjà construit
  par l'appelant (cohérent avec #109 — jamais d'import de `m2_revenue_crm`/`m4_field_ops`/
  `m6_material_control`).

**Correction post-consultation `architecte` (Claude Opus, subagent natif)** — le mécanisme F0-F7
proposé par l'analyste (§7.3 : une « fonction pure » validant une transition sur un
`DemandeApprobation` à `statut` directement positionnable) a été SOUMIS À REVUE avant cadrage
définitif et INVALIDÉ : un appelant pourrait construire `{"statut": "APPROUVE", "approbateur":
None, "preuve": None}` directement, sans jamais passer par la fonction de transition — ce qui
contredirait la promesse du brief §2.4 (« structurellement inatteignable, vérifié mécaniquement »).
Citations vérifiées par lecture directe avant adoption : `m2_revenue_crm/statuts.py:17-23`
(`statut_courant` REJOUE le registre, ne lit jamais un champ stocké) et
`m4_field_ops/etats.py:69-87` (identique, 7 statuts). **Décision retenue : `DemandeApprobation`
est backée par un registre append-only hash-chaîné dédié** (patron M2/M4 exact, pas la « fonction
pure » initialement proposée) — le statut courant est TOUJOURS calculé par relecture de la
chaîne, jamais stocké dans un champ positionnable. Détail complet en architecture (DA-M5-01).

## 1. PERSONAS

- **Nathan (dirigeant, approbateur F6/F7)** : reçoit les demandes d'approbation aux paliers F6
  (argent réel) et F7 (position fiscale) ; veut que le système REFUSE structurellement toute
  approbation à ces paliers sans sa preuve (MFA/mention CPA), jamais une confiance implicite.
- **Rôle financier/admin (état financier complet)** : voit solde, argent disponible, mouvements et
  taux utilisés.
- **Rôle non-financier (terrain, etc.)** : ne voit JAMAIS un solde, un mouvement, ni un taux —
  même verrou que M2/M6/M8, appliqué ici à la source même des coûts.
- **CPA (professionnel externe, futur, hors intégration réelle v1)** : le champ `preuve` d'une
  demande F7 porte sa mention ; v1 ne vérifie pas cryptographiquement une signature CPA réelle,
  seulement la présence structurelle du champ.
- **M9 (futur consommateur, hors périmètre v1)** : consommera l'état financier de M5 comme
  primitive factuelle pour produire le CFO Decision Report — contrat stable requis, pas un format
  ad hoc.

## 2. PARCOURS PRINCIPAUX

### 2.1 Enregistrement d'un mouvement financier

Un appelant fournit un mouvement `{montant, type_mouvement, horodatage, classe_retention, source}`.
M5 valide sa structure (montant numérique, type_mouvement soit une valeur connue soit `AUTRE`,
classe_retention connue) — un mouvement structurellement invalide est rejeté par un verdict nommé,
jamais accepté avec une valeur devinée. Le mouvement validé est ajouté au registre append-only,
haché.

### 2.2 Calcul de l'état financier — solde vs argent disponible

Une fonction pure relit le registre et calcule le SOLDE (somme signée de tous les mouvements) et
l'ARGENT DISPONIBLE (solde moins la somme de TOUS les mouvements `PROVISION` du registre — v1
sans notion de provision « active » ou expirée, voir CA-M5-06) — deux champs distincts, jamais un
seul nombre réutilisé sous deux noms (contrainte non négociable §2.1 du brief).

### 2.3 Déclaration et utilisation d'un taux fiscal

Un taux fiscal est déclaré dans un fichier versionné et sourcé. Une fonction qui a besoin d'un
taux le cherche par identifiant ; si l'identifiant n'existe pas dans la déclaration versionnée
courante, le calcul est BLOQUÉ par un verdict nommé — jamais une approximation ou un dernier taux
connu réutilisé silencieusement.

### 2.4 Cycle de vie d'une demande d'approbation F0-F7

Une demande est créée à un palier F0-F7 avec une action décrite — un maillon `demande_creee` est
ajouté au registre d'approbation dédié, statut `EN_ATTENTE`. Sa transition vers `APPROUVE` exige
un `approbateur` non vide (tous paliers) et, SEULEMENT si le palier est F6 ou F7, une `preuve` non
vide en plus — la transition est REFUSÉE (jamais silencieusement acceptée avec un champ vide) si
ces conditions ne sont pas remplies. Le statut courant d'une demande est TOUJOURS calculé en
relisant la chaîne depuis son maillon `demande_creee` (patron `statut_courant` de M2/M4) — jamais
lu depuis un champ qu'un appelant pourrait positionner directement ; c'est le registre lui-même,
et non un champ mutable, qui fait autorité (correction de conception actée en §0, après
consultation `architecte`).

### 2.5 État financier filtré par rôle

Un état financier destiné à un rôle non autorisé aux coûts ne porte ni solde, ni argent
disponible, ni référence à un mouvement individuel — seulement son identité structurelle
(`type`, `role`, `etat_id`).

## 3. PÉRIMÈTRE V1 vs ROADMAP

### 3.1 En périmètre v1 (mode ombre, prouvable en CI Python, stdlib + PyYAML)

| Élément | Statut |
|---|---|
| Contrats gelés + validation du mouvement financier (énuméré `TypeMouvement` + échappatoire `AUTRE`) | v1 |
| Registre append-only hash-chaîné des mouvements | v1 |
| Calcul solde vs argent disponible (deux champs distincts) | v1 |
| Déclaration et validation de taux fiscaux versionnés+sourcés ; blocage nommé si absent | v1 |
| Registre d'approbation F0-F7 hash-chaîné, statut par relecture, garde F6/F7 (approbateur+preuve) | v1 |
| Classification par classe de rétention (`FISCALE_6_ANS`/`STANDARD`) sur chaque mouvement | v1 |
| État financier déterministe (`etat_id`, patron `roi_engine.py`), filtré par rôle | v1 |
| Conformité statique transversale (AST) : taux codé en dur, échappatoire, imports de domaine | v1 |

### 3.2 Repoussé GATED/T3

| Élément | Raison du report |
|---|---|
| Adapters réels (banque, paie, comptable) | Progression obligatoire read-only → dry-run → write gated (fiche source) ; chacun une story GATED distincte |
| Agent RAG fiscal conversationnel | Hors périmètre déterministe — dépend de D-029/D-031, construit ailleurs, comme le LLM narrateur M8 |
| Forecast 5 ans | R-009 : historique encore insuffisant pour une projection honnête ; seuil `n` minimal futur, patron XmR M8 |
| CFO Decision Report (25 points) complet | Livrable M9, qui consomme l'état financier M5 (tranché §0) |
| Vérification cryptographique réelle MFA/CPA | Intégration Zitadel (P0-9b) — infra hors périmètre du module de domaine |
| Approval Engine central du core | Service pas encore construit comme unifié (brief §2.5) ; migration future, ADR distinct |
| Les 20 sous-départements dans leur richesse complète | v1 = socle commun (registre, soldes, taux, F0-F7, conformité) |

## 4. ÉNUMÉRÉS FERMÉS

### 4.1 `TypeMouvement`

| Valeur | Condition d'obtention |
|---|---|
| `ENCAISSEMENT` | Entrée d'argent (ex. paiement client reçu). |
| `DECAISSEMENT` | Sortie d'argent (ex. paiement fournisseur). |
| `PROVISION` | Réservation d'argent disponible sans mouvement de solde réel (ex. provision fiscale). |
| `AJUSTEMENT` | Correction d'un mouvement antérieur, jamais une réécriture du mouvement original (append-only). |
| `AUTRE` | **Échappatoire D-032** (nom domaine-spécifique, patron `TYPES_TRAVAUX`/`"autre"` de M3) — CHOISIE EXPLICITEMENT par l'appelant quand le mouvement est réel et daté mais que sa nature ne correspond à aucune des quatre catégories ci-dessus. Soumise ainsi, `AUTRE` n'est jamais un rejet. Une valeur qui n'est NI l'une des quatre catégories NI `AUTRE` reste, elle, un rejet nommé (`REJ-MOUVEMENT-TYPE-INCONNU`) — l'échappatoire n'est pas une correction automatique d'une entrée invalide (voir CA-M5-04). |

### 4.2 `PalierApprobation` (F0-F7, caller-spécifié — pas d'échappatoire, voir §0/§7.3)

Ordonné F0 < F1 < ... < F7. F6 = argent réel (Nathan+MFA). F7 = position fiscale (Nathan+CPA,
mention professionnelle REG-10). Un palier hors de cet ensemble est un rejet nommé à la création
de la demande, jamais une valeur par défaut.

### 4.3 `StatutApprobation`

| Valeur | Condition d'obtention |
|---|---|
| `EN_ATTENTE` | État initial de toute demande créée. |
| `APPROUVE` | Conditions du palier remplies (§0/§7.3) — jamais atteint sinon. |
| `REFUSE` | Décision explicite de refus ; état terminal comme `APPROUVE`. |

### 4.4 `ClasseRetention`

| Valeur | Condition d'obtention |
|---|---|
| `FISCALE_6_ANS` | Mouvement soumis à la rétention fiscale légale (Revenu Québec). |
| `STANDARD` | Toute autre donnée financière, soumise à la minimisation Loi 25 par défaut. |

Fournie par l'appelant à chaque mouvement — jamais dérivée devinée par M5 (le module source connaît
la nature fiscale ou non de ce qu'il rapporte).

## 5. CONTRATS GELÉS

### 5.1 Entrée — `MouvementFinancier`

```yaml
MouvementFinancier:
  montant: float            # signé : positif = encaissement, négatif = décaissement (convention gelée ici)
  type_mouvement: str       # enum TypeMouvement
  horodatage: str           # fourni par l'appelant, reproduit tel quel — M5 n'a pas d'horloge
  classe_retention: str     # enum ClasseRetention
  source: str               # module/action à l'origine (texte libre, ex. "m4_field_ops:intervention:INT-042")
```

### 5.2 Maillon du registre append-only — `MaillonMouvement`

```yaml
MaillonMouvement:
  index: int
  montant: float
  type_mouvement: str
  horodatage: str
  classe_retention: str
  source: str
  hash_precedent: str
  hash_maillon: str
```

### 5.3 Déclaration — `TauxFiscal` (fichier versionné, `contracts/taux_fiscaux.v1.yaml`)

```yaml
TauxFiscal:
  id: str          # ex. "tps_qc"
  nom: str
  taux: float       # ex. 0.05 — valeur numérique directement utilisable (contrairement aux
                    # métriques M7/M8, un taux fiscal EST le nombre du domaine, pas une métadonnée)
  version: str
  source: str       # citation légale/réglementaire, texte libre
```

Un identifiant demandé mais absent de la déclaration versionnée courante bloque le calcul
(verdict nommé) — jamais un taux de remplacement deviné.

### 5.4 `MaillonApprobation` (registre append-only dédié — patron M2/M4, PAS un dict positionnable)

`DemandeApprobation` n'est PAS une structure mutable : c'est une SÉQUENCE de maillons hash-chaînés
partageant un `demande_id`, le statut courant se calculant par relecture (patron exact de
`statut_courant` chez M2/M4). Un maillon `demande_creee` (statut initial `EN_ATTENTE`) précède
zéro ou un maillon `transition_approbation` (statut terminal `APPROUVE` ou `REFUSE`).

```yaml
MaillonApprobation:
  index: int
  type_entree: str        # "demande_creee" | "transition_approbation"
  demande_id: str
  palier: str              # enum PalierApprobation (F0-F7), fixé à la création, jamais réécrit
  action: str               # description libre, fixée à la création
  statut: str               # enum StatutApprobation
  approbateur: str | null    # requis (non vide) pour toute transition vers APPROUVE, tous paliers
  preuve: str | null         # requis (non vide) EN PLUS pour APPROUVE, SEULEMENT si palier ∈ {F6, F7}
  horodatage: str
  hash_precedent: str
  hash_maillon: str
```

### 5.5 Sortie — `EtatFinancier`

```yaml
EtatFinancier:
  type: str                     # toujours "ETAT_FINANCIER"
  role: str | null               # null = non filtré (vue complète)
  solde: float | null             # null SSI rôle non autorisé aux coûts
  argent_disponible: float | null # null SSI rôle non autorisé aux coûts
  taux_utilises: list             # [{id, version}], vide si non autorisé aux coûts
  etat_id: str                    # sha256 déterministe du contenu (patron roi_engine.py)
```

## 6. CRITÈRES D'ACCEPTATION

- **CA-M5-01** : un mouvement financier structurellement valide (montant numérique,
  `type_mouvement` connu ou `AUTRE`, `classe_retention` connue) est accepté ; un mouvement
  structurellement invalide est rejeté par un verdict nommé.
- **CA-M5-02** : le registre append-only des mouvements est hash-chaîné (patron M2/M4/M6/M8) ;
  toute altération d'un maillon est détectée à la re-validation.
- **CA-M5-03** : le registre des demandes d'approbation est hash-chaîné (patron M2/M4 exact) ; le
  statut courant d'une demande est calculé par relecture de la chaîne (`statut_courant`), jamais
  lu depuis un champ positionnable directement par l'appelant ; une altération d'un maillon est
  détectée à la re-validation.
- **CA-M5-04** : `AUTRE` est une valeur EXPLICITEMENT choisie par l'appelant quand un mouvement
  réel ne correspond à aucune des quatre autres catégories (échappatoire D-032, jamais une
  catégorie fabriquée par le système, jamais un plantage) — PAS une valeur de repli que
  `valider_mouvement` appliquerait elle-même à un `type_mouvement` non reconnu. Une valeur hors de
  l'énuméré fermé (ni l'une des quatre catégories, ni `AUTRE` lui-même) reste un rejet nommé
  (`REJ-MOUVEMENT-TYPE-INCONNU`), exactement comme `m3_estimation/validation.py:160-167` rejette
  un `type_travaux` hors de `TYPES_TRAVAUX` (qui inclut pourtant `"autre"`) plutôt que de le
  coercer silencieusement — l'échappatoire est un CHOIX explicite de l'appelant, jamais une
  correction automatique d'une entrée invalide.
- **CA-M5-05** : le solde est la somme signée de tous les mouvements du registre — calcul pur,
  reproductible par re-calcul complet (mêmes mouvements → même solde).
- **CA-M5-06** : l'argent disponible est le solde moins la somme de TOUS les mouvements de type
  `PROVISION` du registre (v1 : aucune libération de provision — une libération future sera un
  maillon `AJUSTEMENT` dédié référençant la provision d'origine par sa source, jamais une
  réécriture du mouvement `PROVISION` original) — champ distinct du solde, jamais confondu dans un
  contrat de sortie.
- **CA-M5-07** : un taux fiscal demandé mais absent de la déclaration versionnée courante bloque
  le calcul par un verdict nommé, jamais une valeur par défaut ou un dernier taux connu réutilisé.
- **CA-M5-08** : une demande d'approbation porte un palier F0-F7 fermé ; un palier hors de cet
  ensemble est rejeté à la création (verdict nommé).
- **CA-M5-09** : une demande de palier F6 ou F7 n'atteint JAMAIS le statut `APPROUVE` sans un
  `approbateur` ET une `preuve` non vides — la transition est refusée sinon (garde testée par
  relecture de chaîne, pas par un champ positionnable — voir CA-M5-03).
- **CA-M5-10** : une demande de palier F0-F5 n'atteint `APPROUVE` qu'avec un `approbateur` non
  vide ; `preuve` n'est jamais exigée à ces paliers.
- **CA-M5-11** : chaque mouvement porte une `classe_retention` fermée (`FISCALE_6_ANS` ou
  `STANDARD`) fournie par l'appelant, jamais dérivée devinée par M5.
- **CA-M5-12** : un état financier destiné à un rôle non autorisé aux coûts ne contient ni solde,
  ni argent disponible, ni taux utilisés — seulement son identité structurelle.
- **CA-M5-13** : `etat_id` d'un état financier est déterministe (mêmes mouvements + mêmes taux
  utilisés + mêmes arguments → mêmes octets), patron `roi_engine.py`/`snapshot_id`.
- **CA-M5-14** : aucun taux fiscal n'est codé en dur en Python — garde AST transversale (patron
  `conformite.py::LITTERAL_COUT_INTERDIT`, étendue aux taux).
- **CA-M5-15** : `TypeMouvement` porte son échappatoire D-032 (`AUTRE`), vérifiée par résolution de
  références — garde AST transversale, patron `conformite.py` de M3/M6/M8.
- **CA-M5-16** : aucune fonction de M5 n'importe un paquet `mX_*` de domaine (garde structurelle,
  patron DA-M8-01/CA-M8-14).
- **CA-M5-17** : aucun appel `random` non ensemencé, horloge, ni réseau dans tout le paquet (garde
  AST, patron `conformite.py` M3/M6/M8).
- **CA-M5-18** : aucun mouvement (y compris `AJUSTEMENT`) ni aucune demande d'approbation ne porte
  de champ `cause`/`responsable`/`raison_signalee` — garde AST transversale (R-020 transposé,
  patron DA-M8-07/CA-M8-10 : un `AJUSTEMENT` est un constat de correction, jamais une désignation
  de faute).

Les 18 critères sont en séquence complète, chacun porté par exactement une story.

## 7. STORIES

Sept stories — un socle transversal (contrats/registre/conformité, patron désormais mesuré quatre
fois) plus les quatre mécaniques propres à M5 (soldes, taux, approbation F0-F7, état filtré).

### S001 — Contrats gelés, validation d'entrée, énuméré `TypeMouvement`

| Attribut | Valeur |
|---|---|
| **Périmètre** | `MouvementFinancier`, `TypeMouvement` (+ échappatoire `AUTRE`), `ClasseRetention`, validation structurelle, verdicts de rejet nommés. |
| **Critères portés** | CA-M5-01, CA-M5-04, CA-M5-11 |
| **Tier** | T2 (contrat d'entrée transversal à tout le module, comme M6-S001/M8-S001) |
| **Dépendances** | Aucune |
| **Estimation (D-044)** | ~45 min (cible ≤1h) |

### S002 — Registre append-only hash-chaîné des mouvements

| Attribut | Valeur |
|---|---|
| **Périmètre** | Copie-adaptation du patron M2/M4/M6/M8 (`encodage.py`/`registre.py`). |
| **Critères portés** | CA-M5-02 |
| **Tier** | T1 |
| **Dépendances** | S001 |
| **Estimation (D-044)** | ~30 min (copie-adaptation mécanique, patron quatre fois prouvé) |

### S003 — Solde et argent disponible

| Attribut | Valeur |
|---|---|
| **Périmètre** | Calcul pur du solde (somme signée) et de l'argent disponible (solde − somme de tous les `PROVISION` du registre, v1 sans libération) à partir du registre — deux champs distincts, jamais confondus. |
| **Critères portés** | CA-M5-05, CA-M5-06 |
| **Tier** | T2 (distinction non négociable nommée par Nathan lui-même — correctness financière centrale, pas une story mécanique comme S002) |
| **Dépendances** | S001, S002 |
| **Estimation (D-044)** | ~40 min (cible ≤1h) |

### S004 — Taux fiscaux versionnés et sourcés

| Attribut | Valeur |
|---|---|
| **Périmètre** | `TauxFiscal` déclaré dans `contracts/taux_fiscaux.v1.yaml`, recherche par identifiant, blocage nommé si absent de la version courante. |
| **Critères portés** | CA-M5-07 |
| **Tier** | T2 (intégrité d'une donnée réglementaire — patron price-book M6, jamais un T1 mécanique) |
| **Dépendances** | S001 |
| **Estimation (D-044)** | ~35 min (cible ≤1h) |

### S005 — Registre d'approbation F0-F7 et garde de transition

| Attribut | Valeur |
|---|---|
| **Périmètre** | `MaillonApprobation` sur registre append-only hash-chaîné DÉDIÉ (patron M2/M4 exact — PAS une fonction pure sur un dict positionnable, correction post-consultation `architecte`, voir PRD §0). Statut courant calculé par relecture de chaîne (`statut_courant`, patron `m2_revenue_crm/statuts.py:17-23`) ; transition vers `APPROUVE` gardée à l'écriture (F0-F5 : approbateur ; F6-F7 : approbateur+preuve). **Consultation `architecte` DÉJÀ FAITE au cadrage** (comme M4-S008) — dispatch crew directement sur ce périmètre corrigé, pas de nouvelle consultation nécessaire à l'implémentation. |
| **Critères portés** | CA-M5-03, CA-M5-08, CA-M5-09, CA-M5-10 |
| **Tier** | T2 (frontière humaine F6/F7 codée en dur dans le registre — la story la plus sensible du module) |
| **Dépendances** | S001, S002 (réutilise le patron `registre.py`/`encodage.py`) |
| **Estimation (D-044)** | ~55 min (cible ≤1h) — mécanisme corrigé en cadrage, pas une pure copie-adaptation ; découpage en deux si le cap de 3h est dépassé (D-044) |

### S006 — État financier déterministe filtré par rôle

| Attribut | Valeur |
|---|---|
| **Périmètre** | `EtatFinancier`, `etat_id` déterministe (patron `roi_engine.py`), filtrage binaire par rôle (autorisé aux coûts ou non — jamais de fuite partielle). |
| **Critères portés** | CA-M5-12, CA-M5-13 |
| **Tier** | T2 (frontière de destinataire, patron M6-S007/M8-S005) |
| **Dépendances** | S001, S002, S003, S004 |
| **Estimation (D-044)** | ~40 min (cible ≤1h) |

### S007 — Conformité statique transversale

| Attribut | Valeur |
|---|---|
| **Périmètre** | Copie-adaptation de `conformite.py` (M3/M6/M8) : échappatoire D-032 sur `TypeMouvement`, garde anti-import de domaine, garde littéral de taux codé en dur, 3 familles d'appels interdits (random/horloge/réseau), garde anti-cause/responsable (R-020, patron M8). |
| **Critères portés** | CA-M5-14, CA-M5-15, CA-M5-16, CA-M5-17, CA-M5-18 |
| **Tier** | T1 (patron désormais mesuré quatre fois — M3/M6/M8, jamais un désaccord de fond en revue) |
| **Dépendances** | S001, S002, S003, S004, S005, S006 |
| **Estimation (D-044)** | ~1h (cible atteinte, pas de marge) — patron mesuré mais périmètre le plus large du module (scanne tout le paquet) ; découpage obligatoire au-delà de 3h (D-044), pas une option. |

## 8. DÉCISIONS TRANSVERSALES APPLICABLES

D-032 (échappatoire nommée obligatoire sur tout énuméré fermé — ici `AUTRE` sur `TypeMouvement`) ;
#109 (copie-adaptation, jamais d'import inter-modules — M5 n'importe aucun paquet `mX_*` de
domaine) ; REG-10 (mention professionnelle fiscale obligatoire — portée par le champ `preuve`
d'une demande F7) ; rétention fiscale 6 ans (Revenu Québec) vs minimisation Loi 25 « par classe »
(portée par `ClasseRetention`) ; patron mesuré `roi_engine.py` (`etat_id`/`snapshot_id` stdlib)
réutilisé tel quel ; D-010 (service Approval Engine central du core, PAS encore construit comme
service unifié — M5 v1 garde son registre d'approbation F0-F7 local, migration future hors
périmètre).

## 9. PARAMÈTRES CONFIGURABLES

Aucun seuil numérique arbitraire en v1 (cohérent avec l'absence de forecast et la discipline
« aucun coût codé en dur ») : l'argent disponible se calcule sur TOUS les mouvements `PROVISION`
réels du registre, sans notion de provision « active » à paramétrer (pas un seuil devinable), et
les taux fiscaux sont des déclarations versionnées (§5.3), jamais une constante ajustable en code.

## 10. FRONTIÈRES RATIFIÉES (rappel)

M5 ne construit aucun adapter réel (banque/paie/comptable — read-only puis dry-run puis write,
chacun GATED), ne construit pas l'agent RAG fiscal conversationnel, ne fabrique aucun forecast en
v1 (R-009), ne produit pas le CFO Decision Report complet (position M9, §0), ne vérifie pas
cryptographiquement une preuve MFA/CPA réelle, et n'importe jamais un paquet `mX_*` de domaine.
