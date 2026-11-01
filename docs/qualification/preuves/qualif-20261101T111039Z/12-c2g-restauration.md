# c2g-restauration — [2g] RESTAURATION sur un conteneur neuf à partir de la seule sauvegarde chiffrée et de la clé

- Verdict : **PASSE**
- Attendu : restauration réussie (code 0), services démarrés, prêts, connexion avec le mot de passe d'origine
- Début : 2026-11-01T11:12:18.202+00:00  ·  Fin : 2026-11-01T11:12:28.572+00:00  ·  Durée : 10.37 s

## Constats

| | Constat | Détail |
|---|---|---|
| OK | restauration chiffrée : code 0 | "ok" |
| OK | services prêts (readiness 0) sur les données restaurées | [1, 1, 0] |
| OK | restauré : mauvais identifiant : pas de session (aucun Set-Cookie de session) | {"statut": 401} |
| OK | restauré : bon identifiant : redirection (303) avec cookie de session | {"statut": 303} |
| OK | restauré : cookie de session : HttpOnly, Secure, SameSite | [] |
| OK | restauré : page protégée avec le cookie : 200 | 200 |
| OK | restauré : page protégée sans cookie : redirigée | 303 |
| OK | restauré : page protégée : en-têtes de sécurité présents | ["cache-control", "content-length", "content-security-policy", "content-type", "date", "referrer-policy", "server", "x-content-type-options", "x-frame-options"] |
| OK | restauré : MCP GET /sante = 200 + JSON ok | {"statut": 200, "corps": "{\"statut\": \"ok\", \"service\": \"opsys-metier\"}"} |
| OK | restauré : MCP POST /sante = 405 | 405 |
| OK | restauré : MCP sans jeton = 401 | 401 |
| OK | restauré : MCP mauvais jeton = 401 | 401 |
| OK | restauré : MCP bon jeton : initialize accepté (200) | 200 |
| OK | restauré : console GET /connexion = 200 | 200 |
| OK | restauré : console : en-têtes de sécurité (nosniff, DENY, no-referrer, no-store) | {"manquants": {}, "csp": "default-src 'none'; style-src 'self'; script-src 'self'; img-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"} |
| OK | restauré : console 404 sans trace d'exécution | 404 |
| OK | restauré : console /departements sans session : redirigé vers la connexion | {"statut": 303, "location": "/connexion"} |
| OK | restauré : readiness.py = 0 (prêt) | {"code": 0, "stdout": "ready migrations: 0040\nready configuration: paliers et fragments présents\nready secrets: variables requises présentes\nready mémoire: configuration embeddings et fragment cohérents\nready console: /connexion HTTP 200\n", "stderr": ""} |

## Mesures

```json
{
  "restauration": {
    "duree_s": 0.88,
    "rss_max_enfant_mo": 69.5,
    "cgroup_pic_mo": 79.0
  },
  "temps_jusqu_a_pret_apres_restauration_s": 7.0
}
```

## Commandes (code de sortie réel)

| Code | Durée (s) | Commande |
|---|---|---|
| 0 | 0.01 | `docker volume create --label opsys.banc=qualif-20261101T111039Z qbd2db04-c2gr-data` |
| 0 | 0.02 | `docker volume create --label opsys.banc=qualif-20261101T111039Z qbd2db04-c2gr-cfg` |
| 0 | 1.5 | `docker run --rm --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 2g --memory-swap 2g --label opsys.banc=qualif-20261101` |
| 0 | 0.23 | `docker run -d --init --name qbd2db04-c2g-s2 --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 2g --memory-swap 2g --labe` |
| 0 | 6.77 | `readiness.py en boucle sur qbd2db04-c2g-s2` |
| 0 | 0.71 | `docker exec qbd2db04-c2g-s2 /opt/opsys-venv/bin/python /opt/opsys/install/qualification/interne.py connexion` |
| 0 | 1.13 | `docker exec qbd2db04-c2g-s2 /opt/opsys-venv/bin/python /opt/opsys/install/qualification/interne.py sondes` |

