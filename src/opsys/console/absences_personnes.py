"""Lecture privée des absences signalées : source indépendante et admin SQL courant."""
from m4_field_ops import absences_durables

from . import memoire_chantier as autorite
from . import preparation_chantier as lecture

M4 = 'm04-field-ops'
NOM = 'm4_lire_absence_journaliere_console'


def _t0(deps, session, arguments):
    return lecture._appel(deps, session.utilisateur, M4, NOM, arguments)


def lire(cnx, deps, session, jour, personne_id, *, debut=0, limite=50, source_attendue=None):
    autorite._admin(cnx, session)
    try:
        source = absences_durables.capturer(cnx)
        arguments = dict(jour=jour, personne_id=personne_id, debut=debut, limite=limite,
                         source_attendue=source_attendue)
        attendu = absences_durables.projeter(source, **arguments)
        absences_durables.verifier_sortie(attendu)
        resultat = _t0(deps, session, arguments)
        if resultat != attendu:
            raise lecture.Refus('SOURCE-REPONSE-INCOHERENTE')
        if absences_durables.capturer(cnx).empreinte_snapshot_calculee != source.empreinte_snapshot_calculee:
            raise lecture.Refus('SOURCE-MODIFIEE')
        resultat = lecture._sortie(resultat)
    except absences_durables.Refus as exc:
        raise lecture.Refus(exc.code) from None
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, lecture.Refus):
            raise
        raise lecture.Refus('SOURCE-ABSENCE-INVALIDE') from None
    autorite._admin(cnx, session)
    return resultat
