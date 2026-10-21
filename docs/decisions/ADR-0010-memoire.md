# ADR-0010 — Mémoire : deux magasins, M10 gouverne, la « RAM » est le moteur de contexte

- Statut : **Accepté** (ingénieur en chef, 2026-09-28).
- Complète : [ADR-0008](ADR-0008-fork-openclaw-opsys-core.md) (décision 7) et
  [ADR-0009](ADR-0009-socle-metier.md) (base de l'instance).
- Fondé sur : [audit M10](../departements/M10-audit.md), [RAG-PREMIUM](../memory/RAG-PREMIUM.md),
  documentation mémoire du core (`docs/concepts/memory*.md`, `context-engine.md`, `plugins/hooks.md`).

## État courant — 2026-09-30 (complément, sans réécriture de l’historique)

Les sections T3.3/T3.3-suite-b/T4.18 ci-dessous gardent leur texte et leur contexte historique. Plusieurs
notes « reste », « greffe non appliquée » ou « CI seulement » décrivent l’état au moment de leur rédaction,
pas l’état courant. La réconciliation, les preuves datées et les limites sont consignées dans
[COHERENCE-DOCUMENTAIRE](../research/R17-2026-09-30/COHERENCE-DOCUMENTAIRE.md).

- **Moteur de contexte et garde d’action :** la greffe Core et le hook effectif `before_tool_call` sont
  présents. La voie de contexte M10 utilise la route MCP privée `/mcp/contexte/<agentId>`, liée à l’origine
  du serveur, avec `OPSYS_CONTEXT_MCP_JETON` distinct du bearer public. Les outils de cette voie restent
  refusés au modèle. Le moteur de contexte d’entreprise reste désactivé par défaut; l’activation exige une
  configuration explicite.
- **Admission provider :** un raccord distinct protège les profils configurables exportés vers le runner
  embedded. Avant chaque dispatch `StreamFn`, il exige une admission fraîche et une réservation; usage
  positif seul est réconcilié. Cela ne s’étend pas aux agents départementaux historiques, CLI/harness ou
  plugins à transport propre. La compaction générique et les sous-agents ne sont pas couverts; le provider
  des preuves était simulé et aucun appel fournisseur réel n’a été fait. L’estimation de tokens n’est pas
  une garantie de coût financier.
- **Mémoire de développement M10 :** son registre canonique, son API/console et un audit à la demande sont
  présents selon les preuves locales. Le scan est limité aux fichiers suivis par Git. Les plafonds de
  l’audit ne bornent pas la reconstruction préalable du journal complet; aucun scheduler/nightly ni
  retrieval sémantique n’est prouvé.

Les résultats rapportés sont des preuves ciblées locales sur arbre de travail partagé, non une validation
de CI distante, de production ou de parcours fournisseur avec credentials. Le raccord ciblé C02 ne ferme
pas les autres classes de liaison. Les rapports de preuve détaillent les portées et les diagnostics
étrangers rencontrés.

## Contexte

La définition (P4, P11, M10) exige une mémoire gouvernée, sourcée, versionnée, à paquets de contexte
en couches, qui n'oublie rien et n'injecte que l'utile. Aujourd'hui il existe trois magasins de fait :
- la mémoire des agents du core (SQLite par agent) ;
- la mémoire d'entreprise (PostgreSQL) ;
- le registre M10, en mémoire du processus et perdu au redémarrage.

OPSYS n'écrit aucune configuration mémoire pour les agents. Le partage entre agents
(`tools.agentToAgent`) est actif par défaut.

## Décisions

1. **Deux magasins physiques, pas trois.**
   - **Couche A**, mémoire native de chaque agent du core : paliers, provenance, « dreaming »,
     rappel en deux voies. Mémoire de travail de l'agent, jamais source de vérité d'un fait
     d'entreprise.
   - **Couche B**, mémoire d'entreprise dans la base de l'instance (ADR-0009) : SQLite + FTS5 +
     sqlite-vec par défaut, PostgreSQL + pgvector en option. Même API et mêmes tests que
     `src/opsys/memoire` aujourd'hui.
2. **M10 gouverne, il ne stocke pas.** Ses registres (événements, décisions, révisions) deviennent
   des lignes de la Couche B, chaîne de hash conservée. Il porte :
   - les statuts (10 valeurs de la définition) ;
   - l'ordre de vérité ;
   - la détection des contradictions ;
   - l'audit « non-oubli ».
   Les sept niveaux de confidentialité de la définition deviennent la taxonomie canonique. Les
   quatre sensibilités actuelles de la Couche B s'y rattachent ; la donnée « personnelle » Loi 25
   devient `CLIENT_PRIVATE`, avec échéance et sujet obligatoires. `registre_forge` est renommé
   `registre_evenements` (point ouvert 5 de la définition).
3. **La « RAM » est un moteur de contexte natif du core**, dans le slot `contextEngine`
   (`core/extensions/opsys-context-engine`).
   - `assemble()` compose à chaque tour, sous un budget de tokens, quatre paquets :
     « doit savoir », important, preuves, et approfondissement, chargé seulement sur demande.
   - La compaction est déléguée au runtime.
   - `afterTurn()` est le POSTFLIGHT.
   - Rien n'est stocké entre deux tours : la mémoire durable reste A et B.
4. **PREFLIGHT et POSTFLIGHT sur les hooks du core.**
   - `before_prompt_build` : contexte suffisant, et injection.
   - `before_tool_call` : blocage d'une action N3 ou plus si le contexte est insuffisant.
   - `after_tool_call` : journal de décision et fait mémorisé avec `source = outil + identifiant
     d'approbation`.
   - `agent_end`.
5. **Un seul service d'embeddings local pour les deux couches** : bge-m3 servi en compatible
   OpenAI sur la machine, `memory.search.provider: "openai-compatible"`. Un endpoint cloud
   n'est possible qu'avec une politique explicite (Loi 25, art. 17) ; les données `CLIENT_PRIVATE`
   n'y partent jamais.
6. **Cloisonnement.**
   - Le partage entre agents de département est désactivé par défaut.
   - Un département lit la mémoire d'un autre seulement par la Couche B, dans ses portées de
     lecture.
   - Le contenu des outils, des pages web et des clients reste une donnée non fiable, jamais une
     consigne.
7. **Graphe de connaissances** :
   - par défaut, une table de relations temporelle (sujet, prédicat, objet, source, confiance,
     validité), dans la même base ;
   - en option, Graphiti avec Neo4j, adopté seulement si le repli sature et que la mesure le
     justifie.

## Conséquences

- Porter `src/opsys/memoire` sur SQLite (FTS5 + sqlite-vec) en gardant PostgreSQL en option, avec
  le même jeu d'or et les mêmes tests sur les deux moteurs.
- OPSYS écrit la configuration mémoire des agents du core : provider d'embeddings, dreaming,
  provenance, cloisonnement.
- Première tranche (audit M10, phase 1) : la fin de travaux s'inscrit en mémoire avec sa provenance,
  et le paquet de contexte est injecté à la prochaine estimation de M3 (estimé contre réel).

## Mise en œuvre

### T3.3-suite : greffe du moteur de contexte dans le core (PREFLIGHT et POSTFLIGHT)

Faite le 2026-09-29. Le détail des fichiers est dans `core/PROVENANCE.md` (« Greffes OPSYS »).

Ce qui existe (activable pour tout agent nommé ; le cas visé est M3, avant `m3_estimer_projet`) :
- **Décision 3, `assemble()`.** Le moteur `opsys` (slot `contextEngine`) demande à M10 le paquet de
  l'affaire (`m10_paquet_contexte_affaire`) et le rend en `systemPromptAddition`. L'assemblage des messages et
  la compaction restent ceux du lanceur (`LegacyContextEngine`, `delegateCompactionToRuntime`).
- **Décision 3, `afterTurn()` = POSTFLIGHT.** Il dépose chez M10 ce que les outils listés ont fait pendant le
  tour (`m10_deposer_faits_candidats`) : outil, résultat `ok` ou `refus`, code. Jamais un texte de modèle.
  Un fait déposé est un **candidat** : hors du paquet, hors de la consolidation nocturne.
- **Appel au moteur métier.** Le core sélectionne dans `contextServers` le serveur lié à l'agent
  configuré : HTTP `streamable` `/mcp/contexte/<agentId>`, en-tête
  `Bearer ${OPSYS_CONTEXT_MCP_JETON}`. Cette route fixe l'origine d'appel et n'expose que
  `m10_paquet_contexte_affaire`. Le secret est distinct de `OPSYS_MCP_JETON`; aucun accès direct à
  la base n'est fait. Un appel ouvre sa connexion et la referme : rien n'est gardé entre deux tours.
- **Budget.** M10 calcule le budget de caractères et la troncature ; le core valide la cohérence du paquet
  (compteurs, quatre couches dans l'ordre, total sous le budget de M10) et le refuse en entier au moindre écart.
  Il ne le tronque jamais. Un paquet plus grand que le budget de tokens que le lanceur laisse est refusé de la
  même façon.
- **Fail-closed et sans blocage.** Moteur injoignable, trop lent (`delai_ms`, 4 s par défaut), réponse
  tronquée par le serveur, paquet invalide ou hors budget, aucune affaire dans la demande : le tour continue
  sans paquet, avec le marqueur « contexte d'entreprise indisponible » dans le contexte et une ligne du
  journal `opsys-contexte`.
- **Désactivé par défaut.** `opsys/contexte.json` (`"actif": true`) et `plugins.slots.contextEngine: "opsys"`
  s'écrivent ensemble par `opsys-metier openclaw configurer --contexte-entreprise AGENT[:OUTIL,OUTIL]`. Sans l'option,
  le fichier porte `{"actif": false}` et aucun moteur n'est choisi.
- **Mémoire native conservée.** Le lanceur retire du prompt système la section mémoire de `memory-core` pour
  tout moteur autre que « legacy ». Le moteur `opsys` la rajoute (`buildMemorySystemPromptAddition`) même
  quand `contexte.json` est inactif ou ne nomme pas l'agent : choisir ce moteur ne prive aucun agent de sa
  couche A. En prompt minimal (sous-agents), il la met aussi, ce que le lanceur ne ferait pas.
- **Niveau du dépôt.** `m10_deposer_faits_candidats` est T1 mais **N2** (tâche interne automatique), comme
  `m4_deposer_fichier`. En N3, le mode `ombre` de M10 mettrait chaque tour d'agent en attente d'approbation ;
  `openclaw.generer` refuse d'activer le moteur si le dépôt en exigerait une. Le dépôt est append-only, ne
  décide rien, n'engage personne, et reste fermé aux appareils.

Écarts avec le texte des décisions 3 et 4, voulus :
- **Emplacement.** `core/src/context-engine/`, et non `core/extensions/opsys-context-engine`. Une extension
  n'importe que le SDK de plugins, qui n'expose aucun client MCP ; elle aurait apporté le sien (importeur neuf
  du lockfile) et de nouvelles entrées dans des inventaires que le bac à sable ne régénère pas. La greffe est
  isolée et se déplace en extension telle quelle.
- **Hooks.** Le PREFLIGHT est dans `assemble()` et le POSTFLIGHT dans `afterTurn()`, pas dans
  `before_prompt_build` et `after_tool_call` : ces deux points du moteur de contexte portent déjà la
  permission d'injection et le résultat du tour, sans plugin ni permission de conversation.

Reste après T3.3-suite (les points 1, 2, 3 et la moitié du 6 sont traités par T3.3-suite-b, ci-dessous) :
1. ~~Blocage `before_tool_call`~~ : décision écrite et testée, appel du core à greffer (voir plus bas).
2. ~~Résolution des signaux critiques~~ : faite.
3. ~~Affaire du tour~~ : lue dans la session pour un agent de canal client ; le lien automatique attend M1.
4. **Consolidation des candidats.** La consolidation nocturne ne lit que les événements du bus ; les faits
   candidats attendent une validation puis une intégration à `m10_consolider_affaire` et au paquet.
5. **Paquet « avant une estimation ».** Le paquet est celui de l'affaire (règles, faits, événements, signaux).
   Le paquet par type de travaux (`paquet_contexte_estimation`, estimé contre réel) n'existe pas encore.
6. **Réutilisation de la connexion MCP** d'un tour à l'autre (quatre allers-retours HTTP par appel ; cinq pour un
   agent dont l'affaire vient de la session). Le filtre `CLIENT_PRIVATE` est fait.
7. **Déploiement.** `deploy/entrypoint.sh` et `deploy/install.sh` appellent `opsys-metier openclaw configurer` sans
   l'option : rien n'est activé à l'installation. Le choix du propriétaire (quels agents, quels outils, quels
   agents lisent leur affaire dans la session) reste à brancher.
8. **Preuve en réel.** Les tests du core tournent en CI seulement ; aucun tour d'agent n'a encore été
   exécuté de bout en bout avec un moteur métier lancé.

### T3.3-suite-b : signaux critiques, garde d'action N3+, affaire de la session, confidentialité

Faite le 2026-09-29 ; le core n'a pas été exécuté (la CI fait foi). Détail des fichiers : `core/PROVENANCE.md`.

**Signaux critiques (M10, `signaux.py`).** Un signal est une variance matériaux évaluée au-dessus du seuil,
identifiée par son `evenement_id`, de l'affaire de son WCT. Trois états, un seul sens :
`ouvert` -> `pris_en_compte` -> `clos`.
- L'état se calcule par relecture du registre Affaires (maillons `signal_traite`, append-only), jamais par un
  champ qu'on positionne. Un maillon forgé hors de l'outil, ou qui saute une étape, ne ferme rien.
- Un passage est une décision **humaine** : `m10_prendre_en_compte_signal` et `m10_clore_signal`, N3, portée
  `admin`, avec un motif obligatoire (10 à 500 caractères). L'outil refuse lui-même (`REJ-HUMAIN-REQUIS`) tout
  appel qui n'est ni un appel d'appareil dont l'identité est confirmée en base (personne active, rôle `admin`), ni
  l'exécution d'une demande qu'un humain vient d'approuver. Le modèle seul ne clôt donc jamais, y compris dans un
  département en mode `supervise` ou `autonome`, où un N3 s'exécute sans file. Le maillon garde la personne, son
  rôle, la voie (`appareil` ou `approbation`), le motif ; pour un appel d'appareil l'heure de réception du
  serveur fait foi.
- Lecture de l'approbateur : le socle n'exposait pas à l'outil qui a approuvé (`approbations.decider` ne posait aucun
  contexte). L'outil lisait donc, sans écrire, la demande `en_cours` de son propre nom, de son département, aux
  arguments exacts, avec un approbateur actif de rôle `admin` ou `nathan_owner`. Une contextvar posée par `decider`
  la remplaçait proprement (changement du socle, fait depuis en PLAN T4.15-c) : `approbations.approbateur_en_cours`.
  M10 l'appelle depuis PLAN T4.15-d, avec les mêmes rôles (`humain.roles_humains()`) ; la lecture de la table décrite
  ci-dessus n'existe plus. Le socle ne compare pas les arguments : `decider` rejoue les arguments exacts enregistrés.
- Une seule autre cause de clôture, écrite et testée : M6 republie, pour le même `wct_id` et après le signal, une
  variance évaluée sans dépassement. La clôture se calcule à la lecture. **Elle n'a pas encore de producteur** :
  M6 traite `evaluee` comme terminal. Aujourd'hui, seul un humain clôt.
- Le paquet montre les ouverts d'abord, puis les derniers clos, avec qui et pourquoi (dans le résumé), et un bloc
  `signaux` (`nb_ouverts`, `nb_pris_en_compte`, `nb_clos`) calculé sur tous les signaux : la troncature de la couche
  ne peut pas en cacher un.

**Garde `before_tool_call` (core, `opsys-contexte-garde.ts`).** Pour un outil OPSYS de niveau N3 ou plus, l'appel
est refusé si le paquet de l'affaire était indisponible, jamais évalué pour ce tour, périmé (plus de 15 minutes),
ou s'il porte un signal critique ouvert. Le message dit quoi faire (faire prendre connaissance du signal par un
humain, ou réessayer quand le contexte est disponible).
- Le niveau vient de `contexte.json` (`niveaux`, généré par `openclaw.py` depuis `Outil.niveau_effectif`), jamais du
  modèle. Un outil absent de `niveaux` n'est pas un outil OPSYS connu : jamais bloqué. Les niveaux N0 à N2 ne le
  sont jamais.
- Désactivé ou absent : pas de garde pour les agents non configurés. En revanche, une configuration
  explicitement active mais illisible, invalide, obsolète/non versionnée, ou sans serveur d'origine
  valable produit l'état `invalid`; les appels OPSYS sont bloqués. Le statut inactif n'est donc pas
  confondu avec une activation cassée (C03).
- Le moteur écrit, à chaque tour (`assemble()` avec prompt), l'état de son PREFLIGHT par clé de session (mémoire du
  processus, 512 sessions). Le réassemblage sans prompt que le lanceur fait après chaque résultat d'outil ne compose
  rien et n'écrase pas cet état. Une session qui n'a pas eu son propre tour évalué (un sous-agent, un redémarrage du
  processus en plein tour) n'a pas d'état : ses appels N3+ sont refusés, fail-closed, jusqu'à son prochain tour.
- **Un moteur de contexte ne peut pas bloquer un appel d'outil.** `before_tool_call` appartient au lanceur de hooks
  de plugins et aux politiques d'outils de confiance, que seuls des plugins enregistrent
  (`core/src/agents/agent-tools.before-tool-call.policy.ts`, `runBeforeToolCallHook`, ligne 103 ; hooks de plugins
  ligne 363, `runTrustedToolPolicies` ligne 242 ; sortie rapide sans politique ligne 204) ; l'interface
  `ContextEngine` n'a aucune méthode de ce genre (`core/src/context-engine/types.ts`, ligne 353). **Greffe
  minimale, non appliquée** (hors du périmètre demandé) : dans `runBeforeToolCallHook`, après l'admission de
  boucle (ligne 168) et avant `const hookRunner = getGlobalHookRunner();` (ligne 170), appeler
  `checkOpsysContexteToolCall({ toolName, sessionKey: args.ctx?.sessionKey, agentId: args.ctx?.agentId })` et, si
  `block`, rendre un `HookOutcome` bloqué (`kind: "veto"`, `deniedReason: "plugin-before-tool-call"`, `reason`),
  comme le fait déjà l'admission de boucle. Une douzaine de lignes et un import (`HookBlockedReason` pourrait gagner
  une valeur `opsys-contexte`, `types.ts` ligne 97). Tant qu'elle n'est pas faite, le garde décide
  et le core n'applique pas. La CI devra vérifier que `HookContext.sessionKey` est bien la clé que reçoit
  `assemble()` : sinon le garde ne trouve aucun état et bloque tout N3+ des agents nommés (fail-closed).

**Affaire de la session (M10 `liaison.py`, core).** Sur un canal client, le texte de la demande est celui du client :
une ligne `affaire_id: ...` qu'il écrit ne prouve rien. Pour un agent réglé `"affaire": "session"` dans
`contexte.json` (`opsys-metier openclaw configurer --affaire-par-session AGENT`), le moteur demande à M10 l'affaire liée à
la clé de session (`m10_affaire_de_la_session`, T0, fermé aux appareils), pour le paquet comme pour le dépôt
POSTFLIGHT, et ne lit jamais le texte. Un humain écrit le lien (`m10_lier_session_affaire`, mêmes règles que
ci-dessus) ; le dernier fait foi ; la session principale d'un agent, partagée par tous ses correspondants, n'est
jamais liée. Sans lien : tour sans paquet, marqué, garde fermé pour les N3+.
- **Ce qui reste, et qui exige M1.** (1) Le lien automatique à la création d'un lead : M1 (ou M2) doit connaître la
  clé de session de la conversation qui crée le lead et un producteur déterministe (événement du bus) doit
  l'écrire ; jusque-là c'est un humain (app admin). (2) `session.dmScope: "per-channel-peer"` à écrire dans la
  configuration avant d'activer M1 : par défaut (`main`) tous les correspondants d'un agent partagent une session,
  donc un seul lien, que M10 refuse. (3) Un fil (`:thread:...`) a sa propre clé : à lier ou à ramener à sa
  conversation de base.

**Filtre `CLIENT_PRIVATE` (M10 `confidentialite.py`).** Les sept niveaux de la définition sont la taxonomie
canonique. Règle écrite et épinglée par test :
- un élément non marqué est `INTERNAL` ; un marquage inconnu est traité comme `LEGAL_LOCKED` ;
- `SENSITIVE`, `FINANCIAL`, `SECRET_REF` et `LEGAL_LOCKED` ne sortent jamais dans un paquet ;
- `CLIENT_PRIVATE` ne sort que dans `faits_affaire` et `evenements_recents`, et seulement vers `m01-front-office` et
  `m02-revenue-crm` ; jamais dans `regles_entreprise` ni dans `signaux_non_resolus`. **C'est un choix par défaut,
  à faire valider par le propriétaire** : ajouter un agent ou une couche est une décision de confidentialité, donc
  une modification de la table, de ses tests et de ce texte ;
- sans agent nommé, la vue est la plus restrictive ;
- un élément retenu n'est jamais rendu (ni contenu, ni identifiant) : le paquet compte seulement
  `confidentialite.nb_retenus`. Le filtre passe avant la troncature.
L'agent est celui que le core lit dans la clé de session et transmet (`agent`), jamais un texte : un agent de
département ne voit pas le serveur MCP de M10, seul le moteur du core appelle le paquet en son nom. Le core refuse
un paquet dont le bloc de confidentialité ne nomme pas cet agent, ou dont un fait porte un niveau fermé. Une décision
peut être marquée (`m10_journaliser_decision`, clé sœur `confidentialite`, contrat v1 intact) ; aucun autre producteur
ne marque encore : les événements du bus, dont le catalogue est fermé, n'en portent pas.

**Transport et identité d'origine (frontière DEP-002).** Le nom de l'agent n'est plus passé en
argument d'outil. `openclaw.py` génère pour chaque agent une entrée `serveur_contexte` qui pointe
vers `opsys_context_<agentId>` et `/mcp/contexte/<agentId>`. Le serveur MCP attribue cette voie au
`appelant` canonique du chemin et ne publie que `m10_paquet_contexte_affaire`; le middleware exige
`OPSYS_CONTEXT_MCP_JETON` (24 caractères minimum), distinct du bearer public
`OPSYS_MCP_JETON`. Le générateur ajoute `opsys_context_*__*` au deny de tous les agents, y compris
les agents internes sans allowlist : enregistrer une entrée MCP ne suffit donc pas à rendre l'outil
appelable par le modèle. L'origine (`agentId`) est l'agent servi; l'exécuteur de l'outil reste le
serveur M10. Les accès CLIENT_PRIVATE autorisés pour M1/M2 restent dans leur vue filtrée et ne
sont pas fermés globalement.

**C02 ciblé et C03.** La vérification couvre la liaison M3 `m3_estimer_projet` uniquement : la
configuration lie l'outil à `contrat.lead_id` de type affaire/lead. Le garde compare la valeur à
l'affaire canonique du PREFLIGHT; argument absent, invalide, différent ou affaire inconnue donne un
refus. Une identité de lead ne valide pas une cible WCT/opportunité. Cela ne promeut ni ne prétend
corriger les autres classes C02 (autres types de cibles, opérations ou preuves hors de cette liaison).
Pour C03, `contexte.json` actif et invalide bloque les outils OPSYS; absence ou désactivation
explicite conserve le mode inactif. Les tests du core couvrent config invalide, liaison M3 connue,
cible absente/différente, et le refus effectif par la politique `before_tool_call`.

### T4.18 : l'amont d'une affaire, du lead au devis (M10 `etapes.py`, `amont.py`)

Faite le 2026-09-29. M10 consomme `m1.lead_qualifie`, `m2.client_associe`, `m3.devis_accepte` et
`m3.devis_sans_reponse` (DEFINITION-PRODUIT §6 : « M10 reçoit des événements de tous les départements à chaque
étape »). `m3.devis_envoye` n'existe pas encore au catalogue (T4.7).
- **Ce qui est gardé.** Des identifiants et des faits d'étape, extraits un par un de la charge (liste blanche, formes
  fermées) : jamais le contact du lead, la ville, `conversation_id` ni `signal_id` (empreintes du correspondant), les
  lignes d'un devis, ni un texte de client. Un champ hors de sa forme est refusé (quarantaine du répartiteur), et le
  refus nomme le champ, jamais la valeur. L'instant d'un fait est celui de l'événement.
- **Niveaux posés par M10 sur les faits du bus** (après la rentabilité `FINANCIAL` de T1.5-d ; le catalogue, lui,
  reste fermé et n'en porte pas). Le client associé est `CLIENT_PRIVATE` (son `client_id` est une
  empreinte du contact : sur un numéro de téléphone, elle se retrouve par essais) ; le prix et le coût d'un devis
  accepté sont un maillon compagnon `FINANCIAL`. Le maillon de l'étape « devis accepté » ne porte aucun montant, pour
  que l'étape figure à l'historique. La table de `confidentialite.py` ne change pas : `CLIENT_PRIVATE` sort vers M1 et
  M2 seulement, dans `faits_affaire` et `evenements_recents`.
- **Idempotence et ordre.** Par type et par clé publique (`lead_id`, `devis_id`), jamais par `lead_id` seul : un rejeu,
  même sous un autre `evenement_id`, ne crée rien ; un fait reçu avant celui qui le précède est gardé et ne bloque
  pas l'autre (même défaut que T1.5-d pour le WCT). Un lead inconnu n'est jamais inventé : le fait de l'amont d'un
  lead dont M10 n'a pas reçu le `m1.lead_qualifie` est gardé sous son `lead_id`, et le reçu du répartiteur dit
  `origine_recue: false` et `verdict: AMONT-ORIGINE-NON-RECUE`. Le paquet, lui, ne portait pas ce verdict : sa forme est
  épinglée contre les fixtures du core (`tests/test_openclaw_contexte.py`), qui se modifient en CI seulement (levé par
  T4.18-b, plus bas).
- **Lecture.** Les faits de l'amont sont dans la couche `evenements_recents` : les quatre couches et leur ordre ne
  changent pas (le core les valide). Le paquet garde son budget : avec cinq faits ou plus, le plus ancien sort et
  `nb_omis` le dit ; la consolidation nocturne (`faits_affaire`) garde le compte par jour. (T4.18-b dit les jours à
  consolider et chiffre le budget.)
- **Audit.** `m10_auditer_non_oubli` attend un fait de l'amont par sa clé publique. Un consommateur retiré de
  `evenements.consomme` se voit à la trace absente d'un fait que le bus a publié ; `opsys-metier verifier` le voit aussi
  (fonction orpheline).

### T4.18-b : l'affaire elle-même, une forme commune, le budget de l'historique (M10 `affaire.py`, `paquets.py` ; core)

Faite le 2026-09-29 ; le TypeScript du core n'a pas été exécuté (la CI, `core.yml`, fait foi). Elle lève les trois limites
de T4.18 : le paquet ne disait pas « affaire inconnue », l'historique se tronquait sans dire quoi consolider, et
l'opportunité `<lead>~opp~<wct_id>` que M2 ouvre quand un client revient n'avait pas la forme d'une affaire du core.

- **Une seule forme d'affaire** (`affaire.py`). Une affaire est un lead, ou l'opportunité de M2 ; le lead compte au plus 64
  caractères, le `wct_id` au plus 128, soit 197 pour l'affaire entière ; seuls passent les lettres latines, les chiffres et
  `._:-` (le tilde n'existe que dans `~opp~`) : ni espace, ni retour à la ligne, ni caractère de contrôle ou de sens d'écriture. La
  forme est écrite deux fois, mot pour mot : dans M10 (`FORME_AFFAIRE`) et dans le core (`AFFAIRE_ID` pour un identifiant,
  `AFFAIRE_LINE` pour la ligne `affaire_id: ...` d'une demande). Un test du socle compare le texte des deux motifs, et les
  deux côtés rejouent la MÊME liste de cas, un fichier (`core/src/context-engine/opsys-contexte.affaires.json`) que
  vitest (`opsys-contexte-affaire.test.ts`) et pytest (`test_affaire.py`) lisent tous deux. Côté M10, le lien de session, le
  dépôt POSTFLIGHT, le paquet et les faits de l'amont (M2, M3) la partagent ; M1 garde la forme du lead seul, car il ne
  publie jamais d'opportunité. Les anciennes copies (64 caractères, sans tilde) sont un sous-ensemble de la forme actuelle.
- **Un seul niveau d'opportunité.** M2 rattache toute nouvelle opportunité au lead RACINE
  (`_ouvrir_nouvelle_opportunite_pour_wct`, PLAN T4.18-c) : un second WCT sur `<lead>~opp~<wct 1>` ouvre `<lead>~opp~<wct 2>`,
  jamais une chaîne, que M10 et le core refusent (le cas reste dans la liste partagée, parmi les refus). L'opportunité
  d'origine reste nommée dans l'interaction système de M2.
- **Le bloc `affaire`, additif dans le paquet.** `{connue, origine_recue, origine, verdict}` (`amont.situation`, déjà la
  réponse du consommateur au reçu de chaque fait) : une affaire dont M10 n'a reçu aucun fait est INCONNUE
  (`AMONT-AFFAIRE-INCONNUE`), au lieu de quatre couches vides qu'on lirait comme « rien à signaler » ; une affaire dont
  l'étape qui l'ouvre n'a pas été reçue le dit (`AMONT-ORIGINE-NON-RECUE`). L'étape qui ouvre un lead est le lead qualifié de M1,
  celle qui ouvre une opportunité est le client associé de M2 (`etapes.py`, champ `ouvre` de la table ; jusqu'ici l'origine d'une
  opportunité n'était jamais « reçue »). Le bloc ne dépend pas de la troncature : l'origine est le fait le plus ancien, celui
  que la couche omet en premier. Vocabulaire fermé (booléens, type d'événement du bus, code de verdict), aucun renseignement
  personnel, le même pour tous les agents.
  **Pourquoi un bloc et non un outil `m10_dossier_affaire`.** Le paquet n'est pas un contrat gelé : ses quatre couches et leur ordre,
  que le core valide, ne changent pas, et une clé sœur additive est l'évolution permise. Un second appel par tour coûterait un
  aller-retour MCP de plus (déjà quatre par appel, « Reste » de T3.3-suite, point 6), pourrait échouer seul, et séparerait le
  verdict des couches qu'il qualifie.
- **Ce que le core en fait.** Il valide le bloc sans le réparer : l'incohérence entre les drapeaux, l'origine et le verdict refuse
  le paquet (une affaire inconnue n'a pas d'origine, ni d'événement ni de signal ; une origine reçue est nommée et sans verdict ; un
  type d'origine n'est jamais un texte libre). Il le rend, dans ses propres mots, avant les couches : « Affaire inconnue de la
  mémoire », « Affaire connue, l'étape qui l'a ouverte n'a pas été reçue », « ouverte par m2.client_associe ». Une affaire inconnue est
  journalisée (`opsys-contexte`, niveau info). **Le garde ne change pas** : une affaire inconnue ne bloque pas un outil N3 ou
  plus, comme avant. C'est un choix laissé au propriétaire, non tranché ici : les affaires d'avant T4.18 n'ont aucun fait chez
  M10 (il n'y a pas de rattrapage), et les bloquer arrêterait tout travail sur elles. Aujourd'hui une faute de frappe dans
  `affaire_id` donne un paquet « inconnue » et un garde sans signal ouvert : la phrase du prompt est la seule alerte.
- **Le bloc `consolidation`, additif.** `{a_consolider, nb_a_consolider}` : quand la couche des événements omet des faits, les jours de
  ces faits qu'aucun fait durable ne résume, au plus 10 jours (`NB_JOURS_A_CONSOLIDER_MAX`), les plus anciens d'abord, chacun avec
  l'affaire. Une entrée `{affaire_id, jour}` est l'argument exact de `m10_consolider_affaire` et sort de la liste dès que
  l'outil l'a consolidée (test en boucle fermée). Le jour est celui de l'événement tel qu'il est écrit, comme la consolidation
  (`consolidation.jour_de`) ; « consolidé » a le critère de `consolider_affaire` (la clé `affaire:jour`). Seuls comptent les faits
  que l'agent aurait pu voir : un fait retenu par confidentialité ne donne pas son jour. Le core refuse une liste au-delà de sa
  borne, un jour d'une autre affaire, un doublon, un compte qui ne correspond pas à la liste, ou plus de jours que la couche
  n'a omis de faits. Il écrit une ligne sous les faits des événements : « Jours omis, pas encore résumés dans les faits durables
  (à consolider par M10) : ... ». Personne ne consomme encore la liste par du code (la consolidation nocturne ne traite que la
  veille) : c'est la lecture d'un humain, ou d'un agent M10, qui sait désormais quoi consolider.
- **Le budget du paquet, chiffré** (`paquets.py`, README de M10 ; un test lit ces deux textes et cette section). Le paquet a
  4 000 caractères de faits (`BUDGET_CARACTERES_DEFAUT`), partagés également entre les quatre couches : 1 000 caractères chacune
  (`budget_par_couche`), et au plus 5 faits par couche (`NB_FAITS_MAX_PAR_COUCHE_DEFAUT`). Une couche garde ses faits du plus
  récent au plus ancien et s'arrête au premier plafond atteint ; son premier fait est toujours gardé, même trop gros. Un fait de
  l'historique avec des identifiants de 64 caractères pèse 180 à 270 caractères (mesuré sur les charges réelles) : quatre tiennent
  presque toujours, c'est le plafond de caractères qui coupe. Une affaire complète compte six à huit faits visibles selon l'agent
  et le nombre de devis : le lead qualifié, son origine, sort le premier, puis le client associé pour M1 et M2. Le cadrage (les deux
  blocs, les titres du core) ne compte pas dans le budget. Les chiffres ne changent pas ; le bloc `affaire` et la liste des jours existent
  parce qu'ils rendent cette perte lisible.
- **Ce que seule la CI prouve.** `core.yml` : la construction, `opsys-contexte-affaire.test.ts` (la liste de cas côté core),
  `opsys-contexte-paquet.test.ts` (validation et rendu des deux blocs, cinq paquets réels), `opsys-contexte-engine.test.ts`
  (l'opportunité demandée en entier, l'affaire inconnue journalisée, le garde inchangé). `e2e-core.yml` construit le core et joue app,
  Gateway et moteur sans aucun tour d'agent : il n'exerce pas le moteur de contexte et ne verrait qu'une rupture de la
  construction. Ici, le core est relu à la main, sa logique transcrite en Python, et les fixtures sont
  comparées clé par clé à la sortie réelle de M10 (`tests/test_openclaw_contexte.py`).
- **Reste.** Décider si une affaire inconnue bloque les actions N3 ou plus ; un consommateur
  du bloc `consolidation` qui consolide sans lecture humaine ; le rattrapage des affaires d'avant T4.18.
