# Qualification de la console dans un navigateur RÉEL (2026-11-01)

> Périmètre : les parcours du propriétaire et de l'administrateur de la console web OPSYS (`src/opsys/console/`), rejoués dans
> **Chromium 156 réel** (headless, piloté par `playwright-core` 1.64.1) sur une **instance fictive** (base SQLite jetable, personnes,
> entreprise et secrets fictifs, aucun réseau). Le banc est répétable : `install/qualification/navigateur/`.
> **Formule exacte autorisée** : « les parcours de la console ont été joués dans Chromium réel sur une instance fictive : 132 constats,
> 132 réussis après correction de 11 défauts réels ; Firefox : extrait seulement ; rien d'autre n'est prouvé (voir §9) ».
> Ceci n'est PAS une qualification d'accessibilité complète, ni de sécurité, ni de production.

## 1. Verdict

| | Avant les corrections | Après |
|---|---|---|
| Parcours complet Chromium (`resultats-parcours-…`) | **131 constats, 18 échecs bloquants** | **132 constats, 0 échec bloquant** |
| Injections de défauts (banc) | — | **12 sur 12 détectées** |
| Mutations de source (tests Python sans navigateur) | — | **21 sur 21 tuées** (1 survivante au premier passage, fermée) |
| Firefox 151 (extrait : connexion, tableau, wallboards avec SSE, responsive) | non joué | 31 constats, 31 réussis |

Ce que le navigateur réel a trouvé et que les clients HTTP de test ne voyaient pas : **un wallboard figé** (la CSP bloquait `fetch` et
`EventSource`, §6 D1), **la page qui défile horizontalement** sur 8 pages à 375 px, **une pastille illisible en thème sombre** (2,52:1),
des cases à cocher étirées, une navigation « Plateforme » à impasses, 18 arrêts de tabulation avant le contenu, du JSON brut montré à un
humain refusé. Aucun contrat de sécurité n'a été affaibli (une seule règle de sécurité change, §6 D1, et elle se **restreint** à
l'origine de la console sur les seules pages de wallboard).

## 2. Inventaire des moyens (vérifié, rien n'a été installé)

| Moyen | État sur cette machine | Utilisé |
|---|---|---|
| Chromium système (`chromium`, `google-chrome`…) | absent du `PATH` | non |
| `/opt/pw-browsers` | absent | non |
| Cache Playwright `~/.cache/ms-playwright` | `chromium-1248` (+ headless-shell, + 1228), `firefox-1532`, `webkit-2311` | **Chromium 156.0.8078.4 (1248)** |
| Playwright Python | absent | non |
| Playwright Node : `playwright-core` 1.64.1 | présent **hors dépôt**, dans le `node_modules` d'un autre projet de la machine, lu en lecture seule (`OPSYS_PLAYWRIGHT_CORE`) | **oui** |
| Firefox | build 1532 d'un Playwright plus ancien : se lance, protocole partiellement incompatible (`page.route` échoue) | extrait seulement |
| WebKit | `minibrowser-gtk` présent mais ne se lance pas (bibliothèques manquantes) | non (NON PROUVÉ) |
| Outils MCP du navigateur intégré (`mcp__Claude_Browser__*`) | disponibles | **non** : un banc répétable doit être un script, pas une séance pilotée à la main |
| `mcp__claude-in-chrome__*` | disponible | **non, volontairement** (Chrome personnel et sessions de l'utilisateur) |

**Dépendance fragile, dite sans euphémisme** : `playwright-core` n'est pas dans le dépôt (pas de `npm install` ici, pas de réseau). Le banc le
trouve par variable d'environnement ou dans des `node_modules` voisins ; **sans lui, ou sans Chromium, il écrit « prêt mais NON EXÉCUTÉ », liste
ce qui manque et sort en code 3** (testé : `tests/test_banc_navigateur.py`). Le test `test_banc_navigateur_reel_quand_chromium_present` saute
proprement dans ce cas.

## 3. L'instance fictive

`install/qualification/navigateur/instance.py` : la VRAIE application (`creer_application`) servie par uvicorn sur `127.0.0.1`. Les VRAIS
départements (`departments/`) plus un département FICTIF `m09-qualif` dont l'unique outil (N3, mode « ombre ») ajoute une ligne à un
fichier local : c'est l'« effet » vérifié après approbation. Trois personnes fictives (`proprio-fictif` = `nathan_owner`, `admin-fictif` = `admin`,
`employe-fictif` = `employee`) aux mots de passe générés à l'exécution (fichier 0600 jetable) ; faits fictifs de M8 pour les wallboards ; quatre
demandes N3 en attente ; politique d'autorité mémoire fictive pour la demande cron. **Aucune requête n'a quitté 127.0.0.1** (le banc refuse le
reste et le constate : `global/reseau-externe`). Accommodements (dits dans le README du banc, aucun ne touche une garde de sécurité) : horloge
des wallboards lue dans un fichier, `sleep` du flux SSE ramené à 1 s, session de 5 s sur une seconde instance pour l'expiration.

## 4. Parcours joués dans Chromium (exécution finale `20261101T150736Z`, 78 s)

Preuves : `docs/qualification/navigateur/resultats-parcours-20261101T150736Z.{json,md}`, journal `journal-parcours-…txt`, captures
`20261101T150736Z-NN-*.webp` (1,5 Mo pour tout le dossier de preuves, WebP via ImageMagick ; les PNG d'origine de cette exécution faisaient 1,7 Mo).

| Groupe | Constats | Ce qui a été prouvé dans le navigateur |
|---|---|---|
| connexion (11) | 11/11 | formulaire vide bloqué par le navigateur, aucun POST ; échec 401 en français, `role="alert"`, mot de passe non réaffiché, aucun cookie ; succès ; cookie `HttpOnly`, `Secure`, `SameSite=Strict`, chemin `/opsys`, 8 h, invisible au JavaScript (`document.cookie`), `Set-Cookie` brut conforme ; déjà connecté → redirigé |
| tableau de bord (3) | 3/3 | 17 onglets, onglet courant, 11 cartes (10 départements + 1 fictif), pastille « 4 » |
| approbations (9) | 9/9 | file de 4 demandes N3 avec arguments exacts ; boîte de confirmation du navigateur **rejetée** = rien d'exécuté, **acceptée** = exécutée UNE fois (une ligne dans le fichier d'effets) ; « Exécutées » nomme le signataire ; refus sans effet ; **double soumission simultanée** : 303 puis 400, une seule exécution ; employé : 403 en page lisible |
| Plateforme (18) | 18/18 | fournisseurs (profil, **activation refusée avec codes** `REFUS_POLITIQUE` / `LICENCE_NON_COMMERCIALE`) ; **secret saisi puis jamais réaffiché** : absent du DOM, des champs, de l'URL, du stockage du navigateur, de **toute réponse et redirection reçues**, de l'API, du journal du serveur et de la base (chiffrée) ; avatars, connaissances, connecteurs, observabilité s'affichent ; révocation avec confirmation ; navigation commune aux 5 pages |
| wallboards (11) | 11/11 | rendu serveur sans JS ; **flux SSE ouvert** (« Connecté (flux) ») ; on fait vieillir l'horloge du serveur : **les tuiles deviennent « PÉRIMÉE » SANS recharger le document** et la bannière n'est plus « ok » ; pause (`aria-pressed`) fige l'écran ; reprise ; mode télé ; **réseau coupé : « Connexion perdue … Ne vous y fiez pas »** sur toutes les tuiles ; propriétaire sans rôle `admin` : 403 en page |
| registre / cron (6) | 6/6 | création d'un agent, activation, formulaire cron, case de confirmation exigée par le navigateur, intention **inerte** (« Aucune tâche Core n'a été créée ou exécutée ») |
| déconnexion (3) | 3/3 | cookie effacé, retour arrière + rechargement refusés ; cookie copié avant la déconnexion : **encore accepté** (limite connue, §7 O2) |
| expiration (4) | 4/4 | cookie à 5 s : page protégée redirigée après l'échéance ; cookie signé **échu** et cookie **falsifié** (rôle élevé, signature d'origine) : page redirigée et API en 401 |
| CSRF (7) | 7/7 | POST sans jeton / jeton faux (`/deconnexion`, décision, secret, API JSON) : 403 ; la session survit ; **formulaire soumis depuis un AUTRE SITE avec le bon jeton : Chromium n'envoie pas le cookie** (`SameSite=Strict`) |
| en-têtes (7) | 7/7 | 10 pages : CSP, `nosniff`, `DENY`, `no-referrer`, `no-store` ; ressource statique cache 1 h ; 404 sans trace ; ni `/docs` ni `/openapi.json` ; **la CSP bloque réellement** un script injecté et une image externe (violations consignées) ; la console ne s'affiche pas dans un cadre d'un autre site |
| journal (1) + serveur (8) | 9/9 | un échec de connexion sur la console **sans préfixe** (comme derrière Caddy) produit la ligne d'accès que **le filtre fail2ban de production reconnaît** ; aucun mot de passe, secret de session ni valeur de secret dans les journaux ; aucune valeur de secret ni mot de passe en clair dans la base ; aucun `Traceback` ni 500 ; fichier d'effets exact (A et C une fois ; B, refusée, rien) |

## 5. Accessibilité (WCAG 2.1 AA) et responsive

**Méthode.** axe-core n'est pas disponible hors ligne. J'ai écrit mes propres contrôles (`controles_a11y.js`, injectés par CDP : la CSP reste intacte) et
les ai exécutés sur **21 pages × 3 largeurs (375, 768, 1280) × 2 thèmes (clair, sombre)** : 19 pages de la console, le détail d'un wallboard et la
connexion. Règles : `lang`, titre, un seul `h1`, titres sans saut, repère `main`, `nav` nommés, contenu dans les repères, `id` uniques, champs
étiquetés, `autocomplete` du mot de passe, boutons et liens nommés, `alt`, tableaux avec en-têtes, `tabindex` positif, erreurs annoncées, zoom non
bloqué, références ARIA valides, aucun script/style en ligne, **contraste mesuré** sur chaque nœud de texte visible (jusqu'à 2 641 par page ; fond effectif composé), cases à cocher.
Clavier : parcours Tab sur connexion (+ Entrée), tableau de bord (95 arrêts), approbations (27), secrets (34), fournisseurs (107) : ordre = ordre du
document, aucun piège, **focus visible avec contour ≥ 3:1**, lien d'évitement fonctionnel, confirmation au clavier. Responsive : pas de défilement
horizontal de la **page** à 375, 768, 1280 et 320 px (zoom 400 %), en-tête ≤ 400 px sur un écran de 800 px à 375 px.

**Résultat après corrections : toutes ces règles passent.** Contraste minimal mesuré : 4,56:1 (clair), 5,41:1 (sombre) — **la marge est mince en clair**.

**Ce que ces contrôles NE couvrent PAS** (liste complète, dite sans euphémisme) : la qualité des textes alternatifs et des libellés ; le parcours d'un
**vrai lecteur d'écran** (aucun testé : NVDA, JAWS, VoiceOver, TalkBack) ; l'annonce effective des régions `alert`/`status` ; le contraste des images,
dégradés et pseudo-éléments ; l'espacement du texte (1.4.12) ; le zoom 200 % ; l'orientation ; les cibles tactiles ; les médias ; la logique de
lecture sur des pages que je n'ai pas visitées (la console compte une centaine de modules d'interface : **21 pages sur ~100 balayées**, les pages CRM,
Direction IA, terrain, paie, etc. exigent d'autres rôles et ne l'ont pas été). La règle « `th` avec `scope` » est **assouplie** (les `th` d'un `thead` sont
admis) ; « tableaux nommés (`caption`) » est une bonne pratique, non bloquante, et **n'est pas respectée** (aucun tableau n'a de légende).

## 6. Défauts RÉELS révélés et corrigés (chacun avec preuve avant/après et test Python sans navigateur)

Preuves « avant » : `docs/qualification/navigateur/avant-corrections/` (exécution `20261101T145528Z` du même banc contre le code de la base `5208490a4`,
+ 4 captures). Tests : `tests/test_console_navigateur_corrections.py` (17 tests ; **12 échouent sur l'ancien code, 17 passent après**).

| # | Défaut | Preuve avant | Correction | Test |
|---|---|---|---|---|
| **D1** | **Les wallboards ne se rafraîchissent jamais dans un vrai navigateur.** La CSP `default-src 'none'` n'a pas de `connect-src` : `fetch` et `EventSource` (même origine) sont bloqués. La page reste sur « Connexion : Rendu initial » et **continue d'afficher « à jour »** alors que les mesures sont périmées (capture `…-16-wallboard-perime.webp` « avant »). Seul l'état initial rendu par le serveur est vrai ; le script « Connexion perdue » n'apparaît qu'après 95 s. Les tests existants (faux DOM sous Node) ne pouvaient pas le voir. | `wallboards/flux-sse-ouvert`, `sse-rafraichit`, `perime-en-toutes-lettres`, `pause-fige` | `connect-src 'self'` **ajouté à la CSP des seules pages `/wallboards/{id}`** (`application.py`, `CSP_CONNEXION_MEME_ORIGINE`) ; aucune origine externe, aucune autre page touchée. **C'est le seul changement de sécurité** ; il assouplit la CSP au strict nécessaire. | `test_csp_connect_src_seulement_sur_la_page_de_wallboard` (4 chemins), `…_refuse_les_chemins_deguises` |
| D2 | **La PAGE défile horizontalement** (1.4.10) : la classe `.table-defilante` est utilisée par 6 modules mais **n'avait aucune règle CSS** ; les autres tableaux n'avaient aucun conteneur. 375 px : finance 1078, fournisseurs 896, agents 858, secrets 849, avatars 652, connecteurs 639, budgets 455, wallboards 427 ; 768 px : finance 1086, fournisseurs 904, agents 866, secrets 856 ; 320 px : départements 332 (identifiant de KPI sans coupure). | `accessibilite/reflow`, `responsive/largeur-375/768/320` | règle `.table-defilante` ; `pages.envelopper_tables` enveloppe chaque tableau de premier niveau (idempotent, tableaux imbriqués gérés) ; `.carte, .grille > *` `min-width:0` + `overflow-wrap:anywhere` ; `code` coupe les chaînes longues | `test_tableaux_enveloppes…`, `test_feuille_de_style_regles_issues_du_banc`, `test_cinq_pages_html_sans_tableau_nu…` |
| D3 | **Pastille « Approbations » illisible en thème sombre** : blanc sur `#ff7b72` = **2,52:1** (1.4.3). | `accessibilite/regle-contraste-texte` | variable `--sur-danger` (blanc en clair, `#0f1318` en sombre) | `test_pastille_lisible_en_clair_et_en_sombre` (+ paires badges/messages ≥ 4,5:1) |
| D4 | **Cases à cocher étirées à 100 %** (`input { width:100% }`) : la case flotte au centre, détachée de son libellé (25 sur « fournisseurs »). | `accessibilite/regle-cases-a-cocher-taille` ; capture « avant » 08 | `input[type=checkbox], input[type=radio] { width:auto }` | `test_feuille_de_style_regles_issues_du_banc` |
| D5 | **Aucun lien d'évitement** : 18 arrêts de tabulation avant le contenu (2.4.1, couvert seulement par les repères). | `clavier/lien-evitement`, `connexion-ordre` | « Aller au contenu » en premier arrêt, cible `h1#contenu` (`tabindex="-1"`) | `test_gabarit_un_seul_h1_lien_d_evitement_et_cible` ; `tests/test_console.py` (2 assertions mises à jour : `<h1 id="contenu" tabindex="-1">`, ancres exclues des liens) |
| D6 | **Deux `h1`** dans les pages à sections (fusion, banque, CRM, rapprochements…). | `accessibilite/regle-un-seul-h1` | `pages.retrograder_titres_niveau_1` : le gabarit porte l'unique `h1` | idem |
| D7 | Les erreurs étaient `role="status"` (poli, souvent non annoncé au chargement d'une page) (3.3.1, 4.1.3). | `connexion/echec-annonce` | `role="alert"` pour le genre `erreur`, `status` sinon | `test_erreur_annoncee_en_alert_succes_en_status` |
| D8 | **Sous-navigation « Plateforme » à impasses** : un `<p>` différent par page ; « Connaissances » introuvable depuis Secrets et Connecteurs, « Avatars » absent de Connecteurs, pas de repère `nav`. | `plateforme/sous-navigation` | `pages.navigation_plateforme` unique (`<nav aria-label="Plateforme">`, `aria-current`) dans les 5 pages | `test_cinq_pages_plateforme_exposent_les_quatre_autres_sans_impasse` (sections épinglées dans le test) |
| D9 | **JSON brut montré à un humain** : `{"detail":"administration réservée…"}` pour un 403 de page (wallboards, plateforme…) ; 404 en JSON anglais (`{"detail":"Not Found"}`). | `approbations/refus-lisible`, `wallboards/proprietaire-sans-role-admin` | gestionnaire `HTTPException` : page HTML française **seulement si `Accept: text/html` ET chemin hors `/api/`** ; clients d'API et tests gardent le JSON d'origine ; libellés anglais par défaut jamais affichés ; détail échappé | `test_refus_de_page_lisible_pour_un_navigateur_json_pour_les_clients`, `test_page_inconnue_404…`, `test_refus_html_n_echappe_pas…` |
| D10 | Le message de succès d'une demande cron (`message-succes`) n'avait **aucun style**. | `registre-cron/message-succes-style` | `.message-ok, .message-succes` | `test_feuille_de_style_regles_issues_du_banc` |
| D11 | **En-tête de 602 px (566 sur d'autres pages) sur un écran de 800 px** à 375 px : la barre d'onglets se tasse dans une colonne de 170 px. | `responsive/largeur-375` | `nav` pleine largeur sous 600 px, marges réduites | `test_feuille_de_style_regles_issues_du_banc` |

## 7. Observations NON corrigées (faits, pas des défauts de ce chantier)

- **O1 — Aucun verrouillage applicatif.** 12 échecs de suite : chaque essai reste un 401 et le **bon mot de passe est encore accepté** (constat `info`).
  La limitation est externe (fail2ban, 5 échecs / 10 min → 1 h, `docs/ops/EXPLOITATION.md`) : **le filtre reconnaît la ligne d'accès réelle**, mais fail2ban,
  le bannissement et `ufw` n'ont PAS été exercés. Sur un poste sans fail2ban, la force brute n'est pas freinée.
- **O2 — Cookie rejouable après déconnexion.** Sessions sans état côté serveur (contrat existant, 8 h) : un cookie copié avant la déconnexion reste valide
  jusqu'à son échéance (constat `info`, `deconnexion/cookie-rejoue`). Lever cela exige une liste de révocation : décision d'architecture, non faite ici.
- **O3 — Perte de connexion d'un wallboard annoncée lentement** : 3 × l'intervalle + 5 s (95 s à 30 s ; 185 s à 60 s). Prouvé avec l'horloge du navigateur
  accélérée (Playwright `clock`), pas en temps réel. Contrat M8.8 inchangé.
- **O4 — `fetch` depuis une page de la console hors wallboards est bloqué par la CSP** (à raison). Le banc écrit donc ses doubles soumissions par le
  contexte de requêtes de Playwright (même jar de cookies), pas depuis la page.
- **O5 — Contraste clair mince** (4,56:1 au minimum) : tout éclaircissement du texte atténué le ferait passer sous 4,5:1 (le banc le détecte : injection `contraste-faible`).

## 8. Preuve que le banc et les tests détectent les défauts

**Injections dans l'instance (le banc doit échouer)** — `lancer.py mutations`, résultat `mutations-20261101T151254Z.json` : 12 sur 12 détectées.

| Injection | Constats qui échouent |
|---|---|
| `csrf-retire` | `csrf/post-sans-jeton`, `post-jeton-faux`, `api-sans-jeton`, `inter-sites-samesite` |
| `cookie-sans-httponly` | `connexion/cookie-drapeaux`, `cookie-invisible-js` |
| `cookie-sans-secure` | `connexion/cookie-drapeaux` |
| `cookie-samesite-none` | `connexion/cookie-drapeaux`, `csrf/inter-sites-samesite` |
| `cookie-non-efface` (1ʳᵉ passe : « survivante » car le groupe sortait en exception ; parcours rendu robuste) | `deconnexion/cookie-efface` |
| `secret-en-clair` | `plateforme/secret-jamais-reaffiche`, `secret-aucune-reponse` |
| `etiquette-retiree` | `accessibilite/regle-champs-etiquetes` |
| `lang-retire` | `accessibilite/regle-lang-fr` |
| `csp-affaiblie` | `entetes-securite/pages`, `csp-bloque-script-en-ligne` |
| `focus-retire` | `clavier/connexion-focus-visible`, `departements-focus` |
| `contraste-faible` | `accessibilite/regle-contraste-texte` |
| `debordement-horizontal` | `responsive/largeur-375`, `largeur-768` |

**Mutations de source (tests Python sans navigateur)** — `mutations_sources.py`, `mutations-sources-20261101T151500Z.txt` : 21 sur 21 tuées. Première passe : 20 mutations,
1 survivante (`navigation-sans-connaissances` : le test relisait la liste des sections depuis le code mutant) ; fermée en épinglant la liste dans le test.
Exemples : `connect-src` retiré ; `connect-src` appliqué partout ; regex de wallboard trop large ; tableaux non enveloppés / doublement enveloppés ; second `h1` conservé ;
erreur en `status` ; lien d'évitement retiré ; navigation sans `aria-current` / sans repère `nav` ; erreur HTML servie aux API ; détail non échappé ; pastille blanche en sombre ;
règle de défilement retirée ; libellé anglais affiché.

## 9. NON PROUVÉ (sans euphémisme)

- **Autres navigateurs** : Firefox 151 seulement sur un extrait de 31 constats (connexion, tableau de bord, wallboards avec SSE, responsive), avec un build plus ancien que
  `playwright-core` : les groupes CSRF/en-têtes (qui exigent `page.route`) **n'ont pas pu s'y exécuter**, et le parcours clavier n'y est pas fiable (le critère « retour au début »
  ne convient pas à Firefox) : **non prouvé**. **WebKit/Safari : non lancé.** Chrome/Edge de production, navigateurs mobiles : non.
- **Lecteur d'écran réel** : aucun. Les rôles `alert`/`status` sont présents ; **leur annonce effective n'est pas vérifiée**.
- **Mobile natif** et tactile : seulement des viewports émulés (375, 768) sans gestes ; aucun appareil.
- **Réseau, TLS, Caddy, HSTS, DNS** : instance en HTTP sur 127.0.0.1 (Chromium accepte les cookies `Secure` sur ce « contexte de confiance » ; un vrai poste sans TLS ne les recevrait pas).
  fail2ban, `ufw`, limitation de débit : seulement la reconnaissance de la ligne de journal par le filtre.
- **Pages non balayées** (~80 sur ~100), rôles autres que propriétaire, administrateur et employé ; formulaires terrain ; PDF/OCR (les tests PDF/fusion échouent sur cette machine, préexistant :
  46 échecs identiques avant et après mes changements).
- **Parcours multi-onglets / concurrence réelle de deux humains**, charge, longue durée, redémarrage du serveur pendant un wallboard.
- **Accessibilité** : voir la liste du §5 (1.4.12, 200 %, orientation, cibles, médias, qualité des libellés, `caption`).
- **Fournisseurs réels** (OCR, modèles, courriel, WordPress, Twilio…) : jamais appelés ; la sonde de test de connexion des fournisseurs n'a pas été déclenchée.

## 10. Rejouer

```bash
# venv du dépôt, PYTHONPATH = src + departments/*/src, HOME et TMPDIR privés
export OPSYS_PLAYWRIGHT_CORE=/chemin/vers/node_modules/playwright-core   # sinon recherche dans des node_modules voisins
python install/qualification/navigateur/lancer.py verifier       # code 3 s'il manque un moyen
python install/qualification/navigateur/lancer.py parcours --webp
python install/qualification/navigateur/lancer.py mutations
python install/qualification/navigateur/mutations_sources.py     # ne pas lancer en parallèle d'un parcours
python -m pytest tests/test_console_navigateur_corrections.py tests/test_banc_navigateur.py
```
Les preuves ne sont jamais écrasées (un horodatage par exécution). Chromium plante si `TMPDIR` dépasse ~100 caractères : le banc utilise un dossier court pour le navigateur.

## 11. Suites lancées pour ce chantier (comptes exacts, après le dernier changement de code)

- `tests/test_console*.py` (136 fichiers) + `tests/test_banc_navigateur.py`, en 5 tranches parallèles : **2 472 réussis, 13 sautés, 46 échecs**. Les 46 échecs sont tous dans les tests de fusion PDF/OCR/AP
  (`test_console_fusion_ap*.py`, `test_console_fusion_pdf*.py`) ; **le même ensemble de 46 échoue à l'identique sur la base `5208490a4`** (comparaison des listes, isolation PDF absente de cette machine : préexistant).
- `tests/test_console_navigateur_corrections.py` : 17 réussis (12 échouaient sur l'ancien code) ; `tests/test_banc_navigateur.py` : 13 réussis (dont une exécution réelle dans Chromium ; elle saute si le navigateur manque).
- Gardes d'intégration : `tests/test_paquets_declares.py`, `tests/test_garde_fou_texte.py`, `tests/test_commande_metier.py`, `tests/test_packs_generalisation.py` : 142 réussis ; `tests/test_banc_qualification.py` et
  `tests/test_provenance_m8_lecture_atomique.py` : 54 réussis.
- `ruff check src tests departments` : propre ; `verifier-wt.sh` : `OK` (10 départements, 537 outils : aucun outil ajouté au catalogue ; le département fictif du banc vit sous `install/`, hors du chargement par défaut).
- Matrices d'exigences : **aucun statut changé** (aucune ne justifie « FAIT_PROUVE » : données fictives, connecteurs de production absents).

## 12. Addendum du 2 novembre 2026 : l'écran « Réglages de direction » (CFG-1)

Un quinzième groupe, `reglages`, rejoue dans Chromium (156, Playwright 1.64.1, sans réseau) l'écran de la console qui adopte les valeurs de
direction ([REGLAGES-DIRECTION](../architecture/REGLAGES-DIRECTION.md)) : 10 réglages « À décider » (4 de M2, 6 de M8) avec leur bouton
d'adoption N3, trois propositions seulement (les délais de M2), chacune étiquetée « recommandation, non validée » avec sa source ; la proposition
**préremplit** le champ sans rien appliquer ; la raison est obligatoire côté navigateur ; l'adoption redirige, annonce « Valeur adoptée (N3) »
(`role="status"`), marque la carte « Adopté » et remplit le journal ; une valeur hors bornes est refusée en 400 avec son motif, une adoption sans
jeton CSRF en 403 ; l'état du serveur après ces essais dit exactement une valeur adoptée et une chaîne valide ; le retour arrière remet les dix
réglages à décider ; l'administrateur voit l'écran **sans formulaire** et son POST direct est refusé (403) ; les règles d'accessibilité maison
(3 largeurs × 2 thèmes) et l'absence de défilement horizontal passent. Le tableau de bord compte désormais 18 onglets (le test du banc a été
mis à jour) et la page entre dans le balayage d'accessibilité de l'administrateur.

- Preuves : `docs/qualification/navigateur/resultats-parcours-20261102T070912Z.{json,md}` (groupes `reglages` : 12 constats, et `tableau` : 3, plus 2 globaux : **17 constats, tous OK**),
  journal et trois captures WebP (`…-30-reglages-a-decider`, `…-31-reglages-adopte`, `…-32-reglages-mobile-375`).
- **Banc complet rejoué** (`20261102T070950Z`, 77 s, preuves non archivées) : 139 constats OK et **5 échecs bloquants qui ne viennent pas de ce
  chantier** : la sous-navigation « Plateforme » et quatre constats des wallboards (liste, SSE périmé, pause, « Connexion perdue »). Les mêmes
  5 constats échouent à l'identique sur la base `e0424b040` rejouée dans un clone propre (même Chromium) : ils sont **préexistants dans cet
  environnement** (le rapport du 1er novembre les donnait OK : une dérive du navigateur ou de l'hôte reste à expliquer, non investiguée ici).
- Non prouvé : Firefox et WebKit pour cet écran, lecteur d'écran réel, tactile et téléphone, parcours à deux personnes en même temps.
