"""Horloge du serveur, point unique pour les départements dont le paquet interdit toute horloge interne.

M3 (`m3_estimation.conformite`) refuse `datetime.now()` dans son paquet : ses modules purs reçoivent l'instant en
paramètre. L'adaptateur d'outils, lui, doit savoir « quelle heure est-il » pour juger qu'un barème est en vigueur ou
dater une déclaration : il le demande ICI, jamais à l'appelant (un agent qui choisirait l'heure choisirait aussi le
barème en vigueur). Les tests remplacent `maintenant` (`monkeypatch`), ce qui rend l'horloge injectée et les épreuves
déterministes.
"""

from __future__ import annotations

import datetime as dt


def maintenant() -> dt.datetime:
    """L'instant courant du serveur, en UTC, avec fuseau."""
    return dt.datetime.now(dt.UTC)
