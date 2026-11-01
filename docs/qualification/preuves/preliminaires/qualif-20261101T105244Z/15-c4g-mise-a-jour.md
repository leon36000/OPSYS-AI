# c4g-mise-a-jour — [4g] Mise à jour depuis la version précédente (0038) vers la tête, et retour arrière

- Verdict : **PASSE**
- Attendu : base écrite par l'ancien logiciel migrée sans perte, services prêts, retour arrière alembic sans perte, reprise
- Début : 2026-11-01T10:54:05.335+00:00  ·  Fin : 2026-11-01T10:54:25.706+00:00  ·  Durée : 20.37 s

## Constats

| | Constat | Détail |
|---|---|---|
| OK | arbre de la version précédente (2ffa4f606^) extrait de git | "" |
| OK | instance peuplée PAR L'ANCIEN logiciel (code source /ancien, révision 0038) | {"code_source": "/ancien/src/opsys", "revision": "0038", "tables": 76, "lead_id": "bb67a597622a695769c5bfa5722fd34bbbac6bc0d295dd8895f862a87d530224", "devis_ok": true} |
| OK | instantané de la base avant mise à jour (volume copié) | "" |
| OK | `opsys-metier base migrer` (logiciel courant) : code 0, révision 0040 | "{\n  \"base\": \"sqlite:////opt/data/opsys.db\",\n  \"revision\": \"0040\"\n}\n" |
| OK | aucune donnée existante perdue ou modifiée (toutes les tables de 0038 identiques) | "identiques" |
| OK | integrity_check = ok après mise à jour |  |
| OK | services démarrés sur la base mise à jour (readiness 0 ou 3 « en attente de configuration ») | [1, 1, 3] |
| OK | sondes MCP/console répondent sur la base mise à jour | ["readiness.py = 0 (prêt)"] |
| OK | arrêt propre après mise à jour (code 0) | {"code_sortie": 0, "oom": false, "duree_s": 0.74, "message_arret_demande": true, "message_faux_processus_mort": false} |
| OK | retour arrière alembic 0040 -> 0038 : code 0 | {"avant": "0040", "apres": "0038"} |
| OK | après retour arrière : données identiques à l'état d'avant la mise à jour | "identiques" |
| OK | après retour arrière : integrity_check ok, révision 0038 |  |
| OK | le logiciel PRÉCÉDENT relit la base rétrogradée (base etat, révision 0038) | "epartement\": \"m08-analytics\",\n      \"registre\": \"faits_entonnoir\",\n      \"maillons\": 1\n    },\n    {\n      \"departement\": \"m10-memoire\",\n      \"registre\": \"evenements\",\n      \"maillons\": 2\n    }\n  ]\n}\n" |
| OK | nouvelle montée à la tête : mêmes données, révision 0040 |  |
| OK | logiciel PRÉCÉDENT sur base à 0040 : refus (code ≠ 0), base intacte | {"code": 1, "stderr": "12/site-packages/alembic/script/base.py\", line 239, in _catch_revision_errors\n    raise util.CommandError(resolution) from re\nalembic.util.exc.CommandError: Can't locate revision identified by '0040'\n"} |

## Mesures

```json
{
  "avant_mise_a_jour": {
    "revision": "0038",
    "integrity_check": true,
    "tables": 76,
    "lignes_total": 31,
    "sha256_global": "2965df6d1db198cc49a30c472cc229b2d0a327839e21531b4c3ed670d74dbd2e"
  },
  "migration_0038_vers_0040": {
    "duree_s": 0.98,
    "rss_max_mo": 67.4
  },
  "tables_ajoutees_par_la_mise_a_jour": 10
}
```

## Commandes (code de sortie réel)

| Code | Durée (s) | Commande |
|---|---|---|
| 0 | 0.01 | `docker volume create --label opsys.banc=qualif-20261101T105244Z qb987e29-c4ga-data` |
| 0 | 2.1 | `docker run --rm --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 1g --memory-swap 1g --label opsys.banc=qualif-20261101` |
| 0 | 0.56 | `docker run --rm --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 512m --memory-swap 512m --label opsys.banc=qualif-2026` |
| 0 | 0.01 | `docker volume create --label opsys.banc=qualif-20261101T105244Z qb987e29-c4gas-data` |
| 0 | 0.42 | `docker run --rm --user 1000:1000 -v qb987e29-c4ga-data:/opt/data:ro -v qb987e29-c4gas-data:/copie --entrypoint cp opsys-qualif:banc -a /opt/data/. /copie/` |
| 0 | 1.62 | `docker run --rm --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 512m --memory-swap 512m --label opsys.banc=qualif-2026` |
| 0 | 0.56 | `docker run --rm --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 512m --memory-swap 512m --label opsys.banc=qualif-2026` |
| 0 | 0.02 | `docker volume create --label opsys.banc=qualif-20261101T105244Z qb987e29-c4gad-data` |
| 0 | 0.46 | `docker run --rm --user 1000:1000 -v qb987e29-c4ga-data:/opt/data:ro -v qb987e29-c4gad-data:/copie --entrypoint cp opsys-qualif:banc -a /opt/data/. /copie/` |
| 0 | 0.01 | `docker volume create --label opsys.banc=qualif-20261101T105244Z qb987e29-c4gae-data` |
| 0 | 0.42 | `docker run --rm --user 1000:1000 -v qb987e29-c4ga-data:/opt/data:ro -v qb987e29-c4gae-data:/copie --entrypoint cp opsys-qualif:banc -a /opt/data/. /copie/` |
| 0 | 0.02 | `docker volume create --label opsys.banc=qualif-20261101T105244Z qb987e29-c4gu-cfg` |
| 0 | 0.22 | `docker run -d --init --name qb987e29-c4g-su --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 4g --memory-swap 4g --labe` |
| 3 | 6.76 | `readiness.py en boucle sur qb987e29-c4g-su` |
| 1 | 1.11 | `docker exec qb987e29-c4g-su /opt/opsys-venv/bin/python /opt/opsys/install/qualification/interne.py sondes` |
| 0 | 0.74 | `docker stop -t 30 qb987e29-c4g-su` |
| 0 | 0.86 | `docker run --rm --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 512m --memory-swap 512m --label opsys.banc=qualif-2026` |
| 0 | 0.38 | `docker run --rm --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 512m --memory-swap 512m --label opsys.banc=qualif-2026` |
| 0 | 1.08 | `docker run --rm --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 512m --memory-swap 512m --label opsys.banc=qualif-2026` |
| 0 | 0.94 | `docker run --rm --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 512m --memory-swap 512m --label opsys.banc=qualif-2026` |
| 0 | 0.4 | `docker run --rm --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 512m --memory-swap 512m --label opsys.banc=qualif-2026` |
| 1 | 1.15 | `docker run --rm --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 512m --memory-swap 512m --label opsys.banc=qualif-2026` |
| 0 | 0.37 | `docker run --rm --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 512m --memory-swap 512m --label opsys.banc=qualif-2026` |

