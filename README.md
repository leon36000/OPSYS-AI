# OPSYS-AI

**Système d'entreprise autonome clé en main pour PME, installé sur votre propre VPS.**

Dix départements pilotés par des agents IA, gérés depuis la console OPSYS et le Control UI :
M1 Réception, M2 CRM, M3 Estimation, M4 Terrain, M5 Finance, M6 Matériel, M7 Marketing,
M8 Analytique, M9 Stratégie, M10 Mémoire.

- **OPSYS-CORE** : [OpenClaw](https://github.com/openclaw/openclaw) (MIT) épinglé et étendu :
  canaux (SMS, WhatsApp, courriel, chat, voix), mémoire d'agent à provenance, automatisations,
  Control UI et **apps mobiles iOS/Android officielles**.
- **Capacités des départements** exposées en MCP par OPSYS : outils déterministes, politiques
  d'autonomie, approbations humaines, budgets.
- **Modèles cloud ou locaux** via LiteLLM, avec des paliers `local`, `rapide`, `standard` et `fort`
  configurés dans la console OPSYS, et une clé virtuelle avec plafond de tokens par département.
- **Économie de tokens** :
  - calculs par des outils déterministes, pas par le modèle ;
  - budgets par département ;
  - troncature des sorties ;
  - recherche d'outils à la demande.
- **Humain dans la boucle** : les actions sensibles attendent une approbation (console OPSYS ou app mobile).
  Paiements et engagements ne sont jamais autonomes.
- **Mémoire d'entreprise** : PostgreSQL + pgvector (conception : `docs/memory/RAG-PREMIUM.md`).

## Installation

- **Poste ou serveur, sans Docker** (Linux, macOS, Windows) : `install/install.sh` ou `install/install.ps1`, une commande
  qui construit le core, installe le moteur et le service, puis `install/uninstall.sh` (les données ne sont jamais
  supprimées) et `opsys instance exporter` / `restaurer`. Voir
  [`docs/exploitation/INSTALLATION.md`](docs/exploitation/INSTALLATION.md).
- **VPS Ubuntu/Debian avec Docker Compose** (4 vCPU, 8–16 Go) : voir
  [`docs/ops/INSTALLATION-VPS.md`](docs/ops/INSTALLATION-VPS.md).

## Développement

```bash
python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev,postgres]"
pytest && ruff check src tests && opsys verifier
```

Architecture : [`docs/architecture/ARCHITECTURE.md`](docs/architecture/ARCHITECTURE.md) · Décisions :
[ADR-0006](docs/decisions/ADR-0006-restructuration-v2-core-hermes.md),
[ADR-0007](docs/decisions/ADR-0007-core-openclaw.md) · Mobile : [`MOBILE.md`](docs/architecture/MOBILE.md) · Historique v1 :
[`docs/history/`](docs/history/README.md) · Règles de contribution : [`AGENTS.md`](AGENTS.md).

## Licence

À trancher par le propriétaire : `LICENSE` (Apache-2.0) et ADR-0003 (propriétaire) se
contredisent. Les composants amont gardent leur licence (OpenClaw : MIT).
