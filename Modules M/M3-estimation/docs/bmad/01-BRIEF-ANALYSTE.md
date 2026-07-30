# BRIEF ANALYSTE — MODULE M3 (ESTIMATION)

Rédigé par : Analyste BMAD | Statut : PROPOSÉ | Date : 2025-01-XX

## 1. BESOIN MÉTIER

M3 est le seul module de l'ensemble du système autorisé à porter un prix. Son mandat unique est de produire une estimation chiffrée d'une intervention à partir des éléments qualifiés transmis par M2, en garantissant qu'aucune précision inventée ne quitte le module. M3 reçoit un lead ayant franchi la readiness gate M2 (owner humain confirmé, type de travaux validé, ville renseignée, au moins une interaction humaine post-qualification), analyse la qualité des entrées visuelles et contextuelles disponibles, applique la hiérarchie ratifiée des références d'échelle, et émet un devis structuré portant un identifiant stable (`devis_id`) que M4 attend pour planifier l'intervention terrain. Les bénéficiaires directs sont l'équipe commerciale (qui reçoit un devis défendable, jamais un chiffre sorti de nulle part), M4 (qui reçoit un `devis_id` pour associer l'intervention à son estimation), M5 (qui facturera sur la base du devis émis), et Nathan (qui consulte les alertes de plancher rentable et les estimations bloquées). M3 ne planifie jamais d'intervention (rôle de M4), ne génère jamais de facture (rôle de M5), ne déduit jamais de stock (rôle de M6), et n'envoie jamais de devis directement à un client (engagement externe exclu du périmètre v1).

## 2. CONTRAINTES NON NÉGOCIABLES

### 2.1 Anti-précision-inventée

Une précision inventée n'est pas un défaut technique, c'est un danger commercial. Un prix émis avec une fausse précision (par exemple 4 827,33 € calculé sur des entrées insuffisantes) devient une promesse contractuelle aux yeux du client, expose l'entreprise à des réclamations, et détruit la confiance commerciale. M3 refuse d'émettre un prix précis quand les entrées ne le permettent pas. Le module émet un verdict explicite sur la qualité des entrées et, lorsque celles-ci sont insuffisantes, bloque le prix et signale la raison du blocage. Un schéma sans issue force la fabrication (D-032) : chaque enum de verdict porte une échappatoire obligatoire, et M3 ne choisit jamais par défaut la valeur la plus optimiste.

### 2.2 Photos faibles et prix bloqué

Les « photos faibles » désignent concrètement toute entrée visuelle qui ne permet pas d'établir une référence d'échelle fiable : absence de référence d'échelle connue (objet de dimensions certifiées visible dans le cadre), résolution insuffisante pour distinguer les éléments structurels, angle unique sans multi-vues permettant la triangulation, ou conditions d'éclairage rendant les profondeurs ininterprétables. Lorsque les photos sont qualifiées comme faibles, le prix est bloqué, le verdict est explicite, et le module signale quels éléments manquent pour débloquer l'estimation. M3 ne tente jamais de compenser des entrées faibles par une estimation hasardeuse.

### 2.3 Hiérarchie des références d'échelle

La hiérarchie ratifiée (consensus D-024) est une logique de décision stricte, appliquée dans cet ordre :

1. **Référence d'échelle** — un objet de dimensions certifiées est visible dans le cadre (porte standard, brique, carreau de carrelage, mètre ruban déployé). C'est la condition nécessaire et suffisante pour une estimation précise.
2. **Multi-vues** — plusieurs photos sous angles différents permettent une triangulation géométrique, en l'absence de référence d'échelle explicite. La précision est moindre mais acceptable avec bornes explicites.
3. **Mono-vue à bornes larges** — une seule photo sans référence d'échelle. L'estimation est produite avec des bornes larges (MAE ~0,45 m au mieux sans référence), et le verdict signale explicitement l'incertitude élevée.

M3 applique cette hiérarchie comme logique de décision pure en v1, sans exécuter aucun modèle d'inférence visuelle. Les candidats Depth Pro, DA-V2, et Metric3D sont identifiés mais repoussés en mode GATED/T3.

### 2.4 Plancher rentable et alerte rouge

Chaque estimation est confrontée à un plancher rentable configurable (coût minimal en dessous duquel l'intervention n'est pas viable économiquement). Si l'estimation basse (borne inférieure de l'intervalle de confiance) tombe sous le plancher rentable, M3 émet une alerte rouge explicite. Cette alerte ne bloque pas l'estimation mais signale au responsable commercial que le devis proposé expose l'entreprise à une marge négative ou nulle. Le plancher rentable est un paramètre d'entrée, jamais une valeur codée en dur.

### 2.5 Monte Carlo déterministe

L'estimation par simulation Monte Carlo est exécutée avec une graine fournie par l'appelant, garantissant un déterminisme reproductible. M3 n'utilise jamais `random` non ensemencé, jamais d'horloge interne, jamais de source d'aléa non contrôlée. Deux appels identiques avec la même graine produisent exactement le même résultat. Ce déterminisme est une exigence de traçabilité et de reproductibilité en CI.

### 2.6 Registre append-only estimé-vs-réel

M3 maintient un registre append-only des estimations émises, conçu pour permettre la mesure de l'écart entre l'estimation et le coût réel constaté après intervention (données remontées par M5 et M6). Ce registre est un outil d'apprentissage par mesure, pas un modèle entraîné : il accumule les données, ne fait pas d'inférence automatique, et ne modifie pas les paramètres d'estimation sans intervention humaine explicite.

## 3. FRONTIÈRES DU MODULE

### 3.1 Ce que M3 fait

- Reçoit un lead qualifié ayant franchi la readiness gate M2.
- Valide la qualité des entrées visuelles et contextuelles.
- Applique la hiérarchie des références d'échelle comme logique de décision.
- Émet un devis structuré avec `devis_id`, intervalle de confiance, verdict de qualité, et alerte de plancher rentable le cas échéant.
- Maintient le registre append-only estimé-vs-réel.
- Exécute les simulations Monte Carlo avec graine fournie par l'appelant.

### 3.2 Ce que M3 ne fait JAMAIS

- **Dates** — M3 ne planifie jamais d'intervention, ne propose jamais de créneau, ne calcule jamais de durée d'exécution. Les dates sont le domaine exclusif de M4.
- **Finance** — M3 ne génère jamais de facture, ne calcule jamais de TVA, ne gère jamais de paiement, ne déduit jamais de stock. La finance est le domaine exclusif de M5 et M6.
- **Envoi au client** — M3 n'envoie jamais de devis directement à un client. L'engagement externe est exclu du périmètre v1 et repoussé en mode GATED/T3.
- **Inférence visuelle réelle** — M3 n'exécute aucun modèle de vision par ordinateur en v1 (Depth Pro, DA-V2, Metric3D sont repoussés en GATED/T3). Le module applique la logique de décision de la hiérarchie des références d'échelle sans exécuter d'inférence.
- **Capture guidée** — M3 ne guide pas la capture photo sur l'appareil du technicien ou du client. Le guidage de capture est identifié comme levier mais repoussé en GATED/T3.

## 4. CONTRAT D'ENTRÉE

M3 consomme le contrat gelé `LeadQualifie` transmis par M2, portant :

- `lead_id` — identifiant stable du lead.
- `sha256` — empreinte du contrat gelé, épinglée pour traçabilité.
- `owner` — owner humain confirmé.
- `type_travaux` — type de travaux validé.
- `ville` — ville renseignée.
- `interactions` — au moins une interaction humaine post-qualification.
- `photos` — liste des entrées visuelles (métadonnées, pas de blobs binaires en v1).
- `contexte` — informations contextuelles additionnelles (urgence déclarée, canal d'entrée, etc.).

M3 valide la structure du contrat avant tout traitement et rejette explicitement toute entrée ne respectant pas le schéma gelé (D-015 : contrats gelés = pactes exécutables).

## 5. CONTRAT DE SORTIE

M3 émet un devis structuré portant :

- `devis_id` — identifiant stable du devis, transmis à M4 pour association avec l'intervention planifiée.
- `lead_id` — référence au lead source.
- `intervalle_confiance` — borne inférieure et borne supérieure de l'estimation.
- `verdict_qualite` — verdict explicite sur la qualité des entrées (référence d'échelle, multi-vues, mono-vue à bornes larges, ou photos faibles).
- `prix_bloque` — booléen indiquant si le prix est bloqué en raison d'entrées insuffisantes.
- `alerte_plancher` — booléen indiquant si l'estimation basse tombe sous le plancher rentable.
- `raison_blocage` — description explicite des éléments manquants si le prix est bloqué.
- `graine_monte_carlo` — graine utilisée pour la simulation, garantissant la reproductibilité.
- `hash_maillon` — hash du maillon append-only pour traçabilité.

Chaque enum de verdict porte une échappatoire obligatoire (D-032). M3 ne choisit jamais par défaut la valeur la plus optimiste et ne force jamais une sortie sans issue explicite.

## 6. MODE OMBRE ET MODE GATED

### 6.1 En périmètre v1 (mode ombre, prouvable en CI Python)

- La garde anti-précision-inventée : refus d'émettre un prix précis quand les entrées ne le permettent pas.
- La qualification de la qualité des entrées (photos faibles ⇒ prix bloqué, verdict explicite).
- La hiérarchie des références d'échelle comme logique de décision (référence d'échelle > multi-vues > mono à bornes larges), sans exécuter aucun modèle.
- Le plancher rentable et son alerte rouge.
- Monte Carlo à graine fournie par l'appelant (déterminisme reproductible).
- Le registre append-only estimé-vs-réel (apprentissage = mesure, pas de modèle entraîné).
- Le contrat gelé de sortie vers M4 (le `devis_id` que M4 attend).

### 6.2 Repoussé GATED/T3

- L'exécution réelle de Depth Pro, DA-V2, Metric3D (poids, réseau, GPU).
- La capture guidée sur appareil.
- Toute inférence visuelle.
- L'envoi d'un devis à un client (engagement externe).

## 7. CE QUE L'ANALYSTE PROPOSE ET QUE LE PM TRANCHERA

### 7.1 Seuil de qualification « photos faibles »

L'analyste propose de définir le seuil de qualification « photos faibles » comme toute entrée ne satisfaisant pas au minimum la condition « mono-vue à bornes larges » (une seule photo, résolution minimale configurable, éclairage suffisant pour distinguer les éléments structurels). Le PM tranchera sur les valeurs exactes des seuils de résolution et d'éclairage, et sur la possibilité d'introduire un niveau intermédiaire entre « photos faibles » et « mono-vue à bornes larges ».

### 7.2 Granularité de l'intervalle de confiance

L'analyste propose un intervalle de confiance à deux bornes (basse et haute) avec un niveau de confiance configurable (par défaut 90 %). Le PM tranchera sur la possibilité d'ajouter une estimation médiane (point estimate) en plus de l'intervalle, et sur le niveau de confiance par défaut.

### 7.3 Politique de relance sur photos faibles

L'analyste propose que M3 émette un signal de relance vers M2 lorsque le prix est bloqué en raison de photos faibles, demandant des entrées visuelles complémentaires. Le PM tranchera sur la fréquence maximale de relance, sur l'escalade vers le responsable commercial après N relances infructueuses, et sur la possibilité de clore le lead après un délai configurable sans réponse.

### 7.4 Alimentation du registre estimé-vs-réel

L'analyste propose que le registre estimé-vs-réel soit alimenté automatiquement par M5 (coût réel facturé) et M6 (coût réel des matériaux déstockés) après complétion de l'intervention. Le PM tranchera sur la fréquence de consolidation des écarts, sur les seuils d'alerte en cas de dérive systématique, et sur la possibilité d'ajuster manuellement les paramètres d'estimation sur la base des écarts constatés.

### 7.5 Visibilité du devis pour l'équipe commerciale

L'analyste propose que l'équipe commerciale consulte le devis émis par M3 via une interface de lecture seule, avec possibilité de demander une révision (qui déclenche une nouvelle estimation avec des entrées mises à jour). Le PM tranchera sur la possibilité pour l'équipe commerciale de modifier manuellement le devis avant transmission à M4, et sur les garde-fous nécessaires pour éviter qu'une modification manuelle ne contourne la garde anti-précision-inventée.
