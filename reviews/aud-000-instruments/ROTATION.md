# ROTATION — trio d'audit AUDIT-000

## Pourquoi un trio différent de celui des modules

Gemini-3.1-Pro (163 verdicts), Qwen3.7-Max (145) et DeepSeek-V4-Pro (112) ont approuvé la
quasi-totalité des 168 pull requests de la vague 1. Les reconduire pour auditer ce même
travail reviendrait à leur faire réviser leurs propres approbations. S'y ajoute un écart de
sévérité mesuré : DeepSeek ne rejette que 5,4 % des packs, contre 19 à 47 % pour les autres
membres du roster.

Le trio d'audit est donc choisi parmi les modèles à **faible exposition** aux 168 PR.

## Trio candidat, sondé sur un pack réel

Le sondage n'a pas été une requête de test : le trio a revu pour de bon les deux instruments
du cadrage (`verif_coherence.py`, `mutation_gate.py`, pack de 26 451 caractères). Une route
qui répond à un ping mais échoue sur un pack de taille réelle serait déclarée bonne à tort.

| Modèle | Vendor | Résultat du sondage |
|---|---|---|
| MiniMax-M3 | minimax | **REJECT**, 7 objections dont 2 critiques — route saine |
| Kimi-K3 | moonshot | **REJECT**, 7 objections dont 2 majeures — route saine |
| Grok-4.5 | xai | **ÉCHEC** — 3 essais épuisés, HTTP 408 Request Timeout |

## SWAP journalisé — Grok-4.5 remplacé

Grok-4.5 n'a pas répondu en trois essais. Le remplaçant doit satisfaire trois conditions
simultanées : vendor distinct de minimax et moonshot (décorrélation, REG-05) ; vendor absent
du trio ayant approuvé les 168 PR (google, alibaba, deepseek) ; route mesurée opérationnelle
sur un pack de taille réelle.

- **Composer-2.5** est écarté : même vendor que Grok (xai), et R-001 interdit d'apparier
  Composer et Grok — le remplacer par lui ne change donc rien à la couverture des vendors,
  en plus d'avoir également échoué en 408 lors du consensus élargi.
- **GLM-5.2** est écarté par décision permanente : le modèle fuit son raisonnement dans ses
  sorties, ce qui casse le scellage.
- **LongCat-2.0** a échoué en HTTP 429 lors du consensus élargi.
- **MiMo-Pro-V2** (xiaomi) a répondu avec un verdict valide au consensus élargi sur un pack
  de 46 386 caractères — plus gros que celui de la revue. C'est le remplaçant.

**Trio d'audit retenu : MiniMax-M3 (minimax) · Kimi-K3 (moonshot) · MiMo-Pro-V2 (xiaomi).**
Trois vendors distincts, aucun n'ayant approuvé les 168 PR de la vague 1, aucun n'étant
anthropic (vendor de l'Orchestrateur qui écrit les instruments).

## Le sceau du premier tour ne se recycle pas

Les deux verdicts obtenus (`Kimi-K3.verdict.json`, `MiniMax-M3.verdict.json`, sceau
`6104afec81c0bce8…`) portent sur la version des instruments qui a été rejetée. Ils sont
conservés comme pièces, mais **le tour suivant sera relancé en entier** sur les trois
modèles : compléter un trio en n'appelant que le membre manquant produirait un dossier où
deux verdicts jugent un code et le troisième un autre, et le sceau ne le dirait pas.

## Recomposition du trio — sondage en charge, 2026-08-05

Deux échecs consécutifs (Grok-4.5 en 408 au sondage, Kimi-K3 en 500 sur la revue des corrections)
ont motivé un sondage de toutes les routes de revue disponibles, sous une charge réaliste
(~8 000 caractères de contexte, sortie JSON exigée) plutôt qu'un ping trivial.

| Modèle | Vendor | Résultat | Latence |
|---|---|---|---|
| MiniMax-M3 | minimax | OK | 3 s |
| Grok-4.5 | xai | OK | 3 s |
| Composer-2.5 | xai | OK | 4 s |
| MiMo-V2.5-Pro | xiaomi | OK | 6 s |
| MiMo-Pro-V2 | xiaomi | OK | 9 s |
| Tencent-Hy3 | tencent | OK | 18 s |
| Kimi-K2.6 | moonshot | OK | 22 s |
| Kimi-K3 | moonshot | OK | 25 s |
| MiniMax-M2.7 | minimax | OK | 42 s |
| LongCat-2.0 | meituan | ÉCHEC — HTTP 429 | 24 s |
| Nemotron-3-Ultra | nvidia | ÉCHEC — HTTP 403 | 17 s |

**Ce que le sondage établit, et qui change le diagnostic** : Grok-4.5 et Kimi-K3 répondent tous
deux en quelques secondes sous charge légère. Leurs échecs précédents portaient sur des packs de
47 000 et 57 000 caractères. La cause n'est donc pas la route mais la **taille du pack** — les
« routes instables » étaient un diagnostic faux, et le remède (les remplacer) aurait déplacé le
problème sans le résoudre.

Conséquence opérationnelle : le plafond de pack passe de 50 000 à **30 000 caractères** pour les
revues de lot. Le chiffre de 50 000 venait d'une mesure réelle (un pack de 84 000 avait produit une
sortie vide chez un relecteur sur trois) mais il était encore trop haut pour deux vendors sur cinq.

**Trio d'audit retenu** : MiniMax-M3 (minimax) · MiMo-Pro-V2 (xiaomi) · Tencent-Hy3 (tencent).
Trois vendors distincts, aucun n'ayant approuvé les 168 PR de la vague 1, aucun n'étant anthropic,
tous mesurés opérationnels ce jour. Suppléants, dans l'ordre : Kimi-K3 (moonshot), Grok-4.5 (xai).
