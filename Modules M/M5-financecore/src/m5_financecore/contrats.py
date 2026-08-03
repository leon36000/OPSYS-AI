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

