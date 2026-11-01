# c2g-durcissement — [2g] Durcissement vérifié dans le conteneur en service

- Verdict : **PASSE**
- Attendu : non root, racine en lecture seule, secrets 0600, aucune capacité, ports minimaux, aucun secret dans l'image ni les journaux, journaux sans PII
- Début : 2026-11-01T11:04:29.652+00:00  ·  Fin : 2026-11-01T11:04:34.181+00:00  ·  Durée : 4.53 s

## Constats

| | Constat | Détail |
|---|---|---|
| OK | processus non root (uid/gid) | {"uid": 1000, "gid": 1000} |
| OK | aucun processus du conteneur ne tourne en root | [] |
| OK | système de fichiers racine en lecture seule (code, venv, /etc, /usr) | {"/opt/opsys/probe": "OSError", "/usr/local/probe": "OSError", "/etc/probe": "OSError", "/opt/opsys-venv/probe": "OSError"} |
| OK | seuls /tmp (tmpfs) et les volumes de données sont inscriptibles | {"/tmp": true, "/opt/data": true, "/openclaw-config": true} |
| OK | no-new-privileges actif | "1" |
| OK | aucune capacité effective | "0000000000000000" |
| OK | fichiers de secrets et base : aucun accès groupe/autres (0600) | [] |
| OK | dossier des clés en 0700 | "0o700" |
| OK | ports en écoute minimaux : exactement 8765 (MCP) et 8700 (console) | [8700, 8765] |
| OK | docker inspect : racine en lecture seule |  |
| OK | docker inspect : toutes capacités retirées, no-new-privileges | {"CapDrop": ["ALL"], "SecurityOpt": ["no-new-privileges"]} |
| OK | docker inspect : aucun port publié sur l'hôte | {} |
| OK | docker inspect : limite mémoire et PID posées | {"Memory": 2147483648, "PidsLimit": 256} |
| OK | l'image n'expose que 8765 et 8700 | ["8700/tcp", "8765/tcp"] |
| OK | journaux du service : aucune valeur de secret du banc (jetons, secret de console, clé fournisseur) | {"octets": 5174, "fuites": []} |
| OK | journaux du service : ni mot de passe, ni clé de sauvegarde, ni téléphone du client, ni identifiant tapé (PII) | {"octets_examines": 5174, "secrets_en_clair": [], "pii_trouvees": []} |
| OK | volumes de données/config/sauvegardes : aucun secret du banc en clair (jetons, clé fournisseur, mots de passe) | {"fichiers": 71, "trouvailles": []} |
| OK | système de fichiers de l'image (code, config, hors tests/docs/bibliothèques) : aucun secret ni clé privée | {"fichiers": 4266, "trouvailles": []} |
| OK | historique et variables de l'image : aucune valeur de secret du banc | [] |
| OK | variables d'environnement de l'image : aucun secret (GPG_KEY = empreinte publique de l'image de base) | [] |

## Mesures

```json
{
  "memoire_en_service": {
    "cgroup_pic_mo": 431.9,
    "cgroup_limite": "2147483648",
    "rss_max_par_processus_mo": {
      "opsys-console[27]": 140.8,
      "opsys-mcp[26]": 134.9,
      "python[180]": 31.7,
      "sleep[173]": 1.6
    }
  }
}
```

## Commandes (code de sortie réel)

| Code | Durée (s) | Commande |
|---|---|---|
| 0 | 0.27 | `docker exec qb46c83f-c2g-s1 /opt/opsys-venv/bin/python /opt/opsys/install/qualification/interne.py durcissement` |
| 0 | 0.25 | `docker exec qb46c83f-c2g-s1 /opt/opsys-venv/bin/python /opt/opsys/install/qualification/interne.py balayer /opt/data /openclaw-config /sauvegardes --variables OPENCLAW_GATEWAY_TOKEN OPSYS_MCP_JETON OPSYS_CONTEXT_MCP_JETO` |
| 0 | 3.13 | `docker run --rm --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 512m --memory-swap 512m --label opsys.banc=qualif-2026` |
| 0 | 0.25 | `docker exec qb46c83f-c2g-s1 /opt/opsys-venv/bin/python /opt/opsys/install/qualification/interne.py rss` |
| 0 | 0.25 | `docker exec qb46c83f-c2g-s1 /opt/opsys-venv/bin/python /opt/opsys/install/qualification/interne.py rss` |

