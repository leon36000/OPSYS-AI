"""Types du garde-fou de texte : ce qu'une règle rend, ce que le contrôle sait du texte, les formes qu'il en lit.

Module pur : aucune entrée-sortie.
"""

from __future__ import annotations

import dataclasses
import functools
import re
import unicodedata
from collections.abc import Callable, Iterable


@dataclasses.dataclass(frozen=True)
class Violation:
    """Une règle violée : sa famille, son code de refus stable, et ce qui l'a déclenchée (jamais muet : le détail dit
    quoi retirer). Un code de refus par famille : le code suffit à nommer la règle dans une réponse d'outil."""

    famille: str
    regle: str
    detail: str

    def en_dict(self) -> dict[str, str]:
        return {"regle": self.regle, "detail": self.detail}


@dataclasses.dataclass(frozen=True)
class Contexte:
    """Ce que le contrôle sait de ce texte, tiré du profil de l'entreprise et du dossier, jamais de l'appelant.

    `garanties_validees` : énoncés de garantie approuvés par l'entreprise, recopiés tels quels. `noms_de_marque` : le
    nom commercial, qui peut contenir « garantie » ou « meilleur » sans que le texte en fasse une promesse.
    `noms_clients` : noms de personnes qui ne doivent jamais apparaître. `identifiants` : identifiants internes du
    dossier (chantier, lead, devis, technicien). `longueur_max` : plafond de la plateforme, `None` pour ne pas en
    contrôler. Un nom ou un identifiant de moins de quatre caractères n'est jamais cherché : il se confondrait avec
    un mot courant. Les familles qui n'ont pas besoin du contexte l'ignorent : un département qui n'en fournit pas
    n'a rien à configurer.
    """

    garanties_validees: tuple[str, ...] = ()
    noms_de_marque: tuple[str, ...] = ()
    noms_clients: tuple[str, ...] = ()
    identifiants: tuple[str, ...] = ()
    longueur_max: int | None = None


def plier(texte: str) -> str:
    """Forme de recherche : compatibilité Unicode (espaces insécables, exposants), sans accents, minuscules,
    apostrophes droites, espaces réduits. Les mots-clés y sont cherchés ; le texte lui-même n'est pas modifié."""
    normal = unicodedata.normalize("NFKC", texte).replace("’", "'").replace("‘", "'")
    sans_accents = "".join(c for c in unicodedata.normalize("NFD", normal) if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sans_accents).casefold()


def normal(texte: str) -> str:
    """Forme qui garde les majuscules et les accents (noms propres), espaces réduits."""
    forme = unicodedata.normalize("NFKC", texte).replace("’", "'").replace("‘", "'")
    return re.sub(r"\s+", " ", forme)


def apostrophes_droites(texte: str) -> str:
    """Remplace l'apostrophe courbe par l'apostrophe droite, sans rien d'autre : la forme que lisent les motifs
    écrits pour un message à un client (accents, casse et espaces conservés)."""
    return texte.replace("’", "'")


def masquer(texte: str, morceaux: Iterable[str], *, avec_plier: bool) -> str:
    """Remplace par une espace chaque morceau (nom de marque, énoncé validé) trouvé dans `texte`."""
    resultat = texte
    for morceau in morceaux:
        cherche = plier(morceau) if avec_plier else normal(morceau)
        if cherche.strip():
            resultat = re.sub(re.escape(cherche), " ", resultat, flags=0 if avec_plier else re.IGNORECASE)
    return resultat


class Formes:
    """Les formes d'un texte que les règles lisent, calculées à la demande et une seule fois : une famille qui ne lit
    que `droit` ne paie ni le pliage des accents ni le masquage de la marque."""

    def __init__(self, texte: str, contexte: Contexte) -> None:
        self.texte = texte
        self._contexte = contexte

    @functools.cached_property
    def droit(self) -> str:
        return apostrophes_droites(self.texte)

    @functools.cached_property
    def plie(self) -> str:
        return plier(self.texte)

    @functools.cached_property
    def normal(self) -> str:
        return normal(self.texte)

    @functools.cached_property
    def plie_sans_marque(self) -> str:
        return masquer(self.plie, self._contexte.noms_de_marque, avec_plier=True)

    @functools.cached_property
    def normal_sans_marque(self) -> str:
        return masquer(self.normal, self._contexte.noms_de_marque, avec_plier=False)

    @functools.cached_property
    def plie_sans_garantie(self) -> str:
        return masquer(self.plie_sans_marque, self._contexte.garanties_validees, avec_plier=True)


# Une règle lit les formes et le contexte, et rend ce qu'il faut retirer (une phrase), ou `None` si le texte passe.
Detecteur = Callable[[Formes, Contexte], str | None]


@dataclasses.dataclass(frozen=True)
class Famille:
    """Une famille de règles, nommée. `nom` : l'identifiant qu'un département cite pour l'appliquer. `regle` : le code
    de refus stable que le refus rend. `libelle` : ce que la famille interdit, en une phrase (montré à l'agent qui
    rédige et repris dans le refus). `bloquante` : si elle refuse, aucune autre famille n'est lue (un texte vide n'a
    rien d'autre à contrôler)."""

    nom: str
    regle: str
    libelle: str
    detecter: Detecteur = dataclasses.field(compare=False, repr=False)
    bloquante: bool = False


EXTRAIT_MAX = 48


def extrait(texte: str) -> str:
    propre = texte.strip()
    return propre if len(propre) <= EXTRAIT_MAX else propre[: EXTRAIT_MAX - 1] + "…"


def premier(motifs: Iterable[re.Pattern[str]], texte: str) -> re.Match[str] | None:
    for motif in motifs:
        trouve = motif.search(texte)
        if trouve is not None:
            return trouve
    return None


def a_motifs(motifs: Iterable[re.Pattern[str]], texte: str, quoi: str) -> str | None:
    """Le détail d'un refus quand un motif trouve quelque chose dans `texte`, sinon `None`."""
    trouve = premier(motifs, texte)
    if trouve is None:
        return None
    return f"{quoi} : « {extrait(trouve.group(0))} » ; retire-le"
