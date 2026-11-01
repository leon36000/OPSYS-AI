# E02-installateur-public — Installateur officiel install/install.sh dans un conteneur propre, sans root, sans réseau

- Verdict : **ECHEC**
- Attendu : le résultat réel est consigné ; l'installateur exige Node, uv, pnpm, Docker et le réseau
- Début : 2026-11-01T11:11:24.642+00:00  ·  Fin : 2026-11-01T11:11:25.011+00:00  ·  Durée : 0.37 s

## Constats

| | Constat | Détail |
|---|---|---|
| **ÉCHEC** | l'installateur public termine avec succès (code 0) | "NON : [opsys] ERREUR : Node.js est introuvable. Installez Node 24.16+ ou 26.1+ (https://nodejs.org/), puis relancez cette commande." |

## Mesures

```json
{
  "code_sortie_installateur": 1,
  "sortie": "[opsys] ERREUR : Node.js est introuvable. Installez Node 24.16+ ou 26.1+ (https://nodejs.org/), puis relancez cette commande."
}
```

## Notes

- Échec réel et attendu hors réseau : prérequis absents du conteneur (Node 24.16+/26.1+, uv, pnpm, daemon Docker). Le chemin « installateur » n'est donc NON PROUVÉ ici ; la preuve d'installation de cette qualification est E01 (moteur Python seul, sans Core). Le manque de mémoire observé sur la VM ARM64 (construction du Core) n'est PAS reproduit : le Core n'est pas construit par ce banc.

## Commandes (code de sortie réel)

| Code | Durée (s) | Commande |
|---|---|---|
| 1 | 0.37 | `docker run --rm --network none --user 1000:1000 --label opsys.banc=qualif-20261101T111039Z -e HOME=/home/t --tmpfs /home/t:uid=1000,mode=700,size=256m -v /tmp/claude-1000/-tmp/67e51219-6449-4d92-98d1-fbc071b4eb81/scratch` |

