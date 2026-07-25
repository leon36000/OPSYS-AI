# M7-S004 — Site « Quadruple A » : générateur statique + garde-fou déterministe

## Manifeste
```
story_id:        M7-S004
risk_tier:       T2
allowed_paths:   [Modules M/M7-marketing/src/site/, Modules M/M7-marketing/tests/]
forbidden_paths: [autres modules, core/, .github/]
depends_on:      [M7-S001]
touches_ledger:  false
```
(Les tests vivent dans `Modules M/M7-marketing/tests/` car c'est le seul chemin découvert par le job
CI protégé `gates` — sans cela la story serait non prouvable, cf. ADR-M7-S004.)

## ÉCART DE PÉRIMÈTRE — À RATIFIER PAR NATHAN (T2)
L'issue #23 nomme **Astro** ; la story livre à la place un **générateur statique Python stdlib +
garde-fou déterministe** (décisions D1–D4 de `reviews/M7-S004/ADR-M7-S004.md`, architecte Kimi-K3) :
- Astro exige Node à la génération ; la CI protégée (Python 3.12 + PyYAML) ne peut pas le prouver et
  `.github/` est un chemin interdit → un artefact Astro serait par construction NON prouvé (invariant
  PROOF n°1).
- ADR-0003 (portabilité) et la décision projet « UI web stdlib auto-suffisante » priment sur la
  mention d'un outil dans une story.
- **Proxy honnête** : le garde-fou impose le sous-ensemble décidable statiquement de WCAG AAA et de
  Lighthouse. AUCUNE affirmation « Lighthouse 100 » sans mesure réelle (Chrome headless = différé T3,
  session infra avec Nathan).

## Critères d'acceptation (testables)
1. `guardrail.validate(html)` applique les 18 invariants G-01…G-18 (structure, méta, landmarks,
   skip-link, ordre des titres, alt, JSON-LD Organization, contraste **≥ 7:1 AAA** calculé selon la
   formule WCAG exacte, aria-label nav, cohérence lang) — chaque invariant a un test positif ET un
   test négatif (36 tests).
2. `generator.render_html(content)` est **pur et déterministe** (double rendu ⇒ SHA-256 identique).
3. `generator.generate()` refuse d'écrire la sortie si UNE violation existe (garde-fou à chaque
   génération) — prouvé par test (`GuardrailViolation` + fichier absent).
4. La sortie régénérée `static/index.html` passe `validate()` = 0 violation, contenu réel OPSYS-AI.
5. `contrast_ratio` vérifié sur références connues (21.0 noir/blanc ; 4.54 #767676/blanc).
6. CI `gates` verte (les 40 tests tournent dans le step « Tests module M7 » existant, sans toucher
   `.github/`).
7. Zéro dépendance Node ; zéro ressource externe chargée par la page ; stdlib + PyYAML seulement.

## Pipeline
Branche `story/M7-S004` · TDD RED capturé (collecte en échec avant impl) → GREEN · gates locaux →
PR → revue scellée 3 vendors ≠ codeurs (codeurs = deepseek/moonshot) → **ratification Nathan T2
(écart Astro)** → merge gaté → registre.
