# g384m-parcours — [384m] Entreprise fictive et parcours minimal : lead, soumission, N3 refusée puis accordée

- Verdict : **ECHEC**
- Attendu : chaque constat vérifié en base ; l'approbation N3 est refusée sans humain habilité et accordée par la CLI humaine
- Début : 2026-11-01T11:08:38.675+00:00  ·  Fin : 2026-11-01T11:08:42.378+00:00  ·  Durée : 3.7 s

## Constats

| | Constat | Détail |
|---|---|---|
| **ÉCHEC** | sortie JSON illisible |  |

## Mesures

```json
{
  "memoire_apres_parcours": {}
}
```

## Commandes (code de sortie réel)

| Code | Durée (s) | Commande |
|---|---|---|
| 137 | 3.53 | `docker exec qb46c83f-g384m-s1 /opt/opsys-venv/bin/python /opt/opsys/install/qualification/interne.py parcours` |
| 137 | 0.17 | `docker exec qb46c83f-g384m-s1 /opt/opsys-venv/bin/python /opt/opsys/install/qualification/interne.py rss` |

