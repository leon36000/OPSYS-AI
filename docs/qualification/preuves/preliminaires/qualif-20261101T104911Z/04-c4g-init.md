# c4g-init — [4g] Démarrage à vide puis initialisation d'une instance fictive

- Verdict : **PASSE**
- Attendu : services démarrés (entrypoint de production), prêts « en attente de configuration » (3), puis prêts (0) après initialisation (personnes, paliers, entreprise, profils de base)
- Début : 2026-11-01T10:49:26.737+00:00  ·  Fin : 2026-11-01T10:49:51.585+00:00  ·  Durée : 24.85 s

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
  "temps_avant_premier_readiness_s": 6.7,
  "temps_redemarrage_jusqu_a_pret_s": 6.8,
  "duree_totale_s": 24.8
}
```

## Commandes (code de sortie réel)

| Code | Durée (s) | Commande |
|---|---|---|
| 0 | 0.2 | `docker run -d --init --name qb2f043b-c4g-s1 --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 4g --memory-swap 4g --labe` |
| 3 | 6.68 | `readiness.py en boucle sur qb2f043b-c4g-s1` |
| 0 | 0.84 | `docker exec qb2f043b-c4g-s1 /opt/opsys-venv/bin/python /opt/opsys/install/qualification/interne.py preparer-secrets` |
| 0 | 9.3 | `docker exec qb2f043b-c4g-s1 /opt/opsys-venv/bin/python /opt/opsys/install/qualification/interne.py initialiser` |
| 0 | 1.06 | `docker restart -t 30 qb2f043b-c4g-s1` |
| 0 | 6.76 | `readiness.py en boucle sur qb2f043b-c4g-s1` |

