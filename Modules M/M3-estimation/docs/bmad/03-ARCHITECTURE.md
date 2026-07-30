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
| `contrats.py` | Définition des schémas gelés `LeadQualifie` (entrée) et `EstimationV1` (sortie) avec leurs listes fermées de clés. | D-015 : les contrats gelés sont des pactes exécutables, leur schéma doit être figé dans un fichier dédié. |
| `validation.py` | Validation structurelle du contrat d'entrée `LeadQualifie` : champs obligatoires, types, cohérence du sha256, détection des champs interdits. | Séparé de l'orchestration pour permettre un rejet précoce avant tout traitement coûteux. |
| `qualite_photos.py` | Qualification binaire de la qualité des entrées visuelles à partir des métadonnées photo. | Logique isolée car elle détermine le branchement fail-closed / estimation. |
| `hierarchie_echelle.py` | Application de la hiérarchie ratifiée comme logique de décision pure : référence > multi-vues > mono-vue à bornes larges > indéterminé. | Séparé pour garantir qu'aucun modèle d'inférence ne puisse s'y glisser en v1. |
| `monte_carlo.py` | Simulation Monte Carlo déterministe à graine fournie par l'appelant, production de l'intervalle de confiance. | Isolé pour garantir l'auditabilité du déterminisme (CA-M3-10, CA-M3-11, CA-M3-20). |
| `plancher.py` | Confrontation de la borne basse au plancher rentable, émission de l'alerte rouge. | Logique simple mais métier-critique, isolée pour testabilité directe. |
| `devis.py` | Dérivation du `devis_id` par encodage canonique injectif (préfixage par longueur + sha256). | Copie-adaptation du patron d'encodage canonique prouvé dans les modules voisins. |
| `registre.py` | Registre append-only hash-chaîné des estimations émises ; API ajouter / lire / valider chaîne. | Copie-adaptation du patron de registre hash-chaîné prouvé dans M2. |
| `digest.py` | Production du digest quotidien déterministe des estimations bloquées et des alertes de plancher vers Nathan. | Isolé car consommateur en lecture seule du registre, sans effet sur l'estimation. |
| `signaux.py` | Émission du signal de relance structuré vers M2 sur photos faibles (max 1 par estimation). | Isolé pour garantir la contrainte de fréquence et l'absence de boucle. |
| `estimation.py` | Orchestrateur principal : séquence validation → qualité → hiérarchie → Monte Carlo → plancher → contrat de sortie → registre. | Un seul orchestrateur garantit que l'ordre des étapes ne peut être altéré. |

---

## 2. SCHÉMAS DE DONNÉES

### 2.1 Contrat d'entrée — `LeadQualifie` (reçu de M2)

Schéma gelé, liste FERMÉE de clés. Tout champ absent ou supplémentaire provoque le rejet `CONTRAT_ENTREE_INVALIDE`.

```yaml
LeadQualifie:
  lead_id: str              # Identifiant stable du lead, attribué par M2.
  sha256: str               # Empreinte sha256 du contrat gelé, épinglée pour traçabilité.
  owner: str                # Owner humain confirmé (prénom + nom ou identifiant interne).
  type_travaux: str         # Type de travaux validé (enum fermé M2).
  ville: str                # Ville renseignée, non vide.
  interactions:             # Au moins une interaction humaine post-qualification.
    - type: str             # Type d'interaction (appel, visite, courriel, message).
      horodatage: str       # ISO 8601 avec fuseau obligatoire.
      resume: str           # Résumé factuel, sans engagement.
  photos:                   # Liste des entrées visuelles (métadonnées uniquement, pas de blobs).
    - photo_id: str         # Identifiant stable de la photo.
      resolution_largeur: int   # Largeur en pixels.
      resolution_hauteur: int   # Hauteur en pixels.
      eclairage: float      # Niveau d'éclairage (échelle 0-10).
      angle: str            # Identifiant d'angle (ex: "face", "gauche_45", "droite_45").
      reference_echelle:    # Optionnel — objet de dimensions certifiées visible.
        type: str           # Type d'objet (porte_standard, brique, carreau, metre_ruban).
        dimensions_connues: bool  # True si les dimensions sont certifiées.
  contexte:                 # Informations contextuelles additionnelles.
    urgence_declaree: str   # Niveau d'urgence déclaré par le client (basse, moyenne, haute).
    canal_entree: str       # Canal d'entrée du lead (telephone, courriel, formulaire, message).
```

**Clés interdites** (rejet immédiat si présentes) : `prix`, `montant`, `date_execution`, `engagement`, `tva`, `montant_ttc`, `conditions_paiement`, `creneau`, `duree`.

### 2.2 Contrat de sortie — `EstimationV1` (émis vers M4)

Schéma gelé, liste FERMÉE de clés. Copié mot pour mot du PRD section 5.

```yaml
EstimationV1:
  devis_id: str
    # Dérivé par encodage canonique injectif :
    # encodage = f"{len(lead_id):04d}{lead_id}{len(lead_sha256):04d}{lead_sha256}"
    # devis_id = "M3-DEVIS-" + sha256(encodage).hexdigest()[:16]
    # Injectif car lead_id est unique et lead_sha256 est unique par contrat gelé.

  lead_id: str
    # Identifiant stable du lead source, transmis par M2.

  lead_sha256: str
    # Empreinte sha256 du contrat gelé LeadQualifie d'entrée, épinglée pour traçabilité.

  niveau_confiance: str
    # Enum NiveauConfiance : REFERENCE_ECHELLE | MULTI_VUES | MONO_VUE_BORNES_LARGES | INDETERMINE

  verdict_blocage: str
    # Enum VerdictEstimation : AUCUN_BLOCAGE | QUALITE_ENTREE_INSUFFISANTE |
    # REFERENCE_ECHELLE_ABSENTE | PLANCHER_RENTABILITE_FRANCHI |
    # CONTRAT_ENTREE_INVALIDE | INDETERMINE

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

### 2.3 Énumérés fermés

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

### 2.4 Maillon du registre append-only

```yaml
MaillonEstimation:
  index: int                # Position séquentielle dans le registre (0, 1, 2, ...).
  devis_id: str             # Référence au devis émis.
  lead_id: str              # Référence au lead source.
  niveau_confiance: str     # Enum NiveauConfiance.
  verdict_blocage: str      # Enum VerdictEstimation.
  prix_bloque: bool         # Copie du champ du contrat de sortie.
  borne_basse: float | null # Copie du champ du contrat de sortie.
  borne_haute: float | null # Copie du champ du contrat de sortie.
  alerte_plancher: bool     # Copie du champ du contrat de sortie.
  hash_precedent: str       # sha256 du maillon précédent (chaîne vide pour index 0).
  hash_maillon: str         # sha256 de ce maillon (inclut hash_precedent).
```

### 2.5 Signal de relance vers M2

```yaml
SignalRelanceM2:
  type: str                 # Toujours "DEMANDE_ENTREES_VISUELLES".
  lead_id: str              # Lead concerné.
  devis_id: str             # Devis bloqué correspondant.
  elements_manquants:       # Liste explicite des éléments nécessaires.
    - str
  emission_count: int       # Toujours 1 en v1 (pas de boucle).
```

### 2.6 Digest quotidien vers Nathan

```yaml
DigestEstimationsBloquees:
  type: str                 # Toujours "DIGEST_ESTIMATIONS_BLOQUEES".
  nb_estimations_bloquees: int
  nb_alertes_plancher: int
  estimations_bloquees:
    - devis_id: str
      lead_id: str
      verdict_blocage: str
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

### 3.1 Interface d'entrée — ce que M3 reçoit de M2

M3 reçoit un contrat gelé `LeadQualifie` ayant franchi la **readiness gate M2** :
- `owner` humain confirmé (non vide, non null).
- `type_travaux` validé (appartient à l'enum fermé M2).
- `ville` renseignée (non vide).
- Au moins une interaction humaine post-qualification dans `interactions`.
- `sha256` cohérent avec le contenu du contrat.

M3 reçoit également deux paramètres d'appel hors contrat :
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

**Décision** : Le `devis_id` est dérivé par encodage canonique injectif : `encodage = f"{len(lead_id):04d}{lead_id}{len(lead_sha256):04d}{lead_sha256}"`, puis `devis_id = "M3-DEVIS-" + sha256(encodage).hexdigest()[:16]`. Le préfixage par longueur garantit l'injectivité (pas de collision par concaténation ambiguë).

**Justification** : Copie-adaptation du patron d'encodage canonique prouvé dans les modules voisins. L'injectivité garantit que deux leads différents produisent toujours des `devis_id` distincts (CA-M3-15), et que le même lead produit toujours le même `devis_id` (CA-M3-14).

### DA-M3-08 — Raisons de blocage non accusatoires (R-020)

**Décision** : Les raisons de blocage décrivent les éléments manquants sans attribuer de faute. Formulation : « référence d'échelle non identifiée dans les photos fournies » et non « le technicien n'a pas fourni de référence d'échelle ».

**Justification** : R-020 — aucune formulation accusatoire. Les raisons de blocage sont des constats factuels, pas des jugements. Cette règle est appliquée dans `qualite_photos.py` et `estimation.py` lors de la construction du champ `raison_blocage`.

---

### Décision — le barème de coûts est une ENTRÉE, jamais une donnée du module

Le module ne porte aucune valeur monétaire en dur. Le barème est fourni par l'appelant, exactement
comme la graine du Monte Carlo et comme le référentiel géographique l'est pour le module voisin.
Parce que : une simulation sans modèle sous-jacent produit des bornes arbitraires, et un barème
codé en dur deviendrait faux au premier changement de tarif sans que rien ne le signale. Piège
écarté : émettre un intervalle d'apparence rigoureuse — le Monte Carlo est déterministe et
reproductible — alors que ses paramètres sont inventés. Sans barème utilisable pour le
`type_travaux` demandé, l'estimation est BLOQUÉE avec `INDETERMINE` (CA-M3-21).

## 5. CE QUE CHAQUE STORY PROUVE

| Story | Ce qu'elle prouve |
|---|---|
| **S001** — Validation du contrat d'entrée LeadQualifie | Prouve que M3 accepte un contrat valide et rejette explicitement tout contrat invalide ou contenant un champ interdit, avec verdict nommé (CA-M3-01, CA-M3-02, CA-M3-03). |
| **S002** — Qualification de la qualité des entrées visuelles | Prouve que des photos faibles (résolution sous seuil, éclairage insuffisant, ou liste vide) produisent un blocage du prix avec verdict explicite et signal de relance vers M2 (CA-M3-04). |
| **S003** — Hiérarchie des références d'échelle | Prouve que la classification des niveaux de confiance (REFERENCE_ECHELLE, MULTI_VUES, MONO_VUE_BORNES_LARGES, INDETERMINE) est appliquée comme logique de décision pure sur les métadonnées, sans aucun modèle d'inférence (CA-M3-05, CA-M3-06, CA-M3-07, CA-M3-08). |
| **S004** — Garde anti-précision-inventée et prix bloqué | Prouve que lorsque le prix est bloqué, les bornes de l'intervalle sont null et la raison de blocage est non vide — aucun chiffre ne quitte M3 (CA-M3-09). |
| **S005** — Monte Carlo déterministe à graine fournie | Prouve la reproductibilité bit-à-bit pour la même graine et la divergence pour des graines différentes, sans aucun appel à random non ensemencé (CA-M3-10, CA-M3-11). |
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
