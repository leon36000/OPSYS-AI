# ForgeAI PROOF IDE System — paquet de fondation v0.2 DRAFT

Ce paquet contient les fichiers maîtres à placer à la racine du dépôt qui servira à développer le système.

## Fichiers

- `VISION.md` — pourquoi le produit existe, son périmètre et ses principes.
- `FORGE_METHOD.md` — méthode complète et autorité de fonctionnement proposée.
- `IMPLEMENTATION_SPEC.md` — architecture, modules, phases, tests et critères de sortie.
- `AGENTS.md` — point d'entrée court pour Claude Code, Codex, Cursor, Copilot et autres agents.
- `config.ini.example` — configuration sûre des modes, rôles, fournisseurs, LiteLLM et contexte.

## Ce que Nathan doit faire

1. Lire et corriger les décisions métier ou les noms qui ne conviennent pas.
2. Valider explicitement le statut canonique de `VISION.md` et `FORGE_METHOD.md`.
3. Choisir les décisions ouvertes listées dans `IMPLEMENTATION_SPEC.md`, surtout le nom, la licence et la stratégie Superpowers.
4. Placer les anciens fichiers PROOF dans `docs/history/` plutôt que de les donner comme instructions actives en parallèle.
5. Ouvrir le dépôt dans l'IDE choisi et envoyer :

> Lis `AGENTS.md`, puis les documents qu'il exige. Commence par la Phase 0 de `IMPLEMENTATION_SPEC.md`. N'écris aucun code avant d'avoir produit l'état des lieux, la matrice de capacités vérifiée et les décisions bloquantes.

## Important

Ce paquet est VALIDÉ par Nathan (23 juillet 2026) et remplace les fichiers PROOF multi-IDE antérieurs (GRS_IDE_CONFIGS_v1..v6), archivés dans `docs/history/`. Il intègre le roster complet réconcilié — GLM-5.2, Kimi K3, Kimi Code 2.7, Gemini Flash 3.6, DeepSeek V4 Pro, Gemini 3.1 Pro, LongCat 2.0, Grok 4.5, MiMo 2.5 Pro, Qwen 3.7 Max, MiniMax M3 —, Headroom, LLMLingua-2, DSPy, GEPA, multi-IDE et mode LiteLLM. Voir RECONCILIATION.md pour la traçabilité complète des corrections.
