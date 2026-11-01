# g448m-arret — [448m] Arrêt propre (gabarit seul)

- Verdict : **PASSE**
- Attendu : code de sortie 0, pas de message de processus mort
- Début : 2026-11-01T11:15:01.251+00:00  ·  Fin : 2026-11-01T11:15:02.557+00:00  ·  Durée : 1.31 s

## Constats

| | Constat | Détail |
|---|---|---|
| OK | arrêt propre : code 0, sans OOM | {"code_sortie": 0, "oom": false, "duree_s": 0.99, "message_arret_demande": true, "message_faux_processus_mort": false} |

## Mesures

```json
{
  "arret": {
    "code_sortie": 0,
    "oom": false,
    "duree_s": 0.99,
    "message_arret_demande": true,
    "message_faux_processus_mort": false
  }
}
```

## Commandes (code de sortie réel)

| Code | Durée (s) | Commande |
|---|---|---|
| 0 | 0.29 | `docker exec qb768e49-g448m-s1 /opt/opsys-venv/bin/python /opt/opsys/install/qualification/interne.py rss` |
| 0 | 0.99 | `docker stop -t 30 qb768e49-g448m-s1` |

