# MODULE-ORDER-AND-DEFERRED-SURFACES — Ordre des modules et surfaces différées (C00-005)

`OPSYS_TASK_ID:C00-005`. Ce document fige l'ordre métier ratifié des 10
modules M1–M10 et documente précisément quelles surfaces sont DIFFÉRÉES
(pas supprimées) au-delà du programme Core, avec la distinction explicite
entre ce qui est dû TÔT (contrats) et ce qui reste dû À LA FIN (UI/polish
final).

## 1. Séquence complète Core-first → modules → surfaces finales

Source : `sources/continuity/key/68-CORE-FIRST-REPRIORITIZATION-DECISION-v5.6.0.md:12-17`
(« Décision de reprise — Core d'abord — v5.6.0 »).

```text
squelette vérifié
→ Core autoritatif et qualifié
→ M7 → M1 → M2 → M4 → M3 → M6 → M8 → M10 → M5 → M9
→ application mobile/cockpit/avatar complets
```

## 2. Ordre métier des 10 modules (CORE-002)

> M7 → M1 → M2 → M4 → M3 → M6 → M8 → M10 → M5 → M9

Source : `sources/continuity/key/02-CANON-NON-NEGOCIABLE.md:11`
(« Ordre métier actuel »), convergent avec
`sources/continuity/key/68-CORE-FIRST-REPRIORITIZATION-DECISION-v5.6.0.md:15`.

Aucune transposition, aucune omission : les 10 modules apparaissent une
seule fois chacun, dans cet ordre exact, entre le Core qualifié et
l'application mobile/cockpit/avatar complète.

## 3. Surface mobile — quatre profils préservés, différés (MOBILE-001, MOBILE-002)

> Surface officielle OPSYS-AI avec quatre profils : `ADMIN`, `VENDEUR`, `EMPLOYÉ`, `CLIENT`.

Source : `sources/continuity/key/02-CANON-NON-NEGOCIABLE.md:44`.

> `RF01-W12 Mobile Operations Bridge` est différé, non supprimé.

Source : `sources/continuity/key/68-CORE-FIRST-REPRIORITIZATION-DECISION-v5.6.0.md:21`.

La même source précise (ligne 22) : « Ses quatre profils, contrats, flux
offline, GPS/ETA, paiements et avatar restent canoniques. » —
c'est-à-dire que différer n'efface rien : les quatre profils `ADMIN`,
`VENDEUR`, `EMPLOYÉ` et `CLIENT` restent un invariant du canon, applicable
dès que le programme Core est complété.

## 4. Avatar/voix — contrat Core tôt, UI finale différée (AVATAR-002, VOIX-001)

> Core contracts for `ADMIN`, `VENDEUR`, `EMPLOYÉ`, `CLIENT`, offline sync, GPS windows, payments, notifications and avatar routing are frozen and tested early. The complete mobile application, 3D avatar and visual polish remain outside this Core implementation program.

Source : `sources/continuity/key/69-CORE-ARCHITECTURE-DESIGN-v1.0.0.md:107`.

`sources/continuity/key/19-MOBILE-APP-OPERATIONS-BRIDGE-CANON.md`, §11
« Stratégie de livraison », confirme la même distinction en deux temps :

- **Tôt dans le programme** (ligne 208-215) : contrats mobile/API, modèle
  d'identité et permissions, simulateur des quatre profils, verticales E2E
  minimales, preuve offline/sync, **provider ports pour paiement,
  notification, carte, profondeur et avatar**.
- **Fin du programme** (ligne 221-228) : application complète et design
  final, navigation et expérience cohérentes, **avatar/voix final**,
  optimisation mobile, accessibilité et polish, publication stores et
  lifecycle mobile, qualification E2E réelle des quatre profils.

Le contrat (routage, provider port, permissions) est donc dû TÔT ; l'UI
finale (rendu 3D, voix produite, polish) reste explicitement DIFFÉRÉE à la
fin du programme — jamais construite par le Core lui-même.

## 5. Portée de cette tâche

C00-005 documente cette séquence et cette distinction — elle ne modifie
aucun module M1–M10, n'implémente aucun provider port et ne construit
aucune surface mobile, avatar ou vocale. Voir `CORE-NON-GOALS-v2.md` pour
la liste exhaustive des non-objectifs de ce programme.
