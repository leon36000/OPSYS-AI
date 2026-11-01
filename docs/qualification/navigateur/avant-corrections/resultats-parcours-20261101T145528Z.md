# Résultats du banc navigateur — parcours — 20261101T145528Z

- Verdict : **ECHEC**
- Navigateur : chromium 156.0.8078.4 (Playwright 1.64.1, headless)
- Durée : 106.7 s ; captures : 1631 Ko

| Groupe | Constat | Verdict | Niveau |
|---|---|---|---|
| connexion | page de connexion : h1, lang=fr, deux champs étiquetés, mot de passe masqué | OK | bloquant |
| connexion | formulaire vide : le navigateur bloque, aucun POST envoyé | OK | bloquant |
| connexion | mauvais mot de passe : 401 et message en français, aucun cookie de session | OK | bloquant |
| connexion | le message d'échec est annoncé aux technologies d'assistance (role=alert) | **ÉCHEC** | bloquant |
| connexion | le mot de passe saisi n'est jamais réaffiché ni renvoyé | OK | bloquant |
| connexion | 12 échecs de suite : chaque essai reste refusé (401) | OK | bloquant |
| connexion | après 12 échecs, le bon mot de passe est ENCORE accepté : aucun verrouillage applicatif (la limitation relève de fail2ban en production, NON PROUVÉE ici) | OK | info |
| connexion | cookie de session : HttpOnly, Secure, SameSite=Strict, chemin /opsys, ~8 h | OK | bloquant |
| connexion | le cookie de session est invisible pour le JavaScript de la page (HttpOnly effectif) | OK | bloquant |
| connexion | l'en-tête Set-Cookie brut porte HttpOnly, Secure et SameSite=Strict | OK | bloquant |
| connexion | GET /connexion quand on est connecté : renvoie au tableau de bord | OK | bloquant |
| tableau-de-bord | tableau de bord : h1, 17 onglets, onglet courant, une carte par département (10 réels + 1 fictif) | OK | bloquant |
| tableau-de-bord | la pastille d'approbations annonce les 4 demandes en attente | OK | bloquant |
| tableau-de-bord | la personne connectée est nommée | OK | bloquant |
| approbations | la file « En attente » montre les 4 demandes N3 avec leurs arguments exacts | OK | bloquant |
| approbations | la boîte de confirmation du navigateur, rejetée, n'exécute rien | OK | bloquant |
| approbations | approuver (après confirmation) exécute l'outil UNE fois : une ligne dans le fichier d'effets fictif | OK | bloquant |
| approbations | la demande apparaît dans « Exécutées » avec le statut Exécutée et le nom du signataire | OK | bloquant |
| approbations | refuser n'exécute rien (aucune ligne d'effet de plus) | OK | bloquant |
| approbations | double soumission simultanée d'une approbation : exécutée UNE seule fois | OK | bloquant |
| approbations | après trois décisions, une seule demande reste en attente (la quatrième, jamais décidée) | OK | bloquant |
| approbations | un employé ne voit pas la file : 403 | OK | bloquant |
| approbations | le refus 403 d'une page est une page HTML lisible (titre, lien de retour), pas du JSON brut | **ÉCHEC** | bloquant |
| plateforme | registre de fournisseurs : tableau rempli, « à mesurer », profil client absent annoncé | OK | bloquant |
| plateforme | les cinq pages Plateforme portent la même navigation nommée (5 sections, page courante marquée) : aucune impasse | **ÉCHEC** | bloquant |
| plateforme | le profil de licence s'enregistre (bandeau de succès) | OK | bloquant |
| plateforme | activer un fournisseur à licence non commerciale est refusé, code lisible, rien d'autre activé | OK | bloquant |
| plateforme | le champ de valeur d'un secret est de type password | OK | bloquant |
| plateforme | un secret saisi : bandeau « chiffré, ne sera plus affiché », une ligne de métadonnées, redirection sans la valeur | OK | bloquant |
| plateforme | la valeur du secret n'apparaît ni dans le DOM, ni dans les champs, ni dans l'URL, ni dans le stockage du navigateur | OK | bloquant |
| plateforme | l'API JSON des secrets ne porte pas la valeur | OK | bloquant |
| plateforme | la lecture directe de la valeur d'un secret est refusée à la console (aucune route de lecture en clair) | OK | bloquant |
| plateforme | page « Plateforme — avatars » : 200, titre, contenu rendu | OK | bloquant |
| plateforme | page « Plateforme — connaissances » : 200, titre, contenu rendu | OK | bloquant |
| plateforme | page « Plateforme — connecteurs » : 200, titre, contenu rendu | OK | bloquant |
| plateforme | page « Connecteurs » : 200, titre, contenu rendu | OK | bloquant |
| plateforme | page « Observabilité — coût et latence » : 200, titre, contenu rendu | OK | bloquant |
| plateforme | les avatars listent un département par ligne (10 réels + 1 fictif) avec voix/visage logiques | OK | bloquant |
| plateforme | révoquer un secret : confirmation explicite requise puis bandeau « octets chiffrés détruits » | OK | bloquant |
| plateforme | aucune requête hors 127.0.0.1 pendant le groupe | OK | bloquant |
| plateforme | la valeur du secret n'apparaît dans AUCUNE réponse, URL, redirection ni message de console reçus par le navigateur | OK | bloquant |
| wallboards | liste des wallboards : deux tableaux, lien de chaque ligne | OK | bloquant |
| wallboards | rendu serveur initial sans JS : bannière et tuiles présentes | OK | bloquant |
| wallboards | le flux SSE s'ouvre (mention « Connecté (flux) ») | **ÉCHEC** | bloquant |
| wallboards | le serveur pousse l'état « périmé » par SSE : tuiles périmées SANS rechargement (même document) | **ÉCHEC** | bloquant |
| wallboards | une mesure périmée est écrite en toutes lettres et la bannière n'est plus « ok » | **ÉCHEC** | bloquant |
| wallboards | le bouton de pause bascule aria-pressed (WCAG 2.2.2) | OK | bloquant |
| wallboards | en pause, l'écran ne se rafraîchit plus (les tuiles périmées restent affichées) | **ÉCHEC** | bloquant |
| wallboards | à la reprise, l'état revient à « à jour » par le flux | OK | bloquant |
| wallboards | le mode télé s'affiche (classe tv, lien « Quitter ») | OK | bloquant |
| wallboards | réseau coupé : la page affiche « Connexion perdue », marque toutes les tuiles et dit de ne pas s'y fier | OK | bloquant |
| wallboards | le propriétaire sans rôle admin reçoit 403 sur les wallboards (page HTML lisible) | **ÉCHEC** | bloquant |
| registre-cron | un agent se crée par le formulaire (révision 1, inactif) et sa page de détail s'ouvre | OK | bloquant |
| registre-cron | le profil s'active (le bouton devient « Désactiver ») | OK | bloquant |
| registre-cron | le formulaire de demande cron est proposé (déclencheur horaire déclaré) | OK | bloquant |
| registre-cron | sans la case de confirmation, le navigateur refuse l'envoi | OK | bloquant |
| registre-cron | le message de succès est stylé (fond visible, pas un paragraphe nu) | **ÉCHEC** | bloquant |
| registre-cron | la demande cron est préparée INERTE : « Aucune tâche Core n'a été créée ou exécutée » | OK | bloquant |
| deconnexion | la déconnexion efface le cookie de session et renvoie à la connexion | OK | bloquant |
| deconnexion | retour arrière puis rechargement : page protégée refusée (redirigée vers la connexion), rien de mis en cache | OK | bloquant |
| deconnexion | OBSERVÉ : un cookie copié avant la déconnexion est ENCORE accepté après (session sans état côté serveur, échéance 8 h) : limite à lever par une liste de révocation, hors périmètre de ce banc | OK | info |
| journal | console servie sans préfixe (comme derrière Caddy) : un échec de connexion est refusé en 401 (la ligne d'accès est contrôlée contre le filtre fail2ban par lancer.py) | OK | bloquant |
| expiration | instance à session courte : le cookie expire dans quelques secondes | OK | bloquant |
| expiration | cookie périmé : la page protégée renvoie à la connexion | OK | bloquant |
| expiration | cookie echu-signe : page renvoyée à la connexion et API en 401 | OK | bloquant |
| expiration | cookie falsifie : page renvoyée à la connexion et API en 401 | OK | bloquant |
| csrf | POST /deconnexion sans jeton : 403, page « Action refusée », la session reste ouverte | OK | bloquant |
| csrf | POST avec un jeton CSRF faux : 403 | OK | bloquant |
| csrf | décision d'approbation sans jeton : 403 | OK | bloquant |
| csrf | enregistrement d'un secret sans jeton : 403 et valeur non réécho | OK | bloquant |
| csrf | écriture de l'API JSON sans en-tête X-CSRF-Token : 403 (jeton faux aussi) | OK | bloquant |
| csrf | après ces refus, la session reste valide et le jeton inchangé | OK | bloquant |
| csrf | formulaire soumis depuis un AUTRE SITE avec le bon jeton : le navigateur n'envoie PAS le cookie (SameSite=Strict) et la session survit | OK | bloquant |
| entetes-securite | 10 pages : CSP stricte, nosniff, X-Frame-Options DENY, Referrer-Policy no-referrer, Cache-Control no-store | OK | bloquant |
| entetes-securite | ressource statique : mêmes en-têtes de sécurité, cache public borné d'une heure | OK | bloquant |
| entetes-securite | page inconnue : 404 sans trace d'exécution ni chemin de fichier | OK | bloquant |
| entetes-securite | ni /docs ni /openapi.json (schéma non exposé) | OK | bloquant |
| entetes-securite | la CSP bloque réellement un script injecté en ligne et une image externe (violation consignée par le navigateur) | OK | bloquant |
| entetes-securite | la console ne s'affiche pas dans un cadre d'un autre site (frame-ancestors 'none' / X-Frame-Options) | OK | bloquant |
| entetes-securite | aucune violation de CSP sur le parcours normal des 10 pages (hors l'injection volontaire) | OK | bloquant |
| accessibilite | règle « lang-fr » sur 21 pages × 3 largeurs × 2 thèmes | OK | bloquant |
| accessibilite | règle « titre-page » sur 21 pages × 3 largeurs × 2 thèmes | OK | bloquant |
| accessibilite | règle « un-seul-h1 » sur 21 pages × 3 largeurs × 2 thèmes | **ÉCHEC** | bloquant |
| accessibilite | règle « titres-sans-saut » sur 21 pages × 3 largeurs × 2 thèmes | OK | bloquant |
| accessibilite | règle « repere-main » sur 21 pages × 3 largeurs × 2 thèmes | OK | bloquant |
| accessibilite | règle « reperes-nav-nommes » sur 21 pages × 3 largeurs × 2 thèmes | OK | bloquant |
| accessibilite | règle « contenu-dans-reperes » sur 21 pages × 3 largeurs × 2 thèmes | OK | bloquant |
| accessibilite | règle « ids-uniques » sur 21 pages × 3 largeurs × 2 thèmes | OK | bloquant |
| accessibilite | règle « champs-etiquetes » sur 21 pages × 3 largeurs × 2 thèmes | OK | bloquant |
| accessibilite | règle « autocomplete-mot-de-passe » sur 21 pages × 3 largeurs × 2 thèmes | OK | bloquant |
| accessibilite | règle « boutons-nommes » sur 21 pages × 3 largeurs × 2 thèmes | OK | bloquant |
| accessibilite | règle « liens-nommes » sur 21 pages × 3 largeurs × 2 thèmes | OK | bloquant |
| accessibilite | règle « images-alt » sur 21 pages × 3 largeurs × 2 thèmes | OK | bloquant |
| accessibilite | règle « tables-entetes » sur 21 pages × 3 largeurs × 2 thèmes | OK | bloquant |
| accessibilite | règle « th-avec-scope » sur 21 pages × 3 largeurs × 2 thèmes | OK | bloquant |
| accessibilite | règle « pas-de-tabindex-positif » sur 21 pages × 3 largeurs × 2 thèmes | OK | bloquant |
| accessibilite | règle « erreurs-annoncees » sur 21 pages × 3 largeurs × 2 thèmes | OK | bloquant |
| accessibilite | règle « zoom-non-bloque » sur 21 pages × 3 largeurs × 2 thèmes | OK | bloquant |
| accessibilite | règle « references-aria-valides » sur 21 pages × 3 largeurs × 2 thèmes | OK | bloquant |
| accessibilite | règle « aucun-script-ni-style-en-ligne » sur 21 pages × 3 largeurs × 2 thèmes | OK | bloquant |
| accessibilite | règle « contraste-texte » sur 21 pages × 3 largeurs × 2 thèmes | **ÉCHEC** | bloquant |
| accessibilite | règle « cases-a-cocher-taille » sur 21 pages × 3 largeurs × 2 thèmes | **ÉCHEC** | bloquant |
| accessibilite | aucun défilement horizontal de la PAGE à 375, 768 et 1280 px (1.4.10) sur 21 pages | **ÉCHEC** | bloquant |
| accessibilite | contraste minimal mesuré clair / sombre (texte) | OK | info |
| clavier | connexion : Tab visite le lien d'évitement, l'identifiant, le mot de passe puis le bouton, dans cet ordre | **ÉCHEC** | bloquant |
| clavier | connexion : chaque élément focalisé a un indicateur de focus visible (contour ou ombre) | OK | bloquant |
| clavier | la connexion se soumet au clavier (Entrée dans le champ mot de passe) | OK | bloquant |
| clavier | departements : 94 arrêts de tabulation, ordre = ordre du document, aucun piège (retour au début atteint) | OK | bloquant |
| clavier | departements : focus visible sur chaque arrêt, contraste du contour ≥ 3:1 | OK | bloquant |
| clavier | approbations : 26 arrêts de tabulation, ordre = ordre du document, aucun piège (retour au début atteint) | OK | bloquant |
| clavier | approbations : focus visible sur chaque arrêt, contraste du contour ≥ 3:1 | OK | bloquant |
| clavier | plateforme/secrets : 32 arrêts de tabulation, ordre = ordre du document, aucun piège (retour au début atteint) | OK | bloquant |
| clavier | plateforme/secrets : focus visible sur chaque arrêt, contraste du contour ≥ 3:1 | OK | bloquant |
| clavier | plateforme/fournisseurs : 106 arrêts de tabulation, ordre = ordre du document, aucun piège (retour au début atteint) | OK | bloquant |
| clavier | plateforme/fournisseurs : focus visible sur chaque arrêt, contraste du contour ≥ 3:1 | OK | bloquant |
| clavier | un lien d'évitement (« Aller au contenu ») est le premier arrêt de tabulation | **ÉCHEC** | bloquant |
| clavier | changement de mode d'autonomie : sélection au clavier puis Entrée déclenche la confirmation, qu'on peut refuser | OK | bloquant |
| responsive | à 375 px : pas de défilement horizontal de la page, navigation dans l'écran (6 pages) | **ÉCHEC** | bloquant |
| responsive | à 768 px : pas de défilement horizontal de la page, navigation dans l'écran (6 pages) | **ÉCHEC** | bloquant |
| responsive | à 1280 px : pas de défilement horizontal de la page, navigation dans l'écran (6 pages) | OK | bloquant |
| responsive | à 320 px (équivalent d'un zoom 400 %, 1.4.10) : pas de défilement horizontal de la page | **ÉCHEC** | bloquant |
| global | aucune requête n'a quitté 127.0.0.1 (le banc refuse tout le reste) | OK | bloquant |
| global | taille totale des captures de cette exécution < 3 Mo | OK | info |
| serveur | journaux du serveur : aucune trace du mot de passe d'une personne | OK | bloquant |
| serveur | journaux du serveur : aucune trace du secret de session | OK | bloquant |
| serveur | journaux du serveur : aucune trace du valeur du secret saisi | OK | bloquant |
| serveur | base de données : la valeur du secret n'y est PAS en clair (chiffrée au repos) | OK | bloquant |
| serveur | base de données : aucun mot de passe en clair (empreintes scrypt) | OK | bloquant |
| serveur | journaux du serveur : aucune trace d'exécution (Traceback) ni erreur 500 | OK | bloquant |
| serveur | fichier d'effets : exactement la demande approuvée et celle de la double soumission (une fois chacune) ; la refusée n'a rien produit | OK | bloquant |
| serveur | filtre fail2ban de production : reconnaît une ligne RÉELLE d'échec de connexion émise par le serveur (console sans préfixe) | OK | bloquant |
