# E01-installation-depuis-le-depot-local — Installation du moteur depuis le dépôt local (image de qualification)

- Verdict : **PASSE**
- Attendu : dépendances copiées d'un environnement local, paquet opsys-ai installé depuis le dépôt, image construite sans réseau
- Début : 2026-11-01T11:10:39.376+00:00  ·  Fin : 2026-11-01T11:11:24.641+00:00  ·  Durée : 45.27 s

## Constats

| | Constat | Détail |
|---|---|---|
| OK | dépendances indispensables toutes présentes | "oui" |
| OK | construction de l'image réussie (code 0) | "ok" |
| OK | pip a installé opsys-ai depuis le dépôt (--no-deps --no-build-isolation) | ["Successfully installed opsys-ai-2.0.0.dev0"] |
| OK | `opsys-metier --version` répond (code 0) | "opsys-metier 2.0.0.dev0" |
| OK | `pip check` : aucune dépendance cassée | "No broken requirements found.\nWARNING: The directory '/home/opsys/.cache/pip' or its parent directory is not owned or is not writable by the current user. The cache has been disabled. Check the permis" |
| OK | l'image tourne par défaut en utilisateur non root (uid 1000) | "uid=1000(opsys) gid=1000(opsys) groups=1000(opsys)" |

## Mesures

```json
{
  "dependances": {
    "copiees": 42,
    "absentes_du_venv": [
      "contourpy==1.4.0",
      "cycler==0.12.1",
      "fonttools==4.66.1",
      "kiwisolver==1.5.1",
      "matplotlib==3.11.2",
      "numpy==2.3.5",
      "pyparsing==3.3.3",
      "python-dateutil==2.9.0.post0",
      "pyvrp==0.14.0",
      "six==1.17.0",
      "tqdm==4.70.1",
      "vrplib==2.2.0"
    ],
    "versions_differentes_du_verrou": [],
    "empreintes_du_verrou_verifiees": false
  },
  "duree_construction_s": 41.4,
  "taille_image_mo": 135.5,
  "taille_image_de_base_mo": 41.5,
  "pip_check": {
    "code": 0,
    "sortie": "No broken requirements found.\nWARNING: The directory '/home/opsys/.cache/pip' or its parent directory is not owned or is not writable by the current user. The cache has been disabled. Check the permissions and owner of that directory. If executing pip with sudo, you should use sudo's -H flag."
  },
  "composition_image_mo": {
    "/opt/opsys-venv": 113,
    "/opt/opsys/docs": 48,
    "/usr/local/lib/python3.12": 31,
    "/opt/opsys/departments": 23,
    "/opt/opsys/mobile": 18,
    "/opt/opsys/tests": 9,
    "/opt/opsys/src": 5,
    "/opt/opsys/uv.lock": 1,
    "/opt/opsys/scripts": 1
  }
}
```

## Notes

- ÉCART : `pip install --require-hashes -r requirements-runtime.lock.txt` (chemin de production) exige le réseau et n'a PAS été exécuté ; les dépendances viennent d'un environnement déjà installé (mêmes versions que le verrou, sauf les distributions listées en « absentes_du_venv » : extra « tournées », PyVRP et numériques).
- L'image embarque le dépôt entier hors .dockerignore (mobile/, tests/, docs/) : voir « composition_image_mo ».

## Commandes (code de sortie réel)

| Code | Durée (s) | Commande |
|---|---|---|
| 0 | 0.21 | `preparer_contexte.py (copie hors réseau des dépendances du verrou)` |
| 0 | 41.45 | `docker build --progress=plain -f /tmp/claude-1000/-tmp/67e51219-6449-4d92-98d1-fbc071b4eb81/scratchpad/wt-qualification-docker/install/qualification/Dockerfile --build-context deps=/tmp/claude-1000/-tmp/67e51219-6449-4d9` |
| 0 | 1.96 | `docker run --rm --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 256m --memory-swap 256m --label opsys.banc=qualif-2026` |
| 0 | 0.77 | `docker run --rm --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 256m --memory-swap 256m --label opsys.banc=qualif-2026` |
| 0 | 0.42 | `docker run --rm --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 256m --memory-swap 256m --label opsys.banc=qualif-2026` |
| 0 | 0.38 | `docker run --rm --network none --user 1000:1000 --read-only --tmpfs /tmp:size=64m,mode=1777 --cap-drop ALL --security-opt no-new-privileges --pids-limit 256 --memory 256m --memory-swap 256m --label opsys.banc=qualif-2026` |

