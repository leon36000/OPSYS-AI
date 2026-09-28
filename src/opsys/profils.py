"""Génère, pour chaque département, une « distribution de profil » Hermes.

Hermes installe ensuite chaque dossier généré avec son interface publique et stable :

    hermes profile install <dossier> --name <id> --yes      (ajouter --force pour une mise à jour)

Mémoires, sessions et clés de l'installation ne sont jamais écrasées : elles appartiennent à
l'utilisateur, pas à la distribution.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from . import __version__
from .departements import Departement
from .modeles import section_modele_hermes

REGLES_COMMUNES = """\
## Règles OPSYS (communes à tous les départements)

- Les outils calculent. Ne jamais inventer un prix, un solde, un score, une date ou une quantité :
  appeler l'outil, ou dire que la donnée manque.
- Une réponse `en_attente_approbation` veut dire que l'action n'est PAS faite. Le dire tel quel.
- Économie de tokens : réponses courtes, pas de répétition du contexte, un seul outil à la fois
  quand c'est possible. Une sortie tronquée se lit par tranches avec `opsys_lire_artefact`.
- Vie privée (Loi 25) : ne demander et ne conserver que les renseignements nécessaires à la tâche.
- En cas de doute sur une frontière humaine (paiement, engagement, publication, suppression) :
  s'arrêter et demander.
"""


def rendre_soul(dep: Departement, outils: list[dict[str, str]]) -> str:
    soul = (dep.racine / "SOUL.md").read_text(encoding="utf-8").rstrip()
    lignes = [f"- `{o['nom']}` ({o['autonomie']}) — {o['description']}" for o in outils]
    capacites = "\n".join(lignes)
    return (
        f"{soul}\n\n## Capacités du département {dep.code} — {dep.nom}\n\n"
        f"Mode d'autonomie par défaut : **{dep.mode}**.\n\n{capacites}\n\n{REGLES_COMMUNES}"
    )


def config_hermes(dep: Departement, paliers: Mapping[str, Mapping[str, str]], commande_mcp: str) -> dict[str, Any]:
    return {
        "model": section_modele_hermes(dep.modeles["defaut"], paliers),
        "mcp_servers": {"opsys": {"command": commande_mcp, "args": ["--departement", dep.id]}},
        "plugins": {"enabled": ["opsys"]},
        # Économie de tokens : compaction plus tôt et plus serrée que le défaut Hermes (0,50).
        "compression": {"enabled": True, "threshold": 0.40, "target_ratio": 0.20, "protect_last_n": 12},
        "tools": {"tool_search": {"enabled": "auto"}},
    }


def jobs_cron(dep: Departement) -> dict[str, Any]:
    return {
        "jobs": [
            {
                "id": f"{dep.id}-{p.nom}",
                "name": f"{dep.code} · {p.nom}",
                "prompt": p.consigne,
                "schedule": {"kind": "cron", "expr": p.cron, "display": p.cron},
                "enabled": False,
            }
            for p in dep.planifications
        ]
    }


def generer_distribution(
    dep: Departement,
    destination: Path,
    paliers: Mapping[str, Mapping[str, str]],
    commande_mcp: str = "opsys-mcp",
) -> Path:
    """Écrit la distribution du département dans destination/<id> et renvoie ce dossier."""
    outils = [
        {"nom": o.nom, "autonomie": o.autonomie.value, "description": o.description}
        for o in dep.charger_outils()
    ]
    dossier = destination / dep.id
    if dossier.exists():
        shutil.rmtree(dossier)
    (dossier / "skills").mkdir(parents=True)
    (dossier / "cron").mkdir()

    manifeste = {
        "name": dep.id,
        "version": __version__,
        "description": f"OPSYS {dep.code} — {dep.nom} : {dep.mission}",
        "author": "OPSYS-AI",
    }
    (dossier / "distribution.yaml").write_text(
        yaml.safe_dump(manifeste, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    (dossier / "SOUL.md").write_text(rendre_soul(dep, outils), encoding="utf-8")
    (dossier / "config.yaml").write_text(
        yaml.safe_dump(config_hermes(dep, paliers, commande_mcp), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    (dossier / "cron" / "jobs.json").write_text(
        json.dumps(jobs_cron(dep), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for skill in dep.skills:
        shutil.copytree(dep.racine / "skills" / skill, dossier / "skills" / skill)
    (dossier / ".gitignore").write_text(".env\nauth.json\nmemories/\nsessions/\nlogs/\n", encoding="utf-8")
    return dossier
