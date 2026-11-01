# g768m-sondes — [768m] Sondes de santé, authentification, en-têtes de sécurité

- Verdict : **PASSE**
- Attendu : MCP et console répondent ; jeton exigé ; en-têtes de sécurité ; readiness 0
- Début : 2026-11-01T11:07:01.421+00:00  ·  Fin : 2026-11-01T11:07:03.271+00:00  ·  Durée : 1.85 s

## Constats

| | Constat | Détail |
|---|---|---|
| OK | MCP GET /sante = 200 + JSON ok | {"statut": 200, "corps": "{\"statut\": \"ok\", \"service\": \"opsys-metier\"}"} |
| OK | MCP POST /sante = 405 | 405 |
| OK | MCP sans jeton = 401 | 401 |
| OK | MCP mauvais jeton = 401 | 401 |
| OK | MCP bon jeton : initialize accepté (200) | 200 |
| OK | console GET /connexion = 200 | 200 |
| OK | console : en-têtes de sécurité (nosniff, DENY, no-referrer, no-store) | {"manquants": {}, "csp": "default-src 'none'; style-src 'self'; script-src 'self'; img-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"} |
| OK | console 404 sans trace d'exécution | 404 |
| OK | console /departements sans session : redirigé vers la connexion | {"statut": 303, "location": "/connexion"} |
| OK | readiness.py = 0 (prêt) | {"code": 0, "stdout": "ready migrations: 0040\nready configuration: paliers et fragments présents\nready secrets: variables requises présentes\nready mémoire: configuration embeddings et fragment cohérents\nready console: /connexion HTTP 200\n", "stderr": ""} |
| OK | console : mauvais identifiant : pas de session (aucun Set-Cookie de session) | {"statut": 401} |
| OK | console : bon identifiant : redirection (303) avec cookie de session | {"statut": 303} |
| OK | console : cookie de session : HttpOnly, Secure, SameSite | [] |
| OK | console : page protégée avec le cookie : 200 | 200 |
| OK | console : page protégée sans cookie : redirigée | 303 |
| OK | console : page protégée : en-têtes de sécurité présents | ["cache-control", "content-length", "content-security-policy", "content-type", "date", "referrer-policy", "server", "x-content-type-options", "x-frame-options"] |

## Commandes (code de sortie réel)

| Code | Durée (s) | Commande |
|---|---|---|
| 0 | 1.14 | `docker exec qb46c83f-g768m-s1 /opt/opsys-venv/bin/python /opt/opsys/install/qualification/interne.py sondes` |
| 0 | 0.71 | `docker exec qb46c83f-g768m-s1 /opt/opsys-venv/bin/python /opt/opsys/install/qualification/interne.py connexion` |

