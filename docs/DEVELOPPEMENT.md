# Repères des mainteneurs OPSYS-AI

Le README d'accueil est volontairement succinct. Ce changement de présentation ne
réduit ni le périmètre produit ni les missions autorisées. Les documents ci-dessous
restent publics tant que le dépôt est public ; ce déplacement n'est pas une mesure
de confidentialité.

## Entrées de travail

- [Instructions communes aux agents](../AGENTS.md) et [instructions Claude](../CLAUDE.md).
- [Directives de Nathan](produit/DIRECTIVES-NATHAN.md).
- [Définition du produit](produit/DEFINITION-PRODUIT.md) et [périmètre des modules](produit/PERIMETRE-MODULES.md).
- [Architecture](architecture/ARCHITECTURE.md), [décisions](decisions/README.md) et
  [plan de restructuration](programme/RESTRUCTURATION-2026-09-30.md).
- [Installation](exploitation/INSTALLATION.md) et [VPS Linux](ops/INSTALLATION-VPS.md).
- [Politique de licence et exceptions](LICENCES.md).

La cible prioritaire de livraison est le VPS Linux ; un serveur dédié Linux est
une alternative. Les grandes exigences serveur précèdent la phase mobile.
Les ambitions et statuts de qualification se lisent dans les plans et les preuves,
pas dans la longueur du README ni dans un nombre de tests.

## Commandes de développement

Dans un environnement de développement isolé, selon AGENTS.md et le mandat courant :

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e ".[dev,postgres]"
pytest
ruff check src tests
opsys-metier verifier
```

Ces commandes ne sont pas une instruction de relancer des intentions déjà closes.
Consulter les propriétaires, baux et checkpoints avant toute exécution partagée.
La commande `opsys` appartient au Core ; `opsys metier <commande>` appelle le moteur
métier dont le point d'entrée indépendant est `opsys-metier`.
