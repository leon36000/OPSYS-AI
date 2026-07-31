# Trio — cadrage M3 (2026-07-30)
Rédaction : Qwen3.7-Max (alibaba), trois dispatches enchaînés. Gate : crew-coder-bulk (deepseek).

ROTATION MESURÉE, pas devinée. Deux runs partiels 2/3 PURGÉS (le sceau exige le trio complet en UNE invocation). Diagnostic sur le pack RÉEL (84 k caractères, ~27 k tokens) :
  Tencent-Hy3 : finish=length, contenu VIDE — le raisonnement consomme les 16000 tokens de sortie avant d'émettre.
  Kimi-K2.6   : idem, finish=length, contenu VIDE.
  MiniMax-M3  : contenu 2062 car, reasoning 0 — échec initial transitoire.
  Kimi-2.7    : contenu 1076 car, reasoning 2981 — dans le budget.
  Grok-4.5    : contenu 1756 car, reasoning 4244. Nemotron-3-Ultra : 1882 car.

Trio retenu : Grok-4.5 (xai), Nemotron-3-Ultra (nvidia), Kimi-2.7 (moonshot) — vendors distincts entre eux et des deux rédacteurs (alibaba, deepseek).

DÉCOUPAGE EN DEUX PACKS : civ_review lance les 3 relecteurs EN PARALLÈLE (ThreadPoolExecutor). Mes sondes SÉQUENTIELLES sur le pack de 84 k réussissaient toutes les quatre, mais sous charge concurrente un relecteur sur trois rendait un contenu vide — trois runs partiels 2/3 purgés. Deux périmètres cohérents, deux trios scellés COMPLETS, plutôt qu'un pack unique qui fait tomber la revue.
