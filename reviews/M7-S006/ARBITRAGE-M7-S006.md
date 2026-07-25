# ARBITRAGE SUR PIÈCES — M7-S006 (D-041, rounds Delphi épuisés)

**Décision : APPROVED** (Orchestrateur, sur pièces, 2026-07-25 ~14h30 HE)

## Fondement
- 3 rounds scellés (trio Gemini-3.1-Pro / MiniMax-M3 / Qwen3.7-Max, vendors ≠ codeur DeepSeek,
  ≠ architecte xiaomi). R1 1/3 → R2 2/3 → R3 2/3 : APPROVE CONSTANT de Gemini et Qwen aux rounds
  2-3 ; unique rejeteur MiniMax.
- TOUTES les objections fondées ont été corrigées et prouvées (12 correctifs cumulés) :
  A2-style transitions horodatées (propose_timestamp/approval_timestamp), auto-rejet interdit,
  garde gabarits par liste blanche, types tactics stricts, lecture unique anti-TOCTOU des 3
  fichiers, **validation du brand par le SCHÉMA du contrat gelé** (le check r2 se sautait en
  silence — exposé par fail-closed r3, remplacé par _valider_brand_contre_contrat sur
  profile_schema.required_fields), UUID canonique seul, KeyError non maquillé, code mort retiré,
  asserts d'égalité exacte, commentaire parasite de splice purgé.
- Objection centrale restante de MiniMax (« tests TDAD non livrés dans leur fichier cible ») :
  **RÉFUTÉE PAR PREUVE DÉTERMINISTE** — grep sur l'arbre committé : les 5 fonctions sont top-level
  dans leurs fichiers cibles (test_approval.py:123/150, test_factory.py:108 + remplacement gabarit,
  test_validation.py:140) ; pytest les COLLECTE et les EXÉCUTE (57 verts). Le reviewer lisait le
  rendu du diff d'un round antérieur (marqueurs de routage du patch), pas l'état final.
- Objections restantes non retenues (motifs au pack r3) : double ancrage sha = pattern D-015 ratifié
  (brand v1, PR #34) ; déterminisme/listes = l'ordre fait partie de l'entrée ; sémantique
  approval_timestamp = contrat gelé §1 (l'instant de proposition est tracé par propose_timestamp
  depuis r3) ; imports plats = pattern M7 établi (site/, brand/) ; variantes fromisoformat = contrat
  documenté (ISO-8601 avec timezone exigée, testée).
- Précédents appliqués : ARBITRAGE-S002-R2, ARBITRAGE-P0-5b, ARBITRAGE-P0-5c (2/3 constant +
  critiques résolues-ou-réfutées + mineures corrigées après rounds épuisés = APPROVED).

## Preuves d'exécution (état final bdb8d8e + correctif schéma)
57 tests contenu verts ; suites M7 + globale vertes ; structure_lint VERT ; no-stub rc=0 ;
modules purs (grep déterministe). Merge conditionné : gates=success sur le SHA de tête dès
rétablissement de la facturation Actions (BLOCKED-T3 Nathan, annotation journalisée aux PRs #56/#57).
