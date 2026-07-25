# ADR-M7-S004 — Site Quadruple A : générateur statique stdlib + garde-fou déterministe

- **Story** : M7-S004 (risk_tier T2)
- **Statut** : PROPOSÉ — en attente de ratification Nathan (T2) pour deux déviations groupées (§1, §4.4)
- **Dépend de** : M7-S001 ; préserve l'existant M7-S004a (`src/site/static/index.html`)

---

## 1. Décision Astro vs stdlib

**Décision D1 : on substitue au framework « Astro » nommé par le manifeste un générateur de site statique écrit en Python 3.12 stdlib, couplé à un garde-fou de validation déterministe exécuté à chaque génération.**

Justification : l'invariant constitutionnel n°1 (« ce que la CI ne peut pas prouver n'est pas prouvé ») rend Astro indéfendable ici, car la CI protégée (Python 3.12 stdlib + PyYAML, job `gates`) ne peut ni installer ni exécuter Node sans éditer `.github/ci.yml`, chemin explicitement interdit par le manifeste — un artefact Astro serait donc par construction non prouvé, et le confort du framework nommé ne prime jamais sur un invariant.

**Décision D2 : la substitution est traitée comme une déviation de périmètre formelle, non comme un choix d'implémentation libre.** Justification : le manifeste nomme explicitement « Astro » dans l'acceptance, donc remplacer le moyen tout en préservant l'intention (site statique accessible, WCAG AAA, schema.org, garde-fou à chaque génération) exige la ratification T2 de Nathan déjà requise avant merge — on implémente, on documente l'écart dans la PR, on fait approuver ; on ne décide pas seul.

**Décision D3 : le critère d'acceptation est réinterprété « site statique accessible » (moyen substituable) et non « site Astro » (moyen imposé).** Justification : les quatre autres critères (Lighthouse/WCAG, schema.org, garde-fou) sont indépendants du framework, et ADR-0003 (portabilité, « UI web stdlib auto-suffisante », zéro dépendance lourde non portable) est une décision projet actée qui prime sur la mention d'un outil dans une story.

**Décision D4 : aucune édition de `.github/` n'est effectuée ni demandée dans cette story.** Justification : `.github/` est `forbidden_paths` ; toute évolution CI (Node, Chrome headless) relève d'un changement de manifeste séparé, en T3.

---

## 2. Périmètre prouvable MAINTENANT vs périmètre différé T3

### 2.1 Prouvable maintenant (CI Python existante, zéro Node, zéro édition `.github/`)

- Génération statique déterministe du site (contenu YAML → HTML) et **byte-determinisme** prouvé en CI (double build, comparaison SHA-256).
- Le **sous-ensemble décidable de WCAG 2.x AAA** : ratios de contraste calculés exactement selon la formule WCAG (luminance relative sRGB), structure du document, landmarks, ordre des titres, langue, skip-link, alternatives textuelles, viewport, absence de handlers inline.
- Le **sous-ensemble statique de Lighthouse** (catégories Accessibility/SEO/Best Practices) : title, meta description, canonical, theme-color, charset, JSON-LD valide, dimensions d'images, absence de ressources externes bloquantes (le site n'en charge aucune), budget d'octets.
- La validité schema.org du JSON-LD (parsing JSON strict + champs requis + cohérence croisée avec le contenu visible).
- La politique « garde-fou à chaque génération » : la validation est une étape interne et bloquante du build (§4.2), pas un script optionnel — la CI exécute le build, donc la CI exécute le garde-fou.

### 2.2 Différé T3-Nathan (exige Node, Chrome, ou édition CI)

- **Lighthouse 100 « réel »** : exige Chrome headless piloté par Node → non prouvable dans la CI actuelle, sans exception.
- Audits runtime JS (axe-core, pa11y) : moteur JS requis.
- Métriques de performance mesurées en navigateur réel (LCP, CLS, TBT).
- Le build Astro lui-même, si Nathan refuse la déviation D1.

### 2.3 Proxy honnête

Le proxy Python est fidèle **uniquement sur ce qui est décidable statiquement** ; le contrat de communication est : « sous-ensemble déterministe de WCAG AAA et de Lighthouse vérifié à chaque génération ; mesure Lighthouse réelle planifiée T3 ». Toute mention « Lighthouse 100 » ou « conforme AAA » non qualifiée dans un livrable, un README ou une PR est interdite (voir R-001). Les critères AAA non automatisables (clarté du langage, cohérence de navigation, aide à la saisie) relèvent d'une checklist humaine consignée en revue, et le garde-fou ne prétend jamais les couvrir.

---

## 3. Invariants testables du garde-fou déterministe

Chaque règle porte un identifiant stable (G-xx) référencé dans les violations, les tests et la PR. Toute violation = build échoué, sortie non publiée.

### 3.1 Structure du document
- **G-01** : un seul `<html>` avec `lang` BCP 47 non vide (`fr`).
- **G-02** : un seul `<title>` non vide, longueur bornée [10, 70] caractères.
- **G-03** : `<meta charset="utf-8">` présent, premier enfant de `<head>`.
- **G-04** : `<meta name="viewport">` présent, sans `user-scalable=no` et sans `maximum-scale < 2` (WCAG 1.4.4/1.4.10).
- **G-05** : `<meta name="description">` non vide, longueur bornée [50, 300].
- **G-06** : `<link rel="canonical">` présent, URL absolue `https://`.
- **G-07** : `<meta name="theme-color">` présent, couleur hexadécimale valide.
- **G-08** : `<link rel="icon">` déclaré et l'asset référencé existe dans l'
