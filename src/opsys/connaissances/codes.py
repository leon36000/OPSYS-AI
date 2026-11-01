"""Refus typés des bases de connaissances : `REJ-CONN-…`, toujours avec ce qu'il faut corriger.

`ErreurConnaissances` est une `ValueError` : dans un appel d'outil, `opsys.outils.executer` la rend comme un refus
métier (`erreur: refus_metier`, `details: "REJ-CONN-… : …"`) et annule la transaction ; l'agent sait quoi corriger.
"""

from __future__ import annotations

from typing import Any

# -- entrées ---------------------------------------------------------------------------------------------------------
ENTREE_INVALIDE = "REJ-CONN-ENTREE-INVALIDE"
DEPARTEMENT_INCONNU = "REJ-CONN-DEPARTEMENT-INCONNU"
DOMAINE_IMMUABLE = "REJ-CONN-DOMAINE-IMMUABLE"
TYPE_NON_PRIS_EN_CHARGE = "REJ-CONN-TYPE-NON-PRIS-EN-CHARGE"
TEXTE_TROP_LONG = "REJ-CONN-TEXTE-TROP-LONG"
TEXTE_VIDE = "REJ-CONN-TEXTE-VIDE"
PLAFOND_VOLUME = "REJ-CONN-PLAFOND-VOLUME"
# -- PDF et extraction -------------------------------------------------------------------------------------------------
PDF_INDISPONIBLE = "REJ-CONN-PDF-INDISPONIBLE"
PDF_REFUSE = "REJ-CONN-PDF-REFUSE"
# -- cycle de vie ----------------------------------------------------------------------------------------------------
VERSION_INCONNUE = "REJ-CONN-VERSION-INCONNUE"
SOURCE_INCONNUE = "REJ-CONN-SOURCE-INCONNUE"
TRANSITION_INTERDITE = "REJ-CONN-TRANSITION-INTERDITE"
REVUE_INCOMPLETE = "REJ-CONN-REVUE-INCOMPLETE"
REVUE_HUMAINE_REQUISE = "REJ-CONN-REVUE-HUMAINE-REQUISE"
SEPARATION_DES_ROLES = "REJ-CONN-SEPARATION-DES-ROLES"
RAISON_REQUISE = "REJ-CONN-RAISON-REQUISE"
INTEGRITE = "REJ-CONN-INTEGRITE"
# -- lecture et recherche ----------------------------------------------------------------------------------------------
LECTURE_INTERDITE = "REJ-CONN-LECTURE-INTERDITE"
APPELANT_INCONNU = "REJ-CONN-APPELANT-INCONNU"
APPAREIL_FERME = "REJ-CONN-APPAREIL-FERME"
REQUETE_INVALIDE = "REJ-CONN-REQUETE-INVALIDE"
BACKEND_NON_PRIS_EN_CHARGE = "REJ-CONN-BACKEND-NON-PRIS-EN-CHARGE"
# -- isolation (contenu non fiable) ------------------------------------------------------------------------------------
FILTRE_INDISPONIBLE = "REJ-CONN-FILTRE-INDISPONIBLE"
# -- embeddings et reranker (ports)
# --------------------------------------------------------------------------------------
EMBEDDINGS_NON_RACCORDE = "REJ-CONN-EMBEDDINGS-NON-RACCORDE"
EMBEDDINGS_INVALIDE = "REJ-CONN-EMBEDDINGS-INVALIDE"
ESPACE_INCOMPATIBLE = "REJ-CONN-ESPACE-INCOMPATIBLE"
FOURNISSEUR_REFUSE = "REJ-CONN-FOURNISSEUR-REFUSE"
RERANKER_INVALIDE = "REJ-CONN-RERANKER-INVALIDE"


class ErreurConnaissances(ValueError):
    """Refus typé : `code` stable (`REJ-CONN-…`), `detail` en français québécois, sans contenu sensible."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code} : {detail}")
        self.code = code
        self.detail = detail

    def publique(self) -> dict[str, Any]:
        return {"code": self.code, "detail": self.detail}
