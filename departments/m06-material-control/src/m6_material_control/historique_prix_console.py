"""Lecture console privée de l’historique, source SQL bornée et autorité courante."""
from sqlalchemy import LargeBinary, cast, func, select

from opsys import stockage
from opsys.outils import Outil, valider_arguments
from opsys.stockage.maillons import copier_maillons_avec_metadonnees
from opsys.stockage.schema import REGISTRES

from . import catalogue_console as acces
from . import catalogue_materiaux, historique_prix

NOM = 'm6_lire_historique_prix_console'
REGISTRE = 'livre_prix'


def schema():
    return {'type': 'object', 'properties': {
        'materiau_id': {'type': 'string', 'minLength': 1, 'maxLength': 200},
        'fournisseur_id': {'type': 'string', 'minLength': 1, 'maxLength': 200},
        'debut': {'type': 'integer', 'minimum': 0, 'maximum': 10000},
        'limite': {'type': 'integer', 'minimum': 1, 'maximum': 50},
        'source_attendue': {'type': ['string', 'null'], 'pattern': '^[0-9a-f]{64}$'}},
        'required': ['materiau_id', 'fournisseur_id', 'debut', 'limite', 'source_attendue'],
        'additionalProperties': False}


def capturer(cnx):
    if cnx is None or cnx is not stockage.connexion_courante() or cnx.dialect.name != 'sqlite':
        raise historique_prix.Refus('INSTANCE-NON-QUALIFIEE')
    condition = (REGISTRES.c.departement == acces.DEPARTEMENT) & (REGISTRES.c.registre == REGISTRE)
    n, octets = cnx.execute(select(func.count(), func.sum(func.length(cast(REGISTRES.c.maillon, LargeBinary))))
                           .select_from(REGISTRES).where(condition)).one()
    if n > historique_prix.MAX_SOURCES or (octets or 0) > historique_prix.MAX_OCTETS:
        raise historique_prix.Refus('SOURCES-TROP-VOLUMINEUSES')
    return copier_maillons_avec_metadonnees(cnx, departement=acces.DEPARTEMENT, registre=REGISTRE)


def projeter(snapshot, arguments):
    resultat = historique_prix.lire([(x.rang, x.maillon) for x in snapshot.lignes], **arguments)
    # Empreinte SQL distincte du curseur du contenu métier; aucun timestamp n’est inventé.
    resultat['source_sql'] = snapshot.empreinte_snapshot_calculee
    return resultat


def _autorite(cnx, auteur):
    courant, signataire, _ = acces._autoriser()
    if courant is not cnx or signataire != auteur:
        raise catalogue_materiaux.CatalogueRefuse('IDENTITE')


def lire(materiau_id, fournisseur_id, debut=0, limite=25, source_attendue=None):
    try:
        cnx, auteur, _ = acces._autoriser()
        arguments = dict(materiau_id=materiau_id, fournisseur_id=fournisseur_id, debut=debut,
                         limite=limite, source_attendue=source_attendue)
        if valider_arguments(schema(), arguments) or (debut and source_attendue is None):
            raise historique_prix.Refus('ARGUMENTS')
        snapshot = capturer(cnx)
        resultat = acces._borner({'accepte': True, 'resultat': projeter(snapshot, arguments)})
        _autorite(cnx, auteur)
        if capturer(cnx).empreinte_snapshot_calculee != snapshot.empreinte_snapshot_calculee:
            raise historique_prix.Refus('SOURCE-MODIFIEE')
        _autorite(cnx, auteur)
        return resultat
    except (catalogue_materiaux.CatalogueRefuse, historique_prix.Refus) as exc:
        return {'accepte': False, 'raison': exc.code}
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        return {'accepte': False, 'raison': 'SOURCE-INVALIDE'}


def outil():
    return Outil(nom=NOM, description='Console admin privée : historique des prix déclarés du couple exact.',
                 parametres=schema(), fonction=lire)
