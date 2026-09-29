# M1 et les canaux du core (PLAN T2.1-a)

**Date :** 2026-09-29. **Portée de cette tranche :** un message SMS de client arrive à l'agent M1 par le canal du
core, est qualifié par le code, et devient un lead v2 que M2 recevra par le bus. Rien n'est envoyé au client. Le
courriel a son outil (même chemin) mais pas sa configuration ; la voix vient après.
**Suite (T2.1-b, partie 1, 2026-09-29) :** M2 consomme vraiment `m1.lead_qualifie` (§7).
**Références :** `DEFINITION-PRODUIT` §5, §6, §7 (M1.1, M1.3, M1.4, M1.7), `M1-audit.md`, ADR-0010 (T3.3-suite-b).
**Le core ne s'exécute pas dans ce bac à sable.** Tout ce qui suit sur le core vient de la lecture de ses sources
(`fichier:ligne` donnés) ; la CI (`e2e-core`, `openclaw config validate`) est l'autorité.

## 1. Le chemin d'un SMS

```
client ──SMS──> Twilio ──webhook──> extensions/sms (core)
   signature Twilio vérifiée, limites de débit, reprise durable sans doublon
   expéditeur admis (dmPolicy « open »)                       core/extensions/sms/src/webhook.ts, inbound.ts:112-125
      │ routing.resolveAgentRoute(canal « sms », pair = numéro E.164)      inbound.ts:182
      ▼
   liaison  bindings[] : canal sms -> agent m01-front-office, dmScope « per-channel-peer »
   clé de session  agent:m01-front-office:sms:direct:+1514…    core/src/routing/session-key.ts:240, resolve-route.ts:634
      │
      ▼
   tour de l'agent M1 (outils fermés : opsys_m1__* seulement)
   le modèle voit « Message Context » (channel) et « Conversation info » (sender, message_id, timestamp)
      │ m1_recevoir_message_canal(canal, expediteur, message_id, recu_le, texte)       N2, sans approbation
      ▼
   M1 : provenance -> registre anti-perte -> qualification (taxonomie, zone) -> LeadQualifie v2
        + événement m1.lead_qualifie, dans la même transaction        src/opsys/evenements/catalogue/m1.lead_qualifie.json
      │ bus (repartir, idempotent)
      ▼
   M2 : consomme m1.lead_qualifie (T2.1-b, §7) : ingestion complète et idempotente ; un refus lève, puis quarantaine

   réponse au client : aucune. Le texte final de l'agent est retenu (sendPolicy) ; l'outil « message » du core lui est
   retiré ; seul m1_emettre_notification (N4) écrit à un client, et une personne doit l'approuver.
```

Ce que l'extension livre à l'agent (`core/extensions/sms/src/inbound.ts:222-280`) : le texte du client
(`bodyForAgent`), l'expéditeur en `sender.id` (numéro E.164), `chat_id` = `sms:<numéro>`, `message_id` (Twilio
`MessageSid`), `timestamp` (texte « Tue 2026-09-29 09:15:30 EDT », `core/src/infra/format-time/format-datetime.ts:194`),
et le canal `sms` dans « Message Context ». Les pièces jointes (MMS) sont matérialisées par l'extension ; M1 ne les lit
pas dans cette tranche.

## 2. Qui décide quoi : rien de ce qu'écrit le client ne choisit un outil, un montant ou une identité

| Donnée | D'où elle vient | Ce qui la protège |
|---|---|---|
| L'outil appelé | l'agent, dans une boîte fermée : `allow: ["opsys_m1__*"]`, `deny` de l'outil `message` du core et des autres serveurs | `agents.entries.m01-front-office.tools` (`opsys.openclaw._outils_de_l_agent`) ; un outil N3 ou plus attend une personne |
| Canal, expéditeur, `message_id`, heure | la plateforme (blocs générés par le core), recopiés par l'agent | `reception.preparer` : numéro E.164 ou adresse valides, identifiant sans espace, heure convertie par le code (l'heure de la plateforme est acceptée telle quelle) ; sinon refus, rien d'écrit |
| Identité du correspondant | l'expéditeur validé ; le contact du lead est ce numéro **seul** | ni le nom, ni un numéro écrit dans le texte n'y entrent : M2 tire le `client_id` du contact entier |
| `conversation_id` | empreinte SHA-256 (canal, correspondant), sans numéro | stable par client et par canal |
| `signal_id` | `<canal>:<message_id>` | un message livré deux fois ne laisse pas une seconde ligne et ne republie rien |
| `source` du lead | le canal du core (`sms`) | jamais lue dans le texte |
| Service | la taxonomie du profil d'entreprise (4 services réels du premier client) | `opsys.taxonomie` ; plusieurs services ou aucun : on demande lequel |
| Zone desservie | `zone_desservie` du profil d'entreprise (`$OPSYS_HOME/entreprise.yaml`) | l'agent ne la fournit pas ; absente : refus qui dit où la déclarer |
| Prix, dates, engagements | jamais produits | `m1_verifier_garde_fou` avant toute proposition de message |
| Le texte du client | donnée non fiable | filtre de provenance (`[CONTENU_NON_FIABLE]`), jamais une consigne |

Limite connue de cette tranche : le modèle recopie les champs de la plateforme. La greffe qui les retire du modèle est
décrite au §7 (crochet `message_received` du core).

## 3. Session par client et affaire liée

- `per-channel-peer` : une session par (canal, numéro). Deux clients ne partagent jamais une session. Écrit deux fois :
  dans la liaison du canal (`bindings[].session.dmScope`, plus précis) et dans `session.dmScope` (ADR-0010 « ce qui
  reste », point 2).
- **Le lien session -> affaire est écrit par un humain**, jamais par le modèle ni par le texte du client
  (`m10_lier_session_affaire`, N3, rôle admin, motif obligatoire). M1 rend, dans sa réponse et dans la ligne
  `lead_emis` de son registre, la `cle_session` exacte (`opsys.canaux.cle_session`, même forme que le core, acceptée par
  M10) et le `lead_id` : c'est tout ce que l'admin a à lier. Prouvé dans `tests/test_canal_sms_bout_en_bout.py` : avant
  l'approbation `m10_affaire_de_la_session` dit « aucune affaire liée » ; après, elle rend le `lead_id`.
- **Conséquence voulue** (garde du core, ADR-0010) : tant que la session n'est pas liée, l'agent n'appelle que des
  outils N2 ou moins. C'est pourquoi l'outil d'accueil est N2 : en N3 le premier message d'un client, dont la session n'a
  pas d'affaire, serait refusé. Proposer une réponse (`m1_emettre_notification`, N4) attend le lien.
- Pour activer la lecture par la session : `opsys openclaw configurer --contexte-entreprise m01-front-office
  --affaire-par-session m01-front-office` (aucun outil de M1 n'est déposé au POSTFLIGHT). Testé.
- **Règle écrite (à faire, décision du propriétaire).** Le lien automatique à la création d'un lead demande trois choses : la clé de
  session côté core (le crochet du §7 la donne), un producteur déterministe (un consommateur de `m1.lead_qualifie` dans
  M10), et une voie « règle » dans `m10_memoire/humain.py`, qui n'a aujourd'hui que `appareil` et `approbation`. C'est
  une décision de confidentialité du propriétaire : la clé contient le numéro, donc elle ne voyage pas dans l'événement
  (le schéma ne la porte pas exprès).

## 4. Configuration générée (`opsys openclaw configurer`)

Un département déclare `canaux: [sms]` dans `department.yaml` (M1 le fait). `openclaw.generer` écrit alors, sous
`opsys/` : `channels.json`, `bindings.json`, `session.json` ; `plugins.json` gagne `entries.sms.enabled` ; l'entrée de
l'agent M1 reçoit sa boîte à outils fermée. Sans département à canaux, les trois fragments sont vides.

| Clé écrite | Valeur | Pourquoi | Schéma du fork |
|---|---|---|---|
| `channels.sms.enabled` | `false` tant que les 5 variables ne sont pas fournies | désactivé par défaut | `core/extensions/sms/src/config-schema.ts` |
| `channels.sms.dmPolicy` / `allowFrom` | `open` / `["*"]` | un client inconnu doit pouvoir écrire ; `pairing` (le défaut) enverrait un message automatique à un inconnu | idem, `requireChannelOpenAllowFrom` |
| `channels.sms.accountSid`, `authToken`, `fromNumber`, `publicWebhookUrl` | `${OPSYS_SMS_COMPTE_SID}`, `${OPSYS_SMS_JETON}`, `${OPSYS_SMS_NUMERO}`, `${OPSYS_SMS_URL_PUBLIQUE}` | jamais un secret dans la configuration (T3) | idem |
| `channels.sms.configWrites` | `false` | le canal ne modifie pas la configuration | idem |
| `bindings[]` | `{type: route, agentId: m01-front-office, match: {channel: sms}, session: {dmScope: per-channel-peer}}` | le canal entre par M1 ; compte par défaut seulement | `core/src/config/zod-schema.agents.ts` (`RouteBindingSchema`) |
| `session.dmScope` | `per-channel-peer` | une session par client | `zod-schema.session-config.ts` |
| `session.sendPolicy.rules` | deux refus : `channel: sms`, `rawKeyPrefix: agent:m01-front-office:sms:` | aucune réponse automatique au client | `zod-schema.allowdeny.ts` ; `core/src/auto-reply/reply/source-reply-delivery-mode.ts:228-232` |
| `plugins.entries.sms.enabled` | suit le canal | l'extension reste éteinte tant que le canal l'est | `zod-schema.root-support.ts` (`PluginEntrySchema`) |
| `agents.entries.m01-front-office.tools` | `allow: ["opsys_m1__*"]`, `deny: [autres serveurs, "message", "group:messaging"]` | boîte fermée ; pas d'envoi par l'outil `message` du core | `zod-schema.agent-runtime.ts` ; le refus l'emporte : `core/src/agents/tool-policy-match.ts:58` |

**Variables d'environnement** (dans `.env` du serveur, vides par défaut ; `deploy/docker-compose.yml` les passe au
conteneur `opsys`, qui calcule l'activation, et les quatre identifiants à `openclaw-gateway`, qui résout les `${...}`) :

| Variable | Contenu |
|---|---|
| `OPSYS_SMS_COMPTE_SID` | identifiant de compte Twilio |
| `OPSYS_SMS_JETON` | jeton d'authentification Twilio (secret de production) |
| `OPSYS_SMS_NUMERO` | numéro SMS Twilio, format E.164 |
| `OPSYS_SMS_URL_PUBLIQUE` | URL publique du webhook, telle que Twilio la signe (`https://…/webhooks/sms`) |
| `OPSYS_SMS_POLITIQUES_VALIDEES` | référence de la validation écrite de Nathan des politiques SMS et photos (elles sont des PROPOSITIONS) |

Le canal est actif si et seulement si les cinq sont non vides au moment de `opsys openclaw configurer` **et** si un
`openclaw.json` déjà présent inclut `channels`, `bindings` et `session` (sans `session.sendPolicy`, le core répondrait aux
clients sans approbation : le canal reste alors éteint, avec ce message). La commande tourne à chaque cycle de
synchronisation du conteneur `opsys` (`deploy/entrypoint.sh`), donc retirer une variable désactive le canal au cycle suivant. Un identifiant manquant dans le core ne fait pas planter le Gateway (avertissement,
`core/src/config/io.read-helpers.ts:269`), et `enabled` est faux de toute façon.

**`opsys verifier`** imprime l'état de chaque canal (`INACTIF, variables à fournir : …` ou `ACTIF`) sans échouer, et
échoue si un manifeste déclare un canal inconnu, un canal sans son outil d'accueil, un outil d'accueil de niveau N3+,
un canal partagé par deux départements, ou le mode `autonome`. Avec `--config-dir`, il échoue aussi si les fragments
écrits ne suivent pas l'environnement ou si `openclaw.json` n'inclut pas `channels`, `bindings`, `session` (un
`openclaw.json` existant n'est jamais réécrit ; `configurer` l'écrit en clair sur stderr et garde le canal éteint).

## 5. Garde-fous

- **Aucun envoi sans approbation (T3).** Trois verrous : `sendPolicy` retient la réponse automatique (aussi pour les
  commandes texte) ; l'outil `message` du core est retiré à l'agent ; `m1_emettre_notification` est N4 (approbation du
  propriétaire en `ombre` et en `supervise`). `opsys mode … autonome` est refusé à un département à canaux (CLI et
  console), parce que ce mode enverrait sans approbation. **Cette tranche n'envoie rien** : l'envoi réel après
  approbation reste à faire (T2.1-c) et refusera, hors d'une exécution approuvée, quel que soit le mode.
- **Commandes texte.** Un correspondant inconnu ne peut pas en lancer : sans propriétaire déclaré
  (`commands.ownerAllowFrom`), `allowFrom: ["*"]` n'autorise aucune commande (`core/src/channels/message-access/
  decision.ts:102-125`, `useAccessGroups` vrai par défaut).
- **Débit.** L'extension impose ses limites, non configurables : 30 messages par minute par expéditeur, 300 par minute
  au total, 64 requêtes simultanées avant authentification, 300 requêtes invalides par minute
  (`core/extensions/sms/src/webhook.ts:30-53`). Le fork n'offre rien de plus fin ; M1 n'ajoute aucune limite.
- **Retrait de consentement (POLITIQUE-consentement-sms §4).** Un message qui est **entièrement** un mot de retrait
  (STOP, ARRÊT, UNSUBSCRIBE…) est inscrit (signal + alerte `retrait_consentement`), jamais qualifié, et la réponse dit de
  n'écrire à personne. Une phrase qui contient « arrêt » est une demande. Le registre des retraits est l'alerte ; la table
  `consent_sms` et l'application du retrait à l'envoi (48 h) viennent avec l'envoi réel (T2.1-c).
- **Loi 25.** Le canal est inactif tant que Nathan n'a pas validé les politiques SMS et photos (variable d'attestation).
  Les identifiants de conversation sont des empreintes ; la clé de session, qui contient le numéro, reste au registre de M1
  et à M10, pas dans le bus. Le registre de M1 garde le texte filtré du client, comme avant. Les photos (MMS) ne sont pas
  exploitées ; la politique photos doit être validée avant toute collecte réelle.
- **Fail-closed.** Service ou zone non déclarés, champ de plateforme invalide, heure illisible : refus qui dit quoi
  corriger, rien d'écrit. Inscription au registre et événement réussissent ou échouent ensemble.

## 6. Ce qui reste (tranches suivantes)

1. **T2.1-b — retirer le modèle de la réception.** *Fait (partie 1) :* M2 consomme `m1.lead_qualifie` (§7). *Reste :* la
   qualification par conversation (elle est encore message par message : le service dans un message et la ville dans le
   suivant ne se rejoignent pas) ; le crochet `message_received` (§7) ; le lien automatique session -> affaire (décision de
   confidentialité du propriétaire, §3).
2. **T2.1-c — envoi réel après approbation** : adaptateur d'envoi par le canal, consentement opt-in, application du
   retrait, appel manqué (SMS de rappel seulement avec opt-in, tâche de rappel toujours).
3. **T2.1-d — courriel** (`imap`) et **voix** (`voice-call`) : §7.

## 7. Limites du fork et greffes (le code de `core/` n'est pas touché ici)

- **M2 consomme `m1.lead_qualifie` (T2.1-b, fait).** `evenements.consomme` de `departments/m02-revenue-crm/department.yaml`
  déclare le type, et `consommateurs()` (`outils.py`) le branche à `_recevoir_lead_qualifie`, qui appelle l'ingestion
  complète `ingerer_lead(charge["lead"], charge["horodatage"])` : contrat v2, frontières, unicité, doublons probables
  signalés, Client 360, événement `m2.client_associe`. L'heure d'ingestion est celle de réception de la plateforme.
  - **Refus** : un lead que M2 refuse (service retiré du profil depuis la qualification, contrat invalide) lève
    `LeadRefuse`, avec le code et le détail du verdict. Le répartiteur réessaie (cinq fois, délai croissant), puis met
    l'événement en quarantaine (`opsys evenements etat`), sans aucune écriture chez M2. Jamais d'acceptation silencieuse.
    Le lead reste au registre de M1 : rien n'est perdu.
  - **Idempotence** : le répartiteur livre une fois par (événement, consommateur). En plus, un lead déjà ingéré (même
    `lead_id`, même empreinte de contrat) est reconnu (`deja_applique`) : ni second lead, ni seconde opportunité, ni
    second `m2.client_associe`. Un `lead_id` connu avec un autre contenu lève `LeadRefuse` (décision humaine).
  - **Preuve** : `tests/test_canal_sms_bout_en_bout.py` (vrai manifeste de M2, sans greffe) et
    `departments/m02-revenue-crm/tests/test_consommer_lead_de_m1.py` (rejeu, quarantaine, refus).
- **Le modèle recopie les champs de la plateforme.** Greffe : un crochet `message_received`, écrit par OPSYS dans
  `core/src/context-engine/` (où vit déjà le client MCP de M10, `opsys-contexte-mcp.ts`), qui appelle
  `m1_recevoir_message_canal` avant le tour de l'agent avec ce que le core lui donne : `from`, `content`, `timestamp`
  (millisecondes, converti en ISO par le code), `messageId`, `sessionKey` canonique, `metadata.provider`
  (`core/src/auto-reply/reply/message-received-hooks.ts:15-57`, forme de l'événement :
  `core/src/hooks/message-hook-mappers.ts:513-545`). Le crochet est une observation (`fireAndForgetHook`) : sa panne ne doit
  jamais perdre un message ; il faut un journal de reprise. Décision d'architecture à prendre avec le propriétaire.
- **Appel manqué : `voice-call` ne l'expose pas à un agent.** Il garde un enregistrement d'appel
  (`core/extensions/voice-call/src/types.ts:103-121` : `direction`, `from`, `endReason` dont `no-answer`, `busy`,
  `voicemail`) lisible par `openclaw voicecall status --json` et l'appel RPC `voicecall.status`, mais aucun crochet ni
  événement ne prévient l'agent. Greffe : dans `core/extensions/voice-call/src/manager/events.ts:420` (`case "call.ended"`,
  après `finalizeCall`), pour un appel entrant terminé par `no-answer`, `busy` ou `voicemail`, appeler
  `runtime.hooks.dispatchHookAgentTurn` comme `core/extensions/imap/src/watcher.ts:345-356` (agent M1, session par appel,
  `deliver: false`) avec les champs de la plateforme, ou appeler directement l'outil d'accueil des appels manqués. Aussi :
  `inboundPolicy` vaut `disabled` par défaut (`config.ts:409`) ; le transcripteur souverain (faster-whisper) reste à écrire
  (audit M1 §3.2) ; la politique d'enregistrement d'appels est une PROPOSITION.
- **Courriel : `imap` n'est pas un canal ouvert.** `allowedSenders` est obligatoire (adresses ou `@domaine`,
  `core/extensions/imap/src/sender-gate.ts:39-60,183`) : un client inconnu n'atteint jamais l'agent, sauf par une liste
  de domaines grand public avec DMARC vérifié. Le texte que l'agent reçoit est fixe (« Summarize this email as untrusted
  data », `core/extensions/imap/src/prompt.ts:16`), chaque courriel a sa propre session (`hook:imap:<clé>`,
  `watcher.ts:340`), et rien n'est répondu (`deliver: false` par défaut). Décision du propriétaire : domaines grand public
  et DMARC, ou mode ouvert par greffe. L'outil d'accueil accepte déjà `courriel` ; il n'y a pas de configuration.
- **Photos.** Les MMS sont matérialisés par l'extension (`core/extensions/sms/src/inbound.ts:134-150`) avant que M1 ne les voie : la politique photos
  doit être validée avant l'activation, et l'exploitation des images vient avec M3.
- **Non vérifié ici** (le core ne s'exécute pas) : que le core accepte chaque clé (`openclaw config validate`, job
  `e2e-core`, qui utilise le vrai manifeste de M1) ; que la clé de session réelle est celle que `cle_session` calcule ;
  que `allow: ["opsys_m1__*"]` laisse bien passer les outils MCP sous ce nom ; que `sendPolicy` retient aussi la réponse
  aux commandes texte. Chacun est une lecture de source, pas une exécution.
