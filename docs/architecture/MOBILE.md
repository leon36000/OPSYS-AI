# Application mobile OPSYS

> Réécrit par PLAN T1.4-a (2026-09-28) : remplace la version périmée qui prévoyait un fork des
> apps natives OpenClaw (« phase 2 »). Décision en vigueur : **nouvelle app Expo/React Native,
> réutilisant le protocole et l'appairage d'OpenClaw, pas son code d'interface** — voir
> [ADR-0008](../decisions/ADR-0008-fork-openclaw-opsys-core.md) et le détail technique complet
> dans [`docs/research/R12-app-mobile.md`](../research/R12-app-mobile.md) (pile §3, synchro §4,
> écrans §5, sécurité §6). Ce fichier résume ; R12 fait foi sur le détail et les preuves.

## État actuel : premier écran métier de bout en bout (T1.4-d)

`mobile/` contenait, jusqu'à T1.4-a, un **squelette** (projet, routage par rôle, file sortante
et client protocole en logique pure) sans écran métier. **T1.4-d livre `punch.tsx` (M4.4) et le
« vidangeur »** qui relie enfin `src/outbox` à `src/protocole` (R12 §5 étape 2 : « la plus
petite tranche verticale qui exerce toute la mécanique de file/synchro ») — voir « Vidangeur »
et « Écran `punch.tsx` » ci-dessous. Étapes suivantes (R12 §5, ordre de livraison) : T1.4-c
(protocole d'appairage — encore À FAIRE, voir plus bas), `today.tsx`/`job/[id]`,
`checklist`/`photos`/`signature`, `complete`→`materials` (M6.10), `(admin)/approvals`, E2E
Maestro. T1.4-b (idempotence côté socle) est fait côté serveur — voir
[`IDEMPOTENCE.md`](IDEMPOTENCE.md) — mais son branchement CÔTÉ CORE (`_meta` MCP) reste à faire
en T1.4-c (détail dans la section « `/tools/invoke` » ci-dessous).

## Pile (R12 §3 — versions et licences vérifiées)

Expo SDK 57 (`expo` 57.0.25) + Expo Router 57.0.23 + TypeScript strict, React Native 0.86.3.
Stockage local : `expo-sqlite` (moteur libSQL), désormais réellement câblé par
`src/outbox/service.ts` (voir « Vidangeur » ci-dessous). i18n : i18next + react-i18next +
expo-localization. Génération d'UUID côté appareil : `expo-crypto`. Détection réseau (T1.4-d) :
`@react-native-community/netinfo` 12.0.1, MIT (licence vérifiée dans son fichier `LICENSE`
installé — inscription dans
[`docs/research/INGREDIENTS.md`](../research/INGREDIENTS.md) **en suspens** : cette tranche
n'a pas le droit de modifier ce fichier, voir rapport final de T1.4-d). Toutes MIT, sauf
TypeScript (Apache-2.0) — les deux licences sont acceptées (AGENTS.md). Détail brique par
brique, licences et écarts de version : `docs/research/INGREDIENTS.md` (section « Mobile ») et
le rapport final de PLAN T1.4-a.

Volontairement **pas encore installés** à ce stade (aucun écran n'en a encore besoin) : caméra,
notifications, signature, formulaires (react-hook-form/zod), TanStack Query, `expo-secure-store`,
`expo-location`/`expo-task-manager` (GPS — voir « Écran `punch.tsx` » : la lecture Loi 25
« fenêtre bornée » de R12 §6 n'est pas encore confirmée par Nathan/juriste),
`@testing-library/react-native` (absent de la pile installée — `punch.tsx` est donc testé via sa
logique extraite en fonctions pures, `src/ecrans/punch.ts`, jamais en rendu). Ils entrent avec
les tranches qui en ont besoin, jamais par anticipation.

## Rôles et routage (`src/roles/`)

Quatre profils (DEFINITION-PRODUIT §9) = quatre groupes Expo Router : `(employee)`, `(seller)`,
`(admin)`, `(client)`. `src/roles/garde.ts` exporte `evaluerGarde(session, groupeCible)`, une
fonction **pure** : rôle du jeton d'appareil → groupe autorisé (mappage un-à-un, R12 §6), fail-
closed (session absente, rôle inconnu et rôle valide mais différent du groupe visé refusent
tous les trois, vers `/pairing`). Chaque `_layout.tsx` de groupe appelle cette garde avant de
rendre quoi que ce soit — un jeton `employee` n'atteint donc jamais `(admin)`, y compris par URL
directe. `src/roles/contexte.tsx` porte l'état de session en React Context ; il démarre toujours
`{ presente: false }` (voir Appairage ci-dessous). 227 tests Jest couvrent la garde (matrice rôle
× groupe complète, session absente, rôles inconnus), la file sortante, le vidangeur (faux
transport), le contrat `m4_pointer`, les déclencheurs et la logique de `punch.tsx`.

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
  encore au mobile (pas de `today.tsx`, pas d'appairage T1.4-c) ;
- `technicien_id`/`intervention_id` NE sont PAS dans ce contexte provisoire : ce sont les deux
  seuls champs que l'employé saisit lui-même à l'écran (aucune session appairée pour les
  connaître à sa place) ;
- `appareil_id`/`deviceId` : identifiant généré une fois par processus (`expo-crypto`), jamais
  persisté — regénéré à chaque démarrage tant que `expo-secure-store` et l'appairage (T1.4-c) ne
  fournissent pas l'identité scellée par le serveur. Sans persistance, l'idempotence de bout en
  bout `(appareil, idempotencyKey)` n'est pas garantie d'une session à l'autre — sans
  conséquence tant que T1.4-c n'a pas câblé la lecture de ces champs côté core (section
  précédente).

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
[`IDEMPOTENCE.md`](IDEMPOTENCE.md) §7 documente pour T1.4-c : mêmes noms, même emplacement (corps
de `/tools/invoke`, à côté de `idempotencyKey`) que le changement recommandé pour
`ToolsInvokeInput` (`tools-invoke-shared.ts`) — choisis pour qu'aucune réécriture côté mobile ne
soit nécessaire quand T1.4-c câblera leur lecture vers `_meta` MCP
(`opsys/appareil`/`opsys/horodatageAppareil`). **Le core ne les lit pas encore** : envoyés dès
maintenant, ignorés jusqu'à T1.4-c.

## Idempotence côté socle — fait (PLAN T1.4-b), branchement core à faire (T1.4-c)

`idempotencyKey` protège contre le double envoi côté client (reprise après crash, réseau
instable) ; il ne vaut que si le moteur métier Python l'applique en vérité. **C'est fait** côté
socle (`_meta` MCP `opsys/idempotencyKey`/`opsys/appareil`/`opsys/horodatageAppareil`, table
`mutations_appliquees`, clé `(appareil, cle_idempotence)`, avant d'agir — détail complet,
schéma, concurrence SQLite/PostgreSQL : [`IDEMPOTENCE.md`](IDEMPOTENCE.md)). **Ce qui manque
encore** (IDEMPOTENCE.md §7, lu, jamais modifié ici) : le core (`core/src/gateway/tools-invoke-
shared.ts`, `agent-bundle-mcp-runtime.ts`) ne construit pas encore ce `_meta` à partir du corps
de `/tools/invoke` — `idempotencyKey` n'y sert aujourd'hui qu'à un `toolCallId` local de
déduplication, et `deviceId`/`deviceTimestamp` n'existent pas encore dans `ToolsInvokeInput`. Tant
que ce câblage (T1.4-c) n'est pas fait, un renvoi après une réponse perdue **duplique** l'effet
côté serveur — connu, documenté, sans solution côté mobile (la file sortante fait déjà tout ce
qui lui revient : même id, même clé, à chaque renvoi).

## Sécurité

Jeton d'appareil et clé d'appairage : `expo-secure-store` (Keychain iOS / Keystore Android),
jamais en base SQLite ni `AsyncStorage` (R12 §6) — **pas encore câblé** : rien ne stocke de
jeton tant que l'appairage (T1.4-c) n'existe pas. Conséquence directe pour T1.4-d :
`src/protocole/configuration.ts` (`obtenirConfigurationAppel`) renvoie TOUJOURS `null` (même
philosophie que `src/roles/contexte.tsx` — « on n'invente aucun faux état apparié ») ; sans
configuration, `src/outbox/service.ts` ne construit même pas de vidangeur réel : les mutations
créées par `punch.tsx` s'accumulent en file, en sécurité, sans jamais tenter un appel réseau tant
que T1.4-c n'a pas fourni une vraie source (`urlBase`, `jeton`, `appareilId`). Vues par rôle
appliquées deux fois (serveur ET app, R12 §6) ; ici, uniquement la moitié app (`evaluerGarde`)
est livrée. Consentement GPS, photos/signature : politiques Loi 25 citées par R12 §6 — `punch.tsx`
ne capte AUCUNE géolocalisation réelle (voir « Écran `punch.tsx` »).

## Ce qui n'est PAS encore fait

Pas de protocole d'appairage réel (T1.4-c) ; pas de stockage sécurisé de jeton
(`expo-secure-store` non installé) ; pas de source réelle de `urlBase`/`jeton`/`appareilId`
(`src/protocole/configuration.ts` renvoie `null`) — tant que ça dure, le vidangeur n'est jamais
construit en production et la file s'accumule sans se vider ; pas de branchement `_meta`
MCP côté core (T1.4-c, IDEMPOTENCE.md §7) — un renvoi duplique encore l'effet serveur ; pas de
capture GPS réelle (Loi 25 non confirmée, `expo-location` non installé), ni de fenêtre de
travail/référentiel de villes fournis par le serveur au mobile — `punch.tsx` envoie un contexte
provisoire clairement documenté pour ces champs (`src/m4/contextePointageProvisoire.ts`) ; pas de
persistance du dernier verdict serveur dans la ligne `outbox` (limite documentée dans « Écran
`punch.tsx` ») ; pas d'écran métier au-delà de `punch.tsx` (cédule, checklist, matériaux,
approbations, etc.) ; `identifierMutationsAReprendre` n'a encore aucun appelant réel (la reprise
au démarrage passe directement par `selectionnerProchainesEnvoyables`, qui inclut déjà les
`envoi` — cette fonction reste utile pour une future traçabilité/journalisation dédiée, R12 §4
P3) ; pas de caméra, notifications push, signature ; pas de tests E2E Maestro ; pas de build EAS
ni de publication store (frontière humaine T3, R12 §3) ; inscription de
`@react-native-community/netinfo` dans `docs/research/INGREDIENTS.md` en suspens (licence MIT
vérifiée dans cette tranche, mais ce fichier est hors du périmètre autorisé de T1.4-d — voir le
rapport final).
