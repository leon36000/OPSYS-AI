"""Découpage déterministe d'un texte en fragments, avec leur emplacement exact (page, section, décalages).

Même texte, même découpage, toujours : aucune horloge, aucun modèle, aucun hasard. Un fragment ne franchit jamais une
section (titre markdown `#`…`######`) : les jugements de pertinence et les citations s'attachent donc à un titre précis.
Invariant vérifié à chaque lecture d'intégrité : `fragment.texte == pages[page - 1][debut:fin]`.

Réglage de phase 1 : cible de 700 caractères, 1 100 au plus. Un paragraphe plus long est coupé à la fin d'une phrase ou
d'une ligne, sinon au dernier espace. Ces tailles ne sont pas des optimums mesurés ; elles seront recalibrées avec le
modèle d'embeddings retenu (voir CONNAISSANCES.md, « Limites »).
"""

from __future__ import annotations

import dataclasses
import hashlib
import re

from .codes import ENTREE_INVALIDE, TEXTE_TROP_LONG, ErreurConnaissances
from .modele import FRAGMENTS_MAX

CIBLE = 700
MAXI = 1100
SEPARATEUR_SECTION = " › "
_TITRE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
_FIN_PHRASE = re.compile(r"(?<=[.!?;:])[ \t]+|\n")


@dataclasses.dataclass(frozen=True)
class Fragment:
    rang: int
    page: int
    section: str | None
    debut: int
    fin: int
    texte: str
    sha256: str


def empreinte(texte: str) -> str:
    return hashlib.sha256(texte.encode("utf-8")).hexdigest()


def _blocs(page: str) -> list[tuple[int, int, str | None]]:
    """Paragraphes `(début, fin, section)` d'une page : séparés par une ligne vide ou un titre."""
    blocs: list[tuple[int, int, str | None]] = []
    pile: list[tuple[int, str]] = []
    debut = fin = -1
    section: str | None = None

    def fermer() -> None:
        nonlocal debut, fin
        if debut >= 0:
            blocs.append((debut, fin, section))
        debut = fin = -1

    position = 0
    for ligne in page.split("\n"):
        suivante = position + len(ligne) + 1
        titre = _TITRE.match(ligne)
        if titre:
            fermer()
            niveau, intitule = len(titre.group(1)), titre.group(2).strip()
            while pile and pile[-1][0] >= niveau:
                pile.pop()
            pile.append((niveau, intitule))
            section = SEPARATEUR_SECTION.join(t for _, t in pile)
        elif not ligne.strip():
            fermer()
        else:
            if debut < 0:
                debut = position + (len(ligne) - len(ligne.lstrip()))
            fin = position + len(ligne.rstrip())
        position = suivante
    fermer()
    return blocs


def _couper(page: str, debut: int, fin: int) -> list[tuple[int, int]]:
    """Découpe un paragraphe de plus de MAXI caractères en tranches d'au plus MAXI, à des frontières naturelles."""
    tranches: list[tuple[int, int]] = []
    courant = debut
    while fin - courant > MAXI:
        limite = courant + MAXI
        coupes = [m.end() for m in _FIN_PHRASE.finditer(page, courant, limite)]
        if coupes:
            point = coupes[-1]
        else:
            espace = page.rfind(" ", courant + 1, limite)
            point = espace + 1 if espace > courant else limite
        arret = point
        while arret > courant and page[arret - 1].isspace():
            arret -= 1
        if arret <= courant:  # tranche vide : on avance quand même, jamais de boucle infinie
            arret = point = limite
        tranches.append((courant, arret))
        courant = point
        while courant < fin and page[courant].isspace():
            courant += 1
    if courant < fin:
        tranches.append((courant, fin))
    return tranches


def decouper(pages: list[str]) -> list[Fragment]:
    """Fragments de toutes les pages, rangs consécutifs depuis 0."""
    if not pages or any(not isinstance(p, str) for p in pages):
        raise ErreurConnaissances(ENTREE_INVALIDE, "pages de texte attendues")
    resultat: list[Fragment] = []
    for numero, page in enumerate(pages, start=1):
        courant: tuple[int, int, str | None] | None = None
        morceaux: list[tuple[int, int, str | None]] = []
        for debut, fin, section in _blocs(page):
            for d, f in (_couper(page, debut, fin) if fin - debut > MAXI else [(debut, fin)]):
                morceaux.append((d, f, section))
        for debut, fin, section in morceaux:
            if courant is not None and courant[2] == section and fin - courant[0] <= CIBLE:
                courant = (courant[0], fin, section)
                continue
            if courant is not None:
                resultat.append(_fragment(len(resultat), numero, page, courant))
            courant = (debut, fin, section)
        if courant is not None:
            resultat.append(_fragment(len(resultat), numero, page, courant))
        if len(resultat) > FRAGMENTS_MAX:
            raise ErreurConnaissances(TEXTE_TROP_LONG, f"plus de {FRAGMENTS_MAX} fragments pour une version")
    return resultat


def _fragment(rang: int, numero: int, page: str, morceau: tuple[int, int, str | None]) -> Fragment:
    debut, fin, section = morceau
    texte = page[debut:fin]
    return Fragment(rang, numero, section, debut, fin, texte, empreinte(texte))
