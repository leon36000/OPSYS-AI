# c2g-parcours — [2g] Entreprise fictive et parcours minimal : lead, soumission, N3 refusée puis accordée

- Verdict : **PASSE**
- Attendu : chaque constat vérifié en base ; l'approbation N3 est refusée sans humain habilité et accordée par la CLI humaine
- Début : 2026-11-01T11:11:55.005+00:00  ·  Fin : 2026-11-01T11:12:04.794+00:00  ·  Durée : 9.79 s

## Constats

| | Constat | Détail |
|---|---|---|
| OK | M1 reçoit le message et transmet à M2 (route MCP HTTP) | {"decision": "TRANSMETTRE_M2", "erreur": null} |
| OK | bus : le lead est livré à M2 sans échec ni quarantaine | {"livres": 7, "traites": 7, "echecs": 0, "quarantaines": 0} |
| OK | M2 : lead qualifié |  |
| OK | M3 : soumission créée (brouillon, 625.00 $ calculé par l'outil) |  |
| OK | N3 par un agent (route MCP) : refusé, rien exécuté | "ticket_cible_requis" |
| OK | décision sans humain habilité (identité vide, inconnue, agent système) : refusée, demande en attente | ["(vide): refusé (la décision doit être signée par une personne active (identifiant))", "inconnu-fictif: refusé ('inconnu-fictif' : personne inconnue ou inactive ; décision refusée, r)", "agent-systeme: refusé (agent-systeme : aucun rôle autorisé pour N3 dans m03-estimation (autor)"] |
| OK | CLI sans terminal : refusée (code 1), demande en attente | {"code": 1} |
| OK | CLI humain avec un mauvais mot de passe : refusée (code 1), demande en attente | {"code": 1} |
| OK | CLI humain authentifié (nathan_owner) : accordée (code 0), exécutée | {"code": 0, "statut": "executee"} |
| OK | double décision : refusée, pas de seconde exécution | {"code": 1} |
| OK | bus après acceptation : sans échec ni quarantaine | {"livres": 7, "traites": 7, "echecs": 0, "quarantaines": 0} |
| OK | la soumission est acceptée en base (statut « accepte », approbateur nathan) | {"statut": "accepte", "approbateur": "nathan"} |
| OK | M4 : une intervention « a_planifier » est née de l'acceptation | 1 |
| OK | la décision porte la personne et son rôle | {"statut": "executee", "decide_par": "nathan", "decide_role": "nathan_owner"} |

## Mesures

```json
{
  "memoire_apres_parcours": {
    "cgroup_pic_mo": 433.4,
    "cgroup_limite": "2147483648",
    "rss_max_par_processus_mo": {
      "opsys-console[29]": 142.2,
      "opsys-mcp[27]": 134.2,
      "python[85]": 31.7,
      "sleep[84]": 1.6
    }
  }
}
```

## Commandes (code de sortie réel)

| Code | Durée (s) | Commande |
|---|---|---|
| 0 | 9.52 | `docker exec qbd2db04-c2g-s1 /opt/opsys-venv/bin/python /opt/opsys/install/qualification/interne.py parcours` |
| 0 | 0.27 | `docker exec qbd2db04-c2g-s1 /opt/opsys-venv/bin/python /opt/opsys/install/qualification/interne.py rss` |

