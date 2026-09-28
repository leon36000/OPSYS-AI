# Architecture OPSYS-AI v2

> Décisions : [ADR-0006](../decisions/ADR-0006-restructuration-v2-core-hermes.md) (restructuration)
> et [ADR-0007](../decisions/ADR-0007-core-openclaw.md) (Core = OpenClaw).
> Recherche et ingrédients : [`docs/research/`](../research/).

## En une image

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

## Couches

| Couche | Rôle | Où |
|---|---|---|
| **OPSYS-CORE** | Boucle d'agents, canaux (SMS, WhatsApp, courriel, chat, voix), mémoire d'agent, automatisations, Control UI, apps mobiles | OpenClaw épinglé : `core/UPSTREAM.md` |
| **Capacités (MCP)** | Outils des départements et outils communs (`opsys_*`, dont la mémoire). Un point d'accès par département (`/mcp/<id>`) : les outils communs s'exécutent au nom de ce département, jamais d'un nom choisi par le modèle. Applique autonomie, approbations, budget et troncature | `src/opsys/serveur_mcp.py`, `capacites.py`, `contexte.py` |
| **Départements M1–M10** | Code métier déterministe, manifeste, SOUL, skills, tests | `departments/mNN-*/` |
| **Configuration du Core** | Un agent par département, fournisseur de modèles dédié, serveur MCP dédié (`opsys_mN`) et refus des serveurs des autres départements (`tools.deny`), `$include` | `src/opsys/openclaw.py` |
| **Passerelle de modèles** | LiteLLM : paliers → fournisseurs cloud ou locaux, clé virtuelle et plafonds par département, cache | `src/opsys/passerelle.py`, `modeles.py` |
| **Mémoire** | 2 couches : mémoire d'agent OpenClaw + base de connaissances d'entreprise PostgreSQL/pgvector (MCP) | `docs/memory/RAG-PREMIUM.md`, `src/opsys/memoire/` |
| **Console OPSYS** | Départements (modes), approbations, budgets, paliers de modèles | `src/opsys/console/`, `tableau_de_bord.py` |
| **Mobile** | Apps OpenClaw officielles (phase 1), fork OPSYS (phase 2) | `docs/architecture/MOBILE.md` |
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
