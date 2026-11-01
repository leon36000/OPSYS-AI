# c4g-empreinte-avant — [4g] Empreintes et comptages AVANT sauvegarde

- Verdict : **PASSE**
- Attendu : base saine (integrity_check), empreinte par table stable entre deux lectures
- Début : 2026-11-01T10:53:40.486+00:00  ·  Fin : 2026-11-01T10:53:42.051+00:00  ·  Durée : 1.56 s

## Constats

| | Constat | Détail |
|---|---|---|
| OK | deux lectures successives identiques (instance au repos) | "5c6dcc8e8a3ce9b1" |
| OK | integrity_check = ok |  |

## Mesures

```json
{
  "resume": {
    "revision": "0040",
    "integrity_check": true,
    "tables": 86,
    "lignes_total": 109,
    "sha256_global": "5c6dcc8e8a3ce9b1ce34c4ab43c7e4279ea724db8b19af9d8a0a15d63b4e8b9c"
  }
}
```

## Commandes (code de sortie réel)

| Code | Durée (s) | Commande |
|---|---|---|
| 0 | 0.28 | `docker exec qb987e29-c4g-s1 /opt/opsys-venv/bin/python /opt/opsys/install/qualification/interne.py empreinte` |
| 0 | 0.28 | `docker exec qb987e29-c4g-s1 /opt/opsys-venv/bin/python /opt/opsys/install/qualification/interne.py empreinte` |

