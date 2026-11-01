# c4g-mise-a-jour — [4g] Mise à jour depuis la version précédente (0038) vers la tête, et retour arrière

- Verdict : **ECHEC**
- Attendu : base écrite par l'ancien logiciel migrée sans perte, services prêts, retour arrière alembic sans perte, reprise
- Début : 2026-11-01T10:50:37.236+00:00  ·  Fin : 2026-11-01T10:50:56.459+00:00  ·  Durée : 19.22 s

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
| OK | arrêt propre après mise à jour (code 0) | {"code_sortie": 0, "oom": false, "duree_s": 0.59, "message_arret_demande": true, "message_faux_processus_mort": false} |
| OK | retour arrière alembic 0040 -> 0038 : code 0 | {"avant": "0040", "apres": "0038"} |
| OK | après retour arrière : données identiques à l'état d'avant la mise à jour | "identiques" |
| OK | après retour arrière : integrity_check ok, révision 0038 |  |
| **ÉCHEC** | le logiciel PRÉCÉDENT relit la base rétrogradée (base etat, révision 0038) | "  File \"/opt/opsys-venv/bin/python\", line 1\n    ELF\u0002\u0001\u0001\nSyntaxError: source code cannot contain null bytes\n" |
| OK | nouvelle montée à la tête : mêmes données, révision 0040 |  |
| OK | logiciel PRÉCÉDENT sur base à 0040 : refus (code ≠ 0), base intacte | {"code": 1, "stderr": "  File \"/opt/opsys-venv/bin/python\", line 1\n    ELF\u0002\u0001\u0001\nSyntaxError: source code cannot contain null bytes\n"} |

## Mesures

```json
{
  "avant_mise_a_jour": {
    "revision": "0038",
    "integrity_check": true,
    "tables": 76,
    "lignes_total": 31,
    "sha256_global": "cd30f13f496f9d00e00d9a3b1cac68337a772e3844f9817b5a1eaf832e6dd864"
  },
  "migration_0038_vers_0040": {
    "duree_s": 1.0,
    "rss_max_mo": 67.5
  },
  "tables_ajoutees_par_la_mise_a_jour": 10
}
```

## Commandes (code de sortie réel)

| Code | Durée (s) | Commande |
|---|---|---|
| 0 | 0.02 | `docker volume create --label opsys.banc=qualif-20261101T104911Z qb2f043b-c4ga-data` |
| 0 | 1.99 | `docker run --rm --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 1g --memory-swap 1g --label opsys.banc=qualif-20261101` |
| 0 | 0.54 | `docker run --rm --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 512m --memory-swap 512m --label opsys.banc=qualif-2026` |
| 0 | 0.02 | `docker volume create --label opsys.banc=qualif-20261101T104911Z qb2f043b-c4gas-data` |
| 0 | 0.38 | `docker run --rm --user 1000:1000 -v qb2f043b-c4ga-data:/opt/data:ro -v qb2f043b-c4gas-data:/copie --entrypoint cp opsys-qualif:banc -a /opt/data/. /copie/` |
| 0 | 1.51 | `docker run --rm --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 512m --memory-swap 512m --label opsys.banc=qualif-2026` |
| 0 | 0.51 | `docker run --rm --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 512m --memory-swap 512m --label opsys.banc=qualif-2026` |
| 0 | 0.01 | `docker volume create --label opsys.banc=qualif-20261101T104911Z qb2f043b-c4gad-data` |
| 0 | 0.41 | `docker run --rm --user 1000:1000 -v qb2f043b-c4ga-data:/opt/data:ro -v qb2f043b-c4gad-data:/copie --entrypoint cp opsys-qualif:banc -a /opt/data/. /copie/` |
| 0 | 0.02 | `docker volume create --label opsys.banc=qualif-20261101T104911Z qb2f043b-c4gae-data` |
| 0 | 0.42 | `docker run --rm --user 1000:1000 -v qb2f043b-c4ga-data:/opt/data:ro -v qb2f043b-c4gae-data:/copie --entrypoint cp opsys-qualif:banc -a /opt/data/. /copie/` |
| 0 | 0.01 | `docker volume create --label opsys.banc=qualif-20261101T104911Z qb2f043b-c4gu-cfg` |
| 0 | 0.21 | `docker run -d --init --name qb2f043b-c4g-su --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 4g --memory-swap 4g --labe` |
| 3 | 6.8 | `readiness.py en boucle sur qb2f043b-c4g-su` |
| 1 | 1.12 | `docker exec qb2f043b-c4g-su /opt/opsys-venv/bin/python /opt/opsys/install/qualification/interne.py sondes` |
| 0 | 0.59 | `docker stop -t 30 qb2f043b-c4g-su` |
| 0 | 1.09 | `docker run --rm --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 512m --memory-swap 512m --label opsys.banc=qualif-2026` |
| 0 | 0.56 | `docker run --rm --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 512m --memory-swap 512m --label opsys.banc=qualif-2026` |
| 1 | 0.4 | `docker run --rm --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 512m --memory-swap 512m --label opsys.banc=qualif-2026` |
| 0 | 1.04 | `docker run --rm --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 512m --memory-swap 512m --label opsys.banc=qualif-2026` |
| 0 | 0.54 | `docker run --rm --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 512m --memory-swap 512m --label opsys.banc=qualif-2026` |
| 1 | 0.35 | `docker run --rm --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 512m --memory-swap 512m --label opsys.banc=qualif-2026` |
| 0 | 0.56 | `docker run --rm --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 512m --memory-swap 512m --label opsys.banc=qualif-2026` |

