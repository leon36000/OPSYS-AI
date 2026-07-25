# ADR M7-S010 — Audit concurrentiel SEO — Seconde passe

> Architecte : MiMo-Pro-V2, SECONDE passe. INCIDENT DE RÔLE journalisé : passe 1 = 772 lignes de CODE (violation « l'architecte ne code jamais ») → REJETÉE non lue par les codeurs ; passe 2 = prose seule sous contrainte explicite. Kimi-K3 : sortie vide (3e échec architecte consécutif, R-038). MiMo exclu de la revue S010.

## 1. Schéma des fixtures
L'arborescence `fixtures/concurrents/<slug>/` contiendra quatre fichiers par concurrent : `meta.yaml` (métadonnées), `index.html` (page principale), `robots.txt` (fichier d'exclusion), et `sitemap.xml` (plan du site). Trois slugs retenus : `fort` (concurrent bien référencé avec balisage complet et maillage riche), `faible` (lacunes visibles sur title, meta description, schema.org et maillage), et `casse` (données mal formées : HTML invalide, schema.org avec erreurs, directives robots.txt contradictoires). Chaque fixture doit exhiber un comportement distinctif attestable par l'analyse. Le fichier `meta.yaml` exige les champs : `name` (nom du concurrent, non vide), `url` (URL de la page analysée, non vide), `type` (classification parmi `direct`, `indirect`, `inspirational`), `fictif` (booléen obligatoire à `true` pour garantir l'absence de données réelles), et `description` (résumé optionnel).

## 2. Règles C-xx du rapport
Les règles d'évaluation sont identifiées par des codes stables C-01 à C-08. C-01 : présence d'une balise `<title>` non vide de 60 caractères maximum (conforme/non_conforme). C-02 : présence d'une balise `<meta name="description">` non vide de 160 caractères maximum (conforme/non_conforme). C-03 : présence d'un unique `<h1>` non vide (conforme/non_conforme). C-04 : balisage schema.org détecté (conforme/non_conforme/candidat_a_verifier si présence douteuse). C-05 : maillage interne d'au moins trois liens uniques pointant vers le même domaine (conforme/non_conforme). C-06 : fichier `robots.txt` n'interdisant pas l'accès aux bots IA connus (conforme/non_conforme/KO si absent). C-07 : présence d'un fichier `sitemap.xml` bien formé (conforme/non_conforme/KO si absent). C-08 : couverture thématique suffisante (ratio ≥ 0.5), calculée par tokenisation du contenu textuel (title, meta description, h1, premiers 500 caractères du corps), suppression des stop words français, puis intersection normalisée avec le corpus de notre site (conforme/non_conforme/candidat_a_verifier si calcul impossible).

## 3. Interfaces
Pour chaque fonction publique dans `src/competitive/` : `load_fixture(slug) -> dict` — charge les données d'un concurrent depuis le disque ; `analyze_page(html, url) -> dict` — applique les règles C-01 à C-05 à une page HTML ; `analyze_robots(robots_txt) -> dict` — applique C-06 ; `analyze_sitemap(sitemap_xml) -> dict` — applique C-07 ; `calculate_coverage(html_concurrent, html_nous, stopwords_path) -> float` — applique C-08 ; `generate_report(slugs, notre_site) -> dict` — orchestre l'analyse complète et consolide les résultats. Le module `loader` contient `load_fixture`, appelé par `generate_report` ; `analyzers` contient `analyze_page`, `analyze_robots`, `analyze_sitemap`, appelés par `generate_report` ; `compare` contient `calculate_coverage`, appelé par `generate_report` ; `report` contient `generate_report`. Réutilisation de `seo_audit` (S003) : les fonctions `_audit_page` et `_audit_robots` seront invoquées en lecture seule pour extraire les métriques de base (title, meta, h1, liens, directives robots), car leurs signatures retournent déjà des dictionnaires exploitables sans modification.

## 4. Anti-dérive
Chaque fixture doit porter `fictif: true` sous peine de rejet immédiat par le validateur de chargement. L'interdiction réseau est garantie par un test intégré vérifiant l'absence totale de requêtes HTTP sortantes (via monkey-patch ou mock). Toute erreur de parsing (HTML, YAML, XML) produit un verdict `KO` sans absorption silencieuse. Le déterminisme est assuré par un tri stable des résultats (ordre alphabétique des slugs) et par la transmission externe du timestamp d'appel, jamais généré en interne. Aucun score agrégé n'est produit (conformément à REJ-0040), seuls des verdicts par règle et par concurrent sont émis.

## 5. Stratégie de tests RED/GREEN
Pour chaque règle, des tests positifs (données conformes) et négatifs (données non conformes) seront écrits. Tests spécifiques : refus d'une fixture sans `fictif: true`, vérification du zéro-réseau via instrumentation, test de déterminisme (deux appels identiques donnent le même rapport hors timestamp), et test de robustesse face aux erreurs de parsing. Les tests résideront dans le chemin CI existant `tests/competitive/`, exécutés par le job `gates`.

---
> **NOTE D'ÉCART D'IMPLÉMENTATION (R1, journalisée)** : le §3 prévoyait d'invoquer les fonctions
> privées `_audit_page`/`_audit_robots` de seo_audit ; l'implémentation retient une réimplémentation
> locale testée (25 tests dédiés). Motif : un nom préfixé `_` n'est pas une interface stable — le
> couplage inter-modules à des privés créerait une fragilité que S003 n'a jamais promis de tenir.
> L'esprit du §3 (mêmes faits mesurés, pas de duplication non testée) est conservé. Source de
> l'écart : spec d'implémentation de l'orchestrateur (« l'ADR permet l'un ou l'autre ») — attribution
> transparente ; le trio scellé arbitre au round 2. De même, `calculate_coverage` prend des TEXTES
> BRUTS (l'appelant extrait) — la cible d'extraction ADR (title+meta+h1+500 premiers caractères) est
> appliquée par `report.py` (correctif R1).
