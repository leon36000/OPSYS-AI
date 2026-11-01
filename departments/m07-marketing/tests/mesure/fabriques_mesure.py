"""Fabriques communes aux tests de la mesure marketing. Données FICTIVES."""

from __future__ import annotations

from sqlalchemy import select

from opsys import stockage
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_SORTANTS


def evenements_de(type_evenement: str) -> list[tuple[str, dict]]:
    with stockage.transaction() as cnx:
        lignes = (
            cnx.execute(
                select(EVENEMENTS_SORTANTS)
                .where(EVENEMENTS_SORTANTS.c.type_evenement == type_evenement)
                .order_by(EVENEMENTS_SORTANTS.c.evenement_id)
            )
            .mappings()
            .all()
        )
    return [(ligne["evenement_id"], codec.decoder(ligne["charge"])) for ligne in lignes]
