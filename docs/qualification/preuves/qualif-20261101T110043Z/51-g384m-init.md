# g384m-init — [384m] Démarrage à vide puis initialisation d'une instance fictive

- Verdict : **PASSE**
- Attendu : services démarrés (entrypoint de production), prêts « en attente de configuration » (3), puis prêts (0) après initialisation (personnes, paliers, entreprise, profils de base)
- Début : 2026-11-01T11:08:09.051+00:00  ·  Fin : 2026-11-01T11:08:33.708+00:00  ·  Durée : 24.66 s

## Constats

| | Constat | Détail |
|---|---|---|
| OK | premier démarrage : readiness = 3 (en attente de configuration opérateur), pas 0 ni échec | [1, 1, 3] |
| OK | secrets de test créés dans /cles (0600, dossier 0700) | {"mdp-agent-systeme": "0o600", "mdp-nathan": "0o600", "sauvegarde.cle": "0o600"} |
| OK | initialisation : verifier | "code 0 (attendu 0)" |
| OK | initialisation : personnes creer nathan (nathan_owner) | "code 0 (attendu 0)" |
| OK | initialisation : personnes creer agent-systeme (system_agent) | "code 0 (attendu 0)" |
| OK | initialisation : paliers definir standard | "code 0 (attendu 0)" |
| OK | initialisation : paliers definir rapide | "code 0 (attendu 0)" |
| OK | initialisation : entreprise fictive (services + zone) | "code 0 (attendu 0)" |
| OK | initialisation : agents-base provisionner | "code 0 (attendu 0)" |
| OK | après initialisation et redémarrage : readiness = 0 | [1, 1, 0] |

## Mesures

```json
{
  "temps_avant_premier_readiness_s": 6.9,
  "temps_redemarrage_jusqu_a_pret_s": 6.7,
  "duree_totale_s": 24.7
}
```

## Commandes (code de sortie réel)

| Code | Durée (s) | Commande |
|---|---|---|
| 0 | 0.21 | `docker run -d --init --name qb46c83f-g384m-s1 --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 384m --memory-swap 384m ` |
| 3 | 6.87 | `readiness.py en boucle sur qb46c83f-g384m-s1` |
| 0 | 0.88 | `docker exec qb46c83f-g384m-s1 /opt/opsys-venv/bin/python /opt/opsys/install/qualification/interne.py preparer-secrets` |
| 0 | 9.45 | `docker exec qb46c83f-g384m-s1 /opt/opsys-venv/bin/python /opt/opsys/install/qualification/interne.py initialiser` |
| 0 | 0.55 | `docker restart -t 30 qb46c83f-g384m-s1` |
| 0 | 6.7 | `readiness.py en boucle sur qb46c83f-g384m-s1` |

