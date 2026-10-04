# OPSYS-AI

**Système d'entreprise IA pour PME, conçu pour une installation sur votre propre VPS.**

Dix départements pilotés par des agents IA, gérés depuis la console OPSYS et le Control UI :
M1 Réception, M2 CRM, M3 Estimation, M4 Terrain, M5 Finance, M6 Matériel, M7 Marketing,
M8 Analytique, M9 Stratégie, M10 Mémoire.

- **OPSYS-CORE** : fork modifié d'[OpenClaw](https://github.com/openclaw/openclaw) (MIT),
  maintenu par OPSYS : agents, canaux, mémoire native, automatisations et Control UI.
- **Départements** : outils déterministes exposés en MCP, données métier, politiques,
  approbations et audit partagés. Leur profondeur cible dépasse les parcours déjà livrés.
- **Dashboard** : modes, modèles, budgets et profils de spécialistes configurables par département.
  Leur autonomie et leurs capacités complètes restent à consolider selon le
  [périmètre cible](docs/produit/PERIMETRE-MODULES.md).
- **Modèles cloud ou locaux** : le générateur configure les fournisseurs natifs par défaut. Les
  paliers portent des références de variables d'environnement pour les clés; aucune valeur secrète
  n'est écrite dans la configuration JSON. LiteLLM reste disponible en compatibilité explicite.
  Sans clé requise, le readiness bloque le démarrage; les appels réels aux fournisseurs exigent
  des credentials et ne sont pas prouvés par les tests sans secret.
- **Économie de tokens** : calculs déterministes, contexte ciblé, sorties bornées et comptabilité
  des usages ; couverture complète des budgets fournisseur à consolider.
- **Mobile OPSYS** : application Expo à quatre profils, capture terrain et file hors ligne.
- **Mémoire** : mémoire native des agents et connaissance gouvernée par M10 ; mémoire d'affaires
  et du développement séparées par droits. Le socle utilise SQLite par défaut, PostgreSQL en option.
- **Humain dans la boucle** : les actions financières, fiscales, légales et sensibles nécessitent
  une approbation. Les contrôles de développement sont proportionnés, sans consensus de modèles.

État : produit en consolidation, pas certification de complétion ou de production.
Direction : [directives Nathan](docs/produit/DIRECTIVES-NATHAN.md).
Recherche : [briques qualifiées GitHub/GitLab](docs/research/R16-2026-09-30/README.md).
Travail courant : [plan de restructuration](docs/programme/RESTRUCTURATION-2026-09-30.md).
Bilan : [restructuration du 30 septembre](docs/programme/BILAN-RESTRUCTURATION-2026-09-30.md).

## Installation

- **Services natifs sur poste ou serveur** (Linux, macOS, Windows), avec Docker Linux requis pour
  les tours d'agents : `install/install.sh` ou `install/install.ps1` construit le core, prépare
  le sandbox et installe le moteur et le service, puis `install/uninstall.sh` et
  `opsys metier instance exporter` / `restaurer`. Les défauts connus de chemins et restauration
  sont indiqués dans le guide et le plan de consolidation. Voir
  [`docs/exploitation/INSTALLATION.md`](docs/exploitation/INSTALLATION.md).
- **Une seule commande, `opsys`** (T0.7 lot 2) : c'est le core (`openclaw` en est l'alias). Le moteur métier se lance par
  `opsys metier <commande>`, ou seul par `opsys-metier <commande>` (Docker Compose, développement). Détail : §« Une seule
  commande » de [`docs/exploitation/INSTALLATION.md`](docs/exploitation/INSTALLATION.md).
- **VPS Ubuntu/Debian avec Docker Compose** (4 vCPU, 8–16 Go) : voir
  [`docs/ops/INSTALLATION-VPS.md`](docs/ops/INSTALLATION-VPS.md).

## Développement

```bash
python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev,postgres]"
pytest && ruff check src tests && opsys-metier verifier
```

Architecture : [`docs/architecture/ARCHITECTURE.md`](docs/architecture/ARCHITECTURE.md) · Décisions :
[index des ADR](docs/decisions/README.md),
[ADR-0012](docs/decisions/ADR-0012-reutilisation-profondeur-productivite.md) · Mobile : [`MOBILE.md`](docs/architecture/MOBILE.md) · Historique v1 :
[`docs/history/`](docs/history/README.md) · Règles de contribution : [`AGENTS.md`](AGENTS.md).

## Licence

À trancher par le propriétaire : `LICENSE` (Apache-2.0) et ADR-0003 (propriétaire) se
contredisent. Les composants amont gardent leur licence (OpenClaw : MIT).
