# OPSYS-CORE — provenance du fork

OPSYS-CORE est un **fork dur** d'OpenClaw ([ADR-0008](../docs/decisions/ADR-0008-fork-openclaw-opsys-core.md)).
Il n'est plus synchronisé avec l'amont. Nous le modifions librement et publions nos propres versions.

| Champ | Valeur |
|---|---|
| Projet d'origine | [openclaw/openclaw](https://github.com/openclaw/openclaw) |
| Licence d'origine | MIT, © 2026 OpenClaw Foundation (`LICENSE` conservé tel quel, voir aussi `NOTICE`) |
| Release importée | `v2026.9.6`, tag annoté `ce5bbdc244ee937246cc1700d1b224d020c3b599` |
| Commit importé | `eb377ac59e6c9fd6c7705028034812becf00271b` (2026-09-22) |
| Date d'import | 2026-09-28 |
| Historique amont | non importé (instantané) |

## Transformation appliquée à l'import

Elle est reproductible depuis le tag. Le script est
[`outils/fork/elaguer_core.py`](../outils/fork/elaguer_core.py), et ses raisons sont détaillées dans
[R11](../docs/research/R11-fork-openclaw.md).

1. **Retiré au premier niveau** :
   - `.github/`, `.agents/`, `.claude/`, `.vscode/` ;
   - `apps/` : les apps natives. L'app OPSYS est en Expo, voir R12 ;
   - `crates/`, `CHANGELOG/`, `CHANGELOG.md`, `qa/`, `examples/` ;
   - `appcast.xml`, `fly.toml`, `render.yaml` ;
   - `git-hooks/`. Sans lui, le script `prepare` de pnpm ne reconfigure pas les hooks git du dépôt
     OPSYS-AI.
2. **Extensions** : 42 conservées sur 162, soit les 40 de R11 §3.2 et deux d'appui (`test-support`,
   `image-generation-core`).
3. **`docs/`** : élagué à trois sous-ensembles et un fichier individuel près (T0.6), lus par du
   code non-test ou par des tests de comportement produit que l'élagage des extensions ne suffit
   pas à neutraliser :
   - `docs/reference/templates/` (au complet, gabarits d'espace de travail des agents) : lu par
     `src/agents/workspace-templates.ts` et `src/agents/agent-roles.ts` (`roles/<role>/CLAW.md`,
     `roles/presets/team.json`) — sans lui, tout agent embarqué échoue à l'amorçage
     (« Bundled agent role is missing »).
   - `docs/.generated/` (les 4 fichiers suivis en amont seulement : `README.md`,
     `config-baseline.{counts.json,sha256}`, `sqlite-session-transcript-schema-baseline.sha256`) :
     ligne de base de configuration, lue par `src/config/doc-baseline.ts`.
   - `docs/assets/openclaw-hero-dark.png` : seule image de `docs/assets/` que lit la construction
     de l'UI (`ui/config/control-ui-social-card.ts`, plugin vite de `ui/vite.config.ts`) ; sans
     elle, `pnpm build` échoue sur `ui:build`.

   Même traitement pour un fichier individuel hors de ces trois sous-ensembles (T0.6, liste
   `DOCS_FICHIERS_GARDES` du script d'élagage, sur le modèle d'`APPS_FICHIERS_GARDES`) :
   - `docs/install/docker.md` : deux tests de `src/dockerfile.test.ts` comparent son contenu
     documenté au comportement réel — la commande de santé Compose du script de configuration et
     les arguments de provenance (`GIT_COMMIT`/`OPENCLAW_BUILD_TIMESTAMP`) du Dockerfile — pour
     détecter une dérive doc/produit. Ce sont des tests de comportement produit, pas de CI amont ;
     contrairement au test de `src/audit/message-delivery-progress-store.test.ts` qui lisait
     `.github/actions/git-owner/test-prerequisites.json` (retiré, pas restauré : ce test exécutait
     un `git fetch origin <commit historique d'OpenClaw>` puis un `git worktree add` pour lancer
     l'ancien code de ce commit — un mécanisme qui suppose une continuité d'historique avec l'amont
     qu'un fork dur sans dépendance aux mises à jour amont (ADR-0008) n'a pas : le commit épinglé
     n'existe ni dans ce dépôt ni sur son `origin` réel. Restaurer seul le fichier JSON n'aurait pas
     suffi à faire passer ce test ; il est supprimé plutôt qu'affaibli).

   Le reste de `docs/` (documentation produit amont) reste élagué : OPSYS écrit sa propre
   documentation dans `docs/` du dépôt OPSYS-AI. Les tests qui vérifiaient des pages non
   restaurées (`src/docs/*.test.ts`, huit fichiers) sont retirés, voir le commit qui introduit ce
   paragraphe.

   Même traitement pour deux fichiers partagés d'`apps/`, que la construction lit (T0.6, CI) :
   - `apps/shared/OpenClawKit/Sources/OpenClawKit/Resources/tool-display.json` : importé par
     `ui/src/lib/chat/tool-display.ts` ;
   - `apps/shared/mermaid/.gitignore` : dossier de sortie de `packages/mermaid-renderer`.

   Ils sont listés dans `APPS_FICHIERS_GARDES` du script d'élagage.
4. **Patch pnpm retiré** : `matrix-js-sdk`, avec l'extension Matrix.
5. **`pnpm-lock.yaml` régénéré sans exécuter aucun script de paquet** :
   `pnpm install --lockfile-only --ignore-scripts --ignore-pnpmfile` (pnpm 12.4.0). Résultat : 63
   projets de workspace, 1 687 entrées, contrôles de chaîne d'approvisionnement de pnpm passés.
6. **Fichiers suivis** : exactement ceux que la release suit, moins l'élagage, plus les 27 fichiers
   de `docs/` restaurés au point 3 (26 avant `docs/install/docker.md`, T0.6). Au total, environ
   36 213 fichiers sur 48 575 à l'import ; le chiffre se déplace légèrement à chaque vague
   d'élagage ultérieure de `scripts/`/`test/` et à chaque fichier restauré au cas par cas (T0.6,
   T0.7).

## Suite de la transformation

Elle se fait dans des commits séparés : renommage de la marque visible, greffes OPSYS, puis élagage
de `scripts/` et de `test/` guidé par la CI. Voir `docs/programme/PLAN.md` (T0.6, T0.7).

## Greffes OPSYS

Code propre à OPSYS ajouté ou modifié dans le fork, hors élagage et renommage. Chaque greffe
préfère des fichiers neufs, et ses tests sont dans `test/opsys-tests-cibles.txt` (job `tests-opsys`
de `.github/workflows/core.yml`).

### T1.4-c : identité d'appareil sur `/tools/invoke` et dans le `_meta` MCP

- Ajoutés : `src/agents/mcp-call-meta.ts`, `src/gateway/opsys-device-roles.ts`.
- Modifiés : `src/agents/agent-bundle-mcp-runtime.ts`, `src/gateway/http-auth-utils.ts`,
  `src/gateway/http-utils.ts`, `src/gateway/tools-invoke-http.ts`,
  `src/gateway/tools-invoke-shared.ts`, `packages/gateway-protocol/src/client-info.ts`.

### T1.4-c6 : la porte d'appareil vers le serveur MCP du département

Un appareil appairé (jeton d'appareil, rôle OPSYS) n'appelle plus `/tools/invoke` par la liste d'outils
d'un agent, qui ne contient aucun outil MCP. Le core lit le serveur de l'outil dans `opsys/roles.json`
(clé `serveurs`, générée par `src/opsys/openclaw.py::serveurs_outils`), ouvre une session MCP privée
limitée à ce serveur, y appelle l'outil sous son nom nu et rend l'enveloppe OPSYS telle quelle. Détail,
constat et limites : `docs/architecture/MOBILE.md`, « Nom d'un outil de l'app au moteur ».

- Ajouté : `src/agents/opsys-device-mcp-target.ts` et son test `src/agents/opsys-device-mcp-target.test.ts`
  (deux vrais serveurs MCP stdio), `src/gateway/tools-invoke-http.opsys-device-mcp.test.ts`.
- Modifiés :
  - `src/gateway/opsys-device-roles.ts` : `serveur` dans l'autorisation, refus `server_unknown` ;
  - `src/gateway/tools-invoke-shared.ts` : `invokeOpsysDeviceTool` (un appareil autorisé ne traverse plus
    la liste d'outils du core), `buildOpsysMcpCallMeta` (les clés `_meta` en un seul endroit) ;
  - tests d'origine complétés : `src/gateway/opsys-device-roles.test.ts`,
    `src/gateway/tools-invoke-http.opsys-roles.test.ts`,
    `src/gateway/tools-invoke-http.device-token-auth.test.ts`.
- Routage vitest : `test/vitest/vitest.gateway-server-paths.mjs` (le test HTTP appaire un vrai appareil :
  projet `gateway-database-workers`), et `test/opsys-tests-cibles.txt`.

### T1.4-c5 : l'app apprend sa personne et son rôle nommés (`GET /opsys/identite`)

Un appareil appairé (jeton d'appareil, attribué à une personne OPSYS) lit sa personne et son rôle nommé
(`admin`, `employee`, `seller`) par `GET /opsys/identite`. Le `deviceId` vient du jeton vérifié, par la même
chaîne d'authentification que `/tools/invoke` ; la personne et le rôle viennent de `opsys/appareils.json`,
par le même code que la porte d'outils (`resolveOpsysDeviceIdentity`). Rien de ce que l'app envoie n'est
lu ; le secret partagé, un appareil sans attribution et un rôle que `roles.json` ne déclare pas n'ont
aucune identité. Une route plutôt qu'un champ de `hello-ok` : l'attribution vient après l'approbation
native, et la trame est gelée. Détail : `docs/architecture/MOBILE.md`, « Identité de l'appareil ».

`opsys-mobile` (`GATEWAY_CLIENT_IDS.OPSYS_MOBILE`, T1.4-c4) est maintenant envoyé par l'app. Il n'est
volontairement PAS dans `isNativeAppUiClient` : voir « Identifiant de client » dans `MOBILE.md`.

- Ajoutés : `src/gateway/opsys-device-identity-http.ts` et ses tests `src/gateway/opsys-device-identity-http.test.ts`
  (vrai appairage, vrais fragments), `src/gateway/server-http.opsys-device-identity.test.ts` (route montée),
  `src/gateway/opsys-mobile-trust.test.ts` (identifiant valide, hors de la classe « app native »).
- Modifiés :
  - `src/gateway/opsys-device-roles.ts` : `resolveOpsysDeviceIdentity`, et une résolution commune
    `resolveOpsysDevice` (l'appareil, puis le rôle connu) que la porte d'outils réutilise, sans changer ses
    refus. Durcissement : un `deviceId` nommé comme un membre d'`Object.prototype` (`constructor`) ne lit plus
    l'état hérité (`device_unknown`, avant : `role_unknown`) ;
  - `src/gateway/server-http.ts`, `src/gateway/server-http-modules.ts` : une étape de route et un module
    chargé à la demande ;
  - `packages/gateway-protocol/src/client-info.ts` : commentaire seulement ;
  - test d'origine complété : `src/gateway/opsys-device-roles.test.ts`.
- Routage vitest : `test/vitest/vitest.gateway-server-paths.mjs` (`opsys-device-identity-http.test.ts` :
  projet `gateway-database-workers`, appairage réel) et `test/opsys-tests-cibles.txt`. Les deux autres
  fichiers neufs sont routés par leur nom : `server-http.opsys-device-identity.test.ts` vers
  `gateway-server`, `opsys-mobile-trust.test.ts` vers `gateway-core` (sans « client » ni « server » dans le
  nom).

### T0.10 : le core lance et surveille le moteur métier Python

Le Gateway lance `uv run opsys-mcp --http` (`src/opsys/serveur_mcp.py`), sonde `GET /sante`, le
relance avec un recul exponentiel borné et l'arrête avec lui. **Désactivé par défaut** : sans
`<dossier de config>/opsys/metier.json` portant `"actif": true`, rien ne change au comportement
amont. Le fichier est lu hors du schéma Zod (comme `roles.json`), car le schéma racine est strict.
Format : commentaire d'en-tête de `src/gateway/opsys-metier-config.ts`.

Réutilisé plutôt que réécrit :
- `ProcessSupervisor` (`src/process/supervisor`) : lancement, relais de sortie, arrêt de l'arbre
  de processus (même usage que `src/gateway/desktop/managed-linux.ts`) ;
- `RetrySupervisor` (`packages/retry`) : recul exponentiel (même usage que
  `src/gateway/server-channels.ts`) ;
- registre de masquage des secrets (`src/logging/secret-redaction-registry.ts`) ;
- sidecar de durée de vie du Gateway (`GatewayPostReadySidecarHandle`).

Une seule authentification : le Gateway lit `OPSYS_MCP_JETON` (ou en génère un de 256 bits) et
le passe au moteur par l'environnement du processus enfant, jamais par argument, fichier ni
journal. Les en-têtes `mcp.servers.opsys_mN` lisent la même variable. L'enfant ne reçoit pas les
secrets du Gateway (`OPENCLAW_*`, clés de fournisseurs) : liste blanche dans
`src/gateway/opsys-metier-env.ts`, extensible par la clé `env` de `metier.json`.

- Ajoutés : `src/gateway/opsys-metier-config.ts`, `src/gateway/opsys-metier-env.ts`,
  `src/gateway/opsys-metier-status.ts`, `src/gateway/opsys-metier-supervisor.ts`, et leurs tests
  `src/gateway/opsys-metier-{config,env,supervisor}.test.ts`.
- Modifiés :
  - `src/gateway/server-lifetime-sidecars.ts` : démarre le superviseur et publie son arrêt
    (six lignes, hors Gateway de test minimal) ;
  - `src/gateway/server-methods/health.ts` et `src/gateway/health/types.ts` : la charge des RPC
    `health` et `status` porte `opsysMetier` tant que le moteur est supervisé ;
  - tests d'origine complétés : `src/gateway/server-lifetime-sidecars.test.ts`,
    `src/gateway/server-methods/health.owner-routing.test.ts`.
- Côté Python : `GET /sante` sans jeton ni donnée métier dans `src/opsys/serveur_mcp.py`, et le
  journal d'accès d'uvicorn ignore cette sonde.
- Surface consommée ajoutée au tableau ci-dessous : `opsys/metier.json`.

### T3.3-suite : moteur de contexte OPSYS (PREFLIGHT et POSTFLIGHT)

Un `ContextEngine` du fork, choisi par `plugins.slots.contextEngine: "opsys"`. Il n'ajoute que deux
choses au tour d'un agent de département :
- **PREFLIGHT**, dans `assemble()` : il demande à M10 le paquet de l'affaire
  (`m10_paquet_contexte_affaire`, T0, budget calculé par M10) et le rend en `systemPromptAddition`, que le
  lanceur préfixe déjà au prompt système. L'affaire est la ligne `affaire_id: <lead_id>` de la demande ;
- **POSTFLIGHT**, dans `afterTurn()` : il remet à M10 ce que les outils listés ont fait pendant le tour
  (`m10_deposer_faits_candidats`, T1 en N2) : outil, résultat, code. Jamais le texte du modèle.

**Désactivé par défaut** : sans `<dossier de config>/opsys/contexte.json` portant `"actif": true`, le moteur
est transparent (comportement du moteur « legacy »). Le fichier est lu hors du schéma Zod, comme `roles.json` et
`metier.json`, et généré par `src/opsys/openclaw.py` (`opsys openclaw configurer --contexte-entreprise
AGENT[:OUTIL,OUTIL]`), qui écrit dans le même appel `plugins.slots.contextEngine`. Format : commentaire
d'en-tête de `src/context-engine/opsys-contexte-config.ts`.

Fail-closed et sans blocage. Moteur injoignable, plus lent que `delai_ms`, paquet invalide ou hors budget,
aucune affaire dans la demande : le tour continue SANS paquet, porte le marqueur « contexte d'entreprise
indisponible » et laisse une ligne du journal (sous-système `opsys-contexte`). Un paquet n'est jamais
inventé, réparé ni tronqué : il est refusé en entier. `assemble()` et `afterTurn()` ne lèvent jamais, car le
registre mettrait en quarantaine un moteur qui lève.

Réutilisé plutôt que réécrit :
- `LegacyContextEngine` (`legacy.ts`) : l'assemblage des messages et l'ingestion restent les siens ;
- `delegateCompactionToRuntime` (`delegate.ts`) : la compaction reste celle du lanceur ;
- `resolveMcpTransport`, `connectMcpClient`, `disposeMcpClient` (`src/agents/mcp-*.ts`) : un appel MCP borné,
  avec l'URL et l'en-tête `Bearer ${OPSYS_MCP_JETON}` de `mcp.servers.opsys_m10` ;
- `buildMemorySystemPromptAddition` (`delegate.ts`) : le lanceur retire la section mémoire (outils de
  `memory-core`, citations) du prompt système pour tout moteur autre que « legacy » et attend que le moteur la
  rajoute. Le moteur `opsys` la rajoute toujours, même sans `contexte.json` actif, pour que les agents gardent
  leur mémoire native (ADR-0010, couche A). Écart connu : en mode de prompt minimal (sous-agents), le lanceur
  ne l'aurait pas mise ; le moteur ne connaît pas le mode et la met ;
- le mécanisme d'enregistrement `registerContextEngineForOwner` et le fournisseur de session
  `parseAgentSessionKey` ; le journal `createSubsystemLogger`.

Pourquoi `src/context-engine/` et non `extensions/opsys-context-engine` (l'ordre de `AGENTS.md` préfère une
extension, l'ADR-0010 la nommait) : une extension n'importe que `openclaw/plugin-sdk/*`, qui n'expose aucun
client MCP ; elle aurait embarqué le sien (dépendance propre, donc un importeur neuf dans `pnpm-lock.yaml`) ou
réécrit le transport. Chaque extension figure de plus dans des inventaires tenus à la main que le bac à sable
ne peut pas régénérer (`extensions/ICON_SOURCES.md`, `test/vitest/vitest.extension-misc-paths.mjs`,
`pnpm-lock.yaml`). La greffe est isolée (six fichiers neufs et une ligne dans `init.ts`) : elle passe en
extension avec les mêmes fichiers quand un client MCP entre dans le SDK.

- Ajoutés : `src/context-engine/opsys-contexte-{config,paquet,depot,mcp,engine}.ts`,
  `src/context-engine/opsys-contexte.registration.ts`, et leurs tests
  `src/context-engine/opsys-contexte-{config,paquet,depot,engine}.test.ts`,
  `src/context-engine/opsys-contexte-mcp.wire.test.ts`, `src/context-engine/opsys-contexte.registration.test.ts`
  (fixtures : `src/context-engine/opsys-contexte.test-support.ts`, dont le paquet est la sortie réelle de M10).
- Modifiés : `src/context-engine/init.ts` (`ensureContextEnginesInitialized` enregistre aussi le moteur, sous
  l'identifiant `opsys`, propriétaire « core » ; sans le slot, rien ne le choisit) et
  `test/opsys-tests-cibles.txt`.
- Côté Python : `m10_paquet_contexte_affaire` (T0, existait) et `m10_deposer_faits_candidats` (T1 en N2, fermé
  aux appareils), `openclaw.generer(contexte_entreprise=...)`.
- Surfaces consommées ajoutées au tableau ci-dessous : `opsys/contexte.json`, `plugins.slots.contextEngine`.

### T3.3-suite-b : garde d'action N3+, affaire de la session, paquet vérifié pour l'agent

Trois ajouts au moteur de contexte ci-dessus, dans les mêmes fichiers plus un nouveau. Rien n'est exécuté dans
le bac à sable de développement : la CI (`tests` et `tests-opsys`) fait foi.
- **Garde d'action** (`src/context-engine/opsys-contexte-garde.ts`, nouveau). Le moteur enregistre, par clé de
  session et à chaque tour (`assemble()` avec prompt), ce que son PREFLIGHT a trouvé : paquet prêt et nombre de
  signaux critiques ouverts, ou contexte indisponible et pourquoi. `checkOpsysContexteToolCall` en tire la
  décision pour un outil OPSYS de niveau N3 ou plus (niveau lu dans `contexte.json`, `niveaux`) : refusé si le
  contexte était indisponible, jamais évalué, périmé (15 minutes) ou porte un signal ouvert ; jamais rien d'autre.
  Inactif tant que `contexte.json` ne l'est pas.
- **Appel du garde : greffe dans `runBeforeToolCallHook`.** Un moteur de contexte ne peut pas bloquer un
  outil : `before_tool_call` appartient au lanceur de hooks de plugins et aux politiques d'outils de confiance
  (`src/agents/agent-tools.before-tool-call.policy.ts`) ; `ContextEngine` (`src/context-engine/types.ts`) n'a
  aucune méthode de ce genre. La greffe (une douzaine de lignes, marquée OPSYS) appelle
  `checkOpsysContexteToolCall({ toolName, sessionKey, agentId })` juste après l'admission de boucle et rend un
  `HookOutcome` `veto` marqué `genericDecision`, comme elle ; `deniedReason` est omis (champ optionnel) pour ne
  pas élargir l'union `HookBlockedReason`. Inactif sans `contexte.json` actif (fichier absent → garde
  inactif). Coût : une lecture synchrone de `contexte.json` par appel d'outil. Les tests d'origine voisins
  (`agent-tools.before-tool-call.decision`, `.e2e`, `.embedded-mode`) sont dans `test/opsys-tests-cibles.txt`.
  À vérifier en CI : `HookContext.sessionKey` est la clé que reçoit `assemble()`.
- **Affaire lue dans la session** (`opsys-contexte-engine.ts`, `opsys-contexte-config.ts`). Un agent réglé
  `"affaire": "session"` dans `contexte.json` demande à M10 l'affaire liée à sa clé de session
  (`m10_affaire_de_la_session`), pour le paquet et pour le dépôt POSTFLIGHT, et ne lit jamais le texte de la demande.
  Le réassemblage sans prompt que le lanceur fait après chaque résultat d'outil (`installContextEngineLoopHook`,
  `src/agents/embedded-agent-runner/tool-result-context-guard.ts`) ne compose plus rien.
- **Paquet vérifié** (`opsys-contexte-paquet.ts`). Le core refuse, sans réparer, un paquet sans décompte des
  signaux, dont un signal n'a pas un état et un auteur cohérents, dont un fait n'a pas un niveau de
  confidentialité admissible (jamais un niveau fermé), ou dont le bloc de confidentialité ne nomme pas l'agent
  demandé. L'agent vient de la clé de session ; M10 filtre le paquet pour lui.
- Ajoutés : `src/context-engine/opsys-contexte-garde.ts` et `opsys-contexte-garde.test.ts`.
- Modifiés : `src/context-engine/opsys-contexte-{config,paquet,engine}.ts` et leurs tests,
  `opsys-contexte.test-support.ts` (les paquets sont la sortie réelle de M10 ; `tests/test_openclaw_contexte.py` le
  vérifie), `test/opsys-tests-cibles.txt`.
- Côté Python : `openclaw.generer(affaire_par_session=...)` écrit `niveaux`, `outil_affaire` et `affaire` par agent ;
  M10 (`signaux.py`, `liaison.py`, `confidentialite.py`, `humain.py`).
- Surface consommée : `opsys/contexte.json` porte en plus `niveaux`, `outil_affaire` et, par agent, `affaire`.

## Sécurité

Il n'y a plus de mises à jour automatiques. Une veille mensuelle des avis de sécurité d'OpenClaw
décide, correctif par correctif, s'il faut le reporter à la main. Chaque report est tracé dans ce
fichier.

## Surfaces consommées par la couche Python (transitoire)

`src/opsys/openclaw.py` génère encore la configuration du core de l'extérieur. Ce contrat vient de
l'ancien `core/UPSTREAM.md` (ADR-0007) et reste valable tant que les greffes natives ne l'ont pas
remplacé (ADR-0008, conséquences). Toute modification de ces surfaces dans `core/` doit mettre à
jour `src/opsys/openclaw.py` et ses tests dans le même commit.

| Surface | Usage OPSYS | Source dans le fork |
|---|---|---|
| `$include` (tableau, fusion profonde, chemins sous le dossier de config) | fragments `opsys/{models,agents,mcp}.json` | `src/config/includes.ts` |
| `agents.entries.<id>.{name,workspace,model}` | un agent par département | `src/config/zod-schema.agents.ts` |
| `models.providers.<id>.{baseUrl,apiKey,api:"openai-completions",request.allowPrivateNetwork,models[{id,name}]}` | un fournisseur par département vers LiteLLM, clé virtuelle dédiée | `src/config/zod-schema.core.ts` |
| `mcp.servers.opsys_mN.{url,transport:"streamable-http",headers}` | un serveur par département, `url` = `http://opsys:8765/mcp/<id>` : l'appelant est fixé par l'URL, jamais par le modèle | `src/config/zod-schema.mcp-server.ts` |
| `agents.entries.<id>.tools.deny` (globs `opsys_mN__*`) | chaque agent refuse les outils MCP des 9 autres départements | `src/config/zod-schema.agents.ts` |
| `agents.defaults.contextPruning.{mode:"cache-ttl",ttl}` | élagage des anciens résultats d'outils après inactivité | `src/config/zod-schema.agent-defaults-base.ts` |
| Substitution `${VAR}` | clés `OPSYS_CLE_Mx`, `OPSYS_MCP_JETON` | `src/config/env-substitution.ts` |
| `automations add --cron --tz --session isolated --agent --message` | planifications des départements | `src/cli/cron-cli.ts` |
| Espace de travail : `SOUL.md`, `AGENTS.md`, `skills/` | identité, règles, procédures | `src/agents/` (amorçage de l'espace de travail) |
| `opsys/metier.json` (hors schéma Zod) | active et règle le superviseur du moteur métier (T0.10) ; `openclaw.py` ne l'écrit pas encore | `src/gateway/opsys-metier-config.ts` |
| `opsys/roles.json` (hors schéma Zod) | `roles` : outils permis par rôle d'appareil ; `serveurs` : le serveur MCP de chacun (T1.4-c6). Noms d'outils nus | `src/gateway/opsys-device-roles.ts` |
| `opsys/appareils.json` (hors schéma Zod) | appareil -> personne et rôle OPSYS (T1.4-c2, c4) ; rendu aussi à l'appareil par `GET /opsys/identite` (T1.4-c5). Format inchangé | `src/gateway/opsys-device-roles.ts` |
| `opsys/contexte.json` (hors schéma Zod) | active et règle le moteur de contexte OPSYS (T3.3-suite) ; écrit par `openclaw.py` (`contexte_entreprise`, `affaire_par_session`) ; porte aussi `niveaux` (niveau N de chaque outil, pour le garde), `outil_affaire` et l'`affaire` de chaque agent (T3.3-suite-b) | `src/context-engine/opsys-contexte-config.ts` |
| `plugins.slots.contextEngine` | choisit le moteur `opsys` quand `contexte.json` est actif ; absent sinon (moteur « legacy ») | `src/config/zod-schema.root-shape.ts`, `src/context-engine/registry-selection.ts` |
