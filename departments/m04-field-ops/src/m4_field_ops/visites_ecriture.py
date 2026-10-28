"""Adaptateur SQLite transactionnel privé des prévisions explicitement ancrées."""
import json

from sqlalchemy import LargeBinary, cast, func, select
from opsys import stockage
from opsys.etat import journaliser
from opsys.stockage.maillons import copier_maillons_avec_metadonnees
from opsys.stockage.schema import REGISTRES

from . import journal_durable, visites_durables as domaine
from .registre import Registre

DEPARTEMENT = 'm04-field-ops'


def capturer_visites(cnx):
    if cnx is None or cnx is not stockage.connexion_courante() or cnx.dialect.name != 'sqlite':
        raise domaine.Refus('INSTANCE-NON-QUALIFIEE')
    condition = (REGISTRES.c.departement == DEPARTEMENT) & (REGISTRES.c.registre == domaine.REGISTRE)
    nombre, octets = cnx.execute(select(func.count(), func.sum(func.length(cast(REGISTRES.c.maillon, LargeBinary))))
                                .select_from(REGISTRES).where(condition)).one()
    if nombre > domaine.MAX_SOURCES or (octets or 0) > domaine.MAX_OCTETS:
        raise domaine.Refus('SOURCES-TROP-VOLUMINEUSES')
    return copier_maillons_avec_metadonnees(cnx, departement=DEPARTEMENT, registre=domaine.REGISTRE)


def _autorite(autoriser, auteur):
    if autoriser() != auteur:
        raise domaine.Refus('IDENTITE')


def enregistrer(cnx, arguments, auteur, mutation, horodatage, autoriser, limite_sortie=65536):
    """Appel depuis une transaction SQLite ; l'autorité est réévaluée après append."""
    principal = journal_durable.capturer(cnx)
    source = capturer_visites(cnx)
    copie_principal = Registre([r.maillon for r in principal.lignes])
    copie = Registre([r.maillon for r in source.lignes])
    attendu = domaine.prevoir(copie_principal, copie, **arguments, auteur=auteur,
                               mutation=mutation, horodatage=horodatage)
    if type(limite_sortie) is not int or limite_sortie <= 0 or len(
            json.dumps({'ok': True, 'resultat': attendu}, ensure_ascii=False).encode()) > min(limite_sortie, 65536):
        raise domaine.Refus('SORTIE-TROP-VOLUMINEUSE')
    if attendu['rejoue']:
        _autorite(autoriser, auteur)
        if (journal_durable.capturer(cnx).empreinte_snapshot_calculee != principal.empreinte_snapshot_calculee
                or capturer_visites(cnx).empreinte_snapshot_calculee != source.empreinte_snapshot_calculee):
            raise domaine.Refus('SOURCE-MODIFIEE')
        return attendu
    prepare = copie.lire()[-1]
    with cnx.begin_nested():
        _autorite(autoriser, auteur)
        if (journal_durable.capturer(cnx).empreinte_snapshot_calculee != principal.empreinte_snapshot_calculee
                or capturer_visites(cnx).empreinte_snapshot_calculee != source.empreinte_snapshot_calculee):
            raise domaine.Refus('SOURCE-MODIFIEE')
        resultat = domaine.prevoir(Registre(stockage.maillons(DEPARTEMENT, 'principal')),
                                   Registre(stockage.maillons(DEPARTEMENT, domaine.REGISTRE)),
                                   **arguments, auteur=auteur, mutation=mutation, horodatage=horodatage)
        if resultat != attendu:
            raise domaine.Refus('SOURCE-MODIFIEE')
        journaliser(cnx, auteur['personne'], 'm4.visite_prevue', resultat['visite_id'],
                    {'intervention_id': arguments['ancre']['intervention_id'],
                     'revision': resultat['revision'], 'empreinte_arguments': mutation['empreinte_arguments']})
        apres = capturer_visites(cnx)
        if (len(apres.lignes) != len(source.lignes) + 1 or apres.lignes[:-1] != source.lignes
                or apres.lignes[-1].maillon != prepare
                or journal_durable.capturer(cnx).empreinte_snapshot_calculee != principal.empreinte_snapshot_calculee):
            raise domaine.Refus('SOURCE-MODIFIEE')
        _autorite(autoriser, auteur)
        return resultat
