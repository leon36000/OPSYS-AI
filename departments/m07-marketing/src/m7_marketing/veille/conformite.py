"""Conformité d'un texte à publier face à la veille : aucune imitation de marque, aucune copie, la publicité
comparative signalée.

Un texte que Chloé s'apprête à proposer (publication, page, annonce) est contrôlé contre les concurrents DÉCLARÉS et
les textes
observés de leurs pages publiques :
- le NOM d'un concurrent ou son DOMAINE dans le texte est refusé (`REJ-VEILLE-MARQUE-CONCURRENT`) : ni imitation de
marque, ni
  publicité comparative nommée ;
- un recouvrement de 5-grammes de mots d'au moins 20 % avec un texte observé est refusé (`REJ-VEILLE-COPIE`) : on ne
recopie pas
  la page d'un concurrent, même retouchée ;
- un vocabulaire de comparaison (« meilleur que », « contrairement à », « plus cher que »…) n'est pas refusé mais
ACCOMPAGNÉ de la
  mention « À valider auprès d'un professionnel qualifié (avocat) » : la publicité comparative est encadrée par la loi.

Ce contrôle est une aide, pas un avis juridique ; il ne détecte ni un logo, ni une couleur, ni un slogan transformé.
Module pur.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping
from typing import Any

from .registre import Concurrent

MENTION_COMPARATIVE = "Publicité comparative : À valider auprès d'un professionnel qualifié (avocat)."
SEUIL_COPIE = 0.20
TAILLE_GRAMME = 5
_LIBELLES = {"nom": "le nom", "domaine": "le domaine", "marque": "le nom de marque"}
_COMPARATIF = re.compile(
    r"\b(?:meilleur(?:e|s|es)? que|mieux que|contrairement (?:a|aux)|plus cher(?:e|s|es)? que|moins cher(?:e|s|es)? "
    r"que|"
    r"a la difference d[eu']|compare[es]? a|par rapport a (?:nos|la|les) "
    r"(?:concurrent|concurrence)|superieur(?:e|s|es)? a|"
    r"pire que|plus lent(?:e|s|es)? que|better than|unlike|cheaper than|worse than)")


def plier(texte: str) -> str:
    sans_accents = "".join(c for c in unicodedata.normalize("NFKD", texte.lower()) if not unicodedata.combining(c))
    return re.sub(r"[’`´]", "'", sans_accents)


def mots(texte: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", plier(texte))


def _grammes(liste: list[str]) -> set[tuple[str, ...]]:
    return {tuple(liste[i:i + TAILLE_GRAMME]) for i in range(len(liste) - TAILLE_GRAMME + 1)}


def _noms_de_marque(c: Concurrent) -> list[tuple[str, str]]:
    """(forme recherchée, nature) : le nom d'affichage, son étiquette de domaine et chaque hôte déclaré."""
    formes = [(" ".join(mots(c.nom_affiche)), "nom")]
    for hote in c.hotes():
        formes.append((hote, "domaine"))
        racine = mots(hote.split(".")[0].replace("-", " "))
        if len(racine) >= 2:  # une étiquette à un seul mot est trop courante : seul le nom d'affichage la protège
            formes.append((" ".join(racine), "marque"))
    return [(f, n) for f, n in formes if f]


def _contient(texte_plie: str, forme: str) -> bool:
    return re.search(r"(?<![a-z0-9])" + re.escape(forme) + r"(?![a-z0-9])", texte_plie) is not None


def texte_observe(obs: Mapping[str, Any]) -> str:
    return " ".join(filter(None, [obs.get("titre"), obs.get("description_meta"), *obs.get("h1", [])]))


def controler_texte_propose(texte: Any, concurrents: Iterable[Concurrent],
                            observations: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """`{accepte, refus, mentions, recouvrement}`. Les concurrents passés sont tous ceux que le client a déclarés
    (actifs ou
    retirés : le nom d'un concurrent retiré ne devient pas libre pour autant)."""
    if not isinstance(texte, str) or not texte.strip() or len(texte) > 20_000:
        return {"accepte": False, "refus": [{"code": "REJ-VEILLE-ARGUMENT-INVALIDE", "chemin": "$.texte",
                                             "detail": "texte de 1 à 20 000 caractères attendu"}],
                "mentions": [], "recouvrement": {}}
    plie = plier(texte)
    plie_mots = " ".join(mots(texte))
    refus: list[dict[str, str]] = []
    liste_concurrents = list(concurrents)
    for c in liste_concurrents:
        for forme, nature in _noms_de_marque(c):
            if _contient(plie if nature == "domaine" else plie_mots, forme):
                refus.append({"code": "REJ-VEILLE-MARQUE-CONCURRENT", "chemin": "$.texte",
                              "detail": f"{_LIBELLES[nature]} du concurrent {c.concurrent_id} apparaît dans le texte : "
                              "ni imitation de marque, ni comparaison nommée"})
                break
    mes_grammes = _grammes(mots(texte))
    recouvrement: dict[str, str] = {}
    par_concurrent: dict[str, set[tuple[str, ...]]] = {}
    for obs in observations:
        par_concurrent.setdefault(obs["concurrent_id"], set()).update(_grammes(mots(texte_observe(obs))))
    for concurrent_id in sorted(par_concurrent):
        if not mes_grammes:
            break
        part = len(mes_grammes & par_concurrent[concurrent_id]) / len(mes_grammes)
        recouvrement[concurrent_id] = f"{part:.4f}"
        if part >= SEUIL_COPIE:
            refus.append({"code": "REJ-VEILLE-COPIE", "chemin": "$.texte",
                          "detail": f"{part:.0%} des suites de {TAILLE_GRAMME} mots recouvrent un texte observé du "
                          f"concurrent {concurrent_id} (seuil {SEUIL_COPIE:.0%})"})
    mentions = [MENTION_COMPARATIVE] if _COMPARATIF.search(plie) else []
    return {"accepte": not refus, "refus": refus, "mentions": mentions, "recouvrement": recouvrement}


__all__ = ["MENTION_COMPARATIVE", "SEUIL_COPIE", "controler_texte_propose", "mots", "plier", "texte_observe"]
