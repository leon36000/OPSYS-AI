"""Outils du département FICTIF du banc navigateur : un effet N3 purement local (fichier de l'instance), sans réseau."""

from __future__ import annotations

import json
import os
from pathlib import Path

from opsys.outils import Autonomie, Niveau, Outil

ENV_EFFETS = "OPSYS_QUALIF_EFFETS"


def publier_note(titre: str) -> dict:
    """Simule une publication : AJOUTE une ligne au fichier d'effets de l'instance fictive (rien ne sort de la machine)."""
    chemin = Path(os.environ[ENV_EFFETS])
    with chemin.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"publie": titre, "fictif": True}, ensure_ascii=False) + "\n")
    return {"publie": True, "titre": titre}


OUTILS = (
    Outil("m9_qualif_publier_note", "Publie une note FICTIVE (effet local seulement).",
          {"type": "object", "properties": {"titre": {"type": "string", "maxLength": 120}}, "required": ["titre"],
           "additionalProperties": False}, publier_note, Autonomie.T1, niveau=Niveau.N3),
)
