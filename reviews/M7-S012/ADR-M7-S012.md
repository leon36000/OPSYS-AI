# M7-S012 — Convention UTM gelée, générateur et validateur déterministes

> Architecte : Qwen3.7-Max (prose, 1re passe — 4e ADR conforme d'affilée). ADAPTATIONS d'exécution : tests consolidés en 3 fichiers (test_utm_contrat_regles.py, test_utm_generateur.py, test_utm_integration.py) au lieu de 12+ ; zéro-réseau par getsource (pattern S010/S011, pas de mock socket) ; déterminisme par double appel (pattern établi) ; trio de revue Gemini/MiniMax/MiMo-ou-swap (architecte alibaba exclu).

## 1. Périmètre et autorité

Le module vit dans `src/utm/` et expose trois fonctions publiques pures : `generer_lien_utm`, `valider_lien_utm`, `construire_campaign`. Aucune horloge, aucun réseau, aucun LLM, aucune lecture disque hors contrat YAML gelé. Le contrat `contracts/utm-convention.v1.yaml` est épinglé par sha256 dans un test consommateur (pattern D-015) : toute modification du contrat casse le build avant déploiement. Le module est en dépendance aval de M7-S006 (content-items) et M7-S008 (plan de campagne) en lecture seule de leurs sorties : il ne modifie jamais ces modules, il consomme leurs structures déjà produites.

## 2. Enums normalisés — justification canal par canal

`utm_source` (FR minuscules, sans accents) : `google` (SEO/AIO D-013), `facebook` (S005 Postiz), `instagram` (S005 Postiz), `infolettre` (courriel marque), `gbp` (Google Business Profile, fiche S006), `site` (trafic direct S004), `linkedin` (canal B2B extension), `perplexity` (surface D-013), `tiktok` (extension sociale). Chaque valeur correspond à un canal réellement instrumenté dans le produit ou à une surface D-013 documentée. `utm_medium` : `organique` (SEO naturel), `cpc` (Google Ads, PPC pillar S006), `social` (posts S005/S007), `courriel` (infolettres), `referral` (partenaires/presse), `display` (bannières). Les valeurs sont disjointes par nature de diffusion, pas par plateforme, pour éviter la redondance avec `utm_source`.

## 3. Format `utm_campaign` et règles de slug

Format figé : `<origine>-<slug>-<annee>` où `origine ∈ {fenetre, workflow, contenu}`. `fenetre` pour les entrées S008 (ex. `fenetre-hiver-2025`), `workflow` pour les productions S007 chantier (ex. `workflow-villa-nice-2024`), `contenu` pour les items S006 isolés (ex. `contenu-seo-plomberie-2025`). Le slug est produit par translittération déterministe : NFD + suppression des diacritiques + minuscules + remplacement de tout caractère hors `[a-z0-9-]` par un tiret + fusion des tirets consécutifs + strip des tirets terminaux. L'année est sur 4 chiffres, validée dans `[2020, 2099]`. Longueur totale de `utm_campaign` bornée à 100 caractères pour respecter les limites des outils d'analytics.

## 4. Interfaces publiques — signatures et ordre des paramètres

`generer_lien_utm(url_base: str, source: str, medium: str, campaign: str, content: str | None = None) -> str`. L'ordre est fixé par fréquence d'usage décroissante et par obligation RFC : source/medium/campaign sont toujours requis, content est optionnel (A/B test, variante créative). L'URL de base est en première position car elle est le sujet de la transformation. Politique de préservation des query params existants de `url_base` : ils sont conservés intégralement et les paramètres UTM sont ajoutés en fin de query string dans l'ordre canonique `utm_source, utm_medium, utm_campaign, utm_content`. Si un paramètre UTM préexiste dans `url_base`, il est écrasé (dernier écrit gagne) pour garantir la déterminisme — aucune fusion, aucun merge ambigu. Encodage `%` via `urllib.parse.quote` avec `safe=""` sur les valeurs uniquement, jamais sur les clés.

`valider_lien_utm(url: str) -> list[tuple[str, str, str]]` retourne une liste de triplets `(code, verdict, detail)` où `verdict ∈ {ok, warn, fail}`. Fail-closed : dès qu'un `fail` est émis, le lien est considéré invalide par tout consommateur. La fonction est pure et lève uniquement sur entrée non-string.

`construire_campaign(origine: str, slug_brut: str, annee: int) -> str` applique la translittération et assemble. `normaliser_slug(slug_brut: str) -> str` est exposée en helper public pour testabilité unitaire.

## 5. Règles U-xx du validateur

Chaque règle a un id stable, une ligne de fait mesuré, un verdict déterministe. `U-01` : `url_base` doit être `https` (fail sinon — le HTTP nu est exclu pour sécurité et cohérence analytics). `U-02` : `utm_source` présent et dans l'enum (fail). `U-03` : `utm_medium` présent et dans l'enum (fail). `U-04` : `utm_campaign` présent et matche `^(fenetre|workflow|contenu)-[a-z0-9-]+-\d{4}$` (fail). `U-05` : longueur `utm_campaign` ≤ 100 (fail). `U-06` : encodage `%` correct — re-encoder et comparer byte à byte (fail si divergence). `U-07` : aucun caractère interdit dans les valeurs (hors `[a-z0-9\-_%]` après décodage) (fail). `U-08` : ordre canonique des paramètres UTM dans la query string (warn — non bloquant mais signalé). `U-09` : `utm_content` optionnel, si présent longueur ≤ 80 et même alphabet que slug (fail sinon). `U-10` : pas de duplication de clé UTM (fail). `U-11` : année dans `[2020, 2099]` (fail). `U-12` : slug non vide après normalisation (fail).

## 6. Intégration S006 — table de correspondance surface → source/medium

Une table déclarative dans `src/utm/mapping.py` (pas dans le contrat, pour permettre extension sans casser le sha256) mappe `surface × pillar × type` S006 vers `(source, medium)`. Exemples gelés : `google_aio × seo × page_seo → (google, organique)` ; `perplexity × seo × article_blog → (perplexity, organique)` ; `assistants_ia × social × post_social → (site, referral)` ; `google_aio × ppc × fiche_gbp → (gbp, cpc)`. La fonction `utm_pour_content_item(item: dict) -> str` lit `item["surface"]`, `item["pillar"]`, `item["type"]`, `item["id"]` et `item["title"]` (sans modifier l'item), construit `campaign = construire_campaign("contenu", normaliser_slug(item["title"]), annee_courante_du_item)` et appelle `generer_lien_utm`. L'année est extraite du `timestamp` de proposition S008 si disponible, sinon rejet explicite — jamais d'horloge système.

## 7. Intégration S008 — fenetre_id vers campaign

Pour chaque entrée du plan S008, `utm_pour_fenetre(fenetre: dict, timestamp: str) -> str` lit `fenetre["fenetre_id"]` et `fenetre["theme_source"]`, construit `campaign = construire_campaign("fenetre", normaliser_slug(fenetre_id), annee_extraite_de_timestamp)`. Le `source` et `medium` sont passés par l'appelant (le workflow S008 connaît le canal de diffusion cible de la fenêtre) — le module UTM ne devine jamais.

## 8. Anti-dérive et stratégie RED/GREEN

Gel sha256 du contrat dans `tests/test_utm_contrat.py` : le test lit `contracts/utm-convention.v1.yaml`, calcule son sha256, le compare à la constante attendue — toute édition du contrat exige une mise à jour explicite de la constante et une revue. Déterminisme prouvé : `tests/test_utm_determinisme.py` appelle `generer_lien_utm` 100 fois sur les mêmes entrées et assert l'égalité byte à byte. Zéro réseau : un test d'isolation mock `socket` et vérifie qu'aucune résolution DNS n'est déclenchée. Tests par règle U-xx : un fichier `tests/test_utm_regle_U{nn}.py` par règle, avec cas positif et au moins deux cas négatifs (valeur hors enum, valeur à la limite). Test d'intégration sur données réelles : `tests/test_utm_integration_s006_s008.py` charge un content-item S006 réel et une entrée S008 réelle du dépôt, génère le lien, le valide, assert `verdicts == [(U-01..U-12, ok, ...)]`. RED d'abord : chaque règle U-xx est implémentée côté test avant le validateur, garantissant que le validateur ne passe que s'il satisfait le contrat mesuré.
