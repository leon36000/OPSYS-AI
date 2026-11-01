# c4g-empreinte-avant — [4g] Empreintes et comptages AVANT sauvegarde

- Verdict : **PASSE**
- Attendu : base saine (integrity_check), empreinte par table stable entre deux lectures
- Début : 2026-11-01T11:01:56.555+00:00  ·  Fin : 2026-11-01T11:01:58.154+00:00  ·  Durée : 1.6 s

## Constats

| | Constat | Détail |
|---|---|---|
| OK | deux lectures successives identiques (instance au repos) | "7e5135037c5b6fa1" |
| OK | integrity_check = ok |  |

## Mesures

```json
{
  "resume": {
    "revision": "0040",
    "integrity_check": true,
    "tables": 86,
    "lignes_total": 109,
    "sha256_global": "7e5135037c5b6fa1071b580239b9976a95feb01c109535f1f86de3028432e21c"
  },
  "taille_des_donnees_ko": {
    "/opt/data": 1604,
    "/openclaw-config": 748,
    "/sauvegardes": 4
  }
}
```

## Commandes (code de sortie réel)

| Code | Durée (s) | Commande |
|---|---|---|
| 0 | 0.28 | `docker exec qb46c83f-c4g-s1 /opt/opsys-venv/bin/python /opt/opsys/install/qualification/interne.py empreinte` |
| 0 | 0.27 | `docker exec qb46c83f-c4g-s1 /opt/opsys-venv/bin/python /opt/opsys/install/qualification/interne.py empreinte` |
| 0 | 0.05 | `docker exec qb46c83f-c4g-s1 du -sk /opt/data /openclaw-config /sauvegardes` |

