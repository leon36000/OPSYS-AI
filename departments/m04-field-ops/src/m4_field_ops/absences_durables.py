"""Snapshot SQL privé des absences administratives déclarées, borné avant décodage."""
from sqlalchemy import LargeBinary, cast, func, select

from opsys import stockage
from opsys.stockage.maillons import copier_maillons_avec_metadonnees
from opsys.stockage.schema import REGISTRES

from . import absences_journalieres as domaine
from .journal_durable import Refus
from .journal_durable import verifier_sortie as verifier_sortie
from .registre import Registre

DEPARTEMENT = 'm04-field-ops'


def capturer(cnx):
    if cnx is None or cnx is not stockage.connexion_courante() or cnx.dialect.name != 'sqlite':
        raise Refus('INSTANCE-NON-QUALIFIEE')
    condition = (REGISTRES.c.departement == DEPARTEMENT) & (REGISTRES.c.registre == domaine.REGISTRE)
    nombre, octets = cnx.execute(select(func.count(), func.sum(func.length(cast(REGISTRES.c.maillon, LargeBinary))))
                                .select_from(REGISTRES).where(condition)).one()
    if nombre > domaine.MAX_SOURCES or (octets or 0) > domaine.MAX_OCTETS:
        raise Refus('SOURCE-TROP-VOLUMINEUSE')
    return copier_maillons_avec_metadonnees(cnx, departement=DEPARTEMENT, registre=domaine.REGISTRE)


def projeter(snapshot, jour, personne_id, *, debut=0, limite=50, source_attendue=None):
    try:
        resultat = domaine.lire(Registre([r.maillon for r in snapshot.lignes]), jour, personne_id,
                                debut=debut, limite=limite, source_attendue=source_attendue)
    except domaine.Refus as exc:
        # L'auteur pur partage une classe avec l'autorité; les quotas restent des refus de volume.
        codes = {'SORTIE-TROP-VOLUMINEUSE': 'SORTIE-TROP-VOLUMINEUSE',
                 'SOURCES-TROP-VOLUMINEUSES': 'SOURCE-TROP-VOLUMINEUSE'}
        raise Refus(codes.get(exc.suffixe, 'SOURCE-INVALIDE')) from None
    resultat['source_snapshot'] = snapshot.empreinte_snapshot_calculee
    return resultat
