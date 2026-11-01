# g768m-empreinte-avant — [768m] Empreintes et comptages AVANT sauvegarde

- Verdict : **PASSE**
- Attendu : base saine (integrity_check), empreinte par table stable entre deux lectures
- Début : 2026-11-01T11:07:15.763+00:00  ·  Fin : 2026-11-01T11:07:17.373+00:00  ·  Durée : 1.61 s

## Constats

| | Constat | Détail |
|---|---|---|
| OK | deux lectures successives identiques (instance au repos) | "9c77805f478ce9ca" |
| OK | integrity_check = ok |  |

## Mesures

```json
{
  "resume": {
    "revision": "0040",
    "integrity_check": true,
    "tables": 86,
    "lignes_total": 109,
    "sha256_global": "9c77805f478ce9cac8b78f8367470190dbe546bc3f0b7ff43fcb7e9d68eba38c"
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
| 0 | 0.28 | `docker exec qb46c83f-g768m-s1 /opt/opsys-venv/bin/python /opt/opsys/install/qualification/interne.py empreinte` |
| 0 | 0.28 | `docker exec qb46c83f-g768m-s1 /opt/opsys-venv/bin/python /opt/opsys/install/qualification/interne.py empreinte` |
| 0 | 0.05 | `docker exec qb46c83f-g768m-s1 du -sk /opt/data /openclaw-config /sauvegardes` |

