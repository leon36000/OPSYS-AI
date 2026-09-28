# ARCHITECTURE — MODULE M5 (FINANCECORE)

## 0. CONSENSUS RATIFIÉ

Consultation de l'agent `architecte` (Claude Opus, subagent natif) sur trois questions précises,
AVANT tout dispatch crew — le mécanisme F0-F7 proposé par l'analyste touchait une frontière
humaine réelle (F6=Nathan+MFA, F7=Nathan+CPA), donc « dispatch au subagent architecte si structure
touchée » (skill `proof-bmad`) s'applique sans ambiguïté ici. Citations vérifiées par lecture
directe des fichiers cités avant adoption (jamais prises pour argent comptant) :

**Q1 — mécanisme F0-F7 : INVALIDÉ tel que proposé, corrigé.** La proposition initiale (une
« fonction pure » validant une transition sur un `DemandeApprobation` à `statut` directement
positionnable) permettrait à un appelant de construire `{"statut": "APPROUVE", "approbateur":
None, "preuve": None}` directement, sans jamais passer par la fonction de garde — ce qui rendrait
fausse la promesse du brief §2.4 (« structurellement inatteignable, vérifié mécaniquement »).
Vérifié : `m2_revenue_crm/statuts.py:17-23` (`statut_courant` REJOUE le registre par relecture,
ne lit JAMAIS un champ stocké) et `m4_field_ops/etats.py:69-87` (identique, 7 statuts). **Décision
retenue : `MaillonApprobation` est backé par un registre append-only hash-chaîné dédié**, patron
M2/M4 EXACT — le statut courant est TOUJOURS calculé par relecture de la chaîne. Rejet de
l'alternative WCT/outbox (M4-S008) : confirmé correct par l'architecte (`outbox.py:1-9,22-33` =
double-écriture atomique transition+événement vers 6 consommateurs, sans analogue ici — M5 n'a
qu'UN SEUL consommateur de la décision, le maillon d'approbation lui-même).

**Q2 — provisions : hors périmètre v1, confirmé, avec correction de libellé.** Une provision
`PROVISION` n'a pas de cycle de vie « active/consommée » en v1 (append-only interdit de muter un
maillon pour la « libérer ») — direction délibérément CONSERVATRICE (l'argent disponible peut
sous-estimer après un décaissement réel non encore reflété par un ajustement, jamais l'inverse).
Correction actée : CA-M5-06 dit « TOUS les mouvements `PROVISION` du registre », jamais
« provisions actives » (aucun filtre de ce type n'existe) ; la libération future sera un maillon
`AJUSTEMENT` référençant la provision d'origine par sa `source`, jamais une réécriture.

**Q3 — découpage en fichiers : cohérent avec le patron M8, confirmé.** Mapping 1:1 avec M8
(contrats/validation/encodage/registre/conformite identiques dans leur rôle ; `taux_fiscaux.py`
↔ `dictionnaire.py` — déclaration versionnée ; `etat_financier.py` ↔ `rapports.py` — assemblage +
`etat_id` ; `soldes.py` ↔ calcul pur comme `semantique.py`/`xmr.py`). Point d'organisation retenu :
UN SEUL foyer pour le vocabulaire de verdicts nommés (`validation.py`, jamais dispersé entre
`taux_fiscaux.py`/`approbation.py`), et UN SEUL foyer pour le filtrage par rôle (`etat_financier.py`
uniquement, jamais réinventé ailleurs).

## 1. PAQUET `m5_financecore` — MODULES INTERNES

Le paquet est autonome, copie-adaptation (#109) — comme M8, il n'importe **aucun** paquet `mX_*`
de domaine, même en lecture (DA-M5-04) : il ne connaît structurellement aucun module source,
seulement les contrats génériques (`MouvementFinancier`) que l'appelant lui fournit.

| Fichier | Rôle | Story |
|---|---|---|
| `__init__.py` | Identité de paquet — docstring seule, aucune logique (patron #109). | — |
| `contrats.py` | Constantes gelées : champs attendus, `TypeMouvement` (+ échappatoire D-032 `AUTRE`), `ClasseRetention`, `PalierApprobation`, `StatutApprobation`. | S001 |
| `validation.py` | Valide la structure d'un `MouvementFinancier` ; **foyer UNIQUE du vocabulaire `REJ-*`** de tout le paquet (DA-M5-03) — même les rejets propres à `taux_fiscaux.py`/`approbation.py` appellent des constructeurs de verdict définis ici. | S001 |
| `encodage.py` | Copie-adaptation de `m8_analytics/encodage.py` (lui-même adapté de M4/M6) : `encoder_canonique(*valeurs)`, `empreinte(*valeurs)`. Partagé par `registre.py` ET `approbation.py`. | S002 |
| `registre.py` | Classe générique `Registre` (hash-chaîné, append-only, agnostique de la forme du maillon — patron `m4_field_ops/registre.py:41`) ; `enregistrer_mouvement(mouvement, registre)` = fonction de convenance dessus (pas une classe séparée — mesuré à l'implémentation, plus simple que ce qui était initialement esquissé). **Classe `Registre` instanciée une seconde fois par `approbation.py`** (DA-M5-01) — réutilisation INTERNE au paquet, pas un import inter-module (#109 ne s'applique qu'entre paquets `mX_*` distincts). | S002 |
| `soldes.py` | Calcul pur : solde (somme signée des mouvements `ENCAISSEMENT`/`DECAISSEMENT`/`AJUSTEMENT`/`AUTRE` — `PROVISION` EXCLU par sa propre définition « sans mouvement de solde réel », §2.6) et argent disponible (solde − somme des `PROVISION`) à partir d'une relecture du registre de mouvements. | S003 |
| `taux_fiscaux.py` | Charge et valide `contracts/taux_fiscaux.v1.yaml` ; recherche par identifiant ; blocage nommé (verdict de `validation.py`) si absent de la version courante. | S004 |
| `approbation.py` | `RegistreApprobations` (instanciation de la classe générique `registre.Registre`) ; `creer_demande`, `approuver`, `refuser`, `statut_courant` — patron `m2_revenue_crm/statuts.py` EXACT, garde F6/F7 intégrée à `approuver`. | S005 |
| `etat_financier.py` | Assemble `EtatFinancier` (solde, argent disponible, taux utilisés, `etat_id`) ; **foyer UNIQUE du filtrage par rôle** (DA-M5-03) — binaire, jamais une liste fine comme M8. | S006 |
| `conformite.py` | Contrôle statique AST transversal : copie-adaptation de `m8_analytics/conformite.py` + garde littéral de taux + garde anti-cause (R-020). | S007 |

Aucun fichier `materiel.py`/orchestrateur unique équivalent à M6 : M5 a DEUX points d'écriture
distincts (mouvements, approbations), chacun déjà unique par construction (`registre.py::ajouter`
pour les mouvements via `soldes.py`/l'appelant, `approbation.py::creer_demande`/`approuver`/
`refuser` pour les approbations) — une couche supplémentaire n'ajouterait aucune garantie que la
garde AST anti-écriture-hors-fonction-autorisée (DA-M5-01, patron DA-M6-11) n'apporte déjà.

## 2. SCHÉMAS DE DONNÉES

### 2.1 Entrée — `MouvementFinancier`

```yaml
MouvementFinancier:
  montant: Decimal          # signé : positif = encaissement, négatif = décaissement ; construit depuis un texte décimal
  type_mouvement: str        # enum TypeMouvement
  horodatage: str             # fourni par l'appelant — M5 n'a pas d'horloge
  classe_retention: str        # enum ClasseRetention
  source: str                   # module/action à l'origine, texte libre
```

### 2.2 Maillon du registre append-only — `MaillonMouvement`

```yaml
MaillonMouvement:
  montant: Decimal
  type_mouvement: str
  horodatage: str
  classe_retention: str
  source: str
  type_entree: str                 # toujours "mouvement_enregistre"
  ligne_id: str                     # patron m4_field_ops/registre.py — mesuré à
  precedent_ligne_id: str | null     # l'implémentation S002, corrige DA-M5-07 ci-dessous
```

### 2.3 Déclaration — `TauxFiscal` (`contracts/taux_fiscaux.v1.yaml`)

```yaml
TauxFiscal:
  id: str
  nom: str
  taux: float
  version: str
  source: str
```

### 2.4 Maillon du registre d'approbation — `MaillonApprobation` (DA-M5-01)

```yaml
MaillonApprobation:
  type_entree: str          # "demande_creee" | "transition_approbation"
  demande_id: str
  palier: str                 # enum PalierApprobation (F0-F7), fixé à la création
  action: str                  # description libre, fixée à la création
  statut: str                   # enum StatutApprobation
  approbateur: str | null
  preuve: str | null
  horodatage: str
  ligne_id: str
  precedent_ligne_id: str | null
```

### 2.5 Sortie — `EtatFinancier`

```yaml
EtatFinancier:
  type: str                      # toujours "ETAT_FINANCIER"
  role: str | null
  solde: Decimal | null            # null SSI rôle non autorisé aux coûts
  argent_disponible: Decimal | null # null SSI rôle non autorisé aux coûts
  taux_utilises: list               # [{id, version}], vide si non autorisé aux coûts
  etat_id: str
```

### 2.6 Représentation exacte des montants — correction NEW-PROD-003

Les champs `montant`, `solde` et `argent_disponible` utilisent `Decimal` fini. La frontière
`validation.valider_mouvement` refuse `float`, `int`, booléens et valeurs `NaN`/infinies ;
`Registre.ajouter` réapplique cette garde aux maillons `mouvement_enregistre` avant le calcul du
hash et l'écriture dans la chaîne, et soulève `MouvementInvalide` avec le verdict nommé
`REJ-MOUVEMENT-MONTANT-INVALIDE`. `Decimal` est déjà supporté par `encodage.py`, donc le hash
reste déterministe et injectif. La devise et l'échelle fixe sont explicitement différées ; les
taux fiscaux, qui sont des fractions versionnées et non des montants, conservent leur contrat
`float`.

### 2.7 Énumérés fermés (copie mot pour mot du PRD §4)

#### `TypeMouvement`

| Valeur | Condition d'obtention |
|---|---|
| `ENCAISSEMENT` | Entrée d'argent. |
| `DECAISSEMENT` | Sortie d'argent. |
| `PROVISION` | Réservation d'argent disponible sans mouvement de solde réel. |
| `AJUSTEMENT` | Correction d'un mouvement antérieur (jamais une réécriture — append-only). |
| `AUTRE` | **Échappatoire D-032** (patron `TYPES_TRAVAUX`/`"autre"` de M3) — CHOISIE EXPLICITEMENT par l'appelant, mouvement réel et daté, nature hors des quatre catégories ci-dessus. Une valeur qui n'est ni l'une des quatre catégories ni `AUTRE` reste un rejet nommé (`REJ-MOUVEMENT-TYPE-INCONNU`) — patron `m3_estimation/validation.py:160-167`, qui rejette de même un `type_travaux` hors de `TYPES_TRAVAUX` plutôt que de le coercer vers `"autre"`. |

#### `PalierApprobation` — F0 < F1 < ... < F7, caller-spécifié (pas d'échappatoire — voir PRD §0/§7.3)

#### `StatutApprobation` — `EN_ATTENTE` → `APPROUVE` | `REFUSE` (terminaux)

#### `ClasseRetention` — `FISCALE_6_ANS` | `STANDARD`, fournie par l'appelant

## 3. INTERFACES ET CONTRATS

### 3.1 Ce que M5 reçoit de l'appelant (jamais d'un module de domaine directement)

`MouvementFinancier` à chaque enregistrement ; palier + action à chaque création de demande
d'approbation ; approbateur (+ preuve si F6/F7) à chaque décision ; rôle à chaque calcul d'état
financier.

### 3.2 Ce que M5 émet vers les dashboards/Nathan

`EtatFinancier`, filtré ou non selon le rôle demandé. Une demande F6/F7 `EN_ATTENTE` est le
signal qui route vers Nathan (mécanisme de notification hors périmètre M5 — comme le digest de M8
est distribué par M1, le routage d'une demande d'approbation est un service d'intégration
distinct).

### 3.3 Ce que M5 émet vers M9 (futur, hors périmètre v1)

Aucun contrat gelé v1 — M9 consommera `EtatFinancier` pour produire le CFO Decision Report quand
il sera construit (position tardive, PRD §0).

### 3.4 État interne faisant autorité

**Deux** registres append-only font autorité, chacun sur son propre domaine : le registre des
mouvements (solde, argent disponible — dérivations pures, jamais un compteur maintenu à part,
même discipline que DA-M6-09/DA-M8-«état interne») et le registre d'approbation (statut d'une
demande — calculé PAR RELECTURE, jamais lu depuis un champ positionnable, DA-M5-01).

## 4. DÉCISIONS D'ARCHITECTURE TRANCHÉES

### DA-M5-01 — Registre d'approbation hash-chaîné, statut par relecture (jamais un champ positionnable)

**Décision** : `MaillonApprobation` vit dans un second registre append-only (`approbation.py`,
réutilisant la classe générique `Registre` de `registre.py`). `statut_courant(registre, demande_id)`
relit la chaîne et renvoie le dernier statut rencontré — jamais lu depuis un dict que l'appelant
pourrait construire directement. `approuver()` est le SEUL point d'écriture qui peut faire
avancer une demande vers `APPROUVE`/`REFUSE` ; garde AST dédiée (patron DA-M6-11, « point
d'écriture unique ») vérifie qu'aucune autre fonction du paquet n'appelle `.ajouter()` sur le
registre d'approbation.

**Justification** : consultation `architecte` (§0, Q1) — la proposition initiale (fonction pure
sur un dict à `statut` positionnable) permettait de forger une approbation sans jamais passer par
une garde, contredisant la promesse du brief. Le patron M2/M4 (registre + relecture) est déjà
prouvé deux fois et ferme structurellement cette faille : falsifier un statut exige de casser la
chaîne de hachage, détectable à la re-validation (CA-M5-03) — même niveau de rigueur que partout
ailleurs dans le dépôt, pas une garantie cryptographique absolue (limite honnête : un appelant qui
importerait directement l'objet `Registre` interne pourrait toujours appeler `.ajouter()`
lui-même — risque accepté au même niveau que M2/M4/M6/M8, pas un gap nouveau introduit par M5).

### DA-M5-02 — Provisions sans cycle de vie en v1, direction conservatrice assumée

**Décision** : l'argent disponible soustrait TOUS les mouvements `PROVISION` du registre, sans
notion d' « active » ou « expirée ». Une libération future sera un maillon `AJUSTEMENT` DÉDIÉ
référençant la provision d'origine par sa `source` — jamais une réécriture du maillon `PROVISION`
original (append-only).

**Justification** : consultation `architecte` (§0, Q2) — direction délibérément conservatrice
(l'argent disponible peut être SOUS-estimé après un décaissement réel non encore ajusté, jamais
l'inverse) ; correspond à l'esprit de « jamais un chiffre optimiste par défaut » déjà appliqué
ailleurs (M8 : `null` plutôt qu'une valeur inventée).

### DA-M5-03 — Foyers uniques : vocabulaire de verdicts (`validation.py`) et filtrage par rôle (`etat_financier.py`)

**Décision** : tout verdict nommé (`REJ-*`) du paquet — qu'il concerne un mouvement, un taux, ou
une demande d'approbation — est CONSTRUIT via un constructeur défini dans `validation.py`, jamais
un dict de rejet improvisé localement dans `taux_fiscaux.py`/`approbation.py`. Le filtrage par
rôle d'un état financier ne vit que dans `etat_financier.py`.

**Justification** : consultation `architecte` (§0, Q3) — M2/M4 externalisent `verdicts.py` et
`frontieres.py` séparément ; M8 (patron le plus récent) les fond dans `validation.py`/`rapports.py`
avec succès. Suivre M8, mais nommer explicitement le foyer unique évite que le vocabulaire de
rejet ou le filtrage se dispersent au fil des 7 stories (risque concret vu le nombre de fichiers
qui produisent des rejets : `validation.py`, `taux_fiscaux.py`, `approbation.py`).

### DA-M5-04 — Aucun import de paquet de domaine, même en lecture

**Décision** : `m5_financecore` n'importe JAMAIS `m1_front_office`, `m2_revenue_crm`,
`m3_estimation`, `m4_field_ops`, `m6_material_control`, `m7_marketing`, `m8_analytics`, ni aucun
futur `m9_*`/`m10_*`. Garde AST dédiée dans `conformite.py` (copie-adaptation directe de
`m8_analytics/conformite.py::verifier_aucun_import_domaine`).

**Justification** : #109, frontière la plus stricte du dépôt aux côtés de M8 — M5 ne consomme que
des `MouvementFinancier` génériques fournis par l'appelant, jamais une structure de module connue
à l'avance (cohérent avec PRD §7.5).

### DA-M5-05 — Taux fiscal non déclaré : blocage nommé, jamais une valeur par défaut

**Décision** : `taux_fiscaux.py` lève un verdict nommé (`REJ-TAUX-INCONNU`, construit via
`validation.py`) si l'identifiant demandé n'existe pas dans la déclaration versionnée courante —
jamais une approximation, jamais le dernier taux connu réutilisé silencieusement.

**Justification** : patron price-book de M6 (« sourcé sinon FALLBACK ») transposé ; un taux fiscal
faux affecte un calcul réel — le risque d'un blocage explicite est strictement préférable à une
approximation invisible (fiche source : « sinon blocage »).

### DA-M5-06 — Déterminisme total (zéro horloge, zéro aléa non ensemencé, zéro réseau)

**Décision** : aucun module de M5 n'appelle `time.time`, `datetime.now`/`today`/`utcnow`, `random`
sans graine, `uuid`, `secrets`, `os.urandom`, ni aucune primitive réseau. Tout horodatage provient
de l'appelant, reproduit tel quel.

**Justification** : reproductibilité bit-à-bit de `etat_id` exigée (CA-M5-13) — garde par
`conformite.py`, copie-adaptation directe de M3/M6/M8.

### DA-M5-07 — Convention `precedent_ligne_id` propre à M5 : `None` au premier maillon (patron M4)

**Décision (corrigée après mesure à l'implémentation S002)** : `precedent_ligne_id = None` pour
le premier maillon de CHAQUE registre (mouvements ET approbations, classe `Registre` partagée) —
PAS une chaîne vide (M8) ni 64 zéros (M2/M3).

**Justification** : S002 a adopté le patron `m4_field_ops/registre.py` (classe `Registre`
générique réutilisable pour plusieurs familles de maillons, DA-M5-01) plutôt que le patron
`m8_analytics` (spécifique à une seule forme) — ce choix, tranché par la consultation
`architecte` du cadrage, entraîne mécaniquement la convention de sentinel de SON patron source
(M4 : `None`), pas celle de M8. Cette section documentait encore, à tort, la convention M8
(chaîne vide) après le changement de patron réel en S002 — corrigé ici avant le dispatch de
S005, qui réutilise la MÊME classe `Registre` et hériterait silencieusement de la même dérive
sinon.

### DA-M5-08 — Aucune cause ni accusation dans un mouvement ou une demande (R-020 transposé)

**Décision** : ni `MaillonMouvement` ni `MaillonApprobation` ne porte de champ `cause`,
`responsable`, ni `raison_signalee`. Un `AJUSTEMENT` est un CONSTAT de correction, jamais une
désignation de faute. Garde AST dans `conformite.py` : aucune clé de ce type dans les
dict-littéraux du paquet.

**Justification** : R-020 (« jamais vol automatique » chez M6, DA-M6-07 ; transposé aux séries
temporelles chez M8, DA-M8-07) transposé une troisième fois — un `AJUSTEMENT` financier (ex. une
correction de montant) n'implique JAMAIS qu'un employé a commis une erreur identifiée dans les
données elles-mêmes ; c'est un fait à corriger, pas un verdict de blâme.

### DA-M5-09 — Snapshot/mouvement validé AVANT écriture, aucune écriture partielle

**Décision** : `validation.py` vérifie la structure ENTIÈRE d'un `MouvementFinancier` (montant
`Decimal` fini, type et classe de rétention connus) AVANT tout appel à `registre.ajouter`.
`Registre.ajouter` réapplique la même garde pour un maillon `mouvement_enregistre`, de sorte qu'un
mouvement invalide ne produit AUCUNE écriture, quel que soit le chemin public emprunté.

**Justification** : patron déjà appliqué trois fois (DA-M6-08, DA-M8-06) — « valider toutes les
clés avant la première écriture » ; M5 n'a pas de notion de lot multi-lignes en v1 (un mouvement =
un maillon), donc l'atomicité se limite à un seul maillon, comme M8.

## 5. CE QUE CHAQUE STORY PROUVE

| Story | Ce qu'elle prouve | Critères | Tier |
|---|---|---|---|
| **S001** — Contrats gelés, validation, `TypeMouvement` | Mouvement structurellement valide accepté, invalide rejeté ; échappatoire `AUTRE` ; `classe_retention` fermée fournie par l'appelant. | CA-M5-01, 04, 11 | T2 |
| **S002** — Registre append-only des mouvements | Chaîne préservée à l'ajout, altération détectée. | CA-M5-02 | T1 |
| **S003** — Solde et argent disponible | Deux champs distincts, calcul pur reproductible. | CA-M5-05, 06 | T2 |
| **S004** — Taux fiscaux versionnés et sourcés | Blocage nommé si taux absent, jamais une valeur par défaut. | CA-M5-07 | T2 |
| **S005** — Registre d'approbation F0-F7 | Statut par relecture de chaîne, jamais un champ positionnable ; F6/F7 structurellement gardés. | CA-M5-03, 08, 09, 10 | T2 |
| **S006** — État financier filtré par rôle | Rôle non autorisé aux coûts → ni solde, ni argent disponible, ni taux ; `etat_id` déterministe. | CA-M5-12, 13 | T2 |
| **S007** — Conformité statique transversale | Échappatoire D-032, anti-import de domaine, anti-taux codé en dur, anti-cause, déterminisme. | CA-M5-14, 15, 16, 17, 18 | T1 |

## 6. PARAMÈTRES CONFIGURABLES

Aucun seuil numérique arbitraire en v1 — cohérent avec l'absence de forecast (PRD §9). L'argent
disponible se calcule sur TOUS les mouvements `PROVISION`, sans paramètre de fenêtre ou de seuil ;
les taux fiscaux sont des déclarations versionnées, jamais une constante ajustable en code.

## 7. PÉRIMÈTRE V1 vs GATED/T3

### 7.1 En périmètre v1 (mode ombre, prouvable en CI Python)

| Élément | Fichier(s) responsable(s) |
|---|---|
| Contrats gelés, validation d'entrée, `TypeMouvement` | `contrats.py`, `validation.py` |
| Registre append-only hash-chaîné des mouvements | `registre.py`, `encodage.py` |
| Solde et argent disponible | `soldes.py` |
| Taux fiscaux versionnés et sourcés | `taux_fiscaux.py` |
| Registre d'approbation F0-F7, garde F6/F7 | `approbation.py` |
| État financier filtré par rôle, `etat_id` | `etat_financier.py` |
| Conformité statique (D-032, déterminisme, anti-import, anti-cause) | `conformite.py` |

**Stack technique** : stdlib Python + PyYAML, zéro réseau, zéro horloge interne, zéro LLM.

### 7.2 Repoussé GATED/T3

| Élément | Raison du report |
|---|---|
| Adapters réels (banque, paie, comptable) | read-only → dry-run → write gated (fiche source), chacun une story GATED distincte |
| Agent RAG fiscal conversationnel | Hors périmètre déterministe, comme le LLM narrateur M8 |
| Forecast 5 ans | R-009 : historique encore insuffisant pour une projection honnête |
| CFO Decision Report complet | Livrable M9 (PRD §0) |
| Vérification cryptographique réelle MFA/CPA | Intégration Zitadel (P0-9b), infra hors périmètre du module |
| Approval Engine central du core | Service pas encore construit comme unifié (brief §2.5) |
| Cycle de vie des provisions (libération) | DA-M5-02 — maillon `AJUSTEMENT` dédié, story future |

## 8. RISQUES MESURÉS DANS LE CODE LU (vigilance requise en implémentation et en revue)

1. La classe générique `Registre` (patron `m4_field_ops/registre.py:41`) doit être vérifiée
   AGNOSTIQUE de la forme du maillon avant d'être réutilisée telle quelle par `approbation.py` —
   si sa copie-adaptation dans M5 contient une hypothèse implicite sur la forme d'un mouvement
   (ex. un champ `montant` attendu), l'instanciation pour les approbations échouerait
   silencieusement ou incorrectement. À vérifier explicitement par un test croisé (une même classe
   `Registre`, deux formes de maillon différentes, dans la même suite de tests).
2. `approuver()` et `refuser()` doivent tous deux consulter `statut_courant()` AVANT d'écrire (pas
   seulement `approuver()`) pour rejeter une transition depuis un état déjà terminal
   (`APPROUVE`/`REFUSE`) — patron `REJ-CONVERSATION-CLOSE` de M2 (`statuts.py:52-55`), sinon une
   demande déjà refusée pourrait être approuvée après coup.
3. Le patron `etat_id` (`roi_engine.py:155-166`) calcule le hash SANS le champ `etat_id` lui-même
   — la copie-adaptation de M5 doit reproduire cette exclusion, sinon le hash serait
   auto-référentiel et non reproductible par un tiers qui recalculerait à partir de l'état complet.
