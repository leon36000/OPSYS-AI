# M7 : plugin WordPress « OPSYS Connect » et sas de publication sociale

Statut (2026-11-01) : **tranche 1, jamais exécutée contre un vrai WordPress ni un vrai réseau.** Tout ce qui suit a été
prouvé avec des doubles de test et une analyse statique ; ce que cela ne prouve pas est dit en toutes lettres à la section
« Ce qui n'est PAS prouvé ». Rien n'est qualifié, rien n'est « complet ».

Décisions de départ : feuille de route r2 (« WordPress », « Réseaux/pub »), décision d'architecte r2 n°3 (aucun texte, logo
ou mention final produit par un modèle d'image sans composition déterministe), recherche R4 §2 et §5. Code :
`integrations/wordpress/opsys-connect/` (plugin PHP, GPL-2.0-or-later), `departments/m07-marketing/src/m7_marketing/wordpress/`
(client, flux, registre des sites, analyse maison du PHP), `.../sas_social/` (sas), `.../publication_outils.py` (outils),
`.../journal_chaine.py`, `.../secret_coffre.py`. Vecteurs de test partagés :
`departments/m07-marketing/contracts/opsys-connect-vecteurs.v1.json`.

## 1. Audit de l'existant (avant cette tranche)

| Ce qui existait | État | Ce que la tranche en fait |
|---|---|---|
| `m7_marketing.social.postiz_adapter` + outil `m7_publier_post_social` (T3) | Adaptateur Postiz « GATED » : `enabled=False` par défaut, `dry_run`, écriture réelle toujours refusée (`NotAutorise`). Aucun sas, aucune idempotence, aucun quota. | **Conservé tel quel** (d'autres tests le gardent). Le sas ci-dessous est la voie de publication sociale ; Postiz (AGPL, service séparé non modifié) reste une option de longue traîne (R4 §5.3), derrière le même sas. |
| `m7_marketing.moderation` (détection de visages et de plaques, floutage, revue humaine sous seuil) | Logique pure et testée, détecteur injectable, adaptateur OpenCV non branché. | **Réutilisé** : `garde_fous.moderation_depuis_rapport` transforme un `RapportPhoto` en statut de modération d'un média ; un média non `verifiee` ne part pas. |
| `opsys.garde_fou_texte` + `usine.controle_texte` (profil de texte public de M7) | Familles de règles du socle (adresse, coordonnées, nom de client, prix, chiffre non sourcé, garantie, promesse de date, exagération, lien, longueur). | **Réutilisé** pour tout texte de publication sociale (profil `PROFIL_TEXTE_PUBLIC`) et, sans `lien` ni `longueur`, pour le texte visible d'un article WordPress. Aucun motif n'est recopié. |
| `m7_marketing.site` (sites statiques `opsys.site/v1`, paquet, plan de déploiement, `m7_demander_publication_site` N3 jamais exécutée) | Chaîne complète sans déploiement réel. | **Même patron** pour les nouveaux N3 : l'agent dépose dans la file, la direction approuve, la décision est CONSIGNÉE (`..._NON_EXECUTEE`), rien n'est exécuté par l'outil. |
| `usine` (contenus de chantier, registres append-only, `_proprietaire_qui_decide`) | Décision humaine établie par la plateforme (jeton d'appareil confirmé en base ou approbation de la file), jamais par un argument. | **Réutilisé** pour savoir QUI approuve. |
| Coffre de secrets (`opsys.secrets_coffre`) | Chiffrement au repos, résolution serveur seulement, masquage, journal d'accès. Refuse la résolution dans une transaction métier. | **Réutilisé** (`secret_coffre.fournisseur_du_coffre`) : le secret du site et le jeton d'un compte sortent du coffre le temps d'un appel, depuis un exécuteur hors transaction. |

## 2. Architecture en une page

```
 Chloé (agent, N2)                     direction (N3 / N4)                      exécuteur hors transaction
 ─────────────────                     ───────────────────                      (NON BRANCHÉ dans cette tranche)
 m7_preparer_brouillon_wordpress ─┐
 m7_composer_publication_sociale  ├─►  journaux append-only chaînés  ◄── m7_demander_publication_wordpress (N3)
 m7_soumettre_publication_sociale ┘     (sites_wordpress, publications_wordpress,  m7_demander_publication_sociale (N3)
                                          comptes_sociaux, publications_sociales)  m7_demander_annonce_payante (N4)
                                                      │                                       │ approbation CONSIGNÉE
                                                      ▼                                       ▼
                                  wordpress.executeur ── client signataire ──HTTP signé──► plugin « OPSYS Connect »
                                  sas_social.executeur ── adaptateur (port) ───────────► réseau (doubles seulement)
                                         ▲ jeton / secret : coffre, le temps d'un appel
```

Principe : **aucun outil d'agent ne publie, n'émet un jeton, ne transmet un brouillon ni n'appelle un réseau.** Les douze
outils lisent et écrivent des journaux. Les exécuteurs (`wordpress/executeur.py`, `sas_social/executeur.py`) sont du code
séparé, appelé par un processus hors transaction (le coffre refuse la résolution d'un secret dans une transaction
métier). Aucun planificateur ne les appelle dans cette version.

## 3. Le plugin WordPress

Licence : **GPL-2.0-or-later**, texte intégral dans `integrations/wordpress/opsys-connect/LICENSE`. Un plugin qui s'exécute
dans WordPress est une œuvre dérivée de WordPress (position de la WordPress Foundation et de la FSF, R4 §2.2 : **à valider
auprès d'un juriste**). Le reste du dépôt est sous Apache-2.0 et **n'importe jamais ce dossier** (test AST) ; le code Python
ne fait que LIRE ses fichiers comme du texte (analyse statique) et lui parler par HTTP signé. Les vecteurs de test sont des
données JSON, hors du dossier GPL. Le plugin est mince : aucun prompt, aucun modèle, aucune logique de pointage, aucun
secret.

### Fichiers

| Fichier | Rôle |
|---|---|
| `opsys-connect.php` | En-tête (GPL-2.0-or-later, PHP 8.1, WP 6.9), chargement, crochets. |
| `includes/class-opsys-connect-signature.php` | **Classe pure** : chaîne canonique, HMAC-SHA256, vérification en temps constant (`hash_equals`), fenêtre ±300 s. |
| `includes/class-opsys-connect-approval.php` | **Classe pure** : jeton d'approbation, clé dérivée, constats ordonnés. |
| `includes/class-opsys-connect-fingerprint.php` | **Classe pure** : empreinte du contenu (`opsys-content/v1`). |
| `includes/class-opsys-connect-config.php` | Secret (constante ou option chiffrée libsodium), identifiant du site, utilisateur de service sûr. |
| `includes/class-opsys-connect-seen-store.php` | Table à usage unique : nonces, identifiants d'approbation, clés d'idempotence (clé primaire en base, expiration, purge). |
| `includes/class-opsys-connect-auth.php` | `permission_callback` de toutes les routes, dans un ordre fixe. |
| `includes/class-opsys-connect-content.php` | Brouillons : création idempotente, mise à jour, état, empreinte du contenu STOCKÉ. |
| `includes/class-opsys-connect-media.php` | Téléversement : type MIME réel, image décodable, rien d'écrit hors de la médiathèque. |
| `includes/class-opsys-connect-publisher.php` | Publication ou planification, seulement avec un jeton valide pour le contenu actuel. |
| `includes/class-opsys-connect-guard.php` | Filtre `wp_insert_post_data` : pendant une requête OPSYS, jamais `publish`/`future`/`private` sans l'autorisation du publicateur. |
| `includes/class-opsys-connect-rest.php` | Les sept routes de l'espace `opsys-connect/v1`. |
| `includes/class-opsys-connect-installer.php`, `-admin.php`, `-cli.php`, `uninstall.php` | Cycle de vie, page d'état en lecture seule (aucun formulaire), commandes WP-CLI, désinstallation propre. |
| `tests/verifier-vecteurs.php` | Rejoue les vecteurs partagés contre les trois classes pures. **Jamais exécuté.** |

### Routes (toutes `permission_callback` : Auth, jamais `__return_true`)

| Route | Rôle | Capacité WordPress de l'utilisateur de service |
|---|---|---|
| `GET /health` | version, configuration, état (sans secret) | `read` |
| `GET /types` | types de contenu et caractère gérable | `read` |
| `POST /drafts` | crée un BROUILLON (`draft`/`pending`), idempotent par clé | `edit_posts` |
| `PUT /drafts/{id}` | met à jour un brouillon (jamais un article publié, planifié, privé) | `edit_posts` |
| `POST /media` | téléverse un média (JPEG, PNG, WebP, GIF) | `upload_files` |
| `GET /posts/{id}/state` | état, empreinte vivante, empreinte publiée | `edit_posts` |
| `POST /posts/{id}/publish` | publie (`publish`) ou planifie (`future`), jeton obligatoire | `edit_posts` |

Aucune route n'accepte de paramètre de requête. Le plugin ne gère que les articles qu'il a créés (méta `_opsys_managed`).

### Signature des requêtes (`opsys-connect-sig/v1`)

Chaîne canonique (UTF-8, LF, sans LF final) : `OPSYS-CONNECT-V1`, méthode en majuscules, route REST (`/opsys-connect/v1/…`,
sans `/wp-json` ni requête), horodatage (10 chiffres), nonce (`[A-Za-z0-9_-]{16,64}`), SHA-256 du corps. Signature :
`v1=` + HMAC-SHA256 hexadécimal minuscule, avec le secret partagé en UTF-8 (32 octets au moins). En-têtes :
`X-OPSYS-Key-Id`, `X-OPSYS-Timestamp`, `X-OPSYS-Nonce`, `X-OPSYS-Signature`. Ordre des constats : en-têtes présents,
horodatage, nonce, forme de la signature, fenêtre de ±300 s, comparaison en temps constant. Le nonce est consommé APRÈS une
signature valide, par une insertion à clé primaire (deux requêtes simultanées avec le même nonce ne passent pas toutes les deux).

**Écart assumé avec R4** : R4 recommandait un appairage par clé publique ed25519. La décision d'architecte retient un HMAC avec
secret partagé (plus simple, sans dépendance, vérifiable avec `hash_hmac`). Conséquence : quiconque obtient le secret côté
site peut aussi signer des requêtes ; c'est pourquoi la **publication** ne dépend pas de ce secret seul (jeton d'approbation lié à
l'empreinte, usage unique) et pourquoi le secret est hors de la base (constante `wp-config.php` ou option chiffrée). Le passage à
ed25519 est possible sans toucher au reste : seuls `Signature` et le client changent.

### Jeton d'approbation (`opsys-approval/v1`) et empreinte du contenu

`v1.<charge utile JSON en base64url>.<MAC>`, MAC = HMAC-SHA256 de la charge utile avec une clé DÉRIVÉE du secret (HKDF-Expand à un
bloc, `opsys-connect/approval/v1`) : une signature de requête n'est jamais un jeton valide. Charge utile : `approval_id`,
`site_id`, `action` (`publish`/`schedule`), `post_id`, `content_sha256`, `iat`, `exp` (24 h au plus), `publish_at`
(planification), `approved_by`. Le plugin vérifie, dans cet ordre : forme, MAC, champs exacts, durée, expiration, émission,
site, article, **empreinte du contenu actuel**, action, planification ; puis consomme `approval_id` (une fois) ; puis seulement
change le statut, sous l'autorisation de la garde. L'heure d'une planification vient du jeton, jamais de la requête.

L'empreinte (`opsys-content/v1`) couvre type, titre, corps, extrait, adresse et image à la une, chaque champ préfixé de sa
longueur en OCTETS (un saut de ligne dans une valeur ne peut pas imiter un autre champ). C'est l'empreinte du contenu STOCKÉ
(après `wp_kses_post` et `sanitize_*`) que la direction approuve : une différence avec ce qu'OPSYS a envoyé est une
**divergence**, dite et visible (`divergence: true`), jamais cachée. Après publication, WordPress complète l'adresse : le
plugin mémorise l'empreinte VÉRIFIÉE (`empreinte_publiee`) pour que la réconciliation ne confonde pas ce changement avec une
retouche du contenu.

### Ce que le plugin interdit, et comment

| Règle | Mécanisme |
|---|---|
| Statut forcé `draft`/`pending` | validation à l'entrée (`publish`/`future`/`private` → 403 `opsys_publication_sans_jeton`), valeur littérale passée à WordPress, filtre `wp_insert_post_data` de dernier recours |
| Jamais `publish` sans jeton valide | seul `Publisher` écrit un statut public (test de contrat : aucun autre fichier) |
| Entrée assainie, sortie échappée | `sanitize_text_field`, `sanitize_textarea_field`, `sanitize_title`, `wp_kses_post`, `esc_url_raw`, `esc_html` ; données « slashées » pour `wp_insert_post` ; champs inconnus refusés |
| Aucun SQL concaténé | `$wpdb->insert`, `$wpdb->delete`, `$wpdb->prepare` avec `%i`/`%d` ; table créée par `dbDelta` |
| Aucun `eval`, aucun appel sortant, aucune écriture hors médiathèque | analyse maison (section 7) ; `wp_upload_bits` seul écrit ; extension imposée par le type MIME réel |
| Média | JPEG/PNG/WebP/GIF seulement (pas de SVG, pas de PDF), `finfo` sur les octets, `getimagesizefromstring` concordant, dimensions bornées, aucun `<?php` dans les octets, empreinte déclarée égale à l'empreinte réelle, texte alternatif obligatoire |
| Secret hors de la base | constante `OPSYS_CONNECT_SECRET` ou option chiffrée (libsodium `secretbox`, clé `OPSYS_CONNECT_KEY`), option non chargée automatiquement |
| Utilisateur de service sans pouvoir | rôle `opsys_agent` (lire, écrire des brouillons, téléverser, `opsys_connect_use`) ; refus (503) s'il porte `manage_options`, `publish_posts`, `unfiltered_html`, `install_plugins`, `edit_users`… |
| HTTPS | exigé (sauf constante de développement) |
| Désinstallation | table, rôle, option, tâche planifiée supprimés |

## 4. Modèle de menace

| Menace | Contre-mesure | Reste à craindre |
|---|---|---|
| Requête forgée sans le secret | HMAC, forme stricte, fenêtre ±300 s, comparaison en temps constant | Un secret volé permet de créer des brouillons et de lire l'état, pas de publier. |
| Rejeu d'une requête capturée | nonce à usage unique, clé primaire en base, expiration | Si la table est vidée ou perdue, les requêtes de moins de 5 minutes redeviennent rejouables. |
| Modification en route (corps, méthode, route, horodatage) | tout est dans la chaîne signée (vecteurs « corps-modifie », « route-modifiee »…) | HTTPS reste nécessaire pour la confidentialité du contenu. |
| Publication sans approbation humaine | jeton lié au site, à l'article, à l'empreinte, à l'action, usage unique, 24 h au plus ; garde de statut | Un administrateur WordPress (ou une extension) publie sans passer par le plugin : hors du modèle. |
| Contenu changé après l'approbation | empreinte du contenu stocké recalculée à la sortie ; le client relit aussi l'état du site avant d'émettre le jeton | Entre la vérification et `wp_update_post`, une modification concurrente d'un autre administrateur est théoriquement possible (fenêtre de quelques millisecondes). |
| Jeton volé | usage unique, lié à l'empreinte, expiration (1 h côté OPSYS) | Un jeton non encore utilisé, volé avant l'envoi, publie CE contenu approuvé et rien d'autre. |
| Élévation de privilèges via l'utilisateur de service | rôle minimal, refus s'il a un droit dangereux, `wp_set_current_user` après la signature seulement | Le mot de passe aléatoire est inconnu de tous, mais un administrateur peut créer un mot de passe d'application pour ce compte. |
| Téléversement hostile (polyglotte, SVG, PHP déguisé) | type réel par les octets, extension imposée, image décodable, aucun `<?php`, liste blanche | Une faille de la bibliothèque d'images de WordPress ou de GD reste possible. |
| Injection (XSS, SQL) | assainissement, échappement, requêtes préparées ; analyse maison | Jamais testé contre un vrai WordPress ni PHPCS. |
| Déni de service | corps bornés (1 Mo, 12 Mo pour un média), HTTPS, pas de paramètre de requête | Aucune limitation de débit dans le plugin : à faire au pare-feu ou chez l'hébergeur. |
| Fuite du secret | jamais en base ni dans une réponse ni dans le journal de M7 (tests) | `wp-config.php` doit rester illisible aux tiers. |
| Plugin compromis (chaîne d'approvisionnement) | GPL : le code se relit ; pas d'appel sortant ; pas de mise à jour automatique | R4 le dit : « cible n°1 des attaques WordPress ». **Revue de sécurité indépendante exigée avant toute diffusion publique.** |

## 5. Côté OPSYS

### Client signataire et vérificateurs

`wordpress/signature.py` signe ; `wordpress/jeton.py` émet les jetons ; `wordpress/empreinte.py` calcule l'empreinte. Le
**vérificateur de référence** est écrit à part, dans les tests (`tests/wordpress/reference_verificateur.py`), à partir de la
spécification seulement, sans importer ces modules. Les valeurs attendues des vecteurs sont calculées par **openssl**
(`tests/wordpress/generer_vecteurs.py`). Trois lecteurs indépendants de la spécification (OpenSSL, le client, la référence)
s'accordent sur chaque octet de 5 signatures, 31 vérifications, 38 jetons et 4 empreintes ; le quatrième lecteur, le PHP, n'a pas
été exécuté.

`ClientWordPress` ne fait aucun appel réseau : il prépare une requête signée et la remet à un **port de transport** (aucun transport
réel n'existe). Il refuse d'avance ce que le plugin refuserait (statut non brouillon, route hors de l'espace, secret court,
média vide ou sans texte alternatif), valide chaque réponse (forme, types, statut rendu : un site qui répond « publié » à une
demande de brouillon est signalé), ne cite jamais le message d'une exception de transport, et ne publie que par
`publier(ApprobationVerifiee)`.

### Registre des sites WordPress

`sites_wordpress` (append-only, chaîné) : `site_id`, adresse HTTPS (nom DNS, aucune adresse IP, aucun identifiant ni paramètre,
port 443), `secret_ref` (le NOM du secret dans le coffre, jamais sa valeur), types permis. Un site fictif a un domaine réservé
(`.example`, `.test`, `.invalid`, `.localhost`) et un site réel n'en a jamais. Un site ne se modifie pas ; il se désactive.

### Flux « brouillon → revue → approbation N3 → publication »

`brouillon` (chez OPSYS, contenu contrôlé, IA marquée) → `en_revue` (brouillon transmis au site, empreinte du SITE connue) →
`approuve` (N3, empreinte du site, `publish` ou `schedule`, 1 h) → `publie` / `echec` / `annule`. Refus typés `REJ-WP-…`
(`CONTENU-ACTIF`, `STATUT-INTERDIT`, `EMPREINTE-DIFFERENTE`, `APPROBATION-EXPIREE`, `APPROBATION-DEJA-UTILISEE`,
`CONTENU-DIVERGENT`, `JETON-…` rendus par le plugin, `PUBLICATION-SANS-JETON`, etc.). Le jeton est consigné comme ÉMIS avant
d'être envoyé : si la réponse se perd, l'approbation est brûlée (jamais deux jetons) et `reconcilier` relit le site au lieu de
renvoyer quoi que ce soit.

### Journal append-only

`journal_chaine` : chaque maillon porte le hachage du précédent et son rang. Un maillon retouché, retiré ou réordonné est refusé
(`REJ-…-JOURNAL-ALTERE`). Même si l'attaquant refait toute la chaîne, l'empreinte du contenu approuvé et le contrôle des rangs
le trahissent (tests). Limite : la chaîne protège contre l'oubli et la retouche maladroite, pas contre un administrateur de base
qui réécrirait tout ET l'approbation ET le contenu de façon cohérente ; l'ancrage externe d'une empreinte de tête est à faire.

## 6. Le sas de publication sociale

### Modèle

`Publication` : réseau, compte, texte, titre (YouTube), médias (référence, type, format, SHA-256, poids, dimensions, durée,
texte alternatif, **origine**, `ia_generee`, `realiste`, **modération**, **contrôle OCR**), instant UTC planifié, divulgation
(`texte_ia`, `media_synthetique_realiste`, `contenu_commercial`), type (`organique` | `annonce_payante`), budget (en cents),
options propres au réseau. **Empreinte** : SHA-256 d'un JSON canonique de tout cela, sauf la clé d'idempotence.

### États

`brouillon → en_attente_approbation → approuve → planifie → publie | echec | annule` ; `echec → planifie` par reprise bornée ;
`publie` et `annule` terminaux ; seule une publication en brouillon (ou en attente, qui revient alors en brouillon) se révise.
L'état est le pliage du journal ; un maillon impossible rend le journal incohérent (refus, jamais un état deviné).

### Garde-fous (tous avant l'approbation ET refaits au point de sortie)

- **Texte** : garde-fou du socle (profil de texte public de M7). Plafond effectif : le plus petit de la limite du réseau et de
  5 000 caractères (profil du socle).
- **Limites du réseau**, lues sur la CLASSE d'adaptateur : longueur, titre, mots-clics, nombre de médias, formats, poids, durée,
  mélange image/vidéo, options requises (TikTok : confidentialité choisie sans défaut, `SELF_ONLY` pour une application non
  auditée). Un test remplace la classe par une sous-classe aux limites différentes et montre que le sas suit.
- **Décision r2 n°3** : un média `origine = genere_non_compose` est refusé (`REJ-SOCIAL-MEDIA-GENERE-NON-COMPOSE`) ; une
  `composition_deterministe` exige un contrôle OCR `conforme` ; une photo de chantier ne peut pas être « générée ».
- **Modération** : un média doit être `verifiee` (visages et plaques floutés ou absents, revue humaine faite).
- **Divulgation d'IA** : `media_synthetique_realiste` est CALCULÉ des médias (`ia_generee` et `realiste`), jamais cru ; si elle est
  imposée, la publication doit la déclarer et le réseau doit offrir un champ pour la porter (sinon `DIVULGATION-IMPOSSIBLE`). Le
  texte produit par un modèle est marqué (`texte_ia`) au journal.
- **Annonces payantes** : réseau avec API publicitaire, budget présent, plafonds DURS codés (quotidien 50 $, total 1 000 $ par
  défaut, plus l'égalité montant ≤ plafond × durée).
- **Fenêtre de publication** (7 h–21 h, America/Toronto par défaut, fin exclue), **délai minimal** (5 min), **horizon** (60 jours).
- **Quota** par compte sur 24 h glissantes, exact au bord (un test par bord), calculé sur les instants PRÉVUS à la planification
  et sur les instants RÉELS de publication à la sortie ; une annulée libère sa place.

### Niveaux

N3 pour toute publication publique, **N4 pour toute annonce payante** (engagement de dépense : interprétation retenue de
« N3 obligatoire pour les annonces payantes, N4 pour engagement de dépense » : l'outil qui approuve une annonce est N4, donc
plus strict que N3). Le niveau de l'outil doit être EXACTEMENT celui que la publication exige : un N3 refuse une annonce
(`REJ-SOCIAL-NIVEAU-INSUFFISANT`), un N4 refuse une publication organique. Décideur : `nathan_owner` seulement
(`department.yaml` : `n3` et `n4`).

### Idempotence et pannes

Même clé sur le même compte et même contenu = la même publication (identifiant déterministe) ; même clé et autre contenu =
`REJ-SOCIAL-CLE-CONFLIT`. À la sortie, `tentative` est écrite AVANT l'appel au réseau ; une tentative sans résultat connu (délai
dépassé après l'envoi, processus tué) rend la publication `incertaine` : le sas demande à l'adaptateur de **retrouver** la
publication par son contenu exact avant d'envoyer quoi que ce soit. Tentatives bornées (3), une dernière reprise pour lever une
incertitude. Simulation : **1 000 publications avec pannes aléatoires (avant l'envoi, après l'envoi, définitives), graines 1 et
2 : zéro doublon sur le double de plateforme** (qui ne déduplique pas), et toute publication sortie est publiée au journal.

### Adaptateurs

`reseaux.py` déclare le PORT (`AdaptateurReseau`) et six classes de déclaration (`DeclarationGBP`, `…Facebook`, `…Instagram`,
`…LinkedIn`, `…YouTube`, `…TikTok`) qui portent les `LIMITES`. `doubles.py` : six doubles de test, sans réseau ni clé, avec
pannes injectables. **Aucun adaptateur réel n'existe** ; aucun module réseau n'est importé (test AST). Les chiffres sont ceux de
R4 (niveaux V/S/H) ou des plafonds internes prudents, tous marqués `a_verifier=True` et listés à la section 8.

### Jetons d'accès

Le jeton d'un compte sort du coffre le temps d'un appel (`secret_coffre.fournisseur_du_coffre`), est PASSÉ à l'adaptateur par
l'exécuteur, enregistré au masquage pendant l'appel (un message d'erreur qui le citerait entre masqué au journal, même s'il n'a
aucune forme reconnaissable), puis oublié. Jamais dans une requête d'adaptateur, un journal, un refus ou un résultat (tests).

## 7. Outils M7 et portées

Douze outils (aucun rôle d'appareil, voir `ROLES.md`) :

| Outil | Niveau | Rôle |
|---|---|---|
| `m7_enregistrer_site_wordpress` | T1 / **N3** | brancher un site (adresse HTTPS, nom du secret du coffre, types permis) |
| `m7_preparer_brouillon_wordpress` | T1 / N2 | préparer ou réviser un brouillon d'article ; contenu contrôlé, IA marquée ; rien n'est transmis |
| `m7_demander_publication_wordpress` | T1 / **N3** | approuver `publish` ou `schedule` pour l'empreinte du brouillon revu ; consigné, jamais exécuté |
| `m7_annuler_publication_wordpress` | T1 / N2 | retirer du flux |
| `m7_lire_publication_wordpress` | T0 | publications et sites |
| `m7_enregistrer_compte_social` | T1 / **N3** | déclarer un compte et le NOM de son jeton |
| `m7_composer_publication_sociale` | T1 / N2 | créer ou réviser un brouillon (idempotent) |
| `m7_soumettre_publication_sociale` | T1 / N2 | tous les contrôles ; passe en attente d'approbation |
| `m7_demander_publication_sociale` | T1 / **N3** | approuver une publication ORGANIQUE ; planifiée, jamais envoyée par l'outil |
| `m7_demander_annonce_payante` | T1 / **N4** | approuver une ANNONCE PAYANTE, budget compris |
| `m7_annuler_publication_sociale` | T1 / N2 | retirer de la file |
| `m7_lire_file_publication_sociale` | T0 | file, états, erreurs, comptes, intégrité du journal |

Aucun nouveau paquet de table : les quatre registres sont des journaux génériques de `opsys.stockage` (`REGISTRES`), sans
migration. Aucune commande CLI métier n'est ajoutée.

## 8. Exigences d'accès API par réseau — **à vérifier auprès de la documentation officielle**

Source : recherche R4 §3.4 et §5.2 (2026-10-31), niveaux de preuve V (vérifié), S (secondaire), H (hypothèse). **Rien ci-dessous
n'a été revérifié pour cette tranche.** Les conditions des API changent (R4 le note pour YouTube et LinkedIn) : relire la
documentation officielle avant d'écrire le premier adaptateur réel.

| Réseau | Accès à obtenir (R4) | Limites déclarées dans le sas | À vérifier d'abord |
|---|---|---|---|
| Google Business Profile | accès « Basic API Access » sur demande ; profil vérifié actif depuis 60 jours ou plus ; quota 300 QPM une fois approuvé, 0 avant (V) ; `localPosts` encore sur l'API v4 (S) | 1 500 caractères, 0 ou 1 photo (JPEG/PNG, 5 Mo), 3 publications par 24 h (**plafond interne**, aucune valeur officielle retenue) | existence et version de l'API de publications ; limites de texte et de médias ; quota réel |
| Facebook Pages | application Meta, Advanced Access pour gérer des Pages d'autrui ; Business Verification (V) ; mode B (passerelle OPSYS) pour Meta (décision r2 n°1) | 63 206 caractères, 10 images ou 1 vidéo, 25 par 24 h (**plafond interne**) | permissions et revue ; limites de médias ; champ « AI info » |
| Instagram (professionnel) | `instagram_business_content_publish` (ou Facebook Login), Advanced/Standard Access (V) ; compte professionnel | 2 200 caractères, 30 mots-clics, 1 à 10 médias, JPEG seulement pour les images, 100 par 24 h glissantes, un carrousel compte pour 1 (V) | incohérence « 50 » dans la section carrousel de la documentation officielle (V) ; formats ; durée vidéo |
| LinkedIn Pages | Community Management API, organisation légale, vérification de l'app par un super-administrateur, Development puis Standard tier avec vidéo de démonstration (V) ; `w_organization_social` ; versions mensuelles (la 202511 prend fin le 2026-11-16, V) | 3 000 caractères, jusqu'à 9 images ou 1 vidéo MP4, 25 par 24 h (**plafond interne**) | version d'API à jour ; conditions de stockage des données de membres |
| YouTube | OAuth, projet Google Cloud ; `videos.insert` = 1 unité du compartiment « Video Uploads », 100 appels par jour (V) ; la restriction « privé tant que non audité » aurait été levée pour les projets non vérifiés (V, 2026-10-31 : relire) | titre ≤ 100 caractères obligatoire, description ≤ 5 000, une vidéo, 100 par jour ; champ `containsSyntheticMedia` | audit de conformité éventuel ; limites exactes de titre et de description (octets ou caractères) |
| TikTok | scope `video.publish` (revue), puis audit ; **un client non audité ne publie qu'en `SELF_ONLY`**, 5 utilisateurs par 24 h (V) ; l'usage « outil pour téléverser vers les comptes qu'on gère » est explicitement refusé (V) : **mode B uniquement, avec audit** | 2 200 caractères, une vidéo MP4, 15 par jour par compte (V) ; confidentialité et 3 interactions choisies sans défaut | éligibilité réelle de l'usage d'OPSYS ; étiquette AIGC ; champs de divulgation de contenu commercial |

Autres plateformes évoquées par R4 (Pinterest, X, Threads, Bluesky, Mastodon) : hors de cette tranche. Postiz (AGPL) : service
séparé non modifié, derrière le même sas, non intégré.

## 9. Ce qui est prouvé, par quoi

- **Vecteurs partagés** (`tests/wordpress/test_vecteurs_partages.py`) : signatures, vérifications (bords ±300 s, LF final,
  hexadécimal en majuscules, `v2=`…), jetons (36 cas : chaque constat, domaine de clé, bourrage base64, entiers décimaux,
  dates impossibles), empreintes (Unicode, octets, faux champ dans une valeur).
- **Client contre un site simulé** (`site_simule.py`, une seconde lecture de la spécification) : statut forcé, rejeu, requête
  hors fenêtre, corps/route/méthode modifiés, autre secret, jeton expiré, jeton d'un autre site, contenu modifié après
  l'approbation, jeton réutilisé, réponse perdue puis réconciliation, divergence d'assainissement, réponses hostiles.
- **Contrat de source** (`test_plugin_source_contrat.py`) : constantes, routes, codes d'erreur, un seul fichier écrit un statut
  public, ordre des contrôles d'authentification et des constats du jeton, aucune option en clair, rôle minimal, MIME.
- **Analyse maison du PHP** (`analyse_php.py`, 111 tests) : motifs dangereux, structure, comparaison non constante des MAC.
- **Sas** : 315 tests (modèle, garde-fous, limites par classe, service, exécuteur avec pannes, simulation de 1 000 publications).
- **Outils** : 62 tests avec la vraie file d'approbation et la vraie base.

## 10. Ce qui n'est PAS prouvé

1. **Le plugin n'a jamais été exécuté dans WordPress**, ni sous PHP : `php -v` répond « commande introuvable » sur la machine de
   construction. Aucun `php -l`, aucun PHPCS (règles WordPress), aucun Plugin Check, aucun test PHPUnit, aucun essai sur un site.
   Contrôles réellement faits sur le PHP : analyse syntaxique de tous les fichiers par la **grammaire tree-sitter-php** (aucune
   erreur de syntaxe ; outil local, non reproductible en CI) ; analyse maison de motifs ; tests de contrat sur le texte. Cela ne
   détecte ni une fonction inexistante, ni une signature incorrecte, ni un comportement de WordPress différent de celui supposé
   (par exemple les filtres de `wp_kses`, `wp_update_post` sur un article planifié, le comportement de `%i` selon la version).
2. **`tests/verifier-vecteurs.php` n'a jamais tourné** : c'est la première chose à lancer sur une machine avec PHP 8.1 ou plus.
3. **Aucun appel réseau réel**, ni vers un site WordPress, ni vers une plateforme sociale. Les limites des réseaux ne sont pas
   revérifiées. Le comportement réel d'une plateforme face à une panne (publication « retrouvable » par son contenu exact ?)
   est une hypothèse du port `retrouver`.
4. **Aucun exécuteur n'est branché** à un planificateur : un brouillon n'est donc pas transmis automatiquement, une publication
   approuvée n'est pas envoyée. Les outils le disent dans leur réponse.
5. **Aucune qualité de contenu** n'est mesurée : le garde-fou de texte est un jeu de motifs, pas un jugement.
6. **Les doubles ne prouvent rien sur les vrais services** (formats réellement acceptés, quotas réels, délais).
7. **Revue de sécurité indépendante non faite** (exigée par R4 avant diffusion publique). Pas de limitation de débit dans le plugin.
8. **Juridique, à valider auprès d'un professionnel qualifié** : statut GPL du plugin et distribution privée, Loi 25 (la passerelle
   et les jetons de comptes sociaux), LCAP, divulgation de l'IA et de la publicité en langue française.

## 11. Commandes

```bash
# suites ciblées (voir le rapport de la tranche pour les résultats exacts)
pytest departments/m07-marketing/tests/wordpress departments/m07-marketing/tests/sas_social \
       departments/m07-marketing/tests/test_outils_publication.py departments/m07-marketing/tests/test_journal_chaine_et_coffre.py
# sur une machine avec PHP 8.1+ : la PREMIÈRE vérification du plugin
php integrations/wordpress/opsys-connect/tests/verifier-vecteurs.php departments/m07-marketing/contracts/opsys-connect-vecteurs.v1.json
# régénérer les vecteurs (openssl requis) : python departments/m07-marketing/tests/wordpress/generer_vecteurs.py
```
