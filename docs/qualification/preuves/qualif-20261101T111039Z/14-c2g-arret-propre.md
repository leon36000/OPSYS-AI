# c2g-arret-propre — [2g] Arrêt propre de l'instance restaurée

- Verdict : **PASSE**
- Attendu : code 0, pas de message de processus mort
- Début : 2026-11-01T11:12:33.084+00:00  ·  Fin : 2026-11-01T11:12:34.576+00:00  ·  Durée : 1.49 s

## Constats

| | Constat | Détail |
|---|---|---|
| OK | code de sortie 0 | {"code_sortie": 0, "oom": false, "duree_s": 1.2, "message_arret_demande": true, "message_faux_processus_mort": false} |
| OK | message « arrêt demandé », pas de « processus mort » |  |
| OK | sans OOM |  |

## Mesures

```json
{
  "arret": {
    "code_sortie": 0,
    "oom": false,
    "duree_s": 1.2,
    "message_arret_demande": true,
    "message_faux_processus_mort": false
  }
}
```

## Commandes (code de sortie réel)

| Code | Durée (s) | Commande |
|---|---|---|
| 0 | 0.27 | `docker exec qbd2db04-c2g-s2 /opt/opsys-venv/bin/python /opt/opsys/install/qualification/interne.py rss` |
| 0 | 1.2 | `docker stop -t 30 qbd2db04-c2g-s2` |

