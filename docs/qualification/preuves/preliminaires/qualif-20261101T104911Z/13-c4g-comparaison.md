# c4g-comparaison — [4g] Comparaison des empreintes et comptages avant / après restauration

- Verdict : **PASSE**
- Attendu : mêmes tables, mêmes comptes, mêmes empreintes de contenu (journal d'audit hors lignes instance.*)
- Début : 2026-11-01T10:50:31.116+00:00  ·  Fin : 2026-11-01T10:50:35.631+00:00  ·  Durée : 4.52 s

## Constats

| | Constat | Détail |
|---|---|---|
| OK | base restaurée : integrity_check = ok, révision 0040 |  |
| OK | toutes les tables identiques (comptes et SHA-256 de contenu) | "aucune différence" |
| OK | empreinte globale identique | {"avant": "1d24ac22cf28dd6d", "apres": "1d24ac22cf28dd6d"} |
| OK | l'approbation N3 accordée avant la destruction est présente dans l'instance restaurée | "[\n  {\n    \"id\": \"40b8dca17489\",\n    \"cree_le\": \"2026-11-01T10:49:59+00:00\",\n    \"departement\": \"m03-estimation\",\n    \"ou" |

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
| 0 | 0.27 | `docker exec qb2f043b-c4g-s2 /opt/opsys-venv/bin/python /opt/opsys/install/qualification/interne.py empreinte` |
| 0 | 1.25 | `docker exec qb2f043b-c4g-s2 /opt/opsys-venv/bin/python /opt/opsys/install/qualification/interne.py mesurer -- /opt/opsys-venv/bin/python -m opsys.cli approbations lister --statut executee` |

