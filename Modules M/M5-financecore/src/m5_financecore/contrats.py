from __future__ import annotations

CHAMPS_MOUVEMENT_FINANCIER = frozenset(
    {
        "montant",
        "type_mouvement",
        "horodatage",
        "classe_retention",
        "source",
    }
)
TYPE_MOUVEMENT = (
    "ENCAISSEMENT",
    "DECAISSEMENT",
    "PROVISION",
    "AJUSTEMENT",
    "AUTRE",
)
CLASSE_RETENTION = ("FISCALE_6_ANS", "STANDARD")

PALIER_APPROBATION = ("F0", "F1", "F2", "F3", "F4", "F5", "F6", "F7")
STATUT_APPROBATION = ("EN_ATTENTE", "APPROUVE", "REFUSE")

