# R12 — Pile de l'app mobile OPSYS-AI et stratégie vis-à-vis des apps OpenClaw

**Mandat.** [ADR-0008](../decisions/ADR-0008-fork-openclaw-opsys-core.md) (Accepté, 2026-09-28) tranche déjà le
point 9 de la [définition produit §13](../produit/DEFINITION-PRODUIT.md) : *« App mobile : React Native/Expo,
nouvelle app (...) On réutilise leur protocole et leur appairage, pas leur code d'interface. Détail de la pile :
R12. »* Ce rapport apporte cette preuve (comparaison documentée, §2) et le détail technique demandé par la
mission (§3-§6). Il ne rouvre pas la décision de principe ; il la vérifie et l'outille.

**Alerte périmètre.** [`docs/architecture/MOBILE.md`](../architecture/MOBILE.md) (rédigé avant ADR-0008)
recommande encore, en « phase 2 », un **fork des apps natives OpenClaw**. Ce rapport recommande l'inverse (§1,
§2) et confirme la décision de l'ADR. `MOBILE.md` est donc **périmé sur ce point** et doit être réécrit — hors
périmètre de ce fichier (mission : ne modifier aucun autre fichier que celui-ci).

**Sources.** Clone superficiel local `openclaw/openclaw` (`scratchpad/clones/openclaw`, HEAD `2d39f2f7`,
2026-09-27 ; `package.json` `"version": "2026.9.6"` — cohérent avec `core/UPSTREAM.md` et ADR-0008) : code de
`apps/ios`, `apps/android`, `apps/shared`, `packages/gateway-client`, `packages/gateway-protocol`, et une
quarantaine de pages de `docs/gateway/` et `docs/nodes/`. Registre npm (licences et versions vérifiées le
2026-09-26/27). Pages officielles Expo, PowerSync, ElectricSQL, Maestro, Hot Updater. Côté OPSYS :
[DEFINITION-PRODUIT §5/§6/§9/§13](../produit/DEFINITION-PRODUIT.md), `ARCHITECTURE.md`, `ADR-0008`,
[`docs/programme/PLAN.md`](../programme/PLAN.md),
[`POLITIQUE-geolocalisation.md`](../compliance/politiques/POLITIQUE-geolocalisation.md). Détail : `PREUVE:`.

---

## 1. Les apps OpenClaw : ce qu'elles font, ce qui se réutilise

### 1.1 Fonctions (lecture du code, pas seulement du README)

`apps/ios/Sources/` et `apps/android/app/src/` exposent le même ensemble fonctionnel dans les deux langages :
Chat (flux, modèle, agent, sessions), Voice/Talk (conversation vocale en direct, mot d'éveil), Camera, Location,
Push, Node (mode compagnon), Onboarding, Device/Health/Motion (capteurs), Contacts/Calendar/Reminders (données
personnelles), Screen (capture/contrôle d'écran), LiveActivity (iOS), Settings, Web. `apps/shared/OpenClawKit`
(Swift, partagé iOS/macOS/watchOS) porte `OpenClawProtocol`, `OpenClawChatUI`, `OpenClawNativeState` ;
`apps/android/wear-shared` fait l'équivalent Kotlin pour Wear OS. **C'est un client de conversation avec un
agent IA distant, dont le téléphone est un périphérique (« node ») qui expose ses capteurs** — pas une app
métier à écrans de formulaires.

Mesuré directement : `apps/ios` + `apps/shared` = **266 428 lignes Swift** ; `apps/android` = **258 551 lignes
Kotlin**, soit **≈ 525 000 lignes** pour les deux plateformes mobiles seules (macOS/Linux/Wear ajoutent
211 825 lignes de plus, ce qui explique le chiffre de ~570 000 lignes du brief si l'on inclut des compagnons
non mobiles).

### 1.2 Protocole avec le gateway

Wire v4, trames JSON sur WebSocket, multiplexé avec une API HTTP sur le même port. Deux paquets TypeScript
publiés (`packages/gateway-protocol`, `packages/gateway-client`, MIT tous les deux, alignés sur le train de
release OpenClaw) portent tout le contrat :

- `@openclaw/gateway-protocol` : schémas TypeBox, validateurs, constantes de version, garde-fous de trame sans
  dépendance lourde (`frame-guards`, `client-info`).
- `@openclaw/gateway-client` : machine à états de connexion (authentification par défi, corrélation des
  requêtes, timeouts, reconnexion à recul exponentiel 1-30 s, gestion du jeton d'appareil). **Point clé** : un
  point d'entrée `@openclaw/gateway-client/browser`, **sans dépendance Node ni `ws`**, où l'hôte fournit son
  propre WebSocket et ses propres callbacks de signature — taillé pour un client web ou React Native, pas pour
  un « node » natif.
- **`POST /tools/invoke`** (HTTP simple, sans tour d'agent complet) : appelle un outil nommé avec des arguments
  JSON, jeton porteur, `idempotencyKey` optionnel, réponse `{ok, result}`. C'est la porte déterministe (P7,
  ADR-0008 §2) par laquelle l'app mobile doit appeler `m4_pointer_entree`, `m6_soumettre_materiaux_utilises`,
  etc. — jamais par un tour de modèle.

### 1.3 Appairage

`connect` → `connect.challenge` (nonce serveur) → charge signée v3 (`buildDeviceAuthPayloadV3`, lie
appareil/client/rôle/portées/nonce/plateforme) → `hello-ok` avec jeton d'appareil scellé par rôle (`operator`
ou `node`) et portées. Admission : QR (`oc-pair://<code>`, jeton d'amorçage à usage unique, 10 min) ou code
CLI, approuvée en **deux temps** par le propriétaire (l'appareil, puis la surface de commandes qu'il déclare)
— sauf auto-approbation locale/SSH/CIDR, non pertinente pour un téléphone sur Internet. Jetons
rotatifs/révocables (`device.token.rotate/revoke`). L'algorithme de signature exact (probablement une courbe
elliptique — Ed25519 ou P-256, non confirmé dans la documentation lue) reste **à vérifier dans le code du
fork** avant d'écrire le client mobile.

### 1.4 Notifications, voix, caméra

Push : relais APNs chiffré (iOS, `Sources/Push/*`) et FCM (Android) — mécanique standard, aucune raison de la
recopier plutôt que d'utiliser `expo-notifications` (§3). Voix : mode Talk (conversation vocale en direct) et
mot d'éveil — pertinents pour un futur compagnon conversationnel, **pas requis par la définition produit §9
pour la V1** (aucun des 4 profils n'y demande de dicter au téléphone ; la voix produit reste côté serveur,
M1/Twilio). Caméra (commande `camera.snap`/`camera.clip`) : bridée en largeur, qualité et durée (`--max-width`,
`--quality`, `--delay-ms`, 300 s max, premier plan requis) — **bon patron à copier** pour la prise de photo
terrain (§4). Localisation (`location.get`) : sélecteur `off/whileUsing/always` + bascule « précise » séparée,
désactivé par défaut — **bon patron UX** pour l'écran de consentement GPS d'OPSYS (§6), même si OPSYS implémente
sa propre capture (`expo-location`, pas `node.invoke`).

### 1.5 Réutilisable / non réutilisable

| Réutilisable | Non réutilisable |
|---|---|
| `packages/gateway-protocol` + `packages/gateway-client` (entrée `/browser`), vendorisés en TypeScript — même logique que le fork dur du core (ADR-0008), pas une dépendance npm sur l'amont qui divergera | Le code d'interface `apps/ios` (266 428 lignes Swift) et `apps/android` (258 551 lignes Kotlin) : deux bases, deux langages absents du reste de la pile OPSYS (Python + TypeScript) |
| Le concept et l'UX d'appairage (QR, amorçage court, double approbation, jetons scellés par rôle) | Le paradigme d'app : compagnon de conversation IA (chat, Talk, mot d'éveil, contrôle d'ordinateur, panneau de widgets) — aucun écran de formulaire, de checklist ni de file de mutations hors ligne pour des entités métier |
| `POST /tools/invoke` comme porte déterministe (P7) pour les écritures métier | La synchronisation : ces apps mettent en cache une session de discussion, pas une file de mutations avec idempotence et résolution de conflits |
| Les paramètres de bridage caméra et le sélecteur GPS comme patrons de conception | Le rôle « node » (périphérique exposant ses capteurs à un agent distant) comme modèle principal des écrans terrain — utile en complément optionnel, pas comme fondation |

---

## 2. Comparaison des piles

| Critère (§9, mission) | React Native/Expo | Fork natif OpenClaw | Flutter | PWA |
|---|---|---|---|---|
| 4 profils, écrans dédiés | Routes par groupe (Expo Router) — spec §9.8 déjà écrite pour ça | Tout à construire par-dessus un chat, deux fois | Idem RN, écrans à construire | Idem, mais limité par les lignes suivantes |
| Hors ligne (file, synchro, conflits) | Écosystème mûr (SQLite + TanStack Query), patron libre | Cache de session de chat seulement, rien d'équivalent | Écosystème mûr (sqflite/drift) | IndexedDB viable en principe, bloqué par les lignes suivantes |
| GPS arrière-plan borné aux heures | `expo-location` + `expo-task-manager`, fenêtre bornée | Existe (`location.get`), mais lié au rôle node/agent | Plugins matures | **Pas de localisation arrière-plan fiable sur Safari/iOS PWA** |
| Photos arrière-plan | `expo-camera` + `expo-file-system`, envoi différé | Existe, bridé (§1.4), lié au node | Plugins matures | Capture possible, pas de file d'envoi arrière-plan fiable |
| Signature | `react-native-signature-canvas` | À construire | Packages disponibles | Canvas HTML viable |
| Scan code-barres/QR | `expo-camera` (intégré) | Existe côté node | Packages disponibles | `getUserMedia`, plus lent, moins fiable en entrepôt |
| Push fiable (surtout iOS, approbations T3) | `expo-notifications` (APNs/FCM) | Existe (§1.4) | Plugins matures | **Web Push iOS Safari récent et limité** — risque direct pour « le propriétaire approuve tout depuis le téléphone » |
| Voix | Non requis V1 ; ajoutable via le protocole partagé | Déjà présent (Talk), hors périmètre V1 | À construire | Limité |
| Productivité (un seul code) | Un code TypeScript, iOS+Android | Deux codes (Swift, Kotlin) en permanence | Un code Dart | Un code, mais web |
| Maintenance / langage partagé avec OPSYS | TypeScript = langage du Core (ADR-0008) et de la Control UI | Swift+Kotlin : aucun recouvrement avec Python/TypeScript | Dart : troisième langage, aucun recouvrement | JS/TS, recouvrement total |
| Réutilisation protocole (ADR-0008) | Directe (`gateway-client` est en TypeScript) | Native (même code) mais UI à jeter | À réimplémenter en Dart | Directe (même famille JS/TS) |

**Verdicts.**

- **Fork natif : rejeté.** Le protocole et l'appairage se réutilisent (§1.5) ; l'interface non — deux bases de
  ~525 000 lignes dans des langages absents du reste d'OPSYS, pour un paradigme (chat/périphérique) sans
  équivalent des écrans exigés (checklist, formulaire de matériaux, file de mutations). Les construire
  par-dessus reviendrait à les écrire deux fois, en plus d'hériter de fonctions sans rapport (Talk, mot
  d'éveil, contrôle d'ordinateur, panneau de widgets) à maintenir et à corriger de sécurité indéfiniment.
- **Flutter : rejeté malgré des qualités réelles.** Aussi mono-code, écosystème hors-ligne mûr. Mais Dart est
  une **troisième langue** sans aucun recouvrement avec Python (départements) ou TypeScript (Core, Control UI,
  `gateway-client`) — cela casse la réutilisation du protocole voulue par ADR-0008 (il faudrait réimplémenter
  l'authentification par défi en Dart) et alourdit la maintenance d'une petite équipe.
- **PWA : rejetée, échec de deux exigences non négociables du §9.2.** Pas de localisation d'arrière-plan fiable
  sur Safari/iOS, Web Push historiquement limité sur iOS : ce ne sont pas des compromis mineurs, ils menacent
  directement « GPS arrière-plan limité aux heures de travail » et « le propriétaire approuve tout depuis le
  téléphone ».
- **React Native/Expo : retenu.** Seule option qui coche toutes les exigences dures, partage son langage avec
  le reste d'OPSYS, réutilise directement le protocole TypeScript d'OpenClaw, et correspond à la nomenclature
  de routes déjà écrite dans la définition produit (§9.8, Expo Router). Confirme ADR-0008.

---

## 3. Pile retenue (versions et licences vérifiées, 2026-09-26/27)

| Brique | Rôle | Version | Licence | Note |
|---|---|---|---|---|
| **expo** | SDK/runtime | 57.0.25 (React Native 0.86) | MIT | publié 2026-09-24 ; Nouvelle Architecture par défaut |
| **expo-router** | navigation par fichiers | 57.0.23 | MIT | numérotée sur le SDK depuis la 55 ; correspond à §9.8 |
| **expo-sqlite** | stockage local — défaut | 57.0.3 | MIT | moteur libSQL, fonctionne en Expo Go |
| **@op-engineering/op-sqlite** | stockage local — option chiffrée | 18.2.5 | MIT | SQLCipher en option ; nécessite un dev client custom |
| **Outbox maison** (SQLite + TanStack Query) | synchro hors ligne | code OPSYS | — | retenu plutôt que WatermelonDB/PowerSync/Electric — voir §4 et note ci-dessous |
| @nozbe/watermelondb *(évalué, non retenu V1)* | — | 0.28.0 | MIT | mûr, mais dernière stable avril 2025 (cadence ralentie) ; piste si la lecture hors-ligne se complexifie (catalogue M6 complet, pipeline vendeur complet) |
| @powersync/react-native *(évalué, rejeté)* | — | 2.3.0 (client) | **Apache-2.0** (client) | le **service** PowerSync auto-hébergé est **FSL** (source-available, hors liste acceptée AGENTS.md) ; PowerSync Cloud = SaaS propriétaire payant récurrent. Client seul licite mais inutilisable sans l'un des deux → écarté |
| electric-sql/electric *(évalué, rejeté)* | — | — | Apache-2.0 | licence correcte, mais dépôt affiché **« Beta »**, virage 2026 vers PGlite/TanStack DB (navigateur/Node) sans démonstration de maturité sur SQLite embarqué React Native → écarté pour l'instant, pas pour la licence |
| **@tanstack/react-query** | cache + cycle de vie des mutations | 5.104.0 | MIT | |
| **react-hook-form** + **@hookform/resolvers** | formulaires | 7.89.0 / 5.9.1 | MIT | |
| **zod** | validation de schéma | 4.6.5 | MIT | rejette côté client avant d'atteindre la file sortante |
| **i18next** + **react-i18next** | i18n | 26.4.2 / 17.0.15 | MIT | fr-CA par défaut, en-CA en réserve |
| **expo-localization** | détection langue de l'appareil | 57.0.2 | MIT | |
| **expo-notifications** | push | 57.0.21 | MIT | service Expo Push devant FCM HTTP v1 (Android) et APNs (iOS) |
| **expo-location** + **expo-task-manager** | GPS | 57.0.20 / 57.0.20 | MIT | fixe ponctuel au punch + fenêtre bornée « en route » (§4, §6) |
| **expo-camera** | photo + scan QR/code-barres | 57.0.5 | MIT | `CameraView` couvre les deux besoins sans module natif tiers |
| react-native-vision-camera *(option future, non retenu V1)* | — | 5.2.3 | MIT | aucun besoin actuel ne le justifie ; dev client requis |
| **react-native-signature-canvas** | signature client | 5.1.1 | MIT | rendu WebView |
| **expo-secure-store** | jetons, clé d'appareil | 57.0.4 | MIT | Keychain (iOS) / Keystore (Android) |
| **expo-file-system** | photos en attente d'envoi | 57.0.7 | MIT | |
| **@react-native-community/netinfo** | détection réseau | 12.0.1 | MIT | déclenche la purge de la file sortante à la reconnexion |
| @noble/curves *(piste)* | signature de l'appairage | 2.4.0 | MIT | implémentation JS auditée (Ed25519/P-256/secp256k1…) ; à confirmer selon l'algorithme exact retenu par le fork (§1.3) |
| **Jest** | tests unitaires | fourni par Expo | MIT | logique pure (réducteurs de la file, calculs d'écart en miroir côté UI) |
| **Maestro** | tests E2E — retenu | CLI, hors npm | Apache-2.0 | flux YAML en boîte noire, simule le mode avion, coût de mise en place faible |
| detox *(option, non retenu V1)* | — | 20.51.4 | MIT | plus fin (accès JS bridge), plus lourd à outiller ; à reconsidérer si Maestro ne suffit plus |
| **eas-cli** | build/OTA managés | 24.8.0 | MIT | l'outil est libre ; le **service** EAS est payant (ci-dessous) |
| @hot-updater/core *(alternative auto-hébergée)* | OTA sans EAS Update | 0.36.15 | MIT | pile branchable (S3/Supabase/R2) ; piste si le coût SaaS multi-client ou l'indépendance (P10) l'exige |

**EAS Build/Update — coût.** Palier gratuit : 15 builds Android + 15 iOS/mois (file basse priorité), 1 000
utilisateurs actifs mensuels (UAM) en mise à jour OTA gratuite. Palier Production (≈ 199 $US/mois selon une
source datée de mai 2026, à reconfirmer sur `expo.dev/pricing`) : 225 $US de crédit de build, 50 000 UAM,
1 Tio de bande passante OTA, puis facturation à l'usage (≈ 1-4 $US/build selon plateforme/taille, 0,10 $US/Gio
OTA au-delà). Pour GRS seule (admin + employés + vendeurs installés ; le profil client est un lien web sans
app — §6), le volume d'appareils est faible : le **palier gratuit couvre vraisemblablement la tranche 1**. Le
coût redevient un sujet réel en phase SaaS multi-instances, où `eas build --local` (build sur machine propre,
signature Apple/Google gérée soi-même) et **Hot Updater** ci-dessus sont des sorties de secours crédibles, sans
changer le client `expo-updates`.

**Pourquoi une file maison plutôt qu'un moteur de synchro.** Les mutations mobiles d'OPSYS sont presque toutes
**additives** (un punch, une ligne de matériau, une case de checklist, une photo) et leur résolution de
« conflit » est déjà une règle métier Python précise (§4, §9.7 : écart faible → stock ajusté ; écart fort →
`completed_pending_review` + alerte) — pas un algorithme générique côté client. Un moteur de synchro
bidirectionnelle (WatermelonDB/PowerSync/Electric) réplique des enregistrements entiers et règle des conflits
génériquement ; OPSYS a besoin d'un **journal d'événements à envoyer une fois**, plus un cache de lecture. La
file maison garde 100 % de la logique métier dans les outils Python déjà testés (P7, `outils.py`), ce que
WatermelonDB seul ne changerait pas (il ne fait que remplacer *comment* la file est stockée, pas la question du
conflit) — raison pour laquelle il reste une **piste d'évolution côté lecture**, pas côté écriture.

---

## 4. Modèle de synchro terrain

**Idempotence.** Chaque mutation crée son UUID **côté appareil**, avant toute tentative réseau
(`mutation_id`). Le champ `idempotencyKey` de l'appel HTTP déterministe (§1.2, `/tools/invoke`) le porte ; le
moteur métier Python l'enregistre (table `mutations_appliquees`, clé `(appareil, idempotencyKey)`) avant
d'agir, si bien qu'un renvoi après une réponse perdue est un no-op sûr qui rejoue le même résultat.

**File sortante.** Table SQLite `outbox` : `id` (UUID), `type` (`punch_in`, `punch_out`, `job_status_change`,
`materials_submit`, `checklist_step`, `incident_report`, `photo_upload`, `signature_capture`,
`po_receive_scan`…), `payload` (JSON), `created_at_local` (horodatage + fuseau de l'appareil), `depends_on`
(mutation parente, ex. `materials_submit` après `job_status_change=completed_pending_review`), `status`
(`brouillon`, `en_attente`, `envoi`, `envoyee`, `echec_permanent`), compteur de tentatives. Une boucle de
vidage (premier plan, reconnexion via `@react-native-community/netinfo`, tâche de fond opportuniste) l'écoule
dans l'ordre par chantier, avec un recul exponentiel qui reprend le principe déjà documenté du client OpenClaw
(1 s → 30 s, ×2).

**Horodatage local et serveur.** Chaque événement porte l'heure de l'appareil (affichée à l'employé — « pointé
à 14 h 32 ») **et** l'heure de réception/application du serveur (faisant foi pour la paie brouillon vers M5,
afin qu'une horloge d'appareil dérégée ne puisse pas fausser un calcul — P2, « le code calcule »). Les deux
sont conservées (P3, traçabilité).

**Résolution des conflits.** La vraie règle de fusion est déjà écrite dans la définition produit (§6, §9.7) et
vit côté serveur, en Python testé — pas dans un algorithme client générique. Le rôle du client se limite à :
(1) ne jamais perdre silencieusement un événement mis en file ; (2) permettre un brouillon local modifiable
(`status: brouillon`) avant soumission explicite, comme §9.3 le prévoit pour le formulaire de matériaux ; (3)
afficher le verdict serveur (ajusté vs `completed_pending_review`) une fois synchronisé. Pour la double
écriture rare (deux appareils sur la même approbation), la clé d'idempotence plus un contrôle de version côté
serveur transforme la seconde écriture en « déjà traité » explicite plutôt qu'une fusion silencieuse — cohérent
avec P1 (aucune décision T3 ne se fusionne seule).

**Reprise.** La file vit en SQLite, pas en mémoire : un redémarrage/plantage en plein envoi retrouve une ligne
`status: envoi` et la renvoie **avec la même clé d'idempotence**, jamais en la recréant.

**Photos volumineuses.** Jamais en base64 dans le JSON de la mutation. Capture bridée (`expo-camera`, ≈1600 px
de long côté, JPEG ~0,8 — même principe de bridage que la commande caméra d'OpenClaw, §1.4) ; le fichier va sur
le stockage local (`expo-file-system`) et la ligne de file référence son URI + un hachage SHA-256 + sa cible
(`job_id`, nature). L'envoi du binaire est une requête distincte (repriseable par hachage), déclenchant le
marquage `envoyee` seulement à l'accusé de réception ; le fichier local est purgé après un court délai de grâce
post-confirmation (minimisation, même esprit que la politique GPS ci-dessous). Vidéo/clips hors périmètre V1
(non demandés par §9).

---

## 5. Arborescence des écrans (Expo Router) et ordre de livraison

```
app/
├── _layout.tsx                    # session, appairage, profil actif, thème, i18n
├── pairing/index.tsx              # QR / code d'appairage (protocole §1.3)
├── (employee)/
│   ├── today.tsx                  # chantiers du jour, route (M4.7)
│   ├── punch.tsx                  # M4.4 : entrée/sortie/pauses
│   ├── job/[id]/index.tsx         # en route/arrivé/démarrer/pause
│   ├── job/[id]/checklist.tsx
│   ├── job/[id]/photos.tsx        # avant/pendant/après
│   ├── job/[id]/incident.tsx
│   ├── job/[id]/complete.tsx      # « Terminer » — déclenche §9.7
│   ├── job/[id]/materials.tsx     # M6.10, formulaire matériaux utilisés
│   ├── job/[id]/signature.tsx
│   ├── purchase/new.tsx           # achat imprévu, reçu photo (M6.17)
│   ├── receiving/[poId].tsx       # scan réception PO (M6.7)
│   ├── field-performance-summary.tsx  # M8, limité, non punitif
│   └── settings/privacy.tsx       # retrait du consentement GPS (§6)
├── (seller)/
│   ├── leads.tsx, leads/[id].tsx  # M2, résumé M1
│   ├── pipeline.tsx
│   ├── estimate/[leadId]/{photos,annotate,scenarios,approve}.tsx  # M3
│   ├── quote/[id].tsx
│   ├── coach.tsx                  # M2.9
│   └── sales-analytics.tsx        # §9.8
├── (admin)/
│   ├── inbox.tsx                  # M1 omnicanal
│   ├── dispatch.tsx               # M4
│   ├── approvals/{index,[type]/[id]}.tsx  # M3/M4/M5/M6/M7/M9/M10
│   ├── materials/{alerts,po,variance,stock}.tsx  # M6
│   ├── finance/{invoices,cashflow,anomalies}.tsx # M5
│   ├── marketing/{content,reviews}.tsx           # M7
│   ├── strategy-{dashboard,daily-brief,decisions,risks,opportunities,scenarios,reports}.tsx  # §9.8, M9
│   └── analytics-{dashboard,wallboard,alerts,departments,reports}.tsx  # §9.8, M8
└── (client)/
    ├── request/new.tsx, status.tsx            # M1/M2
    ├── quote/[id].tsx
    ├── track/[jobId].tsx                      # ETA, lien tokenisé (§6)
    └── invoice/[id].tsx                       # M5
```

Groupes de routes gardés par le rôle du jeton d'appareil (§6) ; un jeton `employee` n'atteint jamais les routes
`(admin)`, même par URL directe, et le serveur ne lui envoie de toute façon jamais les champs qu'elles montrent.

**Ordre de livraison (tranche 1 = `docs/programme/PLAN.md` T1, conforme à la mission).** La chorégraphie
« Travaux terminés » d'abord, parce qu'elle traverse neuf départements et prouve toute la chaîne appairage →
hors ligne → synchro → cascade → approbation en une seule fois :

1. Squelette + appairage + routage par rôle (aucun écran métier).
2. `punch.tsx` seul — la plus petite tranche verticale qui exerce toute la mécanique de file/synchro (§4).
3. `today.tsx` + `job/[id]` + transitions de statut.
4. `checklist.tsx` + `photos.tsx` + `signature.tsx`.
5. `complete.tsx` → déclenche la cascade §6/§9.7 → `materials.tsx` (M6.10).
6. `(admin)/approvals` : revue de complétion, alerte d'écart matériaux — **la tranche n'est pas « faite » (P6)
   tant que l'accusé de réception côté propriétaire ne ferme pas la boucle.**
7. E2E Maestro : travaux terminés normaux ; écart de 40 % → `completed_pending_review` + alerte mobile admin
   (exactement le scénario de PLAN.md T1.5).

Tranches suivantes : vendeur et client (§9.4, §9.6 — PLAN.md T2), reste des tableaux de bord admin (PLAN.md
T3-T4). Les écrans de mémoire (M10, note de chantier) et de performance (M8) sont des ajouts à faible risque,
livrables à tout moment après T1.

---

## 6. Sécurité

**Authentification.** Appairage d'appareil (§1.3) réutilisé : chaque téléphone employé/vendeur/admin est un
appareil apparié, avec un **rôle d'opérateur nommé** côté OPSYS-CORE forké — à définir, mappé un-à-un sur les
rôles OPSYS (`admin`, `employee`, `seller`) plutôt que sur le secret partagé générique d'OpenClaw, dont la doc
amont prévient explicitement qu'il donne un accès opérateur complet (`/tools/invoke` avec jeton partagé =
`operator.admin` de fait). **C'est une tâche de durcissement à faire dans le fork avant la tranche 1** : sans
rôles nommés, un jeton employé aurait la même portée qu'un jeton propriétaire. Le profil **client** n'est pas
un appareil apparié durablement : authentification par lien signé à usage limité, échangé contre un jeton borné
dans le temps (liens tokenisés ci-dessous), jamais une identité d'appareil persistante.

**Jetons et rafraîchissement.** Jeton d'appareil scellé par rôle, rotatif/révocable
(`device.token.rotate/revoke`, §1.3). Clé d'appareil et jetons dans `expo-secure-store` (Keychain/Keystore) —
jamais dans la base SQLite ni `AsyncStorage`.

**Stockage chiffré.** Par défaut : protection au repos du système (iOS Data Protection, chiffrement de fichier
Android, actifs par défaut) pour la base `outbox`/cache, plus `expo-secure-store` pour les secrets. Piste de
durcissement si un audit l'exige : `op-sqlite` + SQLCipher (§3) pour un chiffrement au niveau base plutôt que
seulement disque.

**Vues par rôle.** Appliquées **deux fois** : le serveur (outils Python déterministes, même patron
`refus_metier` que le reste d'OPSYS) n'inclut jamais coûts/marges dans la réponse à un jeton `employee`, ni
aucune donnée interne à un jeton client ; l'app ne rend pas non plus ces champs si un bug les laissait passer.
Le rôle porté par le jeton doit traverser toute la chaîne (Core → appel Python), pas seulement être vérifié à
la frontière HTTP — sinon un client modifié pourrait réclamer des champs qu'il ne devrait pas recevoir.

**Liens clients tokenisés et expirants.** Un seul chantier ou une seule facture par lien, expiration serveur,
révocation possible, accès journalisé — généralisation du patron déjà fixé par la définition produit pour le
suivi GPS client (§9.2, §4.13 M4).

**Loi 25 — consentement GPS.** [`POLITIQUE-geolocalisation.md`](../compliance/politiques/POLITIQUE-geolocalisation.md)
(en attente de validation finale de Nathan) est **plus stricte** que la formulation du §9.2 de la définition
produit : elle interdit tout **traçage continu en arrière-plan** et ne permet que des **fixes ponctuels** au
moment du punch et des transitions de statut. Ce rapport retient la politique comme référence (elle porte
l'autorité Loi 25 ; la définition produit est le QUOI général) : `expo-location.getCurrentPositionAsync` couvre
le punch et les transitions (`en_route`, `arrivé`) sans navette d'arrière-plan. La fenêtre « en route » que
§9.6 exige pour l'ETA client reste la seule utilisation de `expo-task-manager` en arrière-plan : bornée au
chantier en cours, démarrée au bouton « En route », arrêtée automatiquement à « Arrivé ». **Cette lecture
(fenêtre bornée = compatible avec « pas de traçage continu ») doit être confirmée par Nathan/juriste avant
livraison**, au même titre que la durée de rétention déjà marquée « à vérifier » dans la politique. Consentement
enregistré dans `employee_consent_location` (version de la politique, horodatage UTC, signataire — nom de table
à reprendre tel quel) ; retrait exposé dans l'app elle-même (`(employee)/settings/privacy.tsx`, §5), pas
seulement à l'accueil, comme la politique l'exige.

**Angle mort à combler.** Aucune politique équivalente n'existe pour les photos et la signature (données
personnelles/biométriques-adjacentes captées par l'app terrain et le portail client). Recommandation : rédiger
une `POLITIQUE-photos-signature.md` sur le patron des quatre politiques déjà en place
(`docs/compliance/politiques/`) avant de livrer les écrans `photos.tsx`/`signature.tsx` — hors périmètre de ce
fichier.

---

## Recommandations de suivi (hors périmètre de ce fichier)

- Réécrire `docs/architecture/MOBILE.md` : remplacer la « phase 2 : fork » par ce choix (§2).
- Consigner cette pile dans un ADR (extension d'ADR-0008 ou nouvel ADR) — ce rapport documente, il ne décide pas.
- Confirmer avec Nathan/juriste la lecture « fenêtre bornée en route » de la politique GPS (§6).
- Rédiger `POLITIQUE-photos-signature.md` (§6).
- Définir les rôles d'opérateur nommés du fork (§6) avant la tranche 1 — sans eux, aucune portée employé
  restreinte n'est possible côté serveur.
- Confirmer l'algorithme de signature d'appairage exact dans le code du fork (§1.3) avant d'écrire le client TS.
- Inscrire les briques retenues dans `docs/research/INGREDIENTS.md` (ce fichier ne le fait pas lui-même, la
  mission limitant ce rapport à un seul fichier).

---

PREUVE:

- Lus en entier : `docs/produit/DEFINITION-PRODUIT.md` (§0-§15, dont §5 P8/P14, §6, §9 en entier, §13),
  `docs/architecture/ARCHITECTURE.md`, `docs/architecture/DEPARTEMENTS.md`, `docs/architecture/MOBILE.md`,
  `core/UPSTREAM.md`, `docs/decisions/ADR-0008-fork-openclaw-opsys-core.md`, `docs/programme/PLAN.md`,
  `docs/compliance/politiques/POLITIQUE-geolocalisation.md`, `docs/research/00-BRIEF.md`, style vérifié sur
  `docs/research/R1-core-openclaw.md`.
- Clone OpenClaw inspecté : `git log -1` → `2d39f2f7` (2026-09-27) ; `package.json` → `"2026.9.6"`.
  `wc -l` : `apps/ios`+`apps/shared` = 266 428 lignes Swift ; `apps/android` = 258 551 lignes Kotlin ;
  `apps/macos`+`apps/linux`+autres compagnons = 211 825 lignes. Lus : `docs/gateway/pairing.md`,
  `docs/gateway/protocol/auth.md`, `docs/gateway/tools-invoke-http-api.md`, `docs/nodes/index.md`,
  `docs/nodes/pairing-and-status.md`, `docs/nodes/location-command.md`, `docs/nodes/device-commands.md`,
  `packages/gateway-client/README.md`, `packages/gateway-protocol/README.md`, `LICENSE` (MIT, OpenClaw
  Foundation).
- Licences et versions vérifiées sur le registre npm le 2026-09-26/27 pour les briques du tableau §3 (`expo`,
  `expo-router`, `expo-sqlite`, `@op-engineering/op-sqlite`, `@nozbe/watermelondb`, `@tanstack/react-query`,
  `react-hook-form`, `zod`, `expo-notifications`, `expo-location`, `expo-camera`,
  `react-native-vision-camera`, `react-native-signature-canvas`, `i18next`, `react-i18next`,
  `expo-localization`, `@powersync/react-native`, `@electric-sql/pglite`, `eas-cli`, `detox`,
  `expo-task-manager`, `expo-secure-store`, `expo-file-system`, `@react-native-community/netinfo`,
  `@hookform/resolvers`, `@noble/curves`, `@hot-updater/core`). Apache-2.0 d'Electric confirmée directement sur
  `github.com/electric-sql/electric` (fichier `LICENSE` + badge, statut « Beta »). FSL du service PowerSync
  confirmée sur `powersync.com/legal/fsl` et `powersync.com/open-source`. Apache-2.0 de Maestro confirmée sur
  `github.com/mobile-dev-inc/maestro`. Tarification EAS vérifiée sur `docs.expo.dev/billing/*` et
  `expo.dev/pricing` (chiffres recoupés avec une source secondaire datée de mai 2026, à reconfirmer avant
  décision finale).
- Fichier produit : `/home/user/OPSYS-AI/docs/research/R12-app-mobile.md`. Aucun autre fichier du dépôt
  modifié.
