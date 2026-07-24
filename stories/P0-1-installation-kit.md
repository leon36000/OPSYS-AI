# Story P0-1 — Installation du kit v1.0 + adaptation OPSYS-AI

Tier: T2
Estimation humain-équivalent (D-044) : ~1 h (cap dur 3 h)
Branche : story/P0-1-installation-kit
Codeur assigné : crew Kimi-2.7 (`crew_dispatch.py --difficulty facile`) — vendor moonshot ∉ trio CIV
Reviewers : trio scellé DeepSeek-V4-Pro · Gemini-3.1-Pro · LongCat-2.0 (3 vendors, tally par script)

## Contexte
Le kit GRS_KIT_DEMARRAGE_v1.0 (squelette 10 modules + méthode PROOF STACK v1.1, ratifiée D-039)
s'installe dans le repo OPSYS-AI (ex-GRS, renommé — décision Nathan 2026-07-23). Le repo contient
déjà, poussés par Nathan (commit 48d66ba), les fichiers du paquet « ForgeAI PROOF IDE System v0.2 »
(produit distinct — référence méthode, chantier séparé) : rien de ces fichiers n'est supprimé.
Décisions Nathan : renommage docs GRS→OPSYS-AI + ADR-0002 ; le kit PROOF STACK v1.1 gouverne seul
l'exécution du repo.

## Portée
1. Copie du kit à la racine (faite mécaniquement, sans scories `.pytest_cache`/`__pycache__`).
2. Ajout des deux sources de vérité : `docs/GRS_Plan_Squelette_Maitre_v1.1_PERFECTION.pdf` (28 p.)
   et `PACK_CONSENSUS_GRS_v2.md` (racine). Noms de fichiers historiques conservés.
3. Adaptations (codeur crew) : README fusionné, CLAUDE.md/AGENTS.md fusionnés (template
   proof-method + pointeurs kit + précédence sur le paquet PROOF-IDE), CODEOWNERS `@leon36000`,
   `.gitignore`, `pytest.ini` (isolation du repo imbriqué), CI durcie (step d'installation pytest),
   renommage GRS→OPSYS-AI dans les docs modifiables, `docs/index.md` complété,
   `docs/decisions/ADR-0002-continuite-opsys-ai.md`.
4. Expurgation de sécurité : la valeur de clé présente dans `config.ini.example` (fichier poussé
   par Nathan) est retirée du tip de main — la clé reste dans l'historique GitHub, d'où rotation
   R-002 (T3, P0-4).

## Interdits spécifiques
- NE JAMAIS modifier `registries/ledger/*.jsonl` (chaîne de hash — byte-identique au kit exigé).
- NE JAMAIS modifier `docs/decisions/ADR-0001-adoption-squelette.md` (ADR immuable).
- NE JAMAIS renommer le PDF ni le PACK (pièces historiques).
- Nom du job CI `gates` et actions épinglées par SHA inchangés (contexte de protection de branche).

## Critères d'acceptation (testables)
1. `python3 scripts/structure_lint.py` → VERT.
2. `python3 scripts/ledger_append.py verify` → toutes chaînes OK.
3. `python3 -m pytest scripts/tests -q` → 3 passed (sans pollution de config parent).
4. `diff` byte-exact des deux jsonl du ledger vs kit → aucune différence.
5. `git status --ignored` : `.pytest_cache`, `__pycache__`, `.coverage`, `.claude/worktrees/`
   uniquement en ignoré — jamais en staged.
6. Aucun MATÉRIAU de clé réelle dans l'arbre de la branche : `git grep -E "sk-forge-[0-9a-f]{16}"`
   vide. (Précision issue de la revue scellée round 1 : le préfixe `sk-forge-` cité comme motif dans
   le présent critère n'est pas un secret ; seul le préfixe suivi d'hexadécimal constitue une clé.)
7. Grep « GRS » dans les docs modifiables : uniquement les mentions historiques légitimes
   (nom de code, noms de fichiers des pièces, ADR-0001, ledger).
8. CI GitHub verte sur la PR (job `gates`).
9. Revue scellée trio → tally APPROVED (3 vendors, sceaux identiques).

## Impact doc
README, CLAUDE.md, AGENTS.md, docs/index.md, ADR-0002 — déclaré dans la PR.

Sortie attendue : PREUVE: (gates + tally + merge) ou BLOCKED: avec raison.
