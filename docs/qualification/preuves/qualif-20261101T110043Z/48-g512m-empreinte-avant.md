# g512m-empreinte-avant — [512m] Empreintes et comptages AVANT sauvegarde

- Verdict : **PASSE**
- Attendu : base saine (integrity_check), empreinte par table stable entre deux lectures
- Début : 2026-11-01T11:08:03.857+00:00  ·  Fin : 2026-11-01T11:08:05.448+00:00  ·  Durée : 1.59 s

## Constats

| | Constat | Détail |
|---|---|---|
| OK | deux lectures successives identiques (instance au repos) | "b982473eb2718fd0" |
| OK | integrity_check = ok |  |

## Mesures

```json
{
  "resume": {
    "revision": "0040",
    "integrity_check": true,
    "tables": 86,
    "lignes_total": 109,
    "sha256_global": "b982473eb2718fd0f696aa385c8a29c9c395a5fbc40f03c1c1ef6bf336fb9f62"
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
| 0 | 0.29 | `docker exec qb46c83f-g512m-s1 /opt/opsys-venv/bin/python /opt/opsys/install/qualification/interne.py empreinte` |
| 0 | 0.26 | `docker exec qb46c83f-g512m-s1 /opt/opsys-venv/bin/python /opt/opsys/install/qualification/interne.py empreinte` |
| 0 | 0.05 | `docker exec qb46c83f-g512m-s1 du -sk /opt/data /openclaw-config /sauvegardes` |

