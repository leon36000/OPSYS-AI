# Application mobile OPSYS

> Réécrit par PLAN T1.4-a (2026-09-28) : remplace la version périmée qui prévoyait un fork des
> apps natives OpenClaw (« phase 2 »). Décision en vigueur : **nouvelle app Expo/React Native,
> réutilisant le protocole et l'appairage d'OpenClaw, pas son code d'interface** — voir
> [ADR-0008](../decisions/ADR-0008-fork-openclaw-opsys-core.md) et le détail technique complet
> dans [`docs/research/R12-app-mobile.md`](../research/R12-app-mobile.md) (pile §3, synchro §4,
> écrans §5, sécurité §6). Ce fichier résume ; R12 fait foi sur le détail et les preuves.

## État actuel : appairage réel + premier écran métier (T1.4-c3)

`mobile/` contenait, jusqu'à T1.4-a, un **squelette** (projet, routage par rôle, file sortante
et client protocole en logique pure) sans écran métier. T1.4-d a livré `punch.tsx` (M4.4) et le
« vidangeur » qui relie `src/outbox` à `src/protocole` (R12 §5 étape 2), mais sans configuration
de connexion réelle (`obtenirConfigurationAppel` renvoyait toujours `null`, faute d'appairage).
**T1.4-c3 livre le CLIENT D'APPAIRAGE réel** (`src/appairage/`) : identité d'appareil Ed25519
générée sur l'appareil, protocole `connect`/`connect.challenge`/`hello-ok` lu et reproduit
fidèlement depuis le fork, écran de saisie de code, stockage sécurisé du jeton, et branchement
du rôle reçu sur la garde de routes existante — voir « Appairage » ci-dessous pour le détail et
les limites (T1.4-c2, encore côté core, reste un préalable pour que le rôle reçu soit
`admin`/`employee`/`seller` en production). Étapes suivantes (R12 §5, ordre de livraison) :
`today.tsx`/`job/[id]`, `checklist`/`photos`/`signature`, `complete`→`materials` (M6.10),
`(admin)/approvals`, E2E Maestro. T1.4-b (idempotence côté socle) est fait côté serveur — voir
[`IDEMPOTENCE.md`](IDEMPOTENCE.md) — mais son branchement CÔTÉ CORE (`_meta` MCP) reste à faire
en T1.4-c1 (détail dans la section « `/tools/invoke` » ci-dessous).

## Pile (R12 §3 — versions et licences vérifiées)

Expo SDK 57 (`expo` 57.0.25) + Expo Router 57.0.23 + TypeScript strict, React Native 0.86.3.
Stockage local : `expo-sqlite` (moteur libSQL), désormais réellement câblé par
`src/outbox/service.ts` (voir « Vidangeur » ci-dessous). i18n : i18next + react-i18next +
expo-localization. Génération d'UUID côté appareil : `expo-crypto`. Détection réseau (T1.4-d) :
`@react-native-community/netinfo` 12.0.1, MIT. Toutes MIT, sauf TypeScript (Apache-2.0) — les
deux licences sont acceptées (AGENTS.md). Détail brique par brique, licences et écarts de
version : `docs/research/INGREDIENTS.md` (section « Mobile ») et le rapport final de PLAN
T1.4-a.

Depuis T1.4-c3 : `expo-secure-store` (jeton d'appareil et clé secrète Ed25519, jamais SQLite ni
`AsyncStorage` — R12 §6) et, pour la signature du défi d'appairage, `@noble/curves` (Ed25519,
algorithme confirmé en lisant le fork — voir « Appairage ») + `@noble/hashes` (SHA-256, dérivation
du `deviceId`). Volontairement **pas encore installés** à ce stade (aucun écran n'en a encore
besoin) : caméra (donc pas de lecture QR — voir « Appairage », code saisi seulement),
notifications, signature manuscrite, formulaires (react-hook-form/zod), TanStack Query,
`expo-location`/`expo-task-manager` (GPS — voir « Écran `punch.tsx` » : la lecture Loi 25
« fenêtre bornée » de R12 §6 n'est pas encore confirmée par Nathan/juriste),
`@testing-library/react-native` (absent de la pile installée — `punch.tsx` et l'écran
d'appairage sont donc testés via leur logique extraite en fonctions pures, jamais en rendu). Ils
entrent avec les tranches qui en ont besoin, jamais par anticipation.

## Rôles et routage (`src/roles/`)

Quatre profils (DEFINITION-PRODUIT §9) = quatre groupes Expo Router : `(employee)`, `(seller)`,
`(admin)`, `(client)`. `src/roles/garde.ts` exporte `evaluerGarde(session, groupeCible)`, une
fonction **pure** : rôle du jeton d'appareil → groupe autorisé (mappage un-à-un, R12 §6), fail-
closed (session absente, rôle inconnu et rôle valide mais différent du groupe visé refusent
tous les trois, vers `/pairing`). Chaque `_layout.tsx` de groupe appelle cette garde avant de
rendre quoi que ce soit — un jeton `employee` n'atteint donc jamais `(admin)`, y compris par URL
directe. `src/roles/contexte.tsx` porte l'état de session en React Context ; il démarre toujours
`{ presente: false }` au premier rendu (`app/_layout.tsx` la restaure ensuite depuis
`expo-secure-store` si une session persistée existe — voir « Appairage » ci-dessous). 312 tests
Jest couvrent la garde (matrice rôle × groupe complète, session absente, rôles inconnus), la
file sortante, le vidangeur (faux transport), le contrat `m4_pointer`, les déclencheurs, la
logique de `punch.tsx`, et désormais le client d'appairage (`src/appairage/`, T1.4-c3).

Chaque groupe a un écran d'accueil minimal et distinctement nommé (`(employee)/employee.tsx`,
etc.) plutôt qu'un `index.tsx` par groupe : Expo Router retire les segments `(parenthèses)` de
l'URL, donc quatre `index.tsx` entreraient tous en conflit sur `/`.

## Appairage (PLAN T1.4-c3)

### Algorithme et format — confirmés en lisant le fork (lecture seule, jamais exécuté, ADR-0008)

R12 §1.3 documentait la séquence `connect` → `connect.challenge` → charge signée v3 → `hello-ok`
mais signalait l'algorithme de signature exact comme « à vérifier ». C'est fait :

- **Séquence sur le fil** (Wire v4, un seul WebSocket par tentative) : à l'ouverture, le serveur
  pousse SANS sollicitation un évènement `{type:"event", event:"connect.challenge",
  payload:{nonce, ts, capabilities}}` (`core/src/gateway/server/connection.ts:333-343`). Le
  client répond par une requête `{type:"req", id, method:"connect", params: ConnectParams}`
  (`core/packages/gateway-client/src/protocol-client.ts:352`, forme exacte de `ConnectParams`
  dans `core/packages/gateway-protocol/src/schema/frames.ts:38-100`). Le serveur répond soit
  `{type:"res", ok:true, payload: HelloOk}` (`HelloOkSchema`, `frames.ts:103-156` :
  `payload.auth = {deviceToken, role, scopes, ...}`), soit `{type:"res", ok:false,
  error:{details:{code:"PAIRING_REQUIRED", reason:"not-paired", requestId, ...}}}` tant que le
  propriétaire n'a pas approuvé (`core/packages/gateway-protocol/src/connect-error-details.ts:46,54-59`,
  émis par `core/src/gateway/server/ws-connection/connect-device-pairing.ts`) — R12 §1.3
  « approbation en deux temps » : `shouldAllowSilentLocalPairing` refuse TOUJOURS l'auto-
  approbation silencieuse pour une connexion distante (`locality === "remote"`,
  `handshake-auth-helpers.ts:92-93`), ce qui couvre le cas d'un téléphone sur Internet.
- **Charge signée v3** — `buildDeviceAuthPayloadV3`/`normalizeDeviceMetadataForAuth`
  (`core/packages/gateway-client/src/device-auth.ts:1-64`) :
  `"v3|" + deviceId + "|" + clientId + "|" + clientMode + "|" + role + "|" + scopes.join(",") +
  "|" + signedAtMs + "|" + (token ?? "") + "|" + nonce + "|" + normaliser(platform) + "|" +
  normaliser(deviceFamily)`, où `normaliser` ne touche QUE les lettres ASCII A-Z (vérifié par un
  vecteur du fork : `"İOS"` → `"İos"`, pas une casse Unicode complète). Portée sur
  `mobile/src/appairage/chargeV3.ts`, testée OCTET PAR OCTET contre des vecteurs recopiés
  tels quels de `core/src/gateway/device-auth.test.ts` et
  `core/packages/gateway-client/src/browser-device-auth.test.ts` (`chargeV3.test.ts`).
- **Signature : Ed25519 pur (EdDSA RFC 8032, sans pré-hachage)**, confirmé dans
  `core/src/infra/ed25519-signature.ts:170-174,199-211` (`crypto.sign(null, ...)`/`crypto.verify(null,
  ...)` sur une clé Ed25519 — l'argument `null` est ce qui distingue le EdDSA pur du variant
  « ph » préhaché). Clé publique/signature encodées en base64url SANS remplissage
  (`base64UrlEncode` = `Buffer#toString("base64url")`). `deviceId` = hex minuscule de
  `sha256(clé publique brute 32 octets)` (`core/src/infra/device-identity.ts:176-187`,
  `deriveDeviceIdFromPublicKey`) — **vérifié par le serveur à chaque connexion**
  (`core/src/gateway/server/ws-connection/connect-device-proof.ts:64-68` : tout écart rejette la
  connexion, `device-id-mismatch`), donc pas un détail optionnel. Signature acceptée si
  `|Date.now() - signedAt| ≤ 2 min` (`connect-device-proof.ts:14,70-73`) et si `nonce` == celui du
  défi reçu sur CETTE connexion (à usage unique). Brique : **`@noble/curves`** (Ed25519) +
  **`@noble/hashes`** (SHA-256), MIT, implémentations JS auditées, confirmées comme LE bon choix
  (R12 §3 les citait comme « piste » avant vérification). Portées sur `src/appairage/identite.ts`,
  **vérifiées octet pour octet contre Node `crypto`** dans `identite.test.ts` — un vecteur
  (graine fixe → clé publique/signature/`deviceId` attendus) où le test signe avec `@noble/curves`
  ET reconstruit indépendamment une clé PEM Ed25519 (préfixes DER lus dans
  `ed25519-signature.ts:4-5`) pour que Node `crypto.verify`/`crypto.sign(null,...)` — jamais du
  code de `core/`, seulement le module `crypto` intégré à Node — confirme la même signature.
- **Code/QR** — `oc-pair://` + base64url(JSON `{url, urls?, bootstrapToken, expiresAtMs?,
  tlsFingerprint?}`), port de `decodePairingSetupCode`/`encodePairingSetupCode`
  (`core/src/pairing/setup-code.ts:414-494`) dans `src/appairage/codeAppairage.ts` : `url` est
  l'URL WebSocket de la passerelle, `bootstrapToken` le jeton d'amorçage à usage unique (R12
  §1.3, 10 min — vérifié aussi côté client via `expiresAtMs` quand il est présent, le serveur
  fait de toute façon foi). `bootstrapToken` voyage comme `auth.bootstrapToken` ET comme `token`
  dans la charge v3 signée (même rôle que dans `selectGatewayConnectAuth`,
  `core/packages/gateway-client/src/connect-auth.ts:45-51`).

### Décision d'intégration — client minimal, pas un import de `core/`

Mission : réutiliser `@openclaw/gateway-client/browser` + `@openclaw/gateway-protocol`
(chemin local, copie vendorisée, ou publication), sinon écrire un client minimal testé contre le
protocole lu. **Retenu : client minimal** (`src/appairage/`), pour trois raisons qui se
recoupent :

1. **La contrainte du mandat l'exige.** `core/` est lecture seule ET « n'exécute jamais son
   code » dans ce bac à sable (AGENTS.md, mission). Un chemin local
   (`"@openclaw/gateway-client": "file:../core/packages/gateway-client"`) ferait exécuter du
   TypeScript de `core/` PAR `npm test`/`npm run typecheck` de `mobile/` lui-même dès que Jest
   résout l'import — précisément ce qui est interdit, même si c'est « seulement » depuis
   `mobile/`. Une copie vendorisée verbatim des DEUX paquets (`gateway-protocol` : ~270 fichiers
   de schémas TypeBox, presque tous sans rapport avec l'appairage ; `gateway-client` :
   `protocol-client.ts` à lui seul 635 lignes, machine à états pensée pour une session agent
   persistante — reconnexion à recul, files de requêtes multiplexées, écouteurs d'évènements,
   dépendance `@openclaw/retry`) recréerait exactement le problème que R12 §2 reproche au fork
   natif OpenClaw rejeté : une grosse base à maintenir pour un besoin étroit. Publier ces paquets
   en interne (npm privé/GitHub Packages) est hors de portée d'une seule tranche et ne lève de
   toute façon pas la première objection (le code exécuté resterait celui de `core/`).
2. **Le besoin réel est étroit.** L'app n'a besoin du protocole WebSocket que pour la POIGNÉE DE
   MAIN d'appairage — une fois le jeton d'appareil obtenu, la socket est FERMÉE et tout le reste
   passe par `POST /tools/invoke` (HTTP, déjà écrit dans `src/protocole/client.ts`, R12 §1.2 :
   « la porte déterministe ... jamais par un tour de modèle/session persistante »). Un client
   minimal qui ne fait QUE `connect`→`connect.challenge`→`hello-ok` (avec recul entre tentatives
   pendant l'attente d'approbation) suffit entièrement ; rien dans `protocol-client.ts` au-delà
   de cette poignée de main n'a d'utilité pour ce cas d'usage.
3. **Testabilité totale sans jamais toucher `core/`.** Chaque brique du protocole
   (`chargeV3.ts`, `identite.ts`, `codeAppairage.ts`, `client.ts`) est une fonction pure ou une
   machine à états avec socket/horloge/sommeil INJECTÉS (même discipline que
   `src/protocole/client.ts`/`src/outbox/vidangeur.ts`), testée contre des vecteurs recopiés
   littéralement des tests du fork (lus, jamais exécutés) et contre Node `crypto` comme oracle
   indépendant pour la partie cryptographique — voir ci-dessus.

**Limite connue, à lever une fois le fork durci (T1.4-c2 ou une tâche core dédiée) :**
`GATEWAY_CLIENT_IDS` (`core/packages/gateway-protocol/src/client-info.ts:10-29`) est un
catalogue FERMÉ sans identifiant OPSYS — `ConnectParams.client.id` doit être une valeur connue
du fork, sous peine d'échec de schéma. `src/appairage/clientInfo.ts` emprunte donc
`openclaw-ios`/`openclaw-android` selon la plateforme, faute de mieux. Ce n'est pas cosmétique :
`isNativeAppUiClient` (`handshake-auth-helpers.ts:37-45`) classe ces id comme des clients natifs
de confiance OpenClaw — un enregistrement dédié (`GATEWAY_CLIENT_IDS.OPSYS_MOBILE` ou
équivalent) est un changement CORE, hors périmètre (lecture seule) de cette tranche.

### Ce que fait l'écran (`app/pairing/index.tsx`)

Saisie du **code seulement** (pas de lecture QR — `expo-camera` alourdirait cette tranche pour un
gain marginal tant que le code peut être copié/collé ou tapé ; à ajouter dans une tranche dédiée
si le besoin terrain le justifie). Au bouton « Appairer » : `chargerOuCreerIdentite` (première
fois : graine aléatoire `expo-crypto.getRandomBytes(32)` → identité Ed25519, persistée ; fois
suivantes : relit la même identité — le `deviceId` reste stable pour l'historique d'approbation
côté propriétaire) → `appairerAppareil` (`src/appairage/client.ts`, la machine à états décrite
ci-dessus, avec recul exponentiel réutilisé tel quel de `src/outbox/recul.ts` entre les
tentatives pendant l'attente d'approbation) → au succès, `sauvegarderSession` (jeton, rôle, URL,
`appareilId`) dans `expo-secure-store`, `definirConfigurationAppel` (`src/protocole
/configuration.ts`) et `definirSession` (`src/roles/contexte.tsx`) sont appelés, puis
`router.replace("/")` laisse `app/index.tsx` rediriger vers le bon groupe (ou revenir à
`/pairing` si le rôle reste inconnu — voir plus bas). `app/_layout.tsx` restaure la même session
au démarrage (`RestaurationSession`, lit `expo-secure-store` une fois) sans repasser par un
nouvel appairage. Écran non testé en rendu (même limite que `punch.tsx`, pas de
`@testing-library/react-native`) ; toute la logique sous-jacente l'est, exhaustivement.

### Rôle reçu -> garde de routes existante, et ce qui attend T1.4-c2

`hello.auth.role` (chaîne libre côté protocole) est stocké TEL QUEL dans `SessionAppareil.role`
et alimente directement `src/roles/garde.ts` (`evaluerGarde`), sans traduction ni mappage codé en
dur ici — c'est voulu. **Aujourd'hui, le fork non modifié ne connaît que deux rôles de
transport, `"operator"`/`"node"`** (`core/src/gateway/role-policy.types.ts:2`), pas de rôles
nommés OPSYS (`admin`/`employee`/`seller`) : `src/appairage/client.ts` demande `role:"operator"`
(seule valeur qui passe la validation du fork actuel pour un appareil humain), et c'est très
probablement CE QUE le serveur renverra dans `hello.auth.role` tant que **T1.4-c2** (« rôles
nommés sur le jeton d'appareil, attribués à l'approbation de l'appairage avec la personne OPSYS »,
PLAN.md) n'est pas livré côté core. `"operator"` n'est PAS un profil connu de
`src/roles/types.ts` (`PROFILS = admin|employee|seller|client`), donc `evaluerGarde` le refuse
déjà correctement (`role_inconnu`, fail-closed, testé exhaustivement dans `garde.test.ts`,
INCHANGÉ par cette tranche) et renvoie vers `/pairing` — **l'appairage réussit, le jeton et le
rôle sont bien stockés, mais aucun écran métier n'est atteignable en production tant que
T1.4-c2 n'a pas remplacé `"operator"` par un rôle nommé.** C'est le comportement CORRECT
(P2, fail-closed) : mieux vaut un appareil apparié mais bloqué à `/pairing` qu'un rôle deviné.
Rien côté mobile n'a besoin de changer quand T1.4-c2 livrera les rôles nommés : le chemin
`hello.auth.role → SessionAppareil.role → evaluerGarde` est déjà générique.

## File sortante (`src/outbox/`, R12 §4)

Logique pure, séparée du stockage :
- `mutation.ts` : `creerMutation` (id fourni par l'appelant — `src/outbox/id.ts` l'obtient de
  `expo-crypto` `randomUUID()` sur l'appareil, avant tout réseau) et les transitions
  `brouillon → en_attente → envoi → envoyee | echec_permanent` ; toute autre transition lève
  (`transitions.ts` tient le graphe fermé, testé exhaustivement sur les 25 paires possibles).
- `recul.ts` : recul exponentiel 1 s → 30 s (×2), fonction pure à partir d'un `maintenant`
  injecté.
- `planification.ts` : ordre d'envoi par chantier puis par `sequence`, une mutation jamais
  envoyée avant que sa `dependsOn` soit `envoyee` (ni avant qu'un ANCÊTRE plus lointain le soit —
  voir « mutations bloquées » ci-dessous) ; une ligne retrouvée `envoi` au démarrage est
  resélectionnée avec le même id (reprise, jamais recréée), sans attendre son recul.
- `depot.ts` (interface `DepotOutbox` + implémentation mémoire, utilisée par les tests) et
  `depot.sqlite.ts` (adaptateur réel, DDL de la table `outbox`) — non exercé par les tests
  unitaires (pas de SQLite natif sous Jest), seulement par une future vérification sur appareil.

**Trois corrections (relecture post-T1.4-a, avant que T1.4-d/punch ne s'appuie dessus) :**

1. **Le recul est maintenant appliqué à la sélection.** `MutationOutbox.prochaineTentativeA`
   (instant UTC, `null` = due immédiatement) est posé par `marquerEchecReessayable(mutation,
   maintenant)` à partir de `calculerProchaineTentativeA` (`recul.ts`) — avant cette correction,
   ce champ n'existait pas et `selectionnerProchainesEnvoyables` renvoyait tout de suite une
   mutation qui venait d'échouer, recul ou pas. `selectionnerProchainesEnvoyables` prend
   maintenant un `maintenant: Date` injecté et exclut toute `en_attente` pas encore due ; une
   reprise (`envoi`) reste toujours due, recul ou pas (ce n'est pas un échec à espacer, c'est un
   redémarrage). Colonne SQLite : `prochaine_tentative_a TEXT`.
2. **L'ordre repose sur `sequence`, pas sur `createdAtLocal`.** `MutationOutbox.sequence` est un
   entier strictement croissant assigné par le DÉPÔT à l'insertion (`DepotOutboxMemoire` : un
   compteur ; `depot.sqlite.ts` : calculé par sous-requête dans le même `INSERT ... RETURNING`,
   `id` restant la clé primaire UUID). `createdAtLocal` (texte d'heure locale AVEC décalage) ne
   sert plus qu'à l'affichage : comparé comme du texte, il se compare mal d'un décalage à
   l'autre — ex. le passage à l'heure normale (1er novembre, -04:00 EDT → -05:00 EST) peut faire
   trier une mutation postérieure AVANT une antérieure. Testé explicitement
   (`mutation.test.ts`, `planification.test.ts`).
3. **Les mutations bloquées par un échec permanent sont maintenant identifiables.**
   `identifierMutationsBloqueesParEchecPermanent` (nouvelle fonction pure) remonte toute la
   chaîne `dependsOn` — pas seulement le parent direct — et retourne les mutations `en_attente`/
   `envoi` dont un ANCÊTRE quelconque est `echec_permanent`. Avant cette correction, ces
   mutations restaient `en_attente` indéfiniment sans que rien ne le signale — contraire à R12
   §4 (« ne jamais perdre silencieusement un événement mis en file »). Cette fonction ne change
   rien à l'envoi (déjà correctement bloqué) ; elle sert à ce qu'une future interface d'alerte
   (`(admin)/approvals` ou équivalent) puisse les montrer. Testé sur une chaîne à trois niveaux.

## Vidangeur (`src/outbox/vidangeur.ts`, R12 §4, T1.4-d)

Le branchement qui manquait entre `src/outbox` (file) et `src/protocole` (client
`/tools/invoke`) est maintenant écrit. `creerVidangeur(config)` : logique pure d'orchestration
(rien n'est lu en dur — dépôt, `fetch`, URL, jeton, identité d'appareil, horloge sont tous
injectés dans `ConfigurationVidangeur`), donc entièrement testable avec un faux transport
(`src/outbox/vidangeur.test.ts`, faux `fetch`). `src/outbox/service.ts` fournit la configuration
réelle (SQLite via `expo-sqlite`, `fetch` global) — non testé unitairement, même raison que
`depot.sqlite.ts` (pas de SQLite natif sous Jest).

Séquence par mutation envoyable (`selectionnerProchainesEnvoyables`, `maintenant` injecté) :
`envoi` (ou reprise si déjà `envoi` — jamais retransitionnée, R12 §4) → appel
`/tools/invoke` avec `idempotencyKey = mutation.id` (**toujours** la même clé, y compris au
renvoi après une réponse perdue ou une reprise après crash) → `envoyee` si accepté,
`en_attente` + recul si réessayable (réseau/408/429/5xx), `echec_permanent` sinon — soit un
échec HTTP définitif (400/403/404), soit un **rejet business** (`accepte: false`, HTTP 200, voir
« Écran `punch.tsx` » ci-dessous). Dans les deux cas d'échec permanent, `RapportVidange` porte le
verdict `{code, detail}` normalisé, pour affichage (mission item 2). Les descendants bloqués par
un ancêtre en `echec_permanent` sont signalés dans `RapportVidange.bloquees`
(`identifierMutationsBloqueesParEchecPermanent`), jamais silencieusement oubliés.

**Verrou simple** : un booléen fermé sur la closure de `creerVidangeur` — un appel à
`vidangerFileSortante()` pendant qu'une vidange est déjà en cours n'en démarre PAS une seconde ;
il renvoie immédiatement `{ignoreeVerrouActif: true}` sans bloquer l'appelant. Rien n'est perdu :
le prochain déclencheur reprendra ce qu'il reste en file.

**Déclencheurs** (`src/outbox/declencheurs.ts`) : premier plan (`AppState`, état `"active"`) et
retour du réseau (`@react-native-community/netinfo`, `isConnected: true`) — les deux prévus par
la mission. `punch.tsx` déclenche EN PLUS une vidange immédiate juste après avoir mis sa propre
mutation en file (best-effort, pour ne pas attendre le prochain changement d'état/réseau quand
l'appareil est déjà en ligne) — ajout au-delà des deux déclencheurs nommés, sans rien changer au
verrou. Les deux modules sont testés avec de faux fournisseurs `AppState`/`NetInfo` injectés
(`declencheurs.test.ts`) ; une erreur de la couche stockage pendant une vidange déclenchée en
arrière-plan est journalisée (`console.error`) et n'atteint jamais l'écran.

**Descripteurs** (`src/outbox/descripteurs.ts`) : associe chaque `TypeMutation` à l'outil réel à
appeler et à l'interprète de sa réponse business. Seuls `punch_in`/`punch_out` sont enregistrés
dans cette tranche (→ `m4_pointer`) ; les tranches suivantes y ajoutent les leurs
(`materials_submit` → `m6_soumettre_materiaux_utilises`, etc.) sans toucher à `vidangeur.ts`.

## Écran `punch.tsx` (M4.4, T1.4-d)

`app/(employee)/punch.tsx` : entrée, sortie, pause — **exactement** ce que l'outil réel accepte
(`departments/m04-field-ops/src/m4_field_ops/outils.py`, `m4_pointer`, lu, jamais exécuté ni
modifié ici ; `pointage.ACTIONS = (arrivee, depart, pause_debut, pause_fin)`). La logique (machine
à états locale, extraction heure/minute, dérivation de l'état de synchro affiché) est **pure**,
dans `src/ecrans/punch.ts`, testée là (21 tests) ; `punch.tsx` ne fait que le câblage React — non
testé en rendu, `@testing-library/react-native` n'étant pas dans la pile installée (ni en
dépendance, ni résolu dans `package-lock.json` : seule une mention en pair optionnel d'un autre
paquet y apparaît).

**Mapping type de mutation ↔ action réelle (décision de cette tranche, à noter car ni R12 ni le
catalogue `TypeMutation` de T1.4-a n'anticipaient la pause).** La mission demande de ne créer que
des mutations `punch_in`/`punch_out` ; `pointage.ACTIONS` en a quatre. Choix retenu : `punch_in`
= l'employé DEVIENT présent/actif (arrivée OU fin de pause), `punch_out` = l'employé DEVIENT
absent (départ OU début de pause) — l'action `m4_pointer` exacte voyage dans `payload.action`,
jamais dans le type de mutation. Bouton « Pause » bascule entre `pause_debut`/`pause_fin` selon
la phase locale (`src/ecrans/punch.ts`, `resoudreActionEmploye`, fail-closed : toute paire
phase/action hors du graphe renvoie `null`).

**Ce que `m4_pointer` exige et que cette tranche ne peut PAS encore fournir avec de vraies
données** (`fix_gps`, `fenetre_travail`, `referentiel_villes`, `ville`, `sel`) : isolé dans
`src/m4/contextePointageProvisoire.ts`, un seul fichier, clairement documenté comme provisoire —
jamais une donnée métier inventée et présentée comme réelle (interdit, AGENTS.md), mais un
contexte de câblage, du même esprit que `attestation.fictif: true` que le serveur LUI-MÊME
impose aujourd'hui (« mode ombre uniquement », `outils.py` `_ATTESTATION`) :
- `fix_gps` : capture GPS hors périmètre — R12 §6, la lecture « fenêtre bornée = compatible Loi
  25 » n'est pas encore confirmée par Nathan/juriste, et `expo-location` n'est volontairement
  pas installé ;
- `fenetre_travail`/`referentiel_villes`/`ville`/`sel` : aucune route serveur ne les expose
  encore au mobile — l'appairage (T1.4-c3) fournit désormais une connexion authentifiée, mais
  ces données de cédule/référentiel arrivent avec `today.tsx` (R12 §5 étape 3), pas avant ;
- `technicien_id`/`intervention_id` NE sont PAS dans ce contexte provisoire : ce sont les deux
  seuls champs que l'employé saisit lui-même à l'écran (`today.tsx`/`job/[id]` les connaîtront
  automatiquement) ;
- `appareil_id`/`deviceId` : **toujours** un identifiant généré une fois par processus
  (`expo-crypto`), jamais persisté ici — `punch.tsx` n'a PAS été reconnecté à la vraie identité
  d'appareil que T1.4-c3 introduit (`src/appairage/identite.ts`, persistée dans
  `expo-secure-store`, stable d'un lancement à l'autre) : ce sont deux identifiants D'APPAREIL
  DIFFÉRENTS aujourd'hui, l'un pour l'appairage (réel, stable), l'autre pour `m4_pointer` (encore
  provisoire, par processus). Les faire converger — `punch.tsx`/`m4/pointage.ts` lisant
  `src/appairage/stockage.ts` plutôt que de générer leur propre id — est un point d'extension
  explicite pour une prochaine tranche, PAS fait ici (mission T1.4-c3 : appairage seulement).
  Sans convergence, l'idempotence de bout en bout `(appareil, idempotencyKey)` reste non garantie
  d'une session à l'autre pour les mutations `punch_in`/`punch_out` — sans conséquence tant que
  T1.4-c1 n'a pas câblé la lecture de ces champs côté core (section suivante).

**Verdict serveur métier vs succès/échec HTTP** (`src/m4/pointage.ts`,
`interpreterResultatPointage`) : un HTTP 200 peut être un REJET métier définitif
(`{accepte: false, verdict}`, patron `depuis_couple` de `src/opsys/outils.py`, lu — voir
`IDEMPOTENCE.md` §3.2/§6 pour l'enveloppe exacte). Sans cette lecture, un rejet s'afficherait
comme un succès silencieux. Un fix GPS incohérent (`gps_coherent: false`) N'EST PAS un rejet — le
pointage est accepté, routé en `en_revue` côté serveur ; seul `accepte: false` est un échec.
Lecture **défensive**, jamais vérifiée contre un core réel dans ce bac à sable (ADR-0008) : une
forme non reconnue est traitée comme un succès plutôt qu'un blocage — à confirmer au premier E2E
Maestro contre un core réel (R12 §5 étape 7).

**Portée de l'affichage du verdict** (limite assumée, mission item 2) : le STATUT de la mutation
(`en_attente`/`envoi`/`envoyee`/`echec_permanent`) est toujours exact, y compris après
redémarrage (persisté dans `outbox`). Le TEXTE du verdict (`{code, detail}`) n'est PAS persisté
dans la ligne `outbox` elle-même — il vient du `RapportVidange` de la vidange que l'écran a
lui-même déclenchée et attendue (juste après avoir mis sa mutation en file). Une vidange
déclenchée en arrière-plan (premier plan, retour réseau) rafraîchit le statut affiché mais pas
forcément ce texte détaillé si elle aboutit à un nouvel échec permanent pendant que l'écran est
resté ouvert sans redéclencher lui-même. Amélioration possible d'une tranche future : persister
le dernier verdict dans la ligne `outbox` (colonne supplémentaire, DDL + `MutationOutbox` à
faire évoluer).

## `/tools/invoke` sans tour de modèle (`src/protocole/`)

Client typé de `POST /tools/invoke`, conforme à la lecture directe du fork (lecture seule —
`core/src/gateway/tools-invoke-http.ts`, `tools-invoke-shared.ts` ; jamais exécuté ici, ADR-0008 :
le core ne se construit/teste qu'en CI). Requête `{ tool, args, action?, sessionKey?, agentId?,
idempotencyKey?, deviceId?, deviceTimestamp? }`, en-tête `authorization: Bearer <jeton>`, réponse
`{ ok: true, result }` ou `{ ok: false, error: { type, message } }` (types fermés :
`invalid_request`, `not_found`, `tool_call_blocked`, `tool_error`). `fetch` est injecté (testable
sans réseau). Classement des échecs : réseau/délai et HTTP 408/429/5xx → réessayable ; les autres
4xx → permanent — `src/protocole/classification.ts`. `idempotencyKey` porte le `mutation_id` de
`src/outbox` pour tout appel émis par la file sortante ; **le branchement réel entre les deux
(vidangeur) est fait (T1.4-d)** — voir « Vidangeur » ci-dessus.

`deviceId`/`deviceTimestamp` (T1.4-d, ajoutés à `RequeteOutilsInvoke`) anticipent le contrat que
[`IDEMPOTENCE.md`](IDEMPOTENCE.md) §7 documente pour T1.4-c1 : mêmes noms, même emplacement
(corps de `/tools/invoke`, à côté de `idempotencyKey`) que le changement recommandé pour
`ToolsInvokeInput` (`tools-invoke-shared.ts`) — choisis pour qu'aucune réécriture côté mobile ne
soit nécessaire quand T1.4-c1 câblera leur lecture vers `_meta` MCP
(`opsys/appareil`/`opsys/horodatageAppareil`). **Le core ne les lit pas encore** : envoyés dès
maintenant, ignorés jusqu'à T1.4-c1. Le jeton d'appareil qu'`app/pairing/index.tsx` obtient
désormais (T1.4-c3, section « Appairage » ci-dessus) EST un jeton `authMethod === "device-token"`
reconnu par l'autorisation HTTP de `/tools/invoke` (vérifié en lisant
`core/src/gateway/http-auth-utils.ts:179,267,477,495,559` — lecture seule, jamais exécuté) : le
Bearer envoyé par `src/protocole/client.ts` après un appairage réussi est donc un jeton que le
fork accepte réellement, pas une supposition.

## Idempotence et identité d'appareil de bout en bout (T1.4-b, T1.4-c1, T1.4-c2 partiel)

- **Idempotence, fait de bout en bout** (T1.4-b pour le socle, T1.4-c1 pour le core) :
  - `/tools/invoke` accepte `idempotencyKey`, `deviceId` et `deviceTimestamp` ;
  - le core les porte jusqu'au `tools/call` MCP, dans le `_meta` (`opsys/idempotencyKey`,
    `opsys/appareil`, `opsys/horodatageAppareil`) ;
  - le socle rejoue la réponse d'un renvoi, sans rien exécuter deux fois ;
  - détail dans [`IDEMPOTENCE.md`](IDEMPOTENCE.md) §7.
- **Rôles nommés, partiel** (T1.4-c2, IDEMPOTENCE.md §7 bis) :
  - OPSYS génère deux fragments : `opsys/roles.json` (outils permis par rôle) et
    `opsys/appareils.json` (appareil → personne et rôle `admin`, `employee`, `seller` ou `client`) ;
  - le core refuse d'office un outil hors de la portée du rôle ;
  - il transmet `opsys/personne` et `opsys/role` au moteur.
- **Limite de sécurité, à lever avant toute mise en service** :
  - `/tools/invoke` authentifie encore par le secret partagé de la Gateway, qui donne un accès
    complet ;
  - le `deviceId` du corps n'est pas lié à l'appelant authentifié, et l'identité transmise
    (`opsys/personne`) peut donc être usurpée par qui détient le secret ;
  - le téléphone ne doit jamais recevoir ce secret ;
  - aucun outil ne doit se fier à `opsys/personne` pour une signature ou une projection tant que
    `/tools/invoke` n'authentifie pas l'appareil par son propre jeton, avec l'identité tirée du
    jeton et non du corps (PLAN T1.4-c4).

## Sécurité

Jeton d'appareil et clé d'appairage : `expo-secure-store` (Keychain iOS / Keystore Android),
jamais en base SQLite ni `AsyncStorage` (R12 §6) — **câblé depuis T1.4-c3**
(`src/appairage/stockage.ts` : clé secrète Ed25519 et session — jeton, rôle, `urlBase`,
`appareilId` — dans deux entrées distinctes ; ni l'une ni l'autre n'est jamais journalisée,
vérifié explicitement par un test — `identite.test.ts`). Une fois l'appairage réussi (ou une
session persistée restaurée au démarrage, `app/_layout.tsx`), `src/protocole/configuration.ts`
(`obtenirConfigurationAppel`) renvoie une vraie configuration et `src/outbox/service.ts`
construit le vidangeur réel — sans appairage, il renvoie toujours `null` (même philosophie que
`src/roles/contexte.tsx` — « on n'invente aucun faux état apparié »), et la file sortante
continue d'accumuler les mutations en sécurité sans jamais tenter d'appel réseau. Vues par rôle
appliquées deux fois (serveur ET app, R12 §6) ; côté app, `evaluerGarde` est câblé sur le rôle
REÇU du serveur (pas encore un rôle nommé OPSYS tant que T1.4-c2 n'est pas livré — voir
« Appairage » ci-dessus, fail-closed en attendant). Consentement GPS, photos/signature :
politiques Loi 25 citées par R12 §6 — `punch.tsx` ne capte AUCUNE géolocalisation réelle (voir
« Écran `punch.tsx` »).

## Ce qui n'est PAS encore fait

**Côté core (hors périmètre de ce dépôt mobile, lecture seule) :** rôles d'opérateur nommés sur
le jeton d'appareil (T1.4-c2) — tant que ce n'est pas livré, le rôle reçu par l'app reste
`"operator"` générique et `evaluerGarde` bloque tout accès métier (fail-closed, voir
« Appairage ») ; branchement `_meta` MCP `deviceId`/`deviceTimestamp` (T1.4-c1, IDEMPOTENCE.md
§7) — un renvoi duplique encore l'effet serveur ; identifiant OPSYS dédié dans
`GATEWAY_CLIENT_IDS` (limite documentée dans « Appairage », `src/appairage/clientInfo.ts`
emprunte `openclaw-ios`/`openclaw-android` en attendant.

**Côté mobile :** pas de lecture QR (code saisi seulement, voir « Appairage » — `expo-camera`
non installé) ; `punch.tsx`/`m4/pointage.ts` n'utilisent pas encore la vraie identité d'appareil
que l'appairage introduit — ils gardent leur propre `appareilId` provisoire par processus (voir
« Écran `punch.tsx` », point d'extension explicite pour une prochaine tranche) ; pas de capture
GPS réelle (Loi 25 non confirmée, `expo-location` non installé), ni de fenêtre de
travail/référentiel de villes fournis par le serveur au mobile — `punch.tsx` envoie un contexte
provisoire clairement documenté pour ces champs (`src/m4/contextePointageProvisoire.ts`) ; pas de
persistance du dernier verdict serveur dans la ligne `outbox` (limite documentée dans « Écran
`punch.tsx` ») ; pas d'écran métier au-delà de `punch.tsx` (cédule, checklist, matériaux,
approbations, etc.) ; `identifierMutationsAReprendre` n'a encore aucun appelant réel (la reprise
au démarrage passe directement par `selectionnerProchainesEnvoyables`, qui inclut déjà les
`envoi` — cette fonction reste utile pour une future traçabilité/journalisation dédiée, R12 §4
P3) ; pas de caméra, notifications push, signature manuscrite ; pas de rotation/révocation de
jeton d'appareil câblée côté app (`device.token.rotate/revoke`, R12 §1.3 — l'app n'appelle
jamais ces méthodes, seulement `connect`) ; pas de tests E2E Maestro ; pas de build EAS ni de
publication store (frontière humaine T3, R12 §3).
