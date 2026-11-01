# g448m-empreinte-avant — [448m] Empreintes et comptages AVANT sauvegarde

- Verdict : **PASSE**
- Attendu : base saine (integrity_check), empreinte par table stable entre deux lectures
- Début : 2026-11-01T11:14:57.223+00:00  ·  Fin : 2026-11-01T11:14:58.807+00:00  ·  Durée : 1.58 s

## Constats

| | Constat | Détail |
|---|---|---|
| OK | deux lectures successives identiques (instance au repos) | "2897902a7e1fe5f4" |
| OK | integrity_check = ok |  |

## Mesures

```json
{
  "resume": {
    "revision": "0040",
    "integrity_check": true,
    "tables": 86,
    "lignes_total": 109,
    "sha256_global": "2897902a7e1fe5f4e89cbba3b00ac9b1fdbcbf3193a7456062dee893260c938a"
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
| 0 | 0.29 | `docker exec qb768e49-g448m-s1 /opt/opsys-venv/bin/python /opt/opsys/install/qualification/interne.py empreinte` |
| 0 | 0.26 | `docker exec qb768e49-g448m-s1 /opt/opsys-venv/bin/python /opt/opsys/install/qualification/interne.py empreinte` |
| 0 | 0.03 | `docker exec qb768e49-g448m-s1 du -sk /opt/data /openclaw-config /sauvegardes` |

