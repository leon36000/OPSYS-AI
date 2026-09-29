"""Familles de confidentialité : ce qui identifie un client ou un lieu (lien, adresse, coordonnées, nom, identifiant).

Un texte public ne dit jamais où habite un client, comment le joindre, comment il s'appelle, ni quel dossier interne
il porte. Les motifs sont ceux de l'usine à contenu de M7 (PLAN T4.17), déplacés ici sans changement de sens.

Limites documentées :
  - Le nom du client n'est pas dans tous les dossiers. Le contrôle reconnaît les FORMES qui désignent un client
    (civilité + nom, « la famille X », « chez X Y », « client : X », @mention) et les noms qu'on lui fournit
    (`Contexte.noms_clients`). Un prénom seul, sans civilité, dans une phrase ordinaire, n'est pas détectable : la
    revue humaine reste la dernière barrière.
  - Un motif ne comprend pas le sens : la règle est nommée, donc contournable par une phrase plus sobre.

Module pur : aucune entrée-sortie.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from ._types import Contexte, Formes, a_motifs, extrait, plier, premier

_TYPES_VOIE = (
    r"(?:rue|avenue|av|boulevard|boul|bd|chemin|ch|rang|route|rte|montee|place|impasse|croissant|allee|cote|carre|"
    r"terrasse|promenade|cercle|ruelle)"
)

# -- adresse (sur le texte plié) ------------------------------------------------------------------------------
_ADRESSES_PLIEES = (
    # « 1234 rue des Érables », « 12, boul. Taschereau », « 12 3e avenue »
    re.compile(rf"\b\d{{1,5}}[a-z]?(?:\s*,\s*|\s+)(?:\d{{1,3}}(?:e|re|ere|eme|ieme)\s+)?{_TYPES_VOIE}\b"),
    re.compile(r"\b[a-z]\d[a-z]\s?-?\d[a-z]\d\b"),  # code postal canadien
    re.compile(r"[-+]?\d{1,3}[.,]\d{4,}\s*[,;/ ]\s*[-+]?\d{1,3}[.,]\d{4,}"),  # coordonnées GPS
    re.compile(r"\b(?:app|apt|appartement|bureau|suite|unite|local)\.?\s*#?\s*\d+\b"),
)
# Une voie NOMMÉE, sans numéro, désigne déjà un lieu : cherchée sur le texte qui garde ses majuscules.
_VOIE_NOMMEE = re.compile(
    r"\b(?i:rue|avenue|boulevard|boul\.|chemin|rang|montée|côte|impasse|croissant|allée)\s+"
    r"(?:(?i:de la|de l'|du|des|de|d')\s*)?[A-ZÀ-ÖØ-Þ]"
)

# -- coordonnées et liens (texte plié) -----------------------------------------------------------------------
_COURRIEL = re.compile(r"[a-z0-9._%+-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,}")
_TELEPHONE = re.compile(r"(?<!\d)(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}(?!\d)")
_LIEN = re.compile(r"https?://|\bwww\.|(?<![@\w-])[a-z0-9-]+\.(?:com|ca|org|net)\b")

# -- nom du client (texte normal : les majuscules comptent) ----------------------------------------------------
_MAJUSCULE = r"[A-ZÀ-ÖØ-Þ]"
_NOM = rf"{_MAJUSCULE}[\w'-]*"
_NOMS_CLIENT = (
    re.compile(rf"\b(?i:monsieur|madame|mademoiselle|mme|mlle|docteur|dre?|m\.)\s+{_NOM}"),
    re.compile(rf"\b(?i:la famille|famille)\s+{_NOM}"),
    re.compile(rf"\b(?i:chez)\s+{_NOM}(?:\s+{_NOM})?"),
    re.compile(rf"\b(?i:client(?:e)?s?|proprietaire|propriétaire)\s*:\s*{_MAJUSCULE}"),
    re.compile(r"(?<![\w.])@[\w.]{2,}"),
)


def lien(formes: Formes, _contexte: Contexte) -> str | None:
    return a_motifs((_LIEN,), formes.plie, "lien")


def adresse(formes: Formes, _contexte: Contexte) -> str | None:
    trouve = premier(_ADRESSES_PLIEES, formes.plie) or _VOIE_NOMMEE.search(formes.normal)
    if trouve is None:
        return None
    return f"adresse ou lieu précis : « {extrait(trouve.group(0))} » ; retire-le"


def coordonnees(formes: Formes, _contexte: Contexte) -> str | None:
    trouve = premier((_COURRIEL, _TELEPHONE), formes.plie)
    if trouve is None:
        return None
    return f"courriel ou téléphone : « {extrait(trouve.group(0))} » ; retire-le"


def _nom_dans(noms_clients: Iterable[str], plie: str) -> bool:
    for nom in noms_clients:
        cherche = plier(nom)
        if len(cherche) >= 4 and re.search(rf"(?<![a-z0-9]){re.escape(cherche)}(?![a-z0-9])", plie):
            return True
    return False


def nom_client(formes: Formes, contexte: Contexte) -> str | None:
    trouve = premier(_NOMS_CLIENT, formes.normal_sans_marque)
    if trouve is not None:
        return f"nom de client : « {extrait(trouve.group(0))} » ; désigne « le client »"
    if _nom_dans(contexte.noms_clients, formes.plie_sans_marque):
        return "un nom fourni comme confidentiel apparaît dans le texte ; retire-le"
    return None


def identifiant_interne(formes: Formes, contexte: Contexte) -> str | None:
    for identifiant in contexte.identifiants:
        cherche = plier(identifiant)
        if len(cherche) >= 4 and cherche in formes.plie:
            return "un identifiant interne du chantier apparaît dans le texte"
    return None
