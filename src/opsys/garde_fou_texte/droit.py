"""Famille « avis légal » : ce qu'un texte destiné au public ou à un client ne dit jamais du droit.

Une entreprise de rénovation n'est pas un cabinet : « M1 ne doit jamais donner un avis légal, fiscal ou contractuel »
(DEFINITION-PRODUIT §7, règles dures de M1).
Le motif est celui que M1 appliquait au seul gabarit de plainte (PLAN T4.5, `plaintes.py`) ; il est devenu une famille
du socle pour que chaque texte de M1 le passe, pas seulement ce gabarit.

Le motif lit du VOCABULAIRE juridique, pas le sens : « nous consultons notre avocat » est refusé comme « vous avez
droit à un recours ». Le département choisit à quels textes il applique la famille : un texte qui doit NOMMER un sujet
légal pour un humain (« le client parle de son avocat ») ne peut pas la passer.

Lecture en minuscules, accents conservés (les formes avec et sans accent sont listées).

Module pur : aucune entrée-sortie.
"""

from __future__ import annotations

import re

from ._types import Contexte, Formes

_AVIS_LEGAL = re.compile(
    r"\b(?:"
    r"vous\s+avez\s+(?:le\s+)?droit|vos\s+droits?|selon\s+la\s+loi|en\s+vertu\s+(?:de|du)|"
    r"l[ée]gal(?:e|es|ement)?|ill[ée]gal(?:e|es|ement)?|juridique(?:s|ment)?|tribunal|tribunaux|poursuite(?:s)?|poursuivre|"
    r"recours|mise\s+en\s+demeure|avocat(?:e|s|es)?|code\s+civil|protection\s+du\s+consommateur|"
    r"responsabilit[ée]\s+(?:civile|l[ée]gale|contractuelle)|contractuel(?:le|s|les|lement)?|prescription"
    r")\b",
    re.IGNORECASE,
)


def avis_legal(formes: Formes, _contexte: Contexte) -> str | None:
    trouve = _AVIS_LEGAL.search(formes.droit)
    if trouve is None:
        return None
    return f"avis légal : « {trouve.group(0)} » ; retire tout ce qui parle de droit"
