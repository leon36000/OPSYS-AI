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

Une installation, une commande, partout (portable, serveur, VPS). La section suivante décrit l'état
**transitoire** actuel (OpenClaw consommé de l'extérieur), remplacé au fil des tâches T0 de
[`PLAN.md`](../programme/PLAN.md).

## En une image (état transitoire)

```
                 ┌────────────────────────────── VPS (docker compose) ──────────────────────────────┐
 Clients ─SMS/   │  Caddy (TLS)  ├─ <domaine>         → Control UI OpenClaw (agents, canaux)        │
 WhatsApp/courriel│              └─ console.<domaine> → Console OPSYS (départements, approbations,  │
 Apps mobiles ──►│                                       budgets, modèles, journal)                 │
 (iOS/Android)   │                                                                                  │
                 │  OPSYS-CORE = OpenClaw épinglé (passerelle, canaux, mémoire native, cron)       │
                 │   ├─ agent m01-front-office (canaux clients)   ├─ agents m02…m10               │
                 │   └─ mémoire d'agent : paliers + provenance + « dreaming »                      │
                 │          │ MCP HTTP /mcp/<département> (jeton)     │ modèles : clé virtuelle      │
                 │          ▼                                         ▼ par département             │
                 │  opsys (Python)                            LiteLLM (alias opsys-local/rapide/    │
                 │   ├─ opsys-mcp : outils déterministes            standard/fort ; tpd_limit ;     │
                 │   │   des départements, politiques T0–T3,        cache Valkey)                   │
                 │   │   approbations, troncature, budgets     ──► fournisseurs cloud / Ollama local │
                 │   ├─ console OPSYS                                                               │
                 │   └─ init : config OpenClaw, clés LiteLLM, schéma + purge mémoire                │
                 │  PostgreSQL 17 + pgvector : métier + base de connaissances d'entreprise (RAG)    │
                 └──────────────────────────────────────────────────────────────────────────────────┘
```

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
  tourne sous son profil `opsys` (T0.11-b) : son état est le dossier canonique `~/.openclaw-opsys`, avec les secrets
  (`.env`), `opsys/metier.json` et le service du Gateway (`openclaw-gateway-opsys`), distinct de celui du core
  d'origine. Les données métier restent dans `$OPSYS_HOME`. Voir [`INSTALLATION.md`](../exploitation/INSTALLATION.md).
- **Docker Compose.** Reste l'option serveur, inchangée : `deploy/` lance encore le moteur et le core dans deux
  conteneurs. Son passage au superviseur est une décision séparée.

## Moteur de contexte (PLAN T3.3-suite)

La « RAM » d'ADR-0010 : un moteur de contexte du core (`core/src/context-engine/opsys-contexte-*.ts`, liste :
`core/PROVENANCE.md`), choisi par `plugins.slots.contextEngine: "opsys"`.

```
 tour d'un agent de département ──► assemble()  ──► M10 : m10_paquet_contexte_affaire (T0)
        (ligne « affaire_id: … »)       │                 MCP HTTP /mcp/m10-memoire, jeton OPSYS_MCP_JETON
                                        └─► systemPromptAddition : le paquet, ou « contexte d'entreprise indisponible »
 fin du tour ────────────────────► afterTurn() ──► M10 : m10_deposer_faits_candidats (T1, N2)
                                                      ce que les outils ont fait, jamais le texte du modèle
```

- **Activation.** Désactivé par défaut. `opsys openclaw configurer --contexte-entreprise
  m03-estimation:m3_estimer_projet` écrit `opsys/contexte.json` (`"actif": true`, agents et outils déposés) et
  `plugins.slots.contextEngine` ensemble. Sans l'option, le moteur n'est pas choisi.
- **Le code calcule.** M10 calcule le paquet, son budget et sa troncature. Le core ne fait que le valider et
  le rendre ; il ne le tronque jamais.
- **Fail-closed, sans blocage.** Moteur injoignable, trop lent (`delai_ms`), paquet invalide, aucune affaire :
  le tour continue sans paquet, avec le marqueur dans le contexte et une ligne du journal `opsys-contexte`.
- **Ce qui manque** est listé dans ADR-0010, « Mise en œuvre » (blocage `before_tool_call`, clôture des signaux
  critiques, affaire liée à la session, consolidation des candidats).

## Couches

| Couche | Rôle | Où |
|---|---|---|
| **OPSYS-CORE** | Boucle d'agents, canaux (SMS, WhatsApp, courriel, chat, voix), mémoire d'agent, automatisations, Control UI, apps mobiles | Fork dur d'OpenClaw (ADR-0008) : `core/`, provenance `core/PROVENANCE.md` |
| **Capacités (MCP)** | Outils des départements et outils communs (`opsys_*`, dont la mémoire). Un point d'accès par département (`/mcp/<id>`) : les outils communs s'exécutent au nom de ce département, jamais d'un nom choisi par le modèle. Applique autonomie, approbations, budget et troncature | `src/opsys/serveur_mcp.py`, `capacites.py`, `contexte.py` |
| **Départements M1–M10** | Code métier déterministe, manifeste, SOUL, skills, tests | `departments/mNN-*/` |
| **Configuration du Core** | Un agent par département, fournisseur de modèles dédié, serveur MCP dédié (`opsys_mN`) et refus des serveurs des autres départements (`tools.deny`), `$include` | `src/opsys/openclaw.py` |
| **Passerelle de modèles** | LiteLLM : paliers → fournisseurs cloud ou locaux, clé virtuelle et plafonds par département, cache | `src/opsys/passerelle.py`, `modeles.py` |
| **Mémoire** | 2 couches : mémoire d'agent OpenClaw + base de connaissances d'entreprise PostgreSQL/pgvector (MCP) | `docs/memory/RAG-PREMIUM.md`, `src/opsys/memoire/` |
| **Taxonomie métier** | Une seule liste des services de l'entreprise (catalogue de référence + profil `$OPSYS_HOME/entreprise.yaml`), lue par M1, M2 et M3 ; fail-closed sans profil ; contrat `LeadQualifie` v2 | `src/opsys/taxonomie.py`, `docs/architecture/TAXONOMIE.md` |
| **Console OPSYS** | Départements (modes), approbations, budgets, paliers de modèles | `src/opsys/console/`, `tableau_de_bord.py` |
| **Mobile** | Nouvelle app Expo Router (pas un fork OpenClaw — ADR-0008, R12) : routage gardé par rôle, file sortante et client `/tools/invoke` en logique pure ; squelette seulement (PLAN T1.4-a), aucun écran métier | `mobile/`, `docs/architecture/MOBILE.md` |
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
6. **Interfaces publiques vers l'amont uniquement** (MCP, configuration, `$include`, CLI). Les patchs
   amont sont l'exception, et ils sont versionnés.
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
5. **Comptabilité.** Chaque appel de modèle passe par la clé LiteLLM du département : dépense
   visible et plafond de tokens par jour appliqué par la passerelle.
