# Architecture OPSYS-AI v2

> QUOI : [définition produit](../produit/DEFINITION-PRODUIT.md). Décision en vigueur :
> [ADR-0008](../decisions/ADR-0008-fork-openclaw-opsys-core.md) (OpenClaw devient OPSYS-CORE par fork
> dur). Recherche et ingrédients : [`docs/research/`](../research/).

## Architecture cible (ADR-0008)

```
 App mobile Expo (admin · vendeur · employé · client)        Dashboard web (Control UI étendue)
                        │   HTTPS + WebSocket, appareils appairés   │
 ┌──────────────────────┴───────────────────────────────────────────┴──────────────────────┐
 │ OPSYS-CORE (TypeScript, fork dur d'OpenClaw v2026.9.6)                                  │
 │ passerelle (seul point d'entrée, authentification) · agents M1…M10 et sous-agents ·     │
 │ canaux (SMS, WhatsApp, courriel, Teams…) · mémoire native + moteur de contexte « RAM » · │
 │ fournisseurs de modèles cloud et locaux · planificateur · superviseur du moteur métier  │
 └──────────────────────────────────────────┬──────────────────────────────────────────────┘
                                            │ MCP (agents) · API interne (interfaces)
 ┌──────────────────────────────────────────┴──────────────────────────────────────────────┐
 │ Moteur métier OPSYS (Python) : sources de vérité des dix départements (§8), moteurs     │
 │ déterministes, événements entre départements, approbations N0–N5, RBAC, audit, métriques │
 └──────────────────────────────────────────┬──────────────────────────────────────────────┘
                                   base de l'instance · fichiers (photos, preuves)
```

Le dépôt contient une installation autonome, le core `opsys`, le moteur métier Python et l'app Expo
à quatre profils. Le générateur `src/opsys/openclaw.py::generer` configure les fournisseurs natifs
par défaut. Les champs `api_key_env` et les noms de clés conventionnels sont des références à des
variables d'environnement; la valeur du secret n'est pas écrite dans le JSON. Une clé requise
manquante bloque le readiness. LiteLLM et `OPSYS_CLE_Mn` restent pris en charge en compatibilité
explicite avec une URL de passerelle. Les tests sans credentials ne valident pas d'appels à un
fournisseur réel; la présence des scripts d'installation et de déploiement ne certifie pas un parcours
de production.

Direction actuelle : [ADR-0012](../decisions/ADR-0012-reutilisation-profondeur-productivite.md),
[périmètre complet](../produit/PERIMETRE-MODULES.md) et
[plan de consolidation](../programme/RESTRUCTURATION-2026-09-30.md).

## Symbiose des départements et agents (cible)

Les agents spécialisés sont configurables par département depuis le dashboard : responsabilités,
modèles, outils, droits, mémoire, budgets et déclencheurs. Les manifestes actuels génèrent surtout
un agent par département ; le registre multi-agents complet est une extension à livrer.

Un événement durable ou une demande précise déclenche les seules capacités utiles. L'outbox,
les corrélations et identifiants de rejeu relient les départements ; la base métier conserve
la vérité, M10 le contexte sourcé. Les messages partagent références et résultats autorisés,
jamais l'ensemble des données client par défaut. La disponibilité de plusieurs agents ne
requiert pas un débat entre modèles. Chaque effet de bord revalide le principal, l'objet,
les arguments, l'approbation et les droits vivants.

Les budgets doivent être réservés avant l'appel fournisseur puis réconciliés sur usage réel,
y compris sous-agents, retries et compaction. Le mécanisme Python existant et une clé LiteLLM
optionnelle ne prouvent pas encore cette garantie de bout en bout.

## Supervision du moteur métier (PLAN T0.10)

Dans l'installation cible, le core lance le moteur Python et le surveille (ADR-0008, décision 2).
La greffe est dans `core/` (liste : `core/PROVENANCE.md`, « Greffes OPSYS »).

- **Activation.** Désactivée par défaut. Elle exige `<dossier de config>/opsys/metier.json` avec
  `"actif": true` et `"dossier"` (chemin absolu du dépôt du moteur). Le format est décrit en tête de
  `core/src/gateway/opsys-metier-config.ts`. Sans ce fichier, le Gateway se comporte comme avant.
- **Lancement.** `uv run opsys-mcp --http --hote 127.0.0.1 --port 8765` dans ce dossier, avec un
  environnement filtré : ni `OPENCLAW_*` ni clés de fournisseurs.
- **Santé.** Le core sonde `GET /sante` (`src/opsys/serveur_mcp.py`, sans jeton ni donnée métier).
  Trois échecs de suite, ou un arrêt du processus : le core termine l'arbre de processus et le
  relance avec un recul de 1 s à 60 s (dix relances de suite au plus, puis état `failed`). L'état
  paraît dans la charge des RPC `health` et `status` (clé `opsysMetier`).
- **Journaux.** Chaque ligne de sortie du moteur passe dans le journal du core, sous-système
  `opsys-metier`. Les sondes ne remplissent pas le journal d'accès d'uvicorn.
- **Une seule authentification.** Le core lit `OPSYS_MCP_JETON` (ou génère un jeton de 256 bits),
  le donne au moteur par l'environnement de l'enfant, et ne l'écrit dans aucun journal. Un jeton
  généré ne sert qu'aux lectures ultérieures de la configuration : la première lecture de
  `${OPSYS_MCP_JETON}` exige que la variable existe déjà (fichier `.env` posé par l'installateur).
- **Installateur.** `install/install.sh` et `install/install.ps1` (PLAN T0.11) posent ce mode sur un poste. Le core
  tourne sous son profil `opsys` (T0.11-b) : son état est le dossier canonique `~/.opsys/core` (T0.7 lot 3 ; avant,
  `~/.openclaw-opsys`, que Doctor déplace), dans le dossier d'instance `~/.opsys`, avec les secrets (`.env`), la
  configuration (`opsys.json`, ou l'`openclaw.json` d'avant, lu en place), `opsys/metier.json` et le service du Gateway
  (`openclaw-gateway-opsys`), distinct de celui du core d'origine. Les données métier restent dans `$OPSYS_HOME`
  (`~/.opsys` par défaut : un seul dossier d'instance). Voir [`INSTALLATION.md`](../exploitation/INSTALLATION.md).
- **Docker Compose.** Reste l'option serveur, inchangée : `deploy/` lance encore le moteur et le core dans deux
  conteneurs. Son passage au superviseur est une décision séparée.

## Moteur de contexte (PLAN T3.3-suite)

**Frontière vérifiée pour la voie de contexte M10 :** l'origine est prise du serveur sélectionné
par le core, jamais d'un argument libre de l'outil. Pour chaque agent configuré, `openclaw.py`
déclare `opsys_context_<agent>` sur `/mcp/contexte/<agent>` avec le secret dédié
`OPSYS_CONTEXT_MCP_JETON`. Le serveur attribue l'appel à cet agent, n'expose que
`m10_paquet_contexte_affaire`, et refuse le secret public `OPSYS_MCP_JETON` sur cette route.
Les noms `opsys_context_*__*` sont refusés par la politique des outils du modèle. Le moteur de
contexte les appelle par sa configuration privée `contextServers`.

Le garde C02 compare aussi la cible typée de l'appel avec l'affaire du PREFLIGHT : pour le cas
M3 `m3_estimer_projet`, seul `contrat.lead_id` correspondant au lead canonique connu est admis.
Champ absent, mal formé ou lead inconnu/mal apparié : refus. Cette correction ne valide pas les
autres classes C02 ni leurs liaisons d'affaires. Pour C03, une configuration explicitement
active mais invalide bloque les outils OPSYS concernés; l'absence ou la désactivation explicite
du moteur reste une configuration inactive. Détails et limites : [ADR-0010](../decisions/ADR-0010-memoire.md).

La « RAM » d'ADR-0010 : un moteur de contexte du core (`core/src/context-engine/opsys-contexte-*.ts`, liste :
`core/PROVENANCE.md`), choisi par `plugins.slots.contextEngine: "opsys"`.

```
 tour d'un agent de département ──► assemble()  ──► M10 : m10_paquet_contexte_affaire (T0)
        (session + cible typée)         │                 /mcp/contexte/<agentId>, OPSYS_CONTEXT_MCP_JETON
                                        └─► systemPromptAddition : le paquet, ou « contexte d'entreprise indisponible »
 fin du tour ────────────────────► afterTurn() ──► M10 : m10_deposer_faits_candidats (T1, N2)
                                                      ce que les outils ont fait, jamais le texte du modèle
```

- **Activation.** Désactivé par défaut. `opsys-metier openclaw configurer --contexte-entreprise
  m03-estimation:m3_estimer_projet` écrit `opsys/contexte.json` (`"actif": true`, agents et outils déposés) et
  `plugins.slots.contextEngine` ensemble. Sans l'option, le moteur n'est pas choisi.
- **Le code calcule.** M10 calcule le paquet, son budget et sa troncature. Le core ne fait que le valider et
  le rendre ; il ne le tronque jamais.
- **Fail-closed.** Moteur injoignable, trop lent (`delai_ms`), paquet invalide ou sans affaire : le PREFLIGHT
  n'injecte pas de paquet et le garde refuse une action N3+ exigeant ce PREFLIGHT. Une configuration active
  invalide bloque les appels OPSYS. La configuration désactivée reste sans garde.
- **L'affaire elle-même** (T4.18-b). Une affaire est un lead ou l'opportunité `<lead>~opp~<wct_id>` que M2 ouvre : une forme
  bornée, écrite dans M10 et dans le core, testée des deux côtés contre la même liste de cas. Le paquet porte, hors de ses quatre couches, un
  bloc `affaire` (connue ou inconnue, étape d'origine reçue ou non, verdict) et un bloc `consolidation` (les jours omis à
  consolider) ; le core les valide et les rend, sans changer le garde. Budget du paquet et décisions : ADR-0010, « T4.18-b ».
- **Limites restantes** : liaison automatique d'une session à un lead, intégration des faits POSTFLIGHT à la
  consolidation durable, réutilisation de connexion, paquet spécialisé estimé/réel et essais d'un tour agent réel.
  Les corrections C02/C03 couvertes sont délimitées dans ADR-0010; elles ne valent pas correction de toutes les
  familles de cibles C02.

## Couches

| Couche | Rôle | Où |
|---|---|---|
| **OPSYS-CORE** | Boucle d'agents, canaux, mémoire native, automatisations, Control UI ; capacités amont à qualifier par canal et configuration | Fork dur d'OpenClaw (ADR-0008) : `core/`, provenance `core/PROVENANCE.md` |
| **Capacités (MCP)** | Outils des départements et outils communs (`opsys_*`). `/mcp/<id>` fixe l'exécuteur départemental. La voie privée `/mcp/contexte/<agentId>` fixe séparément l'origine de lecture M10, utilise `OPSYS_CONTEXT_MCP_JETON` et n'expose que le paquet d'affaire au moteur de contexte; le namespace est refusé aux outils LLM | `src/opsys/serveur_mcp.py`, `capacites.py`, `contexte.py`, `openclaw.py` |
| **Départements M1–M10** | Code métier déterministe, manifeste, SOUL, skills, tests | `departments/mNN-*/` |
| **Configuration du Core** | Un agent par département, fournisseur de modèles dédié, serveur MCP dédié (`opsys_mN`) et refus des serveurs des autres départements (`tools.deny`), `$include` | `src/opsys/openclaw.py` |
| **Modèles** | Fournisseurs natifs du core par défaut, cloud/local; références de clés par variables d'environnement; LiteLLM optionnel en compatibilité explicite. Les appels réels exigent des clés et un fournisseur joignable | `src/opsys/openclaw.py`, `modeles.py`, `src/opsys/passerelle.py` |
| **Mémoire** | A : native des agents ; B : connaissance gouvernée par M10. Base métier SQLite par défaut, PostgreSQL optionnel ; RAG actuel pgvector, cible légère ADR-0010 à qualifier. Domaines métier/développement séparés | `docs/memory/RAG-PREMIUM.md`, `src/opsys/memoire/` |
| **Taxonomie métier** | Une seule liste des services de l'entreprise (catalogue de référence + profil `$OPSYS_HOME/entreprise.yaml`), lue par M1, M2 et M3 ; fail-closed sans profil ; contrat `LeadQualifie` v2 | `src/opsys/taxonomie.py`, `docs/architecture/TAXONOMIE.md` |
| **Garde-fou de texte** | Un catalogue de familles de règles nommées (prix, date, engagement, aveu, avis légal, adresse, coordonnées, nom de client, garantie…) que chaque département choisit : réponse à un client (M1), texte public (M7). Le refus nomme la règle ; fail-closed ; module pur | `src/opsys/garde_fou_texte/`, `docs/architecture/DEPARTEMENTS.md` |
| **Console OPSYS** | Départements (modes), approbations, budgets, paliers de modèles | `src/opsys/console/`, `tableau_de_bord.py` |
| **Mobile** | App Expo Router à quatre profils, écrans métier, capture terrain et file hors ligne ; couverture et défauts de reprise/isolation à qualifier, pas seulement un squelette | `mobile/`, `docs/architecture/MOBILE.md` |
| **Déploiement** | compose, `install.sh`, sauvegardes | `deploy/`, `docs/ops/` |

## Principes non négociables

1. **Le code calcule, le LLM orchestre.** Prix, soldes, scores, cédules, quantités et dates viennent
   d'outils déterministes testés.
2. **Fail-closed.** Une donnée manquante donne un verdict qui dit quoi demander. Un prix sans
   entrées suffisantes est bloqué.
3. **Humain dans la boucle par construction.** T2/T3 deviennent des demandes d'approbation (console
   ou app mobile). T3 n'est jamais autonome.
4. **Économie de tokens en couches** : [ECONOMIE-TOKENS](ECONOMIE-TOKENS.md).
5. **Une installation = une entreprise = un VPS.** OpenClaw est mono-tenant.
6. **Fork maintenu par OPSYS.** Modifier le core et intégrer des ingrédients sous licence est
   autorisé ; préserver provenance, contrats, migrations et veille de sécurité. Aucune synchro
   automatique avec l'amont ; une interface stable reste préférable à un couplage privé fragile.
7. **Aucune installation automatique de skills depuis un registre public** (ClawHub) : les capacités
   viennent des départements OPSYS, relus et testés.

## Flux type : une demande de soumission

1. **Réception.** Un client écrit par SMS. L'agent **M1** (lié au canal) appelle ses outils
   (garde-fou d'interdits, qualification, consentement Loi 25) et délègue à **M2**.
2. **Qualification.** **M2** ingère le lead, détecte les doublons et évalue la readiness.
3. **Estimation.** **M3** appelle `m3_estimer_projet`. Deux issues :
   - photos insuffisantes : prix bloqué, et M1 redemande exactement ce qui manque ;
   - sinon : un intervalle en CAD.
4. **Approbation.** L'envoi du devis est une action T2. Il devient une demande d'approbation, que le
   patron approuve dans la console ou depuis l'app mobile. L'outil s'exécute alors avec les
   arguments exacts enregistrés.
5. **Coût et mémoire.** Le modèle utilise son provider/palier configuré ; les usages sont
   attribués au département, les effets métier à M10. Réservation du budget avant appel et
   couverture des retries/sous-agents font partie du plan de consolidation, sans LiteLLM requis.
