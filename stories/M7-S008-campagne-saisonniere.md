# M7-S008 — Workflow campagne saisonnière (planification déterministe)

T2 · allowed: src/workflows/, tests/ · deps S006+S008a · touches_ledger: false · zéro réseau/horloge.
Date de référence FOURNIE → fenêtres actives de fenetres_marketing (règle OR au chevauchement
d'année, fw-creux-hivernal 12→1 testé) → un content-item PROPOSÉ par thème via S006 (le CONTENT-ITEM
entre en file 0-6, propose-only prouvé par espions approve/publish=0 appel) → plan trié
reproductible (déterminisme testé) + compteurs dérivés. Sujet 100 % factuel du calendrier (aucun
thème inventé), calendrier GELÉ sha256 129160d4… (D-015, test consommateur). 9 tests. Architecte
Qwen3.7-Max (prose, 1re passe). Défaut réel corrigé : le wrapper était proposé au lieu du
content-item porteur de l'id.
