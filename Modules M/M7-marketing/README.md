# M7-marketing

Marketing & Croissance IA — PREMIER MODULE (D-008)

Statut: PILOTE (M7-S000 — mode ombre)

## M7-S000 — Brand Core minimal

Le fichier `src/brand/profile.yaml` est un **GABARIT initial** ; les valeurs proposées
(name, tagline, tone, colors, langue) sont à faire valider par Nathan.

### Endpoint

`GET /brand`

- **200** — `application/json; charset=utf-8` : le profil validé et normalisé.
- **500** — `application/problem+json` (RFC 9457) : profil invalide, YAML malformé,
  ou tag YAML interdit. Le `detail` ne contient jamais le chemin disque du fichier.
- **404** — `application/problem+json` : chemin inconnu ou `/brand/`.
- **405** — `application/problem+json` : méthode non autorisée ; l'en-tête
  `Allow: GET` est renvoyé.
- Les champs inconnus du profil sont tolérés SEULEMENT s'ils sont JSON-sérialisables
  (sinon 500).
- Les query strings sont ignorées sur `/brand`.

### Lancement manuel

```bash
python3 brand_server.py [port]
```

Le serveur se bind sur `127.0.0.1` et affiche le `host:port` réel.

### Tests

```bash
python3 -m pytest "Modules M/M7-marketing/tests" -q
```
