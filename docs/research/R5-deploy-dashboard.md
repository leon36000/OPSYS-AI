# R5 — Installation VPS clé en main, dashboard d'administration, observabilité, sécurité d'exploitation

Date de recherche : 2026-09-28. Méthode : faits vérifiés sur sources primaires (fichiers `LICENSE`
lus directement via `raw.githubusercontent.com`, réponses `api.github.com/repos/OWNER/REPO` via
Firecrawl — l'accès direct `api.github.com`/`github.com` par `curl`/`WebFetch` est bloqué par le
proxy de session sauf dépôt attaché), complétés par `WebSearch` pour le contexte marché (marqué
« approximatif » quand la source est secondaire). Deux dépôts candidats au Core (Hermes Agent,
OpenClaw) étaient déjà clonés dans `scratchpad/clones/` par une recherche parallèle et ont été
inspectés directement (code + docs), ce qui a permis une vérification de première main plus
profonde que pour les autres briques.

**Note méthodologique notable** : pour 4 dépôts (Dokploy, Authentik, Infisical, Langfuse),
`api.github.com` renvoie `license.spdx_id = NOASSERTION` (le détecteur GitHub échoue sur une
structure « open-core » ou un nom de fichier non standard), alors que le fichier `LICENSE` réel,
lu directement, est parfaitement clair (permissif au cœur + sous-répertoire commercial séparé). Ne
jamais se fier au seul champ `license` de l'API — toujours lire le fichier. C'est exactement le
principe C (CLAIMS UNVERIFIED) d'AGENTS.md appliqué à un outil automatisé, pas seulement à un LLM.

---

## A. Empaquetage / orchestration VPS

| Brique | Licence (vérifiée) | Langage | Maturité | Apport pour OPSYS | Intégration | Effort | Risques |
|---|---|---|---|---|---|---|---|
| [Coolify](https://github.com/coollabsio/coolify) | **Apache-2.0** (API GitHub, confirmé) | PHP/Laravel | 62 328 ★, push 2026-09-27, actif | Patron d'installateur one-liner + PaaS complet (databases, 280+ services one-click) | Patron seulement (pas vendorisé — trop lourd/PHP hors stack) | — | Réinstaller Coolify en plus d'OPSYS = double plan de contrôle, redondant |
| [Dokploy](https://github.com/Dokploy/dokploy) | **Apache-2.0 au cœur** + `/proprietary` sous « Dokploy Source Available License v1.0 » (lu directement : `LICENSE.MD` + `LICENSE_PROPRIETARY.md`) | TypeScript | 37 543 ★, push 2026-09-24, actif, branche par défaut `canary` | Patron d'installateur one-liner (`curl \| sh`) + docker-compose profiles | Patron seulement | — | Dossier `/proprietary` à ne jamais copier ; défaut GitHub « NOASSERTION » trompeur (voir note méthodo) |
| [Supabase (self-host)](https://github.com/supabase/supabase) | **Apache-2.0** (racine, vérifié) | Multi (Go/Elixir/TS) | très mature, projet YC historique | Patron docker-compose multi-service `.env`-driven, référence pour Postgres+services satellites | Patron seulement | — | Sous-composants non revérifiés individuellement cette recherche |
| [Dify](https://github.com/langgenius/dify) | **« Apache-2.0 modifié »** — clause anti-SaaS-multi-tenant + clause logo (lu intégralement) | Python/TS | très populaire | Patron d'installateur (`docker/docker-compose.yaml` à profils) | Patron seulement | — | **RISQUE licence réel** : « vous ne pouvez pas utiliser le code source de Dify pour opérer un environnement multi-tenant » sans licence commerciale — disqualifiant si OPSYS devient un jour SaaS multi-client (le brief le prévoit explicitly comme objectif à terme) |

**Conclusion A** : aucune de ces 4 briques n'est vendorisée (langages/paradigmes hors stack Python,
ou risque licence pour Dify). Elles servent de **patrons** pour : (1) un script d'installation
one-liner idempotent, (2) des profils `docker compose --profile`, (3) une commande `update`/`rollback`.

---

## B. Reverse proxy + TLS auto

| Brique | Licence | Langage | Maturité | Apport | Intégration | Effort | Risques |
|---|---|---|---|---|---|---|---|
| [Caddy](https://github.com/caddyserver/caddy) | **Apache-2.0** (vérifié) | Go | **76 129 ★**, push 2026-09-26 | HTTPS automatique (Let's Encrypt/ZeroSSL), `Caddyfile` très court | Service sidecar docker (image officielle) | S | Écosystème forward-auth/OIDC moins documenté que Traefik |
| [Traefik](https://github.com/traefik/traefik) | **MIT** (`LICENSE.md`, vérifié) | Go | ~65k ★ (WebSearch, approximatif — non re-vérifié via API), très actif | Découverte automatique via labels Docker, middleware `forwardAuth` natif | Service sidecar docker | S | Config plus verbeuse (labels par service) |

**Choix argumenté** : **Traefik** en défaut. Raison vérifiée : Authentik publie un guide officiel
d'intégration Traefik (`docs.goauthentik.io/.../server_traefik/`) alors que son intégration Caddy
est communautaire seulement (issue GitHub #3180, « no official support », trouvé via WebSearch) —
et OPSYS doit fédérer *plusieurs* interfaces admin (dashboard + Grafana + Uptime Kuma + Langfuse)
derrière un seul login : le middleware `forwardAuth` déclaré une fois et appliqué par labels à
chaque conteneur est le patron le mieux documenté pour ça. **Caddy reste l'option du profil
« minimal »** (une seule interface exposée = pas besoin de forward-auth centralisé, `Caddyfile` de
15 lignes suffit).

---

## C. Données (Postgres, cache, sauvegardes)

| Brique | Licence (vérifiée) | Langage | Maturité | Apport | Intégration | Effort | Risques |
|---|---|---|---|---|---|---|---|
| PostgreSQL 17 | PostgreSQL License (permissive) | C | — | Base relationnelle, déjà la stack OPSYS (psycopg) | Image officielle `postgres:17` | — | — |
| [pgvector](https://github.com/pgvector/pgvector) | **PostgreSQL License** (vérifié) | C | mature | RAG/embeddings — prérequis explicite du brief (« RAG premium ») | Extension compilée dans l'image (`pgvector/pgvector:pg17`) | S | — |
| [Valkey](https://github.com/valkey-io/valkey) | **BSD-3-Clause** (`COPYING`, vérifié) | C | fork Linux Foundation (mars 2024), soutenu par AWS/Google Cloud/Oracle/Ericsson/Snap (WebSearch), 150+ contributeurs dès les premières semaines | Cache + files + pub/sub, compatible protocole Redis | Image officielle sidecar | — | — |
| [Redis](https://github.com/redis/redis) | **Tri-licence RSALv2 / SSPLv1 / AGPLv3** (depuis Redis 8, `LICENSE.txt` vérifié) | C | très mature mais **non permissive** | — | **NON RETENU** | — | RSALv2/SSPLv1 = source-available (pas open-source au sens OSI) ; l'option AGPLv3 elle-même tombe sous la règle « service séparé non modifié » du brief. **Valkey est un remplacement direct sans compromis technique.** |
| [pgBackRest](https://github.com/pgbackrest/pgbackrest) | **MIT** (vérifié) | C | ~2 décennies de terrain ; alerte de soutien en avril 2026 résolue par le passage à 6 sponsors (AWS, Supabase, Percona, pgEdge, Tiger Data, Eon.io — WebSearch) | Sauvegarde physique Postgres : parallèle, incrémentale par bloc, multi-repo S3 | Sidecar/cron docker + repo S3-compatible | M | — |
| [WAL-G](https://github.com/wal-g/wal-g) | **Apache-2.0** (`LICENSE.md`, vérifié) | Go | mature (successeur de WAL-E) | Alternative plus simple : binaire statique unique, streaming direct vers object storage, pas de serveur repo | Sidecar/cron docker | S | Moins complet que pgBackRest (pas de sauvegarde par bloc) |
| [restic](https://github.com/restic/restic) | **BSD-2-Clause** (vérifié) | Go | mature, très utilisé | Sauvegarde générique **hors-Postgres** (volumes Docker : ClickHouse de Langfuse, DB Uptime Kuma, secrets chiffrés) vers S3/B2, chiffré nativement | Sidecar/cron docker | S | Non conçu pour un dump Postgres cohérent — ne pas l'utiliser pour la base elle-même |

**Choix argumenté** : **PostgreSQL 17 + pgvector** (aucun débat), **Valkey** à la place de Redis
(licence disqualifiante), **pgBackRest** en primaire pour Postgres + **restic** en complément pour
les volumes non-SQL. WAL-G noté comme alternative plus légère si l'équipe préfère un seul binaire
Go sans serveur repo.

---

## D. Auth dashboard (le plus léger adapté à une PME)

| Brique | Licence (vérifiée) | Langage | Maturité (★, création) | RAM approx. (WebSearch) | Protocoles | Risques |
|---|---|---|---|---|---|---|
| [Pocket ID](https://github.com/pocket-id/pocket-id) | **BSD-2-Clause** (vérifié) | Go | **9 307 ★**, créé 2024-08-11 (croissance très rapide pour son âge), push 2026-09-28 | Très faible (binaire Go unique) | OIDC/OAuth2 **certifié OpenID**, passkeys/WebAuthn uniquement (pas de mot de passe = pas de base de mots de passe à fuiter) | Jeune projet ; pas de SAML/LDAP |
| [Authentik](https://github.com/goauthentik/authentik) | **MIT au cœur** (+ `enterprise/` séparé, `website/` CC-BY-SA — lu intégralement ; API GitHub affiche « NOASSERTION » à tort) | Python/TS | **25 758 ★**, créé 2019, push 2026-09-28 (très actif) | ~250–350 Mo (stack + Postgres, sans Redis depuis 2025.10 — WebSearch) | OIDC, SAML, LDAP, proxy forward-auth | Plus riche donc plus de surface |
| [Zitadel](https://github.com/zitadel/zitadel) | **AGPLv3** (vérifié, API + fichier concordants) | Go | 15 119 ★, créé 2020, push 2026-09-28 | Non recommandé sous 4 Go RAM (WebSearch) | OIDC, SAML, SCIM, multi-tenant natif | **RISQUE licence** (service séparé non modifié uniquement) + budget RAM disproportionné pour un VPS 8-16 Go partagé avec tout le reste |
| [Keycloak](https://github.com/keycloak/keycloak) | **Apache-2.0** (`LICENSE.txt`, vérifié) | Java/Quarkus | **37 021 ★**, créé 2013, très large adoption entreprise | Java = empreinte mémoire significative (≥2 Go recommandé) | OIDC, SAML, LDAP fédéré — le plus complet | Licence OK mais poids disproportionné pour une PME sur VPS unique |

**Choix argumenté** : **Pocket ID** pour le profil « minimal » — licence la plus permissive du lot,
empreinte la plus légère, authentification passkey-only (supprime la classe de risque « mot de
passe volé/rejoué », pertinent pour la conformité Loi 25), et croissance communautaire rapide
malgré sa jeunesse. **Authentik** en profil « full » dès que la PME a besoin de SAML/LDAP (ex. un
futur ERP comptable) ou de politiques d'accès par groupe plus fines — cœur MIT, très actif,
empreinte encore raisonnable. **Zitadel et Keycloak explicitement écartés** pour ce contexte : le
premier pour la licence + le budget RAM, le second pour le poids Java disproportionné face à un
VPS 2-4 vCPU/8-16 Go déjà partagé par Postgres/Valkey/Langfuse/Core.

---

## E. Secrets

| Brique | Licence (vérifiée) | Apport | Intégration | Effort | Risques |
|---|---|---|---|---|---|
| [sops](https://github.com/getsops/sops) | **MPL-2.0** (vérifié) | Chiffrement de `.env`/YAML au repos, diff Git lisible (seules les valeurs sont chiffrées) | Binaire CLI, aucun conteneur | S | — |
| [age](https://github.com/FiloSottile/age) | **BSD-3-Clause** (vérifié) | Backend de chiffrement moderne pour sops (remplace GPG) | Binaire CLI | S | Clé privée `age` à sauvegarder hors du VPS (perte = secrets illisibles) |
| Docker `secrets:` | (fonctionnalité Docker native) | Montage tmpfs des secrets les plus sensibles (mot de passe DB, clé JWT) à l'exécution | Natif `docker-compose.yml` | S | — |
| [Infisical](https://github.com/Infisical/infisical) | **MIT au cœur** (+ `ee/` séparé — lu intégralement ; API « NOASSERTION » à tort) | Gestion de secrets en équipe avec audit trail, rotation, RBAC | Service sidecar (ajoute Postgres propre) | M | Sur-ingénierie pour un opérateur solo sur un seul VPS |

**Choix argumenté** : **sops+age pour le fichier au repos** (zéro conteneur, zéro dépendance
serveur — proportionné à une PME) + **Docker `secrets:`** pour l'injection runtime des valeurs les
plus critiques. **Infisical réservé au profil « full »**, seulement si une équipe multi-opérateurs
a besoin d'un contrôle d'accès et d'un audit trail sur les secrets — ne pas l'ajouter par défaut :
c'est exactement le type de complexité que le principe « pas seulement pas cher, mais proportionné »
d'AGENTS.md invite à éviter tant que le besoin n'est pas prouvé.

---

## F. Observabilité LLM et système

| Brique | Licence (vérifiée) | Langage | Maturité | Apport | Intégration | Effort | Risques |
|---|---|---|---|---|---|---|---|
| [Langfuse](https://github.com/langfuse/langfuse) | **MIT au cœur** (`ee/LICENSE` lu intégralement : « Langfuse's core is permissively licensed (MIT). [...] this license does not apply to the core ») | TS | **35 116 ★**, créé 2023, racheté par ClickHouse (janv. 2026, WebSearch), YC, très actif | Tracing LLM par requête, coût/tokens par modèle, prompt management, évaluations, playground — **sans limite** sur le cœur self-hosted | Service sidecar (web+worker) + **ClickHouse** (dépendance propre, coûteuse en RAM) + Postgres | M | SSO/OIDC potentiellement réservé à l'édition Enterprise (`ee/`) — **à confirmer avant implémentation** ; sinon login local Langfuse derrière le forward-auth Traefik |
| [OpenTelemetry Collector](https://github.com/open-telemetry/opentelemetry-collector) | **Apache-2.0** (vérifié) | Go | projet CNCF | Point d'entrée OTLP unique : reçoit traces LLM (→ Langfuse) et métriques système (→ Prometheus) | Sidecar docker | S | — |
| [Prometheus](https://github.com/prometheus/prometheus) | **Apache-2.0** (vérifié) | Go | projet CNCF, référence | Métriques système/containers (via node-exporter + cAdvisor, tous deux Apache-2.0) | Sidecar docker | S | — |
| [Grafana](https://github.com/grafana/grafana) | **AGPLv3** (vérifié) | Go/TS | référence du marché | Dashboards visuels (Prometheus + éventuellement Postgres) | Sidecar docker, **non modifié**, frontière réseau | S | **AGPL** — conforme uniquement en service séparé non modifié (brief §Contraintes) ; ne jamais vendoriser/patcher son code |
| [Uptime Kuma](https://github.com/louislam/uptime-kuma) | **MIT** (vérifié) | JS | **91 888 ★** (le plus populaire de tout ce rapport), push continu | Sondes actives (HTTP/TCP/DNS) sur le dashboard public, les webhooks M1, le site M7 ; alerte email/Telegram/webhook si down | Sidecar docker, SQLite interne | S | Pas d'OIDC natif connu — login local + TOTP intégré suffisant vu la sensibilité faible (page de statut) |

**Choix argumenté** : **OTel Collector en hub unique** (un seul point d'intégration à coder dans le
Core plutôt que N exportateurs) → **Langfuse** pour la traçabilité LLM/coût-par-modèle (répond
directement à l'exigence #3 du brief, « économie de tokens maximale ») → **Prometheus/Grafana**
pour la santé VPS/conteneurs (AGPL assumé comme service non modifié) → **Uptime Kuma** en sonde
externe indépendante (« qui surveille le surveillant »). Le stack ClickHouse de Langfuse est la
seule brique vraiment lourde de ce rapport : elle pousse le profil « full » vers le palier haut
(4 vCPU/16 Go) — à isoler clairement du profil « minimal ».

---

## G. Durcissement VPS + Loi 25

| Élément | Licence | Rôle | Risques/notes |
|---|---|---|---|
| ufw | GPLv2 (paquet OS standard) | Pare-feu par défaut : deny in, allow 22 (rate-limited)/80/443 | Outil hôte, jamais embarqué dans l'image — aucune obligation de publication |
| [fail2ban](https://github.com/fail2ban/fail2ban) | **GPLv2** (`COPYING`, vérifié) | Bannissement IP sur échecs SSH/auth reverse-proxy | Idem — paquet hôte, GPL sans impact sur OPSYS |
| unattended-upgrades | (paquet Debian/Ubuntu officiel) | Correctifs de sécurité auto | — |
| Docker rootless | Apache-2.0 (Moby) | Isolation défense-en-profondeur | Friction connue et **documentée dans le code source Hermes Agent lui-même** (`docker-compose.yml` : remap `HERMES_UID`/`HERMES_GID` via s6-overlay pour que les bind-mounts restent lisibles) — anticiper le même pattern pour les volumes OPSYS |
| Utilisateur non-root de déploiement | — | Compte dédié `opsys`, groupe `docker` (ou rootless) | — |

**Loi 25 (vérifié via WebSearch, CAI du Québec)** : la loi **n'impose pas explicitement** l'hébergement
au Québec/Canada, mais **exige une Évaluation des Facteurs relatifs à la Vie Privée (ÉFVP)
obligatoire depuis septembre 2023** avant toute communication/hébergement de renseignements
personnels **hors Québec**, plus une entente écrite évaluant le régime juridique de l'État
destinataire. → **Recommandation pragmatique** : héberger le VPS dans une région canadienne (ex.
OVHcloud Beauharnois QC, ou Toronto chez DigitalOcean/Vultr) pour éviter cette charge de conformité
récurrente ; si un bucket S3 US-based (ex. Backblaze B2, dont les datacenters sont aux États-Unis)
est retenu pour les sauvegardes malgré tout, chiffrer **avant** l'upload (pgBackRest/restic le font
nativement) et documenter l'ÉFVP correspondante — ou préférer un object storage compatible S3
hébergé au Canada (ex. OVH Object Storage Beauharnois) pour éviter la question entièrement.

---

## H. Dashboard central — extension du Core retenu vs construction séparée

### Ce qui a été vérifié dans le code/documentation des deux candidats Core

**Hermes Agent** (`hermes dashboard`, port **9119**, `127.0.0.1` par défaut — vérifié dans
`docker-compose.yml`, `nix/moduleCommon.nix`, `docker/stage2-hook.sh`) : dashboard React/shadcn +
backend FastAPI, avec un **système de plugins et de thèmes entièrement documenté**
(`website/docs/user-guide/features/extending-the-dashboard.md`, lu intégralement — 928 lignes) :
- Plugin = dossier `~/.hermes/plugins/<name>/dashboard/` avec `manifest.json` + bundle JS IIFE
  **sans étape de build** + `plugin_api.py` (FastAPI `router` auto-monté sous `/api/plugins/<name>/`).
- Peut ajouter un onglet (`tab.path`), remplacer une page existante (`tab.override`), ou injecter
  dans des slots nommés sur des pages existantes (`sessions:top`, `analytics:top`, etc.).
- Rechargement à chaud (`GET /api/dashboard/plugins/rescan`), pas de redémarrage nécessaire pour
  l'UI (redémarrage requis seulement pour les routes backend).
- **Page Analytics native déjà présente** (`web-dashboard.md`, lu) : coût/tokens par jour, par
  modèle, taux de cache-hit — **répond directement à l'exigence « budgets tokens » du brief sans
  rien construire**.
- Docs connexes confirmant la pertinence pour OPSYS : `memory-providers.md`, `credential-pools.md`,
  `provider-routing.md`, `fallback-providers.md` (routage multi-fournisseur + bascule automatique —
  directement réutilisable pour l'exigence #3 « économie de tokens » et #4 « connecter les modèles »).

**OpenClaw** (Control UI, Gateway port **18789** — vérifié dans `docker-compose.yml`) : la
« dashboard » d'OpenClaw est un **concept différent** : un canevas de widgets **par session de
chat**, généré par l'agent (`show_widget`), épinglable, sandboxé en iframe (`docs/web/
dashboard-architecture.md`, lu intégralement — 617 lignes). C'est un patron « l'agent construit une
mini-UI en direct pendant la conversation », pas une console d'administration persistante
multi-pages. L'extension par un tiers pour une **vraie page d'admin permanente** exige le champ
manifest `controlUi.entry` : un bundle JS/CSS **compilé** via `openclaw plugins build`, et cette
UI native tierce est **derrière un drapeau expérimental désactivé par défaut**
(`gateway.controlUi.experimental.customPlugins`, `docs/plugins/manifest/surfaces.md`, lu
intégralement). Le Gateway se durcit par défaut sur loopback + jeton, avec délégation d'auth à un
proxy de confiance plutôt qu'un OIDC natif (`docs/gateway/security/hardened-baseline.md`, lu).

### Recommandation argumentée

**Si Hermes Agent est le Core retenu → étendre son dashboard.** Son modèle de plugin est déjà
exactement la forme dont OPSYS a besoin (onglets par département M1-M10, slots pour enrichir les
pages Sessions/Analytics/Config existantes, `plugin_api.py` FastAPI pour exposer les endpoints
propres à chaque module), sans étape de build, avec rechargement à chaud, et la page Analytics
couvre déjà « budgets tokens » nativement. Effort estimé **S/M par département** (un plugin
Hermes = un dossier + un manifeste + un routeur FastAPI qui appelle le code métier Python déjà
existant des modules M1-M10).

**Si OpenClaw est le Core retenu → construire une console séparée (FastAPI + htmx, ou FastAPI +
shadcn/ui + Refine) plutôt que de forcer son Control UI.** Le canevas de widgets par session
d'OpenClaw est un excellent outil pour « l'agent te montre un graphique en direct », mais ce n'est
pas le bon substrat pour une console d'administration permanente multi-département ; la voie
officielle pour une vraie page tierce (`controlUi.entry`) est plus lourde (build obligatoire) et
gardée derrière un drapeau expérimental non destiné par défaut aux tiers. La console séparée
consommerait l'API/Gateway RPC d'OpenClaw (même chemin que son propre Control UI) sans dépendre de
sa surface d'extension expérimentale. `refinedev/refine` (MIT, vérifié) et `shadcn-ui/ui` (MIT,
vérifié) + `tiangolo/fastapi` (MIT, vérifié) sont les briques recommandées pour cette option.

**Dans les deux cas** : le dashboard OPSYS ne doit **pas** réimplémenter les graphiques
coût-par-modèle ou la supervision système — il doit **orchestrer et embarquer** (via iframe +
SSO forward-auth) les pages déjà construites par Langfuse/Grafana/Uptime Kuma, et se concentrer sur
ce qui est propre à OPSYS : connexion des modèles, budgets par département, mémoire (M10),
canaux (M1). Un embryon de dashboard existe déjà dans le dépôt OPSYS-AI
(`surfaces/dashboard/src/dashboard_server.py`, stdlib Python pur, lu au moment de cette recherche —
squelette « P0-5a », état non garanti stable au moment de la lecture d'un autre chantier concurrent
sur le même dépôt) : il devrait être **remplacé** par l'extension du Core retenu plutôt que
développé en parallèle, pour éviter deux plans de contrôle.

---

## INGRÉDIENTS RETENUS (classés)

1. **Reverse proxy** : Traefik (défaut) / Caddy (profil minimal)
2. **Données** : PostgreSQL 17 + pgvector · Valkey (jamais Redis)
3. **Sauvegardes** : pgBackRest (Postgres) + restic (volumes non-SQL) → S3-compatible canadien
4. **Auth** : Pocket ID (défaut, minimal) → Authentik (upgrade profil full)
5. **Secrets** : sops + age (fichier au repos) + Docker `secrets:` (runtime) → Infisical seulement si équipe multi-opérateurs
6. **Observabilité** : OpenTelemetry Collector (hub) → Langfuse (LLM/coûts) + Prometheus/Grafana (système, AGPL assumé non modifié) + Uptime Kuma (sonde externe)
7. **Durcissement** : ufw + fail2ban + unattended-upgrades + utilisateur non-root/rootless docker + hébergement canadien (Loi 25)
8. **Dashboard** : extension du Core (Hermes) **ou** FastAPI+htmx/shadcn (si OpenClaw) — jamais les deux en parallèle
9. **Patrons d'installateur** (non vendorisés) : Coolify, Dokploy — **Dify écarté** (clause licence anti-SaaS-multi-tenant incompatible avec la trajectoire SaaS du brief)

---

## RECETTE — Architecture cible

### Schéma texte (conteneurs / ports / volumes / réseaux)

```
Internet
   │  :443/:80 (TLS auto)                    :22 (ssh, ufw+fail2ban, rate-limited)
   ▼
┌──────────────────────────────── réseau "edge" ────────────────────────────────┐
│  traefik (ou caddy)            ports hôte: 80,443                             │
│  - forwardAuth → pocket-id     volumes: letsencrypt-certs, traefik.yml, docker.sock:ro │
└───────┬───────────┬───────────────┬───────────────┬───────────────┬──────────┘
        │            │               │               │               │
   (proxy only, aucun port host exposé au-delà de traefik)
        │            │               │               │               │
┌───────▼──┐   ┌─────▼─────┐   ┌─────▼──────┐  ┌─────▼──────┐  ┌─────▼──────┐
│ pocket-id│   │  opsys-   │   │  langfuse- │   │  grafana   │   │ uptime-kuma│
│ (OIDC)   │   │ dashboard │   │  web       │   │            │   │            │
│ :1411    │   │(ext.Core) │   │            │   │            │   │            │
└───────┬──┘   └─────┬─────┘   └─────┬──────┘   └─────┬──────┘   └─────┬──────┘
        │             │               │                │                │
════════╪═════════════╪═══════════════╪════════════════╪════════════════╪═══════
        │             │    réseau "internal" (aucun port host)          │
┌───────▼─────────────▼───┐  ┌────────▼────────┐  ┌─────▼──────┐  ┌────▼─────┐
│  opsys-core (Hermes/     │  │ langfuse-worker │  │ prometheus │  │ (kuma db │
│  OpenClaw fork, M1-M10)  │  │ + clickhouse    │  │ node-export│  │  interne)│
└───────┬──────────────────┘  │ + postgres-lf   │  │ cadvisor   │  └──────────┘
        │                     └────────┬────────┘  └─────┬──────┘
        │                              │                  │
┌───────▼──────────┐  ┌────────────────▼───┐   ┌──────────▼────┐  ┌───────────┐
│ postgres (17+     │  │  otel-collector     │   │ (scrape only) │  │  ollama   │
│ pgvector) :5432   │  │  OTLP in → out      │   └────────────────┘  │ (profil   │
│ volume: pgdata    │  └─────────────────────┘                       │  ollama)  │
├────────────────────┤                                                │ :11434   │
│ valkey :6379       │                                                │ volume:  │
│ volume: valkey-data│                                                │ ollama-  │
└─────────────────────┘                                               │ models   │
                                                                       └───────────┘
┌── cron/systemd timer (hôte, hors compose) ──────────────────────────────────┐
│ pgbackrest  : full hebdo + incr. quotidien + WAL continu → S3 CA            │
│ restic      : nocturne, volumes non-SQL (clickhouse, kuma, secrets.enc) → S3│
│ restore-drill : mensuel, restauration jetable + vérif, log → registries/    │
└───────────────────────────────────────────────────────────────────────────┘

Secrets: ./secrets/opsys.env.sops (chiffré age, dans Git) → déchiffré au déploiement
         → Docker secrets (tmpfs) pour DB password / JWT signing key
```

Profils `docker compose --profile` :
- **minimal** (2-4 vCPU/8 Go) : traefik|caddy, pocket-id, opsys-dashboard, opsys-core, postgres+pgvector, valkey, uptime-kuma, otel-collector (léger), cron backup. *Pas de Langfuse/Grafana/Prometheus.*
- **full** (4 vCPU/16 Go) : minimal + langfuse (web+worker+clickhouse) + prometheus+grafana+node-exporter+cadvisor + authentik (remplace pocket-id) + infisical (optionnel).
- **ollama** (additif, nécessite RAM dédiée par modèle — CPU-only sur 2-4 vCPU reste lent, réservé aux petits modèles ou à un VPS dimensionné plus haut) : ajoute le service `ollama` + volume `ollama-models`.

### Recette d'installation (one-liner, patron Coolify/Dokploy)

1. `curl -fsSL https://<host-opsys>/install.sh | bash -s -- --profile minimal --domain exemple.ca`
   → vérifie OS (Debian/Ubuntu LTS), installe Docker Engine+Compose si absent, crée l'utilisateur
   `opsys` non-root (groupe `docker`), applique ufw (deny in / allow 22,80,443) + fail2ban +
   unattended-upgrades, clone le bundle compose dans `/opt/opsys`.
2. Génération `.env` (mots de passe `openssl rand`, domaine, email ACME) → chiffrement immédiat
   avec `sops -e --age <pubkey>` ; la clé privée `age` est affichée **une seule fois** puis stockée
   hors dépôt (`/opt/opsys/secrets/age.key`, mode 600) — à sauvegarder par l'opérateur.
3. `docker compose --profile minimal up -d` → health-check automatique (curl `/health` via le
   proxy, vérifie le certificat TLS) → affiche l'URL de bootstrap Pocket ID (premier compte admin).
4. **Mise à jour** : `opsys update` → `docker compose pull` + `up -d --remove-orphans` + job de
   migration DB + health-check ; le tag de release déployé est journalisé en append-only dans
   `/opt/opsys/releases.log` (même patron que `registries/ledger/*.jsonl` du projet).
5. **Rollback** : `opsys rollback` → relit la release précédente dans `releases.log`, repointe les
   tags d'image dans `.env`, `up -d`, re-vérifie le health-check.
6. **Sauvegarde/restauration testée** : pgBackRest (full hebdo + incrémental quotidien + WAL
   continu) + restic (nocturne, volumes non-SQL), les deux chiffrés avant upload vers un bucket
   S3-compatible hébergé au Canada. Un job mensuel restaure dans un conteneur Postgres jetable,
   vérifie `pg_isready` + une requête de contrôle, et journalise PASS/FAIL — preuve d'exécution
   réelle exploitable par `scripts/ledger_append.py` (principe P du projet : DONE-avec-preuve).

---

## Sources principales

- Fichiers `LICENSE`/`COPYING`/`LICENSE.md`/`LICENSE.MD` lus directement sur `raw.githubusercontent.com`
  pour : coolify, dokploy (+`LICENSE_PROPRIETARY.md`), supabase, dify, caddy, traefik, pgvector,
  valkey, redis, pgbackrest, wal-g, restic, langfuse (+`ee/LICENSE`), opentelemetry-collector,
  prometheus, grafana, uptime-kuma, authentik, zitadel, keycloak, pocket-id, infisical, sops, age,
  fail2ban, refine, shadcn/ui, fastapi, hermes-agent (local), openclaw (local).
- `api.github.com/repos/...` (via Firecrawl, proxy direct bloqué) pour étoiles/dates de push :
  coolify, dokploy, caddy, authentik, zitadel, pocket-id, keycloak, infisical, langfuse,
  uptime-kuma, hermes-agent, openclaw.
- Code/doc source lus intégralement dans les clones locaux : `hermes-agent/website/docs/user-guide/
  features/extending-the-dashboard.md`, `.../web-dashboard.md`, `hermes-agent/docker-compose.yml`,
  `openclaw/docs/web/dashboard-architecture.md`, `openclaw/docs/plugins/manifest/surfaces.md`,
  `openclaw/docs/vps.md`, `openclaw/docs/gateway/security/hardened-baseline.md`,
  `openclaw/docker-compose.yml`.
- WebSearch (secondaire, marqué comme tel dans le texte) : Valkey/Linux Foundation, comparatif
  Authentik/Zitadel/Keycloak (RAM), comparatif pgBackRest/WAL-G/restic, Langfuse self-host/licence,
  Caddy `forward_auth` vs Traefik `forwardAuth` + Authentik, CAI Québec / Loi 25 (transferts hors
  Québec, ÉFVP obligatoire depuis 09/2023).
