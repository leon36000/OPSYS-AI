# Idempotence des mutations d'appareil (T1.4-b)

> Complète [ARCHITECTURE.md](ARCHITECTURE.md) (couche Capacités MCP) et
> [ADR-0009](../decisions/ADR-0009-socle-metier.md) (une transaction par appel d'outil). Modèle de
> synchro mobile source de cette décision :
> [`docs/research/R12-app-mobile.md`](../research/R12-app-mobile.md) §1.2 et §4.
>
> Ce fichier existait déjà avant T1.4-b avec l'ancien nom réservé `MOBILE.md` : conformément à la
> consigne T1.4-b (éviter un conflit avec l'agent mobile qui réécrit `MOBILE.md` en parallèle), le
> contrat d'idempotence vit ici plutôt que dans `MOBILE.md`.

## 1. Pourquoi

L'app mobile (hors ligne d'abord, §9 de la définition produit) crée chaque mutation (`punch_in`,
`materials_submit`, `checklist_step`, …) **sur l'appareil**, avant toute tentative réseau, et la
rejoue avec la **même** clé tant qu'elle n'a pas reçu d'accusé de réception (R12 §4). Sans
idempotence côté socle, un renvoi après une réponse perdue (réseau coupé pendant la réponse, app
tuée, timeout) **exécuterait l'outil une seconde fois** : un second pointage, une seconde ligne de
matériaux, un second paiement en attente d'approbation. Le socle doit donc garantir qu'une même
mutation d'appareil ne produit jamais deux effets, quel que soit le nombre de renvois.

## 2. Contrat : où voyage la clé

La clé d'idempotence et l'identité de l'appareil voyagent **dans le `_meta` MCP de `tools/call`**,
jamais dans les arguments de l'outil (que le modèle produit et pourrait halluciner, omettre ou
falsifier). Trois clés, sous l'espace de noms `opsys/` :

| Clé `_meta` | Type | Obligatoire si idempotence demandée | Sens |
|---|---|---|---|
| `opsys/idempotencyKey` | string non vide | Oui (sa présence déclenche l'idempotence) | `mutation_id` généré sur l'appareil (R12 §4), unique par mutation logique |
| `opsys/appareil` | string non vide | Oui | Identité de l'appareil appairé (table `appareils`, ADR-0009 §5) |
| `opsys/horodatageAppareil` | string RFC 3339 **avec fuseau** | Oui | Heure locale de l'appareil au moment de la mutation (affichage seulement) |

Sans `opsys/idempotencyKey`, le comportement de `Capacites.appeler` est **strictement inchangé**
(aucune table touchée, aucune clé `rejoue` dans la réponse) : tout appelant MCP qui ne connaît pas
ce contrat (Hermes, Claude Code, un futur outil interne) continue de fonctionner exactement comme
avant T1.4-b.

Si `opsys/idempotencyKey` est présent mais que `opsys/appareil` manque, ou que
`opsys/horodatageAppareil` manque ou n'a pas de fuseau, l'appel est refusé proprement
(`{"ok": false, "erreur": "meta_invalide", ...}`, fail-closed) plutôt que d'exécuter sans
idempotence en silence.

## 3. Ce que fait le socle

### 3.1 Lecture du `_meta` — `serveur_mcp.appeler_outil`

`params.meta` (le SDK MCP Python expose l'alias `_meta` comme l'attribut `meta`, un `dict | None`)
est passé à `idempotence.depuis_meta_mcp`, qui rend une structure typée `idempotence.Meta | None`.
`Capacites.appeler` ne connaît rien de MCP au-delà de cette frontière — c'est la structure typée qui
traverse, jamais le dict brut.

### 3.2 Réclamation puis exécution — `Capacites._appeler_idempotent`

Une seule transaction (`stockage.transaction`, ADR-0009) couvre tout l'appel :

1. **Réclamation** (`idempotence.reclamer`) : lit `(appareil, cle_idempotence)` dans
   `mutations_appliquees`.
   - Absente → tente une insertion (statut transitoire `en_cours`, jamais visible hors de cette
     transaction). Réussie → exécution fraîche.
   - Présente, même outil et même empreinte d'arguments (`idempotence.empreinte_arguments`, SHA-256
     du JSON canonique, clés triées récursivement) → **renvoi** : la réponse enregistrée est rendue
     telle quelle, avec `rejoue: true` ajouté. **Rien n'est ré-exécuté.**
   - Présente, mais outil ou empreinte différents → `MutationConflit` → réponse
     `{"ok": false, "erreur": "mutation_conflit", ...}`. Rien n'est exécuté ni modifié.
2. **Exécution** (exécution fraîche seulement) : le code existant, inchangé
   (`Capacites._distribuer`, donc `outils.executer_atomique`, la création d'une demande
   d'approbation, `_tronquer`) s'exécute **dans la même transaction** — `stockage.transaction`
   l'imbrique automatiquement en point de sauvegarde (ADR-0009), aucune de ces fonctions n'a été
   modifiée pour cela.
3. **Finalisation** (`idempotence.finaliser`, exécution fraîche seulement) : la réponse est
   enregistrée telle quelle (encodée par `stockage.codec`, comme les maillons de registre — fidélité
   de type au-delà de JSON pur), avec `statut` dérivé de son contenu (`ok`/`refus_metier`/
   `en_attente_approbation`, détail juste après). L'appelant reçoit cette même réponse, avec
   `rejoue: false` ajouté.

Sont enregistrées : une exécution réussie (`ok`), un refus métier (`refus_metier`, y compris
`arguments_invalides` : la même mutation sera toujours refusée pour la même raison), et une mise en
attente d'approbation (`en_attente_approbation` — la demande d'approbation elle-même,
`approbations.creer_demande`, n'est donc jamais dupliquée par un renvoi).

Ne sont **pas** enregistrés les refus passagers (`idempotence.ERREURS_PASSAGERES` : `outil_inconnu`,
`departement_appelant_inconnu`, `budget_epuise`). Ils dépendent de l'état de l'instance au moment de
l'appel (outil pas encore déployé, point d'accès mal configuré), pas de la mutation : la réclamation
est retirée et un renvoi réessaie.

Un appel d'appareil n'est pas soumis au budget de jetons du département
(`Capacites._distribuer(appel_appareil=True)`) : ce budget borne la dépense de modèle, et un appel
déterministe par `/tools/invoke` n'en consomme aucun. Les approbations s'appliquent toujours, sauf pour l'humain qui agit lui-même (N3 au plus, identité
valide, outil dans la portée de son rôle) : voir §8. N'est **jamais** enregistrée une panne interne : toute exception non attrapée pendant
l'exécution (un bug, pas un refus métier — `outils.executer` ne convertit que `ValueError`,
`TypeError`, `KeyError`) sort de la transaction entière, qui s'annule — réclamation comprise. Un
renvoi après une panne réelle réessaie donc réellement l'exécution, il ne rejoue pas un échec figé.

### 3.3 Concurrence : une réclamation, jamais deux exécutions

La réclamation et l'exécution étant dans la **même** transaction de bout en bout :

- **SQLite** (défaut) : `BEGIN IMMEDIATE` (`stockage.moteur._debuter_sqlite`) prend le verrou
  exclusif d'écriture dès l'ouverture de la transaction, avant toute instruction. Une deuxième
  réclamation concurrente de la même clé **attend** (jusqu'à `busy_timeout=5000`) que la première
  transaction se termine complètement, puis relit un état déjà résolu (`ok`/`refus_metier`/
  `en_attente_approbation`) : elle rejoue, sans jamais passer par le chemin `IntegrityError`.
- **PostgreSQL** (option) : pas de verrou global à l'ouverture ; deux transactions peuvent lire
  simultanément une absence de réclamation. La contrainte unique `(appareil, cle_idempotence)` (clé
  primaire) fait que l'une des deux insertions **attend** (verrou de ligne Postgres sur une clé en
  conflit non validée), puis, une fois l'autre validée, **échoue proprement** avec `IntegrityError` ;
  la relecture qui suit voit alors la ligne validée et rejoue.

Dans les deux moteurs : jamais deux exécutions pour la même `(appareil, cle_idempotence)`.

## 4. Schéma — migration `0004`

Table `mutations_appliquees` (`src/opsys/stockage/schema.py`,
`src/opsys/stockage/migrations/versions/0004_mutations_appliquees.py`) :

| Colonne | Type | Sens |
|---|---|---|
| `appareil` | `String(128)`, PK | `opsys/appareil` |
| `cle_idempotence` | `String(128)`, PK | `opsys/idempotencyKey` |
| `outil` | `String(128)` | Nom de l'outil appelé |
| `empreinte_arguments` | `String(64)` | SHA-256 du JSON canonique des arguments |
| `reponse` | `Text` | Réponse complète, encodée par `stockage.codec` |
| `horodatage_appareil` | `Text` (ISO) | `opsys/horodatageAppareil`, tel que reçu, sans reformatage |
| `recu_le` | `Text` (ISO) | Heure de réception du **serveur** — fait foi |
| `statut` | `String(24)` | `en_cours` (transitoire) \| `ok` \| `refus_metier` \| `en_attente_approbation` |

Comme le reste du plan de contrôle (`APPROBATIONS`, `JOURNAL`…), les dates sont du texte ISO, pas un
type `DateTime` : elles repartent telles quelles vers les API JSON, sans conversion de fuseau
implicite.

## 5. Les deux horloges — accesseur de contexte

`opsys.contexte.horodatage_reception()` (même esprit que `appeler_en_tant_que` : fixé par la
plateforme dans une `ContextVar`, jamais par le modèle) rend, **pendant l'exécution d'une mutation
idempotente seulement**, une `HorodatageAppareil(appareil, horodatage_appareil, recu_le)` :

- `horodatage_appareil` : l'heure de l'appareil, **affichée à l'employé** (« pointé à 14 h 32 »),
  jamais fiable pour un calcul (une horloge d'appareil peut dériver) ;
- `recu_le` : l'heure de réception du **serveur**, qui **fait foi** pour tout calcul en aval — en
  particulier la paie brouillon de M4 (T1.4-d, R12 §4 : « une horloge d'appareil déréglée ne peut
  pas fausser un calcul »).

Hors d'un appel idempotent (pas de `_meta`, ou pendant la création/décision d'une demande
d'approbation elle-même — le futur exécuteur approuvé, `approbations.decider`, n'a pas encore été
enrichi de ces horloges, voir §7), l'accesseur rend `None`.

## 6. Exemple

```
tools/call "m4_pointer_entree"
  _meta: {
    "opsys/idempotencyKey": "b3f1…",
    "opsys/appareil": "tel-employe-42",
    "opsys/horodatageAppareil": "2026-09-28T14:32:05-04:00"
  }
  arguments: {"chantier_id": "…"}
```

1er appel → `{"ok": true, "resultat": {...}, "rejoue": false}` — perdu en chemin (coupure réseau).
Renvoi, **même** `_meta`, **mêmes** arguments → **exactement** la même réponse, avec
`"rejoue": true` — sans second pointage.

## 7. OPSYS-CORE : transmission du `_meta` (T1.4-c1, fait)

Le core (`core/`) reste lu et modifié sans être exécuté dans le bac à sable (règle du dépôt : il ne
se construit et ne se teste qu'en CI, `.github/workflows/core.yml`). Ce qui suit décrit le
comportement livré par T1.4-c1 — la lecture ci-dessous (constat avant le changement) reste comme
trace du raisonnement.

**Avant T1.4-c1**, `idempotencyKey` de `POST /tools/invoke` n'atteignait jamais le `_meta` MCP. Il ne
servait qu'à construire un `toolCallId` local (déduplication du hook `beforeToolCall`/détection de
boucle) :

- `core/src/gateway/tools-invoke-shared.ts`, `ToolsInvokeInput` (ligne 56) déclare déjà
  `idempotencyKey?: unknown`, mais aucun champ pour l'identité ou l'horodatage de l'appareil.
- `invokeGatewayToolWithSignal` (lignes 405-408) ne l'utilise que pour
  `toolCallId = ...-${idempotencyKey}`, puis appelle
  `gatewayTool.execute?.(toolCallId, hookResult.params, params.signal)` (ligne ~450) : **seuls les
  arguments métier passent**, aucun canal pour une méta hors-bande.
- `AnyAgentTool.execute` (`core/src/agents/tools/common.ts`, ligne 49) a la signature
  `execute(toolCallId, params, signal?, onUpdate?)` — commune à **tous** les outils (core, plugin,
  MCP), donc à ne pas élargir pour un besoin propre au seul chemin MCP.
- Pour un outil MCP, cette chaîne aboutit à
  `core/src/agents/agent-bundle-mcp-materialize.ts`, `createExecute` (ligne 478), qui appelle
  `runtime.callTool(serverName, toolName, input)` — puis
  `core/src/agents/agent-bundle-mcp-runtime.ts`, méthode `callTool` de `ServerMcpRuntime`
  (ligne 1054-1062), qui construit l'appel MCP réel :
  ```ts
  session.client.callTool(
    { name: toolName, arguments: isRecord(input) ? input : {} },  // ← pas de _meta ici
    undefined,
    { timeout: session.requestTimeoutMs, signal },
  )
  ```
  `session.client` est le SDK MCP TypeScript ; son premier argument est le `params` de la requête
  `tools/call` — c'est l'endroit exact, et le seul, où `_meta` doit s'ajouter côté sortant, en miroir
  exact de `params.meta` côté socle (§3.1) confirmé ici par lecture directe du SDK MCP Python
  (`mcp_types.RequestParamsMeta`, un `TypedDict` ouvert — le SDK TypeScript expose la même forme
  ouverte sur `CallToolRequest["params"]._meta`).

**Changement livré par T1.4-c1** (précédent déjà dans ce fichier :
`core/src/gateway/server-plugin-in-process-dispatch.ts`, ligne 65,
`new AsyncLocalStorage<OperatorToolGatewayAuthority>()`, exactement pour une donnée « host-minted,
jamais dérivée des paramètres du fil » — la même propriété que `_meta` d'idempotence exige) :

1. `ToolsInvokeInput` (`tools-invoke-shared.ts`) : deux champs optionnels ajoutés à côté de
   `idempotencyKey` — `deviceId?: unknown` et `deviceTimestamp?: unknown`, mêmes noms que le client
   mobile (`mobile/src/protocole/types.ts`, `RequeteOutilsInvoke`).
2. Nouveau, petit module `core/src/agents/mcp-call-meta.ts` : un
   `AsyncLocalStorage<Record<string, unknown>>` avec `withMcpCallMeta(meta, run)` et
   `currentMcpCallMeta()`, sur le patron exact de `withOperatorToolGatewayAuthority`.
3. `invokeGatewayToolWithSignal` : quand `idempotencyKey` est fourni, construit
   `{"opsys/idempotencyKey": idempotencyKey, "opsys/appareil": deviceId,
   "opsys/horodatageAppareil": deviceTimestamp}` (les deux derniers champs omis, pas envoyés
   `undefined`, quand absents du corps — c'est `opsys.idempotence.depuis_meta_mcp`, côté socle, qui
   refuse proprement s'ils manquent, T1.4-b) et enveloppe l'appel existant à
   `gatewayTool.execute?.(...)` dans `withMcpCallMeta(...)`. **Aucun changement** à la signature
   `execute` ni aux outils non-MCP ; sans `idempotencyKey`, aucun `_meta` ambiant n'est posé —
   comportement byte-for-byte identique à avant T1.4-c1.
4. `agent-bundle-mcp-runtime.ts`, méthode `callTool` : lit `currentMcpCallMeta()` et l'ajoute en
   `_meta` au premier argument de `session.client.callTool(...)` quand présent. **Aucun changement**
   à la signature `ServerMcpRuntime.callTool` (`agent-bundle-mcp-types.ts`) : c'est précisément
   pourquoi la propagation par contexte ambiant (plutôt qu'un paramètre supplémentaire filé à
   travers `agent-bundle-mcp-materialize.ts`) est préférable ici — rayon d'impact nul sur les types
   partagés par tous les outils.

Seuls ces trois fichiers changent (plus le nouveau module), et seulement pour le chemin
`POST /tools/invoke` → outil MCP ; `AnyAgentTool.execute` et `ServerMcpRuntime.callTool` sont
inchangés, tout comme les outils non-MCP. Tests vitest (jamais exécutés dans ce bac à sable, la CI
`core.yml` tranche) : `core/src/agents/mcp-call-meta.test.ts` (le primitif seul),
`core/src/agents/agent-bundle-mcp-runtime.mcp-call-meta.test.ts` (bout en bout sur un vrai
sous-processus MCP stdio : le `_meta` reçu sur le fil, avec et sans `withMcpCallMeta`), et
`core/src/gateway/tools-invoke-http.device-identity.test.ts` (construction du `_meta` depuis le
corps HTTP de `/tools/invoke`, y compris l'absence de `idempotencyKey` et l'absence partielle de
`deviceId`/`deviceTimestamp`).

Ce que T1.4-c1 ne fait PAS : rien côté rôles nommés ni portée d'outil — voir §7 bis (T1.4-c2).

**Correction (T1.4-c6).** La lecture ci-dessus supposait que `/tools/invoke` trouvait un outil MCP dans
la liste d'outils de l'agent. Ce n'est pas le cas : cette liste ne contient que des outils du core, de
plugins et de canaux. Le `_meta` de T1.4-c1 n'était atteignable que par un tour d'agent. Un appareil
appairé passe maintenant par une porte dédiée, qui appelle le serveur MCP du département sous le nom nu
de l'outil, avec ce même `_meta` : voir [MOBILE.md](MOBILE.md), « Nom d'un outil de l'app au moteur ».

## 7 bis. OPSYS-CORE : rôles nommés et portée d'outil (T1.4-c2, durci par T1.4-c4)

Voir `docs/architecture/MOBILE.md` (section rôles) pour le contrat complet (jeton d'appareil,
appairage, refus fermé par défaut) : ce paragraphe ne fait que situer T1.4-c2/T1.4-c4 dans le fil
de ce fichier. Depuis T1.4-j, la liste des outils de chaque rôle n'est plus « tout un
département » : chaque outil déclare ses rôles (`Outil.roles_appareil`, fermé par défaut, T3/N5
jamais), table et règle dans [`ROLES.md`](ROLES.md). `/tools/invoke` transmet, en plus des trois
clés `_meta` ci-dessus, `opsys/personne`/`opsys/role` (résolus depuis un `deviceId` — désormais **authentifié**, voir
ci-dessous — par deux fragments générés côté OPSYS, `opsys/roles.json` et `opsys/appareils.json`,
lus directement par `core/src/gateway/opsys-device-roles.ts` — jamais écrits à la main dans le
core, jamais via `$include`) et refuse un outil hors de la portée du rôle avant même d'émettre
`tools/call` — un appareil non reconnu, un rôle sans entrée dans `roles.json`, ou un outil hors de
la liste du rôle sont trois refus, jamais un accès implicite complet. Côté socle,
`opsys.contexte.depuis_meta_mcp_identite`/`appele_par_appareil`/`identite_appelante` exposent
cette identité par le même patron de `ContextVar` que `horodatage_reception` (§5) ; aucun outil de
département ne les lit encore pour signer ou projeter (M3 restera à adapter dans une tâche
séparée), mais la mise en garde « non authentifié » a été retirée de
`opsys.contexte.identite_appelante()` — voir plus bas pourquoi c'est sûr.

### `opsys-metier appareils` : attribuer une personne et un rôle (T1.4-c4, fait)

`opsys.appareils.appairer` (T1.4-c2) et `opsys.openclaw.ecrire_appareils` existaient déjà, mais
sans surface pour les enchaîner (« aucune surface d'appairage n'existe encore côté console/CLI/app »,
T1.4-c2). `opsys-metier appareils appairer <deviceId> --personne <p> --role <r> --config-dir <dossier>`
comble ce trou : il attribue la personne et le rôle (fail-closed, `appareils.appairer` — la
personne doit déjà porter elle-même ce rôle, ADR-0009 §5), PUIS régénère
`opsys/appareils.json` (`ecrire_appareils`) dans la même commande, pour qu'`opsys-device-roles.ts`
voie l'attribution au prochain appel. `opsys-metier appareils lister`/`revoquer` complètent le trio,
`revoquer` régénérant lui aussi le fragment. **Deux temps distincts, jamais fusionnés** : (1)
l'approbation NATIVE de l'appairage, faite par le propriétaire côté OPSYS-CORE — hors de portée
d'`opsys`, c'est elle qui scelle le jeton d'appareil (R12 §1.3) ; (2) `opsys-metier appareils appairer`,
qui attribue la personne/le rôle OPSYS au `deviceId` déjà approuvé. Une attribution pour un
`deviceId` jamais approuvé côté core reste sans effet concret, par construction : sans jeton
d'appareil valide émis par une approbation native, `/tools/invoke` ne laisse jamais ce `deviceId`
s'authentifier (section suivante) — attribuer une personne à un `deviceId` fictif n'ouvre donc
aucun accès par lui-même.

### `/tools/invoke` authentifie l'appareil par son propre jeton (T1.4-c4, fait)

**Le défaut corrigé.** Avant T1.4-c4, `/tools/invoke` authentifiait tout appelant HTTP par le seul
secret partagé de la Gateway (`token`/`password`), qui donne un accès opérateur complet — c'est le
modèle documenté et voulu pour les appelants serveur de confiance (OpenAI-compatible, automations),
mais le `deviceId` d'`_meta` venait alors du **corps de la requête**, jamais vérifié : un détenteur
du secret partagé pouvait l'omettre (accès complet, aucun rôle appliqué) ou déclarer celui d'un
autre appareil (`opsys/personne`/`opsys/role` usurpés). Corrigé en réutilisant, sans rien écrire de
nouveau, le mécanisme d'authentification par jeton d'appareil déjà présent dans le fork pour
d'autres routes HTTP (lecture Control UI, routes de plugin) :

- **Authentification.** `core/src/gateway/http-auth-utils.ts`, `verifyHttpOperatorDeviceToken` :
  déjà la fonction qui, pour un bearer donné, parcourt les appareils appairés
  (`listDevicePairing`), trouve celui dont le jeton de rôle `"operator"` correspond
  (`verifyPairingToken`), puis le vérifie réellement (révocation, génération de secret partagé,
  portées — `verifyDeviceToken`, `core/src/infra/device-pairing-tokens.ts`). Seul changement : elle
  rend aussi le `deviceId` de l'appareil apparié qui a matché — pas seulement ses portées — puisque
  c'est la seule façon de savoir QUEL appareil s'est authentifié (le bearer lui-même ne porte pas
  de `deviceId`). Ce `deviceId`, jamais le corps, remonte jusqu'à `AuthorizedGatewayHttpRequest.
  deviceId`, exposé uniquement quand `authMethod === "device-token"`.
- **Activation pour `/tools/invoke`.** `authorizeScopedGatewayHttpRequestOrReply` (même fichier)
  gagne un `allowDeviceToken` optionnel (faux par défaut, donc sans effet sur les 6 autres appelants
  existants) ; `tools-invoke-http.ts` est le premier à le passer à `true`, avec un nouveau
  résolveur de portées, `resolveToolsInvokeHttpOperatorScopes` : secret partagé → portées complètes
  documentées (inchangé) ; jeton d'appareil → seulement les portées réellement accordées à CET
  appareil à l'approbation de l'appairage (jamais l'accès complet).
- **Identité, jamais depuis le corps.** `tools-invoke-shared.ts` (`invokeGatewayTool`) reçoit un
  nouveau paramètre hôte, `authenticatedDeviceId` — du même patron que `operatorRoleActor`
  (« host-minted, jamais dérivé des paramètres du fil ») : `tools-invoke-http.ts` ne le renseigne
  que depuis `requestAuth.deviceId` (donc jamais pour un appelant secret partagé). La résolution
  `opsys/personne`/`opsys/role` (`authorizeOpsysDeviceTool`, inchangée) ne se déclenche plus que sur
  `authenticatedDeviceId` : un appelant secret partagé n'en porte jamais, quel que soit le
  `deviceId` de son corps — il ne peut donc plus « emprunter » une identité d'appareil.
  `input.deviceId` (le corps) garde son seul rôle historique (T1.4-c1) : nommer l'appareil pour
  `opsys/appareil` (bookkeeping d'idempotence), utilisé seulement en l'absence d'identité
  authentifiée. Si le corps déclare un `deviceId` **différent** de l'appareil authentifié, l'appel
  est refusé (403, `tool_call_blocked`) avant même de consulter `roles.json` — jamais une
  préférence silencieuse pour l'un ou l'autre.
- **Refus fermé, à chaque étage.** Jeton révoqué, inconnu, ou dont la génération de secret partagé
  a tourné → 401 (`checkHttpOperatorCredentials` échoue, chemin inchangé). Portées de l'appareil
  insuffisantes pour la méthode `agent` (`operator.write`) → 403 (portée manquante, avant même
  d'atteindre `invokeGatewayTool`). Appareil authentifié mais sans entrée dans `appareils.json`, ou
  rôle sans entrée dans `roles.json`, ou outil hors de la portée du rôle → 403 (`tool_call_blocked`,
  inchangé depuis T1.4-c2, mais dorénavant **obligatoire** pour tout appelant authentifié par jeton
  d'appareil — il n'existe plus de « corps sans `deviceId` » qui contournerait le contrôle pour ce
  chemin).
- **Identifiant de client OPSYS.** `GATEWAY_CLIENT_IDS.OPSYS_MOBILE` (`opsys-mobile`) ajouté au
  registre fermé du fork (`core/packages/gateway-protocol/src/client-info.ts`) — vérifié par
  lecture qu'aucun switch exhaustif ni schéma séparé n'en dépend (le schéma de poignée de main
  `Type.Enum(GATEWAY_CLIENT_IDS)` dérive directement de cet objet). **Câblé par T1.4-c5** : le mobile
  envoie `opsys-mobile` (`mobile/src/appairage/clientInfo.ts`), et `isNativeAppUiClient`
  (`handshake-auth-helpers.ts`) ne le reconnaît PAS, volontairement : la classe « app native » ouvre des
  voies d'approbation silencieuse qu'un téléphone OPSYS n'a pas à avoir. Décision, lecture du fork et test
  qui l'épingle : `MOBILE.md`, « Identifiant de client ». La même tranche donne à l'app sa personne et son
  rôle nommé par `GET /opsys/identite`, lus par le même code que cette porte d'outils
  (`resolveOpsysDeviceIdentity`, `opsys-device-roles.ts`) : `MOBILE.md`, « Identité de l'appareil ».
- **Preuve.** Tests vitest ajoutés (la CI `core.yml` les exécute, jamais ce bac à sable) :
  `tools-invoke-http.device-token-auth.test.ts` (bout en bout, appairage/jeton réels via
  `requestDevicePairing`/`approveDevicePairing`/`revokeDeviceToken`, contre un `OPENCLAW_HOME`
  temporaire par test — jeton valide, jeton révoqué, jeton inconnu, `deviceId` de corps
  concordant/discordant, secret partagé qui ne peut pas emprunter d'identité) et
  `tools-invoke-http.opsys-roles.test.ts` (réécrit : un bloc HTTP prouve que le secret partagé ne
  déclenche plus jamais la résolution de rôle, un bloc appelle `invokeGatewayTool` directement pour
  isoler la logique `authenticatedDeviceId`). Côté socle, `tests/test_contexte.py` gagne
  `test_identite_appelante_ignore_les_arguments_de_loutil` : preuve qu'un argument d'outil, même
  nommé pour ressembler à un rôle, n'influence jamais `identite_appelante()` — seul `_meta` le
  peut, structurellement (`depuis_meta_mcp_identite` ne reçoit que `meta` en paramètre).

**Ce qui reste, volontairement hors de cette tranche :** aucun outil de département ne lit encore
`identite_appelante()` pour signer ou projeter (M3, tâche séparée) — le socle, lui, la lit depuis
T1.4-h pour la validation humaine au départ (§8) ; l'identifiant de client OPSYS
n'est pas câblé côté mobile ni dans `isNativeAppUiClient` ; une revue externe (code de sécurité,
AGENTS.md) reste requise avant mise en service, comme pour toute PR touchant M5/les politiques/les
approbations.

## 8. Validation humaine au départ (T1.4-h)

Les départements sont en mode `ombre` : tout outil N3 et plus part en file d'approbation du
propriétaire, ce qui est voulu pour ce qu'un AGENT propose. Mais un appel d'appareil qui porte
l'identité authentifiée de l'humain (`opsys/personne`, `opsys/role`, §7 bis) est l'action de cet
humain, pas une proposition : mettre son pointage ou sa complétion en attente rendrait l'app
inutilisable. La règle et sa justification sont dans l'addendum T1.4-h d'ADR-0009 §4 ; ce qui suit
décrit comment elle s'articule avec l'idempotence.

**Où.** `Capacites._distribuer` → `Capacites._valider_au_depart`, seulement pour `appel_appareil=True`
(donc dans la transaction de `_appeler_idempotent`) et seulement quand l'approbation serait requise.

**Conditions cumulées** (la première qui manque renvoie au chemin normal, sauf la 3) :

1. niveau effectif de l'outil N3 au plus (`politiques.validation_au_depart_possible`) ;
2. identité de jeton d'appareil présente ET confirmée en base à l'instant de l'appel
   (`approbations.signataire_valide` : `identite.personne_active`, et la personne porte toujours ce
   rôle) — sans identité, ou avec une identité invalide, inactive ou dont le rôle a été retiré, la
   demande va en file comme avant ;
3. outil dans la portée du rôle, par `openclaw.roles_outils` (la fonction qui écrit `roles.json` pour
   le core, appelée telle quelle, jamais recopiée) — sinon refus nommé `hors_portee_role`.

**Trace.** Une exécution réussie écrit, dans le même point de sauvegarde que l'outil : une ligne
`approbations` au statut `executee` (`decide_par`/`decide_role` = la personne et le rôle, `outil`,
`arguments`, `niveau`, `cree_le`/`decide_le`, `motif_decision` = « validation humaine au départ par la
personne qui agit, ADR-0009 §4 ») et l'entrée d'audit `approbation.valider_au_depart` du journal
existant (appareil, empreinte des arguments réels). Pas de table ni de journal nouveaux. Le fix GPS
(`fix_gps`) n'est jamais copié en clair dans la trace (POLITIQUE-geolocalisation §5).

**Interaction avec l'idempotence.**

- Un renvoi de la même clé rejoue la réponse enregistrée (§3.2) : il ne repasse ni par la validation
  ni par l'outil, donc ni seconde exécution ni seconde trace — même si la personne a été désactivée
  entre-temps.
- Exécution et trace sont atomiques : si l'écriture de la trace échoue, l'exécution, la ligne, l'entrée
  d'audit et la réclamation `(appareil, cle)` sont annulées ensemble (panne interne, §3.2) ; un renvoi
  réessaie réellement.
- Une réponse d'exécution validée au départ s'enregistre comme toute réponse fraîche (`ok`) ; un refus
  métier ou `arguments_invalides` n'exécute rien et ne laisse aucune trace.
- `hors_portee_role` s'enregistre comme un refus métier (`refus_metier`) et se rejoue au renvoi :
  la portée d'un rôle est une règle du code, pas un état passager de l'instance. Il n'est donc pas
  dans `idempotence.ERREURS_PASSAGERES`. Si l'on préfère qu'un renvoi réessaie après un changement de
  portée, c'est une entrée à y ajouter.
- Appel sans `opsys/idempotencyKey` : `appel_appareil` reste faux, la voie n'est jamais empruntée,
  comportement strictement inchangé (§2).

**Ce qui ne change pas.** N4 et N5 vont toujours au propriétaire (N5 exige toujours l'attestation) ;
un appel sans identité (agent, secret partagé) suit la file ; un outil hors portée d'un rôle qui
serait N4 ou N5 suit aussi la file, comme avant (le core le refuse déjà en amont) ; en mode
`supervise` ou `autonome`, un N3 s'exécute déjà sans approbation, donc sans trace de ce type.

**Limites connues.**

- L'authenticité de l'identité repose sur OPSYS-CORE (jeton d'appareil vérifié, T1.4-c4) : le socle
  relit la personne et le rôle en base, il ne peut pas authentifier l'appareil. Qui détient
  `OPSYS_MCP_JETON` pourrait écrire `opsys/personne`/`opsys/role` dans un `_meta` : ce canal doit rester
  réservé au core. La table `appareils` n'est pas relue par le socle.
- La règle hérite de la granularité de `openclaw.roles_outils` : `employee` couvre tous les outils M4 et
  M6 hors T3. Ce que la file du propriétaire filtrait pour un employé passe désormais sans elle, par
  exemple `m6_approuver_po`, `m4_resoudre_demande`, `m4_definir_consentement_gps`,
  `m4_lire_position_gps`. À resserrer (portée par outil dans les manifestes) avant la mise en service ;
  le resserrement de `roles_outils` profitera automatiquement à cette règle.
- La console affiche la ligne `executee` avec le libellé des demandes approuvées ; c'est le motif et
  le rôle de la décision qui la distinguent d'une approbation du propriétaire.
