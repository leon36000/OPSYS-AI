# ADR-0011 — Canaux : réception sans modèle et envoi réel au client après approbation N4

- Statut : **Proposé** (rédaction confiée par l'ingénieur en chef, 2026-09-29). **La décision appartient au propriétaire**
  (GATE NATHAN, section « Ce que le propriétaire décide »). Rien n'est codé : cet ADR ne touche ni `core/`, ni `src/`,
  ni un département.
- Complète : [ADR-0008](ADR-0008-fork-openclaw-opsys-core.md) (canaux du core, moteur derrière MCP),
  [ADR-0009](ADR-0009-socle-metier.md) (échelle N0–N5, approbations) et [ADR-0010](ADR-0010-memoire.md) (session, affaire).
  Ne remplace aucun ADR. Il tranche ce que [`M1-canaux.md`](../departements/M1-canaux.md) laissait ouvert : le crochet
  `message_received` (§ 7), la table `consent_sms` (§ 5) et l'envoi réel (§ 6).
- Fondé sur : la [définition produit](../produit/DEFINITION-PRODUIT.md) (§ 1, § 5 P1 P8 P9 P10, § 7 M1, § 9, § 10), la
  lecture du fork (chaque `fichier:ligne` ci-dessous a été lu dans ce dépôt, pas retenu de mémoire),
  [`POLITIQUE-consentement-sms`](../compliance/politiques/POLITIQUE-consentement-sms.md), PLAN T2.1 et T4.17-e3/e4.

## Contexte

Un client écrit « mes gouttières débordent, à Laval ». Deux choses manquent entre son téléphone et le registre de M1.

**À l'entrée, le modèle fait la copie.**
- Le core livre le message à l'agent M1 avec des blocs que la plateforme génère : canal, expéditeur, `message_id`, heure.
  Le modèle les recopie dans `m1_recevoir_message_canal` (étape 1 de
  `departments/m01-front-office/skills/recevoir-un-message-de-canal/SKILL.md:12`). L'outil est N2
  (`departments/m01-front-office/src/m1_front_office/outils.py:1359-1417`).
- Le code borne la forme des champs (`departments/m01-front-office/src/m1_front_office/reception.py:193-224`). Il ne peut
  pas savoir que l'expéditeur recopié est celui qui a écrit. Une consigne cachée dans le texte d'un client peut faire
  recopier un autre expéditeur ou un autre texte (par exemple un « STOP » au nom d'un tiers, que l'outil inscrirait comme
  retrait de consentement).
- Le modèle peut aussi oublier l'appel, ou le refaire avec d'autres champs. Chaque message coûte un tour.
- M1-canaux § 7 proposait le crochet `message_received` du core, avec un journal de reprise « à décider ».

**À la sortie, rien ne part.**
- `m1_emettre_notification(canal, message)` est N4 (`outils.py:1636-1653`). Une fois approuvé, son corps appelle un faux bus
  en mémoire (`outils.py:394-402`, `departments/m01-front-office/src/m1_front_office/adaptateurs.py:76-83`).
- L'outil n'a ni destinataire ni conversation : `canal` est une chaîne libre. Le contrat ne dit pas à qui écrire.
- Le core saurait envoyer, mais il réécrit le texte (§ Question 2) et rien ne lie l'envoi à l'approbation.

Le test de dérive de `AGENTS.md` passe : tout ce qui suit parle de clients, de leads, de plaintes, d'approbations du
propriétaire et de messages de gouttières (M1.4, M1.7, M1.8, M1.12 ; P1, P8, P9).

## Décisions proposées

1. **Réception : le core appelle lui-même `m1_recevoir_message_canal`, dans le noyau des tours de canal, avant le tour de
   l'agent, en attendant la réponse.** Il tire les champs du contexte que la plateforme a vérifié (signature Twilio), jamais
   du modèle. Toute panne lève une exception : la file durable du canal garde le message et réessaie. L'idempotence est celle
   du moteur (`signal_id = <canal>:<message_id>`). Le crochet `message_received` n'est pas le mécanisme.
2. **Le modèle ne recopie plus rien.** `m1_recevoir_message_canal` sort de sa boîte d'outils, et le moteur l'exige d'un
   appelant du core (marqueur `_meta` posé par l'hôte). L'agent lit le résultat par `m1_lire_reception` (T0).
3. **Session de confiance.** Le core pose la clé de session réelle dans le `_meta` MCP de tout appel vers un serveur
   `opsys_mN`, jamais vers un autre serveur (la clé contient le numéro du client). Le moteur s'en sert pour tout ce qui vise
   « cette conversation ». Aucun argument ne peut la nommer.
4. **Envoi en deux outils.** `m1_proposer_reponse(texte)` (N2) écrit une proposition liée à la conversation de la session.
   `m1_envoyer_reponse(envoi_id, texte, destinataire_masque)` (N4) est approuvé par une personne ; il ne fait qu'inscrire
   l'approbation. Aucun outil du modèle ne prend un numéro, une adresse ou un canal.
5. **Le moteur tient le grand livre, le core exécute.** Le grand livre est fait de lignes `envoi` du registre de M1
   (ajout seul, chaîne de hash). Le core vient chercher les envois approuvés (sondage toutes les 3 s, par l'appel MCP qu'il
   fait déjà), envoie le texte exact par un chemin qui ne le réécrit pas, et rend l'issue. Aucun appel du moteur vers le core,
   aucun secret de plus.
6. **Au plus une fois.** Un marqueur est inscrit avant la requête à Twilio. Une issue inconnue n'est jamais rejouée : elle va
   à « À voir ». Un échec prouvé avant la requête est réessayé (trois essais proposés), puis va à « À voir ».
7. **Garde d'envoi sans valeur par défaut.** STOP ne se lève jamais. La base d'envoi, la fenêtre de réponse et les plages
   viennent du profil d'entreprise ; absentes, le verdict dit où les déclarer. La garde joue à la proposition, à
   l'approbation et à la réservation. Un message plus récent du client périme la proposition.
8. **Porte fermée = repli manuel.** Canal inactif : l'envoi approuvé va tout de suite à « À voir » avec son texte. Une
   personne l'envoie à la main, puis le clôt (DEFINITION-PRODUIT § 5 P6 et § 10).
9. **Courriel plus tard, même grand livre.** Le fork n'envoie aucun courriel. L'exécuteur SMTP est une tranche à part.
10. **T3 et propriétaire.** Activer Twilio, attester les politiques, mettre en ligne, faire le premier envoi réel : humain
    seul. Les valeurs du profil, l'approbateur, la mention de retrait et la voie du formulaire : GATE NATHAN.

## Question 1 — Réception sans modèle

### Ce que le fork offre déjà

| Pièce | Où | Ce qu'elle garantit |
|---|---|---|
| Signature Twilio, limites de débit, 200 après écriture durable | `core/extensions/sms/src/webhook.ts:167-185`, `:268-279` | expéditeur, corps et `MessageSid` sont ceux que Twilio a signés ; le fournisseur n'a son 200 qu'après la validation de SQLite |
| File durable du canal (« spool ») | `core/extensions/sms/src/ingress-spool.ts:113-176` | le message reste jusqu'à ce que sa livraison à l'agent réussisse ; une exception de livraison veut dire nouvel essai |
| Politique d'essai | `core/src/channels/message/ingress-retry-policy.ts:16-19,89-97` ; `core/src/channels/message/ingress-monitor.ts:167-170` | délai de 1 s doublé jusqu'à 3 min ; échec définitif seulement après 8 essais **et** 24 h ; erreur permanente : échec tout de suite (`core/src/channels/message/ingress-drain.ts:237-275`) |
| Rejeu manuel | `core/src/cli/channels-cli.ts:281-316` | `openclaw channels dead-letters list` et `resubmit --channel sms` |
| Noyau des tours de canal | `core/src/channels/turn/run-channel-turn.ts:162-341` | `ingest`, `classify`, `preflight`, `resolveTurn`, dispatch : tout est attendu, une exception remonte à la file |
| Crochet `message_received` | `core/src/auto-reply/reply/message-received-hooks.ts:15-57` | observation « fire and forget » |
| Crochet `before_dispatch` | `core/src/auto-reply/reply/dispatch-from-config.choose-route.ts:564-651` | attendu, avant le modèle ; peut « prendre » le message |
| Appel du moteur depuis le core | `core/src/context-engine/opsys-contexte-mcp.ts:49-95` | MCP, jeton `OPSYS_MCP_JETON`, une connexion par appel (`:9-10`) |
| `_meta` maîtrisé par l'hôte | `core/src/agents/mcp-call-meta.ts:1-29` ; `core/src/agents/agent-bundle-mcp-runtime.ts:1056-1075` | jamais un argument que le modèle peut forger ; posé aujourd'hui seulement pour la porte d'appareil |

### Les options

**A. Crochet `message_received` (piste de M1-canaux § 7).**
- *Chemin.* `emitMessageReceivedHooks` (`message-received-hooks.ts:35-44` pour le crochet de plugin, `:45-56` pour le crochet
  interne), appelé à `core/src/auto-reply/reply/dispatch-from-config.prepare-operation.ts:397` (chemin normal), `:79` (commande
  rapide) et `core/src/auto-reply/reply/dispatch-from-config.prepare-context.ts:518`. Forme de l'événement :
  `core/src/hooks/message-hook-mappers.ts:513-545`.
- *Core.* Un plugin OPSYS s'abonne et appelle `callOpsysMcpTool`. Pour ne rien perdre, il lui faut un journal : une file
  `openChannelIngressQueue` que le plugin vide vers le moteur (jamais un `PluginStateKeyedStore`, qui évince ses plus vieilles
  entrées : `core/extensions/sms/src/delivery-observations.ts:112-126`).
- *Pannes.* L'appel n'est pas attendu ; sa panne est une ligne de journal détaillé (`core/src/hooks/fire-and-forget.ts:80-88`,
  `logVerbose`). Il court en même temps que le tour : rien n'oblige le journal à être écrit avant que le tour se termine. Il
  n'est pas émis quand la session est occupée (`dispatch-from-config.prepare-operation.ts:193-198`) ni dans les sorties précoces
  (`dispatch-from-config.prepare-operation.ts:200-222`) : son heure dépend du répartiteur de réponses, pas du webhook. Il ne couvre ni le courriel ni
  la voix (autres chemins : `core/extensions/imap/src/watcher.ts:345`, `core/extensions/voice-call/src/manager/events.ts:420`).
- *Sécurité.* Le modèle reste dans la boucle tant que l'outil est dans sa boîte.
- *Coût.* Moyen : plugin, journal et son propre drain, qui refont ce que la file du canal fait déjà.
- *Tests.* Vitest sur le plugin. L'`e2e-core` exige un tour d'agent (faux fournisseur de modèle), car le crochet est émis par le
  répartiteur de réponses.
- *Verdict.* Écartée comme mécanisme de réception. Elle reste utile comme observation.

**B. Crochet `before_dispatch` (attendu), rendu fail-closed.**
- *Chemin.* `dispatch-from-config.choose-route.ts:582-587` : `await hookRunner.runBeforeDispatch(...)` avec `messageId`, `content`,
  `channel`, `sessionKey`, `senderId`, `timestamp` (`:587-602`). `handled: true` (`:625`) évite le modèle.
- *Core.* Une ligne dans la politique d'échec globale : `before_dispatch: "fail-closed"` à
  `core/src/plugins/hook-runner-global.ts:31-35`. Sans elle, l'exception d'un crochet est journalisée et le tour continue
  (`core/src/plugins/hooks.ts:314`, `:591-602`, `:927-930`).
- *Pannes.* Avec cette ligne, l'exception remonte au canal et la file réessaie. Mais le crochet ne tourne que si
  `allowInboundHandlers`, `runtimeTakeoverHooksAllowed` et `hasHooks` sont vrais (`dispatch-from-config.choose-route.ts:565-568`), après les
  sorties précoces de `dispatch-from-config.prepare-operation.ts`. Un crochet sauté ne se signale pas : le canal a le message, le moteur ne l'a jamais reçu et
  personne ne le sait.
- *Sécurité.* La politique fail-closed vaut pour le `before_dispatch` de tous les plugins.
- *Coût.* Faible. *Tests.* Comme A.
- *Verdict.* Meilleure que A. Écartée : la garantie dépend de conditions du répartiteur de réponses, pas du canal.

**C. Appel du core dans le noyau des tours de canal, avant le dispatch, attendu (recommandée).**
- *Chemin.* Dans `runChannelTurn`, entre `assembleResolvedChannelTurn` (`run-channel-turn.ts:237`) et l'entrée dans le `try`
  (`:252`). Le contexte normalisé est là : `RawBody`, `From`, `SenderE164`, `MessageSid`, `Timestamp`
  (`core/src/auto-reply/templating.ts:137,148,174,330,334`), et la clé de session (`resolved.routeSessionKey`, `run-channel-turn.ts:245`). Pour un
  SMS, ce point est atteint par la file durable : `ingress-spool.ts:143-148`, puis `dispatchSmsInboundEvent`
  (`core/extensions/sms/src/inbound.ts:100-323`), puis `inbound.run` (`inbound.ts:216`), lié à `runChannelTurn` par
  `core/src/plugins/runtime/runtime-channel.ts:130`.
- *Core.* `core/src/channels/turn/opsys-reception.ts` (nouveau) :
  - lit `opsys/canaux.json`, généré par `opsys-metier openclaw configurer`, éteint par défaut, sur le patron de `contexte.json`
    (`core/src/context-engine/opsys-contexte-config.ts:1-36`) ;
  - n'agit que pour l'agent et le canal qu'il nomme (M1, `sms`) ;
  - appelle `m1_recevoir_message_canal` par `callOpsysMcpTool`, qui gagne un paramètre `meta` ;
  - laisse remonter toute panne.
- *Pannes et reprise.* Voir le tableau ci-dessous.
- *Sécurité.* Voir « Qui peut appeler quoi ».
- *Coût.* Un appel MCP local par message ; aucun token de sortie pour recopier des champs ; un module neuf, trois points
  d'insertion, un fragment généré.
- *Tests.* Vitest (§ Mise en œuvre) et `e2e-core` **sans modèle** : le webhook signé suffit, puisque la réception précède le tour.
- *Placement voisin.* Le même appel dans `dispatchSmsInboundEvent`, avant la matérialisation des pièces jointes
  (`inbound.ts:133-144`), éviterait de télécharger un MMS que le moteur n'a pas encore accepté. Mais une extension n'importe pas
  `core/src/**` (`core/extensions/AGENTS.md`, « Boundary Rules ») : il faudrait un sous-chemin du SDK des plugins, donc des
  fichiers de référence à mettre à jour. Le noyau ne demande rien de tel ; son seul coût est un MMS téléchargé de nouveau à chaque
  essai quand le moteur est en panne.

**D. Plugin OPSYS dédié (`core/extensions/opsys-canaux`).**
- Il porterait le crochet ou la route, son journal et le client du moteur. Il paie la frontière des extensions (pas d'import de
  `core/src/**`, donc un sous-chemin du SDK pour `callOpsysMcpTool`) et double la file que le canal SMS a déjà.
- C'est le bon foyer du **récepteur du formulaire** (T4.17-e4) : `registerPluginHttpRoute` avec `auth: "plugin"` est le patron
  (`core/extensions/sms/src/gateway.ts:120-132`), et la même file durable et le même client de réception servent le formulaire.
- *Verdict.* Pas pour le SMS ; à reprendre pour le formulaire.

**Autre : le moteur écoute Twilio lui-même.** Écartée. Le Gateway est le seul point d'entrée HTTP (ADR-0008, décision 2).

### Pannes et reprise (option C)

| Situation | Ce qui se passe |
|---|---|
| Moteur arrêté ou lent, moins de 24 h | l'appel lève ; l'événement reste dans la file ; essais de 1 s à 3 min ; à la reprise, le message entre, dans l'ordre pour un même expéditeur (`ingress-spool.ts:127-128`) |
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
| N'importe quel autre client MCP du jeton | rien de plus qu'aujourd'hui | poser la clé de session ou le marqueur : ils viennent de l'hôte, pas des arguments |

Le marqueur est `_meta["opsys/origine"] = "reception"`. Il est posé par `callOpsysMcpTool`, jamais par un outil du modèle.
Le moteur le lit comme il lit déjà l'identité d'appareil (`src/opsys/serveur_mcp.py:80-84`, `src/opsys/contexte.py:159`).
Le serveur MCP n'a qu'un jeton pour tous ses appelants (`serveur_mcp.py:143-164`) : la séparation est faite par la boîte de
l'agent **et** par ce marqueur. L'exigence du marqueur s'allume à la dernière tranche de réception, avec le core en place.

### Recommandation

**Option C.** Le noyau appelle le moteur avant le tour, et la file durable du canal est le journal de reprise : elle existe,
elle est testée, elle a une commande de rejeu. Le moteur reste l'autorité de l'idempotence. Le crochet `message_received` sert
au plus d'observation.

### Ce que voit l'agent

- Il ne recopie rien. Il appelle `m1_lire_reception` (T0, sans argument). L'outil lit la clé de session de confiance et rend la
  dernière réponse de réception de cette conversation, entière (décision, brouillon, questions, score), plus l'état du dernier
  envoi (§ Question 2).
- La réponse complète est inscrite au registre dans la même transaction que le signal : `_signal_deja_recu` ne rend aujourd'hui
  que la forme réduite d'un doublon (`outils.py:1081-1134`), sans le brouillon ni le score.
- La skill `recevoir-un-message-de-canal` et le SOUL de M1 changent. Les deux paramètres que `m1_transferer` et
  `m1_escalader_plainte` font recopier (`outils.py:1550-1556`, `:1581-1588`) se retirent de la même façon, dans une tranche
  suivante hors de cet ADR.
- **Le lien automatique session → affaire** (case ouverte de T2.1-b) devient techniquement possible sans modèle : la clé réelle
  est connue de confiance. Il reste une décision de confidentialité du propriétaire (M1-canaux § 3) ; cet ADR ne la prend pas.
- Le core envoie la clé réelle ; le moteur la compare à `canaux.cle_session` (`src/opsys/canaux.py:110-124`) et refuse une
  divergence (`REJ-CLE-SESSION-DIVERGENTE`). Cela ferme la réserve « non vérifié ici » de M1-canaux § 7.
