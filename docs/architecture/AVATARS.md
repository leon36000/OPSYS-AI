# Avatars des départements

Chaque département se présente sous un avatar : un nom, un rôle, une voix et un visage, personnalisables par
client, joignables par trois canaux (messagerie, voix temps réel, audiovisuel). Ce document décrit ce que
l'étape 1 livre (identité déclarative, validation, résolution par client, lecture admin), ce que l'étape 2 livre
(projection du nom dans le core), où le core affiche un nom d'agent, et les étapes suivantes. Code :
[`src/opsys/avatars.py`](../../src/opsys/avatars.py), [`src/opsys/openclaw.py`](../../src/opsys/openclaw.py)
(`identite_agent`).

## Avatars par défaut

| Département | Avatar | Rôle (manifeste) |
|---|---|---|
| M1 Front Office | Léa | Réceptionniste et adjointe, accueil omnicanal |
| M2 Revenue CRM | Victor | Directeur des ventes et du CRM |
| M3 Estimation | Mathis | Estimateur : métrés et soumissions |
| M4 Field Ops | Gabriel | Répartiteur et chef des opérations terrain |
| M5 FinanceCore | Sophie | Contrôleuse, comptable, fiscaliste et CFO |
| M6 Material Control | Rosalie | Approvisionnement et inventaire |
| M7 Marketing | Chloé | CMO : marque, SEO/GEO, création et réseaux sociaux |
| M8 Analytics | Olivier | Analyste de données et tableaux de bord |
| M9 Strategic Intelligence | Athéna | Direction stratégique et conseil |
| M10 Mémoire | Mnémo | Mémoire, connaissances et apprentissage |

## Contrat du bloc `avatar` (`department.yaml`)

```yaml
avatar:
  nom: Léa
  role: "Réceptionniste et adjointe, accueil omnicanal"
  voix: voix.lea.defaut          # identifiant LOGIQUE, jamais un fournisseur
  visage: visage.lea.defaut      # identifiant LOGIQUE de gabarit
  canaux:
    messagerie: disponible
    voix: prevu
    audiovisuel: prevu
```

- **Champs obligatoires** : `nom`, `role`, `voix`, `visage`, `canaux`. Toute autre clé est refusée (aucun
  `pronom` : ni le schéma du manifeste ni l'`IdentityConfig` du core n'en portent).
- **`nom`** : 40 caractères au plus (le core tronque l'affichage à 50, voir plus bas), des lettres seulement
  (accents permis), en mots séparés par une espace, un trait d'union ou une apostrophe. Ni chiffre, ni symbole,
  ni balise, ni émoji.
- **`role`** : texte court, 80 caractères au plus, sans caractère de contrôle ni chevron.
- **`voix`, `visage`** : `voix.<nom>.<variante>` / `visage.<nom>.<variante>` (une sous-variante permise),
  minuscules ASCII, chiffres, `_` et `-`, 64 caractères au plus. Le fournisseur (ElevenLabs, Piper, Kokoro...)
  et le modèle 3D viendront du registre de fournisseurs, qui traduira l'identifiant logique ; aucun nom de
  fournisseur, URL ou chemin n'est accepté ici.
- **`canaux`** : objet non vide, sous-ensemble de `messagerie`, `voix`, `audiovisuel`, chacun `disponible` ou
  `prevu`. **Seule la messagerie peut être `disponible`** (`avatars.CANAUX_REALISES`) : un manifeste qui déclare
  la voix ou l'audiovisuel disponible est refusé tant que leur runtime n'existe pas. Ces canaux ne sont pas la
  clé `canaux` de premier niveau du manifeste (`opsys.canaux`, p. ex. `sms`), qui dit par où le public écrit.
- **Ce que « messagerie : disponible » affirme** : chaque département est un agent du core (`openclaw.generer`),
  avec lequel l'opérateur clavarde dans l'interface de contrôle du core. Depuis l'étape 2, l'agent porte le NOM
  effectif de l'avatar (section « Projection dans le core »). Ce n'est pas un chat public : le public écrit à M1
  par SMS.

Validation : la forme du bloc est vérifiée à la lecture du manifeste (`departements.lire_manifeste`, via
`avatars.normaliser_avatar`). `opsys-metier verifier` exige ensuite un avatar dans **chaque** département et des
noms distincts entre départements, casse et accents ignorés (« Lea » et « Léa » se confondent à l'oral) :
`avatars.verifier_declarations`.

## Personnalisation par client (`entreprise.yaml`)

Le profil d'entreprise de l'instance (`$OPSYS_HOME/entreprise.yaml`, même fichier que `services`, `equipes` et
`meteo`) porte une clé `avatars`, par identifiant de département :

```yaml
avatars:
  m01-front-office:
    nom: Julie
    voix: voix.julie.chaleureuse
  m05-financecore:
    visage: visage.sophie.tailleur
```

- Le client change `nom`, `voix`, `visage` ; jamais `role` ni `canaux` (ce que le département sait faire est
  dans le code). Mêmes règles de forme que le manifeste ; une entrée vide est refusée.
- `avatars.resoudre_identites(departements, surcharges)` est **pure** : défaut du manifeste + surcharges validées
  → `IdentiteEffective` par département, avec la provenance de chaque champ (`manifeste` ou `entreprise`).
  Refus (`AvatarInvalide`) : département inconnu, département sans avatar, deux identités effectives au même nom
  (y compris un renommage qui reprend le nom par défaut d'un autre département). Deux avatars peuvent échanger
  leurs noms.
- **Fail-closed** : une surcharge cassée n'est jamais lue comme une absence de surcharge (`ProfilInvalide`).
  `opsys-metier verifier` échoue (`avatars.verifier_profil`) ; la lecture admin ne montre aucune identité.
- L'unicité porte sur les noms, pas sur `voix`/`visage` : leur existence dans un registre n'est pas vérifiée
  tant que ce registre n'existe pas.
- Aucune commande d'écriture n'est livrée : le propriétaire édite le fichier ; une écriture signée au journal
  (patron `taxonomie._ecrire_cle_du_profil`) viendra avec la surface de personnalisation.

## Lecture de l'identité effective

Choix : **pas de nouvel outil**, une fonction du socle consommée par une surface admin existante. La
projection de configuration de la console (`opsys.console.configuration_lecture.lire`, servie dans
`configuration_dashboard` de `GET /api/connecteurs`, réservée à `nathan_owner`/`admin` par
`connecteurs_ui.autoriser`) porte maintenant, par département, `avatar` (l'identité effective, `en_dict()`) et,
au niveau racine, `avatars` : `{"statut": "defaut" | "personnalise", "personnalises": [...]}`, ou
`profil_invalide`, `profil_trop_volumineux` (plus de 64 Kio, refusé avant lecture), `avatars_non_declares` ;
dans ces trois cas, aucune identité n'est montrée (pas même les défauts) et aucun chemin n'est exposé. Le futur
worker vocal Python appellera `avatars.identites_effectives` directement. Les compteurs d'outils de
[ROLES.md](ROLES.md) sont inchangés.

## Ce que le core sait déjà d'un nom d'agent

Le core n'est modifié ni à l'étape 1 ni à l'étape 2. Points d'ancrage relevés :

- **Configuration** : `agents.entries.<id>.identity` (ou `agents.list[].identity` ; schéma
  `AgentEntrySchema`, `core/src/config/zod-schema.agent-runtime.ts`, `identity: IdentitySchema`), de type
  `IdentityConfig` (`core/src/config/types.base.ts`) : `name`, `theme`, `emoji`, `avatar` (image : chemin de
  l'espace de travail, URL http(s) ou data URI) et `avatarModelId` (modèle 3D du catalogue local).
- **Résolution** : `resolveAgentIdentity(cfg, agentId)` (`core/src/agents/identity.ts`) lit ce bloc ;
  `resolveAssistantIdentity({cfg, agentId, workspaceDir})` (`core/src/gateway/assistant-identity.ts`) choisit le
  nom dans cet ordre : `identity.name` de la configuration, puis `IDENTITY.md` de l'espace de travail
  (`loadAgentIdentityFromWorkspace`, `core/src/agents/identity-file.ts`), puis « Assistant ». Le nom est tronqué
  à 50 unités UTF-16 (`ASSISTANT_IDENTITY_LIMITS.name`), d'où la limite de 40 côté OPSYS.
- **Consommateurs** : méthode `agent.identity.get` (`core/src/gateway/server-methods/agent-identity.ts`,
  `agentIdentityGetHandler`) ; nom de l'assistant dans le contexte de réponse du chat
  (`core/src/gateway/server-methods/chat-send-reply-context.ts`) ; recherche de sessions
  (`core/src/gateway/session-utils-search.ts`) ; amorçage et route du modèle 3D de l'interface
  (`core/src/gateway/control-ui.ts`) ; mise à jour par `agents.update`, qui accepte `avatarModelId`
  (`core/src/gateway/server-methods/agents.ts`).
- **Interface** : `normalizeAssistantIdentity` (`core/ui/src/lib/assistant-identity.ts`), en-tête du chat
  (`core/ui/src/pages/chat/chat-pane-header.ts`) et composant 3D `openclaw-chat-agent-3d-avatar`
  (`core/ui/src/pages/chat/components/chat-agent-3d-avatar.ts`).
- **Catalogue 3D** : `ASSISTANT_AVATAR_MODELS` (`core/src/shared/assistant-avatar-model-catalog.ts`), deux
  modèles GLB CC0 livrés avec la passerelle (`robotexpressive-quaternius-cc0-v1`, `mpfb-human-cc0-v1`) ; un
  `avatarModelId` hors catalogue est refusé par `core/src/config/validation-core.ts`.
- **Avant l'étape 2**, `openclaw.generer` écrivait `"name": "<code> · <nom>"` (« M1 · Front Office ») sans bloc
  `identity` ni `IDENTITY.md` : `resolveAssistantIdentity` tombait sur « Assistant ».

## Projection dans le core (étape 2, livrée)

`openclaw.generer(..., profil_entreprise=None)` résout, avant toute écriture, l'identité EFFECTIVE de chaque
département (`avatars.identites_effectives` : manifeste + surcharges validées de `$OPSYS_HOME/entreprise.yaml`, ou
du fichier passé en `profil_entreprise`) et l'écrit dans l'entrée de l'agent du département
(`opsys/agents.json`, `entries.<id-du-département>`) :

```json
"m01-front-office": {
  "name": "M1 · Front Office",
  "identity": {"name": "Léa"},
  "description": "Réceptionniste et adjointe, accueil omnicanal",
  ...
}
```

- **`identity.name`** : le seul champ que le core lit pour le nom affiché. `IdentitySchema`
  (`core/src/config/zod-schema.core.ts`, `name: z.string().optional()`) ; `resolveAgentIdentity`
  (`core/src/agents/identity.ts`) le rend tel quel ; `resolveAssistantIdentity`
  (`core/src/gateway/assistant-identity.ts`) le prend en premier (`agentName ? [agentName, "agent"] : fileName ...`),
  donc `agent.identity.get` (`core/src/gateway/server-methods/agent-identity.ts`), lu par l'interface
  (`core/ui/src/lib/agents/identity.ts`), et le nom de l'assistant du contexte de réponse
  (`chat-send-reply-context.ts`) rendent « Léa ». Le prompt système porte aussi `name=Léa` dans sa ligne d'exécution
  (`resolveRuntimeAgentName`, `core/src/agents/system-prompt-params.ts`, ligne `name=` de
  `core/src/agents/system-prompt.ts`).
- **`description`** : le rôle (`AgentEntryBaseSchema`, `core/src/config/zod-schema.agent-entry-base.ts`,
  `description: z.string().optional()`), texte libre que le core relaie seulement (export d'agent,
  `core/src/claws/export.ts`). Le client ne le change pas.
- **`name`** reste « M1 · Front Office » : c'est le nom de la liste des agents (`core/src/gateway/agent-list.ts`
  le préfère à `identity.name`). Seuls les agents de département portent l'avatar ; les profils configurables
  (« Agent OPSYS · <profil> ») n'en portent pas, un même nom sur deux agents serait ambigu.
- **Pas d'`IDENTITY.md`** : la configuration l'emporte déjà sur ce fichier, que le core amorce lui-même dans
  l'espace de travail et dont il tire l'état d'amorçage (`core/src/agents/workspace.ts`) ; OPSYS ne réécrit que
  ce qui lui appartient (`SOUL.md`, `AGENTS.md`, skills).
- **`voix` et `visage` ne sont pas projetés** : aucun champ du core ne prend un identifiant logique sans
  l'interpréter. `identity.avatar` serait lu comme une image (chemin, URL http(s), data URI ;
  `core/src/config/validation-core.ts` refuse le reste), `identity.avatarModelId` doit nommer un modèle du
  catalogue 3D (même fichier, « must name a model in the local avatar catalogue »), et `tts` attend une voix de
  fournisseur. Ils attendent le registre de fournisseurs (étape suivante 1). Changer `voix`/`visage` dans
  `entreprise.yaml` ne change donc aucun fichier généré.
- **Effets de bord relevés dans le core** : avec un `identity.name`, le préfixe `auto` des réponses vaut `[Léa]`
  (`resolveResponsePrefix`, seulement si un canal configure `responsePrefix: auto`, ce qu'OPSYS ne fait pas), les
  mentions de groupe reconnaissent le nom (`core/src/auto-reply/reply/mentions.ts`) et l'identité sortante des
  canaux qui la portent (Slack, Discord...) le reprend (`core/src/infra/outbound/identity.ts`). Le canal SMS de M1
  n'utilise aucun de ces champs, et `session.sendPolicy` interdit toujours la réponse automatique à un client.
- **Fail-closed** : un département sans avatar ou deux noms par défaut identiques, ou une surcharge
  cassée (YAML illisible, nom refusé, doublon, département inconnu, clé non personnalisable, identifiant mal formé)
  → `openclaw.AvatarsRefuses` (sous-classe de `ProfilInvalide`, donc de `ValueError`) « avatars des départements
  invalides, rien n'est écrit ». Aucun fichier n'est écrit, pas même un espace de travail ; une configuration déjà
  générée reste intacte. `opsys-metier openclaw configurer` sort en code 2 avec le message.
- **Refus visible pour l'admin** (`src/opsys/openclaw_refus.py`) : sur le VPS, `deploy/entrypoint.sh` rejoue
  `configurer` toutes les 300 s sans regarder son code de sortie. Chaque refus d'avatars est donc consigné dans le
  journal d'audit (`openclaw.configuration.refusee`, catégorie `surcharges` ou `declarations`, empreinte SHA-256 du
  message ; ni chemin ni contenu du profil), une seule fois par état distinct ; la génération réussie suivante écrit
  une ligne `openclaw.configuration.retablie`. La page Connecteurs de la console (et `GET /api/connecteurs`,
  champ `configuration_dashboard.generation_core`) affiche le refus en cours et dit que le core conserve la
  configuration précédente. Preuves : `tests/test_openclaw_refus_visible.py`.
- **Idempotence** : régénérer sans changement rend tous les fichiers identiques octet pour octet ; renommer un
  avatar ne change que `identity.name` de son agent dans `agents.json`.
- Preuves : `tests/test_openclaw_avatars.py` (dix départements réels, surcharges, dix cas invalides, idempotence,
  contrat épinglé par lecture du code TypeScript ; si `core/node_modules` est installé, `AgentsSchema` valide la
  configuration et `resolveAgentIdentity` la relit). `resolveAssistantIdentity` lui-même a été exécuté une fois
  sous vitest (configuration `vitest.gateway.config.ts`, sonde non conservée) sur une configuration générée avec
  M1 renommée Julie : `agent:Julie`, `agent:Victor` ... `agent:Mnémo` pour les dix agents ; la même sonde sur une
  configuration d'avant l'étape 2 rendait `default:Assistant`. L'en-tête du chat lui-même n'a pas été observé
  dans une interface en marche.

## Étapes suivantes

L'étape 2 (projection du nom dans le core) est livrée, voir plus haut. Restent :

1. **Registre de fournisseurs** : table `voix.*` / `visage.*` → fournisseur, modèle, licence, coût et référence
   de secret, refus nommé pour un identifiant non enregistré (même patron que les paliers de modèles). C'est lui
   qui permettra de projeter `visage` en `identity.avatarModelId` (validé contre le catalogue 3D) et `voix` en
   configuration `tts`, dans `openclaw.identite_agent`.
2. **Session voix LiveKit dans le gateway** : salle par conversation, jeton émis par le gateway, liaison à
   l'agent du département et aux mêmes permissions que le chat.
3. **Worker vocal Python** (Pipecat, `docs/research/INGREDIENTS.md`) : STT → agent → TTS, voix résolue depuis
   `avatars.identites_effectives` et le registre ; interruptions, silences et transfert à un humain.
4. **Rendu TalkingHead sur l'appareil** : visage animé (visèmes) dans l'app et l'interface, gabarit résolu
   depuis `visage` ; le canal `audiovisuel` passe à `disponible` seulement quand ce rendu est livré et testé.
5. **SIP pour Léa** : appels téléphoniques entrants de M1 vers la session vocale, sous les mêmes interdits que
   les autres canaux (aucun prix, date ni engagement ; registre anti-perte).

À chaque étape livrée, `CANAUX_REALISES` s'élargit et les manifestes concernés passent le canal à `disponible`
dans le même diff que la preuve.
