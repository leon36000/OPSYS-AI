# c4g-destruction — [4g] Arrêt propre puis DESTRUCTION de l'instance (conteneur, données, configuration)

- Verdict : **PASSE**
- Attendu : arrêt avec code 0 sans message de processus mort ; volumes data/cfg supprimés ; clés et sauvegardes conservées
- Début : 2026-11-01T11:02:05.084+00:00  ·  Fin : 2026-11-01T11:02:06.335+00:00  ·  Durée : 1.25 s

## Constats

| | Constat | Détail |
|---|---|---|
| OK | arrêt propre : code de sortie 0 | {"code_sortie": 0, "oom": false, "duree_s": 0.73, "message_arret_demande": true, "message_faux_processus_mort": false} |
| OK | arrêt propre : message « arrêt demandé » et pas de « processus mort » |  |
| OK | aucune mise à mort par manque de mémoire (OOM) |  |
| OK | volume de données détruit |  |
| OK | sauvegarde et clé ont survécu (volumes distincts) | ["/cles:", "mdp-agent-systeme", "mdp-nathan", "sauvegarde.cle", "/sauvegardes:", "opsys-sauvegarde-20261101T110159Z-00c6.tar.gz.enc", "opsys-sauvegarde-20261101T110159Z-00c6.tar.gz.enc.meta.json"] |

## Mesures

```json
{
  "arret": {
    "code_sortie": 0,
    "oom": false,
    "duree_s": 0.73,
    "message_arret_demande": true,
    "message_faux_processus_mort": false
  }
}
```

## Commandes (code de sortie réel)

| Code | Durée (s) | Commande |
|---|---|---|
| 0 | 0.28 | `docker exec qb46c83f-c4g-s1 /opt/opsys-venv/bin/python /opt/opsys/install/qualification/interne.py rss` |
| 0 | 0.73 | `docker stop -t 30 qb46c83f-c4g-s1` |
| 0 | 0.02 | `docker rm -f qb46c83f-c4g-s1` |
| 0 | 0.01 | `docker volume rm -f qb46c83f-c4g-data` |
| 0 | 0.01 | `docker volume rm -f qb46c83f-c4g-cfg` |
| 0 | 0.16 | `docker run --rm --network none --user 1000:1000 -v qb46c83f-c4g-sauv:/sauvegardes:ro -v qb46c83f-c4g-cles:/cles:ro --entrypoint ls opsys-qualif:banc /sauvegardes /cles` |

