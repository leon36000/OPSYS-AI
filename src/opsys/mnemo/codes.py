"""Refus typés de Mnémo : `REJ-MNEMO-…`, toujours avec ce qu'il faut corriger.

`ErreurMnemo` est une `ValueError` : dans un appel d'outil, `opsys.outils.executer` la rend comme un refus métier
(`erreur: refus_metier`, `details: "REJ-MNEMO-… : …"`) et annule la transaction ; l'agent sait quoi corriger.
"""

from __future__ import annotations

from typing import Any

# -- appel d'outil ---------------------------------------------------------------------------------------------------
APPAREIL_FERME = "REJ-MNEMO-APPAREIL-FERME"
APPELANT_INCONNU = "REJ-MNEMO-APPELANT-INCONNU"
# -- entrées et vie privée ---------------------------------------------------------------------------------------------
ENTREE_INVALIDE = "REJ-MNEMO-ENTREE-INVALIDE"
DONNEE_PERSONNELLE = "REJ-MNEMO-DONNEE-PERSONNELLE"
SECRET = "REJ-MNEMO-SECRET"
TEXTE_SUSPECT = "REJ-MNEMO-TEXTE-SUSPECT"
HORODATAGE_INVALIDE = "REJ-MNEMO-HORODATAGE-INVALIDE"
PLAFOND = "REJ-MNEMO-PLAFOND"
# -- modèle de soi -----------------------------------------------------------------------------------------------------
DIMENSION_INCONNUE = "REJ-MNEMO-SOI-DIMENSION-INCONNUE"
VALEUR_INVALIDE = "REJ-MNEMO-SOI-VALEUR-INVALIDE"
SOURCE_INVALIDE = "REJ-MNEMO-SOI-SOURCE-INVALIDE"
SOURCE_INTROUVABLE = "REJ-MNEMO-SOI-SOURCE-INTROUVABLE"
ENONCE_INCONNU = "REJ-MNEMO-SOI-ENONCE-INCONNU"
TRANSITION_INTERDITE = "REJ-MNEMO-SOI-TRANSITION-INTERDITE"
SOURCE_DIRECTION_RESERVEE = "REJ-MNEMO-SOI-SOURCE-DIRECTION-RESERVEE"
HUMAIN_REQUIS = "REJ-MNEMO-HUMAIN-REQUIS"
MOTIF_REQUIS = "REJ-MNEMO-MOTIF-REQUIS"
LECTURE_INTERDITE = "REJ-MNEMO-LECTURE-INTERDITE"
# -- graphe ------------------------------------------------------------------------------------------------------------
NOEUD_TYPE_INCONNU = "REJ-MNEMO-GRAPHE-NOEUD-TYPE-INCONNU"
NOEUD_CLE_INVALIDE = "REJ-MNEMO-GRAPHE-NOEUD-CLE-INVALIDE"
NOEUD_INCONNU = "REJ-MNEMO-GRAPHE-NOEUD-INCONNU"
ARETE_NON_AUTORISEE = "REJ-MNEMO-GRAPHE-ARETE-NON-AUTORISEE"
ARETE_INCONNUE = "REJ-MNEMO-GRAPHE-ARETE-INCONNUE"
ARETE_TRANSITION = "REJ-MNEMO-GRAPHE-ARETE-TRANSITION"
ARETE_CONFLIT = "REJ-MNEMO-GRAPHE-ARETE-CONFLIT"
REQUETE_TROP_LARGE = "REJ-MNEMO-GRAPHE-REQUETE-TROP-LARGE"
# -- leçons ------------------------------------------------------------------------------------------------------------
LECON_INCONNUE = "REJ-MNEMO-LECON-INCONNUE"
LECON_TRANSITION = "REJ-MNEMO-LECON-TRANSITION"
LECON_NON_EVALUEE = "REJ-MNEMO-LECON-NON-EVALUEE"
LECON_REGRESSION = "REJ-MNEMO-LECON-REGRESSION"
LECON_SUPPORT_INSUFFISANT = "REJ-MNEMO-LECON-SUPPORT-INSUFFISANT"
LECON_CANARI = "REJ-MNEMO-LECON-CANARI"


class ErreurMnemo(ValueError):
    """Refus typé : `code` stable (`REJ-MNEMO-…`), `detail` en français québécois, sans donnée personnelle."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code} : {detail}")
        self.code = code
        self.detail = detail

    def publique(self) -> dict[str, Any]:
        return {"code": self.code, "detail": self.detail}
