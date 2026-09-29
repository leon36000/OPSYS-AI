"""Familles de promesse d'un texte public : prix ou offre, chiffre sans source, garantie, date, exagération.

Ce sont les règles de l'usine à contenu de M7 (PLAN T4.17), déplacées ici sans changement de sens. Elles sont
STRICTES : un texte public ne parle jamais d'argent, de délai ni de garantie, même sans montant. Une réponse à un
client ne les applique pas (« nous étudions votre budget » y est permis) : elle a ses propres familles
(`engagements.py`), plus étroites.

Un motif ne comprend pas le sens : « meilleur » est refusé même dans une phrase inoffensive. C'est le prix du
fail-closed ; la règle est nommée, donc contournable par une phrase plus sobre. Le nom de marque et les garanties
validées de l'entreprise (`Contexte`) sont masqués avant la lecture : une marque qui contient « garantie » ne fait
pas une promesse.

Module pur : aucune entrée-sortie.
"""

from __future__ import annotations

import re

from ._types import Contexte, Formes, a_motifs

_MOIS = r"(?:janvier|fevrier|mars|avril|mai|juin|juillet|aout|septembre|octobre|novembre|decembre)"
_JOURS = r"(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)"

# -- prix (texte plié) --------------------------------------------------------------------------------------------
_PRIX = (
    # Le départ d'une suite de chiffres et d'espaces seulement (précédée ni d'un chiffre ni d'une espace : jamais au
    # milieu d'un nombre, d'un groupe « 4 500 » ou après plusieurs espaces, que le masque d'une marque laisse) et un
    # quantificateur possessif : le temps reste linéaire, même sur un texte fait uniquement de chiffres et d'espaces.
    re.compile(
        r"(?<![\d ])[ ]*+\d[\d ]*+(?:[.,]\d+)?\s*(?:\$|cad\b|dollars?\b|piastres?\b|€|euros?\b)"
    ),
    re.compile(r"[$€]\s*\d"),
    re.compile(
        r"\b(?:prix|tarif\w*|cout\w*|budget\w*|fourchette\w*|gratuit\w*|sans frais|rabais|escompte\w*|promo\w*|"
        r"soldes?|financement\w*|versements?|mensualit\w*|paiements?)\b"
    ),
)

# -- chiffres avec unité : jamais produits par un modèle (AGENTS.md), sauf sourcés par un outil ------------------
_CHIFFRE = re.compile(
    r"\b\d+(?:[.,]\d+)?\s*(?:%|pi2|m2|pieds?\b|pi\b|pouces?\b|po\b|metres?\b|m\b|cm\b|mm\b|km\b|kg\b|lb\b|"
    r"livres?\b|litres?\b|heures?\b|h\b|jours?\b|semaines?\b|mois\b|ans?\b|annees?\b|minutes?\b|min\b)"
)

# -- garantie (texte plié, après masquage des énoncés validés et du nom de marque) -------------------------------
_GARANTIE = re.compile(
    r"\bgarant\w*|\ba vie\b|\bsatisfait ou rembours\w*|\brembours\w*|\bsans risque\b|\bzero risque\b|"
    r"\baucun risque\b|\bresultats? assures?\b"
)

# -- date et promesse de délai (texte plié) ----------------------------------------------------------------------
_DATES = (
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
    re.compile(r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b"),
    re.compile(rf"\b\d{{1,2}}(?:er)?\s+{_MOIS}\b"),
    re.compile(r"\ble \d{1,2}(?:er)?\b"),
    re.compile(rf"\ble\s+{_JOURS}\b"),
    re.compile(rf"\b{_JOURS}\s+(?:prochain|dernier)\b"),
    re.compile(r"\b(?:demain|apres-demain)\b"),
    re.compile(
        rf"\b(?:la semaine|le mois|l'an|l'annee|la fin de semaine|le week-end)\s+prochaine?\b|"
        rf"\bprochaine?s?\s+(?:semaine|mois|annee|fin de semaine|week-end|jour|{_JOURS})\b"
    ),
    re.compile(r"\bd'ici\b|\bau plus tard\b|\bavant le\b"),
    re.compile(r"\b(?:dans|sous)\s+(?:\d+|un|une|deux|trois|quatre|cinq|quelques)\s+(?:jours?|semaines?|mois|heures?|minutes?)\b"),
    re.compile(rf"\bdes\s+(?:{_JOURS}|maintenant|aujourd'hui)\b"),
)

# -- exagération (texte plié, après masquage du nom de marque) ---------------------------------------------------
_EXAGERATION = (
    re.compile(
        r"\bmeilleur\w*|\bnumero (?:1|un)\b|\bno\.? ?1\b|\bn° ?1\b|#\s?1\b|\bimbattable\w*|\bincomparable\w*|"
        r"\binegal\w*|\bsans equivalent\b|\bunique au quebec\b|\bleader\w*|\b100 ?%|\bparfait\w*|"
        r"\bsans faute\b|\binfaillible\w*|\birreprochable\w*|\bmoins cher\b|\ble plus bas\b|"
        r"\bla seule?\b|\ble seul\b"
    ),
)


def prix_offre(formes: Formes, _contexte: Contexte) -> str | None:
    return a_motifs(_PRIX, formes.plie_sans_marque, "prix ou offre")


def chiffre_non_source(formes: Formes, _contexte: Contexte) -> str | None:
    return a_motifs((_CHIFFRE,), formes.plie_sans_marque, "chiffre non sourcé")


def garantie_non_validee(formes: Formes, _contexte: Contexte) -> str | None:
    return a_motifs((_GARANTIE,), formes.plie_sans_garantie, "garantie non validée")


def promesse_de_date(formes: Formes, _contexte: Contexte) -> str | None:
    return a_motifs(_DATES, formes.plie_sans_marque, "date ou promesse de délai")


def exageration(formes: Formes, _contexte: Contexte) -> str | None:
    return a_motifs(_EXAGERATION, formes.plie_sans_marque, "exagération")
