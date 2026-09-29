# Application mobile OPSYS

> Réécrit par PLAN T1.4-a (2026-09-28) : remplace la version périmée qui prévoyait un fork des
> apps natives OpenClaw (« phase 2 »). Décision en vigueur : **nouvelle app Expo/React Native,
> réutilisant le protocole et l'appairage d'OpenClaw, pas son code d'interface** — voir
> [ADR-0008](../decisions/ADR-0008-fork-openclaw-opsys-core.md) et le détail technique complet
> dans [`docs/research/R12-app-mobile.md`](../research/R12-app-mobile.md) (pile §3, synchro §4,
> écrans §5, sécurité §6). Ce fichier résume ; R12 fait foi sur le détail et les preuves.

## État actuel : chorégraphie « Travaux terminés » complète (T1.4-f)

`mobile/` contenait, jusqu'à T1.4-a, un **squelette** (projet, routage par rôle, file sortante
et client protocole en logique pure) sans écran métier. T1.4-d a livré `punch.tsx` (M4.4) et le
« vidangeur » qui relie `src/outbox` à `src/protocole` (R12 §5 étape 2). T1.4-c3 a livré le
**CLIENT D'APPAIRAGE réel** (`src/appairage/`, voir « Appairage » ci-dessous). **Précision
(T1.4-c4) :** le rôle *reçu par la poignée de main* (`hello.auth.role`, que la garde de routes
regardait avant T1.4-c5) reste le rôle de transport générique du fork (`"operator"`) même après
T1.4-c2/T1.4-c4 ;
ces deux tranches livrent le rôle OPSYS nommé (`admin`/`employee`/`seller`) résolu et appliqué à
CHAQUE appel `/tools/invoke`, indépendamment de la poignée de main (« Idempotence et identité
d'appareil de bout en bout » ci-dessous). T1.4-e a livré R12 §5 étapes 3 et 4 : `today.tsx`
(chantiers du jour, lecture `m4_lister_interventions` + cache local hors ligne — voir « Chantiers
du jour »), `job/[id]/index.tsx` (statut et transitions en route/arrivé/pause par la file
sortante, verdict serveur affiché — voir « Écran `job/[id]/index.tsx` »), `checklist.tsx`,
`photos.tsx`, `signature.tsx` (preuves de chantier, fichier local + SHA-256, jamais de binaire
dans une mutation) et la préparation de la structure `PreuvesCompletion`
(`src/m4/preuvesCompletion.ts`, INCHANGÉ par cette tranche). **T1.4-f livre R12 §5 étape 5 — la
dernière étape qui manquait pour fermer la chorégraphie « Travaux terminés » de bout en bout côté
mobile** : l'envoi RÉEL des fichiers (photos après/signature) par blocs via la file sortante
(`src/fichiers/`, voir « Envoi de fichiers par blocs » ci-dessous — comble le GAP documenté par
T1.4-e), `complete.tsx` (« Terminer », références serveur résolues, dépendance d'ordre
fichiers-avant-complétion) et `materials.tsx` (M6.10, formulaire des matériaux utilisés) — voir
« Écran `complete.tsx` » et « Écran `materials.tsx` » ci-dessous. **Un seul identifiant d'appareil
dans toute l'app depuis T1.4-e** : `punch.tsx` et `job/[id]/index.tsx` lisent tous les deux
`src/protocole/configuration.ts::obtenirConfigurationAppel()` (la VRAIE identité d'appairage) —
voir « Écran `punch.tsx` ». Étape 6 (R12 §5) livrée ensuite : `(admin)/approvals`, le propriétaire liste et décide les demandes
d'approbation N3 et N4 (voir « Écran `approvals.tsx` »). Reste l'E2E Maestro contre un core réel — voir
« Ce qui n'est PAS encore fait ». T1.4-b (idempotence côté socle) et T1.4-c1 (le core transmet la clé,
l'appareil et son heure dans le `_meta` MCP) sont faits côté serveur — voir
[`IDEMPOTENCE.md`](IDEMPOTENCE.md) et la section « `/tools/invoke` » ci-dessous ; le trajet réel
appareil → core → moteur reste à prouver (T1.5). **T1.4-c6 a corrigé un défaut de fond** : `/tools/invoke`
ne voyait aucun outil MCP de département, quel que soit le nom, et l'app n'aurait reçu que des 404 ou
des 400. Le core a maintenant une porte d'appareil vers le serveur du département — voir « Nom d'un
outil de l'app au moteur » ci-dessous.

**T1.4-c5 : l'app apprend sa personne et son rôle nommé.** Le rôle de la poignée de main reste
`"operator"`, mais ce n'est plus lui que la garde de routes regarde : après l'appairage, à chaque
démarrage, à chaque retour au premier plan et à chaque retour du réseau, l'app lit
`GET /opsys/identite` avec son jeton d'appareil. Le core répond avec la personne et le rôle
(`admin`, `employee`, `seller`) que `opsys/appareils.json` attribue à cet appareil, par le même code
que la porte d'outils. L'app affiche cette identité, choisit son profil d'après le rôle NOMMÉ, envoie la
personne comme technicien (elle ne la demande plus à l'employé) et n'ouvre aucun profil sans identité :
voir « Identité de l'appareil » ci-dessous.

**T1.4-l : la file sortante suit le jeton courant et la personne.** Avant, le vidangeur gardait le jeton du
moment de sa construction jusqu'au redémarrage, un 401 marquait chaque mutation `echec_permanent`, et rien
ne disait à qui appartenait une mutation en file. Maintenant : le jeton est relu avant chaque envoi ; chaque
mutation porte sa personne ; après un nouvel appairage pour la MÊME personne elle part avec le nouveau
jeton, pour une AUTRE personne elle reste en quarantaine visible (jamais envoyée, jamais supprimée) ; un
refus d'appareil (401, attribution retirée) arrête la vidange et renvoie l'app à l'écran d'identité : voir
« La file suit le jeton et la personne » ci-dessous.

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

**T1.4-f n'ajoute AUCUNE brique** : l'envoi de fichiers par blocs (`src/fichiers/`, voir « Envoi
de fichiers par blocs ») n'utilise que des modules déjà présents (`expo-file-system` pour la
lecture d'octets, `expo-crypto` pour le hachage, `expo-sqlite` via `src/outbox/service.ts`) plus
un encodeur base64 standard écrit à la main (`src/fichiers/base64.ts`, même raison que
`src/appairage/base64url.ts` : RN/Hermes ne garantit ni `btoa` ni `Buffer`) — donc rien à
inscrire dans `docs/research/INGREDIENTS.md`.

## Rôles et routage (`src/roles/`)

Quatre profils (DEFINITION-PRODUIT §9) = quatre groupes Expo Router : `(employee)`, `(seller)`,
`(admin)`, `(client)`. `src/roles/garde.ts` exporte `evaluerGarde(session, groupeCible)`, une
fonction **pure** : rôle NOMMÉ de l'appareil (confirmé par le serveur, voir « Identité de l'appareil »)
→ groupe autorisé (mappage un-à-un, R12 §6), fail-closed (session absente, rôle inconnu et rôle valide
mais différent du groupe visé refusent tous les trois, vers `/`, l'aiguilleur `app/index.tsx` qui choisit
d'après l'état de l'app : appairage, écran d'erreur d'identité ou groupe du rôle). Chaque `_layout.tsx` de
groupe appelle cette garde avant de rendre quoi que ce soit — un appareil `employee` n'atteint donc
jamais `(admin)`, y compris par URL directe. `src/roles/contexte.tsx` porte l'état de l'app en React
Context ; il démarre toujours en `restauration` au premier rendu (`app/_layout.tsx` relit ensuite
`expo-secure-store` — voir « Appairage » ci-dessous), et la session que la garde regarde en est dérivée :
un profil n'existe que si une identité existe (`src/identite/etat.ts`). 446 tests
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

**Levée par T1.4-c5** : l'app envoie `opsys-mobile`, et le core ne le classe PAS comme app native. Voir
« Identifiant de client » plus bas.

### Ce que fait l'écran (`app/pairing/index.tsx`)

Saisie du **code seulement** (pas de lecture QR — `expo-camera` alourdirait cette tranche pour un
gain marginal tant que le code peut être copié/collé ou tapé ; à ajouter dans une tranche dédiée
si le besoin terrain le justifie). Au bouton « Appairer » : `chargerOuCreerIdentite` (première
fois : graine aléatoire `expo-crypto.getRandomBytes(32)` → identité Ed25519, persistée ; fois
suivantes : relit la même identité — le `deviceId` reste stable pour l'historique d'approbation
côté propriétaire) → `appairerAppareil` (`src/appairage/client.ts`, la machine à états décrite
ci-dessus, avec recul exponentiel réutilisé tel quel de `src/outbox/recul.ts` entre les
tentatives pendant l'attente d'approbation) → au succès, `sauvegarderSession` (jeton, rôle, URL,
`appareilId`) dans `expo-secure-store` et `definirConfigurationAppel` (`src/protocole
/configuration.ts`) sont appelés, puis `apresAppairage` (`src/identite/hooks.ts`) met l'état de l'app
en « lecture de l'identité » et lit l'identité auprès du serveur, et `router.replace("/")` laisse
`app/index.tsx` attendre cette lecture, puis ouvrir le groupe du rôle nommé ou l'écran d'erreur
d'identité (voir « Identité de l'appareil »). `app/_layout.tsx` restaure la même session au démarrage
(`CycleIdentiteApp`, lit `expo-secure-store` puis relit l'identité) sans repasser par un nouvel
appairage. Écran non testé en rendu (même limite que `punch.tsx`, pas de
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

**Levé par T1.4-c5, autrement que prévu.** Ce n'est pas la poignée de main qui porte le rôle nommé, c'est un
appel dédié authentifié par le jeton d'appareil (`GET /opsys/identite`, section suivante). `hello.auth.role`
reste `"operator"` et n'entre plus dans la session : `SessionAppairee.role`, gardé dans le coffre, est le rôle
de TRANSPORT, sans autre usage. La garde de routes regarde le rôle nommé confirmé par le serveur.

## Identité de l'appareil (PLAN T1.4-c5)

### Constat (lu dans le fork, base 1bd1cca)

Après l'appairage, le core ne donnait à l'app que le rôle de transport `operator`, que la garde refuse. Il
attribue bien une personne et un rôle nommé à chaque appareil (`opsys/appareils.json`, T1.4-c2 et c4), mais
il ne le disait qu'au moteur, dans le `_meta` de chaque appel d'outil. L'app ne savait donc ni qui elle
représentait ni quel profil ouvrir, d'où l'identifiant d'employé saisi à la main sur `punch.tsx`,
`job/[id]/index.tsx` et `consent.tsx`, que le serveur confrontait de toute façon (T1.4-k1).

### Décision : un appel dédié authentifié par le jeton, pas la poignée de main

`GET /opsys/identite` (`core/src/gateway/opsys-device-identity-http.ts`, monté par `server-http.ts`).
Quatre raisons, toutes vérifiées par lecture :

1. **L'attribution vient après.** Elle est faite par `opsys appareils appairer`, APRÈS l'approbation native du
   propriétaire (deux temps, T1.4-c4). Le `hello-ok` part à l'approbation : il ne peut pas porter une
   identité que l'appareil n'a pas encore. Seul un appel fait plus tard, et répété, le peut.
2. **L'app ne se reconnecte pas en WebSocket.** Elle ferme la socket dès qu'elle a le jeton, puis ne parle
   plus qu'en HTTP. « À chaque reconnexion » veut dire à chaque démarrage, retour au premier plan et retour
   du réseau : un appel HTTP avec le jeton qu'elle garde déjà, sans refaire toute la poignée de main.
3. **Une révocation ou une réattribution se voit.** Le prochain appel donne un refus ou une autre personne.
4. **`hello-ok` est une trame gelée** (Wire v4, `HelloOkSchema`, schéma strict), commune à tous les clients
   de la passerelle. Une route neuve est plus petite et plus sûre qu'un champ de plus dans cette trame.

### Ce que le core lit, et ce qu'il ne lit jamais

- Le `deviceId` vient du jeton d'appareil VÉRIFIÉ, par la même chaîne que `/tools/invoke`
  (`authorizeScopedGatewayHttpRequestOrReply` avec `allowDeviceToken`, portée `operator.read` : méthode
  `health`). Rien de ce que l'app envoie n'est lu : ni requête, ni en-tête, ni corps ne peuvent nommer un
  autre appareil ou une autre personne.
- La personne et le rôle viennent de `opsys/appareils.json`, par `resolveOpsysDeviceIdentity`
  (`opsys-device-roles.ts`), le même code que `authorizeOpsysDeviceTool` (la porte d'outils) : ce que l'app
  apprend d'elle-même est ce que la porte applique.
- Le secret partagé n'est pas un appareil : il reçoit 403 `device_required`, jamais une identité.
- Un jeton révoqué ou inconnu reçoit 401. Un appareil sans attribution (jamais attribuée, ou révoquée) reçoit
  403 `device_unknown`, un rôle que `roles.json` ne déclare pas 403 `role_unknown` : jamais une identité par
  défaut.

Réponse : `200 { ok: true, identite: { appareilId, personne, role } }`, ou
`403 { ok: false, error: { type: "forbidden", reason, message } }`. `Cache-Control: no-store`. GET seulement.

### Côté app (`src/identite/`)

| Module | Rôle |
|---|---|
| `contrat.ts` | types, rôles nommés (`admin`, `employee`, `seller`, comparés strictement), `interpreterReponseIdentite` (pure) |
| `client.ts` | `lireIdentiteServeur` : le GET, avec le seul jeton ; ne lève jamais |
| `etat.ts` | l'état de l'app et sa décision, pures : `restaurerEtat`, `decider`, `sessionDepuisEtat` |
| `stockage.ts` | dernière identité confirmée, dans `expo-secure-store` (même coffre que le jeton) |
| `service.ts` | restauration du coffre, lecture, écriture de la dernière identité confirmée |
| `hooks.ts` | `useCycleIdentite` : une seule lecture à la fois par session, résultat jeté si la session a changé |
| `BandeauIdentite.tsx` | affiche la personne, le rôle, et « à reconfirmer » |

États (`EtatIdentite`) et ce que chacun ouvre :

| État | Profil ouvert |
|---|---|
| `restauration`, `en_lecture` | aucun (l'aiguilleur attend) |
| `non_appairee` | aucun (`/pairing`) |
| `confirmee` | le groupe du rôle nommé |
| `a_reconfirmer` | le groupe du rôle gardé (serveur injoignable) |
| `erreur` | aucun (`/identite`) |

Règles, toutes testées (Jest) :
- **Fail-closed.** Seule une identité complète, d'un rôle nommé connu et DE CET appareil, est confirmée. Un
  rôle inconnu (`operator`, `ADMIN`, `client`, vide), une personne vide, un rôle absent ou l'identité d'un autre
  appareil sont refusés. Jamais un profil par défaut, jamais le rôle de transport.
- **Un refus retire le profil.** Tout ce que le serveur refuse ou rend de travers (401, 403, autre 4xx, corps
  JSON qui n'est pas une identité) efface l'identité gardée : un appareil révoqué ne garde pas son profil.
- **Hors ligne.** Réseau coupé, délai, 408, 429, 5xx ou corps illisible (portail captif) ne disent rien de
  l'attribution : la dernière identité confirmée sert, marquée « à reconfirmer », et le bandeau le dit. Sans
  identité gardée, c'est une erreur (`hors_ligne_sans_memoire`).
- **Un nouvel appairage repart de zéro.** L'identité gardée est effacée, la lecture recommence.
- **Coffre illisible.** Ce n'est pas « non appairé » : erreur `stockage_illisible`, avec « Réessayer ». La
  configuration déjà en mémoire n'est pas retirée.
- **Démarrage à froid.** Avant T1.4-c5, l'aiguilleur redirigeait vers `/pairing` avant que le coffre soit
  relu, et une session restaurée restait sur l'écran d'appairage. L'aiguilleur attend maintenant la
  restauration.

### Écrans

- `app/index.tsx` : l'aiguilleur unique. Toute garde de groupe qui refuse renvoie à `/` (avant : `/pairing`).
- `app/identite/index.tsx` : l'erreur, avec le texte du motif, l'identifiant de l'appareil (que le propriétaire
  donne à `opsys appareils appairer`), « Réessayer » et « Appairer de nouveau ».
- `punch.tsx`, `job/[id]/index.tsx`, `consent.tsx` : plus de champ « technicien ». Ils envoient la personne
  confirmée (`usePersonneAppairee`) et refusent d'agir sans elle. Le serveur la confronte toujours à
  l'identité authentifiée du jeton (T1.4-k1) : un identifiant qui n'est pas celui de la personne est refusé.
  Une mutation créée hors ligne porte la personne gardée ; si l'appareil est réattribué entre-temps, le
  serveur la refuse et le verdict s'affiche.
- Les trois accueils affichent le bandeau d'identité.

### Preuve et limites

Jest et `tsc` (`mobile/`) ; côté core, vitest de CI seulement (`core/test/opsys-tests-cibles.txt`) :
`opsys-device-roles.test.ts`, `opsys-device-identity-http.test.ts` (appairage réel, vrais fragments),
`server-http.opsys-device-identity.test.ts` (route montée), `opsys-mobile-trust.test.ts`. Les écrans ne sont
pas testés en rendu (pas de bibliothèque de test de rendu) ; des gardes lisent leur source
(`ecransSansSaisie.test.ts`) pour empêcher le retour de la saisie à la main.

- Le trajet réel (appareil → core → moteur) reste à prouver (T1.5) : rien de tout cela n'a tourné contre un
  core réel.
- Un core plus ancien, sans la route, répond 404 : refus (`refus_inattendu`), jamais un profil.
- `personne` est l'identifiant OPSYS (`jdupont`), pas un nom d'affichage : `appareils.json` ne porte pas le
  nom. Un nom complet demanderait une clé sœur additive dans ce fragment.
- La lecture n'a pas de contre-mesure au martelage autre que le limiteur d'authentification de la passerelle.
- Avant T1.4-l, `src/outbox/service.ts` gardait son vidangeur (avec le jeton du moment) sans le refaire quand
  la session changeait : après un nouvel appairage, la file gardait l'ancien jeton jusqu'au redémarrage.
  Corrigé : la file relit la session avant chaque envoi, voir « La file suit le jeton et la personne ».

## Identifiant de client (PLAN T1.4-c5)

L'app se présente au core sous `opsys-mobile` (`GATEWAY_CLIENT_IDS.OPSYS_MOBILE`, ajouté par T1.4-c4), sur
iOS comme sur Android (la plateforme voyage dans `client.platform`). Avant, elle empruntait `openclaw-ios` et
`openclaw-android`.

**Décision : `opsys-mobile` n'entre PAS dans `isNativeAppUiClient`.** Ce que cette classe ouvre, lu dans le
fork :
- le rafraîchissement silencieux des métadonnées d'un appareil, seulement pour une connexion locale directe
  (`shouldAllowSilentLocalPairing`, raison `metadata-upgrade`) ;
- l'approbation automatique par proxy de confiance, seulement si `trustedProxy.deviceAutoApprove` est
  configuré (`resolvePairingApprovalPlan`).

Un téléphone n'est pas une connexion locale directe, et OPSYS ne configure pas de proxy de confiance : la
classe n'apporterait rien, et élargirait la confiance. Un téléphone s'appaire par l'approbation explicite du
propriétaire, et son identité OPSYS vient d'une attribution explicite.

Ce que l'app perd en quittant `openclaw-ios` et `openclaw-android`, lu dans le fork, et pourquoi cela ne
compte pas :
- l'admission d'appairage par code de configuration ne reconnaît ces identifiants que pour le rôle `node`
  (`isMobileNodeBootstrapConnect`), que l'app OPSYS n'utilise pas : elle se connecte en `operator` ;
- `resolvePinnedClientMetadata` accepte en silence un changement de version d'OS pour ces deux
  identifiants (`ios 17.1` devenu `ios 17.2`). L'app envoie une plateforme fixe, `ios` ou `android`, sans
  version : aucune dérive à absorber ;
- la livraison des approbations d'exécution (`EXEC_APPROVAL_CLIENT_IDS`) passe par une socket ouverte, que
  l'app ferme dès qu'elle a son jeton ;
- l'épinglage d'identifiant de client ne concerne que le copilote de navigateur.

Épinglé par `core/src/gateway/opsys-mobile-trust.test.ts` : la trame `connect` de l'app est valide avec cet
identifiant, et `isNativeAppUiClient` le refuse. Si quelqu'un l'ajoute à la classe, ce test échoue et
demande une décision. Cette décision est à confirmer par la revue externe (code d'admission critique).

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
  `depot.sqlite.ts` (adaptateur réel, DDL de la table `outbox`). Le pont natif d'`expo-sqlite` n'existe pas
  sous Jest, mais depuis T1.4-l le SQL de l'adaptateur (DDL, migration, insertion, lecture) est exercé sur
  un vrai moteur SQLite (`node:sqlite`) par `depot.sqlite.test.ts`. Seul le pont natif reste à vérifier
  sur appareil.

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
(rien n'est lu en dur — dépôt, `fetch`, session d'envoi, horloge sont tous injectés dans
`ConfigurationVidangeur`), donc entièrement testable avec un faux transport
(`src/outbox/vidangeur.test.ts`, faux `fetch`). `src/outbox/service.ts` fournit la configuration
réelle (SQLite via `expo-sqlite`, `fetch` global) — non testé unitairement (pas de SQLite natif sous
Jest). **Depuis T1.4-l** le jeton, l'URL et l'identifiant d'appareil ne sont plus des champs de la
configuration : `session()` est relue avant CHAQUE envoi (voir la section suivante).

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

## La file suit le jeton et la personne (PLAN T1.4-l)

### Constat

Trois défauts, lus dans le code d'avant :
1. `service.ts` construisait le vidangeur UNE fois, avec le jeton du moment, et le gardait jusqu'au
   redémarrage. Après « Appairer de nouveau », la file envoyait avec l'ancien jeton.
2. Un jeton révoqué recevait 401, classé « refus définitif » (4xx non réessayable) : chaque mutation en
   file devenait `echec_permanent`, donc perdue pour toujours, alors que rien n'était faux dans la mutation.
3. Rien ne disait à qui appartenait une mutation en file. Un appareil appairé pour quelqu'un d'autre
   aurait envoyé les mutations de la première personne sous l'identité de la seconde. Le serveur ne le voit
   pas toujours : une décision d'approbation ou un bloc de fichier ne nomment pas la personne.

### Décisions

**Le jeton se relit à chaque envoi.** `ConfigurationVidangeur.session()` remplace `urlBase`, `jeton` et
`appareilId`. Le vidangeur est construit une seule fois (un seul verrou pour toute l'app) et ne garde
aucun jeton. La session est lue au dernier moment, juste avant l'appel : le jeton envoyé est le jeton
courant, et il vient du même instantané que la personne (jamais deux lectures).

**La session d'envoi est liée au jeton.** `obtenirSessionEnvoi()` (`src/protocole/configuration.ts`) rend
la configuration ET la personne, seulement si la personne confirmée l'a été POUR CE JETON et cet appareil
(`PersonneConfirmee`). Après un nouvel appairage, il n'y a donc aucune session tant que le serveur n'a pas
dit qui est cette personne pour le NOUVEAU jeton : rien ne part avec l'ancien jeton, rien avec le nouveau
avant confirmation. Le cycle d'identité (`src/identite/hooks.ts`) la tient à jour à chaque changement
d'état (`synchroniserPersonneConfirmee`, pure). Hors ligne, la dernière identité gardée (« à
reconfirmer ») suffit, comme pour ouvrir le profil ; un coffre illisible ne retire pas ce qui est déjà en
mémoire.

**Chaque mutation porte sa personne.** Colonne `proprietaire` de la table `outbox` : la personne confirmée
par le serveur à l'instant de l'insertion, posée par `avecProprietaire` (`src/outbox/proprietaire.ts`,
enveloppe du dépôt que rend `obtenirDepot()`), jamais modifiée ensuite. Les écrans et services n'ont rien
à passer. Sans personne confirmée, l'insertion échoue : jamais une mutation orpheline. Migration SQLite :
`ALTER TABLE ... ADD COLUMN` au démarrage, une seule fois (`initialiserSchemaOutbox`) ; les lignes
d'avant T1.4-l gardent `NULL`.

**Ce que deviennent les mutations en attente** (`en_attente` et `envoi`) :

| Situation | Décision |
|---|---|
| Même personne, nouveau jeton | Elles partent avec le nouveau jeton. Même `id`, donc même clé d'idempotence : le serveur rejoue, jamais deux applications. |
| Autre personne | **Quarantaine.** Conservées à l'identique (statut, tentatives, `id`), jamais envoyées sous la nouvelle identité, jamais supprimées. Comptées dans `RapportVidange.quarantaine` et montrées dans le bandeau d'identité (« N envoi(s) en attente appartiennent à une autre personne »). Elles repartent d'elles-mêmes si l'appareil est de nouveau appairé pour leur personne. |
| Propriétaire inconnu (`NULL`, lignes d'avant T1.4-l) | Même quarantaine, fail-closed : on ne devine pas une identité. |
| Appareil réattribué sans nouvel appairage | Même règle : la relecture de l'identité donne une autre personne, la file ne lui envoie que ses propres mutations. |

La quarantaine n'est ni une suppression, ni un export, ni un transfert vers la nouvelle personne. La
suppression définitive de données est une frontière humaine (T3, AGENTS.md) : sortir une mutation de la
quarantaine autrement que par le retour de sa personne se décidera avec le propriétaire, dans une tranche
dédiée. Les `brouillon` (enregistrements locaux pas encore soumis) ne sont pas comptés : ils n'attendent
aucun envoi.

**Un refus d'appareil arrête la vidange.** `estRefusAppareil` (`src/protocole/classification.ts`), lu dans le
fork : 401 (jeton inconnu ou révoqué) ; 403 `tool_call_blocked` dont le message nomme `device_unknown`
(attribution retirée) ou `role_unknown`. Tout autre 4xx reste un refus de LA mutation (`tool_out_of_scope`,
`server_unknown`, `deviceId` du corps, 400, 404) : traiter ceux-là comme un refus d'appareil bloquerait
toute la file derrière une seule mutation refusée pour son outil. Sur un refus d'appareil :
1. la mutation redevient `en_attente`, sans tentative comptée ni recul (`remettreEnAttenteSansFaute`,
   uniquement depuis `envoi`) : pas sa faute, elle repartira avec la même `id` ;
2. la passe s'arrête tout de suite (`RapportVidange.arret = appareil_refuse`), sans toucher au reste de la
   file ; un essai par passe, jamais une boucle de réessais ;
3. `creerDeclencheurVidange` (`declenchement.ts`) signale le refus UNE fois (`refusAppareil.ts`) ; la racine
   (`app/_layout.tsx`) relit alors l'identité (`GET /opsys/identite`) SANS relancer de vidange ;
4. le jeton révoqué y reçoit 401 : état `erreur` (`jeton_refuse`), la personne confirmée est retirée (plus
   rien ne part), l'aiguilleur renvoie à `/identite`, qui dit que les envois en attente sont conservés et
   propose « Appairer de nouveau ». Si le serveur confirme l'identité malgré le refus (refus passager),
   rien de plus : le prochain déclencheur ordinaire réessaie.

Un refus qui arrive APRÈS un nouvel appairage vise l'ancien jeton, pas l'appareil tel qu'il est : la passe
s'arrête (`session_changee`), aucun signal.

**La file repart après l'identité.** La racine fait `rafraichir()` puis `declencherVidange()` au démarrage,
au premier plan et au retour du réseau ; l'écran d'appairage lance une vidange une fois l'identité lue. Le
signal de refus ne relance jamais de vidange (sinon vidange, refus, lecture, vidange... en boucle si le
serveur refusait les outils mais confirmait l'identité).

### Preuve et limites

Jest et `tsc` (`mobile/`), 987 tests dans 66 fichiers (892 dans 60 avant T1.4-l). `vidangeur.test.ts` : jeton relu à chaque envoi
(changement en cours de passe), réappairage de la même personne (même clé d'idempotence), autre personne
(zéro appel réseau, file identique, quarantaine), propriétaire inconnu, personne qui change en cours de
passe, révocation 401 et 403, arrêt au premier refus, refus d'un ancien jeton. `suiviDuJeton.test.ts` :
le câblage réel (configuration, personne confirmée, dépôt propriétaire, vidangeur, signal) à travers
plusieurs appairages. `depot.sqlite.test.ts` : le vrai SQL, dont la migration d'une base d'avant T1.4-l.

- Jamais exécuté contre un core réel (T1.5), ni le pont natif d'`expo-sqlite`.
- La raison d'un 403 d'appareil se lit dans le TEXTE du message du core (`(device_unknown)`), faute de
  champ structuré sur `/tools/invoke` (contrairement à `/opsys/identite`, qui porte `reason`). Si le core
  change ce texte, ce 403 redevient un refus de mutation (`echec_permanent`) : à corriger côté core en
  ajoutant un `reason` structuré, ce que cette tranche (mobile seulement) ne fait pas. Un 403 « missing
  scope » (jeton sans portée) n'est pas lu comme un refus d'appareil.
- Les écrans ne filtrent pas les `brouillon` d'une autre personne (photos, signature locales) : ils ne
  partent jamais, mais un écran de la nouvelle personne peut les voir.
- Une mutation de la nouvelle personne qui dépend (`dependsOn`) d'une mutation en quarantaine attend
  sans être signalée dans `bloquees` (cas rare : un fichier d'une personne, la complétion d'une autre).
- La quarantaine n'a pas d'écran de gestion : elle se voit (bandeau) et se résout par le retour de sa
  personne.

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
- `technicien_id`/`intervention_id` NE sont PAS dans ce contexte provisoire (`job/[id]/index.tsx`,
  depuis T1.4-e, connaît `intervention_id` automatiquement — voir « Écran `job/[id]/index.tsx` »).
  **Depuis T1.4-k**, `technicien_id` n'est pas libre côté serveur : pour un appel d'appareil d'un employé,
  il DOIT être l'identifiant OPSYS de la personne authentifiée (l'identifiant de technicien EST celui de
  la personne), sinon `REJ-IDENTITE-FOURNIE-DIFFERENTE` (jamais remplacé en silence), et l'intervention
  doit lui être assignée (`REJ-INTERVENTION-NON-ASSIGNEE`). **Depuis T1.4-c5**, l'employé ne saisit plus
  son identifiant : le serveur donne sa personne à l'app (« Identité de l'appareil »), et l'écran envoie
  cette personne (`usePersonneAppairee`), sans jamais créer de mutation s'il n'en a pas.

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
QUE `{intervention_id, statut, lead_id, type_travaux, devis_id}` (depuis T0.13-b, `service` REMPLACE
`type_travaux` pour une intervention issue d'un lead v2 : `estInterventionM4` en exige exactement une, jamais
l'une déduite de l'autre) : ni date/fenêtre de cédule, ni
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

**Depuis T1.4-k, le serveur filtre pour l'employé** : `m4_lister_interventions` ne rend, pour un appel
d'appareil `employee`, que les interventions qui lui sont assignées (`technicien_assigne` = sa
personne, consigné par `m4_planifier_intervention` avant le départ) ; l'admin voit toutes celles du
dispatch. Une intervention non cédulée n'est à personne : aucun employé ne la voit.
`m4_statut_intervention` répond `statut: null` pour l'intervention d'un autre, comme pour une
inconnue (indiscernable) : `interpreterResultatStatutIntervention` le lit déjà comme un statut
inconnu, pas comme une erreur. Le mobile n'a rien à filtrer de son côté.

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
`punch_in`/`punch_out` (descripteurs T1.4-d inchangés, réutilisés tels quels). `technicien_id` est la
personne que le serveur a confirmée pour l'appareil (T1.4-c5, comme `punch.tsx`) ; `appareilId` vient de
la VRAIE session appairée (voir « Écran `punch.tsx` » ci-dessus). Verdict serveur affiché sur un
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

**INCHANGÉ par T1.4-f, précision sur son rôle réel.** `extraireReferencesPhotosLocales`/
`extraireReferencePhotosApres`/`extraireReferenceSignatureLocale` servent encore aujourd'hui,
mais SEULEMENT comme DÉCOUVERTE de candidats (« quelles captures locales existent pour ce
chantier »), jamais comme source des références FINALES envoyées à `m4_completer_intervention` :
`complete.tsx` (ci-dessous) résout les vraies références serveur via
`src/fichiers/etatEnvoi.ts::calculerEtatEnvoiFichier`, une fois l'envoi par blocs `complet`. Les
deux mécanismes coexistent sciemment plutôt que d'être fusionnés : le premier (T1.4-e, `src/photos/`,
`src/signature/`) reste la structure de capture locale, inchangée ; le second (T1.4-f, `src/fichiers/`)
est le transport, entièrement nouveau — voir « Envoi de fichiers par blocs » ci-dessous.

## Envoi de fichiers par blocs (`src/fichiers/`, R12 §4, PLAN T1.4-f)

**Comble le GAP documenté par T1.4-e** (« aucune route serveur pour recevoir l'envoi BINAIRE
d'une photo ou d'une signature ») : un autre agent livre la route serveur EN PARALLÈLE
(`m4_deposer_fichier`/`m4_etat_fichier`, absents de `departments/`/`core/` au moment d'écrire ce
module — vérifié par recherche, rien à lire) ; ce module implémente le CONTRAT FIXE donné par la
mission, testé UNIQUEMENT contre un transport/lecteur de fichier factices, jamais contre un
serveur réel (mission, cadre de travail) — voir « Ce qui n'est PAS encore fait » pour la preuve
qui reste à faire contre un core réel (T1.5).

**Contrat** (`src/fichiers/protocole.ts`) :
- `m4_deposer_fichier(empreinte_sha256, taille_octets, type_mime, index_bloc, nombre_blocs,
  bloc_base64) -> {"accepte": true, "resultat": {"reference", "complet", "blocs_recus"}} |
  {"accepte": false, "verdict": {"code", "detail"}}` — même patron `depuis_couple` que
  `m4_pointer`. `type_mime` : `"image/jpeg" | "image/png"` seulement (`TypeMimeFichier`).
  `reference` = `"fichier:sha256:<empreinte>"`, DÉTERMINISTE depuis l'empreinte déjà connue
  localement (`construireReferenceFichier`) — le mobile n'a donc jamais besoin de relire la
  chaîne exacte renvoyée par le serveur pour la calculer, seulement pour savoir QUAND le fichier
  est `complet`.
- `m4_etat_fichier(empreinte_sha256) -> {"accepte": true, "resultat": {"existe", "complet",
  "blocs_recus", "reference"}}` — même patron, utilisé pour la REPRISE (voir plus bas).

**Découpage** (`src/fichiers/decoupage.ts`) : blocs FIXES de `TAILLE_BLOC_OCTETS` = 262 144
octets décodés, sauf le dernier (1..262 144) — `decouperEnBlocs` (vue `subarray`, jamais une
copie du fichier complet). `validerTailleFichier` refuse localement, AVANT toute tentative
réseau, un `taille_octets` hors 1..`TAILLE_FICHIER_MAX_OCTETS` (10 485 760, 10 MiB) — avec le
MÊME code `REJ-FICHIER-TROP-VOLUMINEUX` que le serveur utiliserait, pour un vocabulaire unique
peu importe où le refus est détecté ; `nombre_blocs` (borne contractuelle 1..64) n'est pas
revalidé séparément, la borne de taille le couvre déjà entièrement (10 485 760 / 262 144 = 40).
Encodage base64 STANDARD (`src/fichiers/base64.ts::encoderBase64Standard`, alphabet `+/` avec
remplissage `=`) — DIFFÉRENT du base64url de `src/appairage/base64url.ts` (charge d'appairage
v3) : deux modules distincts pour ne jamais mélanger les deux alphabets sous un seul nom, testés
chacun contre l'oracle Node `Buffer`/`crypto`.

**Vérification fail-closed avant tout envoi** (mission item 1 : « vérifie que le SHA-256 relu
correspond à celui capturé ; sinon état d'erreur explicite, jamais d'envoi ») —
`src/fichiers/verification.ts::verifierEmpreinteFichier` relit les octets RÉELS du fichier local
(`expo-file-system`, injecté) et les rehache (même brique partagée `src/fichiers/empreinte.ts`
que la capture, T1.4-e) ; toute discordance (fichier modifié/corrompu entre la capture et l'envoi,
potentiellement bien plus tard) bloque `preparerEnvoiFichier` AVANT le moindre découpage/appel
réseau — `envoiOrchestrateur.test.ts` le prouve : aucune mutation `fichier_bloc` n'est créée dans
ce cas.

**Une mutation `fichier_bloc` par bloc, par la file sortante** (`src/outbox/types.ts` : nouveau
`TypeMutation`, catalogue R12 §4 explicitement ouvert par son « … » terminal) —
`src/fichiers/envoiOrchestrateur.ts::preparerEnvoiFichier` construit et enfile (`creerMutation`
→ `soumettreMutation` → `depot.inserer`, MÊME discipline que tout le reste de `src/outbox`) un
bloc à la fois, chacun avec SA PROPRE clé d'idempotence (son propre `mutation.id`, jamais
partagée entre blocs) ; le descripteur `fichier_bloc -> m4_deposer_fichier`
(`src/outbox/descripteurs.ts`) branche l'envoi RÉEL sur le vidangeur GÉNÉRIQUE déjà existant
(T1.4-d) — aucune boucle d'envoi dupliquée, `envoiOrchestrateur.ts` ne fait jamais lui-même
d'appel `/tools/invoke` à l'exception de la lecture de `m4_etat_fichier` ci-dessous.
`photo_upload`/`signature_capture` (T1.4-e) restent TELS QUELS, toujours sans descripteur, sans
jamais devenir `en_attente` : ce sont les enregistrements LOCAUX de capture (URI + SHA-256), pas
le transport — `src/fichiers/candidats.ts` les lit (payload complet, pas seulement l'id, à la
différence de `preuvesCompletion.ts::extraireReferencesPhotosLocales`) pour construire la liste
des fichiers à envoyer.

**État d'un fichier calculé PUREMENT depuis la file locale** (`src/fichiers/etatEnvoi.ts`,
`calculerEtatEnvoiFichier`) : `non_demarre` (aucun bloc encore enfilé) / `en_cours` (au moins un
bloc pas `envoyee`, aucun `echec_permanent`) / `complet` (TOUS les blocs `envoyee` — reference
alors dérivée localement) / `echec_permanent` (au moins UN bloc en échec permanent, PRIORITAIRE
même si les autres ont réussi — reprendre les mêmes octets sous une nouvelle clé d'idempotence ne
changerait pas l'issue d'un rejet business, voir plus bas). Jamais un appel réseau supplémentaire
pour cette lecture : le statut `envoyee` d'un bloc N'EST posé par le vidangeur QU'À l'accusé de
réception du serveur pour CE bloc précis (R12 §4), donc « tous les blocs envoyee » est déjà la
même vérité que le serveur porterait dans `blocs_recus`/`complet`.

**Reprise via `m4_etat_fichier`** (mission item 1) : AVANT de découper/encoder, `preparerEnvoiFichier`
consulte optionnellement `config.obtenirEtatServeur` (lecture DIRECTE, PAS par la file — même
patron que `m4_statut_intervention`, `src/today/statut.ts` — câblée réellement dans
`src/fichiers/service.ts::obtenirEtatServeurReel`) et NE RÉ-ENFILE QUE les indices de bloc que le
serveur n'a pas déjà reçus (`blocsRecus`) — évite de retransmettre un fichier déjà partiellement
envoyé après une interruption (redémarrage, app fermée en plein envoi). Un échec de cette lecture
(hors ligne, technique) N'EST JAMAIS bloquant : traité comme « aucune information de reprise »,
tous les blocs manquants localement sont alors enfilés — la file reste sûre de toute façon
(R12 §4).

**Refus fail-closed, jamais un envoi ni une nouvelle tentative automatique** — `preparerEnvoiFichier`
renvoie un résultat typé (`ResultatPreparationEnvoiFichier`) sans jamais lever :
`type_non_permis` (extension autre que `.jpg`/`.jpeg`/`.png`, voir
`src/fichiers/candidats.ts::deduireTypeMimeDepuisUri` — DÉRIVÉ de l'extension RÉELLE du fichier
local, jamais deviné : les photos sont toujours `.jpg` — capture `imageType: "jpg"`,
`src/photos/service.ts` — et la signature toujours `.png` par défaut de
`react-native-signature-canvas`, vérifié en lisant `node_modules/react-native-signature-canvas
/index.js`, `imageType || "image/png"`, jamais surchargé par `signature.tsx`), `taille_invalide`,
`empreinte_discordante` (voir plus haut), `echec_permanent` (un bloc de CE fichier a déjà été
refusé de façon définitive — l'appelant, `complete.tsx`, doit dire à l'employé de reprendre la
photo/signature, jamais un réessai automatique silencieux).

**Câblage réel** (`src/fichiers/service.ts`, non testé unitairement — même limite documentée que
`src/photos/service.ts`/`src/outbox/service.ts`, pas de FS/réseau natif sous Jest) :
`envoyerFichiersDuChantier(chantierId)` liste TOUS les candidats (photos « après » + signature)
de la file sortante réelle et appelle `preparerEnvoiFichier` sur chacun, séquentiellement (même
raison que `vidangeur.ts` : jamais `Promise.all`).

**Déclenché depuis `complete.tsx` (au montage ET à l'appui sur « Terminer »), jamais depuis
`photos.tsx`/`signature.tsx`** — décision documentée, pas un oubli : ces deux écrans restent
INCHANGÉS par cette tranche (déjà livrés, testés, en usage) plutôt que d'y ajouter un
déclenchement d'envoi qui risquerait une régression. Les déclencheurs GÉNÉRIQUES déjà existants
(`src/outbox/declencheurs.ts`, premier plan/retour réseau, T1.4-d) reprennent ensuite tout ce qui
reste en file même si l'employé quitte `complete.tsx` avant la fin — aucune mutation `fichier_bloc`
n'est jamais perdue. Une tranche future pourrait démarrer l'envoi dès la capture
(`photos.tsx`/`signature.tsx`, plus proche de « photos envoyées en arrière-plan », DEFINITION-PRODUIT.md
§9.2) une fois ce pipeline éprouvé — non fait ici pour limiter le risque sur des écrans déjà en
production (P5, ne pas casser).

**RÉGRESSION-SÛRE, additive** : `RapportVidange` (`src/outbox/vidangeur.ts`) gagne un champ
`resultatsAcceptes: readonly {id, resume}[]` (le `resume` métier de CHAQUE mutation acceptée,
jusqu'ici calculé puis jeté) — nécessaire pour que `complete.tsx` retrouve l'accusé de
`m4_completer_intervention` sans second appel réseau. Purement additif : `envoyees` (déjà
utilisé par `punch.tsx`/`job/[id]/index.tsx`) reste inchangé, testé par les mêmes assertions
qu'avant (`vidangeur.test.ts`, aucune ne comparait l'objet complet).

## Écran `complete.tsx` (« Terminer », R12 §5 étape 5, PLAN T1.4-f)

`app/(employee)/job/[id]/complete.tsx` : construit `PreuvesCompletionM4` avec les RÉFÉRENCES
SERVEUR (jamais les placeholders `mutation_id` de T1.4-e) puis appelle `m4_completer_intervention`
par la file sortante — mission item 2, DEFINITION-PRODUIT.md §9.7 étapes 1-2.

**Dépendance d'ordre obligatoire, structurellement garantie** (mission item 2) —
`src/ecrans/complete.ts::evaluerPreparationCompletion` (fonction PURE, `complete.test.ts`) est
la SEULE porte qui produit `PreuvesCompletionM4` : elle ne rend `pret: true` qu'après avoir
vérifié, DANS CET ORDRE, la checklist (`checklist_complete`), qu'au moins une photo « après »
existe, que l'employé a choisi si une signature est requise, que la signature est présente si
requise, PUIS l'état d'envoi (`calculerEtatEnvoiFichier`) de CHAQUE fichier attendu — `pret`
reste `false` (`fichiers_en_cours`) tant qu'un seul n'est pas `complet`. Il n'existe donc aucun
chemin de code qui construise la mutation `job_completion` avant que ses fichiers ne le soient.
Un SEUL bloc en échec permanent bloque tout (`fichiers_en_echec`, PRIORITAIRE sur `fichiers_en_cours`) :
l'écran affiche `complete.blocages.fichiers_en_echec` et NE RETENTE JAMAIS automatiquement —
l'employé doit reprendre la photo/signature en cause (`photos.tsx`/`signature.tsx`) puis revenir.

**`signature_requise` : demandé explicitement, jamais déduit — limite documentée.** Aucune
donnée serveur n'indique, pour un chantier donné, si une signature client est exigée (même
absence structurelle que le catalogue de checklist, T1.4-e) : plutôt que de le déduire
silencieusement de « une signature a-t-elle été capturée » (ce qui masquerait un chantier où une
signature EST requise mais n'a pas pu être obtenue), l'écran demande un choix explicite
(oui/non, AUCUN par défaut — `signatureRequise: boolean | null`) avant de laisser « Terminer »
avancer, même patron fail-closed que le champ technicien de `job/[id]/index.tsx`.

**Portée volontairement réduite du schéma `m4_completer_intervention`.** Seuls `intervention_id`,
`horodatage`, `preuves_completion`, `signature_requise` sont envoyés
(`src/m4/completion.ts::construireArgumentsCompleterIntervention`) — `photos`,
`description_factuelle`, `consentement_marketing`, `client_satisfait` (des FAITS DU CLIENT, Loi
25, T1.2-f) restent `NON_FOURNI` côté serveur : aucun écran de capture de consentement client
n'existe dans cette tranche ni dans l'ordre de livraison R12 §5 pour T1 — les envoyer sans
capture réelle serait une donnée inventée (AGENTS.md). Une tranche future (rattachée à M7,
DEFINITION-PRODUIT.md §9.3) devra ajouter cet écran avant de les fournir. **`m4_completer_intervention`
n'a PAS de champ « temps réel »** : `duree_reelle_minutes` est calculée PAR LE SERVEUR depuis les
pointages déjà envoyés (`outbox.py::calculer_duree_reelle`, lu) — l'écran n'a donc rien à
transmettre ni à calculer pour §9.7 « temps réel ».

**L'accusé direct de `m4_completer_intervention` n'est pas le WCT complet, et n'a pas à l'être
(PLAN T1.4-i).** `outbox.py::completer_intervention` (étape 13) renvoie un résumé de 8 clés
(`wct_id`, `intervention_id`, `ligne_id`, `statut`, `hash_maillon`, `duree_reelle_minutes`,
`ecart_signale`, `tete_chaine`). Il porte `wct_id`, et c'est tout ce que `materials.tsx` envoie à
`m6_declarer_materiaux_utilises` : M6 relit lui-même la charge `m4.travaux_termines` que M4 a
publiée pour ce `wct_id` (`evenement_id = wct_id`, même transaction que le WCT). **Avant T1.4-i**,
l'outil exigeait le WCT complet (12 clés) de l'appelant et n'en vérifiait que la forme : un appareil
(ou un modèle) pouvait fabriquer un WCT et rattacher des matériaux à un chantier qui n'existe pas,
et l'app relisait `m4_lire_outbox` (l'outbox COMPLET, sans filtre) pour en garder une copie en
cache. Cette relecture, le cache du WCT (`src/m4/wctCache.ts`) et les types qui les portaient
(`WctRecuM4`, `trouverWctParId`, `interpreterResultatLireOutbox`) sont supprimés : un fait vient de
sa source de vérité, jamais de l'appareil (AGENTS.md). Ce qui reste sur l'appareil, par chantier :
le seul `wct_id` de l'accusé (`src/m4/wctIdCompletion.ts`, clé `wct_id_<chantier>_v1`, une chaîne),
parce que l'accusé n'est lu qu'une fois, ici, à la réponse du serveur, et que le lien vers
`materials.tsx` doit survivre à une navigation ou à un redémarrage (R12 §4). Les anciennes entrées
`wct_<chantier>_v1` (WCT complet en JSON) ne sont ni lues ni effacées : un appareil dont l'employé a
terminé un chantier avec l'ancienne version sans avoir rempli les matériaux devra les remplir
autrement que par ce lien.

**Le verdict serveur est affiché TEL QUEL** (mission item 2) : `complete.succes.statut` porte
`resultatCompletion.statut` — `completed_pending_review` ou toute autre valeur renvoyée par le
serveur — jamais reformulé ni maquillé en « succès » générique. Un rejet définitif
(`m4_completer_intervention` refuse, ex. preuves jugées incomplètes côté serveur malgré le
contrôle local, ou `REJ-PREUVE-FICHIER-INTROUVABLE` si une référence ne correspond à aucun fichier
réellement déposé et complet) est affiché de la même façon que `job/[id]/index.tsx`
(`complete.verdict.echecPermanentAvecVerdict`).

**Envoi des fichiers déclenché au montage ET à l'appui sur « Terminer »** — voir « Envoi de
fichiers par blocs » ci-dessus pour la justification (photos/signature déjà capturées
commencent à s'envoyer dès l'arrivée sur cet écran, meilleur effort, jamais bloquant).

**Limite documentée, même famille que celle déjà acceptée pour `punch.tsx` (« portée de
l'affichage du verdict »).** Si la mutation `job_completion` est acceptée/rejetée par un
déclencheur d'ARRIÈRE-PLAN (retour au premier plan, reconnexion) pendant que l'écran est FERMÉ,
ou par une session PRÉCÉDENTE, le texte détaillé (`resultatCompletion`/`dernierVerdict`, React
state PUREMENT local) n'est pas reconstitué à la réouverture — seul le STATUT persisté de la
mutation (`envoyee`/`echec_permanent`) l'est, et l'écran s'appuie dessus pour ne jamais afficher
un mensonge (ex. ne jamais dire « en attente d'envoi » pour une mutation déjà `envoyee`, ne
jamais réactiver le bouton « Terminer » pour une complétion déjà acceptée). Le lien vers
`materials.tsx` reste lui accessible dans ce cas : il se fonde sur le `wct_id` mémorisé
(`src/m4/wctIdCompletion.ts`), pas sur l'état React local. **Exception : si la mutation
`job_completion` est acceptée par un déclencheur d'arrière-plan, l'accusé (donc le `wct_id`) n'est
vu par aucun écran** — `wct_id` non mémorisé, lien absent ; même limite qu'avant T1.4-i pour le
cache du WCT. Amélioration possible d'une tranche future :
persister le verdict détaillé dans la ligne `outbox` elle-même (même remarque déjà faite pour
`punch.tsx`).

Écran non testé en rendu (même limite que les autres écrans de cette tranche) :
`src/ecrans/complete.ts`, `src/fichiers/*`, `src/m4/completion.ts` portent la logique, testée là.

## Écran `materials.tsx` (M6.10, R12 §5 étape 5, PLAN T1.4-f)

`app/(employee)/job/[id]/materials.tsx` : formulaire des matériaux utilisés, ouvert APRÈS
« Terminer » — DEFINITION-PRODUIT.md §9.3/§9.7 étape 3. Envoie `m6_declarer_materiaux_utilises`
par la file sortante (mission item 3).

**Seul le `wct_id` de l'accusé de complétion est envoyé, avec le formulaire** (PLAN T1.4-i) :
`m6_declarer_materiaux_utilises({wct_id, formulaire})`, schéma fermé
(`additionalProperties: false`, plus de `wct` ni de `registre_historique`). `wct_id` vient de
`src/m4/wctIdCompletion.ts`, écrit par `complete.tsx` à l'acceptation de la complétion ; le
formulaire porte le même `wct_id` (`construireArgumentsDeclarerMateriauxUtilises` le prend du
formulaire : une seule source). **M6 lit lui-même le WCT** : la charge `m4.travaux_termines` publiée
par M4 pour ce `wct_id`, validée comme avant (`valider_wct`, `valider_formulaire_materiaux_utilises`).
Un `wct_id` que M4 n'a jamais publié est refusé, sans rien écrire : `REJ-WCT-INCONNU`, affiché tel
quel (échec définitif, comme les autres codes). Aucun `wct_id` mémorisé -> `materials.aucunWct`,
formulaire bloqué (fail-closed) : l'employé doit retourner à l'écran « Terminer ».

**Ce que T1.4-i ne réglait pas, et que T1.4-k règle côté SERVEUR** (le mobile n'a pas changé) : le
serveur savait que le WCT existait, pas que CET appareil avait le droit d'y déclarer. Depuis T1.4-k,
M6 confronte la personne authentifiée de l'appel (`opsys.contexte.identite_appelante()`, revérifiée en
base) au `technicien_id` du WCT : un employé qui envoie le `wct_id` d'un collègue (les `wct_id` sont
des empreintes non secrètes, publiées sur le bus) reçoit `REJ-INTERVENTION-NON-ASSIGNEE`, affiché tel
quel, sans rien écrire. `intervention_id` du formulaire doit être celui du WCT
(`REJ-FORMULAIRE-MATERIAUX-INTERVENTION-INCOHERENTE`), et `chantier_id` celui que la source impose —
le prévu du devis du WCT s'il le connaît, sinon, pour un employé, l'`intervention_id` (ce que l'app
envoie déjà : `materials.tsx` prend l'identifiant de la route pour les deux) :
`REJ-FORMULAIRE-MATERIAUX-CHANTIER-INCOHERENT` sinon. Détail : [`ROLES.md`](ROLES.md). Le contrôle
d'accès appartient au serveur, jamais au mobile.

**Aucune quantité ni aucun prix proposés par défaut** (mission item 3, DEFINITION-PRODUIT.md
§9.3 : « quantités réelles ajustables… **Aucun coût affiché** ») —
`src/ecrans/materials.ts::creerLigneVide` ne pré-remplit RIEN : l'employé compose chaque ligne à
la main (type parmi `prevu`/`non_prevu`/`retour`/`perte`/`bris`/`achat_terrain`, matériau,
quantité, unité) ; le serveur résout seul le coût unitaire
(`materiel.py::_dernier_cout_unitaire_connu`), jamais transmis par le mobile.

**Aucune liste « prévue » (M3/M6) pré-remplie — décision documentée, pas un oubli.** Le contrat
fixe donné pour cette tranche ne couvre QUE `m4_deposer_fichier`/`m4_etat_fichier` ; aucune route
de lecture des besoins estimés (`besoins_prevus`, lue par `m6_creer_po_brouillon` mais jamais
exposée à ce module) n'a été confirmée pour le mobile. L'employé saisit donc chaque ligne « prévu »
à la main plutôt que de choisir dans une liste pré-remplie — cohérent avec la mission (« l'employé
saisit, le serveur calcule »), mais moins guidé que ce que DEFINITION-PRODUIT.md §9.3 (« liste
prévue (M3/M6) ») laisse entendre. Une tranche future pourrait ajouter ce pré-remplissage une
fois une route de lecture confirmée.

**Saisie en texte, conversion à la validation** (`src/ecrans/materials.ts`) : une `LigneEnSaisie`
garde ses nombres en texte brut (`quantiteTexte`, virgule décimale fr-CA tolérée en plus du
point) plutôt qu'en `number | null` — un champ numérique React Native qui convertirait à chaque
frappe perdrait un « 12. » en cours de composition. `validerLigne`/`convertirLigne` (pures,
testées) n'agissent qu'à la soumission ; `achat_terrain` exige `photo_fournie` OU `recu_fourni`
(même règle que `REJ-ACHAT-TERRAIN-PREUVE-MANQUANTE`, `materiel.py`, lu — revérifiée côté client
pour éviter un aller-retour réseau voué à l'échec, l'autorité finale reste le serveur).

**Verdict serveur affiché TEL QUEL** (même discipline que `complete.tsx`) : `REJ-ACHAT-TERRAIN-PREUVE-MANQUANTE`,
`REJ-DECLARATION-DEJA-SOUMISE` (idempotence par `wct_id` — une seconde déclaration pour le même
WCT est refusée nommément), `REJ-COUT-UNITAIRE-INTROUVABLE`, `REJ-WCT-INCONNU` (T1.4-i), et tout autre code de
`validation.valider_wct`/`valider_formulaire_materiaux_utilises` (non lus ici, jamais devinés).
**Forme confirmée en lisant `outils.py` (`declarer_materiaux_utilises`) : le verdict
de refus de CET outil ne porte que `{"code": code}`, JAMAIS de `detail`** — contrairement au
patron `verdicts.construire_verdict` de M4 ; `src/m6/materiaux.ts` lit donc `detail`
défensivement (chaîne vide, jamais un plantage).

**Limite acceptée, même famille que `complete.tsx`/`punch.tsx` : pas de garde locale contre une
double soumission après un remontage de l'écran.** `soumis`/`enAttenteConfirmation` sont des
`useState` purement locaux, jamais persistés ; si l'employé quitte puis revient sur cet écran
après qu'un déclencheur d'arrière-plan a déjà fait accepter la déclaration, le bouton reste
actif et une nouvelle soumission est possible — SANS RISQUE : le serveur refuse nommément
(`REJ-DECLARATION-DEJA-SOUMISE`), affiché normalement comme un échec définitif. Non durci
davantage ici pour rester au périmètre de la mission (item 3).

Écran non testé en rendu (même limite que les autres écrans de cette tranche) :
`src/ecrans/materials.ts`, `src/m6/materiaux.ts` portent la logique, testée là.

## Consentement GPS (`consent.tsx`, POLITIQUE-geolocalisation §4, PLAN T1.4-k)

`app/(employee)/consent.tsx` : l'employé retire SON consentement à la géolocalisation depuis
l'app (POLITIQUE-geolocalisation.md §4 : « l'employé peut retirer son consentement via l'app
employé » ; §7 : droit de retrait à tout moment). Avant T1.4-k l'outil `m4_definir_consentement_gps`
n'était ouvert qu'à l'`admin` (il prenait un `technicien_id` de l'appelant : un employé aurait pu
retirer le consentement d'un collègue) ; il l'est maintenant à `employee`, à condition que
`technicien_id` soit sa propre personne (`REJ-IDENTITE-FOURNIE-DIFFERENTE` sinon, rien d'écrit).
Détail des contrôles : [`ROLES.md`](ROLES.md).

- **Type de mutation** `gps_consent_change` -> `m4_definir_consentement_gps`
  (`src/outbox/descripteurs.ts`), par la file sortante comme tout le reste : le retrait est en file
  AVANT tout réseau, rejoué avec la même clé d'idempotence après une coupure, jamais perdu (R12 §4).
- **Logique pure** : `src/m4/consentementGps.ts` (args exacts du schéma serveur,
  `creerMutationConsentementGps`, interprète du verdict), testée dans `consentementGps.test.ts`.
  `consent.tsx` ne fait que le câblage React, non testé en rendu (même limite que les autres écrans).
- **Ordre** : `chantierId = "0-consentement-gps"` se trie avant tout identifiant d'intervention
  (hexadécimal) dans `selectionnerProchainesEnvoyables` : un retrait en file part avant les
  pointages en attente. Sans cela, un pointage créé APRÈS le retrait pourrait arriver au serveur
  avant lui, et enregistrer une position que l'employé avait refusée (test dans
  `consentementGps.test.ts`).
- **Effet** : immédiat côté serveur. Dès le maillon écrit, `m4_pointer` ignore le fix fourni et bascule
  en mode manuel (`mode_pointage: "manuel"`). L'heure du retrait est celle de RÉCEPTION du serveur
  (T1.4-d), pas `horodatage`, que l'appareil envoie pour l'affichage seulement.
- **Verdict affiché tel quel** (`deriverEtatSynchroAffiche`, comme `punch.tsx`) : un retrait refusé
  (`REJ-IDENTITE-FOURNIE-DIFFERENTE`, `REJ-IDENTITE-APPAREIL-INVALIDE`…) se voit, il n'est jamais rendu
  comme un succès.

**Limites, dites plutôt que masquées :**
- seul le RETRAIT est proposé. Donner son consentement demande le formulaire d'accueil avec
  l'explication des finalités et la case à cocher (POLITIQUE §4), que rien ne présente encore ; le
  serveur accepte déjà `donne` pour la propre personne de l'employé, et `consentementGps.ts`
  construit les deux actions ;
- `technicien` n'est plus saisi (T1.4-c5) : c'est la personne que le serveur a confirmée pour l'appareil,
  que le serveur confronte de toute façon à l'identité authentifiée ;
- `preuve` reste `{fictif: true, reference}` (`consentement.py` refuse toute preuve réelle en mode
  ombre) et `version_politique` nomme la PROPOSITION P0-7, que Nathan n'a pas encore validée
  (`VERSION_POLITIQUE_GEOLOCALISATION`) : à remplacer quand la politique sera publiée ;
- aucun lien de navigation ne mène à cet écran (comme `punch.tsx` : l'accueil employé n'a pas encore de
  navigation) ; l'écran n'a pas été rendu dans ce bac à sable (ADR-0008 : pas d'appareil ni
  d'émulateur), seuls `tsc` et Jest l'ont vérifié ;
- l'employé ne peut pas encore consulter ses propres positions (§7, droit d'accès) :
  `m4_lire_position_gps` reste à l'admin.

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

## Nom d'un outil de l'app au moteur (PLAN T1.4-c6)

Un seul nom circule de l'app au moteur : le **nom nu** de l'outil OPSYS (`m4_pointer`). L'app
l'envoie, `roles.json` le compare, et le serveur du département le connaît sous ce nom. Le nom
matérialisé du moteur d'agents (`opsys_m4__m4_pointer`) n'entre nulle part.

### Constat (lecture du fork, base 1797f56)

L'hypothèse du plan (« le core matérialise `serveur__outil`, l'app envoie le nom nu ») était fausse
par le haut : le nom n'était pas le seul problème. Pour un appel d'appareil, aucun nom ne
fonctionnait.

1. **`/tools/invoke` ne voit aucun outil MCP.** `invokeGatewayTool` cherche l'outil dans
   `resolveGatewayScopedTools` (`core/src/gateway/tools-invoke-shared.ts:432-469`). Cette liste vient de
   `createOpenClawTools` (`tool-resolution.ts:312`) : outils du core, de plugins et de canaux
   (`openclaw-tools.ts:675`). Les outils d'un serveur `mcp.servers` ne sont matérialisés que pour un tour
   d'agent (`embedded-agent-runner/run/attempt-bundle-tools.ts:144`) ou une sonde de diagnostic. Nom nu ou
   nom matérialisé : même réponse, 404 « Tool not available » (`tools-invoke-shared.ts:475`).
2. **Pas d'agent, pas de session.** `sessionKey` vaut `main` par défaut (`tools-invoke-shared.ts:97`). Avec
   les dix agents de départements et aucun marqué par défaut, `resolveRequestedSessionAgentId` n'infère
   aucun propriétaire et répond 400 « Multiple agents are configured… Pass agentId »
   (`session-request-agent.ts:198-210`, `agent-roster.ts:124-141`), avant toute résolution d'outil. L'app
   n'envoie ni `agentId` ni `sessionKey`. Ce point est établi par la lecture ; le test
   `tools-invoke-http.opsys-roles.test.ts` (« does not need an owning agent ») le fait constater par la CI.
3. **Les `tools.deny` par agent ne touchent pas l'appareil.** Les globs `opsys_mN__*` de `openclaw.py`
   filtrent la liste core et plugins d'un agent (`tool-resolution.ts:257-262`, `:626`) ou les outils MCP d'un
   tour d'agent. Ils ne s'appliquent à aucun appel de `/tools/invoke` par jeton d'appareil, ni avant ni
   après ce correctif : la portée d'un appareil est son rôle, pas la politique d'un modèle.
4. **Les tests de T1.4-c1, c2 et c4 masquaient l'écart.** Ils remplaçaient `createOpenClawTools` ou
   `resolveGatewayScopedTools` par un faux outil, avec la mention « comme les vrais outils matérialisés »,
   fausse. Le `_meta` de T1.4-c1 n'était atteignable que par un tour d'agent.
5. **La forme de la réponse comptait aussi.** Le serveur du département répond un bloc texte qui contient
   l'enveloppe `{ok, resultat | erreur, rejoue}` (`src/opsys/serveur_mcp.py`), et l'app lit cette enveloppe
   (`mobile/src/m4/pointage.ts`). La projection d'un outil d'agent (`{content: [{type: "text"}], details}`)
   serait lue comme un succès sans accusé (lecture défensive de l'app) : tout rejet métier passerait
   inaperçu.

### Décision : le core appelle le serveur nommé par `roles.json`, sous le nom nu (option b)

- **Sécurité.** Aucune ambiguïté avec un outil natif : la porte d'appareil ne consulte jamais la liste
  d'outils du core. Le serveur est fixé par `roles.json`, jamais par la requête ; l'outil d'un autre
  serveur ne peut pas être appelé, même s'il porte le même nom.
- **Stabilité.** `buildSafeToolName` tronque à 64 caractères et suffixe (`-2`) en cas de collision
  (`agent-bundle-mcp-names.ts:81`) : un JSON généré d'avance ne peut pas s'y fier. Le nom nu est celui que
  le serveur du département publie (`tools/list`) ; il ne change que par un renommage d'outil, que
  `opsys verifier` et les tests d'épinglage voient.
- **Un seul contrôle, une seule exécution.** La portée est comparée au nom qui est ensuite appelé : c'est
  la même chaîne, lue dans le même fichier (option a écartée : elle aurait couplé l'app à la règle de
  nommage du moteur d'agents).

### Ce qui est livré

- `src/opsys/openclaw.py` : `serveurs_outils`. `roles.json` porte, à côté de `roles`, la clé `serveurs`
  (nom d'outil nu -> clé de `mcp.servers`), pour les seuls outils qu'un rôle peut appeler. Clé sœur
  additive : `roles` ne change pas.
- `core/src/gateway/opsys-device-roles.ts` : `authorizeOpsysDeviceTool` rend aussi `serveur`. Un outil dans
  la portée mais sans entrée `serveurs` est refusé (`server_unknown`) : le core ne devine rien.
- `core/src/agents/opsys-device-mcp-target.ts` (nouveau) : ouvre une session MCP privée qui ne contient
  QUE ce serveur (`includeServerNames`), vérifie que le serveur liste l'outil, l'appelle sous son nom brut
  avec le `_meta` ambiant, et rend l'enveloppe OPSYS telle quelle. La session est fermée après l'appel.
- `core/src/gateway/tools-invoke-shared.ts` : un appareil autorisé prend cette porte
  (`invokeOpsysDeviceTool`) au lieu de la liste d'outils. Le chemin des autres appelants (secret partagé,
  CLI, tableau de bord) est inchangé, y compris ses `tools.deny`.
- App : **aucun changement**. Les noms de `mobile/` étaient déjà les bons. Le test
  `tests/test_portees_appareil.py` épingle que chaque nom d'outil des sources de l'app est l'outil d'un
  département, permis à un rôle, avec son serveur dans `roles.json`.

### Règles de la porte d'appareil

| Règle | Pourquoi |
|---|---|
| Ni agent, ni session, ni liste d'outils. `agentId` et `sessionKey` du corps sont ignorés. | Avec plusieurs départements et aucun agent par défaut, ils feraient un 400 ; un appel d'appareil ne touche aucune session. |
| Le serveur vient de `roles.json`, jamais du corps. | Un appareil ne choisit pas le département. |
| Session MCP à ce seul serveur, vérification de l'outil dans son catalogue, appel sous le nom brut. | Un autre serveur n'est ni démarré ni joignable ; un outil absent du catalogue est un 404. |
| `gateway.tools.deny` s'applique, au nom nu et à la forme `serveur__outil` (globs `opsys_m4__*` compris). | Interrupteur de l'exploitant, déjà valable pour tout `/tools/invoke`. |
| Le hook `before_tool_call` s'exécute (nom nu). | Les politiques de plugin et les approbations gardent leur place. |
| Serveur injoignable : 500 (réessayable par l'app, même clé d'idempotence). Outil absent : 404. Refus : 403. | Règle de `src/protocole/classification.ts` : 408, 429 et 5xx se réessaient, les autres 4xx non. |
| Réponse illisible (pas une enveloppe OPSYS) : 500 générique, détail au journal du core. | Le core n'invente aucun verdict. |

### Preuve et limites

- Vitest (à faire juger par la CI, `tests-opsys`) : `tools-invoke-http.opsys-device-mcp.test.ts` (jeton
  d'appareil réel, fragments réels, porte réelle, transport MCP simulé), `opsys-device-mcp-target.test.ts`
  (deux vrais serveurs stdio, le second porte le même nom d'outil et ne démarre jamais),
  `opsys-device-roles.test.ts`, `tools-invoke-http.opsys-roles.test.ts`,
  `tools-invoke-http.device-token-auth.test.ts`.
- **Une session MCP par appel.** Simple et sans état partagé, mais chaque appel refait la poignée de main
  MCP. Mesuré en T1.5 (`tests/e2e/`, moteur réel sur un vrai uvicorn, SQLite, ordinateur de développement, porte
  refaite en Python d'après le fork) : chaque appel de l'app coûte quatre messages JSON-RPC (`initialize`,
  `notifications/initialized`, `tools/list`, `tools/call`) et six requêtes HTTP (les quatre, le flux serveur, la
  fermeture de session), soit 70 à 150 ms par appel dont l'essentiel est la session ; une journée d'employé
  (consentement, en route, arrivée, deux fichiers, départ, « Terminer », formulaire de matériaux) fait 9 appels et
  environ 0,8 à 1,1 s, plus la livraison du bus. Ce n'est pas la latence d'un core réel (TypeScript, réseau) : à
  refaire contre lui. Si elle gêne, réutiliser le gestionnaire de sessions (`acquireSessionMcpRuntime`).
- **Une réponse illisible se réessaie.** Un 500 est réessayé par l'app ; un défaut permanent du serveur
  (version incompatible) bouclerait jusqu'à la limite d'essais de la file sortante.
- **`action` du corps est ignoré** pour un appareil : les outils OPSYS n'ont pas de paramètre `action`.
- Prouvé à partir du moteur (T1.5, `tests/e2e/test_travaux_termines_appareil.py`) : chaque geste de l'employé et
  de l'admin passe par la vraie application HTTP MCP du moteur, avec le `_meta` que pose `buildOpsysMcpCallMeta`,
  et l'enveloppe est lue comme le fait `readOpsysEnvelope`. Le test refait la règle de la porte en Python d'après
  le code du fork : ce n'est pas le core.
- Non prouvé : le trajet contre un core réel (poignée de main, jeton d'appareil, `mcp.servers` du core, session MCP
  TypeScript), et PostgreSQL pour ces scénarios tant qu'aucun démon docker ne répond (ils sont sautés, pas verts).
  Le scénario qui le prouve est écrit (PLAN T1.5-b : `tests/e2e_core/`, job `e2e-core` de
  `.github/workflows/e2e-core.yml`) mais n'a pas encore tourné contre le core : il mesurera aussi la latence réelle.

## Idempotence et identité d'appareil de bout en bout (T1.4-b, T1.4-c1, T1.4-c2, T1.4-c4)

- **Idempotence, fait de bout en bout** (T1.4-b pour le socle, T1.4-c1 pour le core) :
  - `/tools/invoke` accepte `idempotencyKey`, `deviceId` et `deviceTimestamp` ;
  - le core les porte jusqu'au `tools/call` MCP, dans le `_meta` (`opsys/idempotencyKey`,
    `opsys/appareil`, `opsys/horodatageAppareil`) ;
  - le socle rejoue la réponse d'un renvoi, sans rien exécuter deux fois ;
  - détail dans [`IDEMPOTENCE.md`](IDEMPOTENCE.md) §7.
- **Rôles nommés et portée d'outil, fait** (T1.4-c2 + T1.4-c4, IDEMPOTENCE.md §7 bis) :
  - portée par outil (T1.4-j) : un outil n'est appelable par un rôle que s'il le déclare
    (`Outil.roles_appareil`, fermé par défaut, T3/N5 jamais) ; table et règle dans
    [`ROLES.md`](ROLES.md) ;
  - OPSYS génère deux fragments : `opsys/roles.json` (outils permis par rôle) et
    `opsys/appareils.json` (appareil → personne et rôle `admin`, `employee` ou `seller` ; jamais
    `client`, qui passe par un lien tokenisé),
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
    T1.4-c4 ferme, non traité ici. **Traité par T1.4-c5** : l'app obtient son rôle nommé par un appel dédié
    (« Identité de l'appareil »).

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

### Écran `approvals.tsx` (PLAN T1.4-f, étape 6)

Le propriétaire liste (`m9_lister_demandes_approbation`) et décide (`m9_decider_demande_approbation`) les
demandes d'approbation du socle. La logique est dans `src/ecrans/approvals.ts` et `src/approbations/`
(contrat, chargeur), testée ; `app/(admin)/approvals.tsx` n'est que le câblage React (lien depuis
`admin.tsx`). Règles côté serveur : [`ROLES.md`](ROLES.md), « Les deux outils d'approbation de l'app ».

- **Le serveur décide, l'écran n'offre que ce qu'il permet.** Aucune règle d'approbation n'est recalculée.
  Des boutons n'apparaissent que si le serveur dit `decidable`, sans raison de lecture seule, niveau N3 ou N4,
  personne propriétaire et arguments affichés (`evaluerOffre`) ; au moindre désaccord, lecture seule.
  N5 : « à décider à la console ». Un verdict du serveur est montré tel quel, code et détail.
- **Rien d'inventé.** Un élément illisible est compté (`illisibles`), jamais deviné ; une réponse de
  décision illisible n'est jamais un succès (rejet `reponse_illisible` : rouvrir la liste). Pas de cache de
  la liste : hors ligne, elle n'est pas montrée.
- **Une décision passe par la file sortante** (`approval_decision`, `chantierId = approbations`). Son id est la
  clé d'idempotence : un renvoi rend la réponse enregistrée sans rien refaire, et une autre décision pour la
  même demande reçoit `deja_decidee`. Une décision en file supprime les boutons de sa demande. Le payload est
  exactement `{demande_id, decision, motif?}` : ni personne ni rôle ni appareil.
- **Confirmation en deux temps** (Approuver puis Confirmer) : une décision ne se reprend pas.
- **Les attentes des départements (T1.5).** La file du propriétaire n'est pas que les demandes du socle : les
  départements déclarent aussi des attentes (`attentes()`, ADR-0009 §5) : une complétion en revue avec écart de
  matériaux critique (M4), une facture prête à envoyer, un chantier à réviser (M5). Elles étaient dans la console
  et dans le briefing du matin de M9, mais pas dans l'outil que cet écran lit : l'alerte « écart de 40 % »
  n'atteignait pas le téléphone de l'admin (mesuré par `tests/e2e/`). `m9_lister_demandes_approbation` les rend
  maintenant (`attentes`, `total_attentes`, `attentes_reste`, `attentes_illisibles`) ; l'écran les montre dans une
  section « À voir », **pour information, sans bouton** : ce que le département a écrit est affiché tel quel
  (rien n'est reclassé « critique » ou « urgent » côté app), avec le geste qu'il propose. Une attente illisible est
  comptée, un département dont les attentes n'ont pas pu être lues est nommé (son silence n'est pas « rien à
  signaler »), un moteur qui ne donne pas la clé `attentes` n'est pas lu « aucune » (`vueAttentes`).
- **« Voir plus » : les attentes se lisent par pages (T1.5-e).** Une page tient dans 1 500 caractères (trois
  attentes environ) ; au-delà d'elle, les suivantes n'étaient que comptées et l'admin ne les lisait pas sur son
  téléphone. La réponse dit maintenant `attentes_decalage` (le rang de la page) et `attentes_suivant` (le rang à
  demander, `null` quand rien ne suit) ; tant que `suivant` n'est pas `null`, la section montre un bouton « Voir
  plus (N autres attentes) » qui demande `decalage_attentes = suivant` (un rang, jamais une personne) et recolle la
  page à la suite (`chargerSuiteAttentes`, `fusionnerPageAttentes`, testés). Règles :
  - **Pas de cache**, comme la liste : hors ligne, la suite n'est pas inventée ; l'échec est dit (code et détail
    du serveur), les attentes déjà lues restent affichées et le bouton reste offert pour réessayer.
  - **Une page n'est recollée que si tout s'accorde** : c'est la page demandée (`decalage` = `suivant`), le total
    n'a pas changé, aucune de ses attentes n'est déjà affichée, et elle fait progresser la lecture. Sinon (une
    attente a été traitée ou est apparue entre-temps : le rang a glissé), la liste est **relue depuis le début** et
    l'écran le dit. Une liste qui aurait l'air complète sans l'être est pire qu'une relecture.
  - **Les demandes ne bougent pas** : le serveur les renvoie avec chaque page, l'écran garde celles de la
    première et ne recolle que les attentes.
  - Un moteur plus ancien, qui ne donne ni `attentes_decalage` ni `attentes_suivant`, se lit comme avant : pas de
    bouton, seulement le compte « N autres attentes non affichées : à voir à la console » (`suivant` vaut `null`).
    Un rang ou un suivant présent mais illisible rend toute la réponse illisible (`reponse_illisible`).
- **Limites.** Écran non testé en rendu (comme les autres ; la logique de « Voir plus » l'est) ; le trajet réel appareil → core → moteur reste à
  prouver contre un core réel (T1.4-c5) ; l'attente d'un département n'a pas de bouton : la revue d'une
  complétion se fait par `m4_resoudre_revue_completion` (outil N4, décidé ensuite par le propriétaire dans la
  liste des demandes), sans écran dédié.

## Ce qui n'est PAS encore fait

**Côté core (hors périmètre de ce dépôt mobile, lecture seule) :** la poignée de main WebSocket
d'appairage (`connect`/`hello-ok`) ne rend toujours que le rôle de transport générique du fork
(`"operator"`). L'écart avec les rôles nommés est comblé par T1.4-c5, autrement : l'app lit sa personne et
son rôle nommé par `GET /opsys/identite` (voir « Identité de l'appareil »), et
`GATEWAY_CLIENT_IDS.OPSYS_MOBILE` est câblé dans l'app, sans entrer dans la classe « app native » du core
(voir « Identifiant de client »). Ni l'un ni l'autre n'a tourné contre un core réel (T1.5).
T1.4-c4 refuse (403) tout `deviceId` de corps qui diffère de l'appareil authentifié par le jeton :
depuis T1.4-e, `punch.tsx` et `job/[id]/index.tsx` envoient l'identité d'appairage réelle
(`obtenirConfigurationAppel().appareilId`, le `deviceId` calculé par le client d'appairage), qui
coïncide par construction avec celle que le core authentifie ; la preuve contre un core réel reste
à faire (T1.5). **La route de réception du binaire (`m4_deposer_fichier`/`m4_etat_fichier`),
point bloquant principal laissé par T1.4-e, est livrée EN PARALLÈLE de T1.4-f par un autre
agent** — voir « Envoi de fichiers par blocs » ci-dessus pour le CONTRAT FIXE que le mobile
implémente contre elle. **Non vérifié : la conformité RÉELLE entre les deux côtés.** Le mobile
n'a lu ni exécuté aucun code serveur pour ces deux outils (absents de `departments/`/`core/` au
moment d'écrire cette tranche) ; le contrat a été donné par la mission, jamais lu dans le code —
`m4_completer_intervention` exigera des références `fichier:sha256:<hex>` réellement déposées et
complètes pour `photos_apres`/`signature`, avec un nouveau `REJ-PREUVE-FICHIER-INTROUVABLE`
annoncé par la mission mais absent de `preuves.py` au moment de lire ce fichier (avant la
livraison parallèle) — la préparation à ce refus est donc l'affichage GÉNÉRIQUE du verdict
(`complete.verdict.echecPermanentAvecVerdict`, jamais un texte codé en dur pour ce code précis),
pas une vérification de forme spécifique. Tout écart entre le contrat donné et la route
réellement livrée (nom de champ, forme du `verdict`, taille de bloc, etc.) ne sera découvert qu'au
premier test de bout en bout contre le core/moteur réels (T1.5, R12 §5 étape 7 E2E Maestro) — même
prudence que documentée pour `m4_pointer` (« lecture défensive, jamais vérifiée contre un core
réel dans ce bac à sable »). Aucune route serveur n'expose de date/fenêtre de cédule ni de
technicien assigné par intervention à `m4_lister_interventions` (détaillé dans « Chantiers du
jour » ci-dessus) ; aucune route de lecture des besoins matériaux estimés (`besoins_prevus`)
n'est exposée au mobile pour pré-remplir `materials.tsx` (détaillé dans « Écran `materials.tsx` »
ci-dessus).

**Côté mobile :** pas de lecture QR (code saisi seulement, voir « Appairage » — `expo-camera` est
installé depuis T1.4-e mais seulement pour la capture photo, aucun scan QR câblé) ; pas de
capture GPS réelle (Loi 25 non confirmée, `expo-location` non installé), ni de fenêtre de
travail/référentiel de villes fournis par le serveur au mobile — `punch.tsx`/`job/[id]/index.tsx`
envoient un contexte provisoire clairement documenté pour ces champs
(`src/m4/contextePointageProvisoire.ts`) ; pas de persistance du dernier verdict serveur dans la
ligne `outbox` (limite documentée dans « Écran `punch.tsx` », même limite acceptée pour
`complete.tsx`/`materials.tsx`, voir leurs sections) ; `identifierMutationsAReprendre`
n'a encore aucun appelant réel (la reprise au démarrage passe directement par
`selectionnerProchainesEnvoyables`, qui inclut déjà les `envoi` — cette fonction reste utile pour
une future traçabilité/journalisation dédiée, R12 §4 P3) ; pas de notifications push ; pas de
rotation/révocation de jeton d'appareil COMMANDÉE par l'app (`device.token.rotate/revoke`, R12 §1.3 —
l'app n'appelle jamais ces méthodes, seulement `connect`) ; elle SUBIT une révocation depuis T1.4-l (arrêt
de la vidange, écran d'identité, voir « La file suit le jeton et la personne ») ; pas de tests E2E Maestro ; pas de
build EAS ni de publication store (frontière humaine T3, R12 §3). **Nouveau depuis T1.4-f :**
`complete.tsx` ne capture aucun des quatre champs client optionnels de `m4_completer_intervention`
(`photos`, `description_factuelle`, `consentement_marketing`, `client_satisfait` — faits du
client, Loi 25, T1.2-f) faute d'écran dédié (rattaché à M7, DEFINITION-PRODUIT.md §9.3, hors
ordre de livraison R12 §5 pour T1) ; `materials.tsx` ne pré-remplit aucune ligne « prévue »
depuis M3/M6 (aucune route de lecture confirmée pour le mobile, voir plus haut) — l'employé
compose chaque ligne à la main ; l'envoi de fichiers ne démarre qu'à l'arrivée sur `complete.tsx`
(montage + « Terminer »), pas dès la capture dans `photos.tsx`/`signature.tsx` (décision
documentée, voir « Envoi de fichiers par blocs » — écrans T1.4-e volontairement inchangés).

**Nouveau depuis T1.4-f, hors périmètre de cette tranche :** l'écran `(admin)/approvals` (R12 §5
étape 6) est livré depuis (voir « Écran `approvals.tsx` »), mais la boucle « Travaux terminés » n'est
prouvée de bout en bout qu'avec l'E2E (P6, « la tranche n'est pas faite tant que l'accusé de
réception côté propriétaire ne ferme pas la boucle », R12 §5) : l'alerte d'écart matériaux
(`completed_pending_review`) est un état de M4 que `m4_resoudre_revue_completion` (N4) traite, pas
encore une carte de cet écran ; pas de tests E2E Maestro contre
un core/moteur réels (R12 §5 étape 7 — le scénario exact, « travaux terminés normaux ; écart de
40 % -> `completed_pending_review` + alerte mobile admin », PLAN.md T1.5, reste à exécuter, voir
la remarque ci-dessus sur la conformité non vérifiée du contrat fichiers) ; `technicien_id` n'est
plus saisi sur `punch.tsx`/`job/[id]/index.tsx`/`consent.tsx` depuis T1.4-c5 : c'est la personne que le
serveur a confirmée pour l'appareil (« Identité de l'appareil ») ; depuis T1.4-k, le serveur exige que ce
soit l'identifiant de la personne authentifiée ; pas de suppression/reprise de photo une fois
capturée (`DepotOutbox` n'expose aucune méthode de suppression, volontairement non étendue ici
pour ne pas risquer une régression sur `punch.tsx` déjà en production — une photo capturée par
erreur ne peut être « annulée » qu'en ne la déposant jamais, ce que rien n'empêche aujourd'hui) ;
pas de rafraîchissement automatique de `today.tsx` au retour au premier plan/réseau (seuls
`punch.tsx`/le vidangeur ont ces déclencheurs, R12 §4 les prévoyant spécifiquement pour la file
sortante, pas pour une liste en lecture — un bouton « Rafraîchir » manuel couvre cette tranche) ;
aucun catalogue serveur de checklist par service (décision documentée, voir « Checklist » — pas
un gap à combler mais un choix de conception assumé tant qu'aucune donnée produit n'existe pour
le remplacer) ; pas de purge post-confirmation des fichiers locaux une fois un envoi `complet`
(R12 §4, « le fichier local est purgé après un court délai de grâce post-confirmation » — les
photos/signatures restent indéfiniment dans `Paths.document/opsys-photos|opsys-signatures/`
même après un envoi réussi, même limite que celle documentée par T1.4-e avant que la route
d'envoi n'existe, non résolue par cette tranche faute de temps/périmètre restant).
