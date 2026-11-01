# c4g-arret-propre — [4g] Arrêt propre de l'instance restaurée

- Verdict : **PASSE**
- Attendu : code 0, pas de message de processus mort
- Début : 2026-11-01T10:54:04.593+00:00  ·  Fin : 2026-11-01T10:54:05.335+00:00  ·  Durée : 0.74 s

## Constats

| | Constat | Détail |
|---|---|---|
| OK | code de sortie 0 | {"code_sortie": 0, "oom": false, "duree_s": 0.42, "message_arret_demande": true, "message_faux_processus_mort": false} |
| OK | message « arrêt demandé », pas de « processus mort » |  |
| OK | sans OOM |  |

## Mesures

```json
{
  "arret": {
    "code_sortie": 0,
    "oom": false,
    "duree_s": 0.42,
    "message_arret_demande": true,
    "message_faux_processus_mort": false
  }
}
```

## Commandes (code de sortie réel)

| Code | Durée (s) | Commande |
|---|---|---|
| 0 | 0.29 | `docker exec qb987e29-c4g-s2 /opt/opsys-venv/bin/python /opt/opsys/install/qualification/interne.py rss` |
| 0 | 0.42 | `docker stop -t 30 qb987e29-c4g-s2` |

