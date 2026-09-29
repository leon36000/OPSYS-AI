# M1 et les canaux du core (PLAN T2.1-a)

**Date :** 2026-09-29. **Portée de cette tranche :** un message SMS de client arrive à l'agent M1 par le canal du
core, est qualifié par le code, et devient un lead v2 que M2 recevra par le bus. Rien n'est envoyé au client. Le
courriel a son outil (même chemin) mais pas sa configuration ; la voix vient après.
**Suite (T2.1-b, partie 1, 2026-09-29) :** M2 consomme vraiment `m1.lead_qualifie` (§7), et un client qui écrit le service
dans un message et la ville dans le suivant donne un lead complet, par du code (§8).
**Suite (T4.4, 2026-09-29) :** qualification complète : verdict qui nomme chaque champ manquant, questions obligatoires par
service lues du profil, demande de photos fermée, score de lead explicable, prochaine action datée au registre (§9).
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
| Ce qu'on demande au client | un brouillon que le code compose (§8, §9) ; les questions du service viennent du profil d'entreprise, jamais du code | garde-fou des interdits appliqué par le code, question par question ; il ne part que par `m1_emettre_notification` (N4), après approbation |
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

1. **T2.1-b — retirer le modèle de la réception.** *Fait (partie 1) :* M2 consomme `m1.lead_qualifie` (§7) et la
   qualification se fait par conversation (§8). *Reste :* le crochet `message_received` (§7) ; le lien automatique
   session -> affaire (décision de confidentialité du propriétaire, §3).
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
  - **Preuve** : `tests/test_canal_sms_bout_en_bout.py` (vrai manifeste de M2, sans greffe),
    `tests/test_canal_conversation.py` (quarantaine, rejeu), `departments/m02-revenue-crm/tests/test_consommer_lead_de_m1.py`.
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

## 8. Qualification par conversation (T2.1-b, partie 1)

Un client écrit souvent « mes gouttières fuient » puis, dans le message suivant, « à Laval ». Qualifié message par
message, il ne donnait jamais un lead complet. Le code (`m1_front_office/conversation.py`, module pur), pas le modèle,
rassemble maintenant les messages d'une même conversation dans une fenêtre bornée et qualifie quand service et ville sont
connus. Aucun message n'est envoyé : ce qu'il reste à demander est un brouillon.

**La durée de la fenêtre n'est pas inventée.** Elle vient du profil d'entreprise, comme la zone desservie :

```yaml
# $OPSYS_HOME/entreprise.yaml
fenetre_conversation_minutes: 30   # entier, de 1 à 10080 (sept jours) ; aucun défaut
```

`opsys.taxonomie.charger_fenetre_conversation` la lit ; `enregistrer_fenetre_conversation(minutes, par="nom")` l'écrit, signée
au journal d'audit, sans toucher aux services ni à la zone. La valeur est lue à chaque message. Le « 30 » ci-dessus est un
exemple : le propriétaire choisit.

| Situation | Comportement |
|---|---|
| Fenêtre **absente** | Comportement d'avant : chaque message est qualifié seul. Chaque réponse porte `conversation: {mode: "message_par_message", verdict: {code: "REJ-FENETRE-NON-CONFIGUREE", detail: <où la déclarer>}}`. |
| Fenêtre **déclarée mais invalide** (0, texte, décimal, plus de sept jours) | Refus avant toute écriture (`REJ-PROFIL-INVALIDE`), jamais lue comme absente ; `opsys verifier` la signale. |
| Fenêtre déclarée | Voir ci-dessous. |

**Règles avec fenêtre** (le registre anti-perte est la seule mémoire ; rien n'est gardé entre deux appels) :

- **Conversation ouverte.** Elle commence au premier message que ni un retrait (STOP) ni la fenêtre n'ont fermé. Un message
  s'y joint si son heure de réception est à au plus `fenetre` minutes de celle du premier message (borne incluse). L'heure
  de réception fait foi, pas l'ordre d'arrivée. Au-delà, il ouvre une nouvelle conversation ; les messages d'avant restent
  au registre (une ligne par message, rien n'est perdu) mais ne se joignent plus. La réponse dit combien
  (`conversation.hors_fenetre`).
- **Le lead naît quand service et ville sont connus**, sur le texte rassemblé (mêmes règles que message par message : un seul
  service, une ville de la zone ; plusieurs services évoqués : on demande lequel). L'urgence se lit sur tous les messages.
  `lead_emis` garde `signaux_rassembles` ; l'événement `m1.lead_qualifie` n'a pas changé.
- **Un seul lead par conversation ouverte.** Un message qui arrive après le lead, dans la même fenêtre, est inscrit et
  rattaché (`rattache_au_lead` sur sa ligne) : décision `CONVERSATION_DEJA_QUALIFIEE`, `nouveau_lead: false`, aucun second
  événement. La réponse dit ce que le lead transmis ne porte pas (`complement.urgence_declaree`,
  `complement.autre_service_evoque`) pour qu'une personne le voie. Après la fenêtre, une nouvelle conversation peut donner un
  nouveau lead, même à texte identique : l'identité du lead compte alors le premier message de la conversation.
- **Un message rejoué ne compte pas deux fois** : il est reconnu par son `signal_id` avant tout, rien n'est écrit, la
  réponse est celle d'alors (y compris `CONVERSATION_DEJA_QUALIFIEE`).
- **STOP ferme la conversation.** Ce qui a été écrit avant n'est jamais qualifié (la réponse au STOP dit combien de messages
  restent sans lead : `messages_non_qualifies`). Un message d'après ne se joint pas aux précédents et n'a pas de brouillon
  (`sans_brouillon: "retrait_consentement"`). STOP retire le consentement aux messages, pas le droit d'écrire : une demande
  complète d'après reste qualifiée.

**Ce qui est demandé au client est un brouillon.** Quand le lead n'est pas complet, la réponse porte `a_demander`
(chaque champ du lead qui manque : `service`, `ville`, `contact`), `conversation.connu` (ce qui est établi, §9.1), et
`brouillon_reponse` : une question
courte composée par le code (services demandés lus dans le profil, jamais dans une liste locale), passée au garde-fou des
interdits. Si le garde-fou la refuse (un libellé de service déclaré ne doit pas glisser un prix), il n'y a pas de brouillon
(`sans_brouillon` dit pourquoi). `envoye` vaut toujours `false` : le brouillon ne part que par `m1_emettre_notification`
(N4), en attente d'une personne. Prouvé avec `Capacites` et `approbations.decider`
(`tests/test_canal_conversation.py`) : la réception ne crée aucune demande d'approbation et n'envoie rien.

**Limites connues.**

- La fenêtre se mesure depuis le premier message de la conversation (elle ne glisse pas à chaque message) : un client
  bavard ne garde pas une conversation ouverte indéfiniment. Un message livré hors d'ordre se joint s'il tient dans la
  fenêtre du premier message reçu.
- Changer la durée du profil regroupe autrement les messages déjà au registre, à la lecture suivante.
- Le mécanisme est celui du canal, pas du SMS seul : un courriel du même correspondant dans la fenêtre se joint de la même
  façon (le courriel n'a pas encore sa configuration, §7).
- Sans fenêtre, deux messages de texte identique d'un même client donnent le même `lead_id`, donc un seul événement : M2 ne
  voit pas le second. Non modifié (les `lead_id` déjà émis gardent leur identité) ; la fenêtre, elle, n'a pas ce défaut.
- L'urgence se cumule sur toute la conversation, avant et après le lead (§9.1) ; le lead, lui, est gelé.
- L'agent doit relayer `complement.*` à une personne : aucun outil de tâche n'existe encore côté M1 pour l'écrire ailleurs
  que dans sa réponse.

## 9. Qualification complète (T4.4)

Tranche suivante de M1.3 : une conversation ne meurt plus à la porte. Aucun message n'est envoyé, aucun contrat n'a changé.
Ce que le code fait, par des règles (`qualification.py`, `questions.py`, `photos.py`, `score.py`, `suivi.py`) ; le modèle
orchestre, il ne note ni ne devine rien.

### 9.1 Un verdict qui nomme chaque champ manquant, et un cumul qui couvre tout

- **Le rejet nomme chaque champ.** `verdict_qualification.detail` commence par `champs manquants (service, ville, contact)` et
  dit quoi demander pour chacun ; la réponse porte `champs_manquants` (même sans fenêtre de conversation). Le code du verdict
  reste `REJ-QUALIF-INSUFFISANTE`, et les phrases d'avant (`aucun service…`, `plusieurs services évoqués (a, b)…`) sont gardées.
- **Trois champs font le lead :** `service`, `ville`, `contact`. Pour un message de canal, le contact est l'expéditeur que la
  plateforme a vérifié (§2) : il ne manque jamais, et le texte du client n'y ajoute rien. Pour une demande dont le contact vient
  du texte (voix transcrite, saisie), un téléphone ou un courriel écrit dans un message suivant complète le lead.
- **`conversation.connu`** dit ce que tous les messages rassemblés établissent : `service`, `ville`, `contact` (`canal`, `texte`
  ou `null`) et `urgence_declaree` (vraie dès qu'un message la déclare, jamais inférée du ton).
- **L'urgence se cumule aussi après le lead.** Le lead est gelé (v2) : `complement.urgence_declaree` dit ce que la conversation
  déclare et que le lead transmis ne porte pas, même si l'urgence a été écrite deux messages plus tôt.

### 9.2 Questions obligatoires par service : du profil, jamais du code

Le propriétaire écrit, par service, les questions qu'il veut poser (GATE NATHAN) dans `entreprise.yaml`
(`questions_qualification`, format et verdicts : [TAXONOMIE](../architecture/TAXONOMIE.md)). Une fois le lead complet, la
réponse porte un bloc `questions` :

| `questions.statut` | Sens | Brouillon |
|---|---|---|
| `service_a_preciser` | le service n'est pas établi : on ne sait pas quoi demander | (le lead d'abord) |
| `non_configurees` | le profil n'a aucune question pour ce service ; `verdict` (`REJ-QUESTIONS-NON-CONFIGUREES`) dit où les écrire | aucun : rien n'est inventé |
| `profil_invalide` | des questions sont écrites mais invalides ; `verdict` (`REJ-PROFIL-INVALIDE`) dit la raison | aucun ; **la réception du lead continue** |
| `a_poser` | des questions n'ont pas de réponse (`restantes`, dans l'ordre écrit) | oui |
| `aucune_restante` | le client a tout répondu (`repondues`) | aucun |

- **Une question est répondue** quand un de ses `mots_cles` (écrits par le propriétaire) figure dans les messages rassemblés :
  mot entier, pluriel admis, accents et casse ignorés, comme les mots-clés d'un service. Les réponses données avant le lead
  comptent.
- **Ordre du brouillon :** d'abord ce qui manque au lead, une seule question à la fois (service, ville, contact) ; ensuite les
  questions du service ; ensuite les photos (§9.3). Le lead n'attend pas les questions : il part chez M2 dès qu'il est complet.
- **Chaque question du profil passe seule au garde-fou** (aucun prix, aucune date, aucun engagement, aucun aveu). Celle qui est
  refusée est retirée et nommée (`questions_refusees`) ; les autres partent quand même, pour qu'une question mal écrite ne
  laisse pas le client sans réponse. Si toutes sont refusées : pas de brouillon, `sans_brouillon` dit le code. Le corpus
  adversarial du garde-fou est inchangé.
- **Limites.** (1) Le code reconnaît des mots, pas le sens : « pas de vinyle » répond à une question dont un mot-clé est
  « vinyle ». (2) Deux questions dont les mots-clés se recouvrent se répondent l'une l'autre (« plain-pied » contient le mot
  « pied ») : le propriétaire choisit des termes qui n'appartiennent qu'à une réponse. (3) Un profil invalide n'arrête pas la
  réception (un lead ne se perd pas pour une faute de frappe) ; `opsys verifier` le signale.

### 9.3 Demande de photos : fermée tant que la politique n'est pas validée

Une question `photos: true` du profil est une demande de photos. Elle ne se propose **jamais** tant que
`POLITIQUE-photos-non-contractuelles.md` ne porte pas la ligne exacte `STATUT_VALIDATION: valide` (T3 : Nathan ou un juriste).
C'est la même lecture que M3 (`m3_estimation.politique_photos`) ; `tests/test_politique_photos_derive.py` confronte les deux sur
les mêmes textes et sur le document réel. Toute autre valeur (`proposition`, l'état actuel), un marqueur absent ou dupliqué, un
fichier illisible : fermée. Le bloc `photos` dit `fermee` (avec le verdict `REJ-PHOTO-POLITIQUE-NON-VALIDEE`) ou `ouverte`.
Ouverte, la demande s'ajoute au brouillon des questions, au message qui qualifie le lead ou avec une question encore posée.
M1 ne lit pas les pièces jointes (MMS) : il ne sait pas si les photos sont arrivées, et une personne le voit.

### 9.4 Score de lead : des règles, des poids du profil, jamais un modèle

| Critère | Valeur (0 à 1) |
|---|---|
| `urgence` | 1 si un message de la conversation déclare une urgence explicite, sinon 0 |
| `completude` | éléments établis ÷ éléments attendus : service, ville, contact, et les questions de texte du service |
| `zone` | 1 si une ville de la zone desservie est reconnue, sinon 0 |

`score = 100 × Σ (poids × valeur) ÷ Σ poids`, en fractions exactes, arrondi à l'entier (demi vers le haut). Chaque critère rend
son poids, sa valeur (`"2/5"`), ses points (au centième) et une phrase qui dit ce qui a été constaté. **Les poids sont ceux du
propriétaire** (`poids_score_lead`, un entier par critère, 0 écarte un critère). **Sans poids, pas de score** :
`score.statut = poids_a_configurer` et le verdict `REJ-POIDS-SCORE-NON-CONFIGURES` dit où les écrire ; des poids invalides
donnent `profil_invalide`, jamais « à configurer ».

Exemple (profil fictif de test : poids 30 / 50 / 20, quatre services, questions de la fixture) : « mes gouttières débordent,
c'est urgent » (service et contact connus, urgence) donne 50 ; « à Laval » (le lead naît, ville de la zone) donne 80 ; « environ
40 pieds, deux étages » (les deux questions répondues) donne 100.

Le score **reste dans le registre de M1** (ligne `suivi_conversation`). Le passer à M2 exige un `LeadQualifie` v3 (P5), hors
tâche : le contrat v2, le lead et l'événement `m1.lead_qualifie` n'ont pas changé, et un test le prouve par le vrai bus.

### 9.5 Prochaine action datée au registre

Chaque message reçu (jamais un rejeu) d'une conversation à fenêtre ajoute au registre une ligne `suivi_conversation` : ce que la
conversation établit, ce qui manque, les questions restantes, le score, et la **prochaine action** :

| Action | Quand |
|---|---|
| `demander_precisions` | il manque un champ du lead |
| `poser_les_questions_du_service` | le lead est complet, des questions restent sans réponse |
| `decision_humaine_apres_retrait` | l'une ou l'autre reste à demander, mais le client s'est retiré (STOP) |
| (aucune, ligne `close`) | rien à demander, ou STOP a fermé la conversation |

**Les dates ne viennent jamais de l'horloge du modèle ni du système.** `inscrite_le` est l'heure de réception que la plateforme a
livrée avec le message (ou l'instant fourni) ; `a_faire_avant` est la fin de la fenêtre de la conversation (ouverture + fenêtre
du profil), l'échéance réelle : passé ce moment, les messages suivants ne se rejoignent plus. Aucun délai de relance n'est
inventé. La ligne ne garde aucun texte du client.

Le **digest** (M1.11) relit ces lignes et ajoute, seulement si le registre en porte : « conversations ouvertes à suivre » (écrites
ce jour, dernière ligne encore ouverte) et « conversations sans suivi à l'échéance de leur fenêtre » (la fenêtre se termine ce
jour et la dernière ligne demande toujours une action : une conversation n'y figure que le jour de son échéance). Il ne dit pas
encore les leads sans suivi côté M2 ni les documents manquants.

### 9.6 La réponse du client à « lequel des services ? »

Quand le client cite plusieurs services, le brouillon lui demande par lequel commencer. Le texte rassemblé les évoquait toujours
tous : sa réponse ne changeait rien, la question revenait, la conversation restait bloquée jusqu'à l'expiration de la fenêtre.
**Règle** (`conversation.services_retenus`, isolée dans son commit, hors de la spécification de T4.4) : quand plusieurs services
sont en jeu, un message qui n'en nomme qu'un est le choix du client ; un service de plus s'ajoute et on redemande ; un message sans
service ne choisit rien. Ce que le choix écarte est dit (`conversation.services_ecartes`, ligne `lead_emis` du registre).
**Limite :** « aussi le soffite », écrit après « gouttières et soffite », lit un choix du soffite ; `services_ecartes` le dit à
une personne. À confirmer avec la décision de précédence entre services (encore ouverte, TAXONOMIE.md).

### 9.7 Forme de la réponse de `m1_recevoir_message_canal` (fenêtre déclarée)

| Clé | Présente | Contenu |
|---|---|---|
| `champs_manquants` | lead incomplet (aussi sans fenêtre) | `service`, `ville`, `contact` qui manquent |
| `a_demander`, `brouillon_reponse`, `envoye`, `sans_brouillon`, `questions_refusees` | il y a quelque chose à proposer | `envoye` vaut toujours `false` |
| `questions` | toujours | §9.2 |
| `photos` | le service déclare une demande de photos | §9.3 |
| `score` | toujours | §9.4 |
| `prochaine_action`, `suivi_ligne_id` | toujours (`null` si rien à demander) | §9.5 |
| `conversation.connu`, `conversation.services_ecartes` | toujours, si un service est écarté | §9.1, §9.6 |

### 9.8 Ce que Nathan décide (GATE NATHAN)

Rien de ceci n'a de valeur par défaut dans le code : sans décision, le système le dit.
1. **Les questions par service et leurs mots-clés** (`questions_qualification`). Sans elles : `REJ-QUESTIONS-NON-CONFIGUREES`.
2. **Les poids du score** (`poids_score_lead`). Sans eux : « poids à configurer ».
3. **La validation de la politique « photos »** (`STATUT_VALIDATION: valide`). Sans elle : demande fermée.
4. **La règle du choix du service** (§9.6) : la garder, la retirer, ou la remplacer par la précédence entre services.
5. **Le délai de relance.** L'échéance d'une conversation est la fin de sa fenêtre ; un délai plus court (par exemple répondre
   dans les 15 minutes) est une décision, pas un calcul.
Les questions et les poids des tests sont fictifs : `departments/m01-front-office/fixtures/qualification/profil-fictif.v1.yaml`
(`fictif: true`).
