"""Port privé du journal M4 : vrai T0, projection attendue et admin courant, sans écran."""
from m4_field_ops import journal_durable

from . import memoire_chantier as autorite
from . import preparation_chantier as lecture

M4 = 'm04-field-ops'
NOM = 'm4_lire_journal_quotidien'


def _t0(deps, session, arguments):
    return lecture._appel(deps, session.utilisateur, M4, NOM, arguments)


def lire(cnx, deps, session, jour, *, debut=0, limite=50, source_attendue=None):
    autorite._admin(cnx, session)
    try:
        source = journal_durable.capturer(cnx)
        arguments = dict(jour=jour, debut=debut, limite=limite, source_attendue=source_attendue)
        attendu = journal_durable.projeter(source, **arguments)
        journal_durable.verifier_sortie(attendu)
        resultat = _t0(deps, session, arguments)
        if resultat != attendu:
            raise lecture.Refus('SOURCE-REPONSE-INCOHERENTE')
        if journal_durable.capturer(cnx).empreinte_snapshot_calculee != source.empreinte_snapshot_calculee:
            raise lecture.Refus('SOURCE-MODIFIEE')
        resultat = lecture._sortie(resultat)
    except journal_durable.Refus as exc:
        raise lecture.Refus(exc.code) from None
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, lecture.Refus):
            raise
        raise lecture.Refus('SOURCE-JOURNAL-INVALIDE') from None
    autorite._admin(cnx, session)
    return resultat
