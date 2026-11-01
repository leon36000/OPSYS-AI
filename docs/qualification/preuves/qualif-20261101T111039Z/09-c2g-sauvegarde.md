# c2g-sauvegarde — [2g] Sauvegarde chiffrée (export + AES-256-GCM, clé hors sauvegarde) et vérification

- Verdict : **PASSE**
- Attendu : archive chiffrée dans /sauvegardes, clé dans /cles (hors sauvegarde), vérification de bout en bout, aucun clair
- Début : 2026-11-01T11:12:09.385+00:00  ·  Fin : 2026-11-01T11:12:11.849+00:00  ·  Durée : 2.46 s

## Constats

| | Constat | Détail |
|---|---|---|
| OK | sauvegarde chiffrée réussie (code 0) | "ok" |
| OK | verifiee == vrai |  |
| OK | archive en 0600, propriétaire non root | ["600 opsys"] |
| OK | la clé n'est pas dans le dossier des sauvegardes |  |
| OK | aucune donnée lisible dans l'archive (« nathan » absent du fichier chiffré) | "0" |
| OK | `verifier` indépendant : archive authentifiée avec la clé | "" |

## Mesures

```json
{
  "sauvegarde": {
    "duree_s": 0.93,
    "rss_max_enfant_mo": 69.8,
    "cgroup_pic_mo": 433.4
  },
  "archive": {
    "fichier": "opsys-sauvegarde-20261101T111210Z-9799.tar.gz.enc",
    "octets_chiffres": 46399,
    "revision_base": "0040",
    "cle_id": "b5cba2be7e7c842d65ea4ca9d09025d8"
  }
}
```

## Commandes (code de sortie réel)

| Code | Durée (s) | Commande |
|---|---|---|
| 0 | 1.21 | `docker exec qbd2db04-c2g-s1 /opt/opsys-venv/bin/python /opt/opsys/install/qualification/interne.py mesurer -- /opt/opsys-venv/bin/python -m opsys.sauvegarde_chiffree sauvegarder --dossier /sauvegardes --par banc` |
| 0 | 0.05 | `docker exec qbd2db04-c2g-s1 sh -c stat -c '%a %U' /sauvegardes/opsys-sauvegarde-20261101T111210Z-9799.tar.gz.enc; ls /sauvegardes; ls /cles` |
| 1 | 0.05 | `docker exec qbd2db04-c2g-s1 grep -c -a nathan /sauvegardes/opsys-sauvegarde-20261101T111210Z-9799.tar.gz.enc` |
| 0 | 1.11 | `docker exec qbd2db04-c2g-s1 /opt/opsys-venv/bin/python /opt/opsys/install/qualification/interne.py mesurer -- /opt/opsys-venv/bin/python -m opsys.sauvegarde_chiffree verifier /sauvegardes/opsys-sauvegarde-20261101T111210` |

