# c2g-comparaison — [2g] Comparaison des empreintes et comptages avant / après restauration

- Verdict : **PASSE**
- Attendu : mêmes tables, mêmes comptes, mêmes empreintes de contenu (journal d'audit hors lignes instance.*)
- Début : 2026-11-01T11:04:45.779+00:00  ·  Fin : 2026-11-01T11:04:50.305+00:00  ·  Durée : 4.53 s

## Constats

| | Constat | Détail |
|---|---|---|
| OK | base restaurée : integrity_check = ok, révision 0040 |  |
| OK | toutes les tables identiques (comptes et SHA-256 de contenu) | "aucune différence" |
| OK | empreinte globale identique | {"avant": "d04e4e0a4e623e00", "apres": "d04e4e0a4e623e00"} |
| OK | l'approbation N3 accordée avant la destruction est présente dans l'instance restaurée | "[\n  {\n    \"id\": \"5c1fd7035f87\",\n    \"cree_le\": \"2026-11-01T11:04:15+00:00\",\n    \"departement\": \"m03-estimation\",\n    \"ou" |

## Mesures

```json
{
  "tables": {
    "avant": 86,
    "apres": 86
  },
  "lignes": {
    "avant": 109,
    "apres": 109
  }
}
```

## Commandes (code de sortie réel)

| Code | Durée (s) | Commande |
|---|---|---|
| 0 | 0.26 | `docker exec qb46c83f-c2g-s2 /opt/opsys-venv/bin/python /opt/opsys/install/qualification/interne.py empreinte` |
| 0 | 1.26 | `docker exec qb46c83f-c2g-s2 /opt/opsys-venv/bin/python /opt/opsys/install/qualification/interne.py mesurer -- /opt/opsys-venv/bin/python -m opsys.cli approbations lister --statut executee` |

