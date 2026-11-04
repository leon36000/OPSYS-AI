# OPSYS-AI

**Système d'entreprise IA pour PME, conçu pour une installation sur votre propre VPS.**

Dix départements pilotés par des agents IA, gérés depuis la console OPSYS et le Control UI :
M1 Front Office (Léa), M2 Revenue CRM (Victor), M3 Estimation (Mathis), M4 Field Ops (Gabriel),
M5 FinanceCore (Sophie), M6 Material Control (Rosalie), M7 Marketing (Chloé), M8 Analytics (Olivier),
M9 Strategic Intelligence (Athéna), M10 Mémoire (Mnémo). Seule la messagerie des avatars est disponible.

- **OPSYS-CORE** : fork modifié d'[OpenClaw](https://github.com/openclaw/openclaw) (MIT),
  maintenu par OPSYS : agents, canaux, mémoire native, automatisations et Control UI.
- **Départements** : outils déterministes exposés en MCP, données métier, politiques,
  approbations et audit partagés. Leur profondeur cible dépasse les parcours déjà livrés.
- **Dashboard** : modes, modèles, budgets et profils de spécialistes configurables par département.
  Leur autonomie et leurs capacités complètes restent à consolider selon le
  [périmètre cible](docs/produit/PERIMETRE-MODULES.md).
- **Modèles cloud ou locaux** : LiteLLM est la passerelle de modèles par défaut du déploiement serveur
  (profil `litellm`, ou le LiteLLM existant du client). Une clé OpenRouter saisie une fois dans le coffre,
  dix rôles (LLM rapide, fort, raisonnement, embeddings, reranker, OCR, vision-langage, voix, image) avec
  repli, plafonds et licences, une politique d'économie (Haiku d'abord, Sonnet par défaut, Opus seulement par
  escalade approuvée) : console Plateforme → Modèles et rôles, [PASSERELLE-DE-MODELES](docs/architecture/PASSERELLE-DE-MODELES.md).
  Aucune valeur secrète n'est écrite dans la configuration générée. Les fournisseurs natifs restent possibles.
  Prouvé contre un faux serveur compatible OpenAI ; les appels réels exigent des credentials et ne sont pas
  prouvés par les tests sans secret.
- **Économie de tokens** : calculs déterministes, contexte ciblé, sorties bornées et comptabilité
  des usages ; couverture complète des budgets fournisseur à consolider.
- **Mobile OPSYS** : application Expo à quatre profils, capture terrain et file hors ligne.
- **Mémoire** : mémoire native des agents et connaissance gouvernée par M10 ; mémoire d'affaires
  et du développement séparées par droits. Le socle utilise SQLite par défaut, PostgreSQL en option (éprouvé sur PostgreSQL 17 réel pour le socle, le bus, les constats
  planifiés et l'entrepôt M8 ; charge, durabilité et pool externe non prouvés : `docs/qualification/QUALIFICATION-POSTGRESQL.md`).
- **Humain dans la boucle** : les actions financières, fiscales, légales et sensibles nécessitent
  une approbation. Les contrôles de développement sont proportionnés, sans consensus de modèles.

État : produit en consolidation, pas certification de complétion ou de production.
Direction : [directives Nathan](docs/produit/DIRECTIVES-NATHAN.md).
Recherche : [briques qualifiées GitHub/GitLab](docs/research/R16-2026-09-30/README.md).
Travail courant : [plan de restructuration](docs/programme/RESTRUCTURATION-2026-09-30.md).
Bilan : [restructuration du 30 septembre](docs/programme/BILAN-RESTRUCTURATION-2026-09-30.md).

## Documentation d'utilisation

- [Guide du propriétaire](docs/utilisation/GUIDE-PROPRIETAIRE.md) : ce que fait OPSYS-AI pour vous, ce qui est automatisé, ce que vous approuvez.
- [Guide d'administration](docs/utilisation/GUIDE-ADMINISTRATION.md) : installation, sauvegarde, mise à jour, coffre, fournisseurs, planificateur.
- [Glossaire et FAQ](docs/utilisation/GLOSSAIRE-ET-FAQ.md).
- [Limites connues et ce qui reste à valider](docs/utilisation/LIMITES-CONNUES.md) : **à lire avant de se fier à une fonction**.
- Licences : [inventaire](docs/compliance/INVENTAIRE-LICENCES.md), [SBOM](docs/compliance/sbom.cdx.json),
  [questions à un avocat](docs/compliance/QUESTIONS-AVOCAT.md).

## Chiffres clés

Vérifiés par `tests/test_coherence_documentaire.py` contre `opsys-metier verifier`, les fichiers de migration, le registre MCP et le
catalogue de fournisseurs : un chiffre périmé fait échouer le test.

<!-- chiffres:debut -->
| Chiffre | Valeur |
|---|---|
| Départements | 10 |
| Outils | 695 |
| Outils ouverts aux appareils | 256 |
| Avatars | 10 |
| Packs sectoriels | 2 |
| Fichiers de migration | 50 |
| Tête alembic | 0086 |
| Révision du registre MCP | 34 |
| Outils scellés au registre MCP | 718 |
| Lignes du catalogue de fournisseurs | 66 |
<!-- chiffres:fin -->

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
contredisent. Les composants amont gardent leur licence (OpenClaw : MIT). Inventaire des licences
des dépendances et écarts ouverts : [`docs/compliance/INVENTAIRE-LICENCES.md`](docs/compliance/INVENTAIRE-LICENCES.md).
