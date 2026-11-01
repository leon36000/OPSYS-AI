"""Couche d'adaptation des outils de Mnémo : connexion ambiante, horloge du serveur, droits de lecture, sortie bornée.

- L'**instant** est celui du serveur, jamais un argument d'un modèle ; les tests remplacent `maintenant`.
- **Aucune lecture ni écriture n'est ouverte à un appareil** (`roles_appareil` vide sur tous les outils de Mnémo) ; si
  un appel arrive tout de même avec une identité d'appareil, il est refusé ici (défense en profondeur).
- Le **département appelant** est fixé par la plateforme (`contexte.DEPARTEMENT_APPELANT`), jamais un argument.
- La **sortie est bornée** : le répartiteur tronque au-delà de 6 000 caractères et range le reste en artefact ; on
  borne ici, par éléments ENTIERS, pour ne jamais couper une provenance en deux, et on dit combien d'éléments manquent.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import Connection

from .. import stockage
from ..contexte import DEPARTEMENT_APPELANT, identite_appelante
from . import codes
from .codes import ErreurMnemo

SORTIE_MAX = 5700
_DEPARTEMENT = re.compile(r"^m(0[1-9]|10)-[a-z][a-z0-9-]*$")


def maintenant() -> dt.datetime:
    """L'horloge du serveur (jamais une date fournie par le modèle). Les tests la remplacent."""
    return dt.datetime.now(dt.UTC)


def instant_iso(instant: dt.datetime) -> str:
    return instant.astimezone(dt.UTC).isoformat()


def refuser_appareil() -> None:
    if identite_appelante() is not None:
        raise ErreurMnemo(
            codes.APPAREIL_FERME, "le modèle de soi, le graphe et les leçons ne sont pas ouverts aux appareils"
        )


def connexion() -> Connection:
    refuser_appareil()
    cnx = stockage.connexion_courante()
    if cnx is None:
        raise ErreurMnemo(codes.APPELANT_INCONNU, "aucune transaction de l'instance : appel hors répartiteur refusé")
    return cnx


def departement_appelant() -> str:
    ident = DEPARTEMENT_APPELANT.get()
    if not ident or not _DEPARTEMENT.fullmatch(ident):
        raise ErreurMnemo(
            codes.APPELANT_INCONNU,
            "département appelant inconnu : cet outil passe par le point d'accès MCP d'un département",
        )
    return ident


class Lecture:
    """Adaptateur en lecture seule d'un registre durable (`stockage.maillons`) : n'offre que `lire()`."""

    def __init__(self, maillons: Any) -> None:
        self._maillons = maillons

    def lire(self) -> list[dict[str, Any]]:
        return list(self._maillons)


def borner(reponse: Mapping[str, Any], cles: Sequence[str], maximum: int = SORTIE_MAX) -> dict[str, Any]:
    """Retire des éléments ENTIERS (toujours les derniers de la liste la plus longue parmi `cles`) jusqu'à tenir sous
    `maximum` caractères ; `omis_budget` dit combien."""
    sortie = dict(reponse)
    for c in cles:
        sortie[c] = list(sortie.get(c) or [])
    omis = 0
    while len(json.dumps({**sortie, "omis_budget": omis}, ensure_ascii=False, default=str)) > maximum:
        plus_longue = max(cles, key=lambda c: len(sortie[c]))
        if not sortie[plus_longue]:
            sortie["avertissements"] = [
                *sortie.get("avertissements", []),
                {
                    "code": "SORTIE_TROP_VOLUMINEUSE",
                    "detail": "demande une réponse plus étroite (moins de sauts, une dimension)",
                },
            ]
            break
        sortie[plus_longue].pop()
        omis += 1
    if omis:
        sortie["omis_budget"] = omis
    return sortie
