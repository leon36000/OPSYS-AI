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

Sont enregistrées : une exécution réussie (`ok`), un refus métier (`refus_metier` — y compris
`arguments_invalides`, `outil_inconnu`, `budget_epuise` : des réponses déterministes, sans effet de
bord à protéger, cf. `outils.py`), et une mise en attente d'approbation (`en_attente_approbation` —
la demande d'approbation elle-même, `approbations.creer_demande`, n'est donc jamais dupliquée par un
renvoi). N'est **jamais** enregistrée une panne interne : toute exception non attrapée pendant
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

## 7. Ce qu'il reste à faire dans OPSYS-CORE (T1.4-c) — non modifié ici

Le core (`core/`) est lu, jamais modifié ni exécuté par T1.4-b (règle du dépôt : il ne se construit
et ne se teste qu'en CI). Constat de lecture, précis, pour T1.4-c :

**Aujourd'hui, `idempotencyKey` de `POST /tools/invoke` n'atteint jamais le `_meta` MCP.** Il ne
sert qu'à construire un `toolCallId` local (déduplication du hook `beforeToolCall`/détection de
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

**Changement recommandé pour T1.4-c** (précédent déjà dans ce fichier :
`core/src/gateway/server-plugin-in-process-dispatch.ts`, ligne 65,
`new AsyncLocalStorage<OperatorToolGatewayAuthority>()`, exactement pour une donnée « host-minted,
jamais dérivée des paramètres du fil » — la même propriété que `_meta` d'idempotence exige) :

1. `ToolsInvokeInput` (`tools-invoke-shared.ts`) : ajouter deux champs optionnels à côté de
   `idempotencyKey` — p. ex. `deviceId?: unknown` et `deviceTimestamp?: unknown`.
2. Nouveau, petit module (p. ex. `core/src/agents/mcp-call-meta.ts`) : un
   `AsyncLocalStorage<Record<string, unknown>>` avec `withMcpCallMeta(meta, run)` et
   `currentMcpCallMeta()`, sur le patron exact de `withOperatorToolGatewayAuthority`.
3. `invokeGatewayToolWithSignal` : quand `idempotencyKey` est fourni, construire
   `{"opsys/idempotencyKey": idempotencyKey, "opsys/appareil": deviceId,
   "opsys/horodatageAppareil": deviceTimestamp}` et envelopper l'appel existant à
   `gatewayTool.execute?.(...)` dans `withMcpCallMeta(...)`. **Aucun changement** à la signature
   `execute` ni aux outils non-MCP.
4. `agent-bundle-mcp-runtime.ts`, méthode `callTool` (ligne 1054) : lire `currentMcpCallMeta()` et
   l'ajouter en `_meta` au premier argument de `session.client.callTool(...)` quand présent. **Aucun
   changement** à la signature `ServerMcpRuntime.callTool` (`agent-bundle-mcp-types.ts`, ligne 159) :
   c'est précisément pourquoi la propagation par contexte ambiant (plutôt qu'un paramètre
   supplémentaire filé à travers `agent-bundle-mcp-materialize.ts`) est préférable ici — rayon
   d'impact nul sur les types partagés par tous les outils.

Ce plan ne touche ni `AnyAgentTool.execute`, ni `ServerMcpRuntime.callTool`, ni aucun outil non-MCP :
seuls les trois fichiers ci-dessus changent, et seulement pour le chemin
`POST /tools/invoke` → outil MCP.
