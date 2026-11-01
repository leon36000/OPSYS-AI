# c2g-destruction — [2g] Arrêt propre puis DESTRUCTION de l'instance (conteneur, données, configuration)

- Verdict : **PASSE**
- Attendu : arrêt avec code 0 sans message de processus mort ; volumes data/cfg supprimés ; clés et sauvegardes conservées
- Début : 2026-11-01T11:04:34.182+00:00  ·  Fin : 2026-11-01T11:04:35.809+00:00  ·  Durée : 1.63 s

## Constats

| | Constat | Détail |
|---|---|---|
| OK | arrêt propre : code de sortie 0 | {"code_sortie": 0, "oom": false, "duree_s": 1.1, "message_arret_demande": true, "message_faux_processus_mort": false} |
| OK | arrêt propre : message « arrêt demandé » et pas de « processus mort » |  |
| OK | aucune mise à mort par manque de mémoire (OOM) |  |
| OK | volume de données détruit |  |
| OK | sauvegarde et clé ont survécu (volumes distincts) | ["/cles:", "mdp-agent-systeme", "mdp-nathan", "sauvegarde.cle", "/sauvegardes:", "opsys-sauvegarde-20261101T110428Z-29b4.tar.gz.enc", "opsys-sauvegarde-20261101T110428Z-29b4.tar.gz.enc.meta.json"] |

## Mesures

```json
{
  "arret": {
    "code_sortie": 0,
    "oom": false,
    "duree_s": 1.1,
    "message_arret_demande": true,
    "message_faux_processus_mort": false
  }
}
```

## Commandes (code de sortie réel)

| Code | Durée (s) | Commande |
|---|---|---|
| 0 | 0.29 | `docker exec qb46c83f-c2g-s1 /opt/opsys-venv/bin/python /opt/opsys/install/qualification/interne.py rss` |
| 0 | 1.1 | `docker stop -t 30 qb46c83f-c2g-s1` |
| 0 | 0.03 | `docker rm -f qb46c83f-c2g-s1` |
| 0 | 0.01 | `docker volume rm -f qb46c83f-c2g-data` |
| 0 | 0.01 | `docker volume rm -f qb46c83f-c2g-cfg` |
| 0 | 0.17 | `docker run --rm --network none --user 1000:1000 -v qb46c83f-c2g-sauv:/sauvegardes:ro -v qb46c83f-c2g-cles:/cles:ro --entrypoint ls opsys-qualif:banc /sauvegardes /cles` |

