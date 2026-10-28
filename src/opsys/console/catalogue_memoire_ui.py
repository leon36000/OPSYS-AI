"""Indicateur privé de preuve M10, après autorité admin SQL fraîche."""
from datetime import UTC, datetime

from fastapi import HTTPException

from .. import catalogues_memoire, identite
from . import pages

LIBELLES = {'NON_PUBLIE': 'Version historique sans publication M10', 'EN_ATTENTE': 'Référence M10 en attente',
            'MEMORISE': 'Référence M10 mémorisée et vérifiée', 'ECHEC_LIVRAISON': 'Livraison M10 en échec',
            'QUARANTAINE': 'Référence M10 en quarantaine', 'CONFLIT': 'Preuve M10 incohérente',
            'A_VERIFIER': 'Preuve M10 à vérifier'}


def indicateur(session, cnx_factory, producteur, registre, source_hash):
    with cnx_factory() as cnx:
        personne = identite.personne_active(cnx, session.utilisateur)
        if (personne is None or 'admin' not in personne.roles
                or session.expire <= datetime.now(UTC).timestamp()):
            raise HTTPException(403, 'Accès admin requis')
        try:
            etat = catalogues_memoire.consulter(producteur, registre, source_hash)['etat']
        except (ValueError, KeyError, TypeError):
            etat = 'A_VERIFIER'
    return f'<p data-memoire="{pages.e(etat)}">{pages.e(LIBELLES[etat])}</p>'
