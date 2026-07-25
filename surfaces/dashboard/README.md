# Dashboard OPSYS-AI — P0-5a

Squelette de tableau de bord HTTP pour le pilotage des modules OPSYS-AI.

## Lancer le serveur

```bash
python3 src/dashboard_server.py [port]
```

Sans argument, un port éphémère est choisi.

## Endpoints

- `GET /` — page HTML française (`lang="fr"`) listant les modules et le mode actuel.
- `GET /health` — JSON `{status, mode, mode_source, modules_lisibles, nb_modules, ts}`.

## Mode

Priorité : variable d'environnement `OPSYS_MODE` > `config.yaml` > `horaire`.  
Valeurs admises : `horaire`, `temps-reel`.

## Tests

```bash
python3 -m pytest surfaces/dashboard/tests -q
```

## Accessibilité

- HTML sémantique (`<header>`, `<main>`, `<footer>`, `<h1>`, `<th scope="col">`).
- Contraste AA via CSS inline.
- Aucun JavaScript.

## Suites

- P0-5b : enrichissement du contenu et styles.
- P0-5c : intégration des métriques.
- P0-5d : tests de charge.
