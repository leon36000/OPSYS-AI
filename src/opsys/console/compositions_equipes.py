"""Lecture privée des compositions déclarées : source indépendante et admin SQL courant."""
from m4_field_ops import composition_durable

from . import memoire_chantier as autorite
from . import preparation_chantier as lecture

M4 = 'm04-field-ops'
NOM = 'm4_lire_composition_journaliere_console'


def _t0(deps, session, arguments):
    return lecture._appel(deps, session.utilisateur, M4, NOM, arguments)


def lire(cnx, deps, session, jour, equipe_id, *, debut=0, limite=50, source_attendue=None):
    autorite._admin(cnx, session)
    try:
        source = composition_durable.capturer(cnx)
        arguments = dict(jour=jour, equipe_id=equipe_id, debut=debut, limite=limite, source_attendue=source_attendue)
        attendu = composition_durable.projeter(source, **arguments)
        composition_durable.verifier_sortie(attendu)
        resultat = _t0(deps, session, arguments)
        if resultat != attendu:
            raise lecture.Refus('SOURCE-REPONSE-INCOHERENTE')
        if composition_durable.capturer(cnx).empreinte_snapshot_calculee != source.empreinte_snapshot_calculee:
            raise lecture.Refus('SOURCE-MODIFIEE')
        resultat = lecture._sortie(resultat)
    except composition_durable.Refus as exc:
        raise lecture.Refus(exc.code) from None
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, lecture.Refus):
            raise
        raise lecture.Refus('SOURCE-COMPOSITION-INVALIDE') from None
    autorite._admin(cnx, session)
    return resultat

