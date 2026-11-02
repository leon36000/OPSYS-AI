"""Horloge du serveur, point unique pour les départements dont le paquet interdit toute horloge interne.

M3 (`m3_estimation.conformite`) refuse `datetime.now()` dans son paquet : ses modules purs reçoivent l'instant en
paramètre. L'adaptateur d'outils, lui, doit savoir « quelle heure est-il » pour juger qu'un barème est en vigueur ou
dater une déclaration : il le demande ICI, jamais à l'appelant (un agent qui choisirait l'heure choisirait aussi le
barème en vigueur). Les tests remplacent `maintenant` (`monkeypatch`), ce qui rend l'horloge injectée et les épreuves
déterministes.
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Le fuseau de l'ENTREPRISE : celui dans lequel « aujourd'hui » se calcule pour les départements sans horloge (le
# planificateur le donne à M5 : `Ports.fuseau`) et celui dans lequel M8 date le JOUR d'un constat (minuit local, pas
# minuit UTC). Une seule source : le planificateur et M8 ne peuvent donc pas compter deux jours différents.
FUSEAU_ENTREPRISE = "America/Toronto"


def maintenant() -> dt.datetime:
    """L'instant courant du serveur, en UTC, avec fuseau."""
    return dt.datetime.now(dt.UTC)


def fuseau_entreprise() -> str:
    """Le fuseau de l'entreprise (nom de la base des fuseaux), vérifié lisible : un fuseau inconnu est une erreur
    d'installation qui se dit, jamais un repli silencieux sur l'UTC."""
    try:
        ZoneInfo(FUSEAU_ENTREPRISE)
    except (ZoneInfoNotFoundError, ValueError, OSError) as erreur:
        raise RuntimeError(
            f"REJ-FUSEAU-ILLISIBLE : {FUSEAU_ENTREPRISE!r} n'est pas dans la base des fuseaux"
        ) from erreur
    return FUSEAU_ENTREPRISE
