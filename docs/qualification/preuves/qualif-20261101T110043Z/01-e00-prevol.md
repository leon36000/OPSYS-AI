# E00-prevol — Pré-vol : hôte, daemon, images locales, absence de réseau

- Verdict : **PASSE**
- Attendu : daemon Docker joignable, image de base en cache, disque suffisant, conteneurs étrangers intouchés
- Début : 2026-11-01T11:00:43.222+00:00  ·  Fin : 2026-11-01T11:00:43.413+00:00  ·  Durée : 0.19 s

## Constats

| | Constat | Détail |
|---|---|---|
| OK | daemon Docker joignable | "29.6.2/aarch64/2/systemd/20/130593832960/overlayfs" |
| OK | image de base python:3.12-slim déjà en cache local (aucun pull) | "python@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704/arm64/linux" |
| OK | au moins 10 Go libres (plafond du banc : 8 Go) |  |

## Mesures

```json
{
  "hote": {
    "docker": "29.6.2",
    "arch": "aarch64",
    "cgroup": "2",
    "pilote_cgroup": "systemd",
    "cpus": 20,
    "memoire_totale_go": 121.6,
    "stockage": "overlayfs"
  },
  "image_base": "python@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704|arm64|linux",
  "disque_libre_go": 39.6,
  "depot": {
    "racine": "/tmp/claude-1000/-tmp/67e51219-6449-4d92-98d1-fbc071b4eb81/scratchpad/wt-qualification-docker",
    "commit": "a41d6e7aa8ff",
    "modifications_non_commitees": false
  },
  "conteneurs_etrangers_avant": 26
}
```

## Notes

- Les conteneurs étrangers au banc (dont jeuxvideoca-languagetool-1) ne sont ni lus ni modifiés ; leur état est comparé au pied du rapport.

## Commandes (code de sortie réel)

| Code | Durée (s) | Commande |
|---|---|---|
| 0 | 0.03 | `docker info --format {{.ServerVersion}}/{{.Architecture}}/{{.CgroupVersion}}/{{.CgroupDriver}}/{{.NCPU}}/{{.MemTotal}}/{{.Driver}}` |
| 0 | 0.04 | `docker image inspect python:3.12-slim --format {{index .RepoDigests 0}}/{{.Architecture}}/{{.Os}}` |

