# c2g-arret-propre — [2g] Arrêt propre de l'instance restaurée

- Verdict : **PASSE**
- Attendu : code 0, pas de message de processus mort
- Début : 2026-11-01T11:04:50.305+00:00  ·  Fin : 2026-11-01T11:04:51.709+00:00  ·  Durée : 1.4 s

## Constats

| | Constat | Détail |
|---|---|---|
| OK | code de sortie 0 | {"code_sortie": 0, "oom": false, "duree_s": 1.11, "message_arret_demande": true, "message_faux_processus_mort": false} |
| OK | message « arrêt demandé », pas de « processus mort » |  |
| OK | sans OOM |  |

## Mesures

```json
{
  "arret": {
    "code_sortie": 0,
    "oom": false,
    "duree_s": 1.11,
    "message_arret_demande": true,
    "message_faux_processus_mort": false
  }
}
```

## Commandes (code de sortie réel)

| Code | Durée (s) | Commande |
|---|---|---|
| 0 | 0.27 | `docker exec qb46c83f-c2g-s2 /opt/opsys-venv/bin/python /opt/opsys/install/qualification/interne.py rss` |
| 0 | 1.11 | `docker stop -t 30 qb46c83f-c2g-s2` |

