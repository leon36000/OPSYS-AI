# docs/history/ — Fichiers PROOF antérieurs, archivés

Conformément à l'instruction #4 du `README.md` de ce paquet : « Placer les anciens fichiers PROOF
dans `docs/history/` plutôt que de les donner comme instructions actives en parallèle. »

## Ce qui est archivé ici

Le système multi-IDE construit avant ce paquet (GRS_IDE_CONFIGS_v1 à v6) :
`CLAUDE.md`, `.cursor/rules/00-role.mdc`, `.github/copilot-instructions.md`,
`docs/codex/CODEX-BRIEF.md`, `AGENTS.md` (première version) — 6 itérations produites entre le
23 juillet 2026 (matin) et cette version.

Ces fichiers ne sont **plus des instructions actives**. Ils sont remplacés par le paquet
ForgeAI PROOF IDE System v0.2 (validé) déposé à la racine du dépôt.

## Pourquoi l'archivage plutôt que la suppression

Traçabilité (REG-01, preuve avant déclaration) : le raisonnement qui a mené au roster actuel, à la
règle d'accès tracé, et à l'architecture multi-outils est documenté dans les conversations sources
et dans `RECONCILIATION.md` à la racine. Rien n'est perdu, seulement désactivé.

## Correspondance ancien → nouveau

| Ancien fichier (GRS_IDE_CONFIGS) | Remplacé par |
|---|---|
| `CLAUDE.md` (table de dispatch improvisée) | `CLAUDE.md` (racine, adaptateur mince) + `FORGE_METHOD.md` §8 |
| `.cursor/rules/00-role.mdc` | `.cursor/rules/00-forge.mdc` (racine) |
| `.github/copilot-instructions.md` (VS Code) | `.github/copilot-instructions.md` (racine, GitHub natif) |
| `docs/codex/CODEX-BRIEF.md` | `docs/codex/CODEX-BRIEF.md` (racine, réécrit) |
| `AGENTS.md` (v1, générique) | `AGENTS.md` (racine, ForgeAI PROOF IDE System) |

Le plan maître GRS (section 16bis, `GRS_Plan_Squelette_Maitre_v1.2.pdf`) reste la source de vérité
pour le PRODUIT (les 10 modules M1-M10) ; ce paquet ForgeAI PROOF IDE System devient la source de
vérité pour la MÉTHODE d'exécution qui gouverne leur développement — deux produits distincts
(VISION.md §1), le second gouverne la construction du premier.
