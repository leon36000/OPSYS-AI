# c4g-empreinte-avant — [4g] Empreintes et comptages AVANT sauvegarde

- Verdict : **PASSE**
- Attendu : base saine (integrity_check), empreinte par table stable entre deux lectures
- Début : 2026-11-01T10:50:09.683+00:00  ·  Fin : 2026-11-01T10:50:11.204+00:00  ·  Durée : 1.52 s

## Constats

| | Constat | Détail |
|---|---|---|
| OK | deux lectures successives identiques (instance au repos) | "1d24ac22cf28dd6d" |
| OK | integrity_check = ok |  |

## Mesures

```json
{
  "resume": {
    "revision": "0040",
    "integrity_check": true,
    "tables": 86,
    "lignes_total": 109,
    "sha256_global": "1d24ac22cf28dd6d3883018f397e8f9325a986effac331d873778a3127c47c7d"
  }
}
```

## Commandes (code de sortie réel)

| Code | Durée (s) | Commande |
|---|---|---|
| 0 | 0.27 | `docker exec qb2f043b-c4g-s1 /opt/opsys-venv/bin/python /opt/opsys/install/qualification/interne.py empreinte` |
| 0 | 0.25 | `docker exec qb2f043b-c4g-s1 /opt/opsys-venv/bin/python /opt/opsys/install/qualification/interne.py empreinte` |

