# Résultats du banc navigateur — parcours-firefox — 20261101T150912Z

- Verdict : **PASSE**
- Navigateur : firefox 151.0 (Playwright 1.64.1, headless)
- Durée : 31.9 s ; captures : 753 Ko

| Groupe | Constat | Verdict | Niveau |
|---|---|---|---|
| connexion | page de connexion : h1, lang=fr, deux champs étiquetés, mot de passe masqué | OK | bloquant |
| connexion | formulaire vide : le navigateur bloque, aucun POST envoyé | OK | bloquant |
| connexion | mauvais mot de passe : 401 et message en français, aucun cookie de session | OK | bloquant |
| connexion | le message d'échec est annoncé aux technologies d'assistance (role=alert) | OK | bloquant |
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
| wallboards | liste des wallboards : deux tableaux, lien de chaque ligne | OK | bloquant |
| wallboards | rendu serveur initial sans JS : bannière et tuiles présentes | OK | bloquant |
| wallboards | le flux SSE s'ouvre (mention « Connecté (flux) ») | OK | bloquant |
| wallboards | le serveur pousse l'état « périmé » par SSE : tuiles périmées SANS rechargement (même document) | OK | bloquant |
| wallboards | une mesure périmée est écrite en toutes lettres et la bannière n'est plus « ok » | OK | bloquant |
| wallboards | le bouton de pause bascule aria-pressed (WCAG 2.2.2) | OK | bloquant |
| wallboards | en pause, l'écran ne se rafraîchit plus (les tuiles périmées restent affichées) | OK | bloquant |
| wallboards | à la reprise, l'état revient à « à jour » par le flux | OK | bloquant |
| wallboards | le mode télé s'affiche (classe tv, lien « Quitter ») | OK | bloquant |
| wallboards | réseau coupé : la page affiche « Connexion perdue », marque toutes les tuiles et dit de ne pas s'y fier | OK | bloquant |
| wallboards | le propriétaire sans rôle admin reçoit 403 sur les wallboards (page HTML lisible) | OK | bloquant |
| responsive | à 375 px : pas de défilement horizontal de la page, navigation dans l'écran (6 pages) | OK | bloquant |
| responsive | à 768 px : pas de défilement horizontal de la page, navigation dans l'écran (6 pages) | OK | bloquant |
| responsive | à 1280 px : pas de défilement horizontal de la page, navigation dans l'écran (6 pages) | OK | bloquant |
| responsive | à 320 px (équivalent d'un zoom 400 %, 1.4.10) : pas de défilement horizontal de la page | OK | bloquant |
| global | aucune requête n'a quitté 127.0.0.1 (le banc refuse tout le reste) | OK | bloquant |
| global | taille totale des captures de cette exécution < 3 Mo | OK | info |
