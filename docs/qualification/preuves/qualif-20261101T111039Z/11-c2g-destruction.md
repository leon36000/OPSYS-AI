# c2g-destruction — [2g] Arrêt propre puis DESTRUCTION de l'instance (conteneur, données, configuration)

- Verdict : **PASSE**
- Attendu : arrêt avec code 0 sans message de processus mort ; volumes data/cfg supprimés ; clés et sauvegardes conservées
- Début : 2026-11-01T11:12:16.613+00:00  ·  Fin : 2026-11-01T11:12:18.201+00:00  ·  Durée : 1.59 s

## Constats

| | Constat | Détail |
|---|---|---|
| OK | arrêt propre : code de sortie 0 | {"code_sortie": 0, "oom": false, "duree_s": 0.87, "message_arret_demande": true, "message_faux_processus_mort": false} |
| OK | arrêt propre : message « arrêt demandé » et pas de « processus mort » |  |
| OK | aucune mise à mort par manque de mémoire (OOM) |  |
| OK | volume de données détruit |  |
| OK | sauvegarde et clé ont survécu (volumes distincts) | ["/cles:", "mdp-agent-systeme", "mdp-nathan", "sauvegarde.cle", "/sauvegardes:", "opsys-sauvegarde-20261101T111210Z-9799.tar.gz.enc", "opsys-sauvegarde-20261101T111210Z-9799.tar.gz.enc.meta.json"] |

## Mesures

```json
{
  "arret": {
    "code_sortie": 0,
    "oom": false,
    "duree_s": 0.87,
    "message_arret_demande": true,
    "message_faux_processus_mort": false
  }
}
```

## Commandes (code de sortie réel)

| Code | Durée (s) | Commande |
|---|---|---|
| 0 | 0.25 | `docker exec qbd2db04-c2g-s1 /opt/opsys-venv/bin/python /opt/opsys/install/qualification/interne.py rss` |
| 0 | 0.87 | `docker stop -t 30 qbd2db04-c2g-s1` |
| 0 | 0.06 | `docker rm -f qbd2db04-c2g-s1` |
| 0 | 0.01 | `docker volume rm -f qbd2db04-c2g-data` |
| 0 | 0.02 | `docker volume rm -f qbd2db04-c2g-cfg` |
| 0 | 0.34 | `docker run --rm --network none --user 1000:1000 -v qbd2db04-c2g-sauv:/sauvegardes:ro -v qbd2db04-c2g-cles:/cles:ro --entrypoint ls opsys-qualif:banc /sauvegardes /cles` |

