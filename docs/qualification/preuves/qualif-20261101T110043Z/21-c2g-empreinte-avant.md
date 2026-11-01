# c2g-empreinte-avant — [2g] Empreintes et comptages AVANT sauvegarde

- Verdict : **PASSE**
- Attendu : base saine (integrity_check), empreinte par table stable entre deux lectures
- Début : 2026-11-01T11:04:25.694+00:00  ·  Fin : 2026-11-01T11:04:27.303+00:00  ·  Durée : 1.61 s

## Constats

| | Constat | Détail |
|---|---|---|
| OK | deux lectures successives identiques (instance au repos) | "d04e4e0a4e623e00" |
| OK | integrity_check = ok |  |

## Mesures

```json
{
  "resume": {
    "revision": "0040",
    "integrity_check": true,
    "tables": 86,
    "lignes_total": 109,
    "sha256_global": "d04e4e0a4e623e00ce6dd1ad9f315c89e686b66f8d1d0a0c876c9613c3a1a5b2"
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
| 0 | 0.26 | `docker exec qb46c83f-c2g-s1 /opt/opsys-venv/bin/python /opt/opsys/install/qualification/interne.py empreinte` |
| 0 | 0.29 | `docker exec qb46c83f-c2g-s1 /opt/opsys-venv/bin/python /opt/opsys/install/qualification/interne.py empreinte` |
| 0 | 0.06 | `docker exec qb46c83f-c2g-s1 du -sk /opt/data /openclaw-config /sauvegardes` |

