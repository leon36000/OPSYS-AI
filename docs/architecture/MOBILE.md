# Application mobile OPSYS

> Réécrit par PLAN T1.4-a (2026-09-28) : remplace la version périmée qui prévoyait un fork des
> apps natives OpenClaw (« phase 2 »). Décision en vigueur : **nouvelle app Expo/React Native,
> réutilisant le protocole et l'appairage d'OpenClaw, pas son code d'interface** — voir
> [ADR-0008](../decisions/ADR-0008-fork-openclaw-opsys-core.md) et le détail technique complet
> dans [`docs/research/R12-app-mobile.md`](../research/R12-app-mobile.md) (pile §3, synchro §4,
> écrans §5, sécurité §6). Ce fichier résume ; R12 fait foi sur le détail et les preuves.

## État actuel : chantier du jour, transitions, checklist, photos, signature (T1.4-e)

`mobile/` contenait, jusqu'à T1.4-a, un **squelette** (projet, routage par rôle, file sortante
et client protocole en logique pure) sans écran métier. T1.4-d a livré `punch.tsx` (M4.4) et le
« vidangeur » qui relie `src/outbox` à `src/protocole` (R12 §5 étape 2). T1.4-c3 a livré le
**CLIENT D'APPAIRAGE réel** (`src/appairage/`, voir « Appairage » ci-dessous). **Précision
(T1.4-c4) :** le rôle *reçu par la poignée de main* (`hello.auth.role`, ce que la garde de routes
regarde) reste le rôle de transport générique du fork (`"operator"`) même après T1.4-c2/T1.4-c4 ;
ces deux tranches livrent le rôle OPSYS nommé (`admin`/`employee`/`seller`) résolu et appliqué à
CHAQUE appel `/tools/invoke`, indépendamment de la poignée de main (« Idempotence et identité
d'appareil de bout en bout » ci-dessous). **T1.4-e livre R12 §5 étapes 3 et 4** : `today.tsx`
(chantiers du jour, lecture `m4_lister_interventions` + cache local hors ligne — voir « Chantiers
du jour »), `job/[id]/index.tsx` (statut et transitions en route/arrivé/pause par la file
sortante, verdict serveur affiché — voir « Écran `job/[id]/index.tsx` »), `checklist.tsx`,
`photos.tsx`, `signature.tsx` (preuves de chantier, fichier local + SHA-256, jamais de binaire
dans une mutation — voir les sections dédiées) et la préparation de la structure
`PreuvesCompletion` pour T1.4-f (`src/m4/preuvesCompletion.ts`). **Un seul identifiant d'appareil
dans toute l'app depuis cette tranche** : `punch.tsx` et `job/[id]/index.tsx` lisent tous les
deux `src/protocole/configuration.ts::obtenirConfigurationAppel()` (la VRAIE identité
d'appairage) — voir « Écran `punch.tsx` » pour ce qui a changé. Étapes suivantes (R12 §5, ordre
de livraison) : `complete.tsx`→`materials.tsx` (M6.10), `(admin)/approvals`, E2E Maestro. T1.4-b
(idempotence côté socle) et T1.4-c1 (le core transmet la clé, l'appareil et son heure dans le
`_meta` MCP) sont faits côté serveur — voir [`IDEMPOTENCE.md`](IDEMPOTENCE.md) et la section
« `/tools/invoke` » ci-dessous ; le trajet réel appareil → core → moteur reste à prouver (T1.5).

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
du `deviceId`).

Depuis T1.4-e : **`expo-camera`** 57.0.5 (capture photo, `CameraView` — voir « Photos »),
**`expo-file-system`** 57.0.7 (API `File`/`Directory`/`Paths` de SDK 57, pas l'ancienne API
`FileSystem.*` — stockage local des photos/signature, hachage — voir « Photos », « Signature »),
**`react-native-signature-canvas`** 5.1.1 (rendu WebView, voir « Signature ») et son pair
**`react-native-webview`** 13.16.1 (version lue dans `node_modules/expo/bundledNativeModules.json`
— le même tableau que consulte `expo install`, indisponible ici via le CLI lui-même, le
vérificateur de compatibilité en ligne de `expo install` étant bloqué par le proxy sortant du bac
à sable ; installé explicitement car `legacy-peer-deps=true` — §3 — n'installe jamais
automatiquement un pair). Toutes MIT (fichiers `LICENSE` lus). Volontairement **pas encore
installés** à ce stade (aucun écran n'en a encore besoin) : lecture QR (voir « Appairage », code
saisi seulement), notifications, formulaires (react-hook-form/zod), TanStack Query,
`expo-location`/`expo-task-manager` (GPS — voir « Écran `punch.tsx` » : la lecture Loi 25
« fenêtre bornée » de R12 §6 n'est pas encore confirmée par Nathan/juriste),
`expo-image-manipulator` (aucun redimensionnement post-capture — voir « Photos », le bridage
« ≈1600 px » se fait par choix de résolution de capture, pas par redimensionnement),
`@testing-library/react-native` (absent de la pile installée — tous les écrans de cette tranche
sont donc testés via leur logique extraite en fonctions pures, jamais en rendu). Ils entrent avec
les tranches qui en ont besoin, jamais par anticipation.

## Rôles et routage (`src/roles/`)

Quatre profils (DEFINITION-PRODUIT §9) = quatre groupes Expo Router : `(employee)`, `(seller)`,
`(admin)`, `(client)`. `src/roles/garde.ts` exporte `evaluerGarde(session, groupeCible)`, une
fonction **pure** : rôle du jeton d'appareil → groupe autorisé (mappage un-à-un, R12 §6), fail-
closed (session absente, rôle inconnu et rôle valide mais différent du groupe visé refusent
tous les trois, vers `/pairing`). Chaque `_layout.tsx` de groupe appelle cette garde avant de
rendre quoi que ce soit — un jeton `employee` n'atteint donc jamais `(admin)`, y compris par URL
directe. `src/roles/contexte.tsx` porte l'état de session en React Context ; il démarre toujours
`{ presente: false }` au premier rendu (`app/_layout.tsx` la restaure ensuite depuis
`expo-secure-store` si une session persistée existe — voir « Appairage » ci-dessous). 446 tests
Jest (PLAN T1.4-e ; 312 à T1.4-c3) couvrent la garde (matrice rôle × groupe complète, session
absente, rôles inconnus), la file sortante, le vidangeur (faux transport), le contrat
`m4_pointer`, les déclencheurs, la logique de `punch.tsx`, le client d'appairage
(`src/appairage/`, T1.4-c3), et désormais (T1.4-e) les contrats `m4_lister_interventions`/
`m4_statut_intervention`/`m4_demarrer_route` (`src/m4/interventions.ts`), la sélection/le cache
des chantiers du jour (`src/today/`), les transitions de `job/[id]/index.tsx` (`src/ecrans/job.ts`),
la checklist (`src/checklist/`), le bridage/hachage des photos (`src/photos/`,
`src/fichiers/empreinte.ts`) et le décodage/la mutation de signature (`src/signature/`).

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

**Limite partiellement levée (T1.4-c4) :** `GATEWAY_CLIENT_IDS`
(`core/packages/gateway-protocol/src/client-info.ts:10-29`) était un catalogue FERMÉ sans
identifiant OPSYS — `ConnectParams.client.id` doit être une valeur connue du fork, sous peine
d'échec de schéma. T1.4-c4 y ajoute `OPSYS_MOBILE: "opsys-mobile"`, vérifié sans risque de casse
par lecture (le schéma `Type.Enum(GATEWAY_CLIENT_IDS)` en dérive directement, aucun switch
exhaustif ni liste séparée ne dépend de ce registre). **Non câblé** pour autant :
`src/appairage/clientInfo.ts` emprunte toujours `openclaw-ios`/`openclaw-android` selon la
plateforme, faute de mieux. Ce n'est pas cosmétique : `isNativeAppUiClient`
(`handshake-auth-helpers.ts:37-45`) classe ces id comme des clients natifs de confiance OpenClaw —
faire adopter le véritable identifiant OPSYS au mobile, et éventuellement enseigner à
`isNativeAppUiClient` (ou une autre politique) à le reconnaître, change un comportement de
confiance à l'appairage que cette tranche, core-seule et jamais exécutée dans ce bac à sable, ne
peut pas vérifier de bout en bout — laissé à une tranche dédiée, mobile ET core ensemble.

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

### Rôle reçu -> garde de routes existante, et ce que T1.4-c2/T1.4-c4 livrent EN RÉALITÉ

`hello.auth.role` (chaîne libre côté protocole) est stocké TEL QUEL dans `SessionAppareil.role`
et alimente directement `src/roles/garde.ts` (`evaluerGarde`), sans traduction ni mappage codé en
dur ici — c'est voulu. **Le fork non modifié ne connaît que deux rôles de transport,
`"operator"`/`"node"`** (`core/src/gateway/role-policy.types.ts:2`), pas de rôles nommés OPSYS
(`admin`/`employee`/`seller`) : `src/appairage/client.ts` demande `role:"operator"` (seule valeur
qui passe la validation du fork actuel pour un appareil humain), et c'est CE QUE le serveur rend
dans `hello.auth.role`. **Correction après coup (T1.4-c4, une fois T1.4-c2 réellement livré) :**
le paragraphe précédent, écrit avant T1.4-c2, anticipait que cette tranche remplacerait
`"operator"` par un rôle nommé DANS `hello.auth.role` lui-même. Ce n'est PAS ce que T1.4-c2 ni
T1.4-c4 livrent, en lisant leur code réel : les deux portent sur `/tools/invoke` (authentification
de l'appareil, résolution `deviceId` → personne/rôle → portée d'outil à CHAQUE appel), jamais sur
la poignée de main `connect`/`hello-ok` — voir « Idempotence et identité d'appareil de bout en
bout » ci-dessous pour le détail exact livré. `hello.auth.role` reste donc `"operator"` même pour
un appareil dont l'attribution OPSYS existe (`opsys appareils appairer`, T1.4-c4) et dont
`/tools/invoke` résout correctement `admin`/`employee`/`seller`. `"operator"` n'est PAS un profil
connu de `src/roles/types.ts` (`PROFILS = admin|employee|seller|client`), donc `evaluerGarde` le
refuse déjà correctement (`role_inconnu`, fail-closed, testé exhaustivement dans `garde.test.ts`,
INCHANGÉ par T1.4-c2 ET T1.4-c4) et renvoie vers `/pairing` — **l'appairage réussit, le jeton et
le rôle sont bien stockés, `/tools/invoke` fonctionne et applique le bon rôle OPSYS pour chaque
appel d'outil, mais aucun écran métier n'est atteignable en production tant qu'une tranche core
séparée (non commencée) ne fait pas porter un rôle nommé par la poignée de main elle-même — ou que
l'app n'apprend son rôle OPSYS par un autre moyen que `hello.auth.role`.** C'est le comportement
CORRECT en attendant (P2, fail-closed) : mieux vaut un appareil apparié mais bloqué à `/pairing`
qu'un rôle deviné. Rien côté mobile n'a besoin de changer quand une future tranche livrera un rôle
nommé sur la poignée de main : le chemin
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
  seuls champs que l'employé saisit lui-même à l'écran (`job/[id]/index.tsx`, depuis T1.4-e,
  connaît `intervention_id` automatiquement — voir « Écran `job/[id]/index.tsx` » ; `technicien_id`
  reste saisi à la main des deux côtés, aucune identité employé/technicien n'est encore exposée
  par le serveur au mobile, limite reportée telle quelle, pas résolue par cette tranche).

**CONVERGENCE FAITE (PLAN T1.4-e, mission item 3) : un seul identifiant d'appareil dans toute
l'app.** Avant cette tranche, `appareil_id`/`deviceId` (le champ `attestation.appareil_id` de
`m4_pointer`) était **toujours** un identifiant généré une fois par processus (`expo-crypto`),
jamais persisté — DIFFÉRENT de la vraie identité d'appareil que T1.4-c3 introduit
(`src/appairage/identite.ts`, persistée dans `expo-secure-store`, stable d'un lancement à
l'autre). `src/m4/contextePointageProvisoire.ts::obtenirContextePointageProvisoire` a été changé
pour PRENDRE `appareilId` en PARAMÈTRE plutôt que de le générer lui-même (le générateur par
processus, `genererAppareilIdProvisoire`, est supprimé) ; `punch.tsx` ET `job/[id]/index.tsx`
lisent tous les deux la même source, `src/protocole/configuration.ts::obtenirConfigurationAppel()`
(`ConfigurationAppel.appareilId` = `SessionAppairee.appareilId` = `identite.deviceId`, posé au
même endroit que le jeton d'appareil à l'appairage ou à la restauration de session — voir
`app/pairing/index.tsx`/`app/_layout.tsx`). Fail-closed si absente : les deux écrans refusent
l'action (message dédié, `pointage.appareilNonAppaire`/`job.appareilNonAppaire`) plutôt que de
générer un id de repli — cas normalement impossible à l'intérieur du groupe `(employee)`, gardé
par `evaluerGarde`, qui n'admet que des sessions où cette configuration existe déjà. L'identité
d'APPAREIL envoyée au TRANSPORT (`deviceId` du corps `/tools/invoke`, `src/protocole/types.ts`)
était déjà la vraie depuis T1.4-c3 (`src/outbox/service.ts` la lit de la même configuration) —
c'était SEULEMENT l'attestation `m4_pointer` (à l'intérieur du `payload`, propre à M4) qui restait
provisoire ; les deux convergent maintenant sur la MÊME valeur. Conséquence : l'idempotence de
bout en bout `(appareil, idempotencyKey)` est stable d'une session à l'autre pour toutes les
mutations `punch_in`/`punch_out`/`job_status_change`, sans attendre T1.4-c1 pour ce point précis
(T1.4-c1 reste nécessaire pour que le CORE lise et applique ces champs — section « Idempotence »
ci-dessous, inchangée par cette tranche).

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

## Chantiers du jour (`today.tsx`, M4.7, R12 §5 étape 3, PLAN T1.4-e)

`app/(employee)/today.tsx` : liste, en LECTURE SEULE, via `m4_lister_interventions`
(`departments/m04-field-ops/src/m4_field_ops/outils.py`, lu, jamais exécuté ni modifié ici —
contrat exact et enveloppe HTTP documentés dans `src/m4/interventions.ts`). Cache local lisible
hors ligne : `src/today/cache.ts` (JSON sérialisé) au-dessus d'un dépôt clé/valeur PARTAGÉ,
`src/stockage/depotCleValeur.ts` (mémoire, testé) + `depotCleValeur.sqlite.ts` (`expo-sqlite`,
base séparée `opsys-local.db`, non testé — même limite que `src/outbox/depot.sqlite.ts`) — brique
commune à `today` et `checklist` plutôt que deux adaptateurs SQLite quasi identiques.

**« Chantiers du jour » est un PROXY assumé, pas une vraie date — limite documentée, pas une
invention.** `m4_lister_interventions` (lu dans `etats.py`, `lister_interventions`) ne renvoie
QUE `{intervention_id, statut, lead_id, type_travaux, devis_id}` : ni date/fenêtre de cédule, ni
`technicien_id` assigné, structurellement (même absence que les données de contact). Filtrer par
« aujourd'hui » ou par « mes chantiers » exigerait un champ que le serveur n'expose pas — interdit
d'inventer (AGENTS.md). `src/today/selection.ts::filtrerChantiersActifs` retient donc les
interventions dont le statut représente un travail en cours ou à démarrer
(`planifiee`/`en_route`/`sur_site`/`en_revue`, PAS `reportee` : une intervention reportée est
sortie du flux du jour tant qu'un nouveau `planifiee` ne l'y remet pas), triées par urgence
d'affichage puis par `intervention_id` — un choix de présentation, documenté, jamais une donnée
de cédule réelle. **À corriger dès qu'une route serveur exposera une vraie date/fenêtre par
intervention et un filtre par technicien** (aucune des deux n'existe aujourd'hui parmi les quatre
outils lus pour cette tranche).

Orchestration : `src/today/orchestrateur.ts::creerChargeurChantiers` (pure, testée avec un faux
transport et un dépôt mémoire, `orchestrateur.test.ts`) — tente `m4_lister_interventions` en
ligne, écrit le cache (TOUTES les interventions reçues, le filtrage ne s'applique qu'À LA
LECTURE) sur un succès, retombe sur le dernier cache écrit (avec la raison de l'échec portée,
`raisonHorsLigne`) sur un échec réseau/HTTP/technique — jamais une liste inventée si ni le réseau
ni le cache ne répondent (`source: "aucune"`). `src/today/service.ts` fournit le câblage réel
(`expo-sqlite`, `fetch`, `obtenirConfigurationAppel()`), non testé, même limite que
`src/outbox/service.ts`.

## Écran `job/[id]/index.tsx` (M4.7, R12 §5 étape 3, PLAN T1.4-e)

`app/(employee)/job/[id]/index.tsx` : statut du chantier et transitions légales, par la file
sortante, verdict serveur affiché — mission item 1.

**Statut** : lecture directe (PAS mise en file, c'est une lecture pas une mutation) via
`m4_statut_intervention`, avec repli sur le cache de `today.tsx` hors ligne
(`src/today/statut.ts::obtenirStatutChantier`, même patron source
serveur/cache/aucune qu'`orchestrateur.ts`, testé avec un faux transport,
`statut.test.ts`). `statut: null` (intervention inconnue du serveur) N'EST PAS une erreur — lu et
distingué explicitement (`interpreterResultatStatutIntervention`, `src/m4/interventions.ts`).

**Transitions — DÉCISION DOCUMENTÉE sur « démarrer ».** DEFINITION-PRODUIT.md §9.3 nomme quatre
transitions : « en route, arrivé, démarrer, pause ». La machine à états serveur (`etats.py`, lu)
n'en connaît que DEUX au niveau de l'intervention : `planifiee -> en_route`
(`m4_demarrer_route`, exige une assignation technicien effective) et `en_route -> sur_site`
(`m4_pointer(action="arrivee")`, `pointage.py` étape 13) — la docstring de `etats.py` dit
EXPLICITEMENT que `sur_site` « regroupe arrived+started du produit, qu'un seul état M4 porte
encore ». Il n'existe donc PAS de transition serveur distincte pour « démarrer » :
`src/ecrans/job.ts` (logique pure, testée exhaustivement — matrice phase × action complète,
`job.test.ts`) ne lui associe AUCUNE action ; le bouton « Arrivé » couvre les deux côté produit,
plutôt que d'inventer un bouton sans rien à appeler. « Pause » réutilise TEL QUEL le mécanisme
`m4_pointer`/`pointage.ACTIONS` déjà câblé par `punch.tsx` (T1.4-d) — borné à CE chantier
(`intervention_id` fixé par la route), la phase `en_pause` restant PUREMENT locale (une pause est
« sans effet sur le statut », `pointage.py`) : un rechargement du statut serveur ne remet jamais
l'écran en pause par lui-même (`phaseDepuisStatutServeur`, `sur_site -> sur_place`, jamais
`en_pause`).

Mutations : « En route » crée un `job_status_change` (nouveau descripteur
`src/outbox/descripteurs.ts`, `-> m4_demarrer_route`, testé) ; « Arrivé »/« Pause » créent des
`punch_in`/`punch_out` (descripteurs T1.4-d inchangés, réutilisés tels quels). `technicien_id`
reste saisi à la main (même limite que `punch.tsx`, non résolue ici) ; `appareilId` vient de la
VRAIE session appairée (voir « Écran `punch.tsx` » ci-dessus). Verdict serveur affiché sur un
échec définitif — même patron que `punch.tsx` (`RapportVidange.echecsPermanents`).

**`job_status_change` : une seule direction aujourd'hui.** `DescripteurTypeMutation` associe UN
outil fixe par type de mutation ; `job_status_change -> m4_demarrer_route` est correct tant que
« en route » est la SEULE transition de ce type créée par l'app. Une tranche future qui ajouterait
un report (`m4_signaler_report`) ou une annulation (`m4_annuler_intervention`) — hors périmètre de
cette tranche, la mission ne listant que les quatre outils déjà cités — devra soit ajouter un type
de mutation dédié par transition, soit faire porter l'outil par le payload plutôt que par le
descripteur.

## Checklist (`checklist.tsx`, R12 §5 étape 4, PLAN T1.4-e)

`app/(employee)/job/[id]/checklist.tsx`. **AUCUN catalogue d'items n'existe côté serveur —
décision documentée, pas un oubli.** `preuves.py`/`outils.py` (lus) n'attendent qu'un BOOLÉEN
(`checklist_complete`, `CLES_PREUVES_COMPLETION`) ; le contenu détaillé (quelles étapes, pour
quel service — gouttières, revêtement, soffite/fascia…) n'est modélisé NULLE PART dans le produit
(`DEFINITION-PRODUIT.md` ne liste aucune liste d'étapes par service). Inventer une liste fixe
d'étapes de pose serait de la donnée métier inventée (interdit, AGENTS.md). L'écran laisse donc
l'employé COMPOSER sa propre liste pour le chantier (texte libre, ajouter/cocher/retirer),
persistée localement PAR CHANTIER (même dépôt clé/valeur partagé que `today.tsx`,
`src/checklist/cache.ts`). `checklist_complete` (préparé pour T1.4-f, voir plus bas) n'est vrai
QUE si la liste n'est pas vide ET que tous les items sont cochés — fail-closed, même lecture que
`photos_apres` côté serveur (« une checklist "en cours" ne clôt rien », `preuves.py`). Logique
pure et sa persistance testées intégralement (`src/checklist/logique.test.ts`,
`cache.test.ts`) ; l'écran lui-même n'est pas testé en rendu.

## Photos (`photos.tsx`, avant/pendant/après, R12 §5 étape 4, PLAN T1.4-e)

`app/(employee)/job/[id]/photos.tsx` : `expo-camera` (`CameraView`), capture bridée et fichier
local + SHA-256 — R12 §4, « jamais en base64 dans une mutation ».

**Bridage « ≈1600 px de long côté, JPEG ~0,8 » — limite exacte d'`expo-camera` lue dans ses
types, pas devinée.** `CameraPictureOptions` (`node_modules/expo-camera/build/Camera.types.d.ts`,
lu) n'offre AUCUNE option de largeur/hauteur maximale ni de redimensionnement — seulement
`quality` (0-1, réglé à 0.8) et `imageType` (réglé à `"jpg"`). Le SEUL levier pour approcher
« ≈1600 px » est de choisir, PARMI LES RÉSOLUTIONS RÉELLEMENT SUPPORTÉES par l'appareil
(`CameraView.getAvailablePictureSizesAsync()`), celle dont le plus long côté est le plus proche de
la cible — `src/photos/taille.ts::choisirTaillePhoto`, fonction pure, testée
(`taille.test.ts`) — d'où le « ≈ » de R12 §4, jamais une valeur exacte.
`expo-image-manipulator` (qui permettrait un vrai redimensionnement post-capture) N'EST PAS dans
la pile retenue par R12 §3 : ajouter une brique non prévue pour ce seul besoin est hors périmètre.

**Fichier local + hachage.** `src/photos/service.ts::enregistrerPhotoCapturee` copie le fichier
TEMPORAIRE produit par `takePictureAsync` (cache système, documenté « temporary » par
expo-camera) vers `Paths.document` (PAS `Paths.cache` : R12 §4 exige que le fichier survive
jusqu'à la purge post-confirmation, que le système peut vider sans préavis sous pression de
stockage), le hache (SHA-256, `src/fichiers/empreinte.ts`, brique PARTAGÉE avec la signature —
voir plus bas) et construit la mutation `photo_upload`. **SHA-256 des octets RÉELS du fichier,
pas d'un détour texte** — `expo-crypto` expose `digest(algorithm, data: BufferSource):
Promise<ArrayBuffer>` (hache des octets bruts directement), retenu plutôt que
`digestStringAsync` (hache une CHAÎNE ; son `options.encoding` ne contrôle QUE le format de
SORTIE, jamais l'interprétation de l'entrée — le détour par une chaîne base64 aurait haché le
TEXTE base64, pas les octets, un SHA-256 qui n'aurait pas correspondu à ce qu'un futur point
d'envoi calculerait après décodage). Testé contre Node `crypto` comme oracle indépendant
(vecteurs NIST `sha256("")`/`sha256("abc")`, `empreinte.test.ts` — même discipline que
`identite.test.ts`).

**GAP CÔTÉ SERVEUR, à ne pas confondre avec un oubli mobile — voir aussi « Angle mort à combler »
de R12 §6.** Le mission item 2 le demande explicitement : documenter précisément, sans inventer.
- La mutation `photo_upload` est construite (URI local + SHA-256 + cible `intervention_id`/
  `nature` — jamais le binaire) mais reste DÉLIBÉRÉMENT `brouillon` pour toujours (jamais
  `soumettreMutation`) : **aucune route serveur (core ou moteur Python) n'existe pour recevoir le
  binaire de la photo**. Sans une telle route, il n'y a rien à référencer pour un envoi.
- **Aucun descripteur `photo_upload`** n'est enregistré dans `src/outbox/descripteurs.ts` — pas un
  oubli : si une future régression soumettait quand même ce type par erreur, le vidangeur
  échouerait FORT (`Error`, `vidangeur.ts`, « aucun descripteur enregistré ») plutôt que
  d'échouer en silence ou de bloquer les AUTRES mutations en file (punch, etc.).
- **Ce qu'il manque concrètement pour clore ce gap** (hors périmètre de cette tranche, lecture
  seule de `core/`/`departments/`) : (1) un point d'entrée HTTP/MCP acceptant un envoi binaire
  repriseable par hachage (R12 §4, « requête distincte … déclenchant le marquage `envoyee`
  seulement à l'accusé de réception ») — absent de `core/src/gateway/` à la lecture ; (2) un
  moteur métier (probablement M4 ou un nouveau module) qui reçoit ce binaire, le vérifie contre le
  SHA-256 annoncé, le stocke, et ÉMET une RÉFÉRENCE stable que le mobile pourra alors placer dans
  `photos_apres` — actuellement `preuves.py` n'attend qu'une LISTE DE CHAÎNES sans préciser leur
  provenance, donc la FORME exacte de cette référence (id opaque ? URL signée ?) reste à définir
  avec cette route ; (3) une fois cette route écrite, `src/outbox/descripteurs.ts` gagne un
  descripteur `photo_upload`, et `photos.tsx`/`src/photos/service.ts` appellent
  `soumettreMutation` au lieu de laisser le brouillon inerte.
- **Purge post-confirmation (R12 §4)** : non implémentée, pour la même raison — rien à confirmer
  tant qu'aucun accusé de réception d'envoi n'existe. Le fichier local reste donc indéfiniment
  dans `Paths.document/opsys-photos/` jusqu'à ce que cette route existe.

`src/m4/preuvesCompletion.ts::extraireReferencesPhotosLocales`/`extraireReferencePhotosApres`
lisent ces mutations `brouillon` par `mutation_id` comme référence LOCALE PLACEHOLDER pour
`photos_apres` (T1.4-f) — nommé et documenté comme tel, PAS la vraie référence serveur que le
point (2) ci-dessus émettra un jour.

## Signature (`signature.tsx`, R12 §5 étape 4, PLAN T1.4-e)

`app/(employee)/job/[id]/signature.tsx` : `react-native-signature-canvas` (rendu WebView,
`react-native-webview` en pair — voir « Pile »), MÊME PRINCIPE que les photos (R12 §4, « même
principe » pour la signature) — fichier local + SHA-256, jamais de binaire inline dans une
mutation, et le MÊME gap serveur documenté ci-dessus (aucune route d'envoi, mutation
`signature_capture` délibérément `brouillon`, aucun descripteur enregistré).

**Brique non testable, logique isolée en fonctions pures (mission item 4).** La capture livre une
DataURL (`data:<mimeType>;base64,<...>`) via son callback `onOK` — décodée par
`src/signature/dataUrl.ts::decoderDataUrl` (fonction PURE, testée, `dataUrl.test.ts` : rejette une
DataURL malformée ou vide, fail-closed, jamais un fichier vide écrit) avant que
`src/signature/service.ts::enregistrerSignatureCapturee` (non testé, WebView/`expo-file-system`
natifs) n'écrive les octets décodés sur disque (`Paths.document/opsys-signatures/`), les hache
(`src/fichiers/empreinte.ts`, RÉUTILISÉ des photos — brique partagée plutôt que dupliquée) et
construise la mutation. `signature.tsx` lui-même ne fait que le câblage React (boutons
« Confirmer »/« Effacer » rendus PAR la WebView elle-même via `confirmText`/`clearText`, pas
réimplémentés côté RN).

## Préparation des preuves de complétion (`src/m4/preuvesCompletion.ts`, PLAN T1.4-e)

Mission item 2, dernière phrase : « prépare la structure attendue par
`CLES_PREUVES_COMPLETION`, sans encore appeler la complétion. » `CLES_PREUVES_COMPLETION`
(`"checklist_complete", "photos_apres", "notes", "signature"`) est une copie EXACTE, clé pour
clé, de `preuves.py` (lu, jamais importé ni exécuté). `construirePreuvesCompletion` assemble ces
quatre champs — AUCUNE validation métier dupliquée (le serveur, `preuves.py`, reste la SEULE
autorité fail-closed). `extraireReferencesPhotosLocales`/`extraireReferencePhotosApres` et
`extraireReferenceSignatureLocale` lisent la file sortante RÉELLE (mutations `photo_upload`/
`signature_capture` `brouillon`, voir « Photos »/« Signature » ci-dessus) pour composer
`photos_apres`/`signature` — avec le PLACEHOLDER documenté (`mutation_id` local, pas une vraie
référence serveur). `notes` (texte libre d'imprévus) N'A PAS d'écran dédié dans cette tranche :
DEFINITION-PRODUIT.md §9.7 la rattache au geste « Terminer » lui-même
(`complete.tsx`, T1.4-f), pas à un écran séparé de R12 §5 étape 4 — cette fonction accepte déjà le
paramètre, prête pour que `complete.tsx` le fournisse. `m4_completer_intervention` N'EST PAS
appelé par cette tranche (mission), et ne le sera que par T1.4-f. Testé intégralement
(`preuvesCompletion.test.ts`).

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
que le mécanisme d'authentification HTTP du fork reconnaît (vérifié en lisant
`core/src/gateway/http-auth-utils.ts:179,267,477,495,559` — lecture seule, jamais exécuté) : le
Bearer envoyé par `src/protocole/client.ts` après un appairage réussi est donc un jeton que le
fork accepte réellement, pas une supposition. **Précision (T1.4-c4) :** au moment de T1.4-c3, ce
mécanisme existait dans le fork pour D'AUTRES routes HTTP (lecture Control UI, routes de plugin),
mais `/tools/invoke` lui-même ne l'appelait pas encore avec `allowDeviceToken: true` — jusqu'à
T1.4-c4, `/tools/invoke` n'acceptait donc en pratique QUE le secret partagé, et un Bearer de jeton
d'appareil y était refusé (401). C'est corrigé : `/tools/invoke` réutilise désormais ce même
mécanisme pour de vrai — voir [`IDEMPOTENCE.md`](IDEMPOTENCE.md) §7 bis, « `/tools/invoke`
authentifie l'appareil par son propre jeton ».

## Idempotence et identité d'appareil de bout en bout (T1.4-b, T1.4-c1, T1.4-c2, T1.4-c4)

- **Idempotence, fait de bout en bout** (T1.4-b pour le socle, T1.4-c1 pour le core) :
  - `/tools/invoke` accepte `idempotencyKey`, `deviceId` et `deviceTimestamp` ;
  - le core les porte jusqu'au `tools/call` MCP, dans le `_meta` (`opsys/idempotencyKey`,
    `opsys/appareil`, `opsys/horodatageAppareil`) ;
  - le socle rejoue la réponse d'un renvoi, sans rien exécuter deux fois ;
  - détail dans [`IDEMPOTENCE.md`](IDEMPOTENCE.md) §7.
- **Rôles nommés et portée d'outil, fait** (T1.4-c2 + T1.4-c4, IDEMPOTENCE.md §7 bis) :
  - OPSYS génère deux fragments : `opsys/roles.json` (outils permis par rôle) et
    `opsys/appareils.json` (appareil → personne et rôle `admin`, `employee`, `seller` ou `client`),
    ce dernier régénéré par `opsys appareils appairer <deviceId> --personne <p> --role <r>
    --config-dir <dossier>` (T1.4-c4 : la surface d'attribution manquante en T1.4-c2, deux temps —
    approbation native de l'appairage côté core, puis attribution OPSYS de la personne et du rôle) ;
  - le core refuse d'office un outil hors de la portée du rôle ;
  - il transmet `opsys/personne` et `opsys/role` au moteur — **authentifiés** depuis T1.4-c4 (juste
    en dessous), jamais depuis le corps de la requête.
- **`/tools/invoke` authentifie l'appareil par son propre jeton (T1.4-c4, fait) :**
  - `/tools/invoke` accepte le jeton d'appareil (`hello-ok`) comme authentification, en réutilisant
    le mécanisme de jeton d'appareil déjà présent dans le fork pour d'autres routes HTTP
    (`verifyHttpOperatorDeviceToken`, `core/src/gateway/http-auth-utils.ts`) — pas un nouveau
    mécanisme écrit pour l'occasion ; `deviceId`, `opsys/personne` et `opsys/role` viennent
    désormais du jeton **vérifié**, jamais du corps de la requête ; un `deviceId` de corps
    différent de l'appareil authentifié est refusé (403) plutôt que silencieusement préféré à
    l'un ou l'autre ; jeton révoqué/inconnu → 401 ; appareil authentifié sans entrée dans
    `appareils.json` → refus fermé (403), désormais **obligatoire** (il n'existe plus de « corps
    sans `deviceId` » qui contournait ce contrôle pour un appelant par jeton d'appareil) ;
  - le chemin par secret partagé reste pour les appelants serveur de confiance (accès complet,
    documenté et voulu), mais ne transmet plus jamais `opsys/personne`/`opsys/role` et ne peut
    plus « emprunter » l'identité d'un appareil via le `deviceId` du corps ;
  - **le téléphone ne doit toujours jamais recevoir ce secret** (inchangé) ;
  - détail complet, fichiers et preuve : [`IDEMPOTENCE.md`](IDEMPOTENCE.md) §7 bis.
  - **Ce que T1.4-c4 NE change PAS** : la poignée de main WebSocket d'appairage (`connect` →
    `hello-ok`) reste inchangée — `hello.auth.role` continue de rendre le rôle de transport
    générique du fork (`"operator"`), jamais un rôle nommé OPSYS. La sécurité de `/tools/invoke`
    (quels outils un appareil peut appeler) est maintenant correcte et authentifiée de bout en
    bout ; le ROUTAGE ÉCRAN du mobile (`evaluerGarde`, section « Appairage » ci-dessus) reste donc
    bloqué à `/pairing` pour tout appareil réel tant qu'une tranche séparée n'apprend pas à la
    poignée de main elle-même à rendre un rôle nommé (ou que l'app n'obtient son rôle OPSYS par un
    autre moyen que `hello.auth.role`) — un problème d'UX/routage distinct du trou de sécurité que
    T1.4-c4 ferme, non traité ici.

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
REÇU du serveur (toujours le rôle de transport générique `"operator"`, pas un rôle nommé OPSYS —
la poignée de main elle-même n'est pas ce que T1.4-c2/T1.4-c4 ont changé, voir « Rôle reçu ->
garde de routes » ci-dessus, fail-closed en attendant une tranche core séparée). Consentement GPS, photos/signature :
politiques Loi 25 citées par R12 §6 — `punch.tsx` ne capte AUCUNE géolocalisation réelle (voir
« Écran `punch.tsx` »).

## Ce qui n'est PAS encore fait

**Côté core (hors périmètre de ce dépôt mobile, lecture seule) :** la poignée de main WebSocket
d'appairage (`connect`/`hello-ok`) ne rend toujours que le rôle de transport générique du fork
(`"operator"`), jamais un rôle nommé OPSYS — `evaluerGarde` bloque donc toujours tout accès métier
(fail-closed, voir « Appairage » et « Idempotence et identité d'appareil de bout en bout »
ci-dessus) même si `/tools/invoke` authentifie désormais correctement l'appareil et résout
`admin`/`employee`/`seller` pour CHAQUE appel d'outil (T1.4-c2 + T1.4-c4). Combler cet écart
(faire porter un rôle nommé par la poignée de main elle-même, ou donner à l'app un autre moyen
d'apprendre son rôle OPSYS) reste une tranche core séparée, non commencée.
`GATEWAY_CLIENT_IDS.OPSYS_MOBILE` (`"opsys-mobile"`) a été enregistré (T1.4-c4,
`core/packages/gateway-protocol/src/client-info.ts`), mais **non câblé** :
`src/appairage/clientInfo.ts` emprunte toujours `openclaw-ios`/`openclaw-android`, et
`isNativeAppUiClient` (classification de confiance à l'appairage, `handshake-auth-helpers.ts`) ne
reconnaît pas encore le nouvel identifiant — une tranche dédiée, mobile ET core ensemble.
T1.4-c4 refuse (403) tout `deviceId` de corps qui diffère de l'appareil authentifié par le jeton :
depuis T1.4-e, `punch.tsx` et `job/[id]/index.tsx` envoient l'identité d'appairage réelle
(`obtenirConfigurationAppel().appareilId`, le `deviceId` calculé par le client d'appairage), qui
coïncide par construction avec celle que le core authentifie ; la preuve contre un core réel reste
à faire (T1.5). Autres manques côté serveur : **aucune route (core ou moteur Python) pour recevoir
l'envoi BINAIRE d'une photo ou d'une signature** (PLAN T1.4-e, détaillé dans « Photos » ci-dessus
— le point bloquant principal laissé par cette tranche) ; aucune route serveur n'expose de
date/fenêtre de cédule ni de technicien assigné par intervention à `m4_lister_interventions`
(détaillé dans « Chantiers du jour » ci-dessus).

**Côté mobile :** pas de lecture QR (code saisi seulement, voir « Appairage » — `expo-camera` est
installé depuis T1.4-e mais seulement pour la capture photo, aucun scan QR câblé) ; pas de
capture GPS réelle (Loi 25 non confirmée, `expo-location` non installé), ni de fenêtre de
travail/référentiel de villes fournis par le serveur au mobile — `punch.tsx`/`job/[id]/index.tsx`
envoient un contexte provisoire clairement documenté pour ces champs
(`src/m4/contextePointageProvisoire.ts`) ; pas de persistance du dernier verdict serveur dans la
ligne `outbox` (limite documentée dans « Écran `punch.tsx` ») ; `identifierMutationsAReprendre`
n'a encore aucun appelant réel (la reprise au démarrage passe directement par
`selectionnerProchainesEnvoyables`, qui inclut déjà les `envoi` — cette fonction reste utile pour
une future traçabilité/journalisation dédiée, R12 §4 P3) ; pas de notifications push ; pas de
rotation/révocation de jeton d'appareil câblée côté app (`device.token.rotate/revoke`, R12 §1.3 —
l'app n'appelle jamais ces méthodes, seulement `connect`) ; pas de tests E2E Maestro ; pas de
build EAS ni de publication store (frontière humaine T3, R12 §3).

**Nouveau depuis T1.4-e, hors périmètre de cette tranche :** pas d'écran `complete.tsx`
(« Terminer », déclenche la cascade §9.7 — T1.4-f) ni `materials.tsx` (M6.10) ; `notes`
(imprévus) n'a pas d'écran de saisie (rattachée à `complete.tsx`, voir « Préparation des preuves
de complétion ») ; `technicien_id` reste saisi à la main sur `punch.tsx` ET `job/[id]/index.tsx`
(aucune identité employé/technicien exposée par le serveur au mobile — pas résolu par cette
tranche, contrairement à `appareilId` qui, lui, converge maintenant — voir « Écran `punch.tsx` ») ;
pas de suppression/reprise de photo une fois capturée (`DepotOutbox` n'expose aucune méthode de
suppression, volontairement non étendue ici pour ne pas risquer une régression sur `punch.tsx`
déjà en production) ; pas de rafraîchissement automatique de `today.tsx` au retour au premier
plan/réseau (seuls `punch.tsx`/le vidangeur ont ces déclencheurs, R12 §4 les prévoyant
spécifiquement pour la file sortante, pas pour une liste en lecture — un bouton « Rafraîchir »
manuel couvre cette tranche) ; aucun catalogue serveur de checklist par service (décision
documentée, voir « Checklist » — pas un gap à combler mais un choix de conception assumé tant
qu'aucune donnée produit n'existe pour le remplacer).
