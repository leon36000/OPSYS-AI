# M1 et les canaux du core (PLAN T2.1-a)

**Date :** 2026-09-29. **Portée de cette tranche :** un message SMS de client arrive à l'agent M1 par le canal du
core, est qualifié par le code, et devient un lead v2 que M2 recevra par le bus. Rien n'est envoyé au client. Le
courriel a son outil (même chemin) mais pas sa configuration ; la voix vient après.
**Suite (T2.1-b, partie 1, 2026-09-29) :** M2 consomme vraiment `m1.lead_qualifie` (§7), et un client qui écrit le service
dans un message et la ville dans le suivant donne un lead complet, par du code (§8).
**Suite (T4.4, 2026-09-29) :** qualification complète : verdict qui nomme chaque champ manquant, questions obligatoires par
service lues du profil, demande de photos fermée, score de lead explicable, prochaine action datée au registre (§9).
**Suite (T4.5, 2026-09-29) :** plaintes, urgences de sécurité et transfert humain avec résumé : la plainte prime (jamais de lead),
une attente lisible dans « À voir », un gabarit de réponse empathique en brouillon (§10).
**Suite (T4.17-c, 2026-09-29) :** le garde-fou de texte vit dans le socle (`opsys.garde_fou_texte`, familles nommées que chaque
département choisit) ; l'avis légal y est vérifié partout, pas seulement sur le gabarit de plainte (§11) ; le STOP d'un client est
publié au bus (`m1.retrait_consentement`) : M7 en tire le retrait de son consentement marketing, et M2 celui du consentement
de contact de ses relances, SMS et courriel (§12, T4.9).
**Références :** `DEFINITION-PRODUIT` §5, §6, §7 (M1.1, M1.3, M1.4, M1.7, M1.8, M1.12), `M1-audit.md`, ADR-0010 (T3.3-suite-b).
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
| Prix, dates, engagements, aveux, avis légaux | jamais produits | `m1_verifier_garde_fou` avant toute proposition de message |
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
- Pour activer la lecture par la session : `opsys-metier openclaw configurer --contexte-entreprise m01-front-office
  --affaire-par-session m01-front-office` (aucun outil de M1 n'est déposé au POSTFLIGHT). Testé.
- **Règle écrite (à faire, décision du propriétaire).** Le lien automatique à la création d'un lead demande trois choses : la clé de
  session côté core (le crochet du §7 la donne), un producteur déterministe (un consommateur de `m1.lead_qualifie` dans
  M10), et une voie « règle » dans `m10_memoire/humain.py`, qui n'a aujourd'hui que `appareil` et `approbation`. C'est
  une décision de confidentialité du propriétaire : la clé contient le numéro, donc elle ne voyage pas dans l'événement
  (le schéma ne la porte pas exprès).

## 4. Configuration générée (`opsys-metier openclaw configurer`)

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

Le canal est actif si et seulement si les cinq sont non vides au moment de `opsys-metier openclaw configurer` **et** si un
`openclaw.json` déjà présent inclut `channels`, `bindings` et `session` (sans `session.sendPolicy`, le core répondrait aux
clients sans approbation : le canal reste alors éteint, avec ce message). La commande tourne à chaque cycle de
synchronisation du conteneur `opsys` (`deploy/entrypoint.sh`), donc retirer une variable désactive le canal au cycle suivant. Un identifiant manquant dans le core ne fait pas planter le Gateway (avertissement,
`core/src/config/io.read-helpers.ts:269`), et `enabled` est faux de toute façon.

**`opsys-metier verifier`** imprime l'état de chaque canal (`INACTIF, variables à fournir : …` ou `ACTIF`) sans échouer, et
échoue si un manifeste déclare un canal inconnu, un canal sans son outil d'accueil, un outil d'accueil de niveau N3+,
un canal partagé par deux départements, ou le mode `autonome`. Avec `--config-dir`, il échoue aussi si les fragments
écrits ne suivent pas l'environnement ou si `openclaw.json` n'inclut pas `channels`, `bindings`, `session` (un
`openclaw.json` existant n'est jamais réécrit ; `configurer` l'écrit en clair sur stderr et garde le canal éteint).

## 5. Garde-fous

- **Aucun envoi sans approbation (T3).** Trois verrous : `sendPolicy` retient la réponse automatique (aussi pour les
  commandes texte) ; l'outil `message` du core est retiré à l'agent ; `m1_emettre_notification` est N4 (approbation du
  propriétaire en `ombre` et en `supervise`). `opsys-metier mode … autonome` est refusé à un département à canaux (CLI et
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
  `consent_sms` et l'application du retrait à l'envoi (48 h) viennent avec l'envoi réel (T2.1-c). Le retrait est aussi dit au
  bus, par le `lead_id` des leads déjà ouverts pour ce correspondant, jamais par son numéro (§12).
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
    l'événement en quarantaine (`opsys-metier evenements etat`), sans aucune écriture chez M2. Jamais d'acceptation silencieuse.
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
| Fenêtre **déclarée mais invalide** (0, texte, décimal, plus de sept jours) | Refus avant toute écriture (`REJ-PROFIL-INVALIDE`), jamais lue comme absente ; `opsys-metier verifier` la signale. |
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
- **Chaque question du profil passe seule au garde-fou** (aucun prix, aucune date, aucun engagement, aucun aveu, aucun avis
  légal : `REJ-INTERDIT-*`, §11). Celle qui est
  refusée est retirée et nommée (`questions_refusees`) ; les autres partent quand même, pour qu'une question mal écrite ne
  laisse pas le client sans réponse. Si toutes sont refusées : pas de brouillon, `sans_brouillon` dit le code. Le corpus
  adversarial du garde-fou est inchangé.
- **Limites.** (1) Le code reconnaît des mots, pas le sens : « pas de vinyle » répond à une question dont un mot-clé est
  « vinyle ». (2) Deux questions dont les mots-clés se recouvrent se répondent l'une l'autre (« plain-pied » contient le mot
  « pied ») : le propriétaire choisit des termes qui n'appartiennent qu'à une réponse. (3) Un profil invalide n'arrête pas la
  réception (un lead ne se perd pas pour une faute de frappe) ; `opsys-metier verifier` le signale.

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

## 10. Plaintes, urgences et transfert humain (T4.5)

Un client qui se plaint, ou qui signale un danger, n'est pas un lead : c'est une personne qu'il faut mettre devant un humain.
Rien n'est envoyé au client et aucun contrat n'a changé (`LeadQualifie` v2 et `m1.lead_qualifie` sont intacts). Ce que le
code fait (`plaintes.py`, `transferts.py`, `outils.py`) ; le modèle orchestre, il ne décide ni du type, ni du niveau, ni du
destinataire.

```
message reçu -> provenance (filtre) -> détection par règles (mots de l'entreprise) --reconnu--> TRANSFERT ouvert (registre)
                                             |                                                   |  attente « À voir » (N5/N4/N3)
                                             |                                                   |  brouillon empathique (jamais envoyé)
                                             +--rien de reconnu, aucun transfert ouvert--> qualification (§8, §9)
message d'une conversation dont un transfert est ouvert --> rattaché au transfert, jamais qualifié
```

### 10.1 Détection : par règles, avant la qualification, sur le texte filtré

- **Les mots ne sont pas dans le code.** Le propriétaire les écrit, par catégorie, dans le **profil d'entreprise**
  (`entreprise.yaml`, clé `signaux_plainte`, format dans [TAXONOMIE](../architecture/TAXONOMIE.md)). Cinq catégories, un
  ensemble fermé que le code connaît : `insatisfaction`, `degat`, `garantie`, `avocat` (plaintes) et `securite` (urgence).
  Les lectures sont celles des mots-clés d'un service : mot entier, pluriel admis, accents et casse ignorés, plusieurs mots =
  une expression.
- **Pourquoi le profil et non le `department.yaml` de M1.** (1) Chaque PME a ses mots et ses services : le manifeste est le
  même pour toutes les installations, le profil est par instance (SaaS, une base par instance). (2) Les questions, les poids et
  la fenêtre de M1 (T4.4, T2.1-b) y vivent déjà : une seule source de configuration métier de M1. (3) Il s'écrit avec un nom
  signé au journal d'audit (`enregistrer_signaux_plainte(…, par="nom")`), ce que demande une décision de Nathan ; un
  changement du manifeste passe par une PR. (4) `opsys-metier verifier` signale un profil invalide.
- **Sans vocabulaire, le verdict le dit** : `REJ-SIGNAUX-PLAINTE-NON-CONFIGURES` (« vocabulaire des plaintes à configurer »), et
  la réponse porte `plainte.statut: vocabulaire_a_configurer` : rien n'est reconnu, jamais un mot par défaut. Un vocabulaire
  invalide donne `profil_invalide` (`REJ-PROFIL-INVALIDE`), jamais lu comme absent, et **n'arrête pas la réception** (un lead ne
  se perd pas pour une faute de frappe). Une catégorie sans terme est nommée (`categories_non_configurees`).
- **La plainte prime.** Un message reconnu n'ouvre jamais de lead, même avec service, ville et contact. Il en va de même de
  tout message d'une conversation dont un transfert est encore **ouvert** : il est inscrit et rattaché, jamais qualifié. Une
  fois le transfert clos, ses messages ne se rassemblent plus dans la fenêtre de conversation (`transferts.signaux_exclus`) : les
  mots de la plainte n'ouvriront pas un lead plus tard.
- **Une urgence de sécurité est escaladée tout de suite** (type `urgence`, elle prime sur la plainte dans un même message).
  Aucun conseil de sécurité, aucune promesse d'intervention : ni dans le brouillon, ni dans la consigne à l'agent.
- **Mesures sur les fixtures fictives** (`fixtures/plaintes/plaintes.v1.yaml`, `fictif: true`) : **48 plaintes et urgences sur
  48 escaladées (100 %)**, avec exactement leurs catégories (36 plaintes, 12 urgences ; 6 messages mêlent deux catégories) ; **11 demandes ordinaires sur 12 passent** sans escalade ; la douzième (« ma voisine est avocate ») est un faux positif
  connu, escaladé : une personne lit, rien n'est perdu ; **4 plaintes sur 4 dites sans un mot du vocabulaire ne sont pas
  reconnues** (ironie, formulation indirecte, anglais absent du vocabulaire) : c'est la limite du code, qui lit des mots et pas
  le sens. Elle est couverte par le jugement de l'agent (`m1_escalader_plainte`, 4 sur 4 escaladées dans les tests).

### 10.2 Le transfert : type fermé, résumé obligatoire, destinataire à configurer

Un transfert est une suite de lignes `transfert` du registre anti-perte (append-only, jamais modifiées) : `ouvert`, puis `clos`
quand une PERSONNE le clôt. Ouvert, il est une attente ; les messages arrivés depuis sont rattachés (`rattache_au_transfert`).

| Point | Règle |
|---|---|
| Type | Ensemble fermé de la définition du produit (§7 M1.12) : `ventes`, `estimation`, `admin`, `finance`, `plainte`, `urgence`, `technique`, `proprietaire`. Un autre est refusé par le schéma. |
| Résumé | **Obligatoire, refus si vide.** Absent, le code le compose : type, termes reconnus, canal, nombre et heures des messages, lead déjà transmis ou non, origine du contact. **Aucun texte du client, aucun contact** (la file « À voir » ne porte aucune donnée personnelle). Fourni par l'agent (`resume`), il est **contrôlé** : non vide (`REJ-TRANSFERT-RESUME-VIDE`), 1 200 caractères au plus, passé par le filtre de provenance, **sans donnée de contact brute** (téléphone d'au moins sept chiffres, courriel : `REJ-TRANSFERT-RESUME-CONTACT`), puis par `garde_fou.verifier_sortie` (prix, date, engagement, aveu, avis légal : `REJ-INTERDIT-*`, §11 : un résumé de l'agent ne peut pas nommer un avocat ou un tribunal ; il omet alors `resume`, le code compose le sien et la menace juridique reste lisible dans « À voir »). Un refus n'écrit rien. |
| Contact | Porté **à part**, jamais dans le résumé : l'identité que la plateforme a vérifiée (SMS, courriel), sinon ce que le client a écrit (voix, formulaire), sinon rien. |
| Destinataire | Un **rôle**, lu de la table `destinataires_transfert` du profil (« type -> rôle », vide par défaut). Absent : `destinataire: null` et le verdict `REJ-DESTINATAIRE-NON-CONFIGURE` (« destinataire à configurer », qui nomme le type). **Le code ne choisit jamais une personne.** Le transfert est ouvert quand même : une plainte ne se perd pas pour une configuration manquante. Le rôle est affiché, pas appliqué : les attentes ne sont visibles que de l'admin (T1.5). |
| Idempotence | Un message rejoué ne crée ni second transfert ni seconde ligne. Deux appels de l'agent pour la même conversation et le même type rendent le transfert ouvert (`deja_ouvert`). |
| Date | L'heure de réception du message déclencheur (celle de la plateforme). Ouvert par l'agent : celle du dernier message du client. Jamais une horloge. |

**Les outils.** `m1_transferer(type_transfert, canal, expediteur, resume?)` et `m1_escalader_plainte(raison, canal, expediteur,
resume?)` ouvrent le même transfert que les règles, par le jugement de l'agent (`raison` : les cinq catégories ou `autre`).
L'agent recopie le canal et l'expéditeur comme pour un message reçu ; une conversation sans aucun message est refusée
(`REJ-TRANSFERT-CONVERSATION-INCONNUE`). **On ne sous-classe jamais un danger** : une plainte dont le texte évoque une urgence de
sécurité devient une `urgence`. `m1_lire_transfert(transfert_id)` rend le contexte complet (admin) ; `m1_clore_transfert(
transfert_id, motif, horodatage)` le clôt (admin, décision humaine).

### 10.3 Niveaux N : celui des outils, celui de l'attente

**Outils (ADR-0009 §4).**

| Outil | T / N | Pourquoi |
|---|---|---|
| `m1_transferer`, `m1_escalader_plainte` | T1 / **N2** | Ouvrir un transfert ne fait rien d'externe et n'engage personne : c'est une tâche interne (N2), pas une action externe à faible risque (N3). Trois raisons : en N3, le mode `ombre` mettrait la **création** de l'alerte d'une plainte en attente d'approbation (elle serait invisible avant qu'on approuve qu'elle existe) ; et le garde du core (ADR-0010, N3+ exige une affaire liée à la session) **refuserait l'appel** dans la session d'un client dont l'affaire n'est pas liée : la plainte d'un client inconnu serait perdue. Même choix que `m1_recevoir_message_canal`. |
| `m1_lire_transfert` | T0 / N0 | Lecture. Admin. |
| `m1_clore_transfert` | T1 / **N3** (défaut) | Modification interne non finale : en `ombre`, un agent qui la propose attend une personne ; un appel d'appareil `admin` s'exécute « au départ » (addendum T1.4-h). **L'outil refuse lui-même tout appel qui n'est pas une décision humaine** (`REJ-HUMAIN-REQUIS`, même garde que `m10_clore_signal`) : jeton d'appareil `admin` confirmé en base, ou exécution d'une demande qu'une personne vient d'approuver. Un agent ne clôt jamais seul, même en `supervise` ou `autonome`. |
| `m1_emettre_notification` | T2 / N4 | Inchangé : seul outil qui écrit à un client. Le brouillon d'une plainte n'y part qu'après approbation. |

**Attente (`niveau` dans « À voir »).** Seul l'ordre compte : `approbations.ordre_attente` trie par niveau, puis ancienneté.
**N5** : urgence de sécurité, et plainte avec menace juridique (le sujet est légal, DEFINITION-PRODUIT §5) ; **N4** : plainte,
transfert au propriétaire (la réponse engage l'entreprise) ; **N3** : ventes, estimation, admin, finance, technique (une tâche à
prendre). L'urgence passe devant une plainte plus ancienne (prouvé, E2E). C'est un ordre de lecture, pas une approbation : le
niveau d'une attente n'ouvre aucune décision N5 (l'attestation du professionnel reste celle de l'ADR).

### 10.4 « À voir » : l'attente naît à l'ouverture, une personne la clôt

`attentes()` (même mécanisme que M4, M5 et M6) rend une attente par transfert ouvert : `type` (`plainte_escaladee`,
`urgence_escaladee`, `transfert_humain`), `id` (le transfert), `resume` d'une ligne **sans donnée personnelle** (type,
catégories, canal, nombre de messages, destinataire ou « à configurer »), `niveau`, `depuis`, `action_proposee`. L'admin la lit
par `m9_lister_demandes_approbation` ; l'employé reçoit 403 (E2E). Elle disparaît quand une personne clôt le transfert avec
`m1_clore_transfert` : **sans cet outil, la file ne se viderait jamais**. Le contexte (résumé, contact, messages du client,
brouillon) se lit avec `m1_lire_transfert`. Le digest de M1 compte les transferts ouverts (dont urgences et plaintes) au jour de
référence.

### 10.5 Le gabarit de réponse empathique : un brouillon, jamais envoyé

| Type | Texte (proposition v1, ton à valider par Nathan) |
|---|---|
| plainte | « Bonjour, merci de nous avoir écrit. Nous comprenons que la situation que vous décrivez vous préoccupe. Votre message a été transmis à une personne de l'équipe. » |
| urgence | « Bonjour, merci de votre message. Nous l'avons signalé à une personne de l'équipe. » |

- **Aucune excuse** (« désolé » reconnaît un tort), **aucune promesse ni délai**, **aucun conseil de sécurité** (pas même « appelez
  le 9-1-1 » : décision de Nathan), **rien sur le droit**. Un fait passé seulement : le message a été transmis.
- Le brouillon passe par `garde_fou.verifier_sortie` (prix, date, engagement, aveu, avis légal). Depuis T4.17-c, l'avis légal est
  une famille du garde-fou (§11) : la vérification locale au gabarit, que T4.5 avait ajoutée parce que « Vous avez le droit de
  refuser de payer » passait le garde-fou, n'existe plus. Le corpus adversarial (44 textes) est inchangé et rejoué contre le
  gabarit : 44 sur 44 retirés. Si le gabarit était modifié pour contenir un texte interdit, `brouillon_reponse` vaut `null` et `sans_brouillon` dit le
  code.
- **Pas de brouillon** pour une menace juridique (`sujet_legal_reponse_humaine` : la réponse est humaine), ni pour un client qui
  s'est retiré (STOP : `retrait_consentement`, la plainte est escaladée quand même). `envoye` vaut toujours `false` ; l'envoi est
  `m1_emettre_notification` (N4, approbation).

### 10.6 Forme de la réponse de `m1_recevoir_message_canal` pour une plainte ou une urgence

| Clé | Contenu |
|---|---|
| `decision` | `ESCALADE_PLAINTE`, `ESCALADE_URGENCE` (transfert ouvert par ce message) ou `TRANSFERT_EN_COURS` (rattaché à un transfert ouvert) ; `qualifie: false`, jamais de `lead` |
| `plainte` | `statut`, `categories`, `termes` reconnus (et `verdict` quand le vocabulaire est à configurer ou invalide : présent aussi sur une réponse ordinaire dans ce cas) |
| `transfert` | `transfert_id`, `type_transfert`, `niveau`, `statut`, `nouveau`, `destinataire`, `verdict_destinataire` (détail complet à l'ouverture seulement) |
| `brouillon_reponse`, `envoye`, `gabarit`, `sans_brouillon` | à l'ouverture d'une plainte ou d'une urgence ; `envoye` vaut toujours `false` |
| `consigne` | ce que l'agent ne fait pas (écrire au client, conseiller, promettre) et ce qu'il dit à une personne |

### 10.7 Limites connues

- Le code lit des mots, pas le sens : faux positifs (« ma voisine est avocate ») et faux négatifs (ironie, langue absente du
  vocabulaire). Le vocabulaire est celui du propriétaire ; des **expressions** (« après vos travaux ») réduisent les faux positifs.
- Un transfert reste ouvert tant qu'une personne ne le clôt pas : un client qui écrit une demande ordinaire pendant ce temps est
  rattaché à la plainte, jamais qualifié. C'est voulu (une personne lit) ; le prix est un lead qui attend cette lecture.
- Le rôle destinataire est affiché, pas appliqué : la visibilité par rôle des attentes (au-delà de l'admin) est à faire.
- Les canaux vocal et formulaire passent par `m1_traiter_demande_entrante` (même détection, même transfert) ; les outils de
  l'agent (`m1_transferer`, `m1_escalader_plainte`) ne prennent que les canaux du core (`sms`, `courriel`).
- Une adresse postale dans un résumé fourni par l'agent n'est pas reconnue (seuls le téléphone et le courriel le sont).
- Le résumé de l'agent passe l'avis légal comme tout texte de M1 (§11) : il ne peut pas nommer un avocat. C'est le prix de
  « partout » ; l'exception d'un résumé destiné à un humain est une décision à prendre (§11, GATE).
- Aucun outil de M1 n'écrit encore une tâche dans M2 ni un signal dans M10 pour un transfert : la file « À voir » est la seule
  sortie (le lien vers M2 d'un lead déjà transmis est dit dans le résumé).
- Le jugement de l'agent (`m1_escalader_plainte`) n'est pas vérifié par du code : escalader à tort coûte une lecture.
- Une instance qui n'a déclaré ni ses services ni sa zone refuse tout message de canal (comportement de T2.1-a, rien n'est
  écrit) : une plainte comprise. L'agent le dit ; le message reste dans la session du core. Le vocabulaire des plaintes, lui,
  ne conditionne pas la réception.
- Aucun outil de configuration : le vocabulaire et la table de destinataires s'écrivent dans `entreprise.yaml` ou par
  `opsys.taxonomie.enregistrer_signaux_plainte` et `enregistrer_destinataires_transfert` (signés au journal), comme les
  questions et les poids de T4.4. Ni la console ni l'app n'ont encore d'écran pour cela.
- Un transfert couvre au plus six messages de la conversation ouverte (fenêtre du profil) ou, sans fenêtre, le seul
  message déclencheur ; les messages suivants sont rattachés et la lecture en montre quatre au plus (le reste est compté).

### 10.8 Ce que Nathan décide (GATE NATHAN)

Rien de ceci n'a de valeur par défaut dans le code : sans décision, le système le dit.
1. **Le vocabulaire des plaintes** (`signaux_plainte`, cinq catégories). Sans lui : « vocabulaire à configurer », aucune plainte
   reconnue par le code. Les mots de la fixture sont fictifs.
2. **Qui reçoit chaque type de transfert** (`destinataires_transfert`, type -> rôle : `nathan_owner`, `admin`, `finance`,
   `manager`, `seller`, `employee`). Sans lui : « destinataire à configurer », pour chaque type.
3. **Le ton du gabarit** (§10.5) : proposition, à valider. À trancher explicitement : une excuse, oui ou non ; un renvoi aux
   services d'urgence dans le brouillon d'urgence (aujourd'hui non : c'est un conseil de sécurité) ; une réponse pour une menace
   juridique (aujourd'hui aucune : elle est humaine).
4. **Les niveaux de l'attente** (§10.3) : N5 pour l'urgence de sécurité et la menace juridique, N4 pour la plainte, N3 pour les
   autres transferts.
5. **La règle « la plainte prime tant qu'elle est ouverte »** : garder, ou limiter le rattachement dans le temps.
Les vocabulaires, rôles et messages des tests sont fictifs : `departments/m01-front-office/fixtures/plaintes/plaintes.v1.yaml`
(`fictif: true`).

## 11. Le garde-fou de texte est dans le socle, et l'avis légal y est partout (T4.17-c)

Avant, M1 (`garde_fou.py`) et M7 (`usine/controle_texte.py`) avaient chacun leurs motifs, et l'avis légal n'était vérifié que
sur le gabarit de plainte. Le code partagé vit maintenant dans le socle : `opsys.garde_fou_texte`
(`docs/architecture/DEPARTEMENTS.md` § « Garde-fou de texte partagé »). Aucun département n'importe l'autre.

- **Des familles nommées, un refus qui nomme la règle.** Chaque famille a un nom, un code de refus stable et un libellé. Un refus
  dit toujours quoi retirer.
- **M1 choisit cinq familles** (`garde_fou.PROFIL_REPONSE_CLIENT`), lues dans l'ordre fixe du catalogue :

| Famille | Code de refus | Ce qu'elle refuse |
|---|---|---|
| `prix_montant` | `REJ-INTERDIT-PRIX` | un prix, un montant, une fourchette |
| `date_execution` | `REJ-INTERDIT-DATE` | une date ou un délai d'exécution des travaux (un rappel n'en est pas un) |
| `engagement` | `REJ-INTERDIT-ENGAGEMENT` | une promesse ferme, une garantie, une parole donnée |
| `aveu` | `REJ-INTERDIT-AVEU` | un aveu de faute ou de responsabilité |
| `avis_legal` | `REJ-INTERDIT-AVIS-LEGAL` | droits, loi, recours, avocat, tribunal, contrat : un avis légal, fiscal ou contractuel |

- **Le verdict est celui de la première famille violée** (prix, date, engagement, aveu, avis légal) : même texte, même code.
  Le verdict porte un `detail` (jamais muet) ; un texte accepté rend `OK`.
- **Les corpus de M1 sont inchangés** : 44 textes interdits (100 % bloqués, 100 % de la bonne famille), 22 légitimes (aucun
  faux positif). Les quatre familles d'origine donnent les mêmes verdicts qu'avant le déplacement (mesuré à la livraison contre l'ancien code,
  sur 60 341 textes, avec un script jetable : aucun écart) ; seule l'avis légal s'ajoute, sur des textes que M1 laissait passer.
- **Le texte d'un client se lit en temps linéaire** (T4.17-f). Le profil de M1 n'a pas de plafond de longueur, et la réception
  accepte 20 000 octets : un client pouvait bloquer M1 avec un seul message (20 000 chiffres : 29 s ; 20 000 espaces : 6 s).
  Le montant se lit « un chiffre, puis une devise » (le nombre n'a aucune forme à respecter), les écarts « déclencheur … cible »
  s'arrêtent au déclencheur suivant, et le découpage en segments ne relit plus les blancs. Mêmes verdicts qu'avant (comparés à
  l'ancien code sur 1 414 548 textes et sur 176 millions de suites de jetons, avec un script jetable : aucun écart) ; 5 ms pour
  20 000 chiffres. `tests/test_garde_fou_texte_lineaire.py` et un test de `test_garde_fou.py` (huit textes hostiles de 20 000
  caractères) en gardent la preuve.
- **Trois motifs de M1, hors du garde-fou, se lisent aussi en temps linéaire** (T4.17-g). Le courriel du texte d'un client
  (`qualification`, sans plafond), le prix d'un chiffrage (`contrats`, 500 caractères par contrat, mais le motif n'a pas de
  plafond) et le courriel d'un résumé de transfert (`transferts`, 1 200) relisaient la même suite de caractères à chaque
  départ. Temps de calcul pour 20 000 caractères hostiles, avant puis après : 0,5 s puis 0,3 ms pour le courriel du client
  (100 000 « a. » : 11 s), 67 s puis 2 ms pour le prix (20 000 chiffres), de 1,1 à 1,5 s puis 0,4 ms pour le courriel d'un
  résumé. Le prix se lit « un chiffre, puis une devise, un taux ou un mot » (seule la fourchette lit un nombre entier), le
  courriel d'un résumé se reconnaît à un caractère permis devant le « @ », et celui du client part du début de sa suite de
  caractères permis, saute jusqu'à la première frontière de mot, puis se lit d'un seul jet. Mêmes verdicts qu'avant, et même
  texte de courriel (comparés à l'ancien code sur 22 617 107 textes par version de Python, 3.11, 3.12 et 3.13, avec un
  script jetable : aucun écart ; les fonctions qui lisent ces motifs le sont aussi, sur 6 197 695 textes). Le courriel du
  client a ensuite changé de sens exprès (T4.17-g2, ci-dessous).
  `tests/test_motifs_lineaires.py` en garde la preuve (oracle recopié, textes hostiles de 20 000 et de 100 000 caractères,
  balayage de tous les motifs de M1) ; 95 mutants : 88 tués, 7 équivalents (même sens, même complexité).
- **Le courriel écrit par un client se lit en entier, ou pas du tout** (T4.17-g2). L'ancien motif, gardé tel quel par
  T4.17-g, repartait de la première frontière de mot : « andré.tremblay@x.ca » et « josé.tremblay@x.ca » donnaient tous deux
  « .tremblay@x.ca », dont M2 tire le `client_id` (deux personnes, un seul client) ; « françois@x.ca » n'était pas reconnu ;
  « o’neil@x.ca » donnait « neil@x.ca ». Un courriel tronqué est pire qu'aucun. Les règles :
  - la partie locale se lit jusqu'au « @ », lettres accentuées comprises ;
  - elle ne commence jamais juste après un caractère qui peut prolonger un mot ou une adresse : lettre, chiffre, signes
    permis par la RFC 5322, « @ », accent combinant, caractère de format, apostrophe typographique, traits d'union
    Unicode, point médian. « o’neil@x.ca » ou « jean&marie@x.ca » ne donnent rien, et le rejet dit « aucun téléphone ni
    courriel : demander comment joindre le client » ;
  - le texte passe d'abord en forme NFC : un accent tapé en deux caractères donne la même adresse, donc le même client ;
  - le domaine ne change pas : ASCII, et un domaine accentué ne donne rien.

  Effet sur M2 : M2 accepte ces contacts tels quels, et deux adresses qui ne diffèrent que par le prénom font deux clients.
  Un lead déjà reçu avec une adresse tronquée garde son `client_id` (registre en ajout seul) : si ce client réécrit, son
  nouveau lead porte l'adresse entière, donc un autre `client_id`, que rien ne relie à l'ancien.
  `tests/test_motifs_lineaires.py` compare la lecture à une référence écrite lettre à lettre (suites de jetons, textes
  générés, fixture, hasard) et garde la table de ce qui a changé, cas par cas, par rapport à l'ancien motif.
- **Limite connue du garde-fou d'un résumé** (T4.17-g3) : il lit le texte tel quel ; une partie locale qui finit par un
  accent tapé en deux caractères (un « e » suivi de l'accent aigu combinant U+0301, juste devant le « @ ») n'y est pas
  reconnue comme un courriel.
- **L'avis légal vaut partout où M1 passe un texte** : brouillons de qualification (libellé de service compris), questions du
  profil (retirées et nommées), gabarits de plainte et d'urgence, résumés de transfert, outil `m1_verifier_garde_fou`.
- **Conséquence connue** : un résumé de transfert fourni par l'agent ne peut pas nommer un avocat ou un tribunal
  (`REJ-INTERDIT-AVIS-LEGAL`). L'agent omet `resume` ou retire le terme ; le code compose alors son résumé, qui dit « menace
  juridique » sans texte du client, et l'attente monte en N5. Un texte fait pour un humain pourrait avoir un profil sans avis
  légal ; c'est une décision (GATE), pas un défaut du code.
- **Les motifs lisent des mots, pas le sens** : « Nous consultons notre avocat » est refusé comme « Vous avez droit à un
  recours ». Le prix du fail-closed est un faux positif possible ; la règle est nommée, donc contournable par une phrase plus
  sobre.

## 12. Le STOP est publié au bus : `m1.retrait_consentement` (T4.17-c)

Un correspondant qui écrit STOP se retire des messages (§5). Un client qui ne veut plus de messages n'a pas non plus consenti à ce
que son chantier serve de contenu public : M1 le dit au bus, et M7 en tire ses propres conséquences. M1 n'importe pas M7.

- **Le lien est le `lead_id`, jamais un contact.** M1 crée le `lead_id` (conversation, texte, identité du canal), M2 le reprend tel
  quel, le WCT de M4 le porte, M7 le connaît. L'événement porte les `lead_ids` que M1 a émis pour le correspondant, le canal
  du core, l'heure et le signal du STOP. **Ni numéro, ni courriel, ni `conversation_id`** (une empreinte du numéro, qui reste au
  registre de M1) : le schéma du catalogue est fermé.
- **Pourquoi pas le `client_id` de M2.** M2 le dérive d'une empreinte du contact entier (`clients.identifiant_client`, préfixe
  `m2-client-v1`). M1 le connaîtrait seulement en copiant cet algorithme, ce que la séparation des départements interdit, ou en
  lisant l'événement `m2.client_associe` (une boucle M1 -> M2 -> M1). Le `lead_id` suffit, sans rien exposer.
- **Une publication par STOP qui a des leads.** Sans lead ouvert, rien n'est publié (un consommateur n'aurait rien à retirer) : la
  réponse le dit (`retrait_publie: {leads: 0, evenement_id: null}`). L'identifiant est déterministe (signal du STOP + leads) : un
  STOP rejoué ne publie rien de plus. L'inscription au registre et la publication réussissent ou échouent ensemble.
- **Un lead ouvert après le STOP est retiré aussi.** Le retrait ne se lève pas (`transferts.retire`) : quand le même correspondant
  ouvre un nouveau lead, M1 publie un second événement, pour ce lead seul, avec l'heure et le signal du STOP d'origine.
- **Les opportunités d'un client qui revient.** M2 ouvre `<lead d'origine>~opp~<wct_id>` pour un client dont le lead a fini son
  cycle ; le WCT du chantier suivant peut porter cet identifiant. M7 reconnaît la forme (comme M10) : le retrait d'un lead vaut
  pour le lead d'origine et toutes ses opportunités.
- **Ce que le lien ne couvre pas.** Un même client qui écrit d'un autre numéro ou par un autre canal est un autre correspondant
  pour M1 : le retrait ne le suit pas. C'est la limite du lien sans contact. Les STOP inscrits AVANT cette livraison n'ont pas
  d'événement : un lead déjà ouvert pour eux n'est pas retiré chez M7 tant qu'un nouveau STOP ou un nouveau lead ne le publie
  pas (rattrapage à décider).
- **Côté M7** : le consommateur inscrit un retrait par lead dans `retraits_consentement_marketing` (sans `wct_id`) ; tout contenu
  de ces leads est bloqué (proposer, décider, exporter, photo), un paquet déjà exporté compris ; la réponse du consommateur dit
  quels paquets exportés se retirent à la main. Voir `departments/m07-marketing/README.md`.
- **Limite documentée** : la demande d'avis de M7 naît d'un consentement distinct (`consentement_demande_avis`, T1.5-d) et le STOP
  ne la touche pas ; elle reste un brouillon que rien n'envoie sans approbation. À trancher avec Nathan.
- **Preuve** : `tests/test_stop_retire_consentement_marketing.py` (le vrai bus : STOP, puis tout contenu du client est bloqué,
  paquet exporté compris, numéro absent), `departments/m01-front-office/tests/test_retrait_publie.py`,
  `departments/m07-marketing/tests/usine/test_retrait_du_bus.py`.
