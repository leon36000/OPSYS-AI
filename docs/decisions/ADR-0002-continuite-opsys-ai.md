# ADR-0002 — Continuité OPSYS-AI (renommage GRS)

Statut: Accepted (immuable — changer = nouvel ADR qui supersede)
Date: 2026-07-23

Décision :
1. Le projet GRS est renommé OPSYS-AI (repo github.com/leon36000/OPSYS-AI) — continuité totale.
   `ledger/`, ADR-0001 et les noms de fichiers historiques restent immuables ; « GRS » reste le nom de code d'origine.
2. Répartition des registres : `registries/ledger/*.jsonl` = registre PROJET OPSYS-AI hash-chaîné, vérifié en CI (D-042) ;
   `Registres/*.jsonl` = registre MÉTHODE proof-method.
3. Répartition des dépouillements : `civ_review.py` + `tally_reviews.py` (proof-method, sceau `prompt_sha256`) = autorité pour les REVUES DE CODE ;
   `scripts/tally.py` du kit = autorité pour la PHASE C (consensus). Aucun LLM n'écrit un score dans les deux cas.
4. Profil d'installation D-043 = infra-existante : passerelle LiteLLM, Langfuse et infra Serveur déjà présentes sur l'hôte.
5. Sentinelle = DeepSeek-V4-Pro + Qwen3.7-Max (ADR-0003 proof-method). Divergence journalisée vs D-040 « DeepSeek+GLM » : GLM écarté par données.
6. Les fichiers ForgeAI PROOF IDE System v0.2 présents à la racine (poussés par Nathan, commit 48d66ba) = référentiel d'un produit-méthode DISTINCT qui aura son propre dépôt.
   Le kit PROOF STACK v1.1 gouverne seul l'exécution d'OPSYS-AI.
7. Expurgation de la valeur de clé dans `config.ini.example` : la clé ayant figuré dans l'historique GitHub, la rotation R-002 (P0-4, T3 Nathan) est impérative.

