# Avatars des départements

Chaque département se présente sous un avatar : un nom, un rôle, une voix et un visage, personnalisables par
client, joignables par trois canaux (messagerie, voix temps réel, audiovisuel). Ce document décrit ce que
l'étape 1 livre (identité déclarative, validation, résolution par client, lecture admin), où le core affiche déjà
un nom d'agent, et les étapes suivantes. Code : [`src/opsys/avatars.py`](../../src/opsys/avatars.py).

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
  avec lequel l'opérateur clavarde dans l'interface de contrôle du core. Le chat existe ; le NOM de l'avatar n'y
  est pas encore projeté (section suivante). Ce n'est pas un chat public : le public écrit à M1 par SMS.

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

Le core n'est pas modifié dans cette étape. Points d'ancrage relevés :

- **Configuration** : `agents.list[].identity` (`core/src/config/types.agents.ts`, champ `identity`), de type
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
- **Côté OPSYS aujourd'hui** : `openclaw.generer` (`src/opsys/openclaw.py`) écrit pour chaque département
  `"name": "<code> · <nom>"` (p. ex. « M1 · Front Office ») mais **aucun bloc `identity`** ni `IDENTITY.md` :
  l'interface du chat affiche donc le nom résolu par défaut, pas « Léa ».

## Étapes suivantes

1. **Projection dans le core** : `openclaw.generer` écrit `identity.name` (identité effective) pour l'agent de
   chaque département, et traduit `visage` en `avatarModelId` par une table de correspondance validée contre le
   catalogue 3D. Tests de configuration générée ; aucune modification du core requise pour le nom.
2. **Registre de fournisseurs** : table `voix.*` / `visage.*` → fournisseur, modèle, licence, coût et référence
   de secret, refus nommé pour un identifiant non enregistré (même patron que les paliers de modèles).
3. **Session voix LiveKit dans le gateway** : salle par conversation, jeton émis par le gateway, liaison à
   l'agent du département et aux mêmes permissions que le chat.
4. **Worker vocal Python** (Pipecat, `docs/research/INGREDIENTS.md`) : STT → agent → TTS, voix résolue depuis
   `avatars.identites_effectives` et le registre ; interruptions, silences et transfert à un humain.
5. **Rendu TalkingHead sur l'appareil** : visage animé (visèmes) dans l'app et l'interface, gabarit résolu
   depuis `visage` ; le canal `audiovisuel` passe à `disponible` seulement quand ce rendu est livré et testé.
6. **SIP pour Léa** : appels téléphoniques entrants de M1 vers la session vocale, sous les mêmes interdits que
   les autres canaux (aucun prix, date ni engagement ; registre anti-perte).

À chaque étape livrée, `CANAUX_REALISES` s'élargit et les manifestes concernés passent le canal à `disponible`
dans le même diff que la preuve.
