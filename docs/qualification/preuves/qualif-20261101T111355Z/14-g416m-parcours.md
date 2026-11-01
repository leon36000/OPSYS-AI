# g416m-parcours — [416m] Entreprise fictive et parcours minimal : lead, soumission, N3 refusée puis accordée

- Verdict : **ECHEC**
- Attendu : chaque constat vérifié en base ; l'approbation N3 est refusée sans humain habilité et accordée par la CLI humaine
- Début : 2026-11-01T11:15:32.549+00:00  ·  Fin : 2026-11-01T11:15:38.521+00:00  ·  Durée : 5.97 s

## Constats

| | Constat | Détail |
|---|---|---|
| **ÉCHEC** | sortie JSON illisible |  |

## Mesures

```json
{
  "memoire_apres_parcours": {
    "cgroup_pic_mo": 416.0,
    "cgroup_limite": "436207616",
    "rss_max_par_processus_mo": {
      "python[78]": 31.7,
      "sleep[77]": 1.6,
      "sleep[28]": 1.6,
      "entrypoint.sh[6]": 1.5
    }
  }
}
```

## Commandes (code de sortie réel)

| Code | Durée (s) | Commande |
|---|---|---|
| 137 | 5.7 | `docker exec qb768e49-g416m-s1 /opt/opsys-venv/bin/python /opt/opsys/install/qualification/interne.py parcours` |
| 0 | 0.27 | `docker exec qb768e49-g416m-s1 /opt/opsys-venv/bin/python /opt/opsys/install/qualification/interne.py rss` |

