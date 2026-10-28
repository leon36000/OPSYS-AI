"""Adaptation SQL privée du journal pur : snapshot borné avant tout décodage."""
import json

from sqlalchemy import LargeBinary, cast, func, select

from opsys import contexte, stockage
from opsys.stockage.maillons import copier_maillons_avec_metadonnees
from opsys.stockage.schema import REGISTRES

from . import journal_quotidien
from .registre import Registre

DEPARTEMENT = 'm04-field-ops'


class Refus(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def capturer(cnx):
    if cnx is None or cnx is not stockage.connexion_courante() or cnx.dialect.name != 'sqlite':
        raise Refus('INSTANCE-NON-QUALIFIEE')
    condition = (REGISTRES.c.departement == DEPARTEMENT) & (REGISTRES.c.registre == 'principal')
    nombre, octets = cnx.execute(select(func.count(), func.sum(func.length(cast(REGISTRES.c.maillon, LargeBinary))))
                                .select_from(REGISTRES).where(condition)).one()
    if nombre > journal_quotidien.MAX_SOURCES or (octets or 0) > journal_quotidien.MAX_OCTETS:
        raise Refus('SOURCE-TROP-VOLUMINEUSE')
    return copier_maillons_avec_metadonnees(cnx, departement=DEPARTEMENT, registre='principal')


def projeter(snapshot, jour, *, debut=0, limite=50, source_attendue=None):
    resultat = journal_quotidien.lire(Registre([r.maillon for r in snapshot.lignes]), jour,
                                    debut=debut, limite=limite, source_attendue=source_attendue)
    resultat['source_snapshot'] = snapshot.empreinte_snapshot_calculee
    return resultat


def verifier_sortie(resultat):
    borne = contexte.limite_sortie()
    borne = min(65536, borne) if borne is not None else 65536
    enveloppe = {'ok': True, 'resultat': {'accepte': True, 'resultat': resultat}}
    if len(json.dumps(enveloppe, ensure_ascii=False, allow_nan=False).encode()) > borne:
        raise Refus('SORTIE-TROP-VOLUMINEUSE')
