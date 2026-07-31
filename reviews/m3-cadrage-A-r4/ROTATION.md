# Round 4 — cadrage M3 pack A (2026-07-30)
Round 3 : APPROVE 2/3, REJECT de Grok-4.5 sur 4 objections (2 majeures), toutes des corrections INCOMPLÈTES de ma part.

ROTATION MESURÉE : deux runs partiels 2/3 purgés (le sceau exige le trio complet en UNE invocation). Cause établie par sondage : civ_review lance les trois relecteurs EN PARALLÈLE ; sur un pack de 93 k caractères (~27 k tokens), les relecteurs à raisonnement lourd épuisent leurs 16000 tokens de sortie en raisonnement et rendent un contenu VIDE (finish=length). Mesures : Kimi-2.7 reasoning=2981, Grok-4.5 reasoning=4244, Tencent-Hy3 et Kimi-K2.6 finish=length contenu vide, MiniMax-M3 reasoning=0.
Kimi-2.7 remplacé par MiniMax-M3 (minimax) : sans raisonnement facturé, il ne peut pas épuiser son budget de sortie sur un pack de cette taille.
Trio : Grok-4.5 (xai), Nemotron-3-Ultra (nvidia), MiniMax-M3 (minimax) — vendors distincts entre eux et des rédacteurs (alibaba, deepseek).
