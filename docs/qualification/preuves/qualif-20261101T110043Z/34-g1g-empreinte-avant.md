# g1g-empreinte-avant — [1g] Empreintes et comptages AVANT sauvegarde

- Verdict : **PASSE**
- Attendu : base saine (integrity_check), empreinte par table stable entre deux lectures
- Début : 2026-11-01T11:06:28.292+00:00  ·  Fin : 2026-11-01T11:06:29.878+00:00  ·  Durée : 1.59 s

## Constats

| | Constat | Détail |
|---|---|---|
| OK | deux lectures successives identiques (instance au repos) | "2942b0a8df10bf64" |
| OK | integrity_check = ok |  |

## Mesures

```json
{
  "resume": {
    "revision": "0040",
    "integrity_check": true,
    "tables": 86,
    "lignes_total": 109,
    "sha256_global": "2942b0a8df10bf6400b23020e66f6d6dd638f1caa0bab1f615904fced9fccc04"
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
| 0 | 0.28 | `docker exec qb46c83f-g1g-s1 /opt/opsys-venv/bin/python /opt/opsys/install/qualification/interne.py empreinte` |
| 0 | 0.25 | `docker exec qb46c83f-g1g-s1 /opt/opsys-venv/bin/python /opt/opsys/install/qualification/interne.py empreinte` |
| 0 | 0.06 | `docker exec qb46c83f-g1g-s1 du -sk /opt/data /openclaw-config /sauvegardes` |

