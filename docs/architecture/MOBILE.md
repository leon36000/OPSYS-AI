# Application mobile OPSYS

> Réécrit par PLAN T1.4-a (2026-09-28) : remplace la version périmée qui prévoyait un fork des
> apps natives OpenClaw (« phase 2 »). Décision en vigueur : **nouvelle app Expo/React Native,
> réutilisant le protocole et l'appairage d'OpenClaw, pas son code d'interface** — voir
> [ADR-0008](../decisions/ADR-0008-fork-openclaw-opsys-core.md) et le détail technique complet
> dans [`docs/research/R12-app-mobile.md`](../research/R12-app-mobile.md) (pile §3, synchro §4,
> écrans §5, sécurité §6). Ce fichier résume ; R12 fait foi sur le détail et les preuves.

## État actuel : squelette seulement

`mobile/` contient le **squelette** livré par PLAN T1.4-a : projet, routage par rôle, file
sortante et client protocole en logique pure et testée — **aucun écran métier**. Étapes
suivantes (R12 §5, ordre de livraison) : T1.4-b (idempotence côté socle), T1.4-c (protocole
d'appairage), puis `punch.tsx`, `today.tsx`/`job/[id]`, `checklist`/`photos`/`signature`,
`complete`→`materials` (M6.10), `(admin)/approvals`, E2E Maestro.

## Pile (R12 §3 — versions et licences vérifiées)

Expo SDK 57 (`expo` 57.0.25) + Expo Router 57.0.23 + TypeScript strict, React Native 0.86.3.
Stockage local : `expo-sqlite` (moteur libSQL). i18n : i18next + react-i18next +
expo-localization. Génération d'UUID côté appareil : `expo-crypto`. Toutes MIT, sauf TypeScript
(Apache-2.0) — les deux licences sont acceptées (AGENTS.md). Détail brique par brique, licences
et écarts de version : [`docs/research/INGREDIENTS.md`](../research/INGREDIENTS.md) (section
« Mobile ») et le rapport final de PLAN T1.4-a.

Volontairement **pas encore installés** à ce stade (aucun écran ne les utilise) : caméra,
notifications, signature, formulaires (react-hook-form/zod), TanStack Query, `expo-secure-store`.
Ils entrent avec les tranches qui en ont besoin, jamais par anticipation.

## Rôles et routage (`src/roles/`)

Quatre profils (DEFINITION-PRODUIT §9) = quatre groupes Expo Router : `(employee)`, `(seller)`,
`(admin)`, `(client)`. `src/roles/garde.ts` exporte `evaluerGarde(session, groupeCible)`, une
fonction **pure** : rôle du jeton d'appareil → groupe autorisé (mappage un-à-un, R12 §6), fail-
closed (session absente, rôle inconnu et rôle valide mais différent du groupe visé refusent
tous les trois, vers `/pairing`). Chaque `_layout.tsx` de groupe appelle cette garde avant de
rendre quoi que ce soit — un jeton `employee` n'atteint donc jamais `(admin)`, y compris par URL
directe. `src/roles/contexte.tsx` porte l'état de session en React Context ; il démarre toujours
`{ presente: false }` (voir Appairage ci-dessous). 147 tests Jest couvrent la garde (matrice rôle
× groupe complète, session absente, rôles inconnus) et la file sortante.

Chaque groupe a un écran d'accueil minimal et distinctement nommé (`(employee)/employee.tsx`,
etc.) plutôt qu'un `index.tsx` par groupe : Expo Router retire les segments `(parenthèses)` de
l'URL, donc quatre `index.tsx` entreraient tous en conflit sur `/`.

## Appairage — à faire (PLAN T1.4-c)

`app/pairing/index.tsx` explique l'appairage et affiche l'état (toujours « non apparié » pour
l'instant) : **aucun protocole n'est implémenté**, ni QR, ni code, ni écriture de jeton. R12 §1.3
documente le protocole du fork à reprendre (`connect` → `connect.challenge` → charge signée v3 →
`hello-ok`, jeton d'appareil scellé par rôle) ; l'algorithme de signature exact restait à
confirmer dans le code du fork au moment de R12 (§6, recommandation de suivi). R12 §6 signale
aussi un préalable côté fork : des **rôles d'opérateur nommés** (`admin`/`employee`/`seller`),
faute de quoi un jeton employé aurait la portée d'un jeton propriétaire — à durcir avant de
livrer l'appairage réel, pas seulement côté app.

## File sortante (`src/outbox/`, R12 §4)

Logique pure, séparée du stockage :
- `mutation.ts` : `creerMutation` (id fourni par l'appelant — `src/outbox/id.ts` l'obtient de
  `expo-crypto` `randomUUID()` sur l'appareil, avant tout réseau) et les transitions
  `brouillon → en_attente → envoi → envoyee | echec_permanent` ; toute autre transition lève
  (`transitions.ts` tient le graphe fermé, testé exhaustivement sur les 25 paires possibles).
- `recul.ts` : recul exponentiel 1 s → 30 s (×2), fonction pure à partir d'un `maintenant`
  injecté.
- `planification.ts` : ordre d'envoi par chantier puis par heure de création, une mutation
  jamais envoyée avant que sa `dependsOn` soit `envoyee` ; une ligne retrouvée `envoi` au
  démarrage est resélectionnée avec le même id (reprise, jamais recréée).
- `depot.ts` (interface `DepotOutbox` + implémentation mémoire, utilisée par les tests) et
  `depot.sqlite.ts` (adaptateur réel, DDL de la table `outbox`) — non exercé par les tests
  unitaires (pas de SQLite natif sous Jest), seulement par une future vérification sur appareil.

## `/tools/invoke` sans tour de modèle (`src/protocole/`)

Client typé de `POST /tools/invoke`, conforme à la lecture directe du fork (lecture seule —
`core/src/gateway/tools-invoke-http.ts`, `tools-invoke-shared.ts` ; jamais exécuté ici, ADR-0008 :
le core ne se construit/teste qu'en CI). Requête `{ tool, args, action?, sessionKey?, agentId?,
idempotencyKey? }`, en-tête `authorization: Bearer <jeton>`, réponse `{ ok: true, result }` ou
`{ ok: false, error: { type, message } }` (types fermés : `invalid_request`, `not_found`,
`tool_call_blocked`, `tool_error`). `fetch` est injecté (testable sans réseau). Classement des
échecs : réseau/délai et HTTP 408/429/5xx → réessayable ; les autres 4xx → permanent —
`src/protocole/classification.ts`. `idempotencyKey` doit porter le `mutation_id` de
`src/outbox` pour tout appel émis par la file sortante ; **le branchement réel entre les deux
(boucle de vidage) n'est pas encore écrit**, seuls les deux modules indépendants le sont.

## Idempotence côté socle — à faire (PLAN T1.4-b)

`idempotencyKey` protège contre le double envoi côté client (reprise après crash, réseau
instable) ; il ne vaut que si le moteur métier Python l'applique en vérité (R12 §4 : table
`mutations_appliquees`, clé `(appareil, idempotencyKey)`, avant d'agir). C'est le travail de
PLAN T1.4-b, côté `src/opsys`/départements — hors périmètre de `mobile/`.

## Sécurité

Jeton d'appareil et clé d'appairage : `expo-secure-store` (Keychain iOS / Keystore Android),
jamais en base SQLite ni `AsyncStorage` (R12 §6) — **pas encore câblé** : rien ne stocke de
jeton tant que l'appairage (T1.4-c) n'existe pas. Vues par rôle appliquées deux fois (serveur ET
app, R12 §6) ; ici, uniquement la moitié app (`evaluerGarde`) est livrée. Consentement GPS,
photos/signature : politiques Loi 25 citées par R12 §6, hors périmètre de ce squelette (aucun
écran ne capte encore ces données).

## Ce qui n'est PAS encore fait

Pas d'écran métier (cédule, punch, checklist, matériaux, approbations, etc.) ; pas de protocole
d'appairage réel (T1.4-c) ; pas de stockage sécurisé de jeton (`expo-secure-store` non installé) ;
pas de boucle de vidage reliant `src/outbox` à `src/protocole` ; pas d'idempotence côté socle
(T1.4-b) ; pas de caméra, notifications push, signature, ni de GPS ; pas de tests E2E Maestro ;
pas de build EAS ni de publication store (frontière humaine T3, R12 §3).
