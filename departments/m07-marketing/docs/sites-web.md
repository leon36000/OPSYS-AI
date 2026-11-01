# M7 — Sites web statiques (tranche 1)

Décision d'architecte r6 : le contenu d'un site est décrit par un **schéma JSON versionné, indépendant du moteur de
rendu** ; le premier moteur est en **Python pur** (HTML statique) ; **Astro** reste la cible et sera un second
adaptateur du même schéma quand ses dépendances seront installables. Recherche : R4 §1 (sites, VPS, Caddy), §3.4
(NAP), §9 (Loi 25, langue française, faux avis).

Code : `src/m7_marketing/site/` — `schema_site.py`, `garde_contenu.py`, `rendu_statique.py`, `qa_site.py`,
`paquet.py`, `deploiement.py`, `service.py`. Contrat : `contracts/site-contenu.v1.schema.json`. Démonstration
fictive : `fixtures/sites/revetements-horizon-fictif/` (PME de rénovation extérieure de Laval, fr-CA + en-CA,
`fictif: true`, domaine réservé `.example`). Tests : `tests/site/`.

Le générateur d'une page de `site/generator.py` (vitrine OPSYS-AI, `content.yaml`) reste en place ; la chaîne
ci-dessous ne le remplace pas encore, elle le prolonge (même garde-fou de page `guardrail.py`, même audit SEO, même
évaluation AEO).

## Chaîne

```
schéma opsys.site/v1 ─► schema_site (structure) ─► garde_contenu (contenu) ─► verifier_actifs (images)
   ─► rendu_statique.rendre_site (fichiers en mémoire) ─► qa_site.controler_site (17 contrôles)
   ─► paquet (archive reproductible + manifeste) ─► deploiement (PLAN + Caddyfile, jamais exécuté)
   ─► demande de publication N3 (file d'approbation de la direction, jamais exécutée)
```

Fail-closed à chaque étape : un refus arrête la suite et dit `{code, chemin, detail}`.

## Schéma `opsys.site/v1`

Champs racine (tous requis, aucun champ inconnu) : `schema`, `site_id`, `fictif`, `domaine`, `langues`,
`revision.date` (seule source de date : `lastmod`, année du pied de page), `entreprise`, `charte`, `sources`,
`zones`, `services`, `temoignages`, `faq`, `cta`, `pages`, `images`, `legal`.

- **Langues** : `["fr-CA"]` ou `["fr-CA", "en-CA"]`, le français toujours en premier. Chaque texte localisé porte
  exactement les langues du site. Le français est à la racine (`/services/`), l'anglais sous `/en/`. La version
  anglaise ne peut pas dépasser la française de plus de 15 % en caractères (`REJ-SITE-FRANCAIS-NON-PREDOMINANT`,
  heuristique de la Charte de la langue française, à valider juridiquement).
- **Entreprise** : `nom`, `type_schema` (`HomeAndConstructionBusiness` ou `LocalBusiness`), `description`, NAP
  structurée (`telephone` « +1 450 555 0142 », `courriel` du domaine du site, `adresse` QC/CA avec code postal
  canadien), `heures`, `licence_rbq` facultative (numéro + source déclarée).
- **Charte** : `fond`, `texte`, `primaire`, `texte_sur_primaire`, `focus` (hexadécimal). Contraste **calculé**
  (WCAG 2.x) : 4,5:1 pour le texte et les liens, 3:1 pour l'indicateur de focus (`REJ-SITE-CONTRASTE-INSUFFISANT`).
  Le garde-fou de page hérité tient en plus les paires du gabarit à AAA (G-16).
- **Sources** : `{id, nature, reference, valide_par, date}`, nature parmi `juridique`, `contrat`,
  `registre_officiel`, `mesure`, `fournisseur`, `profil_marque`. Un bloc les cite par `source`.
- **Services**, **zones**, **témoignages** (`initiales` seulement, `zone`, `consentement {statut, preuve, date}`),
  **FAQ**, **CTA** (`cible` : une page, ou le téléphone / le courriel de la NAP), **images** (`images/<nom>.svg|png`,
  `largeur`, `hauteur`, `alt` obligatoire dans chaque langue).
- **Pages** : `slug` par langue (URL propres ; accueil = slug vide), `titre`, `titre_nav`, `description` (50 à 300
  caractères), `navigation`, `sections` typées : `hero`, `texte`, `services`, `service_detail`, `zones`,
  `temoignages`, `faq`, `coordonnees`, `cta`, `mentions_legales`, `confidentialite`. Une page d'accueil, une section
  `mentions_legales` et une section `confidentialite` sont obligatoires.
- **Légal** : `responsable_rp {titre, courriel}` (Loi 25) et `traceurs_non_essentiels: false`.

Codes de structure : `REJ-SITE-SCHEMA-VERSION`, `-CHAMP`, `-CHAMP-INCONNU`, `-LANGUE`, `-TRADUCTION`, `-SECTION`,
`-REFERENCE`, `-IDENTIFIANT`, `-SLUG`, `-NAP`, `-COULEUR`, `-IMAGE`, `-PAGES`, `REJ-SITE-CONTRASTE-INSUFFISANT`,
`REJ-SITE-FICTIF-DOMAINE-REEL` (un site fictif utilise `.example`, `.test`, `.invalid` ou `.localhost`),
`REJ-SITE-FRANCAIS-NON-PREDOMINANT`.

Le contrat JSON Schema publié décrit la même structure pour les autres adaptateurs ; un test vérifie que ses énumérés
suivent les constantes du validateur Python, qui fait foi.

## Garde-fous de contenu (`garde_contenu.py`)

Mêmes familles que l'usine à contenu (`opsys.garde_fou_texte`), plus un complément anglais court, appliquées à chaque
texte libre (jamais aux champs structurés : NAP, heures, initiales) :

| Code | Règle |
|---|---|
| `REJ-SITE-DONNEE-PERSONNELLE` | Adresse, courriel, téléphone, nom de client (formes ou `noms_interdits`), identifiant interne (`wct-…`, `lead-…` ou `identifiants_interdits`). Aucune source ne le lève. |
| `REJ-SITE-PROMESSE-NON-SOURCEE` | Prix ou offre, chiffre avec unité, garantie, date ou délai, sans `source` déclarée sur le bloc. |
| `REJ-SITE-TEXTE-LEGAL-NON-SOURCE` | Vocabulaire juridique ou section légale sans source de nature `juridique`. Le code ne rédige aucun avis légal. |
| `REJ-SITE-EXAGERATION` | « meilleur », « numéro 1 », « best »… ; aucune source ne le lève. |
| `REJ-SITE-LIEN-DANS-TEXTE` | Un lien dans un paragraphe (les liens viennent des CTA et de la navigation). |
| `REJ-SITE-TEMOIGNAGE-NON-CONSENTI` | Témoignage sans statut `consenti`, preuve et date. |
| `REJ-SITE-COPIE-CONCURRENT` | 8 mots consécutifs en commun avec un snapshot concurrent local (`fixtures/concurrents`). |
| `REJ-SITE-TRACEUR-SANS-CONSENTEMENT` | `traceurs_non_essentiels` vrai : aucun consentement actif n'est recueilli sans JavaScript. |
| `REJ-SITE-MARQUE-NON-CONFIGUREE` | Nom de marque du gabarit non configuré. |

Le nom de marque est masqué avant la lecture (une marque qui contient « garantie » ne promet rien). Images :
`REJ-SITE-IMAGE-ABSENTE`, `-DIMENSIONS` (dimensions réelles lues dans le fichier), `-FORMAT`, `-SVG-ACTIF` (script,
gestionnaire ou ressource externe dans un SVG).

## Adaptateurs de rendu

- **Python (livré)** : `rendu_statique.rendre_site(schema, actifs) -> {chemin: octets}`. Même schéma et mêmes actifs,
  mêmes octets (aucune horloge, ordre fixe). Chaque page : `lang`, `hreflang` réciproques et `x-default`, canonique,
  Open Graph, CSP stricte en `<meta>` (style inline par empreinte SHA-256, aucun script exécutable), un seul bloc
  JSON-LD `@graph` (entreprise + `Service` + `FAQPage`, tirés de la NAP et des textes visibles), lien d'évitement,
  repères `header`/`nav`/`main`/`footer`, un seul `h1`, focus visible, images avec `width`/`height`, aucune police ni
  ressource tierce, aucun JavaScript. Fichiers : pages en URL propres, `404.html` et `en/404.html` (`noindex`),
  `sitemap.xml` (versions linguistiques), `robots.txt` (avec `Sitemap:`), `favicon.svg` dérivé de la charte.
  Les témoignages sont affichés en initiales avec la mention de consentement ; aucun balisage `Review` (avis
  auto-publiés, déconseillé).
- **Astro (prévu, non livré)** : un projet Astro qui lit le même JSON (Content Collections) et rend les mêmes
  sections. Critère d'acceptation : `qa_site.controler_site` conforme sur sa sortie `dist/`, et mêmes URL, mêmes
  `hreflang`, même JSON-LD que l'adaptateur Python. Bloqué tant que Node et `astro` ne sont pas installables ici.

## Contrôle qualité (`qa_site.py`)

`controler_site(fichiers, schema)` lit les fichiers produits (de n'importe quel adaptateur) ; `rapport_lisible` en
fait un texte court. 17 contrôles, chacun avec ses constats `{fichier, detail}` :

`QA-HTML-BIEN-FORME` (pile d'éléments `html.parser`, doctype, id en double, attributs en double),
`QA-GARDE-FOU-PAGE` (G-01 à G-18 hérités), `QA-LIENS-INTERNES`, `QA-ANCRES`, `QA-IMAGES` (alt, dimensions déclarées
et réelles), `QA-FORMULAIRES` (libellés), `QA-FOCUS-VISIBLE`, `QA-CONTRASTE` (charte, AA), `QA-LANGUES` (lang,
`hreflang` réciproques), `QA-CANONIQUE-OG`, `QA-JSONLD` (valide, NAP concordante avec le schéma ET visible dans la
page, FAQ et services visibles), `QA-RESSOURCES-TIERCES`, `QA-SCRIPTS`, `QA-POIDS` (50 Ko par document, 500 Ko par
page avec ses images), `QA-PLAN-DU-SITE`, `QA-ROBOTS`, `QA-404`.

Limites : contrôle statique, pas un navigateur. Ni Lighthouse, ni axe-core, ni pa11y (non installables ici) ; aucun
calcul de contraste sur des images ; un vert ne prouve ni l'accessibilité réelle ni un rang Google.

## Paquet et plan de déploiement (artefacts seulement)

`paquet.construire_paquet` : archive `tar.gz` reproductible (entrées triées, horodatage tiré de la version
`AAAAMMJJTHHMMSSZ`, propriétaire 0/0, gzip sans date) avec `SHA256SUMS`, et manifeste (empreinte du schéma, de
l'archive et de chaque fichier, résultat du QA). Un QA non conforme bloque le paquet (`REJ-SITE-QA-NON-CONFORME`).
`m7_preparer_paquet_site` écrit `$OPSYS_HOME/sites/<site_id>/paquets/<version>/` : archive, `MANIFESTE.json`,
`Caddyfile`, `PLAN-DEPLOIEMENT.json` et `.md`. Une version est immuable (`REJ-SITE-PAQUET-EXISTANT`).

`deploiement.planifier_deploiement` rend un plan `PLAN_NON_EXECUTE`, `execute: false` :

- utilisateur **non root** (`opsys-deploy` par défaut ; `root` → `REJ-DEPLOI-UTILISATEUR-ROOT`), clé ed25519,
  seule commande privilégiée `systemctl reload caddy` en liste blanche sudoers ;
- `<racine>/releases/<version>` puis bascule **atomique** `ln -sfn … current.tmp && mv -Tf current.tmp current` ;
- vérification `sha256sum -c` locale et sur le serveur, `caddy validate` avant rechargement ;
- vérifications après bascule (200, 404, en-têtes, certificat > 14 jours, redirection `www`) ;
- **retour arrière** en une commande vers la version précédente ; purge des anciennes versions (N conservées, jamais
  `current`) marquée irréversible ;
- **Caddyfile** : HTTPS automatique (ACME, aucun certificat manuel), HSTS, `nosniff`, `X-Frame-Options`,
  `Referrer-Policy`, `Permissions-Policy`, COOP, CSP stricte (même empreinte de style que les pages, plus
  `frame-ancestors 'none'`), pages 404 par langue, redirection de `www`.

Chaque valeur insérée dans une commande est validée (hôte DNS, utilisateur POSIX, racine sous `/srv/sites/` ou
`/var/www/` terminée par le domaine, port, conservation 2 à 20) puis citée (`shlex.quote`) : `REJ-DEPLOI-*`. Aucun
module du site n'importe `subprocess`, `socket` ni client SSH ou HTTP (test AST).

## Publication : N3+, demande d'approbation, jamais exécutée

`m7_demander_publication_site(version, empreinte_archive, cible, …)` (T1, **N3**, aucun rôle d'appareil) suit le
patron du dépôt (`docs/architecture/ROLES.md`, `approbations.approbateur_en_cours`) :

1. appelé par un agent en mode `ombre`, l'appel est déposé dans la **file d'approbation** du socle, sans exécution ;
2. exécuté hors file (mode supervisé, appel direct) sans humain : `REJ-HUMAIN-REQUIS` ; appareil `admin` qui n'est
   pas le propriétaire : `REJ-HUMAIN-ROLE-INSUFFISANT` ; la politique N3 de M7 (`nathan_owner`) refuse tout autre
   approbateur dans la file ;
3. approuvé par le propriétaire : le paquet est **régénéré** (déterminisme), l'empreinte demandée doit être
   exactement la sienne (`REJ-PUBLICATION-EMPREINTE-DIFFERENTE`), et l'outil rend le plan approuvé avec le statut
   `PUBLICATION_APPROUVEE_NON_EXECUTEE`, `execute: false`. Une personne exécute le plan à la main.

Un site `fictif: true` n'est jamais publiable (`REJ-PUBLICATION-SITE-FICTIF`).

## Outils

| Outil | Autonomie / niveau | Rôle |
|---|---|---|
| `m7_valider_schema_site` | T0 / N0 | Structure, contenu, actifs ; rien d'écrit. |
| `m7_generer_site_statique` | T0 / N0 | Génère en mémoire, rend la liste des fichiers, le QA et, sur demande, un fichier. |
| `m7_preparer_paquet_site` | T1 / N1 | Écrit l'artefact (archive, manifeste, Caddyfile, plan) ; n'exécute rien. |
| `m7_demander_publication_site` | T1 / **N3** | Demande de publication publique ; même approuvée, n'exécute rien. |

Tous prennent `schema` (actifs lus par nom dans `$OPSYS_HOME/sites/<site_id>/actifs/images/`) ou `schema_demo`
(`revetements-horizon-fictif`), et `concurrents` (slugs de snapshots locaux). Aucun n'a de rôle d'appareil.

## Ce qui n'est pas fait

- **Déploiement réel** : aucune connexion SSH, aucun envoi, aucune commande exécutée ; pas de clé SSH générée ni de
  coffre branché ; le Caddyfile n'est pas validé par `caddy validate` ici (Caddy absent).
- **Astro** : second adaptateur prévu, non livré.
- **WordPress** (plugin « OPSYS Connect », R4 §2) et autres CMS : non commencés.
- **Formulaires dynamiques** : aucun formulaire n'est rendu (la CSP porte `form-action 'none'`) ; le contrôle des
  libellés existe pour les adaptateurs futurs. Le formulaire de M1 reste un extrait à coller.
- **Analytique** (Umami, Matomo) et tout traceur : refusés en tranche 1 (Loi 25, consentement préalable).
- **Mesures réelles** : Lighthouse, axe-core, Search Console, indexation : non branchés.
- Avis juridique sur la prédominance du français, les mentions légales et la politique de confidentialité : à obtenir ;
  le code exige une source juridique déclarée, il ne la remplace pas.
