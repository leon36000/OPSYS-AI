# g384m-empreinte-avant — [384m] Empreintes et comptages AVANT sauvegarde

- Verdict : **ECHEC**
- Attendu : base saine (integrity_check), empreinte par table stable entre deux lectures
- Début : 2026-11-01T11:08:45.379+00:00  ·  Fin : 2026-11-01T11:08:46.409+00:00  ·  Durée : 1.03 s

## Constats

| | Constat | Détail |
|---|---|---|
| **ÉCHEC** | deux lectures successives identiques (instance au repos) |  |

## Mesures

```json
{
  "taille_des_donnees_ko": {}
}
```

## Commandes (code de sortie réel)

| Code | Durée (s) | Commande |
|---|---|---|
| 1 | 0.01 | `docker exec qb46c83f-g384m-s1 /opt/opsys-venv/bin/python /opt/opsys/install/qualification/interne.py empreinte` |
| 1 | 0.01 | `docker exec qb46c83f-g384m-s1 /opt/opsys-venv/bin/python /opt/opsys/install/qualification/interne.py empreinte` |
| 1 | 0.01 | `docker exec qb46c83f-g384m-s1 du -sk /opt/data /openclaw-config /sauvegardes` |

