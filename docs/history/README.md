# Historique — état avant la restructuration v2

La restructuration v2 (septembre 2026) a retiré du dépôt la couche de gouvernance historique.
Rien n'est perdu : tout reste dans l'historique git.

**Dernier état complet avant restructuration : commit `fcb65bc`** (`main`, 2026-09-05).

Pour retrouver un élément retiré :

```bash
git show fcb65bc:chemin/du/fichier            # afficher un fichier
git checkout fcb65bc -- reviews/              # restaurer un dossier dans l'arbre de travail
git log --oneline fcb65bc -- audit/           # historique d'un dossier retiré
```

## Ce qui a été retiré et pourquoi

| Élément retiré | Contenu | Raison |
|---|---|---|
| `reviews/` | 711 verdicts de revue (760 fichiers) | Déjà requalifiés « archive non liée au code » (#617) |
| `evidence/`, `registries/`, `Registres/` | Paquets de preuves, registres hash-chaînés | `ledger verify` passait même si le fichier était absent ; registre arrêté au 2026-08-13 |
| `audit/` | Outillage et rapports d'audit (11,8k LOC) | Aucune exécution en CI ; constats repris dans le rapport d'audit v2 |
| `scripts/`, `tools/`, `coordination/`, `.opsys/` | Outillage de méthode (≈ 35k LOC) | Le méta-code pesait 1,6× le code produit ; plusieurs outils étaient orphelins ou non exécutables |
| `stories/`, `surfaces/`, `tests/e2e`, `ops/`, `archive/` | Stories M7, dashboard minimal, harnais e2e du serveur Brand | Remplacés par la nouvelle architecture |
| `VISION.md`, `FORGE_METHOD.md`, `IMPLEMENTATION_SPEC.md`, `RECONCILIATION.md`, `START_HERE.md`, `config.ini.example`, `.cursor/` | Produit-méthode ForgeAI (distinct) | Autre produit, sans lien avec l'exécution d'OPSYS-AI |
| `PACK_CONSENSUS_GRS_v2.md`, `PROMPT_BOOTSTRAP_CLAUDE_CODE.md`, `docs/canon`, `docs/core`, `docs/phase-c`, `docs/incidents`, `docs/superpowers`, `docs/codex` | Canon et méthode PROOF STACK / Core v2.3.0 | Remplacés par `AGENTS.md` v2 et `docs/architecture/` |

Conservés et déplacés : plan maître (`docs/plan/`), politiques Loi 25 et gabarit EFVP
(`docs/compliance/`), ADR-0001 à 0005 (`docs/decisions/`, à titre historique).

## Leçons retenues (audit du 2026-09-28)

1. Le produit s'est arrêté mi-août : l'effort est passé à l'outillage de méthode.
2. Les 10 modules étaient des bibliothèques de règles en mémoire, sans Core, sans persistance
   ni point d'entrée : 0 % « clé en main ».
3. Des contrôles « fail-open » donnaient une fausse assurance.
4. Des bugs réels passaient sous des tests verts construits sur des données synthétiques.

La v2 garde ce qui avait de la valeur — les règles métier des départements et leurs tests —
et reconstruit le reste sur des briques open source matures.
