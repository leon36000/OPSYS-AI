# ADR-0011 — Canaux : réception sans modèle et envoi réel au client après approbation N4

> Note du 30 septembre : document proposé, complété par des preuves historiques de tranches.
> Ses mentions de revue extérieure obligatoire sont remplacées par ADR-0012. Les approbations
> humaines d'envoi réel et de politique de consentement restent applicables ; aucune mise en
> production n'est déduite de l'existence de cet ADR ou de ses patches.

- Statut : **Proposé** (rédaction confiée par l'ingénieur en chef, 2026-09-29). **La décision appartient au
  propriétaire** (GATE NATHAN, section « Ce que le propriétaire décide »). Rien n'est codé : cet ADR ne touche ni
  `core/`, ni `src/`, ni un département.
- Complète : [ADR-0008](ADR-0008-fork-openclaw-opsys-core.md) (canaux du core, moteur derrière MCP),
  [ADR-0009](ADR-0009-socle-metier.md) (échelle N0–N5, approbations) et [ADR-0010](ADR-0010-memoire.md) (session,
  affaire). Ne remplace aucun ADR. Il tranche ce que [`M1-canaux.md`](../departements/M1-canaux.md) laissait ouvert : le
  crochet `message_received` (§ 7), la table `consent_sms` (§ 5) et l'envoi réel (§ 6).
- Fondé sur : la [définition produit](../produit/DEFINITION-PRODUIT.md) (§ 1, § 5 P1 P8 P9 P10, § 7 M1, § 9, § 10), la
  lecture du fork (chaque `fichier:ligne` ci-dessous a été lu dans ce dépôt, pas retenu de mémoire),
  [`POLITIQUE-consentement-sms`](../compliance/politiques/POLITIQUE-consentement-sms.md), PLAN T2.1 et T4.17-e3/e4.
- Convention de citation : `webhook.ts`, `twilio.ts`, `send.ts`, `channel.ts`, `inbound.ts`, `ingress-spool.ts`,
  `delivery-observations.ts`, `public-webhook-url.ts` et `accounts.ts` seuls sont ceux de `core/extensions/sms/src/` ;
  `outils.py`, `reception.py`, `transferts.py` et `adaptateurs.py` seuls sont ceux de
  `departments/m01-front-office/src/m1_front_office/`. Tout autre fichier se cite en chemin complet, et un nom court
  repris juste après son chemin complet désigne le même fichier ; le `send.ts` du Gateway est toujours en chemin
  complet.

## Contexte

Un client écrit « mes gouttières débordent, à Laval ». Deux choses manquent entre son téléphone et le registre de M1.

**À l'entrée, le modèle fait la copie.**
- Le core livre le message à l'agent M1 avec des blocs que la plateforme génère : canal, expéditeur, `message_id`,
  heure. Le modèle les recopie dans `m1_recevoir_message_canal` (étape 1 de
  `departments/m01-front-office/skills/recevoir-un-message-de-canal/SKILL.md:12`). L'outil est N2
  (`departments/m01-front-office/src/m1_front_office/outils.py:1359-1417`).
- Le code borne la forme des champs (`departments/m01-front-office/src/m1_front_office/reception.py:193-224`). Il ne
  peut pas savoir que l'expéditeur recopié est celui qui a écrit. Une consigne cachée dans le texte d'un client peut
  faire recopier un autre expéditeur ou un autre texte (par exemple un « STOP » au nom d'un tiers, que l'outil
  inscrirait comme retrait de consentement).
- Le modèle peut aussi oublier l'appel, ou le refaire avec d'autres champs. Chaque message coûte un tour.
- M1-canaux § 7 proposait le crochet `message_received` du core, avec un journal de reprise « à décider ».

**À la sortie, rien ne part.**
- `m1_emettre_notification(canal, message)` est N4 (`outils.py:1636-1653`). Une fois approuvé, son corps appelle un faux
  bus en mémoire (`outils.py:394-402`, `departments/m01-front-office/src/m1_front_office/adaptateurs.py:76-83`).
- L'outil n'a ni destinataire ni conversation : `canal` est une chaîne libre. Le contrat ne dit pas à qui écrire.
- Le core saurait envoyer, mais il réécrit le texte (§ Question 2) et rien ne lie l'envoi à l'approbation.

Le test de dérive de `AGENTS.md` passe : tout ce qui suit parle de clients, de leads, de plaintes, d'approbations du
propriétaire et de messages de gouttières (M1.4, M1.7, M1.8, M1.12 ; P1, P8, P9).

## Décisions proposées

1. **Réception : le core appelle lui-même `m1_recevoir_message_canal`, dans le noyau des tours de canal, avant le tour
   de l'agent, en attendant la réponse.** Il tire les champs du contexte que la plateforme a vérifié (signature Twilio),
   jamais du modèle. Toute panne lève une exception : la file durable du canal garde le message et réessaie.
   L'idempotence est celle du moteur (`signal_id = <canal>:<message_id>`). Le crochet `message_received` n'est pas le
   mécanisme.
2. **Le modèle ne recopie plus rien.** `m1_recevoir_message_canal` sort de sa boîte d'outils, et le moteur l'exige d'un
   appelant du core (marqueur `_meta` posé par l'hôte). L'agent lit le résultat par `m1_lire_reception` (T0).
3. **Session de confiance.** Le core pose la clé de session réelle dans le `_meta` MCP de tout appel vers un serveur
   `opsys_mN`, jamais vers un autre serveur (la clé contient le numéro du client). Le moteur s'en sert pour tout ce qui
   vise « cette conversation ». Aucun argument ne peut la nommer.
4. **Envoi en deux outils.** `m1_proposer_reponse(texte)` (N2) écrit une proposition liée à la conversation de la
   session. `m1_envoyer_reponse(envoi_id, texte, destinataire_masque)` (N4) est approuvé par une personne ; il ne fait
   qu'inscrire l'approbation. Aucun outil du modèle ne prend un numéro, une adresse ou un canal.
5. **Le moteur tient le registre des envois, le core exécute.** Ce registre est fait de lignes `envoi` du registre de M1
   (ajout seul, chaîne de hash). Le core vient chercher les envois approuvés (sondage toutes les 3 s, par l'appel MCP
   qu'il fait déjà), envoie le texte exact par un chemin qui ne le réécrit pas, et rend l'issue. Aucun appel du moteur
   vers le core, aucun secret de plus.
6. **Au plus une fois.** Un marqueur est inscrit avant la requête à Twilio. Une issue inconnue n'est jamais rejouée :
   elle va à « À voir ». Un échec prouvé avant la requête est réessayé (trois essais proposés), puis va à « À voir ».
7. **Garde d'envoi sans valeur par défaut.** STOP ne se lève jamais. La base d'envoi, la fenêtre de réponse et les
   plages viennent du profil d'entreprise ; absentes, le verdict dit où les déclarer. La garde joue à la proposition, à
   l'approbation et à la réservation. Un message plus récent du client périme la proposition.
8. **Porte fermée = repli manuel.** Canal inactif : l'envoi approuvé va tout de suite à « À voir » avec son texte. Une
   personne l'envoie à la main, puis le clôt (DEFINITION-PRODUIT § 5 P6 et § 10).
9. **Courriel plus tard, même registre des envois.** Le fork n'envoie aucun courriel. L'exécuteur SMTP est une tranche à
   part.
10. **T3 et propriétaire.** Activer Twilio, attester les politiques, mettre en ligne, faire le premier envoi réel :
    humain seul. Les valeurs du profil, l'approbateur, la mention de retrait et la voie du formulaire : GATE NATHAN.

## Question 1 — Réception sans modèle

### Ce que le fork offre déjà

| Pièce | Où | Ce qu'elle garantit |
|---|---|---|
| Signature Twilio, limites de débit, 200 après écriture durable | `core/extensions/sms/src/webhook.ts:167-185`, `:268-279` | expéditeur, corps et `MessageSid` sont ceux que Twilio a signés ; le fournisseur n'a son 200 qu'après la validation de SQLite |
| File durable du canal (« spool ») | `core/extensions/sms/src/ingress-spool.ts:113-176` | le message reste jusqu'à ce que sa livraison à l'agent réussisse ; une exception de livraison veut dire nouvel essai |
| Politique d'essai | `core/src/channels/message/ingress-retry-policy.ts:16-19,89-97` ; `core/src/channels/message/ingress-monitor.ts:167-170` | délai de 1 s doublé jusqu'à 3 min ; échec définitif seulement après 8 essais **et** 24 h ; erreur permanente : échec tout de suite (`core/src/channels/message/ingress-drain.ts:237-275`). Un expéditeur = une voie, servie dans l'ordre ; l'événement est complété **à l'adoption du tour** (`ingress-drain.ts:4`, `:348`) |
| Rejeu manuel | `core/src/cli/channels-cli.ts:281-316` | `openclaw channels dead-letters list` et `resubmit --channel sms` |
| Noyau des tours de canal | `core/src/channels/turn/run-channel-turn.ts:162-341` | `ingest`, `classify`, `preflight`, `resolveTurn`, dispatch : tout est attendu, une exception remonte à la file |
| Crochet `message_received` | `core/src/auto-reply/reply/message-received-hooks.ts:15-57` | observation « fire and forget » |
| Crochet `before_dispatch` | `core/src/auto-reply/reply/dispatch-from-config.choose-route.ts:564-651` | attendu, avant le modèle ; peut « prendre » le message |
| Appel du moteur depuis le core | `core/src/context-engine/opsys-contexte-mcp.ts:49-95` | MCP, jeton `OPSYS_MCP_JETON`, une connexion par appel (`:9-10`) |
| `_meta` maîtrisé par l'hôte | `core/src/agents/mcp-call-meta.ts:1-29` ; `core/src/agents/agent-bundle-mcp-runtime.ts:1056-1075` | jamais un argument que le modèle peut forger ; posé aujourd'hui seulement pour la porte d'appareil |

### Les options

**A. Crochet `message_received` (piste de M1-canaux § 7).**
- *Chemin.* `emitMessageReceivedHooks` (`message-received-hooks.ts:35-44` pour le crochet de plugin, `:45-56` pour le
  crochet interne), appelé à `core/src/auto-reply/reply/dispatch-from-config.prepare-operation.ts:397` (chemin normal),
  `:79` (commande rapide) et `core/src/auto-reply/reply/dispatch-from-config.prepare-context.ts:518`. Forme de
  l'événement : `core/src/hooks/message-hook-mappers.ts:513-545`.
- *Core.* Un plugin OPSYS s'abonne et appelle `callOpsysMcpTool`. Pour ne rien perdre, il lui faut un journal : une file
  `openChannelIngressQueue` que le plugin vide vers le moteur (jamais un `PluginStateKeyedStore`, qui évince ses plus
  vieilles entrées : `core/extensions/sms/src/delivery-observations.ts:112-126`).
- *Pannes.* L'appel n'est pas attendu ; sa panne est une ligne de journal détaillé
  (`core/src/hooks/fire-and-forget.ts:80-88`, `logVerbose`). Il court en même temps que le tour : rien n'oblige le
  journal à être écrit avant que le tour se termine, et la file complète l'événement à l'adoption du tour
  (`ingress-drain.ts:348`, atteinte dans le dispatch : `core/src/auto-reply/reply/agent-runner-execute.ts:205`). Il
  n'est pas émis quand la session est occupée (`dispatch-from-config.prepare-operation.ts:193-198`) ni dans les sorties
  précoces (`dispatch-from-config.prepare-operation.ts:200-222`) : son heure dépend du répartiteur de réponses, pas du
  webhook. Il ne couvre ni le courriel ni la voix (autres chemins : `core/extensions/imap/src/watcher.ts:345`,
  `core/extensions/voice-call/src/manager/events.ts:420`).
- *Sécurité.* Le modèle reste dans la boucle tant que l'outil est dans sa boîte.
- *Coût.* Moyen : plugin, journal et son propre drain, qui refont ce que la file du canal fait déjà.
- *Tests.* Vitest sur le plugin. L'`e2e-core` exige un tour d'agent (faux fournisseur de modèle), car le crochet est
  émis par le répartiteur de réponses.
- *Verdict.* Écartée comme mécanisme de réception. Elle reste utile comme observation.

**B. Crochet `before_dispatch` (attendu), rendu fail-closed.**
- *Chemin.* `dispatch-from-config.choose-route.ts:582-587` : `await hookRunner.runBeforeDispatch(...)` avec `messageId`,
  `content`, `channel`, `sessionKey`, `senderId`, `timestamp` (`:587-602`). `handled: true` (`:625`) évite le modèle.
- *Core.* Une ligne dans la politique d'échec globale : `before_dispatch: "fail-closed"` à
  `core/src/plugins/hook-runner-global.ts:31-35`. Sans elle, l'exception d'un crochet est journalisée et le tour
  continue (`core/src/plugins/hooks.ts:314`, `:591-602`, `:927-930`).
- *Pannes.* Avec cette ligne, l'exception remonte au canal et la file réessaie. Mais le crochet ne tourne que si
  `allowInboundHandlers`, `runtimeTakeoverHooksAllowed` et `hasHooks` sont vrais
  (`dispatch-from-config.choose-route.ts:565-568`), après les sorties précoces de
  `dispatch-from-config.prepare-operation.ts`. Un crochet sauté ne se signale pas : le canal a le message, le moteur ne
  l'a jamais reçu et personne ne le sait.
- *Sécurité.* La politique fail-closed vaut pour le `before_dispatch` de tous les plugins.
- *Coût.* Faible. *Tests.* Comme A.
- *Verdict.* Meilleure que A. Écartée : la garantie dépend de conditions du répartiteur de réponses, pas du canal.

**C. Appel du core dans le noyau des tours de canal, avant le dispatch, attendu (recommandée).**
- *Chemin.* Dans `runChannelTurn`, entre `assembleResolvedChannelTurn` (`run-channel-turn.ts:237`) et l'entrée dans le
  `try` (`:252`). Le contexte normalisé est là : `RawBody`, `From`, `SenderE164`, `MessageSid`, `Timestamp`
  (`core/src/auto-reply/templating.ts:137,148,174,330,334`), et la clé de session (`resolved.routeSessionKey`,
  `run-channel-turn.ts:245`). Ce point précède l'adoption du tour, donc reste dans la fenêtre de reprise de la file.
  Pour un SMS, il est atteint par la file durable : `ingress-spool.ts:143-148`, puis `dispatchSmsInboundEvent`
  (`core/extensions/sms/src/inbound.ts:100-323`), puis `inbound.run` (`inbound.ts:216`), lié à `runChannelTurn` par
  `core/src/plugins/runtime/runtime-channel.ts:130`.
- *Core.* `core/src/channels/turn/opsys-reception.ts` (nouveau) :
  - lit `opsys/canaux.json`, généré par `opsys-metier openclaw configurer`, éteint par défaut, sur le patron de
    `contexte.json` (`core/src/context-engine/opsys-contexte-config.ts:1-36`) ;
  - n'agit que pour l'agent et le canal qu'il nomme (M1, `sms`) ;
  - appelle `m1_recevoir_message_canal` par `callOpsysMcpTool`, qui gagne un paramètre `meta` ;
  - laisse remonter toute panne.
- *Pannes et reprise.* Voir le tableau ci-dessous.
- *Sécurité.* Voir « Qui peut appeler quoi ».
- *Coût.* Un appel MCP local par message ; aucun token de sortie pour recopier des champs ; un module neuf, trois points
  d'insertion, un fragment généré.
- *Tests.* Vitest (§ Mise en œuvre) et `e2e-core` **sans modèle** : le webhook signé suffit, puisque la réception
  précède le tour.
- *Placement voisin.* Le même appel dans `dispatchSmsInboundEvent`, avant la matérialisation des pièces jointes
  (`inbound.ts:133-144`), éviterait de télécharger un MMS que le moteur n'a pas encore accepté. Mais une extension
  n'importe pas `core/src/**` (`core/extensions/AGENTS.md`, « Boundary Rules ») : il faudrait un sous-chemin du SDK des
  plugins, donc des fichiers de référence à mettre à jour. Le noyau ne demande rien de tel ; son seul coût est un MMS
  téléchargé de nouveau à chaque essai quand le moteur est en panne.

**D. Plugin OPSYS dédié (`core/extensions/opsys-canaux`).**
- *Chemin.* Deux formes. (i) Le plugin s'abonne à `message_received` : c'est l'option A, avec ses pannes. (ii) Il reçoit
  lui-même le message par une route HTTP du Gateway (`registerPluginHttpRoute`, `auth: "plugin"`,
  `core/extensions/sms/src/gateway.ts:120-132`) ; pour le SMS, elle remplacerait le webhook du canal.
- *Core.* Une extension neuve. Elle n'importe pas `core/src/**` (`core/extensions/AGENTS.md:29`) : `callOpsysMcpTool`
  passerait par un sous-chemin du SDK des plugins, donc des fichiers de référence à mettre à jour.
- *Pannes.* Forme (i) : celles de A. Forme (ii) : le plugin refait la file durable, l'ordre par expéditeur, les essais
  et le rejeu que le canal SMS a déjà (`ingress-spool.ts:113-176`).
- *Sécurité.* Une route `auth: "plugin"` porte toute son authentification dans le plugin (commentaire de
  `core/src/gateway/server/plugins-http/route-auth.ts:37`). Le plugin vérifierait donc lui-même la signature de chaque
  canal et porterait le jeton MCP : une surface de plus à revoir.
- *Coût.* Le plus élevé pour le SMS. *Tests.* Vitest dans l'extension ; `e2e-core` comme C pour la forme (ii).
- *Verdict.* Pas pour le SMS. C'est le bon foyer du **récepteur du formulaire** (T4.17-e4) : même route
  `auth: "plugin"`, même file durable, même client de réception.

**Autre : le moteur écoute Twilio lui-même.** Écartée. Le Gateway est le seul point d'entrée HTTP (ADR-0008, décision 2
: `ADR-0008-fork-openclaw-opsys-core.md:46`).

### Pannes et reprise (option C)

| Situation | Ce qui se passe |
|---|---|
| Moteur arrêté ou lent, moins de 24 h | l'appel lève ; l'événement reste dans la file ; essais de 1 s à 3 min ; à la reprise, le message entre, dans l'ordre pour un même expéditeur (`ingress-spool.ts:127-128`, `ingress-drain.ts:4`) |
| Moteur arrêté plus de 24 h et 8 essais | l'événement passe en « échec » (`ingress-retry-policy.ts:89-97`), conservé (1 000 au plus, `ingress-spool.ts:151-155`) ; `openclaw channels dead-letters resubmit` le rejoue |
| Le moteur a écrit, la réponse s'est perdue | nouvel essai ; le moteur reconnaît le `signal_id` et rend la réponse d'alors sans écrire (`outils.py:1242-1244`) |
| La livraison échoue après la réception | la file rejoue ; la réception est reconnue de la même façon |
| Twilio rejoue le même `MessageSid` | la file l'ignore (`ingress-spool.ts:119-128`, identité d'événement ; pierre tombale de 24 h, `:151-155`) |
| Refus de configuration (`REJ-SERVICE-NON-CONFIGURE`, `REJ-ZONE-NON-CONFIGUREE`) | traité comme une panne : le message attend dans la file que le propriétaire déclare ; le journal du core porte le code |
| Refus permanent (champ de plateforme invalide) | échec immédiat de la file, comme `SmsIngressPermanentError` (`ingress-spool.ts:33,165-169`) : jamais de boucle |
| MMS sans texte | `reception.py:204-205` refuse un texte vide, et `core/extensions/sms/src/twilio.ts:285` admet un MMS sans corps : le moteur doit inscrire le signal avec `pieces_jointes`, sans le qualifier, et ouvrir une attente « À voir » (une personne regarde la photo). Cas de la tranche c1 |
| Message hors de la file (courriel, voix, formulaire) | hors de cette option : chacun appelle le même client depuis son point d'entrée (T2.1-d, T4.17-e4) |

### Qui peut appeler quoi (réception)

| Appelant | Peut | Ne peut pas |
|---|---|---|
| Twilio | poster un webhook signé (`webhook.ts:167-185`) | rien d'autre |
| Core (noyau des tours) | appeler `m1_recevoir_message_canal`, avec le jeton MCP et le marqueur d'origine | inventer un champ : tout vient du contexte signé |
| Modèle de l'agent M1 | lire `m1_lire_reception` | appeler la réception : l'outil quitte sa boîte (`deny` l'emporte, `core/src/agents/tool-policy-match.ts:58`), et le moteur refuse un appel sans marqueur d'origine |
| Un porteur du jeton MCP | tout, y compris poser un `_meta` | — : le jeton reste réservé au core (`ADR-0009-socle-metier.md:144-147`) ; le marqueur protège du **modèle**, pas d'un jeton volé |

Le marqueur est `_meta["opsys/origine"] = "reception"`, et le même `_meta` porte `opsys/cleSession`. Ils sont posés par
`callOpsysMcpTool`, jamais par un outil du modèle : le modèle ne fournit que les arguments. Le moteur le lit comme il
lit déjà l'identité d'appareil (`src/opsys/serveur_mcp.py:80-84`, `src/opsys/contexte.py:159`). Le serveur MCP n'a qu'un
jeton pour tous ses appelants (`serveur_mcp.py:143-164`) : la séparation est faite par la boîte de l'agent **et** par ce
marqueur. L'exigence du marqueur s'allume à la dernière tranche de réception, avec le core en place.

### Recommandation

**Option C.** Le noyau appelle le moteur avant le tour, et la file durable du canal est le journal de reprise : elle
existe, elle est testée, elle a une commande de rejeu. Le moteur reste l'autorité de l'idempotence. Le crochet
`message_received` sert au plus d'observation.

### Ce que voit l'agent

- Il ne recopie rien. Il appelle `m1_lire_reception` (T0, sans argument). L'outil lit la clé de session de confiance et
  rend la dernière réponse de réception de cette conversation, entière (décision, brouillon, questions, score), plus
  l'état du dernier envoi (§ Question 2).
- La réponse complète est inscrite au registre dans la même transaction que le signal : `_signal_deja_recu` ne rend
  aujourd'hui que la forme réduite d'un doublon (`outils.py:1081-1134`), sans le brouillon ni le score.
- La skill `recevoir-un-message-de-canal` et le SOUL de M1 changent. Les deux paramètres que `m1_transferer` et
  `m1_escalader_plainte` font recopier (`outils.py:1550-1556`, `:1581-1588`) se retirent de la même façon, dans une
  tranche suivante hors de cet ADR.
- **Le lien automatique session → affaire** (case ouverte de T2.1-b) devient techniquement possible sans modèle : la clé
  réelle est connue de confiance. Il reste une décision de confidentialité du propriétaire (M1-canaux § 3) ; cet ADR ne
  la prend pas.
- Le core envoie la clé réelle ; le moteur la compare à `canaux.cle_session` (`src/opsys/canaux.py:110-124`) et refuse
  une divergence (`REJ-CLE-SESSION-DIVERGENTE`). Cela ferme la réserve « non vérifié ici » de M1-canaux § 7.

## Question 2 — Envoi réel après approbation N4

### Ce que le fork et le socle offrent (et ce qu'ils n'offrent pas)

| Pièce | Où | Ce qu'elle garantit, ou pas |
|---|---|---|
| Outil actuel | `outils.py:1636-1653`, `outils.py:394-402`, `adaptateurs.py:76-83` | N4, mais faux bus ; ni destinataire, ni conversation |
| Approbation | `src/opsys/approbations.py:243-244` ; `:288-325` | une décision exécute l'outil avec les arguments **exacts** enregistrés ; `approbateur_en_cours` dit qui a approuvé, en base, jamais par un argument |
| Modes | `src/opsys/politiques.py:28-32` ; `src/opsys/canaux.py:236-247` | `ombre` : N3 et plus attendent ; `supervise` : N4 et plus ; `autonome` : N5 seulement, donc refusé à un département à canaux |
| Réécriture du texte | `core/extensions/sms/src/send.ts:94-104`, `:124-130` ; `core/extensions/sms/src/channel.ts:560` | avant l'envoi, le core retire le balisage markdown, ramène trois sauts de ligne à deux, rogne les blancs, et coupe au-delà de `textChunkLimit` (1 500 par défaut, `core/extensions/sms/src/accounts.ts:27`) : le texte envoyé n'est **pas** toujours le texte donné |
| Requête Twilio | `core/extensions/sms/src/twilio.ts:621-636` | `To`, `Body`, `From`, `StatusCallback` : **aucune clé d'idempotence** côté fournisseur ; 1 600 caractères au plus (`:32`, `:607-611`) ; délai de 30 s (`:26`) |
| Marqueur avant la requête | `twilio.ts:644` ; `send.ts:132-165` | `onPlatformSendDispatch` s'exécute juste avant le POST. Une erreur avant lui est « prouvée non envoyée » ; après lui, l'issue est incertaine (`send.ts:139-162`) |
| RPC `send` du Gateway | `core/src/gateway/server-methods/send.ts:1401-1431` ; `core/src/gateway/server-connection-state.ts:197` ; `core/src/gateway/methods/core-descriptors.ts:338` | portée `operator.write` ; déduplication dans une `Map` du processus (`server-maintenance.ts:336-410` la purge) ; aucune intention d'envoi durable |
| File d'envoi durable du core | `core/src/infra/outbound/deliver-queue.ts:331-364`, `:425-449` ; `core/src/infra/outbound/delivery-queue-recovery.ts:711-804` | écrit avant d'envoyer, refuse de rejouer à l'aveugle un envoi ambigu ; mais exige une réconciliation que l'adaptateur SMS n'a pas (`core/extensions/sms/src/channel.ts:348-385` ; seul Slack l'implémente, `core/extensions/slack/src/channel.ts:546-547`) |
| Accusés de livraison | `core/extensions/sms/src/webhook.ts:196-235` ; `core/extensions/sms/src/delivery-observations.ts:6-9,112-126` | états `delivered`, `undelivered`, `failed`, `canceled` reçus et gardés, mais « état récent borné, pas un registre d'audit » (30 jours, 5 000 messages, on évince les plus vieux) ; personne n'en avertit le moteur |
| Retour des rappels | `core/extensions/sms/src/public-webhook-url.ts:94-139` | le rappel est réessayé si le core répond 5xx, une fois par défaut (`rc`, `:122-127`, et `:129-131`) : on peut répondre 5xx tant que le moteur n'a pas la nouvelle, mais le moteur doit pouvoir perdre un accusé sans perdre l'envoi |
| Secrets | `core/src/gateway/opsys-metier-env.ts:50-52,82-86` ; `deploy/docker-compose.yml:164-168` | le moteur ne devrait pas avoir les jetons de canal ; mais le préfixe `OPSYS_` laisse passer `OPSYS_SMS_JETON` jusqu'à son environnement (voir Conséquences) |
| Courriel | `core/extensions/imap/src/` | lecture seulement : aucune extension du fork n'envoie de courriel (recherche de `smtp`, `nodemailer`, `sendMail` sans résultat dans `core/extensions`, hors tests) |

### Exigences et décisions

| Exigence | Décision |
|---|---|
| **Le destinataire est lié à la conversation et à l'approbation. Jamais un numéro que l'agent choisit.** | Aucun outil du modèle ne prend un numéro, une adresse ou un canal. `m1_proposer_reponse` tire la conversation de la clé de session de confiance (`_meta["opsys/cleSession"]`, posé par l'hôte) et vérifie qu'un message de ce correspondant est au registre. Le numéro est chiffré avec une clé destructible (`src/opsys/cles_chiffrement.py:1-36`, comme la position d'un pointage de M4). Le modèle et l'approbateur n'en voient qu'un masque (quatre derniers chiffres). `envoi_id` = empreinte de (conversation, message répondu, texte). |
| **Le texte envoyé est exactement le texte approuvé.** | Le texte approuvé est celui des arguments de `m1_envoyer_reponse`, que l'outil compare, caractère pour caractère (NFC), à celui du registre des envois. Le moteur rend au core le texte et son empreinte SHA-256 ; le core la recalcule, puis envoie par un chemin qui **ne réécrit pas** : `sendSmsExactText` (nouveau, dans `send.ts`), sans `toSmsPlainText`, sans découpage, qui refuse tout texte de plus de `min(textChunkLimit, 1 600)`. Tout ce qui doit figurer (mention de retrait, nom de l'entreprise) est ajouté par le **moteur** à la proposition, donc vu et approuvé : le core n'ajoute rien. |
| **Un seul envoi.** | Voir « Au plus une fois » ci-dessous : proposition idempotente, une seule proposition ouverte par conversation, approbation exécutée une fois (`approbations.py:232-239`), réservation à un seul gagnant, marqueur avant la requête, issue inconnue jamais rejouée. |
| **Consentement et STOP (CASL, `m1.retrait_consentement`).** | Voir « Garde d'envoi ». |
| **Accusé de livraison, échec.** | Voir « Échecs, essais, À voir ». |
| **Trace de ce qui est parti.** | Les lignes `envoi` du registre de M1 (ajout seul, chaîne de hash vérifiable), qui portent l'approbateur (`approbateur_en_cours`), l'empreinte, le `MessageSid`, chaque tentative et chaque accusé. Plus la ligne de `approbations` et le journal d'audit du socle. |
| **Où vit le code, quel appel authentifié.** | Voir « Où vit le code ». |

### Où vit le code

| Option | Ce qu'elle fait | Verdict |
|---|---|---|
| O1. Le moteur envoie lui-même à Twilio | Python appelle l'API Twilio après l'approbation | Écartée. Le jeton n'est pas censé être dans le moteur (`opsys-metier-env.ts:50-52`). Il faudrait recopier en Python le garde SSRF, les bornes de réponse et le cycle de vie des identifiants de `twilio.ts`. Les rappels d'état arrivent au core de toute façon (`webhook.ts:196-235`). Si le répartiteur du bus porte l'envoi, il attend le réseau dans la transaction du moteur (`src/opsys/evenements/repartiteur.py:100-143`, jusqu'à 30 s). |
| O2. Le moteur appelle le RPC `send` du Gateway | après l'approbation, appel WebSocket ou HTTP | Écartée. Il faudrait donner au moteur une portée `operator.write`, qui écrit à n'importe quel numéro. Déduplication en mémoire (`server-connection-state.ts:197`), pas d'intention durable (`server-methods/send.ts:1401-1431`), texte réécrit (`core/extensions/sms/src/channel.ts:560`). |
| **O3. Le core vient chercher (recommandée)** | un sidecar du Gateway interroge le moteur par le MCP qu'il utilise déjà, envoie, puis rend l'issue | Le core est un exécuteur **sans état** : la vérité est au registre des envois. Il ne faut ni nouveau secret, ni route entrante, ni appel du moteur vers le core. |
| O4. File d'envoi durable du core, alimentée par le moteur | `deliveryIntentId`, `queuePolicy: "required"` | Écartée pour la v1. Deux registres à réconcilier ; la reprise du core refuse de rejouer un envoi ambigu et exige une réconciliation que le SMS n'a pas (`delivery-queue-recovery.ts:711-804`) ; texte réécrit. À reprendre si le registre du moteur devait déléguer la reprise. |

**Appels authentifiés.**
- Core → moteur : MCP en HTTP, `Authorization: Bearer ${OPSYS_MCP_JETON}` (`serveur_mcp.py:143-164`), point d'accès
  `/mcp/m01-front-office`, avec un marqueur `_meta["opsys/origine"] = "envoi"`. C'est l'appel que `callOpsysMcpTool`
  fait déjà (`opsys-contexte-mcp.ts:49-95`).
- Moteur → core : **aucun**.
- Twilio → core : webhook signé (`webhook.ts:167-185`). Core → Twilio : API REST avec le jeton, que seul le core est
  censé porter.

**Où s'accroche le code du core.**
- Le sidecar s'ajoute à `core/src/gateway/server-lifetime-sidecars.ts:134-142`, à côté de `startOpsysMetierSidecar`
  (`core/src/gateway/opsys-metier-supervisor.ts:487-500`) ; fichiers neufs `core/src/gateway/opsys-envoi*.ts`.
- Une extension n'importe pas `core/src/**` (`core/extensions/AGENTS.md:29`) mais le core peut prendre ce qu'elle
  exporte par son `api.ts`. L'extension `sms` exporte donc `sendSmsExactText`, la résolution du compte, et un
  observateur d'accusés de livraison (`setSmsDeliveryObserver`) que `webhook.ts` appelle après `deliveryRecorder.record`
  (`core/extensions/sms/src/webhook.ts:224`), avant de répondre 200 (5xx si l'observateur échoue : Twilio réessaie).
- Le sondage suit la cadence du répartiteur du bus : 3 s (`serveur_mcp.py:34`, `:179-186`). Un client MCP reste ouvert
  pour la boucle, au lieu d'une connexion par sondage.

### Le parcours d'un envoi

```
agent M1   m1_proposer_reponse(texte)         N2   moteur : destinataire tiré de la session de confiance, garde-fou,
                                                   STOP, base et plage vérifiés ; ligne « propose »
                                                   rend envoi_id, empreinte, masque du destinataire, origine du texte
agent M1   m1_envoyer_reponse(envoi_id, texte, destinataire_masque)   N4   -> file d'approbation (nathan_owner)
personne   approuve (console ou app)          approbations.decider exécute l'outil avec les arguments exacts
                                              l'outil : approbateur_en_cours, correspondance avec le registre,
                                              garde repassée ; ligne « approuve » (qui, quand)
core       m1_reserver_envoi   (toutes les 3 s)   moteur : garde repassée, plage ; ligne « reserve » (tentative n)
core       vérifie l'empreinte, la longueur, le compte ; m1_noter_envoi(en_route)   [marqueur]
core       POST Twilio (texte exact)  ->  m1_noter_envoi(poste | rejete | inconnu)
Twilio     rappel d'état (signé) -> core -> m1_noter_livraison   ligne « livraison »
```

L'agent lit le résultat au tour suivant par `m1_lire_reception`, qui rend aussi l'état du dernier envoi. Le texte parti
n'a pas besoin d'être recopié dans la session du core : le registre des envois est la mémoire (P4).

**Ce que le modèle propose : le brouillon du code, ou son propre texte.** La proposition garde l'origine du texte
(`brouillon_du_code` si le texte est celui que la réception a composé et fait passer au garde-fou, `texte_de_l_agent`
sinon). Elle figure dans les arguments de l'approbation : la personne sait ce qu'elle lit.

**Les états** (lignes `envoi` du registre ; l'état est le repli des lignes, comme `transferts.lire`) :

| État | Écrit par | Sorties permises |
|---|---|---|
| `propose` | `m1_proposer_reponse` | `approuve`, `annule` |
| `approuve` | `m1_envoyer_reponse`, après une décision humaine | `reserve`, `annule` |
| `reserve` (tentative n) | `m1_reserver_envoi`, le core | `en_route` ; `non_poste` ; retour à `approuve` si la réservation est périmée (2 min, valeur proposée) **sans** marqueur |
| `en_route` (n) | `m1_noter_envoi`, le core, **avant** la requête | `poste`, `rejete`, `inconnu` |
| `poste` (n, `MessageSid`) | `m1_noter_envoi` | lignes `livraison` (`livre`, `non_livre`) |
| `non_poste` | le core : échec **prouvé** avant la requête | retour à `approuve` (essai suivant) ou `abandon` |
| `rejete` | le core : réponse 4xx du fournisseur | « À voir » (429 : compté comme un essai) |
| `inconnu` | le core, ou le moteur (marqueur sans issue au bout de 2 min) | « À voir », jamais de renvoi automatique |
| `annule` | STOP, refus, fenêtre dépassée, message plus récent, personne | final |
| `abandon` | le moteur, après les essais | « À voir » |

### Au plus une fois

1. La proposition est idempotente : `envoi_id` est déterministe. Une seule proposition est ouverte par conversation
   (`REJ-ENVOI-DEJA-OUVERT`).
2. Une approbation s'exécute une fois (`approbations.py:232-239`). L'outil est de plus idempotent sur l'état : une
   seconde approbation du même `envoi_id` ne change rien.
3. `m1_reserver_envoi` inscrit la réservation dans une transaction : deux appels concurrents ont un seul gagnant.
4. Le marqueur précède la requête. Une réservation sans marqueur est **prouvée non partie** : elle revient à `approuve`.
   Un marqueur sans issue est **inconnu** : jamais rejoué.
5. Le fournisseur n'a pas de clé d'idempotence (`twilio.ts:621-636`) : la garantie est « au plus une fois », pas « au
   moins une fois ». Un client qui reçoit deux fois le même message est pire qu'une personne qui renvoie à la main.
6. `m1_resoudre_envoi(envoi_id, issue, motif)` (N3, humain seul, sur le patron de `m1_clore_transfert` et de
   `_acteur_humain`, `outils.py:926-962`) clôt un envoi « à vérifier » : `parti_a_la_main`, `pas_parti` ou `annule`.
   Aucune issue ne renvoie toute seule ; `pas_parti` permet une **nouvelle** proposition, donc une nouvelle approbation.
7. La vérification d'une issue inconnue chez Twilio (`listTwilioMessages`, `twilio.ts:566-593` : `body`, `dateCreated`,
   `status`) est une aide pour la personne, jamais une preuve.

### Garde d'envoi : consentement, STOP, base, plages

- **STOP ne se lève jamais.** `transferts.retire`
  (`departments/m01-front-office/src/m1_front_office/transferts.py:192-198`) est lu à la proposition, à l'approbation et
  à la réservation. `_enregistrer_retrait` (`outils.py:1137-1196`) annule, dans la même transaction que la ligne du
  STOP, tout envoi non final de la conversation. La politique dit « appliqué dans les 48 heures »
  (POLITIQUE-consentement-sms § 4) : le code l'applique tout de suite, ce qui est plus sévère.
- **Base d'envoi, fenêtre, plages, mention : le profil d'entreprise, sans valeur par défaut** (même patron que
  `fenetre_conversation_minutes`, M1-canaux § 8). Absent, le verdict dit où le déclarer et rien ne part. Les valeurs
  ci-dessous sont des **exemples** :

  ```yaml
  # $OPSYS_HOME/entreprise.yaml
  envoi_client:
    base: reponse_a_un_message                  # ensemble fermé que le code connaît ; absent : aucun envoi
    fenetre_heures: 48                          # entier ; la réponse doit suivre un message du client de moins de 48 h
    plages: [{jours: [lun, mar, mer, jeu, ven], de: "08:00", a: "20:00"}]
    mention_retrait: "Répondez STOP pour ne plus recevoir de messages."
  ```
- **Une réponse, pas un premier contact.** `m1_proposer_reponse` exige un message reçu de cette conversation. Un envoi
  qui commence la conversation (rappel après appel manqué, digest, relance de M2) est hors de cet ADR : il exige un
  consentement actif (POLITIQUE § 4, « missed-call rescue »), tenu par M2
  (`departments/m02-revenue-crm/src/m2_revenue_crm/consentements.py:1-36`) et lu par un événement à créer. La table
  `consent_sms` de M1-canaux § 5 n'est donc **pas** créée.
- **Une proposition meurt avec un message plus récent** du client : la réponse ne répondrait plus à ce qu'il a dit. Elle
  passe à `annule` (`perime`) ; l'agent en propose une autre.
- **La fenêtre** se vérifie aux trois moments ; **les plages** se jouent à la réservation : hors plage, l'envoi approuvé
  attend la prochaine ; hors fenêtre, il est annulé.
- **La mention de retrait**, si le propriétaire en déclare une, est ajoutée par le moteur à chaque proposition (donc
  approuvée avec le texte).
- **La preuve de la base** est écrite à la réservation : heure du dernier message reçu, fenêtre, absence de retrait.
  C'est la trace « consentement documenté » (P8).
- Le CASL est nommé par la mission ; **son contenu n'est pas jugé ici** : POLITIQUE-consentement-sms § 8.1 dit « à
  vérifier par le juriste ». Le code ne fait qu'appliquer ce que le propriétaire et le juriste déclarent.

### Échecs, essais, « À voir »

Valeurs proposées (GATE NATHAN) : trois essais, à une minute puis cinq minutes ; réservation périmée après deux minutes.

| Situation | Ce qui se passe |
|---|---|
| Moteur injoignable au sondage | rien ne part ; le core réessaie au sondage suivant |
| Moteur injoignable au marqueur | le callback lève : rien n'est parti (`core/extensions/sms/src/send.ts:154-162`). Le core tente de dire `non_poste` ; sinon la réservation se périme sans marqueur, donc prouvée non partie, et revient à `approuve` |
| Le moteur a inscrit le marqueur, mais sa réponse s'est perdue | le core ne poste pas (le callback lève), le moteur croit `en_route` → `inconnu` au bout de 2 min : le coût est une vérification par une personne, jamais un doublon |
| Core arrêté après la réservation, avant le marqueur | réservation périmée → **prouvée non partie** → `approuve` (un essai de plus) |
| Core arrêté après le marqueur, sans issue | `inconnu` → « À voir » ; **jamais rejoué** |
| Réponse 4xx de Twilio (`TwilioSmsApiError`, `twilio.ts:173-190`) | `rejete`, avec le statut HTTP et le code du fournisseur → « À voir » ; 429 : essai suivant |
| 5xx, coupure, délai de 30 s, réponse sans SID (`twilio.ts:655-659`) | `inconnu` : le message est peut-être parti |
| Trois échecs prouvés non partis | `abandon` → « À voir » |
| Accusé `undelivered`, `failed` ou `canceled` | ligne `livraison` + « À voir » : le client n'a pas reçu le message |
| Accusé perdu, ou `sent` sans `delivered` | l'état reste `poste` ; ce n'est pas une alerte |
| Accusé arrivé avant l'issue du POST | gardé « orphelin » par `MessageSid`, rattaché quand `poste` arrive |
| STOP entre l'approbation et l'envoi | `annule` (retrait) ; aucune requête |
| Canal inactif (porte fermée, DEFINITION-PRODUIT § 10) | **repli manuel** : pas d'essai, « À voir » avec le texte (`m1_lire_envoi`, admin) ; la personne écrit à la main, puis `m1_resoudre_envoi(parti_a_la_main)` |
| Compte SMS désactivé ou sans numéro d'envoi | même repli |

Une attente « À voir » (`attentes()`, forme de `CHAMPS_ATTENTE`, `approbations.py:62`) porte `type` `envoi_a_verifier`,
un résumé sans donnée personnelle, le niveau N4 et l'action proposée. La lecture du texte et du numéro est un outil
d'admin, journalisé (POLITIQUE § 6).

### Qui peut appeler quoi (envoi)

| Appelant | Peut | Ne peut pas |
|---|---|---|
| Modèle de l'agent M1 | `m1_proposer_reponse` (N2), `m1_envoyer_reponse` (N4, attend une personne), `m1_lire_reception` (T0) | fournir un destinataire, un numéro ou un canal ; appeler les outils réservés au core ; utiliser l'outil `message` du core (refusé, `core/src/agents/tool-policy-match.ts:58`) |
| Propriétaire (`nathan_owner`, seul rôle par défaut : `DEFAUT_ROLES_NIVEAU`, `src/opsys/departements.py:44`) | décider `m1_envoyer_reponse` | — |
| Admin | lire un envoi, clore un envoi « à vérifier » | approuver un N4, sauf si M1 déclare `approbations.n4` (`departements.py:38` : seuls `n3` et `n4` se configurent ; M1 n'en déclare aucun aujourd'hui) |
| Core (sidecar, noyau) | `m1_reserver_envoi`, `m1_noter_envoi`, `m1_noter_livraison`, `m1_recevoir_message_canal` | choisir un texte ou un destinataire : il envoie ce que le moteur remet, l'empreinte vérifiée |
| Moteur | écrire le registre des envois | appeler Twilio ou le core |

Les outils « réservés au core » portent un drapeau du manifeste (`Outil.reserve_au_core`). `openclaw.py` les retire de
la boîte de l'agent (`src/opsys/openclaw.py:153-170`), et chacun exige le marqueur d'origine de l'hôte.
`m1_envoyer_reponse` refuse de lui-même tout appel qui n'est pas l'exécution d'une demande qu'une personne vient
d'approuver (`approbateur_en_cours`) : il reste sûr même si quelqu'un forçait le mode `autonome`, ce que la case ouverte
« Mode autonome et N4 » du PLAN laisse aujourd'hui possible.

### Courriel (ensuite)

- Même registre des envois, même garde. Le fork n'envoie aucun courriel : il faut une extension d'envoi (SMTP) ou un
  adaptateur du moteur. C'est une tranche à part, avec ses décisions : fournisseur SMTP, DKIM, SPF et DMARC (T3), fil de
  la conversation (`In-Reply-To` du courriel reçu, donc le `Message-ID` à inscrire à la réception).
- La session d'un courriel est celle du message (`hook:imap:<clé>`, `core/extensions/imap/src/watcher.ts:340`) : le
  destinataire se lie à ce message, par la même clé de confiance.
- Les bons de commande de M6 vers un fournisseur (DEFINITION-PRODUIT § 10, « Envoi réel d'une commande à un fournisseur
  ») suivront le même rail avec un autre lien de destinataire (le fournisseur de M6, pas une session). Hors de cet ADR.

## Conséquences

- **L'agent M1.** Il n'appelle plus la réception : il lit (`m1_lire_reception`), propose (`m1_proposer_reponse`) et
  demande l'envoi (`m1_envoyer_reponse`). `m1_emettre_notification` est remplacé, et son faux bus sort du chemin de
  production. La skill `recevoir-un-message-de-canal` et le SOUL changent.
- **Le socle.** `Outil.reserve_au_core` ; `opsys.contexte` lit la clé de session et l'origine ; `Capacites._distribuer`
  (`src/opsys/capacites.py:190-236`, point de passage unique) refuse un outil réservé sans marqueur ; `openclaw.py`
  génère `opsys/canaux.json` et les refus de la boîte de l'agent ; `opsys.taxonomie` charge `envoi_client` ;
  `opsys-metier verifier` échoue si la boîte d'un agent contient un outil réservé. Code critique : revue externe
  (`AGENTS.md`).
- **M1.** Modules purs pour les états et la garde, huit outils, une ligne `reception` et des lignes `envoi` au registre,
  `attentes()` de plus, `_enregistrer_retrait` qui annule les envois ouverts.
- **Les tests existants.** Quinze fichiers de tests nomment `m1_recevoir_message_canal` (cascades,
  `tests/test_canal_*.py`, STOP, E2E de la plainte et du formulaire, cinq fichiers de
  `departments/m01-front-office/tests/`). Ceux qui l'appellent par `Capacites` devront poser le marqueur par un aide de
  test commun quand l'exigence s'allume ; l'appel nu (`opsys.outils.executer`) ne change pas.
  `tests/test_openclaw_canaux.py:181-186` (la boîte fermée) reste vrai : les refus ajoutés nomment des outils, jamais
  `opsys_m1__*`.
- **Le core.** Deux modules neufs (`core/src/channels/turn/opsys-reception.ts`, `core/src/gateway/opsys-envoi*.ts`),
  trois points d'insertion pour la réception (`run-channel-turn.ts`, `agent-bundle-mcp-runtime.ts`,
  `opsys-contexte-mcp.ts`), trois pour l'envoi (`server-lifetime-sidecars.ts`, `send.ts`, `webhook.ts` de l'extension
  `sms`, plus son `api.ts`). Le code du core ne s'exécute pas dans ce bac à sable : la CI est l'autorité. Chaque fichier
  touché sous `src/gateway/**` ou `src/agents/**` voit ses tests, neufs et voisins d'origine, inscrits dans
  `core/test/opsys-tests-cibles.txt:8-9` (la règle de la liste) : `test:fast` ne les lance pas.
- **Deux runtimes.** Un appel MCP local toutes les 3 s au repos (lecture seule, sans écriture). Le journal d'accès
  d'uvicorn le montre : le filtre de `serveur_mcp.py:131-140` ne retire que `GET /sante`.
- **Le jeton Twilio est dans l'environnement du moteur.** Le préfixe `OPSYS_` (`opsys-metier-env.ts:82-86`) laisse
  passer `OPSYS_SMS_JETON`, contre le principe écrit à `:50-52`, et le compose le donne au conteneur `opsys`
  (`deploy/docker-compose.yml:164-168`). Le moteur n'en a besoin que pour savoir qu'il est non vide
  (`canaux.manquantes`, `src/opsys/canaux.py:101-103`). Correctif proposé (tranche c9) : le core donne au moteur un
  témoin « présent », jamais la valeur.
- **Loi 25.** Le numéro et le texte envoyés sont chiffrés par une clé destructible ; l'empreinte et le masque restent en
  clair. `approbations.arguments` garde le texte en clair (`approbations.py:93-97`, table non purgée) : sa rétention
  reste à décider avec POLITIQUE § 5 (« historique minimal des envois : date, contenu type, statut », § 3).
- **Jetons de modèle.** Plus aucun token de sortie pour recopier des champs. Un tour de modèle par message reste ; le
  sauter quand le verdict du moteur n'exige rien est une piste, hors de cet ADR (P11).
- **Test de l'envoi avec le vrai core.** L'URL de l'API Twilio est une constante (`twilio.ts:22`) : le faux Twilio de
  l'`e2e-core` exige un réglage explicite `dangerously…`, refusé hors test, sur le modèle de
  `dangerouslyDisableSignatureValidation` (`core/extensions/sms/src/config-schema.ts`).
- **Briques.** Aucune dépendance nouvelle pour le SMS (le `fetch` du core suffit). Un envoi de courriel en demandera une
  : licence à vérifier et inscription à `docs/research/INGREDIENTS.md` avant adoption (`AGENTS.md`).

## Ce qui reste T3 (humain seul)

- Fournir les cinq variables du canal SMS : compte, jeton, numéro, URL publique du webhook, attestation. Ce sont des
  secrets de production (`src/opsys/canaux.py:73-85`, M1-canaux § 4).
- **Attester les politiques** : `OPSYS_SMS_POLITIQUES_VALIDEES` porte la validation écrite de Nathan (SMS et photos) ;
  elles sont des PROPOSITIONS tant qu'elle manque (`docs/compliance/politiques/README.md`). Le juriste tranche ce que
  POLITIQUE § 8.1 lui laisse.
- **Mettre en ligne** : l'URL publique du webhook Twilio et, plus tard, celle du formulaire du site.
- **Faire le premier envoi réel** à un vrai numéro : un engagement externe (`AGENTS.md`, frontières humaines).
- Garder le département en `ombre` ou `supervise` : `autonome` reste refusé (`src/opsys/canaux.py:236-247`).
- Tant que ces portes sont fermées, l'état est « PARTIEL — GATE NATHAN » (DEFINITION-PRODUIT § 5 P6) et le repli manuel
  de la décision 8 s'applique.

## Ce que le propriétaire décide (GATE NATHAN)

Rien de ceci n'a de valeur par défaut dans le code : sans décision, le système le dit. Les valeurs entre parenthèses
sont des propositions.

1. **La voie.** Réception dans le noyau avec la file durable du canal (option C), envoi par un core exécuteur qui vient
   chercher (O3). Ou une autre voie de la liste des options.
2. **Qui approuve un message au client** : `approbations.n4` de M1. Défaut : `nathan_owner` seul
   (`src/opsys/departements.py:44`). L'admin peut-il aussi ? (DEFINITION-PRODUIT § 9.5 : l'admin « envoie la réponse
   approuvée ».)
3. **La base d'envoi d'une réponse.** Répondre à un message du client sans opt-in écrit, dans une fenêtre (48 h ?), ou
   exiger un opt-in explicite même pour une réponse. À trancher avec le juriste (CASL).
4. **Les plages d'envoi.** POLITIQUE § 2 les dit « déjà présentes » : aucune n'existe dans le code.
5. **La mention de retrait** dans chaque message (« Répondez STOP… ») : oui ou non, et le texte. Et l'accusé de retrait
   après un STOP : aucun message aujourd'hui (M1-canaux § 5).
6. **Les essais** (trois, à une minute puis cinq) et la réservation périmée (deux minutes).
7. **Une proposition survit-elle à un nouveau message du client ?** (Non : elle est annulée.)
8. **Un seul envoi ouvert par conversation.** (Oui.)
9. **La rétention** du texte et du numéro envoyés (chiffrés, clé destructible ; durée : POLITIQUE § 5, « 3 ans », à
   vérifier).
10. **Le lien automatique session → affaire** (case ouverte de T2.1-b) : possible sans modèle, toujours à décider.
11. **La voie du formulaire** (T4.17-e4) : recommandation de cet ADR, un plugin dédié qui offre un point d'accueil HTTP
    sans modèle et sert le même client de réception et la même file durable ; l'autre voie (`hooks` du core, où le
    modèle recopierait le `utm`) est écartée. À trancher, avec le contrôle anti-abus (débit, pot de miel).
12. **Le jeton Twilio hors du moteur** (tranche c9) : oui ou non.

## Mise en œuvre : tranches

Chaque tranche se prouve seule et se commite seule. L'ordre est c1, c2, c3 pour la réception ; c4 à c8 pour l'envoi (c4
et c5 ne demandent pas le core) ; c9 à part. Les fichiers du core sont inscrits à `core/test/opsys-tests-cibles.txt`.

**T2.1-c1 — Moteur : clé de session de confiance, marqueur d'origine, `m1_lire_reception`** (Python, sans le core).
- `opsys.contexte` lit `opsys/cleSession` et `opsys/origine`, que `serveur_mcp.appeler_outil` pose comme l'identité
  d'appareil (`serveur_mcp.py:80-84`). Drapeau `Outil.reserve_au_core` et refus dans `Capacites` (aucun outil n'est
  encore marqué). `openclaw.py` retire ces outils de la boîte et génère `opsys/canaux.json` (éteint par défaut). Ligne
  `reception` (réponse complète, bornée) dans la transaction du signal. `m1_lire_reception` (T0).
  `m1_recevoir_message_canal` compare la clé de confiance à `canaux.cle_session` (`REJ-CLE-SESSION-DIVERGENTE`) et
  inscrit un MMS sans texte (`pieces_jointes`) sans le qualifier, avec une attente « À voir ».
- *Preuve.* pytest de M1 et du socle, par `Capacites` : la relecture rend la réponse d'alors (brouillon, questions,
  score compris) ; un rejeu n'ajoute aucune ligne ; une clé divergente est refusée sans écriture ; sans `_meta`, «
  aucune session » (fermé) ; un MMS sans texte est inscrit et visible dans « À voir » ; un outil marqué est absent de la
  boîte (`tests/test_openclaw_canaux.py`) ; ruff ; `opsys-metier verifier` ; mutations sur la comparaison de clé et sur
  le refus sans marqueur.

**T2.1-c2 — Core : la réception avant le tour, attendue, durable** (TypeScript, CI).
- `core/src/channels/turn/opsys-reception.ts`, appelé dans `run-channel-turn.ts` avant le dispatch ; `callOpsysMcpTool`
  gagne un paramètre `meta` ; `agent-bundle-mcp-runtime.ts` pose `opsys/cleSession` pour les serveurs `opsys_mN`
  seulement ; lecture de `opsys/canaux.json`.
- *Preuve.* Vitest, `pnpm test` sur les fichiers inscrits : correspondance des champs (E.164, `MessageSid`, heure ISO,
  texte brut, clé réelle) ; moteur injoignable, l'appel lève et la file garde puis rejoue l'événement (motif de
  `ingress-spool.test.ts`) ; refus permanent, échec de la file sans boucle ; configuration absente ou agent non déclaré,
  aucun appel ; `_meta` reçu par un vrai serveur MCP stdio (motif de `opsys-contexte-mcp.wire.test.ts`) ; clé de session
  absente pour un serveur qui n'est pas OPSYS ; jobs `tests` et `tests-opsys` de `core.yml` verts.

**T2.1-c3 — Bout en bout de la réception, puis l'exigence du marqueur** (`e2e-core` et M1).
- Faux Twilio dans `tests/e2e_core/` (signe le formulaire avec le jeton de test). `m1_recevoir_message_canal` est marqué
  « réservé au core ». La skill et le SOUL disent « lis la réception ». Un aide de test commun pour les tests qui
  passent par `Capacites`.
- *Preuve.* `python tests/e2e_core/scenario.py` : un SMS donne un signal et un lead ; le même `MessageSid` ne donne
  qu'une ligne ; moteur arrêté, le SMS est admis (200) et rien n'est au registre, moteur relancé, il y est en moins de 3
  min ; un STOP est inscrit ; l'appel d'un agent à la réception donne `REJ-ORIGINE-REQUISE` ; `pytest tests/e2e_core`
  (répétition sans core), M1 et socle verts.

**T2.1-c4 — Moteur : le registre des envois et la garde, sans réseau** (Python).
- `m1_proposer_reponse` (N2), `m1_envoyer_reponse` (N4), `m1_lire_envoi` (T0, admin), `m1_resoudre_envoi` (N3, humain
  seul) ; modules purs pour les états et la garde ; profil `envoi_client` (`opsys.taxonomie`, verdicts qui disent où
  déclarer) ; numéro et texte chiffrés ; le STOP annule dans sa propre transaction ; `attentes()`.
- *Preuve.* pytest par `Capacites` et `approbations.decider` : la proposition n'a aucun effet externe ; `nathan`
  approuve et la ligne `approuve` porte son nom, un employé est refusé ; un texte ou un masque qui diffère est refusé ;
  un STOP entre la proposition et l'approbation annule ; fenêtre dépassée ou message plus récent, refus ; profil absent,
  le verdict dit où déclarer ; deux propositions ouvertes, la seconde est refusée ; rejeu, un seul envoi ; le corpus
  adversarial du garde-fou (44 textes interdits) est rejoué sur la proposition ; en mode `autonome` l'outil refuse sans
  approbateur humain ; mutations sur le STOP, l'empreinte et l'approbateur.

**T2.1-c5 — Moteur : les outils du core pour l'envoi** (Python).
- `m1_reserver_envoi`, `m1_noter_envoi`, `m1_noter_livraison`, marqués « réservés au core » (marqueur `envoi`) ;
  réservation périmée ; essais bornés ; accusés orphelins ; attentes « À voir ».
- *Preuve.* pytest exhaustif de la machine à états : chaque transition permise et chaque refusée ; deux `reserver`
  concurrents, un seul gagnant ; `en_route` sans issue devient `inconnu` et n'est jamais réoffert ; réservation sans
  marqueur, retour à `approuve` ; trois `non_poste`, `abandon` ; accusé arrivé avant `poste`, rattaché ensuite ;
  `undelivered`, attente ; canal inactif, repli manuel sans essai ; STOP à la réservation, `annule`.

**T2.1-c6 — Core : l'exécuteur SMS, texte exact, un seul POST** (TypeScript, CI).
- `sendSmsExactText` dans `send.ts`, exporté par `api.ts` ; sidecar `core/src/gateway/opsys-envoi*.ts` accroché à
  `server-lifetime-sidecars.ts:134-142` ; classement `non_poste`, `rejete`, `inconnu` ; aucun repli sur `defaultTo`
  (`channel.ts:245`).
- *Preuve.* Vitest, avec un faux `fetch` qui compte les POST : le `Body` est, octet pour octet, le texte approuvé sur un
  corpus (accents, émoji, sauts de ligne, `*_[]()`, adresse web), que `toSmsPlainText` **change** pour une partie de ce
  corpus ; un texte de plus de `min(textChunkLimit, 1 600)` est refusé sans requête ; une empreinte qui diffère n'envoie
  rien ; un callback de marqueur qui échoue n'envoie rien ; 4xx donne `rejete` ; une coupure après le marqueur donne
  `inconnu` et jamais un second POST ; un destinataire vide est refusé.

**T2.1-c7 — Accusés de livraison du core vers le moteur** (TypeScript et Python).
- `setSmsDeliveryObserver` (`api.ts`), appelé par `webhook.ts` après `record`, même pour un doublon ; 5xx si le moteur
  est injoignable.
- *Preuve.* Vitest voisin de `webhook.test.ts` : chaque rappel signé appelle l'observateur, un doublon aussi, un moteur
  injoignable donne 503 ; pytest : `m1_noter_livraison` idempotent.

**T2.1-c8 — Bout en bout de l'envoi** (`e2e-core`).
- Faux Twilio complet (API et rappels) ; réglage `dangerously…` de l'URL de l'API, refusé hors test.
- *Preuve.* `scenario.py` : approuvé, exactement un POST au texte exact ; core arrêté après le marqueur, `inconnu` sans
  second POST ; 4xx, « À voir » ; STOP entre l'approbation et l'envoi, aucun POST ; rappel `delivered`, ligne
  `livraison` ; canal inactif, repli manuel.

**T2.1-c9 — Durcissement : le jeton Twilio hors du moteur** (TypeScript et déploiement).
- `buildOpsysMetierChildEnv` remplace les variables de canal secrètes par un témoin « présent » ; `docker-compose.yml`
  cesse de les donner au conteneur `opsys`.
- *Preuve.* Vitest de `opsys-metier-env.test.ts` : le moteur reçoit la variable non vide, jamais la valeur ; pytest de
  `tests/test_openclaw_canaux.py` : l'activation ne change pas.

**Après ces tranches, hors de cet ADR** : la réception du courriel (`watcher.ts:345`) et de la voix (`events.ts:420`)
par le même client (T2.1-d) ; le courriel sortant ; le récepteur du formulaire (T4.17-e4) ; les messages qui commencent
une conversation (M2, appel manqué, digest). À noter pour T2.1-d : M1-canaux § 7 propose d'appeler
`dispatchHookAgentTurn` depuis `voice-call`, mais le core refuse tout `externalContentSource` autre que `email`
(`core/src/gateway/server/hooks.ts:660-662`).

## Ce qui n'est pas vérifié ici

Le core ne s'exécute pas dans ce bac à sable : tout ce qui touche `core/` est une lecture de source. La CI (`core.yml`,
`e2e-core.yml`) est l'autorité.
- Que `runtime.sessionKey` de `agent-bundle-mcp-runtime.ts:1012` est la clé que `cle_session` calcule pour un SMS (les
  deux viennent de `resolveAgentRoute`, `inbound.ts:182-191` : lecture, pas exécution).
- Qu'une exception levée entre `resolveTurn` et le dispatch remonte à la file, nettoyage des pièces jointes compris
  (`run-channel-turn.ts:250-283`, `inbound.ts:317-322`).
- Que le `MessageSid` d'un rappel est celui que la réponse d'envoi rend (`twilio.ts:655-665`,
  `delivery-observations.ts:59-65`).
- Que le `_meta` d'un appel d'agent atteint le moteur en HTTP « streamable » : le test existant le prouve pour la porte
  d'appareil (`core/src/agents/agent-bundle-mcp-runtime.mcp-call-meta.test.ts`).
- Le comportement de Twilio (relances, réponses aux STOP, états par opérateur) est hors du dépôt : à vérifier avec le
  fournisseur en T3.
- Les valeurs proposées (trois essais, une minute puis cinq, deux minutes) sont des propositions, pas des mesures.
- Aucun test n'a été lancé pour cet ADR : c'est un document. Il n'existe pas de `tests/test_docs*.py` qui lise les ADR.
