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
`metier.json`, et généré par `src/opsys/openclaw.py` (`opsys metier openclaw configurer --contexte-entreprise
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
- **Preuve de la greffe** : `src/agents/agent-tools.before-tool-call.opsys-contexte.test.ts` appelle la vraie
  `runBeforeToolCallHook` avec un vrai `contexte.json` et le vrai magasin d'état (veto sans état, avec signal
  ouvert, indisponible ou périmé ; aucun veto avec un état sain, hors OPSYS, N0 à N2 ou sans `contexte.json`).
  Routé vers `agents-core` (`src/agents/*.test.ts`) et listé dans `test/opsys-tests-cibles.txt` ; jamais exécuté
  dans le bac à sable, la CI (`tests-opsys`) fait foi.
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

### T4.18-b : forme d'affaire commune, blocs `affaire` et `consolidation` du paquet

Trois ajouts au moteur de contexte, dans les mêmes fichiers. Rien n'est exécuté dans le bac à sable de développement :
la CI (`tests` et `tests-opsys`) fait foi. Le TypeScript est relu à la main, sa logique est transcrite en Python
pour vérifier les attentes des tests, et les fixtures sont comparées clé par clé à la sortie réelle de M10.
- **Forme d'affaire** (`opsys-contexte-paquet.ts`). `AFFAIRE_ID` et `AFFAIRE_LINE` admettent l'opportunité
  `<lead>~opp~<wct_id>` que M2 ouvre quand un client revient : 64 + 5 + 128 caractères au plus, lettres, chiffres et `._:-`
  (le tilde n'existe que dans `~opp~`). Le motif est celui de M10 (`affaire.py`, `FORME_AFFAIRE`), mot pour mot ; un test
  du socle compare les deux textes. `isOpsysAffaireId` est exporté. Les deux côtés rejouent la MÊME liste de cas, un
  fichier JSON partagé (`opsys-contexte.affaires.json`). Une chaîne d'opportunités reste refusée (limite dite).
- **Paquet vérifié, deux blocs additifs.** Le core valide `affaire` (`connue`, `origine_recue`, `origine`, `verdict` : un
  vocabulaire fermé dont l'incohérence refuse le paquet, un type d'origine qui n'est jamais un texte libre, une affaire
  inconnue sans événement ni signal) et `consolidation` (au plus dix jours de CETTE affaire, sans doublon, une liste qui
  correspond à son compte, jamais plus de jours que d'événements omis par la couche). Il rend une phrase de sa plume sur l'affaire,
  avant les couches, et une ligne sous les événements pour les jours à consolider ; le budget de M10 ne compte pas ce cadrage.
  Les quatre couches et leur ordre ne changent pas.
- **Moteur** (`opsys-contexte-engine.ts`). Une affaire inconnue est journalisée (`opsys-contexte`, niveau info). Le garde
  ne change pas : une affaire inconnue ne bloque pas un outil N3 ou plus (décision laissée au propriétaire, ADR-0010).
- Ajoutés : `src/context-engine/opsys-contexte-affaire.test.ts` et `src/context-engine/opsys-contexte.affaires.json`.
- Modifiés : `src/context-engine/opsys-contexte-{paquet,engine}.ts` et leurs tests, `opsys-contexte.test-support.ts` (cinq
  paquets, dont l'opportunité et un historique tronqué de lead venu d'un SMS), `test/opsys-tests-cibles.txt`.
- Côté Python : `m10_memoire/affaire.py` (forme commune), `etapes.py` (l'étape qui ouvre une affaire), `amont.py`, `paquets.py`,
  `consolidation.py`, `faits_candidats.py`, `liaison.py`, `outils.py` ; `tests/test_openclaw_contexte.py` épingle le contrat.
- Ce que seule la CI prouve : la construction (`core.yml`, job `construction`), les trois fichiers de tests du core
  (`tests-opsys`), et que `HookContext.sessionKey` reste la clé que reçoit `assemble()` (déjà à vérifier depuis T3.3-suite-b).

## Renommage, lot 1 : la marque visible devient OPSYS (T0.7)

Décisions : [R14](../docs/research/R14-renommage-core.md). On renomme ce que l'utilisateur voit, jamais l'API interne
du fork (`openclaw/plugin-sdk/*`, `@openclaw/*`, `OPENCLAW_*`, `openclaw.plugin.json`). Le nom de la commande
(`openclaw`), le dossier `~/.openclaw` et les services système restent pour les lots 2 à 4. `LICENSE`, `NOTICE`,
`THIRD_PARTY_NOTICES.md` et ce fichier ne changent pas (avis MIT). Rien ne s'exécute dans le bac à sable : la CI
(`tests` et `tests-opsys`) fait foi. Le lot se livre en trois commits.

Correction après la CI core 28 : `test/scripts/openclaw-cross-os-release-checks.test.ts` entre dans les cibles du lot
(son script lit la bannière). Un seul de ses 311 cas échouait : « keeps release cross-OS OpenAI smoke on GPT-5.6 Luna »
lisait `.github/workflows/openclaw-cross-os-release-checks-reusable.yml` et `openclaw-release-checks.yml`, deux workflows
de publication de l'amont retirés avec `.github/` à l'élagage (plus haut). Ce cas vérifiait un fichier absent du fork
et ne pouvait pas passer : il est retiré, les 310 autres restent.

Correction après la CI core 29 : `src/gateway/server.plugin-http-auth.test.ts` entre aussi dans les cibles (titre du
tableau de bord). Son cas « allows unauthenticated Mattermost slash callback routes » attendait 200 sur la route de
commande de Mattermost ; il a reçu 401. L'exemption de cette route vivait dans l'extension `mattermost`, retirée à
l'élagage : aucun code du fork ne lit plus `channels.mattermost.commands.callbackPath`. Le cas vérifie maintenant ce
que fait le fork (401, la route reste derrière l'authentification du Gateway), en gardant l'assertion sur les autres
canaux.

### Commit 1 : interface et locales

- Modifiés : `ui/index.html` (titre « OPSYS Control », écran de secours), `ui/public/manifest.webmanifest`, les 114
  lignes de valeurs anglaises de `ui/src/i18n/locales/en*.ts` (les clés ne bougent pas) et les libellés en dur de la
  coque : barre du haut, écran de connexion, badge du profil, nom d'espace par défaut, nom d'assistant par défaut du
  compositeur, étiquette du moteur `openclaw` du sélecteur de modèle, suffixe du titre de fenêtre
  (`app-navigation.ts`), message d'installation des notifications (`web-push.runtime.ts`).
- Laissés tels quels, faute de pouvoir les régénérer ou parce qu'ils désignent l'amont : la ligne de licence de la page
  À propos (© OpenClaw Foundation), la carte de la communauté Discord d'OpenClaw et les liens de la page À propos, le
  lien de dépannage `docs.openclaw.ai` de l'écran de secours, et les textes d'aide de la configuration (`configHints.*`,
  qui viennent de `src/config/schema.*.ts` et que fige `docs/.generated/config-baseline.sha256`).
- **`fr-CA`** : locale neuve, dérivée de `fr` (`ui/src/i18n/locales/fr-CA.ts`, `.i18n/fr-CA.{tm.jsonl,meta.json}`,
  glossaire). Seuls les écarts québécois sont ajustés : « courriel » pour « e-mail », pas d'espace avant `?`, `!` et
  `;` (316 segments), et les étiquettes de langue. Les autres écarts possibles (infonuagique, fermer la session) sont
  à faire relire par un locuteur québécois.
- **`fr-CA` par défaut** : `PRODUCT_DEFAULT_LOCALE` (`ui/src/i18n/lib/registry.ts`). `en` reste le catalogue source,
  embarqué et repli de toute clé manquante : un catalogue français embarqué ferait exploser le budget de démarrage.
  `fr-CA` se charge à la demande comme les 20 autres locales, donc aucun octet de plus au démarrage. Langue du
  navigateur : `fr`, `fr-CA` et tout `fr-*` sauf `fr-FR`, `fr-BE`, `fr-CH`, `fr-LU`, `fr-MC` donnent `fr-CA` ; ces cinq
  donnent `fr` ; `en*` donne `en` ; une langue sans catalogue (ou vide) donne `fr-CA`.
- **Mémoires de traduction** : les 20 locales existantes ont été mises à jour à la main (108 entrées chacune : `text`,
  `text_hash`, `cache_key`, traduction avec OPSYS) et reçoivent la nouvelle clé `languages.frCA`. Le script Python qui
  les a réécrites reproduit l'algorithme de `scripts/control-ui-i18n.ts` (hachage, clé de cache, ordre) : vérifié sans
  écart sur les 174 616 entrées d'origine, et `sourceHash` sur l'ancienne valeur. `sourceHash`, `totalKeys` (9 841) et
  `catalog-fallbacks.json` sont à jour. Sur un poste Node, `pnpm ui:i18n:sync --write` ne doit rien changer d'autre que
  `generatedAt`, et aucun fournisseur de traduction n'est nécessaire.
- **Glossaires** : `OPSYS → OPSYS` remplace `OpenClaw → OpenClaw` dans les 21 glossaires existants (dont `sv`, sans locale),
  copié pour `fr-CA`, et dans `DEFAULT_GLOSSARY` de `scripts/control-ui-i18n.ts`. Le pipeline ne réinjecte donc plus la marque amont.
- **Correctif de chaîne de construction** : le chunk `fr-CA-<hash>.js` satisfaisait aussi le motif `fr-` de la locale
  `fr` (`ui/vite.config.ts`, `scripts/check-control-ui-performance.mts`). On teste maintenant la locale la plus longue
  d'abord, sinon le contrôle de performance comptait deux chunks pour `fr`.
- Le contrôle `<title>OPSYS Control</title>` des fumées inter-OS (`scripts/lib/cross-os-release-checks`,
  `scripts/e2e/parallels/macos-smoke.ts`) et le test qui le fige suivent le nouveau titre.

### Commit 2 : invites système et voix

Le modèle s'annonce et parle d'OPSYS. Règle : on change le texte d'identité et les consignes que le modèle lit, jamais
un marqueur de protocole que le code reconnaît ou que les transcriptions existantes contiennent déjà.

- **Invite système de l'agent** : `src/agents/system-prompt.ts` (« You are a personal assistant running inside OPSYS. »,
  section « ## OPSYS Control », mise à jour, fichiers de projet), ses fragments (`system-prompt-messaging.ts`,
  `system-prompt-tool-list.ts`, `prompt-surface.ts`, `delegation-guidance.ts`, `subagents/spawn/subagent-system-prompt.ts`,
  `realtime-bootstrap-context.ts`), l'invite du harnais de code (`agents/sessions/system-prompt.ts`), les deux
  vérificateurs de sécurité (`exec-auto-reviewer.prompt.ts`), l'invite d'un agent de claw (`claws/project.ts`) et
  `LOCAL_MODEL_RUN_SYSTEM_PROMPT` (`cli/capability-cli/model.ts`).
- **Agent système** : `src/system-agent/assistant-prompts.ts` (trois invites, étiquette du rôle dans l'historique,
  références « OPSYS docs » et « OPSYS source »). La persona du crabe ermite reste : c'est une décision de ton, pas de
  marque.
- **Voix** : `src/gateway/talk/session-config.ts`, `realtime-run-control.ts`, `relay/{forced-consults,operations,session-create,provider-results}.ts`,
  `src/talk/agent-consult-{tool,runtime}.ts`, `agent-run-control{,-shared}.ts`, `fast-context-runtime.ts`,
  `extensions/voice-call` (invites, contexte d'agent, consignes de délégation), `extensions/openai`
  (`realtime-quicksilver-instructions.ts`), le fragment Telegram `agent-prompt.ts` et, côté navigateur,
  `ui/src/pages/chat/talk/{gateway-relay,shared}.ts`. Les phrases que la voix prononce disent OPSYS.
- **Consignes de réparation** : `src/commands/triage-prompt.ts`, `src/infra/update-repair-agent.ts`,
  `src/skills/workshop/learn-prompt.ts`.
- Laissés tels quels, faute de pouvoir les changer sans casser la reconnaissance du texte ou pour un lot suivant :
  - les marqueurs : `[OpenClaw heartbeat poll]` et voisins (`auto-reply/heartbeat.ts`), « OpenClaw runtime context
    (internal): » et « OpenClaw runtime event » (`agents/internal-runtime-context.ts`, `internal-events.ts`,
    `agent-steering-queue.ts`), l'en-tête « OpenClaw plugin-injected system context » (`hook-system-context-boundary.ts`),
    « Internal OpenClaw voice … result » et « Speak this exact OpenClaw … » (`talk/exact-speech-protocol.ts`,
    `agent-run-control-shared.ts`, `voice-call/src/webhook/realtime-handler.ts`), le marqueur de reprise
    (`cli-runner/session-history.ts`, `reseed-envelope.ts`) et `[OpenClaw interruption]` (`acp/`) ;
  - le mot d'éveil vocal `OpenClaw` (`talk/realtime-session-policy.ts`) : c'est un comportement, pas un texte ;
  - les descriptions d'outils (`tool-catalog.ts`, `tools/*.ts`, `mcp/channel-tools.ts`) et les messages d'erreur ;
  - les adresses `docs.openclaw.ai` et `github.com/openclaw/openclaw` du bloc « Docs / Source » de l'invite, qui
    désignent l'amont ;
  - les commandes `openclaw …` citées dans les invites (nom de la commande : lot 2).
- Tests mis à jour : ceux qui figent ces phrases (`system-prompt*.test.ts`, `prepare.test.ts`,
  `helpers.system-prompt.test.ts`, les tests de voix de `src/gateway/talk`, `src/talk`, `extensions/voice-call`,
  `extensions/openai`, `ui/src/pages/chat/talk`). Les fixtures qui répètent un texte serveur sans dépendre du code sont
  laissées.

### Commit 3 : bannière, notifications et pages partagées

Ce que l'utilisateur lit sur son terminal, sur son téléphone et dans un lien partagé dit OPSYS. Le nom de la commande
reste `openclaw` (lot 2) : la bannière ne le contient pas.

- **Bannière et `--version`** : `src/cli/banner.ts`, `claw-banner.ts` (mot-symbole OPSYS, largeurs recalculées),
  `tagline.ts` (accroche par défaut et les phrases qui nomment la marque), `program/help.ts`, `src/entry.version-fast-path.ts`,
  `openclaw.mjs` (lanceur), `src/status/status-message.ts` (ligne de version). La sortie de `--version` devient
  `OPSYS <version> (<commit>)`.
- **Lecteurs de la bannière** : la ligne de version est analysée par des scripts. Ils acceptent désormais `OpenClaw`
  (ancienne version encore installée) ET `OPSYS` : le contrôle de version de l'enrôlement d'un nœud
  (`extensions/crabbox/src/crabbox-worker-node-enrollment.ts`) et les expressions des fumées Parallels
  (`scripts/e2e/parallels/{filesystem,windows-smoke,smoke-common,powershell}.ts`). Un invité qui n'a pas été reconstruit
  ne fait donc pas échouer la fumée.
- **Notifications** : titres et corps des notifications Web Push (`ui/public/sw.js`, `gateway/server-methods/push.ts`,
  `approval-web-push.ts`, `event-web-push.ts`), du réveil de nœud (`server-methods/nodes.wake.ts`), de l'alerte
  d'approbation iOS (`infra/push-apns-payloads.ts`) et de la commande `nodes push` (`cli/nodes-cli/register.push.ts`).
- **Pages partagées** : `gateway/control-ui-share.ts` (titre, description, `og:site_name`, carte d'aperçu),
  `control-ui-public-session-render.ts` (titre, en-tête, étiquette de l'assistant, `og:site_name`),
  `portals/portal-http-proxy.ts` (page « portail privé »), `mcp-app-standalone.ts` (titre de la page).
- **Mini-app Telegram** : description de la commande `/dashboard`, réponse et page de la mini-app
  (`extensions/telegram/src/miniapp/{command,page}.ts`).
- **Nom de découverte** : `formatBonjourInstanceName` (`gateway/server-discovery.ts`) annonce « OPSYS » ou
  « <machine> (OPSYS) » ; un nom qui contient déjà `opsys` ou `openclaw` reste tel quel (nom choisi par l'utilisateur).
  Le type de service `_openclaw-gw._tcp` est un protocole : il ne change pas.
- Laissés tels quels :
  - le texte alternatif « OpenClaw logo and lobster mascot » de la carte d'aperçu : l'image est encore le logo de
    l'amont (à remplacer avec le lot des icônes, pas dans ce lot) ;
  - le bouton Slack « Open in OpenClaw » (`extensions/slack/src/progress-blocks.ts`) : il mène à `team.openclaw.ai`, un
    service de l'amont ; les pages de l'extension navigateur (`extensions/browser/chrome-extension/*.html`,
    `bridge-server.ts`) : leurs tests tournent dans Chromium, hors de portée ici ; les deux vont à un lot d'extensions ;
  - les fixtures de tests qui répètent un texte serveur sans dépendre du code (`widearea-dns.test.ts`,
    `server-discovery-runtime.test.ts`, qui simule `formatBonjourInstanceName`) ;
  - les noms de variables, de fonctions et de types (`OpenClawConfig`, `runOpenClaw…`), l'API interne.
- Tests mis à jour ou ajoutés : bannière, accroches, aide, ligne de version, lanceur (`openclaw-launcher-version.e2e`),
  gabarits Parallels, enrôlement crabbox (nouveau cas : ancienne bannière acceptée), notifications (nouveaux cas dans
  `push.test.ts` et `service-worker-cache.test.ts`), pages partagées et nom de découverte (nouveaux cas). Les fichiers
  hors `test:fast` rejoignent `test/opsys-tests-cibles.txt` ; `test/openclaw-launcher.e2e.test.ts` (une expression
  élargie) suit la voie e2e.

## Renommage, lot 2 : une seule commande `opsys` (T0.7)

Décisions : [R14](../docs/research/R14-renommage-core.md), décision 3. `opsys` est la commande du core, `openclaw` en reste
l'alias, et la CLI du moteur Python (qui s'appelait `opsys`) est `opsys metier <commande>`, son exécutable étant
`opsys-metier`. Rien ne s'exécute dans le bac à sable : la CI (`tests`, `tests-opsys`, job `installateur`, `e2e-core`) fait foi.

- **Binaire** : `package.json`, `bin` : `opsys` et `openclaw` pointent tous deux sur `openclaw.mjs`. Le fichier du lanceur
  ne change pas de nom (des centaines de chemins le désignent) ; `isMainModule` compare les chemins réels, un lien `opsys`
  démarre donc le même point d'entrée. Les enveloppes de l'installateur, elles, appellent toujours `node core/openclaw.mjs`.
- **`opsys metier <commande>`** : `src/cli/opsys-metier-argv.ts` (reconnaît `metier` et les seize anciens noms des
  commandes du moteur, depuis l'argv brut, options racines comprises) et `src/cli/opsys-metier-cli.ts` (lance le moteur).
  `src/entry.ts` (`runMainOrRootHelp`) leur répond AVANT les chemins d'aide rapide et Commander, comme il le fait pour le
  relais de crochets natifs : les arguments (`--help`, `--config-dir`, `--par`...) appartiennent au moteur. `metier` n'est
  volontairement PAS une commande Commander : un nouveau nom racine exigerait le catalogue des commandes, l'arbre de
  complétion et leurs tests croisés ; l'aide racine le présente par un exemple (`program/help.ts`).
- **Où est le moteur** : le core ne devine aucun chemin. Il lit `<dossier de config>/opsys/metier.json`, celui que le
  superviseur T0.10 lit déjà (`resolveOpsysDir`), clé `commande_cli` (liste, arguments ajoutés à la fin), que
  `opsys metier instance initialiser` écrit : le même interpréteur que `commande`, `-m opsys.cli`. Sans `commande_cli` ni
  `commande`, la valeur par défaut reprend celle du superviseur (`uv run --project <dossier> opsys-metier`) ; avec une
  `commande` personnalisée et sans `commande_cli`, le core refuse et dit de relancer l'installateur. `"actif": true` n'est
  pas exigé : la CLI ne dépend pas de la supervision. La clé est documentée dans l'en-tête de `opsys-metier-config.ts`
  (un test Python compare les clés écrites à cet en-tête). Aucune autre modification de ce fichier.
- **Lancement** : `spawnSync` héritant du terminal (`stdio: "inherit"` : les mots de passe demandés sans écho marchent),
  dans le dossier courant de l'appelant (les chemins relatifs valent ce qu'on a tapé), code de sortie relayé
  (`resolveSubprocessExitCode`, 128 + signal). Environnement : `buildOpsysMetierCliEnv` (`gateway/opsys-metier-env.ts`),
  le même ensemble que celui du moteur supervisé (jamais `OPENCLAW_*` ni clés de fournisseurs), avec trois différences :
  la clé `env` de `metier.json` ne donne que des défauts (l'`OPSYS_HOME` tapé par l'opérateur l'emporte : sans cela,
  `instance restaurer` irait dans l'instance installée), aucun jeton n'est ajouté (celui de `.env` passe par son préfixe,
  comme avec l'ancienne commande), `PYTHONUTF8=1` sous Windows. Le `.env` de l'état du core est lu par
  `loadGlobalRuntimeDotEnvFiles` (le premier gagnant), sans lire celui du dossier courant.
- **Refus depuis un agent** : la CLI du moteur porte des décisions humaines (approbations, personnes, modes d'autonomie) ;
  `opsys metier` est refusée quand `OPENCLAW_SHELL=exec` (posé par l'exécuteur de commandes des agents), comme
  `operator-cli-message-input.ts` le fait pour ses actions réservées. Le shim `openclaw` du Gateway pour les agents
  (`infra/openclaw-cli-shim.ts`) reste tel quel : il ne fournit toujours que `openclaw`.
- **Anciennes invocations** : `opsys personnes creer ...` (et `openclaw personnes ...`) n'exécute rien, écrit sur la sortie
  d'erreur la forme nouvelle avec les arguments tapés, et sort avec le code 2. Pas de délégation silencieuse : une commande
  retirée qui marcherait encore cacherait une documentation périmée, et un script échoue franchement. La liste est
  `OPSYS_METIER_MOVED_COMMANDS` ; `tests/test_commande_metier.py` la confronte au parseur du moteur, au faux core de la preuve
  de l'installateur et aux noms des commandes du core (aucune collision).
- **Le binaire `opsys` reconnu partout où l'on reconnaît `openclaw`** :
  - `infra/exec-control-command-guard.ts` : le garde qui refuse `channels login` interactif depuis un agent. Sans cela,
    `opsys channels login` l'aurait contourné ;
  - `commands/daemon-install-plan.shared.ts` (dossier du binaire dans le PATH du service) et
    `infra/openclaw-cli-invocation.ts` (l'entrée de la CLI courante, pour les processus enfants).
- **Gardé exprès** (chacun est couplé à du code que la CI seule peut éprouver ; à traiter dans un lot ultérieur si on le
  veut) :
  - `CLI_NAME` (`cli/cli-name.ts`), donc `Usage: openclaw ...`, le nom des fichiers de complétion et les messages de
    `update` : il sert aussi de clé aux étapes de mise à jour persistées (`update-command-package.ts` écrit
    `${CLI_NAME} doctor`, que `doctor-update-schema-guard.ts` compare à la chaîne `"openclaw doctor"` dans la base) ;
    le changer sans remplacer ces sites casserait la garde de schéma de la mise à jour ;
  - `process.title` (`openclaw`, `openclaw-gateway`, `openclaw-hooks`, `openclaw-node-worker`) : `infra/gateway-process-argv.ts`,
    `restart-stale-pids.ts`, `openclaw-process-census.ts`, les diagnostics de `status`, `dashboard` et `doctor` reconnaissent
    un Gateway à ce titre ; les renommer sans étendre ces détecteurs (et les `pkill -f '^openclaw-gateway'` des fumées
    Parallels) laisserait un Gateway périmé non détecté. Un lot dédié, avec ces détecteurs et leurs tests ;
  - les indications `formatCliCommand("openclaw ...")` (242 fichiers) et les préfixes de diagnostic `openclaw:` du lanceur
    et de `node-host-launcher.mjs` (`test/openclaw-launcher.e2e.test.ts` les fige) : l'alias les couvre ;
  - `infra/exec-approvals-policy.ts` : l'exemption de l'inspection en lecture seule des suppressions d'audit ne connaît
    que `openclaw` ; `opsys` demande l'approbation habituelle (la direction sûre) ;
  - le nom de fichier `openclaw.mjs`, les variables `OPENCLAW_*` et les noms de service (`openclaw-gateway-opsys`,
    lot 4).
- Tests neufs : `src/cli/opsys-metier-argv.test.ts`, `src/cli/opsys-metier-cli.test.ts` (lecteur de `metier.json`, environnement,
  code de sortie, refus depuis un agent, message de transition) ; ajoutés à des fichiers existants :
  `src/entry.run-main.test.ts` (l'aiguillage), `src/gateway/opsys-metier-env.test.ts` (`buildOpsysMetierCliEnv`),
  `src/infra/exec-control-command-guard.test.ts` (le garde reconnaît `opsys`), `src/commands/daemon-install-plan.shared.test.ts`.
  Les voisins d'origine des fichiers touchés rejoignent `test/opsys-tests-cibles.txt`. Côté Python : `tests/test_commande_metier.py`,
  `tests/test_instance.py` (la clé `commande_cli`) et la preuve de l'installateur avec le vrai core
  (`tests/installateur/bout_en_bout.sh` et `.ps1`, étapes « 1 bis » et « 1 bis bis »), seule preuve que le core lance bien le moteur.
- Les citations de l'ancienne forme dans le core (messages et commentaires de `opsys-contexte-config.ts`,
  `opsys-device-identity-http.ts` et de leurs tests) disent maintenant `opsys metier ...`.

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
| `opsys/metier.json` (hors schéma Zod) | active et règle le superviseur du moteur métier (T0.10) ; porte aussi `commande_cli`, la ligne de commande de la CLI du moteur que `opsys metier` lance (T0.7 lot 2). Écrit par `instance.py` (`ecrire_metier`) | `src/gateway/opsys-metier-config.ts`, `src/cli/opsys-metier-cli.ts` |
| `opsys/roles.json` (hors schéma Zod) | `roles` : outils permis par rôle d'appareil ; `serveurs` : le serveur MCP de chacun (T1.4-c6). Noms d'outils nus | `src/gateway/opsys-device-roles.ts` |
| `opsys/appareils.json` (hors schéma Zod) | appareil -> personne et rôle OPSYS (T1.4-c2, c4) ; rendu aussi à l'appareil par `GET /opsys/identite` (T1.4-c5). Format inchangé | `src/gateway/opsys-device-roles.ts` |
| `opsys/contexte.json` (hors schéma Zod) | active et règle le moteur de contexte OPSYS (T3.3-suite) ; écrit par `openclaw.py` (`contexte_entreprise`, `affaire_par_session`) ; porte aussi `niveaux` (niveau N de chaque outil, pour le garde), `outil_affaire` et l'`affaire` de chaque agent (T3.3-suite-b) | `src/context-engine/opsys-contexte-config.ts` |
| `plugins.slots.contextEngine` | choisit le moteur `opsys` quand `contexte.json` est actif ; absent sinon (moteur « legacy ») | `src/config/zod-schema.root-shape.ts`, `src/context-engine/registry-selection.ts` |
