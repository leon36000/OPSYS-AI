# CORE-CANON-v2 — Canon Core scellé (C00-005)

`OPSYS_TASK_ID:C00-005`. Ce document fige les invariants du Core partagé
d'OPSYS-AI avant toute complétion de département (M1–M10). Chaque énoncé
ci-dessous est une citation SOURCÉE, transcrite verbatim (apostrophe
typographique comprise) depuis l'une des 5 sources à relire du Task Spec
— jamais une reformulation ni une interprétation libre. Le lien exact
`id → source_ref → acceptance_ref` est porté par `CanonRequirement` dans
`audit/core-baseline/tests/test_core_canon_coverage.py`, qui vérifie
mécaniquement (jamais par lecture humaine seule) que chaque énoncé est
réellement présent ici ou dans les 2 autres sorties de cette tâche.

## 1. Décision Core-first (CORE-001)

> OPSYS-AI doit maintenant produire, ratifier puis exécuter le Core partagé avant toute complétion de département.

Source : `sources/continuity/key/68-CORE-FIRST-REPRIORITIZATION-DECISION-v5.6.0.md:8` (« Décision de reprise — Core
d'abord — v5.6.0 », statut ACTIVE / USER-RATIFIED, 2026-08-08).

Conséquence directe : aucun travail métier M1–M10 ni interface finale
n'est autorisé pendant l'exécution du Core (détaillé dans
`CORE-NON-GOALS-v2.md`). L'ordre exact des 10 modules qui suit cette
étape Core est détaillé dans `MODULE-ORDER-AND-DEFERRED-SURFACES.md`.

## 2. Application mobile — surface, jamais autorité (MOBILE)

L'application mobile est un pont humain entre M1–M10, jamais une vérité
métier indépendante. Ses quatre profils officiels (`ADMIN`, `VENDEUR`,
`EMPLOYÉ`, `CLIENT`) sont préservés et différés — détail complet, y
compris la citation exacte des quatre profils, dans
`MODULE-ORDER-AND-DEFERRED-SURFACES.md`.

## 3. Avatar — surface transversale, jamais source de vérité (AVATAR-001)

> L’avatar est une surface transversale du Core. Il route vers le module autoritatif et ne devient jamais source de vérité.

Source : `sources/continuity/key/02-CANON-NON-NEGOCIABLE.md:39`.

La suite de cette même source précise : « Les conseils fiscaux/juridiques
restent préparatoires, sourcés et soumis aux professionnels requis. » —
rejoint l'invariant juridique (§4) et l'invariant de contrat Core précoce
détaillé dans `MODULE-ORDER-AND-DEFERRED-SURFACES.md` (AVATAR-002 :
`ADMIN`/`VENDEUR`/`EMPLOYÉ`/`CLIENT`, offline sync, GPS windows,
paiements, notifications et routage avatar gelés et testés tôt ; UI
mobile complète, avatar 3D et polish visuel restent hors de ce programme
Core).

## 4. Juridique — toujours gated (JURIDIQUE-001)

> tout acte juridique reste gated

Source : `sources/continuity/key/02-CANON-NON-NEGOCIABLE.md:50`
(« M5 possède l'AR; M1 exécute les communications; tout acte juridique
reste gated. »).

Détail intermodule (`sources/continuity/key/19-MOBILE-APP-OPERATIONS-BRIDGE-CANON.md`,
§7 « Recouvrement et juridique ») : le *Legal & Compliance Service/Core*
prépare les documents juridiques et vérifie la juridiction, mais aucun
courrier juridique, mise en demeure, transmission à une agence ou action
légale ne peut être envoyé sans validation humaine et, selon le cas,
juridique professionnelle. La procédure reste configurable par
juridiction, contrat, type de client, litige et politique — un seuil
(ex. 30 jours) est une règle métier candidate, jamais une loi universelle
à coder en dur.

## 5. Paiements — fournisseurs tokenisés uniquement (PAIEMENTS-001)

> Paiements via fournisseurs tokenisés; aucune donnée complète de carte dans OPSYS-AI.

Source : `sources/continuity/key/02-CANON-NON-NEGOCIABLE.md:49`.

Règles non négociables associées
(`sources/continuity/key/19-MOBILE-APP-OPERATIONS-BRIDGE-CANON.md`, §6) :
OPSYS-AI et l'employé ne voient ni ne stockent les numéros complets de
carte ; aucune donnée de carte dans les logs, captures, RAG ou mémoire ;
webhooks signés, idempotence, reçus et rapprochement M5 ; aucun
remboursement, débit ou correction financière sans gate M5. M1 transmet
les notifications et communications ; il ne décide jamais qu'une facture
est due ou payée.

## 6. Recouvrement — workflow intermodule gated (RECOUVREMENT-001)

> D-MOB-008 : M5 possède l’AR; M1 exécute les communications de recouvrement.

Source : `sources/continuity/key/19-MOBILE-APP-OPERATIONS-BRIDGE-CANON.md:254`.

Le recouvrement est un workflow intermodule complet, jamais un module
isolé : **M5** possède l'AR, l'échéance, le solde, le litige et le statut
de paiement ; **M1** exécute les courriels, appels, SMS et suivis
autorisés ; **M2** conserve l'historique client et les engagements ;
**Legal & Compliance Service/Core** prépare les documents juridiques et
vérifie la juridiction ; **M9** peut signaler un risque ou proposer une
stratégie, sans déclencher l'action ; **M10** conserve les décisions et
preuves selon rétention légale.

## Portée de cette tâche

Cette tâche (C00-005) fige la DOCUMENTATION du canon — elle n'implémente,
ne modifie ni ne complète aucune logique métier M1–M10, aucun code de
`core/src/`, ni aucun des mécanismes cités ci-dessus (Legal & Compliance
Service, gates de paiement, workflow de recouvrement). Ces citations
établissent le canon à respecter par les tâches Core et les modules
ultérieurs — leur implémentation reste hors périmètre de C00-005.
