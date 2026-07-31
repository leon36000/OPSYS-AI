# PRD — MODULE M3 (ESTIMATION)

Rédigé par : PM BMAD | Statut : PROPOSÉ | Date : 2025-01-XX

---

## 0. AJOUTS HORS PÉRIMÈTRE ANALYSTE

Le brief analyste (section 7) proposait plusieurs points à trancher. Le PM valide les ajouts suivants, absents du périmètre initial de l'analyste mais cohérents avec l'architecture globale :

1. **Signal de relance vers M2 sur photos faibles** — proposé par l'analyste en 7.3, validé en v1. M3 émet un signal structuré vers M2 lorsque le prix est bloqué pour qualité d'entrée insuffisante, demandant des entrées visuelles complémentaires. Fréquence maximale : 1 signal par estimation, pas de relance automatique en boucle.
2. **Digest des estimations bloquées vers Nathan** — extension du digest M2. Nathan reçoit un résumé quotidien des estimations bloquées et des alertes de plancher, cohérent avec son rôle de supervision.

Ces deux ajouts restent en mode ombre (logique pure, déterministe, zéro réseau).

---

## 1. PERSONAS

| Persona | Rôle | Interaction avec M3 |
|---|---|---|
| **Nathan** | Propriétaire de l'entreprise | Consulte le digest quotidien des estimations bloquées et des alertes de plancher rentable. Ne modifie jamais une estimation. |
| **Équipe commerciale** | Commerciaux terrain | Reçoit un devis défendable, jamais un chiffre inventé. Peut demander une révision via M2 (nouvelle estimation avec entrées mises à jour). |
| **Répartiteur** | Superviseur des opérations | Consulte les verdicts de blocage pour arbitrer les leads en attente d'entrées complémentaires. |
| **Technicien terrain** | Exécutant (bénéficiaire indirect) | Reçoit via M4 une intervention associée à un `devis_id`. N'interagit pas directement avec M3. |

---

## 2. PARCOURS PRINCIPAUX

### 2.1 Estimation depuis un lead prêt

**Précondition** : un lead a franchi la readiness gate M2 (owner humain confirmé, type de travaux validé, ville renseignée, au moins une interaction humaine post-qualification).

**Déroulement** :
1. M3 reçoit de M2 le contrat gelé `LeadQualifie` (sept clés) ET le marqueur de readiness signé, dont l'`empreinte` est l'épinglage de traçabilité — le cadrage initial la cherchait à tort sous le nom `sha256` dans le contrat (issue #166).
2. M3 valide la structure du contrat (rejet explicite si non conforme).
3. M3 analyse les métadonnées des photos fournies.
4. M3 applique la hiérarchie des références d'échelle : référence > multi-vues > mono-vue à bornes larges.
5. M3 exécute la simulation Monte Carlo avec la graine fournie par l'appelant.
6. M3 confronte la borne basse au plancher rentable.
7. M3 émet le contrat gelé `EstimationV1` avec `devis_id`, intervalle de confiance, verdict, et alerte le cas échéant.
8. M3 inscrit l'estimation dans le registre append-only.

**Postcondition** : un `devis_id` stable est disponible pour M4.

### 2.2 Estimation bloquée faute de qualité

**Précondition** : le lead a franchi la readiness gate M2, mais les photos sont qualifiées « faibles » (résolution sous le seuil, éclairage insuffisant, ou aucune photo).

**Déroulement** :
1. M3 reçoit et valide le contrat d'entrée.
2. M3 qualifie les entrées visuelles : verdict `QUALITE_ENTREE_INSUFFISANTE`.
3. M3 bloque le prix : `prix_bloque = True`, intervalle de confiance vide (`null`).
4. M3 émet le contrat `EstimationV1` avec `raison_blocage` explicite listant les éléments manquants.
5. M3 émet un signal de relance vers M2 demandant des entrées visuelles complémentaires.
6. Nathan reçoit l'alerte dans son digest quotidien.

**Postcondition** : aucun chiffre n'a quitté M3. Le lead reste dans M2 en attente de complétion.

### 2.3 Révision après réalisation

**Précondition** : une intervention a été complétée (WCT émis par M4), et M5/M6 ont remonté le coût réel.

**Déroulement** :
1. Le registre append-only de M3 reçoit le coût réel (facturé par M5, matériaux déstockés par M6).
2. M3 calcule l'écart entre l'estimation (borne basse, borne haute) et le coût réel.
3. L'écart est inscrit dans le registre, sans modification automatique des paramètres d'estimation.
4. Si l'écart dépasse un seuil configurable, une alerte est émise vers Nathan.

**Postcondition** : le registre accumule les données d'apprentissage. Aucun modèle n'est réentraîné automatiquement.

---

## 3. PÉRIMÈTRE V1 vs ROADMAP

### 3.1 En périmètre v1 (mode ombre, prouvable en CI Python)

| Élément | Description |
|---|---|
| Garde anti-précision-inventée | Refus d'émettre un prix précis quand les entrées ne le permettent pas |
| Qualification de la qualité des entrées | Photos faibles ⇒ prix bloqué, verdict explicite |
| Hiérarchie des références d'échelle | Logique de décision pure : référence > multi-vues > mono à bornes larges |
| Plancher rentable | Alert rouge si borne basse sous le plancher configurable |
| Monte Carlo déterministe | Graine fournie par l'appelant, reproductibilité bit-à-bit |
| Registre append-only estimé-vs-réel | Accumulation des écarts, pas de modèle entraîné |
| Contrat gelé de sortie `EstimationV1` | `devis_id` stable pour M4 |
| Signal de relance vers M2 | Sur photos faibles, une seule relance par estimation |
| Digest des estimations bloquées | Vers Nathan, quotidien, déterministe |

**Stack technique** : stdlib Python + PyYAML, zéro réseau, zéro horloge interne, zéro LLM.

### 3.2 Repoussé GATED/T3

| Élément | Raison du report |
|---|---|
| Exécution réelle de Depth Pro | Poids modèle, GPU, infrastructure réseau |
| Exécution réelle de DA-V2 | Idem |
| Exécution réelle de Metric3D | Idem |
| Capture guidée sur appareil | Interface mobile, SDK caméra, UX temps réel |
| Toute inférence visuelle | Dépend des modèles ci-dessus |
| Envoi d'un devis à un client | Engagement externe, exposition juridique |

---

## 4. ÉNUMÉRÉS FERMÉS

### 4.1 NiveauConfiance

Énuméré fermé classifiant la qualité de la base d'estimation. Chaque valeur a une condition d'obtention stricte. Conformément à D-032, une échappatoire obligatoire est prévue.

| Valeur | Condition d'obtention |
|---|---|
| `REFERENCE_ECHELLE` | Au moins une photo dont les métadonnées déclarent un objet de dimensions certifiées visible dans le cadre (porte standard, brique, carreau de carrelage, mètre ruban déployé). Condition nécessaire et suffisante pour une estimation précise. |
| `MULTI_VUES` | Au moins 3 photos sous angles différents (métadonnées `angle` distincts), résolution ≥ seuil configurable, sans référence d'échelle déclarée. Précision moindre, bornes explicites. |
| `MONO_VUE_BORNES_LARGES` | 1 ou 2 photos, résolution ≥ seuil configurable, éclairage suffisant (métadonnées `eclairage` ≥ seuil), sans référence d'échelle, sans multi-vues. MAE ~0,45 m au mieux. |
| `INDETERMINE` | **Échappatoire D-032** — les métadonnées fournies ne permettent de classifier dans aucun des trois niveaux précédents. Ce verdict signale « on ne sait pas » et force un blocage du prix. |

### 4.2 VerdictEstimation

> **Renommé** (revue scellée du cadrage, 3 relecteurs sur 3) : l'énuméré s'appelait
> `VerdictBlocage`, or trois de ses six valeurs portent `prix_bloque: False`. Un nom qui
> affirme un blocage que le booléen contredit est la même classe de défaut qu'une docstring
> contredisant son code. La sémantique de blocage est portée par le champ `prix_bloque`, seul
> et sans ambiguïté ; l'énuméré, lui, qualifie l'ISSUE de l'estimation.

Énuméré fermé des verdicts émis par M3 concernant le statut de l'estimation. Le champ booléen `prix_bloque` indique l'effectivité du blocage. Conformément à D-032, une échappatoire obligatoire est prévue.

| Valeur | Signification | `prix_bloque` |
|---|---|---|
| `AUCUN_BLOCAGE` | Estimation émise normalement, intervalle de confiance calculé. | `False` |
| `QUALITE_ENTREE_INSUFFISANTE` | Photos faibles : résolution sous le seuil, éclairage insuffisant, ou aucune photo fournie. Le prix ne peut pas être estimé. | `True` |
| `REFERENCE_ECHELLE_ABSENTE` | Aucune référence d'échelle identifiée dans les photos. Signalé comme alerte, mais ne bloque pas si le niveau de confiance est `MULTI_VUES` ou `MONO_VUE_BORNES_LARGES`. | `False` |
| `PLANCHER_RENTABILITE_FRANCHI` | La borne basse de l'intervalle de confiance est strictement inférieure au plancher rentable fourni. Alerte rouge : marge négative ou nulle possible. Ne bloque pas l'estimation. | `False` |
| `CONTRAT_ENTREE_INVALIDE` | Le contrat `LeadQualifie` d'entrée ne respecte pas le schéma gelé (champ manquant, type incorrect, champ interdit présent). | `True` |
| `INDETERMINE` | **Échappatoire D-032** — la raison du blocage ne peut être classifiée dans les valeurs précédentes. Signale « on ne sait pas pourquoi ça bloque » et force une revue humaine. | `True` |

---

## 5. CONTRAT GELÉ `EstimationV1`

> **Barème de coûts (ajout après revue scellée)** : le module ne porte AUCUNE valeur de coût.
> Le barème est un paramètre d'ENTRÉE fourni par l'appelant, au même titre que la graine du
> Monte Carlo et que le référentiel géographique de M4. Sans barème couvrant le `type_travaux`
> demandé, l'estimation est bloquée avec `INDETERMINE` : produire des bornes sans modèle serait
> une précision inventée, ce que ce module existe précisément pour empêcher.

Conformément à D-015, ce contrat est un pacte exécutable. Tout champ est obligatoire sauf mention explicite. Aucun champ de date ni de finance ne figure dans ce contrat.

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
- Aucune date (ni date d'exécution, ni créneau, ni durée) — domaine de M4.
- Aucun champ financier (ni TVA, ni montant TTC, ni conditions de paiement) — domaine de M5.
- Aucun identifiant de stock ou de matériau — domaine de M6.

---

## 6. CRITÈRES D'ACCEPTATION

21 critères numérotés, chacun testable déterministiquement, chacun porté par une story unique.

| ID | Critère | Moyen de vérification | Story |
|---|---|---|---|
| CA-M3-01 | Le contrat gelé `LeadQualifie` de M2 (SEPT clés) et le marqueur de readiness signé par M2 sont validés ensemble ; une entrée conforme retourne un accusé structuré. | Test unitaire : contrat et marqueur valides -> acceptation ; le contrat validé est celui que M2 émet RÉELLEMENT, pas une variante durcie. | S001 |
| CA-M3-02 | Toute entrée non conforme est rejetée avec un verdict nommant la faute : contrat malformé, marqueur absent ou structurellement invalide, `readiness_ok` non vrai par identité, ou `lead_id` du marqueur différent de celui du contrat. | Test unitaire, un cas par classe de faute, chacun isolant SA faute. | S001 |
| CA-M3-03 | La readiness M2 est constatée par le MARQUEUR, jamais re-déduite : `owner` et « au moins une interaction post-qualification » sont des conditions vérifiées par M2 avant signature et absentes du contrat. La limite — validation STRUCTURELLE, sans recalcul de l'empreinte, M3 ne possédant pas le registre de M2 — est écrite dans la docstring du module et à côté du verdict. | Test unitaire : marqueur valide accepté ; assertion que la docstring déclare la limite. | S001 |
| CA-M3-04 | Des photos qualifiées « faibles » (résolution sous le seuil configurable, ou éclairage insuffisant, ou liste de photos vide) produisent `verdict_estimation = QUALITE_ENTREE_INSUFFISANTE` et `prix_bloque = True`. | Test unitaire : appel avec fixture photos faibles, assertion sur `verdict_estimation` et `prix_bloque`. | S002 |
| CA-M3-05 | Au moins une photo avec référence d'échelle déclarée dans les métadonnées (objet de dimensions certifiées) produit `niveau_confiance = REFERENCE_ECHELLE`. | Test unitaire : appel avec fixture référence échelle, assertion sur `niveau_confiance`. | S003 |
| CA-M3-06 | Au moins 3 photos sous angles différents (métadonnées `angle` distincts), résolution ≥ seuil, sans référence d'échelle, produisent `niveau_confiance = MULTI_VUES`. | Test unitaire : appel avec fixture multi-vues, assertion sur `niveau_confiance`. | S003 |
| CA-M3-07 | Une seule photo sans référence d'échelle, résolution ≥ seuil, éclairage suffisant, produit `niveau_confiance = MONO_VUE_BORNES_LARGES`. | Test unitaire : appel avec fixture mono-vue, assertion sur `niveau_confiance`. | S003 |
| CA-M3-08 | Des métadonnées photo ne permettant aucune classification (champs ambigus ou manquants) produisent `niveau_confiance = INDETERMINE`. | Test unitaire : appel avec fixture ambiguë, assertion sur `niveau_confiance`. | S003 |
| CA-M3-09 | Quand `prix_bloque = True`, `intervalle_confiance.borne_basse` et `intervalle_confiance.borne_haute` sont `null`, et `raison_blocage` est non vide. | Test unitaire : appel produisant un blocage, assertion nullité des bornes et non-nullité de la raison. | S004 |
| CA-M3-10 | Deux appels Monte Carlo avec la même graine et les mêmes entrées produisent exactement le même intervalle de confiance (égalité bit-à-bit des flottants). | Test unitaire : deux appels identiques, assertion `borne_basse_1 == borne_basse_2` et `borne_haute_1 == borne_haute_2`. | S005 |
| CA-M3-11 | Deux appels Monte Carlo avec des graines différentes et les mêmes entrées produisent des intervalles différents (au moins une borne diffère). | Test unitaire : deux appels avec graines distinctes, assertion `borne_basse_1 != borne_basse_2` ou `borne_haute_1 != borne_haute_2`. | S005 |
| CA-M3-12 | Quand la borne basse de l'intervalle est strictement inférieure au plancher rentable fourni en entrée, `alerte_plancher = True`. | Test unitaire : appel avec plancher élevé, assertion `alerte_plancher == True`. | S006 |
| CA-M3-13 | Quand la borne basse de l'intervalle est supérieure ou égale au plancher rentable fourni en entrée, `alerte_plancher = False`. | Test unitaire : appel avec plancher bas, assertion `alerte_plancher == False`. | S006 |
| CA-M3-14 | `devis_id` est dérivé par encodage canonique injectif (préfixage par longueur + sha256) à partir de `lead_id` et `empreinte_marqueur_m2`, et est reproductible pour les mêmes entrées. | Test unitaire : appel, vérification du format `M3-DEVIS-` + 16 hex, et reproductibilité sur deux appels. | S007 |
| CA-M3-15 | Deux leads différents (`lead_id` distincts) produisent des `devis_id` distincts. | Test unitaire : deux appels avec `lead_id` différents, assertion `devis_id_1 != devis_id_2`. | S007 |
| CA-M3-16 | Le contrat de sortie `EstimationV1` ne contient aucun champ de date (ni `date_execution`, ni `creneau`, ni `duree`) ni aucun champ financier (ni `tva`, ni `montant_ttc`, ni `conditions_paiement`). | Inspection du schéma de sortie : assertion absence des clés interdites. | S007 |
| CA-M3-17 | L'ajout d'une estimation au registre append-only préserve la chaîne de hash : le `hash_maillon` du nouveau maillon inclut le hash du maillon précédent. | Test unitaire : ajout de deux maillons successifs, assertion que le hash du second inclut le hash du premier. | S008 |
| CA-M3-18 | La validation de la chaîne complète du registre réussit quand aucun maillon n'a été altéré, et échoue quand un maillon est altéré. | Test unitaire : validation sur chaîne intacte (assertion succès), altération d'un maillon, re-validation (assertion échec). | S008 |
| CA-M3-19 | Tout enum du module (`NiveauConfiance`, `VerdictEstimation`) possède une valeur `INDETERMINE` comme échappatoire obligatoire (D-032). | Inspection des définitions d'enum : assertion présence de `INDETERMINE` dans chaque enum. | S009 |
| CA-M3-20 | Le module n'appelle jamais `random` sans graine, jamais d'horloge interne (`time.time`, `datetime.now`), jamais de réseau (`socket`, `urllib`, `requests`), et ne porte **aucun littéral numérique de coût** — les coûts viennent du barème fourni, jamais du code. | Analyse statique du code (AST Python) : assertion absence d'appels interdits dans tout le module M3. | S009 |
| CA-M3-21 | Le barème de coûts est **fourni par l'appelant** et jamais inventé : sans barème, ou avec un barème ne couvrant pas le `type_travaux` demandé, l'estimation est BLOQUÉE (`INDETERMINE`, `prix_bloque` vrai, bornes nulles) au lieu de produire des bornes arbitraires. | Appel sans barème puis avec barème incomplet : assertion `prix_bloque is True`, bornes `null`, `bareme_version` nul. | S005 |
| CA-M3-22 | Toute clé interdite (`prix`, `montant`, `date_execution`, `engagement`, `tva`, `montant_ttc`, `conditions_paiement`, `creneau`, `duree`) présente à N'IMPORTE quel niveau d'une entrée — contrat, marqueur ou photos — provoque un rejet EXPLICITE et DISTINCT du rejet générique de schéma. Rétabli après revue scellée : ma réécriture des critères d'entrée l'avait fait disparaître, alors que la détection récursive restait dans le périmètre — un contrôle sans critère se perd à l'implémentation. | Test unitaire : une clé interdite au sommet, une imbriquée dans `contact`, une dans un objet de `photos` ; assertion que le verdict est celui des clés interdites, PAS celui du schéma. | S001 |

---

## 7. STORIES

### S001 — Validation des entrées : contrat M2, marqueur de readiness, photos

| Attribut | Valeur |
|---|---|
| **Périmètre** | Validation conjointe du contrat gelé `LeadQualifie` (les SEPT clés que M2 émet réellement), du marqueur de readiness signé par M2, et des photos fournies séparément par l'appelant. Détection récursive des clés interdites sur toutes les entrées. La readiness est CONSTATÉE via le marqueur, jamais re-déduite : M3 ne possède pas le registre de M2 (limite déclarée). FRONTIÈRE AVEC S002, explicite : S001 valide la STRUCTURE des photos (liste, types, bornes des champs, clés fermées) et rien de plus ; la QUALITÉ — résolution et éclairage sous les seuils, absence de référence d'échelle, blocage du prix — appartient à S002, la story de qualification des entrées visuelles. Une structure valide n'est pas une qualité suffisante, et S001 ne se prononce jamais sur le prix. |
| **Critères portés** | CA-M3-01, CA-M3-02, CA-M3-03, CA-M3-22 |
| **Tier** | T2 (contrat gelé consommé) |
| **Dépendances** | Aucune |

### S002 — Qualification de la qualité des entrées visuelles

| Attribut | Valeur |
|---|---|
| **Périmètre** | Analyse des métadonnées des photos fournies dans le contrat d'entrée. Classification binaire : photos acceptables (au moins le seuil mono-vue) ou photos faibles. Émission du signal de relance vers M2 en cas de photos faibles. |
| **Critères portés** | CA-M3-04 |
| **Tier** | T1 |
| **Dépendances** | S001 |

### S003 — Hiérarchie des références d'échelle

| Attribut | Valeur |
|---|---|
| **Périmètre** | Application de la hiérarchie ratifiée comme logique de décision pure : référence d'échelle > multi-vues > mono-vue à bornes larges > indéterminé. Aucun modèle d'inférence visuelle exécuté. Classification basée uniquement sur les métadonnées des photos. |
| **Critères portés** | CA-M3-05, CA-M3-06, CA-M3-07, CA-M3-08 |
| **Tier** | T1 |
| **Dépendances** | S002 |

### S004 — Garde anti-précision-inventée et prix bloqué

| Attribut | Valeur |
|---|---|
| **Périmètre** | Quand le niveau de confiance est `INDETERMINE` ou le verdict est `QUALITE_ENTREE_INSUFFISANTE`, le prix est bloqué : intervalle de confiance vide (bornes `null`), `raison_blocage` explicite listant les éléments manquants. Aucun chiffre ne quitte M3 dans ce cas. |
| **Critères portés** | CA-M3-09 |
| **Tier** | T1 |
| **Dépendances** | S003 |

### S005 — Monte Carlo déterministe à graine fournie

| Attribut | Valeur |
|---|---|
| **Périmètre** | Simulation Monte Carlo pour produire l'intervalle de confiance. La graine ET le **barème de coûts** sont fournis par l'appelant (jamais `random` non ensemencé, jamais d'horloge, jamais de coût codé en dur). Reproductibilité bit-à-bit pour les mêmes entrées, la même graine et le même barème. Sans barème utilisable, l'estimation est bloquée plutôt qu'inventée — objection de revue scellée : une simulation sans modèle sous-jacent produit des bornes arbitraires, soit exactement la précision inventée que le module doit empêcher. |
| **Critères portés** | CA-M3-10, CA-M3-11, CA-M3-21 |
| **Tier** | T1 |
| **Dépendances** | S003 |

### S006 — Plancher rentable et alerte rouge

| Attribut | Valeur |
|---|---|
| **Périmètre** | Confrontation de la borne basse de l'intervalle au plancher rentable fourni en entrée (paramètre configurable, jamais codé en dur). Émission de l'alerte `alerte_plancher = True` si la borne basse est strictement inférieure au plancher. L'alerte ne bloque pas l'estimation. |
| **Critères portés** | CA-M3-12, CA-M3-13 |
| **Tier** | T1 |
| **Dépendances** | S005 |

### S007 — Contrat de sortie EstimationV1 et devis_id

| Attribut | Valeur |
|---|---|
| **Périmètre** | Assemblage du contrat gelé `EstimationV1` avec tous ses champs obligatoires. Dérivation du `devis_id` par encodage canonique injectif (préfixage par longueur + sha256). Garantie d'absence de tout champ de date ou de finance dans le contrat de sortie. |
| **Critères portés** | CA-M3-14, CA-M3-15, CA-M3-16 |
| **Tier** | T2 (contrat gelé émis) |
| **Dépendances** | S004, S005, S006 |

### S008 — Registre append-only estimé-vs-réel

| Attribut | Valeur |
|---|---|
| **Périmètre** | Maintien d'un registre append-only hash-chaîné des estimations émises. Chaque maillon contient le devis, l'intervalle, et le hash du maillon précédent. API : ajouter, lire, valider chaîne. Conçu pour recevoir ultérieurement le coût réel (M5/M6) et mesurer les écarts. |
| **Critères portés** | CA-M3-17, CA-M3-18 |
| **Tier** | T1 |
| **Dépendances** | S007 |

### S009 — Échappatoires D-032 et conformité déterministe

| Attribut | Valeur |
|---|---|
| **Périmètre** | Vérification transversale que tout enum du module porte une échappatoire `INDETERMINE` (D-032). Vérification par analyse statique (AST) qu'aucun appel à `random` non ensemencé, aucune horloge interne, et aucun réseau n'existe dans le code du module. Digest quotidien déterministe des estimations bloquées et des alertes de plancher vers Nathan. |
| **Critères portés** | CA-M3-19, CA-M3-20 |
| **Tier** | T1 |
| **Dépendances** | S001, S002, S003, S004, S005, S006, S007, S008 |

---

## 8. DÉCISIONS TRANSVERSALES APPLICABLES

| Décision | Application dans M3 |
|---|---|
| **D-032** — Échappatoire obligatoire sur tout enum | `NiveauConfiance.INDETERMINE` et `VerdictEstimation.INDETERMINE` — un schéma sans issue force la fabrication |
| **D-015** — Contrats gelés = pactes exécutables | `LeadQualifie` (entrée) et `EstimationV1` (sortie) sont des schémas stricts, validés avant tout traitement |
| **Loi 25** — Minimisation | M3 ne collecte que les métadonnées photo nécessaires à la classification, jamais les blobs binaires en v1 |
| **Loi 96** — Français d'abord | Tous les verdicts, raisons de blocage, et messages d'erreur sont en français |
| **R-020** — Aucune formulation accusatoire | Les raisons de blocage décrivent les éléments manquants sans attribuer de faute (« référence d'échelle non identifiée » et non « le technicien n'a pas fourni de référence ») |

---

## 9. PARAMÈTRES CONFIGURABLES

| Paramètre | Description | Valeur par défaut |
|---|---|---|
| `seuil_resolution_min` | Résolution minimale (en pixels) pour qu'une photo soit acceptable | Défini par le PM |
| `seuil_eclairage_min` | Niveau d'éclairage minimal (échelle 0-10) pour qu'une photo soit acceptable | Défini par le PM |
| `niveau_confiance_defaut` | Niveau de confiance de l'intervalle Monte Carlo | 0.90 |
| `plancher_rentable` | Coût minimal en dessous duquel l'alerte rouge est émise | Fourni par l'appelant à chaque estimation |
| `nb_iterations_monte_carlo` | Nombre d'itérations de la simulation Monte Carlo | Défini par le PM |
| `bareme_couts` | Contrat gelé `BaremeCouts` : version, unité, postes par type de travaux avec bornes de coût | **Fourni par l'appelant à chaque estimation. Aucune valeur par défaut : un barème par défaut serait un coût inventé** |

---
