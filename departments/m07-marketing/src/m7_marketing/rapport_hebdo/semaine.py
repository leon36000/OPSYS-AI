"""La semaine du rapport hebdomadaire : toujours la dernière semaine ISO COMPLÈTE (lundi au dimanche) avant «
aujourd'hui ».

Tous les jours d'une même semaine donnent donc la MÊME semaine de rapport : c'est ce qui rend le rapport idempotent par
semaine, même si le planificateur passe chaque jour. Module pur, aucune horloge : « aujourd'hui » est fourni (date
locale de
l'entreprise).
"""

from __future__ import annotations

import datetime as dt
import re

_JOUR = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


def jour(valeur: str) -> dt.date:
    """Une date AAAA-MM-JJ canonique ; `ValueError` sinon."""
    if not isinstance(valeur, str) or not _JOUR.fullmatch(valeur):
        raise ValueError("date AAAA-MM-JJ attendue")
    d = dt.date.fromisoformat(valeur)
    if d.isoformat() != valeur:
        raise ValueError("date non canonique")
    return d


def lundi_de(d: dt.date) -> dt.date:
    return d - dt.timedelta(days=d.weekday())


def derniere_semaine_complete(aujourd_hui: dt.date) -> tuple[dt.date, dt.date]:
    """`(lundi, dimanche)` de la dernière semaine terminée avant `aujourd_hui`. Un lundi, c'est la semaine qui vient
    de finir."""
    lundi = lundi_de(aujourd_hui) - dt.timedelta(days=7)
    return lundi, lundi + dt.timedelta(days=6)


def semaine_de(debut: str) -> tuple[dt.date, dt.date]:
    """La semaine dont `debut` est le lundi ; `ValueError` si `debut` n'est pas un lundi."""
    d = jour(debut)
    if d.weekday() != 0:
        raise ValueError("le début d'une semaine de rapport est un lundi")
    return d, d + dt.timedelta(days=6)
