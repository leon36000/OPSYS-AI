# ARCHITECTURE — MODULE M3 (ESTIMATION)

Rédigé par : Architecte BMAD | Statut : PROPOSÉ | Date : 2025-01-XX

---

## 0. CONSENSUS RATIFIÉ (verbatim)

> M3 Estimation : anti-precision-inventee ; photos faibles = prix BLOQUE ; plancher rentable =
> alerte rouge ; Monte Carlo ; apprentissage estime-vs-reel. Fondations D-024 : hierarchie
> reference d'echelle > multi-vues > mono a bornes larges (MAE ~0,45 m au mieux sans reference) ;
> Depth Pro/DA-V2/Metric3D candidats ; guidage de capture = le levier.

Frontières ratifiées : **prix = M3**, dates = M4, finance = M5. M3 est le SEUL module qui porte un prix. M4 refuse tout contrat portant un champ financier, et son événement de complétion porte `devis_id: None` en v1 « en attente de l'implémentation de M3 ».

Décisions transversales applicables :
- **D-032** — Sorties structurées, échappatoire obligatoire sur tout enum (« un schéma sans issue force la fabrication »).
- **D-015** — Contrats gelés = pactes exécutables.
- **Loi 25** — Minimisation.
- **Loi 96** — Français d'abord.
- **R-020** — Aucune formulation accusatoire.

---

## 1. PAQUET `m3_estimation` — MODULES INTERNES

Le paquet `m3_estimation` est autonome. Il réutilise le patron prouvé des modules voisins par **copie-adaptation**, jamais par import inter-modules (décision ratifiée #109). Chaque fichier porte une responsabilité unique.

| Fichier | Responsabilité | Justification |
|---|---|---|
| `__init__.py` | Point d'entrée public du paquet ; expose `estimer()` et `valider_registre()`. | Un seul point d'entrée garantit que l'orchestration ne peut être contournée. |
| `contrats.py` | Définition des schémas gelés `LeadQualifie` (entrée), `BaremeCouts` (entrée), `SeuilsQualite` (entrée) et `EstimationV1` (sortie) avec leurs listes fermées de clés. | D-015 : les contrats gelés sont des pactes exécutables, leur schéma doit être figé dans un fichier dédié. |
| `validation.py` | Validation structurelle des TROIS contrats d'entrée : `LeadQualifie` (champs obligatoires, types, validation de la STRUCTURE du marqueur de readiness et de la CONCORDANCE de son `lead_id` avec celui du contrat, champs interdits), `BaremeCouts` (postes non vide, type_travaux demandé couvert, bornes numériques avec min ≤ max) ET `SeuilsQualite` (les deux clés attendues et leurs types — toute clé manquante, type incorrect ou clé inconnue bloque l'estimation, aucune valeur par défaut). Un contrat gelé sans propriétaire de validation est une promesse que personne ne tient. | Séparé de l'orchestration pour permettre un rejet |
| `qualite_photos.py` | Qualification binaire de la qualité des entrées visuelles à partir des métadonnées photo. | Logique isolée car elle détermine le branchement fail-closed / estimation. |
| `hierarchie_echelle.py` | Application de la hiérarchie ratifiée comme logique de décision pure : référence > multi-vues > mono-vue à bornes larges > indéterminé. | Séparé pour garantir qu'aucun modèle d'inférence ne puisse s'y glisser en v1. |
| `blocage_prix.py` | Garde anti-précision-inventée : décide du blocage du prix à partir du niveau de confiance et de la qualification des photos, et construit la `raison_blocage` comme un CONSTAT (R-020). Bornes toujours nulles — ce module ne calcule aucun prix. | Isolé pour que la promesse « aucun chiffre ne quitte M3 quand le prix est bloqué » soit éprouvable seule, sans traverser l'orchestrateur. |
| `monte_carlo.py` | Simulation Monte Carlo déterministe à graine fournie par l'appelant, production de l'intervalle de confiance. | Isolé pour garantir l'auditabilité du déterminisme (CA-M3-10, CA-M3-11, CA-M3-20). |
| `plancher.py` | Confrontation de la borne basse au plancher rentable, émission de l'alerte rouge. | Logique simple mais métier-critique, isolée pour testabilité directe. |
| `devis.py` | Dérivation du `devis_id` par encodage canonique injectif (préfixage par longueur + sha256). | Copie-adaptation du patron d'encodage canonique prouvé dans les modules voisins. |
| `registre.py` | Registre append-only hash-chaîné des estimations émises ; API ajouter / lire / valider chaîne. | Copie-adaptation du patron de registre hash-chaîné prouvé dans M2. |
| `digest.py` | Production du digest quotidien déterministe des estimations bloquées et des alertes de plancher vers Nathan. | Isolé car consommateur en lecture seule du registre, sans effet sur l'estimation. |
| `signaux.py` | Émission du signal de relance structuré vers M2 sur photos faibles (max 1 par estimation). Câblé par `estimation.py` (PLAN T2.3, DA-M3-12 et suivants) quand la qualité photo est insuffisante — plus un module orphelin. | Isolé pour garantir la contrainte de fréquence et l'absence de boucle. |
| `estimation.py` | Orchestrateur principal : séquence validation du lead → **validation du barème** → qualité → hiérarchie → Monte Carlo → plancher → signal de relance M2 (`signaux.py`, qualité insuffisante) → prix recommandé (`taux_marge` fourni, formule réutilisée de `devis_durable.py`, DA-M3-12) → durée main-d'œuvre → contrat de sortie → registre. La validation du barème précède TOUTE production de bornes (CA-M3-21) : un tirage sans bornes de coût produirait des valeurs arbitraires. | Un seul orchestrateur garantit que l'ordre des étapes ne peut être altéré. |

---

## 2. SCHÉMAS DE DONNÉES

### 2.1 Contrats d'entrée reçus de M2 — `LeadQualifie` et le marqueur de readiness

> **CORRIGÉ (issue #166) — le contrat décrit ici était un FANTÔME.** Le cadrage initial décrivait
> un `LeadQualifie` à huit champs (`sha256`, `owner`, `interactions`, `photos`, `contexte`) que M2
> **n'émet pas**. Mesuré sur le module livré, 533 tests verts : le contrat gelé de M2 porte SEPT
> champs, et le mot « photos » n'apparaît nulle part dans M2. Valider le contrat fantôme aurait
> rejeté tout contrat réel, et les tests seraient passés au vert en fabriquant l'entrée — un
> chemin inexistant en production, propagé aux neuf stories. La description ci-dessous est celle
> de l'interface RÉELLE, celle que M4 consomme déjà depuis 427 tests.

#### `LeadQualifie` — contrat gelé émis par M2 (liste FERMÉE : sept clés gelées, trois optionnelles)

```yaml
LeadQualifie:
  lead_id: str              # Identifiant stable du lead, attribué par M2.
  conversation_id: str      # Référence de la conversation d'origine.
  type_travaux: str         # Énuméré fermé (voir 2.5).
  ville: str                # Ville renseignée, non vide.
  canal: str                # Canal d'entrée : telephone | courriel | formulaire | texte.
  contact: dict             # Clés autorisées : nom, telephone, courriel — au moins une non vide.
  urgence_declaree: bool    # Booléen STRICT (1 et 0 sont refusés).
  source: str               # OPTIONNEL (PLAN T2.2) — canal d'acquisition déclaré par M7 ; chaîne non vide s'il est fourni.
  utm: dict                 # OPTIONNEL (PLAN T2.2) — clés autorisées : utm_source, utm_medium, utm_campaign, utm_content ; non vide, valeurs chaînes non vides.
  campagne: str             # OPTIONNEL (PLAN T2.2) — campagne marketing déclarée par M7 ; chaîne non vide s'il est fourni.
```

M3 valide ce contrat **à l'identique** de ce que fait M4 : mêmes clés, mêmes énumérés, même
sémantique de rejet. Un consommateur qui durcit unilatéralement un contrat gelé rejetterait des
leads que son voisin accepte.

Les trois clés marquées OPTIONNEL (PLAN T2.2, provenance marketing) ne changent pas le contrat
gelé v1 : M2 les accepte si elles sont fournies, et M3 comme M4 les acceptent à l'identique.
Absentes, elles ne produisent ni erreur ni valeur par défaut ; présentes, elles sont validées avec
la même forme que chez M2 (`CHAMPS_CONTRAT_OPTIONNELS`, `CLES_UTM`), et toute autre clé reste
refusée. M3 ne s'en sert pas pour estimer.

#### Marqueur de readiness — émis et signé par M2

```yaml
MarqueurReadiness:
  readiness_ok: bool        # DOIT valoir True par IDENTITÉ (l'entier 1 est refusé).
  lead_id: str              # DOIT correspondre au lead_id du contrat.
  hash_tete_registre: str | null   # Ancre du registre M2 : hex 64 minuscules, ou null.
  horodatage: str           # ISO-8601 à fuseau obligatoire.
  empreinte: str            # Hex 64 minuscules — l'empreinte que le cadrage cherchait sous
                            # le nom « sha256 » : elle est PRODUITE PAR M2, jamais recalculée ici.
```

**C'est le marqueur qui ATTESTE la readiness**, pas une re-déduction depuis des champs du contrat.
`owner` et « au moins une interaction post-qualification » sont des **conditions vérifiées par M2
avant de signer** ; elles ne figurent pas dans le contrat et M3 ne peut ni ne doit les revalider.

**Limite DÉCLARÉE** : la validation du marqueur est STRUCTURELLE. M3 ne possède pas le registre de
M2 et ne peut donc pas recalculer l'empreinte — la vérification cryptographique de bout en bout
appartient à la couche d'intégration qui possède les deux arbres. Ce constat vaut pour M4, qui
procède exactement ainsi ; M3 ne prétend pas mieux.

#### `PhotosFournies` — entrée SÉPARÉE, fournie par l'appelant

M2 ne transporte **aucune** photo (mesuré : zéro occurrence dans tout le module). Les métadonnées
visuelles sont donc une entrée à part entière, au même titre que le barème de coûts et la graine du
Monte Carlo — trois entrées fournies par l'appelant, jamais devinées.

```yaml
PhotosFournies:
  - photo_id: str                 # Identifiant stable.
    resolution_largeur: int       # Pixels, > 0.
    resolution_hauteur: int       # Pixels, > 0.
    eclairage: float              # Échelle 0-10.
    angle: str                    # Identifiant d'angle (face, gauche_45, droite_45, ...).
    reference_echelle: dict|null  # OPTIONNEL. Si présent : {type: str, dimensions_connues: bool}.
```

Une liste VIDE est un cas légitime — et le prix est alors bloqué faute d'entrée visuelle, jamais
estimé au jugé.

**Clés interdites**, contrôlées récursivement sur TOUTES les entrées : `prix`, `montant`,
`date_execution`, `engagement`, `tva`, `montant_ttc`, `conditions_paiement`, `creneau`, `duree`.
La frontière ratifiée ne dépend pas de la provenance de la donnée.

### 2.2 Contrat de sortie — `EstimationV1` (émis vers M4)

Schéma gelé, liste FERMÉE de clés. Copié mot pour mot du PRD section 5.

```yaml
EstimationV1:
  devis_id: str
    # Dérivé par encodage canonique injectif :
    # encodage = f"{len(lead_id):04d}{lead_id}{len(empreinte_marqueur_m2):04d}{empreinte_marqueur_m2}"
    # devis_id = "M3-DEVIS-" + sha256(encodage).hexdigest()[:16]
    # Injectif car lead_id est unique et empreinte_marqueur_m2 est unique par contrat gelé.

  lead_id: str
    # Identifiant stable du lead source, transmis par M2.

  empreinte_marqueur_m2: str
    # Empreinte du MARQUEUR de readiness signé par M2, épinglée pour traçabilité.
    # C'est M2 qui la produit ; M3 la transporte sans la recalculer (il ne possède
    # pas le registre de M2). Le cadrage initial la cherchait à tort dans le contrat.

  niveau_confiance: str
    # Enum NiveauConfiance : REFERENCE_ECHELLE | MULTI_VUES | MONO_VUE_BORNES_LARGES | INDETERMINE

  verdict_estimation: str
    # Enum VerdictEstimation : AUCUN_BLOCAGE | QUALITE_ENTREE_INSUFFISANTE |
    # REFERENCE_ECHELLE_ABSENTE | PLANCHER_RENTABILITE_FRANCHI |
    # CONTRAT_ENTREE_INVALIDE | INDETERMINE

  bareme_version: str | null
    # Version du barème utilisé, épinglée pour traçabilité.
    # Vaut null SI ET SEULEMENT SI l'estimation est bloquée faute de barème
    # utilisable (absent, ou ne couvrant pas le type_travaux demandé) : il n'y a
    # alors aucune version à tracer, et inventer un jeton serait une donnée
    # fabriquée. Dans tous les autres cas — y compris un blocage pour une AUTRE
    # cause, par exemple des photos faibles — le barème a bien été fourni et sa
    # version est épinglée. L'équivalence est donc : bareme_version null <=>
    # verdict_estimation vaut INDETERMINE pour cause de barème.
  prix_bloque: bool
    # True si le prix est bloqué (aucun chiffre émis).

  intervalle_confiance:
    borne_basse: float | null
      # Borne inférieure de l'estimation (en unités monétaires configurables).
      # null si prix_bloque = True.
    borne_haute: float | null
      # Borne supérieure de l'estimation.
      # null si prix_bloque = True.
    niveau: float
      # Niveau de confiance de l'intervalle (ex: 0.90 pour 90 %).
      # Valeur par défaut : 0.90. Configurable par l'appelant.

  alerte_plancher: bool
    # True si borne_basse < plancher_rentable (paramètre d'entrée).

  raison_blocage: str | null
    # Description explicite des éléments manquants si prix_bloque = True.
    # null si prix_bloque = False.

  graine_monte_carlo: int
    # Graine fournie par l'appelant, garantissant la reproductibilité.

  hash_maillon: str
    # sha256 du maillon append-only dans le registre estimé-vs-réel.
```

**Champs absents par design** (frontières M3) :
- Aucune date (ni `date_execution`, ni `creneau`, ni `duree`) — domaine de M4.
- Aucun champ financier (ni `tva`, ni `montant_ttc`, ni `conditions_paiement`) — domaine de M5.
- Aucun identifiant de stock ou de matériau — domaine de M6.

### 2.3 Contrat d'entrée gelé — `BaremeCouts` (fourni par l'appelant)

Liste FERMÉE de clés. Le module ne porte aucune valeur monétaire en dur : le barème est une
donnée d'entrée, au même titre que la graine du Monte Carlo.

```yaml
BaremeCouts:
  version: str
    # Identifiant de version du barème, épinglé dans l'estimation pour traçabilité.
  unite: str
    # Unité monétaire, énumérée et fermée par l'appelant.
  postes:
    # Dictionnaire type_travaux -> paramètres de coût. Un type_travaux absent
    # rend l'estimation IMPOSSIBLE : blocage INDETERMINE, jamais d'extrapolation.
    <type_travaux>:
      cout_unitaire_min: float
      cout_unitaire_max: float
      # Bornes du coût par unité d'ouvrage. Le Monte Carlo tire DANS ces bornes :
      # sans elles il tirerait dans le vide et produirait des bornes arbitraires.
      #
      # COMPLÉTUDE : aucune exigence de couvrir TOUS les types de travaux — le
      # barème peut être partiel. C'est le type_travaux DEMANDÉ qui doit être
      # couvert, sinon blocage. Exiger un barème exhaustif interdirait de
      # démarrer avec un catalogue réduit ; ne rien exiger produirait des bornes
      # inventées. Exemple minimal valide :
      #
      #   postes:
      #     renovation_totale: {cout_unitaire_min: 850.0, cout_unitaire_max: 1400.0}
      #
      # Un appel portant type_travaux = "extension" sur CE barème est BLOQUÉ.
```

Validation fail-closed : barème absent, `postes` vide, type_travaux non couvert, bornes
non numériques ou `min > max` -> estimation bloquée avec `INDETERMINE`.

---

### 2.4 Contrat d'entrée gelé — `SeuilsQualite` (fourni par l'appelant)

`SeuilsQualite` est un schéma gelé : sa liste de clés est FERMÉE.

```yaml
resolution_minimale: int  # résolution en pixels sous laquelle une photo est faible
eclairage_minimal: float  # niveau d'éclairage sous lequel une photo est faible
```

Une clé manquante, un type incorrect ou une clé inconnue BLOQUE l'estimation ; aucune valeur par défaut n'existe.

---

### 2.5 Énumérés fermés

#### `type_travaux` — copie ÉPINGLÉE de l'énuméré fermé de M2

Cinq valeurs, reprises telles quelles du contrat gelé que M2 émet :
`renovation_totale`, `extension`, `ravalement`, `isolation_thermique`, `autre`.

`autre` est l'échappatoire D-032 qui rend la fermeture légitime : sans elle, un type de travaux
non prévu forcerait la fabrication d'une valeur.

Cette copie fait foi pour la validation d'entrée de M3 (décision #109 : jamais d'import
inter-modules). La divergence ne peut pas passer inaperçue — le contrôle de cohérence confronte
cette liste à la constante que M2 déclare dans sa source, et **deux valeurs manquaient ici**
(`ravalement`, `isolation_thermique`) avant que ce contrôle ne l'établisse : le consommateur
ignorait des valeurs que le producteur émet. Filet secondaire déjà ratifié : le barème étant indexé
par `type_travaux`, un type accepté mais absent du barème bloque l'estimation en aval (CA-M3-21).

#### NiveauConfiance

Copié mot pour mot du PRD section 4.1.

| Valeur | Condition d'obtention |
|---|---|
| `REFERENCE_ECHELLE` | Au moins une photo dont les métadonnées déclarent un objet de dimensions certifiées visible dans le cadre (porte standard, brique, carreau de carrelage, mètre ruban déployé). Condition nécessaire et suffisante pour une estimation précise. |
| `MULTI_VUES` | Au moins 3 photos sous angles différents (métadonnées `angle` distincts), résolution ≥ seuil configurable, sans référence d'échelle déclarée. Précision moindre, bornes explicites. |
| `MONO_VUE_BORNES_LARGES` | 1 ou 2 photos, résolution ≥ seuil configurable, éclairage suffisant (métadonnées `eclairage` ≥ seuil), sans référence d'échelle, sans multi-vues. MAE ~0,45 m au mieux. |
| `INDETERMINE` | **Échappatoire D-032** — les métadonnées fournies ne permettent de classifier dans aucun des trois niveaux précédents. Ce verdict signale « on ne sait pas » et force un blocage du prix. |

#### VerdictEstimation

Copié mot pour mot du PRD section 4.2.

| Valeur | Signification | `prix_bloque` |
|---|---|---|
| `AUCUN_BLOCAGE` | Estimation émise normalement, intervalle de confiance calculé. | `False` |
| `QUALITE_ENTREE_INSUFFISANTE` | Photos faibles : résolution sous le seuil, éclairage insuffisant, ou aucune photo fournie. Le prix ne peut pas être estimé. | `True` |
| `REFERENCE_ECHELLE_ABSENTE` | Aucune référence d'échelle identifiée dans les photos. Signalé comme alerte, mais ne bloque pas si le niveau de confiance est `MULTI_VUES` ou `MONO_VUE_BORNES_LARGES`. | `False` |
| `PLANCHER_RENTABILITE_FRANCHI` | La borne basse de l'intervalle de confiance est strictement inférieure au plancher rentable fourni. Alerte rouge : marge négative ou nulle possible. Ne bloque pas l'estimation. | `False` |
| `CONTRAT_ENTREE_INVALIDE` | Le contrat `LeadQualifie` d'entrée ne respecte pas le schéma gelé (champ manquant, type incorrect, champ interdit présent). | `True` |
| `INDETERMINE` | **Échappatoire D-032** — la raison du blocage ne peut être classifiée dans les valeurs précédentes. Signale « on ne sait pas pourquoi ça bloque » et force une revue humaine. | `True` |

### 2.6 Maillon du registre append-only

```yaml
MaillonEstimation:
  index: int                # Position séquentielle dans le registre (0, 1, 2, ...).
  devis_id: str             # Référence au devis émis.
  lead_id: str              # Référence au lead source.
  niveau_confiance: str     # Enum NiveauConfiance.
  verdict_estimation: str      # Enum VerdictEstimation.
  prix_bloque: bool         # Copie du champ du contrat de sortie.
  borne_basse: float | null # Copie du champ du contrat de sortie.
  borne_haute: float | null # Copie du champ du contrat de sortie.
  alerte_plancher: bool     # Copie du champ du contrat de sortie.
  hash_precedent: str       # sha256 du maillon précédent (chaîne vide pour index 0).
  hash_maillon: str         # sha256 de ce maillon (inclut hash_precedent).
```

### 2.7 Signal de relance vers M2

```yaml
SignalRelanceM2:
  type: str                 # Toujours "DEMANDE_ENTREES_VISUELLES".
  lead_id: str              # Lead concerné.
  devis_id: str             # Devis bloqué correspondant.
  elements_manquants:       # Liste explicite des éléments nécessaires.
    - str
  emission_count: int       # Toujours 1 en v1 (pas de boucle).
```

### 2.8 Digest quotidien vers Nathan

```yaml
DigestEstimationsBloquees:
  type: str                 # Toujours "DIGEST_ESTIMATIONS_BLOQUEES".
  nb_estimations_bloquees: int
  nb_alertes_plancher: int
  estimations_bloquees:
    - devis_id: str
      lead_id: str
      verdict_estimation: str
      raison_blocage: str
  alertes_plancher:
    - devis_id: str
      lead_id: str
      borne_basse: float
      plancher_rentable: float
  hash_digest: str          # sha256 déterministe du contenu du digest.
```

---

## 3. INTERFACES ET CONTRATS

### 3.1 Interface d'entrée — ce que M3 reçoit

M3 reçoit de **M2** deux artefacts, décrits en 2.1 : le contrat gelé `LeadQualifie` (sept clés) et
le **marqueur de readiness** signé par M2. C'est le marqueur qui atteste la traversée de la
readiness gate ; M3 le valide structurellement sans prétendre le recalculer.

M3 reçoit de son **appelant** trois entrées supplémentaires, toutes fournies, jamais devinées :

- `photos: list` — métadonnées visuelles (2.1). M2 n'en transporte aucune. Liste vide = prix bloqué.
- `bareme_couts: dict` — **contrat d'entrée gelé** décrit en 2.3, rangé avec les autres contrats gelés. Le module ne porte AUCUNE
  valeur monétaire : sans barème couvrant le `type_travaux` demandé, l'estimation est BLOQUÉE
  avec `INDETERMINE` (CA-M3-21, DA-M3-09). Exiger le barème ici, et non en prose, est ce qui rend
  le critère implémentable — objection critique de revue scellée : un critère qui exige ce que
  l'interface ne déclare pas est improuvable.
- `seuils_qualite: dict` — contrat d'entrée gelé décrit en 2.4, …
- `graine_monte_carlo: int` — graine pour la simulation déterministe.
- `plancher_rentable: float` — seuil d'alerte rouge.

### 3.2 Interface de sortie — ce que M3 émet vers M4

M3 émet le contrat gelé `EstimationV1` portant un `devis_id` stable. M4 consomme ce `devis_id` pour associer l'intervention planifiée à son estimation. M4 refuse tout contrat portant un champ financier : le contrat `EstimationV1` ne contient **aucun** champ de date ni de finance.

### 3.3 Interface de sortie — signal de relance vers M2

M3 émet un `SignalRelanceM2` lorsque le prix est bloqué pour `QUALITE_ENTREE_INSUFFISANTE`. Fréquence maximale : 1 signal par estimation, pas de relance automatique en boucle.

### 3.4 Interface de sortie — digest vers Nathan

M3 produit un `DigestEstimationsBloquees` quotidien, déterministe, hash-chaîné. Nathan le consulte en lecture seule. Ce digest est une extension du digest M2.

### 3.5 Interface d'entrée future — coût réel (M5/M6)

Le registre append-only est conçu pour recevoir ultérieurement le coût réel (facturé par M5, matériaux déstockés par M6) après complétion de l'intervention. En v1, cette interface est définie mais non connectée.

---

## 4. DÉCISIONS D'ARCHITECTURE TRANCHÉES

### DA-M3-01 — Déterminisme du Monte Carlo par graine injectée

**Décision** : La simulation Monte Carlo utilise exclusivement `random.Random(graine)` instancié localement à chaque appel, avec la graine fournie par l'appelant. Aucun appel à `random.random()`, `random.seed()` global, `time.time()`, `datetime.now()`, ou toute autre source d'aléa non contrôlée n'existe dans le module.

**Justification** : La reproductibilité bit-à-bit est une exigence de traçabilité et de preuve en CI (CA-M3-10, CA-M3-11, CA-M3-20). Un aléa non contrôlé rendrait impossible la vérification déterministe et ouvrirait la porte à des estimations non reproductibles en production.

### DA-M3-02 — Refus fail-closed quand la qualité d'entrée est insuffisante

**Décision** : Lorsque les métadonnées photo ne satisfont pas au minimum la condition `MONO_VUE_BORNES_LARGES` (résolution sous le seuil, éclairage insuffisant, ou liste de photos vide), M3 bloque le prix (`prix_bloque = True`), émet le verdict `QUALITE_ENTREE_INSUFFISANTE`, et ne produit aucun chiffre. Les bornes de l'intervalle de confiance sont `null`.

**Justification** : Un prix émis sur des entrées insuffisantes devient une promesse contractuelle aux yeux du client (brief analyste §2.1). Le fail-closed est la seule défense contre l'anti-précision-inventée. M3 ne tente jamais de compenser des entrées faibles par une estimation hasardeuse.

### DA-M3-03 — Absence totale de champ de date et de finance dans le contrat de sortie

**Décision** : Le contrat `EstimationV1` ne contient aucun champ de date (`date_execution`, `creneau`, `duree`) ni aucun champ financier (`tva`, `montant_ttc`, `conditions_paiement`). La validation de sortie rejette explicitement toute tentative d'ajout de ces clés.

**Justification** : Les dates sont le domaine exclusif de M4, la finance est le domaine exclusif de M5/M6. Toute fuite de ces champs dans M3 créerait une responsabilité croisée et contournerait les frontières ratifiées. M4 refuse tout contrat portant un champ financier.

### DA-M3-04 — Frontière avec la vision GATED/T3

**Décision** : M3 n'exécute aucun modèle d'inférence visuelle en v1. Les candidats Depth Pro, DA-V2, et Metric3D sont identifiés mais repoussés en mode GATED/T3. La hiérarchie des références d'échelle est appliquée comme **logique de décision pure** sur les métadonnées photo, sans aucun appel réseau, GPU, ou chargement de poids de modèle.

**Justification** : L'exécution réelle de modèles de vision nécessite une infrastructure (GPU, réseau, stockage de poids) incompatible avec le mode ombre v1 (stdlib Python + PyYAML, zéro réseau). La logique de décision sur métadonnées est suffisante pour prouver la garde anti-précision-inventée en CI.

### DA-M3-05 — Copie-adaptation du patron, jamais d'import inter-modules

**Décision** : Le paquet `m3_estimation` réutilise le patron prouvé des modules voisins (encodage canonique injectif, registre append-only hash-chaîné, catalogue de verdicts) par copie-adaptation de fichiers sources, jamais par import inter-modules.

**Justification** : Décision ratifiée #109. L'isolation des modules garantit qu'un changement dans M2 ne peut casser M3, et que chaque module est independently testable et deployable. Le couplage par import créerait des dépendances circulaires et des régressions en cascade.

### DA-M3-06 — Échappatoire INDETERMINE obligatoire sur tout enum (D-032)

**Décision** : Chaque enum du module (`NiveauConfiance`, `VerdictEstimation`) porte une valeur `INDETERMINE` comme échappatoire obligatoire. Quand les métadonnées ne permettent aucune classification, M3 choisit `INDETERMINE` et bloque le prix, plutôt que de forcer une valeur optimiste.

**Justification** : D-032 — « un schéma sans issue force la fabrication ». Si un enum n'a pas d'échappatoire, le code sera tenté de choisir la valeur la plus proche, produisant une estimation non défendable. L'échappatoire force la transparence : « on ne sait pas » est un verdict valide.

### DA-M3-07 — Encodage canonique injectif pour devis_id

**Décision** : Le `devis_id` est dérivé par encodage canonique injectif : `encodage = f"{len(lead_id):04d}{lead_id}{len(empreinte_marqueur_m2):04d}{empreinte_marqueur_m2}"`, puis `devis_id = "M3-DEVIS-" + sha256(encodage).hexdigest()[:16]`. Le préfixage par longueur garantit l'injectivité (pas de collision par concaténation ambiguë).

**Justification** : Copie-adaptation du patron d'encodage canonique prouvé dans les modules voisins. L'injectivité garantit que deux leads différents produisent toujours des `devis_id` distincts (CA-M3-15), et que le même lead produit toujours le même `devis_id` (CA-M3-14).

### DA-M3-08 — Raisons de blocage non accusatoires (R-020)

**Décision** : Les raisons de blocage décrivent les éléments manquants sans attribuer de faute. Formulation : « référence d'échelle non identifiée dans les photos fournies » et non « le technicien n'a pas fourni de référence d'échelle ».

**Justification** : R-020 — aucune formulation accusatoire. Les raisons de blocage sont des constats factuels, pas des jugements. Cette règle est appliquée dans `qualite_photos.py` et `estimation.py` lors de la construction du champ `raison_blocage`.

---

### DA-M3-10 — un GATE peut lire la source d'un module voisin, le code de production non

Le contrôle de cohérence confronte le contrat consommé par M3 à la constante que M2 déclare dans sa
SOURCE. Parce que : la décision #109 interdit les imports inter-modules pour empêcher le couplage
du CODE DE PRODUCTION — aucun module de M3 n'importe M2, et cette propriété reste vérifiable. Une
vérification, elle, doit précisément confronter un consommateur à son producteur : c'est sa raison
d'être, et s'en priver a laissé passer un contrat fantôme pendant tout un cadrage (issue #166).
Piège écarté : rouvrir ce débat à chaque revue faute de décision écrite — objection de revue
scellée. Le mécanisme est fail-closed et prouvé : source absente ou constante renommée font ROUGIR
le gate, jamais passer en silence.

### ANCRES DE DOCSTRING

Un critère qui promet « c'est écrit dans la docstring » n'est vérifiable que si la phrase attendue
est épinglée. Le contrôle 15 exige cette table, refuse qu'une promesse du PRD n'y figure pas, et
impose chaque ancre À L'EMPLACEMENT DÉCLARÉ dès que le paquet source existe. CA-M3-03
promet la limite à DEUX endroits — la docstring du module et à côté du verdict : chacun
porte donc sa ligne, et la promesse n'est tenue que si les deux moitiés sont écrites.

| Critère | Ancre exacte | Emplacement |
|---|---|---|
| CA-M3-03 | `validation STRUCTURELLE du marqueur : M3 ne recalcule pas l'empreinte, qui couvre des conditions extraites du registre de M2` | docstring de module |
| CA-M3-03 | `seul le registre hash-chaîné de M2 fait foi sur la traversée réelle de la gate` | catalogue de verdicts |

L'ancre est MESURÉE, pas supposée : `emettre_marqueur` de M2 calcule
`empreinte = encoder_canonique(conditions, lead_id, tete)` où `conditions` sortent de
`_extraire_conditions(registre_cible, lead_id)` — du REGISTRE, pas du contrat. M3, qui ne possède
pas ce registre (DA-M3-05), n'a donc pas les entrées du calcul : le non-recalcul n'est pas une
facilité, c'est une impossibilité.

### DA-M3-11 — l'avis d'architecte antérieur au correctif du contrat est PÉRIMÉ sur l'empreinte

L'avis rendu avant #166 décidait que « M3 recalcule l'empreinte du contrat complet MOINS le champ
`sha256` ». Les deux moitiés sont fausses sur le contrat réel, et la mesure le montre : le contrat
`LeadQualifie` émis par M2 a SEPT clés gelées (plus, depuis PLAN T2.2, trois clés optionnelles de
provenance marketing) dont aucune n'est une empreinte — il n'y a pas de `sha256` à
exclure ; et l'empreinte qui existe, celle du marqueur, couvre des conditions extraites du registre
de M2, hors de portée de M3. L'avis raisonnait sur le contrat fantôme que ce correctif supprime.
La story S001 repart donc de la mesure, jamais de cet avis, qui reste au journal comme réfutation.

### DA-M3-09 — le barème de coûts est une ENTRÉE, jamais une donnée du module

Le module ne porte aucune valeur monétaire en dur. Le barème est fourni par l'appelant, exactement
comme la graine du Monte Carlo et comme le référentiel géographique l'est pour le module voisin.
Parce que : une simulation sans modèle sous-jacent produit des bornes arbitraires, et un barème
codé en dur deviendrait faux au premier changement de tarif sans que rien ne le signale. Piège
écarté : émettre un intervalle d'apparence rigoureuse — le Monte Carlo est déterministe et
reproductible — alors que ses paramètres sont inventés. Sans barème utilisable pour le
`type_travaux` demandé, l'estimation est BLOQUÉE avec `INDETERMINE` (CA-M3-21).

### DA-M3-12 — Le prix recommandé est dérivé du coût, jamais un second champ gelé

**Constat** (`docs/departements/M3-audit.md` §2.1) : `bareme_couts` (DA-M3-09) est un barème de
COÛT, et `intervalle_confiance` du contrat gelé `EstimationV1` (2.2) reste donc un intervalle de
COÛT — jamais un prix client. Aucun champ `marge`/`taux_marge`/`prix_recommande` n'existait dans
`EstimationV1`, alors que le mot « prix » de l'interface (`m3_estimer_projet`) désignait en
réalité ce coût.

**Décision** : `prix_recommande` (`{borne_basse, borne_haute}`) est une clé SUPPLÉMENTAIRE de la
réponse de l'orchestrateur — JAMAIS un champ d'`EstimationV1` (2.2), qui reste GELÉ et INCHANGÉ
(P5, DEFINITION-PRODUIT.md §5) — dérivée d'`intervalle_confiance` par un `taux_marge` FOURNI PAR
L'APPELANT (§6, jamais codé en dur, même discipline que `plancher_rentable`) : `prix = cout x (1
+ taux_marge)`, arrondi `ROUND_HALF_UP` au cent. La formule n'est PAS réécrite ici : le module
`devis_durable.py` (PLAN T2.3-a, devis commercial) la possédait déjà pour `prix_unitaire` — elle
en est extraite (`prix_depuis_cout`, `texte_vers_taux_marge`) et réutilisée TELLE QUELLE par
`estimation.py`, jamais dupliquée. Calculé SEULEMENT sur la voie NON bloquée (un prix sans coût
produit n'aurait pas de socle, même raisonnement que la durée de main-d'œuvre, T1.2-f).

`taux_marge` ABSENT n'est PAS une erreur (`prix_recommande` reste `None`, le coût seul demeure
exploitable — le fait est noté dans `elements_manquants`, jamais un silence) ; `taux_marge`
PRÉSENT mais invalide (texte non décimal, `<= -1`) EST un rejet NOMMÉ de l'orchestrateur entier —
même distinction, et même discipline fail-closed, que `plancher_rentable`/
`duree_minutes_par_unite` ailleurs dans ce fichier : une donnée fournie DE TRAVERS est signalée,
jamais silencieusement ignorée ni inventée.

**Justification** : un contrat gelé qui change de forme à chaque nouveau besoin cesse d'être gelé
(P5, DA-M3-07 pour le même principe appliqué à `devis_id`) ; une clé additionnelle non gelée,
absente quand elle ne peut pas être calculée honnêtement, ferme cet écart sans réouvrir
`EstimationV1`. Piège écarté : dupliquer la formule de prix dans deux modules qui pourraient
diverger d'un cent (déjà observé une fois entre `devis_durable.py` T2.3-a et T2.3-b, voir sa
docstring) — la réutilisation directe rend cette divergence structurellement impossible.

## 5. CE QUE CHAQUE STORY PROUVE

| Story | Ce qu'elle prouve |
|---|---|
| **S001** — Validation du contrat d'entrée LeadQualifie | Prouve que M3 accepte un contrat valide et rejette explicitement tout contrat invalide ou contenant un champ interdit, avec verdict nommé (CA-M3-01, CA-M3-02, CA-M3-03, CA-M3-22). |
| **S002** — Qualification de la qualité des entrées visuelles | Prouve que des photos faibles (résolution sous seuil, éclairage insuffisant, ou liste vide) produisent un blocage du prix avec verdict explicite et signal de relance vers M2 (CA-M3-04). |
| **S003** — Hiérarchie des références d'échelle | Prouve que la classification des niveaux de confiance (REFERENCE_ECHELLE, MULTI_VUES, MONO_VUE_BORNES_LARGES, INDETERMINE) est appliquée comme logique de décision pure sur les métadonnées, sans aucun modèle d'inférence (CA-M3-05, CA-M3-06, CA-M3-07, CA-M3-08). |
| **S004** — Garde anti-précision-inventée et prix bloqué | Prouve que lorsque le prix est bloqué, les bornes de l'intervalle sont null et la raison de blocage est non vide — aucun chiffre ne quitte M3 (CA-M3-09). |
| **S005** — Monte Carlo déterministe à graine fournie | Prouve la reproductibilité bit-à-bit pour la même graine et la divergence pour des graines différentes, sans aucun appel à random non ensemencé, et le BLOCAGE lorsque le barème fourni ne couvre pas le type de travaux demandé — un tirage sans bornes produirait des valeurs arbitraires (CA-M3-10, CA-M3-11, CA-M3-21). |
| **S006** — Plancher rentable et alerte rouge | Prouve que l'alerte plancher est émise quand la borne basse est strictement inférieure au plancher, et absente sinon, sans bloquer l'estimation (CA-M3-12, CA-M3-13). |
| **S007** — Contrat de sortie EstimationV1 et devis_id | Prouve que le devis_id est injectif et reproductible, que deux leads distincts produisent des devis distincts, et que le contrat de sortie ne contient aucun champ de date ni de finance (CA-M3-14, CA-M3-15, CA-M3-16). |
| **S008** — Registre append-only estimé-vs-réel | Prouve que la chaîne de hash est préservée à l'ajout et que toute altération d'un maillon est détectée par validation (CA-M3-17, CA-M3-18). |
| **S009** — Échappatoires D-032 et conformité déterministe | Prouve que tout enum porte INDETERMINE, qu'aucun appel interdit (random non ensemencé, horloge, réseau) n'existe dans le module, et que le digest quotidien est déterministe (CA-M3-19, CA-M3-20). |

---

## 6. PARAMÈTRES CONFIGURABLES

| Paramètre | Description | Valeur par défaut |
|---|---|---|
| `seuil_resolution_min` | Résolution minimale (en pixels, produit largeur × hauteur) pour qu'une photo soit acceptable. | Défini par le PM. |
| `seuil_eclairage_min` | Niveau d'éclairage minimal (échelle 0-10) pour qu'une photo soit acceptable. | Défini par le PM. |
| `niveau_confiance_defaut` | Niveau de confiance de l'intervalle Monte Carlo. | 0.90 |
| `plancher_rentable` | Coût minimal en dessous duquel l'alerte rouge est émise. | Fourni par l'appelant à chaque estimation. |
| `nb_iterations_monte_carlo` | Nombre d'itérations de la simulation Monte Carlo. | Défini par le PM. |
| `bareme_couts` | Contrat gelé `BaremeCouts` (2.3) : versions, unité, postes par type de travaux. | **Fourni par l'appelant à chaque estimation. Aucune valeur par défaut : un barème par défaut serait un coût inventé.** |
| `taux_marge` | Taux de marge appliqué au COÛT (intervalle Monte Carlo) pour dériver `prix_recommande` (PLAN T2.3, reste de T2.3-b — voir DA-M3-12). Texte décimal, ex. `"0.35"` pour 35 %. | **Fourni par l'appelant à chaque estimation (paramètre optionnel de `m3_estimer_projet`). Aucune valeur par défaut : absent, aucun prix recommandé n'est calculé (le coût seul reste exploitable) — jamais une marge inventée.** |

---

## 7. PÉRIMÈTRE V1 vs GATED/T3

### 7.1 En périmètre v1 (mode ombre)

| Élément | Fichier responsable |
|---|---|
| Garde anti-précision-inventée | `estimation.py`, `qualite_photos.py` |
| Qualification de la qualité des entrées | `qualite_photos.py` |
| Hiérarchie des références d'échelle | `hierarchie_echelle.py` |
| Plancher rentable | `plancher.py` |
| Monte Carlo déterministe | `monte_carlo.py` |
| Registre append-only | `registre.py` |
| Contrat gelé de sortie | `contrats.py`, `devis.py` |
| Signal de relance vers M2 | `signaux.py` |
| Digest des estimations bloquées | `digest.py` |

**Stack technique** : stdlib Python + PyYAML, zéro réseau, zéro horloge interne, zéro LLM.

### 7.2 Repoussé GATED/T3

| Élément | Raison du report |
|---|---|
| Exécution réelle de Depth Pro | Poids modèle, GPU, infrastructure réseau. |
| Exécution réelle de DA-V2 | Idem. |
| Exécution réelle de Metric3D | Idem. |
| Capture guidée sur appareil | Interface mobile, SDK caméra, UX temps réel. |
| Toute inférence visuelle | Dépend des modèles ci-dessus. |
| Envoi d'un devis à un client | Engagement externe, exposition juridique. |
