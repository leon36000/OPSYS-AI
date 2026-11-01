# g768m-arret — [768m] Arrêt propre (gabarit seul)

- Verdict : **PASSE**
- Attendu : code de sortie 0, pas de message de processus mort
- Début : 2026-11-01T11:07:19.737+00:00  ·  Fin : 2026-11-01T11:07:21.220+00:00  ·  Durée : 1.48 s

## Constats

| | Constat | Détail |
|---|---|---|
| OK | arrêt propre : code 0, sans OOM | {"code_sortie": 0, "oom": false, "duree_s": 1.2, "message_arret_demande": true, "message_faux_processus_mort": false} |

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
| 0 | 0.26 | `docker exec qb46c83f-g768m-s1 /opt/opsys-venv/bin/python /opt/opsys/install/qualification/interne.py rss` |
| 0 | 1.2 | `docker stop -t 30 qb46c83f-g768m-s1` |

