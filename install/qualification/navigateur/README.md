# Banc de parcours navigateur de la console OPSYS

Rejoue les parcours du propriétaire et de l'administrateur dans un **vrai navigateur** (Chromium piloté par `playwright-core`)
sur une **instance fictive** de la console. Répétable, sans réseau, sans donnée réelle. Rapport :
[`docs/qualification/QUALIFICATION-NAVIGATEUR.md`](../../../docs/qualification/QUALIFICATION-NAVIGATEUR.md) ; preuves horodatées et
captures : [`docs/qualification/navigateur/`](../../../docs/qualification/navigateur/).

## Ce que fait le banc

1. `instance.py` monte une instance jetable : base SQLite temporaire, trois personnes fictives (`proprio-fictif`,
   `admin-fictif`, `employe-fictif`) dont les mots de passe sont **générés à l'exécution** (fichier 0600 dans le dossier jetable),
   clé du coffre et secret de console générés, les **vrais départements** (`departments/`) plus un département FICTIF
   (`departement_fictif/m09-qualif`, un seul outil N3 dont l'effet est une ligne dans un fichier local), des faits fictifs de M8
   pour les wallboards, quatre demandes N3 en attente. Serveur : uvicorn, `127.0.0.1` seulement.
2. `lancer.py` démarre trois instances (principale ; à session de 5 s ; sans préfixe d'URL comme derrière Caddy), lance
   `parcours.js`, puis contrôle côté serveur ce que le navigateur ne voit pas (journaux, base, fichier d'effets, filtre fail2ban).
3. `parcours.js` joue 13 groupes de parcours : `connexion`, `tableau`, `approbations`, `plateforme`, `wallboards`, `cron`,
   `deconnexion`, `journal`, `expiration`, `csrf`, `entetes`, `a11y`, `clavier`, `responsive`. Toute requête hors `127.0.0.1` est
   refusée par le banc et comptée (la CSP est laissée intacte : les contrôles s'injectent par CDP, jamais par une balise `script`).
4. `controles_a11y.js` : règles WCAG 2.1 AA **maison** (axe-core n'est pas disponible hors ligne) ; liste exacte de ce qu'elles
   ne couvrent pas en tête du fichier.
5. `injections.py` : défauts simulés dans le processus de l'instance (CSRF retiré, cookie sans HttpOnly, secret affiché, étiquette
   retirée, CSP affaiblie, focus retiré…) pour vérifier que le banc les voit. `mutations_sources.py` : même idée côté sources.

## Exécution

```bash
# venv du dépôt ; PYTHONPATH = src + departments/*/src ; HOME et TMPDIR privés recommandés
python install/qualification/navigateur/lancer.py verifier              # moyens disponibles (code 3 s'il en manque)
python install/qualification/navigateur/lancer.py parcours              # tout le banc, preuves dans docs/qualification/navigateur/
python install/qualification/navigateur/lancer.py parcours --groupes csrf,entetes
python install/qualification/navigateur/lancer.py parcours --moteur firefox --groupes connexion,csrf
python install/qualification/navigateur/lancer.py mutations             # rejoue les groupes concernés contre chaque injection
python install/qualification/navigateur/mutations_sources.py            # mutations de source (ne pas lancer en parallèle)
```

Prérequis : `node` ≥ 20 ; `playwright-core` (variable `OPSYS_PLAYWRIGHT_CORE` = dossier du paquet, sinon recherche dans des
`node_modules` voisins) ; un Chromium (`OPSYS_CHROMIUM`, `PLAYWRIGHT_BROWSERS_PATH`, `~/.cache/ms-playwright`, `/opt/pw-browsers`).
**Rien n'est installé par le banc.** Sans navigateur utilisable il écrit « prêt mais NON EXÉCUTÉ », liste ce qui manque et sort en
code 3 ; il n'invente aucun verdict. Chromium plante si `TMPDIR` dépasse ~100 caractères (socket Unix) : le banc utilise un
dossier court pour le navigateur.

Sorties (jamais écrasées : un horodatage par exécution) : `resultats-<étiquette>-<horodatage>.json` et `.md`, captures PNG
`<horodatage>-NN-<nom>.png`, `journal-<étiquette>-<horodatage>.txt`. Niveaux : « bloquant » (un échec fait échouer le banc) et
« info » (fait observé, consigné sans verdict : limites connues).

## Accommodements du banc (dits, aucun ne touche une garde de sécurité)

- l'horloge des wallboards est lue dans un fichier (pour faire « vieillir » les mesures sans attendre) ; le délai entre deux envois
  SSE passe à 1 s (le contrat 5–3600 s de M8 reste celui de la définition) ;
- le cookie `Secure` est conservé ; Chromium l'accepte sur `http://127.0.0.1` ;
- les doubles soumissions et les écritures sans jeton passent par le contexte de requêtes de Playwright (même jar de cookies), car la
  CSP de la console interdit — à raison — le `fetch` depuis une page hors wallboards.

## Ce que le banc ne prouve pas

Voir « NON PROUVÉ » dans le rapport : autres navigateurs (Firefox : extrait seulement ; WebKit/Safari : non), lecteur d'écran réel,
mobile natif et tactile, TLS/HSTS/Caddy, limitation de débit réelle (fail2ban), session multi-onglets, charge.
