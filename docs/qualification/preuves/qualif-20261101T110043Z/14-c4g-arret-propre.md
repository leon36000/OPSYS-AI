# c4g-arret-propre — [4g] Arrêt propre de l'instance restaurée

- Verdict : **PASSE**
- Attendu : code 0, pas de message de processus mort
- Début : 2026-11-01T11:02:20.981+00:00  ·  Fin : 2026-11-01T11:02:22.492+00:00  ·  Durée : 1.51 s

## Constats

| | Constat | Détail |
|---|---|---|
| OK | code de sortie 0 | {"code_sortie": 0, "oom": false, "duree_s": 1.23, "message_arret_demande": true, "message_faux_processus_mort": false} |
| OK | message « arrêt demandé », pas de « processus mort » |  |
| OK | sans OOM |  |

## Mesures

```json
{
  "arret": {
    "code_sortie": 0,
    "oom": false,
    "duree_s": 1.23,
    "message_arret_demande": true,
    "message_faux_processus_mort": false
  }
}
```

## Commandes (code de sortie réel)

| Code | Durée (s) | Commande |
|---|---|---|
| 0 | 0.26 | `docker exec qb46c83f-c4g-s2 /opt/opsys-venv/bin/python /opt/opsys/install/qualification/interne.py rss` |
| 0 | 1.23 | `docker stop -t 30 qb46c83f-c4g-s2` |

