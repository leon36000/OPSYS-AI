"""Packs sectoriels : le cœur générique PME d'OPSYS-AI et, à côté, tout ce qui dépend du secteur d'activité.

`docs/architecture/PACKS-SECTORIELS.md` : comment créer un pack, ce que le cœur garantit, ce qui reste à faire.
"""

from .codes import CODES_PACK, RefusPack
from .manifeste import Pack, calculer_empreinte, charger_dossier
from .rendu import bloc_sectoriel, copier_skill, rendre_jetons, soul_effectif
from .resolution import (
    CLE_PACK,
    PACK_PAR_DEFAUT,
    charger_pack,
    enregistrer_pack,
    ids_installes,
    pack_actif,
    pack_declare,
    racine_packs,
    termes_sectoriels_installes,
    verifier_packs,
)
from .termes import lignes_avec_termes, termes_trouves

__all__ = [
    "CLE_PACK", "CODES_PACK", "PACK_PAR_DEFAUT", "Pack", "RefusPack", "bloc_sectoriel", "calculer_empreinte",
    "charger_dossier", "charger_pack", "copier_skill", "enregistrer_pack", "ids_installes", "lignes_avec_termes",
    "pack_actif", "pack_declare", "racine_packs", "rendre_jetons", "soul_effectif", "termes_sectoriels_installes",
    "termes_trouves", "verifier_packs",
]
