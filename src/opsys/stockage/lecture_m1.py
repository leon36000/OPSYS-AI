"""Borne la lecture du registre M1 en SQLite avant tout décodage."""

from sqlalchemy import LargeBinary, cast, func, select

from .schema import REGISTRES

MAX_LIGNES = 10_000
MAX_MAILLON_OCTETS = 65_536
MAX_TOTAL_OCTETS = 8_388_608


def borner(
    cnx, *, max_lignes=MAX_LIGNES, max_maillon_octets=MAX_MAILLON_OCTETS,
    max_total_octets=MAX_TOTAL_OCTETS,
) -> int:
    """Refuse la source entière si une limite inclusive est dépassée."""
    if cnx.dialect.name != "sqlite" or not cnx.in_transaction():
        raise RuntimeError("source non qualifiée")
    filtre = (REGISTRES.c.departement == "m01-front-office") & (REGISTRES.c.registre == "principal")
    octets = func.length(cast(REGISTRES.c.maillon, LargeBinary))
    count, maxi, total = cnx.execute(
        select(func.count(), func.coalesce(func.max(octets), 0), func.coalesce(func.sum(octets), 0))
        .select_from(REGISTRES).where(filtre)
    ).one()
    if (
        type(count) is not int or count > max_lignes
        or type(maxi) is not int or maxi > max_maillon_octets
        or type(total) is not int or total > max_total_octets
    ):
        raise RuntimeError("source non qualifiée")
    return count
