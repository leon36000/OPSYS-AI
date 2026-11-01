# c2g-injections — [2g] Injections de défauts : échecs propres, codes typés, aucune perte

- Verdict : **PASSE**
- Attendu : chaque défaut refusé avec son code, l'instance existante intacte (empreinte identique)
- Début : 2026-11-01T11:04:51.709+00:00  ·  Fin : 2026-11-01T11:05:45.534+00:00  ·  Durée : 53.83 s

## Constats

| | Constat | Détail |
|---|---|---|
| OK | F1 restauration avec une mauvaise clé (sur instance non vide, --remplacer) : refusé avec REJ-SAUVEGARDE-MAUVAISE-CLE (code de sortie 14) | {"code": 14, "stderr": "REJ-SAUVEGARDE-MAUVAISE-CLE : cette clé n'est pas celle qui a chiffré la sauvegarde ; rien n'a été déchiffré.\n"} |
| OK | F1 : instance existante intacte (empreinte identique) |  |
| OK | F2a export d'une base vivante corrompue (pages écrasées) : refusé avec REJ-SAUVEGARDE-BASE-CORROMPUE (code de sortie 26) | {"code": 26, "stderr": "REJ-SAUVEGARDE-BASE-CORROMPUE : copie de la base impossible : database disk image is malformed\n"} |
| OK | F2a aucune sauvegarde (ni partielle ni dossier temporaire) n'a été laissée | "[]" |
| OK | F2b archive piégée fabriquée (manifeste cohérent, base abîmée) | "" |
| OK | F2b restauration d'une archive authentique contenant une base corrompue : refusé avec REJ-SAUVEGARDE-BASE-CORROMPUE (code de sortie 26) | {"code": 26, "stderr": "REJ-SAUVEGARDE-BASE-CORROMPUE : la base de l'archive est illisible : database disk image is malformed\n"} |
| OK | F2b la cible n'a reçu aucun fichier (rien de partiel) | "[]" |
| OK | F3 migration 0038->0040 tuée (SIGKILL) à 6 stades : base saine, atomique, reprise sans perte | {"instructions": 36, "revisions_apres_kill": ["0038", "0038", "0038", "0038", "0040", "0040"], "reprise": {"code": 0, "revision": "0040", "donnees_anciennes_intactes": true, "integrity_check": true}} |
| OK | F4 disque plein (destination de 96 Ko) : refusé avec REJ-SAUVEGARDE-DISQUE-PLEIN (code de sortie 19) | {"code": 19, "stderr": "REJ-SAUVEGARDE-DISQUE-PLEIN : copie de la base impossible : database or disk is full\n"} |
| OK | F4 : instance existante intacte (empreinte identique) |  |
| OK | F5a clé de sauvegarde absente (variable non définie) : refusé avec REJ-SAUVEGARDE-CLE-ABSENTE (code de sortie 10) | {"code": 10, "stderr": "REJ-SAUVEGARDE-CLE-ABSENTE : clé de sauvegarde absente : définir OPSYS_SAUVEGARDE_CLE_FICHIER (générer-cle).\n"} |
| OK | F5b OPSYS_CONSOLE_SECRET manquant : le service s'arrête avec un code non nul et le dit | {"etat": "false/1", "extrait": "u conteneur pour relance par restart:unless-stopped.\nINFO:     Shutting down\nINFO:     Waiting for application shutdown.\nINFO:     Application shutdown complete.\nINFO:     Finished server process [15]"} |
| OK | F5b OPSYS_MCP_JETON manquant : le service s'arrête avec un code non nul et le dit | {"etat": "false/1", "extrait": "u conteneur pour relance par restart:unless-stopped.\nINFO:     Shutting down\nINFO:     Waiting for application shutdown.\nINFO:     Application shutdown complete.\nINFO:     Finished server process [17]"} |
| OK | F5 : instance existante intacte (empreinte identique) |  |
| OK | F5c clé de fournisseur de modèle absente : le service RESTE UP et dit « en attente de configuration » (readiness 3) | {"code": 3, "stderr": "not ready secrets: variables requises absentes (ANTHROPIC_API_KEY)"} |
| OK | F6a archive d'une version PLUS RÉCENTE fabriquée (révision 9999, manifeste cohérent) | "" |
| OK | F6a restauration d'une archive de version plus récente : refusé avec REJ-SAUVEGARDE-VERSION-LOGICIEL (code de sortie 25) | {"code": 25, "stderr": "base ('9999') est inconnue de ce logiciel : l'archive vient d'une version plus récente. Mettez le logiciel à jour (relancez l'installateur) avant de restaurer.\n"} |
| OK | F6b format de sauvegarde chiffrée de version inconnue (v99) : refusé avec REJ-SAUVEGARDE-VERSION-FORMAT (code de sortie 18) | {"code": 18, "stderr": "REJ-SAUVEGARDE-VERSION-FORMAT : format de sauvegarde v99 inconnu de ce logiciel (v1) : mettre le logiciel à jour avant de restaurer.\n"} |
| OK | F6 : instance existante intacte (empreinte identique) |  |
| OK | F7a archive tronquée à 50 % (restauration sur cible vierge) : refusé avec REJ-SAUVEGARDE-TRONQUEE (code de sortie 16) | {"code": 16, "stderr": "REJ-SAUVEGARDE-TRONQUEE : bloc incomplet : archive tronquée.\n"} |
| OK | F7a archive tronquée à 50 % : la cible reste vide (rien d'écrit, ni .partiel) | "[]" |
| OK | F7a archive tronquée à 50 % (sur instance non vide, --remplacer) : refusé avec REJ-SAUVEGARDE-TRONQUEE (code de sortie 16) | {"code": 16, "stderr": "REJ-SAUVEGARDE-TRONQUEE : bloc incomplet : archive tronquée.\n"} |
| OK | F7b un seul bit modifié au milieu (restauration sur cible vierge) : refusé avec REJ-SAUVEGARDE-ALTEREE (code de sortie 15) | {"code": 15, "stderr": "REJ-SAUVEGARDE-ALTEREE : le bloc 0 échoue à l'authentification : archive altérée.\n"} |
| OK | F7b un seul bit modifié au milieu : la cible reste vide (rien d'écrit, ni .partiel) | "[]" |
| OK | F7b un seul bit modifié au milieu (sur instance non vide, --remplacer) : refusé avec REJ-SAUVEGARDE-ALTEREE (code de sortie 15) | {"code": 15, "stderr": "REJ-SAUVEGARDE-ALTEREE : le bloc 0 échoue à l'authentification : archive altérée.\n"} |
| OK | F7 : instance existante intacte (empreinte identique) |  |
| OK | F8 clé de sauvegarde rangée dans le dossier des sauvegardes : refusé avec REJ-SAUVEGARDE-CLE-DANS-SAUVEGARDE (code de sortie 13) | {"code": 13, "stderr": "REJ-SAUVEGARDE-CLE-DANS-SAUVEGARDE : la clé de sauvegarde ne doit pas se trouver dans /sauvegardes : une sauvegarde qui contient sa clé ne protège rien.\n"} |
| OK | F8 : instance existante intacte (empreinte identique) |  |

## Mesures

```json
{
  "F3_detail": {
    "instructions_totales": 36,
    "essais": [
      {
        "fraction": 0.05,
        "tue_a_l_instruction": 1,
        "code_enfant": -9,
        "integrity_check": true,
        "revision": "0038",
        "donnees_anciennes_intactes": true
      },
      {
        "fraction": 0.25,
        "tue_a_l_instruction": 9,
        "code_enfant": -9,
        "integrity_check": true,
        "revision": "0038",
        "donnees_anciennes_intactes": true
      },
      {
        "fraction": 0.5,
        "tue_a_l_instruction": 18,
        "code_enfant": -9,
        "integrity_check": true,
        "revision": "0038",
        "donnees_anciennes_intactes": true
      },
      {
        "fraction": 0.75,
        "tue_a_l_instruction": 27,
        "code_enfant": -9,
        "integrity_check": true,
        "revision": "0038",
        "donnees_anciennes_intactes": true
      },
      {
        "fraction": 0.95,
        "tue_a_l_instruction": 34,
        "code_enfant": -9,
        "integrity_check": true,
        "revision": "0040",
        "donnees_anciennes_intactes": true
      },
      {
        "fraction": 0.999,
        "tue_a_l_instruction": 35,
        "code_enfant": -9,
        "integrity_check": true,
        "revision": "0040",
        "donnees_anciennes_intactes": true
      }
    ],
    "reprise": {
      "code": 0,
      "revision": "0040",
      "donnees_anciennes_intactes": true,
      "integrity_check": true
    }
  }
}
```

## Notes

- F4 : le conteneur de test n'a pas de fichier résiduel visible dans /plein (le tmpfs est éphémère) ; la preuve de nettoyage des `.partiel` est dans les tests unitaires tests/test_sauvegarde_chiffree.py::test_disque_plein_ne_laisse_aucun_fichier_partiel.

## Commandes (code de sortie réel)

| Code | Durée (s) | Commande |
|---|---|---|
| 0 | 0.01 | `docker volume create --label opsys.banc=qualif-20261101T110043Z qb46c83f-c2gx-data` |
| 0 | 0.23 | `docker run --rm --user 1000:1000 -v qb46c83f-c2gr-data:/opt/data:ro -v qb46c83f-c2gx-data:/copie --entrypoint cp opsys-qualif:banc -a /opt/data/. /copie/` |
| 0 | 0.38 | `docker run --rm --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 512m --memory-swap 512m --label opsys.banc=qualif-2026` |
| 0 | 1.07 | `docker run --rm --user 1000:1000 -v qb46c83f-c2g-cles:/cles --entrypoint /opt/opsys-venv/bin/python opsys-qualif:banc -m opsys.sauvegarde_chiffree generer-cle /cles/autre.cle` |
| 0 | 1.25 | `docker run --rm --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 512m --memory-swap 512m --label opsys.banc=qualif-2026` |
| 0 | 0.35 | `docker run --rm --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 512m --memory-swap 512m --label opsys.banc=qualif-2026` |
| 0 | 0.01 | `docker volume create --label opsys.banc=qualif-20261101T110043Z qb46c83f-c2gc-data` |
| 0 | 0.23 | `docker run --rm --user 1000:1000 -v qb46c83f-c2gx-data:/opt/data:ro -v qb46c83f-c2gc-data:/copie --entrypoint cp opsys-qualif:banc -a /opt/data/. /copie/` |
| 0 | 0.43 | `docker run --rm --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 256m --memory-swap 256m --label opsys.banc=qualif-2026` |
| 0 | 1.24 | `docker run --rm --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 512m --memory-swap 512m --label opsys.banc=qualif-2026` |
| 0 | 0.26 | `docker run --rm --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 256m --memory-swap 256m --label opsys.banc=qualif-2026` |
| 0 | 0.01 | `docker volume create --label opsys.banc=qualif-20261101T110043Z qb46c83f-c2gk-data` |
| 0 | 1.06 | `docker run --rm --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 512m --memory-swap 512m --label opsys.banc=qualif-2026` |
| 0 | 1.17 | `docker run --rm --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 512m --memory-swap 512m --label opsys.banc=qualif-2026` |
| 0 | 0.23 | `docker run --rm --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 256m --memory-swap 256m --label opsys.banc=qualif-2026` |
| 0 | 0.01 | `docker volume create --label opsys.banc=qualif-20261101T110043Z qb46c83f-c4gam-data` |
| 0 | 6.08 | `docker run --rm --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 512m --memory-swap 512m --label opsys.banc=qualif-2026` |
| 0 | 1.19 | `docker run --rm --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 512m --memory-swap 512m --label opsys.banc=qualif-2026` |
| 0 | 0.39 | `docker run --rm --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 512m --memory-swap 512m --label opsys.banc=qualif-2026` |
| 0 | 1.23 | `docker run --rm --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 512m --memory-swap 512m --label opsys.banc=qualif-2026` |
| 0 | 0.01 | `docker volume create --label opsys.banc=qualif-20261101T110043Z qb46c83f-c2gfcret-cfg` |
| 0 | 0.12 | `docker run -d --init --name qb46c83f-c2g-f-opsys-console-secret --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 512m -` |
| 0 | 0.03 | `docker rm -f qb46c83f-c2g-f-opsys-console-secret` |
| 0 | 0.01 | `docker volume create --label opsys.banc=qualif-20261101T110043Z qb46c83f-c2gfeton-cfg` |
| 0 | 0.11 | `docker run -d --init --name qb46c83f-c2g-f-opsys-mcp-jeton --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 512m --memo` |
| 0 | 0.03 | `docker rm -f qb46c83f-c2g-f-opsys-mcp-jeton` |
| 0 | 0.45 | `docker run --rm --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 512m --memory-swap 512m --label opsys.banc=qualif-2026` |
| 0 | 0.01 | `docker volume create --label opsys.banc=qualif-20261101T110043Z qb46c83f-c2gg-cfg` |
| 0 | 0.13 | `docker run -d --init --name qb46c83f-c2g-g --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 512m --memory-swap 512m --l` |
| 3 | 7.04 | `readiness.py en boucle sur qb46c83f-c2g-g` |
| 3 | 0.97 | `docker exec qb46c83f-c2g-g /opt/opsys-venv/bin/python /opt/opsys/deploy/readiness.py` |
| 0 | 0.1 | `docker rm -f qb46c83f-c2g-g` |
| 0 | 0.01 | `docker volume create --label opsys.banc=qualif-20261101T110043Z qb46c83f-c2gv-data` |
| 0 | 1.02 | `docker run --rm --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 512m --memory-swap 512m --label opsys.banc=qualif-2026` |
| 0 | 1.22 | `docker run --rm --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 512m --memory-swap 512m --label opsys.banc=qualif-2026` |
| 0 | 0.21 | `docker run --rm --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 256m --memory-swap 256m --label opsys.banc=qualif-2026` |
| 0 | 1.16 | `docker run --rm --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 512m --memory-swap 512m --label opsys.banc=qualif-2026` |
| 0 | 0.39 | `docker run --rm --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 512m --memory-swap 512m --label opsys.banc=qualif-2026` |
| 0 | 0.22 | `docker run --rm --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 256m --memory-swap 256m --label opsys.banc=qualif-2026` |
| 0 | 0.38 | `docker run --rm --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 256m --memory-swap 256m --label opsys.banc=qualif-2026` |
| 0 | 0.01 | `docker volume create --label opsys.banc=qualif-20261101T110043Z qb46c83f-c2gt-data` |
| 0 | 1.18 | `docker run --rm --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 512m --memory-swap 512m --label opsys.banc=qualif-2026` |
| 0 | 0.23 | `docker run --rm --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 256m --memory-swap 256m --label opsys.banc=qualif-2026` |
| 0 | 1.21 | `docker run --rm --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 512m --memory-swap 512m --label opsys.banc=qualif-2026` |
| 0 | 0.23 | `docker run --rm --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 256m --memory-swap 256m --label opsys.banc=qualif-2026` |
| 0 | 0.36 | `docker run --rm --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 256m --memory-swap 256m --label opsys.banc=qualif-2026` |
| 0 | 0.01 | `docker volume create --label opsys.banc=qualif-20261101T110043Z qb46c83f-c2gb-data` |
| 0 | 1.37 | `docker run --rm --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 512m --memory-swap 512m --label opsys.banc=qualif-2026` |
| 0 | 0.35 | `docker run --rm --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 256m --memory-swap 256m --label opsys.banc=qualif-2026` |
| 0 | 1.39 | `docker run --rm --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 512m --memory-swap 512m --label opsys.banc=qualif-2026` |
| 0 | 0.54 | `docker run --rm --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 512m --memory-swap 512m --label opsys.banc=qualif-2026` |
| 0 | 0.42 | `docker run --rm --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 256m --memory-swap 256m --label opsys.banc=qualif-2026` |
| 0 | 1.34 | `docker run --rm --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 512m --memory-swap 512m --label opsys.banc=qualif-2026` |
| 0 | 0.51 | `docker run --rm --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 512m --memory-swap 512m --label opsys.banc=qualif-2026` |

