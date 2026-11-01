# g384m-arret — [384m] Arrêt propre (gabarit seul)

- Verdict : **ECHEC**
- Attendu : code de sortie 0, pas de message de processus mort
- Début : 2026-11-01T11:08:46.420+00:00  ·  Fin : 2026-11-01T11:08:46.459+00:00  ·  Durée : 0.04 s

## Constats

| | Constat | Détail |
|---|---|---|
| **ÉCHEC** | arrêt propre : code 0, sans OOM | {"code_sortie": 1, "oom": true, "duree_s": 0.01, "message_arret_demande": true, "message_faux_processus_mort": true} |

## Mesures

```json
{
  "arret": {
    "code_sortie": 1,
    "oom": true,
    "duree_s": 0.01,
    "message_arret_demande": true,
    "message_faux_processus_mort": true
  }
}
```

## Commandes (code de sortie réel)

| Code | Durée (s) | Commande |
|---|---|---|
| 1 | 0.01 | `docker exec qb46c83f-g384m-s1 /opt/opsys-venv/bin/python /opt/opsys/install/qualification/interne.py rss` |
| 0 | 0.01 | `docker stop -t 30 qb46c83f-g384m-s1` |

