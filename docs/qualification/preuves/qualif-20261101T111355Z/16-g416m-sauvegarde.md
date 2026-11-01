# g416m-sauvegarde — [416m] Sauvegarde chiffrée (export + AES-256-GCM, clé hors sauvegarde) et vérification

- Verdict : **ECHEC**
- Attendu : archive chiffrée dans /sauvegardes, clé dans /cles (hors sauvegarde), vérification de bout en bout, aucun clair
- Début : 2026-11-01T11:15:42.554+00:00  ·  Fin : 2026-11-01T11:15:42.566+00:00  ·  Durée : 0.01 s

## Constats

| | Constat | Détail |
|---|---|---|
| **ÉCHEC** | sauvegarde chiffrée réussie (code 0) |  |

## Commandes (code de sortie réel)

| Code | Durée (s) | Commande |
|---|---|---|
| 1 | 0.01 | `docker exec qb768e49-g416m-s1 /opt/opsys-venv/bin/python /opt/opsys/install/qualification/interne.py mesurer -- /opt/opsys-venv/bin/python -m opsys.sauvegarde_chiffree sauvegarder --dossier /sauvegardes --par banc` |

